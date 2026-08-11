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

MAX_CLAIMS = 2  # never stack proof — two is persuasive, four is a pitch deck


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
  "keywords": ["salient nouns/phrases they used"]
}

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
    if out.get("audience_key") == "unknown":
        out["audience_key"] = ""
    if not out.get("domain") and "@" in sender:
        dom = sender.split("@")[-1].strip("> ").lower()
        if dom not in ("gmail.com", "outlook.com", "yahoo.com", "hotmail.com", "icloud.com"):
            out["domain"] = dom
    return out


def _default_model(system: str, user: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    msg = client.messages.create(
        model=config.CLAUDE_MODEL, max_tokens=800, system=system,
        messages=[{"role": "user", "content": user}],
    )
    return msg.content[0].text.strip().strip("`")


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
_KEYWORD_SITUATIONS = {
    "margin_problem": ("margin", "profitability", "profit", "cogs", "landed cost"),
    "pricing_fear": ("price increase", "raise prices", "pricing", "too expensive"),
    "ads_not_working": ("ads stopped", "roas", "cac", "ads aren't", "ads are not",
                        "performance dropped", "cpa"),
    "no_traffic": ("traffic", "seo", "not ranking", "visibility", "nobody finds"),
    "email_problems": ("deliverability", "spam folder", "open rate", "email list"),
    "new_channel": ("affiliate", "new channel", "wholesale", "expand into"),
    "us_market_entry": ("us market", "launch in the us", "enter the us"),
    "scaling": ("scale", "grow", "growth", "next level"),
    "team_exists": ("our team", "my team", "our marketing manager", "in-house"),
    "wants_operator": ("hands on", "someone who's done it", "operator"),
}


def diagnose(classified: dict, enriched: dict) -> tuple[list[str], str]:
    sits: set[str] = set()

    if classified.get("audience_key"):
        sits.add(classified["audience_key"])

    blob = " ".join([classified.get("verbatim_ask", ""),
                     *classified.get("keywords", [])]).lower()
    for sit, needles in _KEYWORD_SITUATIONS.items():
        if any(n in blob for n in needles):
            sits.add(sit)

    if classified.get("voiced_objection"):
        sits.add("solo_operator_doubt")

    # Signals from their own data outrank anything they told us.
    if enriched:
        if enriched.get("visible") is False:
            sits.add("no_traffic")
        if enriched.get("platform") == "shopify" and \
                classified.get("audience_key") in ("", "ecom_inventory"):
            sits.add("ecom_dtc")
        if enriched.get("has_email_capture") is False:
            sits.add("new_channel")

    # The single headline constraint, most-specific first.
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

    objs = kb.objections(tenant, audience_key)
    chosen: dict = {}
    if voiced:
        low = voiced.lower()
        for o in objs:
            if any(w in o.objection.lower() for w in low.split()[:6]):
                chosen = {"objection": o.objection, "response": o.response}
                break
    if not chosen:
        # Nothing voiced: pre-empt the one that actually kills these deals.
        for o in objs:
            if "how fast" in o.objection.lower():
                chosen = {"objection": o.objection, "response": o.response}
                break
    return picked, chosen


def _decide(tenant: str, stage: str, enriched: bool) -> tuple[dict, str]:
    offers = {e.key: e for e in kb.entities(tenant, "offer")}
    if stage == "referral_intro":
        o = offers.get("fractional_cmo")
        return _offer_dict(o), "a 25-minute call this week"
    if stage in ("follow_up", "dormant"):
        o = offers.get("diagnostic")
        return _offer_dict(o), "pick the thread back up with one specific next step"
    if not enriched:
        return {}, "one qualifying question — not a pitch"
    o = offers.get("diagnostic")
    return _offer_dict(o), "the paid diagnostic"


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

    b.enrichment, b.sources_ok, b.sources_failed = enrich(b.domain)
    b.situations, b.constraint = diagnose(c, b.enrichment)
    b.claims, b.objection = _select(tenant, b.situations, b.audience_key,
                                    b.voiced_objection)
    b.offer, b.ask = _decide(tenant, b.stage, bool(b.enrichment))

    # A brief with no proof is a generic email waiting to happen — block it.
    if not b.claims:
        b.blocked = True
        b.missing.append("no claim matched and no fallback available")
    return b
