"""Risk tiers — how hard each page is read, as DATA (BUILD-MAP §5).

A licence list and a blog post are not read with the same care. The tier
decides which readers run, how much of a long page the model reads (the
chunk ceiling — None is "all of it"), and how often the page is due again.
A ceiling is only ever applied with a report: the page is marked `cut`.

The legal and coverage tiers have NO ceiling. The page that states what a
brand is licensed for, or where it operates, is read in full, always.
"""
from __future__ import annotations

import re

from .. import compliance

#: tier -> policy. `max_chunks` None = no ceiling. `days` = fetch cadence.
TIERS: dict[str, dict] = {
    "legal":     {"rank": 0, "max_chunks": None, "days": 7,
                  "why": "a legal / compliance / licensing page — binding"},
    "coverage":  {"rank": 1, "max_chunks": None, "days": 7,
                  "why": "states where the brand operates, what it supports, fees or limits"},
    "product":   {"rank": 2, "max_chunks": 8, "days": 14,
                  "why": "a product or catalogue page"},
    "support":   {"rank": 3, "max_chunks": 8, "days": 30,
                  "why": "help-centre or documentation page"},
    "marketing": {"rank": 4, "max_chunks": 4, "days": 30,
                  "why": "a marketing page"},
    "blog":      {"rank": 5, "max_chunks": 2, "days": 90,
                  "why": "a blog or news post"},
}

_COVERAGE = re.compile(
    r"coverage|countr|support(?:ed)?-|supported|availab|where-we|locations?|"
    r"regions?|markets?|fees?|pricing|limits?|payment-methods?|kyc|"
    r"currenc|assets|tokens|networks|licen", re.I)
_SUPPORT_HOST = re.compile(r"^(help|support|docs|developers?|kb|faq)\.", re.I)
_SUPPORT_PATH = re.compile(r"/(help|support|docs|faq|knowledge|hc)(/|$)", re.I)
_BLOG = re.compile(r"/(blog|news|press|articles?|stories|insights)(/|$)", re.I)
_PRODUCT = re.compile(r"/(products?|collections?|shop|catalog(?:ue)?)(/|$)", re.I)


def tier(url: str, doc: dict | None = None) -> str:
    """The tier for one page, from its URL and — when parsed — its headings.

    A page that is not ON a coverage URL but whose top heading is "Supported
    countries" is a coverage page; a heading is how the brand names it."""
    u = url or ""
    if compliance.is_legal_url(u):
        return "legal"
    host = u.split("://", 1)[-1].split("/", 1)[0]
    path = "/" + u.split("://", 1)[-1].split("/", 1)[-1] if "/" in u.split("://", 1)[-1] else "/"
    heads = " ".join(h["text"] for h in (doc or {}).get("headings", [])[:3])
    if _COVERAGE.search(path) or (heads and _COVERAGE.search(heads.replace(" ", "-"))):
        return "coverage"
    # A help-centre HOST wins over its paths: support.example.com/articles/1
    # is a help article, not a blog post.
    if _SUPPORT_HOST.search(host):
        return "support"
    if _BLOG.search(path):
        return "blog"
    if _PRODUCT.search(path):
        return "product"
    if _SUPPORT_PATH.search(path):
        return "support"
    return "marketing"


def max_chunks(t: str):
    return TIERS.get(t, TIERS["marketing"])["max_chunks"]


def rank(t: str) -> int:
    return TIERS.get(t, TIERS["marketing"])["rank"]


def table() -> list[dict]:
    """The policy, for the console and the report."""
    return [{"tier": k, **v} for k, v in sorted(TIERS.items(), key=lambda kv: kv[1]["rank"])]
