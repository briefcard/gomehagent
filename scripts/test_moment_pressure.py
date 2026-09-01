"""Moments inform the plan — they do not send. And they cannot collide with it.

The first cut of this had `moment_email` filing one plan per PERSON, and every
one of those plans drafted a campaign bound to `segments.esp_id_for(...)` —
the whole segment. Two people with cold carts would have been two identical
sends to the entire list, and one venue enquiry going quiet would have written
to every warm enquiry on file.

There is no per-contact sending surface to fix that with: an Omnisend campaign
targets a segment, and per-contact logic lives in Automations, which nothing
here pushes events to. So a moment's whole contribution is EVIDENCE — how many
people are in the same window, what they are about, and when the earliest one
closes — and one planner decides what to do with it.

What this pins:

  1. PRESSURE COUNTS PEOPLE, NOT MOMENTS. One indecisive shopper who abandons
     four carts is one reason to write, not four.
  2. THE FLOOR IS HONESTY. Under `MIN_PRESSURE` nothing is proposed, because a
     segment send on behalf of three people is a message to a thousand about
     something true of three. Those moments stay OPEN.
  3. PRESSURE PROMOTES THE COMMON TIER. `cart_abandoners` is never on the
     calendar; live signal is the only thing that makes it worth a campaign.
  4. IT CANNOT COLLIDE WITH THE CALENDAR. Both paths write the same `campaign:`
     refs against the same monthly cap, and the pressure pass sees what the
     calendar pass filed EARLIER IN THE SAME RUN. For a venue every moment
     segment is also a high-value calendar segment, so this is the normal case
     rather than a corner one.
  5. PRESSURE BUYS TIMING, NEVER VOLUME. At the cap it refuses by name. A
     cohort does not earn extra sends by having a bad week.
  6. A COHORT RESTS. However loud the signal, one written to four days ago is
     not written to again today.
  7. THE WATCHER IS A SWITCH. No `moment_email` system, no pressure path.

Run: python3 scripts/test_moment_pressure.py
"""
from __future__ import annotations

import datetime as dt
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'mpr.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, kb, moments, planner, segments, systems, tenants  # noqa: E402

_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _force(sys_id: str, **fields) -> None:
    with db.SessionLocal() as s:
        r = s.get(db.System, sys_id)
        for k, v in fields.items():
            setattr(r, k, v)
        s.commit()


def _live(tenant: str, key: str):
    row = systems.find(tenant, key) or systems.create(tenant, key)
    _force(row.id, status="live", autonomy="approve_all")
    return systems.get(row.id)


def _carts(tenant: str, n: int, *, start: int = 0, entity: str = "",
           hours_ago: int = 6) -> None:
    for i in range(start, start + n):
        got = moments.record(
            tenant, "cart_cooling", f"p{i}@example.com",
            dedup_key=f"cart:{i}", entity_key=entity,
            occurred_at=db.utcnow() - dt.timedelta(hours=hours_ago))
        assert got.get("ok"), got


def _open_ref(tenant, key):
    return next((r for r in _plan_refs(tenant) if f":{key}:" in r), "")


def _seg_or_none(tenant, key):
    return next((g for g in moments.pressure(tenant)
                 if g["segment"] == key), None)


def _seg(tenant, key):
    return next(g for g in moments.pressure(tenant) if g["segment"] == key)


def _plan_refs(tenant: str) -> list[str]:
    with db.SessionLocal() as s:
        return sorted(r.ref for r in s.query(db.SystemRun)
                      .filter(db.SystemRun.tenant == tenant,
                              db.SystemRun.stage == systems.PLANNED).all())


def main() -> int:
    db.init_db()
    tenants.seed()
    camp = _live("baci", "campaign_email")
    _live("baci", "moment_email")

    # ---------------------------------------------------------------- 1 ----
    print("— pressure counts PEOPLE, not moments —")
    for i in range(3):
        moments.record("baci", "cart_cooling", "indecisive@example.com",
                       dedup_key=f"cart:many:{i}",
                       occurred_at=db.utcnow() - dt.timedelta(hours=6))
    g = _seg("baci", "cart_abandoners")
    ck("three carts from one person is one person",
       g["people"] == 1 and g["moments"] == 3,
       f"people={g['people']} moments={g['moments']}")
    ck("and that is under the floor, with a reason in words",
       not g["ready"] and "true of 1" in g["why_not"], g["why_not"][:70])

    # ---------------------------------------------------------------- 2 ----
    print("\n— under the floor nothing is proposed, and nothing is spent —")
    out = planner.top_up(camp)
    ck("the pressure path proposed nothing",
       out.get("from_pressure") == 0, str(out.get("from_pressure")))
    ck("no cart campaign was filed",
       not any(":cart_abandoners:" in r for r in _plan_refs("baci")),
       str(_plan_refs("baci")))
    with db.SessionLocal() as s:
        still = (s.query(db.Moment)
                 .filter(db.Moment.kind == "cart_cooling",
                         db.Moment.status == "open").count())
    ck("the moments are still open — a window is not consumed by being ignored",
       still == 3, str(still))

    # ---------------------------------------------------------------- 3 ----
    print("\n— over the floor, pressure promotes a cohort the calendar skips —")
    ck("cart_abandoners really is common-tier, so only pressure can reach it",
       next(x["tier"] for x in segments.CATALOG["ecom_inventory"]
            if x["key"] == "cart_abandoners") == "common")
    kb.add_entity("baci", "product", "aqua-pitcher", "Aqua pitcher",
                  attributes={"availability": "in stock"})
    _carts("baci", 6, entity="aqua-pitcher")
    g = _seg("baci", "cart_abandoners")
    ck("now seven people are in the window", g["people"] == 7, str(g["people"]))
    ck("and the thing most of them looked at is named",
       g["top_entity"] == "aqua-pitcher", g["top_entity"])

    out = planner.top_up(camp)
    ck("one campaign was proposed from pressure",
       out.get("from_pressure") == 1, str(out))
    ref = next((r for r in _plan_refs("baci") if ":cart_abandoners:" in r), "")
    ck("it is one plan for the COHORT, not one per person", bool(ref), ref)
    want = (dt.date.today() + dt.timedelta(days=planner.LEAD_DAYS)).isoformat()
    ck("dated as soon as a plan can honestly run — pressure is urgency",
       ref.endswith(want), f"{ref} vs {want}")
    with db.SessionLocal() as s:
        row = (s.query(db.SystemRun)
               .filter(db.SystemRun.ref == ref).first())
        plan = dict((row.brief or {}).get("plan") or {})
    ck("the featured entity came from what those people were looking at",
       plan.get("entity_key") == "aqua-pitcher", str(plan))

    print("\n  a handle the store renamed does not throw the plan away")
    ck("an unknown handle is not passed on",
       not planner._known_entity("baci", "renamed-by-the-store"))

    # ---------------------------------------------------------------- 4 ----
    print("\n— the evidence is spent, so it cannot argue twice —")
    with db.SessionLocal() as s:
        used = (s.query(db.Moment)
                .filter(db.Moment.kind == "cart_cooling",
                        db.Moment.status == "consumed").all())
    ck("every moment that informed it is closed",
       len(used) == 9, str(len(used)))
    ck("and each says which plan it argued for",
       all(m.consumed_by == ref for m in used),
       str({m.consumed_by for m in used}))
    out2 = planner.top_up(camp)
    ck("a second pass proposes nothing more",
       out2.get("from_pressure") == 0, str(out2))

    # ---------------------------------------------------------------- 5 ----
    print("\n— pressure buys timing, never volume —")
    # The plan from above is consumed, so there is no OPEN plan to attach to
    # and the monthly cap is the thing standing in the way. Without this the
    # attach branch would fire and the cap would never be reached — which is
    # correct behaviour, and would make the assertion below vacuous.
    with db.SessionLocal() as s:
        _row = s.query(db.SystemRun).filter(db.SystemRun.ref == ref).first()
        _row.stage = "brief"
        # AND MOVED OUT OF THE REST WINDOW, WITHOUT LEAVING THE MONTH.
        #
        # Two gates can refuse this cohort — the monthly cap and the rest
        # period — and this section is about the cap. The fixture left the
        # consumed plan dated TODAY, so `_nearest_campaign` returned 0 and the
        # rest gate answered first. Whether it did depended on the weekday the
        # suite happened to run on: it passed all week and failed on a Sunday,
        # which is the worst kind of red — a suite that fails on a particular
        # day teaches people that red means "try again tomorrow".
        #
        # TEN DAYS BACK WAS THE BUG THE COMMENT ABOVE WAS WORRYING ABOUT.
        # The cap counts by calendar month (`planner._month`, "%Y-%m"), so on
        # the 1st through the 10th "ten days ago" is LAST month, the plan does
        # not count, and this suite goes red for the first days of every
        # month — the precise thing the note above says must not happen,
        # written into the fixture underneath it. Found 2026-09-01, the 1st.
        #
        # There is no date that is both outside a six-day rest window and
        # inside the current month on the 1st, so dating around it cannot
        # work. It does not need to: `planner` checks the CAP first
        # (planner.py:414) and only then the rest window (planner.py:417), so
        # a plan dated the 1st satisfies the cap fixture whatever the rest
        # gate would have said. The old assertion below asserted an ordering
        # the code does not use, and passed only because ten days happened to
        # clear both.
        import datetime as _dt
        _pre = ref.rsplit(":", 1)[0]
        _row.ref = f"{_pre}:{_dt.date.today().replace(day=1)}"
        _row_ref = _row.ref
        s.commit()
    ck("the fixture has no open plan for that cohort now",
       not any(":cart_abandoners:" in r for r in _plan_refs("baci")))
    # THE FIXTURE'S REAL PRECONDITION: the consumed plan has to fall in the
    # month the cap counts. That is what broke — `_month` is "%Y-%m", so a
    # plan dated ten days back is LAST month for the first ten days of every
    # one, the cap sees nothing, and this suite went red on a calendar.
    ck("…and the plan it consumed is inside the month the cap counts",
       any(r.rsplit(":", 1)[1].startswith(_dt.date.today().strftime("%Y-%m"))
           for r in _plan_refs("baci") + [_row_ref]
           if ":cart_abandoners:" in r),
       f"this month is {_dt.date.today().strftime('%Y-%m')}")
    _carts("baci", 8, start=100)
    g = _seg("baci", "cart_abandoners")
    ck("the fixture really is over the floor again", g["ready"], str(g["people"]))
    out3 = planner.top_up(camp)
    ck("nothing new is proposed — the cohort is at its monthly cap",
       out3.get("from_pressure") == 0, str(out3.get("from_pressure")))
    ck("and the refusal says so, rather than going quiet",
       any("monthly cap" in r for r in out3["refusals"]),
       str(out3["refusals"])[:110])
    ck("the fresh moments stay OPEN for the next month, not spent on nothing",
       _seg("baci", "cart_abandoners")["people"] == 8,
       str(_seg("baci", "cart_abandoners")["people"]))

    # ---------------------------------------------------------------- 6 ----
    print("\n— a cohort rests between campaigns —")
    ck("the rest period is a declared knob, not a constant in code",
       planner.rest_days_for(camp) == 6, str(planner.rest_days_for(camp)))
    systems.set_cadence(camp.id, per_segment_monthly="4")
    camp = systems.get(camp.id)
    # THIS SECTION'S OWN PRECONDITION, stated here rather than inherited.
    # Section 5 moved the plan out of the rest window so the CAP was the only
    # gate; this one is about the rest gate, so it moves it back in. Both used
    # to rely on the same implicitly-today date, which is why one of them
    # failed on a Sunday and neither said what it was assuming.
    with db.SessionLocal() as s:
        _row = s.query(db.SystemRun).filter(
            db.SystemRun.ref.like("campaign:baci:cart_abandoners:%")).first()
        _pre = _row.ref.rsplit(":", 1)[0]
        _row.ref = f"{_pre}:{(_dt.date.today() - _dt.timedelta(days=2))}"
        s.commit()
    ck("the fixture is now INSIDE the rest window",
       planner._nearest_campaign("baci", "cart_abandoners",
                                 _dt.date.today()) < planner.rest_days_for(camp),
       "otherwise there is nothing for the rest gate to refuse")
    out4 = planner.top_up(camp)
    ck("with the cap raised it is the REST period that now holds it back",
       out4.get("from_pressure") == 0
       and any("day(s) away and this cohort rests for" in r
               for r in out4["refusals"]),
       str(out4["refusals"])[:130])
    ck("and the gap it reports is never negative — a future plan is not a past send",
       not any("-" in r.split("is ")[-1][:4]
               for r in out4["refusals"] if "day(s) away" in r),
       str(out4["refusals"])[:130])

    # ---------------------------------------------------------------- 7 ----
    print("\n— a venue: every moment segment is ALSO a calendar segment —")
    vcamp = _live("ironside", "campaign_email")
    _live("ironside", "moment_email")
    hv = {x["key"] for x in segments.CATALOG["local_venue"]
          if x["tier"] == "high_value"}
    mseg = {m["segment"] for m in moments.CATALOG["local_venue"]}
    ck("the fixture is the colliding case, not a contrived one",
       mseg <= hv, f"moment segments {sorted(mseg)} vs high-value {sorted(hv)}")

    for i in range(7):
        moments.record("ironside", "enquiry_quiet", f"v{i}@example.com",
                       dedup_key=f"q:{i}",
                       occurred_at=db.utcnow() - dt.timedelta(hours=100))
    ck("seven warm enquiries have gone quiet",
       _seg("ironside", "hot_enquiries")["people"] == 7)

    out5 = planner.top_up(vcamp)
    refs = [r for r in _plan_refs("ironside") if ":hot_enquiries:" in r]
    ck("hot_enquiries got exactly ONE plan, not one from each path",
       len(refs) == 1, str(refs))
    ck("pressure attached itself to the queued plan instead of adding a send",
       out5.get("from_pressure") == 0
       and any("hot_enquiries" in r and "attached to the plan already queued"
               in r for r in out5["refusals"]),
       str(out5["refusals"])[:150])
    with db.SessionLocal() as s:
        row = (s.query(db.SystemRun)
               .filter(db.SystemRun.ref == refs[0]).first())
    ck("and the evidence was spent on it, so it cannot argue again",
       _seg_or_none("ironside", "hot_enquiries") is None,
       "moments still open for hot_enquiries")

    # ---------------------------------------------------------------- 8 ----
    print("\n— the watcher is a switch —")
    off = systems.find("ironside", "moment_email")
    _force(off.id, status="paused")
    for i in range(7):
        moments.record("ironside", "event_just_held", f"w{i}@example.com",
                       dedup_key=f"e:{i}",
                       occurred_at=db.utcnow() - dt.timedelta(hours=100))
    out6 = planner.top_up(systems.get(vcamp.id))
    ck("with moments switched off, no pressure reaches the planner",
       out6.get("from_pressure") == 0
       and not any("people are in a window" in r for r in out6["refusals"]),
       str(out6.get("from_pressure")))

    # ---------------------------------------------------------------- 9 ----
    print("\n— a window shorter than the lead time is refused, not filed —")
    # A cohort with no history at all: nothing queued to attach to, nothing to
    # rest from, nothing near the cap. The ONLY thing that can stop it is the
    # window closing before a reviewable plan could run.
    for i in range(6):
        moments.record("baci", "browsed_no_cart", f"b{i}@example.com",
                       dedup_key=f"b:{i}",
                       occurred_at=db.utcnow() - dt.timedelta(hours=30))
    with db.SessionLocal() as s:
        for m in s.query(db.Moment).filter(
                db.Moment.kind == "browsed_no_cart").all():
            m.expires_at = db.utcnow() + dt.timedelta(hours=6)
        s.commit()
    g = _seg("baci", "engaged_non_buyers")
    ck("the fixture is over the floor and has nothing else in its way",
       g["ready"] and not _open_ref("baci", "engaged_non_buyers"),
       f"people={g['people']}")
    out7 = planner.top_up(systems.get(camp.id))
    ck("it is refused for the real reason — the lead time outlives the window",
       any("engaged_non_buyers" in r
           and "before the soonest a reviewable plan can run" in r
           for r in out7["refusals"]),
       str([r for r in out7["refusals"] if "engaged_non_buyers" in r])[:150])
    ck("and nothing was filed for it",
       not any(":engaged_non_buyers:" in r for r in _plan_refs("baci")),
       str(_plan_refs("baci")))

    print("\n" + ("FAILURES: " + ", ".join(_fail) if _fail else "all good"))
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
