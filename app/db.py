"""Database models. Postgres on Render, SQLite locally."""
import datetime as dt
import uuid

from sqlalchemy import (JSON, Column, DateTime, Float, Integer, String, Text,
                        UniqueConstraint, create_engine)
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

    # What was actually SAID, not just that something arrived. Without this the
    # archive is a catalogue: an agent could report that a thread with this
    # counterparty exists and could not tell you a word of what was agreed in
    # it. That is the single failure that made inbox drafts untrustworthy —
    # it looked like a reasoning problem and was a storage one.
    #
    # Bounded, and quoted history stripped before it lands: a re-quoted chain
    # embeds as whatever it is replying to, so a fifteen-message thread would
    # otherwise retrieve as fifteen near-identical rows.
    body_excerpt = Column(Text)
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


class Conversation(Base):
    """One ongoing exchange with one counterparty, for one system.

    `ChatMessage.thread` already namespaces conversation history, and it is the
    right primitive for what it was built for: Gomeh talking to his agents. That
    is roughly twenty threads — roles times tenants — with one operator and no
    lifecycle. Every system on the roadmap breaks it, for reasons that are about
    shape rather than scale:

    * **A thread string is a namespace, not an entity.** There is nowhere to put
      what stage a lead is at, whether we are waiting on them or they on us, or
      when the next touch is due. Those are columns.
    * **Loading context meant replaying messages.** A fourteen-touch sequence
      either re-reads everything, which is the token overhead this layer exists
      to remove, or truncates and forgets what was promised in touch three.
    * **No state machine.** Nothing could enforce "do not send touch four if
      they replied", or "do not offer a refund twice".

    So this sits beside `ChatMessage`, it does not replace it. Operator threads
    stay there; counterparty threads live here.

    **Overlapping threads collapse onto one row.** Two email chains with the same
    person about the same job are one conversation — `open_or_get` finds the open
    one rather than starting a second, and `external_refs` keeps every provider
    thread id that has been folded in. That is the whole answer to "the same
    company has three threads and the agent cannot tell they are one thing".

    There is deliberately no unique constraint on (tenant, contact, system): a
    lead who goes quiet and returns next quarter is a *new* conversation, and a
    constraint would either forbid that or force the old one to stay open.
    Reuse is a lookup on `status == "open"`, not a schema rule.
    """

    __tablename__ = "conversations"

    id = Column(String, primary_key=True, default=_uuid)
    tenant = Column(String, default="", index=True)
    contact_id = Column(String, index=True)
    system_key = Column(String, default="", index=True)  # lead_responder | service_desk | …

    subject = Column(String, default="")        # a human label, for a queue view
    stage = Column(String, default="", index=True)
    status = Column(String, default="open", index=True)   # open | closed | blocked
    outcome = Column(String, default="")        # won | lost | resolved | abandoned

    # The join to the knowledge half. The conversation carries the situation
    # tags; the KB serves the objections and claims for those tags. Written by
    # a classifier that now refuses to guess (see kb.suggest_tags).
    situations = Column(JSON, default=list)
    entity_key = Column(String, default="")     # the product/venue/offer in play

    # Every provider thread id folded into this conversation. [{source, ref}]
    external_refs = Column(JSON, default=list)

    opened_at = Column(DateTime(timezone=True), default=utcnow)
    last_touch_at = Column(DateTime(timezone=True))
    next_action_at = Column(DateTime(timezone=True), index=True)
    closed_at = Column(DateTime(timezone=True))
    blocked_on = Column(String, default="")     # named, never a bare "blocked"


class Touch(Base):
    """One message in one conversation, in either direction.

    Bounded history: the conversation carries state, so reading it never means
    replaying every message. A touch is a record that something was sent or
    received, not the transcript of it.

    `idempotency_key` is the anti-double-send guard, and it is why this is a row
    rather than an entry in a log. A worker restarting mid-publish is a known
    unfixed failure in this codebase; a touch that already exists for a key
    cannot be written twice. The constraint is composite with `tenant` because a
    globally unique column on a per-client table means two clients cannot both
    have one — `test_tenant_isolation` fails the build for exactly this.
    """

    __tablename__ = "touches"
    __table_args__ = (UniqueConstraint("tenant", "idempotency_key",
                                       name="uq_touch_tenant_idem"),)

    id = Column(String, primary_key=True, default=_uuid)
    tenant = Column(String, default="", index=True)
    conversation_id = Column(String, index=True)

    channel = Column(String, default="email")   # email | whatsapp | telegram | call | form
    direction = Column(String, default="out")   # out | in
    summary = Column(Text)                      # what was said, not the full body
    ref = Column(String, default="")            # provider message id

    # Ties a touch back to the run that produced it, so an output can be traced
    # to the context that produced it. `Approval` has had these columns since
    # the tenant migration and nothing has ever written them.
    run_id = Column(String, default="", index=True)
    approval_id = Column(String, default="")

    idempotency_key = Column(String, default="")
    stage_at = Column(String, default="")       # the stage when this was sent
    sent_at = Column(DateTime(timezone=True), default=utcnow)


class Commitment(Base):
    """Something we told a counterparty we would do.

    The point of this table is that "effective without misleading" stops being a
    line in a prompt and becomes a row a validator can check. A prompt mostly
    obeys; a check always blocks — the same split as `note()` versus
    `promote_rule()` on the systems side, one layer over.

    A price quoted, a date offered, a refund promised, a callback agreed. Before
    a drafter says anything about a price or a date, the open commitments on the
    conversation are in front of it, so it cannot quietly contradict what was
    already said or promise the same thing twice.

    `value` is a string for the same reason `KbEntity.price` is: "$2,400", "by
    Friday" and "2–3 weeks" are all real answers and none of them is a number.
    """

    __tablename__ = "commitments"

    id = Column(String, primary_key=True, default=_uuid)
    tenant = Column(String, default="", index=True)
    conversation_id = Column(String, index=True)

    kind = Column(String, default="other")      # price | date | refund | discount | callback | other
    value = Column(String, default="")
    detail = Column(Text)

    status = Column(String, default="open", index=True)  # open | met | broken | withdrawn
    due_at = Column(DateTime(timezone=True), index=True)

    stated_in = Column(String, default="")      # Touch.id — where we said it
    stated_at = Column(DateTime(timezone=True), default=utcnow)
    settled_at = Column(DateTime(timezone=True))
    settled_note = Column(String, default="")


class Moment(Base):
    """A known person is in a window where a message is welcome.

    **Never "abandoned cart".** This platform serves an e-commerce store, a
    venue, a B2B specifier and a digital-products account. A property rental
    has no carts; it has enquiries that go quiet and dates that expire. Name
    the row after the cart and the venue can never use it, and the vertical
    bakes into the generic layer where nobody finds it for a year.

    So the abstraction is the WINDOW, and everything specific to how the window
    was noticed stays in `payload`, which is opaque to every reader. A producer
    files moments; it does not know what they are for, and it must not — the
    proof that this layer is real is that a venue enquiry going quiet and a
    cart going cold land in this table side by side, from two producers,
    neither of which knows the other exists.

    Three timestamps, because they answer three different questions:

        occurred_at   when the signal happened in the world
        due_at        when a message becomes WELCOME — a cart is not cold the
                      instant it is abandoned, and writing then reads as
                      surveillance rather than service
        expires_at    after which it must not be acted on at all. A moment is
                      perishable by definition; one acted on late is worse
                      than one missed, because it proves nobody was looking.
    """

    __tablename__ = "moments"
    #: Idempotency, at the database rather than in a producer's head. Webhooks
    #: retry, pollers overlap, and two workers can see the same signal in the
    #: same second. The producer composes `dedup_key` to include whatever
    #: window it considers one occurrence, so a cart cooling twice in March is
    #: two moments and the same delivery arriving twice is one.
    __table_args__ = (UniqueConstraint("tenant", "dedup_key",
                                       name="uq_moment_tenant_dedup"),)

    id = Column(String, primary_key=True, default=_uuid)
    tenant = Column(String, default="", index=True)
    #: A key from `moments.CATALOG`. Not free text — an unknown kind is a
    #: producer filing something no planner can be asked to consume.
    kind = Column(String, default="", index=True)
    #: WHO. The lowercased email, because it is the one identity every channel
    #: in this system already shares — Contact, the ESP, the store and the
    #: inbox all key on it. `contact_id` when we happen to have the row.
    person_key = Column(String, default="", index=True)
    contact_id = Column(String, default="", index=True)
    #: WHAT it is about — a product, an enquiry's subject, an offer. Empty is
    #: legitimate and common: "this person went quiet" is about nothing.
    entity_key = Column(String, default="", index=True)
    conversation_id = Column(String, default="", index=True)
    #: WHICH PRODUCER filed it, for the same reason `Output.basis` exists: when
    #: a moment turns out to be wrong, the question is always which watcher
    #: was mistaken.
    source = Column(String, default="", index=True)
    dedup_key = Column(String, default="", index=True)

    occurred_at = Column(DateTime(timezone=True), default=utcnow, index=True)
    due_at = Column(DateTime(timezone=True), index=True)
    expires_at = Column(DateTime(timezone=True), index=True)

    #: open | consumed | expired | suppressed
    #:
    #: `suppressed` is its own state and not a deletion: "we chose not to write
    #: to this person" is a fact worth keeping, and a moment that vanishes when
    #: a cap declines it makes a frequency rule impossible to audit.
    status = Column(String, default="open", index=True)
    #: The run that consumed it, so a draft can be traced back to the signal.
    consumed_by = Column(String, default="", index=True)
    #: Why it is not open, in words — the expiry that passed, the cap that
    #: declined it. Named, never a bare "suppressed".
    closed_reason = Column(String, default="")
    closed_at = Column(DateTime(timezone=True))

    #: PRODUCER-SPECIFIC AND OPAQUE. The cart's line items, the enquiry's last
    #: subject. Nothing in the generic layer may read a key out of here — the
    #: moment the planner special-cases `payload["cart_total"]`, commerce has
    #: leaked into the spine and the venue is a second-class citizen again.
    payload = Column(JSON, default=dict)


class Output(Base):
    """One thing a system produced, and the brief that produced it.

    The table that makes a system improvable rather than merely operable. It
    does three jobs that were each going to need their own store:

    * **Anti-repeat.** "Has this claim been used for this product lately" is a
      query here and is unanswerable anywhere else. The handoff lists "topic
      not already covered" as a validator requirement and nothing has ever
      been able to check it.
    * **Attribution.** The e-commerce loop is analyse → hypothesis → generate →
      measure, and it closes only if what varied between two outputs is
      recorded. The brief fields ARE the experiment record.
    * **Hygiene.** A claim never selected across hundreds of outputs is wrong
      or redundant, and nothing else can name which claims those are.

    The brief is stored as columns rather than prose because all three of those
    are queries. `body` is deliberately a short rendering, not the artifact:
    this is a ledger of decisions, not a content store.
    """

    __tablename__ = "outputs"

    id = Column(String, primary_key=True, default=_uuid)
    tenant = Column(String, default="", index=True)
    system_key = Column(String, default="", index=True)
    run_id = Column(String, default="", index=True)

    # --- the brief: what was chosen, and why this rather than that ---------
    situation = Column(String, default="", index=True)
    entity_key = Column(String, default="", index=True)
    audience_key = Column(String, default="", index=True)
    objection_id = Column(String, default="", index=True)
    claim_ids = Column(JSON, default=list)
    media_ids = Column(JSON, default=list)
    #: Which LIVE lookups fed this output — `["shopify_inventory", …]`.
    #:
    #: A claim is true until somebody changes it; a lookup was true at the
    #: moment it was read. Both end up as sentences in the same reply, and once
    #: written they are indistinguishable — which is how a reply saying "that
    #: cup is out of stock", entirely correct in August, gets pulled into the
    #: bundle for a September follow-up and read as though it still holds.
    #:
    #: Recording which lookups fed a body is what lets a later run say "this
    #: one contained a stock reading, re-check before repeating it" instead of
    #: quoting it forward. Empty means no live data went in, which is the
    #: common case and is genuinely different from unknown.
    lookups = Column(JSON, default=list)
    # INDEXED, all three. These four columns are the strategy substrate — what
    # was said, to whom, in what form — and every question worth asking of them
    # is a filter or a group-by over a 90-day window: which intents went to
    # this list, how often, with what spacing. Unindexed that is a sequential
    # scan of every output the account has ever produced, which is why the one
    # reader that exists takes four rows for one segment and nothing has ever
    # aggregated them.
    #
    # `shape` below is deliberately NOT indexed: it is a JSON list, a btree on
    # it would answer no question anybody asks, and it is read by fetching the
    # last few rows rather than by filtering on it.
    theme = Column(String, default="", index=True)
    angle = Column(String, default="", index=True)
    format = Column(String, default="", index=True)
    #: The STRUCTURAL fingerprint of what was produced — for an email, the
    #: block sequence it was built from (`["hero","heading","text",…]`).
    #:
    #: Anti-repeat is already this table's first job, but it could only answer
    #: "has this CLAIM been used lately". The owner's complaint about the email
    #: engine was the other half: every send was the same SHAPE, and nothing
    #: could tell, because shape was never recorded. With it here, a drafter
    #: can be shown the last few layouts and asked for a different one, and
    #: "are we sending the same email every week" becomes a query.
    #:
    #: Empty for skills that have no meaningful structure, which is most of
    #: them, and empty for every row written before this column existed —
    #: honestly unknown rather than falsely uniform.
    shape = Column(JSON, default=list)

    # --- what happened to it ----------------------------------------------
    status = Column(String, default="draft", index=True)  # draft|blocked|approved|published
    blocked_on = Column(JSON, default=list)
    destination = Column(String, default="")
    body = Column(Text)                    # short rendering, not the artifact
    body_hash = Column(String, default="", index=True)

    # Who it concerned, so an output can be traced to a conversation and back.
    conversation_id = Column(String, default="", index=True)
    touch_id = Column(String, default="")

    created_at = Column(DateTime(timezone=True), default=utcnow, index=True)
    published_at = Column(DateTime(timezone=True))
    outcome = Column(JSON, default=dict)   # metrics, filled in later


class AssuranceEvent(Base):
    """One check the data layer performed, and what it caught.

    Everything else in this schema records what was PRODUCED. Nothing records
    what was CHECKED, so "is the layer actually doing anything" had no answer
    except reading code — and a guarantee nobody can see is one nobody
    maintains, which is §2.13 for the third time.

    The row that matters most is a `banned_claim` catch. It is not a metric,
    it is a counterfactual: the model wrote that phrase, deterministic code
    stopped it, and without the layer it would have gone out. That is the only
    honest evidence this is better than the model alone, and it is why
    `caught` is stored as the rule names rather than a count.

    `source` matters as much as the verdict. The substrate, the skill bridge
    and the mail path all check drafts, and they are not equally good at it —
    seeing them side by side is how you find out that the live path is using
    the weaker matcher.
    """

    __tablename__ = "assurance_events"

    id = Column(String, primary_key=True, default=_uuid)
    created_at = Column(DateTime(timezone=True), default=utcnow, index=True)
    tenant = Column(String, default="", index=True)
    system_key = Column(String, default="", index=True)
    run_id = Column(String, default="", index=True)
    output_id = Column(String, default="")

    #: skill | bridge | mail | console — WHERE the check happened.
    source = Column(String, default="", index=True)
    #: Rules the validator actually ran. Absent rules are not passes.
    checked = Column(JSON, default=list)
    #: Rule names that failed. Empty list is a genuine pass; that distinction
    #: is the whole point of storing both.
    caught = Column(JSON, default=list, index=False)
    #: 0 for the first draft, 1..n for each repair attempt.
    attempt = Column(String, default="0")
    #: passed | repaired | blocked — the outcome AFTER the repair loop.
    verdict = Column(String, default="", index=True)
    #: Whether the draft carried a claim_id. Grounding, not correctness.
    grounded = Column(String, default="")
    #: What the run was working without, if anything.
    thin = Column(JSON, default=list)


class ToolCall(Base):
    """One tool call, and whether the thing on the other end answered.

    `Usage` records what the MODEL cost. Nothing recorded what the tools DID —
    so "is this client's Shopify actually being read", "did their Search
    Console start failing three weeks ago", and "what did we do for them this
    month" were all unanswerable, and a client report would have had to be
    written from memory.

    The result is recorded as a SIZE and a verdict, never a payload. A tool
    result is the client's own data — orders, mail, customers — and a ledger
    that copies it becomes a second place their data lives, with none of the
    scoping the first one has. Size and success are what a report needs; the
    body is not.
    """

    __tablename__ = "tool_calls"

    id = Column(String, primary_key=True, default=_uuid)
    at = Column(DateTime(timezone=True), default=utcnow, index=True)
    tenant = Column(String, default="", index=True)
    tool = Column(String, default="", index=True)
    #: kernel (an agent tool) | adapter (a platform client called from code)
    source = Column(String, default="", index=True)
    #: Which of the client's platforms this reached, when it reached one.
    #: Empty for tools that only touch our own tables.
    provider = Column(String, default="", index=True)
    ok = Column(String, default="")          # "yes" | "no" — never a bare bool
    error = Column(Text, default="")         # the provider's own words, capped
    ms = Column(String, default="")          # round trip, for the slow ones
    bytes_back = Column(String, default="")  # size, never the payload itself
    ref = Column(String, default="")         # run id / message id, when known


class ReportedFigure(Base):
    """A number the CLIENT supplied, because we cannot read it.

    Some figures are not ours to compute. What a support reply costs in staff
    time, what a saved sale was worth, what their margin is — those are facts
    about their business, and a platform that guesses them puts an invented
    number in a document the client will forward to somebody else.

    Others we could compute but are not allowed to: a client with privacy
    concerns may decline to connect their store at all, and the choice then is
    a report with a hole in it or a report built from what they send us.

    Stored WITH provenance — who said it, when, and for which period — because
    a client-supplied number in a client-facing report has to be attributable
    back to the client who supplied it. `period_start`/`period_end` are part of
    the identity: last quarter's average order value is not this quarter's, and
    silently carrying one forward is how a report becomes fiction.
    """

    __tablename__ = "reported_figures"

    id = Column(String, primary_key=True, default=_uuid)
    tenant = Column(String, nullable=False, index=True)
    metric_key = Column(String, nullable=False, index=True)
    period_start = Column(String, default="")     # YYYY-MM-DD
    period_end = Column(String, default="")
    value = Column(String, default="")            # as given, never coerced
    unit = Column(String, default="")
    supplied_by = Column(String, default="")      # who said so
    at = Column(DateTime(timezone=True), default=utcnow)
    note = Column(Text, default="")


class PortalLink(Base):
    """A single-use sign-in link for one client user.

    Same shape as `ConnectLink` and `IntakeLink`, deliberately — this codebase
    already had two scoped, expiring, key-free links and inventing a third
    mechanism for the same job is how they drift apart.

    SINGLE USE, unlike those two. A connect link is a task somebody may come
    back to; a sign-in link is a credential, and one that stays valid after use
    sits in a mailbox forever waiting to be forwarded. `used_at` is set on
    redemption and checked before anything is issued.
    """

    __tablename__ = "portal_links"

    token = Column(String, primary_key=True)
    user_id = Column(String, nullable=False, index=True)
    tenant = Column(String, default="", index=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    expires_at = Column(DateTime(timezone=True))
    used_at = Column(DateTime(timezone=True))
    issued_by = Column(String, default="")


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

    # WHICH CONVERSATION this arrived on. `anchor` is a business key —
    # 'Primorous PO-2241' — and answers a different question. Without these two
    # you can find the bill of lading and you can find the thread where the
    # credit was agreed, and nothing joins them: "what was attached to that
    # conversation" is unanswerable. Same shape as the email bodies —
    # catalogued, not connected.
    thread_id = Column(String, default="", index=True)
    gmail_message_id = Column(String, default="", index=True)

    # The extracted text, so a document is answerable rather than merely
    # findable. `read_email_attachment` has been pulling this out of PDFs all
    # along and throwing it away — which is why "what did the BOL say" needed a
    # human to open the file, while "is there a BOL" did not.
    text_excerpt = Column(Text)


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


class CraftLesson(Base):
    """Something learned at one account that may help at a similar one.

    The ONLY table here with no tenant column, and that is the point: it is
    deliberately outside the isolation boundary everything else obeys. So the
    line it must never cross is drawn narrowly and enforced in `app/craft.py`:

    **Craft shapes HOW something is said. It is never WHAT is asserted.** A
    claim is a fact about a client's business, carries a `claim_id` and gets
    cited; a lesson is technique, is injected as guidance, and can never become
    a citation. That distinction is the same one this codebase already draws
    between prose guidance and the banned-claims list, applied one layer out.

    `learned_from` is kept for audit — "where did this come from" must be
    answerable — and is NEVER rendered into a prompt or shown to another
    client. `business_model` is the reach: a lesson from a venue does not
    travel to a shop, using the vocabulary `metrics.OUTCOMES` already defines.

    Nothing lands here automatically. `review` follows the KB's rule and a
    person approves, because the leak guard can only catch what it can
    recognise and a human is the second check.
    """

    __tablename__ = "craft_lessons"

    id = Column(String, primary_key=True, default=_uuid)
    created_at = Column(DateTime(timezone=True), default=utcnow, index=True)
    # Which kind of business it applies to, or "" for any.
    business_model = Column(String, default="", index=True)
    # The situation vocabulary, so a lesson surfaces when it is relevant.
    situations = Column(JSON, default=list)
    lesson = Column(Text, nullable=False)      # the guidance itself
    basis = Column(Text, default="")           # why we believe it
    learned_from = Column(String, default="")  # audit only, never rendered
    review = Column(String, default="proposed", index=True)  # proposed|approved|retired
    approved_by = Column(String, default="")
    approved_at = Column(DateTime(timezone=True))
    uses = Column(String, default="0")


class ComplianceEvent(Base):
    """One privacy request from Shopify, and what we did about it.

    Shopify's three mandatory webhooks carry a LEGAL deadline (30 days), and
    two of them cannot be satisfied by code alone: deciding what counts as a
    customer's data in a system that stores replies, drafts and correspondence
    is a judgement. So this table is the record that the request arrived, what
    was deleted automatically, and what a person still has to do — because a
    compliance obligation nobody can prove was met is one that was not met.

    The payload is kept deliberately: it is the merchant's own request, it is
    small, and reconstructing "which customer did Shopify ask about in March"
    from a deleted row is impossible. `handled_at` is null until somebody
    closes it.
    """

    __tablename__ = "compliance_events"

    id = Column(String, primary_key=True, default=_uuid)
    created_at = Column(DateTime(timezone=True), default=utcnow, index=True)
    topic = Column(String, default="", index=True)   # customers/redact | ...
    shop = Column(String, default="", index=True)    # the myshopify domain
    tenant = Column(String, default="", index=True)  # ours, when resolvable
    payload = Column(JSON, default=dict)
    # What code did on its own, and what it could not decide.
    acted = Column(JSON, default=list)
    needs_human = Column(Text, default="")
    handled_at = Column(DateTime(timezone=True))


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


class KeywordTarget(Base):
    """One keyword this account intends to rank for, and how it plans to.

    THE INTENT TO RANK, NOT THE OBSERVED RANK. Every position question is
    answered from `KeywordReading`, deliberately: a cached `current_position`
    is a number that goes stale silently, and this codebase already lost a
    afternoon to `capabilities()` reporting a stored declaration as a live
    fact. What is stored here is what somebody DECIDED — which phrase, at what
    tier, in which cluster, against which URL.

    `SeoSnapshot` does not replace this and never could: it holds the top 50
    keywords BY TRAFFIC SHARE for a domain, so a phrase you are targeting and
    do not yet rank for has no row there at all. That is the whole population
    this table exists for.

    **`cluster_key` + `role` are the mechanism, not decoration.** A head term
    is not won with an article; it is won with a pillar page and the long-tail
    supports that link into it. A cluster half-built is the most common way
    this work produces nothing, and it is only countable if the grouping is
    data.
    """

    __tablename__ = "keyword_targets"
    __table_args__ = (UniqueConstraint("tenant", "phrase", name="uq_kwt_tenant_phrase"),)

    id = Column(String, primary_key=True, default=_uuid)
    tenant = Column(String, default="", index=True)
    phrase = Column(String, nullable=False, index=True)
    database = Column(String, default="us")     # Semrush regional market

    # --- what kind of keyword this is (computed, never typed) -------------
    tier = Column(String, default="", index=True)     # head | body | long_tail
    intent = Column(String, default="", index=True)   # informational | commercial
                                                      # | transactional | navigational
    volume = Column(Integer, default=0)
    #: Semrush KD, 0-100. NULLABLE ON PURPOSE — unknown is not zero. Semrush's
    #: `phrase_related` projection carries `competition` (paid, 0-1) and no KD,
    #: and filling this from that would be DEFECTS §1's "ranking across
    #: incomparable scales" written deliberately. A row with no KD scores no
    #: difficulty penalty AND no difficulty bonus; see `keywords.score`.
    difficulty = Column(Float)
    cpc = Column(Float, default=0.0)

    #: Which harvester found it. Kept because the four answer different
    #: questions and their yields should be comparable — a source that never
    #: produces a win is one to stop spending calls on.
    source = Column(String, default="", index=True)

    # --- the plan ---------------------------------------------------------
    cluster_key = Column(String, default="", index=True)
    role = Column(String, default="support")          # pillar | support
    target_url = Column(String, default="")
    #: candidate -> planned -> published -> won | parked. `published` means an
    #: artifact exists; `won` is a JUDGEMENT about position and is set from
    #: readings, never by the thing that published.
    status = Column(String, default="candidate", index=True)
    output_id = Column(String, default="", index=True)   # -> Output.id
    run_id = Column(String, default="", index=True)      # -> SystemRun.id
    published_at = Column(DateTime(timezone=True))

    #: Last computed priority + its components, so a ranking can be argued
    #: with rather than only obeyed.
    priority = Column(Float, default=0.0, index=True)
    priority_parts = Column(JSON, default=dict)

    first_seen = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    notes = Column(Text, default="")


class KeywordReading(Base):
    """One observation of one phrase, from one source, at one time.

    TWO SOURCES ON PURPOSE, because they disagree and the disagreement is the
    information. GSC is the truth about YOUR traffic — impressions, clicks and
    an average position over the devices and places your buyers actually are.
    Semrush is the truth about the MARKET — where a competitor sits, what the
    term is worth. Semrush saying 7 while GSC says 11.3 is not an error to
    reconcile, and storing one would mean re-deriving the other every time
    somebody asked.

    `SeoSnapshot.source` has been declared `semrush | gsc` since it was written
    and only `semrush` was ever written to it. This table is where the GSC half
    finally lands.
    """

    __tablename__ = "keyword_readings"

    id = Column(String, primary_key=True, default=_uuid)
    tenant = Column(String, default="", index=True)
    phrase = Column(String, nullable=False, index=True)
    at = Column(DateTime(timezone=True), default=utcnow, index=True)
    source = Column(String, default="gsc", index=True)   # gsc | semrush
    database = Column(String, default="")                # Semrush market, if any

    position = Column(Float)          # NULL means "not ranking", not zero
    impressions = Column(Integer, default=0)
    clicks = Column(Integer, default=0)
    ctr = Column(Float, default=0.0)
    url = Column(String, default="")  # the page that ranked, when reported


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
    #: What this business IS, from `kb.SITUATIONS`' "who they are" set —
    #: ecom_inventory | local_venue | b2b_spec | digital_products | coaching |
    #: real_estate | food_bev | ecom_dtc.
    #:
    #: It decides which OUTCOMES a report carries. A venue is measured in
    #: enquiries and events booked; a store in revenue and average order value.
    #: Reporting a venue's "average order value" is not a small error — it is
    #: the client concluding we do not know what their business is.
    #:
    #: No default, so an account nobody has classified reads as unknown rather
    #: than as a shop.
    business_model = Column(String, default="")
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
    status = Column(String, default="active")   # active | revoked
    #: What this person may DO in the portal — "read_only" | "full".
    #:
    #: Defaults to read_only, and that is the whole point: least privilege for
    #: a surface that shows a client's own commercial data and lets them hand
    #: us figures we will print in a report. Somebody who gains portal access
    #: without an explicit grant should get the lesser of the two, not the
    #: greater, and an upgrade should be a decision somebody made.
    access = Column(String, default="read_only")
    created_at = Column(DateTime(timezone=True), default=utcnow)


# ---------------------------------------------------------------------------
# Knowledge Base — multi-tenant. Every row carries `tenant`; nothing is ever
# read without one. Customisation lives HERE as data, never as forked code.
# Consumed by the brief assembler (deterministic) and enforced by the
# validator (also deterministic). Models are generated FROM these rows and
# never allowed to assert anything that isn't in them.
#
# Every KB content table also carries the provenance columns below. Three
# sources fill these tables — a website crawl, a spreadsheet upload, and a
# human — and without a shared answer to "where did this come from and who may
# change it" each one invented its own. See `provenance.py` for the rules; this
# is the storage they need.
# ---------------------------------------------------------------------------

class _Provenance:
    """Mixin: where a KB row came from and whether a human has signed it off.

    `origin` is the source KIND and is what precedence is computed from. It is
    deliberately separate from the free-text `source` reference, because
    deciding who may overwrite a row by string-matching prose is precisely the
    bug that let a store sync clobber owner-approved copy.

    `review` is one axis shared by all five tables, distinct from the lifecycle
    `status` that claims and entities also carry. A row is proposed, approved
    or rejected; approved is final and only a human may move it.

    `fingerprint` is the normalised content hash. It is what makes a second
    harvest of the same page, or a re-uploaded spreadsheet, update one row
    instead of adding another.
    """

    # No column default, for the same reason `review` has none: auto-migration
    # applies a column default to every existing row, which would stamp the
    # whole knowledge base "human" and leave `_backfill_provenance` nothing to
    # derive from. A store-synced product reading as human-owned would then
    # raise a conflict on every future sync instead of refreshing quietly.
    origin = Column(String)                       # seed|crawl|upload|store_sync|client|human
    # No default, on purpose. Every read accessor treats anything that is not
    # exactly "approved" as not approved, so a row created without one is
    # invisible to the pipeline rather than silently usable — the failure that
    # matters here is a proposal reaching a draft, so this fails closed.
    # Existing production rows come out of the migration as NULL and are
    # grandfathered to approved exactly once, by `_backfill_provenance`.
    review = Column(String)                       # proposed | approved | rejected
    approved_by = Column(String, default="")
    approved_at = Column(DateTime(timezone=True))
    fingerprint = Column(String, default="", index=True)
    # Every source that has asserted this same row, so collapsing a duplicate
    # keeps the corroboration instead of discarding it. [{origin, ref, seen}]
    also_seen = Column(JSON, default=list)

class KbBrand(Base):
    """One row per tenant: who they are, how they sound, what they may not say."""

    __tablename__ = "kb_brand"

    tenant = Column(String, primary_key=True)  # agency | baci | eien | coverings | ironside
    display_name = Column(String, nullable=False)
    positioning = Column(Text)
    elevator = Column(JSON, default=dict)      # {sentence, paragraph, page}
    voice = Column(JSON, default=dict)         # {tone[], do_say[], never_say[], examples[]}
    # How the brand LOOKS, as rules a generator can be held to: {direction,
    # do_show[], never_show[]}. Deliberately not colours, type or logos — those
    # live in the Canva brand kit, which a designer already maintains, and
    # duplicating them BY HAND here would create two sources of truth that
    # drift. (The `theme` below is not that: it is a DERIVED, owner-approved
    # snapshot of those sources, refreshed by re-running the deriver.)
    # What no brand kit holds is art direction: "always styled on a laid
    # table", "never a face", "no props we do not sell". That is the visual
    # equivalent of `voice.never_say`, and without it a generative creative
    # path has nothing to be wrong against.
    visual = Column(JSON, default=dict)
    # How the brand looks in an EMAIL, concretely: the render theme
    # `email_render` consumes — logo URL, palette, font stacks, nav, and the
    # CAN-SPAM footer (mailing address, socials, disclaimer).
    #
    # `theme` is the LIVE one: derived by `brand_theme.derive` (Canva brand kit
    # → Shopify → the site), then reviewed and APPROVED by the owner, whose
    # edits win. `theme_proposed` is the deriver's latest output with per-field
    # provenance, awaiting that review — NOTHING renders with it. A NULL/empty
    # value means "never derived / never approved", which is the true state of
    # every pre-existing row, so the migration needs no backfill.
    theme = Column(JSON, default=dict)
    theme_proposed = Column(JSON, default=dict)
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


class KbClaim(_Provenance, Base):
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
    #: WHO THE READER IS TOLD SAID THIS. Distinct from `source`, which is
    #: internal provenance ("captured", "stated on https://…", "shopify") and
    #: must never be shown to a customer.
    #:
    #: There was no such field, and a pull-quote block therefore had nowhere
    #: honest to get a credit line from — so the drafter was asked for one and
    #: supplied "Eien Health Research", an organisation that does not exist,
    #: under a real statement in a live email (2026-08-22). The lesson is not
    #: "tell the model not to invent attributions": a generator asked for a
    #: field it cannot know will always fill it plausibly. The field has to
    #: exist and be human-owned.
    #:
    #: Empty for ordinary brand claims — those are the brand's own assertions
    #: and need no credit. Filled for a testimonial, where PROOF_USAGE already
    #: requires attribution and the words are the evidence.
    attributed_to = Column(Text, default="")
    situations = Column(JSON, default=list)     # tags the assembler matches on
    # Which entity this is true OF. Blank = true of the brand, usable anywhere.
    # A product FAQ answer, a dimension, a line of product copy — all real, all
    # only sayable in content that references that product. Without this column
    # the choice was to flatten them into brand claims (which produced
    # "Dedicated to cultural innovators … O 13 cm, H 5.5 cm") or discard them.
    entity_key = Column(String, default="", index=True)
    # The one model-WRITTEN field on this table. Everything else is either
    # copied verbatim from the source or chosen by a human; `proves` is a
    # one-line interpretation of what the claim demonstrates, proposed at
    # extraction and frozen by approval like any other editorial field. It is
    # never asserted to a customer — it exists so selection and drafting know
    # what a number is FOR. Empty on every pre-existing row, which is correct:
    # nobody has interpreted those yet.
    proves = Column(Text, default="")
    # Verbatim text from NEAR the claim on the page — the heading it sat under,
    # the sentence beside it — that makes the span mean anything.
    # "1,652 residential & hotel units" is not a claim about anything until you
    # know it is the Opus Communities development. The span rule kept evidence
    # inside the claim's own sentence, so that fact was unrecordable: the name
    # is in the block above, and a verbatim check against the span alone threw
    # it away. Selected like every other span and verified against the page.
    context = Column(Text, default="")
    strength = Column(String, default="strong") # strong | supporting — caps how many per asset
    verified_at = Column(DateTime(timezone=True))
    expires_at = Column(DateTime(timezone=True))  # stale claims stop being selectable
    #: "" (expires on the default interval) | "never" (someone said it is timeless)
    #:
    #: Owner's rule: claims expire BY DEFAULT, and only an explicit decision
    #: makes one permanent. The default is the empty string rather than
    #: "dated", because auto-migration writes a column default onto every
    #: existing row and a value nobody chose must not read as a value somebody
    #: did -- the same reason `origin` and `review` have no default. Empty here
    #: means "expires, on the usual interval"; it never means "unknown".
    expiry_policy = Column(String, default="")
    status = Column(String, default="active")   # active | retired | conflicted


class KbAudience(_Provenance, Base):
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
    source = Column(Text)                       # where this segment came from


class KbObjection(_Provenance, Base):
    """Why a deal stalls, and the approved answer.

    Empty across all four client accounts at audit time. Cannot be machine-
    populated — this is human-authored, and it's half of the paid intake.
    """

    __tablename__ = "kb_objections"

    id = Column(String, primary_key=True, default=_uuid)
    tenant = Column(String, nullable=False, index=True)
    objection = Column(Text, nullable=False)
    response = Column(Text, nullable=False)
    # The join to everything else. A claim carries situations and an objection
    # did not, so selection could match proof to a buyer's problem and could
    # only match objections by word overlap against whatever they happened to
    # type. Sharing the vocabulary makes "which objection fits this situation"
    # and "which claims support this objection" the same query.
    #
    # EMPTY MEANS UNIVERSAL, deliberately — the same convention `audience_key`
    # already uses. An objection nobody has tagged still applies everywhere,
    # so adding this column cannot silently retire the ones already on file.
    situations = Column(JSON, default=list)
    claim_id = Column(String)                   # optional proof to pair with it
    audience_key = Column(String)               # blank = applies to everyone
    # Blank = applies to the brand. Set = only when writing about that entity.
    # A product FAQ is exactly an objection with its approved answer, which is
    # why this is the one place objections can be derived rather than authored.
    entity_key = Column(String, default="", index=True)
    escalate = Column(String, default="no")     # yes -> hand to a human, don't answer
    source = Column(Text)                       # where this objection came from


class _SituationNeedsMixin:
    """Declared live-data requirements for a situation.

    Some questions can never be answered from a knowledge base, however well
    filled. "Where is my order" is not a claim, an objection or an entity — it
    is a fact that exists in Shopify at the moment of asking, and a layer that
    refuses it is as wrong as one that invents an answer.

    So a situation declares what it needs looked up, as data, per tenant. That
    keeps the routing deterministic — the caller is TOLD which tool to call and
    which parameters it takes, rather than an agent guessing from the sentence
    — and it keeps `blocked_on` honest by separating "nobody has authored this"
    (fix: write it) from "this needs a lookup" (fix: call the tool).

    `[{"tool": "shopify_order", "params": ["order_number"], "why": "..."}]`
    """

    needs = Column(JSON, default=list)


class KbSituation(_SituationNeedsMixin, _Provenance, Base):
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
    source = Column(Text)                     # where this tag came from


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
    __table_args__ = (UniqueConstraint("tenant", "provider", "site",
                                       name="uq_credential_tenant_provider_site"),)

    id = Column(String, primary_key=True, default=_uuid)
    tenant = Column(String, nullable=False, index=True)
    provider = Column(String, nullable=False)   # google | shopify | omnisend | ...
    # WHICH property this credential opens, for providers where one client has
    # more than one. Ironside's main site is Squarespace and its landing pages
    # are WordPress; another client may have two WordPress installs. One row per
    # (tenant, provider) could only ever hold one of them, so the second was
    # unconnectable and the page said nothing about why.
    #
    # "" means "the client's single one", which is what every existing row is
    # and what a provider like Shopify or Klaviyo always is.
    site = Column(String, default="", index=True)
    kind = Column(String, default="api_key")    # api_key | oauth
    secret = Column(Text)                       # Fernet ciphertext — never rendered
    meta = Column(JSON, default=dict)           # non-secret: store domain, from_name…
    scopes = Column(Text, default="")
    status = Column(String, default="active")   # active | failed | revoked
    granted_by = Column(String, default="")     # label from the connect link
    granted_at = Column(DateTime(timezone=True), default=utcnow)
    last_verified = Column(DateTime(timezone=True))
    last_error = Column(Text, default="")


class HarvestedPage(Base):
    """One page of a client's site, and the state it was in when last read.

    Without this the crawl had no memory. `discover_pages` returns the site in
    a stable order and the loop took the first N, so a re-run re-read the same
    first N — Baci has 400 pages in its sitemap and every run read the same 40,
    paying a model call each time to be told the claims were already on file.
    Same shape as the sent-mail cursor, and the same fix: record what has been
    read so a later run can move past it.

    `content_hash` is over the extracted text blocks, not the raw HTML — a
    changed analytics tag or cache-buster is not a changed claim, and hashing
    the markup would re-read the whole site on every deploy of their theme.
    """

    __tablename__ = "harvested_pages"
    __table_args__ = (UniqueConstraint("tenant", "url",
                                       name="uq_harvested_page_tenant_url"),)

    id = Column(String, primary_key=True, default=_uuid)
    tenant = Column(String, nullable=False, index=True)
    url = Column(Text, nullable=False)
    content_hash = Column(String)
    read_at = Column(DateTime(timezone=True), default=utcnow)
    claims_found = Column(Integer, default=0)
    truncated = Column(String, default="")   # "yes" when the reply hit the cap


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


class KbEmbedding(Base):
    """One vector for one row, whatever kind of row it is.

    Polymorphic on purpose, for the same reason `KbEntity` absorbs products,
    venues and slabs: making a new type searchable should be zero schema
    change. `kind` is 'claim' | 'objection' | 'situation' | 'entity' | 'media',
    and adding the sixth is a string, not a migration.

    `text_hash` is what stops every harvest re-paying for the whole corpus. The
    vector is only recomputed when the text behind it actually changed.

    `vector` is JSON rather than a pgvector column, deliberately and for now.
    Brute-force cosine over a few thousand rows is milliseconds and needs no
    extension, no cluster and no second source of truth. The storage seam lives
    in `embed.Backend`, so pgvector or a search cluster becomes a backend swap
    when a measured number says so — not a bet placed before there was one.

    `model` and `dims` are stored per row because a model change invalidates
    comparison: cosine between vectors from two different models is a number
    with no meaning, and the alternative to recording it is computing one.
    """

    __tablename__ = "kb_embeddings"
    __table_args__ = (UniqueConstraint("tenant", "kind", "row_id",
                                       name="uq_embedding_tenant_kind_row"),)

    id = Column(String, primary_key=True, default=_uuid)
    tenant = Column(String, nullable=False, index=True)
    kind = Column(String, nullable=False, index=True)
    row_id = Column(String, nullable=False, index=True)

    model = Column(String, default="")
    dims = Column(Integer, default=0)
    text_hash = Column(String, default="", index=True)
    vector = Column(JSON, default=list)

    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow)


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


class KbConflict(Base):
    """Two sources disagree about an approved value. Both are kept; neither wins.

    Coverings' Bio-Glass Emerald Forest is the case this exists for: the master
    sheet says the slab is 100"x56" and the cut sheet says 110"x49". One of
    those loses a specification. No precedence rule can tell you which, because
    the information needed to decide is not in either source — so the row keeps
    what a human approved, the disagreement becomes a visible piece of work, and
    nothing downstream quotes a dimension the system guessed at.

    Aggregated per (row, field) while open: a nightly sync that keeps
    disagreeing raises `hits`, it does not fill a queue.
    """

    __tablename__ = "kb_conflicts"

    id = Column(String, primary_key=True, default=_uuid)
    tenant = Column(String, nullable=False, index=True)
    table_name = Column(String, nullable=False)   # kb_claims | kb_entities | ...
    row_id = Column(String, nullable=False)
    field = Column(String, nullable=False)
    approved_value = Column(Text)                 # what the human signed off on
    incoming_value = Column(Text)                 # what the machine now says
    origin = Column(String)                       # which source disagreed
    source_ref = Column(Text)                     # the URL / file+row it came from
    hits = Column(String, default="1")
    status = Column(String, default="open")       # open | resolved
    resolution = Column(String, default="")       # approved | incoming
    first_seen = Column(DateTime(timezone=True), default=utcnow)
    last_seen = Column(DateTime(timezone=True), default=utcnow)
    resolved_at = Column(DateTime(timezone=True))


class KbEntity(_Provenance, Base):
    """The polymorphic thing being sold.

    One table absorbs agency offers, Baci products, Ironside spaces and
    Coverings slabs. `attributes` is the typed bag; `source`/`verified_at`
    exist because B2B spec sales needs provenance (a wrong dimension loses
    the job) even though the other tenants never populate them.
    """

    __tablename__ = "kb_entities"

    id = Column(String, primary_key=True, default=_uuid)
    tenant = Column(String, nullable=False, index=True)
    type = Column(String, nullable=False)       # offer|product|space|service|program|collection
    key = Column(String, nullable=False)        # stable slug / SKU
    name = Column(String, nullable=False)
    # The groups this belongs to — other KbEntity keys, usually
    # `type="collection"`. It exists so a fact true of a whole range can be
    # said once instead of once per member.
    #
    # Claim scope used to be binary: one entity, or the whole brand. "Every
    # Aqua pitcher is acrylic" could then only be filed once per pitcher, which
    # is why a mass harvest leaves a dozen rows saying one thing — the schema
    # had no way to express what was actually true. Brand-wide was not an
    # option either, because the porcelain lines are not acrylic.
    #
    # A LIST, not one key, because a catalogue groups along several independent
    # axes at once and different facts hang off different ones. Baci's own
    # collections are the proof: a white Aqua pitcher is in `aqua` (its design
    # range), `acrylics-polycarbonate` (its material) and
    # `italian-pitchers-carafes` (its type). The material claim belongs to the
    # material group and the palette claim to the range, so a single parent
    # would force choosing which kind of fact can be said once.
    parent_keys = Column(JSON, default=list)
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

class KbAsset(_Provenance, Base):
    """A creative asset — something the brand may publish, or may only look at.

    `rights` is the axis that matters and it is not a label, it is a gate. A
    competitor's ad saved for inspiration and a photograph the client owns are
    the same shape: a URL, a thumbnail, some tags. Nothing about the row itself
    tells them apart, so if convention is the only thing keeping the first out
    of a published ad, it will eventually go out in one — the §1 pattern
    (*unknown collapsed into a value*) with a legal bill attached.

    So, like `review`, it has **no column default**. Every read treats anything
    that is not exactly `owned` as not publishable, which means a row created
    without an explicit answer is inspiration, not inventory. Auto-migration
    stamping a default across existing rows is exactly what must not happen
    here.

    `uses` and `outcome` are the two feedback signals. Publishing an output
    marks the assets behind it used; performance recorded against the channel
    lands in `outcome`. Together they answer "what actually worked", which is
    the only question that makes a creative library worth keeping.
    """

    __tablename__ = "kb_assets"

    id = Column(String, primary_key=True, default=_uuid)
    tenant = Column(String, nullable=False, index=True)
    kind = Column(String, default="image")     # image | video | design
    # WHAT the asset depicts, which decides how it can be used — and it does
    # not generalise from one client to the next. Baci sells objects with a
    # silhouette, Coverings sells surfaces, Ironside sells places. A cutout
    # treatment is right for the first, meaningless for the second (a tile IS
    # the surface, you do not stand it on a table) and impossible for the third
    # (you cannot cut out a room). Storing it stops the pipeline guessing.
    #   object  — a discrete thing, usually with transparency
    #   surface — a material or texture: tile, stone, fabric, finish
    #   scene   — a place or an installed context, photographed as-is
    subject = Column(String, default="", index=True)
    # owned = the client's to publish. reference = inspiration only, never
    # output. No default: absent means reference, which is the safe reading.
    rights = Column(String, index=True)
    title = Column(String)
    url = Column(Text)                         # where the pixels live
    thumbnail_url = Column(Text)
    canva_design_id = Column(String)           # the editable handle, if any
    source = Column(Text)                      # "generated", "competitor: X"…
    prompt = Column(Text)                      # what produced it, if generated
    derived_from = Column(JSON, default=list)  # asset ids used as inspiration
    tags = Column(JSON, default=list)          # ["on-white", "lifestyle"]
    entity_key = Column(String, default="")    # what it depicts, if anything
    uses = Column(String, default="0")         # times published
    last_used_at = Column(DateTime(timezone=True))
    outcome = Column(JSON, default=dict)       # {"meta": {"roas": …}, …}
    status = Column(String, default="active")  # active | retired
    created_at = Column(DateTime(timezone=True), default=utcnow)


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
    # brief | draft | validated | approved | sent | escalated | skipped |
    # not_built | blocked | failed
    #
    # The distinctions are load-bearing, and collapsing them is how a system
    # reports its best work as failure. The owner caught exactly that: every
    # fraud alert and MFA warning the mail path correctly routed to him was
    # being listed as a "blocked" run — the design working, filed as a problem.
    #
    #   sent/approved  produced something
    #   escalated      routed to a PERSON on purpose. Success, not a refusal:
    #                  "a human must act on this" is the correct outcome for a
    #                  carding attack or a verification deadline.
    #   skipped        correctly produced nothing (promo, notifications)
    #   draft          waiting on a person, not finished
    #   not_built      the system is ready and its generator does not exist
    #                  yet. OUR roadmap, not the account's gap — it must never
    #                  reach `blocked_reasons()`, which ranks what to go and
    #                  WRITE, and which it would otherwise dominate for ever.
    #   blocked        could not produce; something nameable is missing
    #   failed         raised
    #
    # A PROBLEM is only ever `failed`, or `blocked` — a response was required
    # and did not happen. Everything above them is the system working.
    stage = Column(String, default="brief")
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


# Uniqueness that has been regraded. Each entry is
# (table, the columns the OLD constraint covered, new name, new columns).
#
# The old side is a tuple rather than one column name because the credential
# regrade widens a constraint that was already composite — (tenant, provider)
# becoming (tenant, provider, site). Written as a single column, that entry
# would never match and the old constraint would survive, which surfaces as an
# IntegrityError the first time a client connects their second WordPress site.
_REGRADED_UNIQUES = (
    ("contacts", ("email",), "uq_contact_tenant_email", ("tenant", "email")),
    ("shipments", ("name",), "uq_shipment_tenant_name", ("tenant", "name")),
    ("rfqs", ("shipment_name",), "uq_rfq_tenant_shipment",
     ("tenant", "shipment_name")),
    ("credentials", ("tenant", "provider"), "uq_credential_tenant_provider_site",
     ("tenant", "provider", "site")),
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
        for table, old_cols, new_name, new_cols in _REGRADED_UNIQUES:
            if table not in tables:
                continue
            have = {c["name"] for c in insp.get_columns(table)}
            if not set(new_cols) <= have:
                continue  # tenant column not added yet; next startup will catch it
            existing = {u["name"]: u.get("column_names") or []
                        for u in insp.get_unique_constraints(table)}
            for name, cols in existing.items():
                if list(cols) == list(old_cols) and name != new_name:
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
    _auto_index()


def _auto_index() -> None:
    """Create any model index missing from an existing table.

    The sibling of `_auto_migrate`, and needed for the same reason one level
    down. `create_all` builds indexes for tables it creates and never touches
    ones it finds, and `_auto_migrate` adds columns without them — so marking an
    EXISTING column `index=True` changed nothing in production. The declaration
    read as done, the query stayed a sequential scan, and the only place the
    difference showed was a latency nobody was measuring.

    `IF NOT EXISTS` rather than a catalogue diff: the names come from the
    model, so re-running this is free, and an index somebody added by hand
    under our name is left exactly where it is.

    Unlike `_regrade_uniques` this does NOT skip non-Postgres. `CREATE INDEX IF
    NOT EXISTS` is the same statement in SQLite, and every suite runs on SQLite
    — a migration that returns immediately under test is a migration whose only
    execution is in production.
    """
    from sqlalchemy import inspect as sa_inspect, text

    insp = sa_inspect(engine)
    existing_tables = set(insp.get_table_names())
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            have = {i["name"] for i in insp.get_indexes(table.name)}
            cols = {c["name"] for c in insp.get_columns(table.name)}
            for ix in table.indexes:
                names = [c.name for c in ix.columns]
                if ix.name in have or not set(names) <= cols:
                    continue
                target = ", ".join(f'"{c}"' for c in names)
                try:
                    conn.execute(text(
                        f'CREATE INDEX IF NOT EXISTS "{ix.name}" '
                        f'ON "{table.name}" ({target})'))
                except Exception:  # noqa: BLE001 — dialect quirk / raced
                    pass


def _backfill_provenance() -> None:
    """Give existing KB rows the provenance the new columns expect.

    Auto-migration adds columns and never values, so without this every row
    already in production would carry an empty origin and no fingerprint —
    which means no dedupe, and a review queue that cannot tell a crawled
    proposal from something the owner wrote himself.

    Two jobs:

    1. **Consolidate the review axis.** `KbClaim.status` used to carry both the
       lifecycle (active / retired) and the approval state (pending), so the
       same question had two answers depending on which column you read. Review
       now owns approval and status owns lifecycle. A claim that was `pending`
       becomes `proposed` and goes back to being lifecycle-active.

    2. **Fingerprint what is already there**, so the first re-crawl or re-upload
       after this ships collapses onto the existing row instead of duplicating
       it.

    Runs **once**, behind a marker. Not for speed: `review` has no column
    default so that a row written without one is treated as unapproved, and a
    backfill that ran on every boot would keep promoting exactly those rows to
    approved — turning the fail-closed default back into a fail-open one.
    """
    from . import provenance as prov

    MARKER = "kb_provenance_backfilled"
    with SessionLocal() as s:
        if s.get(Setting, MARKER):
            return

    def _origin_from(source: str, default: str) -> str:
        """Read the old free-text `source` back into a structured origin.

        Prefix matches and one exact match, never a substring search: a claim
        sourced "Baci Milano USA — verified in Shopify" was established by a
        human who checked the store, and calling that a store sync would hand
        the catalogue sync ownership of a row it never wrote.
        """
        s = (source or "").strip().lower()
        if s.startswith("stated on http") or s.startswith("review on"):
            return "crawl"
        if s.startswith("submitted by"):
            return "client"
        if s == "shopify":
            return "store_sync"
        return default

    with SessionLocal() as s:
        # --- claims: the one table where status carried two meanings --------
        for row in s.query(KbClaim).all():
            if row.status == "pending":
                row.review, row.status = prov.PROPOSED, "active"
            elif row.status in ("retired", "conflicted"):
                row.review = prov.REJECTED
            elif not row.review:
                row.review = prov.APPROVED
            if not row.origin:
                row.origin = _origin_from(row.source, "seed")
            if not row.fingerprint:
                row.fingerprint = prov.fingerprint(row.claim)

        for row in s.query(KbEntity).all():
            if not row.review:
                row.review = prov.APPROVED
            if not row.origin:
                row.origin = _origin_from(row.source, "seed")
            if not row.fingerprint:
                row.fingerprint = prov.fingerprint(row.key)

        # These three had no provenance at all and went live on write. Anything
        # already in them was put there by the seed or by Gomeh, so approved is
        # the honest reading — but it is recorded rather than assumed from now on.
        for model, fp in ((KbAudience, lambda r: prov.fingerprint(r.key)),
                          (KbObjection, lambda r: prov.fingerprint(r.objection)),
                          (KbSituation, lambda r: prov.fingerprint(r.tag))):
            for row in s.query(model).all():
                if not row.review:
                    row.review = prov.APPROVED
                if not row.origin:
                    row.origin = "seed"
                if not row.fingerprint:
                    row.fingerprint = fp(row)
        s.add(Setting(key=MARKER, value=utcnow().isoformat()))
        s.commit()


def init_db() -> None:
    Base.metadata.create_all(engine)
    try:
        _auto_migrate()
        _migrate_constraints()
    except Exception:  # noqa: BLE001 — never block startup on migration
        import logging
        logging.getLogger("db").exception("auto-migrate failed")
    try:
        _backfill_provenance()
    except Exception:  # noqa: BLE001 — a failed backfill must not block boot
        import logging
        logging.getLogger("db").exception("provenance backfill failed")
