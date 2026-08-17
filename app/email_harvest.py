"""Mine the knowledge base out of what this account has already said by email.

Why email is a better source than the website, and a worse one
--------------------------------------------------------------
Worse, because the signal-to-noise is terrible: an inbox is mostly newsletters,
platform notifications, receipts and cold outreach, and none of that is a claim
about anything.

Better, because two things are true of email that are not true of a website:

  1. **The noise is already sorted.** `triage` has been classifying every
     message into `config.BUCKETS` and labelling it in Gmail, and `EmailLog`
     records the bucket. So this does not need to invent noise filtering — it
     reuses a judgement already made, one message at a time, by the classifier
     that has been running for months. `promo`, `notifications`, `receipts`,
     `subscriptions` and `sales_orders` are excluded by name.

  2. **Sent mail is the brand speaking.** This reads what the account WROTE,
     not what it received. That matters more than it sounds:

       - A sentence someone at the company sent to a real customer is a claim
         they were already comfortable making. It has passed the only review
         that was ever applied to it, which is a person deciding to press send.
       - Paired with the message it replies to, it is an OBJECTION and its
         approved answer — the exact shape of `KbObjection`.

That second point is the reason this module exists. Objections are zero on
every account, and this codebase has repeatedly called them human-authored and
underivable from a crawl. That is true of a website. It is not true of a
mailbox, where the brand has been answering the same questions for years.

What it does not do
-------------------
Nothing here asserts. Claims and objections land as proposals with
`origin="email"` and a message id, invisible to selection until approved —
the same door the crawler and the client intake link use. The extractor selects
verbatim spans and `extract._verify` discards anything not present in the
source, so a reviewer can always check a proposal against the message it came
from.
"""
from __future__ import annotations

import re

from . import config, db, extract, kb, provenance as prov, tenants

# Buckets worth reading. Everything absent from this list is noise BY THE
# CLASSIFIER'S OWN JUDGEMENT — which is the point: the filtering was done at
# triage time, months ago, one message at a time, and does not need redoing.
MINEABLE = {
    "sales_leads": "claims made to a prospect",
    "client_comms": "what was promised and delivered to a client",
    "order_issue": "how a real complaint was answered",
    "order_routine": "the answer to a question customers keep asking",
    "order_basic": "the answer to a routine request",
    "logistics": "quotes, terms and shipping facts",
}

# Never read. Listed explicitly rather than by omission so that a bucket added
# later fails safe — an unknown bucket is not mined.
EXCLUDED = ("promo", "notifications", "receipts", "subscriptions",
            "sales_orders", "urgent_money")

# Quoted history, signatures and disclaimers. Everything below one of these is
# somebody else's words or boilerplate, and mining it would attribute a
# customer's sentence to the brand.
_CUT = re.compile(
    r"^\s*(?:>|On .{0,80}wrote:|-----Original Message-----|From:\s|"
    r"Sent from my |--\s*$|Best regards|Kind regards|Thanks,|Cheers,|"
    r"This email and any attachments|CONFIDENTIAL)", re.I | re.M)


def _own_words(body: str) -> str:
    """Only what this sender actually typed, with the quoted thread removed."""
    m = _CUT.search(body or "")
    text = (body or "")[:m.start()] if m else (body or "")
    return "\n".join(ln.strip() for ln in text.splitlines() if ln.strip())


def _is_question(text: str) -> bool:
    t = (text or "").strip()
    return "?" in t and 12 < len(t) < 600


# ---------------------------------------------------------------------------
# Where the walk has got to.
#
# `Setting` rather than a table: this is a marker, which is what that store is
# for, and it needs no migration. Two hands, because a mailbox is read in two
# directions and they must not overwrite each other — `newest` is how far
# FORWARD we have caught up (so a routine run only sees mail that has arrived
# since), and `oldest` is how far BACK the backfill has walked.
#
# Without this, `fetch_sent_threads` asked for `newer_than:365d` capped at N
# and Gmail answers newest-first, so every run for ever read the same newest N
# threads. Ten thousand exchanges, mined forty at a time, always the same forty.
# ---------------------------------------------------------------------------

def cursor(tenant: str) -> dict:
    """How far this account's sent mail has been read, in both directions."""
    import json as _json
    with db.SessionLocal() as s:
        row = s.get(db.Setting, f"mail_cursor:{tenant}")
        try:
            got = _json.loads(row.value) if row and row.value else {}
        except Exception:  # noqa: BLE001 — a corrupt marker restarts the walk
            got = {}
    return {"newest": int(got.get("newest") or 0),
            "oldest": int(got.get("oldest") or 0),
            "backfill_done": bool(got.get("backfill_done")),
            "threads_read": int(got.get("threads_read") or 0),
            "last_run": got.get("last_run") or ""}


def save_cursor(tenant: str, **fields) -> dict:
    import json as _json
    got = cursor(tenant) | {k: v for k, v in fields.items() if v is not None}
    got["last_run"] = db.utcnow().isoformat()
    with db.SessionLocal() as s:
        row = s.get(db.Setting, f"mail_cursor:{tenant}")
        if not row:
            row = db.Setting(key=f"mail_cursor:{tenant}")
            s.add(row)
        row.value = _json.dumps(got)
        s.commit()
    return got


def reset_cursor(tenant: str) -> str:
    with db.SessionLocal() as s:
        row = s.get(db.Setting, f"mail_cursor:{tenant}")
        if row:
            s.delete(row)
            s.commit()
    return f"{tenant}: sent-mail cursor cleared — the next run starts over."


def _own_domains(tenant: str) -> tuple[str, ...]:
    """Addresses worth excluding in the Gmail query rather than after fetching.

    A thread filtered in the query costs nothing. The same thread filtered
    after the fact costs a full message fetch and often a classification call,
    which is most of what a run spends.
    """
    t = tenants.get(tenant)
    out = set()
    if t and t.domain:
        out.add(t.domain.replace("https://", "").replace("http://", "").strip("/"))
    acct = config.GMAIL_ACCOUNTS.get((t.gmail_alias if t else "") or "") or {}
    if acct.get("email") and "@" in acct["email"]:
        out.add(acct["email"].split("@", 1)[1])
    return tuple(sorted(d for d in out if d))


def bucket_for(alias: str, thread_id: str, inbound: dict | None) -> str:
    """What triage already decided about this thread, or a fresh cheap call.

    Reading the recorded bucket first is the whole efficiency argument: the
    classification has been paid for once already.
    """
    with db.SessionLocal() as s:
        row = (s.query(db.EmailLog)
               .filter(db.EmailLog.thread_id == thread_id)
               .filter(db.EmailLog.category != None)  # noqa: E711
               .first())
        if row and row.category:
            return row.category
    if not inbound:
        return ""
    try:
        from . import triage
        bucket = triage.classify_only(
            {"subject": inbound.get("subject", ""),
             "from": inbound.get("from", ""),
             "body": (inbound.get("body") or "")[:2000]}, alias)
    except Exception:  # noqa: BLE001 — an unclassifiable thread is skipped
        return ""
    # Write it back. This result used to be thrown away, so the next pass over
    # the same history paid for the same classification again — on a backfill
    # walking years of mail that is the single largest recurring cost, and it
    # was buying nothing. Recorded here, triage history becomes a shared asset
    # rather than the harvest's private guess.
    if bucket and inbound.get("id"):
        try:
            with db.SessionLocal() as s:
                row = (s.query(db.EmailLog)
                       .filter(db.EmailLog.gmail_message_id == inbound["id"])
                       .first())
                if row:
                    if not row.category:
                        row.category = bucket
                else:
                    s.add(db.EmailLog(
                        account=alias, gmail_message_id=inbound["id"],
                        thread_id=thread_id, sender=inbound.get("from", ""),
                        subject=(inbound.get("subject") or "")[:500],
                        category=bucket, action="classified_by_harvest",
                        tenant=tenants.for_alias(alias) or ""))
                s.commit()
        except Exception:  # noqa: BLE001 — caching is an optimisation, not a step
            pass
    return bucket


def mine(tenant: str, days: int = 365, limit: int = 80,
         apply: bool = False, direction: str = "forward",
         want: int = 0) -> dict:
    """Read this account's sent mail and propose what it finds.

    Writes nothing unless `apply`, and even then only proposals.

    `direction` decides which end of the mailbox is read. "forward" takes only
    what has arrived since the last run and is what a routine fill should do;
    "backward" walks further into history and is what the nightly backfill
    does. They move different hands of the cursor, so a backfill running
    overnight cannot rewind a top-up that ran at noon.

    `want` budgets by USEFUL threads rather than threads fetched. "Read 40" is
    the wrong unit when thirty of them are receipts.
    """
    t = tenants.get(tenant)
    if not t:
        return {"error": f"unknown tenant {tenant!r}"}
    alias = t.gmail_alias
    if not alias or alias not in config.GMAIL_ACCOUNTS:
        return {"error": f"{tenant} has no connected mailbox"}

    from . import gmail_client

    banned = [b.lower() for b in kb.banned_claims(tenant) if b]
    known = {prov.fingerprint(c.claim)
             for c in kb.claims(tenant) + kb.pending_claims(tenant)}
    known_obj = {prov.fingerprint(o.objection, o.entity_key or "")
                 for o in kb.objections(tenant, include_proposed=True)}

    cur = cursor(tenant)
    after = before = 0
    if direction == "backward":
        # Walk into history. With no cursor yet, start from now and go back.
        before = cur["oldest"] or int(db.utcnow().timestamp())
        if cur["backfill_done"]:
            return {"tenant": tenant, "direction": direction,
                    "note": "backfill already reached the start of this "
                            "mailbox — nothing older to read.",
                    "cursor": cur, "claims_count": 0, "objections_count": 0}
    else:
        after = cur["newest"]     # 0 on a first run, which means "everything"

    try:
        threads = gmail_client.fetch_sent_threads(
            alias, days=days, max_threads=limit, after=after, before=before,
            exclude=_own_domains(tenant))
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{exc.__class__.__name__}: {str(exc)[:180]}"}

    claims, objections, rejected = [], [], []
    # What the writes did, which is not the same number as what was mined.
    write_refused: list[dict] = []
    write_filed = write_corroborated = 0
    api_errors: list[str] = []
    model_ran = False
    not_verbatim: list[str] = []
    skipped: dict[str, int] = {}
    read = 0

    seen_epochs = [th.get("epoch", 0) for th in threads if th.get("epoch")]
    for th in threads:
        if want and read >= want:
            break                 # budget is mineable threads, not threads seen
        reply, inbound = th["reply"], th.get("inbound")
        bucket = bucket_for(alias, th["thread_id"], inbound)
        if bucket not in MINEABLE:
            why = f"{bucket or 'unclassified'} — not a bucket worth mining"
            skipped[why] = skipped.get(why, 0) + 1
            continue

        ours = _own_words(reply.get("body", ""))
        if len(ours) < 60:
            skipped["reply too short to hold a claim"] = \
                skipped.get("reply too short to hold a claim", 0) + 1
            continue
        read += 1
        ref = f"email {reply['id']} · {reply.get('date', '')}".strip()

        # --- claims: the same verbatim-span extractor the crawler uses -----
        blocks = [b for b in ours.split("\n") if len(b) > 25]
        res = extract.extract(tenant, ref, blocks)
        # The website path learned this the hard way: a run that reported
        # "model" while every call 400'd looked like a mailbox with nothing in
        # it. `used` and `error` were both returned here and both ignored, so
        # an out-of-credit account read ten threads, failed twenty calls, and
        # reported a clean zero.
        if res.get("used") == "error":
            api_errors.append(res.get("error", "")[:200])
        elif res.get("used") == "model":
            model_ran = True
        for c in res.get("claims", []):
            body = c["text"].strip()
            fp = prov.fingerprint(body)
            if fp in known:
                continue
            hit = next((b for b in banned if b in body.lower()), "")
            if hit:
                # Said in an email does not make it sayable. If anything this
                # matters MORE here — a banned phrase in sent mail means
                # somebody already told a customer it, and that is worth seeing.
                rejected.append({"text": body[:160], "banned_phrase": hit,
                                 "ref": ref})
                continue
            known.add(fp)
            guess = kb.suggest_tags(tenant, body)
            claims.append({"text": body, "tags": guess["tags"],
                           "proof_type": c["proof_type"],
                           "evidence": c.get("evidence", ""),
                           "source": f"said in {ref}", "bucket": bucket})
            if apply:
                # Read the return. Discarding it here was DEFECTS §1 silent
                # loss on the only derivable source of objections this platform
                # has — a backfill could report hundreds of claims mined and
                # have written none of them.
                said = kb.add_claim(tenant, body, c.get("evidence", ""),
                                    guess["tags"], proof_type=c["proof_type"],
                                    source=f"said in {ref}", status="pending",
                                    origin="email")
                if said.startswith("Unknown tags"):
                    write_refused.append({"text": body[:160], "why": said})
                elif said.startswith("Already on file"):
                    write_corroborated += 1
                else:
                    write_filed += 1

        # --- objections: their question, our answer ------------------------
        # The pair is the unit. An answer without the question it answers is
        # just a sentence, and the question is what selection matches on.
        if inbound and bucket in ("order_issue", "order_routine", "order_basic",
                                  "sales_leads"):
            asked = _own_words(inbound.get("body", ""))
            pair = extract.extract_qa(tenant, asked, ours, ref=ref)
            if pair.get("error"):
                api_errors.append(str(pair["error"])[:200])
            elif pair.get("objection"):
                model_ran = True
            if pair.get("rejected"):
                not_verbatim.append(pair["rejected"])
            elif pair.get("objection"):
                question, answer = pair["objection"], pair["answer"]
                # Only reusable answers. "Your order ships Tuesday" is true and
                # useless as an objection — it answers one order, not a question
                # the next customer will ask.
                if not pair.get("general"):
                    skipped["answer was specific to one customer"] = \
                        skipped.get("answer was specific to one customer", 0) + 1
                elif not any(b in answer.lower() for b in banned):
                    fp = prov.fingerprint(question, "")
                    if fp not in known_obj:
                        known_obj.add(fp)
                        # Tagged from the QUESTION, not the answer: the
                        # situation is the buyer's problem, and the answer is
                        # the response to it.
                        otags = kb.suggest_tags(tenant, question)["tags"]
                        objections.append({
                            "objection": question[:300], "response": answer[:900],
                            "situations": otags,
                            "source": f"answered in {ref}", "bucket": bucket})
                        if apply:
                            kb.add_objection(
                                tenant, question[:300], answer[:900],
                                origin="email", source=f"answered in {ref}",
                                situations=otags)
            elif not extract.available():
                # No key: the crude path, kept so the feature degrades rather
                # than disappears — and labelled, because its output is worse.
                question = next((ln for ln in asked.splitlines()
                                 if _is_question(ln)), "")
                if question and not any(b in ours.lower() for b in banned):
                    fp = prov.fingerprint(question, "")
                    if fp not in known_obj:
                        known_obj.add(fp)
                        objections.append({
                            "objection": question[:300], "response": ours[:900],
                            "source": f"answered in {ref} (unrefined — no "
                                      f"extractor available)", "bucket": bucket})
                        if apply:
                            kb.add_objection(tenant, question[:300], ours[:900],
                                             origin="email",
                                             source=f"answered in {ref}")

    # Move the hand this direction owns, and only that one. A backfill running
    # overnight must not rewind a top-up that ran at noon, and vice versa.
    moved = cur
    if apply and seen_epochs:
        if direction == "backward":
            moved = save_cursor(
                tenant, oldest=min(seen_epochs),
                threads_read=cur["threads_read"] + len(threads),
                # Fewer threads than the window asked for means Gmail has no
                # more that old — the end of the mailbox, not the end of the
                # budget.
                backfill_done=len(threads) < limit)
        else:
            moved = save_cursor(
                tenant, newest=max(seen_epochs),
                threads_read=cur["threads_read"] + len(threads))
    elif apply and not threads and direction == "backward":
        moved = save_cursor(tenant, backfill_done=True)

    return {
        "tenant": tenant, "mailbox": alias, "applied": apply,
        "threads_seen": len(threads),
        "threads_mined": read,
        "direction": direction,
        "window": {"after": after, "before": before},
        "cursor": moved,
        # What actually ran, not what was configured. Reporting
        # `available()` here said "model" on a run where every thread was
        # skipped before the model was reached — the same misreading that made
        # the website path's "deterministic filter" impossible to diagnose.
        # What actually happened, in three distinguishable states. Reporting
        # "model" because threads were READ said the model had worked on a run
        # where every call to it failed.
        # Four states, because a partial failure is its own thing: one path
        # succeeding while another 400s must not report as a clean "model", or
        # the failures are invisible again in a different way.
        "extractor": (
            (f"model, {len(api_errors)} calls FAILED — see extractor_note"
             if api_errors else "model") if model_ran else
            ("model FAILED — see extractor_note" if api_errors else
             ("model (nothing reached it)" if extract.available()
              else "unavailable — ANTHROPIC_API_KEY is not set"))),
        "extractor_note": (api_errors[0] if api_errors else ""),
        "extractor_failures": len(api_errors),
        "claims": claims, "claims_count": len(claims),
        "objections": objections, "objections_count": len(objections),
        "rejected_for_banned_claim": rejected,
        "rejected_not_verbatim": not_verbatim[:10],
        # Mined versus actually written. `claims_count` is the former.
        "filed_count": write_filed,
        "corroborated_count": write_corroborated,
        "write_refused": write_refused[:15],
        "write_refused_count": len(write_refused),
        "skipped_by_reason": dict(sorted(skipped.items(), key=lambda kv: -kv[1])),
        "buckets_mined": sorted(MINEABLE),
        "note": ("Reads SENT mail only — what this account said, not what it "
                 "received. Threads are filtered by the bucket triage already "
                 "assigned, so the noise was sorted once, months ago, rather "
                 "than re-litigated here. Everything lands as a PROPOSAL with "
                 "the message id, invisible to selection until approved. A "
                 "banned phrase found in sent mail is reported and not queued "
                 "— somebody has already said it to a customer."),
    }
