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
    r"currenc|assets|tokens|networks|licen|"
    # The pages that hold a retailer's or service's commitments.
    r"shipping|delivery|returns?|refunds?|exchanges?|warrant|guarantee|"
    r"terms-of-sale|promotions?|offers?|discounts?|rates", re.I)
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


#: A two-level path family this large is generated, not written.
FAMILY_MIN = 500


def thin_families(pages: list[dict]) -> tuple[list[dict], list[dict]]:
    """(pages to read, a report of what was left out).

    transak.com/buy/<coin>/<place> is 5,651 pages: 100 coins by 63 places,
    the same boilerplate with one sentence that differs per PLACE. Reading all
    of them is 22 hours of crawl for 63 answers, so a family keeps one page per
    last segment, always on its commonest middle segment so the answers are
    like for like. One-level paths are never touched (/blog/*, /products/*)
    and neither is a legal page. The report goes on the run card: a left-out
    page is a decision on record, never a silent loss."""
    fams: dict[tuple, list[dict]] = {}
    for p in pages:
        u = p["url"].split("://", 1)[-1].split("?", 1)[0].rstrip("/")
        parts = u.split("/")
        if len(parts) == 4 and not compliance.is_legal_url(p["url"]):
            fams.setdefault((parts[0], parts[1]), []).append(p)
    drop, report = set(), []
    for (host, top), members in sorted(fams.items()):
        if len(members) < FAMILY_MIN:
            continue
        seg = [m["url"].split("?", 1)[0].rstrip("/").split("/")[-2:] for m in members]
        common: dict[str, int] = {}
        for mid, _last in seg:
            common[mid] = common.get(mid, 0) + 1
        best: dict[str, tuple] = {}
        for m, (mid, last) in zip(members, seg):
            rank_ = (-common[mid], mid)
            if last not in best or rank_ < best[last][0]:
                best[last] = (rank_, m["url"])
        keep = {v[1] for v in best.values()}
        drop |= {m["url"] for m in members if m["url"] not in keep}
        report.append({"family": f"{host}/{top}/*/*", "pages": len(members),
                       "kept": len(keep)})
    return [p for p in pages if p["url"] not in drop], report


def max_chunks(t: str):
    return TIERS.get(t, TIERS["marketing"])["max_chunks"]


def rank(t: str) -> int:
    return TIERS.get(t, TIERS["marketing"])["rank"]


def table() -> list[dict]:
    """The policy, for the console and the report."""
    return [{"tier": k, **v} for k, v in sorted(TIERS.items(), key=lambda kv: kv[1]["rank"])]
