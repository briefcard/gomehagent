"""A second worker instance runs each job once, not twice.

Every job in `worker.py` is a cron in an in-process scheduler. A second
instance of the worker service — the obvious way to run operations in parallel
— fires every cron on both: two harvests, two campaign sends, two Semrush
bills. The lease in `_safe` is the only thing that stops it, so this proves
the lease decides the race, releases on both success and failure, and covers
EVERY registration rather than the ones somebody remembered.

Counted, not timed. Two holders race for one name; the property is "how many
ran", which is exact.

Run: python3 scripts/test_job_lease.py
"""
import datetime as dt
import os
import re
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'jl.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, worker  # noqa: E402

_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _as(holder: str):
    """Pretend to be a different instance for one call."""
    real = worker._holder
    worker._holder = lambda: holder
    return real


def main() -> int:
    db.init_db()
    ran = {"n": 0}

    def job():
        ran["n"] += 1

    a = worker._safe(job, "test job")
    b = worker._safe(job, "test job")

    # ---- two instances, one tick, one run ----------------------------------
    real = _as("instance-A")
    a_won = worker._acquire("test job", 600)
    worker._holder = lambda: "instance-B"
    b_won = worker._acquire("test job", 600)
    ck("of two instances waking together, exactly one takes the lease",
       [a_won, b_won] == [True, False],
       f"A={a_won} B={b_won} — both True is the doubled bill this exists to stop")
    with db.SessionLocal() as s:
        row = s.get(db.JobLease, "test job")
    ck("  and the loser is counted as a skip, not lost",
       row is not None and row.runs == 1 and row.skips == 1,
       f"runs={getattr(row, 'runs', None)} skips={getattr(row, 'skips', None)}")
    # Release AS the holder. `_release` refuses to free a lease somebody else
    # holds — which is correct, and is exactly why the first cut of this test
    # failed: it released as the real process and the lease stayed live.
    worker._holder = lambda: "instance-A"
    worker._release("test job")
    worker._holder = real

    # ---- through the wrapper: the job body runs once across both ---------
    ran["n"] = 0
    real = _as("instance-A")
    a()                                   # acquires, runs, releases
    worker._holder = lambda: "instance-B"
    # Re-take A's lease as if A were still mid-run, then B ticks.
    worker._holder = lambda: "instance-A"
    worker._acquire("test job", 600)
    worker._holder = lambda: "instance-B"
    b()                                   # must skip
    worker._holder = real
    ck("a job whose lease another instance holds does not run",
       ran["n"] == 1, f"{ran['n']} run(s) across two instances — 2 is the bug")
    worker._release("test job")
    with db.SessionLocal() as s:
        row = s.get(db.JobLease, "test job")
        s.execute(db.JobLease.__table__.update()
                  .where(db.JobLease.name == "test job")
                  .values(holder="instance-A", leased_until=None))
        s.commit()

    # ---- release on failure --------------------------------------------
    def boom():
        raise RuntimeError("job died")

    worker.alert_error = lambda *a, **k: None       # no Telegram from a test
    worker._safe(boom, "test job")()
    with db.SessionLocal() as s:
        row = s.get(db.JobLease, "test job")
    ck("a job that raises still releases its lease",
       row.leased_until is None,
       "otherwise one crash parks the job for the whole TTL on every instance")

    # ---- expiry is the release nobody has to remember ------------------
    with db.SessionLocal() as s:
        s.execute(db.JobLease.__table__.update()
                  .where(db.JobLease.name == "test job")
                  .values(holder="dead-instance",
                          leased_until=db.utcnow() - dt.timedelta(seconds=1)))
        s.commit()
    ck("an expired lease held by a dead instance can be taken",
       worker._acquire("test job", 600) is True,
       "a crashed worker must not hold a job hostage past the TTL")
    worker._release("test job")

    # ---- a live lease cannot be taken --------------------------------------
    worker._acquire("test job", 600)
    real = _as("instance-C")
    taken = worker._acquire("test job", 600)
    worker._holder = real
    ck("a live lease cannot be taken",
       taken is False, "the pair with the check above: expired opens, live holds")
    worker._release("test job")

    # ---- every registration goes through the wrapper -----------------------
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "app", "worker.py")).read()
    adds = len(re.findall(r"sched\.add_job\(", src))
    safe = len(re.findall(r"sched\.add_job\(\s*_safe\(", src))
    ck("every scheduled job is registered through the leased wrapper",
       adds > 20 and adds == safe,
       f"{safe} of {adds} — one registered around `_safe` is the one that "
       f"runs twice")

    # ---- a per-tenant lease is a different name ----------------------------
    ck("a tenant-sharded job leases per tenant",
       worker._lease_name("keyword sync", "baci") != worker._lease_name("keyword sync", "eien")
       and worker._lease_name("keyword sync") == "keyword sync",
       "so two instances can work two accounts of the same job at once")

    print()
    print("PASS" if not _fail else f"FAILED: {len(_fail)}")
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
