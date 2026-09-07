"""The brand's visual board reaches the generator as pictures, not as words.

Owner, 2026-09-06, on a set of Baci frames: *"just some generic photo of
someone drinking out of a nameless white mug … We have photos of this product
for examples and existing product assets to reference for vibe and quality. So
why are we doing this so poorly?"* — and then: *"each brand should be able to
share a visual board similar to a pinterest board from which the AI should
mimic styling and positioning."*

WHAT WAS TRUE: two photographs of the product on file; four generation calls;
none carried an image. Every request was a JSON body — prompt, size, n — and
the only thing the model was ever told about the product was "do not invent
one". The person-led cell, the one the owner saw, could not carry the product
by construction: its framing said "incidental or absent", its moment could say
"without the product anywhere", and the rule said invent nothing.

TWO KINDS OF PIN, TWO USES, ONE GATE. The brand's OWN pictures go INTO the
request as image inputs — the product from its photographs, the look from the
pins. A REFERENCE pin (someone else's picture, saved for inspiration) never
does: it is kept out by the same `may_publish` gate that keeps it out of a
composite, and the set SAYS it was kept out and why.

AND THE BOARDS ARE THE SWITCH. An account with nothing pinned gets the route
it had yesterday; the day this shipped must not have been the day every
account's frames quietly changed.

BOARDS ARE NAMED, AND A RUN CHOOSES. Owner, later the same day: *"we may have
different looks per brand - studio vs lifestyle vs specific collections. So
please allow us to create these references and optionally select which to
pull from for each run. Please make sure this is accessible by the other
systems as well not just ads."* So a board is created by name, a pin goes on
a board with a role, a run names its boards (none named means all), a board
that does not exist is said rather than widened — and the article hero, the
email hero and `pick` reach the same boards through the same seam.

Run: python3 scripts/test_the_board_reaches_the_generator.py
"""
from __future__ import annotations

import io
import os
import sys
import tempfile
from urllib.parse import unquote

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'board.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["PUBLIC_BASE_URL"] = "https://example.test"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import (admin_ui as ui, coherence, creative, db, imagegen, kb,  # noqa: E402
                 kb_seed, tenants)
from app.web import app  # noqa: E402

KEY = "s3cret"
client = TestClient(app)
_fail: list[str] = []


def ck(label: str, cond, detail: str = "") -> None:
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def png(colour, mode: str = "RGBA", w: int = 80, h: int = 80) -> bytes:
    buf = io.BytesIO()
    Image.new(mode, (w, h), colour).save(buf, format="PNG")
    return buf.getvalue()


def colour_of(blob: bytes) -> tuple:
    return Image.open(io.BytesIO(blob)).convert("RGB").getpixel((2, 2))


def near(a, b, tol: int = 6) -> bool:
    return all(abs(x - y) <= tol for x, y in zip(a, b))


# EVERY PICTURE A SOLID COLOUR, so the bytes the model receives — resized and
# re-encoded on the way — can be traced back to the row they came from. A
# check that the request "has files" would pass on the reference pin's bytes.
PRODUCT_FRONT = (200, 30, 30)
PRODUCT_SIDE = (30, 200, 30)
LOOK_TABLE = (30, 30, 200)
LOOK_LINEN = (200, 200, 30)
SOMEONE_ELSES = (120, 0, 120)
PICS = {
    "https://cdn.example/zodiac-front.png": (PRODUCT_FRONT, "RGBA"),
    "https://cdn.example/zodiac-side.png": (PRODUCT_SIDE, "RGBA"),
    "https://cdn.example/table-evening.png": (LOOK_TABLE, "RGBA"),
    "https://cdn.example/linen-detail.jpg": (LOOK_LINEN, "RGB"),
    "https://pinterest.example/someone-elses-table.png": (SOMEONE_ELSES, "RGBA"),
    "https://cdn.example/omega-bottle.png": ((10, 90, 160), "RGBA"),
    "https://cdn.example/omega-kitchen.png": ((160, 90, 10), "RGBA"),
}


def _blob(url: str) -> bytes:
    if url not in PICS:
        return b""
    colour, mode = PICS[url]
    return png(colour + ((255,) if mode == "RGBA" else ()), mode=mode)


def _id(tenant: str, url: str) -> str:
    return next(a.id for a in kb.assets(tenant, publishable_only=False)
                if a.url == url)


def _inputs(call: dict) -> list:
    """`[(field, colour, mime)]` for one recorded request."""
    return [(name, colour_of(part[1]), part[2]) for name, part in (call["files"] or [])]


def main() -> int:
    db.init_db()
    tenants.seed()
    kb_seed.seed_all()

    sent: list = []
    calls = [0]

    def _fake_post(path, *, json_body=None, files=None, data=None):
        sent.append({"path": path, "files": files, "data": data, "json": json_body})
        calls[0] += 1
        n = int((data or {}).get("n") or (json_body or {}).get("n") or 1)
        # EVERY IMAGE DISTINCT, ACROSS THE WHOLE RUN: identical bytes are
        # content-addressed into one row, and a counter that restarted with
        # `sent.clear()` made the second set a duplicate of the first.
        return {"ok": True, "images": [png((calls[0] * 9 % 250, i * 40,
                                            calls[0] // 28, 255))
                                       for i in range(n)]}

    imagegen.post = _fake_post
    creative._fetch = _blob
    creative.assess = lambda blob, brief, tenant="": {
        "ok": True, "verdicts": [], "overall": "reads right", "failed": [], "fix": ""}

    print("— THE BOARD: what may be pinned, and as what —")
    kb.add_entity("baci", "product", "zodiac-cup", "Zodiac Cup",
                  description="a porcelain cup with a hand-painted zodiac sign",
                  origin="human")
    kb.add_asset("baci", "https://cdn.example/zodiac-front.png", rights=kb.OWNED,
                 title="Zodiac cup, front", subject=kb.OBJECT,
                 entity_key="zodiac-cup", origin="human")
    kb.add_asset("baci", "https://cdn.example/zodiac-side.png", rights=kb.OWNED,
                 title="Zodiac cup, side", subject=kb.OBJECT,
                 entity_key="zodiac-cup", origin="human")
    kb.add_asset("baci", "https://cdn.example/table-evening.png", rights=kb.OWNED,
                 title="Table, evening", subject=kb.SCENE, origin="human")
    kb.add_asset("baci", "https://cdn.example/linen-detail.jpg", rights=kb.OWNED,
                 title="Linen detail", subject=kb.SCENE, origin="human")
    kb.add_asset("baci", "https://pinterest.example/someone-elses-table.png",
                 rights=kb.REFERENCE, title="a table we liked on Pinterest",
                 subject=kb.SCENE, origin="human")
    table = _id("baci", "https://cdn.example/table-evening.png")
    linen = _id("baci", "https://cdn.example/linen-detail.jpg")
    ref = _id("baci", "https://pinterest.example/someone-elses-table.png")
    front = _id("baci", "https://cdn.example/zodiac-front.png")

    ck("a brand starts with no boards and nothing pinned",
       kb.boards("baci") == {} and kb.board("baci")["look"] == []
       and kb.board("baci")["product"] == [])
    ck("a picture cannot be pinned to a board that does not exist",
       "no board called" in kb.set_board_role(table, "studio", "look", True).lower())
    ck("boards are created by name, and answer to a slug",
       kb.add_board("baci", "Studio", note="on white, hard shadow").startswith("Created")
       and kb.add_board("baci", "Lifestyle").startswith("Created")
       and kb.add_board("baci", "Zodiac collection").startswith("Created")
       and set(kb.boards("baci")) == {"studio", "lifestyle", "zodiac-collection"}
       and kb.boards("baci")["studio"]["note"] == "on white, hard shadow",
       str(list(kb.boards("baci"))))
    ck("  the same name twice is refused, not duplicated",
       "already" in kb.add_board("baci", "Studio").lower()
       and len(kb.boards("baci")) == 3)
    ck("  and a board needs a name",
       kb.set_board_role(table, "", "look", True).lower().startswith("no board")
       and "needs a name" in kb.add_board("baci", "  "))
    kb.set_board_role(linen, "studio", "look", True)
    kb.set_board_role(table, "lifestyle", "look", True)
    kb.set_board_role(ref, "lifestyle", "look", True)
    ck("an owned picture and a reference one can both be pinned as the look",
       {r.id for r in kb.board("baci")["look"]} == {table, linen, ref}
       and {r.id for r in kb.board("baci", ["studio"])["look"]} == {linen}
       and {r.id for r in kb.board("baci", ["lifestyle"])["look"]} == {table, ref})
    refused = kb.set_board_role(ref, "lifestyle", "product", True)
    ck("a REFERENCE picture cannot be pinned as the product",
       "reference" in refused.lower()
       and ref not in {r.id for r in kb.board("baci")["product"]}, refused)
    ck("  an unknown role is refused, not stored",
       "no such board role" in kb.set_board_role(table, "studio", "hero", True).lower())
    ck("  and pinning is one tag on the row, beside the ones it had",
       kb.set_board_role(front, "zodiac-collection", "product", True).startswith("Pinned")
       and "board:zodiac-collection:product" in next(a.tags for a in kb.assets("baci")
                                                     if a.id == front)
       and kb.pinned(next(a for a in kb.assets("baci") if a.id == front))
       == [("zodiac-collection", "product")])
    ck("a name that is not a board comes back as unknown, never widened to all",
       kb.board("baci", ["nowhere"]) == {"look": [], "product": [],
                                          "unknown": ["nowhere"], "boards": []}
       and kb.board("baci", ["studio", "nowhere"])["unknown"] == ["nowhere"]
       and {r.id for r in kb.board("baci", ["studio", "nowhere"])["look"]} == {linen})

    print("\n— THE REQUEST: the product from its photographs, the look from the pins —")
    cup = coherence.commit("entity", "zodiac-cup", label="Zodiac Cup")
    got = creative.batch("baci", commitment=cup, entity_key="zodiac-cup",
                         fmt="ad_frame", positioning="the sign you were born under",
                         plates=4, review=True)
    edits = [c for c in sent if c["path"] == "/images/edits"]
    ck("a pinned brand's frames are generated FROM its pictures — every one",
       got["ok"] and len(edits) == 4 and len(sent) == 4 and not got["errors"],
       f"{[c['path'] for c in sent]} errors={got['errors'][:2]}")
    ins = [_inputs(c) for c in edits]
    chosen = next((a.url for a in kb.assets("baci") if a.id == got["product_asset"]), "")
    first = PICS.get(chosen, ((0, 0, 0), ""))[0]
    ck("the product's own photographs are the first inputs — pick's choice first",
       all(len(i) >= 2 and {tuple(i[0][1]) == first or near(i[0][1], first)}
           and {c for _, c, _ in i[:2]} and near(i[0][1], first)
           and (near(i[1][1], PRODUCT_FRONT) or near(i[1][1], PRODUCT_SIDE))
           and not near(i[1][1], i[0][1]) for i in ins),
       f"chosen={chosen.rsplit('/', 1)[-1]} first={[c for _, c, _ in ins[0][:2]]}")
    ck("  and the look pins follow them",
       all(any(near(c, LOOK_TABLE) for _, c, _ in i)
           and any(near(c, LOOK_LINEN) for _, c, _ in i) for i in ins))
    ck("a REFERENCE pin never reaches the model",
       not any(near(c, SOMEONE_ELSES) for i in ins for _, c, _ in i))
    ck("  and the set says it was kept out, and why",
       any(e["asset_id"] == ref and "reference" in e["why"].lower()
           for e in got["board"]["excluded"])
       and "kept out of the request" in got["note"], got["note"][:200])
    ck("every input travels under the one field name the API takes a list on",
       all(name == "image[]" for i in ins for name, _, _ in i))
    ck("a photograph goes as JPEG, a cutout keeps its alpha as PNG",
       any(m == "image/jpeg" for i in ins for _, _, m in i)
       and any(m == "image/png" for i in ins for _, _, m in i))
    ck("the request asks for fidelity to the inputs",
       all(c["data"].get("input_fidelity") == "high" for c in edits))
    prompts = [c["data"]["prompt"] for c in edits]
    ck("the prompt says THIS product, exactly — it no longer forbids one",
       all("reproduced EXACTLY" in p and imagegen._NO_INVENTED_PRODUCT not in p
           for p in prompts))
    ck("  and says which inputs are the look, not the contents",
       all("THE LOOK" in p and "not the contents" in p for p in prompts))
    framings = [f["cell"]["framing"] for f in got["frames"]]
    ck("no cell excludes the product any more — the person-led frame carries it",
       "person_led" in framings
       and not any("without the product" in p or "incidental or absent" in p
                   for p in prompts),
       str(framings))
    ck("  the product-led cells were DRAWN, not composited",
       {"product_led", "detail"} <= set(framings) and got["pasted"] == 0
       and got["board"]["drawn"] is True)
    rows = [a for a in kb.assets("baci", publishable_only=False)
            if (a.batch or "") == got["batch"]]
    ck("every frame records the pictures it was drawn from",
       rows and all(set(r.derived_from or []) == set(got["board"]["pins"]) for r in rows)
       and set(got["board"]["pins"]) == {front, _id("baci", "https://cdn.example/zodiac-side.png"),
                                         table, linen},
       f"{len(rows)} rows, pins={got['board']['pins']}")
    ck("  a run that names no board draws from every board",
       sorted(got["board"]["boards"]) == ["lifestyle", "studio", "zodiac-collection"]
       and got["board"]["unknown"] == [])
    ck("  the pinned product shot comes before the other photographs",
       all(near(i[0][1], PRODUCT_FRONT) for i in ins))

    print("\n— THE SELECTION: a run pulls from the boards it names —")
    sent.clear()
    got_s = creative.batch("baci", commitment=cup, entity_key="zodiac-cup",
                           fmt="ad_frame", positioning="the sign you were born under",
                           plates=1, review=False, boards=["studio"])
    ins_s = [_inputs(c) for c in sent]
    ck("naming one board pulls that board's look and no other's",
       got_s["ok"] and got_s["board"]["boards"] == ["studio"]
       and all(any(near(c, LOOK_LINEN) for _, c, _ in i)
               and not any(near(c, LOOK_TABLE) for _, c, _ in i) for i in ins_s),
       str([[c for _, c, _ in i] for i in ins_s])[:160])
    ck("  and the product's photographs still come, because they are not a look",
       got_s["board"]["drawn"] is True and got_s["board"]["product"] == 2
       and all(near(i[0][1], PRODUCT_SIDE) or near(i[0][1], PRODUCT_FRONT) for i in ins_s))
    sent.clear()
    got_u = creative.batch("baci", commitment=cup, entity_key="zodiac-cup",
                           fmt="ad_frame", positioning="the sign you were born under",
                           plates=1, review=False, boards=["nowhere"])
    ck("a board that does not exist is SAID, and nothing is pulled from it",
       got_u["board"]["unknown"] == ["nowhere"] and got_u["board"]["look"] == 0
       and "no board named nowhere" in got_u["note"], got_u["note"][-160:])

    print("\n— THE OTHER SYSTEMS: the same boards through the same seam —")
    sent.clear()
    creative.assess = lambda blob, brief, tenant="": {
        "ok": True, "verdicts": [], "overall": "reads right", "failed": [], "fix": ""}
    art = creative.generate("baci", commitment=cup, fmt="article_hero",
                            entity_key="zodiac-cup", prominent="The cup for your sign",
                            boards=["lifestyle"])
    ins_a = _inputs(sent[0]) if sent else []
    ck("the article hero is drawn from the boards too, and honours the selection",
       art["ok"] and sent and sent[0]["path"] == "/images/edits"
       and any(near(c, LOOK_TABLE) for _, c, _ in ins_a)
       and not any(near(c, LOOK_LINEN) for _, c, _ in ins_a)
       and (near(ins_a[0][1], PRODUCT_FRONT) or near(ins_a[0][1], PRODUCT_SIDE))
       if ins_a else False,
       f"ok={art.get('ok')} err={art.get('error')} basis={str(art.get('basis'))[:60]} "
       + str([(c["path"], len(c["files"] or [])) for c in sent]))
    ck("  it records what it was drawn from, and says so",
       art["board"]["drawn"] is True and art["board"]["boards"] == ["lifestyle"]
       and "drawn from the brand" in art["basis"]
       and set(next(a.derived_from for a in kb.assets("baci", publishable_only=False)
                    if a.id == art["asset_id"])) == set(art["board"]["pins"]))
    pk = creative.pick("baci", commitment=cup, entity_key="zodiac-cup", fmt="email_hero")
    ck("pick offers the pinned product shot as the hero, above the newest photograph",
       pk["rung"] == "pinned_product" and pk["asset_id"] == front, pk["rung"])
    pk2 = creative.pick("baci", commitment=cup, entity_key="zodiac-cup", fmt="email_hero",
                        boards=["studio"])
    ck("  …only from the boards the run names",
       pk2["rung"] == "photograph", pk2["rung"])
    kb.add_entity("baci", "product", "aqua-jug", "Aqua Jug", description="a jug",
                  origin="human")
    jug = coherence.commit("entity", "aqua-jug", label="Aqua Jug")
    pk3 = creative.pick("baci", commitment=jug, entity_key="aqua-jug", fmt="email_hero")
    ck("  a product with no photograph gets the pinned look, not a random shelf shot",
       pk3["rung"] == "pinned_look" and pk3["asset_id"] in (table, linen), pk3["rung"])
    hero = creative.hero_for_campaign("baci", entity_keys=["zodiac-cup"])
    ck("the campaign email hero prefers the board",
       hero.get("basis") == "approved_asset" and hero.get("asset_id") == front,
       str(hero)[:160])
    ck("  and a reference pin is never a hero",
       ref not in (pk["asset_id"], pk2["asset_id"], pk3["asset_id"], hero.get("asset_id")))

    print("\n— THE SWITCH: nothing pinned, nothing changes —")
    kb.add_entity("eien", "product", "omega-3", "Omega-3 softgel",
                  description="fish oil", origin="human")
    kb.add_asset("eien", "https://cdn.example/omega-bottle.png", rights=kb.OWNED,
                 title="Omega-3 softgel", subject=kb.OBJECT,
                 entity_key="omega-3", origin="human")
    sent.clear()
    omega = coherence.commit("entity", "omega-3", label="Omega-3 softgel")
    got2 = creative.batch("eien", commitment=omega, entity_key="omega-3",
                          fmt="ad_frame", positioning="testing beats price",
                          plates=1, review=False)
    ck("an account with nothing pinned gets the route it had — its photographs are not sent",
       got2["ok"] and sent and all(c["path"] == "/images/generations"
                                    and not c["files"] for c in sent)
       and {k: got2["board"][k] for k in ("on", "drawn", "product", "look", "pins",
                                            "excluded")}
       == {"on": False, "drawn": False, "product": 0, "look": 0, "pins": [],
           "excluded": []},
       str([(c["path"], bool(c["files"])) for c in sent]))
    kb.add_asset("eien", "https://cdn.example/omega-kitchen.png", rights=kb.OWNED,
                 title="Kitchen, morning", subject=kb.SCENE, origin="human")
    kb.add_board("eien", "Lifestyle")
    kb.set_board_role(_id("eien", "https://cdn.example/omega-kitchen.png"),
                      "lifestyle", "look", True)
    sent.clear()
    got3 = creative.batch("eien", commitment=omega, entity_key="omega-3",
                          fmt="ad_frame", positioning="testing beats price",
                          plates=1, review=False)
    # THE OWNER'S EXPECTATION, MADE COMPUTABLE: *"we have photos of this
    # product"* — with the board on, they are used without pinning each one.
    ck("with the board on, the product's own photographs are used without being pinned",
       got3["ok"] and sent and sent[0]["path"] == "/images/edits"
       and len(sent[0]["files"]) == 2 and got3["board"]["drawn"] is True
       and got3["board"] ["product"] == 1 and got3["board"]["look"] == 1,
       str([(c["path"], len(c["files"] or [])) for c in sent]))
    sent.clear()
    knee = coherence.commit("situation", "knee-pain",
                            label="knee pain that flares after sitting")
    got4 = creative.batch("eien", commitment=knee, fmt="ad_frame",
                          positioning="testing beats price", plates=1, review=False)
    ck("a set about no product in particular carries none — the look styles it, the old rule holds",
       got4["ok"] and sent and sent[0]["path"] == "/images/edits"
       and len(sent[0]["files"]) == 1
       and imagegen._NO_INVENTED_PRODUCT in sent[0]["data"]["prompt"]
       and "THE LOOK" in sent[0]["data"]["prompt"]
       and got4["board"]["drawn"] is False and got4["board"]["product"] == 0,
       str([(c["path"], len(c["files"] or [])) for c in sent]))

    print("\n— THE CONSOLE: the board is a section of the Pictures room —")
    page = ui.render_content(KEY, tenant="baci", sub="pictures")
    ck("the boards render where the pictures are reviewed, each by name",
       "Visual boards" in page and 'id="board"' in page
       and all(f'id="board-{b}"' in page for b in ("studio", "lifestyle", "zodiac-collection"))
       and "on white, hard shadow" in page)
    ck("  each pin says what its rights let it do",
       "sent to the model as pixels" in page and "words only, never sent" in page)
    ck("  and the library offers the three actions against a chosen board",
       all(f'value="{v}"' in page for v in ("pin_look", "pin_product", "unpin"))
       and '<select name="board" form="boardform">' in page)
    ck("  the set's card says what it was drawn from",
       "drawn from 4 of the brand" in page)
    ck("the form that starts a run offers the boards to draw from",
       'name="boards" multiple' in ui.boards_select("baci")
       and "Zodiac collection" in ui.boards_select("baci")
       and ui.boards_select("coverings") == "")
    r = client.post("/admin/board_add", params={"key": KEY},
                    data={"tenant": "baci", "name": "Gift guide", "note": "boxed, ribboned"})
    ck("a board is created from the console",
       r.status_code == 200 and "gift-guide" in kb.boards("baci"))
    r = client.post("/admin/board_pin", params={"key": KEY},
                    data={"tenant": "baci", "action": "unpin", "board": "studio",
                          "asset_ids": [linen]})
    ck("unpinning from the console takes the picture off that board",
       r.status_code == 200 and linen not in {x.id for x in kb.board("baci")["look"]})
    r = client.post("/admin/board_pin", params={"key": KEY},
                    data={"tenant": "baci", "action": "pin_product", "board": "lifestyle",
                          "asset_ids": [ref]}, follow_redirects=False)
    ck("  a refusal reaches the page, not the log",
       r.status_code in (302, 303)
       and "reference" in unquote(r.headers.get("location", "")).lower()
       and ref not in {x.id for x in kb.board("baci")["product"]},
       r.headers.get("location", "")[:160])
    r = client.post("/admin/board_pin", params={"key": KEY},
                    data={"tenant": "baci", "action": "pin_look", "board": "nowhere",
                          "asset_ids": [linen]}, follow_redirects=False)
    ck("  pinning to a board that does not exist is refused where it can be read",
       "no board named" in unquote(r.headers.get("location", "")).lower())
    r = client.post("/admin/asset_add", params={"key": KEY},
                    data={"tenant": "baci", "url": "https://cdn.example/new-look.png",
                          "title": "Sideboard, dusk", "rights": "owned",
                          "subject": "scene", "board": "gift-guide:look"},
                    follow_redirects=False)
    ck("a picture added by URL can land straight on a board",
       r.status_code in (302, 303)
       and "https://cdn.example/new-look.png" in
       {x.url for x in kb.board("baci", ["gift-guide"])["look"]})
    r = client.post("/admin/board_remove", params={"key": KEY},
                    data={"tenant": "baci", "board": "gift-guide"})
    ck("removing a board takes its pins with it, and says so",
       r.status_code == 200 and "gift-guide" not in kb.boards("baci")
       and not kb.pinned(next(a for a in kb.assets("baci")
                              if a.url == "https://cdn.example/new-look.png")))
    ck("  no boards is said as a state, before any instruction",
       "no boards" in ui.render_content(KEY, tenant="coverings", sub="pictures"))

    print()
    if _fail:
        print(f"{len(_fail)} FAILED:\n  " + "\n  ".join(_fail))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
