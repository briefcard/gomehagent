"""SEO tool pack for the `seo` role — multi-client, multi-platform.

Research (Semrush) is platform-agnostic. Implementation (read/write the site) is
routed to a per-platform backend (Shopify / WordPress) resolved from the active
site profile (see sites.py), so the SAME tools serve Baci & Eien (Shopify) and
MarketingThatWorks (WordPress) — pass site=<key> to target a client, default is
the primary site.

Grounding: propose_* verifies every link in the content against the real site
(sites.verify_links) before anything queues — the agent never publishes a
hallucinated URL or a product/service link that doesn't exist. Writes are
approval-gated; nothing publishes until Gomeh approves.
"""
import json

import httpx

from . import config, db, memory, sites

SEMRUSH_BASE = "https://api.semrush.com/"

# Tools that take a domain / database — filled from the active site profile.
_NEEDS_DOMAIN = {"semrush_domain_overview", "semrush_top_keywords",
                 "semrush_competitors", "semrush_opportunity_finder",
                 "seo_snapshot", "seo_progress"}
_NEEDS_DB = {"semrush_domain_overview", "semrush_top_keywords", "semrush_competitors",
             "semrush_keyword_metrics", "semrush_related_keywords",
             "semrush_questions", "semrush_opportunity_finder", "seo_snapshot"}
# GSC/GA4 tools take the whole site profile (google_alias, gsc_site, ga4_property).
_GOOGLE_TOOLS = {"gsc_top_queries", "gsc_top_pages", "gsc_page_queries", "gsc_trend",
                 "gsc_inspect_url", "ga4_overview", "ga4_landing_pages",
                 "gsc_list_sites", "ga4_list_properties", "seo_link_google"}


# ---------------------------------------------------------------------------
# Semrush client (platform-agnostic research)
# ---------------------------------------------------------------------------
def _semrush(report: str, **params) -> list[dict] | str:
    if not config.SEMRUSH_API_KEY:
        return "Semrush is not configured (set SEMRUSH_API_KEY in the environment)."
    query = {"type": report, "key": config.SEMRUSH_API_KEY, **params}
    try:
        r = httpx.get(SEMRUSH_BASE, params=query, timeout=30)
    except Exception as exc:  # noqa: BLE001
        return f"Semrush request failed ({exc.__class__.__name__})."
    body = r.text.strip()
    if body.startswith("ERROR") or r.status_code != 200:
        if "NOTHING FOUND" in body.upper():
            return "No Semrush data for that query."
        return f"Semrush error: {body[:160]}"
    lines = body.splitlines()
    if len(lines) < 2:
        return "No Semrush data for that query."
    headers = [h.strip() for h in lines[0].split(";")]
    rows = []
    for line in lines[1:]:
        cells = line.split(";")
        if len(cells) == len(headers):
            rows.append(dict(zip(headers, cells)))
    return rows


def _f(v: str) -> float:
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def semrush_domain_overview(domain: str = "", database: str = "") -> str:
    rows = _semrush("domain_rank", domain=domain or config.SEO_DOMAIN,
                    database=database or config.SEO_DATABASE)
    if isinstance(rows, str):
        return rows
    return json.dumps(rows[0] if rows else {})


def semrush_top_keywords(domain: str = "", database: str = "",
                         limit: int = 30, sort: str = "tr_desc") -> str:
    rows = _semrush("domain_organic", domain=domain or config.SEO_DOMAIN,
                    database=database or config.SEO_DATABASE,
                    display_limit=min(int(limit or 30), 100), display_sort=sort)
    if isinstance(rows, str):
        return rows
    slim = [{"keyword": r.get("Keyword"), "position": r.get("Position"),
             "volume": r.get("Search Volume"), "cpc": r.get("CPC"),
             "url": r.get("Url"), "traffic_pct": r.get("Traffic (%)")} for r in rows]
    return json.dumps(slim)


def semrush_competitors(domain: str = "", database: str = "", limit: int = 15) -> str:
    rows = _semrush("domain_organic_organic", domain=domain or config.SEO_DOMAIN,
                    database=database or config.SEO_DATABASE,
                    display_limit=min(int(limit or 15), 50))
    if isinstance(rows, str):
        return rows
    slim = [{"competitor": r.get("Domain"),
             "common_keywords": r.get("Common Keywords"),
             "organic_keywords": r.get("Organic Keywords"),
             "competition_level": r.get("Competitor Relevance")} for r in rows]
    return json.dumps(slim)


def semrush_keyword_metrics(phrases: str, database: str = "") -> str:
    rows = _semrush("phrase_these", phrase=phrases,
                    database=database or config.SEO_DATABASE)
    if isinstance(rows, str):
        return rows
    slim = [{"keyword": r.get("Keyword"), "volume": r.get("Search Volume"),
             "cpc": r.get("CPC"), "competition": r.get("Competition"),
             "results": r.get("Number of Results")} for r in rows]
    return json.dumps(slim)


def semrush_related_keywords(phrase: str, database: str = "", limit: int = 30) -> str:
    rows = _semrush("phrase_related", phrase=phrase,
                    database=database or config.SEO_DATABASE,
                    display_limit=min(int(limit or 30), 60), display_sort="nq_desc")
    if isinstance(rows, str):
        return rows
    slim = [{"keyword": r.get("Keyword"), "volume": r.get("Search Volume"),
             "cpc": r.get("CPC"), "competition": r.get("Competition")} for r in rows]
    return json.dumps(slim)


def semrush_questions(phrase: str, database: str = "", limit: int = 30) -> str:
    rows = _semrush("phrase_questions", phrase=phrase,
                    database=database or config.SEO_DATABASE,
                    display_limit=min(int(limit or 30), 60), display_sort="nq_desc")
    if isinstance(rows, str):
        return rows
    slim = [{"question": r.get("Keyword"), "volume": r.get("Search Volume"),
             "cpc": r.get("CPC")} for r in rows]
    return json.dumps(slim)


def semrush_opportunity_finder(domain: str = "", database: str = "",
                               min_volume: int = 50, min_pos: int = 11,
                               max_pos: int = 30, limit: int = 20,
                               exclude_terms: list | None = None) -> str:
    """Keywords where the domain ALREADY ranks page 2-3 with real volume — quick
    wins. exclude_terms (per-site brand guardrail) are never recommended."""
    rows = _semrush("domain_organic", domain=domain or config.SEO_DOMAIN,
                    database=database or config.SEO_DATABASE,
                    display_limit=200, display_sort="nq_desc")
    if isinstance(rows, str):
        return rows
    terms = exclude_terms if exclude_terms is not None else config.SEO_EXCLUDE_TERMS
    picks, excluded = [], 0
    for r in rows:
        kw = r.get("Keyword") or ""
        if any(t in kw.lower() for t in terms):
            excluded += 1
            continue
        pos, vol, cpc = _f(r.get("Position")), _f(r.get("Search Volume")), _f(r.get("CPC"))
        if min_pos <= pos <= max_pos and vol >= min_volume:
            score = vol * (cpc + 0.1) / pos
            picks.append((score, {"keyword": kw, "position": int(pos),
                                  "volume": int(vol), "cpc": r.get("CPC"),
                                  "url": r.get("Url")}))
    picks.sort(key=lambda x: x[0], reverse=True)
    out = [p[1] for p in picks[:int(limit or 20)]]
    if not out:
        return ("No page-2/3 opportunities matched the filter — try a lower "
                "min_volume or a wider position range.")
    result = {"opportunities": out}
    if excluded:
        result["excluded_brand_guardrail_keywords"] = excluded
        result["note"] = "Excluded keywords barred by this site's brand guardrail."
    return json.dumps(result)


def capture_snapshot(domain: str = "", database: str = "") -> str:
    domain = domain or config.SEO_DOMAIN
    database = database or config.SEO_DATABASE
    ov = _semrush("domain_rank", domain=domain, database=database)
    if isinstance(ov, str):
        return ov
    o = ov[0] if ov else {}
    kw = _semrush("domain_organic", domain=domain, database=database,
                  display_limit=50, display_sort="tr_desc")
    top = []
    if isinstance(kw, list):
        top = [{"keyword": r.get("Keyword"), "position": r.get("Position"),
                "volume": r.get("Search Volume"), "url": r.get("Url"),
                "traffic_pct": r.get("Traffic (%)")} for r in kw]
    with db.SessionLocal() as s:
        s.add(db.SeoSnapshot(
            domain=domain, database=database, source="semrush",
            rank=o.get("Rank", ""), organic_keywords=o.get("Organic Keywords", "0"),
            organic_traffic=o.get("Organic Traffic", "0"),
            organic_cost=o.get("Organic Cost", "0"), top_keywords=top))
        s.commit()
    return (f"Snapshot saved for {domain} ({database}): "
            f"{o.get('Organic Keywords', '?')} organic keywords, "
            f"{o.get('Organic Traffic', '?')} est. traffic/mo, "
            f"Semrush rank {o.get('Rank', '?')}.")


def seo_progress(domain: str = "") -> str:
    domain = domain or config.SEO_DOMAIN
    with db.SessionLocal() as s:
        snaps = (s.query(db.SeoSnapshot)
                 .filter(db.SeoSnapshot.domain == domain,
                         db.SeoSnapshot.source == "semrush")
                 .order_by(db.SeoSnapshot.at.desc()).limit(2).all())
    if len(snaps) < 2:
        return ("Only one snapshot so far — need at least two to compare. Run "
                "seo_snapshot now and again next week.")
    cur, prev = snaps[0], snaps[1]
    d_kw = _f(cur.organic_keywords) - _f(prev.organic_keywords)
    d_tr = _f(cur.organic_traffic) - _f(prev.organic_traffic)
    prev_pos = {r.get("keyword"): _f(r.get("position")) for r in (prev.top_keywords or [])}
    gained, lost = [], []
    for r in (cur.top_keywords or []):
        k, now = r.get("keyword"), _f(r.get("position"))
        if k in prev_pos and prev_pos[k] and now:
            delta = prev_pos[k] - now
            if delta >= 1:
                gained.append({"keyword": k, "from": int(prev_pos[k]), "to": int(now)})
            elif delta <= -1:
                lost.append({"keyword": k, "from": int(prev_pos[k]), "to": int(now)})
    return json.dumps({
        "domain": domain, "period": f"{prev.at:%Y-%m-%d} -> {cur.at:%Y-%m-%d}",
        "organic_keywords_change": int(d_kw), "organic_traffic_change": int(d_tr),
        "moved_up": sorted(gained, key=lambda x: x["to"])[:15],
        "moved_down": sorted(lost, key=lambda x: x["to"])[:15]})


def seo_context_block() -> str:
    """Injected into the SEO role each turn: which client sites it manages + the
    primary site's current baseline."""
    block = sites.block()
    with db.SessionLocal() as s:
        snap = (s.query(db.SeoSnapshot)
                .filter(db.SeoSnapshot.domain == config.SEO_DOMAIN)
                .order_by(db.SeoSnapshot.at.desc()).first())
    if snap:
        block += (f"\n\nPRIMARY SITE BASELINE ({snap.domain}, captured {snap.at:%b %d}): "
                  f"{snap.organic_keywords} organic kw, {snap.organic_traffic} traffic/mo, "
                  f"Semrush rank {snap.rank}.")
    else:
        block += ("\n\nNo SEO baseline yet for " + config.SEO_DOMAIN
                  + " — call seo_snapshot once to establish the yardstick.")
    return block


# ---------------------------------------------------------------------------
# Implementation (Shopify / WordPress) — proposed, then approval-gated
# ---------------------------------------------------------------------------
def _build_content_fields(profile: dict, args: dict) -> dict:
    """Assemble write fields, turning faqs/jsonld into BOTH extractable FAQ HTML
    and structured data. Shopify -> JSON-LD on a metafield; WordPress (and any
    INLINE_JSONLD backend) -> JSON-LD embedded inline in the content."""
    fields = {k: args[k] for k in ("title", "handle", "seo_title", "seo_description")
              if args.get(k) is not None}
    body = args.get("body_html")
    faqs = args.get("faqs")
    if faqs:
        block = sites.faq_html(faqs)
        body = (body + "\n" + block) if body else block
    structured = sites.compose_jsonld(faqs, args.get("jsonld"))
    if structured:
        if getattr(sites.backend(profile), "INLINE_JSONLD", False):
            body = (body or "") + "\n" + sites.jsonld_script(structured)
        else:
            fields["structured_data"] = structured
    if body is not None:
        fields["body_html"] = body
    return fields


def _link_grounding(profile: dict, fields: dict) -> str | None:
    """Verify every link in the proposed content resolves on the real site.
    Returns an error message (blocking) if internal links are broken, else None."""
    body = fields.get("body_html")
    if not body or "href=" not in body:
        return None
    report = sites.verify_links(profile, body)
    if report["broken"]:
        bad = ", ".join(b["href"] for b in report["broken"])
        return ("BLOCKED — these internal links don't resolve on "
                f"{profile['domain']}: {bad}. Use find_items to get the real URLs "
                "and re-propose. (I won't publish hallucinated links.)")
    return None


def _propose(name: str, args: dict, profile: dict) -> str:
    from . import approvals

    site = profile["key"]
    if name == "propose_theme_schema_renderer":
        if profile.get("platform") == "wordpress":
            return ("Not needed on WordPress — JSON-LD is embedded inline in the "
                    "page content, so there's no theme snippet to install.")
        ap_id = approvals.request_approval(
            "shopify_theme_asset",
            f"[SEO/{site}] Install structured-data renderer in theme <head> (one-time)",
            {"site": site, "bucket": "seo"})
        return (f"Queued for your approval ({ap_id[:8]}): one-time theme setup so "
                "JSON-LD renders into <head> and is rich-result eligible.")

    if name == "propose_seo_update":
        fields = _build_content_fields(profile, args)
        if not fields:
            return "Nothing to update — give seo_title, seo_description, body_html, and/or faqs."
        blocked = _link_grounding(profile, fields)
        if blocked:
            return blocked
        resource = args.get("resource", "collection")
        extras = ("+FAQ schema" if args.get("faqs") else "") + (
            " +JSON-LD" if args.get("jsonld") else "")
        ap_id = approvals.request_approval(
            "seo_update",
            f"[SEO/{site}] Update {resource} {args['resource_id']}: "
            + (args.get("seo_title") or "copy/structured-data") + extras,
            {"site": site, "resource": resource,
             "resource_id": str(args["resource_id"]), "fields": fields, "bucket": "seo"})
        return (f"Queued for your approval ({ap_id[:8]}): update {resource} "
                f"{args['resource_id']} on {site}.\nSEO title: "
                f"{args.get('seo_title', '(unchanged)')}\nMeta: "
                f"{args.get('seo_description', '(unchanged)')}\n"
                "Nothing changes on the site until you approve.")
    if name == "propose_new_collection":
        fields = _build_content_fields(profile, args)
        if not fields.get("title"):
            return "A title is required."
        blocked = _link_grounding(profile, fields)
        if blocked:
            return blocked
        item_ids = [str(p) for p in (args.get("product_ids") or [])]
        ap_id = approvals.request_approval(
            "seo_new_collection",
            f"[SEO/{site}] New collection/landing: {fields['title']}"
            + (f" (+{len(item_ids)} items)" if item_ids else ""),
            {"site": site, "fields": fields, "item_ids": item_ids, "bucket": "seo"})
        return (f"Queued for your approval ({ap_id[:8]}): create '{fields['title']}'"
                + (f" with {len(item_ids)} items" if item_ids else "")
                + (", FAQ schema" if args.get("faqs") else "")
                + f" on {site}. Not created until you approve.")
    # propose_content_page
    fields = _build_content_fields(profile, args)
    if not fields.get("title") or not fields.get("body_html"):
        return "A page needs a title and body_html (structured, answer-first)."
    blocked = _link_grounding(profile, fields)
    if blocked:
        return blocked
    ap_id = approvals.request_approval(
        "seo_new_page",
        f"[SEO/{site}] New page: {fields['title']}"
        + (" (+FAQ schema)" if args.get("faqs") else ""),
        {"site": site, "fields": fields, "bucket": "seo"})
    return (f"Queued for your approval ({ap_id[:8]}): create page "
            f"'{fields['title']}'"
            + (" with FAQPage structured data" if args.get("faqs") else "")
            + f" on {site}. Not published until you approve.")


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------
_SITE = {"site": {"type": "string", "description": "Client site key (default: "
                  "primary). E.g. baci, eien, mtw."}}


def _t(props: dict, required=None, **extra) -> dict:
    schema = {"type": "object", "properties": {**props, **_SITE}}
    if required:
        schema["required"] = required
    return schema


TOOLS = [
    {"name": "semrush_domain_overview",
     "description": "Current SEO snapshot for a site: authority rank, organic "
                    "keyword count, estimated organic traffic.",
     "input_schema": _t({"domain": {"type": "string"}, "database": {"type": "string"}})},
    {"name": "semrush_top_keywords",
     "description": "Organic keywords a site ranks for (position, volume, CPC, "
                    "URL, traffic share). sort: tr_desc/nq_desc/po_asc.",
     "input_schema": _t({"domain": {"type": "string"}, "database": {"type": "string"},
                         "limit": {"type": "integer"}, "sort": {"type": "string"}})},
    {"name": "semrush_competitors",
     "description": "Top organic competitors for a site — who competes for the "
                    "same keywords.",
     "input_schema": _t({"domain": {"type": "string"}, "database": {"type": "string"},
                         "limit": {"type": "integer"}})},
    {"name": "semrush_keyword_metrics",
     "description": "Volume/CPC/competition for specific keywords. phrases: "
                    "SEMICOLON-separated.",
     "input_schema": _t({"phrases": {"type": "string"}, "database": {"type": "string"}},
                        required=["phrases"])},
    {"name": "semrush_related_keywords",
     "description": "Semantically related keywords for a seed — for clustering/"
                    "ideation. (Drifts to head terms; use for breadth.)",
     "input_schema": _t({"phrase": {"type": "string"}, "database": {"type": "string"},
                         "limit": {"type": "integer"}}, required=["phrase"])},
    {"name": "semrush_questions",
     "description": "Question-format keywords the audience asks — the basis for "
                    "value-centric, answer-engine (GEO) content.",
     "input_schema": _t({"phrase": {"type": "string"}, "database": {"type": "string"},
                         "limit": {"type": "integer"}}, required=["phrase"])},
    {"name": "semrush_opportunity_finder",
     "description": "The money tool: keywords where the site ALREADY ranks page "
                    "2-3 with real volume — quick wins. Honors the site's brand "
                    "guardrail (excluded terms).",
     "input_schema": _t({"domain": {"type": "string"}, "database": {"type": "string"},
                         "min_volume": {"type": "integer"}, "min_pos": {"type": "integer"},
                         "max_pos": {"type": "integer"}, "limit": {"type": "integer"}})},
    {"name": "gsc_list_sites",
     "description": "List the Search Console properties this Google account can "
                    "access. Use when the site's GSC property isn't auto-matched, "
                    "then pin it with seo_link_google.",
     "input_schema": _t({})},
    {"name": "ga4_list_properties",
     "description": "List the GA4 properties this Google account can access (id + "
                    "name). Use when the GA4 property isn't auto-matched, then pin "
                    "it with seo_link_google.",
     "input_schema": _t({})},
    {"name": "seo_link_google",
     "description": "Pin which GSC property (e.g. sc-domain:bacimilanousa.com) "
                    "and/or GA4 property id belong to this site, and SAVE it to "
                    "the agent DB for future use. Only needed when auto-discovery "
                    "is ambiguous.",
     "input_schema": _t({"gsc_site": {"type": "string"},
                         "ga4_property": {"type": "string"}})},
    {"name": "gsc_top_queries",
     "description": "Google Search Console — REAL queries the site ranks for "
                    "(clicks, impressions, CTR, avg position) over the last `days` "
                    "(default 28). Ground truth vs Semrush estimates. The GSC "
                    "property is auto-discovered by domain on first use.",
     "input_schema": _t({"days": {"type": "integer"}, "limit": {"type": "integer"}})},
    {"name": "gsc_top_pages",
     "description": "GSC — REAL top pages by clicks/impressions/position over the "
                    "last `days`.",
     "input_schema": _t({"days": {"type": "integer"}, "limit": {"type": "integer"}})},
    {"name": "gsc_page_queries",
     "description": "GSC — the real queries driving a specific page (page_url is "
                    "the full URL). Use to see what a page actually ranks for "
                    "before optimizing it.",
     "input_schema": _t({"page_url": {"type": "string"}, "days": {"type": "integer"},
                         "limit": {"type": "integer"}}, required=["page_url"])},
    {"name": "gsc_trend",
     "description": "GSC — clicks/impressions by date over `days` (default 90) "
                    "with first-half vs second-half direction. Real growth/decline.",
     "input_schema": _t({"days": {"type": "integer"}})},
    {"name": "gsc_inspect_url",
     "description": "GSC URL inspection — is this URL actually indexed by Google? "
                    "verdict, coverage, last crawl, canonical.",
     "input_schema": _t({"url": {"type": "string"}}, required=["url"])},
    {"name": "ga4_overview",
     "description": "GA4 — REAL traffic by channel (sessions, users, conversions) "
                    "over `days` (default 28). Where traffic comes from and what "
                    "converts.",
     "input_schema": _t({"days": {"type": "integer"}})},
    {"name": "ga4_landing_pages",
     "description": "GA4 — ORGANIC landing pages by sessions + conversions: which "
                    "SEO pages actually earn traffic and revenue (page-level ROI).",
     "input_schema": _t({"days": {"type": "integer"}, "limit": {"type": "integer"}})},
    {"name": "seo_snapshot",
     "description": "Capture and store a timestamped SEO snapshot (overview + top "
                    "50 keywords) as the yardstick for progress. Runs weekly too.",
     "input_schema": _t({"domain": {"type": "string"}, "database": {"type": "string"}})},
    {"name": "seo_progress",
     "description": "Compare the two most recent snapshots: keyword/traffic "
                    "movement + per-keyword position changes.",
     "input_schema": _t({"domain": {"type": "string"}})},
    {"name": "list_collections",
     "description": "List the site's collections (Shopify) or categories "
                    "(WordPress) with real ids/handles/URLs — map keyword "
                    "clusters to existing pages vs. gaps. Read-only.",
     "input_schema": _t({})},
    {"name": "find_items",
     "description": "Find products (Shopify) or pages/posts/services (WordPress) "
                    "by title substring — REAL ids/handles/URLs to link to or "
                    "optimize. Use this to ground every product/service link. "
                    "Read-only.",
     "input_schema": _t({"query": {"type": "string"}, "limit": {"type": "integer"}},
                        required=["query"])},
    {"name": "get_seo",
     "description": "Read current title, handle/URL, description and SEO title/"
                    "meta for a resource. resource: collection|product (Shopify) "
                    "or page|post (WordPress). Read before editing. Read-only.",
     "input_schema": _t({"resource": {"type": "string",
                         "enum": ["collection", "product", "page", "post"]},
                         "resource_id": {"type": "string"}},
                        required=["resource", "resource_id"])},
    {"name": "verify_links",
     "description": "Check that every link in a block of HTML resolves on the "
                    "real site (returns ok / broken / external). Use before "
                    "proposing content; propose_* runs this automatically and "
                    "blocks on broken internal links.",
     "input_schema": _t({"html": {"type": "string"}}, required=["html"])},
    {"name": "propose_seo_update",
     "description": "PROPOSE an SEO edit to an existing resource: SEO title "
                    "(<=60), meta (<=160), structured page copy (body_html with "
                    "real H2/H3, lists, tables), and/or faqs. Read current values "
                    "with get_seo first. Queues for approval — not published until "
                    "Gomeh approves.",
     "input_schema": _t({
         "resource": {"type": "string",
                      "enum": ["collection", "product", "page", "post"]},
         "resource_id": {"type": "string"},
         "seo_title": {"type": "string"}, "seo_description": {"type": "string"},
         "body_html": {"type": "string", "description": "Structured HTML "
                       "(answer-first, H2/H3, lists). Link only to REAL URLs "
                       "(find_items)."},
         "faqs": {"type": "array", "items": {"type": "object", "properties": {
             "question": {"type": "string"}, "answer": {"type": "string"}}},
             "description": "Q&A -> extractable FAQ HTML + FAQPage JSON-LD."},
         "jsonld": {"type": "string", "description": "Optional extra JSON-LD "
                    "(Article/BreadcrumbList/ItemList). Don't duplicate Product/"
                    "Organization schema the platform already emits."}},
         required=["resource", "resource_id"])},
    {"name": "propose_new_collection",
     "description": "PROPOSE a new collection (Shopify) or landing page "
                    "(WordPress) — title, handle, structured body_html, SEO "
                    "title/meta, faqs, and product_ids to include (from "
                    "find_items). Queues for approval.",
     "input_schema": _t({
         "title": {"type": "string"}, "handle": {"type": "string"},
         "body_html": {"type": "string"}, "seo_title": {"type": "string"},
         "seo_description": {"type": "string"},
         "faqs": {"type": "array", "items": {"type": "object", "properties": {
             "question": {"type": "string"}, "answer": {"type": "string"}}}},
         "jsonld": {"type": "string"},
         "product_ids": {"type": "array", "items": {"type": "string"}}},
         required=["title"])},
    {"name": "propose_content_page",
     "description": "PROPOSE a new content/answer page (GEO/SEO). Answer-first "
                    "structured body_html (H2/H3, lists, summary up top); pass "
                    "faqs for FAQPage JSON-LD. Link only to REAL URLs. Queues for "
                    "approval.",
     "input_schema": _t({
         "title": {"type": "string"}, "handle": {"type": "string"},
         "body_html": {"type": "string"}, "seo_title": {"type": "string"},
         "seo_description": {"type": "string"},
         "faqs": {"type": "array", "items": {"type": "object", "properties": {
             "question": {"type": "string"}, "answer": {"type": "string"}}}},
         "jsonld": {"type": "string"}}, required=["title", "body_html"])},
    {"name": "propose_theme_schema_renderer",
     "description": "ONE-TIME (Shopify only): install the theme snippet that "
                    "outputs our JSON-LD metafield into <head>. No-op on "
                    "WordPress (inlined). Idempotent, reversible. Queues for "
                    "approval.",
     "input_schema": _t({})},
    {"name": "save_memory",
     "description": "Save/update a durable note in shared working memory (a "
                    "content plan, a decision). Same topic overwrites.",
     "input_schema": {"type": "object", "properties": {
         "topic": {"type": "string"}, "content": {"type": "string"}},
         "required": ["topic", "content"]}},
    {"name": "forget_memory",
     "description": "Archive a working-memory topic once resolved.",
     "input_schema": {"type": "object", "properties": {
         "topic": {"type": "string"}}, "required": ["topic"]}},
]

_HANDLERS = {
    "semrush_domain_overview": semrush_domain_overview,
    "semrush_top_keywords": semrush_top_keywords,
    "semrush_competitors": semrush_competitors,
    "semrush_keyword_metrics": semrush_keyword_metrics,
    "semrush_related_keywords": semrush_related_keywords,
    "semrush_questions": semrush_questions,
    "semrush_opportunity_finder": semrush_opportunity_finder,
    "seo_snapshot": capture_snapshot,
    "seo_progress": seo_progress,
}


def dispatch(name: str, args: dict, session_files: dict) -> str:
    """Execute one SEO tool call. Resolves the active site profile, routes
    implementation tools to the platform backend, and injects the site's
    domain/database/brand-guardrail into the research tools."""
    try:
        site = args.pop("site", "") if isinstance(args, dict) else ""
        profile = sites.get(site)

        if name == "save_memory":
            return memory.remember(args["topic"], args["content"])
        if name == "forget_memory":
            return memory.forget(args["topic"])
        if name == "verify_links":
            return json.dumps(sites.verify_links(profile, args.get("html", "")))
        if name in ("list_collections", "find_items", "get_seo"):
            backend = sites.backend(profile)
            if name == "list_collections":
                return backend.list_collections(profile)
            if name == "find_items":
                return backend.find_items(profile, args.get("query", ""),
                                          int(args.get("limit", 20)))
            return backend.get_seo(profile, args["resource"], args["resource_id"])
        if name in ("propose_seo_update", "propose_new_collection",
                    "propose_content_page", "propose_theme_schema_renderer"):
            return _propose(name, args, profile)
        if name in _GOOGLE_TOOLS:
            from . import google_seo
            return getattr(google_seo, name)(profile, **args)

        # Research tools — fill domain/database/guardrail from the site profile.
        if name in _NEEDS_DOMAIN and not args.get("domain"):
            args["domain"] = profile["domain"]
        if name in _NEEDS_DB and not args.get("database"):
            args["database"] = profile["database"]
        if name == "semrush_opportunity_finder":
            args["exclude_terms"] = profile["exclude_terms"]
        return _HANDLERS[name](**args)[:8000]
    except Exception as exc:  # noqa: BLE001
        return f"Tool error ({exc.__class__.__name__}): {str(exc)[:200]}"
