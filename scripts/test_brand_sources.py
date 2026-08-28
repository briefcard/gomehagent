"""One domain is the WEBSITE. The rest are landing pages, read for facts only.

Some brands publish in more than one place — a campaign landing page, a
microsite, a one-page offer — and until this landed, every one of those was
invisible: harvest read the website alone, and a compliance scan reported a
clean brand while a banned phrase sat live on a landing page nobody had ever
enumerated.

The fix is NOT "a list of domains". The owner's constraint (2026-08-27) is the
whole design: branding, positioning and tone come from the website ONLY. A
landing page is written for one campaign, so a voice derived from one would
take the loudest month of the year as the brand's whole personality. So the
list has two roles with different read permissions, and what this suite exists
to prove is that the two never blur:

  · identity  (voice.gather, brand_theme)   reads the website, and only it
  · facts     (harvest, compliance.scan)    read every source, and say which

    python3 scripts/test_brand_sources.py
"""
from __future__ import annotations

import inspect
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'bs.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import (admin_ui, compliance, db, extract, harvest, kb,  # noqa: E402
                 kb_seed, systems, tenants, voice, web)

# No network, and no model: a suite whose value is determinism must not make a
# billable call because a developer happens to have a key exported.
extract.available = lambda: False

_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


SITE = "bacimilanousa.com"
LANDING = "spring.bacimilano.test"

# The website: enough pages that a naive "read the first N" would spend the
# whole budget here and never reach the landing site. That is the point of the
# round-robin, so the fixture has to be big enough to catch its absence — and
# every page has to carry real prose, because the crawler skips a page with
# under 200 characters of body text as not worth a reading.
_FILLER = ("Baci Milano has designed for the table since the studio opened, "
           "and the collections are built around colour rather than around "
           "occasion. Everything shown here is stocked in the United States "
           "and ships from the New Jersey warehouse. ")


def _page(unique: str) -> str:
    return f"<html><body><p>{unique}</p><p>{_FILLER}</p></body></html>"


SITE_PAGES = {
    f"https://{SITE}/pages/p{i}":
        _page(f"The {i} pieces in this collection are dishwasher safe to "
              f"70 degrees and are sold as a set.")
    for i in range(1, 26)}
SITE_PAGES[f"https://{SITE}/pages/about"] = _page(
    "Baci Milano tableware is stocked in 4 Four Seasons properties worldwide.")

# The landing page: two pages, one of which breaks a hard rule. Neither is
# reachable from the website's sitemap — that is what makes it a second source
# rather than a deep link.
LANDING_PAGES = {
    f"https://{LANDING}/offer": (
        "<html><body>"
        "<p>The spring set is handmade in Italy by 3 artisans.</p>"
        "<p>Every order over $95 ships free to the continental United "
        f"States.</p><p>{_FILLER}</p></body></html>"),
    f"https://{LANDING}/returns": _page(
        "Returns are accepted within 30 days of delivery, unopened."),
}


#: THE COMMONEST LANDING PAGE THERE IS: a path on the client's own domain,
#: absent from the sitemap above. Before 2026-08-28 it could not even be
#: ADDED (dedupe was by host, so it collided with the website) and, once
#: added, discovery asked for `/pages/spring-lp/sitemap.xml` and gave up.
LP_PATH = f"https://{SITE}/pages/spring-lp"
PATH_PAGES = {
    LP_PATH: (
        "<html><body><h1>The Spring Set</h1>"
        "<p>The spring set ships within 2 working days, and every order "
        "travels insured with a tracking number.</p>"
        "<p>Every piece is hand-decorated in Milan by our artisans.</p>"
        f"<p>{_FILLER}</p></body></html>"),
}


def _sitemap(urls) -> str:
    return ('<?xml version="1.0"?><urlset>'
            + "".join(f"<url><loc>{u}</loc><lastmod>2026-08-11</lastmod></url>"
                      for u in urls)
            + "</urlset>")


class _Resp:
    #: `url` because a real httpx response has one and `_one_page` reads it to
    #: learn where a redirect landed. A stub missing a field the code under
    #: test reads is the same defect as the voice panel's stub that used a key
    #: `propose` never returns — the suite passes and the page is broken.
    def __init__(self, text, code=200, url=""):
        self.text, self.status_code, self.url = text, code, url


#: Every URL this suite's stub was asked for, in order — the only way to prove
#: a negative like "the voice deriver never touched the landing page".
FETCHED: list[str] = []


def _fake_get(url, **kw):
    FETCHED.append(url)
    if url == f"https://{SITE}/sitemap.xml":
        return _Resp(_sitemap(SITE_PAGES))
    if url == f"https://{LANDING}/sitemap.xml":
        return _Resp(_sitemap(LANDING_PAGES))
    for bag in (SITE_PAGES, LANDING_PAGES, PATH_PAGES):
        if url in bag:
            return _Resp(bag[url], url=url)
    return _Resp("", 404, url=url)


def main() -> int:
    db.init_db()
    tenants.seed()
    kb_seed.seed_all()
    systems.seed_from_tenants()

    import httpx
    httpx.get = _fake_get

    # ---- 1. the list itself: one website, N landing pages -----------------
    print("— what a source list is —")
    only_site = tenants.content_sources("baci")
    ck("with nothing added, the account has exactly one source",
       len(only_site) == 1, str(only_site))
    ck("and it is the website, in the first position",
       only_site[0]["role"] == "website"
       and only_site[0]["url"] == SITE, str(only_site[0]))

    res = tenants.set_sources("baci", [
        {"url": f"https://{LANDING}", "label": "Spring landing page"},
        {"url": f"https://{LANDING}/", "label": "the same site again"},
        {"url": f"www.{SITE}", "label": "the website, wearing a www"},
    ])
    srcs = tenants.content_sources("baci")
    ck("a landing page is recorded", len(srcs) == 2, str(srcs))
    ck("the website is still first — a caller reading [0] gets identity",
       srcs[0]["role"] == "website")
    ck("the same site written twice is one source, not two",
       sum(1 for x in srcs if x["role"] == "landing_page") == 1)
    ck("the WEBSITE cannot be re-added as a landing page",
       not any(tenants._norm(x["url"]) == tenants._norm(SITE)
               for x in srcs if x["role"] == "landing_page"))
    ck("and the refusal SAYS SO rather than silently dropping the row",
       "website itself" in (res.get("refused") or ""), str(res))

    # ---- 2. every finding can name the site it came from -------------------
    print("\n— which site a fact was read off —")
    ck("a landing-page URL answers with the landing page's own label",
       tenants.source_label("baci", f"https://{LANDING}/offer")
       == "Spring landing page")
    ck("a website URL answers with the website",
       tenants.source_label("baci", f"https://{SITE}/pages/about") == "Website")
    ck("an unrecognised host answers with the host, not a guess",
       tenants.source_label("baci", "https://someoneelse.test/x")
       == "someoneelse.test")

    # ---- 3. harvest reads EVERY source ------------------------------------
    print("\n— harvest —")
    out = harvest.harvest("baci", limit=8, apply=False)
    ck("the run reports one row per source", len(out.get("sources") or []) == 2,
       str([s["label"] for s in out.get("sources") or []]))
    labels = {s["label"]: s for s in out.get("sources") or []}
    ck("each row says how many pages that site enumerated",
       (labels.get("Website", {}).get("pages_found", 0) > 20
        and labels.get("Spring landing page", {}).get("pages_found", 0) == 2),
       str({k: v.get("pages_found") for k, v in labels.items()}))
    read_urls = {c["source"] for c in (out.get("proposed") or [])}
    ck("a fact is proposed off the LANDING PAGE, not only the website",
       any(LANDING in u for u in read_urls),
       str(sorted(read_urls))[:200])
    # The round-robin is the difference between a loop that VISITS every
    # source and one that REACHES it: the run above had a budget of 8 pages
    # against a website of 26, so a concatenated order would have spent all 8
    # on the website and read the landing site never — run after run, for
    # ever, which is the same defect the loop was added to fix.
    ck("and it got there on a budget smaller than the website alone",
       labels["Website"]["pages_found"] > 8 and any(LANDING in u
                                                    for u in read_urls),
       f"budget 8 vs {labels['Website']['pages_found']} website pages")
    ck("the website's own enumeration method is still reported as before",
       out.get("page_source") == "sitemap", str(out.get("page_source")))

    # ---- 4. the ban-list scan covers the landing pages ---------------------
    print("\n— the compliance scan —")
    scan = compliance.scan("baci", limit=40)
    hit_urls = [v["url"] for v in scan.get("violations") or []]
    ck("a banned phrase on a LANDING PAGE is a violation",
       any(LANDING in u for u in hit_urls), str(hit_urls))
    lp = [v for v in scan["violations"] if LANDING in v["url"]][0]
    ck("and the violation names WHICH SITE it is on",
       lp.get("site") == "Spring landing page", str(lp.get("site")))
    ck("the scan reports one row per site read",
       len(scan.get("sources") or []) == 2,
       str([s["label"] for s in scan.get("sources") or []]))
    ck("`domain` still means the website, so every existing reader survives",
       scan.get("domain") == SITE, str(scan.get("domain")))

    # ---- 5. THE CONSTRAINT: identity reads the website, and only it --------
    print("\n— voice is never derived from a landing page —")
    FETCHED.clear()
    texts, how = voice.gather("baci", limit=6)
    touched = [u for u in FETCHED if LANDING in u]
    ck("the voice deriver read the site", bool(texts), how)
    ck("and it touched the landing page ZERO times", not touched,
       f"fetched {touched[:3]}")
    ck("every page it read was on the website",
       all(SITE in u for u in FETCHED), str(FETCHED[:3]))

    from app import brand_theme
    src = inspect.getsource(brand_theme._from_site)
    ck("the brand-theme deriver still reads t.domain, not the source list",
       "t.domain" in src and "content_sources" not in src)
    vsrc = inspect.getsource(voice.gather)
    ck("and so does the voice gatherer",
       "t.domain" in vsrc and "content_sources" not in vsrc)

    # ---- 6. the console: the editor, and the claim card's Details fold -----
    print("\n— the Brand tab —")
    page = admin_ui.render_brand("s3cret", tenant="baci")
    ck("Brand carries the source editor", 'action="/admin/brand_sources"' in page)
    ck("the website field is labelled as the identity source",
       "the identity source" in page)
    ck("and the page states plainly that voice is never derived from a "
       "landing page", "Voice is never derived from a landing page" in page)
    ck("the landing page already on file is shown to be edited",
       "Spring landing page" in page)
    ck("with a way to remove it", 'name="lp_drop"' in page)

    from fastapi.testclient import TestClient
    c = TestClient(web.app, base_url="https://testserver")
    r = c.post("/admin/brand_sources",
               data={"key": "s3cret", "tenant": "baci", "website": SITE,
                     "lp_label": "Spring landing page",
                     "lp_url": f"https://{LANDING}",
                     "add_url": "https://autumn.bacimilano.test",
                     "add_label": "Autumn offer"},
               params={"key": "s3cret"}, follow_redirects=False)
    ck("saving lands back on the page, not on JSON", r.status_code == 303,
       str(r.status_code))
    ck("and back on the sources section it was submitted from",
       "#sources" in r.headers.get("location", ""), r.headers.get("location", ""))
    ck("the added landing page is on file",
       len(tenants.content_sources("baci")) == 3,
       str([s["label"] for s in tenants.content_sources("baci")]))

    r = c.post("/admin/brand_sources",
               data={"key": "s3cret", "tenant": "baci", "website": SITE,
                     "lp_label": ["Spring landing page", "Autumn offer"],
                     "lp_url": [f"https://{LANDING}",
                                "https://autumn.bacimilano.test"],
                     "lp_drop": "https://autumn.bacimilano.test"},
               params={"key": "s3cret"}, follow_redirects=False)
    left = [s["label"] for s in tenants.content_sources("baci")]
    ck("removing one takes exactly that one",
       left == ["Website", "Spring landing page"], str(left))

    # The Details fold names the site — but ONLY when there is more than one
    # to tell apart, because on a single-domain account "read off Website" on
    # every card is a fact stated once too often.
    tenants.set_sources("baci", [{"url": f"https://{LANDING}",
                                  "label": "Spring landing page"}])
    kb.add_claim("baci", "The spring set ships in 2 days.", "2 days",
                 ["gifting"], proof_type="data",
                 source=f"stated on https://{LANDING}/offer",
                 status="pending", origin="crawl")
    content = admin_ui.render_content("s3cret", tenant="baci", sub="claims")
    ck("the claim card's Details fold names the site it was read off",
       "read off Spring landing page" in content,
       "so a reviewer knows which page to go and fix")

    tenants.set_sources("baci", [])
    content1 = admin_ui.render_content("s3cret", tenant="baci", sub="claims")
    ck("with only a website, the card does NOT repeat it on every row",
       "read off Website" not in content1,
       "one site to tell apart is no site to tell apart")

    # ---- 5. A LANDING PAGE IS A PAGE (owner, 2026-08-28) ------------------
    #
    # "as long as the functionalities all work i.e. the scraper takes landing
    # pages and actually pulls the facts when a scrape is set up" — it did
    # not. Everything above this section passed while the feature did
    # nothing, because every check here was about STORING and NAMING a
    # source and none was about READING one. Proven against a real HTTP
    # server: `discover_pages` treated every source as a SITE, so given
    # `example.com/spring-offer` it asked for `/spring-offer/sitemap.xml`,
    # then wp-json under the path, then crawled the links OUT of the page —
    # and never fetched the page itself. A campaign landing page is
    # deliberately link-free, so the commonest landing page in the world
    # discovered exactly zero pages and its facts reached no queue.
    print("\n— a landing page is a PAGE, and its facts actually arrive —")
    from app import compliance as _comp
    found, how = _comp.discover_pages(LP_PATH, limit=50)
    ck("a source naming ONE PAGE is read as that page",
       len(found) == 1 and found[0]["url"] == LP_PATH,
       f"{how!r} {[f['url'] for f in found]}")
    ck("…and says so, rather than borrowing the website's method name",
       how == "landing page", how)
    ck("the fetched HTML rides along, so the reader does not re-request it",
       bool(found and found[0].get("html")))

    # THE WHOLE POINT: the facts on it arrive.
    tenants.set_sources("baci", [{"url": LP_PATH, "label": "Spring campaign"}])
    ck("a path on the website's own host can be ADDED at all",
       any(x["url"] == LP_PATH for x in tenants.content_sources("baci")),
       str(tenants.content_sources("baci")))
    from app import harvest as _hv
    out = _hv.harvest("baci", limit=60, apply=False, recrawl=True)
    props = out.get("proposed") or []
    # `text`, which is the key `harvest` actually returns — the first version
    # of this read `claim`, got "" for every row, and the ban-list assertion
    # below then passed against a list of empty strings. A check that reads a
    # key the producer does not write proves nothing, loudly and in green.
    ck("a proposal carries its sentence under the key harvest writes",
       all("text" in c for c in props), str(props[:1])[:160])
    claims = [str(c.get("text", "")) for c in props]
    ck("the landing page's facts are actually proposed",
       any("ships within 2 working days" in c for c in claims),
       str(claims)[:220])
    ck("…and the ban list still filters what it read",
       not any("hand-decorated" in c.lower() for c in claims), str(claims)[:220])
    rep = {r["label"]: r for r in (out.get("sources") or [])}
    ck("the per-source report counts the landing page's pages",
       rep.get("Spring campaign", {}).get("pages_found") == 1, str(rep)[:220])
    ck("a proposal records the landing page as its source",
       any(LP_PATH in str(c.get("source", ""))
           for c in (out.get("proposed") or [])),
       str([c.get("source") for c in (out.get("proposed") or [])])[:200])

    # And the ban-list scan sees a phrase that is live on it — the half of
    # this feature that is a compliance question, not a knowledge one.
    kb.add_banned("baci", "hand-decorated")
    sc = compliance.scan("baci", limit=60)
    hit = [v for v in (sc.get("violations") or []) if v.get("url") == LP_PATH]
    ck("the ban-list scan checks the landing page too",
       bool(hit), str(sc.get("violations"))[:220])
    ck("…and names WHICH source the live breach is on",
       bool(hit) and hit[0].get("site") == "Spring campaign", str(hit)[:200])

    # ---- 6. same host, different page ------------------------------------
    print("\n— the commonest landing page there is: a path on the site --")
    res6 = tenants.set_sources("baci", [
        {"url": f"https://{SITE}/pages/spring", "label": "Spring"},
        {"url": f"https://{SITE}/pages/summer", "label": "Summer"},
        {"url": f"https://www.{SITE}", "label": "the website, wearing a www"},
    ])
    srcs6 = tenants.content_sources("baci")
    lps6 = [x for x in srcs6 if x["role"] == "landing_page"]
    ck("a path on the website's own host IS a landing page — for a Shopify "
       "store it is the only kind they have",
       len(lps6) == 2, str(lps6))
    ck("two pages on ONE host are two sources, not one",
       {x["label"] for x in lps6} == {"Spring", "Summer"}, str(lps6))
    ck("the bare website is still refused, however it is written",
       "website itself" in (res6.get("refused") or ""), str(res6))
    ck("each page answers with ITS OWN label, not whichever came first",
       tenants.source_label("baci", f"https://{SITE}/pages/summer") == "Summer"
       and tenants.source_label("baci", f"https://{SITE}/pages/spring") == "Spring")
    ck("a page under a landing page belongs to that landing page",
       tenants.source_label("baci", f"https://{SITE}/pages/spring/checkout")
       == "Spring")
    ck("an ordinary website page still answers Website",
       tenants.source_label("baci", f"https://{SITE}/pages/about") == "Website")

    ck("the WEBSITE is stored as a bare host, so it is never reduced to one "
       "page by the landing-page branch",
       tenants.set_website("baci", "https://www.bacimilanousa.com/en/")
       .get("domain") == "bacimilanousa.com",
       str(tenants.set_website("baci", "https://www.bacimilanousa.com/en/")))
    tenants.set_website("baci", SITE)

    # ---- 7. a source that read nothing SAYS SO ----------------------------
    print("\n— absence is not an answer: an empty source is named —")
    from app.web import _summarise
    line = _summarise({"proposed_count": 12, "pages_read": 40, "sources": [
        {"label": "Website", "pages_found": 40},
        {"label": "Spring", "pages_found": 0}]})
    ck("a run that missed a source names it in the status line",
       "READ NOTHING: Spring" in line, line)
    ck("…and a run that missed nothing stays quiet",
       "READ NOTHING" not in _summarise(
           {"proposed_count": 12, "sources": [{"label": "Website",
                                               "pages_found": 40}]}))
    import json as _json
    with db.SessionLocal() as _s:
        _s.merge(db.Setting(key="bg:harvest:baci", value=_json.dumps(
            {"state": "done", "detail": line, "at": "2026-08-28T16:40:00"})))
        _s.commit()
    brand_page = admin_ui.render_brand("s3cret", "baci")
    ck("the Brand tab says it beside the source list it is about",
       "read nothing: Spring" in brand_page)

    # ── a run reports what it LOST, not only what it gained (2026-08-28) ───
    #
    # Every one of these numbers was computed and none reached a surface:
    # `_summarise` kept the gains and dropped the losses, so a harvest that
    # proposed twelve claims and REFUSED TO WRITE FIVE reported "12" and
    # nothing else — while `harvest`'s own source says "these are different
    # numbers and conflating them hid a whole class of loss". It hid it in the
    # status line. Guard: `a_run_says_what_it_lost`.
    lost = _summarise({
        "proposed_count": 12, "pages_read": 40,
        "write_refused_count": 5,
        "write_refused": [{"claim": "Hand-decorated in Milan",
                           "why": "banned phrase"}],
        "rejected_for_banned_claim": ["a", "b"],
        "pages_skipped": 1,
        "dropped_by_reason": {"no proof": 3, "too long": 1}})
    ck("a run names what it REFUSED TO WRITE, not only what it proposed",
       "5 writes refused" in lost, lost)
    ck("…and what the ban list stopped", "2 rejected for a banned claim" in lost)
    ck("…and the reasons lead, most common first",
       "3 no proof, 1 too long" in lost, lost)
    ck("…and one real instance, so the count is actionable",
       "Hand-decorated in Milan (banned phrase)" in lost, lost)
    ck("singular stays singular — 1 page skipped, not 1 pages",
       "1 page skipped" in lost, lost)
    ck("a clean run stays QUIET, or the loud ones stop being read",
       "LOST" not in _summarise({"proposed_count": 12, "pages_read": 40}))
    ck("…and carries the control that re-runs it (rule 1), so the fix is not "
       "an instruction to go somewhere else",
       "/admin/harvest" in brand_page and "/admin/compliance_scan" in brand_page)

    print()
    if _fail:
        print(f"{len(_fail)} FAILED: {', '.join(_fail)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
