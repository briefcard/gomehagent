"""Gather claim candidates from a client's own site — as proposals, never facts.

The knowledge base is thin on every account and the material is sitting on their
websites. The temptation is to scrape it in. The reason not to is that a brand's
own marketing copy is where its banned phrases live, and passing a blocklist is
not the same as being true: "trusted by 500 restaurants" clears every one of
Baci's 24 rules and still has no evidence behind it.

`KbClaim` requires claim + evidence + proof_type + source. Scraped prose supplies
the first and none of the others. So nothing here is ever added as fact:

  * Candidates land as `status="pending"` — the same door client-submitted
    claims already use, invisible to selection until a human approves them.
  * Anything matching the account's `banned_claims` is dropped outright and
    never proposed. The brand banned it; a crawler does not get to reintroduce
    it through a review queue.
  * Situation tags come from matching the account's own `situation_patterns`.
    A candidate that matches none cannot be tagged, so it is REPORTED rather
    than stored with a guessed tag — `add_claim` refuses unknown tags and it is
    right to.

Reviews are the strongest source and the reason this is worth doing at all. A
review has real provenance: `proof_type="testimonial"`, a source that names
where it came from, and a claim phrased as what a customer said rather than what
the brand asserts about itself.
"""
from __future__ import annotations

import json
import re

from . import compliance, kb, tenants

_MIN, _MAX = 25, 240

# Boilerplate that appears on every page of every storefront. None of it is a
# claim, and all of it would otherwise pass a "contains a number" filter.
_NOISE = re.compile(
    r"free shipping|subscribe|newsletter|cookie|privacy|copyright|all rights"
    r"|add to cart|sold out|quantity|sign up|log in|©|terms of service"
    r"|returns? policy|use code|off your first", re.I)

# A claim worth proposing carries a number — that is what makes it checkable.
_HAS_NUMBER = re.compile(r"\d")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE.split(text or "") if s.strip()]


def _jsonld(html: str) -> list[dict]:
    """Every JSON-LD block on a page, flattened. Reviews live here.

    Review apps (Judge.me, Loox, Okendo, Yotpo) all emit structured data, so
    this is a real parse rather than a guess at markup — the difference between
    a testimonial with provenance and a sentence that looked like one.
    """
    out: list[dict] = []
    for block in re.findall(
            r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html or "",
            re.S | re.I):
        try:
            data = json.loads(block.strip())
        except Exception:  # noqa: BLE001 — malformed JSON-LD is common
            continue
        stack = [data]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, dict):
                out.append(item)
                stack.extend(v for v in item.values()
                             if isinstance(v, (dict, list)))
    return out


def _reviews_from(html: str, url: str) -> list[dict]:
    """Testimonials with attribution, from structured data only."""
    found = []
    for node in _jsonld(html):
        if str(node.get("@type", "")).lower() != "review":
            continue
        body = (node.get("reviewBody") or node.get("description") or "").strip()
        if not (_MIN <= len(body) <= _MAX * 3):
            continue
        author = node.get("author")
        if isinstance(author, dict):
            author = author.get("name", "")
        rating = node.get("reviewRating") or {}
        stars = rating.get("ratingValue") if isinstance(rating, dict) else ""
        found.append({
            "text": body[:_MAX * 3],
            "evidence": (f"{stars}-star review" if stars else "customer review")
                        + (f" from {author}" if author else ""),
            "proof_type": "testimonial",
            "source": f"review on {url}",
        })
    return found


def _claims_from(text: str, url: str) -> list[dict]:
    """Sentences that assert something checkable — i.e. that carry a number."""
    out = []
    for s in _sentences(text):
        if not (_MIN <= len(s) <= _MAX):
            continue
        if _NOISE.search(s) or not _HAS_NUMBER.search(s):
            continue
        out.append({"text": s, "evidence": "", "proof_type": "data",
                    "source": f"stated on {url}"})
    return out


def _tags_for(tenant: str, text: str) -> list[str]:
    """Situation tags this text matches, from the account's OWN vocabulary."""
    low = (text or "").lower()
    hits = []
    for tag, patterns in kb.situation_patterns(tenant).items():
        for pat in patterns:
            if all(str(word).lower() in low for word in pat):
                hits.append(tag)
                break
    return hits


def harvest(tenant: str, limit: int = 25, apply: bool = False) -> dict:
    """Read a client's site and propose what it finds. Writes nothing unless
    `apply` is set, and even then only as pending claims."""
    t = tenants.get(tenant)
    if not t:
        return {"error": f"unknown tenant {tenant!r}"}
    if not t.domain:
        return {"error": f"{tenant} has no domain recorded"}

    banned = [b.lower() for b in kb.banned_claims(tenant) if b]
    vocab = kb.situation_patterns(tenant)
    pages = compliance._sitemap_urls(t.domain, limit=max(limit * 3, 90))
    if not pages:
        return {"error": f"no sitemap found at {t.domain}"}

    # Claims already on file, so a repeat run does not re-propose the same line.
    known = {(c.claim or "").strip().lower()
             for c in kb.claims(tenant)} | {
        (c.claim or "").strip().lower() for c in kb.pending_claims(tenant)}

    proposed, rejected, untaggable = [], [], []
    import httpx
    for p in pages[:limit]:
        url = p["url"]
        try:
            r = httpx.get(url, timeout=25, follow_redirects=True)
            if r.status_code != 200:
                continue
            html = r.text
        except Exception:  # noqa: BLE001
            continue
        text = compliance._clean(html)
        for cand in _reviews_from(html, url) + _claims_from(text, url):
            body = cand["text"].strip()
            low = body.lower()
            if low in known:
                continue
            hit = next((b for b in banned if b in low), "")
            if hit:
                # The brand banned this phrase. A crawler does not get to
                # reintroduce it through a review queue.
                rejected.append({"text": body[:160], "banned_phrase": hit,
                                 "url": url})
                continue
            tags = _tags_for(tenant, body)
            if not tags:
                untaggable.append({"text": body[:160], "url": url})
                continue
            known.add(low)
            entry = {**cand, "text": body, "tags": tags}
            proposed.append(entry)
            if apply:
                kb.add_claim(tenant, body, cand["evidence"], tags,
                             proof_type=cand["proof_type"],
                             source=cand["source"], status="pending")

    return {
        "tenant": tenant, "domain": t.domain, "applied": apply,
        "pages_read": min(len(pages), limit),
        "vocabulary_tags": len(vocab),
        "proposed": proposed,
        "proposed_count": len(proposed),
        "rejected_for_banned_claim": rejected,
        "found_but_untaggable": untaggable[:15],
        "untaggable_count": len(untaggable),
        "note": ("Proposals land as PENDING claims — invisible to selection "
                 "until approved at /admin/ui?tab=kb. Anything using a banned "
                 "phrase was dropped, not queued. Untaggable candidates are "
                 "reported rather than stored with a guessed situation tag."),
    }


def harvest_all(limit: int = 25, apply: bool = False) -> dict:
    """Every active account. One failing site must not stop the rest."""
    out = {}
    for t in tenants.all_tenants(include_paused=False):
        try:
            out[t.key] = harvest(t.key, limit=limit, apply=apply)
        except Exception as exc:  # noqa: BLE001
            out[t.key] = {"error": f"{exc.__class__.__name__}: {str(exc)[:160]}"}
    return {"accounts": out, "applied": apply}
