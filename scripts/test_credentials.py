"""A client connects their own accounts, and the secret never comes back out.

Credentials used to exist only as env-group JSON that Gomeh pasted in by hand,
which is the actual ceiling on how many clients this can carry. This is the
replacement: a scoped connect link, verified on submit, encrypted at rest.

The properties worth locking down are mostly negative — what must NOT happen:
a secret must never appear in a rendered page or an admin response, a failing
credential must never be stored, and an account nobody has connected must keep
running on the env value it has always used.

    python3 scripts/test_credentials.py
"""
from __future__ import annotations

import datetime as dt
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'cr.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["CREDENTIAL_KEY"] = "a-test-encryption-key"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import credentials as cred, db, tenants  # noqa: E402
from app.web import app  # noqa: E402

SECRET_VALUE = "shpat_pretend_this_is_a_real_token"
_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    with TestClient(app) as cl:
        tenants.seed()

        # --- encryption round trip ------------------------------------
        print("— encryption —")
        blob = cred._encrypt(SECRET_VALUE)
        ck("ciphertext is not the plaintext", blob != SECRET_VALUE)
        ck("plaintext does not appear in it", SECRET_VALUE not in blob)
        ck("it decrypts back", cred._decrypt(blob) == SECRET_VALUE)
        ck("a bad blob returns empty, never raises", cred._decrypt("garbage") == "")

        # --- what a person actually types -------------------------------
        # Every case here was measured against the live APIs on 2026-08-13 and
        # every one of them failed, most with an exception class name on the
        # client's screen. A wrong value nobody can act on is the same defect
        # as a silent one.
        print("\n— normalising what a client pastes —")
        norm, why = cred._normalize_meta(
            "shopify", {"domain": "https://769684-2.myshopify.com"})
        ck("a domain pasted from the browser bar loses its scheme",
           not why and norm["domain"] == "769684-2.myshopify.com", str(norm))
        norm, why = cred._normalize_meta(
            "shopify", {"domain": "769684-2.myshopify.com/admin/"})
        ck("and any path or trailing slash",
           not why and norm["domain"] == "769684-2.myshopify.com", str(norm))
        norm, why = cred._normalize_meta(
            "shopify", {"domain": "769684-2.MyShopify.com"})
        ck("case does not matter", norm["domain"] == "769684-2.myshopify.com")

        # The address a merchant is ACTUALLY looking at while reading our
        # instructions. Stripping the path left `admin.shopify.com`, which was
        # then told it was "the storefront domain" and sent to Settings →
        # Domains — wrong on both counts, with the handle we needed sitting in
        # the path we had just thrown away.
        norm, why = cred._normalize_meta(
            "shopify", {"domain": "https://admin.shopify.com/store/baci-milano-usa"})
        ck("the admin URL from the browser bar is understood, not refused",
           not why and norm["domain"] == "baci-milano-usa.myshopify.com", str(norm))
        norm, why = cred._normalize_meta(
            "shopify", {"domain": "admin.shopify.com/store/acme/products/123"})
        ck("  even with a deeper path on it",
           not why and norm["domain"] == "acme.myshopify.com", str(norm))
        _, why = cred._normalize_meta("shopify", {"domain": "admin.shopify.com"})
        ck("  and the bare admin host asks for the whole address",
           bool(why) and "store/your-handle" in why, why)

        # A Shopify custom app shows FOUR credentials on one screen and only
        # one of them works. "they begin with shpat_" is true and nearly
        # useless — a person who picked the wrong one reads it and picks
        # another wrong one. The owner hit this with the API secret key.
        bad = cred.store("baci", "shopify", "shpss_deadbeef",
                         meta={"domain": "acme.myshopify.com"})
        ck("the API secret key is named, not just refused",
           not bad["ok"] and "API secret key" in bad["error"], bad.get("error", ""))
        ck("  and the refusal says where the real one is",
           "Admin API access token" in bad["error"])
        ck("  and that it is revealed only once",
           "ONCE" in bad["error"],
           "a token that cannot be re-revealed is the next question they hit")
        for tok, expect in (("shptka_x", "Theme access token"),
                            ("shppa_x", "private-app password")):
            r = cred.store("baci", "shopify", tok,
                           meta={"domain": "acme.myshopify.com"})
            ck(f"  {tok.split('_')[0]}_ is recognised too", expect in r["error"],
               r.get("error", ""))
        unknown = cred.store("baci", "shopify", "nonsense",
                             meta={"domain": "acme.myshopify.com"})
        ck("  and an unrecognised string still names the right prefix",
           "shpat_" in unknown["error"], unknown.get("error", ""))
        ck("  while nothing was stored either way",
           not cred.resolve("baci", "shopify").get("secret"),
           "a credential that failed the shape check must never reach the table")

        _, why = cred._normalize_meta("shopify", {"domain": "bacimilanousa.com"})
        ck("the storefront domain — the one a merchant knows — is refused",
           bool(why), "it was accepted")
        ck("and the refusal says where to find the right one",
           "myshopify.com" in why and "Settings" in why, why)
        ck("including that it may be a number, because Baci's is",
           "number" in why, why)

        norm, _ = cred._normalize_meta("wordpress", {"site": "marketingthatworks.co"})
        ck("a WordPress site with no scheme gets one",
           norm["site"] == "https://marketingthatworks.co", str(norm))
        norm, _ = cred._normalize_meta("wordpress",
                                       {"site": "https://acme.com/blog/"})
        ck("and loses its trailing slash", norm["site"] == "https://acme.com/blog",
           str(norm))
        ck("a provider needing no normalisation is untouched",
           cred._normalize_meta("omnisend", {}) == ({}, ""))

        # --- storing without a live probe ------------------------------
        # _probe would call Shopify; stub it so the test stays offline.
        print("\n— storing —")
        real_probe = cred._probe
        cred._probe = lambda p, s, m: {"ok": True, "detail": "Acme Store"}
        r = cred.store("baci", "shopify", SECRET_VALUE,
                       meta={"domain": "acme.myshopify.com"}, granted_by="Jane")
        ck("a verified credential is stored", r["ok"], str(r))

        with db.SessionLocal() as s:
            row = s.query(db.Credential).filter(
                db.Credential.tenant == "baci").first()
            ck("stored encrypted, not in the clear", row.secret != SECRET_VALUE)
            ck("and the plaintext is nowhere in the row",
               SECRET_VALUE not in (row.secret or "") + str(row.meta))
            ck("granted_by is recorded", row.granted_by == "Jane")
            ck("last_verified is set", row.last_verified is not None)

        ck("resolve returns the decrypted value to code",
           cred.resolve("baci", "shopify")["secret"] == SECRET_VALUE)
        ck("and marks it as the client's", cred.resolve("baci", "shopify")["source"] == "client")

        # --- connected is a claim, and claims go stale -------------------
        print("\n— re-checking a key that was only ever verified once —")
        cred._probe = lambda p, s, m: {"ok": True, "detail": "Acme Store"}
        r = cred.recheck("baci", "shopify")
        ck("a key that still works re-verifies", r["ok"] and r["checked"], str(r))

        cred._probe = lambda p, s, m: {"ok": False,
                                       "error": "Shopify rejected that token."}
        r = cred.recheck("baci", "shopify")
        ck("a key rotated at the provider fails the re-check", not r["ok"], str(r))
        st = {x["provider"]: x for x in cred.status("baci")}
        ck("and the console stops calling it connected",
           st["shopify"]["state"] == "not verifying", str(st["shopify"]))
        ck("with the provider's own reason",
           "rejected" in st["shopify"]["detail"], st["shopify"]["detail"])
        # The important negative. resolve() returns only active rows and falls
        # through to the env blob otherwise, so demoting a credential on a
        # failed probe would silently swap which one is in use — on one network
        # blip, mid-flight, with nothing downstream questioning it.
        ck("but the client's credential is STILL the one in use",
           cred.resolve("baci", "shopify").get("secret") == SECRET_VALUE,
           "a failed probe silently changed which credential resolves")
        ck("and it is still attributed to the client, not the env group",
           cred.resolve("baci", "shopify").get("source") == "client")

        cred._probe = lambda p, s, m: {"ok": True, "detail": "Acme Store"}
        ck("and it recovers when the provider does",
           cred.recheck("baci", "shopify")["ok"])

        r = cred.recheck("baci", "google")
        ck("an oauth credential is skipped, not marked broken",
           not r["ok"] and not r["checked"], str(r))
        ck("and says how to re-verify it instead",
           "reconnect" in r["error"].lower(), r["error"])
        r = cred.recheck("coverings", "shopify")
        ck("re-checking nothing says so rather than failing a row",
           not r["checked"] and "Nothing stored" in r["error"], str(r))

        # --- what must never be stored ---------------------------------
        print("\n— refusing —")
        cred._probe = lambda p, s, m: {"ok": False, "error": "Shopify rejected that token."}
        before = cred.resolve("eien", "shopify").get("secret", "")
        r = cred.store("eien", "shopify", "shpat_wrong",
                       meta={"domain": "x.myshopify.com"})
        ck("a credential that fails its probe is refused", not r["ok"], str(r))
        ck("and nothing was written",
           cred.resolve("eien", "shopify").get("secret", "") == before)

        cred._probe = lambda p, s, m: {"ok": True, "detail": ""}
        ck("a blank secret is refused",
           not cred.store("eien", "shopify", "   ",
                          meta={"domain": "x.myshopify.com"})["ok"])
        ck("a missing required field is refused",
           not cred.store("eien", "shopify", SECRET_VALUE, meta={})["ok"])
        ck("an obviously wrong format is refused before any network call",
           not cred.store("eien", "shopify", "not-a-shopify-token",
                          meta={"domain": "x.myshopify.com"})["ok"])
        ck("an unknown provider is refused",
           not cred.store("eien", "nosuchthing", "x")["ok"])
        cred._probe = real_probe

        # --- the secret must not escape --------------------------------
        print("\n— the secret never comes back out —")
        rows = cred.status("baci")
        ck("status() reports connected", any(
            r["provider"] == "shopify" and r["state"] == "connected" for r in rows))
        ck("status() contains no secret", SECRET_VALUE not in str(rows))

        r = cl.get("/admin/connections", params={"key": "s3cret", "tenant": "baci"})
        ck("the admin board renders", r.status_code == 200)
        ck("and leaks no secret", SECRET_VALUE not in r.text)

        # --- the client-facing page ------------------------------------
        print("\n— the connect link —")
        r = cl.get("/admin/connect_new",
                   params={"key": "s3cret", "tenant": "baci", "label": "Jane"})
        token = r.json()["url"].rsplit("/", 1)[-1]
        ck("a link is minted", bool(token))

        page = cl.get(f"/connect/{token}")
        ck("the client page renders", page.status_code == 200)
        ck("it never echoes the stored secret", SECRET_VALUE not in page.text)
        ck("it needs no admin key", "key=" not in page.text or "s3cret" not in page.text)
        ck("the secret field is a password input", 'type="password"' in page.text)
        ck("and the form POSTs, so keys stay out of the URL",
           'method="post"' in page.text)

        # --- submitting through the page -------------------------------
        cred._probe = lambda p, s, m: {"ok": True, "detail": "Acme Store"}
        r = cl.post(f"/connect/{token}",
                    data={"provider": "omnisend", "secret": "omni-key-123"},
                    follow_redirects=False)
        ck("a submit redirects rather than rendering the value",
           r.status_code == 303, f"status {r.status_code}")
        ck("omnisend is now connected",
           cred.resolve("baci", "omnisend")["secret"] == "omni-key-123")

        r = cl.post(f"/connect/{token}",
                    data={"provider": "omnisend", "secret": "bad"},
                    follow_redirects=False)
        loc = r.headers.get("location", "")
        ck("a rejected submit reports the error in the redirect", "err=" in loc or "ok=" in loc)

        with db.SessionLocal() as s:
            link = s.get(db.ConnectLink, token)
            ck("use is recorded on the link", link.last_used_at is not None)
        cred._probe = real_probe

        # --- a dead link ------------------------------------------------
        print("\n— an expired or revoked link —")
        with db.SessionLocal() as s:
            s.add(db.ConnectLink(token="dead", tenant="baci", status="revoked"))
            s.add(db.ConnectLink(token="old", tenant="baci",
                                 expires_at=db.utcnow() - dt.timedelta(days=1)))
            s.commit()
        ck("a revoked link is refused",
           "no longer active" in cl.get("/connect/dead").text)
        ck("an expired link is refused", "expired" in cl.get("/connect/old").text)
        ck("a bogus token is refused",
           "no longer active" in cl.get("/connect/nope").text)

        # --- the env fallback -------------------------------------------
        print("\n— accounts nobody has connected —")
        ck("an unconnected account resolves to nothing here",
           cred.resolve("coverings", "shopify").get("secret", "") == "")
        ck("and its status reads missing",
           any(r["provider"] == "shopify" and r["state"] == "missing"
               for r in cred.status("coverings")))
        ck("shopify_config falls through to the env blob when unconnected",
           cred.shopify_config("nosuchstore") == {})
        with db.SessionLocal() as s:
            t = s.get(db.Tenant, "baci")
            store_key = t.shopify_store
        if store_key:
            cfg = cred.shopify_config(store_key)
            ck("a connected client's token is what the store code now gets",
               cfg.get("token") == SECRET_VALUE, str(list(cfg)))

        # --- declared is not connected -------------------------------------
        #
        # `capabilities()` promised "the tenant names it AND the credential
        # exists" and delivered that for two of eight. `esp`, `cms`, `ads` and
        # `crm` read a key out of the Tenant's own JSON column — and
        # `credential_ref` ("OMNISEND_BACI") is dereferenced nowhere, with no
        # Omnisend credential anywhere in the codebase. Both directions are
        # pinned here: a declaration must not read as wired, and a real env
        # registry entry must not stop reading as wired.
        print("\n— a declaration is not a connection —")
        # Disconnect what this fixture genuinely connected earlier, so what is
        # left is the declaration alone. Omnisend was wired through the connect
        # page above and `esp` was correctly reading True off a real credential.
        cred.revoke("baci", "shopify")
        cred.revoke("baci", "omnisend")
        ck("with omnisend connected, esp was wired for a real reason —"
           " it is only the declaration that must not count",
           "omnisend" not in cred.connected_providers("baci"))

        with db.SessionLocal() as s:
            t = s.get(db.Tenant, "baci")
            ck("baci still DECLARES an esp", bool((t.esp or {}).get("provider")),
               str(t.esp))
        ck("but esp does not read as wired, because no credential exists",
           not tenants.capabilities("baci")["esp"])
        ck("  and it is named as needing connecting, not silently absent",
           tenants.capability_detail("baci")["esp"]["needs_connecting"])
        ck("a credential_ref is still dereferenced nowhere",
           not cred.resolve("baci", "omnisend").get("secret"))

        with db.SessionLocal() as s:
            cv = s.get(db.Tenant, "coverings")
            declares_cms = bool((cv.cms or {}).get("platform"))
        ck("coverings declares a cms with an empty creds_key", declares_cms)
        ck("  and it does not read as wired either",
           not tenants.capabilities("coverings")["cms"])

        # The other direction, which matters just as much: membership in the
        # env registry IS the credential. Testing the shape of the secret
        # instead would report a live inbox as disconnected and strip the agent
        # of its tools — the same error pointed the other way.
        from app import config as _cfg
        _cfg.GMAIL_ACCOUNTS.setdefault("baci", {"email": "b@example.com"})
        ck("an env-group inbox still reads as wired",
           tenants.capabilities("baci")["inbox"])
        ck("  and says it came from the env group",
           tenants.capability_detail("baci")["inbox"]["via"] == "env:google",
           tenants.capability_detail("baci")["inbox"]["via"])
        ck("an env inbox does NOT grant analytics — those scopes are unverified",
           not tenants.capabilities("baci")["analytics"])

        # A CMS that IS the store needs no second credential. The platform name
        # only says which provider to look for; the grant still requires that
        # provider to resolve, which is what keeps this from being the
        # declaration-counts defect wearing a different hat.
        _had_store = "baci" in _cfg.SHOPIFY_STORES
        _cfg.SHOPIFY_STORES.setdefault("baci", {"domain": "b.myshopify.com",
                                                "token": "shpat_x"})
        try:
            ck("baci's cms is wired by the Shopify credential it already has",
               tenants.capabilities("baci")["cms"])
            ck("  and it says which credential did it",
               tenants.capability_detail("baci")["cms"]["via"].endswith("shopify"),
               tenants.capability_detail("baci")["cms"]["via"])
            ck("coverings declares shopify too, but has no store, so unwired",
               not tenants.capabilities("coverings")["cms"])
            ck("ironside's squarespace is in no provider map and stays unwired",
               not tenants.capabilities("ironside")["cms"])
        finally:
            # Put the registry back. Leaving it set makes `resolve` fall through
            # to the env blob, and the revoke assertion below — which checks the
            # secret is gone — would pass on a stale value instead.
            if not _had_store:
                _cfg.SHOPIFY_STORES.pop("baci", None)

        # --- revoke ------------------------------------------------------
            print("\n— connecting WordPress, which is where the real ones fail —")
        import httpx as _httpx
        calls: list[dict] = []

        class _Resp:
            def __init__(self, code=200, body=None, text=""):
                self.status_code, self._b, self.text = code, body or {}, text

            def json(self):
                if self._b is None:
                    raise ValueError("not json")
                return self._b

            def raise_for_status(self):
                return None

        def _fake_get(url, **kw):
            calls.append({"url": url, "follow": kw.get("follow_redirects"),
                          "auth": kw.get("auth")})
            if "rest_route" in url:
                return _Resp(200, {"name": "Editor"})
            return _Resp(404, {}, "not found")

        _real = _httpx.get
        _httpx.get = _fake_get
        try:
            for raw, want in [("acme.com", "https://acme.com"),
                              ("https://acme.com/", "https://acme.com"),
                              ("https://acme.com/blog", "https://acme.com/blog")]:
                m, _ = cred._normalize_meta("wordpress", {"site": raw})
                ck(f"  {raw!r} becomes {want!r}", m["site"] == want, m["site"])

            calls.clear()
            res = cred._probe("wordpress", "abcd EFGH ijkl",
                              {"site": "https://acme.com", "username": "editor"})
            ck("REDIRECTS ARE FOLLOWED — nearly every WordPress site redirects "
               "http→https or www→apex, and Basic auth dies silently at a 301",
               all(c["follow"] for c in calls), str([c["follow"] for c in calls]))
            ck("  a site with plain permalinks is still found via ?rest_route",
               res["ok"] and len(calls) == 2, str(calls[-1]["url"] if calls else ""))
            ck("  the application password keeps its spaces — we told them to copy "
               "it that way", calls[0]["auth"][1] == "abcd EFGH ijkl",
               str(calls[0]["auth"][1]))

            _httpx.get = lambda url, **kw: _Resp(
                401, {}, '{"code":"rest_not_logged_in"}')
            res = cred._probe("wordpress", "x",
                              {"site": "https://acme.com", "username": "editor"})
            ck("a host that strips the Authorization header is NAMED as such, not "
               "reported as a wrong password",
               not res["ok"] and "Authorization header" in res["error"],
               res["error"][:70])

            _httpx.get = lambda url, **kw: _Resp(401, {}, "bad credentials")
            res = cred._probe("wordpress", "x",
                              {"site": "https://acme.com", "username": "editor"})
            ck("  a genuine rejection says which username it wants",
               not res["ok"] and "login name" in res["error"], res["error"][:70])

            _httpx.get = lambda url, **kw: _Resp(404, {}, "nope")
            res = cred._probe("wordpress", "x",
                              {"site": "https://acme.com", "username": "editor"})
            ck("  and no API at all lists what was tried",
               not res["ok"] and "wp-json" in res["error"]
               and "rest_route" in res["error"], res["error"][:80])
        finally:
            _httpx.get = _real

        print("\n— disconnecting —")
        cred.revoke("baci", "shopify")
        ck("revoke clears the stored secret",
           cred.resolve("baci", "shopify").get("secret", "") == "")
        with db.SessionLocal() as s:
            row = s.query(db.Credential).filter(
                db.Credential.tenant == "baci",
                db.Credential.provider == "shopify").first()
            ck("and the row keeps a record that it existed", row.status == "revoked")

        # --- the agency's Canva serves every account ---------------------
        #
        # Canva is the ONLY provider allowed to do this, and the boundary is
        # what the checks below are really for: a design tool holds our own
        # finished work, a Shopify token holds the client's orders. Falling
        # back on the second would read one client's data through another's
        # connection.
        print("\n— the agency's shared connection —")
        with db.SessionLocal() as s:
            s.add(db.Credential(tenant="agency", provider="canva", kind="oauth",
                                secret=cred._encrypt("agency-canva-token"),
                                meta={}, status="active", granted_by="gomeh"))
            s.commit()
        got = cred.resolve("ironside", "canva")
        ck("a client with no Canva of its own uses the agency's",
           got.get("secret") == "agency-canva-token")
        ck("and it is reported as the agency's, never as the client's",
           got.get("source") == "agency", got.get("source", ""))
        ck("the console says connected, and says whose",
           next(r for r in cred.status("ironside") if r["provider"] == "canva")
           ["state"] == "connected")
        ck("  naming the agency in the detail",
           "agency" in next(r for r in cred.status("ironside")
                            if r["provider"] == "canva")["detail"])
        with db.SessionLocal() as s:
            s.add(db.Credential(tenant="ironside", provider="canva", kind="oauth",
                                secret=cred._encrypt("ironside-own-token"),
                                meta={}, status="active", granted_by="client"))
            s.commit()
        own = cred.resolve("ironside", "canva")
        ck("a client's own connection overrides the agency's",
           own.get("secret") == "ironside-own-token" and own.get("source") == "client")

        # --- one client, several installs of one provider ----------------
        #
        # Ironside's main site is Squarespace and its landing pages are
        # WordPress; other clients run more than one WordPress install. One row
        # per (tenant, provider) could hold exactly one of them, so the second
        # was unconnectable and nothing on the page said why.
        print("\n— several sites for one provider —")
        for url, tok in (("https://lp.example.com", "wp-one"),
                         ("https://events.example.com", "wp-two")):
            with db.SessionLocal() as s:
                s.add(db.Credential(
                    tenant="ironside", provider="wordpress", kind="api_key",
                    site=cred._site_key("wordpress", url),
                    secret=cred._encrypt(tok),
                    meta={"site": url, "username": "editor"},
                    status="active", granted_by="client"))
                s.commit()
        ck("both installs are held, not one",
           len(cred.sites("ironside", "wordpress")) == 2,
           str(cred.sites("ironside", "wordpress")))
        amb = cred.resolve("ironside", "wordpress")
        ck("asking without saying which is REFUSED, not guessed",
           not amb.get("secret") and "say which" in amb.get("error", ""),
           amb.get("error", "")[:60])
        ck("  and the refusal names them",
           len(amb.get("sites", [])) == 2)
        ck("each is reachable by name",
           cred.resolve("ironside", "wordpress", "lp.example.com")["secret"]
           == "wp-one")
        ck("however the client spelled it",
           cred.resolve("ironside", "wordpress",
                        "HTTPS://Events.Example.com/")["secret"] == "wp-two",
           "scheme, case and trailing slash all normalise to one key")
        ck("disconnecting without saying which is refused too",
           "say which" in cred.revoke("ironside", "wordpress"),
           "severing both because the caller named neither is the worst reading")
        cred.revoke("ironside", "wordpress", "lp.example.com")
        ck("  and disconnecting one leaves the other",
           cred.sites("ironside", "wordpress") == ["https://events.example.com"])
        ck("with one left, no site is needed again",
           cred.resolve("ironside", "wordpress")["secret"] == "wp-two")
        st = next(r for r in cred.status("ironside") if r["provider"] == "wordpress")
        ck("the console can address each one separately",
           st["site_scoped"] and len(st["connections"]) == 1,
           str([c["site"] for c in st["connections"]]))
        ck("a single-site provider is unaffected",
           not next(r for r in cred.status("baci")
                    if r["provider"] == "klaviyo")["site_scoped"])

        # The line that must not move.
        with db.SessionLocal() as s:
            s.add(db.Credential(tenant="agency", provider="shopify", kind="api_key",
                                secret=cred._encrypt("shpat_agency"), meta={},
                                status="active", granted_by="gomeh"))
            s.commit()
        ck("NO fallback for a provider holding client data",
           cred.resolve("coverings", "shopify").get("secret", "") == "",
           "coverings must never read Shopify through the agency's token")

    # --- the env group is a REGISTRY, not a secret ------------------------
    #
    # A Shopify store configured the SUPPORTED way — `client_id` +
    # `client_secret`, no inline token, `data_tools._shopify_token` completing
    # a client_credentials grant — has no `cfg["token"]`. `status()` asked
    # `_from_env(...)["secret"]` and therefore reported a live, working store
    # as MISSING, so the console showed a paste-an-API-key form for a
    # credential the owner had already supplied in another form.
    #
    # `_env_registry_hit`'s docstring records this exact trap and
    # `wired_capabilities` was fixed to use it. The DISPLAY layer was not.
    print("\n— a store with client credentials and no inline token —")
    import json as _json
    from app import config as _cfg
    _keep = _cfg.SHOPIFY_STORES
    _cfg.SHOPIFY_STORES = _json.loads(_json.dumps({
        "baci": {"domain": "baci.myshopify.com",
                 "client_id": "abc", "client_secret": "shh"}}))
    try:
        rows = {r["provider"]: r for r in cred.status("baci")}
        ck("the console says CONNECTED", rows["shopify"]["state"] == "connected",
           f'got {rows["shopify"]["state"]!r} — the store works; '
           f'_shopify_token exchanges the client credentials on demand')
        ck("and says where it comes from",
           "env group" in rows["shopify"]["detail"], rows["shopify"]["detail"])
        caps = cred.wired_capabilities("baci")
        ck("the capability layer agreed all along",
           caps.get("commerce") == "env:shopify", str(caps))
        ck("so display and capability now say the same thing",
           (rows["shopify"]["state"] == "connected") == ("commerce" in caps),
           "one of them reading connected while the other reads missing is "
           "how an owner gets told to supply a credential twice")
    finally:
        _cfg.SHOPIFY_STORES = _keep

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
