"""The Omnisend send path, driven against a stubbed transport.

Connecting Omnisend used to switch on the `esp` capability and nothing else —
`campaign_email` could install, pass readiness and go live with no way to put
an email anywhere.

The API cannot be reached from here, so `omnisend.call` is replaced and what is
checked is the REQUEST this module builds and the decisions it makes about it:
that a campaign is drafted and never sent, that sending needs an explicit
confirmation, that a sender address is never invented, and that a half-finished
run says what it left behind.

Run: python3 scripts/test_omnisend.py
"""
import os
import sys
import tempfile

_tmp = os.path.join(tempfile.mkdtemp(), "omni.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}"
os.environ["APPROVAL_SECRET"] = "test-secret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, omnisend, tenants  # noqa: E402

_fails: list[str] = []
_sent: list[dict] = []


def ck(label: str, cond: bool, detail: str = "") -> None:
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fails.append(label)


def _fake(responses: dict):
    """Record every request, answer from a path->response map."""
    def _c(tenant, method, path, *, payload=None, params=None):
        _sent.append({"method": method, "path": path, "payload": payload})
        for pat, res in responses.items():
            if pat in path:
                return res
        return {"ok": True, "data": {}}
    return _c


def main() -> int:
    db.init_db()
    tenants.seed()

    print("— no connection is a refusal that names the fix —")
    omnisend.call = omnisend._call
    r = omnisend.import_template("baci", "T", "<p>hi</p>")
    ck("without a key it refuses and says where to connect one",
       not r["ok"] and "Accounts tab" in r["error"], r.get("error", "")[:90])

    print("\n— HTML to a reviewable draft —")
    _sent.clear()
    omnisend.call = _fake({
        "/api/email-templates/import": {"ok": True, "data": {"templateID": "tpl_1"}},
        "/api/campaigns": {"ok": True, "data": {
            "id": "camp_1", "status": "draft",
            "content": {"email": {"contentID": "cnt_1"}}}},
    })
    r = omnisend.draft_from_html(
        "baci", name="Aqua restock", subject="The Aqua pitchers are back",
        sender_name="Baci Milano", html="<p>Shatterproof acrylic.</p>",
        preheader="Shatterproof, dishwasher-safe", include_segments=["seg_1"])
    ck("a draft is created end to end", r["ok"] and r["stage"] == "done",
       str(r)[:110])
    ck("  and it is a DRAFT — nothing was sent",
       r["status"] == "draft" and "nothing has been sent" in r["note"])
    ck("  the campaign id is the top-level id, not contentID or templateID",
       r["campaign_id"] == "camp_1" and r["template_id"] == "tpl_1",
       f"{r['campaign_id']} / {r['template_id']}")

    tpl_req = next(s for s in _sent if "import" in s["path"])
    camp_req = next(s for s in _sent if s["path"] == "/api/campaigns")
    ck("the template is imported before the campaign references it",
       _sent.index(tpl_req) < _sent.index(camp_req))
    email = camp_req["payload"]["content"]["email"]
    ck("  email fields are nested under content.email, not flat on content",
       "email" in camp_req["payload"]["content"] and "subject" in email)
    ck("  subject, senderName and templateID are all present",
       {"subject", "senderName", "templateID"} <= set(email), str(sorted(email)))
    ck("  NO SENDER ADDRESS IS INVENTED — the brand's verified sender is used",
       "senderEmail" not in email and "replyToEmail" not in email,
       str(sorted(email)))
    ck("  no locale is guessed either", "language" not in camp_req["payload"])
    ck("  and no schedule — a schedule is a send with a delay on it",
       "sendingSettings" not in camp_req["payload"])
    ck("  the segment is carried",
       camp_req["payload"]["audience"]["includedSegmentIDs"] == ["seg_1"])
    ck("  type and channel are set for a regular email",
       camp_req["payload"]["type"] == "regular"
       and camp_req["payload"]["channel"] == "email")

    print("\n— sending is a separate, guarded act —")
    _sent.clear()
    r = omnisend.send_campaign("baci", "camp_1")
    ck("SENDING WITHOUT CONFIRMATION IS REFUSED", not r["ok"], str(r)[:80])
    ck("  and nothing left the building", not _sent, str(_sent))
    omnisend.call = _fake({"/send": {"ok": True, "data": {"status": "started"}}})
    r = omnisend.send_campaign("baci", "camp_1", confirm=True)
    ck("with confirmation it sends", r["ok"] and r["status"] == "started")
    ck("  by POSTing to the campaign's own send endpoint",
       _sent[-1]["path"] == "/api/campaigns/camp_1/send", _sent[-1]["path"])

    print("\n— refusals that a retry cannot fix —")
    omnisend.call = _fake({"/api/campaigns": {
        "ok": False, "needs_owner": True,
        "error": "Omnisend has no verified sender address for this brand"}})
    r = omnisend.create_draft_campaign(
        "baci", name="X", subject="S", sender_name="Baci", template_id="tpl_1")
    ck("a missing verified sender is reported, not retried around",
       not r["ok"] and r.get("needs_owner"), str(r)[:90])

    print("\n— a half-finished run says what it left behind —")
    _sent.clear()
    omnisend.call = _fake({
        "/api/email-templates/import": {"ok": True, "data": {"templateID": "tpl_9"}},
        "/api/campaigns": {"ok": False, "error": "400: content.email.subject required"},
    })
    r = omnisend.draft_from_html("baci", name="N", subject="S",
                                 sender_name="Baci", html="<p>x</p>")
    ck("the failure is reported with its stage", not r["ok"]
       and r["stage"] == "campaign", str(r)[:80])
    ck("  AND the orphaned template is named, not silently abandoned",
       "tpl_9" in r.get("orphan", ""), r.get("orphan", ""))

    print("\n— the fields Omnisend enforces even on a draft —")
    omnisend.call = _fake({})
    r = omnisend.create_draft_campaign("baci", name="N", subject="",
                                       sender_name="Baci", template_id="t")
    ck("a missing subject is caught here rather than by a 400",
       not r["ok"] and "subject" in r["error"], r.get("error", "")[:90])
    r = omnisend.import_template("baci", "N", "   ")
    ck("empty HTML is refused before a request is made",
       not r["ok"], r.get("error", "")[:60])

    omnisend.call = omnisend._call
    print()
    if _fails:
        print(f"{len(_fails)} FAILED:")
        for f in _fails:
            print(f"  - {f}")
        return 1
    print("all green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
