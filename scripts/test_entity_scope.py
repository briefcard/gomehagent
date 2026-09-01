"""A piece about a PLACE may cite the things in it.

Owner, 2026-08-31, on an article written for Miami Ironside: *"this article
about 'Corporate Events in Miami' hit several different entities in a single
space as a value proposition compared to other locations. So, we definitely
want to have more than one entity in this article."*

`kb.claims(tenant)` was brand-wide, `kb.claims(tenant, entity_key=X)` was
brand-wide plus one, and there was no third answer. So an article about the
LOCATION saw brand-wide claims only — and the venues that are the EVIDENCE for
"several distinct spaces in one place" were invisible to the drafter. The
best claim the account has was the one it could not prove.

THE RULE THAT WAS DOING THE WRONG JOB. `kb.claims`' docstring said a fact only
true of one product must not turn up in a newsletter about something else.
That is a truth rule enforced by retrieval, and retrieval cannot enforce it:
it cannot tell CITING a fact from ASSERTING it of the wrong subject. The
second is `coherence.proof_belongs_to_subject`, a gate that already exists and
is already guarded. Widening the scope is safe BECAUSE that gate checks
attribution — and the narrow scope was paying for a rule it never enforced.

WHAT IS ASSERTED:

  · three scopes, not two: the brand, one subject, several subjects
  · a venue's own facts outrank brand-wide ones when the venue is in scope,
    including when several are — scoring against one of them would rank the
    Atrium's facts as a distant relative of the Glassbox
  · every claim once, however many entities are in scope
  · the plan field is a REFERENCE: a venue nobody approved is refused, not
    quietly read as no scope
  · a topic commitment declares its proof scopes, so the gate knows which
    venues' facts legitimately belong in it
  · nothing moves for a piece about one thing

Run: python3 scripts/test_entity_scope.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'es.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import (coherence, db, kb, resolve as rs, skill,  # noqa: E402
                 systems, tenants)
import app.skill_pack  # noqa: F401,E402  (registers the pack)

_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    db.init_db()
    tenants.seed()
    kb.ensure_brand("baci", "Miami Ironside")
    kb.set_brand("baci", positioning="One campus, many rooms.", tone="warm")
    for k, n in (("glassbox", "Glassbox"), ("atrium", "Atrium"),
                 ("yard", "The Yard")):
        kb.add_entity("baci", "product", k, n)
    kb.add_banned("baci", "made in Italy")   # catalog_compliance needs one
    kb.add_claim("baci", "Six distinct spaces on one campus.", "site plan", [])
    kb.add_claim("baci", "Glassbox seats 180.", "fire cert", [],
                 entity_key="glassbox")
    kb.add_claim("baci", "Atrium seats 90.", "fire cert", [],
                 entity_key="atrium")

    print("— three scopes, where there used to be two —")
    brand = [c.claim for c in kb.claims("baci")]
    one = [c.claim for c in kb.claims("baci", entity_key="glassbox")]
    many = [c.claim for c in kb.claims("baci",
                                       entity_keys=["glassbox", "atrium"])]
    ck("the brand alone sees only brand-wide proof", len(brand) == 1, str(brand))
    ck("one subject sees the brand's and its own", len(one) == 2, str(one))
    ck("several subjects see the brand's and ALL of theirs", len(many) == 3,
       "the venues ARE the evidence for 'several distinct spaces'")

    print("\n— and each venue's facts outrank the brand-wide one —")
    ck("with several in scope, specificity still leads",
       many[0] != "Six distinct spaces on one campus."
       and many[-1] == "Six distinct spaces on one campus.",
       " | ".join(x[:24] for x in many))
    ck("  every claim appears once", len(many) == len(set(many)))

    print("\n— the singular is the plural with one item —")
    ck("no second code path to keep in step",
       [c.id for c in kb.claims("baci", entity_key="glassbox")]
       == [c.id for c in kb.claims("baci", entity_keys=["glassbox"])])

    print("\n— resolve carries it to the drafter —")
    b_one = rs.resolve("baci", tier=3, entity_key="glassbox")
    b_many = rs.resolve("baci", tier=3, entity_keys=["glassbox", "atrium"])
    ck("one venue reaches the bundle",
       len(b_one["claims"]) == 2, str(len(b_one["claims"])))
    ck("  and a location reaches it with all of them",
       len(b_many["claims"]) == 3, str(len(b_many["claims"])))
    cnt = b_many["coverage"]["counts"]
    ck("  the receipt counts what was actually offered",
       cnt["claims_offered"] == 3, str(cnt["claims_offered"]))
    ck("  and measures the pool against the SAME scope",
       cnt["claims_selectable"] == 3,
       "`rows` is what the drafter gets and `_pool` is what the receipt "
       "measures it against — scoping them differently would report a "
       "narrowing that did not happen")

    print("\n— the plan field is a reference, not free text —")
    fields = {f["key"]: f for f in
              systems.workflow("blog")["plan_fields"]}
    ck("blog can say what else it is about", "entity_keys" in fields,
       ", ".join(sorted(fields)))
    ck("  and it is checked against real entities",
       fields["entity_keys"].get("kind") == "entity_list")
    ok = systems._check_plan_refs("baci", "blog",
                                  {"entity_keys": "glassbox, atrium"})
    bad = systems._check_plan_refs("baci", "blog",
                                   {"entity_keys": "glassbox, not-a-venue"})
    ck("a real list passes", ok == "", ok)
    ck("  and one bad key is refused by name", "not-a-venue" in bad, bad)

    print("\n— the commitment declares whose facts belong in it —")
    c = coherence.commit("topic", "corporate-events-in-miami",
                         label="Corporate Events in Miami",
                         also=["atrium"], proof_scopes=["glassbox", "atrium"])
    ck("a topic can carry proof scopes",
       c["proof_scopes"] == ["glassbox", "atrium"], str(c))
    ck("  which is what the gate reads to allow a venue's proof",
       "proof_scopes" in coherence.commit("topic", "x"),
       "without it `review` falls back to the topic slug, which is not an "
       "entity key, so every venue fact reads as borrowed")

    print("\n— and a RUN carries it, not just resolve —")
    # The boundary is the point: `resolve` has accepted a plural scope from the
    # moment it was written, and a value that stops at the skill edge is the
    # shape this repo keeps closing — declared here, read nowhere. Asserted
    # through `skill.run`, because that is the only place the plumbing exists.
    _ALL = {c: True for c in tenants.CAPABILITIES}
    tenants.capabilities = lambda k: dict(_ALL)
    seen: dict = {}

    def _probe(ctx):
        seen["claims"] = [c["claim"] for c in (ctx.bundle.get("claims") or [])]
        return ctx.emit("Designed in Milan.", require_citation=False)

    skill.register(skill.Skill(
        key="_scope_probe", name="scope probe", does="records its bundle",
        system_key="catalog_compliance", tier=3, needs=(),
        params=("entity_key", "entity_keys"), run=_probe))
    row = systems.find("baci", "catalog_compliance") or \
        systems.create("baci", "catalog_compliance")
    # BOTH RETURNS ASSERTED. `update` refuses go-live while the contract is
    # empty or the declared knowledge is missing, and ignoring that is silent
    # loss in the harness itself — the probe simply never runs and every
    # assertion after it reads as a defect in the code under test. It cost a
    # cycle here before this line existed.
    _r1 = systems.update(row.id, **{f: "declared for the test"
                                    for f, _l, _h in systems.CONTRACT})
    assert _r1.get("ok"), f"contract fill refused: {_r1}"
    _r2 = systems.update(row.id, status="live", autonomy="shadow")
    assert _r2.get("ok"), f"go-live refused: {_r2}"

    skill.run("_scope_probe", "baci", entity_key="glassbox")
    ck("a run naming one venue sees two", len(seen["claims"]) == 2,
       str(seen["claims"]))
    skill.run("_scope_probe", "baci", entity_keys="glassbox, atrium")
    ck("  and a run naming several sees all of them",
       len(seen["claims"]) == 3, str(seen["claims"]))
    skill.run("_scope_probe", "baci")
    ck("  while a run naming none still sees the brand alone",
       len(seen["claims"]) == 1, str(seen["claims"]))

    print("\n— and nothing moves for a piece about one thing —")
    ck("an article naming one venue is unchanged",
       [c.claim for c in kb.claims("baci", entity_key="glassbox")] == one)

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
