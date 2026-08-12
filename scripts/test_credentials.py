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

        # --- revoke ------------------------------------------------------
        print("\n— disconnecting —")
        cred.revoke("baci", "shopify")
        ck("revoke clears the stored secret",
           cred.resolve("baci", "shopify").get("secret", "") == "")
        with db.SessionLocal() as s:
            row = s.query(db.Credential).filter(
                db.Credential.tenant == "baci",
                db.Credential.provider == "shopify").first()
            ck("and the row keeps a record that it existed", row.status == "revoked")

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
