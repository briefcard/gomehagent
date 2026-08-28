"""A briefing you can clear, ranked by client.

Owner, 2026-08-27: *"ever growing daily digest emails that I have no way of
clearing or updating so it's practically useless to me. I need to fix it to
be the most relevant things first by client and then the older, house keeping
or upcoming to be placed after. I also need to be able to let the system know
when things it flagged are handled / irrelevant / updated."*

The old digest listed everything open, grouped by TYPE, with no control of any
kind on any line. Two of its sections had no bound at all — every pending
approval and every past-due deadline, for ever — so the only direction it
could move was longer. This file pins the three properties that fix that:

  · CLIENT FIRST, worst first, housekeeping and upcoming below.
  · CLEARABLE from the email itself, by signed link, with no session.
  · An ack covers the item AS IT WAS — if it changes it is a new fact and it
    comes back (the owner's call; permanently silencing a live problem is how
    a real one gets missed).

    python3 scripts/test_digest.py
"""
from __future__ import annotations

import datetime as dt
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'dg.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["PUBLIC_BASE_URL"] = "https://ops.example"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import (approvals, db, digest, emailfmt, gmail_client,  # noqa: E402
                 tenants, web)

_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _deadline(tenant, desc, due, amount="$100", created=None):
    with db.SessionLocal() as s:
        row = db.Deadline(tenant=tenant, account=tenant, description=desc,
                          amount=amount, due_date=due, status="open")
        if created:
            row.created_at = created
        s.add(row)
        s.commit()
        return row.id


def _mail(tenant, sender, subject, action, seen=None):
    with db.SessionLocal() as s:
        row = db.EmailLog(tenant=tenant, account=tenant, sender=sender,
                          subject=subject, action=action,
                          gmail_message_id=f"m-{sender}-{subject}"[:60],
                          thread_id=f"t-{subject}")
        if seen:
            row.seen_at = seen
        s.add(row)
        s.commit()
        return row.id


def main() -> int:
    db.init_db()
    tenants.seed()
    yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    next_week = (dt.date.today() + dt.timedelta(days=5)).isoformat()

    # baci: an overdue bill (the worst thing in the building)
    d_over = _deadline("baci", "Freight invoice 88", yesterday, "$4,120")
    # eien: a decision waiting, plus noise
    ap = approvals.request_approval(
        "seo_new_article", "Publish: five ways to sleep better",
        {"site": "eien"}, notify=False)
    with db.SessionLocal() as s:
        s.get(db.Approval, ap).tenant = "eien"
        s.commit()
    _mail("eien", "sam@example.com", "Where is my order", "escalated")
    _mail("eien", "noreply@stripe.com", "Receipt", "ignored")
    _mail("baci", "newsletter@x.com", "Weekly", "auto_replied")
    d_soon = _deadline("coverings", "Insurance renewal", next_week, "$800")
    # `agency` sorts FIRST alphabetically and has only low-priority work, so
    # an alphabetical order and a ranked one disagree. Without this the
    # ordering assertion below passed either way — `sabotage.py` caught it
    # reporting the_briefing_leads_with_the_client as MISSED (2026-08-27).
    _mail("agency", "vendor@example.com", "Renewal quote", "drafted")

    # ---- 1. ranked, by client -------------------------------------------
    print("— the shape of a briefing —")
    b = digest.brief()
    keys = [c["key"] for c in b["clients"]]
    ck("the account with overdue money leads", keys and keys[0] == "baci",
       str(keys))
    ck("  ahead of one that merely sorts earlier",
       "agency" in keys and keys.index("baci") < keys.index("agency"),
       f"{keys} — ranked, not alphabetical")
    ck("every client with live work has a block of its own",
       set(keys) >= {"baci", "eien"}, str(keys))
    baci = [c for c in b["clients"] if c["key"] == "baci"][0]
    ck("and each block leads with ITS worst thing",
       baci["items"][0]["kind"] == "deadline", str(baci["items"][0]))
    ck("upcoming money is NOT in the client blocks",
       all(i["ref"] != d_soon for c in b["clients"] for i in c["items"]),
       "a renewal five days out is not today's problem")
    ck("  it is in upcoming", any(i["ref"] == d_soon for i in b["upcoming"]))
    ck("housekeeping is below, not interleaved",
       {i["detail"] for i in b["housekeeping"]}
       >= {"filtered, no action", "replied automatically"},
       str([i["detail"] for i in b["housekeeping"]]))

    # ---- 2. it is clearable, from the email ------------------------------
    print("\n— every line can be closed from the email —")
    text = digest.build_digest()
    ck("the text briefing carries a link on every line",
       "https://ops.example/digest/" in text)
    # ONE link per item in text, not three: three signed URLs per line is
    # ~600 characters of noise around a 40-character fact, and the first
    # render of this was genuinely unreadable.
    worst = max((ln for ln in text.splitlines() if "digest/" in ln), key=len)
    ck("  and only one, so the text stays readable",
       worst.count("https://") == 1, worst[:90])
    links = digest.ack_links(baci["items"][0])
    ck("three verbs, one link each",
       set(links) == {"handled", "irrelevant", "updated"}, str(list(links)))
    html_body = emailfmt.digest_email(b, "AM", digest.ack_links)
    for v in ("handled", "irrelevant", "updated"):
        ck(f"  the HTML briefing offers '{v}'", f">{v}</a>" in html_body)
    ck("  the tail names which client each row belongs to",
       "[coverings]" in html_body,
       "upcoming and housekeeping span every account, so a bare line there "
       "cannot be placed")
    ck("  but a client block does not repeat it on every line",
       html_body.count("[baci]") <= html_body.count("Baci Milano USA"),
       "the heading already said it (rule 8: every fact stated once)")

    from fastapi.testclient import TestClient
    c = TestClient(web.app, base_url="https://testserver")
    r = c.get("/digest/" + links["handled"].rsplit("/", 1)[-1])
    ck("the link works with no session at all", r.status_code == 200,
       "the owner is on a phone; a control needing a login never gets used")
    ck("  and says what it did", "handled" in r.text.lower(), r.text[:120])

    b2 = digest.brief()
    ck("the cleared item is gone from the next briefing",
       not any(i["ref"] == d_over for cl in b2["clients"] for i in cl["items"]),
       "this is the whole complaint: it could never shrink")
    with db.SessionLocal() as s:
        ck("  a handled deadline is marked done in its OWN table too",
           s.get(db.Deadline, d_over).status == "done",
           "two records of one fact that can disagree is worse than one")

    # ---- 3. an ack covers the item AS IT WAS -----------------------------
    print("\n— it comes back if it changes —")
    ap2 = approvals.request_approval("seo_update", "Retitle the Aqua page",
                                     {"site": "baci"}, notify=False)
    with db.SessionLocal() as s:
        s.get(db.Approval, ap2).tenant = "baci"
        s.commit()
    item = [i for cl in digest.brief()["clients"] for i in cl["items"]
            if i["ref"] == ap2][0]
    c.get("/digest/" + digest.ack_links(item)["handled"].rsplit("/", 1)[-1])
    after = digest.brief()
    ck("handled hides it", not any(
        i["ref"] == ap2 for cl in after["clients"] for i in cl["items"]))
    ck("  and the briefing says how many it is hiding", after["cleared"] >= 1,
       "a count, so a quiet briefing cannot be confused with a broken one")
    with db.SessionLocal() as s:
        s.get(db.Approval, ap2).summary = "Retitle the Aqua page — NOW BLOCKED"
        s.commit()
    ck("but a changed version is a NEW fact and comes back", any(
        i["ref"] == ap2 for cl in digest.brief()["clients"] for i in cl["items"]),
       "permanently silencing a live problem is how a real one gets missed")

    print("\n— irrelevant means the flag was wrong, and stays wrong —")
    item2 = [i for cl in digest.brief()["clients"] for i in cl["items"]
             if i["ref"] == ap2][0]
    c.get("/digest/" + digest.ack_links(item2)["irrelevant"].rsplit("/", 1)[-1])
    with db.SessionLocal() as s:
        s.get(db.Approval, ap2).summary = "Changed yet again"
        s.commit()
    ck("it does not come back even when it changes", not any(
        i["ref"] == ap2 for cl in digest.brief()["clients"] for i in cl["items"]),
       "the owner said the flag itself was wrong, not the state of the world")

    # ---- 4. updated re-reads the source ----------------------------------
    print("\n— updated re-reads the context —")
    m_id = _mail("baci", "buyer@example.com", "Quote please", "drafted")
    read: list[tuple] = []
    gmail_client.get_thread_context = lambda a, t, limit=5: (
        read.append((a, t)), "The customer says the date moved to June.")[1]
    m_item = [i for cl in digest.brief()["clients"] for i in cl["items"]
              if i["ref"] == m_id][0]
    r2 = c.get("/digest/" + digest.ack_links(m_item)["updated"].rsplit("/", 1)[-1])
    ck("it goes and reads the thread", bool(read), str(read))
    with db.SessionLocal() as s:
        ck("  and stores what it now says",
           "date moved to June" in (s.get(db.EmailLog, m_id).body_excerpt or ""),
           "the owner's words: it should not reflect outdated information")
    ck("  and says so", "re-read" in r2.text.lower(), r2.text[:140])

    # ---- 5. it is bounded ------------------------------------------------
    print("\n— it cannot grow without bound —")
    old = db.utcnow() - dt.timedelta(days=30)
    for n in range(4):
        _deadline("ironside", f"Old thing {n}",
                  (dt.date.today() - dt.timedelta(days=20)).isoformat(),
                  created=old)
    with db.SessionLocal() as s:
        for row in s.query(db.Deadline).filter(
                db.Deadline.tenant == "ironside").all():
            row.created_at = old
        s.commit()
    for n in range(12):
        ap_n = approvals.request_approval("seo_update", f"Old edit {n}",
                                          {"site": "x"}, notify=False)
        with db.SessionLocal() as s:
            row = s.get(db.Approval, ap_n)
            row.tenant, row.created_at = "ironside", old
            s.commit()
    for n in range(digest.PER_CLIENT + 3):        # fresh, so they stay on top
        ap_f = approvals.request_approval("seo_update", f"Fresh edit {n}",
                                          {"site": "x"}, notify=False)
        with db.SessionLocal() as s:
            s.get(db.Approval, ap_f).tenant = "coverings"
            s.commit()
    b3 = digest.brief()
    cov = [cl for cl in b3["clients"] if cl["key"] == "coverings"][0]
    ck("a client block is capped", len(cov["items"]) == digest.PER_CLIENT,
       str(len(cov["items"])))
    ck("  and says how many it did not show", cov["more"] >= 3, str(cov["more"]))
    ck("  while still reporting the real depth", cov["total"] >= 9,
       "the count must come from the list, not from the page")
    ck("things open for a week sink to the tail, not the top",
       b3["stale_total"] >= 12, str(b3["stale_total"]))
    ck("  but OVERDUE MONEY never sinks",
       all(i["kind"] != "deadline" or "OVERDUE" not in i["detail"]
           for i in b3["stale"]),
       "a bill that falls off the list is exactly what this section would "
       "otherwise cause")

    print("\n— a drafted reply is not a decision here either —")
    ap3 = approvals.request_approval(
        "send_email", "Re: dishwasher safe?",
        {"account": "baci", "to": "x@y.example", "subject": "Re: safe?",
         "body": "yes", "thread_id": "t1", "draft_id": "d1"}, notify=False)
    with db.SessionLocal() as s:
        s.get(db.Approval, ap3).tenant = "baci"
        s.commit()
    ck("it is not listed as awaiting approval",
       ap3 not in digest.build_digest(),
       "the draft is in the mailbox; the digest was the last surface still "
       "asking for a decision nobody can act on there")

    print("\n— a mis-tap is recoverable —")
    d_undo = _deadline("baci", "Card renewal", yesterday, "$60")
    it = [i for cl in digest.brief()["clients"] for i in cl["items"]
          if i["ref"] == d_undo][0]
    r3 = c.get("/digest/" + digest.ack_links(it)["irrelevant"].rsplit("/", 1)[-1])
    ck("the page you land on offers Undo", ">Undo</a>" in r3.text,
       "a wrong tap on a phone was otherwise permanent for 'irrelevant'")
    c.get("/digest/" + digest.undo_link(it["kind"], it["ref"],
                                        it["fingerprint"]).rsplit("/", 1)[-1])
    ck("  and it comes back", any(
        i["ref"] == d_undo for cl in digest.brief()["clients"]
        for i in cl["items"]))
    with db.SessionLocal() as s:
        ck("  with its own status restored, not guessed",
           s.get(db.Deadline, d_undo).status == "open",
           "guessing 'open' would reopen something already closed")

    print("\n— a bad or stale link fails safely —")
    ck("a forged token is refused",
       "not valid" in digest.apply_ack("nonsense.token.here"))
    ck("  and an approval token cannot be replayed here",
       "not valid" in digest.apply_ack(
           approvals._signer.dumps([ap3, "approved"])),
       "different salts, so one route's link cannot drive the other")

    print()
    if _fail:
        print(f"{len(_fail)} FAILED:")
        for f in _fail:
            print(f"  - {f}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
