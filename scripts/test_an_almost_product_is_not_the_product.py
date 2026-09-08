"""An "almost" product is not the product: a candidate the judge names a
difference on is redrawn with that difference named, twice if it must be,
and if it is still not the product it is DROPPED and said — never filed.
Nothing else in the frame is a product, and the judge is asked about that
too.

Owner, 2026-09-08: *"The images are looking good but with the wrong
PRODUCTS! … Our acrylic glassware is generalized to shapes and glasses that
aren't correct depictions. Our plates are given design embellishments both
in the main product and the products shown in the surrounding scene. These
days, there must be a way to create this without hallucinations."*

WHAT WAS TRUE. The bar was 85 and one redraft; the closest candidate was
filed whatever its match, so a glass that was almost the glass reached the
owner as a frame with "product match 84" under it. Nothing told the model
the rest of the table was not its to design, and the judge was not asked
whether it had.

Run: python3 scripts/test_an_almost_product_is_not_the_product.py
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
from types import SimpleNamespace

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'almost.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["PUBLIC_BASE_URL"] = "https://example.test"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image  # noqa: E402

from app import (coherence, creative, db, imagegen, kb, kb_seed, llm,  # noqa: E402
                 tenants, web)

_fail: list[str] = []
STEM = "the stem is a plain cylinder, not the faceted stem in the photographs"


def ck(label: str, cond, detail: str = "") -> None:
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def png(colour, w: int = 96, h: int = 96) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (w, h), colour).save(buf, format="PNG")
    return buf.getvalue()


PICS = {"https://cdn.example/glass-front.png": png((240, 240, 250, 255)),
        "https://cdn.example/look-1.png": png((30, 30, 200, 255))}


def main() -> int:
    db.init_db()
    tenants.seed()
    kb_seed.seed_all()
    kb.add_entity("baci", "product", "faceted-glass", "Faceted Glass",
                  description="an acrylic wine glass with a faceted stem", origin="human")
    kb.add_asset("baci", "https://cdn.example/glass-front.png", rights=kb.OWNED, title="glass",
                 subject=kb.OBJECT, entity_key="faceted-glass", origin="human")
    kb.add_asset("baci", "https://cdn.example/look-1.png", rights=kb.OWNED, title="look",
                 subject=kb.SCENE, origin="human")
    kb.add_board("baci", "Studio")
    kb.set_board_role(next(a.id for a in kb.assets("baci") if "look-1" in (a.url or "")),
                      "studio", "look", True)
    creative._fetch = lambda url: PICS.get(url, b"")
    creative.assess = lambda blob, brief, tenant="": {
        "ok": True, "verdicts": [], "overall": "reads right", "failed": [], "fix": ""}
    creative.product_features = lambda tenant, entity_key, product, **k: {
        "ok": True, "features": ["a faceted stem", "a clear acrylic bowl"], "cached": False}
    glass = coherence.commit("entity", "faceted-glass", label="Faceted Glass")
    sent: list = []
    calls = [0]

    def _post(path, *, json_body=None, files=None, data=None):
        sent.append({"path": path, "files": files, "data": data})
        calls[0] += 1
        n = int((data or {}).get("n") or 1)
        return {"ok": True, "images": [png((calls[0] * 9 % 250, i * 40 + 20, calls[0] // 28, 255))
                                       for i in range(n)]}
    imagegen.post = _post

    def _run(judge):
        # the image counter is NOT reset: identical bytes are one picture to
        # the content-addressed store, and a repeat would file nothing
        sent.clear()
        creative.compare_product = judge
        return creative.batch("baci", commitment=glass, entity_key="faceted-glass", fmt="ad_frame",
                              positioning="the glass that survives the party", plates=1,
                              review=False, boards=("studio",))

    print("— AN ALMOST PRODUCT IS REDRAWN, TWICE IF IT MUST BE, THEN DROPPED AND SAID —")
    almost = lambda c, p, f, tenant="": {"ok": True, "match": 88, "differences": [STEM],  # noqa: E731
                                          "same": True, "lettering": False, "invented": False,
                                          "why": ""}
    got = _run(almost)
    prompts = [str((c["data"] or {}).get("prompt") or "") for c in sent]
    ck("a candidate at 88 with a named difference is not the product — nothing is filed for the cell",
       got.get("made") == 0 and got["fidelity"].get("not_the_product") == 1, str(got.get("fidelity"))[:200])
    ck("  it was redrawn twice with the difference named before being given up",
       len(sent) == 1 + creative.REDRAFTS == 3
       and all("CORRECT exactly these" in p and STEM in p for p in prompts[1:]), f"calls={len(sent)}")
    ck("  and the set says what was dropped and why",
       "1 cell(s) dropped — NOT the product" in str(got.get("note", "")) and STEM[:30] in str(got.get("note", "")),
       str(got.get("note", ""))[-260:])
    ck("  the bar is ninety, and a second redraft is allowed",
       creative.FIDELITY_KEEP >= 90 and creative.REDRAFTS >= 2)

    print("\n— THE PRODUCT ITSELF IS FILED, WITH NO OTHER PRODUCT IN THE FRAME —")
    true = lambda c, p, f, tenant="": {"ok": True, "match": 96, "differences": [],  # noqa: E731
                                        "same": True, "lettering": False, "invented": False,
                                        "why": ""}
    got2 = _run(true)
    p0 = str((sent[0]["data"] or {}).get("prompt") or "")
    ck("a true likeness is filed with its match on the frame",
       got2.get("made") == 1 and (got2["frames"][0].get("fidelity") or {}).get("match") == 96
       and got2["fidelity"].get("not_the_product") == 0)
    ck("  the request says the other pieces are from the same line as the product, in the board's style, nothing invented",
       "THE OTHER PIECES OF TABLEWARE in the frame are from the same line as the product" in p0
       and "Nothing invented" in p0 and "plain" not in p0.lower().split("the other pieces")[1][:400],
       p0[-300:])
    ck("  the rule rides beside the exact-product rule and the look rule, not instead of them",
       "reproduced EXACTLY" in p0 and "THE OTHER PIECES OF TABLEWARE" in p0 and "THE LOOK" in p0)

    print("\n— INVENTED DECORATION IS A FAULT, REDRAWN AWAY —")
    seen = [0]

    def strewn(c, p, f, tenant=""):
        seen[0] += 1
        # the first request's four candidates all carry a second, invented
        # plate; the redraw's are clean
        first = seen[0] <= 4
        return {"ok": True, "match": 95, "differences": [], "same": True,
                "lettering": False, "invented": first, "why": ""}
    got3 = _run(strewn)
    prompts3 = [str((c["data"] or {}).get("prompt") or "") for c in sent]
    ck("a frame with invented decoration on it is redrawn, asking for every invented ornament to be removed",
       len(sent) >= 2 and "REMOVE every invented decoration" in prompts3[1],
       prompts3[1][-200:] if len(prompts3) > 1 else "")
    ck("  and the clean redraw is the one filed",
       got3.get("made") == 1 and (got3["frames"][0].get("fidelity") or {}).get("redrafted") is True
       and got3["fidelity"].get("not_the_product") == 0, str(got3.get("fidelity"))[:160])
    stubborn = lambda c, p, f, tenant="": {"ok": True, "match": 95, "differences": [],  # noqa: E731
                                            "same": True, "lettering": False, "invented": True,
                                            "why": ""}
    got4 = _run(stubborn)
    ck("  a frame that keeps its invented decoration after the redraws is dropped and said",
       got4.get("made") == 0 and got4["fidelity"].get("not_the_product") == 1
       and "decoration was invented on the product or the pieces around it" in str(got4.get("note", "")),
       str(got4.get("note", ""))[-200:])
    verdicts_in = [({"ok": True, "match": 97, "differences": [], "invented": True}, b"a"),
                   ({"ok": True, "match": 90, "differences": [], "invented": False}, b"b")]
    creative.compare_product = lambda c, p, f, tenant="": next(v for v, b in verdicts_in if b == c)
    pick = creative._closest([b"a", b"b"], [b"p"], [], "baci")
    ck("  a candidate free of invented decoration outranks a higher-scoring one with it",
       pick.get("ok") and pick.get("blob") == b"b")

    print("\n— COMPANIONS ARE THE OWNER'S PINS, NEVER THE CATALOGUE'S GUESS —")
    # Owner, 2026-09-08, first: background products "should just align with
    # our product line if they do show up"; then, after a day of companions
    # drawn from the catalogue: "all their relative proportions are off …
    # it's almost better if we stick to letting the visual boards set the
    # reference and let the AI generate the photos." So a companion joins
    # the request only when the owner pinned it as the product on the board
    # a run selects; a product with photographs but no pin stays out.
    ck("with nothing pinned beside the product, no companion photograph is sent — the line rule carries the other pieces",
       not any(f[1][0].startswith("cast-") for f in (sent[0]["files"] or []))
       and "DESIGN AND PATTERN REFERENCE" not in p0)
    kb.add_entity("baci", "product", "faceted-bowl", "Faceted Bowl",
                  description="an acrylic bowl with a faceted foot", origin="human",
                  attributes={"product_type": "Bowl"})
    kb.add_asset("baci", "https://cdn.example/bowl.png", rights=kb.OWNED, title="bowl",
                 subject=kb.OBJECT, entity_key="faceted-bowl", origin="human")
    PICS["https://cdn.example/bowl.png"] = png((250, 200, 200, 255))
    refs0 = creative.board_inputs("baci", "faceted-glass", boards=("studio",))
    ck("  a product with a photograph but no pin is NOT added on its own",
       not refs0["cast"] and not hasattr(creative, "companions"))
    kb.set_board_role(next(a.id for a in kb.assets("baci") if "bowl" in (a.url or "")),
                      "studio", "product", True)
    refs = creative.board_inputs("baci", "faceted-glass", boards=("studio",))
    ck("  pinned as the product on the chosen board, it is the cast — by name, trimmed like the product",
       len(refs["cast"]) == 1 and refs["cast_names"] == ["Faceted Bowl"] and len(refs["product"]) == 1)
    judged: list = []

    def true_with_cast(c, p, f, tenant="", cast=None):
        judged.append(list(cast or []))
        return {"ok": True, "match": 96, "differences": [], "same": True,
                "lettering": False, "invented": False, "why": ""}
    got5 = _run(true_with_cast)
    files5 = [f[1][0] for f in (sent[0]["files"] or [])]
    p5 = str((sent[0]["data"] or {}).get("prompt") or "")
    ck("the pinned companion's photograph rides the request as DESIGN AND PATTERN reference — what it looks like, never its size",
       got5.get("made") == 1 and files5 == ["product-1", "cast-1", "look-1"]
       and "DESIGN AND PATTERN REFERENCE for the other pieces on the table: reference images 2 to 2" in p5
       and "Faceted Bowl" in p5 and "not how big they are" in p5, f"{files5} {p5[-200:]}")
    ck("  the judge is handed the companion's photograph too",
       judged and all(len(c) == 1 for c in judged), str([len(c) for c in judged]))
    ck("  and the set says what the table was laid with",
       "1 of its companions (Faceted Bowl)" in str(got5.get("note", "")), str(got5.get("note", ""))[:200])
    seen2: list = []

    def _ask_cast(kind, content, tenant="", max_tokens=0, **k):
        seen2.append(content)
        return SimpleNamespace(ok=True, text=json.dumps({
            "match": 95, "differences": [], "same_product": True, "lettering": False,
            "invented": False}), degraded="", error="")
    llm.ask = _ask_cast
    creative._compare_product_live(png((1, 2, 3, 255)), [PICS["https://cdn.example/glass-front.png"]],
                                   ["a faceted stem"], "baci", cast=[PICS["https://cdn.example/bowl.png"]])
    imgs = [b for b in seen2[-1] if isinstance(b, dict) and b.get("type") == "image"]
    txt = " ".join(b.get("text", "") for b in seen2[-1] if isinstance(b, dict) and b.get("type") == "text")
    ck("  the live judge sees candidate, product and companion, and is told which is which",
       len(imgs) == 3 and "supporting pieces" in txt
       and "reference images do not show" in " ".join(txt.split()),
       f"{len(imgs)} images")
    kb.add_board("baci", "Table")
    kb.set_board_role(next(a.id for a in kb.assets("baci") if "bowl" in (a.url or "")),
                      "table", "product", True)
    kb.set_board_role(next(a.id for a in kb.assets("baci") if "glass-front" in (a.url or "")),
                      "table", "product", True)
    refs2 = creative.board_inputs("baci", "faceted-glass", boards=("table",))
    ck("a product pinned on the chosen board that is not the product is the cast, by the owner's choice",
       len(refs2["cast"]) == 1 and refs2["cast_names"] == ["Faceted Bowl"] and len(refs2["product"]) == 1)

    print("\n— THE JUDGE IS ASKED THE RIGHT QUESTIONS —")
    asked: list = []

    def _ask(kind, content, tenant="", max_tokens=0, **k):
        asked.append(" ".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"))
        return SimpleNamespace(ok=True, text=json.dumps({
            "match": 70, "differences": ["a plain rim instead of the gold rim"],
            "same_product": False, "lettering": False, "invented": True}), degraded="", error="")
    llm.ask = _ask
    v = creative._compare_product_live(png((1, 2, 3, 255)), [PICS["https://cdn.example/glass-front.png"]],
                                       ["a faceted stem"], "baci")
    ck("the rubric says an almost product is a different product, naming silhouette and embellishment",
       "ALMOST" in asked[-1] and "silhouette" in asked[-1] and "embellishment" in asked[-1]
       and "generalised" in asked[-1], asked[-1][-300:])
    ck("  and asks whether decoration was INVENTED beyond what the references show — the original complaint",
       '"invented"' in asked[-1] and "reference images do not show" in " ".join(asked[-1].split())
       and v.get("invented") is True and v.get("match") == 70, str(v))
    ck("the run summary carries the drop",
       "NOT the product" in web._summarise(got))

    print()
    if _fail:
        print(f"{len(_fail)} FAILED:\n  " + "\n  ".join(_fail))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
