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


def all_profiles() -> dict:
    """All site profiles keyed by site key (primary + SEO_SITES_JSON)."""
    sites: dict = {}
    try:
        raw = json.loads(config.SEO_SITES_JSON)
    except (ValueError, TypeError):
        raw = {}
    for k, v in raw.items():
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
    """Resolve a site profile; falls back to the primary site."""
    sites = all_profiles()
    if site_key and site_key in sites:
        return sites[site_key]
    return sites.get(config.SEO_PRIMARY_SITE) or next(iter(sites.values()))


def backend(profile: dict):
    """The implementation module for a profile's platform (duck-typed: same
    function surface across backends)."""
    from . import shopify_seo, wordpress_seo
    return wordpress_seo if profile.get("platform") == "wordpress" else shopify_seo


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
