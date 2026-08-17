"""How an agent turns "I don't know this" into something a human can approve.

The old behaviour was to ask. A question in the operator's inbox is a dead end:
it interrupts, it gets answered once in a sentence nobody keeps, and the next
time the same question arrives the agent asks again. Nothing accumulates.

A proposal is the same instinct with a memory. The agent drafts what it thinks
the answer is, files it against the thread that prompted it, and a human either
approves it — at which point every future system answers that question without
asking anyone — or corrects it, which is a better correction than a chat reply
because it lands on the row rather than in a conversation.

Nothing here lands usable. `origin="agent"` is not in `AUTO_APPROVED`, so every
row written through this file is `PROPOSED` and invisible to selection until
somebody signs it off. That is not a limitation to work around; it is the only
reason an agent may write to the knowledge base at all.

**Provenance points back at the thread.** A reviewer reading "should we say we
ship to Canada in 3 days?" needs to know a customer asked it on Tuesday and
what exactly they asked. A proposal with no source is a suggestion; a proposal
with a source is evidence.
"""
from __future__ import annotations

from . import kb

#: The agent may widen the vocabulary this many times per review cycle before
#: the honest answer stops being "add a tag" and becomes "this account's
#: vocabulary is wrong". `kb.MAX_NEW_SITUATIONS` says the same thing about
#: crawls; an agent deserves the same ceiling.
MAX_SITUATION_PROPOSALS = 3


def objection(tenant: str, question: str, answer: str, *,
              source_ref: str = "", situations: list[str] | None = None,
              entity_key: str = "") -> dict:
    """"A customer asked this and we have no approved answer" — with a draft.

    The highest-value thing an agent can file. Objections are the field that
    blocks most accounts, they can only come from someone who has met the
    question, and an agent reading the inbox meets them all day.
    """
    question = (question or "").strip()
    answer = (answer or "").strip()
    if not question:
        return {"ok": False, "why": "a proposal needs the question that was asked"}
    if not answer:
        return {"ok": False, "why": ("propose an ANSWER, not just a gap. A "
                                     "reviewer approving a blank has done the "
                                     "work themselves.")}
    msg = kb.add_objection(
        tenant, question[:300], answer[:900],
        situations=[s for s in (situations or []) if s],
        entity_key=entity_key, origin="agent",
        source=source_ref or "proposed by an agent while drafting")
    already = "Already on file" in msg
    return {
        "ok": True, "kind": "objection", "duplicate": already,
        "message": msg.splitlines()[0] if msg else "",
        "review_at": "/admin/ui?tab=content",
        # Approval will REFUSE an unscoped objection until the reviewer says
        # whether it is true of one product or of everything. Saying so here
        # turns a confusing rejection later into a decision the agent can
        # front-load — it usually knows, because it just read the thread.
        "scope": entity_key or "unscoped",
        "needs_at_approval": ([] if entity_key else
                              ["pick the product this is true of, or confirm "
                               "brand-wide — an answer approved with no scope "
                               "is claimed of everything this account sells"]),
        "note": ("nothing is usable yet — an agent proposal is PROPOSED by "
                 "construction and stays invisible to every system until a "
                 "human approves it")}


def claim(tenant: str, text: str, evidence: str, *, source_ref: str = "",
          situations: list[str] | None = None, entity_key: str = "") -> dict:
    """A fact the account appears to rely on but has never written down.

    Evidence is required and that is the point: an agent that cannot say WHERE
    a fact came from is proposing a belief, and beliefs are what the ban list
    exists to catch.
    """
    text = (text or "").strip()
    if not text:
        return {"ok": False, "why": "nothing to propose"}
    if not (evidence or "").strip():
        return {"ok": False, "why": ("a claim needs evidence — where this was "
                                     "said, measured or agreed. Without it a "
                                     "reviewer cannot check it and is being "
                                     "asked to take a machine's word.")}
    msg = kb.add_claim(
        tenant, text[:400], evidence[:300],
        [s for s in (situations or []) if s], proof_type="data",
        source=source_ref or "proposed by an agent while drafting",
        status="pending", origin="agent", entity_key=entity_key)
    return {"ok": True, "kind": "claim",
            "duplicate": "Already on file" in msg,
            "message": msg.splitlines()[0] if msg else "",
            "review_at": "/admin/ui?tab=content"}


def situation(tenant: str, tag: str, description: str, *,
              source_ref: str = "") -> dict:
    """A kind of question this account keeps getting and has no name for.

    Refused when the vocabulary already covers it — `add_situation` checks a
    near-synonym for any non-human origin, because a vocabulary of
    `pricing` / `price_worry` / `cost_concern` is worse than a short one:
    selection splits across them and no single tag accumulates the approved
    examples the tagger learns from.
    """
    tag = (tag or "").strip().lower().replace(" ", "_")
    if not tag:
        return {"ok": False, "why": "a situation needs a tag"}
    if not (description or "").strip():
        return {"ok": False, "why": ("describe what it MEANS. A bare tag is "
                                     "unreviewable and untaggable — nobody "
                                     "else can apply it consistently.")}
    msg = kb.add_situation(tenant, tag, patterns=[],
                           description=description.strip()[:200],
                           origin="agent",
                           source=source_ref or "proposed by an agent")
    refused = "Not added" in msg or "already has" in msg
    return {"ok": not refused, "kind": "situation", "message": msg,
            "why": (msg if refused else ""),
            "note": ("the vocabulary already covers this — use the existing "
                     "tag" if refused else
                     "proposed; it cannot tag anything until approved")}


def from_gap(tenant: str, gap: dict, *, source_ref: str = "") -> dict:
    """Turn one `resolve()` gap straight into the proposal that would close it.

    The bundle already names what is missing and what would fix it. This is the
    short path from reading that to filing it, so an agent does not have to
    work out which of three functions applies.
    """
    missing = (gap or {}).get("missing", "")
    if "objection" in missing:
        return {"ok": False, "needs": ["question", "answer"],
                "call": "propose.objection",
                "why": "an objection proposal needs the question and a draft "
                       "answer — this function cannot invent either"}
    if "situation" in missing:
        return {"ok": False, "needs": ["tag", "description"],
                "call": "propose.situation"}
    return {"ok": False, "why": f"no proposal shape for {missing!r}",
            "note": "some gaps are for a human to fill, not a machine to guess"}
