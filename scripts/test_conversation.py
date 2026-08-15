"""Three email threads with one company are one conversation, or the agent lies.

`ChatMessage.thread` namespaces the operator's conversations with his agents —
about twenty threads, one operator, no lifecycle. Pointed at counterparties it
breaks in three ways: nowhere to record what stage a lead is at, no way to read
context without replaying every message, and nothing that can enforce "do not
send touch four if they already replied".

This suite is that gap closed. The cases that matter most:

  * two threads with the same person fold onto one row, and the provider ids
    of both are kept — the overlapping-threads problem stated plainly
  * a returning lead is a NEW conversation, which is why reuse is a lookup on
    status rather than a unique constraint
  * an outbound touch without an idempotency key is refused, because this
    codebase has a known double-send and an optional guard is an absent one
  * two tenants may use the SAME idempotency key — proof the constraint is
    composite, not global

    python3 scripts/test_conversation.py
"""
from __future__ import annotations

import datetime as dt
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'cv.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import conversation as cv, db, tenants  # noqa: E402
from app.web import app  # noqa: E402

_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _contact(tenant: str, email: str) -> str:
    with db.SessionLocal() as s:
        row = db.Contact(tenant=tenant, email=email, name=email.split("@")[0],
                         role="client")
        s.add(row)
        s.commit()
        s.refresh(row)
        return row.id


def main() -> int:
    with TestClient(app) as cl:  # noqa: F841 — startup builds the schema
        tenants.seed()
        jane = _contact("agency", "jane@acme.com")
        other = _contact("baci", "jane@acme.com")   # same address, other client

        print("— stages are data, per system —")
        ck("a lead ladder and a desk ladder are different",
           cv.stages("lead_responder") != cv.stages("service_desk"))
        ck("an undeclared system still gets a ladder",
           cv.stages("nothing_declared") == ("open", "working", "closed"))
        ck("terminal is declared, not 'the last one'",
           set(cv.terminal("lead_responder")) == {"won", "lost"},
           str(cv.terminal("lead_responder")))

        print("\n— two threads with the same person are ONE conversation —")
        c1, made1 = cv.open_or_get("agency", jane, "lead_responder",
                                   subject="Website enquiry",
                                   situations=["pricing"],
                                   external_ref=("gmail", "thread-aaa"))
        ck("the first one is created", made1)
        ck("it starts on the first stage of its ladder", c1.stage == "new",
           c1.stage)

        c2, made2 = cv.open_or_get("agency", jane, "lead_responder",
                                   situations=["timing"],
                                   external_ref=("gmail", "thread-bbb"))
        ck("the second thread does NOT start a second conversation", not made2)
        ck("it is the same row", c1.id == c2.id)
        ck("and BOTH provider threads are kept",
           {r["ref"] for r in c2.external_refs} == {"thread-aaa", "thread-bbb"},
           str(c2.external_refs))
        ck("what the new thread told us is added, not swapped in",
           sorted(c2.situations) == ["pricing", "timing"], str(c2.situations))
        ck("and the subject somebody set is not overwritten",
           c2.subject == "Website enquiry", c2.subject)

        print("\n— one client's conversation is invisible to another —")
        ck("a real id does not resolve under the wrong account",
           cv.get("baci", c1.id) is None)
        ck("and the same person at another client is separate",
           cv.open_or_get("baci", other, "lead_responder")[0].id != c1.id)

        print("\n— a stage nobody declared is refused BY NAME —")
        msg = cv.advance("agency", c1.id, "nurturing")
        ck("it refuses", "Unknown stage" in msg, msg[:60])
        ck("and says what IS declared", "qualifying" in msg, msg[-60:])
        ck("a declared stage moves", cv.advance("agency", c1.id, "contacted")
           == "Moved to contacted.")

        print("\n— an outbound touch without a key is refused —")
        t, made, note = cv.record_touch("agency", c1.id, direction="out",
                                        summary="first outreach")
        ck("nothing is recorded", t is None and not made)
        ck("and the reason names the failure it prevents",
           "sends it twice" in note, note[:70])

        print("\n— the same key twice writes once —")
        t1, made1, _ = cv.record_touch("agency", c1.id, direction="out",
                                       summary="first outreach",
                                       idempotency_key="run-1:touch-1")
        t2, made2, note = cv.record_touch("agency", c1.id, direction="out",
                                          summary="first outreach",
                                          idempotency_key="run-1:touch-1")
        ck("the first is written", made1)
        ck("the second is not", not made2)
        ck("it returns the original rather than failing", t2.id == t1.id)
        ck("and says nothing was sent twice", "twice" in note, note)
        ck("one touch on file", len(cv.touches("agency", c1.id)) == 1)

        print("\n— but two CLIENTS may use the same key —")
        bc, _ = cv.open_or_get("baci", other, "lead_responder")
        tb, madeb, _ = cv.record_touch("baci", bc.id, direction="out",
                                       summary="unrelated",
                                       idempotency_key="run-1:touch-1")
        ck("the second client's touch is written", madeb,
           "a global unique here would make one client block the other")

        print("\n— inbound borrows the provider's own id —")
        ti, madei, _ = cv.record_touch("agency", c1.id, direction="in",
                                       summary="they replied", ref="msg-99")
        ck("it is recorded without the caller minting a key", madei)
        ck("and the key is the provider's", ti.idempotency_key == "in:msg-99",
           ti.idempotency_key)
        _, again, _ = cv.record_touch("agency", c1.id, direction="in",
                                      summary="they replied", ref="msg-99")
        ck("so redelivery of the same message is a no-op", not again)

        print("\n— a commitment is a row a validator can check —")
        bad, note = cv.commit_to("agency", c1.id, "price", "   ")
        ck("an empty promise is refused", bad is None and "needs a value" in note)
        good, note = cv.commit_to("agency", c1.id, "price", "$2,400",
                                  detail="quoted for the audit",
                                  stated_in=t1.id)
        ck("a real one is recorded", good is not None, note)
        ck("and is outstanding",
           [c.value for c in cv.open_commitments("agency", c1.id)] == ["$2,400"])
        ck("another client cannot see it",
           cv.open_commitments("baci", c1.id) == [])
        ck("settling it takes it off the list",
           cv.settle("agency", good.id, "met") == "Marked met."
           and cv.open_commitments("agency", c1.id) == [])

        print("\n— what the resolver will read —")
        st = cv.state_for("agency", contact_id=jane, system_key="lead_responder")
        ck("it exists", st["exists"])
        ck("it carries the situations the KB will answer against",
           sorted(st["situations"]) == ["pricing", "timing"], str(st["situations"]))
        ck("it says who the ball is with", st["awaiting"] == "us",
           f"last touch was inbound, so it is our move — got {st['awaiting']}")
        ck("and the ladder travels with the stage",
           st["stage"] == "contacted" and "qualifying" in st["stages"])

        print("\n— absence is reported, not implied —")
        nobody = _contact("agency", "never@spoke.com")
        st = cv.state_for("agency", contact_id=nobody)
        ck("it does not pretend to be a conversation", st["exists"] is False)
        ck("and says why, rather than returning a blank",
           "no open conversation" in st["why"], st["why"])
        ck("with the shape callers expect either way",
           st["situations"] == [] and st["open_commitments"] == []
           and st["touch_count"] == 0)

        print("\n— the work queue is what is actually due —")
        past = db.utcnow() - dt.timedelta(hours=2)
        future = db.utcnow() + dt.timedelta(days=3)
        cv.advance("agency", c1.id, "qualifying", next_action_at=past)
        later, _ = cv.open_or_get("agency", _contact("agency", "l8@acme.com"),
                                  "lead_responder")
        cv.advance("agency", later.id, "contacted", next_action_at=future)
        ids = [r.id for r in cv.due("agency")]
        ck("the overdue one is in the queue", c1.id in ids)
        ck("the future one is not", later.id not in ids, str(ids))

        print("\n— reaching a terminal stage closes it —")
        ck("moving to won closes", cv.advance("agency", c1.id, "won")
           == "Moved to won.")
        row = cv.get("agency", c1.id)
        ck("status and outcome cannot disagree",
           row.status == "closed" and row.outcome == "won",
           f"{row.status}/{row.outcome}")
        ck("and it drops out of the work queue",
           c1.id not in [r.id for r in cv.due("agency")])

        print("\n— and a returning lead is a NEW conversation —")
        c3, made3 = cv.open_or_get("agency", jane, "lead_responder")
        ck("the closed one is not reopened", made3 and c3.id != c1.id,
           "this is why reuse is a status lookup, not a unique constraint")

    print()
    if _fail:
        print(f"FAILED {len(_fail)}:")
        for f in _fail:
            print(f"  - {f}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
