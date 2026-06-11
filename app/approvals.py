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
        notify_batch([ap_id])
    return ap_id


def notify_batch(ap_ids: list[str], title: str | None = None) -> None:
    """One notification covering many approvals, each with its own links."""
    if not ap_ids:
        return
    with db.SessionLocal() as s:
        aps = s.query(db.Approval).filter(db.Approval.id.in_(ap_ids)).all()
    if config.WHATSAPP_ENABLED:
        for ap in aps:
            whatsapp.send_approval(ap.id, ap.summary)
        return
    blocks = []
    for i, ap in enumerate(aps, 1):
        approve = f"{config.PUBLIC_BASE_URL}/decide/{_signer.dumps([ap.id, 'approved'])}"
        deny = f"{config.PUBLIC_BASE_URL}/decide/{_signer.dumps([ap.id, 'denied'])}"
        body = ap.payload.get("body", "")
        blocks.append(
            f"{'-' * 50}\n{i}. {ap.summary}\n\n"
            f"DRAFT:\n{body[:1500]}\n\n"
            f"APPROVE & SEND: {approve}\nDENY: {deny}\n"
        )
    subject = title or f"[{len(aps)} replies awaiting your approval]"
    gmail_client.send_email(
        config.NOTIFY_FROM_ALIAS, config.APPROVER_EMAIL, subject,
        f"Review each draft, then click its link. Drafts also sit in each "
        f"inbox's Drafts folder if you'd rather edit before sending "
        f"(editing there = edit then send manually, then DENY here).\n\n"
        + "\n".join(blocks) + "\n— Your assistant",
    )


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
                                p.get("thread_id"))
    # Future kinds: buy_label (Phase 4), pay (never auto), book_freight (Phase 5)


def pending_count() -> int:
    with db.SessionLocal() as s:
        return s.query(db.Approval).filter(db.Approval.status == "pending").count()


def _fmt(payload: dict) -> str:
    return "\n".join(f"  {k}: {str(v)[:500]}" for k, v in payload.items())
