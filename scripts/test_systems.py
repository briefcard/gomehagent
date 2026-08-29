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
    # CHANGED 2026-08-20, deliberately. These pinned the rule that an empty
    # contract blocks a system, which the owner overturned: "Every system
    # currently has to fill in the contract otherwise the system fails. That
    # doesn't need to happen." As a blocker it was also being reported as
    # something the ACCOUNT was missing — three of the top four rows in a real
    # week's knowledge backlog were contract fields, which no amount of writing
    # about the client could ever satisfy.
    check("an empty contract is NOT a blocker",
          not any(b.startswith("contract:")
                  for b in systems.ready(lead)["blockers"]),
          str(systems.ready(lead)["blockers"]))
    check("  and is still visible as incomplete",
          systems.ready(lead)["contract_complete"] is False)

    # agency has no ESP wired and no such system; use a tenant that needs one.
    campaign = systems.find("baci", "campaign_email")
    baci_blockers = systems.ready(campaign)["blockers"]
    check("a KB gap is reported separately from a connection gap",
          any(b.startswith("knowledge base:") for b in baci_blockers),
          "; ".join(baci_blockers)[:90])

    reports = systems.find("ironside", "reports")
    check("requires_any blocks only when NONE of the options are wired",
          any("at least one of" in b for b in systems.ready(reports)["blockers"]))

    # ---- the decision has to reach the run ------------------------------
    print("\n— deciding an output moves the system up the ladder —")
    from app import approvals

    dec = systems.find("baci", "reports") or systems.create("baci", "reports")
    rid = systems.start_run(dec.id, "baci", trigger="test")
    systems.finish_run(rid, "produced")
    before = systems.stats(dec.id)
    ap = approvals.request_approval("skill_output", "a draft to decide",
                                    {"tenant": "baci"}, notify=False,
                                    run_id=rid, system_id=dec.id)
    check("an approval carries the run that produced it",
          bool(ap), "nothing came back from request_approval")
    check("before deciding, the run counts as undecided",
          before["decided"] == 0, str(before))
    approvals.apply_decision(ap, "approved")
    after = systems.stats(dec.id)
    check("APPROVING IT RECORDS THE DECISION ON THE RUN",
          after["decided"] == 1 and after["approved"] == 1, str(after))
    check("  so approval_rate is a real number, not a permanent zero",
          after["approval_rate"] == 1.0, str(after["approval_rate"]))

    rid2 = systems.start_run(dec.id, "baci", trigger="test")
    systems.finish_run(rid2, "produced")
    ap2 = approvals.request_approval("skill_output", "one to deny",
                                     {"tenant": "baci"}, notify=False,
                                     run_id=rid2, system_id=dec.id)
    approvals.apply_decision(ap2, "denied")
    check("a denial is recorded too — the gate needs both",
          systems.stats(dec.id)["denied"] == 1,
          str(systems.stats(dec.id)))

    # ---- the go-live gate ----------------------------------------------
    print("\n— the contract gate —")
    # CHANGED with the above: going live is gated on connections and knowledge,
    # not on prose. What the contract still gates is `auto` — the rung where
    # nobody reads the output, which is the case its eight questions were
    # written for.
    went = systems.update(lead.id, status="live")
    check("going live is NOT refused for an incomplete contract alone",
          went.get("ok") is True or "contract" not in str(went.get("blockers", "")),
          str(went))
    lead_live = systems.find("agency", "lead_responder")
    lead_live.autonomy = "approve_exceptions"
    gate = systems.can_promote(lead_live)
    check("  but the unattended rung still requires it",
          not gate["can"] and "contract" in gate["why"], gate["why"][:70])

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

    # THE SCOPE BETWEEN "this pipeline" and "ban the phrase for ever".
    # Owner, 2026-08-29: the claim margin's "Never again" files lessons about
    # what an ACCOUNT sells and may assert, and filed system-scoped they
    # taught the blog while every other system went on repeating them.
    systems.note("agency", systems.ACCOUNT,
                 "Never recommend a category this account does not sell.")
    g_own = systems.guidance_block("agency", "lead_responder")
    g_other = systems.guidance_block("agency", "reports")
    check("an account lesson reaches the system that was open",
          "Never recommend a category" in g_own)
    check("…and every other system too — that is the whole point",
          "Never recommend a category" in g_other,
          "filed against one pipeline it teaches one pipeline")
    check("…without dragging that system's own lessons across",
          "Lead with the number" not in g_other,
          "'shorter lines' is about one pipeline and has no business "
          "reaching another")
    check("…and it is labelled as account-wide, not as the system's own",
          "for this ACCOUNT" in g_other and "for this system" not in g_other,
          "a drafter that cannot tell 'true of the brand everywhere' from "
          "'true of this pipeline' will apply one as the other")
    check("an account with no account-lesson gets no empty heading",
          systems.account_block("nobody") == "")

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

    # --- the two questions stay apart ----------------------------------
    #
    # `ready` gates GOING LIVE. `can_produce` gates whether work happens at
    # all, and ONLY an absent connection belongs in it. These were one bar,
    # which is how an unapproved objection came to stand between a customer
    # and a reply.
    #
    # Asserted as invariants over the classification rather than as the state
    # of one fixture: the first attempt checked `can_produce` on a tenant with
    # no connections at all, where everything is legitimately impossible, and
    # was testing the fixture instead of the rule.
    for key in ("ad_creative", "reorder_engine", "campaign_email", "blog",
                "lead_responder", "service_desk", "content_compliance",
                "catalog_compliance", "reports"):
        st = ready_for(key)
        ck(f"{key}: knowledge is never a reason it cannot run",
           not any("knowledge base" in b for b in st["impossible"]),
           str(st["impossible"]))
        ck(f"  {key}: only connections are",
           all("not connected" in b or "at least one of" in b
               for b in st["impossible"]), str(st["impossible"]))

    # `reports` needs no connection and no knowledge, so a blank contract is
    # the only thing left — which is exactly the case the owner overruled.
    row = systems.find("gatetest", "reports")
    with db.SessionLocal() as s_:
        live = s_.get(db.System, row.id)
        live.owner = ""
        s_.commit()
        blank = systems.ready(s_.get(db.System, live.id))
    # This fixture has no connections, so `can_produce` is legitimately False
    # for every system on it. The claim being locked is narrower and is the one
    # that actually changed: a blank contract is not among the reasons.
    ck("an incomplete contract is NOT a reason it cannot run",
       not any(b.startswith("contract:") for b in blank["impossible"]),
       str(blank["impossible"]))
    ck("  and it is not carried as thin either",
       not any(t.startswith("contract:") for t in blank["thin"]),
       str(blank["thin"]))
    ck("  it is reported on its own, for a person to answer or not",
       blank["contract_complete"] is False and blank["missing_contract"],
       "advisory, not a gap the account has to fill")

    # The classification must NOT be re-derived from the message text. The
    # first version used `b.startswith("not connected:")` on prose this same
    # function assembles — §1's string-matching pattern, written by the author
    # of the rule. Rewording a blocker would have reclassified every
    # connection gap as `thin`, and a system with no mailbox would have begun
    # producing replies it had no way to send.
    r = ready_for("ad_creative")
    ck("every blocker lands in exactly one of the two lists",
       sorted(r["blockers"]) == sorted(r["impossible"] + r["thin"]),
       "neither list is parsed back out of the other")


if __name__ == "__main__":
    raise SystemExit(main())