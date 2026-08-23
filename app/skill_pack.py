"""The first four skills, written against the frozen contract.

None of these is Baci-specific. Each is a template that reads its client out of
the knowledge base, which is locked decision #3 — the moment one of them is
forked for an account, the platform stops existing. Baci is simply the account
they are pointed at first, and the one they were measured against.

    catalog_compliance   the store's own copy, checked against the store's rules
    catalog_seo_rewrite  compliant replacements, composed by code, approval-gated
    inbound_reply        a grounded answer to a real question
    ad_copy              ad text the model writes from one approved claim

## Where the model writes, and where code does

`inbound_reply` and `ad_copy` are model calls: the model gets the bundle and
writes, and deterministic code decides what it may write *from* and whether the
result ships. That is the platform's first locked decision — AI at the edges,
selection and validation as code either side.

`catalog_seo_rewrite` composes by code instead, and that is not a downgrade. A
meta description is 155 characters of "name, proof, invitation"; composing it
from an approved claim is the Atlas's rule (`the prompt is composed from the
brief by code`) applied where the brief is the whole artifact. It also means the
replacement carries a `claim_id` by construction, so the citation check passes
for a real reason rather than a decorative one.

## Why the metadata sweep is not the site scanner again

`compliance.scan` reads the public site and matches against rendered prose.
`_clean` strips `<head>` before matching, so a meta description is invisible to
it — and a meta description is *the* field a violation hides in, because it is
templated across an entire catalogue at once and never read by a human after
the template is written. Baci's own audit is the shape of this: 110 flagged
strings, 96 of them one repeated SEO-meta template. The crawler saw none of
those 96.

## Why the rewrite composes rather than prompts

A meta description is 155 characters of "name, proof, invitation". Composing
that from an approved claim by code is not a downgrade from a model call — it
is the Atlas's rule (`the prompt is composed from the brief by code`) applied
where the brief is the whole artifact. It also means the replacement carries a
`claim_id` by construction, so the validator's citation check passes for a real
reason rather than a decorative one, and the whole skill is testable offline.
"""
from __future__ import annotations

import html as _htmllib
import re

from . import coherence, compliance, responder, sites
from . import kb as kb_mod
from .skill import Context, Skill, register

_TAGS = re.compile(r"<[^>]+>")

# Fields of a product that carry copy, in the order an operator should fix
# them. `seo_description` leads because it is both the most templated and the
# least visible.
COPY_FIELDS = ("seo_description", "seo_title", "title", "body")


# ---------------------------------------------------------------------------
# Reading the catalogue
#
# Behind one function so the live REST path and a fixture are the same shape to
# everything above. Tests replace `fetch_products`; nothing else changes.
# ---------------------------------------------------------------------------


def _flag(value, default: bool = False) -> bool:
    """A yes/no parameter that may arrive as a bool OR as a plan's string.

    `bool("no")` is True — so the moment plans started carrying these fields
    as text, a saved "no" would have switched the thing ON. Absent or blank
    means the default, exactly like the parameter not being passed.
    """
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


def _strip(html_text: str) -> str:
    return " ".join(_htmllib.unescape(_TAGS.sub(" ", html_text or "")).split())


def _fetch_products_live(profile: dict, limit: int) -> tuple[list[dict], dict]:
    """Products with their copy fields and SEO metafields.

    Returns `(products, coverage)`. Coverage is not decoration: SEO metafields
    are one REST call per product, so a large catalogue is deliberately only
    partly scanned and the caller must be told that rather than shown a clean
    result over a third of the shelf.
    """
    from . import shopify_seo

    store = shopify_seo._store(profile)
    page = shopify_seo._get(store, "products.json", {
        "limit": max(1, min(250, limit)),
        "fields": "id,handle,title,body_html,status"})
    raw = page.get("products") or []

    total = None
    try:
        total = (shopify_seo._get(store, "products/count.json") or {}).get("count")
    except Exception:                                            # noqa: BLE001
        total = None                       # unknown stays unknown, see below

    out = []
    for p in raw:
        seo_title, seo_desc = "", ""
        try:
            mf = shopify_seo._get(store, f"products/{p['id']}/metafields.json",
                                  {"namespace": "global"})
            for m in mf.get("metafields") or []:
                if m.get("key") == "title_tag":
                    seo_title = m.get("value") or ""
                elif m.get("key") == "description_tag":
                    seo_desc = m.get("value") or ""
        except Exception:                                        # noqa: BLE001
            # A metafield read that failed is NOT an empty metafield. Marking
            # it unread keeps "we looked and it was clean" apart from "we never
            # looked", which is the distinction this whole layer is built on.
            seo_title = seo_desc = None

        # Lowercased to match `catalog_sync`, which keys a KbEntity on
        # `handle.strip().lower()`. The validator looks an entity up by that
        # key, so a handle that differs in case would fail `unknown_entity` on
        # a product that is sitting right there in the knowledge base.
        out.append({"id": str(p.get("id")),
                    "handle": (p.get("handle") or "").strip().lower(),
                    "title": p.get("title") or "",
                    "body": _strip(p.get("body_html")),
                    "seo_title": seo_title, "seo_description": seo_desc,
                    "status": p.get("status") or ""})

    return out, {"scanned": len(out), "catalogue_total": total,
                 "complete": total is not None and len(out) >= total}


fetch_products = _fetch_products_live


# ---------------------------------------------------------------------------
# 1 · Catalogue compliance
# ---------------------------------------------------------------------------


def _sweep(ctx: Context) -> dict:
    """Find the violations. Emits nothing.

    Kept pure because the rewrite skill needs the same findings, and the first
    version of this simply called the report skill — which emitted the report
    into the rewrite's context, so the rewrite's first "replacement" was a
    440-character compliance summary that then failed the ban list it was
    quoting. `emit` has one caller per artifact, and a function that both finds
    and publishes cannot be reused by anything that only wants to find.
    """
    profile = sites.get(str(ctx.params.get("site") or ""))
    limit = int(ctx.params.get("limit") or 50)

    products, cov = fetch_products(profile, limit)
    if not products:
        ctx.note("the catalogue read returned no products — check the store "
                 "connection before reading this as a clean result")
        return {"products": 0, "coverage": cov, "findings": [], "unread": [],
                "groups": []}

    unread, findings = [], []
    for p in products:
        for fname in COPY_FIELDS:
            value = p.get(fname)
            if value is None:
                unread.append({"handle": p["handle"], "field": fname})
                continue
            if not value.strip():
                continue
            hits, questions = compliance._match(ctx.tenant, value)
            for h in hits:
                findings.append({"handle": p["handle"], "product_id": p["id"],
                                 "name": p["title"], "field": fname,
                                 "phrase": h["phrase"], "context": h["context"],
                                 "kind": "violation"})
            for q in questions:
                findings.append({"handle": p["handle"], "product_id": p["id"],
                                 "name": p["title"], "field": fname,
                                 "phrase": q["phrase"], "context": q["context"],
                                 "kind": "review"})

    violations = [f for f in findings if f["kind"] == "violation"]

    # Group by (field, phrase). A templated breach is one decision repeated N
    # times, and reporting it as N findings buries the one thing to fix.
    groups: dict[tuple, list] = {}
    for f in violations:
        groups.setdefault((f["field"], f["phrase"]), []).append(f)
    ranked = sorted(groups.items(), key=lambda kv: -len(kv[1]))

    if unread:
        ctx.note(f"{len(unread)} field(s) could not be read and were not "
                 f"counted as clean")
    if not cov["complete"]:
        ctx.note(f"scanned {cov['scanned']} product(s)"
                 + (f" of {cov['catalogue_total']}" if cov["catalogue_total"]
                    else "; catalogue size unknown")
                 + " — raise `limit` for the rest")

    return {"products": len(products), "coverage": cov, "findings": findings,
            "unread": unread, "violations": violations, "ranked": ranked,
            "groups": [{"field": f, "phrase": p, "count": len(r),
                        "handles": [x["handle"] for x in r]}
                       for (f, p), r in ranked]}


def _run_catalog_compliance(ctx: Context) -> dict:
    found = _sweep(ctx)
    cov = found["coverage"]
    violations = found.get("violations") or []

    if not violations:
        return {"summary": f"no violations in {cov.get('scanned', 0)} product(s)",
                **found}

    lines = [f"{len(violations)} banned-claim violation(s) across "
             f"{len({f['handle'] for f in violations})} product(s), "
             f"{cov['scanned']} scanned.", ""]
    for (fname, phrase), rows in found["ranked"]:
        lines.append(f"{len(rows)}x  {fname}  —  {phrase!r}")
        lines.append(f"      e.g. {rows[0]['handle']}: {rows[0]['context'][:160]}")
    ctx.emit("\n".join(lines), fmt="report", require_citation=False)

    return {"summary": f"{len(violations)} violation(s), "
                       f"{len(found['ranked'])} distinct pattern(s)", **found}


register(Skill(
    key="catalog_compliance",
    name="Catalogue compliance sweep",
    does="Check product titles, descriptions and SEO metadata in the store "
         "against this brand's banned claims. Reports violations grouped by "
         "the template that caused them. Reads only — changes nothing.",
    system_key="catalog_compliance",
    tier=1,                       # rules are all it needs, and tier 1 is cheap
    needs=("rules.banned_claims",),
    # The ONE constitutive declaration in the pack. Every other gap makes an
    # output thinner; this one makes it false — a sweep against an empty ban
    # list reports a catalogue CLEAN that nothing checked, and Baci's own audit
    # is 110 violations that a sweep like that would have blessed.
    constitutive=("banned_claims",),
    params=("site", "limit"),
    writes=False,
    produces="report",
    run=_run_catalog_compliance))


# ---------------------------------------------------------------------------
# 2 · Compliant SEO rewrite
# ---------------------------------------------------------------------------

_META_MAX = 155
_BRAND_WIDE = "brand-wide"        # what resolve() reports for an unscoped claim


def _compose_meta(name: str, claim: str, positioning: str) -> str:
    """Name, proof, then whatever of the positioning still fits.

    Deliberately dull. This field is read by a search engine and by someone
    deciding whether to click, and the failure mode being fixed is a clever
    template repeated across a whole catalogue.
    """
    claim = claim.rstrip(". ").strip()
    base = f"{name} — {claim}."
    if len(base) > _META_MAX:
        return base[:_META_MAX - 1].rstrip(" ,;—-") + "."
    tail = (positioning or "").strip().rstrip(".")
    if tail and len(base) + len(tail) + 2 <= _META_MAX:
        return f"{base} {tail}."
    return base


def _run_catalog_seo_rewrite(ctx: Context) -> dict:
    sweep = _sweep(ctx)
    targets = [f for f in sweep.get("findings", [])
               if f["kind"] == "violation" and f["field"] == "seo_description"]
    if not targets:
        return {"summary": "no SEO description needs rewriting",
                "coverage": sweep.get("coverage", {})}

    positioning = (ctx.rules.get("positioning") or "").strip()
    unwritable = []
    by_handle: dict[str, dict] = {}
    for f in targets:
        by_handle.setdefault(f["handle"], f)

    for handle, f in by_handle.items():
        # Proof scoped to this product first; a claim about a different
        # product is not a fact about this one, so a global claim is only a
        # fallback and is marked as such.
        # `resolve` reports a claim's scope as its entity_key, or the literal
        # "brand-wide" when it has none. A claim about a different product is
        # not proof about this one, so a scoped match wins and a brand-wide
        # claim is only the fallback — recorded as such in `proof_scope`.
        scoped = [c for c in ctx.claims if c.get("scope") == handle]
        pool = scoped or [c for c in ctx.claims
                          if c.get("scope") == _BRAND_WIDE]
        if not pool:
            unwritable.append({"handle": handle, "name": f["name"],
                               "why": "no approved claim to substantiate a "
                                      "replacement — author one for this "
                                      "product, or a catalogue-wide one"})
            continue
        pick = pool[0]
        body = _compose_meta(f["name"], pick["claim"], positioning)
        ctx.emit(body, claim_ids=[pick["claim_id"]], entity_key=handle,
                 angle="compliance_rewrite", fmt="seo_description",
                 destination="shopify:product.metafield.global.description_tag",
                 meta={"replaces": f["context"], "phrase": f["phrase"],
                       "product_id": f["product_id"],
                       "proof_scope": pick.get("scope") or "catalogue-wide"})

    if unwritable:
        ctx.note(f"{len(unwritable)} product(s) have a violation but no "
                 f"approved claim to replace it with — listed under "
                 f"`unwritable`, and they are the authoring backlog")

    return {"summary": f"{len(ctx.items)} replacement(s) drafted, "
                       f"{len(unwritable)} blocked on proof",
            "unwritable": unwritable, "coverage": sweep.get("coverage", {})}


register(Skill(
    key="catalog_seo_rewrite",
    name="Compliant SEO rewrite",
    does="Draft replacement SEO descriptions for products whose current one "
         "breaks a banned claim. Every replacement is composed from an "
         "approved claim and carries its id. Proposes only — never writes.",
    system_key="catalog_compliance",
    tier=2,                       # needs the approved claims, not the deep tier
    needs=("rules.banned_claims",),
    params=("site", "limit"),
    writes=True,
    produces="proposal",
    run=_run_catalog_seo_rewrite))


# ---------------------------------------------------------------------------
# 3 · Inbound reply
# ---------------------------------------------------------------------------


def _run_inbound_reply(ctx: Context) -> dict:
    utterance = str(ctx.params.get("utterance") or "").strip()
    if not utterance:
        ctx.note("nothing was asked")
        return {"summary": "no utterance supplied"}

    res = responder.answer(
        ctx.tenant, utterance,
        contact_id=str(ctx.params.get("contact_id") or ""),
        entity_key=str(ctx.params.get("entity_key") or ""),
        system_key=ctx.skill.system_key, run_id=ctx.run_id,
        facts=ctx.params.get("facts") or None,
        draft_with_model=bool(ctx.params.get("draft_with_model")),
        bundle=ctx.bundle)

    # A question needing live data is not a knowledge gap and must not be
    # reported as one — the responder already draws that line, so carry it
    # rather than flattening it into a refusal.
    if res.get("stage") == "lookup":
        ctx.note("this needs live data before it can be answered: "
                 + ", ".join(res.get("ready_to_call") or
                             [n["call"] for n in res.get("needs", [])]))
        return {"summary": "needs a lookup first", "needs": res.get("needs"),
                "ready_to_call": res.get("ready_to_call", [])}

    if not res.get("ok"):
        ctx.note("the reply path refused: "
                 + "; ".join(res.get("blocked_on") or ["unspecified"]))
        return {"summary": "blocked", "blocked_on": res.get("blocked_on", []),
                "stage": res.get("stage", "")}

    def _repair(previous: str, failures: list) -> str:
        """Re-ask for the reply with its rejection attached.

        A customer reply is the worst place to leave a blocked draft sitting in
        a queue — the cost of the gap is a person waiting. So it self-corrects
        on the same terms as everything else: the rules are unchanged and the
        same check runs again.

        Only the model can repair. `responder.answer` also has a deterministic
        path that assembles an approved objection response verbatim, and asking
        that to try again returns the identical text, which `emit` reads as
        "nothing more to give" and stops on — correctly, because rewording an
        approved answer is not this loop's job.
        """
        note = "\n".join(f"- {f['detail']} → {f['fix']}" for f in failures)
        fixed, _ = responder._draft(
            ctx.tenant, utterance,
            {**ctx.bundle,
             "rules": {**ctx.bundle.get("rules", {}),
                       "block": ctx.bundle.get("rules", {}).get("block", "")
                       + f"\n\n## Your previous reply was rejected\n{previous}"
                         f"\n\n## Why, and what to change\n{note}\n"
                         f"Rewrite it so none of these apply. Keep it truthful "
                         f"and keep the citation; do not argue with the rules."}})
        return fixed

    # A model draft the responder rejected is handed to `emit` anyway, so the
    # repair loop gets something to work with. Without this the only outcomes
    # were "send nothing" and "start from scratch" — and for a customer reply
    # the cost of the first is a person waiting on an answer.
    body = res.get("draft") or res.get("draft_rejected") or ""
    if not body:
        ctx.note("no reply was produced: "
                 + (res.get("draft_blocked_by")
                    or "no approved answer matched and no model was asked"))
        return {"summary": "nothing to draft",
                "grounding": (res.get("grounding") or {}).get("level", "")}

    # THE SAME CONTRACT, A DIFFERENT REFERENT. A reply's subject is the
    # QUESTION, not a product — which is why the commitment is typed by kind
    # rather than assuming an entity. The image clause is then vacuous (a reply
    # has no pictures) and the checks that remain are the ones that matter
    # here: a reply must not spend the same proof twice, and must not volunteer
    # the brand's credentials at a customer who asked where their order is.
    _ev = [c for c in (res.get("evidence") or []) if c.get("claim_id")]
    _commit = coherence.commit(
        "situation", res.get("situation") or "the question asked",
        audience=str(ctx.params.get("contact_id") or ""),
        action="answer it",
        also=[k for k in [str(ctx.params.get("entity_key") or "")] if k])

    ctx.emit(body,
             claim_ids=[c.get("claim_id") for c in _ev],
             commitment=_commit,
             parts=lambda _text: coherence.parts(
                 text=_text,
                 claims=[{"claim_id": c.get("claim_id", ""),
                          "text": c.get("claim", "") or c.get("text", ""),
                          "scope": c.get("scope", "brand-wide")}
                         for c in _ev]),
             entity_key=str(ctx.params.get("entity_key") or ""),
             situation=res.get("situation") or "",
             conversation_id=res.get("conversation_id") or "",
             angle="reply", fmt="reply",
             # Which live lookups fed this reply, so a follow-up weeks later
             # can tell a brand fact from a stock reading. The responder
             # declares them; passing them on is what stops `Output.lookups`
             # being written by one writer and missed by the other.
             lookups=res.get("lookups_used") or [],
             # Only the model path can repair. The confident path assembles an
             # objection response a human approved verbatim, and rewording that
             # is not this loop's job.
             redraft=_repair if res.get("mode") == "draft_from_context" else None)
    return {"summary": "one reply drafted",
            "grounding": (ctx.bundle.get("grounding") or {}).get("level", "")}


register(Skill(
    key="inbound_reply",
    name="Inbound reply",
    does="Answer one inbound question from approved objections, claims and "
         "prior correspondence. Refuses rather than inventing, and says "
         "whether the answer needs live data instead of knowledge.",
    system_key="service_desk",
    tier=3,
    needs=("rules.banned_claims",),
    # `thread_id` is declared so the one-reply-per-conversation guard can see
    # it: `skill.run` refuses an undeclared parameter before any check runs, so
    # a guard reading a parameter nobody may pass is a guard that never fires.
    # Optional — a first contact has no thread, and refusing those would block
    # most of what this skill is for.
    params=("utterance", "contact_id", "entity_key", "facts",
            "draft_with_model", "thread_id"),
    writes=False,
    produces="draft",
    run=_run_inbound_reply))


# ---------------------------------------------------------------------------
# 4 · Ad copy — the model writes it, code decides what it may write from
# ---------------------------------------------------------------------------

_ANGLES = ("proof", "objection", "occasion")

_AD_SYSTEM = """You are writing one short ad for this brand.

You are given exactly one approved claim to build on. Use it. Do not introduce
a second factual claim, a price, a material, an origin or a guarantee that is
not in the context — the hard rules are enforced in code after you write, so a
draft breaking one is thrown away rather than softened, and you will simply
have wasted the slot.

Match the house voice. Write the ad and nothing else: no headline label, no
options, no commentary, no hashtags. Two or three short lines."""

_ANGLE_BRIEF = {
    "proof": "Lead with the claim as the reason to buy. Plain and confident.",
    "objection": "Open by naming the hesitation below, then answer it with the "
                 "claim. Do not invent a different hesitation.",
    "occasion": "Put the claim in the moment the buyer would actually use it.",
}


def _compose_ad(claim: dict, angle: str, objections: list, entity_key: str) -> str:
    """The deterministic fallback. Dull on purpose, and honest about being it.

    This is what runs with no API key. It is not "ad copy" in any sense worth
    paying for — it is a grounded placeholder that keeps the pipeline provable
    offline, and `basis` says so on every variant it produces.
    """
    proof = claim["claim"].rstrip(". ")
    if angle == "objection" and objections:
        body = f"{objections[0]['objection'].rstrip('? ')}?\n\n{proof}."
    elif angle == "occasion" and entity_key:
        body = f"{proof}.\n\nBuilt for the table you actually set."
    else:
        body = f"{proof}."
    if claim.get("evidence"):
        body += f"\n\n({claim['evidence']})"
    return body


def _draft_ad_live(bundle: dict, claim: dict, angle: str,
                   objections: list) -> tuple[str, str]:
    """One model call for one claim. Returns `(text, why_not)`.

    **One call per claim, deliberately.** Asking for N variants in one response
    means parsing which line came from which claim, and a mis-parse would file
    the wrong `claim_id` in the ledger — attribution that is wrong is worse than
    attribution that is missing, because the anti-repeat and hygiene queries
    both trust it. Per-claim calls make attribution structural: the id is known
    before the model is asked, exactly as the SEO rewrite carries its id by
    construction.
    """
    from . import config
    if not config.ANTHROPIC_API_KEY:
        return "", "ANTHROPIC_API_KEY is not set"
    try:
        import anthropic

        parts = [bundle["rules"]["block"].strip(),
                 f"\n## The one claim you may build on\n"
                 f"{claim['claim']}"
                 + (f"\n(evidence: {claim['evidence']})" if claim.get("evidence") else "")
                 + f"\n(this is true of: {claim.get('scope') or 'the brand'})"]

        ents = bundle.get("entities") or []
        if ents:
            parts.append("\n## What is being advertised")
            for e in ents[:3]:
                parts.append(f"- {e.get('name', '')}: {e.get('description', '')}"
                             [:300])
        aud = bundle.get("audiences") or []
        if aud:
            parts.append("\n## Who is reading")
            for a in aud[:2]:
                parts.append(f"- {a.get('name') or a.get('key', '')}: "
                             f"{a.get('pains') or a.get('description') or ''}"[:300])
        if angle == "objection" and objections:
            parts.append("\n## The hesitation to answer")
            parts.append(f"- {objections[0]['objection']}")
        parts.append(f"\n## Angle\n{_ANGLE_BRIEF.get(angle, '')}")

        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model=config.CLAUDE_MODEL, max_tokens=400,
            system=_AD_SYSTEM,
            messages=[{"role": "user", "content": "\n".join(parts)}])
        try:
            from . import usage
            # The bundle carries its own account (`resolve` puts it there),
            # so this needs no extra parameter threaded through the pack.
            usage.log_usage("ad_copy_draft", config.CLAUDE_MODEL, msg,
                            tenant=str(bundle.get("tenant") or ""))
        except Exception:                                        # noqa: BLE001
            pass
        return msg.content[0].text.strip(), ""
    except Exception as exc:                                     # noqa: BLE001
        # Classified, not truncated — see app/model_error.py. `ad_copy`
        # degrades to a composer when the model is unavailable, and a spend
        # limit reported as "BadRequestError" makes that look like a code
        # fault rather than an account one.
        from . import model_error
        return "", model_error.explain(exc)


# Replaceable so the offline suite can drive both halves — including a model
# that returns a banned phrase, which must still be blocked by the validator.
draft_ad = _draft_ad_live


def _run_ad_copy(ctx: Context) -> dict:
    entity_key = str(ctx.params.get("entity_key") or "")
    audience_key = str(ctx.params.get("audience_key") or "")
    want = max(1, min(5, int(ctx.params.get("variants") or 3)))

    if not ctx.claims:
        ctx.note("no approved claim is in scope, so there is nothing to "
                 "advertise from — this is the authoring backlog, not a bug")
        return {"summary": "no proof in scope"}

    # The image half of this skill does not exist yet and is not faked. Steps
    # 05 and 06 of the build map (themes, media references) are what supply a
    # picture and the rule for choosing one; until then this produces copy and
    # says so, rather than emitting a creative that silently has no art
    # direction attached.
    ctx.note("copy only — no imagery. Theme and media selection need the "
             "visual identity and media layers (build map steps 05 and 06); "
             "until those land, art direction is a human's job.")

    objections = ctx.bundle.get("objections") or []
    by_basis: dict[str, int] = {}
    degraded_note = ""

    for i, claim in enumerate(ctx.claims[:want]):
        angle = _ANGLES[i % len(_ANGLES)]

        text, why_not = draft_ad(ctx.bundle, claim, angle, objections)
        if text:
            basis = "model"
        else:
            # Degrade, and SAY SO on the row. A silent fallback is the defect
            # this codebase already met in the extractor: a path measured at
            # zero recall looked exactly like a working one, and only the
            # `extractor` field told the truth. `basis` is that field here.
            text = _compose_ad(claim, angle, objections, entity_key)
            basis = f"composed ({why_not})"
            degraded_note = why_not

        by_basis[basis.split(" (")[0]] = by_basis.get(basis.split(" (")[0], 0) + 1

        def _repair(previous: str, failures: list, _c=claim, _a=angle) -> str:
            """Hand the draft its own failures and ask again.

            Only the model can repair — the composer is deterministic and would
            return the identical string, which `emit` reads as "nothing more to
            give" and stops on. That is the right behaviour, not a limitation:
            with no API key there is nothing to reason about the failure with.
            """
            note = "\n".join(f"- {f['detail']} → {f['fix']}" for f in failures)
            fixed, _ = draft_ad(
                {**ctx.bundle,
                 "rules": {**ctx.bundle.get("rules", {}),
                           "block": ctx.bundle.get("rules", {}).get("block", "")
                           + f"\n\n## Your previous attempt was rejected\n"
                             f"{previous}\n\n## Why, and what to change\n{note}\n"
                             f"Rewrite it so none of these apply. Do not argue "
                             f"with the rules and do not drop the claim."}},
                _c, _a, objections)
            return fixed

        ctx.emit(text, claim_ids=[claim["claim_id"]], entity_key=entity_key,
                 audience_key=audience_key, angle=angle, fmt="ad_copy",
                 redraft=_repair if basis == "model" else None,
                 meta={"needs_art_direction": True, "basis": basis})

    if degraded_note:
        ctx.note(f"the model did not write these — {degraded_note}. What is "
                 f"filed is a grounded placeholder, not ad copy: every variant "
                 f"carries basis='composed'.")

    return {"summary": f"{len(ctx.items)} variant(s) ({', '.join(
                f'{n} {b}' for b, n in sorted(by_basis.items()))}), no imagery",
            "by_basis": by_basis, "angles": list(_ANGLES[:len(ctx.items)])}


register(Skill(
    key="ad_copy",
    name="Ad copy",
    does="Draft ad copy variants from approved claims for one entity and "
         "audience. Copy only — imagery waits on the media layer, and each "
         "variant is flagged as needing art direction.",
    system_key="ad_creative",
    tier=3,
    needs=("rules.banned_claims",),
    params=("entity_key", "audience_key", "variants", "utterance"),
    writes=False,
    produces="draft",
    run=_run_ad_copy))


# ---------------------------------------------------------------------------
# 5 · Campaign email — the data layer writes the copy, code renders and gates it
#
# The owner's requirement, in one line: the COPY comes from the data layer, so
# every email stays on-brand (voice), credible (approved claims), and correctly
# positioned — never the model freelancing. Same split as `ad_copy`: the model
# writes FROM the bundle, and code decides what it may write from and whether the
# result ships. What is new here is the whole email — subject, body, branded
# render, ESP-native personalization — assembled around that grounded copy and
# put through `emit` so the banned-claims gate runs before anything is drafted
# into a client's ESP.
# ---------------------------------------------------------------------------

_CAMPAIGN_SYSTEM = """You are writing ONE marketing email for this brand, to a
specific audience segment, to drive ONE action.

Everything you may assert is in the context: the brand's positioning and voice,
the APPROVED CLAIMS (your only credibility — cite the ones you use by id), the
products, and the segment you are writing to. Do NOT introduce a claim, price,
material, origin, guarantee or statistic that is not in the context — the hard
rules are enforced in code after you write, so a draft that breaks one is thrown
away, not softened, and you will have wasted the slot.

EMAIL CRAFT — these are enforced or measured, not suggestions:
- Subject: UNDER 45 characters (mobile inboxes cut around 40). One specific
  benefit or curiosity, sentence case, no clickbait, no ALL CAPS, at most one
  emoji and usually none. Code trims anything longer.
- Preheader: under 80 characters, COMPLETES the subject — never repeats it.
- Headline: one short line (under 50 chars) a reader gets in a glance.
- Body: 2–3 SECTIONS, each ONE idea. A section is one or two short
  paragraphs, one or two sentences each. Optional 2–5 word heading per
  section. Nobody reads a wall — write for the scan, let the sections and
  product cards breathe.
- Products: feature 1–3 FROM THE OFFERED LIST when they serve this segment,
  by key — the cards rendered are exactly the ones you pick, so your prose
  and the cards must agree. Never name a product that is not on the list.
- ONE call to action. No second ask, no invented offer.
Match the house voice throughout.

YOU DESIGN THE EMAIL, not just the words. Compose 5–10 blocks from this
vocabulary, in the order the message wants — vary the structure to fit THIS
message, never repeat one fixed skeleton:
  {"type":"heading","text":"...","level":1}   the one big headline (level 1
                                              once); omit level for a small
                                              section kicker
  {"type":"text","html":"one or two short <p> paragraphs; may use
                         {{FIRST_NAME}}; no <html>/<head>/<style>, no images"}
  {"type":"quote","text":"an approved claim given room","claim_id":"REQUIRED
                          — an offered claim id"}
                                              do NOT write an attribution —
                                              who said it is copied from the
                                              claim's own source by code
  {"type":"stat","value":"90 days","caption":"what the number means",
   "claim_id":"REQUIRED — numbers come only from offered claims"}
  {"type":"list","items":["3–5 short scannable points"]}
  {"type":"banner","text":"one short emphasis line on the brand colour"}
  {"type":"products","keys":["1–3 offered product keys"]}
  {"type":"hero"}                             where the hero image sits —
                                              placement only; code supplies
                                              the approved photograph
  {"type":"cta","label":"...","url":""}       exactly once
  {"type":"signature","text":"the sign-off line","name":"REQUIRED — a real
                      person on file","role":"optional"}
  {"type":"ps","html":"the postscript — the most-read line after the subject;
                       one link, the same destination as the CTA"}
  {"type":"divider"}
A launch might open on a banner; an education piece might run
heading→text→stat→list; a winback might lead with the quote. Choose what
serves the message — code drops any block that breaks a rule (an uncited
stat, an unoffered product) and says so, rather than softening it.

HOW TO OPEN. The subject earns the open and the first line earns the read, so
spend them: no "Hi {{FIRST_NAME}}, we hope you're well", no announcing what
the email is about. Start in the middle of something — a moment, a number, a
question the reader already has. Subject lines run 3–8 words and say something
specific; the preheader EXTENDS the subject, it never repeats it.

ONE EMAIL, ONE SUBJECT. Write about the products offered to you and nothing
else. Do not introduce another product line, another mechanism, or another
audience's positioning part-way through — a reader who came for one thing and
is handed a second stops believing both. If a claim in front of you belongs to
a different product than the one this email is about, leave it out.

NEVER WRITE A URL. Use "" for every link and every cta_url. You are not given
the site's addresses and cannot know them; code fills each one in with a page
that exists. A plausible-looking path is a broken link.

BE SPECIFIC OR SAY NOTHING. "Premium quality", "elevate your space",
"unmatched craftsmanship" are worth nothing — they are what every brand
writes. A number, a timeframe, a material, a name, a real detail: that is what
a reader believes. If you cannot be specific about something, leave it out.

Return JSON only, nothing else:
{"subject": "...", "preheader": "...",
 "blocks": [ ...the email, in order, from the vocabulary above... ],
 "claim_ids": ["id of each approved claim you used anywhere"],
 "cta_label": "fallback CTA if you somehow omit the cta block", "cta_url": ""}"""


#: Inbox display cuts a subject around 40 characters on mobile; 45 is the
#: writing target the prompt asks for, 60 the hard line code enforces — a
#: drafter that ignores the brief gets trimmed at a word boundary and the
#: run says so. The PLAN's subject is the owner's line and is never touched.
SUBJECT_TARGET, SUBJECT_HARD = 45, 60
PREHEADER_HARD = 90

#: A composed layout (5–10 blocks, each with its own strings) is several times
#: the size of the old single-blob draft. 900 was the ceiling while the drafter
#: returned two paragraphs; at that size a block layout comes back cut in half
#: and unparseable, which reads downstream as "the model failed" and serves the
#: composer's fixed skeleton — the sameness this whole path exists to end.
CAMPAIGN_MAX_TOKENS = 2400

#: WHAT A SEND IS FOR. The owner's complaint (2026-08-21) was "this is all
#: templates … we want variety and true generation of content and different
#: sections", and the honest reading is that variety is not a prompt adjective:
#: a story email, a teaching email, a proof email and an offer email are
#: DIFFERENT EMAILS, not one email reshuffled. So intent is a field on the
#: plan, the planner rotates it, and it changes the brief, the shape and the
#: length budget. The ratio the rotation holds is Hormozi's give:ask (~3.5:1 in
#: $100M Leads): three sends that give for every one that asks.
CAMPAIGN_INTENTS: dict[str, dict] = {
    "story": {
        "label": "Story",
        "asks": False,
        "brief": "Tell ONE true, specific story — an origin, a customer, a "
                 "decision, a moment in the workshop. Earn the read before "
                 "you earn the click. Open in the middle of the scene, never "
                 "with a greeting or a summary of what you are about to say.",
        "shape": "Lead with text, not a hero. A pull-quote or a single image "
                 "can land mid-story. Products come late and small, if at all.",
        "words": (180, 320)},
    "education": {
        "label": "Education",
        "asks": False,
        "brief": "Teach one thing the reader can use today, whether or not "
                 "they ever buy — how to choose, how to care for it, what the "
                 "difference actually is. The payoff must be usable standing "
                 "in a kitchen, not a brochure paragraph.",
        "shape": "A checklist or numbered points is the natural spine here; "
                 "heading → text → list → a short close reads better than "
                 "prose alone.",
        "words": (150, 280)},
    "proof": {
        "label": "Proof",
        "asks": False,
        "brief": "Let the evidence carry it: what people actually said, what "
                 "the numbers actually are. Your own adjectives are worth "
                 "nothing here — every strong statement must trace to an "
                 "approved claim.",
        "shape": "Quote and stat blocks are the point of this send; build "
                 "around them rather than burying them in paragraphs.",
        "words": (120, 240)},
    "offer": {
        "label": "Offer",
        "asks": True,
        "brief": "Make the offer plainly and early — what it is, who it is "
                 "for, what it costs, what happens next. No throat-clearing. "
                 "If there is a real deadline or a real stock limit, say the "
                 "actual number; if there is not, do not manufacture one.",
        "shape": "Offer first, proof second, deadline third, one CTA. A "
                 "banner can carry the offer line; product cards belong here.",
        "words": (90, 200)},
}

#: HOW IT LOOKS, chosen from how warm the segment is — the one genuine fork in
#: the research. Halbert's A-pile (a personal-looking letter survives the sort
#: a commercial-looking mailer does not) and Ben Settle's plain-text school
#: pull one way; e-commerce's designed templates pull the other. Chase Dimond
#: resolves it by AUDIENCE rather than by taste: people who know you and are
#: engaged do better on a letter that reads like a person wrote it; colder or
#: visually-driven audiences need the designed frame to remember who you are.
#: So the engine picks per segment, and neither pole is a house style.
CAMPAIGN_FORMATS: dict[str, dict] = {
    "letter": {
        "label": "Personal letter",
        "brief": "Write it as a letter from one person to one person. Short "
                 "paragraphs, plain words, a signature at the end, and a P.S. "
                 "that carries the one link — the P.S. is the most-read line "
                 "you have. ONE photograph at most and no banner: the point "
                 "is that it reads as written, not designed. When the letter "
                 "is about a specific product, SHOW that product — a reader "
                 "asked to buy something they cannot see is being asked to "
                 "take it on trust.",
        # `hero` and `products` are here on purpose, and were not at first.
        # A letter with no imagery at all was the strict reading of the
        # plain-text school, and it shipped a supplement LAUNCH — to repeat
        # buyers, about a product they had never seen — containing nothing but
        # the logo (owner, 2026-08-22). One photograph does not stop a letter
        # being a letter. The grid is what does, so `_assemble_blocks` caps a
        # letter at a single product card.
        "blocks": ("hero", "heading", "text", "quote", "list", "products",
                   "cta", "divider", "signature", "ps")},
    "designed": {
        "label": "Designed",
        "brief": "Use the full designed frame — the photograph up top, the "
                 "product cards, a banner when one line deserves emphasis. "
                 "Keep live text under every image: a reader with images off "
                 "must still get the message.",
        "blocks": ("hero", "heading", "text", "quote", "stat", "list",
                   "banner", "products", "cta", "divider", "ps")},
}


def _trim_words(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit + 1]
    return (cut[:cut.rfind(" ")] if " " in cut else cut[:limit]).rstrip(" ,;:—-")


def _shape_campaign_copy(copy: dict, note) -> dict:
    """Deterministic email craft — a prompt mostly obeys, code always holds.

    The owner's first live drafts came back with long subjects and one
    unbroken wall of paragraphs (2026-08-21). The prompt now asks for
    sections and short lines; THIS is what happens when a drafter ignores
    it: the subject is trimmed at a word boundary past the hard line (the
    plan's own subject is never touched — it is applied after this), and a
    single body blob is split into sections of at most two paragraphs so
    the rendered email breathes whatever came back. Nothing is reworded.
    """
    subject = str(copy.get("subject") or "").strip()
    if len(subject) > SUBJECT_HARD:
        copy["subject"] = _trim_words(subject, SUBJECT_TARGET)
        note(f"subject trimmed from {len(subject)} to "
             f"{len(copy['subject'])} chars — inbox display cuts around 40")
    pre = str(copy.get("preheader") or "").strip()
    if len(pre) > PREHEADER_HARD:
        copy["preheader"] = _trim_words(pre, PREHEADER_HARD)

    sections = [s for s in (copy.get("sections") or [])
                if isinstance(s, dict) and (s.get("body_html") or "").strip()]
    if not sections:
        blob = str(copy.get("body_html") or "")
        paras = [p for p in re.split(r"(?i)</p>\s*", blob) if p.strip()]
        paras = [p if p.rstrip().lower().endswith("</p>") else p + "</p>"
                 for p in paras]
        sections = [{"heading": "", "body_html": "".join(paras[i:i + 2])}
                    for i in range(0, len(paras), 2)]
    copy["sections"] = sections[:4]
    copy["body_html"] = "".join(s.get("body_html", "")
                                for s in copy["sections"])
    return copy


def _segment_brief(tenant: str, segment) -> dict:
    """The target segment and its angle, from the business-model catalog."""
    if isinstance(segment, dict) and segment.get("name"):
        return segment
    from . import segments as seg
    got = seg.for_tenant(tenant)
    if got.get("ok"):
        for s in got["segments"]:
            if s["key"] == segment:
                return s
    return {"key": str(segment or "general"), "name": str(segment or "General list"),
            "angle": "", "definition": ""}


#: How many recent sends the drafter is shown, and how far back the give:ask
#: rotation looks. Four is one full turn of the ratio (three gives, one ask).
CRAFT_HISTORY = 4


def _recent_sends(tenant: str, segment_key: str) -> list[dict]:
    """The last few campaign emails to THIS list — shape, subject, opening.

    Read from the output ledger, which is where "what have we already done"
    has always lived. Only sends that actually cleared the validator count:
    a blocked draft was never seen by anyone, so avoiding its shape would be
    avoiding a ghost.
    """
    from . import db
    out: list[dict] = []
    try:
        with db.SessionLocal() as s:
            rows = (s.query(db.Output)
                    .filter(db.Output.tenant == tenant,
                            db.Output.format == "campaign_email",
                            db.Output.angle == segment_key,
                            db.Output.status.notin_(("blocked", "superseded")))
                    .order_by(db.Output.created_at.desc())
                    .limit(CRAFT_HISTORY).all())
            for r in rows:
                lines = [ln.strip() for ln in (r.body or "").split("\n")
                         if ln.strip()]
                _theme = str(r.theme or "")
                _intent, _, _fmt = _theme.partition("|")
                out.append({"shape": list(r.shape or []),
                            "intent": _intent, "format": _fmt,
                            "subject": lines[0] if lines else "",
                            "opening": next((ln for ln in lines[3:]), "")})
    except Exception:                                            # noqa: BLE001
        # History is an improvement, never a precondition: a brand-new
        # account, or a column an old database has not grown yet, must still
        # be able to send. No history simply means nothing to avoid.
        return []
    return out


def _craft_review(ctx, copy: dict, blocks: list, craft: dict) -> list[dict]:
    """The craft checks, with this send's own facts filled in.

    Two of the checks need to know things only the run knows: whether this
    send ASKS (its intent), whether it carries PROOF (a quote or stat block
    built from an approved claim), and whether any urgency in it has a real
    source. `deadline` is a plan field the owner fills; an empty one means
    there is no deadline, which is a fact, not a gap to paper over.
    """
    from . import email_craft
    intent = str(craft.get("intent") or "")
    deadline = str(ctx.params.get("deadline") or "").strip()
    return email_craft.review(
        subject=copy.get("subject", ""), preheader=copy.get("preheader", ""),
        body=_blocks_text(blocks), intent=intent,
        asks=bool(CAMPAIGN_INTENTS.get(intent, {}).get("asks")),
        has_proof=any(b.get("type") in ("quote", "stat") for b in blocks),
        urgency_backed_by=deadline)


def _campaign_craft(ctx, seg: dict) -> dict:
    """What KIND of email this is, how it should LOOK, and what to avoid.

    Three decisions the drafter should not be making from scratch each time:

    * **intent** — the plan's when the owner set one, otherwise rotated so the
      list is given to roughly three times for every time it is asked (the
      give:ask ratio Hormozi puts at ~3.5:1). Counting the last few sends is
      what makes the ratio real rather than a sentence in a prompt.
    * **format** — from how warm the cohort is, not from taste. See
      `segments.warmth`.
    * **avoid** — the shapes, subjects and openings already used on this list.
    """
    from . import segments as segmod
    hist = _recent_sends(ctx.tenant, seg["key"])

    intent = str(ctx.params.get("intent") or "").strip().lower()
    why = ""
    if intent and intent not in CAMPAIGN_INTENTS:
        ctx.note(f"unknown intent {intent!r} on the plan — the ones that exist "
                 f"are: " + ", ".join(CAMPAIGN_INTENTS))
        intent = ""
    if intent:
        why = "set on the plan"
    else:
        # Rotate. An ask is due only when the last few sends gave enough;
        # otherwise take the give-intent this list has gone longest without,
        # so a segment does not receive three stories in a row either.
        recent = [h.get("intent") for h in hist]
        gives = [k for k, v in CAMPAIGN_INTENTS.items() if not v["asks"]]
        asked_recently = any(
            CAMPAIGN_INTENTS.get(str(i or ""), {}).get("asks") for i in recent[:3])
        if not hist:
            intent, why = "story", "first send to this list — earn the read first"
        elif not asked_recently and len(hist) >= 3:
            intent, why = "offer", "three sends have given; this one may ask"
        else:
            # LEAST RECENTLY USED, not "first one unused". Once every give
            # had appeared in the window, "first unused" found none and fell
            # back to gives[0] — so a list that had seen all three got story,
            # story, story for ever. Ordering by how long ago each was last
            # sent keeps the rotation turning however long the history is.
            used = [i for i in recent if i in gives]
            intent = min(gives, key=lambda g: (-(used.index(g) if g in used
                                                 else len(used) + 1)))
            why = "rotating so this list gets a different kind of email"

    # FORMAT VARIES, warmth only BIASES it. Fixed per segment, a warm list got
    # a letter every single time and a cold list a designed frame every single
    # time — the intent axis rotated underneath and the email still arrived
    # looking identical (owner, 2026-08-22). So warmth sets the default and the
    # history breaks the pattern: after two sends in the same form, the next
    # one switches. An offer intent also leans designed whatever the warmth,
    # because an offer wants the product shown.
    warmth = segmod.warmth(seg["key"])
    fmt = "letter" if warmth == "warm" else "designed"
    recent_fmt = [h.get("format") for h in hist if h.get("format")]
    if len(recent_fmt) >= 2 and recent_fmt[0] == recent_fmt[1] == fmt:
        fmt = "designed" if fmt == "letter" else "letter"
        why = (why + "; " if why else "") + "switching form after two the same"
    elif CAMPAIGN_INTENTS.get(intent, {}).get("asks") and fmt == "letter":
        fmt = "designed"
        why = (why + "; " if why else "") + "an offer shows the product"
    return {"intent": intent, "format": fmt, "warmth": warmth, "why": why,
            "deadline": str(ctx.params.get("deadline") or "").strip(),
            "avoid": [h for h in hist if h.get("shape") or h.get("subject")]}


def _craft_brief(craft: dict) -> str:
    """The per-send half of the prompt: what this email is FOR, how it should
    look, and what the last few sends already did.

    The anti-repetition half is the part that makes "vary the structure" more
    than a hope. Told once per call, a model will happily produce the same
    shape twice; shown the shapes and opening lines it already used, it has
    something concrete to move away from. Same discipline as the claims
    anti-repeat, applied to form instead of content.
    """
    intent = CAMPAIGN_INTENTS.get(str(craft.get("intent") or ""), {})
    fmt = CAMPAIGN_FORMATS.get(str(craft.get("format") or ""), {})
    out: list[str] = []
    if intent:
        lo, hi = intent["words"]
        out += [f"\n## WHAT THIS SEND IS FOR: {intent['label']}",
                intent["brief"], intent["shape"],
                f"Length: about {lo}–{hi} words of body copy.",
                ("This send MAKES THE ASK." if intent["asks"] else
                 "This send GIVES — it does not push the sale. One soft "
                 "invitation at the end is the whole ask.")]
    if fmt:
        out += [f"\n## HOW IT LOOKS: {fmt['label']}", fmt["brief"],
                "Blocks available to you for this send: "
                + ", ".join(fmt["blocks"]) + " (use no others)."]
    if craft.get("deadline"):
        out += ["\n## THE REAL DEADLINE (state it exactly, never soften or "
                "inflate it)", str(craft["deadline"])]
    else:
        out.append("\n## NO DEADLINE EXISTS for this send. Do not imply one — "
                   "no 'last chance', no 'ends tonight', no 'while supplies "
                   "last'. Urgency nobody can point at is a lie, and code "
                   "will stop the send over it.")
    prev = craft.get("avoid") or []
    if prev:
        out.append("\n## DO NOT REPEAT THE LAST SENDS")
        for p in prev[:3]:
            bits = []
            if p.get("shape"):
                bits.append("shape " + " → ".join(p["shape"]))
            if p.get("subject"):
                bits.append(f"subject {p['subject']!r}")
            if p.get("opening"):
                bits.append(f"opened {p['opening'][:60]!r}")
            if bits:
                out.append("- " + "; ".join(bits))
        out.append("Use a different structure and a different opening move "
                   "from every one of those. Not a reworded version of the "
                   "same email — a different email.")
    return "\n".join(out)


def _draft_campaign_live(bundle: dict, seg: dict, goal: str,
                         craft: dict | None = None) -> tuple:
    """One model call for one email. Returns `(data|None, basis, why_not)`.

    `data` is the JSON the model returned (subject/preheader/blocks/claim_ids).
    Degrades to the composer when the model is unavailable, and says why on the
    row — the `basis` field, exactly as `ad_copy` does.

    `craft` carries the per-send direction that makes two campaigns different
    emails rather than one email twice: the `intent` (what this send is FOR),
    the `format` (letter or designed, chosen from segment warmth), and
    `avoid` — the shapes and lines the last few sends already used.
    """
    from . import config, llm
    if not config.ANTHROPIC_API_KEY:
        return None, "composed", "ANTHROPIC_API_KEY is not set"
    try:
        import json as _json
        parts = [bundle.get("rules", {}).get("block", "").strip()]
        claims = bundle.get("claims") or []
        if claims:
            parts.append("\n## APPROVED CLAIMS — your only credibility, cite by id:")
            for c in claims[:6]:
                # The usage rule rides WITH the claim. What a claim permits
                # depends on where it came from — a testimonial is quoted
                # verbatim with attribution, a spec is stated exactly, data
                # may be restated but the figure may not change — and a
                # drafter that is not told cannot comply. Code checks this
                # after the fact; saying it here is how it rarely has to.
                parts.append(f"- [{c['claim_id']}] {c['claim']}"
                             + (f" (evidence: {c['evidence']})" if c.get("evidence") else "")
                             # BACKGROUND, said out loud. A credential true of
                             # the company is not proof about the product this
                             # email is about, and a list that does not say so
                             # invites a drafter to spend all of them.
                             + ("\n    BACKGROUND — true of the brand, not of "
                                "this product. Use AT MOST ONE, once, and only "
                                "if it earns its place."
                                if c.get("background") else "")
                             + (f"\n    USE: {c['usage_rule']}" if c.get("usage_rule") else ""))
        ents = bundle.get("entities") or []
        if ents:
            parts.append("\n## Products you may feature (cite by key — the "
                         "cards rendered under your copy will be exactly the "
                         "ones you pick):")
            for e in ents[:6]:
                parts.append(f"- [{e.get('key', '')}] {e.get('name', '')}: "
                             f"{e.get('description', '')}"[:220])
        objs = bundle.get("objections") or []
        if objs:
            parts.append("\n## Hesitations you may answer:")
            for o in objs[:2]:
                parts.append(f"- {o.get('objection', '')}")
        parts.append(f"\n## Segment you are writing to:\n{seg['name']} — "
                     f"{seg.get('definition', '')}")
        parts.append(f"## The action to drive:\n{goal or seg.get('angle', '')}")
        parts.append(_craft_brief(craft or {}))

        # Through `llm.ask`: one door, so the purpose is logged, the model is
        # chosen by the same map as everything else, and a failure comes back
        # classified. This call used to build its own Anthropic client and log
        # its own usage — the exact per-call drift `llm.py` exists to end.
        reply = llm.ask("campaign_email", "\n".join(parts),
                        tenant=str(bundle.get("tenant") or ""),
                        system=_CAMPAIGN_SYSTEM, max_tokens=CAMPAIGN_MAX_TOKENS)
        if not reply.ok:
            return None, "composed", (reply.error or reply.degraded
                                      or "the model call failed")
        # A composed layout is several times the size of the old sections
        # blob, and a JSON object cut off mid-block does not parse. Truncation
        # must be NAMED: silently composing here would turn "the emails all
        # look the same" back on without anything saying why.
        if reply.stop_reason == "max_tokens":
            return None, "composed", (
                f"the model hit the {CAMPAIGN_MAX_TOKENS}-token ceiling and the "
                f"layout came back incomplete")
        text = reply.text
        s, e = text.find("{"), text.rfind("}")
        data = _json.loads(text[s:e + 1])
        # `blocks` is the current contract; `sections`/`body_html` are the older
        # shapes, still accepted because the composer speaks one of them and a
        # model may fall back to it. Checking only the old two — which is what
        # this line did when the prompt started asking for `blocks` — rejected
        # every well-formed composed layout and quietly served the composer.
        usable = isinstance(data, dict) and bool(
            data.get("blocks") or data.get("sections") or data.get("body_html"))
        return (data if usable else None), "model", (
            "" if usable else "the model returned no usable email body")
    except Exception as exc:                                     # noqa: BLE001
        from . import model_error
        return None, "composed", model_error.explain(exc)


draft_campaign = _draft_campaign_live   # the seam the offline suite replaces


def _compose_campaign(bundle: dict, seg: dict, goal: str) -> dict:
    """The deterministic grounded fallback — dull, honest, provable offline."""
    claims = bundle.get("claims") or []
    top = claims[0] if claims else None
    line = (goal or seg.get("angle") or "A quick note").split(".")[0]
    proof = top["claim"].rstrip(". ") if top else ""
    sections = [{"heading": "", "body_html": "<p>Hi {{FIRST_NAME}},</p>"}]
    if proof:
        sections.append({"heading": "", "body_html": f"<p>{proof}.</p>"})
    return {"subject": _trim_words(line, SUBJECT_TARGET) or seg["name"],
            "preheader": seg.get("definition", "")[:80],
            "headline": _trim_words(line, 50),
            "sections": sections,
            "body_html": "".join(s["body_html"] for s in sections),
            "claim_ids": [top["claim_id"]] if top else [],
            "cta_label": "Shop now", "cta_url": ""}


def _theme_for(tenant: str) -> dict:
    """The render theme: the OWNER-APPROVED derived theme when one exists.

    `brand_theme.live_theme` returns only what the owner reviewed — never the
    deriver's unreviewed proposal — so a customer sees no look nobody signed
    off. Until a theme is approved this falls back to the old minimal shape:
    branded by name on the default palette, with no address. That absent
    address is not hidden: `email_render` shows a loud placeholder and
    `missing_to_send` names it, so the email reads as not-yet-sendable rather
    than quietly shipping without a CAN-SPAM footer.
    """
    from . import brand_theme, kb
    b = kb.brand(tenant)
    name = (b.display_name if b else "") or tenant
    t = brand_theme.live_theme(tenant)
    if t:
        # Identity is brand-KB data; a theme approved without it still renders
        # under the client's name rather than an empty title.
        t.setdefault("name", name)
        foot = dict(t.get("footer") or {})
        foot.setdefault("brand", t["name"])
        t["footer"] = foot
        return t
    return {"name": name,
            "footer": {"brand": name, "address": "", "tagline": "",
                       "disclaimer": ""}}


def _product_items(ents: list) -> list:
    return [{"name": e.get("name", ""), "price": e.get("price", ""),
             "url": e.get("url", ""), "image": e.get("image", "")}
            for e in ents[:3] if e.get("name")]


def _legacy_blocks(copy: dict, ents: list, hero: dict | None) -> list:
    """The fixed skeleton, kept as the fallback shape — the composer and any
    old-shape draft land here: hero, headline, headed sections with
    dividers, product cards, one CTA."""
    blocks: list = []
    if hero and hero.get("url"):
        blocks.append({"type": "hero", "image": hero["url"],
                       "alt": hero.get("alt", "")})
    if (copy.get("headline") or "").strip():
        blocks.append({"type": "heading", "text": copy["headline"].strip(),
                       "level": 1})
    sections = copy.get("sections") or (
        [{"heading": "", "body_html": copy.get("body_html") or ""}])
    for i, sec in enumerate(sections):
        if i:
            blocks.append({"type": "divider"})
        if (sec.get("heading") or "").strip():
            blocks.append({"type": "heading", "text": sec["heading"].strip()})
        blocks.append({"type": "text", "html": sec.get("body_html") or ""})
    items = _product_items(ents)
    if items:
        blocks.append({"type": "divider"})
        blocks.append({"type": "products", "items": items})
    if copy.get("cta_label"):
        blocks.append({"type": "cta", "label": copy["cta_label"],
                       "url": copy.get("cta_url") or "#"})
    return blocks


#: A GENERATION STUTTER: the text ends by repeating its own tail.
#:
#: Four variants shipped live before this was general enough — "matters now.
#: now.", "every day. day.", "productionction", and "read it.d it." Each was
#: chased with its own pattern (whole word, then syllable) and the next one
#: slipped past, because they are not four bugs. They are one: the model
#: finishes a string, then emits some suffix of it a second time.
#:
#: So the rule is stated that way. Take the last N characters; if the N before
#: them are identical, one copy is spurious. Longest N first, so the whole
#: repeat goes rather than a fragment of it.
#:
#: Five characters minimum, and only at the very END of the string. Shorter
#: windows match real writing ("bye bye", "couscous", "beriberi"), and a
#: repeat mid-sentence is usually deliberate. Both bounds were set by testing
#: against the four real cases and a list of things that must survive.
STUTTER_MIN, STUTTER_MAX = 5, 14


def _undouble(s: str) -> str:
    t = str(s or "")
    tail = ""
    while t and t[-1] in " \t\n":
        tail, t = t[-1] + tail, t[:-1]
    # Trailing close-tags are markup, not text; the repeat sits before them.
    m = re.search(r"((?:</[^>]+>\s*)+)$", t)
    close = m.group(1) if m else ""
    if close:
        t = t[:-len(close)]
    for n in range(STUTTER_MAX, STUTTER_MIN - 1, -1):
        if len(t) >= 2 * n and t[-n:] == t[-2 * n:-n]:
            return t[:-n] + close + tail
    return s


def _fill_dead_links(blocks: list, url: str) -> int:
    """Point every empty link at the email's one destination. Returns how many.

    A drafter writes `<a href="">the product page</a>` because it does not know
    the URL — it cannot, the link is a fact about the store and the drafter is
    given no facts. Treating that as a fault and BLOCKING the send was the
    wrong reading and stopped emails that were otherwise fine (owner,
    2026-08-22: "it was working before"). The prose is the drafter's; the
    destination is ours; so we supply it, exactly as the CTA button, the hero
    image and the signature are supplied.
    """
    if not url or url == "#":
        return 0
    filled = 0
    for b in blocks or []:
        for f in ("html", "text"):
            if not b.get(f):
                continue
            new, n = re.subn(r'href\s*=\s*"\s*#?\s*"', f'href="{url}"',
                             str(b[f]))
            if n:
                b[f], filled = new, filled + n
    return filled


def _undouble_blocks(blocks: list) -> list:
    for b in blocks or []:
        for f in ("text", "html", "caption", "attribution"):
            if b.get(f):
                b[f] = _undouble(b[f])
        # Checklist lines are copy too, and were being skipped — the live
        # garbled word ("productionction") was in one.
        if isinstance(b.get("items"), list):
            b["items"] = [_undouble(i) if isinstance(i, str) else i
                          for i in b["items"]]
    return blocks


def _norm_quote(s: str) -> str:
    """A quote reduced to what it actually SAYS, for comparison — case,
    spacing, surrounding quotation marks and a trailing stop are formatting,
    not wording."""
    t = re.sub(r"\s+", " ", str(s or "")).strip()
    t = t.strip("“”‘’\"' ").rstrip(". ")
    return t.casefold()


def _proof_misuse(kind: str, b: dict, claim: dict) -> str:
    """Why this proof block may not stand, or "" if it may.

    Citing a real claim id is necessary and NOT sufficient, which is the hole
    this closes. Two ways a block can cite honestly and still lie:

      · A TESTIMONIAL reworded. `kb.PROOF_USAGE` has said from the beginning
        that a customer's words are quoted verbatim with attribution and never
        paraphrased — "the colours are better in person" said BY the brand is
        an unevidenced claim; said as a named customer's quote it is a fact
        about what someone said, and the words ARE the evidence. A quote block
        carrying a testimonial's id and different words invents a sentence for
        a real person, which is the worst thing in this system's reach.
      · A NUMBER that is not in the claim. A stat block reading "93%" against
        a claim that never says 93 is an invented figure wearing a real
        citation — worse than an uncited one, because it looks traceable.
    """
    ptype = str(claim.get("proof_type") or "").lower()
    if kind == "quote":
        if ptype in kb_mod.VERBATIM_ONLY:
            said, quoted = _norm_quote(claim.get("claim")), _norm_quote(b.get("text"))
            if not quoted or quoted != said:
                return (f"it is a {ptype}, which must be quoted verbatim "
                        f"({claim.get('usage_rule', '')}) and the words were "
                        f"changed")
            if not str(claim.get("attributed_to") or "").strip():
                # Checked on the RECORD, not on the block: the drafter no
                # longer supplies an attribution at all (it is copied from the
                # claim), so the question is whether the KB knows who said it.
                # A customer quote nobody can be credited for is just an
                # unevidenced sentence in quotation marks.
                return (f"it is a {ptype} and nobody is on file to credit — "
                        f"set who said it on the claim, or do not quote it")
        return ""
    # stat: every number in the value must appear in the claim's own evidence.
    nums = re.findall(r"\d[\d,.]*", str(b.get("value") or ""))
    if not nums:
        return "a stat block with no figure in it is a heading, not proof"
    source = f"{claim.get('evidence', '')} {claim.get('claim', '')}".replace(",", "")
    missing = [n for n in nums if n.replace(",", "") not in source]
    if missing:
        return ("the figure " + ", ".join(missing[:2]) + " is not in the "
                "claim it cites — a number the evidence does not contain is "
                "an invented one")
    return ""


def _assemble_blocks(copy: dict, ents: list, hero: dict | None,
                     offered_claims: dict, note, fmt: str = "",
                     signatory: dict | None = None,
                     default_cta_url: str = "",
                     known_urls: set | None = None) -> tuple[list, list]:
    """The drafter's OWN layout, held to the rules — or the legacy skeleton.

    "This is all templates" (owner, 2026-08-21): the fix is that the model
    composes the email's structure from the renderer's vocabulary, and THIS
    function is why that stays safe — it validates every block against the
    same lines code always held, drops what breaks one BY NAME, and never
    rewords anything:

      · images only from governed sources — a `hero` block is placement
        only, filled from the approved library, dropped (named) when no
        approved photograph exists; the model cannot supply a URL;
      · products only from the offered keys;
      · a `stat` or `quote` must cite an OFFERED claim id — an uncited
        number is an invented number;
      · exactly one CTA — the first stands, extras are dropped;
      · a block the chosen FORMAT does not carry is dropped — a personal
        letter with a product grid in it is not a personal letter;
      · unknown block types are dropped, not guessed.

    Returns (blocks, extra_cited_claim_ids).
    """
    raw = copy.get("blocks")
    if not isinstance(raw, list) or not raw:
        return _legacy_blocks(copy, ents, hero), []

    allowed = set(CAMPAIGN_FORMATS.get(str(fmt or ""), {}).get("blocks") or ())
    by_key = {e["key"]: e for e in ents if e.get("key")}
    out: list = []
    extra_cited: list[str] = []
    seen_cta = seen_hero = False
    for b in raw[:12]:
        if not isinstance(b, dict):
            continue
        kind = str(b.get("type") or "").strip()
        if allowed and kind and kind not in allowed:
            note(f"layout: a {kind} block was dropped — this send is a "
                 f"{CAMPAIGN_FORMATS[fmt]['label'].lower()} and does not "
                 f"carry one")
            continue
        if kind == "hero":
            if seen_hero:
                continue
            seen_hero = True
            if hero and hero.get("url"):
                out.append({"type": "hero", "image": hero["url"],
                            "alt": hero.get("alt", "")})
            else:
                note("layout: the hero block was dropped — no approved "
                     "photograph is available for it")
        elif kind == "products":
            picked = [by_key[k] for k in (b.get("keys") or [])
                      if isinstance(k, str) and k in by_key]
            ghosts = [k for k in (b.get("keys") or [])
                      if isinstance(k, str) and k not in by_key]
            if ghosts:
                note("layout: product key(s) not on the offered list were "
                     "dropped: " + ", ".join(ghosts[:4]))
            # A letter shows ONE thing. More than that is a catalogue page
            # with a signature at the bottom, which is not the format.
            items = _product_items(picked)[:1 if fmt == "letter" else 3]
            if items:
                out.append({"type": "products", "items": items})
        elif kind in ("quote", "stat"):
            cid = str(b.get("claim_id") or "").strip()
            if cid not in offered_claims:
                note(f"layout: a {kind} block was dropped — it cited no "
                     f"offered claim, and an uncited "
                     + ("number" if kind == "stat" else "quote")
                     + " is an invented one")
                continue
            claim = offered_claims.get(cid) or {}
            why = _proof_misuse(kind, b, claim)
            if why:
                note(f"layout: a {kind} block was dropped — {why}")
                continue
            extra_cited.append(cid)
            if kind == "stat":
                out.append({"type": "stat", "value": b.get("value", ""),
                            "caption": b.get("caption", "")})
            else:
                # ATTRIBUTION IS COPIED, NEVER WRITTEN. It says where a
                # statement came from, which is a claim about the world, so it
                # comes off the claim record and the drafter's is discarded.
                # Asked for one, a model supplies something plausible — a live
                # email credited a line to "Eien Health Research", an
                # organisation that does not exist. A claim with no source on
                # file renders unattributed, which is the truth.
                out.append({"type": "quote", "text": b.get("text", ""),
                            "attribution": str(claim.get("attributed_to") or "")})
        elif kind == "cta":
            if seen_cta:
                note("layout: a second CTA was dropped — one ask per email")
                continue
            seen_cta = True
            # A literal "#" is the drafter saying "I do not know the URL",
            # exactly as an empty string does — it must not outrank the real
            # destination code can supply.
            _u = str(b.get("url") or "").strip()
            if _u == "#":
                _u = ""
            _cu = str(copy.get("cta_url") or "").strip()
            _want = _u or (_cu if _cu != "#" else "")
            # A destination the drafter wrote is honoured only if it is a page
            # that actually exists; otherwise the looked-up one stands. This is
            # the same rule as names and figures — the words are the drafter's,
            # the fact is ours.
            if _want and known_urls is not None:
                if _want.split("?")[0].rstrip("/") not in known_urls:
                    note(f"the CTA pointed at {_want}, which is not a page on "
                         f"this site — using {default_cta_url}")
                    _want = ""
            out.append({"type": "cta", "label": b.get("label") or
                        copy.get("cta_label") or "Shop now",
                        "url": _want or default_cta_url or "#"})
        elif kind == "signature":
            # The name is BRAND data and the drafter's is IGNORED. This block
            # once accepted any non-empty name, which a model duly filled with
            # "Maya Chen, Head of Product" — a person who does not exist,
            # signing a live customer email (2026-08-22). A name is a claim
            # about a human being; it comes from the record or the letter goes
            # unsigned. Same rule as the hero: the model chooses PLACEMENT,
            # code supplies the governed content.
            who = str((signatory or {}).get("name") or "").strip()
            if not who:
                note("layout: the sign-off was dropped — no sender name is on "
                     "file to sign it (set it on the Brand tab), and "
                     "inventing a person is not an option")
                continue
            out.append({"type": "signature", "text": b.get("text", ""),
                        "name": who,
                        "role": str((signatory or {}).get("role") or "")})
        elif kind in ("heading", "text", "list", "banner", "divider", "ps"):
            out.append(b)
        else:
            note(f"layout: unknown block type {kind!r} dropped")

    if not seen_cta and copy.get("cta_label"):
        out.append({"type": "cta", "label": copy["cta_label"],
                    "url": copy.get("cta_url") or default_cta_url or "#"})
    if not seen_hero and hero and hero.get("url") and (
            not allowed or "hero" in allowed):
        # Media presence outranks the omission: an approved, relevant
        # photograph exists, so it leads. The drafter still owns everything
        # below it. A letter-format send is the exception — it has no hero by
        # definition, and forcing one in would undo the format.
        out.insert(0, {"type": "hero", "image": hero["url"],
                       "alt": hero.get("alt", "")})
        note("layout: the drafter omitted the hero; the approved photograph "
             "was placed on top")
    # The P.S. belongs at the end, under everything — it is a postscript, and
    # a drafter that put it mid-email meant it as one.
    tail = [b for b in out if b.get("type") == "ps"]
    if tail:
        out = [b for b in out if b.get("type") != "ps"] + tail[:1]
    return out, extra_cited


def _blocks_text(blocks: list) -> str:
    """Every human-readable string in the layout, for the validator — a
    banned phrase in a banner or a quote is as banned as one in a
    paragraph."""
    parts: list[str] = []
    for b in blocks or []:
        for f in ("text", "value", "caption", "attribution", "label"):
            if b.get(f):
                parts.append(str(b[f]))
        if b.get("html"):
            parts.append(_strip(b["html"]))
        for item in (b.get("items") or []):
            if isinstance(item, str):
                parts.append(item)
    return "\n".join(parts)


#: How many BRAND-WIDE claims are put in front of the drafter. Two, so there is
#: a choice; `coherence.BACKGROUND_BUDGET` holds the finished email to one.
BACKGROUND_OFFERED = 2


def _run_campaign_email(ctx: Context) -> dict:
    from . import creative, email_craft, email_render, esp, fitness, links
    seg = _segment_brief(ctx.tenant, ctx.params.get("segment"))
    goal = str(ctx.params.get("goal") or "")

    # Products FIRST, so the drafter writes copy that knows what it is
    # selling: the plan's entity when one was set (resolve matched it into
    # the bundle), otherwise the catalogue's top available items. Every
    # field is read from the store sync — name, price, URL, photograph.
    from . import kb as _kb, tenants as _tn
    _dom = (getattr(_tn.get(ctx.tenant), "domain", "") or "").strip()

    def _prod(e: dict) -> dict:
        attrs = e.get("attributes") or {}
        pkey = e.get("key", "")
        return {"key": pkey, "name": e.get("name", ""),
                "price": e.get("price", ""),
                "description": e.get("description", ""),
                "availability": e.get("availability", ""),
                "image": e.get("image") or attrs.get("image", ""),
                "url": e.get("url") or (f"https://{_dom}/products/{pkey}"
                                        if _dom and pkey else "")}

    # What this business requires of a thing before it may be named at all.
    # An entity that reaches the drafter WILL be written about — the Eien
    # letter proved that a product needs no card and no parameter to be
    # recommended, only a mention — so the screen happens before the offer.
    _model = str(getattr(_tn.get(ctx.tenant), "business_model", "") or "")
    plan_scoped = bool(ctx.bundle.get("entities"))
    ents = [_prod(e) for e in (ctx.bundle.get("entities") or [])
            if e.get("name")]
    if not ents:
        rows = _kb.entities(ctx.tenant, available_only=True)
        rows.sort(key=lambda r: (not (r.attributes or {}).get("image"),
                                 r.name or ""))
        ents = [_prod({"key": r.key, "name": r.name, "price": r.price,
                       "description": r.description or "",
                       "availability": r.availability or "",
                       "attributes": r.attributes or {}}) for r in rows[:6]]
    # Where a CTA goes when the drafter supplies no URL. A featured product's
    # own page first, the storefront second — anything but the `#` that
    # shipped a button reading "Learn about CitroBurn" straight to nowhere.
    # WHERE THIS EMAIL SENDS PEOPLE — looked up, never constructed. A CTA on
    # `/collections/all` shipped to a store whose catalogue is at
    # `/collections/shop`, because the drafter wrote the platform's usual
    # shape and nothing checked it against the actual site.
    _dests = links.destinations(ctx.tenant)
    _known = {d["url"].split("?")[0].rstrip("/") for d in _dests} or None
    _cta_home = links.best_for(
        ctx.tenant,
        [e.get("key", "") for e in (ctx.bundle.get("entities") or [])],
        _dests) or (f"https://{_dom}" if _dom else "")
    # NO PHOTOGRAPHS ANYWHERE? FETCH THEM. The catalogue sync is what puts a
    # product's photo on the entity and in the creative library, and an account
    # whose sync predates that code has products with no imagery — which is a
    # data gap the owner is then asked to close by hand, before every send, for
    # ever. Four imageless sends running were spent asking (owner, 2026-08-22).
    #
    # Narrow on purpose: only when NOTHING has an image, only when commerce is
    # actually wired, and never as a substitute for the real sync — this
    # refreshes what a campaign is about to render and says that it did. The
    # sync is idempotent and duplicate-safe by URL, so the cost of being wrong
    # here is one redundant read.
    if ents and not any(e.get("image") for e in ents):
        from . import catalog_sync as _cs, tenants as _tnm
        if _tnm.capabilities(ctx.tenant).get("commerce"):
            got = _cs.sync_shopify(ctx.tenant)
            if got.get("error"):
                ctx.note("no product photographs on file, and the catalogue "
                         "could not be refreshed: " + str(got["error"])[:120])
            else:
                ctx.note(f"no product photographs were on file, so the "
                         f"catalogue was refreshed first — "
                         f"{got.get('images_filed', 0)} photo(s) filed from "
                         f"{got.get('products_seen', 0)} product(s)")
                rows = _kb.entities(ctx.tenant, available_only=True)
                rows.sort(key=lambda r: (not (r.attributes or {}).get("image"),
                                         r.name or ""))
                refreshed = [_prod({"key": r.key, "name": r.name,
                                    "price": r.price,
                                    "description": r.description or "",
                                    "availability": r.availability or "",
                                    "attributes": r.attributes or {}})
                             for r in rows[:6]]
                if any(e.get("image") for e in refreshed):
                    ents = refreshed
        else:
            ctx.note("no product photographs on file and no store is "
                     "connected, so this email cannot show one")

    ents, _refused = fitness.screen(_model, ents)

    # ONE EMAIL, ONE SUBJECT. Claims arrive scoped: `brand-wide` ones are true
    # of the company, the rest belong to a particular product. With no entity
    # named on the plan they were ALL offered at once, so an email about
    # Omega-3 and a joint formula was handed a claim about GLP-1 metabolism and
    # reasonably worked it in — a different product, a different audience, a
    # different positioning, in the middle of somebody else's story (owner,
    # 2026-08-22). The scope was on every claim and nothing read it.
    _feat = {e.get("key", "") for e in ents if e.get("key")}
    _own = [c for c in ctx.claims if (c.get("scope") or "brand-wide") in _feat]
    # BACKGROUND IS BUDGETED, NOT FREE. Brand-wide claims used to pass this
    # filter unconditionally — the rule below read "brand-wide OR in scope" —
    # so every credential the company owns arrived with the same standing as
    # the subject's own proof, under a heading reading "your only credibility,
    # cite by id". A drafter handed six of those reasonably used them all, and
    # a product email became a company profile: the Four Seasons placement
    # asserted twice and "designed in Milan" asserted twice, in an email about
    # shatterproof glasses (owner, 2026-08-22).
    #
    # Two of them are offered so there is a CHOICE; `coherence.review` holds
    # the artifact to spending one. Marked `background` so the prompt can say
    # what they are for rather than hoping the ordering implies it.
    # BACKGROUND IS RELATIVE TO A SUBJECT. With no product featured — a story,
    # a letter, an account with an empty catalogue — the brand IS what the
    # email is about, and its brand-wide claims are the only proof in
    # existence. Capping them there does not stop stuffing; it starves the
    # email of everything it had. So the budget applies only when there is a
    # product for the credential to be background TO.
    _brandwide = [c for c in ctx.claims
                  if (c.get("scope") or "brand-wide") == "brand-wide"]
    if ents:
        _bg = [{**c, "background": True}
               for c in _brandwide][:BACKGROUND_OFFERED]
    else:
        _bg = _brandwide
    _in_scope = _own + _bg
    _aside = len(ctx.claims) - len(_in_scope)
    if _aside and _in_scope:
        # `ctx.claims` is a READ-ONLY property deriving from `bundle["claims"]`,
        # so assigning to it raised AttributeError and killed the whole run.
        # It never fired before today because the old rule let every brand-wide
        # claim through, which made `_aside` zero on every test account — the
        # "one email, one subject" scoping added 2026-08-22 would have crashed
        # the first campaign that genuinely had a claim to set aside. Writing
        # the bundle is both necessary and sufficient: the property reads it,
        # and so does the drafter.
        ctx.bundle["claims"] = _in_scope
        ctx.note(f"{_aside} claim(s) set aside — one email, one subject "
                 f"({len(_own)} about what this email features, "
                 f"{len(_bg)} brand credential(s) offered as background)")

    for r in _refused:
        ctx.note(f"not offered to the drafter: {r['name']} — {r['why']}")
    if _refused and not ents:
        ctx.note("nothing in the catalogue may be featured right now — the "
                 "email will be written without naming a product")
    ctx.bundle["entities"] = ents

    if not ctx.claims:
        ctx.note("no approved claim is in scope, so this email has no credibility "
                 "from the data layer — it can still be written, but authoring a "
                 "claim or two for this brand is what makes it persuasive.")

    # WHAT KIND of email this is, HOW it should look, and what the last few
    # sends to this list already did. Without these three the drafter is asked
    # for "an email" every time and — reasonably — writes the same one, which
    # is what "this is all templates" actually described.
    craft = _campaign_craft(ctx, seg)
    if craft.get("intent"):
        _label = CAMPAIGN_INTENTS[craft["intent"]]["label"]
        ctx.note(f"this send is {'an' if _label[0] in 'AEIOU' else 'a'} "
                 f"{_label} email in "
                 f"{CAMPAIGN_FORMATS[craft['format']]['label'].lower()} form"
                 + (f" — {craft['why']}" if craft.get("why") else ""))
    if craft.get("avoid"):
        ctx.note(f"varying from the last {len(craft['avoid'])} send(s): "
                 + " / ".join(" → ".join(p.get("shape") or []) or "?"
                              for p in craft["avoid"]))

    copy, basis, why = draft_campaign(ctx.bundle, seg, goal, craft)
    if copy is None:
        if why:
            ctx.note("the model did not draft this one: " + why)
        copy = _compose_campaign(ctx.bundle, seg, goal)
    copy = _shape_campaign_copy(copy, ctx.note)
    # The model may only cite claims that were actually offered — an invented id
    # is worse than none, because it looks traceable. Intersect with the bundle.
    # The whole claim, not just its id: a proof block has to be checked
    # against what the claim actually SAYS (see `_proof_misuse`), and an id
    # alone cannot answer that.
    offered = {c["claim_id"]: c for c in ctx.claims}
    cited = [cid for cid in (copy.get("claim_ids") or []) if cid in offered]

    # When the drafter designed its own layout, product choice lives in its
    # `products` blocks and the full offered list stays available to them.
    # The legacy shapes keep the `featured_keys` intersection: the drafter
    # names WHICH offered items it featured, or the offered order stands —
    # "random products" under segment-specific prose was the owner's read
    # of the alternative (2026-08-21).
    # WHAT THE DRAFTER ACTUALLY CHOSE — read the same way whichever contract it
    # answered in, and read BEFORE anything else selects.
    #
    # This used to be gated `if not copy.get("blocks")`, so on the CURRENT
    # contract — the one that ships — the offered list was never narrowed. Four
    # selectors then read it independently and disagreed: the product cards came
    # from the drafter's `products` block, the hero came from `hero_for_campaign`
    # over the WHOLE offered list, and the imageless fallback took whichever
    # offered product happened to have a photograph. That is how an email whose
    # subject line and body were about shatterproof glasses shipped with a
    # tablecloth as its hero and a pitcher bundle on its card (owner,
    # 2026-08-22). Nothing in it was false; the parts simply never agreed.
    by_key = {e["key"]: e for e in ents if e.get("key")}
    picked = [k for k in (copy.get("featured_keys") or [])
              if isinstance(k, str) and k in by_key]
    for b in (copy.get("blocks") or []):
        if isinstance(b, dict) and b.get("type") == "products":
            picked += [k for k in (b.get("keys") or [])
                       if isinstance(k, str) and k in by_key]
    picked = list(dict.fromkeys(picked))
    if picked:
        ents = [by_key[k] for k in picked][:3]
        ctx.note("products: the drafter featured "
                 + ", ".join(e["name"] for e in ents))
    else:
        ents = ents[:3]
        if ents and not plan_scoped and not copy.get("blocks"):
            ctx.note("products: no entity on the plan and no drafter "
                     "choice — the catalogue's top available items are "
                     "featured; set Featured entity on the plan to "
                     "choose them")
    ctx.bundle["entities"] = ents

    # THE COMMITMENT: what this email is about, declared now, so every selector
    # below derives from one decision instead of re-deciding for itself. The
    # plan's entity outranks the drafter's — the plan is the reviewed
    # instruction — and the rest of what was featured are declared COMPANIONS,
    # which is the difference between "this email shows three products" and
    # "this email shows three products nobody chose".
    # ONLY WHAT SOMEBODY ACTUALLY CHOSE. Falling back to `ents[0]` committed the
    # email to whichever product the catalogue happened to rank first — a
    # decision nobody made, asserted as though somebody had, which is the very
    # thing this contract exists to stop. When neither the plan nor the drafter
    # named one, there is no entity subject and the email is committed to its
    # audience instead; the parts are then held to agreeing with each other.
    _subject = str(ctx.params.get("entity_key") or "").strip() or (
        picked[0] if picked else "")
    if _subject:
        _sub_name = next((e.get("name", "") for e in ents
                          if e.get("key") == _subject), _subject)
        commitment = coherence.commit(
            "entity", _subject, label=_sub_name, audience=seg["key"],
            action=goal or seg.get("angle", ""),
            also=[e.get("key", "") for e in ents if e.get("key") != _subject])
    else:
        # No product at all is a legitimate email — a story, a letter. It has
        # no entity subject, so the subject checks are vacuous; the proof and
        # image checks still hold, and those are the ones that matter here.
        commitment = coherence.commit("audience", seg["key"],
                                      audience=seg["key"],
                                      action=goal or seg.get("angle", ""))
    ctx.note(f"this email is about: {commitment.get('label') or seg['name']}"
             + (f" (with " + ", ".join(commitment["also"]) + ")"
                if commitment.get("also") else ""))

    # A subject set on the PLAN is the owner's line and outranks the
    # drafter's — the plan is the reviewed instruction. Set before
    # validation, so the banned-claims gate reads what will actually ship.
    plan_subject = str(ctx.params.get("subject") or "").strip()
    if plan_subject:
        copy["subject"] = plan_subject
        ctx.note("subject line came from the plan, not the drafter")

    # The bespoke visual, through the governed loop: an APPROVED, OWNED
    # photograph or nothing — `draft_visual` opts into having a Canva draft
    # created on a miss, which lands in the pictures queue, never in this
    # email. The refusal/note is surfaced either way, so an imageless send
    # is a decision the owner can see, not a silent default.
    # SELECTED FROM THE COMMITMENT, not from the offered list. The subject
    # leads, its companions follow — so a photograph of the thing this email is
    # about is preferred over a photograph of something that merely happened to
    # be on the shortlist.
    hero_got = creative.hero_for_campaign(
        ctx.tenant, segment_key=seg["key"],
        # THE SUBJECT FIRST, then everything this email actually features.
        # Scoping to the commitment ALONE starved the legacy path, where the
        # drafter names nothing and the catalogue fallback still puts real
        # products in the email — the hero then dropped to the brand-wide shelf
        # past a perfectly good photograph of the product on the card.
        # `_usable` honours this order, so priority is expressed here once.
        entity_keys=[k for k in ([commitment.get("key")]
                                 + list(commitment.get("also") or [])
                                 + [e.get("key", "") for e in ents]) if k],
        title=f"Email hero — {seg['name']}"[:120],
        draft_if_missing=_flag(ctx.params.get("draft_visual")))
    hero = hero_got.get("image")
    hero_subject = str(hero_got.get("subject_key") or "")
    if hero_got.get("basis") == "drafted_in_canva":
        ctx.note("bespoke visual: " + hero_got.get("note", ""))
    elif not hero:
        # THE PRODUCT'S OWN PHOTOGRAPH IS A HERO. The creative library and the
        # entity's `attributes.image` are two different stores, both filled by
        # the same catalogue sync, and only the library was ever reachable
        # from here — so an account whose products all had photos still sent
        # imageless emails if nothing had been filed as a library asset
        # (owner, three sends running: "still no images").
        #
        # Rights are not being stretched to do this. It is the same URL, from
        # the same product, that the sync files as `rights=owned` for exactly
        # this purpose: the client's photograph of the client's product,
        # already published on their own storefront.
        #
        # THE SUBJECT'S OWN SHOT FIRST. `next(... if e.get("image"))` over the
        # offered order took whichever product happened to have a photograph,
        # which on an unnarrowed list meant the alphabetically-first one — a
        # second route to the same wrong picture. The committed subject leads;
        # a companion only stands in when the subject has no photograph, and
        # then the run says so.
        _order = sorted(ents, key=lambda e: e.get("key") != commitment.get("key"))
        _shot = next((e for e in _order if e.get("image")), None)
        if _shot:
            hero = {"url": _shot["image"], "alt": _shot.get("name", "")}
            hero_subject = _shot.get("key", "")
            ctx.note(f"hero: no library photograph, so {_shot.get('name','')}'s "
                     f"own product shot leads the email"
                     + ("" if _shot.get("key") == commitment.get("key")
                        else " — the subject itself has no photograph on file"))
        else:
            ctx.note("no hero image: " + hero_got.get("why", ""))

    theme = _theme_for(ctx.tenant)
    webview = bool(esp.caps(ctx.tenant).get("webview", True))
    missing = email_render.missing_to_send(theme)
    if missing:
        ctx.note("not yet sendable: " + "; ".join(missing)
                 + " (comes from the brand theme, which needs deriving/review)")

    # ONE function builds everything downstream of the copy — layout, HTML,
    # native personalization — and returns the exact text the validator will
    # read. It runs again on every repair, which is the point.
    #
    # It used to be a straight line: render, personalize, then emit with the
    # HTML already in `meta`. Two defects lived in that gap. (1) A repair
    # rewrote the copy and re-validated it, but `meta["html"]` still held the
    # render of the REJECTED draft — so a repaired email filed clean text and
    # shipped the failing HTML to the ESP. (2) The repair returned only
    # `body_html`, so the re-check no longer contained the subject: a banned
    # phrase in a SUBJECT LINE was "repaired" by rewriting the body, and the
    # second check passed because the subject was no longer being looked at.
    # Rebuilding from the copy, and checking the same shape every time, closes
    # both — the thing validated and the thing sent are now the same artifact.
    state: dict = {}

    def _build(c: dict) -> str:
        blocks, extra_cited = _assemble_blocks(c, ents, hero,
                                               offered_claims=offered,
                                               note=ctx.note,
                                               fmt=craft.get("format", ""),
                                               signatory=theme.get("sender"),
                                               default_cta_url=_cta_home,
                                               known_urls=_known)
        # The email's one destination, in preference order: what the CTA
        # actually ended up pointing at, then the featured product's page,
        # then the storefront. Every empty link in the prose gets it.
        _dest = next((b.get("url") for b in blocks
                      if b.get("type") == "cta" and b.get("url")
                      and b.get("url") != "#"), "")
        _dest = _dest or next((e.get("url") for e in ents if e.get("url")), "")
        _n = _fill_dead_links(blocks, _dest or _cta_home)
        for _b in blocks:
            for _f in ("html", "text"):
                if _b.get(_f):
                    _b[_f], _bad = links.repoint(_b[_f], ctx.tenant,
                                                 _dest or _cta_home, _dests)
                    for _u in _bad:
                        ctx.note(f"link repointed — {_u} is not a page on this "
                                 f"site; sent to {_dest or _cta_home} instead")
        if _n:
            ctx.note(f"{_n} link(s) the drafter left empty now point at "
                     f"{_dest or _cta_home} — a drafter is not given URLs, "
                     f"so it cannot supply them")
        _undouble_blocks(blocks)
        c["preheader"] = _undouble(c.get("preheader", ""))
        c["subject"] = _undouble(c.get("subject", ""))
        html = email_render.render(theme, blocks,
                                   preheader=c.get("preheader", ""),
                                   # Omnisend has no view-in-browser variable —
                                   # its caps say so, and a header link no
                                   # variable can fill ships as literal text.
                                   webview=webview)
        native = esp.personalize(ctx.tenant, html)
        state.update(
            copy=c, blocks=blocks,
            cited=list(dict.fromkeys(
                [cid for cid in (c.get("claim_ids") or []) if cid in offered]
                + extra_cited)),
            html=native["html"] if native.get("ok") else html,
            native_ok=bool(native.get("ok")),
            native_why=str(native.get("error") or native.get("why") or ""))
        # Subject and preheader are read by a human in the inbox before
        # anything else, so they are checked with the body, always.
        return (f"{c.get('subject', '')}\n{c.get('preheader', '')}\n"
                f"{c.get('headline', '')}\n" + _blocks_text(blocks))

    to_check = _build(copy)

    # CRAFT, checked in code and given ONE chance to be fixed. This is
    # deliberately not the banned-claims loop: compliance blocks forever,
    # craft is advice — except for urgency with nothing behind it, which is a
    # lie told in the client's name and is therefore a block. A second model
    # pass is worth it because the findings are specific enough to act on;
    # a third would be paying for diminishing returns on a taste question.
    findings = _craft_review(ctx, copy, state["blocks"], craft)
    if findings and basis == "model":
        again, _b2, _w2 = draft_campaign(
            {**ctx.bundle,
             "rules": {**ctx.bundle.get("rules", {}),
                       "block": ctx.bundle.get("rules", {}).get("block", "")
                       + email_craft.as_prompt(findings)}}, seg, goal, craft)
        if again:
            retry = _shape_campaign_copy(again, ctx.note)
            if plan_subject:
                retry["subject"] = plan_subject
            left = _craft_review(ctx, retry, _assemble_blocks(
                retry, ents, hero, offered_claims=offered, note=lambda _m: None,
                fmt=craft.get("format", ""), signatory=theme.get("sender"),
                default_cta_url=_cta_home, known_urls=_known)[0], craft)
            # Keep the rewrite only when it is actually better — and BLOCKS
            # decide that before anything else. The first rule here compared
            # total finding counts, so a retry that removed the one thing
            # stopping the send but added a shorter-subject nudge scored
            # "not fewer" and was thrown away, leaving the email blocked over
            # a problem the drafter had just fixed.
            was, now = (email_craft.block_reasons(findings),
                        email_craft.block_reasons(left))
            better = (len(now) < len(was)
                      or (len(now) == len(was) and len(left) < len(findings)))
            if better:
                copy, to_check, findings = retry, _build(retry), left
                ctx.note("craft: redrafted once and it came back better"
                         + (f" — {len(was) - len(now)} blocking problem(s) "
                            f"resolved" if len(now) < len(was) else ""))
    for f in findings:
        ctx.note(f"craft ({f['severity']}): {f['detail']} → {f['fix']}")

    ctx.note("layout: " + ", ".join(b.get("type", "?")
                                    for b in state["blocks"]))

    # AN EMAIL WITH NO PICTURE IN IT SAYS SO. One shipped carrying nothing but
    # the logo (owner, 2026-08-22) and the run did not remark on it, because
    # each individual decision — this format has no hero, this product has no
    # photo — was reported separately and nobody adds them up. The reader sees
    # the total, so the run reports the total, and names which of the two
    # reasons it was.
    if not any(b.get("type") == "hero" or
               (b.get("type") == "products"
                and any(i.get("image") for i in (b.get("items") or [])))
               for b in state["blocks"]):
        if hero and hero.get("url"):
            ctx.note("this email carries NO image — an approved photograph "
                     "was available and the layout did not place it")
        else:
            # COUNT IT, do not advise. "Run the catalogue sync" was the note
            # for three imageless sends running and did not settle whether the
            # sync was the problem. The number does: 0 of 14 is a sync that
            # has not run, 11 of 14 is a layout that did not place what it had.
            _all = _kb.entities(ctx.tenant, available_only=False)
            _with = sum(1 for e in _all
                        if (e.attributes or {}).get("image"))
            ctx.note(
                f"this email carries NO image at all, only the logo — "
                f"{_with} of {len(_all)} product(s) have a photograph on file"
                + (" — run the catalogue sync on the Review tab; until it "
                   "does, there is no product imagery to place"
                   if not _with else
                   " — photos exist, so this is the layout, not the data")
                + (" (and no approved library photograph either)"
                   if not hero_got.get("image") else ""))
    if not state["native_ok"]:
        # The failure is REPORTED, not assumed. This said "ESP not connected"
        # for every cause, including `personalize`'s unknown-token refusal —
        # the guard that exists to catch a drafter typo. One stray token made
        # a connected account read as disconnected and the draft vanish with
        # no reason given.
        ctx.note("personalization stayed neutral, so nothing was drafted into "
                 "the ESP: " + (state["native_why"] or "no ESP is connected — "
                                "connect one to make {{FIRST_NAME}} and the "
                                "unsubscribe link native"))

    def _repair(previous: str, failures: list) -> str:
        why = "\n".join(f"- {f['detail']} → {f['fix']}" for f in failures)
        again, _b, _w = draft_campaign(
            {**ctx.bundle,
             "rules": {**ctx.bundle.get("rules", {}),
                       "block": ctx.bundle.get("rules", {}).get("block", "")
                       + f"\n\n## Your previous copy was rejected\n{previous}"
                         f"\n\n## Why, and what to change\n{why}\nRewrite it so "
                         f"none of these apply; keep it truthful and keep the "
                         f"claims you cited."}}, seg, goal, craft)
        if not again:
            return ""
        # Rebuild through the same path, so the repaired email is the one that
        # gets rendered, personalized, re-checked and — if it passes — sent.
        return _build(_shape_campaign_copy(again, ctx.note))

    def _parts() -> dict:
        """The email AS ITS PARTS, read after every rebuild.

        A callable for the same reason `meta` is one: a repair replaces the
        copy, and a parts dict built before that describes the artifact that
        was thrown away. It is also the whole reason the hero is checkable at
        all — `emit` validates a STRING, and the picture was never in it.
        """
        _items = [{"key": i.get("key", ""), "name": i.get("name", "")}
                  for b in state["blocks"] if b.get("type") == "products"
                  for i in (b.get("items") or [])]
        _imgs = [{"url": hero.get("url", ""), "alt": hero.get("alt", ""),
                  "subject_key": hero_subject or "",
                  "basis": hero_got.get("basis", "")}
                 for b in state["blocks"] if b.get("type") == "hero" and hero]
        _c = state["copy"]
        return coherence.parts(
            text=_blocks_text(state["blocks"]),
            prominent=f"{_c.get('subject', '')} {_c.get('headline', '')}",
            images=_imgs, items=_items,
            claims=[{"claim_id": cid, "text": offered[cid]["claim"],
                     "scope": offered[cid].get("scope", "brand-wide")}
                    for cid in state["cited"] if cid in offered])

    item = ctx.emit(
        to_check, claim_ids=state["cited"], angle=seg["key"],
        fmt="campaign_email",
        # ONE ARTIFACT, ONE SUBJECT — checked at the same door, repaired by the
        # same loop, on the parts rather than on the prose.
        commitment=commitment, parts=_parts,
        require_citation=False,      # a promo email need not cite; banned always runs
        destination=f"esp:{esp.provider_for(ctx.tenant) or 'none'}",
        # Filed so the NEXT send can be a different one: the shape it must not
        # repeat, and the intent that decides whether the list is owed a give
        # or has earned an ask.
        # `intent|format` — both axes of the last send, so the next one can
        # differ on either. Shape alone cannot tell them apart now that a
        # letter may also carry a hero and a product.
        theme=f"{craft.get('intent', '')}|{craft.get('format', '')}",
        shape=lambda: [b.get("type", "?") for b in state["blocks"]],
        # A CALLABLE, read after the repair loop settles: meta must describe
        # the email that finally passed, not the one that was replaced.
        meta=lambda: {"subject": state["copy"].get("subject", ""),
                      "preheader": state["copy"].get("preheader", ""),
                      "html": state["html"], "segment": seg["key"],
                      "basis": basis, "intent": craft.get("intent", ""),
                      "format": craft.get("format", ""),
                      "shape": [b.get("type", "?") for b in state["blocks"]],
                      "sendable": not missing, "missing_to_send": missing},
        redraft=_repair if basis == "model" else None)

    copy, cited = state["copy"], state["cited"]
    final_html, native_ok = state["html"], state["native_ok"]

    # A craft BLOCK stops the send the same way a banned claim does. There is
    # exactly one of them — urgency with no source — and it earns the severity:
    # every other finding is a worse email, this one is a false statement made
    # in the client's name, at scale, over their sending domain.
    hard = email_craft.block_reasons(findings)

    # THE LAST LINE: what the copy actually NAMES. Screening the offer list
    # stops the common case; it cannot stop a drafter that knows a product
    # from a claim, a past send, or the brand's own positioning. Eien's letter
    # named CitroBurn in a sentence — no card, no key, no parameter — so the
    # only check that could ever have caught it is one that reads the words.
    # Promoting something a customer cannot buy is a block, not advice: the
    # click goes to a dead page and the sender pays for it in trust.
    for _why in email_craft.dead_links(state["blocks"]):
        hard.append({"severity": "block", "rule": "dead_link", "detail": _why,
                     "fix": "give it the real destination — a send is spent "
                            "whether or not the link worked"})

    _all_ents = _kb.entities(ctx.tenant, available_only=False)
    _named = fitness.named_unfit(_model, to_check, _all_ents)
    for n in _named:
        hard.append({"severity": "block", "rule": "unfit_entity_named",
                     "detail": f"the email recommends {n['name']}, but "
                               f"{n['why']}",
                     "fix": "fix it in the store, or send an email that does "
                            "not name it"})
    if hard:
        ctx.note("not drafted into the ESP: "
                 + "; ".join(f["detail"] for f in hard))

    # Set it up in the ESP as a DRAFT — only when the copy passed, the ESP is
    # connected, and there is nothing blocking a send. A draft is safe (nothing
    # sends); LAUNCHING is `esp.backend().send_campaign(confirm=True)`, which the
    # substrate never calls — that is the final approval the owner keeps.
    esp_draft, esp_target = {}, {}
    if (item.get("ok") and not missing and native_ok and not hard
            and _flag(ctx.params.get("draft_into_esp"), default=True)):
        mod, refusal = esp.backend(ctx.tenant)
        if refusal:
            ctx.note("could not draft into the ESP: " + refusal)
        else:
            # Bind the draft to the PLANNED segment inside the ESP — the
            # remembered id first, a live name-match second, and a named
            # absence third: an untargeted draft is a real state the owner
            # must see, because at launch it would go to whoever the ESP
            # defaults to rather than to the cohort the plan named.
            from . import segments as segmod
            target = esp_target = segmod.esp_id_for(ctx.tenant, seg["key"])
            include = [target["id"]] if target.get("id") else None
            if not target.get("id"):
                ctx.note("the ESP draft is untargeted — " + target.get("why", ""))
            elif target.get("why"):
                ctx.note(target["why"])
            try:
                esp_draft = mod.draft_from_html(
                    ctx.tenant, name=copy.get("subject", "")[:120],
                    subject=copy.get("subject", ""),
                    sender_name=theme["name"], html=final_html,
                    preheader=copy.get("preheader", ""),
                    include_segments=include)
                if not esp_draft.get("ok"):
                    ctx.note("the ESP rejected the draft: "
                             + esp_draft.get("error", "")[:200])
                elif esp_draft.get("images_not_rehosted"):
                    # Rehosted images cannot be broken by the ESP; these
                    # stayed hotlinked and might be.
                    ctx.note("image(s) the ESP would not rehost — kept "
                             "hotlinked, may render broken there: "
                             + ", ".join(esp_draft["images_not_rehosted"][:3]))
                if esp_draft.get("ok") and hero_got.get("asset_id"):
                    # Feedback signal one: the photograph actually went into
                    # a drafted campaign. Publishing is the explicit act the
                    # creative library's `uses` counter exists for.
                    from . import kb as _kb
                    _kb.mark_asset_used(hero_got["asset_id"],
                                        destination="campaign_email draft")
            except Exception as exc:                            # noqa: BLE001
                ctx.note(f"drafting into the ESP raised {exc.__class__.__name__}")

    # NO DRAFT, NO APPROVAL TO GIVE. `emit` queued one the moment the copy
    # cleared the validator, but the artifact is created here, afterwards — so
    # anything that stopped it (a craft block, an ESP refusal, a raised
    # exception) leaves a queue item describing an email that exists nowhere.
    # Approving it produced nothing and removed it from the queue, which is how
    # an approved campaign became impossible to find (owner, 2026-08-22).
    if not esp_draft.get("ok") and _flag(ctx.params.get("draft_into_esp"),
                                         default=True):
        why = ("; ".join(f["detail"] for f in hard) if hard
               else esp_draft.get("error")
               or ("the copy did not pass the validator" if not item.get("ok")
                   else "; ".join(missing) if missing
                   else "personalization did not run, so nothing was drafted"
                   if not native_ok else "the ESP draft was not created"))
        from . import approvals as _appr
        if _appr.withdraw(ctx.run_id, why):
            ctx.note("the approval for this email was withdrawn — there is no "
                     "draft in the ESP to approve: " + why)

    return {"summary": (f"campaign email for '{seg['name']}' — {basis}, "
                        + ("sendable" if not missing else "not yet sendable")
                        + (", hero image" if hero else ", no hero image")
                        + (", drafted in ESP" if esp_draft.get("ok")
                           else ", NOT DRAFTED IN ESP")),
            "segment": seg, "basis": basis, "cited_claims": cited,
            "hero": {"basis": hero_got.get("basis", ""),
                     "asset_id": hero_got.get("asset_id", ""),
                     "drafted": hero_got.get("drafted", {})},
            "esp_target": esp_target,
            "esp_draft": esp_draft, "html_bytes": len(final_html)}


register(Skill(
    key="campaign_email",
    name="Campaign email",
    does="Draft a send-ready, on-brand, compliant marketing email for one "
         "audience segment — copy grounded in the brand's voice and approved "
         "claims, rendered to the brand's look, made native for its ESP, and "
         "(when connected) set up as a draft ready to launch pending approval.",
    system_key="campaign_email",
    tier=3,
    needs=("rules.voice_tone", "rules.positioning"),
    params=("segment", "goal", "subject", "intent", "deadline", "entity_key",
            "audience_key", "utterance", "draft_into_esp", "draft_visual"),
    writes=True,
    produces="draft",
    run=_run_campaign_email))
