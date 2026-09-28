"""Every job is a file you can hand to Claude — the platform's context, the
job's inputs and what went wrong — from the queue.

Owner, 2026-09-28: "make sure that every Job organizes the context in the
skill file and shows it in the job queue so I can take failed jobs and just
run them in a Claude chat in case it fails and I have to quickly turn it
around for a client."

`handoff.for_job` builds the file from the SAME package the job's skill reads
(`resolve.resolve`, `bundle.PARTS` in order); the Queue links every row to it.
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'h.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["SEO_SITES_JSON"] = "{}"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import admin_ui as ui, db, handoff, jobs, kb, systems, tenants, web  # noqa: E402

_fail: list = []
T = "baci"
CLAIM = "Designed in Milan by the Italian design house Baci Milano."


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    db.init_db()
    tenants.seed()
    kb.add_claim(T, CLAIM, "brand file", [], origin="human", status="active")
    kb.add_banned(T, "hand-decorated")
    kb.add_audience(T, "hosts", "Hosts who entertain", ["dull tables"], ["a table worth a photo"])
    kb.add_entity(T, "product", "portofino", "Portofino dinner set")
    sysrow = systems.find(T, "campaign_email") or systems.create(T, "campaign_email")
    with db.SessionLocal() as s:
        s.get(db.System, sysrow.id).status = "live"
        s.commit()
    plan = systems.open_plan(T, "campaign_email", ref="t:1", planned_for="2026-10-01",
                             plan={"segment": "new_subscribers", "audience_key": "hosts",
                                   "goal": "Art Basel — hosting guests during the fair",
                                   "entity_key": "portofino"})
    job = jobs.enqueue(T, "system_run", system_key="campaign_email", label="Email — Art Basel",
                       payload={"key": "campaign_email", "trigger": "manual",
                                "run_id": plan["run_id"]})["id"]
    jobs.claim(T, "w")
    jobs.finish(job, "failed", "RuntimeError: the email could not be made — the maker timed out")

    print("— a failed email job, as a skill file —")
    got = handoff.for_job(job)
    md = got.get("markdown", "")
    ck("it is a skill file: frontmatter naming the account and the work",
       md.startswith("---\nname: baci-") and "\ndescription: " in md.split("---")[1], md[:120])
    ck("  it says what went wrong, in the platform's own words",
       "## What happened" in md and "the maker timed out" in md)
    ck("  what to hand back, for this kind of work", "complete HTML" in md and "{{UNSUBSCRIBE}}" in md)
    ck("  the job's own inputs — the plan it was asked to carry out",
       "Art Basel — hosting guests during the fair" in md and '"segment": "new_subscribers"' in md)
    ck("  the brand package the skill reads: its proof, its ban list, its buyer, its catalogue",
       CLAIM in md and "hand-decorated" in md and "Hosts who entertain" in md
       and "Portofino dinner set" in md, "")
    ck("  in the package's own declared order, each part saying what it is",
       md.index("### rules") < md.index("### claims") < md.index("### entities")
       and "### claims — approved proof" in md)
    ck("  the rules that are never broken travel with it", "Invent nothing" in md)

    print("\n— a job a chat cannot do still says what it was and why it stopped —")
    sync = jobs.enqueue(T, "sync", payload={})["id"]
    jobs.claim(T, "w")
    jobs.finish(sync, "failed", "the store refused the token")
    md2 = handoff.for_job(sync)["markdown"]
    ck("a sync's file is its task and its failure — no brand package pretending to help",
       "the store refused the token" in md2 and "cannot do it" in md2 and "### claims" not in md2)
    ck("an unknown job is refused by name", handoff.for_job("nope") == {"ok": False, "why": "no such job"})

    print("\n— the queue carries it: every row, and the failed ones say what it is for —")
    page = ui.render_jobs("s3cret", T)
    ck("the failed job links to its file, as a way to finish it",
       f"/admin/job_brief?id={job}" in page and "Finish it in Claude" in page)
    c = TestClient(web.app)
    c.cookies.set("console", web._console_token())
    r = c.get(f"/admin/job_brief?id={job}&tenant={T}")
    ck("the page offers it to copy, whole", r.status_code == 200 and 'id="brief"' in r.text
       and "the maker timed out" in r.text)
    r = c.get(f"/admin/job_brief?id={job}&tenant={T}&download=1")
    ck("and to download, as a .md named for the account and the work",
       r.status_code == 200 and r.headers.get("content-type", "").startswith("text/markdown")
       and 'filename="baci-' in r.headers.get("content-disposition", "")
       and r.text.startswith("---\nname: baci-"), r.headers.get("content-disposition", ""))

    print()
    print("ALL GREEN" if not _fail else f"FAILED: {len(_fail)}")
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
