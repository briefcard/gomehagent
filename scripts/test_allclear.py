"""Escalation is success, and "that was me" has to stick.

Two corrections the owner made after reading a real week of logs.

**Escalation is not a problem.** Routing a carding attack, an MFA change or a
verification deadline to a person is the CORRECT outcome. It was being filed as
a `blocked` run, so the Diagnostics tab listed the mail path's best work as
failures — and each escalation's reasoning went into `blocked_reasons()`, which
ranks what to go and WRITE into the knowledge base, where no amount of writing
could ever satisfy "verify this with TD Bank out of band". His rule, and it is
the right one: *a problem is a log showing a response was required and failed
to happen.*

**And nothing could be cleared.** The same concerns were raised five times
because nothing could tell the model a person had already looked — while a
stale working-memory note about a possible breach inflated every
security-shaped email that arrived after it.

    python3 scripts/test_allclear.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'ac.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import (db, diagnostics, kb, memory, systems,  # noqa: E402
                 tenants, web, worker)

_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    db.init_db()
    tenants.seed()
    kb.ensure_brand("baci", "Baci Milano USA")

    print("— an escalation is the system working, not a problem —")
    rid = worker._mail_run("baci", {"id": "m-1"})
    worker._finish_mail_run(rid, "escalate", {
        "reply_body": "",
        "reason": "Klaviyo TOTP MFA added — verify this was you"})
    with db.SessionLocal() as s:
        row = s.get(db.SystemRun, rid)
        ck("it is filed as escalated, not blocked", row.stage == "escalated",
           row.stage)
        ck("  and nothing lands on the knowledge backlog",
           not (row.blocked_on or []),
           "no amount of writing satisfies 'verify this out of band'")
        ck("  while the reason is kept and readable",
           "Klaviyo" in (row.output or ""))

    h = [r for r in diagnostics.health("baci", days=1)["systems"]
         if r["key"] == "inbox_triage"][0]
    ck("the tab counts ZERO problems", h["problems"] == 0, str(h["problems"]))
    ck("  counts it as raised for you", h["escalated"] == 1)
    ck("  and the verdict says so rather than reporting a refusal",
       "raised for you" in h["verdict"], h["verdict"])

    ev = [e for e in diagnostics.events("baci", days=1) if e["kind"] == "run"]
    ck("the log row reads as OK", ev and ev[0]["level"] == "ok",
       str(ev[0]["level"]) if ev else "none")
    ck("  and says what was raised", "Klaviyo" in ev[0]["detail"])

    print("\n— mail that needed no reply is also not a problem —")
    r2 = worker._mail_run("baci", {"id": "m-2"})
    worker._finish_mail_run(r2, "ignore", {"reply_body": "", "reason": ""})
    h = [r for r in diagnostics.health("baci", days=1)["systems"]
         if r["key"] == "inbox_triage"][0]
    ck("still zero problems", h["problems"] == 0, str(h["problems"]))
    ck("  and it is counted as worked", h["worked"] == 2, str(h["worked"]))

    print("\n— a real failure still IS a problem —")
    r3 = worker._mail_run("baci", {"id": "m-3"})
    worker._finish_mail_run(r3, "somethingelse", {"reply_body": "x"})
    with db.SessionLocal() as s:
        row = s.get(db.SystemRun, r3)
        row.stage, row.error = "failed", "ShopifyError: 401"
        s.commit()
    h = [r for r in diagnostics.health("baci", days=1)["systems"]
         if r["key"] == "inbox_triage"][0]
    ck("a raised run counts", h["problems"] == 1, str(h["problems"]))

    print("\n— 'no generator yet' is our build queue, not the account's gap —")
    srow = systems.create("baci", "service_desk", "Service desk")
    run = systems.start_run(srow.id, "baci", trigger="schedule")
    systems.finish_run(run, "not_built",
                       error="no generator yet — system is otherwise able to run")
    ck("it does not reach the knowledge backlog",
       not [r for r in systems.blocked_reasons("baci", 7)
            if "generator" in r[0]],
       "it dominated the ranking of what to go and write")
    h = [r for r in diagnostics.health("baci", days=1)["systems"]
         if r["key"] == "service_desk"][0]
    ck("  and is not counted as a problem", h["problems"] == 0)
    ck("  while still being visible", h["not_built"] == 1)
    ck("  and named honestly in the verdict",
       "our build queue" in h["verdict"], h["verdict"])

    print("\n— the contract is advisory, not a gap the account has to fill —")
    srow2 = systems.create("baci", "content_compliance", "Website content")
    st = systems.ready(srow2)
    ck("a blank contract does not appear as missing knowledge",
       not any("contract" in t for t in st["thin"]), str(st["thin"]))
    ck("  and does not stop the system producing", st["can_produce"] is True)
    ck("  while still being visible to a person",
       st["contract_complete"] is False and st["missing_contract"],
       "the eight questions are worth answering, just not a blocker")
    # The gate only fires on a system that is otherwise READY — `can_promote`
    # checks readiness first, and a system blocked on knowledge never reaches
    # the contract question.
    kb.add_banned("baci", "hand-decorated")
    srow2.autonomy = "approve_exceptions"
    st2 = systems.ready(srow2)
    ck("  (the system is otherwise ready)", st2["ready"], str(st2["blockers"]))
    gate = systems.can_promote(srow2)
    ck("  but it DOES gate the unattended rung",
       not gate["can"] and "contract" in gate["why"], gate["why"][:80])
    ck("    naming what is still blank", "Kill criteria" in gate["why"])

    print("\n— the mail path is not evaluated by the substrate loop —")
    ck("inbox_triage is declared externally driven",
       "inbox_triage" in systems.EXTERNALLY_DRIVEN,
       "it drafts through triage and files its own runs; the tick reported it "
       "as having no generator while it was answering mail all day")

    print("\n— 'that was me' sticks, and reaches the drafter —")
    memory.clear_concern("Klaviyo TOTP MFA added 20 Aug", "that was Gomeh")
    block = memory.cleared_block()
    ck("it is recorded", "Klaviyo" in block)
    ck("  and says not to raise it again", "Do NOT escalate" in block)
    ck("  and it reaches triage's prompt",
       "Klaviyo" in memory.cleared_block("baci"))

    print("\n— but it clears the EVENT, never the category —")
    ck("the caveat is explicit",
       "not the category" in block and "still worth raising" in block,
       "'the MFA change was fine' must not become 'MFA changes are fine' — "
       "the next one is the real one")

    print("\n— and the stale belief that inflates everything is visible —")
    memory.remember("possible breach", "DHL account-permission grant looked odd")
    notes = memory.working_notes()
    ck("working memory can be read at last", any(
        n["topic"] == "possible breach" for n in notes), str(notes)[:80])
    ck("  cleared items are listed apart from beliefs",
       not any(n["topic"].startswith("cleared:") for n in notes),
       "one says what is true, the other says what has been answered")
    nid = [n["id"] for n in notes if n["topic"] == "possible breach"][0]
    memory.retire(nid)
    ck("  and it can be retired", not any(
        n["topic"] == "possible breach" for n in memory.working_notes()))
    ck("  which stops it being injected",
       "DHL" not in memory.memory_block("", "baci"))

    print("\n— reachable from where the alarm is read —")
    c = TestClient(web.app)
    r = c.get("/admin/allclear?key=s3cret&what=TD+Bank+overdraft+alert"
              "&because=verified+with+the+bank").json()
    ck("one call clears it", r.get("ok") is True, str(r)[:70])
    ck("  and it shows up", any("TD Bank" in x["content"]
                                for x in memory.concerns()))
    m = c.get("/admin/memory?key=s3cret").json()
    ck("the console shows both halves",
       "working_memory" in m and "cleared" in m)
    anon = TestClient(web.app)
    rr = anon.get("/admin/memory")
    ck("unauthorised cannot read it",
       rr.status_code >= 400 or "error" in rr.json(), str(rr.status_code))

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
