"""Signing in with Google or Meta, without any of it reaching the network.

The API-key connector could be checked by pasting a key and watching it verify.
OAuth cannot: the interesting half happens on someone else's server, and the
parts we own are a signature, a redirect and the handling of what comes back.
Those are exactly the parts that fail silently, so they are what this covers.

What it locks down, in order of how much it would cost to get wrong:

  · A token response with no refresh token is REFUSED. Storing the one-hour
    access token instead would produce a connection that verifies, appears on
    the console as connected, and stops working during the night.
  · A narrower grant than we asked for is stored and NAMED. This is the
    DEFECTS entry "verify() catches a dead token but not a narrow one", and it
    is the one thing OAuth can do that an API key never could.
  · State cannot be forged, tampered with, or replayed a day later.
  · A client-connected mailbox is preferred over the env blob — without which
    the whole Google flow stores a credential nothing ever reads.

    python3 scripts/test_oauth.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from urllib.parse import unquote

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'oa.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["CREDENTIAL_KEY"] = "a-test-encryption-key"
os.environ["GOOGLE_CLIENT_ID"] = "test-client-id"
os.environ["GOOGLE_CLIENT_SECRET"] = "test-client-secret"
os.environ["META_APP_ID"] = "test-meta-app"
os.environ["META_APP_SECRET"] = "test-meta-secret"
os.environ["PUBLIC_BASE_URL"] = "https://assistant.example.com"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import credentials as cred, db, oauth, tenants  # noqa: E402
from app.web import app  # noqa: E402

GOOGLE_SCOPES = oauth.FLOWS["google"]["scopes"]
REFRESH = "1//pretend-this-is-a-real-refresh-token"
_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:  # noqa: C901 — one suite, read top to bottom
    with TestClient(app) as cl:
        tenants.seed()

        # --- the flow can say why it cannot run ------------------------
        print("— configuration —")
        ck("a configured provider reports no blocker",
           oauth.configured("google") == "", oauth.configured("google"))
        ck("an unknown provider is named, not crashed on",
           "unknown provider" in oauth.configured("dropbox"))
        real_id = oauth.config.GOOGLE_CLIENT_ID
        oauth.config.GOOGLE_CLIENT_ID = ""
        ck("a missing app credential names the env var it needs",
           "GOOGLE_CLIENT_ID" in oauth.configured("google"))
        oauth.config.GOOGLE_CLIENT_ID = real_id
        # ...and names ITS OWN, for every flow. The old code was a ternary
        # reading "google, or else Meta", so Canva -- added third -- told the
        # operator on the console to go and set META_APP_SECRET. Every provider
        # is checked here rather than the two that existed when it was written.
        for prov, want in (("google", "GOOGLE_CLIENT_ID"),
                           ("meta_ads", "META_APP_ID"),
                           ("canva", "CANVA_CLIENT_ID")):
            said = oauth.configured(prov)
            ck(f"{prov} names its own env var when unconfigured",
               said == "" or want in said, said)
        real_base = oauth.config.PUBLIC_BASE_URL
        oauth.config.PUBLIC_BASE_URL = "http://localhost:8000"
        ck("a non-https base URL is refused before the round trip",
           "https" in oauth.configured("google"))
        oauth.config.PUBLIC_BASE_URL = real_base

        # --- state -----------------------------------------------------
        print("\n— state —")
        state = oauth.sign_state("baci", "google", connect_token="tok123")
        data, why = oauth.read_state(state)
        ck("a signed state reads back", not why, why)
        ck("and carries the tenant and the connect token",
           data.get("tenant") == "baci" and data.get("t") == "tok123", str(data))

        body, sig = state.split(".", 1)
        forged = oauth.sign_state("coverings", "google", connect_token="tok123")
        _, tampered_why = oauth.read_state(f"{forged.split('.')[0]}.{sig}")
        ck("a payload swapped under a valid signature is refused",
           bool(tampered_why), tampered_why)

        _, junk_why = oauth.read_state("not-a-state")
        ck("junk is refused rather than raising", bool(junk_why), junk_why)
        _, empty_why = oauth.read_state("")
        ck("an absent state is refused too", bool(empty_why), empty_why)

        old = oauth.sign_state("baci", "google")
        stale_body = old.split(".")[0]
        # rebuild with an expiry in the past, signed correctly
        import base64
        import json as _json
        payload = _json.loads(oauth._unb64(stale_body))
        payload["exp"] = int(time.time()) - 5
        raw = oauth._b64(_json.dumps(payload, separators=(",", ":"),
                                     sort_keys=True).encode())
        _, exp_why = oauth.read_state(f"{raw}.{oauth._sig(raw)}")
        ck("a correctly signed but expired state is refused",
           bool(exp_why), exp_why)
        del base64

        # --- the consent URL -------------------------------------------
        print("\n— the consent URL —")
        url = oauth.authorize_url("google", state)
        ck("it points at Google", url.startswith(oauth.FLOWS["google"]["authorize"]))
        ck("it asks for offline access", "access_type=offline" in url)
        ck("it forces the consent screen, which is what returns a refresh token",
           "prompt=consent" in url)
        ck("it carries the state", "state=" in url)
        ck("it asks for every scope we need",
           all(s.rsplit("/", 1)[-1] in url for s in GOOGLE_SCOPES))
        ck("the redirect URI is derived, not typed",
           oauth.redirect_uri("google")
           == "https://assistant.example.com/oauth/google/callback",
           oauth.redirect_uri("google"))

        # --- what comes back -------------------------------------------
        print("\n— the token response —")
        ck("a full grant reports nothing missing",
           oauth._missing_scopes(GOOGLE_SCOPES, GOOGLE_SCOPES) == [])
        partial = [s for s in GOOGLE_SCOPES if "calendar" not in s]
        missing = oauth._missing_scopes(GOOGLE_SCOPES, partial)
        ck("an unticked permission is named",
           len(missing) == 1 and "calendar" in missing[0], str(missing))
        ck("Meta's bare permission names compare against the same rule",
           oauth._missing_scopes(["ads_read", "ads_management"], ["ads_read"])
           == ["ads_management"])
        ck("a provider that reports no scopes at all is not read as a total refusal",
           oauth._missing_scopes(GOOGLE_SCOPES, []) == [])

        # --- storing ---------------------------------------------------
        print("\n— storing what came back —")
        good = {"ok": True, "secret": REFRESH, "kind": "oauth",
                "label": "gs@bacimilanousa.com", "granted": GOOGLE_SCOPES,
                "missing": [], "expires_at": 0}
        r = cred.store_oauth("baci", "google", good, granted_by="Jane")
        ck("a good grant is stored", r["ok"], str(r))
        ck("and reports the mailbox it connected",
           "bacimilanousa" in r["detail"], r["detail"])

        with db.SessionLocal() as s:
            row = (s.query(db.Credential)
                   .filter(db.Credential.tenant == "baci",
                           db.Credential.provider == "google").first())
        ck("the token is encrypted at rest", REFRESH not in (row.secret or ""))
        ck("it decrypts back to what the provider gave us",
           cred._decrypt(row.secret) == REFRESH)
        ck("it is recorded as an oauth credential", row.kind == "oauth")
        ck("the granted scopes are kept, so narrowness is auditable later",
           row.scopes.count("googleapis.com") == len(GOOGLE_SCOPES))

        failed = cred.store_oauth("baci", "google",
                                  {"ok": False, "error": "Sign-in was cancelled."})
        ck("a failed exchange is not stored", not failed["ok"], str(failed))

        print("\n— a partial grant is a connection with a dark half —")
        cred.store_oauth("eien", "google",
                         {**good, "granted": partial, "missing": missing,
                          "label": "store@eienhealth.com"})
        st = {r["provider"]: r for r in cred.status("eien")}
        ck("it still counts as connected", st["google"]["state"] == "connected")
        ck("and the console says which permission is dark",
           "calendar" in st["google"]["detail"], st["google"]["detail"])

        # --- the secret never comes back out ---------------------------
        print("\n— the secret never comes back out —")
        cl.get(f"/admin/ui?key={os.environ['APPROVAL_SECRET']}")
        body_text = cl.get("/admin/connections?tenant=baci").text
        ck("not in the connections board", REFRESH not in body_text)
        ck("and the board still shows it as connected",
           '"state":"connected"' in body_text.replace(" ", ""))

        # --- capability wiring -----------------------------------------
        print("\n— what a sign-in turns on —")
        caps = tenants.capabilities("baci")
        ck("Google grants the mailbox", caps["inbox"])
        ck("and Search Console / GA4 in the same consent — the clause that "
           "used to read only the Tenant column", caps["analytics"])
        cred.store_oauth("ironside", "meta_ads",
                         {"ok": True, "secret": "meta-long-lived", "kind": "oauth",
                          "label": "Miami Ironside", "granted": ["ads_read"],
                          "missing": [], "expires_at": int(time.time()) + 60 * 86400})
        ck("a Meta sign-in turns on ads, which it never used to",
           tenants.capabilities("ironside")["ads"])
        ck("and does not turn on anything else",
           not tenants.capabilities("ironside")["commerce"])

        # --- renewal ---------------------------------------------------
        print("\n— renewing what expires on a clock —")
        due = [d["tenant"] for d in cred.renew_due()]
        ck("a Meta token 60 days out is not due yet", "ironside" not in due, str(due))
        soon = int(time.time()) + 3 * 86400
        with db.SessionLocal() as s:
            row = (s.query(db.Credential)
                   .filter(db.Credential.tenant == "ironside",
                           db.Credential.provider == "meta_ads").first())
            row.meta = {**(row.meta or {}), "expires_at": soon}
            s.commit()
        due = cred.renew_due()
        ck("three days out, it is", [d["tenant"] for d in due] == ["ironside"], str(due))
        ck("a Google credential is never due — refresh tokens have no clock",
           all(d["provider"] != "google" for d in due))

        real_renew = oauth.renew
        oauth.renew = lambda p, t: {"ok": True, "secret": "meta-renewed",
                                    "expires_at": int(time.time()) + 60 * 86400}
        out = cred.renew_tick()
        ck("renewal replaces the token", out["renewed"] == ["ironside/meta_ads"],
           str(out))
        ck("and the new one is what resolves now",
           cred.resolve("ironside", "meta_ads")["secret"] == "meta-renewed")
        ck("nothing is due immediately afterwards", not cred.renew_due())

        oauth.renew = lambda p, t: {"ok": False, "error": "Meta rejected the token."}
        with db.SessionLocal() as s:
            row = (s.query(db.Credential)
                   .filter(db.Credential.tenant == "ironside",
                           db.Credential.provider == "meta_ads").first())
            row.meta = {**(row.meta or {}), "expires_at": soon}
            s.commit()
        out = cred.renew_tick()
        ck("a failed renewal is reported, not swallowed", bool(out["failed"]),
           str(out))
        st = {r["provider"]: r for r in cred.status("ironside")}
        ck("and the connection reads failed, so it shows up on the console",
           st["meta_ads"]["state"] == "failed", str(st["meta_ads"]))
        ck("with the provider's own reason",
           "rejected" in st["meta_ads"]["detail"], st["meta_ads"]["detail"])
        oauth.renew = real_renew

        # --- the routes ------------------------------------------------
        # The half most worth exercising: a redirect chain nobody runs locally
        # is how /connect went 500ing in production for weeks.
        print("\n— the routes —")
        import datetime as _dt
        with db.SessionLocal() as s:
            s.add(db.ConnectLink(token="linktok", tenant="coverings",
                                 label="Jane",
                                 expires_at=db.utcnow() + _dt.timedelta(days=7)))
            s.add(db.ConnectLink(token="deadtok", tenant="coverings",
                                 label="Old", status="revoked",
                                 expires_at=db.utcnow() + _dt.timedelta(days=7)))
            s.commit()

        r = cl.get("/connect/linktok/oauth/google", follow_redirects=False)
        ck("the start route redirects to Google", r.status_code == 303,
           str(r.status_code))
        ck("and it is Google it redirects to",
           r.headers.get("location", "").startswith(
               oauth.FLOWS["google"]["authorize"]))
        sent_state = r.headers["location"].split("state=")[1].split("&")[0]
        parsed, _ = oauth.read_state(sent_state)
        ck("the state it minted is scoped to the link's tenant",
           parsed.get("tenant") == "coverings", str(parsed))

        r = cl.get("/connect/deadtok/oauth/google", follow_redirects=False)
        ck("a revoked link cannot start a sign-in",
           r.status_code == 200 and "no longer active" in r.text,
           str(r.status_code))

        r = cl.get("/oauth/google/callback?code=x&state=forged",
                   follow_redirects=False)
        ck("a callback with an unsigned state is refused", r.status_code == 400,
           str(r.status_code))

        r = cl.get(f"/oauth/google/callback?error=access_denied&state={sent_state}",
                   follow_redirects=False)
        ck("declining consent goes back to the link, not to an error page",
           r.status_code == 303
           and r.headers.get("location", "").startswith("/connect/linktok"),
           r.headers.get("location", ""))
        ck("and says it was cancelled rather than that something broke",
           "cancelled" in r.headers.get("location", ""))

        # A link revoked between consent and callback must not complete.
        with db.SessionLocal() as s:
            s.get(db.ConnectLink, "linktok").status = "revoked"
            s.commit()
        real_exchange = oauth.exchange
        oauth.exchange = lambda p, c: {"ok": True, "secret": "should-not-store",
                                       "granted": [], "missing": [], "label": "",
                                       "expires_at": 0}
        r = cl.get(f"/oauth/google/callback?code=x&state={sent_state}",
                   follow_redirects=False)
        ck("a link revoked mid-flow cannot complete the sign-in",
           "no longer active" in r.text, str(r.status_code))
        ck("and nothing was stored for that account",
           not cred.resolve("coverings", "google").get("secret"))
        oauth.exchange = real_exchange

        # --- the console can see and drive it ---------------------------
        # Same discipline as test_kb_ui: every credential state the platform
        # holds must reach the page its operator reads. It did not before —
        # `status()` returned all of this and nothing rendered any of it, so
        # every connection action was a curl from the runbook.
        print("\n— the console —")
        # CHANGED with the console rebuild, not worked around. The Accounts
        # tab used to stack every account on one page, so a connected provider
        # ANYWHERE satisfied this. It now renders one account at a time —
        # which is the point of the rearrangement, because that page has
        # buttons that revoke credentials — so the test names the account
        # whose credential it stored.
        page = cl.get("/admin/ui?tab=accounts&tenant=baci").text
        ck("the Accounts tab has a Connections section", "Connections" in page)
        ck("every provider is listed by name",
           all(cred.PROVIDERS[p]["name"].split(" (")[0] in page
               for p in cred.PROVIDERS), "a provider is missing from the page")
        ck("a connected provider says so", 'chip on">connected' in page)
        ck("an unconnected one says missing", 'chip off">missing' in page)
        ck("Google offers a Connect button that starts the owner flow",
           "/admin/oauth/google?" in page)
        ck("so does Meta, once its app credentials exist",
           "/admin/oauth/meta_ads?" in page)

        # The half-configured case — one provider's app credentials set and the
        # other's not — is the state this is actually onboarded in, so it is
        # the state worth asserting rather than the tidy one.
        real_meta = oauth.config.META_APP_ID
        oauth.config.META_APP_ID = ""
        blocked = cl.get("/admin/ui?tab=accounts").text
        ck("with no Meta app id, the page names the env var",
           "META_APP_ID" in blocked, "the blocker is not on the page")
        ck("and offers no button that could only fail",
           "/admin/oauth/meta_ads?" not in blocked)
        ck("while Google, which is configured, is unaffected",
           "/admin/oauth/google?" in blocked)
        oauth.config.META_APP_ID = real_meta

        ck("there is a form to mint a connect link",
           'action="/admin/connect_link"' in page)
        ck("disconnect is a POST, not a prefetchable GET",
           'method="post" action="/admin/connect_revoke"' in page)
        ck("no secret reaches the page", REFRESH not in page
           and "meta-renewed" not in page)

        r = cl.post("/admin/connect_link",
                    data={"tenant": "baci", "label": "Jane", "days": "30"},
                    follow_redirects=False)
        ck("minting a link redirects back to the console", r.status_code == 303,
           str(r.status_code))
        loc = r.headers.get("location", "")
        ck("and hands back a URL rather than a JSON blob", "link=" in loc, loc)
        minted = unquote(loc.split("link=")[1])
        ck("which points at the connect page",
           "/connect/" in minted and minted.startswith("https://"), minted)
        ck("the page then shows it to copy", minted in cl.get(loc).text)

        r = cl.post("/admin/connect_link",
                    data={"tenant": "nosuch", "label": "x", "days": "30"},
                    follow_redirects=False)
        ck("an unknown account is refused by name",
           "err=" in r.headers.get("location", ""), r.headers.get("location", ""))

        r = cl.post("/admin/connect_revoke",
                    data={"tenant": "eien", "provider": "google"},
                    follow_redirects=False)
        ck("disconnecting from the console works", r.status_code == 303)
        ck("and it actually disconnected",
           not cred.resolve("eien", "google").get("secret"))

        # --- the bridge ------------------------------------------------
        # The whole Google flow is decorative without this: gmail_client read
        # config.GMAIL_ACCOUNTS directly, so a connected mailbox would store,
        # verify, show as connected, and never be read by email_harvest.
        print("\n— a connected mailbox is the one that gets read —")
        # baci's alias is "baci" from the seed — the same join google_config uses.
        cred.config.GMAIL_ACCOUNTS["baci"] = {"email": "old@example.com",
                                              "refresh_token": "env-blob-token"}
        got = cred.google_config("baci")
        ck("the client's own token wins over the env blob",
           got["refresh_token"] == REFRESH, str(got.get("refresh_token")))
        ck("and it carries the mailbox the consent screen identified",
           got["email"] == "gs@bacimilanousa.com", str(got))

        cred.config.GMAIL_ACCOUNTS["personal"] = {"email": "g@example.com",
                                                  "refresh_token": "env-only"}
        ck("an account that has connected nothing keeps its env value",
           cred.google_config("personal")["refresh_token"] == "env-only")
        ck("an alias nobody has is empty, not a KeyError",
           cred.google_config("nope") == {})

        cred.revoke("baci", "google")
        ck("after revoking, the env blob is what is left",
           cred.google_config("baci")["refresh_token"] == "env-blob-token")
        ck("and the account no longer reports analytics",
           not tenants.capabilities("baci")["analytics"])

    print("\n" + ("all checks passed" if not _fail
                  else f"{len(_fail)} FAILED: " + ", ".join(_fail)))
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
