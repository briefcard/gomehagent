"""Progress at three resolutions, and an empty window says why.

Owner, 2026-09-02: *"The progress page as it stands isn't helpful being that it
only checks 28 days out. We need daily, weekly and monthly progress."*

`days` had been a parameter the whole time — clamped 1-365 — with NO control
that set it. So the page answered one question at one resolution and the other
two were reachable only by hand-editing a URL.

AN EMPTY WINDOW IS NOT A ZERO. The day view is the one most likely to have
nothing in it: Search Console lags and most accounts sync weekly. Printing 0
there reads as "nothing moved" when the truth is "nothing was measured", and
those lead to opposite decisions.

AND EACH WINDOW CARRIES ITS OWN CONTROL, because which answer is true changes
with the window — a week when the whole site rose is not a week the work rose,
and that is most of why one window was never enough.

Run: python3 scripts/test_progress_windows.py
"""
import datetime as dt
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'pw.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import admin_ui, db, keywords, tenants  # noqa: E402

KEY = "s3cret"
_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _read(tenant, phrase, days_ago, pos):
    with db.SessionLocal() as s:
        s.add(db.KeywordReading(tenant=tenant, phrase=phrase, position=pos,
                                source="gsc",
                                at=db.utcnow() - dt.timedelta(days=days_ago)))
        s.commit()


def main() -> int:
    db.init_db()
    tenants.seed()

    # Tracked page: 12 -> 8 (a four-place gain). Untracked control: 20 -> 19.
    keywords.upsert("baci", "tracked one", status="published")
    keywords.upsert("baci", "untracked one", status="candidate")
    for ph, ago, pos in (("tracked one", 40, 12.0), ("tracked one", 2, 8.0),
                         ("untracked one", 40, 20.0), ("untracked one", 2, 19.0)):
        _read("baci", ph, ago, pos)

    w = {x["label"]: x for x in keywords.progress_windows("baci")}
    ck("all three resolutions are reported",
       set(w) == {"yesterday", "this week", "this month"}, str(sorted(w)))

    print()
    print("— a window with nothing in it says so, and is not a zero —")
    ck("the day window is not measurable here",
       w["yesterday"]["measurable"] is False,
       "the newest reading is two days old — Search Console lags, and most "
       "accounts sync weekly")
    ck("  its gain is withheld, not 0",
       w["yesterday"]["position_gain"] is None,
       str(w["yesterday"]["position_gain"]))
    ck("  and it says which side is missing",
       "nothing was measured" in w["yesterday"]["why_not"],
       w["yesterday"]["why_not"])
    ck("  distinguishing that from a baseline",
       "baseline" not in w["yesterday"]["why_not"],
       "no-reading-inside and no-reading-before are different situations and "
       "the first cut reported the second for both")

    print()
    print("— a window with both sides measures, against its own control —")
    ck("the week window measures", w["this week"]["measurable"] is True)
    ck("  the gain is places moved UP",
       w["this week"]["position_gain"] == 4.0,
       f'{w["this week"]["position_gain"]} — 12 to 8 is a gain of four, and a '
       f'delta reading -4 is one somebody misquotes the first time')
    ck("  and the control is the untargeted queries",
       w["this week"]["control_gain"] == 1.0
       and w["this week"]["control_pages"] == 1,
       str({k: w["this week"][k] for k in ("control_gain", "control_pages")}))
    ck("  so the two are separable",
       w["this week"]["position_gain"] != w["this week"]["control_gain"],
       "if they were equal the window would be reporting the market, not the "
       "work")

    print()
    print("— with no control the control column is withheld —")
    keywords.upsert("baci", "untracked one", status="published")
    solo = {x["label"]: x for x in keywords.progress_windows("baci")}
    ck("every phrase is now tracked",
       solo["this week"]["control_pages"] == 0,
       "so there is nothing left to compare against")
    ck("  and the control gain is None, not 0",
       solo["this week"]["control_gain"] is None,
       "a 0 there would read as 'the rest of the site was flat', which is a "
       "measurement nobody made")

    print()
    print("— and the page offers the resolutions it reports —")
    page = " ".join(admin_ui._progress_section(KEY, "baci", 28).split())
    ck("the table is rendered", "at three resolutions" in page)
    for d in (1, 7, 30, 90):
        ck(f"  a link sets the window to {d}", f"days={d}" in page)
    ck("  each link keeps the tab and the account",
       page.count("sub=progress") >= 4 and page.count("tenant=baci") >= 4,
       "a window switch that loses the account is a switch nobody uses twice")
    ck("  and the empty window's reason is on the page, not just in the data",
       "nothing was measured" in page,
       "a caveat that never renders is a caveat nobody made")

    print()
    print("PASS" if not _fail else f"FAILED: {len(_fail)}")
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
