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


def _sitemap(urls) -> str:
    return ('<?xml version="1.0"?><urlset>'
            + "".join(f"<url><loc>{u}</loc><lastmod>2026-08-11</lastmod></url>"
                      for u in urls)
            + "</urlset>")


class _Resp:
    def __init__(self, text, code=200):
        self.text, self.status_code = text, code


#: Every URL this suite's stub was asked for, in order — the only way to prove
#: a negative like "the voice deriver never touched the landing page".
FETCHED: list[str] = []


def _fake_get(url, **kw):
    FETCHED.append(url)
    if url == f"https://{SITE}/sitemap.xml":
        return _Resp(_sitemap(SITE_PAGES))
    if url == f"https://{LANDING}/sitemap.xml":
        return _Resp(_sitemap(LANDING_PAGES))
    for bag in (SITE_PAGES, LANDING_PAGES):
        if url in bag:
            return _Resp(bag[url])
    return _Resp("", 404)


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

    print()
    if _fail:
        print(f"{len(_fail)} FAILED: {', '.join(_fail)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
