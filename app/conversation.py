"""Counterparty state — who we are talking to, where it stands, what we promised.

The knowledge half of this platform answers *what is true about this brand*.
This is the other half: *what is true about this conversation*. Every system on
the roadmap needs both, and until now only the first existed — which is why an
agent handed three email threads with the same company had no way to know they
were one thing.

Three rows, and each earns its place by closing a specific failure:

* ``Conversation`` — the state machine and the retrieval key. Its
  ``situations`` are what the KB serves objections and claims against, so this
  table is the join between the two halves.
* ``Touch`` — bounded history, and the idempotency guard. Reading a
  conversation never means replaying its messages.
* ``Commitment`` — what we told them. This is what turns "be effective without
  misleading" from a line in a prompt into something a validator can check.

Everything here is tenant-scoped on both sides. A read takes a tenant and
filters by it; there is deliberately no ``get(id)`` that trusts an id alone,
because an id from one client's queue must not resolve against another's.
"""
from __future__ import annotations

import datetime as dt

from . import db

# ---------------------------------------------------------------------------
# Stages are DATA, per system, not a branch per system in code.
#
# A system is a spec — that is the whole reason installing one for client #2
# costs an afternoon instead of a week. The moment a stage list is expressed as
# `if system_key == "lead_responder"` the fork has already happened, it is just
# not in a separate file yet.
#
# `terminal` is declared rather than inferred as "the last one". A lead that is
# lost and a lead that is won are both endings, and neither is last.
# ---------------------------------------------------------------------------
STAGES: dict[str, dict[str, tuple]] = {
    "lead_responder": {
        "stages": ("new", "contacted", "replied", "qualifying",
                   "meeting_booked", "won", "lost"),
        "terminal": ("won", "lost"),
    },
    "service_desk": {
        "stages": ("received", "diagnosing", "awaiting_customer",
                   "awaiting_internal", "resolved", "escalated"),
        "terminal": ("resolved",),
    },
    "venue_enquiry": {
        "stages": ("enquiry", "qualifying", "showing_scheduled", "showing_done",
                   "proposal_sent", "booked", "lost"),
        "terminal": ("booked", "lost"),
    },
    "influencer_outreach": {
        "stages": ("identified", "contacted", "replied", "negotiating",
                   "agreed", "delivered", "declined"),
        "terminal": ("delivered", "declined"),
    },
}

#: A system with no declared ladder still gets one. Better a coarse stage that
#: is honest than a system that cannot record where anything stands.
DEFAULT = {"stages": ("open", "working", "closed"), "terminal": ("closed",)}

OPEN, CLOSED, BLOCKED = "open", "closed", "blocked"


def stages(system_key: str) -> tuple:
    """The ordered ladder for one system."""
    return tuple(STAGES.get(system_key, DEFAULT)["stages"])


def terminal(system_key: str) -> tuple:
    """The stages that end a conversation. More than one, and not the last."""
    return tuple(STAGES.get(system_key, DEFAULT)["terminal"])


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------

def open_or_get(tenant: str, contact_id: str, system_key: str,
                subject: str = "", situations: list[str] | None = None,
                entity_key: str = "", external_ref: tuple | None = None
                ) -> tuple[db.Conversation, bool]:
    """The open conversation with this contact for this system, or a new one.

    This is the thread-merge point, and the reason it is a lookup rather than a
    unique constraint. Two email chains with the same person about the same job
    are one conversation and must land on one row — but a lead who goes quiet
    and comes back next quarter is genuinely a second conversation, and a
    constraint could not tell those apart. ``status == "open"`` can.

    ``external_ref`` is ``(source, ref)`` — a Gmail thread id, a form
    submission id. Every one that has been folded in is kept, so "which threads
    is this?" is answerable after the fact.

    Returns ``(conversation, created)``. Callers that care about the difference
    — a first touch reads differently from a fifth — get it without a second
    query.
    """
    with db.SessionLocal() as s:
        row = (s.query(db.Conversation)
               .filter(db.tenant_filter(db.Conversation, tenant),
                       db.Conversation.contact_id == contact_id,
                       db.Conversation.system_key == system_key,
                       db.Conversation.status == OPEN)
               .order_by(db.Conversation.opened_at.desc()).first())
        created = False
        if not row:
            ladder = stages(system_key)
            row = db.Conversation(
                tenant=tenant, contact_id=contact_id, system_key=system_key,
                subject=subject, stage=ladder[0], status=OPEN,
                situations=list(situations or []), entity_key=entity_key,
                external_refs=[])
            s.add(row)
            created = True
        else:
            # An existing conversation learns from a new thread; it does not
            # get overwritten by it. A later message naming an entity fills a
            # blank, and never replaces one somebody already set.
            if situations:
                row.situations = sorted(set(row.situations or []) | set(situations))
            if entity_key and not row.entity_key:
                row.entity_key = entity_key
            if subject and not row.subject:
                row.subject = subject
        if external_ref:
            refs = list(row.external_refs or [])
            pair = {"source": external_ref[0], "ref": external_ref[1]}
            if pair not in refs:
                refs.append(pair)
                row.external_refs = refs
        s.commit()
        s.refresh(row)
        s.expunge_all()
        return row, created


def get(tenant: str, conversation_id: str) -> db.Conversation | None:
    """One conversation, scoped. There is no lookup that trusts an id alone."""
    with db.SessionLocal() as s:
        row = (s.query(db.Conversation)
               .filter(db.tenant_filter(db.Conversation, tenant),
                       db.Conversation.id == conversation_id).first())
        if row:
            s.expunge_all()
        return row


def advance(tenant: str, conversation_id: str, stage: str,
            blocked_on: str = "", next_action_at: dt.datetime | None = None) -> str:
    """Move a conversation to a stage its system actually declares.

    An unknown stage is refused **by name**, the same way ``add_claim`` refuses
    a tag outside the vocabulary. A stage nobody declared is a typo or an
    invented step, and either way the next reader of that queue would be
    looking at a state that does not exist.

    Reaching a terminal stage closes the conversation, so "won" and "closed"
    cannot disagree.
    """
    with db.SessionLocal() as s:
        row = (s.query(db.Conversation)
               .filter(db.tenant_filter(db.Conversation, tenant),
                       db.Conversation.id == conversation_id).first())
        if not row:
            return "No such conversation for this account."
        ladder = stages(row.system_key)
        if stage not in ladder:
            return (f"Unknown stage '{stage}' for {row.system_key}. "
                    f"Declared stages: {', '.join(ladder)}")
        row.stage = stage
        if blocked_on:
            row.status, row.blocked_on = BLOCKED, blocked_on
        elif row.status == BLOCKED:
            row.status, row.blocked_on = OPEN, ""
        if next_action_at is not None:
            row.next_action_at = next_action_at
        if stage in terminal(row.system_key):
            row.status = CLOSED
            row.outcome = row.outcome or stage
            row.closed_at = db.utcnow()
            row.next_action_at = None
        s.commit()
        return f"Moved to {stage}."


def close(tenant: str, conversation_id: str, outcome: str = "") -> str:
    """End a conversation without walking it to a terminal stage."""
    with db.SessionLocal() as s:
        row = (s.query(db.Conversation)
               .filter(db.tenant_filter(db.Conversation, tenant),
                       db.Conversation.id == conversation_id).first())
        if not row:
            return "No such conversation for this account."
        row.status, row.outcome = CLOSED, outcome or "abandoned"
        row.closed_at, row.next_action_at = db.utcnow(), None
        s.commit()
        return f"Closed ({row.outcome})."


def due(tenant: str, system_key: str = "", at: dt.datetime | None = None) -> list:
    """Open conversations whose next action has come due. The work queue."""
    at = at or db.utcnow()
    with db.SessionLocal() as s:
        q = (s.query(db.Conversation)
             .filter(db.tenant_filter(db.Conversation, tenant),
                     db.Conversation.status == OPEN,
                     db.Conversation.next_action_at.isnot(None)))
        if system_key:
            q = q.filter(db.Conversation.system_key == system_key)
        rows = [r for r in q.all() if db.as_utc(r.next_action_at) <= at]
        rows.sort(key=lambda r: db.as_utc(r.next_action_at))
        s.expunge_all()
        return rows


# ---------------------------------------------------------------------------
# Touches
# ---------------------------------------------------------------------------

def record_touch(tenant: str, conversation_id: str, direction: str = "out",
                 channel: str = "email", summary: str = "", ref: str = "",
                 run_id: str = "", approval_id: str = "",
                 idempotency_key: str = "") -> tuple[db.Touch | None, bool, str]:
    """Record a message. Returns ``(touch, created, note)``.

    **An outbound touch without an idempotency key is refused.** This codebase
    already has a known unfixed double-send: a worker restarting mid-publish
    sends twice, because nothing held a key it could check. A guard that is
    optional is a guard that is absent on the one call site that needed it, so
    the key is mandatory in the direction where sending twice costs something.

    Inbound messages default their key to the provider's own message id, which
    is a better key than anything we could mint — it is the same id whichever
    worker picks the message up.

    A second call with a key already on file writes nothing and returns the
    original with ``created=False``. That is the whole contract: safe to retry.
    """
    if direction == "in" and not idempotency_key and ref:
        idempotency_key = f"in:{ref}"
    if direction == "out" and not idempotency_key:
        return (None, False,
                "An outbound touch needs an idempotency_key — without one a "
                "restarted worker sends it twice.")

    with db.SessionLocal() as s:
        conv = (s.query(db.Conversation)
                .filter(db.tenant_filter(db.Conversation, tenant),
                        db.Conversation.id == conversation_id).first())
        if not conv:
            return None, False, "No such conversation for this account."

        if idempotency_key:
            seen = (s.query(db.Touch)
                    .filter(db.tenant_filter(db.Touch, tenant),
                            db.Touch.idempotency_key == idempotency_key).first())
            if seen:
                s.expunge_all()
                return seen, False, "Already recorded — nothing sent twice."

        row = db.Touch(
            tenant=tenant, conversation_id=conversation_id, direction=direction,
            channel=channel, summary=summary, ref=ref, run_id=run_id,
            approval_id=approval_id, idempotency_key=idempotency_key,
            stage_at=conv.stage)
        s.add(row)
        conv.last_touch_at = db.utcnow()
        s.commit()
        s.refresh(row)
        s.expunge_all()
        return row, True, "Recorded."


def touches(tenant: str, conversation_id: str, limit: int = 50) -> list:
    """The exchange, newest last. Bounded — state lives on the conversation."""
    with db.SessionLocal() as s:
        rows = (s.query(db.Touch)
                .filter(db.tenant_filter(db.Touch, tenant),
                        db.Touch.conversation_id == conversation_id)
                .order_by(db.Touch.sent_at.desc()).limit(limit).all())
        s.expunge_all()
        return list(reversed(rows))


# ---------------------------------------------------------------------------
# Commitments
# ---------------------------------------------------------------------------

def commit_to(tenant: str, conversation_id: str, kind: str, value: str,
              detail: str = "", due_at: dt.datetime | None = None,
              stated_in: str = "") -> tuple[db.Commitment | None, str]:
    """Record something we told them we would do.

    A commitment with no value is not a commitment, it is a note — and a note
    that reads like a promise is worse than neither, because a drafter will
    treat it as one. Refused rather than stored empty.
    """
    if not (value or "").strip():
        return None, "A commitment needs a value — what was actually promised."
    with db.SessionLocal() as s:
        conv = (s.query(db.Conversation)
                .filter(db.tenant_filter(db.Conversation, tenant),
                        db.Conversation.id == conversation_id).first())
        if not conv:
            return None, "No such conversation for this account."
        row = db.Commitment(tenant=tenant, conversation_id=conversation_id,
                            kind=kind, value=value.strip(), detail=detail,
                            due_at=due_at, stated_in=stated_in, status=OPEN)
        s.add(row)
        s.commit()
        s.refresh(row)
        s.expunge_all()
        return row, f"Recorded: {kind} — {value.strip()}"


def settle(tenant: str, commitment_id: str, status: str, note: str = "") -> str:
    """Close a commitment as met, broken or withdrawn."""
    if status not in ("met", "broken", "withdrawn"):
        return "Status must be met, broken or withdrawn."
    with db.SessionLocal() as s:
        row = (s.query(db.Commitment)
               .filter(db.tenant_filter(db.Commitment, tenant),
                       db.Commitment.id == commitment_id).first())
        if not row:
            return "No such commitment for this account."
        row.status, row.settled_note = status, note
        row.settled_at = db.utcnow()
        s.commit()
        return f"Marked {status}."


def open_commitments(tenant: str, conversation_id: str = "") -> list:
    """What is still outstanding — for one conversation, or the whole account.

    This is the read a drafter makes before it says anything about a price or a
    date, and the read a validator makes before an output goes out.
    """
    with db.SessionLocal() as s:
        q = (s.query(db.Commitment)
             .filter(db.tenant_filter(db.Commitment, tenant),
                     db.Commitment.status == OPEN))
        if conversation_id:
            q = q.filter(db.Commitment.conversation_id == conversation_id)
        rows = q.order_by(db.Commitment.stated_at).all()
        s.expunge_all()
        return rows


# ---------------------------------------------------------------------------
# The read step 03 will call
# ---------------------------------------------------------------------------

def state_for(tenant: str, contact_id: str = "", system_key: str = "",
              conversation_id: str = "") -> dict:
    """Everything the resolver needs about where this stands.

    Absence is reported, not implied. A contact with no conversation returns
    ``exists: False`` and a reason — not an empty dict, which reads downstream
    as "nothing has happened" and is indistinguishable from "we never looked".
    That distinction is the one this codebase keeps having to relearn.
    """
    row = None
    if conversation_id:
        row = get(tenant, conversation_id)
    elif contact_id:
        with db.SessionLocal() as s:
            q = (s.query(db.Conversation)
                 .filter(db.tenant_filter(db.Conversation, tenant),
                         db.Conversation.contact_id == contact_id,
                         db.Conversation.status == OPEN))
            if system_key:
                q = q.filter(db.Conversation.system_key == system_key)
            row = q.order_by(db.Conversation.opened_at.desc()).first()
            if row:
                s.expunge_all()

    if not row:
        return {"exists": False,
                "why": ("no open conversation for this contact"
                        if contact_id or conversation_id
                        else "no contact or conversation given"),
                "situations": [], "open_commitments": [], "touch_count": 0}

    commitments = open_commitments(tenant, row.id)
    hist = touches(tenant, row.id)
    return {
        "exists": True,
        "conversation_id": row.id,
        "system_key": row.system_key,
        "stage": row.stage,
        "stages": list(stages(row.system_key)),
        "status": row.status,
        "blocked_on": row.blocked_on or "",
        "situations": list(row.situations or []),
        "entity_key": row.entity_key or "",
        "subject": row.subject or "",
        "external_refs": list(row.external_refs or []),
        "touch_count": len(hist),
        "last_direction": hist[-1].direction if hist else "",
        "awaiting": ("them" if hist and hist[-1].direction == "out"
                     else "us" if hist else "first contact"),
        "next_action_at": row.next_action_at,
        "open_commitments": [
            {"id": c.id, "kind": c.kind, "value": c.value,
             "due_at": c.due_at, "detail": c.detail or ""}
            for c in commitments],
    }
