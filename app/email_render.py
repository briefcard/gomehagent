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


def _theme(theme: dict) -> dict:
    """A theme with every field filled from the default, deep enough for the
    nested dicts the renderer reads."""
    t = {**_DEFAULT, **(theme or {})}
    for k in ("colors", "font", "footer", "sender"):
        t[k] = {**_DEFAULT[k], **((theme or {}).get(k) or {})}
    return t


def _esc(s) -> str:
    return _html.escape(str(s or ""))


def _sized(url: str, width: int) -> str:
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
    return f"{stem}_{width}x{dot}{ext}{sep}{query}"


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
        img = (f'<tr><td style="padding:0">'
               f'<img src="{_esc(_sized(b["image"], t["width"] * 2))}" '
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
    # Bare <p> tags get an inline rhythm — email clients reset paragraph
    # margins their own way, and "it just looks like long text" (owner,
    # 2026-08-21) is what default margins read as. Styled tags are left as
    # the generator wrote them.
    body = body.replace("<p>", '<p style="margin:0 0 14px">')
    return (f'<tr><td style="padding:10px 32px 2px;font-family:{t["font"]["body"]};'
            f'font-size:16px;line-height:1.65;color:{c["text"]}">{body}</td></tr>')


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
    """Product rows, not cramped columns. Three names squeezed into thirds
    wrapped badly on the owner's phone and nothing about them said
    "tappable" — each product is a full-width row now: photo left when the
    sync has one, name in the brand accent with the price under it, an
    accent arrow on the right, and the WHOLE row is one link."""
    c = t["colors"]
    rows = []
    for p in (b.get("items") or [])[:3]:
        url = p.get("url") or "#"
        img_td = (f'<td width="96" valign="top" style="padding:2px 14px 2px 0">'
                  f'<a href="{_esc(url)}">'
                  f'<img src="{_esc(_sized(p["image"], 176))}" width="88" '
                  f'alt="{_esc(p.get("name", ""))}" style="display:block;width:88px;'
                  f'height:88px;border:0;border-radius:{t["radius"]};'
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
    return (f'<tr><td style="padding:4px 32px 12px"><table role="presentation" '
            f'width="100%" cellpadding="0" cellspacing="0" border="0">'
            f'{"".join(rows)}</table></td></tr>')


def _heading(b: dict, t: dict) -> str:
    """A scannable section heading — level 1 is the email's one headline,
    anything else a section KICKER: small caps in the brand accent, the
    device that makes a section read as designed rather than as more
    paragraph. The owner's live drafts read as "just long text" while the
    section heads were plain bold lines one size off the body."""
    c = t["colors"]
    if int(b.get("level") or 2) <= 1:
        return (f'<tr><td style="padding:16px 32px 2px">'
                f'<div style="font-family:{t["font"]["heading"]};font-size:24px;'
                f'font-weight:700;line-height:1.25;color:{c["text"]}">'
                f'{_esc(b.get("text", ""))}</div></td></tr>')
    return (f'<tr><td style="padding:14px 32px 0">'
            f'<div style="font-family:{t["font"]["body"]};font-size:13px;'
            f'font-weight:700;letter-spacing:1.5px;text-transform:uppercase;'
            f'color:{c["accent"]}">{_esc(b.get("text", ""))}</div></td></tr>')


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
    education-shaped email a paragraph run would bury."""
    c = t["colors"]
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


_BLOCKS = {"hero": _hero, "text": _text, "cta": _cta, "button": _cta,
           "heading": _heading, "products": _products, "divider": _divider,
           "quote": _quote, "list": _list, "stat": _stat, "banner": _banner,
           "signature": _signature, "ps": _ps}


def _header(t: dict, webview: bool = True) -> str:
    c = t["colors"]
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


def render(theme: dict, blocks: list, *, preheader: str = "",
           webview: bool = True) -> str:
    """Canonical blocks + a client theme → send-ready, email-safe HTML.

    The output carries NEUTRAL tokens still (`{{FIRST_NAME}}`, `{{UNSUBSCRIBE}}`,
    and — only when `webview` is true — `{{VIEW_IN_BROWSER}}`) —
    `esp.personalize` renders those native for whichever platform the client
    is on. `webview` comes from the provider's caps: Omnisend has no
    view-in-browser variable, and emitting the token for it would either ship
    literal text or trip personalize's unknown-token refusal. The header
    (logo) and the legal footer are added here, so no generator can omit them.
    """
    t = _theme(theme)
    c = t["colors"]
    rows = [_header(t, webview=webview)]
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
