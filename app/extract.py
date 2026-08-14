"""Find the claims on a page — by selecting spans, never by writing text.

Why this is a model call when almost nothing else here is
--------------------------------------------------------
Deciding whether a sentence is a claim a business makes about itself is an
open-class semantic judgement. Measured across five real homepages, a "claim"
was any of: an origin ("Designed in Milan"), a material ("shatter-resistant
Melamine"), a provenance ("Original sections of the Berlin Wall, painted by
Thierry Noir"), a standard ("No PFAS. No seed oils."), an ownership fact
("every shop is independently owned"), a performance figure ("$6M to $20M in
18 months") or a scale figure ("stocked in 4 Four Seasons properties").

No finite feature set spans that. The hand-written version tried, and every
rule was a proxy that collided with real content: "carries a number" matched
`&#8217;` as 8217; "two measurements" read `$6M to $20M` as metres; "has a
verb" missed irregular past tense and dropped a seeded agency claim. Tightening
one rule always widened another. Recall on the Baci and Ironside homepages was
0% — every real claim on both pages was discarded, and the run reported
`"no number, so nothing to check": 77`, which reads as a fact about the site
rather than about the filter.

This is exactly the "ingest drafting" position that locked decision #1 reserves
for a model.

What makes it safe: the model selects, it does not write
-------------------------------------------------------
Every returned claim must be a VERBATIM substring of the block it came from,
and `_verify` checks that in code and discards anything that is not. That one
constraint does the heavy lifting:

  * Fabrication is not trusted-away, it is *checked*. A span that is not in the
    source never survives, whatever the model says about it.
  * Re-runs are stable. Same spans, same fingerprints, so `add_claim`'s dedupe
    collapses a second crawl instead of filling the queue with rephrasings.
  * The rule that a testimonial's wording IS its evidence holds automatically —
    nothing here can reword anything.
  * A reviewer checks a sentence against a URL, not a summary against a page.

Everything that protects the knowledge base stays deterministic and stays
AFTER this: banned-phrase enforcement, situation-tag validation against the
tenant's own vocabulary, fingerprint dedupe, `review="proposed"`, and a human
approving. The model cannot reintroduce a banned phrase, cannot invent a tag,
and cannot make anything selectable. It proposes; code disposes.

Decision #2 is untouched: no model validates a model anywhere in this path.
"""
from __future__ import annotations

import json
import re

from . import config, kb

# Enough context to judge, not enough to drown. Blocks are already stripped of
# nav, header and footer by `compliance.text_blocks`, which is both cheaper and
# more reliable than asking a model to ignore page furniture.
_MAX_BLOCKS = 60
_MAX_CHARS = 14000

PROOF_TYPES = ("data", "case_study", "certification", "spec", "testimonial")

_SYSTEM = """You extract claims from a company's own website for a knowledge \
base. You SELECT text; you never write it.

Return every span that is a claim the business makes about itself. A claim is \
any checkable assertion: origin, materials, standards, certifications, \
ownership, provenance, scale, performance, capability, or a customer's own \
words.

RULES, in order of importance:

1. Every `text` value MUST be copied EXACTLY from a block, character for \
character. Never paraphrase, summarise, join two blocks, fix a typo, or trim \
punctuation. A span that is not an exact substring is discarded and wasted.
2. One claim per span. Do not merge sentences.
3. Skip navigation, buttons, prices on their own, product-listing repetition, \
cookie and newsletter text, and headings that only restate the body.
4. Skip anything that is purely a specification value (dimensions, material \
name on its own) — those belong on the product record, not in the claim library.
5. `proof_type`:
   - "testimonial" for a customer's own words (first person, a review, a quote)
   - "data" for a figure the business states about itself
   - "case_study" for a named engagement or outcome
   - "certification" for a standard, accreditation or award
   - "spec" for a stated product property (material, durability, capacity)
6. `evidence` is the part of the SAME span that makes it checkable (the figure, \
the named party, the standard). Copy it verbatim from the span, or use "".
7. If the page is about one product and the claim is only true of that product, \
set `entity_scoped` true. A claim true of the whole brand is false.

Return ONLY a JSON array, no prose:
[{"text": "...", "proof_type": "...", "evidence": "...", "entity_scoped": bool}]
Return [] if the page makes no claims."""


def _context(tenant: str, url: str, entity_key: str = "") -> str:
    """What this account is, in its own words, so judgement is grounded."""
    b = kb.brand(tenant)
    bits = [f"Account: {tenant}", f"Page: {url}"]
    if b:
        if b.display_name:
            bits.append(f"Brand: {b.display_name}")
        if b.positioning:
            bits.append(f"Positioning: {b.positioning}")
        banned = list(b.banned_claims or [])
        if banned:
            # Advisory only. The enforcement is `harvest`'s deterministic check
            # after this returns — a prompt mostly obeys, a check always blocks,
            # and both is the standing pattern here.
            bits.append("This brand must never claim: " + ", ".join(banned[:30]))
    if entity_key:
        bits.append(f"This page is the product page for: {entity_key}")
    return "\n".join(bits)


def _verify(candidates: list[dict], blocks: list[str],
            entity_key: str = "") -> tuple[list[dict], list[str]]:
    """Keep only spans that genuinely appear in the source. Code, not trust.

    This is the guarantee. Whatever the model returned, a claim survives only
    if it is a real substring of a real block — so the pipeline cannot be made
    to assert something the page does not say, even by a model that ignores
    every instruction above.
    """
    kept, rejected = [], []
    norm = {" ".join(b.split()): b for b in blocks}
    joined = "\n".join(norm)
    for c in candidates:
        text = " ".join(str(c.get("text", "")).split())
        if not text:
            continue
        if text not in joined:
            rejected.append(text[:120])
            continue
        ptype = str(c.get("proof_type", "")).lower()
        if ptype not in PROOF_TYPES:
            ptype = "data"
        ev = " ".join(str(c.get("evidence", "") or "").split())
        if ev and ev not in text:
            ev = ""          # evidence must come from the span, not from air
        kept.append({
            "text": text,
            "proof_type": ptype,
            "evidence": ev,
            "entity_key": entity_key if c.get("entity_scoped") else "",
            "source": f"stated on {c.get('_url', '')}".strip(),
        })
    return kept, rejected


def _call(system: str, user: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    msg = client.messages.create(
        model=config.CLAUDE_MODEL, max_tokens=2000, temperature=0,
        system=system, messages=[{"role": "user", "content": user}],
    )
    try:
        from . import usage
        usage.log_usage("harvest_extract", config.CLAUDE_MODEL, msg)
    except Exception:  # noqa: BLE001 — never fail a crawl on accounting
        pass
    return msg.content[0].text.strip()


def _parse(raw: str) -> list[dict]:
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    start, end = raw.find("["), raw.rfind("]")
    if start < 0 or end < start:
        return []
    try:
        data = json.loads(raw[start:end + 1])
    except Exception:  # noqa: BLE001 — a malformed reply is not a crawl failure
        return []
    return [d for d in data if isinstance(d, dict)]


def available() -> bool:
    return bool(config.ANTHROPIC_API_KEY)


def extract(tenant: str, url: str, blocks: list[str],
            entity_key: str = "") -> dict:
    """Claims on one page, as verbatim spans.

    Returns `{"claims": [...], "rejected_not_verbatim": [...], "used": ...}`.
    `used` names what actually did the work, so a run can never quietly report
    a model's recall when it fell back to the regex floor.
    """
    blocks = [b for b in blocks if b and len(b) > 12][:_MAX_BLOCKS]
    if not blocks:
        return {"claims": [], "rejected_not_verbatim": [], "used": "none"}
    if not available():
        return {"claims": [], "rejected_not_verbatim": [], "used": "unavailable",
                "note": "ANTHROPIC_API_KEY is not set; harvest fell back to the "
                        "deterministic filter, which has known 0% recall on "
                        "qualitative claims."}

    body, total = [], 0
    for b in blocks:
        if total + len(b) > _MAX_CHARS:
            break
        body.append(b)
        total += len(b)

    user = (_context(tenant, url, entity_key) + "\n\nBLOCKS:\n"
            + "\n".join(f"- {b}" for b in body))
    try:
        raw = _call(_SYSTEM, user)
    except Exception as exc:  # noqa: BLE001
        return {"claims": [], "rejected_not_verbatim": [],
                "used": "error", "error": f"{exc.__class__.__name__}: {str(exc)[:160]}"}

    cands = [{**c, "_url": url} for c in _parse(raw)]
    kept, rejected = _verify(cands, body, entity_key)
    return {"claims": kept, "rejected_not_verbatim": rejected, "used": "model"}

_QA_SYSTEM = """You are reading one email exchange: a message a customer sent, and the reply the business sent back. You SELECT text; you never write it.

Return the OBJECTION and the ANSWER, if the exchange contains one.

An objection is the thing the customer actually wanted to know or was worried about — not their greeting, not their backstory, not their sign-off. An answer is the part of the reply that addresses it.

RULES:
1. `objection` MUST be an exact substring of the INBOUND message. `answer` MUST be an exact substring of the REPLY. Character for character, both of them. A span that is not an exact substring is discarded and wasted.
2. Return the SHORTEST span that carries the whole question, and the shortest that carries the whole answer. "Hi - is this dishwasher safe? I broke my last set." is wrong; "is this dishwasher safe?" is right.
3. Skip the exchange entirely if the customer asked nothing, if the reply does not answer, or if it is scheduling, chit-chat or an acknowledgement.
4. `general` is true when the answer would be just as correct for any customer asking the same thing, and false when it is specific to this order, this person or this date.

Return ONLY JSON, no prose:
{"objection": "...", "answer": "...", "general": bool}
Return {} if there is no reusable question-and-answer here."""


def extract_qa(tenant: str, inbound: str, reply: str, ref: str = "") -> dict:
    """The question a customer asked and the answer they were given.

    Both spans are verified against their own source — the objection must
    appear in the inbound message and the answer in the reply — so the pair
    cannot be a paraphrase of either, and cannot silently swap who said what.
    That last failure is the one worth engineering against: attributing a
    customer's words to the brand is exactly what `PROOF_USAGE` forbids
    everywhere else.

    Returns {} when there is no reusable pair, which is most exchanges.
    """
    inbound, reply = (inbound or "").strip(), (reply or "").strip()
    if not available() or len(inbound) < 15 or len(reply) < 25:
        return {}
    user = (f"INBOUND (what the customer sent):\n{inbound[:4000]}\n\n"
            f"REPLY (what the business sent back):\n{reply[:4000]}")
    try:
        raw = _call(_QA_SYSTEM, user)
    except Exception:  # noqa: BLE001 — one unreadable thread is not a failure
        return {}
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < start:
        return {}
    try:
        data = json.loads(raw[start:end + 1])
    except Exception:  # noqa: BLE001
        return {}

    q = " ".join(str(data.get("objection", "")).split())
    a = " ".join(str(data.get("answer", "")).split())
    if not q or not a:
        return {}
    # The guarantee. Each span must come from ITS OWN side of the exchange.
    if q not in " ".join(inbound.split()):
        return {"rejected": "objection is not in the inbound message"}
    if a not in " ".join(reply.split()):
        return {"rejected": "answer is not in the reply"}
    return {"objection": q, "answer": a, "general": bool(data.get("general")),
            "ref": ref}
