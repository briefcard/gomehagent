"""Shared memory layer.

- Conversational: WhatsApp chat history (chat_messages) replayed each turn.
- Situational: durable Memory notes (ongoing tasks, decisions, standing
  instructions) injected into every prompt — chat AND email triage — so the
  whole system shares one working state.
"""
import datetime as dt

from . import db

CHAT_WINDOW_DAYS = 7
CHAT_MAX_TURNS = 30
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
