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

    week_ahead = (dt.date.today() + dt.timedelta(days=7)).isoformat()
    with db.SessionLocal() as s:
        deadlines = (
            s.query(db.Deadline)
            .filter(db.Deadline.status.in_(["open", "alerted"]),
                    db.Deadline.due_date <= week_ahead)
            .order_by(db.Deadline.due_date)
            .all()
        )

    lines = [f"Assistant digest — {dt.datetime.now().strftime('%a %b %d, %I:%M%p')}\n"]

    if deadlines:
        lines.append("💸 MONEY DEADLINES (next 7 days):")
        for d in deadlines:
            lines.append(f"  • {d.due_date} — {d.description} ({d.amount}) [{d.account}]")
        lines.append("")

    if pending:
        lines.append(f"⏳ AWAITING YOUR APPROVAL ({len(pending)}):")
        for ap in pending:
            lines.append(f"  • [{ap.kind}] {ap.summary}")
        lines.append("")

    # DRAFTS THAT SHIPPED NEEDING A FIX. They carry no pending approval — by
    # design, since nothing defective is launchable — so before this they were
    # invisible in the one place the owner actually reads. A draft the owner
    # never hears about is the same as no draft, and the whole point of putting
    # it in the ESP was that they could see it (owner, 2026-08-22).
    with db.SessionLocal() as s:
        defective = (
            s.query(db.SystemRun)
            .filter(db.SystemRun.blocked_on.isnot(None),
                    db.SystemRun.created_at >= since)
            .order_by(db.SystemRun.created_at.desc())
            .all()
        )
    defective = [r for r in defective if (r.blocked_on or [])]
    if defective:
        lines.append(f"🔧 DRAFTED BUT NEEDS FIXING ({len(defective)}):")
        counts: dict[str, int] = {}
        for r in defective:
            for reason in (r.blocked_on or []):
                counts[str(reason)] = counts.get(str(reason), 0) + 1
            lines.append(f"  • {r.tenant} — {', '.join(r.blocked_on or [])}")
        # The same cause twice is an ACCOUNT problem, not an unlucky send —
        # which is the difference between fixing one email and fixing the
        # field that broke every one of them.
        repeat = sorted(((n, k) for k, n in counts.items() if n > 1),
                        reverse=True)
        for n, k in repeat:
            lines.append(f"  ↳ {k} hit {n} sends — fix this at the account, "
                         f"not one email at a time")
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
    from . import emailfmt

    body = build_digest()  # plain text — used for WhatsApp and as fallback

    # Structured pull for the HTML version
    since = db.utcnow() - dt.timedelta(hours=12)
    week_ahead = (dt.date.today() + dt.timedelta(days=7)).isoformat()
    with db.SessionLocal() as s:
        emails = (s.query(db.EmailLog).filter(db.EmailLog.seen_at >= since)
                  .order_by(db.EmailLog.seen_at.desc()).all())
        pending = s.query(db.Approval).filter(db.Approval.status == "pending").all()
        deadlines = (s.query(db.Deadline)
                     .filter(db.Deadline.status.in_(["open", "alerted"]),
                             db.Deadline.due_date <= week_ahead)
                     .order_by(db.Deadline.due_date).all())
    sections: dict[str, list] = {}
    for e in emails:
        sections.setdefault(e.action or "other", []).append(e)

    now = dt.datetime.now()
    when = now.strftime("%p")
    subject = (f"{'Morning' if when == 'AM' else 'Evening'} briefing — "
               f"{now.strftime('%a %b %d')}")
    gmail_client.send_email(
        config.NOTIFY_FROM_ALIAS, config.APPROVER_EMAIL, subject, body,
        html=emailfmt.digest_email(deadlines, pending, sections, when),
    )
    whatsapp.send_text(body)  # no-op until WhatsApp is enabled
