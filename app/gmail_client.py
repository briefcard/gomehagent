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
]

_services: dict = {}


def service_for(alias: str):
    """Build (and cache) a Gmail API client for one inbox alias."""
    if alias in _services:
        return _services[alias]
    acct = config.GMAIL_ACCOUNTS[alias]
    creds = Credentials(
        token=None,
        refresh_token=acct["refresh_token"],
        client_id=config.GOOGLE_CLIENT_ID,
        client_secret=config.GOOGLE_CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )
    creds.refresh(Request())
    _services[alias] = build("gmail", "v1", credentials=creds, cache_discovery=False)
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
