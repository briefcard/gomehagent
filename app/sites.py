"""SEO site profiles + backend resolution + link grounding.

One SEO agent serves many client properties across platforms. A *site profile*
is the per-client config (domain, Semrush market, platform, creds, brand rules);
the *backend* is the platform implementation (Shopify / WordPress) that reads and
writes that site. The research layer (Semrush) is platform-agnostic; only the
implementation backend differs — same role, same tools, different site.

verify_links() is the grounding guarantee: every link in proposed content is
HTTP-checked against the real site before anything is queued, so the agent never
publishes a hallucinated URL or a product/service link that doesn't exist.
"""
import json
import re

import httpx

from . import config


def _primary() -> dict:
    """The primary site profile, built from the SEO_* env (back-compatible)."""
    return {"key": config.SEO_PRIMARY_SITE, "domain": config.SEO_DOMAIN,
            "database": config.SEO_DATABASE, "platform": config.SEO_PLATFORM,
            "creds_key": config.SEO_STORE, "exclude_terms": config.SEO_EXCLUDE_TERMS,
            "voice": config.SEO_VOICE, "guardrail": config.SEO_GUARDRAIL,
            "google_alias": config.SEO_GOOGLE_ALIAS,
            "gsc_site": config.SEO_GSC_SITE, "ga4_property": config.SEO_GA4_PROPERTY}


class UnknownSite(Exception):
    """A site was NAMED and does not resolve.

    It exists because the alternative was silence. `get()` fell back to the
    primary site for any key it did not hold, so `site="coverings"` returned
    BACI — same shape as `capabilities()` reporting a declared capability as
    wired (§2.29): the name says one client and the resolution quietly becomes
    another. On this path it writes. An article proposed for Coverings would
    have queued against Baci's store, under a summary reading
    `[SEO/coverings]`, checked against Baci's ban list — because
    `seo_guard.tenant_for` resolves from the PROFILE's domain, not the key
    that was asked for. Three of five tenants had no profile at all.
    """


def _brand_rules(brand) -> dict:
    """Voice, guardrail and exclude_terms FROM THE KB.

    These three used to exist only in `SEO_SITES_JSON`, which meant a new
    organisation got `voice: ""`, `guardrail: ""`, `exclude_terms: []` and the
    SEO role wrote for it with no brand rules at all — while `KbBrand` held
    exactly these fields for that same account. Baci's env `exclude_terms` is
    literally its banned-claims list, keyed in a second place by hand: the same
    two-lists-of-one-thing defect as the site registry, one field down.

    The KB is the multi-tenant store and it is the one a CLIENT can fill
    themselves through `/intake/<token>`. Env stays as an override for the
    accounts that already have entries.
    """
    if not brand:
        return {"voice": "", "guardrail": "", "exclude_terms": []}
    voice = brand.voice or {}
    tone = ", ".join(t for t in (voice.get("tone") or []) if t)
    never = [n for n in (voice.get("never_say") or []) if n]
    banned = [b.strip().lower() for b in (brand.banned_claims or []) if b.strip()]
    guard = " ".join(filter(None, [
        (brand.positioning or "").strip(),
        ("Never say: " + "; ".join(never) + "." if never else ""),
        ("Banned claims: " + "; ".join(banned) + "." if banned else "")]))
    return {"voice": tone, "guardrail": guard, "exclude_terms": banned}


def _from_tenants() -> dict:
    """Site profiles derived from the tenant registry.

    THE TENANT ROWS DECIDE WHICH CLIENTS EXIST, THE CONNECTION DECIDES THE
    PLATFORM, AND THE KB DECIDES THE BRAND RULES. None of the three is a thing
    an operator declares by hand, which is the point: a new organisation is
    created at `/admin/tenant_add`, connects its store or site at
    `/connect/<token>`, fills its KB at `/intake/<token>`, and has a working
    SEO profile without anybody editing Python or an env blob.

    `platform` resolves through `credentials.wired_capabilities` rather than a
    local rule, because that function is the single source of truth for "is
    this connected" (§2.29 exists because a second one drifted). A DECLARED
    platform is the fallback, not the primary — it is how Ironside says
    "squarespace", a platform nothing can connect to yet, and `backend()`
    refuses it by name rather than borrowing another platform's client.

    Degrades to {} when the database is unreachable, which is what exists
    today anyway — the refusal in `get()` is what makes that safe.
    """
    from . import credentials, db, tenants
    out: dict = {}
    try:
        rows = tenants.all_tenants()
    except Exception:  # noqa: BLE001 — no DB (offline suites, boot order)
        return out
    try:
        with db.SessionLocal() as s:
            brands = {b.tenant: b for b in s.query(db.KbBrand).all()}
    except Exception:  # noqa: BLE001
        brands = {}
    for t in rows:
        domain = (getattr(t, "domain", "") or "").strip()
        if not domain:
            continue
        cms = getattr(t, "cms", None) or {}
        # What is CONNECTED, first. "client:shopify" / "env:wordpress" both
        # end in the provider, and a provider is a platform here.
        try:
            wired = credentials.wired_capabilities(t.key).get("cms", "")
        except Exception:  # noqa: BLE001
            wired = ""
        platform = (wired.rsplit(":", 1)[-1] if wired else
                    (cms.get("platform") or "")).strip().lower()
        out[t.key] = {
            "key": t.key, "domain": domain,
            "database": ((getattr(t, "analytics", None) or {}).get("semrush_db")
                         or config.SEO_DATABASE),
            "platform": platform,
            # The tenant key is a valid store key: `credentials.shopify_config`
            # falls back to treating an unmatched key AS the tenant, which is
            # exactly how a client-connected store resolves. So a new account
            # needs no `creds_key` at all.
            "creds_key": (cms.get("creds_key")
                          or getattr(t, "shopify_store", "") or t.key),
            # THIS ACCOUNT'S OWN GOOGLE, never the agency's.
            #
            # This fell back to `config.SEO_GOOGLE_ALIAS` ("personal"), which
            # was correct only under the shared-identity model — one Google
            # account granted viewer access on every client's property. The
            # owner corrected that on 2026-08-26: *"every account has their
            # own google connect."*
            #
            # Under per-account connections the fallback is the `sites.get()`
            # defect one field along, and it was already costing: Ironside's
            # own Google is connected, the console files it under the TENANT
            # and sets no alias, so `gmail_alias` is empty and every Search
            # Console read for Ironside went through `personal` — an account
            # whose token is revoked. Its own working connection was never
            # asked.
            #
            # `t.key` is the right second choice and not a fallback to
            # somebody else: `credentials.google_config` treats an unmatched
            # key AS the tenant, so this resolves that account's own
            # credential — the same fix the inbox probe needed an hour ago.
            "google_alias": getattr(t, "gmail_alias", "") or t.key,
            "gsc_site": "", "ga4_property": "",
            **_brand_rules(brands.get(t.key))}
        # ACCEPTED NEGATIVE KEYWORDS live on the tenant row, beside the other
        # research config (`semrush_db`). They are NOT banned claims — a
        # banned claim is a compliance rule about what may be SAID; an
        # exclude term is a research filter about what to LOOK FOR — so they
        # merge alongside the brand rules rather than into them. This is the
        # home the accept button writes to; before it existed the mute-lesson
        # proposals were prose with no backing store anywhere.
        extra = [(x or "").strip().lower()
                 for x in ((getattr(t, "analytics", None) or {})
                           .get("exclude_terms") or [])]
        if extra:
            seen = set(out[t.key]["exclude_terms"])
            out[t.key]["exclude_terms"] = out[t.key]["exclude_terms"] + [
                x for x in extra if x and x not in seen]
    return out


def all_profiles() -> dict:
    """All site profiles keyed by site key (tenants + SEO_SITES_JSON + primary).

    An env entry merges ONTO the tenant profile it matches — by key, or failing
    that by domain, which is the join `seo_guard.tenant_for` and
    `tenant_scope` already use. Matching by domain is what keeps the `mtw`
    entry attached to the `agency` tenant instead of standing beside it as a
    fourth client; the env key stays registered as an alias so anything that
    already says `site=mtw` keeps working.
    """
    sites: dict = _from_tenants()
    by_domain = {_norm(v["domain"]): k for k, v in sites.items() if v["domain"]}
    try:
        raw = json.loads(config.SEO_SITES_JSON)
    except (ValueError, TypeError):
        raw = {}
    for k, v in raw.items():
        target = k if k in sites else by_domain.get(_norm(v.get("domain", "")), "")
        if target:
            # Only the fields the env actually sets, so a tenant-derived
            # domain/platform is not overwritten by this block's defaults.
            for fld in ("domain", "database", "platform", "creds_key", "voice",
                        "guardrail", "google_alias", "gsc_site", "ga4_property"):
                if v.get(fld):
                    sites[target][fld] = v[fld]
            if v.get("exclude_terms"):
                sites[target]["exclude_terms"] = [
                    t.strip().lower() for t in v["exclude_terms"] if t.strip()]
            if target != k:
                sites[k] = sites[target]      # alias: site=mtw still resolves
            continue
        sites[k] = {
            "key": k, "domain": v.get("domain", ""),
            "database": v.get("database", "us"),
            "platform": v.get("platform", "shopify"),
            "creds_key": v.get("creds_key", k),
            "exclude_terms": [t.strip().lower() for t in v.get("exclude_terms", [])
                              if t.strip()],
            "voice": v.get("voice", ""),
            "guardrail": v.get("guardrail", ""),
            "google_alias": v.get("google_alias", config.SEO_GOOGLE_ALIAS),
            "gsc_site": v.get("gsc_site", ""),
            "ga4_property": v.get("ga4_property", "")}
    p = _primary()
    sites.setdefault(p["key"], p)
    return sites


def get(site_key: str = "") -> dict:
    """Resolve a site profile. NO SITE NAMED falls back to the primary; a site
    named that does not resolve RAISES.

    The difference is the whole point. Blank means "use the default" and is a
    real request. A key we do not hold means somebody meant a specific client,
    and answering with a different one is worse than answering with nothing —
    see `UnknownSite`.
    """
    sites = all_profiles()
    if site_key:
        if site_key in sites:
            return sites[site_key]
        raise UnknownSite(
            f"No site profile for {site_key!r}. Known: "
            + (", ".join(sorted(sites)) or "none")
            + ". A client needs a tenant row with a domain (and a cms platform), "
              "or an entry in SEO_SITES_JSON — I will not fall back to another "
              "client's site.")
    return sites.get(config.SEO_PRIMARY_SITE) or next(iter(sites.values()))


#: platform -> the module that implements it. A NAME PER ARM, never a bare
#: `else`. It used to read `wordpress if platform == "wordpress" else shopify`,
#: which was harmless only while every site was one of the two — Ironside is
#: `squarespace` and resolved, silently, to the Shopify backend, where it would
#: have tried to write articles to a store named "ironside" that does not
#: exist. Same shape as the `token_style` bare `else` in `oauth.exchange`
#: (§2.31): an unlisted value inheriting the behaviour of the last one.
BACKENDS = {"shopify": "shopify_seo", "wordpress": "wordpress_seo"}


#: How a create-article reply carries the platform's own id for the page it
#: just made. ONE FORMATTER, ONE PARSER, because the reply is a sentence for a
#: person and the id has to survive the trip without turning it into JSON.
#:
#: The id is the difference between a refresh that REVISES the ranking page and
#: one that publishes a second page beside it. Nothing captured it: the reply
#: was read for its URL and thrown away, so `propose_article_revision` — which
#: has existed and worked the whole time — had no `article_id` to address and
#: every blog run queued a create. On a connected store, approving a refresh
#: put a duplicate on the blog.
_ID_MARK = " · id "


def with_article_id(sentence: str, article_id) -> str:
    """Append the platform's id to a backend reply, once, in the one form."""
    aid = str(article_id or "").strip()
    return f"{sentence}{_ID_MARK}{aid}" if aid else sentence


def article_id_in(sentence: str) -> str:
    """The platform id a create-reply carried, or "" — never a guess.

    Empty is a real answer and the callers treat it as one: no id means the
    page cannot be revised in place, which is a different situation from a
    failed publish and gets a different sentence.
    """
    text = str(sentence or "")
    if _ID_MARK not in text:
        return ""
    return text.rsplit(_ID_MARK, 1)[1].split()[0].strip() if \
        text.rsplit(_ID_MARK, 1)[1].strip() else ""


def backend(profile: dict):
    """The implementation module for a profile's platform (duck-typed: same
    function surface across backends). An unimplemented platform REFUSES by
    name rather than borrowing another platform's client."""
    import importlib
    who = profile.get("key") or "this site"
    # `or "shopify"` lived here and was the same defect as the bare `else` it
    # replaced: an account with NOTHING CONNECTED resolved to the Shopify
    # backend and would have tried to write to a store that does not exist.
    # Absent is not a platform, and it has its own sentence because the fix is
    # different — connect something, rather than build a backend.
    platform = (profile.get("platform") or "").strip().lower()
    if not platform:
        raise UnknownSite(
            f"{who} has no CMS connected, so there is nothing to publish to. "
            f"Connect a site or store at /connect/<token> — the platform "
            f"follows from the connection.")
    mod = BACKENDS.get(platform)
    if not mod:
        raise UnknownSite(
            f"{who} is on {platform!r}, which has no backend built. "
            f"Implemented: {', '.join(sorted(BACKENDS))}.")
    return importlib.import_module(f".{mod}", __package__)


def block() -> str:
    """Dynamic context: which client sites this SEO agent serves, so the agent
    always knows the active site, its platform, and its per-site brand rules."""
    sites = all_profiles()
    lines = []
    for p in sites.values():
        lines.append(f"- {p['key']}: {p['domain']} [{p['platform']}]")
        if p.get("guardrail"):
            lines.append(f"    ⚠ GUARDRAIL (obey strictly): {p['guardrail']}")
        if p.get("exclude_terms"):
            lines.append("    never target/claim: " + ", ".join(p["exclude_terms"]))
        if p.get("voice"):
            lines.append("    voice: " + p["voice"])
    return ("\n\nSITES YOU MANAGE (default = " + config.SEO_PRIMARY_SITE
            + "; pass site=<key> to target another). Use each site's platform and "
            "brand/compliance rules; obey every GUARDRAIL strictly; never mix "
            "clients' data, links, voice or rules:\n" + "\n".join(lines))


# ---------------------------------------------------------------------------
# Shared structured-snippet builders (platform-agnostic content)
# ---------------------------------------------------------------------------
def faq_schema(faqs: list) -> dict:
    return {"@context": "https://schema.org", "@type": "FAQPage",
            "mainEntity": [{"@type": "Question", "name": f["question"],
                            "acceptedAnswer": {"@type": "Answer", "text": f["answer"]}}
                           for f in faqs if f.get("question") and f.get("answer")]}


def faq_html(faqs: list) -> str:
    """Visible, extractable FAQ HTML (answer-first H3/P) for the page body."""
    parts = ["<h2>Frequently asked questions</h2>"]
    for f in faqs:
        if f.get("question") and f.get("answer"):
            parts.append(f"<h3>{f['question']}</h3>\n<p>{f['answer']}</p>")
    return "\n".join(parts)


def compose_jsonld(faqs: list | None, extra) -> list:
    """Merge an optional FAQPage with extra JSON-LD (Article/Breadcrumb/ItemList).
    Returns a list of schema objects (one <script> can hold an array)."""
    items: list = []
    if faqs:
        fs = faq_schema(faqs)
        if fs["mainEntity"]:
            items.append(fs)
    if extra:
        if isinstance(extra, str):
            try:
                extra = json.loads(extra)
            except (ValueError, TypeError):
                extra = None
        if isinstance(extra, list):
            items += extra
        elif isinstance(extra, dict):
            items.append(extra)
    return items


def jsonld_script(structured: list) -> str:
    """Inline <script> JSON-LD for platforms that allow it in content (WordPress)."""
    return ('<script type="application/ld+json">' + json.dumps(structured)
            + "</script>")


def _norm(domain: str) -> str:
    """Bare host, lowercased — the join key shared with `tenant_scope`."""
    d = (domain or "").strip().lower()
    for pre in ("https://", "http://"):
        if d.startswith(pre):
            d = d[len(pre):]
    return d.split("/")[0].removeprefix("www.")


def _domain_host(profile: dict) -> str:
    return (profile.get("domain") or "").replace("https://", "").replace(
        "http://", "").strip("/").lower()


def verify_links(profile: dict, html: str) -> dict:
    """GROUNDING: extract every href in `html` and HTTP-check it resolves.
    Internal links (relative or same-domain) that 404/fail are 'broken' and must
    be fixed before publishing. Returns {ok, broken, external}. A page that links
    to real products/collections passes; a hallucinated URL is caught here."""
    host = _domain_host(profile)
    base = "https://" + host
    hrefs = re.findall(r'href=["\']([^"\']+)["\']', html or "")
    ok, broken, external = [], [], []
    seen = set()
    for h in hrefs:
        if not h or h in seen or h.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        seen.add(h)
        if h.startswith("/"):
            url, internal = base + h, True
        elif h.startswith("http"):
            url = h
            internal = host in h.lower()
        else:
            url, internal = base + "/" + h, True
        status = 0
        try:
            r = httpx.head(url, follow_redirects=True, timeout=10)
            if r.status_code in (403, 405) or r.status_code >= 500:
                r = httpx.get(url, follow_redirects=True, timeout=10)
            status = r.status_code
        except Exception:  # noqa: BLE001 — network/DNS errors -> treat as unresolved
            status = 0
        entry = {"href": h, "url": url, "status": status}
        if status and status < 400:
            (ok if internal else external).append(entry)
        elif internal:
            broken.append(entry)
        else:
            external.append({**entry, "note": "external link not reachable"})
    return {"ok": ok, "broken": broken, "external": external}
