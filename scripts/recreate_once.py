"""ONE REAL RUN, LOOKED AT. The whole email maker — brief, cast, compose,
bake, check, shoot, judge — against a brand's public store, with a real
model key, writing the email, its picture and its story to a folder so the
person building it sees the output before anything ships.

    python3 scripts/recreate_once.py --tenant baci --store https://bacimilanousa.com \\
        --url https://reallygoodemails.com/emails/<slug> [--entity portofino] [--out /tmp/once]

Needs ANTHROPIC_API_KEY in the environment or in .env (never printed). Uses
a throwaway SQLite file, never the deployed database. Pictures come from the
store's public products.json (every product image, the packshot first);
the brand's mark, address and handle from its homepage.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--store", required=True, help="the storefront, e.g. https://bacimilanousa.com")
    ap.add_argument("--url", required=True, help="one email's page on reallygoodemails.com")
    ap.add_argument("--entity", default="", help="the entity key the email is about (a product handle)")
    ap.add_argument("--out", default="")
    ap.add_argument("--db", default="", help="reuse a seeded database from an earlier run")
    ap.add_argument("--max-pictures", type=int, default=60)
    ap.add_argument("--no-vision", action="store_true",
                    help="skip reading each picture's KIND with the model (a lifestyle shot vs a packshot); the "
                         "cast sheet is then mixed by the store's ordering alone")
    ap.add_argument("--reread", action="store_true", help="read the reference again even if its brief is on file")
    a = ap.parse_args()
    # A durable folder, not the system temp dir: macOS cleared the first
    # runs' folders before anyone looked at them (2026-09-17). Git-ignored.
    runs = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runs")
    out = a.out or os.path.join(runs, f"once-{a.tenant}-{time.strftime('%Y%m%d-%H%M%S')}")
    os.makedirs(out, exist_ok=True)
    dbfile = a.db or os.path.join(out, "once.db")
    os.environ["DATABASE_URL"] = f"sqlite:///{dbfile}"
    os.environ.setdefault("APPROVAL_SECRET", "once")
    os.environ.setdefault("PUBLIC_BASE_URL", "http://localhost:8000")
    # THE KEY LIVES IN `.env.keys`, NOT `.env`: `config.load_dotenv()` reads
    # `.env` into every process, suites included — and the suites are written
    # to run keyless. This script alone reads the keys file, never printing it.
    keys = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env.keys")
    if os.path.exists(keys):
        for ln in open(keys):
            if "=" in ln and not ln.startswith("#"):
                k, v = ln.strip().split("=", 1)
                if v and not os.environ.get(k):
                    os.environ[k] = v
    from app import brand_theme, config, db, email_structures as es, kb, recreate, tenants
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("no ANTHROPIC_API_KEY — put one in .env.keys (ANTHROPIC_API_KEY=…); it is read, never printed", file=sys.stderr)
        return 2
    db.init_db()
    tenants.seed()
    kb.ensure_brand(a.tenant, a.tenant.title())
    if not a.db:
        _seed(a.tenant, a.store, a.max_pictures, a.no_vision)
    print(f"— recreating {a.url} for {a.tenant}" + (f" about {a.entity}" if a.entity else ""))
    steps: list[str] = []
    if a.reread and a.db:
        from app import email_structures as _es2
        _sid = next((r["id"] for r in _es2.library() if r.get("source_url") == a.url or (r.get("brief") or {}).get("concept")), "")
        got = {"ok": True, "structure_id": _sid,
               "recreation": recreate.again(_sid, a.tenant, entity_key=a.entity, progress=lambda t: (steps.append(t), print("  ·", t)))} if _sid else recreate.swipe(a.url, a.tenant, entity_key=a.entity, progress=lambda t: (steps.append(t), print("  ·", t)))
    else:
        got = recreate.swipe(a.url, a.tenant, entity_key=a.entity, progress=lambda t: (steps.append(t), print("  ·", t)))
    rec = got.get("recreation") or {}
    if not got.get("ok") and not rec:
        print("FAILED:", got.get("why"))
        return 1
    st = next((r for r in es.library() if r["id"] == got.get("structure_id")), {})
    with open(os.path.join(out, "brief.json"), "w") as f:
        json.dump(st.get("brief") or {}, f, indent=1, ensure_ascii=False)
    html = rec.get("html") or ""
    # the baked blocks live on our media route, which no server serves here:
    # write them beside the page so the file opens whole (broken pictures on
    # the owner's first look, 2026-09-17)
    if html:
        from app import config as _cfg, media as _media
        base = _cfg.PUBLIC_BASE_URL.rstrip("/") + "/media/"
        os.makedirs(os.path.join(out, "media"), exist_ok=True)
        for bid, ext in set(re.findall(re.escape(base) + r"([0-9a-f]{32})\.(\w+)", html)):
            try:
                blob, _mime = _media.get(bid)
                open(os.path.join(out, "media", f"{bid}.{ext}"), "wb").write(blob or b"")
                html = html.replace(f"{base}{bid}.{ext}", f"media/{bid}.{ext}")
            except Exception as e:                                # noqa: BLE001
                print("  · could not localise", bid, e)
    with open(os.path.join(out, "email.html"), "w") as f:
        f.write(html)
    latest = recreate.latest(got["structure_id"], a.tenant) or {}
    if latest.get("png"):
        from app import media
        blob_id = latest["png"].rsplit("/", 1)[-1].split(".")[0]
        png, _ = media.get(blob_id)
        with open(os.path.join(out, "email.png"), "wb") as f:
            f.write(png or b"")
    with open(os.path.join(out, "findings.json"), "w") as f:
        json.dump({"status": rec.get("status"), "subject": rec.get("subject"), "preheader": rec.get("preheader"),
                   "story": latest.get("story"),
                   "findings": rec.get("findings"), "rounds": latest.get("rounds"), "verdict": latest.get("verdict")},
                  f, indent=1, ensure_ascii=False)
    print()
    print("STATUS:", rec.get("status"), "· subject:", rec.get("subject"))
    print("STORY:", rec.get("note"))
    st_ = latest.get("story") or {}
    if st_:
        print("THE STORY:", st_.get("hook", ""))
        for b_ in st_.get("beats") or []:
            print(f"  [{b_.get('beat', '')}] ({b_.get('about', '')}) {b_.get('says', '')}" + (f"  <- {b_['rests_on']}" if b_.get("rests_on") else ""))
        if st_.get("turned"):
            print("  turned:", "; ".join(map(str, st_["turned"])))
    for fnd in rec.get("findings") or []:
        print(f"  [{fnd.get('severity')}] {fnd.get('where')} — {fnd.get('what')}" + (f" → {fnd['do']}" if fnd.get("do") else ""))
    print("OUT:", out)
    return 0


def _seed(tenant: str, store: str, max_pictures: int, no_vision: bool = False) -> None:
    """The brand as its public store shows it: products with their images
    (packshot first), the mark, the address, the Instagram handle."""
    import httpx
    from app import brand_theme, kb
    ua = {"User-Agent": "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
    store = store.rstrip("/")
    r = httpx.get(f"{store}/collections/all/products.json?limit=250", headers=ua, timeout=30, follow_redirects=True)
    products = r.json().get("products", [])
    n_ent = n_pic = 0
    for p in products:
        handle, title = p.get("handle", ""), p.get("title", "")
        images = p.get("images") or []
        if not (handle and title and images):
            continue
        price = (p.get("variants") or [{}])[0].get("price", "")
        desc = re.sub(r"<[^>]+>", " ", p.get("body_html") or "")
        kb.add_entity(tenant, "product", handle, title, description=desc[:600], price=price,
                      attributes={"image": images[0]["src"], "url": f"{store}/products/{handle}"}, origin="human")
        n_ent += 1
        for i, im in enumerate(images):
            if n_pic >= max_pictures:
                break
            src = im["src"]
            name = src.rsplit("/", 1)[-1].split("?")[0].lower()
            packshot = i == 0 or name.endswith(".png")
            kb.add_asset(tenant, src, rights=kb.OWNED, subject="object" if packshot else "photo",
                         tags=["store-image:%d" % (i + 1)] + (["packshot"] if packshot else []),
                         title=(im.get("alt") or title)[:120], entity_key=handle, origin="store_sync")
            n_pic += 1
    home = httpx.get(store, headers=ua, timeout=30, follow_redirects=True).text
    logo = re.search(r'src="([^"]*[Ll]ogo[^"]*\.(?:png|svg|webp))', home)
    logo_url = logo.group(1) if logo else ""
    if logo_url.startswith("//"):
        logo_url = "https:" + logo_url
    handle = re.search(r'instagram\.com/([A-Za-z0-9_.]+)', home)
    addr = re.search(r"(\d{2,5} [A-Z][^<|\"]{3,60}?(?:Ave|Avenue|St\b|Street|Blvd|Boulevard|Road|Rd|Way|Drive|Dr\b)[^<|\"]{0,40})", home)
    edits = {"footer.address": (addr.group(1).strip() if addr else ""), "logo_url": logo_url}
    if handle:
        edits["footer.socials"] = [{"name": "Instagram", "url": f"https://instagram.com/{handle.group(1)}"}]
    # THE BRAND'S FACES AND ACCENT, from the storefront's own CSS variables — a
    # Shopify theme declares --font-heading--family / --font-body--family and
    # its primary button colour. Without them the maker invented Playfair and
    # green on every local run (2026-09-17) and we judged it on a brand with no
    # brand; the deploy's deriver fills these from Canva/Shopify/site.
    def _var(name):
        m2 = re.search(re.escape(name) + r"\s*:\s*([^;}]+)", home)
        return m2.group(1).strip() if m2 else ""
    heading, body = _var("--font-heading--family"), _var("--font-body--family")
    if heading:
        edits["font.heading"] = heading.split(",")[0].strip().strip("'\"")
    if body:
        edits["font.body"] = body.split(",")[0].strip().strip("'\"")
    btn = _var("--color-primary-button-background") or _var("--color-button") or _var("--color-accent")
    rgb = re.match(r"rgb\(\s*(\d+)\s+(\d+)\s+(\d+)", btn or "")
    if rgb:
        edits["colors.accent"] = "#%02x%02x%02x" % tuple(int(x) for x in rgb.groups())
    elif re.match(r"#[0-9a-fA-F]{6}$", btn or ""):
        edits["colors.accent"] = btn
    brand_theme.approve(tenant, {k: v for k, v in edits.items() if v})
    from app import pictures
    # KINDS BY LOOKING, as the deploy does from the Brand tab: without them the
    # cast sheet cannot put a scene beside a packshot, and the owner's run of
    # 2026-09-17 cast the product alone twice ("a bit plain")
    read = pictures.read_pictures(tenant, limit=max_pictures, vision=not no_vision)
    kinds: dict = {}
    for a in kb.assets(tenant):
        k = (a.reading or {}).get("kind") or "unread"
        kinds[k] = kinds.get(k, 0) + 1
    print(f"  · seeded {n_ent} products, {n_pic} pictures, {read.get('read', 0)} read"
          + (" by looking: " + ", ".join(f"{n} {k}" for k, n in sorted(kinds.items(), key=lambda x: -x[1])) if not no_vision else " for their tones")
          + (f"; mark {logo_url}" if logo_url else "; no mark found") + (f"; address {edits['footer.address']}" if edits.get("footer.address") else "")
          + (f"; faces {edits.get('font.heading')}/{edits.get('font.body')}" if edits.get("font.body") else "; no faces found on the site")
          + (f"; accent {edits['colors.accent']}" if edits.get("colors.accent") else "; no accent found on the site"))


if __name__ == "__main__":
    sys.exit(main())
