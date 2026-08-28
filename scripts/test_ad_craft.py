"""The ads get a craft brief, not only a list of prohibitions.

Owner, 2026-08-29: *"ads are completely terrible copy outputs that instead
need to be created by following rules Alex Hormozi and Sam Pilleros share
about ads that work in mid 2026."* The cause was findable in one read: the
entire creative instruction the drafter received was

    "You are writing one short ad for this brand … Do not introduce a second
     factual claim, a price, a material, an origin or a guarantee … Match the
     house voice … Two or three short lines."

100% prohibition, 0% craft. The validator is superb at stopping a draft that
is FALSE and says nothing about one that is DULL, and nothing else was
speaking to the drafter at all.

None of the rules are invented. They are the pipeline in
`.claude/skills/baci-ad-intelligence/references/copy-system.md` — Hormozi's
value equation for WHAT the copy must contain, Piliero's concept diversity and
hook discipline for HOW MANY and HOW DIFFERENT — which had existed for weeks
and which no generator had ever read. Same shape as a KB rule that never
reaches a validator.

    python3 scripts/test_ad_craft.py
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'ac.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import ad_craft, skill_pack  # noqa: E402

_fail: list[str] = []


def ck(label: str, cond, detail: str = "") -> None:
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


GOOD = ("Your Leo friend already owns 4 candles she did not ask for. "
        "15% off with FIRST15 — the cup made for her sign, shipped from "
        "Miami in 2 days.")


def main() -> int:
    print("— a good ad passes clean: a gate with false positives gets ignored —")
    f = ad_craft.review(body=GOOD, headline="Which sign is she?",
                        angle="gifting", offer="15% off",
                        levers=["dream_outcome", "time_delay", "effort"])
    sc = ad_craft.score(f)
    ck("no findings on a genuinely good ad", not f,
       "; ".join(x["rule"] for x in f))
    ck("…and it scores full marks and ships",
       sc["total"] == sc["of"] and sc["ship"], str(sc))

    print("\n— the hook: the first five words are the whole audition —")
    ck("an ad opening on an adjective is blocked",
       "hook_is_vague" in {x["rule"] for x in ad_craft.review(
           body="Beautiful tableware for every occasion. 4 pieces.",
           levers=["dream_outcome", "effort"])})
    ck("…and so is one that opens by announcing itself",
       "hook_is_an_announcement" in {x["rule"] for x in ad_craft.review(
           body="Introducing the Aqua set. 4 pieces, shatterproof.",
           levers=["effort", "likelihood"])},
       "nobody is waiting to be introduced to anything")

    print("\n— specificity: the words every competitor also uses —")
    vague = ad_craft.review(body="Elegant, timeless pieces. Elevate your table.",
                            levers=["dream_outcome", "effort"])
    rules = {x["rule"] for x in vague}
    ck("aesthetic adjectives are named", "vague_adjectives" in rules)
    ck("empty superlatives are named", "platitudes" in rules)
    ck("an ad with no number and no proof is nudged",
       "nothing_concrete" in {x["rule"] for x in ad_craft.review(
           body="The set your guests remember. Nothing to curate.",
           levers=["dream_outcome", "effort"])})

    print("\n— THE DEFECT THIS RULESET WAS BUILT FROM: a buried offer —")
    # copy-system.md found the offer at char 142–261 on four of five live
    # texts, past the ~125 characters Meta shows before "… more".
    buried = ("There is a certain kind of evening where the table matters "
              "more than the food, and the people stay long after the plates "
              "are cleared, which is the whole point. Anyway, 15% off with "
              "FIRST15.")
    found = ad_craft.review(body=buried, offer="15% off",
                            levers=["dream_outcome", "likelihood"])
    hit = next((x for x in found if x["rule"] == "offer_past_the_fold"), None)
    ck("an offer past the truncation is blocked", hit is not None)
    ck("…and the finding says WHERE it landed, not just that it is late",
       hit is not None and "character" in hit["detail"], str(hit))
    ck("an offer that is simply absent is a different, named finding",
       "offer_missing" in {x["rule"] for x in ad_craft.review(
           body=GOOD.replace("15% off with FIRST15 — ", ""), offer="15% off",
           levers=["dream_outcome", "time_delay"])})
    ck("the position is found however the case is written",
       ad_craft.offer_position("Now 15% OFF everything", "15% off") == 4)

    print("\n— the value equation: two levers or it is a mood board —")
    ck("an ad declaring one lever is blocked",
       "not_enough_value_levers" in {x["rule"] for x in ad_craft.review(
           body=GOOD, levers=["dream_outcome"])})
    ck("…and one declaring none is too",
       "not_enough_value_levers" in {x["rule"] for x in ad_craft.review(
           body=GOOD, levers=[])})
    ck("a lever that is not one of the four is discarded, not counted",
       ad_craft.levers_present("x", ["dream_outcome", "vibes"])
       == ["dream_outcome"])

    print("\n— urgency is held to the same rule email is —")
    ck("manufactured scarcity is blocked when no deadline exists",
       "urgency_without_a_deadline" in {x["rule"] for x in ad_craft.review(
           body="Last chance. 4 pieces, shatterproof, ships in 2 days.",
           levers=["effort", "time_delay"])})
    ck("…and permitted when there is a real one",
       "urgency_without_a_deadline" not in {x["rule"] for x in ad_craft.review(
           body="Last chance. 4 pieces, shatterproof, ships in 2 days.",
           levers=["effort", "time_delay"],
           urgency_backed_by="2026-09-30")})

    print("\n— gifting does not generalise, and is withheld on evidence —")
    ck("a venue gets the universal four",
       ad_craft.angles_for("event space, corporate buyers, capacity, parking")
       == ad_craft.UNIVERSAL_ANGLES)
    ck("a giftable brand gets gifting as well",
       "gifting" in ad_craft.angles_for("hosts who entertain; the perfect gift"))
    ck("every angle offered is one the ruleset actually briefs",
       all(a in ad_craft.ANGLES for a in
           ad_craft.angles_for("gift") + ad_craft.UNIVERSAL_ANGLES))

    print("\n— the drafter's reply parses forgivingly —")
    got = ad_craft.parse("HEADLINE: Which sign is she?\n"
                         "LEVERS: dream_outcome, time_delay\n---\n" + GOOD)
    ck("a well-formed reply splits into headline, levers and body",
       got["headline"] == "Which sign is she?"
       and got["levers"] == ["dream_outcome", "time_delay"]
       and got["body"] == GOOD, str(got)[:160])
    plain = ad_craft.parse("Just an ad with no markers at all.")
    ck("a reply ignoring the format keeps its AD and loses its headline",
       plain["body"] == "Just an ad with no markers at all."
       and plain["headline"] == "",
       "throwing the ad away over a formatting slip is the wrong trade")

    print("\n— and the generator actually RECEIVES all of this —")
    sysp = skill_pack._AD_SYSTEM
    for phrase, why in (
            ("first five words", "the hook rule"),
            ("value equation", "Hormozi's four levers"),
            ("125", "the truncation the offer must beat"),
            ("one idea", "the one-idea rule"),
            ("manufacture urgency", "the urgency rule")):
        ck(f"the brief carries {why}", phrase.lower() in sysp.lower(), phrase)
    ck("the angles the drafter is briefed on come from the ruleset",
       skill_pack._angle_brief("identity").startswith("Identity"),
       skill_pack._angle_brief("identity")[:60])

    # THE PROMPT ITSELF, not just the system string. `ad_prompt` was split out
    # of the API call precisely so this is assertable without an API key — a
    # brief nobody can read without spending money is a brief nobody checks,
    # and the guard `the_drafter_gets_a_craft_brief` was MISSED until this
    # existed.
    prompt = "\n".join(skill_pack.ad_prompt(
        {"rules": {"block": "RULES"}, "offer": "15% off", "deadline": ""},
        {"claim": "Dishwasher safe at 65 degrees.", "evidence": "lab report"},
        "identity", []))
    ck("the drafter is told HOW TO ANSWER, so levers can be declared at all",
       "HEADLINE:" in prompt and "LEVERS:" in prompt)
    ck("…and which angle it is writing, in the ruleset's own words",
       "Identity —" in prompt)
    ck("…and the offer, with the character budget it has to beat",
       "15% off" in prompt and str(ad_craft.TRUNCATION) in prompt)
    ck("…and that no deadline exists, when none does",
       "NO deadline" in prompt,
       "silence about a deadline is how a model invents one")
    with_dl = "\n".join(skill_pack.ad_prompt(
        {"rules": {"block": "R"}, "deadline": "2026-09-30"},
        {"claim": "c"}, "offer", []))
    ck("…and states the real one when there is", "2026-09-30" in with_dl)
    ck("`proof` is no longer an angle — it is a lever in every ad",
       "proof" not in ad_craft.ANGLES)

    print()
    if _fail:
        print(f"{len(_fail)} FAILED:")
        for f_ in _fail:
            print(f"  - {f_}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
