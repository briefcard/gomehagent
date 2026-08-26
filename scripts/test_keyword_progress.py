"""Did the work move anything — and may we say it was the work.

Phase 3 of INITIATIVE-seo-blog. `SeoSnapshot` could say whether a DOMAIN was up;
nothing could say whether the article we published for a keyword moved that
keyword, because nothing joined the two and no phrase outside the top 50 by
traffic had a series at all.

The three refusals asserted here are the point of the module:

  * a rise is not reported as ours without a CONTROL group;
  * a movement inside `ATTRIBUTION_DAYS` of publication is listed and NOT
    attributed, because Google has not settled;
  * a goal is never invented — with none declared the report names the missing
    field and still delivers every number that does not depend on it.

    python3 scripts/test_keyword_progress.py
"""
import datetime as dt
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'kp.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["SEO_SITES_JSON"] = "{}"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, keywords, systems  # noqa: E402

_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def reading(tenant, phrase, *, pos, clicks=0, impressions=0, days_ago=0):
    with db.SessionLocal() as s:
        s.add(db.KeywordReading(
            tenant=tenant, phrase=phrase, source="gsc",
            at=db.utcnow() - dt.timedelta(days=days_ago),
            position=pos, clicks=clicks, impressions=impressions))
        s.commit()


def main() -> int:
    db.init_db()
    with db.SessionLocal() as s:
        s.add(db.Tenant(key="acme", name="Acme", kind="client",
                        domain="acme.example", business_model="ecom_inventory",
                        systems=["blog"]))
        s.commit()

    print("— sync records what GSC returned, and nothing about what it did not —")
    keywords.upsert("acme", "acrylic jug", volume=5000, status="published")
    keywords.upsert("acme", "never returned", volume=100, status="published")
    keywords._fetch_gsc = lambda p, days, limit: [
        {"query": "acrylic jug", "position": 2.0, "clicks": 40, "impressions": 900},
        {"query": "some other query", "position": 8.0, "clicks": 12, "impressions": 300}]
    out = keywords.sync("acme")
    ck("readings filed for what came back", out["readings"] == 2)
    ck("a tracked phrase with no data is COUNTED, not nulled",
       out["tracked_without_data"] == 1,
       "absent from a truncated top-N is not the same fact as 'not ranking'")
    ck("nothing was written for it",
       keywords.latest_reading("acme", "never returned") is None)

    print("\n— `won` is derived from readings, in both directions —")
    ck("top-3 becomes won", out["won"] == 1, str(out))
    ck("status followed",
       [r.status for r in keywords.targets("acme") if r.phrase == "acrylic jug"][0] == "won")
    keywords._fetch_gsc = lambda p, days, limit: [
        {"query": "acrylic jug", "position": 9.0, "clicks": 8, "impressions": 700}]
    out2 = keywords.sync("acme")
    ck("a win that was LOST stops being a win", out2["lost"] == 1,
       "a status that only ratchets upward is a status that lies")

    print("\n— with no prior readings it says BASELINE, not a delta —")
    p = keywords.progress("acme", days=28)
    ck("it says so", any("baseline" in n for n in p["notes"]), str(p["notes"])[:90])
    ck("and invents no percentage", p["tracked"]["change"]["clicks_pct"] is None,
       "no base is not zero growth")

    print("\n— a control group, or the comparison is not made —")
    reading("acme", "acrylic jug", pos=18.0, clicks=5, impressions=400, days_ago=40)
    reading("acme", "some other query", pos=9.0, clicks=10, impressions=280, days_ago=40)
    p = keywords.progress("acme", days=28)
    ck("tracked and control are separated",
       p["tracked"]["now"]["phrases"] == 1 and p["control"]["now"]["phrases"] == 1,
       f"tracked={p['tracked']['now']['phrases']} control={p['control']['now']['phrases']}")
    ck("a smaller position reads as a POSITIVE gain",
       p["tracked"]["change"]["position_gain"] == 9.0,
       "18 -> 9; a delta that reads -9 for a nine-place gain is one somebody "
       "misreports the first time they quote it")
    ck("the control moved too, and by less",
       p["control"]["change"]["position_gain"] == 1.0
       and p["tracked"]["change"]["position_gain"] > p["control"]["change"]["position_gain"],
       f"tracked +{p['tracked']['change']['position_gain']} vs control "
       f"+{p['control']['change']['position_gain']} — the control is not "
       "expected to sit still; it is expected to say how much of the move was "
       "the tide")

    with db.SessionLocal() as s:
        for r in s.query(db.KeywordReading).filter_by(phrase="some other query").all():
            s.delete(r)
        s.commit()
    p2 = keywords.progress("acme", days=28)
    ck("an EMPTY control is named, not silently skipped",
       any("control" in n for n in p2["notes"]), str(p2["notes"])[:100])

    print("\n— a fresh publish is reported and NOT attributed —")
    with db.SessionLocal() as s:
        r = s.query(db.KeywordTarget).filter_by(phrase="acrylic jug").first()
        r.published_at = db.utcnow() - dt.timedelta(days=3)
        s.commit()
    p = keywords.progress("acme", days=28)
    m = p["movements"][0]
    ck("the movement is still listed", m["phrase"] == "acrylic jug")
    ck("with its age", m["days_since_publish"] == 3)
    ck("flagged too_early", m["too_early"] is True)
    ck("and excluded from what we claim",
       p["attributable"] == 0 and p["too_early_to_attribute"] == 1,
       f"attributable={p['attributable']}")

    with db.SessionLocal() as s:
        r = s.query(db.KeywordTarget).filter_by(phrase="acrylic jug").first()
        r.published_at = db.utcnow() - dt.timedelta(days=60)
        s.commit()
    p = keywords.progress("acme", days=28)
    ck("past the settling window it counts", p["attributable"] == 1)

    print("\n— the goal is declared or NAMED ABSENT, never invented —")
    ck("no goal is reported as no goal", p["goal"]["declared"] is None)
    ck("and the missing field is named", "set_goal" in (p["goal"].get("missing") or ""))
    ck("every other number still arrived",
       p["tracked"]["now"]["clicks"] == 8 and p["wins"]["top10"] == 1,
       "a missing target must not take the report down with it")

    row = systems.find("acme", "blog")
    if not row:
        with db.SessionLocal() as s:
            s.add(db.System(tenant="acme", key="blog", name="Blog", status="live"))
            s.commit()
        row = systems.find("acme", "blog")
    ck("an unknown goal field is refused by name",
       "unknown goal field" in (systems.set_goal(row.id, nonsense=5).get("error") or ""))
    ck("a non-number is refused",
       "whole number" in (systems.set_goal(row.id, top3="lots").get("error") or ""))
    ck("an absurd value is refused",
       "between" in (systems.set_goal(row.id, top3=99999).get("error") or ""))
    ck("all-blank is refused", "every box was blank" in
       (systems.set_goal(row.id, top3="", top10="").get("error") or ""))

    systems.set_goal(row.id, organic_clicks=100, top3=4, top10=8, horizon_days=90)
    p = keywords.progress("acme", days=28)
    ck("the goal comes back", p["goal"]["declared"]["organic_clicks"] == 100)
    ck("it is stamped, so it can be seen to go stale",
       bool(p["goal"]["declared"].get("set_at")))
    ck("attainment is computed against it",
       p["goal"]["attainment"]["organic_clicks"]["pct"] == 8.0,
       str(p["goal"]["attainment"]["organic_clicks"]))
    ck("per-tier wins are counted",
       p["wins"]["by_tier"].get("head", {}).get("top10") == 1,
       str(p["wins"]["by_tier"]))

    print("\n— the loop closes: readings move priorities the same night —")
    keywords.upsert("acme", "page two term", volume=800, status="published")
    keywords.record_reading("acme", "page two term", position=45.0, clicks=0)
    keywords.score("acme")
    before = {r.phrase: r.priority for r in keywords.targets("acme")}["page two term"]
    keywords._fetch_gsc = lambda p, days, limit: [
        {"query": "page two term", "position": 14.0, "clicks": 3, "impressions": 500}]
    out = keywords.sync("acme")
    after = {r.phrase: r.priority for r in keywords.targets("acme")}["page two term"]
    ck("sync re-scored", out.get("rescored", 0) > 0, str(out)[:110])
    ck("a keyword that moved to page two is now worth more",
       after > before, f"{before} -> {after}")
    ck("and the sync says what is now top", bool(out.get("top")), str(out.get("top"))[:80])

    print("\n— and the map tops itself up, on its own clock —")
    ck("a fresh map is not due", keywords.harvest_due("acme") is False,
       "positions move nightly; the competitive landscape does not, and each "
       "top-up spends Semrush calls")
    with db.SessionLocal() as s:
        for r in s.query(db.KeywordTarget).filter_by(tenant="acme").all():
            r.first_seen = db.utcnow() - dt.timedelta(days=keywords.HARVEST_EVERY_DAYS + 1)
        s.commit()
    ck("an old one is", keywords.harvest_due("acme") is True)
    with db.SessionLocal() as s:
        s.add(db.Tenant(key="empty", name="Empty", kind="client",
                        domain="empty.example", business_model="b2b_spec",
                        systems=[]))
        s.commit()
    ck("an account with NO map is never auto-harvested",
       keywords.harvest_due("empty") is False,
       "a first harvest is the moment somebody decides this account is being "
       "worked on — starting one automatically spends a client's quota on a "
       "map nobody asked for")

    print("\n— the answer-engine half, and the line it will not cross —")
    for ph, pos, ctr, imp in (("are jugs dishwasher safe", 5.0, 0.4, 900),
                              ("how to clean a jug", 6.0, 4.0, 300),
                              ("jug care guide", 7.0, 3.6, 250),
                              ("best jug", 8.0, 4.4, 220),
                              ("jug sizes", 9.0, 3.9, 210)):
        keywords.upsert("acme", ph, volume=200, status="published")
        keywords.record_reading("acme", ph, position=pos, ctr=ctr,
                                impressions=imp, clicks=int(imp * ctr / 100))
    a = keywords.aeo("acme")
    ck("it counts questions answered vs still open",
       a["coverage"]["questions_in_map"] >= 2 and "unanswered" in a["coverage"],
       str(a["coverage"]))
    flagged = {f["phrase"] for f in a["answer_taken"]["flagged"]}
    ck("a page ranking 5th with a tenth the band's CTR is flagged",
       "are jugs dishwasher safe" in flagged, str(flagged))
    ck("its well-clicked neighbours are not",
       "best jug" not in flagged and "jug sizes" not in flagged)
    ck("the baseline is OUR OWN keywords, and it says so",
       "median CTR" in " ".join(a["answer_taken"]["bands"].values()),
       "a published CTR curve is somebody else's sample standing in for a "
       "measurement")
    ck("a band too small to have a median says so, not zero",
       "too few" in a["answer_taken"]["bands"].get("1-3", ""),
       a["answer_taken"]["bands"].get("1-3", ""))
    ck("it is called a FLAG, not a measurement",
       "not a measurement" in a["answer_taken"]["means"])
    ck("and AI citation is named as NOT measured",
       "cites this brand" in a["not_measured"] and "source='ai'" in a["not_measured"],
       "asking a model from memory would measure its training data, not its "
       "citations")

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
