"""The board is scannable; the workflow view is where you work.

Spec §8. The system card was fifteen kinds of thing — identity, toggle,
workflow link, description, work strip, the full gate, the autonomy ladder,
run stats, promote/demote, an 8-field contract form, the guidance thread, a
hard-rule form and a run log — on every row, for every installed system, on a
board that never paginated. Drawing one row loaded that system's ENTIRE run
history three times over, so the all-accounts view multiplied that by five
clients.

And the on/off control rendered three different ways: two `.tog` states on the
board, and a Switch on / Pause button pair in the workflow view — two opposite
labelling conventions for one operation, one click apart.

    python3 scripts/test_systems_board.py
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'sb.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import admin_ui, approvals, db, systems, tenants, web  # noqa: E402

_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    db.init_db()
    tenants.seed()
    systems.seed_from_tenants()
    c = TestClient(web.app, base_url="https://testserver")
    board = c.get("/admin/ui?key=s3cret&tab=systems&tenant=baci").text
    rows = systems.for_tenant("baci")
    one = rows[0]

    # ---- 1. the board row is the scannable half --------------------------
    print("— what a board row carries —")
    ck("it names the system and its rung", one.name in board)
    ck("it carries the toggle", 'class="tog' in board)
    ck("it carries the gate as ONE chip",
       ">Ready</span>" in board or "Blocked &mdash;" in board
       or ">Running thin</span>" in board, "three states, not two")
    ck("it carries the work strip", "waiting on you" in board)
    ck("and the way in", "Workflow &rarr;" in board)

    print("\n— and what it no longer carries —")
    ck("the 8-field contract form is NOT on the board",
       "8 questions a system answers" not in board,
       "it was on every card, for every system, on every account")
    ck("the guidance thread is not either",
       "Make it a rule" not in board)
    ck("nor the five-number run stat",
       "</b> runs" not in board, "it lives once, on Runs, beside them")
    ck("nor the autonomy ladder / promote",
       "Promote to" not in board and "Down a rung" not in board)

    # ---- 2. all of it is still reachable, one click in -------------------
    print("\n— the workflow view has it all, behind a rail —")
    def wf(sub=""):
        return c.get(f"/admin/ui?key=s3cret&tab=systems&tenant=baci"
                     f"&system={one.key}" + (f"&wf={sub}" if sub else "")).text
    settings = wf("settings")
    ck("Settings holds the contract",
       "8 questions a system answers" in settings)
    ck("  the ladder and promote",
       any(x in settings for x in ("Promote to", "Top of the ladder",
                                   "Next rung")),
       "whichever rung it is on, the ladder is stated")
    ck("  and the full gate, not just the chip",
       "Ready." in settings or "cannot run at all" in settings
       or "Running thin." in settings)
    runs_v = wf("runs")
    ck("Runs holds the five numbers", "</b> runs" in runs_v)
    ck("the rail offers every section",
       all(f"&amp;wf={v}" in settings for v, _l in admin_ui.WORKFLOW_SUBS),
       "each section is a tab now, not a scroll")

    # ---- 3. ONE toggle convention ----------------------------------------
    print("\n— one toggle, everywhere —")
    ck("the workflow view uses the board's toggle component",
       'class="tog' in settings)
    ck("  and NOT the old button pair",
       ">Switch on</button>" not in settings and ">Pause</button>" not in settings,
       "two opposite labellings for one operation, one click apart")

    # ---- 4. the board asks the database once, not once per system --------
    print("\n— the board asks once —")
    seen: list[str] = []
    real = db.SessionLocal

    class _Spy:
        def __init__(self):
            self.s = real()

        def query(self, *a, **k):
            seen.append(getattr(a[0], "__name__", str(a[0])))
            return self.s.query(*a, **k)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return self.s.__exit__(*a)

        def __getattr__(self, n):
            return getattr(self.s, n)

    db.SessionLocal = _Spy
    try:
        admin_ui._board_counts(rows)
    finally:
        db.SessionLocal = real
    ck("every row's strip costs two queries, not five per system",
       seen.count("SystemRun") == 1 and seen.count("Approval") == 1,
       f"{seen} for {len(rows)} systems")

    # ---- 5. the board pages ----------------------------------------------
    # The cap is lowered rather than seeding sixteen system types: the
    # property under test is "the board pages", not "this fixture has enough
    # kinds of system". Checked against a REAL second page, because a pager
    # renders nothing at all when everything fits — so an assertion made
    # against the unpaged board would have passed without paging existing.
    print("\n— it pages —")
    real_cap = admin_ui.SYSTEMS_PAGE
    admin_ui.SYSTEMS_PAGE = 1
    try:
        paged = c.get("/admin/ui?key=s3cret&tab=systems&tenant=baci").text
        page2 = c.get("/admin/ui?key=s3cret&tab=systems&tenant=baci"
                      "&page=2").text
    finally:
        admin_ui.SYSTEMS_PAGE = real_cap
    ck("a pager appears once there is more than one page",
       'class="pager"' in paged and "older &rarr;" in paged, "was unpaginated")
    ck("  and it reports the real depth",
       f"of {len(rows)}</span>" in paged, str(len(rows)))
    ck("  page 1 shows only the first system",
       rows[0].name in paged and rows[1].name not in paged,
       "a cap that does not cap is decoration")
    ck("  and page 2 shows the next one",
       rows[1].name in page2 and rows[0].name not in page2)
    ck("the sub-tab count stays the REAL depth, not the page",
       f'<span class="cnt">{len(rows)}</span>' in paged, str(len(rows)))

    # ---- 6. deciding on the workflow view comes back to it ---------------
    print("\n— a decision keeps your place —")
    # `skill_output` records the decision and executes nothing — this test is
    # about WHERE you land afterwards, not about firing a live SEO write.
    ap = approvals.request_approval("skill_output", "Retitle something",
                                    {"skill": "ad_copy"}, notify=False)
    with db.SessionLocal() as s:
        row = s.get(db.Approval, ap)
        row.tenant, row.system_id = "baci", one.id
        s.commit()
    waiting = wf("waiting")
    ck("the queue decides in place, not through a bare /decide link",
       'action="/admin/ship_decide"' in waiting and "/decide/" not in waiting,
       "the same defect Review's queue was rebuilt to end")
    ck("  and the approve button states its consequence",
       "Approve" in waiting)
    r = c.post("/admin/ship_decide",
               data={"key": "s3cret", "tenant": "baci", "approval_id": ap,
                     "verdict": "approved", "back_system": one.key},
               params={"key": "s3cret"}, follow_redirects=False)
    loc = r.headers.get("location", "")
    ck("deciding returns to the system you decided from",
       "tab=systems" in loc and f"system={one.key}" in loc
       and "wf=waiting" in loc, loc)

    # ---- 7. the installer points at what it names ------------------------
    print("\n— the catalogue links at the thing —")
    avail = c.get("/admin/ui?key=s3cret&tab=systems&tenant=baci"
                  "&sub=available").text
    ck("an already-installed entry links to its workflow",
       "installed &middot;" in avail and "Workflow &rarr;" in avail,
       "it named a system and pointed nowhere")

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
