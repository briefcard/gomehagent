"""The weekly number files itself: one plan per ISO week, never more.

`reports` had a skill and an executor and no planner, so the week's report
existed only when somebody remembered. `report_rollout` walks the horizon a
week at a time and files one plan per ISO week under a ref that names the
week — `open_plan` is idempotent per ref, so that ref IS the calendar. The
recipient is the one field no planner can read from data; it is required and
left absent, so an unfilled plan says so.

Run: python3 scripts/test_report_planner.py
"""
import datetime as dt
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'rp.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, planner, systems, tenants  # noqa: E402

_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _plans(row):
    with db.SessionLocal() as s:
        return (s.query(db.SystemRun)
                .filter(db.SystemRun.system_id == row.id,
                        db.SystemRun.trigger == "planner").all())


def main() -> int:
    db.init_db()
    tenants.seed()
    row = systems.find("baci", "reports") or systems.create("baci", "reports")
    with db.SessionLocal() as s:
        s.get(db.System, row.id).status = "live"
        s.commit()

    ck("the reports knob is declared once, in KNOBS",
       "reports_weekly" in planner.KNOBS and planner.KNOBS["reports_weekly"]["cap"] >= 1)
    cad = planner.report_cadence_for(systems.find("baci", "reports"))
    ck("  and the reports cadence carries it",
       cad.get("reports_weekly") == 1 and cad.get("horizon_days") == 14, str(cad))
    ck("  and the cadence form renders it for this system",
       any(k["key"] == "reports_weekly" for k in planner.knobs_for(systems.find("baci", "reports"))),
       "a knob the planner reads and the form does not offer is one nobody can turn")
    ck("the planner is registered for reports", planner.PLANNERS.get("reports") is planner.report_rollout)

    today = db.utcnow().date()
    weeks = {(today + dt.timedelta(days=i)).isocalendar()[:2]
             for i in range(0, 15)}
    p1 = planner.report_rollout(systems.find("baci", "reports"))
    n1 = len(_plans(row))
    ck("one plan per ISO week across the horizon, and no more",
       p1["proposed"] == len(weeks) == n1, f"{p1} vs {len(weeks)} week(s), {n1} plan(s)")
    p2 = planner.report_rollout(systems.find("baci", "reports"))
    ck("a second pass refreshes every week and creates none — the pair",
       p2["proposed"] == 0 and p2["refreshed"] == len(weeks) and len(_plans(row)) == n1,
       f"{p2}; {len(_plans(row))} plan(s) after, {n1} before")

    refs = [r.ref for r in _plans(row)]
    ck("every plan's ref names its ISO week",
       refs and all("-W" in (r or "") for r in refs), str(refs)[:120])
    # The brief nests the fields under `plan` beside `edited` and `planned_for`.
    briefs = [dict((getattr(r, "brief", None) or {}).get("plan") or {}) for r in _plans(row)]
    ck("the plan carries the window and leaves the recipient for the owner",
       briefs and all(b.get("days") == 7 and "to" not in b for b in briefs), str(briefs[:1]))
    ck("  because `to` is the required field no planner can read from data",
       any(f["key"] == "to" and f["required"]
           for f in systems.CATALOG["reports"]["workflow"]["plan_fields"]))

    print()
    print("PASS" if not _fail else f"FAILED: {len(_fail)}")
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
