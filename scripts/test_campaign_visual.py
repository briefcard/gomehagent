"""Bespoke campaign visuals, governed: approved library or nothing.

What is checked is the LOOP, not Canva: the hero image in a campaign email
can only ever be an APPROVED, OWNED photograph (entity-scoped beats
brand-wide, logos are never heroes, reference/proposed rows are structurally
unreachable); a miss is a NAMED absence; opting into `draft_visual` creates a
right-sized Canva draft that lands in the library as a design — which cannot
be selected as a hero, so nothing generated in a run can ship in that same
run; and the full skill path puts the approved photograph into the rendered
HTML, drafts into the ESP, and files the use on the asset. sabotage.
asset_rights_gate removes the rights filter and this suite must fail.

Run: python3 scripts/test_campaign_visual.py
"""
import json
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'cv.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import (canva, creative, credentials as cred, db, esp, kb,  # noqa: E402
                 skill, skill_pack, systems, tenants)

_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


_ALL = {c: True for c in tenants.CAPABILITIES}
tenants.capabilities = lambda key: dict(_ALL) if tenants.get(key) else \
    {c: False for c in tenants.CAPABILITIES}

_drafted: list = []
_designs: list = []


def _fake_esp():
    esp.provider_for = lambda t: "omnisend"
    esp.personalize = lambda t, html: {"ok": True, "html": html}

    class _Mod:
        @staticmethod
        def draft_from_html(tenant, *, name, subject, sender_name, html,
                            preheader=""):
            _drafted.append({"tenant": tenant, "subject": subject})
            return {"ok": True, "campaign_id": "camp_1"}
    esp.backend = lambda t: (_Mod, "")


def _fake_canva(connected: set):
    orig = cred.resolve

    def _resolve(tenant, provider, site=""):
        if provider == "canva":
            return ({"secret": "tok"} if tenant in connected else {})
        return orig(tenant, provider, site)
    cred.resolve = _resolve

    def _create(tenant, *, title, design_type="", asset_id="", entity_key="",
                width=0, height=0):
        _designs.append({"tenant": tenant, "title": title,
                         "width": width, "height": height})
        return {"ok": True, "design_id": "DAF9",
                "edit_url": "https://canva.example/e/DAF9", "recorded": "ok"}
    canva.create_design = _create


def _seed_live(tenant):
    kb.ensure_brand(tenant, tenant.title())
    kb.set_brand(tenant, positioning="Italian-designed tableware.",
                 tone="direct, warm")
    # An empty ban list fails campaign validation BY DESIGN ("the validator
    # has nothing to check against, so nothing can be sent safely").
    kb.add_banned(tenant, "made in Italy")
    kb.add_situation(tenant, "quality", patterns=[["quality"]],
                     description="Is it any good?", origin="seed")
    kb.add_claim(tenant, "Designed in Milan and used in leading hotels.",
                 "brand brief", ["quality"], origin="human", status="active")
    row = systems.find(tenant, "campaign_email") or systems.create(tenant, "campaign_email")
    with db.SessionLocal() as s:
        r = s.get(db.System, row.id)
        r.status = "live"
        s.commit()


def main() -> int:  # noqa: PLR0915
    db.init_db()
    tenants.seed()
    _seed_live("baci")
    _fake_esp()
    _fake_canva(connected=set())
    from app import brand_theme
    ok = brand_theme.approve("baci", {"footer.address":
                                      "2875 NE 191st St, Aventura, FL 33180"})
    assert ok.get("ok") and ok["gaps"] == [], ok
    kb.add_entity("baci", "product", "aqua-pitcher", "Aqua pitcher")

    print("— selection: approved and owned, or nothing —")
    kb.add_asset("baci", "https://cdn.example/ref-competitor.jpg",
                 rights=kb.REFERENCE, title="Competitor ad", origin="human")
    kb.add_asset("baci", "https://cdn.example/crawl-candidate.jpg",
                 rights=kb.OWNED, title="Crawl candidate", origin="crawl")
    kb.add_asset("baci", "https://cdn.example/logo.png", rights=kb.OWNED,
                 title="Brand mark", subject=kb.LOGO, origin="human")
    got = creative.hero_for_campaign("baci", segment_key="reorder_due")
    ck("reference, proposed and logo rows are all unreachable",
       got["basis"] == "none" and got["image"] is None, got.get("basis"))
    ck("the absence is NAMED, with both ways out",
       "pictures queue" in got["why"] and "draft_visual" in got["why"],
       got.get("why", "")[:80])

    kb.add_asset("baci", "https://cdn.example/brandwide.jpg", rights=kb.OWNED,
                 title="Tablescape, evening", origin="human")
    kb.add_asset("baci", "https://cdn.example/aqua-hero.jpg", rights=kb.OWNED,
                 title="Aqua pitcher on linen", entity_key="aqua-pitcher",
                 origin="human")
    got = creative.hero_for_campaign("baci", segment_key="reorder_due",
                                     entity_keys=["aqua-pitcher"])
    ck("entity-scoped photograph beats brand-wide",
       got["basis"] == "approved_asset"
       and got["image"]["url"].endswith("aqua-hero.jpg"), str(got.get("image")))
    got = creative.hero_for_campaign("baci", segment_key="reorder_due")
    ck("with no entity in scope, brand-wide serves",
       got["basis"] == "approved_asset"
       and got["image"]["url"].endswith("brandwide.jpg"))

    print("\n— the miss path: a Canva draft for review, never pixels now —")
    got = creative.hero_for_campaign("eien", draft_if_missing=True)
    ck("no Canva connected is a named refusal",
       got["basis"] == "none" and "no Canva is" in got["why"], got.get("why", "")[:60])
    _fake_canva(connected={"eien"})
    got = creative.hero_for_campaign("eien", segment_key="week_one",
                                     draft_if_missing=True)
    ck("a right-sized draft is created",
       got["basis"] == "drafted_in_canva"
       and _designs and _designs[-1]["width"] == creative.HERO_W
       and _designs[-1]["height"] == creative.HERO_H, str(_designs[-1:]))
    ck("…and returns NO image — nothing unapproved can ship this run",
       got["image"] is None and "review queue" in got.get("note", ""))

    print("\n— the whole skill: photograph into the email, use filed —")
    skill_pack.draft_campaign = lambda bundle, seg, goal: (
        {"subject": "Back in stock", "preheader": "the aqua returns",
         "body_html": "<p>Hi {{FIRST_NAME}}, Designed in Milan and used in "
                      "leading hotels.</p>",
         "claim_ids": [], "cta_label": "Shop", "cta_url": "https://x/s"},
        "model", "")
    r = skill.run("campaign_email", "baci", segment="reorder_due")
    item = (r.get("items") or [{}])[0]
    html = item.get("meta", {}).get("html", "")
    ck("the run produced", r.get("status") == "produced", str(r.get("status")))
    ck("the approved photograph IS the hero in the rendered HTML",
       'src="https://cdn.example/brandwide.jpg"' in html)
    ck("the run names the hero's basis",
       r["detail"]["hero"]["basis"] == "approved_asset", str(r["detail"]["hero"]))
    ck("the email still drafted into the ESP", r["detail"]["esp_draft"].get("ok") is True)
    used = [a for a in kb.assets("baci", publishable_only=False)
            if a.url.endswith("brandwide.jpg")][0]
    ck("the use was filed on the asset (feedback signal one)",
       used.uses == "1" and used.last_used_at is not None, used.uses)

    print("\n— and with only unusable imagery, the email ships imageless —")
    _drafted.clear()
    r2 = skill.run("campaign_email", "eien", segment="week_one") \
        if systems.find("eien", "campaign_email") else None
    # eien has no live system in this suite — the governed miss is asserted at
    # the creative layer above; here we re-run baci with its usable rows gone.
    with db.SessionLocal() as s:
        for a in s.query(db.KbAsset).filter(db.KbAsset.tenant == "baci"):
            if a.url.endswith(("brandwide.jpg", "aqua-hero.jpg")):
                a.status = "retired"
        s.commit()
    r3 = skill.run("campaign_email", "baci", segment="reorder_due")
    item3 = (r3.get("items") or [{}])[0]
    html3 = item3.get("meta", {}).get("html", "")
    ck("no <img falls back into the hero slot", "cdn.example" not in html3)
    ck("the imageless state is named on the run",
       r3["detail"]["hero"]["basis"] == "none", str(r3["detail"]["hero"]))
    ck("and the email still went out to the ESP as a draft",
       r3["detail"]["esp_draft"].get("ok") is True)

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
