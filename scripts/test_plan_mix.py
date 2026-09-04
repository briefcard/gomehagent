"""The Plan's mix, its recommendation, the schedule reset, and the refresh.

Owner, 2026-09-04: *"I will need to refresh the plan to add new systems and
to reset the schedule if the initial schedule doesn't make sense. I should be
able to adjust the plan based on the percent of long tail / branded / short /
specific topics etc and the app should recommend a base setting default based
on the current status of the brand and where the best opportunities lie."*

What must hold, each proven against the thing itself rather than a label:

  · the RECOMMENDATION is computed from the map — the share per tier, branded
    and buying intent, leaning toward striking distance — and every number
    carries the sentence that produced it;
  · the MIX is a declared knob the planner READS (rule 4): with a share set,
    the class wins over the score; with none set, the score order stands; a
    trio that does not sum to 100 is refused by name; the walk is seeded
    with the open queue; a pillar still goes ahead of its support;
  · RESET re-dates a system's open plans from today under its cadence and
    keeps every date the owner set; the calendar planners refuse by name;
  · REFRESH installs every declared planner's system the account is ready
    for, names the ones it is not, and tops up every one that is on;
  · the Plan tab shows the fact WITH its control, and every control lands
    back on the room it was pressed in with a sentence.

    python3 scripts/test_plan_mix.py
"""
from __future__ import annotations

import datetime as dt
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'pm.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["SEO_SITES_JSON"] = "{}"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import db, keywords, planner, systems, tenants, web  # noqa: E402

KEY = "s3cret"
TODAY = dt.date.today()
_fail: list[str] = []


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


def _wipe(tenant, key):
    """Back to an empty queue and an all-candidate map, between scenarios."""
    row = systems.find(tenant, key)
    with db.SessionLocal() as s:
        s.query(db.SystemRun).filter(db.SystemRun.system_id == row.id).delete()
        for r in s.query(db.KeywordTarget).filter(db.KeywordTarget.tenant == tenant):
            r.status = "candidate"
        s.commit()


def _by_date(tenant, key, prefix="article:"):
    """(planned_for, keyword) for the open plans, soonest first."""
    out = []
    for p in systems.plans(tenant, key):
        if str(p.ref or "").startswith(prefix):
            b = p.brief or {}
            out.append((str(b.get("planned_for") or ""),
                        str((b.get("plan") or {}).get("keyword") or "")))
    return sorted(out)


def _unclustered(tenant):
    """Clear cluster and role on every row: the mix tests want the walk's
    own ordering, not the pillar rule's, which has its own scenario."""
    with db.SessionLocal() as s:
        for r in s.query(db.KeywordTarget).filter(db.KeywordTarget.tenant == tenant):
            r.cluster_key, r.role = "", ""
        s.commit()


def _tier(tenant, phrase):
    return next(r.tier for r in keywords.targets(tenant) if r.phrase == phrase)


def main() -> int:
    db.init_db()
    tenants.seed()
    T = "baci"                                  # ecom_inventory: head >= 2000
    blog = _live(T, "blog")
    seed = (("italian tableware", 6000),          # head
            ("acrylic stemware", 590),            # body
            ("melamine plates", 900),             # body
            ("baci milano plates", 400),          # body, BRANDED
            ("best acrylic wine glasses", 700),   # body, commercial
            ("buy melamine plates online", 150),  # body, transactional
            ("how to clean acrylic wine glasses", 300),     # long-tail
            ("are melamine plates dishwasher safe", 200),   # long-tail
            ("what is melamine made of", 120))              # long-tail
    for ph, vol in seed:
        keywords.upsert(T, ph, volume=vol, source="test", database="us")
    keywords.cluster(T)
    keywords.score(T)
    _unclustered(T)
    tiers = {r.phrase: r.tier for r in keywords.targets(T)}
    ck("the fixture is the shape the map has: one head, five body, three long-tail",
       sorted(tiers.values()).count("head") == 1
       and list(tiers.values()).count("body") == 5
       and list(tiers.values()).count("long_tail") == 3, str(tiers))

    # ── 1. the recommendation is computed from the map ────────────────────
    print("— the recommendation is arithmetic over the map, with its why —")
    rec = keywords.mix_recommendation(T)
    c = rec["counts"]
    ck("it counts the candidates per tier",
       c["candidates"] == 9 and c["tier"] == {"head": 1, "body": 5, "long_tail": 3},
       str(c["tier"]))
    ck("  and the branded and buying ones",
       c["branded"] == 1 and c["buying"] == 2,
       f"branded={c['branded']} buying={c['buying']}")
    r = rec["recommended"]
    ck("the tier trio sums to 100, in fives",
       sum(r[t] for t in planner.MIX_TIERS) == 100
       and all(r[t] % 5 == 0 for t in planner.MIX_TIERS), str(r))
    ck("  leaning where the candidates are: body carries most, head least",
       r["body"] > r["long_tail"] > r["head"], str(r))
    ck("branded is small and capped — one branded phrase of nine",
       0 < r["branded"] <= keywords.BRANDED_CAP, str(r))
    ck("buying holds its floor — two buying phrases of nine",
       r["buying"] == keywords.BUYING_FLOOR, str(r))
    ck("every number carries a sentence",
       len(rec["why"]) >= 3 and any("candidates" in w for w in rec["why"])
       and any("branded" in w for w in rec["why"])
       and any("buying" in w for w in rec["why"]), " | ".join(rec["why"])[:200])

    keywords.record_reading(T, "acrylic stemware", position=12.0)
    keywords.score(T)
    rec2 = keywords.mix_recommendation(T)
    ck("a page already on page two moves the recommendation toward its tier",
       rec2["recommended"]["body"] > r["body"],
       f"body {r['body']} -> {rec2['recommended']['body']}")
    ck("  and says so",
       any("page one or two" in w for w in rec2["why"]), " | ".join(rec2["why"])[:200])

    print("\n— the two rules a share cannot express —")
    A = "agency"                                # digital_products: head >= 1000
    for ph in ("wedding venues", "event spaces", "party venues"):
        keywords.upsert(A, ph, volume=5000, source="test")
    keywords.upsert(A, "how to pick a wedding venue in miami", volume=100, source="test")
    keywords.score(A)
    ra = keywords.mix_recommendation(A)["recommended"]
    ck("head is capped — three head terms of four still get at most the cap",
       ra["head"] == keywords.HEAD_CAP and sum(ra[t] for t in planner.MIX_TIERS) == 100,
       str(ra))
    E = "coverings"                             # b2b_spec: head >= 500
    keywords.upsert(E, "porcelain tile", volume=3000, source="test",
                    role="pillar", cluster_key="tile", status="candidate")
    for i in range(9):
        keywords.upsert(E, f"how to lay porcelain tile on a wall {i}", volume=50,
                        source="test", role="support", cluster_key="tile",
                        status="candidate")
    keywords.upsert(E, "how to grout porcelain tile outdoors", volume=60,
                    source="test", role="support", cluster_key="tile",
                    status="published")
    keywords.score(E)
    re_ = keywords.mix_recommendation(E)
    ck("a cluster with published supports and no pillar holds head at the floor",
       re_["recommended"]["head"] == keywords.HEAD_FLOOR,
       str(re_["recommended"]))
    ck("  naming the pillar those supports are waiting on",
       any("porcelain tile" in w and "published supports" in w for w in re_["why"]),
       " | ".join(re_["why"])[:240])
    ck("an empty map recommends nothing and says why",
       keywords.mix_recommendation("eien")["recommended"] is None
       and "build the map" in keywords.mix_recommendation("eien")["why"][0])

    # ── 2. the knob, validated at the knob ────────────────────────────────
    print("\n— the mix is set here, and a share that does not sum is refused —")
    out = systems.set_mix(blog.id, head=50, body=30, long_tail=30, branded=10, buying=30)
    ck("head + body + long_tail must sum to 100",
       "must sum to 100, got 110" in (out.get("error") or ""), str(out))
    ck("  and nothing was stored", planner.mix_for(systems.get(blog.id)) == {})
    ck("junk is refused by name",
       "whole number" in (systems.set_mix(blog.id, head="lots").get("error") or ""))
    ck("out of range is refused, not clamped",
       "between 0 and 100" in (systems.set_mix(blog.id, head=150).get("error") or ""))
    ck("an unknown knob is refused",
       "no mix knob" in (systems.set_mix(blog.id, bogus=5).get("error") or ""))
    ck("all blank is refused rather than a silent no-op",
       "nothing to set" in (systems.set_mix(blog.id).get("error") or ""))
    ck("the first write needs every share",
       "every share is needed" in (systems.set_mix(blog.id, head=20).get("error") or ""))
    out = systems.set_mix(blog.id, head=20, body=30, long_tail=50, branded=10, buying=30)
    ck("a mix that adds up lands", out.get("ok"), str(out))
    ck("  and the planner reads it back",
       planner.mix_for(systems.get(blog.id))
       == {"head": 20, "body": 30, "long_tail": 50, "branded": 10, "buying": 30})
    out = systems.set_mix(blog.id, buying="40", head="")
    ck("blank means leave it alone",
       out.get("ok") and planner.mix_for(systems.get(blog.id))["head"] == 20
       and planner.mix_for(systems.get(blog.id))["buying"] == 40, str(out))
    out = systems.set_mix(blog.id, head=30)
    ck("a partial write that breaks the sum is refused against what is stored",
       "got 110" in (out.get("error") or "")
       and planner.mix_for(systems.get(blog.id))["head"] == 20, str(out))
    out = systems.set_mix(blog.id, use_recommended=True)
    ck("'use the recommendation' writes exactly the recommendation",
       out.get("ok") and planner.mix_for(systems.get(blog.id)) == rec2["recommended"],
       str(planner.mix_for(systems.get(blog.id))))
    out = systems.set_mix(blog.id, clear=True)
    ck("clear removes it — the planner is back to score order",
       out.get("cleared") and planner.mix_for(systems.get(blog.id)) == {})
    with db.SessionLocal() as s:
        r_ = s.get(db.System, blog.id)
        r_.config = {**(r_.config or {}), "mix": {"head": 60, "body": 60,
                                                   "long_tail": 60, "branded": 0,
                                                   "buying": 0}}
        s.commit()
    ck("a stored trio that does not sum is read as NO mix, never bent",
       planner.mix_for(systems.get(blog.id)) == {})
    systems.set_mix(blog.id, clear=True)

    # ── 3. the planner READS it ───────────────────────────────────────────
    print("\n— with no mix, the score order stands —")
    top = keywords.targets(T, status="candidate")[0].phrase
    ck("the striking-distance body term is the top of the map on score",
       top == "acrylic stemware", top)
    out = planner.blog_rollout(systems.get(blog.id))
    first = _by_date(T, "blog")
    ck("it proposed", out["proposed"] >= 3, str(out)[:120])
    ck("the first plan is the top-scoring keyword", first[0][1] == top, str(first[:3]))
    ck("  and the run says no mix was declared", out["mix"]["declared"] == {})

    print("\n— with a mix, the class wins over the score —")
    _wipe(T, "blog")
    systems.set_mix(blog.id, head=0, body=0, long_tail=100, branded=0, buying=0)
    out = planner.blog_rollout(systems.get(blog.id))
    dates = _by_date(T, "blog")
    lt = [d for d, ph in dates if _tier(T, ph) == "long_tail"]
    other = [d for d, ph in dates if _tier(T, ph) != "long_tail"]
    ck("every long-tail plan is dated before every other plan",
       lt and (not other or max(lt) < min(other)), str(dates))
    ck("  the top-scoring body term no longer goes first",
       dates[0][1] != top, str(dates[:2]))
    ck("  and the run reports what it filed by class",
       out["mix"]["declared"]["long_tail"] == 100
       and out["mix"]["filed"]["tier"].get("long_tail", 0) == 3, str(out["mix"]))

    _wipe(T, "blog")
    systems.set_mix(blog.id, head=100, body=0, long_tail=0, branded=0, buying=0)
    planner.blog_rollout(systems.get(blog.id))
    dates = _by_date(T, "blog")
    ck("head at 100% puts the head term first", dates[0][1] == "italian tableware",
       str(dates[:2]))

    _wipe(T, "blog")
    systems.set_mix(blog.id, head=0, body=50, long_tail=50, branded=0, buying=100)
    planner.blog_rollout(systems.get(blog.id))
    dates = _by_date(T, "blog")
    ck("buying at 100% puts a buying-intent phrase first",
       dates[0][1] in ("best acrylic wine glasses", "buy melamine plates online"),
       str(dates[:2]))

    print("\n— a pillar still goes ahead of its support inside the walk —")
    _wipe(T, "blog")
    keywords.upsert(T, "italian tableware", role="pillar", cluster_key="tableware")
    keywords.upsert(T, "how to clean acrylic wine glasses", role="support",
                    cluster_key="tableware")
    systems.set_mix(blog.id, head=0, body=0, long_tail=100, branded=0, buying=0)
    out = planner.blog_rollout(systems.get(blog.id))
    when = dict((ph, d) for d, ph in _by_date(T, "blog"))
    ck("the support fits the mix and pulls its pillar ahead of it",
       "italian tableware" in when and "how to clean acrylic wine glasses" in when
       and when["italian tableware"] < when["how to clean acrylic wine glasses"],
       str(when))
    ck("  and the run says the mix's pick pulled it",
       any("the mix picked" in x for x in out["pillar_first"]),
       str(out["pillar_first"])[:160])
    _unclustered(T)

    print("\n— the mix holds over the open queue, not over one pass —")
    _wipe(T, "blog")
    # Branded and buying NEUTRAL, so only the tier shares and the open queue
    # decide: with nothing open the top body term fits at once; with two body
    # plans already open its class is over budget and long-tail goes first.
    systems.set_mix(blog.id, head=0, body=50, long_tail=50, branded=50, buying=50)
    for ph in ("acrylic stemware", "melamine plates"):
        got = systems.open_plan(T, "blog", ref=f"article:{T}:{keywords.slug(ph)}",
                                plan={"keyword": ph},
                                planned_for=(TODAY + dt.timedelta(days=1)).isoformat())
        keywords.upsert(T, ph, status="planned")
        ck(f"  a body plan for {ph!r} is already open", got.get("created"))
    planner.blog_rollout(systems.get(blog.id))
    new = [(d, ph) for d, ph in _by_date(T, "blog")
           if ph not in ("acrylic stemware", "melamine plates")]
    ck("two body plans already open, so the first NEW plan is long-tail",
       new and _tier(T, new[0][1]) == "long_tail", str(new[:2]))
    ck("  (and a body term was next in line on score, so the seed decided)",
       any(_tier(T, ph) == "body" for _, ph in new), str(new[:3]))
    systems.set_mix(blog.id, clear=True)

    # ── 4. reset ──────────────────────────────────────────────────────────
    print("\n— reset re-dates the open plans from today, keeping what you set —")
    _wipe(T, "blog")
    planner.blog_rollout(systems.get(blog.id))
    before = _by_date(T, "blog")
    ck("there are plans to reset", len(before) >= 4, str(len(before)))
    systems.set_cadence(blog.id, articles_monthly="2")
    held = systems.plans(T, "blog")[1]
    yours = (TODAY + dt.timedelta(days=40)).isoformat()
    systems.save_plan(held.id, {}, planned_for=yours)
    got = systems.open_plan(T, "blog", ref=f"refresh:{T}:zzz",
                            plan={"keyword": "acrylic stemware",
                                  "revision_notes": "position 12"},
                            planned_for=(TODAY + dt.timedelta(days=30)).isoformat())
    ck("  a refresh-lane plan is open too", got.get("created"))
    out = planner.reset_schedule(systems.get(blog.id))
    after = _by_date(T, "blog")
    lead = (TODAY + dt.timedelta(days=planner.LEAD_DAYS)).isoformat()
    ck("it re-dated every article plan but the one you dated",
       out.get("ok") and out["redated"] == len(before) - 1 + 1
       and out["kept"] == [held.ref], str(out)[:160])
    ck("  the first is LEAD_DAYS out", after[0][0] == lead, str(after[:2]))
    step = 30 // 2
    free = [d for d, _ in after if d != yours]
    gaps = {(dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days
            for a, b in zip(free, free[1:])}
    ck("  the rest follow the cadence just set — 15 days apart at 2 a month",
       gaps == {step}, str(gaps))
    ck("  your date survived", yours in [d for d, _ in after], str(after))
    ref_lane = _by_date(T, "blog", prefix="refresh:")
    ck("  the refresh lane is its own lane, re-laid from LEAD_DAYS too",
       ref_lane and ref_lane[0][0] == lead, str(ref_lane))
    systems.set_cadence(blog.id, articles_monthly="4")

    mail = _live(T, "campaign_email")
    planner.campaign_rollout(mail)
    seg_plans = systems.plans(T, "campaign_email")
    ck("campaign plans exist to reset", len(seg_plans) >= 2, str(len(seg_plans)))
    out = planner.reset_schedule(systems.get(mail.id))
    seg_after = systems.plans(T, "campaign_email")
    ck("campaigns re-lay per segment, SPACING_DAYS apart",
       out.get("ok") and out["redated"] == len(seg_plans)
       and (seg_after[0].brief or {}).get("planned_for") == lead
       and (seg_after[1].brief or {}).get("planned_for")
       == (TODAY + dt.timedelta(days=planner.LEAD_DAYS + planner.SPACING_DAYS)).isoformat(),
       str([(p.brief or {}).get("planned_for") for p in seg_after]))
    ck("  and the ref follows the date, because the ref carries it",
       all(str(p.ref).endswith((p.brief or {}).get("planned_for", "?"))
           for p in seg_after), str([p.ref for p in seg_after][:2]))
    gbp = systems.create(T, "gbp_post")
    out = planner.reset_schedule(gbp)
    ck("a calendar planner refuses by name",
       "calendar" in (out.get("error") or ""), str(out))
    ck("an unknown system is refused",
       "unknown" in (planner.reset_schedule(None).get("error") or ""))

    # ── 5. refresh ────────────────────────────────────────────────────────
    print("\n— refresh installs what the account is ready for and names the rest —")
    ck("eien starts with no blog system", systems.find("eien", "blog") is None)
    pre = systems.prerequisites("eien", "blog")
    ck("an account with no knowledge base meets NONE of a system's needs",
       not pre["ready"] and len(pre["missing"]) == 4
       and all(i["note"] == "no knowledge base yet" for i in pre["missing"]),
       str(pre["missing"])[:160])
    out = planner.refresh("eien")
    ck("with its needs unmet, blog is NAMED and not installed",
       any(u.startswith("blog:") and "needs" in u for u in out["unmet"])
       and systems.find("eien", "blog") is None, str(out["unmet"])[:200])
    real = systems.prerequisites
    systems.prerequisites = lambda t, k: {"ready": True, "missing": [], "items": []}
    try:
        out = planner.refresh("eien")
    finally:
        systems.prerequisites = real
    ck("with them met, every declared planner's system is installed",
       set(out["installed"]) >= {"blog", "campaign_email", "gbp_post"}
       and systems.find("eien", "blog") is not None, str(out["installed"]))
    ck("  off, because the switch is yours",
       systems.find("eien", "blog").status == "designed"
       and "blog" in out["off"] and out["topped"] == {}, str(out["off"]))
    _live("eien", "blog")
    out = planner.refresh("eien")
    ck("a system that is on gets topped up, and its refusal is carried",
       "blog" in out["topped"] and out["topped"]["blog"]["proposed"] == 0
       and any("map" in x for x in out["topped"]["blog"]["refusals"]),
       str(out["topped"].get("blog"))[:160])

    # ── 6. the console: the fact with its control ─────────────────────────
    print("\n— the Plan tab shows the fact with its control, and lands back —")
    c = TestClient(web.app)
    goal = c.get(f"/admin/ui?key={KEY}&tab=plan&tenant={T}&sub=goal").text
    ck("the goal room carries the mix", 'id="mix"' in goal and "Recommended:" in goal)
    ck("  with the map's shares as a fact", "candidates</span>" in goal)
    ck("  every declared share has a box",
       all(f'name="{k}"' in goal for k in planner.MIX), str(list(planner.MIX)))
    ck("  and the two one-click controls",
       'name="use_recommended"' in goal and 'name="clear"' in goal)
    ck("  saying the planner plans by score while nothing is set",
       "plans by score alone" in goal)
    r = c.get(f"/admin/plan_mix?key={KEY}&tenant={T}&head=50&body=30&long_tail=30"
              f"&branded=0&buying=0", follow_redirects=False)
    ck("a bad sum is refused where it was typed", r.status_code == 303
       and "must+sum+to+100" in r.headers.get("location", "")
       and "sub=goal" in r.headers.get("location", ""), r.headers.get("location", ""))
    r = c.get(f"/admin/plan_mix?key={KEY}&tenant={T}&use_recommended=1",
              follow_redirects=False)
    landed = c.get(r.headers["location"]).text
    ck("the recommendation is taken in one click, and the page says so",
       r.status_code == 303 and "Mix set from the recommendation" in landed
       and "this is the recommendation" in landed)
    sched = c.get(f"/admin/ui?key={KEY}&tab=plan&tenant={T}&sub=schedule").text
    ck("the schedule room offers Refresh", 'action="/admin/plan_refresh"' in sched)
    ck("  and Reset for a system with open plans that can be re-laid",
       'action="/admin/plan_reset"' in sched and 'value="blog"' in sched)
    r = c.get(f"/admin/plan_reset?key={KEY}&tenant={T}&system=blog",
              follow_redirects=False)
    ck("Reset lands back on the schedule with a sentence",
       r.status_code == 303 and "Schedule+reset" in r.headers.get("location", "")
       and "sub=schedule" in r.headers.get("location", ""), r.headers.get("location", ""))
    r = c.get(f"/admin/plan_reset?key={KEY}&tenant={T}&system=gbp_post",
              follow_redirects=False)
    ck("  a calendar planner's refusal is read there too",
       "calendar" in r.headers.get("location", ""))
    r = c.get(f"/admin/plan_refresh?key={KEY}&tenant={T}", follow_redirects=False)
    landed = c.get(r.headers["location"]).text
    ck("Refresh lands back with what it did",
       r.status_code == 303 and "Plan refreshed" in landed and "blog:" in landed)
    sysp = c.get(f"/admin/ui?key={KEY}&tab=systems&tenant={T}&system=blog").text
    ck("the system's own cadence fold carries Reset beside the cadence",
       "Reset the schedule from today" in sysp)
    empty = c.get(f"/admin/ui?key={KEY}&tab=plan&tenant=coverings&sub=schedule").text
    ck("an empty schedule still offers Refresh — the first control there",
       'action="/admin/plan_refresh"' in empty and "Nothing has been planned" in empty)

    print()
    if _fail:
        print(f"{len(_fail)} FAILED: {_fail}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
