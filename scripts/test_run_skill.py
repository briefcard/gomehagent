"""The agent can reach the data layer, and still cannot pick a client.

Four skills have existed since the substrate was written and were callable only
from Python and two admin routes. The agent — the thing that actually answers
Gomeh and, later, a client — had no way to run one. Every guarantee in the
substrate applied to work nobody could start.

`run_skill` closes that, and the interesting half is what it does NOT hand the
model:

  · The account. `tool_scope` strips `tenant` from the schema and injects the
    resolved value at dispatch, so the model picks a skill and never a client.
  · The context. `catalogue()` is the description, so the model chooses a NAME
    and the substrate resolves the brief, validates the output, files it and
    applies the rung. A tool list would make the model assemble the context, and
    it would assemble it wrong in ways nothing downstream can see.

    python3 scripts/test_run_skill.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'rs.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import command_agent as ca, db, kb, skill, systems, tenants, tool_scope  # noqa: E402

_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    db.init_db()
    tenants.seed()
    systems.create("baci", "catalog_compliance")
    systems.create("baci", "content_compliance")

    print("— the model is never asked which client —")
    tools = tool_scope.filter_tools(ca.ACTION_TOOLS, "baci")
    rs = next((t for t in tools if t["name"] == "run_skill"), None)
    ck("the tool is offered", rs is not None)
    ck("  and `tenant` is NOT in the schema it sees",
       "tenant" not in rs["input_schema"]["properties"],
       str(sorted(rs["input_schema"]["properties"])))
    args, refusal = tool_scope.guard("run_skill", {"skill": "x"}, "baci")
    ck("  the account is injected at dispatch instead",
       args.get("tenant") == "baci" and not refusal)
    ck("a tool naming an account must be registered",
       "run_skill" in tool_scope.SCOPED,
       "test_tenant_isolation fails by name otherwise")

    print("\n— the description IS the catalogue —")
    ck("it names a skill this account has",
       "catalog_compliance" in rs["description"])
    ck("  and says what a blocked one is waiting on",
       "not connected" in rs["description"] or "not installed" in rs["description"],
       "a model that cannot see a blocked skill concludes the system cannot do "
       "it at all, instead of saying what is missing")
    ck("  a skill that is not installed is still listed, with why",
       "ad_copy" in rs["description"])
    ck("with no account there is nothing to list, and it says so",
       "no account is active" in skill.tool_description("").lower())

    print("\n— refusals are named, never worked around —")
    ck("no client is a refusal",
       "No client is active" in ca._run_skill({"tenant": "", "skill": "a"}))
    ck("no skill lists what is ready",
       "Which skill?" in ca._run_skill({"tenant": "baci", "skill": ""}))
    ck("an unknown skill is named, not guessed at",
       "no skill keyed" in ca._run_skill({"tenant": "baci", "skill": "nope"}))
    ck("params must be an object",
       "must be an object" in ca._run_skill(
           {"tenant": "baci", "skill": "catalog_compliance", "params": "x"}))
    said = ca._run_skill({"tenant": "baci", "skill": "catalog_compliance"})
    ck("a missing connection is reported as one",
       "not connected" in said, said[:80])
    ck("  and the agent is told NOT to do it by hand",
       "do not draft this by hand" in said,
       "the whole point of the layer is that the ungoverned path is worse")

    print("\n— a thin run says what it lacked —")
    # Every registered skill needs a connection, and this fixture has none, so
    # the thin path is exercised where it actually lives: the formatting. That
    # is the part this file owns — `test_skill.py` covers `thin` being produced.
    kb.ensure_brand("baci", "Baci")
    kb.add_banned("baci", "made in Italy")
    real = skill.run
    skill.run = lambda key, tenant, **kw: {
        "status": "produced", "summary": "one report",
        "items": [{"status": "draft"}, {"status": "blocked"}],
        "thin": ["knowledge base: tone", "contract: Owner"],
        "notes": ["working without: tone"], "run_id": "r1"}
    try:
        out = ca._run_skill({"tenant": "baci", "skill": "catalog_compliance"})
    finally:
        skill.run = real
    ck("a produced run is reported as produced", "produced" in out, out[:60])
    ck("  the blocked item is counted, not hidden",
       "1 of them blocked by the validator" in out, out)
    ck("  and it says what the run worked WITHOUT",
       "worked WITHOUT" in out and "knowledge base: tone" in out,
       "a thin answer reported as a clean one is exactly what the gating "
       "change was supposed to make visible")
    ck("  telling the agent to pass that on",
       "say so if you pass this on" in out)

    print("\n— every registered skill is reachable by name —")
    for row in skill.catalogue("baci"):
        said = ca._run_skill({"tenant": "baci", "skill": row["key"]})
        ck(f"  {row['key']} answers rather than raising",
           bool(said) and "Traceback" not in said, said.splitlines()[0][:70])

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
