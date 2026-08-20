"""One reply per conversation, whoever writes it.

Three systems sit on one inbox — `inbox_triage`, `service_desk`,
`lead_responder`. Today only the first produces anything, so nothing can
collide; that is a fact about the build, not a property of the design, and it
expires the moment a generator lands. This is the property.

The existing guards do not cover it and it is worth being precise about why.
`worker.already_seen` is keyed on a Gmail MESSAGE id — it stops one email being
triaged twice and says nothing about two systems answering one thread. And the
two paths record in different places: triage writes `EmailLog` and an
`Approval`, the substrate writes `Output`. Neither can see the other.

This codebase has already paid for that shape once, one level down: an approval
built from a COPY of a draft meant approving it later "would deliver the
original text A SECOND TIME to the same customer on the same thread".

    python3 scripts/test_replies.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'rp.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import approvals, db, kb, replies, skill, tenants  # noqa: E402

_fail: list[str] = []
THREAD = "t-100"


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


_seq = iter(range(1000))


def triaged(thread, action="drafted", tenant="baci"):
    # A unique message id per row: `gmail_message_id` is unique, which is the
    # per-message idempotency this guard sits ABOVE rather than replaces.
    with db.SessionLocal() as s:
        s.add(db.EmailLog(account="baci", tenant=tenant,
                          gmail_message_id=f"m-{next(_seq)}",
                          thread_id=thread, sender="a@b.com", subject="hi",
                          category="order_routine", action=action))
        s.commit()


def main() -> int:
    db.init_db()
    tenants.seed()
    kb.ensure_brand("baci", "Baci Milano USA")
    kb.add_banned("baci", "hand-decorated")
    # Installed, or `preflight` refuses first — which is the correct EARLIER
    # refusal, and would have hidden whether the thread guard fires at all.
    from app import systems
    systems.create("baci", "service_desk", "Service desk")

    print("— an untouched thread is free —")
    ck("nobody owns it", not replies.owner("baci", THREAD))
    ck("  so any system may answer",
       replies.may_reply("baci", THREAD, "service_desk")["ok"])

    print("\n— once one system replies, it owns the thread —")
    triaged(THREAD)
    held = replies.owner("baci", THREAD)
    ck("the owner is named", held.get("system") == "inbox_triage", str(held))
    ck("  the same system may continue",
       replies.may_reply("baci", THREAD, "inbox_triage")["ok"],
       "a follow-up on a thread it owns is a conversation, not a collision")
    other = replies.may_reply("baci", THREAD, "service_desk")
    ck("  a DIFFERENT system is refused", not other["ok"])
    # `.get`, not `[...]`: with the guard disabled there is no `why` at all,
    # and a KeyError is a crash rather than a named failure — a sabotage run
    # has to say WHICH assertion the missing guard broke.
    ck("    by name, not silently",
       "inbox_triage" in other.get("why", ""),
       "a silent skip looks identical to a broken system")
    ck("    saying why it matters",
       "two replies to one question" in other.get("why", ""))

    print("\n— it reads BOTH ledgers, not just its own —")
    t2 = "t-200"
    approvals.request_approval("send_email", "a system's draft",
                               {"tenant": "baci", "thread_id": t2},
                               notify=False)
    ck("an approval queued elsewhere also claims the thread",
       bool(replies.owner("baci", t2)),
       "triage writes EmailLog, the substrate writes Output — a check that "
       "consults one fails exactly when it matters")
    ck("  and triage would defer to it",
       not replies.may_reply("baci", t2, "inbox_triage")["ok"])

    print("\n— a decision against frees the thread —")
    t3 = "t-300"
    ap = approvals.request_approval("send_email", "rejected draft",
                                    {"tenant": "baci", "thread_id": t3},
                                    notify=False)
    with db.SessionLocal() as s:
        row = s.get(db.Approval, ap)
        row.status = "denied"
        s.commit()
    ck("a denied reply does not hold the thread",
       not replies.owner("baci", t3),
       "we decided not to send it — somebody still has to answer")

    print("\n— and one client's thread never blocks another's —")
    triaged("shared-id", tenant="ironside")
    ck("scoped by account",
       replies.may_reply("baci", "shared-id", "service_desk")["ok"],
       "gmail thread ids are not unique across mailboxes")

    print("\n— no thread at all is not a collision —")
    ck("a first contact is allowed",
       replies.may_reply("baci", "", "service_desk")["ok"],
       "refusing these would block most of what a reply skill is for")

    print("\n— the bucket decides the owner, as data —")
    ck("sales go to the lead responder",
       replies.route("sales_leads") == "lead_responder")
    ck("  order questions to the service desk",
       replies.route("order_routine") == "service_desk")
    ck("  and anything unclaimed stays with triage",
       replies.route("receipts") == "inbox_triage",
       "a system that has not claimed a kind of mail must not silently start "
       "answering it")

    print("\n— the second entry point is guarded too —")
    # `run_skill` is a kernel tool: the WhatsApp agent can reach a drafting
    # skill directly, never passing through triage.
    from app import skill_pack     # noqa: F401 — registers the skills
    sk = skill.get("inbound_reply") if hasattr(skill, "get") else None
    ck("the reply skill declares thread_id",
       "thread_id" in skill.catalogue("baci")[0].get("params", [])
       or any("thread_id" in (e.get("params") or [])
              for e in skill.catalogue("baci")),
       "skill.run refuses an undeclared parameter BEFORE any guard reads it — "
       "a guard reading a parameter nobody may pass never fires")
    r = skill.run("inbound_reply", "baci", utterance="hello",
                  thread_id=THREAD)
    ck("  and a skill is refused on an owned thread",
       r["status"] == "refused", r["status"])
    ck("    naming the system that has it",
       any("inbox_triage" in b for b in r.get("blocked_on", [])),
       str(r.get("blocked_on")))
    del sk

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
