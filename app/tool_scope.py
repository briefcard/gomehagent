"""One account boundary for every tool, whichever role owns it.

The first version of this gated the eleven shared `data_tools` and stopped
there. An audit of the roles found **39 tools across admin and seo taking the
account as a model-supplied argument** — including `queue_email_draft`, which
drafts mail *as* an account, and `propose_seo_update`, which publishes to a live
store. Gating one pack and not the others is not a boundary, it is a preference.

The rule, applied uniformly:

  * while an account is active, the parameter naming an account is **removed
    from the schema the model sees**, so it cannot address one;
  * the resolved value is **injected at dispatch**;
  * a call that names a *different* account is **refused by name**, never
    silently redirected — a silent substitution teaches the model it worked;
  * a tool whose connection is not wired is **not offered at all**, which also
    cuts what is sent every turn.

`ACCOUNT_PARAMS` is the completeness guard: any tool whose schema exposes one of
those names must be registered in `SCOPED` or the isolation test fails. That is
what stops the fortieth tool from quietly reopening this.
"""
from __future__ import annotations

# Parameter names that mean "which account". A tool exposing one of these and
# not appearing in SCOPED is a hole, and the test says so by name.
ACCOUNT_PARAMS = ("store", "account", "alias", "site", "tenant")

# How to turn a tenant into the value each parameter expects. Three vocabularies
# exist for the same idea — an inbox alias, a Shopify store key, and an SEO site
# profile key — which is itself on the list of things to collapse.
_RESOLVERS = {
    "account": lambda t: t.gmail_alias or "",
    "alias": lambda t: t.gmail_alias or "",
    "store": lambda t: t.shopify_store or "",
    # The account itself, for tools that work on the client rather than on one
    # of its connected properties. Same rule as the other three: the model
    # never sees this parameter and never chooses a value for it.
    "tenant": lambda t: t.key or "",
}


def _site_for(t) -> str:
    """The SEO profile key for a tenant.

    `sites.py` is a parallel registry keyed off SEO_SITES_JSON, so the mapping
    is by key, then by domain. A tenant with no profile has no SEO site, and
    its SEO tools are withheld rather than defaulted to the primary site — which
    is what the unscoped code did, and is how one client's content work would
    have been done against another's property.
    """
    from . import connections, sites
    try:
        profiles = sites.all_profiles()
    except Exception:  # noqa: BLE001 — a missing SEO config is not an outage
        return ""
    if t.key in profiles:
        return t.key
    # One normaliser, shared with `connections.tenant_for_site`, which is this
    # same join run backwards. The inline version here lowercased and stripped
    # `www.` but not the scheme, so a profile whose domain was written
    # `https://acme.com` matched nothing while its inverse matched fine — two
    # implementations of one rule disagreeing, which is the whole reason
    # `app/connections.py` exists.
    dom = connections.norm_domain(t.domain or "")
    for key, p in profiles.items():
        if dom and connections.norm_domain(p.get("domain", "")) == dom:
            return key
    return ""


_RESOLVERS["site"] = _site_for


# tool -> (parameter naming the account, capability it needs)
# "" as the capability means "no connection required, but still scoped".
SCOPED: dict[str, tuple[str, str]] = {
    # --- shared data tools -------------------------------------------------
    "shopify_find_orders":   ("store", "commerce"),
    "shopify_order_details": ("store", "commerce"),
    "drive_search":          ("account", "inbox"),
    "email_history_search":  ("account", "inbox"),
    "read_email":            ("account", "inbox"),
    "read_email_attachment": ("account", "inbox"),
    "find_contacts":         ("account", "inbox"),
    # --- admin: reads ------------------------------------------------------
    "schedule_brief":        ("account", "inbox"),
    "calendar_events":       ("account", "inbox"),
    "find_unsubscribes":     ("account", "inbox"),
    "chase_invoices":        ("account", "inbox"),
    "export_tax_receipts":   ("account", "inbox"),
    # --- admin: writes, the ones that actually act as a client -------------
    "queue_email_draft":     ("account", "inbox"),
    "organize_emails":       ("account", "inbox"),
    "save_file_to_drive":    ("account", "inbox"),
    "calendar_create_event": ("account", "inbox"),
    "reschedule_event":      ("account", "inbox"),
    "add_voice_rule":        ("account", "inbox"),
    "sync_catalog":          ("account", "inbox"),
    "log_inbound_inventory": ("store", "commerce"),
    # --- seo: research -----------------------------------------------------
    "semrush_domain_overview":    ("site", ""),
    "semrush_top_keywords":       ("site", ""),
    "semrush_competitors":        ("site", ""),
    "semrush_keyword_metrics":    ("site", ""),
    "semrush_related_keywords":   ("site", ""),
    "semrush_questions":          ("site", ""),
    "semrush_opportunity_finder": ("site", ""),
    "seo_snapshot":               ("site", ""),
    "seo_progress":               ("site", ""),
    # --- seo: the client's own properties ----------------------------------
    "gsc_list_sites":       ("site", ""),
    "ga4_list_properties":  ("site", ""),
    "seo_link_google":      ("site", ""),
    "gsc_top_queries":      ("site", ""),
    "gsc_top_pages":        ("site", ""),
    "gsc_page_queries":     ("site", ""),
    "gsc_trend":            ("site", ""),
    "gsc_inspect_url":      ("site", ""),
    "ga4_overview":         ("site", ""),
    "ga4_landing_pages":    ("site", ""),
    "list_collections":     ("site", ""),
    "find_items":           ("site", ""),
    "get_seo":              ("site", ""),
    "verify_links":         ("site", ""),
    # --- seo: writes to a live storefront ----------------------------------
    "propose_seo_update":            ("site", ""),
    "propose_new_collection":        ("site", ""),
    "propose_content_page":          ("site", ""),
    "propose_theme_schema_renderer": ("site", ""),
    # --- the data layer, as one tool ---------------------------------------
    "run_skill":            ("tenant", ""),
}


#: Tools whose DESCRIPTION depends on the account.
#:
#: `run_skill` is the only one, and it has to be: the whole point is that the
#: agent is shown which skills can run for THIS client and what each blocked
#: one is waiting on, instead of a static list it has to guess against. A
#: registry rather than an `if name == ...` in the loop, because the second
#: entry is where that pattern goes wrong and this file has watched it happen
#: twice (`oauth.configured`, `capabilities`).
DYNAMIC_DESCRIPTION: dict = {}


def _register_dynamic() -> None:
    from . import skill, skill_pack  # noqa: F401 — importing registers the pack
    DYNAMIC_DESCRIPTION["run_skill"] = skill.tool_description


def handles(tenant: str) -> dict[str, str]:
    """Every vocabulary this account answers to, resolved once.

    `account_for` reads the Tenant row and, for `site`, re-parses
    `SEO_SITES_JSON` on every call — and `filter_tools` called it once PER
    TOOL. With eighty-odd schemas that is eighty database round trips and
    eighty JSON parses to build a tool list, on every single turn of every
    agent. Nothing was wrong with the answer; it was just being computed
    from scratch for each tool that asked.

    One read, one dict. `filter_tools` uses this; `guard` still asks for a
    single parameter, since it handles one call at a time.
    """
    from . import tenants
    t = tenants.get(tenant)
    if not t:
        return {}
    return {param: (fn(t) or "") for param, fn in _RESOLVERS.items()}


def account_for(tenant: str, param: str) -> str:
    """The value this account resolves to for one parameter, or ""."""
    from . import tenants
    t = tenants.get(tenant)
    if not t:
        return ""
    fn = _RESOLVERS.get(param)
    return fn(t) if fn else ""


def filter_tools(tools: list[dict], tenant: str) -> list[dict]:
    """The schemas this account may use, with the account parameter removed."""
    if not tenant:
        return tools
    from . import tenants
    caps = tenants.capabilities(tenant)
    resolved = handles(tenant)
    out = []
    for spec in tools:
        if spec.get("name") in DYNAMIC_DESCRIPTION or spec.get("name") == "run_skill":
            if not DYNAMIC_DESCRIPTION:
                _register_dynamic()
            fn = DYNAMIC_DESCRIPTION.get(spec.get("name"))
            if fn:
                spec = {**spec, "description": fn(tenant)}
        scoped = SCOPED.get(spec.get("name", ""))
        if not scoped:
            out.append(spec)
            continue
        param, need = scoped
        if need and not caps.get(need):
            continue
        if not resolved.get(param):
            continue  # nothing to address for this client — do not offer it
        schema = dict(spec.get("input_schema") or {})
        schema["properties"] = {k: v for k, v in
                                (schema.get("properties") or {}).items()
                                if k != param}
        schema["required"] = [r for r in (schema.get("required") or [])
                              if r != param]
        out.append({**spec, "input_schema": schema})
    return out


def guard(name: str, args: dict, tenant: str) -> tuple[dict | None, str]:
    """Enforce the boundary on one call.

    Returns (args, "") to proceed with the account injected, or (None, message)
    to refuse. The refusal is returned to the model as the tool result, so it
    learns the boundary rather than retrying.
    """
    if not tenant:
        return args, ""
    scoped = SCOPED.get(name)
    if not scoped:
        return args, ""
    param, need = scoped
    resolved = account_for(tenant, param)
    if not resolved:
        return None, (f"{tenant} has no {need or param} configured, so {name} "
                      f"cannot run for this account. Connect it first.")
    supplied = args.get(param)
    if supplied and supplied != resolved:
        return None, (f"Refused: this conversation is about {tenant}. "
                      f"Switch accounts to work on {supplied!r}.")
    return {**args, param: resolved}, ""
