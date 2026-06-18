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


def load_chat_history() -> list[dict]:
    """Recent WhatsApp turns as Anthropic messages (alternating roles)."""
    since = db.utcnow() - dt.timedelta(days=CHAT_WINDOW_DAYS)
    with db.SessionLocal() as s:
        rows = (s.query(db.ChatMessage)
                .filter(db.ChatMessage.created_at >= since)
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


def save_turn(role: str, content: str) -> None:
    with db.SessionLocal() as s:
        s.add(db.ChatMessage(role=role, content=content[:8000]))
        s.commit()


def remember(topic: str, content: str) -> str:
    with db.SessionLocal() as s:
        existing = (s.query(db.Memory)
                    .filter(db.Memory.topic == topic, db.Memory.status == "active")
                    .first())
        if existing:
            existing.content = content
            existing.created_at = db.utcnow()
        else:
            s.add(db.Memory(topic=topic, content=content))
        s.commit()
    return f"Remembered under '{topic}'."


def forget(topic: str) -> str:
    with db.SessionLocal() as s:
        n = (s.query(db.Memory)
             .filter(db.Memory.topic == topic, db.Memory.status == "active")
             .update({"status": "archived"}))
        s.commit()
    return f"Archived {n} note(s) on '{topic}'."


def memory_block() -> str:
    """Active memory rendered for injection into system prompts."""
    with db.SessionLocal() as s:
        rows = (s.query(db.Memory).filter(db.Memory.status == "active")
                .order_by(db.Memory.created_at.desc()).limit(MEMORY_MAX).all())
    if not rows:
        return ""
    lines = [f"- [{r.topic}] {r.content} (noted {r.created_at:%b %d})" for r in rows]
    return ("\n\nWORKING MEMORY (ongoing tasks, decisions, standing "
            "instructions — treat as current truth unless contradicted):\n"
            + "\n".join(lines))


def shipments_block() -> str:
    """Open shipment records — injected into triage and chat prompts."""
    with db.SessionLocal() as s:
        rows = (s.query(db.Shipment)
                .filter(db.Shipment.status != "closed")
                .order_by(db.Shipment.updated_at.desc()).limit(15).all())
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


def lessons_block(role: str = "") -> str:
    """Global lessons + this role's lessons — injected into every agent."""
    with db.SessionLocal() as s:
        q = s.query(db.Lesson).filter(
            (db.Lesson.scope == "global") | (db.Lesson.scope == role))
        rows = q.order_by(db.Lesson.created_at.desc()).limit(30).all()
    if not rows:
        return ""
    return ("\n\nLESSONS LEARNED (hard-won corrections — these apply across "
            "tasks and were learned from real mistakes; obey them):\n"
            + "\n".join(f"- {r.lesson}" for r in rows))


def sender_history(sender_email: str, limit: int = 3) -> str:
    """What we previously did with this sender — for email triage context."""
    with db.SessionLocal() as s:
        rows = (s.query(db.EmailLog)
                .filter(db.EmailLog.sender.ilike(f"%{sender_email}%"))
                .order_by(db.EmailLog.seen_at.desc()).limit(limit).all())
    if not rows:
        return ""
    lines = [f"- {r.seen_at:%b %d}: '{r.subject}' -> {r.action} ({r.detail})"
             for r in rows]
    return "\n\nPRIOR INTERACTIONS with this sender:\n" + "\n".join(lines)
