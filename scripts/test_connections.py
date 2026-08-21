"""A connection the client made themselves must be readable by the code that publishes.

`DEFECTS.md` §3 has said for weeks that *a client is defined in three places* —
the `Tenant` table, `SEO_SITES_JSON` via `sites.py`, and `SeoSiteConfig`. This
suite pins the consequence that made it urgent rather than merely untidy.

`shopify_seo` and `wordpress_seo` are the only two modules that publish to a
client's live website, and both resolved credentials straight out of the env
groups. They never called `credentials`. So a client could finish the connect
flow, have the credential encrypted, probed and displayed as connected, grant
`cms` or `commerce` to `wired_capabilities` — and every publish would still
refuse with "add it to WORDPRESS_SITES_JSON".

Two layers disagreeing about whether an account is connected is the §2.29 shape
one floor down, and `credentials.google_config` had already written the verdict:
*the connection would be real and unreadable, which is worse than absent.*

The negative half matters as much: the env group must keep working untouched
for the accounts that have always run on it, since nothing was cut over.

    python3 scripts/test_connections.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'cx.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["CREDENTIAL_KEY"] = "a-test-encryption-key"

# Only `baci` is in the env group. Every other account below must be reachable
# through its own connection or not at all — which is the whole point.
os.environ["SHOPIFY_STORES_JSON"] = json.dumps(
    {"baci": {"domain": "baci-milano-usa.myshopify.com", "token": "shpat_from_env"}})
os.environ["WORDPRESS_SITES_JSON"] = json.dumps({})
os.environ["SEO_SITES_JSON"] = json.dumps({
    "coverings": {"domain": "coveringsetc.com", "platform": "shopify",
                  "creds_key": "coverings"},
    "baci": {"domain": "bacimilanousa.com", "platform": "shopify",
             "creds_key": "baci"},
    "mtw": {"domain": "marketingthatworks.co", "platform": "wordpress",
            "creds_key": "agencywp"},
    "ironside": {"domain": "miamiironside.com", "platform": "squarespace",
                 "creds_key": ""},
})
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import (connections, credentials as cred, db, shopify_seo,  # noqa: E402
                 sites, tenants, wordpress_seo)

_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    db.init_db()
    tenants.seed()

    real_probe = cred._probe
    cred._probe = lambda p, s, m: {"ok": True, "detail": "stubbed"}
    try:
        # Coverings connects its own Shopify. It has NO entry in
        # SHOPIFY_STORES_JSON and never will — this is what a real client
        # onboarding looks like now.
        res = cred.store("coverings", "shopify", "shpat_coverings_own_token",
                         {"domain": "coverings-etc.myshopify.com"})
        assert res.get("ok"), res
        # The agency connects a WordPress install. The env group is empty.
        res = cred.store("agency", "wordpress", "abcd EFGH ijkl mnop",
                         {"site": "marketingthatworks.co", "username": "editor"})
        assert res.get("ok"), res
    finally:
        cred._probe = real_probe

    prof = sites.all_profiles()

    # --- the defect, stated as the case that used to fail ----------------
    print("— a client's own Shopify reaches the publish path —")
    p = prof["coverings"]
    refusal = shopify_seo._ok(p)
    ck("a client-connected store is publishable with no env entry",
       refusal is None, refusal or "")
    ck("and it does not say 'not configured'",
       not (refusal or "").lower().count("not configured"), refusal or "")
    cfg = shopify_seo._cfg("coverings")
    ck("the DOMAIN resolves from the client's connection, not a KeyError",
       cfg.get("domain") == "coverings-etc.myshopify.com", str(cfg))
    ck("the token comes with it",
       cfg.get("token") == "shpat_coverings_own_token", str(cfg.get("token"))[:12])
    ck("_base builds a real admin URL",
       shopify_seo._base("coverings").startswith(
           "https://coverings-etc.myshopify.com/admin/api/"),
       shopify_seo._base("coverings"))

    print("\n— a client's own WordPress reaches the publish path —")
    p = prof["mtw"]
    refusal = wordpress_seo._ok(p)
    ck("a client-connected install is publishable with an EMPTY env group",
       refusal is None, refusal or "")
    cfg = wordpress_seo._cfg(p) or {}
    ck("base_url comes from the connection",
       cfg.get("base_url") == "https://marketingthatworks.co", str(cfg.get("base_url")))
    ck("so does the application password",
       cfg.get("app_password") == "abcd EFGH ijkl mnop", "")
    ck("and the username", cfg.get("user") == "editor", str(cfg.get("user")))
    ck("nothing is told to edit WORDPRESS_SITES_JSON",
       "WORDPRESS_SITES_JSON" not in (refusal or ""), refusal or "")

    # --- the negative half: nothing was cut over -------------------------
    print("\n— the env group still carries the accounts that always ran on it —")
    p = prof["baci"]
    ck("baci has no client connection", "shopify" not in cred.connected_providers("baci"))
    ck("and is still publishable from the env group", shopify_seo._ok(p) is None,
       shopify_seo._ok(p) or "")
    ck("with the env domain", shopify_seo._cfg("baci").get("domain")
       == "baci-milano-usa.myshopify.com", str(shopify_seo._cfg("baci")))
    ck("and the env token", shopify_seo._cfg("baci").get("token") == "shpat_from_env")

    # --- refusals name the account, not an env var -----------------------
    print("\n— what it says when there really is nothing —")
    orphan = {"key": "nobody", "domain": "nobody.example", "platform": "shopify",
              "creds_key": "nobody"}
    cfg, refusal = connections.platform_config(orphan)
    ck("an unconnected site refuses", not cfg and bool(refusal), refusal)
    ck("naming the site", "nobody" in refusal, refusal)
    ck("and pointing at the connect page, not only at Render",
       "connect" in refusal.lower(), refusal)

    # A client with a WordPress install for a DIFFERENT property. Refusing is
    # right — publishing one site's content to another because it was the only
    # credential available is the kind of thing a client finds out by reading
    # their own website — but "has no wordpress connection" would be false.
    other = {"key": "mtw2", "domain": "blog.marketingthatworks.co",
             "platform": "wordpress", "creds_key": "agencywp"}
    cfg, refusal = connections.platform_config(other)
    if connections.tenant_for_site("mtw2"):
        ck("a connection for another property still refuses", not cfg, str(cfg))
        ck("but says WHICH properties are connected, not that none are",
           "no wordpress connection" not in refusal, refusal)

    cfg, refusal = connections.platform_config(prof["ironside"])
    ck("a platform with no backend refuses by naming the platform",
       not cfg and "squarespace" in refusal.lower(), refusal)
    ck("and does not read as a missing token",
       "token" not in refusal.lower() and "password" not in refusal.lower(), refusal)

    # --- the join itself --------------------------------------------------
    print("\n— site key to account —")
    ck("by key when they match", connections.tenant_for_site("baci") == "baci")
    ck("by DOMAIN when the profile key differs from the account key",
       connections.tenant_for_site("mtw") == "agency",
       connections.tenant_for_site("mtw"))
    ck("an unknown site resolves to nothing, NEVER to the primary site",
       connections.tenant_for_site("no-such-site") == "",
       connections.tenant_for_site("no-such-site"))
    ck("and so does an empty one", connections.tenant_for_site("") == "")

    # --- the two joins are one rule, run in two directions ---------------
    # `tool_scope._site_for` maps an account to its site; `tenant_for_site`
    # maps back. They were written months apart with two copies of the domain
    # comparison, and the copies did not agree — the inline one did not strip a
    # scheme, so a profile whose domain was written `https://acme.com` resolved
    # one way and not the other. A boundary that holds in one direction only is
    # not a boundary.
    print("\n— the account/site join is reversible —")
    from app import tool_scope
    for tenant_key in ("baci", "coverings", "agency"):
        site_key = tool_scope._site_for(tenants.get(tenant_key))
        ck(f"{tenant_key} -> site -> {tenant_key}",
           bool(site_key) and connections.tenant_for_site(site_key) == tenant_key,
           f"site={site_key!r} back={connections.tenant_for_site(site_key)!r}")

    ck("a domain written with a scheme normalises the same as a bare one",
       connections.norm_domain("https://WWW.Acme.com/pricing?x=1")
       == connections.norm_domain("acme.com"),
       connections.norm_domain("https://WWW.Acme.com/pricing?x=1"))

    # --- resolving the account is done once, not once per tool -----------
    # `filter_tools` asked `account_for` for every schema it considered, and
    # `account_for` reads the Tenant row — with the `site` resolver re-parsing
    # SEO_SITES_JSON on top. 48 tools are scoped, 27 of them by site, so one
    # tool list cost 48 database reads and 27 JSON parses. On every turn of
    # every agent. The answer was never wrong; it was recomputed from scratch
    # for each tool that asked for it.
    print("\n— the account is resolved once per tool list —")
    from app import tool_scope
    real_get, seen = tenants.get, {"n": 0}

    def counted(k):
        seen["n"] += 1
        return real_get(k)

    # `run_skill` is excluded: its description is REGENERATED per account (it
    # has to be — the whole point is showing which skills can run for this
    # client), so it costs reads for a reason that has nothing to do with the
    # loop being measured. Leaving it in makes a one-tool cost look like growth.
    _measurable = [(n, v) for n, v in tool_scope.SCOPED.items() if n != "run_skill"]

    def cost(scoped_tools):
        """Account reads taken to filter a list holding `scoped_tools` scoped tools."""
        rows = _measurable[:scoped_tools]
        many = [{"name": n, "input_schema": {"properties": {p: {}}, "required": [p]}}
                for n, (p, _) in rows]
        seen["n"] = 0
        out = tool_scope.filter_tools(many, "baci")
        return seen["n"], out

    tenants.get = counted
    try:
        few, _ = cost(4)
        lots, got = cost(len(_measurable))
    finally:
        tenants.get = real_get

    # The PROPERTY, not a magic number: twelve times the tools must not cost
    # twelve times the reads. A threshold would drift; this cannot pass while
    # the resolution is back inside the loop.
    ck("the cost of a tool list does not grow with the number of tools",
       few == lots, f"{few} reads for 4 scoped tools, {lots} for "
                    f"{len(_measurable)}")
    ck("and the scoping still holds — the account parameter is gone",
       all("store" not in (t.get("input_schema", {}).get("properties") or {})
           for t in got if t["name"] == "shopify_find_orders"))

    # --- L1 and L2 must not disagree -------------------------------------
    # The console says an account is connected by reading `wired_capabilities`.
    # The publish path says so by resolving a credential. When those two
    # disagree, one of the screens is lying to somebody, and that is the entire
    # defect this suite exists for.
    print("\n— the console and the publish path agree —")
    for site_key, profile in prof.items():
        tenant = connections.tenant_for_site(site_key)
        if not tenant:
            continue
        platform = profile.get("platform", "")
        provider = connections.PLATFORM_PROVIDER.get(platform, "")
        if not provider:
            continue
        caps = cred.wired_capabilities(tenant)
        granted = bool(set(cred.GRANTS.get(provider, ())) & set(caps))
        cfg, _ = connections.platform_config(profile)
        ck(f"{tenant}/{platform}: capability chip and publish path match",
           granted == bool(cfg), f"chip={granted} publishes={bool(cfg)}")

    print()
    if _fail:
        print(f"{len(_fail)} FAILED: " + "; ".join(_fail))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
