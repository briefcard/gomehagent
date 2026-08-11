"""Tenant registry + who-am-I-working-on-right-now.

Two jobs:

  1. RESOLVE  — given a tenant key, what is it connected to? Which inbox,
     which Shopify store, which ESP, which ad account. Every system asks here
     rather than reading env JSON directly, so adding a client is a row.

  2. SCOPE    — given a Telegram chat id, who is this and what may they see?
     Owner switches freely; a client is pinned to one tenant. Scope comes from
     the user row, never from anything the caller passes in.

Connection fields hold KEYS into the existing credential dicts
(SHOPIFY_STORES, GMAIL_ACCOUNTS) or vault references — never secrets.
"""
from __future__ import annotations

from . import config, db

# Capabilities a system can require. resolve() reports which are wired, so a
# pipeline can refuse cleanly ("Ironside has no ESP") instead of failing deep
# inside a publish call.
CAPABILITIES = ("inbox", "commerce", "esp", "cms", "ads", "analytics",
                "design", "crm")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def get(key: str) -> db.Tenant | None:
    with db.SessionLocal() as s:
        t = s.get(db.Tenant, key)
        if t:
            s.expunge(t)
        return t


def all_tenants(include_paused: bool = False) -> list[db.Tenant]:
    with db.SessionLocal() as s:
        q = s.query(db.Tenant)
        if not include_paused:
            q = q.filter(db.Tenant.status == "active")
        rows = q.order_by(db.Tenant.kind.desc(), db.Tenant.key).all()
        s.expunge_all()
        return rows


def capabilities(key: str) -> dict:
    """Which integrations this tenant actually has wired.

    A capability is 'wired' only if the tenant names it AND the underlying
    credential exists. Naming a Shopify store that isn't in SHOPIFY_STORES is
    a misconfiguration that should surface here, not at publish time.
    """
    t = get(key)
    if not t:
        return {c: False for c in CAPABILITIES}
    return {
        "inbox": bool(t.gmail_alias and t.gmail_alias in config.GMAIL_ACCOUNTS),
        "commerce": bool(t.shopify_store and t.shopify_store in config.SHOPIFY_STORES),
        "esp": bool((t.esp or {}).get("provider")),
        "cms": bool((t.cms or {}).get("platform")),
        "ads": bool((t.ads or {}).get("meta_account_id")
                    or (t.ads or {}).get("google_customer_id")),
        "analytics": bool((t.analytics or {}).get("ga4_property")
                          or (t.analytics or {}).get("gsc_site")),
        "design": bool((t.design or {}).get("canva_brand_id")),
        "crm": bool((t.crm or {}).get("provider")),
    }


def resolve(key: str) -> dict:
    """Everything a system needs to operate as this tenant."""
    t = get(key)
    if not t:
        return {"error": f"unknown tenant {key!r}"}
    caps = capabilities(key)
    return {
        "key": t.key, "name": t.name, "kind": t.kind, "domain": t.domain,
        "timezone": t.timezone, "systems": list(t.systems or []),
        "connections": {
            "inbox": t.gmail_alias, "commerce": t.shopify_store,
            "esp": t.esp, "cms": t.cms, "ads": t.ads,
            "analytics": t.analytics, "design": t.design, "crm": t.crm,
        },
        "capabilities": caps,
        "missing": [c for c, ok in caps.items() if not ok],
    }


def requires(key: str, *needed: str) -> tuple[bool, list[str]]:
    """Gate for a system: can this tenant run it, and if not, what's absent."""
    caps = capabilities(key)
    absent = [c for c in needed if not caps.get(c)]
    return (not absent), absent


# ---------------------------------------------------------------------------
# Users + active context
# ---------------------------------------------------------------------------

def user_for_chat(chat_id: str | int) -> db.User | None:
    with db.SessionLocal() as s:
        u = s.query(db.User).filter(
            db.User.telegram_chat_id == str(chat_id),
            db.User.status == "active").first()
        if u:
            s.expunge(u)
        return u


def visible_tenants(user: db.User | None) -> list[str]:
    """What this user may operate on. Owners see all; everyone else is pinned."""
    if user is None:
        return []
    if user.role == "owner":
        return [t.key for t in all_tenants()]
    return [user.tenant_key] if user.tenant_key else []


def active(user: db.User | None) -> str:
    """Current working context. Falls back to the only tenant a client has."""
    if user is None:
        return ""
    if user.role != "owner":
        return user.tenant_key or ""
    if user.active_tenant:
        return user.active_tenant
    return "agency"  # sensible default: your own book


def switch(user: db.User | None, key: str) -> str:
    """Change context. Refuses anything outside the user's scope."""
    if user is None:
        return "Unknown user."
    key = (key or "").strip().lower()
    allowed = visible_tenants(user)
    if key not in allowed:
        return (f"No access to {key!r}. You can use: "
                f"{', '.join(allowed) or '(none)'}")
    if user.role != "owner":
        return f"You're scoped to {key} — nothing to switch."
    with db.SessionLocal() as s:
        row = s.get(db.User, user.id)
        row.active_tenant = key
        s.commit()
    t = get(key)
    caps = capabilities(key)
    on = ", ".join(c for c, ok in caps.items() if ok) or "nothing wired yet"
    return f"Now working on {t.name}. Connected: {on}."


def summary_line(key: str) -> str:
    t = get(key)
    if not t:
        return f"{key} — unknown"
    caps = capabilities(key)
    wired = sum(1 for ok in caps.values() if ok)
    return f"{t.key:11s} {t.name[:26]:26s} {wired}/{len(CAPABILITIES)} wired"


# ---------------------------------------------------------------------------
# Seed — the five real businesses, from what this project has established.
# Connection keys reference existing config dicts; blanks are honest gaps.
# ---------------------------------------------------------------------------

_SEED = [
    dict(key="agency", name="MarketingThatWorks.co", kind="own",
         domain="marketingthatworks.co", gmail_alias="personal",
         systems=["lead_responder", "reports"],
         notes="Tenant zero. Owner is both operator and approver."),
    dict(key="baci", name="Baci Milano USA", kind="own",
         domain="bacimilanousa.com", gmail_alias="baci", shopify_store="baci",
         esp={"provider": "omnisend", "credential_ref": "OMNISEND_BACI"},
         cms={"platform": "shopify", "creds_key": "baci"},
         ads={"meta_account_id": "949335500698690"},
         analytics={"semrush_db": "us"},
         systems=["campaign_email", "service_desk", "reports"],
         notes="Omnisend confirmed via app embed in published theme."),
    dict(key="eien", name="Eien Health", kind="own",
         domain="eienhealth.com", gmail_alias="eien",
         esp={"provider": "omnisend", "credential_ref": "OMNISEND_EIEN"},
         systems=["reorder_engine", "reports"],
         notes="84.9% one-time buyers, 33 active subs — reorder engine testbed."),
    dict(key="coverings", name="Coverings Etc", kind="client",
         domain="coveringsetc.com",
         cms={"platform": "shopify", "creds_key": ""},
         crm={"provider": "salesforce", "creds_key": ""},
         analytics={"semrush_db": "us"},
         systems=["blog", "reports"],
         notes="Shopify in build; ESP unnamed; no inbox connected yet."),
    dict(key="ironside", name="Miami Ironside", kind="client",
         domain="miamiironside.com",
         cms={"platform": "squarespace", "creds_key": ""},
         systems=["lead_responder", "reports"],
         notes="1:1 enquiry response, not broadcast. Blocked on rate cards."),
]


def seed(force: bool = False) -> dict:
    added, skipped = [], []
    with db.SessionLocal() as s:
        for row in _SEED:
            existing = s.get(db.Tenant, row["key"])
            if existing and not force:
                skipped.append(row["key"])
                continue
            if existing:
                s.delete(existing)
                s.flush()
            s.add(db.Tenant(**row))
            added.append(row["key"])
        s.commit()
    return {"added": added, "skipped": skipped}


def seed_owner(chat_id: str, name: str = "Gomeh") -> dict:
    """Register the owner against a Telegram chat id."""
    with db.SessionLocal() as s:
        u = s.query(db.User).filter(
            db.User.telegram_chat_id == str(chat_id)).first()
        if u:
            u.role, u.name = "owner", name
        else:
            s.add(db.User(name=name, telegram_chat_id=str(chat_id),
                          role="owner", active_tenant="agency"))
        s.commit()
    return {"owner": name, "chat_id": str(chat_id)}
