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

import datetime as _dt

import html as _htmllib
import re

from . import ad_craft, funnel
from . import coherence, compliance, responder, sites, systems
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

    # A CLEAN SWEEP IS STILL A CHECK, and it used to return here without
    # emitting anything — so the history recorded bad days and nothing else,
    # and "we checked and it was clean" was indistinguishable from "nobody
    # checked". Those are the two states a compliance record exists to tell
    # apart. Owner, 2026-08-31, asking for a reviewable history of checks.
    _when = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if not violations:
        lines = [f"Catalogue compliance — {_when}", "",
                 f"No banned claim found. {cov.get('scanned', 0)} product(s) "
                 f"checked."]
    else:
        lines = [f"Catalogue compliance — {_when}", "",
                 f"{len(violations)} banned-claim violation(s) across "
                 f"{len({f['handle'] for f in violations})} product(s), "
                 f"{cov['scanned']} scanned.", ""]
        for (fname, phrase), rows in found["ranked"]:
            lines.append(f"{len(rows)}x  {fname}  —  {phrase!r}")
            lines.append(f"      e.g. {rows[0]['handle']}: "
                         f"{rows[0]['context'][:160]}")
    # A COMPLIANCE REPORT IS MANY SUBJECTS ON PURPOSE — one line per product
    # that broke a rule. Holding it to one subject would be wrong, and leaving
    # it uncommitted would make `no_commitment` fire on every run. `survey` is
    # the declared escape: the check inverts to non-duplication instead of
    # being switched off, which for a report that ranks repeated patterns is
    # exactly the property worth having.
    ctx.emit("\n".join(lines), fmt="report", require_citation=False,
             commitment=coherence.commit(
                 "survey", "catalogue", action="list what breaks a rule"),
             parts=lambda _t: coherence.parts(text=_t))

    return {"summary": (f"{len(violations)} violation(s), "
                        f"{len(found['ranked'])} distinct pattern(s)"
                        if violations else
                        f"no violations in {cov.get('scanned', 0)} product(s)"),
            **found}


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
        # ONE PRODUCT, ONE META DESCRIPTION. This skill already picked proof
        # scoped-first — the commitment is what lets code CHECK that it did,
        # and catches the case the fallback allows: a brand-wide claim is fine,
        # another product's claim never is. The ancestor chain rides along so a
        # collection's claim about its members is not mistaken for a stray.
        _commit = coherence.commit(
            "entity", handle, label=f["name"], action="rank for this product",
            proof_scopes=[handle] + list(kb_mod.ancestors(ctx.tenant, handle)))
        ctx.emit(body, claim_ids=[pick["claim_id"]], entity_key=handle,
                 angle="compliance_rewrite", fmt="seo_description",
                 commitment=_commit,
                 # A meta description is ALL prominent — it is the whole of
                 # what a searcher reads — so it is passed once, as that.
                 parts=lambda _t, _p=pick: coherence.parts(
                     prominent=_t,
                     claims=[{"claim_id": _p.get("claim_id", ""),
                              "text": _p.get("claim", ""),
                              "scope": _p.get("scope", "brand-wide")}]),
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

def _run_weekly_report(ctx: Context) -> dict:
    """The weekly number, as a message to the client, held for approval."""
    from . import approvals as _appr, client_report, tenants
    t = tenants.get(ctx.tenant)
    days = int(ctx.params.get("days") or 7)
    to = str(ctx.params.get("to") or getattr(t, "report_to", "") or "").strip()
    rep = client_report.assemble(ctx.tenant, days)
    if rep.get("error"):
        ctx.note(rep["error"])
        return {"summary": rep["error"]}
    msg = client_report.render_email(rep)
    account = getattr(t, "gmail_alias", "") or ""
    # Blockers are NAMED on the run, not discovered at approval. A report
    # with nowhere to go still renders — the owner can read it — but the
    # send cannot be attached, and the note says which half is missing.
    if not to:
        ctx.note("no recipient: pass to= or set the account's report address")
    if not account:
        ctx.note("no sending account: this account has no Gmail alias")
    # The TEXT is the artifact and the summary; the html rides in meta and in
    # the send. Emitting the html put a <div style=...> on the approval card.
    item = ctx.emit(msg["text"], fmt="report_document", destination=to,
                    require_citation=False,
                    meta={"subject": msg["subject"], "days": days, "to": to,
                          "html": msg["html"]})
    if to and account and ctx.run_id:
        _appr.attach_send(ctx.run_id, {"account": account, "to": to,
                                       "subject": msg["subject"],
                                       "text": msg["text"], "html": msg["html"]})
    return {"summary": f"weekly report drafted for {to or 'nobody yet'}",
            "output_id": item.get("output_id", ""), "subject": msg["subject"]}


register(Skill(
    key="weekly_report",
    name="Weekly report",
    does="The week's number for one client, read off the record and put in "
         "their vocabulary — what moved, what we did, what is not yet "
         "measured and why. Held for approval; approving sends it.",
    system_key="reports",
    tier=1,
    needs=(),
    params=("days", "to"),
    # A report that SENDS is a write. `writes=False` filed it as a draft with
    # no approval to carry the send on — nothing to approve, nothing sent.
    writes=True,
    produces="report",
    run=_run_weekly_report))


# THE SAME REPLY, GOVERNED AS A LEAD. `replies.ROUTES` sends `sales_leads`
# mail to `lead_responder` and everything else to `service_desk`, and the
# responder files each run under the system it was called for — but a Skill
# binds ONE system_key, so only service_desk had a skill and lead_responder
# read as "no generator" to autonomy, readiness and the effectiveness map.
# A first enquiry and a routine order question are the same drafting act with
# different governance: different rung, different guidance, different measure.
# One run function, two envelopes.
register(Skill(
    key="lead_reply",
    name="Lead reply",
    does="Answer a first enquiry from a prospect with a grounded, approved "
         "draft — the same responder as a service reply, governed as a lead: "
         "its own autonomy rung, its own guidance, its own edit rate.",
    system_key="lead_responder",
    tier=3,
    needs=("rules.banned_claims",),
    params=("utterance", "contact_id", "entity_key", "facts",
            "draft_with_model", "thread_id"),
    writes=False,
    produces="draft",
    run=_run_inbound_reply))


# ---------------------------------------------------------------------------
# 4 · Ad copy — the model writes it, code decides what it may write from
# ---------------------------------------------------------------------------

#: The angles this account may use, decided per run by `ad_craft.angles_for`
#: from the account's OWN data — see `_run_ad_copy`. It was three hardcoded
#: here ("proof", "objection", "occasion"), and "proof" is not an angle at
#: all: proof is a value lever that belongs in EVERY ad, not the theme of one.
#: Kept as the universal fallback for callers with no evidence to hand.
_ANGLES = ad_craft.UNIVERSAL_ANGLES

#: THE BRIEF USED TO BE ONLY PROHIBITIONS. Every sentence told the model what
#: it must not do and none told it how to write an ad — which is why the owner
#: called the output "completely terrible" (2026-08-29). The rules below are
#: from `ad_craft`, which is the pipeline already written down and validated
#: against a live account; this string is where the drafter finally receives
#: them. The prohibitions stay, because they are the reason nothing false
#: ships — they are simply no longer the whole instruction.
_AD_SYSTEM = """You are writing one short ad for this brand.

## What must be true
You are given exactly one approved claim to build on. Use it. Do not introduce
a second factual claim, a price, a material, an origin or a guarantee that is
not in the context — the hard rules are enforced in code after you write, so a
draft breaking one is thrown away rather than softened, and you will simply
have wasted the slot. Match the house voice.

## What makes it an ad rather than a description
THE FIRST FIVE WORDS ARE THE WHOLE AUDITION. They are the only words most
people read. Open on a concrete noun, a number, or the reader themselves —
never an adjective, and never "Introducing", "Discover" or "Meet". Nobody is
waiting to be introduced to anything.

ONE IDEA. A second idea does not add to the first, it competes with it.

BE SPECIFIC OR SAY NOTHING. "Beautiful", "elegant", "timeless", "curated",
"perfect for" are true of every competitor in the category, which is exactly
why they persuade nobody. Name the material, the number, the moment. One real
number does more for belief than any adjective.

THE VALUE EQUATION. Pull at least two of these four levers, and say which:
- dream_outcome — what their life looks like after
- likelihood — why it will work FOR THEM: proof, numbers, what sold out
- time_delay — how fast; in stock, ships in time
- effort — what they do NOT have to do
An ad pulling none of them is a mood board.

IF THERE IS AN OFFER, IT GOES EARLY. The feed cuts at about 125 characters.
An offer after the cut was not made. State it exactly as it is given to you —
an offer worded differently in each variant reads as a different offer.

NEVER manufacture urgency. No "last chance", "ends tonight", "while supplies
last" unless a real deadline is given to you below. Code will stop it."""

def _angle_brief(angle: str) -> str:
    """One angle's instruction, from the ruleset. One writer, one vocabulary."""
    a = ad_craft.ANGLES.get(angle) or {}
    return f"{a.get('label', angle)} — {a.get('brief', '')}"


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

        parts = ad_prompt(bundle, claim, angle, objections)
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


def ad_prompt(bundle: dict, claim: dict, angle: str,
              objections: list) -> list[str]:
    """Everything the ad drafter is told, as inspectable parts.

    SPLIT OUT so it can be asserted on. It used to be assembled inline inside
    the API call, which meant the only way to check that a craft rule reached
    the model was to have an API key — so `the_drafter_gets_a_craft_brief`
    could be sabotaged and every suite still passed. A brief nobody can read
    without spending money is a brief nobody checks.
    """
    parts = [bundle["rules"]["block"].strip()]
    if bundle.get("revision_notes"):
        # The board's regenerate rides through here (UI overhaul 3.4).
        # Notes FIRST — the convention campaign_email and blog_article
        # already hold: the owner's direction outranks everything but
        # the rules themselves.
        parts.append("\n## The owner reviewed the previous batch — "
                     "address this before anything else\n"
                     + str(bundle["revision_notes"]).strip())
    parts.append(
        f"\n## The one claim you may build on\n"
        f"{claim['claim']}"
        + (f"\n(evidence: {claim['evidence']})" if claim.get("evidence") else "")
        + f"\n(this is true of: {claim.get('scope') or 'the brand'})")

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
    # WHERE THE READER IS, before the angle — because the angle is HOW to say
    # it and the stage is WHO IS LISTENING, and getting the second one wrong
    # produces a well-formed ad aimed at somebody else. The objections and
    # situations this account actually has are quoted here, which is the whole
    # of the owner's 2026-08-29 correction: they are strategy, not grounding.
    if bundle.get("funnel"):
        parts.append(funnel.brief(bundle["funnel"]))
    # WHAT THIS BATCH IS TESTING, above the angle, because the angle is one
    # way of expressing it. Without this a batch of five variants is five
    # drafts; with it they are five expressions of one idea, which is what
    # makes the batch a test and the result readable.
    if str(bundle.get("positioning") or "").strip():
        parts.append(
            "\n## THE POSITIONING THIS BATCH IS TESTING\n"
            + str(bundle["positioning"]).strip()
            + "\nEvery variant must be an expression of THIS idea. Variants "
              "that argue different things cannot be compared, and a batch "
              "that tests nothing teaches nothing.")
    parts.append(f"\n## Angle\n{_angle_brief(angle)}")
    # The offer, once, exactly as it will be stated everywhere else, plus
    # where it has to land. `ad_craft` measures both after the fact.
    offer = str(bundle.get("offer") or "").strip()
    if offer:
        parts.append(f"\n## The offer — state it EXACTLY like this, and "
                     f"inside the first {ad_craft.TRUNCATION} characters\n"
                     f"{offer}")
    deadline = str(bundle.get("deadline") or "").strip()
    parts.append(f"\n## The real deadline\n{deadline}" if deadline else
                 "\n## There is NO deadline for this. Do not imply one.")
    parts.append("\n## How to answer\n" + ad_craft.REPLY_FORMAT)
    return parts


# Replaceable so the offline suite can drive both halves — including a model
# that returns a banned phrase, which must still be blocked by the validator.
draft_ad = _draft_ad_live


def _has_a_reader_to_pick(tenant: str) -> bool:
    """Can this account name a reader at all?

    The requirement binds only when the choice EXISTS. An account with no
    approved persona on file still runs — thinly, and `_reader_gap` says so —
    because refusing there would stop work on the strength of an absence,
    which this layer does not do. An account WITH personas that named none is
    a decision somebody skipped, and that is what gets refused.
    """
    try:
        from . import kb as _k
        return bool(_k.audiences(tenant))
    except Exception:                                            # noqa: BLE001
        return False


def _reader_gap(ctx) -> None:
    """Say — on the run and on Assurance — that this work has no reader.

    TWO DIFFERENT GAPS, and collapsing them is the thing this codebase keeps
    paying for. "Nobody has written a persona" is work for the owner in the
    knowledge base. "Three are approved and this send named none of them" is a
    decision missing from the plan. Same symptom, different fix, different
    person — so they get different keys and Assurance can separate them.

    Mass marketing only, which is why this lives in the drafters rather than
    in `resolve`: a one-to-one reply has an actual person on the other end and
    needs no persona at all.
    """
    if ctx.bundle.get("audience"):
        return
    roster = len(ctx.bundle.get("audiences") or [])
    if roster:
        ctx.thin.append("reader:not-chosen")
        ctx.note(f"no reader was chosen for this piece — {roster} approved "
                 f"persona(s) are on file and none was named, so it is written "
                 f"for everybody and therefore for nobody in particular")
    else:
        ctx.thin.append("reader:none-on-file")
        ctx.note("no buyer persona is on file for this account, so nothing "
                 "can say whose words to write in — authoring one is what "
                 "turns this from generic copy into copy for somebody")


def _run_ad_copy(ctx: Context) -> dict:
    entity_key = str(ctx.params.get("entity_key") or "")
    audience_key = str(ctx.params.get("audience_key") or "")
    want = max(1, min(5, int(ctx.params.get("variants") or 3)))
    # `revision_notes` is on the bundle already — `skill.run` hops every
    # OWNER_INPUT parameter there for every skill. This was a private
    # three-line copy, one of three, for the parameter whose declared supplier
    # in `bundle.PARTS` was `skill.run` all along.

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
    # `offer` and `deadline` are already on the bundle — `skill.run` puts every
    # OWNER_INPUT parameter there for every skill. This used to be a private
    # two-line hop here, which is why `campaign_email` could read a parameter
    # it had never declared and get nothing for a fortnight.
    by_basis: dict[str, int] = {}
    degraded_note = ""
    #: The variant board's rows (3.4): what each KEPT variant is, in the
    #: board's own vocabulary — angle, basis, the claim it stands on, the
    #: post-repair text. Collected at emit because `angle` and the claim's
    #: wording live here and nowhere on the item.
    board_rows: list[dict] = []

    # ONE AD, ONE SUBJECT — the same contract the campaign runs under, with a
    # different referent shape. An ad has no imagery yet (see the note above),
    # so the picture clauses are vacuous; what is NOT vacuous is whose proof it
    # is. `kb.claims` hands back the brand's claims plus this entity's plus its
    # GROUPS', which is correct and is exactly why the check needs the ancestor
    # chain: "every Aqua piece is acrylic" is true of an Aqua pitcher, and
    # calling that off-subject would refuse the case the data layer was built
    # to serve.
    _label = ""
    _scopes: list[str] = []
    from . import systems as _sysm_ad
    _named_ad = [k for k in _sysm_ad.entity_list(
        ctx.params.get("entity_keys") or "") if k != entity_key]
    if entity_key:
        _row = next((e for e in kb_mod.entities(ctx.tenant, available_only=False)
                     if e.key == entity_key), None)
        _label = (getattr(_row, "name", "") or "") if _row else ""
        # THE HERO PLUS WHAT ELSE THE BATCH IS ABOUT. An ad for a venue may
        # legitimately lean on the campus it sits in; `entity_key` is still
        # the hero, and this is the rest of what its copy may cite.
        _scopes = ([entity_key] + _named_ad
                   + [a for k in [entity_key] + _named_ad
                      for a in kb_mod.ancestors(ctx.tenant, k)])
    _commit_base = dict(label=_label, audience=audience_key,
                        proof_scopes=_scopes)

    # WHICH ANGLES THIS ACCOUNT MAY USE, from its own knowledge base rather
    # than a fixed list. `gifting` is the one that does not generalise — an
    # events venue advertising "the most personal gift" is writing an ad for
    # somebody else's business, and nothing downstream would catch it because
    # the validator checks whether a draft is TRUE, not whether it is about us.
    _evidence = " ".join(
        [str(a.get("name") or a.get("key") or "") + " "
         + " ".join(a.get("pains") or []) for a in (ctx.bundle.get("audiences") or [])]
        + [str(c.get("claim") or "") for c in ctx.claims[:12]]
        + [str(o.get("objection") or "") for o in objections[:6]])
    angles = ad_craft.angles_for(_evidence)

    # THE FUNNEL STAGE, if one was asked for. Optional by design: a run with
    # no stage behaves exactly as it did before, so nothing that already works
    # changes shape. With one, the account's own objections and situations are
    # quoted into the brief and the angles narrow to the ones that make sense
    # for that reader — an offer-led ad at awareness is asking a stranger to
    # buy, and an objection-killer at awareness answers a hesitation nobody
    # has yet.
    stage = funnel.normalise(str(ctx.params.get("funnel_stage") or ""))
    if str(ctx.params.get("funnel_stage") or "").strip() and not stage:
        ctx.note(f"unknown funnel stage "
                 f"{str(ctx.params['funnel_stage'])!r} — the ones that exist "
                 f"are: " + ", ".join(funnel.STAGES)
                 + ". Running without one.")
    # THE BRIEF IS BUILT EITHER WAY. It used to be `if stage:` — so unless
    # somebody passed the knob, the ad drafter got no situations, no
    # objections-as-strategy, no audience vocabulary and no search phrases.
    # The default run, which is the run that actually happens, read almost
    # none of the data layer (owner, 2026-08-29: "how do we make sure to take
    # advantage of our context / data layer … to generate the best result").
    #
    # A DERIVED STAGE BRIEFS BUT DOES NOT BIND. An explicit stage is a
    # decision and narrows the angles with it; a derived one is an inference,
    # so it supplies the knowledge and leaves the angle set alone. Anything
    # that worked before therefore still produces the same variants — it just
    # produces them knowing what this account knows.
    # THE POSITIONING UNDER TEST. Given, it rides the bundle into the brief
    # and is recorded on every row of the batch so "which positioning did
    # better" is one GROUP BY. Absent, the run SUGGESTS the ones this
    # account's own data supports rather than silently testing nothing —
    # act where you report, and the run is the only place that knows.
    positioning = str(ctx.params.get("positioning") or "").strip()
    if positioning:
        ctx.bundle["positioning"] = positioning
        ctx.note(f"testing: {positioning}")
    else:
        try:
            _sug = funnel.proposals(ctx.tenant, limit=3)
        except Exception:                                        # noqa: BLE001
            _sug = {"proposals": [], "gaps": []}
        for _p in _sug.get("proposals") or []:
            ctx.note(f"worth testing ({_p['stage']}, {_p['audience']}): "
                     f"{_p['positioning']} — {_p['why']}"
                     + (f" [already tested {_p['tested']}x]"
                        if _p["tested"] else ""))
        for _g in _sug.get("gaps") or []:
            ctx.note(f"positioning (thin): {_g}")
        if _sug.get("proposals"):
            ctx.note("this batch tests no stated positioning — pass "
                     "positioning=… to make it a test rather than five drafts")

    chose = bool(stage)
    if not stage:
        # From what the batch already carries, not from a new knob (rule 4):
        # an ad with an offer to state is asking, and asking is bottom-of-
        # funnel behaviour whoever is reading.
        stage = funnel.stage_from(asks=bool(str(ctx.bundle.get("offer") or "").strip()))
    _reader_gap(ctx)
    plan = funnel.inputs_for(
        ctx.tenant, stage, claims=ctx.claims, objections=objections,
        entities=ctx.bundle.get("entities"),
        audience=ctx.bundle.get("audience"),
        offer=str(ctx.bundle.get("offer") or ""))
    ctx.bundle["funnel"] = plan
    if chose:
        angles = funnel.angles_for_stage(stage, angles)
        ctx.note(f"funnel stage: {plan['label']} — the reader "
                 f"{plan['reader']}")
    else:
        ctx.note(f"funnel stage (derived, angles not narrowed): "
                 f"{plan['label']} — the reader {plan['reader']}. "
                 f"Pass funnel_stage to choose one and narrow the angles.")
    # WHAT IS MISSING, BY NAME. The owner's "if they are available, of
    # course" is not permission to proceed quietly: a stage whose leading
    # input is absent produces something plausible and wrong, and the run is
    # the only place that can say so.
    for n in plan.get("note") or []:
        ctx.note(f"funnel (thin): {n}")
    if plan.get("missing"):
        # `Context.thin` is the list the assurance ledger reads as "what this
        # run was working WITHOUT" — appending here puts a strategy gap on the
        # same record as a knowledge gap, which is what it is.
        ctx.thin.extend(f"funnel:{m}" for m in plan["missing"])

    ctx.note("angles in play for this account: " + ", ".join(angles)
             + ("" if "gifting" in angles else
                " (gifting is not offered — nothing in this account's "
                "knowledge base says people buy this for somebody else)"))

    for i, claim in enumerate(ctx.claims[:want]):
        angle = angles[i % len(angles)]

        raw, why_not = draft_ad(ctx.bundle, claim, angle, objections)
        headline, levers, craft_findings = "", [], []
        text = raw
        if raw:
            basis = "model"
            got = ad_craft.parse(raw)
            text, headline, levers = got["body"], got["headline"], got["levers"]
            # THE CRAFT GATE. Model output only: the composer below is a
            # deterministic restatement of the claim and IS a mood board by
            # construction — it says so in `basis` — so reviewing it would
            # produce the same findings on every offline run and teach the
            # reader to skip them.
            craft_findings = ad_craft.review(
                body=text, headline=headline, angle=angle,
                offer=str(ctx.bundle.get("offer") or ""), levers=levers,
                urgency_backed_by=str(ctx.bundle.get("deadline") or ""),
                proof=str(claim.get("evidence") or ""))
            blocked = ad_craft.block_reasons(craft_findings)
            if blocked:
                # ONE redraft, and KEEP IT ONLY IF THE BLOCKS WENT DOWN — the
                # rule email learned the hard way: comparing total findings
                # threw away a retry that fixed the blocking problem and added
                # a nudge.
                retry_raw, _ = draft_ad(
                    {**ctx.bundle,
                     "rules": {**ctx.bundle.get("rules", {}),
                               "block": ctx.bundle.get("rules", {}).get("block", "")
                               + ad_craft.as_prompt(craft_findings)}},
                    claim, angle, objections)
                if retry_raw:
                    r = ad_craft.parse(retry_raw)
                    left = ad_craft.review(
                        body=r["body"], headline=r["headline"], angle=angle,
                        offer=str(ctx.bundle.get("offer") or ""),
                        levers=r["levers"],
                        urgency_backed_by=str(ctx.bundle.get("deadline") or ""),
                        proof=str(claim.get("evidence") or ""))
                    now = ad_craft.block_reasons(left)
                    if len(now) < len(blocked) or (
                            len(now) == len(blocked)
                            and len(left) < len(craft_findings)):
                        text, headline = r["body"], r["headline"]
                        levers, craft_findings = r["levers"], left
                        ctx.note(f"craft: variant {i + 1} redrafted once and "
                                 f"came back better — "
                                 f"{len(blocked) - len(now)} blocking "
                                 f"problem(s) resolved")
            sc = ad_craft.score(craft_findings)
            ctx.note(f"craft: variant {i + 1} ({angle}) scores "
                     f"{sc['total']}/{sc['of']}"
                     + ("" if sc["ship"] else " — below the bar to ship"))
            for f in craft_findings:
                ctx.note(f"craft ({f['severity']}): {f['detail']} → {f['fix']}")
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

        _commit = (coherence.commit("entity", entity_key, action=angle,
                                    **_commit_base)
                   if entity_key else
                   coherence.commit("audience", audience_key or "everyone",
                                    action=angle))
        item = ctx.emit(
            text, claim_ids=[claim["claim_id"]], entity_key=entity_key,
            audience_key=audience_key, angle=angle, fmt="ad_copy",
            # ON EVERY VARIANT, not on the batch. The batch is not a row —
            # the variants are — so recording the hypothesis once somewhere
            # else would mean joining through the run to answer the only
            # question worth asking of it.
            positioning=positioning, funnel_stage=stage,
            commitment=_commit,
            parts=lambda _t, _c=claim: coherence.parts(
                text=_t,
                claims=[{"claim_id": _c.get("claim_id", ""),
                         "text": _c.get("claim", ""),
                         "scope": _c.get("scope", "brand-wide")}]),
            redraft=_repair if basis == "model" else None,
            meta={"needs_art_direction": True, "basis": basis})
        if item["ok"]:
            # `item["body"]` and not `text`: a repair replaces the body, and
            # a board row built from the pre-repair draft would show the
            # variant that was thrown away — the exact drift `meta` being a
            # callable exists to prevent.
            board_rows.append({
                "n": len(board_rows) + 1, "output_id": item["output_id"],
                "angle": angle, "basis": basis,
                "needs_art_direction": True,
                "claim_ids": list(item["claim_ids"]),
                "claim": str(claim.get("claim") or ""),
                "text": item["body"], "dropped": False})

    if degraded_note:
        ctx.note(f"the model did not write these — {degraded_note}. What is "
                 f"filed is a grounded placeholder, not ad copy: every variant "
                 f"carries basis='composed'.")

    # THE BATCH IS AN ARTIFACT (UI overhaul 3.4, spec §3c). These variants
    # used to live only in run-detail JSON — "no surface shows them, so
    # nothing can be judged, edited, or regenerated". One ArtifactBody per
    # batch, anchored on the first kept variant's ledger row, holds the
    # reviewable set as JSON: /admin/work/<anchor> renders it as the variant
    # board, owner edits append versions, and the regenerate loop rewrites
    # the SAME row in place — so the version history and the draft-vs-current
    # story stay meaningful across regenerations. `draft_body` freezes the
    # machine's original batch (the workroom's virtual v1).
    #
    # `into_batch` marks a run the regenerate spawned to REFILL an existing
    # board: the caller merges these rows into that batch, and a second
    # board for the refill would state every variant twice.
    if board_rows and not str(ctx.params.get("into_batch") or "").strip():
        import json as _json
        _doc = _json.dumps(
            {"kind": "ad_batch", "entity_key": entity_key,
             "entity_label": _label, "audience_key": audience_key,
             "blocked_at_emit": len(ctx.items) - len(board_rows),
             "variants": board_rows}, ensure_ascii=False, indent=1)
        from . import db as _db
        with _db.SessionLocal() as s:
            s.add(_db.ArtifactBody(
                tenant=ctx.tenant, output_id=board_rows[0]["output_id"],
                run_id=ctx.run_id or "", system_key="ad_creative",
                format="ad_batch", destination="",
                # What this board IS, so it can be named in a list rather
                # than shown as "ad batch · 2026-08-28" beside four others.
                meta={"entity_key": entity_key, "entity_label": _label,
                      "audience_key": audience_key,
                      "variants": len(board_rows)},
                body=_doc, draft_body=_doc, bytes=len(_doc)))
            s.commit()
        ctx.note("the batch is on its variant board — judge, edit, drop and "
                 "regenerate it there")

    return {"summary": f"{len(ctx.items)} variant(s) ({', '.join(
                f'{n} {b}' for b, n in sorted(by_basis.items()))}), no imagery",
            "by_basis": by_basis, "angles": list(_ANGLES[:len(ctx.items)]),
            "board_rows": board_rows}


register(Skill(
    key="ad_copy",
    name="Ad copy",
    does="Draft ad copy variants from approved claims for one entity and "
         "audience. Copy only — imagery waits on the media layer, and each "
         "variant is flagged as needing art direction.",
    system_key="ad_creative",
    tier=3,
    needs=("rules.banned_claims",),
    # `revision_notes` + `into_batch` are the board's regenerate loop (3.4):
    # the digest rides the brief, and `into_batch` names the board the rows
    # will be merged into (so the refill run writes no second board).
    # `offer` and `deadline` are craft inputs, not decoration: the ruleset
    # measures WHERE the offer lands (the feed cuts at ~125 characters) and
    # refuses manufactured urgency when no deadline exists. Both are owner
    # input — a generator inventing a discount or a deadline is the one
    # failure here that costs real money.
    params=("entity_key", "entity_keys", "audience_key", "variants", "utterance",
            "revision_notes", "into_batch", "offer", "deadline",
            # awareness | interest | consideration | bottom — see app/funnel.py.
            # Optional: without it the stage is DERIVED, which briefs the
            # drafter with this account's own knowledge but does not narrow
            # the angles. Naming one is a decision and binds both.
            "funnel_stage",
            # THE HYPOTHESIS this batch tests, in one sentence. Optional, and
            # the run suggests ones the data supports when it is absent —
            # `funnel.proposals` builds them from the account's own claims,
            # objections and situations. Recorded on every row of the batch,
            # so "which positioning did better" is one GROUP BY.
            "positioning"),
    writes=False,
    produces="draft",
    # An ad is one-to-many in the same sense a campaign is.
    requires=("audience_key",),
    requires_when=_has_a_reader_to_pick,
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

THE ANGLE YOU CHOSE. When no angle was set for you, return the one you picked
as `"angle": "..."` alongside the subject and blocks — one short sentence
describing the IDEA, not the subject line. It is recorded on the run so a
person can read back what you decided and set it themselves next time. When an
angle WAS given to you, do not echo it back.

DO NOT BUILD A WORLDVIEW OUT OF ONE PRODUCT. Write about the thing in front of
you, not about what good taste is. "The Joke set is minimal and durable" is a
fact about a product. "A well-considered table doesn't announce itself" is a
theory of taste — and a catalogue that also sells maximalist ranges will have
to contradict it in the next send. A brand caught arguing both sides is
believed on neither. Sentences that begin "the trick of a good…", "the best
X…", "a well-considered Y…" are the shape to avoid: say it about the subject,
in the subject's name, or do not say it.

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
    from . import db, ledger
    out: list[dict] = []
    try:
        with db.SessionLocal() as s:
            rows = (s.query(db.Output)
                    .filter(db.Output.tenant == tenant,
                            db.Output.format == "campaign_email",
                            db.Output.angle == segment_key,
                            # `repaired` belongs here too, and its absence was
                            # costing the window silently. It marks an attempt
                            # the validator REJECTED and a later one replaced —
                            # never seen by anybody — and it is filed with an
                            # empty `theme` and `shape`. So it entered these
                            # four rows as a send with no intent and no layout,
                            # displacing a real one and teaching the drafter to
                            # vary from a draft that was thrown away.
                            db.Output.status.notin_(ledger.NOT_A_SEND))
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
    deadline = str(ctx.bundle.get("deadline") or "").strip()
    return email_craft.review(
        subject=copy.get("subject", ""), preheader=copy.get("preheader", ""),
        body=_blocks_text(blocks), intent=intent,
        asks=bool(CAMPAIGN_INTENTS.get(intent, {}).get("asks")),
        has_proof=any(b.get("type") in ("quote", "stat") for b in blocks),
        urgency_backed_by=deadline,
        # WHAT IS BEING SOLD, so a sentence that names it reads as a
        # description rather than as a theory of taste.
        featured=", ".join(e.get("name", "") for e in
                           (ctx.bundle.get("entities") or [])[:3]))


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
    # WHERE THE READER IS, DERIVED — not a fourth knob. `warmth` already
    # answers "does this cohort know us" and the intent already answers "does
    # this send ask", so the stage is a reading of two decisions that have
    # been made rather than a new one to make (design rule 4). The account's
    # own objections and situations are then quoted into the brief for that
    # stage, which is the owner's 2026-08-29 correction applied to email.
    stage = funnel.stage_from(
        warmth=warmth, asks=bool(CAMPAIGN_INTENTS.get(intent, {}).get("asks")))
    _reader_gap(ctx)
    plan = funnel.inputs_for(
        ctx.tenant, stage, claims=ctx.claims,
        objections=ctx.bundle.get("objections"),
        entities=ctx.bundle.get("entities"),
        audience=ctx.bundle.get("audience"),
        offer=str(ctx.bundle.get("offer") or ""))
    for n in plan.get("note") or []:
        ctx.note(f"funnel (thin): {n}")
    if plan.get("missing"):
        ctx.thin.extend(f"funnel:{m}" for m in plan["missing"])
    ctx.note(f"funnel stage: {plan['label']} — derived from a {warmth} list "
             f"on a{'n asking' if plan['asks'] else ' giving'} send")

    return {"intent": intent, "format": fmt, "warmth": warmth, "why": why,
            "funnel": plan,
            "deadline": str(ctx.bundle.get("deadline") or "").strip(),
            # A redraft's marching orders — set by the workroom's
            # Request-changes path, empty on a fresh draft. Rides `craft`
            # rather than a new drafter argument so every suite's stub
            # signature survives, and a stub can observe it.
            "revision_notes": str(ctx.params.get("revision_notes")
                                  or "").strip(),
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
    if craft.get("revision_notes"):
        # FIRST, because it outranks everything else here: the owner read
        # the previous version and sent it back with these.
        out.append("\n## THIS IS A REDRAFT — THE OWNER SENT THE LAST ONE "
                   "BACK\nFix every item below. These outrank the style "
                   "brief and the anti-repeat list:\n"
                   + str(craft["revision_notes"]))
    # THE READER, BEFORE THE PURPOSE. What this send is FOR only makes sense
    # after who is receiving it — and the account's own hesitations and
    # situations are what make "answer their doubt" a real instruction rather
    # than a category.
    if craft.get("funnel"):
        out.append(funnel.brief(craft["funnel"]))
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
        contested = bundle.get("contested_positioning") or []
        if contested:
            parts.append(
                "\n## THIS CATALOGUE ARGUES WITH ITSELF, ON PURPOSE\n"
                "Positions are filed against particular ranges here, not "
                "against the brand: "
                + "; ".join(f"{c.get('scope', '?')} — {c.get('claim', '')[:90]}"
                            for c in contested[:4])
                + "\nSo a sentence about what a good table, room or evening is "
                  "like will be contradicted by the next send. Write the "
                  "position of the thing you are selling, named as its own.")

        ents = bundle.get("entities") or []
        if ents:
            parts.append("\n## Products you may feature (cite by key — the "
                         "cards rendered under your copy will be exactly the "
                         "ones you pick):")
            for e in ents[:6]:
                parts.append(("- HERO " if e.get("hero") else "- ")
                             + f"[{e.get('key', '')}] {e.get('name', '')}: "
                               f"{e.get('description', '')}"[:220])
            if any(e.get("hero") for e in ents):
                parts.append(
                    "The HERO is what this email argues for. Its positioning "
                    "is the email's positioning. You may show the others as "
                    "companions — a complement, a pairing, a second option — "
                    "but do NOT make a second case for them: one email argues "
                    "one thing.")
        objs = bundle.get("objections") or []
        if objs:
            parts.append("\n## Hesitations you may answer:")
            for o in objs[:2]:
                parts.append(f"- {o.get('objection', '')}")
        parts.append(f"\n## Segment you are writing to:\n{seg['name']} — "
                     f"{seg.get('definition', '')}")
        # DIRECTION, NAMED AS DIRECTION. Handed over under a bare heading the
        # angle reads as copy, and a drafter short of a subject line will
        # reach for the nearest sentence it was given.
        _angle = (goal or "").strip()
        if _angle:
            parts.append(
                "\n## THE ANGLE — the idea this email is built around\n"
                + _angle
                + "\nThis is a brief written FOR you, not copy: never quote "
                  "it, never use it as the subject line, never paste it into "
                  "the body. Write the email this idea implies.")
        else:
            # NO ANGLE IS A JOB, NOT A GAP. Choosing one from the segment and
            # what is actually in stock is the thing a model is genuinely good
            # at, and demanding it up front made a person invent a concept
            # before anything could run.
            parts.append(
                "\n## NO ANGLE WAS SET — choose one\n"
                "Nobody has said what this email should be about. Decide it "
                "yourself from the segment above, the products you have been "
                "offered and the approved proof, and pick the one a person in "
                "that segment would actually open. Return it in `angle` as one "
                "short sentence describing the idea — not the subject line, "
                "the IDEA — so it can be read back and corrected.")
        parts.append(f"## The action to drive:\n{seg.get('angle', '') or 'one click to the product'}")
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


#: What the entity picker chose on the last campaign run — a test seam,
#: so a suite can tell a subject the PLAN named from one the picker did.
_last_ents: list = []

draft_campaign = _draft_campaign_live   # the seam the offline suite replaces


def _compose_campaign(bundle: dict, seg: dict, goal: str) -> dict:
    """The deterministic grounded fallback — dull, honest, provable offline."""
    claims = bundle.get("claims") or []
    ents = bundle.get("entities") or []
    top = claims[0] if claims else None
    proof = top["claim"].rstrip(". ") if top else ""
    # THE ANGLE IS NOT THE SUBJECT LINE. This read
    # `line = (goal or seg.get("angle") or ...)` and put it straight into both
    # `subject` and `headline` — so the internal brief written FOR the drafter
    # ("A reason to come back now, while the habit is recoverable and before a
    # win-back discount is needed") arrived in a customer's inbox as the
    # subject (owner, 2026-08-23). It is direction, and direction is never
    # copy. The composer cannot invent a line, so it uses what it actually
    # has: the thing being sold, or failing that the proof.
    _named = next((e.get("name", "") for e in ents if e.get("name")), "")
    line = _named or (proof.split(".")[0] if proof else "") or seg["name"]
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


def _legacy_blocks(copy: dict, ents: list, hero: dict | None,
                   default_cta_url: str = "") -> list:
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
        # THE DESTINATION IS OURS TO SUPPLY, on this path too. This read
        # `or "#"`, and "#" is precisely what `email_craft.dead_links` blocks —
        # so the COMPOSER, the deterministic fallback that exists to always
        # produce something shippable, produced an email that could never ship.
        # Every send with no model available died on a button the drafter was
        # never given the URL for (owner, 2026-08-22).
        blocks.append({"type": "cta", "label": copy["cta_label"],
                       "url": (copy.get("cta_url") or default_cta_url or "#")})
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
        return _legacy_blocks(copy, ents, hero, default_cta_url), []

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

#: THE ONE LINE THE DRAFT DOES NOT CROSS.
#:
#: Everything else wrong with an email — a dead button, an incoherent hero, a
#: missing address, merge tags that stayed neutral — is drafted into the ESP
#: marked, because the owner cannot judge what they cannot see and a draft
#: cannot send itself. These four are different in kind: an email carrying one
#: of them is not an imperfect email, it is a FALSE OR FORBIDDEN STATEMENT made
#: in the client's name. Putting it in the sending platform, one careless click
#: from a list, is the one case where withholding buys real safety rather than
#: only removing visibility. The run still says exactly what it was and why.
#:
#:   banned_claim        the brand has forbidden this phrase, usually in writing
#:   no_ban_list         nothing was checked at all, so "clean" is unfounded
#:   unbacked_urgency    a deadline nobody can point at — a lie, at scale
#:   unfit_entity_named  recommends something a customer cannot buy
#:   unapproved_offer    a discount nobody signed off, at list scale
WITHHOLD_FROM_ESP = frozenset({
    "banned_claim", "no_ban_list", "unbacked_urgency", "unfit_entity_named",
    "unapproved_offer"})


def _run_campaign_email(ctx: Context) -> dict:
    from . import (creative, email_craft, email_render, esp, fitness,
                   ledger, links, offers)
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
        # WHAT THIS BUYER IS FOR, before what the catalogue happens to list
        # first. Owner, 2026-09-01: *"some audiences are more associated with
        # different entities."* With no entity on the plan this offered the
        # catalogue's first six by "has a photograph, then alphabetically" —
        # and the note underneath admitted it. Alphabetical order is not a
        # judgement about who is reading; a recommendation somebody entered
        # is.
        #
        # ORDER IS THE RECOMMENDATION, so these are not re-sorted: the first
        # entity named for an audience is the one they are most for, and
        # re-sorting by photograph would put that decision back where it was.
        _aud_key = str((ctx.bundle.get("audience") or {}).get("key")
                       or ctx.params.get("audience_key") or "").strip()
        rec = _kb.audience_entities(ctx.tenant, _aud_key)
        if rec:
            ents = [_prod({"key": r.key, "name": r.name, "price": r.price,
                           "description": r.description or "",
                           "availability": r.availability or "",
                           "attributes": r.attributes or {}}) for r in rec[:6]]
            ctx.note(f"products: offered from what {_aud_key!r} is recommended "
                     f"for — " + ", ".join(e["name"] for e in ents))
        else:
            rows = _kb.entities(ctx.tenant, available_only=True)
            rows.sort(key=lambda r: (not (r.attributes or {}).get("image"),
                                     r.name or ""))
            ents = [_prod({"key": r.key, "name": r.name, "price": r.price,
                           "description": r.description or "",
                           "availability": r.availability or "",
                           "attributes": r.attributes or {}})
                    for r in rows[:6]]
            # SAID AT THE MOMENT OF CHOOSING, in both branches. The
            # explanation for this branch lived in a later note, after the
            # drafter — so a run that failed at drafting chose products by
            # guessing and said nothing about it, which is the one case where
            # somebody most needs to know a guess was made.
            if ents:
                ctx.note("products: nobody has said what this audience is "
                         "for, so the catalogue's top available items are "
                         "offered — set Featured entity on the plan, or "
                         "recommended entities on the audience, to choose "
                         "them")
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
    # NAME THE CAUSE, NOT THE SYMPTOM. `destinations` always includes the site
    # root when a domain is on file, so an empty `_cta_home` means one thing
    # and only one thing: this account has no domain. The run used to report
    # that as 'the "Shop now" button points nowhere', which reads as a drafting
    # mistake and sends whoever is fixing it to the wrong place — the drafter
    # is never given URLs and could not have supplied one. One field on the
    # account closes it, for every send.
    if not _cta_home:
        ctx.note("no storefront URL is on file for this account, so no link in "
                 "this email can point anywhere — set the domain on the "
                 "Connections tab and every future send fixes itself")
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
    # Which LIVE reads fed this email, as opposed to stored facts of unknown
    # age. The distinction is the whole of `ledger.perishable`: a claim is true
    # until somebody changes it, a reading was true when it was taken. The
    # entities below normally come from the SYNCED catalogue — a stored row,
    # not a reading — so this stays empty unless the sync actually runs in this
    # run and the email is written from what the store said just now.
    live_reads: list[str] = []
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
                # The store was read just now, so availability and price in
                # this email are a READING with a half-life, not a stored fact.
                live_reads.append("shopify_inventory")
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
    # THE HERO ENTITY — the one thing this email ARGUES FOR, decided before a
    # word is written.
    #
    # Owner, 2026-08-31: "It doesn't have to be one-email one-product. It just
    # needs to not mix up positioning between them. Maybe a hero product is a
    # better description." And: "this is going to be used for entities —
    # products is just a type of entity. It could be venues, digital
    # offerings, etc." So: hero ENTITY, and nothing here says product.
    #
    # An email may legitimately show several. What it may not do is argue
    # several positionings at once, and it was: the drafter was handed up to
    # six entities as a flat list, with nothing saying which one the email is
    # for, so it reasonably made a case for each and the email had no line.
    #
    # The hero is the plan's entity when the owner set one — the reviewed
    # instruction — and otherwise the catalogue's first offered row, which is
    # already ranked. Companions may still be shown; they simply do not bring
    # an argument of their own.
    _hero = str(ctx.params.get("entity_key") or "").strip() or next(
        (e.get("key", "") for e in ents if e.get("key")), "")
    # NOT narrowed here, and the measurement is why: `resolve` already scopes
    # claims by entity (`kb.claims` filters `entity_key.in_(["", None, key,
    # *ancestors])`), so a companion's proof CANNOT reach this bundle — with no
    # entity named the bundle carries brand-wide claims only. Re-filtering
    # against the hero would be a no-op dressed as a guarantee.
    _feat = {e.get("key", "") for e in ents if e.get("key")}
    _own = [c for c in ctx.claims if (c.get("scope") or "brand-wide") in _feat]
    if _hero:
        # Marked on the entity the drafter sees, so the prompt can say which
        # one carries the argument rather than leaving it to be inferred from
        # the order.
        for _e in ents:
            _e["hero"] = (_e.get("key") == _hero)
        _hero_name = next((e.get("name", "") for e in ents
                           if e.get("key") == _hero), _hero)
        ctx.note(f"hero: {_hero_name} — the positioning is its own; anything "
                 f"else shown is a companion and brings no argument of its "
                 f"own")
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

    # NO OFFER SET? USE THE ONE THIS BRAND ACTUALLY RUNS.
    #
    # A person fills the offer field so that no generator ever invents a
    # discount. But on an account that has been promoting for years, a blank
    # field does not mean there is no offer — it means nobody has typed the
    # history back in. `offers.applicable` ranks what this brand has ALREADY
    # SENT, so an existing brand starts with a shelf instead of a blank.
    #
    # A PROPOSED offer is still used, and the email is then HELD. That is the
    # same shape as an off-catalogue steer: the thing appears, it is named,
    # and it cannot ship until a person decides — which is a better offer to
    # the owner than a blank field they have to guess at, and safer than a
    # drafter left free to invent one.
    derived_offer: dict = {}
    if not str(ctx.bundle.get("offer") or "").strip():
        _got = offers.applicable(
            ctx.tenant, segment=seg["key"],
            entity_keys=[e.get("key", "") for e in ents])
        if _got.get("ok"):
            ctx.bundle["offer"] = _got["offer"]
            if _got["usable"]:
                ctx.note(f"no offer was set, so the one this brand runs is "
                         f"used: \u201c{_got['offer'][:90]}\u201d — "
                         f"{_got['why']}")
            else:
                derived_offer = _got
                ctx.note(f"no offer was set, so a PROPOSED offer was used: "
                         f"\u201c{_got['offer'][:90]}\u201d ({_got['why']}). "
                         f"It is not approved, so this email cannot be "
                         f"published until you approve that offer.")

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
    # WHAT IT DECIDED, SAID OUT LOUD. An angle the system chose for itself is
    # a decision the owner never made, so it is reported rather than left to be
    # inferred from the copy — and it is the thing they would want to correct
    # on the plan next time.
    chosen_angle = str(copy.get("angle") or "").strip()
    if chosen_angle and not goal:
        ctx.note(f"no angle was set, so the drafter chose one: {chosen_angle}")
    elif goal:
        ctx.note(f"angle from the plan: {goal[:120]}")
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
            # NAME WHICH GUESS THIS WAS. "Nobody chose" and "the audience's
            # recommendation stood" are different situations and the fix for
            # each is different: the first wants a Featured entity on the
            # plan, the second is already somebody's decision and wants
            # nothing.
            ctx.note("products: no entity on the plan and no drafter choice — "
                     + (f"the recommendation on {_aud_key!r} stood"
                        if _aud_key and _kb.audience_entities(ctx.tenant,
                                                              _aud_key)
                        else "the catalogue's top available items are "
                             "featured; set Featured entity on the plan, or "
                             "recommended entities on the audience, to choose "
                             "them"))
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
    # WHAT THE PICKER CHOSE, kept so a suite can tell a plan's subjects from
    # the drafter's. Without it an assertion about the plan passes whenever
    # the picker happened to return the same room, which is how this went
    # [ MISSED ] on 2026-08-31.
    global _last_ents
    _last_ents = list(ents)
    # WHAT THE OWNER SAID THE SEND IS ABOUT, on top of what the drafter
    # featured. `also` was whatever `ents` happened to hold, so an email
    # covering three rooms was only as multi-subject as the picker made it.
    # A plan naming them is the reviewed instruction and outranks that.
    from . import systems as _sysm
    _named = _sysm.entity_list(ctx.params.get("entity_keys") or "")
    if _subject:
        _sub_name = next((e.get("name", "") for e in ents
                          if e.get("key") == _subject), _subject)
        _also = [e.get("key", "") for e in ents if e.get("key") != _subject]
        for k in _named:
            if k != _subject and k not in _also:
                _also.append(k)
        commitment = coherence.commit(
            "entity", _subject, label=_sub_name, audience=seg["key"],
            action=goal or seg.get("angle", ""), also=_also,
            # A group's claim is true of its members, so the ancestor chain of
            # everything featured is legitimate proof — but a group is not a
            # thing that may appear on a product card, which is why it lands
            # here and not in `also`.
            # A group's claim is true of its members, so the ancestor chain
            # of everything featured is legitimate proof — but a group is not
            # a thing that may appear on a card, which is why it lands here
            # and not in `also`.
            proof_scopes=[_subject] + _also + [
                a for k in [_subject] + _also
                for a in _kb.ancestors(ctx.tenant, k)])
    else:
        # No product at all is a legitimate email — a story, a letter. It has
        # no entity subject, so the subject checks are vacuous; the proof and
        # image checks still hold, and those are the ones that matter here.
        commitment = coherence.commit(
            "audience", seg["key"], audience=seg["key"],
            action=goal or seg.get("angle", ""),
            # A letter with no product subject may still be ABOUT several
            # rooms, and the plan is where that was said. Without this the
            # gate reads every venue fact in it as proof borrowed from
            # somewhere else.
            proof_scopes=(_named + [a for k in _named
                                    for a in _kb.ancestors(ctx.tenant, k)])
            or None)
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
                + (" — photos exist, so this is the layout, not the data"
                   if _with else
                   " — no product photos are on file; the store sync runs "
                   "before every send and found none, so they need adding "
                   "to the store itself (or the photo library)")
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
        # WHICH PRODUCT WENT TO WHICH LIST. Both columns existed and neither
        # was written for a campaign, so the ledger held every email ever sent
        # and could not answer the first question anybody asks of it: what have
        # we already pushed at these people, and how recently. `ad_copy` has
        # passed both since it was written; this path never did.
        #
        # `_subject` is what somebody actually CHOSE — the plan's entity or the
        # drafter's — and is deliberately empty for a letter that features no
        # product, which is a real state and not a gap to be filled in.
        entity_key=_subject, audience_key=seg["key"],
        # The intent, in its own indexed column rather than only inside
        # `theme`. `theme` is `"{intent}|{format}"` and answering "how often
        # has this list been given to rather than asked" from it means a
        # string split across every row in the period. It is the same fact,
        # filed where it can be grouped by.
        situation=craft.get("intent", ""),
        # The photograph that CARRIED it. Read from the FINAL blocks, after
        # the repair loop, for the same reason `shape` is.
        #
        # Both current formats list `hero`, so today this cannot differ from
        # "an asset was chosen" — the condition is defensive, not load-bearing,
        # and no sabotage entry claims otherwise. It is here because the moment
        # a format omits `hero` (a plain-text send is the obvious one) the
        # difference becomes real and silent: an asset would be credited, its
        # `uses` counter incremented, and "which picture worked" answered with
        # a photograph nobody ever received.
        media_ids=lambda: ([hero_got["asset_id"]]
                           if hero_got.get("asset_id") and hero
                           and any(b.get("type") == "hero"
                                   for b in state["blocks"]) else []),
        # Only reads actually taken in this run — see `live_reads` above.
        lookups=list(live_reads),
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
        meta=lambda: {"angle": chosen_angle or goal,
                      "angle_chosen_by": ("drafter" if chosen_angle and not goal
                                          else "plan" if goal else ""),
                      "subject": state["copy"].get("subject", ""),
                      "preheader": state["copy"].get("preheader", ""),
                      "html": state["html"], "segment": seg["key"],
                      # WHO IT WAS WRITTEN FOR, on the artifact. The redraft
                      # rebuilds the call from this meta, and `audience_key` is
                      # required now — without it here there is nowhere to read
                      # the reader back from, because `Output.audience_key`
                      # carries the SEGMENT for a campaign.
                      "audience_key": str(ctx.params.get("audience_key") or ""),
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

    # A DERIVED OFFER NOBODY APPROVED, AND THE COPY ACTUALLY STATES IT.
    #
    # Checked against the words rather than assumed from the parameter, for
    # the same reason `named_unfit` reads the copy: a drafter handed an offer
    # it chose not to mention must not hold the send over one. `offer_position`
    # is the check `ad_craft` already uses to find an offer in a body, so the
    # question "is it in there" has one answer in this codebase, not two.
    if derived_offer and ad_craft.offer_position(
            to_check, derived_offer["offer"]) >= 0:
        hard.append({
            "severity": "block", "rule": "unapproved_offer",
            "detail": (f"this email states an offer that is proposed and not "
                       f"approved: \u201c{derived_offer['offer'][:110]}\u201d"),
            "fix": ("approve that offer on Review, or set the real one on the "
                    "plan — an unapproved discount going out over the "
                    "client's sending domain is the one mistake here that "
                    "costs money")})

    _all_ents = _kb.entities(ctx.tenant, available_only=False)
    _named = fitness.named_unfit(_model, to_check, _all_ents)
    for n in _named:
        hard.append({"severity": "block", "rule": "unfit_entity_named",
                     "detail": f"the email recommends {n['name']}, but "
                               f"{n['why']}",
                     "fix": "fix it in the store, or send an email that does "
                            "not name it"})
    if hard:
        ctx.note("this draft is not fit to launch as it stands: "
                 + "; ".join(f["detail"] for f in hard))

    # HELD FOR YOUR REVIEW — the ESP draft is made at APPROVAL, never here.
    #
    # The previous policy drafted into the ESP the moment there was HTML,
    # because the console had no preview surface and withholding the draft
    # took away the only view the owner had of the work (2026-08-22: "how
    # else will I see it and send it?" — the [NEEDS FIX] campaign-name
    # convention was that policy's warning label). The WORKROOM is that view
    # now, and the owner inverted the flow with it (2026-08-27): "we want to
    # have a preview before it gets sent over so that the feedback on
    # changes / entire plan adjustment that may be needed can happen in the
    # data layer that we have access to as opposed to in the ESP."
    #
    # So: the artifact is kept whole in OUR store (ledger writes
    # ArtifactBody), the review — preview, feedback, subject/preheader
    # adjustment, redraft — happens in the workroom against our own data
    # layer, and `push_campaign_to_esp` below is the ONLY code that writes a
    # campaign into a client's platform, called by the approval executor.
    # Nothing sits in a client's ESP that the owner has not approved.
    defects = [f["detail"] for f in hard]
    if not item.get("ok"):
        defects += [f["detail"] for f in (item.get("failures") or [])]
    if not native_ok:
        defects.append("merge tags stayed neutral — "
                       + (state["native_why"] or "no ESP personalization"))
    defects += list(missing)

    _forbidden = [f for f in (hard + list(item.get("failures") or []))
                  if str(f.get("rule", "")) in WITHHOLD_FROM_ESP]
    if _forbidden:
        ctx.note("will NEVER be pushed to the ESP — this email would state "
                 "something false or forbidden in the client's name: "
                 + "; ".join(f["detail"] for f in _forbidden))

    esp_draft = {}
    # Segment binding is COMPUTED here — so the workroom can warn about an
    # untargeted send while there is still time to fix it — and USED at push
    # time. Remembered id first, live name-match second, named absence third.
    from . import segments as segmod
    esp_target = segmod.esp_id_for(ctx.tenant, seg["key"])
    if not esp_target.get("id"):
        ctx.note("the campaign is untargeted so far — " + esp_target.get("why", ""))
    elif esp_target.get("why"):
        ctx.note(esp_target["why"])

    # Everything the approval-time push needs, in one recipe. It rides in
    # two places: on the ARTIFACT (the machine's stash, below) and on the
    # pending APPROVAL (the owner-editable mirror the workroom's adjust form
    # writes — the push prefers it, so what the owner changed is what the
    # client's platform receives).
    _prov = esp.provider_for(ctx.tenant) or "none"
    _push_recipe = ({
        "provider": _prov,
        "subject": copy.get("subject", ""),
        "preheader": copy.get("preheader", ""),
        "sender_name": theme["name"],
        "segment_key": seg["key"],
        "segment_id": esp_target.get("id") or "",
        "hero_asset_id": hero_got.get("asset_id") or ""}
        if final_html and not _forbidden else {})

    # THE ARTIFACT THE WORKROOM REVIEWS — the rendered email, kept whole in
    # our store. `emit` records the validated COPY on the ledger; the HTML is
    # only final HERE, after render, personalization and rehosting — so this
    # is its one writer. `draft_body` freezes on first write (v1, the
    # workroom's virtual first version); `body` is what the push sends.
    if final_html:
        from . import db as _db
        with _db.SessionLocal() as s:
            _row = (s.query(_db.ArtifactBody)
                    .filter(_db.ArtifactBody.output_id == item["output_id"])
                    .first())
            # WHAT THIS EMAIL IS, on the artifact. `ledger.record` carries
            # `meta` for everything it writes, and this path is its own
            # writer — so a campaign was the one artifact with no identity
            # on it, and the Drafts index named three of them "campaign
            # email · 2026-08-28" (owner, 2026-08-28). `item["meta"]` is the
            # dict `emit` already resolved after the repair loop.
            _meta = dict(item.get("meta") or {})
            if _row is None:
                s.add(_db.ArtifactBody(
                    tenant=ctx.tenant, output_id=item["output_id"],
                    run_id=ctx.run_id or "", system_key="campaign_email",
                    format="campaign_email", destination="",
                    body=final_html, draft_body=final_html, meta=_meta,
                    bytes=len(final_html), push=_push_recipe))
            else:
                _row.body = final_html
                if not (_row.draft_body or ""):
                    _row.draft_body = final_html
                _row.bytes = len(final_html)
                _row.meta = {**(_row.meta or {}), **_meta}
                _row.push = _push_recipe
            s.commit()

    if _push_recipe:
        from . import approvals as _appr
        _appr.attach_esp_push(ctx.run_id, _push_recipe)

    # WHERE IT STANDS. The destination column names a state somebody can act
    # on: held for the workroom's review, withheld outright, or nothing to
    # hold. A campaign id lands here only when the push actually creates one.
    if _forbidden:
        _landed = f"esp:{_prov}:withheld"
    elif final_html:
        _landed = f"esp:{_prov}:held-for-review"
    else:
        _landed = f"esp:{_prov}:not-drafted"
    ledger.delivered(ctx.tenant, item["output_id"], _landed)

    # AN APPROVAL IS A QUESTION ABOUT SOMETHING PUSHABLE. Defective or
    # forbidden copy withdraws it — the workroom still shows the artifact and
    # its defects, feedback still files, but nothing offers to put it in a
    # client's platform until a redraft comes back clean.
    if defects or _forbidden or not final_html:
        why = ("; ".join(f["detail"] for f in _forbidden) if _forbidden
               else "; ".join(defects) if defects
               else "no HTML was produced")
        from . import approvals as _appr
        if _appr.withdraw(ctx.run_id, why):
            ctx.note("the approval was withdrawn — not fit to push as it "
                     "stands: " + why + ". Review it in the workroom; a "
                     "clean redraft re-queues it.")

    # RECORDED SO IT CAN STOP HAPPENING. Every defect goes on the run, where
    # `systems.blocked_reasons` ranks it by how often it actually cost a send —
    # which is the difference between "an email needed fixing once" and "this
    # account has no storefront URL on file and every send has been landing
    # with a dead button". Coherence rules stay namespaced and out of that
    # ranking; these are exactly the kind that belong in it.
    if defects:
        _rules = ([f["rule"] for f in hard]
                  + [f["rule"] for f in (item.get("failures") or [])
                     if not item.get("ok")]
                  + (["personalize_failed"] if not native_ok else [])
                  + (["theme_incomplete"] if missing else []))
        systems.record_defects(ctx.run_id, _rules)
        ctx.note("recorded so it can be fixed at the source: "
                 + ", ".join(dict.fromkeys(_rules)))

    return {"summary": (f"campaign email for '{seg['name']}' — {basis}, "
                        + ("sendable" if not missing else "not yet sendable")
                        + (", hero image" if hero else ", no hero image")
                        + (", NOT PUSHABLE (false or forbidden): "
                           + "; ".join(f["detail"] for f in _forbidden)[:120]
                           if _forbidden
                           else ", held for your review — approving pushes "
                                "it to the ESP"
                           if final_html and not defects
                           else ", held with defects — fix before it can "
                                "be approved: " + "; ".join(defects)[:120]
                           if final_html
                           else ", no HTML was produced")),
            "defects": defects,
            "segment": seg, "basis": basis, "cited_claims": cited,
            "hero": {"basis": hero_got.get("basis", ""),
                     "asset_id": hero_got.get("asset_id", ""),
                     "drafted": hero_got.get("drafted", {})},
            "esp_target": esp_target,
            "esp_draft": esp_draft, "html_bytes": len(final_html)}


def push_campaign_to_esp(tenant: str, output_id: str) -> dict:
    """Create the ESP draft for an APPROVED campaign — the ONLY ESP write.

    Called by the approval executor (and the workroom's retry button). Reads
    what the emit stashed on the approval — subject, preheader, sender,
    segment binding — which is also where the workroom's pre-push edits land,
    so what the owner adjusted in our data layer is exactly what reaches the
    platform. Idempotent by destination: a campaign already pushed returns
    its id instead of drafting a twin.
    """
    from . import db, esp, ledger
    with db.SessionLocal() as s:
        art = (s.query(db.ArtifactBody)
               .filter(db.ArtifactBody.output_id == output_id).first())
        out = s.get(db.Output, output_id)
        push = {}
        latest_status = ""
        approval_id = ""
        held_defects: list = []
        run_decision = ""
        run_id = art.run_id if art is not None else ""
        if run_id:
            aprs = (s.query(db.Approval)
                    .filter(db.Approval.run_id == run_id)
                    .order_by(db.Approval.created_at.desc()).all())
            latest_status = aprs[0].status if aprs else ""
            approval_id = aprs[0].id if aprs else ""
            for apr in aprs:
                got = (apr.payload or {}).get("esp_push")
                if got:
                    push = dict(got)
                    break
            run = s.get(db.SystemRun, run_id)
            if run is not None:
                held_defects = list(run.blocked_on or [])
                run_decision = run.decision or ""
        s.expunge_all()
    # THE REVIEW'S VERDICT BINDS THE PUSH — this function must never be a
    # side door around it. A withdrawn approval, or defects recorded on the
    # run with no approval in sight, both mean "not fit to push as it
    # stands"; a clean redraft re-queues a fresh approval and lifts this.
    if latest_status == "withdrawn" or (
            held_defects and run_decision != "approved"):
        return {"ok": False,
                "error": "the review withdrew this campaign — not fit to "
                         "push as it stands"
                         + (f" ({'; '.join(held_defects[:3])})"
                            if held_defects else "")
                         + "; a clean redraft re-queues it"}
    if art is None or not (art.body or "").strip():
        return {"ok": False,
                "error": "no artifact HTML is kept for this campaign — "
                         "nothing to push"}
    # The approval's copy first — that is where the workroom's edits land —
    # falling back to the machine's stash on the artifact.
    push = push or dict(getattr(art, "push", None) or {})
    if not push:
        return {"ok": False,
                "error": "no push recipe — this campaign was withheld "
                         "(false or forbidden) or predates review-"
                         "before-push; a clean redraft supplies one"}
    already = (getattr(out, "destination", "") or "")
    if ":campaign/" in already:
        return {"ok": True, "provider": already.split(":")[1],
                "campaign_id": already.split(":campaign/")[-1],
                "note": "already in the ESP — not drafted twice"}
    mod, refusal = esp.backend(tenant)
    if refusal:
        return {"ok": False, "error": refusal}
    prov = esp.provider_for(tenant) or "esp"
    include = [push["segment_id"]] if push.get("segment_id") else None
    try:
        esp_draft = mod.draft_from_html(
            tenant, name=(push.get("subject") or "campaign")[:120],
            subject=push.get("subject", ""),
            sender_name=push.get("sender_name", ""),
            html=art.body, preheader=push.get("preheader", ""),
            include_segments=include)
    except Exception as exc:                                     # noqa: BLE001
        return {"ok": False,
                "error": f"the ESP raised {exc.__class__.__name__}: "
                         f"{str(exc)[:160]}"}
    if not esp_draft.get("ok"):
        return {"ok": False,
                "error": esp_draft.get("error", "the ESP rejected the draft")}
    landed_note = ""
    try:
        ledger.delivered(tenant, output_id,
                         f"esp:{prov}:campaign/{esp_draft.get('campaign_id')}")
    except Exception as exc:                                     # noqa: BLE001
        # The draft EXISTS in the platform; hiding a failed ledger write
        # would make our record disagree with reality silently — the exact
        # intention-vs-outcome confusion `delivered` was built to end.
        landed_note = (f"draft created, but recording it failed "
                       f"({exc.__class__.__name__}) — the ledger still says "
                       f"held-for-review")
    # WHAT A PERSON HAD TO CHANGE, measured at the moment it leaves.
    #
    # `SystemRun.edit_diff` is the number the Measured section is built from —
    # "the share of sends nobody had to touch" — and for a campaign it had no
    # producer at all: `edits.record` has two call sites and both are Gmail, so
    # a campaign approval (kind="skill_output") never reached either. The tab
    # has been structurally empty for this system since it was written.
    #
    # The comparison is `draft_body` against `body`: what we first produced
    # against what the owner approved after the workroom's edits. The declared
    # measure used to be "generated HTML vs the ESP draft at launch", which
    # cannot be taken — `omnisend.campaign()` returns status, name, sent_at and
    # segment ids, and no content. Measuring what we can actually see beats
    # declaring a measure nobody can compute, and this is the better number
    # anyway: it is exactly "did a human have to touch it".
    # Against the RUN, not the approval: a campaign on the shadow or auto rung
    # has no approval behind it, and requiring one to measure would leave the
    # systems trusted most as the ones nobody can check. The approval is still
    # updated when there is one, so "what happened to this draft" is answerable
    # from either end.
    if (art.draft_body or "").strip():
        try:
            from . import claim_trace as _ct
            from . import edits as _edits
            # OVER THE READABLE TEXT, not the markup. `edits.delta` is a line
            # diff, and an email body is one long line of HTML — so the sample
            # on the Measured list was the doctype and a wall of table tags,
            # which tells a reader nothing about what a person changed. The
            # question is "did a human have to touch the WORDS".
            _was, _now = (_ct.plain_text(art.draft_body or ""),
                          _ct.plain_text(art.body or ""))
            _edits.record_run(run_id, _was, _now)
            if approval_id:
                _edits.record(approval_id, _was, _now)
        except Exception:                                        # noqa: BLE001
            pass    # measurement must never fail a push that already happened

    if push.get("hero_asset_id"):
        # The photograph actually reached a drafted campaign — the explicit
        # act the creative library's `uses` counter exists for.
        try:
            from . import kb as _kb
            _kb.mark_asset_used(push["hero_asset_id"],
                                destination="campaign_email draft")
        except Exception:                                        # noqa: BLE001
            pass
    got = {"ok": True, "provider": prov,
           "campaign_id": esp_draft.get("campaign_id", "")}
    if landed_note:
        got["note"] = landed_note
    if esp_draft.get("images_not_rehosted"):
        got["images_not_rehosted"] = esp_draft["images_not_rehosted"]
    return got


def _prior_run_id(output_id: str) -> str:
    """The run that produced an output, so superseding it withdraws its
    approval too. An approval left standing on a replaced draft is a button
    that publishes the page the replacement was written to replace."""
    from . import db
    with db.SessionLocal() as s:
        art = (s.query(db.ArtifactBody)
               .filter(db.ArtifactBody.output_id == output_id).first())
        return (art.run_id or "") if art is not None else ""


def supersede(tenant: str, output_id: str, new_oid: str, *,
              keyword_id: str = "", run_id: str = "",
              close_feedback: bool = False, why: str = "redraft") -> None:
    """Retire one output in favour of its replacement. ONE WRITER.

    SUPERSEDE, NEVER DUPLICATE: one intent keeps one live row. The old item
    stays readable — its workroom page names the successor — but it leaves
    every queue, every count and the anti-repeat window, its pending approval
    is withdrawn, and the keyword's pointer moves to the living draft.

    Extracted because a second caller arrived. A refresh writes the same
    article again, and the half-dozen writes that make a replacement a
    replacement rather than a second page were written out longhand inside
    the workroom redraft. Copied to the new caller they would have drifted;
    the version that drifts is always the one that stops withdrawing the old
    approval, which leaves two live articles queued for one keyword.

    `close_feedback` is the workroom's alone: the notes are marked applied
    because that redraft consumed them. A planner-driven refresh consumed
    nobody's notes and must not close them.
    """
    from . import approvals as _appr
    from . import db, ledger

    with db.SessionLocal() as s:
        old = s.get(db.Output, output_id)
        if old is not None:
            old.status = "superseded"
        old_art = (s.query(db.ArtifactBody)
                   .filter(db.ArtifactBody.output_id == output_id).first())
        if old_art is not None and (old_art.state or "") == "in_review":
            old_art.state = ""
        if close_feedback:
            for f_row in (s.query(db.FeedbackItem)
                          .filter(db.FeedbackItem.output_id == output_id,
                                  db.FeedbackItem.level == "draft",
                                  db.FeedbackItem.status == "open").all()):
                f_row.status = "applied"
                f_row.applied_at = db.utcnow()
        if keyword_id:
            kw_row = s.get(db.KeywordTarget, keyword_id)
            if kw_row is not None:
                # The board's draft link must point at the LIVING draft.
                kw_row.output_id = new_oid
        s.commit()
    try:
        ledger.delivered(tenant, output_id, f"superseded:{new_oid}")
    except Exception:                                            # noqa: BLE001
        pass
    if run_id:
        _appr.withdraw(run_id, f"superseded by {why} -> {new_oid}")


def redraft_artifact(tenant: str, output_id: str, note: str = "",
                     overrides: dict | None = None, part: str = "") -> dict:
    """Request changes: redraft one held artifact, consuming its feedback.

    The workroom's loop, closed. Open draft-level FeedbackItems (plus the
    note typed at the button, plus any plan-field overrides — segment,
    entity, intent, deadline, angle) become the drafter's marching orders
    via `revision_notes`; the skill runs FRESH through every gate, and the
    old item is SUPERSEDED, never edited in place: old Output → status
    "superseded" with its destination naming the successor, old approval
    withdrawn, feedback marked applied. One intent, one live row — the
    substrate's own vocabulary for a replaced attempt, applied at the
    artifact level.
    """
    from . import approvals as _appr
    from . import db, ledger, skill as _skill
    overrides = dict(overrides or {})
    with db.SessionLocal() as s:
        art = (s.query(db.ArtifactBody)
               .filter(db.ArtifactBody.output_id == output_id).first())
        out = s.get(db.Output, output_id)
        run = s.get(db.SystemRun, art.run_id) if art and art.run_id else None
        fb = (s.query(db.FeedbackItem)
              .filter(db.FeedbackItem.output_id == output_id,
                      db.FeedbackItem.level == "draft",
                      db.FeedbackItem.status == "open").all())
        kw = (s.query(db.KeywordTarget)
              .filter(db.KeywordTarget.output_id == output_id).first())
        s.expunge_all()
    if art is None:
        return {"ok": False, "error": "no artifact with that id"}
    if ":campaign/" in (getattr(out, "destination", "") or ""):
        return {"ok": False,
                "error": "already pushed to the ESP — redraft the NEXT send "
                         "instead; a draft in the platform is edited there"}
    if (getattr(out, "status", "") or "") == "published" or (
            kw is not None and (kw.status or "") in ("published", "won")):
        return {"ok": False,
                "error": "already published — a live page gets a revision "
                         "through the revision path, not a redraft of the "
                         "draft it came from"}

    # THE TYPED NOTE IS FILED, NOT WHISPERED.
    #
    # It used to be appended to the digest and never persisted: it never
    # appeared in the thread, could not be reinforced, and was destroyed on
    # every refused click — which is exactly what happened throughout the
    # redraft outage this week. `feedback_add`'s own principle is that a
    # feedback store nothing reads is a complaint box; the inverse is what
    # this did — a judgement nothing stores is a shout.
    #
    # Filing BEFORE running is the point rather than a side effect: a redraft
    # that then refuses leaves the note filed and open, so nothing typed is
    # ever lost to a refusal.
    #
    # Inside `redraft_artifact` rather than in the route, so a direct caller
    # behaves identically to a click.
    if (note or "").strip():
        with db.SessionLocal() as s:
            s.add(db.FeedbackItem(
                tenant=tenant, output_id=output_id,
                part=str(part or "overall"), category="",
                note=str(note).strip(), level="draft", status="open"))
            s.commit()
            fb = (s.query(db.FeedbackItem)
                  .filter(db.FeedbackItem.output_id == output_id,
                          db.FeedbackItem.level == "draft",
                          db.FeedbackItem.status == "open").all())
            s.expunge_all()

    lines = [f"[{f.part} · {f.category or 'general'}] {f.note}" for f in fb]
    if not lines:
        return {"ok": False,
                "error": "nothing to redraft from — file feedback or type a "
                         "note; a redraft with no direction is a reroll"}
    digest = "\n".join(f"- {ln}" for ln in lines)

    brief = dict(run.brief) if run is not None and isinstance(
        run.brief, dict) else {}
    fmt = art.format or ""
    if fmt == "campaign_email":
        params = {
            "segment": (overrides.get("segment")
                        or getattr(out, "audience_key", "") or
                        brief.get("segment", "")),
            "entity_key": (overrides.get("entity_key")
                           or brief.get("entity_key", "")
                           or getattr(out, "entity_key", "") or ""),
            "intent": (overrides.get("intent")
                       or getattr(out, "situation", "") or ""),
            "deadline": (overrides.get("deadline")
                         or brief.get("deadline", "") or ""),
            "goal": overrides.get("goal") or brief.get("goal", "") or "",
            "subject": overrides.get("subject") or brief.get("subject", ""),
            # WHO IT IS WRITTEN FOR. `campaign_email` requires this now
            # (c4f72cc), and this caller never supplied it — so on any account
            # with an approved persona every Request-changes click was refused
            # before the bundle was even resolved. The commit that added the
            # requirement claimed this door was covered. It was not.
            #
            # NEVER from `out.audience_key`: that column carries the SEGMENT
            # for a campaign, which is why line 3257 already uses it as the
            # segment fallback. The artifact's meta is where the reader is.
            "audience_key": (overrides.get("audience_key")
                             or (getattr(art, "meta", None) or {})
                             .get("audience_key") or ""),
            "revision_notes": digest}
        skill_key = "campaign_email"
    elif fmt == "cms_article" or kw is not None:
        if kw is None:
            return {"ok": False,
                    "error": "no keyword row joins this article — nothing "
                             "names what a redraft should target"}
        params = {"keyword": kw.phrase,
                  "role": overrides.get("role") or kw.role or "",
                  "cluster": kw.cluster_key or "",
                  "angle": (overrides.get("angle")
                            or getattr(out, "angle", "") or ""),
                  "entity_key": (overrides.get("entity_key")
                                 or getattr(out, "entity_key", "") or ""),
                  "revision_notes": digest}
        skill_key = "blog_article"
    elif fmt == "ad_batch":
        # The board regenerates IN PLACE — its own tail, not the supersede
        # flow below: a batch is a SET with per-variant judgement, and the
        # kept variants must survive exactly as reviewed.
        return _regenerate_ad_batch(tenant, output_id, art, fb, digest,
                                    overrides)
    else:
        return {"ok": False,
                "error": f"no redraft path for format {fmt!r} yet"}

    params = {k: v for k, v in params.items() if str(v or "").strip()}
    r = _skill.run(skill_key, tenant, **params)
    new_item = next((i for i in (r.get("items") or [])
                     if i.get("output_id")), None)
    if new_item is None:
        # NAME THE REFUSAL. `blocked_on` is the one field that says which
        # parameter or rule stopped it, and this threw it away — so a redraft
        # refused for a missing reader read only as the bare word "blocked",
        # which is a dead end for whoever has to fix it. `_regenerate_ad_batch`
        # already reports it this way.
        return {"ok": False,
                "error": "the redraft produced nothing — "
                         + (("; ".join(r.get("blocked_on") or [])
                             or str(r.get("summary")
                                    or r.get("status") or "unknown"))[:200])}
    new_oid = new_item["output_id"]

    supersede(tenant, output_id, new_oid, keyword_id=(kw.id if kw else ""),
              run_id=art.run_id or "", close_feedback=True,
              why="redraft (workroom)")
    return {"ok": True, "output_id": new_oid, "consumed": len(fb),
            "summary": (r.get("summary") or "")[:200]}


def _regenerate_ad_batch(tenant: str, output_id: str, art, fb: list,
                         digest: str, overrides: dict) -> dict:
    """Regenerate an ad batch from its feedback — kept variants survive.

    A batch is a SET with per-variant judgement, so it does not supersede
    wholesale the way an email or an article does. The board (its
    ArtifactBody) keeps its identity and its version history — that is what
    makes versions and the draft-vs-current story meaningful — and
    supersession happens at the VARIANT level: every replaced variant's
    ledger row closes with a pointer to its replacement and its pending
    approval is withdrawn, while kept variants' rows, owner edits and
    approvals are untouched.

    Dropped variants name what gets replaced. With nothing dropped, the
    whole batch is redrafted — Request-changes with no drops is a judgement
    about all of it. The `superseded:`-prefixed destination is deliberately
    NOT used here: the board's anchor row can itself be a replaced variant,
    and the board must never render as a superseded PAGE.
    """
    import json as _json

    from . import approvals as _appr
    from . import db, skill as _skill
    try:
        batch = _json.loads(art.body or "")
        variants = list(batch.get("variants") or [])
        if not variants:
            raise ValueError("no variants")
    except Exception:                                            # noqa: BLE001
        return {"ok": False, "error": "the batch record is unreadable — "
                                      "nothing names its variants"}

    dropped = [v for v in variants if v.get("dropped")]
    kept = [v for v in variants if not v.get("dropped")] if dropped else []
    replaced = dropped if dropped else variants

    notes = digest
    if kept:
        notes += ("\n\nThese variants were KEPT and will run beside yours — "
                  "do not repeat their lines:\n"
                  + "\n".join("- " + str(v.get("text") or "")[:200]
                              for v in kept))

    r = _skill.run("ad_copy", tenant,
                   entity_key=(overrides.get("entity_key")
                               or batch.get("entity_key") or ""),
                   audience_key=(overrides.get("audience_key")
                                 or batch.get("audience_key") or ""),
                   variants=max(1, min(5, len(replaced))),
                   revision_notes=notes, into_batch=output_id)
    rows = list((r.get("detail") or {}).get("board_rows") or [])
    if not rows:
        # Rule 7: a refusal names its reason where the button was. A blocked
        # run's reasons live in blocked_on; "blocked" alone sends the owner
        # hunting through Diagnostics for what this line could have said.
        why = ("; ".join(r.get("blocked_on") or [])
               or str(r.get("summary") or r.get("status") or "unknown"))
        return {"ok": False,
                "error": "the regenerate produced nothing that cleared the "
                         "gates — " + why[:220]}

    with db.SessionLocal() as s:
        # Emit order pairs each replaced slot with its replacement; a slot
        # the refill could not clear closes without a successor and the
        # return says so.
        for i, v in enumerate(replaced):
            _o = s.get(db.Output, str(v.get("output_id") or ""))
            if _o is not None:
                _o.status = "superseded"
                _o.destination = ("replaced-in-batch:"
                                  + (rows[i]["output_id"]
                                     if i < len(rows) else ""))
        gone = {str(v.get("output_id") or "") for v in replaced}
        for apr in (s.query(db.Approval)
                    .filter(db.Approval.tenant == tenant,
                            db.Approval.status == "pending").all()):
            if (apr.payload or {}).get("output_id") in gone:
                apr.status = "withdrawn"
                apr.decided_at = db.utcnow()
                apr.payload = {**(apr.payload or {}),
                               "withdrawn_because":
                                   "replaced on the board by a regenerate"}
        merged = kept + rows
        for n, v in enumerate(merged, 1):
            v["n"] = n
        batch["variants"] = merged
        batch["last_regenerate"] = {"asked": len(replaced),
                                    "cleared": len(rows)}
        _doc = _json.dumps(batch, ensure_ascii=False, indent=1)
        row = s.get(db.ArtifactBody, art.id)
        row.body = _doc
        row.bytes = len(_doc)
        nv = 2 + (s.query(db.ArtifactVersion)
                  .filter(db.ArtifactVersion.output_id == output_id).count())
        s.add(db.ArtifactVersion(
            tenant=tenant, output_id=output_id, n=nv, author="machine",
            note=f"regenerated {len(rows)} of {len(replaced)} variant(s) "
                 f"with feedback", body=_doc))
        for f_row in (s.query(db.FeedbackItem)
                      .filter(db.FeedbackItem.output_id == output_id,
                              db.FeedbackItem.level == "draft",
                              db.FeedbackItem.status == "open").all()):
            f_row.status = "applied"
            f_row.applied_at = db.utcnow()
        s.commit()

    short = ""
    if len(rows) < len(replaced):
        short = (f" — asked for {len(replaced)}, {len(rows)} cleared the "
                 f"gates; the shortfall is on the run's record")
    return {"ok": True, "output_id": output_id, "consumed": len(fb),
            "summary": (r.get("summary") or "")[:160] + short}


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
    # `offer` and `deadline` are OWNER_INPUT — `skill.run` puts them on the
    # bundle for every skill. `offer` was READ by `_campaign_craft` and never
    # declared here, so `run` refused the parameter at the door and every
    # bottom-of-funnel send reported an offer gap that nothing could close.
    #
    # `audience_key` is gone: nothing in this skill or in the runner ever read
    # it, so a caller setting it was silently ignored. The segment already
    # decides who is written to, and a second vocabulary for a decision
    # already made is the defect design rule 4 exists to stop.
    params=("revision_notes",
            "segment", "goal", "subject", "intent", "deadline", "entity_key",
            # THE REST OF WHAT THE SEND IS ABOUT. `entity_key` is the hero;
            # this is everything else its copy may cite, for the email whose
            # subject is a place rather than a thing.
            "entity_keys",
            # WHO IT IS WRITTEN FOR — back, and wired this time. Removing it
            # (ec58e7a) reasoned that "the segment already decides who is
            # written to". That conflated two different facts: the segment is
            # who RECEIVES the send, the audience is who it is WRITTEN FOR,
            # and one `reorder_due` list contains all three Baci personas.
            "audience_key",
            "offer", "utterance", "draft_visual"),
    writes=True,
    produces="draft",
    # ONE-TO-MANY WORK NAMES ITS READER. Owner, 2026-08-31: "Audience only
    # applies in plural to segments in mass marketing." A campaign goes to a
    # list, so it is written for one persona on that list — and the choice is
    # only refused when the account has personas to choose from.
    requires=("audience_key",),
    requires_when=_has_a_reader_to_pick,
    run=_run_campaign_email))


# ---------------------------------------------------------------------------
# blog_article — one article against one keyword
# ---------------------------------------------------------------------------
#: The MOVES an article can make. A vocabulary, deliberately — not a lookup
#: from intent to format.
#:
#: The owner's objection to a lookup, 2026-08-26: *"the format should be
#: dynamic right? Otherwise we will be generating a lot of the same articles
#: for the same keywords. It will take many different angles and
#: reader-driven content to rank sometimes."* He is right, and a table mapping
#: "best X" to "comparison" would guarantee the failure: eight supports under
#: one pillar would arrive as eight versions of the same page, competing with
#: each other for the query they were all written to win.
#:
#: So intent NARROWS the set and history picks from what is left. `campaign_
#: email` has done this since it was written — `_craft_brief` shows the model
#: the shapes and openings of the last three sends and tells it to move away
#: from them, which is the claims anti-repeat applied to form. Articles had
#: none of it.
ARTICLE_ANGLES: dict[str, dict] = {
    "definitive": dict(
        label="The definitive answer",
        brief="Answer the query completely and plainly, better than anything "
              "ranking for it. No hedging, no throat-clearing, no history of "
              "the category before the answer.",
        fits=("informational", "navigational")),
    "comparison": dict(
        label="A comparison that commits",
        brief="Set the real options side by side on the criteria a buyer "
              "actually weighs, and SAY which suits whom. A comparison that "
              "refuses to conclude is a table, not an article.",
        fits=("commercial", "transactional")),
    "walkthrough": dict(
        label="Do it with me",
        brief="Numbered steps somebody can follow while holding the thing. "
              "Each step is an action, not a consideration.",
        fits=("informational",)),
    "correction": dict(
        label="What everyone gets wrong",
        brief="Name the common belief, show why it fails, replace it. Only "
              "where an approved claim genuinely contradicts received "
              "wisdom — inventing a myth to knock down is the cheapest and "
              "most obvious form of this and it reads as filler.",
        fits=("informational", "commercial")),
    "checklist": dict(
        label="Before you buy",
        brief="The short list of things worth checking, each with the reason "
              "it matters. Scannable; a reader should be able to use it in a "
              "shop without reading the prose.",
        fits=("commercial", "transactional")),
    "situational": dict(
        label="For one specific occasion",
        brief="One concrete situation — a table for six outdoors, a first "
              "flat, a gift with an hour to spare — answered end to end. "
              "Narrower than the query, which is what makes it worth reading.",
        fits=("commercial", "transactional", "informational")),
    "explainer": dict(
        label="Why it is like that",
        brief="The mechanism behind the thing: what makes it work, what the "
              "trade-off is, why the obvious alternative is not used. Earns "
              "the trust that a recommendation later spends.",
        fits=("informational",)),
}


def _pick_angle(intent: str, recent: list, cluster: str = "") -> tuple[str, str]:
    """Which move this article makes, given what has already been written.

    Two filters and then rotation. Intent narrows the set — a "how to" query
    is not answered with a comparison — and everything already used IN THIS
    CLUSTER is removed, because a cluster is the one place where sameness is
    guaranteed to be noticed: eight supports around one pillar, all written
    to the same recipe, compete with each other.

    Falls back through: unused-and-fitting, then unused-anywhere, then the
    least recently used. Never refuses — an article with a repeated angle is
    a worse article, not a false one, and this is not a gate.
    """
    fitting = [k for k, v in ARTICLE_ANGLES.items()
               if not intent or intent in v["fits"]] or list(ARTICLE_ANGLES)
    used_here = [r[0] for r in recent if r[1] == cluster and r[0]]
    used_any = [r[0] for r in recent if r[0]]
    for pool, why in ((
            [k for k in fitting if k not in used_here],
            f"fits {intent or 'the query'}, unused in this cluster"), (
            [k for k in fitting if k not in used_any],
            f"fits {intent or 'the query'}, unused anywhere yet"), (
            fitting, "every fitting angle has been used — least recent")):
        if pool:
            if why.endswith("least recent"):
                # LAST use, not first. `used_any` is newest-first, so a larger
                # index is longer ago — and sorting ascending on the reversed
                # list keyed off FIRST use, which meant the angle that opened
                # the cluster won every round after the set was exhausted:
                # five different articles, then "definitive" forever.
                pool.sort(key=lambda k: used_any.index(k) if k in used_any
                          else len(used_any), reverse=True)
            return pool[0], why
    return "definitive", "no angle fitted"


def _recent_articles(tenant: str, limit: int = 12) -> list:
    """(angle, cluster, opening) for the last few articles, newest first.

    The cluster is JOINED from `KeywordTarget.output_id` rather than stored a
    second time on `Output` — the keyword row already records which article
    was written for it, and a second copy is a second thing to drift.
    """
    from . import db as _db, ledger as _lg
    rows = _lg.recent(tenant, system_key="blog", limit=limit)
    ids = [o.id for o in rows if o.id]
    by_output: dict[str, str] = {}
    if ids:
        with _db.SessionLocal() as s:
            for k in (s.query(_db.KeywordTarget)
                      .filter(_db.KeywordTarget.tenant == tenant,
                              _db.KeywordTarget.output_id.in_(ids)).all()):
                by_output[k.output_id] = k.cluster_key or ""
    out = []
    for o in rows:
        opening = re.sub(r"<[^>]+>", " ", o.body or "")
        opening = re.sub(r"\s+", " ", opening).strip()[:90]
        out.append(((o.angle or "").split(" ")[0],
                    by_output.get(o.id, ""), opening))
    return out


_ARTICLE_SYSTEM = """You write articles that answer a search query better than
anything already ranking for it, for a brand whose rules you are given.

ANSWER FIRST. The opening paragraph answers the query in plain language, before
any preamble, context or brand history. A reader who leaves after one paragraph
should have their answer, and an answer engine quoting one passage should be
able to quote that one.

STRUCTURE: an H1 that is the article's title, then H2 sections whose headings
are the sub-questions a reader actually has. Short paragraphs. Use an H3 + one
paragraph for anything that is literally a question.

THE H1 IS THE TITLE THAT SHIPS — it becomes the page title and the <title> tag,
so write it for a person choosing what to click, and carry the target phrase
inside it naturally. Under about 60 characters. Not the bare search query: "Buy
acrylic dinnerware" is what the machine typed, not what a person would click.
"Acrylic Dinnerware That Survives a Whole Summer Outside" carries the same
words and is worth reading.

GROUND EVERY FACTUAL ASSERTION in the approved claims you are given. If a claim
does not cover something, write around it or leave it out. Never invent a
statistic, a date, a material, a place of manufacture, or a superlative.

NEVER write a link you were not given. If you were given internal links, use
them once each, in the sentence where they are genuinely useful.

WHERE A PICTURE WOULD HELP, MARK THE PLACE — never write an image tag. Put
`<!--IMAGE: what it should show-->` on its own line between two paragraphs, at
most twice, and only where a reader would genuinely be helped by seeing the
thing rather than reading about it. Describe the SUBJECT of the passage it sits
beside, concretely and in a few words — "a folding table set for eight in a
garden", not "an image about outdoor dining". You are naming a place and a
subject; the system chooses the actual picture from what this brand has
approved, and removes the marker when it has nothing that fits. An article
where every marker was dropped must still read correctly, so never refer to a
picture in the prose.

Return HTML: h1, h2, h3, p, ul/li, and a href only for links you were given.
No <script>, no <style>, no inline styles, no image tags."""


def _article_prompt(bundle: dict, keyword: str, role: str, angle: str,
                    questions: list, links: list, entity: dict | None,
                    avoid: list | None = None) -> str:
    parts = [bundle["rules"]["block"].strip(),
             f"\n## The query this must answer\n{keyword}"]
    parts.append(
        "\n## What kind of article this is\n" + (
            "A PILLAR. It is the main page for this topic and the supporting "
            "articles will link into it, so it must cover the whole subject "
            "broadly rather than exhaustively on one narrow point."
            if role == "pillar" else
            "A SUPPORT. It answers ONE narrow question thoroughly and links "
            "back to the pillar. Do not try to cover the whole topic."))
    claims = bundle.get("claims") or []
    if claims:
        parts.append("\n## The only facts you may assert")
        for c in claims[:12]:
            parts.append(f"- {c['claim']}"
                         + (f" (evidence: {c['evidence']})" if c.get("evidence") else "")
                         + f" [true of: {c.get('scope') or 'the brand'}]")
    # No `else`: the skill refuses before reaching here when there are no
    # claims, because `emit` would block the result as uncited anyway.
    if entity:
        parts.append(f"\n## What this is about\n{entity.get('name', '')}: "
                     f"{entity.get('description', '')}"[:400])
    if questions:
        parts.append("\n## Real questions people search, to answer as H3s")
        for q in questions[:8]:
            parts.append(f"- {q}")
    if links:
        parts.append("\n## Internal links you may use (and no others)")
        for L in links[:6]:
            parts.append(f'- <a href="{L["url"]}">{L["anchor"]}</a>')
    # WHERE THE SEARCHER IS, before what the article does. Derived from the
    # keyword's own intent (see `_run_blog_article`), so somebody who typed
    # "best X vs Y" is briefed as a person comparing alternatives and shown
    # this account's actual objections — rather than written at as though
    # they had typed "what is X".
    if bundle.get("funnel"):
        parts.append(funnel.brief(bundle["funnel"]))
    if angle:
        spec = ARTICLE_ANGLES.get(angle)
        if spec:
            parts.append(f"\n## THE MOVE THIS ARTICLE MAKES: {spec['label']}")
            parts.append(spec["brief"])
        else:
            parts.append(f"\n## Angle\n{angle}")
    if avoid:
        # Told once, a model will happily write the same article twice. Shown
        # what it already published for this brand, it has something concrete
        # to move away from — `campaign_email` has worked this way since it
        # was written and articles had none of it.
        parts.append("\n## DO NOT REPEAT THESE — they are already published")
        for a, c, opening in avoid[:4]:
            bits = []
            if a:
                bits.append(f"a '{a}' article")
            if c:
                bits.append(f"in the {c} cluster")
            if opening:
                bits.append(f"opening {opening!r}")
            if bits:
                parts.append("- " + " ".join(bits))
        parts.append("Take a different approach and a different opening move "
                     "from every one of those. Not a reworded version of the "
                     "same page — a different page. Two articles in one "
                     "cluster written to the same recipe compete with each "
                     "other for the query they were both written to win.")
    if bundle.get("revision_notes"):
        parts.append("\n## THIS IS A REDRAFT — THE OWNER SENT THE LAST ONE "
                     "BACK\nFix every item below; they outrank the angle "
                     "brief and the anti-repeat list:\n"
                     + str(bundle["revision_notes"]))
    return "\n".join(parts)


import re as _re


#: What the drafter leaves behind where a picture would help. An HTML COMMENT
#: on purpose: if one is ever missed, it renders as nothing. `[IMAGE: …]` would
#: render as literal text on a live page, and the failure mode of a placement
#: system has to be an absent picture, never visible scaffolding.
_IMG_MARK = _re.compile(r'[ \t]*<!--\s*IMAGE:\s*(.{3,160}?)\s*-->[ \t]*\n?',
                        _re.I | _re.S)

#: An article is not a gallery. Two is enough to break up a long piece and few
#: enough that each one has to earn its place.
MAX_BODY_IMAGES = 2


def place_images(body: str, tenant: str, *, commitment: dict | None = None,
                 entity_key: str = "", used: set | None = None) -> tuple:
    """Fill the drafter's placement markers from what this brand has approved.

    THE MODEL NAMES THE PLACE AND THE SUBJECT; IT NEVER NAMES THE PICTURE. The
    same rule the internal links already follow, for the same reason: a URL
    from a model is a URL nobody can vouch for, and `_link_grounding` exists
    because that failure shipped once. Here it cannot happen by construction —
    the marker carries prose, and every `src` comes from `creative.pick`,
    which selects only assets somebody approved.

    A MARKER WITH NOTHING BEHIND IT IS REMOVED, NOT LEFT. It is also recorded:
    the subject becomes a brief, the same queue the hero's absence feeds, so
    "this article wanted a picture of X" reaches the person who can make one
    instead of dying in a run log. An article whose markers were all dropped
    still reads correctly, which is why the prompt forbids referring to a
    picture in the prose.

    THE HERO IS NEVER REPEATED. `used` carries the hero's asset id in, and a
    body image that duplicated it would read as a rendering fault rather than
    as illustration — the same picture twice, once under the headline and once
    halfway down.

    Returns `(html, placed, wanted)` — the body, the assets used, and the
    briefs for the ones that could not be filled.
    """
    from . import creative
    seen = set(used or ())
    placed: list[dict] = []
    wanted: list[str] = []

    def _one(m):
        subject = " ".join(m.group(1).split())
        if len(placed) >= MAX_BODY_IMAGES:
            wanted.append(subject)
            return ""
        got = creative.pick(tenant, commitment=commitment, fmt="article_body",
                            entity_key=entity_key, prominent=subject)
        aid = str(got.get("asset_id") or "")
        if not aid or aid in seen or not (got.get("url") or ""):
            wanted.append(subject)
            return ""
        seen.add(aid)
        placed.append({"asset_id": aid, "url": got["url"], "subject": subject,
                       "rung": got.get("rung", ""), "why": got.get("why", "")})
        # ALT TEXT FROM THE ASSET, never from the marker. The marker is what
        # the writer WANTED to see; the alt has to describe what is actually
        # there, or a screen reader is told about a picture nobody chose.
        alt = str(got.get("alt") or got.get("subject") or subject)
        return (f'<figure><img src="{_esc_attr(got["url"])}" '
                f'alt="{_esc_attr(alt)}" loading="lazy"></figure>\n')

    return _IMG_MARK.sub(_one, str(body or "")), placed, wanted


def _esc_attr(v: str) -> str:
    """Attribute-safe. A caption or alt carrying a quote would otherwise close
    the attribute and put prose into the markup."""
    return (str(v or "").replace("&", "&amp;").replace('"', "&quot;")
            .replace("<", "&lt;").replace(">", "&gt;"))


def _draft_article_live(bundle: dict, keyword: str, role: str, angle: str,
                        questions: list, links: list,
                        entity: dict | None,
                        avoid: list | None = None) -> tuple[str, str]:
    """One model call for one article. Returns `(html, why_not)`."""
    from . import config
    if not config.ANTHROPIC_API_KEY:
        return "", "ANTHROPIC_API_KEY is not set"
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model=config.CLAUDE_MODEL, max_tokens=3000,
            system=_ARTICLE_SYSTEM,
            messages=[{"role": "user", "content": _article_prompt(
                bundle, keyword, role, angle, questions, links, entity,
                avoid)}])
        try:
            from . import usage
            usage.log_usage("blog_article_draft", config.CLAUDE_MODEL, msg,
                            tenant=str(bundle.get("tenant") or ""))
        except Exception:  # noqa: BLE001 — accounting must not fail a draft
            pass
        return "".join(b.text for b in msg.content if b.type == "text").strip(), ""
    except Exception as exc:  # noqa: BLE001
        # Classified, not truncated, for the same reason `ad_copy` does it: a
        # spend limit reported as "BadRequestError" reads as a code fault
        # rather than an account one, and this skill REFUSES on a failed draft
        # rather than degrading, so the message is the whole explanation.
        from . import model_error
        return "", model_error.explain(exc)


def _trim_words(text: str, limit: int) -> str:
    """Trim at a word boundary, never mid-word — an ellipsis over a chop."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit - 1].rsplit(" ", 1)[0].rstrip(",;:-— ") + "…"


def _h1_of(body_html: str) -> str:
    """The article's own H1, as text. `""` when it wrote none."""
    import re as _re
    m = _re.search(r"<h1[^>]*>(.*?)</h1>", body_html or "",
                   _re.I | _re.S)
    if not m:
        return ""
    return _re.sub(r"\s+", " ", _re.sub(r"<[^>]+>", "", m.group(1))).strip()


def _targets_keyword(keyword: str, title: str) -> bool:
    """Does this title already go after that query?

    TOKEN COVERAGE, not an exact substring. "Melamine and Acrylic Dinnerware,
    Compared" targets "acrylic dinnerware sets" — every content word is there
    — and the old exact-match test said no, so a good human title was stuffed
    with the query and then TRUNCATED AWAY by the 60-character trim. The
    reader got the search phrase plus a fragment.

    `keywords.tokens` is the vocabulary, not a second stemmer here: it is the
    same predicate `keywords.cluster` uses to decide whether one phrase
    contains another, so "targets it" means the same thing in the plan and in
    the title tag.
    """
    from . import keywords as _kw
    want, got = set(_kw.tokens(keyword)), set(_kw.tokens(title))
    if not want:
        return False
    hit = want & got
    if hit == want:
        return True
    # MOST, not all. A strict subset called "Melamine and Acrylic Dinnerware,
    # Compared" a miss for "acrylic dinnerware sets" over the single word
    # "sets", and then stapled the query onto a title that was plainly about
    # it. Two thirds with at least two real words matched is generous enough
    # to stop that and tight enough that one incidental shared word — "best",
    # "miami" — does not count as targeting.
    return len(hit) >= 2 and len(hit) * 3 >= len(want) * 2


def _seo_title(keyword: str, title: str) -> str:
    """The <title> tag, ≤60 chars, carrying the target query.

    Deterministic on purpose (same reasoning as the description below), and
    rewritten 2026-08-29 because the previous version produced exactly what
    the owner described: it stapled the raw keyword to the front with an em
    dash, so a page about melamine got

        "Best melamine dinnerware vs acrylic — Which Dinnerware…"

    — the query, then a truncated fragment of the human title. A title tag is
    read by a person deciding whether to click; a stuffed one is skipped, and
    Google rewrites it anyway.

    The order now: keep the human title when it already targets the query
    (token coverage, not substring); otherwise fit the query in ALONGSIDE it
    rather than in place of it, trimming the title to make room instead of
    letting the trim eat it; and when there is no room for both, keep the
    HUMAN title — a page that ranks slightly worse and gets clicked beats one
    that ranks and does not.
    """
    keyword = (keyword or "").strip()
    title = (title or "").strip()
    if not keyword:
        return _trim_words(title, 60)
    if not title:
        return _trim_words(keyword[:1].upper() + keyword[1:], 60)
    if _targets_keyword(keyword, title) or keyword.lower() in title.lower():
        return _trim_words(title, 60)
    # Room for both? Trim the TITLE to fit beside the query, never the other
    # way round — the old code trimmed the joined string, which is why the
    # human half was the half that disappeared.
    lead = keyword[:1].upper() + keyword[1:]
    room = 60 - len(lead) - 3           # " — "
    if room >= 24:
        return f"{lead} — {_trim_words(title, room)}"
    return _trim_words(title, 60)


def _meta_description(keyword: str, body_html: str) -> str:
    """≤155 characters, from the article's own words, ANCHORED on the keyword.

    Formulaic on purpose — the same reasoning that keeps
    `catalog_seo_rewrite` deterministic: there is nothing here for a model to
    decide, and a generated one is a second place for a banned claim to
    enter. The 2026-08-27 fix: this took `keyword` and never used it, so the
    description was whatever the article happened to open with. Now the
    excerpt STARTS at the first sentence that contains the phrase — the
    article's own sentence, never a composed one — and only falls back to
    the opening when no sentence carries it (which the SERP then shows
    honestly: this page does not lead with the query).
    """
    import re as _re
    # DROP THE H1 FIRST. Stripping every tag and taking the opening text made
    # the description begin with the title — "A Summer Table There is a
    # certain kind of evening…" — so the snippet spent its first words
    # repeating the line directly above it in the result. The title and the
    # description are two pieces of real estate, not one said twice (rule 8).
    body_html = _re.sub(r"<h1[^>]*>.*?</h1>", " ", body_html or "",
                        flags=_re.I | _re.S)
    text = _re.sub(r"<[^>]+>", " ", body_html)
    text = _re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    keyword = (keyword or "").strip().lower()
    if keyword:
        sentences = _re.split(r"(?<=[.!?])\s+", text)
        for i, sen in enumerate(sentences):
            if keyword in sen.lower():
                packed = sen
                for nxt in sentences[i + 1:]:
                    if len(packed) + 1 + len(nxt) > 155:
                        break
                    packed = f"{packed} {nxt}"
                return _trim_words(packed, 155)
    return _trim_words(text, 155)


def article_commitment(keyword: str, entity_key: str, also: list,
                       title: str = "") -> dict:
    """What one article is ABOUT. One writer, two callers.

    The run builds this to choose a picture and to hand the coherence gate its
    subject. The workroom's Generate-the-picture control has to build the SAME
    one — a generated picture briefed against a different subject than the
    article was written against is a picture of the wrong thing, and it would
    look right in both places separately.

    Extracted rather than copied for the reason everything here is: the copy
    that drifts is the one nobody re-reads.
    """
    from . import coherence, keywords as kw_mod

    also = [k for k in (also or []) if k and k != entity_key]
    scopes = [k for k in ([entity_key] if entity_key else []) + also if k]
    return coherence.commit(
        "entity" if entity_key else "topic",
        entity_key or kw_mod.slug(keyword),
        label=title or keyword,
        also=also,
        proof_scopes=scopes or None)


def _run_blog_article(ctx: Context) -> dict:
    from . import (coherence, creative, keywords as kw_mod, seo_tools,
                   sites, tenants)

    keyword = str(ctx.params.get("keyword") or "").strip()
    if not keyword:
        return {"summary": "no keyword — this skill writes one article against "
                           "one query, and without it there is nothing to aim at"}
    role = str(ctx.params.get("role") or "").strip() or "support"
    angle = str(ctx.params.get("angle") or "").strip()
    entity_key = str(ctx.params.get("entity_key") or "").strip()

    # NO CLAIMS, NO ARTICLE — checked before the model is called, not after.
    # `emit` defaults `require_citation` to True for a draft, so an article
    # written without approved claims is blocked as uncited every time. The
    # first cut had a prompt branch for "you have no claims", which meant
    # spending a model call to produce something the validator was always
    # going to refuse — and reporting it as a validation failure rather than
    # as the authoring backlog it actually is. `ad_copy` already says this
    # better: it is not a bug, it is a queue of writing nobody has done.
    if not ctx.claims:
        ctx.note("no approved claim is in scope for this keyword, so there is "
                 "nothing an article could assert. This is the KB backlog, not "
                 "a failure — approve a claim and re-run.")
        return {"summary": "no proof in scope", "keyword": keyword}

    row = next((r for r in kw_mod.targets(ctx.tenant) if r.phrase == keyword), None)
    if row is None:
        # A keyword typed straight into a run joins the map before drafting.
        # Without this the board — the only surface that links the review
        # page — never listed the article, and the page was reachable only by
        # hand-typing its output id into the address bar.
        kw_mod.upsert(ctx.tenant, keyword, source="direct_run")
        kw_mod.cluster(ctx.tenant)
        row = next((r for r in kw_mod.targets(ctx.tenant)
                    if r.phrase == keyword), None)
    cluster_key = str(ctx.params.get("cluster") or "") or (row.cluster_key if row else "")
    if row is not None:
        role = ctx.params.get("role") or row.role or role

    # WHERE THE SEARCHER IS, from the keyword's OWN intent. `keywords` already
    # sorts every phrase into transactional / commercial / informational /
    # navigational in order to rank and cluster it, and those are funnel
    # positions under different names — "best X vs Y" is somebody comparing
    # alternatives, which is the consideration stage's definition. Derived
    # rather than parameterised, for the same reason email's is: the decision
    # has already been made once and a second knob for it is a second
    # vocabulary (design rule 4).
    _intent = (getattr(row, "intent", "") if row is not None else "") \
        or kw_mod.classify_intent(keyword, kw_mod.brand_tokens_for(ctx.tenant))
    _stage = funnel.stage_from_keyword(_intent)
    _reader_gap(ctx)
    _plan = funnel.inputs_for(
        ctx.tenant, _stage, claims=ctx.claims,
        objections=ctx.bundle.get("objections"),
        entities=ctx.bundle.get("entities"),
        audience=ctx.bundle.get("audience"))
    ctx.bundle["funnel"] = _plan
    ctx.note(f"funnel stage: {_plan['label']} — '{keyword}' is a "
             f"{_intent} search")
    for _n in _plan.get("note") or []:
        ctx.note(f"funnel (thin): {_n}")
    if _plan.get("missing"):
        ctx.thin.extend(f"funnel:{m}" for m in _plan["missing"])

    # The AEO half, and it is not an extra: `semrush_questions` harvested these
    # into the map, so the questions this article answers are ones people
    # actually searched rather than ones a model imagined. They become H3s in
    # the body AND the FAQPage schema, from one list.
    siblings = [r for r in kw_mod.targets(ctx.tenant, cluster_key=cluster_key)
                if r.phrase != keyword] if cluster_key else []
    # A sibling that is ALREADY PUBLISHED is a link, never an FAQ answer.
    # Answering inline what you are also linking to as its own article
    # competes with your own page for the same query — and the FAQ block is
    # where a support's whole reason to exist would quietly get duplicated
    # into its pillar.
    questions = [r.phrase for r in siblings
                 if kw_mod.is_question(r.phrase)
                 and not (r.target_url or "").strip()][:8]

    # Only links that RESOLVE. A sibling with no target_url has not been
    # published, and inventing the URL it will one day have is exactly what
    # `_link_grounding` blocks at the queue — better not to offer it.
    links = [{"url": r.target_url, "anchor": r.phrase}
             for r in siblings if (r.target_url or "").strip()]
    if role == "support":
        pillar = next((r for r in siblings if r.role == "pillar"
                       and (r.target_url or "").strip()), None)
        if pillar is None:
            ctx.note("no published pillar to link back to yet — this support "
                     "will need its link added when the pillar goes live")

    entity = None
    if entity_key:
        entity = next((e for e in (ctx.bundle.get("entities") or [])
                       if e.get("key") == entity_key), None)

    # WHICH MOVE, chosen against what has already been written. An explicit
    # angle from the plan wins — the owner naming one is a decision, not a
    # preference — and otherwise it rotates, avoiding what this cluster has
    # already used. `why` is recorded so the choice can be read back.
    avoid = _recent_articles(ctx.tenant)
    # A redraft's marching orders ride the bundle into the prompt — set by
    # the workroom's Request-changes path, absent on a fresh draft.
    angle_why = "set on the plan"
    if not angle:
        angle, angle_why = _pick_angle(
            (row.intent if row is not None else "") or "", avoid, cluster_key)
    body, why_not = _draft_article_live(
        ctx.bundle, keyword, role, angle, questions, links, entity, avoid)
    if not body:
        # NO COMPOSED FALLBACK, unlike `ad_copy`. A three-line ad assembled
        # from a claim is a usable placeholder; a template article is a thin
        # page, and thin pages are actively harmful to the thing this system
        # exists to improve. Refusing is the better output.
        ctx.note(f"not drafted — {why_not}. Nothing was filed: a templated "
                 f"article would rank worse than no article.")
        return {"summary": f"not drafted ({why_not})", "keyword": keyword}

    # THE MODEL'S OWN H1 IS THE TITLE. This line used to be
    # `title = keyword[:1].upper() + keyword[1:]` — the article's Title was
    # set to the capitalised SEARCH QUERY and the H1 the drafter had been
    # explicitly asked for ("an H1 that is the article's title",
    # `_ARTICLE_SYSTEM`) was written into the body and never read. `_seo_title`
    # then saw the keyword already "in" the title, returned it unchanged, and
    # both fields shipped as the raw query. Owner, 2026-08-29: "you just put
    # in the keyword instead of optimizing with a human-facing name that
    # incorporates the optimized keywords."
    title = _h1_of(body)
    if not title:
        # No H1 came back. Say so rather than silently falling back to the
        # query, which is how this stayed invisible: a title tag that IS the
        # search phrase is the worst result a SERP can carry, and it looked
        # like a deliberate optimisation.
        title = keyword[:1].upper() + keyword[1:]
        ctx.note("the draft returned no H1, so the title falls back to the "
                 "keyword itself — edit it in the workroom before publishing; "
                 "a title tag that is the bare search phrase reads as spam "
                 "and wins no clicks")
    faqs = [{"question": q, "answer": ""} for q in questions]
    # WHAT THIS ARTICLE IS, on the artifact itself. These three were computed
    # here, handed to `_propose`, and then existed only inside the approval
    # payload — so the review page went blank the moment that approval stopped
    # being pending, and an edit made in that state was silently dropped.
    if title and not _targets_keyword(keyword, title) \
            and keyword.lower() not in title.lower():
        # ACT WHERE YOU REPORT: the workroom is where a title is edited, and
        # this is the run that knows. Better than silently stuffing the query
        # in, which is what used to happen and what made the output unusable.
        ctx.note(f"the title does not carry {keyword!r} — it reads well but "
                 f"the target phrase is only in the body. Reword it in the "
                 f"workroom if the ranking matters more than the click")
    # THE FEATURED IMAGE. An article published with none is not a smaller
    # version of the same post — it is the one that looks broken on the blog
    # index and in every share card. The blog attached no media at all, and
    # `shopify_seo.create_article` sent no image field, so the gap was open at
    # BOTH ends; this closes the drafting one.
    #
    # SELECTS an approved photograph, never generates. `imagegen` has exactly
    # one caller — the manual `/admin/creative` endpoint, which returns a PNG
    # and files nothing — so there is no generated asset for anything to
    # attach yet. Named here rather than left implicit because the absence is
    # the interesting part.
    # THE SHARED LADDER, not this system's own rule. `hero_for_campaign` was
    # written for a campaign and orders by entity scope, so an article about a
    # SITUATION — knee pain, say — fell to the brand-wide rung and took a
    # product photograph. `creative.pick` reads what the piece is about and,
    # on the topic side of the ladder, refuses a product shot outright rather
    # than ranking it last: it is the wrong picture, not a lesser one.
    # WHOSE FACTS THIS PIECE MAY CITE. `proof_scopes` is coherence's own
    # field for it — "which entity keys' claims are legitimately ABOUT this
    # subject" — and it was never passed here, so a TOPIC commitment declared
    # no scope and `coherence.review` fell back to the topic slug, which is
    # not an entity key. An article about a location could therefore cite
    # nothing about its venues without the gate reading it as proof borrowed
    # from elsewhere.
    from . import systems as _sysm
    _also = [k for k in _sysm.entity_list(ctx.params.get("entity_keys") or "")
             if k != entity_key]
    _about = article_commitment(keyword, entity_key, _also, title)
    _hero = creative.pick(
        ctx.tenant, commitment=_about, fmt="article_hero",
        entity_key=entity_key, prominent=title,
        claim=(ctx.bundle.get("claims") or [{}])[0].get("claim", ""))
    _hero_id = str(_hero.get("asset_id") or "")
    # THE PICTURES INSIDE THE PIECE, filled where the drafter marked a place.
    # After the hero on purpose: the hero's id goes in as `used`, so the same
    # photograph cannot appear twice — once under the headline and once
    # halfway down, which reads as a rendering fault rather than illustration.
    body, _in_body, _img_wanted = place_images(
        body, ctx.tenant, commitment=_about, entity_key=entity_key,
        used={_hero_id} if _hero_id else set())
    if _in_body:
        ctx.note("pictures in the piece: "
                 + "; ".join(f"{p['subject']} ({p['rung']})" for p in _in_body))
    for _w in _img_wanted:
        # THE SAME QUEUE THE HERO'S ABSENCE FEEDS. A marker the account could
        # not fill is a picture somebody wanted, named — not a silent gap.
        ctx.thin.append(f"image:{_w}")
    if _img_wanted:
        ctx.note(f"{len(_img_wanted)} place(s) in the article wanted a picture "
                 f"this account does not have yet — the markers were removed, "
                 f"and each is filed as a brief.")
    if _hero_id:
        ctx.note(f"picture: {_hero['rung']} — {_hero['why']}")
    else:
        # NAMED AS A REQUEST, not as a shrug — and the request has to be one
        # somebody can actually make.
        #
        # THIS SENTENCE WAS FALSE IN BOTH HALVES. It read "generate it from the
        # workroom, or the nightly sweep will", and there was no workroom
        # control and no sweep: `creative.generate` and `creative.batch` are
        # complete, assessed, guarded by nine sabotage entries — and had ZERO
        # production callers. The only image path that ran was `creative.pick`,
        # which selects among APPROVED assets and never makes one, so an
        # account with no approved photographs got no hero, ever, and was told
        # twice that something was coming. Owner, 2026-09-01: *"I also dont see
        # any images… where is all the work we did for generating images?"*
        #
        # The control now exists (`/admin/article_picture`), so the sentence
        # points at it and says where the result lands — proposed, on Review ·
        # Pictures, because a generated picture is not an approved one.
        ctx.note(f"no picture: {_hero['why']}. A brief is ready for one about "
                 f"“{_hero['subject']}” — press Generate the picture on this "
                 f"article's page; it arrives on Review · Pictures for you to "
                 f"approve before anything can use it.")
        ctx.thin.append(f"image:{_hero['subject'] or 'no subject declared'}")

    def _repair_article(previous: str, failures: list) -> str:
        """Hand the article its own rejection and ask again.

        Owner, 2026-09-02: *"Does the auto have a redraft capability with
        instruction on why it failed validation?"* The loop exists in
        `Context.emit` and runs at EVERY rung — but only when the skill hands
        it a repairer, and `blog_article` handed it none. Three of the six
        emits in this pack passed one; the article did not, so the longest
        thing this system writes and the only one that lands on a public page
        under the client's own domain was the one that never got a second
        attempt. A banned phrase in paragraph nine blocked the whole piece and
        waited for a person, at every rung including `auto` — where nobody is
        watching, which is precisely where a blocked draft costs the most.

        The failures are named, not summarised: `detail` is what broke and
        `fix` is what the checker itself says to do about it. Rewriting the
        rules into a nicer sentence here would be a second vocabulary for the
        same thing, and the drafter would be reasoning about my paraphrase
        rather than the gate it has to pass.

        Only the model can repair; with no key there is nothing to reason with
        and `_draft_article_live` returns "", which `emit` reads as "nothing
        more to give" and stops on — correctly.
        """
        note = "\n".join(f"- {f['detail']} → {f['fix']}" for f in failures)
        fixed, _ = _draft_article_live(
            {**ctx.bundle,
             "rules": {**ctx.bundle.get("rules", {}),
                       "block": ctx.bundle.get("rules", {}).get("block", "")
                       + f"\n\n## Your previous article was rejected\n"
                         f"{previous[:6000]}\n\n## Why, and what to change\n"
                         f"{note}\nRewrite it so none of these apply. Keep the "
                         f"H1, keep the structure, keep every internal link "
                         f"you were given, and do not drop the claims. Do not "
                         f"argue with the rules."}},
            keyword, role, angle, questions, links, entity, avoid)
        if not fixed:
            return fixed
        # THE REPAIR IS A FRESH DRAFT, WITH FRESH MARKERS. `place_images` ran
        # once, on the FIRST body; a repaired one comes back carrying
        # `<!--IMAGE: …-->` that nothing has filled, and `emit` takes it as
        # final. So a repaired article published raw scaffolding and no
        # pictures — and repair only runs on `auto`, which is the rung that
        # publishes with nobody looking. Every stage that transforms a body
        # has to run on every body, not on the first one.
        _hero_used = {_hero_id} if _hero_id else set()
        _hero_used |= {p["asset_id"] for p in _in_body}
        fixed, _again, _still_wanted = place_images(
            fixed, ctx.tenant, commitment=_about, entity_key=entity_key,
            used=_hero_used)
        for _w in _still_wanted:
            ctx.thin.append(f"image:{_w}")
        return fixed

    ctx.emit(body, claim_ids=[c["claim_id"] for c in (ctx.bundle.get("claims") or [])[:12]],
             entity_key=entity_key, angle=angle or f"{role} article",
             fmt="cms_article", redraft=_repair_article,
             # WHAT THIS ARTICLE IS ABOUT, handed to the gate.
             #
             # `_about` was built above and went only to `creative.pick`, so an
             # article was the one draft in this pack whose commitment never
             # reached `emit` — and `Context.emit` runs the coherence axis only
             # `if commitment is None: return []`. So ZERO coherence rules ran
             # on any article ever written: the check that asks "is this about
             # the thing it said it was about" was built, wired to five of six
             # emit sites, and silently skipped on the sixth.
             commitment=_about,
             parts=lambda text: coherence.parts(
                 text=text, prominent=title,
                 images=([{"url": _hero.get("url", ""),
                           "alt": _hero.get("alt", ""),
                           "subject_key": entity_key or "",
                           "basis": _hero.get("basis", "")}]
                         if _hero_id else []),
                 items=[], claims=[
                     {"claim_id": c["claim_id"], "text": c["claim"],
                      "scope": c.get("scope", "brand-wide")}
                     for c in (ctx.bundle.get("claims") or [])[:12]]),
             media_ids=[_hero_id] if _hero_id else [],
             meta={"title": title,
                   "seo_title": _seo_title(keyword, title),
                   "seo_description": _meta_description(keyword, body),
                   "keyword": keyword, "role": role, "cluster": cluster_key,
                   "questions": questions, "internal_links": len(links),
                   "angle_why": angle_why})

    # --- queue the publish, through the ONE path that queues articles ------
    #
    # `seo_tools._propose` owns `_build_content_fields` (FAQ HTML + JSON-LD,
    # routed per platform), `_link_grounding` and the approval. Composing the
    # fields here instead would be a second copy of the AEO half — the same
    # two-lists defect this initiative has now fixed twice.
    # --- what happened to the PUBLISH, said out loud -----------------------
    #
    # DRAFTED IS NOT PUBLISHED, and the first version's summary did not know
    # the difference: it read "support article for 'x'" whether the publish
    # had been queued, refused, or never attempted, while the harness added
    # "1 item(s)" from the ledger row. The owner read that as an article on
    # their store and went looking for it in Shopify. Nothing was there,
    # because `eien` has no `blog_id` — the one branch here that queues
    # nothing at all.
    #
    # `ctx.note` said so and nobody saw it: notes are not in the one line a
    # "Run now" prints. So the state goes in the SUMMARY, first, before the
    # things that went right.
    # THE KEYWORD LEARNS ITS OUTPUT BEFORE ANYTHING PUBLISHES IT.
    #
    # This sat AFTER the publish block, which was harmless while every push
    # waited for a person: the approval was decided minutes or days later, by
    # which time the row knew its `output_id`. On `auto` the ship happens
    # INSIDE this run, and `keywords.mark_published` joins on exactly that
    # column — so it found no row, wrote nothing, and the page went live on
    # the client's site while the map still read `status=planned`,
    # `target_url=''`. Live, unlinkable, unmeasurable, and silent.
    #
    # A join has to exist before the thing that uses it. Reproduced at
    # rung=auto: approval `executed`, CMS had the article, KeywordTarget
    # unchanged.
    if row is not None:
        kw_mod.upsert(ctx.tenant, keyword, run_id=ctx.run_id,
                      # A row with an article behind it is past "candidate"
                      # whatever filed it. A DIRECT run (no plan) left the
                      # status untouched, so the board's targeting table —
                      # the exact place the run summary told the owner to
                      # look — did not list it: the notification pointed at
                      # a row that was not there.
                      status=("planned" if row is not None
                              and row.status == "candidate" else None),
                      output_id=(ctx.items[-1] or {}).get("output_id", "")
                      if ctx.items else "")

    t = tenants.get(ctx.tenant)
    blog_id = ((t.cms or {}) if t else {}).get("blog_id") or ""
    profile = sites.get(ctx.tenant)
    publish: dict = {"queued": False}
    # CAN WE ACTUALLY PUBLISH — asked of `backend()`, not of the platform
    # string. Ironside declares `squarespace`, so testing for an EMPTY
    # platform missed it entirely and the run reported a missing blog_id for
    # a store that does not exist. `backend()` already refuses by name for
    # both cases — nothing connected, and a platform with no backend built —
    # and its refusal is the sentence worth showing.
    try:
        sites.backend(profile)
        can_push = True
    except sites.UnknownSite as exc:
        can_push, why_no_cms = False, str(exc)

    if not can_push:
        publish["detail"] = (
            f"NOT queued — {why_no_cms} The article is written and kept; "
            f"paste it in from its review page, then record the live URL "
            f"there.")
    elif profile.get("platform") != "wordpress" and not blog_id:
        # NOTHING TO GUESS IS NOT A CHOICE. A store with exactly one blog was
        # being refused by a rule written for stores with several, so the
        # commonest account drafted articles that could never be queued until
        # somebody found the picker on another tab. Resolve it, RECORD it —
        # an auto-chosen destination the owner cannot see is worse than the
        # question — and only ask when there is a real ambiguity.
        try:
            blog_id = sites.backend(profile).sole_blog_id(profile) or ""
        except Exception:                                        # noqa: BLE001
            blog_id = ""
        if blog_id:
            tenants.set_blog(ctx.tenant, blog_id)
            ctx.note(f"this store has one blog ({blog_id}); articles will "
                     f"publish into it. Change it on the Plan tab.")

    if not can_push:
        # SAY WHAT IS MISSING — AND STILL SAY WHERE THE ARTICLE IS.
        #
        # `backend()`'s refusal names the generic case; `publish_gap` names
        # THIS account's, including the one the generic sentence gets WRONG:
        # a connection that exists but was approved without the scope that
        # writes articles, which the generic text sends somebody to reconnect
        # from scratch.
        #
        # BOTH HALVES SHIP. The first cut REPLACED the message and lost "the
        # article is written and kept; paste it in from its review page" — so
        # a person was told what was missing and not where the work went,
        # which is the more urgent of the two when a run has just finished.
        # `test_blog_skill` caught it on exactly that sentence, and it was the
        # code that was wrong, not the assertion.
        _gap = sites.publish_gap(ctx.tenant)
        if not _gap["ok"]:
            publish["detail"] = (
                "NOT queued — " + _gap["why"]
                + (" " + _gap["fix"] if _gap["fix"] else "")
                + " The article is written and kept; paste it in from its "
                  "review page, then record the live URL there.")
    elif profile.get("platform") != "wordpress" and not blog_id:
        publish["detail"] = (
            f"NOT queued — no blog_id set for {ctx.tenant}. This store holds "
            f"more than one blog and guessing writes to the wrong place. "
            f"Pick one on the console&#39;s Plan tab, then re-run.")
    else:
        # REVISE THE PAGE THAT RANKS; NEVER PUBLISH A SECOND BESIDE IT.
        # Owner, 2026-09-01: *"when a Needs Attention is addressed, do we have
        # the mechanism to patch with link in a way that makes sense?"* We did
        # not. This call was hardcoded to the CREATE tool, so a refresh of a
        # live page queued `seo_new_article` — reproduced as two identical
        # create approvals for one keyword. Approving the second would have
        # put a duplicate on the blog: the exact cannibalisation the whole
        # attention lane exists to prevent, produced by the lane.
        #
        # `propose_article_revision` has existed and worked the whole time and
        # needed one thing nothing supplied — the platform's `article_id`. It
        # is now captured at create and stored by `mark_published`.
        #
        # A REVISION TOUCHES ONLY WHAT IT SENDS, which is why the handle is
        # absent here: changing it moves the page's URL, and moving the URL of
        # something that ranks throws away the reason to refresh it.
        _live_id = str(getattr(row, "cms_article_id", "") or "") if row else ""
        _revising = bool(_live_id and (row.target_url or "").strip())
        said = seo_tools._propose(
            "propose_article_revision" if _revising else "propose_article", {
            "blog_id": blog_id, "title": title, "body_html": body,
            **({"article_id": _live_id} if _revising
               else {"handle": kw_mod.slug(keyword)}),
            "seo_title": _seo_title(keyword, title),
            "seo_description": _meta_description(keyword, body),
            "faqs": [f for f in faqs if f["answer"]],
            # The JOIN, carried from birth. The 2026-08-26 audit found the
            # article approval payload held no output_id and no run_id, so the
            # executor had nothing to join a write-back on — the live URL was
            # discarded into a WhatsApp message and the keyword map never
            # learned its article went live.
            "output_id": ((ctx.items[-1] or {}).get("output_id", "")
                          if ctx.items else ""),
            "run_id": ctx.run_id,
            "published": False}, profile)
        # `_propose` returns a SENTENCE either way — "Queued for your approval
        # (id): ..." on success, and a refusal ("BLOCKED — these internal links
        # don't resolve...", "Which blog?...") otherwise. Reading which is the
        # difference between an article waiting for a human and one that was
        # silently dropped.
        publish["queued"] = said.startswith("Queued for your approval")
        publish["detail"] = said if publish["queued"] else f"NOT queued — {said}"
        # ON `auto`, AND ONLY WHERE THE OWNER SAID SO. Owner, 2026-09-02:
        # *"Yes Cleared should push."* `systems.AUTO_SHIPS` holds the per-system
        # answer, because "push" is a different irreversible act in each one —
        # a published page can be revised and the refresh lane exists to do
        # exactly that, while a send cannot be recalled. campaign_email is off
        # there by decision, not omission.
        #
        # The approval is still created and still executed by the same arm; it
        # is simply decided by the rung instead of by a person, and the run
        # records `auto` so the two can be told apart afterwards.
        if publish["queued"] and _sysm.rung(ctx.autonomy) == "auto" \
                and _sysm.may_auto_ship(ctx.skill.system_key):
            from . import approvals as _appr
            _oid = ((ctx.items[-1] or {}).get("output_id", "")
                    if ctx.items else "")
            _shipped = _appr.ship_unattended(
                ctx.tenant, _oid, why="auto rung")
            if _shipped.get("ok"):
                publish["detail"] = ("published without asking (auto rung) — "
                                     + str(_shipped.get("said") or "")[:160])
            else:
                # NAMED. An unattended ship that quietly did not happen is the
                # worst of both: nobody was asked, and nothing went out.
                publish["detail"] += (f" — auto ship did not run: "
                                      f"{_shipped.get('why', 'unknown')}")
    ctx.note(publish["detail"])

    # ONE KEYWORD, ONE PAGE — enforced HERE, because every caller comes
    # through the skill. Owner, 2026-09-01: *"keywords often need a few
    # articles to start ranking"* — a TOPIC does, a KEYWORD does not, and two
    # pages aimed at one query cannibalise. The keyword's existing article
    # was silently orphaned by the `output_id` write below: the pointer moved
    # and the old page stayed live, queued and countable. So a refresh — or
    # anyone re-running a keyword that already shipped — produced exactly the
    # second page this lane exists to prevent.
    prior = (row.output_id or "") if row is not None else ""
    new_oid = ((ctx.items[-1] or {}).get("output_id", "") if ctx.items else "")
    if prior and new_oid and prior != new_oid:
        supersede(ctx.tenant, prior, new_oid,
                  keyword_id=(row.id if row is not None else ""),
                  run_id=_prior_run_id(prior), why="refresh")

    head = ("drafted and queued for approval" if publish["queued"]
            else "DRAFTED — the copy is kept, nothing queued")
    return {"summary": f"{head} — {role} article for {keyword!r}"
                       + (f", {len(questions)} question(s) answered" if questions else "")
                       + (f", {len(links)} internal link(s)" if links else "")
                       + (f". {publish['detail']}" if not publish["queued"] else ""),
            "keyword": keyword, "role": role, "cluster": cluster_key,
            "angle": angle, "angle_why": angle_why,
            "questions": questions, "publish": publish,
            # Said on EVERY run, including the successful one. "Where is my
            # article" is the question this skill will be asked most often,
            # and approving is the step between here and the answer.
            "next": ("approve it in the queue — nothing reaches the store "
                     "until you do" if publish["queued"]
                     else "the article is written and kept — its review "
                          "page opens when you run it from the Plan tab, and "
                          "the board's 'review the draft' link reaches it any "
                          "time; fix the reason above and re-run to queue it "
                          "as well")}


register(Skill(
    key="blog_article",
    name="Blog article",
    does="Write one answer-first article against one keyword from the map — "
         "grounded in approved claims, answering the questions people actually "
         "searched, with FAQ structured data and only internal links that "
         "resolve. Queues the publish for approval; never publishes itself.",
    system_key="blog",
    tier=3,
    needs=("rules.voice_tone", "rules.positioning"),
    # A ban list is CONSTITUTIVE here and nowhere else in this pack. An article
    # is the longest thing this system writes and the only one that lands on a
    # public page under the client's own domain; drafting one against an empty
    # ban list is not a thinner article, it is an unchecked one.
    constitutive=("banned_claims",),
    params=("keyword", "role", "cluster", "angle", "entity_key",
            # THE REST OF WHAT THE PIECE IS ABOUT. `entity_key` is the hero;
            # this is everything else it may cite, for the article whose
            # subject is a place rather than a thing.
            "entity_keys", "utterance",
            # An article is one-to-many, so it has a reader in the same sense
            # a campaign does — and it briefs from the same funnel.
            "audience_key",
            "revision_notes"),
    writes=True,
    produces="draft",
    run=_run_blog_article))
