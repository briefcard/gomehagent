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

from . import compliance, responder, sites
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

    ctx.emit(body,
             claim_ids=[c.get("claim_id") for c in (res.get("evidence") or [])
                        if c.get("claim_id")],
             entity_key=str(ctx.params.get("entity_key") or ""),
             situation=res.get("situation") or "",
             conversation_id=res.get("conversation_id") or "",
             angle="reply", fmt="reply",
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
    params=("utterance", "contact_id", "entity_key", "facts",
            "draft_with_model"),
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
            usage.log_usage("ad_copy_draft", config.CLAUDE_MODEL, msg)
        except Exception:                                        # noqa: BLE001
            pass
        return msg.content[0].text.strip(), ""
    except Exception as exc:                                     # noqa: BLE001
        return "", f"{exc.__class__.__name__}: {str(exc)[:120]}"


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
