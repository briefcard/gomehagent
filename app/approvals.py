"""Approval flow: email links today, WhatsApp buttons when enabled.

Every gated action -> Approval row -> notification to Gomeh -> webhook/link
decision -> execution. Tokens are signed; links expire after 7 days.
"""
import datetime as dt

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from . import config, db, gmail_client, whatsapp

_signer = URLSafeTimedSerializer(config.APPROVAL_SECRET)


def request_approval(kind: str, summary: str, payload: dict, notify: bool = True,
                     run_id: str = "", system_id: str = "") -> str:
    """Create a pending approval. notify=False lets the caller batch
    notifications (one email per poll cycle instead of one per item).

    `run_id` is what lets the decision travel back to the run that produced
    this, which is how a system earns its next rung. The columns existed from
    the start and no caller ever filled them, so `systems.stats()` reported
    zero decided runs forever and `can_promote` could never clear its gate.
    """
    # Attribute now, while the payload that names the client is in hand. Doing
    # it later is archaeology: the 330 approvals written before this line have
    # to be recovered from their payloads, and some of them cannot be.
    from . import tenant_scope
    with db.SessionLocal() as s:
        ap = db.Approval(kind=kind, summary=summary, payload=payload,
                         tenant=tenant_scope.resolve(payload=payload),
                         run_id=run_id, system_id=system_id,
                         channel="whatsapp" if config.WHATSAPP_ENABLED else "email")
        s.add(ap)
        s.commit()
        ap_id = ap.id

    if notify:
        # THE APPROVAL IS ALREADY COMMITTED. Letting a notification failure
        # raise out of here told every caller the REQUEST had failed when only
        # the telling had — and the queue filled silently behind the error. It
        # surfaced from `blog_article`, where an exception here marks the whole
        # skill run `failed` and discards a drafted article whose approval was
        # sitting in the database the entire time.
        #
        # Logged rather than swallowed: a channel that is down for a week is a
        # real problem, just not this function's problem to have.
        try:
            notify_pending()
        except Exception:  # noqa: BLE001
            import logging
            logging.getLogger("approvals").exception(
                "approval %s was filed but could not be announced", ap_id)
    return ap_id


MAX_WA_NOTIFY_ATTEMPTS = 3  # then fall back to approve-by-email-link
WA_SENDS_PER_CYCLE = 12     # Meta pair-rate protection: never storm one user
STALE_APPROVAL_DAYS = 3     # older drafts skip WhatsApp -> straight to the digest


def _set_payload_flags(ap_id: str, **flags) -> None:
    """Merge bookkeeping flags into an approval's payload (short transaction)."""
    with db.SessionLocal() as s:
        ap = s.get(db.Approval, ap_id)
        if ap:
            ap.payload = {**ap.payload, **flags}
            s.commit()


def _email_approvals(items: list, title: str | None = None) -> None:
    """ONE email with real Approve/Deny links for these approvals."""
    from . import emailfmt

    rich, plain = [], []
    for i, (ap_id, summary, p) in enumerate(items, 1):
        approve = f"{config.PUBLIC_BASE_URL}/decide/{_signer.dumps([ap_id, 'approved'])}"
        deny = f"{config.PUBLIC_BASE_URL}/decide/{_signer.dumps([ap_id, 'denied'])}"
        rich.append({**p, "approve_url": approve, "deny_url": deny})
        plain.append(f"{i}. {summary}\n   Approve: {approve}\n   Deny: {deny}\n")
    n = len(items)
    subject = title or (f"{n} draft repl{'y' if n == 1 else 'ies'} ready for "
                        f"your review")
    gmail_client.send_email(
        config.NOTIFY_FROM_ALIAS, config.APPROVER_EMAIL, subject,
        "Replies awaiting your approval:\n\n" + "\n".join(plain),
        html=emailfmt.approval_email(rich, intro=title),
    )


def notify_pending(title: str | None = None) -> int:
    """Notify Gomeh of every pending approval not yet announced. DURABLE
    (Jul 2026): an approval is marked _notified only AFTER a send succeeds —
    failures retry on the next batch cycle (APPROVAL_BATCH_MINUTES), and after
    MAX_WA_NOTIFY_ATTEMPTS WhatsApp failures it falls back to an email with
    real Approve/Deny links. An approval must never be silently lost (the old
    mark-before-send silenced the Drive-taxonomy cards forever)."""
    with db.SessionLocal() as s:
        aps = (
            s.query(db.Approval)
            .filter(db.Approval.status == "pending")
            .order_by(db.Approval.created_at)
            .all()
        )
        items = [(ap.id, ap.summary,
                  {**dict(ap.payload), "_kind": ap.kind}, ap.created_at)
                 for ap in aps if not ap.payload.get("_notified")]
    if not items:
        return 0

    if config.WHATSAPP_ENABLED:
        import datetime as _dt

        def _aware(ts):  # sqlite naive vs Postgres aware
            return ts.replace(tzinfo=_dt.timezone.utc) if ts and ts.tzinfo is None else ts

        stale_cutoff = db.utcnow() - _dt.timedelta(days=STALE_APPROVAL_DAYS)
        sent, fallback, attempted = 0, [], 0
        for ap_id, summary, payload, created in items:
            # Stale drafts don't deserve 3 WhatsApp attempts each — one links
            # digest covers the whole backlog without hammering the pair limit.
            if _aware(created) and _aware(created) < stale_cutoff:
                fallback.append((ap_id, summary, payload))
                continue
            if attempted >= WA_SENDS_PER_CYCLE:
                continue  # untouched — next cycle picks it up
            attempted += 1
            if whatsapp.send_approval(ap_id, summary, payload):
                _set_payload_flags(ap_id, _notified=True)
                sent += 1
            else:
                attempts = int(payload.get("_notify_attempts", 0)) + 1
                if attempts >= MAX_WA_NOTIFY_ATTEMPTS:
                    fallback.append((ap_id, summary, payload))
                else:
                    _set_payload_flags(ap_id, _notify_attempts=attempts)
        if fallback:
            try:
                _email_approvals(fallback, f"{len(fallback)} approvals waiting "
                                           "— approve by link")
                for ap_id, _, _ in fallback:
                    _set_payload_flags(ap_id, _notified=True)
                sent += len(fallback)
            except Exception:  # noqa: BLE001 — stays pending; next cycle retries
                pass
        return sent

    _email_approvals([i[:3] for i in items], title)
    for it in items:  # only after the send call succeeded
        _set_payload_flags(it[0], _notified=True)
    return len(items)


def attach_esp_push(run_id: str, push: dict) -> int:
    """Stash what the approval-time ESP push needs on the approval itself.

    Under review-before-push (UI overhaul 3.3) the approval IS the
    authorization to write into a client's platform, so it carries everything
    the write needs — subject, preheader, sender, segment binding. This is
    also the seam that makes the workroom's pre-push edits real: the edit
    form updates this payload, and `push_campaign_to_esp` reads it.
    """
    if not run_id:
        return 0
    n = 0
    with db.SessionLocal() as s:
        rows = (s.query(db.Approval)
                .filter(db.Approval.run_id == run_id,
                        db.Approval.status == "pending").all())
        for ap in rows:
            ap.payload = {**(ap.payload or {}), "esp_push": dict(push)}
            n += 1
        if n:
            s.commit()
    return n


def withdraw(run_id: str, why: str) -> int:
    """Close the pending approvals for a run whose artifact never appeared.

    `emit` queues an approval as soon as the copy clears the validator, and for
    campaign_email the artifact — the ESP draft — is only attempted AFTER that.
    So anything that stops the draft (a craft block, an ESP error, an orphaned
    template) used to leave an approval sitting in the queue describing an
    email that does not exist anywhere. Approving it reported success, removed
    it from the queue, and produced nothing: the owner approved an email and
    then could not find it in Omnisend (2026-08-22).

    An approval is a question about a REAL thing. When the thing was not
    created, the question is withdrawn and says why, rather than being left to
    be answered about nothing.
    """
    if not run_id:
        return 0
    n = 0
    with db.SessionLocal() as s:
        rows = (s.query(db.Approval)
                .filter(db.Approval.run_id == run_id,
                        db.Approval.status == "pending").all())
        for ap in rows:
            ap.status = "withdrawn"
            ap.decided_at = db.utcnow()
            ap.payload = {**(ap.payload or {}), "withdrawn_because": why}
            ap.summary = f"[not created] {ap.summary}"
            n += 1
        if n:
            s.commit()
    return n


def decide(token: str) -> str:
    """Resolve a signed decision link; execute if approved."""
    try:
        ap_id, decision = _signer.loads(token, max_age=7 * 24 * 3600)
    except SignatureExpired:
        return "This approval link has expired."
    except BadSignature:
        return "Invalid link."
    return apply_decision(ap_id, decision)


def apply_decision(ap_id: str, decision: str) -> str:
    with db.SessionLocal() as s:
        ap = s.get(db.Approval, ap_id)
        if not ap:
            return "Approval not found."
        if ap.status != "pending":
            return f"Already {ap.status}."
        ap.status = decision
        ap.decided_at = db.utcnow()
        # Write the decision back onto the run that produced this.
        #
        # `Approval` has carried `system_id` and `run_id` since it was written
        # and nothing ever populated the other side, so `systems.stats()`
        # reported zero decided runs for every system forever — which meant
        # `can_promote` could never clear its 20-run gate and the autonomy
        # ladder was capped at `approve_all` in production. The gates, the
        # approval rate and every "did this get better over time" question all
        # read a field that was never written.
        if ap.run_id:
            run = s.get(db.SystemRun, ap.run_id)
            if run and not run.decision:
                run.decision = decision
        s.commit()
        if decision == "approved":
            _execute(ap)
            ap.status = "executed"
            ap.executed_at = db.utcnow()
            s.commit()
            # `skill_output` has no executable side — the artifact already
            # exists in the destination platform (an ESP draft, a proposal
            # row) and approving it means "reviewed, ready to launch there".
            # Saying "executed" made that indistinguishable from an approval
            # that actually sent something, which is how approving a campaign
            # read as sending it and left the owner looking for an email that
            # nothing had promised to move.
            if ap.kind == "skill_output" and (ap.payload or {}).get("esp_push"):
                # Review-before-push (UI overhaul 3.3): the campaign was HELD
                # in our store for the workroom's review, and approving is
                # what writes the draft into the client's platform. Launching
                # still stays human, in the ESP.
                from . import skill_pack as _sp
                p = ap.payload or {}
                got = _sp.push_campaign_to_esp(
                    ap.tenant or p.get("tenant", ""), p.get("output_id", ""))
                if got.get("ok"):
                    extra = (" (some images stayed hotlinked: "
                             + ", ".join(got["images_not_rehosted"][:3]) + ")"
                             if got.get("images_not_rehosted") else "")
                    return (f"Approved and pushed to {got.get('provider')} as "
                            f"a draft (campaign {got.get('campaign_id')})"
                            f"{extra} — launch-ready. Launching stays yours, "
                            f"in the platform.")
                return (f"Approved — but the push to the ESP failed: "
                        f"{got.get('error', 'unknown')[:200]}. Nothing is in "
                        f"the platform; retry from the workroom once it is "
                        f"fixed.")
            if ap.kind == "skill_output":
                return (f"Approved: {ap.summary}. Nothing was sent — this "
                        f"marks the draft reviewed. Launch it in the platform "
                        f"where it lives.")
            _HANDLED = {"send_email", "refile_moves", "seo_update",
                        "seo_new_collection", "seo_new_page",
                        "seo_new_article", "seo_article_revision",
                        "shopify_theme_asset", "systems_update"}
            if ap.kind in _HANDLED:
                return f"Approved and executed: {ap.summary}"
            # The nightly sweep files kind="sweep"; nothing executes it, and
            # "executed" over a no-op teaches the reader the word means
            # nothing.
            return (f"Approved: {ap.summary}. This kind has nothing to "
                    f"execute — approving records the decision.")
        return f"Denied: {ap.summary}"


def reconcile_drafts() -> dict:
    """Close approvals whose draft is gone, and LEARN from what was sent.

    THE SEND IS THE APPROVAL (owner, 2026-08-27). A drafted reply is not a
    decision the console has to collect: the draft is sitting in the client's
    mailbox, the person answers the customer from there, and the moment they
    press send they have approved it. What the console is for is the other
    half — noticing that it went, closing the row so the queue does not fill
    with work already done, and measuring *what changed between the draft and
    the letter*, which is the only honest signal of where the generator is
    wrong.

    That last part is why this function exists and it was the part that was
    missing: the docstring promised the delta, `edits` was imported for it,
    and nothing ever called it. So sending from Gmail — the normal path, and
    now the ONLY path for a drafted reply — closed the approval and threw the
    lesson away.

    IT RECONCILES OUTBOUND MAIL, not only Gmail drafts (widened 2026-08-28).
    An approval with no draft behind it — an RFQ, an invoice reminder, a
    shipment follow-up — was skipped entirely, so answering that person
    directly left the row pending for ever and the queue filled with work
    already done. Those are asked of the mailbox the same way: by thread when
    the approval is a reply, by recipient-since-raised when it starts one.

    SENT and DELETED are told apart, because to `read_draft` they are the same
    absence. A sent draft leaves a message in SENT on the thread and teaches;
    a deleted one leaves nothing, closes as `draft_discarded`, and teaches
    nothing — filing it as sent would measure an "edit" against a letter that
    was never written, and free-riding on that number is worse than not having
    it.

    Runs on a tick. It only ever CLOSES approvals — it never sends anything —
    so the worst case of a wrong reading here is an approval that needed a
    second look being marked done, not a customer being mailed.
    """
    from . import edits, gmail_client as gc

    closed, discarded, kept, skipped = 0, 0, 0, 0
    #: Answered another way while our draft sat there — counted apart from
    #: `closed`, because the draft is still in the mailbox and the owner may
    #: want to clear it. NOTHING here deletes it: this function only ever
    #: closes approvals, and removing somebody's mail is not its decision.
    answered_n = 0
    stale_drafts: list[str] = []
    #: (approval_id, drafted body, sent body) — recorded AFTER this session
    #: commits, because `edits.record` opens its own and writes the same rows.
    learn: list[tuple[str, str, str]] = []
    with db.SessionLocal() as s:
        rows = (s.query(db.Approval)
                .filter(db.Approval.status == "pending",
                        db.Approval.kind == "send_email").all())
        for ap in rows:
            p = ap.payload or {}
            draft_id, alias = p.get("draft_id"), p.get("account")
            if not alias:
                skipped += 1          # no mailbox to ask
                continue
            if not draft_id:
                # NO GMAIL DRAFT BEHIND IT — an RFQ, an invoice reminder, a
                # shipment follow-up, the report-figures ask. Nothing ever
                # reconciled these (owner, 2026-08-28: "I'm looking at a list
                # of emails that I've already handled"), so answering the
                # person directly left the row in the queue for ever, and the
                # queue filled with work already done.
                #
                # Asked of the mailbox, not of the console: a thread if the
                # approval is a reply, otherwise the recipient since the
                # approval was raised.
                try:
                    if p.get("thread_id"):
                        sent = gc.sent_in_thread(alias, p["thread_id"])
                    else:
                        sent = gc.sent_to_since(alias, p.get("to") or "",
                                                db.as_utc(ap.created_at))
                except Exception:                                # noqa: BLE001
                    skipped += 1      # unreadable: decide on the next tick
                    continue
                if not sent:
                    kept += 1         # genuinely still waiting on a person
                    continue
                ap.status = "sent_outside"
                ap.decided_at = db.utcnow()
                closed += 1
                # AND WHAT YOU WROTE INSTEAD. The whole point of noticing is
                # to learn from it: the delta between what was drafted and
                # what actually went reaches `SystemRun.edit_diff`, which is
                # what `systems.edit_lessons` feeds back into the drafter.
                learn.append((ap.id, p.get("body", ""), sent.get("body", "")))
                continue
            try:
                live = gc.read_draft(alias, draft_id)
            except Exception:                                    # noqa: BLE001
                skipped += 1
                continue
            if live:
                # THE DRAFT STILL EXISTS — WHICH IS NOT THE SAME AS UNANSWERED
                # (owner, 2026-08-28: "I have been seeing drafts to these
                # emails inside of gmail" on a list of mail already handled).
                # Answering from a phone, or composing fresh instead of
                # sending the draft, leaves the draft sitting there: this
                # stopped at `read_draft`, counted the row as still waiting,
                # and asked again for ever while the drafts piled up.
                try:
                    answered = gc.sent_in_thread(alias, p.get("thread_id") or "")
                except Exception:                                # noqa: BLE001
                    kept += 1        # unreadable thread: ask again next tick
                    continue
                raised = db.as_utc(ap.created_at).timestamp()
                if answered and float(answered.get("at") or 0) > raised:
                    # Sent AFTER this was raised, so it is a reply to the same
                    # conversation that is not the draft we are holding.
                    ap.status = "answered_elsewhere"
                    ap.decided_at = db.utcnow()
                    answered_n += 1
                    stale_drafts.append(p.get("subject") or ap.summary or "")
                    learn.append((ap.id, p.get("body", ""),
                                  answered.get("body", "")))
                    continue
                kept += 1             # still sitting there, still needs a person
                continue
            try:
                sent = gc.sent_in_thread(alias, p.get("thread_id") or "")
            except Exception:                                    # noqa: BLE001
                # An unreadable thread means DECIDE NEXT TICK, never
                # "discarded". Concluding from a network error would file a
                # reply the customer actually received as one that never
                # happened — and lose its lesson permanently, because this
                # only ever looks at PENDING rows.
                skipped += 1
                continue
            ap.decided_at = db.utcnow()
            if sent:
                ap.status = "sent_outside"
                closed += 1
                learn.append((ap.id, p.get("body", ""), sent.get("body", "")))
            else:
                # No draft and nothing sent on the thread: it was deleted, or
                # the thread cannot be read. Either way nobody was written to,
                # so the thread is free for another system to answer.
                ap.status = "draft_discarded"
                discarded += 1
        s.commit()

    measured = 0
    for ap_id, generated, sent_body in learn:
        if edits.record(ap_id, generated, sent_body).get("measured"):
            measured += 1

    return {"closed": closed, "discarded": discarded, "still_waiting": kept,
            "answered_elsewhere": answered_n,
            "drafts_left_in_the_mailbox": stale_drafts[:10],
            "not_applicable": skipped, "deltas_recorded": measured,
            "note": "an approval whose draft has gone was dealt with in Gmail; "
                    "leaving it pending is how the queue fills with work "
                    "already done. What was sent is compared with what was "
                    "drafted, and that difference is what the generator "
                    "learns from."}


def _fields_from_artifact(output_id: str, payload_fields: dict) -> dict:
    """The payload's fields, with the artifact's current text laid over them.

    One home for what a person edits (`ArtifactBody.body` + `.meta`), one for
    what the proposer computed (handle, structured data, published flag), and
    a single place they are joined — here, at the moment of the write.

    Falls back to the payload untouched when there is no artifact or no meta,
    so every approval queued before the column existed publishes exactly as
    it did before.
    """
    if not output_id:
        return payload_fields
    try:
        with db.SessionLocal() as s:
            art = (s.query(db.ArtifactBody)
                   .filter(db.ArtifactBody.output_id == output_id).first())
            if art is None:
                return payload_fields
            body, meta = art.body, dict(art.meta or {})
    except Exception:                                            # noqa: BLE001
        return payload_fields
    out = dict(payload_fields or {})
    if body and body.strip():
        out["body_html"] = body
    for k in ("title", "seo_title", "seo_description"):
        if str(meta.get(k, "") or "").strip():
            out[k] = meta[k]
    return out


def _published(res: str) -> bool:
    """Did a backend write actually happen? Every SEO arm below asks this.

    A BACKEND REFUSAL IS A STRING, NOT AN EXCEPTION. `seo_guard.check` returns
    a reason so an agent gets a sentence rather than a stack trace, and a
    backend's `_ok` reports an unconfigured store the same way — both arrive
    here as an ordinary return value. An arm that interpolates that value
    after the word "created" therefore announces a BLOCKED write as a done
    one: "📄 Page created (baci): Refused — banned_claim: ...".
    Three of the five kinds below read that way, which hid the ban list from
    the only person who could act on it.

    A write that succeeded returns a URL; anything else failed. WordPress
    falls back to "(created)"/"(updated)" when its REST response omits `link`,
    so a rare success is reported here as a failure — that is the safe
    direction of this error, because somebody investigates it.
    """
    return str(res or "").startswith("http")


def _execute(ap: db.Approval) -> None:
    if ap.kind == "send_email":
        p = ap.payload
        draft_id = p.get("draft_id") or ""
        if draft_id:
            # SEND THE DRAFT, not a copy of what it said when it was written.
            # This is what keeps the queue and the mailbox in step: whatever
            # goes out is what was approved, an edit made in Gmail goes with
            # it, and nothing is left behind to pile up.
            from . import edits
            live = gmail_client.read_draft(p["account"], draft_id)
            if not live:
                # The draft is gone, so somebody already sent or deleted it
                # outside the queue. Sending now would deliver the ORIGINAL
                # text a second time, to the same customer, on the same
                # thread — the exact duplicate this change exists to stop.
                return
            gmail_client.send_draft(p["account"], draft_id)
            edits.record(ap, p.get("body", ""), live.get("body", ""))
        else:
            # No draft behind it — a reply composed somewhere else, or an
            # approval queued before this existed.
            gmail_client.send_email(p["account"], p["to"], p["subject"],
                                    p["body"], p.get("thread_id"),
                                    cc=p.get("cc", ""))
        if p.get("expect_reply"):
            import datetime as dt
            with db.SessionLocal() as s:
                s.add(db.FollowUp(
                    account=p["account"], tenant=ap.tenant or "",
                    thread_id=p.get("thread_id"),
                    to=p["to"], subject=p["subject"],
                    due_date=(dt.date.today() + dt.timedelta(days=3)).isoformat(),
                ))
                s.commit()
    elif ap.kind == "refile_moves":
        from . import drive_io, whatsapp
        p = ap.payload
        alias = p.get("account", "baci")
        b2b = drive_io.find_folder(alias, "B2B")
        done, failed = 0, 0
        for m in p.get("moves", []):
            try:
                folder_id = drive_io.ensure_path(alias, b2b, m["to"])
                drive_io.move(alias, m["file_id"], folder_id)
                done += 1
                from . import data_tools
                data_tools.index_document(
                    m["from"].rsplit("/", 1)[-1], m["to"],
                    anchor=m["to"].rsplit("/", 1)[-1], source="refile")
            except Exception:  # noqa: BLE001
                failed += 1
        whatsapp.send_text(f"📁 Refile executed: {done} files moved"
                           + (f", {failed} failed (left in place)" if failed else "") + ".")
    elif ap.kind == "seo_update":
        from . import sites, whatsapp
        p = ap.payload
        profile = sites.get(p.get("site"))
        res = sites.backend(profile).update_seo(
            profile, p["resource"], p["resource_id"], p["fields"])
        whatsapp.send_text(
            f"🔎 SEO updated ({p.get('site')}): {res}" if _published(res)
            else f"⛔ SEO NOT updated ({p.get('site')}): {res}")
    elif ap.kind == "seo_new_collection":
        from . import sites, whatsapp
        p = ap.payload
        profile = sites.get(p.get("site"))
        res = sites.backend(profile).create_collection(
            profile, p["fields"], p.get("item_ids"))
        whatsapp.send_text(
            f"🆕 Created ({p.get('site')}): {res}" if _published(res)
            else f"⛔ NOT created ({p.get('site')}): {res}")
    elif ap.kind == "seo_new_page":
        from . import sites, whatsapp
        p = ap.payload
        profile = sites.get(p.get("site"))
        res = sites.backend(profile).create_page(profile, p["fields"])
        whatsapp.send_text(
            f"📄 Page created ({p.get('site')}): {res}" if _published(res)
            else f"⛔ Page NOT created ({p.get('site')}): {res}")
    elif ap.kind == "seo_new_article":
        from . import keywords, seo_guard, sites, whatsapp
        p = ap.payload
        profile = sites.get(p.get("site"))
        # THE PUSH USES WHAT WAS REVIEWED. The payload's fields carry the
        # machine-set half (handle, structured_data, published, tags), and the
        # ARTIFACT carries what a person can change — its body and its
        # identity. Overlaying rather than choosing means the edit screen's
        # promise ("the push uses exactly this") is true by construction
        # instead of by two copies staying in step, which they did not: an
        # edit made with no pending approval never reached the payload at all.
        res = sites.backend(profile).create_article(
            profile, p.get("blog_id") or None,
            _fields_from_artifact(p.get("output_id") or "", p["fields"]))
        if _published(res):
            # CLOSE THE LOOP, which this arm never did: the 2026-08-26 audit
            # found create_article's return — which BEGINS with the live URL —
            # was interpolated into a WhatsApp message and discarded, so no
            # production code had ever written target_url/published_at and
            # `progress` had a structurally starved cohort. The URL is the
            # first token by both backends' convention (`_published` already
            # depends on it); the write-back joins on the output_id the
            # payload now carries.
            if p.get("output_id"):
                keywords.mark_published(
                    seo_guard.tenant_for(profile) or (ap.tenant or ""),
                    p["output_id"], url=res.split()[0].rstrip(".,"))
                # Published work is not held work: release the workroom's
                # Save-for-later hold so the In-progress strip only ever
                # lists things still owed a decision.
                try:
                    with db.SessionLocal() as s:
                        row = (s.query(db.ArtifactBody)
                               .filter(db.ArtifactBody.output_id ==
                                       p["output_id"]).first())
                        if row is not None and (row.state or "") == "in_review":
                            row.state = ""
                            s.commit()
                except Exception:                                # noqa: BLE001
                    pass
        whatsapp.send_text(
            f"📝 Article created ({p.get('site')}): {res}"
            if _published(res)
            else f"⛔ Article NOT created ({p.get('site')}): {res}")
    elif ap.kind == "seo_article_revision":
        from . import sites, whatsapp
        p = ap.payload
        profile = sites.get(p.get("site"))
        res = sites.backend(profile).update_article(
            profile, p.get("blog_id") or None, p["article_id"], p["fields"])
        whatsapp.send_text(
            f"✏️ Article revised ({p.get('site')}): {res}"
            if _published(res)
            else f"⛔ Article NOT revised ({p.get('site')}): {res}")
    elif ap.kind == "shopify_theme_asset":
        from . import sites, whatsapp
        p = ap.payload
        profile = sites.get(p.get("site"))
        msg = sites.backend(profile).install_schema_renderer(profile)
        whatsapp.send_text(f"🧩 {msg}")
    elif ap.kind == "systems_update":
        from . import systems_map, whatsapp
        p = ap.payload
        systems_map.set_doc(p["key"], p["content"], title=p.get("title", ""),
                            updated_by="approval", pinned=p.get("pinned"))
        whatsapp.send_text(f"🗺 Systems Map adopted: {p['key']} — filing and "
                           "organizing now conform to it.")
    # Future kinds: buy_label (Phase 4), pay (never auto), book_freight (Phase 5)


def autonomy_stats(days: int = 30) -> dict:
    """Approve/deny rates per bucket — the data behind earned autonomy."""
    import datetime as dt
    since = db.utcnow() - dt.timedelta(days=days)
    stats: dict[str, dict[str, int]] = {}
    with db.SessionLocal() as s:
        for ap in (s.query(db.Approval)
                   .filter(db.Approval.created_at >= since,
                           db.Approval.status.in_(["executed", "approved", "denied"]))
                   .all()):
            bucket = (ap.payload or {}).get("bucket", "unknown")
            d = stats.setdefault(bucket, {"approved": 0, "denied": 0})
            d["approved" if ap.status in ("executed", "approved") else "denied"] += 1
    for d in stats.values():
        total = d["approved"] + d["denied"]
        d["approval_rate"] = round(100 * d["approved"] / total) if total else 0
    return stats


def decided_in_console(ap) -> bool:
    """Is this approval a decision the console actually collects?

    ONE predicate, because the count and the list must never disagree (design
    rule 8: counts come from the lists actually rendered). The "N waiting"
    pill links straight at the queue, so a pill that counts a row the queue
    does not show is a lie you catch in a single click.

    A drafted reply is the one exception, and it is the owner's rule
    (2026-08-27): the draft is in the client's own mailbox, answering the
    customer from there IS approving it, and `reconcile_drafts` closes the
    row and records what changed. Nothing is lost by not asking here — the
    only thing asking could add is a second copy of the same letter.

    A `send_email` with NO `draft_id` — an RFQ, an invoice reminder, a
    shipment follow-up — exists nowhere but this queue, so it stays.
    """
    return not (getattr(ap, "kind", "") == "send_email"
                and (getattr(ap, "payload", None) or {}).get("draft_id"))


def pending_count(tenant: str = "") -> int:
    """How many decisions are waiting — for one client, or for everyone.

    `Approval.tenant` has been filled since attribution was wired, and this
    counted every row regardless, so the "N waiting" beside one client's name
    in the console was another client's backlog. `tenant=""` still means every
    account, because the digest and the ops channel genuinely want that number.

    Counted through `decided_in_console`, not with a bare `.count()`, so the
    pill and the queue it points at can never drift apart.
    """
    with db.SessionLocal() as s:
        q = s.query(db.Approval).filter(db.Approval.status == "pending")
        if tenant:
            q = q.filter(db.Approval.tenant == tenant)
        return sum(1 for ap in q.all() if decided_in_console(ap))


def _fmt(payload: dict) -> str:
    return "\n".join(f"  {k}: {str(v)[:500]}" for k, v in payload.items())
