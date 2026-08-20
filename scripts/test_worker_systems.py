"""The worker is the engine the systems ledger never had.

`start_run` and `finish_run` existed with no callers outside their own test, so
every run count on the Systems tab was structurally zero and `blocked_reasons()`
— the KB backlog ranked by how often each gap actually cost an output — had
nothing to rank.

Two things are checked here. That the tick records real blockers without
sending anything, and that the inbox loop is driven by the tenant registry
rather than the env blob, *without* silently dropping a mailbox that has no
tenant row — which would stop mail being processed with nothing to say so.

    python3 scripts/test_worker_systems.py
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'ws.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["GMAIL_ACCOUNTS_JSON"] = (
    '{"personal":{"email":"g@x.com","refresh_token":"r"},'
    '"baci":{"email":"b@x.com","refresh_token":"r"},'
    '"orphan":{"email":"o@x.com","refresh_token":"r"}}')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, kb, kb_seed, systems, tenants, worker  # noqa: E402

_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    db.init_db()
    tenants.seed()
    kb.seed_agency()
    kb_seed.seed_all()
    systems.seed_from_tenants()

    # ---- the inbox loop is registry-driven -------------------------------
    print("— which inboxes, for whom —")
    pairs = dict(worker.inboxes())
    ck("every configured mailbox is still polled", len(pairs) == 3, str(pairs))
    ck("a claimed inbox resolves to its client", pairs.get("baci") == "baci")
    ck("the agency inbox resolves too", pairs.get("personal") == "agency")
    ck("an inbox with NO tenant is still polled, not silently dropped",
       "orphan" in pairs, "a dropped inbox stops mail with nothing to say so")
    ck("and is marked unattributed rather than guessed",
       pairs.get("orphan") == "")

    # ---- the tick records, and sends nothing ------------------------------
    print("\n— the systems tick —")
    all_sys = systems.all_systems()
    ck("systems are installed to evaluate", len(all_sys) > 0, f"{len(all_sys)}")

    before = sum(len(systems.runs(s.id, limit=0)) for s in all_sys)
    ck("the ledger starts empty — nothing ever called it", before == 0,
       f"{before} runs")

    worker.systems_tick()

    after = sum(len(systems.runs(s.id, limit=0)) for s in all_sys)
    ck("the tick recorded a run for every system", after == len(all_sys),
       f"{after} runs for {len(all_sys)} systems")

    stages = set()
    for s in all_sys:
        for r in systems.runs(s.id, limit=0):
            stages.add(r.stage)
    ck("nothing was recorded as sent", "sent" not in stages, str(stages))
    ck("blocked runs carry a named reason",
       all(r.blocked_on for s in all_sys for r in systems.runs(s.id, limit=0)
           if r.stage == "blocked"))

    # ---- and the backlog is now rankable ----------------------------------
    print("\n— the KB backlog, ranked by what it cost —")
    reasons = systems.blocked_reasons()
    ck("blocked_reasons() finally has something to rank", bool(reasons),
       str(reasons[:1]))
    ck("it is ordered by frequency",
       [n for _, n in reasons] == sorted([n for _, n in reasons], reverse=True))
    # `blocked_on` is a JSON list and `blocked_reasons` iterates it. Passing a
    # joined string instead ranked ' ' and 'e' as the two costliest gaps — the
    # assertions above all passed while the output was nonsense.
    ck("a reason is a whole sentence, not a character",
       all(len(r) > 3 for r, _ in reasons),
       str([r for r, _ in reasons if len(r) <= 3][:5]))
    ck("and it reads like the thing that is missing",
       any("contract" in r or "connected" in r or "knowledge base" in r
           or "generator" in r for r, _ in reasons),
       str(reasons[:1]))
    for s in all_sys[:3]:
        for r in systems.runs(s.id, limit=1):
            ck(f"{s.tenant}/{s.key} stores blockers as a list",
               isinstance(r.blocked_on, list), type(r.blocked_on).__name__)

    # ---- a system that cannot run says why --------------------------------
    print("\n— what is actually blocking them —")
    for s in all_sys[:4]:
        state = systems.ready(s)
        run = systems.runs(s.id, limit=1)[0]
        if not state["ready"]:
            ck(f"{s.tenant}/{s.key} blocked for a stated reason",
               run.stage == "blocked" and bool(run.blocked_on),
               (run.blocked_on or "")[:80])
        else:
            # CHANGED 2026-08-20. This pinned "no generator yet" as a BLOCKED
            # run with the reason in `blocked_on`. The owner read a week of it
            # and was right: our missing generator is not the account's gap,
            # and `blocked_on` feeds `blocked_reasons()` — the ranking of what
            # to go and WRITE — where it sat at the top for ever, unanswerable
            # by any amount of writing about the client.
            ck(f"{s.tenant}/{s.key} is ready and is filed as not_built",
               run.stage == "not_built", run.stage)
            ck(f"  and says so without claiming the account is missing it",
               "no generator" in (run.error or "") and not (run.blocked_on or []),
               (run.error or "")[:70])

    # ---- re-running is safe ------------------------------------------------
    print("\n— running it again —")
    worker.systems_tick()
    after2 = sum(len(systems.runs(s.id, limit=0)) for s in all_sys)
    ck("a second tick adds one run per system, not a duplicate storm",
       after2 == after * 2, f"{after2}")

    # ---- a paused system is left alone -------------------------------------
    print("\n— paused means paused —")
    target = all_sys[0]
    with db.SessionLocal() as s:
        s.get(db.System, target.id).status = "paused"
        s.commit()
    n_before = len(systems.runs(target.id, limit=0))
    worker.systems_tick()
    ck("a paused system is not evaluated",
       len(systems.runs(target.id, limit=0)) == n_before)

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
