"""The nightly sweep — deterministic findings, and a model that is optional.

The owner asked how the system finds correlations rather than waiting to be
asked, and then asked for it to run in the evening on a cheap model. Both
constraints shape this: the correlation is computed in Python from rows we
already wrote, and the model only puts words around numbers it is handed. So
the cost is a few hundred tokens a night, and — the part this file exists to
hold — **the findings stand when the model does not run at all**. A sweep that
goes silent when an API key expires is worse than one that reads awkwardly.

    python3 scripts/test_correlate.py
"""
import datetime as dt
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'co.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ.pop("ANTHROPIC_API_KEY", None)      # the sweep must work without it
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import (approvals, assurance, correlate, db, kb,  # noqa: E402
                 systems, tenants, toolcalls, web)

_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def kinds(fs):
    return {f["kind"] for f in fs}


def main() -> int:
    db.init_db()
    tenants.seed()
    kb.ensure_brand("baci", "Baci Milano USA")

    print("— a quiet account produces no findings, and says which kind of quiet —")
    out = correlate.nightly(days=7)
    ck("nothing is invented", not out["findings"], str(out["findings"])[:60])
    ck("  and silence is not reported as health",
       "did not run" in out["note"],
       "a week where nothing ran and a clean week produce identical zeros")
    ck("  and nothing was delivered", out["delivered"] is False)

    print("\n— a dying connection outranks everything —")
    for _ in range(5):
        toolcalls.record("baci", "shopify:GET /products", provider="shopify",
                         ok=False, error="401 invalid token")
    toolcalls.record("baci", "shopify:GET /products", provider="shopify", ok=True)
    f = correlate.sweep("baci", 7)
    ck("it is found", "dead_connection" in kinds(f), str(kinds(f)))
    dead = [x for x in f if x["kind"] == "dead_connection"][0]
    ck("  carrying the provider's own words",
       any("401" in e for e in dead["evidence"]), str(dead["evidence"]))
    ck("  and it is the top finding", f[0]["kind"] == "dead_connection")

    print("\n— one bad call is not a pattern —")
    toolcalls.record("ironside", "gmail:GET /messages", provider="google",
                     ok=False, error="hiccup")
    ck("a single failure is not reported",
       "dead_connection" not in kinds(correlate.sweep("ironside", 7)),
       "reporting the internet nightly teaches people to ignore the sweep")

    print("\n— what is published under the client's name outranks nearly all of it —")
    # The weekly sweep records violations and nothing announced them. A
    # compliance check whose findings sit in a table is a check nobody acts on.
    from app import compliance
    cc = systems.create("baci", "content_compliance", "Website content")
    compliance.record_scan("baci", {
        "pages_checked": 42,
        "violations": [{"url": "https://x/p1",
                        "hits": [{"phrase": "hand-decorated", "context": "..."}]},
                       {"url": "https://x/p2",
                        "hits": [{"phrase": "made in Italy", "context": "..."}]}],
        "by_phrase": {"hand-decorated": 5, "made in Italy": 2}})
    f = correlate.sweep("baci", 7)
    site = [x for x in f if x["kind"] == "site_violations"]
    ck("live-site violations are reported", site, str(kinds(f)))
    ck("  naming which bans were breached, and how often",
       any("hand-decorated (5" in e for e in site[0]["evidence"]),
       str(site[0]["evidence"]))
    ck("  and saying they are already published",
       "published under the client's name" in site[0]["suggests"])
    ck("  outranking everything except a dead connection",
       site[0]["weight"] > 80 and f[0]["kind"] == "dead_connection",
       f"{site[0]['weight']} vs {f[0]['kind']}")

    print("\n— a clean site is not a finding —")
    compliance.record_scan("ironside", {"pages_checked": 10, "violations": [],
                                        "by_phrase": {}})
    ck("nothing is reported when there is nothing wrong",
       "site_violations" not in kinds(correlate.sweep("ironside", 7)))

    print("\n— the gap that cost the most output —")
    sysrow = systems.create("baci", "lead_responder", "Lead responder")
    for _ in range(4):
        r = systems.start_run(sysrow.id, "baci", trigger="inbound_email")
        systems.finish_run(r, "blocked", blocked_on=["lead_time"])
    f = correlate.sweep("baci", 7)
    gap = [x for x in f if x["kind"] == "knowledge_gap"]
    ck("it is found", gap, str(kinds(f)))
    ck("  naming what to go and write",
       any("lead_time" in e for e in gap[0]["evidence"]), str(gap[0]["evidence"]))

    print("\n— a rule the drafter keeps reaching for is its own finding —")
    for _ in range(4):
        assurance.record("baci", source="mail", checked=["banned_claims"],
                         caught=["banned_claim"], verdict="blocked")
    f = correlate.sweep("baci", 7)
    rule = [x for x in f if x["kind"] == "rule_keeps_firing"]
    ck("it is found", rule, str(kinds(f)))
    ck("  and it is framed as cost, not as risk",
       "stopped" in " ".join(rule[0]["evidence"]),
       "each one WAS caught — the finding is that it keeps happening")
    ck("  suggesting guidance rather than another rule",
       "guidance" in rule[0]["suggests"])

    print("\n— a queue nobody works —")
    for i in range(4):
        ap = approvals.request_approval("send_email", f"waiting {i}",
                                        {"tenant": "baci"}, notify=False)
        with db.SessionLocal() as s:
            row = s.get(db.Approval, ap)
            row.created_at = db.utcnow() - dt.timedelta(days=9)
            s.commit()
    f = correlate.sweep("baci", 7)
    q = [x for x in f if x["kind"] == "queue_not_worked"]
    ck("it is found", q, str(kinds(f)))
    ck("  and says a stalled queue looks like a working one",
       "looks identical" in q[0]["suggests"])

    print("\n— grounding that is not landing is separated from knowledge that is absent —")
    ck("no claims on file means no finding",
       "grounding_not_landing" not in kinds(correlate.sweep("baci", 7)),
       "nothing to cite is not a failure to cite")
    kb.add_situation("baci", "material_question", [["material"]], "what it is")
    kb.add_claim("baci", "The Aqua range is BPA-free acrylic", "spec sheet",
                 ["material_question"])
    for _ in range(3):
        assurance.record("baci", source="mail", checked=["banned_claims"],
                         caught=[], verdict="passed", grounded=False)
    f = correlate.sweep("baci", 7)
    gr = [x for x in f if x["kind"] == "grounding_not_landing"]
    ck("with claims on file and none cited, it IS a finding", gr, str(kinds(f)))
    ck("  and it names the right fix",
       "prompt problem" in gr[0]["suggests"],
       "opposite fixes: the knowledge is there and unused")

    print("\n— the sweep works with no model at all —")
    out = correlate.nightly(days=7)
    ck("it still delivers", out["delivered"] is True)
    ck("  without a narrator", out["narrated"] is False)
    ck("  and says so rather than pretending", "without the summariser" in out["body"])
    ck("  while every finding still carries its evidence",
       all(x["evidence"] for x in out["findings"]))
    ck("  and its suggested action", all(x["suggests"] for x in out["findings"]))

    print("\n— one message per sweep, never one per finding —")
    with db.SessionLocal() as s:
        n = s.query(db.Approval).filter(db.Approval.kind == "sweep").count()
    ck("a sweep with many findings queues once", n == 1, str(n),)

    print("\n— a broken check is reported, not skipped —")
    real = correlate._dead_connection
    correlate._dead_connection = lambda t, d: 1 / 0
    try:
        f = correlate.sweep("baci", 7)
    finally:
        correlate._dead_connection = real
    ck("the sweep survives", bool(f))
    ck("  and names the check that failed",
       any(x["kind"] == "sweep_error" for x in f),
       "a sweep that silently skips half its checks reads as a clean night")

    print("\n— the compliance sweep runs on a schedule at last —")
    # Both checks existed and NEITHER was scheduled. `compliance.scan` says in
    # its own docstring that `since` is "what makes this cheap enough to run on
    # a schedule", and nothing ever ran it.
    from app import compliance as _c, worker
    calls = {"scan": 0, "since": None}
    real_scan = _c.scan

    def _fake_scan(tenant, limit=60, since=""):
        calls["scan"] += 1
        calls["since"] = since
        return {"pages_checked": 3, "violations": [], "by_phrase": {}}

    _c.scan = _fake_scan
    try:
        switch_on("baci", "content_compliance")
        before = _runs("baci", "content_compliance")
        worker.compliance_sweep()
        after = _runs("baci", "content_compliance")
        ck("it scans a switched-on account", calls["scan"] >= 1)
        ck("  filing exactly ONE run, not two", after == before + 1,
           f"{after - before} runs — `record_scan` files its own; a second "
           f"here would double every scan and halve every rate from it")
        ck("  and the next pass only walks what changed",
           bool(calls["since"]), f"since={calls['since']!r}")

        # And the switch, again — it is the dictator everywhere.
        switch_off("baci", "content_compliance")
        n = calls["scan"]
        worker.compliance_sweep()
        ck("a switched-off account is not scanned", calls["scan"] == n)
    finally:
        _c.scan = real_scan

    print("\n— and turning it on is one call, with the refusals named —")
    c = TestClient(web.app)
    # `system_set` takes a uuid, so switching one thing on for five accounts
    # was five lookups and five calls — enough friction that it did not get
    # done, which is how a working scanner sat switched off.
    r = c.get("/admin/system_on?key=s3cret&system=content_compliance"
              "&install=1").json()
    ck("it addresses systems by name", "accounts" in r, str(r)[:70])
    ck("  and reports per account", len(r["accounts"]) >= 2, str(r["accounts"]))
    ck("  naming what is missing rather than skipping",
       any("live" == v or ":" in v for v in r["accounts"].values()),
       str(r["accounts"]))
    ck("an unknown system is refused with the list",
       "known" in c.get("/admin/system_on?key=s3cret&system=nope").json())
    ck("  and installing is opt-in",
       "not installed" in str(c.get(
           "/admin/system_on?key=s3cret&system=ad_creative").json()),
       "a route that quietly installs across every account is how somebody "
       "finds a pipeline they never chose")
    anon2 = TestClient(web.app)
    rr2 = anon2.get("/admin/system_on?system=content_compliance")
    ck("unauthorised cannot use it",
       rr2.status_code >= 400 or "error" in rr2.json(), str(rr2.status_code))

    print("\n— and the tick stops calling it un-built —")
    ck("content_compliance is scheduled elsewhere",
       "content_compliance" in systems.externally_driven())
    ck("  as is catalog_compliance",
       "catalog_compliance" in systems.externally_driven(),
       "a daily 'no generator yet' five days after it swept the whole site")

    print("\n— on demand, and read-only unless asked —")
    before = _sweeps()
    r = c.get("/admin/sweep?key=s3cret&tenant=baci").json()
    ck("it computes without delivering",
       r["findings"] and _sweeps() == before,
       "reading it a dozen times must not fill the queue")
    c.get("/admin/sweep?key=s3cret&run=1")
    ck("  and delivers when told to", _sweeps() == before + 1)
    anon = TestClient(web.app)
    rr = anon.get("/admin/sweep")
    ck("unauthorised cannot read it",
       rr.status_code >= 400 or "error" in rr.json(), str(rr.status_code))

    print()
    if _fail:
        print(f"{len(_fail)} FAILED:")
        for f_ in _fail:
            print(f"  - {f_}")
        return 1
    print("all checks passed")
    return 0


def switch_on(tenant, key):
    _set_status(tenant, key, "live")


def switch_off(tenant, key):
    _set_status(tenant, key, "paused")


def _set_status(tenant, key, status):
    """Directly, because `update(status="live")` is gated on readiness — a
    different rule from the one under test."""
    with db.SessionLocal() as s:
        row = (s.query(db.System).filter(db.System.tenant == tenant,
                                         db.System.key == key).first())
        row.status = status
        s.commit()


def _runs(tenant, key) -> int:
    with db.SessionLocal() as s:
        row = (s.query(db.System).filter(db.System.tenant == tenant,
                                         db.System.key == key).first())
        return s.query(db.SystemRun).filter(
            db.SystemRun.system_id == row.id).count() if row else 0


def _sweeps() -> int:
    with db.SessionLocal() as s:
        return s.query(db.Approval).filter(db.Approval.kind == "sweep").count()


if __name__ == "__main__":
    raise SystemExit(main())
