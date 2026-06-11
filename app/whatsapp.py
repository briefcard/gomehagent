"""WhatsApp Cloud API adapter. Dormant until WHATSAPP_* env vars are set.

Once the Baci Milano number (Google Voice -> Cloud API) is verified by Meta,
set WHATSAPP_TOKEN / WHATSAPP_PHONE_ID / WHATSAPP_APPROVER_NUMBER and
approvals + escalations switch from email to WhatsApp automatically.
"""
import httpx

from . import config

API = "https://graph.facebook.com/v21.0"


def _post(payload: dict) -> None:
    httpx.post(
        f"{API}/{config.WHATSAPP_PHONE_ID}/messages",
        headers={"Authorization": f"Bearer {config.WHATSAPP_TOKEN}"},
        json=payload,
        timeout=30,
    ).raise_for_status()


def send_text(body: str) -> None:
    if not config.WHATSAPP_ENABLED:
        return
    _post({
        "messaging_product": "whatsapp",
        "to": config.WHATSAPP_APPROVER_NUMBER,
        "type": "text",
        "text": {"body": body[:4096]},
    })


def send_approval(approval_id: str, summary: str) -> None:
    """Interactive Approve/Deny buttons; replies handled in web.py webhook."""
    _post({
        "messaging_product": "whatsapp",
        "to": config.WHATSAPP_APPROVER_NUMBER,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": f"Approval needed:\n{summary[:900]}"},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": f"approve:{approval_id}", "title": "Approve"}},
                    {"type": "reply", "reply": {"id": f"deny:{approval_id}", "title": "Deny"}},
                ]
            },
        },
    })
