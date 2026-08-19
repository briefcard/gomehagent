"""Where a system is breaking, at which layer, and only for the account asked.

Two things this holds, and the second is why the file exists at all.

**The classification.** A blocked run and a failed run are not the same event.
One is the pipeline refusing a named missing thing — the design working, and a
job for the knowledge queue. The other is an exception — a job for the code or
a connection. A page that colours them alike sends somebody to the wrong place,
so the layer is asserted per event rather than inferred by whoever reads it.

**The scoping.** Every query in `diagnostics` filters on the account, and the
only way to see more than one is to ask for it by name. Seeded with real rows
on TWO accounts, so a leak fails the test rather than passing an empty table —
which is exactly how `test_console_frame` was passing while the Systems tab
rendered every client's pipelines on one page.

    python3 scripts/test_diagnostics.py
"""
import datetime as dt
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'dg.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import (approvals, assurance, db, diagnostics, kb,  # noqa: E402
                 systems, tenants, toolcalls, web)

_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def seed():
    db.init_db()
    tenants.seed()
    kb.ensure_brand("baci", "Baci Milano USA")
    kb.ensure_brand("ironside", "Miami Ironside")

    si = systems.create("ironside", "lead_responder", "Lead responder")
    sb = systems.create("baci", "campaign_email", "Campaign email")

    # ironside: one clean, one blocked, one raised.
    ok = systems.start_run(si.id, "ironside", trigger="inbound_email", ref="m1")
    systems.finish_run(ok, "sent", decision="approved")
    bl = systems.start_run(si.id, "ironside", trigger="inbound_email", ref="m2")
    systems.finish_run(bl, "blocked", blocked_on=["lead_time"])
    er = systems.start_run(si.id, "ironside", trigger="schedule")
    systems.finish_run(er, "failed", error="ShopifyError: 401 unauthorised")

    # baci: a run with a phrase nobody outside baci should ever see.
    bb = systems.start_run(sb.id, "baci", trigger="schedule", ref="BACI-ONLY-REF")
    systems.finish_run(bb, "blocked", blocked_on=["baci_secret_gap"])

    toolcalls.record("ironside", "gmail_search", provider="google", ok=True, ms=120)
    toolcalls.record("ironside", "shopify_products", provider="shopify",
                     ok=False, error="401 invalid token", ms=90)
    toolcalls.record("ironside", "slow_thing", provider="google", ok=True,
                     ms=diagnostics.SLOW_MS + 500)
    toolcalls.record("baci", "baci_only_tool", provider="shopify", ok=False,
                     error="BACI-ONLY-ERROR")

    assurance.record("ironside", source="substrate", checked=["banned_claims"],
                     caught=["banned_claim"], verdict="blocked")
    assurance.record("baci", source="seo", checked=["banned_claims"],
                     caught=["baci_only_rule"], verdict="blocked")

    approvals.request_approval("send_email", "Ironside enquiry reply",
                               {"body": "hi", "tenant": "ironside"}, notify=False)
    approvals.request_approval("send_email", "BACI-ONLY-APPROVAL",
                               {"body": "hi", "tenant": "baci"}, notify=False)
    return si, sb


def main() -> int:
    si, sb = seed()

    print("— one account's log is one account's —")
    ev = diagnostics.events("ironside", days=7, limit=500)
    ck("something was recorded at all", len(ev) > 0, f"{len(ev)} events")
    ck("no other account's rows are in it",
       all(e["tenant"] == "ironside" for e in ev),
       "a diagnostics page pooling clients is the defect it was built to fix")
    blob = repr(ev)
    for marker in ("BACI-ONLY-REF", "BACI-ONLY-ERROR", "BACI-ONLY-APPROVAL",
                   "baci_secret_gap", "baci_only_rule"):
        ck(f"  {marker} does not appear", marker not in blob)

    print("\n— and the cross-account view is reached by asking, never by default —")
    every = diagnostics.events("", days=7, limit=500)
    ck("it exists", any(e["tenant"] == "baci" for e in every)
       and any(e["tenant"] == "ironside" for e in every))
    ck("  and every row still names its account",
       all(e["tenant"] for e in every))

    print("\n— a refusal and a crash are not the same event —")
    runs = [e for e in ev if e["kind"] == "run"]
    blocked = [e for e in runs if "blocked" in e["summary"]]
    failed = [e for e in runs if "failed" in e["summary"]]
    ck("a blocked run is logic, not a failure",
       blocked and blocked[0]["layer"] == "logic" and blocked[0]["level"] == "warn",
       "the pipeline refusing a named gap IS the design working")
    ck("  and names what it refused on",
       blocked and "lead_time" in blocked[0]["detail"])
    ck("a raised run is functionality",
       failed and failed[0]["layer"] == "functionality"
       and failed[0]["level"] == "fail")
    ck("  and carries the provider's own words",
       failed and "401" in failed[0]["detail"],
       "'tool failed' sends nobody anywhere")

    print("\n— slow is its own layer, not a failure —")
    slow = [e for e in ev if e["kind"] == "tool" and e["layer"] == "performance"]
    ck("a slow call is performance", len(slow) == 1, f"{len(slow)}")
    ck("  and still counts as having worked",
       slow and slow[0]["level"] == "warn")
    dead = [e for e in ev if e["kind"] == "tool" and e["level"] == "fail"]
    ck("a dead call is functionality",
       dead and dead[0]["layer"] == "functionality")

    print("\n— absence is reported as absence, never as zero —")
    quiet = diagnostics.report("coverings", days=7)
    ck("a silent account says so", quiet["silent"] and quiet["note"],
       "nothing ran and a clean run look identical as zeros")
    ck("  and does not claim health",
       "clean report" in quiet["note"])
    h = diagnostics.health("coverings", days=7)
    ck("an account with no system says that too", bool(h["note"]))
    hi = diagnostics.health("ironside", days=7)
    row = hi["systems"][0]
    ck("a system that ran gets a verdict, not a score", bool(row["verdict"]))
    ck("  blocked and failed are counted apart",
       row["blocked"] == 1 and row["failed"] == 1,
       f'{row["blocked"]}/{row["failed"]}')

    print("\n— platforms rank by rate, and say what could not be timed —")
    pf = diagnostics.platforms("ironside", days=7)
    ck("the broken connection is first",
       pf["providers"] and pf["providers"][0]["provider"] == "shopify",
       "a provider failing most of the time is not the same as the internet")
    ck("  and carries its last error",
       pf["providers"][0]["last_error"].startswith("401"))
    ck("the slow tool is listed", any(t["tool"] == "slow_thing" for t in pf["slow"]))

    print("\n— a run that never finished is not a run that failed —")
    lost = systems.start_run(si.id, "ironside", trigger="schedule")
    with db.SessionLocal() as s:
        r = s.get(db.SystemRun, lost)
        r.created_at = db.utcnow() - dt.timedelta(
            hours=diagnostics.STALE_RUN_HOURS + 2)
        s.commit()
    hi2 = diagnostics.health("ironside", days=7)
    r2 = hi2["systems"][0]
    ck("it is counted as unfinished", r2["unfinished"] == 1)
    ck("  and the verdict points at the worker",
       "never finished" in r2["verdict"])

    print("\n— the tab renders, and renders one account —")
    c = TestClient(web.app)
    r = c.get("/admin/ui?key=s3cret&tab=diagnostics&tenant=ironside")
    ck("200", r.status_code == 200, str(r.status_code))
    body = r.text.split('<div class="main">', 1)[-1]
    ck("  it is in the nav", "Diagnostics" in r.text)
    ck("  names the account above the fold", "Miami Ironside" in body[:500])
    for marker in ("BACI-ONLY-APPROVAL", "BACI-ONLY-ERROR", "baci_secret_gap"):
        ck(f"  {marker} is not on the page", marker not in body)
    ck("  the failing platform is on it", "401 invalid token" in body)

    print("\n— filters narrow rather than widen —")
    only_fail = c.get("/admin/ui?key=s3cret&tab=diagnostics&tenant=ironside"
                      "&level=fail").text.split('<div class="main">', 1)[-1]
    ck("a level filter drops the clean rows",
       only_fail.count('class="ev ok"') == 0
       and only_fail.count('class="ev fail"') > 0)
    ck("  and cannot pull in another account",
       "BACI-ONLY-ERROR" not in only_fail)

    print("\n— the filter chips count the window, not themselves —")
    both = diagnostics.report("ironside", days=7, level="problems")
    ck("problems only keeps failures AND warnings",
       all(e["level"] in ("fail", "warn") for e in both["events"])
       and any(e["level"] == "fail" for e in both["events"])
       and any(e["level"] == "warn" for e in both["events"]),
       "'failures' alone hides the blocked runs, which is where most "
       "breakdowns show first")
    ck("  and the counts still describe the whole window",
       both["counts"] == diagnostics.report("ironside", days=7)["counts"],
       "a chip reading 0 because you are already filtered agrees with nothing")

    print("\n— live is opt-in, and the page it polls is a pure read —")
    off = c.get("/admin/ui?key=s3cret&tab=diagnostics&tenant=ironside").text
    ck("no refresh unless asked for", "http-equiv=\"refresh\"" not in off,
       "a page that reloads while somebody reads a stack trace is worse than "
       "one they refresh themselves")
    on = c.get("/admin/ui?key=s3cret&tab=diagnostics&tenant=ironside"
               "&live=15").text
    ck("  and one when it is", 'http-equiv="refresh" content="15"' in on)
    ck("  while the filters survive the reload",
       "live=15" in on and "days=7" in on,
       "a refresh that drops your filter is a refresh that undoes your work")
    # The reason polling is safe HERE and was catastrophic elsewhere: this
    # endpoint writes nothing. Asserted rather than asserted-in-a-comment.
    before = c.get("/admin/diagnostics?key=s3cret&tenant=ironside").json()
    after = c.get("/admin/diagnostics?key=s3cret&tenant=ironside").json()
    ck("reading it twice changes nothing",
       before["counts"] == after["counts"]
       and len(before["events"]) == len(after["events"]),
       "the ~200-draft incident was a poller re-firing a side-effectful "
       "endpoint; this one must never become one")

    print("\n— the JSON route refuses to guess an account —")
    r = c.get("/admin/diagnostics?key=s3cret")
    ck("no tenant is refused by name", "tenant is required" in r.json().get("error", ""),
       "an absent account would have to mean 'all' or 'the first one', and a "
       "monitor guessing between those watches the wrong client")
    ck("  and * is the explicit all",
       c.get("/admin/diagnostics?key=s3cret&tenant=*").json()["tenant"] == "")

    print("\n— all-accounts is a place you go on purpose —")
    allp = c.get("/admin/ui?key=s3cret&tab=diagnostics&tenant=*")
    ck("it renders", allp.status_code == 200)
    ab = allp.text.split('<div class="main">', 1)[-1]
    ck("  and says so on the page itself", "All accounts" in ab)
    ck("  and only then shows both", "baci" in ab and "ironside" in ab)

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
