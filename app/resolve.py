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

import logging

from . import bundle as _pkg, conversation as cv, kb, tenants

log = logging.getLogger(__name__)

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


def _rules(tenant: str, system: str = "", guidance_also: tuple = ()) -> dict:
    """Tier 1. Identity and the constraints that must never be violated.

    Two shapes on purpose. `block` is the prose already written for injection —
    `tenants.agent_block` was built for exactly this and is the right size. The
    structured fields beside it are what a deterministic validator reads, and a
    validator cannot parse prose.

    **What this pipeline has been taught rides along with it.**
    `systems.guidance_block` renders a system's standing guidance and the edits
    humans made to its recent drafts. It is appended HERE, in the one function
    every consumer of a bundle already reads, because the alternative was
    adding a render to each skill by hand — and `feedback_block` spent its
    whole life with no caller precisely because wiring it meant touching seven
    places. One append, and every skill, the responder and the mail path all
    draft with it.

    Scoped to `system`, never tenant-wide: a lesson learned answering support
    mail must not quietly change how the ad copy reads. With no system named,
    there is no guidance — a bundle that does not know which pipeline it is for
    has no business carrying one pipeline's corrections.

    Kept as its own key as well as appended, so a caller that renders the parts
    separately can still show it under its own heading rather than buried in
    the identity prose.
    """
    b = kb.brand(tenant)
    block = tenants.agent_block(tenant)
    guidance = ""
    if system:
        from . import systems as _sys
        guidance = _sys.guidance_block(tenant, system, also=guidance_also)
    return {
        "block": block + guidance,
        "guidance": guidance,
        # `craft` is NOT folded into `block` here — it is added to the bundle
        # further down, once the situations are known, so a lesson can be
        # matched to what is actually being asked rather than injected at
        # every account on every turn.
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
            guidance_also: tuple = (),
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
    rules = _rules(tenant, system, guidance_also=tuple(guidance_also or ()))
    searched.append("rules")
    if rules["guidance"]:
        searched.append("guidance")
    # `blocked` is now reserved for the one thing that makes OUTPUT unsafe:
    # without a ban list, the validator has nothing to check against and
    # "clean" would be a false assurance. Everything else that used to live
    # here is a gap — reported, never a veto. This layer's job is to hand over
    # what it has and say how well-grounded it is; deciding what can be done
    # with that belongs to whatever is reading, which is smarter than a list
    # of missing rows.
    gaps: list[dict] = []
    _claims_pool = _claims_flat = 0
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

    # OBJECTIONS FOR WORK THAT ASKS NO QUESTION.
    #
    # `_situated` returns early with `([], [], [])` when there is no utterance,
    # which is EVERY generative system — a campaign, an article, an ad. That is
    # right for RANKING (there is no question to rank against) and wrong for
    # SUPPLY: the account's approved hesitations are exactly what a
    # bottom-of-funnel email should answer, and they never arrived.
    #
    # Worse than absent, it read as denial. `funnel.inputs_for` only falls back
    # when `objections is None`, so an empty list defeated the fallback and the
    # run reported "no approved objections are on file" — on an account with
    # eight. That sentence reaches the owner twice: in the run notes, and on the
    # Assurance tab as `funnel:objection`, where it sends them to author
    # knowledge they already have. A gap report that is wrong is worse than no
    # gap report, because it is acted on.
    #
    # Unranked and said so, the same shape `_situated` already uses when it
    # cannot place an utterance: hand over what the account has, marked, and
    # let the consumer judge. Scoped by entity when one is named, because a
    # hesitation about one product is not a fact about another.
    if tier >= 2 and not objections and not utterance:
        rows = kb.objections(tenant, audience_key=audience_key,
                             entity_key=entity_key or None)[:limit]
        objections = [{
            "objection_id": o.id, "objection": o.objection,
            "response": o.response,
            "situations": list(o.situations or []),
            "entity_key": o.entity_key or "",
            "relevance": "unranked — this work asks no question to rank against",
            "support": [],
        } for o in rows]
        if objections:
            searched.append("objections")

    bundle["objections"] = objections

    # WHO IS READING, in their own words. `KbAudience` carries pains,
    # vocabulary and buying triggers, `funnel.inputs_for` reads all three off
    # `bundle["audiences"]` — and nothing ever put them there. Unlike claims
    # and objections the funnel has no fallback fetch for audiences, so the
    # value was `None` in every drafting system this platform has: the ad, the
    # email and the article all wrote in the brand's words because the buyer's
    # were never handed over. It failed silently, too — an absent audience is
    # not in `thin`, so the run said nothing and the account looked like one
    # with no audiences on file.
    #
    # Tier 2, beside the objections: one query, and it situates rather than
    # deepens. `kb.audiences` already filters to approved.
    bundle["audiences"] = ([
        {"key": a.key, "name": a.name, "pains": list(a.pains or []),
         "vocabulary": list(a.vocabulary or []),
         "buying_trigger": a.buying_trigger or "",
         "decision_timeline": a.decision_timeline or ""}
        for a in kb.audiences(tenant)] if tier >= 2 else [])
    if tier >= 2:
        searched.append("audiences")

    # THE ONE READER THIS WORK IS FOR — singular, and separate from the roster.
    #
    # `bundle["audiences"]` is the whole cast, and it has exactly one
    # legitimate consumer: `funnel.proposals`, which SUGGESTS which ads are
    # worth making and whose whole product is the cross-product of personas.
    # Every DRAFTER was reading the same roster and `funnel.inputs_for` was
    # concatenating it — so a Baci email was briefed that its reader wants a
    # gift that feels chosen, already owns plenty, AND wants the look cheaply.
    # Three real buyers merged into one contradictory instruction.
    #
    # Mass marketing speaks to a segment, so it must speak to ONE of them. A
    # one-to-one reply has an actual person and needs none of this, which is
    # why this is empty rather than guessed when nobody named a reader.
    bundle["audience"] = {}
    if tier >= 2 and audience_key:
        _match = [a for a in (bundle.get("audiences") or [])
                  if a.get("key") == audience_key]
        if _match:
            bundle["audience"] = _match[0]
        else:
            # NAMED AND NOT FOUND is a different fact from nobody naming one,
            # and it is the more urgent: somebody chose a reader that this
            # account does not have approved.
            gaps.append({
                "missing": f"the audience {audience_key!r}",
                "means": "it was named but is not an approved persona for "
                         "this account, so the work has no reader",
                "fix": "pick one that exists, or approve that persona"})

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
        # HOW MUCH WAS HELD BACK, and how much of the pile can never be
        # narrowed. A claim with no situation tag and no entity is brand-wide
        # proof: selectable whenever nobody asks for a situation, which for a
        # campaign or an article is always. Those are the rows that compete
        # with each other on every single draft, so the ratio between them and
        # what actually gets offered IS the clutter, and it belongs on the
        # receipt rather than in somebody's head.
        _pool = kb.claims(tenant, entity_key=entity_key or None)
        _claims_pool = len(_pool)
        _claims_flat = sum(1 for c in _pool
                           if not (c.situations or []) and not c.entity_key)
        bundle["claims"] = [
            {"claim": c.claim, "evidence": c.evidence or "", "claim_id": c.id,
             "situations": sorted(c.situations or []),
             "scope": c.entity_key or "brand-wide",
             "proves": getattr(c, "proves", "") or "",
             # WHAT KIND of proof this is, and what that kind PERMITS.
             # `kb.PROOF_USAGE` has always held the rule that a testimonial is
             # quoted verbatim and never reworded — but it stopped at the
             # console, where it was shown to a human reviewing the claim. No
             # bundle carried it, so no generator could obey it and no
             # validator could enforce it. A rule visible only to the person
             # who is not writing the copy is not a rule.
             "proof_type": (getattr(c, "proof_type", "") or "").lower(),
             "strength": getattr(c, "strength", "") or "",
             # WHO THE READER MAY BE TOLD SAID THIS — human-owned, and the
             # ONLY thing a credit line may be built from. Deliberately not
             # `source`, which is internal provenance ("captured", "stated on
             # https://…") and would be nonsense under a pull-quote. A
             # generator asked to supply a credit it cannot know will invent a
             # plausible one, which is how a live email credited a line to
             # "Eien Health Research" (2026-08-22).
             "attributed_to": getattr(c, "attributed_to", "") or "",
             "usage_rule": kb.usage_rule(getattr(c, "proof_type", "") or "")}
            for c in rows]
        if rows:
            searched.append("claims")

        # WHETHER THIS BRAND HOLDS MORE THAN ONE POSITION, and which ranges
        # hold them. Carried on every bundle rather than fetched by the one
        # generator that happens to think of it: a copywriter, a script and an
        # ad all have the same way of going wrong here — arguing from the
        # product in front of them to a theory of taste the catalogue next
        # door contradicts.
        bundle["contested_positioning"] = [
            {"claim": c.claim, "scope": c.entity_key or "brand-wide",
             "claim_id": c.id}
            for c in kb.contested_positioning(tenant)]
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
            # A NAMED entity is an INSTRUCTION, not a ranking hint. `entity_key`
            # only ever opened this branch — it was never passed to the ranker —
            # so with no `requirements` (which is every campaign) the caller got
            # whatever `match_entities` ranks first with nothing to rank on:
            # alphabetical order. An owner who set "Featured entity: Firenze" on
            # a plan got the catalogue's first three rows and no way to tell.
            # The named one leads; a ranked window that missed it is not a
            # reason to drop it, so it is fetched directly.
            if entity_key:
                rest = [e for e in entities if e.get("key") != entity_key]
                named = [e for e in entities if e.get("key") == entity_key]
                if not named:
                    named = [{"key": r.key, "name": r.name, "type": r.type,
                              "price": r.price, "description": r.description,
                              "attributes": r.attributes or {},
                              "availability": r.availability or ""}
                             for r in kb.entities(tenant, available_only=False)
                             if r.key == entity_key]
                if named:
                    entities = named + rest
                else:
                    gaps.append({"missing": f"the entity {entity_key!r}",
                                 "means": "it was named but is not in the "
                                          "catalogue under that key",
                                 "fix": "re-run catalog_sync, or pick the "
                                        "entity again from the list"})
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

        # What was said BEFORE any of this existed. `conversation` covers the
        # thread a system is running; the archive covers the years of email and
        # documents that predate it — which is where "what did we agree in
        # March" actually lives, and why an agent kept asking for it.
        if utterance:
            from . import archive
            found = archive.search(tenant, utterance, limit=3)
            hits = found["hits"]
            # A thread's attachments travel WITH it. The invoice is usually
            # where the answer actually is, and a covering email that says
            # "please see attached" is the least useful sentence in the inbox.
            from . import archive as _ar
            for h in hits:
                if h.get("kind") == "thread" and h.get("thread_id"):
                    docs = _ar.for_thread(tenant, h["thread_id"])
                    if docs:
                        h["attachments"] = docs
            bundle["correspondence"] = hits
            bundle["correspondence_coverage"] = found["coverage"]
            searched.append("correspondence")
            if found["degraded"]:
                gaps.append({
                    "missing": "part of the correspondence archive",
                    "means": found["degraded"],
                    "fix": "/admin/archive_index?tenant=&kind=thread"})
        else:
            skipped.append({"what": "correspondence",
                            "why": "no utterance to search the archive with"})
    else:
        skipped.append({"what": "deep", "why": f"tier {tier} requested"})

    bundle["entities"] = entities
    bundle["conversation"] = convo
    bundle.setdefault("correspondence", [])

    # What we already said, that may no longer be true.
    #
    # Correspondence comes back as prose and reads uniformly true: a reply
    # saying a cup is out of stock is as confident in September as it was in
    # August, and nothing in the sentence marks which half was a reading from
    # the store. `ledger.perishable` asks the OUTPUT instead of the sentence —
    # every lookup that fed a body has a half-life, and past it the reply must
    # not be repeated without checking.
    #
    # Filed beside the correspondence rather than removed from it. What was
    # said is a fact about the conversation and stays true whatever the stock
    # does now; the drafter needs to know it was said AND that it has aged.
    # What worked at a SIMILAR account, and it ranks last on purpose.
    #
    # This is the one thing in a bundle that did not come from this client.
    # Precedence here is the same rule claims already use — relevance, then
    # specificity, then strength — and a cross-client lesson is the least
    # specific thing that can be said about anything, so it sits at the bottom
    # and says so in its own text. It is technique, never a fact, and it can
    # never carry a claim_id: see `app/craft.py` for why that line is the whole
    # safety design.
    try:
        from . import craft as _craft
        bundle["craft"] = _craft.block(
            tenant, situations.get("detected") or [])
        if bundle["craft"]:
            searched.append("craft")
    except Exception:                                            # noqa: BLE001
        bundle["craft"] = ""     # borrowed technique must never lose a draft

    from . import ledger as _ledger
    bundle["perishable"] = _ledger.perishable(
        tenant, conversation_id=(convo or {}).get("id", "") if isinstance(convo, dict) else "")
    if bundle["perishable"]:
        searched.append("perishable facts")

    # --- the receipt ----------------------------------------------------
    comp = kb.completeness(tenant)
    # SAY WHEN THE PILE IS THE PROBLEM.
    #
    # The rule is the honest one and needs no tuned threshold: MORE untagged
    # brand-wide claims than can ever be offered at once means some of them
    # are permanently competing for the same slots. Under that, everything on
    # file can be shown and there is nothing to report.
    #
    # Not a refusal. Authoring more proof is not the fix and neither is
    # deleting any — tagging or scoping what is already written is, because
    # that is what lets selection narrow instead of rotate.
    _offered_n = len(bundle.get("claims") or [])
    if _claims_flat and _offered_n and _claims_flat > _offered_n:
        gaps.append({
            "missing": "situation tags or an entity on most approved claims",
            "means": (f"{_claims_flat} of {_claims_pool} claims are brand-wide "
                      f"and untagged, so nothing can narrow them and they "
                      f"compete on every draft — only {_offered_n} can be "
                      f"offered at a time, so selection rotates rather than "
                      f"choosing"),
            "fix": "tag or scope what is on file; authoring more will not help"})

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
            "audiences": len(bundle.get("audiences") or []),
            "support_claims": len(support),
            # The clutter, as two numbers a person can act on.
            "claims_offered": len(bundle.get("claims") or []),
            "claims_selectable": _claims_pool,
            "claims_unnarrowable": _claims_flat,
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
    # THE PACKAGE AGAINST WHAT IT PROMISED. `bundle.PARTS` declares every part
    # this layer hands over; this checks the thing actually built against it.
    #
    # Reported, never a veto — the rule this whole module runs on. But
    # reported LOUDLY, because the failure it catches is the one that hides:
    # `audiences` was read by every drafter's funnel brief and supplied by
    # nobody for the life of the codebase, and the only reason it took two
    # years to find is that nothing ever compared what was carried against
    # what was expected.
    _absent = _pkg.verify(bundle)
    if _absent:
        bundle["coverage"]["promised_but_absent"] = _absent
        log.error("resolve(%s): the package is missing declared part(s): %s "
                  "— a consumer reading one of these gets None and no gap "
                  "note", tenant, ", ".join(_absent))
    return bundle
