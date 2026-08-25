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

    def _fake(bundle, keyword, role, angle, questions, links, entity):
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
