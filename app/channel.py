"""Ops channel router: Telegram when configured, WhatsApp otherwise.

Callers use `channel.send_text(...)` / `channel.send_approval(...)` and never
branch on which surface is live. Signatures are identical to `whatsapp.py`, so
this is a drop-in for existing call sites.

Safety property that makes the migration cheap: with TELEGRAM_ENABLED false
every function here is a pass-through to `whatsapp`, so swapping call sites
changes nothing until the Telegram env vars are actually set (Aug 2026).
"""
from . import config


def active() -> str:
    if config.TELEGRAM_ENABLED:
        return "telegram"
    if config.WHATSAPP_ENABLED:
        return "whatsapp"
    return "email"


def send_text(body: str, email_fallback: bool = True):
    if config.TELEGRAM_ENABLED:
        from . import telegram
        return telegram.send_text(body, email_fallback=email_fallback)
    from . import whatsapp
    return whatsapp.send_text(body, email_fallback=email_fallback)


def send_approval(approval_id: str, summary: str, detail: dict | None = None) -> bool:
    if config.TELEGRAM_ENABLED:
        from . import telegram
        return telegram.send_approval(approval_id, summary, detail)
    from . import whatsapp
    return whatsapp.send_approval(approval_id, summary, detail)


def ask(question: str, field: str, options: list[str] | None = None):
    """Blocking-input prompt. WhatsApp has no editable-message equivalent, so
    it degrades to a plain question."""
    if config.TELEGRAM_ENABLED:
        from . import telegram
        return telegram.ask(question, field, options)
    from . import whatsapp
    return whatsapp.send_text(f"❓ {question}")


def resolve(message_id, outcome: str) -> None:
    """Rewrite an answered prompt in place. No-op off Telegram."""
    if config.TELEGRAM_ENABLED and message_id:
        from . import telegram
        telegram.resolve(message_id, outcome)
