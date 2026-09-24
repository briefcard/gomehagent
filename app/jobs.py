"""The work queue: a run that outlives the process that asked for it.

WHY THIS EXISTS. A long run used to be a daemon thread inside the WEB
service (`web._run_bg`). That much survived a page refresh — the thread is
detached from the request — but it did not survive a deploy, and
`web._sweep_interrupted` exists to clean up after exactly that: the owner
pressed a button, the card said "running", a deploy restarted the service,
and the card went on saying "running" for a run that had stopped
(2026-09-08, five minutes into a run whose card promised two).

Three things were wrong and only one of them was the thread:

  1. NOTHING RECORDED WHAT TO RUN. `_run_bg` wrote what had HAPPENED into
     `Setting["bg:{label}:{tenant}"]`. With no record of the work itself,
     nothing could pick it back up — the only recovery was a person
     pressing the button again, and only if they noticed.
  2. THE STATUS STORE HELD ONE ROW PER (label, tenant). A second run of the
     same thing overwrote the first, so there was no history and no way to
     tell two runs apart.
  3. THE HEAVY WORK RAN ON THE WEB DYNO, competing with request serving for
     a `starter` plan's memory while making model calls and taking browser
     screenshots.

So: the press ENQUEUES, the worker service claims and runs, and the row is
the status. `db.JobQueue.run_id` joins the job to the `SystemRun` it
produced, so "is it running" and "what did it decide" are one answer.

WHAT A DEPLOY COSTS IS DECLARED, NEVER GUESSED. Each kind in `KINDS` says
whether it may be picked up again. The default is False and the burden is on
the kind to argue otherwise: a job that only READS may be retried freely, but
one that spends a model call or files an approval is reported as
`interrupted` and waits for a person. Repeating that quietly is how one
approval becomes two, which is the failure this system's whole approval
gate exists to prevent.
"""
from __future__ import annotations

import datetime as dt
import logging
import threading

from sqlalchemy import update

from . import db

log = logging.getLogger("jobs")

#: How often a running job says it is still alive. A job blocked in a model
#: call cannot tick by itself, so the runner beats for it on a thread.
HEARTBEAT_SECONDS = 30

#: No heartbeat for this long and the holder is gone — a deploy, an OOM, a
#: dyno recycled. Generous next to HEARTBEAT_SECONDS so a slow machine is
#: never mistaken for a dead one; short enough that a deploy is noticed
#: while the owner is still looking at the screen.
STALE_AFTER_SECONDS = 5 * 60

#: How long a claim is held before a sibling may reclaim the row. The
#: heartbeat extends it, so this is the grace period after the last beat.
LEASE_SECONDS = STALE_AFTER_SECONDS

TERMINAL = ("done", "failed", "interrupted", "cancelled")

#: THE REGISTRY. A kind names what to call and what a deploy costs.
#:
#: `target` is "module:function", resolved at run time so this module imports
#: nothing heavy and cannot make a cycle. The function is called as
#: `fn(tenant=..., **payload)`, and a function that takes `progress` is handed
#: a writer whose text lands on the card.
KINDS: dict[str, dict] = {
    "system_run": {
        "what": "a system's own check",
        "target": "app.skill:run",
        # NOT RETRYABLE, deliberately. `skill.run` drafts, calls the model
        # and can file an approval. Re-running it from the top after a deploy
        # would spend the call again and could queue a SECOND approval for
        # the same thing — and an owner approving both sends twice. The run
        # is reported as interrupted with its own re-run control instead, so
        # repeating it is a decision somebody made.
        "retryable": False,
    },
    "hosting": {
        "what": "the hand-off of approved pictures to the client's site",
        "target": "app.hosting:publish_all",
        # RETRYABLE, and checked rather than assumed. `publish_all` skips any
        # picture already hosted (`if (row.hosted or {}).get("url") ...
        # continue`), so a second run resumes where a stopped one left off
        # instead of repeating it. That matters more here than anywhere else
        # in the registry: the loop moves pictures one at a time, and an
        # interrupted sweep leaves the rest still ours with nothing saying
        # how far it got.
        "retryable": True,
    },
    "layers": {
        "what": "each kept frame's Meta placements, layered in Canva",
        "target": "app.hosting:layer_kept",
        # RETRYABLE for the same checked reason: `layer_placements` goes
        # through `to_canva`, which "opens the design it has rather than
        # making a second" for a frame already in Canva for that placement.
        # A re-run fills the gaps and duplicates nothing.
        "retryable": True,
    },
    # ── THE HEAVY CREATIVE WORK (2026-09-23) ────────────────────────────────
    # These four ran as daemon threads inside the WEB service until the
    # owner's instance was restarted under them mid-session. Measured on the
    # laptop: the web process is 131 MB at import before a request, one
    # `recreate._stamp` of a full-page email screenshot peaks at +38 MB, and
    # the cast stage was allowed to hold 24 pictures' bytes at once. Render
    # gives the service 512 MB and expects it to answer requests with them.
    # Nothing about the work changed — only which process does it.
    "email_recreate": {
        "what": "a reference read, recreated for this brand, and judged",
        "target": "app.recreate:job",
        # NOT RETRYABLE. Five to seven model calls and a browser; repeating
        # it after a deploy spends that again for a picture nobody asked for
        # twice. The card says it was interrupted and carries its own
        # re-run control, which is the same answer `system_run` gives.
        "retryable": False,
    },
    "ad_frames": {
        "what": "a set of ad frames, drawn and judged against the product",
        "target": "app.creative:frames_job",
        # WHOSE SIGNATURE THE PAYLOAD MUST SATISFY. `frames_job` chooses one
        # model or several and forwards the rest, so a payload key it does
        # not name still has to be one `batch` accepts — this is the
        # declaration `test_the_route_sends_what_the_callee_takes` checks,
        # and it is the reason `situation` reaching the generator is still
        # guarded now that the press goes through a queue.
        "takes": "app.creative:batch",
        # NOT RETRYABLE, same argument and a larger bill: a set is up to
        # sixteen pictures from a paid image model.
        "retryable": False,
    },
    "boards": {
        "what": "a visual board filled from Pinterest, or read into direction",
        "target": "app.creative:board_job",
        # RETRYABLE, and checked: `fill_board` files a pin by its source URL
        # and skips one already on the board, and `read_board_direction`
        # overwrites the board's direction rather than appending to it. A
        # second run fills the gaps and duplicates nothing.
        "retryable": True,
    },
    "sync": {
        "what": "this brand's catalogue and every store picture, re-read",
        "target": "app.catalog_sync:sync_shopify",
        # RETRYABLE: the sync upserts by the store's own ids, so running it
        # again lands on the same rows.
        "retryable": True,
    },
    # ── EVERYTHING ELSE THE CONSOLE STARTS (2026-09-23) ─────────────────────
    # These ran as threads in the web process, or inline in the request, and
    # the same function could be started three ways with two status stores.
    # One door now: a press queues its kind; nothing runs in a request.
    "voice": {"what": "the brand's voice, read off its site into a proposal",
              "target": "app.voice:derive",
              # re-running overwrites the proposal it wrote; nothing is sent
              "retryable": True},
    "email": {"what": "claims and objections mined from sent mail",
              "target": "app.email_harvest:mine",
              # files proposals; a second pass could file a second copy
              "retryable": False},
    "harvest": {"what": "the brand's own pages read for claims",
                "target": "app.harvest:harvest", "retryable": False},
    "scan": {"what": "the live site checked against the brand's banned claims",
             "target": "app.compliance:scan_and_record",
             # a read and a record; running it twice records the same scan
             "retryable": True},
    "answer_engines": {"what": "whether the answer engines can read the site",
                       "target": "app.answer_engines:check", "retryable": True},
    "verify": {"what": "every connection this account has, live-tested",
               "target": "app.tenants:verify_and_store", "retryable": True},
    "canva_harvest": {"what": "a design pulled from Canva into the library",
                      "target": "app.canva:harvest", "retryable": False},
    "drive_photos": {"what": "photographs pulled from a Drive folder",
                     "target": "app.creative:harvest_drive", "retryable": False},
    "keywords_harvest": {"what": "keywords gathered from Search Console and Semrush",
                         # Semrush is billed per line; never repeat it unasked
                         "target": "app.keywords:harvest", "retryable": False},
    "offers_harvest": {"what": "offers mined from sent mail",
                       "target": "app.offers:harvest", "retryable": False},
}


#: QUEUED AND RUNNING ARE BOTH "IT IS HAPPENING" to whoever pressed the
#: button — the difference between them is up to twenty seconds of a worker's
#: tick, and a room that treated a queued job as finished would say a run
#: "ran" before it started. The sentence in `says` keeps the two apart for
#: anyone who wants the detail.
IN_FLIGHT = ("queued", "running")


def kind(name: str) -> dict:
    return KINDS.get(name) or {}


def retryable(name: str) -> bool:
    """Whether a kind may be picked up again after its process died.

    Unknown kinds are NOT retryable: the safe direction for a question this
    module cannot answer is to wait for a person.
    """
    return bool(kind(name).get("retryable"))


def _resolve(target: str):
    import importlib
    mod, _, fn = str(target or "").partition(":")
    if not mod or not fn:
        raise ValueError(f"a kind's target must be 'module:function', got {target!r}")
    return getattr(importlib.import_module(mod), fn)


# ---------------------------------------------------------------------------
# Enqueue
# ---------------------------------------------------------------------------

def enqueue(tenant: str, kind_: str, *, payload: dict | None = None,
            system_key: str = "", label: str = "", dedupe: bool = True) -> dict:
    """Put work on the queue. `{ok, id, why, already}`.

    `dedupe` refuses a second identical job while one is still outstanding.
    A double-pressed button is the common case and, for a kind that is not
    retryable, the expensive one: two runs, two model calls, two approvals
    for one intent. The existing job is returned rather than an error,
    because "it is already running" is the answer the presser wanted.
    """
    if not tenant:
        return {"ok": False, "why": "a job belongs to an account", "id": ""}
    if kind_ not in KINDS:
        return {"ok": False, "why": f"no such kind of job: {kind_}", "id": ""}
    with db.SessionLocal() as s:
        if dedupe:
            open_ = (s.query(db.JobQueue)
                     .filter(db.JobQueue.tenant == tenant,
                             db.JobQueue.kind == kind_,
                             db.JobQueue.system_key == (system_key or ""),
                             db.JobQueue.state.in_(("queued", "running")))
                     .order_by(db.JobQueue.created_at.desc()).first())
            if open_ is not None:
                return {"ok": True, "id": open_.id, "already": True,
                        "why": ("it is already running" if open_.state == "running"
                                else "it is already queued")}
        row = db.JobQueue(tenant=tenant, kind=kind_, system_key=system_key or "",
                          label=label or KINDS[kind_].get("what", kind_),
                          payload=dict(payload or {}), state="queued")
        s.add(row)
        s.commit()
        return {"ok": True, "id": row.id, "already": False, "why": ""}


# ---------------------------------------------------------------------------
# Claim, beat, finish — the worker's side
# ---------------------------------------------------------------------------

def claim(tenant: str, holder: str) -> str:
    """Take the oldest queued job for one account, or "" — ONE statement decides.

    The row is selected and then claimed by an UPDATE whose WHERE clause
    still says `queued`, so two workers issuing it in the same instant get
    rowcounts 1 and 0 from the database. The loser takes the next row rather
    than the same one, which is the whole correctness argument — nothing
    here reads-then-writes and trusts what it read.
    """
    now = db.utcnow()
    with db.SessionLocal() as s:
        row = (s.query(db.JobQueue)
               .filter(db.JobQueue.tenant == tenant, db.JobQueue.state == "queued")
               .order_by(db.JobQueue.created_at.asc()).first())
        if row is None:
            return ""
        got = s.execute(
            update(db.JobQueue)
            .where(db.JobQueue.id == row.id, db.JobQueue.state == "queued")
            .values(state="running", holder=holder, started_at=now,
                    heartbeat_at=now,
                    leased_until=now + dt.timedelta(seconds=LEASE_SECONDS),
                    attempts=db.JobQueue.attempts + 1, detail=""))
        s.commit()
        return row.id if got.rowcount == 1 else ""


def heartbeat(job_id: str, detail: str | None = None) -> None:
    """Still alive, and optionally what it is doing now."""
    now = db.utcnow()
    values = {"heartbeat_at": now,
              "leased_until": now + dt.timedelta(seconds=LEASE_SECONDS)}
    if detail is not None:
        values["detail"] = str(detail)[:1500]
    with db.SessionLocal() as s:
        s.execute(update(db.JobQueue)
                  .where(db.JobQueue.id == job_id, db.JobQueue.state == "running")
                  .values(**values))
        s.commit()


def finish(job_id: str, state: str, detail: str = "", run_id: str = "") -> None:
    with db.SessionLocal() as s:
        row = s.get(db.JobQueue, job_id)
        if row is None:
            return
        row.state = state
        row.detail = str(detail)[:1500]
        row.finished_at = db.utcnow()
        row.leased_until = None
        if run_id:
            row.run_id = run_id
        s.commit()


def reclaim() -> dict:
    """Deal with jobs whose holder went away. `{retried, interrupted}`.

    This is the half `web._sweep_interrupted` could not do. That one runs at
    boot in the web service and can only mark a status row failed — it has
    no record of the work, so nothing can resume. Here the work IS the row:
    a kind declared retryable goes back on the queue, and one that is not
    stops as `interrupted` and says so, which is a different sentence from
    "failed" and leads to a different action.
    """
    cut = db.utcnow() - dt.timedelta(seconds=STALE_AFTER_SECONDS)
    out = {"retried": 0, "interrupted": 0}
    with db.SessionLocal() as s:
        stale = (s.query(db.JobQueue)
                 .filter(db.JobQueue.state == "running",
                         db.JobQueue.heartbeat_at < cut).all())
        for row in stale:
            was = row.holder or "a worker"
            if retryable(row.kind):
                row.state = "queued"
                row.holder = ""
                row.leased_until = None
                row.detail = (f"{was} stopped before it finished (a deploy does "
                              f"that) — queued again, attempt {int(row.attempts or 0) + 1}")
                out["retried"] += 1
            else:
                row.state = "interrupted"
                row.finished_at = db.utcnow()
                row.leased_until = None
                row.detail = (
                    f"{was} stopped while this was running — a deploy does that. "
                    "It was not started again on its own, because this job can "
                    "spend a model call and file an approval, and doing that "
                    "twice for one press is worse than waiting. Press it again "
                    "when you want it."
                    + (f" Last progress: {row.detail}" if row.detail else ""))
                out["interrupted"] += 1
        if stale:
            s.commit()
    return out


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

def summarise(result) -> str:
    """The two or three numbers that say whether a run was worth anything.

    AND WHICH SOURCE CAME BACK EMPTY. A run over several sites reported one
    set of totals, so a landing page that enumerated nothing was invisible
    behind a website that enumerated plenty: the line read "proposed_count 12
    · pages_read 40" and the owner had no way to learn the landing page they
    had just added contributed zero. The per-source report existed in the
    return value the whole time and no surface rendered it, which is the
    same shape as a KB rule that never reaches a validator. Absence is not an
    answer (design rule 12): a source that read nothing has to say so where
    the run is reported.
    """
    if not isinstance(result, dict):
        return ""
    if result.get("error"):
        return f"error: {result['error']}"
    keep = ("proposed_count", "pages_read", "pages_unchanged", "pages_remaining",
            "faqs_filed_as_objections", "claims_count", "objections_count",
            "threads_seen", "added", "updated", "violations", "extractor",
            "made", "clean")
    bits = [f"{k} {result[k]}" for k in keep if result.get(k) not in (None, "")]
    empty = [r.get("label") or r.get("url", "")
             for r in (result.get("sources") or [])
             if isinstance(r, dict) and not r.get("pages_found")]
    if empty:
        bits.append("READ NOTHING: " + ", ".join(str(e) for e in empty[:4]))
    lost = _losses(result)
    if lost:
        bits.append("LOST: " + " · ".join(lost))
    # a keyword harvest's phrases that nothing else contained, each made a
    # pillar of its own — "we found a theme" and "we found six unrelated
    # phrases and called each one a theme" are different results
    lone = int(result.get("orphan_pillars") or 0)
    if lone:
        bits.append(f"{lone} phrase{'' if lone == 1 else 's'} stood alone and became "
                    f"{'its own pillar' if lone == 1 else 'their own pillars'}")
    # A set's own `note` is where it says what it was drawn from and what
    # was kept out of the request; a strip that only counted frames would
    # show a board of reference pins as a board that is working.
    note = result.get("extractor_note") or (
        result.get("note") if isinstance(result.get("note"), str) else "") or ""
    out = " · ".join(bits) + (f" — {note[:300]}" if note else "")
    # THE FAILURES A RUN COLLECTED, when its own note did not carry them. A
    # frames run kept every cell's refusal in `errors` and the strip showed
    # "made 0" with no reason (owner, 2026-09-08). Said once: a note that
    # already names the first failure is not repeated.
    errs = ([str(e) for e in result.get("errors") if str(e).strip()]
            if isinstance(result.get("errors"), (list, tuple)) else [])
    if errs and errs[0].split(": ", 1)[-1][:60] not in note:
        out += f" — {len(errs)} error(s): {errs[0][:200]}"
    return out


#: What a run REFUSED, SKIPPED or DROPPED, by the key each producer already
#: writes it under. `label` is what a person needs to read; `plural` decides
#: the wording; a value of 0 or an empty container is never mentioned, because
#: a clean run must stay quiet or the loud ones stop being read.
_LOSS_KEYS = (
    ("write_refused_count", "write{s} refused"),
    ("rejected_for_banned_claim", "rejected for a banned claim"),
    ("not_verbatim_count", "rejected as not verbatim"),
    ("pages_skipped", "page{s} skipped"),
    ("pages_skipped_unchanged", "page{s} unchanged since last scan"),
    ("truncated_page_count", "page{s} too long to read whole"),
    ("drafts_skipped", "draft product{s} skipped"),
    ("skipped_small", "image{s} too small to use"),
    ("dropped_for_banned_claims", "sentence{s} dropped for a banned claim"),
)


def _losses(result: dict) -> list[str]:
    """The other half of what a run did.

    Every one of these numbers was already computed and NONE of them reached a
    surface — `_summarise` kept the gains and dropped the losses, so a harvest
    that proposed twelve claims and REFUSED TO WRITE FIVE reported "12" and
    nothing else. `harvest`'s own source says why that matters: "What the
    writes actually did, as opposed to what was proposed. These are different
    numbers and conflating them hid a whole class of loss." It hid it here.

    Found 2026-08-28 by the sweep the owner asked for — how many UI units have
    no piping — which found 30 warning-shaped facts computed and rendered
    nowhere. This closes the seventeen of them that are run losses.

    `dropped_by_reason` and `skipped_by_reason` are dicts of reason → count, so
    the WHY leads: "3 no proof, 1 too long" beats "4 dropped" at exactly the
    moment somebody is deciding whether to care.
    """
    out: list[str] = []
    for key, label in _LOSS_KEYS:
        v = result.get(key)
        n = len(v) if isinstance(v, (list, tuple, dict)) else (v or 0)
        try:
            n = int(n)
        except (TypeError, ValueError):
            continue
        if n > 0:
            out.append(f"{n} " + label.format(s="" if n == 1 else "s"))
    for key in ("dropped_by_reason", "skipped_by_reason"):
        why = result.get(key)
        if isinstance(why, dict) and why:
            top = sorted(why.items(), key=lambda kv: -int(kv[1] or 0))[:3]
            out.append(", ".join(f"{v} {k}" for k, v in top))
    # ONE EXAMPLE OF EACH LOSS. "5 writes refused" tells you to care; it does
    # not tell you what to look at, and the producers already carry the list —
    # `write_refused`, `skipped_examples`, `truncated_pages`,
    # `drafts_skipped_examples` were all computed and all unreachable. A count
    # whose instance you cannot see is a number you can only worry about.
    for key in ("write_refused", "skipped_examples", "truncated_pages",
                "drafts_skipped_examples"):
        rows = result.get(key)
        if isinstance(rows, (list, tuple)) and rows:
            first = rows[0]
            if isinstance(first, dict):
                # WHAT it was, then WHY — in that order. `why` alone repeats
                # the aggregate above ("2 banned phrase") and names no
                # instance, which is the half a person needs to go and look.
                what = (first.get("claim") or first.get("text")
                        or first.get("url") or next(iter(first.values()), ""))
                why = first.get("why") or ""
                first = f"{what}{f' ({why})' if why else ''}"
            out.append(f"e.g. {str(first)[:110]}")
            break
    return out


def _summary(result) -> str:
    """The few facts that say whether a run was worth anything.

    A run that correctly produced nothing and a button that did nothing are
    different facts and must not look alike — the same rule `web._summarise`
    was written for, applied to what a skill run returns.
    """
    if not isinstance(result, dict):
        return ""
    if result.get("status") == "blocked" or result.get("blocked_on"):
        named = ", ".join(str(b) for b in (result.get("blocked_on") or [])[:3])
        return f"blocked — {named}" if named else "blocked"
    bits = []
    items = result.get("items")
    if isinstance(items, list):
        bits.append(f"{len(items)} produced")
        # the run's result lands where a person decides it; the queue row is
        # where they will look first now that the press no longer waits
        if any(isinstance(i, dict) and i.get("disposition") == "needs_approval"
               for i in items):
            bits.append("waiting on you")
    for k in ("status", "approval_id"):
        if result.get(k):
            bits.append(f"{k} {result[k]}")
    notes = result.get("notes")
    if isinstance(notes, list) and notes:
        bits.append(str(notes[0])[:200])
    # A CREATIVE RUN IS NOT A SKILL RUN. It reports what it drew, what it
    # kept out and which cell the API refused — and none of that is in the
    # keys above. `summarise` is the reader written for it, and using it here
    # is what stopped "a run that made nothing says why" from becoming
    # "finished, nothing produced" when the work moved to the worker.
    rich = summarise(result)
    if rich:
        bits.append(rich)
    return " · ".join(bits) or "finished, nothing produced"


def run_one(job_id: str) -> dict:
    """Run one claimed job to its end. `{ok, state, detail}`.

    The heartbeat runs on its own thread because the work does not: a job
    blocked in a model call for four minutes cannot tick for itself, and
    without the beat `reclaim` would take a perfectly healthy run away from
    it.
    """
    with db.SessionLocal() as s:
        row = s.get(db.JobQueue, job_id)
        if row is None or row.state != "running":
            return {"ok": False, "state": "", "detail": "no such running job"}
        kind_, tenant, payload = row.kind, row.tenant, dict(row.payload or {})
    spec = kind(kind_)
    if not spec:
        finish(job_id, "failed", f"no such kind of job: {kind_}")
        return {"ok": False, "state": "failed", "detail": f"unknown kind {kind_}"}
    # WHAT THE WORKER IS DOING, IN ITS LOG. A ten-minute campaign email ran
    # with nothing in the log but anonymous HTTP lines (owner, 2026-09-23:
    # "in the worker I'm not seeing the run").
    import time as _time
    t0 = _time.monotonic()
    log.info("job %s: %s for %s — started", job_id[:8], kind_, tenant)

    stop = threading.Event()

    def _beat() -> None:
        while not stop.wait(HEARTBEAT_SECONDS):
            try:
                heartbeat(job_id)
            except Exception:                                    # noqa: BLE001
                log.exception("heartbeat failed for %s", job_id)

    beat = threading.Thread(target=_beat, daemon=True)
    beat.start()
    try:
        fn = _resolve(spec["target"])
        import inspect
        try:
            takes = "progress" in inspect.signature(fn).parameters
        except (TypeError, ValueError):
            takes = False
        if takes and "progress" not in payload:
            payload["progress"] = lambda text: heartbeat(job_id, str(text or "")[:600])
        result = fn(tenant=tenant, **payload)
    except Exception as exc:                                     # noqa: BLE001
        log.exception("job %s: %s for %s — failed after %ds", job_id[:8], kind_,
                      tenant, _time.monotonic() - t0)
        finish(job_id, "failed", f"{exc.__class__.__name__}: {exc}")
        return {"ok": False, "state": "failed", "detail": str(exc)[:300]}
    finally:
        stop.set()
    run_id = str((result or {}).get("run_id") or "") if isinstance(result, dict) else ""
    # A RUN THAT MADE NOTHING IS NOT DONE. `skill.run` catches its own errors
    # and returns `status: failed` (or refused/blocked at a gate) rather than
    # raising, so a campaign email that could not be made landed here as
    # "ran" with the failure buried in the detail.
    status = str((result or {}).get("status") or "") if isinstance(result, dict) else ""
    state = "failed" if status in ("failed", "refused", "blocked") else "done"
    finish(job_id, state, _summary(result), run_id=run_id)
    log.info("job %s: %s for %s — %s after %ds: %s", job_id[:8], kind_, tenant,
             state, _time.monotonic() - t0, _summary(result)[:200])
    return {"ok": state == "done", "state": state, "detail": _summary(result)}


def drain(tenant: str, holder: str, limit: int = 4) -> dict:
    """Claim and run this account's queued jobs. `{ran, ids}`.

    Bounded per tick so one account with a long queue cannot hold a worker
    away from the accounts after it in the shard.
    """
    ran, ids = 0, []
    for _ in range(max(1, limit)):
        job_id = claim(tenant, holder)
        if not job_id:
            break
        ids.append(job_id)
        run_one(job_id)
        ran += 1
    return {"ran": ran, "ids": ids}


# ---------------------------------------------------------------------------
# Read — what the console shows
# ---------------------------------------------------------------------------

def latest(tenant: str, *, system_key: str = "", kind_: str = "") -> dict:
    """The most recent job for one account, optionally one system. {} if none."""
    with db.SessionLocal() as s:
        q = s.query(db.JobQueue).filter(db.JobQueue.tenant == tenant)
        if system_key:
            q = q.filter(db.JobQueue.system_key == system_key)
        if kind_:
            q = q.filter(db.JobQueue.kind == kind_)
        row = q.order_by(db.JobQueue.created_at.desc()).first()
        return as_dict(row) if row is not None else {}


def as_dict(row) -> dict:
    """One job as the console reads it — including the SENTENCE for its state.

    The words live here rather than in the template because the same job is
    reported in more than one room, and a state that reads differently
    depending on where you saw it is the two-stores problem this queue was
    built to remove.
    """
    if row is None:
        return {}
    state = str(row.state or "")
    at = row.finished_at or row.started_at or row.created_at
    says = {
        "queued": "queued — a worker will pick this up shortly",
        "running": "running now",
        "done": "ran",
        "failed": "ran and failed",
        "interrupted": "stopped by a restart, and not started again on its own",
        "cancelled": "taken off the queue before a worker reached it",
    }.get(state, state)
    return {"id": row.id, "tenant": row.tenant, "kind": row.kind,
            "system_key": row.system_key or "", "label": row.label or "",
            "state": state, "says": says, "detail": str(row.detail or ""),
            "attempts": int(row.attempts or 0), "run_id": row.run_id or "",
            "at": db.as_utc(at).isoformat() if at else "",
            "finished": state in TERMINAL,
            "retryable": retryable(row.kind)}


def status(tenant: str, kind_: str) -> dict:
    """The latest job of one kind — THE status reader. Every card, strip and
    banner that says whether something is running asks this; there is no
    second store to fall back to since `web.bg_status` and its `Setting` rows
    were deleted on 2026-09-23.

    Its shape is the one the rooms were written against, ON PURPOSE. The picture and brand rooms render background state
    off `admin_ui.BG_*_LABELS` with wording tuned over several rounds — the
    honest estimate of how long a frame takes, the progress line, the reason
    a refusal gave in the API's own words. Migrating a label to the queue
    should not cost that, so the queue answers in the shape the renderer
    already reads and the labels stay the vocabulary. A label not yet
    migrated has no kind here and keeps falling through to `bg_status`.
    """
    got = latest(tenant, kind_=kind_)
    if not got:
        return {}
    return {"state": got["state"], "detail": got["detail"], "at": got["at"],
            "says": got["says"], "attempts": got["attempts"]}


def board(tenant: str, *, done: int = 12) -> dict:
    """WHAT THIS ACCOUNT HAS IN THE AIR, for the pill in the frame and the
    queue room it clicks into.

    `{running: [...], queued: [...], done: [...], n_flight, says}` — the
    in-flight rows carry a POSITION and a `waited`/`ran_for` in seconds,
    because "queued" with nothing else said is the same silence the queue was
    built to remove: three of them behind a twelve-minute recreation is a
    different fact from one that is about to start.
    """
    now = db.utcnow()

    def _secs(then) -> int:
        return int((now - db.as_utc(then)).total_seconds()) if then else 0

    with db.SessionLocal() as s:
        rows = (s.query(db.JobQueue).filter(db.JobQueue.tenant == tenant)
                .order_by(db.JobQueue.created_at.asc()).all())
        running, queued, fin = [], [], []
        for r in rows:
            got = as_dict(r)
            if r.state == "running":
                got["ran_for"] = _secs(r.started_at)
                running.append(got)
            elif r.state == "queued":
                got["waited"] = _secs(r.created_at)
                got["position"] = len(queued) + 1
                queued.append(got)
            else:
                got["ran_for"] = (int((db.as_utc(r.finished_at)
                                       - db.as_utc(r.started_at)).total_seconds())
                                  if r.finished_at and r.started_at else 0)
                fin.append(got)
        fin.reverse()
        fin = fin[:max(0, done)]
    n = len(running) + len(queued)
    if not n:
        says = ""
    else:
        first = (running or queued)[0]
        says = first.get("detail") or first.get("label") or first["kind"]
        if n > 1:
            says += f" · {n - 1} more waiting"
    return {"running": running, "queued": queued, "done": fin,
            "n_flight": n, "says": says}


def cancel(job_id: str) -> str:
    """Take a QUEUED job off the queue. "" when it went, else why not.

    A running job is not cancellable and says so rather than pretending: the
    worker is inside a model call, and a row marked cancelled under it would
    be a second store disagreeing with the process — which is the whole thing
    this table exists to stop.
    """
    with db.SessionLocal() as s:
        row = s.get(db.JobQueue, job_id)
        if row is None:
            return "no such job"
        if row.state != "queued":
            return ("it is already running — a worker is inside it, and it "
                    "finishes or a restart interrupts it"
                    if row.state == "running" else f"it is {row.state}, not queued")
        row.state, row.detail = "cancelled", "taken off the queue by hand"
        row.finished_at = db.utcnow()
        s.commit()
        return ""


def again(job_id: str) -> dict:
    """Queue the same work again — the control a job that was interrupted or
    failed carries. A NEW row, because the old one is what happened and the
    history the one-row store never kept is the point."""
    with db.SessionLocal() as s:
        row = s.get(db.JobQueue, job_id)
        if row is None:
            return {"ok": False, "why": "no such job", "id": ""}
        kind_, tenant, payload = row.kind, row.tenant, dict(row.payload or {})
        system_key, label = row.system_key or "", row.label or ""
    return enqueue(tenant, kind_, payload=payload, system_key=system_key,
                   label=label, dedupe=True)


def recent(tenant: str = "", limit: int = 20) -> list[dict]:
    """The last jobs, newest first — the history the one-row store never kept."""
    with db.SessionLocal() as s:
        q = s.query(db.JobQueue)
        if tenant:
            q = q.filter(db.JobQueue.tenant == tenant)
        rows = q.order_by(db.JobQueue.created_at.desc()).limit(max(1, limit)).all()
        return [as_dict(r) for r in rows]
