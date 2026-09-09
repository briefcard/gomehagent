"""The Semrush door is priced, budgeted, and shuts itself on a zero balance.

Owner, 2026-09-07: *"We need to be very careful with this specific API because
it's very expensive. I want a plan for minimizing the individual calls and
making calls in bulk only."*

What was true that night, read off the ledger: the Monday cron's harvest made
eighteen Semrush requests for one account — one succeeded, one was refused
with `ERROR 132 :: API UNITS BALANCE IS ZERO`, and the loop then asked sixteen
more times. Semrush bills per LINE returned, at 40 units a line for the two
reports the harvest fans out per seed, so one harvest is 28,000 units an
account, and nothing in the code priced it, budgeted it, or stopped it. Every
clamp was a `display_limit` reasoned about in lines; the ledger recorded calls
and bytes and never the bill; a caller that named no limit would have been
sent the API's own default of 10,000 lines.

This suite drives the door (`seo_tools._semrush`) through a stubbed
`httpx.get` — the seam `test_toolcalls` already uses — and the harvest through
its documented fetch seams, and asserts on the ledger, the requests actually
made, and the notes, never on a helper's return alone.

    python3 scripts/test_semrush_units.py
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'su.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["PUBLIC_BASE_URL"] = "https://example.test"
os.environ["SEMRUSH_API_KEY"] = "fake-key"
os.environ["SEO_SITES_JSON"] = json.dumps(
    {"baci": {"domain": "bacimilanousa.com", "platform": "shopify",
              "creds_key": "baci", "database": "us"}})
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import admin_ui, config, db, diagnostics, keywords, seo_tools, tenants, toolcalls  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


class _R:
    def __init__(self, text, status=200):
        self.text, self.status_code = text, status


class Http:
    """A stand-in for `httpx.get` that remembers every request it was asked
    to make. `reply` is a string, an `_R`, or a function of (url, params)."""

    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def __call__(self, url, params=None, timeout=None):
        params = dict(params or {})
        self.calls.append((url, params))
        r = self.reply(url, params) if callable(self.reply) else self.reply
        return r if isinstance(r, _R) else _R(r)

    def to(self, host_frag: str) -> list:
        return [c for c in self.calls if host_frag in c[0]]


def ledger(tool: str = "", tenant: str = "") -> list:
    with db.SessionLocal() as s:
        q = s.query(db.ToolCall)
        if tool:
            q = q.filter(db.ToolCall.tool == tool)
        if tenant:
            q = q.filter(db.ToolCall.tenant == tenant)
        rows = q.order_by(db.ToolCall.at).all()
        s.expunge_all()
        return rows


def fresh_balance(units: int) -> None:
    """A positive reading, filed the way the console button files one — and
    therefore also the way a halted door is reopened."""
    seo_tools.record_reading(units, "console")


CSV3 = "Keyword;Search Volume;CPC;Competition\na;100;1.0;0.1\nb;90;1.0;0.1\nc;80;1.0;0.1"


def main() -> int:
    db.init_db()
    tenants.seed()
    real_get = seo_tools.httpx.get
    caps = (config.SEMRUSH_WEEKLY_CAP, config.SEMRUSH_ACCOUNT_WEEKLY_CAP,
            config.SEMRUSH_TURN_CAP)
    config.SEMRUSH_WEEKLY_CAP, config.SEMRUSH_ACCOUNT_WEEKLY_CAP = 10**7, 10**6
    fresh_balance(500_000)

    try:
        print("— the price list is per line, per report, and never free —")
        e = seo_tools.estimate
        ck("related keywords: 40 lines × 40 units", e("phrase_related", display_limit=40) == 1600)
        ck("questions: the same price", e("phrase_questions", display_limit=40) == 1600)
        ck("the gap pull: 200 lines × 10", e("domain_organic", display_limit=200) == 2000)
        ck("a domain overview is one line", e("domain_rank") == 10)
        ck("the batch report is one line per phrase", e("phrase_these", phrase="a;b;c") == 30)
        ck("a call that names no limit is priced at DEFAULT_LINES, never the API's 10,000",
           e("phrase_related") == seo_tools.DEFAULT_LINES * 40, str(e("phrase_related")))
        ck("nothing may ask for more than MAX_LINES",
           e("phrase_related", display_limit=9000) == seo_tools.MAX_LINES * 40)
        ck("an unpriced report is charged at the dearest known rate",
           e("phrase_new_thing", display_limit=10) == 10 * seo_tools.UNPRICED_RATE)
        ck("the ledger row carries the cost", hasattr(db.ToolCall, "units"))

        for i in range(8):
            keywords.upsert("baci", f"acrylic seed{i}", volume=500, source="semrush_own")
        # THE BILL THIS REPLACED, priced from the code as it stood that night:
        # 40 lines of domain_organic + 200 more + eight seeds x two 40-lines
        # reports at 40 units a line.
        was = (e("domain_organic", display_limit=40)
               + e("domain_organic", display_limit=200)
               + 8 * (e("phrase_related", display_limit=40)
                      + e("phrase_questions", display_limit=40)))
        ck("the harvest that ran on 2026-09-07 was 28,000 units", was == 28_000, str(was))
        now = keywords.harvest_estimate("baci")
        one_domain = e("domain_organic", display_limit=seo_tools.DOMAIN_PULL_LINES)
        per_seed = 2 * e("phrase_related", display_limit=seo_tools.EXPANSION_LINES)
        ck("the same harvest today is one domain read plus the seed budget",
           now == one_domain + config.SEMRUSH_NEW_SEEDS_PER_RUN * per_seed
           and now < was // 3, f"{now} vs {was}")
        ck("the unattended top-up is the one domain read",
           keywords.harvest_estimate(
               "baci", sources=keywords.UNATTENDED_SOURCES) == one_domain,
           str(one_domain))
        ck("forty hand-typed seeds cost the same as three, because three is "
           "what a run buys",
           keywords.harvest_estimate("baci", seeds=tuple(str(i) for i in range(40)))
           == keywords.harvest_estimate("baci", seeds=("a", "b", "c")))

        print("\n— the door prices what it read and bounds what it asks —")
        http = Http(CSV3)
        seo_tools.httpx.get = http
        rows = seo_tools._semrush("phrase_related", _tenant="baci", phrase="jug")
        row = ledger("semrush_phrase_related", "baci")[-1]
        ck("three lines back at 40 a line land as 120 units on the row",
           isinstance(rows, list) and len(rows) == 3 and int(row.units or 0) == 120,
           f"units={row.units}")
        ck("the request carried DEFAULT_LINES, not the API's default",
           http.calls[-1][1].get("display_limit") == seo_tools.DEFAULT_LINES,
           str(http.calls[-1][1].get("display_limit")))
        ck("spent() reads the bill by account",
           toolcalls.spent("semrush", tenant="baci") == 120
           and toolcalls.spent("semrush", tenant="eien") == 0
           and toolcalls.spent("semrush") == 120)
        seo_tools._semrush("phrase_related", _tenant="baci", phrase="jug", display_limit=9000)
        ck("an oversized ask is sent at MAX_LINES",
           http.calls[-1][1].get("display_limit") == seo_tools.MAX_LINES)
        seo_tools._semrush("domain_rank", _tenant="baci", domain="x", database="us")
        ck("a one-line report is sent no display_limit",
           "display_limit" not in http.calls[-1][1])
        n_before = len(http.calls)
        seo_tools.semrush_keyword_metrics(";".join(f"k{i}" for i in range(250)),
                                          database="us", _tenant="baci")
        batch = http.calls[n_before:]
        ck("250 phrases go as three batch requests of at most 100",
           len(batch) == 3 and [len(p["phrase"].split(";")) for _, p in batch] == [100, 100, 50],
           str([len(p.get("phrase", "").split(";")) for _, p in batch]))

        print("\n— a zero balance shuts the door, once, and the next call makes no request —")
        http = Http("ERROR 132 :: API UNITS BALANCE IS ZERO")
        seo_tools.httpx.get = http
        got = seo_tools._semrush("phrase_related", _tenant="baci", phrase="jug", display_limit=10)
        ck("the refusal is reported as an error", str(got).startswith("Semrush error"), str(got))
        ck("and the door is now halted", bool(seo_tools.halted()), seo_tools.halted())
        got2 = seo_tools._semrush("phrase_questions", _tenant="baci", phrase="jug", display_limit=10)
        ck("the second call is the halt sentence and made NO request",
           "halted" in str(got2) and len(http.calls) == 1, f"{len(http.calls)} request(s)")
        ck("no ledger row for the call that never left",
           not ledger("semrush_phrase_questions", "baci"))
        ck("exactly one halt row in the ledger", len(ledger("semrush_halt")) == 1)
        fresh_balance(500_000)
        http = Http("ERROR 403 :: ERROR 132 :: API UNITS BALANCE IS ZERO")
        seo_tools.httpx.get = http
        seo_tools._semrush("domain_organic", _tenant="baci", domain="x", display_limit=10)
        ck("the 403-wrapped form of the same error halts too", bool(seo_tools.halted()))

        print("\n— a balance reading is free, kept, and reopens the door —")
        http = Http(lambda url, p: "12,500" if "countapiunits" in url else CSV3)
        seo_tools.httpx.get = http
        units = seo_tools.units_balance("baci")
        ck("the number comes back parsed", units == 12_500, str(units))
        ck("a positive balance reopens a halted door", seo_tools.halted() == "")
        ck("the reading is kept", seo_tools.balance_cached().get("units") == 12_500)
        brow = ledger("semrush_balance")[-1]
        ck("the reading is on the ledger at zero units", brow.ok == "yes" and int(brow.units or 0) == 0)
        with db.SessionLocal() as s:
            series = s.query(db.SemrushReading).order_by(db.SemrushReading.at).all()
        ck("the series holds the refusals and the readings in order",
           series[-1].source == "console" and series[-1].units == 12_500
           and sum(1 for r in series if r.source == "refusal") == 2
           and all(r.halted_until for r in series if r.source == "refusal"),
           str([(r.source, r.units) for r in series]))
        http = Http(lambda url, p: "<html>nope</html>" if "countapiunits" in url else CSV3)
        seo_tools.httpx.get = http
        ck("a non-number is None and the last good reading stands",
           seo_tools.units_balance("baci") is None
           and seo_tools.balance_cached().get("units") == 12_500)
        http = Http(lambda url, p: "0" if "countapiunits" in url else CSV3)
        seo_tools.httpx.get = http
        seo_tools.units_balance("baci")
        why = seo_tools.preflight("baci", 100, what="a test")
        ck("a zero reading before a run halts the door in the run's own words",
           "halted" in why and bool(seo_tools.halted()), why)
        http = Http(lambda url, p: "500" if "countapiunits" in url else CSV3)
        seo_tools.httpx.get = http
        seo_tools.units_balance("baci")
        ck("a run that costs more than the balance is refused by the balance",
           "refused" in seo_tools.preflight("baci", 900, what="a test")
           and seo_tools.preflight("baci", 400, what="a test") == "")
        fresh_balance(500_000)

        print("\n— the caps bind every caller, through the one door —")
        http = Http(CSV3)
        seo_tools.httpx.get = http
        config.SEMRUSH_ACCOUNT_WEEKLY_CAP = 100
        got = seo_tools._semrush("phrase_related", _tenant="baci", phrase="x", display_limit=10)
        ck("an account over its weekly cap is refused, in a sentence naming the cap",
           str(got).startswith("refused") and "baci" in str(got) and "cap" in str(got), str(got))
        ck("and no request was made", len(http.calls) == 0)
        ref = ledger("semrush_refused", "baci")
        ck("the refusal is one ledger row that says refused, with no provider",
           len(ref) == 1 and ref[0].error.startswith("refused") and not ref[0].provider)
        with db.SessionLocal() as s:
            t = s.get(db.Tenant, "baci")
            t.analytics = {**(t.analytics or {}), "semrush_weekly_cap": 5000}
            s.commit()
        got = seo_tools._semrush("phrase_related", _tenant="baci", phrase="x", display_limit=10)
        ck("the account's own setting raises its cap", isinstance(got, list) and len(http.calls) == 1)
        config.SEMRUSH_WEEKLY_CAP = 50
        got = seo_tools._semrush("phrase_related", _tenant="baci", phrase="x", display_limit=10)
        ck("the service-wide cap binds above the account's",
           str(got).startswith("refused") and "service" in str(got) and len(http.calls) == 1)
        config.SEMRUSH_WEEKLY_CAP, config.SEMRUSH_ACCOUNT_WEEKLY_CAP = 10**7, 10**6
        with db.SessionLocal() as s:
            t = s.get(db.Tenant, "baci")
            t.analytics = {k: v for k, v in (t.analytics or {}).items()
                           if k != "semrush_weekly_cap"}
            s.commit()
        ck("the override removed, the default cap is back",
           seo_tools.cap_for("baci") == config.SEMRUSH_ACCOUNT_WEEKLY_CAP)

        print("\n— Diagnostics: a refusal is logic, not a dead key, and the bill is shown —")
        ev = [e for e in diagnostics.events("baci", 7, limit=500)
              if e["kind"] == "tool" and e["summary"].startswith("semrush_refused")]
        ck("the refusal is filed at the logic layer as a warning",
           ev and all(e["layer"] == "logic" and e["level"] == "warn" for e in ev),
           str([(e["layer"], e["level"]) for e in ev][:2]))
        pf = diagnostics.platforms("baci", days=7)
        sem = next((p for p in pf["providers"] if p["provider"] == "semrush"), {})
        real_fails = [r for r in ledger(tenant="baci")
                      if r.provider == "semrush" and r.ok != "yes"]
        ck("the provider's failure count is the real refusals from Semrush, not ours",
           sem.get("failed") == len(real_fails), f"{sem.get('failed')} vs {len(real_fails)}")
        ck("the bill by account matches the ledger",
           pf["semrush"]["units"] == toolcalls.spent("semrush", tenant="baci", days=7)
           and pf["semrush"]["by_tenant"].get("baci") == pf["semrush"]["units"]
           and sem.get("units") == pf["semrush"]["units"])
        ck("the balance and the cap ride with it",
           pf["semrush"]["balance"].get("units") == 500_000
           and pf["semrush"]["weekly_cap"] == config.SEMRUSH_WEEKLY_CAP)
        from app import admin_ui
        page = admin_ui.render_diagnostics("s3cret", "baci", msg="balance read")
        ck("the page shows the bill, its control, and the flash",
           "Semrush units" in page and "Read the balance now" in page
           and "balance read" in page)

        print("\n— a chat is not a harvest: the turn's own budget —")
        http = Http(CSV3)
        seo_tools.httpx.get = http
        tok = seo_tools.start_turn(cap=50)
        got = seo_tools._semrush("phrase_related", _tenant="baci", phrase="x", display_limit=10)
        ck("a call over the turn's budget is refused naming the turn",
           str(got).startswith("refused") and "turn" in str(got) and not http.calls, str(got))
        seo_tools.end_turn(tok)
        got = seo_tools._semrush("phrase_related", _tenant="baci", phrase="x", display_limit=10)
        ck("outside a turn the same call proceeds", isinstance(got, list) and len(http.calls) == 1)
        tok = seo_tools.start_turn(cap=1000)
        seo_tools._semrush("phrase_related", _tenant="baci", phrase="x", display_limit=10)
        seo_tools._semrush("phrase_related", _tenant="baci", phrase="y", display_limit=10)
        got = seo_tools._semrush("phrase_related", _tenant="baci", phrase="z", display_limit=20)
        seo_tools.end_turn(tok)
        ck("what a turn spent counts against what it may still spend",
           str(got).startswith("refused") and len(http.calls) == 3, str(got)[:80])
        ksrc = open(os.path.join(ROOT, "app", "kernel.py")).read()
        ck("the kernel opens the budget around the step loop and closes it in a finally",
           re.search(r"_turn = _seo\.start_turn\(\)\n    try:\n", ksrc)
           and re.search(r"    finally:\n        _seo\.end_turn\(_turn\)\n", ksrc))

        print("\n— the harvest is checked once at the top and stops at the halt —")
        seams = {k: getattr(keywords, k) for k in
                 ("_fetch_gsc", "_fetch_own", "_fetch_gap", "_fetch_related", "_fetch_questions")}
        count = {"own": 0, "gap": 0, "related": 0, "questions": 0}

        def _own(p, limit):
            count["own"] += 1
            return [{"keyword": "acrylic pitcher", "volume": 900, "cpc": 1.0}]

        def _gap(p, limit):
            count["gap"] += 1
            return [{"keyword": "melamine bowls", "volume": 300}]

        def _rel(p, seed, limit):
            count["related"] += 1
            return [{"keyword": f"{seed} set", "volume": 70, "cpc": 1.0}]

        def _q(p, seed, limit):
            count["questions"] += 1
            return [{"question": f"how to store a {seed}", "volume": 40}]
        keywords._fetch_gsc = lambda p, d, l: []
        keywords._fetch_own, keywords._fetch_gap = _own, _gap
        keywords._fetch_related, keywords._fetch_questions = _rel, _q
        try:
            fresh_balance(500_000)
            out = keywords.harvest("baci")
            ck("with the door open the run buys its budget of new seeds",
               count["related"] == config.SEMRUSH_NEW_SEEDS_PER_RUN
               and count["questions"] == config.SEMRUSH_NEW_SEEDS_PER_RUN
               and not any("refused" in n or "halted" in n for n in out["notes"]),
               str(count))
            for k in count:
                count[k] = 0
            seo_tools._halt("API UNITS BALANCE IS ZERO", "baci")
            out = keywords.harvest("baci")
            ck("halted: no Semrush seam is touched and the note says why",
               count == {"own": 0, "gap": 0, "related": 0, "questions": 0}
               and any("halted" in n for n in out["notes"]), f"{count} {out['notes'][:1]}")
            fresh_balance(500_000)
            config.SEMRUSH_ACCOUNT_WEEKLY_CAP = 1000
            out = keywords.harvest("baci")
            ck("a harvest the cap cannot hold is refused before its first call",
               count == {"own": 0, "gap": 0, "related": 0, "questions": 0}
               and any(n.startswith("refused") for n in out["notes"]), f"{count}")
            config.SEMRUSH_ACCOUNT_WEEKLY_CAP = 10**6

            def _rel_then_halt(p, seed, limit):
                count["related"] += 1
                seo_tools._halt("API UNITS BALANCE IS ZERO", "baci")
                return []
            keywords._fetch_related = _rel_then_halt
            for k in count:
                count[k] = 0
            out = keywords.harvest("baci")
            ck("a door that shuts mid-run stops the loop at the next seed",
               count["related"] == 1 and count["questions"] == 1
               and any("halted" in n for n in out["notes"]), str(count))
            fresh_balance(500_000)
        finally:
            for k, v in seams.items():
                setattr(keywords, k, v)

        print("\n— the unattended top-up does not expand —")
        from app import systems as _sy
        real_find, real_due, real_harvest = _sy.find, keywords.harvest_due, keywords.harvest
        _sy.find = lambda t, k: object()
        keywords.harvest_due = lambda t: True
        keywords.harvest = lambda tenant, **kw: kw
        try:
            got = keywords.harvest_one("baci")
            ck("the cron's unit asks for the cheap sources only",
               got.get("sources") == keywords.UNATTENDED_SOURCES, str(got))
        finally:
            _sy.find, keywords.harvest_due, keywords.harvest = real_find, real_due, real_harvest

        print("\n— the rivals refresh and the snapshot are checked before their first read —")
        real_serp, real_scope = keywords._fetch_serp, keywords.rivals_scope
        serp = {"n": 0}

        def _serp(p, phrase, limit):
            serp["n"] += 1
            return [{"domain": "rival.com", "url": "https://rival.com/x", "position": 1}]
        keywords._fetch_serp = _serp
        keywords.rivals_scope = lambda t, *, top=12: ["acrylic jug", "acrylic pitcher"]
        try:
            seo_tools._halt("API UNITS BALANCE IS ZERO", "baci")
            got = keywords.rivals_refresh("baci")
            ck("halted: nothing is read and the result says refused",
               got["fetched"] == 0 and serp["n"] == 0 and "halted" in got["refused"], str(got))
            fresh_balance(500_000)
            got = keywords.rivals_refresh("baci")
            ck("open: both words are read", got["fetched"] == 2 and serp["n"] == 2, str(got))
        finally:
            keywords._fetch_serp, keywords.rivals_scope = real_serp, real_scope
        http = Http(CSV3)
        seo_tools.httpx.get = http
        seo_tools._halt("API UNITS BALANCE IS ZERO", "baci")
        got = seo_tools.capture_snapshot("bacimilanousa.com", "us", _tenant="baci")
        ck("the snapshot returns the halt and makes no request",
           "halted" in str(got) and not http.calls)
        fresh_balance(500_000)

        print("\n— a filter Semrush rejects costs an answer, not the harvest —")
        seen = {"n": 0}

        def _reject_filtered(url, params=None, timeout=None):
            seen["n"] += 1
            p = dict(params or {})
            if p.get("display_filter"):
                return _R("ERROR 50 :: SOMETHING WRONG WITH THE FILTER")
            return _R(CSV3)
        seo_tools.httpx.get = _reject_filtered
        got = seo_tools.semrush_related_keywords("jug", database="us", _tenant="baci")
        ck("the rows still come back, from one retry without the filter",
           got.startswith("[") and seen["n"] == 2, f"{seen['n']} request(s): {got[:50]}")
        rows = ledger("semrush_phrase_related", "baci")
        ck("and the rejection is recorded so the contract can be fixed",
           any("filter rejected" in (r.error or "") for r in rows),
           str([(r.ok, (r.error or "")[:40]) for r in rows[-2:]]))
        http = Http("ERROR 132 :: API UNITS BALANCE IS ZERO")
        seo_tools.httpx.get = http
        seo_tools.semrush("phrase_questions", _tenant="baci", phrase="zzz",
                          database="us", display_limit=25)
        ck("a zero balance is NOT retried — it is the door, not the filter",
           len(http.calls) == 1 and bool(seo_tools.halted()), f"{len(http.calls)}")
        fresh_balance(500_000)

        print("\n— the blog system says when its map cannot grow —")
        from app import systems as _sy
        _sy.create("baci", "blog")
        if True:
            seo_tools._halt("API UNITS BALANCE IS ZERO", "baci")
            r = keywords.readiness("baci", probe=False)
            know = r["knows_what_to_write"]
            ck("a halted door is a note on the blog system's own readiness",
               any("halted" in n for n in know["notes"]), str(know["notes"])[:120])
            ck("and it does not turn a working account red",
               know["ok"] == (not know["fix"]), f"ok={know['ok']} fix={know['fix']}")
            ck("the door's state travels with the numbers a page needs",
               know["research"]["halted"] is True
               and "next_top_up_units" in know["research"])
            page = admin_ui.render_plan("s3cret", "baci", sub="architecture")
            ck("and it reaches the Plan tab, where the control already is",
               "halted" in page and "Topping up costs" in page)
            fresh_balance(500_000)
            config.SEMRUSH_ACCOUNT_WEEKLY_CAP = 1
            know = keywords.readiness("baci", probe=False)["knows_what_to_write"]
            ck("an exhausted cap says the map cannot be topped up",
               any("cannot be topped up" in n for n in know["notes"]),
               str(know["notes"])[:120])
            config.SEMRUSH_ACCOUNT_WEEKLY_CAP = 10**6

        print("\n— the agent is told what its research costs —")
        from app.roles import seo as _seorole
        ident = _seorole.IDENTITY
        ck("it no longer leads with the most expensive report",
           "lead with semrush_opportunity_finder" not in ident)
        ck("it is told the order, cheapest first",
           "CHEAPEST SOURCE FIRST" in ident and "keyword map" in ident)
        ck("and what a refusal means, so it does not re-ask",
           "refused" in ident and "Never re-ask" in ident)

        print("\n— the worker reads the balance daily, and the health probe is free —")
        wsrc = open(os.path.join(ROOT, "app", "worker.py")).read()
        ck("the daily balance job is registered around _safe",
           re.search(r'_safe\(seo_tools\.balance_reading, "semrush balance"\)', wsrc) is not None)
        from app import web
        http = Http(lambda url, p: "777" if "countapiunits" in url else CSV3)
        seo_tools.httpx.get = http
        out = web.health_seo(key="s3cret")
        ck("/health/seo reports the balance and reaches only the balance endpoint",
           out.get("semrush_units") == 777 and out.get("semrush_probe") == "ok"
           and http.calls and all("countapiunits" in u for u, _ in http.calls), str(out.get("semrush_probe")))
        got = web.admin_semrush_balance(key="s3cret", tenant="baci")
        ck("the console control reads it too", got.get("units") == 777 and got.get("halted") == "")
        hsrc = open(os.path.join(ROOT, "app", "web.py")).read()
        body = hsrc[hsrc.index("def health_seo("):hsrc.index("@app.get(\"/admin/semrush_balance\")")]
        ck("the probe no longer spends a domain read", "semrush_domain_overview" not in body)
    finally:
        seo_tools.httpx.get = real_get
        (config.SEMRUSH_WEEKLY_CAP, config.SEMRUSH_ACCOUNT_WEEKLY_CAP,
         config.SEMRUSH_TURN_CAP) = caps

    print("\n" + ("ALL PASSED" if not _fail else f"{len(_fail)} FAILED: {_fail}"))
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
