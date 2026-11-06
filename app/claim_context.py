"""What a reviewer needs to judge a claim: its context, its date, its kind,
and how it can be verified.

Owner, 2026-11-06, on three claims from the Transak harvest:

* "KYC is instantly approved." — *in what context?* It came from a help
  article titled "Is KYC required on the staging environment?": true only in
  the developer sandbox. The sentence was kept; the one condition that makes
  it true was not.
* "Transak secures 6 new US state licenses …" — *a point in time, not a claim
  about the total number of licenses.* It was being recorded as
  "licences: 6", and so fed the licence disagreement as if it were a total.
* "The partnership between StellaSwap and Transak ensures …" — *is this
  partnership still in place? If not we don't want to highlight it.*

"Not only do these facts on their own lack the context to have any
significance, but a reviewer would have no way of verifying, supporting or
approving them."

So every claim carries: where it sits (page title, section, the sentences
either side), the page's date, whether it is scoped to a sandbox, and its
KIND by named rules — each kind with what verifies it and who owns that. The
rules are text rules, the same for every company (BUILD-MAP §14), and each is
named so it can be measured from reviewer decisions like the grouping rules.
No model decides any of it inside the app.
"""
from __future__ import annotations

import datetime as dt
import re

#: kind -> (rule, what a reviewer must check, who can confirm it)
KINDS: dict[str, dict] = {
    "event": {
        "rule": re.compile(
            r"\b(secures?|secured|announc\w+|launch(?:es|ed)?|unveil\w*|introduc\w+|"
            r"partners? with|partnered|teams? up|joins?|joined|raises?|raised|acquir\w+|"
            r"expands?|expanded|celebrat\w+|today|this week|has (?:obtained|received|been granted)|"
            r"is now live|goes live|went live)\b", re.I),
        "check": "A dated announcement: true on its date, not a statement of today's totals. "
                 "Keep it as history (dated), or remove it from pages that read as current.",
        "owner": "PR / press office",
    },
    "increment": {
        "rule": re.compile(r"\b\d[\d,]*\+?\s+(?:new|additional|more|further|extra)\b", re.I),
        "check": "Counts what was ADDED, not the total — never compare it with a total.",
        "owner": "PR / press office",
    },
    "relationship": {
        "rule": re.compile(r"\b(partner(?:ship|ed|s)?|integrat\w+|collaborat\w+|teams? up|"
                           r"powered by|in partnership|alliance)\b", re.I),
        "check": "Names a partner or integration: confirm it is still active before it is "
                 "highlighted anywhere.",
        "owner": "partnerships owner",
    },
    "absolute": {
        "rule": re.compile(r"\b(instant(?:ly)?|immediate(?:ly)?|always|never|guarantee\w*|100%|"
                           r"zero|no (?:fees?|hidden|charges?|kyc)|free of charge|risk[- ]free|"
                           r"unlimited|always free)\b", re.I),
        "check": "Absolute wording: state the conditions (for whom, where, by which method) or "
                 "soften it.",
        "owner": "product owner + compliance",
    },
    "superlative": {
        "rule": re.compile(r"\b(most|largest|biggest|best|leading|first|only|#1|number one|"
                           r"fastest|cheapest|lowest|world'?s)\b", re.I),
        "check": "A superlative needs substantiation on file (a ranking, a report, a regulator "
                 "source), or it should be removed.",
        "owner": "compliance (substantiation file)",
    },
    "testimonial": {
        "rule": re.compile(r"^(?:[A-Z][a-z]+\.?\s+)?(?:i|i'm|i've|my|we've been)\s", re.I),
        "check": "A customer's words, not the brand's claim: confirm consent and that it is "
                 "quoted accurately.",
        "owner": "marketing (consent record)",
    },
}
#: Wording that scopes a claim to a sandbox / test environment.
_SANDBOX = re.compile(r"\b(staging|sandbox|test(?:ing)? environment|testnet|demo mode|"
                      r"dummy|developer environment)\b", re.I)
#: An event or relationship older than this is flagged as possibly out of date.
STALE_DAYS = 365


def kinds_of(text: str, proof_type: str = "") -> list[str]:
    """The kinds a claim's own words show (several can apply)."""
    out = [k for k, spec in KINDS.items() if spec["rule"].search(text or "")]
    if (proof_type or "") == "testimonial" and "testimonial" not in out:
        out.append("testimonial")
    return out


def is_history(text: str) -> bool:
    """A figure in this sentence is history or an increment, not a current
    total: "secures 6 new licences", "launched in 3 more countries"."""
    return bool(KINDS["event"]["rule"].search(text or "")
                or KINDS["increment"]["rule"].search(text or ""))


def _norm(s: str) -> str:
    return " ".join(re.sub(r"[^\w%+$€£]+", " ", (s or "").lower()).split())


def locate(doc: dict, text: str) -> dict:
    """Where the claim sits in its page: section heading, and the line before
    and after. {} when the page no longer carries the words."""
    lines = doc.get("lines") or []
    heads = {_norm(h.get("text", "")) for h in doc.get("headings", [])}
    want = _norm(text)[:120]
    section, at = "", -1
    for i, ln in enumerate(lines):
        n = _norm(ln)
        if n in heads:
            section = ln
        if want and want in n:
            at = i
            break
    if at < 0:
        return {}
    prev = next((lines[j] for j in range(at - 1, -1, -1) if _norm(lines[j]) not in heads), "")
    nxt = next((lines[j] for j in range(at + 1, len(lines)) if _norm(lines[j]) not in heads), "")
    return {"section": section if _norm(section) != _norm(lines[at]) else "",
            "before": prev[:300], "line": lines[at][:400], "after": nxt[:300]}


def _age_days(date: str, today: dt.date | None = None) -> int | None:
    try:
        d = dt.date.fromisoformat(date[:10])
    except (TypeError, ValueError):
        return None
    return ((today or dt.date.today()) - d).days


def context_for(tenant: str, claim_text: str, pages: list[str], proof_type: str = "",
                docs: dict | None = None, today: dt.date | None = None) -> dict:
    """Everything a reviewer needs for one claim, from the stored crawl.

    `docs` caches Documents by URL across a card list."""
    from .pipeline import fetch, parse, policy
    docs = docs if docs is not None else {}
    where = []
    for u in pages[:5]:
        if u not in docs:
            docs[u] = parse.document(tenant, u) if fetch.latest(tenant, u) else {}
        d = docs[u]
        loc = locate(d, claim_text) if d else {}
        where.append({"url": u, "title": d.get("title", "") if d else "",
                      "published": d.get("published", "") if d else "",
                      "tier": policy.tier(u, d or None), **loc})
    kinds = kinds_of(claim_text, proof_type)
    first = where[0] if where else {}
    scope_text = " ".join([claim_text, first.get("title", ""), first.get("section", ""), first.get("url", "")])
    sandbox = bool(_SANDBOX.search(scope_text))
    dates = [w["published"] for w in where if w.get("published")]
    newest = max(dates) if dates else ""
    age = _age_days(newest, today) if newest else None
    flags = []
    if sandbox:
        flags.append("Scoped to a sandbox / staging environment: true there only. Never state "
                     "it outside the developer docs.")
    dated_kind = any(k in kinds for k in ("event", "relationship", "increment"))
    if dated_kind and age is not None and age > STALE_DAYS:
        flags.append(f"Stated on a page dated {newest} ({age // 30} months ago): confirm it is "
                     f"still true before it is highlighted.")
    elif dated_kind and not newest and any(w.get("tier") == "blog" for w in where):
        flags.append("On an undated post: confirm when it was true.")
    checks = [{"kind": k, "check": KINDS[k]["check"], "owner": KINDS[k]["owner"]} for k in kinds]
    if not checks and not sandbox:
        checks = [{"kind": "statement", "check": "Confirm it against the source of record, or "
                   "attach the evidence that supports it.", "owner": "the claim's owner"}]
    return {"kinds": kinds, "sandbox": sandbox, "newest_date": newest, "age_days": age,
            "flags": flags, "checks": checks, "where": where}
