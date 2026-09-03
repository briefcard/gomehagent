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

    # ======================================================================
    # SHARDING: two instances split the accounts, every account worked once
    # ======================================================================
    from app import keywords, media, performance, tenants
    tenants.seed()
    keys = [x.key for x in tenants.all_tenants()]
    ck("there are accounts to split", len(keys) >= 2, str(keys))
    worked = []
    # Instance A holds the first account's lease mid-run; instance B ticks.
    worker._holder = lambda: "instance-A"
    worker._acquire(worker._lease_name("shard job", keys[0]), 600)
    worker._holder = lambda: "instance-B"
    got = worker._each_tenant("shard job", lambda k: worked.append(k) or {"ok": True})
    worker._holder = lambda: "instance-A"
    worker._release(worker._lease_name("shard job", keys[0]))
    worker._holder = real
    ck("a sharded job skips the account another instance holds and works the rest",
       keys[0] not in worked and set(worked) == set(keys[1:]),
       f"worked {worked} of {keys}")
    ck("  and says which account was skipped, by name",
       got.get(keys[0], {}).get("skipped") == "leased by another worker", str(got.get(keys[0])))

    # A sharded registration takes NO job-level lease — the pair.
    with db.SessionLocal() as s:
        s.query(db.JobLease).filter(db.JobLease.name == "pair job").delete()
        s.commit()
    worker._safe(lambda: None, "pair job", sharded=True)()
    with db.SessionLocal() as s:
        job_lease_after_sharded = s.get(db.JobLease, "pair job")
    worker._safe(lambda: None, "pair job", sharded=False)()
    with db.SessionLocal() as s:
        job_lease_after_plain = s.get(db.JobLease, "pair job")
    ck("a sharded job takes no job-level lease, an unsharded one does",
       job_lease_after_sharded is None and job_lease_after_plain is not None,
       "a job-level lease on top of per-tenant ones hands the whole job to "
       "one instance again")

    # The serial *_all is exactly the unit over every account — the two
    # paths cannot drift. Stub the expensive unit and compare.
    real_sync, real_harvest, real_psync = keywords.sync, keywords.harvest, performance.sync
    keywords.sync = lambda tenant, *, days=28: {"synced": tenant, "days": days}
    keywords.harvest = lambda tenant, *, limit=40: {"harvested": tenant}
    performance.sync = lambda tenant, *, days=30: {"ok": True, "t": tenant}
    try:
        a = keywords.sync_all(days=9)
        b = {k: keywords.sync_one(k, days=9) for k in keys
             if __import__("app.systems", fromlist=["find"]).find(k, "blog")}
        ck("keywords.sync_all is sync_one over every account with a blog", a == b, f"{a} vs {b}")
        a2 = performance.sync_all(days=5)
        from app import systems as _sy
        b2 = {k: performance.sync_one(k, days=5) for k in keys
              if (_sy.find(k, "campaign_email") and _sy.is_on(_sy.find(k, "campaign_email")))}
        ck("performance.sync_all is sync_one over every switched-on account", a2 == b2, f"{a2} vs {b2}")
    finally:
        keywords.sync, keywords.harvest, performance.sync = real_sync, real_harvest, real_psync

    # The library sweep runs once, not once per account.
    calls = {"n": 0}
    real_sweep = media.sweep
    media.sweep = lambda: calls.__setitem__("n", calls["n"] + 1) or {
        "dropped_rejected": 0, "expired_unreviewed": 0, "dropped_orphan": 0}
    try:
        worker.media_sweep()
    finally:
        media.sweep = real_sweep
    ck("picture retention sweeps the library once, not once per account",
       calls["n"] == 1, f"{calls['n']} sweep(s) for {len(keys)} account(s)")

    # Every sharded registration points at a wrapper that shards.
    sharded_regs = re.findall(r'_safe\((\w+), "[^"]+", sharded=True\)', src)
    ck("every sharded registration names a wrapper", len(sharded_regs) == 4, str(sharded_regs))
    ck("  and each wrapper calls _each_tenant",
       all(re.search(r'def ' + w + r'\(\) -> dict:\n(?:.*\n){0,3}.*_each_tenant\(', src)
           for w in sharded_regs),
       "a wrapper that loops itself is the job-level lease wearing a new name")

    # ======================================================================
    # PARALLEL IS OBSERVED, NOT ASSUMED
    # ======================================================================
    with db.SessionLocal() as s:
        s.query(db.JobLease).delete()
        s.add(db.JobLease(name="j1", last_holder="instance-A", last_run_at=db.utcnow()))
        s.add(db.JobLease(name="j2", last_holder="instance-A", last_run_at=db.utcnow()))
        s.add(db.JobLease(name="j3", last_holder="instance-B",
                          last_run_at=db.utcnow() - dt.timedelta(hours=48)))
        s.commit()
    one = worker.instances_seen(24)
    ck("one holder inside the window reads as one instance",
       one["instances"] == 1 and one["verdict"] == "one instance did every job", str(one))
    ck("  a holder outside the window is not counted",
       "instance-B" not in one["holders"], str(one["holders"]))
    with db.SessionLocal() as s:
        s.add(db.JobLease(name="j4", last_holder="instance-B", last_run_at=db.utcnow()))
        s.commit()
    two = worker.instances_seen(24)
    ck("two holders inside the window read as parallel — the pair",
       two["instances"] == 2 and two["verdict"] == "parallel", str(two))

    print()
    print("PASS" if not _fail else f"FAILED: {len(_fail)}")
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
