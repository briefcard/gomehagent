"""WordPress implementation backend for the `seo` role (e.g. MarketingThatWorks,
a service-based site). Same function surface as shopify_seo, so the SEO tools and
approval executors don't care about the platform.

Uses the WordPress REST API with Application Passwords (Basic auth). Credentials
per site live in config.WORDPRESS_SITES, keyed by profile['creds_key'].

Platform differences vs Shopify, handled here:
- WordPress KEEPS <script> in post content, so JSON-LD is embedded inline
  (INLINE_JSONLD = True) — no theme snippet needed (install_schema_renderer is a
  no-op).
- "collections" map to categories; "items" are pages/posts (services on a
  service site). create_collection falls back to a landing PAGE.
- SEO is handled with NATIVE WordPress fields — no SEO plugin required: the
  <title> tag follows the post title, and the meta description is written to the
  native `excerpt` field (themes/SEO plugins read the excerpt as the description).
  If Yoast/RankMath happen to be REST-exposed we ALSO set their precise meta as a
  bonus, but nothing depends on it (best-effort, never fatal).
"""
import json
import re

import httpx

from . import config, sites

INLINE_JSONLD = True  # WordPress content keeps <script> -> embed JSON-LD inline


def _cfg(profile: dict) -> dict | None:
    return config.WORDPRESS_SITES.get(profile.get("creds_key", ""))


def _ok(profile: dict) -> str | None:
    if not _cfg(profile):
        return (f"WordPress site '{profile.get('creds_key')}' not configured for "
                f"site '{profile['key']}' (add it to WORDPRESS_SITES_JSON).")
    return None


def _api(profile: dict) -> str:
    return _cfg(profile)["base_url"].rstrip("/") + "/wp-json/wp/v2"


def _auth(profile: dict) -> tuple:
    c = _cfg(profile)
    return (c["user"], c["app_password"])


def _get(profile: dict, path: str, params: dict | None = None):
    r = httpx.get(f"{_api(profile)}/{path}", params=params or {},
                  auth=_auth(profile), timeout=30)
    r.raise_for_status()
    return r.json()


def _send(profile: dict, method: str, path: str, body: dict) -> dict:
    r = httpx.request(method, f"{_api(profile)}/{path}", json=body,
                      auth=_auth(profile), timeout=30)
    r.raise_for_status()
    return r.json()


def _text(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html or "").strip()


def _seo_meta(fields: dict) -> dict:
    """SEO title/description in the common WP SEO plugins' keys — set ONLY as a
    bonus if the site exposes them over REST (see _apply_plugin_meta)."""
    meta = {}
    if fields.get("seo_title") is not None:
        meta["_yoast_wpseo_title"] = fields["seo_title"]
        meta["rank_math_title"] = fields["seo_title"]
    if fields.get("seo_description") is not None:
        meta["_yoast_wpseo_metadesc"] = fields["seo_description"]
        meta["rank_math_description"] = fields["seo_description"]
    return meta


def _apply_plugin_meta(profile: dict, ptype: str, rid, fields: dict) -> None:
    """Best-effort: if Yoast/RankMath meta is REST-exposed, set the precise SEO
    title/description too. NEVER fatal — the native post title (title tag) and
    excerpt (meta description) already carry SEO, so this is pure upside."""
    meta = _seo_meta(fields)
    if not meta:
        return
    try:
        _send(profile, "PUT", f"{ptype}/{rid}", {"meta": meta})
    except Exception:  # noqa: BLE001 — meta not REST-exposed; native fields suffice
        pass


# ---------------------------------------------------------------------------
# Read (no approval)
# ---------------------------------------------------------------------------
def list_collections(profile: dict) -> str:
    err = _ok(profile)
    if err:
        return err
    cats = _get(profile, "categories", {"per_page": 100,
                "fields": "id,name,slug,link,count"})
    out = [{"id": c["id"], "title": c.get("name"), "handle": c.get("slug"),
            "url": c.get("link"), "type": "category", "count": c.get("count")}
           for c in cats]
    return json.dumps(out)


def find_items(profile: dict, query: str = "", limit: int = 20) -> str:
    """Search pages and posts (real ids/slugs/URLs) — what to link to or optimize."""
    err = _ok(profile)
    if err:
        return err
    out = []
    for ptype in ("pages", "posts"):
        try:
            items = _get(profile, ptype, {"search": query, "per_page": int(limit or 20),
                                          "_fields": "id,title,slug,link,type"})
            out += [{"id": i["id"], "title": i.get("title", {}).get("rendered", ""),
                     "handle": i.get("slug"), "url": i.get("link"),
                     "type": i.get("type", ptype[:-1])} for i in items]
        except Exception:  # noqa: BLE001 — a post type may be disabled
            continue
    return json.dumps(out[:int(limit or 20)]) if out else f"No content matching '{query}'."


def get_seo(profile: dict, resource: str, resource_id: str) -> str:
    err = _ok(profile)
    if err:
        return err
    ptype = "posts" if resource == "post" else "pages"
    obj = _get(profile, f"{ptype}/{resource_id}",
               {"_fields": "id,title,slug,link,content,excerpt,meta"})
    meta = obj.get("meta", {}) or {}
    title = obj.get("title", {}).get("rendered", "")
    return json.dumps({
        "id": obj.get("id"), "title": title,
        "handle": obj.get("slug"), "url": obj.get("link"),
        "description_html": (obj.get("content", {}).get("rendered", "") or "")[:1500],
        # title tag follows the post title; meta description follows the excerpt
        "seo_title": meta.get("_yoast_wpseo_title") or meta.get("rank_math_title") or title,
        "seo_description": (meta.get("_yoast_wpseo_metadesc")
                            or meta.get("rank_math_description")
                            or _text(obj.get("excerpt", {}).get("rendered", "")))})


# ---------------------------------------------------------------------------
# Write — called ONLY by the approval executor, after Gomeh approves
# ---------------------------------------------------------------------------
def update_seo(profile: dict, resource: str, resource_id, fields: dict) -> str:
    ptype = "posts" if resource == "post" else "pages"
    body: dict = {}
    if fields.get("title") is not None:
        body["title"] = fields["title"]          # drives the <title> tag natively
    if fields.get("handle") is not None:
        body["slug"] = fields["handle"]
    if fields.get("body_html") is not None:
        body["content"] = fields["body_html"]
    if fields.get("seo_description") is not None:
        body["excerpt"] = fields["seo_description"]  # native meta-description path
    obj = _send(profile, "PUT", f"{ptype}/{resource_id}", body)
    _apply_plugin_meta(profile, ptype, resource_id, fields)  # bonus, never fatal
    return obj.get("link", "(updated)")


def create_page(profile: dict, fields: dict) -> str:
    body = {"title": fields["title"], "content": fields.get("body_html", ""),
            "status": "publish"}
    if fields.get("handle"):
        body["slug"] = fields["handle"]
    if fields.get("seo_description") is not None:
        body["excerpt"] = fields["seo_description"]
    obj = _send(profile, "POST", "pages", body)
    _apply_plugin_meta(profile, "pages", obj.get("id"), fields)
    return obj.get("link", "(created)")


def create_collection(profile: dict, fields: dict, item_ids: list | None = None) -> str:
    """WordPress has no product collection; create a landing PAGE instead. If
    item_ids (page/post ids) are given, append links to them in the body so the
    'collection' references real content."""
    if item_ids:
        links = []
        for iid in item_ids:
            try:
                it = _get(profile, f"pages/{iid}", {"_fields": "title,link"})
                links.append(f'<li><a href="{it.get("link")}">'
                             f'{it.get("title", {}).get("rendered", "")}</a></li>')
            except Exception:  # noqa: BLE001
                continue
        if links:
            fields = {**fields, "body_html": (fields.get("body_html", "")
                      + "\n<ul>" + "\n".join(links) + "</ul>")}
    return create_page(profile, fields)


def install_schema_renderer(profile: dict) -> str:
    return ("WordPress renders JSON-LD inline in page content — no theme setup "
            "needed (structured data is embedded directly when the page is created).")
