"""Knowledge Base access + seeding.

Read side of the KB. Everything here is deterministic — no model calls. The
brief assembler queries through these functions, the validator enforces
against them, and generators are only ever handed what these return.

Rule that keeps the platform a platform: customisation lives in these rows,
never in forked code. A new tenant is new data, not a new module.
"""
from __future__ import annotations

import datetime as dt
import logging

from . import db, provenance as prov

log = logging.getLogger("kb")

# Controlled situation vocabulary. Claims are tagged with these and the
# assembler matches on them, so proof selection is a query rather than a model
# picking whichever number sounds best.
SITUATIONS = {
    # who they are
    "ecom_dtc", "ecom_inventory", "digital_products", "coaching",
    "local_venue", "b2b_spec", "real_estate", "food_bev",
    # what's wrong
    "scaling", "margin_problem", "ads_not_working", "no_traffic",
    "pricing_fear", "email_problems", "new_channel", "us_market_entry",
    # what they doubt about you
    "team_exists", "solo_operator_doubt", "big_spender", "wants_operator",

    # Consumer- and trade-side situations. The set above was written for the
    # agency selling B2B services; a tableware brand's claims have nowhere to
    # live in it. These let product tenants tag proof at all.
    #
    # NOTE: the proper fix is a per-tenant vocabulary stored as data — a module
    # constant shared by every tenant is exactly the kind of customisation that
    # decision #3 says must not live in code. Tracked, not yet built.
    "gifting", "occasion_hosting", "collector", "replacement_reorder",
    "trade_specification", "wellness_routine", "subscription_lapse",
    "venue_enquiry", "capacity_fit",
}


# What each kind of proof MAY be used for. `proof_type` records where a claim
# came from; this records what that origin permits, which is a different
# question and the one a generator actually needs answered.
#
# The testimonial rule is the load-bearing one. A customer's review reworded as
# brand copy is a fabrication however true the sentiment was — "the colours are
# better in person" said BY the brand is an unevidenced claim, and said as a
# quote from a named customer it is a fact about what someone said. The words
# and the attribution are the evidence, so neither may be edited away.
PROOF_USAGE = {
    "testimonial": "Quote verbatim, with attribution. Never paraphrase, "
                   "reword, or restate as the brand's own claim.",
    "case_study": "May be summarised. Keep the numbers exact.",
    "data": "May be restated. The figure may not change.",
    "certification": "State exactly as certified. No embellishment.",
    "spec": "State exactly. A spec restated loosely is a wrong spec.",
}

# Proof whose wording IS the evidence, so the text is immutable once captured.
VERBATIM_ONLY = ("testimonial",)


def usage_rule(proof_type: str) -> str:
    return PROOF_USAGE.get((proof_type or "").strip().lower(), "")


# --------------------------------------------------------------------------
# Read accessors — the only way the pipeline touches the KB
# --------------------------------------------------------------------------

def brand(tenant: str) -> db.KbBrand | None:
    with db.SessionLocal() as s:
        return s.get(db.KbBrand, tenant)


def banned_claims(tenant: str) -> list[str]:
    b = brand(tenant)
    return list(b.banned_claims or []) if b else []


def claims(tenant: str, situations: list[str] | None = None,
           limit: int = 0, entity_key: str | None = None) -> list[db.KbClaim]:
    """Active, unexpired claims, ranked by how well they fit the situation.

    Scoped by entity, and the default is the safe one. With no `entity_key`
    you get only what is true of the BRAND — a fact that is only true of one
    product ("generous 32 cm footprint") must not turn up in a newsletter about
    something else. Name an entity and you get the brand's claims plus that
    entity's, which is what writing about a product actually needs.

    Ranking is SPECIFICITY first, strength second. Sorting on strength alone
    ties every "strong" claim and breaks on insertion order — which had a
    prospect complaining about email deliverability being answered with a
    Shopify exit story. A claim matching two of the buyer's situations beats
    one matching a single situation, however impressive its number.
    """
    now = dt.datetime.now(dt.timezone.utc)
    want = set(situations or [])
    with db.SessionLocal() as s:
        # Approved AND lifecycle-active. `review` is the approval axis and
        # `status` is the lifecycle one; a row needs both to be selectable.
        q = s.query(db.KbClaim).filter(
            db.KbClaim.tenant == tenant,
            db.KbClaim.review == prov.APPROVED,
            db.KbClaim.status == "active",
        )
        if entity_key:
            q = q.filter(db.KbClaim.entity_key.in_(["", None, entity_key]))
        else:
            q = q.filter(db.KbClaim.entity_key.in_(["", None]))
        rows = q.all()
        scored = []
        for r in rows:
            if r.expires_at and db.as_utc(r.expires_at) < now:
                continue  # stale proof is not selectable
            overlap = len(set(r.situations or []) & want)
            if want and not overlap:
                continue
            scored.append((-overlap, 0 if r.strength == "strong" else 1, r))
        scored.sort(key=lambda t: (t[0], t[1]))
        out = [r for _, _, r in scored]
        s.expunge_all()
        return out[:limit] if limit else out


def claim_inventory(tenant: str) -> dict[str, list[db.KbClaim]]:
    """Every claim on file, split by why it is or isn't selectable.

    `claims()` drops pending, retired and expired rows silently, which is right
    for selection and wrong for a reader: it makes an account with no proof look
    identical to one whose proof went stale last month. Absence is a third state
    and it has to survive to the surface, so the split is computed here — the one
    place that knows the shape of a claim — rather than re-derived in a template.
    """
    now = dt.datetime.now(dt.timezone.utc)
    out: dict[str, list[db.KbClaim]] = {
        "selectable": [], "pending": [], "expired": [], "retired": []}
    with db.SessionLocal() as s:
        rows = s.query(db.KbClaim).filter(db.KbClaim.tenant == tenant).all()
        s.expunge_all()
    for r in rows:
        review = r.review or prov.APPROVED
        if review == prov.PROPOSED:
            out["pending"].append(r)
        elif review == prov.REJECTED or r.status != "active":
            out["retired"].append(r)          # rejected | retired | conflicted
        elif r.expires_at and db.as_utc(r.expires_at) < now:
            out["expired"].append(r)
        else:
            out["selectable"].append(r)
    return out


def audiences(tenant: str, include_proposed: bool = False) -> list[db.KbAudience]:
    """Approved segments only, unless a reviewer asks to see the rest.

    Every read accessor in this module is a pipeline input, so the approval
    filter belongs here rather than at each call site — a proposal that reaches
    a generator is indistinguishable from a fact once it is in a draft.
    """
    with db.SessionLocal() as s:
        q = s.query(db.KbAudience).filter(db.KbAudience.tenant == tenant)
        if not include_proposed:
            q = q.filter(db.KbAudience.review == prov.APPROVED)
        rows = q.all()
        s.expunge_all()
        return rows


def audience(tenant: str, key: str) -> db.KbAudience | None:
    with db.SessionLocal() as s:
        row = s.query(db.KbAudience).filter(
            db.KbAudience.tenant == tenant, db.KbAudience.key == key).first()
        if row:
            s.expunge(row)
        return row


def objections(tenant: str, audience_key: str = "",
               include_proposed: bool = False,
               entity_key: str | None = None,
               any_entity: bool = False,
               situations: list[str] | None = None) -> list[db.KbObjection]:
    """Approved objections for a tenant; narrowed to a segment when one is given.

    Entity scope works exactly as it does for claims, and matters more here:
    "Is it dishwasher safe? Yes, every piece" is a true and useful answer about
    one product and a nonsense answer about a pouf.

    No audience_key means "everything" — not "only the universal ones". The
    latter silently undercounts, which made completeness() report 5 of 6.
    """
    with db.SessionLocal() as s:
        q = s.query(db.KbObjection).filter(db.KbObjection.tenant == tenant)
        if not include_proposed:
            q = q.filter(db.KbObjection.review == prov.APPROVED)
        if any_entity:
            # Every objection this account holds, whatever it is scoped to.
            # For SELECTION that would be wrong — it is how a porcelain answer
            # reaches a pouf. For a person maintaining the knowledge base it is
            # the only honest view: the Knowledge tab used to call `objections`
            # with no entity, get back the brand-wide subset, and present it as
            # the list. Every product-scoped answer was invisible on the one
            # page whose job is showing what the account knows.
            pass
        elif entity_key:
            q = q.filter(db.KbObjection.entity_key.in_(["", None, entity_key]))
        else:
            q = q.filter(db.KbObjection.entity_key.in_(["", None]))
        rows = q.all()
        if audience_key:
            rows = [r for r in rows
                    if not r.audience_key or r.audience_key == audience_key]
        s.expunge_all()

    if situations:
        # Ranked, never filtered. An objection tagged for this situation comes
        # first; an untagged one is general and still useful. Dropping the
        # general ones would lose "can you guarantee a result", which applies
        # to every enquiry any client ever gets.
        want = set(situations)
        rows.sort(key=lambda r: (-len(set(r.situations or []) & want),
                                 0 if (r.situations or []) else 1))
    return rows


def support_for(tenant: str, objection: db.KbObjection,
                limit: int = 2) -> list[db.KbClaim]:
    """The claims that back up an answer.

    Two ways, in order of authority. A `claim_id` pinned by a human is a
    decision and wins outright. Otherwise the situations are the join: a claim
    tagged for the same problem this objection raises is, by construction,
    proof aimed at the same doubt.
    """
    if objection is None:
        return []
    if objection.claim_id:
        with db.SessionLocal() as s:
            row = s.get(db.KbClaim, objection.claim_id)
            if row and row.tenant == tenant and row.review == prov.APPROVED:
                s.expunge(row)
                return [row]
    tags = list(objection.situations or [])
    if not tags:
        return []
    return claims(tenant, situations=tags, limit=limit,
                  entity_key=objection.entity_key or None)


def situations(tenant: str, include_proposed: bool = False) -> set[str]:
    """The valid situation tags for one tenant.

    Falls back to the shared default set only when a tenant has authored none,
    so existing behaviour is preserved while new tenants get their own words.

    **Proposed tags are excluded**, and this matters more than it looks. This
    set is what `add_claim` validates against, so it decides which claims may
    exist at all. While only the seed wrote here every row was approved and the
    filter was moot; the moment the extractor could propose a tag it wished
    existed, returning proposed rows would have let a machine widen the
    vocabulary and then immediately file claims against its own invention —
    review gate intact and bypassed in the same breath.

    The test is `!= PROPOSED` rather than `== APPROVED` on purpose. Rows
    written before this table carried a review state have none, and they have
    been in use all along; excluding them would empty the vocabulary of every
    existing tenant and fall through to the shared constant, which is how the
    agency ended up unable to match anything in the first place.
    """
    with db.SessionLocal() as s:
        q = s.query(db.KbSituation).filter(db.KbSituation.tenant == tenant)
        rows = q.all()
        tags = {r.tag for r in rows
                if include_proposed or (r.review or "") != prov.PROPOSED}
    return tags or set(SITUATIONS)


def situation_rows(tenant: str) -> list[db.KbSituation]:
    """The tenant's diagnostic vocabulary in full, for reading rather than matching.

    `situations()` returns bare tags for validation. This returns the rows, so
    whoever is authoring a claim can see what each tag means and what phrasing
    triggers it. `add_claim` refuses a tag outside this set — that refusal is
    what silently cost Baci and Ironside four claims at seed time — so the
    vocabulary has to be legible wherever claims are written.
    """
    with db.SessionLocal() as s:
        rows = s.query(db.KbSituation).filter(
            db.KbSituation.tenant == tenant).order_by(db.KbSituation.tag).all()
        s.expunge_all()
        return rows


def situation_patterns(tenant: str) -> dict[str, list[tuple]]:
    """Tag -> match patterns, for the diagnosis step."""
    with db.SessionLocal() as s:
        rows = s.query(db.KbSituation).filter(
            db.KbSituation.tenant == tenant).all()
        out = {r.tag: [tuple(p) for p in (r.patterns or []) if p] for r in rows}
    return {k: v for k, v in out.items() if v}


def _tok(text: str) -> set[str]:
    """Informative words. Short ones carry no signal and dominate any overlap."""
    import re as _re
    return {w for w in _re.findall(r"[a-z][a-z'-]{3,}", (text or "").lower())}


#: A single shared word is a coincidence, not a signal. Checked BEFORE the
#: normalised score because the score can be inflated by a short candidate:
#: one word shared with a four-word fragment already scores 0.5.
MIN_SHARED_WORDS = 2

#: Shared words over the square root of the candidate's length. Two words
#: shared with a sixteen-word sentence lands exactly on this floor; anything
#: below it is too thin to carry a tag nobody is going to re-read.
MIN_LEARNED_SCORE = 0.5


def suggest_tags(tenant: str, text: str, limit: int = 2,
                 entity_key: str = "", exclude_claim_id: str = "") -> dict:
    """Best-guess situation tags for a candidate claim, and why.

    ``exclude_claim_id`` scores against every row on file *except* that one.
    A claim already in the vocabulary matches itself perfectly and tells you
    nothing, so anything re-tagging an existing row — or measuring whether the
    floors below are set right, which is leave-one-out over real claims — has
    to leave it out.

    Two sources, in order of authority:

      1. **Patterns** — the tenant's own `KbSituation` triggers. An exact match
         is a decision, not a guess, and `basis` says so.
      2. **The claims already approved for this account.** Every active claim
         carries tags a human chose, so the words in them are a worked example
         of what each tag means here. A candidate is scored against that,
         which means the tagging gets better every time you approve something
         rather than staying as good as the day the patterns were written.

    Retired claims are the negative signal: something close to what was
    rejected before is flagged rather than suggested, because re-proposing what
    was already turned down is how a review queue teaches you to stop reading it.

    No model call — this is word overlap over the tenant's own rows, so it is
    explainable and it cannot invent a tag that does not exist.

    **A weak overlap now returns no tag.** This function was written to seed a
    review queue, where a human reads `basis` and catches a bad guess. It is
    also the only classifier the account has, so anything that routes on
    situations inherits it — and there, nobody is reading `basis`. The score
    was computed and thrown away, and the gate was "shared any word at all", so
    a one-word overlap asserted a tag with exactly the authority of a
    twelve-word one. That is the same shape as a keyword match asserting
    ``fits: True`` (DEFECTS 2.5): weak evidence and strong evidence arriving
    indistinguishable. Absence is a third state, so it survives to the caller:

    * ``confident`` — whether ``tags`` may be acted on without a human.
    * ``score`` — the top candidate's normalised overlap. ``None`` for a
      pattern hit, because a decision does not have a confidence; a number
      there would be the metadata-as-content mistake in a new place.
    * ``candidates`` — every tag considered with its score and shared-word
      count, **including the ones that fell below the floor**. A reviewer
      should still see "we wondered about pricing and weren't sure" rather
      than a blank, and a runtime caller should be able to log the near-miss.

    ``tags`` stays empty unless the guess clears both floors. Callers that
    file proposals get an untagged proposal, which is a supported state that
    routes to a human (``add_claim`` allows it for proposals, and refuses it
    at approval). Callers that route live traffic should check ``confident``
    and refuse rather than answer against a tag nobody stands behind.
    """
    valid = situations(tenant)
    words = _tok(text)
    if not words:
        return {"tags": [], "basis": "", "confident": False, "score": None,
                "candidates": [], "similar_to_rejected": "",
                "path": "none", "degraded": ""}

    inv = claim_inventory(tenant)
    rejected_like = ""
    for row in inv["retired"]:
        if exclude_claim_id and row.id == exclude_claim_id:
            continue
        # Rejecting "dishwasher safe" for the pouf must not teach the tagger
        # that the same sentence is bad for the porcelain. A rejection only
        # carries across rows that share a scope.
        rek = (getattr(row, "entity_key", "") or "")
        if rek and entity_key and rek != entity_key:
            continue
        overlap = words & _tok(row.claim)
        if len(overlap) >= max(3, len(words) // 3):
            rejected_like = row.claim[:120]
            break

    # 1. patterns
    hits = []
    for tag, patterns in situation_patterns(tenant).items():
        for pat in patterns:
            if all(str(w).lower() in (text or "").lower() for w in pat):
                hits.append(tag)
                break
    if hits:
        # The warning rides along even here. A pattern match tells you which
        # tag applies; it says nothing about whether this exact sentence has
        # already been turned down.
        return {"tags": hits[:limit], "basis": "pattern", "confident": True,
                "score": None,
                "candidates": [{"tag": t, "score": None, "shared": None}
                               for t in hits[:limit]],
                "similar_to_rejected": rejected_like,
                "path": "pattern", "degraded": ""}

    # 2. semantic — nearest approved claims by meaning rather than by words.
    #
    # This is the tier word overlap cannot reach: "will it survive the
    # dishwasher" and "is it dishwasher safe" share almost no informative
    # words and are the same question. It sits BELOW patterns, which remain a
    # decision, and ABOVE overlap, which remains the floor and the offline
    # path.
    #
    # When it cannot run — no key, no network, nothing indexed — the cascade
    # continues to overlap and `degraded` carries the reason. A fallback that
    # looks like the real path is how the extractor ran at 0% recall for weeks.
    degraded = ""
    try:
        from . import embed
        hits, why, _scan = embed.search(tenant, "claim", text,
                                        limit=max(4, limit * 2))
        degraded = why
        if hits:
            by_id = {r.id: r for r in inv["selectable"]}
            per_tag: dict[str, float] = {}
            for h in hits:
                if exclude_claim_id and h["row_id"] == exclude_claim_id:
                    continue
                row = by_id.get(h["row_id"])
                if not row:
                    continue          # retired or approved-away since indexing
                for tag in (row.situations or []):
                    if tag in valid:
                        per_tag[tag] = max(per_tag.get(tag, 0.0), h["score"])
            if per_tag:
                ranked = sorted(per_tag.items(), key=lambda kv: -kv[1])[:limit]
                return {
                    "tags": [t for t, _ in ranked],
                    "basis": ("means the same as approved claims tagged "
                              + ", ".join(t for t, _ in ranked)),
                    "confident": True,
                    "score": round(ranked[0][1], 4),
                    "candidates": [{"tag": t, "score": round(sc, 4),
                                    "shared": None} for t, sc in ranked],
                    "similar_to_rejected": rejected_like,
                    "path": "semantic", "degraded": "",
                }
    except Exception as exc:  # noqa: BLE001 — recall must never break tagging
        degraded = f"semantic path errored: {exc.__class__.__name__}"
        log.warning("semantic tagging failed for %s: %s", tenant, exc)

    # 2. learned from what has already been approved here
    per_tag: dict[str, set[str]] = {}
    for row in inv["selectable"]:
        if exclude_claim_id and row.id == exclude_claim_id:
            continue
        for tag in (row.situations or []):
            if tag in valid:
                per_tag.setdefault(tag, set()).update(
                    _tok(f"{row.claim} {row.evidence or ''}"))
    scored = []
    for tag, vocab in per_tag.items():
        shared = words & vocab
        if shared:
            # Normalise by the candidate's length so a long sentence does not
            # out-score a precise one purely by having more words.
            scored.append((len(shared) / (len(words) ** 0.5), tag, shared))
    scored.sort(reverse=True)

    # Everything considered, floor or no floor. A near-miss is information —
    # it is what tells a reviewer the vocabulary is missing a tag rather than
    # that the sentence was unreadable.
    candidates = [{"tag": tag, "score": round(score, 3), "shared": len(shared)}
                  for score, tag, shared in scored[:limit]]

    if not scored:
        return {"tags": [], "basis": "", "confident": False, "score": None,
                "candidates": [], "similar_to_rejected": rejected_like,
                "path": "none", "degraded": degraded}

    top_score, _, top_shared = scored[0]
    confident = (len(top_shared) >= MIN_SHARED_WORDS
                 and top_score >= MIN_LEARNED_SCORE)

    if not confident:
        return {
            "tags": [],
            "basis": (f"too thin to place — best was {scored[0][1]} on "
                      f"{len(top_shared)} shared word"
                      f"{'' if len(top_shared) == 1 else 's'} "
                      f"(score {top_score:.2f}, floor {MIN_LEARNED_SCORE})"),
            "confident": False,
            "score": round(top_score, 3),
            "candidates": candidates,
            "similar_to_rejected": rejected_like,
            "path": "overlap", "degraded": degraded,
        }

    # Only tags that clear the floor themselves ride along. The second tag is
    # a suggestion in its own right, not a passenger on the first one's score.
    kept = [t for score, t, shared in scored[:limit]
            if len(shared) >= MIN_SHARED_WORDS and score >= MIN_LEARNED_SCORE]
    return {"tags": kept,
            "basis": "resembles approved claims tagged " + ", ".join(kept),
            "confident": True,
            "score": round(top_score, 3),
            "candidates": candidates,
            "similar_to_rejected": rejected_like,
            "path": "overlap", "degraded": degraded}


#: Below this many human-tagged claims, a percentage over them is theatre.
#: The same rule the platform already applies to revenue on small lists:
#: report the number, refuse the conclusion.
CALIBRATION_MIN_N = 25

#: (min_shared, min_score) pairs to compare when choosing floors. The live
#: setting is inserted at read time so it is ranked among the alternatives
#: rather than assumed to be the right one.
CALIBRATION_SWEEP = [(1, 0.0), (1, 0.5), (2, 0.0), (2, 0.4), (2, 0.6),
                     (2, 0.8), (3, 0.5), (3, 0.8)]

#: Cosine thresholds to compare for the semantic path. Cosine lives on a
#: different scale from the overlap score and needs its own sweep.
SEMANTIC_SWEEP = [0.45, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85]

#: Below this many samples on EACH side, "these two distributions separate" is
#: a statement about two numbers, not about a classifier. `separable` reports
#: None rather than a boolean that reads as evidence.
MIN_N_FOR_SEPARABLE = 5


def _semantic_floor() -> float:
    from . import embed
    return embed.MIN_SEMANTIC_SCORE


def calibration(tenant: str) -> dict:
    """Are `MIN_SHARED_WORDS` and `MIN_LEARNED_SCORE` right for this account?

    Leave-one-out over every approved claim a human tagged: hide the claim from
    the vocabulary, re-score it, and see whether it recovers the tag the human
    chose and at what score. A claim left in its own vocabulary matches itself
    perfectly and proves nothing, which is what `exclude_claim_id` is for.

    The two failure modes point opposite ways and only real claims can say
    which one is live. A floor set too low places a tag nobody stands behind,
    and a service desk answers with the wrong objection, confidently. A floor
    set too high refuses claims it used to place, and every harvest lands
    untagged.

    Pattern hits are counted separately and excluded from the sweep: a pattern
    match is a decision that never passes through the floors, so folding it in
    would credit them for placements they had no part in.

    Reads only. `n` is the number that decides whether any percentage here is
    worth believing — see `CALIBRATION_MIN_N`.
    """
    rows = [r for r in claim_inventory(tenant)["selectable"] if r.situations]
    pattern, semantic, learned = [], [], []
    degraded = ""

    for row in rows:
        human = sorted({t for t in (row.situations or []) if t})
        text = f"{row.claim} {row.evidence or ''}".strip()
        g = suggest_tags(tenant, text, entity_key=(row.entity_key or ""),
                         exclude_claim_id=row.id)
        rec = {"claim": row.claim[:80], "human": human, "tags": g["tags"],
               "basis": g["basis"], "path": g["path"],
               "top": (g["candidates"] or [None])[0]}
        degraded = degraded or g.get("degraded", "")
        # Three paths now, and only ONE of them passes through the word-overlap
        # floors. Sweeping a semantic placement against MIN_LEARNED_SCORE would
        # credit those floors for a decision they had no part in — the same
        # mistake as folding pattern hits into the sweep.
        if g["path"] == "pattern":
            rec["hit"] = bool(set(g["tags"]) & set(human))
            pattern.append(rec)
        elif g["path"] == "semantic":
            rec["hit"] = bool(set(g["tags"]) & set(human))
            semantic.append(rec)
        else:
            learned.append(rec)

    def _outcome(rec, min_shared, min_score):
        top = rec["top"]
        if not top:
            return "no_overlap"
        if top["shared"] < min_shared or top["score"] < min_score:
            return "refused"
        return "correct" if top["tag"] in rec["human"] else "wrong"

    grid = list(CALIBRATION_SWEEP)
    live = (MIN_SHARED_WORDS, MIN_LEARNED_SCORE)
    if live not in grid:
        grid.append(live)
    sweep = []
    for ms, sc in sorted(grid):
        tally = {"correct": 0, "wrong": 0, "refused": 0, "no_overlap": 0}
        for rec in learned:
            tally[_outcome(rec, ms, sc)] += 1
        sweep.append({"min_shared": ms, "min_score": sc, "live": (ms, sc) == live,
                      **tally})

    right = sorted(r["top"]["score"] for r in learned
                   if r["top"] and r["top"]["tag"] in r["human"])
    wrong = sorted(r["top"]["score"] for r in learned
                   if r["top"] and r["top"]["tag"] not in r["human"])

    # The semantic path has its own floor and had no measurement — the first
    # version of this reported distributions for word overlap only, which is
    # the floor that existed when it was written. Setting MIN_SEMANTIC_SCORE
    # without this is the same guessing the instrument was built to stop.
    sem_right = sorted(r["top"]["score"] for r in semantic
                       if r["top"] and r["top"]["tag"] in r["human"])
    sem_wrong = sorted(r["top"]["score"] for r in semantic
                       if r["top"] and r["top"]["tag"] not in r["human"])

    sem_sweep = []
    for t in SEMANTIC_SWEEP:
        ok = bad = through = 0
        for r in semantic:
            top = r["top"]
            if not top or top["score"] < t:
                # NOT "refused" — raising this floor drops the claim to the
                # word-overlap tier, which may still place it. Calling that a
                # refusal would overstate the cost of a higher floor.
                through += 1
            elif top["tag"] in r["human"]:
                ok += 1
            else:
                bad += 1
        sem_sweep.append({"min_score": t, "correct": ok, "wrong": bad,
                          "falls_through_to_overlap": through,
                          "live": abs(t - _semantic_floor()) < 1e-9})

    def _dist(vals):
        if not vals:
            return None
        return {"n": len(vals), "min": vals[0], "max": vals[-1],
                "p10": vals[max(0, int(len(vals) * 0.10) - 1)],
                "median": vals[len(vals) // 2],
                "p90": vals[min(len(vals) - 1, int(len(vals) * 0.90))]}

    def _separable(a: list, b: list):
        """True, False, or None when there is not enough to say either."""
        if len(a) < MIN_N_FOR_SEPARABLE or len(b) < MIN_N_FOR_SEPARABLE:
            return None
        return min(a) > max(b)

    separable = _separable(right, wrong)
    return {
        "tenant": tenant,
        "n": len(rows),
        "enough_to_calibrate": len(rows) >= CALIBRATION_MIN_N,
        "min_n": CALIBRATION_MIN_N,
        "live_floors": {"min_shared": MIN_SHARED_WORDS,
                        "min_score": MIN_LEARNED_SCORE},
        "pattern": {"n": len(pattern),
                    "agreed": sum(1 for r in pattern if r["hit"]),
                    "misses": [r for r in pattern if not r["hit"]]},
        # The comparison the whole exercise exists for: two scorers on the same
        # claims. Adopt the semantic path because `agreed` moved, not because
        # it is newer.
        "semantic": {"n": len(semantic),
                     "agreed": sum(1 for r in semantic if r["hit"]),
                     "misses": [r for r in semantic if not r["hit"]],
                     "degraded": degraded},
        "semantic_scores": {
            "floor": _semantic_floor(),
            "correct_tag_on_top": _dist(sem_right),
            "wrong_tag_on_top": _dist(sem_wrong),
            "separable": _separable(sem_right, sem_wrong),
            "sweep": sem_sweep,
            "min_n_for_separable": MIN_N_FOR_SEPARABLE,
        },
        "learned_n": len(learned),
        "scores": {"correct_tag_on_top": _dist(right),
                   "wrong_tag_on_top": _dist(wrong)},
        "separable": separable,
        "separable_window": ([max(wrong), min(right)] if separable else None),
        "sweep": sweep,
        "rows": learned,
    }


#: Two claims this close are close enough that a tagger will confuse them.
#: Measured, and then measured again after the first number found nothing: on
#: Baci the outright duplicate scored 0.9672, but the pair that costs two
#: misses under leave-one-out — "Designed in Milan by the Italian design
#: house" against "Baci Milano is an Italian design house" — sits at 0.7641.
#: A floor of 0.85 excluded the very pair the tool was built to find.
LABEL_CONFLICT_SCORE = 0.75


def label_conflicts(tenant: str, min_score: float = LABEL_CONFLICT_SCORE,
                    limit: int = 25) -> list[dict]:
    """Near-identical claims that were tagged differently.

    This is the defect the calibration run surfaced and could not fix. Three of
    Baci's misses were not the classifier being wrong — they were two claims
    saying the same thing under opposite tags, so leave-one-out marked each of
    them wrong using the other as truth. One inconsistency, two failures, and
    no floor anywhere separates them: the worst offender scored **0.9672**,
    which is higher than most correct placements.

    So the fix is upstream of retrieval. A tagger cannot be better than the
    labels it learns from, and this is the queue for making those labels agree.

    Reported, never merged. Same rule as `near_duplicates` and
    `situation_overlaps`: which of two tags is right is a judgement about the
    business, and a machine that picks one is inventing.

    Costs no provider call — both sides are already vectors.
    """
    from . import embed
    inv = {r.id: r for r in claim_inventory(tenant)["selectable"]}
    out = []
    for p in embed.pairs(tenant, "claim", min_score=min_score, limit=limit * 8):
        a, b = inv.get(p["a"]), inv.get(p["b"])
        if not a or not b:
            continue                     # retired since indexing
        ta, tb = set(a.situations or []), set(b.situations or [])
        if not ta or not tb or ta == tb:
            continue                     # identical labelling is not a conflict

        # The predicate is DIFFER, not "share nothing", and the first version
        # got that wrong — it required disjoint sets and so reported zero on an
        # account with a known 0.9672 conflict. Sharing a tag does not stop the
        # confusion: retrieval ranks by score and takes the top tag, so
        # {collector, replacement_reorder} against {collector, gifting} still
        # answers `gifting` and is still marked wrong. The overlap is what
        # makes it subtle, not what makes it harmless.
        shared, only_a, only_b = ta & tb, ta - tb, tb - ta
        disjoint = not shared
        out.append({
            "score": p["score"],
            "disjoint": disjoint,
            "shared": sorted(shared),
            "a": {"id": a.id, "claim": a.claim[:110], "situations": sorted(ta),
                  "only_here": sorted(only_a), "entity_key": a.entity_key or ""},
            "b": {"id": b.id, "claim": b.claim[:110], "situations": sorted(tb),
                  "only_here": sorted(only_b), "entity_key": b.entity_key or ""},
            "why": (
                f"{int(p['score'] * 100)}% the same claim"
                + (", and not one tag in common" if disjoint
                   else f", agreeing on {', '.join(sorted(shared))} and "
                        f"disagreeing on "
                        f"{', '.join(sorted(only_a | only_b))}")
                + " — retrieval takes the top-scoring tag, so whichever of "
                  "these a new claim matches first decides how it is filed"),
        })
    # Worst first: no tags in common is a harder disagreement than a partial
    # one, and a closer pair confuses a tagger more than a distant one.
    out.sort(key=lambda c: (not c["disjoint"], -c["score"]))
    return out[:limit]


def repair_fingerprints(tenant: str, apply: bool = False) -> dict:
    """Recompute claim fingerprints, and report the duplicates that surface.

    Every row edited before the `update_claim` fix carries
    `fingerprint(claim)` where `add_claim` would have written
    `fingerprint(claim, entity_key)`. Until those are rewritten the dedup check
    keeps missing, so this is not cosmetic — it is what stops the next harvest
    filing the same claim a third time.

    Recomputing **collapses nothing**. Two rows landing on one fingerprint is
    reported as a collision and left alone: which of two taggings is right is a
    judgement about the business, and the row that keeps its id is the row
    every objection's `claim_id` still points at. Merge from
    `label_conflicts`, deliberately, one pair at a time.
    """
    changed, collisions = [], {}
    with db.SessionLocal() as s:
        rows = s.query(db.KbClaim).filter(db.KbClaim.tenant == tenant).all()
        for r in rows:
            want = prov.fingerprint(r.claim or "", r.entity_key or "")
            if want != (r.fingerprint or ""):
                changed.append({"id": r.id, "claim": (r.claim or "")[:80],
                                "entity_key": r.entity_key or "",
                                "was": (r.fingerprint or "")[:12],
                                "now": want[:12]})
                if apply:
                    r.fingerprint = want
            collisions.setdefault(want, []).append(
                {"id": r.id, "claim": (r.claim or "")[:80],
                 "situations": sorted(r.situations or []),
                 "entity_key": r.entity_key or ""})
        if apply:
            s.commit()

    dupes = [{"fingerprint": fp[:12], "rows": rs}
             for fp, rs in collisions.items() if len(rs) > 1]
    return {
        "tenant": tenant, "applied": bool(apply),
        "claims": len(rows), "fingerprints_rewritten": len(changed),
        "examples": changed[:5],
        "duplicate_groups": len(dupes), "duplicates": dupes[:10],
        "note": ("nothing was merged — a duplicate group is a decision, and "
                 "the surviving row's id is what every objection's claim_id "
                 "still points at"),
    }


def situation_desc(tenant: str) -> dict[str, str]:
    """Tag -> the headline constraint it implies, in the tenant's own words."""
    with db.SessionLocal() as s:
        rows = s.query(db.KbSituation).filter(
            db.KbSituation.tenant == tenant).all()
        return {r.tag: (r.description or "") for r in rows if r.description}


#: How many new tags one crawl may propose before the answer stops being "add
#: a tag" and starts being "this account's vocabulary is wrong".
MAX_NEW_SITUATIONS = 3


def similar_situation(tenant: str, tag: str) -> str:
    """An existing tag that already covers `tag`, or "".

    Without this the extractor's no-fit path is a tag generator: nothing stops
    `proof_of_scale`, `scale_proof` and `training_volume` all being created for
    the same idea, and a vocabulary of near-synonyms is worse than a short one
    — selection splits across them and no single tag accumulates the approved
    examples that make the learned tagger work.

    Compared against each existing tag AND its description, because the tags
    are slugs and the description is where the meaning actually lives:
    `credibility` and `proof_of_scale` share no characters, but "they doubt we
    can actually do this" and "proof of scale" do.
    """
    want = (tag or "").strip().lower().replace(" ", "_")
    if not want:
        return ""
    words = _tok(want.replace("_", " "))
    for row in situation_rows(tenant):
        if row.tag == want:
            return row.tag
        if prov.similarity(want.replace("_", " "),
                           row.tag.replace("_", " ")) >= 0.6:
            return row.tag
        # A short slug against a sentence: ask what fraction of the proposed
        # tag's words the description already contains, not how alike the two
        # strings are overall — a three-word tag can never look like a
        # twelve-word description however well it is covered by it.
        desc = _tok(row.description or "")
        if words and len(words & desc) / len(words) >= 0.6:
            return row.tag
    return ""


def _situation_users(tenant: str) -> dict[str, set[str]]:
    """Which rows each situation actually tags. The empirical signal.

    Two tags that read differently and are used identically are the same tag.
    `solo_operator_doubt` ("wonders whether one person can carry it") and
    `team_exists` ("wonders whether there is a team behind it") score 0.25 on
    their descriptions and 0.0 on their tags and triggers — no lexical measure
    will ever pair them — but every claim that answers one answers the other.
    Usage sees what words cannot.
    """
    used: dict[str, set[str]] = {}
    with db.SessionLocal() as s:
        for model in (db.KbClaim, db.KbObjection):
            for row in s.query(model).filter(model.tenant == tenant).all():
                for tag in (row.situations or []):
                    used.setdefault(tag, set()).add(f"{model.__name__}:{row.id}")
    return used


def situation_neighbours(tenant: str, tag: str, limit: int = 3) -> list[dict]:
    """The nearest situations to this one, best first, and why each is near.

    This is the context-priority map. When a situation has thin proof behind
    it, the alternative to returning nothing is reaching to its closest
    neighbours — but only in a known order, and only while saying that is what
    happened. `basis` names which signal fired so a caller can decide whether
    to trust it, exactly as `fits` is tri-state rather than a bare boolean:
    widened context is not matched context and must never be reported as it.

      used_together   the two tags land on the same rows. Strongest — it is
                      what the account DOES, not what the words look like.
      reads_alike     descriptions and triggers overlap. Weakest, and blind to
                      the case above.
    """
    rows = {r.tag: r for r in situation_rows(tenant)}
    if tag not in rows:
        return []
    used = _situation_users(tenant)
    mine, me = used.get(tag, set()), rows[tag]
    out = []
    for other, row in rows.items():
        if other == tag:
            continue
        theirs = used.get(other, set())
        together = (len(mine & theirs) / len(mine | theirs)
                    if (mine or theirs) else 0.0)
        words_a = f"{me.description or ''} " + " ".join(
            w for pp in (me.patterns or []) for w in pp)
        words_b = f"{row.description or ''} " + " ".join(
            w for pp in (row.patterns or []) for w in pp)
        alike = prov.similarity(words_a, words_b)
        # Used-together dominates. Reading alike may only break a tie — the
        # same rule the catalogue matcher follows, for the same reason: two
        # signals of different kinds must not be sorted against each other.
        score = together if together else alike * 0.5
        if score <= 0:
            continue
        out.append({"tag": other, "score": round(score, 3),
                    "basis": "used_together" if together else "reads_alike",
                    "description": row.description or "",
                    "same_kind": (row.kind or "") == (me.kind or "")})
    return sorted(out, key=lambda d: -d["score"])[:limit]


#: Above this share of shared rows, two tags are doing one job.
SITUATION_OVERLAP = 0.6

#: ...but only once there are enough rows for the share to mean anything. Two
#: tags that co-occur on a single claim score 100% and are usually unrelated:
#: measured on the agency's seed, the co-occurrence signal alone paired
#: `food_bev` with `no_traffic` on one shared row. The same reasoning as the
#: note about holdouts on small lists — a ratio over a tiny denominator is a
#: coincidence with a percent sign on it.
MIN_ROWS_FOR_OVERLAP = 3


def situation_overlaps(tenant: str) -> list[dict]:
    """Pairs of situations that are probably one situation.

    Reported, never merged automatically — the same rule `near_duplicates`
    follows. Merging two tags rewrites how every claim under them can be
    selected, and a machine has no business doing that unasked.
    """
    rows = {r.tag: r for r in situation_rows(tenant)}
    used = _situation_users(tenant)
    seen, out = set(), []
    for tag in rows:
        for n in situation_neighbours(tenant, tag, limit=len(rows)):
            pair = tuple(sorted((tag, n["tag"])))
            if pair in seen:
                continue
            shared = len(used.get(tag, set()) | used.get(n["tag"], set()))
            hit = (
                (n["basis"] == "used_together"
                 and n["score"] >= SITUATION_OVERLAP
                 and shared >= MIN_ROWS_FOR_OVERLAP)
                or (n["basis"] == "reads_alike"
                    and n["score"] >= prov.NEAR_DUPLICATE)
            )
            if not hit:
                continue
            seen.add(pair)
            out.append({
                "keep": pair[0], "drop": pair[1], "score": n["score"],
                "basis": n["basis"],
                "rows": {p: len(used.get(p, set())) for p in pair},
                "why": (f"{n['score']:.0%} of the rows tagged one are tagged "
                        f"the other" if n["basis"] == "used_together"
                        else "their descriptions and triggers read alike"),
            })
    return sorted(out, key=lambda d: -d["score"])


def merge_situations(tenant: str, keep: str, drop: str,
                     dry_run: bool = True) -> dict:
    """Fold one situation into another, retagging everything that used it.

    The tag has to move BEFORE the row is deleted, or every claim tagged only
    with `drop` becomes untaggable — `add_claim` refuses tags outside the
    vocabulary, so a claim left holding a retired tag can never be re-approved
    and can never be selected. Silent retirement of real proof.
    """
    valid = situations(tenant, include_proposed=True)
    if keep not in valid:
        return {"error": f"{keep!r} is not a situation for {tenant}."}
    if drop not in valid or drop == keep:
        return {"error": f"{drop!r} is not a separate situation for {tenant}."}

    moved = {"claims": 0, "objections": 0}
    with db.SessionLocal() as s:
        for model, name in ((db.KbClaim, "claims"), (db.KbObjection, "objections")):
            for row in s.query(model).filter(model.tenant == tenant).all():
                tags = list(row.situations or [])
                if drop not in tags:
                    continue
                moved[name] += 1
                if dry_run:
                    continue
                tags = [keep if x == drop else x for x in tags]
                row.situations = sorted(set(tags))
        if not dry_run:
            row = (s.query(db.KbSituation)
                   .filter(db.KbSituation.tenant == tenant,
                           db.KbSituation.tag == drop).first())
            if row:
                s.delete(row)
            s.commit()
    return {"tenant": tenant, "keep": keep, "dropped": drop,
            "dry_run": dry_run, "retagged": moved,
            "note": ("Nothing changed — this is what it would do."
                     if dry_run else
                     f"{drop!r} folded into {keep!r}; every row that carried it "
                     f"now carries {keep!r}.")}


def add_situation(tenant: str, tag: str, patterns: list[list[str]] | None = None,
                  description: str = "", kind: str = "problem",
                  origin: str = "human", source: str = "",
                  review: str = "") -> str:
    """Add or update a situation tag.

    `review` follows the same rule as every other KB table: a human or a seed
    lands approved, a machine lands proposed. This used to be hardcoded to
    APPROVED, which was harmless while only the seed wrote here — and became a
    hole the moment the extractor started proposing tags it wished existed,
    because a machine would have been silently editing the one vocabulary that
    decides whether any claim can be accepted at all.
    """
    tag = (tag or "").strip().lower().replace(" ", "_")
    if not tag:
        return "A situation needs a tag."
    # A machine may not widen the vocabulary with a synonym of something that
    # is already in it. A human still can — they may have a reason, and they
    # can see both.
    if not prov.lands_approved(origin):
        near = similar_situation(tenant, tag)
        if near and near != tag:
            return (f"Not added — {tenant} already has {near!r}, which covers "
                    f"{tag!r}. Use that instead.")
    with db.SessionLocal() as s:
        existing = s.query(db.KbSituation).filter(
            db.KbSituation.tenant == tenant, db.KbSituation.tag == tag).first()
        landed = review or (prov.APPROVED if prov.lands_approved(origin)
                            else prov.PROPOSED)
        row = existing or db.KbSituation(
            tenant=tenant, tag=tag, origin=origin, source=source,
            review=landed, fingerprint=prov.fingerprint(tag),
            approved_by="seed" if origin == "seed" else "",
            approved_at=db.utcnow() if landed == prov.APPROVED else None)
        row.patterns = [list(p) for p in (patterns or [])]
        row.description = description or row.description
        row.kind = kind
        if not existing:
            s.add(row)
        s.commit()
    return f"{'Updated' if existing else 'Added'} situation {tag} for {tenant}."


def entities(tenant: str, type: str = "", available_only: bool = True,
             include_proposed: bool = False) -> list[db.KbEntity]:
    with db.SessionLocal() as s:
        q = s.query(db.KbEntity).filter(db.KbEntity.tenant == tenant,
                                        db.KbEntity.status == "active")
        if not include_proposed:
            q = q.filter(db.KbEntity.review == prov.APPROVED)
        if type:
            q = q.filter(db.KbEntity.type == type)
        rows = q.all()
        if available_only:
            rows = [r for r in rows if r.availability == "available"]
        s.expunge_all()
        return rows


# --------------------------------------------------------------------------
# Entity selection — reaching the thing actually being sold.
#
# Selection used to query claims and objections only. Entities were reachable
# solely through a hardcoded agency offer key, so an enquiry that named a
# headcount never touched the capacity data one table over. That is the defect
# this section closes: the buyer states a requirement, and code finds what
# satisfies it.
# --------------------------------------------------------------------------

def _num(value) -> float | None:
    """Coerce an attribute to a number. '4,000 sq ft' -> 4000.0, '' -> None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    import re as _re
    m = _re.search(r"[\d,]+(?:\.\d+)?", str(value))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def selection_config(tenant: str) -> dict:
    b = brand(tenant)
    return dict((b.selection or {}) if b else {})


def match_entities(tenant: str, requirements: dict | None = None,
                   limit: int = 3) -> list[dict]:
    """Rank what this tenant sells against what the buyer actually asked for.

    Returns dicts rather than rows because the *reason* a thing matched is part
    of the answer — a draft that names a venue must be able to say it seats the
    headcount, and a generator can only say that if selection hands it over.

    Entities that do NOT satisfy a stated requirement are returned too, marked
    `fits: False`. "Nothing you have fits 600 seated" is a real answer, and
    silently returning the closest thing would invent a fit that isn't there.
    """
    requirements = requirements or {}
    cfg = selection_config(tenant)
    etype = cfg.get("primary_type", "")
    rows = entities(tenant, etype) if etype else entities(tenant)
    if not rows:
        return []

    modes = cfg.get("modes") or [{"mode": "keyword"}]

    def _base(r: db.KbEntity) -> dict:
        return {"key": r.key, "name": r.name, "type": r.type, "price": r.price,
                "description": r.description, "attributes": r.attributes or {}}

    # --- what a word is worth -------------------------------------------
    # Keyword hits search the entity's WORDS — name, description and attribute
    # VALUES — never attribute names. A room that merely has a
    # `seated_capacity` field would otherwise "match" the word seated.
    def _blob(r: db.KbEntity) -> str:
        return " ".join([r.name or "", r.description or "",
                         *[str(v) for v in (r.attributes or {}).values()]]).lower()

    # Attributes explicitly ruled out for an entity. An open-air garden has no
    # seated capacity and never will; once that is said, it stops being
    # reported as a gap AND stops appearing as an unknown in every result.
    with db.SessionLocal() as _s:
        ruled_out = {
            (u.entity_key, u.attribute) for u in _s.query(db.KbUnknown).filter(
                db.KbUnknown.tenant == tenant,
                db.KbUnknown.status == "not_applicable").all()}

    raw_words = [w.lower() for w in (requirements.get("keywords") or [])
                 if len(w) > 2]
    blobs = {r.key: _blob(r) for r in rows}

    # A word that appears in almost everything carries no information — "white"
    # in a tile catalogue, "gift" in a gift brand, "space" in a venue list.
    # Document frequency decides this per catalogue, so it works for any client
    # and any vocabulary without a hand-maintained stoplist anywhere.
    words = raw_words
    if len(rows) >= 4:
        words = [w for w in raw_words
                 if sum(1 for b in blobs.values() if w in b) <= 0.6 * len(rows)]

    def _hits(r: db.KbEntity) -> list[str]:
        return [w for w in words if w in blobs[r.key]]

    # --- a stated requirement is authoritative ---------------------------
    # `fits` is deliberately tri-state:
    #   True  — a stated requirement was checked and satisfied
    #   False — checked and NOT satisfied
    #   None  — could not be checked, because the entity has no such data
    # Anything that collapses None into either of the others is inventing: an
    # entity with no seated capacity recorded is not "unsuitable", and a
    # keyword match is relevance, never satisfaction.
    for mode in [m for m in modes if m.get("mode") == "capacity_fit"]:
        need = _num(requirements.get(mode.get("requirement", "headcount")))
        if need is None:
            continue
        attrs = mode.get("attributes", {})
        # Which attribute the requirement is measured against can itself depend
        # on a stated fact — seated and standing are different rooms.
        attr = attrs.get("default", "")
        for flag, alt in attrs.items():
            if flag != "default" and requirements.get(flag):
                attr = alt
                break
        label = attr.replace("_", " ")

        scored = []
        for r in rows:
            if (r.key, attr) in ruled_out:
                continue  # said to be inapplicable — not an option, not a gap
            have = _num((r.attributes or {}).get(attr))
            if have is None:
                # Surfaced, not dropped. Silently removing it would imply the
                # option was ruled out, when in fact it was never measured.
                scored.append({
                    **_base(r), "fits": None, "basis": "unknown",
                    "attribute": attr,  # so the gap can be recorded and answered
                    "why": f"no {label} recorded — cannot be judged against {int(need)}",
                    "_rank": (1, 0, -len(_hits(r))),
                })
                continue
            fits = have >= need
            scored.append({
                **_base(r), "fits": fits, "basis": "requirement",
                "why": (f"{label} {int(have)} "
                        f"{'covers' if fits else 'is short of'} {int(need)}"),
                # Satisfied first, then unknown, then known-short. Within the
                # satisfied group, the smallest that still works (least waste);
                # keyword relevance only ever breaks a tie.
                "_rank": (0 if fits else 2, abs(have - need), -len(_hits(r))),
            })
        if scored:
            out = [dict(d) for d in sorted(scored, key=lambda d: d["_rank"])]
            for d in out:
                d.pop("_rank", None)
            return out[:limit] if limit else out

    # --- no requirement to check: relevance only -------------------------
    scored = []
    for r in rows:
        hits = _hits(r)
        if words and not hits:
            continue
        scored.append({
            **_base(r),
            # Never True. Nothing was verified, so nothing may be asserted.
            "fits": None,
            "basis": "keyword" if hits else "unranked",
            "why": (f"mentions {', '.join(hits)}" if hits
                    else "no stated requirement to match on"),
            "_rank": (-len(hits), r.name or ""),
        })
    out = [dict(d) for d in sorted(scored, key=lambda d: d["_rank"])]
    for d in out:
        d.pop("_rank", None)
    return out[:limit] if limit else out


# --------------------------------------------------------------------------
# Unknowns — the attribute-level backlog.
#
# `match_entities` stays pure: it reports what it could not judge and the
# caller decides whether this occurrence is worth remembering. Writing on a
# read would make every speculative match mutate the backlog.
# --------------------------------------------------------------------------

def record_unknowns(tenant: str, matches: list[dict], asked_for: str = "") -> int:
    """Count the gaps a real enquiry just ran into. Returns rows touched."""
    n = 0
    with db.SessionLocal() as s:
        for m in matches:
            if m.get("basis") != "unknown":
                continue
            attr = m.get("attribute") or ""
            if not attr:
                continue
            row = s.query(db.KbUnknown).filter(
                db.KbUnknown.tenant == tenant,
                db.KbUnknown.entity_key == m.get("key", ""),
                db.KbUnknown.attribute == attr,
                db.KbUnknown.status == "open").first()
            if row:
                row.hits = str(int(row.hits or "0") + 1)
                row.last_seen = db.utcnow()
                if asked_for:
                    row.asked_for = asked_for
            else:
                s.add(db.KbUnknown(tenant=tenant, entity_key=m.get("key", ""),
                                   entity_name=m.get("name", ""), attribute=attr,
                                   asked_for=asked_for))
            n += 1
        s.commit()
    return n


def unknowns(tenant: str = "", status: str = "open") -> list[db.KbUnknown]:
    """Open gaps, most costly first — ranked by how often each blocked an answer."""
    with db.SessionLocal() as s:
        q = s.query(db.KbUnknown).filter(db.KbUnknown.status == status)
        if tenant:
            q = q.filter(db.KbUnknown.tenant == tenant)
        rows = q.all()
        s.expunge_all()
    return sorted(rows, key=lambda r: -int(r.hits or "0"))


def resolve_unknown(unknown_id: str, value: str) -> str:
    """Answer a gap: write the value onto the entity and close the row.

    `not applicable` is a real answer and is recorded as one — an outdoor
    garden may genuinely have no seated capacity, and re-asking forever is
    what makes a system feel broken.
    """
    value = (value or "").strip()
    if not value:
        return "Needs a value, or say 'n/a'."
    with db.SessionLocal() as s:
        row = s.get(db.KbUnknown, unknown_id)
        if not row:
            return "No such gap."
        if value.lower() in ("n/a", "na", "none", "not applicable"):
            row.status, row.answer = "not_applicable", value
            s.commit()
            return (f"Marked not applicable — {row.entity_name} will stop being "
                    f"offered against {row.attribute.replace('_', ' ')}.")
        ent = s.query(db.KbEntity).filter(
            db.KbEntity.tenant == row.tenant,
            db.KbEntity.key == row.entity_key).first()
        if not ent:
            return f"{row.entity_key} is no longer in the catalogue."
        attrs = dict(ent.attributes or {})
        num = _num(value)
        attrs[row.attribute] = int(num) if num is not None and num == int(num) else value
        ent.attributes = attrs
        ent.verified_at = db.utcnow()
        row.status, row.answer = "answered", value
        s.commit()
        name, attr = ent.name, row.attribute.replace("_", " ")
    return f"{name}: {attr} = {value}. It can now be matched against that."


def next_step_for(tenant: str, stage: str) -> dict:
    """What this tenant proposes at this stage. Data, not hardcoded offer keys."""
    b = brand(tenant)
    steps = (b.next_steps or {}) if b else {}
    return dict(steps.get(stage) or steps.get("default") or {})


# --------------------------------------------------------------------------
# Completeness — the KB audit, as code. The assembler calls this before
# building a brief so the pipeline blocks with a named field instead of
# inventing something (this is what stopped the Ironside quote).
# --------------------------------------------------------------------------

#: One place that knows how to test a single named KB requirement. `completeness`
#: answers "may we generate from this account at all"; this answers "may THIS
#: system run", which is a different and usually much smaller question.
def needs_met(tenant: str, fields: tuple[str, ...]) -> list[str]:
    """Which of the named KB requirements this account does not meet.

    `systems.ready` used to ignore the per-system `kb_needs` entirely and gate
    everything on `completeness()` — one global bar of six things. That was
    wrong in both directions at once, and neither error was visible because the
    declared list was never read:

      · Website content compliance declares it needs `banned_claims` and
        nothing else. It was blocked until the account had a tone, a claim, an
        audience, an objection AND a product — five things it never touches.
        The cheapest system to switch on was gated like the most expensive one.
      · `next_steps` is in the lead responder's declared needs and
        `completeness()` does not check it at all, so a lead responder could
        pass its gate and produce a draft with a blank ask — the §2.8 failure,
        still reachable.

    A refusal that names something the system does not use is a false refusal,
    and this codebase's whole claim is that it refuses accurately.
    """
    b = brand(tenant)
    if not b:
        return ["kb_brand row"]
    have = {
        "tone": bool((b.voice or {}).get("tone")),
        "banned_claims": bool(b.banned_claims),
        "next_steps": bool(b.next_steps),
        "positioning": bool(b.positioning),
        "claim": bool(claims(tenant)),
        "audience": bool(audiences(tenant)),
        "objection": bool(objections(tenant)),
        "entity": bool(entities(tenant, available_only=False)),
    }
    waiting = {
        "claim": len(pending_claims(tenant)),
        "audience": len([a for a in audiences(tenant, include_proposed=True)
                         if (a.review or "") == prov.PROPOSED]),
        "objection": len([o for o in objections(tenant, include_proposed=True,
                                                any_entity=True)
                          if (o.review or "") == prov.PROPOSED]),
        "entity": len([e for e in entities(tenant, available_only=False,
                                           include_proposed=True)
                       if (e.review or "") == prov.PROPOSED]),
    }
    missing = []
    for f in fields:
        if have.get(f, True):
            continue
        # Same distinction completeness() draws: nobody has told us yet, versus
        # somebody has and it is sitting in a queue. Different fixes.
        n = waiting.get(f, 0)
        missing.append(f"{f} ({n} waiting for review)" if n else f)
    return missing


def completeness(tenant: str) -> dict:
    """Whether this account can be generated from, and what is missing if not.

    Counts APPROVED rows only — a proposal is not something a generator may
    use. But "none" and "three waiting for you to approve them" are different
    problems with different fixes, and reporting both as `kb_objections (none)`
    sends someone off to author what a client already wrote. So a pending count
    rides alongside, and the blocker names the action rather than the absence.
    """
    b = brand(tenant)
    missing: list[str] = []
    if not b:
        return {"tenant": tenant, "ready": False, "missing": ["kb_brand row"],
                "counts": {}, "awaiting_review": {}}
    if not (b.voice or {}).get("tone"):
        missing.append("brand.voice.tone")
    if not b.banned_claims:
        missing.append("brand.banned_claims")
    counts = {
        "claims": len(claims(tenant)),
        "audiences": len(audiences(tenant)),
        "objections": len(objections(tenant)),
        "entities": len(entities(tenant, available_only=False)),
    }
    waiting = {
        "claims": len(pending_claims(tenant)),
        "audiences": len([a for a in audiences(tenant, include_proposed=True)
                          if (a.review or "") == prov.PROPOSED]),
        "objections": len([o for o in objections(tenant, include_proposed=True)
                           if (o.review or "") == prov.PROPOSED]),
        "entities": len([e for e in entities(tenant, available_only=False,
                                             include_proposed=True)
                         if (e.review or "") == prov.PROPOSED]),
    }
    for name in ("claims", "audiences", "objections", "entities"):
        if counts[name] == 0:
            missing.append(
                f"kb_{name} ({waiting[name]} waiting for review)" if waiting[name]
                else f"kb_{name} (none)")
    return {"tenant": tenant, "ready": not missing, "missing": missing,
            "counts": counts, "awaiting_review": waiting}


# --------------------------------------------------------------------------
# Write side.
#
# Kept here rather than in a separate module so there is exactly one place that
# knows the shape of a KB row. Every writer normalises and validates before it
# commits — a claim with an unknown situation tag can never be selected, and an
# audience with no vocabulary is a row that makes the output worse, so both are
# refused at the door rather than stored and puzzled over later.
# --------------------------------------------------------------------------

def _split(text: str, sep: str = ";") -> list[str]:
    return [p.strip() for p in (text or "").split(sep) if p.strip()]


def ensure_brand(tenant: str, display_name: str = "") -> db.KbBrand:
    """Get the brand row, creating a bare one if this tenant has none yet.

    Without this every write to a fresh tenant would fail on a missing parent
    row, which is how a knowledge base ends up with claims and no voice.
    """
    with db.SessionLocal() as s:
        row = s.get(db.KbBrand, tenant)
        if not row:
            row = db.KbBrand(tenant=tenant,
                             display_name=display_name or tenant.title())
            s.add(row)
            s.commit()
        s.refresh(row)
        s.expunge(row)
        return row


def set_brand(tenant: str, **fields) -> str:
    """Update brand-level fields. `tone` is a convenience into voice.tone."""
    allowed = {"display_name", "positioning", "elevator", "voice",
               "banned_claims", "approval_policy", "selection", "next_steps"}
    tone = fields.pop("tone", None)
    bad = set(fields) - allowed
    if bad:
        return f"Unknown field(s): {sorted(bad)}"
    ensure_brand(tenant)
    with db.SessionLocal() as s:
        row = s.get(db.KbBrand, tenant)
        for k, v in fields.items():
            setattr(row, k, v)
        if tone is not None:
            voice = dict(row.voice or {})
            voice["tone"] = _split(tone, ",") or _split(tone, " ")
            row.voice = voice
        s.commit()
    return f"Updated {tenant} brand."


def add_banned(tenant: str, phrase: str) -> str:
    """Add a phrase the validator will reject. Creates the brand row if needed."""
    phrase = (phrase or "").strip()
    if not phrase:
        return "A rule needs a phrase."
    ensure_brand(tenant)
    with db.SessionLocal() as s:
        row = s.get(db.KbBrand, tenant)
        current = list(row.banned_claims or [])
        if phrase.lower() in [c.lower() for c in current]:
            return f"Already banned for {tenant}."
        row.banned_claims = current + [phrase]
        s.commit()
        n = len(row.banned_claims)
    return f"Banned for {tenant} ({n} rules): “{phrase}”"


def add_claim(tenant: str, claim: str, evidence: str, tags: list[str],
              proof_type: str = "case_study", source: str = "",
              strength: str = "strong", status: str = "active",
              origin: str = "human", entity_key: str = "",
              proves: str = "", context: str = "") -> str:
    """Add a claim, or record that another source corroborates one on file.

    `status="pending"` is kept as the way callers ask for a proposal, and is
    translated to `review=proposed` — approval and lifecycle are two axes now,
    and this is the one place that still has to know they used to be one.
    """
    review = prov.PROPOSED if status == "pending" else prov.APPROVED
    status = "active" if status == "pending" else status
    valid = situations(tenant)
    unknown = [t for t in tags if t not in valid]
    if unknown:
        return (f"Unknown tags for {tenant}: {', '.join(unknown)}\n"
                f"Valid: {', '.join(sorted(valid))}")
    # A claim being REVIEWED may arrive untagged; a claim being USED may not.
    # The requirement moved from write time to approve time so a derived
    # candidate can be proposed and segmented by a human at the moment they
    # look at it, rather than discarded for want of a tag a crawler could not
    # infer. `claims()` only returns active rows, so an untagged pending claim
    # is invisible to selection either way — and `review_claim` refuses to
    # activate one.
    if not tags and review == prov.APPROVED:
        return "Needs at least one situation tag, or it can never be selected."

    # The entity is part of the identity: the same sentence about two products
    # is two facts, and collapsing them would attach one product's copy to
    # another.
    fp = prov.fingerprint(claim, entity_key)
    with db.SessionLocal() as s:
        # The same fact arriving from a second source is corroboration, not a
        # second claim. Before this, a re-run of the seed or the harvester
        # duplicated every row it had already written.
        dupe = s.query(db.KbClaim).filter(
            db.KbClaim.tenant == tenant, db.KbClaim.fingerprint == fp).first()
        if dupe:
            seen = list(dupe.also_seen or [])
            if not any(e.get("ref") == (source or "") and
                       e.get("origin") == origin for e in seen):
                seen.append({"origin": origin, "ref": source or "",
                             "seen": db.utcnow().isoformat()})
                dupe.also_seen = seen
                s.commit()
            state = ("already approved" if (dupe.review or "") == prov.APPROVED
                     else "already waiting for review")
            return (f"Already on file for {tenant} — {state}. Recorded that "
                    f"{origin} says it too.\n{dupe.claim}")

        s.add(db.KbClaim(tenant=tenant, claim=claim, evidence=evidence,
                         proof_type=proof_type, source=source or "captured",
                         situations=tags, strength=strength, status=status,
                         review=review, origin=origin, fingerprint=fp,
                         entity_key=entity_key, proves=proves, context=context,
                         approved_by="seed" if origin == "seed" else "",
                         approved_at=db.utcnow() if review == prov.APPROVED else None,
                         also_seen=[{"origin": origin, "ref": source or "",
                                     "seen": db.utcnow().isoformat()}],
                         verified_at=db.utcnow()))
        s.commit()
    if review != prov.APPROVED:
        # claims() filters on approved, so a proposal is invisible to selection
        # until a human has looked at it. That is the point.
        return (f"Submitted for review — it will not be used until approved.\n"
                f"{claim}")

    # A row that lands approved never passes through `review_claim`, so the
    # index hook there never fires for it — and seeding and console adds are
    # exactly that path. Without this, every claim written by `seed_kb` was
    # invisible to semantic recall until somebody remembered to run a backfill,
    # and nothing would have looked wrong. Index where the row becomes
    # selectable, which is here as well as there.
    try:
        from . import embed
        with db.SessionLocal() as s:
            row = (s.query(db.KbClaim)
                   .filter(db.KbClaim.tenant == tenant,
                           db.KbClaim.fingerprint == fp).first())
        if row:
            embed.ensure(tenant, "claim", row.id,
                         f"{claim} {evidence or ''}".strip())
    except Exception as exc:  # noqa: BLE001 — indexing must not fail a write
        log.warning("embed on add failed for %s: %s", tenant, exc)

    return (f"Added to {tenant} ({len(claims(tenant))} claims).\n"
            f"{claim}\n{evidence}\ntags: {', '.join(tags)}")


def pending_claims(tenant: str = "") -> list[db.KbClaim]:
    """Claims awaiting review — proposals from any source, not yet selectable."""
    with db.SessionLocal() as s:
        q = s.query(db.KbClaim).filter(db.KbClaim.review == prov.PROPOSED)
        if tenant:
            q = q.filter(db.KbClaim.tenant == tenant)
        rows = q.order_by(db.KbClaim.verified_at.desc()).all()
        s.expunge_all()
        return rows


def review_claim(claim_id: str, approve: bool, by: str = "owner") -> str:
    """Approve or reject a claim, and record who did it.

    Approval is the moment a row becomes final: from here no crawl, upload or
    store sync may change its wording — they raise a `KbConflict` instead. That
    guarantee is only as good as the record of who made it, which is why
    `approved_by` and `approved_at` are written here and nowhere else.
    """
    with db.SessionLocal() as s:
        row = s.get(db.KbClaim, claim_id)
        if not row:
            return "No such claim."
        if approve and not (row.situations or []):
            # This is where the tag requirement is actually enforced. Letting an
            # untagged claim go active would make it permanently unselectable
            # while looking approved — worse than refusing.
            return ("Give it at least one situation tag before approving — "
                    "an untagged claim can never be selected.")
        if approve:
            row.review, row.status = prov.APPROVED, "active"
            row.approved_by, row.approved_at = by, db.utcnow()
        else:
            row.review, row.status = prov.REJECTED, "retired"
        s.commit()
        text = row.claim
        tenant, ev = row.tenant, (row.evidence or "")

    # Index at the moment it becomes selectable. The alternative is an index
    # that drifts from the truth it indexes — which is the exact failure that
    # argued against putting retrieval in a separate datastore, and it would be
    # no better for having been built here. Best effort: a provider outage must
    # never turn an approval into a failure, and `/admin/embed_backfill` picks
    # up whatever this missed.
    try:
        from . import embed
        if approve:
            embed.ensure(tenant, "claim", claim_id, f"{text} {ev}".strip())
        else:
            # Rejected means retired means unusable. Leaving the vector behind
            # is the index-drift this design exists to avoid.
            embed.forget(tenant, "claim", claim_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("embed sync on review failed for %s: %s", claim_id, exc)

    return (f"Approved — now selectable, and final.\n{text}" if approve
            else f"Rejected.\n{text}")


def update_claim(claim_id: str, claim: str = None, evidence: str = None,
                 tags: list[str] | None = None, proof_type: str = None,
                 source: str = None, strength: str = None,
                 entity_key: str | None = None, proves: str | None = None,
                 context: str | None = None) -> str:
    """Edit a claim in place. The editing half of propose-then-approve.

    Tags are validated against the tenant's vocabulary exactly as `add_claim`
    does — a human correcting a proposal must not be able to invent a tag that
    selection will never match either.
    """
    with db.SessionLocal() as s:
        row = s.get(db.KbClaim, claim_id)
        if not row:
            return "No such claim."
        if entity_key is not None:
            ek = (entity_key or "").strip().lower()
            # Validated exactly as tags are. A claim scoped to an entity that
            # does not exist is unreachable: selection only ever asks for the
            # scope of something it is already writing about, so a typo here
            # silently retires the claim rather than failing loudly.
            if ek and not [e for e in entities(row.tenant, available_only=False,
                                               include_proposed=True)
                           if e.key == ek]:
                return (f"{row.tenant} has nothing in its catalogue keyed "
                        f"{ek!r}. Leave it blank for a brand-level claim.")
            row.entity_key = ek
        if tags is not None:
            valid = situations(row.tenant)
            unknown = [t for t in tags if t not in valid]
            if unknown:
                return (f"Unknown tags for {row.tenant}: {', '.join(unknown)}\n"
                        f"Valid: {', '.join(sorted(valid))}")
            row.situations = tags
        # A testimonial's wording is its evidence. Editing it turns a record of
        # what a customer said into something the brand asserts, which is the
        # one edit that changes a true row into a false one.
        if (claim is not None and str(claim).strip()
                and (row.proof_type or "") in VERBATIM_ONLY
                and str(claim).strip() != (row.claim or "").strip()):
            return ("This is a customer's own words — quote it, do not rewrite "
                    "it. Correct the tags or the attribution instead, or reject "
                    "it if it should not be used at all.")
        if context is not None:
            row.context = str(context).strip()[:600]
        if proves is not None:
            # Editable to empty, unlike the fields below: a model-written
            # reading a reviewer disagrees with should be removable, not only
            # replaceable.
            row.proves = str(proves).strip()[:400]
        for field, value in (("claim", claim), ("evidence", evidence),
                             ("proof_type", proof_type), ("source", source),
                             ("strength", strength)):
            if value is not None and str(value).strip():
                setattr(row, field, str(value).strip())
        # A human has touched the wording, so the row is theirs from now on and
        # the fingerprint has to follow the text — otherwise a re-crawl of the
        # ORIGINAL sentence would not recognise the row it belongs to and would
        # file the uncorrected version all over again.
        row.origin = "human"
        # entity_key is PART of the fingerprint in add_claim, and leaving it
        # out here made the two disagree: after any edit a row carried
        # fingerprint(claim) while a fresh add of the same claim on the same
        # product computed fingerprint(claim, entity_key). They never matched,
        # so dedup missed and the row was filed twice. Baci has exactly that —
        # "This is sold as a set of 5 pieces." on set-5-dishes-appetizer-joke,
        # twice, with different tags. `update_objection` had this right; the
        # claim path is the one that got missed.
        row.fingerprint = prov.fingerprint(row.claim, row.entity_key or "")
        s.commit()
    return "Saved."


def retire_claim(claim_id: str) -> str:
    """Take a claim out of selection without deleting the record of it."""
    return review_claim(claim_id, approve=False)


# --------------------------------------------------------------------------
# The review queue, for every table rather than just claims.
#
# Claims were the only table with an approval state, so a proposal was only
# possible for the one kind of row a crawler happened to produce. A spreadsheet
# upload proposes entities, a client intake link proposes audiences and
# objections, and all of them went live on write. These two functions are the
# uniform surface: one place to see what is waiting, one place to make it final.
# --------------------------------------------------------------------------

REVIEWABLE = {
    "claim": (db.KbClaim, "claim"),
    "audience": (db.KbAudience, "name"),
    "objection": (db.KbObjection, "objection"),
    "entity": (db.KbEntity, "name"),
    "situation": (db.KbSituation, "tag"),
}


def proposals(tenant: str = "", kind: str = "") -> dict[str, list]:
    """Everything waiting for a human, by kind, newest table first.

    Each row is returned with the near-duplicates already on file, because the
    reviewer's real question is rarely "is this true" — it is "haven't I seen
    this already", and answering that by memory is how a queue stops being read.
    """
    out: dict[str, list] = {}
    for name, (model, field) in REVIEWABLE.items():
        if kind and name != kind:
            continue
        with db.SessionLocal() as s:
            q = s.query(model).filter(model.review == prov.PROPOSED)
            if tenant:
                q = q.filter(model.tenant == tenant)
            rows = q.all()
            approved = []
            if rows:
                aq = s.query(model).filter(model.review == prov.APPROVED)
                if tenant:
                    aq = aq.filter(model.tenant == tenant)
                approved = aq.all()
            s.expunge_all()
        if not rows:
            continue

        # Two products can carry facts that read alike and are not
        # interchangeable — "dishwasher safe" is true of the porcelain and false
        # of the pouf; "Ø 25 cm" is true of exactly one thing. So similarity is
        # only a DUPLICATE within the scope where both rows could actually be
        # selected together. Outside it, the same wording is a parallel fact and
        # merging or rejecting one would delete a real product's answer.
        def _scoped(row):
            ek = getattr(row, "entity_key", "") or ""
            if not hasattr(row, "entity_key"):
                return approved, []
            # Would collide: brand-level rows, plus rows on the same entity.
            same = [a for a in approved
                    if (getattr(a, "entity_key", "") or "") in ("", ek)]
            # Same words, different thing. Informational, never a duplicate.
            other = [a for a in approved
                     if (getattr(a, "entity_key", "") or "") not in ("", ek)]
            return same, other

        entries = []
        for r in rows:
            same, other = _scoped(r)
            text = getattr(r, field, "") or ""
            dupes = prov.near_duplicates(text, same, field)
            # A brand-level row saying the same thing DOES cover an
            # entity-scoped proposal — that is real redundancy, and the
            # narrower row adds nothing.
            covered = [d for d in dupes
                       if not (getattr(d, "entity_key", "") or "")
                       and (getattr(r, "entity_key", "") or "")]
            entries.append({
                "row": r,
                "near_duplicates": dupes,
                "covered_by_brand_level": covered,
                "parallel_on_other_entities":
                    prov.near_duplicates(text, other, field),
            })
        out[name] = entries
    return out


#: What a rescrape puts back. Everything else it depends on.
HARVESTED_ORIGINS = ("crawl", "email")


def purge_harvested(tenant: str, origins: tuple[str, ...] = HARVESTED_ORIGINS,
                    include_entities: bool = False,
                    dry_run: bool = True) -> dict:
    """Clear machine-read claims and objections so a rescrape can refill them.

    `purge_proposals` deletes only un-reviewed rows, which is the wrong tool
    here: the objections filed brand-wide by the old harvester were APPROVED —
    through a review form that offered no way to scope them — so they are
    exactly the rows it will not touch.

    **What this deliberately does NOT delete**, because a rescrape cannot put
    any of it back and two of them make the rescrape worse:

      · `KbEntity` — the catalogue. `harvest` scopes a product page by looking
        its handle up in this set, so with the entities gone EVERY re-harvested
        objection comes back unscoped and the defect this purge is meant to
        clear recurs in full. Delete these and the rescrape is guaranteed to
        reproduce the bug.
      · `KbBrand.banned_claims` — the one input a crawler can never derive. A
        site records what a brand does say; the ban list is what it must not.
        It is also the filter that drops "handmade in Italy" before it reaches
        the queue, so without it the rescrape reintroduces what the rules exist
        to keep out.
      · `KbSituation` — the tag vocabulary. `add_claim` refuses tags outside
        it, so an empty vocabulary means nothing harvested can be filed.
      · anything of human or seed origin, and the store sync's own rows.

    Rows are DELETED, not rejected, for the reason `purge_proposals` gives:
    `suggest_tags` learns what a bad claim looks like from retired rows, and
    filing a hundred correct-but-mis-scoped answers as rejected would teach the
    tagger the wrong lesson.

    Dry run by default, like every other bulk write here.
    """
    if not tenant:
        return {"error": "name the account, or '*' for every account — an "
                         "empty target is how the wrong one gets emptied"}
    human = [o for o in origins if o in prov.HUMAN_ORIGINS]
    if human:
        return {"error": f"{', '.join(human)} is a human origin. This clears "
                         f"what a machine read, never what a person authored."}

    kinds = ["claim", "objection"]
    ent_origins = tuple(origins)
    if include_entities:
        # The synced catalogue is store_sync origin, not crawl — without this
        # "include entities" would match almost nothing and quietly do nothing.
        kinds.append("entity")
        ent_origins = tuple(set(origins) | {"store_sync"})

    hit: dict[str, dict] = {}
    with db.SessionLocal() as s:
        for name in kinds:
            model, field = REVIEWABLE[name]
            want = ent_origins if name == "entity" else origins
            q = s.query(model).filter(model.origin.in_(list(want)))
            if tenant != "*":
                q = q.filter(model.tenant == tenant)
            rows = q.all()
            if not rows:
                continue
            hit[name] = {
                "total": len(rows),
                "approved": sum(1 for r in rows
                                if (r.review or "") == prov.APPROVED),
                "accounts": sorted({r.tenant for r in rows}),
                "examples": [str(getattr(r, field, ""))[:70] for r in rows[:3]],
            }
            if not dry_run:
                for r in rows:
                    s.delete(r)
        if not dry_run:
            s.commit()

    targets = ([t.key for t in tenants_mod().all_tenants(include_paused=True)]
               if tenant == "*" else [tenant])
    kept = {
        "entities_kept": {k: len(entities(k, available_only=False,
                                          include_proposed=True))
                          for k in targets},
        "banned_claims": {k: len(banned_claims(k)) for k in targets},
        "situations": {k: len(situations(k)) for k in targets},
    }
    notes = [
        "The ban list and the tag vocabulary are untouched. A crawler can "
        "never derive banned_claims — a site records what a brand does say — "
        "and it is the filter that drops 'handmade in Italy' before it reaches "
        "the queue. An empty tag vocabulary would refuse every harvested claim.",
        "Human- and seed-origin entities are kept: Ironside's eight venues "
        "were authored, not synced, and no catalogue sync would put them back. "
        "`/admin/seed_kb` restores them if you do clear them.",
    ]
    if include_entities:
        notes.insert(0, (
            "THE SYNCED CATALOGUE IS GONE. `harvest` scopes a product page by "
            "looking its handle up in the entity set, so until it is rebuilt "
            "EVERY harvested answer comes back unscoped — which is the defect "
            "this purge was run to clear. Re-run the catalogue sync BEFORE the "
            "harvest, not after."))
    order = ([f"/admin/catalog_sync?tenant=<account>  (rebuild the catalogue "
              f"FIRST — nothing scopes without it)"] if include_entities else [])
    return {
        "tenant": tenant, "accounts": targets, "origins": list(origins),
        "included_entities": include_entities, "dry_run": dry_run,
        "deleted" if not dry_run else "would_delete": hit,
        "kept": kept, "kept_note": notes,
        "next": order + [
            "/admin/fill?tenant=<account>&apply=1  (re-harvest)",
            "/admin/ui?tab=content&tenant=<account>  (review — objections now "
            "refuse to approve until you say what each one is true of)",
        ],
    }


def tenants_mod():
    from . import tenants as _t
    return _t


def purge_proposals(tenant: str = "", origin: str = "",
                    dry_run: bool = True) -> dict:
    """Delete un-reviewed proposals. Nothing approved is ever touched.

    Proposals produced by an earlier version of the crawler are not wrong so
    much as meaningless — they were selected by a filter that has since been
    fixed, and re-reading them costs more than re-running the harvest.

    **Deleted, not rejected**, and that is the deliberate part. `suggest_tags`
    treats retired claims as the negative signal for future tagging, so
    rejecting a hundred pieces of parser noise would teach the tagger that
    noise is what a rejected claim looks like and quietly degrade every
    suggestion after it. A row that was never really a proposal should leave no
    trace.

    Defaults to a dry run, like every other bulk write here.
    """
    hit: dict[str, int] = {}
    with db.SessionLocal() as s:
        for name, (model, _field) in REVIEWABLE.items():
            q = s.query(model).filter(model.review == prov.PROPOSED)
            if tenant:
                q = q.filter(model.tenant == tenant)
            if origin:
                q = q.filter(model.origin == origin)
            rows = q.all()
            if not rows:
                continue
            hit[name] = len(rows)
            if not dry_run:
                for r in rows:
                    s.delete(r)
        if not dry_run:
            s.commit()
    return {"tenant": tenant or "all", "origin": origin or "any",
            "dry_run": dry_run, "deleted": hit,
            "total": sum(hit.values()),
            "note": ("Approved rows are never touched. Proposals are deleted "
                     "rather than rejected, because a rejected row is training "
                     "data for the tagger and parser noise is not a lesson. "
                     "Pass dry_run=0 to actually delete.")}


def scope_unconfirmed(row) -> bool:
    """True when nobody has yet said what this row is true OF.

    `entity_key = ""` carries two completely different meanings and the code
    could not tell them apart: a human deciding "this is true of the whole
    brand", and a crawler failing to work out which product a page was about.
    Collapsing the second into the first is how "Is it dishwasher safe? Yes,
    top rack" — scraped off one product page — became a fact about a catalogue
    that includes gold-rim porcelain, which is not dishwasher safe at all.

    No new column: `origin` already separates them. A machine-origin row with
    no entity and no human approval never had its scope decided. Approving it
    IS the decision, which is why the guard is on the approval path and why
    approving with the box ticked is allowed.
    """
    if getattr(row, "entity_key", None):
        return False                      # scoped to something: decided
    if prov.lands_approved(getattr(row, "origin", "") or ""):
        return False                      # a human said it: decided
    return (getattr(row, "review", "") or "") != prov.APPROVED


def update_objection(row_id: str, objection: str = None, response: str = None,
                     entity_key: str | None = None, audience_key: str = None,
                     escalate: str = None,
                     situations: list[str] | None = None) -> str:
    """Edit an objection in place — the editing half of propose-then-approve.

    Claims have had this since the review queue existed; objections never did,
    so the review form offered Approve and Reject and nothing else. A reviewer
    who could SEE that "sold as a set of 6" was true of one product and not the
    catalogue had no way to say so — the only moves were to approve it wrong or
    throw away a real answer. That is why the wrong ones are approved.

    `entity_key` is validated against the catalogue exactly as `update_claim`
    does it: an objection scoped to something that does not exist is
    unreachable, because selection only ever asks for the scope of what it is
    already writing about.
    """
    with db.SessionLocal() as s:
        row = s.get(db.KbObjection, row_id)
        if not row:
            return "No such objection."
        if entity_key is not None:
            ek = (entity_key or "").strip().lower()
            if ek and not [e for e in entities(row.tenant, available_only=False,
                                               include_proposed=True)
                           if e.key == ek]:
                return (f"{row.tenant} has nothing in its catalogue keyed "
                        f"{ek!r}. Leave it blank only if the answer really is "
                        f"true of everything they sell.")
            row.entity_key = ek
            row.fingerprint = prov.fingerprint(row.objection or "", ek)
        if situations is not None:
            valid = globals()["situations"](row.tenant)
            unknown = [t for t in situations if t not in valid]
            if unknown:
                return (f"Unknown tags for {row.tenant}: {', '.join(unknown)}\n"
                        f"Valid: {', '.join(sorted(valid))}")
            row.situations = list(situations)
        for field, value in (("objection", objection), ("response", response),
                             ("audience_key", audience_key),
                             ("escalate", escalate)):
            if value is not None and str(value).strip():
                setattr(row, field, str(value).strip())
        s.commit()
    return "Saved."


def approve(kind: str, row_id: str, by: str = "owner",
            approve_it: bool = True, brand_wide: bool = False) -> str:
    """Make a proposed row final — or reject it — for any KB table.

    Claims keep their own entry point because approving one has an extra
    precondition (it must carry a situation tag or it can never be selected).

    Objections have gained a second one, for the same reason and with worse
    consequences: an answer with no scope is claimed of everything the account
    sells. `brand_wide=True` is the reviewer saying so on purpose.
    """
    if kind == "claim":
        return review_claim(row_id, approve_it, by=by)
    pair = REVIEWABLE.get(kind)
    if not pair:
        return f"Unknown kind {kind!r}. One of: {', '.join(sorted(REVIEWABLE))}."
    model, field = pair
    with db.SessionLocal() as s:
        row = s.get(model, row_id)
        if not row:
            return f"No such {kind}."
        if (approve_it and kind == "objection" and not brand_wide
                and scope_unconfirmed(row)):
            return ("Say what this answer is true of before approving it. A "
                    "product answer approved with no scope is claimed of "
                    "everything this account sells — “dishwasher safe” read "
                    "off one product page becomes a promise about the "
                    "porcelain too. Pick the item, or tick that it really is "
                    "true brand-wide.")
        row.review = prov.APPROVED if approve_it else prov.REJECTED
        if approve_it:
            row.approved_by, row.approved_at = by, db.utcnow()
        s.commit()
        label = getattr(row, field, "") or row_id
    return (f"Approved — {kind} “{label}” is now in use, and final."
            if approve_it else f"Rejected {kind} “{label}”.")


def add_audience(tenant: str, key: str, name: str, pains: list[str],
                 vocabulary: list[str], buying_trigger: str = "",
                 decision_timeline: str = "", origin: str = "human",
                 source: str = "", review: str = "") -> str:
    key = (key or "").strip().lower().replace(" ", "_")
    if not key or not name:
        return "An audience needs a key and a name."
    review = review or (prov.APPROVED if prov.lands_approved(origin)
                        else prov.PROPOSED)
    with db.SessionLocal() as s:
        existing = s.query(db.KbAudience).filter(
            db.KbAudience.tenant == tenant, db.KbAudience.key == key).first()
        if existing:
            # An approved segment is final. A client re-submitting through an
            # intake link, or a later upload, proposes a change — it does not
            # silently redefine who the buyer is.
            res = prov.apply_fields(
                existing,
                {"name": name, "buying_trigger": buying_trigger,
                 "decision_timeline": decision_timeline},
                origin, source, table="kb_audiences", tenant=tenant)
            if prov.may_write("pains", existing.origin or "", existing.review or "",
                              origin):
                existing.pains, existing.vocabulary = pains, vocabulary
            s.commit()
            if res["conflicts"]:
                return (f"Audience {key} is approved — left unchanged. "
                        f"Disagreement recorded on: {', '.join(res['conflicts'])}.")
            return f"Updated audience {key} for {tenant}."
        s.add(db.KbAudience(
            tenant=tenant, key=key, name=name, pains=pains,
            vocabulary=vocabulary, buying_trigger=buying_trigger,
            decision_timeline=decision_timeline, origin=origin, review=review,
            source=source, fingerprint=prov.fingerprint(key),
            approved_by="seed" if origin == "seed" else "",
            approved_at=db.utcnow() if review == prov.APPROVED else None))
        s.commit()
    return f"Added audience {key} for {tenant}."


def add_objection(tenant: str, objection: str, response: str,
                  audience_key: str = "", escalate: str = "no",
                  origin: str = "human", source: str = "",
                  review: str = "", entity_key: str = "",
                  situations: list[str] | None = None) -> str:
    if not objection or not response:
        return "An objection needs both the objection and the approved answer."
    tags = list(situations or [])
    if tags:
        valid = globals()["situations"](tenant)
        unknown = [t for t in tags if t not in valid]
        if unknown:
            return (f"Unknown tags for {tenant}: {', '.join(unknown)}\n"
                    f"Valid: {', '.join(sorted(valid))}")
    review = review or (prov.APPROVED if prov.lands_approved(origin)
                        else prov.PROPOSED)
    fp = prov.fingerprint(objection, entity_key)
    with db.SessionLocal() as s:
        # This table inserted unconditionally, so every re-seed duplicated the
        # whole set. Same objection, same answer -> one row.
        dupe = s.query(db.KbObjection).filter(
            db.KbObjection.tenant == tenant,
            db.KbObjection.fingerprint == fp).first()
        if dupe:
            if prov.may_write("response", dupe.origin or "", dupe.review or "",
                              origin) and response != dupe.response:
                dupe.response = response
                s.commit()
                return f"Updated the answer to that objection for {tenant}."
            if response != dupe.response:
                prov.record_conflict(tenant, "kb_objections", dupe.id,
                                     "response", dupe.response, response,
                                     origin, source)
                return (f"That objection is already answered and approved for "
                        f"{tenant} — the differing answer was recorded, not applied.")
            return f"Already on file for {tenant}."
        s.add(db.KbObjection(tenant=tenant, objection=objection,
                             response=response, audience_key=audience_key,
                             escalate=escalate, origin=origin, review=review,
                             source=source, fingerprint=fp,
                             entity_key=entity_key, situations=tags,
                             approved_by="seed" if origin == "seed" else "",
                             approved_at=db.utcnow() if review == prov.APPROVED else None))
        s.commit()
    return f"Added objection for {tenant} ({len(objections(tenant))} total)."


def add_entity(tenant: str, type: str, key: str, name: str,
               description: str = "", price: str = "",
               attributes: dict | None = None, source: str = "",
               origin: str = "human", review: str = "") -> str:
    """Add or update a thing being sold, respecting who owns which field.

    The store owns price and availability forever — those change on their own
    and re-approving a price is how a catalogue goes stale. Everything else is
    editorial: once approved, a sync or an upload that disagrees records a
    conflict rather than overwriting.
    """
    key = (key or "").strip().lower().replace(" ", "-")
    if not key or not name:
        return "An entity needs a key and a name."
    review = review or (prov.APPROVED if prov.lands_approved(origin)
                        else prov.PROPOSED)
    with db.SessionLocal() as s:
        existing = s.query(db.KbEntity).filter(
            db.KbEntity.tenant == tenant, db.KbEntity.key == key).first()
        if existing:
            res = prov.apply_fields(
                existing,
                {"type": type, "name": name, "description": description,
                 "price": price},
                origin, source, table="kb_entities", tenant=tenant)
            if attributes is not None and prov.may_write(
                    "attributes", existing.origin or "", existing.review or "",
                    origin):
                existing.attributes = attributes
            if source:
                existing.source = source
            existing.verified_at = db.utcnow()
            s.commit()
            if res["conflicts"]:
                return (f"{key} is approved — kept as approved. Disagreement "
                        f"recorded on: {', '.join(res['conflicts'])}.")
            return f"Updated {type} {key} for {tenant}."
        s.add(db.KbEntity(
            tenant=tenant, key=key, type=type, name=name,
            description=description, price=price,
            attributes=attributes if attributes is not None else {},
            source=source or "captured", origin=origin, review=review,
            fingerprint=prov.fingerprint(key),
            approved_by="seed" if origin == "seed" else "",
            approved_at=db.utcnow() if review == prov.APPROVED else None,
            verified_at=db.utcnow()))
        s.commit()
    return f"Added {type} {key} for {tenant}."


# --------------------------------------------------------------------------
# Guided intake.
#
# The reason a knowledge base stays empty is never that writing to it is hard —
# it's that nobody remembers what's missing. These steps are ordered by what
# unblocks the most: a brand with no voice blocks every generator, while a
# fourth audience segment blocks nothing. `next_step` asks one question; the
# answer comes back as ordinary text and is parsed by code, not a model.
# --------------------------------------------------------------------------

INTAKE_STEPS = [
    dict(id="display_name", asks="brand",
         q="What is this brand called, exactly as it should appear in writing?",
         hint="Just the name."),
    dict(id="positioning", asks="brand",
         q="One sentence: what do they do, and for whom?",
         hint="Plain words, no tagline."),
    dict(id="tone", asks="brand",
         q="Three or four words for how they sound.",
         hint="e.g. direct, warm, unhurried, no hype"),
    dict(id="banned_claims", asks="brand",
         q="What must this brand NEVER claim? One per line or separated by semicolons.",
         hint="Origin, production method, guarantees, medical claims — anything "
              "that is a legal or brand risk. This becomes a hard rule."),
    dict(id="audience", asks="audience",
         q="Describe one buyer segment.",
         hint="key | name | pains (semicolons) | words they use (semicolons)"),
    dict(id="objection", asks="objection",
         q="What is one reason a deal stalls, and how do you answer it?",
         hint="objection | your approved answer"),
    dict(id="entity", asks="entity",
         q="Name one thing they sell.",
         hint="type | key | name | price | description   (type = offer|product|space|service)"),
    dict(id="claim", asks="claim",
         q="One thing this brand can prove, with the number.",
         hint="claim | evidence | situation tags (spaces)"),
    dict(id="next_steps", asks="brand",
         q="What do you want them asked to do on a first reply?",
         hint="just the ask, e.g. 'a walkthrough' or 'a sample to the studio'"),
]

_STEP = {s["id"]: s for s in INTAKE_STEPS}


def gaps(tenant: str) -> list[dict]:
    """Every intake step still unanswered, in the order they should be answered.

    Counts proposals as answered — deliberately, and in contrast to
    `completeness()`. The question this asks is "has anybody told us yet",
    not "may we use it". A client whose objection is sitting in the review
    queue has already answered; asking them again because nobody has approved
    it yet is the fastest way to make someone abandon an intake form.
    """
    b = brand(tenant)
    voice = (b.voice or {}) if b else {}
    have = {
        "display_name": bool(b and b.display_name and b.display_name != tenant.title()),
        "positioning": bool(b and b.positioning),
        "tone": bool(voice.get("tone")),
        "banned_claims": bool(b and b.banned_claims),
        "audience": len(audiences(tenant, include_proposed=True)) > 0,
        "objection": len(objections(tenant, include_proposed=True)) > 0,
        "entity": len(entities(tenant, available_only=False,
                               include_proposed=True)) > 0,
        "claim": len(claims(tenant)) + len(pending_claims(tenant)) > 0,
        # Without this the decision layer has nothing to propose and the ask
        # comes back empty — which is exactly what happened to the agency when
        # its hardcoded offer keys were removed and nothing replaced them.
        "next_steps": bool(b and (b.next_steps or {})),
    }
    return [s for s in INTAKE_STEPS if not have.get(s["id"])]


def next_step(tenant: str) -> dict | None:
    g = gaps(tenant)
    return g[0] if g else None


def apply_answer(tenant: str, step_id: str, text: str,
                 source: str = "owner") -> str:
    """Route a free-text answer into the right table. Deterministic parsing —
    a model guessing which field a sentence belongs to is a silent-corruption
    machine, and the KB is the one place nothing may be silently wrong."""
    step = _STEP.get(step_id)
    text = (text or "").strip()
    if not step:
        return "That question expired — send /next for the current one."
    if not text:
        return "Nothing captured."

    # The scalar brand fields accept anything, which means an answer typed for a
    # different question lands as plausible-looking garbage — a pipe-formatted
    # objection became a four-word "voice" in testing. A pipe is never valid in
    # these, so treat it as a misrouted answer and say so.
    # banned_claims belongs here too: a misrouted answer stored as a banned
    # phrase would silently reject legitimate drafts forever. Fail-closed in
    # the wrong direction is still wrong.
    if step_id in ("display_name", "positioning", "tone", "banned_claims",
                   "next_steps") and "|" in text:
        return (f"That looks like an answer to a different question — "
                f"{_STEP[step_id]['hint']}. Send /next to see the current one.")

    if step_id == "display_name":
        return set_brand(tenant, display_name=text)
    if step_id == "positioning":
        return set_brand(tenant, positioning=text)
    if step_id == "tone":
        words = _split(text, ",") or _split(text, " ")
        if len(words) > 8:
            return ("Tone is three or four words, not a sentence — "
                    "e.g. direct, warm, unhurried.")
        return set_brand(tenant, tone=text)
    if step_id == "next_steps":
        b = brand(tenant)
        steps = dict((b.next_steps or {}) if b else {})
        steps["default"] = {"ask": text}
        steps.setdefault("first_contact", {"ask": text})
        return set_brand(tenant, next_steps=steps)
    if step_id == "banned_claims":
        phrases = _split(text.replace("\n", ";"))
        return "\n".join(add_banned(tenant, p) for p in phrases) or "Nothing captured."

    # A client filling their own intake link is a source, not an authority.
    # Their claims already waited for review; their audiences, objections and
    # entities went live the moment they typed them, which is the same
    # over-claiming risk with none of the same protection.
    origin = "human" if source == "owner" else "client"
    ref = "" if source == "owner" else f"submitted by {source}"

    parts = [p.strip() for p in text.split("|")]
    if step_id == "audience":
        if len(parts) < 4:
            return f"Format: {step['hint']}"
        return add_audience(tenant, parts[0], parts[1],
                            _split(parts[2]), _split(parts[3]),
                            origin=origin, source=ref)
    if step_id == "objection":
        if len(parts) < 2:
            return f"Format: {step['hint']}"
        return add_objection(tenant, parts[0], parts[1],
                             origin=origin, source=ref)
    if step_id == "entity":
        if len(parts) < 3:
            return f"Format: {step['hint']}"
        return add_entity(tenant, parts[0], parts[1], parts[2],
                          description=parts[4] if len(parts) > 4 else "",
                          price=parts[3] if len(parts) > 3 else "",
                          origin=origin, source=ref)
    if step_id == "claim":
        if len(parts) < 3:
            return f"Format: {step['hint']}"
        import re as _re
        tags = [t.strip().lower() for t in _re.split(r"[\s,]+", parts[2]) if t.strip()]
        # A client will always over-claim. Their proof waits for review; the
        # owner's does not.
        return add_claim(tenant, parts[0], parts[1], tags, source=ref,
                         origin=origin,
                         status="pending" if source != "owner" else "active")
    return "Unrecognised step."


# --------------------------------------------------------------------------
# Seed — MarketingThatWorks.co (tenant "agency"), tenant zero.
#
# Every claim below is from marketingthatworks.co or was established from live
# data in the platform-design work. Nothing invented: if a number isn't
# public or verifiable, it isn't here.
# --------------------------------------------------------------------------

_AGENCY_CLAIMS = [
    # (claim, evidence, proof_type, source, situations, strength)
    ("Took a coaching company from $6M to $20M as fractional CMO",
     "$6M → $20M in 18 months, $15M ad spend directed", "case_study",
     "marketingthatworks.co — Heartcore Business",
     ["coaching", "digital_products", "scaling", "big_spender"], "strong"),

    ("Built, scaled and sold my own Shopify brand, then ran the acquirer's portfolio",
     "Top 1% Shopify, sold to an aggregator; then $1M+/mo paid social across 8 brands",
     "case_study", "marketingthatworks.co — Miaroo",
     ["ecom_dtc", "wants_operator", "solo_operator_doubt", "big_spender"], "strong"),

    ("Directed $60M+ in ad spend across a decade",
     "$60M+", "data", "marketingthatworks.co",
     ["big_spender", "scaling"], "supporting"),

    ("Took a regional produce brand from $300k to $1M/year",
     "$300k → $1M", "case_study", "marketingthatworks.co — CV Harvest",
     ["ecom_dtc", "food_bev", "scaling", "no_traffic"], "strong"),

    ("Raised catalog pricing 28% with no drop in conversion",
     "3.5× → 4.5× landed cost across 224 variants, conversion rate held",
     "data", "Baci Milano USA — owner-operated, verified in Shopify",
     ["ecom_inventory", "margin_problem", "pricing_fear"], "strong"),

    ("Diagnosed an ad collapse that was actually a stockout",
     "In-season zodiac SKUs at 100% sell-through; sessions flat, conversion halved",
     "data", "Baci Milano USA — Meta + Shopify cross-check",
     ["ecom_inventory", "ads_not_working"], "strong"),

    ("Ran event-venue paid acquisition at 7×+ ROAS",
     "7×+ ROAS on event-planning campaigns", "data",
     "Miami Ironside — Google Ads + analytics, May 2026",
     ["local_venue", "ads_not_working"], "strong"),

    ("Built a brand's US market entry after several failed attempts",
     "Placements incl. Four Seasons and the Ritz-Carlton Yacht Collection",
     "case_study", "marketingthatworks.co — Baci Milano USA",
     ["us_market_entry", "ecom_inventory", "b2b_spec"], "strong"),

    ("Built an affiliate channel from zero",
     "0 → 100+ affiliates in a year; expansion into Australia and Dubai",
     "case_study", "marketingthatworks.co — Arabelle Yee",
     ["new_channel", "digital_products", "scaling"], "supporting"),

    ("Recovered a failing email programme on 1.2M contacts",
     "Domain reputation restored to High for the first time; IP reputation repaired",
     "case_study", "marketingthatworks.co — deliverability rescue",
     ["email_problems", "digital_products"], "strong"),

    ("Led marketing and sales teams of 30+",
     "30+ personnel", "data", "marketingthatworks.co",
     ["team_exists", "solo_operator_doubt"], "supporting"),

    ("Directed marketing for a 1,652-unit residential and hotel development",
     "1,652 units; $60M in sales generated for South Florida brokers",
     "case_study", "marketingthatworks.co — Opus Communities",
     ["real_estate", "local_venue"], "supporting"),
]

_AGENCY_AUDIENCES = [
    ("ecom_inventory", "E-commerce owner, $2–10M, carries stock",
     ["cash trapped in inventory", "SKUs that never sell",
      "ads that work then stop", "margin eaten by discounting"],
     ["ROAS", "AOV", "sell-through", "landed cost", "MOQ"],
     "A month where ads stopped working, or a cash squeeze from a bad buy",
     "2–6 weeks"),
    ("digital_products", "Coaching / info / digital products operator",
     ["launch-dependent revenue", "list fatigue", "no evergreen engine",
      "deliverability decay"],
     ["funnel", "launch", "list", "webinar", "LTV"],
     "A launch that underperformed the last one", "1–4 weeks"),
    ("local_venue", "Venue, events or local service business",
     ["inbound enquiries that go cold", "seasonality",
      "no idea which channel produced the booking"],
     ["bookings", "site visit", "walk-in", "per-head"],
     "A quiet quarter or a competitor taking known accounts", "2–8 weeks"),
    ("b2b_spec", "B2B distributor / specification sales",
     ["long cycles", "invisible in search", "samples that go nowhere",
      "reps buried in admin"],
     ["spec", "A&D", "trade", "sample", "project"],
     "Losing a specification they expected to win", "1–3 months"),
]

_AGENCY_OBJECTIONS = [
    ("You're one person — can you actually handle this?",
     "I've led marketing and sales teams of 30+ and directed $60M in spend. "
     "What you get from me is the strategic layer plus installed systems that "
     "keep running; execution capacity scales with a senior bench.",
     "", "no"),  # applies to every segment — audience_key takes AUDIENCE keys,
                 # not situation tags (solo_operator_doubt is a situation)
    ("We tried an agency before and it didn't work.",
     "Most agencies rent you attention and it leaves when the retainer does. "
     "The deliverable here is machinery you keep — documented, automated, and "
     "operated by your team after handoff.", "", "no"),
    ("How fast will we see results?",
     "Recovery first: something verifiable in your own data inside 2–4 weeks — "
     "spend recovered, demand you already paid for and dropped, or margin "
     "leaking per order. Growth work comes after that's banked.", "", "no"),
    ("Why wouldn't we just hire someone in-house?",
     "You should, eventually. A hire costs more, takes 3 months to ramp, and "
     "leaves with the knowledge. I build the system first so the hire inherits "
     "something instead of starting over.", "", "no"),
    ("AI content doesn't work / we tried it and it was generic.",
     "Agreed, and I'll tell you which parts genuinely don't work yet. What "
     "does work is grounded generation: systems that write from your real "
     "product data and rules, with a human approving before anything ships.",
     "", "no"),
    ("Can you guarantee a specific result?",
     "No, and anyone who does is selling you something. I'll show you the "
     "baseline, the measurement design, and the kill criteria before we start.",
     "", "yes"),
]

_AGENCY_OFFERS = [
    ("diagnostic", "Paid diagnostic",
     "2–3 weeks. Marketing audit, unit-economics model and a 90-day plan, "
     "delivered as a working session. Findings are verifiable in your own data.",
     {"duration": "2-3 weeks", "deliverable": "audit + model + 90-day plan"},
     "from $5,000"),
    ("fractional_cmo", "Fractional CMO retainer",
     "Defined operating rhythm — weekly leadership sync, monthly plan and "
     "review, quarterly reset — plus ownership of outcomes on one or two named "
     "channels and a capped execution allowance.",
     {"minimum_term": "6 months", "cadence": "weekly + monthly + quarterly",
      "execution": "capped allowance, overflow scoped separately"},
     "from $7,500/mo"),
    ("systems_install", "Systems install",
     "Fixed scope, fixed price. Ad-spend and inventory guard, catalog "
     "repricing, replenishment engine, content or response systems — built, "
     "run, and handed over with the operating manual.",
     {"pricing": "fixed", "handover": "documented + trained"},
     "scoped per build"),
]


# The agency's own vocabulary, as rows rather than as the module constant.
# `seed_agency` looped no situations at all, so `situations("agency")` fell back
# to `SITUATIONS` — a bare set with NO patterns — and `situation_patterns()`
# returned {}. Nothing could ever pattern-match for the agency; only the learned
# tagger worked there, and a crawl of its own site could tag nothing.
#
# Patterns are roots, not whole phrases: real people write "raising prices",
# not "raise prices".
_AGENCY_SITUATIONS = [
    ("ecom_dtc", "who_they_are", "sells direct to consumers online",
     [["shopify"], ["dtc"], ["our store"], ["online store"], ["ecommerce"]]),
    ("ecom_inventory", "who_they_are", "carries stock, so cash sits in inventory",
     [["inventory"], ["stock"], ["sku"], ["reorder"], ["warehouse"]]),
    ("digital_products", "who_they_are", "sells courses, memberships or info products",
     [["course"], ["membership"], ["funnel"], ["launch"], ["webinar"]]),
    ("coaching", "who_they_are", "coaching or consulting business",
     [["coaching"], ["coach"], ["clients"], ["program"]]),
    ("local_venue", "who_they_are", "a venue, events or local service business",
     [["venue"], ["event"], ["booking"], ["walk-in"], ["local"]]),
    ("b2b_spec", "who_they_are", "sells into specification or trade channels",
     [["spec"], ["trade"], ["architect"], ["designer"], ["distributor"]]),
    ("real_estate", "who_they_are", "property or development marketing",
     [["development"], ["units"], ["real estate"], ["broker"]]),
    ("food_bev", "who_they_are", "food or beverage brand",
     [["food"], ["beverage"], ["produce"], ["grocery"]]),
    ("scaling", "problem", "growing and the current setup will not carry it",
     [["scale"], ["scaling"], ["grow"], ["growth"], ["next level"]]),
    ("margin_problem", "problem", "revenue is there and margin is not",
     [["margin"], ["profitab"], ["cost"], ["unit econom"]]),
    ("ads_not_working", "problem", "paid acquisition stopped performing",
     [["ads"], ["roas"], ["cac"], ["facebook"], ["meta"], ["google ads"]]),
    ("no_traffic", "problem", "not enough demand reaching them at all",
     [["traffic"], ["no one"], ["nobody finds"], ["visibility"], ["seo"]]),
    ("pricing_fear", "problem", "knows the price is wrong and is afraid to move it",
     [["price"], ["pricing"], ["raise"], ["discount"], ["too cheap"]]),
    ("email_problems", "problem", "owned channel is decaying",
     [["email"], ["deliverab"], ["open rate"], ["list"], ["klaviyo"], ["omnisend"]]),
    ("new_channel", "problem", "wants a channel they have never run",
     [["affiliate"], ["new channel"], ["expand into"], ["tiktok"], ["amazon"]]),
    ("us_market_entry", "problem", "entering the US market",
     [["us market"], ["united states"], ["market entry"], ["expand to the us"]]),
    ("team_exists", "doubt", "wonders whether there is a team behind it",
     [["team"], ["capacity"], ["bandwidth"], ["who does the work"]]),
    ("solo_operator_doubt", "doubt", "wonders whether one person can carry it",
     [["one person"], ["just you"], ["freelance"], ["agency or"]]),
    ("big_spender", "doubt", "spends enough that competence matters",
     [["budget"], ["spend"], ["per month"], ["monthly spend"]]),
    ("wants_operator", "doubt", "wants someone who has run it, not advised on it",
     [["operator"], ["actually run"], ["own brand"], ["hands on"]]),
]

def seed_agency(force: bool = False) -> dict:
    """Populate the `agency` tenant. Idempotent unless force=True."""
    tenant = "agency"

    # The vocabulary is ensured on EVERY call, ahead of the idempotence guard
    # below. That guard returns early whenever the brand row exists, so once
    # `_AGENCY_SITUATIONS` was written it could never actually reach a database
    # that had already been seeded — which is why production still reported
    # `situation_patterns("agency") == {}` long after the rows were authored,
    # and why a crawl of the agency's own site could tag nothing. The only way
    # to apply them was force=True, which DELETES every claim, audience,
    # objection and entity: a destructive operation to fix a missing one.
    #
    # `add_situation` is idempotent per tag and updates in place, so calling it
    # every time is free and self-healing.
    ensured = 0
    for tag, kind, desc, pats in _AGENCY_SITUATIONS:
        add_situation(tenant, tag, pats, desc, kind=kind, origin="seed")
        ensured += 1

    with db.SessionLocal() as s:
        existing = s.get(db.KbBrand, tenant)
        if existing and not force:
            return {"status": "already seeded — pass force=True to overwrite",
                    "situations_ensured": ensured}
        if force:
            for model in (db.KbClaim, db.KbAudience, db.KbObjection, db.KbEntity):
                s.query(model).filter(model.tenant == tenant).delete()
            if existing:
                s.delete(existing)
            s.flush()

        s.add(db.KbBrand(
            tenant=tenant,
            display_name="MarketingThatWorks.co",
            positioning="Agentic performance marketing. Strategist and fractional "
                        "CMO who operates his own e-commerce brands, so the advice "
                        "comes with a P&L behind it.",
            elevator={
                "sentence": "I design and operate AI-driven acquisition systems "
                            "inside companies that want the upside without the headcount.",
                "paragraph": "A decade as CMO and fractional CMO across e-commerce, "
                             "coaching, real estate and luxury — $60M+ in ad spend "
                             "directed, teams of 30+ led, and brands of my own "
                             "including one sold while top 1% on Shopify. I don't "
                             "advise e-commerce brands from the outside; I run two.",
            },
            voice={
                "tone": ["direct", "specific", "operator-not-consultant",
                         "unhurried", "no hype"],
                "do_say": ["here's what I'd look at first", "in your own data",
                           "I run two of my own brands", "the number is"],
                "never_say": ["synergy", "leverage as a verb", "circle back",
                              "game-changer", "unlock your potential",
                              "in today's fast-paced world", "I hope this email finds you well"],
                "examples": [],  # filled from the edit diff once drafts start shipping
            },
            banned_claims=[
                # Promising outcomes is what creates the month-five conversation.
                "guarantee", "guaranteed results", "we guarantee",
                "risk-free", "double your revenue", "10x your",
                # Never assert a client metric that isn't already public.
                "confidential client",
            ],
            approval_policy={"auto_publish": [],
                             "requires_signoff": ["outbound_email", "proposal"]},
            selection={"primary_type": "offer", "modes": [{"mode": "keyword"}]},
            # Previously hardcoded in brief._decide as agency offer keys. Now
            # data, so a tenant selling spaces or products is not routed to a
            # "diagnostic" that exists only in this catalogue.
            next_steps={
                "referral_intro": {"entity_key": "fractional_cmo",
                                   "ask": "a 25-minute call this week"},
                "follow_up": {"entity_key": "diagnostic",
                              "ask": "pick the thread back up with one specific next step"},
                "dormant": {"entity_key": "diagnostic",
                            "ask": "pick the thread back up with one specific next step"},
                "first_contact": {"entity_key": "diagnostic",
                                  "ask": "the paid diagnostic"},
                "default": {"entity_key": "diagnostic", "ask": "the paid diagnostic"},
            },
        ))

        # Seeded rows are owner-authored facts, so they land approved — but
        # they carry the same provenance columns as anything else, or the
        # first re-seed duplicates them and no sync knows to leave them alone.
        _seed = dict(origin="seed", review=prov.APPROVED, approved_by="seed",
                     approved_at=db.utcnow())

        # Situations are ensured above, before the idempotence guard, so they
        # are deliberately not inserted here.

        for claim, ev, ptype, src, sits, strength in _AGENCY_CLAIMS:
            bad = set(sits) - SITUATIONS
            if bad:
                raise ValueError(f"unknown situation tags {bad} on claim {claim!r}")
            s.add(db.KbClaim(tenant=tenant, claim=claim, evidence=ev,
                             proof_type=ptype, source=src, situations=sits,
                             strength=strength, verified_at=db.utcnow(),
                             fingerprint=prov.fingerprint(claim), **_seed))

        for key, name, pains, vocab, trigger, timeline in _AGENCY_AUDIENCES:
            s.add(db.KbAudience(tenant=tenant, key=key, name=name, pains=pains,
                                vocabulary=vocab, buying_trigger=trigger,
                                decision_timeline=timeline,
                                fingerprint=prov.fingerprint(key), **_seed))

        for obj, resp, aud, esc in _AGENCY_OBJECTIONS:
            s.add(db.KbObjection(tenant=tenant, objection=obj, response=resp,
                                 audience_key=aud, escalate=esc,
                                 fingerprint=prov.fingerprint(obj), **_seed))

        for key, name, desc, attrs, price in _AGENCY_OFFERS:
            s.add(db.KbEntity(tenant=tenant, type="offer", key=key, name=name,
                              description=desc, attributes=attrs, price=price,
                              source="marketingthatworks.co",
                              verified_at=db.utcnow(),
                              fingerprint=prov.fingerprint(key), **_seed))
        s.commit()
    return {"status": "seeded", **completeness(tenant)}
