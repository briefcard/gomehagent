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

    print("\n— an unknown stage is refused by name, not silently ignored —")
    r3 = skill.run("ad_copy", "baci", entity_key="aqua-plate",
                   audience_key="hosts", variants=1, funnel_stage="middle-ish")
    ck("the run names the stages that exist",
       any("unknown funnel stage" in n for n in r3.get("notes") or []),
       "; ".join(r3.get("notes") or [])[:120])
    ck("…and still runs rather than failing over a typo",
       r3["status"] == "produced", r3["status"])

    print("\n— a run with no stage behaves exactly as it did before —")
    r4 = skill.run("ad_copy", "baci", entity_key="aqua-plate",
                   audience_key="hosts", variants=2)
    ck("no stage, no funnel notes", not any("funnel stage" in n
                                            for n in r4.get("notes") or []))
    ck("…and it still produces", r4["status"] == "produced")

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
