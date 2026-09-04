"""What the owner can run tonight, from a URL, and what the probe says.

Built the evening before a client presentation, when the question was "does
any of this actually work" and the answer was "the suites say so". These are
the surfaces that let a person check without a suite: two on-demand jobs
(the Sunday learning sweep and the weekly report planner) and a connections
probe that names the image key — which, absent, had degraded every ad to a
placeholder and every article to no pictures with nothing anywhere saying so.

Run: python3 scripts/test_ops_added.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'oa.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["SEO_SITES_JSON"] = "{}"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import config, db, ops_jobs, systems, tenants, web  # noqa: E402

_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    db.init_db()
    tenants.seed()
    c = TestClient(web.app)

    # ---- the two jobs exist where /admin/run_job looks --------------------
    ck("learning_sweep is an on-demand job", callable(ops_jobs.JOBS.get("learning_sweep")))
    ck("report_plans is an on-demand job", callable(ops_jobs.JOBS.get("report_plans")))
    r = c.get("/admin/run/learning_sweep?key=s3cret")
    ck("the route accepts it", r.status_code == 200 and "started" in r.text, r.text[:100])

    said = ops_jobs.report_plans()
    ck("report plans on a bare platform says nothing is switched on",
       "no account has the reports system switched on" in said, said[:100])
    row = systems.find("baci", "reports") or systems.create("baci", "reports")
    with db.SessionLocal() as s:
        s.get(db.System, row.id).status = "live"
        s.commit()
    said2 = ops_jobs.report_plans()
    ck("  and with one on, it files that account's weeks — the pair",
       "baci:" in said2 and "proposed" in said2, said2[:100])
    out = ops_jobs.learning_sweep()
    ck("the learning sweep runs on demand and reports per account",
       isinstance(out, str) and "baci" in out, out[:120])

    # ---- the probe names the image key ----------------------------------
    real = config.OPENAI_API_KEY
    config.OPENAI_API_KEY = ""
    try:
        missing = c.get("/health/connections?key=s3cret").json()
    finally:
        config.OPENAI_API_KEY = real
    ck("with no image key the connections probe says which key, by name",
       "OPENAI_API_KEY" in str(missing.get("images", "")), str(missing.get("images"))[:100])
    config.OPENAI_API_KEY = "sk-test"
    try:
        present = c.get("/health/connections?key=s3cret").json()
    finally:
        config.OPENAI_API_KEY = real
    ck("  and with one set it says so — the pair",
       str(present.get("images", "")).startswith("ok"), str(present.get("images"))[:60])

    print()
    print("PASS" if not _fail else f"FAILED: {len(_fail)}")
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
