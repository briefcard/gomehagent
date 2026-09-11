"""Content fits the design: the drafter is briefed on the design's slots with
the limits its type imposes; the picture slots are filled from the brand's
own library by kind and aspect, and every slot nothing fills is named; the
library keeps the design an approved send was built on.

INITIATIVE-email-design.md, Phase 5 (and the seam of Phase 6, checked in
the structure and ledger suites).

  1. THE BRIEF: sections in order, slots with limits, the headline's word
     budget by scale, never copy; nothing for a design with no order.
  2. THE FILLER: a hero without a picture takes the brand's; a section
     with a picture slot takes one of the right kind, cut to its aspect;
     the k-th section of a kind takes the k-th picture; a reference pin
     never; a miss is named and the section keeps its words; a picture is
     added, never a word.
  3. THE PAINTER: a picture block is drawn as the section says; split
     puts it beside the words, collage two across; a hero keeps its own.
  4. THE LIBRARY: an approved send files the design it was built on.

    python3 scripts/test_content_fits_the_design.py
"""
from __future__ import annotations

import os
import re
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'fit.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, email_design as ed, email_render as er, email_structures as es, kb, tenants  # noqa: E402

_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


THEME = {"name": "Brand", "footer": {"address": "1 Main St", "brand": "Brand"}}
CDN = "https://cdn.shopify.com/s/files/1/0001/"


def main() -> int:
    db.init_db()
    tenants.seed()
    kb.ensure_brand("baci", "Baci")

    print("— 1. the brief —")
    d, _ = ed.normalize({"type": {"scale": "poster", "heading_case": "upper"}, "cta": {"style": "outline"},
                         "sections": [{"kind": "hero", "layout": "overlay", "bg": "dark", "slots": ["kicker", "headline", "image:1"]},
                                      {"kind": "feature", "layout": "split-left", "bg": "surface", "slots": ["headline", "body", "image:1"]},
                                      {"kind": "products", "layout": "grid3", "bg": "tint", "slots": ["products:3"]},
                                      {"kind": "proof", "bg": "page", "slots": ["quote"]},
                                      {"kind": "closing", "bg": "surface", "slots": ["cta"]}]})
    b = ed.brief(d)
    ck("the sections are briefed in order, each with where it sits",
       b.index("1. hero — overlay on the dark") < b.index("2. feature — split-left on the surface")
       < b.index("3. products — grid3 on the tint") < b.index("5. closing"))
    ck("every slot carries its limit: the headline's by scale and case, the kicker's, the body's, the proof's",
       "at most 4 words (poster scale, set in capitals)" in b and "headline (≤4 words)" in b
       and "kicker (at most 3 words)" in b and "body (40–90 words)" in b
       and "APPROVED claim, verbatim, or leave the slot" in b and "products ×3" in b)
    ck("a picture slot is the brand's to fill — the drafter writes its alt line only",
       "picture ×1 — from the brand's own library; you write its alt line only" in b)
    ck("the ask's style is said; the brief never carries copy",
       "outline button" in b and not re.search(r'"[A-Z][^"]{10,}"', b))
    ck("a design with no order briefs nothing — the drafter composes as before",
       ed.brief(ed.house()) == "")
    st = {"name": "x", "sequence": ["hero", "text"], "profile": {"notes": "The picture carries the opening."},
          "design": d}
    ck("a structure with a design is briefed by the design, with its notes beneath",
       "THE DESIGN THIS SEND IS BUILT ON" in es.brief(st) and "carries the opening" in es.brief(st))
    ck("a structure with the house design keeps the old brief — order and shape",
       "Compose the blocks in THIS order" in es.brief({"name": "h", "sequence": ["hero", "text"],
                                                       "profile": {"hero_first": True}, "design": ed.house()}))

    print("\n— 2. the filler —")
    kb.add_asset("baci", CDN + "life1.jpg", rights=kb.OWNED, subject="photo", title="the table", origin="human")
    kb.add_asset("baci", CDN + "life2.jpg", rights=kb.OWNED, subject="photo", title="the lunch", origin="human")
    kb.add_asset("baci", CDN + "pack.jpg", rights=kb.OWNED, subject="object", tags=["store-image:1", "packshot"], origin="store_sync")
    kb.add_asset("baci", CDN + "ref.jpg", rights=kb.REFERENCE, subject="scene", origin="pinterest")
    blocks = [{"type": "hero", "headline": "Head", "sub": "Sub"},
              {"type": "heading", "text": "Feature"}, {"type": "text", "html": "<p>Words.</p>"},
              {"type": "products", "items": [{"name": "A", "url": "#", "image": CDN + "a.jpg"}]},
              {"type": "quote", "text": "Q"}, {"type": "cta", "label": "Go", "url": "#"}]
    filled, rep = ed.fill("baci", d, blocks)
    ck("a hero without a picture takes the brand's own — the kind the design names for a hero",
       filled[0]["type"] == "hero" and "life" in filled[0]["image"] and rep["filled"] >= 1)
    imgs = [x for x in filled if x.get("type") == "image"]
    ck("the feature section's picture slot takes the other lifestyle picture, as a picture block before its words "
       "— the drafter's run of words and the reader's 'feature' meet as one family",
       len(imgs) == 1 and "life" in imgs[0]["image"] and imgs[0]["image"] != filled[0]["image"]
       and filled.index(imgs[0]) < filled.index(next(x for x in filled if x.get("type") == "text")))
    ck("a reference pin never fills a slot; a picture used once is not used twice",
       not any("ref.jpg" in (x.get("image") or "") for x in filled)
       and len({x.get("image") for x in filled if x.get("type") in ("hero", "image")}) == 2)
    ck("the drafter's words are untouched — a picture is added, never a word",
       [x for x in filled if x.get("type") not in ("image",)] == [{**blocks[0], "image": filled[0]["image"], "alt": filled[0]["alt"]}] + blocks[1:])
    ck("nothing missed, nothing to say", rep["missed"] == [] and rep["notes"] == [])
    dd, _ = ed.normalize({"imagery": {"feature": "texture"},
                          "sections": [{"kind": "hero", "slots": ["headline"]},
                                       {"kind": "intro", "slots": ["body", "image:2"]}]})
    notes = []
    filled2, rep2 = ed.fill("baci", dd, blocks, note=notes.append)
    ck("a slot nothing fits is named with its fix, on the run, and the section keeps its words",
       rep2["missed"] and "2 of 2 picture(s) for the intro section (texture)" in rep2["missed"][0]
       and "file a surface photograph" in rep2["missed"][0]
       and any(n.startswith("design slot not filled") for n in notes)
       and [x for x in filled2 if x.get("type") == "text"])
    ck("a design with no order fills nothing and says nothing",
       ed.fill("baci", ed.house(), blocks) == (blocks, {"filled": 0, "missed": [], "notes": []}))
    hero_kept = ed.fill("baci", d, [{"type": "hero", "image": CDN + "own.jpg", "headline": "H"}])[0][0]
    ck("a hero that already carries a picture keeps it", hero_kept["image"].endswith("own.jpg"))

    print("\n— 3. the painter —")
    html = er.render_design(d, THEME, filled)
    ck("the feature's picture is beside its words — the split layout, the picture on the left",
       'width="50%"' not in html and html.count('valign="top"><table') >= 1
       and html.index(imgs[0]["image"].rsplit("/", 1)[1].rsplit(".", 1)[0]) < html.index("Words."))
    right, _ = ed.normalize({"sections": [{"kind": "hero", "slots": ["headline"]},
                                          {"kind": "feature", "layout": "split-right", "slots": ["body", "image:1"]}]})
    h2 = er.render_design(right, THEME, ed.fill("baci", right, blocks)[0])
    ck("split-right puts the words first", h2.index("Words.") < h2.index("life"))
    coll, _ = ed.normalize({"sections": [{"kind": "hero", "slots": ["headline"]},
                                         {"kind": "feature", "layout": "collage", "slots": ["image:2", "body"]}]})
    h3 = er.render_design(coll, THEME, ed.fill("baci", coll, blocks)[0])
    ck("collage sets two pictures across, square, then the words",
       h3.count("_crop_center") >= 2 and h3.index("life1") < h3.index("Words.") and "life2" in h3)
    ck("a picture block carries live alt text and is cut to the slot's aspect through the CDN",
       ('alt="the lunch"' in html or 'alt="the table"' in html) and re.search(r"life\d_\d+x\d+_crop_center", html))
    ck("the picture block is in the renderer's vocabulary, so a structure may name a section that carries one",
       "image" in er._BLOCKS and "image" in es.block_types())

    print("\n— 4. the library —")
    with db.SessionLocal() as s:
        s.add(db.Output(id="out-d", tenant="baci", system_key="campaign_email",
                        shape=["hero", "heading", "text", "cta"], angle="offer", theme="designed"))
        s.add(db.ArtifactBody(output_id="out-d", tenant="baci", body="<p>x</p>",
                              meta={"design": d, "structure_id": "abc"}))
        s.commit()
    got = es.file_from_output("out-d")
    row = next(r for r in es.library() if r["id"] == got["id"])
    ck("an approved send files the design it was built on, with its shape, approved",
       got["ok"] and row["review"] == "approved" and row["design"]["type"]["scale"] == "poster"
       and [x["kind"] for x in row["design"]["sections"]][:2] == ["hero", "feature"])
    with db.SessionLocal() as s:
        s.add(db.Output(id="out-h", tenant="baci", system_key="campaign_email",
                        shape=["heading", "text", "cta"], angle="story", theme="letter"))
        s.commit()
    got2 = es.file_from_output("out-h")
    row2 = next(r for r in es.library() if r["id"] == got2["id"])
    ck("a send with no design on record files the house design",
       got2["ok"] and row2["design"]["sections"] == [] and ed.complete(row2["design"]))

    print("\n" + ("ALL PASSED" if not _fail else f"{len(_fail)} FAILED: {_fail}"))
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
