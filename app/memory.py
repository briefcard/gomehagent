"""Shared memory layer.

- Conversational: WhatsApp chat history (chat_messages) replayed each turn.
- Situational: durable Memory notes (ongoing tasks, decisions, standing
  instructions) injected into every prompt — chat AND email triage — so the
  whole system shares one working state.
"""
import datetime as dt

from . import db

# Keep the window tight: recency matters more than depth. Older context lives
# in working memory / records, not the raw transcript.
CHAT_WINDOW_DAYS = 3
CHAT_MAX_TURNS = 16
MEMORY_MAX = 25


def load_chat_history(thread: str = "admin") -> list[dict]:
    """Recent turns for ONE conversation thread as Anthropic messages. Each agent
    (and sub-thread) has its own thread, so contexts never bleed between agents."""
    since = db.utcnow() - dt.timedelta(days=CHAT_WINDOW_DAYS)
    with db.SessionLocal() as s:
        rows = (s.query(db.ChatMessage)
                .filter(db.ChatMessage.created_at >= since,
                        db.ChatMessage.thread == thread)
                .order_by(db.ChatMessage.created_at)
                .all())[-CHAT_MAX_TURNS:]
    messages: list[dict] = []
    for r in rows:
        if messages and messages[-1]["role"] == r.role:
            messages[-1]["content"] += "\n" + r.content  # merge consecutive
        else:
            messages.append({"role": r.role, "content": r.content})
    if messages and messages[0]["role"] == "assistant":
        messages.pop(0)  # API requires the first message to be from the user
    return messages


def save_turn(thread: str, role: str, content: str) -> None:
    with db.SessionLocal() as s:
        s.add(db.ChatMessage(thread=thread, role=role, content=content[:8000]))
        s.commit()


def remember(topic: str, content: str, scope: str = "global") -> str:
    """Save/update a working-memory note. scope = 'global' (all agents) or a role
    name ('admin', 'seo') so an agent's notes don't pollute the others."""
    with db.SessionLocal() as s:
        existing = (s.query(db.Memory)
                    .filter(db.Memory.topic == topic, db.Memory.scope == scope,
                            db.Memory.status == "active")
                    .first())
        if existing:
            existing.content = content
            existing.created_at = db.utcnow()
        else:
            s.add(db.Memory(topic=topic, content=content, scope=scope))
        s.commit()
    return f"Remembered under '{topic}'" + ("" if scope == "global" else f" ({scope})") + "."


def forget(topic: str, scope: str | None = None) -> str:
    """Archive a note by topic. If scope is given, only that scope's note (an
    agent can't archive another agent's or a global note)."""
    with db.SessionLocal() as s:
        q = s.query(db.Memory).filter(db.Memory.topic == topic,
                                      db.Memory.status == "active")
        if scope is not None:
            q = q.filter(db.Memory.scope == scope)
        n = q.update({"status": "archived"})
        s.commit()
    return f"Archived {n} note(s) on '{topic}'."


def memory_block(role: str = "", tenant: str = "") -> str:
    """Active memory for injection: GLOBAL notes + this role's own notes only, so
    one agent's working memory never contaminates another's context.

    When a tenant is given, notes belonging to a *different* client are excluded
    as well. Unattributed notes still appear — they are the pre-tenant ones, and
    dropping them would silently empty the agent's memory — but one client's
    working notes never reach a conversation about another.
    """
    with db.SessionLocal() as s:
        q = (s.query(db.Memory)
             .filter(db.Memory.status == "active",
                     (db.Memory.scope == "global") | (db.Memory.scope == role)))
        if tenant:
            q = q.filter(db.tenant_filter(db.Memory, tenant, include_unassigned=True))
        rows = q.order_by(db.Memory.created_at.desc()).limit(MEMORY_MAX).all()
    if not rows:
        return ""
    lines = [f"- [{r.topic}] {r.content} (noted {r.created_at:%b %d})" for r in rows]
    return ("\n\nWORKING MEMORY (ongoing tasks, decisions, standing "
            "instructions — treat as current truth unless contradicted):\n"
            + "\n".join(lines))


# ---------------------------------------------------------------------------
# All-clears: "that was me, stop raising it"
#
# The mail path escalated the same concerns five times because nothing could
# tell it a person had already looked. Worse, one working-memory note about a
# possible breach was inflating every security-shaped email that arrived after
# it — the Klaviyo escalation cited that note as its reason.
#
# A cleared concern is stored as a Memory under a reserved topic prefix rather
# than in a table of its own: memory is ALREADY injected into triage, already
# scoped per tenant and role, and already worded as current truth. What it
# lacked was a way to say "and this particular worry is answered".
# ---------------------------------------------------------------------------

CLEARED = "cleared:"


def clear_concern(what: str, because: str = "", scope: str = "global",
                  tenant: str = "") -> str:
    """Record that a person looked at something and it is fine.

    Deliberately about an EVENT, not a category. "The Klaviyo TOTP MFA added on
    20 Aug was me" is a fact that stays true; "ignore Authorize.net alerts"
    would suppress the carding attack that is actually happening. The block
    below tells the model exactly that, because the difference between the two
    is the difference between a quiet inbox and a missed breach.
    """
    what = (what or "").strip()
    if not what:
        return "An all-clear needs to say what is cleared."
    topic = CLEARED + what[:80]
    body = what + (f" — {because}" if because else "")
    with db.SessionLocal() as s:
        row = (s.query(db.Memory)
               .filter(db.Memory.topic == topic,
                       db.Memory.status == "active").first())
        if row:
            row.content, row.created_at = body, db.utcnow()
        else:
            s.add(db.Memory(topic=topic, content=body, scope=scope,
                            tenant=tenant or ""))
        s.commit()
    return f"Cleared: {what[:120]}"


def concerns(tenant: str = "") -> list[dict]:
    """Everything currently marked as looked-at-and-fine."""
    with db.SessionLocal() as s:
        q = (s.query(db.Memory)
             .filter(db.Memory.status == "active",
                     db.Memory.topic.like(CLEARED + "%")))
        if tenant:
            q = q.filter(db.tenant_filter(db.Memory, tenant,
                                          include_unassigned=True))
        return [{"topic": r.topic[len(CLEARED):], "content": r.content,
                 "when": db.as_utc(r.created_at).date().isoformat(),
                 "scope": r.scope, "tenant": r.tenant or ""}
                for r in q.order_by(db.Memory.created_at.desc()).all()]


def cleared_block(tenant: str = "") -> str:
    """The all-clears, for injection — with the one caveat that keeps them safe.

    Rendered apart from working memory rather than inside it, because these say
    something different: not "here is a fact" but "this particular worry has
    been answered". The caveat is load-bearing. Without it a model reads "the
    MFA change was fine" as "MFA changes are fine", and the next one — the real
    one — goes out as routine.
    """
    rows = concerns(tenant)
    if not rows:
        return ""
    lines = [f"- {r['content']} (cleared {r['when']})" for r in rows]
    return ("\n\nALREADY LOOKED AT AND FINE — Gomeh has personally accounted "
            "for each of these. Do NOT escalate them again, and do not treat "
            "them as evidence that something is wrong.\n"
            + "\n".join(lines)
            + "\nEach line clears THAT EVENT, not the category it belongs to. "
              "A NEW instance of the same kind of thing is still worth raising "
              "— say plainly that a previous one was cleared, and raise it "
              "anyway.")


def working_notes(tenant: str = "") -> list[dict]:
    """Active working memory, for a person to read and prune.

    None of this was visible anywhere. A note saying a breach may be under way
    is injected into every triage as current truth, and it goes on inflating
    every security-shaped email until somebody retires it — which nobody could
    do without first being able to see it.
    """
    with db.SessionLocal() as s:
        q = (s.query(db.Memory)
             .filter(db.Memory.status == "active",
                     ~db.Memory.topic.like(CLEARED + "%")))
        if tenant:
            q = q.filter(db.tenant_filter(db.Memory, tenant,
                                          include_unassigned=True))
        return [{"id": r.id, "topic": r.topic, "content": r.content,
                 "scope": r.scope, "tenant": r.tenant or "",
                 "when": db.as_utc(r.created_at).date().isoformat()}
                for r in q.order_by(db.Memory.created_at.desc()).all()]


def retire(note_id: str) -> str:
    """Drop one working-memory note by id."""
    with db.SessionLocal() as s:
        row = s.get(db.Memory, note_id)
        if not row:
            return f"No note {note_id!r}."
        row.status = "retired"
        s.commit()
        return f"Retired: {row.topic}"


def shipments_block(tenant: str) -> str:
    """Open shipment records — injected into triage and chat prompts.

    Scoped, and the scope is not optional. `tenant="*"` is the OWNER's
    cross-account view — the back office runs every business's logistics, so the
    admin agent legitimately sees all of it. A concrete key is ONE client's, and
    one client's shipments must never appear in another client's drafting prompt
    — which is exactly what an unscoped query did on the live mail path, seeding
    every tenant's triage with every other tenant's counterparties and gaps.

    An unresolved scope (``""``) sees only legacy unattributed rows, never
    another tenant's — the same fail-toward-less-exposure the rest of the
    tenant layer already follows. Legacy rows written before attribution are
    still shown to a concrete tenant via `include_unassigned`; a backfill is
    what lets that tighten to strict.
    """
    with db.SessionLocal() as s:
        q = s.query(db.Shipment).filter(db.Shipment.status != "closed")
        if tenant != "*":
            q = q.filter(db.tenant_filter(db.Shipment, tenant,
                                          include_unassigned=True))
        rows = q.order_by(db.Shipment.updated_at.desc()).limit(15).all()
    if not rows:
        return ""
    lines = []
    for r in rows:
        missing = [k for k, v in (r.docs or {}).items() if v == "missing"]
        lines.append(f"- {r.name}: {r.status}, ETA {r.eta or '?'}, "
                     f"counterparty {r.counterparty or '?'}"
                     + (f", missing docs: {', '.join(missing)}" if missing else "")
                     + (f" — {r.notes[:120]}" if r.notes else ""))
    return "\n\nOPEN SHIPMENTS (structured records — current truth):\n" + "\n".join(lines)


def add_lesson(lesson: str, scope: str = "global", origin: str = "") -> str:
    """Record a generalizable lesson read by ALL agents (or scope to a role)."""
    txt = lesson.strip()
    with db.SessionLocal() as s:
        existing = (s.query(db.Lesson)
                    .filter(db.Lesson.lesson.ilike(txt)).first())
        if existing:
            existing.hits = str(int(existing.hits or "0") + 1)
        else:
            s.add(db.Lesson(lesson=txt, scope=scope, origin=origin))
        s.commit()
    return f"Lesson recorded ({scope}): {txt[:80]}"


def lessons_block(role: str = "", tenant: str = "") -> str:
    """Global lessons + this role's lessons — injected into every agent.

    A lesson learned on one account may be specific to it ("this client hates
    exclamation marks"), so a tenant-tagged lesson only reaches that tenant's
    conversations. Untagged lessons stay universal, which is what `Lesson` was
    built for.
    """
    with db.SessionLocal() as s:
        q = s.query(db.Lesson).filter(
            (db.Lesson.scope == "global") | (db.Lesson.scope == role))
        if tenant:
            q = q.filter(db.tenant_filter(db.Lesson, tenant, include_unassigned=True))
        rows = q.order_by(db.Lesson.created_at.desc()).limit(30).all()
    if not rows:
        return ""
    return ("\n\nLESSONS LEARNED (hard-won corrections — these apply across "
            "tasks and were learned from real mistakes; obey them):\n"
            + "\n".join(f"- {r.lesson}" for r in rows))


def sender_history(sender_email: str, tenant: str, limit: int = 3) -> str:
    """What we previously did with this sender — for email triage context.

    Scoped, and the scope is required. The same forwarder is a counterparty for
    several clients, so an unscoped lookup let one client's prior handling of a
    shared sender seed another client's draft. `tenant="*"` is the owner's
    cross-account view; a concrete key is one client's history plus the legacy
    unattributed rows, never another tenant's.
    """
    with db.SessionLocal() as s:
        q = s.query(db.EmailLog).filter(
            db.EmailLog.sender.ilike(f"%{sender_email}%"))
        if tenant != "*":
            q = q.filter(db.tenant_filter(db.EmailLog, tenant,
                                          include_unassigned=True))
        rows = q.order_by(db.EmailLog.seen_at.desc()).limit(limit).all()
    if not rows:
        return ""
    lines = [f"- {r.seen_at:%b %d}: '{r.subject}' -> {r.action} ({r.detail})"
             for r in rows]
    return "\n\nPRIOR INTERACTIONS with this sender:\n" + "\n".join(lines)
