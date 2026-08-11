"""Telegram Bot API adapter — the ops channel.

Same surface as `whatsapp.py` (send_text / send_approval / download_media /
transcribe) so callers can use either channel without knowing which. Dormant
until TELEGRAM_* env vars are set.

Chosen over WhatsApp for ops notifications (Aug 2026): almost everything this
channel sends is business-initiated ("this is blocked", "this needs approval"),
which is exactly the category WhatsApp restricts behind the 24-hour window and
pre-approved templates. Telegram has no window and no template review, plus two
affordances that matter here: real inline buttons, and editMessageText so an
answered prompt is rewritten in place instead of scrolling away.

Security: bot tokens are bearer credentials and bot usernames are discoverable,
so every inbound update is checked against TELEGRAM_ALLOWED_CHAT_IDS and
silently dropped otherwise. This bot can write to the KB — it is not public.
"""
import hashlib

import httpx

from . import config


def wire_secret() -> str:
    """The value actually sent to Telegram as `secret_token`.

    Telegram only accepts [A-Za-z0-9_-] there, but Render's `generateValue`
    can emit characters outside that set (which is how this first failed with
    "secret token contains unallowed characters"). So we send a sha256 digest
    of the configured secret rather than the secret itself: always hex, always
    valid, always under the 256-char limit, deterministic on both ends — and
    the raw secret never leaves our own infrastructure.

    The webhook handler compares against this same derived value, so the two
    halves can never drift.
    """
    raw = config.TELEGRAM_WEBHOOK_SECRET or ""
    return hashlib.sha256(raw.encode()).hexdigest() if raw else ""

API = "https://api.telegram.org"

# Telegram hard limits (exceeding them is a 400, not a truncation).
TEXT_LIMIT = 4096
CALLBACK_DATA_LIMIT = 64


class TelegramSendError(Exception):
    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def _call(method: str, payload: dict, timeout: int = 30) -> dict:
    r = httpx.post(
        f"{API}/bot{config.TELEGRAM_BOT_TOKEN}/{method}",
        json=payload,
        timeout=timeout,
    )
    if r.status_code >= 400:
        try:
            err = r.json()
        except Exception:  # noqa: BLE001
            err = {}
        raise TelegramSendError(err.get("error_code", r.status_code),
                                err.get("description", r.text[:200]))
    return r.json().get("result", {}) or {}


def is_allowed(chat_id) -> bool:
    """Fail closed: an empty allowlist authorises nobody but the approver."""
    return str(chat_id) in config.TELEGRAM_ALLOWED_CHAT_IDS


def _remember_sent(message_id, content: str, approval_id: str = "") -> None:
    """Record outbound messages so a reply can be resolved back to its prompt.

    Reuses db.WaMessage with a 'tg:' prefix rather than adding a parallel table
    — the id space is namespaced so it can never collide with a wamid.
    """
    if not message_id:
        return
    from . import db
    try:
        with db.SessionLocal() as s:
            s.merge(db.WaMessage(wamid=f"tg:{message_id}", role="assistant",
                                 content=content[:6000], approval_id=approval_id))
            s.commit()
    except Exception:  # noqa: BLE001
        pass


def send_text(body: str, email_fallback: bool = True,
              chat_id: str = "", reply_markup: dict | None = None) -> int:
    """Send to the ops chat. Returns the Telegram message_id (0 on failure).

    email_fallback=False for callers with their OWN fallback — same contract as
    whatsapp.send_text, so the approval ladder's single-digest behaviour holds.
    """
    if not config.TELEGRAM_ENABLED:
        return 0
    payload: dict = {
        "chat_id": chat_id or config.TELEGRAM_CHAT_ID,
        "text": body[:TEXT_LIMIT],
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        res = _call("sendMessage", payload)
        mid = res.get("message_id", 0)
        _remember_sent(mid, body)
        return mid
    except TelegramSendError as exc:
        # 401 = revoked/incorrect token, 403 = bot blocked or never started by
        # the user. Both are config faults worth naming rather than swallowing.
        if exc.code in (401, 403):
            _fallback(f"⚠️ Telegram rejected the send ({exc.code}: "
                      f"{exc.message}). Check TELEGRAM_BOT_TOKEN, and make sure "
                      "you have pressed Start on the bot.\n\nOriginal message:\n"
                      + body)
            return 0
    except Exception:  # noqa: BLE001
        pass
    if email_fallback:
        _fallback(body)
    return 0


def _fallback(body: str) -> None:
    """Reuse whatsapp's hardened email fallback rather than duplicating it.

    That path already carries the storm guard added after a notify burst sent
    200 'Assistant update' emails in a minute (Jul 2026) — dedupe by body hash
    plus an hourly cap. Worth the private import to not re-learn that lesson.
    """
    from . import whatsapp
    try:
        whatsapp._email_fallback(body, "Telegram was unavailable")
    except Exception:  # noqa: BLE001
        pass


def send_approval(approval_id: str, summary: str, detail: dict | None = None) -> bool:
    """Full draft plus inline Approve/Deny/Edit buttons in ONE message.

    Unlike WhatsApp (1024-char interactive body forced a second message), the
    whole thing fits in a single 4096-char message with the keyboard attached —
    so the chat stays one row per decision. Returns True only if Telegram
    accepted it; the caller keeps its own fallback so an approval is never lost.
    """
    detail = detail or {}
    parts = [summary[:400]]
    if detail.get("cc"):
        parts.append(f"Cc: {detail['cc']}")
    if detail.get("inbound_snippet"):
        parts.append(f"\n— They wrote —\n{detail['inbound_snippet'][:500]}")
    if detail.get("body"):
        parts.append(f"\n— Proposed reply —\n{detail['body'][:2500]}")
    if detail.get("suggestion"):
        parts.append(f"\n💡 {detail['suggestion']}")
    full = "\n".join(parts)

    # callback_data is capped at 64 BYTES by Telegram; anything longer is
    # rejected outright, so guard rather than truncate into a wrong id.
    keyboard = []
    for action, label in (("approve", "✅ Approve"),
                          ("deny", "❌ Deny"),
                          ("edit", "✏️ Edit")):
        data = f"{action}:{approval_id}"
        if len(data.encode()) > CALLBACK_DATA_LIMIT:
            return False
        keyboard.append({"text": label, "callback_data": data})

    if not config.TELEGRAM_ENABLED:
        return False
    try:
        res = _call("sendMessage", {
            "chat_id": config.TELEGRAM_CHAT_ID,
            "text": full[:TEXT_LIMIT],
            "disable_web_page_preview": True,
            "reply_markup": {"inline_keyboard": [keyboard]},
        })
    except Exception:  # noqa: BLE001 — report, never lose the approval
        return False
    _remember_sent(res.get("message_id", 0), full, approval_id=approval_id)
    return True


def ask(question: str, field: str, options: list[str] | None = None) -> int:
    """Ask for a blocking input (a missing KB field) and expect a typed reply.

    Used when the pipeline refuses to proceed — e.g. Ironside has no rate card,
    so the quote stops and this asks for it rather than inventing a number.
    """
    markup = None
    if options:
        row = []
        for opt in options[:3]:
            data = f"field:{field}:{opt}"
            if len(data.encode()) <= CALLBACK_DATA_LIMIT:
                row.append({"text": opt, "callback_data": data})
        if row:
            markup = {"inline_keyboard": [row]}
    return send_text(f"❓ {question}", reply_markup=markup)


def resolve(message_id: int, outcome: str) -> None:
    """Rewrite an answered prompt in place so the chat reads as a ledger.

    Telegram-only affordance and the reason this channel stays usable at 20
    decisions a week — answered items stop competing for attention.
    """
    if not (config.TELEGRAM_ENABLED and message_id):
        return
    try:
        _call("editMessageText", {
            "chat_id": config.TELEGRAM_CHAT_ID,
            "message_id": message_id,
            "text": outcome[:TEXT_LIMIT],
            "disable_web_page_preview": True,
        })
    except Exception:  # noqa: BLE001
        pass


def ack(callback_query_id: str, text: str = "") -> None:
    """Answer a button tap. Without this the client spins for ~30s."""
    if not config.TELEGRAM_ENABLED:
        return
    try:
        _call("answerCallbackQuery",
              {"callback_query_id": callback_query_id, "text": text[:200]})
    except Exception:  # noqa: BLE001
        pass


def download_media(file_id: str) -> tuple[bytes, str]:
    """Fetch a received voice note / photo / document. Two hops: getFile for
    the path, then the file endpoint (a different host prefix to the API)."""
    meta = _call("getFile", {"file_id": file_id})
    path = meta.get("file_path", "")
    if not path:
        raise RuntimeError(f"Telegram getFile returned no file_path for {file_id}")
    data = httpx.get(f"{API}/file/bot{config.TELEGRAM_BOT_TOKEN}/{path}", timeout=60)
    data.raise_for_status()
    mime = "audio/ogg" if path.endswith(".oga") or path.endswith(".ogg") else ""
    return data.content, mime or "application/octet-stream"


def transcribe(audio: bytes, mime: str) -> str:
    """Voice note -> text. Delegates to the existing Whisper path so both
    channels transcribe identically."""
    from . import whatsapp
    return whatsapp.transcribe(audio, mime)


def set_webhook(base_url: str) -> dict:
    """Point Telegram at /telegram/webhook. Run once per deploy target.

    secret_token is echoed back in the X-Telegram-Bot-Api-Secret-Token header
    on every update — the webhook handler must reject anything without it.
    """
    return _call("setWebhook", {
        "url": f"{base_url.rstrip('/')}/telegram/webhook",
        "secret_token": wire_secret(),
        "allowed_updates": ["message", "callback_query"],
    })
