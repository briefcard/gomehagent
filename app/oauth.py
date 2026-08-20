"""OAuth as a declared flow, so the routes know no provider by name.

Two providers need OAuth rather than a pasted key — Google and Meta — and the
temptation is to write two functions called `google_callback` and
`meta_callback`. That is the customisation-in-code pattern decision #3 forbids,
and `sources.py` already paid for the lesson: the moment a third provider
arrives, an if-tree that knows every provider by name has to be edited in four
places and one of them gets missed.

So a flow declares itself:

    {"authorize", "token"    the two endpoints
     "scopes":               what we ask for, as a list
     "extra":                query params the provider needs on the consent URL
     "client":               () -> (client_id, client_secret) read at CALL time,
                             never at import, so a missing env var is a named
                             refusal rather than a crash on boot
     "stores":               which token we keep — refresh_token or long_lived
     "identify":             (access_token, meta) -> {"label", "granted"}}

Three things here are load-bearing and worth not undoing:

**State is signed, not stored.** It carries the connect token, the tenant and
an expiry, HMAC'd with `APPROVAL_SECRET`. A table row would need cleanup and a
migration; a signature needs neither, and the thing an attacker would have to
forge is the connect token, which is already the capability. Ten-minute expiry,
because a consent screen left open overnight and completed by someone else is
not a flow anyone wants.

**A missing refresh token is a refusal.** Google returns `refresh_token` only
on first consent unless `prompt=consent` is forced — which we do force. If it
comes back absent anyway, storing the access token would produce a connection
that works for one hour and then fails somewhere unrelated, which is exactly
the class of defect this codebase keeps finding. It is refused by name instead.

**Granted scopes are compared to requested scopes.** DEFECTS records that
`verify()` catches a dead token but not a narrow one — "grant the full read
set, it fails quietly later". For OAuth it does not have to be quiet: both
providers report what was actually granted, so a user who unticked Drive on the
consent screen is told which scope is missing, at the moment they get it wrong.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time

from . import config

STATE_TTL = 600  # seconds. A consent screen is a thing you finish now.


# ---------------------------------------------------------------------------
# What can be connected by signing in.
# ---------------------------------------------------------------------------

def _google_client() -> tuple[str, str]:
    return config.GOOGLE_CLIENT_ID, config.GOOGLE_CLIENT_SECRET


def _canva_client() -> tuple[str, str]:
    return config.CANVA_CLIENT_ID, config.CANVA_CLIENT_SECRET


def _identify_canva(access_token: str, payload: dict) -> dict:
    import httpx
    try:
        r = httpx.get("https://api.canva.com/rest/v1/users/me",
                      headers={"Authorization": f"Bearer {access_token}"},
                      timeout=20)
        if r.status_code >= 400:
            return {}
        d = (r.json() or {}).get("team_user") or {}
        return {"label": d.get("user_id", ""), "team_id": d.get("team_id", "")}
    except Exception:                                            # noqa: BLE001
        return {}


def _cc_client() -> tuple[str, str]:
    return config.CONSTANT_CONTACT_CLIENT_ID, config.CONSTANT_CONTACT_CLIENT_SECRET


def _identify_cc(access_token: str, payload: dict) -> dict:
    """Which Constant Contact account this is.

    `/account/summary` is the lightest authenticated read the API offers and it
    needs `account_read`, which is asked for — so a token that cannot answer it
    is a narrower grant than we requested and worth knowing about at connect
    time rather than at send time.
    """
    import httpx
    try:
        r = httpx.get("https://api.cc.email/v3/account/summary",
                      headers={"Authorization": f"Bearer {access_token}"},
                      timeout=20)
        if r.status_code >= 400:
            return {}
        d = r.json() or {}
        return {"label": d.get("organization_name") or d.get("email", ""),
                "granted": (payload.get("scope") or "").split()}
    except Exception:                                            # noqa: BLE001
        return {}


def _meta_client() -> tuple[str, str]:
    return config.META_APP_ID, config.META_APP_SECRET


def _shopify_client() -> tuple[str, str]:
    return config.SHOPIFY_CLIENT_ID, config.SHOPIFY_CLIENT_SECRET


#: A Shopify shop domain and nothing else. Anchored, lowercase, no port, no
#: path, no credentials, no unicode.
_SHOP_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,59}\.myshopify\.com$")


def shop_host(raw: str) -> str:
    """A validated `<handle>.myshopify.com`, or "" — and this one is a GATE.

    Shopify is the only flow whose endpoints live on a host the caller supplies:
    every other provider posts its client secret to a constant we compiled in,
    while here the authorize and token URLs are built from a shop domain that
    arrives in a form field and, at the callback, in a query parameter anyone
    can write. Without this, `shop=evil.example.com` makes us POST
    `client_id` + `client_secret` to an attacker's server — a full credential
    disclosure from one link, and it would look exactly like a failed sign-in.

    So the rule is allowlist, not sanitise: the value must match the shape
    Shopify itself guarantees, and anything else is refused rather than
    repaired. The normalisation that DOES happen (scheme, path, admin URL) runs
    in `credentials._normalize_meta`, which is a convenience for a human typing
    into a form; this is the security boundary and it accepts one shape.
    """
    host = (raw or "").strip().lower()
    host = host.split("://", 1)[-1].split("/", 1)[0].split("?", 1)[0]
    host = host.split("@")[-1].split(":", 1)[0]      # no userinfo, no port
    return host if _SHOP_RE.match(host) else ""


#: What each scope lets us do, in words a merchant can weigh. Rendered on the
#: connect page from the flow's own `scopes`, so a scope added here appears
#: there and an unlisted one shows as itself rather than silently as nothing.
#:
#: Write access is described by WHAT IT CHANGES, not as "write": "publish and
#: revise blog posts and pages" is something somebody can agree or object to;
#: "write_content" is not, and a consent screen nobody can read is consent in
#: name only.
SCOPE_WORDS = {
    "read_products": "read your products, prices and collections",
    "write_products": "update product descriptions and SEO fields",
    "read_orders": "read orders, so replies can answer about them",
    "read_inventory": "read stock levels",
    "read_customers": "see who a message is from — their past orders and any "
                      "previous problems",
    "read_content": "read your blog posts and pages",
    "write_content": "publish and revise blog posts and pages",
    "read_themes": "read your theme",
    "write_themes": "add a structured-data snippet to your theme "
                    "(reversible from Shopify's theme history)",
}


def scope_words(provider: str) -> list[str]:
    """The plain-language grant list for a flow, in the order it is requested."""
    return [SCOPE_WORDS.get(s, s) for s in (FLOWS.get(provider) or {}).get("scopes", [])]


def _identify_shopify(access_token: str, payload: dict) -> dict:
    """What was connected, and what Shopify actually granted.

    Shopify returns the granted scopes on the token response itself, so this
    needs no extra call — and `scope` is authoritative in a way an app's
    configured scopes are not: a merchant can be shown one set and approve it
    while the app was later reconfigured, and only the response says which
    happened.
    """
    granted = [s.strip() for s in (payload.get("scope") or "").split(",")
               if s.strip()]
    return {"label": payload.get("_shop", ""), "granted": granted}


def _identify_google(access_token: str, payload: dict) -> dict:
    """Which mailbox this is, and what it actually granted.

    `getProfile` rather than an `openid` scope: the address is the useful
    identity here, gmail.modify already reaches it, and one fewer scope on the
    consent screen is one fewer reason to decline.
    """
    import httpx
    granted = (payload.get("scope") or "").split()
    r = httpx.get("https://gmail.googleapis.com/gmail/v1/users/me/profile",
                  headers={"Authorization": f"Bearer {access_token}"}, timeout=20)
    label = ""
    if r.status_code == 200:
        label = r.json().get("emailAddress", "")
    return {"label": label, "granted": granted}


def _identify_meta(access_token: str, payload: dict) -> dict:
    """Meta does not return scopes with the token — they come from /me/permissions."""
    import httpx
    granted: list[str] = []
    r = httpx.get("https://graph.facebook.com/v21.0/me/permissions",
                  params={"access_token": access_token}, timeout=20)
    if r.status_code == 200:
        granted = [p["permission"] for p in r.json().get("data", [])
                   if p.get("status") == "granted"]
    who = httpx.get("https://graph.facebook.com/v21.0/me",
                    params={"access_token": access_token, "fields": "name"},
                    timeout=20)
    label = who.json().get("name", "") if who.status_code == 200 else ""
    return {"label": label, "granted": granted}


FLOWS: dict[str, dict] = {
    "google": dict(
        authorize="https://accounts.google.com/o/oauth2/v2/auth",
        token="https://oauth2.googleapis.com/token",
        # The set scripts/google_oauth.py has always requested. Authorize once,
        # never again — a second consent round-trip to add Search Console later
        # is a second chance for the client to not get round to it.
        scopes=[
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/drive",
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/webmasters.readonly",
            "https://www.googleapis.com/auth/analytics.readonly",
        ],
        extra={"access_type": "offline", "prompt": "consent",
               "include_granted_scopes": "true"},
        client=_google_client,
        env="GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET",
        token_style="post_body",
        stores="refresh_token",
        identify=_identify_google,
    ),
    # Shopify. The one flow whose endpoints are PER SHOP -- `{shop}` is filled
    # from a validated `shop_host`, never from a raw form value. See that
    # function for why this is a security boundary rather than a formatting
    # convenience.
    #
    # Offline access by default: no `access_mode` in `extra` means the token
    # does not expire and is not tied to a logged-in session, which is what a
    # background worker reading orders at 3am needs. An online token would die
    # with the merchant's browser session.
    "shopify": dict(
        authorize="https://{shop}/admin/oauth/authorize",
        token="https://{shop}/admin/oauth/access_token",
        # Everything this platform can do to a Shopify store, asked ONCE.
        #
        # The first version stopped at the three read scopes on the grounds
        # that asking for undisclosed write access loses a client's trust. The
        # owner corrected it, and he is right: the answer to undisclosed is to
        # DISCLOSE, not to omit. Omitting means the blog system cannot publish
        # and the client has to be sent back through a second consent round —
        # which is the same reasoning already written into the Google flow, and
        # a second round-trip is a second chance for them not to get round to
        # it.
        #
        # So the connect page lists these in plain words (`SCOPE_WORDS`),
        # rendered FROM this list so the two cannot drift apart.
        # `read_customers` is here because `lookups.TOOLS` declares
        # `shopify_customer` — "order history, lifetime value, previous
        # issues" — so a support reply is meant to be able to see who it is
        # answering. Note it needs Shopify's separate PROTECTED CUSTOMER DATA
        # approval on top of the scope; without that the fields come back
        # REDACTED rather than erroring, which reads as an empty account.
        scopes=["read_products", "write_products",
                "read_orders", "read_inventory", "read_customers",
                "read_content", "write_content",
                "read_themes", "write_themes"],
        extra={},
        client=_shopify_client,
        env="SHOPIFY_CLIENT_ID / SHOPIFY_CLIENT_SECRET",
        token_style="post_body",
        stores="access_token",
        identify=_identify_shopify,
        shop_scoped=True,
        # Shopify signs the callback query with the client secret. Verified
        # before the code is spent -- see `verify_callback`.
        signed_callback=True,
    ),
    "meta_ads": dict(
        authorize="https://www.facebook.com/v21.0/dialog/oauth",
        token="https://graph.facebook.com/v21.0/oauth/access_token",
        scopes=["ads_read", "ads_management", "business_management"],
        extra={},
        client=_meta_client,
        env="META_APP_ID / META_APP_SECRET",
        token_style="get_params",
        stores="long_lived",
        identify=_identify_meta,
    ),
    "canva": dict(
        authorize="https://www.canva.com/api/oauth/authorize",
        token="https://api.canva.com/rest/v1/oauth/token",
        # Asked for once. `folder:write` is not optional here: every design and
        # asset this platform creates is filed into that account's own folder,
        # and without it they land loose in a shared team space where one
        # client's work sits next to another's.
        scopes=["asset:read", "asset:write",
                "design:content:read", "design:content:write",
                "design:meta:read", "folder:read", "folder:write",
                "brandtemplate:content:read", "profile:read"],
        extra={},
        client=_canva_client,
        env="CANVA_CLIENT_ID / CANVA_CLIENT_SECRET",
        token_style="post_body",
        stores="refresh_token",
        identify=_identify_canva,
        pkce=True,
    ),
    "constant_contact": dict(
        authorize="https://authz.constantcontact.com/oauth2/default/v1/authorize",
        token="https://authz.constantcontact.com/oauth2/default/v1/token",
        # `offline_access` is what makes this a connection rather than a
        # session: without it Constant Contact returns an access token that
        # dies in hours and no refresh token, so the account would read
        # connected on the console and stop working the same afternoon. That is
        # the exact failure `test_oauth` already refuses for Google.
        scopes=["account_read", "contact_data", "campaign_data",
                "offline_access"],
        extra={"response_type": "code"},
        client=_cc_client,
        env="CONSTANT_CONTACT_CLIENT_ID / CONSTANT_CONTACT_CLIENT_SECRET",
        token_style="basic_auth",
        stores="refresh_token",
        identify=_identify_cc,
    ),
}


# A flow declaring no `env` would raise inside `configured()` at render time --
# on the console, for the one person trying to connect it. Caught at import
# instead, which is the only moment it is cheap.
for _key, _spec in FLOWS.items():
    assert _spec.get("env"), f"OAuth flow {_key!r} declares no env var names"
    assert _spec.get("token_style") in ("post_body", "get_params", "basic_auth"), \
        f"OAuth flow {_key!r} declares no token_style"


def configured(provider: str) -> str:
    """"" if this flow can run, else why not — in words an operator can act on."""
    spec = FLOWS.get(provider)
    if not spec:
        return f"unknown provider {provider!r}"
    cid, secret = spec["client"]()
    if not (cid and secret):
        # Read off the flow, never a per-provider ternary. The ternary said
        # "google or else META" and Canva arrived third, so the console told
        # anyone trying to connect Canva to go and set the Meta app secret --
        # a refusal that names the wrong missing thing is worse than one that
        # names nothing, because it sends somebody to do the wrong work.
        return f"{spec['env']} not set in the env group"
    if not config.PUBLIC_BASE_URL.startswith("https://"):
        return (f"PUBLIC_BASE_URL is {config.PUBLIC_BASE_URL!r} — OAuth "
                f"redirects must be https, so consent will be rejected")
    return ""


def redirect_uri(provider: str) -> str:
    """Must match the console registration byte for byte, so it is derived once."""
    return f"{config.PUBLIC_BASE_URL.rstrip('/')}/oauth/{provider}/callback"


# ---------------------------------------------------------------------------
# State: signed, short-lived, and never a database row.
# ---------------------------------------------------------------------------

def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sig(body: str) -> str:
    return _b64(hmac.new(f"oauth:{config.APPROVAL_SECRET}".encode(),
                         body.encode(), hashlib.sha256).digest())


def _pkce_pair() -> tuple[str, str]:
    """A PKCE verifier and its S256 challenge.

    Canva Connect requires PKCE even for a confidential client, so this is not
    optional for that provider.
    """
    import base64
    import hashlib
    import secrets as _secrets
    verifier = _b64(_secrets.token_bytes(48))
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def sign_state(tenant: str, provider: str, connect_token: str = "",
               via: str = "connect", verifier: str = "", shop: str = "") -> str:
    """Sign the round-trip payload. `verifier` rides ENCRYPTED, not merely signed.

    The PKCE verifier has to survive a redirect through the provider and come
    back, and it must stay secret while it does — a signed-but-readable state
    would hand it to anyone who can see the URL, which is the interception PKCE
    exists to stop. So it is encrypted with the credential key: the provider
    and anything reading the address bar see ciphertext, and only this service
    can recover it. That keeps the codebase's rule that sign-in state is never
    a database row, without making the verifier public to buy it.
    """
    payload = {"tenant": tenant, "p": provider, "t": connect_token,
               "via": via, "exp": int(time.time()) + STATE_TTL}
    if shop:
        # Carried SIGNED rather than read back off the callback's own `shop`
        # parameter. Shopify does send one, but taking it from there would let
        # a forged link start a flow for one shop and complete it against
        # another -- and the two are compared at the callback for exactly that
        # reason.
        payload["shop"] = shop
    if verifier:
        from . import credentials as _cred
        payload["v"] = _cred._encrypt(verifier)
    body = _b64(json.dumps(payload, separators=(",", ":"),
                           sort_keys=True).encode())
    return f"{body}.{_sig(body)}"


def state_verifier(data: dict) -> str:
    """Recover the PKCE verifier from a validated state payload."""
    blob = (data or {}).get("v") or ""
    if not blob:
        return ""
    try:
        from . import credentials as _cred
        return _cred._decrypt(blob)
    except Exception:                                            # noqa: BLE001
        return ""


def verify_callback(provider: str, params: dict) -> str:
    """"" if this callback really came from the provider, else why not.

    Shopify signs the callback's query string with the app's client secret.
    Our own `state` already proves WE started the flow, but it does not prove
    who finished it: a signed state is a bearer value that travels in an
    address bar, through the merchant's browser history and any referrer, and
    replaying it with a `code` of somebody's choosing is exactly the attack the
    provider's own signature closes.

    The digest is over every query parameter except `hmac` and `signature`,
    sorted by key and joined as a query string — Shopify's documented rule.
    Compared with `compare_digest`, because a byte-at-a-time comparison on a
    signature check is a timing oracle.

    A flow that does not sign its callback returns "" — absent is not failed,
    and treating it as failed would break Google and Meta, which do not sign.
    """
    spec = FLOWS.get(provider) or {}
    if not spec.get("signed_callback"):
        return ""
    from urllib.parse import urlencode
    got = str(params.get("hmac") or "")
    if not got:
        return "that sign-in carried no signature"
    _cid, secret = spec["client"]()
    if not secret:
        return "cannot verify the sign-in: the client secret is not set"
    body = urlencode(sorted(
        (k, v) for k, v in params.items() if k not in ("hmac", "signature")))
    want = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(want, got):
        return "that sign-in did not come from the provider"
    return ""


def read_state(state: str) -> tuple[dict, str]:
    """The payload, or a reason it cannot be trusted. Never raises on junk."""
    try:
        body, sig = (state or "").split(".", 1)
    except ValueError:
        return {}, "malformed sign-in state"
    if not hmac.compare_digest(sig, _sig(body)):
        return {}, "sign-in state did not verify"
    try:
        data = json.loads(_unb64(body))
    except Exception:  # noqa: BLE001 — a tampered payload is a refusal, not a 500
        return {}, "unreadable sign-in state"
    if int(data.get("exp", 0)) < time.time():
        return {}, "this sign-in took too long — start again"
    return data, ""


# ---------------------------------------------------------------------------
# The two legs.
# ---------------------------------------------------------------------------

def endpoint(provider: str, which: str, shop: str = "") -> str:
    """The authorize or token URL, with a shop-scoped flow's host filled in.

    Refuses rather than formatting a bad host into a URL: an unvalidated shop
    reaching `{shop}` is the credential-disclosure hole `shop_host` exists to
    close, so the check is repeated at the point of use rather than trusted
    from the caller.
    """
    spec = FLOWS[provider]
    url = spec[which]
    if not spec.get("shop_scoped"):
        return url
    host = shop_host(shop)
    if not host:
        raise ValueError(f"{shop!r} is not a myshopify.com shop domain")
    return url.format(shop=host)


def authorize_url(provider: str, state: str, challenge: str = "",
                  shop: str = "") -> str:
    from urllib.parse import urlencode
    spec = FLOWS[provider]
    cid, _ = spec["client"]()
    params = {
        "client_id": cid,
        "redirect_uri": redirect_uri(provider),
        "response_type": "code",
        "scope": " ".join(spec["scopes"]),
        "state": state,
        **spec["extra"],
    }
    if spec.get("pkce"):
        # Sent as S256 rather than plain: a `plain` challenge is the verifier
        # itself, which would put it in the address bar and undo the point.
        params["code_challenge"] = challenge
        params["code_challenge_method"] = "S256"
    if spec.get("shop_scoped"):
        # Shopify wants them comma-separated under `scope`, not space-joined.
        params["scope"] = ",".join(spec["scopes"])
    return f"{endpoint(provider, 'authorize', shop)}?{urlencode(params)}"


def exchange(provider: str, code: str, code_verifier: str = "",
             shop: str = "") -> dict:
    """Consent code -> the token we intend to keep, plus what was granted.

    Returns {ok, secret, kind, label, granted, missing, expires_at, error}.
    `secret` is the long-lived half — a Google refresh token or a Meta
    long-lived access token — never the one-hour access token, which is derived
    from it on demand and is not worth storing.
    """
    import httpx
    spec = FLOWS.get(provider)
    if not spec:
        return {"ok": False, "error": f"unknown provider {provider!r}"}
    why = configured(provider)
    if why:
        return {"ok": False, "error": why}
    cid, secret = spec["client"]()

    # How the token endpoint wants to be called is a FACT ABOUT THE PROVIDER,
    # so it is declared on the flow. This was an if/elif on the provider name
    # ending in a bare `else`, which is the shape that produced the Canva
    # blocker bug one function above: whatever is added next silently inherits
    # the branch written for something else. Here that would mean a new
    # provider's client secret going out as a URL query parameter — into access
    # logs and proxy caches — because Meta happened to be the fallback.
    try:
        style = spec["token_style"]
        if style == "get_params":
            r = httpx.get(endpoint(provider, "token", shop), timeout=30, params={
                "code": code, "client_id": cid, "client_secret": secret,
                "redirect_uri": redirect_uri(provider)})
        else:
            form = {"grant_type": "authorization_code", "code": code,
                    "redirect_uri": redirect_uri(provider)}
            if spec.get("shop_scoped"):
                # Shopify's token endpoint takes client_id/client_secret/code
                # and nothing else; it has no grant_type and no redirect_uri,
                # and sending them is how the exchange 400s on a flow that is
                # otherwise correct.
                form = {"code": code}
            if spec.get("pkce") and code_verifier:
                form["code_verifier"] = code_verifier
            headers = {}
            if style == "basic_auth":
                # Constant Contact authenticates the client with an
                # Authorization header rather than body fields, and rejects the
                # exchange outright if the pair is posted in the form.
                pair = base64.b64encode(f"{cid}:{secret}".encode()).decode()
                headers["Authorization"] = f"Basic {pair}"
            else:
                form["client_id"], form["client_secret"] = cid, secret
            r = httpx.post(endpoint(provider, "token", shop), timeout=30,
                           data=form, headers=headers)
        if r.status_code >= 400:
            return {"ok": False, "error": _provider_error(r)}
        payload = r.json()
    except httpx.HTTPError as exc:
        return {"ok": False,
                "error": f"Could not reach {provider}: {exc.__class__.__name__}"}

    access = payload.get("access_token", "")
    if not access:
        return {"ok": False, "error": "No access token came back."}

    expires_at = 0
    kept = spec["stores"]
    if kept == "access_token":
        # The token IS the credential and does not expire. Shopify issues no
        # refresh token for offline access, so there is nothing else to keep.
        #
        # This arm exists because the branch below used to end in a bare
        # `else` that ran Meta's long-lived exchange — so a third provider
        # inherited Meta's token swap and would have failed inside a function
        # named for another platform. Same shape as the `token_style` else that
        # would have leaked a client secret into a URL (§2.31); an `else` in a
        # per-provider switch is a defect waiting for the next provider.
        keep = access
        payload = {**payload, "_shop": shop_host(shop)}
    elif kept == "refresh_token":
        keep = payload.get("refresh_token", "")
        if not keep:
            # Storing the access token here would produce a connection that
            # works for an hour and then fails inside something unrelated.
            return {"ok": False,
                    "error": "Google returned no refresh token. This usually "
                             "means the account was already connected to this "
                             "app — remove it at "
                             "myaccount.google.com/permissions and try again."}
    elif kept == "long_lived":
        long_lived, expires_at, err = _meta_long_lived(access, cid, secret)
        if err:
            return {"ok": False, "error": err}
        keep = long_lived
        access = long_lived
    else:
        # Named, not guessed. A flow declaring a `stores` nobody implemented
        # must refuse loudly here rather than take whichever arm happens to be
        # last.
        return {"ok": False,
                "error": f"{provider} declares stores={kept!r}, which this "
                         f"exchange does not implement"}

    try:
        who = spec["identify"](access, payload)
    except Exception as exc:  # noqa: BLE001 — identity is useful, not required
        who = {"label": "", "granted": []}
        del exc

    granted = who.get("granted") or []
    missing = _missing_scopes(spec["scopes"], granted)
    # What the credential needs to be USED, beyond the secret itself.
    extra_meta = {"domain": shop_host(shop)} if spec.get("shop_scoped") else {}
    return {"ok": True, "secret": keep, "kind": "oauth", "meta": extra_meta,
            "label": who.get("label", ""), "granted": granted,
            "missing": missing, "expires_at": expires_at}


def _provider_error(r) -> str:
    """The provider's own words when it has any, rather than a status code."""
    try:
        body = r.json()
    except Exception:  # noqa: BLE001
        return f"Sign-in was rejected (HTTP {r.status_code})."
    err = body.get("error")
    if isinstance(err, dict):  # Meta shape
        return err.get("message") or f"Sign-in was rejected (HTTP {r.status_code})."
    detail = body.get("error_description") or err or ""
    return (f"Sign-in was rejected: {detail}" if detail
            else f"Sign-in was rejected (HTTP {r.status_code}).")


def _missing_scopes(requested: list[str], granted: list[str]) -> list[str]:
    """What was asked for and not given.

    Google reports full scope URLs; Meta reports bare permission names. Compare
    on the last path segment so one rule covers both, and so a provider
    switching to a versioned URL does not silently report everything missing.
    """
    def leaf(s: str) -> str:
        return s.rsplit("/", 1)[-1]

    have = {leaf(g) for g in granted}
    if not have:  # nothing reported is not the same as nothing granted
        return []
    return [s for s in requested if leaf(s) not in have]


def _meta_long_lived(short: str, cid: str, secret: str) -> tuple[str, int, str]:
    """Meta tokens do not refresh; they are exchanged for a ~60-day one.

    Returns (token, expires_at_epoch, error). The expiry is stored because
    nothing else will remind anyone: a Meta connection dies quietly at day 60
    unless something renews it. See `renew_due` and the worker tick.
    """
    import httpx
    try:
        r = httpx.get("https://graph.facebook.com/v21.0/oauth/access_token",
                      timeout=30, params={
                          "grant_type": "fb_exchange_token",
                          "client_id": cid, "client_secret": secret,
                          "fb_exchange_token": short})
        if r.status_code >= 400:
            return "", 0, _provider_error(r)
        body = r.json()
    except httpx.HTTPError as exc:
        return "", 0, f"Could not reach Meta: {exc.__class__.__name__}"
    token = body.get("access_token", "")
    if not token:
        return "", 0, "Meta returned no long-lived token."
    # Meta omits expires_in when the token is effectively permanent (system
    # users). Zero means "no known expiry", which the renewal job reads as
    # nothing to do — rather than as "expired in 1970".
    return token, int(time.time()) + int(body.get("expires_in", 0) or 0), ""


def access_token(provider: str, refresh_token: str) -> dict:
    """A short-lived access token from the long-lived one we stored.

    `exchange` deliberately keeps only the refresh token — an access token that
    expires in an hour is not worth a database row — so every caller that
    actually talks to a provider needs this step. Nothing cached: a cached
    token outlives the revocation that was supposed to end it, and the whole
    point of the Disconnect button is that it takes effect.

    Uses the flow's own `token_style`, so a provider whose token endpoint wants
    Basic auth is not sent its client secret as a form field.
    """
    import httpx
    spec = FLOWS.get(provider)
    if not spec:
        return {"ok": False, "error": f"unknown provider {provider!r}"}
    if spec["stores"] != "refresh_token":
        return {"ok": False,
                "error": f"{provider} does not use refresh tokens"}
    why = configured(provider)
    if why:
        return {"ok": False, "error": why}
    if not refresh_token:
        return {"ok": False, "error": f"no stored {provider} token"}
    cid, secret = spec["client"]()
    form = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    headers = {}
    if spec["token_style"] == "basic_auth":
        pair = base64.b64encode(f"{cid}:{secret}".encode()).decode()
        headers["Authorization"] = f"Basic {pair}"
    else:
        form["client_id"], form["client_secret"] = cid, secret
    try:
        r = httpx.post(spec["token"], data=form, headers=headers, timeout=30)
    except httpx.HTTPError as exc:
        return {"ok": False,
                "error": f"{exc.__class__.__name__}: {str(exc)[:160]}"}
    if r.status_code >= 400:
        return {"ok": False, "error": _provider_error(r)}
    body = r.json()
    tok = body.get("access_token", "")
    if not tok:
        return {"ok": False,
                "error": f"{provider} returned no access token"}
    # Some providers ROTATE the refresh token on every use and invalidate the
    # old one. Handing it back means the caller can store it; dropping it would
    # mean the connection works once and then dies, which looks exactly like a
    # revocation and would be debugged as one.
    return {"ok": True, "token": tok,
            "new_refresh": body.get("refresh_token", "") or "",
            "expires_in": body.get("expires_in", 0)}


def renew(provider: str, token: str) -> dict:
    """Extend a token that cannot refresh. Meta only; Google needs no renewal."""
    spec = FLOWS.get(provider)
    if not spec or spec["stores"] != "long_lived":
        return {"ok": False, "error": f"{provider} does not renew"}
    why = configured(provider)
    if why:
        return {"ok": False, "error": why}
    cid, secret = spec["client"]()
    fresh, expires_at, err = _meta_long_lived(token, cid, secret)
    if err:
        return {"ok": False, "error": err}
    return {"ok": True, "secret": fresh, "expires_at": expires_at}
