"""A real answer to a real customer question, assembled and held to account.

This is the first thing in the platform that produces something, and it does it
**without a model call**. That is not a compromise for a capped API key — it
falls out of what "approved" already means. An approved objection carries the
response a human wrote and signed off; answering a question that matches it is
retrieval, assembly and validation, not authorship. The model's job would be to
make it sound bespoke, which is the last thing to add rather than the first.

The chain, and every link already existed:

    resolve()      what does this account know that bears on this question
    assemble       the approved response, with the claims that back it
    validator      pure code, fails closed, names what it blocked on
    ledger         what was produced, from which brief

**A blocked run is recorded too.** A ledger of only the things that worked
cannot tell you what stopped, and `blocked_reasons()` on the systems side
already learned this — the point is to rank the knowledge-base backlog by how
often each gap actually cost an answer.

Nothing here sends. `answer()` returns a draft and files it; publishing is a
separate, explicit act, so the default is shadow and autonomy stays earned.
"""
from __future__ import annotations

from . import conversation as cv, ledger, resolve as rs, validator


def answer(tenant: str, utterance: str, *, contact_id: str = "",
           entity_key: str = "", system_key: str = "service_desk",
           run_id: str = "", within_days: int = 30) -> dict:
    """Answer one question from what this account actually knows.

    Returns the draft, the evidence behind it, the validator's verdict, and the
    ledger id — so what was said, why, and on whose authority are all one
    lookup rather than a reconstruction.
    """
    bundle = rs.resolve(tenant, system=system_key, utterance=utterance,
                        contact_id=contact_id, entity_key=entity_key, tier=3)

    conversation_id = (bundle.get("conversation") or {}).get("conversation_id", "")
    situation = (bundle.get("situations") or {}).get("detected") or []
    situation = situation[0] if situation else ""

    def _blocked(reasons: list[str], stage: str) -> dict:
        row = ledger.record(
            tenant, system_key, situation=situation, entity_key=entity_key,
            status="blocked", blocked_on=reasons, run_id=run_id,
            conversation_id=conversation_id, format="reply")
        return {"ok": False, "stage": stage, "blocked_on": reasons,
                "output_id": row.id, "bundle": bundle,
                "note": "recorded as blocked — a gap only gets fixed if it is "
                        "counted"}

    # --- 1. could the layer ground it at all ------------------------------
    if bundle.get("blocked_on"):
        return _blocked(bundle["blocked_on"], "resolve")
    if not bundle.get("objections"):
        return _blocked(["no approved objection matched this question"],
                        "resolve")

    # --- 2. assemble, from what a human already approved ------------------
    top = bundle["objections"][0]
    claim_ids = [c["claim_id"] for c in top.get("support", []) if c.get("claim_id")]
    body = (top.get("response") or "").strip()

    # --- 3. validate: code only, fails closed -----------------------------
    verdict = validator.check(
        tenant, body, claim_ids=claim_ids, entity_key=entity_key,
        conversation_id=conversation_id, within_days=within_days,
        # The response is a human-approved sentence, not an assembled claim.
        # Demanding a citation for wording somebody signed off would block
        # every answer this system can give.
        require_citation=False)
    if not verdict["ok"]:
        return _blocked([f"{f['rule']}: {f['detail']}" for f in verdict["failures"]],
                        "validate") | {"verdict": verdict}

    # --- 4. file it -------------------------------------------------------
    row = ledger.record(
        tenant, system_key, situation=situation, entity_key=entity_key,
        objection_id=top.get("objection_id", ""), claim_ids=claim_ids,
        status="draft", body=body, format="reply", run_id=run_id,
        conversation_id=conversation_id, angle=top.get("objection", "")[:80])

    return {
        "ok": True,
        "draft": body,
        "answers": top.get("objection", ""),
        "situation": situation,
        "evidence": top.get("support", []),
        "rules_enforced": verdict["rules_enforced"],
        "checked": verdict["checked"],
        "output_id": row.id,
        "conversation_id": conversation_id,
        "open_commitments": (bundle.get("conversation") or {}).get(
            "open_commitments", []),
        "coverage": bundle.get("coverage", {}),
        "note": ("draft only — nothing was sent. Publishing is a separate act, "
                 "so the default stays shadow and autonomy is earned."),
    }


def send(tenant: str, output_id: str, *, conversation_id: str = "",
         channel: str = "email", ref: str = "", destination: str = "") -> dict:
    """Mark a draft as gone out, and record the touch that carried it.

    Deliberately separate from `answer`. The idempotency key is the output id,
    so a retry after a crash cannot send the same reply twice — the failure
    the handoff flags as unfixed on the publish path.
    """
    msg = ledger.publish(tenant, output_id, destination=destination)
    if "No such" in msg:
        return {"ok": False, "why": msg}
    touch = None
    if conversation_id:
        touch, created, note = cv.record_touch(
            tenant, conversation_id, direction="out", channel=channel,
            summary=f"replied (output {output_id[:8]})", ref=ref,
            idempotency_key=f"output:{output_id}")
        if not created:
            return {"ok": True, "already_sent": True, "why": note,
                    "touch_id": touch.id if touch else ""}
    return {"ok": True, "output_id": output_id,
            "touch_id": touch.id if touch else "", "note": msg}
