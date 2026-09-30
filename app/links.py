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

import html as _html
import json
import re
from urllib.parse import urljoin, urlparse

#: Handles a store might use for "everything we sell". Ordered by how likely
#: they are to be the real catalogue rather than a subset. Only ever used to
#: RANK handles that genuinely exist — never to construct one.
_SHOP_HANDLES = ("shop", "all", "catalog", "catalogue", "products", "store",
                 "shop-all", "all-products")


def _domain(tenant: str) -> str:
    from . import tenants
    t = tenants.get(tenant)
    return (getattr(t, "domain", "") or "").strip().lower()


#: THE SITE'S OWN PAGES AND ITS MENU, read off the site by the worker — a
#: daily sweep and once after each deploy, never inside a request or a run.
#: Owner, 2026-09-29: the email's header needs the site's navigation and
#: "Request a Partnership" needs the wholesale page — pages no catalogue read
#: names, and the theme's nav that should have held them was never filled
#: (nothing derived it, nothing on the Brand tab set it).
SITE_KEY = "site_pages:{}"
_NOT_A_PAGE = {"products", "collections", "blogs", "search", "cart", "account", "pages",
               "sitemap", "policies", "checkout", "password", "tagged", "feed"}
_NOT_IN_MENU = ("/account", "/cart", "/search", "/login", "/checkout", "/policies", "/password")


def pages_from(urls: list[str], dom: str) -> list[dict]:
    """The site's own pages out of its sitemap: Shopify's `/pages/<slug>`, or
    a top-level `/<slug>` on a site with no `/pages/` (Squarespace) — never a
    product, a collection, a post or a tag. Labelled from the slug."""
    out, seen = [], set()
    for u in urls:
        p = urlparse(str(u or ""))
        if dom not in (p.netloc or "").lower():
            continue
        path = p.path.rstrip("/")
        m = re.fullmatch(r"/pages/([\w-]+)", path) or re.fullmatch(r"/([\w-]+)", path)
        if not m or m.group(1).lower() in _NOT_A_PAGE:
            continue
        url = f"https://{dom}{path}"
        if url not in seen:
            seen.add(url)
            out.append({"label": re.sub(r"[-_]+", " ", m.group(1)).strip().title(), "url": url})
    return out[:80]


def menu_from(page: str, dom: str) -> list[dict]:
    """The links in the site's own header — its navigation as a visitor sees
    it at the top of the home page — in their order, with their words."""
    block = re.search(r"<header\b.*?</header>", page or "", re.S | re.I)
    scope = block.group(0) if block else " ".join(re.findall(r"<nav\b.*?</nav>", page or "", re.S | re.I))
    out, seen = [], set()
    for href, text in re.findall(r"<a\b[^>]*?href=[\"']([^\"'#]+)[\"'][^>]*>(.*?)</a>", scope, re.S | re.I):
        label = _html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text))).strip()
        p = urlparse(urljoin(f"https://{dom}/", href.strip()))
        if not label or len(label) > 24 or dom not in (p.netloc or "").lower():
            continue
        if any(p.path.startswith(x) for x in _NOT_IN_MENU):
            continue
        url = f"https://{dom}{p.path.rstrip('/')}" if p.path not in ("", "/") else f"https://{dom}"
        if url not in seen:
            seen.add(url)
            out.append({"label": label, "url": url})
    return out[:8]


def read_site(tenant: str) -> dict:
    """`{at, pages, menu}` read off the site — its sitemap's pages and its
    header's links. NETWORK, so the worker's to call, never a request's; the
    worker files what this returns (it already writes the settings table, and
    a second writer is what the register's ratchet refuses)."""
    from . import brand_theme, compliance, db
    dom = _domain(tenant)
    if not dom:
        return {"skipped": "no domain on file"}
    base = f"https://{dom}"
    urls = [str(r.get("url") or "") for r in compliance._sitemap_urls(base, limit=2000)]
    try:
        home = brand_theme.fetch_page(base)
    except Exception:                                             # noqa: BLE001
        home = ""
    return {"at": db.utcnow().isoformat(), "pages": pages_from(urls, dom), "menu": menu_from(home, dom)}


def site_pages(tenant: str) -> dict:
    """`{at, pages, menu}` as last read off the site — `{}` when never read."""
    from . import db
    with db.SessionLocal() as s:
        row = s.get(db.Setting, SITE_KEY.format(tenant))
        value = row.value if row is not None else ""
    try:
        return json.loads(value) if value else {}
    except ValueError:
        return {}


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
    # THE SITE'S OWN MENU AND PAGES, as the worker last read them — a
    # wholesale page, a contact page — so a button's words can find theirs.
    site = site_pages(tenant)
    for item in list(site.get("menu") or []) + list(site.get("pages") or []):
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


#: A BUTTON GOES WHERE ITS WORDS SAY. Owner, 2026-09-29: "the buttons don't
#: correspond with the correct links like 'Request a Partnership' should take
#: you to the wholesale page not the collections page." Every button the
#: drafter wrote without an address was sent to ONE fallback page, whatever it
#: said. Each job: the words a button uses for it, then the words its page
#: carries in its label or address.
INTENTS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "wholesale": (("wholesale", "partnership", "partner with", "become a partner", "trade",
                   "stockist", "retailer", "reseller", "b2b", "for retailers",
                   "for your store", "for your shop"),
                  ("wholesale", "trade", "partner", "stockist", "retailer", "b2b")),
    "contact": (("contact", "get in touch", "talk to us", "write to us", "email us", "call us",
                 "enquire", "inquire", "ask us"),
                ("contact", "get-in-touch", "enquir", "inquir")),
    "about": (("our story", "about us", "who we are", "meet the"),
              ("about", "our-story", "story")),
    "stores": (("find a store", "store locator", "visit a store", "near you"),
               ("stores", "locator", "stockists", "find-a-store")),
}


def for_words(words: str, dests: list[dict]) -> dict | None:
    """The page a button's words name, or None when they name none in
    particular ("Shop now" is the fallback's to answer, not this)."""
    w = " " + re.sub(r"[^a-z0-9' ]+", " ", str(words or "").lower()) + " "
    for _job, (said, page) in INTENTS.items():
        if any(f" {t} " in w or f" {t}" in w for t in said):
            for d in dests:
                if d.get("kind") in ("page", "home", "collection"):
                    hay = f"{d.get('label', '')} {d.get('url', '')}".lower()
                    if any(p in hay for p in page):
                        return d
            return None
    # A button that names a collection by its own name goes to that collection.
    toks = {t for t in re.findall(r"[a-z]{4,}", w)} - {"shop", "view", "see", "discover", "explore",
                                                       "collection", "collections", "more", "the"}
    best, best_n = None, 0
    for d in dests:
        if d.get("kind") != "collection":
            continue
        name = {t for t in re.findall(r"[a-z]{4,}", str(d.get("label", "")).lower())}
        n = len(name & toks)
        if name and n == len(name) and n > best_n:
            best, best_n = d, n
    return best


_A = re.compile(r"<a\b([^>]*?)href=([\"'])(.*?)\2([^>]*)>(.*?)</a>", re.I | re.S)


def match_buttons(html: str, dests: list[dict]) -> tuple[str, list[str]]:
    """`(html, changes)` — every link whose words name a page sent to that
    page. Only a link of button length (40 characters of words or fewer) is
    read, and only one whose words name a page is moved."""
    changes: list[str] = []

    def one(m):
        words = re.sub(r"<[^>]+>", " ", m.group(5))
        words = re.sub(r"\s+", " ", words).strip()
        href = m.group(3)
        if not words or len(words) > 40 or not href.startswith("http"):
            return m.group(0)
        hit = for_words(words, dests)
        if not hit or _norm_href(hit["url"]) == _norm_href(href):
            return m.group(0)
        changes.append(f"“{words}” went to {href} — sent to {hit['url']}, the page it names")
        return f"<a{m.group(1)}href={m.group(2)}{hit['url']}{m.group(2)}{m.group(4)}>{m.group(5)}</a>"

    return _A.sub(one, html or ""), changes


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
