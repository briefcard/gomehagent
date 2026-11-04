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


def check_m4_risk_tiers():
    """M4 — tiers decide how hard a page is read; legal/coverage are never cut."""
    from app import extract, jobs
    from app.pipeline import fetch, policy
    cases = {f"{BASE}/pages/compliance": "legal", f"{BASE}/pages/coverage": "coverage",
             f"{BASE}/blogs/news/spring": "blog", f"{BASE}/products/aqua": "product",
             "https://support.example.com/en/articles/1": "support", f"{BASE}/pages/about": "marketing"}
    got = {u: policy.tier(u) for u in cases}
    ck("M4 every page gets its tier from its URL", got == cases, str(got))
    ck("M4 a page whose heading names coverage is a coverage page",
       policy.tier(f"{BASE}/pages/about", {"headings": [{"level": 1, "text": "Supported countries"}]})
       == "coverage")
    ck("M4 legal and coverage pages have no ceiling",
       policy.max_chunks("legal") is None and policy.max_chunks("coverage") is None
       and policy.max_chunks("blog") is not None)
    long_blocks = [f"Licence {i}: we are registered as a money transmitter in jurisdiction "
                   f"number {i} under the applicable state statute and its rules." for i in range(1500)]
    real_av, real_call = extract.available, extract._call
    extract.available = lambda: True
    extract._call = lambda system, user, tenant="": {"text": "[]", "truncated": False}
    try:
        legal = extract.extract("baci", f"{BASE}/pages/compliance", long_blocks,
                                max_chunks=policy.max_chunks("legal"))
        blog = extract.extract("baci", f"{BASE}/blogs/news/x", long_blocks,
                               max_chunks=policy.max_chunks("blog"))
    finally:
        extract.available, extract._call = real_av, real_call
    ck("M4 a very long legal page is read in full, every chunk",
       not legal["input"]["cut"] and legal["input"]["read"] == legal["input"]["blocks"],
       str(legal["input"]))
    ck("M4 the same page as a blog post is cut at its tier's ceiling — and says so",
       blog["input"]["cut"] and blog["input"]["chunks"] == policy.max_chunks("blog"), str(blog["input"]))
    # Ordering: with a budget of one page, the legal page is read first even
    # when the sitemap lists a marketing page ahead of it.
    pages = {f"{BASE}/pages/about": "<html><body><main><p>We think colour belongs on the table, "
                                    "every day, in every home that loves to cook and gather.</p>"
                                    + FILLER + "</main></body></html>",
             **PAGES}
    net(pages)
    harvest.forget_pages("baci")
    res = harvest.harvest("baci", limit=1, apply=True, recrawl=True)
    ck("M4 a budget of one page reads the legal page first",
       res.get("pages_by_tier") == {"legal": 1}, str(res.get("pages_by_tier")))
    res = harvest.harvest("baci", limit=10, apply=True, recrawl=True)
    tiers = {r.url: r.risk_tier for r in fetch.snapshots("baci")}
    ck("M4 the report and the stored page carry the tier",
       res.get("pages_by_tier", {}).get("coverage") == 1
       and tiers.get(f"{BASE}/pages/compliance") == "legal"
       and tiers.get(f"{BASE}/pages/about") == "marketing", str(res.get("pages_by_tier")) + str(tiers))
    ck("M4 re-reading stored pages is a queued job on the worker",
       "reprocess" in jobs.KINDS and jobs.KINDS["reprocess"]["target"] == "app.pipeline.reprocess:job")


def check_m5_known_answers_audits_trust():
    """M5 — QA tests the capture: known answers, audits, a trust grade."""
    from app import admin_ui, mcp_server
    from app.pipeline import checks
    comp = f"{BASE}/pages/compliance"
    net(PAGES)
    harvest.harvest("baci", limit=10, apply=True, recrawl=True)
    out = checks.add_known("baci", "legal.licences", "19", comp, by="qa-anna")
    ck("M5 QA can write down a fact they know", "id" in out, str(out))
    got = {r["subject"]: r for r in checks.check_known("baci")["results"]}
    ck("M5 the capture is tested against it: 19 licences found",
       got["legal.licences"]["result"] == "found", str(got.get("legal.licences")))
    checks.add_known("baci", "coverage.countries", "75", f"{BASE}/pages/never-read")
    checks.add_known("baci", "coverage.blockchains", "12", comp)
    got = {r["subject"]: r for r in checks.check_known("baci")["results"]}
    ck("M5 a known answer on a page never read is 'not read', not a failure",
       got["coverage.countries"]["result"] == "not_read" and not got["coverage.countries"]["severity"])
    ck("M5 a figure the page was read for and not captured is 'missing' — P1",
       got["coverage.blockchains"]["result"] == "missing"
       and got["coverage.blockchains"]["severity"] == "P1")
    checks.remove_known("baci", got["coverage.blockchains"]["id"])
    checks.remove_known("baci", got["coverage.countries"]["id"])
    # The licence table loses rows: the next read says so, as a P1.
    short = dict(PAGES)
    short[comp] = PAGES[comp].replace("".join(
        f"<tr><td>State {i}</td><td>Money transmitter</td><td>MT-{1000 + i}</td></tr>"
        for i in range(10, 19)), "")
    net(short)
    res = harvest.harvest("baci", limit=10, apply=True, recrawl=True)
    ka = res.get("known_answers") or {}
    ck("M5 a harvest that captures 10 of 19 licences reports a P1 known-answer failure",
       ka.get("failed") == 1 and ka["failures"][0]["result"] == "different"
       and ka["failures"][0]["captured"] == ["10"], str(ka))
    tr = checks.trust("baci")
    ck("M5 trust is RED while a known answer fails, and says why",
       tr["grade"] == "red" and any("known answer" in r for r in tr["reasons"]), str(tr["reasons"]))
    net(PAGES)
    harvest.harvest("baci", limit=10, apply=True, recrawl=True)
    # Audits: legal and coverage pages first, decisions carry who made them.
    drawn = checks.draw_sample("baci", n=2, seed=1)
    ck("M5 an audit draws the highest-risk pages first",
       [a["tier"] for a in drawn] == ["legal", "coverage"], str([a["tier"] for a in drawn]))
    ck("M5 each audit shows what was recorded from the page",
       any(x["subject"] == "legal.licences" for x in drawn[0]["recorded"]))
    checks.decide_audit("baci", drawn[0]["id"], True, by="qa-anna")
    checks.decide_audit("baci", drawn[1]["id"], False, "the 75 countries slide", by="qa-anna")
    rec = checks.audit_recall("baci")
    ck("M5 audit recall is measured, and a miss is kept with its note and reviewer",
       rec["audited"] == 2 and rec["recall"] == 0.5
       and rec["missed"][0]["note"] == "the 75 countries slide" and rec["missed"][0]["by"] == "qa-anna",
       str(rec))
    tr = checks.trust("baci")
    ck("M5 trust is amber, not green, until enough audits are done",
       tr["grade"] == "amber" and any("audit" in r for r in tr["reasons"]), str(tr))
    html = admin_ui.render_content("s3cret", tenant="baci", sub="checks")
    ck("M5 the console shows trust, known answers and audit forms",
       "Can the capture be trusted?" in html and "/admin/known_answer" in html
       and "/admin/audit_draw" in html and 'name="by"' in html)
    mt = mcp_server.get_trust("baci")
    ck("M5 get_trust gives the grade and its reasons to a Claude session",
       mt.get("ok") and mt.get("grade") in ("green", "amber", "red") and mt.get("reasons"))
    ck("M5 known answers and audits are this account's only",
       not checks.known_answers("eien") and not checks.open_audits("eien")
       and checks.audit_recall("eien")["audited"] == 0)


def check_console_controls_do_what_they_say():
    """Every QA control on the console, PRESSED over HTTP, and its effect read
    back from the data — not inferred from the redirect."""
    from fastapi.testclient import TestClient
    from app import jobs, web as _web
    from app.pipeline import account, checks
    c = TestClient(_web.app)
    comp = f"{BASE}/pages/compliance"
    r = c.post("/admin/known_answer?key=s3cret", data={
        "tenant": "baci", "action": "add", "subject": "legal.licences", "expected": "19",
        "where_url": comp, "by": "qa-ben"}, follow_redirects=False)
    ka = [k for k in checks.known_answers("baci") if k.subject == "legal.licences"]
    ck("CONSOLE adding a known answer records it with the reviewer, and tests it at once",
       r.status_code in (200, 303) and ka and ka[0].set_by == "qa-ben" and ka[0].last_result == "found",
       f"{r.status_code} {[(k.set_by, k.last_result) for k in ka]}")
    r = c.post("/admin/audit_draw?key=s3cret", data={"tenant": "baci"}, follow_redirects=False)
    opened = checks.open_audits("baci")
    ck("CONSOLE drawing an audit opens pages to check", r.status_code in (200, 303) and opened,
       str(r.status_code))
    if opened:
        r = c.post("/admin/audit_decide?key=s3cret", data={
            "tenant": "baci", "audit_id": opened[0]["id"], "action": "missed", "missed": ""},
            follow_redirects=False)
        ck("CONSOLE 'something was missed' with no note is refused — a miss must say what",
           any(a["id"] == opened[0]["id"] for a in checks.open_audits("baci")))
        c.post("/admin/audit_decide?key=s3cret", data={
            "tenant": "baci", "audit_id": opened[0]["id"], "action": "complete", "by": "qa-ben"},
            follow_redirects=False)
        with db.SessionLocal() as s:
            row = s.get(db.AuditSample, opened[0]["id"])
        ck("CONSOLE 'complete' closes the audit with the reviewer's name",
           row.status == "complete" and row.decided_by == "qa-ben", f"{row.status} {row.decided_by}")
    # A figure: mark one not-a-fact, from the console.
    page = f"{BASE}/pages/coverage"
    from app.pipeline import fetch, parse
    html = PAGES[page].replace("</main>", "<p>Our team answered 812 questions last week.</p></main>")
    fetch.store("baci", page, html, parse.parse(html)["text_hash"])
    from app.pipeline import reprocess as _rp
    _rp.reprocess("baci", apply=True)
    fig = next((g for g in account.open_figures("baci") if g["number"] == "812"), None)
    ck("CONSOLE a fresh unexplained figure is listed", fig is not None)
    if fig:
        c.post("/admin/figure_decide?key=s3cret", data={
            "tenant": "baci", "figure_id": fig["id"], "action": "ignore"}, follow_redirects=False)
        ck("CONSOLE 'Not a fact' closes it",
           not any(g["number"] == "812" for g in account.open_figures("baci")))
    r = c.post("/admin/reprocess?key=s3cret", data={"tenant": "baci"}, follow_redirects=False)
    with db.SessionLocal() as s:
        queued = (s.query(db.JobQueue)
                  .filter(db.JobQueue.tenant == "baci", db.JobQueue.kind == "reprocess").count())
    ck("CONSOLE 'Re-read stored pages' queues a reprocess job on the worker",
       r.status_code in (200, 303) and queued == 1, f"{r.status_code} queued={queued}")


def check_m6_the_agreement_rule():
    """truth.agrees — the one judge — table-driven."""
    from app import truth
    cases = [  # stated, stated-qualifier, true, true-qualifier, agrees?
        (162, "", 162, "", True), (75, "", 162, "", False),
        (100, "at least", 162, "", True),        # "over 100" is true of 162
        (200, "at least", 162, "", False),       # "200+" is an overclaim
        (160, "at least", 160, "at least", True), (162, "at least", 160, "at least", False),
        (19, "counted", 19, "", True), (18, "counted", 19, "", False),
        (155, "about", 162, "", True), (120, "about", 162, "", False),
        (200, "up to", 162, "", True), (100, "up to", 162, "", False),
        (170, "", 160, "at least", True), (150, "", 160, "at least", False),
    ]
    bad = [c for c in cases if truth.agrees(c[0], c[1], c[2], c[3]) != c[4]]
    ck("M6 the agreement rule holds on every case", not bad, str(bad))


def check_m6_truth_findings_and_questions():
    """M6 — QA sets the truth per subject × scope; disagreements are findings."""
    from fastapi.testclient import TestClient
    from app import admin_ui, findings, mcp_server, truth, web as _web
    from app.pipeline import fetch, parse, reprocess
    comp, cov = f"{BASE}/pages/compliance", f"{BASE}/pages/coverage"
    ship, terms = f"{BASE}/policies/shipping-policy", f"{BASE}/policies/terms-of-service"
    aqua = f"{BASE}/pages/aqua-availability"
    pages = dict(PAGES)
    pages[ship] = "<html><body><main><p>We ship orders to 3 regions.</p>" + FILLER + "</main></body></html>"
    pages[terms] = "<html><body><main><p>Products are shipped to 2 regions only.</p>" + FILLER + "</main></body></html>"
    pages[aqua] = "<html><body><main><p>Aqua is available in 40 countries.</p>" + FILLER + "</main></body></html>"
    net(pages)
    harvest.forget_pages("baci")
    res = harvest.harvest("baci", limit=20, apply=True, recrawl=True)
    ck("M6 the harvest rebuilds findings", isinstance(res.get("findings"), dict)
       and res["findings"].get("open_now", 0) >= 2, str(res.get("findings")))
    fs = findings.listing("baci")
    countries = next((f for f in fs if f["subject"] == "coverage.countries"
                      and f["kind"] == "unresolved"), None)
    ck("M6 a subject the site states several ways is ONE plain question with every value",
       countries is not None and countries["question"].startswith("How many countries")
       and {"162+", "75", "145", "40"} <= {v["value"] for v in countries["detail"]["values"]},
       str(countries and [v["value"] for v in countries["detail"]["values"]]))
    ck("M6 a coverage disagreement is P2", countries and countries["severity"] == "P2")
    # Baci B1 in numbers: the shipping policy and the terms disagree — both legal.
    pol = next((f for f in fs if f["urls"] and set(f["urls"]) >= {ship, terms}), None)
    ck("M6 two LEGAL pages disagreeing is a P1", pol is not None and pol["severity"] == "P1",
       str(pol and (pol["subject"], pol["severity"], pol["urls"])))
    # Decisions need a reason.
    out = findings.decide("baci", countries["id"], "correct", "", value="162+")
    ck("M6 a decision without a reason is refused", "error" in out)
    out = findings.decide("baci", countries["id"], "correct", "The coverage API lists 162",
                          by="qa-anna", value="162+")
    ck("M6 'this is correct' sets the truth and recomputes", out.get("ok"), str(out))
    t = truth.resolve("baci", "coverage.countries")
    ck("M6 the truth is the chosen value, with who and why",
       t and t["value"] == "162+" and t["decided_by"] == "qa-anna" and "API" in t["reason"], str(t))
    fs = findings.listing("baci")
    contra = {f["value"]: f for f in fs if f["subject"] == "coverage.countries"
              and f["kind"] == "contradiction"}
    ck("M6 every page stating otherwise is now a contradiction to fix (75, 145, 40)",
       {"75", "145", "40"} <= set(contra) and "162+" not in contra, str(sorted(contra)))
    ck("M6 the unresolved question closed itself, with its reason kept",
       any(f["id"] == countries["id"] and f["status"] == "closed"
           for f in findings.listing("baci", "all")))
    # Both right: the Aqua page speaks for one product.
    f40 = contra.get("40")
    out = findings.decide("baci", f40["id"], "scope", "Aqua ships to fewer markets",
                          by="qa-anna", url=aqua, entity="aqua") if f40 else {}
    ck("M6 'both right — that page is about this product' closes it and scopes the truth",
       out.get("ok") and not any(f["value"] == "40" and f["status"] == "open"
                                 for f in findings.listing("baci") if f["subject"] == "coverage.countries")
       and truth.resolve("baci", "coverage.countries", {"entity": "aqua"})["value"] == "40"
       and truth.resolve("baci", "coverage.countries")["value"] == "162+", str(out))
    # Source of truth: the licence page, and the truth FOLLOWS it.
    lic_q = next((f for f in findings.listing("baci") if f["subject"] == "legal.licences"), None)
    if lic_q is None:
        # The licence figure agrees everywhere; make the compliance page the
        # source through the decision path anyway, via a fresh finding.
        truth.make_source("baci", comp, ["legal.licences"], by="qa-anna")
        r = [x for x in __import__("app.statements", fromlist=["x"]).rows_for_url("baci", comp)
             if x.subject == "legal.licences"][0]
        truth.set_value("baci", "legal.licences", r.value, r.number, r.qualifier,
                        mode="follows_source", source_url=comp, reason="the register", by="qa-anna")
    else:
        findings.decide("baci", lic_q["id"], "source", "the register is authoritative",
                        by="qa-anna", url=comp)
    ck("M6 the declared source is listed with what it governs",
       any(x.ref == comp and "legal.licences" in (x.governs or []) for x in truth.sources("baci")))
    fewer = PAGES[comp].replace("<tr><td>State 18</td><td>Money transmitter</td><td>MT-1018</td></tr>", "")
    fetch.store("baci", comp, fewer, parse.parse(fewer)["text_hash"])
    reprocess.reprocess("baci", apply=True)
    ck("M6 a source-of-truth page that changes moves the truth with it (19 → 18)",
       truth.resolve("baci", "legal.licences")["value"] == "18", str(truth.resolve("baci", "legal.licences")))
    # A legal page disagreeing with the truth questions the truth itself.
    legal_bad = f"{BASE}/policies/legal-notice"
    html = "<html><body><main><p>We operate in 140 countries.</p>" + FILLER + "</main></body></html>"
    pages[legal_bad] = html
    net(pages)
    harvest.harvest("baci", limit=20, apply=True, recrawl=True)
    bc = [f for f in findings.listing("baci") if f["kind"] == "binding_conflict"]
    ck("M6 a legal page disagreeing with the approved answer is a P1 binding conflict",
       bc and bc[0]["severity"] == "P1" and legal_bad in bc[0]["urls"], str(bc[:1]))
    out = findings.decide("baci", bc[0]["id"], "escalate", "legal to confirm 140 vs 162", by="qa-anna")
    ck("M6 'needs legal review' holds it out of the open queue",
       out.get("ok") and not any(f["id"] == bc[0]["id"] for f in findings.listing("baci"))
       and any(f["id"] == bc[0]["id"] for f in findings.listing("baci", "escalated")))
    # Console: the questions render, and answering one over HTTP works.
    html = admin_ui.render_content("s3cret", tenant="baci", sub="truth")
    ck("M6 the console asks plain questions with the four answers",
       "Questions for QA" in html and "This is correct" in html
       and "source of truth" in html and "Needs legal review" in html and "/admin/finding_decide" in html)
    open_now = findings.listing("baci")
    c = TestClient(_web.app)
    target = next((f for f in open_now if f["kind"] == "contradiction"), None)
    if target:
        r = c.post("/admin/finding_decide?key=s3cret", data={
            "tenant": "baci", "finding_id": target["id"], "decision": "escalate",
            "reason": "ask the coverage team", "by": "qa-ben"}, follow_redirects=False)
        with db.SessionLocal() as s:
            row = s.get(db.Finding, target["id"])
        ck("CONSOLE answering a question records the decision, reason and reviewer",
           r.status_code in (200, 303) and row.status == "escalated" and row.decided_by == "qa-ben"
           and row.reason == "ask the coverage team")
    got = mcp_server.get_truth("baci")
    ck("M6 get_truth gives a Claude session the answers and the open findings",
       got.get("ok") and any(a["subject"] == "coverage.countries" and a["value"] == "162+"
                             for a in got["answers"]) and "findings" in got)
    ck("M6 truth and findings are this account's only",
       not truth.values("eien") and not findings.listing("eien", "all") and not truth.sources("eien"))


def check_m7_the_fact_gate():
    """M7 — every draft, reply and site edit is held to the approved truth."""
    from app import mcp_server, seo_guard, triage, validator

    def rules(body, entity=""):
        return [f["rule"] for f in validator.check("baci", body, entity_key=entity,
                                                    require_citation=False)["failures"]]
    ck("M7 a draft saying 'ships to 40 countries' against the brand answer 162+ is blocked",
       "contradicts_fact" in rules("Our tableware now ships to 40 countries."))
    ck("M7 the same figure on the Aqua product (its own answer is 40) passes",
       "contradicts_fact" not in rules("Aqua ships to 40 countries.", entity="aqua"))
    ck("M7 'over 100 countries' is true of 162 and passes",
       not {"contradicts_fact", "disputed_fact", "contradicts_legal"} & set(rules("Loved in over 100 countries.")))
    ck("M7 an overclaim ('200+ countries') is blocked", "contradicts_fact" in rules("In 200+ countries!"))
    ck("M7 a figure a legal page states otherwise, with no answer approved, is blocked",
       "contradicts_legal" in rules("We ship to 5 regions."), str(rules("We ship to 5 regions.")))
    ck("M7 a figure the site disputes, with no answer approved, waits for QA",
       "disputed_fact" in rules("We ship to 3 regions."), str(rules("We ship to 3 regions.")))
    got = mcp_server.check("baci", body="Now shipping to 40 countries.", kind="email")
    ck("M7 the MCP check a Claude session runs carries the block",
       not got.get("ok") and any(b.get("rule") == "contradicts_fact" for b in got.get("blocks", [])),
       str(got.get("blocks"))[:300])
    profile = {"key": "baci", "domain": "bacimilanousa.com"}
    why = seo_guard.check(profile, {"body_html": "<p>Available in 75 countries.</p>"}, what="test")
    ck("M7 an SEO edit to the live site stating a wrong figure is refused", "contradicts_fact" in why, why[:200])
    res = triage._apply_guards({"action": "auto_reply", "category": "order_routine",
                                "reply_subject": "Re: shipping",
                                "reply_body": "Yes — we deliver to 75 countries."},
                               "baci", sender_trusted=True)
    ck("M7 an email reply stating a wrong figure cannot auto-send",
       res.get("action") != "auto_reply", str({k: res.get(k) for k in ("action", "reason")}))
    pkg = mcp_server.get_package("baci", system="campaign_email")
    ck("M7 the brief a writer works from carries the approved figures and the disputed ones",
       "Approved figures" in pkg and "162+" in pkg and "Disputed figures" in pkg)


def main() -> int:
    db.init_db()
    tenants.seed()
    kb_seed.seed_all()
    check_m1_snapshots_and_documents()
    check_m2_scan_reads_the_store()
    check_m3_readers_accounting_and_reprocess()
    check_m4_risk_tiers()
    check_m5_known_answers_audits_trust()
    check_console_controls_do_what_they_say()
    check_m6_the_agreement_rule()
    check_m6_truth_findings_and_questions()
    check_m7_the_fact_gate()
    print(f"\n{'FAILED: ' + ', '.join(_fail) if _fail else 'all checks passed'}")
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
