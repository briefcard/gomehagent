"""One call that hands an agent its context, so it never has to go looking.

Navigation is the overhead this layer exists to remove. An agent wired to tools
has to *discover* context — five calls, five chances to stop early, and a token
bill proportional to how thorough it happened to feel. So nothing here is a
tool an agent chooses to use. `resolve()` takes a request and returns a bundle,
and the bundle is the whole of what the caller gets.

Three tiers, because a voice turn and an email draft do not need the same
things:

    1  rules       identity, positioning, voice, the ban list. Tiny, always.
    2  situated    the objections for the situation actually detected, each
                   with the claims that back it.
    3  deep        entity match against a stated requirement, and the state of
                   the conversation this belongs to.

**The receipt is the point.** Every bundle says what was searched, what was
found, and what could not be grounded — so a caller never has to wonder whether
thin means "there is little" or "we did not look". That is the same discipline
the kernel already demands of agents ("state what you searched and what you
might have missed"), applied to retrieval itself.

**This layer enriches; it does not gatekeep.** That distinction was got wrong
once and is worth stating plainly. Refusing to *invent* is essential and lives
in `validator`, on output, in code that fails closed. Refusing to hand over
*context* is a different act entirely — it lets a missing row veto a reader
holding the brand rules, the catalogue and every approved claim, which is
plenty to work from.

So almost nothing here blocks. `gaps` reports what is thin, each with a fix.
`grounding.level` says how much support a bundle carries, so a reader can
calibrate rather than infer it from silence. Material that is weakly matched
comes back **labelled**, not withheld — withholding protects a machine that
takes the top result blindly and merely handicaps one that can judge.

`blocked_on` is reserved for the single case that makes output genuinely
unsafe: no ban list, so the validator has nothing to check against and "clean"
would be a false assurance.
"""
from __future__ import annotations

from . import conversation as cv, kb, tenants

#: Tier names, in the order they are built. A caller asks for a depth, not a
#: list — asking for tier 3 without tier 1 is not a thing anyone wants.
TIERS = ("rules", "situated", "deep")


def readiness(tenant: str) -> dict:
    """What can this account actually answer, and what would unblock the rest.

    `resolve()` tells you whether ONE request can be grounded. This tells you
    how many of them can, before you send any — which is the question an agency
    onboarding a client is really asking, and the one nothing here answered.

    The probe set is the tenant's **own situation vocabulary**, not questions
    invented for the occasion. A situation is answerable when an approved
    objection carries that tag; it is proven when a claim backs the objection.
    Those are the two states a drafter can tell apart, so they are the two
    states reported.

    No model call and no network — this is counting rows the KB already has.
    """
    from . import kb

    tags = sorted(kb.situations(tenant))
    all_obj = kb.objections(tenant, any_entity=True)
    inv = kb.claim_inventory(tenant)
    b = kb.brand(tenant)

    per, answerable, proven = [], 0, 0
    for tag in tags:
        obj = [o for o in all_obj if tag in (o.situations or [])]
        cl = [c for c in inv["selectable"] if tag in (c.situations or [])]
        pend_o = len([o for o in kb.objections(tenant, any_entity=True,
                                               include_proposed=True)
                      if tag in (o.situations or [])]) - len(obj)
        state = ("proven" if obj and cl else
                 "answerable" if obj else
                 "waiting on review" if pend_o > 0 else "unanswerable")
        answerable += bool(obj)
        proven += bool(obj and cl)
        per.append({"situation": tag, "state": state,
                    "objections": len(obj), "claims": len(cl),
                    "objections_in_review": max(pend_o, 0)})

    # Ranked by how many situations each one unblocks, because "what should I
    # do first" is the only useful ordering and a flat list of gaps is not it.
    blockers = []
    if not (b and (b.voice or {}).get("tone")):
        blockers.append({"fix": "brand.voice.tone", "unblocks": "every draft",
                         "where": "Knowledge tab", "situations": len(tags)})
    if not (b and b.banned_claims):
        blockers.append({"fix": "brand.banned_claims",
                         "unblocks": "every draft AND every compliance scan",
                         "where": "Knowledge tab", "situations": len(tags)})
    waiting = [p for p in per if p["state"] == "waiting on review"]
    if waiting:
        blockers.append({
            "fix": f"approve {sum(p['objections_in_review'] for p in waiting)} "
                   f"objection(s) already proposed",
            "unblocks": f"{len(waiting)} situation(s)", "where": "Content tab",
            "situations": len(waiting)})
    missing = [p["situation"] for p in per if p["state"] == "unanswerable"]
    if missing:
        blockers.append({
            "fix": f"author an objection for: {', '.join(missing[:6])}"
                   + (" …" if len(missing) > 6 else ""),
            "unblocks": f"{len(missing)} situation(s)",
            "where": "/next on Telegram, or an intake link",
            "situations": len(missing)})
    blockers.sort(key=lambda x: -x["situations"])

    return {
        "tenant": tenant,
        "situations": len(tags),
        "answerable": answerable,
        "proven": proven,
        "score": f"{answerable}/{len(tags)}" if tags else "0/0",
        "entities": len(kb.entities(tenant, available_only=False)),
        "has_voice": bool(b and (b.voice or {}).get("tone")),
        "has_ban_list": bool(b and b.banned_claims),
        "per_situation": per,
        "next_actions": blockers,
        "verdict": (
            "cannot answer anything yet" if answerable == 0 else
            f"can answer {answerable} of {len(tags)} situations, "
            f"{proven} of them with proof attached"),
    }


def _rules(tenant: str) -> dict:
    """Tier 1. Identity and the constraints that must never be violated.

    Two shapes on purpose. `block` is the prose already written for injection —
    `tenants.agent_block` was built for exactly this and is the right size. The
    structured fields beside it are what a deterministic validator reads, and a
    validator cannot parse prose.
    """
    b = kb.brand(tenant)
    return {
        "block": tenants.agent_block(tenant),
        "positioning": (b.positioning if b else "") or "",
        "voice_tone": list((b.voice or {}).get("tone") or []) if b else [],
        "banned_claims": list(b.banned_claims or []) if b else [],
    }


def _situated(tenant: str, utterance: str, entity_key: str,
              audience_key: str, limit: int) -> tuple[dict, list, list]:
    """Tier 2. Classify, then retrieve only if the classification stands up.

    An unconfident classification does **not** quietly fall through to
    retrieval. Ranking objections against a tag nobody stands behind returns a
    plausible list aimed at the wrong problem, and nothing downstream can tell
    that from a good one. So the situations come back with their basis and
    score, and retrieval is skipped with a reason.
    """
    if not utterance:
        return ({"detected": [], "basis": "", "confident": False,
                 "score": None, "candidates": [],
                 "why": "no utterance given"}, [], [])

    g = kb.suggest_tags(tenant, utterance, entity_key=entity_key)
    detected = {"detected": g["tags"], "basis": g["basis"],
                "confident": g["confident"], "score": g["score"],
                "candidates": g["candidates"], "why": ""}
    if not g["confident"]:
        # Label it, do not withhold it. Withholding was the wrong instinct:
        # ranking objections against a tag nobody stands behind is dangerous
        # for a machine that takes the top one blindly, and merely *unhelpful*
        # for a reader that can judge relevance. The consumer here is
        # intelligent, so the honest move is to hand over what the account has
        # with the confidence marked, not to decide on its behalf that it gets
        # nothing.
        detected["why"] = ("could not place this against the account's "
                           "situation vocabulary — the objections below are "
                           "unranked, judge relevance yourself")
        rows = kb.objections(tenant, audience_key=audience_key,
                             entity_key=entity_key or None)[:limit]
        out, support = [], []
        for o in rows:
            backing = kb.support_for(tenant, o)
            support.extend(backing)
            out.append({
                "objection_id": o.id, "objection": o.objection,
                "response": o.response,
                "situations": list(o.situations or []),
                "entity_key": o.entity_key or "",
                "relevance": "unranked — the question could not be placed",
                "support": [{"claim": c.claim, "evidence": c.evidence or "",
                             "claim_id": c.id} for c in backing],
            })
        return detected, out, support

    rows = kb.objections(tenant, audience_key=audience_key,
                         entity_key=entity_key or None,
                         situations=g["tags"])[:limit]
    out, support = [], []
    for o in rows:
        backing = kb.support_for(tenant, o)
        support.extend(backing)
        out.append({
            # The ledger records which objection answered, so "why did we say
            # that" is a lookup rather than a reconstruction.
            "objection_id": o.id,
            "objection": o.objection,
            "response": o.response,
            "situations": list(o.situations or []),
            "entity_key": o.entity_key or "",
            "support": [{"claim": c.claim, "evidence": c.evidence or "",
                         "claim_id": c.id} for c in backing],
        })
    return detected, out, support


def resolve(tenant: str, system: str = "", utterance: str = "",
            contact_id: str = "", entity_key: str = "", audience_key: str = "",
            requirements: dict | None = None, tier: int = 3,
            limit: int = 3) -> dict:
    """The one contract every system and skill calls.

    Returns a bundle plus a coverage receipt. Read `blocked_on` before reading
    anything else: a non-empty list means this account cannot safely produce
    output for this request, and the entries name the field to go and fill.
    """
    tenant = (tenant or "").strip()
    if not tenant or not tenants.get(tenant):
        return {"tenant": tenant, "error": "unknown account",
                "blocked_on": ["a known tenant"], "coverage": {
                    "searched": [], "skipped": [], "complete": False}}

    tier = max(1, min(3, int(tier)))
    searched, skipped, blocked = [], [], []

    # --- tier 1 ---------------------------------------------------------
    rules = _rules(tenant)
    searched.append("rules")
    # `blocked` is now reserved for the one thing that makes OUTPUT unsafe:
    # without a ban list, the validator has nothing to check against and
    # "clean" would be a false assurance. Everything else that used to live
    # here is a gap — reported, never a veto. This layer's job is to hand over
    # what it has and say how well-grounded it is; deciding what can be done
    # with that belongs to whatever is reading, which is smarter than a list
    # of missing rows.
    gaps: list[dict] = []
    if not rules["banned_claims"]:
        blocked.append("brand.banned_claims — the validator has nothing to "
                       "check output against, so nothing can be sent safely")
    if not rules["voice_tone"]:
        gaps.append({"missing": "brand.voice.tone",
                     "means": "no measured house voice to match",
                     "fix": "/admin/propose_voice, then set it"})

    bundle = {"tenant": tenant, "system": system, "tier": tier,
              "rules": rules}

    # --- tier 2 ---------------------------------------------------------
    situations, objections, support = {"detected": [], "confident": False,
                                       "why": "tier 1 only"}, [], []
    if tier >= 2:
        situations, objections, support = _situated(
            tenant, utterance, entity_key, audience_key, limit)
        searched.append("situations")
        if utterance:
            searched.append("objections")
            if not situations["confident"]:
                gaps.append({
                    "missing": "a confident situation match",
                    "means": "the objections returned are unranked",
                    "fix": "add a pattern for this phrasing, or approve a "
                           "claim that resembles it",
                    "candidates": situations["candidates"]})
            if not objections:
                gaps.append({
                    "missing": f"an approved objection for "
                               f"{situations['detected'] or 'this question'}",
                    "means": "no pre-approved answer — draft from the rules, "
                             "claims and entities below",
                    "fix": "author one, or approve what is in review"})
    else:
        skipped.append({"what": "situated", "why": "tier 1 requested"})

    bundle["situations"] = situations
    bundle["objections"] = objections

    # Approved proof, whether or not an objection matched. A direct consumer
    # of this bundle got claims only as a by-product of objection support,
    # which meant the account with no objection on file handed over rules and
    # nothing to substantiate them.
    #
    # Still scoped by entity, and that is CORRECTNESS rather than gatekeeping:
    # "generous 32 cm footprint" is not a fact about a different product, and
    # labelling it would not make it one.
    if tier >= 2:
        rows = kb.claims(tenant, situations=situations.get("detected") or None,
                         entity_key=entity_key or None, limit=limit * 2)
        bundle["claims"] = [
            {"claim": c.claim, "evidence": c.evidence or "", "claim_id": c.id,
             "situations": sorted(c.situations or []),
             "scope": c.entity_key or "brand-wide",
             "proves": getattr(c, "proves", "") or ""}
            for c in rows]
        if rows:
            searched.append("claims")
    else:
        bundle["claims"] = []

    # --- what no knowledge base can answer --------------------------------
    #
    # Two refusals that look identical and are not. "Nobody has authored an
    # objection for this" is fixed by writing one. "Where is my order" is not
    # a gap in the knowledge base at all — it is a fact that exists in the
    # store at the moment of asking, and refusing it is as wrong as inventing
    # it. Separating them is what lets a caller act instead of stopping.
    needs: list[dict] = []
    if tier >= 2 and situations.get("detected"):
        from . import lookups
        needs = lookups.needed_for(tenant, situations["detected"], utterance,
                                   entity_key)
        if needs:
            searched.append("lookups")
    bundle["needs_lookup"] = needs
    ready = [n for n in needs if n["ready"]]
    if needs:
        # Deliberately NOT added to `blocked_on`, and that took a failing test
        # to get right. A lookup that cannot run — no parameter, no connection
        # — is still not a knowledge gap, and putting it in the same list made
        # the responder file "where is my order" on the authoring backlog,
        # where no amount of writing could ever satisfy it. Each entry carries
        # its own `ready` and `blocked_because`; a caller reads those.
        if ready:
            # An answer that needs live data is not groundable from the KB
            # alone, and saying so is the honest state — but the caller has
            # everything it needs to change that, which "blocked" would not
            # communicate.
            bundle["action_required"] = [
                {"call": n["tool"], "with": n["have"], "returns": n["returns"]}
                for n in ready]

    # --- tier 3 ---------------------------------------------------------
    entities, convo = [], {"exists": False, "why": "not requested"}
    if tier >= 3:
        if requirements or entity_key:
            entities = kb.match_entities(tenant, requirements or {},
                                         limit=limit, include_unavailable=True)
            searched.append("entities")
            if not entities:
                gaps.append({"missing": "a matching entity",
                             "means": "nothing in the catalogue fits what was "
                                      "asked for",
                             "fix": "re-run catalog_sync, or answer without "
                                    "naming a product"})
        else:
            skipped.append({"what": "entities",
                            "why": "no requirement or entity given"})
        if contact_id:
            convo = cv.state_for(tenant, contact_id=contact_id,
                                 system_key=system)
            searched.append("conversation")
        else:
            skipped.append({"what": "conversation", "why": "no contact given"})
    else:
        skipped.append({"what": "deep", "why": f"tier {tier} requested"})

    bundle["entities"] = entities
    bundle["conversation"] = convo

    # --- the receipt ----------------------------------------------------
    comp = kb.completeness(tenant)
    bundle["blocked_on"] = blocked
    bundle["gaps"] = gaps
    # How much support this bundle actually carries, so a reader can calibrate
    # rather than infer it from what is absent. This is the number that used to
    # be expressed as a refusal.
    bundle["grounding"] = {
        "level": ("answered" if objections and situations.get("confident") else
                  "unranked" if objections else
                  "supported" if (bundle.get("entities") or rules["banned_claims"])
                  else "rules_only"),
        "means": {
            "answered": "an approved objection matches — the response below "
                        "was written and signed off by a human",
            "unranked": "objections exist but the question could not be "
                        "placed; judge relevance yourself",
            "supported": "no pre-approved answer, but the rules, claims and "
                         "entities here are real and current — draft from them",
            "rules_only": "brand rules only. Say less rather than inventing "
                          "specifics, and everything in `gaps` would help",
        }[("answered" if objections and situations.get("confident") else
           "unranked" if objections else
           "supported" if (bundle.get("entities") or rules["banned_claims"])
           else "rules_only")],
    }
    bundle["coverage"] = {
        "searched": searched,
        "skipped": skipped,
        "counts": {
            "objections": len(objections),
            "support_claims": len(support),
            "entities": len(entities),
            "open_commitments": len(convo.get("open_commitments", [])),
        },
        # Complete means "everything this request asked for was looked at and
        # grounded". A thin bundle that reads as complete is the failure the
        # receipt exists to prevent, so this is never optimistic.
        "complete": not blocked and not any(
            s["what"] in ("objections", "situated") for s in skipped),
        "account_ready": comp.get("ready", False),
        "account_missing": comp.get("missing", []),
    }
    return bundle
