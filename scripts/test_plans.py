"""Offline exercise of the plans layer — work declared in advance of execution.

Covers the two mechanisms the owner asked for by name (2026-08-21) and the
gates around them: SAVING plan edits (validated, tracked, carried forward
across re-proposals) and the COMPLETENESS bar (an under-specified instruction
is never executed — it waits, visibly, with its gaps named). Plus: the switch
and the rung enforced at consumption structurally, the same-row consume in
`skill.run`, the tick's consumption loop, and planned rows counting as queue
— never as activity — in stats, promotion tails and diagnostics.

    python3 scripts/test_plans.py
"""
from __future__ import annotations

import datetime as dt
import os
import sys
import tempfile

_tmp = os.path.join(tempfile.mkdtemp(), "plans_test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, diagnostics, skill, systems, tenants  # noqa: E402
from app import skill_pack  # noqa: E402,F401  — registers the real skills

PASS, FAIL = "  ok  ", " FAIL "
_failures = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"[{PASS if cond else FAIL}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _failures.append(label)


TODAY = dt.date.today().isoformat()
FUTURE = (dt.date.today() + dt.timedelta(days=9)).isoformat()


def _probe_catalog() -> None:
    """Two throwaway catalogue systems: one plan-capable, one not."""
    systems.CATALOG["plan_probe"] = dict(
        name="Plan probe", does="test", requires=(), requires_any=(),
        needs_kb=False, kb_needs=(),
        workflow=dict(unit="one probe", skill="plan_probe",
                      plan_fields=(
                          dict(key="segment", label="Segment", required=True),
                          dict(key="goal", label="Goal", required=False),
                      ),
                      artifact="none", ship="", measure=""))
    systems.CATALOG["plain_probe"] = dict(
        name="Plain probe", does="test", requires=(), requires_any=(),
        needs_kb=False, kb_needs=())
    skill.register(skill.Skill(
        key="plan_probe", name="Plan probe", does="test",
        system_key="plan_probe", tier=1, params=("segment", "goal"),
        writes=False, produces="report", run=lambda ctx: {"summary": "ok"}))
    # A plan-capable system whose CONNECTION is absent — the queue that can
    # never drain until something is wired.
    systems.CATALOG["plan_probe_gated"] = dict(
        name="Plan probe gated", does="test", requires=("esp",),
        requires_any=(), needs_kb=False, kb_needs=(),
        workflow=dict(unit="one gated probe", skill="plan_probe_gated",
                      plan_fields=(
                          dict(key="segment", label="Segment", required=True),
                      ),
                      artifact="none", ship="", measure=""))
    skill.register(skill.Skill(
        key="plan_probe_gated", name="Plan probe gated", does="test",
        system_key="plan_probe_gated", tier=1, params=("segment",),
        writes=False, produces="report", run=lambda ctx: {"summary": "ok"}))


def _open_count(tenant: str) -> int:
    return len(systems.plans(tenant, "plan_probe"))


def main() -> int:
    db.init_db()
    tenants.seed()
    _probe_catalog()

    # ---- declarations ---------------------------------------------------
    print("\n— the workflow declaration —")
    for key in systems.CATALOG:
        wf = systems.workflow(key)
        check(f"{key}: workflow() answers with every field",
              all(f in wf for f in
                  ("unit", "skill", "plan_fields", "artifact", "ship", "measure")))
    check("campaign_email is plan-capable", systems.plan_capable("campaign_email"))
    check("lead_responder is not — inbound-driven systems take no plans",
          not systems.plan_capable("lead_responder"))
    # The drift pin: a plan field the consuming skill does not accept would
    # leave every plan waiting forever. Growing the plan (subject line, hero)
    # and teaching the skill must land in the same change, and this is what
    # forces it.
    for key in systems.CATALOG:
        wf = systems.workflow(key)
        if not (wf["plan_fields"] and wf["skill"]):
            continue
        sk = skill.get(wf["skill"])
        check(f"{key}: its consuming skill {wf['skill']!r} is registered",
              sk is not None)
        if sk:
            declared = {f["key"] for f in wf["plan_fields"]}
            check(f"{key}: every plan field is a parameter the skill accepts",
                  declared <= set(sk.params),
                  f"drifted: {sorted(declared - set(sk.params))}")

    # ---- opening plans --------------------------------------------------
    print("\n— open_plan refuses before it files —")
    check("no ref → refused",
          "stable item key" in (systems.open_plan(
              "agency", "plan_probe", ref="", plan={}).get("error") or ""))
    check("not installed → refused by name",
          "not installed" in (systems.open_plan(
              "agency", "lead_responder", ref="x").get("error") or ""))

    row = systems.create("agency", "plan_probe")
    out = systems.open_plan("agency", "plan_probe", ref="probe:1")
    check("designed is OFF — a planner never fills a queue for a system "
          "nobody switched on", "plans are only filed" in (out.get("error") or ""))
    systems.update(row.id, status="live")

    plain = systems.create("agency", "plain_probe")
    systems.update(plain.id, status="live")
    check("a system with no plan fields takes no plans",
          "declares no plan fields" in (systems.open_plan(
              "agency", "plain_probe", ref="x").get("error") or ""))
    check("an unknown plan field is refused BY NAME",
          "unknown plan field(s): nope" in (systems.open_plan(
              "agency", "plan_probe", ref="probe:1",
              plan={"nope": 1}).get("error") or ""))
    check("a malformed date is refused",
          "ISO date" in (systems.open_plan(
              "agency", "plan_probe", ref="probe:1", plan={},
              planned_for="soonish").get("error") or ""))

    print("\n— a plan is filed, and completeness names its gaps —")
    out = systems.open_plan("agency", "plan_probe", ref="probe:1",
                            plan={"goal": "warm them up"})
    check("filed", bool(out.get("ok")) and bool(out.get("created")))
    plan_a = out["run_id"]
    check("incomplete, and the gaps are NAMED",
          not out["complete"] and "Segment" in out["missing"]
          and "planned date" in out["missing"], str(out.get("missing")))

    # ---- saving — the owner's edit mechanism ----------------------------
    print("\n— save_plan: validated, tracked, blank is not an edit —")
    out = systems.save_plan(plan_a, {"segment": "vips"}, planned_for=TODAY)
    check("an edit lands and completeness flips",
          out.get("ok") and out["complete"], str(out))
    check("every accepted edit is tracked",
          set(out["edited"]) == {"segment", "planned_for"}, str(out.get("edited")))
    out = systems.save_plan(plan_a, {"goal": "   "})
    check("a blank input is NOT an edit — absence of typing must not clear "
          "a value", out.get("ok") and "goal" not in out["edited"])
    check("an unknown key is refused BY NAME",
          "unknown plan field(s): rogue" in (
              systems.save_plan(plan_a, {"rogue": "x"}).get("error") or ""))

    print("\n— re-proposal carries the owner's edits forward —")
    out = systems.open_plan("agency", "plan_probe", ref="probe:1",
                            plan={"segment": "everyone", "goal": "resell"},
                            planned_for=FUTURE)
    check("same ref updates, never double-files",
          out.get("updated") and _open_count("agency") == 1)
    check("the owner's field is preserved; the planner's is refreshed",
          "segment" in out["preserved"] and "goal" in out["refreshed"],
          str(out))
    check("the owner's date is preserved too", "planned_for" in out["preserved"])
    got = systems.plans("agency", "plan_probe")[0]
    check("the stored plan agrees",
          (got.brief["plan"]["segment"] == "vips"
           and got.brief["plan"]["goal"] == "resell"
           and got.brief["planned_for"] == TODAY))

    # ---- the consumption gates ------------------------------------------
    print("\n— consumable: the switch, the bar, the rung —")
    sysrow = systems.get(row.id)
    v = systems.consumable(got, sysrow)
    check("shadow + unapproved → held for your explicit approval",
          not v["ok"] and "approval" in v["why"], v["why"])
    check("approving an INCOMPLETE plan is refused — consent to an "
          "under-specified instruction is not consent",
          "not complete" in (systems.approve_plan(
              systems.open_plan("agency", "plan_probe", ref="probe:3",
                                plan={"segment": "s"})["run_id"])
              .get("error") or ""))
    check("approve_plan clears a complete one",
          systems.approve_plan(plan_a).get("ok") is True)
    got = systems.plans("agency", "plan_probe")[0]
    check("approved + complete + live → consumable",
          systems.consumable(got, systems.get(row.id))["ok"])

    systems.update(row.id, status="paused")
    v = systems.consumable(got, systems.get(row.id))
    check("PAUSED → not consumable — the switch dictates at the queue too",
          not v["ok"] and "on" in v["why"], v["why"])
    systems.update(row.id, status="live")

    incomplete = systems.plans("agency", "plan_probe")[-1]  # probe:3, dateless
    v = systems.consumable(incomplete, systems.get(row.id))
    check("incomplete → not consumable, gap NAMED",
          not v["ok"] and "planned date" in v["why"], v["why"])

    systems.update(row.id, autonomy="approve_exceptions")
    p4 = systems.open_plan("agency", "plan_probe", ref="probe:4",
                           plan={"segment": "s4"}, planned_for=TODAY)["run_id"]
    p4row = [r for r in systems.plans("agency", "plan_probe") if r.id == p4][0]
    check("approve_exceptions consumes a due plan without the extra tap",
          systems.consumable(p4row, systems.get(row.id))["ok"])
    systems.update(row.id, autonomy="shadow")

    print("\n— plans(): dateless is never due —")
    due = systems.plans("agency", "plan_probe", due_by=TODAY)
    check("due today: the dated ones only, dateless excluded",
          {r.id for r in due} == {plan_a, p4},
          f"got {len(due)}")

    # ---- consuming through skill.run ------------------------------------
    print("\n— skill.run(run_id=…): the same row becomes the execution —")
    baci_sys = systems.create("baci", "plan_probe")
    systems.update(baci_sys.id, status="live")
    out = skill.run("plan_probe", "baci", run_id=plan_a)
    check("another account cannot consume this plan",
          out["status"] == "refused" and "different account" in out["blocked_on"][0])
    out = skill.run("plan_probe", "agency", run_id=plan_a, segment="override")
    check("a caller may not override a plan field — the plan is the reviewed "
          "instruction", out["status"] == "refused"
          and "may not be overridden" in out["blocked_on"][0])
    out = skill.run("plan_probe", "agency", run_id=plan_a, bogus=1)
    check("an unknown caller parameter is refused BEFORE the plan is touched",
          out["status"] == "refused" and "unknown parameter" in out["blocked_on"][0])
    with db.SessionLocal() as s:
        check("…and after all three refusals the plan is still PLANNED",
              s.get(db.SystemRun, plan_a).stage == "planned")
        runs_before = s.query(db.SystemRun).filter(
            db.SystemRun.system_id == row.id).count()

    out = skill.run("plan_probe", "agency", run_id=plan_a)
    with db.SessionLocal() as s:
        r = s.get(db.SystemRun, plan_a)
        runs_after = s.query(db.SystemRun).filter(
            db.SystemRun.system_id == row.id).count()
    check("the consume ran", out["status"] in ("empty", "produced"), out["status"])
    check("the SAME row advanced to a terminal stage — one row is one item",
          out["run_id"] == plan_a and r.stage == "sent", r.stage)
    check("no second row was filed", runs_after == runs_before)
    check("the plan SURVIVES execution — the brief is the record of what "
          "this run was asked to do",
          (r.brief or {}).get("plan", {}).get("segment") == "vips")
    check("a consumed plan can no longer be edited",
          "already consumed" in (systems.save_plan(
              plan_a, {"segment": "late"}).get("error") or ""))

    print("\n— declaration drift is refused at the last gate too —")
    old_fields = systems.CATALOG["plan_probe"]["workflow"]["plan_fields"]
    systems.CATALOG["plan_probe"]["workflow"]["plan_fields"] = old_fields + (
        dict(key="rogue", label="Rogue", required=False),)
    p5 = systems.open_plan("agency", "plan_probe", ref="probe:5",
                           plan={"segment": "s5", "rogue": "r"},
                           planned_for=TODAY)["run_id"]
    systems.approve_plan(p5)
    out = skill.run("plan_probe", "agency", run_id=p5)
    check("a plan carrying a field the skill does not accept waits, named",
          out["status"] == "refused" and "drifted" in out["blocked_on"][0])
    systems.CATALOG["plan_probe"]["workflow"]["plan_fields"] = old_fields
    systems.skip_plan(p5, reason="drift probe done")

    # ---- queue is not activity ------------------------------------------
    print("\n— planned rows are queue, never activity —")
    st = systems.stats(row.id)
    with db.SessionLocal() as s:
        planned_n = s.query(db.SystemRun).filter(
            db.SystemRun.system_id == row.id,
            db.SystemRun.stage == "planned").count()
        total_n = s.query(db.SystemRun).filter(
            db.SystemRun.system_id == row.id).count()
    check("there are open plans on the ledger", planned_n >= 2, str(planned_n))
    check("stats() counts none of them", st["total"] == total_n - planned_n,
          f"total {st['total']} vs rows {total_n} ({planned_n} planned)")

    # Backdate an open plan past the stale-run window: a plan for next week
    # must never read as a dead worker.
    with db.SessionLocal() as s:
        stale = s.get(db.SystemRun, p4)
        stale.created_at = db.utcnow() - dt.timedelta(hours=50)
        s.commit()
    h = diagnostics.health("agency")
    mine = [x for x in h["systems"] if x["key"] == "plan_probe"][0]
    check("diagnostics: open plans report as QUEUED", mine["queued"] >= 2,
          str(mine["queued"]))
    check("…and a plan older than the stale window is NOT an unfinished run",
          mine["unfinished"] == 0, str(mine["unfinished"]))
    check("…and runs counts activity only", mine["runs"] == st["total"])

    # ---- the tick consumes ----------------------------------------------
    print("\n— systems_tick: due plans run; held plans wait, visibly —")
    from app import worker
    systems.update(row.id, autonomy="approve_exceptions")
    p6 = systems.open_plan("agency", "plan_probe", ref="probe:6",
                           plan={"segment": "s6"}, planned_for=TODAY)["run_id"]
    systems.open_plan("agency", "plan_probe", ref="probe:7",
                      plan={"segment": "s7"}, planned_for=FUTURE)

    p7 = systems.plans("agency", "plan_probe", due_by=FUTURE)
    future_id = [r.id for r in p7 if r.ref == "probe:7"][0]

    calls = []
    real_run = skill.run
    skill.run = lambda *a, **k: calls.append((a, k)) or {"status": "empty"}
    try:
        worker.systems_tick()
    finally:
        skill.run = real_run
    consumed_ids = {k.get("run_id") for _a, k in calls}
    check("EVERY due, consumable plan was handed to skill.run — and only those",
          consumed_ids == {p4, p6}, str(sorted(consumed_ids)))
    check("the future plan was not", future_id not in consumed_ids)
    with db.SessionLocal() as s:
        eval_rows = (s.query(db.SystemRun)
                     .filter(db.SystemRun.system_id == row.id,
                             db.SystemRun.stage.in_(("skipped", "not_built")),
                             db.SystemRun.trigger == "schedule").count())
    check("a day where plans ran files NO evaluation row — the consumed "
          "runs are the record", eval_rows == 0, str(eval_rows))

    systems.update(row.id, autonomy="approve_all")
    calls.clear()
    skill.run = lambda *a, **k: calls.append((a, k)) or {"status": "empty"}
    try:
        worker.systems_tick()
    finally:
        skill.run = real_run
    check("on approve_all an unapproved plan is HELD, not run", not calls)
    with db.SessionLocal() as s:
        quiet = (s.query(db.SystemRun)
                 .filter(db.SystemRun.system_id == row.id,
                         db.SystemRun.stage == "skipped",
                         db.SystemRun.trigger == "schedule")
                 .order_by(db.SystemRun.created_at.desc()).first())
    check("…and the quiet-day row says so", quiet is not None
          and "held" in (quiet.output or ""),
          (quiet.output or "")[:80] if quiet else "no quiet row filed")

    # ---- a segment is a REFERENCE, not free text ------------------------
    print("\n— a plan's segment must point at a real catalog segment —")
    camp = systems.create("baci", "campaign_email")
    with db.SessionLocal() as s:
        s.get(db.System, camp.id).status = "live"
        s.commit()
    out = systems.open_plan("baci", "campaign_email", ref="ref:1",
                            plan={"segment": "everyone_ever",
                                  "goal": "g"}, planned_for=TODAY)
    check("a made-up segment key is refused, naming it AND the real ones",
          "unknown segment 'everyone_ever'" in (out.get("error") or "")
          and "reorder_due" in (out.get("error") or ""),
          (out.get("error") or "")[:80])
    out = systems.open_plan("baci", "campaign_email", ref="ref:1",
                            plan={"segment": "reorder_due", "goal": "g"},
                            planned_for=TODAY)
    check("a real catalog key files", out.get("ok") is True)
    check("save_plan holds the same line — a hand-built URL cannot sneak "
          "one past the form's select",
          "unknown segment 'nope'" in (systems.save_plan(
              out["run_id"], {"segment": "nope"}).get("error") or ""))
    check("…while the probe's kindless segment field stays free text",
          systems.open_plan("agency", "plan_probe", ref="freetext:1",
                            plan={"segment": "anything at all"},
                            planned_for=TODAY).get("ok") is True)

    # ---- a refusal is not a consumption ---------------------------------
    print("\n— a blocked system's due plans do not read as consumed —")
    gated = systems.create("agency", "plan_probe_gated")
    with db.SessionLocal() as s:
        # `update()` correctly refuses go-live with no ESP wired; force the
        # status so the tick evaluates exactly that misconfigured state.
        s.get(db.System, gated.id).status = "live"
        s.get(db.System, gated.id).autonomy = "approve_exceptions"
        s.commit()
    gp = systems.open_plan("agency", "plan_probe_gated", ref="gated:1",
                           plan={"segment": "g"}, planned_for=TODAY)["run_id"]
    worker.systems_tick()          # the REAL skill.run — preflight blocks it
    with db.SessionLocal() as s:
        gprow = s.get(db.SystemRun, gp)
        evals = (s.query(db.SystemRun)
                 .filter(db.SystemRun.system_id == gated.id,
                         db.SystemRun.stage == "blocked").all())
    check("the plan is untouched — still planned", gprow.stage == "planned")
    check("…and the day filed a BLOCKED evaluation row naming the gap",
          len(evals) == 1 and any("esp" in b for b in (evals[0].blocked_on or [])),
          str([e.blocked_on for e in evals]))

    # ---- skipping is a decision -----------------------------------------
    print("\n— skip_plan —")
    out = systems.skip_plan(p6, reason="not this week")
    check("skipping records a decision", out.get("ok") is True)
    with db.SessionLocal() as s:
        r = s.get(db.SystemRun, p6)
    check("…as a terminal skipped run, denied, reason kept",
          r.stage == "skipped" and r.decision == "denied"
          and (r.brief or {}).get("skip_reason") == "not this week")
    check("a skipped plan cannot be skipped twice",
          "not a plan any more" in (systems.skip_plan(p6).get("error") or ""))

    print()
    if _failures:
        print(f"{len(_failures)} FAILED: {_failures}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
