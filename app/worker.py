"""Background worker: polls every inbox, triages, schedules digests."""
import logging
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
            row = systems.create(tenant, grounding.SYSTEM_KEY, "Inbox triage")
        return row.id
    except Exception:                                            # noqa: BLE001
        return ""       # bookkeeping must never stop the inbox


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


def _finish_mail_run(run_id: str, action: str, result: dict) -> None:
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
    except Exception:                                            # noqa: BLE001
        pass


def process_emails(alias: str, emails: list[dict], new_approvals: list[str],
                   tenant: str = "") -> None:
    """Triage a batch from one inbox. `tenant` is resolved once by the caller
    so every email in the batch is attributed and scoped identically."""
    from . import tenants as _tn
    tenant = tenant or _tn.for_alias(alias)
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

        _finish_mail_run(run_id, action, result)

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
    from . import systems
    live = ready_count = blocked_count = 0
    for sysrow in systems.all_systems():
        if sysrow.status not in ("live", "designed"):
            continue          # paused and retired are decisions, not failures
        if sysrow.key in systems.EXTERNALLY_DRIVEN:
            # Its runs are filed by the pipeline that does the work — see
            # `systems.EXTERNALLY_DRIVEN`. Evaluating it here reported the mail
            # path as having no generator while it was drafting replies all
            # day, and put that claim at the top of the backlog.
            continue
        live += 1
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
    log.info("systems tick: %d evaluated, %d ready, %d blocked",
             live, ready_count, blocked_count)


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
