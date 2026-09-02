"""Klaviyo drafts, and cannot send.

Owner, 2026-09-02, testing the email system: *"Approved — but the push to the
ESP failed: ironside is connected to Klaviyo, but its send adapter is not built
yet."* The message was right — `esp.PROFILES` named an adapter module that did
not exist, and `esp.backend` said so by name rather than returning a None the
generator would trip over three calls later.

IT CANNOT SEND, AND THE ABSENCE IS THE GUARANTEE. Owner, 2026-08-31: *"Leave it
human, in the ESP."* There is no `send_campaign` in the module — not an
unfinished one, not a guarded one. Code that cannot send cannot send by
accident, and an adapter that could would be one config flag from a send nobody
reviewed.

THE LIVE ROUND TRIP IS UNVERIFIED and this suite does not pretend otherwise.
What is tested: the request shapes, the auth header, every refusal path, the
orphan reporting, and the draft-only guarantee. What is NOT: whether Klaviyo
accepts these exact bodies, because no live account is connected here. The
first real push is the proof.

Run: python3 scripts/test_klaviyo.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'kl.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import credentials, db, esp, klaviyo, tenants  # noqa: E402

_fail = []
SENT = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _connect(tenant, secret="pk_live_test"):
    with db.SessionLocal() as s:
        s.query(db.Credential).filter(db.Credential.tenant == tenant,
                                      db.Credential.provider == "klaviyo").delete()
        s.add(db.Credential(tenant=tenant, provider="klaviyo", site="",
                            kind="api_key", secret=credentials._encrypt(secret),
                            meta={}, scopes="", status="active",
                            granted_at=db.utcnow()))
        s.commit()


def _stub(script):
    """Replace the one seam every call goes through. `script` maps
    (method, path) -> response dict; anything unscripted is a failure the
    test wants to see rather than a silent default."""
    SENT.clear()

    def _c(tenant, method, path, *, payload=None, params=None):
        SENT.append({"method": method, "path": path, "payload": payload,
                     "params": params})
        for (m, p), resp in script.items():
            if m == method and path.startswith(p):
                return resp
        return {"ok": False, "error": f"unscripted call {method} {path}"}
    klaviyo.call = _c


OK_TPL = {"ok": True, "data": {"data": {"id": "TPL1"}}}
OK_CAMP = {"ok": True, "data": {"data": {
    "id": "CAMP1",
    "relationships": {"campaign-messages": {"data": [{"id": "MSG1"}]}}}}}
OK_ATTACH = {"ok": True, "data": {}}


def main() -> int:
    db.init_db()
    tenants.seed()

    print("— the adapter exists, and `esp.backend` finds it —")
    _connect("baci")
    with db.SessionLocal() as s:
        s.get(db.Tenant, "baci").esp = {"provider": "klaviyo"}
        s.commit()
    mod, why = esp.backend("baci")
    ck("it resolves to a module", mod is not None, why or "")
    ck("  and it is the Klaviyo one",
       getattr(mod, "__name__", "").endswith("klaviyo"),
       getattr(mod, "__name__", ""))
    ck("  the refusal the owner saw is gone",
       "send adapter is not built" not in (why or ""),
       why or "no refusal")

    print()
    print("— IT CANNOT SEND. The absence is the guarantee —")
    ck("no send function exists at all",
       not hasattr(klaviyo, "send_campaign") and not hasattr(klaviyo, "send"),
       "not an unfinished one and not a guarded one — code that cannot send "
       "cannot send by accident")
    src = __import__("pathlib").Path(klaviyo.__file__).read_text()
    ck("  and nothing posts a send job",
       "send-job" not in src and "send_job" not in src,
       "a send job is the only thing that makes a Klaviyo campaign go out")
    # THE PAYLOAD, NOT THE SOURCE. Grepping the module for "send_strategy"
    # found it in the comment explaining its absence — a source assertion
    # failing on the prose that documents the behaviour it is checking. What
    # matters is what goes on the wire.
    _stub({("POST", "/templates/"): OK_TPL,
           ("POST", "/campaigns/"): OK_CAMP,
           ("POST", "/campaign-message-assign-template/"): OK_ATTACH})
    klaviyo.draft_from_html("baci", name="n", subject="s", sender_name="B",
                            html="<p>x</p>", include_segments=["SEG1"])
    _bodies = str([c["payload"] for c in SENT])
    ck("  nor sets a send strategy on the wire",
       "send_strategy" not in _bodies and "send-strategy" not in _bodies,
       "its absence is what leaves the campaign a draft")
    ck("  and nothing posts to a send endpoint",
       not any("send" in c["path"] for c in SENT),
       str([c["path"] for c in SENT]))

    print()
    print("— a draft is template, then campaign, then attach —")
    _stub({("POST", "/templates/"): OK_TPL,
           ("POST", "/campaigns/"): OK_CAMP,
           ("POST", "/campaign-message-assign-template/"): OK_ATTACH})
    got = klaviyo.draft_from_html(
        "baci", name="Autumn note", subject="A note about your table",
        sender_name="Baci", html="<h1>Hi</h1>", preheader="Inside",
        include_segments=["SEG1"])
    ck("it reports done", got.get("ok") and got.get("stage") == "done",
       str(got)[:110])
    ck("  carrying both ids", got.get("campaign_id") == "CAMP1"
       and got.get("template_id") == "TPL1", str(got)[:110])
    ck("  in three calls, in that order",
       [c["path"] for c in SENT] == ["/templates/", "/campaigns/",
                                     "/campaign-message-assign-template/"],
       str([c["path"] for c in SENT]))
    body = SENT[1]["payload"]["data"]["attributes"]
    ck("  the campaign names its audience",
       body["audiences"]["included"] == ["SEG1"], str(body["audiences"]))
    ck("  and carries the subject and preheader the owner reviewed",
       body["campaign-messages"]["data"][0]["attributes"]["definition"]
       ["content"]["subject"] == "A note about your table",
       str(body)[:120])
    ck("  the HTML goes in the TEMPLATE, not the campaign",
       "<h1>Hi</h1>" in str(SENT[0]["payload"])
       and "<h1>Hi</h1>" not in str(SENT[1]["payload"]),
       "a campaign body Klaviyo cannot render is a draft nobody can open")

    print()
    print("— no audience is refused, never defaulted to everybody —")
    _stub({("POST", "/templates/"): OK_TPL})
    none = klaviyo.draft_from_html(
        "baci", name="n", subject="s", sender_name="B", html="<p>x</p>",
        include_segments=[])
    ck("it refuses by name",
       not none.get("ok") and "no audience" in none.get("error", ""),
       none.get("error", "")[:90])
    ck("  and says why a default would be wrong",
       "not a default worth having" in none.get("error", ""),
       "sending to everyone because nobody chose is the one mistake an ESP "
       "cannot undo")
    ck("  no campaign was attempted",
       [c["path"] for c in SENT] == ["/templates/"],
       str([c["path"] for c in SENT]))

    print()
    print("— a half-made draft is REPORTED, not swallowed —")
    _stub({("POST", "/templates/"): OK_TPL,
           ("POST", "/campaigns/"): {"ok": False, "error": "400: bad audience"}})
    half = klaviyo.draft_from_html(
        "baci", name="n", subject="s", sender_name="B", html="<p>x</p>",
        include_segments=["SEG1"])
    ck("it names the stage that failed", half.get("stage") == "campaign",
       str(half)[:100])
    ck("  and the orphan it left behind",
       "TPL1" in half.get("orphan", ""),
       "a template with no campaign is a real thing somebody has to clean up "
       "in the account; returning only the error hides it")
    _stub({("POST", "/templates/"): OK_TPL,
           ("POST", "/campaigns/"): OK_CAMP,
           ("POST", "/campaign-message-assign-template/"):
               {"ok": False, "error": "400: no template"}})
    noattach = klaviyo.draft_from_html(
        "baci", name="n", subject="s", sender_name="B", html="<p>x</p>",
        include_segments=["SEG1"])
    ck("a campaign with no HTML attached says so",
       noattach.get("stage") == "attach"
       and "no HTML attached" in noattach.get("orphan", ""),
       str(noattach)[:120])

    print()
    print("— and the orphan reaches the person who must clean it up —")
    # It was computed and rendered nowhere: the piping audit flagged
    # `klaviyo.draft_from_html.orphan` as a warning-shaped key no UI file
    # mentions. Worse, the message it sat behind claimed "Nothing is in the
    # platform" — false whenever a template imported and the campaign did
    # not, and a retry then makes a second one.
    import inspect as _i
    from app import approvals as _ap
    _src = _i.getsource(_ap)
    ck("the failure message reads the orphan",
       'got.get("orphan")' in _src,
       "the adapters' own name for a half-made draft")
    ck("  and stops claiming nothing is in the platform when there is",
       "LEFT BEHIND IN THE PLATFORM" in _src
       and _src.count("Nothing is in the platform") == 1,
       "the sentence survives for the case where it is true")

    print()
    print("— the API's own words survive —")
    klaviyo.call = klaviyo._call
    with db.SessionLocal() as s:
        s.query(db.Credential).filter(db.Credential.tenant == "wm").delete()
        s.commit()
    ck("an unconnected account is refused before any call",
       "no Klaviyo connection" in klaviyo._key("wm")[1],
       klaviyo._key("wm")[1][:80])
    ck("the revision header is pinned, not floating",
       bool(klaviyo.REVISION) and klaviyo.REVISION[0].isdigit(),
       f"{klaviyo.REVISION} — Klaviyo versions by date and rejects a call "
       f"with none; following the newest breaks on a day nobody deployed")

    print()
    print("PASS" if not _fail else f"FAILED: {len(_fail)}")
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
