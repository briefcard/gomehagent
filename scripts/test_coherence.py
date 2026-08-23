"""One artifact, one subject — the check, and the live defects it closes.

The email that prompted this (owner, 2026-08-22): hero photograph of a
TABLECLOTH, subject line and body about shatterproof GLASSES, product card a
PITCHER bundle, the Four Seasons placement asserted twice and "designed in
Milan" asserted twice. Nothing in it was false and every part was individually
grounded — it was still not client-facing, because the parts did not agree.

Four things are pinned here.

  1. THE UNIT IS THE ARTIFACT, NOT THE STRING. `validator.check` reads text, so
     no rule written there could ever see a wrong picture. `emit` now takes the
     PARTS and `coherence.review` reads them.
  2. THE COMMITMENT COMES FIRST. Nothing may be selected before the artifact
     declares what it is about. The hero used to be chosen fifty lines before
     the drafter said what the email was for.
  3. THE CONTRACT IS TYPED BY REFERENT, so it fits systems with no product. A
     reply commits to a QUESTION; a round-up commits to being many things and
     the check inverts rather than being switched off.
  4. A COHERENCE FAILURE IS NOT A KNOWLEDGE GAP. It blocks the send and stays
     out of the authoring backlog, because no amount of authoring would have
     prevented it.

Run: python3 scripts/test_coherence.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'coh.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import (brand_theme, coherence, db, esp, kb, skill,  # noqa: E402
                 skill_pack, systems, tenants)

_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def rules(findings):
    return {f["rule"] for f in findings}


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


# --------------------------------------------------------------------------
# Part one: the check itself, with no database in the way.
# --------------------------------------------------------------------------
def unit():
    print("\n— the failing email, reconstructed —")
    c = coherence.commit("entity", "acrylic-water-glasses",
                         label="Clear Acrylic Water Glasses",
                         audience="lapsed", action="see the set",
                         also=[])
    bad = coherence.parts(
        prominent="Glasses that go where you go",
        text=("Picture the scene: someone knocks a water glass and nothing "
              "happens. That is what Baci Milano set out to solve. The result "
              "landed on tables at the Four Seasons and aboard the "
              "Ritz-Carlton Yacht Collection. Designed in Milan. Specified by "
              "the Four Seasons and the Ritz-Carlton Yacht Collection."),
        images=[{"url": "https://cdn/tablecloth.jpg", "alt": "Linen tablecloth",
                 "subject_key": "portofino-tablecloth", "basis": "approved_asset"}],
        items=[{"key": "acrylic-pitcher-set", "name": "Acrylic Pitcher & Glasses Set"}],
        claims=[{"claim_id": "C1", "scope": "brand-wide",
                 "text": "Specified by the Four Seasons and the Ritz-Carlton "
                         "Yacht Collection."},
                {"claim_id": "C2", "scope": "brand-wide",
                 "text": "Baci Milano is a design house based in Milan."}])
    got = coherence.review(c, bad, brand_name="Baci Milano")
    r = rules(got)
    ck("the tablecloth hero is caught", "image_off_subject" in r, str(sorted(r)))
    ck("the uncommitted pitcher bundle is caught", "item_off_subject" in r)
    ck("the Four Seasons proof spent twice is caught", "proof_repeated" in r)
    ck("two brand credentials in a product email is caught",
       "background_overrun" in r)
    ck("…and every one of them BLOCKS", len(coherence.block_reasons(got)) >= 4)
    ck("the findings carry a fix, not just a complaint",
       all(f.get("fix") for f in got))

    print("\n— the same email, made coherent —")
    good = coherence.parts(
        prominent="Glasses that go where you go",
        text=("Someone knocks a water glass and nothing happens. Shatterproof, "
              "and specified by the Four Seasons. Six to a set."),
        images=[{"url": "https://cdn/glasses.jpg", "alt": "Acrylic glasses",
                 "subject_key": "acrylic-water-glasses", "basis": "approved_asset"}],
        items=[{"key": "acrylic-water-glasses", "name": "Clear Acrylic Water Glasses"}],
        claims=[{"claim_id": "C1", "scope": "brand-wide",
                 "text": "Specified by the Four Seasons."}])
    ck("it passes", coherence.review(c, good, brand_name="Baci Milano") == [],
       str(coherence.review(c, good, brand_name="Baci Milano")))

    print("\n— what the brand is called is not a repeated proof —")
    many = coherence.parts(
        text="Baci Milano makes this. Baci Milano has for years. Baci Milano.",
        images=[], items=[{"key": "acrylic-water-glasses", "name": "Glasses"}],
        claims=[{"claim_id": "C9", "scope": "acrylic-water-glasses",
                 "text": "Baci Milano designs its own moulds."}])
    ck("the brand's own name repeating is not flagged",
       "proof_repeated" not in rules(
           coherence.review(c, many, brand_name="Baci Milano")))

    print("\n— an unattributed picture is not assumed innocent —")
    mystery = coherence.parts(
        text="Glasses.", images=[{"url": "https://cdn/x.jpg", "alt": "x"}],
        items=[], claims=[])
    ck("an image with no subject_key is reported",
       "image_unattributed" in rules(coherence.review(c, mystery)))

    print("\n— no commitment must never read as coherent —")
    ck("an artifact with no commitment BLOCKS",
       rules(coherence.review({}, coherence.parts(text="anything")))
       == {"no_commitment"})

    print("\n— a companion named at commit time is legitimate —")
    with_companion = coherence.commit(
        "entity", "acrylic-water-glasses", label="Clear Acrylic Water Glasses",
        also=["acrylic-pitcher-set"])
    ok_parts = coherence.parts(
        text="Glasses that do not shatter, and the pitcher that matches.",
        images=[{"url": "u", "alt": "a", "subject_key": "acrylic-pitcher-set"}],
        items=[{"key": "acrylic-pitcher-set", "name": "Pitcher Set"}], claims=[])
    ck("a committed companion may be shown and pictured",
       coherence.review(with_companion, ok_parts) == [],
       str(coherence.review(with_companion, ok_parts)))

    print("\n— a REPLY commits to a question, not to a product —")
    q = coherence.commit("situation", "shipping_time", action="answer it")
    reply = coherence.parts(
        text="It leaves the warehouse in two days. Our pieces are specified by "
             "the Four Seasons. Specified by the Four Seasons, in fact.",
        claims=[{"claim_id": "C1", "scope": "brand-wide",
                 "text": "Specified by the Four Seasons."}])
    rr = rules(coherence.review(q, reply, brand_name="Baci Milano"))
    ck("the same proof spent twice in a reply is caught", "proof_repeated" in rr)
    ck("…and no image rule fires on a text-only artifact",
       not any(x.startswith("image_") for x in rr), str(sorted(rr)))

    print("\n— a ROUND-UP is many subjects on purpose —")
    survey = coherence.commit("survey", "august", expects=["glasses", "linens"])
    rows = coherence.parts(
        text="Glasses sold well. Linens held steady.",
        items=[{"key": "a"}, {"key": "a"}, {"key": "b"}])
    sr = rules(coherence.review(survey, rows))
    ck("multiplicity is NOT a failure in survey mode",
       "item_off_subject" not in sr and "subject_absent" not in sr, str(sorted(sr)))
    ck("…but the same item listed twice still is", "survey_repeats" in sr)
    missing = coherence.review(
        coherence.commit("survey", "august", expects=["glasses", "candles"]),
        coherence.parts(text="Glasses sold well."))
    ck("…and a round-up missing what it promised says so",
       "survey_incomplete" in rules(missing))


# --------------------------------------------------------------------------
# Part two: the live path. The ordering defect is the one that shipped.
# --------------------------------------------------------------------------
def _seed(tenant="baci"):
    kb.ensure_brand(tenant, "Baci Milano")
    kb.set_brand(tenant, positioning="Italian-designed tableware.", tone="warm")
    kb.add_banned(tenant, "made in Italy")
    row = systems.find(tenant, "campaign_email") or systems.create(tenant, "campaign_email")
    with db.SessionLocal() as s:
        s.get(db.System, row.id).status = "live"
        s.commit()
    brand_theme.approve(tenant, {"footer.address": "2875 NE 191st St, Aventura FL"})


def _drafter(blocks, subject="Glasses that go where you go", claim_ids=()):
    def _d(bundle, seg, goal, craft=None):
        return ({"subject": subject, "preheader": "six to a set",
                 "blocks": list(blocks), "claim_ids": list(claim_ids),
                 "cta_label": "Shop", "cta_url": "https://x/s"}, "model", "")
    return _d


def live():
    db.init_db()
    tenants.seed()
    _seed("baci")
    _fake_esp()

    # Two products. `aa-` sorts FIRST, which is what the old code picked.
    kb.add_entity("baci", "product", "aa-tablecloth", "Portofino Tablecloth",
                  description="Linen.",
                  attributes={"image": "https://cdn/tablecloth.jpg",
                              "availability": "in stock"})
    kb.add_entity("baci", "product", "zz-glasses", "Clear Acrylic Water Glasses",
                  description="Shatterproof acrylic.",
                  attributes={"image": "https://cdn/glasses.jpg",
                              "availability": "in stock"})

    print("\n— the hero follows the SUBJECT, not the alphabet —")
    skill_pack.draft_campaign = _drafter([
        {"type": "hero"},
        {"type": "heading", "text": "They do not shatter", "level": 1},
        {"type": "text", "html": "<p>A note about the glasses.</p>"},
        {"type": "products", "keys": ["zz-glasses"]},
        {"type": "cta", "label": "See the set", "url": "https://x/p"},
    ])
    r = skill.run("campaign_email", "baci", segment="new_subscribers",
                  goal="introduce the glasses")
    item = (r.get("items") or [{}])[0]
    html = (item.get("meta") or {}).get("html") or ""
    ck("the email committed to the product the drafter actually featured",
       (item.get("commitment") or {}).get("key") == "zz-glasses",
       str(item.get("commitment")))
    ck("…so the hero is the GLASSES, not the alphabetically-first tablecloth",
       "cdn/glasses.jpg" in html and "cdn/tablecloth.jpg" not in html)
    ck("the run says out loud what the email is about",
       any("this email is about" in n for n in r.get("notes", [])))
    ck("and it passed", item.get("ok") is True, str(item.get("failures")))

    print("\n— an uncommitted product on a card cannot ship —")
    skill_pack.draft_campaign = _drafter([
        {"type": "heading", "text": "They do not shatter", "level": 1},
        {"type": "text", "html": "<p>About the glasses.</p>"},
        {"type": "products", "keys": ["zz-glasses"]},
        {"type": "cta", "label": "See", "url": "https://x/p"},
    ])
    # The drafter names one product; the offered list holds two. Before the
    # fix the bundle kept BOTH and every selector downstream could pick either.
    r2 = skill.run("campaign_email", "baci", segment="new_subscribers",
                   goal="introduce the glasses")
    i2 = (r2.get("items") or [{}])[0]
    ck("the offered list was narrowed to what was actually featured",
       (i2.get("commitment") or {}).get("also") == [],
       str((i2.get("commitment") or {}).get("also")))

    print("\n— the gate STOPS a send, it does not merely observe one —")
    #
    # Without a live block this file proved only that coherent emails pass,
    # which every version of the code does — `sabotage.py` reported the guard
    # UNDETECTED, and it was right. The drafter below repeats one claim's proof
    # twice; it returns the same copy when asked again, so the repair loop has
    # nothing to give and the email must stay blocked.
    kb.add_claim("baci", "Specified by the Four Seasons.", "brand brief",
                 [], origin="human", status="active")
    _cid = (kb.claims("baci") or [{}])[0]
    _cid = _cid["claim_id"] if isinstance(_cid, dict) else getattr(_cid, "id", "")
    _drafted.clear()
    skill_pack.draft_campaign = _drafter([
        {"type": "heading", "text": "They do not shatter", "level": 1},
        {"type": "text", "html": "<p>Specified by the Four Seasons. Truly, "
                                 "specified by the Four Seasons.</p>"},
        {"type": "products", "keys": ["zz-glasses"]},
        {"type": "cta", "label": "See", "url": "https://x/p"},
    ], claim_ids=[_cid])
    r3 = skill.run("campaign_email", "baci", segment="new_subscribers",
                   goal="introduce the glasses")
    i3 = (r3.get("items") or [{}])[0]
    _rules3 = {f["rule"] for f in (i3.get("failures") or [])}
    ck("an email that spends one proof twice is BLOCKED at the gate",
       i3.get("ok") is False and "coherence:proof_repeated" in _rules3,
       str(sorted(_rules3)))
    ck("…and the draft still reaches the ESP, marked, so it can be looked at",
       len(_drafted) == 1 and "[NEEDS FIX" in (_drafted[-1].get("name") or ""),
       (_drafted[-1].get("name") or "")[:70] if _drafted else "no draft")
    # NOT approvable, and by the stronger route: `emit` only ever queues an
    # approval for an item that PASSED, so an incoherent email never gets one
    # to withdraw. The draft exists to be looked at; it cannot be launched
    # through this system.
    with db.SessionLocal() as _s:
        _pending = [a for a in _s.query(db.Approval).all()
                    if (a.payload or {}).get("output_id") == i3.get("output_id")]
    ck("…but it is not approvable — nothing incoherent becomes launchable",
       not _pending and i3.get("ok") is False, str(len(_pending)))
    ck("…and the rule is namespaced, so it is not read as an authoring gap",
       all(r.startswith("coherence:") or r == "no_ban_list" for r in _rules3),
       str(sorted(_rules3)))

    print("\n— a coherence block is not a knowledge gap —")
    #
    # Asserted against a table that HAS both kinds in it. Run against an empty
    # ledger this passes for the wrong reason — which is one of the six false
    # passes `sabotage.py` was written after, so it is not repeated here.
    _sys = systems.find("baci", "campaign_email")
    with db.SessionLocal() as s:
        for reasons in (["coherence:image_off_subject", "no_ban_list"],
                        ["coherence:proof_repeated"]):
            s.add(db.SystemRun(tenant="baci", system_id=_sys.id,
                               stage="blocked", blocked_on=reasons))
        s.commit()
    backlog = dict(systems.blocked_reasons("baci"))
    ck("a real authoring gap IS counted", backlog.get("no_ban_list") == 1,
       str(backlog))
    ck("…and the coherence blocks beside it are NOT",
       not any(k.startswith("coherence:") for k in backlog), str(backlog))


# --------------------------------------------------------------------------
# Part three: the SAME contract on a system with no product cards and no
# imagery. If it only fits the email it is not a contract, it is a patch.
# --------------------------------------------------------------------------
def ads():
    print("\n— an ad commits to an entity; its proof must be about that entity —")
    c = coherence.commit("entity", "aqua-pitcher", label="Aqua pitcher",
                         proof_scopes=["aqua-pitcher", "aqua"])
    borrowed = coherence.parts(
        text="The Aqua pitcher. Holds a generous 32 cm footprint.",
        claims=[{"claim_id": "C7", "scope": "firenze-platter",
                 "text": "A generous 32 cm footprint."}])
    r = rules(coherence.review(c, borrowed))
    ck("another product's fact is not evidence about this one",
       "proof_off_subject" in r, str(sorted(r)))

    # A GROUP's claim IS true of its members. `kb.claims` walks the ancestor
    # chain deliberately, so a check that called this off-subject would refuse
    # exactly the case the data layer exists to serve.
    inherited = coherence.parts(
        text="The Aqua pitcher. Every Aqua piece is acrylic, so it travels.",
        claims=[{"claim_id": "C8", "scope": "aqua",
                 "text": "Every Aqua piece is acrylic."}])
    ck("…but the GROUP's claim is, and is not flagged",
       "proof_off_subject" not in rules(coherence.review(c, inherited)),
       str(sorted(rules(coherence.review(c, inherited)))))

    print("\n— a two-sentence ad is not destroyed by a weak word match —")
    short = coherence.parts(text="It does not shatter. Ever.")
    sev = {f["rule"]: f["severity"] for f in coherence.review(c, short)}
    ck("a short artifact that never names its subject ADVISES",
       sev.get("subject_absent") == "nudge", str(sev))
    long_miss = coherence.parts(text=("It does not shatter. " * 30))
    sev2 = {f["rule"]: f["severity"] for f in coherence.review(c, long_miss)}
    ck("…while a long one that never names it BLOCKS",
       sev2.get("subject_absent") == "block", str(sev2))

    print("\n— the live ad skill —")
    _ad = systems.find("baci", "ad_creative") or systems.create("baci", "ad_creative")
    with db.SessionLocal() as s:
        s.get(db.System, _ad.id).status = "live"
        s.commit()
    kb.add_entity("baci", "product", "aqua-pitcher", "Aqua pitcher",
                  description="Acrylic.", attributes={"availability": "in stock"})
    kb.add_claim("baci", "The Aqua pitcher pours without dripping.", "tested",
                 [], origin="human", status="active", entity_key="aqua-pitcher")
    skill_pack.draft_ad = lambda b, c, a, o: (
        "The Aqua pitcher pours without dripping.", "")
    r = skill.run("ad_copy", "baci", entity_key="aqua-pitcher", variants=1)
    it = (r.get("items") or [{}])[0]
    ck("an ad carries a commitment like everything else",
       (it.get("commitment") or {}).get("key") == "aqua-pitcher",
       str(it.get("commitment")))
    ck("…and a clean one passes", it.get("ok") is True, str(it.get("failures")))

    print("\n— an ad that spends its one proof twice —")
    skill_pack.draft_ad = lambda b, c, a, o: (
        "The Aqua pitcher pours without dripping. It really does pour "
        "without dripping.", "")
    r2 = skill.run("ad_copy", "baci", entity_key="aqua-pitcher", variants=1)
    i2 = (r2.get("items") or [{}])[0]
    ck("…is caught by the same rule the email is",
       i2.get("ok") is False
       and "coherence:proof_repeated" in {f["rule"] for f in (i2.get("failures") or [])},
       str([f["rule"] for f in (i2.get("failures") or [])]))


def main():
    unit()
    live()
    ads()
    print("\n" + ("all checks passed" if not _fail
                  else f"{len(_fail)} FAILED: " + "; ".join(_fail)))
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
