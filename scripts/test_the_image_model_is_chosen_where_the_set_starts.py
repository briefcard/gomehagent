"""The image model is chosen where the set starts: the OpenAI default,
Google's models once their key is set, or both — one set per model on the
same brief, every frame carrying the model that drew it.

Owner, 2026-09-08: *"Can we just place those into the system and allow me
to choose which model to use or if to use both."*

Run: python3 scripts/test_the_image_model_is_chosen_where_the_set_starts.py
"""
from __future__ import annotations

import base64
import io
import os
import sys
import tempfile
from types import SimpleNamespace
from urllib.parse import unquote

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'choice.db')}"
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


def main() -> int:
    db.init_db()
    tenants.seed()
    kb_seed.seed_all()
    config.OPENAI_API_KEY = "sk-test"
    config.GEMINI_API_KEY = ""

    print("— THE OFFER SAYS WHAT IS SET UP, AND WHAT ONE LINE WOULD ADD —")
    offer = imagegen.choices()
    ck("the default comes first and is selectable",
       offer and offer[0]["value"] == imagegen.MODEL and offer[0]["ok"] and "default" in offer[0]["label"])
    gem = [c for c in offer if c["value"].startswith("gemini:")]
    ck("  Google's models are listed but not selectable without their key, naming the variable",
       len(gem) == 2 and all(not c["ok"] and "GEMINI_API_KEY" in c["why"] for c in gem), str(gem)[:160])
    sel = ui.model_select()
    ck("  the form shows them disabled with the reason, and no 'both' yet",
       'name="image_model"' in sel and sel.count("disabled") == 2 and "GEMINI_API_KEY" in sel
       and 'value="both"' not in sel)
    ck("  '' means the default; 'both' is refused by name; an unlisted model is refused",
       imagegen.chosen("") == ([imagegen.MODEL], "")
       and not imagegen.chosen("both")[0] and "GEMINI_API_KEY" in imagegen.chosen("both")[1]
       and not imagegen.chosen("gemini:gemini-3-pro-image")[0]
       and not imagegen.chosen("dall-e-9")[0], str(imagegen.chosen("both")))
    config.GEMINI_API_KEY = "gk-test"
    sel2 = ui.model_select()
    ck("with the key set every model is selectable and 'both' is offered",
       "disabled" not in sel2 and 'value="both"' in sel2 and "one set per model" in sel2)
    ck("  and 'both' means every model with a key",
       imagegen.chosen("both") == ([imagegen.MODEL, "gemini:gemini-3-pro-image", "gemini:gemini-3.1-flash-image"], ""))
    frm = open(ui.__file__).read()
    ck("  the make-frames form carries the choice beside the boards",
       "{model_select()}" in frm and frm.index("{boards_select(tenant)}\n        {model_select()}") > 0)

    print("\n— THE ROUTE HONOURS THE CHOICE, AND REFUSES BY NAME —")
    with db.SessionLocal() as s:
        s.add(db.Output(id="out-1", tenant="baci", system_key="ad_creative", entity_key="",
                        body="The sign you were born under"))
        s.commit()
    scheduled: list = []
    real_bg = web._run_bg
    web._run_bg = lambda label, fn, *a, **kw: scheduled.append((label, fn, a, kw))
    from fastapi.testclient import TestClient
    try:
        client = TestClient(web.app)
        r = client.post("/admin/ad_frames", params={"key": KEY},
                        data={"tenant": "baci", "output_id": "out-1", "plates": "4",
                              "image_model": "gemini:gemini-3-pro-image"}, follow_redirects=False)
        ck("a chosen model reaches the run",
           r.status_code == 303 and scheduled and scheduled[-1][1] is creative.batch
           and scheduled[-1][3].get("image_model") == "gemini:gemini-3-pro-image"
           and "by gemini:gemini-3-pro-image" in unquote(r.headers.get("location", "")),
           str(scheduled[-1][3].get("image_model") if scheduled else None))
        r = client.post("/admin/ad_frames", params={"key": KEY},
                        data={"tenant": "baci", "output_id": "out-1", "plates": "4", "image_model": "both"},
                        follow_redirects=False)
        ck("  'both' runs one set per model",
           scheduled[-1][1] is creative.batch_each
           and scheduled[-1][3].get("models") == [imagegen.MODEL, "gemini:gemini-3-pro-image", "gemini:gemini-3.1-flash-image"]
           and "one set per model" in unquote(r.headers.get("location", "")))
        n = len(scheduled)
        config.GEMINI_API_KEY = ""
        r = client.post("/admin/ad_frames", params={"key": KEY},
                        data={"tenant": "baci", "output_id": "out-1", "plates": "4",
                              "image_model": "gemini:gemini-3-pro-image"}, follow_redirects=False)
        ck("  a model without its key is refused before anything runs, naming the variable",
           len(scheduled) == n and "GEMINI_API_KEY" in unquote(r.headers.get("location", "")),
           unquote(r.headers.get("location", ""))[:160])
        r = client.post("/admin/ad_frames", params={"key": KEY},
                        data={"tenant": "baci", "output_id": "out-1", "plates": "4"}, follow_redirects=False)
        ck("  no choice is the default",
           len(scheduled) == n + 1 and scheduled[-1][3].get("image_model") == imagegen.MODEL)
    finally:
        web._run_bg = real_bg
    config.GEMINI_API_KEY = "gk-test"

    print("\n— BOTH: ONE SET PER MODEL, TOLD APART ON THE FRAME AND THE CARD —")
    kb.add_entity("baci", "product", "zodiac-cup", "Zodiac Cup", description="a cup", origin="human")
    kb.add_asset("baci", "https://cdn.example/cup.png", rights=kb.OWNED, title="cup",
                 subject=kb.OBJECT, entity_key="zodiac-cup", origin="human")
    kb.add_asset("baci", "https://cdn.example/look.png", rights=kb.OWNED, title="look", subject=kb.SCENE, origin="human")
    kb.add_board("baci", "Studio")
    kb.set_board_role(next(a.id for a in kb.assets("baci") if "look" in (a.url or "")), "studio", "look", True)
    prod, look = png((200, 30, 30, 255)), png((30, 30, 200, 255))
    creative._fetch = lambda url: {"https://cdn.example/cup.png": prod, "https://cdn.example/look.png": look}.get(url, b"")
    creative.assess = lambda blob, brief, tenant="": {"ok": True, "verdicts": [], "overall": "", "failed": [], "fix": ""}
    creative.product_features = lambda tenant, entity_key, product, **k: {"ok": True, "features": ["a gold rim"], "cached": False}
    creative.compare_product = lambda c, p, f, tenant="", **k: {"ok": True, "match": 96, "differences": [], "same": True,
                                                              "lettering": False, "invented": False, "why": ""}
    counter = [0]

    def _openai(path, **kw):
        counter[0] += 1
        n_ = int((kw.get("data") or {}).get("n") or (kw.get("json_body") or {}).get("n") or 1)
        return {"ok": True, "images": [png((counter[0] * 7 % 250, i * 50 + 5, 1, 255)) for i in range(n_)]}
    imagegen.post = _openai
    gcalls: list = []

    def _gpost(url, *, headers, json_body):
        gcalls.append(json_body["model"])
        counter[0] += 1
        return SimpleNamespace(status_code=200, text="", json=lambda: {"outputs": [
            {"type": "image", "mime_type": "image/png",
             "data": base64.b64encode(png((counter[0] * 7 % 250, 3, 200, 255))).decode()}]})
    gemini_images.post = _gpost
    cup = coherence.commit("entity", "zodiac-cup", label="Zodiac Cup")
    got = creative.batch_each("baci", models=[imagegen.MODEL, "gemini:gemini-3-pro-image"],
                              commitment=cup, entity_key="zodiac-cup", fmt="ad_frame",
                              positioning="the sign you were born under", plates=1, review=False,
                              boards=("studio",))
    ck("both makes one set per model on the same brief",
       got.get("ok") and len(got.get("sets") or []) == 2 and got["sets"][0]["model"] == imagegen.MODEL
       and got["sets"][1]["model"] == "gemini:gemini-3-pro-image" and got.get("made") == 2
       and gcalls and all(m == "gemini-3-pro-image" for m in gcalls), str(got.get("sets"))[:220])
    ck("  and the summary names each model's count",
       imagegen.MODEL + ": 1 made" in got.get("note", "") and "gemini:gemini-3-pro-image: 1 made" in got.get("note", "")
       and "made 2" in web._summarise(got), got.get("note", "")[:200])
    frames = [a for a in kb.assets("baci", publishable_only=False) if (a.batch or "")]
    tags = {t for a in frames for t in (a.tags or []) if str(t).startswith("model:")}
    ck("  every frame carries the model that drew it",
       tags == {f"model:{imagegen.MODEL}", "model:gemini:gemini-3-pro-image"}, str(tags))
    page = ui.render_content(KEY, tenant="baci", sub="pictures")
    ck("  and the set cards say which model drew each",
       f"drawn by {imagegen.MODEL}" in page and "drawn by gemini:gemini-3-pro-image" in page)

    print()
    if _fail:
        print(f"{len(_fail)} FAILED:\n  " + "\n  ".join(_fail))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
