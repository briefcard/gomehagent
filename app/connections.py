"""One answer to "what is this client connected to, and with what".

Four registries grew up answering that question independently, and by the time
they were counted a client was defined in three places (`DEFECTS.md` §3) while
the question "which credential opens this property" had four implementations:

  * `credentials` — the client's own connections, encrypted, per tenant.
  * `config.SHOPIFY_STORES` / `GMAIL_ACCOUNTS` / `WORDPRESS_SITES` — the env
    groups, keyed by a name pasted into Render.
  * `db.Tenant.shopify_store` / `.gmail_alias` / `.cms` — names pointing INTO
    those blobs.
  * `sites.py` — SEO site profiles from `SEO_SITES_JSON`, carrying their own
    `creds_key` pointing into the same blobs.

`credentials.resolve` already unified the first two, correctly, per tenant. What
it could not fix is that most consumers do not address a tenant. They address a
store key, an inbox alias, or an SEO site key — three vocabularies for one idea
— so the unification stopped at the door of every module that speaks one of the
other three.

**The measurable consequence, and the reason this module exists.** `shopify_seo`
and `wordpress_seo` — the only two modules that publish to a client's live
website — resolved credentials straight out of the env blobs and never once
called `credentials`. So a client could complete the connect flow, have the
credential stored, probed and shown as connected on the console, grant `cms` or
`commerce` to `wired_capabilities`, and every publish would still refuse with
"add it to WORDPRESS_SITES_JSON". That is `google_config`'s own warning happening
one layer down: *the connection would be real and unreadable, which is worse
than absent.*

So the rule here is the one `resolve` already follows, extended to whichever
vocabulary the caller happens to speak:

    the client's own connection first, the env group second, and a refusal
    BY NAME when neither exists.

Resolution is by **tenant**, never by the env key. That is the part that fixes
rather than papers over: a store connected by OAuth has no env key at all, so
anything joining through `creds_key` can never find it however many fallbacks
it stacks.
"""
from __future__ import annotations

from . import config, credentials


# Which provider serves a site profile's platform. Reused from `credentials`
# rather than restated, because two copies of this map is how the CMS half and
# the SEO half start disagreeing about what "wordpress" means.
PLATFORM_PROVIDER = credentials.CMS_PLATFORM_PROVIDER


def norm_domain(value: str) -> str:
    """A domain comparable to another domain, however it was written."""
    d = (value or "").strip().lower()
    d = d.split("://", 1)[-1]
    d = d.split("/", 1)[0]
    return d[4:] if d.startswith("www.") else d


def tenant_for_site(site_key: str) -> str:
    """Which account an SEO site profile belongs to, or "".

    The inverse of `tool_scope._site_for`, and it has to exist for the same
    reason that one does: the two halves of this system key the same client on
    different names, so crossing between them is a join and not a lookup.

    By key first, then by domain — the two ways a profile and a tenant are
    actually tied together today. Absent is returned as "" and never as the
    primary site: defaulting here would resolve one client's publish against
    another client's credential, which is the single worst thing this file
    could do.
    """
    if not site_key:
        return ""
    from . import db, sites
    profile = (sites.all_profiles() or {}).get(site_key) or {}
    dom = norm_domain(profile.get("domain", ""))
    with db.SessionLocal() as s:
        row = s.query(db.Tenant).filter(db.Tenant.key == site_key).first()
        if row:
            return row.key
        if dom:
            for t in s.query(db.Tenant).all():
                if norm_domain(t.domain or "") == dom:
                    return t.key
    return ""


def _env_for(platform: str, creds_key: str) -> dict:
    """The env-group blob for a platform, in that platform's own shape."""
    if platform == "shopify":
        return dict(config.SHOPIFY_STORES.get(creds_key) or {})
    if platform == "wordpress":
        return dict(config.WORDPRESS_SITES.get(creds_key) or {})
    return {}


#: platform -> the env var its group is actually read from. Named rather than
#: derived from the platform, because `SHOPIFY_STORES_JSON` and
#: `WORDPRESS_SITES_JSON` do not share a spelling and a refusal that sends an
#: operator to a variable that does not exist is worse than one that says
#: nothing.
ENV_GROUP = {"shopify": "SHOPIFY_STORES_JSON",
             "wordpress": "WORDPRESS_SITES_JSON"}


def platform_config(profile: dict) -> tuple[dict, str]:
    """Live credentials for one SEO site profile: ``(config, refusal)``.

    Returns the platform's OWN shape — `{domain, token}` for Shopify,
    `{base_url, user, app_password}` for WordPress — so the backends keep the
    field names they already use and this is a change of source, not a rewrite
    of every call site.

    Exactly one of the two is ever non-empty. A refusal names the account and
    what to connect, because "not configured" sent an operator to an env var
    for a client who had connected the thing correctly through the console.
    """
    platform = (profile.get("platform") or "").strip().lower()
    provider = PLATFORM_PROVIDER.get(platform, "")
    site_key = profile.get("key", "")
    creds_key = profile.get("creds_key", "") or site_key

    if not provider:
        # Ironside declares Squarespace, which no backend implements. Saying so
        # by name beats an empty config that reads as a missing token.
        return {}, (f"site '{site_key}' runs on {platform or 'an unnamed platform'}, "
                    f"which has no backend — nothing can publish to it.")

    tenant = tenant_for_site(site_key)
    if tenant:
        got = credentials.resolve(tenant, provider,
                                  site=profile.get("domain", "")
                                  if provider in credentials.SITE_SCOPED else "")
        if got.get("error"):
            # Several connections and the caller did not say which. `resolve`
            # already refuses rather than picking; carry its words through
            # rather than flattening it to "not configured".
            return {}, got["error"]
        if got.get("secret"):
            if provider == "shopify" and got.get("domain"):
                return {"domain": got["domain"], "token": got["secret"]}, ""
            if provider == "wordpress" and got.get("site"):
                return {"base_url": got["site"], "user": got.get("username", ""),
                        "app_password": got["secret"]}, ""

    env = _env_for(platform, creds_key)
    if env:
        return env, ""

    who = tenant or f"site '{site_key}'"
    return {}, (f"{who} has no {provider} connection — connect it on the "
                f"account's connect page, or add '{creds_key}' to "
                f"{ENV_GROUP.get(platform, 'the env group')}.")
