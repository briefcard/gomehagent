"""The model takes what the docs say it takes — and a run says where it
stands while it runs, says everything when it ends, and shows what it drew
even when the judge kept nothing.

Owner, 2026-09-08, after a run whose Google half was refused on
`response_format.mime_type` and whose OpenAI half the judge emptied, on a
card that promised "two to three minutes" and then cut the reason at 140
characters: *"make sure that you learn the lesson of what kind of inputs
the models take"* and *"Nothing landed back into the drafts we expected."*

Run: python3 scripts/test_the_model_takes_what_the_docs_say.py
"""
from __future__ import annotations

import base64
import io
import json
import os
import sys
import tempfile
import time
from types import SimpleNamespace

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'docs.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["PUBLIC_BASE_URL"] = "https://example.test"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image  # noqa: E402

from app import (admin_ui as ui, coherence, config, creative, db, gemini_images,  # noqa: E402
                 imagegen, kb, kb_seed, tenants, web)

KEY = "s3cret"
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


def jpeg(colour, w: int = 64, h: int = 64) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), colour).save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def gif(colour, w: int = 16, h: int = 16) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), colour).save(buf, format="GIF")
    return buf.getvalue()


def _bg(label: str, tenant: str) -> dict:
    with db.SessionLocal() as s:
        row = s.get(db.Setting, f"bg:{label}:{tenant}")
        return json.loads(row.value) if row and row.value else {}


def main() -> int:  # noqa: PLR0915
    db.init_db()
    tenants.seed()
    kb_seed.seed_all()
    config.OPENAI_API_KEY = "sk-test"
    config.GEMINI_API_KEY = "gk-test"

    print("— THE CONTRACT, PER MODEL, FROM THE DOCS —")
    ck("the docs URL rides the module and every model has its limits written down",
       gemini_images.DOC.startswith("https://ai.google.dev/")
       and all(set(v) >= {"objects", "style", "sizes"} for v in gemini_images.LIMITS.values())
       and gemini_images.LIMITS["gemini-3-pro-image"]["objects"] == 6
       and gemini_images.LIMITS["gemini-3.1-flash-image"]["objects"] == 10
       and gemini_images.LIMITS["gemini-3.1-flash-lite-image"] == {"objects": 14, "style": 0, "sizes": ("1K",)}
       and "512px" in gemini_images.LIMITS["gemini-3.1-flash-image"]["sizes"]
       and "512px" not in gemini_images.LIMITS["gemini-3-pro-image"]["sizes"])
    ck("  the input mime types are the documented five, and the inline ceiling is 20 MB",
       set(gemini_images.INPUT_MIMES) == {"image/png", "image/jpeg", "image/webp", "image/heic", "image/heif"}
       and gemini_images.INLINE_BUDGET == 20 * 1024 * 1024 and gemini_images.INLINE_MARGIN < gemini_images.INLINE_BUDGET)
    ck("  the size asked for is one every model offers",
       all(gemini_images.IMAGE_SIZE in v["sizes"] for v in gemini_images.LIMITS.values()))

    sent: list = []
    reply_mime = ["image/jpeg"]

    def _gpost(url, *, headers, json_body):
        sent.append(json_body)
        blob = jpeg((200, 30, 30)) if reply_mime[0] == "image/jpeg" else png((200, 30, 30, 255))
        return SimpleNamespace(status_code=200, text="", json=lambda: {"outputs": [
            {"type": "image", "mime_type": reply_mime[0], "data": base64.b64encode(blob).decode()}]})
    gemini_images.post = _gpost
    got = gemini_images.edit("a cup on a table",
                             images=[("product-1", png((1, 2, 3, 255)), "image/png"),
                                     ("look-1", jpeg((9, 9, 9)), "image/jpeg")],
                             model="gemini:gemini-3-pro-image", shape="square", n=1)
    body = sent[-1]
    ck("the request sets NO mime_type on response_format — the docs' own example sends none, and Pro refused image/png by name",
       got.get("ok") and "mime_type" not in body["response_format"]
       and body["response_format"] == {"type": "image", "aspect_ratio": "1:1", "image_size": "1K"},
       str(body.get("response_format")))
    ck("  the reply's JPEG comes back as PNG bytes — the pipeline's contract, honoured at the edge",
       got.get("ok") and got["images"] and got["images"][0][:8] == b"\x89PNG\r\n\x1a\n")
    ck("  every input block carries the mime its bytes actually are",
       [b["mime_type"] for b in body["input"] if b["type"] == "image"] == ["image/png", "image/jpeg"])
    reply_mime[0] = "image/png"
    got_png = gemini_images.edit("a cup", images=[("product-1", png((1, 2, 3, 255)), "image/png")],
                                 model="gemini:gemini-3-pro-image", n=1)
    ck("  a PNG reply is kept as it is", got_png.get("ok") and got_png["images"][0][:4] == b"\x89PNG")

    got2 = gemini_images.edit("a cup",
                              images=[("product-1", gif((1, 2, 3)), "image/gif"),
                                      ("product-2", b"not an image at all", "image/png")],
                              model="gemini:gemini-3.1-flash-image", n=1)
    body2 = sent[-1]
    ins = [b for b in body2["input"] if b["type"] == "image"]
    ck("an input the API does not take is converted to PNG; one that is not an image is left out and said",
       got2.get("ok") and len(ins) == 1 and ins[0]["mime_type"] == "image/png"
       and "product-2" in got2.get("note", "") and "left out" in got2.get("note", ""), str(got2.get("note")))

    real_margin = gemini_images.INLINE_MARGIN
    gemini_images.INLINE_MARGIN = 250
    got3 = gemini_images.edit("a cup",
                              images=[("product-1", png((1, 2, 3, 255), 8, 8), "image/png"),
                                      ("look-1", png((5, 5, 5, 255), 64, 64), "image/png"),
                                      ("look-2", png((6, 6, 6, 255), 64, 64), "image/png")],
                              model="gemini:gemini-3-pro-image", n=1)
    gemini_images.INLINE_MARGIN = real_margin
    ins3 = [b for b in sent[-1]["input"] if b["type"] == "image"]
    ck("the inline ceiling is kept by dropping trailing pictures, and the drop is said",
       got3.get("ok") and len(ins3) < 3 and ins3[0]["data"] and "20 MB" in got3.get("note", ""),
       f"inputs={len(ins3)} note={got3.get('note')}")

    got4 = gemini_images.edit("a cup", images=[(f"product-{i}", png((i, 2, 3, 255)), "image/png") for i in range(9)]
                              + [(f"look-{i}", png((7, i, 3, 255)), "image/png") for i in range(5)],
                              model="gemini:gemini-3-pro-image", n=1)
    ins4 = [b for b in sent[-1]["input"] if b["type"] == "image"]
    ck("a model's reference caps hold — Pro: 6 objects and 3 style",
       got4.get("ok") and len(ins4) == 9 and got4.get("inputs") == 9, str(len(ins4)))

    print("\n— THE OPENAI CONTRACT, PER MODEL, FROM ITS REFERENCE —")
    ck("the reference URL rides the module, the 2.5 pair is listed with its extra quality tiers, the mini takes no fidelity",
       imagegen.OPENAI_DOC.startswith("https://developers.openai.com/")
       and "xhigh" in imagegen.OPENAI_MODELS["gpt-image-2.5-sunburst"]["quality"]
       and "xhigh" not in imagegen.OPENAI_MODELS["gpt-image-1"]["quality"]
       and imagegen.OPENAI_MODELS["gpt-image-1-mini"]["fidelity"] is False
       and all(v["refs"] == 16 for v in imagegen.OPENAI_MODELS.values()))
    snap = imagegen.openai_contract("gpt-image-2.5-sunburst-2026-09-08")
    ck("  a dated snapshot answers as its family, listed; an unknown id gets the documented defaults, unlisted",
       snap.get("listed") is True
       and {k: v for k, v in snap.items() if k != "listed"} == imagegen.OPENAI_MODELS["gpt-image-2.5-sunburst"]
       and imagegen.openai_contract("dall-e-9") == {**imagegen.OPENAI_DEFAULT, "listed": False})
    ck("  the newest editing model is offered where a set starts, once the OpenAI key is set",
       any(c["value"] == "gpt-image-2.5-sunburst" and c["ok"] for c in imagegen.choices()))
    ocalls: list = []

    def _opost(path, *, json_body=None, files=None, data=None):
        ocalls.append({"path": path, "files": files, "data": data, "json": json_body})
        n_ = int((data or {}).get("n") or (json_body or {}).get("n") or 1)
        return {"ok": True, "images": [png((9, i * 30 + 3, 9, 255)) for i in range(n_)]}
    imagegen.post = _opost
    got_o = imagegen.with_references("a cup", product=[png((1, 2, 3, 255))], look=[jpeg((5, 5, 5))],
                                     shape="square", n=1, model="gpt-image-2.5-sunburst")
    ck("the 2.5 model goes through the documented multipart door with input_fidelity high",
       got_o.get("ok") and ocalls and ocalls[-1]["path"] == "/images/edits"
       and ocalls[-1]["data"]["model"] == "gpt-image-2.5-sunburst"
       and ocalls[-1]["data"]["input_fidelity"] == "high" and len(ocalls[-1]["files"]) == 2,
       str(got_o)[:160])
    before = len(ocalls)
    bad = imagegen.with_references("a cup", product=[png((1, 2, 3, 255))], look=[], shape="square",
                                   n=1, model="dall-e-9")
    ck("  an id the reference does not list is SENT with the documented defaults — the model is a setting — and SAID, with the docs URL",
       bad.get("ok") and len(ocalls) == before + 1 and ocalls[-1]["data"]["model"] == "dall-e-9"
       and "not in the OpenAI edits reference" in bad.get("note", "") and imagegen.OPENAI_DOC in bad.get("note", ""),
       str(bad.get("note"))[:200])
    many = imagegen.with_references("a cup", product=[png((i, 2, 3, 255)) for i in range(4)],
                                    look=[png((7, i, 3, 255)) for i in range(4)],
                                    cast=[png((3, 3, i, 255)) for i in range(3)], shape="square", n=1,
                                    model="gpt-image-1")
    ck("  the pictures are counted against the documented sixteen",
       many.get("ok") and len(ocalls[-1]["files"]) <= 16)
    real_refs = imagegen.OPENAI_MODELS["gpt-image-1"]["refs"]
    imagegen.OPENAI_MODELS["gpt-image-1"]["refs"] = 2
    few = imagegen.with_references("a cup", product=[png((i, 2, 3, 255)) for i in range(3)],
                                   look=[png((7, 1, 3, 255))], shape="square", n=1, model="gpt-image-1")
    imagegen.OPENAI_MODELS["gpt-image-1"]["refs"] = real_refs
    ck("  past the count the rest are dropped from the end, and said",
       few.get("ok") and len(ocalls[-1]["files"]) == 2 and "past the documented 2 images" in few.get("note", ""),
       f"files={len(ocalls[-1]['files'])} note={few.get('note')}")
    gone = imagegen.plate("a table", shape="square", n=1, model="dall-e-9")
    ck("  scenery through an unlisted model goes through and is said the same way",
       gone.get("ok") and "not in the OpenAI edits reference" in gone.get("note", ""), str(gone)[:200])
    ck("'both' is one set PER PROVIDER — three OpenAI models on one key are not three sets",
       imagegen.chosen("both") == ([imagegen.MODEL, "gemini:gemini-3-pro-image"], "")
       and imagegen.chosen("both", default="gpt-image-2.5-sunburst") == (["gpt-image-2.5-sunburst", "gemini:gemini-3-pro-image"], "")
       and imagegen.chosen("both", default="gemini:gemini-3.1-flash-image") == (["gemini:gemini-3.1-flash-image", imagegen.MODEL], ""),
       str(imagegen.chosen("both", default="gpt-image-2.5-sunburst")))
    config.GEMINI_API_KEY = ""
    ck("  and with one provider keyed it is refused by name, on the form too",
       not imagegen.chosen("both")[0] and "two providers" in imagegen.chosen("both")[1]
       and 'value="both"' not in ui.model_select())
    config.GEMINI_API_KEY = "gk-test"

    print("\n— A RUN SAYS WHERE IT STANDS —")
    seen: list = []

    def _slow(tenant, *, progress=None):
        for i in (1, 2):
            progress(f"cell {i} of 2")
            seen.append(_bg("slowjob", tenant).get("detail"))
        return {"made": 2}
    web._run_bg("slowjob", _slow, "baci")
    for _ in range(50):
        if _bg("slowjob", "baci").get("state") == "done":
            break
        time.sleep(0.05)
    ck("a job that takes `progress` is handed a writer, and each call replaces the running detail",
       seen == ["cell 1 of 2", "cell 2 of 2"] and _bg("slowjob", "baci").get("state") == "done", str(seen))

    def _plain(tenant):
        return {"made": 1}
    web._run_bg("plainjob", _plain, "baci")
    for _ in range(50):
        if _bg("plainjob", "baci").get("state") == "done":
            break
        time.sleep(0.05)
    ck("  a job without it is called exactly as before", _bg("plainjob", "baci").get("state") == "done")

    with db.SessionLocal() as s:
        s.merge(db.Setting(key="bg:ad_frames:baci", value=json.dumps(
            {"state": "running", "detail": "cell 3 of 8 — 2 kept", "at": "2026-09-08T15:36:00"})))
        s.merge(db.Setting(key="bg:layers:baci", value=json.dumps(
            {"state": "done", "detail": "3 placements", "at": "2026-09-08T10:00:00"})))
        s.commit()
    n = web._sweep_interrupted()
    after = _bg("ad_frames", "baci")
    ck("at boot a job left RUNNING is marked failed with the reason, its last progress kept; done rows untouched",
       n == 1 and after.get("state") == "failed" and "server restarted" in after.get("detail", "")
       and "cell 3 of 8" in after.get("detail", "") and after.get("at") == "2026-09-08T15:36:00"
       and _bg("layers", "baci").get("state") == "done", str(after))
    with db.SessionLocal() as s:
        s.merge(db.Setting(key="bg:ad_frames:baci", value=json.dumps(
            {"state": "running", "detail": "", "at": "2026-09-08T15:36:00"})))
        s.commit()
    card = ui._frames_run("baci")
    ck("the running card gives the honest estimate — minutes per frame, a set per model — and says to reload",
       "three to six" in card and "per model" in card and "reload" in card.lower() and "two to three" not in card)
    with db.SessionLocal() as s:
        s.merge(db.Setting(key="bg:ad_frames:baci", value=json.dumps(
            {"state": "running", "detail": "model 2 of 2 (gemini): cell 3 of 8 — 2 kept", "at": "2026-09-08T15:36:00"})))
        s.commit()
    card2 = ui._frames_run("baci")
    ck("  and shows the run's own progress once it has any",
       "cell 3 of 8" in card2 and "model 2 of 2" in card2 and "three to six" not in card2)
    long = "x" * 900
    with db.SessionLocal() as s:
        s.merge(db.Setting(key="bg:ad_frames:baci", value=json.dumps(
            {"state": "done", "detail": long, "at": "2026-09-08T15:52:00"})))
        s.commit()
    ck("  a finished run's whole note is shown, not the first 600 characters",
       long in ui._frames_run("baci"))

    print("\n— WHAT THE JUDGE DROPPED IS SHOWN, NOT COUNTED —")
    kb.add_entity("baci", "product", "zodiac-cup", "Zodiac Cup", description="a cup", origin="human")
    kb.add_asset("baci", "https://cdn.example/cup.png", rights=kb.OWNED, title="cup",
                 subject=kb.OBJECT, entity_key="zodiac-cup", origin="human")
    kb.add_asset("baci", "https://cdn.example/look.png", rights=kb.OWNED, title="look",
                 subject=kb.SCENE, origin="human")
    kb.add_board("baci", "Studio")
    kb.set_board_role(next(a.id for a in kb.assets("baci") if "look" in (a.url or "")), "studio", "look", True)
    prod, look = png((200, 30, 30, 255)), png((30, 30, 200, 255))
    creative._fetch = lambda url: {"https://cdn.example/cup.png": prod, "https://cdn.example/look.png": look}.get(url, b"")
    creative.assess = lambda blob, brief, tenant="": {"ok": True, "verdicts": [], "overall": "", "failed": [], "fix": ""}
    creative.product_features = lambda tenant, entity_key, product, **k: {"ok": True, "features": ["a gold rim"], "cached": False}
    creative.compare_product = lambda c, p, f, tenant="", **k: {"ok": True, "match": 60, "same": False, "lettering": False,
                                                              "invented": False, "why": "",
                                                              "differences": ["the rim is plain"]}
    counter = [0]

    def _openai(path, **kw):
        counter[0] += 1
        n_ = int((kw.get("data") or {}).get("n") or (kw.get("json_body") or {}).get("n") or 1)
        return {"ok": True, "images": [png((counter[0] * 7 % 250, i * 50 + 5, 1, 255)) for i in range(n_)]}
    imagegen.post = _openai
    cup = coherence.commit("entity", "zodiac-cup", label="Zodiac Cup")
    lines: list = []
    got = creative.batch("baci", commitment=cup, entity_key="zodiac-cup", plates=2, review=False,
                         progress=lambda t: lines.append(t))
    sets = kb.batches("baci")
    g = next((x for x in sets if x["batch"] == got.get("batch")), None)
    ck("a set the judge emptied makes 0 — and the closest attempt of each dropped cell is filed APART, tagged",
       got.get("made") == 0 and got["fidelity"]["not_the_product"] >= 1
       and got["fidelity"]["shown_below"] == got["fidelity"]["not_the_product"]
       and g is not None and g["made"] == 0 and len(g["attempts"]) == got["fidelity"]["shown_below"]
       and all(kb.NOT_THE_PRODUCT in (a.tags or []) for a in g["attempts"]),
       f"made={got.get('made')} fidelity={got.get('fidelity')} attempts={len(g['attempts']) if g else None}")
    ck("  each attempt carries the judge's word — match and the named difference — and was never assessed against the brief",
       g is not None and all((a.assessment or {}).get("fidelity", {}).get("match") == 60
                             and "the rim is plain" in (a.assessment or {}).get("fidelity", {}).get("differences", [])
                             and (a.assessment or {}).get("fidelity", {}).get("below") is True
                             and not (a.assessment or {}).get("ok") for a in g["attempts"]))
    ck("  the note says the attempts are under the set",
       "closest attempt of each is under the set" in got.get("note", ""), got.get("note", "")[-200:])
    ck("  and names the lever — how many photographs it drew from, add close-ups of what was named",
       "drew from 1 photograph(s) of the product" in got.get("note", "")
       and "close-ups of what the judge named" in got.get("note", ""), got.get("note", "")[-260:])
    ck("  progress was told after every cell, in the run's own words",
       len(lines) == 2 and lines[0].startswith("cell 1 of 2") and "not the product" in lines[-1], str(lines))
    page = ui._batch_cards(KEY, "baci", list(kb.proposed_assets("baci")))[0]
    ck("the set card shows them under the frames, marked NOT the product with the match, not counted above",
       "Not the product" in page and "NOT the product &middot; match 60" in page and "the rim is plain" in page
       and f"below the bar of {creative.FIDELITY_KEEP}" in page)

    lines2: list = []
    got_each = creative.batch_each("baci", models=[imagegen.MODEL], commitment=cup, entity_key="zodiac-cup",
                                   plates=1, review=False, progress=lambda t: lines2.append(t))
    ck("both: every progress line names the model, and the per-set note is kept whole",
       lines2 and all(l.startswith(f"model 1 of 1 ({imagegen.MODEL}): cell") for l in lines2)
       and len(got_each["sets"][0]["note"]) > 140 and "NOT the product" in got_each.get("note", ""),
       f"{lines2[:1]} note_len={len(got_each['sets'][0]['note'])}")

    print()
    if _fail:
        print(f"{len(_fail)} FAILED:")
        for f in _fail:
            print(f"  - {f}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
