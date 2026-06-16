"""WhatsApp Cloud API adapter. Dormant until WHATSAPP_* env vars are set.

Once the Baci Milano number (Google Voice -> Cloud API) is verified by Meta,
set WHATSAPP_TOKEN / WHATSAPP_PHONE_ID / WHATSAPP_APPROVER_NUMBER and
approvals + escalations switch from email to WhatsApp automatically.
"""
import httpx

from . import config

API = "https://graph.facebook.com/v21.0"


class MetaSendError(Exception):
    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def _post(payload: dict) -> str:
    r = httpx.post(
        f"{API}/{config.WHATSAPP_PHONE_ID}/messages",
        headers={"Authorization": f"Bearer {config.WHATSAPP_TOKEN}"},
        json=payload,
        timeout=30,
    )
    if r.status_code >= 400:
        try:
            err = r.json().get("error", {})
        except Exception:  # noqa: BLE001
            err = {}
        raise MetaSendError(err.get("code", r.status_code),
                            err.get("message", r.text[:200]))
    try:
        return r.json()["messages"][0]["id"]  # wamid of the sent message
    except Exception:  # noqa: BLE001
        return ""


def _remember_sent(wamid: str, content: str, approval_id: str = "") -> None:
    if not wamid:
        return
    from . import db
    try:
        with db.SessionLocal() as s:
            s.merge(db.WaMessage(wamid=wamid, role="assistant",
                                 content=content[:6000], approval_id=approval_id))
            s.commit()
    except Exception:  # noqa: BLE001
        pass


import os

WHATSAPP_TEMPLATE_NAME = os.environ.get("WHATSAPP_TEMPLATE_NAME", "")


def send_text(body: str) -> None:
    if not config.WHATSAPP_ENABLED:
        return
    err: MetaSendError | None = None
    try:
        wamid = _post({
            "messaging_product": "whatsapp",
            "to": config.WHATSAPP_APPROVER_NUMBER,
            "type": "text",
            "text": {"body": body[:4096]},
        })
        _remember_sent(wamid, body)
        return
    except MetaSendError as exc:
        err = exc
    except Exception:  # noqa: BLE001
        pass
    # Diagnose honestly instead of blaming the 24h window for everything.
    if err and err.code == 190:
        _email_fallback("⚠️ My WhatsApp access token is invalid or expired "
                        f"(Meta error 190: {err.message}). Update WHATSAPP_TOKEN "
                        "in Render with a fresh system-user token.\n\n"
                        "Original message:\n" + body)
        return
    window_closed = bool(err and err.code in (131047, 131026))
    # Closed window (or unknown failure): try an approved template message.
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
    if window_closed:
        _email_fallback(body, "the WhatsApp 24-hour window was closed — any "
                              "WhatsApp message from you reopens it")
    else:
        _email_fallback(body, "WhatsApp send failed"
                        + (f" (Meta error {err.code}: {err.message})" if err else ""))


def _email_fallback(body: str, reason: str = "WhatsApp was unavailable") -> None:
    from . import emailfmt, gmail_client  # local import avoids circular dependency

    try:
        first_line = next((ln for ln in body.splitlines() if ln.strip()), "update")
        full = body + f"\n\nDelivered by email because {reason}."
        gmail_client.send_email(
            config.NOTIFY_FROM_ALIAS,
            config.APPROVER_EMAIL,
            "Assistant update: " + first_line[:70],
            full,
            html=emailfmt.text_to_html(full),
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


def send_approval(approval_id: str, summary: str, detail: dict | None = None) -> None:
    """Interactive Approve/Deny/Edit buttons WITH the full draft inline, so
    Gomeh can decide from WhatsApp without opening email."""
    detail = detail or {}
    parts = [summary[:300]]
    if detail.get("inbound_snippet"):
        parts.append(f"\n— They wrote —\n{detail['inbound_snippet'][:400]}")
    if detail.get("body"):
        parts.append(f"\n— Proposed reply —\n{detail['body'][:2400]}")
    if detail.get("suggestion"):
        parts.append(f"\n💡 {detail['suggestion']}")
    text = "\n".join(parts)[:3900]  # WhatsApp interactive body cap is 4096
    wamid = _post({
        "messaging_product": "whatsapp",
        "to": config.WHATSAPP_APPROVER_NUMBER,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": text},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": f"approve:{approval_id}", "title": "✅ Approve"}},
                    {"type": "reply", "reply": {"id": f"deny:{approval_id}", "title": "❌ Deny"}},
                    {"type": "reply", "reply": {"id": f"edit:{approval_id}", "title": "✏️ Edit"}},
                ]
            },
        },
    })
    _remember_sent(wamid, text, approval_id=approval_id)
