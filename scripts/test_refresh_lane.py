"""A page that is owed a refresh gets a plan, and the refresh replaces it.

Phase 1 made "this published page is not working" visible. This is the step
that makes it WORK: the planner files a plan for the pages whose reading
argues for a refresh, and running one replaces the article instead of adding
a second page to the same query.

THREE JOINS, and each closes a place where the two halves were written apart:

  · THE BAND IS READ, NOT RE-DERIVED. `keywords._MOVES` holds the position
    bands once, and `attention` returns the action beside the sentence. A
    planner re-testing `position <= 10` would drift from the console, which
    would then go on saying "supports in its cluster" while a rewrite was
    quietly filed.

  · THE MONTH IS READ FROM `planned_for`. `_existing_by_month` parsed the
    month out of the ref — a date for campaigns, a keyword slug for
    articles — so every blog row raised ValueError and was skipped. The
    helper returned {} on every call and `articles_monthly` only ever bound
    WITHIN one run: three runs in a month filed three articles against a cap
    of one.

  · ONE KEYWORD, ONE PAGE, enforced in the skill where every caller passes.
    The keyword's `output_id` was overwritten on each run, so the previous
    article was orphaned rather than retired: still live, still queued, still
    counted, still on the site. A refresh would have produced the exact
    duplicate this whole lane exists to prevent.

Run: python3 scripts/test_refresh_lane.py
"""
import datetime as dt
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'rl.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import (db, kb, keywords, planner, skill, skill_pack,  # noqa: E402
                 systems, tenants)

_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _live(tenant, key, cadence=None):
    row = systems.find(tenant, key) or systems.create(tenant, key)
    with db.SessionLocal() as s:
        r = s.get(db.System, row.id)
        r.status = "live"
        if cadence:
            cfg = dict(r.config or {})
            cfg["cadence"] = cadence
            r.config = cfg
        s.commit()
    return systems.find(tenant, key)


def _published(phrase, *, live_days, pos, won_days=None, role="support"):
    keywords.upsert("baci", phrase, status="published", role=role,
                    cluster_key="c1")
    with db.SessionLocal() as s:
        r = (s.query(db.KeywordTarget)
             .filter(db.KeywordTarget.tenant == "baci",
                     db.KeywordTarget.phrase == phrase).first())
        r.published_at = db.utcnow() - dt.timedelta(days=live_days)
        r.won_at = (db.utcnow() - dt.timedelta(days=won_days)
                    if won_days else None)
        s.add(db.KeywordReading(tenant="baci", phrase=phrase,
                                position=pos, source="gsc"))
        s.commit()


def _plans(sysrow, prefix):
    with db.SessionLocal() as s:
        return [r for r in s.query(db.SystemRun)
                .filter(db.SystemRun.system_id == sysrow.id).all()
                if (r.ref or "").startswith(prefix)]


def main() -> int:
    db.init_db()
    tenants.seed()
    kb.ensure_brand("baci", "Baci")

    print("— the band decides, and the planner reads the decision —")
    for pos, want in ((6, "refresh"), (18, "supports"), (55, "reread")):
        act, sentence = keywords._owed_for(pos)
        ck(f"position {pos} argues for {want!r}", act == want, sentence)
    ck("the sentence and the action come from ONE call",
       keywords._owed_for(6)[1] == dict(
           (a, t) for _c, a, t in keywords._MOVES)["refresh"],
       "two lookups would be two places the bands could drift")

    blog = _live("baci", "blog",
                 {"articles_monthly": 1, "refreshes_monthly": 1,
                  "horizon_days": 40})

    _published("slipped page", live_days=90, pos=9, won_days=40)
    _published("stalled close", live_days=90, pos=8)
    _published("stalled far", live_days=90, pos=20)
    _published("stalled miles", live_days=90, pos=60)
    _published("no data", live_days=90, pos=None) if False else None
    keywords.upsert("baci", "brand new", status="candidate", role="pillar",
                    cluster_key="c2", priority=90)

    out = planner.blog_rollout(blog)
    refs = {r.ref for r in _plans(blog, "refresh:")}
    print()
    print("— only the pages a refresh would actually help get one —")
    # A SEPARATE TENANT WITH ROOM FOR ALL FOUR. On the capped one above these
    # assertions passed whatever the filter did: the cap admitted two plans,
    # so "position 20 is absent" was the BUDGET's behaviour, not the band's.
    # Same trap as a test that asserts on the picker's answer and calls it the
    # plan's. Here nothing is scarce, so absence can only mean refused.
    roomy = _live("wm2", "blog", {"refreshes_monthly": 9, "horizon_days": 40})
    kb.ensure_brand("wm2", "WM2")
    for ph, pos, won in (("slipped page", 9, 40), ("stalled close", 8, None),
                         ("stalled far", 20, None), ("stalled miles", 60, None)):
        keywords.upsert("wm2", ph, status="published", role="support",
                        cluster_key="c1")
        with db.SessionLocal() as sx:
            r = (sx.query(db.KeywordTarget)
                 .filter(db.KeywordTarget.tenant == "wm2",
                         db.KeywordTarget.phrase == ph).first())
            r.published_at = db.utcnow() - dt.timedelta(days=90)
            r.won_at = db.utcnow() - dt.timedelta(days=won) if won else None
            sx.add(db.KeywordReading(tenant="wm2", phrase=ph, position=pos,
                                     source="gsc"))
            sx.commit()
    planner.blog_rollout(roomy)
    wide = {r.ref for r in _plans(roomy, "refresh:")}
    ck("with room for all four, only two are filed",
       len(wide) == 2, f"{sorted(wide)} — budget cannot be the reason now")
    ck("  the page at 20 is refused on its band, not on budget",
       "refresh:wm2:stalled-far" not in wide)
    ck("  and so is the page at 60",
       "refresh:wm2:stalled-miles" not in wide)

    ck("a slipping page is filed",
       "refresh:baci:slipped-page" in refs,
       "it ranked and stopped: the intent matches and the cluster carries "
       "it, so what changed is on or past the page")
    ck("a page in striking distance is filed",
       "refresh:baci:stalled-close" in refs)
    ck("a page at 20 is NOT filed as a refresh",
       "refresh:baci:stalled-far" not in refs,
       "that band owes supports in the cluster — a different keyword's "
       "article, planned as one")
    ck("a page at 60 is NOT filed as a refresh",
       "refresh:baci:stalled-miles" not in refs,
       "intent or indexation; a rewrite changes neither")

    print()
    print("— the refresh has its own budget and its own ref space —")
    months = [str((r.brief or {}).get("planned_for", ""))[:7]
              for r in _plans(blog, "refresh:")]
    ck("the cap bound at 1/month",
       max(months.count(m) for m in set(months)) == 1,
       f"{sorted(months)} against refreshes_monthly=1")
    ck("  and the second one waits for next month rather than being dropped",
       len(set(months)) == len(months) and len(months) == 2,
       "a page that is owed a refresh does not stop being owed one because "
       "this month is full — it moves, the way an article does")
    ck("a new article was still planned",
       out["proposed"] == 1,
       "sharing one cap would have starved whichever lane lost, and the "
       "loser is always the refresh — a new page is visibly a thing that "
       "did not exist before")
    ck("refresh refs never collide with article refs",
       not any(r.ref.startswith("article:") for r in _plans(blog, "refresh:")))

    print()
    print("— the reading travels with the plan —")
    row = _plans(blog, "refresh:")[0]
    notes = ((row.brief or {}).get("plan") or {}).get("revision_notes", "")
    ck("the plan says why", "not working" in notes and "position" in notes,
       notes[:90])
    ck("`revision_notes` is a declared plan field",
       "revision_notes" in {f["key"] for f in
                            systems.workflow("blog")["plan_fields"]},
       "open_plan refuses an undeclared field, so the reason would have been "
       "dropped on the floor")

    print()
    print("— the month is read from planned_for, not parsed out of the ref —")
    blog2 = _live("wm", "blog", {"articles_monthly": 1, "horizon_days": 20})
    kb.ensure_brand("wm", "WM")
    for i, p in enumerate(["one", "two", "three"]):
        keywords.upsert("wm", p, status="candidate", role="pillar",
                        cluster_key=f"k{i}", priority=100 - i)
    for _ in range(3):
        planner.blog_rollout(blog2)
    mo = dt.date.today().strftime("%Y-%m")
    same_month = [r for r in _plans(blog2, "article:")
                  if str((r.brief or {}).get("planned_for", ""))[:7] == mo]
    ck("three runs in one month respect a cap of one",
       len(same_month) == 1,
       f"{len(same_month)} filed — the cap used to bind only WITHIN a run, "
       f"and the tick runs the planner every day")

    print()
    print("— one keyword, one page: the SECOND run replaces the first —")
    # Driven through the real skill, twice, on one keyword. Asserting on the
    # source text instead would be the hollow-assertion shape this session
    # keeps finding: it reads as coverage and proves nothing ran.
    skill_pack._draft_article_live = lambda *a, **k: (
        "<h1>Acrylic jugs</h1><p>An acrylic jug is a jug made of acrylic, "
        "and this sentence exists so the body is long enough to be an "
        "article rather than a stub.</p>", "")
    kb.add_claim("baci", "Baci jugs are dishwasher safe.", "lab report", [])
    with db.SessionLocal() as sx:
        b = sx.get(db.KbBrand, "baci")
        b.positioning = "Mid-century tableware, made to order."
        b.voice = {"tone": ["warm", "plain"]}
        # Constitutive for this skill: an article drafted against an empty ban
        # list is not thinner, it is unchecked.
        b.banned_claims = ["handmade"]
        sx.commit()
    first = skill.run("blog_article", "baci", keyword="acrylic jug",
                      role="pillar")
    oid1 = ((first.get("items") or [{}])[-1] or {}).get("output_id", "")
    ck("the first run produced a page", bool(oid1), str(first)[:120])

    second = skill.run("blog_article", "baci", keyword="acrylic jug",
                       role="pillar",
                       revision_notes="published and not working: stalled")
    oid2 = ((second.get("items") or [{}])[-1] or {}).get("output_id", "")
    ck("the second run produced a different page", bool(oid2) and oid2 != oid1)

    with db.SessionLocal() as sx:
        o1 = sx.get(db.Output, oid1)
        o2 = sx.get(db.Output, oid2)
        krow = (sx.query(db.KeywordTarget)
                .filter(db.KeywordTarget.tenant == "baci",
                        db.KeywordTarget.phrase == "acrylic jug").first())
    ck("the first page is SUPERSEDED, not left live",
       (o1.status or "") == "superseded",
       f"status={o1.status!r} — the `output_id` write moved the pointer and "
       f"left the old article live, queued, countable and on the site: the "
       f"second page on one query that cannibalisation means")
    ck("the replacement is live", (o2.status or "") != "superseded")
    ck("the keyword points at the living draft",
       (krow.output_id or "") == oid2, krow.output_id)
    ck("supersede has exactly one writer",
       __import__("pathlib").Path(skill_pack.__file__).read_text()
       .count('old.status = "superseded"') == 1,
       "the copy that drifts is always the one that stops withdrawing the "
       "old approval, which leaves two live articles for one keyword")

    print()
    print("— a page inside the cooldown is not offered again —")
    with db.SessionLocal() as s:
        r = (s.query(db.KeywordTarget)
             .filter(db.KeywordTarget.tenant == "baci",
                     db.KeywordTarget.phrase == "stalled close").first())
        r.refreshed_at = db.utcnow() - dt.timedelta(days=5)
        s.commit()
    ck("it leaves the queue entirely",
       not any(x["phrase"] == "stalled close"
               for x in keywords.attention("baci")),
       "it was refreshed and has not been re-crawled; offering it again asks "
       "for a decision that cannot yet be informed")

    print()
    print("— every candidate planned is not a quiet month —")
    blog3 = _live("eien", "blog", {"refreshes_monthly": 2, "horizon_days": 40})
    kb.ensure_brand("eien", "Eien")
    keywords.upsert("eien", "settled page", status="published")
    with db.SessionLocal() as s:
        r = (s.query(db.KeywordTarget)
             .filter(db.KeywordTarget.tenant == "eien",
                     db.KeywordTarget.phrase == "settled page").first())
        r.published_at = db.utcnow() - dt.timedelta(days=90)
        s.add(db.KeywordReading(tenant="eien", phrase="settled page",
                                position=7.0, source="gsc"))
        s.commit()
    res = planner.blog_rollout(blog3)
    ck("with no candidates left, refreshes are still filed",
       res.get("refresh_plans") == 1,
       "the early return skipped the whole pass — and 'every candidate is "
       "already planned' is exactly when refreshes are the only work left")

    print()
    print("PASS" if not _fail else f"FAILED: {len(_fail)}")
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
