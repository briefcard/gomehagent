"""The Constant Contact send path, driven against a stubbed transport.

Omnisend had the only ESP adapter, so a client on Constant Contact could
connect it, switch on `esp`, watch `campaign_email` pass readiness and have
nowhere to put an email.

The API cannot be reached from here, so `constant_contact.call` is replaced and
what is checked is the REQUEST this module builds and the decisions it makes:
that a campaign is drafted and never sent, that sending needs an explicit
confirmation, that a from-address is READ from the account rather than
invented, and that every error the API reports survives to the caller.

Run: python3 scripts/test_constant_contact.py
"""
import os
import sys
import tempfile

_tmp = os.path.join(tempfile.mkdtemp(), "cc.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}"
os.environ["APPROVAL_SECRET"] = "test-secret"
os.environ["CREDENTIAL_KEY"] = "test-key"
os.environ["PUBLIC_BASE_URL"] = "https://assistant.example.com"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import constant_contact as cc, credentials as cred, db, oauth, tenants  # noqa: E402

_fails: list[str] = []
_sent: list[dict] = []


def ck(label: str, cond: bool, detail: str = "") -> None:
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fails.append(label)


def _fake(responses: dict):
    def _c(tenant, method, path, *, payload=None, params=None):
        _sent.append({"method": method, "path": path, "payload": payload})
        for pat, res in responses.items():
            if pat in path:
                return res
        return {"ok": True, "data": {}}
    return _c


ONE_SENDER = {"ok": True, "data": [
    {"email_address": "hello@acme.com", "confirm_status": "CONFIRMED"}]}
TWO_SENDERS = {"ok": True, "data": [
    {"email_address": "hello@acme.com", "confirm_status": "CONFIRMED"},
    {"email_address": "events@acme.com", "confirm_status": "CONFIRMED"}]}
CREATED = {"ok": True, "data": {
    "campaign_id": "camp-1", "current_status": "DRAFT",
    "campaign_activities": [{"campaign_activity_id": "act-1",
                             "role": "primary_email"}]}}


def main() -> int:  # noqa: C901 — one suite, read top to bottom
    db.init_db()
    tenants.seed()

    print("— no connection is a refusal that names the fix —")
    cc.call = cc._call
    r = cc.senders("baci")
    ck("without a connection it refuses and says where to make one",
       not r["ok"] and "Accounts tab" in r["error"], r.get("error", "")[:80])

    print("\n— the provider is offered, and says what blocks it —")
    ck("Constant Contact is a connectable provider",
       "constant_contact" in cred.PROVIDERS)
    ck("and it grants esp, like the others",
       cred.GRANTS["constant_contact"] == ("esp",))
    ck("its blocker names ITS OWN env vars",
       "CONSTANT_CONTACT_CLIENT_ID" in oauth.configured("constant_contact"),
       oauth.configured("constant_contact"))
    ck("offline_access is requested, or the token dies the same day",
       "offline_access" in oauth.FLOWS["constant_contact"]["scopes"])
    ck("the token endpoint is called with Basic auth",
       oauth.FLOWS["constant_contact"]["token_style"] == "basic_auth")

    print("\n— HTML to a reviewable draft —")
    _sent.clear()
    cc.call = _fake({"/account/emails": ONE_SENDER, "/emails": CREATED})
    r = cc.draft_from_html("baci", name="August", subject="Hello",
                           html="<p>hi</p>", from_name="Acme")
    ck("a draft is created", r["ok"] and r["campaign_id"] == "camp-1")
    ck("  and it comes back as a DRAFT, not a send", r["status"] == "DRAFT")
    ck("  with the activity id the schedule call will need",
       r["activity_id"] == "act-1")
    create = next(s for s in _sent if s["path"] == "/emails")
    act = create["payload"]["email_campaign_activities"][0]
    ck("the activity is the primary email", act["role"] == "primary_email")
    ck("format_type is 5 — the only kind V3 can create",
       act["format_type"] == 5)
    ck("the sender is the account's CONFIRMED address, not one we made up",
       act["from_email"] == "hello@acme.com")
    ck("reply-to defaults to the same address rather than being left empty",
       act["reply_to_email"] == "hello@acme.com")
    ck("no postal address is invented when none was given",
       "physical_address_in_footer" not in act,
       "the account's own footer address applies; a wrong one is the field "
       "CAN-SPAM is about")
    ck("NOTHING was scheduled as a side effect of drafting",
       not any("schedules" in s["path"] for s in _sent))

    print("\n— a sender is never guessed —")
    cc.call = _fake({"/account/emails": TWO_SENDERS, "/emails": CREATED})
    r = cc.draft_from_html("baci", name="A", subject="S", html="<p>x</p>",
                           from_name="Acme")
    ck("with two confirmed addresses it refuses and lists them",
       not r["ok"] and "events@acme.com" in r["error"], r.get("error", "")[:90])
    r = cc.draft_from_html("baci", name="A", subject="S", html="<p>x</p>",
                           from_name="Acme", from_email="events@acme.com")
    ck("  and accepts one that is named and confirmed", r["ok"])
    r = cc.draft_from_html("baci", name="A", subject="S", html="<p>x</p>",
                           from_name="Acme", from_email="nope@acme.com")
    ck("an unconfirmed address is refused BEFORE the campaign is created",
       not r["ok"] and "not a confirmed address" in r["error"])

    cc.call = _fake({"/account/emails": {"ok": True, "data": [
        {"email_address": "pending@acme.com", "confirm_status": "UNCONFIRMED"}]}})
    r = cc.draft_from_html("baci", name="A", subject="S", html="<p>x</p>",
                           from_name="Acme")
    ck("an account with nothing confirmed says which address is waiting",
       not r["ok"] and "pending@acme.com" in r["error"], r.get("error", "")[:90])

    print("\n— sending is a separate, confirmed act —")
    _sent.clear()
    cc.call = _fake({})
    r = cc.send_campaign("baci", "act-1")
    ck("send without confirmation is REFUSED", not r["ok"])
    ck("  and the refusal says it is irreversible",
       "irreversible" in r["error"])
    ck("  and nothing was sent", not _sent)
    cc.send_campaign("baci", "act-1", confirm=True)
    ck("with confirmation it schedules",
       _sent[-1]["path"] == "/emails/activities/act-1/schedules")
    ck("  and '0' is how Constant Contact is told to send now",
       _sent[-1]["payload"] == {"scheduled_date": "0"})

    print("\n— recipients are attached before a send can work —")
    _sent.clear()
    r = cc.set_recipients("baci", "act-1", [])
    ck("no list is a refusal, not an empty send", not r["ok"] and not _sent)
    cc.set_recipients("baci", "act-1", ["list-9"])
    ck("a list is attached with a PUT to the activity",
       _sent[-1]["method"] == "PUT"
       and _sent[-1]["payload"] == {"contact_list_ids": ["list-9"]})

    print("\n— every error the API reports survives —")
    class _R:
        status_code = 400
        content = b"x"
        text = ""

        @staticmethod
        def json():
            return [{"error_key": "a", "error_message": "subject is required"},
                    {"error_key": "b", "error_message": "html_content missing"}]
    said = cc._error_text(_R())
    ck("all of them, not just the first",
       "subject is required" in said and "html_content missing" in said,
       "one field revealed per attempt is three round trips to fix one draft")

    print("\n— an empty draft is caught before any call —")
    _sent.clear()
    r = cc.draft_from_html("baci", name="A", subject="S", html="   ",
                           from_name="Acme")
    ck("nothing to send is refused locally", not r["ok"] and not _sent)

    print()
    if _fails:
        print(f"{len(_fails)} FAILED:")
        for f in _fails:
            print(f"  - {f}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
