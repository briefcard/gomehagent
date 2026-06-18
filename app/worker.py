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
        # Read PDF attachments (up to 2, <5MB each) so triage sees their content
        email["pdfs"] = []
        for att in (email.get("attachments") or [])[:4]:
            if not att["filename"].lower().endswith(".pdf") or len(email["pdfs"]) >= 2:
                continue
            try:
                data = gmail_client.download_attachment(alias, email["id"],
                                                        att["attachment_id"])
                if len(data) < 5_000_000:
                    email["pdfs"].append({"filename": att["filename"], "data": data})
            except Exception:  # noqa: BLE001
                log.exception("pdf download failed: %s", att["filename"])
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

        # A reply arrived: close any follow-up timers on this thread
        with db.SessionLocal() as s:
            s.query(db.FollowUp).filter(
                db.FollowUp.thread_id == email["threadId"],
                db.FollowUp.status.in_(["waiting", "chased"]),
            ).update({"status": "closed"}, synchronize_session=False)
            s.commit()

        # Expense ledger: receipts captured for tax records
        ex = result.get("expense")
        if isinstance(ex, dict) and ex.get("vendor"):
            with db.SessionLocal() as s:
                s.add(db.Expense(account=alias, vendor=ex.get("vendor"),
                                 amount=ex.get("amount", ""),
                                 expense_date=ex.get("date", ""),
                                 source_subject=email["subject"]))
                s.commit()

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
            reply_cc = result.get("reply_cc", "")
            gmail_client.create_draft(
                alias, email["from"], result["reply_subject"] or f"Re: {email['subject']}",
                result["reply_body"], email["threadId"], cc=reply_cc,
            )
            ap_id = approvals.request_approval(
                "send_email",
                f"Reply drafted in [{alias}] to {email['from']}: {email['subject']}"
                + (" ⚠️ NEEDS FACTS" if detail.startswith("NEEDS-FACTS") else ""),
                {
                    "account": alias, "to": email["from"],
                    "subject": result["reply_subject"] or f"Re: {email['subject']}",
                    "body": result["reply_body"], "thread_id": email["threadId"],
                    "cc": reply_cc,
                    "inbound_from": email["from"],
                    "inbound_snippet": email["body"][:600],
                    "reason": detail,
                    "suggestion": result.get("suggestion") or "",
                    "bucket": bucket,
                    "expect_reply": bucket in ("logistics", "sales_leads", "client_comms"),
                },
                notify=False,  # announced on the APPROVAL_BATCH_MINUTES schedule
            )
            new_approvals.append(ap_id)
            logged = "drafted"
        elif action == "escalate":
            sugg = result.get("suggestion")
            note = (f"🚨 [{alias}] {email['from']} — {email['subject']}\n{detail}"
                    + (f"\n💡 {sugg}" if sugg else ""))
            whatsapp.send_text(note)
            if not config.WHATSAPP_ENABLED:
                gmail_client.send_email(
                    config.NOTIFY_FROM_ALIAS, config.APPROVER_EMAIL,
                    f"[URGENT] {email['subject']}", note + "\n\n" + email["body"][:2000],
                )
            logged = "escalated"
        else:
            # sales_orders stay UNREAD so Gomeh sees every order himself
            if bucket != "sales_orders":
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
    note = "Money deadlines within 3 days:\n" + "\n".join(lines)
    whatsapp.send_text("💸 " + note)
    if not config.WHATSAPP_ENABLED:
        from . import emailfmt
        gmail_client.send_email(
            config.NOTIFY_FROM_ALIAS, config.APPROVER_EMAIL,
            "Heads up — money deadlines in the next 3 days", note,
            html=emailfmt.text_to_html(note),
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


def follow_up_chase() -> None:
    """Daily: chase overdue follow-ups once; escalate after second silence."""
    import datetime as dt
    today = dt.date.today().isoformat()
    with db.SessionLocal() as s:
        due = (s.query(db.FollowUp)
               .filter(db.FollowUp.due_date <= today,
                       db.FollowUp.status.in_(["waiting", "chased"]))
               .all())
        items = [(f.id, f.status, f.account, f.to, f.subject, f.thread_id) for f in due]
    for fid, status, account, to, subject, thread_id in items:
        if status == "waiting":
            approvals.request_approval(
                "send_email",
                f"[Follow-up] No reply from {to}: {subject}",
                {"account": account, "to": to,
                 "subject": subject if subject.lower().startswith("re:") else f"Re: {subject}",
                 "body": ("Hi,\n\nJust following up on my note below — could you "
                          "give me an update when you have a moment?\n\nThank you,\n\n"
                          + ("Baci Milano Customer Care" if account == "baci"
                             else "Eien Health Customer Care" if account == "eien"
                             else "Gomeh")),
                 "thread_id": thread_id, "inbound_from": to,
                 "inbound_snippet": "(no reply received in 3 days)",
                 "reason": "Automatic follow-up: counterparty silent 3 days",
                 "bucket": "logistics", "expect_reply": False},
                notify=False,
            )
            with db.SessionLocal() as s:
                f = s.get(db.FollowUp, fid)
                f.status = "chased"
                f.due_date = (dt.date.today() + dt.timedelta(days=3)).isoformat()
                s.commit()
        else:  # already chased once -> escalate to Gomeh
            whatsapp.send_text(f"⚠️ Still no reply from {to} after a chase: "
                               f"\"{subject}\" [{account}]. Wants your call.")
            with db.SessionLocal() as s:
                f = s.get(db.FollowUp, fid)
                f.status = "escalated"
                s.commit()


_last_alert: dict[str, float] = {}


def alert_error(context: str, exc: Exception) -> None:
    """Tell Gomeh when something breaks — max once per hour per context."""
    import time as _t
    now = _t.time()
    if now - _last_alert.get(context, 0) < 3600:
        return
    _last_alert[context] = now
    note = (f"⚙️ Heads up — my {context} hit an error "
            f"({exc.__class__.__name__}: {str(exc)[:150]}). I'll keep retrying; "
            "if you see this repeatedly, something needs fixing.")
    try:
        whatsapp.send_text(note)
        if not config.WHATSAPP_ENABLED:
            gmail_client.send_email(config.NOTIFY_FROM_ALIAS, config.APPROVER_EMAIL,
                                    "Assistant error: " + context, note)
    except Exception:  # noqa: BLE001
        log.exception("alert delivery failed")


def _safe(fn, context: str):
    def wrapped() -> None:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            log.exception("%s failed", context)
            alert_error(context, exc)
    return wrapped


def weekly_cost_report() -> None:
    from . import usage
    r = usage.report(7)
    body = (f"Weekly API cost report (last 7 days)\n\n"
            f"Spend: ${r['est_cost_usd']}  |  Projected monthly: "
            f"${r['projected_monthly_usd']}\n"
            f"Cache hit rate: {r['cache_hit_rate_pct']}%  "
            f"(saved ~${r['est_saved_by_cache_usd']} via caching)\n"
            f"Calls: {r['calls']}\n\nBy purpose:\n"
            + "\n".join(f"  • {k}: {v['calls']} calls, ${v['cost_usd']}, "
                        f"{v['cache_hit_pct']}% cached"
                        for k, v in r["by_purpose"].items()))
    whatsapp.send_text("💵 " + body)
    if not config.WHATSAPP_ENABLED:
        from . import emailfmt
        gmail_client.send_email(config.NOTIFY_FROM_ALIAS, config.APPROVER_EMAIL,
                                "Weekly API cost report", body,
                                html=emailfmt.text_to_html(body))


def main() -> None:
    db.init_db()
    log.info("Worker starting. Inboxes: %s | WhatsApp: %s | auto-send: %s",
             list(config.GMAIL_ACCOUNTS), config.WHATSAPP_ENABLED,
             config.AUTO_SEND_ENABLED)
    # Startup jobs are wrapped so a failure can NEVER crash the worker (exit 1).
    _safe(voice_learn.ensure_profiles, "voice profiles")()
    _safe(bucket_backfill, "bucket backfill")()
    _safe(backlog_sweep, "backlog sweep")()
    sched = BackgroundScheduler(timezone="America/New_York")
    sched.add_job(_safe(poll_all, "inbox polling"), "interval",
                  minutes=config.POLL_INTERVAL_MIN)
    sched.add_job(_safe(approvals.notify_pending, "approval batching"),
                  "interval", minutes=config.APPROVAL_BATCH_MINUTES)
    sched.add_job(_safe(deadline_alerts, "deadline alerts"), "cron", hour=9, minute=0)
    sched.add_job(_safe(follow_up_chase, "follow-up chasing"), "cron",
                  hour=9, minute=30)
    from . import ops_jobs
    sched.add_job(_safe(ops_jobs.daily_review, "daily review"), "cron",
                  hour=8, minute=30)  # the 'expert second look'
    sched.add_job(_safe(weekly_cost_report, "cost report"), "cron",
                  day_of_week="mon", hour=8, minute=0)
    sched.add_job(_safe(ops_jobs.JOBS["business_pulse"], "business pulse"),
                  "cron", day_of_week="mon", hour=7, minute=30)
    sched.add_job(_safe(ops_jobs.JOBS["contract_expiry_watch"], "expiry watch"),
                  "cron", day_of_week="mon", hour=7, minute=0)
    # Meeting scans 3x daily: morning, afternoon, evening (EST)
    for h in (8, 13, 18):
        sched.add_job(_safe(ops_jobs.JOBS["meeting_scan"], "meeting scan"),
                      "cron", hour=h, minute=15)
    for hour in config.DIGEST_HOURS:
        sched.add_job(_safe(digest.send_digest, "digest"), "cron",
                      hour=hour, minute=0)
    sched.start()
    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
