"""Approval flow: email links today, WhatsApp buttons when enabled.

Every gated action -> Approval row -> notification to Gomeh -> webhook/link
decision -> execution. Tokens are signed; links expire after 7 days.
"""
import datetime as dt

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from . import config, db, gmail_client, whatsapp

_signer = URLSafeTimedSerializer(config.APPROVAL_SECRET)


def request_approval(kind: str, summary: str, payload: dict) -> str:
    """Create a pending approval and notify Gomeh. Returns approval id."""
    with db.SessionLocal() as s:
        ap = db.Approval(kind=kind, summary=summary, payload=payload,
                         channel="whatsapp" if config.WHATSAPP_ENABLED else "email")
        s.add(ap)
        s.commit()
        ap_id = ap.id

    if config.WHATSAPP_ENABLED:
        whatsapp.send_approval(ap_id, summary)
    else:
        approve = f"{config.PUBLIC_BASE_URL}/decide/{_signer.dumps([ap_id, 'approved'])}"
        deny = f"{config.PUBLIC_BASE_URL}/decide/{_signer.dumps([ap_id, 'denied'])}"
        gmail_client.send_email(
            config.NOTIFY_FROM_ALIAS,
            config.APPROVER_EMAIL,
            f"[APPROVAL NEEDED] {summary}",
            f"{summary}\n\nDetails:\n{_fmt(payload)}\n\n"
            f"APPROVE: {approve}\n\nDENY: {deny}\n\n— Your assistant",
        )
    return ap_id


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
