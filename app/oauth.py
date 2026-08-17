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


def _meta_client() -> tuple[str, str]:
    return config.META_APP_ID, config.META_APP_SECRET


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
        stores="refresh_token",
        identify=_identify_google,
    ),
    "meta_ads": dict(
        authorize="https://www.facebook.com/v21.0/dialog/oauth",
        token="https://graph.facebook.com/v21.0/oauth/access_token",
        scopes=["ads_read", "ads_management", "business_management"],
        extra={},
        client=_meta_client,
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
        stores="refresh_token",
        identify=_identify_canva,
        pkce=True,
    ),
}


def configured(provider: str) -> str:
    """"" if this flow can run, else why not — in words an operator can act on."""
    spec = FLOWS.get(provider)
    if not spec:
        return f"unknown provider {provider!r}"
    cid, secret = spec["client"]()
    if not (cid and secret):
        env = "GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET" if provider == "google" \
            else "META_APP_ID / META_APP_SECRET"
        return f"{env} not set in the env group"
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
               via: str = "connect", verifier: str = "") -> str:
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

def authorize_url(provider: str, state: str, challenge: str = "") -> str:
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
    return f"{spec['authorize']}?{urlencode(params)}"


def exchange(provider: str, code: str, code_verifier: str = "") -> dict:
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

    try:
        if provider == "canva":
            r = httpx.post(spec["token"], timeout=30, data={
                "grant_type": "authorization_code", "code": code,
                "client_id": cid, "client_secret": secret,
                "redirect_uri": redirect_uri(provider),
                "code_verifier": code_verifier})
        elif provider == "google":
            r = httpx.post(spec["token"], timeout=30, data={
                "code": code, "client_id": cid, "client_secret": secret,
                "redirect_uri": redirect_uri(provider),
                "grant_type": "authorization_code"})
        else:
            r = httpx.get(spec["token"], timeout=30, params={
                "code": code, "client_id": cid, "client_secret": secret,
                "redirect_uri": redirect_uri(provider)})
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
    if spec["stores"] == "refresh_token":
        keep = payload.get("refresh_token", "")
        if not keep:
            # Storing the access token here would produce a connection that
            # works for an hour and then fails inside something unrelated.
            return {"ok": False,
                    "error": "Google returned no refresh token. This usually "
                             "means the account was already connected to this "
                             "app — remove it at "
                             "myaccount.google.com/permissions and try again."}
    else:
        long_lived, expires_at, err = _meta_long_lived(access, cid, secret)
        if err:
            return {"ok": False, "error": err}
        keep = long_lived
        access = long_lived

    try:
        who = spec["identify"](access, payload)
    except Exception as exc:  # noqa: BLE001 — identity is useful, not required
        who = {"label": "", "granted": []}
        del exc

    granted = who.get("granted") or []
    missing = _missing_scopes(spec["scopes"], granted)
    return {"ok": True, "secret": keep, "kind": "oauth",
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
