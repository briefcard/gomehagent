"""Variety and craft: two campaigns must be two different emails.

The owner's read of the first live sends (2026-08-21) was "this is all
templates … we want variety and true generation of content and different
sections". It was accurate: the macro-structure was compiled into the code, so
the model could only ever change words. This suite pins the four things that
make the difference structural rather than hoped-for.

  1. THE DRAFTER COMPOSES THE LAYOUT, and code holds every old line — an
     uncited stat is dropped, an unoffered product is dropped, a second CTA is
     dropped, the hero comes only from the approved library.
  2. FORMAT FOLLOWS THE AUDIENCE — a warm cohort gets a personal letter (no
     hero, no product grid, a sign-off and a P.S.); a cold one gets the
     designed frame. Blocks the format does not carry are dropped BY NAME.
  3. INTENT ROTATES — a list is given to about three times for every time it
     is asked, and the shapes and openings of recent sends are fed back so the
     next one differs.
  4. CRAFT IS CHECKED IN CODE — subject length, repeated preview text,
     platitudes, missing proof are advice; urgency with nothing behind it is a
     BLOCK, because a deadline that does not exist is a false statement made
     in the client's name.

Plus the two live defects this change fixed: a repair now re-renders (the ESP
used to receive the HTML of the REJECTED draft), and the subject is re-checked
after a repair (a banned phrase in a subject line used to survive one).

Run: python3 scripts/test_campaign_variety.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'cv.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import (approvals, brand_theme, db, email_craft, esp,  # noqa: E402
                 kb, skill, skill_pack, systems, tenants)

_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


_ALL = {c: True for c in tenants.CAPABILITIES}
tenants.capabilities = lambda key: dict(_ALL) if tenants.get(key) else \
    {c: False for c in tenants.CAPABILITIES}

_drafted = []


def _fake_esp():
    esp.provider_for = lambda t: "omnisend"
    esp.personalize = lambda t, html: {"ok": True,
                                       "html": html.replace("{{FIRST_NAME}}", "‹NAME›")}

    class _Mod:
        @staticmethod
        def draft_from_html(tenant, *, name, subject, sender_name, html,
                            preheader="", include_segments=None):
            _drafted.append({"subject": subject, "html": html, "name": name})
            return {"ok": True, "campaign_id": "c1", "stage": "done"}
    esp.backend = lambda t: (_Mod, "")


def _seed(tenant="baci"):
    kb.ensure_brand(tenant, tenant.title())
    kb.set_brand(tenant, positioning="Italian-designed tableware.", tone="warm")
    kb.add_banned(tenant, "made in Italy")
    kb.add_situation(tenant, "quality", patterns=[["quality"]],
                     description="Is it any good?", origin="seed")
    kb.add_claim(tenant, "Placed in Four Seasons and Ritz dining rooms.",
                 "brand brief", ["quality"], origin="human", status="active")
    row = systems.find(tenant, "campaign_email") or systems.create(tenant, "campaign_email")
    with db.SessionLocal() as s:
        s.get(db.System, row.id).status = "live"
        s.commit()
    brand_theme.approve(tenant, {"footer.address": "2875 NE 191st St, Aventura FL"})


def _claim_id(tenant="baci"):
    """The id the BUNDLE will offer — `KbClaim.id`, which is what
    `resolve` surfaces as `claim_id`."""
    rows = kb.claims(tenant)
    c = rows[0] if rows else None
    return (c["claim_id"] if isinstance(c, dict) else getattr(c, "id", "")) if c else ""


def _blocks_drafter(blocks, subject="A specific enough line", preheader="a different second line",
                    claim_ids=()):
    def _d(bundle, seg, goal, craft=None):
        return ({"subject": subject, "preheader": preheader, "blocks": list(blocks),
                 "claim_ids": list(claim_ids), "cta_label": "Shop",
                 "cta_url": "https://x/s"}, "model", "")
    return _d


def _shape(res):
    return ((res.get("items") or [{}])[0].get("meta") or {}).get("shape") or []


def _meta(res, k):
    return ((res.get("items") or [{}])[0].get("meta") or {}).get(k)


def main():
    db.init_db()
    tenants.seed()
    _seed("baci")
    _fake_esp()
    cid = _claim_id("baci")

    print("\n— the DRAFTER composes the layout; code holds every line —")
    skill_pack.draft_campaign = _blocks_drafter([
        {"type": "banner", "text": "The Portofino table"},
        {"type": "heading", "text": "It started with a boat", "level": 1},
        {"type": "text", "html": "<p>Hi {{FIRST_NAME}}, a short note.</p>"},
        {"type": "quote", "text": "Placed in leading hotels.", "claim_id": cid},
        {"type": "list", "items": ["Melamine, not china", "Dishwasher safe"]},
        {"type": "cta", "label": "See it", "url": "https://x/p"},
        {"type": "ps", "html": "It ships in two days."},
    ], claim_ids=[cid])
    r = skill.run("campaign_email", "baci", segment="new_subscribers",
                  goal="introduce the line")
    shape = _shape(r)
    html = (_meta(r, "html") or "")
    ck("the composed layout is what shipped, in the drafter's own order",
       shape[:3] == ["banner", "heading", "text"], str(shape))
    ck("blocks the OLD renderer never had are rendered",
       "The Portofino table" in html and "Melamine, not china" in html)
    ck("the P.S. renders as a postscript, not as another paragraph",
       "P.S." in html and "It ships in two days" in html)
    ck("the quote carried an offered claim, so it survived",
       "quote" in shape, str(shape))

    print("\n— a stat or quote with no offered claim is an invented number —")
    skill_pack.draft_campaign = _blocks_drafter([
        {"type": "text", "html": "<p>Hello.</p>"},
        {"type": "stat", "value": "93%", "caption": "of buyers reorder"},
        {"type": "cta", "label": "Shop", "url": "https://x/s"}])
    r = skill.run("campaign_email", "baci", segment="new_subscribers", goal="sell")
    ck("the uncited stat was dropped", "stat" not in _shape(r), str(_shape(r)))
    ck("…and the run SAYS why, by name",
       any("uncited" in n and "invented" in n for n in r.get("notes", [])))

    print("\n— citing a real claim is NOT enough: proof must be used as its "
          "kind allows —")
    kb.add_claim("baci", "The colours are better in person than online.",
                 "review #8812", ["quality"], proof_type="testimonial",
                 attributed_to="Dana R., verified buyer",
                 origin="human", status="active")
    kb.add_claim("baci", "It arrived faster than I expected.", "review #9001",
                 ["quality"], proof_type="testimonial",
                 origin="human", status="active")     # nobody on file to credit
    tid = ""
    for c in kb.claims("baci"):
        if "colours are better" in (c.claim or ""):
            tid = c.id
    ck("a testimonial is on file to test with", bool(tid))

    # The id is real, the attribution is there — and the WORDS were changed.
    skill_pack.draft_campaign = _blocks_drafter([
        {"type": "text", "html": "<p>Hello.</p>"},
        {"type": "quote", "text": "Our colours look incredible in real life.",
         "claim_id": tid, "attribution": "A customer"},
        {"type": "cta", "label": "Shop", "url": "https://x/s"}])
    r = skill.run("campaign_email", "baci", segment="new_subscribers", goal="sell")
    ck("a REWORDED testimonial is dropped — words are never put in a real "
       "person's mouth", "quote" not in _shape(r), str(_shape(r)))
    ck("…and the refusal names the rule it broke",
       any("verbatim" in n for n in r.get("notes", [])))

    skill_pack.draft_campaign = _blocks_drafter([
        {"type": "text", "html": "<p>Hello.</p>"},
        {"type": "quote", "text": "The colours are better in person than online.",
         "claim_id": tid, "attribution": "Verified buyer"},
        {"type": "cta", "label": "Shop", "url": "https://x/s"}])
    r = skill.run("campaign_email", "baci", segment="new_subscribers", goal="sell")
    ck("the SAME testimonial quoted verbatim stands", "quote" in _shape(r),
       str(_shape(r)))

    uncredited = ""
    for c in kb.claims("baci"):
        if "arrived faster" in (c.claim or ""):
            uncredited = c.id
    skill_pack.draft_campaign = _blocks_drafter([
        {"type": "text", "html": "<p>Hello.</p>"},
        {"type": "quote", "text": "It arrived faster than I expected.",
         "claim_id": uncredited, "attribution": "A happy customer"},
        {"type": "cta", "label": "Shop", "url": "https://x/s"}])
    r = skill.run("campaign_email", "baci", segment="new_subscribers", goal="sell")
    ck("a testimonial with NOBODY on file to credit is dropped — the drafter "
       "does not get to name the customer", "quote" not in _shape(r),
       str(_shape(r)))
    ck("…and the refusal says to set who said it",
       any("nobody is on file to credit" in n for n in r.get("notes", [])))

    print("\n— WHO SAID IT is copied from the record, never written —")
    # `source` is internal provenance and must NEVER reach a reader;
    # `attributed_to` is the human-owned credit line and is the only thing a
    # quote may be attributed with.
    kb.add_claim("baci", "As we age, natural GLP-1 activity can decline.",
                 "internal review", ["quality"], proof_type="data",
                 source="captured", attributed_to="Nature Metabolism, 2021",
                 origin="human", status="active")
    kb.add_claim("baci", "This one has no source recorded.", "x", ["quality"],
                 proof_type="data", source="stated on https://internal",
                 origin="human", status="active")
    sourced = unsourced = ""
    for c in kb.claims("baci"):
        if "GLP-1" in (c.claim or ""):
            sourced = c.id
        if "no source recorded" in (c.claim or ""):
            unsourced = c.id

    skill_pack.draft_campaign = _blocks_drafter([
        {"type": "text", "html": "<p>Hello.</p>"},
        {"type": "quote", "text": "As we age, natural GLP-1 activity can decline.",
         "claim_id": sourced, "attribution": "Eien Health Research"},
        {"type": "cta", "label": "Go", "url": "https://x/g"}])
    r = skill.run("campaign_email", "baci", segment="new_subscribers", goal="x")
    html = _meta(r, "html") or ""
    ck("an institution the drafter INVENTED never reaches the reader",
       "Eien Health Research" not in html)
    ck("…the claim's own recorded source is what renders",
       "Nature Metabolism, 2021" in html)

    skill_pack.draft_campaign = _blocks_drafter([
        {"type": "text", "html": "<p>Hello.</p>"},
        {"type": "quote", "text": "This one has no source recorded.",
         "claim_id": unsourced, "attribution": "Harvard Study"},
        {"type": "cta", "label": "Go", "url": "https://x/g"}])
    r = skill.run("campaign_email", "baci", segment="new_subscribers", goal="x")
    html = _meta(r, "html") or ""
    ck("with nobody on file the quote renders UNATTRIBUTED, not credited "
       "to whatever sounded right",
       "quote" in _shape(r) and "Harvard" not in html, str(_shape(r)))
    ck("…and internal provenance never leaks to the reader either",
       "stated on https://internal" not in html and "captured" not in html)

    print("\n— a figure the claim does not contain is invented, citation or not —")
    dc = kb.add_claim("baci", "Ships flat in two days.", "carrier data: 2 days",
                      ["quality"], proof_type="data", origin="human", status="active")
    did = ""
    for c in kb.claims("baci"):
        if (c.claim or "").startswith("Ships flat"):
            did = c.id
    skill_pack.draft_campaign = _blocks_drafter([
        {"type": "text", "html": "<p>Hello.</p>"},
        {"type": "stat", "value": "93%", "caption": "reorder", "claim_id": did},
        {"type": "cta", "label": "Shop", "url": "https://x/s"}])
    r = skill.run("campaign_email", "baci", segment="new_subscribers", goal="sell")
    ck("a stat whose number is absent from its claim is dropped",
       "stat" not in _shape(r), str(_shape(r)))
    ck("…and the refusal says the figure is not in the claim",
       any("not in the" in n and "claim" in n for n in r.get("notes", [])))

    skill_pack.draft_campaign = _blocks_drafter([
        {"type": "text", "html": "<p>Hello.</p>"},
        {"type": "stat", "value": "2 days", "caption": "to your door", "claim_id": did},
        {"type": "cta", "label": "Shop", "url": "https://x/s"}])
    # A `stat` belongs to the designed frame, so ask a cold, unused segment.
    r = skill.run("campaign_email", "baci", segment="unengaged_sunset", goal="sell")
    ck("the figure the claim DOES contain stands", "stat" in _shape(r), str(_shape(r)))

    print("\n— the proof rule reaches the drafter, not just the reviewer —")
    seen_prompt = {}

    def _capture_prompt(bundle, seg, goal, craft=None):
        seen_prompt["claims"] = bundle.get("claims") or []
        return _blocks_drafter([{"type": "text", "html": "<p>x</p>"},
                                {"type": "cta", "label": "Go", "url": "#"}])(
            bundle, seg, goal, craft)
    skill_pack.draft_campaign = _capture_prompt
    skill.run("campaign_email", "baci", segment="new_subscribers", goal="x")
    ck("the bundle carries each claim's proof_type",
       any(c.get("proof_type") for c in seen_prompt.get("claims", [])))
    ck("…and the usage rule that proof_type implies",
       any("verbatim" in (c.get("usage_rule") or "").lower()
           for c in seen_prompt.get("claims", [])))

    print("\n— one ask per email —")
    skill_pack.draft_campaign = _blocks_drafter([
        {"type": "text", "html": "<p>Hello.</p>"},
        {"type": "cta", "label": "Buy", "url": "https://x/a"},
        {"type": "cta", "label": "Or this", "url": "https://x/b"}])
    r = skill.run("campaign_email", "baci", segment="new_subscribers", goal="sell")
    ck("the second CTA was dropped", _shape(r).count("cta") == 1, str(_shape(r)))

    print("\n— FORMAT follows the audience, not taste —")
    letter_blocks = [
        {"type": "banner", "text": "SALE"},
        {"type": "heading", "text": "A note about the glasses", "level": 1},
        {"type": "text", "html": "<p>Hi {{FIRST_NAME}}.</p>"},
        {"type": "products", "keys": []},
        {"type": "signature", "text": "Talk soon,", "name": "Gomeh"},
        {"type": "cta", "label": "Have a look", "url": "https://x/g"},
        {"type": "ps", "html": "One more thing."},
    ]
    skill_pack.draft_campaign = _blocks_drafter(letter_blocks)
    # Segments with NO history, so warmth alone decides — format now cycles
    # once a list has seen two of the same form, which is tested below.
    warm = skill.run("campaign_email", "baci", segment="vip_high_aov",
                     goal="cross-sell")
    cold = skill.run("campaign_email", "baci", segment="engaged_non_buyers",
                     goal="introduce")
    ck("a WARM cohort gets the personal letter", _meta(warm, "format") == "letter",
       str(_meta(warm, "format")))
    ck("a COLD cohort gets the designed frame", _meta(cold, "format") == "designed",
       str(_meta(cold, "format")))
    ck("the letter drops the banner it cannot carry",
       "banner" not in _shape(warm) and "banner" in _shape(cold),
       f"warm={_shape(warm)} cold={_shape(cold)}")
    ck("…and says so by name",
       any("personal letter and does not carry one" in n for n in warm.get("notes", [])))
    # The sign-off needs a real person on file and none is yet — that whole
    # rule is exercised below. What the letter keeps here is its postscript.
    ck("the letter keeps its P.S.", "ps" in _shape(warm), str(_shape(warm)))
    ck("the same drafter output produced two DIFFERENT emails",
       _shape(warm) != _shape(cold))

    print("\n— a sign-off nobody is on file to make is dropped, never invented —")
    skill_pack.draft_campaign = _blocks_drafter([
        {"type": "text", "html": "<p>Hello.</p>"},
        {"type": "signature", "text": "Best,", "name": ""},
        {"type": "cta", "label": "Go", "url": "https://x/g"}])
    r = skill.run("campaign_email", "baci", segment="repeat_buyers", goal="x")
    ck("the nameless signature was dropped", "signature" not in _shape(r), str(_shape(r)))
    ck("…and the refusal names the reason",
       any("inventing a person is not an option" in n for n in r.get("notes", [])))

    print("\n— INTENT rotates so a list is given to more than it is asked —")
    ck("intent is recorded on what shipped", _meta(cold, "intent") in
       skill_pack.CAMPAIGN_INTENTS, str(_meta(cold, "intent")))
    ck("an intent set on the plan outranks the rotation",
       _meta(skill.run("campaign_email", "baci", segment="new_subscribers",
                       goal="x", intent="education"), "intent") == "education")
    r = skill.run("campaign_email", "baci", segment="new_subscribers", goal="x",
                  intent="nonsense")
    ck("an unknown intent is refused BY NAME, not silently ignored",
       any("unknown intent" in n for n in r.get("notes", [])))

    print("\n— the last sends are fed back, so the next one differs —")
    seen = {}

    def _capture(bundle, seg, goal, craft=None):
        seen.update(craft or {})
        return _blocks_drafter([{"type": "text", "html": "<p>x</p>"},
                                {"type": "cta", "label": "Go", "url": "#"}])(
            bundle, seg, goal, craft)
    skill_pack.draft_campaign = _capture
    skill.run("campaign_email", "baci", segment="new_subscribers", goal="x")
    ck("the drafter is shown the shapes already used on this list",
       bool(seen.get("avoid")) and any(a.get("shape") for a in seen["avoid"]),
       str([a.get("shape") for a in (seen.get("avoid") or [])][:2]))
    ck("…and the brief actually tells it not to repeat them",
       "DO NOT REPEAT" in skill_pack._craft_brief(seen))

    print("\n— CRAFT is checked in code, not hoped from the prompt —")
    f = email_craft.review(
        subject="Premium quality tableware that will truly elevate your space "
                "this coming season",
        preheader="Premium quality tableware that will truly elevate",
        body="Our unmatched craftsmanship is second to none.",
        intent="offer", asks=True, has_proof=False)
    rules = {x["rule"] for x in f}
    ck("a long subject is flagged", "subject_length" in rules, str(sorted(rules)))
    ck("preview text that repeats the subject is flagged", "preheader_repeats" in rules)
    ck("platitudes are flagged with the actual words",
       "platitude" in rules and any("premium quality" in x["detail"] for x in f))
    ck("an ask with no proof is flagged", "no_proof" in rules)
    ck("all of those are ADVICE, never a block",
       email_craft.block_reasons(f) == [])

    print("\n— urgency with nothing behind it is a BLOCK —")
    urgent = [{"type": "text", "html": "<p>Last chance, this ends tonight. Hurry.</p>"},
              {"type": "cta", "label": "Buy", "url": "https://x/b"}]
    before = len(_drafted)
    skill_pack.draft_campaign = _blocks_drafter(urgent, subject="Ends tonight")
    r = skill.run("campaign_email", "baci", segment="new_subscribers", goal="sell",
                  intent="offer")
    ck("the copy passed the banned-claims validator",
       (r.get("items") or [{}])[0].get("ok") is True)
    ck("…but nothing was drafted into the ESP", len(_drafted) == before)
    ck("…and the run names the fabricated urgency",
       any("urgency with nothing behind it" in n for n in r.get("notes", [])))

    before = len(_drafted)
    r = skill.run("campaign_email", "baci", segment="new_subscribers", goal="sell",
                  intent="offer", deadline="the sale really ends Sunday 23:59 ET")
    ck("the SAME copy ships once a real deadline is on the plan",
       len(_drafted) == before + 1)

    print("\n— a repair re-renders: the ESP gets the REPAIRED email —")
    calls = {"n": 0}

    def _first_banned(bundle, seg, goal, craft=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return ({"subject": "A clean subject line",
                     "preheader": "second line", "blocks": [
                         {"type": "text", "html": "<p>Our tableware is made in Italy.</p>"},
                         {"type": "cta", "label": "Shop", "url": "https://x/s"}],
                     "claim_ids": [], "cta_label": "Shop", "cta_url": "https://x/s"},
                    "model", "")
        return ({"subject": "A clean subject line", "preheader": "second line",
                 "blocks": [{"type": "text", "html": "<p>Designed in Milan.</p>"},
                            {"type": "cta", "label": "Shop", "url": "https://x/s"}],
                 "claim_ids": [], "cta_label": "Shop", "cta_url": "https://x/s"},
                "model", "")
    skill_pack.draft_campaign = _first_banned
    before = len(_drafted)
    r = skill.run("campaign_email", "baci", segment="new_subscribers", goal="sell")
    it = (r.get("items") or [{}])[0]
    ck("the repair cleared the banned phrase", it.get("ok") is True and it.get("repairs") == 1,
       f"ok={it.get('ok')} repairs={it.get('repairs')}")
    ck("the HTML filed on the item is the REPAIRED one",
       "made in Italy" not in (it.get("meta", {}).get("html") or "")
       and "Designed in Milan" in (it.get("meta", {}).get("html") or ""))
    ck("the ESP received the REPAIRED html, not the rejected render",
       len(_drafted) == before + 1
       and "made in Italy" not in _drafted[-1]["html"]
       and "Designed in Milan" in _drafted[-1]["html"])

    print("\n— a banned phrase in the SUBJECT cannot be repaired away —")
    calls2 = {"n": 0}

    def _banned_subject(bundle, seg, goal, craft=None):
        # The body changes on the retry; the SUBJECT stays banned. Before the
        # re-check covered the subject, rewriting the body was enough to pass.
        calls2["n"] += 1
        return ({"subject": "Our plates are made in Italy",
                 "preheader": "second line",
                 "blocks": [{"type": "text",
                             "html": f"<p>Rewrite number {calls2['n']}.</p>"},
                            {"type": "cta", "label": "Shop", "url": "https://x/s"}],
                 "claim_ids": [], "cta_label": "Shop", "cta_url": "https://x/s"},
                "model", "")
    skill_pack.draft_campaign = _banned_subject
    before = len(_drafted)
    r = skill.run("campaign_email", "baci", segment="new_subscribers", goal="sell")
    it = (r.get("items") or [{}])[0]
    ck("the email stayed blocked", it.get("ok") is False, str(it.get("ok")))
    ck("…and nothing reached the ESP", len(_drafted) == before)

    print("\n— a thing you cannot buy is never promoted (the CitroBurn case) —")
    from app import catalog_sync, fitness
    untracked = [{"inventory_management": None}]
    ck("a DRAFT product is not 'available', whatever its stock says",
       catalog_sync._available({"status": "draft", "variants": untracked}) == "draft")
    ck("an archived product is named as archived",
       catalog_sync._available({"status": "archived", "variants": untracked})
       == "archived")
    ck("an active but unpublished product is named as unpublished",
       catalog_sync._available({"status": "active", "published_at": None,
                                "variants": untracked}) == "unpublished")
    ck("an active, published, untracked product IS available",
       catalog_sync._available({"status": "active", "published_at": "2026-01-01",
                                "variants": untracked}) == "available")
    ck("a payload with no published_at key is not read as unpublished",
       catalog_sync._available({"status": "active", "variants": untracked})
       == "available")
    ck("availability that was never recorded is NOT permission",
       "never recorded" in fitness.unfit("ecom_inventory",
                                         {"name": "X", "availability": ""}))

    with db.SessionLocal() as s:
        s.add(db.KbEntity(tenant="baci", key="citroburn", name="CitroBurn",
                          type="product", price="49", availability="draft",
                          status="active", review="approved", attributes={}))
        s.commit()

    before = len(_drafted)
    skill_pack.draft_campaign = _blocks_drafter([
        {"type": "text", "html": "<p>CitroBurn came out of that process.</p>"},
        {"type": "cta", "label": "Learn about CitroBurn", "url": "https://x/c"}])
    r = skill.run("campaign_email", "baci", segment="new_subscribers", goal="x")
    ck("a draft product NAMED IN PROSE — no card, no key — is caught",
       any("CitroBurn" in n and "draft in the store" in n
           for n in r.get("notes", [])))
    ck("…and nothing reached the ESP", len(_drafted) == before)
    ck("the banned-claims validator had passed it, so this is a NEW gate",
       (r.get("items") or [{}])[0].get("ok") is True)

    print("\n— a sign-off names a real person or nobody —")
    sig = [{"type": "text", "html": "<p>Hello.</p>"},
           {"type": "signature", "text": "Thank you,", "name": "Maya Chen",
            "role": "Head of Product"},
           {"type": "cta", "label": "Go", "url": "https://x/g"}]
    skill_pack.draft_campaign = _blocks_drafter(sig)
    r = skill.run("campaign_email", "baci", segment="reorder_due", goal="x")
    ck("a person the drafter INVENTED never signs the email",
       "signature" not in _shape(r)
       and "Maya Chen" not in (_meta(r, "html") or ""), str(_shape(r)))
    ck("…and the run says where a real name would come from",
       any("Brand tab" in n for n in r.get("notes", [])))

    brand_theme.approve("baci", {"sender.name": "Gomeh Saias",
                                 "sender.role": "Founder"})
    r = skill.run("campaign_email", "baci", segment="reorder_due", goal="x")
    ck("with a real signatory on file the letter is signed — by THEM",
       "signature" in _shape(r)
       and "Gomeh Saias" in (_meta(r, "html") or "")
       and "Maya Chen" not in (_meta(r, "html") or ""), str(_shape(r)))

    print("\n— a button with no destination is FILLED where one exists, and "
          "blocks only where none does —")
    with db.SessionLocal() as s:
        t = s.query(db.Tenant).filter(db.Tenant.key == "baci").first()
        was_domain, t.domain = t.domain, "example-store.com"
        s.commit()
    # A drafter that supplies NO url anywhere — which is the real case: the
    # model is never given the store's URLs, so it cannot write them.
    _urlless = lambda b, sg, g, craft=None: (
        {"subject": "A specific enough line", "preheader": "a second line",
         "blocks": [{"type": "text", "html": "<p>Hello.</p>"},
                    {"type": "cta", "label": "Learn more", "url": "#"}],
         "claim_ids": [], "cta_label": "Learn more", "cta_url": ""}, "model", "")
    before = len(_drafted)
    skill_pack.draft_campaign = _urlless
    r = skill.run("campaign_email", "baci", segment="new_subscribers", goal="x")
    ck("a placeholder '#' does not outrank the real storefront",
       len(_drafted) == before + 1
       and "example-store.com" in (_meta(r, "html") or ""))

    # Nothing to point at anywhere: no domain, and no entity with a URL.
    with db.SessionLocal() as s:
        t = s.query(db.Tenant).filter(db.Tenant.key == "baci").first()
        t.domain = ""
        s.commit()
    before = len(_drafted)
    skill_pack.draft_campaign = _urlless
    r = skill.run("campaign_email", "baci", segment="new_subscribers", goal="x")
    # CHANGED 2026-08-22. A dead button is BROKEN, not false — and withholding
    # the draft over it left the owner with nothing to look at, which is how a
    # send "that was working before" became invisible. The draft now goes to
    # the ESP carrying the problem in its INTERNAL name; what it does not get
    # is an approval. Withholding is reserved for `WITHHOLD_FROM_ESP` — the
    # things that would be false or forbidden if a human did click send.
    ck("the draft still reaches the ESP, because a draft cannot send itself",
       len(_drafted) == before + 1, str(len(_drafted) - before))
    ck("…marked [NEEDS FIX] in the name the ESP shows the OWNER",
       "[NEEDS FIX" in (_drafted[-1].get("name") or "") if _drafted else False,
       (_drafted[-1].get("name") or "")[:70] if _drafted else "")
    ck("…while the SUBJECT stays what a customer would receive",
       not (_drafted[-1].get("subject") or "").startswith("[") if _drafted else False,
       (_drafted[-1].get("subject") or "")[:50] if _drafted else "")
    ck("…and the run says which control is dead",
       any("points nowhere" in n for n in r.get("notes", [])))
    ck("…and it is recorded, so a repeat is visible as an account gap",
       any(k == "dead_link" for k, _ in systems.blocked_reasons("baci")),
       str(systems.blocked_reasons("baci")[:3]))
    with db.SessionLocal() as s:
        t = s.query(db.Tenant).filter(db.Tenant.key == "baci").first()
        t.domain = was_domain or ""
        s.commit()

    print("\n— a letter may SHOW the thing it is selling —")
    import re as _re
    with db.SessionLocal() as s:
        s.add(db.KbEntity(tenant="baci", key="glp1", name="GLP-1 Support",
                          type="product", price="59", availability="available",
                          status="active", review="approved",
                          attributes={"image": "https://cdn.shopify.com/s/f/p/g.jpg?v=1"}))
        s.add(db.KbEntity(tenant="baci", key="second", name="Second Thing",
                          type="product", price="19", availability="available",
                          status="active", review="approved",
                          attributes={"image": "https://cdn.shopify.com/s/f/p/s.jpg?v=1"}))
        s.commit()
    skill_pack.draft_campaign = _blocks_drafter([
        {"type": "text", "html": "<p>Hi {{FIRST_NAME}}.</p>"},
        {"type": "products", "keys": ["glp1", "second"]},
        {"type": "list", "items": ["Supports natural GLP-1 productionction"]},
        {"type": "cta", "label": "See it", "url": "https://x/g"},
        {"type": "ps", "html": "<p>P.S. The science is fascinating.</p>"}])
    r = skill.run("campaign_email", "baci", segment="win_back", goal="launch")
    html = _meta(r, "html") or ""
    imgs = _re.findall(r'<img[^>]+src="([^"]+)"', html)
    ck("a warm-segment letter is still a letter", _meta(r, "format") == "letter")
    ck("…and it now carries the product's photograph",
       any("/p/g" in u for u in imgs), str(imgs))
    ck("…sized for the slot, not the full-resolution original",
       any("_176x" in u for u in imgs), str(imgs))
    ck("a letter shows ONE product, never a grid",
       html.count("Second Thing") == 0, str(imgs))

    print("\n— the label the renderer owns is not written twice —")
    ck("the drafter's own 'P.S.' prefix is stripped, tags or no tags",
       html.count("P.S.") == 1, str(html.count("P.S.")))
    # The stutter is now REMOVED before anyone reads it, rather than reported
    # for a redraft — one rule covers all four live variants, so the craft
    # nudge fires only on whatever it cannot repair.
    ck("a garbled word never reaches the reader",
       "productionction" not in html and "production" in html, html[:0] or "")

    print("\n— an email with no picture in it SAYS so —")
    # The state this reports on is a catalogue with NO photographs anywhere,
    # which is what an account that has never run the sync looks like.
    with db.SessionLocal() as s:
        kept = {}
        for e in s.query(db.KbEntity).filter(db.KbEntity.tenant == "baci").all():
            kept[e.key] = dict(e.attributes or {})
            e.attributes = {k: v for k, v in (e.attributes or {}).items()
                            if k != "image"}
        s.commit()
    skill_pack.draft_campaign = _blocks_drafter([
        {"type": "text", "html": "<p>Words only.</p>"},
        {"type": "cta", "label": "Go", "url": "https://x/g"}])
    r = skill.run("campaign_email", "baci", segment="new_subscribers", goal="x")
    ck("the run names an imageless send instead of leaving it to be noticed",
       any("NO image" in n for n in r.get("notes", [])))
    ck("…and COUNTS the photos on file, so the cause is not a guess",
       any("product(s) have a photograph on file" in n
           for n in r.get("notes", [])))
    with db.SessionLocal() as s:
        for e in s.query(db.KbEntity).filter(db.KbEntity.tenant == "baci").all():
            if e.key in kept:
                e.attributes = kept[e.key]
        s.commit()

    print("\n— a product's own photograph is a hero, with no library at all —")
    with db.SessionLocal() as s2:
        s2.add(db.KbEntity(tenant="baci", key="firenze", name="Firenze Set",
                           type="product", price="129", availability="available",
                           status="active", review="approved",
                           attributes={"image": "https://cdn.shopify.com/s/f/p/fz.jpg?v=9"}))
        s2.commit()
    skill_pack.draft_campaign = _blocks_drafter([
        {"type": "heading", "text": "A table worth setting", "level": 1},
        {"type": "text", "html": "<p>Hi {{FIRST_NAME}}.</p>"},
        {"type": "cta", "label": "See it", "url": "https://x/f"}])
    r = skill.run("campaign_email", "baci", segment="lapsed_60_90", goal="launch")
    ck("with nothing in the creative library, the product shot leads",
       "hero" in _shape(r) and "/p/fz" in (_meta(r, "html") or ""), str(_shape(r)))
    ck("…and the run says where that photograph came from",
       any("own product shot" in n for n in r.get("notes", [])))


    print("\n— with no photographs on file, the catalogue is refreshed first —")
    from app import catalog_sync as _cs
    with db.SessionLocal() as s:
        for e in s.query(db.KbEntity).filter(db.KbEntity.tenant == "baci").all():
            e.attributes = {k: v for k, v in (e.attributes or {}).items()
                            if k != "image"}
        s.commit()
    _calls = []
    _real_sync = _cs.sync_shopify

    def _fake_sync(tenant, limit=250, dry_run=False):
        _calls.append(tenant)
        with db.SessionLocal() as s2:
            e = (s2.query(db.KbEntity)
                 .filter(db.KbEntity.tenant == "baci",
                         db.KbEntity.key == "glp1").first())
            if e:
                e.attributes = {"image": "https://cdn.shopify.com/s/f/p/re.jpg?v=2"}
                s2.commit()
        return {"products_seen": 3, "images_filed": 1}
    _cs.sync_shopify = _fake_sync
    skill_pack.draft_campaign = _blocks_drafter([
        {"type": "heading", "text": "A table worth setting", "level": 1},
        {"type": "text", "html": "<p>Hi {{FIRST_NAME}}.</p>"},
        {"type": "cta", "label": "See it", "url": "https://x/f"}])
    r = skill.run("campaign_email", "baci", segment="repeat_buyers", goal="launch")
    ck("a catalogue with no photos is refreshed rather than reported",
       _calls == ["baci"], str(_calls))
    ck("…and the photograph it fetched is in the email",
       "/p/re" in (_meta(r, "html") or ""), str(_shape(r)))
    ck("…and the run says it refreshed, so it is not a silent write",
       any("catalogue was refreshed" in n for n in r.get("notes", [])))
    _cs.sync_shopify = _real_sync

    print("\n— a link points at a page that EXISTS, not the usual pattern —")
    from app import links as _links
    with db.SessionLocal() as s:
        t = s.query(db.Tenant).filter(db.Tenant.key == "baci").first()
        t.domain = "eienhealth.com"
        s.add(db.KbEntity(tenant="baci", key="shop", name="Shop",
                          type="collection", availability="available",
                          status="active", review="approved", attributes={}))
        s.commit()
    ck("the store's real catalogue page is found, not /collections/all",
       _links.shop_url("baci") == "https://eienhealth.com/collections/shop",
       _links.shop_url("baci"))
    ck("a URL that does not exist is spotted",
       _links.check('<a href="https://eienhealth.com/collections/all">x</a>',
                    "baci") == ["https://eienhealth.com/collections/all"])
    ck("…and an external link is somebody else's business",
       _links.check('<a href="https://instagram.com/x">x</a>', "baci") == [])

    skill_pack.draft_campaign = _blocks_drafter([
        {"type": "text", "html": "<p>Hello.</p>"},
        {"type": "cta", "label": "See",
         "url": "https://eienhealth.com/collections/all"},
        {"type": "ps",
         "html": '<p>P.S. <a href="https://eienhealth.com/collections/all">here</a>.</p>'}])
    r = skill.run("campaign_email", "baci", segment="repeat_buyers", goal="x")
    html = _meta(r, "html") or ""
    ck("an invented collection URL never reaches the reader",
       "/collections/all" not in html)
    ck("…every on-site link points at the real catalogue",
       "/collections/shop" in html)
    ck("…and the run names what it repointed",
       any("not a page on this site" in n for n in r.get("notes", [])))

    print("\n— one email, one subject: another product's claims are set aside —")
    kb.add_claim("baci", "Belongs only to the metabolic formula.", "x",
                 ["quality"], proof_type="data", entity_key="glp1-support",
                 origin="human", status="active")
    _seen = {}

    def _capture_claims(b, sg, g, craft=None):
        _seen["claims"] = [c.get("claim", "") for c in (b.get("claims") or [])]
        return _blocks_drafter([
            {"type": "text", "html": "<p>Hi.</p>"},
            {"type": "products", "keys": ["glp1"]},
            {"type": "cta", "label": "See", "url": ""}])(b, sg, g, craft)
    skill_pack.draft_campaign = _capture_claims
    r = skill.run("campaign_email", "baci", segment="repeat_buyers", goal="x")
    # `kb.claims` has always scoped this correctly: with no entity named you
    # get BRAND-WIDE claims only. So a product's own claim cannot leak — and
    # the live GLP-1 non-sequitur (owner, 2026-08-22) means that claim is
    # filed brand-wide in the KB, which is a DATA fix, not a code one. The
    # skill-level screen below is the belt to that braces: it also holds when
    # an entity IS named and the drafter features a different subset.
    ck("a claim scoped to a product this email does not feature is withheld",
       not any("metabolic formula" in c for c in _seen.get("claims", [])),
       " | ".join(c[:34] for c in _seen.get("claims", [])))
    ck("…and brand-wide claims still come through",
       any("Four Seasons" in c for c in _seen.get("claims", [])))

    print("\n— a link the drafter could not know is FILLED, not fatal —")
    with db.SessionLocal() as s:
        t = s.query(db.Tenant).filter(db.Tenant.key == "baci").first()
        t.domain = "example-store.com"
        s.commit()
    before = len(_drafted)
    skill_pack.draft_campaign = lambda b, sg, g, craft=None: ({
        "subject": "A specific enough line", "preheader": "a second line",
        "blocks": [
            {"type": "text", "html": "<p>Hi {{FIRST_NAME}}.</p>"},
            {"type": "cta", "label": "See it", "url": ""},
            {"type": "ps", "html": '<p>P.S. it is on the <a href="">page</a>.</p>'}],
        "claim_ids": [], "cta_label": "See it", "cta_url": ""}, "model", "")
    r = skill.run("campaign_email", "baci", segment="repeat_buyers", goal="x")
    html = _meta(r, "html") or ""
    ck("an email whose links the drafter left empty STILL SHIPS",
       len(_drafted) == before + 1)
    ck("…because the empty links were pointed at the store, not blocked",
       'href=""' not in html and 'href="#"' not in html
       and "example-store.com" in html)
    ck("…and the run says it supplied them",
       any("drafter left empty" in n for n in r.get("notes", [])))

    print("\n— an approval is never offered for an email that was not created —")
    row = systems.find("baci", "campaign_email")
    with db.SessionLocal() as s:
        rr = s.get(db.System, row.id)
        rr.autonomy = "approve_all"
        s.commit()

    before = len(_drafted)
    skill_pack.draft_campaign = _blocks_drafter([
        {"type": "text", "html": "<p>CitroBurn came out of that process.</p>"},
        {"type": "cta", "label": "Learn more", "url": "https://x/c"}])
    r = skill.run("campaign_email", "baci", segment="new_subscribers", goal="x")
    ck("the copy passed the validator", (r.get("items") or [{}])[0].get("ok") is True)
    ck("…but no draft reached the ESP", len(_drafted) == before)
    ck("the summary SAYS it was not drafted",
       "NOT DRAFTED IN ESP" in (r.get("summary") or ""), r.get("summary", "")[:70])
    with db.SessionLocal() as s:
        ap = (s.query(db.Approval)
              .filter(db.Approval.run_id == (r.get("run_id") or ""))
              .first())
    ck("the approval for it was WITHDRAWN, not left waiting",
       ap is not None and ap.status == "withdrawn",
       ap.status if ap else "no approval row")
    ck("…and it records why, so the queue is not a mystery",
       bool((ap.payload or {}).get("withdrawn_because")) if ap else False)
    ck("approving it can no longer report success over nothing",
       "Already withdrawn" in approvals.apply_decision(ap.id, "approved")
       if ap else False)

    before = len(_drafted)
    skill_pack.draft_campaign = _blocks_drafter([
        {"type": "text", "html": "<p>An ordinary email.</p>"},
        {"type": "cta", "label": "Shop", "url": "https://example.com/shop"}])
    r = skill.run("campaign_email", "baci", segment="new_subscribers", goal="x")
    with db.SessionLocal() as s:
        ap = (s.query(db.Approval)
              .filter(db.Approval.run_id == (r.get("run_id") or "")).first())
    ck("a real draft still queues a real approval",
       len(_drafted) == before + 1 and ap is not None and ap.status == "pending")
    said = approvals.apply_decision(ap.id, "approved") if ap else ""
    ck("…and approving says what it actually did — reviewed, not sent",
       "Nothing was sent" in said and "Launch it" in said, said[:70])

    with db.SessionLocal() as s:
        rr = s.get(db.System, row.id)
        rr.autonomy = "auto"
        s.commit()

    print("\n— the composer still works when there is no model —")
    skill_pack.draft_campaign = lambda b, s, g, craft=None: (None, "composed", "no key")
    r = skill.run("campaign_email", "baci", segment="new_subscribers", goal="x")
    ck("it still produced an email", (r.get("items") or [{}])[0].get("ok") is True)
    ck("…marked composed, and the run says the model did not draft it",
       _meta(r, "basis") == "composed"
       and any("did not draft" in n for n in r.get("notes", [])))

    print("\n" + ("all checks passed" if not _fail
                  else f"{len(_fail)} FAILED: " + "; ".join(_fail)))
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
