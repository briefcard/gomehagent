"""The truth pipeline's stage contracts (BUILD-MAP-truth-pipeline.md §4).

One check group per milestone. Every group runs offline: the network is a
dict of pages, the model is off.

    python3 scripts/test_pipeline.py
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'pl.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, extract, harvest, kb_seed, tenants  # noqa: E402

extract.available = lambda: False

_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


class _Resp:
    def __init__(self, text, code=200):
        self.text, self.status_code = text, code


BASE = "https://bacimilanousa.com"
FILLER = ("<p>Our checkout settles in local currency, verifies identity once, and "
          "works inside the partner's own app so customers never leave the page.</p>")
PAGES = {
    f"{BASE}/pages/coverage": (
        "<html><body><header>Available in 162+ countries</header><main>"
        "<h1>Coverage</h1><div class='swiper-slide'>75 countries</div>"
        "<h2>Supported countries</h2><ul><li>France</li><li>Spain</li><li>Italy</li></ul>"
        + FILLER + "</main><footer>Live in 145 countries</footer></body></html>"),
    f"{BASE}/pages/compliance": (
        "<html><body><main><h1>Compliance</h1><h2>State licences</h2>"
        "<table><tr><th>State</th><th>Licence</th><th>Number</th></tr>"
        + "".join(f"<tr><td>State {i}</td><td>Money transmitter</td><td>MT-{1000 + i}</td></tr>"
                  for i in range(19))
        + "</table>" + FILLER + "</main></body></html>"),
}


def net(pages):
    import httpx
    calls = []
    sitemap = ("<?xml version=\"1.0\"?><urlset>"
               + "".join(f"<url><loc>{u}</loc></url>" for u in pages) + "</urlset>")

    def get(url, **kw):
        calls.append(url)
        if url.endswith("/sitemap.xml"):
            return _Resp(sitemap)
        return _Resp(pages[url]) if url in pages else _Resp("", 404)
    httpx.get = get
    return calls


def check_m1_snapshots_and_documents():
    """M1 — one fetch, many readers: a fetched page is kept with its Document."""
    from app.pipeline import fetch, parse
    net(PAGES)
    harvest.forget_pages("baci")
    harvest.harvest("baci", limit=10, apply=False)
    ck("M1 a rehearsal stores no snapshot", not fetch.snapshots("baci"))
    harvest.harvest("baci", limit=10, apply=True)
    snaps = {r.url: r for r in fetch.snapshots("baci")}
    ck("M1 every page read is stored", set(snaps) == set(PAGES), str(sorted(snaps)))
    row = snaps.get(f"{BASE}/pages/compliance")
    ck("M1 the stored copy is the page as fetched",
       row is not None and fetch.html_of(row) == PAGES[f"{BASE}/pages/compliance"])
    doc = parse.document("baci", f"{BASE}/pages/compliance")
    tab = (doc.get("tables") or [{}])[0]
    ck("M1 a table is parsed as a table: headers, 19 rows, under its heading",
       tab.get("headers") == ["State", "Licence", "Number"] and tab.get("n_rows") == 19
       and tab.get("section") == "Compliance › State licences", str(tab)[:200])
    cov = parse.document("baci", f"{BASE}/pages/coverage")
    ck("M1 a list is parsed with its item count and section",
       any(x["section"].endswith("Supported countries") and x["n_items"] == 3
           for x in cov.get("lists", [])), str(cov.get("lists")))
    ck("M1 slider content is read AND flagged as interactive",
       "swiper" in cov.get("interactive", [])
       and any("75 countries" in ln for ln in cov.get("lines", [])))
    ck("M1 furniture is kept in the Document (header and footer lines)",
       any("162+" in ln for ln in cov["lines"]) and any("145" in ln for ln in cov["lines"]))
    ck("M1 the snapshot hash is the harvest's page hash (no spurious re-reads)",
       row.content_hash == parse.parse(PAGES[f"{BASE}/pages/compliance"])["text_hash"])
    # A newer parser re-parses from the stored bytes; nothing is fetched.
    calls = net(PAGES)
    old = parse.VERSION
    parse.VERSION = old + 1
    try:
        again = parse.document("baci", f"{BASE}/pages/compliance")
    finally:
        parse.VERSION = old
    ck("M1 a newer parser re-reads the stored copy with zero fetches",
       again.get("version") == old + 1 and not calls, str(calls))
    ck("M1 snapshots are this account's only", not fetch.snapshots("eien"))


def check_m2_scan_reads_the_store():
    """M2 — the ban-list scan checks the stored copy; the site is fetched once."""
    import datetime as dt
    from app import compliance, kb
    from app.pipeline import fetch
    ck("M2 baci has rules to scan with", bool(kb.banned_claims("baci")))
    # The scan reads marketing pages only (legal pages are binding, not
    # phrase-checked), and discovery reads robots.txt / sitemap.xml.
    scanned = [u for u in PAGES if not compliance.is_legal_url(u)]
    calls = net(PAGES)
    res = compliance.scan("baci", limit=20)
    pages_hit = [u for u in calls if u in PAGES]
    ck("M2 a scan right after a harvest fetches no page again",
       not pages_hit and res.get("pages_from_store") == len(scanned)
       and res.get("pages_checked") == len(scanned),
       str({"fetched": pages_hit, "from_store": res.get("pages_from_store"),
            "checked": res.get("pages_checked")}))
    # An old copy is not trusted: fetched again and re-stored.
    with db.SessionLocal() as s:
        for r in s.query(db.PageSnapshot).filter(db.PageSnapshot.tenant == "baci"):
            r.fetched_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=3)
        s.commit()
    calls = net(PAGES)
    res = compliance.scan("baci", limit=20)
    ck("M2 a stale stored copy is fetched again, and the report says so",
       res.get("pages_fetched") == len(scanned)
       and len([u for u in calls if u in PAGES]) == len(scanned), str(res.get("pages_fetched")))
    newest = max(r.fetched_at.replace(tzinfo=dt.timezone.utc) if r.fetched_at.tzinfo is None
                 else r.fetched_at for r in fetch.snapshots("baci"))
    ck("M2 what the scan fetched is stored for the next reader",
       dt.datetime.now(dt.timezone.utc) - newest < dt.timedelta(minutes=5))
    # A banned phrase on a stored page is still found from the stored copy.
    phrase = kb.banned_claims("baci")[0]
    url = f"{BASE}/pages/coverage"
    bad = PAGES[url].replace("<h1>Coverage</h1>", f"<h1>Coverage</h1><p>Every piece is {phrase}.</p>")
    from app.pipeline import parse
    fetch.store("baci", url, bad, parse.parse(bad)["text_hash"])
    calls = net(PAGES)            # the network still serves the clean page
    res = compliance.scan("baci", limit=20)
    ck("M2 the scan's finding comes from the stored copy",
       any(v["url"] == url for v in res.get("violations", [])), str(res.get("violations"))[:200])


def main() -> int:
    db.init_db()
    tenants.seed()
    kb_seed.seed_all()
    check_m1_snapshots_and_documents()
    check_m2_scan_reads_the_store()
    print(f"\n{'FAILED: ' + ', '.join(_fail) if _fail else 'all checks passed'}")
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
