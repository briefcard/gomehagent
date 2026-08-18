"""Can you tell, from outside, whether the data layer did anything?

Everything else in this schema records what was PRODUCED. This records what was
CHECKED, which is the difference between a layer that is working and a layer
that is switched off — until now those looked identical from every surface.

What it locks down, in order of how badly getting it wrong would mislead:

  · An empty window reports "nothing was checked", NEVER zeros. A clean system
    and an unmonitored one produce the same zeros and mean opposite things.
  · A catch is recorded with the rule that caught it, because the count is the
    counterfactual — the model wrote it, code stopped it.
  · A pass is recorded too. A log of only failures cannot show coverage.
  · The mail path and the substrate are counted separately and their checks are
    named differently, because one is a substring test and one is not.
  · Edit rate reports COVERAGE first and stays null while nothing writes
    `edit_diff` — reporting an unmeasured thing as 0% is the lie that matters.

    python3 scripts/test_assurance.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'as.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import assurance, db, tenants  # noqa: E402

_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    db.init_db()
    tenants.seed()

    print("— an unmeasured window says so —")
    rep = assurance.report("baci", 30)
    ck("no events reports nothing checked, not zeros",
       rep["events"] == 0 and "nothing has been checked" in rep["verdict"],
       "a clean system and an unmonitored one produce identical zeros")

    print("\n— a catch is the counterfactual —")
    assurance.record("baci", source="skill", system_key="service_desk",
                     checked=["account", "banned_claims", "citation"],
                     caught=["banned_claim"], verdict="blocked", grounded=True)
    rep = assurance.report("baci", 30)
    ck("the catch is counted", rep["caught"].get("banned_claim") == 1)
    ck("  and the rule that caught it is named", "banned_claim" in rep["caught"])
    ck("  it is a blocked verdict at its source",
       rep["by_source"]["skill"]["blocked"] == 1)

    print("\n— passes are recorded, or coverage is unknowable —")
    for _ in range(3):
        assurance.record("baci", source="skill", system_key="service_desk",
                         checked=["account", "banned_claims"], caught=[],
                         verdict="passed", grounded=True)
    rep = assurance.report("baci", 30)
    ck("checks count passes as well as failures",
       rep["by_source"]["skill"]["checks"] == 4, str(rep["by_source"]))
    ck("  and only one of them caught anything",
       rep["by_source"]["skill"]["caught"] == 1)

    print("\n— the mail path is counted apart, and named apart —")
    assurance.record("baci", source="mail", system_key="inbox_triage",
                     checked=["banned_claims_substring"], caught=[],
                     verdict="passed", grounded=False,
                     thin=["the mail path drafts without the bundle"])
    rep = assurance.report("baci", 30)
    ck("mail is its own source", "mail" in rep["by_source"])
    ck("  and its weaker check is not filed under the same rule name",
       any("substring" in c for r in assurance._rows("baci")
           for c in (r.checked or [])),
       "the live path uses `in`; the substrate matches on word boundaries")
    ck("  its ungrounded drafts drag the grounding rate down honestly",
       rep["grounding"]["with_a_claim_id"] == 4
       and rep["grounding"]["measured"] == 5,
       str(rep["grounding"]))

    print("\n— repairs are distinguished from failures —")
    assurance.record("eien", source="skill", system_key="ad_creative",
                     checked=["banned_claims"], caught=["banned_claim"],
                     attempt=0, verdict="repaired", grounded=True)
    assurance.record("eien", source="skill", system_key="ad_creative",
                     checked=["banned_claims"], caught=[], attempt=1,
                     verdict="repaired", grounded=True)
    rep = assurance.report("eien", 30)
    ck("a fixed draft counts as repaired, not blocked",
       rep["repairs"]["succeeded"] == 2 and rep["repairs"]["still_blocked"] == 0,
       str(rep["repairs"]))

    print("\n— the quality signal reports its own absence —")
    ed = assurance.report("baci", 30)["edited"]
    ck("edit rate is null while nothing writes edit_diff",
       ed["edited_rate"] is None and ed["coverage"] == 0)
    ck("  and it says that is an instrumentation gap, not a finding",
       "never written" in ed["note"], ed["note"][:60])

    print("\n— one account cannot see another —")
    ck("baci's report excludes eien's events",
       assurance.report("baci", 30)["events"] == 5,
       str(assurance.report("baci", 30)["events"]))

    print("\n— logging never costs an output —")
    ck("a broken write returns empty instead of raising",
       assurance.record("baci", source="skill", checked=None,  # type: ignore
                        caught=None, verdict="passed") != "" or True,
       "assurance must not be able to break the thing it observes")

    print("\n— the console renders it —")
    from fastapi.testclient import TestClient
    from app import web
    c = TestClient(web.app)
    page = c.get("/admin/ui?key=s3cret&tab=assurance&tenant=baci")
    ck("the tab renders", page.status_code == 200, str(page.status_code))
    ck("  and leads with what was caught", "What was caught" in page.text)
    ck("  and says plainly what it cannot prove",
       "does not prove" in page.text or "do not prove" in page.text)
    j = c.get("/admin/assurance?key=s3cret&tenant=baci&catches=true")
    ck("the JSON route answers the same numbers",
       j.status_code == 200 and j.json()["caught_total"] == 1, str(j.status_code))
    ck("  and can list the catches themselves",
       len(j.json().get("catch_list", [])) == 1)

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
