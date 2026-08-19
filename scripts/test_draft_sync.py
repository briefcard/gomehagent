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


def _queue(body: str, draft_id: str = "", tenant: str = "baci") -> str:
    return approvals.request_approval(
        "send_email", "reply", {"account": "baci", "to": "c@x.example",
                                "subject": "Re: order", "body": body,
                                "thread_id": "t1", "draft_id": draft_id},
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
    ap6 = _queue(GEN, "vanished")
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
