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
    a = ap.parse_args()
    out = a.out or os.path.join(tempfile.gettempdir(), f"once-{a.tenant}-{int(time.time())}")
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
        _seed(a.tenant, a.store, a.max_pictures)
    print(f"— recreating {a.url} for {a.tenant}" + (f" about {a.entity}" if a.entity else ""))
    steps: list[str] = []
    got = recreate.swipe(a.url, a.tenant, entity_key=a.entity, progress=lambda t: (steps.append(t), print("  ·", t)))
    rec = got.get("recreation") or {}
    if not got.get("ok") and not rec:
        print("FAILED:", got.get("why"))
        return 1
    st = next((r for r in es.library() if r["id"] == got.get("structure_id")), {})
    with open(os.path.join(out, "brief.json"), "w") as f:
        json.dump(st.get("brief") or {}, f, indent=1, ensure_ascii=False)
    with open(os.path.join(out, "email.html"), "w") as f:
        f.write(rec.get("html") or "")
    latest = recreate.latest(got["structure_id"], a.tenant) or {}
    if latest.get("png"):
        from app import media
        blob_id = latest["png"].rsplit("/", 1)[-1].split(".")[0]
        png, _ = media.get(blob_id)
        with open(os.path.join(out, "email.png"), "wb") as f:
            f.write(png or b"")
    with open(os.path.join(out, "findings.json"), "w") as f:
        json.dump({"status": rec.get("status"), "subject": rec.get("subject"), "preheader": rec.get("preheader"),
                   "findings": rec.get("findings"), "rounds": latest.get("rounds"), "verdict": latest.get("verdict")},
                  f, indent=1, ensure_ascii=False)
    print()
    print("STATUS:", rec.get("status"), "· subject:", rec.get("subject"))
    print("STORY:", rec.get("note"))
    for fnd in rec.get("findings") or []:
        print(f"  [{fnd.get('severity')}] {fnd.get('where')} — {fnd.get('what')}" + (f" → {fnd['do']}" if fnd.get("do") else ""))
    print("OUT:", out)
    return 0


def _seed(tenant: str, store: str, max_pictures: int) -> None:
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
    brand_theme.approve(tenant, {k: v for k, v in edits.items() if v})
    from app import pictures
    read = pictures.read_pictures(tenant, limit=max_pictures, vision=False)
    print(f"  · seeded {n_ent} products, {n_pic} pictures, {read.get('read', 0)} read for their tones"
          + (f"; mark {logo_url}" if logo_url else "; no mark found") + (f"; address {edits['footer.address']}" if edits.get("footer.address") else ""))


if __name__ == "__main__":
    sys.exit(main())
