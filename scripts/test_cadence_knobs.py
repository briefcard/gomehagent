"""The cadence form offers exactly the knobs its planner reads.

Owner, 2026-09-02, on the refresh windows: *"That should be set in the UI based
on the cadence."*

They were module constants no console could reach — so every account got the
same settle time regardless of how fast Google actually crawls their site. And
the form was worse than missing: it rendered two inputs, both the CAMPAIGN
planner's, on a card that also serves the blog. An owner on the blog system was
offered "per segment / month" — a number nothing on that system reads — and
never shown `articles_monthly` at all.

ONE DECLARATION, `planner.KNOBS`: the number, its ceiling, and what it means.
The planner reads it, the form renders from it, and `set_cadence` validates
against it. A knob cannot now exist in one and not the others — which is
precisely how these three drifted, since the ceilings were listed twice.

Run: python3 scripts/test_cadence_knobs.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'ck.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import db, keywords, planner, systems, tenants, web  # noqa: E402

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
    blog = _live("baci", "blog")
    mail = _live("baci", "campaign_email")

    print("— each planner is offered its OWN knobs, and only those —")
    b = {k["key"] for k in planner.knobs_for(blog)}
    m = {k["key"] for k in planner.knobs_for(mail)}
    ck("the blog gets its article and refresh numbers",
       {"articles_monthly", "refreshes_monthly", "refresh_after_days",
        "refresh_cooldown_days"} <= b, str(sorted(b)))
    ck("  and is NOT offered per-segment sending",
       "per_segment_monthly" not in b,
       "a number nothing on that system reads, on that system's own card")
    ck("campaign_email gets its segment knobs",
       {"per_segment_monthly", "segment_rest_days"} <= m, str(sorted(m)))
    ck("  and is not offered article counts",
       "articles_monthly" not in m, str(sorted(m)))
    ck("both share the horizon, because both planners read it",
       "horizon_days" in b and "horizon_days" in m)

    print()
    print("— every offered knob is one the planner can actually read —")
    for row, fn in ((blog, planner.blog_cadence_for),
                    (mail, planner.cadence_for)):
        for k in planner.knobs_for(row):
            if k["key"] == "segment_rest_days":
                continue          # its own reader, `rest_days_for`
            ck(f"  {row.key}.{k['key']} reaches the cadence",
               k["key"] in fn(row), str(sorted(fn(row))))

    print()
    print("— setting one changes what the board actually does —")
    ck("the default windows are the module constants",
       keywords.refresh_windows("baci")
       == (keywords.REFRESH_AFTER_DAYS, keywords.REFRESH_COOLDOWN_DAYS),
       "an account that has set nothing must behave exactly as it did")
    c = TestClient(web.app)
    r = c.get(f"/admin/plan_cadence?key={KEY}&tenant=baci&system=blog"
              f"&refresh_after_days=14&refresh_cooldown_days=21",
              follow_redirects=False)
    ck("the route accepts them", r.status_code == 303,
       r.headers.get("location", "")[:90])
    ck("  and the reader returns them",
       keywords.refresh_windows("baci") == (14, 21),
       str(keywords.refresh_windows('baci')))
    # AND THE BOARD BEHAVES DIFFERENTLY, which is the actual claim. Asserting
    # only that `refresh_windows` returns the number tests the getter, not the
    # decision — and a guard on `attention`'s call site reported MISSED
    # against exactly that gap.
    import datetime as _dt
    keywords.upsert("baci", "twenty days old", status="published")
    with db.SessionLocal() as sx:
        kr = (sx.query(db.KeywordTarget)
              .filter(db.KeywordTarget.tenant == "baci",
                      db.KeywordTarget.phrase == "twenty days old").first())
        kr.published_at = db.utcnow() - _dt.timedelta(days=20)
        sx.add(db.KeywordReading(tenant="baci", phrase="twenty days old",
                                 position=18.0, source="gsc"))
        sx.commit()

    def _state():
        return next((x["state"] for x in keywords.attention("baci")
                     if x["phrase"] == "twenty days old"), "")
    ck("  a 20-day page is past a 14-day settle", _state() == "stalled",
       f"{_state()} — with settle=14 it is old enough to be judged")
    c.get(f"/admin/plan_cadence?key={KEY}&tenant=baci&system=blog"
          f"&refresh_after_days=30", follow_redirects=False)
    ck("  and raising the settle to 30 makes it too early again",
       _state() == "too_early",
       f"{_state()} — the knob has to change the DECISION, not just the "
       f"number the getter hands back")
    c.get(f"/admin/plan_cadence?key={KEY}&tenant=baci&system=blog"
          f"&refresh_after_days=14", follow_redirects=False)

    print()
    print("— a value out of range is refused BY NAME, not written —")
    bad = systems.set_cadence(blog.id, refresh_cooldown_days="9999")
    ck("it says which knob and what the ceiling is",
       "refresh_cooldown_days" in str(bad.get("error", ""))
       and "365" in str(bad.get("error", "")), str(bad))
    ck("  and nothing changed",
       keywords.refresh_windows("baci") == (14, 21),
       "a bad value written silently sits behind a planner for weeks")
    ck("an unknown knob is refused rather than stored",
       "no cadence knob" in
       str(systems.set_cadence(blog.id, made_up_thing="3").get("error", "")),
       "config that nothing reads is indistinguishable from config that works")
    ck("blank means leave it alone",
       "nothing to set" in
       str(systems.set_cadence(blog.id, horizon_days="").get("error", "")))

    print()
    print("— the form renders them, with the reason and the recommendation —")
    from app import admin_ui
    # RE-READ THE ROW. `blog` was fetched before the cadence was written, so
    # rendering from it would show the old numbers and the assertion below
    # would be testing a stale object rather than the form.
    blog = systems.find("baci", "blog")
    card = " ".join(admin_ui._cadence_form(KEY, blog, "", "").split())
    ck("  the form shows the value that was set",
       'value="21"' in card,
       "rendering a stale row would make every assertion here about the "
       "fixture rather than about the form")
    ck("every blog knob has an input", all(
        f'name="{k}"' in card for k in
        ("articles_monthly", "refreshes_monthly", "refresh_after_days",
         "refresh_cooldown_days", "horizon_days")), card[:150])
    ck("  each carries what it means",
       "re-crawled before the refresh can be judged" in card
       and "has not settled" in card,
       "a number with no explanation gets changed once and never again — and "
       "these are knobs whose consequence arrives a month later")
    ck("  and a changed one shows what was recommended",
       "Recommended: 60" in card,
       "cooldown is 21 here; the default it moved away from is worth stating")
    ck("  while an untouched one does not nag",
       "Recommended: 4" not in card,
       "articles_monthly is still 4 — repeating the default back is noise")
    ck("campaign_email's card is a different card",
       'name="per_segment_monthly"' in
       " ".join(admin_ui._cadence_form(KEY, mail, "", "").split()))

    print()
    print("PASS" if not _fail else f"FAILED: {len(_fail)}")
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
