"""Offline exercise of the systems registry. No API keys, no network.

Covers the things that would silently rot: readiness blocking on each of its
three causes, the go-live gate refusing an incomplete contract, the autonomy
ladder refusing an unearned rung, and feedback landing in the two distinct
places it is supposed to land in.

    python3 scripts/test_systems.py
"""
from __future__ import annotations

import os
import sys
import tempfile

# A temp file, never sqlite:///:memory: — pooled connections each get their own
# empty in-memory database and every query then fails with "no such table".
_tmp = os.path.join(tempfile.mkdtemp(), "systems_test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config, db, kb, systems, tenants  # noqa: E402

# `agency` names its inbox "personal", and capabilities() only calls a
# connection wired if the credential actually exists — so with no
# GMAIL_ACCOUNTS_JSON in the environment, every agency system is correctly
# blocked on "not connected: inbox". That is the behaviour under test
# elsewhere; here it would just mask the gate logic, so supply a stub.
config.GMAIL_ACCOUNTS.setdefault("personal", {"email": "test@example.com"})

PASS, FAIL = "  ok  ", " FAIL "
_failures = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"[{PASS if cond else FAIL}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _failures.append(label)


def main() -> int:
    db.init_db()
    tenants.seed()
    kb.seed_agency()

    print("\n— seeding systems from the tenant rows —")
    out = systems.seed_from_tenants()
    check("adopts every pipeline named on a tenant", len(out["added"]) >= 8,
          f"{len(out['added'])} created")
    check("second run is idempotent",
          systems.seed_from_tenants()["added"] == [])

    # ---- readiness ------------------------------------------------------
    print("\n— readiness names its blockers —")
    lead = systems.find("agency", "lead_responder")
    check("a fresh system is not ready", not systems.ready(lead)["ready"])
    check("an empty contract is named as the blocker",
          any(b.startswith("contract:") for b in systems.ready(lead)["blockers"]))

    # agency has no ESP wired and no such system; use a tenant that needs one.
    campaign = systems.find("baci", "campaign_email")
    baci_blockers = systems.ready(campaign)["blockers"]
    check("a KB gap is reported separately from a connection gap",
          any(b.startswith("knowledge base:") for b in baci_blockers),
          "; ".join(baci_blockers)[:90])

    reports = systems.find("ironside", "reports")
    check("requires_any blocks only when NONE of the options are wired",
          any("at least one of" in b for b in systems.ready(reports)["blockers"]))

    # ---- the go-live gate ----------------------------------------------
    print("\n— the contract gate —")
    refused = systems.update(lead.id, status="live")
    check("going live is refused while the contract is incomplete",
          bool(refused.get("error")), refused.get("error", ""))

    for f in systems.CONTRACT_FIELDS:
        systems.update(lead.id, **{f: f"filled {f}"})
    lead = systems.find("agency", "lead_responder")
    check("contract now reads complete", systems.ready(lead)["contract_complete"])

    ok = systems.update(lead.id, status="live")
    check("going live succeeds once contract + connections are in place",
          bool(ok.get("ok")), str(ok.get("blockers", ""))[:90])

    # ---- the autonomy ladder -------------------------------------------
    print("\n— the autonomy ladder —")
    lead = systems.find("agency", "lead_responder")
    check("starts in shadow", lead.autonomy == "shadow")

    p = systems.promote(lead.id)
    check("shadow -> approve_all needs only readiness",
          p.get("autonomy") == "approve_all", str(p)[:80])

    lead = systems.find("agency", "lead_responder")
    verdict = systems.can_promote(lead)
    check("approve_all -> approve_exceptions is refused with no history",
          not verdict["can"], verdict["why"])

    # Earn it: enough clean decided runs to clear the gate.
    gate = systems.GATES["approve_exceptions"]
    for _ in range(gate["min_runs"]):
        rid = systems.start_run(lead.id, "agency", trigger="inbound_email")
        systems.finish_run(rid, "sent", decision="approved")
    lead = systems.find("agency", "lead_responder")
    check("promotion is allowed once the run history earns it",
          systems.can_promote(lead)["can"],
          str(systems.stats(lead.id)))

    # A single denial in the tail pulls the permission back.
    rid = systems.start_run(lead.id, "agency", trigger="inbound_email")
    systems.finish_run(rid, "sent", decision="denied")
    lead = systems.find("agency", "lead_responder")
    check("one recent denial closes the gate again",
          not systems.can_promote(lead)["can"],
          systems.can_promote(lead)["why"])

    check("demotion never needs a gate",
          systems.demote(lead.id, "testing")["autonomy"] == "shadow")

    # ---- blocked runs become the backlog --------------------------------
    print("\n— refusals are recorded, not dropped —")
    rid = systems.start_run(lead.id, "agency", trigger="inbound_email")
    systems.finish_run(rid, "blocked", blocked_on=["kb_objections (none)"])
    rid = systems.start_run(lead.id, "agency", trigger="inbound_email")
    systems.finish_run(rid, "blocked", blocked_on=["kb_objections (none)"])
    backlog = systems.blocked_reasons("agency")
    check("blocked reasons aggregate, most frequent first",
          backlog and backlog[0] == ("kb_objections (none)", 2), str(backlog[:2]))

    # ---- feedback: two channels, two behaviours -------------------------
    print("\n— guidance shapes drafting; a rule is enforced —")
    systems.note("agency", "lead_responder", "Lead with the number, not the greeting.")
    block = systems.feedback_block("agency", "lead_responder")
    check("guidance is injected into this system's prompt",
          "Lead with the number" in block)
    check("and not into another system's",
          "Lead with the number" not in systems.feedback_block("agency", "reports"))

    before = set(kb.banned_claims("agency"))
    systems.promote_rule("agency", "handcrafted")
    after = set(kb.banned_claims("agency"))
    check("a promoted rule lands in banned_claims where code enforces it",
          "handcrafted" in after and after > before)
    check("promoting the same rule twice is a no-op",
          "Already a rule" in systems.promote_rule("agency", "handcrafted"))

    # ---- the board renders ----------------------------------------------
    print("\n— the board —")
    board = systems.board()
    check("board covers every system", len(board) == len(systems.all_systems()))
    check("every entry carries named blockers or none",
          all(isinstance(b["blockers"], list) for b in board))

    # ---- per-system KB gating -------------------------------------------
    print("\n— gated on what it declared, not one global bar —")
    check_per_system_kb_gate(check)

    print()
    if _failures:
        print(f"{len(_failures)} FAILED: " + ", ".join(_failures))
        return 1
    print(f"all checks passed ({_tmp})")
    return 0


def check_per_system_kb_gate(ck):
    """A system is gated on what IT declared, not on one global bar.

    `kb_needs` was declared per system and read nowhere: `ready()` called
    `completeness()`, so compliance — which uses one field — was blocked until
    the account had a tone, a claim, an audience, an objection and a product.
    Meanwhile `next_steps`, which the lead responder genuinely needs,
    was checked by neither, leaving the blank-ask failure of DEFECTS 2.8
    reachable through a passing gate.
    """
    from app import kb, systems, db
    with db.SessionLocal() as s:
        if not s.get(db.Tenant, "gatetest"):
            s.add(db.Tenant(key="gatetest", name="Gate Test", kind="client",
                            domain="gatetest.com"))
            s.commit()
    kb.ensure_brand("gatetest", "Gate Test")
    with db.SessionLocal() as s:
        b = s.query(db.KbBrand).filter(db.KbBrand.tenant == "gatetest").first()
        b.banned_claims = ["made in italy"]
        s.commit()

    def ready_for(key):
        row = systems.find("gatetest", key) or systems.create("gatetest", key)
        with db.SessionLocal() as s:
            live = s.get(db.System, row.id)
            for f, _l, _w in systems.CONTRACT:
                setattr(live, f, "filled in")
            s.commit()
            return systems.ready(s.get(db.System, live.id))

    r = ready_for("content_compliance")
    ck("compliance runs on its one declared field and nothing else",
       r["ready"], str(r["blockers"]))

    r = ready_for("lead_responder")
    kbb = next((b for b in r["blockers"] if b.startswith("knowledge base")), "")
    ck("the lead responder is gated on next_steps, which the old bar never checked",
       "next_steps" in kbb, kbb)
    ck("and not on fields it never declared",
       "positioning" not in kbb, kbb)

    r = ready_for("reorder_engine")
    kbb = next((b for b in r["blockers"] if b.startswith("knowledge base")), "")
    ck("the reorder engine is gated at all — it used to be gated on nothing",
       "entity" in kbb, str(r["blockers"]))

    ck("a field nobody has answered is named plainly",
       kb.needs_met("gatetest", ("tone",)) == ["tone"])
    ck("and one satisfied is not named",
       kb.needs_met("gatetest", ("banned_claims",)) == [])


if __name__ == "__main__":
    raise SystemExit(main())