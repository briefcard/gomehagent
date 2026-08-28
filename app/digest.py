"""Morning and evening briefings — ranked by client, and clearable.

The digest used to be a list of everything open, grouped by TYPE, with no way
to say "done". So it only ever grew, and a briefing that cannot shrink stops
being read (owner, 2026-08-27: *"ever growing … practically useless to me"*).

Three things make it a briefing again:

  · **It is ranked, and grouped by CLIENT.** The owner works one account at a
    time, so a list that interleaves five of them by category is a list you
    have to re-sort in your head. Each client leads with its most urgent
    thing; the client with the worst thing leads the email.

  · **It is bounded.** Housekeeping and upcoming go BELOW the accounts, as
    counts and short lists rather than everything. Anything still open after
    a week sinks to a tail — except money already overdue, which never sinks,
    because "it fell off the list" is exactly how a bill gets missed.

  · **Every line can be closed from the email**: handled · irrelevant ·
    updated. Signed one-click links, the same mechanism approval mail already
    uses, because the owner is reading this on a phone with no session.

An ack is against the item AS IT WAS — see `db.DigestAck`. `updated` means
"the context is stale, go read it again" (owner's words: *"the thread context
should be updated … it should not reflect outdated information"*), so it
re-reads the source and lets the refreshed version come back if it now says
something different.
"""
from __future__ import annotations

import datetime as dt
import hashlib

from itsdangerous import URLSafeTimedSerializer

from . import config, db, gmail_client, whatsapp

#: Its own salt, so a digest token can never be replayed against /decide and
#: vice versa — the two routes take the same shape of secret and do very
#: different things.
_signer = URLSafeTimedSerializer(config.APPROVAL_SECRET, salt="digest-ack")

#: How long an ack link stays good. Longer than a digest cycle by a wide
#: margin, so acting on Friday's email on Monday still works.
ACK_MAX_AGE = 30 * 24 * 3600

#: An item still open after this long stops leading and sinks to the tail.
#: It is not hidden — it is demoted, with its own controls, because the whole
#: complaint was about things that could never be cleared.
STALE_DAYS = 7

#: What each block shows before it says "+N more". A briefing is a briefing.
PER_CLIENT = 6
TAIL_CAP = 20

STATES = ("handled", "irrelevant", "updated")
#: Not a verb the briefing offers — it is offered on the page you land on
#: AFTER acting, so a mis-tap on a phone is recoverable. Without it the only
#: way back was to wait for the item to change, which for "irrelevant" is
#: never.
UNDO = "undo"


def _fp(*parts) -> str:
    """A hash of what the line actually SAYS.

    The ack is against the item as it was: if this changes, the owner has not
    seen this version, so it comes back. That is the whole resurfacing rule in
    one function.
    """
    raw = "|".join(str(x or "") for x in parts)
    return hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()[:16]


def _age_days(when) -> int:
    if not when:
        return 0
    return max(0, (db.utcnow() - db.as_utc(when)).days)


# ---------------------------------------------------------------------------
# The items
# ---------------------------------------------------------------------------
# One shape for everything the briefing can carry, so ranking, grouping,
# suppression and the ack links are written once rather than per section.
#
#   kind        approval | deadline | defect | mail
#   ref         the row id, which is what an ack points at
#   tenant      whose account this is — the grouping the owner asked for
#   rank        0 is the most urgent; ties break on age, oldest first
#   bucket      now | upcoming | housekeeping
#   fingerprint what this line says, hashed
def _item(kind, ref, tenant, title, detail, rank, bucket, fingerprint,
          age_days=0) -> dict:
    return {"kind": kind, "ref": ref, "tenant": tenant or "",
            "title": title, "detail": detail, "rank": rank, "bucket": bucket,
            "fingerprint": fingerprint, "age_days": age_days}


def collect(hours_back: int = 12) -> list[dict]:
    """Everything the briefing could say, before suppression or ranking."""
    from . import approvals
    since = db.utcnow() - dt.timedelta(hours=hours_back)
    today = dt.date.today().isoformat()
    week_ahead = (dt.date.today() + dt.timedelta(days=7)).isoformat()
    out: list[dict] = []

    with db.SessionLocal() as s:
        # --- money: overdue first, and overdue NEVER sinks ------------------
        for d in (s.query(db.Deadline)
                  .filter(db.Deadline.status.in_(["open", "alerted"]),
                          db.Deadline.due_date <= week_ahead)
                  .order_by(db.Deadline.due_date).all()):
            overdue = (d.due_date or "") < today
            out.append(_item(
                "deadline", d.id, d.tenant or d.account,
                f"{d.description} ({d.amount})",
                f"due {d.due_date}" + (" — OVERDUE" if overdue else ""),
                rank=0 if overdue else 5,
                bucket="now" if overdue else "upcoming",
                fingerprint=_fp(d.description, d.amount, d.due_date, d.status),
                age_days=_age_days(d.created_at)))

        # --- decisions actually waiting on a person -------------------------
        # Through the SAME predicate the console queue and the waiting pill
        # use: a drafted reply is answered in the mailbox, so listing it here
        # as "awaiting your approval" asks for a decision nobody can act on
        # (2026-08-27 — the digest was the surface this was still wrong on).
        for ap in (s.query(db.Approval)
                   .filter(db.Approval.status == "pending").all()):
            if not approvals.decided_in_console(ap):
                continue
            out.append(_item(
                "approval", ap.id, ap.tenant, ap.summary or ap.kind,
                f"waiting {_age_days(ap.created_at)}d · {ap.kind}",
                rank=1, bucket="now",
                fingerprint=_fp(ap.summary, ap.kind, ap.status),
                age_days=_age_days(ap.created_at)))

        # --- drafts that shipped needing a fix ------------------------------
        # They carry no pending approval by design — nothing defective is
        # launchable — so this is the only place the owner hears about them.
        for r in (s.query(db.SystemRun)
                  .filter(db.SystemRun.blocked_on.isnot(None),
                          db.SystemRun.created_at >= since)
                  .order_by(db.SystemRun.created_at.desc()).all()):
            why = [str(x) for x in (r.blocked_on or []) if x]
            if not why:
                continue
            out.append(_item(
                "defect", r.id, r.tenant, "Drafted but needs fixing",
                ", ".join(why), rank=2, bucket="now",
                fingerprint=_fp(*why),
                age_days=_age_days(r.created_at)))

        # --- the mail --------------------------------------------------------
        # Escalated and drafted are work. Auto-replied and filtered are the
        # record that the machine did its job, which is worth a count and not
        # worth a page — that is the "housekeeping" the owner asked to move.
        rank_of = {"escalated": 1, "drafted": 3,
                   "auto_replied": 8, "ignored": 9}
        for e in (s.query(db.EmailLog)
                  .filter(db.EmailLog.seen_at >= since)
                  .order_by(db.EmailLog.seen_at.desc()).all()):
            action = e.action or "other"
            out.append(_item(
                "mail", e.id, e.tenant or e.account,
                f"{e.sender}: {e.subject}",
                {"escalated": "escalated to you", "drafted": "drafted for you",
                 "auto_replied": "replied automatically",
                 "ignored": "filtered, no action"}.get(action, action),
                rank=rank_of.get(action, 7),
                bucket="now" if action in ("escalated", "drafted")
                       else "housekeeping",
                fingerprint=_fp(e.sender, e.subject, action),
                age_days=_age_days(e.seen_at)))
    return out


def _suppressed(items: list[dict]) -> tuple[list[dict], int]:
    """Drop what the owner has already dealt with. Returns (kept, dropped).

    `irrelevant` kills the item outright — the owner said the flag itself was
    wrong. `handled` and `updated` only kill THIS VERSION of it: the ack is
    matched on the fingerprint, so an item that has since changed does not
    match, and comes back as the new fact it is.
    """
    if not items:
        return [], 0
    refs = {i["ref"] for i in items}
    with db.SessionLocal() as s:
        acks = (s.query(db.DigestAck)
                .filter(db.DigestAck.ref.in_(list(refs))).all())
    dead = {(a.kind, a.ref) for a in acks if a.state == "irrelevant"}
    seen = {(a.kind, a.ref, a.fingerprint) for a in acks
            if a.state in ("handled", "updated")}
    kept = [i for i in items
            if (i["kind"], i["ref"]) not in dead
            and (i["kind"], i["ref"], i["fingerprint"]) not in seen]
    return kept, len(items) - len(kept)


def ack_links(item: dict) -> dict:
    """One signed link per verb — for the HTML briefing, where they are three
    words on the line and a decision costs one tap."""
    base = config.PUBLIC_BASE_URL.rstrip("/")
    return {st: f"{base}/digest/{_signer.dumps([item['kind'], item['ref'], item['fingerprint'], st])}"
            for st in STATES}


def item_link(item: dict) -> str:
    """ONE link for the item, which opens the three choices.

    The text briefing gets this rather than three URLs per line. A signed
    token is ~200 characters, so three of them per item buried the content
    completely — the first plain-text render of this was unreadable, which
    would have replaced "a list I cannot clear" with "a list I cannot read".
    """
    base = config.PUBLIC_BASE_URL.rstrip("/")
    return (f"{base}/digest/"
            f"{_signer.dumps([item['kind'], item['ref'], item['fingerprint']])}")


def brief(hours_back: int = 12) -> dict:
    """The briefing as data: per-client blocks, then the tail.

    Rendered twice (text and HTML) from this one structure, so the two can
    never drift into saying different things.
    """
    from . import tenants
    items, dropped = _suppressed(collect(hours_back))

    now, upcoming, house, stale = [], [], [], []
    for i in items:
        if i["bucket"] == "upcoming":
            upcoming.append(i)
        elif i["bucket"] == "housekeeping":
            house.append(i)
        elif i["rank"] > 0 and i["age_days"] >= STALE_DAYS:
            # Still open after a week. Demoted, never hidden — and money
            # already overdue (rank 0) is exempt, because a bill that falls
            # off the list is exactly the failure this section would cause.
            stale.append(i)
        else:
            now.append(i)

    names = {t.key: t.name for t in tenants.all_tenants(include_paused=True)}
    by_client: dict[str, list[dict]] = {}
    for i in now:
        by_client.setdefault(i["tenant"] or "(unassigned)", []).append(i)
    for rows in by_client.values():
        rows.sort(key=lambda i: (i["rank"], -i["age_days"]))
    # The client with the worst single thing leads, then the one with more of
    # them — so the order answers "who needs me first" rather than the
    # alphabet.
    order = sorted(by_client,
                   key=lambda k: (by_client[k][0]["rank"], -len(by_client[k])))

    for bag in (upcoming, house, stale):
        bag.sort(key=lambda i: (i["rank"], -i["age_days"]))
    return {
        "clients": [{"key": k, "name": names.get(k, k),
                     "items": by_client[k][:PER_CLIENT],
                     "more": max(0, len(by_client[k]) - PER_CLIENT),
                     "total": len(by_client[k])} for k in order],
        "upcoming": upcoming[:TAIL_CAP], "upcoming_total": len(upcoming),
        "housekeeping": house[:TAIL_CAP], "housekeeping_total": len(house),
        "stale": stale[:TAIL_CAP], "stale_total": len(stale),
        "cleared": dropped,
    }


def build_digest(hours_back: int = 12) -> str:
    """The plain-text briefing — WhatsApp, the command agent, and the
    fallback body of the email."""
    b = brief(hours_back)
    when = dt.datetime.now().strftime("%a %b %d, %I:%M%p")
    lines = [f"Assistant digest — {when}\n"]

    for c in b["clients"]:
        lines.append(f"■ {c['name'].upper()} ({c['total']})")
        for i in c["items"]:
            lines.append(f"  • {i['title']} — {i['detail']}")
            lines.append(f"    clear: {item_link(i)}")
        if c["more"]:
            lines.append(f"  … and {c['more']} more")
        lines.append("")

    def _tail(title: str, rows: list[dict], total: int) -> None:
        if not rows:
            return
        lines.append(f"{title} ({total}):")
        for i in rows:
            who = i["tenant"] or "—"
            lines.append(f"  • [{who}] {i['title']} — {i['detail']}")
            lines.append(f"    clear: {item_link(i)}")
        if total > len(rows):
            lines.append(f"  … and {total - len(rows)} more")
        lines.append("")

    _tail("📅 UPCOMING", b["upcoming"], b["upcoming_total"])
    _tail("🕰 STILL OPEN, OLDER THAN A WEEK", b["stale"], b["stale_total"])
    _tail("🧹 HOUSEKEEPING — done automatically, no action",
          b["housekeeping"], b["housekeeping_total"])

    if b["cleared"]:
        lines.append(f"({b['cleared']} item(s) you already cleared are not "
                     f"shown. They come back only if they change.)")
    if len(lines) == 1:
        lines.append("Quiet period — nothing needing attention.")
    return "\n".join(lines)


def read_token(token: str) -> dict:
    """Unpack a briefing link. Four parts act; three parts ask which verb."""
    from itsdangerous import BadSignature, SignatureExpired
    try:
        parts = _signer.loads(token, max_age=ACK_MAX_AGE)
    except SignatureExpired:
        return {"error": "That link has expired — open the console and clear "
                         "it there."}
    except (BadSignature, ValueError):
        return {"error": "That link is not valid."}
    if not isinstance(parts, list) or len(parts) not in (3, 4):
        return {"error": "That link is not valid."}
    out = {"kind": parts[0], "ref": parts[1], "fingerprint": parts[2],
           "state": parts[3] if len(parts) == 4 else ""}
    if out["state"] and out["state"] not in STATES + (UNDO,):
        return {"error": "That link is not valid."}
    return out


def choices(kind: str, ref: str, fingerprint: str) -> dict:
    """The three verbs for one item, as links — what the ask-page renders."""
    item = {"kind": kind, "ref": ref, "fingerprint": fingerprint}
    return ack_links(item)


def apply_ack(token: str) -> str:
    """Act on a signed link from the briefing. Returns the sentence to show."""
    got = read_token(token)
    if got.get("error"):
        return got["error"]
    kind, ref = got["kind"], got["ref"]
    fingerprint, state = got["fingerprint"], got["state"]
    if not state:
        return "That link is not valid."

    if state == UNDO:
        return _undo(kind, ref, fingerprint)

    note = ""
    if state == "updated":
        # "The thread context should be updated … it should not reflect
        # outdated information" (owner). So this is not a dismissal: it
        # re-reads the source, and because the ack is filed against the OLD
        # fingerprint, a version that now says something different comes back
        # on the next briefing rather than staying silenced.
        note = _refresh(kind, ref)

    with db.SessionLocal() as s:
        tenant = ""
        row = s.get({"approval": db.Approval, "deadline": db.Deadline,
                     "defect": db.SystemRun, "mail": db.EmailLog}
                    .get(kind, db.Approval), ref)
        if row is not None:
            tenant = getattr(row, "tenant", "") or ""
        # A deadline has its own lifecycle column and people read it, so
        # "handled" here has to mean the same thing there — two records of
        # one fact that can disagree is worse than one. Done BEFORE the ack
        # row is built, because the ack must carry what the status WAS:
        # setting the note afterwards left it empty, and undo could then only
        # guess "open" — which would reopen something already closed.
        if kind == "deadline" and row is not None and state in ("handled",
                                                                "irrelevant"):
            note = (note + f" was:{row.status}").strip()
            row.status = "done" if state == "handled" else "dismissed"
        s.add(db.DigestAck(tenant=tenant, kind=kind, ref=ref,
                           fingerprint=fingerprint, state=state, note=note))
        s.commit()

    said = {"handled": "Marked handled — it will not come back unless it "
                       "changes.",
            "irrelevant": "Marked irrelevant — it will not be flagged again.",
            "updated": "Context re-read. If it now says something different "
                       "you will see the new version; if not, it stays "
                       "cleared."}[state]
    return said + ((" " + note) if note and not note.startswith("was:") else "")


def undo_link(kind: str, ref: str, fingerprint: str) -> str:
    base = config.PUBLIC_BASE_URL.rstrip("/")
    return f"{base}/digest/{_signer.dumps([kind, ref, fingerprint, UNDO])}"


def _undo(kind: str, ref: str, fingerprint: str) -> str:
    """Take back the last ack on this item — including `irrelevant`, which is
    the one there is otherwise no way back from."""
    with db.SessionLocal() as s:
        ack = (s.query(db.DigestAck)
               .filter(db.DigestAck.kind == kind, db.DigestAck.ref == ref,
                       db.DigestAck.fingerprint == fingerprint)
               .order_by(db.DigestAck.at.desc()).first())
        if not ack:
            return "Nothing to undo — this item is not cleared."
        was = ""
        for token in (ack.note or "").split():
            if token.startswith("was:"):
                was = token[4:]
        if kind == "deadline" and was:
            row = s.get(db.Deadline, ref)
            if row is not None:
                row.status = was
        s.delete(ack)
        s.commit()
    return "Put back — it will be in the next briefing."


def _refresh(kind: str, ref: str) -> str:
    """Re-read an item from wherever it actually lives. Best effort.

    Only mail has a live source worth re-reading on demand; everything else
    is recomputed from the database on the next build anyway, which is what
    the fingerprint comparison already picks up.
    """
    if kind != "mail":
        return "It is recomputed from its source on the next briefing."
    try:
        with db.SessionLocal() as s:
            row = s.get(db.EmailLog, ref)
            if not row or not row.thread_id:
                return ""
            account, thread_id = row.account, row.thread_id
        text = gmail_client.get_thread_context(account, thread_id, limit=3)
        if not text:
            return ""
        with db.SessionLocal() as s:
            row = s.get(db.EmailLog, ref)
            if row:
                row.body_excerpt = text[:4000]
                s.commit()
        return "The thread was re-read."
    except Exception:                                            # noqa: BLE001
        # A briefing link must never show a stack trace: the ack itself is
        # still filed by the caller, which is the part the owner asked for.
        return "The thread could not be re-read just now."


def send_digest() -> None:
    from . import emailfmt

    b = brief()
    body = build_digest()
    now = dt.datetime.now()
    when = now.strftime("%p")
    subject = (f"{'Morning' if when == 'AM' else 'Evening'} briefing — "
               f"{now.strftime('%a %b %d')}")
    gmail_client.send_email(
        config.NOTIFY_FROM_ALIAS, config.APPROVER_EMAIL, subject, body,
        html=emailfmt.digest_email(b, when, ack_links),
    )
    whatsapp.send_text(body)  # no-op until WhatsApp is enabled
