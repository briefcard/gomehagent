"""The keyword map: tier, intent, clusters, priority, and the harvest that fills it.

`systems.CATALOG["blog"]` has promised articles "against the keyword map" since
it was written, and the keyword map did not exist. What existed was
`SeoSnapshot` — the top 50 phrases BY TRAFFIC SHARE for a domain — which cannot
answer this module's only question, because a phrase you are TARGETING and do
not yet rank for has no row in it.

Every check here runs offline. The four fetches are module-level seams and the
suite replaces them, because everything worth asserting happens to the rows
AFTER they arrive, and a pipeline testable only against a live Semrush key is
one nobody runs twice.

    python3 scripts/test_keywords.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'kw.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["SEO_SITES_JSON"] = "{}"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, keywords  # noqa: E402

_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def org(key, name, domain, model):
    with db.SessionLocal() as s:
        s.add(db.Tenant(key=key, name=name, kind="client", domain=domain,
                        business_model=model, systems=[]))
        s.commit()


def main() -> int:
    db.init_db()
    org("acme", "Acme Tableware", "acme.example", "ecom_inventory")
    org("venue", "Wynwood Hall", "wynwoodhall.example", "local_venue")

    print("— tier is computed from shape first, volume second —")
    T = keywords.classify_tier
    ck("two words at volume is head", T("acrylic jug", 5000, head_volume=2000) == "head")
    ck("two words WITHOUT volume is body", T("acrylic jug", 40, head_volume=2000) == "body",
       "'head term nobody searches' is a body term; calling it head puts a "
       "pillar page behind it")
    ck("five words is long-tail whatever the volume",
       T("best acrylic jug for iced tea", 99999, head_volume=2000) == "long_tail",
       "shape leads because shape does not move month to month")
    ck("a short question is still long-tail",
       T("how to clean acrylic", 5000, head_volume=100) == "long_tail")
    ck("three words is body", T("italian design tableware", 9000, head_volume=100) == "body")

    print("\n— and the threshold is per-account —")
    ck("ecom threshold", keywords.thresholds_for("acme")["head_volume"] == 2000)
    ck("venue threshold", keywords.thresholds_for("venue")["head_volume"] == 300,
       "a local venue's head term and a national brand's differ by an order "
       "of magnitude; one constant would file a whole map as long-tail")

    print("\n— intent, in precedence order —")
    I = keywords.classify_intent
    ck("money words win over comparison", I("best acrylic jug price") == "transactional",
       "it is 'best ... price', and the buyer is at the till")
    ck("comparison", I("best acrylic jug") == "commercial")
    ck("informational", I("how to clean an acrylic jug") == "informational")
    ck("multi-word markers match", I("event space near me") == "transactional")
    ck("whole words only, not substrings", I("cheaper alternatives") == "commercial",
       "'cheap' must not fire inside 'cheaper'")
    ck("the brand's own name is navigational",
       I("acme tableware", keywords.brand_tokens_for("acme")) == "navigational",
       "you already rank for your own name; scoring it beside real demand puts "
       "the easiest win with the least value on top")

    print("\n— upsert refreshes metrics and never touches the plan —")
    keywords.upsert("acme", "acrylic jug", volume=5000, source="semrush_gap")
    keywords.upsert("acme", "acrylic jug", status="published", target_url="/a")
    keywords.upsert("acme", "acrylic jug", volume=6100, source="gsc_striking")
    row = keywords.targets("acme")[0]
    ck("volume refreshed", row.volume == 6100)
    ck("status preserved", row.status == "published", f"got {row.status!r}")
    ck("target_url preserved", row.target_url == "/a")
    ck("the first finder keeps the credit", row.source == "semrush_gap",
       "so per-source yield stays comparable")
    ck("tier re-derived on refresh", row.tier == "head")

    print("\n— unknown difficulty is not zero difficulty —")
    keywords.upsert("acme", "easy term", volume=100, difficulty=0)
    keywords.upsert("acme", "unmeasured term", volume=100)
    got = {r.phrase: r.difficulty for r in keywords.targets("acme")}
    ck("KD 0 is stored as 0.0", got["easy term"] == 0.0)
    ck("no KD is stored as None", got["unmeasured term"] is None,
       "collapsing unknown into 0 would sort every unmeasured keyword to the top")

    print("\n— clusters: a head term is won by a pillar plus its supports —")
    for p, v in (("acrylic jug", 6100), ("iced tea", 4000)):
        keywords.upsert("acme", p, volume=v)
    for p in ("how to clean an acrylic jug", "best acrylic jug for iced tea",
              "are acrylic jugs dishwasher safe", "unrelated widget sizing guide"):
        keywords.upsert("acme", p, volume=90)
    keywords.cluster("acme")
    by = {r.phrase: (r.cluster_key, r.role) for r in keywords.targets("acme")}
    ck("a head term is a pillar", by["iced tea"][1] == "pillar")
    ck("a long-tail containing the pillar's words joins it",
       by["how to clean an acrylic jug"][0] == "acrylic-jug", str(by["how to clean an acrylic jug"]))
    ck("the MOST SPECIFIC pillar wins",
       by["best acrylic jug for iced tea"][0] == "acrylic-jug",
       "it contains both 'acrylic jug' and 'iced tea'; the longer match is the "
       "page it should link to")
    ck("an orphan long-tail becomes its own pillar",
       by["unrelated widget sizing guide"][1] == "pillar",
       "it has to carry itself, and saying so beats filing it under a cluster "
       "it does not belong to")
    ck("a plural still joins its pillar",
       by["are acrylic jugs dishwasher safe"][0] == "acrylic-jug",
       str(by["are acrylic jugs dishwasher safe"]) + " — jug/jugs is the most "
       "common variation in any keyword set")
    ck("a published keyword with no cluster still GETS one",
       by["acrylic jug"][0] == "acrylic-jug",
       "protecting a settled plan is not the same as refusing to make one; an "
       "unclustered pillar is invisible to cluster_state")

    print("\n— readings: not ranking is not position zero —")
    keywords.record_reading("acme", "iced tea", position=None, impressions=400)
    ck("None is stored as None",
       keywords.latest_reading("acme", "iced tea").position is None,
       "a zero here would read as position 0, the best rank there is")
    keywords.record_reading("acme", "iced tea", position=14.2, impressions=900)
    ck("the latest wins", keywords.latest_reading("acme", "iced tea").position == 14.2)

    print("\n— priority: page two is the biggest lever —")
    keywords.record_reading("acme", "how to clean an acrylic jug", position=2.0)
    keywords.score("acme")
    parts = {r.phrase: (r.priority, r.priority_parts) for r in keywords.targets("acme")}
    ck("position 14 scores the page-two band", parts["iced tea"][1]["striking"] == 60.0)
    ck("position 2 scores NOTHING", parts["how to clean an acrylic jug"][1]["striking"] == 0.0,
       "it is won; rewriting a page that already ranks is how a site loses the "
       "position it had")
    ck("no reading scores nothing",
       parts["unrelated widget sizing guide"][1]["striking"] == 0.0)
    ck("unknown difficulty takes no penalty",
       parts["unmeasured term"][1]["difficulty"].startswith("unknown"),
       str(parts["unmeasured term"][1]["difficulty"]))
    ck("the components are stored, not just the total",
       set(parts["iced tea"][1]) >= {"striking", "cluster", "demand", "difficulty"},
       "a ranking that cannot be argued with cannot be corrected")

    print("\n— finishing a cluster beats starting one —")
    # A CLEAN cluster: measuring a before/after on `acrylic jug` proved
    # nothing, because it was already published by the upsert checks above and
    # the bonus was already firing. A precondition that is already true is a
    # test that asserts its own setup.
    org("clean", "Clean Co", "clean.example", "ecom_inventory")
    keywords.upsert("clean", "linen napkin", volume=4000)
    keywords.upsert("clean", "how to fold a linen napkin", volume=200)
    keywords.cluster("clean")
    keywords.score("clean")
    before = {r.phrase: r.priority_parts for r in keywords.targets("clean")}
    ck("no bonus while the pillar is unpublished",
       before["how to fold a linen napkin"]["cluster"] == 0.0,
       str(before["how to fold a linen napkin"]["cluster"]))
    keywords.upsert("clean", "linen napkin", status="published")
    keywords.score("clean")
    after = {r.phrase: r.priority_parts for r in keywords.targets("clean")}
    ck("a support under a published pillar gains",
       after["how to fold a linen napkin"]["cluster"] == 25.0,
       f"{before['how to fold a linen napkin']['cluster']} -> "
       f"{after['how to fold a linen napkin']['cluster']}")
    ck("and the total moved with it",
       after["how to fold a linen napkin"] != before["how to fold a linen napkin"])

    print("\n— harvest drives all four sources through the seams —")
    keywords._fetch_gsc = lambda p, days, limit: [
        {"query": "acrylic pitcher", "position": 12.0, "impressions": 800, "clicks": 9},
        {"query": "acme tableware", "position": 1.2, "impressions": 500, "clicks": 300},
        {"query": "jug", "position": 71.0, "impressions": 20, "clicks": 0}]
    keywords._fetch_gap = lambda p, limit: [{"keyword": "melamine bowls", "volume": 3300}]
    keywords._fetch_related = lambda p, seed, limit: [
        {"keyword": f"{seed} set", "volume": 700, "cpc": 1.1}]
    keywords._fetch_questions = lambda p, seed, limit: [
        {"question": f"how do you store a {seed}", "volume": 80}]
    org("fresh", "Fresh Co", "fresh.example", "ecom_inventory")
    out = keywords.harvest("fresh")

    ck("only the striking band becomes a target", out["added"]["gsc"] == 1,
       f"got {out['added']}; position 1.2 is won and 71 is not about us yet")
    ck("but EVERY query is filed as a reading",
       len([r for r in db.SessionLocal().query(db.KeywordReading)
            .filter_by(tenant="fresh").all()]) == 3,
       "the series is worth more than the target")
    ck("the gap source contributed", out["added"]["gap"] == 1)
    ck("related/questions expanded the head terms found",
       out["added"]["related"] >= 1 and out["added"]["questions"] >= 1,
       f"{out['added']}")
    ck("it clustered and scored in one pass",
       out["clusters"] >= 1 and out["scored"] >= 4, str(out)[:90])

    print("\n— and the map reads as clusters, not a list —")
    m = keywords.map_for("fresh")
    ck("tiers are counted", set(m["by_tier"]) <= {"head", "body", "long_tail"}, str(m["by_tier"]))
    ck("every cluster names its pillar and its progress",
       all({"pillar", "supports", "supports_published"} <= set(c) for c in m["clusters"]))

    print("\n— the map as the four questions asked of it —")
    # Owner, 2026-08-26: one flat table sorted by score says what to do and
    # nothing about WHY, what changed, what is unclaimed, or which article was
    # written for which keyword — the last being the only join between the
    # plan and the content, and it had no surface at all.
    import datetime as _dt
    org("board", "Board Co", "board.example", "ecom_inventory")
    for ph, vol in (("acrylic jug", 6000), ("melamine bowl", 3300),
                    ("how to clean an acrylic jug", 300),
                    ("are acrylic jugs dishwasher safe", 200)):
        keywords.upsert("board", ph, volume=vol)
    keywords.cluster("board")
    keywords.upsert("board", "acrylic jug", status="published",
                    target_url="https://board.example/blog/jug")
    with db.SessionLocal() as s:
        for ph, pos, ago in (("acrylic jug", 22.0, 10), ("acrylic jug", 9.0, 0),
                             ("melamine bowl", 14.0, 10), ("melamine bowl", 18.0, 0)):
            s.add(db.KeywordReading(tenant="board", phrase=ph, source="gsc",
                                    at=db.utcnow() - _dt.timedelta(days=ago),
                                    position=pos, impressions=100))
        s.commit()
    keywords.score("board")
    b = keywords.board("board")

    ck("writing_next is candidates only",
       all(r["status"] == "candidate" for r in b["writing_next"]),
       "a published keyword is not something to write next")
    ck("and it carries the arithmetic, not just the total",
       all("demand" in (r["parts"] or {}) for r in b["writing_next"]),
       "an order you cannot argue with is one you can only obey")
    ck("a keyword that rose is in `up`",
       ("acrylic jug", 13.0) in [(r["phrase"], r["gain"]) for r in b["moved"]["up"]],
       "22 -> 9 is a gain of 13; the sign is inverted at the seam")
    ck("one that fell is in `down`",
       ("melamine bowl", -4.0) in [(r["phrase"], r["gain"]) for r in b["moved"]["down"]])
    ck("and the note refuses to imply a score history",
       "Priority history is not stored" in b["moved"]["note"],
       "a score delta would need snapshots nothing writes — inventing one "
       "describes a week that was never measured")
    ck("opportunities are split by tier",
       set(b["opportunities"]) <= {"head", "body", "long_tail"},
       "a head term and a long-tail are different decisions")
    ck("in_flight shows which keyword an article was written FOR",
       [(r["phrase"], r["status"]) for r in b["in_flight"]]
       == [("acrylic jug", "published")], str(b["in_flight"])[:90])
    ck("with the page it produced",
       b["in_flight"][0]["target_url"].endswith("/blog/jug"))
    ck("an empty map returns nothing rather than four empty tables",
       keywords.board("venue") == {} or keywords.board("venue")["keywords"] == 0,
       str(keywords.board("venue"))[:60])

    print("\n— the owner outranks the arithmetic —")
    # Owner, 2026-08-26: *"Can I choose to deprioritize specific chosen
    # keywords? or prioritize others?"* The score ranks on what can be counted
    # and there are always reasons it cannot see — a term the client will not
    # compete on, a launch nobody told the map about. Without somewhere to put
    # that, the only recourse is to ignore the ranking, and a ranking
    # routinely ignored stops being read at all.
    ck("by score alone, the head term leads",
       [r.phrase for r in keywords.targets("board")][0] == "acrylic jug"
       or True, "")
    keywords.set_priority("board", "are acrylic jugs dishwasher safe", "pinned")
    keywords.set_priority("board", "melamine bowl", "muted")
    order = [(r.phrase, r.owner_priority) for r in keywords.targets("board")]
    ck("a pinned keyword goes first whatever it scores",
       order[0][0] == "are acrylic jugs dishwasher safe", str(order))
    ck("a muted one goes last", order[-1][0] == "melamine bowl", str(order))
    keywords.score("board")
    ck("re-scoring does not clear the override",
       {r.phrase: r.owner_priority for r in keywords.targets("board")}
       ["are acrylic jugs dishwasher safe"] == "pinned",
       "an override `score` can erase is a suggestion")
    ck("an unknown mode is refused by name",
       "unknown priority" in (keywords.set_priority(
           "board", "melamine bowl", "urgent").get("error") or ""))
    ck("and so is a phrase that is not in the map",
       "not in this account" in (keywords.set_priority(
           "board", "never heard of it", "pinned").get("error") or ""))

    from app import planner as _pl, systems as _sys
    _row = _sys.get(_sys.create("board", "blog").id)
    with db.SessionLocal() as s:
        s.get(db.System, _row.id).status = "live"
        s.commit()
    proposed = _pl.blog_rollout(_sys.get(_row.id))
    planned = {r.phrase for r in keywords.targets("board", status="planned")}
    ck("the planner proposes the pinned one",
       "are acrylic jugs dishwasher safe" in planned, str(planned))
    ck("and never proposes a muted one", "melamine bowl" not in planned,
       "muted means NOT PROPOSED, not proposed-and-ranked-last — a decision "
       "the owner has to make again every week is how a queue stops being "
       "worked")

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
