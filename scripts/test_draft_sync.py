"""The queue and the mailbox stay in step, and the delta is the quality signal.

Owner: *"they should be in sync so that it's not a constant build up, whatever
gets sent in the end is approved, and we track the delta."*

Before this, a drafted reply produced TWO things that never spoke to each other:
a Gmail draft, and an approval built from a COPY of what that draft said at the
moment it was written. Approving composed a THIRD message from that copy. So:

  · editing the draft in Gmail changed nothing anybody sent;
  · approving left the draft behind to accumulate;
  · sending it yourself from Gmail left the approval pending for ever, and
    approving it later would deliver the original text a SECOND time to the
    same customer on the same thread.

    python3 scripts/test_draft_sync.py
"""
import inspect
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'ds.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import approvals, db, edits, gmail_client, tenants  # noqa: E402

_fail: list[str] = []
_sent_drafts: list[str] = []
_sent_fresh: list[dict] = []
_DRAFTS: dict[str, dict] = {}
#: recipient -> the most recent message this mailbox sent them since an
#: approval was raised. The draftless half of the same question.
_SENT_TO: dict[str, dict] = {}
#: thread_id -> the message this mailbox actually sent on it. A draft that was
#: SENT leaves one here; a draft that was DELETED does not, and the whole
#: point of the 2026-08-27 change is that those two stop being the same event.
_SENT_ON_THREAD: dict[str, dict] = {}


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _stub():
    gmail_client.read_draft = lambda a, d: dict(_DRAFTS.get(d) or {})
    gmail_client.send_draft = lambda a, d: (_sent_drafts.append(d),
                                            _DRAFTS.pop(d, None), "sent")[2]
    gmail_client.send_email = lambda a, to, su, bo, th=None, cc="", **k: (
        _sent_fresh.append({"to": to, "body": bo}), "fresh")[1]
    gmail_client.sent_in_thread = lambda a, t: dict(_SENT_ON_THREAD.get(t) or {})
    gmail_client.sent_to_since = lambda a, to, since: dict(_SENT_TO.get(to) or {})


def _queue(body: str, draft_id: str = "", tenant: str = "baci",
           thread_id: str = "t1") -> str:
    return approvals.request_approval(
        "send_email", "reply", {"account": "baci", "to": "c@x.example",
                                "subject": "Re: order", "body": body,
                                "thread_id": thread_id, "draft_id": draft_id},
        notify=False)


def main() -> int:
    db.init_db()
    tenants.seed()
    _stub()
    GEN = "Hi Marisa,\n\nYour order ships Tuesday.\n\nBest,\nBaci"

    print("— what is sent is the DRAFT, not a copy of it —")
    _DRAFTS["d1"] = {"draft_id": "d1", "body": GEN}
    ap = _queue(GEN, "d1")
    approvals.apply_decision(ap, "approved")
    ck("the draft itself is sent", _sent_drafts == ["d1"])
    ck("  and no second message is composed", not _sent_fresh,
       "composing a fresh copy is what discarded the edit and left the draft")
    ck("  so nothing is left behind to pile up", "d1" not in _DRAFTS)

    print("\n— an edit made in Gmail actually goes out, and is measured —")
    EDITED = "Hi Marisa,\n\nYour order ships Wednesday, apologies.\n\nBest,\nBaci"
    _DRAFTS["d2"] = {"draft_id": "d2", "body": EDITED}
    ap2 = _queue(GEN, "d2")           # queued with the GENERATED text
    approvals.apply_decision(ap2, "approved")
    ck("the edited draft is what sends", "d2" in _sent_drafts)
    with db.SessionLocal() as s:
        pay = (s.get(db.Approval, ap2).payload or {})
    ck("the delta is recorded", bool(pay.get("edit")))
    ck("  and it says the human changed it", pay["edit"]["as_is"] is False,
       str(pay["edit"]))
    ck("  with a sample, not the whole letter",
       0 < len(pay.get("edit_sample", "")) <= 1200,
       "a second copy of every customer reply is a data store nobody asked for")

    print("\n— sent as-is is recognised as such —")
    _DRAFTS["d3"] = {"draft_id": "d3", "body": GEN}
    ap3 = _queue(GEN, "d3")
    approvals.apply_decision(ap3, "approved")
    with db.SessionLocal() as s:
        ck("an untouched draft reports as_is",
           (s.get(db.Approval, ap3).payload or {})["edit"]["as_is"] is True)

    print("\n— the duplicate send is closed —")
    ap4 = _queue(GEN, "gone")         # draft already sent by hand
    _sent_drafts.clear(); _sent_fresh.clear()
    approvals.apply_decision(ap4, "approved")
    ck("approving a vanished draft sends NOTHING",
       not _sent_drafts and not _sent_fresh,
       "otherwise the customer gets the original text a second time on the "
       "same thread")

    print("\n— and the queue does not fill with work already done —")
    _DRAFTS["d5"] = {"draft_id": "d5", "body": GEN}
    ap5 = _queue(GEN, "d5")
    ap6 = _queue(GEN, "vanished", thread_id="t6")
    # 2026-08-27: this scenario always MEANT "already sent it from Gmail", and
    # said so in prose; the code could not tell that from a deleted draft, so
    # the fixture now states it. The deleted case gets its own section below.
    _SENT_ON_THREAD["t6"] = {"message_id": "m6", "body": GEN}
    res = approvals.reconcile_drafts()
    ck("an approval whose draft is gone is closed", res["closed"] >= 1)
    ck("  one still sitting there is left alone", res["still_waiting"] >= 1)
    with db.SessionLocal() as s:
        ck("  closed as sent_outside, not as approved",
           s.get(db.Approval, ap6).status == "sent_outside",
           "it was dealt with in Gmail; calling it approved would claim we did it")
        ck("  and the live one is still pending",
           s.get(db.Approval, ap5).status == "pending")
    ck("reconciling never sends anything",
       not _sent_drafts and not _sent_fresh,
       "the worst case of a wrong reading must be a closed approval, never a "
       "mailed customer")

    print("\n— the diff ignores what a human did not write —")
    ck("quoted history is not an edit",
       edits.delta(GEN, GEN + "\n\nOn Mon, Marisa wrote:\n> when?")["as_is"],
       "Gmail appends the original to every reply")
    ck("trailing whitespace is not an edit",
       edits.delta(GEN, GEN + "   ")["as_is"],
       "a smart quote or a stray space is not a correction, and counting it "
       "reports the generator as worse than it is")
    ck("a real rewrite is", not edits.delta(GEN, "Different entirely.")["as_is"])

    print("\n— an approval with no draft behind it still works —")
    _sent_fresh.clear()
    approvals.apply_decision(_queue(GEN, ""), "approved")
    ck("it composes a message, as before", len(_sent_fresh) == 1,
       "approvals queued before this existed, and replies composed elsewhere")

    # ---------------------------------------------------------------------
    # THE SEND IS THE APPROVAL (owner, 2026-08-27): "all emails will be
    # considered approved when they are sent, and the difference between the
    # draft and the sent email will be the learning difference for the agent
    # to learn from."
    #
    # `reconcile_drafts` already closed the row. It did NOT record the delta —
    # its own docstring promised it and `edits` was imported for it — so the
    # normal path, sending from Gmail, threw the lesson away every time.
    # ---------------------------------------------------------------------
    print("\n— sending it yourself IS approving it, and it teaches —")
    _SENT_ON_THREAD.clear()
    HAND = "Hi Marisa,\n\nYour order ships Tuesday — I've added a note.\n\nBest,\nBaci"
    ap7 = _queue(GEN, "d7", thread_id="t7")
    _SENT_ON_THREAD["t7"] = {"message_id": "m7", "body": HAND}   # sent by hand
    res = approvals.reconcile_drafts()
    ck("a draft sent from Gmail closes its approval",
       res["closed"] >= 1, str(res))
    ck("  and the delta IS recorded", res["deltas_recorded"] >= 1,
       "this is the whole point: what changed between the draft and the "
       "letter is the only honest signal of where the generator is wrong")
    with db.SessionLocal() as s:
        pay7 = (s.get(db.Approval, ap7).payload or {})
    ck("  the edit lands on the approval", bool(pay7.get("edit")), str(pay7)[:120])
    ck("  and says a human changed it", pay7["edit"]["as_is"] is False,
       str(pay7.get("edit")))
    ck("  with a sample, not the letter",
       0 < len(pay7.get("edit_sample", "")) <= 1200)

    print("\n— a DELETED draft is not a send, and must not teach —")
    ap8 = _queue(GEN, "d8", thread_id="t8")     # nothing sent on t8
    res8 = approvals.reconcile_drafts()
    with db.SessionLocal() as s:
        ap8row = s.get(db.Approval, ap8)
        ck("it is closed as discarded, not as sent",
           ap8row.status == "draft_discarded", ap8row.status)
        ck("  and NO delta is recorded against it",
           not (ap8row.payload or {}).get("edit"),
           "measuring an edit against a letter nobody wrote poisons the one "
           "quality number this system has")
    ck("  the run reports them apart", res8["discarded"] >= 1, str(res8))
    _sent_drafts.clear(); _sent_fresh.clear()
    approvals.reconcile_drafts()
    ck("reconciling still sends nothing", not _sent_drafts and not _sent_fresh,
       "the worst case of a wrong reading must be a closed approval, never a "
       "mailed customer")

    print("\n— a discarded draft frees the thread —")
    from app import replies
    own = replies.owner("baci", "t8")
    ck("nobody owns a thread that was never answered", not own, str(own))
    ck("but a thread that WAS answered is still owned",
       bool(replies.owner("baci", "t7")), str(replies.owner("baci", "t7")))

    print("\n— and the console no longer asks about a drafted reply —")
    from app import admin_ui
    _DRAFTS["d9"] = {"draft_id": "d9", "body": GEN}
    ap9 = _queue(GEN, "d9", thread_id="t9")     # a reply, waiting in Gmail
    ap10 = approvals.request_approval(          # an email with NO draft
        "send_email", "[Invoice reminder] c@x.example: Invoice",
        {"account": "baci", "to": "c@x.example", "subject": "Invoice",
         "body": "Just following up."}, notify=False)
    page = admin_ui.render_content("s3cret", tenant="baci", sub="ship")
    # Pinned on the approval's own id and its subject, not on the draft id:
    # "d9" is a substring of the hex colour #6d28d9 in the stylesheet, and an
    # assertion that can be satisfied by a token value is not an assertion.
    ck("the drafted reply is NOT in the ship queue",
       ap9 not in page and "Re: order" not in page,
       "the draft is in the mailbox; sending it there is the approval")
    ck("but an email that exists nowhere else still is",
       "Invoice reminder" in page,
       "it has no draft anywhere, so this queue is its only way out")
    ck("the queue says where drafted replies went",
       "Drafted replies are not here" in page)
    ck("and the chip names what is left", ">emails<" in page, "was 'replies'")

    # The pill and the queue must never disagree — it links straight at the
    # queue, so an over-count is a lie you catch in one click (rule 8).
    n = approvals.pending_count("baci")
    ck("the waiting pill counts what the queue shows", n == 1,
       f"pill says {n}; the queue shows the invoice reminder only")
    from fastapi.testclient import TestClient
    from app import web
    c = TestClient(web.app, base_url="https://testserver")
    fb = c.get("/admin/pending", params={"key": "s3cret"}).text
    ck("and the email fallback queue agrees",
       "Invoice reminder" in fb and "Re: order" not in fb,
       "a signed approve link for a reply already sent would mail it twice")

    # ---------------------------------------------------------------------
    # OUTBOUND MAIL WITH NO DRAFT BEHIND IT (owner, 2026-08-28: "there was no
    # feedback for communication with clients that lets a system know that
    # they have already been answered … I'm looking at a list of emails that
    # I've already handled").
    #
    # An RFQ, an invoice reminder, a shipment follow-up: the system wrote the
    # words, there is no Gmail draft, and answering the person yourself used
    # to leave the approval pending for ever.
    # ---------------------------------------------------------------------
    print("\n— mail you answered yourself stops asking to be sent —")
    _SENT_TO.clear()
    ap_r = approvals.request_approval(
        "send_email", "[RFQ] quote request to freight@x.example",
        {"account": "baci", "to": "freight@x.example",
         "subject": "Quote request", "body": GEN}, notify=False)
    res_r = approvals.reconcile_drafts()
    with db.SessionLocal() as s:
        ck("with nothing sent it is left alone",
           s.get(db.Approval, ap_r).status == "pending", str(res_r))
    _SENT_TO["freight@x.example"] = {
        "message_id": "s1",
        "body": "Hi — could you also quote express? Thanks, Gomeh"}
    _sent_drafts.clear(); _sent_fresh.clear()
    res_r2 = approvals.reconcile_drafts()
    with db.SessionLocal() as s:
        row_r = s.get(db.Approval, ap_r)
        ck("once you have written to them, it closes",
           row_r.status == "sent_outside", row_r.status)
        ck("  and the delta is recorded — how YOU answered",
           bool((row_r.payload or {}).get("edit")),
           "the point of noticing is to learn from it")
        ck("    saying it was rewritten, not sent as-is",
           (row_r.payload or {})["edit"]["as_is"] is False,
           str((row_r.payload or {}).get("edit")))
    ck("the run reports it", res_r2["deltas_recorded"] >= 1, str(res_r2))
    ck("and it still sends nothing", not _sent_drafts and not _sent_fresh)
    # NOT "the queue is empty": the invoice reminder from the section above
    # is still genuinely pending — nothing has been sent to that address —
    # and asserting zero would have been asserting that reconcile closes
    # things it should leave alone.
    fb2 = c.get("/admin/pending", params={"key": "s3cret"}).text
    ck("the answered one leaves the queue", "RFQ" not in fb2, "closed")
    ck("  and the unanswered one stays", "Invoice reminder" in fb2,
       "reconcile must close only what was actually dealt with")

    # ---------------------------------------------------------------------
    # THE DRAFT IS STILL THERE, AND YOU ANSWERED ANYWAY (owner, 2026-08-28:
    # "I have been seeing drafts to these emails inside of gmail", on a list
    # of mail already handled). Replying from a phone, or composing fresh
    # rather than sending the draft, leaves the draft sitting in the mailbox.
    # Reconcile stopped at `read_draft`, counted the row as still waiting,
    # and asked again for ever.
    # ---------------------------------------------------------------------
    print("\n— you answered another way; the draft is still sitting there —")
    _DRAFTS["d10"] = {"draft_id": "d10", "body": GEN}
    ap10 = _queue(GEN, "d10", thread_id="t10")
    with db.SessionLocal() as s:
        raised = db.as_utc(s.get(db.Approval, ap10).created_at).timestamp()
    # A message sent on that thread BEFORE the approval was raised is the
    # earlier half of the conversation, not an answer to it.
    _SENT_ON_THREAD["t10"] = {"message_id": "old", "at": raised - 600,
                              "body": "an earlier message on this thread"}
    approvals.reconcile_drafts()
    with db.SessionLocal() as s:
        ck("an OLDER message on the thread is not an answer",
           s.get(db.Approval, ap10).status == "pending",
           "or every thread with any history would close itself")
    TYPED = "Hi Marisa — answered from my phone, shipping Thursday."
    _SENT_ON_THREAD["t10"] = {"message_id": "m10", "at": raised + 60,
                              "body": TYPED}
    _sent_drafts.clear(); _sent_fresh.clear()
    res10 = approvals.reconcile_drafts()
    with db.SessionLocal() as s:
        row10 = s.get(db.Approval, ap10)
        ck("answering another way closes the approval",
           row10.status == "answered_elsewhere", row10.status)
        ck("  and it is NOT filed as 'the draft was sent'",
           row10.status != "sent_outside",
           "the draft is still in the mailbox; saying it went would be wrong")
        ck("  the delta is against what you ACTUALLY wrote",
           (row10.payload or {}).get("edit_sample", "").find("phone") >= 0
           or (row10.payload or {})["edit"]["as_is"] is False,
           str((row10.payload or {}).get("edit")))
    ck("the run names the drafts left behind",
       res10["answered_elsewhere"] >= 1
       and any("order" in x for x in res10["drafts_left_in_the_mailbox"]),
       str(res10["drafts_left_in_the_mailbox"]))
    ck("  and it deletes nothing", "d10" in _DRAFTS,
       "closing an approval is this function's job; clearing somebody's "
       "mailbox is not")
    ck("  and still sends nothing", not _sent_drafts and not _sent_fresh)

    print("\n— asked of the MAILBOX, not of the console —")
    src = inspect.getsource(approvals.reconcile_drafts)
    ck("a draftless reply is matched on its thread", "sent_in_thread" in src)
    ck("  and one that STARTS a conversation, on the recipient",
       "sent_to_since" in src, "an RFQ has no thread to look in")

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
