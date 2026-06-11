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

# ---------------- Buckets ----------------
# Every email is classified into exactly one bucket. The bucket drives:
# Gmail label, auto-send eligibility, notification urgency, deadline tracking.
BUCKETS = {
    "urgent_money": "Costs money NOW or soon: late fees, penalties, demurrage, "
                    "chargebacks, payment disputes, failed payments, invoices due, "
                    "tax/government notices, service suspension warnings",
    "order_issue": "Customer order problems: cancellation requests, refunds, "
                   "damaged/wrong items, complaints, anything unclear or emotional",
    "order_routine": "Routine order questions answerable from Shopify data: "
                     "status, tracking, delivery estimate, address confirmation",
    "logistics": "Freight forwarders, customs brokers, warehouse, shipments, "
                 "quotes, RFQs, arrival notices, shipping documents",
    "client_comms": "Saias Consulting client work: deliverables, feedback, "
                    "scheduling, project communication",
    "sales_leads": "New business: wholesale inquiries, partnerships, B2B leads, "
                   "press, anyone who could become revenue",
    "subscriptions": "Software/services: renewal notices, price increases, "
                     "receipts, trial endings, plan changes",
    "notifications": "Automated platform notifications needing no reply "
                     "(Shopify, Google, banks, carriers)",
    "promo": "Newsletters, marketing blasts, cold outreach spam",
}

# Gmail label shown in the inbox for each bucket
BUCKET_LABELS = {
    "urgent_money": "Agent/1-Money-Urgent",
    "order_issue": "Agent/2-Order-Issues",
    "order_routine": "Agent/3-Order-Routine",
    "logistics": "Agent/4-Logistics",
    "client_comms": "Agent/5-Clients",
    "sales_leads": "Agent/6-Leads",
    "subscriptions": "Agent/7-Subscriptions",
    "notifications": "Agent/8-Notifications",
    "promo": "Agent/9-Promo",
}

# Buckets where auto-send is permitted once AUTO_SEND_ENABLED=true.
# order_routine drafts are tool-verified (Shopify) so they're the safe start.
AUTO_SEND_BUCKETS = set(
    os.environ.get("AUTO_SEND_BUCKETS", "order_routine").split(",")
)

# Cheap model for backfill classification (no drafting, label-only)
CLASSIFY_MODEL = os.environ.get("CLASSIFY_MODEL", "claude-haiku-4-5-20251001")
BUCKET_BACKFILL_DAYS = int(os.environ.get("BUCKET_BACKFILL_DAYS", "30"))

POLL_INTERVAL_MIN = int(os.environ.get("POLL_INTERVAL_MIN", "5"))
DIGEST_HOURS = (8, 20)  # 8am and 8pm America/New_York

# Training-wheels mode: while false, NOTHING is auto-sent — every reply
# (even to trusted contacts) is drafted and queued for approval in batches.
AUTO_SEND_ENABLED = os.environ.get("AUTO_SEND_ENABLED", "false").lower() == "true"

# On worker startup, sweep this many days back for emails that never got a
# reply and queue drafts for them as the first approval batch.
BACKLOG_DAYS = int(os.environ.get("BACKLOG_DAYS", "14"))

# How often to email Gomeh the pending-approvals batch (escalations are
# always immediate). Drafts accumulate quietly between batches.
APPROVAL_BATCH_MINUTES = int(os.environ.get("APPROVAL_BATCH_MINUTES", "30"))

# Shopify Admin API access, one entry per store:
# {"baci": {"domain": "xxx.myshopify.com", "token": "shpat_..."},
#  "eien": {"domain": "yyy.myshopify.com", "token": "shpat_..."}}
SHOPIFY_STORES = json.loads(os.environ.get("SHOPIFY_STORES_JSON", "{}"))

# How many prior messages of a thread to give Claude as context.
THREAD_CONTEXT_MESSAGES = int(os.environ.get("THREAD_CONTEXT_MESSAGES", "5"))

# WhatsApp Cloud API (optional — agent falls back to email until these are set)
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_ID = os.environ.get("WHATSAPP_PHONE_ID", "")
WHATSAPP_APPROVER_NUMBER = os.environ.get("WHATSAPP_APPROVER_NUMBER", "")
WHATSAPP_VERIFY_TOKEN = os.environ.get("WHATSAPP_VERIFY_TOKEN", "")

WHATSAPP_ENABLED = bool(WHATSAPP_TOKEN and WHATSAPP_PHONE_ID and WHATSAPP_APPROVER_NUMBER)
