"""Which live lookup a question needs, and what it needs to perform it.

The layer's job is to hand a caller its context. Some context is not knowledge
and never will be: an order's status, a stock level, a tracking number. These
exist in a system at the moment of asking, and a knowledge base that refuses
them is failing in the same way one that invents them would.

So this is the seam between *what the brand knows* and *what is true right
now*. A situation declares what it needs; this module says whether that tool
exists, whether the account can reach it, and which parameters are already in
the customer's own sentence.

**It does not call anything.** Naming the lookup and performing it are
different jobs with different blast radii, and keeping them apart is what lets
the caller — a skill, a system, an agent with tools — decide. The layer says
"you need the order number and it is 10432"; whether to go and get it is not
the layer's call.

Parameter extraction is deterministic. An order number in a sentence is a
pattern, not a judgement, and paying a model call to read one back would be
the kind of thing decision #1 puts on the wrong side of the line.
"""
from __future__ import annotations

import re

#: The lookups a situation may declare. A tool that is not here cannot be
#: named, exactly as a claim cannot carry a situation tag outside the
#: tenant's vocabulary — a declaration nothing can satisfy is worse than none,
#: because it reads as a route.
TOOLS: dict[str, dict] = {
    "shopify_order": {
        "capability": "commerce",
        "params": ["order_number", "email"],
        "any_of": True,           # either identifies an order
        "returns": "status, fulfilment, tracking, line items",
        "why": "order state exists in the store, never in the knowledge base",
    },
    "shopify_inventory": {
        "capability": "commerce",
        "params": ["entity_key"],
        "returns": "stock on hand per variant",
        "why": "stock is true at the moment of asking and stale by lunchtime",
    },
    "shopify_customer": {
        "capability": "commerce",
        "params": ["email"],
        "returns": "order history, lifetime value, previous issues",
        "why": "who this is changes what a fair answer looks like",
    },
    "tracking": {
        "capability": "commerce",
        "params": ["tracking_number", "order_number"],
        "any_of": True,
        "returns": "carrier scan history",
        "why": "'where is it' is a carrier question, not a brand question",
    },
    "calendar_availability": {
        "capability": "calendar",
        "params": ["date"],
        "returns": "what is free, and what is already booked",
        "why": "a venue cannot answer a date from a knowledge base",
    },
}

# Deterministic, and deliberately conservative. A pattern that fires on the
# wrong thing hands a caller a confident wrong parameter, which is worse than
# handing it none — the caller can ask for a missing one.
_PATTERNS = {
    "order_number": re.compile(r"(?:order\s*#?|#)\s*([0-9]{3,10})\b", re.I),
    "email": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    "tracking_number": re.compile(r"\b(1Z[0-9A-Z]{16}|[0-9]{12,22})\b"),
    "date": re.compile(
        r"\b(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}(?:/\d{2,4})?|"
        r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2})\b",
        re.I),
}


def extract_params(utterance: str, wanted: list[str]) -> dict:
    """Pull the parameters a lookup needs out of what the customer wrote."""
    found = {}
    for name in wanted or []:
        pat = _PATTERNS.get(name)
        if not pat:
            continue
        m = pat.search(utterance or "")
        if m:
            found[name] = m.group(1) if m.groups() else m.group(0)
    return found


def needed_for(tenant: str, situation_tags: list[str], utterance: str = "",
               entity_key: str = "") -> list[dict]:
    """Which lookups the placed situations declare, and how ready each one is.

    Every entry says what to call, what it still needs, and whether this
    account can reach it at all — a tool the client has never connected is a
    different problem from one missing a parameter, and telling them apart is
    the difference between "ask the customer" and "wire up Shopify".
    """
    from . import kb, tenants

    rows = {r.tag: r for r in kb.situation_rows(tenant)}
    caps = tenants.capabilities(tenant)
    out, seen = [], set()

    for tag in situation_tags or []:
        row = rows.get(tag)
        for want in (getattr(row, "needs", None) or []):
            name = (want or {}).get("tool", "")
            spec = TOOLS.get(name)
            if not spec or name in seen:
                continue
            seen.add(name)

            params = list(want.get("params") or spec["params"])
            have = extract_params(utterance, params)
            if entity_key and "entity_key" in params:
                have["entity_key"] = entity_key
            missing = [p for p in params if p not in have]
            satisfied = (bool(have) if spec.get("any_of") else not missing)

            out.append({
                "tool": name,
                "for_situation": tag,
                "capability": spec["capability"],
                "connected": bool(caps.get(spec["capability"])),
                "returns": spec["returns"],
                "why": want.get("why") or spec["why"],
                "params": params,
                "have": have,
                "missing": [] if satisfied else missing,
                "ready": satisfied and bool(caps.get(spec["capability"])),
                "blocked_because": (
                    "" if satisfied and caps.get(spec["capability"]) else
                    f"{spec['capability']} is not connected for this account"
                    if not caps.get(spec["capability"]) else
                    f"ask the customer for: {', '.join(missing)}"),
            })
    return out


def validate_declaration(needs: list[dict]) -> tuple[list[dict], list[str]]:
    """Keep only declarations naming a real tool. Refuses like a bad tag does."""
    kept, bad = [], []
    for want in needs or []:
        name = (want or {}).get("tool", "")
        if name in TOOLS:
            kept.append(want)
        else:
            bad.append(name or "(unnamed)")
    return kept, bad
