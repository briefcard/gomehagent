"""A drawn product is judged against its own photographs, and the closest
candidate is the one kept — with what was wrong named, and corrected once.

Owner, 2026-09-07: *"the photos are better but they are still not recreating
the product photos exactly. How can we improve this?"* — and, on the plan:
*"Lets follow your advice."*

WHAT WAS TRUE. A frame drawn from the product's photographs was filed as it
came: two candidates per cell, both kept, neither compared to the photographs
it was drawn from. The prompt said "reproduce exactly" and named nothing —
not the material, not the pattern, not the marks a careful observer would
check. Nothing could say a candidate's glyph was a star and not the crab,
so nothing could ask for the crab. And the look pins shared the model's
attention with the product, four against four.

THE RULES, each with its guard: every candidate is JUDGED against the
photographs, with the differences NAMED; the CLOSEST candidate is the one
kept, four asked for so there is a choice; a kept candidate that is still
wrong is redrawn ONCE with its differences in the prompt and kept only if
closer; the product's CHECKLIST — derived once from its photographs, cached —
reaches the prompt and is the judge's rubric; the look YIELDS to the product
(two pins, not four) and a product input is TRIMMED to the product; fidelity
is SAID on the frame; and a bake-off model reaches the request.

Run: python3 scripts/test_the_product_is_judged_against_its_photographs.py
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
from types import SimpleNamespace

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'fid.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["PUBLIC_BASE_URL"] = "https://example.test"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image  # noqa: E402

from app import (admin_ui as ui, coherence, creative, db, imagegen, kb,  # noqa: E402
                 kb_seed, llm, tenants)

KEY = "s3cret"
_fail: list[str] = []


def ck(label: str, cond, detail: str = "") -> None:
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def png(colour, w: int = 80, h: int = 80, mode: str = "RGBA") -> bytes:
    buf = io.BytesIO()
    Image.new(mode, (w, h), colour).save(buf, format="PNG")
    return buf.getvalue()


def cutout_with_margins() -> bytes:
    """A 200×200 transparent canvas with a 40×40 product in the middle — the
    shape a Shopify cutout arrives in."""
    im = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    for x in range(80, 120):
        for y in range(80, 120):
            im.putpixel((x, y), (200, 30, 30, 255))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


PICS = {
    "https://cdn.example/cup-front.png": cutout_with_margins(),
    "https://cdn.example/cup-side.png": png((30, 200, 30, 255)),
    "https://cdn.example/look-1.png": png((30, 30, 200, 255)),
    "https://cdn.example/look-2.png": png((30, 60, 200, 255)),
    "https://cdn.example/look-3.png": png((30, 90, 200, 255)),
}
CANDIDATE = {}   # colour -> index, so a kept frame can be traced to its candidate


def main() -> int:
    db.init_db()
    tenants.seed()
    kb_seed.seed_all()
    kb.add_entity("baci", "product", "zodiac-cup", "Zodiac Cup",
                  description="a porcelain cup with a hand-painted zodiac sign",
                  attributes={"material": "porcelain", "set": "6"}, origin="human")
    for url in ("https://cdn.example/cup-front.png", "https://cdn.example/cup-side.png"):
        kb.add_asset("baci", url, rights=kb.OWNED, title=url.rsplit("/", 1)[-1],
                     subject=kb.OBJECT, entity_key="zodiac-cup", origin="human")
    for url in ("https://cdn.example/look-1.png", "https://cdn.example/look-2.png",
                "https://cdn.example/look-3.png"):
        kb.add_asset("baci", url, rights=kb.OWNED, title=url.rsplit("/", 1)[-1],
                     subject=kb.SCENE, origin="human")
    kb.add_board("baci", "Lifestyle")
    for a in kb.assets("baci"):
        if "look-" in (a.url or ""):
            kb.set_board_role(a.id, "lifestyle", "look", True)
    creative._fetch = lambda url: PICS.get(url, b"")
    creative.assess = lambda blob, brief, tenant="": {
        "ok": True, "verdicts": [], "overall": "reads right", "failed": [], "fix": ""}

    sent: list = []
    calls = [0]

    def _post(path, *, json_body=None, files=None, data=None):
        sent.append({"path": path, "files": files, "data": data, "json": json_body})
        calls[0] += 1
        n = int((data or {}).get("n") or (json_body or {}).get("n") or 1)
        out = []
        for i in range(n):
            colour = (calls[0] * 9 % 250, i * 40 + 20, calls[0] // 28, 255)
            CANDIDATE[colour[:3]] = i
            out.append(png(colour))
        return {"ok": True, "images": out}
    imagegen.post = _post

    FEATURES = ["white porcelain with a matte finish", "a gold Cancer crab glyph on the front",
                "a thin gold rim", "a straight, slightly tapered body", "a small round handle"]
    creative.product_features = lambda tenant, entity_key, product, **k: {
        "ok": True, "features": list(FEATURES), "cached": False}

    def _judge_scripted(best_at: int, score_best: int, score_rest: int, diffs):
        def _judge(candidate, product, features, tenant=""):
            colour = Image.open(io.BytesIO(candidate)).convert("RGB").getpixel((2, 2))
            idx = CANDIDATE.get(tuple(colour), -1)
            if idx == best_at:
                return {"ok": True, "match": score_best, "differences": [], "why": ""}
            return {"ok": True, "match": score_rest, "differences": list(diffs), "why": ""}
        return _judge

    print("— ENTRY: four candidates, judged, the closest kept —")
    creative.compare_product = _judge_scripted(2, 95, 60, ["the glyph is a star, not the Cancer crab"])
    cup = coherence.commit("entity", "zodiac-cup", label="Zodiac Cup")
    got = creative.batch("baci", commitment=cup, entity_key="zodiac-cup", fmt="ad_frame",
                         positioning="the sign you were born under", plates=1, review=True)
    edits = [c for c in sent if c["path"] == "/images/edits"]
    ck("the drawn cell asks for FOUR candidates, so there is a choice",
       got["ok"] and edits and edits[0]["data"].get("n") == "4",
       f"n={edits[0]['data'].get('n') if edits else None}")
    ck("  the prompt carries the product's checklist — what a careful observer checks",
       edits and all(f in edits[0]["data"]["prompt"] for f in FEATURES),
       (edits[0]["data"]["prompt"][-400:] if edits else ""))
    ck("  ONE frame is filed for the cell — the closest — not all four",
       got["made"] == 1, f"made={got['made']}")
    ck("  and it is the candidate the judge scored highest",
       got["frames"] and (got["frames"][0].get("fidelity") or {}).get("match") == 95,
       str(got["frames"][0].get("fidelity") if got["frames"] else None))
    row = next((a for a in kb.assets("baci", publishable_only=False)
                if (a.batch or "") == got["batch"]), None)
    ck("  fidelity is on the frame's record, with how many were judged",
       row is not None and (row.assessment or {}).get("fidelity", {}).get("match") == 95
       and (row.assessment or {}).get("fidelity", {}).get("candidates") == 4,
       str((row.assessment or {}).get("fidelity") if row else None))
    ck("  and the set says it: judged, kept, closest to the product",
       got.get("fidelity", {}).get("judged") == 4 and got.get("fidelity", {}).get("kept") == 1
       and "closest to the product" in got["note"], got["note"][:200])

    print("\n— REDRAFT: a kept candidate that is still wrong is redrawn once, differences named —")
    sent.clear(); CANDIDATE.clear()
    state = {"round": 0}

    def _judge_wrong_then_right(candidate, product, features, tenant=""):
        # round 1: every candidate wrong; round 2 (after the redraft): right
        if len(sent) < 2:
            return {"ok": True, "match": 60, "differences": ["the rim is silver, not gold"], "why": ""}
        return {"ok": True, "match": 90, "differences": [], "why": ""}
    creative.compare_product = _judge_wrong_then_right
    got2 = creative.batch("baci", commitment=cup, entity_key="zodiac-cup", fmt="ad_frame",
                          positioning="the sign you were born under", plates=1, review=True)
    edits2 = [c for c in sent if c["path"] == "/images/edits"]
    ck("a second request is made for the cell, with the differences in the prompt",
       len(edits2) == 2 and "the rim is silver, not gold" in edits2[1]["data"]["prompt"]
       and "CORRECT" in edits2[1]["data"]["prompt"],
       f"{len(edits2)} request(s)")
    ck("  and the redrawn frame is kept because it is closer",
       got2["made"] == 1 and (got2["frames"][0].get("fidelity") or {}).get("match") == 90
       and (got2["frames"][0].get("fidelity") or {}).get("redrafted") is True,
       str(got2["frames"][0].get("fidelity") if got2["frames"] else None))

    print("\n— DEGRADED: no judge, no silent pretence —")
    sent.clear()
    creative.compare_product = lambda candidate, product, features, tenant="": {
        "ok": False, "match": 0, "differences": [], "why": "ANTHROPIC_API_KEY is not set"}
    got3 = creative.batch("baci", commitment=cup, entity_key="zodiac-cup", fmt="ad_frame",
                          positioning="the sign you were born under", plates=1, review=False)
    ck("with no judge, the usual two are kept and the set SAYS fidelity was not judged",
       got3["made"] == creative.PER_PROMPT and "not judged" in got3["note"]
       and got3.get("fidelity", {}).get("judged") == 0, got3["note"][:160])

    print("\n— THE CHECKLIST: derived once from the photographs, cached —")
    asks: list = []

    def _ask(kind, content, tenant="", max_tokens=0, **k):
        asks.append(kind)
        return SimpleNamespace(ok=True, text=json.dumps({"features": FEATURES}), degraded="", error="")
    llm.ask = _ask
    from app import creative as _c
    import importlib
    real_features = importlib.import_module("app.creative").__dict__.get("_product_features_live")
    ck("the derivation exists as a real seam", callable(real_features))
    if callable(real_features):
        f1 = real_features("baci", "zodiac-cup", [PICS["https://cdn.example/cup-front.png"]])
        f2 = real_features("baci", "zodiac-cup", [PICS["https://cdn.example/cup-front.png"]])
        ck("the checklist is derived from the photographs with ONE vision call, then cached",
           f1.get("features") == FEATURES and f2.get("features") == FEATURES
           and f2.get("cached") is True and asks.count("creative_review") == 1,
           f"calls={asks.count('creative_review')} cached={f2.get('cached')}")
        f3 = real_features("baci", "zodiac-cup", [PICS["https://cdn.example/cup-side.png"]])
        ck("  and re-derived when the photographs change",
           f3.get("cached") is False and asks.count("creative_review") == 2)

    print("\n— THE JUDGE: a real comparison, parsed —")
    real_judge = importlib.import_module("app.creative").__dict__.get("_compare_product_live")
    ck("the judge exists as a real seam", callable(real_judge))
    if callable(real_judge):
        seen: list = []

        def _ask2(kind, content, tenant="", max_tokens=0, **k):
            seen.append(content)
            return SimpleNamespace(ok=True, text=json.dumps({
                "match": 72, "differences": ["the glyph is a star, not the Cancer crab"],
                "same_product": False}), degraded="", error="")
        llm.ask = _ask2
        v = real_judge(png((1, 2, 3, 255)), [PICS["https://cdn.example/cup-front.png"]], FEATURES, "baci")
        images = [b for b in seen[-1] if isinstance(b, dict) and b.get("type") == "image"]
        text = " ".join(b.get("text", "") for b in seen[-1] if isinstance(b, dict) and b.get("type") == "text")
        ck("the candidate and the photographs go to the judge together, with the checklist as its rubric",
           len(images) == 2 and all(f in text for f in FEATURES), f"{len(images)} images")
        ck("  and the verdict carries the match and the named differences",
           v.get("ok") and v.get("match") == 72 and v.get("differences") == ["the glyph is a star, not the Cancer crab"],
           str(v))

    print("\n— INPUTS: the look yields to the product, and the product is trimmed —")
    ck("with the product in the request, at most two look pins ride along",
       edits and len([f for f in edits[0]["files"] if f[1][0].startswith("look-")]) <= 2
       and len([f for f in edits[0]["files"] if f[1][0].startswith("product-")]) == 2,
       str([f[1][0] for f in edits[0]["files"]]) if edits else "")
    # THE CUTOUT, found by its transparency — not by position: `pick`'s choice
    # leads the product inputs, and which photograph that is depends on
    # creation order. A check on "product-1" passed for the wrong reason.
    sizes = {}
    for f in (edits[0]["files"] if edits else []):
        if not f[1][0].startswith("product-"):
            continue
        im = Image.open(io.BytesIO(f[1][1]))
        has_alpha = im.mode == "RGBA" and im.getchannel("A").getextrema()[0] < 32
        sizes["cutout" if has_alpha else "solid"] = im.size
    ck("  a cutout with wide transparent margins is sent trimmed to the product",
       sizes.get("cutout") is not None and sizes["cutout"][0] <= 48 and sizes["cutout"][1] <= 48,
       f"{sizes} (the product is 40×40 on a 200×200 canvas; 4% padding)")
    ck("  and a photograph with no margins is sent as it is",
       sizes.get("solid") == (80, 80), str(sizes))

    print("\n— THE CONSOLE: fidelity is said on the frame —")
    page = ui.render_content(KEY, tenant="baci", sub="pictures")
    ck("the set card shows the product match on each frame",
       "product match 95" in page or "product match 90" in page)

    print("\n— THE BAKE-OFF: another model reaches the request —")
    sent.clear()
    creative.compare_product = _judge_scripted(0, 95, 60, ["x"])
    got4 = creative.batch("baci", commitment=cup, entity_key="zodiac-cup", fmt="ad_frame",
                          positioning="the sign you were born under", plates=1,
                          review=False, image_model="gpt-image-1-mini")
    ck("a named model is what the request is made with",
       got4["ok"] and sent and sent[0]["data"].get("model") == "gpt-image-1-mini",
       str(sent[0]["data"].get("model") if sent else None))

    print()
    if _fail:
        print(f"{len(_fail)} FAILED:\n  " + "\n  ".join(_fail))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
