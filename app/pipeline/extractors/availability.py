"""Whether a page says the brand operates in a place.

A site can answer this per place: transak.com/buy/xaut/norway reads "We're not
available in Norway yet", /buy/sei/guam is a working how-to-buy page with
"Payment Methods Supported in Guam". No count on any page says as much about
where the brand really operates, so each answer is a statement of its own,
`availability.<place>`. A site that gives one place both answers is the only
thing that becomes a finding.

A buy page must name the same place twice: "How to Buy Crypto in the 1inch
Wallet" is a blog post, and the wallet is not a country.
"""
from __future__ import annotations

import re
import unicodedata

NAME = "availability"
VERSION = 2
USES_MODEL = False
MAX_PLACE_WORDS = 5

_NOT = re.compile(r"(?:we(?:['\u2019]re| are)|is) not available in (.+?)(?: yet)?[.!]?$", re.I)
_BUY = re.compile(r"how to buy .+? in (.+)$", re.I)
_METHODS = re.compile(r"payment methods supported in (.+)$", re.I)


def _slug(place: str) -> str:
    # Accents folded, not dropped: "Réunion" is reunion, never r-union.
    plain = unicodedata.normalize("NFKD", place).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")


def _is_place(name: str) -> bool:
    """A place is a short proper name. "Chrome, Firefox, or on non-Apple
    devices" and "your area or for your wallet" are sentences."""
    return name[:1].isupper() and "," not in name and len(name.split()) <= MAX_PLACE_WORDS


def _state(place: str, value: str, number: float, line: str) -> dict:
    return {"subject": f"availability.{_slug(place)}", "value": value,
            "number": number, "qualifier": "", "unit": "place", "match": place,
            "text": line[:400], "field": "body", "section": "",
            "locator": "availability"}


def run(doc: dict, terms: tuple = ()) -> list[dict]:
    heads = [" ".join((h.get("text") or "").split()) for h in doc.get("headings", [])]
    lines = heads + [" ".join(b.split()) for b in doc.get("blocks", [])]
    for ln in lines:
        m = _NOT.search(ln)
        if m and _is_place(m.group(1)):
            return [_state(m.group(1), "not available", 0.0, ln)]
    buy = next((m.group(1) for m in map(_BUY.search, heads) if m), "")
    said = {_slug(m.group(1)) for m in map(_METHODS.search, lines) if m}
    if buy and _slug(buy) in said:
        return [_state(buy, "available", 1.0, f"How to buy in {buy}")]
    return []
