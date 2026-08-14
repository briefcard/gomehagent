"""The registry of things that can fill a knowledge base, as data.

A first version of this hardcoded the order of five named sources in an
orchestrator function. That is the customisation-in-code pattern decision #3
forbids, and it has already bitten this codebase three times — the hardcoded
`diagnostic` offer key, the shared situation constant, the literal `"how fast"`
objection lookup. Adding a sixth source would have meant editing an if-tree
that knows every source by name.

So a source declares itself and the runner knows nothing about any of them:

    {"key", "label", "produces",
     "capability":   a name from tenants.CAPABILITIES, or "" for none
     "precondition": tenant -> "" if it can run, else why not
     "run":          (tenant, apply, budget) -> dict}

Adding the spreadsheet upload is one entry in `SOURCES`. Onboarding a client
who has none of these wired reports five honest skips rather than crashing.

What this deliberately does NOT include is the seed. `kb_seed` is bootstrap
data for the five accounts that existed before the platform did — it is not a
source a sixth client has, and putting it here would make the registry a
description of our history rather than of what any account can use.
"""
from __future__ import annotations

from . import kb, tenants


def _needs_domain(tenant: str) -> str:
    t = tenants.get(tenant)
    return "" if (t and t.domain) else "no domain recorded"


def _needs_ban_list(tenant: str) -> str:
    # Scanning against zero rules reports a clean site that is not clean. The
    # refusal is the feature; see compliance.scan.
    return "" if kb.banned_claims(tenant) else (
        "no banned_claims on file — a scan against zero rules would report a "
        "clean site that has not been checked")


def _catalogue(tenant: str, apply: bool, budget: int) -> dict:
    from . import catalog_sync
    r = catalog_sync.sync_shopify(tenant, dry_run=not apply)
    return {k: r.get(k) for k in
            ("products_seen", "added", "updated", "out_of_stock",
             "held_back_count", "error")} | {
        "compliance_violations": len(r.get("compliance_violations") or [])}


def _compliance(tenant: str, apply: bool, budget: int) -> dict:
    from . import compliance
    r = compliance.scan(tenant, limit=budget)
    return {"pages_checked": r.get("pages_checked"),
            "violations": len(r.get("violations") or []),
            "error": r.get("error")}


def _website(tenant: str, apply: bool, budget: int) -> dict:
    from . import harvest
    r = harvest.harvest(tenant, limit=budget, apply=apply)
    # `extractor_note` carries WHY the model did not run — no blocks worth
    # reading, an API error, a missing key. Dropping it meant a run could
    # report `extractor: "deterministic filter"` with no way to tell which of
    # those happened, which is the §2 lesson about drop reasons reading as a
    # finding about the site when they were a finding about the filter.
    return {k: r.get(k) for k in
            ("extractor", "extractor_note", "pages_read", "pages_skipped",
             "proposed_count", "faqs_found", "untagged_count",
             "situations_wanted", "situations_proposed", "error")}


def _sent_mail(tenant: str, apply: bool, budget: int) -> dict:
    from . import email_harvest
    r = email_harvest.mine(tenant, limit=budget, apply=apply)
    return {k: r.get(k) for k in
            ("threads_seen", "threads_mined", "claims_count",
             "objections_count", "extractor", "error")}


# Order matters, and only for one reason: the catalogue runs before the website
# so that a product page can be scoped to the product it is about. Everything
# else is independent.
SOURCES = [
    {"key": "catalogue", "label": "Product catalogue",
     "produces": "entities, with live price and stock",
     "capability": "commerce", "precondition": None, "run": _catalogue},

    {"key": "compliance", "label": "Live-site compliance",
     "produces": "pages that break the brand's own rules",
     "capability": "", "precondition": _needs_ban_list, "run": _compliance},

    {"key": "website", "label": "Their website",
     "produces": "claim and review proposals",
     "capability": "", "precondition": _needs_domain, "run": _website},

    {"key": "sent_mail", "label": "Sent mail",
     "produces": "claims they have already made, and the objections they answer",
     "capability": "inbox", "precondition": None, "run": _sent_mail},
]


def available(tenant: str) -> list[dict]:
    """Every source, with whether this account can use it and why not."""
    caps = tenants.capabilities(tenant)
    out = []
    for src in SOURCES:
        why = ""
        if src["capability"] and not caps.get(src["capability"]):
            why = f"no {src['capability']} connection"
        elif src["precondition"]:
            why = src["precondition"](tenant)
        out.append({"key": src["key"], "label": src["label"],
                    "produces": src["produces"], "usable": not why,
                    "blocked_by": why})
    return out


def fill(tenant: str, apply: bool = False, budget: int = 40,
         only: list[str] | None = None) -> dict:
    """Run every source this account has wired. Reads unless `apply`.

    Never raises on one source: an account whose store is unreachable should
    still get its website read. Each failure is reported in place.
    """
    if not tenants.get(tenant):
        return {"error": f"unknown tenant {tenant!r}"}

    ran = []
    for src in SOURCES:
        if only and src["key"] not in only:
            continue
        state = next(s for s in available(tenant) if s["key"] == src["key"])
        if not state["usable"]:
            ran.append({**state, "ran": False})
            continue
        try:
            result = src["run"](tenant, apply, budget)
            ran.append({**state, "ran": True,
                        "result": {k: v for k, v in result.items() if v is not None}})
        except Exception as exc:  # noqa: BLE001 — one source must not stop the rest
            ran.append({**state, "ran": False,
                        "error": f"{exc.__class__.__name__}: {str(exc)[:200]}"})

    # What is still missing comes from `kb.gaps`, which is already per-tenant,
    # already ordered by what unblocks the most, and already derived from
    # INTAKE_STEPS as data. Writing that list again here is how it goes stale.
    comp = kb.completeness(tenant)
    waiting = comp.get("awaiting_review", {})
    return {
        "tenant": tenant, "applied": apply,
        "sources": ran,
        "ready": comp["ready"],
        "counts": comp["counts"],
        "awaiting_review": waiting,
        "still_needs_a_human": [
            {"field": g["id"], "question": g["q"], "hint": g["hint"]}
            for g in kb.gaps(tenant)],
        "next": (f"Review {sum(waiting.values())} proposals at "
                 f"/admin/ui?tab=content&tenant={tenant}"
                 if sum(waiting.values()) else
                 "Nothing waiting. Answer the questions above with /next."),
        "note": ("Every source files PROPOSALS — nothing here approved anything, "
                 "and nothing is usable by a generator until a human does. "
                 "Without apply=1 this is a read-only rehearsal."),
    }
