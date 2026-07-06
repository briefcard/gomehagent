"""Approval flow: email links today, WhatsApp buttons when enabled.

Every gated action -> Approval row -> notification to Gomeh -> webhook/link
decision -> execution. Tokens are signed; links expire after 7 days.
"""
import datetime as dt

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from . import config, db, gmail_client, whatsapp

_signer = URLSafeTimedSerializer(config.APPROVAL_SECRET)


def request_approval(kind: str, summary: str, payload: dict, notify: bool = True) -> str:
    """Create a pending approval. notify=False lets the caller batch
    notifications (one email per poll cycle instead of one per item)."""
    with db.SessionLocal() as s:
        ap = db.Approval(kind=kind, summary=summary, payload=payload,
                         channel="whatsapp" if config.WHATSAPP_ENABLED else "email")
        s.add(ap)
        s.commit()
        ap_id = ap.id

    if notify:
        notify_pending()
    return ap_id


MAX_WA_NOTIFY_ATTEMPTS = 3  # then fall back to approve-by-email-link


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
        items = [(ap.id, ap.summary, dict(ap.payload))
                 for ap in aps if not ap.payload.get("_notified")]
    if not items:
        return 0

    if config.WHATSAPP_ENABLED:
        sent, fallback = 0, []
        for ap_id, summary, payload in items:
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
                _email_approvals(fallback, "WhatsApp unreachable — approve "
                                           "these by link instead")
                for ap_id, _, _ in fallback:
                    _set_payload_flags(ap_id, _notified=True)
                sent += len(fallback)
            except Exception:  # noqa: BLE001 — stays pending; next cycle retries
                pass
        return sent

    _email_approvals(items, title)
    for ap_id, _, _ in items:  # only after the send call succeeded
        _set_payload_flags(ap_id, _notified=True)
    return len(items)


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
        s.commit()
        if decision == "approved":
            _execute(ap)
            ap.status = "executed"
            ap.executed_at = db.utcnow()
            s.commit()
            return f"Approved and executed: {ap.summary}"
        return f"Denied: {ap.summary}"


def _execute(ap: db.Approval) -> None:
    if ap.kind == "send_email":
        p = ap.payload
        gmail_client.send_email(p["account"], p["to"], p["subject"], p["body"],
                                p.get("thread_id"), cc=p.get("cc", ""))
        if p.get("expect_reply"):
            import datetime as dt
            with db.SessionLocal() as s:
                s.add(db.FollowUp(
                    account=p["account"], thread_id=p.get("thread_id"),
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
        url = sites.backend(profile).update_seo(
            profile, p["resource"], p["resource_id"], p["fields"])
        whatsapp.send_text(f"🔎 SEO updated ({p.get('site')}): {url}")
    elif ap.kind == "seo_new_collection":
        from . import sites, whatsapp
        p = ap.payload
        profile = sites.get(p.get("site"))
        url = sites.backend(profile).create_collection(
            profile, p["fields"], p.get("item_ids"))
        whatsapp.send_text(f"🆕 Created ({p.get('site')}): {url}")
    elif ap.kind == "seo_new_page":
        from . import sites, whatsapp
        p = ap.payload
        profile = sites.get(p.get("site"))
        url = sites.backend(profile).create_page(profile, p["fields"])
        whatsapp.send_text(f"📄 Page created ({p.get('site')}): {url}")
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


def pending_count() -> int:
    with db.SessionLocal() as s:
        return s.query(db.Approval).filter(db.Approval.status == "pending").count()


def _fmt(payload: dict) -> str:
    return "\n".join(f"  {k}: {str(v)[:500]}" for k, v in payload.items())
