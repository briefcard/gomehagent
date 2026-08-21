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
    "radius": "8px", "width": 600,
    # A working nav, brand data: [{"label","url"}]. Empty renders no nav bar.
    "nav": [],
    # `socials` [{"name","url"}] and `disclaimer` are brand data too; the
    # unsubscribe/preferences are NEUTRAL TOKENS the ESP layer makes native.
    "footer": {"brand": "", "address": "", "tagline": "",
               "socials": [], "disclaimer": ""},
}


def _theme(theme: dict) -> dict:
    """A theme with every field filled from the default, deep enough for the
    nested dicts the renderer reads."""
    t = {**_DEFAULT, **(theme or {})}
    for k in ("colors", "font", "footer"):
        t[k] = {**_DEFAULT[k], **((theme or {}).get(k) or {})}
    return t


def _esc(s) -> str:
    return _html.escape(str(s or ""))


# ---------------------------------------------------------------------------
# Blocks — the canonical, ESP-agnostic vocabulary a generator emits. Unknown
# block types are skipped with an HTML comment rather than raising: a renderer
# that dies on one bad block loses the whole email, and the comment leaves a
# trace for whoever is reading the source.
# ---------------------------------------------------------------------------

def _hero(b: dict, t: dict) -> str:
    c = t["colors"]
    img = ""
    if b.get("image"):
        img = (f'<tr><td style="padding:0"><img src="{_esc(b["image"])}" '
               f'width="{t["width"]}" alt="{_esc(b.get("alt",""))}" '
               f'style="display:block;width:100%;max-width:{t["width"]}px;'
               f'height:auto;border:0;border-radius:{t["radius"]} {t["radius"]} 0 0"></td></tr>')
    head = (f'<tr><td style="padding:28px 32px 4px">'
            f'<h1 style="margin:0;font-family:{t["font"]["heading"]};'
            f'font-size:26px;line-height:1.25;color:{c["text"]};font-weight:600">'
            f'{_esc(b.get("headline",""))}</h1></td></tr>') if b.get("headline") else ""
    sub = (f'<tr><td style="padding:6px 32px 0">'
           f'<p style="margin:0;font-family:{t["font"]["body"]};font-size:16px;'
           f'line-height:1.5;color:{c["muted"]}">{_esc(b.get("sub",""))}</p></td></tr>') \
        if b.get("sub") else ""
    return img + head + sub


def _text(b: dict, t: dict) -> str:
    c = t["colors"]
    # `html` is trusted here: it is the generator's validated copy, and it
    # carries neutral tokens the renderer must not escape (escaping would turn
    # `{{FIRST_NAME}}` into text and a link into a string). The validator is the
    # gate on this content, upstream — see the module docstring.
    body = b.get("html") or (f"<p>{_esc(b.get('text',''))}</p>" if b.get("text") else "")
    return (f'<tr><td style="padding:14px 32px;font-family:{t["font"]["body"]};'
            f'font-size:16px;line-height:1.6;color:{c["text"]}">{body}</td></tr>')


def _cta(b: dict, t: dict) -> str:
    c = t["colors"]
    # A bulletproof button: a table cell with the fill, not a styled <a>, so
    # Outlook renders the background at all.
    return (f'<tr><td style="padding:12px 32px 20px"><table role="presentation" '
            f'cellpadding="0" cellspacing="0" border="0"><tr>'
            f'<td style="background:{c["accent"]};border-radius:{t["radius"]}">'
            f'<a href="{_esc(b.get("url","#"))}" '
            f'style="display:inline-block;padding:13px 26px;'
            f'font-family:{t["font"]["body"]};font-size:15px;font-weight:600;'
            f'color:{c["accent_text"]};text-decoration:none">'
            f'{_esc(b.get("label","Shop now"))}</a></td></tr></table></td></tr>')


def _products(b: dict, t: dict) -> str:
    c = t["colors"]
    cells = []
    for p in (b.get("items") or [])[:3]:
        img = (f'<img src="{_esc(p.get("image",""))}" width="168" '
               f'alt="{_esc(p.get("name",""))}" style="display:block;width:100%;'
               f'height:auto;border:0;border-radius:{t["radius"]}">'
               if p.get("image") else "")
        price = (f'<div style="font-family:{t["font"]["body"]};font-size:14px;'
                 f'color:{c["muted"]};padding-top:2px">{_esc(p.get("price",""))}</div>'
                 if p.get("price") else "")
        cells.append(
            f'<td width="33%" valign="top" style="padding:6px">'
            f'<a href="{_esc(p.get("url","#"))}" style="text-decoration:none;color:{c["text"]}">'
            f'{img}<div style="font-family:{t["font"]["body"]};font-size:15px;'
            f'font-weight:600;padding-top:8px">{_esc(p.get("name",""))}</div>{price}</a></td>')
    if not cells:
        return ""
    return (f'<tr><td style="padding:10px 26px"><table role="presentation" width="100%" '
            f'cellpadding="0" cellspacing="0" border="0"><tr>{"".join(cells)}</tr>'
            f'</table></td></tr>')


def _divider(b: dict, t: dict) -> str:
    return (f'<tr><td style="padding:8px 32px"><div style="height:1px;'
            f'background:{t["colors"]["border"]};line-height:1px">&nbsp;</div></td></tr>')


_BLOCKS = {"hero": _hero, "text": _text, "cta": _cta, "button": _cta,
           "products": _products, "divider": _divider}


def _header(t: dict) -> str:
    c = t["colors"]
    logo = (f'<img src="{_esc(t["logo_url"])}" alt="{_esc(t["logo_alt"] or t["name"])}" '
            f'height="30" style="display:block;border:0;height:30px">'
            if t["logo_url"] else
            f'<span style="font-family:{t["font"]["heading"]};font-size:20px;'
            f'font-weight:600;color:{c["text"]}">{_esc(t["name"])}</span>')
    view = (f'<a href="{BROWSER}" style="font-family:{t["font"]["body"]};'
            f'font-size:12px;color:{c["muted"]};text-decoration:underline">View in browser</a>')
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
    links = (f'&nbsp;&nbsp;<span style="color:{c["border"]}">·</span>&nbsp;&nbsp;'.join(
        f'<a href="{_esc(i["url"])}" style="color:{c["text"]};text-decoration:none;'
        f'font-family:{t["font"]["body"]};font-size:13px;letter-spacing:.02em;'
        f'text-transform:uppercase">{_esc(i["label"])}</a>' for i in nav_items[:5]))
    nav = (f'<tr><td style="padding:14px 32px 6px" align="center">{links}</td></tr>'
           f'<tr><td style="padding:0 32px"><div style="height:1px;'
           f'background:{c["border"]};line-height:1px">&nbsp;</div></td></tr>')
    return top + nav


def _footer(t: dict) -> str:
    c, f = t["colors"], t["footer"]
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
        links = "&nbsp;&nbsp;&nbsp;".join(
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


def render(theme: dict, blocks: list, *, preheader: str = "") -> str:
    """Canonical blocks + a client theme → send-ready, email-safe HTML.

    The output carries NEUTRAL tokens still (`{{FIRST_NAME}}`, `{{UNSUBSCRIBE}}`,
    `{{VIEW_IN_BROWSER}}`) — `esp.personalize` renders those native for whichever
    platform the client is on. The header (logo) and the legal footer are added
    here, so no generator can omit them.
    """
    t = _theme(theme)
    c = t["colors"]
    rows = [_header(t)]
    for b in (blocks or []):
        fn = _BLOCKS.get((b or {}).get("type", ""))
        rows.append(fn(b, t) if fn else f"<!-- skipped unknown block: {_esc(b.get('type',''))} -->")
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
