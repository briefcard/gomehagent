"""Database models. Postgres on Render, SQLite locally."""
import datetime as dt
import uuid

from sqlalchemy import JSON, Column, DateTime, String, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from . import config

engine = create_engine(config.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


def _uuid() -> str:
    return uuid.uuid4().hex


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Approval(Base):
    """Any action that needs Gomeh's sign-off before execution."""

    __tablename__ = "approvals"

    id = Column(String, primary_key=True, default=_uuid)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    kind = Column(String, nullable=False)  # send_email | buy_label | pay | other
    status = Column(String, default="pending")  # pending | approved | denied | executed | expired
    summary = Column(Text, nullable=False)  # one-line human description
    payload = Column(JSON, nullable=False)  # everything needed to execute on approval
    decided_at = Column(DateTime(timezone=True))
    executed_at = Column(DateTime(timezone=True))
    channel = Column(String, default="email")  # email | whatsapp


class EmailLog(Base):
    """Every inbound email seen and what the agent did with it."""

    __tablename__ = "email_log"

    id = Column(String, primary_key=True, default=_uuid)
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

    id = Column(String, primary_key=True, default=_uuid)
    email = Column(String, unique=True, nullable=False)
    name = Column(String)
    company = Column(String)
    role = Column(String)  # forwarder | customs_broker | warehouse | client | vendor | other
    entity = Column(String)  # baci | eien | saias | shared
    trusted = Column(String, default="no")  # yes -> routine replies may auto-send


class Deadline(Base):
    """Anything with a date that costs money if missed."""

    __tablename__ = "deadlines"

    id = Column(String, primary_key=True, default=_uuid)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    account = Column(String)
    description = Column(Text, nullable=False)  # what's due
    amount = Column(String)  # "$148.50" or "unknown"
    due_date = Column(String)  # YYYY-MM-DD (lexicographic compare works)
    source_subject = Column(Text)
    status = Column(String, default="open")  # open | alerted | done | dismissed


class ChatMessage(Base):
    """WhatsApp conversation history — gives the command agent continuity."""

    __tablename__ = "chat_messages"

    id = Column(String, primary_key=True, default=_uuid)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    role = Column(String, nullable=False)  # user | assistant
    content = Column(Text, nullable=False)


class Memory(Base):
    """Durable working memory: ongoing tasks, decisions, standing instructions.
    Written by the agent itself; injected into every prompt (chat + triage)."""

    __tablename__ = "memories"

    id = Column(String, primary_key=True, default=_uuid)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    topic = Column(String, nullable=False)  # e.g. 'Turkey shipment', 'standing rule'
    content = Column(Text, nullable=False)
    status = Column(String, default="active")  # active | archived


class FollowUp(Base):
    """Outbound messages that expect a reply — chased automatically."""

    __tablename__ = "follow_ups"

    id = Column(String, primary_key=True, default=_uuid)
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

    id = Column(String, primary_key=True, default=_uuid)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow)
    name = Column(String, unique=True, nullable=False)  # e.g. 'Turkey-Mar2026'
    status = Column(String, default="quoting")  # quoting|booked|in_transit|customs|arrived|received|closed
    eta = Column(String)  # YYYY-MM-DD or ''
    counterparty = Column(String)  # forwarder/broker
    docs = Column(JSON, default=dict)  # {'BOL': 'have|missing|link', ...}
    costs = Column(JSON, default=dict)  # {'freight': '...', 'duties': '...'}
    notes = Column(Text, default="")


class RFQ(Base):
    """A request-for-quote round for one shipment, across multiple forwarders."""

    __tablename__ = "rfqs"

    id = Column(String, primary_key=True, default=_uuid)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    shipment_name = Column(String, unique=True, nullable=False)
    status = Column(String, default="quoting")  # quoting | complete | decided | closed
    details = Column(JSON, default=dict)  # cargo, origin, incoterm, ready date...
    forwarders = Column(JSON, default=list)  # emails the RFQ went to
    quotes = Column(JSON, default=dict)  # {forwarder_email: {total, breakdown, notes, received}}


class Expense(Base):
    """Business expense receipts captured from email — tax-season raw material."""

    __tablename__ = "expenses"

    id = Column(String, primary_key=True, default=_uuid)
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
    created_at = Column(DateTime(timezone=True), default=utcnow)
    scope = Column(String, default="global")  # global | <role name>
    lesson = Column(Text, nullable=False)
    origin = Column(String, default="")  # which agent/role learned it
    hits = Column(String, default="0")  # times reinforced


class Setting(Base):
    """Tiny key/value store for run-once markers."""

    __tablename__ = "settings"

    key = Column(String, primary_key=True)
    value = Column(Text)


class VoiceProfile(Base):
    """Per-inbox writing style, distilled from past sent emails."""

    __tablename__ = "voice_profiles"

    alias = Column(String, primary_key=True)  # personal | baci | eien
    rules = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)


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
    except Exception:  # noqa: BLE001 — never block startup on migration
        import logging
        logging.getLogger("db").exception("auto-migrate failed")
