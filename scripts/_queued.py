"""WHAT A PRESS SCHEDULED, now that a press queues instead of threading.

Several suites spied on `web._run_bg` to learn what a button had started:
the label, the function, and the arguments it was given. On 2026-09-23 the
heavy creative work moved off the web service onto the job queue, so a press
writes a row and a worker runs it in another process — and every one of
those spies went quiet, reporting an empty list rather than a changed shape.

These two keep those suites saying exactly what they said before:

    spy(jobs)      records each job a press queues; nothing runs.
    run_now(jobs)  runs the kind's real target in the test's own process,
                   so both sides of the seam still execute — the rule
                   `test_the_route_sends_what_the_callee_takes` exists for.

A stub that quietly accepted anything would be worse than no suite at all,
so both refuse an unknown kind exactly as `jobs.enqueue` does.
"""
from __future__ import annotations

import contextlib


def _refuse(jobs, kind_: str) -> dict | None:
    if kind_ not in jobs.KINDS:
        return {"ok": False, "why": f"no such kind of job: {kind_}", "id": ""}
    return None


@contextlib.contextmanager
def spy(jobs):
    """Yields a list of `{tenant, kind, payload, system_key}`, newest last."""
    seen: list[dict] = []
    real = jobs.enqueue

    def fake(tenant, kind_, *, payload=None, system_key="", label="", dedupe=True):
        no = _refuse(jobs, kind_)
        if no:
            return no
        seen.append({"tenant": tenant, "kind": kind_, "payload": dict(payload or {}),
                     "system_key": system_key})
        return {"ok": True, "id": f"queued-{len(seen)}", "already": False, "why": ""}

    jobs.enqueue = fake
    try:
        yield seen
    finally:
        jobs.enqueue = real


@contextlib.contextmanager
def run_now(jobs):
    """Like `spy`, but each queued job's target RUNS before the press
    returns. Each record gains `result`."""
    seen: list[dict] = []
    real = jobs.enqueue

    def fake(tenant, kind_, *, payload=None, system_key="", label="", dedupe=True):
        no = _refuse(jobs, kind_)
        if no:
            return no
        row = {"tenant": tenant, "kind": kind_, "payload": dict(payload or {}),
               "system_key": system_key}
        seen.append(row)
        fn = jobs._resolve(jobs.KINDS[kind_]["target"])
        row["result"] = fn(tenant=tenant, **row["payload"])
        return {"ok": True, "id": f"ran-{len(seen)}", "already": False, "why": ""}

    jobs.enqueue = fake
    try:
        yield seen
    finally:
        jobs.enqueue = real
