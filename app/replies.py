"""One reply per conversation, whoever writes it.

Three systems sit on the same inbox — `inbox_triage`, `service_desk`,
`lead_responder` — and today only the first produces anything, so nothing can
collide. That is a fact about the build, not a property of the design, and it
stops being true the moment a generator lands. This module is the property.

**Why the existing guards do not cover it.** `worker.already_seen` is keyed on
a Gmail MESSAGE id, so it stops one email being triaged twice and says nothing
about two different systems answering the same thread. `Conversation.system_key`
records an owner but is written on the substrate path only. And the two paths
record in different places — triage writes `EmailLog` and an `Approval`, the
substrate writes `Output` — so neither can see the other. Nothing joins them,
which is exactly how a customer gets two replies to one question.

This codebase has already paid for that shape once: an approval built from a
COPY of a draft meant approving it later "would deliver the original text A
SECOND TIME to the same customer on the same thread". Same failure, one level
up.

**The rule: a thread has one owner, and the second system to arrive refuses.**
It refuses by NAME — saying which system already replied and when — because a
silent skip looks identical to a system that is broken, and somebody would go
and debug the wrong thing.

**Routing so it rarely comes up.** The bucket triage already computes decides
which system owns a reply. Declared as data (`ROUTES`) rather than branching
in code, so adding a system is an edit here and not a new `elif` in the mail
loop.
"""
from __future__ import annotations

import datetime as dt

from . import db

#: Which system owns a reply, by the bucket triage already assigns.
#:
#: A bucket with no entry belongs to `inbox_triage` — the general path — which
#: is the honest default: a system that has not claimed a kind of mail should
#: not silently start answering it because somebody added a row.
ROUTES = {
    "sales_leads": "lead_responder",
    "order_routine": "service_desk",
    "order_basic": "service_desk",
    "order_issue": "service_desk",
}

#: Systems whose runs come from the MAIL PATH rather than from the substrate.
#:
#: Derived from `ROUTES` rather than listed again, because a hand-kept second
#: copy is the one that goes stale — and going stale here means `systems_tick`
#: filing "no generator yet" against a system whose work is being done every
#: day by triage.
HANDLED_BY_MAIL = frozenset({"inbox_triage"} | set(ROUTES.values()))

#: How long an owned thread stays owned. A conversation that went quiet for a
#: fortnight and comes back is a new exchange, not a double-reply risk.
OWNED_FOR_DAYS = 14


def route(bucket: str) -> str:
    """The system that owns a reply to this kind of mail."""
    return ROUTES.get(bucket or "", "inbox_triage")


def owner(tenant: str, thread_id: str) -> dict:
    """Who has already replied to this thread, or {}.

    Reads BOTH ledgers, because the two paths write to different ones and a
    check that consults one is a check that fails exactly when it matters.
    Returns the most recent, so "who has this" is answered rather than "did
    anybody ever".
    """
    if not thread_id:
        return {}
    since = db.utcnow() - dt.timedelta(days=OWNED_FOR_DAYS)
    found: list[dict] = []

    with db.SessionLocal() as s:
        # The mail path: an EmailLog row that produced a reply.
        q = (s.query(db.EmailLog)
             .filter(db.EmailLog.thread_id == thread_id,
                     db.EmailLog.seen_at >= since,
                     db.EmailLog.action.in_(("drafted", "auto_replied"))))
        if tenant:
            q = q.filter(db.EmailLog.tenant == tenant)
        for r in q.all():
            found.append({"system": "inbox_triage", "what": r.action,
                          "when": db.as_utc(r.seen_at)})

        # Anything that queued a reply for approval — the substrate included.
        # Matched on the payload's thread, which is what `worker` writes and
        # what any generator queueing a reply has to carry anyway.
        aq = s.query(db.Approval).filter(db.Approval.kind == "send_email",
                                         db.Approval.created_at >= since)
        if tenant:
            aq = aq.filter(db.Approval.tenant == tenant)
        for r in aq.all():
            if (r.payload or {}).get("thread_id") != thread_id:
                continue
            if r.status in ("denied", "expired", "draft_discarded"):
                # Decided against, or the draft was deleted without being
                # sent — either way nobody wrote to this customer, so the
                # thread is free again. Leaving a discarded draft owning the
                # thread would block every other system from ever answering
                # a question that never got a reply.
                continue
            found.append({"system": _system_name(s, r.system_id) or "a system",
                          "what": f"approval {r.status}",
                          "when": db.as_utc(r.created_at)})

    if not found:
        return {}
    latest = max(found, key=lambda f: f["when"])
    return {"system": latest["system"], "what": latest["what"],
            "when": latest["when"].isoformat(), "replies": len(found)}


def _system_name(session, system_id: str) -> str:
    if not system_id:
        return ""
    row = session.get(db.System, system_id)
    return row.key if row else ""


def may_reply(tenant: str, thread_id: str, system_key: str) -> dict:
    """May this system answer this thread? `{ok}` or `{ok: False, why}`.

    The same system replying again is allowed — a follow-up on a thread it
    already owns is a conversation, not a collision. A DIFFERENT system is
    refused, by name.
    """
    if not thread_id:
        # Nothing to collide on. Refusing here would block every reply that is
        # not part of a thread, which is most first contacts.
        return {"ok": True}
    held = owner(tenant, thread_id)
    if not held or held["system"] == system_key:
        return {"ok": True, "held_by": held.get("system", "")}
    return {"ok": False, "held_by": held["system"],
            "why": (f"{held['system']} already handled this thread "
                    f"({held['what']}, {held['when'][:16]}). Two systems "
                    f"answering one conversation is how a customer gets two "
                    f"replies to one question — if this one should own it, "
                    f"decide that rather than both writing.")}
