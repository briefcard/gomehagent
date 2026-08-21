"""Brief assembler — the decision layer that runs BEFORE anything is drafted.

The old WhatsApp agent went `message arrives -> draft reply`, with nothing in
between. That is why its output was generic: it had the thread but not the
business state and not the decision. This module is the missing step.

Five stages, and only ONE of them calls a model:

    1. CLASSIFY  model  extract structure from free text
    2. ENRICH    code   what their own site and data say
    3. DIAGNOSE  rules  which situation tags apply
    4. SELECT    code   the proof that matches, from the KB
    5. DECIDE    code   the single ask

Selection is a query, not a judgement call. A model asked to "pick a relevant
case study" reaches for whichever number sounds most impressive; a query
filtered on situation tags returns the one that matches the buyer.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict

from . import config, kb

log = logging.getLogger("brief")

MAX_CLAIMS = 2   # never stack proof — two is persuasive, four is a pitch deck
MAX_MATCHES = 3  # options, not a catalogue dump


@dataclass
class Brief:
    tenant: str
    blocked: bool = False
    missing: list[str] = field(default_factory=list)

    # 1 classify
    contact_name: str = ""
    company: str = ""
    domain: str = ""
    source: str = ""            # inbound_form | referral | in_person | cold_reply
    stage: str = ""             # first_contact | follow_up | dormant | referral_intro
    audience_key: str = ""
    verbatim_ask: str = ""
    voiced_objection: str = ""
    requirements: dict = field(default_factory=dict)  # hard facts they stated

    # 2 enrich
    enrichment: dict = field(default_factory=dict)
    sources_ok: list[str] = field(default_factory=list)
    sources_failed: list[str] = field(default_factory=list)

    # 3 diagnose
    situations: list[str] = field(default_factory=list)
    constraint: str = ""

    # 4 select
    claims: list[dict] = field(default_factory=list)
    objection: dict = field(default_factory=dict)
    matches: list[dict] = field(default_factory=list)  # what they sell that fits
    unmet: list[str] = field(default_factory=list)     # nothing fits, and why

    # 5 decide
    offer: dict = field(default_factory=dict)
    ask: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# 1. CLASSIFY — the one model call. Extraction, not judgement.
# ---------------------------------------------------------------------------

_CLASSIFY_PROMPT = """You extract structure from an inbound business email. You do
not write, advise, or infer beyond what is stated.

Return ONLY a JSON object:
{
  "contact_name": "", "company": "", "domain": "bare domain or ''",
  "source": "inbound_form|referral|in_person|cold_reply",
  "stage": "first_contact|follow_up|dormant|referral_intro",
  "audience_key": "ecom_inventory|digital_products|local_venue|b2b_spec|unknown",
  "verbatim_ask": "one sentence, their words where possible",
  "voiced_objection": "an objection they actually raised, else ''",
  "keywords": ["salient nouns/phrases they used"],
  "requirements": {}
}

requirements: hard facts they STATED, as a flat object. Extract only what is
written — never estimate, round or infer. Use these keys when they apply:
  headcount   integer, number of people
  seated      true only if they said seated/dinner/banquet
  standing    true only if they said standing/reception/cocktail
  date        their words for when, e.g. "March", "Sept 14"
  budget      their words for money, e.g. "under $10k"
  quantity    integer, units of a product
Omit any key they did not state. An empty object is correct and expected.

audience_key guidance — pick "unknown" rather than guessing:
  ecom_inventory   sells physical product it stocks
  digital_products coaching, courses, info, software
  local_venue      venue, events, local service
  b2b_spec         distributor or manufacturer selling into trade/specification
"""


def classify(text: str, sender: str = "", model_fn=None) -> dict:
    """Extract structure. `model_fn` is injectable so tests run without API calls."""
    if model_fn is None:
        model_fn = _default_model
    raw = model_fn(_CLASSIFY_PROMPT, f"From: {sender}\n\n{text}")
    try:
        raw = raw[raw.find("{"):raw.rfind("}") + 1]
        out = json.loads(raw)
    except Exception:  # noqa: BLE001
        log.warning("classify: unparseable model output")
        out = {}
    out.setdefault("keywords", [])
    reqs = out.get("requirements")
    out["requirements"] = reqs if isinstance(reqs, dict) else {}
    if out.get("audience_key") == "unknown":
        out["audience_key"] = ""
    if not out.get("domain") and "@" in sender:
        dom = sender.split("@")[-1].strip("> ").lower()
        if dom not in ("gmail.com", "outlook.com", "yahoo.com", "hotmail.com",
                       "icloud.com", "example.com", "example.org", "test.com"):
            out["domain"] = dom
    return out


def _default_model(system: str, user: str) -> str:
    """The classifier's model call. Returns "" when it could not be made.

    `classify` already treats unparseable output as an empty classification, so
    "" degrades exactly the way junk output does. What was missing is the
    REASON: a spend limit and a model writing prose both produced an empty
    dict, and only one of those is fixed in a billing console. The gateway
    classifies it and it is logged here rather than discarded.
    """
    from . import llm
    r = llm.ask("brief_classify", user, system=system, max_tokens=800)
    if not r.ok:
        log.warning("classify: no model output — %s", r.error or r.degraded)
        return ""
    return r.text.strip().strip("`")


# ---------------------------------------------------------------------------
# 2. ENRICH — code only. Every signal is independently optional; what failed is
# recorded rather than silently treated as absent, because "no ads running" and
# "we couldn't check for ads" lead to different emails.
# ---------------------------------------------------------------------------

def _signal_site(domain: str) -> dict:
    """Platform + owned-channel signals, straight off their homepage."""
    import httpx
    r = httpx.get(f"https://{domain}", timeout=12, follow_redirects=True,
                  headers={"User-Agent": "Mozilla/5.0 (compatible; research)"})
    html = r.text
    low = html.lower()
    platform = "unknown"
    for name, marker in (("shopify", "cdn.shopify.com"),
                         ("squarespace", "squarespace"),
                         ("wordpress", "wp-content"),
                         ("webflow", "webflow"),
                         ("wix", "wix.com"),
                         ("bigcommerce", "bigcommerce")):
        if marker in low:
            platform = name
            break
    esp = ""
    for name in ("klaviyo", "omnisend", "mailchimp", "attentive", "postscript"):
        if name in low:
            esp = name
            break
    return {
        "platform": platform,
        "esp_detected": esp,
        "has_email_capture": any(k in low for k in
                                 ("newsletter", "subscribe", "sign up for", "email-signup")),
        "has_blog": "/blog" in low,
    }


def _signal_semrush(domain: str) -> dict:
    from . import seo_tools
    if not config.SEMRUSH_API_KEY:
        raise RuntimeError("SEMRUSH_API_KEY not configured")
    raw = (seo_tools.semrush_domain_overview(domain) or "").strip()
    if not raw.startswith("{"):
        # The helper returns a human-readable error string on failure; treating
        # that as "no organic presence" would invent a diagnosis.
        raise RuntimeError(raw[:80] or "empty response")
    data = json.loads(raw)
    if not data:
        return {"organic_keywords": 0, "organic_traffic": 0, "visible": False}
    kw = int(float(data.get("Organic Keywords", 0) or 0))
    tr = int(float(data.get("Organic Traffic", 0) or 0))
    return {"organic_keywords": kw, "organic_traffic": tr, "visible": kw > 50}


# Registry so a missing integration degrades instead of breaking the pipeline.
SIGNALS = {"site": _signal_site, "semrush": _signal_semrush}


def enrich(domain: str) -> tuple[dict, list[str], list[str]]:
    out, ok, failed = {}, [], []
    if not domain:
        return out, ok, ["no domain to enrich from"]
    for name, fn in SIGNALS.items():
        try:
            out.update(fn(domain))
            ok.append(name)
        except Exception as exc:  # noqa: BLE001
            failed.append(f"{name}: {exc.__class__.__name__}")
    return out, ok, failed


# ---------------------------------------------------------------------------
# 3. DIAGNOSE — rules, deliberately. Debuggable, testable, and the reasoning is
# inspectable after the fact, which a model's wouldn't be.
# ---------------------------------------------------------------------------

# Things they said -> situations. Their words are evidence.
#
# Each entry is a list of PATTERNS; a pattern is a tuple of substrings that
# must ALL appear. Roots rather than whole phrases, because real prospects
# write "raising prices" not "raise prices" and "landing in spam" not
# "spam folder" — literal phrases silently missed both in testing.
_KEYWORD_SITUATIONS = {
    "margin_problem": [("margin",), ("profitab",), ("cogs",), ("landed cost",),
                       ("cost of goods",)],
    "pricing_fear": [("rais", "price"), ("pricing",), ("underpriced",),
                     ("too expensive",), ("price increas",), ("charge more",)],
    "ads_not_working": [("ads", "stopped"), ("roas",), ("cac",), ("cpa",),
                        ("ads", "not work"), ("ads", "aren't work"),
                        ("performance", "drop"), ("ads", "dying"),
                        ("acquisition", "cost")],
    "no_traffic": [("traffic",), ("seo",), ("rank",), ("visibilit",),
                   ("nobody finds",), ("not showing up",), ("invisible",)],
    "email_problems": [("spam",), ("deliverab",), ("open rate",), ("email list",),
                       ("inbox",), ("unsubscrib",)],
    "new_channel": [("affiliate",), ("new channel",), ("wholesale",),
                    ("expand into",), ("another channel",)],
    "us_market_entry": [("us market",), ("launch in the us",), ("enter the us",),
                        ("american market",)],
    "scaling": [("scale",), ("scaling",), ("grow",), ("next level",)],
    "team_exists": [("our team",), ("my team",), ("in-house",),
                    ("marketing manager",), ("our marketer",)],
    "wants_operator": [("hands on",), ("hands-on",), ("actually done it",),
                       ("operator",), ("run it yourself",)],
}


def _matches(blob: str, patterns: list[tuple]) -> bool:
    return any(all(part in blob for part in pat) for pat in patterns)


def diagnose(classified: dict, enriched: dict,
             sources_ok: list[str] | None = None,
             tenant: str = "") -> tuple[list[str], str]:
    """Which situations apply. Patterns come from the tenant's own vocabulary
    when it has authored one — the shared set below was written for the agency
    selling B2B services, and a venue enquiry matched none of it."""
    sits: set[str] = set()
    sources_ok = sources_ok or []

    if classified.get("audience_key"):
        sits.add(classified["audience_key"])

    blob = " ".join([classified.get("verbatim_ask", ""),
                     *classified.get("keywords", [])]).lower()
    patterns_by_tag = (kb.situation_patterns(tenant) if tenant else {}) \
        or _KEYWORD_SITUATIONS
    for sit, patterns in patterns_by_tag.items():
        if _matches(blob, patterns):
            sits.add(sit)

    if classified.get("voiced_objection"):
        sits.add("solo_operator_doubt")

    # Signals from their own data outrank anything they told us — but ONLY
    # from a source that actually answered. A page fetch that returned a
    # parking page or an error looks identical to a real site with no signup
    # form, and inferring "they have no owned channel" from that is a
    # fabricated diagnosis, not a thin one.
    if "semrush" in sources_ok and enriched.get("visible") is False:
        sits.add("no_traffic")
    if "site" in sources_ok:
        if enriched.get("platform") == "shopify" and \
                classified.get("audience_key") in ("", "ecom_inventory"):
            sits.add("ecom_dtc")
        # Requires a recognised platform: on an unidentifiable page the
        # absence of a signup form tells us nothing.
        if enriched.get("platform") != "unknown" and \
                enriched.get("has_email_capture") is False:
            sits.add("new_channel")

    # The headline constraint. A tenant with its own vocabulary states what each
    # situation means; the ladder below only applies to the shared default set,
    # whose tags a venue or a product brand will never carry.
    if tenant and patterns_by_tag is not _KEYWORD_SITUATIONS:
        descs = kb.situation_desc(tenant)
        for tag in sorted(sits):
            if descs.get(tag):
                return sorted(sits), descs[tag]
        return sorted(sits), ("unclear from available signals" if not sits
                              else f"stated: {', '.join(sorted(sits))}")

    if "margin_problem" in sits or "pricing_fear" in sits:
        constraint = "converting but margin is thin"
    elif "ads_not_working" in sits:
        constraint = "paid acquisition degrading"
    elif "no_traffic" in sits:
        constraint = "not visible — demand isn't reaching them"
    elif "email_problems" in sits:
        constraint = "owned channel is broken"
    elif "scaling" in sits:
        constraint = "working, needs a bigger engine"
    else:
        constraint = "unclear from available signals"

    return sorted(sits), constraint


# ---------------------------------------------------------------------------
# 4/5. SELECT + DECIDE — pure queries over the KB.
# ---------------------------------------------------------------------------

def _select(tenant: str, situations: list[str], audience_key: str,
            voiced: str) -> tuple[list[dict], dict]:
    rows = kb.claims(tenant, situations=situations, limit=MAX_CLAIMS)
    if not rows:  # nothing situation-matched — fall back to strongest overall
        rows = kb.claims(tenant, limit=1)
    picked = [{"id": r.id, "claim": r.claim, "evidence": r.evidence,
               "source": r.source} for r in rows]

    # Objections are ranked by the SAME situations the claims were selected on,
    # so the doubt that gets pre-empted is the one this buyer's problem actually
    # raises. `kb.objections` ranks rather than filters, so an untagged general
    # objection is still reachable.
    objs = kb.objections(tenant, audience_key, situations=situations)
    chosen: dict = {}
    if voiced:
        low = voiced.lower()
        for o in objs:
            if any(w in o.objection.lower() for w in low.split()[:6]):
                chosen = {"objection": o.objection, "response": o.response}
                break
    if not chosen and objs:
        # Nothing voiced: pre-empt the best-ranked one for this situation.
        #
        # This used to look for the literal string "how fast", which exists only
        # in the agency's seeded objections — so on Baci and Ironside it matched
        # nothing and the brief went out with no objection handled at all. Same
        # defect as the hardcoded `diagnostic` offer key, in the same function.
        o = objs[0]
        chosen = {"objection": o.objection, "response": o.response}

    # The proof that backs the answer, joined on the same vocabulary. An
    # objection answered with an assertion is an opinion; answered with a claim
    # that carries its evidence, it is an argument.
    if chosen:
        row = next((o for o in objs if o.objection == chosen["objection"]), None)
        support = kb.support_for(tenant, row)
        if support:
            chosen["support"] = [{"id": c.id, "claim": c.claim,
                                  "evidence": c.evidence} for c in support]
    return picked, chosen


def _decide(tenant: str, stage: str, has_signal: bool) -> tuple[dict, str]:
    """What to propose. Driven by the tenant's own next_steps, not by offer keys
    that only ever existed in the agency's catalogue.

    `has_signal` is true when we learned anything at all — enrichment succeeded
    or they stated a hard requirement. With nothing, a first contact gets a
    question rather than a pitch, which is the one piece of the old hardcoded
    logic worth keeping.
    """
    if stage == "first_contact" and not has_signal:
        step = kb.next_step_for(tenant, "cold")
        return {}, (step.get("ask") or "one qualifying question — not a pitch")

    step = kb.next_step_for(tenant, stage)
    if step:
        by_key = {e.key: e for e in kb.entities(tenant)}
        return _offer_dict(by_key.get(step.get("entity_key", ""))), \
            step.get("ask", "")

    # No configured next step. Say so rather than reaching for a key that
    # happens to exist in another tenant's catalogue.
    return {}, ""


def _offer_dict(o) -> dict:
    if not o:
        return {}
    return {"key": o.key, "name": o.name, "price": o.price,
            "description": o.description}


# ---------------------------------------------------------------------------
# assemble
# ---------------------------------------------------------------------------

def assemble(tenant: str, text: str, sender: str = "", model_fn=None) -> Brief:
    """Inbound email -> a decision. Blocks with named gaps rather than guessing."""
    ready = kb.completeness(tenant)
    if not ready["ready"]:
        return Brief(tenant=tenant, blocked=True, missing=ready["missing"])

    c = classify(text, sender, model_fn=model_fn)
    b = Brief(
        tenant=tenant,
        contact_name=c.get("contact_name", ""),
        company=c.get("company", ""),
        domain=c.get("domain", ""),
        source=c.get("source", ""),
        stage=c.get("stage", "first_contact"),
        audience_key=c.get("audience_key", ""),
        verbatim_ask=c.get("verbatim_ask", ""),
        voiced_objection=c.get("voiced_objection", ""),
    )

    b.requirements = c.get("requirements", {})
    b.enrichment, b.sources_ok, b.sources_failed = enrich(b.domain)
    b.situations, b.constraint = diagnose(c, b.enrichment, b.sources_ok, tenant)
    b.claims, b.objection = _select(tenant, b.situations, b.audience_key,
                                    b.voiced_objection)

    # What they asked for, matched against what this tenant actually sells.
    reqs = dict(b.requirements)
    reqs.setdefault("keywords", c.get("keywords", []))
    # Ranked over the WHOLE catalogue, then trimmed for the brief. Judging the
    # gaps on the trimmed list would miss any unknown that fell below the cut.
    ranked = kb.match_entities(tenant, reqs, limit=0)
    b.matches = ranked[:MAX_MATCHES]

    # `fits` is tri-state. Nothing satisfying a stated requirement is a real
    # answer worth surfacing — but only when something was actually checked;
    # a set of unknowns is not evidence that nothing fits.
    checked = [m for m in ranked if m.get("basis") == "requirement"]
    if checked and not any(m["fits"] is True for m in checked):
        b.unmet = [m["why"] for m in checked if m["fits"] is False]

    # Record the gaps only when they actually cost an answer. If four rooms
    # already fit, a fifth with no capacity recorded blocked nothing, and
    # counting it would bury the gaps that genuinely lose enquiries.
    if ranked and not any(m["fits"] is True for m in ranked):
        kb.record_unknowns(tenant, ranked, b.verbatim_ask)

    b.offer, b.ask = _decide(tenant, b.stage,
                             bool(b.enrichment or b.requirements))

    # A brief with no proof is a generic email waiting to happen — block it.
    if not b.claims:
        b.blocked = True
        b.missing.append("no claim matched and no fallback available")
    return b
