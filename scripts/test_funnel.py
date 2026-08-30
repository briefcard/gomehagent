"""Objections and situations are STRATEGY, not only grounding.

Owner, 2026-08-29: *"You should [be] using the objections and situations as
information for what people actually care about to create ads in different
parts of the funnel … the objections we identify, situations we have and
claims we make should inform our content strategy alongside the keywords."*
And, in the same breath, the constraint that makes it honest: *"IF they are
available of course."*

Before this, the knowledge base was read as a permission system. Claims were
the list of things a draft MAY assert and nothing chose between them on the
basis of who was reading; objections fed one ad angle and only the first row
of it; situations fed ads not at all — although `KbSituation.kind` has carried
`who_they_are | problem | doubt` since the schema was written, which is a
funnel nobody had read as one.

What this file pins is that the four stages read that data, that the stage
changes what the drafter is TOLD, and — the part the owner's caveat makes
load-bearing — that a missing input is NAMED rather than quietly replaced by
whatever else was lying around.

    python3 scripts/test_funnel.py
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'fn.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import (ad_craft, db, funnel, kb, kb_seed,  # noqa: E402
                 skill, skill_pack, systems, tenants)

# Offline: capabilities are credential-backed; stub at the boundary the way
# the ad-board suite already does.
_ALL = {c: True for c in tenants.CAPABILITIES}
tenants.capabilities = lambda key: dict(_ALL) if tenants.get(key) else \
    {c: False for c in tenants.CAPABILITIES}

_fail: list[str] = []


def ck(label: str, cond, detail: str = "") -> None:
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    db.init_db()
    tenants.seed()
    kb_seed.seed_all()
    systems.seed_from_tenants()

    # `ad_creative` has to exist for the account before a run of it can do
    # anything — same setup the ad-board suite uses.
    _row = systems.find("baci", "ad_creative") or systems.create(
        "baci", "ad_creative")
    # Filled and switched on, the way the ad-board suite does it — a system
    # that is merely declared cannot run, and this file is about what a run
    # says, not about the go-live gate.
    systems.update(_row.id, **{f: "declared for the test"
                               for f, _l, _h in systems.CONTRACT})
    # `ready()` blocks go-live on the KB the system declares it needs, and
    # ad_creative needs a tone. Setting it is fixture work, not a shortcut
    # round the gate — the gate is doing its job.
    kb.set_brand("baci", tone="direct, warm")
    _go = systems.update(_row.id, status="live", autonomy="shadow")
    assert _go.get("ok"), f"go-live refused: {_go}"

    print("— the stages read the data the schema already had —")
    ck("every stage names the knowledge it leads with",
       all(st["leads"] for st in funnel.STAGES.values()))
    ck("every angle a stage asks for is one the ad ruleset briefs",
       all(a in ad_craft.ANGLES for st in funnel.STAGES.values()
           for a in st["angles"]),
       "a stage asking for an angle nobody can write is a dead end")
    ck("only the bottom of the funnel asks for the sale",
       [k for k, v in funnel.STAGES.items() if v["asks"]] == ["bottom"],
       "pushing at awareness loses the reader you were about to earn")

    print("\n— the vocabulary takes what people actually type —")
    for raw, want in (("TOF", "awareness"), ("bof", "bottom"),
                      ("Middle of funnel", "consideration"),
                      ("sales", "bottom"), ("consideration", "consideration"),
                      ("nonsense", "")):
        ck(f"  {raw!r} → {want!r}", funnel.normalise(raw) == want,
           funnel.normalise(raw))

    print("\n— an account's OWN objections and situations reach the brief —")
    kb.add_situation("baci", "hosting-anxiety",
                     patterns=[["thrown", "together"]],
                     description="dreads the table looking thrown together",
                     kind="problem", origin="human")
    kb.add_objection("baci", "Will it survive the dishwasher?",
                     "Yes — tested at 65 degrees for 200 cycles.",
                     origin="human")
    con = funnel.inputs_for("baci", "consideration")
    text = funnel.brief(con)
    ck("consideration leads on objections", "objection" in con["leads"])
    ck("…and the drafter is shown the REAL hesitation, not the idea of one",
       "dishwasher" in text.lower(),
       "a drafter told 'lead with an objection' writes a generic objection ad")
    ck("…and the honest answer travels with it",
       "65 degrees" in text)
    ck("…and it is told not to invent a different one",
       "Do not invent a different one" in text)

    aware = funnel.inputs_for("baci", "awareness")
    atext = funnel.brief(aware)
    ck("awareness leads on the problem situation, not the product",
       "situation:problem" in aware["leads"], str(aware["leads"]))
    # The tag is normalised on the way in (hyphens dropped), so assert on
    # what the store actually holds rather than on what was typed.
    ck("…and quotes the account's own situation",
       "hostinganxiety" in atext.replace("-", ""),
       atext[:160])
    ck("…and says plainly that it does not ask for the sale",
       "does NOT ask for the sale" in atext)

    print("\n— 'if they are available': a gap is NAMED, never papered over —")
    # coverings has an empty knowledge base — the real state of the two most
    # local clients, which is why this is the case that matters.
    empty = funnel.inputs_for("coverings", "consideration")
    ck("a stage with no objections reports it as missing",
       "objection" in empty["missing"], str(empty["missing"]))
    ck("…in consequences, not field names",
       any("hesitates over" in n for n in empty["note"]),
       "; ".join(empty["note"])[:120])
    etext = funnel.brief(empty)
    ck("…and the drafter is told what it does not have",
       "DOES NOT HAVE" in etext)
    ck("…and told not to invent it",
       "Do not invent" in etext,
       "an invented hesitation is worse than a shorter ad")
    ck("a stage never silently downgrades to whatever is present",
       empty["leads"] != empty["missing"] and not empty["leads"],
       str(empty))

    print("\n— the stage narrows the angles to the ones that fit the reader —")
    ck("awareness never gets the offer angle",
       "offer" not in funnel.angles_for_stage("awareness",
                                              ad_craft.UNIVERSAL_ANGLES),
       "an offer-led ad at awareness asks a stranger to buy")
    ck("awareness never gets the objection angle",
       "objection" not in funnel.angles_for_stage("awareness",
                                                  ad_craft.UNIVERSAL_ANGLES),
       "it answers a hesitation the reader has not formed yet")
    ck("the bottom of the funnel does get both",
       set(funnel.angles_for_stage("bottom", ad_craft.UNIVERSAL_ANGLES))
       == {"objection", "offer"})
    ck("a stage never invents an angle this account may not use",
       "gifting" not in funnel.angles_for_stage(
           "awareness", ad_craft.UNIVERSAL_ANGLES))

    print("\n— and the ad run actually uses it —")
    r = skill.run("ad_copy", "baci", entity_key="aqua-plate",
                  audience_key="hosts", variants=2, funnel_stage="bottom",
                  offer="15% off")
    notes = " ".join(r.get("notes") or [])
    ck("the run produced at this stage", r["status"] == "produced",
       f"{r['status']} {r.get('blocked_on')}")
    ck("the run says where the reader is", "funnel stage: Bottom" in notes,
       notes[:100])
    # THE RUN STATES ITS OWN ANGLES. Reading them back out of the artifact
    # store made this a test of the store's shape; the run reports them, and
    # that report is the thing a person actually sees.
    def _in_play(res):
        said = next((n for n in res.get("notes") or []
                     if n.startswith("angles in play")), "")
        return [a.strip(" .") for a in
                said.split(":", 1)[-1].split("(")[0].split(",") if a.strip()]

    angles = _in_play(r)
    ck("…and every angle in play is one that stage permits",
       bool(angles)
       and all(a in funnel.STAGES["bottom"]["angles"] for a in angles),
       str(angles))

    r2 = skill.run("ad_copy", "baci", entity_key="aqua-plate",
                   audience_key="hosts", variants=2, funnel_stage="awareness")
    angles2 = _in_play(r2)
    ck("a different stage produces DIFFERENT angles — the stage is not "
       "decoration", bool(angles2) and set(angles2) != set(angles),
       f"bottom={angles} awareness={angles2}")
    ck("…and none of them asks for the sale at awareness",
       "offer" not in angles2, str(angles2))

    print("\n— EMAIL derives its stage; it does not get a fourth knob —")
    # `segments.warmth` already answers "does this cohort know us" and the
    # intent already answers "does this send ask". A `funnel_stage` parameter
    # beside them would be a third vocabulary for a thing decided twice.
    ck("a giving send to a cold list is awareness",
       funnel.stage_from(warmth="cold", asks=False) == "awareness")
    ck("a giving send to a warm list is consideration",
       funnel.stage_from(warmth="warm", asks=False) == "consideration")
    ck("any send that ASKS is bottom of funnel, whoever it is addressed to",
       funnel.stage_from(warmth="cold", asks=True) == "bottom"
       and funnel.stage_from(warmth="warm", asks=True) == "bottom",
       "a cold ask is not an awareness email with a button on it")
    ck("an unknown warmth is treated as cold, the safer read",
       funnel.stage_from(warmth="", asks=False) == "awareness")

    cold = funnel.brief(funnel.inputs_for("baci", "awareness"))
    hot = funnel.brief(funnel.inputs_for("baci", "bottom", offer="15% off"))
    ck("the two ends of the funnel brief the drafter DIFFERENTLY",
       cold != hot and "Awareness" in cold and "Bottom" in hot)
    ck("the cold one leads on the situation, not the hesitation",
       "SITUATIONS" in cold and "HESITATIONS" not in cold)
    ck("the asking one leads on the hesitation and names the offer",
       "HESITATIONS" in hot and "OFFER TO CLOSE ON" in hot)

    print("\n— THE BLOG derives its stage from the keyword's own intent —")
    from app import keywords as kwmod
    for phrase, want in (("how to set a dinner table", "awareness"),
                         ("best melamine dinnerware vs acrylic", "consideration"),
                         ("buy acrylic dinnerware", "bottom")):
        got = funnel.stage_from_keyword(
            kwmod.classify_intent(phrase, kwmod.brand_tokens_for("baci")))
        ck(f"  {phrase!r} → {want}", got == want, got)
    ck("a brand search is somebody who already knows you",
       funnel.stage_from_keyword("navigational") == "interest")
    ck("an unknown intent falls to awareness — the stage that assumes least",
       funnel.stage_from_keyword("") == "awareness"
       and funnel.stage_from_keyword("nonsense") == "awareness")
    ck("every intent the keyword layer can emit maps to a real stage",
       all(funnel.stage_from_keyword(lbl) in funnel.STAGES
           for lbl, _m in kwmod.INTENT_MARKERS),
       "a marker added to the keyword layer must not fall off the funnel")

    print("\n— an unknown stage is refused by name, not silently ignored —")
    r3 = skill.run("ad_copy", "baci", entity_key="aqua-plate",
                   audience_key="hosts", variants=1, funnel_stage="middle-ish")
    ck("the run names the stages that exist",
       any("unknown funnel stage" in n for n in r3.get("notes") or []),
       "; ".join(r3.get("notes") or [])[:120])
    ck("…and still runs rather than failing over a typo",
       r3["status"] == "produced", r3["status"])

    print("\n— a batch tests one idea, or says it is testing none —")
    r7 = skill.run("ad_copy", "baci", entity_key="aqua-plate",
                   audience_key="hosts", variants=2,
                   positioning="Certified food-safe, not price, is the reason")
    ck("the stated hypothesis is noted",
       any(n.startswith("testing:") for n in r7.get("notes") or []),
       "; ".join(r7.get("notes") or [])[:140])
    with db.SessionLocal() as _s:
        _rows = [o for o in _s.query(db.Output)
                 .filter(db.Output.positioning != "").all()]
    ck("…and recorded on EVERY variant, not once per batch",
       len(_rows) >= 2 and {o.positioning for o in _rows} ==
       {"Certified food-safe, not price, is the reason"},
       f"{len(_rows)} rows: {sorted({o.positioning for o in _rows})}",)

    r8 = skill.run("ad_copy", "baci", entity_key="aqua-plate",
                   audience_key="hosts", variants=2)
    ck("with none stated the run suggests ones the data supports",
       any("worth testing" in n for n in r8.get("notes") or []),
       "; ".join(n for n in (r8.get("notes") or []) if "worth" in n)[:160])
    ck("…and says the batch is testing nothing",
       any("tests no stated positioning" in n for n in r8.get("notes") or []),
       "five drafts that argue different things cannot be compared")

    print("\n— every suggestion is derived, and the gaps are named —")
    from app import funnel as _fn
    _g = _fn.proposals("baci", limit=4)
    ck("proposals carry the triple",
       all({"audience", "stage", "positioning"} <= set(p) for p in _g["proposals"]),
       str(_g["proposals"][:1]))
    ck("…and say why the data supports each",
       all(p.get("why") for p in _g["proposals"]))
    ck("…and how often it has already been tested",
       all("tested" in p for p in _g["proposals"]),
       "a positioning run four times is a repetition, not a suggestion")
    # DERIVED FROM THE STATE, not pinned to one gap: earlier tests in this
    # file add objections to baci, so asserting a fixed gap would pass or
    # fail on the order the checks happen to run in.
    _kinds = {getattr(r, "kind", "") for r in kb.situation_rows("baci")}
    _expect = []
    if not kb.objections("baci"):
        _expect.append("no objections on file")
    if "problem" not in _kinds:
        _expect.append("no situation is filed as a `problem`")
    ck("every gap it names is genuinely missing",
       all(any(e in g for g in _g["gaps"]) for e in _expect),
       f"expected {_expect}, got {_g['gaps']}")
    ck("…and nothing present is reported as missing",
       not (kb.objections("baci")
            and any("no objections" in g for g in _g["gaps"])),
       "a gap that is not a gap trains people to ignore the list")

    # THE GAP LOGIC ITSELF, on an account that genuinely lacks the sources —
    # by the time the checks above run, baci has been given both, so they
    # exercise the correspondence and not the naming.
    _bare = funnel.proposals("nobody-at-all", limit=3)
    ck("an account with nothing on file gets no invented proposals",
       _bare["proposals"] == [],
       "a suggestion built from nothing is the one thing this must not do")
    ck("…and is told what to fill in first",
       any("no objections on file" in g for g in _bare["gaps"])
       and any("no audiences" in g for g in _bare["gaps"]),
       str(_bare["gaps"]))

    print("\n— the whole audience row, not two fields of it —")
    from app import funnel as fn, kb as _kb
    _p = fn.inputs_for("baci", "consideration",
                       audiences=_kb.audiences("baci"), entities=[])
    _b = fn.brief(_p)
    ck("the buyer's own vocabulary reaches the drafter",
       "audience_vocabulary" in _p["have"]
       and "THE WORDS THIS BUYER USES" in _b,
       "KbAudience has carried `vocabulary` since the schema was written and "
       "every generator read `name` and `pains`")
    ck("…and what makes them act now",
       "WHAT MAKES THIS BUYER ACT NOW" in _b or
       "buying_trigger" not in _p["have"])

    # ...AND IT ARRIVES BY THE REAL ROUTE. The two checks above hand
    # `audiences` straight to `inputs_for`, which proves the funnel can read
    # an audience and NOT that any drafter is ever given one. `resolve` never
    # wrote `bundle["audiences"]`, and `inputs_for` — unlike claims and
    # objections — has no fallback fetch, so the live value was `None` in the
    # ad, the email and the article alike while this section stayed green.
    # Asserted on the BUNDLE, which is what the drafters actually read.
    from app import resolve as _rs
    _bundle = _rs.resolve("baci", system="campaign_email", tier=3)
    _auds = _bundle.get("audiences") or []
    ck("the bundle CARRIES the audience — the route the drafter reads",
       bool(_auds) and any(a.get("vocabulary") for a in _auds),
       f"bundle keys: {sorted(_bundle)[:12]}")
    _live = fn.inputs_for("baci", "consideration",
                          audiences=_bundle.get("audiences"), entities=[])
    ck("  so the live path has the buyer's words, not just the hand-fed one",
       "audience_vocabulary" in _live["have"], str(sorted(_live["have"])))

    print("\n— the owner's own input reaches the drafter —")
    # `offer` and `deadline` are OWNER_INPUT: a person fills them so that a
    # generator never invents a discount or a deadline. That is defeated
    # entirely if the field a person filled does not arrive, which is what
    # happened to `campaign_email` — it READ `offer` and never declared it, so
    # `run` refused the parameter and every bottom-of-funnel send reported a
    # gap nothing could close. Asserted through `skill.run`, the surface.
    _saw = {}
    _real_ad = skill_pack.draft_ad
    skill_pack.draft_ad = lambda bundle, claim, angle, objections: (
        _saw.update(offer=bundle.get("offer"),
                    deadline=bundle.get("deadline"),
                    audiences=bundle.get("audiences")) or ("Plate.", "model"))
    skill.run("ad_copy", "baci", entity_key="aqua-plate", variants=1,
              offer="15% off through Sunday", deadline="Sunday 11pm")
    skill_pack.draft_ad = _real_ad
    ck("an offer typed by the owner reaches the ad drafter",
       _saw.get("offer") == "15% off through Sunday", str(_saw.get("offer")))
    ck("  and so does the deadline behind any urgency",
       _saw.get("deadline") == "Sunday 11pm", str(_saw.get("deadline")))
    ck("  and the ad drafter is given the audience too",
       bool(_saw.get("audiences")), str(bool(_saw.get("audiences"))))

    _crow = systems.find("baci", "campaign_email") or \
        systems.create("baci", "campaign_email")
    with db.SessionLocal() as _s:
        _s.get(db.System, _crow.id).status = "live"
        _s.commit()
    _saw2 = {}
    _real_c = skill_pack.draft_campaign
    skill_pack.draft_campaign = lambda bundle, seg, goal, craft=None: (
        _saw2.update(offer=bundle.get("offer"),
                     have=sorted((craft or {}).get("funnel", {}).get("have", {})))
        or ({"subject": "S", "preheader": "p", "body_html": "<p>x</p>",
             "claim_ids": [], "cta_label": "Shop",
             "cta_url": "https://x/s"}, "model", ""))
    _r = skill.run("campaign_email", "baci", segment="reorder_due",
                   intent="offer", offer="15% off through Sunday")
    skill_pack.draft_campaign = _real_c
    ck("the campaign accepts an offer instead of refusing the parameter",
       _r["status"] == "produced", str(_r.get("blocked_on")))
    ck("  the offer reaches the email drafter",
       _saw2.get("offer") == "15% off through Sunday", str(_saw2.get("offer")))
    ck("  and the bottom-of-funnel brief stops reporting a gap it cannot close",
       "offer" in (_saw2.get("have") or []), str(_saw2.get("have")))

    print("\n— search phrases are scoped to the reader —")
    from app import keywords as _kw
    _kw.upsert("baci", "what is melamine", volume=100)
    _kw.upsert("baci", "buy melamine dinner plates", volume=100)
    _bot = fn.inputs_for("baci", "bottom", entities=[])
    _aw = fn.inputs_for("baci", "awareness", entities=[])
    ck("a bottom-of-funnel brief prefers transactional language",
       "buy melamine dinner plates" in (_bot["have"].get("keyword_stage_fit") or []),
       str(_bot["have"].get("keyword_stage_fit")))
    ck("…and an awareness brief prefers the question",
       "what is melamine" in (_aw["have"].get("keyword_stage_fit") or []),
       str(_aw["have"].get("keyword_stage_fit")))
    ck("a stage with no matching phrase still gets the account's language",
       bool(fn.inputs_for("baci", "interest", entities=[])["have"].get("keyword")),
       "an empty block would read as 'no search data', which is a different "
       "and untrue thing")

    # THIS CONTRACT CHANGED DELIBERATELY, 2026-08-29. It used to read "a run
    # with no stage behaves exactly as it did before" and asserted that no
    # funnel note appeared — which was true and was the defect: without the
    # knob NO plan was built, so the default run, the one that actually
    # happens, got no situations, no objections-as-strategy, no audience
    # vocabulary and no search phrases. Owner: "how do we make sure to take
    # advantage of our context / data layer … to generate the best result."
    #
    # The half of the old promise worth keeping is asserted instead: a DERIVED
    # stage briefs but does not BIND. It supplies the knowledge; it does not
    # narrow the angle set, because an inference is not a decision.
    print("\n— with no stage the brief is still built, and says it inferred —")
    r4 = skill.run("ad_copy", "baci", entity_key="aqua-plate",
                   audience_key="hosts", variants=2)
    ck("the data layer reaches the drafter anyway",
       any("funnel stage (derived" in n for n in r4.get("notes") or []),
       "; ".join(r4.get("notes") or [])[:160])
    ck("…and says it was inferred, not chosen",
       any("angles not narrowed" in n for n in r4.get("notes") or []),
       "a stage nobody chose must not read as one somebody did")
    ck("…and it still produces", r4["status"] == "produced")

    angles_of = lambda r: {v.get("angle") for v in (r.get("variants") or [])}
    r5 = skill.run("ad_copy", "baci", entity_key="aqua-plate",
                   audience_key="hosts", variants=4)
    r6 = skill.run("ad_copy", "baci", entity_key="aqua-plate",
                   audience_key="hosts", variants=4, funnel_stage="bottom")
    ck("an inference leaves the angle set alone",
       len(angles_of(r5)) >= len(angles_of(r6)) or not angles_of(r6),
       f"derived={sorted(x for x in angles_of(r5) if x)} "
       f"chosen={sorted(x for x in angles_of(r6) if x)}")

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
