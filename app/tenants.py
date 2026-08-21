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


def declared_capabilities(key: str) -> dict:
    """What the Tenant row *claims* is set up. Intent, not evidence.

    Kept because it is genuinely useful — it is the onboarding checklist, and
    the gap between declared and wired is exactly the connect-page backlog. It
    is NOT what `capabilities()` returns, and the two must never be conflated
    again: see `capability_detail`.
    """
    t = get(key)
    if not t:
        return {c: False for c in CAPABILITIES}
    return {
        "inbox": bool(t.gmail_alias),
        "commerce": bool(t.shopify_store),
        "esp": bool((t.esp or {}).get("provider")),
        "cms": bool((t.cms or {}).get("platform")),
        "ads": bool((t.ads or {}).get("meta_account_id")
                    or (t.ads or {}).get("google_customer_id")),
        "analytics": bool((t.analytics or {}).get("ga4_property")
                          or (t.analytics or {}).get("gsc_site")),
        "design": bool((t.design or {}).get("canva_brand_id")),
        "crm": bool((t.crm or {}).get("provider")),
    }


def capabilities(key: str) -> dict:
    """Which integrations this tenant actually has wired.

    A capability is wired only if a credential granting it resolves — from the
    client's own connection first, the env group second. `credentials.resolve`
    already unifies those two, so this asks it rather than reimplementing the
    question per capability.

    **This used to lie for half of them.** The docstring promised "the tenant
    names it AND the underlying credential exists", and delivered that for
    `inbox` and `commerce` only. `esp`, `cms`, `ads` and `crm` checked nothing
    but the presence of a key in the Tenant's own JSON column — and
    `credential_ref` ("OMNISEND_BACI") is dereferenced nowhere in this codebase,
    while there is no Omnisend credential anywhere in it. So Baci reported an
    ESP it did not have, and Coverings reported a CMS and a CRM whose
    `creds_key` was the empty string.

    That is §1's *unknown collapsed into a value*: "declared" and "connected"
    are different states and were being reported as one. It is also precisely
    the failure the old docstring said the function existed to prevent — a
    system requiring `esp` passed `systems.ready()`, went live, and would have
    failed deep inside a publish call instead of refusing cleanly.

    Declarations are still available, separately, from `declared_capabilities`.
    """
    from . import credentials as _cred
    if not get(key):
        return {c: False for c in CAPABILITIES}
    wired = _cred.wired_capabilities(key)
    return {c: c in wired for c in CAPABILITIES}


def capability_detail(key: str) -> dict:
    """Per capability: wired, how, declared — and the gap between them.

    `needs_connecting` is the useful column: the client said they have an ESP
    and no credential for one exists. That is a connect link to send, not a
    mystery to debug at publish time.
    """
    wired = {}
    if get(key):
        from . import credentials as _cred
        wired = _cred.wired_capabilities(key)
    declared = declared_capabilities(key)
    return {c: {"wired": c in wired, "via": wired.get(c, ""),
                "declared": declared.get(c, False),
                "needs_connecting": declared.get(c, False) and c not in wired}
            for c in CAPABILITIES}


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


def verify(key: str) -> dict:
    """Actually CALL each wired integration and report what came back.

    capabilities() answers "is it configured" — a cheap dictionary lookup that
    cannot tell a working token from a revoked one, or full scopes from
    read_products only. This answers "does it work", which is the question that
    matters before you trust a report built on it.

    Each probe is the lightest authenticated call the provider offers.
    Anything with no adapter yet is reported as configured-but-unverified
    rather than quietly counted as working.
    """
    t = get(key)
    if not t:
        return {"error": f"unknown tenant {key!r}"}
    caps = capabilities(key)
    out: dict = {}

    # --- commerce -------------------------------------------------------
    if caps["commerce"]:
        try:
            from . import data_tools
            shop = data_tools._shopify(t.shopify_store, "shop.json")["shop"]
            out["commerce"] = {"status": "ok", "detail": shop.get("name", "")}
        except Exception as exc:  # noqa: BLE001
            out["commerce"] = {"status": "FAIL",
                               "detail": f"{exc.__class__.__name__}: {str(exc)[:140]}"}
    else:
        out["commerce"] = {"status": "not configured", "detail": ""}

    # --- inbox ----------------------------------------------------------
    if caps["inbox"]:
        try:
            from . import gmail_client
            with gmail_client._google_lock:
                p = (gmail_client.service_for(t.gmail_alias)
                     .users().getProfile(userId="me").execute())
            out["inbox"] = {"status": "ok",
                            "detail": p.get("emailAddress", t.gmail_alias)}
        except Exception as exc:  # noqa: BLE001
            out["inbox"] = {"status": "FAIL",
                            "detail": f"{exc.__class__.__name__}: {str(exc)[:140]}"}
    else:
        out["inbox"] = {"status": "not configured", "detail": ""}

    # --- analytics (Semrush is the only one with a live client today) ----
    domain = t.domain or ""
    if caps["analytics"] and domain and config.SEMRUSH_API_KEY:
        try:
            from . import seo_tools
            raw = (seo_tools.semrush_domain_overview(
                domain, (t.analytics or {}).get("semrush_db", "us")) or "").strip()
            ok = raw.startswith("{") and raw != "{}"
            out["analytics"] = {"status": "ok" if ok else "FAIL",
                                "detail": raw[:120]}
        except Exception as exc:  # noqa: BLE001
            out["analytics"] = {"status": "FAIL",
                                "detail": f"{exc.__class__.__name__}: {str(exc)[:140]}"}
    elif caps["analytics"]:
        out["analytics"] = {"status": "unverified",
                            "detail": "no SEMRUSH_API_KEY or no domain"}
    else:
        out["analytics"] = {"status": "not configured", "detail": ""}

    # --- no adapter yet: say so rather than imply it works ---------------
    for cap, why in (("esp", "no ESP adapter built yet"),
                     ("cms", "no CMS adapter built yet"),
                     ("ads", "no ads adapter built yet"),
                     ("crm", "no CRM adapter built yet"),
                     ("design", "Canva not connected")):
        out[cap] = ({"status": "unverified", "detail": why} if caps[cap]
                    else {"status": "not configured", "detail": ""})

    tested = [c for c, r in out.items() if r["status"] in ("ok", "FAIL")]
    failed = [c for c, r in out.items() if r["status"] == "FAIL"]
    return {"tenant": key, "name": t.name, "results": out,
            "tested": tested, "failed": failed,
            "healthy": bool(tested) and not failed}


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


def for_alias(alias: str) -> str:
    """Which client owns this inbox, or "".

    The unattended half of the system is addressed by inbox alias, not by
    tenant: the worker polls `GMAIL_ACCOUNTS` and triage is handed an alias.
    This is the one place that turns the one into the other, so the scoping the
    agent gets is available to the code that runs with nobody watching.
    """
    if not alias:
        return ""
    with db.SessionLocal() as s:
        t = s.query(db.Tenant).filter(db.Tenant.gmail_alias == alias).first()
        return t.key if t else ""


def agent_block(key: str) -> str:
    """Who the agent is working for, injected into every turn.

    The agent had no concept of a client at all — `command_agent`, `kernel` and
    `triage` contained zero references to tenants — so it could not tell which
    store a question was about, and had no access to the rules the knowledge
    base already held for that account. This is the bridge.

    Deliberately compact: identity, what is reachable, and the constraints that
    must never be violated. Detail is available through tools; what belongs in
    every turn is the part that changes the answer.
    """
    from . import kb
    t = get(key)
    if not t:
        return ("\n\nACCOUNT: none selected. Say which client this is about "
                "before acting — do not assume.")
    caps = capabilities(key)
    wired = [c for c, ok in caps.items() if ok]
    lines = [f"\n\nACTIVE ACCOUNT: {t.name} (`{t.key}`)"
             f"{' — ' + t.domain if t.domain else ''}",
             f"Connected: {', '.join(wired) if wired else 'nothing yet'}."
             f" Not connected: {', '.join(c for c in CAPABILITIES if c not in wired) or '—'}.",
             "Every tool call and every statement you make is about THIS account. "
             "If a question is about a different client, say so rather than "
             "answering from the wrong one."]

    b = kb.brand(key)
    if b:
        if b.positioning:
            lines.append(f"What they do: {b.positioning}")
        tone = (b.voice or {}).get("tone") or []
        if tone:
            lines.append(f"Voice: {', '.join(tone)}.")
        banned = b.banned_claims or []
        if banned:
            lines.append(
                "NEVER say, in any draft or summary for this account: "
                + "; ".join(banned)
                + ". These are enforced rules, not preferences.")
    ents = kb.entities(key, available_only=False)
    if ents:
        names = ", ".join(e.name for e in ents[:12])
        lines.append(f"They sell ({len(ents)}): {names}"
                     + (" …" if len(ents) > 12 else ""))
    return "\n".join(lines)


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
    dict(key="agency", name="MarketingThatWorks.co", kind="own", business_model="digital_products",
         domain="marketingthatworks.co", gmail_alias="personal",
         systems=["lead_responder", "reports"],
         notes="Tenant zero. Owner is both operator and approver."),
    dict(key="baci", name="Baci Milano USA", kind="own", business_model="ecom_inventory",
         domain="bacimilanousa.com", gmail_alias="baci", shopify_store="baci",
         esp={"provider": "omnisend", "credential_ref": "OMNISEND_BACI"},
         cms={"platform": "shopify", "creds_key": "baci"},
         ads={"meta_account_id": "949335500698690"},
         analytics={"semrush_db": "us"},
         systems=["campaign_email", "service_desk", "reports"],
         notes="Omnisend confirmed via app embed in published theme."),
    dict(key="eien", name="Eien Health", kind="own", business_model="ecom_inventory",
         domain="eienhealth.com", gmail_alias="eien",
         # The store credential has been live in SHOPIFY_STORES all along
         # (/health/connections reports "ok — Eien Health"); this row simply
         # never named it, so `commerce` read unwired and `reorder_engine` —
         # which requires it — could never go live. Seeding skips existing
         # rows, so the deployed database needs the same change applied via
         # /admin/tenant_set?tenant=eien&field=shopify_store&value=eien
         shopify_store="eien",
         esp={"provider": "omnisend", "credential_ref": "OMNISEND_EIEN"},
         systems=["reorder_engine", "reports"],
         notes="84.9% one-time buyers, 33 active subs — reorder engine testbed."),
    dict(key="coverings", name="Coverings Etc", kind="client", business_model="b2b_spec",
         domain="coveringsetc.com",
         cms={"platform": "shopify", "creds_key": ""},
         crm={"provider": "salesforce", "creds_key": ""},
         analytics={"semrush_db": "us"},
         systems=["blog", "reports"],
         notes="Shopify in build; ESP unnamed; no inbox connected yet."),
    dict(key="ironside", name="Miami Ironside", kind="client", business_model="local_venue",
         domain="miamiironside.com",
         cms={"platform": "squarespace", "creds_key": ""},
         systems=["lead_responder", "reports"],
         notes="1:1 enquiry response, not broadcast. Blocked on rate cards."),
]


def seed(force: bool = False) -> dict:
    added, skipped, backfilled = [], [], []
    with db.SessionLocal() as s:
        for row in _SEED:
            existing = s.get(db.Tenant, row["key"])
            if existing and not force:
                # Skipping existing rows is right — but it also meant a
                # classification added to _SEED never reached a row created
                # before it: live eien sat with a BLANK business_model while
                # this file said ecom_inventory, and the planner refused
                # (2026-08-21). A blank is a value nobody chose, so filling
                # ONLY blanks from the seed is a backfill, not an overwrite —
                # anything the owner set (or sets later, on the Connections
                # tab control) is never touched.
                if not (existing.business_model or "").strip() \
                        and row.get("business_model"):
                    existing.business_model = row["business_model"]
                    backfilled.append(row["key"])
                skipped.append(row["key"])
                continue
            if existing:
                s.delete(existing)
                s.flush()
            s.add(db.Tenant(**row))
            added.append(row["key"])
        s.commit()
    return {"added": added, "skipped": skipped, "backfilled": backfilled}


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
