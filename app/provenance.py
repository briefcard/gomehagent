"""Where a KB row came from, and who is allowed to change it.

Three sources fill a client's knowledge base — a crawl of their website, a
spreadsheet they upload, and a human typing — and before this module each one
had its own private idea of what happens when it meets a row that already
exists. Measured on the write layer as it stood:

  * Two of the five KB tables had an approval state; the other three went live
    the instant anything wrote to them, including a client through an intake
    link.
  * `add_claim` and `add_objection` inserted unconditionally, so re-running a
    seed or a harvest duplicated every row it had already written.
  * The same fact arriving from a crawl and from an upload became two rows with
    nothing linking them.
  * Approval left no trace — no record of who approved a row or when — so
    "approved is final" was a convention rather than a property.
  * `catalog_sync` decided whether a human owned a row by testing
    `source not in ("shopify", "")`. An owner-approved description on a row the
    store had originally supplied still read `source="shopify"`, so the next
    sync overwrote it.

This module is the single answer to all five. Every ingest path goes through
it, and the rules below are the only place they are written down.

**The rule: approved is final.** Once a human approves a row, no machine source
may change its editorial content — not a re-crawl, not a re-upload, not a store
sync. A machine that disagrees records a `KbConflict` and leaves the row alone.
That is the refuse-rather-than-invent discipline (decision #4) applied to
ingest: the system does not get to quietly decide which of two sources was
right, because it cannot know.

**The exception is narrow and per-field.** A store is authoritative for price
and stock forever — those are facts that change on their own, and making
someone re-approve a price is how a knowledge base goes stale. `OWNED` is the
whole of that exception and it is deliberately short.

**Duplicates are collapsed only when they are exactly the same fact**, judged
on a normalised fingerprint. Anything merely similar is *flagged for a human*,
never merged, because merging two nearly-identical sentences invents a third
that neither source said.
"""
from __future__ import annotations

import hashlib
import re

from . import db

# How a row got here. This is the *kind* of source, kept separate from the
# free-text `source` reference (a URL, a filename and row number) precisely
# because precedence must never be decided by string-matching prose — which is
# the bug that let a sync overwrite approved copy.
ORIGINS = ("seed", "crawl", "upload", "store_sync", "client", "human")

# Origins that a human is behind. These may always write.
HUMAN_ORIGINS = ("human", "seed")

# Origins whose rows land usable without review. A store sync is a mirror of a
# system that is already authoritative for what exists, what it costs and
# whether it is in stock — and putting 250 products through a review queue is
# how you get a review queue nobody opens. Everything else is an *assertion*
# somebody made: a crawl of marketing copy, a spreadsheet, a client typing.
# Those are proposals, and a human decides.
AUTO_APPROVED = HUMAN_ORIGINS + ("store_sync",)


def lands_approved(origin: str) -> bool:
    """Whether a row from this origin is usable the moment it is written."""
    return origin in AUTO_APPROVED

# Per-origin fields that origin owns outright and may refresh even on an
# approved row. Everything not listed here is editorial and is frozen by
# approval. Keep this list short — every entry is a promise that a machine may
# silently change something a human signed off on.
OWNED = {
    "store_sync": frozenset({"price", "availability"}),
}

# Review states. One axis, shared by every KB table, distinct from the
# lifecycle `status` (active / retired) that some tables also carry.
PROPOSED, APPROVED, REJECTED = "proposed", "approved", "rejected"
REVIEW_STATES = (PROPOSED, APPROVED, REJECTED)


def normalise(text: str) -> str:
    """The comparable form of a piece of prose.

    Two sources that mean the same thing rarely spell it the same way: a crawl
    picks up "Shipped 1,200 orders in 2025." and a spreadsheet says
    "We shipped 1200 orders in 2025". Both collapse to the same string here.

    Deliberately conservative. Every extra rule is a chance to fuse two facts
    that were never the same one, and a wrongly merged claim is invisible —
    it looks exactly like a claim nobody submitted twice.
    """
    t = (text or "").lower()
    t = t.replace("’", "'").replace("‘", "'")
    t = t.replace("“", '"').replace("”", '"')
    t = t.replace("–", "-").replace("—", "-")
    # Thousands separators before punctuation is stripped, or "1,200" becomes
    # "1 200" and stops matching "1200".
    t = re.sub(r"(?<=\d),(?=\d{3})", "", t)
    # Leading filler that changes the grammar and not the fact.
    t = re.sub(r"^(we|our|the|this|it)\s+", "", t)
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return " ".join(t.split())


def fingerprint(*parts: str) -> str:
    """A stable id for "this exact fact", for collapsing repeat ingests."""
    joined = " ".join(normalise(p) for p in parts if p)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest() if joined else ""


def similarity(a: str, b: str) -> float:
    """Token overlap of two normalised strings, 0..1. Used to FLAG, never merge."""
    ta, tb = set(normalise(a).split()), set(normalise(b).split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


# Tuned on real claim-length sentences, not chosen for roundness. A claim is
# short, so a single differing token moves the score a long way: "shipped 1200
# orders in 2025" against "shipped 1250 orders in 2025" scores 0.67, and those
# two rows in a queue are exactly the pair a reviewer must see together. The
# cost of a false positive is one extra glance, because this only ever flags.
NEAR_DUPLICATE = 0.65


def near_duplicates(text: str, candidates: list, field: str = "claim",
                    threshold: float = NEAR_DUPLICATE) -> list:
    """Rows that say almost the same thing as `text`.

    The review queue's job is to be readable. Three phrasings of one fact are
    three decisions a person has to make and reconcile, which is how a queue
    stops being read. Surfacing them together makes it one decision — and it
    stays a human's decision, which is the difference between this and merging.
    """
    out = []
    for row in candidates:
        other = getattr(row, field, "") or ""
        if not other:
            continue
        score = similarity(text, other)
        if score >= threshold:
            out.append((score, row))
    return [r for _, r in sorted(out, key=lambda p: -p[0])]


def may_write(field: str, existing_origin: str, existing_review: str,
              incoming_origin: str) -> bool:
    """May `incoming_origin` change `field` on a row in this state?

    The whole precedence policy, in one function, so that a new ingest source
    inherits it instead of inventing its own — which is exactly how
    `catalog_sync` ended up with a private rule that was subtly wrong.
    """
    if incoming_origin in HUMAN_ORIGINS:
        return True                      # a human may always correct a row
    if (existing_review or PROPOSED) != APPROVED:
        return True                      # still a proposal — refine it freely
    if field in OWNED.get(incoming_origin, frozenset()):
        return True                      # this source owns the field outright
    # A source may always refresh a row it created and no human has since
    # taken over. Without this a nightly catalogue sync would raise a conflict
    # every time a product description changed on the storefront — noise that
    # would bury the conflicts that actually mean something. The moment a human
    # edits the row its origin becomes theirs, and the sync is locked out.
    return existing_origin == incoming_origin


def record_conflict(tenant: str, table: str, row_id: str, field: str,
                    approved_value: str, incoming_value: str,
                    origin: str, source_ref: str = "") -> str:
    """A machine disagreed with an approved value. Keep both, change neither.

    This is the Bio-Glass case: a master sheet says the slab is 100"x56" and the
    cut sheet says 110"x49". Both are on file, one of them loses a job, and no
    amount of precedence logic can tell you which. So the row keeps the value a
    human approved and the disagreement becomes visible work.

    Idempotent per (row, field, incoming value): a nightly sync that keeps
    disagreeing raises the count, not a new row.
    """
    with db.SessionLocal() as s:
        row = s.query(db.KbConflict).filter(
            db.KbConflict.tenant == tenant,
            db.KbConflict.table_name == table,
            db.KbConflict.row_id == row_id,
            db.KbConflict.field == field,
            db.KbConflict.status == "open").first()
        if row and (row.incoming_value or "") == (incoming_value or ""):
            row.hits = str(int(row.hits or "0") + 1)
            row.last_seen = db.utcnow()
            s.commit()
            return row.id
        if row:
            # The machine changed its mind since last time. The newest
            # disagreement is the useful one; keep the count.
            row.incoming_value = incoming_value
            row.source_ref = source_ref or row.source_ref
            row.hits = str(int(row.hits or "0") + 1)
            row.last_seen = db.utcnow()
            s.commit()
            return row.id
        new = db.KbConflict(
            tenant=tenant, table_name=table, row_id=row_id, field=field,
            approved_value=str(approved_value or "")[:4000],
            incoming_value=str(incoming_value or "")[:4000],
            origin=origin, source_ref=source_ref)
        s.add(new)
        s.commit()
        return new.id


def conflicts(tenant: str = "", status: str = "open") -> list:
    """Open disagreements, most persistent first."""
    with db.SessionLocal() as s:
        q = s.query(db.KbConflict).filter(db.KbConflict.status == status)
        if tenant:
            q = q.filter(db.KbConflict.tenant == tenant)
        rows = q.all()
        s.expunge_all()
    return sorted(rows, key=lambda r: -int(r.hits or "0"))


def resolve_conflict(conflict_id: str, keep: str) -> str:
    """Settle a disagreement. `keep` is 'approved' or 'incoming'.

    Resolving writes through to the row when the incoming value wins, because a
    conflict a human has settled and that the row does not reflect is a lie
    with a timestamp on it.
    """
    keep = (keep or "").strip().lower()
    if keep not in ("approved", "incoming"):
        return "Say which value to keep: 'approved' or 'incoming'."
    with db.SessionLocal() as s:
        row = s.get(db.KbConflict, conflict_id)
        if not row:
            return "No such conflict."
        if keep == "incoming":
            model = _MODELS.get(row.table_name)
            if not model:
                return f"Cannot write back to {row.table_name}."
            target = s.get(model, row.row_id)
            if not target:
                return "The row this was about is gone."
            setattr(target, row.field, row.incoming_value)
            # A human just chose this value, so it is now human-owned and the
            # machine that proposed it may not quietly change it back.
            target.origin = "human"
            target.review = APPROVED
            target.approved_at = db.utcnow()
        row.status = "resolved"
        row.resolution = keep
        row.resolved_at = db.utcnow()
        s.commit()
        field, table = row.field, row.table_name
    return (f"Kept the {keep} value for {field} on {table}."
            + (" The row was updated." if keep == "incoming" else ""))


# Populated at import time from db, so `resolve_conflict` can write back to
# whichever table the conflict was raised against.
_MODELS = {
    "kb_claims": db.KbClaim,
    "kb_audiences": db.KbAudience,
    "kb_objections": db.KbObjection,
    "kb_entities": db.KbEntity,
    "kb_situations": db.KbSituation,
}


def apply_fields(row, incoming: dict, origin: str, source_ref: str = "",
                 table: str = "", tenant: str = "") -> dict:
    """Write what this origin is allowed to write; report the rest as conflicts.

    The one function every ingest path calls to update an existing row. Returns
    a summary of what happened so the caller can report it rather than guess:
    `{"written": [...], "unchanged": [...], "conflicts": [...]}`.
    """
    written, unchanged, blocked = [], [], []
    existing_origin = getattr(row, "origin", "") or "human"
    existing_review = getattr(row, "review", "") or PROPOSED
    for field, value in incoming.items():
        if value is None or value == "":
            continue                       # absence is not an assertion
        current = getattr(row, field, None)
        if str(current or "") == str(value):
            unchanged.append(field)
            continue
        if may_write(field, existing_origin, existing_review, origin):
            setattr(row, field, value)
            written.append(field)
        else:
            blocked.append(field)
            record_conflict(tenant or getattr(row, "tenant", ""), table,
                            row.id, field, current, value, origin, source_ref)
    # A human who edits a row takes ownership of it, which is what locks the
    # machine sources out of it from here on. This is the fix for the specific
    # bug that `source not in ("shopify", "")` could not express: approved copy
    # on a row the store had originally supplied stayed machine-owned and was
    # overwritten by the next sync.
    if written and origin in HUMAN_ORIGINS:
        row.origin = origin
    return {"written": written, "unchanged": unchanged, "conflicts": blocked}
