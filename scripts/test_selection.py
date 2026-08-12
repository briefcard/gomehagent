"""Selection must reach the thing being sold, and must never overstate a fit.

The bug this file exists to prevent: a 200-seat room was ranked first for a
party of 220 seated, because a keyword match on the word "seated" (which
appeared only in the ATTRIBUTE NAME `seated_capacity`) outranked an actual
capacity comparison. That is a wrong venue in a real email.

    python3 scripts/test_selection.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'sel.db')}"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import brief, db, kb, kb_seed, tenants  # noqa: E402

_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _names(rows, fitting=True):
    return [r["name"] for r in rows if r["fits"] is fitting]


def main() -> int:
    db.init_db()
    tenants.seed()
    kb.seed_agency()
    kb_seed.seed_all()

    print("\n— capacity is compared, not keyword-matched —")
    seated = kb.match_entities("ironside", {"headcount": 220, "seated": True,
                                            "keywords": ["seated", "catering"]}, limit=8)
    ck("a room that seats 200 is never offered for 220",
       "Glassbox" not in _names(seated) and "Gallery 62" not in _names(seated))
    ck("rooms that do seat 220 are offered",
       set(_names(seated)) == {"Event Space", "Ironsbend"}, str(_names(seated)))
    ck("the near miss is still reported, marked as short",
       "Glassbox" in _names(seated, fitting=False))
    ck("the reason is stated in the entity's own numbers",
       "covers 220" in seated[0]["why"], seated[0]["why"])

    print("\n— the same number against a different requirement —")
    standing = kb.match_entities("ironside", {"headcount": 220, "standing": True}, limit=8)
    ck("standing 220 opens rooms that seated 220 excluded",
       "Glassbox" in _names(standing))
    ck("smallest sufficient room ranks first (least waste)",
       standing[0]["name"] == "Glassbox", standing[0]["why"])

    print("\n— refusing is an answer —")
    huge = kb.match_entities("ironside", {"headcount": 600, "seated": True}, limit=8)
    ck("nothing on the campus fits 600 seated",
       not any(r["fits"] is True for r in huge))
    ck("every measured option says why it doesn't",
       all("short of 600" in r["why"]
           for r in huge if r["basis"] == "requirement"))
    ck("and the unmeasurable ones are not counted as refusals",
       all("cannot be judged" in r["why"]
           for r in huge if r["basis"] == "unknown"))

    print("\n— what could not be measured is reported, not deleted —")
    unknown = [r for r in seated if r["fits"] is None]
    ck("entities with no such attribute are surfaced as unknown",
       {"Lemon Grove", "Virtual Set"} <= {r["name"] for r in unknown},
       str([r["name"] for r in unknown]))
    ck("an unknown says it could not be judged",
       all("cannot be judged" in r["why"] for r in unknown))
    ck("unknown outranks known-too-small",
       [r["fits"] for r in seated] == sorted(
           [r["fits"] for r in seated],
           key=lambda f: {True: 0, None: 1, False: 2}[f]))

    print("\n— keyword mode when no number is stated —")
    kw = kb.match_entities("ironside", {"keywords": ["led", "production"]}, limit=3)
    ck("the production space surfaces for an AV request",
       kw and kw[0]["name"] == "Virtual Set", kw[0]["why"] if kw else "")
    ck("a keyword match NEVER asserts a fit — relevance is not satisfaction",
       all(r["fits"] is None and r["basis"] == "keyword" for r in kw))

    print("\n— a word that matches everything carries no information —")
    for k, n, d in [("s1", "Aqua set", "colourful italian set"),
                    ("s2", "Rosa set", "colourful italian set"),
                    ("s3", "Verde set", "colourful italian set"),
                    ("s4", "Mamma plate", "colourful pattern plate")]:
        kb.add_entity("baci", "product", k, n, description=d)
    sat = kb.match_entities("baci", {"keywords": ["colourful", "zodiac"]}, limit=6)
    ck("the saturating word is dropped, the discriminating one is kept",
       all("zodiac" in r["why"] for r in sat) and sat,
       str([(r["name"], r["why"]) for r in sat]))
    ck("so a generic word cannot drag in the whole catalogue", len(sat) <= 2,
       f"{len(sat)} returned")

    print("\n— vocabulary and decisions are per tenant —")
    ck("ironside has its own situation tags",
       "venue_enquiry" in kb.situations("ironside")
       and "margin_problem" not in kb.situations("ironside"))
    ck("baci has different ones",
       "gifting" in kb.situations("baci")
       and "venue_enquiry" not in kb.situations("baci"))
    ck("agency keeps the shared set", "margin_problem" in kb.situations("agency"))
    ck("a claim tagged outside the tenant vocabulary is refused",
       "Unknown tags" in kb.add_claim("ironside", "x", "y", ["margin_problem"]))

    print("\n— the assembler end to end —")

    def stub(_s, _u):
        return json.dumps({
            "contact_name": "Dana", "company": "Northwind", "domain": "",
            "source": "inbound_form", "stage": "first_contact",
            "audience_key": "unknown",
            "verbatim_ask": "We need a venue for 220 guests seated in March",
            "voiced_objection": "",
            "keywords": ["venue", "guests", "seated", "March"],
            "requirements": {"headcount": 220, "seated": True, "date": "March"}})

    kb.add_objection("ironside", "Is the date available?", "We hold dates 5 business days.")
    kb.set_brand("ironside", tone="direct, warm, practical")
    b = brief.assemble("ironside", "venue for 220 seated in March",
                       "dana@northwind.com", model_fn=stub).to_dict()
    ck("situations fire on a venue enquiry", "capacity_fit" in b["situations"],
       str(b["situations"]))
    ck("the constraint is in the tenant's words",
       "headcount" in b["constraint"], b["constraint"])
    ck("the ask is the tenant's, not the agency's",
       "walkthrough" in b["ask"], b["ask"])
    ck("the brief carries rooms that actually fit",
       [m["name"] for m in b["matches"] if m["fits"]] == ["Event Space", "Ironsbend"],
       str([m["name"] for m in b["matches"]]))

    print("\n— unknowns become answerable questions —")

    def stub_big(_s, _u):
        return json.dumps({
            "contact_name": "Dana", "company": "NW", "domain": "",
            "source": "inbound_form", "stage": "first_contact",
            "audience_key": "unknown",
            "verbatim_ask": "350 guests seated in May", "voiced_objection": "",
            "keywords": ["guests", "seated"],
            "requirements": {"headcount": 350, "seated": True}})

    b2 = brief.assemble("ironside", "350 seated", "d@nw.com",
                        model_fn=stub_big).to_dict()
    ck("an enquiry nothing fits reports what fell short", bool(b2["unmet"]),
       str(b2["unmet"][:1]))
    gaps = kb.unknowns("ironside")
    ck("and the unmeasurable options are logged as gaps", len(gaps) >= 2,
       str([(g.entity_name, g.attribute) for g in gaps]))

    brief.assemble("ironside", "350 seated", "d@nw.com", model_fn=stub_big)
    ck("a repeat enquiry increments the same gap, not a new row",
       len(kb.unknowns("ironside")) == len(gaps)
       and max(int(g.hits) for g in kb.unknowns("ironside")) == 2)

    # A gap that cost nothing must not be logged: plenty of rooms seat 100.
    before = len(kb.unknowns("ironside"))

    def stub_small(_s, _u):
        return json.dumps({
            "contact_name": "D", "company": "", "domain": "",
            "source": "inbound_form", "stage": "first_contact",
            "audience_key": "unknown", "verbatim_ask": "100 seated",
            "voiced_objection": "", "keywords": [],
            "requirements": {"headcount": 100, "seated": True}})

    brief.assemble("ironside", "100 seated", "d@nw.com", model_fn=stub_small)
    ck("a gap that blocked nothing is not logged",
       len(kb.unknowns("ironside")) == before)

    target = [g for g in kb.unknowns("ironside") if g.entity_key == "virtual-set"][0]
    kb.resolve_unknown(target.id, "160")
    vs = [r for r in kb.match_entities("ironside", {"headcount": 150, "seated": True},
                                       limit=0) if r["key"] == "virtual-set"]
    ck("answering a gap writes it onto the entity and it becomes matchable",
       vs and vs[0]["fits"] is True, vs[0]["why"] if vs else "not returned")

    lg = [g for g in kb.unknowns("ironside") if g.entity_key == "lemon-grove"][0]
    kb.resolve_unknown(lg.id, "n/a")
    still = [r for r in kb.match_entities("ironside", {"headcount": 150, "seated": True},
                                          limit=0) if r["key"] == "lemon-grove"]
    ck("'n/a' removes it from that requirement entirely, not just from the queue",
       not still)
    ck("and it is never asked about again",
       not [g for g in kb.unknowns("ironside") if g.entity_key == "lemon-grove"])

    print()
    if _fail:
        print(f"{len(_fail)} FAILED: {_fail}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
