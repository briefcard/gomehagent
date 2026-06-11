"""Background worker: polls every inbox, triages, schedules digests."""
import logging
import time

from apscheduler.schedulers.background import BackgroundScheduler

from . import approvals, config, db, digest, gmail_client, triage, voice_learn, whatsapp

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("worker")


def is_trusted(sender: str) -> bool:
    email = sender.split("<")[-1].rstrip(">").strip().lower()
    with db.SessionLocal() as s:
        c = s.query(db.Contact).filter(db.Contact.email == email).first()
        return bool(c and c.trusted == "yes")


def already_seen(message_id: str) -> bool:
    with db.SessionLocal() as s:
        return s.query(db.EmailLog).filter(
            db.EmailLog.gmail_message_id == message_id
        ).count() > 0


OWN_ADDRESSES = {a["email"].lower() for a in config.GMAIL_ACCOUNTS.values()}


def _sender_email(sender: str) -> str:
    return sender.split("<")[-1].rstrip(">").strip().lower()


def process_emails(alias: str, emails: list[dict], new_approvals: list[str]) -> None:
    for email in emails:
        if already_seen(email["id"]):
            continue
        # LOOP GUARD: never process mail sent by any of our own accounts
        # (approval batches, digests, escalations) — mark read and move on.
        if _sender_email(email["from"]) in OWN_ADDRESSES:
            gmail_client.mark_read(alias, email["id"])
            continue
        try:
            email["thread_context"] = gmail_client.get_thread_context(
                alias, email["threadId"], config.THREAD_CONTEXT_MESSAGES
            )
        except Exception:  # noqa: BLE001 — context is best-effort
            email["thread_context"] = ""
        trusted = is_trusted(email["from"])
        result = triage.triage_email(email, alias, trusted)
        action = result["action"]
        detail = result.get("reason", "")
        bucket = result.get("category", "notifications")

        # Organize: apply the bucket label in Gmail
        try:
            gmail_client.add_label(alias, email["id"], config.BUCKET_LABELS[bucket])
        except Exception:  # noqa: BLE001 — labeling is best-effort
            log.exception("labeling failed")

        # Money ledger: record any extracted deadline
        dl = result.get("deadline")
        if isinstance(dl, dict) and dl.get("due_date"):
            with db.SessionLocal() as s:
                s.add(db.Deadline(
                    account=alias, description=dl.get("what", email["subject"]),
                    amount=dl.get("amount", "unknown"), due_date=dl["due_date"],
                    source_subject=email["subject"],
                ))
                s.commit()

        # Training-wheels mode: until AUTO_SEND_ENABLED=true, nothing is sent
        # without approval — auto-replies become drafts in the approval batch.
        if action == "auto_reply" and not config.AUTO_SEND_ENABLED:
            action = "draft"
            detail += " [auto-send disabled: queued for approval]"
        log.info("[%s] %s -> %s (%s)", alias, email["subject"][:60], action, detail)

        if action == "auto_reply":
            gmail_client.send_email(
                alias, email["from"], result["reply_subject"] or f"Re: {email['subject']}",
                result["reply_body"], email["threadId"],
            )
            gmail_client.mark_read(alias, email["id"])
            logged = "auto_replied"
        elif action == "draft":
            gmail_client.create_draft(
                alias, email["from"], result["reply_subject"] or f"Re: {email['subject']}",
                result["reply_body"], email["threadId"],
            )
            ap_id = approvals.request_approval(
                "send_email",
                f"Reply drafted in [{alias}] to {email['from']}: {email['subject']}"
                + (" ⚠️ NEEDS FACTS" if detail.startswith("NEEDS-FACTS") else ""),
                {
                    "account": alias, "to": email["from"],
                    "subject": result["reply_subject"] or f"Re: {email['subject']}",
                    "body": result["reply_body"], "thread_id": email["threadId"],
                    "inbound_from": email["from"],
                    "inbound_snippet": email["body"][:600],
                    "reason": detail,
                },
                notify=False,  # announced on the APPROVAL_BATCH_MINUTES schedule
            )
            new_approvals.append(ap_id)
            logged = "drafted"
        elif action == "escalate":
            note = (f"🚨 [{alias}] {email['from']} — {email['subject']}\n{detail}")
            whatsapp.send_text(note)
            if not config.WHATSAPP_ENABLED:
                gmail_client.send_email(
                    config.NOTIFY_FROM_ALIAS, config.APPROVER_EMAIL,
                    f"[URGENT] {email['subject']}", note + "\n\n" + email["body"][:2000],
                )
            logged = "escalated"
        else:
            gmail_client.mark_read(alias, email["id"])
            logged = "ignored"

        with db.SessionLocal() as s:
            s.add(db.EmailLog(
                account=alias, gmail_message_id=email["id"], thread_id=email["threadId"],
                sender=email["from"], subject=email["subject"],
                category=bucket, action=logged, detail=detail,
            ))
            s.commit()


def bucket_backfill() -> None:
    """One-time: label the last BUCKET_BACKFILL_DAYS of every inbox so Gomeh's
    mail is organized from day one. Cheap model, no drafting."""
    with db.SessionLocal() as s:
        if s.get(db.Setting, "bucket_backfill_done"):
            return
    total = 0
    for alias in config.GMAIL_ACCOUNTS:
        try:
            for email in gmail_client.fetch_recent(alias, config.BUCKET_BACKFILL_DAYS):
                if already_seen(email["id"]) or _sender_email(email["from"]) in OWN_ADDRESSES:
                    continue
                bucket = triage.classify_only(email, alias)
                gmail_client.add_label(alias, email["id"], config.BUCKET_LABELS[bucket])
                with db.SessionLocal() as s:
                    s.add(db.EmailLog(
                        account=alias, gmail_message_id=email["id"],
                        thread_id=email["threadId"], sender=email["from"],
                        subject=email["subject"], category=bucket,
                        action="labeled", detail="backfill",
                    ))
                    s.commit()
                total += 1
        except Exception:  # noqa: BLE001
            log.exception("backfill failed for %s", alias)
    with db.SessionLocal() as s:
        s.merge(db.Setting(key="bucket_backfill_done", value=str(total)))
        s.commit()
    log.info("bucket backfill complete: %d emails labeled", total)


def deadline_alerts() -> None:
    """Daily: escalate anything costing money within 3 days; weekly look-ahead
    lives in the digest."""
    import datetime as dt
    soon = (dt.date.today() + dt.timedelta(days=3)).isoformat()
    with db.SessionLocal() as s:
        due = (
            s.query(db.Deadline)
            .filter(db.Deadline.status == "open", db.Deadline.due_date <= soon)
            .order_by(db.Deadline.due_date)
            .all()
        )
        if not due:
            return
        lines = [f"• {d.due_date} — {d.description} ({d.amount}) [{d.account}]" for d in due]
        for d in due:
            d.status = "alerted"
        s.commit()
    note = "💸 MONEY DEADLINES within 3 days:\n" + "\n".join(lines)
    whatsapp.send_text(note)
    if not config.WHATSAPP_ENABLED:
        gmail_client.send_email(
            config.NOTIFY_FROM_ALIAS, config.APPROVER_EMAIL,
            "[URGENT] Money deadlines approaching", note,
        )


def poll_all() -> None:
    new_approvals: list[str] = []
    for alias in config.GMAIL_ACCOUNTS:
        try:
            process_emails(alias, gmail_client.fetch_unread(alias), new_approvals)
        except Exception:  # noqa: BLE001 — one bad inbox must not kill the loop
            log.exception("inbox %s failed", alias)
    # NOTE: no notification here — approvals.notify_pending runs on its own
    # schedule so Gomeh gets at most one batch email per APPROVAL_BATCH_MINUTES.


def backlog_sweep() -> None:
    """First-run sweep: every email of the last BACKLOG_DAYS days that never
    got a reply -> triaged -> one big approval batch for Gomeh."""
    new_approvals: list[str] = []
    for alias in config.GMAIL_ACCOUNTS:
        try:
            emails = gmail_client.fetch_unanswered(alias, config.BACKLOG_DAYS)
            log.info("[%s] backlog sweep: %d unanswered threads", alias, len(emails))
            process_emails(alias, emails, new_approvals)
        except Exception:  # noqa: BLE001
            log.exception("backlog sweep %s failed", alias)
    if new_approvals:
        approvals.notify_pending(
            title=f"[Assistant · BACKLOG] {len(new_approvals)} unanswered emails — drafts ready",
        )


def main() -> None:
    db.init_db()
    log.info("Worker starting. Inboxes: %s | WhatsApp: %s | auto-send: %s",
             list(config.GMAIL_ACCOUNTS), config.WHATSAPP_ENABLED,
             config.AUTO_SEND_ENABLED)
    voice_learn.ensure_profiles()  # learn Gomeh's voice per inbox (first run only)
    bucket_backfill()  # one-time: organize recent mail into bucket labels
    backlog_sweep()  # idempotent: EmailLog dedup skips already-processed messages
    sched = BackgroundScheduler(timezone="America/New_York")
    sched.add_job(poll_all, "interval", minutes=config.POLL_INTERVAL_MIN)
    sched.add_job(approvals.notify_pending, "interval",
                  minutes=config.APPROVAL_BATCH_MINUTES)
    sched.add_job(deadline_alerts, "cron", hour=9, minute=0)
    for hour in config.DIGEST_HOURS:
        sched.add_job(digest.send_digest, "cron", hour=hour, minute=0)
    sched.start()
    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
