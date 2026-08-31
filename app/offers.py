"""Offers — what this brand has actually put in front of people, on file.

An offer is not knowledge about the brand and it is not craft. It is the one
thing in a send that a generator must never invent: a discount nobody
authorised, written over the client's own sending domain, at list scale. So it
is a FIELD a person fills — `OWNER_INPUT` in the skill layer — and this module
is what stops that field being blank forever on an account that has been
running promotions for years.

## Where offers live, and why not a new table

`KbEntity.type` has carried `offer` since the schema was written, beside
`product`, `space`, `service` and `collection`. An offer therefore inherits
the whole provenance machinery already: `review=PROPOSED` rows are excluded
from `kb.entities()` by default, so a proposed offer is *structurally*
unusable rather than usable-if-nobody-checks, and it lands in the same review
queue the owner already works. A second store would have meant a second
approval path, a second queue and a second thing to forget — the duplication
this codebase keeps paying for.

## The bootstrap, and its honest limit

`harvest` reads what this account has ALREADY SENT and proposes the offers it
finds. That is what lets an existing brand start with a populated shelf
instead of typing its own history back in.

It is deliberately **deterministic** — patterns, not a model. Two reasons, and
the second is the real one. An offer has a recognisable shape ("20% off",
"free shipping", "buy one get one"), so a model buys little; and a model
reading our own past output to propose rows that shape our future output is a
loop with nothing outside it. The proposals still land PROPOSED and a person
still decides, but the thing being proposed is a QUOTE from a real send rather
than a paraphrase, and the evidence is the sentence it came from.

The limit, stated: this finds offers that were STATED in copy. An offer that
lived only in a discount code never written into an email is not here, and no
amount of reading our own sends will find it. That is a real gap and it is
closed by typing it in, not by guessing.
"""
from __future__ import annotations

import datetime as dt
import re

from . import db, kb
from . import provenance as prov

#: How an offer is written, in the shapes a promotion actually takes. Anchored
#: on the CONCRETE part — a number, a currency, a named freebie — because
#: "special" and "exclusive" are adjectives every email uses and matching them
#: would propose the whole archive as offers.
_PATTERNS = (
    re.compile(r"\b\d{1,2}\s?%\s*(?:off|discount|savings?)\b", re.I),
    re.compile(r"\b(?:save|take)\s*(?:an?\s+extra\s+)?\d{1,2}\s?%", re.I),
    re.compile(r"[£$€]\s?\d+(?:\.\d{2})?\s*(?:off|discount)\b", re.I),
    re.compile(r"\b(?:save|take)\s*[£$€]\s?\d+(?:\.\d{2})?", re.I),
    re.compile(r"\bfree\s+(?:shipping|delivery|returns?|gift|sample)\b", re.I),
    re.compile(r"\bcomplimentary\s+\w+", re.I),
    re.compile(r"\bbuy\s+(?:one|two|\d+)\s*,?\s*get\s+(?:one|two|\d+|\w+\s+)"
               r"(?:free|half)\b", re.I),
    re.compile(r"\bbogo\b", re.I),
    re.compile(r"\b\d+\s+for\s+(?:the\s+price\s+of\s+\d+|[£$€]\s?\d+)", re.I),
)

#: A sentence longer than this is prose that happens to contain a number, not
#: an offer line. Kept generous — offers are stated plainly, and the cap is
#: here to stop a whole paragraph becoming an entity `name`.
MAX_LEN = 160

#: Never propose more than this from one sweep. An account with four years of
#: sends should produce a shortlist a person will actually read, not a queue
#: they close. The most recent win, because a stale promotion is the one least
#: worth re-running.
MAX_PROPOSALS = 12


def phrases(text: str) -> list[str]:
    """The offer statements in one body, as they were written.

    Returns the SENTENCE, not the matched fragment: "20% off" is not an offer,
    "20% off everything in the Aqua range until Sunday" is. A reviewer
    approving a fragment would be approving something they cannot check.
    """
    out: list[str] = []
    for raw in re.split(r"(?<=[.!?])\s+|\n+", str(text or "")):
        line = " ".join(raw.split()).strip(" -–—•|")
        if not line or len(line) > MAX_LEN or line.endswith("?"):
            continue
        if any(p.search(line) for p in _PATTERNS):
            out.append(line)
    return list(dict.fromkeys(out))


def _key(phrase: str) -> str:
    """A stable slug for one offer, from its comparable form.

    `prov.normalise` is what the knowledge base already uses to decide two
    strings are the same fact, so an offer re-stated with different
    punctuation across two sends is one row rather than two.
    """
    base = re.sub(r"[^a-z0-9]+", "-", prov.normalise(phrase)).strip("-")
    return ("offer-" + base)[:60].rstrip("-")


def known(tenant: str, include_proposed: bool = False) -> list:
    """The offers on file. Approved only, unless a reviewer asks for the rest."""
    return kb.entities(tenant, type="offer", available_only=False,
                       include_proposed=include_proposed)


def harvest(tenant: str, *, days: int = 730, apply: bool = False) -> dict:
    """Propose offers from what this account has already sent.

    `apply=False` REPORTS, like every sweep in this codebase that can write —
    a bootstrap that silently files fifteen rows the first time somebody
    presses it is a surprise, and this one runs against years of archive.

    Every proposal carries the campaign it was found in and the date it went
    out, because "is this offer still one we run" is the question a reviewer
    is actually being asked and they cannot answer it from the words alone.
    """
    since = db.utcnow() - dt.timedelta(days=days)
    with db.SessionLocal() as s:
        rows = (s.query(db.Output)
                .filter(db.tenant_filter(db.Output, tenant),
                        db.Output.format == "campaign_email",
                        db.Output.created_at >= since)
                .order_by(db.Output.created_at.desc()).all())
        sends = [(r.id, r.body or "", db.as_utc(r.created_at),
                  r.audience_key or r.angle or "", r.entity_key or "")
                 for r in rows]
        s.expunge_all()

    found: dict[str, dict] = {}
    for oid, body, at, segment, entity in sends:
        for ph in phrases(body):
            k = _key(ph)
            if not k or k == "offer":
                continue
            hit = found.setdefault(k, {
                "key": k, "phrase": ph, "times_seen": 0, "segments": [],
                "entities": [], "last_seen": at, "output_id": oid})
            hit["times_seen"] += 1
            if segment and segment not in hit["segments"]:
                hit["segments"].append(segment)
            if entity and entity not in hit["entities"]:
                hit["entities"].append(entity)

    ranked = sorted(found.values(),
                    key=lambda h: (h["last_seen"], h["times_seen"]),
                    reverse=True)[:MAX_PROPOSALS]
    on_file = {e.key for e in known(tenant, include_proposed=True)}
    fresh = [h for h in ranked if h["key"] not in on_file]

    filed = 0
    if apply:
        for h in fresh:
            said = kb.add_entity(
                tenant, "offer", h["key"], h["phrase"][:200],
                description=h["phrase"],
                attributes={"seen_with_segments": h["segments"],
                            "seen_with_entities": h["entities"],
                            "times_seen": h["times_seen"],
                            "last_seen": h["last_seen"].date().isoformat()},
                source=(f"stated in a campaign sent "
                        f"{h['last_seen'].date().isoformat()} "
                        f"({h['output_id'][:12]})"),
                origin="harvest", review=prov.PROPOSED)
            if not str(said).lower().startswith(("an entity", "unknown")):
                filed += 1

    return {"ok": True, "sends_read": len(sends),
            "found": len(found), "proposals": fresh, "already_on_file":
                len(ranked) - len(fresh), "filed": filed, "applied": apply,
            "note": ("" if apply else
                     "nothing was written — press apply to file these for "
                     "review")}


def applicable(tenant: str, *, segment: str = "",
               entity_keys: tuple | list = ()) -> dict:
    """The offer most likely to fit THIS send, and whether it may be used.

    Ranked, never invented: the shelf is what a person approved (or what the
    bootstrap proposed and a person has yet to decide). Preference order is
    the honest one — an offer this cohort has actually been given before,
    then one used with a product this send features, then the most recent.

    Returns `usable=False` for a proposal, and the caller is expected to say
    so on the artifact rather than quietly drop it: an offer that fits and is
    merely unapproved is a decision waiting for the owner, not an absence.
    """
    ents = set(k for k in (entity_keys or []) if k)
    best, best_rank, proposed_seen = None, None, False
    for row in known(tenant, include_proposed=True):
        attrs = row.attributes or {}
        approved = (row.review or "") == prov.APPROVED
        if not approved:
            proposed_seen = True
        seg_hit = segment and segment in (attrs.get("seen_with_segments") or [])
        ent_hit = bool(ents & set(attrs.get("seen_with_entities") or []))
        # Approved first, always — a usable offer outranks a better-matching
        # one the owner has not signed off, because the second cannot ship.
        rank = (approved, bool(seg_hit), ent_hit,
                str(attrs.get("last_seen") or ""), int(attrs.get("times_seen") or 0))
        if best_rank is None or rank > best_rank:
            best, best_rank = row, rank
    if best is None:
        return {"ok": False, "offer": "", "usable": False, "key": "",
                "why": ("no offer is on file for this account — sweep the "
                        "sends you have already made, or type the offer on "
                        "the plan")
                       if not proposed_seen else "no offer matched"}
    approved = (best.review or "") == prov.APPROVED
    attrs = best.attributes or {}
    why = ("last used " + str(attrs.get("last_seen") or "previously")
           + (f", with this cohort" if segment and segment in
              (attrs.get("seen_with_segments") or []) else "")
           + (f", {attrs.get('times_seen')}× in all"
              if attrs.get("times_seen") else ""))
    return {"ok": True, "offer": best.description or best.name,
            "key": best.key, "usable": approved, "why": why,
            "review": best.review or ""}
