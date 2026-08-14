"""Per-client credentials: stored encrypted, supplied by the client, resolved here.

Until now every credential was a name in a Render env-group JSON blob that Gomeh
created by hand. That works for five accounts he owns and stops working the
moment onboarding is supposed to happen without him — which is the actual limit
on how many clients this can carry.

Three things live here:

  1. PROVIDERS — what can be connected, how, and where the client finds it. The
     copy is part of the data because a client who cannot find their API key
     will email instead, which is the thing being removed.

  2. STORAGE  — Fernet ciphertext in `Credential.secret`. The value is never
     returned to any surface. `status()` reports connected / failed / missing
     and `last_verified`; nothing renders the secret, including to the owner.

  3. RESOLUTION — `resolve()` reads the database first and falls back to the
     env blobs. That fallback is what makes this safe to deploy: the five
     existing accounts keep working untouched, and each one moves over when its
     client connects it, with no cutover and no redeploy.

A credential that has verified against the live API is self-proving, so there is
no approval queue in front of it — an approval step here would only add a queue
someone has to work.
"""
from __future__ import annotations

import base64
import hashlib
import os

from . import config, db

# --------------------------------------------------------------------------
# What can be connected.
#
# `kind` is api_key or oauth. Only api_key is wired today; the oauth entries are
# declared so the connect page can show them as "coming soon" rather than
# pretending the stack is smaller than it is.
# --------------------------------------------------------------------------

PROVIDERS: dict[str, dict] = {
    "shopify": dict(
        name="Shopify",
        kind="api_key",
        capability="commerce",
        field="Admin API access token",
        also={"domain": "Your myshopify.com domain, e.g. acme.myshopify.com"},
        howto="In Shopify admin: Settings → Apps and sales channels → Develop apps "
              "→ Create an app → Configure Admin API scopes (tick read_products, "
              "read_orders, read_inventory) → Install app → Reveal token once.",
        starts="shpat_"),
    "omnisend": dict(
        name="Omnisend",
        kind="api_key",
        capability="esp",
        field="API key",
        also={},
        howto="In Omnisend: Store settings → Integrations & API → API keys → "
              "Create API key.",
        starts=""),
    "klaviyo": dict(
        name="Klaviyo",
        kind="api_key",
        capability="esp",
        field="Private API key",
        also={},
        howto="In Klaviyo: Settings → API keys → Create Private API Key "
              "(read access is enough to start).",
        starts="pk_"),
    "wordpress": dict(
        name="WordPress",
        kind="api_key",
        capability="cms",
        field="Application password",
        also={"site": "Your site URL, e.g. https://acme.com",
              "username": "The WordPress username it belongs to"},
        howto="In WordPress: Users → Profile → Application Passwords → add one. "
              "Copy it including the spaces.",
        starts=""),
    "google": dict(
        name="Google (Gmail, Drive, Calendar, Search Console, Analytics)",
        kind="oauth",
        capability="inbox",
        field="",
        also={},
        howto="Click Connect and sign in with Google, then Allow. Google will "
              "warn you that this app is not verified by them — that is "
              "expected: it is our own app, used only by our own clients, and "
              "it has not been through Google's public review. Click Advanced, "
              "then Continue. Leave every permission ticked; unticking one "
              "switches off the part of the system that uses it.",
        starts=""),
    "meta_ads": dict(
        name="Meta Ads",
        kind="oauth",
        capability="ads",
        field="",
        also={},
        howto="Click Connect and sign in with Meta, then choose the business "
              "and ad account you want us to read. Read access is enough to "
              "start.",
        starts=""),
}

CONNECTABLE = tuple(k for k, v in PROVIDERS.items() if v["kind"] == "api_key")

# Which capabilities each provider turns on. Most grant one; a Google sign-in
# grants the mailbox AND Search Console AND GA4 in the same consent, so
# reporting it as `inbox` alone left `analytics` reading "not wired" on an
# account that had just wired it.
GRANTS: dict[str, tuple[str, ...]] = {
    "google": ("inbox", "analytics"),
    "shopify": ("commerce",),
    "omnisend": ("esp",),
    "klaviyo": ("esp",),
    "wordpress": ("cms",),
    "meta_ads": ("ads",),
}


# --------------------------------------------------------------------------
# Encryption at rest.
# --------------------------------------------------------------------------

def _fernet():
    """The cipher, keyed from CREDENTIAL_KEY.

    Falls back to a key derived from APPROVAL_SECRET so a missing env var
    degrades to "still encrypted, but with a key that also lives elsewhere"
    rather than to plaintext. Set CREDENTIAL_KEY in production and keep it out
    of wherever the database backups go — encryption at rest buys nothing if the
    key sits next to the ciphertext.
    """
    from cryptography.fernet import Fernet
    raw = os.environ.get("CREDENTIAL_KEY", "")
    if raw:
        key = raw.encode()
        if len(key) != 44:  # not already url-safe base64 of 32 bytes
            key = base64.urlsafe_b64encode(hashlib.sha256(key).digest())
    else:
        key = base64.urlsafe_b64encode(
            hashlib.sha256(f"cred:{config.APPROVAL_SECRET}".encode()).digest())
    return Fernet(key)


def _encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def _decrypt(blob: str) -> str:
    if not blob:
        return ""
    try:
        return _fernet().decrypt(blob.encode()).decode()
    except Exception:  # noqa: BLE001 — a key rotation should not crash a read
        return ""


# --------------------------------------------------------------------------
# Read.
# --------------------------------------------------------------------------

def resolve(tenant: str, provider: str) -> dict:
    """The live credential for one client and provider, or {}.

    Database first, env blob second. The fallback is deliberate and load-bearing
    during the migration: an account whose client has not connected anything
    keeps running on the value Gomeh pasted into Render, and switches over the
    moment a connect link is used. Nothing needs a cutover.
    """
    with db.SessionLocal() as s:
        row = (s.query(db.Credential)
               .filter(db.Credential.tenant == tenant,
                       db.Credential.provider == provider,
                       db.Credential.status == "active").first())
        if row and row.secret:
            return {"secret": _decrypt(row.secret), "source": "client",
                    **(row.meta or {})}
    return _from_env(tenant, provider)


def _from_env(tenant: str, provider: str) -> dict:
    """The pre-tenant path: a name on the Tenant row into an env-group blob."""
    from . import tenants
    t = tenants.get(tenant)
    if not t:
        return {}
    if provider == "shopify" and t.shopify_store:
        cfg = config.SHOPIFY_STORES.get(t.shopify_store) or {}
        if cfg:
            return {"secret": cfg.get("token", ""), "domain": cfg.get("domain", ""),
                    "source": "env"}
    if provider == "google" and t.gmail_alias:
        acct = config.GMAIL_ACCOUNTS.get(t.gmail_alias) or {}
        if acct:
            return {"secret": acct.get("refresh_token", ""),
                    "email": acct.get("email", ""), "source": "env"}
    return {}


def status(tenant: str) -> list[dict]:
    """Per provider: connected or not, how, when it last verified.

    Never includes the secret. The owner does not need to see a client's API key
    and there is no screen on which showing it would be an improvement.
    """
    with db.SessionLocal() as s:
        rows = {r.provider: r for r in s.query(db.Credential).filter(
            db.Credential.tenant == tenant).all()}
    from . import oauth
    out = []
    for key, spec in PROVIDERS.items():
        row = rows.get(key)
        env = _from_env(tenant, key)
        if row and row.status == "active" and row.last_error:
            # Still the credential in use — see `recheck`. "We could not verify
            # this" is a third state between connected and missing, and
            # collapsing it into either one is how the console starts lying.
            state, detail = "not verifying", (row.last_error or "")[:160]
        elif row and row.status == "active":
            state, detail = "connected", f"by {row.granted_by or 'the client'}"
            # A partial grant is a connection with a dark half, and the only
            # place that can ever be said is here — the token itself works.
            for scope in (row.meta or {}).get("missing_scopes") or []:
                detail += f" · not granted: {scope.rsplit('/', 1)[-1]}"
        elif row and row.status == "failed":
            state, detail = "failed", (row.last_error or "")[:120]
        elif env.get("secret"):
            state, detail = "connected", "from the env group (not yet moved over)"
        else:
            state, detail = "missing", ""
        # An OAuth provider is self-serve once the app credentials exist. Before
        # that it is not "coming soon", it is one env var away, and saying which
        # is the difference between a blocker someone can clear and a mystery.
        blocked = oauth.configured(key) if spec["kind"] == "oauth" else ""
        out.append({
            "provider": key, "name": spec["name"], "kind": spec["kind"],
            "capability": spec["capability"], "state": state, "detail": detail,
            "last_verified": (db.as_utc(row.last_verified).date().isoformat()
                              if row and row.last_verified else ""),
            "self_serve": spec["kind"] == "api_key" or not blocked,
            "blocked_by": blocked,
        })
    return out


# --------------------------------------------------------------------------
# Write.
# --------------------------------------------------------------------------

def store(tenant: str, provider: str, secret: str, meta: dict | None = None,
          granted_by: str = "") -> dict:
    """Verify against the live API, then save. Refuses to store what fails.

    Order matters: a credential is checked before it is written, so a client
    typing a key with a trailing space finds out on the spot rather than
    producing a silent failure a week later in something that reads it.
    """
    spec = PROVIDERS.get(provider)
    if not spec:
        return {"ok": False, "error": f"unknown provider {provider!r}"}
    secret = (secret or "").strip()
    if not secret:
        return {"ok": False, "error": f"{spec['name']} needs a {spec['field']}."}
    meta = {k: (v or "").strip() for k, v in (meta or {}).items() if v}
    meta, why = _normalize_meta(provider, meta)
    if why:
        return {"ok": False, "error": why}
    for field in spec["also"]:
        if not meta.get(field):
            return {"ok": False, "error": f"{spec['also'][field]}"}
    if spec["starts"] and not secret.startswith(spec["starts"]):
        return {"ok": False,
                "error": f"That does not look like a {spec['name']} "
                         f"{spec['field']} — they begin with {spec['starts']}."}

    probe = _probe(provider, secret, meta)
    if not probe["ok"]:
        return {"ok": False, "error": probe["error"]}

    with db.SessionLocal() as s:
        row = (s.query(db.Credential)
               .filter(db.Credential.tenant == tenant,
                       db.Credential.provider == provider).first())
        if not row:
            row = db.Credential(tenant=tenant, provider=provider)
            s.add(row)
        row.kind = spec["kind"]
        row.secret = _encrypt(secret)
        row.meta = meta
        row.status = "active"
        row.granted_by = granted_by or row.granted_by or ""
        row.granted_at = db.utcnow()
        row.last_verified = db.utcnow()
        row.last_error = ""
        s.commit()
    return {"ok": True, "detail": probe.get("detail", "")}


def store_oauth(tenant: str, provider: str, result: dict,
                granted_by: str = "") -> dict:
    """Save what `oauth.exchange` came back with. Never called with a raw code.

    The split from `store()` is deliberate rather than cosmetic. `store()`
    validates a pasted string — a prefix, some required companion fields — and
    then probes it. None of that applies here: the string was issued by the
    provider seconds ago and the provider already told us it is good, so
    re-probing would only add a second way to fail. What replaces the probe is
    the scope check, which is the thing an API key never had.

    A narrower grant than we asked for is stored and REPORTED, not refused. The
    connection genuinely works for the scopes that were granted, and refusing
    it outright would leave a client who unticked Calendar with no connection
    at all rather than most of one. `missing_scopes` on the row is what the
    console reads to say which half is dark.
    """
    spec = PROVIDERS.get(provider)
    if not spec:
        return {"ok": False, "error": f"unknown provider {provider!r}"}
    if not result.get("ok") or not result.get("secret"):
        return {"ok": False, "error": result.get("error") or "sign-in failed"}

    missing = list(result.get("missing") or [])
    meta = {k: v for k, v in {
        "label": result.get("label", ""),
        "missing_scopes": missing,
        "expires_at": int(result.get("expires_at") or 0),
    }.items() if v}

    with db.SessionLocal() as s:
        row = (s.query(db.Credential)
               .filter(db.Credential.tenant == tenant,
                       db.Credential.provider == provider).first())
        if not row:
            row = db.Credential(tenant=tenant, provider=provider)
            s.add(row)
        row.kind = "oauth"
        row.secret = _encrypt(result["secret"])
        row.meta = meta
        row.scopes = " ".join(result.get("granted") or [])
        row.status = "active"
        row.granted_by = granted_by or row.granted_by or ""
        row.granted_at = db.utcnow()
        row.last_verified = db.utcnow()
        row.last_error = ""
        s.commit()

    _invalidate(tenant, provider)
    detail = result.get("label") or f"{spec['name']} connected"
    if missing:
        detail += (" — but these were not granted: "
                   + ", ".join(m.rsplit("/", 1)[-1] for m in missing))
    return {"ok": True, "detail": detail, "missing": missing}


def recheck(tenant: str, provider: str) -> dict:
    """Re-probe a stored credential and record what happened.

    `store()` verifies once, at the moment of connection, and nothing has ever
    checked again. A key that is rotated, revoked at the provider, or attached
    to an app whose scopes were narrowed goes on reading "connected" with a
    `last_verified` date from whenever it was pasted — which is worse than
    showing nothing, because it is a positive claim that has stopped being
    tested.

    OAuth credentials are skipped rather than failed: probing a Google refresh
    token means minting an access token, and treating "we did not check" as
    "broken" would mark a working connection failed. Absence is a third state
    here too.
    """
    spec = PROVIDERS.get(provider)
    if not spec:
        return {"ok": False, "error": f"unknown provider {provider!r}"}
    if spec["kind"] != "api_key":
        return {"ok": False, "checked": False,
                "error": f"{spec['name']} is a sign-in, not a key — reconnect "
                         f"it to re-verify."}
    with db.SessionLocal() as s:
        row = (s.query(db.Credential)
               .filter(db.Credential.tenant == tenant,
                       db.Credential.provider == provider,
                       db.Credential.status.in_(("active", "failed"))).first())
        if not row or not row.secret:
            return {"ok": False, "checked": False,
                    "error": f"Nothing stored for {spec['name']}."}
        secret, meta = _decrypt(row.secret), dict(row.meta or {})

    probe = _probe(provider, secret, meta)
    with db.SessionLocal() as s:
        row = (s.query(db.Credential)
               .filter(db.Credential.tenant == tenant,
                       db.Credential.provider == provider).first())
        if row:
            # `status` is deliberately NOT set to "failed" here. `resolve()`
            # returns only active rows and falls through to the env blob
            # otherwise, so demoting on a failed probe would silently swap a
            # client's live credential for whatever Gomeh pasted into Render —
            # on one network blip, mid-flight, with nothing downstream
            # questioning it. A probe failing is evidence about the probe as
            # well as about the key. The failure is recorded and shown; which
            # credential is in use does not move until a human decides.
            row.last_error = "" if probe["ok"] else probe["error"][:500]
            if probe["ok"]:
                row.last_verified = db.utcnow()
            s.commit()
    return {"ok": probe["ok"], "checked": True,
            "detail": probe.get("detail", ""), "error": probe.get("error", "")}


def revoke(tenant: str, provider: str) -> str:
    with db.SessionLocal() as s:
        row = (s.query(db.Credential)
               .filter(db.Credential.tenant == tenant,
                       db.Credential.provider == provider).first())
        if not row:
            return "Nothing connected."
        row.status, row.secret = "revoked", ""
        s.commit()
    _invalidate(tenant, provider)
    return f"{PROVIDERS[provider]['name']} disconnected."


def _invalidate(tenant: str, provider: str) -> None:
    """Tell whoever caches this credential that it has changed.

    Only Gmail caches one today, and it does so for the life of the process.
    Connecting and revoking are now things a client does while the worker is
    running, so a revoked mailbox would otherwise go on being read until the
    next deploy — which is the one failure here with a real consequence.
    """
    if provider != "google":
        return
    from . import tenants
    t = tenants.get(tenant)
    alias = (t.gmail_alias if t else "") or tenant
    try:
        from . import gmail_client
        gmail_client.forget(alias)
    except Exception:  # noqa: BLE001 — google libs are optional in test envs
        pass


# Shopify serves an unsupported version by falling back to the oldest supported
# one, so a stale string here degrades quietly rather than breaking — which is
# exactly why it drifted to 2024-10 unnoticed. Pinned and dated so the next
# person can tell at a glance whether it is old.
SHOPIFY_API_VERSION = "2026-01"   # set 2026-08; Shopify supports each for 12mo
KLAVIYO_REVISION = "2024-10-15"   # Klaviyo keeps dated revisions working


def _normalize_meta(provider: str, meta: dict) -> tuple[dict, str]:
    """Fix what a person actually types, and refuse what cannot be fixed.

    Measured against the four inputs a real client is most likely to give,
    every one of which failed before this existed:

      https://acme.myshopify.com   built `https://https://…` and died on a
                                   ConnectError with no usable message
      acme.com                     the storefront domain — the one a merchant
                                   knows — answered, was not an admin API, and
                                   reported "HTTPStatusError"
      acme.com  (WordPress)        no scheme, so httpx refused with
                                   "UnsupportedProtocol"
      trailing slashes / spaces    handled already for spaces, not for slashes

    A wrong value that produces an exception class name on a client's screen is
    the same defect as a silent failure: they cannot act on either. Returns
    (meta, error) — a non-empty error is a refusal made before any request.
    """
    meta = dict(meta)

    if provider == "shopify":
        raw = (meta.get("domain") or "").strip().lower()
        raw = raw.split("://", 1)[-1]          # paste from the browser bar
        raw = raw.split("/", 1)[0].strip()     # any path, any trailing slash
        if raw and not raw.endswith(".myshopify.com"):
            return meta, (
                f"{raw} is the storefront domain. Shopify's API needs the admin "
                f"one, which ends in .myshopify.com — it is in Shopify admin "
                f"under Settings → Domains, and it may be a number rather than "
                f"your brand name.")
        meta["domain"] = raw

    if provider == "wordpress":
        raw = (meta.get("site") or "").strip()
        if raw and "://" not in raw:
            raw = f"https://{raw}"             # nobody types the scheme
        meta["site"] = raw.rstrip("/")

    return meta, ""


def _probe(provider: str, secret: str, meta: dict) -> dict:
    """The lightest authenticated call each provider offers.

    Anything without a probe is accepted as unverified rather than reported as
    working — the same rule `tenants.verify()` follows, for the same reason.
    """
    import httpx
    try:
        if provider == "shopify":
            domain = meta.get("domain", "")
            r = httpx.get(
                f"https://{domain}/admin/api/{SHOPIFY_API_VERSION}/shop.json",
                headers={"X-Shopify-Access-Token": secret}, timeout=20)
            if r.status_code == 401:
                return {"ok": False, "error": "Shopify rejected that token."}
            if r.status_code == 403:
                # A live token whose app was never granted read_products et al.
                # This is the one scope failure a probe CAN see; the rest still
                # surface later, which is why the runbook says grant the full set.
                return {"ok": False,
                        "error": "That token is valid but the app has no read "
                                 "access. Re-check the Admin API scopes on the "
                                 "custom app, then reveal the token again."}
            if r.status_code == 404:
                return {"ok": False,
                        "error": f"No store found at {domain}. Check it against "
                                 f"Settings → Domains in Shopify admin."}
            r.raise_for_status()
            return {"ok": True, "detail": r.json()["shop"]["name"]}
        if provider == "omnisend":
            r = httpx.get("https://api.omnisend.com/v3/contacts?limit=1",
                          headers={"X-API-KEY": secret}, timeout=20)
            if r.status_code in (401, 403):
                return {"ok": False, "error": "Omnisend rejected that API key."}
            r.raise_for_status()
            return {"ok": True, "detail": "Omnisend connected"}
        if provider == "klaviyo":
            r = httpx.get("https://a.klaviyo.com/api/accounts/",
                          headers={"Authorization": f"Klaviyo-API-Key {secret}",
                                   "revision": KLAVIYO_REVISION}, timeout=20)
            if r.status_code in (401, 403):
                return {"ok": False, "error": "Klaviyo rejected that API key."}
            r.raise_for_status()
            return {"ok": True, "detail": "Klaviyo connected"}
        if provider == "wordpress":
            site = meta.get("site", "").rstrip("/")
            r = httpx.get(f"{site}/wp-json/wp/v2/users/me",
                          auth=(meta.get("username", ""), secret), timeout=20)
            if r.status_code in (401, 403):
                return {"ok": False,
                        "error": "WordPress rejected that username and password."}
            r.raise_for_status()
            return {"ok": True, "detail": r.json().get("name", "WordPress connected")}
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout):
        # The two causes are a typo in the address and an outage, and a client
        # can only act on the first — so name it first.
        where = meta.get("domain") or meta.get("site") or PROVIDERS[provider]["name"]
        return {"ok": False,
                "error": f"Could not reach {where}. Check the address is right "
                         f"and that the site is up."}
    except httpx.HTTPStatusError as exc:
        # Something answered and it was not the API we asked for — almost always
        # the wrong address rather than the wrong key.
        return {"ok": False,
                "error": f"{meta.get('domain') or meta.get('site') or 'That address'} "
                         f"answered with HTTP {exc.response.status_code}, which is "
                         f"not a {PROVIDERS[provider]['name']} API. Check the "
                         f"address rather than the key."}
    except httpx.HTTPError:
        return {"ok": False,
                "error": f"Could not reach {PROVIDERS[provider]['name']}. "
                         f"Try again in a moment."}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{exc.__class__.__name__}: {str(exc)[:120]}"}
    return {"ok": True, "detail": "stored without a live check"}


def shopify_config(store_key: str) -> dict:
    """A config-shaped {domain, token} for a Shopify store key, client-first.

    The consuming code addresses stores by the env-blob key on `Tenant
    .shopify_store`, not by tenant. This maps that key back to its account so a
    credential the client connected themselves is used in place of the one
    pasted into Render — with the env value still there if they never do.
    Returns {} when neither exists, so callers keep their own KeyError.
    """
    if not store_key:
        return {}
    with db.SessionLocal() as s:
        t = (s.query(db.Tenant)
             .filter(db.Tenant.shopify_store == store_key).first())
        tenant = t.key if t else store_key
    got = resolve(tenant, "shopify")
    if got.get("source") == "client" and got.get("secret") and got.get("domain"):
        return {"domain": got["domain"], "token": got["secret"]}
    return dict(config.SHOPIFY_STORES.get(store_key) or {})


RENEW_WINDOW_DAYS = 14


def renew_due(now: int | None = None) -> list[dict]:
    """Connections close enough to expiry to be worth renewing, with why.

    Google refresh tokens do not expire on a clock, so nothing here ever
    matches them. Meta long-lived tokens die at about sixty days and cannot be
    refreshed — they are exchanged for a new one while still valid, which means
    the only way a Meta connection survives is if something notices in time.
    Fourteen days is wide enough that a fortnight of failed renewals still
    leaves room to tell someone.

    An expiry of 0 means "no known expiry" — Meta omits `expires_in` for system
    users — and is deliberately not treated as "expired in 1970".
    """
    import time as _time
    from . import oauth
    now = int(now if now is not None else _time.time())
    cutoff = now + RENEW_WINDOW_DAYS * 86400
    out = []
    with db.SessionLocal() as s:
        rows = s.query(db.Credential).filter(
            db.Credential.kind == "oauth",
            db.Credential.status == "active").all()
        for r in rows:
            spec = oauth.FLOWS.get(r.provider) or {}
            if spec.get("stores") != "long_lived":
                continue
            expires = int((r.meta or {}).get("expires_at") or 0)
            if not expires or expires > cutoff:
                continue
            out.append({"tenant": r.tenant, "provider": r.provider,
                        "expires_at": expires, "expired": expires <= now})
    return out


def renew_tick() -> dict:
    """Renew every long-lived token nearing expiry. Failures are recorded, loudly.

    A failed renewal marks the credential `failed` with the provider's own
    reason, which is what puts it on the console as a connection that needs
    attention. The alternative — leaving it `active` until the token actually
    dies — turns a fourteen-day warning into a silent outage discovered by
    whatever tries to read ads data next.
    """
    from . import oauth
    done, failed = [], []
    for due in renew_due():
        tenant, provider = due["tenant"], due["provider"]
        current = resolve(tenant, provider)
        if not current.get("secret"):
            continue
        result = oauth.renew(provider, current["secret"])
        with db.SessionLocal() as s:
            row = (s.query(db.Credential)
                   .filter(db.Credential.tenant == tenant,
                           db.Credential.provider == provider).first())
            if not row:
                continue
            if result["ok"]:
                row.secret = _encrypt(result["secret"])
                row.meta = {**(row.meta or {}),
                            "expires_at": int(result.get("expires_at") or 0)}
                row.last_verified = db.utcnow()
                row.last_error = ""
                done.append(f"{tenant}/{provider}")
            else:
                row.status = "failed"
                row.last_error = result["error"][:500]
                failed.append(f"{tenant}/{provider}: {result['error'][:120]}")
            s.commit()
    return {"renewed": done, "failed": failed}


def google_config(alias: str) -> dict:
    """A config-shaped {email, refresh_token} for a Gmail alias, client-first.

    The exact mirror of `shopify_config`, and it exists for the same reason: the
    consuming code addresses mailboxes by the env-blob key on
    `Tenant.gmail_alias`, not by tenant. Without this a client could complete
    the Google consent screen, have the credential store, verify and appear
    connected on the console — and `email_harvest` would still read the env
    blob, find nothing, and report an account with no mailbox. The connection
    would be real and unreadable, which is worse than absent.

    Returns {} when neither exists, so callers keep their own KeyError.
    """
    if not alias:
        return {}
    with db.SessionLocal() as s:
        t = (s.query(db.Tenant)
             .filter(db.Tenant.gmail_alias == alias).first())
        tenant = t.key if t else alias
    got = resolve(tenant, "google")
    if got.get("source") == "client" and got.get("secret"):
        return {"email": got.get("label", "") or got.get("email", ""),
                "refresh_token": got["secret"]}
    return dict(config.GMAIL_ACCOUNTS.get(alias) or {})


def granted_capabilities(tenant: str) -> set[str]:
    """Every capability this client's own connections turn on.

    `capabilities()` used to ask "is provider X connected" per capability, which
    meant each new provider needed a new clause and `ads`/`analytics` never got
    one. Asking the provider what it grants keeps that in one table.
    """
    return {cap for prov in connected_providers(tenant)
            for cap in GRANTS.get(prov, ())}


def needed_for(tenant: str) -> list[str]:
    """Which providers this account should connect, from the systems installed.

    Asking a venue for a Shopify token is how a connect page stops being used.
    Falls back to the self-serve set when no system is installed yet.
    """
    from . import systems
    caps: set[str] = set()
    for sysrow in systems.for_tenant(tenant):
        spec = systems.CATALOG.get(sysrow.key) or {}
        caps.update(spec.get("requires", ()))
        caps.update(spec.get("requires_any", ()))
    if not caps:
        # No system installed yet is the common case during onboarding, and the
        # old fallback was CONNECTABLE — api-key providers only — so Google
        # never appeared on a new client's connect page at all. The honest
        # default is everything they could connect, not everything we happened
        # to implement first.
        return list(PROVIDERS)
    # Matched against what a provider GRANTS, not its headline capability: a
    # system needing `analytics` is served by a Google sign-in, whose nominal
    # capability is `inbox`.
    return [k for k in PROVIDERS if set(GRANTS.get(k, ())) & caps]


def connected_providers(tenant: str) -> set[str]:
    """Providers this client has connected themselves. Cheap — capabilities()
    calls it on every render, so it reads one indexed column and no secrets."""
    with db.SessionLocal() as s:
        return {r.provider for r in s.query(db.Credential).filter(
            db.Credential.tenant == tenant,
            db.Credential.status == "active").all() if r.secret}
