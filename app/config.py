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
    "order_issue": "SERIOUS order problems: wrong/defective/damaged items, "
                   "refund demands, angry or emotional complaints, anything big",
    "order_basic": "Easily-handled order requests: subscription cancellation "
                   "requests, basic asks missing key info (no order number, no "
                   "email match) where the right reply is a clarifying question "
                   "or receipt acknowledgment",
    "order_routine": "Routine order questions answerable from Shopify data: "
                     "status, tracking, delivery estimate, address confirmation",
    "logistics": "Freight forwarders, customs brokers, warehouse, shipments, "
                 "quotes, RFQs, arrival notices, shipping documents",
    "client_comms": "Saias Consulting client work: deliverables, feedback, "
                    "scheduling, project communication",
    "sales_leads": "New business: wholesale inquiries, partnerships, B2B leads, "
                   "press, anyone who could become revenue",
    "sales_orders": "Order activity from OUR OWN stores: Shopify/merchant "
                    "notifications like 'You have a new order', fulfillment "
                    "confirmations, payout notices — operationally important, "
                    "never mere noise",
    "receipts": "Business expense receipts/paid invoices for software, "
                "services, suppliers (Anthropic, Render, Google, Canva, "
                "Shopify bills...) — tracked for taxes",
    "subscriptions": "Software/service lifecycle: upcoming renewals, price "
                     "increases, trial endings, plan changes — anything that "
                     "WILL charge soon",
    "notifications": "Automated platform notifications needing no reply and "
                     "carrying no money info (logins, system alerts, social)",
    "promo": "Newsletters, marketing blasts, cold outreach spam",
}

# Gmail label shown in the inbox for each bucket
BUCKET_LABELS = {
    "urgent_money": "Agent/1-Money-Urgent",
    "order_issue": "Agent/2-Order-Issues",
    "order_basic": "Agent/2-Order-Basic",
    "order_routine": "Agent/3-Order-Routine",
    "logistics": "Agent/4-Logistics",
    "client_comms": "Agent/5-Clients",
    "sales_leads": "Agent/6-Leads",
    "sales_orders": "Agent/0-Orders",
    "receipts": "Agent/7-Receipts",
    "subscriptions": "Agent/7-Subscriptions",
    "notifications": "Agent/8-Notifications",
    "promo": "Agent/9-Promo",
}

# Buckets where auto-send is permitted once AUTO_SEND_ENABLED=true.
# order_routine is tool-verified (Shopify); order_basic replies are
# clarifying questions / acknowledgments that commit to nothing.
AUTO_SEND_BUCKETS = set(
    os.environ.get("AUTO_SEND_BUCKETS", "order_routine,order_basic").split(",")
)

# Per-bucket model routing: logistics runs on Opus for maximum judgment
# (documents, customs, money on the line). Everything else uses CLAUDE_MODEL.
BUCKET_MODELS = json.loads(os.environ.get(
    "BUCKET_MODELS_JSON", '{"logistics": "claude-opus-4-8"}'
))

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

# ---------------- Baci Backoffice (inbound-logistics API) ----------------
# The rep/backoffice PWA (repo briefcard/baci-backoffice) is the source of truth
# for inbound shipments + their customs/freight documents. This agent logs
# shipments/docs there over the agent API. BACI_AGENT_TOKEN must equal the
# AGENT_API_TOKEN set on that service. Unset = the logistics tools stay disabled.
BACI_BACKOFFICE_URL = os.environ.get("BACI_BACKOFFICE_URL", "https://baci-backoffice.onrender.com")
BACI_AGENT_TOKEN = os.environ.get("BACI_AGENT_TOKEN", "")

# ---------------- SEO agent (role: seo) ----------------
# Semrush Analytics API key (Semrush -> Subscription -> API). The deployed agent
# calls api.semrush.com natively, the same pattern as Shopify/Gmail.
SEMRUSH_API_KEY = os.environ.get("SEMRUSH_API_KEY", "")
# First target property + market for the SEO agent. Baci Milano USA.
SEO_DOMAIN = os.environ.get("SEO_DOMAIN", "bacimilanousa.com")
SEO_DATABASE = os.environ.get("SEO_DATABASE", "us")  # Semrush regional database
# Shopify store key (a key in SHOPIFY_STORES) the SEO agent implements on —
# create collections, rewrite copy, set SEO title/meta tags. Writes are
# approval-gated. Baci Milano USA's store.
SEO_STORE = os.environ.get("SEO_STORE", "baci")
# Compliance guardrail: keyword substrings the opportunity finder must NEVER
# recommend as targets. Baci Milano is an Italian DESIGN brand, mass-manufactured
# — NOT made in Italy, NOT handmade, NOT artisanal — so origin claims ("made in
# Italy") AND handcraft/craftsmanship claims ("handmade", "artisan",
# "craftsmanship") are all off-limits (false claims = legal/advertising risk). We
# still rank for "Italian <product>" (style/design); we never claim Italian
# manufacture or handcraft. Comma-separated, case-insensitive substring match.
SEO_EXCLUDE_TERMS = [t.strip().lower() for t in os.environ.get(
    "SEO_EXCLUDE_TERMS",
    "made in italy,from italy,italian made,made italy,imported from italy,"
    "handmade,hand-made,hand made,handcrafted,hand-crafted,hand crafted,"
    "craftsmanship,artisan,artisanal,hand-painted,handpainted,hand painted"
).split(",") if t.strip()]
# Conversational loop model for the SEO role. Defaults to Opus — the role's
# work (strategy, GSC-vs-Semrush judgment, content quality) rewards the stronger
# model. Override with a cheaper model via SEO_MODEL if cost matters more.
SEO_MODEL = os.environ.get("SEO_MODEL", "claude-opus-4-8")

# ---- SEO multi-site / multi-platform ----
# RECOMMENDED: define EVERY client (the primary included) in SEO_SITES_JSON below
# — one uniform structure. The flat SEO_* vars above (SEO_DOMAIN/SEO_DATABASE/
# SEO_STORE/SEO_PLATFORM/SEO_EXCLUDE_TERMS/SEO_GUARDRAIL/SEO_VOICE) are a FALLBACK
# used only when SEO_PRIMARY_SITE is NOT present in SEO_SITES_JSON (sites._all
# setdefaults the flat-var primary if the JSON doesn't define it).
SEO_PLATFORM = os.environ.get("SEO_PLATFORM", "shopify")  # shopify | wordpress (primary fallback)
SEO_PRIMARY_SITE = os.environ.get("SEO_PRIMARY_SITE", "baci")  # default site key
SEO_VOICE = os.environ.get("SEO_VOICE", "")  # primary fallback brand-voice line
# Primary fallback compliance/brand guardrail (e.g. a health brand: no medical claims).
SEO_GUARDRAIL = os.environ.get("SEO_GUARDRAIL", "")
# Every client profile. Each entry: domain, database (Semrush market), platform
# (shopify|wordpress), creds_key (key in SHOPIFY_STORES / WORDPRESS_SITES), optional
# exclude_terms[], guardrail (compliance rule), voice. GSC/GA4 auto-discover by
# domain. Write guardrail/voice WITHOUT double quotes so the JSON stays valid. E.g.
# {"baci":{"domain":"bacimilanousa.com","platform":"shopify","creds_key":"baci",...},
#  "eien":{"domain":"eienhealth.com","platform":"shopify","creds_key":"eien",...},
#  "mtw":{"domain":"marketingthatworks.co","platform":"wordpress","creds_key":"mtw",...}}
SEO_SITES_JSON = os.environ.get("SEO_SITES_JSON", "{}")
# WordPress credentials per creds_key (Application Passwords — WP user profile):
# {"mtw": {"base_url":"https://marketingthatworks.co","user":"editor","app_password":"xxxx xxxx ..."}}
WORDPRESS_SITES = json.loads(os.environ.get("WORDPRESS_SITES_JSON", "{}"))

# ---- GSC + GA4 (real ranking/click + traffic/conversion truth) ----
# ONE Google account (alias in GMAIL_ACCOUNTS) used for all sites — grant it into
# each client's Search Console + GA4 property. Default: personal. Needs the
# webmasters.readonly + analytics.readonly scopes — re-run scripts/google_oauth.py.
SEO_GOOGLE_ALIAS = os.environ.get("SEO_GOOGLE_ALIAS", "personal")
# GSC property / GA4 property are OPTIONAL overrides — leave blank and the agent
# auto-discovers the one matching each site's domain and saves it in the DB
# (SeoSiteConfig). Set these only to force a specific property for the primary site.
SEO_GSC_SITE = os.environ.get("SEO_GSC_SITE", "")
SEO_GA4_PROPERTY = os.environ.get("SEO_GA4_PROPERTY", "")

# WhatsApp Cloud API (optional — agent falls back to email until these are set)
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_ID = os.environ.get("WHATSAPP_PHONE_ID", "")


def _norm_phone(raw: str) -> str:
    """Accepts '7869237857', '+1 786-923-7857', '17869237857' etc.
    Returns Cloud-API format: country code + number, digits only."""
    digits = "".join(c for c in raw if c.isdigit())
    if len(digits) == 10:  # bare US number -> add country code
        digits = "1" + digits
    return digits


WHATSAPP_APPROVER_NUMBER = _norm_phone(os.environ.get("WHATSAPP_APPROVER_NUMBER", ""))
WHATSAPP_VERIFY_TOKEN = os.environ.get("WHATSAPP_VERIFY_TOKEN", "")

WHATSAPP_ENABLED = bool(WHATSAPP_TOKEN and WHATSAPP_PHONE_ID and WHATSAPP_APPROVER_NUMBER)
