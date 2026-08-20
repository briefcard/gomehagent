"""Connecting a client's Shopify without walking them through developer settings.

A custom app is five minutes for a store you OWN. For a client's store it means
talking a merchant through Shopify's developer settings, ticking API scopes, and
copying a token shown exactly once — which is not something to ask of somebody
you are onboarding. OAuth is the flow for that, and this is the first one in
this codebase whose endpoints are not a constant.

That last part is the whole risk. Every other provider posts its client secret
to a host compiled in here; Shopify's authorize and token URLs are built from a
shop domain that arrives in a form field and, at the callback, in a query
parameter anyone can write. `shop=evil.example.com` would make us POST
client_id + client_secret to an attacker's server, from one link, looking
exactly like a failed sign-in. Most of this file is about that.

    python3 scripts/test_shopify_oauth.py
"""
import hashlib
import hmac
import os
import sys
import tempfile
from urllib.parse import parse_qs, urlencode, urlparse

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'so.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["SHOPIFY_CLIENT_ID"] = "test-client-id"
os.environ["SHOPIFY_CLIENT_SECRET"] = "test-client-secret"
os.environ["PUBLIC_BASE_URL"] = "https://ops.example.com"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import credentials as cred, db, oauth, tenants, web  # noqa: E402

_fail: list[str] = []
SHOP = "acme.myshopify.com"


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def signed(params: dict) -> dict:
    """A callback signed the way Shopify signs one."""
    body = urlencode(sorted(params.items()))
    return {**params, "hmac": hmac.new(b"test-client-secret", body.encode(),
                                       hashlib.sha256).hexdigest()}


def main() -> int:
    db.init_db()
    tenants.seed()
    c = TestClient(web.app)

    print("— the shop gate: an allowlist, not a cleanup —")
    ok_forms = ["acme.myshopify.com", "https://acme.myshopify.com/admin",
                "ACME.MyShopify.com", "acme.myshopify.com:443"]
    for v in ok_forms:
        ck(f"  accepts {v[:38]}", oauth.shop_host(v) == SHOP, oauth.shop_host(v))
    attacks = {
        "evil.example.com": "a different host entirely",
        "acme.myshopify.com.evil.com": "the suffix trick",
        "evil.com?x=acme.myshopify.com": "the domain in a query string",
        "acme.myshopify.com@evil.com": "userinfo, so the real host is evil.com",
        "": "nothing at all",
    }
    for v, why in attacks.items():
        ck(f"  refuses {v[:38] or '(empty)'}", oauth.shop_host(v) == "", why)

    print("\n— and it is enforced where the URL is BUILT, not only at the door —")
    for bad in ("evil.example.com", "", "acme.myshopify.com@evil.com"):
        try:
            oauth.endpoint("shopify", "token", bad)
            ck(f"  {bad[:30] or '(empty)'} cannot become a token URL", False,
               "it built one")
        except ValueError:
            ck(f"  {bad[:30] or '(empty)'} cannot become a token URL", True)
    ck("  a good one does",
       oauth.endpoint("shopify", "token", SHOP)
       == f"https://{SHOP}/admin/oauth/access_token")

    print("\n— starting the flow —")
    r = c.get("/admin/oauth/shopify?key=s3cret&tenant=baci&shop=" + SHOP,
              follow_redirects=False)
    ck("it redirects to the merchant's own domain", r.status_code == 303,
       str(r.status_code))
    loc = r.headers.get("location", "")
    ck("  on the shop's host, not ours", urlparse(loc).netloc == SHOP, loc[:70])
    q = parse_qs(urlparse(loc).query)
    ck("  asking for the scopes the flow declares",
       q.get("scope", [""])[0] == "read_products,read_orders,read_inventory",
       q.get("scope", [""])[0])
    ck("  with our registered redirect", q["redirect_uri"][0]
       == "https://ops.example.com/oauth/shopify/callback")
    state = q["state"][0]
    data, why = oauth.read_state(state)
    ck("  and the shop travels SIGNED inside the state",
       not why and data.get("shop") == SHOP, why or str(data))

    print("\n— a bad shop never starts a flow —")
    bad = c.get("/admin/oauth/shopify?key=s3cret&tenant=baci&shop=evil.example.com")
    ck("it is refused", "error" in bad.json(), str(bad.json())[:80])
    ck("  and the refusal does not echo the value back",
       "evil.example.com" not in str(bad.json()),
       "an error page that reflects arbitrary input is its own problem")
    missing = c.get("/admin/oauth/shopify?key=s3cret&tenant=baci")
    ck("a missing shop is refused too, by name", "error" in missing.json())

    print("\n— the callback must carry Shopify's own signature —")
    good = signed({"code": "abc", "shop": SHOP, "state": state,
                   "timestamp": "1"})
    ck("an unsigned callback is refused",
       c.get("/oauth/shopify/callback", params={k: v for k, v in good.items()
                                                if k != "hmac"},
             follow_redirects=False).status_code == 400,
       "state proves WE started it, not who finished it")
    forged = {**good, "hmac": "0" * 64}
    ck("  and a forged signature is refused",
       c.get("/oauth/shopify/callback", params=forged,
             follow_redirects=False).status_code == 400)
    tampered = signed({"code": "abc", "shop": SHOP, "state": state,
                       "timestamp": "1"})
    tampered["code"] = "swapped-after-signing"
    ck("  and a signature that no longer covers the params is refused",
       c.get("/oauth/shopify/callback", params=tampered,
             follow_redirects=False).status_code == 400,
       "replaying a state with a chosen code is the attack this closes")

    print("\n— and it must come back for the shop it left with —")
    other = signed({"code": "abc", "shop": "someone-else.myshopify.com",
                    "state": state, "timestamp": "1"})
    got = c.get("/oauth/shopify/callback", params=other, follow_redirects=False)
    ck("a different shop on the way back is refused", got.status_code == 400,
       str(got.status_code))
    ck("  and nothing was stored", not cred.resolve("baci", "shopify").get("secret"),
       "a token filed under a client who never authorised it")

    print("\n— a completed sign-in stores a usable connection —")
    calls = {}

    class _Resp:
        status_code = 200
        def json(self):
            return {"access_token": "shpat_from_oauth",
                    "scope": "read_products,read_orders,read_inventory"}

    import httpx
    real_post = httpx.post

    def _post(url, **kw):
        calls["url"] = url
        calls["data"] = kw.get("data")
        return _Resp()

    httpx.post = _post
    try:
        done = c.get("/oauth/shopify/callback", params=good,
                     follow_redirects=False)
    finally:
        httpx.post = real_post
    ck("the exchange went to the SHOP's token endpoint",
       calls.get("url") == f"https://{SHOP}/admin/oauth/access_token",
       str(calls.get("url")))
    ck("  carrying the code and nothing Shopify rejects",
       calls.get("data") == {"code": "abc", "client_id": "test-client-id",
                             "client_secret": "test-client-secret"},
       str(calls.get("data")))
    ck("  and it completed", done.status_code == 303, str(done.status_code))

    got = cred.resolve("baci", "shopify")
    ck("the token is stored", got.get("secret") == "shpat_from_oauth")
    ck("  WITH the shop, or nothing can address the store",
       got.get("domain") == SHOP,
       "a working token every caller then fails to use, green on the console "
       "throughout")
    # Ask the DATABASE what landed, not a summary of it — a column accepting
    # a value proves nothing about whether it was written.
    with db.SessionLocal() as s:
        row = (s.query(db.Credential)
               .filter(db.Credential.tenant == "baci",
                       db.Credential.provider == "shopify").first())
        stored_scopes = (row.scopes or "") if row else ""
    ck("  and the granted scopes come from the RESPONSE",
       "read_orders" in stored_scopes and "read_products" in stored_scopes,
       stored_scopes or "(nothing stored)")

    print("\n— and the adapter can now actually use it —")
    conf = cred.shopify_config("baci")
    ck("shopify_config resolves domain + token",
       conf.get("domain") == SHOP and conf.get("token") == "shpat_from_oauth",
       str(conf))

    print("\n— both ways stay open —")
    row = [x for x in cred.status("baci") if x["provider"] == "shopify"][0]
    ck("Shopify still accepts a pasted token", row["kind"] == "api_key")
    ck("  and offers the button beside it", row["oauth_too"] is True)
    ck("  and knows it needs a shop", row["shop_scoped"] is True)

    print("\n— a flow declaring an unimplemented `stores` refuses by name —")
    # The branch this replaces ended in a bare `else` that ran Meta's
    # long-lived exchange, so a third provider inherited Meta's token swap.
    real = oauth.FLOWS["shopify"]["stores"]
    oauth.FLOWS["shopify"]["stores"] = "something_nobody_wrote"
    httpx.post = _post          # the token call must SUCCEED to reach the branch
    try:
        out = oauth.exchange("shopify", "abc", shop=SHOP)
    finally:
        oauth.FLOWS["shopify"]["stores"] = real
        httpx.post = real_post
    ck("it says which value is unimplemented",
       not out["ok"] and "something_nobody_wrote" in out["error"], str(out)[:90])

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
