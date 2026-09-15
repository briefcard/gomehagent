"""THE MODEL MAKES THE EMAIL; THE CODE INSPECTS IT.

INITIATIVE-email-recreation.md §0, 2026-09-12. A reference email is read into
a BRIEF in words, the brand's material is gathered into a KIT, the pictures
are CAST by looking, the copy is written to the brief's jobs, and then the
model WRITES THE EMAIL — the HTML itself, with everything in view. The code
checks invariants, a browser takes a picture, a judge compares that picture
to the reference and names what differs, the model edits, and the round with
the fewest blocking findings is kept. The card shows the reference beside
ours with the open findings; the owner's note is one more finding.

Nothing here is a design vocabulary. The brief is a light schema of free
words. `check` is the only closed list in the chain, and every item in it is
an invariant — brand assets only, nothing from the reference, email-safe
HTML, contrast, the footer the law wants, the ESP's tokens, the brand's own
rules, no fabrication — never what an email must look like. A reference with
a device nobody has seen needs nothing added to this file.

The trace this was built from is §1 of the plan: each function below is the
component named on the right-hand side of that table.
"""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from urllib.parse import urlparse

from . import config, db

#: Rounds: the first, then up to this many edits. The hand-made proof took two.
ROUNDS = 2
#: Gmail clips a message over ~102 KB and hides the footer with it.
HTML_MAX = 100_000
#: Candidates the caster looks at on one sheet — 6 × 4 cells at the reviewer's tier.
CAST_MAX = 24
#: The column the hand-made proof was set at; the composer is told this width.
COLUMN = 600
#: Statuses a recreation ends in.
SHIPPABLE, NOT_SHIPPABLE, CANNOT, FAILED, RUNNING = (
    "shippable", "not shippable", "cannot be made", "failed", "running")
#: Characters and phrases that assert something not on file.
_FABRICATED = re.compile(r"[✓✔☑]|\bverified\b|\b\d[\d,.]*\s*[kK]?\s*(?:likes?|followers|comments)\b", re.I)


# ---------------------------------------------------------------------------
# small shared helpers
# ---------------------------------------------------------------------------

def _json(text: str):
    """The first JSON object or array in a reply, or None."""
    t = str(text or "")
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if m:
        t = m.group(1)
    m = re.search(r"[\[{].*[\]}]", t, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except ValueError:
        return None


def _ask(purpose: str, blocks, *, tenant: str = "", max_tokens: int = 1500):
    from . import llm
    return llm.ask(purpose, blocks, tenant=tenant, max_tokens=max_tokens)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").replace("’", "'").replace("‘", "'")
                  .replace("“", '"').replace("”", '"').replace("—", "-").replace("–", "-")).strip()


def _grams(text: str, n: int = 5) -> set:
    words = re.findall(r"[a-z0-9']+", _norm(text).lower())
    return {" ".join(words[i:i + n]) for i in range(max(0, len(words) - n + 1))}


# ---------------------------------------------------------------------------
# 1. THE BRIEF — the reference read in words, the way a designer briefs it
# ---------------------------------------------------------------------------

BRIEF_KEYS = ("concept", "sections", "visual_system", "devices", "reference_text", "reference_hexes")

#: With no reference in the rotation the maker designs the email itself; the
#: caster still needs slots to cast for — a hero and a second picture.
DESIGNLESS = {
    "concept": "", "designless": True,
    "sections": [{"n": 1, "what": "the opening picture", "does": "shows the subject at its best",
                  "asset": {"kind": "photograph", "shows": "the subject of this email at its best — in use, in a scene, or the thing itself"}, "copy": []},
                 {"n": 2, "what": "a second picture", "does": "shows another side of it",
                  "asset": {"kind": "photograph", "shows": "another angle — in use, at the table, in a room, a detail"}, "copy": []}],
    "visual_system": {}, "devices": [], "reference_text": [], "reference_hexes": [],
}

_BRIEF_PROMPT = """You are a senior email designer briefing a colleague who will RECREATE this
email's design for a different brand, with that brand's own photographs, products and words.
You have the whole email as one small picture first, then in legible strips top to bottom.

Write the brief as JSON with exactly these keys:

"concept": one sentence — what this email IS and does (e.g. "a recipe delivered as a
  screenshot of the brand's own Instagram post; a pun hook above; shop the product used below").
"sections": an array, top to bottom, one object per section:
   {"n": 1,
    "what": what it is, in a phrase (a device if it is one: 'a social post shown as a post:
            avatar, handle, photo, icon row, dots, caption'),
    "does": what it does for the reader,
    "asset": {"kind": "photograph" | "mark" | "illustration" | "none",
              "shows": the ROLE the picture plays, in terms ANY brand's own photograph could
              fill — "the hero product, alone, big", "the product in a scene of use — food on
              it, hands, sunlight", "the product being bought — in a basket, a bag, at the
              counter", "the range side by side, packs standing together", "a person with the
              product". NEVER the reference's own product, props, colours or background: the
              other brand has none of them. What the reference's picture LOOKS like (its
              ground colour, its frame, its angle) belongs in "look", where it is recreated
              in the other brand's tones},
    "copy": [{"id": "s1_kicker", "job": what these words must do, in one line —
              'a two-line hook that turns on how the product is used', 'four numbered steps
              naming the product, the last step one word', "limit": words or lines}],
    "look": how it is set — ground, alignment, type roles, scale, spacing, framing}
"visual_system": {"type": the type roles and their character (display face heavy/condensed,
   small-caps kicker, script accent, body size), "colour": how colour is used (which
   grounds are dark, where the accent goes, how much contrast, whether the page turns),
   "rhythm": spacing, widths, insets, corner radii, rules, "column": the content width you see}
"devices": an array of every distinct device you can see, each described so it can be
   drawn without the picture.
"reference_text": every visible word of the email, line by line, verbatim.
"reference_hexes": the six most dominant colours as hex.

Rules: describe, never rate. Do not round a thing you see to a familiar name — if it is a
screenshot of a social post, say so; if lettering is drawn, say so. Copy ids are unique.
Return the JSON only."""


def brief(asset_id: str, *, tenant: str = "") -> dict:
    """The swipe picture at `asset_id` read into a brief and stored on the
    structure it was read into. `{ok, brief, structure_id, why, calls}`."""
    from . import pictures as ed
    with db.SessionLocal() as s:
        a = s.get(db.KbAsset, asset_id)
        url = str(getattr(a, "url", "") or "") if a else ""
        st = (s.query(db.EmailStructure).filter(db.EmailStructure.source_asset_id == asset_id)
              .order_by(db.EmailStructure.created_at.desc()).first())
        sid = st.id if st else ""
    if not url:
        return {"ok": False, "why": "no reference picture at that id", "calls": 0}
    blob = ed._fetch(url)
    if not blob:
        return {"ok": False, "why": "the reference picture could not be fetched", "calls": 0}
    tier, edge = ed._tier_edge()
    parts = ed.strips(blob, edge)
    if len(parts) + 1 > ed.MAX_IMAGE_BLOCKS:
        return {"ok": False, "why": f"the reference is too tall to read whole ({len(parts)} strips)", "calls": 0}
    blocks = [ed._image_block(ed.contact_sheet(blob, edge))] + [ed._image_block(p["png"]) for p in parts]
    blocks.append({"type": "text", "text": _BRIEF_PROMPT})
    reply = _ask("email_brief", blocks, tenant=tenant, max_tokens=6000)
    if not getattr(reply, "ok", False):
        return {"ok": False, "why": f"the reader did not answer — {getattr(reply, 'error', '')}", "calls": 1}
    got = _json(reply.text)
    why = brief_problem(got)
    if why:
        return {"ok": False, "why": why, "calls": 1}
    got["read"] = {"tier": tier, "edge": edge, "strips": len(parts), "model": getattr(reply, "model", "")}
    if sid:
        with db.SessionLocal() as s:
            st = s.get(db.EmailStructure, sid)
            st.brief = got
            s.commit()
    return {"ok": True, "brief": got, "structure_id": sid, "calls": 1}


def brief_problem(got) -> str:
    """Why a reply is not a brief — by name, or "" when it is one."""
    if not isinstance(got, dict):
        return "the reader did not answer with a JSON object"
    missing = [k for k in BRIEF_KEYS if k not in got]
    if missing:
        return "the brief lacks " + ", ".join(missing)
    if not str(got.get("concept") or "").strip():
        return "the brief has no concept"
    secs = got.get("sections")
    if not isinstance(secs, list) or not secs:
        return "the brief has no sections"
    for i, sec in enumerate(secs):
        if not isinstance(sec, dict) or not str(sec.get("what") or "").strip():
            return f"section {i + 1} does not say what it is"
    return ""


# ---------------------------------------------------------------------------
# 2. THE KIT — the brand's material, gathered once
# ---------------------------------------------------------------------------

def kit(tenant: str) -> dict:
    """Everything the brand has that an email may be made of. Every item is
    already on file and already approved — this gathers, it invents nothing."""
    from . import brand_theme, esp, kb, pictures as ed
    b = kb.brand(tenant)
    theme = brand_theme.filled(brand_theme.live_theme(tenant) or {})
    voice = (getattr(b, "voice", None) or {}) if b else {}
    ents = []
    for e in kb.entities(tenant)[:60]:
        a = getattr(e, "attributes", None) or {}
        desc = re.sub(r"<[^>]+>", " ", str(getattr(e, "description", "") or ""))
        ents.append({"key": e.key, "name": e.name, "type": getattr(e, "type", "") or "",
                     "url": str(a.get("url") or ""), "price": str(a.get("price") or ""),
                     "image": str(a.get("image") or ""), "description": _norm(desc)[:400]})
    pics = []
    for a in kb.assets(tenant):
        if getattr(a, "rights", "") != kb.OWNED or getattr(a, "kind", "image") != "image" or not a.url:
            continue
        r = getattr(a, "reading", None) or {}
        pics.append({"id": a.id, "url": a.url, "small": ed._small_url(a.url), "title": a.title or "",
                     "entity_key": a.entity_key or "", "subject": a.subject or "",
                     "kind": r.get("kind") or "", "colours": r.get("colours") or {},
                     "size": r.get("size") or [], "aspect": r.get("aspect") or "",
                     "alone": r.get("alone"), "person": r.get("person"), "tags": list(a.tags or [])})
    claims = [{"id": c.id, "claim": str(getattr(c, "claim", "") or "")} for c in (kb.claims(tenant) or [])[:40]]
    handles = {s.get("name", "").lower(): s.get("url", "") for s in (theme.get("footer") or {}).get("socials") or []}
    caps = esp.caps(tenant)
    hosts = {urlparse(p["url"]).netloc for p in pics} | {urlparse(theme.get("logo_url") or "").netloc,
                                                        urlparse(config.PUBLIC_BASE_URL).netloc}
    return {"tenant": tenant, "name": theme.get("name") or (getattr(b, "display_name", "") if b else tenant),
            "positioning": str(getattr(b, "positioning", "") or "") if b else "",
            "voice": {k: voice.get(k) for k in ("tone", "do_say", "never_say") if voice.get(k)},
            "theme": theme, "entities": ents, "pictures": pics, "claims": claims, "handles": handles,
            "rules": {"channel": kb.channel_rules(tenant, "campaign_email") or ""},
            "esp": {"provider": esp.provider_for(tenant), "tokens": list(esp.TOKENS),
                    "webview": bool(caps.get("webview", True))},
            "hosts": {h for h in hosts if h}}


# ---------------------------------------------------------------------------
# 3. THE CAST — the brand's pictures chosen by LOOKING, with reasons
# ---------------------------------------------------------------------------

_CAST_PROMPT = """You are casting photographs for an email that recreates a reference design for the
brand %(name)s. The sheet shows the brand's own pictures, numbered. Each numbered cell is one
picture; under the sheet are the same pictures' filed facts.

The brief's picture slots — each names the ROLE a picture plays in the design:
%(slots)s

The brand's pictures will never match the reference's subject — a different product, in
different colours, on different tables. Cast by ROLE: for each slot pick the ONE picture on
the sheet that plays that role best for this brand (a hero of the product; the product in
use or in a scene; the product being bought or carried; the range side by side; a person
with it) and say why in a line. Colours do not matter — the email's tones follow the
picture you pick. Prefer a picture not used lately (%(recent)s), and among equals prefer
the ones about %(subject)s. Say "none" for a slot only when no picture on the sheet could
play the role at all. Never pick the same picture for two slots.

Return JSON only: {"picks": [{"section": n, "cell": k, "why": "..."}],
                   "none": [{"section": n, "needs": "a photograph of ..."}]}"""


def _sheet(cells: list[bytes]) -> bytes:
    """A numbered contact sheet, 6 across, cells 250 px, PNG — under the
    reviewer's tier so nothing is downscaled."""
    import io
    from PIL import Image, ImageDraw, ImageFont
    from . import llm, pictures as ed
    # BOTH limits the model holds a picture to: the long edge AND the total
    # pixels (≈1.18 M at the standard tier — the API refused a 1546×1034
    # sheet on the owner's first real run, 2026-09-15). Six across, four
    # down at 208 px is 1318×882; the sheet is measured with the model's
    # own arithmetic afterwards and shrunk if it would still be refused.
    cols, cell, pad = 6, 208, 10
    rows = max(1, (len(cells) + cols - 1) // cols)
    W, H = cols * (cell + pad) + pad, rows * (cell + pad) + pad
    sheet = Image.new("RGB", (W, H), "#ffffff")
    d = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.load_default(size=26)
    except Exception:                                            # noqa: BLE001
        font = ImageFont.load_default()
    for i, blob in enumerate(cells):
        x, y = pad + (i % cols) * (cell + pad), pad + (i // cols) * (cell + pad)
        try:
            im = Image.open(io.BytesIO(blob)).convert("RGB")
            im.thumbnail((cell, cell))
            sheet.paste(im, (x + (cell - im.width) // 2, y + (cell - im.height) // 2))
        except Exception:                                        # noqa: BLE001
            d.rectangle([x, y, x + cell, y + cell], outline="#999")
        d.rectangle([x, y, x + 44, y + 34], fill="#111111")
        d.text((x + 6, y + 3), str(i + 1), fill="#ffffff", font=font)
    tier, edge = ed._tier_edge()
    fit_w, fit_h = llm.resized_size(W, H, edge, llm.IMAGE_TIERS[tier]["max_tokens"])
    if (fit_w, fit_h) != (W, H):
        sheet = sheet.resize((fit_w, fit_h), Image.LANCZOS)
    buf = io.BytesIO()
    sheet.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def candidates(kit_: dict, *, entity_key: str = "", recent_media=(), seed: str = "") -> list[dict]:
    """The pictures the caster is shown: the subject's first, then the rest,
    what this list saw lately last; a seeded shuffle inside each rank so two
    campaigns on the same subject are shown a different order."""
    import random
    recent = set(recent_media or ())
    rnd = random.Random(seed or "cast")
    pics = list(kit_.get("pictures") or [])
    rnd.shuffle(pics)
    rank = lambda p: (0 if entity_key and p.get("entity_key") == entity_key else 1,  # noqa: E731
                      1 if p["id"] in recent else 0,
                      0 if p.get("kind") and not str(p.get("kind")).startswith("packshot") else 1)
    pics.sort(key=rank)
    return pics[:CAST_MAX]


def cast(tenant: str, brief_: dict, kit_: dict, *, entity_key: str = "",
         recent_media=(), seed: str = "") -> dict:
    """`{ok, picks: {section: {asset_id, url, why, ...}}, none: [...], said, calls}`.
    A mark slot takes the brand's logo without a look. A slot nothing fits
    is cut and said with what it needs."""
    from . import pictures as ed
    slots = [sec for sec in brief_.get("sections") or []
             if str(((sec.get("asset") or {}).get("kind") or "none")).lower() == "photograph"]
    marks = [sec.get("n") for sec in brief_.get("sections") or []
             if str(((sec.get("asset") or {}).get("kind") or "")).lower() == "mark"]
    # an illustration (a cartoon figure, drawn lettering) is a DEVICE: the
    # composer draws it in HTML/CSS or a baked block, or leaves it out — it
    # is never a photograph to find on the brand's shelf
    drawn = [sec.get("n") for sec in brief_.get("sections") or []
             if str(((sec.get("asset") or {}).get("kind") or "")).lower() == "illustration"]
    out = {"ok": True, "picks": {}, "none": [], "marks": marks, "drawn": drawn, "said": [], "calls": 0}
    if not slots:
        out["said"].append("the design carries no photograph")
        return out
    cands = candidates(kit_, entity_key=entity_key, recent_media=recent_media, seed=seed)
    if not cands:
        out["none"] = [{"section": s.get("n"), "needs": (s.get("asset") or {}).get("shows") or "a photograph"} for s in slots]
        out["said"].append("no publishable picture on file — every photograph slot is cut")
        return out
    blobs = [ed._fetch_bounded(p["small"]) or ed._fetch_bounded(p["url"]) for p in cands]
    keep = [(p, b) for p, b in zip(cands, blobs) if b]
    if not keep:
        out["none"] = [{"section": s.get("n"), "needs": (s.get("asset") or {}).get("shows") or "a photograph"} for s in slots]
        out["said"].append("no picture could be fetched for the sheet — every photograph slot is cut")
        return out
    cands = [p for p, _ in keep]
    sheet = _sheet([b for _, b in keep])
    facts = "\n".join(f'{i + 1}. {p["title"] or "untitled"}' + (f' — {p["kind"]}' if p.get("kind") else "")
                      + (f' — about {p["entity_key"]}' if p.get("entity_key") else "")
                      + (" — a person in it" if p.get("person") else "") for i, p in enumerate(cands))
    slot_text = "\n".join(f'section {s.get("n")}: {s.get("what")} — must show: '
                          f'{(s.get("asset") or {}).get("shows") or "(not said)"}' for s in slots)
    subject = next((e["name"] for e in kit_.get("entities") or [] if e["key"] == entity_key), "") or "the brand"
    recent_titles = [p["title"] for p in cands if p["id"] in set(recent_media or ())][:6]
    prompt = _CAST_PROMPT % {"name": kit_.get("name"), "slots": slot_text, "subject": subject,
                             "recent": ", ".join(recent_titles) or "none lately"}
    blocks = [ed._image_block(sheet), {"type": "text", "text": prompt + "\n\nThe pictures' facts:\n" + facts}]
    reply = _ask("email_cast", blocks, tenant=tenant, max_tokens=1200)
    out["calls"] = 1
    got = _json(reply.text) if getattr(reply, "ok", False) else None
    if not isinstance(got, dict):
        out["ok"] = False
        out["said"].append("the caster did not answer — " + str(getattr(reply, "error", "") or "no JSON"))
        return out
    used: set[str] = set()
    for pk in got.get("picks") or []:
        try:
            k = int(pk.get("cell")) - 1
            sec = int(pk.get("section"))
        except (TypeError, ValueError):
            continue
        if not (0 <= k < len(cands)) or cands[k]["id"] in used or sec in out["picks"]:
            continue
        p = cands[k]
        used.add(p["id"])
        out["picks"][sec] = {"asset_id": p["id"], "url": p["url"], "title": p["title"], "kind": p.get("kind"),
                             "colours": p.get("colours"), "size": p.get("size"), "aspect": p.get("aspect"),
                             "entity_key": p.get("entity_key"), "why": str(pk.get("why") or "")[:300]}
    for s in slots:
        n = s.get("n")
        if n not in out["picks"]:
            needs = next((str(x.get("needs") or "") for x in (got.get("none") or []) if x.get("section") == n), "")
            out["none"].append({"section": n, "needs": needs or ((s.get("asset") or {}).get("shows") or "a photograph")})
    out["said"].append(f"{len(out['picks'])} of {len(slots)} photograph slot(s) cast from {len(cands)} on the sheet"
                       + (f"; cut: {', '.join('section ' + str(x['section']) for x in out['none'])}" if out["none"] else ""))
    return out


# ---------------------------------------------------------------------------
# 5. THE COMPOSITION — the model writes the email
# ---------------------------------------------------------------------------

ASPECTS = {"1x1": 1.0, "4x5": 1.25, "3x2": 2 / 3, "16x9": 9 / 16}
FIT_WIDTH = 1200   # 2× the column: sharp on a phone, small enough to load


def fit(tenant: str, url: str, aspect: str, width: int = FIT_WIDTH) -> str:
    """The picture at `url` cut to `aspect` (centre crop) and `width` — a
    Shopify CDN picture by its URL, any other by Pillow, hosted by `media`.
    The original when it cannot be cut. ADJUSTED TO FIT THE EMAIL (owner,
    2026-09-14): a designer crops; the model is handed the crops."""
    ratio = ASPECTS.get(aspect)
    if not ratio:
        return url
    h = int(round(width * ratio))
    u = str(url or "")
    if "cdn.shopify.com" in u or "/cdn/shop/" in u:
        base, sep, query = u.partition("?")
        stem, dot, ext = base.rpartition(".")
        if dot and len(ext) <= 5 and "/" not in ext and not re.search(r"_\d+x\d*(_crop_\w+)?$", stem):
            return f"{stem}_{width}x{h}_crop_center{dot}{ext}{sep}{query}"
        return u
    try:
        import io
        from PIL import Image
        from . import media, pictures as ed
        blob = ed._fetch_bounded(u)
        if not blob:
            return u
        im = Image.open(io.BytesIO(blob)).convert("RGB")
        W, H = im.size
        if W / H > width / h:                       # too wide: trim the sides
            nw = int(H * width / h); x0 = (W - nw) // 2; im = im.crop((x0, 0, x0 + nw, H))
        else:                                        # too tall: trim top and bottom
            nh = int(W * h / width); y0 = (H - nh) // 2; im = im.crop((0, y0, W, y0 + nh))
        im = im.resize((min(width, im.width), min(h, im.height)), Image.LANCZOS)
        buf = io.BytesIO(); im.save(buf, format="JPEG", quality=85, optimize=True)
        put = media.put(tenant, buf.getvalue(), mime="image/jpeg", origin="derived")
        return put["url"] if put.get("ok") else u
    except Exception:                                            # noqa: BLE001
        return u


def fits(tenant: str, cast_: dict) -> dict:
    """Every cast picture in every aspect: `{section: {"original": url, "1x1": url, …}}`."""
    out = {}
    for n, p in (cast_.get("picks") or {}).items():
        out[n] = {"original": p["url"], **{a: fit(tenant, p["url"], a) for a in ASPECTS}}
    return out


_EXEMPLAR = "docs/recreations/ayoh-baci-portofino.html"


def exemplar() -> str:
    """THE STANDARD — the email made by hand on 2026-09-12 (Ayoh → Baci), shown
    to the composer as an example of the craft expected: the scale of the
    type, a device drawn faithfully, the page in a photograph's own tone,
    real products and links. Never a design to copy — the design is the
    brief's."""
    import os
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        with open(os.path.join(here, _EXEMPLAR), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


_COMPOSE_PROMPT = """You are the designer AND the writer. Make the finished email: the subject line, the
preheader, and the complete HTML — recreating the reference's DESIGN (the brief below) for
%(name)s with %(name)s's own pictures, products and words, carrying the message below.
Work the way a designer at a good studio works: the design comes from the brief, the craft
comes from you, the material comes only from the brand.

THE BRIEF — the reference, read by a designer. Recreate its concept, every section in order,
its devices, its type roles, its colour logic and its rhythm. A device it describes (a social
post shown as a post with avatar, handle, icon row and dots; a script closer; a bordered
button; a numbered recipe) is DRAWN — in HTML/CSS, or inside a baked block (below) — never
approximated by a plain paragraph.
%(brief)s

THE BRAND
name: %(name)s — %(positioning)s
voice: %(voice)s
mark: %(logo)s
instagram handle: %(handle)s
postal address (footer, verbatim): %(address)s
body face on file: %(body_face)s
%(rules_brand)s

THE PICTURES — the brand's own, cast for this design by looking at them. Each is offered in
the original and cut to 1:1, 4:5, 3:2 and 16:9 (centre crops, 1200 px wide): use the cut
that fits the slot, never stretch. The tones measured from each are the palette this email
leads with: the page ground may be a photograph's bold tone if the reference's is, the card
its light tone; the brand's accent supports; every text colour must read on its ground.
%(pictures)s
%(cut)s

THE MESSAGE this email carries%(message)s

THE STANDARD — an email made by hand from another reference for another brand. Copy its
CRAFT (a headline that fills the column; the page in the photograph's own tone; a device
drawn faithfully; real product names and links; tight copy that turns), NOT its design and
not one of its words:
%(exemplar)s

RULES
- Table layout, every style inline, one centred column %(column)d px wide (a width="%(column)d"
  table, max-width:%(column)dpx), a full-width outer table painting the page ground.
- Pictures: ONLY the URLs listed above, verbatim. Every <img> has alt text and an explicit
  width. No background-image. No <script>, <form>, <video>, <iframe>.
- Type: outside baked blocks use email-safe stacks only (Georgia; Helvetica/Arial; Impact,
  'Arial Black' for a heavy display line; 'Brush Script MT', cursive for a script).
- BAKED BLOCKS: a display headline, a script line, a device with icons — anything that needs
  a web font or inline SVG — goes inside <!--bake-->…<!--/bake-->: exactly one complete
  <table width="…"> that paints its own ground, no links inside. Each is photographed at 2×
  and replaced by one <img>; a Google Fonts <link> in <head> is allowed for them. Body copy,
  buttons and product names are never baked.
- Social proof (quotes, testimonials, reviews) exists only when a claim or review is listed
  under the message; with none on file, that block carries a short useful tip or fact from
  the brand's material instead — no quotation marks, no attribution, nothing presented as
  what a customer said. Never a verified tick, a like count, a rating, a figure not listed.
- The brand's ban list is absolute. Every link is a real URL from the material or
  {{UNSUBSCRIBE}}%(webview)s; no other {{token}}, no "#".
- The footer carries the postal address verbatim and an Unsubscribe link on {{UNSUBSCRIBE}}.
- Under %(size)d KB.

OUTPUT, exactly:
Subject: <the subject line>
Preheader: <the preheader>
<!DOCTYPE html>… the complete HTML document. Nothing after it."""

_REVISE_PROMPT = """Below is the email you wrote and the judge's findings after comparing it to the reference.
EDIT the HTML to close each finding. Change only what a finding requires; every other line
stays exactly as it is. The same rules apply (email-safe outside baked blocks; only the
listed pictures; the address and {{UNSUBSCRIBE}}; nothing invented).

FINDINGS
%(findings)s

OUTPUT, exactly:
Subject: <the subject line, unchanged unless a finding names it>
Preheader: <the preheader>
<!DOCTYPE html>… the complete HTML document. Nothing after it.

THE HTML
%(html)s"""


def _message_text(message: dict | None) -> str:
    if not message:
        return ": the brand itself — write the subject line and the preheader yourself."
    lines = []
    for k, v in (("subject line (use verbatim)", message.get("subject")), ("preheader", message.get("preheader")),
                 ("angle", message.get("angle")), ("offer", message.get("offer"))):
        if v:
            lines.append(f"- {k}: {v}")
    if message.get("products"):
        lines.append("- products (name · price · url):\n" + "\n".join(
            f"  · {p.get('name')} · {p.get('price', '')} · {p.get('url', '')}" for p in message["products"][:8]))
    if message.get("claims"):
        lines.append("- approved claims — use VERBATIM or not at all:\n" + "\n".join(f"  · {c}" for c in message["claims"][:8]))
    if message.get("text"):
        lines.append("- what the drafter wrote, to carry (its facts and its ask, not its shape):\n" + str(message["text"])[:2200])
    return ":\n" + "\n".join(lines)


def _parse_email(text: str) -> tuple[str, str, str]:
    t = str(text or "")
    m = re.search(r"```(?:html)?\s*(.*?)```", t, re.S)
    if m:
        t = m.group(1)
    subject = (re.search(r"^\s*Subject:\s*(.+)$", t, re.M) or [None, ""])[1].strip() if re.search(r"^\s*Subject:", t, re.M) else ""
    pre = (re.search(r"^\s*Preheader:\s*(.+)$", t, re.M) or [None, ""])[1].strip() if re.search(r"^\s*Preheader:", t, re.M) else ""
    k = t.lower().find("<!doctype")
    if k < 0:
        k = t.lower().find("<html")
    html = t[k:].strip() if k >= 0 else ""
    return subject, pre, html


def compose(brief_: dict, kit_: dict, cast_: dict, message: dict | None = None, *, tenant: str = "",
            fitted: dict | None = None, html: str = "", findings=()) -> dict:
    """`{ok, subject, preheader, html, why, edited}` — ONE MIND writes the
    copy and the HTML together; with `html` and `findings` it EDITS."""
    theme = kit_.get("theme") or {}
    if html and findings:
        prompt = _REVISE_PROMPT % {
            "findings": "\n".join(f'- [{f.get("severity", "")}] {f.get("where", "")}: {f.get("what", "")}'
                                  + (f' → {f["do"]}' if f.get("do") else "") for f in findings),
            "html": html}
    else:
        fitted = fitted if fitted is not None else fits(tenant, cast_)
        pics = []
        for n, p in (cast_.get("picks") or {}).items():
            c = p.get("colours") or {}
            urls = fitted.get(n) or {"original": p["url"]}
            pics.append(f'section {n} — {p.get("title")}' + (f' ({p["why"]})' if p.get("why") else "") + "\n"
                        + "\n".join(f"   {a}: {u}" for a, u in urls.items())
                        + ("\n   tones: " + ", ".join(f"{k} {v}" for k, v in c.items() if isinstance(v, str)) if c else ""))
        for n in cast_.get("marks") or []:
            pics.append(f"section {n} — the brand's mark: {theme.get('logo_url') or '(none on file: set the name in type)'}")
        for n in cast_.get("drawn") or []:
            pics.append(f"section {n} — an ILLUSTRATION in the reference: draw a simple equivalent in HTML/CSS "
                        f"or inside a baked block, in the brand's tones, or leave it out — never a photograph")
        cut = ("Slots with no picture that fits — leave the section out, keep the flow:\n"
               + "\n".join(f'section {x["section"]}: needs {x["needs"]}' for x in cast_.get("none") or [])
               if cast_.get("none") else "")
        voice = kit_.get("voice") or {}
        never = voice.get("never_say") or []
        rules_brand = ""
        if never:
            rules_brand += "never say: " + ", ".join(map(str, never[:20])) + "\n"
        if (kit_.get("rules") or {}).get("channel"):
            rules_brand += "the brand's email instructions: " + kit_["rules"]["channel"][:800] + "\n"
        if kit_.get("compliance"):
            rules_brand += "lines that must appear verbatim: " + " | ".join(kit_["compliance"][:4]) + "\n"
        prompt = _COMPOSE_PROMPT % {
            "name": kit_.get("name"), "positioning": kit_.get("positioning") or "",
            "voice": ", ".join(map(str, voice.get("tone") or [])) or "as the material reads",
            "logo": theme.get("logo_url") or "(no mark on file — set the name in type)",
            "handle": (kit_.get("handles") or {}).get("instagram") or "(none on file)",
            "address": (theme.get("footer") or {}).get("address") or "",
            "body_face": (theme.get("font") or {}).get("body") or "Helvetica, Arial, sans-serif",
            "rules_brand": rules_brand,
            "brief": (json.dumps({k: brief_.get(k) for k in ("concept", "sections", "visual_system", "devices")},
                                 ensure_ascii=False, indent=1) if brief_.get("concept") else
                      "(no reference this time — DESIGN IT YOURSELF: a strong designed email in the standard "
                      "below, with one idea, one big picture, type at scale, the page in the picture's own tone, "
                      "a real device or two, one ask)"),
            "pictures": "\n".join(pics) or "(none)", "cut": cut,
            "message": _message_text(message), "exemplar": exemplar()[:14000],
            "column": COLUMN, "size": HTML_MAX // 1000,
            "webview": " or {{VIEW_IN_BROWSER}}" if (kit_.get("esp") or {}).get("webview", True) else
                       " (this platform has no view-in-browser variable — offer none)"}
    reply = _ask("email_compose", prompt, tenant=tenant, max_tokens=16000)
    if not getattr(reply, "ok", False):
        return {"ok": False, "html": "", "subject": "", "preheader": "", "edited": 0,
                "why": "the composer did not answer — " + str(getattr(reply, "error", ""))}
    subject, pre, out = _parse_email(reply.text)
    if "<table" not in out.lower():
        return {"ok": False, "html": "", "subject": "", "preheader": "", "edited": 0,
                "why": "the composer did not return an email"}
    edited = 0
    if html:
        import difflib
        edited = sum(1 for d in difflib.unified_diff(html.splitlines(), out.splitlines(), lineterm="", n=0)
                     if d.startswith(("+", "-")) and not d.startswith(("+++", "---")))
    return {"ok": True, "html": out, "subject": subject, "preheader": pre, "why": "", "edited": edited}


_BAKE = re.compile(r"<!--\s*bake\s*-->(.*?)<!--\s*/bake\s*-->", re.S | re.I)


def bake(html: str, tenant: str) -> tuple[str, list[str]]:
    """Every <!--bake-->…<!--/bake--> block photographed and replaced by one
    <img> — the reference's own trick (its display type and its post card
    are pictures), and the only way a web font or an SVG icon survives
    Gmail. Alt text = the block's words, so the checks still read them.
    Without a door the blocks stay as HTML (their fallback stacks show)."""
    from . import media, shots
    frags = _BAKE.findall(html)
    if not frags:
        return html, []
    head = ""
    m = re.search(r"<head>(.*?)</head>", html, re.S | re.I)
    if m:
        head = re.sub(r"<title>.*?</title>", "", m.group(1), flags=re.S | re.I)
    notes = []
    out = html
    for frag in frags:
        shot = shots.shoot_fragment(head, frag)
        words = _norm(re.sub(r"<[^>]+>", " ", frag))[:200]
        if not shot.get("ok"):
            notes.append(f"a block could not be baked ({shot.get('why')}) — left as HTML")
            continue
        put = media.put(tenant, shot["png"], mime="image/png", origin="derived")
        if not put.get("ok"):
            notes.append("a baked block could not be hosted — left as HTML")
            continue
        w = re.search(r'<table[^>]*\bwidth="?(\d+)', frag)
        width = int(w.group(1)) if w else COLUMN
        img = (f'<img src="{put["url"]}" width="{width}" alt="{words.replace(chr(34), "&quot;")}" '
               f'style="display:block;width:100%;max-width:{width}px;height:auto;border:0">')
        out = out.replace(f"<!--bake-->{frag}<!--/bake-->", img, 1) if f"<!--bake-->{frag}<!--/bake-->" in out \
            else _BAKE.sub(lambda mm, _f=frag, _i=img: _i if mm.group(1) == _f else mm.group(0), out, count=0)
        notes.append(f"baked: {words[:60]}")
    return out, notes


# ---------------------------------------------------------------------------
# 6. THE CHECKS — the invariants; the only closed list in the chain
# ---------------------------------------------------------------------------

_HEX = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")
_TOKEN = re.compile(r"\{\{\s*(.*?)\s*\}\}", re.S)


class _Walk(HTMLParser):
    """Text, images, links, tags — and every (text colour, ground) pair the
    inline styles resolve, so contrast is measured, not assumed."""

    VOID = {"img", "br", "hr", "meta", "link", "input"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text: list[str] = []
        self.imgs: list[dict] = []
        self.links: list[str] = []
        self.tags: set[str] = set()
        self.pairs: list[tuple[str, str, str]] = []
        self.unresolved: list[str] = []
        self.widths: set[str] = set()
        self.stack: list[tuple[str, str, str, bool]] = [("", "", "#ffffff", False)]  # tag, color, bg, hidden

    @staticmethod
    def _style(attrs) -> dict:
        st = dict(attrs).get("style") or ""
        out = {}
        for part in st.split(";"):
            if ":" in part:
                k, v = part.split(":", 1)
                out[k.strip().lower()] = v.strip()
        return out

    def handle_starttag(self, tag, attrs):
        self.tags.add(tag)
        a = dict(attrs)
        st = self._style(attrs)
        _, color, bg, hidden = self.stack[-1]
        if a.get("width"):
            self.widths.add(str(a["width"]))
        if "width" in st:
            self.widths.add(st["width"].replace("px", ""))
        c = st.get("color", "")
        if c:
            m = _HEX.search(c)
            if m:
                color = _expand(m.group(0))
            else:
                self.unresolved.append(f"colour {c!r}")
        g = st.get("background-color") or st.get("background") or a.get("bgcolor") or ""
        if g:
            m = _HEX.search(g)
            if m:
                bg = _expand(m.group(0))
            elif g.strip().lower() not in ("transparent", "none"):
                self.unresolved.append(f"ground {g!r}")
        hidden = hidden or "display:none" in (a.get("style") or "").replace(" ", "").lower()
        if tag == "img":
            self.imgs.append({"src": a.get("src", ""), "alt": a.get("alt"), "width": a.get("width")})
        if tag == "a" and a.get("href"):
            self.links.append(a["href"])
        if tag not in self.VOID:
            self.stack.append((tag, color, bg, hidden))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        tag, color, bg, hidden = self.stack[-1]
        if tag in ("style", "script", "title") or hidden:
            return
        t = data.strip()
        if not t:
            return
        self.text.append(t)
        if color:
            self.pairs.append((t[:40], color, bg))

    def words(self) -> str:
        """Everything a reader sees, baked words included (they ride as alt)."""
        return " ".join(self.text + [im.get("alt") or "" for im in self.imgs if im.get("alt")])


def _expand(h: str) -> str:
    h = h.lower()
    return h if len(h) == 7 else "#" + "".join(ch * 2 for ch in h[1:])


def check(html: str, kit_: dict, brief_: dict, copy_: dict | None = None, *,
          links: bool = False, reference_host: str = "") -> list[dict]:
    """The invariants, each a finding `{code, severity, where, what}`.
    `severity` is "blocks" (not shippable) or "note". Nothing here judges a
    design; that is the judge's job and the owner's."""
    from . import esp, palette, validator
    out: list[dict] = []
    add = lambda code, sev, where, what: out.append({"code": code, "severity": sev, "where": where, "what": what})  # noqa: E731
    if not html or not html.strip():
        add("empty", "blocks", "email", "no HTML")
        return out
    w = _Walk()
    try:
        w.feed(html)
    except Exception as e:                                        # noqa: BLE001
        add("parse", "blocks", "email", f"the HTML did not parse: {e}")
        return out
    text = w.words()
    theme = kit_.get("theme") or {}
    # 4. email-safe
    size = len(html.encode("utf-8"))
    if size > HTML_MAX:
        add("size", "blocks", "email", f"{size // 1000} KB — Gmail clips over {HTML_MAX // 1000} KB")
    for bad in ("svg", "script", "form", "video", "iframe"):
        if bad in w.tags:
            add("tag", "blocks", "email", f"<{bad}> does not survive email clients")
    if re.search(r"background(?:-image)?\s*:[^;\"']*url\(", html, re.I):
        add("bg_image", "blocks", "email", "a CSS background image — Outlook and Gmail drop it")
    if not (str(COLUMN) in w.widths or f"{COLUMN}px" in html):
        add("column", "note", "email", f"no {COLUMN}-px column found")
    for im in w.imgs:
        if im.get("alt") is None:
            add("alt", "blocks", im.get("src", "")[:80], "an image without alt text")
        if not im.get("width"):
            add("img_width", "note", im.get("src", "")[:80], "an image without an explicit width")
    # 1. brand assets only
    allowed = {p["url"] for p in kit_.get("pictures") or []} | ({theme.get("logo_url")} if theme.get("logo_url") else set())
    hosts = set(kit_.get("hosts") or ())
    for im in w.imgs:
        src = im.get("src") or ""
        host = urlparse(src).netloc
        if src.startswith("data:"):
            continue
        if src not in allowed and host not in hosts:
            add("asset", "blocks", src[:100], "not one of the brand's own pictures")
        elif src not in allowed:
            add("asset_unlisted", "note", src[:100], "a brand host, but not a filed picture")
    # 2. nothing from the reference
    ref_words = brief_.get("reference_text") or []
    ref_grams = _grams(" ".join(map(str, ref_words)))
    hit = _grams(text) & ref_grams
    if hit:
        add("leak_words", "blocks", "copy", "five words in a row from the reference: " + sorted(hit)[0])
    ref_hex = {_expand(h) for h in map(str, brief_.get("reference_hexes") or []) if _HEX.fullmatch(h.strip())}
    ours_hex = {_expand(h) for h in _HEX.findall(html)}
    if ref_hex & ours_hex:
        add("leak_hex", "blocks", "colour", "the reference's own colour: " + ", ".join(sorted(ref_hex & ours_hex)[:3]))
    if reference_host and any(urlparse(im.get("src", "")).netloc == reference_host for im in w.imgs):
        add("leak_image", "blocks", "image", "a picture from the reference's host")
    # 3. what must appear verbatim — the claims the message names (a claim
    #    reworded is a claim nobody approved)
    norm_text = _norm(text)
    for c in (copy_ or {}).get("claims") or []:
        if _norm(c) and _norm(c) not in norm_text and any(g in _grams(text, 3) for g in _grams(c, 3)):
            add("claim", "blocks", "copy", f"an approved claim reworded: {_norm(c)[:60]!r}")
    # 5. contrast
    seen = set()
    for t, fg, bg in w.pairs:
        if (fg, bg) in seen:
            continue
        seen.add((fg, bg))
        try:
            ratio = palette.contrast(fg, bg)
        except Exception:                                        # noqa: BLE001
            continue
        if ratio < 4.5:
            add("contrast", "blocks", t[:40], f"{fg} on {bg} reads at {ratio:.1f}:1 — 4.5:1 is the floor")
    for u in sorted(set(w.unresolved))[:5]:
        add("contrast_unresolved", "note", "colour", f"not measured: {u}")
    # 6. the law and the platform
    addr = _norm((theme.get("footer") or {}).get("address") or "")
    if addr and addr not in norm_text:
        add("address", "blocks", "footer", "the postal address on file is not in the email")
    tokens = [m.strip() for m in _TOKEN.findall(html)]
    if "UNSUBSCRIBE" not in tokens:
        add("unsubscribe", "blocks", "footer", "no {{UNSUBSCRIBE}} token")
    for tk in tokens:
        if tk not in esp.TOKENS:
            add("token", "blocks", "footer", f"an unknown token {{{{{tk}}}}}")
    if "VIEW_IN_BROWSER" in tokens and not (kit_.get("esp") or {}).get("webview", True):
        add("webview", "blocks", "header", "a view-in-browser link this platform has no variable for")
    # 7. the brand's rules at use
    for h in validator._banned(kit_.get("tenant", ""), text) or []:
        add("banned", "blocks", "copy", f"the brand's ban list: {h.get('phrase') or h}")
    # 9. fabrication
    m = _FABRICATED.search(text)
    if m:
        add("fabricated", "blocks", "copy", f"asserts something not on file: {m.group(0)!r}")
    if not kit_.get("claims"):
        # A QUOTE WITH NOBODY BEHIND IT: quotation marks and an attribution
        # dash where the brand has no claim or review on file.
        q = re.search(r"[\"“][^\"”]{20,}[\"”]\s*[—–-]\s*[A-Z][\w.]+", text)
        if q or "<blockquote" in html.lower():
            add("fabricated_quote", "blocks", "copy",
                "a quote presented as someone's words — nothing is on file to quote")
    # 8. links live
    if links:
        import httpx
        for href in sorted({h for h in w.links if h.startswith("http")}):
            try:
                r = httpx.head(href, timeout=8, follow_redirects=True)
                if r.status_code >= 400:
                    add("link", "blocks", href[:80], f"answers {r.status_code}")
            except Exception as e:                                # noqa: BLE001
                add("link", "blocks", href[:80], f"does not answer ({type(e).__name__})")
    for href in w.links:
        if href in ("#", "") or href.startswith("#"):
            add("link_placeholder", "blocks", href or "#", "a placeholder link")
    return out


def blocking(findings) -> list[dict]:
    return [f for f in (findings or []) if f.get("severity") == "blocks"]


# ---------------------------------------------------------------------------
# 7. THE JUDGE — ours beside the reference; findings, never a score
# ---------------------------------------------------------------------------

_JUDGE_PROMPT = """Two emails: first the REFERENCE (whole, then its top), then OURS (whole, then its top).
Ours was made to recreate the reference's design for another brand with that brand's own
pictures and words. The designer's brief of the reference:
concept: %(concept)s
devices: %(devices)s

Judge ours against the reference as an art director would, and answer JSON only:
{"same_concept": true|false,
 "devices_in_order": true|false,
 "weight_rhythm": one line on scale, spacing and visual weight compared,
 "brand_material": true|false — everything in ours is the other brand's own (no copied words or pictures),
 "findings": [{"where": "section n / the headline / the post card",
               "what": what differs from the reference in a way that matters,
               "do": the concrete edit that closes it,
               "severity": "blocks" if the recreation fails without it, else "cosmetic"}]}
Name real differences only — proportions, a missing device, a device drawn wrong, type set too
small or too light, a ground that should turn, spacing off by half. Do not ask for the
reference's colours, words or pictures: the brand's own are correct by design."""


_JUDGE_ALONE = """One email, ours (whole, then its top), made for a brand with no reference to follow.
Judge it as an art director would — against the standard of the best designed brand emails:
one idea, type at scale, the page in a photograph's own tone, a device or two drawn well,
one ask, nothing generic. Answer JSON only:
{"same_concept": true, "devices_in_order": true, "brand_material": true,
 "weight_rhythm": one line on scale, spacing and visual weight,
 "findings": [{"where": "...", "what": what falls short in a way that matters, "do": the concrete edit,
               "severity": "blocks" if it must change before sending, else "cosmetic"}]}"""


def judge(reference_png: bytes, ours_png: bytes, brief_: dict, *, tenant: str = "") -> dict:
    """`{ok, findings, verdict, why, calls}` — ours beside the reference, or
    ours alone when there is no reference."""
    from . import pictures as ed
    if not ours_png:
        return {"ok": False, "findings": [], "verdict": {}, "why": "no picture to judge", "calls": 0}
    _, edge = ed._tier_edge()
    blocks = []
    try:
        for png in ((reference_png, ours_png) if reference_png else (ours_png,)):
            blocks.append(ed._image_block(ed.contact_sheet(png, edge)))
            blocks.append(ed._image_block(ed.strips(png, edge)[0]["png"]))
    except Exception as e:                                        # noqa: BLE001
        return {"ok": False, "findings": [], "verdict": {}, "why": f"a picture could not be cut: {e}", "calls": 0}
    blocks.append({"type": "text", "text": (_JUDGE_PROMPT % {
        "concept": brief_.get("concept"), "devices": "; ".join(map(str, brief_.get("devices") or []))[:1500]})
        if reference_png else _JUDGE_ALONE})
    reply = _ask("email_judge", blocks, tenant=tenant, max_tokens=2000)
    got = _json(reply.text) if getattr(reply, "ok", False) else None
    if not isinstance(got, dict):
        return {"ok": False, "findings": [], "verdict": {}, "calls": 1,
                "why": "the judge did not answer — " + str(getattr(reply, "error", "") or "no JSON")}
    finds = []
    for f in got.get("findings") or []:
        if isinstance(f, dict) and f.get("what"):
            finds.append({"code": "judge", "severity": "blocks" if str(f.get("severity", "")).lower() == "blocks" else "cosmetic",
                          "where": str(f.get("where") or "")[:80], "what": str(f.get("what"))[:300],
                          "do": str(f.get("do") or "")[:300]})
    verdict = {k: got.get(k) for k in ("same_concept", "devices_in_order", "weight_rhythm", "brand_material")}
    if verdict.get("same_concept") is False:
        finds.insert(0, {"code": "judge", "severity": "blocks", "where": "the whole",
                         "what": "not the reference's concept", "do": "recreate the concept the brief names"})
    return {"ok": True, "findings": finds, "verdict": verdict, "why": "", "calls": 1}


# ---------------------------------------------------------------------------
# 8. THE LOOP — make, check, shoot, judge, edit; keep the best round
# ---------------------------------------------------------------------------

def _reference_png(structure_id: str) -> tuple[bytes, str]:
    from . import pictures as ed
    if not structure_id:
        return b"", ""
    with db.SessionLocal() as s:
        st = s.get(db.EmailStructure, structure_id)
        aid = st.source_asset_id if st else ""
        a = s.get(db.KbAsset, aid) if aid else None
        url = str(getattr(a, "url", "") or "") if a else ""
    return (ed._fetch(url) if url else b""), urlparse(url).netloc


def run(structure_id: str, tenant: str, entity_key: str = "", *, recent_media=(),
        seed: str = "", progress=None, message: dict | None = None, via: str = "press",
        extra_pictures: list | None = None) -> dict:
    """One recreation of `structure_id` for `tenant`, stored as a `Recreation`
    row and returned as `{ok, id, status, note, findings, rounds, html, text,
    media_ids, blocking}`. With a campaign `message` the copy carries it and
    `via` says so on the row."""
    from . import media, shots
    say = progress or (lambda *_: None)
    story: list[str] = []
    with db.SessionLocal() as s:
        st = s.get(db.EmailStructure, structure_id) if structure_id else None
        if structure_id and not st:
            return {"ok": False, "why": "no design at that id", "status": FAILED}
        brief_ = dict(st.brief or {}) if st else {}
        aid = (st.source_asset_id or "") if st else ""
        name = (st.name or structure_id) if st else "no reference"
        row = db.Recreation(tenant=tenant, structure_id=structure_id or "", entity_key=entity_key, status=RUNNING,
                            models={"via": via})
        s.add(row)
        s.commit()
        rid = row.id
    calls = 0

    def _finish(status: str, **fields) -> dict:
        with db.SessionLocal() as s:
            r = s.get(db.Recreation, rid)
            r.status = status
            r.note = " ".join(story)
            for k, v in fields.items():
                setattr(r, k, v)
            r.models = {**(r.models or {}), **(fields.get("models") or {}), "via": via}
            s.commit()
        cp = fields.get("copy") or {}
        html_ = fields.get("html", "")
        w_ = _Walk()
        try:
            w_.feed(html_)
        except Exception:                                        # noqa: BLE001
            pass
        return {"ok": status not in (FAILED,), "id": rid, "status": status, "note": " ".join(story),
                "findings": fields.get("findings", []), "rounds": fields.get("rounds", []), "calls": calls,
                "html": html_, "text": w_.words(), "subject": cp.get("subject", ""),
                "preheader": cp.get("preheader", ""),
                "media_ids": [p.get("asset_id") for p in ((fields.get("cast") or {}).get("picks") or {}).values()
                              if p.get("asset_id")],
                "blocking": len(blocking(fields.get("findings", [])))}

    # the brief — or none: with no reference the maker designs the email
    # itself, and the caster is asked for a hero and a second picture
    if not brief_ and aid:
        say("reading the reference into a brief")
        got = brief(aid, tenant=tenant)
        calls += got.get("calls", 0)
        if not got.get("ok"):
            story.append(f"The reference could not be read: {got.get('why')}.")
            return _finish(FAILED)
        brief_ = got["brief"]
        story.append(f"Read {name} into a brief: {brief_.get('concept')}")
    elif brief_:
        story.append(f"Brief on file: {brief_.get('concept')}")
    else:
        brief_ = dict(DESIGNLESS)
        story.append("No reference — the maker designs this one itself.")
    # the kit and the cast
    say("gathering the brand's material and casting its pictures")
    kit_ = kit(tenant)
    for x in (extra_pictures or []):
        if x.get("id") and x.get("url"):
            kit_["pictures"].insert(0, {"id": x["id"], "url": x["url"], "small": x["url"], "title": x.get("title") or "drawn",
                                        "entity_key": entity_key, "subject": "photo", "kind": x.get("kind") or "",
                                        "colours": {}, "size": [], "aspect": "", "alone": None, "person": None, "tags": []})
            kit_["hosts"].add(urlparse(x["url"]).netloc)
    cast_ = cast(tenant, brief_, kit_, entity_key=entity_key, recent_media=recent_media, seed=seed)
    calls += cast_.get("calls", 0)
    story.extend(cast_.get("said") or [])
    photo_slots = [sec for sec in brief_.get("sections") or []
                   if str(((sec.get("asset") or {}).get("kind") or "")).lower() == "photograph"]
    if not cast_.get("ok"):
        story.append("The caster did not answer: " + "; ".join(cast_.get("said") or []) + ".")
        return _finish(FAILED, brief=brief_, cast=cast_)
    if brief_.get("designless") and not cast_.get("picks"):
        # NO REFERENCE AND NO PICTURE: a type-led email, said — a brand with
        # nothing on file still gets its send; a reference that needs
        # photographs the brand lacks does not.
        story.append("No picture on file — a type-led email.")
        cast_ = {**cast_, "none": []}
    elif photo_slots and not cast_.get("picks"):
        story.append("Every photograph slot is cut, so the email cannot be made for this brand yet — "
                     + "; ".join(f"section {x['section']} needs {x['needs']}" for x in cast_.get("none") or []))
        return _finish(CANNOT, brief=brief_, cast=cast_,
                       findings=[{"code": "needs", "severity": "blocks", "where": f"section {x['section']}",
                                  "what": f"needs {x['needs']}"} for x in cast_.get("none") or []])
    # the copy
    fitted = fits(tenant, cast_)
    copy_ = {"claims": list((message or {}).get("claims") or [])}
    # the rounds
    ref_png, ref_host = _reference_png(structure_id)
    if aid and not ref_png:
        story.append("The reference picture could not be fetched — ours is judged on its own.")
    rounds: list[dict] = []
    html, raw, findings_prev = "", "", []
    best_i, best_n = -1, 10 ** 6
    for n in range(ROUNDS + 1):
        say(f"round {n}: " + ("writing the email" if n == 0 else "editing to the findings"))
        made = compose(brief_, kit_, cast_, message, tenant=tenant, fitted=fitted, html=raw, findings=findings_prev)
        calls += 1
        if not made.get("ok"):
            story.append(f"Round {n}: {made.get('why')}.")
            break
        raw = made["html"]                                   # the model's HTML, edited next round
        html, baked = bake(raw, tenant)                      # what is checked, shot, judged and sent
        for b_ in baked:
            if not b_.startswith("baked:"):
                story.append(b_ + ".")
        copy_.update(subject=made.get("subject") or copy_.get("subject", ""),
                     preheader=made.get("preheader") or copy_.get("preheader", ""))
        checks = check(html, kit_, brief_, copy_, links=True, reference_host=ref_host)
        shot = shots.shoot(html)
        png_id = ""
        if shot.get("ok"):
            put = media.put(tenant, shot["png"], mime="image/png", origin="generated")
            png_id = put.get("id", "") if put.get("ok") else ""
        judged = (judge(ref_png, shot["png"], brief_, tenant=tenant) if shot.get("ok")
                  else {"ok": False, "findings": [], "verdict": {}, "why": shot.get("why") or "no picture", "calls": 0})
        calls += judged.get("calls", 0)
        open_ = blocking(checks) + blocking(judged.get("findings"))
        rounds.append({"n": n, "png_id": png_id, "baked": sum(1 for b_ in baked if b_.startswith("baked:")),
                       "check": checks, "judge": judged.get("findings", []),
                       "verdict": judged.get("verdict", {}), "judged": judged.get("ok", False),
                       "why_not_judged": judged.get("why", "") if not judged.get("ok") else "",
                       "blocking": len(open_), "edited": made.get("edited", 0), "html": html,
                       "shot": {"door": shot.get("door", ""), "ms": shot.get("ms", 0), "why": shot.get("why", "")}})
        story.append(f"Round {n}: {len(blocking(checks))} check(s) block, "
                     + (f"the judge names {len(blocking(judged.get('findings')))} blocking and "
                        f"{len(judged.get('findings', [])) - len(blocking(judged.get('findings')))} cosmetic"
                        if judged.get("ok") else f"not judged ({judged.get('why')})")
                     + (f", {made['edited']} lines edited" if n else "") + ".")
        if len(open_) < best_n:
            best_i, best_n = n, len(open_)
        if not open_:
            break
        findings_prev = open_ + [f for f in judged.get("findings", []) if f.get("severity") == "cosmetic"][:3]
    if best_i < 0:
        return _finish(FAILED, brief=brief_, cast=cast_, copy=copy_)
    best = rounds[best_i]
    kept = [f for f in best["check"] + best["judge"] if f.get("severity") in ("blocks", "cosmetic", "note")]
    status = SHIPPABLE if not blocking(kept) and best["judged"] else NOT_SHIPPABLE
    if status == NOT_SHIPPABLE and not blocking(kept) and not best["judged"]:
        story.append("Not judged, so not called shippable.")
    story.append(f"Kept round {best_i} of {len(rounds)}: {status}.")
    slim = [{k: v for k, v in r.items() if k != "html"} for r in rounds]
    return _finish(status, brief=brief_, cast=cast_, copy=copy_, html=best["html"], png_id=best["png_id"],
                   rounds=slim, findings=kept, best=best_i,
                   models={"calls": calls, "door": best["shot"]["door"]})


def swipe(url: str, tenant: str, *, entity_key: str = "", progress=None) -> dict:
    """ONE PRESS FROM A LINK (owner, 2026-09-12: *"I add a reference from a
    link, it needs to give me the initial review of how we recreated it"*):
    the gallery page's picture is filed on the swipe board (once — a second
    paste of the same page finds it), read into a brief, filed as ONE design
    keyed by that picture, and recreated for this brand — so what lands on the
    Designs page is the reference beside ours with the judge's review, not a
    reading to approve. `{ok, structure_id, recreation, why}`."""
    from . import email_structures as es
    say = progress or (lambda *_: None)
    say("filing the reference")
    got = es.add_swipe(url)            # a page already on file comes back with its picture
    asset_id = got.get("asset_id", "")
    if not asset_id:
        return {"ok": False, "why": got.get("why") or "the page could not be filed", "structure_id": ""}
    with db.SessionLocal() as s:
        have = (s.query(db.EmailStructure).filter(db.EmailStructure.source_asset_id == asset_id)
                .order_by(db.EmailStructure.created_at.desc()).first())
        on_file = dict(have.brief or {}) if have else {}
    if on_file.get("concept"):
        say("brief on file")
        filed = es.file_reference(asset_id, brief=on_file, source_url=url)
    else:
        say("reading the reference into a brief")
        read = brief(asset_id, tenant=tenant)
        if not read.get("ok"):
            return {"ok": False, "why": read.get("why"), "structure_id": ""}
        filed = es.file_reference(asset_id, brief=read["brief"], source_url=url)
    say("recreating it for this brand")
    rec = run(filed["id"], tenant, entity_key, seed=f"{filed['id']}:{tenant}:first", progress=progress, via="press")
    return {"ok": rec.get("ok", False), "structure_id": filed["id"], "recreation": rec,
            "why": rec.get("note", "") if not rec.get("ok") else ""}


def again(structure_id: str, tenant: str, *, entity_key: str = "", progress=None) -> dict:
    """Read the reference again (a fresh brief) and recreate — the control
    for a design whose reading was wrong, not merely whose recreation was."""
    from . import email_structures as es
    with db.SessionLocal() as s:
        st = s.get(db.EmailStructure, structure_id)
        aid = st.source_asset_id if st else ""
    if not aid:
        return {"ok": False, "why": "this design has no reference picture to read"}
    read = brief(aid, tenant=tenant)
    if not read.get("ok"):
        return {"ok": False, "why": read.get("why")}
    es.file_reference(aid, brief=read["brief"])
    return run(structure_id, tenant, entity_key, seed=f"{structure_id}:{tenant}:{db.utcnow().isoformat(timespec='minutes')}",
               progress=progress, via="press")


def latest(structure_id: str, tenant: str) -> dict | None:
    """The newest recreation of this structure for this brand, for the card."""
    from . import media
    with db.SessionLocal() as s:
        rows = (s.query(db.Recreation).filter(db.Recreation.structure_id == structure_id,
                                              db.Recreation.tenant == tenant)
                .order_by(db.Recreation.created_at.desc()).limit(6).all())
        # THE NEWEST RESULT, not the newest row: a run that failed before it
        # made anything must not hide the last picture and review behind
        # "failed" — unless nothing else exists. A run in flight is shown as
        # such by the card.
        r = next((x for x in rows if x.status == RUNNING), None) or \
            next((x for x in rows if x.status not in (FAILED,)), None) or (rows[0] if rows else None)
        if not r:
            return None
        rounds = list(r.rounds or [])
        best = r.best or 0
        verdict = (rounds[best].get("verdict") or {}) if 0 <= best < len(rounds) else {}
        return {"id": r.id, "status": r.status, "note": r.note or "", "entity_key": r.entity_key or "",
                "png": media.url_for(r.png_id) if r.png_id else "", "findings": list(r.findings or []),
                "rounds": rounds, "best": best, "at": r.created_at.isoformat(timespec="minutes")
                if r.created_at else "", "concept": (r.brief or {}).get("concept", ""),
                "has_html": bool(r.html), "verdict": verdict, "via": (r.models or {}).get("via", "")}


def html_of(recreation_id: str) -> str:
    with db.SessionLocal() as s:
        r = s.get(db.Recreation, recreation_id)
        return (r.html or "") if r else ""
