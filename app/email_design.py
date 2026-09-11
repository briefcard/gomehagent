"""The DESIGN of an email, as words the renderer can draw.

INITIATIVE-email-design.md, Phase 1. The owner, 2026-09-11, on a send built
from a swiped structure: *"it is currently making the same email with slight
layout differences, but we want the creatives, the styling and font formats
etc — it should be similar to recreating [the reference] with our content and
dynamic assets, potentially in colors that make more sense for each brand."*

A design is a DOCUMENT the renderer executes — never a knob on a fixed
template, which is what the six-axis `look` was and why every email came out
as the house template with the toggles flipped. It describes the whole of how
an email is built: the frame, the header, the type system, the colour ROLES,
each section's layout and image treatment and slots, the ask, the dividers,
the footer, and what kind of picture each slot wants.

THREE THINGS A DESIGN NEVER CARRIES, by construction rather than by rule:

* **A colour.** Every ground is a ROLE (`page`, `surface`, `dark`, `tint`,
  `accent`); the brand's palette fills the role at render, so the same design
  is navy and cream for one brand and forest and bone for another. A hex
  anywhere in a design is dropped at `normalize` and said.
* **A typeface.** The type system names a CLASSIFICATION ("serif-display",
  "sans-grotesque") and a FORMAT (scale, weight, case, tracking, leading); the
  brand's own faces win when it has them on file, the classification chooses
  a stack only when it has none.
* **A word.** There is no free-text field. Slots say what KIND of content
  goes where (`headline`, `products:3`, `quote`); the drafter writes it, the
  brand's own claims and pictures fill it, and every gate that reads copy
  still reads it. A reference contributes its design, never its material.

THE VOCABULARY IS CLOSED SO THAT EVERY VALUE HAS A PAINTER. `SCHEMA` is one
declarative structure — for every field its allowed values, its default and
one line of meaning — and from it derive: the reading prompt (Phase 3), the
validator (`normalize`, here), the RUNBOOK table (`scripts/gen_email_design_
doc.py`, byte-compared) and the test that refuses a value nothing draws
(Phase 4, when the painters exist). Adding a layout is one schema entry and
one painter; nothing is listed twice.

`house()` is today's renderer expressed as a design, so the old `look`
becomes a minimal design and nothing in production changes until the campaign
run is switched (Phase 6).
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Roles and small vocabularies
# ---------------------------------------------------------------------------

#: The palette a BRAND supplies (Phase 2). A design may name only the GROUND
#: roles; the ink that goes on each ground is derived from it at render
#: (surface → ink, dark → dark_ink, tint → tint_ink, accent → accent_ink,
#: page → ink), so a design cannot put dark type on a dark ground.
ROLES = ("page", "surface", "ink", "muted", "accent", "accent_ink",
         "dark", "dark_ink", "tint", "tint_ink", "border", "secondary")
GROUNDS = ("page", "surface", "dark", "tint", "accent")

#: What KIND of section. Named by what the section is for, so a design read
#: off a reference and the drafter's own blocks meet in one vocabulary.
KINDS = ("hero", "intro", "feature", "products", "proof", "editorial",
         "offer", "closing", "ps")

#: What kind of content a slot holds. `products` and `image` take a count
#: (`products:3`, `image:2`); everything else is one thing.
SLOTS = ("kicker", "headline", "sub", "body", "list", "cta", "products",
         "quote", "stat", "image", "caption", "signature", "ps")
COUNTED = ("products", "image")
SLOT_MAX = 6

#: The renderer's block a slot becomes, so a design's `sequence` — the
#: identity the library already keys on — can be derived from its sections
#: and only ever names blocks `email_render._BLOCKS` can build. An image slot
#: in a hero is the hero picture; anywhere else it is the section's own
#: picture and no block of its own (the layout draws it).
_SLOT_BLOCK = {"kicker": "heading", "headline": "heading", "sub": "text",
               "body": "text", "list": "list", "cta": "cta",
               "products": "products", "quote": "quote", "stat": "stat",
               "caption": "text", "signature": "signature", "ps": "ps"}


class _F:
    """One field of the schema: allowed values, the default, what it means.

    `many` = a list drawn from the values (the accent may be used on buttons
    AND rules); everything else is exactly one value. Values are strings,
    ints or bools — never a colour, never a face, never a word.
    """
    __slots__ = ("values", "default", "meaning", "many")

    def __init__(self, values, default, meaning, *, many=False):
        self.values, self.default, self.meaning, self.many = tuple(values), default, meaning, many
        if many:
            assert all(d in self.values for d in default), (default, values)
        else:
            assert default in self.values, (default, values)


_ONOFF = (False, True)
IMAGERY = ("packshot-on-plain", "packshot-on-colour", "lifestyle", "flat-lay",
           "portrait", "texture")

#: The fields of ONE SECTION — used twice: as `defaults` per kind (how a
#: block of that kind is painted when the drafter composes its own order) and
#: inside `sections[]` (a concrete order read off a reference).
SECTION = {
    "layout": _F(("stack", "split-left", "split-right", "grid2", "grid3", "collage",
                  "overlay", "columns", "band", "letter"), "stack",
                 "how the section's parts sit: stacked; picture beside the words "
                 "(left or right); a grid of two or three; a collage of pictures; "
                 "words ON the picture; two columns of words; one line on a band; "
                 "a letter's paragraphs"),
    "align": _F(("left", "center"), "left", "where the words sit"),
    "bg": _F(GROUNDS, "surface", "the ground the section sits on — a ROLE the "
                                 "brand's palette fills, never a colour"),
    "pad": _F(("none", "tight", "regular", "airy"), "regular",
              "the room around the section"),
    "image": _F(("none", "contained", "bleed", "rounded", "circle", "framed", "duotone"),
                "contained", "the picture's treatment: inside the margins; edge to "
                             "edge; rounded corners; a circle; a keyline; a tint"),
    "aspect": _F(("square", "portrait", "landscape", "wide"), "landscape",
                 "the picture's shape — the slot the brand's own picture is cut to"),
    "text_on_image": _F(_ONOFF, False, "the words sit over the picture"),
    "rule_above": _F(("none", "thin", "thick", "dotted"), "none",
                     "a rule between this section and the one before"),
}

#: The whole design. Every group is a dict of fields; `defaults` is SECTION
#: per kind; `sections` is a list of SECTION + `kind` + `slots`.
SCHEMA = {
    "frame": {
        "page": _F(("page", "dark", "tint"), "page", "the ground behind the email"),
        "container": _F(("flat", "card"), "card",
                        "the email sits flat on the page, or in a card on it"),
        "width": _F((600, 640, 680), 600, "the email's width in pixels"),
        "radius": _F(("none", "soft", "round"), "soft", "how corners are cut, everywhere"),
        "border": _F(_ONOFF, True, "a keyline around the card"),
    },
    "header": {
        "logo": _F(("left", "center"), "left", "where the brand mark sits"),
        "nav": _F(("none", "inline", "below"), "inline",
                  "the store's sections as links: none, beside the mark, on their own line"),
        "case": _F(("upper", "title"), "upper", "how the links are set"),
        "bg": _F(GROUNDS, "surface", "the header's ground — a role"),
        "rule": _F(_ONOFF, True, "a rule under the header"),
    },
    "type": {
        "display_family": _F(("serif-display", "serif-editorial", "sans-geometric",
                              "sans-grotesque", "condensed", "script"), "serif-editorial",
                             "the CLASS of the headline face — the brand's own face wins "
                             "when it has one on file; this chooses a stack only when it "
                             "has none"),
        "body_family": _F(("serif", "sans"), "sans", "the class of the reading face"),
        "scale": _F(("modest", "large", "display", "poster"), "modest",
                    "how big the headline is against the body"),
        "heading_weight": _F(("light", "regular", "bold", "black"), "bold",
                             "the headline's weight"),
        "heading_case": _F(("upper", "title", "sentence"), "sentence", "the headline's case"),
        "tracking": _F(("tight", "normal", "wide"), "normal", "letter-spacing on headings"),
        "align": _F(("left", "center"), "left", "where headings sit"),
        "body_size": _F((14, 15, 16, 17), 16, "the reading size in pixels"),
        "leading": _F(("tight", "regular", "airy"), "regular", "line height everywhere"),
        "kicker": _F(("none", "caps", "accent", "rule"), "accent",
                     "the small line over a section: none; small capitals; small "
                     "capitals in the accent; with a short rule"),
        "italic_sub": _F(_ONOFF, False, "the sub-headline is set in italics"),
    },
    "palette": {
        "mood": _F(("light", "dark", "high-contrast", "tonal", "mono"), "light",
                   "the email's overall key — read off the reference, filled by the "
                   "brand's roles"),
        "accent_use": _F(("buttons", "rules", "type", "blocks"), ["buttons", "rules"],
                         "where the accent is allowed to appear", many=True),
    },
    "cta": {
        "style": _F(("filled", "outline", "underline", "arrow", "full"), "filled",
                    "the ask's shape: a filled button; outlined; an underlined line; "
                    "a line with an arrow; a full-width bar"),
        "radius": _F(("square", "soft", "pill"), "soft", "the button's corners"),
        "size": _F(("small", "regular", "large"), "regular", "the button's size"),
        "case": _F(("upper", "title", "sentence"), "sentence", "the label's case"),
        "align": _F(("left", "center"), "left", "where the ask sits"),
    },
    "dividers": {
        "style": _F(("none", "thin", "thick", "dotted", "ornament"), "thin",
                    "what separates sections when a divider is asked for"),
    },
    "footer": {
        "bg": _F(GROUNDS, "surface", "the footer's ground — a role"),
        "align": _F(("left", "center"), "center", "where the footer's lines sit"),
        "socials": _F(("none", "words", "icons"), "words", "how the social links are shown"),
        "rule": _F(_ONOFF, False, "a rule over the footer"),
    },
    "imagery": {
        "hero": _F(IMAGERY, "lifestyle", "the kind of picture the opening wants"),
        "product": _F(IMAGERY, "packshot-on-plain", "the kind of picture a product card wants"),
        "feature": _F(IMAGERY, "lifestyle", "the kind of picture a feature section wants"),
    },
}

_HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(")
_URL = re.compile(r"https?://|www\.", re.I)
_SLOT = re.compile(r"^([a-z]+)(?::(\d+))?$")


# ---------------------------------------------------------------------------
# Normalising: everything the renderer draws, nothing it does not, and every
# dropped thing said
# ---------------------------------------------------------------------------
def _leak(v) -> str:
    """Why a free value may not enter a design, or '' when it is only unknown."""
    s = str(v)
    if _HEX.search(s):
        return "a design never names a colour — grounds are roles the brand fills"
    if _URL.search(s):
        return "a design never carries a link"
    return ""


def _one(field: _F, raw, path: str, dropped: list):
    """One field's value: the raw value when the renderer draws it, else the
    default — and the reason, in a sentence, when it was not the raw value."""
    if raw is None:
        return list(field.default) if field.many else field.default
    if field.many:
        vals = raw if isinstance(raw, (list, tuple)) else [raw]
        keep, bad = [], []
        for v in vals:
            v2 = v.strip().lower() if isinstance(v, str) else v
            (keep if v2 in field.values and v2 not in keep else bad).append(v2 if v2 in field.values else v)
        for v in bad:
            dropped.append(f"{path} {v!r}: " + (_leak(v) or
                           f"not a value the renderer draws ({', '.join(map(str, field.values))})"))
        return keep or list(field.default)
    v = raw.strip().lower() if isinstance(raw, str) else raw
    # A bool field takes a bool; "true"/"on"/"yes" as words are read as one.
    if field.values == _ONOFF:
        if isinstance(v, str):
            v = v in ("true", "on", "yes", "1")
        elif not isinstance(v, bool):
            v = bool(v)
        return v
    # An int field takes an int, or its digits.
    if all(isinstance(x, int) and not isinstance(x, bool) for x in field.values):
        try:
            v = int(v)
        except (TypeError, ValueError):
            pass
    if v in field.values and type(v) is type(field.default):
        return v
    dropped.append(f"{path} {raw!r}: " + (_leak(raw) or
                   f"not a value the renderer draws ({', '.join(map(str, field.values))}) "
                   f"— {field.default!r} used"))
    return field.default


def _group(fields: dict, raw, path: str, dropped: list) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for name, field in fields.items():
        out[name] = _one(field, raw.get(name), f"{path}.{name}", dropped)
    for name in raw:
        if name not in fields:
            dropped.append(f"{path}.{name}: " + (_leak(raw[name]) or
                           "not a field the renderer knows — dropped"))
    return out


def _slots(raw, path: str, dropped: list) -> list[str]:
    """`["kicker", "headline", "products:3"]` — names the drafter fills, with a
    count where one makes sense. An unknown slot, or a count off the scale,
    is dropped and said; a design cannot ask for a kind of content the
    renderer has no place for."""
    vals = raw if isinstance(raw, (list, tuple)) else ([raw] if raw else [])
    out: list[str] = []
    for v in vals:
        m = _SLOT.match(str(v).strip().lower())
        if not m or m.group(1) not in SLOTS:
            dropped.append(f"{path} slot {v!r}: " + (_leak(v) or
                           f"not a slot the renderer fills ({', '.join(SLOTS)})"))
            continue
        name, n = m.group(1), m.group(2)
        if n is not None and name not in COUNTED:
            dropped.append(f"{path} slot {v!r}: only {' and '.join(COUNTED)} take a count — "
                           f"{name!r} kept without one")
            n = None
        if n is not None and not (1 <= int(n) <= SLOT_MAX):
            dropped.append(f"{path} slot {v!r}: a count is 1–{SLOT_MAX} — 1 used")
            n = "1"
        out.append(f"{name}:{int(n)}" if n is not None else name)
    return out


def normalize(raw: dict | None) -> tuple[dict, list[str]]:
    """`(design, dropped)`: a COMPLETE design — every field filled, every
    value one the renderer draws — and every raw thing that did not make it,
    each with its reason. Nothing is dropped in silence: a reading that
    volunteered a hex, a face or a layout nothing draws is told so on the
    card (owner's rule from the frames run that "made 0" — a thing that
    changed nothing says why).
    """
    raw = raw if isinstance(raw, dict) else {}
    dropped: list[str] = []
    design: dict = {}
    for group, fields in SCHEMA.items():
        design[group] = _group(fields, raw.get(group), group, dropped)
    # Per-kind defaults: how a block of each kind is painted when the drafter
    # composes its own order. Every kind is present, filled from SECTION's
    # defaults, so a renderer never looks a kind up and finds nothing.
    rd = raw.get("defaults") if isinstance(raw.get("defaults"), dict) else {}
    design["defaults"] = {k: _group(SECTION, rd.get(k), f"defaults.{k}", dropped) for k in KINDS}
    for k in rd:
        if k not in KINDS:
            dropped.append(f"defaults.{k}: not a section kind ({', '.join(KINDS)})")
    # A concrete order, when the design has one.
    secs = raw.get("sections")
    out_secs: list[dict] = []
    for i, s in enumerate(secs if isinstance(secs, list) else []):
        p = f"sections[{i}]"
        if not isinstance(s, dict):
            dropped.append(f"{p}: not a section — dropped")
            continue
        kind = str(s.get("kind", "")).strip().lower()
        if kind not in KINDS:
            dropped.append(f"{p} kind {s.get('kind')!r}: " + (_leak(s.get("kind", "")) or
                           f"not a section kind ({', '.join(KINDS)}) — section dropped"))
            continue
        body = {k: v for k, v in s.items() if k not in ("kind", "slots")}
        sec = {"kind": kind, **_group(SECTION, body, p, dropped),
               "slots": _slots(s.get("slots"), p, dropped)}
        out_secs.append(sec)
    design["sections"] = out_secs
    for k in raw:
        if k not in SCHEMA and k not in ("defaults", "sections"):
            dropped.append(f"{k}: " + (_leak(raw[k]) or "not a part of a design — dropped"))
    return design, dropped


def complete(design: dict) -> bool:
    """True when every field the schema names is present with a drawn value —
    what `normalize` guarantees, checkable on a row read back."""
    d2, dropped = normalize(design)
    return not dropped and d2 == design


# ---------------------------------------------------------------------------
# The house: today's renderer, as a design
# ---------------------------------------------------------------------------
#: The old six-axis `look`, mapped into the vocabulary. Kept until Phase 4
#: retires `email_render.LOOK`; after that a look IS a design and this map
#: is only how the rows filed before were migrated.
_LOOK_HERO = {"contained": {"layout": "stack", "image": "contained"},
              "bleed": {"layout": "stack", "image": "bleed"},
              "overlay": {"layout": "overlay", "image": "bleed", "text_on_image": True,
                          "bg": "dark"},
              "split": {"layout": "split-left", "image": "contained", "aspect": "portrait"}}
_LOOK_CTA = {"block": {"style": "filled", "radius": "soft"},
             "full": {"style": "full", "radius": "soft"},
             "pill": {"style": "filled", "radius": "pill"},
             "link": {"style": "arrow", "radius": "soft"}}
_LOOK_PRODUCTS = {"rows": "stack", "grid2": "grid2", "grid3": "grid3"}


def house(look: dict | None = None, *, width: int = 600) -> dict:
    """Today's renderer, expressed as a design — the white card on a grey
    page, the mark left and the links beside it, an editorial serif over a
    grotesque body, a kicker in the accent, a filled soft button, a thin
    rule, a quiet centred footer — with the six look axes folded in where
    each of them moved something. `house()` with no look is exactly the
    house default; a structure filed under a look migrates to `house(look)`.
    Tenant-free by design: a design carries no brand."""
    from . import email_render
    lk = email_render._look(look)
    pad = {"tight": "tight", "regular": "regular", "airy": "airy"}[lk["density"]]
    d = {
        "frame": {"page": "page", "container": "card", "width": width,
                  "radius": "soft", "border": True},
        "header": {"logo": "left", "nav": "inline", "case": "upper",
                   "bg": "surface", "rule": True},
        "type": {"display_family": "serif-editorial", "body_family": "sans",
                 "scale": "display" if lk["scale"] == "display" else "modest",
                 "heading_weight": "bold", "heading_case": "sentence",
                 "tracking": "normal", "align": "left", "body_size": 16,
                 "leading": pad, "kicker": "accent", "italic_sub": False},
        "palette": {"mood": "light", "accent_use": ["buttons", "rules", "type"]},
        "cta": {**_LOOK_CTA[lk["cta"]], "size": "regular", "case": "sentence",
                "align": "left"},
        "dividers": {"style": "thin"},
        "footer": {"bg": "surface", "align": "center", "socials": "words", "rule": False},
        "imagery": {"hero": "lifestyle", "product": "packshot-on-plain",
                    "feature": "lifestyle"},
        "defaults": {k: {"pad": pad} for k in KINDS},
        "sections": [],
    }
    d["defaults"]["hero"].update(_LOOK_HERO[lk["hero"]])
    d["defaults"]["products"]["layout"] = _LOOK_PRODUCTS[lk["products"]]
    if lk["bands"]:
        # Every second section on the page colour — said per kind, since the
        # house has no fixed order: the kinds a drafter alternates.
        for k in ("feature", "proof", "offer"):
            d["defaults"][k]["bg"] = "page"
    design, dropped = normalize(d)
    assert not dropped, dropped   # the house is in the vocabulary by definition
    return design


# ---------------------------------------------------------------------------
# Reading a design: its identity, its blocks, its one-line name
# ---------------------------------------------------------------------------
def sequence_of(design: dict) -> list[str]:
    """The block types a design's sections ask for, in order — the identity
    the library keys on (`email_structures.signature`). Only blocks the
    renderer builds, by construction of `_SLOT_BLOCK`; an empty design (the
    house, or one with no fixed order) has no sequence of its own."""
    out: list[str] = []
    for s in design.get("sections") or []:
        names = [slot.split(":", 1)[0] for slot in (s.get("slots") or [])]
        if s.get("kind") == "hero":
            # The renderer's hero block carries the picture, the headline and
            # the sub itself; only an ask after it is a block of its own.
            out.append("hero")
            names = [n for n in names if n not in ("image", "kicker", "headline", "sub")]
        for name in names:
            if name == "image":
                continue          # drawn by the section's layout, not a block
            b = _SLOT_BLOCK.get(name)
            if b:
                out.append(b)
    return out


def summary(design: dict) -> str:
    """One line for a card: the key, the type, the ask, how many sections."""
    t, c, p = design.get("type", {}), design.get("cta", {}), design.get("palette", {})
    n = len(design.get("sections") or [])
    bits = [f"{p.get('mood', '')} key",
            f"{t.get('display_family', '')} over {t.get('body_family', '')} body, "
            f"{t.get('scale', '')} scale",
            f"{c.get('style', '')} {c.get('radius', '')} ask",
            (f"{n} section{'s' if n != 1 else ''}" if n else "the drafter's own order")]
    return "; ".join(b for b in bits if b.strip())


def fields() -> list[tuple[str, str, tuple, object, str]]:
    """Every field in the vocabulary as `(group, name, values, default,
    meaning)` — the walk the generated RUNBOOK table, the reading prompt and
    the painter test all share, so none of them can list a field the others
    do not."""
    rows = []
    for group, fs in SCHEMA.items():
        for name, f in fs.items():
            rows.append((group, name, f.values, f.default, f.meaning))
    for name, f in SECTION.items():
        rows.append(("section", name, f.values, f.default, f.meaning))
    return rows
