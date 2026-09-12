"""The reader has eyes: a reference is read into its whole design from
strips the reviewer can actually see, in three passes, in the schema's own
words — and never a word of the reference's copy.

INITIATIVE-email-design.md, Phase 3. The first reader sent the gallery
screenshot whole, so a 680×4543 email reached the reviewer at 235×1568 —
body type under five pixels — and the prompt then said "never a colour, a
typeface". This one:

  1. CUTS STRIPS to the reviewer's tier, overlapping, every one marked to be
     REFUSED rather than downscaled; a contact sheet for the whole.
  2. ASKS IN THE SCHEMA'S WORDS: every field of every global group, every
     SECTION field, every slot — derived, so the prompt cannot name a field
     the validator does not know, nor omit one it does.
  3. STITCHES the strips: a section cut by a strip edge is one section.
  4. CRITIQUES ONCE and applies the patch; what the patch says that the
     vocabulary does not hold is dropped and said.
  5. REFUSES the reference's copy in the notes, a reading with no sections,
     a request over twenty images, and a pass that did not run — each by
     name.
  6. DERIVES the old look for the live renderer, the library's sequence,
     and reads the phone render when the gallery serves one.
  7. FILES it proposed, with the read on the structure and on the card.

    python3 scripts/test_the_reader_has_eyes.py
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'eyes.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import (admin_ui, config, db, email_design as ed, email_render as er,  # noqa: E402
                 email_structures as es, kb, llm, tenants)

_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _png(w: int, h: int, colour: str = "#f4f1ea") -> bytes:
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (w, h), colour)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, w, h // 6], fill="#1e2a44")
    for y in range(h // 6 + 40, h - 40, 34):
        d.rectangle([40, y, w - 40, y + 14], fill="#7a746b")
    b = io.BytesIO(); im.save(b, format="PNG")
    return b.getvalue()


def _size(block: dict):
    from PIL import Image
    return Image.open(io.BytesIO(base64.b64decode(block["source"]["data"]))).size


def main() -> int:
    db.init_db()
    tenants.seed()
    kb.ensure_brand("baci", "Baci")
    model = config.CREATIVE_REVIEW_MODEL
    tier, edge = ed._tier_edge()

    print(f"— 1. strips cut to the reviewer's tier ({model!r}: {tier}, {edge} px) —")
    parts = ed.strips(_png(680, 4543), edge)
    ck("a 680×4543 screenshot is several strips, none taller than the edge",
       len(parts) >= 3 and all(p["height"] <= edge for p in parts), str([(p["top"], p["bottom"]) for p in parts]))
    ck("consecutive strips overlap by the overlap, and together cover the whole",
       all(parts[i + 1]["top"] == parts[i]["bottom"] - ed.STRIP_OVERLAP for i in range(len(parts) - 1))
       and parts[0]["top"] == 0 and parts[-1]["bottom"] == 4543)
    ck("every strip is seen as sent — it fits the tier",
       all(llm.image_fits(model, p["width"], p["height"]) for p in parts))
    ck("a short picture is one strip; a wide one is narrowed to the edge first",
       len(ed.strips(_png(680, 900), edge)) == 1
       and ed.strips(_png(2400, 600), edge)[0]["width"] == edge)
    ck("the high-resolution tier needs fewer strips for the same picture",
       len(ed.strips(_png(680, 4543), llm.IMAGE_TIERS["high"]["max_edge"])) < len(parts))
    sheet = ed.contact_sheet(_png(680, 4543), edge)
    from PIL import Image
    sw, sh = Image.open(io.BytesIO(sheet)).size
    ck("the contact sheet is the whole email at a size the tier holds",
       llm.image_fits(model, sw, sh) and sh <= edge and abs(sw / sh - 680 / 4543) < 0.01, f"{sw}×{sh}")
    blk = ed._image_block(parts[0]["png"])
    ck("every image block carries the refusal switch — refused, never downscaled",
       blk.get("transformations") == llm.OVERSIZED_IMAGE_ERROR == {"oversized_image": "error"})

    print("\n— 2. the prompts are the schema —")
    pa, pb = ed.prompt_global(True), ed.prompt_strip(2, 3, 1448, 3016, 4543)
    ck("pass A names every field of every global group, with its values",
       all(f'"{n}"' in pa and all(str(v) in pa for v in f.values if isinstance(v, str))
           for g in ed.SCHEMA for n, f in ed.SCHEMA[g].items())
       and set(ed._GLOBAL_GROUPS) == set(ed.SCHEMA))
    named_a = set(re.findall(r'^\s+"([a-z_]+)":', pa, re.M))
    known = {n for g in ed.SCHEMA for n in ed.SCHEMA[g]} | set(ed.SCHEMA) | {"notes"}
    ck("and nothing outside the schema — a field the validator would drop is never asked for",
       named_a and named_a <= known, str(named_a - known))
    ck("pass B names every SECTION field, every kind, every slot, and which strip it is",
       all(f'"{n}"' in pb for n in ed.SECTION) and all(k in pb for k in ed.KINDS)
       and all(s in pb for s in ed.SLOTS) and "strip 2 of 3" in pb and "1448–3016" in pb)
    ck("the phone render is announced only when there is one",
       "Image 3 is the same email as rendered on a phone" in pa
       and "Image 3" not in ed.prompt_global(False))
    pc = ed.prompt_critique(ed.normalize({"sections": [{"kind": "hero", "slots": ["headline"]}]})[0], 3)
    ck("pass C shows the design as read and asks for a patch, never copy or colour",
       "Images 1–3" in pc and '"sections"' in pc and "JSON patch" in pc and "never a colour" in pc
       and '"defaults"' not in pc)
    ck("neither prompt asks for the arrangement only, nor forbids the type",
       "arrangement only" not in pa + pb and "never a colour, a typeface" not in pa + pb)

    print("\n— 3. stitching —")
    st = ed.stitch([[{"kind": "hero", "slots": ["headline"]}, {"kind": "intro", "slots": ["headline"]}],
                    [{"kind": "intro", "continued": True, "slots": ["headline", "body"]},
                     {"kind": "products", "slots": ["products:3"]}],
                    [{"kind": "closing", "continued": False, "slots": ["cta"]}]])
    ck("a section cut by a strip edge is one section, its slots the union in order",
       [s["kind"] for s in st] == ["hero", "intro", "products", "closing"]
       and st[1]["slots"] == ["headline", "body"] and "continued" not in st[1], str(st))
    ck("a first strip's first section is never merged into nothing",
       [s["kind"] for s in ed.stitch([[{"kind": "intro", "continued": True}]])] == ["intro"])

    print("\n— 4. the critique, applied once —")
    base, _ = ed.normalize({"type": {"heading_case": "sentence"},
                            "sections": [{"kind": "hero", "bg": "surface", "slots": ["headline"]},
                                         {"kind": "products", "slots": ["products:2"]}]})
    patched, drops = ed.apply_patch(base, {"type": {"heading_case": "upper", "display_family": "Didot"},
                                           "sections": [{"index": 0, "bg": "dark"},
                                                        {"index": 9, "bg": "dark"}, "junk"]})
    ck("a global field and a section by index are corrected; an index off the end is ignored",
       patched["type"]["heading_case"] == "upper" and patched["sections"][0]["bg"] == "dark"
       and patched["sections"][1]["bg"] == "surface")
    ck("what the patch says that the vocabulary does not hold is dropped and said",
       any("'Didot'" in d for d in drops) and patched["type"]["display_family"] == base["type"]["display_family"])
    ck("an empty patch changes nothing", ed.apply_patch(base, {}) == (base, []))

    print("\n— 5. refusals, by name —")
    ck("three or more words in quotation marks are the reference's copy",
       ed.quoted_copy('Opens with "Summer is finally here" and asks late') == "Summer is finally here"
       and ed.quoted_copy("uses a 'wide' measure") == "" and ed.quoted_copy("") == "")

    print("\n— 6. the old look, the sequence, the phone render —")
    dsg, _ = ed.normalize({"type": {"scale": "poster", "leading": "airy"}, "cta": {"style": "arrow"},
                           "sections": [{"kind": "hero", "layout": "overlay", "text_on_image": True},
                                        {"kind": "feature", "bg": "page"},
                                        {"kind": "products", "layout": "grid2"}]})
    lk = ed.look_of_design(dsg)
    ck("the live renderer's look is derived: overlay hero, display scale, airy, bands, a link ask, a grid",
       lk == {"hero": "overlay", "scale": "display", "density": "airy", "bands": True,
              "cta": "link", "products": "grid2"}, str(lk))
    ck("split, bleed, contained, pill and full read as themselves; the house reads as the house",
       ed.look_of_design(ed.normalize({"sections": [{"kind": "hero", "layout": "split-right"}],
                                       "cta": {"radius": "pill"}})[0])["hero"] == "split"
       and ed.look_of_design(ed.normalize({"sections": [{"kind": "hero", "image": "bleed"}]})[0])["hero"] == "bleed"
       and ed.look_of_design(ed.normalize({"cta": {"style": "full"}})[0])["cta"] == "full"
       and ed.look_of_design(ed.house()) == er._LOOK_DEFAULT)
    ck("the library's sequence falls back to the kinds when a reading named no slots",
       ed.sequence_for_library(ed.normalize({"sections": [{"kind": "hero"}, {"kind": "offer"}]})[0])
       == ["hero", "heading", "text", "cta"])
    ck("the phone render's address follows the gallery's pattern, and only that pattern",
       ed.mobile_url("https://cdn.rge/emails/slug-one.png") == "https://cdn.rge/emails/mobile/slug-one.png"
       and ed.mobile_url("https://cdn.rge/other/slug.png") == "" and ed.mobile_url("") == "")

    print("\n— 7. a reading, end to end, filed and on the card —")
    class _R:
        def __init__(self, text="", content=b"", status=200):
            self.text, self.content, self.status_code = text, content, status
            self.headers = {}
    page = ('<html><head><title>Editorial gallery email</title>'
            '<meta property="og:image" content="https://cdn.rge/emails/editorial.png">'
            '<meta property="og:title" content="An editorial gallery email"></head></html>')
    shot, phone = _png(680, 3000), _png(375, 3254, "#ffffff")
    sent: list = []
    A = {"frame": {"container": "flat", "width": 640}, "header": {"logo": "center", "nav": "below"},
         "type": {"display_family": "serif-display", "scale": "poster", "heading_case": "upper",
                  "tracking": "wide", "kicker": "rule", "display_font": "Canela", "accent": "#b8302f"},
         "palette": {"mood": "dark", "accent_use": ["buttons", "type"]},
         "cta": {"style": "outline", "radius": "square", "case": "upper"},
         "dividers": {"style": "thick"}, "footer": {"bg": "dark", "socials": "icons"},
         "imagery": {"hero": "portrait", "product": "packshot-on-colour"},
         "fits_intents": ["story", "offer"], "fits_formats": ["designed"],
         "notes": 'A poster headline over the picture; the ask arrives late. Opens with "Summer is finally here".'}
    B = {1: {"sections": [{"kind": "hero", "layout": "overlay", "bg": "dark", "image": "bleed",
                           "aspect": "portrait", "text_on_image": True,
                           "slots": ["kicker", "headline", "image:1"]},
                          {"kind": "editorial", "layout": "columns", "bg": "surface", "slots": ["headline"]}]},
         2: {"sections": [{"kind": "editorial", "continued": True, "layout": "columns", "bg": "surface",
                           "slots": ["headline", "body", "body"]},
                          {"kind": "products", "layout": "grid2", "bg": "tint", "slots": ["products:4"]},
                          {"kind": "closing", "layout": "band", "bg": "accent", "slots": ["cta"]}]}}
    C = {"type": {"heading_case": "title"}, "sections": [{"index": 1, "bg": "page"}],
         "notes": "A poster headline over the picture; two columns of editorial; the ask on a band."}

    class _Reply:
        ok = True
        def __init__(self, text): self.text = text

    def _ask(purpose, blocks, **k):
        sent.append(blocks)
        text = next((b["text"] for b in reversed(blocks) if b.get("type") == "text"), "")
        if "JSON patch" in text:
            return _Reply(json.dumps(C))
        m = re.search(r"strip (\d+) of (\d+)", text)
        if m:
            return _Reply(json.dumps(B.get(int(m.group(1)), {"sections": []})))
        return _Reply(json.dumps(A))
    real_get, real_ask = es.httpx.get, llm.ask
    es.httpx.get = lambda url, **k: (_R(page) if "reallygoodemails" in url
                                     else _R(content=phone) if "/mobile/" in url
                                     else _R(content=shot))
    llm.ask = _ask
    try:
        sw = es.add_swipe("https://reallygoodemails.com/emails/an-editorial-gallery-email")
        rd = es.read_swipe(sw["asset_id"])
        ck("the reading lands as a proposed structure carrying its design", rd.get("ok") and rd["review"] == "proposed", str(rd)[:120])
        row = next(r for r in es.library() if r["id"] == rd["id"])
        d, info = row["design"], row["profile"].get("read") or {}
        ck("pass A's global design lands — frame, header, type, palette, ask, footer, imagery",
           d["frame"]["container"] == "flat" and d["frame"]["width"] == 640 and d["header"]["logo"] == "center"
           and d["type"]["scale"] == "poster" and d["type"]["kicker"] == "rule" and d["palette"]["mood"] == "dark"
           and d["palette"]["accent_use"] == ["buttons", "type"] and d["cta"]["style"] == "outline"
           and d["footer"]["socials"] == "icons" and d["imagery"]["product"] == "packshot-on-colour")
        ck("the strips' sections are stitched in order, the cut one once",
           [s["kind"] for s in d["sections"]] == ["hero", "editorial", "products", "closing"]
           and d["sections"][1]["slots"] == ["headline", "body"]
           and d["sections"][2]["slots"] == ["products:4"] and d["sections"][3]["bg"] == "accent")
        ck("the critique's patch is applied once — a field, a section, the notes",
           d["type"]["heading_case"] == "title" and d["sections"][1]["bg"] == "page"
           and info.get("critiqued") is True and "two columns of editorial" in row["profile"]["notes"])
        ck("what the reading volunteered outside the vocabulary is dropped and said on the structure",
           "Canela" not in json.dumps(d) and "#b8302f" not in json.dumps(d)
           and any("display_font" in x for x in info["dropped"]) and any("never names a colour" in x for x in info["dropped"]))
        ck("the reference's own copy never reaches the notes — the critique's clean notes stand",
           "Summer is finally here" not in json.dumps(row["profile"]))
        ck("the read is on the structure: tier, strips, calls, the phone render, the critique",
           info["tier"] == tier and info["strips"] == len(ed.strips(shot, edge)) and info["mobile"] is True
           and info["calls"] == info["strips"] + 2, str(info))
        ck("pass A saw the contact sheet, the top strip and the phone render; every image fits the tier",
           sum(1 for b in sent[0] if b.get("type") == "image") == 3
           and all(llm.image_fits(model, *_size(b)) for blocks in sent for b in blocks if b.get("type") == "image"))
        ck("the live renderer's look and the library's sequence are derived from the design",
           row["profile"]["look"]["hero"] == "overlay" and row["profile"]["look"]["cta"] == "block"
           and row["profile"]["look"]["scale"] == "display" and row["profile"]["look"]["bands"] is True
           and row["sequence"][0] == "hero" and "products" in row["sequence"], str(row["profile"]["look"]))
        ck("the structure is named by what it does — never by the gallery page's title, which is the "
           "email's own headline and brand",
           "gallery" not in row["name"].lower() and "editorial" not in row["name"].lower()
           and row["name"].startswith("dark key;"), row["name"])
        ck("fits and the source ride along",
           set(row["fits_intents"]) == {"story", "offer"} and row["fits_formats"] == ["designed"]
           and row["source_url"].endswith("/emails/an-editorial-gallery-email"))
        card = admin_ui._structures_card("s3cret", "baci")
        ck("the card says the design, the read, the drops, the sections and offers Read its design",
           "design: dark key" in card and f"read in {info['calls']} calls from {info['strips']} strip(s)" in card
           and "with the phone render" in card and "critiqued once" in card
           and "the vocabulary does not hold" in card and "products · grid2 on tint" in card
           and "Read its design" in card)
        # The token preview is gone from the card (2026-09-12): the recreation
        # leads, the token reading folds away under it, and the reference is
        # shown beside OURS — `test_the_model_makes_the_email` covers that.
        from app import brand_theme as _bt
        _bt.approve("baci", {"footer.address": "1 Main St", "palette.dark": "#0b1a0f"})
        card2 = admin_ui._structures_card("s3cret", "baci")
        ck("the recreation leads the card and the token reading folds away under it",
           "not yet recreated for this brand" in card2 and "the token reading" in card2
           and "srcdoc=" not in card2 and card2.index("Recreate again") < card2.index("Read its design"))
        # The quoted-copy gate, exercised: a critique with no notes leaves
        # pass A's, which quote three words of the email — dropped, and said.
        C_no_notes = {k: v for k, v in C.items() if k != "notes"}
        llm.ask = lambda p, blocks, **k: (_Reply(json.dumps(C_no_notes)) if "JSON patch" in (blocks[-1].get("text") or "")
                                          else _ask(p, blocks, **k))
        rq = ed.read(sw["asset_id"])
        rrow = next(r for r in es.library() if r["id"] == rq["id"])
        ck("notes that quote three words of the email are dropped, and the drop says so",
           rq.get("ok") and "Summer" not in (rrow["profile"].get("notes") or "")
           and any("quoted the email's own copy" in x for x in rq["read"]["dropped"]), str(rq["read"]["dropped"])[-160:])
        llm.ask = _ask
        # Refusals, through the same reader.
        sent.clear()
        es.httpx.get = lambda url, **k: (_R(page) if "reallygoodemails" in url
                                         else _R(status=404) if "/mobile/" in url else _R(content=shot))
        llm.ask = lambda p, blocks, **k: _Reply(json.dumps({"sections": []})) if "strip " in (blocks[-1].get("text") or "") else _Reply(json.dumps(A))
        no = ed.read(sw["asset_id"])
        ck("a reading that finds no sections is refused by name", not no.get("ok") and "found no sections" in no["why"], no.get("why", ""))
        class _Bad:
            ok = False
            error = "overloaded"
        llm.ask = lambda *a, **k: _Bad()
        bad = ed.read(sw["asset_id"])
        ck("a pass that did not run refuses with the model's own error", not bad.get("ok") and bad["why"] == "overloaded")
        llm.ask = _ask
        real_max = ed.MAX_IMAGE_BLOCKS
        ed.MAX_IMAGE_BLOCKS = 1
        try:
            over = ed.read(sw["asset_id"])
        finally:
            ed.MAX_IMAGE_BLOCKS = real_max
        ck("a request over the image limit is refused before it is sent", not over.get("ok") and "over 1" in over["why"])
        again = ed.read(sw["asset_id"])
        ck("a phone render the gallery does not serve is skipped and said",
           again.get("ok") and again["read"]["mobile"] is False)
    finally:
        es.httpx.get, llm.ask = real_get, real_ask

    print("\n" + ("ALL PASSED" if not _fail else f"{len(_fail)} FAILED: {_fail}"))
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
