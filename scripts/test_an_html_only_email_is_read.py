"""An email that arrives as HTML only is read, not returned empty.

Found 2026-11-02, answering the Baci inbox: `inbox_thread` returned
`"body": ""` for Daniel Lucas ("Issue with order #2007") and Alissa Kopp
(order #2102). `gmail_client._extract_text` walked the MIME tree for a
`text/plain` part and nothing else. A message sent from an iPhone, Verizon
webmail, Outlook mobile or a web form often carries `text/html` only, so the
reader got "". That one function feeds twelve callers, including triage's
intake (`fetch_new`), the backlog sweep, email search and `inbox_thread`, so
every one of them saw an empty customer email.

What this suite holds:
  * plain text is still preferred when a message has both parts;
  * an HTML-only message (top level and nested in multipart/related) comes
    back as readable text, with paragraphs and <br> kept as line breaks;
  * <style>, <script> and <head> never leak into the text;
  * an attached .txt/.html file is not mistaken for the body;
  * a message with no text part at all is still "".

Sabotage run before commit: the HTML fallback in `_extract_text` was removed
(back to plain-only), and the HTML-only checks went red. Restored.

Run: python3 scripts/test_an_html_only_email_is_read.py
"""
from __future__ import annotations

import base64
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'html.db')}"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import gmail_client  # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


def part(mime: str, text: str, filename: str = "") -> dict:
    data = base64.urlsafe_b64encode(text.encode()).decode()
    return {"mimeType": mime, "filename": filename, "body": {"data": data}}


HTML = ("<html><head><title>x</title><style>p{color:red}</style></head><body>"
        "<div dir='ltr'>Hi,<br>My order #2007 never arrived.</div>"
        "<p>FedEx says it was lost.&nbsp;Can you help?</p>"
        "<script>track()</script></body></html>")

# 1. both parts: plain wins
both = {"mimeType": "multipart/alternative", "parts": [
    part("text/plain", "PLAIN BODY"), part("text/html", "<p>HTML BODY</p>")]}
check("plain text is preferred when both parts exist",
      gmail_client._extract_text(both) == "PLAIN BODY",
      repr(gmail_client._extract_text(both)))

# 2. HTML only, at the top level
top = part("text/html", HTML)
got = gmail_client._extract_text(top)
check("an HTML-only message is read", "never arrived" in got and "FedEx says" in got, repr(got))
check("<br> and <p> become line breaks",
      "Hi,\nMy order #2007 never arrived." in got, repr(got))
check("style, script and head do not leak",
      not any(s in got for s in ("color:red", "track()", "<", "x\n")), repr(got))
check("&nbsp; becomes a plain space", "lost. Can you help?" in got, repr(got))

# 3. HTML only, nested (iPhone: multipart/related -> html + inline images)
nested = {"mimeType": "multipart/mixed", "parts": [
    {"mimeType": "multipart/related", "parts": [
        part("text/html", "<div>Photos attached of the broken cup.</div>"),
        {"mimeType": "image/jpeg", "filename": "image0.jpeg",
         "body": {"attachmentId": "a1"}}]}]}
check("a nested HTML-only message is read",
      gmail_client._extract_text(nested) == "Photos attached of the broken cup.",
      repr(gmail_client._extract_text(nested)))

# 4. an attached text file is not the body
attached = {"mimeType": "multipart/mixed", "parts": [
    part("text/plain", "ATTACHED FILE", filename="notes.txt"),
    part("text/html", "<p>The real message.</p>")]}
check("an attached .txt is not mistaken for the body",
      gmail_client._extract_text(attached) == "The real message.",
      repr(gmail_client._extract_text(attached)))

# 5. nothing to read
empty = {"mimeType": "multipart/mixed", "parts": [
    {"mimeType": "image/jpeg", "filename": "a.jpg", "body": {"attachmentId": "z"}}]}
check("a message with no text part is still empty",
      gmail_client._extract_text(empty) == "", repr(gmail_client._extract_text(empty)))

print(f"\n{'ALL PASS' if not FAILS else f'{len(FAILS)} FAILED: ' + ', '.join(FAILS)}")
sys.exit(1 if FAILS else 0)
