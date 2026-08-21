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

from app import (config, db, email_render, esp, kb, skill,  # noqa: E402
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
        def draft_from_html(tenant, *, name, subject, sender_name, html, preheader=""):
            _drafted.append({"tenant": tenant, "subject": subject})
            return {"ok": True, "campaign_id": "camp_1", "stage": "done"}
    esp.backend = lambda t: (_Mod, "")


def main():
    db.init_db()
    tenants.seed()
    _seed_live("baci")           # business_model ecom_inventory, from the seed
    _fake_esp()
    # A complete-enough theme so the CAN-SPAM address gap doesn't mask the ESP
    # draft path (the real address comes from the brand-theme deriver).
    email_render.missing_to_send = lambda theme: []

    def _grounded_stub(banned_phrase=""):
        def _d(bundle, seg, goal):
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

    print("\n— a valid, sendable email is DRAFTED into the ESP (never sent) —")
    ck("draft_from_html was called on the client's ESP",
       any(d["subject"] == "You're about to run out" for d in _drafted))
    ck("the run reports the ESP draft", r["detail"]["esp_draft"].get("ok") is True)

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
