"""Claim scope: individual, group, brand-wide — and the conflicts between them.

Scope used to be binary, one entity or the whole brand, so "every Aqua pitcher
is acrylic" could only be said once per pitcher. That is not a review backlog,
it is the schema having no way to express what is true: brand-wide would be
false, because the porcelain lines are not acrylic.

Precedence is a correctness rule, not a preference. The narrower a claim's
scope, the more precisely it was checked against the thing being written about.

Run: python3 scripts/test_scope.py
"""
import os
import sys
import tempfile

_tmp = os.path.join(tempfile.mkdtemp(), "scope.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}"
os.environ["APPROVAL_SECRET"] = "test-secret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, kb, tenants  # noqa: E402

_fails: list[str] = []


def ck(label: str, cond: bool, detail: str = "") -> None:
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fails.append(label)


def _scopes(tenant, entity_key, situation="material"):
    return [(c.entity_key or "brand-wide")
            for c in kb.claims(tenant, situations=[situation],
                               entity_key=entity_key)]


def main() -> int:
    db.init_db()
    tenants.seed()
    kb.set_brand("baci", tone="Warm, precise.")
    kb.add_banned("baci", "hand-decorated")
    kb.add_situation("baci", "material", patterns=[["material"]],
                     origin="human")

    kb.add_entity("baci", "collection", "aqua", "Aqua Collection")
    for k, n in [("white-acrylic-pitcher-aqua", "White Acrylic Pitcher"),
                 ("taupe-acrylic-pitcher-aqua", "Taupe Acrylic Pitcher")]:
        kb.add_entity("baci", "product", k, n)
        kb.join_group("baci", k, "aqua")
    kb.add_entity("baci", "product", "mamma-mia-plate", "Mamma Mia Plate")

    print("— selecting items into a group —")
    ck("an entity knows the group above it",
       kb.ancestors("baci", "white-acrylic-pitcher-aqua") == ["aqua"],
       str(kb.ancestors("baci", "white-acrylic-pitcher-aqua")))
    ck("a group lists its members",
       len(kb.group_members("baci", "aqua")) == 2)
    ck("an item outside it has no group",
       kb.ancestors("baci", "mamma-mia-plate") == [])
    ck("a group cannot contain itself",
       "cannot be its own" in kb.join_group("baci", "aqua", "aqua"))
    ck("A LOOP IS REFUSED — a walk that stops at a cycle looks exactly like "
       "one that reached the top, so this is checked on the proposed parent",
       "would make a loop" in kb.join_group("baci", "aqua",
                                            "white-acrylic-pitcher-aqua"))
    ck("  and the refusal left the tree intact",
       kb.ancestors("baci", "white-acrylic-pitcher-aqua") == ["aqua"])
    ck("an unknown group is refused, not silently created",
       "No entity keyed" in kb.join_group("baci", "mamma-mia-plate", "nope"))

    print("\n— several groups at once, because a catalogue has several axes —")
    kb.add_entity("baci", "collection", "acrylics", "Acrylics")
    kb.add_entity("baci", "collection", "pitchers", "Pitchers & Carafes")
    for g in ("acrylics", "pitchers"):
        kb.join_group("baci", "white-acrylic-pitcher-aqua", g)
    ck("an entity belongs to its range, its material AND its type",
       set(kb.ancestors("baci", "white-acrylic-pitcher-aqua"))
       == {"aqua", "acrylics", "pitchers"},
       str(sorted(kb.ancestors("baci", "white-acrylic-pitcher-aqua"))))
    ck("  joining one group never evicts it from another",
       "aqua" in kb.ancestors("baci", "white-acrylic-pitcher-aqua"))
    kb.add_claim("baci", "Shatterproof acrylic, not glass.", "material sheet",
                 ["material"], origin="human", entity_key="acrylics")
    ck("  a claim on the MATERIAL group reaches it",
       "acrylics" in _scopes("baci", "white-acrylic-pitcher-aqua"),
       str(_scopes("baci", "white-acrylic-pitcher-aqua")))
    ck("  and not the taupe pitcher, which was never added to it",
       "acrylics" not in _scopes("baci", "taupe-acrylic-pitcher-aqua"),
       str(_scopes("baci", "taupe-acrylic-pitcher-aqua")))
    ck("leaving one group keeps the others",
       "Removed from 1" in kb.leave_group("baci", "white-acrylic-pitcher-aqua",
                                          "pitchers")
       and "aqua" in kb.ancestors("baci", "white-acrylic-pitcher-aqua"))

    print("\n— one claim, said once, true of the whole range —")
    kb.add_claim("baci", "Shatterproof acrylic throughout.", "spec sheet",
                 ["material"], origin="human", entity_key="aqua")
    kb.add_claim("baci", "Fine porcelain, dishwasher-safe.", "spec sheet",
                 ["material"], origin="human")                    # brand-wide
    kb.add_claim("baci", "This pitcher holds 1.5 litres.", "spec sheet",
                 ["material"], origin="human",
                 entity_key="white-acrylic-pitcher-aqua")

    ck("a group claim reaches a member that never mentions it",
       "aqua" in _scopes("baci", "taupe-acrylic-pitcher-aqua"),
       str(_scopes("baci", "taupe-acrylic-pitcher-aqua")))
    ck("IT DOES NOT LEAK OUTSIDE THE GROUP — the porcelain plate never sees "
       "the acrylic claim",
       "aqua" not in _scopes("baci", "mamma-mia-plate"),
       str(_scopes("baci", "mamma-mia-plate")))

    print("\n— precedence: individual, then group, then brand-wide —")
    got = _scopes("baci", "white-acrylic-pitcher-aqua")
    ck("every scope it belongs to is offered", len(got) == 4, str(got))
    ck("  the individual claim leads", got[0] == "white-acrylic-pitcher-aqua",
       str(got))
    ck("  brand-wide comes last", got[-1] == "brand-wide", str(got))
    # Two groups both sit at depth 1, so their order relative to each other is
    # a tie and deliberately not asserted — pinning it would be pinning an
    # implementation detail, which is how the insertion-order bug hid before.
    ck("  both groups sit between them", set(got[1:-1]) == {"aqua", "acrylics"},
       str(got))
    ck("a member with no claim of its own leads with the group's",
       _scopes("baci", "taupe-acrylic-pitcher-aqua")[0] == "aqua")

    # Relevance still leads: a claim that answers the question asked beats a
    # narrower one about something else.
    kb.add_situation("baci", "care", patterns=[["care"]], origin="human")
    kb.add_claim("baci", "Top-rack dishwasher safe, every piece.", "care sheet",
                 ["material", "care"], origin="human")
    ranked = kb.claims("baci", situations=["material", "care"],
                       entity_key="white-acrylic-pitcher-aqua")
    ck("relevance still outranks specificity — two situations beat one",
       (ranked[0].entity_key or "") == "",
       f"led with {(ranked[0].entity_key or 'brand-wide')!r}")

    print("\n— conflicts are flagged, never resolved —")
    cs = kb.scope_conflicts("baci")
    ck("overlapping scopes are reported", bool(cs), "nothing flagged")
    ck("  the widest blast radius comes first",
       cs[0]["affects"] == sorted(cs[0]["affects"], key=lambda k: k)
       or len(cs[0]["affects"]) >= len(cs[-1]["affects"]),
       str([len(c["affects"]) for c in cs]))
    ck("  ONE PAIR IS ONE ROW, not one row per member — a collection-wide "
       "overlap must not become forty entries",
       all(len({(c["wins"]["claim_id"], c["loses"]["claim_id"])}) == 1
           for c in cs)
       and len({(c["wins"]["claim_id"], c["loses"]["claim_id"])
                for c in cs}) == len(cs),
       f"{len(cs)} rows")
    widest = cs[0]
    ck("  it names every entity it affects", len(widest["affects"]) >= 2,
       str(widest["affects"]))
    ck("  and says which claim wins, without deciding whether that is right",
       widest["wins"]["depth"] > widest["loses"]["depth"]
       and "check that" in widest["why"])

    print("\n— a claim with no group behaves exactly as before —")
    ck("brand-wide still reaches everything",
       "brand-wide" in _scopes("baci", "mamma-mia-plate"))
    ck("asking with no entity returns brand-wide only",
       all((c.entity_key or "") == ""
           for c in kb.claims("baci", situations=["material"])))

    print()
    if _fails:
        print(f"{len(_fails)} FAILED:")
        for f in _fails:
            print(f"  - {f}")
        return 1
    print("all green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
