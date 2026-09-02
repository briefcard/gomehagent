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
#: Which account a Semrush call is being made FOR. Passed explicitly, never
#: ambient: one API key serves every client, so a call that cannot say whose
#: work it was is a unit of a shared quota nobody can budget.
def _semrush(report: str, _tenant: str = "", **params) -> list[dict] | str:
    """One Semrush read, recorded against the account that asked for it.

    SEMRUSH IS READ-ONLY AND CANNOT POLLUTE THE SEMRUSH ACCOUNT. This is a GET
    against their index; Projects, Position Tracking and Site Audit are a
    separate surface with separate limits that nothing here touches.

    What IS shared is the QUOTA, and until this was instrumented nothing could
    say which client spent it. Every other platform reaches its API through
    `toolcalls.http_seam` and lands in the ledger with an account attached —
    `seo_tools` imported `toolcalls` nowhere, so Semrush was the one provider
    absent from Diagnostics entirely: no call count, no failure rate, and a
    dying key would have shown up as thin harvests rather than as an error.

    `http_seam` does not fit here — its `tenant_of` maps the seam's first
    argument to an account, and this one's is a report type — so the plain
    recorder is used instead.
    """
    import time as _clock
    from . import toolcalls as _tc

    if not config.SEMRUSH_API_KEY:
        return "Semrush is not configured (set SEMRUSH_API_KEY in the environment)."
    query = {"type": report, "key": config.SEMRUSH_API_KEY, **params}
    _t0 = _clock.monotonic()

    def _log(ok: bool, err: str = "", body: str = "") -> None:
        _tc.record(_tenant, f"semrush_{report}", source="seo",
                   provider="semrush", ok=ok, error=err,
                   ms=int((_clock.monotonic() - _t0) * 1000),
                   bytes_back=len(body or ""))

    try:
        r = httpx.get(SEMRUSH_BASE, params=query, timeout=30)
    except Exception as exc:  # noqa: BLE001
        _log(False, f"{exc.__class__.__name__}")
        return f"Semrush request failed ({exc.__class__.__name__})."
    body = r.text.strip()
    if body.startswith("ERROR") or r.status_code != 200:
        if "NOTHING FOUND" in body.upper():
            # A real answer, not a failure: the index holds nothing for this
            # phrase. Recorded as OK so a quiet niche does not read as a
            # broken key on the Diagnostics failure rate.
            _log(True, body=body)
            return "No Semrush data for that query."
        _log(False, body[:160], body)
        return f"Semrush error: {body[:160]}"
    _log(True, body=body)
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


def semrush_domain_overview(domain: str = "", database: str = "", _tenant: str = "") -> str:
    rows = _semrush("domain_rank", _tenant=_tenant, domain=domain or config.SEO_DOMAIN,
                    database=database or config.SEO_DATABASE)
    if isinstance(rows, str):
        return rows
    return json.dumps(rows[0] if rows else {})


def semrush_top_keywords(domain: str = "", database: str = "",
                         limit: int = 30, sort: str = "tr_desc",
                         _tenant: str = "") -> str:
    rows = _semrush("domain_organic", _tenant=_tenant, domain=domain or config.SEO_DOMAIN,
                    database=database or config.SEO_DATABASE,
                    display_limit=min(int(limit or 30), 100), display_sort=sort)
    if isinstance(rows, str):
        return rows
    slim = [{"keyword": r.get("Keyword"), "position": r.get("Position"),
             "volume": r.get("Search Volume"), "cpc": r.get("CPC"),
             "url": r.get("Url"), "traffic_pct": r.get("Traffic (%)")} for r in rows]
    return json.dumps(slim)


def semrush_competitors(domain: str = "", database: str = "", limit: int = 15, _tenant: str = "") -> str:
    rows = _semrush("domain_organic_organic", _tenant=_tenant, domain=domain or config.SEO_DOMAIN,
                    database=database or config.SEO_DATABASE,
                    display_limit=min(int(limit or 15), 50))
    if isinstance(rows, str):
        return rows
    slim = [{"competitor": r.get("Domain"),
             "common_keywords": r.get("Common Keywords"),
             "organic_keywords": r.get("Organic Keywords"),
             "competition_level": r.get("Competitor Relevance")} for r in rows]
    return json.dumps(slim)


def semrush_serp_rivals(phrase: str, database: str = "", limit: int = 10,
                        _tenant: str = "") -> str:
    """Who ranks for ONE phrase — the only report that answers "who is above us".

    `domain_organic_organic` (semrush_competitors, above) is the cheap
    domain-level neighbour and cannot answer this: it says which sites compete
    with us OVERALL, never who holds position 3 for the phrase we are about to
    write against. Per-keyword rivals need a per-keyword report.

    THE LIMIT IS THE BILL. Semrush charges by the LINE returned, not by the
    call, so `display_limit` is the cost control and it is clamped here rather
    than trusted from the caller — `_semrush` forwards params blind, so an
    unclamped limit is an unbounded charge. Ten is deep enough to name everyone
    a page-one contender has to pass and shallow enough that a full refresh of
    a prioritised map costs a fraction of one harvest.

    `export_columns` is deliberately NOT sent. The API's column codes are short
    aliases that differ per report, and a wrong one returns a valid-looking row
    set with the wrong fields in it; the defaults already carry domain and url,
    and rank comes from ORDER, which is what an organic report is sorted by.
    """
    rows = _semrush("phrase_organic", _tenant=_tenant, phrase=phrase,
                    database=database or config.SEO_DATABASE,
                    display_limit=max(1, min(int(limit or 10), 20)))
    if isinstance(rows, str):
        return rows
    out = []
    for i, r in enumerate(rows):
        domain = (r.get("Domain") or r.get("domain") or "").strip()
        if not domain:
            continue
        # Position from the column when the report carries one, else from
        # order. Both are read because the organic report is rank-sorted by
        # definition, so order is a correct fallback and never a guess.
        pos = _f(r.get("Position") or r.get("position") or 0) or float(i + 1)
        out.append({"domain": domain,
                    "url": (r.get("Url") or r.get("url") or "").strip(),
                    "position": pos})
    return json.dumps(out)


def semrush_keyword_metrics(phrases: str, database: str = "", _tenant: str = "") -> str:
    rows = _semrush("phrase_these", _tenant=_tenant, phrase=phrases,
                    database=database or config.SEO_DATABASE)
    if isinstance(rows, str):
        return rows
    slim = [{"keyword": r.get("Keyword"), "volume": r.get("Search Volume"),
             "cpc": r.get("CPC"), "competition": r.get("Competition"),
             "results": r.get("Number of Results")} for r in rows]
    return json.dumps(slim)


def semrush_related_keywords(phrase: str, database: str = "", limit: int = 30, _tenant: str = "") -> str:
    rows = _semrush("phrase_related", _tenant=_tenant, phrase=phrase,
                    database=database or config.SEO_DATABASE,
                    display_limit=min(int(limit or 30), 60), display_sort="nq_desc")
    if isinstance(rows, str):
        return rows
    slim = [{"keyword": r.get("Keyword"), "volume": r.get("Search Volume"),
             "cpc": r.get("CPC"), "competition": r.get("Competition")} for r in rows]
    return json.dumps(slim)


def semrush_questions(phrase: str, database: str = "", limit: int = 30, _tenant: str = "") -> str:
    rows = _semrush("phrase_questions", _tenant=_tenant, phrase=phrase,
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
                               exclude_terms: list | None = None,
                               _tenant: str = "") -> str:
    """Keywords where the domain ALREADY ranks page 2-3 with real volume — quick
    wins. exclude_terms (per-site brand guardrail) are never recommended."""
    rows = _semrush("domain_organic", _tenant=_tenant, domain=domain or config.SEO_DOMAIN,
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


def capture_snapshot(domain: str = "", database: str = "",
                     _tenant: str = "") -> str:
    domain = domain or config.SEO_DOMAIN
    database = database or config.SEO_DATABASE
    ov = _semrush("domain_rank", _tenant=_tenant, domain=domain, database=database)
    if isinstance(ov, str):
        return ov
    o = ov[0] if ov else {}
    kw = _semrush("domain_organic", _tenant=_tenant, domain=domain, database=database,
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


def seo_context_block(tenant: str = "") -> str:
    """Injected into the SEO role each turn: which client sites it manages + the
    primary site's current baseline.

    Accepts the active account (the kernel passes it) for signature parity with
    the other role context hooks. NOT yet used to scope the baseline — that line
    still shows the primary site's numbers regardless of which client is active,
    which is a separate leak (audit SEO-1) fixed when the SEO role is scoped by
    site rather than by the global SEO_DOMAIN.
    """
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
    if name in ("propose_article", "propose_article_revision"):
        revision = name.endswith("revision")
        fields = _build_content_fields(profile, args)
        for k in ("author", "tags", "summary_html"):
            if args.get(k) is not None:
                fields[k] = args[k]
        if args.get("published") is not None:
            fields["published"] = bool(args["published"])
        if not revision and not (fields.get("title") and fields.get("body_html")):
            return ("A new article needs a title and body_html — answer-first: "
                    "the answer in the opening paragraph, then H2/H3 sections.")
        if revision and not fields:
            return ("Nothing to change. A revision touches only the fields you "
                    "send, so read the live text with get_article first and "
                    "pass back just what should differ.")
        blocked = _link_grounding(profile, fields)
        if blocked:
            return blocked
        # THE BAN LIST FIRES HERE, not only at the backend. Both run: the
        # backend check is what protects a caller that never came through a
        # proposal, and this one is what stops a banned claim reaching the
        # approval queue at all. Asking somebody to approve prose that cannot
        # publish spends the scarcest thing this system has — the owner's
        # attention on a queue — on a decision with no outcome.
        from . import seo_guard
        refusal = seo_guard.check(
            profile, fields,
            what="article revision" if revision else "new article")
        if refusal:
            return refusal
        # Shopify stores can hold several blogs and the write path is
        # blogs/<id>/articles.json, so a missing id would 404 at the API rather
        # than here. Name the field instead of guessing one.
        blog_id = str(args.get("blog_id") or "")
        if not blog_id and profile.get("platform") != "wordpress":
            return ("Which blog? This store can have several — call list_blogs "
                    "and pass blog_id.")
        if revision:
            if not args.get("article_id"):
                return "A revision needs article_id — find it with list_articles."
            ap_id = approvals.request_approval(
                "seo_article_revision",
                f"[SEO/{site}] Revise article {args['article_id']}: "
                + (fields.get("title") or "copy/structured-data"),
                {"site": site, "blog_id": blog_id,
                 "article_id": str(args["article_id"]), "fields": fields,
                 # THE JOIN, on this arm too. The create arm has carried
                 # output_id/run_id since the 2026-08-26 audit — without them
                 # the executor has nothing to write the result back onto. The
                 # revision arm never carried them because nothing filed a
                 # revision; now the refresh lane does, and an approved
                 # refresh that records nothing is the same open loop one
                 # tool over: no `refreshed_at`, so the cooldown never starts
                 # and the page is offered for refresh again next week.
                 "output_id": str(args.get("output_id") or ""),
                 "run_id": str(args.get("run_id") or ""),
                 "bucket": "seo"})
            return (f"Queued for your approval ({ap_id[:8]}): revise article "
                    f"{args['article_id']} on {site}, touching only "
                    + ", ".join(sorted(fields))
                    + ". Nothing changes until you approve.")
        ap_id = approvals.request_approval(
            "seo_new_article",
            f"[SEO/{site}] New article: {fields['title']}"
            + (" (+FAQ schema)" if args.get("faqs") else ""),
            # `output_id` rides in the payload so the executor can write the
            # publish back onto the keyword row; `run_id` on the approval row
            # itself so the decision and the edit delta reach the SystemRun —
            # the parameter existed since the column did and this path never
            # passed it.
            {"site": site, "blog_id": blog_id, "fields": fields, "bucket": "seo",
             "output_id": str(args.get("output_id") or "")},
            run_id=str(args.get("run_id") or ""))
        return (f"Queued for your approval ({ap_id[:8]}): create article "
                f"'{fields['title']}' on {site}"
                + (", PUBLISHED on approval" if fields.get("published")
                   else ", saved as a draft")
                + (" with FAQPage structured data" if args.get("faqs") else "")
                + ". Not written until you approve.")

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
    {"name": "list_blogs",
     "description": "The blogs on this site (Shopify can have several; "
                    "WordPress has one posts stream). Needed before writing an "
                    "article — get blog_id from here.",
     "input_schema": _t({})},
    {"name": "list_articles",
     "description": "Existing articles/posts (id, title, handle, status, "
                    "updated). Use it to find what to revise, and to avoid "
                    "writing a second article on a topic already covered.",
     "input_schema": _t({"blog_id": {"type": "string"},
                         "limit": {"type": "integer"}})},
    {"name": "get_article",
     "description": "One article IN FULL, including its live body. READ THIS "
                    "BEFORE ANY REVISION — rewriting a page that already ranks "
                    "is how a site loses the position it had.",
     "input_schema": _t({"blog_id": {"type": "string"},
                         "article_id": {"type": "string"}},
                        required=["article_id"])},
    {"name": "propose_article",
     "description": "PROPOSE a NEW article (SEO/GEO). Answer-first body_html: "
                    "the answer in the opening paragraph, then H2/H3 sections; "
                    "pass faqs for FAQPage JSON-LD. Link only to REAL URLs "
                    "(find_items). Saved as a DRAFT unless published=true. "
                    "Queues for approval.",
     "input_schema": _t({
         "blog_id": {"type": "string"},
         "title": {"type": "string"}, "handle": {"type": "string"},
         "body_html": {"type": "string"}, "summary_html": {"type": "string"},
         "seo_title": {"type": "string"}, "seo_description": {"type": "string"},
         "author": {"type": "string"}, "tags": {"type": "string"},
         "published": {"type": "boolean"},
         "faqs": {"type": "array", "items": {"type": "object", "properties": {
             "question": {"type": "string"}, "answer": {"type": "string"}}}},
         "jsonld": {"type": "string"}}, required=["title", "body_html"])},
    {"name": "propose_article_revision",
     "description": "PROPOSE a revision to an EXISTING article. PARTIAL — send "
                    "only the fields that should change; anything omitted is "
                    "left alone. Call get_article first. Queues for approval.",
     "input_schema": _t({
         "blog_id": {"type": "string"}, "article_id": {"type": "string"},
         "title": {"type": "string"}, "handle": {"type": "string"},
         "body_html": {"type": "string"}, "summary_html": {"type": "string"},
         "seo_title": {"type": "string"}, "seo_description": {"type": "string"},
         "author": {"type": "string"}, "tags": {"type": "string"},
         "published": {"type": "boolean"},
         "faqs": {"type": "array", "items": {"type": "object", "properties": {
             "question": {"type": "string"}, "answer": {"type": "string"}}}},
         "jsonld": {"type": "string"}}, required=["article_id"])},
    {"name": "propose_theme_schema_renderer",
     "description": "ONE-TIME (Shopify only): install the theme snippet that "
                    "outputs our JSON-LD metafield into <head>. No-op on "
                    "WordPress (inlined). Idempotent, reversible. Queues for "
                    "approval.",
     "input_schema": _t({})},
    {"name": "save_memory",
     "description": "Save/update a durable note in YOUR (SEO) working memory — the "
                    "live project plan, target keywords, what shipped, what's next. "
                    "Same topic overwrites. SAVE your plan/state after each session "
                    "so long-horizon work survives the short conversation window. "
                    "shared=true only for a cross-cutting fact all agents need.",
     "input_schema": {"type": "object", "properties": {
         "topic": {"type": "string"}, "content": {"type": "string"},
         "shared": {"type": "boolean"}},
         "required": ["topic", "content"]}},
    {"name": "forget_memory",
     "description": "Archive one of your SEO working-memory topics once resolved.",
     "input_schema": {"type": "object", "properties": {
         "topic": {"type": "string"}}, "required": ["topic"]}},
    {"name": "systems_list",
     "description": "Index of the Systems Map — durable docs on how Gomeh's "
                    "world is organized (projects, conventions, registries).",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "systems_get",
     "description": "Read one Systems Map doc in full (e.g. 'project:<name>') — "
                    "consult before restructuring anything a prior task set up.",
     "input_schema": {"type": "object", "properties": {
         "key": {"type": "string"}}, "required": ["key"]}},
    {"name": "systems_update",
     "description": "Create/update a Systems Map doc when a project advanced or "
                    "structure changed (keys: 'project:<name>', "
                    "'conventions:<topic>') — the next session inherits the map.",
     "input_schema": {"type": "object", "properties": {
         "key": {"type": "string"}, "content": {"type": "string"},
         "title": {"type": "string"}, "pinned": {"type": "boolean"}},
         "required": ["key", "content"]}},
    {"name": "request_feature",
     "description": "File a feature request when you hit a real limitation "
                    "(missing tool/data source, cap that cut results). Concrete "
                    "problem + proposed fix; then continue with what you have.",
     "input_schema": {"type": "object", "properties": {
         "title": {"type": "string"}, "problem": {"type": "string"},
         "proposal": {"type": "string"}}, "required": ["title", "problem"]}},
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
            return memory.remember(args["topic"], args["content"],
                                   scope="global" if args.get("shared") else "seo")
        if name == "forget_memory":
            return memory.forget(args["topic"], scope="seo")
        if name == "systems_list":
            from . import systems_map
            return systems_map.list_docs()
        if name == "systems_get":
            from . import systems_map
            return systems_map.get_doc(args["key"])
        if name == "systems_update":
            from . import systems_map
            return systems_map.set_doc(args["key"], args["content"],
                                       title=args.get("title", ""),
                                       updated_by="seo",
                                       pinned=args.get("pinned"))
        if name == "request_feature":
            from . import systems_map
            return systems_map.request_feature("seo", args["title"],
                                               args["problem"],
                                               args.get("proposal", ""))
        if name == "verify_links":
            return json.dumps(sites.verify_links(profile, args.get("html", "")))
        if name in ("list_blogs", "list_articles", "get_article"):
            backend = sites.backend(profile)
            if name == "list_blogs":
                return backend.list_blogs(profile)
            if name == "list_articles":
                return backend.list_articles(profile, args.get("blog_id"),
                                             int(args.get("limit", 20)))
            return backend.get_article(profile, args.get("blog_id"),
                                       args["article_id"])
        if name in ("list_collections", "find_items", "get_seo"):
            backend = sites.backend(profile)
            if name == "list_collections":
                return backend.list_collections(profile)
            if name == "find_items":
                return backend.find_items(profile, args.get("query", ""),
                                          int(args.get("limit", 20)))
            return backend.get_seo(profile, args["resource"], args["resource_id"])
        if name in ("propose_seo_update", "propose_new_collection",
                    "propose_content_page", "propose_theme_schema_renderer",
                    "propose_article", "propose_article_revision"):
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
        # WHOSE work this call is. Injected here, where the profile is already
        # resolved, and never taken from the model: `_tenant` is deliberately
        # absent from every schema in `TOOLS`, so the agent cannot name an
        # account to bill — the same rule `tool_scope.SCOPED` enforces for the
        # account parameter itself.
        if name.startswith("semrush_") or name in ("seo_snapshot",):
            from . import seo_guard
            args["_tenant"] = seo_guard.tenant_for(profile)
        return _HANDLERS[name](**args)[:8000]
    except sites.UnknownSite as exc:
        # A refusal, not a crash. The generic arm below would render this as
        # "Tool error (UnknownSite)", which reads like something broke rather
        # than like a client that needs setting up.
        return str(exc)
    except Exception as exc:  # noqa: BLE001
        return f"Tool error ({exc.__class__.__name__}): {str(exc)[:200]}"
