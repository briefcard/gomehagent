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

from . import conversation as cv, kb, ledger, resolve as rs, validator


def answer(tenant: str, utterance: str, *, contact_id: str = "",
           entity_key: str = "", system_key: str = "service_desk",
           run_id: str = "", within_days: int = 30,
           facts: dict | None = None, draft_with_model: bool = False) -> dict:
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

    # --- 1. does this need something no knowledge base holds ---------------
    #
    # Asked BEFORE the blocked check, because a question needing live data is
    # not a gap in the knowledge base and must not be filed as one. Filing it
    # as unanswerable would put "where is my order" on the authoring backlog
    # for ever, where no amount of writing could ever satisfy it.
    declared = bundle.get("needs_lookup") or []
    if declared and not facts:
        # ANY declared lookup routes here, not only the ones that can run.
        # A missing parameter and an unconnected Shopify are both reasons the
        # caller must act on, and neither is something authoring can fix —
        # which is what filing them as blocked would have implied.
        return {
            "ok": False, "stage": "lookup", "situation": situation,
            "needs": [{"call": n["tool"], "with": n["have"],
                       "returns": n["returns"], "ready": n["ready"],
                       "blocked_because": n["blocked_because"]}
                      for n in declared],
            "ready_to_call": [n["tool"] for n in declared if n["ready"]],
            "bundle": bundle,
            "note": ("this needs live data, not more knowledge. Call what is "
                     "ready, then ask again with facts={...}. Nothing was "
                     "filed as a knowledge gap, because there is none — no "
                     "amount of authoring answers 'where is my order'."),
        }

    # --- 2. unsafe to send at all -----------------------------------------
    # The only genuine stop: with no ban list the validator has nothing to
    # check against, so "clean" would be a false assurance. Everything else
    # that used to stop here is now context handed over with its grounding
    # labelled.
    if bundle.get("blocked_on"):
        return _blocked(bundle["blocked_on"], "unsafe")

    # --- 3. no pre-approved answer is not a refusal ------------------------
    #
    # This was the design error worth naming. Refusing here made a missing row
    # able to veto an intelligence that had the brand rules, the positioning,
    # the catalogue and every approved claim in front of it — plenty to write
    # a good answer from. The layer's job is to supply context and say how
    # strong it is; what to do with that belongs to the reader.
    #
    # The guard against invention stays exactly where it belongs: on the way
    # out, in `validator`, which is code and fails closed.
    # Assemble ONLY on a confident match. `resolve` hands unranked objections
    # to whatever is reading, because a reader can judge relevance — but this
    # function has no judgement in it, and picking the top of an unranked list
    # is precisely the plausible-answer-to-the-wrong-question failure. So an
    # unranked bundle goes to the caller intact, candidates included, rather
    # than being answered from here.
    confident = (bundle.get("grounding") or {}).get("level") == "answered"
    if not confident:
        drafted, draft_note, verdict = "", "", None
        if draft_with_model:
            drafted, draft_note = _draft(tenant, utterance, bundle)
            if drafted:
                # Same gate as an approved answer. A model draft is exactly
                # the case the validator exists for -- it is the only text in
                # this system nobody signed off on.
                verdict = validator.check(
                    tenant, drafted, claim_ids=[c["claim_id"] for c
                                                in bundle.get("claims", [])],
                    entity_key=entity_key, conversation_id=conversation_id,
                    require_citation=False)
                if not verdict["ok"]:
                    drafted, draft_note = "", "; ".join(
                        f"{f['rule']}: {f['detail']}" for f in verdict["failures"])
        ledger.record(tenant, system_key, situation=situation,
                      entity_key=entity_key, status="draft_from_context",
                      run_id=run_id, conversation_id=conversation_id,
                      format="reply", blocked_on=[])
        return {
            "ok": True,
            "mode": "draft_from_context",
            "draft": drafted,
            "draft_blocked_by": draft_note,
            "validated": (verdict["ok"] if verdict else None),
            "checks_run": (verdict["checked"] if verdict else []),
            "grounding": bundle.get("grounding", {}),
            "context": {
                "rules": bundle.get("rules", {}),
                "claims": [
                    {"claim": c.claim, "evidence": c.evidence or "",
                     "claim_id": c.id, "situations": sorted(c.situations or [])}
                    for c in kb.claims(tenant, entity_key=entity_key or None,
                                       limit=6)],
                "entities": bundle.get("entities", []),
                "conversation": bundle.get("conversation", {}),
                # Candidates, explicitly not an answer. A reader that can weigh
                # relevance should see them; this function picking one would be
                # the judgement it does not have.
                "possible_objections": bundle.get("objections", []),
            },
            "gaps": bundle.get("gaps", []),
            "situation": situation,
            "validate_with": {
                "endpoint": "validator.check",
                "why": "draft freely, then run it through the validator — the "
                       "ban list, citations, stock and repeats are enforced "
                       "on the way out, not by withholding context",
            },
            "note": ("no pre-approved answer for this, which is not a reason "
                     "to say nothing. Everything above is real and current. "
                     "Draft from it, then validate."),
        }

    # --- 2. assemble, from what a human already approved ------------------
    top = bundle["objections"][0]
    claim_ids = [c["claim_id"] for c in top.get("support", []) if c.get("claim_id")]
    body = (top.get("response") or "").strip()

    # Live facts are appended as data, never woven into the approved sentence.
    # The response is wording a human signed off; editing it to fit a tool
    # result would be re-authoring it without the approval, and the whole
    # reason this runs without a model is that nobody is doing that.
    if facts:
        body = body + "\n\n" + "\n".join(
            f"{k}: {v}" for k, v in facts.items() if str(v).strip())

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


_DRAFT_SYSTEM = """You are drafting a reply on behalf of this brand.

Use ONLY what the context supports. Where you do not know something, say so
plainly rather than guessing — a customer would rather be told "let me check"
than be told something wrong.

Never state a price, a date or a policy that is not in the context. The hard
rules are enforced in code after you write, so a draft breaking one is thrown
away rather than softened.

Match the house voice. 3-6 sentences. No subject line, no signature."""


def _draft(tenant: str, utterance: str, bundle: dict) -> tuple[str, str]:
    """Write a reply from the bundle. Returns (draft, why_not).

    The ONLY model call in this file, and it sits exactly where the platform's
    first locked decision puts one: content drafting, at the edge, with
    selection and validation as deterministic code either side of it.
    """
    from . import config
    if not config.ANTHROPIC_API_KEY:
        return "", "ANTHROPIC_API_KEY is not set"
    try:
        import anthropic
        parts = [bundle["rules"]["block"].strip()]
        if bundle.get("claims"):
            parts.append("\n## Proof you may lean on")
            for c in bundle["claims"]:
                parts.append(f"- {c['claim']} ({c['evidence']}) [{c['scope']}]")
        if bundle.get("objections"):
            parts.append("\n## Answers already approved for similar questions")
            for o in bundle["objections"]:
                parts.append(f"- Q: {o['objection']}\n  A: {o['response']}")
        if bundle.get("correspondence"):
            parts.append("\n## What we have said before, in prior threads")
            for h in bundle["correspondence"]:
                parts.append(f"- [{h['kind']}] {h.get('subject') or ''}\n"
                             f"  {(h.get('excerpt') or '')[:400]}")
        if bundle.get("conversation", {}).get("open_commitments"):
            parts.append("\n## Already promised to THIS person — do not contradict")
            for c in bundle["conversation"]["open_commitments"]:
                parts.append(f"- {c['kind']}: {c['value']}")
        parts.append(f"\n(grounding: {bundle['grounding']['level']})")

        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model=config.CLAUDE_MODEL, max_tokens=600,
            system=_DRAFT_SYSTEM,
            messages=[{"role": "user",
                       "content": "\n".join(parts)
                                  + f"\n\n---\nThey wrote:\n{utterance}"}])
        try:
            from . import usage
            usage.log_usage("responder_draft", config.CLAUDE_MODEL, msg)
        except Exception:  # noqa: BLE001
            pass
        return msg.content[0].text.strip(), ""
    except Exception as exc:  # noqa: BLE001
        return "", f"{exc.__class__.__name__}: {str(exc)[:120]}"
