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


import os

WHATSAPP_TEMPLATE_NAME = os.environ.get("WHATSAPP_TEMPLATE_NAME", "")


def send_text(body: str) -> None:
    if not config.WHATSAPP_ENABLED:
        return
    try:
        _post({
            "messaging_product": "whatsapp",
            "to": config.WHATSAPP_APPROVER_NUMBER,
            "type": "text",
            "text": {"body": body[:4096]},
        })
        return
    except Exception:  # noqa: BLE001 — 24h window closed or API hiccup
        pass
    # 24h window closed: try an approved template message (reopens nothing,
    # but reaches the phone). Falls back to email if no template configured.
    if WHATSAPP_TEMPLATE_NAME:
        try:
            # Template parameters may not contain newlines.
            flat = " | ".join(line.strip() for line in body.splitlines()
                              if line.strip())[:900]
            _post({
                "messaging_product": "whatsapp",
                "to": config.WHATSAPP_APPROVER_NUMBER,
                "type": "template",
                "template": {"name": WHATSAPP_TEMPLATE_NAME,
                             "language": {"code": "en_US"},
                             "components": [{"type": "body", "parameters": [
                                 {"type": "text", "text": flat}]}]},
            })
            return
        except Exception:  # noqa: BLE001
            pass
    _email_fallback(body)


def _email_fallback(body: str) -> None:
    from . import emailfmt, gmail_client  # local import avoids circular dependency

    try:
        first_line = next((ln for ln in body.splitlines() if ln.strip()), "update")
        gmail_client.send_email(
            config.NOTIFY_FROM_ALIAS,
            config.APPROVER_EMAIL,
            "Assistant update: " + first_line[:70],
            body + "\n\nDelivered by email because the WhatsApp 24-hour window "
                   "was closed. Send the agent any WhatsApp message to reopen it.",
            html=emailfmt.text_to_html(
                body + "\n\nDelivered by email because the WhatsApp 24-hour "
                       "window was closed. Send the agent any WhatsApp message "
                       "to reopen it."),
        )
    except Exception:  # noqa: BLE001
        pass


def download_media(media_id: str) -> tuple[bytes, str]:
    """Download a received media file (voice note, image, doc) from Meta."""
    meta = httpx.get(
        f"{API}/{media_id}",
        headers={"Authorization": f"Bearer {config.WHATSAPP_TOKEN}"},
        timeout=30,
    ).json()
    data = httpx.get(
        meta["url"],
        headers={"Authorization": f"Bearer {config.WHATSAPP_TOKEN}"},
        timeout=60,
    )
    data.raise_for_status()
    return data.content, meta.get("mime_type", "audio/ogg")


def transcribe(audio: bytes, mime: str) -> str:
    """Speech-to-text via OpenAI Whisper. Needs OPENAI_API_KEY env var."""
    import os
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        raise RuntimeError("OPENAI_API_KEY not set")
    ext = "ogg" if "ogg" in mime else "m4a" if "mp4" in mime else "mp3"
    r = httpx.post(
        "https://api.openai.com/v1/audio/transcriptions",
        headers={"Authorization": f"Bearer {key}"},
        data={"model": "whisper-1"},
        files={"file": (f"note.{ext}", audio, mime)},
        timeout=120,
    )
    r.raise_for_status()
    return r.json().get("text", "").strip()


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
