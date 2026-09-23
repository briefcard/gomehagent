"""Work that runs somewhere else still says what it is doing.

Owner, 2026-09-23, after the heavy jobs moved to the worker: *"can we have a
loading toaster that updates us on the status of each ongoing job and clicks
into a job queue that we can track in case there are several jobs in the
queue?"*

The move was right and it cost visibility. A press returns instantly now, and
the only sign anything was happening was a card on the page you pressed it
from — walk to another tab and the console looked idle while a twelve-minute
recreation ran.

So: a pill on EVERY page of an account that has something in the air, and a
queue room it clicks into. What this suite holds shut —

  · the pill is rendered SERVER-SIDE and is true without a line of script;
  · it is absent when nothing is in the air, because a badge reading "0 jobs"
    is furniture and the pill has to mean something the moment it appears;
  · the queue is reachable when the pill is not, since "did it finish" is
    asked most often when nothing is running;
  · the room says WHICH, in what order, and how long each has been at it —
    "queued" with nothing else said is the silence this queue was built to
    remove;
  · a queued job can be taken off; a running one cannot be, and says why
    rather than pretending;
  · a job a restart stopped can be run again, as a NEW row.

    python3 scripts/test_the_queue_is_visible.py
"""
import os
import re
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'q.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["SEO_SITES_JSON"] = "{}"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient                        # noqa: E402

from app import admin_ui as ui, db, jobs, tenants, web           # noqa: E402

KEY = "s3cret"
BROWSER = {"accept": "text/html"}
_fail: list = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _pill(html: str) -> str:
    m = re.search(r'<a class="jobpill"[^>]*>(.*?)</a>', html, re.S)
    return m.group(0) if m else ""


def main() -> int:
    db.init_db()
    tenants.seed()
    c = TestClient(web.app)
    c.cookies.set("console", web._console_token())

    print("— an idle account is not told it is idle —")
    page = ui.render_brand(KEY, "baci")
    ck("the pill is on the page but hidden when nothing is in the air",
       "jobpill" in page and " hidden>" in _pill(page),
       "a badge reading 0 jobs is furniture")
    ck("  and the queue is reachable anyway, from the frame",
       ui.url("baci", "jobs") in page,
       "'did it finish' is asked most often when nothing is running")

    print("\n— something in the air, on every page —")
    a = jobs.enqueue("baci", "email_recreate",
                     payload={"mode": "run", "structure": "st-1"})["id"]
    b = jobs.enqueue("baci", "sync", payload={})["id"]
    d = jobs.enqueue("baci", "boards", payload={"mode": "read", "slug": "studio"})["id"]
    jobs.claim("baci", "worker-1")
    jobs.heartbeat(a, "cast 3 of 24 photographs")
    for where, html in (("Brand", ui.render_brand(KEY, "baci")),
                        ("Plan", ui.render_plan(KEY, "baci"))):
        p = _pill(html)
        ck(f"  the {where} page carries it, without script",
           p and " hidden>" not in p and "3" in p, p[:90])
    ck("  and it says what the running one is doing, not just that one is",
       "cast 3 of 24" in _pill(ui.render_brand(KEY, "baci")))
    ck("  with the others counted, so three behind one is not read as one",
       "2 more waiting" in _pill(ui.render_brand(KEY, "baci")),
       _pill(ui.render_brand(KEY, "baci"))[:120])
    ck("another account's work is not this account's pill",
       " hidden>" in _pill(ui.render_brand(KEY, "eien")))

    print("\n— what the pill polls —")
    got = c.get(f"/admin/jobs.json?tenant=baci").json()
    ck("it answers in counts and a sentence",
       got["n_flight"] == 3 and got["running"] == 1 and got["queued"] == 2
       and "cast 3 of 24" in got["says"], str(got))
    ck("  and it is a READ — a poller that can start work is a machine for "
       "repeating a mistake every five seconds",
       "jobs_json" in open(os.path.join(os.path.dirname(os.path.dirname(
           os.path.abspath(__file__))), "app", "web.py"), encoding="utf-8").read()
       and jobs.board("baci")["n_flight"] == 3)
    ck("  it refuses without the console key",
       TestClient(web.app).get("/admin/jobs.json?tenant=baci").json().get("error")
       == "unauthorized")

    print("\n— the room it clicks into —")
    room = c.get("/admin/baci/jobs", headers=BROWSER).text
    ck("the queue opens", "The queue" in room and "What ran" in room)
    ck("  the running one is named, with how long it has been at it",
       "running" in room and "so far" in room)
    ck("  and the ones behind it know their place",
       "1 in line" in room and "2 in line" in room,
       "queued with nothing else said is the silence this replaced")
    ck("  each row says what kind of work it is",
       "email_recreate" in room and "sync" in room and "boards" in room)

    print("\n— the two controls a queue needs —")
    r = c.post("/admin/job_cancel", params={"key": KEY},
               data={"tenant": "baci", "id": b}, follow_redirects=False)
    cancelled = [j for j in jobs.board("baci")["done"] if j["id"] == b]
    ck("a queued job can be taken off", r.status_code == 303
       and "ok=" in r.headers.get("location", "")
       and cancelled and cancelled[0]["state"] == "cancelled",
       str(cancelled)[:100])
    ck("  and it leaves the queue", b not in [j["id"] for j in jobs.board("baci")["queued"]])
    r = c.post("/admin/job_cancel", params={"key": KEY},
               data={"tenant": "baci", "id": a}, follow_redirects=False)
    ck("a RUNNING job cannot be cancelled, and says why rather than pretending",
       "err=" in r.headers.get("location", "")
       and "worker is inside it" in r.headers.get("location", "").replace("%20", " "),
       r.headers.get("location", "")[:120])

    jobs.finish(d, "interrupted", "a deploy stopped it")
    r = c.post("/admin/job_again", params={"key": KEY},
               data={"tenant": "baci", "id": d}, follow_redirects=False)
    ck("a job a restart stopped can be run again", r.status_code == 303
       and "ok=" in r.headers.get("location", ""))
    again = [j for j in jobs.board("baci")["queued"] if j["kind"] == "boards"]
    ck("  as a NEW row, carrying the same work",
       len(again) == 1 and again[0]["id"] != d,
       "the old row is what happened; the history is the point")
    room2 = c.get("/admin/baci/jobs", headers=BROWSER).text
    ck("  and the stopped one is still on the page, said as stopped",
       "stopped by a restart" in room2)

    print()
    print("PASS" if not _fail else f"FAILED: {len(_fail)}\n  " + "\n  ".join(_fail))
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
