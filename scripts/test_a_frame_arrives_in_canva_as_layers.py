"""A frame reaches Canva as LAYERS — photo, mark, headline, CTA — through the
connection that already works, one design per Meta placement, and the
approved pictures come back at Meta's recommended sizes as our own bytes.

Owner, 2026-09-07: *"the text and components are not separate layers on
Canva they are burned on — is there a way to layer them so we can adjust as
needed? Also, How do we ensure that final approved assets get created in the
different ratios needed for the meta placements?"* And, when a second sign-in
appeared: *"canva was working before, why are we adjusting the way we
connect?"*

THE CONTRACT, read from Canva's published docs on 2026-09-07 (the owner's
standing rule: fix a provider call from its docs, and keep the URLs here):
  imports   https://www.canva.dev/docs/connect/api-reference/design-imports/create-design-import-job/
            POST /v1/imports, body = the file, Content-Type application/octet-stream,
            Import-Metadata {"title_base64" (≤ 50 chars unencoded), "mime_type"};
            job → GET /v1/imports/{jobId} → success {result.designs[]} | failed {error.message}
  types     https://www.canva.dev/docs/connect/api-reference/design-imports/
            PowerPoint (.pptx) is an accepted type — each object arrives as its own element
  exports   https://www.canva.dev/docs/connect/api-reference/exports/create-design-export-job/
            format {type: png, width?, height?} 40–25000 px, aspect kept
  results   https://www.canva.dev/docs/connect/api-reference/exports/get-design-export-job/
            "These URLs expire after 24 hours" — so the bytes are kept, not the link
  editor    https://mcp.canva.com/.well-known/oauth-protected-resource/mcp names ONLY
            mcp.canva.com as the issuer of tokens it accepts — the editor's own tools
            would need a second sign-in, which is why this ship does not use them
  Meta      https://www.facebook.com/business/ads-guide/update/image
            Feed 4:5 1440×1800; Reels/Stories 9:16 1440×2560, safe 14% top / 35% bottom / 6% sides

Run: python3 scripts/test_a_frame_arrives_in_canva_as_layers.py
"""
from __future__ import annotations

import base64
import io
import json
import os
import sys
import tempfile
from types import SimpleNamespace

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'layers.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["PUBLIC_BASE_URL"] = "https://example.test"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image  # noqa: E402

from app import (admin_ui as ui, canva, compose, credentials as cred, db,  # noqa: E402
                 hosting, kb, kb_seed, layers, media, oauth, tenants, web)

KEY = "s3cret"
_fail: list[str] = []


def ck(label: str, cond, detail: str = "") -> None:
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def png(colour, w: int = 1024, h: int = 1024) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), colour).save(buf, format="PNG")
    return buf.getvalue()


def busy_png(w: int = 1024, h: int = 1024) -> bytes:
    im = Image.new("RGB", (w, h), (255, 255, 255))
    px = im.load()
    for y in range(h):
        for x in range(0, w, 1):
            if ((x // 6) + (y // 6)) % 2 == 0:
                px[x, y] = (10, 10, 10)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


THEME = {"logo_url": "https://cdn.example/baci-mark.png",
         "colors": {"accent": "#b5473b", "accent_text": "#ffffff", "text": "#1c1e22"},
         "font": {"heading": "'Playfair Display', Georgia, serif",
                  "body": "-apple-system, Inter, Helvetica, sans-serif"}}
LOGO = png((255, 255, 255), 400, 120)
HEADLINE = "The sign you were born under"
COPY = ("Born in July? Then the crab is yours.\n"
        "The Cancer cup, in white porcelain with a gold glyph.\n\n"
        "Shop the Zodiac cups →")


def _seed(tenant: str, secret: str, by: str) -> None:
    with db.SessionLocal() as s:
        s.add(db.Credential(tenant=tenant, provider="canva", kind="oauth",
                            secret=cred._encrypt(secret), meta={},
                            status="active", granted_by=by))
        s.commit()


def _frame(url: str, title: str, tags=("output:out-1",), batch: str = "b1") -> str:
    kb.add_asset("baci", url, rights=kb.OWNED, title=title, kind="image",
                 subject=kb.OBJECT, entity_key="zodiac-cup", origin="generated",
                 batch=batch, tags=list(tags))
    return next(a.id for a in kb.assets("baci", publishable_only=False) if a.url == url)


def _row(aid: str):
    return next(a for a in kb.assets("baci", publishable_only=False) if a.id == aid)


def _in(box: dict, x0: int, y0: int, x1: int, y1: int) -> bool:
    return (box["x"] >= x0 - 1 and box["y"] >= y0 - 1
            and box["x"] + box["w"] <= x1 + 1 and box["y"] + box["h"] <= y1 + 1)


def main() -> int:
    db.init_db()
    tenants.seed()
    kb_seed.seed_all()
    kb.add_entity("baci", "product", "zodiac-cup", "Zodiac Cup",
                  description="a porcelain cup with a zodiac sign", origin="human")
    _seed("baci", "baci-refresh", "client")
    oauth.access_token = lambda provider, refresh: {"ok": True, "token": "baci-access"}
    with db.SessionLocal() as s:
        b = s.get(db.KbBrand, "baci")
        b.theme = dict(THEME)
        s.add(db.ArtifactBody(
            tenant="baci", output_id="out-1", run_id="", system_key="ad_creative",
            format="ad_batch", destination="", meta={},
            body=json.dumps({"variants": [{"n": 1, "output_id": "out-1",
                                           "headline": HEADLINE, "text": COPY,
                                           "dropped": False}]}),
            draft_body="", bytes=10))
        s.commit()
    hosting._logo = lambda theme: LOGO

    # ---- the deck, on its own ------------------------------------------
    print("— A DECK IS LAYERS, LAID OUT FOR THE RATIO —")
    dark = png((30, 40, 60))
    d = layers.deck(dark, size=compose.SIZES["9:16"], headline=HEADLINE,
                    ask="Shop the Zodiac cups", theme=THEME, logo=LOGO,
                    safe=compose.META_PLACEMENTS["9:16"]["safe"], title="t")
    r = layers.read_layers(d["pptx"])
    names = [L["name"] for L in r["layers"]]
    ck("the deck is a PowerPoint package with one slide at the placement's size",
       {"[Content_Types].xml", "ppt/presentation.xml", "ppt/slides/slide1.xml",
        "ppt/theme/theme1.xml"} <= set(r["parts"]) and r["size"] == (1080, 1920), str(r["size"]))
    ck("  photo, mark, headline and CTA are SEPARATE objects on it",
       names == ["Photo", "Logo", "Headline", "CTA"], str(names))
    by = {L["name"]: L for L in r["layers"]}
    ck("  the photo fills the frame, cover-cropped rather than stretched",
       by["Photo"]["box"] == {"x": 0, "y": 0, "w": 1080, "h": 1920} and by["Photo"]["cropped"],
       str(by["Photo"]))
    W, H = 1080, 1920
    safe_box = (int(W * 0.06), int(H * 0.14), W - int(W * 0.06), H - int(H * 0.35))
    ck("  on 9:16 the mark, headline and CTA sit inside Meta's safe zone "
       "(top 14%, bottom 35%, sides 6%)",
       all(_in(by[n]["box"], *safe_box) for n in ("Logo", "Headline", "CTA")),
       str({n: by[n]["box"] for n in ("Logo", "Headline", "CTA")}))
    ck("  the headline is the ad's words, in the brand's heading face",
       by["Headline"]["text"] == HEADLINE and by["Headline"]["font"] == "Playfair Display",
       f"{by['Headline']['text']!r} {by['Headline']['font']!r}")
    ck("  the CTA is a pill in the brand's accent with the ask on it, in the body face",
       by["CTA"]["geometry"] == "roundRect" and by["CTA"]["fill"] == "B5473B"
       and by["CTA"]["text"] == "Shop the Zodiac cups" and by["CTA"]["font"] == "Inter",
       str(by["CTA"]))
    ck("  white type on a dark picture", by["Headline"]["colour"] == "FFFFFF")
    light = layers.deck(png((240, 236, 230)), size=compose.SIZES["1:1"], headline=HEADLINE,
                        ask="Shop", theme=THEME, logo=LOGO)
    lb = {L["name"]: L for L in layers.read_layers(light["pptx"])["layers"]}
    ck("  the brand's text colour on a pale one — measured under the type, not chosen",
       lb["Headline"]["colour"] == "1C1E22" and "Scrim" not in lb, str(lb["Headline"]["colour"]))
    busy = layers.deck(busy_png(), size=compose.SIZES["4:5"], headline=HEADLINE, ask="Shop",
                       theme=THEME, logo=LOGO)
    bb = [L["name"] for L in layers.read_layers(busy["pptx"])["layers"]]
    ck("  and a busy picture gets a scrim layer behind the type, which the designer may delete",
       "Scrim" in bb and bb.index("Scrim") < bb.index("Headline"), str(bb))
    sq = layers.read_layers(light["pptx"])["layers"][0]
    ck("  a square picture into a square frame is not cropped at all", not sq["cropped"])
    none = layers.deck(dark, size=compose.SIZES["1:1"], theme=THEME)
    nb = {L["name"]: L for L in layers.read_layers(none["pptx"])["layers"]}
    ck("  with no copy and no mark the CTA still exists, saying the default ask, and says what it skipped",
       nb["CTA"]["text"] == layers.DEFAULT_ASK and "Headline" not in nb
       and set(none["skipped"]) == {"Logo", "Headline"}, str(none["skipped"]))
    ck("  the ask is the ad's last short line, arrows and hashtags dropped",
       layers.ask_line(COPY) == "Shop the Zodiac cups"
       and layers.ask_line("Shop the cups →\n#zodiac #cups") == "Shop the cups"
       and layers.ask_line("A long closing sentence that is not an ask at all here.") == "",
       layers.ask_line(COPY))
    ck("  and the frame's headline rule is the one rule (web delegates to layers)",
       web._first_line("# The sign\nmore") == layers.first_line("# The sign\nmore") == "The sign")

    # ---- the documented import call ------------------------------------
    print("\n— THE IMPORT IS THE DOCUMENTED CALL —")
    import httpx
    seen: dict = {}
    real_post = httpx.post

    def _post(url, **kw):
        seen.update({"url": url, **kw})
        return SimpleNamespace(status_code=200, text="",
                               json=lambda: {"job": {"id": "job-x", "status": "in_progress"}})
    httpx.post = _post
    try:
        res = canva._call_import("baci", b"PK-bytes", "Zodiac · identity · 1:1", canva.PPTX_MIME)
    finally:
        httpx.post = real_post
    meta = {}
    try:
        meta = json.loads(seen.get("headers", {}).get("Import-Metadata", "{}"))
    except Exception:                                            # noqa: BLE001
        pass
    ck("POST /v1/imports with the bytes as the body and Content-Type application/octet-stream",
       res.get("ok") and seen.get("url", "").endswith("/v1/imports")
       and seen.get("content") == b"PK-bytes"
       and seen.get("headers", {}).get("Content-Type") == "application/octet-stream",
       str(seen.get("url")))
    ck("  Import-Metadata carries the title base64'd and the PowerPoint MIME type",
       base64.b64decode(meta.get("title_base64", "")).decode() == "Zodiac · identity · 1:1"
       and meta.get("mime_type") == canva.PPTX_MIME, str(meta))
    long = "x" * 80
    httpx.post = _post
    try:
        canva._call_import("baci", b"1", long, canva.PPTX_MIME)
    finally:
        httpx.post = real_post
    meta2 = json.loads(seen["headers"]["Import-Metadata"])
    ck("  and the title is cut to Canva's 50 characters, unencoded",
       len(base64.b64decode(meta2["title_base64"])) == 50)

    # ---- the fake Canva -------------------------------------------------
    calls: list = []
    imports: list = []
    n = {"folder": 0, "job": 0, "export": 0}
    FAIL_TITLES: set = set()

    def _call(tenant, method, path, *, payload=None, params=None):
        calls.append((method, path, payload))
        if path == "/folders" and method == "POST":
            n["folder"] += 1
            return {"ok": True, "data": {"folder": {"id": f"folder-{n['folder']}"}}}
        if path == "/folders/move":
            return {"ok": True, "data": {}}
        if path.startswith("/imports/"):
            job = path.rsplit("/", 1)[-1]
            title = next((i["title"] for i in imports if i["job"] == job), "")
            if title in FAIL_TITLES:
                return {"ok": True, "data": {"job": {"id": job, "status": "failed",
                                                     "error": {"code": "invalid_file",
                                                               "message": "Document could not be imported"}}}}
            did = "DES" + job.split("-")[-1]
            return {"ok": True, "data": {"job": {"id": job, "status": "success", "result": {
                "designs": [{"id": did, "title": title,
                             "urls": {"edit_url": f"https://www.canva.com/api/design/{did}/edit",
                                      "view_url": f"https://www.canva.com/api/design/{did}/view"},
                             "thumbnail": {"url": f"https://thumb/{did}.png"}}]}}}}
        if path == "/exports" and method == "POST":
            n["export"] += 1
            return {"ok": True, "data": {"job": {"id": f"exp-{n['export']}", "status": "in_progress"}}}
        if path.startswith("/exports/"):
            job = path.rsplit("/", 1)[-1]
            return {"ok": True, "data": {"job": {"id": job, "status": "success",
                                                 "urls": [f"https://export-download.canva.com/{job}.png"]}}}
        return {"ok": False, "error": f"unexpected {method} {path}"}

    def _import(tenant, blob, title, mime):
        n["job"] += 1
        imports.append({"tenant": tenant, "blob": blob, "title": title, "mime": mime,
                        "job": f"job-{n['job']}"})
        return {"ok": True, "data": {"job": {"id": f"job-{n['job']}", "status": "in_progress"}}}

    downloaded: list = []

    def _download(url):
        downloaded.append(url)
        # distinct bytes per export, so three placements cannot collapse into one blob
        return png((len(downloaded) * 40 % 255, 90, 90), 200, 250), "image/png"

    canva.call, canva.call_import, canva.download = _call, _import, _download
    canva.IMPORT_POLL_S, canva.HARVEST_POLL_S = 0, 0

    # ---- a frame goes as layers -----------------------------------------
    print("\n— A FRAME GOES TO CANVA AS LAYERS, ONE DESIGN PER PLACEMENT —")
    url1 = media.put("baci", dark, mime="image/png", origin="generated")["url"]
    aid = _frame(url1, "Zodiac · identity")
    got = hosting.to_canva("baci", aid)
    ck("the frame is imported as a deck and the design recorded on the frame",
       got.get("ok") and not got.get("reused") and got.get("design_id") == "DES1"
       and _row(aid).canva_design_id == "DES1"
       and (_row(aid).canva_designs or {}).get("1:1") == "DES1", str(got)[:200])
    ck("  its edit URL is Canva's, from the import result",
       got.get("edit_url", "").startswith("https://www.canva.com/api/design/DES1"), got.get("edit_url", ""))
    sent = layers.read_layers(imports[-1]["blob"])
    sb = {L["name"]: L for L in sent["layers"]}
    ck("  the deck carries the AD'S OWN headline and ask, read from the batch record",
       sb.get("Headline", {}).get("text") == HEADLINE
       and sb.get("CTA", {}).get("text") == "Shop the Zodiac cups", str({k: v['text'] for k, v in sb.items()}))
    ck("  the brand's mark is a layer of its own", "Logo" in sb and sb["Logo"]["kind"] == "picture")
    ck("  the mime is PowerPoint's and the title names the ratio",
       imports[-1]["mime"] == canva.PPTX_MIME and imports[-1]["title"].endswith("· 1:1")
       and len(imports[-1]["title"]) <= canva.UPLOAD_NAME_MAX, imports[-1]["title"])
    ck("  no flat picture was uploaded and no custom design created — the import is the design",
       not any(p in ("/designs", "/asset-uploads") for _, p, _ in calls), str([p for _, p, _ in calls]))
    ck("  and it is filed in the account's folder",
       any(p == "/folders/move" and (pl or {}).get("item_id") == "DES1" for _, p, pl in calls))
    ck("  the note says which layers there are",
       "Headline" in got.get("note", "") and "CTA" in got.get("note", "")
       and "layers" in got.get("note", ""), got.get("note", "")[:120])
    again = hosting.to_canva("baci", aid)
    ck("a second ask for the same placement reuses the design rather than importing twice",
       again.get("reused") is True and again.get("design_id") == "DES1" and len(imports) == 1)
    tall = hosting.to_canva("baci", aid, "9:16")
    tb = layers.read_layers(imports[-1]["blob"])
    tbb = {L["name"]: L for L in tb["layers"]}
    ck("the 9:16 is its own design, laid out inside Meta's safe zone, recorded beside the 1:1",
       tall.get("ok") and tall.get("design_id") == "DES2" and tb["size"] == (1080, 1920)
       and all(_in(tbb[k]["box"], *safe_box) for k in ("Logo", "Headline", "CTA"))
       and (_row(aid).canva_designs or {}).get("9:16") == "DES2"
       and _row(aid).canva_design_id == "DES1", str(_row(aid).canva_designs))
    ck("  an unknown placement is refused by name",
       not hosting.to_canva("baci", aid, "3:4").get("ok"))
    ck("  the console's stage reads the frame as editable",
       hosting.stage(_row(aid)) == "editable")

    print("\n— APPROVAL MAKES EVERY PLACEMENT, OFF THE REQUEST, WHERE A CANVA IS CONNECTED —")
    url2 = media.put("baci", png((20, 60, 30)), mime="image/png", origin="generated")["url"]
    aid2 = _frame(url2, "Zodiac · after")
    made = hosting.layer_placements("baci", aid2)
    ck("layer_placements makes the 1:1, 4:5 and 9:16 as three layered designs",
       made.get("ok") and set(made.get("designs") or {}) == {"1:1", "4:5", "9:16"}
       and not made.get("errors"), str(made)[:200])
    url3 = media.put("baci", png((60, 20, 30)), mime="image/png", origin="generated")["url"]
    aid3 = _frame(url3, "Zodiac · during")
    FAIL_TITLES.add("Zodiac · during · 4:5")
    part = hosting.layer_placements("baci", aid3)
    ck("  a placement Canva refuses is named with Canva's reason; the others are still made",
       set(part.get("designs") or {}) == {"1:1", "9:16"}
       and "could not be imported" in (part.get("errors") or {}).get("4:5", ""), str(part)[:220])
    FAIL_TITLES.clear()

    scheduled: list = []
    real_bg = web._run_bg
    web._run_bg = lambda label, fn, *a, **kw: scheduled.append((label, fn, a))
    from fastapi.testclient import TestClient
    url4 = media.put("baci", png((10, 10, 80)), mime="image/png", origin="generated")["url"]
    aid4 = _frame(url4, "Zodiac · before")
    try:
        with TestClient(web.app) as cl:
            cl.post("/admin/assets_decide?key=s3cret",
                    data={"tenant": "baci", "action": "approve", "asset_ids": [aid4]},
                    follow_redirects=False)
        lay = [s_ for s_ in scheduled if s_[0] == "layers"]
        ck("approving a frame schedules its layered placements in the background",
           len(lay) == 1 and lay[0][1] is hosting.layer_kept and lay[0][2] == ("baci", [aid4]),
           str([(s_[0], s_[2]) for s_ in scheduled]))
        ck("  and the flat crops are still cut, so the frame has placements even before Canva answers",
           set((_row(aid4).placements or {}).keys()) >= {"4:5", "9:16"})
        scheduled.clear()
        real_acct = canva.which_account
        canva.which_account = lambda t: {"source": "", "note": ""}
        url5 = media.put("baci", png((80, 10, 10)), mime="image/png", origin="generated")["url"]
        aid5 = _frame(url5, "Zodiac · plain")
        try:
            with TestClient(web.app) as cl:
                cl.post("/admin/assets_decide?key=s3cret",
                        data={"tenant": "baci", "action": "approve", "asset_ids": [aid5]},
                        follow_redirects=False)
        finally:
            canva.which_account = real_acct
        ck("  with no Canva connected nothing is scheduled — the account is not told three times per frame",
           not any(s_[0] == "layers" for s_ in scheduled), str([s_[0] for s_ in scheduled]))
    finally:
        web._run_bg = real_bg
    kept = hosting.layer_kept("baci", [aid4])
    ck("  layer_kept reports per frame", kept.get("made") == 3 and kept.get("frames") == 1, str(kept))

    print("\n— THE APPROVED PICTURES COME BACK AT META'S SIZES, AS OUR OWN BYTES —")
    before = _row(aid2).url
    calls.clear()
    back = canva.harvest("baci", asset_id=aid2)
    exports = [pl for m, p, pl in calls if p == "/exports" and m == "POST"]
    sizes = {(pl.get("format") or {}).get("width"): (pl.get("format") or {}).get("height") for pl in exports}
    ck("harvest exports the three designs: the 1:1 at its own size, Feed 4:5 at 1440×1800, Reels 9:16 at 1440×2560",
       back.get("ok") and back.get("filed") == 3 and len(exports) == 3
       and sizes.get(None) is None and sizes.get(1440) in (1800, 2560)
       and {(f.get("width"), f.get("height")) for f in (pl["format"] for pl in exports)}
       == {(None, None), (1440, 1800), (1440, 2560)}, str(sizes))
    row2 = _row(aid2)
    ck("  the frame's picture and placements now point at OUR store, not Canva's 24-hour link",
       row2.url != before and "/media/" in row2.url
       and all("/media/" in str(row2.placements.get(f, "")) for f in ("4:5", "9:16"))
       and len({row2.url, row2.placements.get("4:5"), row2.placements.get("9:16")}) == 3
       and len(downloaded) == 3 and all("export-download.canva.com" in u for u in downloaded),
       f"{row2.url} {row2.placements}")
    ck("  and the frame says it was edited in Canva, once",
       str(row2.source).count("edited in Canva") == 1, str(row2.source))
    canva.harvest("baci", asset_id=aid2)
    ck("  bringing it back again does not stack the note",
       str(_row(aid2).source).count("edited in Canva") == 1)
    ck("  naming one placement's design brings back that frame",
       canva.harvest("baci", design_id=(_row(aid).canva_designs or {}).get("9:16", "")).get("filed", 0) >= 1)
    ck("  an export outside Canva's 40–25000 px is refused before the call",
       not canva.export("baci", "DES1", "png", width=30_000).get("ok"))

    print("\n— THE KEPT-FRAMES CARD AND THE EXPORT SAY WHERE THE LAYERS ARE —")
    kb.review_asset(aid2, approve=True, rights="owned")
    kb.review_asset(aid, approve=True, rights="owned")
    page = ui.render_content(KEY, tenant="baci", sub="pictures")
    ck("a kept frame's ratios link to their layered designs in Canva",
       "Kept frames" in page and page.count("layers in Canva") >= 3
       and "https://www.canva.com/design/DES2/edit" in page, "")
    ck("  a ratio not made yet offers a button that makes it, naming the ratio",
       'name="fmt" value="4:5"' in page and "layer in Canva" in page, "")
    ck("  and a frame with designs offers to bring them back",
       "asset_harvest" in page and "bring back from Canva" in page, "")
    ck("  the card says Meta's sizes and safe zones",
       "1440&times;1800" in page and "1440&times;2560" in page and "35%" in page, "")
    lines = web._variant_frames("baci", "out-1")
    ck("  the ad export lists each placement's layered design",
       sum(1 for ln in lines if "layers in Canva: https://www.canva.com/design/" in ln) >= 3,
       "\n".join(lines)[:400])

    print("\n— THE ROUTES —")
    with TestClient(web.app) as cl:
        r1 = cl.post("/admin/asset_canva?key=s3cret",
                     data={"tenant": "baci", "asset_id": aid, "fmt": "4:5"},
                     follow_redirects=False)
        r2 = cl.post("/admin/asset_harvest?key=s3cret",
                     data={"tenant": "baci", "asset_id": aid}, follow_redirects=False)
    ck("the edit route takes a ratio and opens that design",
       r1.status_code == 303 and "canva.com" in r1.headers.get("location", "")
       and (_row(aid).canva_designs or {}).get("4:5", "").startswith("DES"),
       f"{r1.status_code} {r1.headers.get('location', '')}")
    ck("  the bring-back route returns to the kept frames with what happened",
       r2.status_code == 303 and "kept" in r2.headers.get("location", "")
       and "back+from+Canva" in r2.headers.get("location", "").replace("%20", "+"),
       f"{r2.status_code} {r2.headers.get('location', '')[:160]}")

    print()
    if _fail:
        print(f"{len(_fail)} FAILED:\n  " + "\n  ".join(_fail))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
