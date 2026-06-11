"""Background worker: polls every inbox, triages, schedules digests."""
import logging
import time

from apscheduler.schedulers.background import BackgroundScheduler

from . import approvals, config, db, digest, gmail_client, triage, whatsapp

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


def process_emails(alias: str, emails: list[dict], new_approvals: list[str]) -> None:
    for email in emails:
        if already_seen(email["id"]):
            continue
        trusted = is_trusted(email["from"])
        result = triage.triage_email(email, alias, trusted)
        action = result["action"]
        detail = result.get("reason", "")

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
                },
                notify=False,  # batched at end of cycle
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
                category=result.get("category"), action=logged, detail=detail,
            ))
            s.commit()


def poll_all() -> None:
    new_approvals: list[str] = []
    for alias in config.GMAIL_ACCOUNTS:
        try:
            process_emails(alias, gmail_client.fetch_unread(alias), new_approvals)
        except Exception:  # noqa: BLE001 — one bad inbox must not kill the loop
            log.exception("inbox %s failed", alias)
    approvals.notify_batch(new_approvals)  # one email per cycle, not per item


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
    approvals.notify_batch(
        new_approvals,
        title=f"[BACKLOG] {len(new_approvals)} unanswered emails — drafts ready for review",
    )


def main() -> None:
    db.init_db()
    log.info("Worker starting. Inboxes: %s | WhatsApp: %s | auto-send: %s",
             list(config.GMAIL_ACCOUNTS), config.WHATSAPP_ENABLED,
             config.AUTO_SEND_ENABLED)
    backlog_sweep()  # idempotent: EmailLog dedup skips already-processed messages
    sched = BackgroundScheduler(timezone="America/New_York")
    sched.add_job(poll_all, "interval", minutes=config.POLL_INTERVAL_MIN)
    for hour in config.DIGEST_HOURS:
        sched.add_job(digest.send_digest, "cron", hour=hour, minute=0)
    sched.start()
    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
