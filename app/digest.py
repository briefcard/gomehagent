"""Morning (8am) and evening (8pm) EST digests."""
import datetime as dt

from . import config, db, gmail_client, whatsapp


def build_digest(hours_back: int = 12) -> str:
    since = db.utcnow() - dt.timedelta(hours=hours_back)
    with db.SessionLocal() as s:
        emails = (
            s.query(db.EmailLog)
            .filter(db.EmailLog.seen_at >= since)
            .order_by(db.EmailLog.seen_at.desc())
            .all()
        )
        pending = (
            s.query(db.Approval).filter(db.Approval.status == "pending").all()
        )

    lines = [f"Assistant digest — {dt.datetime.now().strftime('%a %b %d, %I:%M%p')}\n"]

    if pending:
        lines.append(f"⏳ AWAITING YOUR APPROVAL ({len(pending)}):")
        for ap in pending:
            lines.append(f"  • [{ap.kind}] {ap.summary}")
        lines.append("")

    by_action: dict[str, list] = {}
    for e in emails:
        by_action.setdefault(e.action or "other", []).append(e)

    labels = {
        "auto_replied": "✅ Replied automatically",
        "drafted": "✍️ Drafted for your review",
        "escalated": "🚨 Escalated",
        "ignored": "🗑 Filtered (no action)",
    }
    for action, label in labels.items():
        items = by_action.get(action, [])
        if not items:
            continue
        lines.append(f"{label} ({len(items)}):")
        for e in items[:15]:
            lines.append(f"  • [{e.account}] {e.sender}: {e.subject}")
        lines.append("")

    if len(lines) == 1:
        lines.append("Quiet period — nothing needing attention.")
    return "\n".join(lines)


def send_digest() -> None:
    body = build_digest()
    gmail_client.send_email(
        config.NOTIFY_FROM_ALIAS, config.APPROVER_EMAIL, "Daily assistant digest", body
    )
    whatsapp.send_text(body)  # no-op until WhatsApp is enabled
