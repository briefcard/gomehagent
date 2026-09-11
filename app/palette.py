"""A brand's PALETTE OF ROLES — the colours that fill a design's grounds.

INITIATIVE-email-design.md, Phase 2. A design (`email_design`) names only
ROLES — "the hero sits on the dark ground, the ask is the accent" — and this
module is where a brand's actual colours are put under those names, so the
same design is navy and cream for one brand and forest and bone for another.

Three rules, all inherited from `brand_theme`:

* **Derived, never invented.** A role a source supplies is that source's, and
  says so. A role no source supplies is COMPUTED from what exists by one
  stated rule (the dark ground is the ink; the tint is the accent at eight
  per cent over the surface; every ink is the readable one on its ground)
  and labelled `computed: <the rule>` — never attributed to a source, never
  silent.
* **Checked, and a failure is a finding.** Every ground/ink pair is measured
  for contrast (WCAG's relative luminance); a pair below the bar is a named
  finding on the card, not a quiet fallback to something else.
* **Proposed, never live.** Nothing here writes a theme; `brand_theme.derive`
  proposes, the owner approves, and an owner-edited role survives re-derives
  like every other edited field.

The arithmetic lives here rather than in `brand_theme` because the renderer's
DEFAULT palette is the same rule applied to its default colours — one rule,
in one place, for both.
"""
from __future__ import annotations

import colorsys
import re

from .email_design import ROLES

_HEX = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

#: Grounds and the ink that reads on each — the pairs the findings measure.
INK_OF = {"page": "ink", "surface": "ink", "dark": "dark_ink", "tint": "tint_ink",
          "accent": "accent_ink"}
#: WCAG AA: 4.5:1 for body text; 3:1 for large text and secondary lines.
BAR_TEXT, BAR_LARGE = 4.5, 3.0


# ---------------------------------------------------------------------------
# Arithmetic
# ---------------------------------------------------------------------------
def parse(hexv) -> tuple[int, int, int] | None:
    m = _HEX.match(str(hexv or "").strip())
    if not m:
        return None
    h = m.group(1)
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))    # type: ignore[return-value]


def to_hex(rgb) -> str:
    r, g, b = (max(0, min(255, int(round(x)))) for x in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def norm(hexv) -> str:
    """`#rrggbb`, lower-case, or '' when it is not a colour."""
    rgb = parse(hexv)
    return to_hex(rgb) if rgb else ""


def luminance(hexv) -> float:
    """WCAG relative luminance, 0 (black) to 1 (white)."""
    rgb = parse(hexv)
    if not rgb:
        return 0.0
    def _lin(c: int) -> float:
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (_lin(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b) -> float:
    """WCAG contrast ratio between two colours, 1 to 21."""
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return round((hi + 0.05) / (lo + 0.05), 2)


def on(hexv, dark: str = "#1c1e22", light: str = "#ffffff") -> str:
    """The readable ink on a ground — whichever of the two contrasts more.
    (`brand_theme._on`'s luminance rule, kept: light type on anything that
    is not clearly light.)"""
    return dark if luminance(hexv) > 0.35 else light


def mix(a, b, t: float) -> str:
    """`a` moved `t` of the way towards `b`."""
    ra, rb = parse(a), parse(b)
    if not ra or not rb:
        return norm(a) or norm(b)
    return to_hex(tuple(x + (y - x) * t for x, y in zip(ra, rb)))


def saturation(hexv) -> float:
    rgb = parse(hexv)
    if not rgb:
        return 0.0
    return colorsys.rgb_to_hsv(*(c / 255.0 for c in rgb))[1]


# ---------------------------------------------------------------------------
# Filling the roles
# ---------------------------------------------------------------------------
def fill(given: dict | None, colors: dict | None) -> tuple[dict, dict]:
    """`(palette, how)` — every role filled, and for each role how: "given",
    "from colors.<field>", or "computed: <rule>" for a role no source gave. `given` is what the sources proposed under
    role names; `colors` is the renderer-shaped `theme["colors"]` the older
    fields already hold (bg, surface, text, muted, accent, accent_text,
    border), read for the roles they already are.
    """
    g = {k: norm(v) for k, v in (given or {}).items() if k in ROLES and norm(v)}
    c = {k: norm(v) for k, v in (colors or {}).items() if norm(v)}
    p: dict = {}
    how: dict = {}

    def _take(role: str, *cands, rule: str = ""):
        """The first candidate that exists: a role a source gave (`given`),
        else the older theme colour that already IS that role (`from
        colors.<field>` — the deriver resolves it to that field's source)."""
        for v, origin in cands:
            if v:
                p[role] = v
                how[role] = origin
                return
    _take("surface", (g.get("surface"), "given"), (c.get("surface"), "from colors.surface"))
    _take("page", (g.get("page"), "given"), (c.get("bg"), "from colors.bg"))
    _take("ink", (g.get("ink"), "given"), (c.get("text"), "from colors.text"))
    _take("muted", (g.get("muted"), "given"), (c.get("muted"), "from colors.muted"))
    _take("accent", (g.get("accent"), "given"), (c.get("accent"), "from colors.accent"))
    _take("border", (g.get("border"), "given"), (c.get("border"), "from colors.border"))
    # What is still missing is computed from what exists — each by one rule.
    if "surface" not in p:
        p["surface"], how["surface"] = "#ffffff", "computed: white, no surface on file"
    if "page" not in p:
        p["page"], how["page"] = mix(p["surface"], "#000000", 0.04), \
            "computed: the surface, four per cent towards black"
    if "ink" not in p:
        p["ink"], how["ink"] = "#1c1e22", "computed: near-black, no text colour on file"
    if "muted" not in p:
        p["muted"], how["muted"] = mix(p["ink"], p["surface"], 0.45), \
            "computed: the ink, forty-five per cent towards the surface"
    if "accent" not in p:
        p["accent"], how["accent"] = p["ink"], "computed: the ink stands in — no accent on file"
    if "border" not in p:
        p["border"], how["border"] = mix(p["surface"], p["ink"], 0.1), \
            "computed: the surface, ten per cent towards the ink"
    _take("accent_ink", (g.get("accent_ink"), "given"), (c.get("accent_text"), "from colors.accent_text"))
    if "accent_ink" not in p:
        p["accent_ink"], how["accent_ink"] = on(p["accent"]), "computed: the readable ink on the accent"
    _take("dark", (g.get("dark"), "given"))
    if "dark" not in p:
        if luminance(p["ink"]) < 0.2:
            p["dark"], how["dark"] = p["ink"], "computed: the ink, as a ground"
        else:
            p["dark"], how["dark"] = mix(p["ink"], "#000000", 0.6), \
                "computed: the ink, sixty per cent towards black — the ink itself is too light for a ground"
    _take("dark_ink", (g.get("dark_ink"), "given"))
    if "dark_ink" not in p:
        p["dark_ink"], how["dark_ink"] = on(p["dark"], dark=p["ink"], light=p["surface"]), \
            "computed: the readable ink on the dark ground"
    _take("tint", (g.get("tint"), "given"))
    if "tint" not in p:
        p["tint"], how["tint"] = mix(p["surface"], p["accent"], 0.08), \
            "computed: the accent, eight per cent over the surface"
    _take("tint_ink", (g.get("tint_ink"), "given"))
    if "tint_ink" not in p:
        p["tint_ink"], how["tint_ink"] = on(p["tint"], dark=p["ink"], light=p["surface"]), \
            "computed: the readable ink on the tint"
    _take("secondary", (g.get("secondary"), "given"))
    if "secondary" not in p:
        p["secondary"], how["secondary"] = p["muted"], "computed: the muted colour stands in — no second colour on file"
    # `how[role]` is one of "given" (a source proposed it under this name),
    # "from colors.<field>" (the older theme field that already is this
    # role) or "computed: <rule>". The deriver turns the first two into the
    # source's own name; only the third is a label of its own.
    return {k: p[k] for k in ROLES}, how


def findings(palette: dict) -> list[str]:
    """Every ground/ink pair below the bar, named with its ratio. The muted
    line is held to the large-text bar; everything else to body text."""
    out = []
    p = {k: norm(v) for k, v in (palette or {}).items()}
    for ground, ink in INK_OF.items():
        if not p.get(ground) or not p.get(ink):
            continue
        r = contrast(p[ground], p[ink])
        if r < BAR_TEXT:
            out.append(f"{ink} on {ground} is {r}:1 — below {BAR_TEXT}:1 for text")
    if p.get("muted") and p.get("surface"):
        r = contrast(p["muted"], p["surface"])
        if r < BAR_LARGE:
            out.append(f"muted on surface is {r}:1 — below {BAR_LARGE}:1 for a secondary line")
    if p.get("accent") and p.get("surface"):
        r = contrast(p["accent"], p["surface"])
        if r < BAR_LARGE:
            out.append(f"accent on surface is {r}:1 — a text link in the accent would not read; "
                       f"keep the accent to buttons and rules")
    return out


# ---------------------------------------------------------------------------
# What a brand kit says, and what the photographs say
# ---------------------------------------------------------------------------
def rank_kit(hexes) -> dict[str, tuple[str, str]]:
    """A Canva kit's colours, put under roles by one stated rule each —
    `{role: (hex, rule)}`. The first colour is the accent (the designer's
    order is the designer's; today's `colors.accent` reads the same one);
    the darkest is the dark ground and, when near black, the ink; the
    lightest is the page; a second light one the tint; the most saturated
    of what is left the secondary. Nothing is discarded that a role can
    take; what no role takes is returned under `unplaced` by the caller."""
    cols = [norm(h) for h in (hexes or []) if norm(h)]
    cols = list(dict.fromkeys(cols))
    out: dict[str, tuple[str, str]] = {}
    if not cols:
        return out
    out["accent"] = (cols[0], "the first colour in the kit")
    rest = cols[1:]
    by_l = sorted(rest, key=luminance)
    darks = [c for c in by_l if luminance(c) < 0.2]
    lights = [c for c in by_l if luminance(c) > 0.7]
    if darks:
        out["dark"] = (darks[0], "the darkest colour in the kit")
        if luminance(darks[0]) < 0.06:
            out["ink"] = (darks[0], "the darkest colour in the kit, near black")
        rest = [c for c in rest if c != darks[0]]
    if lights:
        light = sorted(lights, key=luminance, reverse=True)
        out["page"] = (light[0], "the lightest colour in the kit")
        rest = [c for c in rest if c != light[0]]
        if len(light) > 1:
            out["tint"] = (light[1], "the second-lightest colour in the kit")
            rest = [c for c in rest if c != light[1]]
    mids = [c for c in rest if c not in out.values()]
    if mids:
        sec = max(mids, key=saturation)
        out["secondary"] = (sec, "the most saturated colour in the kit after the accent")
    return out


def from_pictures(blobs: list[bytes]) -> dict[str, tuple[str, str]]:
    """The colours the brand's own product photographs are made of, as
    proposals for the roles a photograph can honestly fill: the most frequent
    colour that is not white, black or grey → `secondary`; the most frequent
    LIGHT colour → `tint`. `{role: (hex, rule)}`; nothing when there is
    nothing to say. Quantised small — a colour that does not survive a
    64-pixel thumbnail is not a colour the eye reads off the product."""
    import io
    from collections import Counter
    from PIL import Image
    count: Counter = Counter()
    n = 0
    for blob in blobs or []:
        try:
            im = Image.open(io.BytesIO(blob)).convert("RGB")
        except Exception:                                        # noqa: BLE001
            continue
        n += 1
        q = im.resize((64, 64), Image.LANCZOS).quantize(colors=16).convert("RGB")
        for freq, rgb in q.getcolors(64 * 64) or []:
            hx = to_hex(rgb)
            L, S = luminance(hx), saturation(hx)
            # White, black and grey are not brand colours. A LIGHT colour is
            # low in saturation by nature — a bone, a pale green — so the
            # light band is held to a gentler bar than the mid-tones, where
            # low saturation really is grey.
            if L > 0.94 or L < 0.04:
                continue
            if S < (0.04 if L > 0.7 else 0.18):
                continue
            count[hx] += freq
    if not count:
        return {}
    out: dict[str, tuple[str, str]] = {}
    src = f"the brand's own product photographs ({n} picture{'s' if n != 1 else ''})"
    ranked = [c for c, _ in count.most_common()]
    mid = [c for c in ranked if luminance(c) <= 0.7]
    light = [c for c in ranked if luminance(c) > 0.7]
    if mid:
        out["secondary"] = (mid[0], f"{src}: the most frequent colour that is not white, black or grey")
    if light:
        out["tint"] = (light[0], f"{src}: the most frequent light colour")
    return out
