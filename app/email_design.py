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


# ---------------------------------------------------------------------------
# The brand's pictures, by the kind of slot each can fill
# ---------------------------------------------------------------------------
#: How a slot's `imagery` kind is found among what is on file. Nothing new is
#: filed for this: the catalogue sync marks the featured store image
#: `packshot` (subject object), later store images are the product among
#: other things, Drive photographs are `photo`, a pinned scene is `scene`,
#: a surface is `surface`. A cut-out ("packshot-on-colour") is made at fill
#: time by `creative.focused`, never stored, so it reads as a packshot here.
_KIND_FIT = {
    "packshot-on-plain": (("object", "packshot"), ("object", "")),
    "packshot-on-colour": (("object", "packshot"), ("object", "")),
    "lifestyle": (("photo", ""), ("scene", ""), ("object", "store-image")),
    "flat-lay": (("photo", ""), ("scene", ""), ("object", "store-image")),
    "portrait": (("photo", ""), ("scene", "")),
    "texture": (("surface", ""),),
}


def assets_for(tenant: str, kind: str, aspect: str = "") -> dict:
    """The brand's own publishable pictures that can fill a slot of this
    `imagery` kind, best fit first — `{ok, kind, aspect, assets, why}`.
    `assets` are the KbAsset rows; `aspect` rides along as the crop the slot
    wants (the filler cuts to it through the CDN, Phase 5). An empty answer
    says why by name, so a run that leaves a slot empty can say it too."""
    from . import kb
    fits = _KIND_FIT.get(kind)
    if fits is None:
        return {"ok": False, "kind": kind, "aspect": aspect, "assets": [],
                "why": f"{kind!r} is not an imagery kind ({', '.join(_KIND_FIT)})"}
    rows = [a for a in kb.assets(tenant) if (a.kind or "image") == "image"]
    out, seen = [], set()
    for subject, tag in fits:
        for a in rows:
            if a.id in seen or (a.subject or "") != subject:
                continue
            tags = [str(t) for t in (a.tags or [])]
            if tag == "packshot" and "packshot" not in tags:
                continue
            if tag == "store-image" and not any(t.startswith("store-image:") and t != "store-image:1"
                                                for t in tags):
                continue
            if tag == "" and subject == "object" and "packshot" in tags:
                pass    # a packshot fits a plain-packshot slot as the second rank too
            seen.add(a.id)
            out.append(a)
    why = "" if out else (f"no publishable picture on file fits a {kind} slot — "
                          + {"texture": "file a surface photograph",
                             "portrait": "file a photograph of a person, or a scene",
                             }.get(kind, "run the catalogue sync, or file a photograph"))
    return {"ok": bool(out), "kind": kind, "aspect": aspect, "assets": out, "why": why}


def assets_by_kind(tenant: str) -> dict[str, int]:
    """How many pictures could fill each imagery kind — the Brand tab's line."""
    return {k: len(assets_for(tenant, k)["assets"]) for k in _KIND_FIT}


# ---------------------------------------------------------------------------
# READING a reference into a design — with eyes (Phase 3)
#
# The first reader sent the gallery screenshot whole; the screenshots are
# 680 wide and 2800–4600 tall, and Claude scales a picture to its model's
# tier (`llm.IMAGE_TIERS`), so a 680×4543 email reached the standard tier
# at 235×1568 with body type under five pixels — and the prompt then said
# "never a colour, a typeface". This reader:
#
#   * cuts the screenshot into STRIPS that fit the reviewer's tier, each
#     marked `oversized_image: error` so a strip that WOULD be downscaled is
#     refused by the API and said, never degraded in silence;
#   * reads in three passes — A, the whole design (frame, header, type,
#     palette, ask, footer, imagery) off a contact sheet and the top strip;
#     B, the sections in each strip; C, a critique of the assembled design
#     against the strips, answered as a patch — and merges the patch once;
#   * derives every prompt from `SCHEMA` (`fields()`), so the reading can
#     never be asked for a field the validator does not know;
#   * files the result PROPOSED, with everything `normalize` dropped listed
#     on the structure, and never a word of the reference's copy.
# ---------------------------------------------------------------------------
STRIP_OVERLAP = 120
MAX_IMAGE_BLOCKS = 20          # over this the API holds every image to 2000 px
_GLOBAL_GROUPS = ("frame", "header", "type", "palette", "cta", "dividers", "footer", "imagery")


def _tier_edge() -> tuple[str, int]:
    from . import config, llm
    tier, _why = llm.image_tier(config.CREATIVE_REVIEW_MODEL)
    return tier, llm.IMAGE_TIERS[tier]["max_edge"]


def strips(blob: bytes, max_edge: int, overlap: int = STRIP_OVERLAP) -> list[dict]:
    """The screenshot as strips that fit `max_edge`, each
    `{png, top, bottom, width, height}`, overlapping by `overlap` px so a
    section cut by a strip edge is seen whole in one of them. A picture
    that already fits is one strip. Lossless PNG: this is the one place
    the type has to stay legible."""
    import io
    from PIL import Image
    im = Image.open(io.BytesIO(blob)).convert("RGB")
    W, H = im.size
    if W > max_edge:
        im = im.resize((max_edge, max(1, round(H * max_edge / W))), Image.LANCZOS)
        W, H = im.size
    out = []
    top = 0
    while True:
        bottom = min(H, top + max_edge)
        crop = im.crop((0, top, W, bottom))
        buf = io.BytesIO()
        crop.save(buf, format="PNG", optimize=True)
        out.append({"png": buf.getvalue(), "top": top, "bottom": bottom,
                    "width": W, "height": bottom - top})
        if bottom >= H:
            break
        top = bottom - overlap
    return out


def contact_sheet(blob: bytes, max_edge: int) -> bytes:
    """The whole email at the size the reviewer's tier can hold — the view
    for the overall key, the frame and the rhythm, never for the type."""
    import io
    from PIL import Image
    from . import llm
    im = Image.open(io.BytesIO(blob)).convert("RGB")
    w, h = llm.resized_size(*im.size, max_edge, max_edge * 4)
    if (w, h) != im.size:
        im = im.resize((w, h), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _image_block(png: bytes) -> dict:
    import base64
    from . import llm
    return {"type": "image",
            "source": {"type": "base64", "media_type": "image/png",
                       "data": base64.standard_b64encode(png).decode()},
            # A strip that would be downscaled is REFUSED, not shrunk.
            "transformations": dict(llm.OVERSIZED_IMAGE_ERROR)}


def _vals(field: _F) -> str:
    return " | ".join(("on" if v else "off") if isinstance(v, bool) else str(v)
                      for v in field.values)


def _field_lines(fields: dict, indent: str = "    ") -> str:
    return "\n".join(f'{indent}"{name}": {_vals(f)}  — {f.meaning}'
                     + ("  (a list; several allowed)" if f.many else "")
                     for name, f in fields.items())


def prompt_global(has_mobile: bool) -> str:
    """Pass A. Derived from SCHEMA: every global group, every field, its
    values and meaning — the reading is asked for exactly what the
    validator knows and nothing else."""
    groups = "\n".join(f'  "{g}": {{\n{_field_lines(SCHEMA[g])}\n  }}' for g in _GLOBAL_GROUPS)
    imgs = ("Image 1 is the whole email scaled to fit; Image 2 is its top at full size"
            + ("; Image 3 is the same email as rendered on a phone" if has_mobile else "") + ".")
    return (f"You are looking at a marketing email from a public gallery. {imgs}\n"
            "Describe its DESIGN — how it is built — and never its words, its brand, its "
            "products, its prices, or what its pictures show. Grounds are ROLES (page, "
            "surface, dark, tint, accent), never colours; faces are CLASSES, never names.\n"
            "Answer as JSON with exactly these groups and fields, each value one of the "
            "values listed for it:\n{\n" + groups + ",\n"
            '  "notes": "one or two sentences on what the design does well — the arrangement, '
            'the rhythm, the type. No brand names, no product names, no quoted copy, no '
            'URLs, no colours."\n}\nNothing outside the JSON.')


def prompt_strip(k: int, n: int, top: int, bottom: int, total: int) -> str:
    """Pass B. The sections visible in one strip, in SECTION's own words."""
    return (f"This is strip {k} of {n} of the same email (pixels {top}–{bottom} of {total}). "
            "List the SECTIONS visible in it, top to bottom — never their words, only how "
            "each is built. Answer as JSON:\n"
            '{"sections": [{\n'
            f'    "kind": {" | ".join(KINDS)}  — what the section is for\n'
            '    "continued": true | false  — true when this section began above this strip\n'
            + _field_lines(SECTION) + "\n"
            f'    "slots": a list from {", ".join(SLOTS)} in reading order; products and image '
            f'take a count like "products:3" (1–{SLOT_MAX})\n'
            "}]}\nNothing outside the JSON.")


def prompt_critique(design: dict, n: int) -> str:
    """Pass C. The strips again, the design as read, and one question."""
    import json
    return (f"Images 1–{n} are the strips of the same email, top to bottom. Below is its "
            "design as it was read. List every visible property this description gets "
            "WRONG or MISSES — a ground that is dark where it says surface, a headline "
            "set upper-case where it says sentence, a section missing, a slot missing — "
            "and answer ONLY with a JSON patch in the same shape holding just the fields "
            'to change: {"frame": {...}, "type": {...}, ..., "sections": [{"index": <0-based '
            "index into the sections below>, ...fields to change...}], "
            '"notes": "..."}. An empty object {} means the reading is right. Never a word '
            "of the email's copy, never a colour, never a face's name.\n\nTHE DESIGN AS READ:\n"
            + json.dumps({k: v for k, v in design.items() if k != "defaults"}, indent=1))


def _json(text: str) -> dict:
    import json
    m = re.search(r"\{.*\}", str(text or ""), re.S)
    if not m:
        return {}
    try:
        got = json.loads(m.group(0))
    except ValueError:
        return {}
    return got if isinstance(got, dict) else {}


def stitch(per_strip: list[list[dict]]) -> list[dict]:
    """Sections from consecutive strips as one list: a strip's first
    section marked `continued` is the previous strip's last, seen again in
    the overlap — kept once, its slots the union in order."""
    out: list[dict] = []
    for k, secs in enumerate(per_strip):
        for i, s in enumerate(secs):
            s = dict(s or {})
            cont = bool(s.pop("continued", False))
            if k and i == 0 and cont and out:
                prev = out[-1]
                for slot in s.get("slots") or []:
                    if slot not in (prev.get("slots") or []):
                        prev.setdefault("slots", []).append(slot)
                continue
            out.append(s)
    return out


def apply_patch(design: dict, patch: dict) -> tuple[dict, list[str]]:
    """The critique's corrections merged once — global groups field by
    field, sections by index — and the result normalised; returns what the
    patch tried to say that the vocabulary does not hold."""
    import copy
    d = copy.deepcopy(design)
    for g in _GLOBAL_GROUPS:
        if isinstance(patch.get(g), dict):
            d[g] = {**d.get(g, {}), **patch[g]}
    for s in (patch.get("sections") or []) if isinstance(patch.get("sections"), list) else []:
        if not isinstance(s, dict):
            continue
        try:
            i = int(s.get("index"))
        except (TypeError, ValueError):
            continue
        if 0 <= i < len(d.get("sections") or []):
            d["sections"][i] = {**d["sections"][i], **{k: v for k, v in s.items() if k != "index"}}
    return normalize(d)


_QUOTED = re.compile(r'["“”‘’\']([^"“”‘’\']{2,}?)["“”‘’\']')


def quoted_copy(notes: str) -> str:
    """A run of three or more words inside quotation marks — the reference's
    own copy, arriving as a 'note'. Returned so the caller can refuse the
    notes and say why; '' when clean."""
    for m in _QUOTED.finditer(str(notes or "")):
        if len(m.group(1).split()) >= 3:
            return m.group(1)
    return ""


def look_of_design(design: dict) -> dict:
    """The old six-axis look, read off a design — so the LIVE renderer, which
    still draws `look` until Phase 4, arranges a swiped structure as well as
    it can today. The inverse of `house()` where an inverse exists."""
    hero = (design.get("defaults") or {}).get("hero") or {}
    for s in design.get("sections") or []:
        if s.get("kind") == "hero":
            hero = s
            break
    prod = next((s for s in (design.get("sections") or []) if s.get("kind") == "products"),
                (design.get("defaults") or {}).get("products") or {})
    t, c = design.get("type") or {}, design.get("cta") or {}
    look = {
        "hero": ("overlay" if hero.get("layout") == "overlay" or hero.get("text_on_image")
                 else "split" if str(hero.get("layout", "")).startswith("split")
                 else "bleed" if hero.get("image") == "bleed" else "contained"),
        "scale": "display" if t.get("scale") in ("display", "poster") else "modest",
        "density": {"tight": "tight", "airy": "airy"}.get(str(t.get("leading")), "regular"),
        "bands": any((s.get("bg") == "page") for s in (design.get("sections") or [])),
        "cta": ("link" if c.get("style") in ("arrow", "underline") else
                "full" if c.get("style") == "full" else
                "pill" if c.get("radius") == "pill" else "block"),
        "products": {"grid2": "grid2", "grid3": "grid3"}.get(str(prod.get("layout")), "rows"),
    }
    return look


_KIND_BLOCKS = {"hero": ["hero"], "intro": ["heading", "text"], "feature": ["heading", "text"],
                "products": ["products"], "proof": ["quote"], "editorial": ["heading", "text"],
                "offer": ["heading", "text", "cta"], "closing": ["text", "cta"], "ps": ["ps"]}


def sequence_for_library(design: dict) -> list[str]:
    """The library's sequence for a read design: from its slots, or — when a
    reading named sections but no slots — from the kinds, so a structure is
    never filed with fewer than the two blocks the library requires."""
    seq = sequence_of(design)
    if len(seq) >= 2:
        return seq
    out: list[str] = []
    for s in design.get("sections") or []:
        out += _KIND_BLOCKS.get(str(s.get("kind")), [])
    return out


def mobile_url(url: str) -> str:
    """The gallery's phone render of the same email, when the screenshot URL
    follows the pattern it serves it under (`…/emails/<slug>.png` →
    `…/emails/mobile/<slug>.png`); '' otherwise."""
    m = re.match(r"^(https?://[^?]*/emails/)([^/?]+\.(?:png|jpg|jpeg|webp))$", str(url or ""), re.I)
    return f"{m.group(1)}mobile/{m.group(2)}" if m else ""


def _fetch(url: str) -> bytes:
    import httpx
    from .email_structures import _UA
    try:
        r = httpx.get(url, headers={"User-Agent": _UA}, timeout=25, follow_redirects=True)
        return r.content if r.status_code == 200 else b""
    except Exception:                                            # noqa: BLE001
        return b""


def read(asset_id: str) -> dict:
    """Read one swiped screenshot into a PROPOSED structure carrying its
    design. `{ok, id, name, design, dropped, read: {tier, strips, calls,
    mobile}}` or `{ok: False, why}`."""
    from . import db, email_structures as es, kb, llm
    with db.SessionLocal() as s:
        row = s.get(db.KbAsset, asset_id)
        if row is None:
            return {"ok": False, "why": "no such swipe"}
        url, title, src = row.url or "", row.title or "", (row.source or "")
        if (row.rights or kb.REFERENCE) != kb.REFERENCE:
            return {"ok": False, "why": "not a reference swipe — a brand's own picture is not read for design"}
    blob = _fetch(url)
    if not blob:
        return {"ok": False, "why": "could not fetch the screenshot"}
    tier, edge = _tier_edge()
    try:
        parts = strips(blob, edge)
        sheet = contact_sheet(blob, edge)
    except Exception as exc:                                     # noqa: BLE001
        return {"ok": False, "why": f"the screenshot could not be read as a picture ({exc.__class__.__name__})"}
    murl = mobile_url(url)
    mob = _fetch(murl) if murl else b""
    mobile_sheet = b""
    if mob:
        try:
            mobile_sheet = contact_sheet(mob, edge)
        except Exception:                                        # noqa: BLE001
            mobile_sheet = b""
    calls = 0

    def _ask(blocks: list, text: str, max_tokens: int) -> dict:
        nonlocal calls
        imgs = [b for b in blocks if b.get("type") == "image"]
        if len(imgs) > MAX_IMAGE_BLOCKS:
            raise ValueError(f"{len(imgs)} images in one request — over {MAX_IMAGE_BLOCKS}, "
                             f"where the API holds every image to 2000 px")
        calls += 1
        reply = llm.ask("creative_review", blocks + [{"type": "text", "text": text}],
                        tenant=es.SWIPE_TENANT, max_tokens=max_tokens)
        if not getattr(reply, "ok", False):
            raise RuntimeError(getattr(reply, "error", "") or "the reading could not run")
        return _json(getattr(reply, "text", ""))

    try:
        # A — the whole design.
        a_blocks = [{"type": "text", "text": "Image 1:"}, _image_block(sheet),
                    {"type": "text", "text": "Image 2:"}, _image_block(parts[0]["png"])]
        if mobile_sheet:
            a_blocks += [{"type": "text", "text": "Image 3:"}, _image_block(mobile_sheet)]
        a = _ask(a_blocks, prompt_global(bool(mobile_sheet)), 1400)
        if not a:
            return {"ok": False, "why": "the reading did not answer in the shape asked (pass A)"}
        # B — the sections, strip by strip.
        per_strip: list[list[dict]] = []
        total = parts[-1]["bottom"]
        for k, p in enumerate(parts, 1):
            b = _ask([_image_block(p["png"])],
                     prompt_strip(k, len(parts), p["top"], p["bottom"], total), 1400)
            secs = b.get("sections") if isinstance(b.get("sections"), list) else []
            per_strip.append([x for x in secs if isinstance(x, dict)])
        raw = {g: a.get(g) for g in _GLOBAL_GROUPS}
        raw["sections"] = stitch(per_strip)
        if not raw["sections"]:
            return {"ok": False, "why": (f"the reading found no sections in {len(parts)} "
                                         f"strip(s) — the picture may not be an email")}
        design, dropped = normalize(raw)
        # C — the critique, applied once.
        c_blocks = []
        for i, p in enumerate(parts, 1):
            c_blocks += [{"type": "text", "text": f"Image {i}:"}, _image_block(p["png"])]
        patch = _ask(c_blocks, prompt_critique(design, len(parts)), 1200)
        patched = False
        if patch:
            design, dropped2 = apply_patch(design, patch)
            dropped += [f"critique: {d}" for d in dropped2]
            patched = True
    except (RuntimeError, ValueError) as exc:
        return {"ok": False, "why": str(exc)}
    notes = str(a.get("notes") or "")
    if patch and isinstance(patch.get("notes"), str) and patch["notes"].strip():
        notes = patch["notes"]
    if (q := quoted_copy(notes)):
        dropped.append(f"notes: the reading quoted the email's own copy ({q[:40]!r}) — notes dropped; "
                       f"a design carries technique, never material")
        notes = ""
    seq = sequence_for_library(design)
    info = {"tier": tier, "edge": edge, "strips": len(parts), "calls": calls,
            "mobile": bool(mobile_sheet), "critiqued": patched, "dropped": dropped}
    got = es.file_structure(
        name=(title or "swiped design")[:120], sequence=seq, source="swipe",
        review="proposed", fits_intents=list(a.get("fits_intents") or []),
        fits_formats=list(a.get("fits_formats") or []),
        source_url=src or url, source_asset_id=asset_id, notes=notes,
        design=design, look=look_of_design(design), read_info=info)
    got["design"], got["read"] = design, info
    got.setdefault("dropped", dropped)
    return got


# ---------------------------------------------------------------------------
# The preview: a design executed with THIS brand's material (Phase 4)
# ---------------------------------------------------------------------------
def preview_blocks(tenant: str) -> list[dict]:
    """Sample blocks a structure is previewed with for one brand — its own
    photograph as the hero, its own three products, fixed sample copy that
    is plainly sample copy. Nothing here is a draft; it exists so "would
    this recreate the reference?" is answered on the card, before approval,
    with the brand's material rather than lorem or another brand's."""
    from . import kb
    ents = []
    for e in kb.entities(tenant)[:12]:
        a = getattr(e, "attributes", None) or {}
        if getattr(e, "name", "") and a.get("image"):
            ents.append({"name": e.name, "price": str(a.get("price") or ""),
                         "url": str(a.get("url") or "#"), "image": str(a["image"])})
        if len(ents) == 3:
            break
    hero = ""
    got = assets_for(tenant, "lifestyle")
    if got["ok"]:
        hero = got["assets"][0].url or ""
    elif ents:
        hero = ents[0]["image"]
    blocks: list[dict] = []
    if hero:
        blocks.append({"type": "hero", "image": hero, "alt": "the brand's own photograph",
                       "headline": "A sample headline, set the design's way",
                       "sub": "Sample copy — the drafter writes the real words."})
    else:
        blocks.append({"type": "heading", "text": "A sample headline, set the design's way", "level": 1})
    blocks += [{"type": "heading", "text": "A section kicker"},
               {"type": "text", "html": "<p>Sample body copy, so the measure, the leading and the "
                                        "ink on this ground can be judged. The real email carries "
                                        "this brand's own words and claims.</p>"},
               {"type": "text", "html": "<p>A second paragraph, for the layouts that deal words "
                                        "into two columns.</p>"}]
    if ents:
        blocks.append({"type": "products", "items": ents})
    blocks += [{"type": "quote", "text": "A pull-quote stands in for an approved claim.",
                "attribution": "sample"},
               {"type": "divider"},
               {"type": "cta", "label": "The ask", "url": "#"},
               {"type": "ps", "text": "A postscript, set apart above the footer."}]
    return blocks


def preview_html(tenant: str, design: dict) -> tuple[str, str]:
    """`(html, why_not)`: the design executed with the brand's live theme —
    or its proposal when nothing is approved yet, said — on its own material.
    '' with a reason when the brand has no theme at all."""
    from . import brand_theme, email_render
    theme = brand_theme.live_theme(tenant)
    note = ""
    if not theme:
        theme = dict((brand_theme.proposed(tenant) or {}).get("theme") or {})
        note = "through the PROPOSED theme — nothing is approved on the Brand tab yet"
    if not theme:
        return "", "this brand has no theme yet — derive and approve one on the Brand tab to preview"
    html = email_render.render_design(design, theme, preview_blocks(tenant),
                                      preheader="Design preview")
    return html, note
