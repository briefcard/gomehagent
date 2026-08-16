"""The last gate before anything reaches a customer. Code only, fails closed.

A prompt mostly obeys. A check always blocks — that split is already the
design behind `note()` versus `promote_rule()`, and this is where the second
half actually happens. **There is no model call in this file and there must
never be one**: a model validating a model is the one thing the platform's
second locked decision forbids outright, because both can be wrong in the same
direction and nothing would notice.

Every rule returns a named failure. "Blocked" with no field is a dead end for
whoever has to fix it, and the whole discipline of this codebase is that a
refusal names what would unblock it.

Fails closed in the literal sense: an unknown account, a missing ban list, or
an exception inside a rule all produce a failure, never a pass. The dangerous
default is the one where a validator that could not run reports clean —
`compliance.scan` already refuses an account with no `banned_claims` for
exactly this reason.
"""
from __future__ import annotations

import re

from . import conversation as cv, kb, ledger


def _banned(tenant: str, text: str) -> list[dict]:
    """Barred phrases actually present in the text.

    Word-boundary matched, because a substring test flags "guarantee" inside
    "guaranteed" twice and, worse, flags real words that merely contain a
    banned one. The ban list is enforced, so a false positive is a blocked
    draft somebody has to argue with.
    """
    out = []
    low = (text or "").lower()
    for phrase in kb.banned_claims(tenant) or []:
        p = (phrase or "").strip().lower()
        if not p:
            continue
        if re.search(r"(?<!\w)" + re.escape(p) + r"(?!\w)", low):
            out.append({"phrase": phrase})
    return out


def check(tenant: str, body: str, *, claim_ids: list[str] | None = None,
          entity_key: str = "", conversation_id: str = "",
          within_days: int = 30, require_citation: bool = True) -> dict:
    """Validate one draft. Returns `{ok, failures, checked}`.

    `failures` is a list of `{rule, detail, fix}` — the fix is not decoration,
    it is what makes a blocked run actionable instead of a dead end.
    """
    failures, checked = [], []

    def fail(rule, detail, fix):
        failures.append({"rule": rule, "detail": detail, "fix": fix})

    # --- the account can be validated at all ------------------------------
    checked.append("account")
    if not kb.brand(tenant):
        fail("unknown_account", f"no brand row for {tenant!r}",
             "create the account before drafting for it")
        return {"ok": False, "failures": failures, "checked": checked}

    rules = kb.banned_claims(tenant) or []
    if not rules:
        # Not a warning. Passing a draft against zero rules and calling it
        # clean is worse than not checking — it is a false assurance, and
        # compliance.scan already refuses on the same grounds.
        fail("no_ban_list", "this account has no banned_claims",
             "author the ban list on the Knowledge tab — a crawler can never "
             "derive it, because a site records what a brand does say")

    # --- nothing barred is being said -------------------------------------
    checked.append("banned_claims")
    for hit in _banned(tenant, body):
        fail("banned_claim", f"the draft says {hit['phrase']!r}",
             "reword it, or retire the rule if it is no longer true")

    # --- every fact is attributable ---------------------------------------
    checked.append("citation")
    ids = [c for c in (claim_ids or []) if c]
    if require_citation and body.strip() and not ids:
        fail("uncited", "the draft carries no claim_id",
             "assemble it from approved claims, or mark it as opinion")

    inv = {c.id: c for c in kb.claim_inventory(tenant)["selectable"]}
    for cid in ids:
        if cid not in inv:
            fail("claim_not_selectable",
                 f"claim {cid[:12]} is retired, pending, or another account's",
                 "re-resolve — the context this was drafted from is stale")

    # --- the thing being sold can actually be bought ----------------------
    if entity_key:
        checked.append("entity")
        ent = [e for e in kb.entities(tenant, available_only=False)
               if e.key == entity_key]
        if not ent:
            fail("unknown_entity", f"nothing on file keyed {entity_key!r}",
                 "check the catalogue key, or re-run catalog_sync")
        elif ent[0].availability != "available":
            fail("entity_unavailable",
                 f"{ent[0].name} is {ent[0].availability}",
                 "do not route demand to a shelf that is empty — pick another "
                 "entity or hold the send")

    # --- we are not saying it twice ---------------------------------------
    if ids:
        checked.append("not_repeated")
        rep = ledger.is_repeat(tenant, ids, entity_key, within_days)
        if rep["repeat"]:
            for cid, where in rep["claims"].items():
                fail("repeat",
                     f"claim {cid[:12]} already went out for this entity "
                     f"within {within_days} days ({len(where)}×)",
                     "pick different proof, or widen the window deliberately")

    # --- we are not contradicting what we already promised ----------------
    if conversation_id:
        checked.append("commitments")
        for c in cv.open_commitments(tenant, conversation_id):
            checked.append(f"commitment:{c.kind}")
            # The cheap, honest version: if the draft talks about the same KIND
            # of thing as an open promise and does not repeat its value, a
            # human looks. Deciding whether two prices agree is a judgement,
            # and a validator that guesses at one is worse than one that asks.
            if c.kind.lower() in (body or "").lower() and c.value not in (body or ""):
                fail("commitment_conflict",
                     f"an open {c.kind} commitment says {c.value!r} and this "
                     f"draft discusses {c.kind} without repeating it",
                     "restate the commitment or settle it before replying")

    return {"ok": not failures, "failures": failures, "checked": checked,
            "rules_enforced": len(rules)}
