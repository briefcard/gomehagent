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


def init_db() -> None:
    Base.metadata.create_all(engine)
