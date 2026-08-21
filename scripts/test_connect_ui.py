"""A route that is switched off must SAY it is switched off.

`status(tenant)` answers "is this account connected". Nothing answered "can
anybody connect at all", and those have different owners: a client cannot fix
an unset app credential, and the person who can had no screen saying one was
unset.

Shopify earned this suite. Its one-click route is built and deployed, and
`status()` computed the blocker as:

    blocked = oauth.configured(key) if spec["kind"] == "oauth" else ""

Shopify's `kind` is `api_key` (with `oauth_optional`), so the blocker was never
computed for it. With the app credentials unset the button did not render on the
console OR the client page, and no screen anywhere said why — so connecting any
store meant walking a merchant through developer settings, nine API scopes and a
token revealed exactly once, with the easy route invisible.

An absent button and an unbuilt feature look identical. That is the defect.

    python3 scripts/test_connect_ui.py
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'cu.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["CREDENTIAL_KEY"] = "a-test-encryption-key"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import config, credentials as cred, db, tenants  # noqa: E402
from app.web import app  # noqa: E402

_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _shopify(r):
    return next(p for p in r["providers"] if p["provider"] == "shopify")


def _way(prov, kind):
    return next(w for w in prov["ways"] if w["kind"] == kind)


def main() -> int:
    db.init_db()
    tenants.seed()
    config.PUBLIC_BASE_URL = "https://assistant.example.com"

    # --- with the app credentials unset ----------------------------------
    print("— Shopify with its app credentials unset —")
    config.SHOPIFY_CLIENT_ID = config.SHOPIFY_CLIENT_SECRET = ""
    r = cred.routes()
    sh = _shopify(r)
    ck("the token route is available", _way(sh, "api_key")["ok"])
    ck("the one-click route is NOT", not _way(sh, "oauth")["ok"])
    ck("and the reason names the env vars, not 'unavailable'",
       "SHOPIFY_CLIENT_ID" in _way(sh, "oauth")["why"], _way(sh, "oauth")["why"])
    ck("the provider reads as degraded, not as ready", sh["degraded"] and not sh["dead"],
       sh["verdict"])
    ck("the token route says what it actually costs — this is the whole "
       "argument for switching the other one on",
       "nine API scopes" in _way(sh, "api_key")["effort"],
       _way(sh, "api_key")["effort"][:60])

    # `status()` is what every connect surface renders from. The bug lived here.
    st = {x["provider"]: x for x in cred.status("baci")}
    ck("status() knows Shopify HAS a one-click route", st["shopify"]["has_oauth"])
    ck("and reports what is blocking it — this was empty, because the check "
       "asked kind == 'oauth' and Shopify's kind is api_key",
       "SHOPIFY_CLIENT_ID" in st["shopify"]["oauth_blocked_by"],
       repr(st["shopify"]["oauth_blocked_by"]))

    # --- the console must say it out loud --------------------------------
    print("\n— the console names it —")
    with TestClient(app) as cl:
        page = cl.get("/admin/ui?key=s3cret&tab=accounts&tenant=baci").text
    page_off = page
    ck("the Connections tab renders", "Connection routes" in page)
    ck("Shopify's blocker is NAMED on the page", "SHOPIFY_CLIENT_ID" in page)
    ck("and it says the one-click route exists rather than staying silent",
       "One-click sign-in" in page)
    # Needed MOST while the route is blocked: registering it IS half of
    # switching the flow on. It used to be withheld until the flow already
    # worked, which handed the value over only once nobody needed it.
    ck("the redirect URI to register is shown WHILE BLOCKED — the other half "
       "of the job, and the half that fails silently on a byte mismatch",
       "/oauth/shopify/callback" in page)
    # The real property, not a substring hunt: `shpat_` appears on the page as
    # INSTRUCTIONS ("it begins shpat_ — not the API key"), which is the opposite
    # of a leak. Store a known value and prove that value never renders.
    SECRET = "shpat_this_exact_value_must_never_render"
    real_probe = cred._probe
    cred._probe = lambda pr, sc, m: {"ok": True, "detail": "stubbed"}
    try:
        res = cred.store("baci", "shopify", SECRET,
                         {"domain": "baci-test.myshopify.com"})
        assert res.get("ok"), res
    finally:
        cred._probe = real_probe
    with TestClient(app) as cl:
        page2 = cl.get("/admin/ui?key=s3cret&tab=accounts&tenant=baci").text
    ck("a stored secret never reaches the page", SECRET not in page2)
    ck("though the connection itself is shown as connected",
       "connected" in page2)

    # --- with them set ----------------------------------------------------
    print("\n— and once they are set —")
    config.SHOPIFY_CLIENT_ID = "test-client-id"
    config.SHOPIFY_CLIENT_SECRET = "test-client-secret"
    sh = _shopify(cred.routes())
    ck("both routes are available", _way(sh, "oauth")["ok"] and _way(sh, "api_key")["ok"])
    ck("the provider reads as ready", not sh["degraded"] and not sh["dead"], sh["verdict"])
    ck("and it still hands over the redirect URI once working",
       "/oauth/shopify/callback" in _way(sh, "oauth")["action"],
       _way(sh, "oauth")["action"])
    with TestClient(app) as cl:
        page = cl.get("/admin/ui?key=s3cret&tab=accounts&tenant=baci").text
    ck("the console now offers the sign-in", "Sign in with Shopify" in page)
    ck("with somewhere to type the shop", 'name="shop"' in page)
    # Switching the button on does not make the DATA complete, and both of the
    # ways it stays incomplete fail quietly: redacted fields read as an empty
    # account, and a 60-day order window reads as a quiet business.
    ck("and it still warns that the button is not the whole job",
       "Protected Customer Data" in page and "read_all_orders" in page)
    ck("the caveat is shown while the route is OFF too, since it is true either "
       "way and is the more expensive half to discover late",
       "Protected Customer Data" in page_off)

    # --- the prerequisites nobody was told about --------------------------
    print("\n— prerequisites —")
    real = os.environ.get("CREDENTIAL_KEY", "")
    try:
        os.environ["CREDENTIAL_KEY"] = ""
        warns = {w["what"] for w in cred.routes()["warnings"]}
        ck("an unset CREDENTIAL_KEY is reported",
           any("CREDENTIAL_KEY" in w for w in warns), str(warns))
    finally:
        os.environ["CREDENTIAL_KEY"] = real
    ck("and it is silent once set",
       not any("CREDENTIAL_KEY" in w["what"] for w in cred.routes()["warnings"]))

    config.PUBLIC_BASE_URL = "http://localhost:8000"
    r = cred.routes()
    ck("a non-https base URL is reported, because every OAuth redirect dies "
       "on it and each provider would otherwise be blamed separately",
       any("PUBLIC_BASE_URL" in w["what"] for w in r["warnings"]))
    ck("and every one-click route reads blocked while it is wrong",
       all(not _way(p, "oauth")["ok"] for p in r["providers"]
           if any(w["kind"] == "oauth" for w in p["ways"])))
    config.PUBLIC_BASE_URL = "https://assistant.example.com"

    print()
    if _fail:
        print(f"{len(_fail)} FAILED: " + "; ".join(_fail))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
