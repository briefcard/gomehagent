"""Where a link may point — read from the site, never assumed from a pattern.

An email went out with its call to action on
`https://eienhealth.com/collections/all`, which does not exist: that store's
catalogue lives at `/collections/shop` (owner, 2026-08-22). Nobody had checked;
the URL was written by the drafter, from the platform convention it had learnt
somewhere, and every layer downstream treated a plausible string as a fact.

This is the same rule that already governs names, sources, figures and
photographs, applied to the one field that had escaped it: **a generator may
choose the words of a link, never its destination.** A URL is a claim about
what exists on somebody's site. It is looked up here or it is not used.

The destinations are read from three places, all of them real:

  * PRODUCTS — the catalogue sync's own handles, which is why product links in
    that same email were correct while the collection link was not.
  * COLLECTIONS — Shopify's `custom_collections` and `smart_collections`,
    fetched once and filed as entities. A store's "everything" page is called
    whatever its owner called it, and the only way to know is to ask.
  * THE APPROVED NAV — `theme.nav`, which the owner reviewed on the Brand tab.
    It carries the pages a human decided were worth linking to, which is a
    better answer than any heuristic over a sitemap.

`best_for` then answers the question a generator actually has — "where should
this email send people" — with the most specific real destination available:
the product being featured, else the store's own catalogue page, else home.
Blogs and ads will ask the same question, which is why this is a module and
not four lines inside the email skill.
"""
from __future__ import annotations

import re

#: Handles a store might use for "everything we sell". Ordered by how likely
#: they are to be the real catalogue rather than a subset. Only ever used to
#: RANK handles that genuinely exist — never to construct one.
_SHOP_HANDLES = ("shop", "all", "catalog", "catalogue", "products", "store",
                 "shop-all", "all-products")


def _domain(tenant: str) -> str:
    from . import tenants
    t = tenants.get(tenant)
    return (getattr(t, "domain", "") or "").strip().lower()


def _fetch_collections(tenant: str) -> int:
    """File this store's real collections as entities. Returns how many.

    Only reached when none are on file. Two API calls, and the result is what
    makes `/collections/<handle>` a fact rather than a guess.
    """
    from . import data_tools, kb, tenants
    t = tenants.get(tenant)
    if not (t and getattr(t, "shopify_store", "")):
        return 0
    if not tenants.capabilities(tenant).get("commerce"):
        return 0
    n = 0
    try:
        for path in ("custom_collections.json", "smart_collections.json"):
            raw = data_tools._shopify(t.shopify_store, path, {"limit": 250})
            for c in (raw.get(path.split(".")[0]) or []):
                handle = (c.get("handle") or "").strip().lower()
                if not handle:
                    continue
                kb.add_entity(tenant, "collection", handle,
                              c.get("title") or handle,
                              description="Shopify collection",
                              source=f"https://{_domain(tenant)}/collections/{handle}",
                              origin="store_sync")
                n += 1
    except Exception:                                            # noqa: BLE001
        return n          # partial is still better than none; caller reports
    return n


def destinations(tenant: str, *, fetch: bool = True) -> list[dict]:
    """Every URL on this tenant's site that is known to exist."""
    from . import brand_theme, kb
    dom = _domain(tenant)
    out: list[dict] = []
    if not dom:
        return out
    out.append({"kind": "home", "key": "", "label": "Home",
                "url": f"https://{dom}"})

    rows = kb.entities(tenant, available_only=False)
    colls = [r for r in rows if (r.type or "") == "collection"]
    if not colls and fetch and _fetch_collections(tenant):
        rows = kb.entities(tenant, available_only=False)
        colls = [r for r in rows if (r.type or "") == "collection"]
    for r in colls:
        out.append({"kind": "collection", "key": r.key, "label": r.name or r.key,
                    "url": f"https://{dom}/collections/{r.key}"})
    for r in rows:
        if (r.type or "") in ("collection", ""):
            continue
        out.append({"kind": "product", "key": r.key, "label": r.name or r.key,
                    "url": f"https://{dom}/products/{r.key}"})

    # The owner-approved nav: pages a human chose, which no catalogue read
    # would surface (an About page, a stockists list, a size guide).
    for item in (brand_theme.live_theme(tenant) or {}).get("nav") or []:
        u = str((item or {}).get("url") or "").strip()
        if u.startswith("http") and dom in u:
            out.append({"kind": "page", "key": "", "url": u,
                        "label": str(item.get("label") or "")})

    seen, uniq = set(), []
    for d in out:
        if d["url"] not in seen:
            seen.add(d["url"])
            uniq.append(d)
    return uniq


def shop_url(tenant: str, dests: list[dict] | None = None) -> str:
    """The store's own catalogue page — `/collections/shop` if that is what
    they called it, `/collections/all` only if that genuinely exists."""
    dests = destinations(tenant) if dests is None else dests
    colls = [d for d in dests if d["kind"] == "collection"]
    for want in _SHOP_HANDLES:
        for d in colls:
            if d["key"] == want:
                return d["url"]
    for d in dests:                        # a nav entry pointing at a listing
        if d["kind"] == "page" and "/collections/" in d["url"]:
            return d["url"]
    if colls:
        return colls[0]["url"]
    home = next((d["url"] for d in dests if d["kind"] == "home"), "")
    return home


def best_for(tenant: str, entity_keys: list[str] | None = None,
             dests: list[dict] | None = None) -> str:
    """Where this piece of content should send people.

    One featured product gets its own page — the most specific true answer.
    Several, or none, get the catalogue. Never a constructed path.
    """
    dests = destinations(tenant) if dests is None else dests
    keys = [k for k in (entity_keys or []) if k]
    if len(keys) == 1:
        hit = next((d for d in dests
                    if d["kind"] == "product" and d["key"] == keys[0]), None)
        if hit:
            return hit["url"]
    return shop_url(tenant, dests)


def points_at(html: str, url: str) -> bool:
    """Does this markup link to that page? Offline, and deliberately so.

    `sites.verify_links` HTTP-checks every href, which is right before a
    publish and wrong for a question asked about hundreds of stored articles
    at once: the answer here is "did the writer link to this", not "does the
    internet still serve it".

    Compared on the normalised form — scheme dropped, query and fragment
    dropped, trailing slash dropped, lowercased — because the same page is
    written half a dozen ways and a comparison that calls those different
    would report a link that plainly exists as missing.
    """
    want = _norm_href(url)
    if not want:
        return False
    return any(_norm_href(h) == want
               for h in re.findall(r'href\s*=\s*["\']([^"\']+)["\']',
                                   str(html or "")))


def _norm_href(href: str) -> str:
    h = str(href or "").strip().split("#")[0].split("?")[0]
    if not h:
        return ""
    for prefix in ("https://", "http://"):
        if h.lower().startswith(prefix):
            h = h[len(prefix):]
            break
    return h.rstrip("/").lower()


def check(html: str, tenant: str, dests: list[dict] | None = None) -> list[str]:
    """Links in this markup that point at the tenant's own site but at no
    URL known to exist. External links are somebody else's business."""
    dom = _domain(tenant)
    if not dom:
        return []
    dests = destinations(tenant) if dests is None else dests
    known = {d["url"].rstrip("/") for d in dests}
    bad: list[str] = []
    for href in re.findall(r'href\s*=\s*"([^"]+)"', str(html or "")):
        h = href.strip()
        if not h.startswith("http") or dom not in h:
            continue
        if h.split("?")[0].rstrip("/") not in known:
            bad.append(h)
    return sorted(set(bad))


def repoint(html: str, tenant: str, fallback: str,
            dests: list[dict] | None = None) -> tuple[str, list[str]]:
    """Send every unknown on-site link to a real page. Returns (html, fixed).

    Replacing beats blocking, for the reason the empty-href gate had to learn
    the hard way: the drafter cannot know URLs, so treating its guess as a
    fault stops good emails. What it CAN do is write the sentence around the
    link, and that stays exactly as written.
    """
    fixed = check(html, tenant, dests)
    if not (fixed and fallback):
        return html, []
    out = str(html or "")
    for bad in fixed:
        out = out.replace(f'href="{bad}"', f'href="{fallback}"')
    return out, fixed
