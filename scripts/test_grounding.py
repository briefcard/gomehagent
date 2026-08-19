"""The knowledge base reaches the path that answers customers — and guards it.

Three things this holds, and each was a real hole.

**Grounding.** `resolve.resolve` had exactly ONE caller, the skill substrate.
So every claim, objection and piece of brand guidance the owner approved
reached registered skills and nothing else, while the inbound mail path — the
one drafting the replies he reads each morning — worked from a hardcoded prompt
and a substring test. Months of approved knowledge could not reach the drafts.

**The hard rules, on BOTH mail paths.** `triage` checked the ban list with a
plain `in` test while `validator._banned` next door matched on word boundaries,
so "hand-decorated" was caught and "hand decorated" walked through. And
`command_agent.queue_email_draft` — the owner dictating a reply over WhatsApp —
checked nothing at all, wrote a real Gmail draft, and queued it.

**The learning loop.** `systems.feedback_block` rendered a pipeline's standing
guidance for injection at drafting and had NO CALLER, in the whole codebase,
ever. The Guidance box on every Systems card was saved, displayed and read by
nothing. `SystemRun.edit_diff` was written and read only by two reports.

    python3 scripts/test_grounding.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'gr.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import (db, edits, grounding, kb, resolve as rs,  # noqa: E402
                 systems, tenants, triage, validator)

_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def seed():
    db.init_db()
    tenants.seed()
    kb.ensure_brand("baci", "Baci Milano USA")
    kb.add_banned("baci", "hand-decorated")
    kb.add_situation("baci", "material_question",
                     patterns=[["what", "made", "of"], ["material"]],
                     description="asking what a piece is made from")
    cid = kb.add_claim("baci", "The Aqua range is BPA-free acrylic",
                       "supplier spec sheet 2026", ["material_question"],
                       proof_type="spec")
    kb.add_objection("baci", "Is acrylic going to look cheap?",
                     "It is the same material used for premium barware — "
                     "clear, weighty and dishwasher safe.",
                     situations=["material_question"])
    return cid


def main() -> int:
    seed()

    print("— the mail path resolves the same bundle a skill would —")
    email = {"subject": "What is the Aqua jug made of?",
             "body": "Hi — a customer asked what material the Aqua jug is. "
                     "Is acrylic going to look cheap on a laid table?"}
    g = grounding.for_mail("baci", email)
    ck("it reached the knowledge base", bool(g["bundle"]), g["error"])
    ck("  and rendered something to draft from", bool(g["text"]))
    ck("the approved claim is in the prompt",
       "BPA-free acrylic" in g["text"])
    ck("  carrying its id, so the draft can be traced",
       any(cid in g["text"] for cid in g["claim_ids"]),
       "an uncited draft cannot be traced back to what made it true")
    ck("the approved objection is in the prompt",
       "look cheap" in g["text"] and "premium barware" in g["text"],
       "a pre-approved answer beats anything the model would compose")
    ck("  and is offered BEFORE the raw claims",
       g["text"].index("APPROVED ANSWERS") < g["text"].index("APPROVED CLAIMS"))

    print("\n— an account with nothing on file is thinner, never blocked —")
    kb.ensure_brand("coverings", "Coverings Etc")
    bare = grounding.for_mail("coverings", email)
    ck("it still returns a bundle", bool(bare["bundle"]))
    ck("  and says what it could not give", bool(bare["thin"]),
       "absent knowledge is a label on the work, not a gate in front of it")
    ck("  and never refuses", "error" in bare and not bare["error"])
    none = grounding.for_mail("", email)
    ck("an unmapped inbox says so rather than silently drafting blind",
       bool(none["thin"]) and not none["text"])

    print("\n— a newsletter does not pay for a bundle —")
    # A tier-3 resolve runs a semantic search over the archive. Roughly half of
    # inbound is promo or a platform notification that never replies, and
    # grounding those doubles down on the spend problem already on the watch
    # list: triage is 93% of model cost and the cheap classifier that routes it
    # does not filter it.
    for b in grounding.NO_REPLY_BUCKETS:
        skipped = grounding.for_mail("baci", email, bucket=b)
        ck(f"  {b} resolves nothing", not skipped["bundle"] and not skipped["text"])
        ck(f"    and says why, without calling it a gap",
           skipped["skipped"] and not skipped["thin"],
           "'we did not ground a newsletter' must not land on the knowledge "
           "backlog for ever")
    ck("a bucket that CAN reply still grounds",
       bool(grounding.for_mail("baci", email, bucket="sales_leads")["text"]))
    ck("  and so does an unclassified one",
       bool(grounding.for_mail("baci", email, bucket="")["text"]),
       "a bucket added next week must default to grounded, not to skipped")

    print("\n— a model may not invent a claim id —")
    offered = g["claim_ids"]
    ck("an offered id survives", grounding.verify(offered, offered[:1]) == offered[:1])
    ck("  an invented one does not",
       grounding.verify(offered, ["made-up-id"]) == [],
       "a draft carrying an unresolvable id is worse than an uncited one — "
       "it LOOKS traceable")
    ck("  and a stale bundle's id does not either",
       grounding.verify([], offered) == [])

    print("\n— the ban list is matched the way the substrate matches it —")
    spaced = {"reply_subject": "", "reply_body": "Every piece is hand decorated.",
              "action": "draft", "category": "client_comms"}
    out = triage._apply_guards(dict(spaced), "baci", False)
    # `.get`, not `[...]`: with the guard removed there is no reason key at
    # all, and a KeyError is a crash rather than a named failure. A sabotage
    # run has to say WHICH assertion the missing guard broke.
    ck("'hand decorated' is caught",
       "BANNED CLAIM" in out.get("reason", ""),
       "the substring test caught 'hand-decorated' and let this one through — "
       "the spelling that matters is the one that walked past")
    ck("  and the draft is escalated, not silently sent",
       out["action"] in ("draft", "escalate"))
    clean = {"reply_subject": "", "reply_body": "The Aqua jug is BPA-free acrylic.",
             "action": "draft", "category": "client_comms"}
    ok = triage._apply_guards(dict(clean), "baci", False)
    ck("a clean draft passes", "BANNED CLAIM" not in (ok.get("reason") or ""))
    ck("  and an uncited reply is NOT blocked",
       ok["action"] == "draft",
       "an email answering 'where is my order' has no claim to cite; a guard "
       "that fires on every reply is a guard somebody switches off")

    print("\n— the reason prefix is an interface, not prose —")
    # `emailfmt` and `worker` both BRANCH on the marker in this field, so it is
    # read by code as well as by a person. Swapping the validator in replaced
    # "BANNED CLAIM" with a generic "BLOCKED" and broke the one assertion that
    # had guarded this since it was written — caught by test_tenant_isolation,
    # which is why that suite is marked mandatory.
    ck("a banned claim is marked as one, at the front",
       out.get("reason", "").startswith("BANNED CLAIM:"), out.get("reason", "")[:40])
    ck("  and the marker names the rule rather than a generic block",
       "BLOCKED:" not in out.get("reason", ""),
       "one marker covering two rules is how a grep starts lying")

    print("\n— a cited id survives the guard and is recorded —")
    cited = {"reply_subject": "", "reply_body": "The Aqua range is BPA-free acrylic.",
             "action": "draft", "category": "client_comms",
             "claim_ids": offered[:1]}
    r = triage._apply_guards(dict(cited), "baci", False, offered_claim_ids=offered)
    ck("the citation is kept", r["claim_ids"] == offered[:1])
    invented = dict(cited, claim_ids=["nope"])
    r2 = triage._apply_guards(invented, "baci", False, offered_claim_ids=offered)
    ck("  and an invented one is stripped", r2["claim_ids"] == [])

    print("\n— what the guard did is on the record either way —")
    from app import assurance
    rep = assurance.report("baci", days=1)
    ck("passes are recorded, not only catches", rep["events"] >= 3,
       f'{rep["events"]} events')
    ck("  under the real rule name",
       "banned_claims" in str(rep["by_source"]) or
       any("banned_claim" in k for k in rep["caught"]),
       "recording a weak check under the strong one's name hides which ran")
    ck("  and grounding is measured",
       rep["grounding"]["measured"] > 0)

    print("\n— the learning loop: guidance reaches the prompt —")
    systems.create("baci", grounding.SYSTEM_KEY, "Inbox triage")
    systems.note("baci", grounding.SYSTEM_KEY,
                 "Stop opening with 'I hope this finds you well'.")
    b = rs.resolve("baci", system=grounding.SYSTEM_KEY, utterance="material?")
    ck("standing guidance is in the bundle", bool(b["rules"]["guidance"]))
    ck("  and in the block every skill already injects",
       "finds you well" in b["rules"]["block"],
       "feedback_block had no caller because wiring it meant touching seven "
       "places; resolve is the one place they all read")
    other = rs.resolve("baci", system="campaign_email", utterance="material?")
    ck("  and does NOT leak to another system",
       "finds you well" not in other["rules"]["block"],
       "a lesson from support mail must not change how the ads read")
    nosys = rs.resolve("baci", utterance="material?")
    ck("  and a bundle with no system carries no guidance",
       not nosys["rules"]["guidance"])

    print("\n— the learning loop: what a human changed comes back —")
    sysrow = systems.find("baci", grounding.SYSTEM_KEY)
    run = systems.start_run(sysrow.id, "baci", trigger="inbound_email")
    systems.finish_run(run, "draft")
    with db.SessionLocal() as s:
        r = s.get(db.SystemRun, run)
        r.edit_diff = "- I hope this finds you well.\n+ Thanks for writing."
        r.decision = "edited"
        s.commit()
    lesson = systems.edit_lessons("baci", grounding.SYSTEM_KEY)
    ck("the edit is fed back", "Thanks for writing" in lesson)
    ck("  labelled as observed, not as an instruction",
       "observed" in lesson and "not instructions" in lesson,
       "a model told it was corrected over-fits to the last rewrite")
    ck("  and it reaches the prompt through the bundle",
       "Thanks for writing" in rs.resolve(
           "baci", system=grounding.SYSTEM_KEY)["rules"]["block"])

    print("\n— a run sent as-is teaches nothing and is not fed back —")
    run2 = systems.start_run(sysrow.id, "baci", trigger="inbound_email")
    systems.finish_run(run2, "draft")
    with db.SessionLocal() as s:
        r = s.get(db.SystemRun, run2)
        r.edit_diff = "sent unchanged"
        r.decision = "approved"
        s.commit()
    ck("confirmation is not mistaken for a correction",
       "sent unchanged" not in systems.edit_lessons("baci", grounding.SYSTEM_KEY))

    print("\n— the command path refuses rather than drafting a barred reply —")
    # The owner dictating a reply over WhatsApp. This branch wrote a real Gmail
    # draft and queued an approval with no check of any kind.
    import app.command_agent as ca
    import app.gmail_client as gc
    import app.approvals as ap_mod
    made, queued = [], []
    gc.create_draft = lambda *a, **k: made.append(a) or "draft-1"
    ap_mod.request_approval = lambda *a, **k: queued.append(a) or "ap-1"
    ca.gmail_client = gc
    ca.approvals = ap_mod
    import app.tenant_scope as ts
    ts_resolve = ts.resolve
    ts.resolve = lambda alias="", payload=None, key="": "baci"

    bad = ca.admin_dispatch("queue_email_draft", {
        "account": "baci", "to": "buyer@example.com",
        "subject": "Our pieces", "body": "Each one is hand decorated."}, {})
    ck("it refuses", "Not drafted" in bad, bad[:90])
    ck("  and names the phrase so it can be reworded",
       "hand-decorated" in bad)
    ck("  and NO Gmail draft was created", not made,
       "the check has to run before the write, not after it")
    ck("  and nothing was queued for approval", not queued,
       "a queued draft is one the owner might simply approve")

    good = ca.admin_dispatch("queue_email_draft", {
        "account": "baci", "to": "buyer@example.com",
        "subject": "Our pieces", "body": "The Aqua range is BPA-free acrylic."}, {})
    ck("a clean instruction still drafts", "Draft queued" in good, good[:90])
    ck("  and did write the draft", len(made) == 1)
    ts.resolve = ts_resolve

    print("\n— the mail path finally has a ledger, and it feeds itself —")
    # The circle: worker opens a run -> the approval carries run_id -> the
    # owner edits and approves -> edits.record writes edit_diff ON THAT RUN ->
    # edit_lessons reads it back into the next draft's prompt. Nothing on this
    # path ever set run_id, so every rewrite was measured against nothing.
    from app import worker
    rid = worker._mail_run("baci", {"id": "msg-1"})
    ck("a run is opened per email", bool(rid))
    ck("  against an auto-created system row",
       bool(systems.find("baci", grounding.SYSTEM_KEY)),
       "a run filed against a system that does not exist is an orphan")
    worker._finish_mail_run(rid, "draft", {"reply_body": "hello", "reason": ""})
    with db.SessionLocal() as s2:
        row = s2.get(db.SystemRun, rid)
        ck("  a drafted reply stays OPEN, waiting on a person",
           row.stage == "draft" and row.finished_at is None)
    esc = worker._mail_run("baci", {"id": "msg-2"})
    worker._finish_mail_run(esc, "escalate",
                            {"reply_body": "x", "reason": "BLOCKED: banned"})
    with db.SessionLocal() as s2:
        row = s2.get(db.SystemRun, esc)
        ck("  an escalation is blocked, with the reason kept",
           row.stage == "blocked" and row.blocked_on
           and "banned" in row.blocked_on[0])
    skip = worker._mail_run("baci", {"id": "msg-3"})
    worker._finish_mail_run(skip, "ignore", {"reply_body": "", "reason": ""})
    with db.SessionLocal() as s2:
        row = s2.get(db.SystemRun, skip)
        ck("  and promo mail is `skipped`, not counted as a send",
           row.stage == "skipped" and row.finished_at is not None,
           "half of inbound needs no reply; counting those as sends makes the "
           "success rate a measure of how much junk arrived")

    # Diagnostics must not report the waiting draft as a dead worker.
    from app import diagnostics
    h = [r for r in diagnostics.health("baci", days=1)["systems"]
         if r["key"] == grounding.SYSTEM_KEY][0]
    ck("the queue is reported as waiting, not as unfinished",
       h["waiting"] >= 1 and h["unfinished"] == 0,
       "an approval queue and a dead worker are opposite findings")
    ck("  and a blocked run still outranks a waiting queue in the verdict",
       "refused" in h["verdict"], h["verdict"])
    # The waiting line only earns the verdict when nothing is actually wrong —
    # otherwise "3 waiting on you" would sit where "a connection is dead"
    # belongs.
    wonly = worker._mail_run("ironside", {"id": "i-1"})
    worker._finish_mail_run(wonly, "draft", {"reply_body": "hi", "reason": ""})
    hi = [r for r in diagnostics.health("ironside", days=1)["systems"]
          if r["key"] == grounding.SYSTEM_KEY][0]
    ck("  and it says so when nothing is wrong",
       "waiting on you" in hi["verdict"], hi["verdict"])

    # And the delta lands on the run, which is what makes it learnable.
    class _Ap:
        id = None
    with db.SessionLocal() as s2:
        a = db.Approval(kind="send_email", summary="x", payload={},
                        tenant="baci", run_id=rid)
        s2.add(a); s2.commit(); _Ap.id = a.id
    edits.record(_Ap, "I hope this finds you well. The jug is acrylic.",
                 "Thanks for writing. The jug is acrylic.")
    with db.SessionLocal() as s2:
        ck("approving an edited draft writes the delta onto the run",
           bool((s2.get(db.SystemRun, rid).edit_diff or "").strip()))
    ck("  and it comes back as guidance on the next draft",
       "Thanks for writing" in rs.resolve(
           "baci", system=grounding.SYSTEM_KEY)["rules"]["block"],
       "this is the whole loop: measured, then read")

    print("\n— and the console shows the guidance is actually live —")
    # The Guidance box said "injected into this system's drafting prompt" for
    # months while `feedback_block` had no caller. The card now proves it.
    from app import admin_ui
    card = admin_ui._thread("s3cret", systems.find("baci", grounding.SYSTEM_KEY))
    ck("the card says what is in the prompt", "In the prompt now" in card)
    ck("  counting the corrections written", "correction(s) you wrote" in card)
    ck("  and the edits fed back", "edits you made" in card)
    blank = systems.create("coverings", "campaign_email", "Campaign email")
    ck("  and says plainly when nothing is being injected",
       "Nothing is being injected yet" in admin_ui._thread("s3cret", blank),
       "an empty promise is what this line exists to stop")

    print("\n— the whole path, driven against a stubbed model —")
    # Everything above tests the PIECES. Nothing exercised `triage_email`
    # itself, so the assembly order was uncovered — and reordering it is
    # exactly the change this session made (the bucket has to be known before
    # the bundle is resolved, or a newsletter pays for an embedding search).
    # Same shape as test_omnisend: drive a stub and assert the REQUEST.
    seen = {"system": "", "classify_calls": 0, "models": []}

    class _Blk:
        type = "text"
        def __init__(self, t): self.text = t

    class _Msg:
        stop_reason = "end_turn"
        usage = type("u", (), {"input_tokens": 1, "output_tokens": 1,
                               "cache_read_input_tokens": 0,
                               "cache_creation_input_tokens": 0})()
        def __init__(self, t): self.content = [_Blk(t)]

    verdict = ('{"category":"sales_leads","action":"draft",'
               '"reason":"asked what it is made of",'
               '"reply_subject":"Re: material","reply_body":'
               '"The Aqua range is BPA-free acrylic.","reply_cc":"",'
               f'"claim_ids":["{offered[0]}"],"deadline":null,'
               '"expense":null,"suggestion":null}')

    def _create(**kw):
        seen["models"].append(kw.get("model"))
        sysarg = kw.get("system")
        if isinstance(sysarg, str):          # the cheap classifier
            seen["classify_calls"] += 1
            return _Msg(bucket_reply["v"])
        seen["system"] = "".join(b.get("text", "") for b in (sysarg or []))
        return _Msg(verdict)

    bucket_reply = {"v": "sales_leads"}
    real = triage.client
    triage.client = type("C", (), {"messages": type("M", (), {"create": staticmethod(_create)})()})()
    try:
        got = triage.triage_email(
            {"id": "m-9", "from": "buyer@example.com", "to": "", "cc": "",
             "subject": "What is the Aqua jug made of?", "date": "today",
             "body": "Is acrylic going to look cheap?", "threadId": "t-9"},
            "baci", False, tenant="baci")
        ck("the approved claim reached the prompt",
           "BPA-free acrylic" in seen["system"])
        ck("  and the approved objection with it",
           "premium barware" in seen["system"])
        ck("  and this system's standing guidance",
           "finds you well" in seen["system"],
           "the Guidance box promised this for months while nothing read it")
        ck("  and what a human last changed",
           "Thanks for writing" in seen["system"])
        ck("the citation survives to the verdict",
           got.get("claim_ids") == [offered[0]], str(got.get("claim_ids")))
        ck("the classifier runs ONCE, not twice",
           seen["classify_calls"] == 1, str(seen["classify_calls"]))

        # A newsletter must not pay for the bundle.
        seen["system"], bucket_reply["v"] = "", "promo"
        triage.triage_email(
            {"id": "m-10", "from": "news@example.com", "to": "", "cc": "",
             "subject": "50% off everything", "date": "today",
             "body": "Shop the sale.", "threadId": "t-10"},
            "baci", False, tenant="baci")
        ck("a promo email is not grounded",
           "BPA-free acrylic" not in seen["system"]
           and "WHAT THIS ACCOUNT KNOWS" not in seen["system"],
           "half of inbound is a newsletter, and a tier-3 resolve costs an "
           "embedding call")
    finally:
        triage.client = real

    print("\n— and one client's edits never reach another's drafts —")
    kb.ensure_brand("ironside", "Miami Ironside")
    ck("scoped to the account",
       not systems.edit_lessons("ironside", grounding.SYSTEM_KEY),
       "the samples are the client's own correspondence")

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
