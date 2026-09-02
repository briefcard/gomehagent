"""Did refreshing work — and can we honestly say it was the refresh.

Phase 4, and the one that makes the whole lane checkable. Phase 1 made a
published page that is not working visible, Phase 2 filed the plan, and the
revision arm rewrites the page that ranks. All of that is a BET that refreshing
moves a page, and until this the system had no way to be told it was wrong.
Adding a class of work without the measurement is adding it on faith.

The blog system's declared measure is "position change in `keywords.progress`,
against a control" — and that covered only PUBLISHING.

FOUR REFUSALS, each asserted:

  · No claim without a control. A quarter when the whole site rose is not a
    refresh working, and `lift` is None rather than the raw gain when there is
    no control to subtract.
  · No attribution Google has not settled. A refresh inside ATTRIBUTION_DAYS
    is listed and flagged, exactly as a publication is.
  · No number where there is no reading. A page with no reading from BEFORE
    its refresh cannot be judged at all — counted and NAMED, never dropped,
    because a silent drop makes a thin answer look like a confident one.
  · No comparison across the wrong dates. Measured from each page's OWN
    refresh date: a page refreshed 10 days into a 28-day window, compared
    now-against-28-days-ago, folds 18 days of pre-refresh drift into the
    answer and credits it to the refresh.

Run: python3 scripts/test_refresh_effect.py
"""
import datetime as dt
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 're.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, keywords, tenants  # noqa: E402

_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _reading(tenant, phrase, days_ago, pos):
    with db.SessionLocal() as s:
        s.add(db.KeywordReading(tenant=tenant, phrase=phrase, position=pos,
                                source="gsc",
                                at=db.utcnow() - dt.timedelta(days=days_ago)))
        s.commit()


def _page(tenant, phrase, *, refreshed=None, status="published"):
    keywords.upsert(tenant, phrase, status=status)
    with db.SessionLocal() as s:
        r = (s.query(db.KeywordTarget)
             .filter(db.KeywordTarget.tenant == tenant,
                     db.KeywordTarget.phrase == phrase).first())
        r.published_at = db.utcnow() - dt.timedelta(days=200)
        r.refreshed_at = (db.utcnow() - dt.timedelta(days=refreshed)
                          if refreshed is not None else None)
        s.commit()


def main() -> int:
    db.init_db()
    tenants.seed()

    print("— a refresh is measured from its OWN date, not the window edge —")
    # Refreshed 30 days ago. It DRIFTED DOWN before the refresh (12 -> 15) and
    # rose after it (15 -> 9). A window-edge comparison would read 12 -> 9 and
    # credit the refresh with 3; the honest answer is 15 -> 9, which is 6.
    _page("baci", "drifted then fixed", refreshed=30)
    _reading("baci", "drifted then fixed", 60, 12.0)
    _reading("baci", "drifted then fixed", 33, 15.0)
    _reading("baci", "drifted then fixed", 5, 9.0)
    # An unrefreshed control page that also improved a little.
    _page("baci", "left alone")
    _reading("baci", "left alone", 60, 20.0)
    _reading("baci", "left alone", 5, 19.0)

    got = keywords.refresh_effect("baci", days=90)
    m = {x["phrase"]: x for x in got["movements"]}
    ck("the before reading is the one just before the refresh",
       m["drifted then fixed"]["from"] == 15.0,
       f'from={m["drifted then fixed"]["from"]} — 12.0 would be the reading '
       f'from before the drift, crediting the refresh with the fall it fixed')
    ck("  so the gain is the refresh's, not the drift's",
       m["drifted then fixed"]["gain"] == 6.0,
       str(m["drifted then fixed"]))

    print()
    print("— and it is stated against a control —")
    ck("the control is the unrefreshed pages",
       got["control_pages"] == 1 and got["control_avg_gain"] == 1.0,
       str({k: got[k] for k in ("control_pages", "control_avg_gain")}))
    ck("  and the lift subtracts it",
       got["lift"] == 5.0,
       f'avg_gain={got["avg_gain"]} control={got["control_avg_gain"]} '
       f'lift={got["lift"]} — a rise everywhere is not a refresh working')

    print()
    print("— with no control there is no lift, not a bare number —")
    solo = keywords.refresh_effect("wm", days=90)
    _page("wm", "only page", refreshed=30)
    _reading("wm", "only page", 40, 14.0)
    _reading("wm", "only page", 5, 8.0)
    solo = keywords.refresh_effect("wm", days=90)
    ck("the gain is still computed", solo["avg_gain"] == 6.0, str(solo["avg_gain"]))
    ck("  but the lift is withheld",
       solo["lift"] is None,
       "falling back to the raw gain is exactly the claim this refuses — a "
       "quarter when the whole site rose is not a refresh working")
    ck("  and it says why",
       any("no control group" in n for n in solo["notes"]),
       str(solo["notes"]))

    print()
    print("— a refresh Google has not settled is listed, not attributed —")
    _page("baci", "just refreshed", refreshed=3)
    _reading("baci", "just refreshed", 10, 18.0)
    _reading("baci", "just refreshed", 1, 6.0)
    got2 = keywords.refresh_effect("baci", days=90)
    m2 = {x["phrase"]: x for x in got2["movements"]}
    ck("it appears in the movements", "just refreshed" in m2)
    ck("  flagged too early", m2["just refreshed"]["too_early"] is True,
       f'{keywords.ATTRIBUTION_DAYS}-day window')
    ck("  and its 12-point jump is NOT in the average",
       got2["avg_gain"] == 6.0,
       f'avg_gain={got2["avg_gain"]} — including it would let an unsettled '
       f'reading carry the whole claim')
    ck("  and the count says how many were held back",
       got2["too_early"] == 1 and got2["judged"] == 1, str(got2)[:100])

    print()
    print("— a page that cannot be judged is NAMED, not dropped —")
    _page("baci", "no before reading", refreshed=30)
    _reading("baci", "no before reading", 5, 11.0)
    _page("baci", "no after reading", refreshed=30)
    _reading("baci", "no after reading", 40, 11.0)
    got3 = keywords.refresh_effect("baci", days=90)
    blind = {x["phrase"]: x for x in got3["unmeasurable"]}
    ck("both are reported", len(blind) == 2, str(sorted(blind)))
    ck("  and each says which side is missing",
       "before" in blind["no before reading"]["why"]
       and "since" in blind["no after reading"]["why"],
       str(blind))
    ck("  they are not counted as judged",
       got3["judged"] == 1, str(got3["judged"]))
    ck("  they are not counted as zero gain either",
       got3["avg_gain"] == 6.0,
       "dropping them silently would make a thin answer look confident; "
       "counting them as 0 would make refreshing look useless")
    ck("  and the report says so in words",
       any("cannot be judged yet" in n for n in got3["notes"]),
       str(got3["notes"]))

    print()
    print("— the control is a real cohort, not a silent zero —")
    # THE FIRST CUT SPLIT THE CONTROL ON THE WINDOW'S EDGE, whose `then`
    # bucket holds only readings OLDER than the window — so every control
    # page's history sat inside `now`, the cohort came back as 0 pages, and
    # `lift` was withheld for a right-looking wrong reason. A control that
    # quietly evaluates to nothing is worse than no control: it would have
    # stayed withheld forever on an account that HAD one.
    ck("the control cohort is non-empty here",
       got3["control_pages"] >= 1,
       f'{got3["control_pages"]} page(s) — the assertions about `lift` above '
       f'mean nothing if this is 0, because withheld-for-no-control and '
       f'withheld-for-a-broken-control look identical from outside')
    ck("  and it excludes the refreshed pages themselves",
       got3["control_pages"] == 1,
       "a page cannot be its own control")

    print()
    print("— and it rides in the report the system's measure names —")
    rep = keywords.progress("baci", days=28)
    ck("progress carries it", "refresh" in rep)
    ck("  over its own longer window",
       rep["refresh"]["window_days"] >= 90,
       "a 28-day view drops most refreshes, which are judged from their own "
       "date rather than the window's")
    ck("  and its notes reach the top-level notes",
       any(n.startswith("refresh:") for n in rep["notes"]),
       "a caveat nobody reads is a caveat nobody made")

    print()
    print("PASS" if not _fail else f"FAILED: {len(_fail)}")
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
