"""Multi-account Gmail access.

Each inbox authorizes ONCE (scripts/google_oauth.py) and its refresh token
lives in GMAIL_ACCOUNTS_JSON. No sign-outs, no re-auth — tokens refresh
automatically forever (unless revoked).
"""
import base64
from email.message import EmailMessage

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from . import config

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/drive.readonly",
]

_services: dict = {}
_creds: dict = {}


def creds_for(alias: str) -> Credentials:
    """Refresh-token credentials for one account (shared by Gmail + Drive)."""
    if alias not in _creds:
        acct = config.GMAIL_ACCOUNTS[alias]
        creds = Credentials(
            token=None,
            refresh_token=acct["refresh_token"],
            client_id=config.GOOGLE_CLIENT_ID,
            client_secret=config.GOOGLE_CLIENT_SECRET,
            token_uri="https://oauth2.googleapis.com/token",
        )
        creds.refresh(Request())
        _creds[alias] = creds
    return _creds[alias]


def service_for(alias: str):
    """Build (and cache) a Gmail API client for one inbox alias."""
    if alias not in _services:
        _services[alias] = build(
            "gmail", "v1", credentials=creds_for(alias), cache_discovery=False
        )
    return _services[alias]


def fetch_unread(alias: str, max_results: int = 20) -> list[dict]:
    """Return unread inbox messages (metadata + plain-text body)."""
    svc = service_for(alias)
    resp = (
        svc.users()
        .messages()
        .list(userId="me", q="is:unread in:inbox", maxResults=max_results)
        .execute()
    )
    out = []
    for ref in resp.get("messages", []):
        msg = svc.users().messages().get(userId="me", id=ref["id"], format="full").execute()
        headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
        out.append(
            {
                "id": msg["id"],
                "threadId": msg["threadId"],
                "from": headers.get("from", ""),
                "to": headers.get("to", ""),
                "subject": headers.get("subject", ""),
                "date": headers.get("date", ""),
                "body": _extract_text(msg["payload"]),
            }
        )
    return out


def _extract_text(payload: dict) -> str:
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode(errors="replace")
    for part in payload.get("parts", []) or []:
        text = _extract_text(part)
        if text:
            return text
    return ""


def fetch_unanswered(alias: str, days: int = 14, max_threads: int = 50) -> list[dict]:
    """Inbox threads from the last N days where the LAST message is not ours —
    i.e. emails that still need a response. Used for the startup backlog sweep."""
    svc = service_for(alias)
    me = config.GMAIL_ACCOUNTS[alias]["email"].lower()
    resp = (
        svc.users()
        .threads()
        .list(userId="me", q=f"in:inbox -from:me newer_than:{days}d", maxResults=max_threads)
        .execute()
    )
    out = []
    for ref in resp.get("threads", []):
        thread = svc.users().threads().get(userId="me", id=ref["id"], format="full").execute()
        msgs = thread.get("messages", [])
        if not msgs:
            continue
        last = msgs[-1]
        headers = {h["name"].lower(): h["value"] for h in last["payload"].get("headers", [])}
        if me in headers.get("from", "").lower():
            continue  # we already replied last — not awaiting us
        out.append(
            {
                "id": last["id"],
                "threadId": thread["id"],
                "from": headers.get("from", ""),
                "to": headers.get("to", ""),
                "subject": headers.get("subject", ""),
                "date": headers.get("date", ""),
                "body": _extract_text(last["payload"]),
            }
        )
    return out


def get_thread_context(alias: str, thread_id: str, limit: int = 5) -> str:
    """Last few messages of a thread, formatted for the triage prompt."""
    svc = service_for(alias)
    thread = svc.users().threads().get(userId="me", id=thread_id, format="full").execute()
    parts = []
    for msg in thread.get("messages", [])[-limit:]:
        headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
        parts.append(
            f"--- {headers.get('date', '?')} | From: {headers.get('from', '?')} ---\n"
            f"{_extract_text(msg['payload'])[:2000]}"
        )
    return "\n\n".join(parts)


def fetch_sent(alias: str, max_results: int = 50) -> list[str]:
    """Bodies of recently sent emails — used to learn the owner's voice."""
    svc = service_for(alias)
    resp = svc.users().messages().list(
        userId="me", q="in:sent -to:me", maxResults=max_results
    ).execute()
    bodies = []
    for ref in resp.get("messages", []):
        msg = svc.users().messages().get(userId="me", id=ref["id"], format="full").execute()
        headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
        text = _extract_text(msg["payload"])[:1500]
        if text.strip():
            bodies.append(f"Subject: {headers.get('subject', '')}\n{text}")
    return bodies


_labels: dict = {}


def ensure_label(alias: str, name: str) -> str:
    """Get-or-create a Gmail label, cached."""
    key = (alias, name)
    if key not in _labels:
        svc = service_for(alias)
        existing = {
            lb["name"]: lb["id"]
            for lb in svc.users().labels().list(userId="me").execute().get("labels", [])
        }
        if name in existing:
            _labels[key] = existing[name]
        else:
            _labels[key] = svc.users().labels().create(
                userId="me", body={"name": name}
            ).execute()["id"]
    return _labels[key]


def add_label(alias: str, message_id: str, label_name: str) -> None:
    service_for(alias).users().messages().modify(
        userId="me", id=message_id,
        body={"addLabelIds": [ensure_label(alias, label_name)]},
    ).execute()


def fetch_recent(alias: str, days: int, max_results: int = 200) -> list[dict]:
    """Recent inbox messages (metadata + short body) for bucket backfill."""
    svc = service_for(alias)
    out, token = [], None
    while len(out) < max_results:
        resp = svc.users().messages().list(
            userId="me", q=f"in:inbox newer_than:{days}d",
            maxResults=min(100, max_results - len(out)), pageToken=token,
        ).execute()
        for ref in resp.get("messages", []):
            msg = svc.users().messages().get(userId="me", id=ref["id"], format="full").execute()
            headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
            out.append({
                "id": msg["id"], "threadId": msg["threadId"],
                "from": headers.get("from", ""), "subject": headers.get("subject", ""),
                "date": headers.get("date", ""),
                "body": _extract_text(msg["payload"])[:1500],
            })
        token = resp.get("nextPageToken")
        if not token:
            break
    return out


def _extract_attachments(payload: dict) -> list[dict]:
    out = []
    if payload.get("filename") and payload.get("body", {}).get("attachmentId"):
        out.append({
            "filename": payload["filename"],
            "attachment_id": payload["body"]["attachmentId"],
            "mime": payload.get("mimeType", ""),
        })
    for part in payload.get("parts", []) or []:
        out.extend(_extract_attachments(part))
    return out


def fetch_with_attachments(alias: str, days: int, max_results: int = 150) -> list[dict]:
    """Messages with attachments (PDF/Office docs) for the document sweep."""
    svc = service_for(alias)
    out, token = [], None
    q = f"has:attachment newer_than:{days}d"
    while len(out) < max_results:
        resp = svc.users().messages().list(
            userId="me", q=q, maxResults=min(100, max_results - len(out)),
            pageToken=token,
        ).execute()
        for ref in resp.get("messages", []):
            msg = svc.users().messages().get(userId="me", id=ref["id"], format="full").execute()
            headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
            atts = [a for a in _extract_attachments(msg["payload"])
                    if a["filename"].lower().endswith(
                        (".pdf", ".xlsx", ".xls", ".docx", ".csv"))]
            if atts:
                out.append({
                    "id": msg["id"], "threadId": msg["threadId"],
                    "from": headers.get("from", ""), "subject": headers.get("subject", ""),
                    "date": headers.get("date", ""),
                    "snippet": msg.get("snippet", ""), "attachments": atts,
                })
        token = resp.get("nextPageToken")
        if not token:
            break
    return out


def download_attachment(alias: str, message_id: str, attachment_id: str) -> bytes:
    att = service_for(alias).users().messages().attachments().get(
        userId="me", messageId=message_id, id=attachment_id
    ).execute()
    return base64.urlsafe_b64decode(att["data"])


def mark_read(alias: str, message_id: str) -> None:
    service_for(alias).users().messages().modify(
        userId="me", id=message_id, body={"removeLabelIds": ["UNREAD"]}
    ).execute()


def create_draft(alias: str, to: str, subject: str, body: str, thread_id: str | None = None) -> str:
    msg = _mime(to, subject, body)
    draft_body = {"message": {"raw": msg}}
    if thread_id:
        draft_body["message"]["threadId"] = thread_id
    draft = service_for(alias).users().drafts().create(userId="me", body=draft_body).execute()
    return draft["id"]


def send_email(alias: str, to: str, subject: str, body: str, thread_id: str | None = None) -> str:
    payload = {"raw": _mime(to, subject, body)}
    if thread_id:
        payload["threadId"] = thread_id
    sent = service_for(alias).users().messages().send(userId="me", body=payload).execute()
    return sent["id"]


def _mime(to: str, subject: str, body: str) -> str:
    msg = EmailMessage()
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()
