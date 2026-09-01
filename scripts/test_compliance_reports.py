"""Every compliance check files a dated report, clean or not.

Owner, 2026-08-31: *"Both should generate their own reports in the system,
dated and organized so it can be reviewed the history of compliance checks."*

Neither did. Three separate reasons, and each was invisible on its own:

  1. `content_compliance` put its findings on the RUN's `outcome` — a JSON
     blob readable only by the tab that rendered it, with no artifact behind
     it, so there was nothing to open and nothing dated to page through.
  2. `catalog_compliance` DID emit a report — and `ledger.record` dropped it.
     `"<" in body` gated BOTH branches of the keep test, so a declared
     artifact format was kept only if it happened to contain markup, and
     every plain-text artifact was discarded. `report` was not in
     `ARTIFACT_FORMATS` either.
  3. A CLEAN sweep returned before emitting anything, so the history recorded
     bad days and nothing else — and "we checked and it was clean" was
     indistinguishable from "nobody checked". Those are the two states a
     compliance record exists to tell apart.

Run: python3 scripts/test_compliance_reports.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'cr.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import (admin_ui, compliance, db, kb, ledger,  # noqa: E402
                 systems, tenants)

_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _reports(tenant, key):
    with db.SessionLocal() as s:
        rows = (s.query(db.ArtifactBody)
                .filter(db.ArtifactBody.tenant == tenant,
                        db.ArtifactBody.system_key == key,
                        db.ArtifactBody.format == "report")
                .order_by(db.ArtifactBody.created_at).all())
        s.expunge_all()
        return rows


def main() -> int:
    db.init_db()
    tenants.seed()
    kb.ensure_brand("baci", "Baci")
    kb.add_banned("baci", "handmade")
    systems.create("baci", "content_compliance")

    print("— a plain-text report is a KEPT artifact —")
    ck("`report` is a declared artifact format",
       "report" in ledger.ARTIFACT_FORMATS, str(ledger.ARTIFACT_FORMATS))
    row = ledger.record("baci", "content_compliance", format="report",
                        status="sent", body="Plain text, no markup at all.")
    ck("  and it is kept even with no markup in it",
       bool(_reports("baci", "content_compliance")),
       "`\\\"<\\\" in body` gated both branches, so every plain-text artifact "
       "was discarded — which is what a compliance report is")

    print("\n— a clean website sweep files one —")
    n0 = len(_reports("baci", "content_compliance"))
    compliance.record_scan("baci", {"pages_checked": 12, "violations": [],
                                    "by_phrase": {}})
    got = _reports("baci", "content_compliance")
    ck("the clean check is on the record", len(got) == n0 + 1)
    ck("  it is DATED in the report itself",
       "Website compliance — " in got[-1].body
       and "UTC" in got[-1].body.splitlines()[0], got[-1].body[:60])
    ck("  and it says plainly that nothing was found",
       "No banned claim found" in got[-1].body,
       "a history of only bad days cannot tell a clean check from no check")

    print("\n— and so does a dirty one, with where —")
    compliance.record_scan("baci", {
        "pages_checked": 9, "by_phrase": {"handmade": 2},
        "violations": [{"url": "https://x/a",
                        "hits": [{"phrase": "handmade",
                                  "context": "our handmade bowls"}]}]})
    body = _reports("baci", "content_compliance")[-1].body
    ck("the count leads", "1 violation(s)" in body, body.splitlines()[2][:60])
    ck("  the phrase is counted", "2x  'handmade'" in body)
    ck("  and the URL is there to go and fix",
       "https://x/a" in body and "our handmade bowls" in body)

    print("\n— a scan that could not run says so, and is not clean —")
    compliance.record_scan("baci", {"error": "no domain on file"})
    body = _reports("baci", "content_compliance")[-1].body
    ck("it is filed, not skipped", "NOT CHECKED" in body, body[:70])
    ck("  and refuses to read as clean",
       "says it is clean" in body and "No banned claim" not in body,
       "a sweep that reported CLEAN having read nothing is the false "
       "assurance both these systems exist to prevent")

    print("\n— the history has its own room, dated, newest first —")
    sysrow = systems.find("baci", "content_compliance")
    ck("Reports is a rail on a system whose deliverable IS the report",
       "reports" in [v for v, _l in admin_ui._workflow_subs(sysrow)],
       str([v for v, _l in admin_ui._workflow_subs(sysrow)]))
    card = admin_ui._reports_section("s3cret", sysrow)
    ck("  every check is listed", card.count('class="msg"') == 4,
       str(card.count('class="msg"')))
    ck("  each one links to its own workroom", "/admin/work/" in card)
    ck("  and the states are told apart at a glance",
       "clean" in card and "findings" in card and "not checked" in card,
       "three states, three chips — the whole reason to keep a history")

    print("\n— and both systems now declare where their work goes —")
    for k in ("content_compliance", "catalog_compliance"):
        wf = systems.workflow(k)
        ck(f"  {k:20s} declares a ship", bool(wf.get("ship")), str(wf.get("ship"))[:50])
        ck(f"    and names what performs it", bool(wf.get("ship_by")),
           str(wf.get("ship_by")))
        ck(f"    with `report` as its artifact", wf.get("artifact") == "report",
           str(wf.get("artifact")))

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
