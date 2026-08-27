"""The blog planner and the blog skill — which landed together, as promised.

`CATALOG["blog"]` carried this note from the day it was written: *"No
`plan_fields` yet: plans exist only once a skill can consume them, or they
would queue forever. The keyword-map planner and the drafting skill land
together."* This suite is what that sentence was waiting for.

The two properties worth more than the rest:

  * **A support is never planned before its pillar.** A cluster of supports
    pointing at a page that does not exist is the most common way this work
    produces motion and no result, and it is a rule a priority score cannot
    express.
  * **A failed draft files NOTHING.** `ad_copy` degrades to a composer because
    a three-line placeholder is usable; a templated ARTICLE is a thin page,
    and thin pages actively harm the thing this system exists to improve.

    python3 scripts/test_blog_skill.py
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'bs.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["SEO_SITES_JSON"] = "{}"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, kb, keywords, planner, skill, skill_pack, systems, tenants  # noqa: E402

_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    db.init_db()
    with db.SessionLocal() as s:
        s.add(db.Tenant(key="acme", name="Acme Tableware", kind="client",
                        domain="acme.example", business_model="ecom_inventory",
                        cms={"platform": "shopify", "creds_key": "acme",
                             "blog_id": "77"}, systems=["blog"]))
        s.commit()
    # A CONNECTION, not a declaration. Since Phase 2 `cms` falls out of a
    # Shopify credential carrying `write_content` — so a tenant row that merely
    # NAMES shopify is correctly blocked, and this suite has to connect one
    # like any other account would.
    from app import credentials
    with db.SessionLocal() as s:
        s.add(db.Credential(tenant="acme", provider="shopify", site="",
                            kind="oauth", secret=credentials._encrypt("tok"),
                            meta={"domain": "acme.myshopify.com"},
                            scopes="read_products,write_products,write_content",
                            status="active", granted_at=db.utcnow()))
        s.commit()
    kb.ensure_brand("acme", "Acme Tableware")
    # Untagged is deliberate: §2.27 — an untagged approved claim is BRAND-WIDE
    # proof, not an unusable one, and an article is exactly the brand-wide case.
    kb.add_claim("acme", "Acme jugs are made from BPA-free acrylic.",
                 "supplier spec sheet, 2026", [])
    with db.SessionLocal() as s:
        b = s.get(db.KbBrand, "acme")
        b.positioning = "Mid-century tableware, made to order."
        b.voice = {"tone": ["warm", "plain"]}
        b.banned_claims = ["handmade"]
        s.commit()
    sysrow = systems.get(systems.create("acme", "blog").id)
    systems.set_status(sysrow.id, "live") if hasattr(systems, "set_status") else None
    with db.SessionLocal() as s:
        r = s.get(db.System, sysrow.id)
        r.status = "live"
        s.commit()
    sysrow = systems.get(sysrow.id)

    print("— the declaration the planner and skill share —")
    wf = systems.workflow("blog")
    ck("blog declares its skill", wf["skill"] == "blog_article")
    ck("and plan fields", bool(wf["plan_fields"]))
    sk = skill.get("blog_article")
    ck("every plan field is a parameter the skill accepts",
       all(f["key"] in sk.params for f in wf["plan_fields"]),
       "growing the plan and teaching the skill to honour it must land in one "
       "change")
    ck("a ban list is CONSTITUTIVE for an article",
       "banned_claims" in sk.constitutive,
       "the longest thing this system writes, on a public page under the "
       "client's own domain — drafting it against an empty ban list is not a "
       "thinner article, it is an unchecked one")

    print("\n— the planner proposes from the map, pillar first —")
    keywords.upsert("acme", "acrylic jug", volume=6000)
    keywords.upsert("acme", "how to clean an acrylic jug", volume=300)
    keywords.upsert("acme", "are acrylic jugs dishwasher safe", volume=200)
    keywords.cluster("acme")
    # Make a SUPPORT the top-ranked candidate, so the pillar rule has to fire.
    keywords.record_reading("acme", "how to clean an acrylic jug", position=13.0)
    keywords.score("acme")
    top = keywords.targets("acme")[0]
    ck("a support outranks the pillar on score alone",
       top.phrase == "how to clean an acrylic jug" and top.role == "support",
       f"top={top.phrase!r} role={top.role!r}")

    out = planner.blog_rollout(sysrow)
    ck("it proposed", out["proposed"] >= 1, str(out)[:110])
    states = {r.phrase: r.status for r in keywords.targets("acme")}
    ck("the pillar is now planned", states["acrylic jug"] == "planned", str(states))
    ck("the support that ranked first is planned TOO, not skipped",
       states["how to clean an acrylic jug"] == "planned",
       "the pillar goes AHEAD of it, not instead of it — the first cut "
       "consumed the highest-priority keyword in the map by promoting over it")
    ck("and the run SAYS it reordered", bool(out["pillar_first"]),
       str(out["pillar_first"])[:110])

    print("\n— idempotent per keyword —")
    again = planner.blog_rollout(sysrow)
    ck("a re-run refreshes rather than duplicates",
       again["proposed"] == 0 or again["refreshed"] >= 1, str(again)[:110])

    print("\n— a paused system files nothing —")
    # A fresh candidate first, or this would pass because the queue is empty
    # rather than because the switch held — a test asserting its own setup.
    keywords.upsert("acme", "melamine bowl", volume=4000)
    keywords.cluster("acme")
    keywords.score("acme")
    with db.SessionLocal() as s:
        s.get(db.System, sysrow.id).status = "paused"
        s.commit()
    off = planner.blog_rollout(systems.get(sysrow.id))
    ck("and says why", off["proposed"] == 0 and any(
        "paused" in r or "not live" in r or "on" in r for r in off["refusals"]),
       str(off["refusals"])[:110])
    ck("the candidate is still a candidate",
       {r.phrase: r.status for r in keywords.targets("acme")}["melamine bowl"]
       == "candidate")
    with db.SessionLocal() as s:
        s.get(db.System, sysrow.id).status = "live"
        s.commit()

    print("\n— the skill refuses rather than filing a thin page —")
    skill_pack._draft_article_live = lambda *a, **k: ("", "ANTHROPIC_API_KEY is not set")
    r = skill.run("blog_article", "acme", keyword="acrylic jug", role="pillar")
    ck("it reports not-drafted", "not drafted" in str(r).lower(), str(r)[:140])
    ck("and produced nothing", not (r.get("items") or []),
       "a templated article would rank worse than no article")

    r = skill.run("blog_article", "acme")
    ck("no keyword is refused by name", "keyword" in str(r).lower(), str(r)[:120])

    print("\n— with a model, the cluster's questions become the article's —")
    seen: dict = {}

    def _fake(bundle, keyword, role, angle, questions, links, entity,
              avoid=None):
        seen.update(keyword=keyword, role=role, questions=list(questions),
                    links=list(links))
        return ("<h1>Acrylic jugs</h1><p>An acrylic jug is a jug made of "
                "acrylic.</p><h3>Are acrylic jugs dishwasher safe?</h3>"
                "<p>Check the base.</p>"), ""
    skill_pack._draft_article_live = _fake

    keywords.upsert("acme", "how to clean an acrylic jug",
                    target_url="https://acme.example/blog/clean", status="published")
    r = skill.run("blog_article", "acme", keyword="acrylic jug", role="pillar")
    ck("the question sibling was offered as a question",
       "are acrylic jugs dishwasher safe" in seen.get("questions", []),
       str(seen.get("questions")))
    ck("a sibling that is already PUBLISHED is not also an FAQ",
       "how to clean an acrylic jug" not in seen.get("questions", []),
       "it has its own URL and is offered as a link — answering it inline "
       "would compete with our own page for the same query")
    ck("only a sibling with a real URL became a link",
       [L["url"] for L in seen.get("links", [])] == ["https://acme.example/blog/clean"],
       str(seen.get("links")))
    ck("the role reached the prompt", seen.get("role") == "pillar")
    ck("an article was produced", len(r.get("items") or []) == 1, str(r)[:140])
    ck("it passed the validator", r["items"][0].get("ok") is True,
       str(r["items"][0].get("failures"))[:140])
    with db.SessionLocal() as s:
        out_row = s.get(db.Output, r["items"][0]["output_id"])
    ck("and is filed in the ledger as a cms_article",
       (out_row.format or "") == "cms_article", str(out_row and out_row.format))
    ck("carrying the claim it was built on", bool(out_row.claim_ids),
       "attribution is what makes anti-repeat and hygiene answerable")

    print("\n— no CMS is not a reason to withhold the article —")
    # Owner, 2026-08-26, hitting `{"error":"not ready to go live","blockers":
    # ["not connected: cms"]}`: *"Remember we said if theres no CMS to publish
    # to, just give me the article copy."* The retention was built and the
    # GATE was left in place, so an account on Squarespace could not run the
    # system at all — and an article is real work before it is a published
    # page: drafted, checked against the ban list, through the validator and
    # the structure checks, and kept whole.
    ck("the blog system requires no connection to RUN",
       systems.CATALOG["blog"]["requires"] == (),
       "publishing needs a CMS; writing does not")

    # A SEPARATE account with nothing connected. Changing acme's declaration
    # proved nothing: acme holds a live Shopify credential and a WIRED cms
    # correctly beats a declared one, so `backend()` resolved and the run fell
    # through to the blog_id branch. The test was asserting its own setup.
    with db.SessionLocal() as s:
        s.add(db.Tenant(key="sqonly", name="Squarespace Only", kind="client",
                        domain="sqonly.example", business_model="local_venue",
                        cms={"platform": "squarespace"}, systems=[]))
        s.commit()
    kb.ensure_brand("sqonly", "Squarespace Only")
    with db.SessionLocal() as s:
        _b = s.get(db.KbBrand, "sqonly")
        _b.banned_claims, _b.voice = ["guaranteed"], {"tone": ["direct"]}
        s.commit()
    kb.add_claim("sqonly", "Eight venues across the campus.", "site plan", [])
    _sq = systems.create("sqonly", "blog")
    with db.SessionLocal() as s:
        s.get(db.System, _sq.id).status = "live"
        s.commit()
    keywords.upsert("sqonly", "miami event venue", volume=800)
    keywords.cluster("sqonly")
    skill_pack._draft_article_live = lambda *a, **k: (
        "<h1>x</h1><p>Eight venues across the campus.</p>", "")
    r_nocms = skill.run("blog_article", "sqonly", keyword="miami event venue",
                        role="pillar")
    ck("it still produces the article", len(r_nocms.get("items") or []) == 1,
       str(r_nocms)[:110])
    ck("and names the REAL reason nothing was queued",
       "squarespace" in r_nocms["summary"],
       "testing for an empty platform missed this entirely — Ironside "
       "DECLARES squarespace, so the run reported a missing blog_id for a "
       "store that does not exist. `backend()` already refuses by name")
    oid = r_nocms["items"][0]["output_id"]
    with db.SessionLocal() as s:
        kept = s.query(db.ArtifactBody).filter_by(output_id=oid).first()
    ck("the copy is kept whole, however short",
       kept is not None and kept.body,
       "the `> 2000` guard threw away exactly the case this table exists "
       "for — a short article on an account with nowhere else to keep it")
    # REWORDED 2026-08-26: the paragraph became a sentence when runs started
    # LANDING on the review page — the summary stopped carrying what the page
    # carries. The property was never the words; it is that the summary says
    # where the article lives.
    ck("and the run says where to read it",
       "review page" in r_nocms["summary"], r_nocms["summary"][-90:])

    print("\n— eight supports in one cluster are not eight of the same article —")
    # Owner, 2026-08-26, on a proposed intent->format lookup: *"the format
    # should be dynamic right? Otherwise we will be generating a lot of the
    # same articles for the same keywords. It will take many different angles
    # and reader-driven content to rank sometimes."* He is right: a table
    # mapping "best X" to "comparison" guarantees the failure it looks like it
    # prevents — every support under one pillar arrives as a version of the
    # same page, competing for the query they were all written to win.
    #
    # `campaign_email` has solved this since it was written: `_craft_brief`
    # shows the model the shapes and openings of the last three sends and
    # tells it to move away from them. Articles had none of it.
    # NOT `seen` — this suite already binds that name to a dict at the "with a
    # model" section, and `_fake` writes to it with `.update()`. Rebinding it
    # to a list here made that call an AttributeError two hundred lines later,
    # in a check about something else entirely.
    drafted: list = []

    def _watch(bundle, kw_, role_, angle_, questions_, links_, entity_,
               avoid_=None):
        drafted.append((kw_, angle_, len(avoid_ or [])))
        return f"<h1>{kw_}</h1><p>Acme jugs are made from BPA-free acrylic.</p>", ""
    skill_pack._draft_article_live = _watch
    for ph in ("how to clean a jug", "are jugs dishwasher safe",
               "can you freeze a jug", "how to store jugs"):
        keywords.upsert("acme", ph, volume=200)
    keywords.cluster("acme")
    for ph in ("how to clean a jug", "are jugs dishwasher safe",
               "can you freeze a jug", "how to store jugs"):
        skill.run("blog_article", "acme", keyword=ph, role="support")

    ck("the drafter is handed what came before it",
       all(isinstance(n, int) for _k, _a, n in drafted) and len(drafted) == 4,
       "the `avoid` argument exists on the seam and is passed every call")
    ck("every angle is one the vocabulary declares",
       all(a in skill_pack.ARTICLE_ANGLES for _k, a, _n in drafted),
       str([a for _k, a, _n in drafted]))

    # The rotation itself, driven directly — four full skill runs prove the
    # wiring, this proves the property, and mixing the two hides which broke.
    hist: list = []
    picked = []
    for _ in range(4):
        a, _why = skill_pack._pick_angle("informational", hist, "jugs")
        picked.append(a)
        hist.insert(0, (a, "jugs", ""))
    ck("four articles in one cluster take four different angles",
       len(set(picked)) == 4, str(picked))
    ck("and a fifth cluster starts over, because sameness is only noticed "
       "inside a cluster",
       skill_pack._pick_angle("informational", hist, "bowls")[0] == picked[0],
       "history is filtered to THIS cluster first — eight supports around one "
       "pillar are where identical recipes compete with each other")

    ck("intent narrows the set rather than fixing the format",
       skill_pack._pick_angle("commercial", [], "")[0]
       != skill_pack._pick_angle("informational", [], "")[0],
       "a how-to query is not answered with a comparison — but neither "
       "intent gets ONE answer")
    ck("and when the set is exhausted it cycles least-recent-first",
       [skill_pack._pick_angle("informational",
                               [(a, "c", "") for a in reversed(prev)], "c")[0]
        for prev in ([], ["definitive"], ["definitive", "walkthrough"])]
       == ["definitive", "walkthrough", "correction"],
       "keying off FIRST use meant the angle that opened a cluster won every "
       "round forever after")
    ck("an angle named on the plan is not overridden",
       skill.run("blog_article", "acme", keyword="how to clean a jug",
                 role="support", angle="comparison")["detail"]["angle_why"]
       == "set on the plan",
       "the owner naming one is a decision, not a preference")

    print("\n— drafted is not published, and the summary knows the difference —")
    ck("a queued publish says so", r["summary"].startswith("drafted and queued"),
       r["summary"][:90])
    ck("and says approving is the next step", "approve" in r["detail"]["next"],
       r["detail"]["next"][:70])
    ck("the approval id is carried",
       "Queued for your approval" in r["detail"]["publish"]["detail"],
       r["detail"]["publish"]["detail"][:70])

    # The exact shape the owner hit: a tenant with a connected store and no
    # blog_id. The old summary read "support article for 'x'" and the harness
    # printed "1 item(s)", so it looked published; nothing had been queued.
    with db.SessionLocal() as s:
        row_t = s.get(db.Tenant, "acme")
        row_t.cms = {"platform": "shopify", "creds_key": "acme"}   # blog_id gone
        s.commit()
    r_noid = skill.run("blog_article", "acme", keyword="acrylic jug", role="pillar")
    ck("no blog_id is NOT reported as a success",
       r_noid["summary"].startswith("DRAFTED"), r_noid["summary"][:90])
    ck("the reason is in the summary, not only in a note",
       "blog_id" in r_noid["summary"], r_noid["summary"][:120])
    ck("and it is still filed in the ledger, so nothing is lost",
       len(r_noid.get("items") or []) == 1,
       "the draft is real work; what is false is calling it published")
    with db.SessionLocal() as s:
        s.get(db.Tenant, "acme").cms = {"platform": "shopify", "creds_key": "acme",
                                        "blog_id": "77"}
        s.commit()

    print("\n— a refusal from the queue path is a refusal, not a success —")
    import app.seo_tools as _st
    _real = _st._propose
    _st._propose = lambda *a, **k: ("BLOCKED — these internal links don't "
                                    "resolve on acme.example: /nope")
    skill_pack._draft_article_live = _fake
    r_blocked = skill.run("blog_article", "acme", keyword="acrylic jug", role="pillar")
    ck("a BLOCKED propose reads as not queued",
       r_blocked["detail"]["publish"]["queued"] is False
       and r_blocked["summary"].startswith("DRAFTED"),
       r_blocked["summary"][:100])
    _st._propose = _real

    print("\n— a banned claim is blocked BY THE VALIDATOR, with the claim in scope —")
    skill_pack._draft_article_live = lambda *a, **k: (
        "<h1>Jugs</h1><p>Every jug is handmade in our workshop.</p>", "")
    r_bad = skill.run("blog_article", "acme", keyword="acrylic jug", role="pillar")
    item = (r_bad.get("items") or [None])[0]
    ck("something WAS drafted and then refused", item is not None,
       "the claim is still in scope here, so a refusal cannot be the "
       "no-proof path wearing the validator's clothes")
    ck("the validator is what refused it",
       item is not None and item.get("ok") is False
       and any(f["rule"] == "banned_claim" for f in (item.get("failures") or [])),
       str(item.get("failures") if item else None)[:130])

    print("\n— with no approved claim there is no article, and no model call —")
    called = {"n": 0}

    def _count(*a, **k):
        called["n"] += 1
        return "<h1>x</h1><p>y</p>", ""
    skill_pack._draft_article_live = _count
    with db.SessionLocal() as s:                     # retire the only claim
        for c in s.query(db.KbClaim).filter_by(tenant="acme").all():
            c.status = "retired"
        s.commit()
    r_none = skill.run("blog_article", "acme", keyword="acrylic jug")
    ck("nothing is produced", not (r_none.get("items") or []), str(r_none)[:110])
    ck("and the model was never asked", called["n"] == 0,
       "spending a call to produce something the validator will always refuse "
       "as uncited is not a validation failure, it is the KB backlog")
    ck("which is what it says",
       any("backlog" in n for n in (r_none.get("notes") or [])),
       str(r_none.get("notes"))[:120])

    # ------------------------------------------------------------------
    print("\n— the SEO head is pre-filled AND optimized to the keyword —")
    # Owner, 2026-08-27: "pre-fill Title, SEO, and Meta descriptions
    # optimized to the target keywords." _meta_description took the keyword
    # and never used it; seo_title was a mid-word [:60] chop.
    st = skill_pack._seo_title("acrylic wine glasses",
                               "Toast Without Fear: Our Sturdiest Stemware")
    ck("a title missing the keyword gets the keyword LEADING, ≤60",
       st.lower().startswith("acrylic wine glasses") and len(st) <= 60, st)
    st2 = skill_pack._seo_title("acrylic wine glasses",
                                "Acrylic Wine Glasses That Survive the Pool")
    ck("a title already carrying it is kept, word-trimmed",
       st2 == "Acrylic Wine Glasses That Survive the Pool"
       and " — " not in st2, st2)
    ck("no mid-word chop at the 60 boundary",
       not skill_pack._seo_title("k", "word " * 30).rstrip("…").endswith("wor"))
    body = ("<p>Summer tables get rowdy. Our acrylic wine glasses shrug off "
            "drops and dishwashers alike. Guests notice the shine first.</p>"
            "<p>More prose follows here.</p>")
    md = skill_pack._meta_description("acrylic wine glasses", body)
    ck("the meta description STARTS at the article's own keyword sentence",
       md.startswith("Our acrylic wine glasses") and len(md) <= 155, md)
    md2 = skill_pack._meta_description("acrylic wine glasses",
                                       "<p>Nothing relevant here at all.</p>")
    ck("…and falls back to the opening when no sentence carries it",
       md2.startswith("Nothing relevant"), md2)

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
