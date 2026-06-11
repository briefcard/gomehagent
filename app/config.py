"""Central configuration — everything comes from environment variables."""
import json
import os

from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///local.db")
# Render gives postgres://, SQLAlchemy wants postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")

# JSON map of inbox alias -> {"email": ..., "refresh_token": ...}
# e.g. {"personal": {...}, "baci": {...}, "eien": {...}}
GMAIL_ACCOUNTS = json.loads(os.environ.get("GMAIL_ACCOUNTS_JSON", "{}"))

APPROVER_EMAIL = os.environ.get("APPROVER_EMAIL", "gomehsaias@gmail.com")
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000")
APPROVAL_SECRET = os.environ.get("APPROVAL_SECRET", "dev-secret-change-me")

# Which inbox sends agent notifications/digests (alias key in GMAIL_ACCOUNTS)
NOTIFY_FROM_ALIAS = os.environ.get("NOTIFY_FROM_ALIAS", "personal")

POLL_INTERVAL_MIN = int(os.environ.get("POLL_INTERVAL_MIN", "5"))
DIGEST_HOURS = (8, 20)  # 8am and 8pm America/New_York

# Training-wheels mode: while false, NOTHING is auto-sent — every reply
# (even to trusted contacts) is drafted and queued for approval in batches.
AUTO_SEND_ENABLED = os.environ.get("AUTO_SEND_ENABLED", "false").lower() == "true"

# On worker startup, sweep this many days back for emails that never got a
# reply and queue drafts for them as the first approval batch.
BACKLOG_DAYS = int(os.environ.get("BACKLOG_DAYS", "14"))

# WhatsApp Cloud API (optional — agent falls back to email until these are set)
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_ID = os.environ.get("WHATSAPP_PHONE_ID", "")
WHATSAPP_APPROVER_NUMBER = os.environ.get("WHATSAPP_APPROVER_NUMBER", "")
WHATSAPP_VERIFY_TOKEN = os.environ.get("WHATSAPP_VERIFY_TOKEN", "")

WHATSAPP_ENABLED = bool(WHATSAPP_TOKEN and WHATSAPP_PHONE_ID and WHATSAPP_APPROVER_NUMBER)
