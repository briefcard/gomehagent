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

# Meta app credentials, for the Ads connector. Same pair as Google: the app is
# ours and one registration serves every client, so a new account connects by
# signing in rather than by anyone creating anything.
META_APP_ID = os.environ.get("META_APP_ID", "")
META_APP_SECRET = os.environ.get("META_APP_SECRET", "")
# Canva Connect. Create the integration at canva.com/developers, and register
# the redirect URI the console prints -- it must match byte for byte.
# Shopify OAuth — for onboarding CLIENT stores without each owner hand-making a
# custom app. Distinct from SHOPIFY_STORES_JSON, which holds tokens pasted for
# our own stores; both paths coexist and `credentials.resolve` prefers the
# client's own connection.
SHOPIFY_CLIENT_ID = os.environ.get("SHOPIFY_CLIENT_ID", "")
SHOPIFY_CLIENT_SECRET = os.environ.get("SHOPIFY_CLIENT_SECRET", "")
CANVA_CLIENT_ID = os.environ.get("CANVA_CLIENT_ID", "")
CANVA_CLIENT_SECRET = os.environ.get("CANVA_CLIENT_SECRET", "")
# Canva's own MCP server — the adopted transport (ARCHITECTURE.md): called by
# OUR adapter, never wired into a model loop. Empty disables the MCP path and
# the adapter stays on REST.
CANVA_MCP_URL = os.environ.get("CANVA_MCP_URL", "https://mcp.canva.com/mcp")
CANVA_MCP = os.environ.get("CANVA_MCP", "")   # "1" prefers MCP where mapped
CONSTANT_CONTACT_CLIENT_ID = os.environ.get("CONSTANT_CONTACT_CLIENT_ID", "")
CONSTANT_CONTACT_CLIENT_SECRET = os.environ.get("CONSTANT_CONTACT_CLIENT_SECRET", "")

# How many sent threads one nightly backfill window reads. A mailbox holds
# years and a request holds seconds, so history is walked on a schedule — a few
# hundred a night rather than a few dozen per run, and without one job holding
# the Gmail quota for an hour.
MAIL_BACKFILL_THREADS = int(os.environ.get("MAIL_BACKFILL_THREADS", "250"))

# Output ceiling for one page of claim extraction. Sized to the response
# SCHEMA, not to a round number: each claim now carries text, evidence,
# proof_type, situations, context and proves, so it costs roughly twice what it
# did when this was 2000 — a cap that quietly fitted about five claims a page.
EXTRACT_MAX_TOKENS = int(os.environ.get("EXTRACT_MAX_TOKENS", "8000"))

# JSON map of inbox alias -> {"email": ..., "refresh_token": ...}
# e.g. {"personal": {...}, "baci": {...}, "eien": {...}}
GMAIL_ACCOUNTS = json.loads(os.environ.get("GMAIL_ACCOUNTS_JSON", "{}"))

APPROVER_EMAIL = os.environ.get("APPROVER_EMAIL", "gomehsaias@gmail.com")
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000")
APPROVAL_SECRET = os.environ.get("APPROVAL_SECRET", "dev-secret-change-me")

# A credential that reads and cannot write. APPROVAL_SECRET is not one: several
# console routes still mutate on a GET (/admin/seed_kb, /admin/kb_add,
# /admin/harvest, /admin/tenant_scope), so handing it to a consumer that only
# needs context hands over write access to the knowledge base.
#
# NO DEFAULT, deliberately. Unset means read-only access is disabled rather
# than protected by a guessable string — `_matches` refuses an empty expected
# value, so this fails closed rather than open.
READ_KEY = os.environ.get("READ_KEY", "")

# Embeddings. The same key `whatsapp.transcribe` already needs for voice notes,
# so one variable covers both. Unset means the semantic path is unavailable and
# the classifier falls back to word overlap — which it will SAY, because a
# silent fallback that looks like a working one is how the extractor ran at 0%
# recall for weeks.
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

# text-embedding-3 supports shortening at request time. 512 is a third of the
# storage and compute of the full 1536 for a quality difference that does not
# show up at this corpus size.
EMBED_MODEL = os.environ.get("EMBED_MODEL", "text-embedding-3-small")
EMBED_DIMS = int(os.environ.get("EMBED_DIMS", "512"))

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
# The nightly correlation sweep. Cheap on purpose and separate from
# CLASSIFY_MODEL so one can be changed without the other: the sweep does not
# route anything, it only puts words around numbers that were already computed.
# Nothing it writes is sent anywhere — it lands in a digest a person reads.
SWEEP_MODEL = os.environ.get("SWEEP_MODEL", "claude-haiku-4-5-20251001")

# Judging a generated picture against the brief it was made to. Vision, and
# not the cheap classifier: the question is "is this about the right thing",
# which is the whole reason the check exists. Sonnet by default; overridable
# because the frontier moves and this is the one call whose model choice
# somebody will want to change without a deploy.
CREATIVE_REVIEW_MODEL = os.environ.get("CREATIVE_REVIEW_MODEL",
                                       "claude-sonnet-4-6")
# THE PICTURE GENERATOR. Every text model on this platform has been
# overridable for months — CLAUDE_MODEL, CLASSIFY_MODEL, SWEEP_MODEL,
# SEO_MODEL, CREATIVE_REVIEW_MODEL — and the one call the owner is actually
# unhappy with was the only one hardcoded, so comparing it against anything
# else needed a deploy. The reviewer's row above already argues this exact
# case: "the frontier moves and this is the one call whose model choice
# somebody will want to change without a deploy." It is truer of the
# generator than of the judge.
IMAGE_MODEL = os.environ.get("IMAGE_MODEL", "gpt-image-1")
# The endpoint the generator talks to. A row, not an abstraction: swapping to
# a provider with a different request shape needs more than a URL, and
# pretending otherwise would be a seam that fails at the first real use.
IMAGE_API_BASE = os.environ.get("IMAGE_API_BASE", "https://api.openai.com/v1")
# THE SECOND IMAGE PROVIDER, for the bake-off. Exact reproduction of a
# specific object is a provider capability (bakeoff.py); Google's image
# models take reference images of objects "with high fidelity" (docs read
# 2026-09-08). A model named `gemini:<model>` anywhere a model is named —
# IMAGE_MODEL, `bakeoff.py --models` — goes to `gemini_images` instead of
# the OpenAI-compatible endpoint above. Unset key = that route refuses by
# name; nothing else changes.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_API_BASE = os.environ.get("GEMINI_API_BASE",
                                 "https://generativelanguage.googleapis.com/v1beta")

SWEEP_HOUR = int(os.environ.get("SWEEP_HOUR", "20"))
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

# Omnisend requires a dated API version header on every call (`Omnisend-Version`).
# Its absence is a 400 "Omnisend-Version: required" — the first live call. Its
# FORMAT is a full date, YYYY-MM-DD — the second live call: "2024-06" came back
# 400 "Omnisend-Version: invalid_format" on the Eien segments probe
# (2026-08-21). The default is the one version the API reference documents
# (api-docs.omnisend.com/reference/overview). Overridable so a version bump is
# an env change, not a code deploy.
OMNISEND_API_VERSION = os.environ.get("OMNISEND_API_VERSION", "2026-03-15")

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
#: THE BILL IS PER LINE, AND THESE ARE THE CEILINGS. Semrush charges every
#: line a report returns, at a price that depends on the report
#: (`seo_tools.UNIT_PRICE`: related keywords and questions cost four times a
#: domain report). One key serves every account, so the ceilings are rolling
#: seven-day totals read from the ledger: one for the whole service, one per
#: account (overridable per tenant in `Tenant.analytics["semrush_weekly_cap"]`),
#: and one per agent turn so a chat cannot spend a harvest. Enforced in
#: `seo_tools._semrush`, the one door every Semrush read goes through.
#:
#: The account default sits just above ONE full harvest (28,000) so the
#: Plan tab's button still works once a week and a second click the same
#: week is refused by name. Both come down once expansion is cached and
#: budgeted (the 2026-09-07 audit's Phase 2), when a harvest costs a
#: third of this.
SEMRUSH_WEEKLY_CAP = int(os.environ.get("SEMRUSH_WEEKLY_CAP", "60000"))
SEMRUSH_ACCOUNT_WEEKLY_CAP = int(os.environ.get("SEMRUSH_ACCOUNT_WEEKLY_CAP", "30000"))
SEMRUSH_TURN_CAP = int(os.environ.get("SEMRUSH_TURN_CAP", "3000"))
#: Below this many remaining units the daily balance reading tells the owner.
SEMRUSH_LOW_BALANCE = int(os.environ.get("SEMRUSH_LOW_BALANCE", "20000"))
#: How long a bought answer stays reusable. The related keywords and questions
#: around a phrase are the two reports Semrush charges 40 units a line for and
#: will not batch, and they move over months — so re-asking inside this window
#: buys an answer we already have. Sixty is the conservative end; the owner may
#: raise it to ninety, which is closer to how slowly a question set turns over.
SEMRUSH_EXPANSION_TTL_DAYS = int(os.environ.get("SEMRUSH_EXPANSION_TTL_DAYS", "60"))
#: The fewest monthly searches a phrase must have to be worth buying. Applied
#: server-side on the expansions, where the tail is long and nothing at the end
#: of it is ever written.
SEMRUSH_MIN_VOLUME = int(os.environ.get("SEMRUSH_MIN_VOLUME", "10"))
#: New seeds one weekly harvest may expand. A seed already expanded inside the
#: TTL costs nothing, so this bounds only what is genuinely new — the
#: difference between a map that deepens every week and a bill that repeats.
SEMRUSH_NEW_SEEDS_PER_RUN = int(os.environ.get("SEMRUSH_NEW_SEEDS_PER_RUN", "3"))
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

# --- Telegram: the ops channel (Aug 2026) -----------------------------------
# Preferred over WhatsApp for blocked-pipeline pings and approvals: no 24-hour
# window, no template review, real inline buttons, and editable messages.
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
# Verifies the X-Telegram-Bot-Api-Secret-Token header on every inbound update.
TELEGRAM_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")


def _chat_ids(raw: str, primary: str) -> set[str]:
    """Allowlist of chat ids permitted to command the bot. Fails CLOSED: with
    nothing configured only the approver's own chat is authorised, because this
    bot can write to the knowledge base and bot usernames are discoverable."""
    ids = {c.strip() for c in raw.split(",") if c.strip()}
    if primary:
        ids.add(primary.strip())
    return ids


TELEGRAM_ALLOWED_CHAT_IDS = _chat_ids(
    os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS", ""), TELEGRAM_CHAT_ID)

TELEGRAM_ENABLED = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)
