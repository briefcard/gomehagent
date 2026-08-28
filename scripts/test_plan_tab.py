"""Plan is the strategy, not only the keyword map.

Spec §7 plus the owner's expanded intent (2026-08-27): *"keywords are a big
part of it but as we run different systems in parallel and add new systems
into it, the plan page should help make sense of what we want to do and how
each system fits into that plan."*

Three things this pins:

  · ONE WINDOW. `_board_section` was called with a LITERAL 7 while the 7/28/90
    control governed only the Progress section below it — so "Moved in the
    last 7 days" sat directly above a control that silently did not affect it.

  · STRATEGY REACHES THE OWNER. `strategy.read` has existed since the moments
    work, is deterministic, and was read by the planner and shown to nobody.

  · A DATELESS PLAN IS NOT SCHEDULED. `plan_complete` requires a valid date;
    one without can never come due, so listing it under a heading that says
    it will is the difference between "queued" and "lost".

    python3 scripts/test_plan_tab.py
"""
from __future__ import annotations

import datetime as dt
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'pt.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import (admin_ui, db, keywords, systems,  # noqa: E402
                 tenants, web)

_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    db.init_db()
    tenants.seed()
    systems.seed_from_tenants()
    T = "baci"
    for ph, vol in (("italian tableware", 2400), ("acrylic stemware", 590),
                    ("melamine plates outdoor", 320)):
        keywords.upsert(T, ph, volume=vol, source="test", database="us")

    # ---- 1. the rail ------------------------------------------------------
    print("— every room, and only one at a time —")
    landing = admin_ui.render_plan("s3cret", T)
    for v, _label in admin_ui.PLAN_SUBS:
        ck(f"the rail offers {v}", f"&amp;sub={v}" in landing)
    strat = admin_ui.render_plan("s3cret", T, sub="strategy")
    arch = admin_ui.render_plan("s3cret", T, sub="architecture")
    ck("a room renders alone, not stacked with the rest",
       'id="strategy"' in strat and "The architecture" not in strat,
       "the whole point of a rail is that you stop scrolling past four "
       "sections to reach the fifth")
    ck("  and the other room is reachable", "The architecture" in arch)

    # Readiness and the window govern EVERY room, so they stay above the rail.
    for v, _label in admin_ui.PLAN_SUBS:
        page = admin_ui.render_plan("s3cret", T, sub=v)
        ck(f"  readiness is above the rail on {v}", 'class="cards"' in page)

    # ---- 2. ONE window control -------------------------------------------
    print("\n— one window, governing every dated table —")
    ck("the control is rendered once, in the header",
       landing.count('href="/admin/ui?tab=plan') >= 3
       and "every dated table on this page reads this window" in landing)
    b7 = admin_ui.render_plan("s3cret", T, sub="board", days=7)
    b90 = admin_ui.render_plan("s3cret", T, sub="board", days=90)
    ck("the BOARD obeys it, not a hard-coded 7",
       "last 7 days" in b7 and "last 90 days" in b90,
       "it read 'Moved in the last 7 days' above a control that did nothing")
    p7 = admin_ui.render_plan("s3cret", T, sub="progress", days=7)
    p90 = admin_ui.render_plan("s3cret", T, sub="progress", days=90)
    ck("  and so does Progress", p7 != p90)

    # ---- 3. Strategy reaches the owner -----------------------------------
    print("\n— the programme, in front of the person who runs it —")
    ck("Strategy renders findings, named not scored",
       "What would change it:" in strat or "Nothing is out of balance" in strat,
       "a single 'strategy health: 62%' tells nobody what to do")
    ck("  with the honest zero when nothing has been sent",
       "give:ask not measurable yet" in strat or "per ask" in strat)
    ck("  and says what each SYSTEM is doing about it",
       "What each system is doing about it" in strat
       and "shipped this week" in strat,
       "this is the half the owner asked for: how each system fits the plan")
    rows = systems.for_tenant(T)
    ck("  naming every installed system, linking to its workflow",
       all(r.name in strat for r in rows)
       and all(f"system={r.key}" in strat for r in rows), str(len(rows)))

    # ---- 4. Schedule, and the plan that can never come due ---------------
    print("\n— what is coming, across every system —")
    empty = admin_ui.render_plan("s3cret", T, sub="schedule")
    ck("an empty schedule says so and names what fills it",
       "Nothing has been planned" in empty and "Plan queue" in empty)

    # Whichever plan-capable system this account actually has — the fixture
    # must not assume a catalogue entry is installed here.
    row = next(r for r in rows if systems.plan_capable(r.key))
    # Plans are only filed for a system that is ON — the `plan_switch_gate`
    # guard exists for that, so the fixture switches it on rather than
    # working around it.
    with db.SessionLocal() as s:
        s.get(db.System, row.id).status = "live"
        s.commit()
    # Empty plans on purpose: a plan's segment and entity are REFERENCES the
    # system validates, and inventing keys here would be testing that
    # refusal rather than the Schedule. An incomplete plan is also the state
    # the table has to render honestly.
    soon = (dt.date.today() + dt.timedelta(days=4)).isoformat()
    dated = systems.open_plan(T, row.key, ref="p-dated", plan={},
                              planned_for=soon, trigger="test")
    ck("the dated fixture plan was filed", "run_id" in dated, str(dated)[:120])
    got = systems.open_plan(T, row.key, ref="p-undated", plan={},
                            planned_for="", trigger="test")
    ck("the fixture filed two plans", "run_id" in got, str(got)[:120])
    if "run_id" not in got:
        return 1
    # `open_plan` fills a blank date with today on purpose, so the only way to
    # reach the lost state is a date that does not parse — which is exactly
    # what `plan_complete` refuses, and therefore what must not be listed as
    # scheduled.
    with db.SessionLocal() as s:
        r = s.get(db.SystemRun, got["run_id"])
        brief = dict(r.brief or {})
        brief["planned_for"] = "whenever"
        r.brief = brief
        s.commit()

    sched = admin_ui.render_plan("s3cret", T, sub="schedule")
    ck("a dated plan is listed with its date", soon in sched)
    ck("  naming the system it belongs to", row.name in sched)
    ck("a plan whose date cannot be read is NOT filed as scheduled",
       "no date" in sched and sched.index("no date") < sched.index(soon),
       "it reads as queued and means lost, so it leads rather than hides")
    ck("  and the page says why that matters",
       "can never come due" in sched)
    ck("an incomplete plan names its gap",
       "not a complete instruction" in sched or "still missing" in sched
       or "needs " in sched, "a plan waiting on a field says which field")

    # ---- 4b. WHAT BECAME OF IT (owner, 2026-08-27) -----------------------
    # Every Plan-side view filtered stage == PLANNED, so a plan VANISHED the
    # moment the tick consumed it: you could see what was coming and never
    # what happened to it. The plan row IS the run row, so this is one query.
    print("\n— and what became of what was planned —")
    shipped = systems.open_plan(T, row.key, ref="p-done", plan={},
                               planned_for=(dt.date.today()
                                            - dt.timedelta(days=6)).isoformat(),
                               trigger="test")
    systems.finish_run(shipped["run_id"], "sent", decision="approved",
                       output="campaign sent to 412 people")
    skipped = systems.open_plan(T, row.key, ref="p-skip", plan={},
                                planned_for=(dt.date.today()
                                             - dt.timedelta(days=2)).isoformat(),
                                trigger="test")
    systems.skip_plan(skipped["run_id"], reason="the offer moved to September")
    # An overdue plan the system cannot run: due days ago, still sitting.
    late = systems.open_plan(T, row.key, ref="p-late", plan={},
                             planned_for=(dt.date.today()
                                          - dt.timedelta(days=5)).isoformat(),
                             trigger="test")
    with db.SessionLocal() as s:
        s.get(db.System, row.id).status = "paused"   # so it cannot be consumed
        s.commit()

    sched2 = admin_ui.render_plan("s3cret", T, sub="schedule")
    ck("a plan that SHIPPED is still on the timeline",
       "shipped" in sched2 and "campaign sent to 412 people" in sched2,
       "it used to vanish the moment the tick consumed it")
    ck("a plan that was SKIPPED says so, with the reason",
       "skipped" in sched2 and "moved to September" in sched2,
       "a decision recorded, never a silent delete")
    ck("an overdue plan says it is overdue AND why it is stuck",
       "overdue 5d" in sched2 and "a plan is only consumed by a system that "
       "is on" in sched2,
       "the worker counts these as held and nothing told the owner")
    ck("  and the stuck ones LEAD the table",
       sched2.index("overdue 5d") < sched2.index("campaign sent to 412"),
       "the row that reads as queued and is not moving is the only one that "
       "needs a person")
    ck("  with a count at the top", "are not moving" in sched2)
    # A run nobody planned is not a deviation from the plan — it was never on
    # it. Tested by making one and looking for its own marker, rather than by
    # reading the sentence that says so.
    direct = systems.start_run(row.id, T, trigger="manual", ref="not-planned")
    systems.finish_run(direct, "sent", decision="approved",
                       output="MARKER-direct-run-never-planned")
    sched_d = admin_ui.render_plan("s3cret", T, sub="schedule")
    ck("a direct run is NOT listed as a departure from the plan",
       "MARKER-direct-run-never-planned" not in sched_d
       and "it carries no plan" in sched_d,
       "a run nobody planned is not a deviation — it was never on the plan")

    # The owner's own edits, carried forward and finally visible.
    with db.SessionLocal() as s:
        r = s.get(db.SystemRun, late["run_id"])
        br = dict(r.brief or {})
        br["edited"] = ["segment"]
        r.brief = br
        s.commit()
    sched3 = admin_ui.render_plan("s3cret", T, sub="schedule")
    ck("a field YOU changed is shown against the plan",
       "you changed:" in sched3 and "segment" in sched3,
       "`edited` has always been recorded so the planner cannot overwrite "
       "you — and was never shown to you")

    # ---- 5. the goal has its own room ------------------------------------
    print("\n— the goal is set once a quarter, so it is not always open —")
    goal = admin_ui.render_plan("s3cret", T, sub="goal")
    ck("the goal room holds the goal", 'id="goal"' in goal)
    ck("  with the set-form FOLDED, not open under a weekly section",
       "<details" in goal and "Set or change the goal" in goal)
    prog = admin_ui.render_plan("s3cret", T, sub="progress")
    ck("  and Progress no longer carries it", 'id="goal"' not in prog)

    # ---- 6. wide tables scroll rather than overflow ----------------------
    print("\n— a wide table scrolls inside itself —")
    ck("Progress's moves table is wrapped", "tblwrap" in prog)
    ck("  and so is the Schedule", "tblwrap" in sched)

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
