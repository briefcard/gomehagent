"""What's new — the owner's facts for one piece — reaches every writer as
facts to state, and every check that asks "is it on file" counts it.

Owner, 2026-09-29: "if we have a specific activation, incoming collection, or
any other kind of new information, I want to be able to provide that as an
input for the generation." The angle could not carry it: the email drafter is
told the angle is "a brief written FOR you, not copy: never quote it", the
article's writer is told the only facts are the product text and the approved
claims, and the fact checks strip what is not on file.

On the way, the other half of "on file": the kit holds BRAND-WIDE claims only,
so an article or email about a product never had that product's own approved
claims in the material its fact check reads.
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'n.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["SEO_SITES_JSON"] = "{}"
os.environ.pop("SHOTS_WS", None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import (ad_craft, admin_ui as ui, articles as ar, bundle, config, db, handoff,  # noqa: E402
                 jobs, kb, llm, recreate as rc, skill, skill_pack, systems, tenants, topics, web)

_fail: list = []
T = "baci"
NEWS = ("The Portofino Blu collection arrives October 15 — 12 new pieces at $640 a set; "
        "pre-orders open October 1.")
BRAND_CLAIM = "Designed in Milan by the Italian design house Baci Milano."
PRODUCT_CLAIM = "Every Portofino piece is dishwasher safe."


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


class _R:
    ok, error, degraded, stop_reason = True, "", "", "end_turn"

    def __init__(self, text: str):
        self.text = text


def main() -> int:
    db.init_db()
    tenants.seed()
    kb.add_banned(T, "hand-decorated")
    kb.add_entity(T, "product", "portofino", "Portofino dinner set", description="Melamine and porcelain.")
    kb.add_audience(T, "hosts", "Hosts who entertain", ["dull tables"], ["a table worth a photo"])
    kb.add_claim(T, BRAND_CLAIM, "brand file", [], origin="human", status="active")
    kb.add_claim(T, PRODUCT_CLAIM, "product page", [], origin="human", status="active",
                 entity_key="portofino")
    for k in topics.CHANNELS:
        row = systems.find(T, k) or systems.create(T, k)
        with db.SessionLocal() as s:
            s.get(db.System, row.id).status = "live"
            s.commit()
    _all = {c: True for c in tenants.CAPABILITIES}
    tenants.capabilities = lambda key: dict(_all) if tenants.get(key) else {c: False for c in tenants.CAPABILITIES}

    print("— the field is on every plan that writes, with room for sentences —")
    for key in ("blog", "campaign_email", "ad_creative"):
        f = next((f for f in systems.workflow(key)["plan_fields"] if f["key"] == "news"), None)
        ck(f"{key}: a What's new field", bool(f) and f.get("kind") == "long", str(f))
    box = ui._plan_field_input({"key": "news", "kind": "long", "label": "What's new"}, NEWS, T)
    ck("  a box of sentences, showing what was typed", '<textarea name="news"' in box and "October 15" in box)

    print("\n— the package carries it, as it carries the offer and the deadline —")
    ck("an owner input, described as facts", "news" in bundle.OWNER_INPUT
       and "facts" in bundle.PARTS["news"]["what"])
    ck("declared by the article, the email and the ads",
       all("news" in skill.get(k).params for k in ("blog_article", "campaign_email", "ad_copy")))
    ck("the kit alone never had the product's own claim — the gap this closes",
       PRODUCT_CLAIM not in [c["claim"] for c in rc.kit(T).get("claims") or []])

    print("\n— the article: the news first, the product's claims, in the order the cut keeps —")
    kit_ = {"tenant": T, "entities": [{"key": "portofino", "name": "Portofino dinner set",
                                       "description": "Melamine and porcelain."}]
            + [{"key": f"p{i}", "name": f"Portofino piece {i}", "description": "x" * 700} for i in range(8)],
            "claims": [{"claim": BRAND_CLAIM}]}
    before = ar.article_material(kit_, "portofino", "portofino dinnerware")
    m = ar.article_material(kit_, "portofino", "portofino dinnerware",
                            claims=[PRODUCT_CLAIM, BRAND_CLAIM], news=NEWS)
    ck("the material leads with the news", m.splitlines()[0].endswith(NEWS), m[:120])
    ck("  carries the product's own approved claim", PRODUCT_CLAIM in m and PRODUCT_CLAIM not in before)
    ck("  and puts the claims before the related products, inside the shortest cut",
       m.index(PRODUCT_CLAIM) < m.index("Portofino piece 0") and PRODUCT_CLAIM in m[:2500])
    ck("a price the news gives is on file — the number check lets it stand",
       ar.numbers_not_in("Pre-order the set at $640.", m) == []
       and ar.numbers_not_in("Pre-order the set at $640.", before) == ["$640"])

    said: list = []
    real_ask = ar._ask
    ar._ask = lambda purpose, prompt, **k: (said.append(prompt[-1]["text"] if isinstance(prompt, list) else prompt)
                                            or _R('{"beats": []}'))
    ar.decide_story({}, {**kit_, "_news": NEWS}, "portofino dinnerware", entity_key="portofino",
                    material=m, tenant=T)
    ck("the story is told to build on it — said, not implied",
       bool(said) and "WHAT'S NEW" in said[-1] and NEWS in said[-1] and "not implied" in said[-1])
    ar.compose({**kit_, "_news": NEWS}, {"name": "p", "blocks": []}, {}, {"hook": "h", "beats": []},
               "portofino dinnerware", tenant=T, products=[], collections=[])
    ck("  and the writer, which sees the story and not the material, is handed it too",
       "WHAT'S NEW" in said[-1] and NEWS in said[-1] and "Write the finished article" in said[-1])
    said.clear()
    ar.run(T, "portofino dinnerware", entity_key="portofino", news=NEWS, claims=[PRODUCT_CLAIM, BRAND_CLAIM])
    story_p = next((x for x in said if x.startswith("You are the writer. Before a line of the article")), "")
    ck("a real article run hands its story the news — as facts to state, and first in its material",
       "WHAT'S NEW" in story_p and NEWS in story_p.split("THE MATERIAL")[-1][:400]
       and PRODUCT_CLAIM in story_p, story_p[:120] or str([x[:60] for x in said]))
    ar._ask = real_ask

    got: dict = {}
    real_run = ar.run
    ar.run = lambda tenant, keyword, **k: (got.update(k) or {"ok": False, "status": "failed", "rounds": [],
                                                            "note": "stopped by the suite", "why": "stopped by the suite"})
    r = skill.run("blog_article", T, keyword="portofino dinnerware", entity_key="portofino",
                  news=NEWS, generate_visual="no")
    ar.run = real_run
    ck("the blog skill hands the maker the news", got.get("news") == NEWS, str(r)[:200])
    ck("  and the claims it has in scope — the product's own among them",
       PRODUCT_CLAIM in (got.get("claims") or []) and BRAND_CLAIM in (got.get("claims") or []),
       str(got.get("claims")))

    print("\n— the email: the drafter says it, the maker states it, the fact check counts it —")
    config.ANTHROPIC_API_KEY = config.ANTHROPIC_API_KEY or "test-key"
    asked: list = []
    real_llm = llm.ask
    llm.ask = lambda purpose, prompt, **k: (asked.append(prompt)
                                            or _R('{"blocks": [{"type": "text", "html": "<p>x</p>"}]}'))
    skill_pack._draft_campaign_live({"rules": {"block": "RULES"}, "claims": [], "news": NEWS, "tenant": T},
                                    {"name": "New subscribers", "definition": "joined this month"},
                                    "Autumn tables", {})
    llm.ask = real_llm
    p = asked[-1] if asked else ""
    ck("the drafter is told What's new as facts to SAY — the angle stays direction",
       "WHAT'S NEW" in p and NEWS in p and "to be said" in p and p.index(NEWS) < p.index("THE ANGLE"), p[:160])
    msg = {"news": NEWS, "claims": [PRODUCT_CLAIM]}
    ck("the maker is told it as true, to state exactly",
       NEWS in rc._message_text(msg) and "TRUE AS WRITTEN" in rc._message_text(msg))
    mat = rc._material({"entities": kit_["entities"][:1], "claims": [{"claim": BRAND_CLAIM}]}, "portofino", msg)
    ck("the email's fact check reads the news first and the claim the email cites",
       mat.splitlines()[0].endswith(NEWS) and PRODUCT_CLAIM in mat and BRAND_CLAIM in mat, mat[:160])

    print("\n— the ads: the writer states it, the panel that briefs it knows it —")
    b = {"rules": {"block": "RULES"}, "news": NEWS}
    ap = "\n".join(skill_pack.ad_prompt(b, {"claim": BRAND_CLAIM}, "benefit", []))
    ck("the ad writer is handed it to state", "What's new" in ap and NEWS in ap)
    pp = "\n".join(ad_craft.panel_prompt(b, [{"n": 1, "claim": {"claim": BRAND_CLAIM}, "angle": "benefit"}]))
    ck("  and the panel's brief is written knowing it", NEWS in pp)

    print("\n— stated as given: who it is about, and a number's qualifier (2026-10-01) —")
    # Owner, of "Milan has 500 European stockists" for "over 500 retailers in
    # Europe": "that language isn't very good is it?"
    given = "We have over 500 retailers in Europe. Up to 30% off the Aqua line."
    said = {"Milan has 500 European stockists.": True, "Take 30% off the Aqua line.": True,
            "More than 500 retailers in Europe carry us.": False, "500+ European retailers.": False,
            "Up to 30% off the Aqua line.": False, "Our 500ml carafe.": False}
    wrong = {w: bundle.news_changed(w, given) for w in said}
    ck("a number the owner qualified is held to its qualifier wherever the copy states it",
       all(bool(wrong[w]) == flag for w, flag in said.items()), str({w: bool(v) for w, v in wrong.items()}))
    ck("  and it says what changed",
       "\u201cover 500\u201d" in (wrong["Milan has 500 European stockists."] or [""])[0])
    ck("every writer is told who a fact is about and that a number keeps its qualifier",
       bundle.NEWS_RULE in p and bundle.NEWS_RULE in rc._message_text(msg) and bundle.NEWS_RULE in ap
       and bundle.NEWS_RULE in story_p, "drafter / maker / ads / the article's story")
    blog = ar.check("<h1>Tables</h1><p>Milan has 500 European stockists.</p>", "Tables", "meta", "",
                    {}, {"_news": given})
    ck("the article's checks block it", any(f["code"] == "news_changed" and f["severity"] == "blocks"
                                            for f in blog), str([f["code"] for f in blog]))
    ad_ = ad_craft.review(body="Milan has 500 European stockists. Shop the edit.", headline="Tables", news=given)
    ck("  and so does the ad review", any(f["rule"] == "news_changed" and f["severity"] == "block" for f in ad_),
       str([f["rule"] for f in ad_]))
    ck("the email's fact check is told a changed subject or a dropped qualifier is listed too",
       "pinned on a different subject" in rc._TRUTH_PROMPT and "its qualifier dropped" in rc._TRUTH_PROMPT)

    print("\n— one topic, every piece that writes —")
    topics.plan(T, topic="Portofino Blu launch", channels=list(topics.CHANNELS), entity_key="portofino",
                audience_key="hosts", segment="new_subscribers", news=NEWS, on="2026-10-01")

    def plan_of(key: str, ref: str) -> dict:
        rows = [x for x in systems.plans(T, key) if x.ref == ref]
        return ((rows[0].brief or {}).get("plan") or {}) if rows else {}
    ck("the article, the email and the ads each carry it",
       all(plan_of(k, f"topic:portofino-blu-launch:{k}").get("news") == NEWS
           for k in ("blog", "campaign_email", "ad_creative")))
    ck("  the Business Profile post does not — it is made from the article",
       "news" not in plan_of("gbp_post", "topic:portofino-blu-launch:gbp_post"))
    c = TestClient(web.app)
    c.cookies.set("console", web._console_token())
    c.post("/admin/topic_plan", data={"tenant": T, "topic": "Wine Week", "channels": ["blog"],
                                       "news": NEWS, "on": "2026-10-01"}, follow_redirects=False)
    ck("the Plan tab's card files it", plan_of("blog", "topic:wine-week:blog").get("news") == NEWS)
    ck("  and has the box for it", 'name="news"' in ui.render_plan("s3cret", T))

    print("\n— the Claude file carries it as a described part, not a line of JSON —")
    run_id = systems.open_plan(T, "campaign_email", ref="t:news", planned_for="2026-10-01",
                               plan={"segment": "new_subscribers", "audience_key": "hosts",
                                     "goal": "the launch", "entity_key": "portofino", "news": NEWS})["run_id"]
    job = jobs.enqueue(T, "system_run", system_key="campaign_email", label="Email — launch",
                       payload={"key": "campaign_email", "trigger": "manual", "run_id": run_id})["id"]
    md = handoff.for_job(job).get("markdown", "")
    ck("### news — what's new, with the facts under it",
       "### news — what's new" in md and NEWS in md.split("### news")[-1][:500], md[-300:])

    print()
    print("ALL GREEN" if not _fail else f"FAILED: {len(_fail)}")
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
