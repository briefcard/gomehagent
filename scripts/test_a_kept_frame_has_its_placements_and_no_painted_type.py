"""A kept frame carries its Meta placements where the owner can see them, and
no candidate with painted type wins.

Owner, 2026-09-07: *"the text and components are not separate layers on
Canva they are burned on — is there a way to layer them so we can adjust as
needed? Also, how do we ensure that final approved assets get created in the
different ratios needed for the meta placements?"*

WHAT WAS TRUE. Nothing in the pipeline sets type into a frame; what the owner
saw was the image MODEL painting lettering and button-like components — most
likely copied from look pins that are finished ads with copy on them. The
review has asked "is the image free of text" since it was written, as ADVICE;
the fidelity judge ranked by product match alone, so a lettered candidate
could be the one kept. And approving a frame has cut its 4:5 and 9:16 crops
since 2026-08-29 — recorded on the frame, moved by the hand-off — and no
surface showed them: not the card, not the export. Meta's placements (read
from the Ads Guide 2026-09-07): Feed 4:5, recommended 1440×1800, minimum
600×750; Reels 9:16, recommended 1440×2560, safe zones 14% top, 35% bottom,
6% each side.

The rules, each with its guard: the judge is asked about LETTERING and a
lettered candidate never beats a clean one; painted lettering is redrawn away
by name; a kept frame's placements are shown on the Pictures page and listed
in the ad export; the board says to pin photographs, not finished ads.

Run: python3 scripts/test_a_kept_frame_has_its_placements_and_no_painted_type.py
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
from types import SimpleNamespace

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'kept.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["PUBLIC_BASE_URL"] = "https://example.test"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image  # noqa: E402

from app import (admin_ui as ui, coherence, creative, db, imagegen, kb,  # noqa: E402
                 kb_seed, llm, tenants, web)

KEY = "s3cret"
_fail: list[str] = []


def ck(label: str, cond, detail: str = "") -> None:
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def png(colour, w: int = 96, h: int = 96) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (w, h), colour).save(buf, format="PNG")
    return buf.getvalue()


PICS = {
    "https://cdn.example/cup-front.png": png((200, 30, 30, 255)),
    "https://cdn.example/look-1.png": png((30, 30, 200, 255)),
}
CANDIDATE: dict = {}


def main() -> int:
    db.init_db()
    tenants.seed()
    kb_seed.seed_all()
    kb.add_entity("baci", "product", "zodiac-cup", "Zodiac Cup",
                  description="a porcelain cup with a hand-painted zodiac sign", origin="human")
    kb.add_asset("baci", "https://cdn.example/cup-front.png", rights=kb.OWNED, title="cup",
                 subject=kb.OBJECT, entity_key="zodiac-cup", origin="human")
    kb.add_asset("baci", "https://cdn.example/look-1.png", rights=kb.OWNED, title="look",
                 subject=kb.SCENE, origin="human")
    kb.add_board("baci", "Lifestyle")
    kb.set_board_role(next(a.id for a in kb.assets("baci") if "look-1" in (a.url or "")),
                      "lifestyle", "look", True)
    creative._fetch = lambda url: PICS.get(url, b"")
    creative.assess = lambda blob, brief, tenant="": {
        "ok": True, "verdicts": [], "overall": "reads right", "failed": [], "fix": ""}
    creative.product_features = lambda tenant, entity_key, product, **k: {
        "ok": True, "features": ["a gold Cancer crab glyph"], "cached": False}
    sent: list = []
    calls = [0]

    def _post(path, *, json_body=None, files=None, data=None):
        sent.append({"path": path, "files": files, "data": data, "json": json_body})
        calls[0] += 1
        n = int((data or {}).get("n") or (json_body or {}).get("n") or 1)
        out = []
        for i in range(n):
            colour = (calls[0] * 9 % 250, i * 40 + 20, calls[0] // 28, 255)
            CANDIDATE[colour[:3]] = (calls[0], i)
            out.append(png(colour))
        return {"ok": True, "images": out}
    imagegen.post = _post

    def _idx(candidate):
        colour = Image.open(io.BytesIO(candidate)).convert("RGB").getpixel((2, 2))
        return CANDIDATE.get(tuple(colour), (0, -1))

    print("— THE JUDGE IS ASKED ABOUT LETTERING, AND A LETTERED CANDIDATE NEVER WINS —")
    seen: list = []

    def _ask(kind, content, tenant="", max_tokens=0, **k):
        seen.append(" ".join(b.get("text", "") for b in content if isinstance(b, dict)
                             and b.get("type") == "text"))
        return SimpleNamespace(ok=True, text=json.dumps({
            "match": 91, "differences": [], "same_product": True, "lettering": True}),
            degraded="", error="")
    llm.ask = _ask
    v = creative._compare_product_live(png((1, 2, 3, 255)), [PICS["https://cdn.example/cup-front.png"]],
                                       ["a gold Cancer crab glyph"], "baci")
    ck("the judge is asked whether the picture carries lettering, logos or components",
       "lettering" in seen[-1].lower() and ("button" in seen[-1].lower() or "component" in seen[-1].lower()),
       seen[-1][-200:])
    ck("  and its verdict carries the answer", v.get("ok") and v.get("lettering") is True, str(v))

    def _judge(candidate, product, features, tenant=""):
        call, i = _idx(candidate)
        if i == 0:      # the best product match — but it has painted type
            return {"ok": True, "match": 96, "differences": [], "same": True,
                    "lettering": True, "why": ""}
        if i == 1:      # clean, slightly lower match
            return {"ok": True, "match": 88, "differences": [], "same": True,
                    "lettering": False, "why": ""}
        return {"ok": True, "match": 60, "differences": ["the glyph is a star"],
                "same": False, "lettering": False, "why": ""}
    creative.compare_product = _judge
    cup = coherence.commit("entity", "zodiac-cup", label="Zodiac Cup")
    got = creative.batch("baci", commitment=cup, entity_key="zodiac-cup", fmt="ad_frame",
                         positioning="the sign you were born under", plates=1, review=True)
    fid = (got["frames"][0].get("fidelity") or {}) if got.get("frames") else {}
    ck("a clean candidate is kept over a better-matching one with painted type",
       got["ok"] and got["made"] == 1 and fid.get("match") == 88 and fid.get("lettering") is False,
       str(fid))

    print("\n— PAINTED LETTERING IS REDRAWN AWAY, BY NAME —")
    sent.clear(); CANDIDATE.clear()

    def _all_lettered(candidate, product, features, tenant=""):
        # the FIRST request's candidates all carry type; the redraw's are clean
        # (keyed on requests seen, not on the running image counter)
        if len(sent) == 1:
            return {"ok": True, "match": 92, "differences": [], "same": True,
                    "lettering": True, "why": ""}
        return {"ok": True, "match": 90, "differences": [], "same": True,
                "lettering": False, "why": ""}
    creative.compare_product = _all_lettered
    got2 = creative.batch("baci", commitment=cup, entity_key="zodiac-cup", fmt="ad_frame",
                          positioning="the sign you were born under", plates=1, review=False)
    edits = [c for c in sent if c["path"] == "/images/edits"]
    ck("when every candidate carries type, ONE redraft asks for it to be removed, by name",
       len(edits) == 2 and "REMOVE" in edits[1]["data"]["prompt"]
       and "lettering" in edits[1]["data"]["prompt"].lower(), f"{len(edits)} request(s)")
    fid2 = (got2["frames"][0].get("fidelity") or {}) if got2.get("frames") else {}
    ck("  and the clean redraw is the one kept",
       fid2.get("lettering") is False and fid2.get("redrafted") is True, str(fid2))
    ck("  the reference rule says a pin's own text is not part of the look",
       "text" in imagegen._THE_LOOK.lower() and ("logo" in imagegen._THE_LOOK.lower()
                                                  or "button" in imagegen._THE_LOOK.lower()))

    print("\n— A KEPT FRAME HAS ITS PLACEMENTS, WHERE THE OWNER CAN SEE THEM —")
    frame_id = got["frames"][0]["asset_id"]
    # the frame is for an ad variant: tag it as the route would
    with db.SessionLocal() as s:
        row = s.get(db.KbAsset, frame_id)
        row.tags = list(row.tags or []) + ["output:out-1"]
        s.commit()
    kb.review_asset(frame_id, approve=True, rights="owned")
    cut = creative.placements("baci", frame_id)
    ck("approving cuts the 4:5 and 9:16 placements onto the frame",
       cut.get("ok") and set((cut.get("cut") or {}).keys()) >= {"4:5", "9:16"}, str(cut)[:160])
    page = ui.render_content(KEY, tenant="baci", sub="pictures")
    ck("the Pictures page shows the kept frame with its placements and Meta's sizes for them",
       "Kept frames" in page and "4:5" in page and "9:16" in page and "1080" in page
       and "1440&times;1800" in page and "1440&times;2560" in page, "")
    lines = web._variant_frames("baci", "out-1")
    ck("  and the ad export lists each frame's placements under it",
       any("4:5" in ln and "9:16" in " ".join(lines) for ln in lines)
       and any("1080" in ln for ln in lines), "\n".join(lines)[:300])
    ck("  naming Meta's placements they are for",
       "Feed" in page and ("Reels" in page or "Stories" in page), "")

    print("\n— THE BOARD SAYS WHAT TO PIN —")
    # The boards card lives on the Brand tab since 2026-09-07 (owner: they
    # shape every system's pictures, not one run's).
    brand_page = ui.render_brand(KEY, tenant="baci")
    ck("the boards card warns that copy on a pin is copied into the frame",
       "finished ads" in brand_page or "copy on a pin" in brand_page, "")

    print()
    if _fail:
        print(f"{len(_fail)} FAILED:\n  " + "\n  ".join(_fail))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
