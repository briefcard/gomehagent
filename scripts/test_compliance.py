"""The live site is checked against the brand's own rules.

`banned_claims` were enforced at the moment something was drafted, and nowhere
else. Nothing had ever asked whether the storefront already says the thing.
Baci's ban on "made in Italy" exists because that phrasing is a factual and
legal problem — so the pages already using it are the first thing worth finding.

Pages come from sitemap.xml rather than a platform API, because the clients are
on Shopify, WordPress and Squarespace, and Squarespace has no usable publishing
API. Every platform publishes a sitemap, and its `lastmod` is what makes a
repeat scan cheap.

    python3 scripts/test_compliance.py
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'cp.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import compliance, db, kb, kb_seed, systems, tenants  # noqa: E402

_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


SITEMAP = """<?xml version="1.0"?><urlset>
  <url><loc>https://bacimilanousa.com/</loc><lastmod>2026-08-10</lastmod></url>
  <url><loc>https://bacimilanousa.com/pages/about</loc><lastmod>2026-08-11</lastmod></url>
  <url><loc>https://bacimilanousa.com/products/aqua</loc><lastmod>2026-01-02</lastmod></url>
  <url><loc>https://bacimilanousa.com/cart</loc><lastmod>2026-08-11</lastmod></url>
  <url><loc>https://bacimilanousa.com/sitemap_pages.xml</loc></url>
</urlset>"""

PAGES = {
    "https://bacimilanousa.com/": "<html><body><h1>Baci</h1>"
        "<p>Colourful Italian design for people who host.</p></body></html>",
    "https://bacimilanousa.com/pages/about": "<html><body>"
        "<script>var x='handmade';</script>"
        "<p>Every piece is handmade in Italy by our artisans.</p></body></html>",
    "https://bacimilanousa.com/products/aqua": "<html><body>"
        "<p>The Aqua set. Six pieces. Is it made in Italy? Baci Milano is an "
        "Italian design house and this piece is produced to its designs.</p>"
        "</body></html>",
}


class _Resp:
    def __init__(self, text, code=200):
        self.text, self.status_code = text, code


def _fake_get(url, **kw):
    if url.endswith("/sitemap.xml"):
        return _Resp(SITEMAP)
    if url in PAGES:
        return _Resp(PAGES[url])
    return _Resp("", 404)


def main() -> int:
    db.init_db()
    tenants.seed()
    kb_seed.seed_all()
    systems.seed_from_tenants()

    import httpx
    real_get = httpx.get
    httpx.get = _fake_get

    # ---- what it enumerates ----------------------------------------------
    print("— reading the sitemap —")
    urls = compliance._sitemap_urls("bacimilanousa.com")
    locs = [u["url"] for u in urls]
    ck("public pages are found", len(locs) == 3, str(locs))
    ck("the cart is not treated as brand copy",
       not any("/cart" in u for u in locs))
    ck("nested sitemaps are not checked as pages",
       not any(u.endswith(".xml") for u in locs))
    ck("lastmod is carried, so a repeat scan can skip what did not change",
       any(u["lastmod"] for u in urls))

    # ---- the scan ---------------------------------------------------------
    print("\n— the scan —")
    r = compliance.scan("baci", limit=40)
    ck("it checked the live pages", r["pages_checked"] == 3, str(r.get("pages_checked")))
    ck("it found the non-compliant page", len(r["violations"]) == 1,
       str([v["url"] for v in r["violations"]]))
    v = r["violations"][0]
    ck("and names it", v["url"].endswith("/pages/about"), v["url"])
    phrases = [h["phrase"].lower() for h in v["hits"]]
    ck("naming every rule it breaks",
       {"handmade", "artisan"} <= set(phrases), str(phrases))
    ck("with the sentence around it, so it is fixable without opening the page",
       "handmade in Italy" in v["hits"][0]["context"], v["hits"][0]["context"][:70])
    ck("compliant pages are not reported",
       not any(u["url"].endswith("/products/aqua") for u in r["violations"]))

    # ---- script tags are not page copy ------------------------------------
    ck("a banned word inside a <script> is not a violation",
       all("var x" not in h["context"] for h in v["hits"]),
       "stripping scripts stops false positives from analytics blobs")

    # ---- the false positive that made this worth fixing -------------------
    # Against the real site a naive substring match flagged 15 of 26 pages, and
    # almost all of them were one FAQ reading "Is it made in Italy? Baci Milano
    # is an Italian design house…" — the compliant ANSWER, not a breach.
    print("\n— a question is not a claim —")
    aqua = [v for v in r["violations"] if v["url"].endswith("/products/aqua")]
    ck("an FAQ question is NOT reported as a violation", not aqua,
       "a checker that cries wolf stops being read")
    q = [x for x in r["questions_to_review"] if x["url"].endswith("/products/aqua")]
    ck("but it IS surfaced separately for an eye", bool(q), str(q)[:90])
    ck("and the count is reported", r["questions_count"] >= 1)

    # ---- context is a sentence, not a character window --------------------
    ctx = v["hits"][0]["context"]
    ck("context is a whole sentence, judgeable without opening the page",
       ctx.endswith(".") or ctx.endswith("…"), repr(ctx[-40:]))

    # ---- ranked -----------------------------------------------------------
    ck("phrases are ranked by how many pages use them", bool(r["by_phrase"]),
       str(r["by_phrase"]))

    # ---- incremental ------------------------------------------------------
    print("\n— only what changed —")
    r2 = compliance.scan("baci", limit=40, since="2026-08-11")
    ck("older pages are skipped", r2["pages_checked"] < r["pages_checked"],
       f"{r2['pages_checked']} vs {r['pages_checked']}")
    ck("but the changed one is still caught", len(r2["violations"]) == 1)
    ck("and it says how many it skipped", r2["pages_skipped_unchanged"] > 0)

    # ---- refusing ---------------------------------------------------------
    print("\n— when it cannot check —")
    # A brand-new account, before anyone has said what it may not claim.
    with db.SessionLocal() as s:
        s.add(db.Tenant(key="fresh", name="Fresh Co", domain="fresh.test"))
        s.commit()
    out = compliance.scan("fresh")
    ck("an account with no banned claims is refused, not passed",
       "no banned_claims" in out.get("error", ""), str(out)[:90])
    out = compliance.scan("nosuchclient")
    ck("an unknown account is refused", "unknown tenant" in out.get("error", ""))

    httpx.get = lambda url, **kw: _Resp("", 404)
    out = compliance.scan("ironside")
    ck("a site with no sitemap says so rather than reporting clean",
       "no sitemap" in out.get("error", ""), str(out)[:90])
    httpx.get = _fake_get

    # ---- it is a system ----------------------------------------------------
    print("\n— it is a system, with a ledger —")
    ck("it is in the catalogue", "content_compliance" in systems.CATALOG)
    sysrow = systems.create("baci", "content_compliance")
    before = len(systems.runs(sysrow.id, limit=0))
    compliance.record_scan("baci", compliance.scan("baci"))
    runs = systems.runs(sysrow.id, limit=0)
    ck("a scan is recorded as a run", len(runs) == before + 1)
    ck("carrying what it found",
       (runs[0].outcome or {}).get("violations") == 1, str(runs[0].outcome))
    # A REAL CHECK. This was the literal `True` with the call it describes on
    # the NEXT line — so it printed [ ok ] whatever `scan` did, including
    # returning a clean bill of health for an account with no rules to check
    # against, which is the one outcome it exists to forbid.
    fresh = compliance.scan("fresh")
    ck("an account without the rules blocks rather than reporting clean",
       "no banned_claims" in str(fresh.get("error", "")),
       str(fresh)[:110] + " — a clean report from an account with nothing to "
       "check against is the most dangerous output this can produce")
    compliance.record_scan("fresh", fresh)

    httpx.get = real_get
    print()
    if _fail:
        print(f"{len(_fail)} FAILED:")
        for f in _fail:
            print(f"  - {f}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
