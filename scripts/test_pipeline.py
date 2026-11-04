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
        "<p>Payments move through 40 corridors every day.</p>"
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


def check_m3_readers_accounting_and_reprocess():
    """M3 — pluggable readers, counted tables, unaccounted figures, re-reads."""
    from app import extract, statements as st
    from app.pipeline import account, extractors, fetch, parse, reprocess
    comp = f"{BASE}/pages/compliance"
    lic = [r for r in st.rows("baci", "legal.licences") if r.url == comp]
    ck("M3 a 19-row table under 'State licences' is a counted, binding licence figure",
       any(r.value == "19" and r.qualifier == "counted" and r.authority == "binding"
           and r.field == "table" and r.extractor == "enumerations" for r in lic),
       str([(r.value, r.qualifier, r.field, r.extractor) for r in lic]))
    figs = account.open_figures("baci")
    corr = [g for g in figs if g["number"] == "40" and "corridors" in g["context"]]
    ck("M3 a figure no reader understood is LISTED with its sentence", bool(corr),
       str([(g["number"], g["context"][:40]) for g in figs]))
    ck("M3 figures are this account's only",
       bool(figs) and not account.open_figures("eien"))
    ck("M3 rows inside a counted table are the table's, not separate figures",
       not any("MT-" in g["context"] or g["context"].startswith("State ") for g in figs),
       str([g["context"][:30] for g in figs]))
    from app import admin_ui
    html = admin_ui.render_content("s3cret", tenant="baci", sub="facts")
    ck("M3 the console lists open figures with their decisions and a re-read button",
       "Figures we could not read" in html and "/admin/figure_decide" in html
       and "/admin/reprocess" in html and "Not a fact" in html,
       str([x for x in ("Figures we could not read", "/admin/figure_decide", "/admin/reprocess", "Not a fact") if x not in html]))
    # A reviewer teaches the account the word; a re-read of STORED pages
    # records it, with zero fetches.
    out = account.label("baci", corr[0]["id"], "coverage.corridors") if corr else {}
    ck("M3 labelling a figure teaches the account its term",
       out.get("term") == "corridors" and ("corridors", "coverage.corridors") in st.terms("baci"),
       str(out))
    calls = net({})
    rep = reprocess.reprocess("baci", apply=True)
    ck("M3 reprocess reads the stored pages and fetches nothing",
       rep["pages_read_from_store"] >= 2 and rep["pages_fetched"] == 0 and not calls,
       str({k: rep[k] for k in ("pages_read_from_store", "pages_fetched")}) + str(calls))
    ck("M3 after the label, the figure is a statement and no longer open",
       any(r.value == "40" for r in st.rows("baci", "coverage.corridors"))
       and not any(g["number"] == "40" and "corridors" in g["context"]
                   for g in account.open_figures("baci")))
    # A bumped reader re-reads with its new version; old rows are replaced.
    from app.pipeline.extractors import enumerations
    old = enumerations.VERSION
    enumerations.VERSION = old + 1
    try:
        reprocess.reprocess("baci", apply=True)
    finally:
        enumerations.VERSION = old
    vers = {r.extractor_version for r in st.rows("baci") if r.extractor == "enumerations"}
    ck("M3 a bumped reader's statements replace its old ones", vers == {old + 1}, str(vers))
    extractors.DISABLED.add("enumerations")
    try:
        reprocess.reprocess("baci", apply=True)
        none = [r for r in st.rows("baci") if r.extractor == "enumerations"]
    finally:
        extractors.DISABLED.discard("enumerations")
    ck("M3 a reader can be switched off without stopping the others",
       not none and st.rows("baci", "coverage.countries"))
    reprocess.reprocess("baci", apply=True)
    # Ignoring a sentence applies to it on every page.
    from app import mcp_server
    out = mcp_server.get_statements("baci")
    ck("M3 get_statements states the capture's open gaps",
       "unaccounted_open" in out and isinstance(out.get("unaccounted"), list))
    csv_out = mcp_server.get_statements("baci", format="csv")
    ck("M3 the CSV names the reader, section and position of each figure",
       "extractor,section,locator" in csv_out["csv"].splitlines()[0]
       and "enumerations" in csv_out["csv"])
    # The model's reading of an unchanged chunk is paid once.
    calls_m = []
    real_av, real_call = extract.available, extract._call
    extract.available = lambda: True
    extract._call = lambda system, user, tenant="": (calls_m.append(1) or
                                                    {"text": "[]", "truncated": False})
    try:
        blocks = parse.parse(PAGES[comp])["blocks"]
        r1 = extract.extract("baci", comp, blocks)
        r2 = extract.extract("baci", comp, blocks)
    finally:
        extract.available, extract._call = real_av, real_call
    ck("M3 an unchanged chunk is read by the model once, then from the cache",
       len(calls_m) == r1["input"]["chunks"] and r2["input"].get("cached") == r2["input"]["chunks"],
       f"calls={len(calls_m)} r1={r1['input']} r2={r2['input']}")


def main() -> int:
    db.init_db()
    tenants.seed()
    kb_seed.seed_all()
    check_m1_snapshots_and_documents()
    check_m2_scan_reads_the_store()
    check_m3_readers_accounting_and_reprocess()
    print(f"\n{'FAILED: ' + ', '.join(_fail) if _fail else 'all checks passed'}")
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
