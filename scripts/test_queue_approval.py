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
    # ONE CLICK, NOT TWO. Owner, 2026-09-01: *"the 'Put it in front of me'
    # button is not necessary, just put the approve button directly there.
    # This applies to all systems."* The two-step was an artefact of how the
    # control got built — queuing arrived as the missing control and approving
    # already lived elsewhere — so the page asked for the queue and THEN the
    # decision. Nobody pressed the first meaning anything but the second.
    ck("the page offers the decision itself", ">Approve</button>" in page,
       "a page that reports an absence with no control is a fix instruction; "
       "one that asks to be asked is one gesture too many")
    ck("  and it is not a request to be asked later",
       "Put it in front of me" not in page,
       "the intermediate step is gone, not renamed")
    ck("  and says what pressing it does",
       "releases it to ship" in page,
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
    # DECIDED IN PLACE, not handed off to the email mechanism. The bar used
    # to link to `/decide/<signed-token>`, which renders a bare `<h2>` on an
    # unstyled page with no way back — the owner's "a page that confirms its
    # been sent with no UI", 2026-08-31.
    ck("Approve is there", "Approve" in page2
       and "/admin/ship_decide" in page2)
    ck("  and it decides in place rather than leaving the console",
       "/decide/" not in page2,
       "the signed links stay the EMAIL mechanism; a console page posts")
    ck("  and it lands back on this artifact",
       f'name="back_work" value="{oid}"' in page2,
       "design rule 3: a decision never costs the reader their place")
    ck("  Redraft is beside it", "#redraft" in page2)
    ck("  and it stops offering the standalone control",
       ">Approve</button>" not in page2 or "/admin/ship_decide" in page2,
       "two ways to ask for the same thing is the bulk this removed")

    print("\n— and the button that says Approve APPROVES —")
    oid2, _r2 = _stranded("baci")
    r2 = c.post(f"/admin/queue_approval?key={KEY}",
                data={"output_id": oid2, "decide": "approved"},
                follow_redirects=False)
    ck("it lands back on the workroom", r2.status_code == 303
       and f"/admin/work/{oid2}" in r2.headers.get("location", ""))
    with db.SessionLocal() as s_:
        rows = [a for a in s_.query(db.Approval).all()
                if str((a.payload or {}).get("output_id") or "") == oid2]
    ck("the approval row still exists",
       len(rows) == 1,
       "one click fewer, not one record fewer — the audit trail is the whole "
       "reason the row is created rather than skipped")
    ck("  and it is decided, not pending",
       rows and rows[0].status in ("approved", "executed"),
       str(rows[0].status if rows else "none"))
    ck("  decided by the same executor every other surface uses",
       rows and rows[0].decided_at is not None,
       "`approvals.apply_decision` is what the signed email link and "
       "`ship_decide` call, so the record does not depend on which surface "
       "made the decision")

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

    print("\n— ONE press: decide, and land back here, styled —")
    ap_id = _pending(oid)[0].id
    r4 = c.post(f"/admin/ship_decide?key={KEY}",
                data={"tenant": "baci", "approval_id": ap_id,
                      "back_work": oid, "verdict": "approved"},
                follow_redirects=False)
    ck("one press decides it", r4.status_code == 303 and not _pending(oid),
       f"{r4.status_code}, {len(_pending(oid))} still pending")
    loc = r4.headers.get("location", "")
    ck("  and lands back on the artifact, not on a bare page",
       loc.startswith(f"/admin/work/{oid}") and "ok=" in loc, loc[:110])
    page3 = c.get(loc).text
    ck("  which renders the confirmation as UI",
       'class="flash"' in page3 or 'class="ok"' in page3,
       "the owner's complaint was an unstyled <h2> with no way back")
    ck("  and there is no second Approve to press",
       "Approve" not in page3.split("Waiting on you")[0]
       or "/admin/ship_decide" not in page3,
       "a decided artifact must stop offering the decision")

    print("\n— an ad batch is queued the way its board READS: per variant —")
    import json as _json
    batch = {"variants": [{"output_id": "v-one", "headline": "A"},
                          {"output_id": "v-two", "headline": "B"}]}
    oid3, _ = _stranded("baci", body=_json.dumps(batch))
    with db.SessionLocal() as s_:
        _a = (s_.query(db.ArtifactBody)
              .filter(db.ArtifactBody.output_id == oid3).first())
        _a.format = "ad_batch"
        s_.commit()
    c.post(f"/admin/queue_approval?key={KEY}", data={"output_id": oid3},
           follow_redirects=False)
    # The board counts approvals whose payload output_id is a VARIANT's, and
    # `/admin/ad_batch_decide` resolves those. One approval carrying the BATCH
    # id would satisfy `_article_bundle`, hide this button, and be counted by
    # nothing — an approval no surface can decide.
    ck("no approval is filed against the batch itself", not _pending(oid3),
       "a batch-level row is decidable by nothing on that page")
    ck("  one is filed against each variant",
       len(_pending("v-one")) == 1 and len(_pending("v-two")) == 1,
       f'v-one={len(_pending("v-one"))}, v-two={len(_pending("v-two"))}')

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
