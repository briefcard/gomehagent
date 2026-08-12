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

_TAG = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)
_HTML = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")

# Pages that are never brand copy — checking them produces noise, not findings.
_SKIP = ("/cart", "/checkout", "/account", "/policies/", "/wp-json",
         "/feed", ".xml", ".json", ".pdf", "/search")


def _clean(html: str) -> str:
    return _WS.sub(" ", _HTML.sub(" ", _TAG.sub(" ", html or ""))).strip()


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

    def _fetch(url: str) -> str:
        try:
            r = httpx.get(url, timeout=25, follow_redirects=True)
            return r.text if r.status_code == 200 else ""
        except Exception:  # noqa: BLE001
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

    root = _fetch(f"{base}/sitemap.xml") or _fetch(f"{base}/sitemap_index.xml")
    if not root:
        return []
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


def check_page(tenant: str, url: str) -> dict:
    """Fetch one page and check its visible text against the account's rules."""
    import httpx
    try:
        r = httpx.get(url, timeout=25, follow_redirects=True)
        if r.status_code != 200:
            return {"url": url, "status": f"HTTP {r.status_code}", "phrases": []}
        text = _clean(r.text)
    except Exception as exc:  # noqa: BLE001
        return {"url": url, "status": exc.__class__.__name__, "phrases": []}

    low = text.lower()
    hits = []
    for phrase in kb.banned_claims(tenant):
        if not phrase:
            continue
        at = low.find(phrase.lower())
        if at >= 0:
            hits.append({"phrase": phrase,
                         "context": text[max(0, at - 60):at + len(phrase) + 60].strip()})
    return {"url": url, "status": "ok", "phrases": hits,
            "words": len(text.split())}


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

    pages = _sitemap_urls(t.domain, limit=max(limit * 4, 200))
    if not pages:
        return {"error": f"no sitemap found at {t.domain} — cannot enumerate "
                         f"pages for this platform yet"}

    considered = [p for p in pages
                  if not since or not p["lastmod"] or p["lastmod"][:10] >= since]
    checked, violations, errors = [], [], []
    for p in considered[:limit]:
        res = check_page(tenant, p["url"])
        if res["status"] != "ok":
            errors.append({"url": res["url"], "status": res["status"]})
            continue
        checked.append(res["url"])
        if res["phrases"]:
            violations.append({"url": res["url"], "lastmod": p["lastmod"],
                               "hits": res["phrases"]})

    by_phrase: dict[str, int] = {}
    for v in violations:
        for h in v["hits"]:
            by_phrase[h["phrase"]] = by_phrase.get(h["phrase"], 0) + 1

    return {
        "tenant": tenant, "domain": t.domain,
        "rules_checked": len(rules),
        "pages_in_sitemap": len(pages),
        "pages_checked": len(checked),
        "pages_skipped_unchanged": len(pages) - len(considered),
        "violations": violations,
        "by_phrase": sorted(by_phrase.items(), key=lambda kv: -kv[1]),
        "fetch_errors": errors[:10],
        "note": ("Each violation is a live page using a phrase this brand has "
                 "banned. Nothing is rewritten — the URL and the surrounding "
                 "sentence are what make it fixable."),
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
        systems.finish_run(run_id, "sent", outcome={
            "pages_checked": result["pages_checked"],
            "violations": len(result["violations"]),
            "by_phrase": dict(result["by_phrase"]),
        })
    return run_id
