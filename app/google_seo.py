"""GSC + GA4 read layer for the SEO role — the ground-truth research feed.

Google Search Console gives REAL rankings/clicks/impressions/CTR (vs Semrush's
modeled estimates); GA4 gives REAL sessions/users/conversions by channel and
landing page. This is the truth the agent measures itself against.

SELF-CONFIGURING: you don't pre-set which GSC property or GA4 property belongs to
a site. The agent uses one Google account (default: personal — you grant it into
each property), DISCOVERS the matching GSC site + GA4 property by domain on first
use, and PERSISTS the mapping in the DB (SeoSiteConfig). Resolution order per
field: explicit profile/env value -> DB -> auto-discover (then saved).

All Google calls go through the shared locked lane (gmail_client._google_lock) —
googleapiclient/httplib2 is not thread-safe and concurrency segfaults the
process. Needs the webmasters.readonly + analytics.readonly scopes (the latter
also covers the GA4 Admin API used for discovery) — re-run
scripts/google_oauth.py to grant them.
"""
import datetime as dt
import json

from googleapiclient.discovery import build

from . import config, db, gmail_client

_gsc_cache: dict = {}
_insp_cache: dict = {}
_ga_cache: dict = {}
_admin_cache: dict = {}


# ---------------------------------------------------------------------------
# Service builders (all behind the Google lock)
# ---------------------------------------------------------------------------
def _gsc(alias: str):
    if alias not in _gsc_cache:
        with gmail_client._google_lock:
            _gsc_cache[alias] = build("webmasters", "v3",
                credentials=gmail_client.creds_for(alias), cache_discovery=False)
    return _gsc_cache[alias]


def _inspect(alias: str):
    if alias not in _insp_cache:
        with gmail_client._google_lock:
            _insp_cache[alias] = build("searchconsole", "v1",
                credentials=gmail_client.creds_for(alias), cache_discovery=False)
    return _insp_cache[alias]


def _ga(alias: str):
    if alias not in _ga_cache:
        with gmail_client._google_lock:
            _ga_cache[alias] = build("analyticsdata", "v1beta",
                credentials=gmail_client.creds_for(alias), cache_discovery=False)
    return _ga_cache[alias]


def _admin(alias: str):
    if alias not in _admin_cache:
        with gmail_client._google_lock:
            _admin_cache[alias] = build("analyticsadmin", "v1beta",
                credentials=gmail_client.creds_for(alias), cache_discovery=False)
    return _admin_cache[alias]


def _alias(profile: dict) -> str:
    return profile.get("google_alias") or config.SEO_GOOGLE_ALIAS


def _host(profile: dict) -> str:
    return (profile.get("domain") or "").replace("https://", "").replace(
        "http://", "").replace("www.", "").strip("/")


def _err(exc: Exception) -> str:
    msg = str(exc)
    low = msg.lower()
    if "403" in msg or "scope" in low or "insufficient" in low or "permission" in low:
        return ("Google permission error — re-run scripts/google_oauth.py to grant "
                "webmasters.readonly + analytics.readonly, and confirm the Google "
                f"account is a user on this property. ({msg[:160]})")
    if "404" in msg or "not found" in low:
        return f"Property not found. ({msg[:160]})"
    return f"Google API error: {msg[:200]}"


def _range(days: int) -> tuple[str, str]:
    end = dt.date.today()
    start = end - dt.timedelta(days=int(days or 28))
    return start.isoformat(), end.isoformat()


# ---------------------------------------------------------------------------
# DB persistence of the resolved GSC/GA4 mapping
# ---------------------------------------------------------------------------
def _load_link(site_key: str) -> dict:
    with db.SessionLocal() as s:
        row = s.get(db.SeoSiteConfig, site_key)
        return {"gsc_site": row.gsc_site, "ga4_property": row.ga4_property} if row else {}


def _save_link(site_key: str, domain: str, gsc_site=None, ga4_property=None) -> None:
    with db.SessionLocal() as s:
        row = s.get(db.SeoSiteConfig, site_key)
        if not row:
            row = db.SeoSiteConfig(site=site_key)
            s.add(row)
        row.domain = domain or row.domain
        if gsc_site is not None:
            row.gsc_site = gsc_site
        if ga4_property is not None:
            row.ga4_property = ga4_property
        row.updated_at = db.utcnow()
        s.commit()


# ---------------------------------------------------------------------------
# GSC property discovery + resolution
# ---------------------------------------------------------------------------
def _gsc_site_entries(profile: dict) -> list:
    svc = _gsc(_alias(profile))
    with gmail_client._google_lock:
        return svc.sites().list().execute().get("siteEntry", [])


def gsc_list_sites(profile: dict) -> str:
    """List the Search Console properties this Google account can access."""
    try:
        entries = _gsc_site_entries(profile)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)
    rows = [{"site": e["siteUrl"], "permission": e.get("permissionLevel")}
            for e in entries]
    return json.dumps(rows) if rows else "This Google account has no GSC properties."


def _match_gsc_site(entries: list, host: str):
    urls = [e["siteUrl"] for e in entries
            if e.get("permissionLevel") != "siteUnverifiedUser"]
    if f"sc-domain:{host}" in urls:
        return f"sc-domain:{host}"
    for u in urls:  # url-prefix property
        if u.rstrip("/") in (f"https://{host}", f"http://{host}",
                             f"https://www.{host}", f"http://www.{host}"):
            return u
    for u in urls:  # any property containing the host
        if host in u:
            return u
    return None


def _resolve_gsc_site(profile: dict):
    if profile.get("gsc_site"):
        return profile["gsc_site"]
    cached = _load_link(profile["key"]).get("gsc_site")
    if cached:
        return cached
    host = _host(profile)
    try:
        match = _match_gsc_site(_gsc_site_entries(profile), host)
    except Exception:  # noqa: BLE001
        return None
    if match:
        _save_link(profile["key"], host, gsc_site=match)
    return match


def _no_gsc(profile: dict) -> str:
    return ("No Search Console property is linked to " + profile["domain"]
            + " yet, and none auto-matched. Call gsc_list_sites to see what this "
            "Google account can access, then seo_link_google to pin the right one "
            "(it's saved to the DB after).")


# ---------------------------------------------------------------------------
# GA4 property discovery + resolution (Admin API)
# ---------------------------------------------------------------------------
def _ga4_summaries(profile: dict) -> list:
    svc = _admin(_alias(profile))
    with gmail_client._google_lock:
        resp = svc.accountSummaries().list().execute()
    out = []
    for acc in resp.get("accountSummaries", []):
        for p in acc.get("propertySummaries", []):
            out.append({"property": p["property"].replace("properties/", ""),
                        "name": p.get("displayName"), "account": acc.get("displayName")})
    return out


def ga4_list_properties(profile: dict) -> str:
    """List the GA4 properties this Google account can access (id + name)."""
    try:
        props = _ga4_summaries(profile)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)
    return json.dumps(props) if props else "This Google account has no GA4 properties."


def _discover_ga4(profile: dict, host: str):
    props = _ga4_summaries(profile)
    token = host.split(".")[0].lower()
    named = [p for p in props if token in (p["name"] or "").lower()]
    for p in (named or props)[:30]:  # confirm by the web stream's URL
        try:
            svc = _admin(_alias(profile))
            with gmail_client._google_lock:
                streams = svc.properties().dataStreams().list(
                    parent="properties/" + p["property"]).execute()
        except Exception:  # noqa: BLE001
            continue
        for stx in streams.get("dataStreams", []):
            uri = (stx.get("webStreamData", {}) or {}).get("defaultUri", "")
            if host in uri.replace("www.", ""):
                return p["property"]
    return named[0]["property"] if len(named) == 1 else None


def _resolve_ga4(profile: dict):
    if profile.get("ga4_property"):
        return profile["ga4_property"].replace("properties/", "").strip()
    cached = _load_link(profile["key"]).get("ga4_property")
    if cached:
        return cached
    host = _host(profile)
    try:
        match = _discover_ga4(profile, host)
    except Exception:  # noqa: BLE001
        return None
    if match:
        _save_link(profile["key"], host, ga4_property=match)
    return match


def seo_link_google(profile: dict, gsc_site: str = "", ga4_property: str = "") -> str:
    """Pin (and persist) which GSC property and/or GA4 property belong to this
    site — for when auto-discovery is ambiguous. Saved to the agent DB."""
    _save_link(profile["key"], _host(profile),
               gsc_site=gsc_site or None,
               ga4_property=(ga4_property.replace("properties/", "").strip()
                             if ga4_property else None))
    link = _load_link(profile["key"])
    return (f"Linked {profile['key']} ({profile['domain']}) -> "
            f"GSC: {link.get('gsc_site') or '(unset)'}, "
            f"GA4: {link.get('ga4_property') or '(unset)'}. Saved.")


# ---------------------------------------------------------------------------
# Google Search Console — real rankings / clicks / impressions / CTR
# ---------------------------------------------------------------------------
def _gsc_query(profile: dict, site: str, body: dict) -> dict:
    svc = _gsc(_alias(profile))
    with gmail_client._google_lock:
        return svc.searchanalytics().query(siteUrl=site, body=body).execute()


def _gsc_rows(resp: dict, key_names: list) -> list:
    out = []
    for r in resp.get("rows", []):
        row = dict(zip(key_names, r.get("keys", [])))
        row.update({"clicks": int(r.get("clicks", 0)),
                    "impressions": int(r.get("impressions", 0)),
                    "ctr": round(r.get("ctr", 0) * 100, 2),
                    "position": round(r.get("position", 0), 1)})
        out.append(row)
    return out


def gsc_top_queries(profile: dict, days: int = 28, limit: int = 25) -> str:
    """Real search queries the site ranks for: clicks, impressions, CTR, avg
    position. The truth behind Semrush estimates."""
    site = _resolve_gsc_site(profile)
    if not site:
        return _no_gsc(profile)
    start, end = _range(days)
    try:
        resp = _gsc_query(profile, site, {"startDate": start, "endDate": end,
                          "dimensions": ["query"], "rowLimit": int(limit or 25)})
    except Exception as exc:  # noqa: BLE001
        return _err(exc)
    rows = _gsc_rows(resp, ["query"])
    return json.dumps(rows) if rows else f"No Search Console data for {site} in that period."


def gsc_top_pages(profile: dict, days: int = 28, limit: int = 25) -> str:
    """Real top pages by clicks/impressions/position."""
    site = _resolve_gsc_site(profile)
    if not site:
        return _no_gsc(profile)
    start, end = _range(days)
    try:
        resp = _gsc_query(profile, site, {"startDate": start, "endDate": end,
                          "dimensions": ["page"], "rowLimit": int(limit or 25)})
    except Exception as exc:  # noqa: BLE001
        return _err(exc)
    rows = _gsc_rows(resp, ["page"])
    return json.dumps(rows) if rows else "No Search Console data for that period."


def gsc_page_queries(profile: dict, page_url: str, days: int = 28,
                     limit: int = 25) -> str:
    """Which real queries drive a specific page — the basis for optimizing it."""
    site = _resolve_gsc_site(profile)
    if not site:
        return _no_gsc(profile)
    start, end = _range(days)
    body = {"startDate": start, "endDate": end, "dimensions": ["query"],
            "rowLimit": int(limit or 25),
            "dimensionFilterGroups": [{"filters": [
                {"dimension": "page", "operator": "equals", "expression": page_url}]}]}
    try:
        resp = _gsc_query(profile, site, body)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)
    rows = _gsc_rows(resp, ["query"])
    return json.dumps(rows) if rows else f"No Search Console queries for {page_url}."


def gsc_trend(profile: dict, days: int = 90) -> str:
    """Clicks/impressions by date — growth or decline over time."""
    site = _resolve_gsc_site(profile)
    if not site:
        return _no_gsc(profile)
    start, end = _range(days)
    try:
        resp = _gsc_query(profile, site, {"startDate": start, "endDate": end,
                          "dimensions": ["date"], "rowLimit": 1000})
    except Exception as exc:  # noqa: BLE001
        return _err(exc)
    rows = _gsc_rows(resp, ["date"])
    if not rows:
        return "No Search Console data for that period."
    half = len(rows) // 2 or 1
    first = sum(r["clicks"] for r in rows[:half])
    second = sum(r["clicks"] for r in rows[half:])
    return json.dumps({"days": len(rows),
                       "clicks_total": sum(r["clicks"] for r in rows),
                       "impressions_total": sum(r["impressions"] for r in rows),
                       "clicks_first_half": first, "clicks_second_half": second,
                       "direction": "up" if second > first else "down" if second < first else "flat",
                       "daily": rows[-30:]})


def gsc_inspect_url(profile: dict, url: str) -> str:
    """Index status of a URL — is the page actually indexed by Google?"""
    site = _resolve_gsc_site(profile)
    if not site:
        return _no_gsc(profile)
    try:
        svc = _inspect(_alias(profile))
        with gmail_client._google_lock:
            resp = svc.urlInspection().index().inspect(
                body={"inspectionUrl": url, "siteUrl": site}).execute()
    except Exception as exc:  # noqa: BLE001
        return _err(exc)
    r = resp.get("inspectionResult", {}).get("indexStatusResult", {})
    return json.dumps({"verdict": r.get("verdict"),
                       "coverage": r.get("coverageState"),
                       "indexing_state": r.get("indexingState"),
                       "last_crawl": r.get("lastCrawlTime"),
                       "google_canonical": r.get("googleCanonical"),
                       "robots": r.get("robotsTxtState")})


# ---------------------------------------------------------------------------
# GA4 — real sessions / users / conversions
# ---------------------------------------------------------------------------
def _ga_report(profile: dict, days: int, dimensions: list,
               limit: int = 25, organic_only: bool = False) -> str:
    pid = _resolve_ga4(profile)
    if not pid:
        return ("No GA4 property is linked to " + profile["domain"] + " yet, and "
                "none auto-matched. Call ga4_list_properties, then seo_link_google "
                "to pin it (saved after).")
    dims = [{"name": d} for d in dimensions]
    dim_filter = None
    if organic_only:
        dim_filter = {"filter": {"fieldName": "sessionDefaultChannelGroup",
                      "stringFilter": {"value": "Organic Search"}}}
    # Newer GA4 properties expose 'keyEvents' instead of 'conversions'; fall back.
    for conv in ("conversions", "keyEvents", None):
        metrics = [{"name": "sessions"}, {"name": "totalUsers"}]
        if conv:
            metrics.append({"name": conv})
        body = {"dateRanges": [{"startDate": f"{int(days or 28)}daysAgo",
                                "endDate": "today"}],
                "dimensions": dims, "metrics": metrics,
                "orderBys": [{"metric": {"metricName": "sessions"}, "desc": True}],
                "limit": int(limit or 25)}
        if dim_filter:
            body["dimensionFilter"] = dim_filter
        try:
            svc = _ga(_alias(profile))
            with gmail_client._google_lock:
                resp = svc.properties().runReport(
                    property=f"properties/{pid}", body=body).execute()
        except Exception as exc:  # noqa: BLE001
            if conv is None:
                return _err(exc)
            continue
        headers = ([h["name"] for h in resp.get("dimensionHeaders", [])]
                   + [m["name"] for m in resp.get("metricHeaders", [])])
        rows = []
        for r in resp.get("rows", []):
            vals = ([d["value"] for d in r.get("dimensionValues", [])]
                    + [m["value"] for m in r.get("metricValues", [])])
            rows.append(dict(zip(headers, vals)))
        return json.dumps(rows) if rows else "No GA4 data for that period."
    return "No GA4 data for that period."


def ga4_overview(profile: dict, days: int = 28) -> str:
    """Traffic by channel: sessions, users, conversions — where traffic comes
    from and what converts."""
    return _ga_report(profile, days, ["sessionDefaultChannelGroup"], limit=20)


def ga4_landing_pages(profile: dict, days: int = 28, limit: int = 25) -> str:
    """ORGANIC landing pages by sessions + conversions — which SEO pages actually
    earn traffic and revenue. The page-level ROI view."""
    return _ga_report(profile, days, ["landingPagePlusQueryString"],
                      limit=limit, organic_only=True)
