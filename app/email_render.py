"""Render a canonical email to send-ready, on-brand, email-safe HTML.

The goal the owner set is speed to a SEND-READY email, not a draft somebody
still has to finish. Three things decide whether an email is send-ready, and
they are owned in three different places on purpose:

  * **Says nothing it shouldn't** — the validator, on the copy, before it ever
    reaches here. This module renders; it does not check claims.
  * **Sounds like the brand** — the voice layer, in the copy the generator
    wrote. Also upstream.
  * **Looks like the brand** — THIS module, applied through a per-client
    ``theme``. Two companies hand the same canonical blocks and get two
    visibly different, correctly-branded emails, because their theme differs.
    That is the whole "each company differs" requirement, expressed as data.

So the split is: a generator produces canonical BLOCKS (semantic, ESP-agnostic,
carrying neutral tokens like ``{{FIRST_NAME}}``) plus already-validated copy;
this renders them through the client's THEME into HTML that survives Outlook and
Gmail; then ``esp.personalize`` turns the neutral tokens native. Nothing here
knows which ESP is on the other end, and nothing here composes copy.

**Email-safe by construction.** Marketing HTML is not web HTML — Outlook renders
with Word's engine. So this is table-layout with INLINE styles, a bounded width,
a bulletproof (table-based) button, and a legal footer that is not optional:
CAN-SPAM requires a physical address and a working unsubscribe, so the footer
carries the client's address and the ``{{UNSUBSCRIBE}}`` token every time. An
email missing those is not "a thinner draft" — it is one that cannot be sent, so
the footer is added by the renderer and cannot be forgotten by a generator.
"""
from __future__ import annotations

import html as _html
import re as _re

# The neutral tokens the footer always carries; the body may carry these too.
# They stay neutral here and become native in `esp.personalize`.
UNSUB = "{{UNSUBSCRIBE}}"
BROWSER = "{{VIEW_IN_BROWSER}}"


# ---------------------------------------------------------------------------
# THEME — the per-client visual identity. Derived (Canva brand kit → Shopify
# theme → site) and owner-approved; stored per client. Everything optional has
# a sane fallback, so an incomplete theme renders a plainer email rather than
# refusing — this layer does not gate on a missing accent colour.
# ---------------------------------------------------------------------------
_DEFAULT = {
    "name": "",
    "logo_url": "", "logo_alt": "",
    "colors": {"bg": "#f2f3f5", "surface": "#ffffff", "text": "#1c1e22",
               "muted": "#6b7280", "accent": "#1f2937", "accent_text": "#ffffff",
               "border": "#e6e8ec"},
    "font": {"heading": "Georgia, 'Times New Roman', serif",
             "body": "-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"},
    # THE PALETTE OF ROLES (INITIATIVE-email-design.md, Phase 2): the twelve
    # names a DESIGN's grounds resolve through — page, surface, ink, muted,
    # accent, accent_ink, dark, dark_ink, tint, tint_ink, border, secondary.
    # Filled below from `colors` by `palette.fill`, the one rule the deriver
    # applies to a brand's own colours, so the default palette and a brand's
    # computed roles are the same arithmetic. No painter reads it until
    # Phase 4; it is in the shape now so a role is a theme field the owner
    # can approve and edit like any other.
    "palette": {},
    # KEY THE GROUNDS TO THE PICTURES (owner, 2026-09-12): with this on —
    # the default — an email's page, tint, dark and secondary are keyed to
    # the photographs chosen for it (`palette.key_to_pictures`); the
    # identity roles never move. Off, every email sits on the approved
    # palette as it is. A brand field, approved and edited like the rest.
    "keyed_grounds": True,
    "radius": "8px", "width": 600,
    # A working nav, brand data: [{"label","url"}]. Empty renders no nav bar.
    "nav": [],
    # WHO SIGNS a letter-format email. Brand data, owner-entered, and the only
    # source a `signature` block may draw on: asked for a sign-off with nobody
    # on file, a drafter invented "Maya Chen, Head of Product" and signed a
    # live customer email as her (2026-08-22). A real person's name under a
    # message they never wrote is not a copy problem, so the name cannot come
    # from the generator at all. Empty means letters go unsigned.
    "sender": {"name": "", "role": ""},
    # `socials` [{"name","url"}] and `disclaimer` are brand data too; the
    # unsubscribe/preferences are NEUTRAL TOKENS the ESP layer makes native.
    "footer": {"brand": "", "address": "", "tagline": "",
               "socials": [], "disclaimer": ""},
}


def _default_palette() -> dict:
    from . import palette as _pal
    return _pal.fill({}, _DEFAULT["colors"])[0]


_DEFAULT["palette"] = _default_palette()


#: THE LOOK: how the blocks are ARRANGED. A closed vocabulary, every value a
#: design pattern rather than anyone's artwork — the hero's treatment, the
#: type scale, the density, alternating bands, the button style, the product
#: layout. It sits ON TOP of the brand theme and never inside it: a look may
#: not change a colour or a typeface, because those are the brand's identity
#: and this is only the shape the identity is poured into. Read off a swiped
#: email in words (`email_structures.read_swipe`), kept on the structure, and
#: applied here — so "mimic the style" means the arrangement, and the words,
#: pictures, colours and faces stay the brand's own.
LOOK = {
    "hero": ("contained", "bleed", "overlay", "split"),
    "scale": ("modest", "display"),
    "density": ("tight", "regular", "airy"),
    "bands": (False, True),
    "cta": ("block", "full", "pill", "link"),
    "products": ("rows", "grid2", "grid3"),
}
_LOOK_DEFAULT = {"hero": "contained", "scale": "modest", "density": "regular",
                 "bands": False, "cta": "block", "products": "rows"}


def _look(look: dict | None) -> dict:
    """A complete look: every axis filled from the default, every value one
    the renderer knows. An unknown value is DROPPED to the default rather than
    carried — a reading that said "hero: cinematic" must not become a hero
    nothing draws."""
    out = dict(_LOOK_DEFAULT)
    for k, v in (look or {}).items():
        if k not in LOOK:
            continue
        if k == "bands":
            out[k] = bool(v)
        elif v in LOOK[k]:
            out[k] = v
    return out


#: Padding per density, for the blocks that take it.
_PAD = {"tight": (6, 24), "regular": (10, 32), "airy": (18, 40)}


#: THE TYPE SYSTEM a section is set in — a design's `type` group resolved to
#: the numbers the painters use. The house values are today's exactly, so a
#: painter reading these emits the same bytes it always did for the house;
#: a design moves them. Sizes are (hero h1, section h1); weights CSS.
_SCALE = {"modest": (26, 24), "large": (32, 28), "display": (38, 34), "poster": (48, 42)}
_WEIGHT = {"light": "300", "regular": "400", "bold": "600", "black": "800"}
_TRACK = {"tight": "-0.02em", "normal": "", "wide": "0.08em"}
_LEAD = {"tight": "1.5", "regular": "1.65", "airy": "1.8"}
_TYPE_DEFAULT = {"scale": "modest", "heading_weight": "bold", "heading_case": "sentence",
                 "tracking": "normal", "align": "left", "body_size": 16,
                 "leading": "regular", "kicker": "accent", "italic_sub": False}


def _type(spec: dict | None) -> dict:
    """The resolved type context: every value the painters read, from the
    design's `type` group or the house."""
    tp = {**_TYPE_DEFAULT, **{k: v for k, v in (spec or {}).items() if k in _TYPE_DEFAULT}}
    h1, h2 = _SCALE.get(tp["scale"], _SCALE["modest"])
    return {**tp, "h1": h1, "h2": h2, "weight": _WEIGHT.get(tp["heading_weight"], "600"),
            "case": {"upper": "text-transform:uppercase;", "title": "text-transform:capitalize;"}.get(tp["heading_case"], ""),
            "track": (f'letter-spacing:{_TRACK[tp["tracking"]]};' if _TRACK.get(tp["tracking"]) else ""),
            "talign": ("text-align:center;" if tp["align"] == "center" else ""),
            "lh": _LEAD.get(tp["leading"], "1.65")}


def _theme(theme: dict, look: dict | None = None, type_spec: dict | None = None) -> dict:
    """A theme with every field filled from the default, deep enough for the
    nested dicts the renderer reads."""
    t = {**_DEFAULT, **(theme or {})}
    for k in ("colors", "font", "footer", "sender", "palette"):
        t[k] = {**_DEFAULT[k], **((theme or {}).get(k) or {})}
    # The look rides beside the theme, never inside it: a theme row on file
    # cannot smuggle an arrangement in, and a look cannot reach a colour.
    t["look"] = _look(look)
    t["type"] = _type(type_spec)
    return t


def _esc(s) -> str:
    return _html.escape(str(s or ""))


#: The crop a slot's aspect asks for, as height per width — cut through the
#: same Shopify filename convention (`_600x480_crop_center`), so a picture
#: arrives at the slot's shape rather than being squashed into it.
_ASPECT = {"square": 1.0, "portrait": 1.25, "landscape": 0.667, "wide": 0.5}


def _sized(url: str, width: int, aspect: str = "") -> str:
    """A Shopify CDN photo asked for at the size the email actually shows.

    The catalogue sync stores the storefront's own image URL, which is the
    full-resolution original — a several-megabyte file behind a 600px hero and
    an 88px thumbnail. That is slow enough on a phone to read as a broken
    image, and it is the kind of payload a sanitising importer drops.

    Shopify's FILENAME convention (`photo_1200x.jpg`) is used rather than the
    `?width=` parameter on purpose: a query parameter would put a second `&`
    in the src, `_esc` would render it `&amp;`, and Omnisend's importer has
    already been caught turning entity references into literal text (the
    `&nbsp;` → " bsp;" incident). No new `&`, no new failure mode.

    Only Shopify's CDN is touched — guessing a resize scheme for an unknown
    host would break the URL rather than shrink it. Anything else, and any URL
    already carrying a size, is returned exactly as given.
    """
    u = str(url or "")
    if "cdn.shopify.com" not in u and "/cdn/shop/" not in u:
        return u
    base, sep, query = u.partition("?")
    stem, dot, ext = base.rpartition(".")
    if not dot or len(ext) > 5 or "/" in ext:
        return u
    if _re.search(r"_\d+x\d*$", stem):          # already sized — leave it alone
        return u
    if aspect in _ASPECT:
        return f"{stem}_{width}x{int(round(width * _ASPECT[aspect]))}_crop_center{dot}{ext}{sep}{query}"
    return f"{stem}_{width}x{dot}{ext}{sep}{query}"


# ---------------------------------------------------------------------------
# Blocks — the canonical, ESP-agnostic vocabulary a generator emits. Unknown
# block types are skipped with an HTML comment rather than raising: a renderer
# that dies on one bad block loses the whole email, and the comment leaves a
# trace for whoever is reading the source.
# ---------------------------------------------------------------------------

def _hero(b: dict, t: dict) -> str:
    """The opening picture, in one of four treatments the look chooses.

    contained  the picture, then the headline under it (the house default)
    bleed      the same, edge to edge with no rounding — a magazine opener
    overlay    the headline ON the picture, over a dark scrim, white type
    split      picture on the left, headline and sub on the right, two columns

    Every treatment is a table, because email. The overlay is the one that
    needs care: the text colour is forced white over a scrim, which is the
    one place a look touches colour — and it does so only because a headline
    in the brand's dark text on a dark photograph is unreadable, which is a
    worse offence than a white one.
    """
    c = t["colors"]
    lk = t["look"]
    tp = t["type"]
    pv, ph = _PAD[lk["density"]]
    # The size: the look's scale (the house's two steps) or the design's
    # (four). The look wins only where it says display, which the design's
    # own scale already says.
    h1 = tp["h1"] if tp["scale"] != "modest" else (38 if lk["scale"] == "display" else 26)
    lh = "1.1" if h1 >= 38 else "1.25"
    hs = f'{tp["case"]}{tp["track"]}{tp["talign"]}'
    sub_style = "font-style:italic;" if tp.get("italic_sub") else ""
    treat = t.get("image") or ""
    src = _sized(b["image"], t["width"] * 2, t.get("aspect", "")) if b.get("image") else ""
    alt = _esc(b.get("alt", ""))
    headline, sub = b.get("headline", ""), b.get("sub", "")

    if lk["hero"] == "split" and src:
        half = t["width"] // 2
        pic = (f'<td width="{half}" valign="top" style="padding:0">'
               f'<img src="{_esc(src)}" width="{half}" alt="{alt}" '
               f'style="display:block;width:100%;max-width:{half}px;height:auto;border:0'
               f'{";border-radius:" + t["radius"] if treat == "rounded" else ""}"></td>')
        words = (f'<td valign="middle" style="padding:{pv + 8}px {ph - 8}px">'
                 + (f'<h1 style="margin:0 0 8px;font-family:{t["font"]["heading"]};'
                    f'font-size:{h1 - 6}px;line-height:{lh};color:{c["text"]};font-weight:{tp["weight"]};{hs}">'
                    f'{_esc(headline)}</h1>' if headline else "")
                 + (f'<p style="margin:0;font-family:{t["font"]["body"]};font-size:15px;'
                    f'line-height:1.5;color:{c["muted"]};{sub_style}">{_esc(sub)}</p>' if sub else "")
                 + '</td>')
        cells = words + pic if t.get("split") == "right" else pic + words
        return (f'<tr><td style="padding:0"><table role="presentation" width="100%" '
                f'cellpadding="0" cellspacing="0" border="0"><tr>{cells}</tr></table></td></tr>')

    if lk["hero"] == "overlay" and src:
        return (f'<tr><td style="padding:0;background:{c["text"]} url({_esc(src)}) center/cover '
                f'no-repeat" background="{_esc(src)}" valign="bottom">'
                f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
                f'border="0"><tr><td style="padding:120px {ph}px {pv + 18}px;'
                f'background:linear-gradient(to bottom, rgba(0,0,0,0) 0%, rgba(0,0,0,.62) 100%)">'
                + (f'<h1 style="margin:0;font-family:{t["font"]["heading"]};'
                   f'font-size:{h1}px;line-height:{lh};color:#ffffff;font-weight:{tp["weight"]};{hs}">'
                   f'{_esc(headline)}</h1>' if headline else "")
                + (f'<p style="margin:8px 0 0;font-family:{t["font"]["body"]};font-size:16px;'
                   f'line-height:1.5;color:#ffffff;opacity:.9;{sub_style}">{_esc(sub)}</p>' if sub else "")
                + '</td></tr></table></td></tr>')

    radius = "0" if lk["hero"] == "bleed" else f'{t["radius"]} {t["radius"]} 0 0'
    # A DESIGN'S TREATMENT of the opening picture: inside the margins,
    # rounded on every corner, a circle, a keyline, or on the tint (the one
    # "duotone" email can honestly do without touching the pixels).
    if treat == "contained" and t.get("cta"):
        w = t["width"] - 2 * ph
        img = (f'<tr><td style="padding:{pv}px {ph}px 0"><img src="{_esc(src)}" width="{w}" '
               f'alt="{alt}" style="display:block;width:100%;max-width:{w}px;height:auto;border:0;'
               f'border-radius:{t["radius"]}"></td></tr>') if src else ""
    elif treat in ("rounded", "circle", "framed", "duotone") and src:
        w = t["width"] - 2 * ph
        if treat == "circle":
            w = min(w, 320)
        rad = {"rounded": "16px", "circle": "50%", "framed": t["radius"], "duotone": t["radius"]}[treat]
        frame = f'border:1px solid {c["border"]};padding:8px;' if treat == "framed" else ""
        ground = f'background:{t["palette"]["tint"]};padding:{pv + 10}px {ph}px;' if treat == "duotone" else f'padding:{pv}px {ph}px 0;'
        img = (f'<tr><td align="center" style="{ground}"><img src="{_esc(src)}" width="{w}" '
               f'alt="{alt}" style="display:block;width:100%;max-width:{w}px;height:auto;border:0;'
               f'border-radius:{rad};{frame}margin:0 auto"></td></tr>')
    else:
        img = (f'<tr><td style="padding:0"><img src="{_esc(src)}" width="{t["width"]}" '
               f'alt="{alt}" style="display:block;width:100%;max-width:{t["width"]}px;'
               f'height:auto;border:0;border-radius:{radius}"></td></tr>') if src else ""
    head = (f'<tr><td style="padding:{pv + 18}px {ph}px 4px">'
            f'<h1 style="margin:0;font-family:{t["font"]["heading"]};'
            f'font-size:{h1}px;line-height:{lh};color:{c["text"]};font-weight:{tp["weight"]};{hs}">'
            f'{_esc(headline)}</h1></td></tr>') if headline else ""
    subr = (f'<tr><td style="padding:6px {ph}px 0">'
            f'<p style="margin:0;font-family:{t["font"]["body"]};font-size:16px;'
            f'line-height:1.5;color:{c["muted"]};{sub_style}">{_esc(sub)}</p></td></tr>') if sub else ""
    return img + head + subr


def _text(b: dict, t: dict) -> str:
    c = t["colors"]
    # `html` is trusted here: it is the generator's validated copy, and it
    # carries neutral tokens the renderer must not escape (escaping would turn
    # `{{FIRST_NAME}}` into text and a link into a string). The validator is the
    # gate on this content, upstream — see the module docstring.
    body = b.get("html") or (f"<p>{_esc(b.get('text',''))}</p>" if b.get("text") else "")
    # Bare <p> tags get an inline rhythm — email clients reset paragraph
    # margins their own way, and "it just looks like long text" (owner,
    # 2026-08-21) is what default margins read as. Styled tags are left as
    # the generator wrote them.
    body = body.replace("<p>", '<p style="margin:0 0 14px">')
    pv, ph = _PAD[t["look"]["density"]]
    lh = {"tight": "1.5", "regular": "1.65", "airy": "1.8"}[t["look"]["density"]]
    tp = t["type"]
    if tp["leading"] != "regular":
        lh = tp["lh"]
    return (f'<tr><td style="padding:{pv}px {ph}px 2px;font-family:{t["font"]["body"]};'
            f'font-size:{tp["body_size"]}px;line-height:{lh};color:{c["text"]}{";" + tp["talign"].rstrip(";") if tp["talign"] else ""}">{body}</td></tr>')


def _cta(b: dict, t: dict) -> str:
    """The ask, in the style the look chooses: a block button (the house
    default), a full-width bar, a pill, or a plain text link with an arrow.
    A bulletproof button either way — a table cell with the fill, not a
    styled <a>, so Outlook renders the background at all."""
    c = t["colors"]
    lk = t["look"]
    pv, ph = _PAD[lk["density"]]
    url, label = _esc(b.get("url", "#")), _esc(b.get("label", "Shop now"))
    spec = t.get("cta")
    if spec:
        # A DESIGN'S ASK: filled, outlined, an underlined line, a line with
        # an arrow, or a full-width bar; square, soft or pill; three sizes;
        # its case and where it sits. On the accent ground the filled
        # button inverts (surface on accent) so it still reads as a button.
        radius = {"square": "0", "soft": t["radius"], "pill": "999px"}.get(spec["radius"], t["radius"])
        pad, fs = {"small": ("10px 20px", "14px"), "regular": ("14px 28px", "15px"),
                   "large": ("18px 36px", "17px")}.get(spec["size"], ("14px 28px", "15px"))
        case = {"upper": "text-transform:uppercase;letter-spacing:.06em;",
                "title": "text-transform:capitalize;"}.get(spec["case"], "")
        align = ' align="center"' if spec["align"] == "center" else ""
        fam = t["font"]["body"]
        on_accent = t.get("ground") == "accent"
        # On the accent ground `c["surface"]` IS the accent (the ground
        # context paints surface as the ground), so the inversion reads the
        # palette's true surface — the first cut painted accent on accent.
        pal = t.get("palette") or {}
        fill, ink = ((pal.get("surface", "#ffffff"), pal.get("accent", c["accent"])) if on_accent
                     else (c["accent"], c["accent_text"]))
        link_ink = c["text"] if on_accent else c["accent"]
        if spec["style"] in ("arrow", "underline"):
            deco = "underline" if spec["style"] == "underline" else "none"
            tail = " &rarr;" if spec["style"] == "arrow" else ""
            return (f'<tr><td{align} style="padding:{pv}px {ph}px {pv + 8}px">'
                    f'<a href="{url}" style="font-family:{fam};font-size:{fs};font-weight:600;'
                    f'color:{link_ink};text-decoration:{deco};{case}">{label}{tail}</a></td></tr>')
        if spec["style"] == "outline":
            return (f'<tr><td{align} style="padding:{pv + 2}px {ph}px {pv + 10}px"><table role="presentation" '
                    f'cellpadding="0" cellspacing="0" border="0"{" align=center" if align else ""}><tr>'
                    f'<td style="border:2px solid {link_ink};border-radius:{radius}">'
                    f'<a href="{url}" style="display:inline-block;padding:{pad};font-family:{fam};'
                    f'font-size:{fs};font-weight:600;color:{link_ink};text-decoration:none;{case}">'
                    f'{label}</a></td></tr></table></td></tr>')
        full = spec["style"] == "full"
        return (f'<tr><td{align} style="padding:{pv + 2}px {ph}px {pv + 10}px"><table role="presentation" '
                f'cellpadding="0" cellspacing="0" border="0"{" width=100%" if full else (" align=center" if align else "")}><tr>'
                f'<td style="background:{fill};border-radius:{radius};{"text-align:center;" if full else ""}">'
                f'<a href="{url}" style="display:{"block" if full else "inline-block"};'
                f'padding:{pad};font-family:{fam};font-size:{fs};'
                f'font-weight:600;color:{ink};text-decoration:none;{case}">'
                f'{label}</a></td></tr></table></td></tr>')
    if lk["cta"] == "link":
        return (f'<tr><td style="padding:{pv}px {ph}px {pv + 8}px">'
                f'<a href="{url}" style="font-family:{t["font"]["body"]};font-size:16px;'
                f'font-weight:600;color:{c["accent"]};text-decoration:none">'
                f'{label} &rarr;</a></td></tr>')
    radius = "999px" if lk["cta"] == "pill" else t["radius"]
    width = ' width="100%"' if lk["cta"] == "full" else ""
    align = 'text-align:center;' if lk["cta"] == "full" else ""
    return (f'<tr><td style="padding:{pv + 2}px {ph}px {pv + 10}px"><table role="presentation" '
            f'cellpadding="0" cellspacing="0" border="0"{width}><tr>'
            f'<td style="background:{c["accent"]};border-radius:{radius};{align}">'
            f'<a href="{url}" style="display:{"block" if lk["cta"] == "full" else "inline-block"};'
            f'padding:14px 28px;font-family:{t["font"]["body"]};font-size:15px;'
            f'font-weight:600;color:{c["accent_text"]};text-decoration:none">'
            f'{label}</a></td></tr></table></td></tr>')


def _products(b: dict, t: dict) -> str:
    """Product rows, not cramped columns. Three names squeezed into thirds
    wrapped badly on the owner's phone and nothing about them said
    "tappable" — each product is a full-width row now: photo left when the
    sync has one, name in the brand accent with the price under it, an
    accent arrow on the right, and the WHOLE row is one link."""
    c = t["colors"]
    pv, ph = _PAD[t["look"]["density"]]
    if t["look"]["products"] in ("grid2", "grid3"):
        return _product_grid(b, t, 2 if t["look"]["products"] == "grid2" else 3)
    rows = []
    for p in (b.get("items") or [])[:3]:
        url = p.get("url") or "#"
        img_td = (f'<td width="96" valign="top" style="padding:2px 14px 2px 0">'
                  f'<a href="{_esc(url)}">'
                  f'<img src="{_esc(_sized(p["image"], 176, "square"))}" width="88" '
                  f'alt="{_esc(p.get("name", ""))}" style="display:block;width:88px;'
                  f'height:88px;border:0;border-radius:{"50%" if t.get("image") == "circle" else t["radius"]};'
                  f'background:{c["border"]}"></a></td>'
                  if p.get("image") else "")
        price = (f'<div style="font-family:{t["font"]["body"]};font-size:14px;'
                 f'color:{c["muted"]};padding-top:2px">{_esc(p.get("price", ""))}</div>'
                 if p.get("price") else "")
        rows.append(
            f'<tr><td style="padding:10px 0;border-bottom:1px solid {c["border"]}">'
            f'<table role="presentation" width="100%" cellpadding="0" '
            f'cellspacing="0" border="0"><tr>{img_td}'
            f'<td valign="middle"><a href="{_esc(url)}" style="text-decoration:none">'
            f'<div style="font-family:{t["font"]["body"]};font-size:16px;'
            f'font-weight:600;color:{c["accent"]}">{_esc(p.get("name", ""))}</div>'
            f'{price}</a></td>'
            f'<td width="30" align="right" valign="middle"><a href="{_esc(url)}" '
            f'style="font-family:{t["font"]["body"]};font-size:18px;font-weight:700;'
            f'text-decoration:none;color:{c["accent"]}">→</a></td>'
            f'</tr></table></td></tr>')
    if not rows:
        return ""
    return (f'<tr><td style="padding:4px {ph}px {pv + 2}px"><table role="presentation" '
            f'width="100%" cellpadding="0" cellspacing="0" border="0">'
            f'{"".join(rows)}</table></td></tr>')


def _product_grid(b: dict, t: dict, cols: int) -> str:
    """Products as a grid of cards — the catalogue shape a swipe may carry.
    Two or three across, square picture on top, name and price under it, the
    whole card one link. Cells are fixed-width table cells so Outlook keeps
    them side by side; on a narrow phone the two-up still fits and the
    three-up is the one the reader pinches, which is the trade the swipe
    already made. Rows of `cols`, up to six products."""
    c = t["colors"]
    pv, ph = _PAD[t["look"]["density"]]
    items = [p for p in (b.get("items") or [])[:6] if p.get("name")]
    if not items:
        return ""
    inner = t["width"] - 2 * ph
    gap = 12
    cw = (inner - gap * (cols - 1)) // cols
    cells = []
    for p in items:
        url = _esc(p.get("url") or "#")
        prad = {"rounded": "16px", "circle": "50%"}.get(t.get("image") or "", t["radius"])
        pic = (f'<img src="{_esc(_sized(p["image"], cw * 2, t.get("aspect") or "square"))}" width="{cw}" '
               f'alt="{_esc(p.get("name", ""))}" style="display:block;width:100%;'
               f'max-width:{cw}px;height:auto;border:0;border-radius:{prad};'
               f'background:{c["border"]}">' if p.get("image") else
               f'<div style="width:100%;height:{cw}px;background:{c["border"]};'
               f'border-radius:{t["radius"]}"></div>')
        price = (f'<div style="font-family:{t["font"]["body"]};font-size:14px;'
                 f'color:{c["muted"]};padding-top:2px">{_esc(p.get("price", ""))}</div>'
                 if p.get("price") else "")
        cells.append(
            f'<td width="{cw}" valign="top" style="padding:0 0 {gap}px">'
            f'<a href="{url}" style="text-decoration:none">{pic}'
            f'<div style="font-family:{t["font"]["body"]};font-size:15px;font-weight:600;'
            f'color:{c["accent"]};padding-top:8px">{_esc(p.get("name", ""))}</div>'
            f'{price}</a></td>')
    rows = []
    spacer = f'<td width="{gap}" style="font-size:0;line-height:0">&nbsp;</td>'
    for i in range(0, len(cells), cols):
        row = cells[i:i + cols]
        # A short last row keeps its cell width rather than stretching.
        rows.append("<tr>" + spacer.join(row) + "</tr>")
    return (f'<tr><td style="padding:{pv}px {ph}px {pv}px"><table role="presentation" '
            f'width="100%" cellpadding="0" cellspacing="0" border="0">'
            f'{"".join(rows)}</table></td></tr>')


def _heading(b: dict, t: dict) -> str:
    """A scannable section heading — level 1 is the email's one headline,
    anything else a section KICKER: small caps in the brand accent, the
    device that makes a section read as designed rather than as more
    paragraph. The owner's live drafts read as "just long text" while the
    section heads were plain bold lines one size off the body."""
    c = t["colors"]
    tp = t["type"]
    pv, ph = _PAD[t["look"]["density"]]
    display = t["look"]["scale"] == "display" or tp["scale"] in ("display", "poster")
    hs = f'{tp["case"]}{tp["track"]}{tp["talign"]}'
    if int(b.get("level") or 2) <= 1:
        size = tp["h2"] if tp["scale"] != "modest" else (34 if display else 24)
        return (f'<tr><td style="padding:{pv + 6}px {ph}px 2px">'
                f'<div style="font-family:{t["font"]["heading"]};'
                f'font-size:{size}px;'
                f'font-weight:{"700" if tp["weight"] == "600" else tp["weight"]};line-height:{"1.1" if display else "1.25"};'
                f'color:{c["text"]};{hs}">{_esc(b.get("text", ""))}</div></td></tr>')
    # At display scale the section head is a real title rather than a
    # kicker — the one reading of "big type" that survives a small screen.
    if display:
        return (f'<tr><td style="padding:{pv + 4}px {ph}px 0">'
                f'<div style="font-family:{t["font"]["heading"]};font-size:22px;'
                f'font-weight:700;line-height:1.2;color:{c["text"]};{hs}">'
                f'{_esc(b.get("text", ""))}</div></td></tr>')
    # THE KICKER, in the style the design names: small capitals in the
    # accent (the house), in the ink, with a short rule beneath, or none —
    # which sets it as a plain small heading rather than dropping it.
    k = tp["kicker"]
    if k == "pill":
        # A FILLED PILL: small capitals on the tint, in the ink — the label
        # a newsletter puts over its lead story.
        pal = t.get("palette") or {}
        return (f'<tr><td style="padding:{pv + 4}px {ph}px 0{";text-align:center" if tp["talign"] else ""}">'
                f'<span style="display:inline-block;padding:5px 12px;border-radius:999px;'
                f'background:{pal.get("tint", c["bg"])};font-family:{t["font"]["body"]};'
                f'font-size:12px;font-weight:700;letter-spacing:1px;text-transform:uppercase;'
                f'color:{pal.get("tint_ink", c["text"])}">{_esc(b.get("text", ""))}</span></td></tr>')
    col = c["text"] if k in ("caps", "rule", "none") else c["accent"]
    caps = "" if k == "none" else "letter-spacing:1.5px;text-transform:uppercase;"
    rule = (f'<div style="width:28px;height:2px;background:{c["accent"]};margin:6px 0 0'
            f'{";margin-left:auto;margin-right:auto" if tp["talign"] else ""}"></div>' if k == "rule" else "")
    return (f'<tr><td style="padding:{pv + 4}px {ph}px 0">'
            f'<div style="font-family:{t["font"]["body"]};font-size:13px;'
            f'font-weight:700;{caps}'
            f'color:{col};{tp["talign"]}">{_esc(b.get("text", ""))}</div>{rule}</td></tr>')


def _quote(b: dict, t: dict) -> str:
    """A pull-quote — an approved claim given room. Serif, larger, an accent
    rule on the left; the one block that makes proof read as proof."""
    c = t["colors"]
    who = (f'<div style="font-family:{t["font"]["body"]};font-size:13px;'
           f'color:{c["muted"]};padding-top:8px">{_esc(b.get("attribution", ""))}'
           f'</div>') if b.get("attribution") else ""
    return (f'<tr><td style="padding:16px 32px">'
            f'<table role="presentation" width="100%" cellpadding="0" '
            f'cellspacing="0" border="0"><tr>'
            f'<td width="4" style="background:{c["accent"]};border-radius:2px;'
            f'font-size:0;line-height:0"> </td>'
            f'<td style="padding:2px 0 2px 18px;font-family:{t["font"]["heading"]};'
            f'font-size:19px;line-height:1.5;font-style:italic;color:{c["text"]}">'
            f'{_esc(b.get("text", ""))}{who}</td>'
            f'</tr></table></td></tr>')


def _list(b: dict, t: dict) -> str:
    """A checklist — short scannable points with accent marks, for the
    education-shaped email a paragraph run would bury. A DESIGN may set the
    list another way (`section.list`): pill buttons two across, rows with an
    arrow and a rule between them, or plain lines."""
    c = t["colors"]
    style = t.get("list_style") or "check"
    items = [str(i) for i in (b.get("items") or [])[:6] if str(i or "").strip()]
    if not items:
        return ""
    pv, ph = _PAD[t["look"]["density"]]
    fam = t["font"]["body"]
    if style == "pill":
        gap = 12
        cw = (t["width"] - 2 * ph - gap) // 2
        cells = [(f'<td width="{cw}" style="padding:0 0 {gap}px"><div style="border:1px solid {c["border"]};'
                  f'border-radius:999px;padding:12px 14px;text-align:center;font-family:{fam};font-size:14px;'
                  f'font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:{c["text"]};'
                  f'background:{(t.get("palette") or {}).get("page", c["bg"])}">{_esc(it)}</div></td>') for it in items]
        sp = f'<td width="{gap}" style="font-size:0;line-height:0">&nbsp;</td>'
        rows = "".join("<tr>" + sp.join(cells[i:i + 2]) + "</tr>" for i in range(0, len(cells), 2))
        return (f'<tr><td style="padding:{pv}px {ph}px"><table role="presentation" width="100%" '
                f'cellpadding="0" cellspacing="0" border="0">{rows}</table></td></tr>')
    if style == "arrow":
        rows = "".join(
            f'<tr><td style="padding:12px 0;border-top:1px solid {c["border"]}"><table role="presentation" '
            f'width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
            f'<td style="font-family:{t["font"]["heading"]};font-size:18px;font-weight:700;line-height:1.3;'
            f'color:{c["text"]}">{_esc(it)}</td>'
            f'<td width="28" align="right" style="font-family:{fam};font-size:18px;font-weight:700;'
            f'color:{c["accent"]}">&rarr;</td></tr></table></td></tr>' for it in items)
        return (f'<tr><td style="padding:{pv}px {ph}px"><table role="presentation" width="100%" '
                f'cellpadding="0" cellspacing="0" border="0">{rows}</table></td></tr>')
    if style == "plain":
        rows = "".join(f'<tr><td style="font-family:{fam};font-size:16px;line-height:1.55;color:{c["text"]};'
                       f'padding:4px 0">{_esc(it)}</td></tr>' for it in items)
        return (f'<tr><td style="padding:{pv}px {ph}px"><table role="presentation" width="100%" '
                f'cellpadding="0" cellspacing="0" border="0">{rows}</table></td></tr>')
    rows = "".join(
        f'<tr><td width="26" valign="top" style="font-family:{t["font"]["body"]};'
        f'font-size:16px;font-weight:700;color:{c["accent"]};padding:5px 0">✓</td>'
        f'<td style="font-family:{t["font"]["body"]};font-size:16px;'
        f'line-height:1.55;color:{c["text"]};padding:5px 0">{_esc(item)}</td></tr>'
        for item in (b.get("items") or [])[:6] if str(item or "").strip())
    if not rows:
        return ""
    return (f'<tr><td style="padding:8px 32px"><table role="presentation" '
            f'width="100%" cellpadding="0" cellspacing="0" border="0">'
            f'{rows}</table></td></tr>')


def _stat(b: dict, t: dict) -> str:
    """One big number with its caption — a claim's figure, given weight."""
    c = t["colors"]
    return (f'<tr><td align="center" style="padding:18px 32px 14px">'
            f'<div style="font-family:{t["font"]["heading"]};font-size:44px;'
            f'font-weight:700;line-height:1;color:{c["accent"]}">'
            f'{_esc(b.get("value", ""))}</div>'
            f'<div style="font-family:{t["font"]["body"]};font-size:14px;'
            f'color:{c["muted"]};padding-top:6px">{_esc(b.get("caption", ""))}'
            f'</div></td></tr>')


def _banner(b: dict, t: dict) -> str:
    """A full-width accent strip carrying one short line — announcement
    emphasis without a second CTA."""
    c = t["colors"]
    return (f'<tr><td style="padding:14px 32px">'
            f'<table role="presentation" width="100%" cellpadding="0" '
            f'cellspacing="0" border="0"><tr>'
            f'<td align="center" style="background:{c["accent"]};'
            f'border-radius:{t["radius"]};padding:16px 20px;'
            f'font-family:{t["font"]["body"]};font-size:16px;font-weight:600;'
            f'color:{c["accent_text"]}">{_esc(b.get("text", ""))}</td>'
            f'</tr></table></td></tr>')


def _divider(b: dict, t: dict) -> str:
    style = t.get("divider")
    c = t["colors"]
    if style == "none":
        return ""
    if style == "thick":
        return (f'<tr><td style="padding:12px 32px"><div style="height:3px;'
                f'background:{c["text"]};line-height:3px"> </div></td></tr>')
    if style == "dotted":
        return (f'<tr><td style="padding:8px 32px"><div style="height:0;'
                f'border-top:2px dotted {c["border"]};line-height:0"> </div></td></tr>')
    if style == "ornament":
        return (f'<tr><td align="center" style="padding:10px 32px;font-family:{t["font"]["heading"]};'
                f'font-size:16px;color:{c["accent"]};line-height:1">&#10022;</td></tr>')
    return (f'<tr><td style="padding:8px 32px"><div style="height:1px;'
            f'background:{t["colors"]["border"]};line-height:1px"> </div></td></tr>')


#: The drafter's own "P.S." prefix, stripped so it does not sit under the
#: renderer's label and read "P.S. P.S." — which shipped live (2026-08-22).
#:
#: The first cut allowed at most ONE optional `<p>` before the label, so it
#: worked on `<p>P.S. …` and missed `<p>P.S.</p><p>…` and
#: `<p><strong>P.S.</strong> …`. Any run of tags is skipped now, before and
#: after the label, because where a writer puts their emphasis tags is not
#: something a prompt should have to standardise. The lookahead stops it
#: eating a word that merely starts with those letters ("PS5", "Psychology").
#:
#: Only whitespace and punctuation are consumed AFTER the label — never a
#: closing tag. Eating one leaves its opener unbalanced (`<p><strong>P.S.
#: </strong> …` became `<p><strong>…` with nothing to close it, which bolds
#: the rest of the email). The empty `<p></p>` a stripped label can leave
#: behind is cleaned separately, where it cannot unbalance anything.
_PS_LABEL = _re.compile(
    r"^((?:\s|<[^>]+>)*)P\.?\s?S\.?(?![A-Za-z0-9])[\s:—\-]*", _re.I)


def _signature(b: dict, t: dict) -> str:
    """A sign-off — the block that makes a letter a letter.

    An email that closes with a person's name is a different object from one
    that closes with a logo: it reads as written TO someone rather than
    broadcast AT them, which is the whole A-pile idea (a personal-looking
    letter survives the sort a commercial-looking mailer does not). The name
    is brand data, never invented here.
    """
    c = t["colors"]
    role = (f'<div style="font-family:{t["font"]["body"]};font-size:14px;'
            f'color:{c["muted"]};padding-top:2px">{_esc(b.get("role", ""))}'
            f'</div>') if b.get("role") else ""
    return (f'<tr><td style="padding:14px 32px 4px">'
            f'<div style="font-family:{t["font"]["body"]};font-size:16px;'
            f'line-height:1.6;color:{c["text"]}">{_esc(b.get("text", ""))}</div>'
            f'<div style="font-family:{t["font"]["heading"]};font-size:17px;'
            f'color:{c["text"]};padding-top:6px">{_esc(b.get("name", ""))}</div>'
            f'{role}</td></tr>')


def _ps(b: dict, t: dict) -> str:
    """The postscript, set apart above the footer.

    Kept as its own block rather than an ordinary paragraph because of what it
    is: the line most likely to be read after the subject, and — by Hormozi's
    own reported numbers — the highest click-through element in his sends. It
    gets a rule above it and its own rhythm, and any link inside it points at
    the SAME destination as the CTA; one ask per email is enforced upstream.
    """
    c = t["colors"]
    body = b.get("html") or _esc(b.get("text", ""))
    # The label is the renderer's, so a drafter that also wrote "P.S." — which
    # is the natural thing to write — must not produce "P.S. P.S.". Strip one
    # leading label rather than asking the prompt to remember not to type it.
    body = _PS_LABEL.sub(r"\1", body, count=1)
    body = _re.sub(r"^(?:\s|<p[^>]*>\s*</p>)+", "", body)
    return (f'<tr><td style="padding:18px 32px 6px">'
            f'<div style="border-top:1px solid {c["border"]};padding-top:14px;'
            f'font-family:{t["font"]["body"]};font-size:15px;line-height:1.6;'
            f'color:{c["text"]}"><span style="font-weight:600">P.S.</span> '
            f'{body}</div></td></tr>')


def _image(b: dict, t: dict) -> str:
    """A section's own picture — a slot the design asked for, filled from
    the brand's library (never by a drafter: the filler is the only writer
    of this block). Cut to the slot's aspect through the CDN, treated as
    the section's `image` says, live alt text always."""
    pv, ph = _PAD[t["look"]["density"]]
    if b.get("mark"):
        # THE BRAND'S MARK where the reference had its logo band — never a
        # photograph. The mark is the theme's, sized to the band.
        if not t.get("logo_url"):
            return ""
        return (f'<tr><td align="center" style="padding:{pv + 6}px {ph}px">'
                f'<img src="{_esc(t["logo_url"])}" alt="{_esc(t.get("logo_alt") or t.get("name") or "")}" '
                f'height="36" style="display:inline-block;height:36px;border:0"></td></tr>')
    if not b.get("image"):
        return ""
    treat = t.get("image") or "contained"
    w = t["width"] if treat == "bleed" else t["width"] - 2 * ph
    rad = {"rounded": "16px", "circle": "50%", "bleed": "0"}.get(treat, t["radius"])
    frame = f'border:1px solid {t["colors"]["border"]};padding:8px;' if treat == "framed" else ""
    cell = (f'padding:0' if treat == "bleed" else
            f'background:{(t.get("palette") or {}).get("tint", t["colors"]["bg"])};padding:{pv + 10}px {ph}px'
            if treat == "duotone" else f'padding:{pv}px {ph}px 0')
    return (f'<tr><td align="center" style="{cell}"><img src="{_esc(_sized(b["image"], w * 2, t.get("aspect", "")))}" '
            f'width="{w}" alt="{_esc(b.get("alt", ""))}" style="display:block;width:100%;max-width:{w}px;'
            f'height:auto;border:0;border-radius:{rad};{frame}margin:0 auto"></td></tr>')


_BLOCKS = {"hero": _hero, "text": _text, "cta": _cta, "button": _cta, "image": _image,
           "heading": _heading, "products": _products, "divider": _divider,
           "quote": _quote, "list": _list, "stat": _stat, "banner": _banner,
           "signature": _signature, "ps": _ps}


def _band(row: str, bg: str) -> str:
    """Paint a block's outer cell with the band colour. Every painter emits
    `<tr><td style="…">` first, so the background is added to that first
    cell's style and nothing else moves."""
    return row.replace('<tr><td style="', f'<tr><td style="background:{bg};', 1) \
        if row.startswith('<tr><td style="') else \
        row.replace('<tr><td align="center" style="',
                    f'<tr><td align="center" style="background:{bg};', 1)


def _header(t: dict, webview: bool = True, spec: dict | None = None) -> str:
    c = t["colors"]
    if spec:
        return _header_design(t, webview, spec)
    logo = (f'<img src="{_esc(t["logo_url"])}" alt="{_esc(t["logo_alt"] or t["name"])}" '
            f'height="30" style="display:block;border:0;height:30px">'
            if t["logo_url"] else
            f'<span style="font-family:{t["font"]["heading"]};font-size:20px;'
            f'font-weight:600;color:{c["text"]}">{_esc(t["name"])}</span>')
    # Omnisend has no view-in-browser variable at all (their docs, verified
    # 2026-08-21) — a link whose href no ESP variable can fill ships as a
    # literal token, so the caller passes the provider's `webview` cap and a
    # provider without one gets a header without the link.
    view = ((f'<a href="{BROWSER}" style="font-family:{t["font"]["body"]};'
             f'font-size:12px;color:{c["muted"]};text-decoration:underline">'
             f'View in browser</a>') if webview else "")
    top = (f'<tr><td style="padding:18px 32px 0"><table role="presentation" width="100%" '
           f'cellpadding="0" cellspacing="0" border="0"><tr>'
           f'<td align="left">{logo}</td><td align="right">{view}</td>'
           f'</tr></table></td></tr>')
    # A working nav bar — real links to the store's sections. Centered, spaced,
    # in the body font, tinted to the brand text colour. Rendered only when the
    # theme carries nav items, so a plainer brand skips it cleanly.
    nav_items = [i for i in (t.get("nav") or []) if i.get("label") and i.get("url")]
    if not nav_items:
        return top
    links = (f'  <span style="color:{c["border"]}">·</span>  '.join(
        f'<a href="{_esc(i["url"])}" style="color:{c["text"]};text-decoration:none;'
        f'font-family:{t["font"]["body"]};font-size:13px;letter-spacing:.02em;'
        f'text-transform:uppercase">{_esc(i["label"])}</a>' for i in nav_items[:5]))
    nav = (f'<tr><td style="padding:14px 32px 6px" align="center">{links}</td></tr>'
           f'<tr><td style="padding:0 32px"><div style="height:1px;'
           f'background:{c["border"]};line-height:1px"> </div></td></tr>')
    return top + nav


def _header_design(t: dict, webview: bool, spec: dict) -> str:
    """The header a DESIGN asks for: the mark left or centred; the store's
    links none, inline beside the mark, or on their own line below; upper
    or title case; a rule under it or not. The ground is the section
    context's, painted by the caller."""
    c = t["colors"]
    logo = (f'<img src="{_esc(t["logo_url"])}" alt="{_esc(t["logo_alt"] or t["name"])}" '
            f'height="30" style="display:block;border:0;height:30px'
            f'{";margin:0 auto" if spec["logo"] == "center" else ""}">'
            if t["logo_url"] else
            f'<span style="font-family:{t["font"]["heading"]};font-size:20px;'
            f'font-weight:600;color:{c["text"]}">{_esc(t["name"])}</span>')
    view = ((f'<a href="{BROWSER}" style="font-family:{t["font"]["body"]};'
             f'font-size:12px;color:{c["muted"]};text-decoration:underline">'
             f'View in browser</a>') if webview else "")
    nav_items = [i for i in (t.get("nav") or []) if i.get("label") and i.get("url")]
    case = "text-transform:uppercase;letter-spacing:.02em;" if spec["case"] == "upper" else ""
    links = (f'  <span style="color:{c["border"]}">·</span>  '.join(
        f'<a href="{_esc(i["url"])}" style="color:{c["text"]};text-decoration:none;'
        f'font-family:{t["font"]["body"]};font-size:13px;{case}">{_esc(i["label"])}</a>'
        for i in nav_items[:5])) if nav_items and spec["nav"] != "none" else ""
    if spec["logo"] == "center":
        top = (f'<tr><td align="center" style="padding:18px 32px 0">{logo}'
               + (f'<div style="padding-top:6px">{view}</div>' if view else "") + '</td></tr>')
        if links and spec["nav"] == "inline":
            top += f'<tr><td align="center" style="padding:10px 32px 0">{links}</td></tr>'
    else:
        right = (links if links and spec["nav"] == "inline" else view)
        top = (f'<tr><td style="padding:18px 32px 0"><table role="presentation" width="100%" '
               f'cellpadding="0" cellspacing="0" border="0"><tr>'
               f'<td align="left">{logo}</td><td align="right">{right}</td>'
               f'</tr></table></td></tr>')
        if links and spec["nav"] == "inline" and view:
            top += f'<tr><td align="right" style="padding:4px 32px 0">{view}</td></tr>'
    if links and spec["nav"] == "below":
        top += f'<tr><td style="padding:14px 32px 6px" align="center">{links}</td></tr>'
    if spec["rule"]:
        top += (f'<tr><td style="padding:{"0" if links and spec["nav"] == "below" else "12px"} 32px 0">'
                f'<div style="height:1px;background:{c["border"]};line-height:1px"> </div></td></tr>')
    else:
        top += '<tr><td style="padding:0 32px 6px;font-size:0;line-height:0"> </td></tr>'
    return top


def _footer(t: dict, spec: dict | None = None) -> str:
    c, f = t["colors"], t["footer"]
    if spec:
        return _footer_design(t, spec)
    # CAN-SPAM: a physical address and a working unsubscribe are REQUIRED. The
    # address is rendered from the theme; if a client's theme has none the line
    # says so, loudly, rather than shipping an email that is illegal to send.
    addr = (_esc(f["address"]) if f["address"]
            else '<span style="color:#c0392b">[NO MAILING ADDRESS ON FILE — '
                 'required before this can send]</span>')
    tag = (f'<div style="padding-bottom:10px">{_esc(f["tagline"])}</div>'
           if f["tagline"] else "")
    # Socials — brand data, real links. A quiet row above the legal line.
    socials = [s for s in (f.get("socials") or []) if s.get("name") and s.get("url")]
    social_row = ""
    if socials:
        links = "   ".join(
            f'<a href="{_esc(s["url"])}" style="color:{c["muted"]};'
            f'text-decoration:none;font-weight:600">{_esc(s["name"])}</a>'
            for s in socials[:5])
        social_row = f'<div style="padding-bottom:12px;font-size:13px">{links}</div>'
    # Per-brand disclaimer (e.g. a supplement DSHEA line). Brand data, and the
    # validator still enforces the ban list on it upstream — this only renders.
    disc = (f'<div style="padding-top:10px;font-size:11px;color:{c["muted"]};'
            f'opacity:.85">{_esc(f["disclaimer"])}</div>' if f["disclaimer"] else "")
    return (f'<tr><td style="padding:24px 32px 32px;font-family:{t["font"]["body"]};'
            f'font-size:12px;line-height:1.6;color:{c["muted"]};text-align:center">'
            f'{tag}{social_row}'
            f'<div>{_esc(f["brand"] or t["name"])} · {addr}</div>'
            f'<div style="padding-top:8px">'
            f'<a href="{UNSUB}" style="color:{c["muted"]};text-decoration:underline">'
            f'Unsubscribe</a></div>{disc}</td></tr>')


def _footer_design(t: dict, spec: dict) -> str:
    """The footer a DESIGN asks for: its lines left or centred, the social
    links as words, as chips, or not at all, a rule over it or not. The
    ground is the section context's. CAN-SPAM is not a variant: the
    address and the unsubscribe are in every one."""
    c, f = t["colors"], t["footer"]
    al = "center" if spec["align"] == "center" else "left"
    addr = (_esc(f["address"]) if f["address"]
            else '<span style="color:#c0392b">[NO MAILING ADDRESS ON FILE — '
                 'required before this can send]</span>')
    tag = f'<div style="padding-bottom:10px">{_esc(f["tagline"])}</div>' if f["tagline"] else ""
    socials = [x for x in (f.get("socials") or []) if x.get("name") and x.get("url")]
    social_row = ""
    if socials and spec["socials"] == "words":
        social_row = ('<div style="padding-bottom:12px;font-size:13px">' + "   ".join(
            f'<a href="{_esc(x["url"])}" style="color:{c["muted"]};text-decoration:none;'
            f'font-weight:600">{_esc(x["name"])}</a>' for x in socials[:5]) + "</div>")
    elif socials and spec["socials"] == "icons":
        # No icon files are ever fetched from anywhere: the "icon" is the
        # platform's initial in a small chip, in the ground's own ink.
        social_row = ('<div style="padding-bottom:12px">' + " ".join(
            f'<a href="{_esc(x["url"])}" title="{_esc(x["name"])}" style="display:inline-block;'
            f'width:26px;height:26px;line-height:26px;border-radius:13px;border:1px solid {c["muted"]};'
            f'color:{c["muted"]};text-decoration:none;font-size:12px;font-weight:700;text-align:center">'
            f'{_esc(x["name"][:1])}</a>' for x in socials[:5]) + "</div>")
    disc = (f'<div style="padding-top:10px;font-size:11px;color:{c["muted"]};'
            f'opacity:.85">{_esc(f["disclaimer"])}</div>' if f["disclaimer"] else "")
    rule = (f'<tr><td style="padding:0 32px"><div style="height:1px;background:{c["border"]};'
            f'line-height:1px"> </div></td></tr>' if spec["rule"] else "")
    return (rule + f'<tr><td style="padding:24px 32px 32px;font-family:{t["font"]["body"]};'
            f'font-size:12px;line-height:1.6;color:{c["muted"]};text-align:{al}">'
            f'{tag}{social_row}'
            f'<div>{_esc(f["brand"] or t["name"])} · {addr}</div>'
            f'<div style="padding-top:8px">'
            f'<a href="{UNSUB}" style="color:{c["muted"]};text-decoration:underline">'
            f'Unsubscribe</a></div>{disc}</td></tr>')


def render(theme: dict, blocks: list, *, preheader: str = "",
           webview: bool = True, look: dict | None = None) -> str:
    """Canonical blocks + a client theme → send-ready, email-safe HTML.

    The output carries NEUTRAL tokens still (`{{FIRST_NAME}}`, `{{UNSUBSCRIBE}}`,
    and — only when `webview` is true — `{{VIEW_IN_BROWSER}}`) —
    `esp.personalize` renders those native for whichever platform the client
    is on. `webview` comes from the provider's caps: Omnisend has no
    view-in-browser variable, and emitting the token for it would either ship
    literal text or trip personalize's unknown-token refusal. The header
    (logo) and the legal footer are added here, so no generator can omit them.

    `look` is the arrangement (see LOOK): read off a swiped email and kept on
    the structure that was picked. It is normalised before anything reads
    it, so an unknown value falls back to the house default. With `bands`
    on, every second SECTION (a run of blocks between headings, or between
    the hero and the first heading) sits on the brand's page background
    instead of the card surface — the alternating-band rhythm of a designed
    email, painted with colours the brand already has.
    """
    t = _theme(theme, look)
    c = t["colors"]
    rows = [_header(t, webview=webview)]
    section, banded = 0, t["look"]["bands"]
    for b in (blocks or []):
        kind = (b or {}).get("type", "")
        fn = _BLOCKS.get(kind)
        if kind == "heading" and int((b or {}).get("level") or 2) > 1:
            section += 1
        elif kind == "hero":
            section = 0
        row = (fn(b, t) if fn
               else f"<!-- skipped unknown block: {_esc(b.get('type',''))} -->")
        if banded and section % 2 == 1 and fn and kind != "hero":
            row = _band(row, c["bg"])
        rows.append(row)
    rows.append(_footer(t))

    pre = (f'<div style="display:none;max-height:0;overflow:hidden;opacity:0">'
           f'{_esc(preheader)}</div>' if preheader else "")
    inner = "".join(rows)
    return (
        '<!DOCTYPE html><html lang="en"><head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="light">'
        f'<title>{_esc(t["name"])}</title></head>'
        f'<body style="margin:0;padding:0;background:{c["bg"]}">'
        f'{pre}'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'border="0" style="background:{c["bg"]}"><tr>'
        f'<td align="center" style="padding:24px 12px">'
        f'<table role="presentation" width="{t["width"]}" cellpadding="0" cellspacing="0" '
        f'border="0" style="width:100%;max-width:{t["width"]}px;background:{c["surface"]};'
        f'border:1px solid {c["border"]};border-radius:{t["radius"]}">'
        f'{inner}'
        f'</table></td></tr></table></body></html>'
    )


def missing_to_send(theme: dict) -> list[str]:
    """What a theme still lacks to produce a SENDABLE email — not a prettier
    one. Only the things whose absence makes the email un-sendable or unbranded
    enough to embarrass: a mailing address (CAN-SPAM) and a brand name. A logo
    or an accent colour is a quality gap, reported elsewhere, not here.
    """
    t = _theme(theme)
    gaps = []
    if not t["footer"]["address"]:
        gaps.append("footer.address — CAN-SPAM requires a physical mailing address")
    if not (t["footer"]["brand"] or t["name"]):
        gaps.append("brand name")
    return gaps


# ---------------------------------------------------------------------------
# RENDERING A DESIGN — INITIATIVE-email-design.md, Phase 4
#
# `render` above paints one email: thirteen block painters, one frame, one
# header, one footer, six toggles. `render_design` executes a DESIGN
# (`email_design.SCHEMA`): the blocks are grouped into SECTIONS, each section
# gets the treatment the design names for its kind (or for its place in a
# concrete order read off a reference), and every colour is resolved through
# the brand's PALETTE OF ROLES — the section's ground and the ink that reads
# on it — never through the design, which names roles only. The block
# painters are the same ones: each is handed a style context whose colours
# ARE the section's ground, so a quote on the dark ground is painted by the
# quote painter in the dark ground's ink, and nothing is written twice.
#
# `render` stays as it is until Phase 6 switches the campaign run and
# retires it — its positional bands and its six toggles are not worth
# imitating through a section renderer, and the suites that pin them pin
# the OLD behaviour, honestly.
# ---------------------------------------------------------------------------

#: A face by CLASS, for a brand with none on file: (the Google face to link,
#: the email-safe stack). The brand's own face always wins (Decision 1).
_CLASS_STACKS = {
    "serif-display": ("Playfair Display", "'Playfair Display', Georgia, 'Times New Roman', serif"),
    "serif-editorial": ("", "Georgia, 'Times New Roman', serif"),
    "sans-geometric": ("Montserrat", "'Montserrat', 'Century Gothic', 'Trebuchet MS', Arial, sans-serif"),
    "sans-grotesque": ("Inter", "'Inter', -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"),
    "condensed": ("Oswald", "'Oswald', 'Arial Narrow', Impact, Arial, sans-serif"),
    "script": ("Dancing Script", "'Dancing Script', 'Brush Script MT', cursive"),
}
_BODY_STACKS = {"serif": ("", "Georgia, 'Times New Roman', serif"),
                "sans": ("", "-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif")}
_RADIUS = {"none": "0", "soft": "8px", "round": "16px"}
_SECTION_PAD = {"none": 0, "tight": 6, "regular": 14, "airy": 28}
_DENSITY_OF_PAD = {"none": "tight", "tight": "tight", "regular": "regular", "airy": "airy"}
#: Which of a block's kinds is its own section; everything else joins the
#: run it is in (a heading starts one).
_BLOCK_KIND = {"hero": "hero", "products": "products", "quote": "proof", "stat": "proof",
               "banner": "offer", "signature": "closing", "ps": "ps"}


#: The slots a hero section may carry beyond its own picture and headline;
#: a design whose hero names any of these is a CARD — the words belong in
#: it, and the run that follows the hero block is absorbed into it.
_HERO_WORDS = ("body", "list", "cta", "quote", "stat", "caption")


def group_sections(blocks: list, design: dict | None = None) -> list[dict]:
    """The drafter's flat blocks as sections: a hero, a product block, a
    proof block, a banner, a signature and a P.S. are each their own; a
    heading starts a run of words (the first run after the top is the
    intro, then feature and editorial by turns); text, a list, a divider
    and an ask join the run they are in; an ask with no run is the closing.
    Returns `[{kind, blocks}]`.

    With a `design` whose first hero section carries WORD slots — body, a
    list, an ask — the hero is a card in the reference (its headline and
    copy live with its picture), so the run that follows the hero block is
    absorbed into the hero section; without this the design's next words
    section landed on the hero's own copy and everything after was off by
    one (the pistol-shrimp review, 2026-09-11)."""
    out: list[dict] = []
    cur: dict | None = None
    runs = 0
    pending: list[dict] = []          # pictures waiting for the run they belong to
    for b in blocks or []:
        kind = str((b or {}).get("type", ""))
        own = _BLOCK_KIND.get(kind)
        if own:
            out.append({"kind": own, "blocks": [b]})
            cur = None
            continue
        if kind not in _BLOCKS:
            continue
        if kind == "image" and cur is None:
            # A picture never starts a run: the filler puts it before the
            # words it was filled for, and it joins them.
            pending.append(b)
            continue
        if kind == "divider":
            # A DIVIDER IS A SECTION BOUNDARY — the one mark a drafter has to
            # say "the next thing is its own section" without a heading
            # (the pistol-shrimp review's closing, absorbed into the run
            # above it). It stays with the run it closes, painted as the
            # design's divider, and the next block starts fresh.
            if cur is not None:
                cur["blocks"].append(b)
            cur = None
            continue
        # A heading starts a run — unless the run so far is only headings
        # (a kicker, then its headline): those are one section's top, not two.
        only_heads = cur is not None and all(b.get("type") == "heading" for b in cur["blocks"])
        starts = (kind == "heading" and not only_heads) or cur is None
        if starts and (kind == "heading" or kind != "cta"):
            runs += 1
            cur = {"kind": "intro" if runs == 1 else ("feature" if runs % 2 == 0 else "editorial"),
                   "blocks": pending}
            pending = []
            out.append(cur)
        elif cur is None:            # an ask on its own
            cur = {"kind": "closing", "blocks": pending}
            pending = []
            out.append(cur)
        cur["blocks"].append(b)
    if pending:
        out.append({"kind": "editorial", "blocks": pending})
    # THE LAST RUN OF WORDS WITH NO HEADING IS THE CLOSING — "was this
    # forwarded to you?" and the ask again, under everything else.
    if out and out[-1]["kind"] in WORDS and not any(b.get("type") == "heading" for b in out[-1]["blocks"]) \
            and len(out) > 1:
        out[-1]["kind"] = "closing"
    hero_spec = next((x for x in ((design or {}).get("sections") or []) if x.get("kind") == "hero"), None)
    if hero_spec and any(str(sl).split(":")[0] in _HERO_WORDS for sl in (hero_spec.get("slots") or [])):
        for i in range(len(out) - 1):
            if out[i]["kind"] == "hero" and out[i + 1]["kind"] in WORDS:
                out[i]["blocks"] = out[i]["blocks"] + out[i + 1]["blocks"]
                del out[i + 1]
                # The runs after it keep their turns: the first run of words
                # is still the intro of the design's words family.
                n = 0
                for g in out[i + 1:]:
                    if g["kind"] in WORDS:
                        n += 1
                        g["kind"] = "intro" if n == 1 else ("feature" if n % 2 == 0 else "editorial")
                break
    return out


#: A run of words is one family. The grouping names runs intro, feature and
#: editorial by their position; a reading names them by judgment — so a
#: group and a design section meet on the FAMILY, in order, never on which
#: of the three either side happened to say.
WORDS = ("intro", "feature", "editorial")


def _family(kind: str) -> str:
    return "words" if kind in WORDS else kind


def _holds(sec: dict, blocks: list | None) -> bool:
    """Whether a design section's slots can hold what a group carries: a
    group with words needs a section with a word slot; a group that is only
    a picture fits a picture-only section. A section with no slots holds
    anything."""
    slots = {str(x).split(":")[0] for x in (sec.get("slots") or [])}
    if not slots or not blocks:
        return True
    types = {b.get("type") for b in blocks}
    word_types = {"heading", "text", "list", "cta", "button", "quote", "stat", "signature", "ps", "products"}
    if types & word_types:
        return bool(slots - {"image"})
    return True


def _spec_for(design: dict, kind: str, taken: dict, blocks: list | None = None) -> dict:
    """How a section of this kind is painted: the design's per-kind default,
    overlaid by the next unconsumed section of that FAMILY in the design's
    concrete order that can HOLD what the group carries — a reference's
    hero treatment reaches the hero, its product grid the products, its
    second run of words the second run of words; a closing of words skips a
    closing that is only a picture (a logo band) for the one with a body."""
    spec = dict((design.get("defaults") or {}).get(kind) or {})
    fam = _family(kind)
    order = [s for s in (design.get("sections") or []) if _family(str(s.get("kind"))) == fam]
    i = taken.get(fam, 0)
    j = next((k for k in range(i, len(order)) if _holds(order[k], blocks)), None)
    if j is not None:
        spec.update({k: v for k, v in order[j].items() if k != "kind"})
        taken[fam] = j + 1
    return spec


def _ground_colors(palette: dict, role: str) -> dict:
    """The renderer's colour roles as they are ON THIS GROUND: the ground
    itself as surface and page, the ink that reads on it, a muted line and
    a border mixed from the two, the accent kept for buttons and rules."""
    from . import palette as _pal
    ink_role = _pal.INK_OF.get(role, "ink")
    ground, ink = palette[role], palette[ink_role]
    return {"bg": ground, "surface": ground, "text": ink,
            "muted": _pal.mix(ink, ground, 0.45), "border": _pal.mix(ground, ink, 0.14),
            "accent": palette["accent"], "accent_text": palette["accent_ink"]}


def _faces(base: dict, tspec: dict) -> tuple[dict, list[str]]:
    """The faces: the brand's own where it has one on file (its stack is not
    the renderer's default), else the class the design names — and the
    Google faces to link for the classes that have one."""
    faces, google = {}, []
    for role, default, table, key in (("heading", _DEFAULT["font"]["heading"], _CLASS_STACKS, "display_family"),
                                      ("body", _DEFAULT["font"]["body"], _BODY_STACKS, "body_family")):
        own = str(base["font"].get(role) or "")
        if own and own != default:
            faces[role] = own
            continue
        gf, stack = table.get(tspec.get(key), ("", default))
        faces[role] = stack
        if gf:
            google.append(gf)
    return faces, google


def _context(base: dict, design: dict, spec: dict, role: str, kind: str) -> dict:
    """The style context one section is painted in: the brand's theme with
    the colours of this ground, the design's type and ask, the section's
    treatment, and the old look derived for the painters that still read it."""
    t = dict(base)
    t["colors"] = _ground_colors(base["palette"], role)
    t["ground"] = role
    t["type"] = _type(design["type"])
    if spec.get("align") == "center":
        t["type"] = {**t["type"], "talign": "text-align:center;", "align": "center"}
        t["cta_center"] = True
    if spec.get("layout") == "letter":
        t["type"] = {**t["type"], "kicker": "none", "leading": "airy", "lh": _LEAD["airy"]}
    if spec.get("layout") == "band":
        t["type"] = {**t["type"], "talign": "text-align:center;", "align": "center"}
    t["cta"] = dict(design["cta"])
    if spec.get("layout") == "band" or t.get("cta_center"):
        t["cta"] = {**t["cta"], "align": "center"}
    t["divider"] = design["dividers"]["style"]
    t["radius"] = _RADIUS.get(design["frame"]["radius"], "8px")
    t["width"] = int(design["frame"]["width"])
    t["image"] = spec.get("image", "contained")
    t["aspect"] = spec.get("aspect", "")
    t["list_style"] = spec.get("list", "check")
    t["split"] = "right" if spec.get("layout") == "split-right" else "left"
    layout = spec.get("layout", "stack")
    hero = ("overlay" if layout == "overlay" or spec.get("text_on_image") else
            "split" if layout in ("split-left", "split-right") else
            "bleed" if spec.get("image") == "bleed" else "contained")
    t["look"] = _look({"hero": hero,
                       "scale": "display" if t["type"]["scale"] in ("display", "poster") else "modest",
                       "density": _DENSITY_OF_PAD.get(spec.get("pad", "regular"), "regular"),
                       "bands": False,
                       "cta": "block",
                       "products": {"grid2": "grid2", "grid3": "grid3", "collage": "grid2"}.get(layout, "rows")})
    return t


#: Which block types fill each slot, in the order the design's slots run.
_SLOT_TYPES = {"kicker": ("heading",), "headline": ("heading",), "sub": ("text",), "body": ("text",),
               "list": ("list",), "cta": ("cta", "button"), "products": ("products",),
               "quote": ("quote",), "stat": ("stat",), "image": ("hero", "image"),
               "caption": ("text",), "signature": ("signature",), "ps": ("ps",)}


def ordered(blocks: list, slots: list | None) -> list:
    """The section's blocks in the ORDER the design's slots run — a headline
    over the picture when the reference had it so — each slot taking the
    next unconsumed block of its type; a kicker takes a level-2 heading and
    a headline a level-1 one where both exist; what no slot names follows
    in the order the drafter wrote it. Without slots, the drafter's order."""
    if not slots:
        return list(blocks)
    left = list(blocks)
    out: list = []
    for slot in slots:
        name = str(slot).split(":")[0]
        types = _SLOT_TYPES.get(name)
        if not types:
            continue
        pick = None
        for b in left:
            if b.get("type") not in types:
                continue
            if name == "kicker" and b.get("type") == "heading" and int(b.get("level") or 2) <= 1:
                continue
            if name == "headline" and b.get("type") == "heading" and int(b.get("level") or 2) > 1 \
                    and any(x.get("type") == "heading" and int(x.get("level") or 2) <= 1 for x in left):
                continue
            pick = b
            break
        if pick is not None:
            out.append(pick)
            left.remove(pick)
    return out + left


def _paint(blocks: list, t: dict) -> str:
    rows = []
    for b in blocks:
        fn = _BLOCKS.get((b or {}).get("type", ""))
        if fn:
            rows.append(fn(b, t))
    return "".join(rows)


def _lay_stack(blocks: list, t: dict, spec: dict) -> str:
    return _paint(blocks, t)


def _lay_columns(blocks: list, t: dict, spec: dict) -> str:
    """Two columns of words: the run's headings stay full width above; its
    text and lists are dealt left and right, half each."""
    heads = [b for b in blocks if b.get("type") == "heading"]
    rest = [b for b in blocks if b.get("type") != "heading"]
    words = [b for b in rest if b.get("type") in ("text", "list")]
    others = [b for b in rest if b.get("type") not in ("text", "list")]
    if len(words) < 2:
        return _paint(blocks, t)
    half = (len(words) + 1) // 2
    ph = _PAD[t["look"]["density"]][1]
    inner = {**t, "width": (t["width"] - 2 * ph) // 2}
    left, right = _paint(words[:half], inner), _paint(words[half:], inner)
    cols = (f'<tr><td style="padding:0 {ph - 24}px"><table role="presentation" width="100%" '
            f'cellpadding="0" cellspacing="0" border="0"><tr>'
            f'<td width="50%" valign="top"><table role="presentation" width="100%" cellpadding="0" '
            f'cellspacing="0" border="0">{left}</table></td>'
            f'<td width="50%" valign="top"><table role="presentation" width="100%" cellpadding="0" '
            f'cellspacing="0" border="0">{right}</table></td></tr></table></td></tr>')
    return _paint(heads, t) + cols + _paint(others, t)


def _lay_split(blocks: list, t: dict, spec: dict) -> str:
    """A picture beside the words: the section's picture block in one cell,
    everything else in the other, the side the layout says. A hero section
    keeps its own split (the hero painter draws it); a section with no
    picture stacks."""
    pics = [b for b in blocks if b.get("type") == "image" and b.get("image")]
    if not pics or any(b.get("type") == "hero" for b in blocks):
        return _paint(blocks, t)
    words = [b for b in blocks if b is not pics[0]]
    ph = _PAD[t["look"]["density"]][1]
    half = (t["width"] - 2 * ph) // 2
    inner = {**t, "width": half + 2 * ph}
    pic = (f'<td width="{half}" valign="top"><table role="presentation" width="100%" cellpadding="0" '
           f'cellspacing="0" border="0">{_image(pics[0], {**inner, "image": "rounded" if t.get("image") == "rounded" else "contained"})}</table></td>')
    txt = (f'<td width="{half}" valign="middle"><table role="presentation" width="100%" cellpadding="0" '
           f'cellspacing="0" border="0">{_paint(words, inner)}</table></td>')
    cells = txt + pic if t.get("split") == "right" else pic + txt
    return (f'<tr><td style="padding:0 {ph - 24 if ph > 24 else 0}px"><table role="presentation" width="100%" '
            f'cellpadding="0" cellspacing="0" border="0"><tr>{cells}</tr></table></td></tr>')


def _lay_collage(blocks: list, t: dict, spec: dict) -> str:
    """Pictures two across, the words under them: the section's picture
    blocks as a grid, then the rest. With one or no picture it stacks."""
    pics = [b for b in blocks if b.get("type") == "image" and b.get("image")]
    if len(pics) < 2:
        return _paint(blocks, t)
    rest = [b for b in blocks if b.get("type") != "image"]
    pv, ph = _PAD[t["look"]["density"]]
    gap = 12
    cw = (t["width"] - 2 * ph - gap) // 2
    cells = [(f'<td width="{cw}" valign="top" style="padding:0 0 {gap}px"><img src="{_esc(_sized(p["image"], cw * 2, "square"))}" '
              f'width="{cw}" alt="{_esc(p.get("alt", ""))}" style="display:block;width:100%;max-width:{cw}px;'
              f'height:auto;border:0;border-radius:{t["radius"]}"></td>') for p in pics[:4]]
    spacer = f'<td width="{gap}" style="font-size:0;line-height:0">&nbsp;</td>'
    rows = "".join("<tr>" + spacer.join(cells[i:i + 2]) + "</tr>" for i in range(0, len(cells), 2))
    grid = (f'<tr><td style="padding:{pv}px {ph}px 0"><table role="presentation" width="100%" '
            f'cellpadding="0" cellspacing="0" border="0">{rows}</table></td></tr>')
    return grid + _paint(rest, t)


def _lay_band(blocks: list, t: dict, spec: dict) -> str:
    """One thing on a band: everything centred in one generous cell, the
    ground the section's (an accent or a dark, in the design that asked
    for it) — a banner block loses its own box, since the band IS the box."""
    c = t["colors"]
    inner = []
    for b in blocks:
        if b.get("type") == "banner":
            inner.append(f'<tr><td align="center" style="padding:6px 0;font-family:{t["font"]["heading"]};'
                         f'font-size:22px;font-weight:{t["type"]["weight"]};line-height:1.25;'
                         f'color:{c["text"]};{t["type"]["case"]}{t["type"]["track"]}">{_esc(b.get("text", ""))}</td></tr>')
        else:
            fn = _BLOCKS.get(b.get("type", ""))
            if fn:
                inner.append(fn(b, t))
    ph = _PAD[t["look"]["density"]][1]
    return (f'<tr><td align="center" style="padding:22px {ph}px;text-align:center">'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
            f'{"".join(inner)}</table></td></tr>')


LAYOUTS = {"stack": _lay_stack, "split-left": _lay_split, "split-right": _lay_split,
           "grid2": _lay_stack, "grid3": _lay_stack, "collage": _lay_collage,
           "overlay": _lay_stack, "columns": _lay_columns, "band": _lay_band,
           "letter": _lay_stack}
#: Vocabulary values that are not drawn by this renderer YET, and which
#: phase draws them — named so the painter walk skips them by name rather
#: than passing them by accident.
NOT_DRAWN_YET = {"imagery.hero": "Phase 5 — read by the filler, not the painter",
                 "imagery.product": "Phase 5 — read by the filler, not the painter",
                 "imagery.feature": "Phase 5 — read by the filler, not the painter",
                 "palette.mood": "Phase 7 — a key the reader records; the brand's palette decides",
                 "palette.accent_use": "Phase 7"}


def _wrap(inner: str, ground: str, pad: int, rule_above: str = "none",
          rule_colour: str = "", card: dict | None = None) -> str:
    """A section's rows inside its ground, with the room the design asks
    for above and below, and a rule over it when asked. With `card` (the
    `cards` container: `{page, radius}`), the section is its own rounded
    card with the page showing around it."""
    if not inner:
        return ""
    rule = ""
    if rule_above == "thin":
        rule = f"border-top:1px solid {rule_colour};"
    elif rule_above == "thick":
        rule = f"border-top:3px solid {rule_colour};"
    elif rule_above == "dotted":
        rule = f"border-top:2px dotted {rule_colour};"
    if card:
        return (f'<tr><td style="background:{card["page"]};padding:0 24px 20px">'
                f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
                f'style="background:{ground};border-radius:{card["radius"]};{rule}">'
                f'<tr><td style="padding:{pad}px 0"><table role="presentation" width="100%" cellpadding="0" '
                f'cellspacing="0" border="0">{inner}</table></td></tr></table></td></tr>')
    return (f'<tr><td style="background:{ground};padding:{pad}px 0;{rule}">'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
            f'{inner}</table></td></tr>')


def render_design(design: dict, theme: dict, blocks: list, *, preheader: str = "",
                  webview: bool = True) -> str:
    """A DESIGN executed with a brand's palette, faces and chrome, on the
    drafter's blocks → send-ready, email-safe HTML.

    Every colour in the output is one of the brand's twelve roles (plus the
    scrim the overlay hero paints over a photograph); the design chose the
    ROLE of every ground and the brand chose what colour that role is. The
    faces are the brand's own where it has them, the class the design names
    where it has none. CAN-SPAM's footer is in every design.
    """
    from . import email_design
    design, _dropped = email_design.normalize(design)
    base = _theme(theme)
    pal = base["palette"]
    faces, google = _faces(base, design["type"])
    base = {**base, "font": {**base["font"], **faces}}
    width = int(design["frame"]["width"])
    radius = _RADIUS.get(design["frame"]["radius"], "8px")

    rows: list[str] = []
    hd = design["header"]
    ht = _context(base, design, {"pad": "regular"}, hd["bg"], "header")
    rows.append(_wrap(_header(ht, webview=webview, spec=hd), pal[hd["bg"]], 0))
    taken: dict = {}
    cards = design["frame"]["container"] == "cards"
    card = {"page": pal[design["frame"]["page"]], "radius": radius} if cards else None
    if cards:
        rows.append(f'<tr><td style="background:{card["page"]};font-size:0;line-height:0;height:20px">&nbsp;</td></tr>')
    for sec in group_sections(blocks, design):
        spec = _spec_for(design, sec["kind"], taken, sec["blocks"])
        role = spec.get("bg", "surface")
        t = _context(base, design, spec, role, sec["kind"])
        blocks_s = ordered(sec["blocks"], spec.get("slots"))
        if cards and blocks_s and blocks_s[-1].get("type") == "divider":
            # In a stack of cards the gap IS the divider; a boundary divider
            # at the end of a card would paint a rule under nothing.
            blocks_s = blocks_s[:-1]
        inner = LAYOUTS.get(spec.get("layout", "stack"), _lay_stack)(blocks_s, t, spec)
        rows.append(_wrap(inner, pal[role], _SECTION_PAD.get(spec.get("pad", "regular"), 14),
                          spec.get("rule_above", "none"), t["colors"]["border"], card))
    ft = design["footer"]
    ftt = _context(base, design, {"pad": "regular"}, ft["bg"], "footer")
    rows.append(_wrap(_footer(ftt, spec=ft), pal[ft["bg"]], 0))

    page = pal[design["frame"]["page"]]
    one_card = design["frame"]["container"] == "card"
    chrome = ((f'background:{pal["surface"]};' if not cards else f'background:{page};')
              + (f'border:1px solid {pal["border"]};' if one_card and design["frame"]["border"] else "")
              + (f"border-radius:{radius};" if one_card else ""))
    pre = (f'<div style="display:none;max-height:0;overflow:hidden;opacity:0">'
           f'{_esc(preheader)}</div>' if preheader else "")
    fonts = ""
    if google:
        fam = "&family=".join(g.replace(" ", "+") + ":wght@400;600;700" for g in google)
        fonts = (f'<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family={fam}&display=swap">'
                 f'<style>@import url("https://fonts.googleapis.com/css2?family={fam}&display=swap");</style>')
    return (
        '<!DOCTYPE html><html lang="en"><head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="light">'
        f'<title>{_esc(base["name"])}</title>{fonts}</head>'
        f'<body style="margin:0;padding:0;background:{page}">'
        f'{pre}'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'border="0" style="background:{page}"><tr>'
        f'<td align="center" style="padding:{"24px 12px" if one_card else "0"}">'
        f'<table role="presentation" width="{width}" cellpadding="0" cellspacing="0" '
        f'border="0" style="width:100%;max-width:{width}px;{chrome}">'
        f'{"".join(rows)}'
        f'</table></td></tr></table></body></html>'
    )
