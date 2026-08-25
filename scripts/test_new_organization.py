"""Onboarding an organisation nobody wrote code for.

The question this answers, in the owner's words (2026-08-25): *"this should
work across any new organization."* Not the seeded five — any account created
tomorrow, through the product surfaces only.

Before this branch it did not. `/admin/tenant_add` creates a row with no `cms`
block; `GRANTS["shopify"]` granted `commerce` and NOT `cms`, so a client who
connected their store was told the blog system was not ready FOREVER, and the
only cure was an operator hand-writing `cms={"platform": "shopify"}` onto the
tenant row. `SEO_SITES_JSON` was a second hand-kept list, so a new account also
got `voice: ""`, `guardrail: ""`, `exclude_terms: []` — the SEO role wrote for
it with no brand rules while `KbBrand` held exactly those fields for that same
account.

Three things that were declared are derived now: the platform comes from the
CONNECTION, the brand rules come from the KB, and `cms` falls out of a Shopify
credential that actually carries `write_content`.

    python3 scripts/test_new_organization.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'no.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["SEO_SITES_JSON"] = "{}"          # nobody wrote an entry for Acme
os.environ["SEO_PRIMARY_SITE"] = "baci"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import credentials, db, kb, sites  # noqa: E402

_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def new_org(key: str, domain: str) -> None:
    """Exactly what /admin/tenant_add writes: no cms, no store, no systems."""
    with db.SessionLocal() as s:
        s.add(db.Tenant(key=key, name=key.title(), kind="client", domain=domain,
                        business_model="ecom_inventory", systems=[],
                        notes="created via /admin/tenant_add"))
        s.commit()


def connect(tenant: str, provider: str, scopes: str | None) -> None:
    """A connection is a Credential row. `scopes=None` is the api_key/env path,
    which records none — a different fact from an empty grant."""
    with db.SessionLocal() as s:
        s.add(db.Credential(tenant=tenant, provider=provider, site="",
                            kind="oauth" if scopes is not None else "api_key",
                            secret=credentials._encrypt("tok"),
                            meta={"domain": f"{tenant}.myshopify.com"},
                            scopes=scopes if scopes is not None else "",
                            status="active", granted_at=db.utcnow()))
        s.commit()


def main() -> int:
    db.init_db()

    print("— a brand-new account, created and nothing else —")
    new_org("acme", "acme.example")
    ck("it exists as a site", "acme" in sites.all_profiles())
    ck("on its OWN domain", sites.get("acme")["domain"] == "acme.example")
    ck("with no platform, because nothing is connected",
       sites.get("acme")["platform"] == "",
       "a default of 'shopify' here is a guess, and the guess writes")
    ck("cms is not wired", "cms" not in credentials.wired_capabilities("acme"))
    try:
        sites.backend(sites.get("acme"))
        ck("no backend is offered yet", False, "it returned one")
    except sites.UnknownSite:
        ck("no backend is offered yet", True, "refuses by name rather than "
           "borrowing the Shopify client")

    print("\n— the client connects their store. Nothing else happens. —")
    connect("acme", "shopify", "read_products,write_products,read_content,write_content")
    caps = credentials.wired_capabilities("acme")
    ck("cms is wired BY THE CONNECTION", caps.get("cms") == "client:shopify",
       "no operator wrote cms={'platform': 'shopify'} anywhere")
    ck("commerce too", caps.get("commerce") == "client:shopify")
    prof = sites.get("acme")
    ck("the platform follows", prof["platform"] == "shopify")
    ck("creds_key defaults to the tenant key", prof["creds_key"] == "acme",
       "credentials.shopify_config treats an unmatched store key AS the tenant")
    ck("and the backend resolves",
       sites.backend(prof).__name__.endswith("shopify_seo"))

    print("\n— a token WITHOUT write_content does not get cms —")
    new_org("readonly", "readonly.example")
    connect("readonly", "shopify", "read_products,read_content")
    caps = credentials.wired_capabilities("readonly")
    ck("cms refused on a known, insufficient grant", "cms" not in caps,
       "a capability that reads wired and fails at the write is the defect "
       "§2.29 was written to close")
    ck("commerce still granted", caps.get("commerce") == "client:shopify",
       "one missing scope must not disconnect the rest")

    print("\n— an api_key/env connection records no scopes, and still counts —")
    new_org("legacy", "legacy.example")
    connect("legacy", "shopify", None)
    ck("unrecorded scopes grant cms",
       credentials.wired_capabilities("legacy").get("cms") == "client:shopify",
       "unknown is not absent — refusing here would disconnect every account "
       "that works today")

    print("\n— the KB supplies the brand rules, not an env blob —")
    ck("no rules before the KB is filled", sites.get("acme")["guardrail"] == "")
    b = kb.ensure_brand("acme", "Acme Co")
    with db.SessionLocal() as s:
        row = s.get(db.KbBrand, "acme")
        row.positioning = "Mid-century furniture, made to order in Ohio."
        row.voice = {"tone": ["warm", "plain"], "never_say": ["cheap"]}
        s.commit()
    kb.add_banned("acme", "Solid Oak")
    prof = sites.get("acme")
    ck("voice comes from KbBrand.voice.tone", prof["voice"] == "warm, plain")
    ck("guardrail carries positioning", "made to order in Ohio" in prof["guardrail"])
    ck("guardrail carries never_say", "cheap" in prof["guardrail"])
    ck("exclude_terms ARE the banned claims", prof["exclude_terms"] == ["solid oak"],
       "one list, lowercased — the env copy was a second hand-keyed one")

    print("\n— none of that required an SEO_SITES_JSON entry —")
    ck("env is empty and everything above still held",
       os.environ["SEO_SITES_JSON"] == "{}")

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
