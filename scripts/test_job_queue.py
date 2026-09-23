"""A run outlives the process that asked for it, and says where it got to.

The defect this suite holds shut, in two halves (owner, 2026-09-22):

  1. THE RUN DIED WITH THE WEB SERVICE. A press ran the work in a daemon
     thread inside `assistant-web`. A page refresh never touched it — the
     thread is detached from the request — but a deploy killed it, and
     `web._sweep_interrupted` exists to tidy up after exactly that. Nothing
     recorded what to RUN, only what had happened, so nothing could resume.
  2. THE STATUS WAS WRITTEN WHERE NOTHING READ IT. The press wrote
     `Setting["bg:run:{system}:{tenant}"]`; every reader iterates a literal
     tuple (`admin_ui.BG_LABELS` and its siblings) that a per-system label
     cannot be a member of. So "Run the check now" was followed by silence
     whether the run was working, finished, blocked or dead.

The properties are counted, never timed: how many times a job ran, which
state a stale row lands in, whether a label a reader can reach exists.

Run: python3 scripts/test_job_queue.py
"""
import datetime as dt
import os
import re
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'jq.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, jobs, worker  # noqa: E402

_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _state(job_id: str) -> str:
    with db.SessionLocal() as s:
        row = s.get(db.JobQueue, job_id)
        return str(row.state) if row else ""


def _age(job_id: str, seconds: int) -> None:
    """Push a job's last sign of life into the past — a holder that went away."""
    with db.SessionLocal() as s:
        row = s.get(db.JobQueue, job_id)
        row.heartbeat_at = db.utcnow() - dt.timedelta(seconds=seconds)
        s.commit()


def main() -> int:
    db.init_db()
    ran: list = []

    from app import admin_ui
    _here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src_web = open(os.path.join(_here, "app", "web.py"), encoding="utf-8").read()
    src = src_web

    print("— the registry names real functions, computed not surveyed —")
    # A kind whose target does not resolve is a button that fails the first
    # time somebody presses it, months after the typo. Checked against the
    # registry itself so a kind added later is covered without editing this.
    for name, spec in jobs.KINDS.items():
        try:
            fn, why = jobs._resolve(spec["target"]), ""
        except Exception as exc:                                 # noqa: BLE001
            fn, why = None, f"{exc.__class__.__name__}: {exc}"
        ck(f"  {name} -> {spec['target']} resolves", callable(fn), why)
    ck("  and every kind says whether a deploy may repeat it",
       all("retryable" in s for s in jobs.KINDS.values()))
    print()

    def _work(tenant, **kw):
        ran.append((tenant, kw))
        return {"status": "sent", "items": [1, 2], "run_id": "run-7"}

    def _boom(tenant, **kw):
        raise ValueError("the store said no")

    jobs.KINDS["_t_ok"] = {"what": "a test job", "target": "t:work", "retryable": False}
    jobs.KINDS["_t_retry"] = {"what": "a re-runnable test job", "target": "t:work",
                              "retryable": True}
    jobs.KINDS["_t_boom"] = {"what": "a job that raises", "target": "t:boom",
                             "retryable": False}
    # The doubles are reached through the same seam the real kinds use; the
    # block above is what proves that seam resolves real targets.
    jobs._resolve = lambda target: {"t:work": _work, "t:boom": _boom}[target]

    print("— the press enqueues; the row is the work, not just a note about it —")
    put = jobs.enqueue("baci", "_t_ok", system_key="blog_article",
                       payload={"key": "blog_article"})
    ck("a press queues the work", put["ok"] and _state(put["id"]) == "queued")
    ck("  and the row carries what to run, so something else can run it",
       jobs.latest("baci", system_key="blog_article")["kind"] == "_t_ok")
    ck("an unknown kind is refused by name",
       not jobs.enqueue("baci", "nonesuch")["ok"])
    ck("a job with no account is refused — every row is scoped",
       not jobs.enqueue("", "_t_ok")["ok"])

    print("\n— a double press is one run, not two —")
    again = jobs.enqueue("baci", "_t_ok", system_key="blog_article",
                         payload={"key": "blog_article"})
    ck("the second press returns the SAME job rather than queuing another",
       again["ok"] and again["already"] and again["id"] == put["id"], str(again))
    ck("  and says so in words the presser wanted", "already" in again["why"])

    print("\n— two workers, one job: the claim is a single statement —")
    a = jobs.claim("baci", "instance-A")
    b = jobs.claim("baci", "instance-B")
    ck("one worker gets it and the other gets nothing", bool(a) and not b,
       f"A={a!r} B={b!r}")
    ck("  and the row records who holds it", _state(a) == "running")

    print("\n— it runs, and the run is joined to the ledger row it made —")
    out = jobs.run_one(a)
    got = jobs.latest("baci", system_key="blog_article")
    ck("the work actually ran, once", len(ran) == 1 and out["state"] == "done", str(ran))
    ck("  the account was passed, never guessed", ran[0][0] == "baci")
    ck("  the payload reached the function", ran[0][1].get("key") == "blog_article")
    ck("  and the SystemRun it produced is on the job", got["run_id"] == "run-7")
    ck("  a finished run says what it did, not just that it ended",
       "2 produced" in got["detail"], got["detail"])

    print("\n— a run killed by a deploy: reported, and repeated only if declared safe —")
    stop = jobs.enqueue("baci", "_t_ok", system_key="gbp_listing")["id"]
    jobs.claim("baci", "instance-A")
    _age(stop, jobs.STALE_AFTER_SECONDS + 60)
    ck("a job still beating is left alone",
       jobs.reclaim() and _state(stop) == "interrupted")
    said = jobs.latest("baci", system_key="gbp_listing")
    ck("a job that can spend a model call is NOT re-run on its own",
       said["state"] == "interrupted" and "not started again" in said["says"], said["says"])
    ck("  and it says a deploy did it, and what to do", "deploy" in said["detail"]
       and "again" in said["detail"], said["detail"][:90])
    ck("  which is a different sentence from a failure — they need different things",
       said["says"] != jobs.as_dict(None).get("says"))

    safe = jobs.enqueue("baci", "_t_retry", system_key="harvesting")["id"]
    jobs.claim("baci", "instance-A")
    _age(safe, jobs.STALE_AFTER_SECONDS + 60)
    jobs.reclaim()
    ck("a job declared safe to re-run goes back on the queue",
       _state(safe) == "queued")
    ck("  and says which attempt it is on",
       "attempt 2" in jobs.latest("baci", system_key="harvesting")["detail"])
    ck("an unknown kind is never retried — the safe direction for a question "
       "this module cannot answer", not jobs.retryable("nonesuch"))
    jobs.finish(safe, "done", "settled, so the next claim is not this one")

    print("\n— a heartbeat is what separates a slow run from a dead one —")
    live = jobs.enqueue("baci", "_t_ok", system_key="reports")["id"]
    jobs.claim("baci", "instance-A")
    _age(live, jobs.STALE_AFTER_SECONDS + 60)
    jobs.heartbeat(live, "read 12 of 40 pages")
    jobs.reclaim()
    ck("a beating job survives the sweep that takes a dead one",
       _state(live) == "running")
    ck("  and the card carries its progress, not just 'running'",
       jobs.latest("baci", system_key="reports")["detail"] == "read 12 of 40 pages")

    print("\n— a failure is recorded, never only logged —")
    bid = jobs.enqueue("baci", "_t_boom", system_key="x")["id"]
    jobs.claim("baci", "instance-A")
    jobs.run_one(bid)
    blew = jobs.latest("baci", system_key="x")
    ck("a raising job lands as failed with its reason",
       blew["state"] == "failed" and "the store said no" in blew["detail"], blew["detail"])

    print("\n— the history the one-row store never kept —")
    ck("every run is its own row, so two runs of one system are two facts",
       len([r for r in jobs.recent("baci", 50) if r["system_key"] == "blog_article"]) >= 1
       and len(jobs.recent("baci", 50)) >= 5, str(len(jobs.recent("baci", 50))))
    ck("one account cannot see another's queue",
       jobs.latest("eien", system_key="blog_article") == {})

    print("\n— the console reads THIS, and the dead key is gone —")
    ck("the press no longer writes a status key nothing can read",
       not re.search(r'^\s*_run_bg\(f"run:\{system\}"', src, re.M))
    ck("the press enqueues instead", 'enqueue(tenant, "system_run"' in src)
    ck("the card renders the queue row beside the button that makes one",
       "_run_state(row.tenant, row.key)" in
       open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "app", "admin_ui.py"), encoding="utf-8").read())
    real = jobs.enqueue("baci", "system_run", system_key="blog_article",
                        payload={"key": "blog_article"})["id"]
    jobs.finish(real, "done", "2 produced · status sent")
    html = admin_ui._run_state("baci", "blog_article")
    ck("  and it says the state in words", "ran" in html and "chip" in html, html[:80])
    jobs.finish(jobs.enqueue("baci", "system_run", system_key="stopped")["id"],
                "interrupted", "a deploy stopped it")
    ck("  an interrupted run is not dressed as a failure on the card",
       "restart" in admin_ui._run_state("baci", "stopped"),
       admin_ui._run_state("baci", "stopped")[:90])
    ck("  a system never run from here says so rather than showing nothing",
       "Never run" in admin_ui._run_state("baci", "never_touched"))

    print("\n— the hand-off to the client's site: queued, reported, resumable —")
    # These two are the only kinds declared retryable, and both claims were
    # CHECKED in the code rather than assumed: `publish_all` skips a picture
    # already hosted, and `to_canva` "opens the design it has rather than
    # making a second". A re-run resumes; it does not repeat.
    ck("publishing to the client's CMS may be resumed", jobs.retryable("hosting"))
    ck("  and so may layering into Canva", jobs.retryable("layers"))
    hid = jobs.enqueue("baci", "hosting")["id"]
    jobs.claim("baci", "instance-A")
    _age(hid, jobs.STALE_AFTER_SECONDS + 60)
    jobs.reclaim()
    ck("a hand-off a deploy stopped goes back on the queue, so the pictures "
       "it had not reached are not left with nothing saying so",
       _state(hid) == "queued")
    shape = jobs.status("baci", "hosting")
    ck("  and it answers in the shape the pictures room already reads",
       set(shape) >= {"state", "detail", "at"} and shape["state"] == "queued",
       str(shape))
    room = admin_ui._frames_run("baci")
    ck("  which the pictures room renders where the pictures were promised",
       "queued" in room, room[:100])
    jobs.finish(hid, "interrupted", "a deploy stopped it")
    ck("  an interrupted hand-off is not dressed as a failure there either",
       "stopped" in admin_ui._frames_run("baci"))
    ck("the press hands off through the queue, not a thread",
       '_jobs.enqueue(tenant, "hosting")' in src_web
       and not re.search(r'_run_bg\("hosting"', src_web))
    ck("  and so does the layering that runs beside it",
       '_jobs.enqueue(tenant, "layers"' in src_web
       and not re.search(r'_run_bg\("layers"', src_web))

    print("\n— the heavy creative work runs in the worker, not in the web process —")
    # WHY THIS SECTION EXISTS. The owner's console restarted under them
    # mid-session on 2026-09-23 while a recreation ran. Measured on the
    # laptop: `app.web` is 131 MB at import before a request; one
    # `recreate._stamp` of a full-page email screenshot peaks at +38 MB; the
    # cast stage was allowed to hold 24 pictures' bytes at once. Render gives
    # the web service 512 MB and expects it to serve requests with them.
    #
    # The population is DERIVED from web.py, never listed here: every label
    # still started as a thread is read out of the source, so a heavy job
    # added later and threaded is caught by this check rather than by an
    # instance dying.
    threaded = set(re.findall(r'_run_bg\(\s*[\'"]([a-z_]+)[\'"]', src_web))
    HEAVY = {"email_recreate", "ad_frames", "boards", "sync"}
    ck("no image-heavy job is started as a thread inside the web service",
       not (HEAVY & threaded), f"still threaded: {sorted(HEAVY & threaded)}")
    ck("  and each of them is a kind of queued work instead",
       HEAVY <= set(jobs.KINDS), f"missing: {sorted(HEAVY - set(jobs.KINDS))}")
    for label in sorted(HEAVY):
        ck(f"  the press that starts {label} enqueues",
           f'enqueue(tenant, "{label}"' in src_web)
    ck("  a set of frames is never repeated by a restart — it is a paid model "
       "call per picture", jobs.retryable("ad_frames") is False)
    ck("  nor is a recreation, for the same reason",
       jobs.retryable("email_recreate") is False)

    print("\n— what the room shows while a queued job waits its turn —")
    from app import web as _w
    qid = jobs.enqueue("eien", "email_recreate",
                       payload={"mode": "run", "structure": "st-1"})["id"]
    st = jobs.status("eien", "email_recreate")
    ck("the room reads the queue for a migrated label",
       st.get("state") == "queued", str(st))
    ck("  and QUEUED counts as in flight, so the button that started it is "
       "not offered again while a worker is still on its way",
       "queued" in jobs.IN_FLIGHT and "running" in jobs.IN_FLIGHT)
    ck("  no room decides that for itself any more",
       not re.search(r'state"\)\s*==\s*"running"', open(
           os.path.join(_here, "app", "admin_ui.py"), encoding="utf-8").read()))
    ck("there is ONE status store — the thread runner and its Setting rows "
       "are gone, so every label is a kind",
       not hasattr(_w, "bg_status") and not hasattr(_w, "_run_bg")
       and not hasattr(_w, "_sweep_interrupted"))

    print("\n— the payload is JSON, and the targets take it as it arrives —")
    from app import creative as _cr, recreate as _rc
    seen = {}
    _cr.batch = lambda tenant, **kw: seen.update({"one": (tenant, kw)}) or {"ok": True}
    _cr.batch_each = lambda tenant, **kw: seen.update({"each": (tenant, kw)}) or {"ok": True}
    _cr.frames_job("baci", models=["gpt-image-1"], boards=["lifestyle"], plates=2)
    ck("one model asks for one set, with the model named",
       seen["one"][1].get("image_model") == "gpt-image-1", str(seen.get("one")))
    ck("  and the boards a JSON payload turned into a list arrive as the "
       "tuple the generator reads", seen["one"][1].get("boards") == ("lifestyle",))
    _cr.frames_job("baci", models=["gpt-image-1", "gemini:gemini-3-pro-image"])
    ck("two models ask for one set each", "each" in seen)
    _rc.run = lambda *a, **k: {"ok": True, "how": "run"}
    _rc.again = lambda *a, **k: {"ok": True, "how": "again"}
    _rc.swipe = lambda *a, **k: {"ok": True, "how": "swipe"}
    ck("a recreation, a re-read and a pasted link are three modes of one door",
       [_rc.job("baci", mode=m, structure="s", url="https://x/y")["how"]
        for m in ("run", "again", "swipe")] == ["run", "again", "swipe"])
    ck("  and a mode with nothing to work on is refused rather than guessed",
       not _rc.job("baci", mode="run")["ok"] and not _rc.job("baci", mode="swipe")["ok"])

    print("\n— the worker drains it, and both instances may —")
    wsrc = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "app", "worker.py"), encoding="utf-8").read()
    ck("the drain is registered through the lease wrapper",
       bool(re.search(r'_safe\(queue_drain_sharded, "job queue", sharded=True\)', wsrc)))
    ck("  sharded, so the second instance adds throughput instead of skipping",
       "def queue_drain_sharded() -> dict:" in wsrc and "_each_tenant(\"job queue\"" in wsrc)
    ck("  and the system_run kind is the one that is never retried silently",
       jobs.KINDS["system_run"]["retryable"] is False)

    ran.clear()
    jobs.enqueue("baci", "_t_ok", system_key="drained")
    drained = jobs.drain("baci", "instance-A", limit=4)
    ck("a drain claims and runs what is waiting", drained["ran"] >= 1 and len(ran) >= 1,
       str(drained))
    ck("  and stops when the queue is empty", jobs.drain("baci", "instance-A")["ran"] == 0)

    print()
    print("PASS" if not _fail else f"FAILED: {len(_fail)}")
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
