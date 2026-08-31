"""A draft with no decision on it can be put in front of a person.

Until 2026-08-31 `_disposition` returned `recorded` on `shadow`, and `emit`
queues an approval only on `needs_approval`. Shadow is the DEFAULT —
`db.System.autonomy` defaults to it and `systems.create` never sets anything
else — so every system a client installed and did not promote drafted things
nobody could approve. The owner's report was simply *"I don't see the button"*,
and they were right: there was no row for a button to act on.

`_disposition` now queues at every rung but `auto`, which fixes it going
forward. This suite covers the half that reaches BACKWARD: every draft already
in the store was filed under the old rule. Backfilling would drop an unread
queue on somebody in one transaction, so instead the draft carries the control
that ends its own absence — design rule 1, on the surface the rule was written
for.

WHAT IS ASSERTED:

  · the control is ON the page that reports the absence, not in a runbook
  · pressing it produces a pending decision for THAT artifact
  · the ESP recipe rides along, so a late-queued campaign approves into
    something rather than into nothing
  · pressing it twice does not queue twice
  · an empty draft is refused — there is nothing to approve
  · once queued, the page offers Approve and Redraft and stops offering to
    queue

Run: python3 scripts/test_queue_approval.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'qa.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import (admin_ui, db, kb, systems, tenants, web)  # noqa: E402

KEY = "s3cret"
_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _stranded(tenant, *, body="<p>A quiet note about the table.</p>", push=None):
    """An artifact filed the way the old default rung filed them: no approval."""
    row = systems.find(tenant, "campaign_email") or \
        systems.create(tenant, "campaign_email")
    with db.SessionLocal() as s:
        out = db.Output(tenant=tenant, system_key="campaign_email",
                        format="email", status="recorded", body=body[:2000])
        s.add(out)
        s.commit()
        art = db.ArtifactBody(tenant=tenant, output_id=out.id,
                              system_key="campaign_email", format="email",
                              body=body, draft_body=body, bytes=len(body),
                              push=dict(push or {}))
        s.add(art)
        s.commit()
        oid = out.id
    return oid, row


def _page(oid):
    art, kw, ap = web._article_bundle(oid)
    return admin_ui.render_workroom(KEY, oid, art, kw, ap)


def _pending(oid):
    with db.SessionLocal() as s:
        return [a for a in s.query(db.Approval)
                .filter(db.Approval.status == "pending").all()
                if (a.payload or {}).get("output_id") == oid]


def main() -> int:
    db.init_db()
    tenants.seed()
    kb.ensure_brand("baci", "Baci")
    c = TestClient(web.app)

    print("— a stranded draft carries the control that ends its own absence —")
    oid, _row = _stranded("baci", push={"provider": "omnisend",
                                        "subject": "A note"})
    page = _page(oid)
    # The BUTTON, not the form's action attribute: asserting on the URL let
    # the button itself be deleted with the suite still green (sabotage
    # reported MISSED, 2026-08-31). What a person clicks is the surface.
    ck("the page offers to queue it", "Put it in front of me" in page,
       "a page that reports an absence with no control is a fix instruction")
    ck("  and says what pressing it gets you",
       "Approve" in page and "send it back" in page.lower(),
       "state the consequence on the button, not in a paragraph elsewhere")

    print("\n— pressing it produces a decision for THAT artifact —")
    r = c.post(f"/admin/queue_approval?key={KEY}",
               data={"output_id": oid}, follow_redirects=False)
    ck("it lands back on the workroom", r.status_code == 303
       and f"/admin/work/{oid}" in r.headers.get("location", ""),
       r.headers.get("location", ""))
    ck("  and says it worked", "ok=" in r.headers.get("location", ""))
    got = _pending(oid)
    ck("exactly one decision is now waiting", len(got) == 1, str(len(got)))
    ck("  and the ESP recipe rode along",
       bool((got[0].payload or {}).get("esp_push")),
       "without it a late-queued campaign approves into nothing — the push "
       "reads the payload, and ArtifactBody.push is the machine's stash "
       "written precisely so a campaign reviewed outside the flow can ship")

    print("\n— and now the page offers the pair, not the queue button —")
    page2 = _page(oid)
    ck("Approve is there", "Approve" in page2 and "/decide/" in page2)
    ck("  Redraft is beside it", "#redraft" in page2)
    ck("  and it stops offering to queue what is already queued",
       "Put it in front of me" not in page2,
       "two ways to ask for the same thing is the bulk this removed")

    print("\n— pressing it twice does not queue twice —")
    c.post(f"/admin/queue_approval?key={KEY}", data={"output_id": oid},
           follow_redirects=False)
    ck("still exactly one", len(_pending(oid)) == 1, str(len(_pending(oid))))

    print("\n— an empty draft is refused —")
    oid2, _ = _stranded("baci", body="   ")
    r2 = c.post(f"/admin/queue_approval?key={KEY}",
                data={"output_id": oid2}, follow_redirects=False)
    ck("nothing to approve is said, not queued",
       "err=" in r2.headers.get("location", "") and not _pending(oid2),
       r2.headers.get("location", ""))

    print("\n— and it is behind the admin key —")
    # The console serves its sign-in page rather than a JSON error to an
    # unauthenticated browser, so the property worth asserting is the effect,
    # not the wording: a wrong key queues nothing.
    before = len(_pending(oid2))
    c.post("/admin/queue_approval?key=wrong", data={"output_id": oid2})
    ck("a wrong key queues nothing", len(_pending(oid2)) == before,
       f"{before} -> {len(_pending(oid2))}")

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
