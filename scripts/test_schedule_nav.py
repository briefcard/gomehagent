"""The Schedule sorts by its columns, and its links land on the actual card.

Owner, 2026-09-02:
  1. *"On the plan page, I want to be able to sort the columns with a default
     by date."*
  2. *"I want the clickable link to take you to the specific planned action in
     the respective system — right now it just takes you to the system page
     not the card for that specific planned action."*

THE CARD HAS CARRIED `id="plan-<id>"` ALL ALONG and nothing ever linked to it.
A bare `#plan-<id>` would still have missed, because the queue paginates: the
card named is often three pages down, and a link that lands on page one reads
as a link that does not work. So the URL names the PLAN and
`_planned_section` resolves which page holds it.

SORTED BY DATE BY DEFAULT. The old order led with state — overdue first —
which is the right default for triage and the wrong one for reading a
calendar, and it could not be changed at all.

Run: python3 scripts/test_schedule_nav.py
"""
import datetime as dt
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'sn.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import admin_ui, db, kb, systems, tenants  # noqa: E402

KEY = "s3cret"
_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _live(tenant, key):
    row = systems.find(tenant, key) or systems.create(tenant, key)
    with db.SessionLocal() as s:
        s.get(db.System, row.id).status = "live"
        s.commit()
    return systems.find(tenant, key)


def main() -> int:
    db.init_db()
    tenants.seed()
    kb.ensure_brand("baci", "Baci")
    blog = _live("baci", "blog")

    # Enough plans to paginate, with dates deliberately out of filing order so
    # "sorted by date" cannot pass by accident on insertion order.
    n = admin_ui.PLANS_PAGE * 2 + 3
    # DATES SCRAMBLED AGAINST INSERTION ORDER, deterministically. Filing them
    # in date order made insertion order, creation order and date order all
    # agree — so sorting by `state` (identical rank for every open plan, hence
    # a stable no-op) produced the same list as sorting by date, and a guard
    # flipping the default reported MISSED. No two orderings coincide now.
    offsets = {i: ((i * 7) % n) + 1 for i in range(n)}
    for i in range(n):
        day = dt.date.today() + dt.timedelta(days=offsets[i])
        systems.open_plan("baci", "blog", ref=f"article:baci:kw-{i:02d}",
                          plan={"keyword": f"kw {i:02d}"},
                          planned_for=day.isoformat(), trigger="planner")
    plans = systems.plans("baci", "blog")
    ck("the queue paginates", len(plans) > admin_ui.PLANS_PAGE,
       f"{len(plans)} plans, {admin_ui.PLANS_PAGE} per page — without this the "
       f"deep link would pass whatever it did")

    print()
    print("— the link names the plan, not just the system —")
    sched = " ".join(admin_ui._schedule_section(KEY, "baci").split())
    last = plans[-1]
    ck("every row links to its own plan",
       f"plan={last.id}" in sched and f"#plan-{last.id}" in sched,
       "the anchor existed; nothing pointed at it")
    ck("  and still carries the system it belongs to",
       "tab=systems" in sched and "system=blog" in sched)

    print()
    print("— and the queue opens on the page that holds it —")
    # A plan deliberately NOT on page one.
    deep = plans[admin_ui.PLANS_PAGE + 1]
    page1 = " ".join(admin_ui._planned_section(KEY, blog, 1).split())
    # WRITTEN PLAINLY. The first cut read `X in page1 is False or X not in
    # page1` — a chained comparison or'd with its own negation, which is true
    # for every input. It would have passed with the card ON page one, making
    # the assertion below meaningless.
    ck("it is absent from page one",
       f'id="plan-{deep.id}"' not in page1,
       "otherwise the next assertion proves nothing")
    landed = " ".join(
        admin_ui._planned_section(KEY, blog, 1, deep.id).split())
    ck("naming it brings its card onto the page",
       f'id="plan-{deep.id}"' in landed,
       "a link that lands on page one while the card is on page three reads "
       "as a link that does not work")
    ck("  and an unknown id does not blank the queue",
       'class="plan' in " ".join(
           admin_ui._planned_section(KEY, blog, 1, "no-such-id").split()),
       "a stale bookmark must degrade to page one, not to nothing")

    print()
    print("— the columns sort, and the default is date —")
    def _order(html):
        import re
        return re.findall(r"kw \d\d", html)

    default = _order(" ".join(admin_ui._schedule_section(KEY, "baci").split()))
    by_when = _order(" ".join(
        admin_ui._schedule_section(KEY, "baci", "when").split()))
    ck("no sort given behaves as `when`", default == by_when,
       "the default has to BE a column, not a fourth secret order")
    # THE WHOLE ORDER, against the dates themselves. `default[0] == X or
    # default[:1] != Y` passed on whichever clause happened to hold — here the
    # weaker one — and would have accepted almost any ordering.
    want = sorted((f"kw {i:02d}" for i in range(n)),
                  key=lambda k: offsets[int(k.split()[1])])
    ck("  and that order is by date, not by filing order",
       default == want[:len(default)],
       f"{default[:3]} vs {want[:3]}")
    ck("  which is a DIFFERENT order from how they were filed",
       want[:len(default)] != [f"kw {i:02d}" for i in range(len(default))],
       "if the two agreed, sorting by date would pass without sorting")
    desc = _order(" ".join(
        admin_ui._schedule_section(KEY, "baci", "when", True).split()))
    ck("  and it reverses", desc == list(reversed(default)),
       f"{desc[:3]} vs {default[:3]}")

    # A DIFFERENT COLUMN MUST GIVE A DIFFERENT ORDER. Every assertion above
    # compares a sort to `when` or to its reverse, so pinning the key to
    # `when` for every column left them all green — the guard reported MISSED.
    by_planned = _order(" ".join(
        admin_ui._schedule_section(KEY, "baci", "planned").split()))
    ck("sorting by another column really reorders",
       by_planned != by_when and sorted(by_planned) == sorted(by_when),
       f"{by_planned[:3]} vs {by_when[:3]} — same rows, different order; "
       f"equal lists would mean the column was ignored")
    ck("  and by that column's own values",
       by_planned == sorted(by_planned),
       f"{by_planned[:3]} — `planned` holds the keyword text, so its order "
       f"is alphabetical")

    print()
    print("— a stuck row leads, WITHIN whatever order you chose —")
    # The first cut sorted purely by the column and said in its own comment
    # that stuck rows still led. `test_plan_tab` caught it; asserted here too,
    # where the sort lives, because a claim in a comment is not a check.
    stuck_ref = "article:baci:kw-07"
    with db.SessionLocal() as sx:
        r = (sx.query(db.SystemRun)
             .filter(db.SystemRun.ref == stuck_ref).first())
        b = dict(r.brief or {})
        b["planned_for"] = (dt.date.today() - dt.timedelta(days=9)).isoformat()
        r.brief = b
        sx.commit()
    for col in ("when", "system", "planned", "state"):
        html = " ".join(admin_ui._schedule_section(KEY, "baci", col).split())
        first = _order(html)[:1]
        ck(f"  overdue leads when sorted by {col}",
           first == ["kw 07"],
           f"{first} — a plan that reads as queued and is not moving is the "
           f"only row anybody has to act on, whichever column was picked")

    print()
    print("— every heading that looks sortable is one —")
    head = " ".join(admin_ui._schedule_section(KEY, "baci").split())
    for col, (label, _fn) in admin_ui.SCHEDULE_SORTS.items():
        ck(f"  {col} is clickable", f"ssort={col}" in head, label)
    ck("the current column shows which way it is going",
       "&darr;" in head or "&uarr;" in head,
       "an arrow-less sorted table makes you click to find out")
    ck("an unknown sort falls back rather than erroring",
       bool(admin_ui._schedule_section(KEY, "baci", "nonsense")),
       "a bookmarked column that was renamed must not 500")

    print()
    print("PASS" if not _fail else f"FAILED: {len(_fail)}")
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
