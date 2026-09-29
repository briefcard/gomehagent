"""THE TYPE — a vetted network of face pairings, one per brand.

Owner, 2026-09-29, on an email whose headline stacked a sans kicker, a serif
headline and a handwritten word between them: "The different fonts … don't
work together and it's hard to read — there should be a network of
complementary fonts so that you don't just guess." The maker chose its own
display and accent faces per email (THE SYSTEM FIRST allowed "at most ONE
accent face"), and faces set inside baked blocks were never counted — so every
email could be three new voices, checked by nothing.

A PAIRING is a headline face and a body face chosen TOGETHER, each with the
email-safe stack an inbox falls back to and the web face a baked block is set
in. There is no accent face: a script or marker line in a reference is set in
the headline face's italic. A brand has ONE pairing — its own faces when they
are on file (the default, so the storefront and the email agree), or one of
these chosen on the Brand tab. The maker is handed the pairing and nothing
else; `faces_off` names any other face, in live text and in baked blocks.
"""
from __future__ import annotations

import re

_SERIF = "Georgia, 'Times New Roman', serif"
_SANS = "Helvetica, Arial, sans-serif"

#: The network. Each pairing is a known-good combination — a contrast of
#: structure (serif over sans, or one family in two weights), never two faces
#: competing for the same job. `web` is the face a baked block loads.
PAIRINGS: dict[str, dict] = {
    "editorial": dict(
        name="Editorial — Playfair Display over Source Sans 3",
        character="a high-contrast serif for headlines over a plain humanist sans — classic, magazine-like",
        headline=dict(family="Playfair Display", stack=f"'Playfair Display', {_SERIF}"),
        body=dict(family="Source Sans 3", stack=f"'Source Sans 3', {_SANS}")),
    "companion": dict(
        name="Companion — DM Serif Display over DM Sans",
        character="a serif and a sans drawn as one family — tidy, modern-classic",
        headline=dict(family="DM Serif Display", stack=f"'DM Serif Display', {_SERIF}"),
        body=dict(family="DM Sans", stack=f"'DM Sans', {_SANS}")),
    "luxe": dict(
        name="Luxe — Cormorant Garamond over Montserrat",
        character="a fine display serif with a geometric sans — fashion, hospitality, the high end",
        headline=dict(family="Cormorant Garamond", stack=f"'Cormorant Garamond', {_SERIF}"),
        body=dict(family="Montserrat", stack=f"'Montserrat', {_SANS}")),
    "classic": dict(
        name="Classic — Libre Baskerville over Lato",
        character="a bookish serif with a friendly sans — established, warm",
        headline=dict(family="Libre Baskerville", stack=f"'Libre Baskerville', {_SERIF}"),
        body=dict(family="Lato", stack=f"'Lato', {_SANS}")),
    "modern": dict(
        name="Modern — Inter throughout",
        character="one neutral grotesque in two weights — calm, contemporary, the pictures lead",
        headline=dict(family="Inter", stack=f"'Inter', {_SANS}"),
        body=dict(family="Inter", stack=f"'Inter', {_SANS}")),
    "bold": dict(
        name="Bold — Montserrat over Merriweather",
        character="a strong geometric sans for headlines over a sturdy reading serif",
        headline=dict(family="Montserrat", stack=f"'Montserrat', {_SANS}"),
        body=dict(family="Merriweather", stack=f"'Merriweather', {_SERIF}")),
    "system": dict(
        name="System — Georgia over Helvetica",
        character="the two faces every inbox has — nothing to load, nothing to fall back",
        headline=dict(family="Georgia", stack=_SERIF),
        body=dict(family="Helvetica", stack=_SANS)),
}

#: The web face a baked block loads for a system face — a baked block is set by
#: a browser that may not have Georgia or Helvetica installed; these are drawn
#: to the same metrics.
WEB_EQUIVALENT = {"georgia": "Gelasio", "times new roman": "Tinos", "times": "Tinos",
                  "helvetica": "Arimo", "arial": "Arimo"}

#: Names in a stack that are not a face of their own.
_ALIASES = {"-apple-system", "blinkmacsystemfont", "system-ui", "segoe ui",
            "serif", "sans-serif", "cursive", "monospace", "inherit", "initial"}


def _families(stack: str) -> list[str]:
    return [f.strip().strip("'\"").strip() for f in str(stack or "").split(",") if f.strip()]


def first_family(stack: str) -> str:
    """The face a stack asks for — its first real family, aliases skipped."""
    for f in _families(stack):
        if f.lower() not in _ALIASES:
            return f
    return ""


def _face(family: str, stack: str) -> dict:
    return {"family": family, "stack": stack or family,
            "web": WEB_EQUIVALENT.get(family.lower(), family)}


def for_theme(theme: dict | None) -> dict:
    """This brand's pairing: the one chosen on the Brand tab, else its own
    faces — matched to a pairing of the network when they are one of them."""
    font = (theme or {}).get("font") or {}
    key = str(font.get("pairing") or "").strip()
    if key in PAIRINGS:
        p = PAIRINGS[key]
        return {"key": key, "name": p["name"], "character": p["character"],
                "headline": _face(p["headline"]["family"], p["headline"]["stack"]),
                "body": _face(p["body"]["family"], p["body"]["stack"])}
    from .brand_theme import DEFAULT
    head = str(font.get("heading") or DEFAULT["font"]["heading"])
    body = str(font.get("body") or DEFAULT["font"]["body"])
    hf, bf = first_family(head) or "Georgia", first_family(body) or "Helvetica"
    for k, p in PAIRINGS.items():
        if p["headline"]["family"].lower() == hf.lower() and p["body"]["family"].lower() == bf.lower():
            return for_theme({"font": {"pairing": k}})
    return {"key": "own", "name": f"The brand's own — {hf} over {bf}",
            "character": "the faces the brand's own site is set in",
            "headline": _face(hf, head), "body": _face(bf, body)}


def allowed(pairing: dict) -> set[str]:
    """Every face name this pairing may show — its two faces, their web faces
    and every fallback in their stacks — lowercased."""
    out = set()
    for role in ("headline", "body"):
        f = pairing.get(role) or {}
        out |= {x.lower() for x in _families(f.get("stack", ""))}
        out |= {str(f.get("family", "")).lower(), str(f.get("web", "")).lower()}
    return {x for x in out if x} | _ALIASES


def faces_off(families, pairing: dict) -> list[str]:
    """The faces among `families` (CSS font-family values) this pairing does
    not have, by the face each asks for first."""
    ok = allowed(pairing)
    off = []
    for fam in families:
        f = first_family(fam)
        if f and f.lower() not in ok and f not in off:
            off.append(f)
    return off


_BAKE = re.compile(r"<!--\s*bake\s*-->(.*?)<!--\s*/bake\s*-->", re.S | re.I)


def baked_families(raw_html: str) -> list[str]:
    """The font-family values set inside baked blocks — pictures by the time
    the render is read, so only the maker's own HTML still says them."""
    return [m for frag in _BAKE.findall(raw_html or "")
            for m in re.findall(r"font-family:\s*([^;\"]+)", frag, re.I)]


def prompt_text(pairing: dict) -> str:
    """The pairing, as the maker is told it."""
    h, b = pairing["headline"], pairing["body"]
    return (f"{pairing['name']} — {pairing['character']}.\n"
            f"  headline face (display lines, headlines, product names): {h['family']} — in live text "
            f"font-family: {h['stack']}; inside a baked block load and set {h['web']}\n"
            f"  body face (everything else — body copy, kickers, buttons, captions, the footer): "
            f"{b['family']} — in live text font-family: {b['stack']}; inside a baked block {b['web']}\n"
            f"  no third face, and no accent face: a script or hand-lettered line in the reference is "
            f"set in the headline face's italic")
