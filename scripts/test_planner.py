"""Offline exercise of the campaign rollout planner and the tick's top-up.

What must hold: the planner proposes ONLY what it reads from data (segment
key + catalog angle; never a subject, never an invented value), respects the
monthly cap per segment — counting skipped items, because a skip was a
decision — paces itself (at most one new item per segment per run), carries
the owner's edits forward through a refresh, refuses by name when the
account has no business model, and reaches the tick through the registry so
a paused system proposes nothing.

    python3 scripts/test_planner.py
"""
from __future__ import annotations

import datetime as dt
import os
import sys
import tempfile

_tmp = os.path.join(tempfile.mkdtemp(), "planner_test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, planner, segments, systems, tenants  # noqa: E402

PASS, FAIL = "  ok  ", " FAIL "
_failures = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"[{PASS if cond else FAIL}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _failures.append(label)


TODAY = dt.date.today()


def _force(sys_id: str, **fields) -> None:
    with db.SessionLocal() as s:
        r = s.get(db.System, sys_id)
        for k, v in fields.items():
            setattr(r, k, v)
        s.commit()


def _rows(sys_id: str, prefix: str = "") -> list:
    with db.SessionLocal() as s:
        q = s.query(db.SystemRun).filter(db.SystemRun.system_id == sys_id)
        if prefix:
            q = q.filter(db.SystemRun.ref.like(prefix + "%"))
        rows = q.all()
        s.expunge_all()
        return rows


def main() -> int:
    db.init_db()
    tenants.seed()

    # ---- cadence: defaults, overrides, refusals -------------------------
    print("\n— cadence: the owner's number, validated at the knob —")
    row = systems.create("baci", "campaign_email")
    _force(row.id, status="live", autonomy="approve_all")
    row = systems.get(row.id)
    cad = planner.cadence_for(row)
    check("defaults are the declared conservative pair",
          cad == {"horizon_days": 21, "per_segment_monthly": 1}, str(cad))
    out = systems.set_cadence(row.id, horizon_days="35")
    check("a valid override lands, the blank box left alone",
          out.get("ok") and planner.cadence_for(systems.get(row.id))
          == {"horizon_days": 35, "per_segment_monthly": 1})
    check("junk is refused by name",
          "whole number" in (systems.set_cadence(row.id,
                             per_segment_monthly="lots").get("error") or ""))
    check("an over-cap value is refused, not clamped silently",
          "between 1 and" in (systems.set_cadence(row.id,
                              horizon_days="900").get("error") or ""))
    check("two blank boxes are refused rather than a silent no-op",
          "nothing to set" in (systems.set_cadence(row.id).get("error") or ""))
    systems.set_cadence(row.id, horizon_days="21")
    row = systems.get(row.id)

    # ---- the rollout: data only, capped, paced ---------------------------
    print("\n— the rollout proposes from the catalog, and only from it —")
    high = segments.for_tenant("baci")["high_value"]
    out = planner.top_up(row)
    check("first run proposes one per high-value segment",
          out["ok"] and out["proposed"] == len(high),
          f"{out['proposed']} of {len(high)}")
    plans = systems.plans("baci", "campaign_email")
    by_seg = {(p.brief or {}).get("plan", {}).get("segment"): p for p in plans}
    seg0 = high[0]
    p0 = by_seg[seg0["key"]]
    check("the goal is the catalog's own angle — read, not written",
          p0.brief["plan"]["goal"] == seg0["angle"])
    check("no subject is proposed — no source holds one",
          all("subject" not in (p.brief or {}).get("plan", {}) for p in plans))
    check("refs carry the item key format",
          all((p.ref or "").startswith(f"campaign:baci:") for p in plans))
    dates = sorted((p.brief or {}).get("planned_for", "") for p in plans)
    lead = (TODAY + dt.timedelta(days=planner.LEAD_DAYS)).isoformat()
    horizon = (TODAY + dt.timedelta(days=21)).isoformat()
    check("every date sits inside [lead, horizon]",
          all(lead <= d <= horizon for d in dates), str(dates))
    check("slots are spaced, not stacked on one day", len(set(dates)) == len(dates))

    print("\n— it tops up to the horizon, then goes quiet —")
    total_runs = 0
    for _ in range(6):
        got = planner.top_up(systems.get(row.id))
        total_runs += 1
        if got["proposed"] == 0:
            break
    check("proposing reaches zero rather than growing forever",
          got["proposed"] == 0, f"after {total_runs} runs")
    allrows = _rows(row.id, "campaign:baci:")
    refs = [r.ref for r in allrows]
    check("no ref was ever filed twice", len(refs) == len(set(refs)))
    permonth: dict[tuple, int] = {}
    for r in allrows:
        seg_key = r.ref.split(":")[2]
        month = r.ref.rsplit(":", 1)[1][:7]
        permonth[(seg_key, month)] = permonth.get((seg_key, month), 0) + 1
    check("no segment exceeds its monthly cap",
          all(n <= 1 for n in permonth.values()), str(permonth))

    print("\n— a refresh cannot write over the owner —")
    systems.set_cadence(row.id, per_segment_monthly="2")
    systems.save_plan(p0.id, {"goal": "OWNERANGLE"})
    got = planner.top_up(systems.get(row.id))
    check("the same-slot proposal became a refresh, not a duplicate",
          got["refreshed"] >= 1, str(got))
    with db.SessionLocal() as s:
        p0b = s.get(db.SystemRun, p0.id)
    check("…and the owner's angle survived it",
          (p0b.brief or {}).get("plan", {}).get("goal") == "OWNERANGLE")
    systems.set_cadence(row.id, per_segment_monthly="1")

    print("\n— a skipped month stays skipped —")
    target = by_seg[high[1]["key"]]
    tprefix = f"campaign:baci:{high[1]['key']}:"
    tmonth = (target.brief or {}).get("planned_for", "")[:7]
    before = len([r for r in _rows(row.id, tprefix)
                  if r.ref.rsplit(":", 1)[1][:7] == tmonth])
    systems.skip_plan(target.id, reason="not this month")
    planner.top_up(systems.get(row.id))
    after = len([r for r in _rows(row.id, tprefix)
                 if r.ref.rsplit(":", 1)[1][:7] == tmonth])
    check("the planner does not re-propose a month the owner declined",
          after == before, f"{before} -> {after}")

    # ---- refusals, named -------------------------------------------------
    print("\n— refusals name the missing thing —")
    with db.SessionLocal() as s:
        s.add(db.Tenant(key="modelless", name="No Model Yet"))
        s.commit()
    m = systems.create("modelless", "campaign_email")
    _force(m.id, status="live")
    got = planner.top_up(systems.get(m.id))
    check("no business model → refused by name, nothing filed",
          not got["ok"] and any("business_model" in r for r in got["refusals"])
          and not _rows(m.id))
    _force(row.id, status="paused")
    got = planner.top_up(systems.get(row.id))
    check("a paused system proposes nothing, and says so",
          got["proposed"] == 0 and any("off" in r or "paused" in r
                                       for r in got["refusals"]))
    _force(row.id, status="live")
    check("a system with no planner returns None — a different fact from "
          "'proposed nothing'",
          planner.top_up(systems.get(systems.create("baci", "blog").id)) is None)

    # ---- the tick reaches planners through the registry ------------------
    print("\n— the tick tops up through the registry —")
    from app import skill, worker
    systems.CATALOG["plan_probe"] = dict(
        name="Plan probe", does="test", requires=(), requires_any=(),
        needs_kb=False, kb_needs=(),
        workflow=dict(unit="one probe", skill="plan_probe",
                      plan_fields=(dict(key="segment", label="Segment",
                                        required=True),),
                      artifact="none", ship="", measure=""))
    skill.register(skill.Skill(
        key="plan_probe", name="Plan probe", does="test",
        system_key="plan_probe", tier=1, params=("segment",),
        writes=False, produces="report", run=lambda ctx: {"summary": "ok"}))
    probe_live = systems.create("agency", "plan_probe")
    systems.update(probe_live.id, status="live")
    probe_off = systems.create("ironside", "plan_probe")

    calls: list[str] = []
    planner.PLANNERS["plan_probe"] = (
        lambda sysrow: calls.append(sysrow.tenant) or
        {"ok": True, "proposed": 0, "refreshed": 0,
         "refusals": ["STUBREFUSAL"]})
    try:
        worker.systems_tick()
    finally:
        planner.PLANNERS.pop("plan_probe", None)
    check("the live probe's planner ran once", calls == ["agency"], str(calls))
    with db.SessionLocal() as s:
        quiet = (s.query(db.SystemRun)
                 .filter(db.SystemRun.system_id == probe_live.id,
                         db.SystemRun.stage == "skipped")
                 .order_by(db.SystemRun.created_at.desc()).first())
    check("…and its refusal reached the quiet-day row",
          quiet is not None and "STUBREFUSAL" in (quiet.output or ""),
          (quiet.output or "")[:80] if quiet else "no row")

    print()
    if _failures:
        print(f"{len(_failures)} FAILED: {_failures}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
