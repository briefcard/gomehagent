"""The knowledge base, rendered for the path that answers customers.

The wiring audit's worst finding was not a bug, it was an absence:
`resolve.resolve` had exactly ONE caller — the skill substrate — so every claim,
objection and piece of brand guidance the owner had approved reached work that
ran through a registered skill and nothing else. The inbound mail path, which
is the one that drafts a reply to a real customer every morning, drafted from a
hardcoded prompt and a substring check. The owner had been approving knowledge
for months that could not reach the drafts he read.

This module is the join. It resolves the bundle for one inbound email, renders
it for a prompt, and checks the draft that comes back against it.

**Enrich, never gatekeep.** The owner's own correction, and it is load-bearing
here more than anywhere: *"There should be NO block because of a lack of data.
If it's not there, then don't use it."* A thin bundle produces a thinner block
and a labelled draft. The only thing that stops a reply is a phrase the account
has banned — which makes the output FALSE rather than merely thinner.

**Offered, not asserted.** Claims go into the prompt with their ids and an
instruction to cite the ones actually used. A model may not invent an id: what
comes back is intersected with what went out (`verify`), because an id that was
never offered is either a hallucination or a stale bundle, and both must fail
the same way.

**It renders what a person would need to answer.** Objections first — a
pre-approved answer to the exact hesitation is worth more than any amount of
proof — then the claims that substantiate, then the catalogue, then what must
be looked up live rather than remembered.
"""
from __future__ import annotations

#: The system key the mail path files everything under. One constant, because
#: it is used by the run, the assurance record and the guidance lookup, and
#: three string literals drift.
SYSTEM_KEY = "inbox_triage"

#: Buckets that never produce a reply, so resolving a bundle for them buys
#: nothing and costs real money.
#:
#: A tier-3 resolve runs a semantic search over the archive — an embedding call
#: — plus a dozen queries, and roughly half of inbound is a newsletter or a
#: platform notification. Grounding those would have doubled down on the exact
#: problem already on the watch list: triage is 93% of model spend, and the
#: cheap classifier that routes it does not filter it. The bucket is computed
#: BEFORE the drafting loop for model routing, so this costs nothing to check.
#:
#: Named as a list of what to SKIP rather than what to ground, deliberately: a
#: new bucket should default to being grounded. Getting a reply that is thinner
#: than it needed to be is a bad day; silently dropping the knowledge base from
#: a bucket somebody added last week is the defect this whole pass exists to
#: close.
NO_REPLY_BUCKETS = ("notifications", "promo", "sales_orders")

#: How much of an inbound email is used to situate it. The subject plus the top
#: of the body is what a person reads to decide what the mail is about; the
#: signature and quoted history below it match every situation equally and
#: would make the detection worse, not better.
UTTERANCE_CHARS = 700


def utterance_from(email: dict) -> str:
    """What to match this mail against."""
    subject = (email.get("subject") or "").strip()
    body = (email.get("body") or "").strip()
    return f"{subject}\n{body[:UTTERANCE_CHARS]}".strip()


def for_mail(tenant: str, email: dict, bucket: str = "") -> dict:
    """Resolve everything the mail path can be grounded in.

    Never raises. A knowledge layer that can take down the inbox is worse than
    one that is absent for a cycle, and the failure is REPORTED in `thin` so a
    draft written without the bundle is not mistaken for one written with it.

    `bucket` is the cheap classifier's verdict, already computed for model
    routing. A bucket that never replies is skipped — see `NO_REPLY_BUCKETS`.
    """
    out = {"bundle": {}, "text": "", "claim_ids": [], "thin": [],
           "grounding": "none", "error": "", "skipped": ""}
    if not tenant:
        out["thin"] = ["this inbox is not mapped to an account, so no "
                       "knowledge base could be reached at all"]
        return out
    if bucket and bucket in NO_REPLY_BUCKETS:
        # Not a gap and NOT reported as one: nothing was missing, we chose not
        # to look. Filing it under `thin` would put "we did not ground a
        # newsletter" on the knowledge backlog for ever.
        out["skipped"] = f"{bucket} needs no reply, so no bundle was resolved"
        return out
    try:
        from . import replies as _rep
        from . import resolve as rs
        # SCOPED TO THE SYSTEM THAT OWNS THIS REPLY, not to the path that
        # found it.
        #
        # Every bundle carries `rules.guidance` — what this pipeline has been
        # taught, scoped to the system, because a lesson learned answering
        # support mail must not quietly change how the ad copy reads. This
        # path resolved under `inbox_triage`, which is not a key in
        # `systems.CATALOG` at all, so `guidance_block` looked up a system
        # that does not exist and returned "". The owner could type standing
        # guidance on the Lead responder or Service desk page — the two
        # systems that answer real customer mail every morning — and it
        # reached nothing.
        #
        # `replies.route` already answers "which system owns a reply to this
        # kind of mail" and is what decides who may reply at all, so the
        # bundle is scoped by the same answer rather than a second one.
        # ADDITIVE, never instead of. `inbox_triage` renders its own page on
        # the Systems board, so guidance typed there is a real instruction for
        # the whole inbox and swapping the scope would have silently stopped
        # reading it. Both threads are carried: what was said to the inbox,
        # and what was said to the system that owns this kind of mail.
        system = _rep.route(bucket)
        bundle = rs.resolve(tenant, system=system,
                            utterance=utterance_from(email), tier=3,
                            guidance_also=(SYSTEM_KEY,))
        out["system_key"] = system
    except Exception as exc:                                     # noqa: BLE001
        out["error"] = f"{exc.__class__.__name__}: {str(exc)[:160]}"
        out["thin"] = [f"the knowledge base could not be read ({out['error']})"]
        return out

    out["bundle"] = bundle
    out["claim_ids"] = [c["claim_id"] for c in (bundle.get("claims") or [])
                        if c.get("claim_id")]
    out["grounding"] = (bundle.get("grounding") or {}).get("level", "none")
    # `blocked_on` from resolve is a LABEL here, not a veto — the mail path
    # must answer the customer either way. The one genuinely unsafe case (no
    # ban list) is handled by the validator refusing to bless the draft, not by
    # refusing to write one.
    out["thin"] = list(bundle.get("blocked_on") or []) + [
        g.get("missing", "") for g in (bundle.get("gaps") or []) if g.get("missing")]
    out["text"] = render(bundle)
    return out


def render(bundle: dict) -> str:
    """The bundle as prompt text, in the order a person would use it."""
    if not bundle:
        return ""
    parts: list[str] = []

    objections = bundle.get("objections") or []
    if objections:
        parts.append(
            "\nAPPROVED ANSWERS to hesitations like this one. These have been "
            "reviewed and signed off — prefer them over anything you would "
            "compose yourself, adapting only the wording to this thread:")
        for o in objections[:3]:
            parts.append(f'- They may be thinking: "{o.get("objection", "")}"'
                         + (f'\n  Approved answer: {o["response"]}'
                            if o.get("response") else ""))
            for sup in (o.get("support") or [])[:2]:
                parts.append(f'    · backed by [{sup["claim_id"]}] {sup["claim"]}')

    claims = bundle.get("claims") or []
    if claims:
        parts.append(
            "\nAPPROVED CLAIMS you may state as fact. Each carries an id. "
            "Use only what the thread actually calls for, and list the ids of "
            "the ones you used in claim_ids — an uncited draft cannot be "
            "traced back to what made it true:")
        for c in claims[:6]:
            line = f'- [{c["claim_id"]}] {c["claim"]}'
            if c.get("evidence"):
                line += f'\n  (evidence: {c["evidence"]})'
            scope = c.get("scope") or "brand-wide"
            line += f"\n  (true of: {scope})"
            parts.append(line)

    ents = bundle.get("entities") or []
    if ents:
        # `fits` is tri-state on purpose in `kb.match_entities` and it is
        # rendered as such: False is "this does not meet what they asked",
        # None is "nothing on file says either way". Flattening the second into
        # the first would answer a question the catalogue cannot answer.
        parts.append("\nCATALOGUE — what is on file. Never state a price or a "
                     "stock level from here without a live lookup; these are "
                     "catalogue records, not the store:")
        for e in ents[:5]:
            line = f'- {e.get("name", "")}'
            if e.get("fits") is False:
                line += f' — DOES NOT MEET what was asked ({e.get("basis", "")})'
            elif e.get("fits") is None and e.get("basis") == "unknown":
                line += " — nothing on file says whether this fits"
            if e.get("description"):
                line += f': {e["description"][:180]}'
            parts.append(line)

    # Live facts, and the reason they are not in the block above.
    needs = bundle.get("needs_lookup") or []
    if needs:
        parts.append(
            "\nDO NOT ANSWER THESE FROM MEMORY — they are true at the moment "
            "of asking and stale by lunchtime. Call the tool, or say you will "
            "confirm and follow up:")
        for n in needs[:5]:
            why = "" if n.get("ready") else f' (cannot run: {n.get("blocked_because", "")})'
            parts.append(f'- {n.get("returns") or n.get("tool", "")}{why}')

    # What we said before that may have gone off.
    per = bundle.get("perishable") or []
    if per:
        parts.append(
            "\nWE SAID THIS BEFORE AND IT MAY HAVE AGED. It was true when it "
            "was sent; do not repeat it without checking:")
        for p in per[:3]:
            parts.append(f'- (said {p.get("said_on", "")}) {p.get("body", "")}'
                         + (f'\n  {p["warning"]}' if p.get("warning") else ""))

    corr = bundle.get("correspondence") or []
    if corr:
        parts.append("\nEARLIER CORRESPONDENCE AND DOCUMENTS on file that look "
                     "relevant (this is the years of history that predate the "
                     "thread in front of you):")
        for h in corr[:3]:
            if h.get("kind") == "document" or h.get("filename"):
                parts.append(f'- document: {h.get("filename", "")}'
                             + (f' ({h["doc_type"]})' if h.get("doc_type") else ""))
                continue
            parts.append(f'- thread: {h.get("subject", "")}'
                         + (f' — from {h["from"]}' if h.get("from") else ""))
            for d in (h.get("attachments") or [])[:3]:
                parts.append(f'    · attached: {d.get("filename", "")}')

    # What this pipeline has been TAUGHT, which rides on the rules block.
    #
    # It is rendered here rather than left to the caller, and that is not a
    # style choice — it is the bug this renderer shipped with for an hour.
    # `resolve._rules` appends the guidance to `rules["block"]`, which every
    # SKILL injects; the mail path does not inject that block, it builds its
    # own identity prose from `tenants.agent_block`. So the guidance reached
    # every consumer except the one it was written for, and each piece tested
    # green on its own. The end-to-end stub is what caught it.
    #
    # Only `guidance`, never the whole block: the caller already has the
    # identity prose, and injecting it twice is how a prompt starts
    # contradicting itself.
    guidance = ((bundle.get("rules") or {}).get("guidance") or "").strip()
    # Borrowed technique, last and labelled — see `app/craft.py`.
    craft = (bundle.get("craft") or "").strip()

    if not parts and not guidance and not craft:
        return ""
    head = ("\n\n=== WHAT THIS ACCOUNT KNOWS ===\n"
            "Everything below has been approved by the owner. It is what you "
            "are allowed to assert. Nothing here overrides the hard rules.\n"
            + "\n".join(parts)) if parts else ""
    return (head + (f"\n{guidance}" if guidance else "")
            + (f"\n{craft}" if craft else ""))


def verify(offered: list[str], claimed) -> list[str]:
    """Which cited ids were actually offered.

    A model may not introduce a claim id. One that was never in the prompt is
    either invented or read off a stale bundle, and both have to fail the same
    way — a draft carrying an id nothing can resolve is worse than an uncited
    one, because it LOOKS traceable.
    """
    if not claimed:
        return []
    if isinstance(claimed, str):
        claimed = [c.strip() for c in claimed.replace(",", " ").split()]
    allowed = set(offered or [])
    return [c for c in claimed if isinstance(c, str) and c.strip() in allowed]
