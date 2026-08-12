"""Database models. Postgres on Render, SQLite locally."""
import datetime as dt
import uuid

from sqlalchemy import (JSON, Column, DateTime, String, Text, UniqueConstraint,
                        create_engine)
from sqlalchemy.orm import declarative_base, sessionmaker

from . import config

engine = create_engine(config.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

# A row whose client could not be determined. Deliberately NOT a synonym for
# "belongs to everyone": an unattributed row is an open question, and treating
# it as shared is how one client's shipment ends up in another client's report.
# `tenant_filter` excludes it unless a caller asks for it by name.
UNASSIGNED = ""


def _uuid() -> str:
    return uuid.uuid4().hex


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def as_utc(value):
    """Normalise a stored datetime to timezone-aware UTC.

    SQLite drops the timezone even on a DateTime(timezone=True) column, while
    Postgres preserves it — so any comparison against utcnow() works in
    production and raises "can't compare offset-naive and offset-aware" the
    moment it runs locally. Always compare through this.
    """
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=dt.timezone.utc)


class Approval(Base):
    """Any action that needs Gomeh's sign-off before execution."""

    __tablename__ = "approvals"

    id = Column(String, primary_key=True, default=_uuid)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    kind = Column(String, nullable=False)  # send_email | buy_label | pay | other
    status = Column(String, default="pending")  # pending | approved | denied | executed | expired
    summary = Column(Text, nullable=False)  # one-line human description
    payload = Column(JSON, nullable=False)  # everything needed to execute on approval
    tenant = Column(String, default="", index=True)  # which client this action belongs to
    # Which pipeline asked, and which run it belongs to. Added while the table
    # is empty; the alternative is retrofitting the join once it has live data.
    system_id = Column(String, default="")
    run_id = Column(String, default="")
    decided_at = Column(DateTime(timezone=True))
    executed_at = Column(DateTime(timezone=True))
    channel = Column(String, default="email")  # email | whatsapp


class EmailLog(Base):
    """Every inbound email seen and what the agent did with it."""

    __tablename__ = "email_log"

    id = Column(String, primary_key=True, default=_uuid)
    tenant = Column(String, default="", index=True)  # derived from `account`
    seen_at = Column(DateTime(timezone=True), default=utcnow)
    account = Column(String, nullable=False)  # alias: personal | baci | eien
    gmail_message_id = Column(String, unique=True, nullable=False)
    thread_id = Column(String)
    sender = Column(String)
    subject = Column(Text)
    category = Column(String)  # forwarder | order | invoice | client | junk | other
    action = Column(String)  # auto_replied | drafted | escalated | ignored
    detail = Column(Text)


class Contact(Base):
    """Known counterparties. 'trusted' contacts qualify for auto-send replies."""

    __tablename__ = "contacts"
    # The same person is often a counterparty for more than one client, with a
    # different role and a different trust level in each. A global unique on
    # email made the second client an IntegrityError.
    __table_args__ = (UniqueConstraint("tenant", "email", name="uq_contact_tenant_email"),)

    id = Column(String, primary_key=True, default=_uuid)
    tenant = Column(String, default="", index=True)  # replaces `entity`
    email = Column(String, nullable=False)
    name = Column(String)
    company = Column(String)
    role = Column(String)  # forwarder | customs_broker | warehouse | client | vendor | other
    entity = Column(String)  # DEPRECATED — superseded by `tenant`; read by nothing
    trusted = Column(String, default="no")  # yes -> routine replies may auto-send


class Deadline(Base):
    """Anything with a date that costs money if missed."""

    __tablename__ = "deadlines"

    id = Column(String, primary_key=True, default=_uuid)
    tenant = Column(String, default="", index=True)  # derived from `account`
    created_at = Column(DateTime(timezone=True), default=utcnow)
    account = Column(String)
    description = Column(Text, nullable=False)  # what's due
    amount = Column(String)  # "$148.50" or "unknown"
    due_date = Column(String)  # YYYY-MM-DD (lexicographic compare works)
    source_subject = Column(Text)
    status = Column(String, default="open")  # open | alerted | done | dismissed


class ChatMessage(Base):
    """Conversation history — one separate thread per agent (and optional
    sub-thread), so each agent keeps its own context with no bleed between them."""

    __tablename__ = "chat_messages"

    id = Column(String, primary_key=True, default=_uuid)
    tenant = Column(String, default="", index=True)  # derived from `thread`
    created_at = Column(DateTime(timezone=True), default=utcnow)
    # Conversation thread: 'admin', 'seo', or a sub-thread like 'seo:eien'.
    # Defaults to 'admin' so all pre-existing history stays on the admin thread.
    thread = Column(String, default="admin", index=True)
    role = Column(String, nullable=False)  # user | assistant
    content = Column(Text, nullable=False)


class Memory(Base):
    """Durable working memory: ongoing tasks, decisions, standing instructions.
    Written by the agent itself; injected into every prompt (chat + triage)."""

    __tablename__ = "memories"

    id = Column(String, primary_key=True, default=_uuid)
    tenant = Column(String, default="", index=True)  # derived from `scope`
    created_at = Column(DateTime(timezone=True), default=utcnow)
    topic = Column(String, nullable=False)  # e.g. 'Turkey shipment', 'standing rule'
    content = Column(Text, nullable=False)
    status = Column(String, default="active")  # active | archived
    # Which agent a note belongs to: 'global' (all agents) or a role name
    # ('admin', 'seo'). Each agent sees global + its own — no cross-agent noise.
    scope = Column(String, default="global", index=True)


class FollowUp(Base):
    """Outbound messages that expect a reply — chased automatically."""

    __tablename__ = "follow_ups"

    id = Column(String, primary_key=True, default=_uuid)
    tenant = Column(String, default="", index=True)  # derived from `account`
    created_at = Column(DateTime(timezone=True), default=utcnow)
    account = Column(String, nullable=False)
    thread_id = Column(String)
    to = Column(String)
    subject = Column(Text)
    due_date = Column(String)  # YYYY-MM-DD
    status = Column(String, default="waiting")  # waiting | chased | closed | escalated


class Shipment(Base):
    """Structured record per import shipment — the spine of logistics."""

    __tablename__ = "shipments"
    # Two clients importing in the same month both want 'Turkey-Mar2026'.
    __table_args__ = (UniqueConstraint("tenant", "name", name="uq_shipment_tenant_name"),)

    id = Column(String, primary_key=True, default=_uuid)
    tenant = Column(String, default="", index=True)  # whose shipment this is
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow)
    name = Column(String, nullable=False)  # e.g. 'Turkey-Mar2026'
    status = Column(String, default="quoting")  # quoting|booked|in_transit|customs|arrived|received|closed
    eta = Column(String)  # YYYY-MM-DD or ''
    counterparty = Column(String)  # forwarder/broker
    docs = Column(JSON, default=dict)  # {'BOL': 'have|missing|link', ...}
    costs = Column(JSON, default=dict)  # {'freight': '...', 'duties': '...'}
    notes = Column(Text, default="")


class RFQ(Base):
    """A request-for-quote round for one shipment, across multiple forwarders."""

    __tablename__ = "rfqs"
    __table_args__ = (UniqueConstraint("tenant", "shipment_name",
                                       name="uq_rfq_tenant_shipment"),)

    id = Column(String, primary_key=True, default=_uuid)
    tenant = Column(String, default="", index=True)  # whose RFQ this is
    created_at = Column(DateTime(timezone=True), default=utcnow)
    shipment_name = Column(String, nullable=False)
    status = Column(String, default="quoting")  # quoting | complete | decided | closed
    details = Column(JSON, default=dict)  # cargo, origin, incoterm, ready date...
    forwarders = Column(JSON, default=list)  # emails the RFQ went to
    quotes = Column(JSON, default=dict)  # {forwarder_email: {total, breakdown, notes, received}}


class Expense(Base):
    """Business expense receipts captured from email — tax-season raw material."""

    __tablename__ = "expenses"

    id = Column(String, primary_key=True, default=_uuid)
    tenant = Column(String, default="", index=True)  # whose P&L this hits
    seen_at = Column(DateTime(timezone=True), default=utcnow)
    account = Column(String)
    vendor = Column(String)
    amount = Column(String)
    expense_date = Column(String)  # YYYY-MM-DD if known
    source_subject = Column(Text)


class DocIndex(Base):
    """Registry of every document the agent files — instant recall by
    counterparty/PO/shipment without relying on Drive search."""

    __tablename__ = "doc_index"

    id = Column(String, primary_key=True, default=_uuid)
    tenant = Column(String, default="", index=True)  # whose document this is
    created_at = Column(DateTime(timezone=True), default=utcnow)
    filename = Column(String, nullable=False)
    path = Column(Text, nullable=False)  # folder path under B2B
    link = Column(Text, default="")
    doc_type = Column(String, default="")  # BOL, commercial invoice, PO...
    anchor = Column(String, default="")  # 'Primorous PO-2241', 'Turkey-Mar2026'
    source = Column(String, default="")  # email | whatsapp | sweep | refile
    content_hash = Column(String, default="", index=True)  # sha256 — dedup across runs


class Usage(Base):
    """Token usage per Claude call — powers cache-hit + cost auditing."""

    __tablename__ = "usage"

    id = Column(String, primary_key=True, default=_uuid)
    tenant = Column(String, default="", index=True)  # per-client cost attribution
    at = Column(DateTime(timezone=True), default=utcnow, index=True)
    purpose = Column(String)  # triage | command | classify | job
    model = Column(String)
    input_tokens = Column(String, default="0")
    output_tokens = Column(String, default="0")
    cache_read = Column(String, default="0")
    cache_write = Column(String, default="0")


class WaMessage(Base):
    """Map WhatsApp message IDs -> their content, so when Gomeh uses the reply
    feature we can show the agent exactly which prior message he quoted."""

    __tablename__ = "wa_messages"

    wamid = Column(String, primary_key=True)
    tenant = Column(String, default="", index=True)  # whose conversation
    at = Column(DateTime(timezone=True), default=utcnow)
    role = Column(String)  # assistant | user
    content = Column(Text)
    approval_id = Column(String, default="")  # set if this was an approval msg


class Lesson(Base):
    """Cross-agent learning. A correction that is GENERALIZABLE (applies
    beyond one inbox/role) is stored here and read by EVERY agent, so a
    mistake one agent makes teaches all of them. Role-specific corrections
    stay as VoiceProfile rules; universal ones become Lessons."""

    __tablename__ = "lessons"

    id = Column(String, primary_key=True, default=_uuid)
    tenant = Column(String, default="", index=True)  # blank = applies to every client
    created_at = Column(DateTime(timezone=True), default=utcnow)
    scope = Column(String, default="global")  # global | <role name>
    lesson = Column(Text, nullable=False)
    origin = Column(String, default="")  # which agent/role learned it
    hits = Column(String, default="0")  # times reinforced


class SystemDoc(Base):
    """The Systems Map — durable, structured knowledge of HOW Gomeh's world is
    organized: Drive folder taxonomies, filing conventions, registries, active
    projects. Agents READ these before organizational work (read-before-write)
    and UPDATE them after, so structure is never re-invented per task."""

    __tablename__ = "system_docs"

    key = Column(String, primary_key=True)  # e.g. 'drive:baci', 'conventions:filing'
    tenant = Column(String, default="", index=True)  # derived from the key prefix
    title = Column(String, default="")
    content = Column(Text, default="")
    pinned = Column(String, default="")  # 'true' -> inject full content every turn
    updated_at = Column(DateTime(timezone=True), default=utcnow)
    updated_by = Column(String, default="")  # role/job that last wrote it


class FeatureRequest(Base):
    """Agent-filed feature requests: when an agent hits a limitation (missing
    tool, a cap that cut results, repeated friction) it records the problem and
    a concrete proposal here instead of silently working around it. Gomeh
    reviews (/admin/features) and ships upgrades in a dev session."""

    __tablename__ = "feature_requests"

    id = Column(String, primary_key=True, default=_uuid)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    role = Column(String, default="")  # which agent filed it
    title = Column(String, nullable=False)
    problem = Column(Text, default="")
    proposal = Column(Text, default="")
    status = Column(String, default="open")  # open | planned | built | rejected
    hits = Column(String, default="1")  # times this friction was re-hit


class SeoSnapshot(Base):
    """Point-in-time SEO snapshot for the self-analysis loop — a baseline plus
    recurring captures so the SEO agent can measure growth/decline per domain
    over time and adjust the plan from real data (never a guess)."""

    __tablename__ = "seo_snapshots"

    id = Column(String, primary_key=True, default=_uuid)
    tenant = Column(String, default="", index=True)  # derived from `domain`
    at = Column(DateTime(timezone=True), default=utcnow, index=True)
    domain = Column(String, nullable=False, index=True)
    database = Column(String, default="us")
    source = Column(String, default="semrush")  # semrush | gsc
    rank = Column(String, default="")            # Semrush authority rank
    organic_keywords = Column(String, default="0")
    organic_traffic = Column(String, default="0")
    organic_cost = Column(String, default="0")
    top_keywords = Column(JSON, default=list)    # [{keyword, position, volume, url, traffic_pct}]
    notes = Column(Text, default="")


class SeoSiteConfig(Base):
    """Resolved Google property mapping per SEO site — discovered ONCE (the GSC
    site URL + GA4 property id that belong to the site's domain) then persisted,
    so the agent never re-discovers and nothing has to be set in env in advance."""

    __tablename__ = "seo_site_config"

    site = Column(String, primary_key=True)   # site profile key (baci, eien, mtw)
    tenant = Column(String, default="", index=True)  # derived from `site` / `domain`
    domain = Column(String, default="")
    gsc_site = Column(String, default="")     # e.g. sc-domain:bacimilanousa.com
    ga4_property = Column(String, default="")  # numeric GA4 property id
    updated_at = Column(DateTime(timezone=True), default=utcnow)


class Setting(Base):
    """Tiny key/value store for run-once markers."""

    __tablename__ = "settings"

    key = Column(String, primary_key=True)
    value = Column(Text)


class VoiceProfile(Base):
    """Per-inbox writing style, distilled from past sent emails."""

    __tablename__ = "voice_profiles"

    alias = Column(String, primary_key=True)  # personal | baci | eien
    tenant = Column(String, default="", index=True)  # derived from `alias`
    rules = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class Tenant(Base):
    """The registry. One row per business, the agency included.

    This is what "switch to Baci" switches TO. Before this table, the wiring
    for a client was scattered across SHOPIFY_STORES_JSON, GMAIL_ACCOUNTS_JSON,
    SEO_SITES_JSON and the KB, with nothing joining them — so there was no
    single answer to "which inbox, store and ad account is this client?".

    Connection columns hold KEYS into the existing credential dicts, never
    secrets. Adding a client is a row here plus its KB rows; never new code.
    """

    __tablename__ = "tenants"

    key = Column(String, primary_key=True)   # agency | baci | eien | coverings | ironside
    name = Column(String, nullable=False)
    kind = Column(String, default="client")  # client | own — 'own' = Gomeh's own P&L
    status = Column(String, default="active")  # active | paused | offboarded
    domain = Column(String)
    timezone = Column(String, default="America/New_York")

    # --- connections: keys into config dicts / vault refs, not credentials ---
    gmail_alias = Column(String)        # key in GMAIL_ACCOUNTS — inbox monitoring
    shopify_store = Column(String)      # key in SHOPIFY_STORES
    cms = Column(JSON, default=dict)    # {platform, creds_key}
    esp = Column(JSON, default=dict)    # {provider, credential_ref, from_name, reply_to}
    ads = Column(JSON, default=dict)    # {meta_account_id, google_customer_id}
    analytics = Column(JSON, default=dict)  # {ga4_property, gsc_site, semrush_db}
    design = Column(JSON, default=dict)     # {canva_brand_id, drive_folder}
    crm = Column(JSON, default=dict)        # {provider, creds_key}

    # --- governance ---
    systems = Column(JSON, default=list)    # which pipelines are switched on
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class User(Base):
    """Who may talk to the system, and on whose behalf.

    Roles: owner sees every tenant and can switch freely; client is pinned to
    one tenant and a narrow surface (reports, approvals); freelancer is pinned
    to one tenant with no reporting access. Scope is enforced server-side from
    this row — never from a parameter the caller supplies.
    """

    __tablename__ = "users"

    id = Column(String, primary_key=True, default=_uuid)
    name = Column(String)
    email = Column(String)
    telegram_chat_id = Column(String, index=True)  # how the ops channel knows them
    role = Column(String, default="client")        # owner | client | freelancer
    tenant_key = Column(String)                    # null for owner = all tenants
    active_tenant = Column(String)                 # current context, per user
    status = Column(String, default="active")
    created_at = Column(DateTime(timezone=True), default=utcnow)


# ---------------------------------------------------------------------------
# Knowledge Base — multi-tenant. Every row carries `tenant`; nothing is ever
# read without one. Customisation lives HERE as data, never as forked code.
# Consumed by the brief assembler (deterministic) and enforced by the
# validator (also deterministic). Models are generated FROM these rows and
# never allowed to assert anything that isn't in them.
# ---------------------------------------------------------------------------

class KbBrand(Base):
    """One row per tenant: who they are, how they sound, what they may not say."""

    __tablename__ = "kb_brand"

    tenant = Column(String, primary_key=True)  # agency | baci | eien | coverings | ironside
    display_name = Column(String, nullable=False)
    positioning = Column(Text)
    elevator = Column(JSON, default=dict)      # {sentence, paragraph, page}
    voice = Column(JSON, default=dict)         # {tone[], do_say[], never_say[], examples[]}
    # Hard compliance boundary. The validator rejects any draft containing one
    # of these strings — see Baci's origin/handcraft rules. Never advisory.
    banned_claims = Column(JSON, default=list)
    approval_policy = Column(JSON, default=dict)  # {auto_publish[], requires_signoff[]}

    # How selection reaches the thing this tenant actually sells. Without it the
    # assembler could only ever look at claims and objections, so a venue
    # enquiry naming a headcount never touched the capacity data sitting one
    # table over. Shape:
    #   {"primary_type": "space",
    #    "modes": [{"mode": "capacity_fit", "requirement": "headcount",
    #               "attributes": {"seated": "seated_capacity",
    #                              "default": "standing_capacity"}}]}
    selection = Column(JSON, default=dict)

    # What to propose at each stage, per tenant. Replaces hardcoded agency offer
    # keys in the decision layer. Shape:
    #   {"first_contact": {"entity_key": "diagnostic", "ask": "the paid diagnostic"}}
    next_steps = Column(JSON, default=dict)

    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class KbClaim(Base):
    """A fact the brand is allowed to assert, with its proof and when to use it.

    `situations` is what makes selection deterministic: the assembler filters
    claims by the prospect's situation rather than letting a model pick a
    flattering number. Every factual sentence a generator writes must cite one
    of these ids, or the validator rejects the draft.
    """

    __tablename__ = "kb_claims"

    id = Column(String, primary_key=True, default=_uuid)
    tenant = Column(String, nullable=False, index=True)
    claim = Column(Text, nullable=False)        # the assertion, in plain words
    evidence = Column(Text)                     # the number: "$6M -> $20M in 18 months"
    proof_type = Column(String)                 # data | case_study | certification | testimonial | spec
    source = Column(Text)                       # where it came from — required for spec claims
    situations = Column(JSON, default=list)     # tags the assembler matches on
    strength = Column(String, default="strong") # strong | supporting — caps how many per asset
    verified_at = Column(DateTime(timezone=True))
    expires_at = Column(DateTime(timezone=True))  # stale claims stop being selectable
    status = Column(String, default="active")   # active | retired | conflicted


class KbAudience(Base):
    """A buyer segment, in their vocabulary rather than yours."""

    __tablename__ = "kb_audiences"

    id = Column(String, primary_key=True, default=_uuid)
    tenant = Column(String, nullable=False, index=True)
    key = Column(String, nullable=False)        # ecom_inventory | b2b_spec | local_venue | digital_products
    name = Column(String, nullable=False)
    pains = Column(JSON, default=list)
    vocabulary = Column(JSON, default=list)     # words THEY use — not your category terms
    buying_trigger = Column(Text)
    decision_timeline = Column(String)
    notes = Column(Text)


class KbObjection(Base):
    """Why a deal stalls, and the approved answer.

    Empty across all four client accounts at audit time. Cannot be machine-
    populated — this is human-authored, and it's half of the paid intake.
    """

    __tablename__ = "kb_objections"

    id = Column(String, primary_key=True, default=_uuid)
    tenant = Column(String, nullable=False, index=True)
    objection = Column(Text, nullable=False)
    response = Column(Text, nullable=False)
    claim_id = Column(String)                   # optional proof to pair with it
    audience_key = Column(String)               # blank = applies to everyone
    escalate = Column(String, default="no")     # yes -> hand to a human, don't answer


class KbSituation(Base):
    """One tenant's diagnostic vocabulary, as data.

    The situation tags were a module constant shared by every tenant, written
    for the agency selling B2B services. A tableware brand's proof had nowhere
    to live in it, and a venue enquiry saying "220 guests seated" matched none
    of its patterns — so nothing was diagnosed and selection had nothing to
    filter on. A shared constant is also exactly the customisation-in-code that
    decision #3 forbids.

    `patterns` is a list of lists: the inner list is a set of substrings that
    must ALL appear for the tag to fire. Roots rather than whole phrases,
    because real people write "raising prices" not "raise prices".
    """

    __tablename__ = "kb_situations"

    id = Column(String, primary_key=True, default=_uuid)
    tenant = Column(String, nullable=False, index=True)
    tag = Column(String, nullable=False)
    kind = Column(String, default="problem")  # who_they_are | problem | doubt
    description = Column(Text)
    patterns = Column(JSON, default=list)


class IntakeLink(Base):
    """A scoped, expiring link that lets a CLIENT fill their own knowledge base.

    Filling a KB is the one job that does not scale by the owner typing faster.
    This is the surface a client gets: one tenant, no secret key, no access to
    anything else, and answers parsed by exactly the same code as the console
    and the bot — so a fact entered by a client and one entered by Gomeh land
    identically. Claims they submit land as `pending` and stay invisible to
    selection until reviewed, because a client will always over-claim.
    """

    __tablename__ = "intake_links"

    token = Column(String, primary_key=True)
    tenant = Column(String, nullable=False, index=True)
    label = Column(String)                 # who it was sent to
    status = Column(String, default="active")   # active | revoked
    answered = Column(String, default="0")      # how many questions they filled
    created_at = Column(DateTime(timezone=True), default=utcnow)
    expires_at = Column(DateTime(timezone=True))
    last_used_at = Column(DateTime(timezone=True))


class Credential(Base):
    """One provider connection for one client, held encrypted.

    Credentials used to live only in Render env-group JSON blobs keyed by name
    — fine while Gomeh created every one of them by hand, and the reason
    onboarding needed him at a keyboard. This is the same value, per tenant,
    written by the client themselves through a scoped connect link.

    `secret` is Fernet ciphertext and is never returned to any surface: the
    console and the connect page render `status` and `last_verified`, never the
    value. A credential that has verified against the live API is self-proving,
    which is why there is no approval queue in front of it.
    """

    __tablename__ = "credentials"
    __table_args__ = (UniqueConstraint("tenant", "provider",
                                       name="uq_credential_tenant_provider"),)

    id = Column(String, primary_key=True, default=_uuid)
    tenant = Column(String, nullable=False, index=True)
    provider = Column(String, nullable=False)   # google | shopify | omnisend | ...
    kind = Column(String, default="api_key")    # api_key | oauth
    secret = Column(Text)                       # Fernet ciphertext — never rendered
    meta = Column(JSON, default=dict)           # non-secret: store domain, from_name…
    scopes = Column(Text, default="")
    status = Column(String, default="active")   # active | failed | revoked
    granted_by = Column(String, default="")     # label from the connect link
    granted_at = Column(DateTime(timezone=True), default=utcnow)
    last_verified = Column(DateTime(timezone=True))
    last_error = Column(Text, default="")


class ConnectLink(Base):
    """A scoped, expiring link that lets a CLIENT connect their own accounts.

    Same shape and same guarantees as `IntakeLink`, for the other half of
    onboarding: one tenant, no admin key, nothing else reachable. Where the
    intake link fills the knowledge base, this one fills `Credential`.
    """

    __tablename__ = "connect_links"

    token = Column(String, primary_key=True)
    tenant = Column(String, nullable=False, index=True)
    label = Column(String)                      # who it was sent to
    status = Column(String, default="active")   # active | revoked
    created_at = Column(DateTime(timezone=True), default=utcnow)
    expires_at = Column(DateTime(timezone=True))
    last_used_at = Column(DateTime(timezone=True))


class KbUnknown(Base):
    """A question the catalogue could not answer, and how often it mattered.

    When selection is asked for 220 seated and a space has no seated capacity
    recorded, the honest answer is "cannot be judged" — but saying that forever
    is a system with no way to learn. Each occurrence is counted here, so the
    gaps that actually cost answers rise to the top and can be filled in one
    reply. Resolving a row writes the value onto the entity and closes it.

    Aggregated by (tenant, entity_key, attribute): one row per real gap, not
    one per enquiry.
    """

    __tablename__ = "kb_unknowns"

    id = Column(String, primary_key=True, default=_uuid)
    tenant = Column(String, nullable=False, index=True)
    entity_key = Column(String, nullable=False)
    entity_name = Column(String)
    attribute = Column(String, nullable=False)   # e.g. seated_capacity
    asked_for = Column(Text)                     # what was being matched, verbatim
    hits = Column(String, default="1")           # how often this gap blocked an answer
    status = Column(String, default="open")      # open | answered | not_applicable
    answer = Column(Text)
    first_seen = Column(DateTime(timezone=True), default=utcnow)
    last_seen = Column(DateTime(timezone=True), default=utcnow)


class KbEntity(Base):
    """The polymorphic thing being sold.

    One table absorbs agency offers, Baci products, Ironside spaces and
    Coverings slabs. `attributes` is the typed bag; `source`/`verified_at`
    exist because B2B spec sales needs provenance (a wrong dimension loses
    the job) even though the other tenants never populate them.
    """

    __tablename__ = "kb_entities"

    id = Column(String, primary_key=True, default=_uuid)
    tenant = Column(String, nullable=False, index=True)
    type = Column(String, nullable=False)       # offer | product | space | service | program
    key = Column(String, nullable=False)        # stable slug / SKU
    name = Column(String, nullable=False)
    description = Column(Text)
    attributes = Column(JSON, default=dict)     # capacity, material, seats, deliverables...
    price = Column(String)                      # string: ranges and "from $X" are common
    availability = Column(String, default="available")  # available | oos | unbookable | draft
    source = Column(String)                     # where the attribute data came from
    verified_at = Column(DateTime(timezone=True))
    freshness_days = Column(String)             # past this, the assembler blocks rather than warns
    status = Column(String, default="active")


# ---------------------------------------------------------------------------
# Systems — an installed pipeline for one tenant, and the ledger of what it did.
#
# Before this, a "system" was a string in Tenant.systems: a label with no state,
# no contract, no owner and no history. There was no way to ask whether a system
# was safe to switch on, what it had produced, or whether it was working — which
# is the question the whole platform exists to answer.
# ---------------------------------------------------------------------------

class System(Base):
    """One pipeline installed for one tenant.

    Carries the 8-part contract as columns rather than prose, because the rule
    is that a system without one doesn't get built — and a rule that can't be
    evaluated isn't enforced. `ready()` in systems.py is that evaluation.

    `autonomy` is the earned ladder as a state machine: shadow -> approve_all
    -> approve_exceptions -> auto. Nothing starts autonomous, and promotion is
    an explicit act with the run history sitting next to the button.
    """

    __tablename__ = "systems"

    id = Column(String, primary_key=True, default=_uuid)
    tenant = Column(String, nullable=False, index=True)
    key = Column(String, nullable=False)      # lead_responder | campaign_email | ...
    name = Column(String, nullable=False)

    status = Column(String, default="designed")   # designed | live | paused | retired
    autonomy = Column(String, default="shadow")   # shadow | approve_all | approve_exceptions | auto

    # --- the 8-part contract (locked decision #8) ---
    job_replaced = Column(Text)      # the human task this removes
    owner = Column(String)           # who is accountable when it misbehaves
    baseline = Column(Text)          # the number before it existed
    primary_metric = Column(Text)    # the one number that says it works
    counterfactual = Column(Text)    # how we'd know it wasn't just seasonality
    kill_criteria = Column(Text)     # what makes us switch it off
    failure_mode = Column(Text)      # how it breaks, and who notices
    weekly_artifact = Column(Text)   # what lands in the client's inbox on Friday

    config = Column(JSON, default=dict)
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    went_live_at = Column(DateTime(timezone=True))


class SystemRun(Base):
    """One execution. The ledger that makes 'is it working?' a query.

    Blocked runs are recorded, not discarded: `blocked_on` is the named missing
    field the pipeline refused on. A month of those is the KB backlog, sorted by
    how often each gap actually cost an output.

    `edit_diff` is the highest-value column here — what a human changed before
    approving is the only honest signal of where the generator is wrong, and it
    is what the voice layer learns from.
    """

    __tablename__ = "system_runs"

    id = Column(String, primary_key=True, default=_uuid)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    system_id = Column(String, nullable=False, index=True)
    tenant = Column(String, nullable=False, index=True)  # denormalised: per-client queries stay cheap

    trigger = Column(String)          # inbound_email | schedule | manual
    ref = Column(String)              # source identifier, e.g. a gmail message id
    stage = Column(String, default="brief")  # brief | draft | validated | approved | sent | blocked | failed
    blocked_on = Column(JSON, default=list)  # named missing fields — refuse-don't-invent, recorded

    brief = Column(JSON, default=dict)
    output = Column(Text)
    approval_id = Column(String)
    decision = Column(String)         # approved | denied | edited | auto
    edit_diff = Column(Text)
    outcome = Column(JSON, default=dict)   # measured after the fact
    error = Column(Text)
    finished_at = Column(DateTime(timezone=True))


def tenant_filter(model, tenant: str, include_unassigned: bool = False):
    """The scope clause for a per-client query.

    One place decides what "belongs to this client" means, so a call site cannot
    quietly get it wrong. Unassigned rows are EXCLUDED by default: a row whose
    client was never determined is an open question, and folding it into whoever
    happens to be asking is exactly how one client's data reaches another.
    Callers that genuinely want the backlog pass `include_unassigned=True`.
    """
    col = model.tenant
    if include_unassigned:
        return col.in_([tenant, UNASSIGNED])
    return col == tenant


# Uniqueness that used to be global and is now per client. Each entry is
# (table, old single column) -> the composite that replaces it.
_REGRADED_UNIQUES = (
    ("contacts", "email", "uq_contact_tenant_email", ("tenant", "email")),
    ("shipments", "name", "uq_shipment_tenant_name", ("tenant", "name")),
    ("rfqs", "shipment_name", "uq_rfq_tenant_shipment", ("tenant", "shipment_name")),
)


def _migrate_constraints() -> None:
    """Replace the global unique constraints with per-tenant ones.

    `_auto_migrate` adds columns but never touches constraints, so an existing
    database keeps enforcing "one contact per email across every client" long
    after the model says otherwise — and the failure appears as an
    IntegrityError while onboarding, not here.

    Postgres only. SQLite cannot drop a constraint without rebuilding the table,
    and every SQLite database here is created fresh by `create_all`, which
    builds the composite form from the start.
    """
    if engine.dialect.name != "postgresql":
        return
    from sqlalchemy import inspect as sa_inspect, text

    insp = sa_inspect(engine)
    tables = set(insp.get_table_names())
    with engine.begin() as conn:
        for table, old_col, new_name, new_cols in _REGRADED_UNIQUES:
            if table not in tables:
                continue
            have = {c["name"] for c in insp.get_columns(table)}
            if not set(new_cols) <= have:
                continue  # tenant column not added yet; next startup will catch it
            existing = {u["name"]: u.get("column_names") or []
                        for u in insp.get_unique_constraints(table)}
            for name, cols in existing.items():
                if cols == [old_col] and name != new_name:
                    conn.execute(text(
                        f'ALTER TABLE "{table}" DROP CONSTRAINT "{name}"'))
            if new_name not in existing:
                cols = ", ".join(f'"{c}"' for c in new_cols)
                conn.execute(text(
                    f'ALTER TABLE "{table}" ADD CONSTRAINT "{new_name}" UNIQUE ({cols})'))


def _auto_migrate() -> None:
    """Add any model columns missing from existing tables. create_all() makes
    NEW tables but never alters existing ones, so adding a column to a model
    would otherwise break queries with ProgrammingError. This reconciles them
    automatically on startup — so future field additions just work."""
    from sqlalchemy import inspect as sa_inspect, text

    insp = sa_inspect(engine)
    existing_tables = set(insp.get_table_names())
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue  # create_all already handled brand-new tables
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                ddl = col.type.compile(dialect=engine.dialect)
                default = ""
                if col.default is not None and getattr(col.default, "arg", None) is not None \
                        and not callable(col.default.arg):
                    val = col.default.arg
                    default = f" DEFAULT '{val}'" if isinstance(val, str) else f" DEFAULT {val}"
                try:
                    conn.execute(text(
                        f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {ddl}{default}'))
                except Exception:  # noqa: BLE001 — already exists / dialect quirk
                    pass


def init_db() -> None:
    Base.metadata.create_all(engine)
    try:
        _auto_migrate()
        _migrate_constraints()
    except Exception:  # noqa: BLE001 — never block startup on migration
        import logging
        logging.getLogger("db").exception("auto-migrate failed")
