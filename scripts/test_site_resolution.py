"""Which client a site key resolves to — and what happens when it resolves to none.

The defect this pins was found by asking a plain question: with `blog` going on
for all five accounts, what does `site="coverings"` do? It returned BACI.

`sites.get()` fell back to the primary site for any key it did not hold, and
three of five tenants had no profile at all — `SEO_SITES_JSON` listed baci,
eien and mtw while the tenant registry held agency, baci, eien, coverings and
ironside. Two hand-maintained lists of the same clients, drifted.

What that cost on this path, specifically: `propose_article(site="coverings")`
would have queued a write to Baci's store under a summary reading
`[SEO/coverings]`, and `seo_guard` would have checked it against BACI's ban
list — because `tenant_for` resolves from the PROFILE's domain, not the key
that was asked for. Coverings' own rules would never have run.

Two fixes, both asserted here: the tenant rows decide which clients exist, and
a site NAMED that does not resolve refuses instead of becoming someone else.

    python3 scripts/test_site_resolution.py
"""
import json
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'sr.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
# The shape shipped in .env.example: three sites, and `mtw` keyed differently
# from the `agency` tenant that owns the same domain.
os.environ["SEO_SITES_JSON"] = json.dumps({
    "baci": {"domain": "bacimilanousa.com", "platform": "shopify",
             "creds_key": "baci", "guardrail": "Italian-DESIGNED, never made-in-Italy.",
             "exclude_terms": ["Made In Italy", " handmade "]},
    "eien": {"domain": "eienhealth.com", "platform": "shopify", "creds_key": "eien"},
    "mtw": {"domain": "marketingthatworks.co", "platform": "wordpress",
            "creds_key": "mtw", "voice": "Confident, plain-English B2B."}})
os.environ["SEO_PRIMARY_SITE"] = "baci"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, seo_tools, sites, tenants  # noqa: E402

_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    db.init_db()
    tenants.seed()
    profiles = sites.all_profiles()

    print("— the tenant registry decides which clients exist —")
    for t in tenants.all_tenants():
        if (t.domain or "").strip():
            ck(f"{t.key} has a profile", t.key in profiles)

    print("\n— and each one resolves to ITS OWN site, not the primary's —")
    for key, domain in (("baci", "bacimilanousa.com"),
                        ("eien", "eienhealth.com"),
                        ("agency", "marketingthatworks.co"),
                        ("coverings", "coveringsetc.com"),
                        ("ironside", "miamiironside.com")):
        got = sites.get(key)["domain"]
        ck(f"{key} -> {domain}", got == domain, f"got {got!r}")

    print("\n— a site NAMED that does not resolve refuses —")
    try:
        sites.get("nope")
        ck("unknown site raises", False, "it returned a profile instead")
    except sites.UnknownSite as exc:
        ck("unknown site raises", True)
        ck("the refusal lists what IS known", "coverings" in str(exc), str(exc)[:60])
    ck("blank still means 'the default site'",
       sites.get("")["key"] == "baci",
       "no site named is a real request; a site named that we do not hold is not")

    print("\n— the agent sees a refusal, not a crash —")
    out = seo_tools.dispatch("list_blogs", {"site": "nope"}, {})
    ck("dispatch renders it as a sentence", out.startswith("No site profile"), out[:60])
    ck("not as a Tool error", "Tool error" not in out, out[:60])

    print("\n— env entries MERGE onto the tenant they match, by key or domain —")
    ck("mtw's env voice reaches the agency tenant",
       sites.get("agency")["voice"] == "Confident, plain-English B2B.",
       "matched by domain — the join tenant_scope and seo_guard already use")
    ck("agency is wordpress, from the env entry",
       sites.get("agency")["platform"] == "wordpress")
    ck("site=mtw still resolves (alias kept)",
       sites.get("mtw")["domain"] == "marketingthatworks.co",
       "anything already saying site=mtw keeps working")
    ck("agency and mtw are the SAME profile, not two clients",
       sites.get("mtw")["key"] == sites.get("agency")["key"])
    ck("baci keeps its guardrail",
       sites.get("baci")["guardrail"].startswith("Italian-DESIGNED"))
    ck("exclude_terms are normalised",
       sites.get("baci")["exclude_terms"] == ["made in italy", "handmade"])
    ck("a tenant with no env entry still has a platform",
       sites.get("coverings")["platform"] == "shopify",
       "from the tenant row's cms.platform")

    print("\n— every account reads Search Console through ITS OWN Google —")
    # Owner, 2026-08-26: *"every account has their own google connect."* This
    # reverses §2.12's shared-identity assumption, and the old fallback was
    # already costing: Ironside's own Google is connected, the console files
    # it under the TENANT and sets no alias, so `gmail_alias` was empty and
    # every Search Console read for Ironside went through `personal` — an
    # account whose token is revoked. Its own working connection was never
    # asked.
    for t, expect in (("baci", "baci"), ("eien", "eien"),
                      ("agency", "personal"), ("coverings", "coverings"),
                      ("ironside", "ironside")):
        ck(f"{t} reads through {expect!r}",
           sites.get(t)["google_alias"] == expect,
           str(sites.get(t)["google_alias"]))
    ck("an account with no alias falls back to its own KEY, not the agency's",
       sites.get("ironside")["google_alias"] != "personal",
       "`credentials.google_config` treats an unmatched key AS the tenant, so "
       "the key resolves that account's own credential — borrowing another "
       "account's identity is never the repair")
    from app import google_seo as _gs
    ck("and the reader refuses to substitute one",
       _gs._alias({"google_alias": ""}) == "",
       "returning SEO_GOOGLE_ALIAS here meant a client with no Google of its "
       "own silently read through the agency's")

    print("\n— an unimplemented platform refuses BY NAME —")
    try:
        sites.backend(sites.get("ironside"))
        ck("squarespace does not borrow the Shopify backend", False,
           "it returned a backend — Ironside would write to a store that does "
           "not exist")
    except sites.UnknownSite as exc:
        ck("squarespace does not borrow the Shopify backend", True)
        ck("it names the platform", "squarespace" in str(exc), str(exc)[:70])
    ck("shopify resolves", sites.backend(sites.get("baci")).__name__.endswith("shopify_seo"))
    ck("wordpress resolves", sites.backend(sites.get("agency")).__name__.endswith("wordpress_seo"))

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
