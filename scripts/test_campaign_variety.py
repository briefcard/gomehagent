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
    # RETARGETED (UI overhaul 3.3): nothing drafts at emit any more — a clean
    # run is HELD for the workroom; "ships" means it clears the urgency gate.
    ck("the SAME copy is held cleanly once a real deadline is on the plan",
       "held for your review" in (r.get("summary") or ""),
       (r.get("summary") or "")[:90])

    print("\n— a repair re-renders: the ESP gets the REPAIRED email —")
    calls = {"n": 0}

    # ON `auto`, THE ONLY RUNG THAT REPAIRS SINCE 2026-09-02. The property
    # asserted below is unchanged and was a real bug once: the rendered HTML
    # was built from the PRE-repair copy, so a repaired email filed the
    # repaired text and shipped the failing HTML. Only the precondition moved.
    with db.SessionLocal() as _s:
        _row = systems.find("baci", "campaign_email")
        _s.get(db.System, _row.id).autonomy = "auto"
        _s.commit()

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
    # RETARGETED (UI overhaul 3.3): the ESP sees it at the approval-time
    # push — which must carry the REPAIRED render, never the rejected one.
    skill_pack.push_campaign_to_esp("baci", it.get("output_id", ""))
    ck("the push carries the REPAIRED html, not the rejected render",
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
       "example-store.com" in (_meta(r, "html") or ""))

    # Nothing to point at anywhere: no domain, and no entity with a URL.
    with db.SessionLocal() as s:
        t = s.query(db.Tenant).filter(db.Tenant.key == "baci").first()
        t.domain = ""
        s.commit()
    before = len(_drafted)
    skill_pack.draft_campaign = _urlless
    r = skill.run("campaign_email", "baci", segment="new_subscribers", goal="x")
    # CHANGED 2026-08-22, CHANGED AGAIN 2026-08-27 (UI overhaul 3.3). A dead
    # button is BROKEN, not false. The 08-22 policy shipped it to the ESP
    # marked [NEEDS FIX] because the console had no other way to look at it;
    # the WORKROOM is that way now, so a defective email is HELD in our
    # store — visible, reviewable, its approval withdrawn — and NOTHING
    # reaches the client's platform. The push refuses the withdrawn verdict
    # rather than offering a side door around it.
    ck("a defective draft reaches the ESP never — it is held for the workroom",
       len(_drafted) == before, str(len(_drafted) - before))
    ck("…the summary says held-with-defects",
       "held with defects" in (r.get("summary") or ""),
       (r.get("summary") or "")[:90])
    _oid_dead = (r.get("items") or [{}])[0].get("output_id", "")
    _got_dead = skill_pack.push_campaign_to_esp("baci", _oid_dead)
    ck("…and the push refuses the withdrawn verdict, naming it",
       _got_dead.get("ok") is not True
       and "withdrew" in (_got_dead.get("error") or ""),
       str(_got_dead)[:90])
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
    ck("an email whose links the drafter left empty is STILL HELD cleanly",
       "held for your review" in (r.get("summary") or ""),
       (r.get("summary") or "")[:90])
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
    ck("the summary SAYS it can never be pushed",
       "NOT PUSHABLE" in (r.get("summary") or ""), r.get("summary", "")[:70])
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
    # RETARGETED (UI overhaul 3.3): the approval queues while NOTHING is in
    # the ESP — and approving is now the act that pushes the draft there.
    ck("a clean campaign queues its approval with nothing yet in the ESP",
       len(_drafted) == before and ap is not None and ap.status == "pending")
    said = approvals.apply_decision(ap.id, "approved") if ap else ""
    ck("…and approving PUSHES the draft and says so — launch stays human",
       "pushed to" in said and "Launch" in said
       and len(_drafted) == before + 1, said[:80])

    print("\n— Request changes: the redraft consumes the filed feedback —")
    skill_pack.draft_campaign = _blocks_drafter([
        {"type": "text", "html": "<p>First attempt, fine but wordy.</p>"},
        {"type": "cta", "label": "Shop", "url": "https://example.com/shop"}])
    r_rd = skill.run("campaign_email", "baci", segment="new_subscribers",
                     goal="x")
    oid_a = (r_rd.get("items") or [{}])[0].get("output_id", "")
    with db.SessionLocal() as s:
        s.add(db.FeedbackItem(tenant="baci", output_id=oid_a, part="body",
                              category="length",
                              note="REDRAFT-NOTE two products max",
                              level="draft", status="open"))
        s.commit()
    _seen: dict = {}
    _orig_drafter = skill_pack.draft_campaign

    def _capture(bundle, seg, goal, craft=None):
        _seen["craft"] = dict(craft or {})
        return _orig_drafter(bundle, seg, goal, craft)
    skill_pack.draft_campaign = _capture
    got_rd = skill_pack.redraft_artifact("baci", oid_a, note="typed note too")
    ck("the redraft runs fresh and supersedes",
       got_rd.get("ok") is True
       and got_rd.get("output_id") not in ("", oid_a), str(got_rd)[:90])
    ck("…the drafter received the owner's notes, feedback first",
       "REDRAFT-NOTE" in (_seen.get("craft", {}).get("revision_notes") or "")
       and "typed note too" in (_seen.get("craft", {})
                                .get("revision_notes") or ""),
       (_seen.get("craft", {}).get("revision_notes") or "")[:80])
    with db.SessionLocal() as s:
        old_o = s.get(db.Output, oid_a)
        fb_row = (s.query(db.FeedbackItem)
                  .filter_by(output_id=oid_a).first())
        old_ap = (s.query(db.Approval)
                  .filter(db.Approval.run_id == (r_rd.get("run_id") or ""))
                  .first())
    ck("the old row is SUPERSEDED and names its successor",
       old_o.status == "superseded"
       and old_o.destination == f"superseded:{got_rd.get('output_id')}",
       f"{old_o.status} · {old_o.destination}")
    ck("…its approval withdrawn, so nothing stale is decidable",
       old_ap is not None and old_ap.status == "withdrawn",
       str(getattr(old_ap, "status", None)))
    ck("…and the feedback is marked applied", fb_row.status == "applied")

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

    print("\n— the angle is direction, not copy —")
    #
    # Owner, 2026-08-23: "we have incorrectly wired the Angle/Concept field in
    # the email campaign prompt into the subject line which is not the point."
    # It was exactly that: `_compose_campaign` did
    #     line = (goal or seg.get("angle") or "A quick note").split(".")[0]
    # and put `line` into BOTH `subject` and `headline`. So the internal brief
    # written FOR the drafter arrived in a customer's inbox as the subject —
    # and because a model-less account always takes the composer path, every
    # send they had seen was like that.
    kb.add_entity("baci", "product", "glasses", "Clear Acrylic Water Glasses",
                  description="Shatterproof.",
                  attributes={"availability": "in stock"})
    _brief = ("A reason to come back now, while the habit is recoverable and "
              "before a win-back discount is needed.")
    skill_pack.draft_campaign = lambda b, s, g, craft=None: (None, "composed", "no key")
    r = skill.run("campaign_email", "baci", segment="win_back", goal=_brief)
    _m = (r.get("items") or [{}])[0].get("meta") or {}
    ck("the composer does not put the brief in the subject line",
       _brief[:24] not in _m.get("subject", ""), _m.get("subject", ""))
    # A PRODUCT NAME, whichever one the bundle led with — not this suite's
    # most recently seeded product. Pinning the exact name made the check about
    # fixture ordering rather than about the behaviour.
    _catalogue = {e.name for e in kb.entities("baci", available_only=False)}
    ck("…it uses something a customer would recognise instead",
       _m.get("subject", "") in _catalogue,
       f'{_m.get("subject", "")!r} not one of {sorted(_catalogue)[:4]}')
    ck("…nor in the headline", _brief[:24] not in (_m.get("html") or ""))
    ck("the angle is still RECORDED, so nothing is lost",
       _brief[:24] in (_m.get("angle") or ""))
    ck("…and the run says where it came from",
       any("angle from the plan" in n for n in r.get("notes", [])))

    print("\n— with no angle at all, one gets chosen and named —")
    skill_pack.draft_campaign = _blocks_drafter(
        [{"type": "text", "html": "<p>A short note.</p>"},
         {"type": "cta", "label": "See", "url": "https://x/p"}],
        subject="Six that do not shatter")

    def _with_angle(bundle, seg, goal, craft=None):
        data, basis, why = _blocks_drafter(
            [{"type": "text", "html": "<p>A short note.</p>"},
             {"type": "cta", "label": "See", "url": "https://x/p"}],
            subject="Six that do not shatter")(bundle, seg, goal, craft)
        data["angle"] = "The set that survives the pool deck"
        return data, basis, why

    skill_pack.draft_campaign = _with_angle
    r2 = skill.run("campaign_email", "baci", segment="new_subscribers", goal="")
    _m2 = (r2.get("items") or [{}])[0].get("meta") or {}
    ck("the drafter's own angle is filed on the run",
       _m2.get("angle") == "The set that survives the pool deck", str(_m2.get("angle")))
    ck("…attributed to the drafter, not to the plan",
       _m2.get("angle_chosen_by") == "drafter", str(_m2.get("angle_chosen_by")))
    ck("…and the run says it chose one, so it is correctable next time",
       any("drafter chose one" in n for n in r2.get("notes", [])))
    ck("the angle it chose is NOT the subject the customer sees",
       "The set that survives" not in _m2.get("subject", ""),
       _m2.get("subject", ""))

    print("\n— an angle is no longer demanded before anything can run —")
    from app import systems as _sysmod
    _goal_field = next(f for f in _sysmod.workflow("campaign_email")["plan_fields"]
                       if f["key"] == "goal")
    ck("the angle field is optional", not _goal_field.get("required"),
       str(_goal_field))

    print("\n— one email, one argument: the hero owns the positioning —")
    # Owner, 2026-08-31: "It doesn't have to be one-email one-product. It just
    # needs to not mix up positioning between them."
    #
    # Proof was scoped to EVERY featured product, so six offered products meant
    # six products' worth of "your only credibility, cite by id" — and a
    # drafter handed that reasonably built a case for each. The email showed
    # several things and argued several things, which is the mix.
    _seed("coverings")
    kb.add_audience("coverings", "spec", "The specifier", ["m"], ["slab"])
    for _k, _n in (("aqua-jug", "Aqua Jug"), ("milano-plate", "Milano Plate"),
                   ("firenze-bowl", "Firenze Bowl")):
        kb.add_entity("coverings", "product", _k, _n, price="40")
        kb.add_claim("coverings", f"{_n} is why people choose us.",
                     f"spec {_k}", ["quality"], entity_key=_k,
                     origin="human", status="active")
    # ASSERTED ON THE PROMPT, because the prompt is what changed. Asserting on
    # the bundle passed with the fix reverted — both guards reported MISSED,
    # which is the harness catching a check that was watching the wrong thing.
    _saw2: dict = {}
    _real_llm = skill_pack.llm.ask if hasattr(skill_pack, "llm") else None

    from app import config as _cfg, llm as _llm
    _key_was, _cfg.ANTHROPIC_API_KEY = _cfg.ANTHROPIC_API_KEY, "test-key"
    _ask_was = _llm.ask

    def _capture_prompt(purpose, prompt, **kw):
        _saw2["prompt"] = prompt
        raise RuntimeError("stop after the prompt is built")
    _llm.ask = _capture_prompt
    # Point the seam back at the LIVE builder — the suite replaces it globally,
    # and the prompt is what this check is about.
    _seam_was = skill_pack.draft_campaign
    skill_pack.draft_campaign = skill_pack._draft_campaign_live
    try:
        skill.run("campaign_email", "coverings", segment="reorder_due",
                  audience_key="spec", entity_key="milano-plate")
    except Exception:
        pass
    skill_pack.draft_campaign = _seam_was
    _llm.ask, _cfg.ANTHROPIC_API_KEY = _ask_was, _key_was
    _pr = _saw2.get("prompt") or ""
    ck("companions are still offered — this is not a one-entity rule",
       _pr.count("[milano-plate]") and _pr.count("[aqua-jug]"),
       "an email may show several; it may not argue several")
    ck("  exactly one of them is marked HERO", _pr.count("- HERO ") == 1,
       str([l for l in _pr.splitlines() if l.startswith("- ")])[:140])
    ck("  and it is the one the plan named",
       "- HERO [milano-plate]" in _pr,
       "the plan is the reviewed instruction")
    ck("the drafter is told the hero owns the positioning",
       "one email argues one thing" in _pr,
       "without it, which entity the email is FOR is inferred from list order")

    print("\n— Request changes still works on an account that HAS a persona —")
    # THE REGRESSION THIS PINS. c4f72cc made `audience_key` required on
    # campaign_email, and its own commit message claimed the workroom redraft
    # was covered. It was not: `redraft_artifact` rebuilt the call without the
    # field, so on any account with an approved persona every Request-changes
    # click was refused before the bundle was even resolved — the notes never
    # reached the drafter, the feedback stayed open, and the owner was told
    # only "blocked".
    #
    # On its OWN account deliberately: the block above runs on a persona-less
    # `baci`, which is precisely the state the regression does not bite in, so
    # testing it there would prove nothing.
    _seed("eien")
    kb.add_audience("eien", "core_hostess", "The host",
                    ["mismatched sets"], ["tablescape"])
    _r0 = skill.run("campaign_email", "eien", segment="reorder_due",
                    audience_key="core_hostess", goal="x")
    _oid0 = (_r0.get("items") or [{}])[0].get("output_id", "")
    ck("a draft records WHO it was written for",
       ((_r0.get("items") or [{}])[0].get("meta") or {})
       .get("audience_key") == "core_hostess",
       "there is nowhere else to read it back from — Output.audience_key "
       "carries the SEGMENT for a campaign")
    _saw: dict = {}
    _keep = skill_pack.draft_campaign

    def _cap(bundle, seg, goal, craft=None):
        _saw["notes"] = (craft or {}).get("revision_notes", "")
        return _keep(bundle, seg, goal, craft)
    skill_pack.draft_campaign = _cap
    _rd = skill_pack.redraft_artifact("eien", _oid0,
                                      note="Make the opening warmer.")
    skill_pack.draft_campaign = _keep
    ck("Request changes redrafts instead of refusing",
       _rd.get("ok") is True, str(_rd.get("error"))[:110])
    ck("  and the owner's note reaches the drafter",
       "Make the opening warmer" in (_saw.get("notes") or ""),
       repr(_saw.get("notes"))[:90])

    # ...AND WHEN A REDRAFT IS GENUINELY REFUSED, IT SAYS WHY. The message
    # threw `blocked_on` away, so the one field naming the cause was lost and
    # every refusal read as the bare word "blocked".
    _r1 = skill.run("campaign_email", "eien", segment="reorder_due",
                    audience_key="core_hostess", goal="y")
    _oid1 = (_r1.get("items") or [{}])[0].get("output_id", "")
    with db.SessionLocal() as _s:
        _a = (_s.query(db.ArtifactBody)
              .filter(db.ArtifactBody.output_id == _oid1).first())
        _a.meta = {}                       # a draft from before the reader was recorded
        _s.commit()
    _bad = skill_pack.redraft_artifact("eien", _oid1, note="try again")
    ck("a refused redraft NAMES what stopped it",
       _bad.get("ok") is False and "audience_key" in str(_bad.get("error")),
       str(_bad.get("error"))[:120])

    print("\n— the typed note is FILED, not whispered —")
    # It used to be appended to the digest and never persisted: never in the
    # thread, never reinforceable, and destroyed on every refused click — which
    # is what happened all through the redraft outage. `feedback_add`'s own
    # principle is that a store nothing reads is a complaint box; this was the
    # inverse — a judgement nothing stores is a shout. It also made the flash
    # lie: a note-only redraft reported "0 feedback item(s) consumed".
    _r2 = skill.run("campaign_email", "eien", segment="reorder_due",
                    audience_key="core_hostess", goal="z")
    _oid2 = (_r2.get("items") or [{}])[0].get("output_id", "")
    _saw3: dict = {}
    _keep3 = skill_pack.draft_campaign

    def _cap3(bundle, seg, goal, craft=None):
        _saw3["notes"] = (craft or {}).get("revision_notes", "")
        return _keep3(bundle, seg, goal, craft)
    skill_pack.draft_campaign = _cap3
    _rd2 = skill_pack.redraft_artifact("eien", _oid2, part="body",
                                       note="Lead with the shipping line.")
    skill_pack.draft_campaign = _keep3
    ck("a note-only redraft reports what it actually consumed",
       _rd2.get("consumed") == 1, str(_rd2.get("consumed")))
    ck("  and the note reaches the drafter with the SAME structure a filed "
       "item carries",
       "[body · general] Lead with the shipping line." in (_saw3.get("notes") or ""),
       "the same sentence must not arrive structured or naked depending on "
       "which box it landed in")
    with db.SessionLocal() as _s:
        _rows = (_s.query(db.FeedbackItem)
                 .filter(db.FeedbackItem.output_id == _oid2).all())
        _states = [(f.part, f.status) for f in _rows]
    ck("  it is in the thread, and closed once applied",
       _states == [("body", "applied")], str(_states))

    # AND IT SURVIVES A REFUSAL — the behaviour that would have preserved the
    # owner's notes throughout the outage. Filed BEFORE the run, deliberately.
    _r3 = skill.run("campaign_email", "eien", segment="reorder_due",
                    audience_key="core_hostess", goal="w")
    _oid3 = (_r3.get("items") or [{}])[0].get("output_id", "")
    with db.SessionLocal() as _s:
        _a3 = (_s.query(db.ArtifactBody)
               .filter(db.ArtifactBody.output_id == _oid3).first())
        _a3.meta = {}
        _s.commit()
    _rd3 = skill_pack.redraft_artifact("eien", _oid3, part="body",
                                       note="Do not lose this thought.")
    with db.SessionLocal() as _s:
        _kept = [(f.note[:25], f.status) for f in
                 _s.query(db.FeedbackItem)
                 .filter(db.FeedbackItem.output_id == _oid3).all()]
    ck("a note typed at a redraft that REFUSES is not lost",
       _rd3.get("ok") is False and _kept == [("Do not lose this thought.", "open")],
       str(_kept))

    print("\n" + ("all checks passed" if not _fail
                  else f"{len(_fail)} FAILED: " + "; ".join(_fail)))
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
