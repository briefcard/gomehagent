"""The correspondence archive, made answerable instead of merely catalogued.

This closes the failure that made inbox drafts untrustworthy, and it was never
a reasoning failure. `EmailLog` recorded that a message arrived — sender,
subject, what the agent did — and not a word of what was said. `DocIndex`
recorded that a bill of lading exists and not what was on it. So an agent
asked to reference a prior thread had two options: ask, or guess. Both look
like a stupid model and both are a storage problem.

Three things make an archive answerable rather than searchable:

**The text has to be kept.** Obvious in hindsight; the extraction was already
happening in `read_email_attachment` and being thrown away.

**Quoted history has to go first.** A fifteen-message thread where everyone
top-posts is fifteen rows that all embed as whatever the first message said.
`email_harvest._own_words` already solves this and is reused rather than
rewritten.

**Meaning has to beat keywords.** "The pallet damage" and "the broken crates
from the March shipment" are the same event with no words in common. Gmail
search returns nothing and the agent asks a question it should not have had to
ask. That is the whole reason this indexes rather than greps.

Long documents are chunked, and the chunk index rides in `row_id` as
`<id>#<n>` — no schema change, because `KbEmbedding` is keyed on
(tenant, kind, row_id) and that is still unique per chunk. Without chunking a
forty-page contract embeds as its title page and nothing in it is findable.
"""
from __future__ import annotations

import logging
import re

from . import db, embed

log = logging.getLogger("archive")

#: Long enough to hold a real message or a page of a document, short enough
#: that one chunk is about one thing. A chunk covering three topics retrieves
#: for all of them and is precise about none.
CHUNK_CHARS = 1800

#: Bounded on the way in. The archive is for finding and quoting, not for
#: replacing the mail store — the id is kept so the full thing is one fetch
#: away when someone actually needs it.
MAX_STORED = 12000

#: Buckets nobody will ever ask a question about. Deliberately NARROWER than
#: `email_harvest.EXCLUDED`, and the difference is the point: mining excludes
#: `sales_orders` and `urgent_money` so a customer's words are not mined as
#: brand claims, which says nothing about whether anyone will later ask "what
#: did we ship on order 10432" or "what did the bank say". Those belong in an
#: archive. A marketing blast does not — it has content, it is simply content
#: nobody will ever look for, and indexing it spends money to make real threads
#: harder to find.
SKIP_BUCKETS = frozenset({"promo", "notifications", "subscriptions"})

#: Only pure acknowledgements. This started at 120 and was wrong: the suite's
#: own realistic thread — "Confirming the crates arrived broken on the March
#: shipment. We agreed to credit the damaged units on the next invoice." — is
#: 118 characters, and dropping it would have discarded a commitment while
#: reporting success.
#:
#: The asymmetry decides the number. Keeping "Thanks!" costs one weak vector
#: that will never outrank a substantive one; dropping "Yes, we can ship by
#: Friday" (27 chars) loses a promise somebody made. So the floor removes
#: acknowledgements and nothing else — bucket and sender do the real filtering.
MIN_INDEXABLE_CHARS = 20

#: Nothing sent from these is a conversation.
AUTOMATED_SENDER = re.compile(
    r"(no[-_.]?reply|do[-_.]?not[-_.]?reply|mailer-daemon|postmaster|"
    r"bounce|notification[s]?@|automated@)", re.I)


def indexable(bucket: str, sender: str, text: str) -> tuple[bool, str]:
    """Is this worth keeping, and if not, why not.

    Returns a REASON rather than a bare False so the backfill can report what
    it declined and you can disagree with it. A filter that silently drops mail
    is indistinguishable from one that is broken.
    """
    if (bucket or "").strip().lower() in SKIP_BUCKETS:
        return False, f"{bucket} — nobody asks a question about this"
    if sender and AUTOMATED_SENDER.search(sender):
        return False, "automated sender — not a conversation"
    body = (text or "").strip()
    if len(body) < MIN_INDEXABLE_CHARS:
        return False, (f"{len(body)} chars — too short to answer anything, "
                       f"and it would dilute every search")
    return True, ""


def clean(text: str) -> str:
    """Only what the sender actually typed, quoted history removed."""
    try:
        from .email_harvest import _own_words
        return (_own_words(text or "") or "").strip()
    except Exception:  # noqa: BLE001 — never fail indexing on a parse
        return (text or "").strip()


def chunks(text: str, size: int = CHUNK_CHARS) -> list[str]:
    """Split on paragraphs, then hard-wrap anything still oversized."""
    out, buf = [], ""
    for para in (text or "").split("\n\n"):
        para = para.strip()
        if not para:
            continue
        if len(buf) + len(para) + 2 <= size:
            buf = f"{buf}\n\n{para}" if buf else para
        else:
            if buf:
                out.append(buf)
            while len(para) > size:
                out.append(para[:size])
                para = para[size:]
            buf = para
    if buf:
        out.append(buf)
    return out or []


def store_email(tenant: str, gmail_message_id: str, body: str) -> int:
    """Keep what an email said. Returns characters stored."""
    text = clean(body)[:MAX_STORED]
    if not text:
        return 0
    with db.SessionLocal() as s:
        row = (s.query(db.EmailLog)
               .filter(db.EmailLog.gmail_message_id == gmail_message_id).first())
        if not row:
            return 0
        row.body_excerpt = text
        s.commit()
    return len(text)


def store_document(tenant: str, doc_id: str, text: str) -> int:
    with db.SessionLocal() as s:
        row = (s.query(db.DocIndex)
               .filter(db.tenant_filter(db.DocIndex, tenant, include_unassigned=True),
                       db.DocIndex.id == doc_id).first())
        if not row:
            return 0
        row.text_excerpt = (text or "").strip()[:MAX_STORED]
        s.commit()
        return len(row.text_excerpt or "")


def _index(tenant: str, kind: str, row_id: str, text: str) -> tuple[int, str]:
    parts = chunks(text)
    wrote, why = 0, ""
    for i, part in enumerate(parts):
        ok, note = embed.ensure(tenant, kind, f"{row_id}#{i}", part)
        if ok:
            wrote += 1
        elif note not in ("unchanged", "nothing to embed"):
            why = why or note
    return wrote, why


def index(tenant: str, kind: str = "thread", limit: int = 200) -> dict:
    """Embed stored correspondence so it can be found by meaning.

    Reports rather than raises, and counts `no_text` apart from `skipped`:
    "nothing has been stored yet" and "already indexed" are opposite problems
    and lumping them was a defect once already.
    """
    if kind not in ("thread", "document"):
        return {"error": "kind must be thread or document"}

    with db.SessionLocal() as s:
        if kind == "thread":
            rows = (s.query(db.EmailLog)
                    .filter(db.tenant_filter(db.EmailLog, tenant))
                    .order_by(db.EmailLog.seen_at.desc()).limit(limit).all())
            items = [(r.id, f"{r.subject or ''}\n\n{r.body_excerpt or ''}".strip(),
                      r.category or "", r.sender or "") for r in rows]
        else:
            rows = (s.query(db.DocIndex)
                    .filter(db.tenant_filter(db.DocIndex, tenant))
                    .order_by(db.DocIndex.created_at.desc()).limit(limit).all())
            # A filed document is there because somebody filed it — no bucket
            # filter applies, only the length floor.
            items = [(r.id, f"{r.filename or ''} {r.anchor or ''}\n\n"
                            f"{r.text_excerpt or ''}".strip(), "", "")
                     for r in rows]
        s.expunge_all()

    wrote = chunked = no_text = 0
    why = ""
    declined: dict[str, int] = {}
    for row_id, text, bucket, sender in items:
        body = text.split("\n\n", 1)[1] if "\n\n" in text else ""
        if not body.strip():
            no_text += 1
            continue
        ok, reason = indexable(bucket, sender, body)
        if not ok:
            key = reason.split("—")[0].strip() or reason
            declined[key] = declined.get(key, 0) + 1
            continue
        n, err = _index(tenant, kind, row_id, text)
        wrote += n
        chunked += 1
        why = why or err
    return {
        "tenant": tenant, "kind": kind, "rows": len(items),
        "indexed_rows": chunked, "chunks_written": wrote,
        "no_text_stored": no_text, "declined": declined,
        "declined_total": sum(declined.values()), "why": why,
        "note": ("" if not no_text else
                 f"{no_text} rows are catalogued but hold no text — those are "
                 f"findable by subject and unanswerable in content, which is "
                 f"the gap this exists to close"),
    }


def search(tenant: str, query: str, kinds: tuple[str, ...] = ("thread", "document"),
           limit: int = 5) -> dict:
    """Find prior correspondence by meaning, and say how much was searched.

    The coverage half is not decoration. The original failure was a search that
    silently returned a fraction of the archive, so an agent reported an answer
    with no idea it had seen a slice — which reads exactly like diligence.
    """
    # Coverage is tracked PER KIND. Collapsing it into one flag meant an
    # un-indexed document store made a perfectly good thread search report as
    # "NOT searched" — so a reader would conclude nothing had been looked at
    # while holding the right answer. Absence collapsed into a value, again,
    # and in the one field whose whole job is to be trustworthy.
    hits, scanned, per_kind = [], 0, {}
    for kind in kinds:
        rows, why, stat = embed.search(tenant, kind, query, limit=limit * 2)
        scanned += stat.get("scanned", 0)
        per_kind[kind] = {"searched": not why, "why": why,
                          "chunks": stat.get("scanned", 0)}
        for h in rows:
            base, _, part = h["row_id"].partition("#")
            hits.append({**h, "row_id": base, "kind": kind,
                         "chunk": int(part) if part.isdigit() else 0})

    # One row, one hit: a long thread that chunks into six pieces should not
    # crowd out five other threads because it happened to be long.
    best: dict[str, dict] = {}
    for h in hits:
        key = f"{h['kind']}:{h['row_id']}"
        if key not in best or h["score"] > best[key]["score"]:
            best[key] = h
    ranked = sorted(best.values(), key=lambda h: -h["score"])[:limit]

    searched = [k for k, v in per_kind.items() if v["searched"]]
    missed = {k: v["why"] for k, v in per_kind.items() if not v["searched"]}
    return {
        "hits": _hydrate(tenant, ranked),
        "searched_kinds": searched,
        "unsearched_kinds": missed,
        # Kept for callers that only want a yes/no, but it now means "SOMETHING
        # could not be searched", never "nothing was".
        "degraded": "; ".join(f"{k}: {w}" for k, w in missed.items()),
        "chunks_scanned": scanned,
        "coverage": (
            f"searched every indexed chunk of {', '.join(searched)}"
            + (f"; did NOT search {', '.join(missed)}" if missed else "")
            if searched else
            f"NOT searched — {'; '.join(missed.values())}"),
    }


def _passage(text: str, n: int) -> str:
    """The chunk that actually matched, not the start of the document.

    Chunking found Clause 9 on page nine and hydration was handing back the
    title page — which is the very failure this module exists to fix, rebuilt
    one layer up. Re-chunking is deterministic, so index `n` is the same
    passage that was embedded.
    """
    parts = chunks(text or "")
    if 0 <= n < len(parts):
        # The WHOLE chunk, not the first 600 characters of it. Truncating here
        # rebuilt the exact bug this fixes: retrieval correctly found the chunk
        # containing "Clause 9", and the excerpt cut it off before reaching it.
        # A chunk is already bounded by CHUNK_CHARS — that IS the unit of
        # relevance, and slicing it again just hides the answer more subtly.
        return parts[n]
    return (text or "")[:CHUNK_CHARS]


def _hydrate(tenant: str, hits: list[dict]) -> list[dict]:
    """Turn ids back into something a reader can act on."""
    out = []
    with db.SessionLocal() as s:
        for h in hits:
            if h["kind"] == "thread":
                r = s.get(db.EmailLog, h["row_id"])
                if not r or r.tenant != tenant:
                    continue
                out.append({
                    "kind": "thread", "score": h["score"], "id": r.id,
                    "subject": r.subject or "", "from": r.sender or "",
                    "when": r.seen_at, "thread_id": r.thread_id or "",
                    "excerpt": _passage(
                        f"{r.subject or ''}\n\n{r.body_excerpt or ''}".strip(),
                        h.get("chunk", 0)),
                    "category": r.category or ""})
            else:
                r = s.get(db.DocIndex, h["row_id"])
                if not r or (r.tenant or "") not in (tenant, ""):
                    continue
                out.append({
                    "kind": "document", "score": h["score"], "id": r.id,
                    "filename": r.filename, "doc_type": r.doc_type or "",
                    "anchor": r.anchor or "", "link": r.link or "",
                    "excerpt": _passage(
                        f"{r.filename or ''} {r.anchor or ''}\n\n"
                        f"{r.text_excerpt or ''}".strip(),
                        h.get("chunk", 0))})
    return out


def backfill_bodies(tenant: str, limit: int = 200) -> dict:
    """Fetch what old threads actually said, for rows logged before there was
    anywhere to put it.

    `EmailLog` has held sender and subject for months and no body, so the
    archive backfill finds 104 rows and nothing to index. This is the job that
    fills them.

    **The bucket filter runs BEFORE the Gmail call, not after.** A promo's
    bucket was decided by triage months ago, so declining it here costs one
    dictionary lookup and saves a network round trip. Filtering after fetching
    would work and would spend an API call per marketing blast to learn what
    was already on the row.
    """
    from . import gmail_client

    with db.SessionLocal() as s:
        rows = (s.query(db.EmailLog)
                .filter(db.tenant_filter(db.EmailLog, tenant))
                .order_by(db.EmailLog.seen_at.desc()).limit(limit * 3).all())
        s.expunge_all()

    todo = [r for r in rows if not (r.body_excerpt or "").strip()]
    fetched = stored = failed = 0
    declined: dict[str, int] = {}
    why = ""

    for r in todo:
        if fetched >= limit:
            break
        # Decided from what is already on the row — no network needed to know
        # a marketing blast is a marketing blast.
        ok, reason = indexable(r.category or "", r.sender or "", "x" * 999)
        if not ok:
            key = reason.split("—")[0].strip() or reason
            declined[key] = declined.get(key, 0) + 1
            continue
        try:
            body = gmail_client.fetch_body(r.account, r.gmail_message_id)
            fetched += 1
        except Exception as exc:  # noqa: BLE001 — one dead id is not a failure
            failed += 1
            why = why or f"{exc.__class__.__name__}: {str(exc)[:100]}"
            continue
        if store_email(tenant, r.gmail_message_id, body):
            stored += 1

    return {
        "tenant": tenant, "considered": len(todo), "fetched": fetched,
        "stored": stored, "declined": declined,
        "declined_total": sum(declined.values()), "failed": failed, "why": why,
        "remaining": max(0, len(todo) - fetched - sum(declined.values())),
        "next": ("run /admin/archive_index?kind=thread to embed what was just "
                 "stored — fetching and indexing are separate so a failed "
                 "fetch does not look like a failed index"),
    }


#: What is worth extracting. A scanned image with no text layer is a document
#: whose content nobody can read without OCR, and pretending otherwise stores
#: an empty row that looks indexed.
READABLE = (".pdf", ".txt", ".csv", ".md")


def fetch_attachments(tenant: str, limit: int = 50) -> dict:
    """Pull the documents that arrived ON threads, and keep what they say.

    `read_email_attachment` has been extracting PDF text on demand for months
    and RETURNING it — no store, no commit. So every question about the same
    bill of lading re-downloaded and re-parsed it, nothing was searchable, and
    an agent had to first SUSPECT an attachment mattered before it would look.
    If it did not suspect, it asked a human instead. That is the same failure
    as the missing email bodies, one layer down.

    Filed against the thread it came on, so "what was attached to the
    conversation where we agreed the credit" is a query rather than a memory.
    """
    from . import gmail_client
    import hashlib

    with db.SessionLocal() as s:
        rows = (s.query(db.EmailLog)
                .filter(db.tenant_filter(db.EmailLog, tenant),
                        db.EmailLog.body_excerpt.isnot(None))
                .order_by(db.EmailLog.seen_at.desc()).limit(limit).all())
        s.expunge_all()

    found = stored = skipped = failed = 0
    unreadable: dict[str, int] = {}
    why = ""

    for r in rows:
        try:
            svc = gmail_client.service_for(r.account)
            msg = svc.users().messages().get(
                userId="me", id=r.gmail_message_id, format="full").execute()
            atts = gmail_client._extract_attachments(msg.get("payload", {}))
        except Exception as exc:  # noqa: BLE001
            failed += 1
            why = why or f"{exc.__class__.__name__}: {str(exc)[:100]}"
            continue

        for a in atts:
            found += 1
            name = a.get("filename", "")
            if not name.lower().endswith(READABLE):
                key = name.rsplit(".", 1)[-1].lower() if "." in name else "no extension"
                unreadable[key] = unreadable.get(key, 0) + 1
                continue
            try:
                data = gmail_client.download_attachment(
                    r.account, r.gmail_message_id, a["attachment_id"])
                if name.lower().endswith(".pdf"):
                    from .data_tools import _pdf_text
                    text = _pdf_text(data)
                else:
                    text = data.decode(errors="replace")
            except Exception as exc:  # noqa: BLE001
                failed += 1
                why = why or f"{exc.__class__.__name__}: {str(exc)[:100]}"
                continue

            text = (text or "").strip()
            if len(text) < MIN_INDEXABLE_CHARS:
                # A scan with no text layer. Recorded as unreadable rather than
                # stored empty — an empty row that looks indexed is worse than
                # an absent one, because nothing will ever come back to it.
                unreadable["no text layer"] = unreadable.get("no text layer", 0) + 1
                skipped += 1
                continue

            h = hashlib.sha256(text.encode()).hexdigest()[:32]
            with db.SessionLocal() as s:
                existing = (s.query(db.DocIndex)
                            .filter(db.DocIndex.tenant == tenant,
                                    db.DocIndex.content_hash == h).first())
                if existing:
                    # Same document on a second thread: keep the link rather
                    # than a duplicate row.
                    if not existing.thread_id:
                        existing.thread_id = r.thread_id or ""
                        existing.gmail_message_id = r.gmail_message_id
                        s.commit()
                    skipped += 1
                    continue
                s.add(db.DocIndex(
                    tenant=tenant, filename=name, path="(email attachment)",
                    doc_type="", anchor=(r.subject or "")[:120], source="email",
                    content_hash=h, text_excerpt=text[:MAX_STORED],
                    thread_id=r.thread_id or "",
                    gmail_message_id=r.gmail_message_id))
                s.commit()
            stored += 1

    return {
        "tenant": tenant, "threads_read": len(rows), "attachments_found": found,
        "stored": stored, "already_on_file": skipped, "failed": failed,
        "unreadable": unreadable, "why": why,
        "next": ("run /admin/archive_index?kind=document to embed them — then "
                 "an invoice is findable by what it SAYS, not by its filename"),
    }


def for_thread(tenant: str, thread_id: str) -> list[dict]:
    """Every document that arrived on one conversation.

    The join that did not exist. `anchor` is a business key and answers a
    different question; this answers "what came with this thread".
    """
    with db.SessionLocal() as s:
        rows = (s.query(db.DocIndex)
                .filter(db.tenant_filter(db.DocIndex, tenant, include_unassigned=True),
                        db.DocIndex.thread_id == thread_id).all())
        s.expunge_all()
    return [{"id": r.id, "filename": r.filename, "doc_type": r.doc_type or "",
             "has_text": bool((r.text_excerpt or "").strip()),
             "excerpt": (r.text_excerpt or "")[:300]} for r in rows]
