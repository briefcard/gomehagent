"""A design is executed: every value in the vocabulary is drawn, every colour
comes through the brand's palette, one design is two emails for two brands,
and CAN-SPAM survives every one.

INITIATIVE-email-design.md, Phase 4. `render` painted one email; this proves
`render_design` paints what a design says — walked from the schema, never
listed, so a field added tomorrow is checked the moment it exists.

  1. EVERY VALUE IS DRAWN: for every field the schema names (bar the ones
     `NOT_DRAWN_YET` names, by phase), every value renders and DIFFERS from
     the default's output while keeping the copy and the footer.
  2. COLOURS ONLY THROUGH THE PALETTE: every hex in every render is a role
     of the brand's palette or the renderer's own mix of two of them; a
     ground takes its own ink (light on dark, dark on light).
  3. ONE DESIGN, TWO BRANDS: the same design through two palettes is two
     emails with the same words and the same structure and different colours.
  4. THE FACES: the brand's own wins; the class chooses only when there is
     none; a Google face is linked only when a class chose it.
  5. SECTIONS: the drafter's blocks grouped by the rules; a concrete order
     reaches its kinds in sequence; a layout nothing draws falls to stack.
  6. CAN-SPAM in every design; live text under every picture.

    python3 scripts/test_a_design_is_executed.py
"""
from __future__ import annotations

import os
import re
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'x.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import email_design as ed, email_render as er, palette as P  # noqa: E402

_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


CDN = "https://cdn.shopify.com/s/files/1/0001/"
THEME = {"name": "Brand A", "logo_url": "https://x/logo.png",
         "colors": {"accent": "#b8302f", "text": "#1c1a17", "bg": "#f1ede6", "surface": "#ffffff"},
         "palette": {"page": "#f1ede6", "surface": "#ffffff", "ink": "#1c1a17", "muted": "#7a746b",
                     "accent": "#b8302f", "accent_ink": "#ffffff", "dark": "#1e2a44", "dark_ink": "#f3efe8",
                     "tint": "#f6e9e3", "tint_ink": "#1c1a17", "border": "#e3ddd3", "secondary": "#c9b8a3"},
         "nav": [{"label": "New", "url": "https://x/new"}, {"label": "Gifts", "url": "https://x/gifts"}],
         "footer": {"address": "100 Example Ave, Miami FL", "brand": "Brand A",
                    "socials": [{"name": "Instagram", "url": "https://instagram.com/a"}]}}
THEME_B = {**THEME, "name": "Brand B",
           "palette": {"page": "#eef1ec", "surface": "#fbfcf9", "ink": "#15201a", "muted": "#6d7b72",
                       "accent": "#c98a1e", "accent_ink": "#1a1508", "dark": "#173b2c", "dark_ink": "#edf3ec",
                       "tint": "#e5eee6", "tint_ink": "#15201a", "border": "#d9e0d9", "secondary": "#8aa38f"}}
BLOCKS = [{"type": "hero", "image": CDN + "hero.jpg", "alt": "the table", "headline": "Head", "sub": "Sub"},
          {"type": "heading", "text": "Kicker"},
          {"type": "text", "html": "<p>Body copy one.</p>"},
          {"type": "text", "html": "<p>Body copy two.</p>"},
          {"type": "list", "items": ["one", "two"]},
          {"type": "divider"},
          {"type": "products", "items": [{"name": "Plate", "url": "https://x/a", "image": CDN + "a.jpg", "price": "$45"},
                                         {"name": "Bowl", "url": "https://x/b", "image": CDN + "b.jpg", "price": "$38"},
                                         {"name": "Mug", "url": "https://x/c", "image": CDN + "c.jpg", "price": "$28"}]},
          {"type": "quote", "text": "Placed at the Four Seasons.", "attribution": "claim"},
          {"type": "banner", "text": "One line on a band"},
          {"type": "heading", "text": "More"},
          {"type": "text", "html": "<p>Closing copy.</p>"},
          {"type": "cta", "label": "Go", "url": "https://x/go"},
          {"type": "signature", "text": "Warmly,", "name": "Gomeh", "role": "Founder"},
          {"type": "ps", "text": "P.S. line"}]
HEX = re.compile(r"(?<![&\w])#[0-9a-fA-F]{3,6}\b")   # not an entity like &#10022;

#: The kind of section each SECTION field is exercised on — the one whose
#: painter draws it; a layout on the kind that takes it.
_KIND_FOR_LAYOUT = {"overlay": "hero", "split-left": "hero", "split-right": "hero",
                    "grid2": "products", "grid3": "products", "collage": "products",
                    "columns": "intro", "band": "offer", "letter": "intro", "stack": "intro"}


def _design_with(group: str, name: str, value):
    """A design that differs from the default in ONE field."""
    raw: dict = {}
    if group == "section":
        kind = _KIND_FOR_LAYOUT.get(value, "hero") if name == "layout" else (
            "hero" if name in ("image", "aspect", "text_on_image") else "intro")
        raw["sections"] = [{"kind": kind, name: value}]
    else:
        raw[group] = {name: value}
    d, dropped = ed.normalize(raw)
    assert not dropped, (group, name, value, dropped)
    return d


def _allowed(theme: dict) -> set[str]:
    pal = er._theme(theme)["palette"]
    out = {v.lower() for v in pal.values()}
    for role in ed.GROUNDS:
        out |= {v.lower() for v in er._ground_colors(pal, role).values()}
    return out | {"#ffffff", "#000000", "#c0392b"}      # the scrim's ends; the no-address warning


def main() -> int:
    base = er.render_design(ed.house(), THEME, BLOCKS)
    ck("the house design renders the copy, the products, the ask and the legal footer",
       all(x in base for x in ("Head", "Body copy one", "Plate", ">Go<", er.UNSUB, "100 Example Ave")))

    print("— 1. every value is drawn —")
    walked, skipped, same, lost = 0, [], [], []
    readers = ed.readers()
    filler_fields = [(g, n) for (g, n), by in readers.items() if by == "filler"]
    for group, name, values, default, _meaning in ed.fields():
        key = f"{group}.{name}"
        if key in er.NOT_DRAWN_YET:
            skipped.append(key)
            continue
        if readers.get((group, name)) == "filler":
            continue                 # read by the filler; walked below with the filler
        for v in values:
            if isinstance(default, list):
                if v in default:
                    continue
                v_ = [v]
            else:
                if v == default:
                    continue
                v_ = v
            walked += 1
            out = er.render_design(_design_with(group, name, v_), THEME, BLOCKS)
            if out == base:
                same.append(f"{key}={v!r}")
            if not all(x in out for x in ("Head", "Body copy one", er.UNSUB)) or not re.search(r"<a [^>]*>Go\b", out):
                lost.append(f"{key}={v!r}")
    print(f"  {walked} non-default values walked from the schema; {len(skipped)} field(s) skipped by name: {skipped}")
    ck("every value the schema names changes the email — none is a knob nothing reads",
       walked > 60 and not same, str(same))
    ck("and none loses the copy, the ask or the legal footer", not lost, str(lost))
    # THE FILLER'S FIELDS, walked with the filler: a value the chooser does
    # not act on is as much a dead knob as one the painter ignores. Each
    # kind names a picture of that kind when one is on file; "mark" fills
    # the brand's mark; a design's imagery default reaches a section that
    # inherits it.
    from app import db as _db, kb as _kb, tenants as _tn
    _db.init_db(); _tn.seed(); _kb.ensure_brand("baci", "Baci")
    cdn = "https://cdn.shopify.com/s/files/1/0001/"
    _kinds = {"packshot-on-plain": "pk", "packshot-on-colour": "pc", "lifestyle": "lf",
              "flat-lay": "fl", "portrait": "pt", "texture": "tx"}
    for kind, tag in _kinds.items():
        _kb.add_asset("baci", f"{cdn}{tag}.jpg", rights=_kb.OWNED, subject="photo", title=kind, origin="human")
    with _db.SessionLocal() as _s:
        for a in _s.query(_db.KbAsset).filter(_db.KbAsset.tenant == "baci").all():
            a.reading = {"colours": {"dominant": "#888888", "light": "#eeeeee", "dark": "#111111", "mid": "#5577aa",
                                     "key": "mid", "luminance": 0.5, "warmth": 0.0},
                         "kind": a.title, "how": {"colours": "arithmetic", "kind": "test"}, "aspect": "landscape"}
        _s.commit()
    filled_by_kind = {}
    for kind in _kinds:
        d, _ = ed.normalize({"sections": [{"kind": "feature", "image_kind": kind, "slots": ["headline", "body", "image:1"]}]})
        got = ed.choose_media("baci", d)
        filled_by_kind[kind] = [a.title for a in (got["by_section"].get(0) or [])]
    ck("section.image_kind is read by the filler — each kind chooses a picture of that kind",
       all(filled_by_kind[k] == [k] for k in _kinds), str(filled_by_kind))
    d_mark, _ = ed.normalize({"sections": [{"kind": "closing", "layout": "band", "image_kind": "mark", "slots": ["image:1"]}]})
    ck("and image_kind mark fills the brand's mark, never a photograph",
       ed.choose_media("baci", d_mark)["by_section"].get(0) == "mark")
    d_inh, _ = ed.normalize({"imagery": {"feature": "texture"}, "sections": [{"kind": "feature", "slots": ["body", "image:1"]}]})
    ck("imagery.<family> is read by the filler — an inheriting section takes the design's default kind",
       [a.title for a in ed.choose_media("baci", d_inh)["by_section"].get(0) or []] == ["texture"])
    ck("the filler's fields are declared, and they are the picture-kind fields",
       set(filler_fields) == {("section", "image_kind"), ("imagery", "hero"), ("imagery", "product"), ("imagery", "feature")},
       str(filler_fields))
    ck("the fields skipped are exactly the ones NOT_DRAWN_YET names, each with its phase",
       set(skipped) == set(er.NOT_DRAWN_YET) and all(v.startswith("Phase") for v in er.NOT_DRAWN_YET.values()))
    # NOT_DRAWN_YET must be honest the other way too: a field it names must
    # not draw — or it is hiding a drawn field from the walk.
    hides = []
    for key in er.NOT_DRAWN_YET:
        group, name = key.split(".")
        f = ed.SCHEMA[group][name]
        for v in f.values:
            v_ = [v] if f.many else v
            if er.render_design(_design_with(group, name, v_), THEME, BLOCKS) != base:
                hides.append(f"{key}={v!r}")
    ck("NOT_DRAWN_YET names only fields that truly do not draw yet", not hides, str(hides))

    print("\n— 2. colours only through the palette —")
    allowed = _allowed(THEME)
    stray = {}
    for group, name, values, default, _m in ed.fields():
        if f"{group}.{name}" in er.NOT_DRAWN_YET:
            continue
        for v in values:
            v_ = [v] if isinstance(default, list) else v
            out = er.render_design(_design_with(group, name, v_), THEME, BLOCKS)
            bad = {h.lower() for h in HEX.findall(out)} - allowed
            if bad:
                stray[f"{group}.{name}={v!r}"] = sorted(bad)
    ck("every hex in every render is a palette role or the renderer's own mix of two — never the design's",
       not stray, str(stray)[:300])
    dark = er.render_design(_design_with("section", "bg", "dark"), THEME, BLOCKS)
    pal = THEME["palette"]
    ck("a section on the dark ground is painted in the dark ground's ink",
       f'background:{pal["dark"]}' in dark and f'color:{pal["dark_ink"]}' in dark)
    band = er.render_design(ed.normalize({"sections": [{"kind": "closing", "layout": "band", "bg": "accent"}]})[0], THEME,
                            [{"type": "cta", "label": "Go", "url": "https://x/go"}])
    ck("on the accent ground the filled button inverts, so it still reads as a button",
       f'background:{pal["surface"]};border-radius' in band and f'color:{pal["accent"]};text-decoration:none' in band)
    ck("the design carries no colour into the render — a hex in a design is dropped before painting",
       "#00ff00" not in er.render_design({"frame": {"page": "#00ff00"}}, THEME, BLOCKS))

    print("\n— 3. one design, two brands —")
    d = ed.normalize({"type": {"display_family": "serif-display", "scale": "poster", "heading_case": "upper"},
                      "cta": {"style": "outline", "radius": "square"},
                      "sections": [{"kind": "hero", "layout": "overlay", "bg": "dark", "text_on_image": True},
                                   {"kind": "products", "layout": "grid3", "bg": "tint"},
                                   {"kind": "proof", "bg": "page"}]})[0]
    a, b = er.render_design(d, THEME, BLOCKS), er.render_design(d, THEME_B, BLOCKS)
    tags = lambda h: re.sub(r'="[^"]*"', '=""', re.sub(r">[^<]*<", "><", h))
    ck("the same design through two palettes is two emails — same words, same structure, different colours",
       a != b and tags(a) == tags(b) and {h.lower() for h in HEX.findall(a)} != {h.lower() for h in HEX.findall(b)}
       and THEME_B["palette"]["dark"] in b and THEME["palette"]["dark"] in a and "Head" in a and "Head" in b)

    print("\n— 4. the faces —")
    own = {**THEME, "font": {"heading": "'Cormorant', Georgia, serif", "body": "'Karla', Arial, sans-serif"}}
    o = er.render_design(d, own, BLOCKS)
    ck("the brand's own face wins over the class the design names",
       "Cormorant" in o and "Playfair" not in o and "fonts.googleapis.com" not in o)
    ck("with no face on file, the class chooses and its Google face is linked, with a fallback stack",
       "Playfair Display" in a and "fonts.googleapis.com/css2?family=Playfair+Display" in a and "Georgia" in a)
    ck("the house design links nothing — its classes are email-safe stacks",
       "fonts.googleapis.com" not in base)

    print("\n— 5. sections —")
    kinds = [s["kind"] for s in er.group_sections(BLOCKS)]
    ck("the drafter's blocks are grouped by the rules — hero, a run, products, proof, offer, a run, closing, ps",
       kinds == ["hero", "intro", "products", "proof", "offer", "feature", "closing", "ps"], str(kinds))
    ck("an ask on its own is the closing; a run holds its ask",
       [s["kind"] for s in er.group_sections([{"type": "cta", "label": "x", "url": "#"}])] == ["closing"]
       and len(er.group_sections([{"type": "heading", "text": "h"}, {"type": "cta", "label": "x", "url": "#"}])) == 1)
    taken: dict = {}
    dd = ed.normalize({"sections": [{"kind": "products", "layout": "grid2"}, {"kind": "products", "layout": "grid3"}]})[0]
    ck("a concrete order reaches its kinds in sequence — the first product section grid2, the second grid3",
       er._spec_for(dd, "products", taken)["layout"] == "grid2" and er._spec_for(dd, "products", taken)["layout"] == "grid3"
       and er._spec_for(dd, "products", taken)["layout"] == "stack")
    two = er.render_design(dd, THEME, BLOCKS + [{"type": "products", "items": BLOCKS[6]["items"]}])
    ck("…and the render honours it: two product blocks, two layouts", two.count('width="') > base.count('width="'))
    ck("every layout the schema names has a painter; a layout nothing draws falls to stack",
       set(ed.SECTION["layout"].values) == set(er.LAYOUTS)
       and er.LAYOUTS.get("hologram", er._lay_stack) is er._lay_stack)
    centred, _ = ed.normalize({"sections": [{"kind": "hero", "slots": ["headline"]},
                                            {"kind": "intro", "slots": ["headline", "body"]},
                                            {"kind": "closing", "align": "center", "slots": ["body", "cta"]}]})
    c_blocks = [{"type": "hero", "image": CDN + "h.jpg"}, {"type": "heading", "text": "H", "level": 1},
                {"type": "text", "html": "<p>Words.</p>"}, {"type": "divider"},
                {"type": "text", "html": "<p>Forwarded?</p>"}, {"type": "cta", "label": "Go", "url": "#"}]
    ck("a centred closing centres its ask too, not only its words",
       'align="center"' in er.render_design(centred, THEME, c_blocks).split("Go</a>")[0][-420:])
    stack_cards, _ = ed.normalize({"frame": {"container": "cards"}, "sections": [{"kind": "intro", "slots": ["body"]}]})
    ck("in a stack of cards a boundary divider paints no rule at the bottom of a card",
       "height:1px" not in er.render_design(stack_cards, THEME, [{"type": "heading", "text": "H"}, {"type": "text", "html": "<p>x</p>"}, {"type": "divider"}]).split("</table></td></tr></table></td></tr>")[0].split("H<")[1])
    cols = er.render_design(_design_with("section", "layout", "columns"), THEME, BLOCKS)
    ck("columns deal the run's words left and right", cols.count('width="50%"') == 2)

    print("\n— 6. CAN-SPAM in every design; live text under every picture —")
    ck("the unsubscribe and the address survive every footer variant",
       all(er.UNSUB in er.render_design(_design_with("footer", n, v), THEME, BLOCKS)
           and "100 Example Ave" in er.render_design(_design_with("footer", n, v), THEME, BLOCKS)
           for n, f in ed.SCHEMA["footer"].items() for v in f.values))
    no_addr = er.render_design(ed.house(), {**THEME, "footer": {"brand": "A"}}, BLOCKS)
    ck("a theme with no address renders the loud placeholder, never a quiet omission",
       "NO MAILING ADDRESS ON FILE" in no_addr)
    imgs = re.findall(r"<img[^>]*>", a)
    ck("every picture carries alt text and the words are live text beside it",
       imgs and all("alt=" in i for i in imgs) and "Head" in re.sub(r"<img[^>]*>", "", a))
    ck("a picture is cut to the slot's aspect through the CDN's own convention",
       "_crop_center" in er.render_design(_design_with("section", "aspect", "square"), THEME, BLOCKS)
       and "_1200x1200_crop_center" in er.render_design(_design_with("section", "aspect", "square"), THEME, BLOCKS))

    print("\n" + ("ALL PASSED" if not _fail else f"{len(_fail)} FAILED: {_fail}"))
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
