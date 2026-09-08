"""A second image provider is a call away: a `gemini:` model takes the same
words and the same pictures, in the same order, through Google's image API —
so the bake-off compares providers on identical requests.

Owner, 2026-09-08: *"These days, there must be a way to create this without
hallucinations."* Exact reproduction of a specific object is a provider
capability; `scripts/bakeoff.py` could only compare models on one endpoint
and said a different provider "needs an adapter first". This is it.

THE CONTRACT (Google's docs, read 2026-09-08 —
https://ai.google.dev/gemini-api/docs/image-generation):
  POST https://generativelanguage.googleapis.com/v1beta/interactions
  header x-goog-api-key; body {"model", "input": [{"type":"text","text"},
  {"type":"image","mime_type","data":<base64>}…], "response_format":
  {"type":"image","aspect_ratio","image_size"}}; the reply's
  last image block is the picture. Reference limits: gemini-3-pro-image 6
  objects + 3 style, gemini-3.1-flash-image 10 objects, flash-lite 14, no
  style references on the lite and legacy models.

Run: python3 scripts/test_a_second_image_provider_is_a_call_away.py
"""
from __future__ import annotations

import base64
import io
import os
import sys
import tempfile
from types import SimpleNamespace

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'gem.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["PUBLIC_BASE_URL"] = "https://example.test"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image  # noqa: E402

from app import (coherence, config, creative, db, gemini_images, imagegen, kb,  # noqa: E402
                 kb_seed, tenants, toolcalls)

_fail: list[str] = []


def ck(label: str, cond, detail: str = "") -> None:
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def png(colour, w: int = 64, h: int = 64) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (w, h), colour).save(buf, format="PNG")
    return buf.getvalue()


MADE = png((10, 200, 30, 255))
B64 = base64.b64encode(MADE).decode()


def main() -> int:
    db.init_db()
    tenants.seed()
    kb_seed.seed_all()
    config.GEMINI_API_KEY = "gk-test"
    calls: list = []
    openai_calls: list = []
    reply = {"mode": "ok"}

    def _post(url, *, headers, json_body):
        calls.append({"url": url, "headers": headers, "json": json_body})
        if reply["mode"] == "429":
            return SimpleNamespace(status_code=429, text="", json=lambda: {
                "error": {"code": 429, "message": "Resource has been exhausted", "status": "RESOURCE_EXHAUSTED"}})
        if reply["mode"] == "nested":
            return SimpleNamespace(status_code=200, text="", json=lambda: {
                "id": "int-1", "steps": [{"type": "model_call", "content": [
                    {"type": "text", "text": "Here you go"},
                    {"type": "image", "mime_type": "image/png", "data": B64}]}]})
        if reply["mode"] == "legacy":
            return SimpleNamespace(status_code=200, text="", json=lambda: {
                "candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "image/png", "data": B64}}]}}]})
        if reply["mode"] == "empty":
            return SimpleNamespace(status_code=200, text="", json=lambda: {"id": "int-2", "outputs": [{"type": "text", "text": "no"}]})
        return SimpleNamespace(status_code=200, text="", json=lambda: {
            "id": "int-0", "model": json_body["model"],
            "outputs": [{"type": "text", "text": "a table"}, {"type": "image", "mime_type": "image/png", "data": B64}]})
    gemini_images.post = _post
    imagegen.post = lambda path, **kw: (openai_calls.append(path) or {"ok": True, "images": [png((1, 1, 1, 255))]})

    print("— THE SAME WORDS AND PICTURES, THROUGH GOOGLE'S DOOR —")
    prod, cast, look = png((200, 30, 30, 255)), png((30, 30, 200, 255)), png((30, 200, 200, 255))
    got = imagegen.with_references("a laid table at dusk", product=[prod], look=[look], cast=[cast],
                                   cast_names=["Faceted Bowl"], shape="portrait", n=2,
                                   model="gemini:gemini-3-pro-image", checklist=["a gold rim"])
    ck("a gemini: model makes one call per picture asked for, and nothing goes to the other door",
       got.get("ok") and len(got.get("images") or []) == 2 and len(calls) == 2 and not openai_calls,
       f"calls={len(calls)} openai={len(openai_calls)} err={got.get('error', '')}")
    c = calls[0]
    ck("  to the documented endpoint, with the key in the documented header",
       c["url"].endswith("/v1beta/interactions") and c["headers"].get("x-goog-api-key") == "gk-test", c["url"])
    body = c["json"]
    blocks = body.get("input") or []
    ck("  the model is named without the prefix and the words go first — the exact-product rule, the checklist, the cast rule, the look rule",
       body.get("model") == "gemini-3-pro-image" and blocks and blocks[0]["type"] == "text"
       and "reproduced EXACTLY" in blocks[0]["text"] and "a gold rim" in blocks[0]["text"]
       and "DESIGN AND PATTERN REFERENCE" in blocks[0]["text"] and "THE LOOK" in blocks[0]["text"], str(body)[:200])
    imgs = [b for b in blocks if b["type"] == "image"]
    ck("  the pictures follow in the same order as the other door — product, cast, look — as base64 with their MIME",
       [base64.b64decode(b["data"]) for b in imgs] == [prod, cast, look]
       and all(b["mime_type"] == "image/png" for b in imgs), f"{len(imgs)} images")
    ck("  the shape becomes the documented aspect ratio and size",
       # NO `mime_type` SINCE 2026-09-08: the first live run was refused on it
       # ("Supported values: 'image/jpeg'"), the docs' own curl example sends
       # none, and the reply is converted to PNG at the edge instead
       # (`test_the_model_takes_what_the_docs_say`).
       body.get("response_format") == {"type": "image",
                                       "aspect_ratio": "2:3", "image_size": "1K"}, str(body.get("response_format")))
    ck("  and the picture that comes back is the reply's image block, decoded",
       got["images"][0] == MADE and got.get("note", "").endswith("gemini-3-pro-image"))
    rows = [r for r in toolcalls._rows("", 1) if r.provider == "gemini_images"]
    ck("  every call is filed under its own provider, the reply's shape on the row",
       len(rows) >= 2 and all(r.ok == "yes" for r in rows[-2:]) and "keys:" in (rows[-1].ref or "")
       and "outputs" in (rows[-1].ref or ""), str([(r.ok, r.ref) for r in rows[-2:]]))
    calls.clear()
    imagegen.with_references("square", product=[prod], look=[], model="gemini:gemini-3.1-flash-image", shape="square")
    imagegen.with_references("wide", product=[prod], look=[], model="gemini:gemini-3.1-flash-image", shape="landscape")
    ck("  square and landscape map too",
       [c["json"]["response_format"]["aspect_ratio"] for c in calls] == ["1:1", "3:2"])

    print("\n— THE LIMITS THE DOCS SET —")
    calls.clear()
    many_p, many_c, many_l = [png((i, 0, 0, 255)) for i in range(5)], [png((0, i, 0, 255)) for i in range(3)], [png((0, 0, i, 255)) for i in range(3)]
    imagegen.with_references("x", product=many_p, cast=many_c, look=many_l, model="gemini:gemini-3-pro-image")
    n_img = len([b for b in calls[-1]["json"]["input"] if b["type"] == "image"])
    ck("Nano Banana Pro takes six object references and three style references — eight objects offered, six sent, plus the three looks",
       n_img == 9, f"{n_img} images")
    calls.clear()
    imagegen.with_references("x", product=many_p, cast=many_c, look=many_l, model="gemini:gemini-3.1-flash-lite-image")
    n_img = len([b for b in calls[-1]["json"]["input"] if b["type"] == "image"])
    ck("  the lite model takes no style references, so the looks stay home", n_img == 8, f"{n_img} images")

    print("\n— REFUSALS, SAID BY NAME —")
    config.GEMINI_API_KEY = ""
    calls.clear()
    got2 = imagegen.with_references("x", product=[prod], look=[look], model="gemini:gemini-3-pro-image")
    ck("without a key the door refuses by the name of the variable, and calls nothing",
       not got2.get("ok") and "GEMINI_API_KEY" in got2.get("error", "") and not calls, got2.get("error", ""))
    config.GEMINI_API_KEY = "gk-test"
    reply["mode"] = "429"
    got3 = imagegen.with_references("x", product=[prod], look=[look], model="gemini:gemini-3-pro-image")
    ck("  Google's error comes back as status and message, and is filed",
       not got3.get("ok") and got3.get("error", "").startswith("429: Resource has been exhausted")
       and any(r.ok == "no" and "exhausted" in (r.error or "") for r in toolcalls._rows("", 1) if r.provider == "gemini_images"),
       got3.get("error", ""))
    reply["mode"] = "empty"
    got4 = imagegen.with_references("x", product=[prod], look=[look], model="gemini:gemini-3-pro-image")
    ck("  a reply with no image block says so, naming the keys it did have",
       not got4.get("ok") and "no image block" in got4.get("error", "") and "outputs" in got4.get("error", ""), got4.get("error", ""))

    print("\n— THE REPLY'S SHAPE IS NOT ASSUMED —")
    reply["mode"] = "nested"
    got5 = imagegen.with_references("x", product=[prod], look=[look], model="gemini:gemini-3-pro-image")
    ck("an image block nested under steps is found", got5.get("ok") and got5["images"][0] == MADE)
    reply["mode"] = "legacy"
    got6 = imagegen.with_references("x", product=[prod], look=[look], model="gemini:gemini-3-pro-image")
    ck("  and the older inlineData shape is read too", got6.get("ok") and got6["images"][0] == MADE)
    reply["mode"] = "ok"

    print("\n— THE OTHER ROUTES —")
    calls.clear()
    openai_calls.clear()
    pl = imagegen.plate("an empty table", shape="square", n=1, model="gemini:gemini-3.1-flash-image")
    ck("a plate through the gemini door is text only",
       pl.get("ok") and len(calls) == 1 and not any(b["type"] == "image" for b in calls[0]["json"]["input"])
       and not openai_calls)
    calls.clear()
    imagegen.with_references("x", product=[prod], look=[look], model="gpt-image-1")
    ck("  a plain model name still goes to the first door, untouched",
       openai_calls == ["/images/edits"] and not calls)
    doc = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "bakeoff.py")).read()
    ck("  the bake-off names the second door", "gemini:" in doc and "GEMINI_API_KEY" in doc)

    print("\n— THROUGH THE WHOLE SET —")
    kb.add_entity("baci", "product", "zodiac-cup", "Zodiac Cup", description="a cup", origin="human")
    kb.add_asset("baci", "https://cdn.example/cup.png", rights=kb.OWNED, title="cup",
                 subject=kb.OBJECT, entity_key="zodiac-cup", origin="human")
    kb.add_asset("baci", "https://cdn.example/look.png", rights=kb.OWNED, title="look", subject=kb.SCENE, origin="human")
    kb.add_board("baci", "Studio")
    kb.set_board_role(next(a.id for a in kb.assets("baci") if "look" in (a.url or "")), "studio", "look", True)
    creative._fetch = lambda url: {"https://cdn.example/cup.png": prod, "https://cdn.example/look.png": look}.get(url, b"")
    creative.assess = lambda blob, brief, tenant="": {"ok": True, "verdicts": [], "overall": "", "failed": [], "fix": ""}
    creative.product_features = lambda tenant, entity_key, product, **k: {"ok": True, "features": ["a gold rim"], "cached": False}
    creative.compare_product = lambda c, p, f, tenant="", **k: {"ok": True, "match": 96, "differences": [], "same": True,
                                                              "lettering": False, "invented": False, "why": ""}
    calls.clear()
    openai_calls.clear()
    cup = coherence.commit("entity", "zodiac-cup", label="Zodiac Cup")
    got7 = creative.batch("baci", commitment=cup, entity_key="zodiac-cup", fmt="ad_frame",
                          positioning="the sign you were born under", plates=1, review=False,
                          boards=("studio",), image_model="gemini:gemini-3-pro-image")
    ck("a set run on a gemini: model draws every candidate through Google and files the frame",
       got7.get("made") == 1 and len(calls) >= 4 and not openai_calls
       and all(c["json"]["model"] == "gemini-3-pro-image" for c in calls), f"made={got7.get('made')} calls={len(calls)}")

    print()
    if _fail:
        print(f"{len(_fail)} FAILED:\n  " + "\n  ".join(_fail))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
