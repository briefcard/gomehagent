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
        return triage.classify_only(
            {"subject": inbound.get("subject", ""),
             "from": inbound.get("from", ""),
             "body": (inbound.get("body") or "")[:2000]}, alias)
    except Exception:  # noqa: BLE001 — an unclassifiable thread is skipped
        return ""


def mine(tenant: str, days: int = 365, limit: int = 80,
         apply: bool = False) -> dict:
    """Read this account's sent mail and propose what it finds.

    Writes nothing unless `apply`, and even then only proposals.
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

    try:
        threads = gmail_client.fetch_sent_threads(alias, days=days,
                                                  max_threads=limit)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{exc.__class__.__name__}: {str(exc)[:180]}"}

    claims, objections, rejected = [], [], []
    not_verbatim: list[str] = []
    skipped: dict[str, int] = {}
    read = 0

    for th in threads:
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
                kb.add_claim(tenant, body, c.get("evidence", ""), guess["tags"],
                             proof_type=c["proof_type"],
                             source=f"said in {ref}", status="pending",
                             origin="email")

        # --- objections: their question, our answer ------------------------
        # The pair is the unit. An answer without the question it answers is
        # just a sentence, and the question is what selection matches on.
        if inbound and bucket in ("order_issue", "order_routine", "order_basic",
                                  "sales_leads"):
            asked = _own_words(inbound.get("body", ""))
            pair = extract.extract_qa(tenant, asked, ours, ref=ref)
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
                        objections.append({
                            "objection": question[:300], "response": answer[:900],
                            "source": f"answered in {ref}", "bucket": bucket})
                        if apply:
                            kb.add_objection(
                                tenant, question[:300], answer[:900],
                                origin="email", source=f"answered in {ref}")
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

    return {
        "tenant": tenant, "mailbox": alias, "applied": apply,
        "threads_seen": len(threads),
        "threads_mined": read,
        "extractor": "model" if extract.available() else "unavailable",
        "claims": claims, "claims_count": len(claims),
        "objections": objections, "objections_count": len(objections),
        "rejected_for_banned_claim": rejected,
        "rejected_not_verbatim": not_verbatim[:10],
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
