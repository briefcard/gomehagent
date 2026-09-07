"""An ad is about the thing the owner chose, and a refusal is not an ad.

Owner, 2026-09-07, pasting an "ad" for a Sagrada Família head that opened
*"I need to stop here and be honest with you"*, asked whether shatterproof was
*"cleared for the Melamine set specifically, or only the Baroque & Rock
acrylics"*, and ended *"Which of these can you confirm?"* — then: *"Just so
we're clear, I choose a Sagrada familia head product. Why is joke being
referenced? Why is baroque & rock? Your wiring is all messed up."*

THE WIRING. `resolve.resolve` opens its catalogue branch whenever an entity is
named and, with no buyer requirements to rank on, `kb.match_entities` hands
back the catalogue's first rows in whatever order they sort. A 2026-08 fix
made the NAMED entity lead that list — and kept the strangers behind it. So
`bundle["entities"]` for a Sagrada ad was Sagrada plus two alphabetical
neighbours; the panel printed them as ADVERTISED, the drafter got them under
"What is being advertised", and the reviewers — quite reasonably — wrote a
brief about products that were never chosen. The zodiac cup's "18-piece gift"
(2026-09-06) arrived by the same path.

AND THE REFUSAL. `ad_craft.parse` is forgiving by design: a reply with no
markers is all body. A model that writes the owner a message instead of an
ad therefore had that message filed as the variant, `basis=model`, and shown
on the board as copy.

Two facts, each with its guard: a named entity brings NO strangers (the
"also features" are named too, and nothing else comes); a reply that speaks
to the operator is a DECLINE — not filed, said on the run and on the board
with what the drafter asked for.

Run: python3 scripts/test_the_ad_is_about_the_thing_you_chose.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'chosen.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import ad_craft, db, kb, skill, skill_pack, systems, tenants, web  # noqa: E402

KEY = "s3cret"
_fail: list[str] = []
# The system goes live only when the account can act (ads or commerce) —
# granted here the way `test_ad_panel` grants it, because this suite is
# about what the brief carries, not about readiness.
_ALL = {c: True for c in tenants.CAPABILITIES}
tenants.capabilities = lambda key: dict(_ALL) if tenants.get(key) else \
    {c: False for c in tenants.CAPABILITIES}


def ck(label: str, cond, detail: str = "") -> None:
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


THE_REFUSAL = """I need to stop here and be honest with you.

The brief instructs me not to write this ad without a confirmed product detail beyond "sold as a set of 6." Both reviewers made that call, and the brief ratifies it.

**What I need before I can write this honestly:**

- **Material/function:** Is "shatterproof and suited to indoor & outdoor use" cleared for the Melamine set specifically, or only the Baroque & Rock acrylics?
- **Visual signature:** Is there a specific pattern, colour, or finish detail on the white Joke set that's approved to name?

Which of these can you confirm?"""

A_REAL_AD = ("HEADLINE: A head for the table\nLEVERS: dream_outcome, effort\n---\n"
             "Six ceramic heads, one conversation that starts itself.\n\n"
             "Set them down and watch who talks first.\n\nShop the set.")

A_BARE_AD_THAT_ASKS = ("Which host are you — the one who plans, or the one who "
                       "pours?\n\nEither way, the table is set.\n\nShop it.")

# A REAL AD whose copy happens to use the operator's own words — markers make
# it an ad, whatever it says to its reader.
A_REAL_AD_IN_OPERATOR_WORDS = (
    "HEADLINE: Can you confirm?\nLEVERS: dream_outcome, likelihood\n---\n"
    "Can you confirm you're the host who plans? Let me know which sign is "
    "yours.\n\nSix heads, one table.\n\nShop the set.")


class FakePanel:
    def __init__(self):
        self.bundles: list = []
        self.concepts: list = []

    def __call__(self, bundle, concepts):
        self.bundles.append(bundle)
        self.concepts.append(list(concepts))
        return ({"variants": {c["n"]: {"hormozi": "h", "piliero": "p",
                                       "brief": f"BRIEF-{c['n']}"} for c in concepts},
                 "batch": {"piliero": "distinct", "verdict": "distinct"}}, "")


class FakeDraft:
    def __init__(self, replies: list[str]):
        self.replies, self.calls = list(replies), []

    def __call__(self, bundle, claim, angle, objections):
        self.calls.append((bundle, claim, angle, objections))
        reply = self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]
        return reply, ""


def contract(row, autonomy):
    systems.update(row.id, **{f: "declared for the test" for f, _l, _h in systems.CONTRACT})
    systems.update(row.id, status="live", autonomy=autonomy)
    return systems.get(row.id)


def main() -> int:
    db.init_db()
    tenants.seed()
    kb.ensure_brand("baci", "Baci")
    kb.set_brand("baci", positioning="Italian-designed tableware.", tone="direct, warm")
    kb.add_banned("baci", "hand-decorated")
    for c, ev in (("Dishwasher safe at 65 degrees.", "lab report"),
                  ("Designed in Milan.", "brand file"),
                  ("Ships within two days.", "ops log")):
        kb.add_claim("baci", c, ev, [], origin="human", status="active")
    kb.add_audience("baci", "hosts", "Hosts who entertain",
                    ["dull tables"], ["colour", "set"], origin="human")
    # THE CATALOGUE, in the order it sorts: the two neighbours the owner saw
    # in their ad, and the thing they actually chose.
    kb.add_entity("baci", "product", "baroque-rock-tumbler", "Baroque & Rock tumbler",
                  description="Shatterproof acrylic, suited to indoor and outdoor use.",
                  attributes={"material": "acrylic"}, origin="human")
    kb.add_entity("baci", "product", "joke-melamine-18", "Joke Melamine 18-piece set",
                  description="An 18-piece set in white melamine — durable and dishwasher-safe.",
                  attributes={"material": "melamine", "pieces": "18"}, origin="human")
    kb.add_entity("baci", "product", "sagrada-head", "Sagrada Família head",
                  description="A ceramic head inspired by Gaudí's Sagrada Família, "
                              "glazed by hand, 24 cm tall. Sold as a set of 6.",
                  attributes={"material": "ceramic", "height_cm": "24", "set": "6"},
                  origin="human")
    row = systems.find("baci", "ad_creative") or systems.create("baci", "ad_creative")
    contract(row, autonomy="approve_all")
    skill_pack.panel_check = lambda b, d: ({}, "")

    print("— ENTRY: the ad is briefed on the product the owner chose, and nothing else —")
    fp, fd = FakePanel(), FakeDraft([A_REAL_AD])
    skill_pack.panel_ad, skill_pack.draft_ad = fp, fd
    r = skill.run("ad_copy", "baci", entity_key="sagrada-head", audience_key="hosts",
                  variants=2)
    ck("the run produced", r.get("status") == "produced",
       f"{r.get('status')} {r.get('blocked_on')} {r.get('notes', [])[:2]}")
    keys = [[e.get("key") for e in (b.get("entities") or [])] for b in fp.bundles]
    ck("the panel is handed the chosen product and NO strangers",
       keys and all(k == ["sagrada-head"] for k in keys), str(keys))
    shown = "\n".join(ad_craft.panel_prompt(fp.bundles[0], fp.concepts[0]))
    ck("  ADVERTISED names Sagrada and not Joke, not Baroque & Rock",
       "Sagrada" in shown and "Joke" not in shown and "Baroque" not in shown,
       shown[shown.find("ADVERTISED"):][:160])
    ck("  and the panel sees the product's own facts, so its brief cannot ask for one",
       "material: ceramic" in shown and "set: 6" in shown,
       shown[shown.find("ADVERTISED"):][:200])
    b0, c0, a0, o0 = fd.calls[0]
    told = "\n".join(skill_pack.ad_prompt(b0, c0, a0, o0))
    sect = told[told.find("What is being advertised"):told.find("Who is reading")
                if "Who is reading" in told else None]
    ck("the drafter's 'What is being advertised' is the chosen product alone",
       "Sagrada" in sect and "Joke" not in sect and "Baroque" not in sect, sect[:200])
    ck("  and carries the product's OWN catalogue facts as the confirmed details",
       "material: ceramic" in sect and "set: 6" in sect, sect[:240])
    fp2, fd2 = FakePanel(), FakeDraft([A_REAL_AD])
    skill_pack.panel_ad, skill_pack.draft_ad = fp2, fd2
    r2 = skill.run("ad_copy", "baci", entity_key="sagrada-head",
                   entity_keys="joke-melamine-18", audience_key="hosts", variants=1)
    keys2 = [e.get("key") for e in (fp2.bundles[0].get("entities") or [])]
    ck("an 'also features' entity is named too — hero first, then it, nothing else",
       r2.get("status") == "produced" and keys2 == ["sagrada-head", "joke-melamine-18"],
       str(keys2))
    fp3, fd3 = FakePanel(), FakeDraft([A_REAL_AD])
    skill_pack.panel_ad, skill_pack.draft_ad = fp3, fd3
    r3 = skill.run("ad_copy", "baci", audience_key="hosts", variants=1)
    ck("with no entity chosen the ad is brand-wide and the catalogue is not guessed at",
       r3.get("status") == "produced" and not (fp3.bundles[0].get("entities") or []),
       str([e.get("key") for e in (fp3.bundles[0].get("entities") or [])]))

    print("\n— DECLINE: a reply that speaks to the operator is not filed as copy —")
    ck("the pasted refusal is read as a decline, with what it asked",
       "confirm" in ad_craft.declined(THE_REFUSAL).lower()
       and "shatterproof" in ad_craft.declined(THE_REFUSAL).lower(),
       ad_craft.declined(THE_REFUSAL)[:120])
    ck("  a real ad is never read as one — markers make it an ad",
       ad_craft.declined(A_REAL_AD) == "")
    ck("  nor is a bare caption that merely asks the reader a question",
       ad_craft.declined(A_BARE_AD_THAT_ASKS) == "")
    ck("  nor a real ad whose copy uses the operator's own words — markers win",
       ad_craft.declined(A_REAL_AD_IN_OPERATOR_WORDS) == "",
       ad_craft.declined(A_REAL_AD_IN_OPERATOR_WORDS)[:80])
    ck("  and an empty reply is nothing, not a decline", ad_craft.declined("") == "")
    fp4, fd4 = FakePanel(), FakeDraft([THE_REFUSAL, A_REAL_AD])
    skill_pack.panel_ad, skill_pack.draft_ad = fp4, fd4
    r4 = skill.run("ad_copy", "baci", entity_key="sagrada-head", audience_key="hosts",
                   variants=2)
    bodies = [str(i.get("body") or "") for i in (r4.get("items") or [])]
    ck("the refusal is NOT a variant — one ad was filed, not two",
       r4.get("status") == "produced" and len(bodies) == 1
       and "stop here" not in bodies[0], f"{len(bodies)} item(s): {[b[:40] for b in bodies]}")
    notes = " ".join(str(n) for n in (r4.get("notes") or []))
    ck("  the run says the drafter declined and what it asked for",
       "declined" in notes.lower() and "confirm" in notes.lower(), notes[:200])
    anchor = (r4.get("items") or [{}])[0].get("output_id") or ""
    with db.SessionLocal() as s:
        art = (s.query(db.ArtifactBody).filter(db.ArtifactBody.output_id == anchor).first())
        doc = json.loads(art.body) if art else {}
    ck("  the board record carries the decline beside its variants",
       doc.get("kind") == "ad_batch" and len(doc.get("variants") or []) == 1
       and (doc.get("declined") or [{}])[0].get("n") == 1
       and "confirm" in str((doc.get("declined") or [{}])[0].get("asked") or "").lower(),
       str(doc.get("declined"))[:160])
    c = TestClient(web.app, base_url="https://testserver")
    page = c.get(f"/admin/work/{anchor}?key={KEY}").text
    ck("  and the board SAYS it, with the ask, where the variants are judged",
       "declined" in page.lower() and "Which of these can you confirm" in page,
       "the board is where the owner reads this; a note in a run log is not")
    fp5, fd5 = FakePanel(), FakeDraft([THE_REFUSAL])
    skill_pack.panel_ad, skill_pack.draft_ad = fp5, fd5
    r5 = skill.run("ad_copy", "baci", entity_key="sagrada-head", audience_key="hosts",
                   variants=2)
    ck("a batch where every draft declined produces nothing and says why",
       not (r5.get("items") or []) and "declined" in
       " ".join(str(n) for n in (r5.get("notes") or [])).lower()
       and "declined" in str(r5.get("summary") or "").lower(),
       f"{r5.get('status')} — {str(r5.get('summary'))[:120]}")

    print()
    if _fail:
        print(f"{len(_fail)} FAILED:\n  " + "\n  ".join(_fail))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
