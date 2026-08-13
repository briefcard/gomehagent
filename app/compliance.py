"""Website content compliance — is the live site saying what the brand allows?

The knowledge base has held each account's `banned_claims` since it was built,
and enforced them only at the moment something was drafted. The site itself was
never checked. Baci's ban on "made in Italy" exists precisely because that
phrasing is a legal and factual problem — and nothing had ever looked at whether
the storefront already says it.

Three page sources, because the clients are on three platforms:

  * **Shopify**  — the Admin API, product by product (`catalog_sync` does this
    on the same pass it fills the catalogue).
  * **WordPress** — `wp-json`, when the application password is connected.
  * **Anything, including Squarespace** — `sitemap.xml`. Squarespace has no
    usable publishing API, so the sitemap is the only complete list of what is
    public. It also carries `lastmod`, which answers "what changed since we last
    looked" without needing Search Console at all.

What this does NOT do yet is fix anything. Detection first: a list of URLs and
the exact phrase on each is immediately actionable, and an auto-rewrite that
nobody has read is the thing this whole platform is built to avoid.
"""
from __future__ import annotations

import re

from . import db, kb, tenants

# Identify ourselves honestly on every fetch. The default `python-httpx/…`
# agent is 403'd by ordinary WAF rules — marketingthatworks.co returns 403 to
# it and 200 to a named agent — so a site the owner controls looked unreadable
# when it was only unlabelled. This says who is asking and why rather than
# pretending to be a browser.
UA = ("SaiasOpsBot/1.0 (+content-compliance; first-party check of a site we "
      "operate; contact gomehsaias@gmail.com)")
HEADERS = {"User-Agent": UA}


_TAG = re.compile(r"<(script|style|noscript|svg|template)[^>]*>.*?</\1>", re.S | re.I)
# Page furniture. Present on every page, identical every time, and none of it is
# brand copy — a banned word in a menu link is not the site making a claim, and
# a nav item is not a candidate for the proof library.
_FURNITURE = re.compile(
    r"<(nav|header|footer|aside|form|button|select)[^>]*>.*?</\1>", re.S | re.I)
# The body of the page, when the markup says where it is.
_MAIN = re.compile(r"<(?:main|article)[^>]*>(.*?)</(?:main|article)>", re.S | re.I)
_HTML = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)

# Pages that are never brand copy — reading them produces noise, not findings.
#
# The additions past the first line are all things a real crawl brought back:
# WordPress' default "Sample Page", tag and author archives that restate other
# pages' copy, pagination, and error pages that a site serves with a 200.
_SKIP = ("/cart", "/checkout", "/account", "/policies/", "/wp-json",
         "/feed", ".xml", ".json", ".pdf", "/search",
         "/sample-page", "/wp-admin", "/wp-content", "/wp-includes",
         "/404", "/error", "/not-found", "/thank-you", "/thanks",
         "/tag/", "/category/", "/author/", "/page/", "?s=", "?p=",
         "/privacy", "/terms", "/cookie", "/legal", "/disclaimer",
         "/login", "/register", "/cdn-cgi/")

# A page whose title says it is an error, whatever status code it was served
# with. Squarespace and plenty of WordPress themes return 200 on a missing page.
_DEAD_TITLE = re.compile(
    r"\b(404|403|not found|page not found|error|oops|nothing here|"
    r"sample page|coming soon|under construction|untitled)\b", re.I)


def skip_url(url: str) -> bool:
    return any(s in (url or "").lower() for s in _SKIP)


def page_title(html: str) -> str:
    m = _TITLE.search(html or "")
    return _clean(m.group(1)) if m else ""


def is_dead_page(html: str, text: str | None = None,
                 min_chars: int = 0) -> str:
    """Why this page is not worth reading, or "" if it is.

    Returns the reason rather than a bool so a report can say which pages were
    skipped and why — "enumerated 400, read 240" with no explanation is the
    kind of silent narrowing this codebase treats as a defect.

    `min_chars` defaults to 0 because the two callers want different things.
    Compliance must read a thin page: a two-line page can still say "handmade
    in Italy", and skipping it would report a clean site that is not clean.
    Harvest passes a real threshold, because a page with no prose on it has no
    claim on it either.
    """
    title = page_title(html)
    if _DEAD_TITLE.search(title):
        return f"title reads as an error or placeholder: {title[:60]!r}"
    body = _clean(html) if text is None else text
    if len(body) < min_chars:
        return f"almost no text on the page ({len(body)} chars)"
    return ""


def _clean(html_text: str) -> str:
    """Readable prose from a page: the body, without the furniture, unescaped.

    Two defects, both of which reached the review queue:

    1. **Furniture was kept.** Stripping tags but not nav/header/footer meant
       candidates came back as `"Book a 25-min intro Start the intake ..."` and
       a banned word in a menu link was reported as a claim the site makes.

    2. **Entities were never decoded**, so `isn&#8217;t` survived into the
       text. That is not only ugly in the queue — harvest's "a claim carries a
       number" filter is what decides a sentence is checkable, and `8217`
       is a number. Every curly apostrophe on the page was manufacturing
       evidence, which is most of why the proposals were junk.

    Unescape happens AFTER tags are stripped. The other order turns an escaped
    `&lt;script&gt;` in the copy into something that looks like markup.
    """
    import html as _htmllib

    raw = html_text or ""
    raw = _TAG.sub(" ", raw)
    body = _MAIN.search(raw)
    if body:
        raw = body.group(1)          # the markup told us where the content is
    raw = _FURNITURE.sub(" ", raw)
    return _WS.sub(" ", _htmllib.unescape(_HTML.sub(" ", raw))).strip()


def _sitemap_urls(base: str, limit: int = 300) -> list[dict]:
    """Every public URL, from sitemap.xml, following index files one level.

    Returns `lastmod` where the sitemap gives it, so a later run can check only
    what changed. This is the universal path: every platform publishes one, and
    for Squarespace it is the only complete list that exists.
    """
    import httpx
    base = base.rstrip("/")
    if not base.startswith("http"):
        base = "https://" + base
    out: list[dict] = []
    seen: set[str] = set()

    problems: list[str] = []

    def _fetch(url: str) -> str:
        """Fetch, recording WHY a failure happened.

        Swallowing every exception into "" made a TLS misconfiguration look
        identical to a site with no sitemap — www.coveringsetc.com serves a
        certificate without its intermediate, which curl tolerates via the
        system store and most libraries do not. Reporting that as "no sitemap
        found" sends you looking in the wrong place, and it is the
        absence-collapsed-into-a-value pattern in a diagnostic.
        """
        try:
            r = httpx.get(url, timeout=25, follow_redirects=True, headers=HEADERS)
            return r.text if r.status_code == 200 else ""
        except Exception as exc:  # noqa: BLE001
            name = exc.__class__.__name__
            detail = str(exc)[:120]
            if "CERTIFICATE_VERIFY_FAILED" in detail:
                detail = ("TLS certificate chain is incomplete — the server is "
                          "not sending its intermediate certificate")
            problems.append(f"{url}: {name} — {detail}")
            return ""

    def _parse(xml: str) -> tuple[list[str], list[dict]]:
        maps = re.findall(r"<sitemap>.*?<loc>(.*?)</loc>.*?</sitemap>", xml, re.S | re.I)
        urls = []
        for block in re.findall(r"<url>(.*?)</url>", xml, re.S | re.I):
            loc = re.search(r"<loc>(.*?)</loc>", block, re.I)
            mod = re.search(r"<lastmod>(.*?)</lastmod>", block, re.I)
            if loc:
                urls.append({"url": loc.group(1).strip(),
                             "lastmod": (mod.group(1).strip() if mod else "")})
        return maps, urls

    # Try both hosts. A tenant's domain is recorded without www, and plenty of
    # sites canonicalise TO www and serve a plain 404 on the apex rather than
    # redirecting — coveringsetc.com/sitemap.xml is a 404 while
    # www.coveringsetc.com/sitemap.xml is a 200.
    host = base.split("://", 1)[1]
    hosts = [base]
    alt = host[4:] if host.startswith("www.") else "www." + host
    hosts.append(base.split("://", 1)[0] + "://" + alt)

    # robots.txt is where a site DECLARES its sitemap, and it is the only
    # discovery method that does not require knowing the platform. Guessing
    # paths found Shopify and Squarespace and missed WordPress, which publishes
    # /wp-sitemap.xml.
    candidates: list[str] = []
    for h in hosts:
        for line in _fetch(f"{h}/robots.txt").splitlines():
            if line.lower().startswith("sitemap:"):
                loc = line.split(":", 1)[1].strip()
                if loc:
                    candidates.append(loc)
    for h in hosts:
        candidates += [f"{h}/sitemap.xml", f"{h}/sitemap_index.xml",
                       f"{h}/wp-sitemap.xml", f"{h}/sitemap-index.xml"]

    root = ""
    for cand in candidates:
        root = _fetch(cand)
        if root and "<" in root:
            break
    if not root:
        _sitemap_urls.last_problems = problems[:4]
        return []
    _sitemap_urls.last_problems = []
    children, urls = _parse(root)
    for child in children[:12]:            # a sitemap index, one level deep
        if len(out) + len(urls) >= limit:
            break
        _, more = _parse(_fetch(child))
        urls += more
    for u in urls:
        loc = u["url"]
        if loc in seen or any(s in loc.lower() for s in _SKIP):
            continue
        seen.add(loc)
        out.append(u)
        if len(out) >= limit:
            break
    return out


def _hosts(base: str) -> list[str]:
    base = base.rstrip("/")
    if not base.startswith("http"):
        base = "https://" + base
    host = base.split("://", 1)[1]
    alt = host[4:] if host.startswith("www.") else "www." + host
    return [base, base.split("://", 1)[0] + "://" + alt]


def _wp_json_urls(base: str, limit: int = 300) -> list[dict]:
    """Pages and posts from the WordPress REST API.

    WordPress exposes published content over wp-json without authentication, so
    a site with sitemaps switched off is still fully enumerable — which
    marketingthatworks.co is, despite /sitemap.xml redirecting to a
    /wp-sitemap.xml that 404s.
    """
    import httpx
    out: list[dict] = []
    for host in _hosts(base):
        for kind in ("pages", "posts"):
            try:
                r = httpx.get(
                    f"{host}/wp-json/wp/v2/{kind}",
                    params={"per_page": 50,
                            "_fields": "link,modified,title,content"},
                    timeout=40, follow_redirects=True, headers=HEADERS)
                if r.status_code != 200:
                    continue
                for item in r.json():
                    link = item.get("link") or ""
                    if not link or any(s in link.lower() for s in _SKIP):
                        continue
                    # Take the CONTENT here too. marketingthatworks.co answers
                    # the API with 200 and every HTML page with 403 — a WAF
                    # being stricter about page views than about its own API.
                    # Reading what the site publishes beats working around what
                    # it blocks, and it is one request instead of fifty.
                    body = (item.get("content") or {}).get("rendered", "")
                    title = (item.get("title") or {}).get("rendered", "")
                    out.append({"url": link,
                                "lastmod": (item.get("modified") or "")[:10],
                                "html": f"<h1>{title}</h1>{body}"[:400_000]})
            except Exception:  # noqa: BLE001 — not a WordPress site, or blocked
                continue
        if out:
            break
    seen, uniq = set(), []
    for u in out:
        if u["url"] not in seen:
            seen.add(u["url"])
            uniq.append(u)
    return uniq[:limit]


def _crawl_urls(base: str, limit: int = 60) -> list[dict]:
    """Last resort: internal links from the homepage.

    Not a complete picture of a site and does not pretend to be — but "some of
    the pages" beats "we could not look", and the pages linked from a homepage
    are the ones carrying brand copy anyway.
    """
    import httpx
    for host in _hosts(base):
        try:
            r = httpx.get(host, timeout=25, follow_redirects=True,
                          headers=HEADERS)
            if r.status_code != 200:
                continue
        except Exception:  # noqa: BLE001
            continue
        root = str(r.url).rstrip("/")
        found, seen = [], set()
        for href in re.findall(r'href=["\']([^"\'#?]+)', r.text):
            if href.startswith("//") or href.startswith("mailto:"):
                continue
            url = (root + href if href.startswith("/")
                   else href if href.startswith(root) else "")
            if not url or url in seen or any(s in url.lower() for s in _SKIP):
                continue
            seen.add(url)
            found.append({"url": url, "lastmod": ""})
            if len(found) >= limit:
                break
        if found:
            return found
    return []


def discover_pages(base: str, limit: int = 300) -> tuple[list[dict], str]:
    """Every public page, by whichever method this site supports.

    Sitemap first — it is complete and carries lastmod, which is what makes a
    repeat scan cheap. Then the WordPress API. Then the homepage. Returns the
    source alongside the pages, because "40 pages via homepage crawl" and "400
    pages via sitemap" are very different levels of confidence in a clean scan.
    """
    pages = _sitemap_urls(base, limit=limit)
    if pages:
        return pages, "sitemap"
    problems = list(getattr(_sitemap_urls, "last_problems", []))
    pages = _wp_json_urls(base, limit=limit)
    if pages:
        return pages, "wordpress api"
    pages = _crawl_urls(base, limit=min(limit, 60))
    if pages:
        return pages, "homepage crawl"
    discover_pages.last_problems = problems
    return [], ""


def check_page(tenant: str, url: str, html: str = "") -> dict:
    """Check one page. Uses `html` when discovery already supplied it."""
    import httpx
    if html:
        text = _clean(html)
    else:
        try:
            r = httpx.get(url, timeout=25, follow_redirects=True, headers=HEADERS)
            if r.status_code != 200:
                return {"url": url, "status": f"HTTP {r.status_code}",
                        "phrases": [], "questions": []}
            text = _clean(r.text)
        except Exception as exc:  # noqa: BLE001
            return {"url": url, "status": exc.__class__.__name__,
                    "phrases": [], "questions": []}

    hits, questions = _match(tenant, text)
    return {"url": url, "status": "ok", "phrases": hits,
            "questions": questions, "words": len(text.split())}


_SENT = re.compile(r"(?<=[.!?])\s+")


def _match(tenant: str, text: str) -> tuple[list[dict], list[dict]]:
    """Find banned phrases, separating assertions from questions about them.

    Run against Baci's live site, a naive substring match flagged 15 of 26
    pages — and almost all of them were one FAQ entry reading *"Is it made in
    Italy? Baci Milano is an Italian design house — this piece is …"*, which is
    the compliant answer to the question, not a breach of it.

    A checker with that false-positive rate is worse than none, because it stops
    being read. So a phrase inside an interrogative sentence is reported
    separately as something to eyeball rather than as a violation — and the
    context is the whole sentence rather than a character window, because
    "…t is shatterproof and suited to indoor & outdoor use. Is it made in…"
    cannot be judged without opening the page, which defeats the point.
    """
    sentences = [s.strip() for s in _SENT.split(text or "") if s.strip()]
    hits: list[dict] = []
    questions: list[dict] = []
    for phrase in kb.banned_claims(tenant):
        if not phrase:
            continue
        low_p = phrase.lower()
        for sent in sentences:
            if low_p not in sent.lower():
                continue
            # Centre the window on the phrase. A care matrix renders as one
            # 900-character "sentence", so taking the first 300 showed a table
            # header and not the words that were flagged.
            if len(sent) > 300:
                at = sent.lower().find(low_p)
                start = max(0, at - 120)
                snip = ("…" if start else "") + sent[start:at + len(phrase) + 120] + "…"
            else:
                snip = sent
            entry = {"phrase": phrase, "context": snip}
            if sent.rstrip().endswith("?"):
                questions.append(entry)
            else:
                hits.append(entry)
            break          # one example per phrase is enough to act on
    return hits, questions


def scan(tenant: str, limit: int = 60, since: str = "") -> dict:
    """Check a client's live site against its own rules.

    `since` is an ISO date: only pages the sitemap reports as modified on or
    after it are fetched. That is what makes this cheap enough to run on a
    schedule — a full site is checked once, and after that only what changed.
    """
    t = tenants.get(tenant)
    if not t:
        return {"error": f"unknown tenant {tenant!r}"}
    if not t.domain:
        return {"error": f"{tenant} has no domain recorded"}
    rules = kb.banned_claims(tenant)
    if not rules:
        return {"error": f"{tenant} has no banned_claims — nothing to check "
                         f"against. Add them before scanning."}

    pages, source = discover_pages(t.domain, limit=max(limit * 4, 200))
    if not pages:
        why = getattr(discover_pages, "last_problems", [])
        if why:
            return {"error": f"could not reach {t.domain}", "detail": why,
                    "note": "This is a connection problem, not a missing "
                            "sitemap. Fix the site before reading anything "
                            "into a clean scan."}
        return {"error": f"could not enumerate any pages at {t.domain} — no "
                         f"sitemap, no WordPress API, and no links found on the "
                         f"homepage"}

    considered = [p for p in pages
                  if not since or not p["lastmod"] or p["lastmod"][:10] >= since]
    checked, violations, errors, to_review = [], [], [], []
    for p in considered[:limit]:
        res = check_page(tenant, p["url"], html=p.get("html", ""))
        if res["status"] != "ok":
            errors.append({"url": res["url"], "status": res["status"]})
            continue
        checked.append(res["url"])
        if res["phrases"]:
            violations.append({"url": res["url"], "lastmod": p["lastmod"],
                               "hits": res["phrases"]})
        if res.get("questions"):
            to_review.append({"url": res["url"],
                              "hits": res["questions"]})

    by_phrase: dict[str, int] = {}
    for v in violations:
        for h in v["hits"]:
            by_phrase[h["phrase"]] = by_phrase.get(h["phrase"], 0) + 1

    return {
        "tenant": tenant, "domain": t.domain, "page_source": source,
        "rules_checked": len(rules),
        "pages_in_sitemap": len(pages),
        "pages_checked": len(checked),
        "pages_skipped_unchanged": len(pages) - len(considered),
        "violations": violations,
        "questions_to_review": to_review[:20],
        "questions_count": len(to_review),
        "by_phrase": sorted(by_phrase.items(), key=lambda kv: -kv[1]),
        "fetch_errors": errors[:10],
        "note": ("Each violation is a live page using a phrase this brand has "
                 "banned, stated as a claim. `questions_to_review` are pages "
                 "where the phrase appears inside a question — usually an FAQ "
                 "answering it correctly — and are worth an eye, not a fix. "
                 "Nothing is rewritten."),
    }


def record_scan(tenant: str, result: dict) -> str:
    """Log a scan against the compliance system's ledger, if it is installed."""
    from . import systems
    row = systems.find(tenant, "content_compliance")
    if not row:
        return ""
    run_id = systems.start_run(row.id, tenant, trigger="schedule")
    if result.get("error"):
        systems.finish_run(run_id, "blocked", blocked_on=[result["error"]])
    else:
        # The findings themselves, not just the count. A scan whose detail only
        # existed in the response that triggered it would have to be re-run to
        # be read twice — and a list of URLs nobody can look at again is not a
        # report. Capped so one bad site cannot bloat the ledger row.
        systems.finish_run(run_id, "sent", outcome={
            "pages_checked": result["pages_checked"],
            "violations": len(result["violations"]),
            "by_phrase": dict(result["by_phrase"]),
            "detail": [{"url": v["url"],
                        "phrases": [h["phrase"] for h in v["hits"]],
                        "context": (v["hits"][0]["context"] if v["hits"] else "")[:220]}
                       for v in result["violations"][:40]],
            "truncated": max(0, len(result["violations"]) - 40),
        })
    return run_id


def purge_scans(tenant: str = "", dry_run: bool = True) -> dict:
    """Drop recorded compliance scans, so the tab stops showing a stale one.

    A scan taken before `_clean` unescaped entities and dropped page furniture
    reports findings against text the site never displayed — a banned word in a
    nav link, or a match inside `&#8217;`. Keeping it is worse than having no
    scan: the tab presents it with a timestamp and it reads as current.
    """
    from . import db as _db, systems
    hit = 0
    with _db.SessionLocal() as s:
        q = s.query(_db.SystemRun).join(
            _db.System, _db.System.id == _db.SystemRun.system_id).filter(
                _db.System.key == "content_compliance")
        if tenant:
            q = q.filter(_db.SystemRun.tenant == tenant)
        rows = q.all()
        hit = len(rows)
        if not dry_run:
            for r in rows:
                s.delete(r)
            s.commit()
    return {"tenant": tenant or "all", "dry_run": dry_run,
            "scans_cleared": hit,
            "note": ("Clears recorded scans only — no knowledge-base row is "
                     "touched. Re-run the scan to get a current one. "
                     "Pass dry_run=0 to actually delete.")}


def last_scan(tenant: str) -> dict:
    """The most recent scan for this account, or {}."""
    from . import db as _db, systems
    row = systems.find(tenant, "content_compliance")
    if not row:
        return {}
    runs = systems.runs(row.id, limit=1)
    if not runs:
        return {}
    r = runs[0]
    return {"at": _db.as_utc(r.created_at), "stage": r.stage,
            "blocked_on": r.blocked_on or [], **(r.outcome or {})}
