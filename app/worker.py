"""Background worker: polls every inbox, triages, schedules digests."""
import logging
import os
import time

from apscheduler.schedulers.background import BackgroundScheduler

from . import approvals, archive, config, db, digest, gmail_client, triage, voice_learn, whatsapp

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("worker")


def is_trusted(sender: str, alias: str = "") -> bool:
    """Is this sender trusted enough for a routine reply to auto-send?

    Scoped to the inbox's client. The same forwarder can now be a contact for
    several clients with a different trust level in each, so an unscoped lookup
    would let one client's `trusted=yes` authorise auto-send on another
    client's mail. Unassigned contacts still count — they are the pre-tenant
    rows and dropping them would silently switch auto-send off — but a contact
    belonging to a *different* client never does.
    """
    email = sender.split("<")[-1].rstrip(">").strip().lower()
    tenant = ""
    if alias:
        with db.SessionLocal() as s:
            row = s.query(db.Tenant).filter(db.Tenant.gmail_alias == alias).first()
            tenant = row.key if row else ""
    with db.SessionLocal() as s:
        q = s.query(db.Contact).filter(db.Contact.email == email)
        q = q.filter(db.tenant_filter(db.Contact, tenant, include_unassigned=True)
                     if tenant else db.Contact.tenant == db.UNASSIGNED)
        return any(c.trusted == "yes" for c in q.all())


def inboxes() -> list[tuple[str, str]]:
    """Every mailbox this worker polls, as (alias, tenant).

    Driven from the tenant registry rather than `GMAIL_ACCOUNTS` directly, so
    onboarding a client is a row instead of an env change plus a worker
    redeploy — which was the last place adding a client needed a deploy.

    An alias with no tenant is still polled, and reported as unattributed. The
    tempting version of this function returns only claimed inboxes; that one
    silently stops processing mail the moment a `gmail_alias` is mistyped, and
    nothing would say so. Absence is a third state here too.
    """
    from . import tenants
    claimed: dict[str, str] = {}
    for t in tenants.all_tenants(include_paused=False):
        if t.gmail_alias and t.gmail_alias in config.GMAIL_ACCOUNTS:
            claimed[t.gmail_alias] = t.key
    pairs = [(alias, claimed.get(alias, "")) for alias in config.GMAIL_ACCOUNTS]
    orphans = [a for a, k in pairs if not k]
    if orphans:
        log.warning("inboxes with no tenant (still polled, unattributed): %s",
                    ", ".join(orphans))
    return pairs


def already_seen(message_id: str) -> bool:
    with db.SessionLocal() as s:
        return s.query(db.EmailLog).filter(
            db.EmailLog.gmail_message_id == message_id
        ).count() > 0


OWN_ADDRESSES = {a["email"].lower() for a in config.GMAIL_ACCOUNTS.values()}


def _sender_email(sender: str) -> str:
    return sender.split("<")[-1].rstrip(">").strip().lower()


def _mail_system_id(tenant: str) -> str:
    """The `inbox_triage` system row for this account, created on first sight.

    Auto-created rather than seeded, deliberately. Every account with a mapped
    inbox is already running this pipeline whether or not somebody installed
    it on the Systems tab, and a run filed against a system that does not exist
    is the orphan the Diagnostics tab reports. It lands in `designed / shadow`
    like every other install, so appearing here grants it nothing — the send
    path is unchanged and still gated on the approval queue.
    """
    if not tenant:
        return ""
    try:
        from . import grounding, systems
        row = systems.find(tenant, grounding.SYSTEM_KEY)
        if not row:
            # Created LIVE, because it is running — the row records a fact.
            # Created `designed` it would read as switched off while answering
            # mail all day, and once the switch actually gates the mail path
            # (below) that mismatch would stop the inbox.
            row = systems.create(tenant, grounding.SYSTEM_KEY, "Inbox triage")
            systems.update(row.id, status="live")
            row = systems.find(tenant, grounding.SYSTEM_KEY)
        elif (row.status or "") == "designed":
            # One-time backfill for rows created before the switch meant
            # anything. `designed` here was never a decision — nobody chose it
            # — whereas `paused` was, and is left alone.
            systems.update(row.id, status="live")
            row = systems.find(tenant, grounding.SYSTEM_KEY)
        return row.id
    except Exception:                                            # noqa: BLE001
        return ""       # bookkeeping must never stop the inbox


def _mail_is_on(tenant: str) -> bool:
    """Is the mail path switched on for this account?

    Fails OPEN — no tenant, no row, or a lookup that raises all mean "run".
    A switch nobody has set is not a switch somebody turned off, and treating
    it as one would stop an inbox on the strength of a missing row.
    """
    if not tenant:
        return True
    try:
        from . import grounding, systems
        row = systems.find(tenant, grounding.SYSTEM_KEY)
        if not row:
            return True
        if (row.status or "") == "designed":
            return True     # never decided; `_mail_system_id` backfills it
        return systems.is_on(row)
    except Exception:                                            # noqa: BLE001
        return True


def _mail_run(tenant: str, email: dict) -> str:
    """Open a run for one inbound email. Returns "" if it could not be opened."""
    sid = _mail_system_id(tenant)
    if not sid:
        return ""
    try:
        from . import systems
        return systems.start_run(sid, tenant, trigger="inbound_email",
                                 ref=email.get("id", ""))
    except Exception:                                            # noqa: BLE001
        return ""


def _rehome_run(run_id: str, tenant: str, bucket: str) -> str:
    """File this run under the system the bucket belongs to, if it is installed.

    Triage is ONE executor doing several jobs. The systems are governance
    envelopes — a contract, an autonomy rung, standing guidance, metrics, a run
    ledger — and until now every mail run landed under `inbox_triage`, so
    `lead_responder` and `service_desk` had empty ledgers while triage answered
    their mail all day. Their guidance could never be earned and their autonomy
    could never be promoted, because nothing they governed had ever run.

    Re-homing on FINISH rather than at start, because the bucket is not known
    until triage has read the mail — that is the one moment we actually know
    which job this was.

    **Only to a system that is already installed.** A silent install would put
    a pipeline on somebody's Systems tab that they never chose, and the whole
    point of the envelope is that installing it is a decision. Not installed
    means the run stays with `inbox_triage`, which is the truth: triage did it,
    and nothing else has claimed that kind of mail.
    """
    from . import replies, systems
    key = replies.route(bucket)
    if key == "inbox_triage" or not tenant:
        return ""
    try:
        row = systems.find(tenant, key)
        if not row or not systems.is_on(row):
            # Not installed, or installed and switched OFF. Either way the run
            # stays with triage, which is the truth: triage did the work and
            # nothing else has claimed that kind of mail. Re-homing into a
            # paused system would fill the ledger of something the owner
            # deliberately stopped.
            return ""
        with db.SessionLocal() as s:
            run = s.get(db.SystemRun, run_id)
            if not run:
                return ""
            run.system_id = row.id
            s.commit()
        return key
    except Exception:                                            # noqa: BLE001
        return ""           # bookkeeping must never stop the inbox


def _finish_mail_run(run_id: str, action: str, result: dict,
                     tenant: str = "", bucket: str = "") -> None:
    """Close the run out with what actually happened to the draft.

    The stage is the ACTION, not the model's confidence: `escalate` is where a
    guard caught something or the mail needed a person, and recording it as a
    normal draft would hide every catch from `systems.stats` and from the
    Diagnostics verdict. `blocked_on` carries the reason so the backlog ranks
    by what actually cost an output.
    """
    if not run_id:
        return
    # `escalate` is `escalated`, NOT `blocked` — the owner caught this one.
    #
    # Routing a carding attack, an MFA change or a verification deadline to a
    # person is the CORRECT outcome, not a refusal. Filing it as `blocked` made
    # the Diagnostics log list the mail path's best work as problems, and put
    # each escalation's reasoning into `blocked_reasons()`, which ranks what to
    # go and WRITE into the knowledge base — where no amount of writing could
    # ever satisfy "verify this with TD Bank out of band".
    #
    # `ignore` is `skipped`, NOT `sent`: roughly half of inbound is promo that
    # correctly produces nothing, and counting those as sends would make the
    # success rate an artefact of how much junk arrived. `draft` stays open —
    # waiting on a person is not finished.
    stage = {"auto_reply": "sent", "draft": "draft",
             "escalate": "escalated", "ignore": "skipped"}.get(action, "draft")
    reason = (result.get("reason") or "")
    fields = {"output": (result.get("reply_body") or "")[:2000]}
    if stage == "escalated":
        # Kept on the run so the log can say WHY it was raised, without it
        # counting as a gap. `output` carries it; `blocked_on` deliberately
        # stays empty.
        fields["output"] = (reason or "escalated")[:2000]
    try:
        from . import systems
        systems.finish_run(run_id, stage, **fields)
        _rehome_run(run_id, tenant, bucket)
    except Exception:                                            # noqa: BLE001
        pass


def process_emails(alias: str, emails: list[dict], new_approvals: list[str],
                   tenant: str = "") -> None:
    """Triage a batch from one inbox. `tenant` is resolved once by the caller
    so every email in the batch is attributed and scoped identically."""
    from . import tenants as _tn
    tenant = tenant or _tn.for_alias(alias)
    # The switch decides whether the mail path runs at all.
    #
    # Owner's rule: the on/off mechanism dictates whether a system is running.
    # `inbox_triage` is a system like any other, so pausing it stops triage for
    # that account — labelling and drafting both. That is a real lever worth
    # having during an incident, and it was previously impossible: the row
    # existed and controlled nothing.
    #
    # Fails OPEN when there is nothing to consult. An unmapped inbox has no
    # System row, and a mailbox that cannot be switched off must not be treated
    # as switched off — that would silently stop mail nobody had turned off.
    if not _mail_is_on(tenant):
        log.info("[%s] inbox_triage is switched off — %d email(s) left alone",
                 alias, len(emails))
        return

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
                alias, email["threadId"], config.THREAD_CONTEXT_MESSAGES,
                # The message being acted on is printed above the thread under
                # its own heading; including it again made every threaded
                # prompt carry it twice.
                exclude_id=email.get("id", ""),
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
        trusted = is_trusted(email["from"], alias)

        # One run per triaged email, so the mail path finally has a ledger.
        #
        # `systems.stats` reported nothing for the pipeline that does most of
        # the work, the Diagnostics tab could not show a mail failure, and —
        # the one that matters most — `edits.record` writes the delta onto
        # `SystemRun.edit_diff` VIA the approval's `run_id`, which nothing on
        # this path ever set. So every rewrite the owner made was measured
        # against nothing and could never come back as guidance. Threading the
        # run is what closes that circle.
        #
        # Wrapped throughout: bookkeeping that can stop the inbox is worse than
        # no bookkeeping, and this runs against live customer mail.
        run_id = _mail_run(tenant, email)
        result = triage.triage_email(email, alias, trusted, tenant=tenant)
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
                s.add(db.Expense(account=alias, tenant=tenant,
                                 vendor=ex.get("vendor"),
                                 amount=ex.get("amount", ""),
                                 expense_date=ex.get("date", ""),
                                 source_subject=email["subject"]))
                s.commit()

        # Money ledger: record any extracted deadline
        dl = result.get("deadline")
        if isinstance(dl, dict) and dl.get("due_date"):
            with db.SessionLocal() as s:
                s.add(db.Deadline(
                    account=alias, tenant=tenant, description=dl.get("what", email["subject"]),
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
            # One reply per thread, whoever writes it.
            #
            # `already_seen` stops the same MESSAGE being triaged twice and says
            # nothing about a second system answering the same conversation.
            # Today nothing else produces, so this cannot fire — it is here
            # BEFORE the generators land rather than after the first customer
            # gets two answers to one question.
            from . import replies
            may = replies.may_reply(tenant, email["threadId"], "inbox_triage")
            if not may["ok"]:
                log.info("[%s] not drafting: %s", alias, may["why"])
                detail += f" [not drafted: {may['why'][:120]}]"
                _finish_mail_run(run_id, "ignore", result, tenant, bucket)
                logged = "deferred"
                with db.SessionLocal() as s:
                    s.add(db.EmailLog(
                        account=alias, tenant=tenant,
                        gmail_message_id=email["id"],
                        thread_id=email["threadId"], sender=email["from"],
                        subject=email["subject"], category=bucket,
                        action=logged, detail=detail))
                    s.commit()
                continue
            reply_cc = result.get("reply_cc", "")  # reply-all: preserve original CCs
            # The draft id is KEPT. It was thrown away, which is why the queue
            # and the mailbox could not stay in step: approving composed a
            # third message from a copy of what the draft said when it was
            # written, so an edit made in Gmail was silently discarded and the
            # draft itself was left to accumulate.
            draft_id = gmail_client.create_draft(
                alias, email["from"], result["reply_subject"] or f"Re: {email['subject']}",
                result["reply_body"], email["threadId"], cc=reply_cc,
            )
            ap_id = approvals.request_approval(
                "send_email",
                f"Reply drafted in [{alias}] to {email['from']}: {email['subject']}"
                + (" ⚠️ NEEDS FACTS" if detail.startswith("NEEDS-FACTS") else ""),
                run_id=run_id,
                system_id=_mail_system_id(tenant),
                payload={
                    "account": alias, "to": email["from"],
                    "draft_id": draft_id,
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
            # The all-clear travels WITH the alarm.
            #
            # The same concerns were raised five times because clearing one
            # meant knowing a URL existed and going to find it. An escalation
            # somebody cannot answer from where they read it is an escalation
            # that gets answered by ignoring it — and then the real one looks
            # like the four before it.
            clear = ""
            if config.PUBLIC_BASE_URL.startswith("http"):
                from urllib.parse import quote as _q
                clear = (f"\n\n✅ That was you / already handled? "
                         f"{config.PUBLIC_BASE_URL.rstrip('/')}/admin/allclear"
                         f"?key={config.APPROVAL_SECRET}"
                         f"&what={_q(email['subject'][:80])}"
                         + (f"&tenant={tenant}" if tenant else ""))
            note = (f"🚨 [{alias}] {email['from']} — {email['subject']}\n{detail}"
                    + (f"\n💡 {sugg}" if sugg else "") + clear)
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

        _finish_mail_run(run_id, action, result, tenant, bucket)

        with db.SessionLocal() as s:
            s.add(db.EmailLog(
                account=alias, tenant=tenant, gmail_message_id=email["id"], thread_id=email["threadId"],
                sender=email["from"], subject=email["subject"],
                category=bucket, action=logged, detail=detail,
                # What was SAID, not just that it arrived. Every draft that
                # invented a detail or asked for one it should have had was
                # this line missing: the body was in hand right here and was
                # thrown away, so a later agent could name the thread and not
                # quote a word of it. Quoted history is stripped on the way in.
                # Filtered at WRITE time, not just at index time: a marketing
                # blast should not occupy a row of the archive either. The
                # bucket triage already assigned decides it, so this costs no
                # extra classification.
                body_excerpt=(
                    archive.clean(email.get("body") or "")[:archive.MAX_STORED]
                    if archive.indexable(bucket, email.get("from", ""),
                                         email.get("body") or "")[0] else None),
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
                        body_excerpt=(
                            archive.clean(
                                email.get("body") or "")[:archive.MAX_STORED]
                            if archive.indexable(
                                bucket, email.get("from", ""),
                                email.get("body") or "")[0] else None),
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
    for alias, tenant in inboxes():
        try:
            process_emails(alias, gmail_client.fetch_unread(alias),
                           new_approvals, tenant=tenant)
        except Exception:  # noqa: BLE001 — one bad inbox must not kill the loop
            log.exception("inbox %s failed", alias)
    # NOTE: no notification here — approvals.notify_pending runs on its own
    # schedule so Gomeh gets at most one batch email per APPROVAL_BATCH_MINUTES.


def backlog_sweep() -> None:
    """First-run sweep: every email of the last BACKLOG_DAYS days that never
    got a reply -> triaged -> one big approval batch for Gomeh."""
    new_approvals: list[str] = []
    for alias, tenant in inboxes():
        try:
            emails = gmail_client.fetch_unanswered(alias, config.BACKLOG_DAYS)
            log.info("[%s/%s] backlog sweep: %d unanswered threads",
                     alias, tenant or "unattributed", len(emails))
            process_emails(alias, emails, new_approvals, tenant=tenant)
        except Exception:  # noqa: BLE001
            log.exception("backlog sweep %s failed", alias)
    if new_approvals:
        approvals.notify_pending(
            title=f"[Assistant · BACKLOG] {len(new_approvals)} unanswered emails — drafts ready",
        )


def mail_backfill() -> None:
    """Walk one more window of each account's sent-mail history, nightly.

    A mailbox holds years; a request holds seconds. Before this, the harvest
    asked Gmail for `newer_than:365d` capped at a few dozen threads and Gmail
    answers newest-first, so every run read the same newest few dozen for ever
    — which is why a real account reported 40 threads seen and 0 claims found.

    Backwards, on a schedule, is the only shape that fits: each night the
    cursor moves a little further into history and the knowledge base fills
    over a week or two, at no cost to any request. `/admin/fill` stays a fast
    top-up of new mail only.
    """
    from . import email_harvest, tenants
    done = []
    for t in tenants.all_tenants():
        if not tenants.capabilities(t.key).get("inbox"):
            continue
        cur = email_harvest.cursor(t.key)
        if cur["backfill_done"]:
            continue
        r = email_harvest.mine(t.key, apply=True, direction="backward",
                               limit=config.MAIL_BACKFILL_THREADS, want=0)
        if r.get("error"):
            log.warning("mail backfill %s: %s", t.key, r["error"])
            continue
        done.append(f"{t.key}: +{r.get('threads_seen', 0)} threads, "
                    f"{r.get('claims_count', 0)} claims, "
                    f"{r.get('objections_count', 0)} objections")
    if done:
        log.info("mail backfill — %s", "; ".join(done))


def credential_renewal() -> None:
    """Extend OAuth tokens that expire on a clock, and say so when one cannot.

    Silence on success is the point — this should be invisible for months at a
    time. A failure is announced, because a client whose Meta connection has
    lapsed needs to click Connect again and nothing else will tell them.
    """
    from . import channel, credentials as cred
    result = cred.renew_tick()
    if result["renewed"]:
        log.info("renewed credentials: %s", ", ".join(result["renewed"]))
    if result["failed"]:
        log.warning("credential renewal FAILED: %s", "; ".join(result["failed"]))
        channel.send_text(
            "⚠️ A connection could not be renewed and is now marked failed:\n"
            + "\n".join(f"· {f}" for f in result["failed"])
            + "\n\nThe client needs to reconnect it from their connect link.")


def claim_expiry_sweep() -> None:
    """Weekly: return claims that have come due to the approval queue.

    Owner's rule — claims expire by default, and an expired one goes back to be
    asked about rather than silently dropping out of selection.

    **Reports before it moves anything, once.** The first run on a knowledge
    base nobody has ever dated will find every claim older than a year at the
    same moment, and forty approved claims quietly reopening overnight is a
    surprise even when it is correct. So the first sweep on each account is a
    dry run that says what it WOULD do, and the `Setting` marker means the next
    one applies. This codebase has had the other kind of incident: a poller
    re-triggered a slow endpoint and 200 queued drafts went out at 400 sends a
    minute.
    """
    from . import kb, tenants
    for t in tenants.all_tenants(include_paused=True):
        marker = f"claim_expiry_warned:{t.key}"
        dry = kb.expire_due(t.key)
        if not dry["expired"]:
            continue
        with db.SessionLocal() as s:
            warned = s.get(db.Setting, marker)
            if not warned:
                s.add(db.Setting(key=marker, value=db.utcnow().isoformat()))
                s.commit()
                log.info("claim expiry: %s has %d claim(s) due — reporting "
                         "only on this first pass", t.key, dry["expired"])
                continue
        applied = kb.expire_due(t.key, apply=True)
        log.info("claim expiry: returned %d claim(s) to the queue for %s",
                 applied["expired"], t.key)


def compliance_sweep() -> None:
    """Check every switched-on account's site and catalogue against its rules.

    Both checks existed and NEITHER was scheduled. `compliance.scan` says in
    its own docstring that `since` is "what makes this cheap enough to run on a
    schedule", and nothing ever ran it; `catalog_compliance` is a registered
    skill reachable only from WhatsApp or a URL. So the answer to "how often do
    we check compliance" was "whenever somebody remembers", which for the check
    that would have caught Baci's 110 banned-claim violations is not an answer.

    Weekly, not daily. A site's copy does not change hourly, a full crawl is
    the expensive kind of job, and a violations queue that grows every morning
    stops being read — the same reasoning the claim-expiry sweep already uses.

    Incremental after the first pass: `since` is the date of the last scan, so
    a site is walked in full once and then only where it changed.

    Nothing is rewritten and nothing is sent. A violation is a URL and the
    sentence around it, which is what makes it fixable.
    """
    from . import compliance, skill, systems, tenants as tn

    for t in tn.all_tenants():
        # --- the live website ------------------------------------------
        site = systems.find(t.key, "content_compliance")
        if site and systems.is_on(site):
            # `record_scan` files the run ITSELF, including the refusal case —
            # no domain, or no ban list to check against, which matters because
            # a sweep reporting CLEAN when it had no rules is exactly the false
            # assurance `catalog_compliance` declares `banned_claims`
            # constitutive to prevent. Filing a second run here would double
            # every scan in the ledger and halve every rate computed from it.
            try:
                prev = compliance.last_scan(t.key) or {}
                at = prev.get("at")
                since = at.date().isoformat() if at else ""
                compliance.record_scan(
                    t.key, compliance.scan(t.key, limit=60, since=since))
            except Exception as exc:                             # noqa: BLE001
                # Only reached if the scan RAISED, which `record_scan` never
                # sees. Recorded rather than swallowed: a sweep that fails
                # silently reads as a clean site.
                log.exception("compliance scan failed for %s", t.key)
                run_id = systems.start_run(site.id, t.key, trigger="schedule")
                systems.finish_run(
                    run_id, "failed",
                    error=f"{exc.__class__.__name__}: {str(exc)[:300]}")

        # --- the catalogue ---------------------------------------------
        # A registered skill, so `skill.run` files its own run, applies the
        # switch and carries its own refusals. Nothing to wrap but the call.
        cat = systems.find(t.key, "catalog_compliance")
        if cat and systems.is_on(cat):
            try:
                res = skill.run("catalog_compliance", t.key, trigger="schedule")
                if (res or {}).get("status") == "refused":
                    # A refusal is OUR bug (an unknown skill, an unknown
                    # account) and files no run — unlogged, this sweep
                    # refused for weeks with an empty registry and read as
                    # a quiet Monday.
                    log.error("catalog compliance REFUSED for %s: %s", t.key,
                              "; ".join(res.get("blocked_on") or []))
            except Exception:                                    # noqa: BLE001
                log.exception("catalog compliance failed for %s", t.key)


def segments_sweep() -> None:
    """Weekly: keep every switched-on campaign account's segment map true.

    READS the client's ESP and WRITES only our own record — the remembered
    key→id links and the stored state the Segments card renders from. It
    never creates or edits a segment in a live account; building stays
    `materialize(apply=1)`, an explicit act behind its dry-run gate.

    Weekly and gated on the switch, like the compliance sweep and for the
    same reasons: segments do not churn hourly, and a maintenance job for a
    system nobody turned on is the daily-noise defect wearing a new name.
    Drift findings land in the stored state (the card leads with them) and
    in the log; a sweep that cannot read the ESP records that refusal as
    the state rather than silently keeping last week's.
    """
    from . import segments as segmod, systems, tenants as tn

    for t in tn.all_tenants():
        row = systems.find(t.key, "campaign_email")
        if not (row and systems.is_on(row)):
            continue
        try:
            out = segmod.sync(t.key)
            if not out.get("ok"):
                log.warning("segments sweep could not read %s's ESP: %s",
                            t.key, out.get("error", ""))
            elif out.get("drift"):
                log.warning("segment drift for %s: %s", t.key,
                            "; ".join(d["what"] for d in out["drift"])[:400])
        except Exception:                                        # noqa: BLE001
            log.exception("segments sweep failed for %s", t.key)


def media_sweep() -> None:
    """Drop the bytes behind pictures nobody approved.

    Runs for every account, and says something only when it did something —
    a nightly line reporting zero is how a log stops being read.
    """
    # ONCE. `media.sweep()` takes no tenant — it is the whole library — and
    # this loop called it once per account, so a five-account platform swept
    # the same library five times a night and logged it under five names.
    from . import media
    got = media.sweep()
    if any(got[k] for k in ("dropped_rejected", "expired_unreviewed",
                            "dropped_orphan")):
        log.info("picture retention: %s", got)


def moments_sweep() -> None:
    """Hourly: notice what has gone quiet, and retire what has gone stale.

    Two halves, and the second is the one that is easy to forget. Producers
    only ever ADD; without an expiry pass the table grows for ever and, far
    worse, "what is open" stops meaning anything — an operator looking at the
    queue could no longer tell live work from a year of things nobody got to.

    Hourly rather than daily because a moment has a window. `enquiry_quiet`
    opens three days after the last touch and a daily sweep would serve it up
    to a day late, which for a `back_in_stock` (one hour) would miss the window
    entirely. Cheap: one indexed query per account, and it files nothing when
    nothing has changed.

    NOT gated on the campaign switch. Filing a moment sends nothing — the
    planner that consumes them is what decides whether anybody is written to,
    and gating the WATCHING on the sending would mean an account switching on
    starts with no history of what it just missed.
    """
    from . import inbox_events, moments as _mo

    try:
        got = inbox_events.sweep()
        if got.get("filed"):
            log.info("moments: filed %s quiet-enquiry moment(s)", got["filed"])
    except Exception:                                            # noqa: BLE001
        log.exception("moments sweep (inbox) failed")
    try:
        n = _mo.expire_stale()
        if n:
            log.info("moments: expired %s past their window", n)
    except Exception:                                            # noqa: BLE001
        log.exception("moments sweep (expiry) failed")


def systems_tick() -> None:
    """Evaluate every installed system once, and record what happened.

    `start_run` and `finish_run` had no callers outside their test script, so
    every run count on the Systems tab was structurally zero and
    `blocked_reasons()` — the KB backlog ranked by how often each gap actually
    cost an output — had nothing to rank. This is the caller.

    Nothing here sends. A system that is not `live` is skipped entirely, and a
    system on the `shadow` rung records and stops. That is what makes it safe to
    switch on before the generator exists: the ledger starts filling with real
    blockers today, so when the generator lands it has a baseline to be measured
    against rather than starting blind.

    Daily rather than per-interval, deliberately. The question this answers is
    "could this system have run today", which does not change every ten minutes,
    and a run row per system per tick would bury the signal it exists to carry.
    """
    import datetime as _dt

    from . import skill, systems
    today = _dt.date.today().isoformat()
    live = ready_count = blocked_count = consumed_count = 0
    for sysrow in systems.all_systems():
        if not systems.is_on(sysrow):
            # ONE switch, and `designed` is off. This used to evaluate designed
            # systems too, to collect blockers early — which is what filed a
            # daily row against every pipeline nobody had turned on.
            continue
        if sysrow.key in systems.externally_driven():
            # Its runs are filed by the pipeline that does the work — see
            # `systems.EXTERNALLY_DRIVEN`. Evaluating it here reported the mail
            # path as having no generator while it was drafting replies all
            # day, and put that claim at the top of the backlog.
            continue
        live += 1

        # The workflow layer: a plan-capable system runs from its OWN queue.
        # First the planner tops the queue up (propose only — a fresh
        # proposal lands LEAD_DAYS out, so nothing proposed here can also be
        # consumed here), then due plans are consumed one by one —
        # `take_plan` re-checks the switch, the completeness bar and the
        # rung structurally, so this loop cannot execute an under-specified
        # or unapproved instruction even if it tries. A day where plans ran
        # needs no evaluation row: the consumed runs ARE the record.
        queued = held = 0
        planner_note = ""
        if systems.plan_capable(sysrow.key):
            try:
                from . import planner as _planner
                topped = _planner.top_up(sysrow)
                if topped and topped.get("refusals"):
                    planner_note = ("; planner: "
                                    + "; ".join(topped["refusals"])[:300])
                if topped and topped.get("proposed"):
                    log.info("planner proposed %d for %s/%s",
                             topped["proposed"], sysrow.tenant, sysrow.key)
            except Exception:                                    # noqa: BLE001
                log.exception("planner failed for %s/%s",
                              sysrow.tenant, sysrow.key)
            wf = systems.workflow(sysrow.key)
            open_plans = systems.plans(sysrow.tenant, sysrow.key)
            queued = len(open_plans)
            ran_here = 0
            for prow in systems.plans(sysrow.tenant, sysrow.key,
                                      due_by=today):
                if not systems.consumable(prow, sysrow)["ok"]:
                    held += 1
                    continue
                try:
                    res = skill.run(wf["skill"] or sysrow.key, sysrow.tenant,
                                    trigger="schedule", run_id=prow.id)
                    # A refusal is NOT a consumption. `skill.run` refuses
                    # before touching the plan (a blocked preflight — no ESP
                    # wired — or a held gate), and counting that as "ran"
                    # would skip the evaluation row below, so a system whose
                    # queue can never drain would file nothing at all and
                    # read as busy.
                    if (res or {}).get("status") in ("refused", "blocked"):
                        held += 1
                    else:
                        ran_here += 1
                except Exception:                                # noqa: BLE001
                    log.exception("plan consumption failed for %s/%s",
                                  sysrow.tenant, sysrow.key)
            if ran_here:
                consumed_count += ran_here
                ready_count += 1
                continue

        run_id = systems.start_run(sysrow.id, sysrow.tenant, trigger="schedule")
        try:
            state = systems.ready(sysrow)
            # `can_produce`, NOT `ready`. This is the unattended path, and it
            # was still gating on the full go-live bar after `skill.run` had
            # stopped — so a scheduled system with a blank contract or a thin
            # knowledge base was skipped every tick, which is exactly the rule
            # the owner overturned, running by itself all night.
            #
            # `ready` still decides go-live. It does not decide whether work
            # happens.
            if not state["can_produce"]:
                blocked_count += 1
                # A LIST, not a joined string: `blocked_reasons()` iterates this
                # to rank the backlog, and a string iterates into characters —
                # which ranked ' ' and 'e' as the two costliest gaps.
                systems.finish_run(run_id, "blocked",
                                   blocked_on=list(state["impossible"]))
                continue
            ready_count += 1
            if systems.plan_capable(sysrow.key):
                # The generator EXISTS for these — what was missing today was
                # work in the queue. Filed as `skipped` (correctly produced
                # nothing), never `not_built`: reporting a wired skill as
                # unbuilt is the inbox_triage mislabel all over again.
                from . import planner as _planner
                has_planner = sysrow.key in _planner.PLANNERS
                detail = ("no plans were due today"
                          + (f" — {queued} queued" if queued else
                             (" — nothing is queued"
                              + ("" if has_planner else
                                 "; no planner exists for this system, so "
                                 "plans are filed by hand")))
                          + (f", {held} held (incomplete or awaiting your "
                             f"approval)" if held else "")
                          + planner_note)
                systems.finish_run(run_id, "skipped", output=detail)
                continue
            # The generator lands here. Until it does, say so on the run rather
            # than recording a success that never happened. What the run would
            # have been working WITHOUT is recorded beside that, so the gap is
            # already ranked in `blocked_reasons()` by the time there is
            # something to block.
            # `not_built`, not `blocked`. The system is READY; what is missing
            # is our generator, which is a roadmap item rather than anything
            # this account can answer. As `blocked` it dominated
            # `blocked_reasons()` — the ranking of what to go and WRITE — with
            # a row nobody could ever satisfy by writing, and it was reported
            # nightly as a problem.
            systems.finish_run(
                run_id, "not_built",
                error=("no generator yet — system is otherwise able to run"
                       + ("; would have run without: "
                          + ", ".join(state["thin"]) if state["thin"] else "")))
        except Exception as exc:  # noqa: BLE001 — one system must not stop the rest
            log.exception("systems tick failed for %s/%s", sysrow.tenant, sysrow.key)
            systems.finish_run(run_id, "failed",
                               error=f"{exc.__class__.__name__}: {str(exc)[:300]}")
    log.info("systems tick: %d evaluated, %d ready, %d blocked, %d plan(s) consumed",
             live, ready_count, blocked_count, consumed_count)


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


#: Who this process is, for the lease row. Render sets RENDER_INSTANCE_ID per
#: instance; anywhere else, host and pid are enough to tell two apart.
def _holder() -> str:
    import socket
    return (os.environ.get("RENDER_INSTANCE_ID")
            or f"{socket.gethostname()}:{os.getpid()}")


#: How long a lease is held if the job never releases it (a crash mid-run).
#: Long enough that a slow harvest is not re-run by a sibling that woke a
#: minute later; short enough that a dead instance does not park a job for a
#: day. Per-job overrides go in _LEASE_TTL by context string.
LEASE_TTL_SECONDS = 20 * 60
_LEASE_TTL = {"inbox polling": 90, "moments sweep": 15 * 60,
              "keyword map top-up": 60 * 60, "nightly sweep": 60 * 60}


def _lease_name(context: str, tenant: str = "") -> str:
    return f"{context}:{tenant}" if tenant else context


def _acquire(name: str, ttl: int) -> bool:
    """Take the lease or return False. ONE statement decides the race.

    The row is created on first sight; after that, acquisition is a single
    UPDATE whose WHERE clause says "free or expired". Two instances issuing it
    in the same instant get rowcounts 1 and 0 from the database, which is the
    whole correctness argument — nothing here reads-then-writes.
    """
    import datetime as _dt
    from sqlalchemy import or_, update
    now = db.utcnow()
    me = _holder()
    with db.SessionLocal() as s:
        if s.get(db.JobLease, name) is None:
            try:
                s.add(db.JobLease(name=name)); s.commit()
            except Exception:  # noqa: BLE001 — a sibling created it first
                s.rollback()
        got = s.execute(
            update(db.JobLease)
            .where(db.JobLease.name == name,
                   or_(db.JobLease.leased_until.is_(None),
                       db.JobLease.leased_until < now))
            .values(holder=me, leased_until=now + _dt.timedelta(seconds=ttl),
                    last_run_at=now, last_holder=me,
                    runs=db.JobLease.runs + 1))
        s.commit()
        if got.rowcount == 1:
            return True
        s.execute(update(db.JobLease).where(db.JobLease.name == name)
                  .values(skips=db.JobLease.skips + 1))
        s.commit()
        return False


def _release(name: str) -> None:
    from sqlalchemy import update
    with db.SessionLocal() as s:
        s.execute(update(db.JobLease)
                  .where(db.JobLease.name == name,
                         db.JobLease.holder == _holder())
                  .values(leased_until=None))
        s.commit()


def _each_tenant(context: str, one, *, include_paused: bool = False) -> dict:
    """Run one per-tenant unit for every account, leasing PER TENANT.

    THIS IS WHERE PARALLEL BECOMES THROUGHPUT. `_safe`'s job-level lease makes
    a second instance safe: one of them runs the job and the other skips it,
    so N instances do the work of one. A sharded job leases `context:tenant`
    instead — two instances waking on the same minute split the accounts
    between them, and every account is still worked exactly once.

    The unit owns its gates and returns a dict that says why it skipped, so a
    sharded run reads the same as the serial `*_all` it replaces.
    """
    from . import tenants
    out: dict[str, object] = {}
    for t in tenants.all_tenants(include_paused=include_paused):
        name = _lease_name(context, t.key)
        if not _acquire(name, _LEASE_TTL.get(context, LEASE_TTL_SECONDS)):
            out[t.key] = {"skipped": "leased by another worker"}
            continue
        try:
            out[t.key] = one(t.key)
        except Exception as exc:  # noqa: BLE001
            log.exception("%s failed for %s", context, t.key)
            alert_error(f"{context} ({t.key})", exc)
            out[t.key] = {"error": exc.__class__.__name__}
        finally:
            _release(name)
    return out


def keyword_sync_sharded() -> dict:
    from . import keywords
    return _each_tenant("keyword sync", keywords.sync_one)


def keyword_harvest_sharded() -> dict:
    from . import keywords
    return _each_tenant("keyword map top-up", keywords.harvest_one)


def learning_sharded() -> dict:
    """Weekly: pre-send edits → proposed standing guidance, per account."""
    from . import learning
    return _each_tenant("learning sweep", learning.sweep_for)


def performance_sharded() -> dict:
    from . import performance
    got = _each_tenant("performance sweep", performance.sync_one)
    for tenant, res in got.items():
        if isinstance(res, dict) and not res.get("ok") and not res.get("skipped"):
            log.info("performance sweep %s: %s", tenant, res.get("why", ""))
    return got


def instances_seen(hours: int = 24) -> dict:
    """Which worker instances actually did work in the window.

    THE PROOF THAT PARALLEL IS ON. `numInstances: 2` in render.yaml is a
    request; this reads the lease table, where every job records the holder
    that ran it (`RENDER_INSTANCE_ID` per instance). Two distinct holders in
    a day means two workers are sharing the work. One means you are paying
    for parallel and getting a spare, and nothing else on the platform would
    say so.
    """
    import datetime as _dt
    since = db.utcnow() - _dt.timedelta(hours=hours)
    with db.SessionLocal() as s:
        rows = (s.query(db.JobLease)
                .filter(db.JobLease.last_run_at.isnot(None),
                        db.JobLease.last_run_at >= since).all())
        holders = sorted({r.last_holder for r in rows if r.last_holder})
        jobs = len(rows)
    return {"hours": hours, "instances": len(holders), "holders": holders,
            "jobs_run": jobs,
            "verdict": ("parallel" if len(holders) >= 2 else
                        "one instance did every job" if holders else
                        "nothing has run in the window")}


def _safe(fn, context: str, *, tenant: str = "", sharded: bool = False):
    """Run one job: leased, logged, alerted — never raised.

    THE LEASE LIVES HERE AND NOWHERE ELSE, so every `sched.add_job` in this
    file is covered by the same six lines and a second worker instance is
    safe the day it is started. `test_job_lease.py` counts that every
    registration goes through this wrapper; a job registered around it would
    be the one that runs twice.
    """
    name = _lease_name(context, tenant)
    ttl = _LEASE_TTL.get(context, LEASE_TTL_SECONDS)

    def wrapped() -> None:
        # A SHARDED job takes no job-level lease: the per-tenant leases in
        # `_each_tenant` ARE its lease, and a job-level one on top would hand
        # the whole job to one instance again. `test_job_lease` holds the
        # pair — sharded skips this, unsharded takes it.
        if not sharded and not _acquire(name, ttl):
            log.info("%s: another worker holds the lease — skipped", name)
            return
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            log.exception("%s failed", context)
            alert_error(context, exc)
        finally:
            if not sharded:
                _release(name)
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
    # Report what it is actually about to do, per client. "Inboxes: [...]" said
    # nothing about which account each one served, so a mistyped gmail_alias
    # looked identical to a correct one at startup.
    log.info("Worker starting. WhatsApp: %s | auto-send: %s",
             config.WHATSAPP_ENABLED, config.AUTO_SEND_ENABLED)
    for _alias, _tenant in inboxes():
        log.info("  inbox %-12s -> %s", _alias, _tenant or "UNATTRIBUTED")
    # Startup jobs are wrapped so a failure can NEVER crash the worker (exit 1).
    _safe(voice_learn.ensure_profiles, "voice profiles")()
    from . import systems_map
    _safe(systems_map.ensure_seeds, "systems map seeds")()
    _safe(bucket_backfill, "bucket backfill")()
    _safe(backlog_sweep, "backlog sweep")()
    sched = BackgroundScheduler(timezone="America/New_York")
    sched.add_job(_safe(poll_all, "inbox polling"), "interval",
                  minutes=config.POLL_INTERVAL_MIN)
    sched.add_job(_safe(approvals.notify_pending, "approval batching"),
                  "interval", minutes=config.APPROVAL_BATCH_MINUTES)
    sched.add_job(_safe(deadline_alerts, "deadline alerts"), "cron", hour=9, minute=0)
    # Its own slot, not chained to polling: a slow system evaluation must never
    # delay the inbox loop, and vice versa.
    sched.add_job(_safe(systems_tick, "systems tick"), "cron", hour=7, minute=0)
    # Weekly, not daily: a claim that came due on Tuesday is not more true on
    # Wednesday, and a queue that grows every morning stops being read.
    sched.add_job(_safe(claim_expiry_sweep, "claim expiry"), "cron",
                  day_of_week="mon", hour=8, minute=30)
    # Keep the queue and the mailbox in step. Frequent, because the window
    # being closed is "Gomeh sent it from Gmail and the approval is still
    # sitting in the waiting count".
    sched.add_job(_safe(approvals.reconcile_drafts, "draft reconciliation"),
                  "interval", minutes=20)
    sched.add_job(_safe(follow_up_chase, "follow-up chasing"), "cron",
                  hour=9, minute=30)
    # Meta long-lived tokens expire at ~60 days and cannot refresh; they must be
    # exchanged while still valid. Daily, because the failure mode is an ads
    # connection that dies quietly and is discovered by whatever reads it next.
    sched.add_job(_safe(credential_renewal, "credential renewal"), "cron",
                  hour=6, minute=30)
    # Overnight, so a long walk never competes with the inbox loop. Stops on
    # its own once each account's cursor reaches the start of its mailbox.
    sched.add_job(_safe(mail_backfill, "sent-mail backfill"), "cron",
                  hour=3, minute=15)
    # The evening sweep. Late on purpose: it reads the day that just happened,
    # and it competes with nothing. The correlation is deterministic Python
    # over rows we already wrote; only the summary paragraph touches a model,
    # on the cheapest one, and the findings stand without it.
    from . import correlate
    sched.add_job(_safe(correlate.nightly, "nightly sweep"), "cron",
                  hour=config.SWEEP_HOUR, minute=10)
    # Readings BEFORE the sweep reads them, which is why this is :05 and not
    # :10 — a sweep that runs first reports on yesterday's positions and calls
    # them today's.
    from . import keywords
    sched.add_job(_safe(keyword_sync_sharded, "keyword sync", sharded=True), "cron",
                  hour=config.SWEEP_HOUR, minute=5)
    # The map itself, weekly. Positions move nightly and the competitive
    # landscape does not — and a harvest spends Semrush calls per account, so
    # running it on the reading schedule would be a bill for no new answer.
    # Monday, before the week's writing is planned.
    sched.add_job(_safe(keyword_harvest_sharded, "keyword map top-up", sharded=True), "cron",
                  day_of_week="mon", hour=config.SWEEP_HOUR, minute=25)
    # Weekly, Sunday: a habit is a week's worth of edits, not a day's. Proposes
    # only — every rule goes through the approval queue before a drafter
    # reads it — so a sweep on a quiet account files nothing and says why.
    sched.add_job(_safe(learning_sharded, "learning sweep", sharded=True), "cron",
                  day_of_week="sun", hour=config.SWEEP_HOUR, minute=35)
    # Weekly and overnight: a full site crawl is the expensive kind of job, a
    # site's copy does not change hourly, and a violations queue that grows
    # every morning stops being read. After the first pass it only walks what
    # changed. Monday early, clear of the other weekly jobs.
    sched.add_job(_safe(compliance_sweep, "compliance sweep"), "cron",
                  day_of_week="mon", hour=4, minute=30)
    # Segment upkeep: re-link and report drift before the 07:00 tick plans
    # the week's campaigns against those segments.
    sched.add_job(_safe(segments_sweep, "segments sweep"), "cron",
                  day_of_week="mon", hour=5, minute=15)
    # Moments: watch for windows opening, and close the ones that shut. Every
    # hour, because a window is measured in hours and a daily pass would serve
    # a one-hour moment a day late — which is to say, never.
    sched.add_job(_safe(moments_sweep, "moments sweep"), "interval", hours=1)
    # A retention policy nothing runs is a comment. Daily and quiet: it keeps
    # the bytes behind APPROVED pictures and drops the rest, which on a normal
    # day is nothing at all.
    sched.add_job(_safe(media_sweep, "picture retention"), "cron",
                  hour=3, minute=40)
    # After the tick, so today's results are on the rows before tomorrow's
    # planner reads them.
    sched.add_job(_safe(performance_sharded, "performance sweep", sharded=True), "cron",
                  hour=9, minute=15)
    from . import ops_jobs
    sched.add_job(_safe(ops_jobs.daily_review, "daily review"), "cron",
                  hour=8, minute=30)  # the 'expert second look'
    sched.add_job(_safe(weekly_cost_report, "cost report"), "cron",
                  day_of_week="mon", hour=8, minute=0)
    sched.add_job(_safe(ops_jobs.JOBS["business_pulse"], "business pulse"),
                  "cron", day_of_week="mon", hour=7, minute=30)
    sched.add_job(_safe(ops_jobs.JOBS["contract_expiry_watch"], "expiry watch"),
                  "cron", day_of_week="mon", hour=7, minute=0)
    # Weekly systems review: stale Systems Map docs + the agents' open feature
    # requests — the self-improvement loop's heartbeat.
    sched.add_job(_safe(systems_map.systems_review, "systems review"),
                  "cron", day_of_week="mon", hour=8, minute=45)
    # SEO self-analysis loop: weekly snapshot of the target domain so seo_progress
    # can measure growth/decline. Only scheduled when Semrush is configured.
    if config.SEMRUSH_API_KEY:
        from . import seo_tools
        sched.add_job(_safe(seo_tools.capture_snapshot, "seo snapshot"),
                      "cron", day_of_week="mon", hour=6, minute=0)
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
