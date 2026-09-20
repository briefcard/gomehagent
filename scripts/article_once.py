"""THE LOOKING LOOP for the blog — one article, on a laptop, against a real key.

    python3 scripts/article_once.py --tenant baci --store https://bacimilanousa.com \\
        --keyword "melamine vs porcelain dinnerware" \\
        [--rivals https://a.com/x,https://b.com/y] [--approach https://c.com/z] \\
        [--entity 18-piece-set-portofino-melamine] [--collections melamine,porcelain] \\
        [--db runs/<earlier>/once.db] [--no-vision]

Seeds a throwaway store (the same seed as `recreate_once.py`: products, every
picture, the mark, the address, the faces and accent from the storefront),
reads the rivals given (locally there is no Semrush; on the deploy the
rivals are on file), decides the story, writes the article, checks it,
renders it, judges it against the top rival, edits, keeps the best round —
and writes `brief.json`, `story.json`, `article.html`, `page.html`,
`article.png`, `findings.json` to `runs/article-<tenant>-<stamp>/`.
The key lives in `.env.keys`; it is read, never printed.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--store", required=True, help="the public store, e.g. https://bacimilanousa.com")
    ap.add_argument("--keyword", required=True)
    ap.add_argument("--rivals", default="", help="comma-separated URLs of the pages that rank (locally there is no Semrush)")
    ap.add_argument("--approach", default="", help="an article the owner likes for its way in")
    ap.add_argument("--entity", default="", help="the product the article is about, if one")
    ap.add_argument("--collections", default="", help="comma-separated collection handles the article may link")
    ap.add_argument("--role", default="support")
    ap.add_argument("--out", default="")
    ap.add_argument("--db", default="", help="reuse an earlier run's once.db (skips the seed)")
    ap.add_argument("--max-pictures", type=int, default=60)
    ap.add_argument("--no-vision", action="store_true")
    a = ap.parse_args()
    keys = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env.keys")
    if os.path.exists(keys):
        for ln in open(keys):
            if "=" in ln and not ln.startswith("#"):
                k, v = ln.strip().split("=", 1)
                if v and not os.environ.get(k):
                    os.environ[k] = v
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("no ANTHROPIC_API_KEY — put one in .env.keys; it is read, never printed", file=sys.stderr)
        return 2
    runs = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runs")
    out = a.out or os.path.join(runs, f"article-{a.tenant}-{time.strftime('%Y%m%d-%H%M%S')}")
    os.makedirs(out, exist_ok=True)
    dbfile = a.db or os.path.join(out, "once.db")
    os.environ["DATABASE_URL"] = f"sqlite:///{os.path.abspath(dbfile)}"
    os.environ.setdefault("APPROVAL_SECRET", "local")
    from app import articles, db, tenants
    db.init_db()
    tenants.seed()
    if not a.db:
        from recreate_once import _seed
        _seed(a.tenant, a.store, a.max_pictures, a.no_vision)
    store = a.store.rstrip("/")
    collections = [f"{store}/collections/{c.strip()}" for c in a.collections.split(",") if c.strip()]
    print(f"— writing '{a.keyword}' for {a.tenant}" + (f" about {a.entity}" if a.entity else ""))
    got = articles.run(a.tenant, a.keyword, role=a.role, entity_key=a.entity,
                       rival_urls=[u.strip() for u in a.rivals.split(",") if u.strip()], approach_url=a.approach,
                       collections=collections, progress=lambda t: print("  ·", t))
    print()
    print("STATUS:", got.get("status"), "· title:", got.get("title", ""), "·", got.get("words", 0), "words")
    print("STORY:", got.get("note"))
    st = got.get("story") or {}
    if st:
        print("THE STORY:", st.get("hook", ""))
        for b in st.get("beats") or []:
            print(f"  [{b.get('beat', '')}] ({b.get('about', '')}) {b.get('heading', '')} — {str(b.get('says', ''))[:90]}")
        if st.get("turned"):
            print("  turned:", "; ".join(map(str, st["turned"])))
    for f in got.get("findings") or []:
        print(f"  [{f.get('severity')}] {f.get('where')} — {f.get('what')}" + (f" → {f['do']}" if f.get("do") else ""))
    with open(os.path.join(out, "brief.json"), "w") as f:
        json.dump(got.get("brief") or {}, f, indent=1, ensure_ascii=False)
    with open(os.path.join(out, "story.json"), "w") as f:
        json.dump(st, f, indent=1, ensure_ascii=False)
    if got.get("html"):
        from app.recreate import kit as _kit
        kit_ = _kit(a.tenant)
        with open(os.path.join(out, "article.html"), "w") as f:
            f.write(f"<!-- Title: {got.get('title', '')} -->\n<!-- Meta: {got.get('meta', '')} -->\n" + got["html"])
        with open(os.path.join(out, "page.html"), "w") as f:
            f.write(articles.page(got["html"], got.get("title", ""), kit_))
    if got.get("png"):
        with open(os.path.join(out, "article.png"), "wb") as f:
            f.write(got["png"])
    with open(os.path.join(out, "findings.json"), "w") as f:
        json.dump({"status": got.get("status"), "title": got.get("title"), "meta": got.get("meta"), "verdict": got.get("verdict"),
                   "findings": got.get("findings"), "calls": got.get("calls"),
                   "rounds": [{k: v for k, v in r.items() if k not in ("png", "html")} for r in got.get("rounds") or []]},
                  f, indent=1, ensure_ascii=False, default=str)
    print("OUT:", out)
    return 0 if got.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
