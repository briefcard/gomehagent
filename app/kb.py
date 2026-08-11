"""Knowledge Base access + seeding.

Read side of the KB. Everything here is deterministic — no model calls. The
brief assembler queries through these functions, the validator enforces
against them, and generators are only ever handed what these return.

Rule that keeps the platform a platform: customisation lives in these rows,
never in forked code. A new tenant is new data, not a new module.
"""
from __future__ import annotations

import datetime as dt

from . import db

# Controlled situation vocabulary. Claims are tagged with these and the
# assembler matches on them, so proof selection is a query rather than a model
# picking whichever number sounds best.
SITUATIONS = {
    # who they are
    "ecom_dtc", "ecom_inventory", "digital_products", "coaching",
    "local_venue", "b2b_spec", "real_estate", "food_bev",
    # what's wrong
    "scaling", "margin_problem", "ads_not_working", "no_traffic",
    "pricing_fear", "email_problems", "new_channel", "us_market_entry",
    # what they doubt about you
    "team_exists", "solo_operator_doubt", "big_spender", "wants_operator",

    # Consumer- and trade-side situations. The set above was written for the
    # agency selling B2B services; a tableware brand's claims have nowhere to
    # live in it. These let product tenants tag proof at all.
    #
    # NOTE: the proper fix is a per-tenant vocabulary stored as data — a module
    # constant shared by every tenant is exactly the kind of customisation that
    # decision #3 says must not live in code. Tracked, not yet built.
    "gifting", "occasion_hosting", "collector", "replacement_reorder",
    "trade_specification", "wellness_routine", "subscription_lapse",
    "venue_enquiry", "capacity_fit",
}


# --------------------------------------------------------------------------
# Read accessors — the only way the pipeline touches the KB
# --------------------------------------------------------------------------

def brand(tenant: str) -> db.KbBrand | None:
    with db.SessionLocal() as s:
        return s.get(db.KbBrand, tenant)


def banned_claims(tenant: str) -> list[str]:
    b = brand(tenant)
    return list(b.banned_claims or []) if b else []


def claims(tenant: str, situations: list[str] | None = None,
           limit: int = 0) -> list[db.KbClaim]:
    """Active, unexpired claims, ranked by how well they fit the situation.

    Ranking is SPECIFICITY first, strength second. Sorting on strength alone
    ties every "strong" claim and breaks on insertion order — which had a
    prospect complaining about email deliverability being answered with a
    Shopify exit story. A claim matching two of the buyer's situations beats
    one matching a single situation, however impressive its number.
    """
    now = dt.datetime.now(dt.timezone.utc)
    want = set(situations or [])
    with db.SessionLocal() as s:
        rows = s.query(db.KbClaim).filter(
            db.KbClaim.tenant == tenant,
            db.KbClaim.status == "active",
        ).all()
        scored = []
        for r in rows:
            if r.expires_at and r.expires_at < now:
                continue  # stale proof is not selectable
            overlap = len(set(r.situations or []) & want)
            if want and not overlap:
                continue
            scored.append((-overlap, 0 if r.strength == "strong" else 1, r))
        scored.sort(key=lambda t: (t[0], t[1]))
        out = [r for _, _, r in scored]
        s.expunge_all()
        return out[:limit] if limit else out


def audiences(tenant: str) -> list[db.KbAudience]:
    with db.SessionLocal() as s:
        rows = s.query(db.KbAudience).filter(db.KbAudience.tenant == tenant).all()
        s.expunge_all()
        return rows


def audience(tenant: str, key: str) -> db.KbAudience | None:
    with db.SessionLocal() as s:
        row = s.query(db.KbAudience).filter(
            db.KbAudience.tenant == tenant, db.KbAudience.key == key).first()
        if row:
            s.expunge(row)
        return row


def objections(tenant: str, audience_key: str = "") -> list[db.KbObjection]:
    """All objections for a tenant; narrowed to a segment when one is given.

    No audience_key means "everything" — not "only the universal ones". The
    latter silently undercounts, which made completeness() report 5 of 6.
    """
    with db.SessionLocal() as s:
        rows = s.query(db.KbObjection).filter(db.KbObjection.tenant == tenant).all()
        if audience_key:
            rows = [r for r in rows
                    if not r.audience_key or r.audience_key == audience_key]
        s.expunge_all()
        return rows


def entities(tenant: str, type: str = "", available_only: bool = True
             ) -> list[db.KbEntity]:
    with db.SessionLocal() as s:
        q = s.query(db.KbEntity).filter(db.KbEntity.tenant == tenant,
                                        db.KbEntity.status == "active")
        if type:
            q = q.filter(db.KbEntity.type == type)
        rows = q.all()
        if available_only:
            rows = [r for r in rows if r.availability == "available"]
        s.expunge_all()
        return rows


# --------------------------------------------------------------------------
# Completeness — the KB audit, as code. The assembler calls this before
# building a brief so the pipeline blocks with a named field instead of
# inventing something (this is what stopped the Ironside quote).
# --------------------------------------------------------------------------

def completeness(tenant: str) -> dict:
    b = brand(tenant)
    missing: list[str] = []
    if not b:
        return {"tenant": tenant, "ready": False, "missing": ["kb_brand row"],
                "counts": {}}
    if not (b.voice or {}).get("tone"):
        missing.append("brand.voice.tone")
    if not b.banned_claims:
        missing.append("brand.banned_claims")
    counts = {
        "claims": len(claims(tenant)),
        "audiences": len(audiences(tenant)),
        "objections": len(objections(tenant)),
        "entities": len(entities(tenant, available_only=False)),
    }
    for name in ("claims", "audiences", "objections", "entities"):
        if counts[name] == 0:
            missing.append(f"kb_{name} (none)")
    return {"tenant": tenant, "ready": not missing,
            "missing": missing, "counts": counts}


# --------------------------------------------------------------------------
# Write side.
#
# Kept here rather than in a separate module so there is exactly one place that
# knows the shape of a KB row. Every writer normalises and validates before it
# commits — a claim with an unknown situation tag can never be selected, and an
# audience with no vocabulary is a row that makes the output worse, so both are
# refused at the door rather than stored and puzzled over later.
# --------------------------------------------------------------------------

def _split(text: str, sep: str = ";") -> list[str]:
    return [p.strip() for p in (text or "").split(sep) if p.strip()]


def ensure_brand(tenant: str, display_name: str = "") -> db.KbBrand:
    """Get the brand row, creating a bare one if this tenant has none yet.

    Without this every write to a fresh tenant would fail on a missing parent
    row, which is how a knowledge base ends up with claims and no voice.
    """
    with db.SessionLocal() as s:
        row = s.get(db.KbBrand, tenant)
        if not row:
            row = db.KbBrand(tenant=tenant,
                             display_name=display_name or tenant.title())
            s.add(row)
            s.commit()
        s.refresh(row)
        s.expunge(row)
        return row


def set_brand(tenant: str, **fields) -> str:
    """Update brand-level fields. `tone` is a convenience into voice.tone."""
    allowed = {"display_name", "positioning", "elevator", "voice",
               "banned_claims", "approval_policy"}
    tone = fields.pop("tone", None)
    bad = set(fields) - allowed
    if bad:
        return f"Unknown field(s): {sorted(bad)}"
    ensure_brand(tenant)
    with db.SessionLocal() as s:
        row = s.get(db.KbBrand, tenant)
        for k, v in fields.items():
            setattr(row, k, v)
        if tone is not None:
            voice = dict(row.voice or {})
            voice["tone"] = _split(tone, ",") or _split(tone, " ")
            row.voice = voice
        s.commit()
    return f"Updated {tenant} brand."


def add_banned(tenant: str, phrase: str) -> str:
    """Add a phrase the validator will reject. Creates the brand row if needed."""
    phrase = (phrase or "").strip()
    if not phrase:
        return "A rule needs a phrase."
    ensure_brand(tenant)
    with db.SessionLocal() as s:
        row = s.get(db.KbBrand, tenant)
        current = list(row.banned_claims or [])
        if phrase.lower() in [c.lower() for c in current]:
            return f"Already banned for {tenant}."
        row.banned_claims = current + [phrase]
        s.commit()
        n = len(row.banned_claims)
    return f"Banned for {tenant} ({n} rules): “{phrase}”"


def add_claim(tenant: str, claim: str, evidence: str, tags: list[str],
              proof_type: str = "case_study", source: str = "",
              strength: str = "strong") -> str:
    unknown = [t for t in tags if t not in SITUATIONS]
    if unknown:
        return (f"Unknown tags: {', '.join(unknown)}\n"
                f"Valid: {', '.join(sorted(SITUATIONS))}")
    if not tags:
        return "Needs at least one situation tag, or it can never be selected."
    with db.SessionLocal() as s:
        s.add(db.KbClaim(tenant=tenant, claim=claim, evidence=evidence,
                         proof_type=proof_type, source=source or "captured",
                         situations=tags, strength=strength,
                         verified_at=db.utcnow()))
        s.commit()
    return (f"Added to {tenant} ({len(claims(tenant))} claims).\n"
            f"{claim}\n{evidence}\ntags: {', '.join(tags)}")


def add_audience(tenant: str, key: str, name: str, pains: list[str],
                 vocabulary: list[str], buying_trigger: str = "",
                 decision_timeline: str = "") -> str:
    key = (key or "").strip().lower().replace(" ", "_")
    if not key or not name:
        return "An audience needs a key and a name."
    with db.SessionLocal() as s:
        existing = s.query(db.KbAudience).filter(
            db.KbAudience.tenant == tenant, db.KbAudience.key == key).first()
        row = existing or db.KbAudience(tenant=tenant, key=key)
        row.name, row.pains, row.vocabulary = name, pains, vocabulary
        if buying_trigger:
            row.buying_trigger = buying_trigger
        if decision_timeline:
            row.decision_timeline = decision_timeline
        if not existing:
            s.add(row)
        s.commit()
    return f"{'Updated' if existing else 'Added'} audience {key} for {tenant}."


def add_objection(tenant: str, objection: str, response: str,
                  audience_key: str = "", escalate: str = "no") -> str:
    if not objection or not response:
        return "An objection needs both the objection and the approved answer."
    with db.SessionLocal() as s:
        s.add(db.KbObjection(tenant=tenant, objection=objection,
                             response=response, audience_key=audience_key,
                             escalate=escalate))
        s.commit()
    return f"Added objection for {tenant} ({len(objections(tenant))} total)."


def add_entity(tenant: str, type: str, key: str, name: str,
               description: str = "", price: str = "",
               attributes: dict | None = None, source: str = "") -> str:
    key = (key or "").strip().lower().replace(" ", "-")
    if not key or not name:
        return "An entity needs a key and a name."
    with db.SessionLocal() as s:
        existing = s.query(db.KbEntity).filter(
            db.KbEntity.tenant == tenant, db.KbEntity.key == key).first()
        row = existing or db.KbEntity(tenant=tenant, key=key)
        row.type, row.name = type, name
        row.description = description or row.description
        row.price = price or row.price
        row.attributes = attributes if attributes is not None else (row.attributes or {})
        row.source = source or row.source or "captured"
        row.verified_at = db.utcnow()
        if not existing:
            s.add(row)
        s.commit()
    return f"{'Updated' if existing else 'Added'} {type} {key} for {tenant}."


# --------------------------------------------------------------------------
# Guided intake.
#
# The reason a knowledge base stays empty is never that writing to it is hard —
# it's that nobody remembers what's missing. These steps are ordered by what
# unblocks the most: a brand with no voice blocks every generator, while a
# fourth audience segment blocks nothing. `next_step` asks one question; the
# answer comes back as ordinary text and is parsed by code, not a model.
# --------------------------------------------------------------------------

INTAKE_STEPS = [
    dict(id="display_name", asks="brand",
         q="What is this brand called, exactly as it should appear in writing?",
         hint="Just the name."),
    dict(id="positioning", asks="brand",
         q="One sentence: what do they do, and for whom?",
         hint="Plain words, no tagline."),
    dict(id="tone", asks="brand",
         q="Three or four words for how they sound.",
         hint="e.g. direct, warm, unhurried, no hype"),
    dict(id="banned_claims", asks="brand",
         q="What must this brand NEVER claim? One per line or separated by semicolons.",
         hint="Origin, production method, guarantees, medical claims — anything "
              "that is a legal or brand risk. This becomes a hard rule."),
    dict(id="audience", asks="audience",
         q="Describe one buyer segment.",
         hint="key | name | pains (semicolons) | words they use (semicolons)"),
    dict(id="objection", asks="objection",
         q="What is one reason a deal stalls, and how do you answer it?",
         hint="objection | your approved answer"),
    dict(id="entity", asks="entity",
         q="Name one thing they sell.",
         hint="type | key | name | price | description   (type = offer|product|space|service)"),
    dict(id="claim", asks="claim",
         q="One thing this brand can prove, with the number.",
         hint="claim | evidence | situation tags (spaces)"),
]

_STEP = {s["id"]: s for s in INTAKE_STEPS}


def gaps(tenant: str) -> list[dict]:
    """Every intake step still unmet, in the order they should be answered."""
    b = brand(tenant)
    voice = (b.voice or {}) if b else {}
    have = {
        "display_name": bool(b and b.display_name and b.display_name != tenant.title()),
        "positioning": bool(b and b.positioning),
        "tone": bool(voice.get("tone")),
        "banned_claims": bool(b and b.banned_claims),
        "audience": len(audiences(tenant)) > 0,
        "objection": len(objections(tenant)) > 0,
        "entity": len(entities(tenant, available_only=False)) > 0,
        "claim": len(claims(tenant)) > 0,
    }
    return [s for s in INTAKE_STEPS if not have.get(s["id"])]


def next_step(tenant: str) -> dict | None:
    g = gaps(tenant)
    return g[0] if g else None


def apply_answer(tenant: str, step_id: str, text: str) -> str:
    """Route a free-text answer into the right table. Deterministic parsing —
    a model guessing which field a sentence belongs to is a silent-corruption
    machine, and the KB is the one place nothing may be silently wrong."""
    step = _STEP.get(step_id)
    text = (text or "").strip()
    if not step:
        return "That question expired — send /next for the current one."
    if not text:
        return "Nothing captured."

    # The scalar brand fields accept anything, which means an answer typed for a
    # different question lands as plausible-looking garbage — a pipe-formatted
    # objection became a four-word "voice" in testing. A pipe is never valid in
    # these, so treat it as a misrouted answer and say so.
    if step_id in ("display_name", "positioning", "tone") and "|" in text:
        return (f"That looks like an answer to a different question — "
                f"{_STEP[step_id]['hint']}. Send /next to see the current one.")

    if step_id == "display_name":
        return set_brand(tenant, display_name=text)
    if step_id == "positioning":
        return set_brand(tenant, positioning=text)
    if step_id == "tone":
        words = _split(text, ",") or _split(text, " ")
        if len(words) > 8:
            return ("Tone is three or four words, not a sentence — "
                    "e.g. direct, warm, unhurried.")
        return set_brand(tenant, tone=text)
    if step_id == "banned_claims":
        phrases = _split(text.replace("\n", ";"))
        return "\n".join(add_banned(tenant, p) for p in phrases) or "Nothing captured."

    parts = [p.strip() for p in text.split("|")]
    if step_id == "audience":
        if len(parts) < 4:
            return f"Format: {step['hint']}"
        return add_audience(tenant, parts[0], parts[1],
                            _split(parts[2]), _split(parts[3]))
    if step_id == "objection":
        if len(parts) < 2:
            return f"Format: {step['hint']}"
        return add_objection(tenant, parts[0], parts[1])
    if step_id == "entity":
        if len(parts) < 3:
            return f"Format: {step['hint']}"
        return add_entity(tenant, parts[0], parts[1], parts[2],
                          description=parts[4] if len(parts) > 4 else "",
                          price=parts[3] if len(parts) > 3 else "")
    if step_id == "claim":
        if len(parts) < 3:
            return f"Format: {step['hint']}"
        import re as _re
        tags = [t.strip().lower() for t in _re.split(r"[\s,]+", parts[2]) if t.strip()]
        return add_claim(tenant, parts[0], parts[1], tags)
    return "Unrecognised step."


# --------------------------------------------------------------------------
# Seed — MarketingThatWorks.co (tenant "agency"), tenant zero.
#
# Every claim below is from marketingthatworks.co or was established from live
# data in the platform-design work. Nothing invented: if a number isn't
# public or verifiable, it isn't here.
# --------------------------------------------------------------------------

_AGENCY_CLAIMS = [
    # (claim, evidence, proof_type, source, situations, strength)
    ("Took a coaching company from $6M to $20M as fractional CMO",
     "$6M → $20M in 18 months, $15M ad spend directed", "case_study",
     "marketingthatworks.co — Heartcore Business",
     ["coaching", "digital_products", "scaling", "big_spender"], "strong"),

    ("Built, scaled and sold my own Shopify brand, then ran the acquirer's portfolio",
     "Top 1% Shopify, sold to an aggregator; then $1M+/mo paid social across 8 brands",
     "case_study", "marketingthatworks.co — Miaroo",
     ["ecom_dtc", "wants_operator", "solo_operator_doubt", "big_spender"], "strong"),

    ("Directed $60M+ in ad spend across a decade",
     "$60M+", "data", "marketingthatworks.co",
     ["big_spender", "scaling"], "supporting"),

    ("Took a regional produce brand from $300k to $1M/year",
     "$300k → $1M", "case_study", "marketingthatworks.co — CV Harvest",
     ["ecom_dtc", "food_bev", "scaling", "no_traffic"], "strong"),

    ("Raised catalog pricing 28% with no drop in conversion",
     "3.5× → 4.5× landed cost across 224 variants, conversion rate held",
     "data", "Baci Milano USA — owner-operated, verified in Shopify",
     ["ecom_inventory", "margin_problem", "pricing_fear"], "strong"),

    ("Diagnosed an ad collapse that was actually a stockout",
     "In-season zodiac SKUs at 100% sell-through; sessions flat, conversion halved",
     "data", "Baci Milano USA — Meta + Shopify cross-check",
     ["ecom_inventory", "ads_not_working"], "strong"),

    ("Ran event-venue paid acquisition at 7×+ ROAS",
     "7×+ ROAS on event-planning campaigns", "data",
     "Miami Ironside — Google Ads + analytics, May 2026",
     ["local_venue", "ads_not_working"], "strong"),

    ("Built a brand's US market entry after several failed attempts",
     "Placements incl. Four Seasons and the Ritz-Carlton Yacht Collection",
     "case_study", "marketingthatworks.co — Baci Milano USA",
     ["us_market_entry", "ecom_inventory", "b2b_spec"], "strong"),

    ("Built an affiliate channel from zero",
     "0 → 100+ affiliates in a year; expansion into Australia and Dubai",
     "case_study", "marketingthatworks.co — Arabelle Yee",
     ["new_channel", "digital_products", "scaling"], "supporting"),

    ("Recovered a failing email programme on 1.2M contacts",
     "Domain reputation restored to High for the first time; IP reputation repaired",
     "case_study", "marketingthatworks.co — deliverability rescue",
     ["email_problems", "digital_products"], "strong"),

    ("Led marketing and sales teams of 30+",
     "30+ personnel", "data", "marketingthatworks.co",
     ["team_exists", "solo_operator_doubt"], "supporting"),

    ("Directed marketing for a 1,652-unit residential and hotel development",
     "1,652 units; $60M in sales generated for South Florida brokers",
     "case_study", "marketingthatworks.co — Opus Communities",
     ["real_estate", "local_venue"], "supporting"),
]

_AGENCY_AUDIENCES = [
    ("ecom_inventory", "E-commerce owner, $2–10M, carries stock",
     ["cash trapped in inventory", "SKUs that never sell",
      "ads that work then stop", "margin eaten by discounting"],
     ["ROAS", "AOV", "sell-through", "landed cost", "MOQ"],
     "A month where ads stopped working, or a cash squeeze from a bad buy",
     "2–6 weeks"),
    ("digital_products", "Coaching / info / digital products operator",
     ["launch-dependent revenue", "list fatigue", "no evergreen engine",
      "deliverability decay"],
     ["funnel", "launch", "list", "webinar", "LTV"],
     "A launch that underperformed the last one", "1–4 weeks"),
    ("local_venue", "Venue, events or local service business",
     ["inbound enquiries that go cold", "seasonality",
      "no idea which channel produced the booking"],
     ["bookings", "site visit", "walk-in", "per-head"],
     "A quiet quarter or a competitor taking known accounts", "2–8 weeks"),
    ("b2b_spec", "B2B distributor / specification sales",
     ["long cycles", "invisible in search", "samples that go nowhere",
      "reps buried in admin"],
     ["spec", "A&D", "trade", "sample", "project"],
     "Losing a specification they expected to win", "1–3 months"),
]

_AGENCY_OBJECTIONS = [
    ("You're one person — can you actually handle this?",
     "I've led marketing and sales teams of 30+ and directed $60M in spend. "
     "What you get from me is the strategic layer plus installed systems that "
     "keep running; execution capacity scales with a senior bench.",
     "", "no"),  # applies to every segment — audience_key takes AUDIENCE keys,
                 # not situation tags (solo_operator_doubt is a situation)
    ("We tried an agency before and it didn't work.",
     "Most agencies rent you attention and it leaves when the retainer does. "
     "The deliverable here is machinery you keep — documented, automated, and "
     "operated by your team after handoff.", "", "no"),
    ("How fast will we see results?",
     "Recovery first: something verifiable in your own data inside 2–4 weeks — "
     "spend recovered, demand you already paid for and dropped, or margin "
     "leaking per order. Growth work comes after that's banked.", "", "no"),
    ("Why wouldn't we just hire someone in-house?",
     "You should, eventually. A hire costs more, takes 3 months to ramp, and "
     "leaves with the knowledge. I build the system first so the hire inherits "
     "something instead of starting over.", "", "no"),
    ("AI content doesn't work / we tried it and it was generic.",
     "Agreed, and I'll tell you which parts genuinely don't work yet. What "
     "does work is grounded generation: systems that write from your real "
     "product data and rules, with a human approving before anything ships.",
     "", "no"),
    ("Can you guarantee a specific result?",
     "No, and anyone who does is selling you something. I'll show you the "
     "baseline, the measurement design, and the kill criteria before we start.",
     "", "yes"),
]

_AGENCY_OFFERS = [
    ("diagnostic", "Paid diagnostic",
     "2–3 weeks. Marketing audit, unit-economics model and a 90-day plan, "
     "delivered as a working session. Findings are verifiable in your own data.",
     {"duration": "2-3 weeks", "deliverable": "audit + model + 90-day plan"},
     "from $5,000"),
    ("fractional_cmo", "Fractional CMO retainer",
     "Defined operating rhythm — weekly leadership sync, monthly plan and "
     "review, quarterly reset — plus ownership of outcomes on one or two named "
     "channels and a capped execution allowance.",
     {"minimum_term": "6 months", "cadence": "weekly + monthly + quarterly",
      "execution": "capped allowance, overflow scoped separately"},
     "from $7,500/mo"),
    ("systems_install", "Systems install",
     "Fixed scope, fixed price. Ad-spend and inventory guard, catalog "
     "repricing, replenishment engine, content or response systems — built, "
     "run, and handed over with the operating manual.",
     {"pricing": "fixed", "handover": "documented + trained"},
     "scoped per build"),
]


def seed_agency(force: bool = False) -> dict:
    """Populate the `agency` tenant. Idempotent unless force=True."""
    tenant = "agency"
    with db.SessionLocal() as s:
        existing = s.get(db.KbBrand, tenant)
        if existing and not force:
            return {"status": "already seeded — pass force=True to overwrite"}
        if force:
            for model in (db.KbClaim, db.KbAudience, db.KbObjection, db.KbEntity):
                s.query(model).filter(model.tenant == tenant).delete()
            if existing:
                s.delete(existing)
            s.flush()

        s.add(db.KbBrand(
            tenant=tenant,
            display_name="MarketingThatWorks.co",
            positioning="Agentic performance marketing. Strategist and fractional "
                        "CMO who operates his own e-commerce brands, so the advice "
                        "comes with a P&L behind it.",
            elevator={
                "sentence": "I design and operate AI-driven acquisition systems "
                            "inside companies that want the upside without the headcount.",
                "paragraph": "A decade as CMO and fractional CMO across e-commerce, "
                             "coaching, real estate and luxury — $60M+ in ad spend "
                             "directed, teams of 30+ led, and brands of my own "
                             "including one sold while top 1% on Shopify. I don't "
                             "advise e-commerce brands from the outside; I run two.",
            },
            voice={
                "tone": ["direct", "specific", "operator-not-consultant",
                         "unhurried", "no hype"],
                "do_say": ["here's what I'd look at first", "in your own data",
                           "I run two of my own brands", "the number is"],
                "never_say": ["synergy", "leverage as a verb", "circle back",
                              "game-changer", "unlock your potential",
                              "in today's fast-paced world", "I hope this email finds you well"],
                "examples": [],  # filled from the edit diff once drafts start shipping
            },
            banned_claims=[
                # Promising outcomes is what creates the month-five conversation.
                "guarantee", "guaranteed results", "we guarantee",
                "risk-free", "double your revenue", "10x your",
                # Never assert a client metric that isn't already public.
                "confidential client",
            ],
            approval_policy={"auto_publish": [],
                             "requires_signoff": ["outbound_email", "proposal"]},
        ))

        for claim, ev, ptype, src, sits, strength in _AGENCY_CLAIMS:
            bad = set(sits) - SITUATIONS
            if bad:
                raise ValueError(f"unknown situation tags {bad} on claim {claim!r}")
            s.add(db.KbClaim(tenant=tenant, claim=claim, evidence=ev,
                             proof_type=ptype, source=src, situations=sits,
                             strength=strength, verified_at=db.utcnow()))

        for key, name, pains, vocab, trigger, timeline in _AGENCY_AUDIENCES:
            s.add(db.KbAudience(tenant=tenant, key=key, name=name, pains=pains,
                                vocabulary=vocab, buying_trigger=trigger,
                                decision_timeline=timeline))

        for obj, resp, aud, esc in _AGENCY_OBJECTIONS:
            s.add(db.KbObjection(tenant=tenant, objection=obj, response=resp,
                                 audience_key=aud, escalate=esc))

        for key, name, desc, attrs, price in _AGENCY_OFFERS:
            s.add(db.KbEntity(tenant=tenant, type="offer", key=key, name=name,
                              description=desc, attributes=attrs, price=price,
                              source="marketingthatworks.co", verified_at=db.utcnow()))
        s.commit()
    return {"status": "seeded", **completeness(tenant)}
