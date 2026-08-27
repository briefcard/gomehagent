"""The campaign generator skill: the DATA LAYER writes the copy, code gates it.

The owner's requirement is that copy comes from the data layer — on-brand voice,
approved claims as credibility, correct positioning — never the model
freelancing, and nothing reaches a client's ESP without the banned-claims gate.
Driven offline: the model seam (`draft_campaign`) and the ESP (`personalize`,
`backend`) are the module seams the suite replaces, so no live model or ESP is
touched. What is checked is the governed path: grounded copy is produced and
cites a real claim; a banned phrase is BLOCKED; with no model it degrades to the
composer; personalization is made native; and a valid, sendable email is drafted
into the ESP while nothing is ever sent.

Run: python3 scripts/test_campaign_email.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'ce.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import (config, db, esp, kb, skill,  # noqa: E402
                 skill_pack, systems, tenants)

_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


# All capabilities wired, so the system can go live (mirrors test_skill).
_ALL = {c: True for c in tenants.CAPABILITIES}
tenants.capabilities = lambda key: dict(_ALL) if tenants.get(key) else \
    {c: False for c in tenants.CAPABILITIES}


def _seed_live(tenant):
    kb.ensure_brand(tenant, tenant.title())
    kb.set_brand(tenant, positioning="Italian-designed tableware for the table.",
                 tone="direct, warm")
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


# A fake ESP: connected, personalizes by a visible marker, drafts a campaign.
_drafted = []


def _fake_esp():
    esp.provider_for = lambda t: "omnisend"
    esp.personalize = lambda t, html: {"ok": True,
                                        "html": html.replace("{{FIRST_NAME}}", "‹NAME›")}

    class _Mod:
        @staticmethod
        def draft_from_html(tenant, *, name, subject, sender_name, html,
                            preheader="", include_segments=None):
            _drafted.append({"tenant": tenant, "subject": subject,
                             "include": include_segments})
            return {"ok": True, "campaign_id": "camp_1", "stage": "done"}
    esp.backend = lambda t: (_Mod, "")


def main():
    db.init_db()
    tenants.seed()
    _seed_live("baci")           # business_model ecom_inventory, from the seed
    _fake_esp()
    # A real, owner-approved theme — the address that makes the email sendable
    # arrives the way it does in production (brand_theme.approve), so the
    # CAN-SPAM gate stays ON and the ESP draft path is reached honestly.
    from app import brand_theme
    ok = brand_theme.approve("baci", {"footer.address":
                                      "2875 NE 191st St, Aventura, FL 33180"})
    assert ok.get("ok") and ok["gaps"] == [], ok

    def _grounded_stub(banned_phrase=""):
        def _d(bundle, seg, goal, craft=None):
            claims = bundle.get("claims") or []
            cid = claims[0]["claim_id"] if claims else ""
            body = (f"<p>Hi {{{{FIRST_NAME}}}}, {banned_phrase or 'our tableware is Italian-designed'}. "
                    f"Restock before you run out.</p>")
            return ({"subject": "You're about to run out", "preheader": "restock in one tap",
                     "body_html": body, "claim_ids": [cid] if cid else [],
                     "cta_label": "Reorder", "cta_url": "https://x/reorder"}, "model", "")
        return _d

    print("— the copy is grounded in the data layer and produces a send-ready email —")
    skill_pack.draft_campaign = _grounded_stub()
    r = skill.run("campaign_email", "baci", segment="reorder_due")
    ck("the skill produced an email", r["status"] == "produced", str(r.get("status")))
    item = (r.get("items") or [{}])[0]
    ck("it cited the brand's approved claim (credibility from the KB)",
       bool(item.get("claim_ids")), str(item.get("claim_ids")))
    ck("the rendered HTML is on the item", bool(item.get("meta", {}).get("html")))
    ck("it targeted the segment", item.get("meta", {}).get("segment") == "reorder_due")

    print("\n— personalization is made native for the client's ESP —")
    ck("the {{FIRST_NAME}} token was rendered native",
       "‹NAME›" in item["meta"]["html"] and "{{FIRST_NAME}}" not in item["meta"]["html"])

    # RETARGETED (UI overhaul 3.3, owner 2026-08-27): review-before-push.
    # Emit HOLDS the campaign in our store for the workroom's review; the ESP
    # draft is created by `push_campaign_to_esp`, which the approval executor
    # calls. So the invariant flipped: draft_from_html must NOT fire at emit,
    # and MUST fire — with the same subject and binding — at push.
    print("\n— a valid, sendable email is HELD for review, never pre-drafted —")
    ck("draft_from_html was NOT called at emit — nothing reaches the ESP "
       "before approval", not _drafted, str(_drafted)[:80])
    ck("the run says it is held for the workroom",
       "held for your review" in (r.get("summary") or ""),
       (r.get("summary") or "")[:100])
    oid = item.get("output_id", "")
    got_push = skill_pack.push_campaign_to_esp("baci", oid)
    ck("…and the approval-time push creates the draft, same subject",
       got_push.get("ok") is True
       and any(d["subject"] == "You're about to run out" for d in _drafted),
       str(got_push)[:100])

    print("\n— the push is BOUND to the planned segment in the ESP —")
    ck("with nothing linked, the push is untargeted and the run SAID so",
       _drafted and _drafted[-1]["include"] is None
       and any("untargeted" in n for n in r.get("notes", [])),
       str((r.get("notes") or [])[-1:])[:90])
    from app import segments as segmod
    segmod._store_links("baci", {"reorder_due": {"id": "seg-lnk-1",
                                                 "name": "Reorder due"}})
    r_bind = skill.run("campaign_email", "baci", segment="reorder_due")
    oid_b = (r_bind.get("items") or [{}])[0].get("output_id", "")
    skill_pack.push_campaign_to_esp("baci", oid_b)
    ck("a remembered segment id rides the pushed draft as its audience",
       _drafted[-1]["include"] == ["seg-lnk-1"],
       str(_drafted[-1].get("include")))
    ck("…and the run reports the target",
       (r_bind.get("detail") or {}).get("esp_target", {}).get("id") == "seg-lnk-1")

    print("\n— email craft is enforced by code, not hoped from the prompt —")
    _drafted.clear()
    skill_pack.draft_campaign = lambda bundle, seg, goal, craft=None: (
        {"subject": "This is a very long subject line that would be cut off "
                    "by every mobile inbox long before the point lands",
         "preheader": "p", "claim_ids": [],
         "body_html": "<p>One.</p><p>Two.</p><p>Three.</p><p>Four.</p>",
         "cta_label": "Shop", "cta_url": "https://x/s"}, "model", "")
    r_craft = skill.run("campaign_email", "baci", segment="reorder_due")
    item_c = (r_craft.get("items") or [{}])[0]
    ck("a rambling subject is trimmed at a word boundary",
       len(item_c.get("meta", {}).get("subject", "")) <= 46
       and any("subject trimmed" in n for n in r_craft.get("notes", [])),
       item_c.get("meta", {}).get("subject", ""))
    ck("a wall of paragraphs is broken into sections with a divider",
       item_c.get("meta", {}).get("html", "").count("height:1px") >= 1)

    skill_pack.draft_campaign = lambda bundle, seg, goal, craft=None: (
        {"subject": "Short and specific", "preheader": "p",
         "headline": "The one-line hook", "claim_ids": [],
         "sections": [
             {"heading": "Why now", "body_html": "<p>Because.</p>"},
             {"heading": "What you get", "body_html": "<p>This.</p>"}],
         "cta_label": "Shop", "cta_url": "https://x/s"}, "model", "")
    r_sec = skill.run("campaign_email", "baci", segment="reorder_due")
    html_s = (r_sec.get("items") or [{}])[0].get("meta", {}).get("html", "")
    ck("the drafter's sections render native: headline + headed sections",
       "The one-line hook" in html_s and "Why now" in html_s
       and "What you get" in html_s)

    print("\n— products: the catalogue is IN the email, photo and all —")
    with db.SessionLocal() as s:
        s.add(db.KbEntity(tenant="baci", key="aqua-pitcher-x",
                          type="product", name="Aqua Pitcher",
                          price="$95", availability="available",
                          origin="store_sync", review="approved",
                          source="shopify",
                          attributes={"image": "https://cdn.x/aqua.jpg"}))
        s.commit()
    r_prod = skill.run("campaign_email", "baci", segment="reorder_due")
    html_p = (r_prod.get("items") or [{}])[0].get("meta", {}).get("html", "")
    ck("the product card carries name, price and the store's own photo",
       "Aqua Pitcher" in html_p and "https://cdn.x/aqua.jpg" in html_p
       and "$95" in html_p)
    ck("…and the run says the catalogue chose it, since no entity was set",
       any("top available items" in n for n in r_prod.get("notes", [])))
    ck("omnisend's header carries NO view-in-browser — it has no variable "
       "for one", "View in browser" not in html_p)

    print("\n— a subject set on the PLAN outranks the drafter's —")
    _drafted.clear()
    r_subj = skill.run("campaign_email", "baci", segment="reorder_due",
                       subject="The owner's own line")
    item_s = (r_subj.get("items") or [{}])[0]
    # RETARGETED (UI overhaul 3.3): the ESP sees nothing at emit — the
    # plan's subject must ride the held artifact's push recipe and reach the
    # platform when the approval-time push fires.
    skill_pack.push_campaign_to_esp("baci", item_s.get("output_id", ""))
    ck("the plan's subject is what ships",
       item_s.get("meta", {}).get("subject") == "The owner's own line"
       and any(d["subject"] == "The owner's own line" for d in _drafted),
       str(item_s.get("meta", {}).get("subject")))
    ck("…and the run says where the line came from",
       any("subject line came from the plan" in n for n in r_subj.get("notes", [])))

    print("\n— a banned phrase is BLOCKED before anything is drafted —")
    _drafted.clear()
    skill_pack.draft_campaign = _grounded_stub(banned_phrase="these are made in Italy")
    r2 = skill.run("campaign_email", "baci", segment="reorder_due")
    item2 = (r2.get("items") or [{}])[0]
    ck("the banned-claim email did not pass the validator",
       not item2.get("ok"), str(item2.get("failures"))[:80])
    ck("and nothing was drafted into the ESP", not _drafted)

    print("\n— with no model, it degrades to the grounded composer, not silence —")
    skill_pack.draft_campaign = skill_pack._draft_campaign_live
    _key = config.ANTHROPIC_API_KEY
    config.ANTHROPIC_API_KEY = ""
    r3 = skill.run("campaign_email", "baci", segment="reorder_due")
    config.ANTHROPIC_API_KEY = _key
    item3 = (r3.get("items") or [{}])[0]
    ck("it still produced, marked basis=composed",
       r3["status"] == "produced" and item3.get("meta", {}).get("basis") == "composed",
       str(item3.get("meta", {}).get("basis")))

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
