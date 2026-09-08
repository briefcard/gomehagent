"""A Pinterest board, by its link, fills one of the brand's visual boards —
through Pinterest's public feed, no API, no sign-in — and the reference pins
it brings are READ INTO DIRECTION WORDS that ride every picture drawn for
that board. They are never sent as pixels.

Owner, 2026-09-08: *"I dont want to use an API for pinterest but I also
dont have a way to upload those photos directly. Ideally if we can go off a
board link that'd work best."*

WHAT WAS TRUE. The boards card has said since 2026-09-06 that a reference
pin "is read for direction, in words, and never sent"; `board_inputs` kept
it out and nothing read it — a reference pin contributed nothing at all.

THE CONTRACT (a public page format, verified 2026-09-08, not an API):
  https://www.pinterest.com/<user>/<board>.rss → XML; <item> carries the
  pin's <title>, <link>, and a <description> holding an <img src> at
  i.pinimg.com/236x/…; the same path under /originals/ is the full file,
  /736x/ the large thumbnail.

Run: python3 scripts/test_a_pinterest_board_link_fills_a_board.py
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
from types import SimpleNamespace
from urllib.parse import unquote

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'pin.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["PUBLIC_BASE_URL"] = "https://example.test"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image  # noqa: E402

from app import (admin_ui as ui, coherence, creative, db, imagegen, kb,  # noqa: E402
                 kb_seed, llm, pinterest, tenants, web)

KEY = "s3cret"
_fail: list[str] = []
BOARD = "https://www.pinterest.com/bacimilano/lifestyle/"
DIRECTION = ("Soft north daylight from a window at the left, low contrast; a slightly "
             "high three-quarter camera on tables laid with linen; a palette of warm "
             "whites, terracotta and olive; hands appear, faces do not.")


def ck(label: str, cond, detail: str = "") -> None:
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def png(colour, w: int = 96, h: int = 96) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (w, h), colour).save(buf, format="PNG")
    return buf.getvalue()


def _item(n: int, title: str) -> str:
    img = f"https://i.pinimg.com/236x/aa/bb/{n:02d}/{n:02d}abc.jpg"
    return (f"<item><title>{title}</title>"
            f"<link>https://www.pinterest.com/pin/{1000 + n}/</link>"
            f"<description>&lt;a href=&quot;https://www.pinterest.com/pin/{1000 + n}/&quot;&gt;"
            f"&lt;img src=&quot;{img}&quot;&gt;&lt;/a&gt;{title}</description></item>")


FEED = ('<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
        '<title>Lifestyle</title><link>' + BOARD + '</link>'
        + _item(1, "Linen table, morning") + _item(2, "Terracotta and olive")
        + _item(3, "Hands pouring") + '</channel></rss>').encode()

FETCHED: list = []
PICS = {
    "https://i.pinimg.com/originals/aa/bb/01/01abc.jpg": png((200, 120, 80, 255)),
    "https://i.pinimg.com/originals/aa/bb/02/02abc.jpg": png((120, 140, 80, 255)),
    # the third pin's full-size file is gone; its large thumbnail is not
    "https://i.pinimg.com/736x/aa/bb/03/03abc.jpg": png((90, 90, 200, 255)),
    "https://cdn.example/cup.png": png((250, 250, 250, 255)),
}


def main() -> int:
    db.init_db()
    tenants.seed()
    kb_seed.seed_all()
    kb.add_entity("baci", "product", "zodiac-cup", "Zodiac Cup",
                  description="a porcelain cup with a zodiac sign", origin="human")
    kb.add_asset("baci", "https://cdn.example/cup.png", rights=kb.OWNED, title="cup",
                 subject=kb.OBJECT, entity_key="zodiac-cup", origin="human")
    kb.add_board("baci", "Lifestyle", note="tables, daylight")
    kb.add_board("baci", "Studio")

    def _fetch(url):
        FETCHED.append(url)
        return PICS.get(url, b"")
    creative._fetch = _fetch
    feeds: dict = {pinterest.feed_url(BOARD): (200, FEED)}
    asked: list = []
    pinterest.get = lambda url: (asked.append(url) or feeds.get(url, (404, b"")))
    seen: list = []

    def _ask(kind, content, tenant="", max_tokens=0, **k):
        seen.append(content)
        return SimpleNamespace(ok=True, text=DIRECTION, degraded="", error="")
    llm.ask = _ask

    print("— THE LINK IS A BOARD LINK, OR IT IS REFUSED BY NAME —")
    ck("a board link with a query string and no scheme is cleaned to the board",
       pinterest.board_url("pinterest.com/bacimilano/lifestyle/?invite=1")[0] == BOARD)
    ck("  a pin link, a search, or another site is refused",
       all(pinterest.board_url(u)[1] for u in
           ("https://www.pinterest.com/pin/1234/", "https://www.pinterest.com/search/pins/?q=x",
            "https://instagram.com/bacimilano", "")))
    ck("  the feed is the board's own public feed",
       pinterest.feed_url(BOARD) == "https://www.pinterest.com/bacimilano/lifestyle.rss")

    print("\n— THE FEED'S PINS, FULL SIZE —")
    got = pinterest.pins(BOARD)
    ck("the pins come off the feed with their title, link and full-size file",
       got["ok"] and got["title"] == "Lifestyle" and len(got["pins"]) == 3
       and got["pins"][0]["image"] == "https://i.pinimg.com/originals/aa/bb/01/01abc.jpg"
       and got["pins"][0]["link"].endswith("/pin/1001/")
       and got["pins"][0]["title"] == "Linen table, morning", str(got)[:200])
    gone = pinterest.pins("https://www.pinterest.com/nobody/secret/")
    ck("  a board that has no public feed is said, with the feed address",
       not gone["ok"] and "404" in gone["error"] and "secret.rss" in gone["error"], gone.get("error", ""))

    print("\n— FILLING THE BOARD: REFERENCE PINS, THEN THE DIRECTION —")
    res = pinterest.fill_board("baci", "lifestyle", BOARD)
    rows = [a for a in kb.assets("baci", publishable_only=False) if "pinimg" in (a.url or "")]
    ck("every pin lands on the board as a REFERENCE look pin, filed as a scene from that board",
       res.get("ok") and res.get("added") == 3 and len(rows) == 3
       and all((a.rights or "") == kb.REFERENCE for a in rows)
       and all(("lifestyle", "look") in kb.pinned(a) for a in rows)
       and all(a.source == f"pinterest: {BOARD}" and a.subject == kb.SCENE for a in rows),
       str(res)[:220])
    ck("  a pin whose full-size file is gone is kept at its large thumbnail",
       any(a.url == "https://i.pinimg.com/736x/aa/bb/03/03abc.jpg" for a in rows)
       and "https://i.pinimg.com/originals/aa/bb/03/03abc.jpg" in FETCHED)
    d = (kb.boards("baci")["lifestyle"].get("direction") or {})
    ck("  the board is read into direction — one vision call over its reference pins, stored on the board",
       res["read"].get("ok") and d.get("text") == DIRECTION and d.get("from") == 3
       and d.get("read_at") and len(seen) == 1
       and sum(1 for b in seen[0] if b.get("type") == "image") == 3, str(d)[:160])
    ck("  the reading asks for direction and forbids naming a product",
       any("product" in b.get("text", "").lower() and "direction" in b.get("text", "").lower()
           for b in seen[0] if b.get("type") == "text"))
    ck("  the note says what happened, and that the pins are reference",
       "3 pin(s) added" in res["note"] and "REFERENCE" in res["note"]
       and "direction read from 3" in res["note"], res["note"])
    again = pinterest.fill_board("baci", "lifestyle", BOARD)
    ck("filling twice adds nothing twice",
       again.get("added") == 0 and again.get("already") == 3
       and len([a for a in kb.assets("baci", publishable_only=False) if "pinimg" in (a.url or "")]) == 3,
       str(again)[:160])
    ck("  a board that does not exist is refused",
       not pinterest.fill_board("baci", "nowhere", BOARD).get("ok"))
    no_refs = creative.read_board_direction("baci", "studio")
    ck("  a board with no reference pins has nothing to read, and says why",
       not no_refs.get("ok") and "no reference pins" in no_refs.get("why", ""))

    print("\n— THE DIRECTION RIDES EVERY DRAWN CELL; THE PINS NEVER DO —")
    refs = creative.board_inputs("baci", "zodiac-cup", boards=("lifestyle",))
    ck("board_inputs carries the words and keeps the pixels out",
       refs.get("direction", "").startswith("Lifestyle: Soft north daylight")
       and not refs["look"] and len(refs["excluded"]) == 3
       and all("reference only" in e["why"] for e in refs["excluded"]), str(refs.get("direction", ""))[:80])
    ck("  a board without a direction contributes no words",
       creative.board_inputs("baci", "zodiac-cup", boards=("studio",)).get("direction", "") == "")
    sent: list = []
    calls = [0]

    def _post(path, *, json_body=None, files=None, data=None):
        sent.append({"path": path, "files": files, "data": data})
        calls[0] += 1
        n = int((data or {}).get("n") or 1)
        return {"ok": True, "images": [png((calls[0] * 9 % 250, i * 40 + 20, calls[0] // 28, 255))
                                       for i in range(n)]}
    imagegen.post = _post
    creative.assess = lambda blob, brief, tenant="": {
        "ok": True, "verdicts": [], "overall": "reads right", "failed": [], "fix": ""}
    creative.product_features = lambda tenant, entity_key, product, **k: {
        "ok": True, "features": ["a gold glyph"], "cached": False}
    creative.compare_product = lambda candidate, product, features, tenant="": {
        "ok": True, "match": 90, "differences": [], "same": True, "lettering": False, "why": ""}
    cup = coherence.commit("entity", "zodiac-cup", label="Zodiac Cup")
    got2 = creative.batch("baci", commitment=cup, entity_key="zodiac-cup", fmt="ad_frame",
                          positioning="the sign you were born under", plates=2,
                          review=False, boards=("lifestyle",))
    prompts = [str((c["data"] or {}).get("prompt") or "") for c in sent]
    ck("every cell's prompt carries the brand's visual direction, under its heading",
       got2.get("made", 0) >= 1 and prompts
       and all("THE BRAND'S VISUAL DIRECTION" in p and "warm whites, terracotta" in p for p in prompts),
       f"cells={len(prompts)}")
    ck("  and no Pinterest picture is among the request's files",
       all(not any(f[1][0].startswith("look-") for f in (c["files"] or [])) for c in sent))
    sent.clear()
    creative.batch("baci", commitment=cup, entity_key="zodiac-cup", fmt="ad_frame",
                   positioning="the sign you were born under", plates=2,
                   review=False, boards=("studio",))
    ck("  a run on a board without direction carries none",
       sent and all("VISUAL DIRECTION" not in str((c["data"] or {}).get("prompt") or "") for c in sent))

    print("\n— THE BRAND TAB: THE CONTROL AND THE WORDS, ON THE BOARD —")
    page = ui.render_brand(KEY, tenant="baci")
    ck("each board offers a Pinterest board link and a read control",
       page.count('action="/admin/board_fill"') == 2 and page.count('action="/admin/board_read"') == 2
       and "Fill from a Pinterest board" in page)
    ck("  the board shows its direction, and from how many pins",
       "terracotta and olive" in page and "read from 3" in page)
    kb.add_asset("baci", "https://cdn.example/ref-studio.png", rights=kb.REFERENCE, title="ref",
                 subject=kb.SCENE, origin="human")
    rid = next(a.id for a in kb.assets("baci", publishable_only=False) if "ref-studio" in (a.url or ""))
    kb.set_board_role(rid, "studio", "look", True)
    page2 = ui.render_brand(KEY, tenant="baci")
    ck("  a board with reference pins and no direction says they guide nothing yet",
       "not read into direction yet" in page2 and "guide nothing" in page2)

    print("\n— THE ROUTES —")
    scheduled: list = []
    real_bg = web._run_bg
    web._run_bg = lambda label, fn, *a, **kw: scheduled.append((label, fn, a))
    from fastapi.testclient import TestClient
    try:
        client = TestClient(web.app)
        r = client.post("/admin/board_fill", params={"key": KEY},
                        data={"tenant": "baci", "board": "lifestyle",
                              "url": "https://instagram.com/bacimilano"}, follow_redirects=False)
        loc = unquote(r.headers.get("location", ""))
        ck("a link that is not a Pinterest board is refused on the Brand tab, at the board",
           r.status_code == 303 and "tab=brand" in loc and "not a Pinterest board" in loc
           and loc.endswith("#board-lifestyle") and not scheduled, loc[:200])
        r = client.post("/admin/board_fill", params={"key": KEY},
                        data={"tenant": "baci", "board": "lifestyle", "url": BOARD + "?x=1"},
                        follow_redirects=False)
        ck("  a board link schedules the fill in the background, cleaned, and says so",
           r.status_code == 303 and scheduled and scheduled[-1][0] == "boards"
           and scheduled[-1][1] is pinterest.fill_board and scheduled[-1][2] == ("baci", "lifestyle", BOARD)
           and "background" in unquote(r.headers.get("location", "")), str(scheduled)[:160])
        r = client.post("/admin/board_read", params={"key": KEY},
                        data={"tenant": "baci", "board": "studio"}, follow_redirects=False)
        ck("  reading a board's pins into direction is its own control",
           r.status_code == 303 and scheduled[-1][0] == "boards"
           and scheduled[-1][1] is creative.read_board_direction and scheduled[-1][2] == ("baci", "studio"))
    finally:
        web._run_bg = real_bg
    ck("  the label the boards card reads is declared",
       any(lbl == "boards" for lbl, _n in ui.BG_BRAND_LABELS))
    with db.SessionLocal() as s:
        s.merge(db.Setting(key="bg:boards:baci", value=json.dumps(
            {"state": "failed", "detail": "Pinterest answered 404 for the board's feed",
             "at": "2026-09-08T10:00:00"})))
        s.commit()
    page3 = ui.render_brand(KEY, tenant="baci")
    ck("  a fill that failed is said on the card, with the reason",
       "The board fill failed" in page3 and "answered 404" in page3)

    print()
    if _fail:
        print(f"{len(_fail)} FAILED:\n  " + "\n  ".join(_fail))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
