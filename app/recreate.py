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

import functools
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

#: The side of one cell on the contact sheet, in pixels. ONE definition: the
#: cutter that shrinks a picture as it arrives and the sheet that pastes it
#: must agree, or the sheet pastes something it then shrinks again.
SHEET_CELL = 208
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
    # an apostrophe inside a word stays (don't); a quote mark hugging a word
    # goes ('PICKLES' is pickles) — a judge quotes the reference in quotes
    words = [w.strip("'") for w in re.findall(r"[a-z0-9']+", _norm(text).lower())]
    words = [w for w in words if w]
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

"concept": one sentence — what this email IS and DOES, in FORM ONLY (e.g. "a recipe
  delivered as a screenshot of the brand's own Instagram post; a pun hook above; shop the
  product used below"). NEVER the reference's product, category, cuisine, season or
  seasonal theme. "introduces a new pre-seasoned seafood SKU via a Taco Tuesday theme" is
  the reference's SUBJECT, not its concept — the other brand sells none of that and will
  be briefed to make it. Write the shape the other brand will fill with its own material:
  "a single-product launch with a themed hook and a limited-time gift".
"concept_instance": the reference's own subject in a phrase, for the record only — the
  product, category or occasion it happened to be about. Recorded so the other brand
  knows what NOT to carry over, the same way a device records its instance.
"sections": an array, top to bottom, one object per section:
   {"n": 1,
    "what": what it is, in a phrase (a device if it is one: 'a social post shown as a post:
            avatar, handle, photo, icon row, dots, caption'),
    "does": what it does for the reader,
    "asset": {"kind": "photograph" | "mark" | "illustration" | "none",
              "role": which of these the picture plays — "hero: the product alone, big" |
                      "in use: the product in a scene, with food, hands, a person, a place" |
                      "the range: several pieces or formats together" | "detail: close on
                      texture, pattern, material" | "lifestyle: the world of the brand, the
                      product secondary" | "a person" — one of these, in these words, with
                      at most one clause of what the scene should FEEL like (sunlit, at the
                      table, on the move). NEVER the reference's prop, product, angle,
                      tilt or background — a basket, a jar, "viewed from above" — the other
                      brand casts from its own shelf and has none of those,
              "instance": the reference's own picture in a phrase, for the record only —
                      "a jar in a wire basket, tilted, from above",
              "shows": the same as "role" (kept for older readers)},
    "copy": [{"id": "s1_kicker", "job": what these words must do, in one line —
              'a two-line hook that turns on how the product is used', 'four numbered steps
              naming the product, the last step one word', "limit": words or lines}],
    "look": how it is set — ground, alignment, type roles, scale, spacing, framing}
"visual_system": {"type": the type roles and their character (display face heavy/condensed,
   small-caps kicker, script accent, body size), "colour": how colour is used (which
   grounds are dark, where the accent goes, how much contrast, whether the page turns),
   "rhythm": spacing, widths, insets, corner radii, rules, "column": the content width you see}
"devices": an array of every distinct device you can see, each an object:
   {"what": how it is drawn — shape, placement, scale, weight — so it can be drawn without
            the picture,
    "kind": "structure" (it carries the email: the hero, the post card, the product frame,
            the headline stack, the button, the footer) | "dressing" (it adds character: a
            mascot, a handwritten aside, a badge, a sticker, a doodle, a texture),
    "role": what it does for the reader in this email — points at the button, names the
            new format, adds a sensory cue, breaks the grid, signs the brand,
    "effect": the feeling it adds — informal, playful, handmade, urgent, premium,
    "instance": the reference's own instance in a phrase (its mascot, its word, its
            prop) — recorded so the other brand knows what NOT to copy}
"reference_text": every visible word of the email, line by line, verbatim.
"reference_hexes": the six most dominant colours as hex.
"argument": the email's copy as ONE argument, top to bottom, an array of beats:
   {"beat": "problem" | "evidence" | "reframe" | "proof" | "risk reversal" | "offer" |
            "invitation" | "ask" | "sign-off" (or a word of your own),
    "says": what the beat says, in a phrase (not the words verbatim — they are in
            reference_text; and not the reference's product or theme — the beat's JOB,
            which the other brand will rest on its own material),
    "does": what it does to the reader — names their disappointment, removes the risk,
            gives permission, earns the ask,
    "rests_on": what the beat needs to be TRUE — a fact, a test, a guarantee, a feeling the
            reader already has, nothing}
   — so the colleague can write the SAME ARGUMENT for the other brand, resting each beat on
   what that brand actually has, and drop or turn a beat it cannot rest.

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
    # devices are objects now (kind, role, effect, instance) and a busy
    # reference's brief runs past 6,000 tokens — the owner's re-read was cut
    # off mid-JSON and reported as "not a JSON object" (2026-09-17)
    reply = _ask("email_brief", blocks, tenant=tenant, max_tokens=16000)
    if not getattr(reply, "ok", False):
        return {"ok": False, "why": f"the reader did not answer — {getattr(reply, 'error', '')}", "calls": 1}
    got = _json(reply.text)
    why = brief_problem(got)
    if why and getattr(reply, "stop_reason", "") == "max_tokens":
        why = f"the reader's brief was cut off at the length limit ({len(reply.text or '')} characters) — {why}"
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

def _entity_row(e) -> dict:
    """One product as the maker reads it."""
    a = getattr(e, "attributes", None) or {}
    desc = re.sub(r"<[^>]+>", " ", str(getattr(e, "description", "") or ""))
    return {"key": e.key, "name": e.name, "type": getattr(e, "type", "") or "",
            "url": str(a.get("url") or ""), "price": str(getattr(e, "price", "") or a.get("price") or ""),
            "image": str(a.get("image") or ""), "description": _norm(desc)[:1200]}


def kit(tenant: str) -> dict:
    """Everything the brand has that an email may be made of. Every item is
    already on file and already approved — this gathers, it invents nothing."""
    from . import brand_theme, esp, kb, pictures as ed
    b = kb.brand(tenant)
    theme = brand_theme.filled(brand_theme.live_theme(tenant) or {})
    voice = (getattr(b, "voice", None) or {}) if b else {}
    # a SAMPLE of the catalogue for the maker's prompt — the subject of the
    # send is added by `run` whatever its place, so this cap never decides
    # which products exist
    ents = [_entity_row(e) for e in kb.entities(tenant)[:60]]
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
    logo_tone = _logo_tone(theme.get("logo_url") or "")
    return {"tenant": tenant, "name": theme.get("name") or (getattr(b, "display_name", "") if b else tenant),
            "positioning": str(getattr(b, "positioning", "") or "") if b else "",
            "voice": {k: voice.get(k) for k in ("tone", "do_say", "never_say") if voice.get(k)},
            "theme": theme, "entities": ents, "pictures": pics, "claims": claims, "handles": handles,
            "rules": {"channel": kb.channel_rules(tenant, "campaign_email") or ""},
            "esp": {"provider": esp.provider_for(tenant), "tokens": list(esp.TOKENS),
                    "webview": bool(caps.get("webview", True))},
            "logo_tone": logo_tone,
            "hosts": {h for h in hosts if h}}


def _logo_tone(url: str) -> str:
    """"light" | "dark" | "" — the mark's own luminance over its opaque pixels,
    so the composer knows which ground it needs. Baci's only mark on file is
    white; the maker set it on a yellow page (2026-09-17)."""
    if not url:
        return ""
    try:
        import io
        from PIL import Image
        from . import pictures
        blob = pictures._fetch_bounded(url)
        if not blob:
            return ""
        im = Image.open(io.BytesIO(blob)).convert("RGBA")
        im.thumbnail((256, 256))
        px = [(r, g, b) for r, g, b, a in im.getdata() if a > 128]
        if not px:
            return ""
        lum = sum(0.2126 * r + 0.7152 * g + 0.0722 * b for r, g, b in px) / (255 * len(px))
        return "light" if lum > 0.6 else "dark" if lum < 0.4 else ""
    except Exception:                                             # noqa: BLE001
        return ""


# ---------------------------------------------------------------------------
# 3. THE CAST — the brand's pictures chosen by LOOKING, with reasons
# ---------------------------------------------------------------------------

_CAST_PROMPT = """You are casting photographs for an email that recreates a reference design for the
brand %(name)s. The sheet shows the brand's own pictures, numbered. Each numbered cell is one
picture; under the sheet are the same pictures' filed facts.

The brief's picture slots — each names the ROLE a picture plays in the design:
%(slots)s

The brand's pictures will never match the reference's subject — a different product, in
different colours, on different tables, and NEVER its prop, its angle or its tilt. Cast by
ROLE: for each slot pick the ONE picture on the sheet that plays that role best for this
brand — a hero of the product; the product in use, in a scene, with people; the range
together; a detail; the brand's world — and say why in a line. Two slots with different
roles get two different KINDS of picture: a scene for "in use" or "lifestyle", the product
alone for "hero" or "the range". A picture of another product of the brand plays a
lifestyle role perfectly well. Colours do not matter — the email's tones follow the
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
    cols, cell, pad = 6, SHEET_CELL, 10
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


def _cell(blob: bytes, *, cell: int = SHEET_CELL) -> bytes:
    """One picture cut to its square on the contact sheet, as PNG bytes.

    The cut happens the moment the bytes arrive so the full-size picture is
    never held beside twenty-three others: a store master decodes to about
    eight megabytes and the sheet needs twenty kilobytes of it.
    """
    import io
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(blob))
        im.draft("RGB", (cell, cell))          # JPEG: decode small, never full
        im = im.convert("RGB")
        im.thumbnail((cell, cell), Image.LANCZOS, reducing_gap=2.0)
        buf = io.BytesIO()
        im.save(buf, format="PNG", optimize=True)
        im.close()
        return buf.getvalue()
    except Exception:                                            # noqa: BLE001
        return b""


def _role(sec: dict) -> str:
    """The role a slot's picture plays — `role` where the brief has it, the
    older `shows` otherwise."""
    a = sec.get("asset") or {}
    return str(a.get("role") or a.get("shows") or "").strip()


def _is_scene(p: dict) -> bool:
    """A photograph of the world — a scene, a person, a table — as against a
    packshot. Read by vision where a reading exists; by the store's own
    ordering and subject where it does not (locally no vision runs)."""
    k = str(p.get("kind") or "").lower()
    if k:
        return not k.startswith("packshot") and k not in ("mark", "logo", "graphic")
    if p.get("person") is True:
        return True
    return str(p.get("subject") or "") == "photo" and "packshot" not in (p.get("tags") or [])


def candidates(kit_: dict, *, entity_key: str = "", recent_media=(), seed: str = "") -> list[dict]:
    """The pictures the caster is shown — A MIX BY ROLE, so every slot has
    something to cast: the subject's own pictures (capped, scenes first),
    then the brand's scenes (people, tables, places — other products
    included), then packshots; what this list saw lately last; a seeded
    shuffle inside each rank so two campaigns on the same subject see a
    different order. The owner's run of 2026-09-17 offered 24 Portofino
    pictures and nothing else, and the lifestyle role went uncast."""
    import random
    recent = set(recent_media or ())
    rnd = random.Random(seed or "cast")
    pics = list(kit_.get("pictures") or [])
    rnd.shuffle(pics)
    own = [p for p in pics if entity_key and p.get("entity_key") == entity_key]
    own.sort(key=lambda p: (1 if p["id"] in recent else 0, 0 if _is_scene(p) else 1))
    rest = [p for p in pics if p not in own]
    scenes = sorted([p for p in rest if _is_scene(p)], key=lambda p: 1 if p["id"] in recent else 0)
    shots = sorted([p for p in rest if not _is_scene(p)], key=lambda p: 1 if p["id"] in recent else 0)
    third = max(4, CAST_MAX // 3)
    chosen = own[:third * 2 if not scenes else third] + scenes[:third] + shots[:third]
    for p in own[third:] + scenes[third:] + shots[third:]:
        if len(chosen) >= CAST_MAX:
            break
        if p not in chosen:
            chosen.append(p)
    return chosen[:CAST_MAX]


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
        out["none"] = [{"section": s.get("n"), "needs": _role(s) or "a photograph"} for s in slots]
        out["said"].append("no publishable picture on file — every photograph slot is cut")
        return out
    # ONE PICTURE IN MEMORY AT A TIME. This built a list of every candidate's
    # bytes before it drew anything: twenty-four pictures, six megabytes each
    # allowed, inside the process that also served the console. Each is now
    # fetched, cut to its cell and dropped.
    keep, cells = [], []
    for p in cands:
        blob = ed._fetch_bounded(p["small"]) or ed._fetch_bounded(p["url"])
        if not blob:
            continue
        cut = _cell(blob)
        del blob
        if cut:
            keep.append(p)
            cells.append(cut)
    if not keep:
        out["none"] = [{"section": s.get("n"), "needs": _role(s) or "a photograph"} for s in slots]
        out["said"].append("no picture could be fetched for the sheet — every photograph slot is cut")
        return out
    cands = keep
    sheet = _sheet(cells)
    facts = "\n".join(f'{i + 1}. {p["title"] or "untitled"}' + (f' — {p["kind"]}' if p.get("kind") else "")
                      + (f' — about {p["entity_key"]}' if p.get("entity_key") else "")
                      + (" — a person in it" if p.get("person") else "") for i, p in enumerate(cands))
    slot_text = "\n".join(f'section {s.get("n")}: {s.get("what")} — must show: '
                          f'{_role(s) or "(not said)"}' for s in slots)
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
            out["none"].append({"section": n, "needs": needs or (_role(s) or "a photograph")})
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
its type roles, its colour logic and its rhythm. Its devices are of two kinds:
- STRUCTURE (a social post shown as a post; a product frame; a headline stack; a bordered
  button; a numbered recipe) is recreated faithfully — DRAWN in HTML/CSS or inside a baked
  block (below), never approximated by a plain paragraph.
- DRESSING (a mascot, a handwritten aside, a badge, a sticker, a doodle) is KEPT, and
  RE-AUTHORED FROM THIS BRAND'S WORLD so it means something here: the same role and the same
  effect, played by a thing of this brand — its products, its place, its voice, what its
  photographs show. A snack brand's crunch word becomes a word that is TRUE of this product
  and of this email's idea; its cartoon shopper becomes a drawn thing from this brand's own
  world; its badge carries a fact from the material. Never the reference's instance, never a
  generic stand-in (a random exclamation, a random emoji), never decoration that says
  nothing. The standard below shows the move: a sauce brand's "SAUCE THE MEAT!" became a
  tableware brand's "Set the scene!"; its recipe's last step became "Mangia!". If nothing in
  this brand can play a dressing device honestly, leave it out and say so in the turned
  comment.
%(brief)s

THE BRAND
name: %(name)s — %(positioning)s
voice: %(voice)s
mark: %(logo)s%(logo_tone)s
accent colour on file: %(accent)s
today: %(today)s — never name a season, holiday or date that has passed; never invent a
  date, a deadline, a "this weekend", a launch or a discount that is not in the material
instagram handle: %(handle)s
postal address (footer, verbatim): %(address)s
faces on file: heading %(heading_face)s · body %(body_face)s
%(rules_brand)s

THE PICTURES — the brand's own, cast for this design by looking at them. Each is offered in
the original and cut to 1:1, 4:5, 3:2 and 16:9 (centre crops, 1200 px wide): use the cut
that fits the slot, never stretch. The tones measured from each are the palette this email
leads with: the page ground may be a photograph's bold tone if the reference's is, the card
its light tone; the brand's accent supports; every text colour must read on its ground.
THE REFERENCE'S COLOURS ARE NOT YOURS — not its ground, not its accent, not a near match of
either: if the reference is yellow, yours is this brand's. A mark that is light needs a dark
ground under it; on a light ground set the name in type instead.
%(pictures)s
%(cut)s

THE MESSAGE this email carries%(message)s
%(story)s
%(notes)sTHE STANDARD — %(standard_is)s. Copy its CRAFT (a headline that fills the column; the
page in the photograph's own tone; a device drawn faithfully; real product names and links;
tight copy that turns), NOT its design, not one of its words, and none of its pictures or
links — they are another email's:
%(exemplar)s

THE SYSTEM FIRST — the way a designer at a good studio works: before the first section,
set the system, then lay every section out from it. One rhythm reads as one email; a
different inset and a different size in every section reads as pieces glued together.
Declare it as the first line inside <body>, as a comment, and then USE ONLY THOSE VALUES:
<!-- system: faces display=… headline=… body=… accent=…(optional) ·
     scale: display/headline/subhead/body/small = 64/40/24/16/12 (your numbers) ·
     space: 8/16/32/56 (your four steps) · inset: 34 (one side inset, the whole column) ·
     radius: 14 -->
The faces: TWO — the brand's heading face for display and headlines, the brand's body face
for everything else — plus at most ONE accent face (a script, a marker hand) used ONCE, for
the single dressing device that needs it. Where the brand has no heading face on file, one
display face stands in for it. An italic of a face is that face; a different face for the
tagline, the pills, the buttons or the footer is a fourth voice and a fault. The scale: five sizes with clear steps; every font-size in the email is one
of them. The space: four steps; every vertical gap is one of them, and like things get the
same gap (headline→body, picture→caption, section→section). The inset: one number, every
section's content sits on it; a card inside the column has its own one inner inset. Colours
change, designs change; this discipline does not.

RULES
- Table layout, every style inline, one centred column %(column)d px wide (a width="%(column)d"
  table, max-width:%(column)dpx), a full-width outer table painting the page ground.
- Pictures: ONLY the URLs listed above, verbatim. Every <img> has alt text and an explicit
  width. No background-image. No <script>, <form>, <video>, <iframe>. An <svg> anywhere
  outside a baked block is a defect — social links are text, an icon is baked or left out.
- Type: outside baked blocks use email-safe stacks only (Georgia; Helvetica/Arial; Impact,
  'Arial Black' for a heavy display line; 'Brush Script MT', cursive for a script).
- BAKED BLOCKS: a display headline, a script line, a device with icons — anything that needs
  a web font or inline SVG — goes inside <!--bake-->…<!--/bake-->: exactly one complete
  <table width="…">, no links inside, TYPE AND DRAWN SHAPES ONLY: never a photograph (no
  <img> inside a baked block — a photograph is placed as its own <img>), never body copy
  (a baked block holds at most a dozen words), never a button or a product name. It is
  photographed on a transparent ground at 2× and replaced by one <img>; paint a ground
  inside it only when the device has one. A Google Fonts <link> in <head> is allowed for them.
- Every photograph appears ONCE. A second slot gets a second picture or a different cut,
  never the same one again.
- A product fact (dishwasher safe, BPA free, made in…, a material, a count) appears only if
  it is in the product's own text or the claims below — a callout is never invented.
- A social link only for a handle listed above; no "TikTok" without a TikTok handle.
- Social proof (quotes, testimonials, reviews) exists only when a claim or review is listed
  under the message; with none on file, that block carries a short useful tip or fact from
  the brand's material instead — no quotation marks, no attribution, nothing presented as
  what a customer said. Never a verified tick, a like count, a rating, a figure not listed.
- The brand's ban list is absolute. Every link is a real URL from the material or
  {{UNSUBSCRIBE}}%(webview)s; no other {{token}}, no "#".
- The footer carries the postal address verbatim and an Unsubscribe link on {{UNSUBSCRIBE}}.
- Under %(size)d KB.
- THE HONEST TURN: if the design's concept rests on a fact this brand's material does not
  have — a list of stores that stock it, a launch, a deal, an event — turn the concept to the
  nearest true one (the product on the site, the collection, the piece itself) and say what
  you turned in one HTML comment at the top: <!-- turned: … -->. Never a store, a stockist,
  a "near you", a date or a discount that is not in the material.

OUTPUT, exactly — the FIRST characters of your answer are "Subject:". No preamble, no plan,
no reasoning before it: what you turned and why goes ONLY inside the <!-- turned: … -->
comment at the top of the HTML, in three sentences at most. (A reply that deliberated first
ran out of room before the email was finished.)
Subject: <the subject line>
Preheader: <the preheader>
<!DOCTYPE html>… the complete HTML document. Nothing after it."""

_REVISE_PROMPT = """Below is the email you wrote and the judge's findings after comparing it to the reference.
EDIT the HTML to close each finding. Change only what a finding requires; every other line
stays exactly as it is. The same rules apply (email-safe outside baked blocks; only the
listed pictures; the address and {{UNSUBSCRIBE}}; nothing invented). Keep to the system
declared in the <!-- system --> comment at the top of <body>: an edit uses ITS faces, ITS
sizes, ITS spacing steps and ITS inset — never a new value; if the system itself is wrong,
change the comment and every place that follows from it.

%(story)s
FINDINGS — a [contrast] finding is closed FIRST and by changing the text colour or the ground
it sits on to a pair that reads at the floor it names (4.5:1, 3:1 for large type) — over a
photograph, by a solid panel or a darker/lighter ground under the words, never by leaving it
as it is; the rest in the order given.
%(findings)s

OUTPUT, exactly:
Subject: <the subject line, unchanged unless a finding names it>
Preheader: <the preheader>
<!DOCTYPE html>… the complete HTML document. Nothing after it.

THE HTML
%(html)s"""


_STORY_PROMPT = """You are the writer. Before a line of the email is set, decide THE STORY — the argument
this email makes for %(name)s — the way a good copywriter does: the reader's real objection,
the brand's real answer, the real reason to act, each resting on something the brand has.

THE REFERENCE'S ARGUMENT — another brand's email, read as beats:
%(argument)s

THE BRAND
name: %(name)s — %(positioning)s
voice: %(voice)s
%(rules_brand)s
THE MATERIAL — the only facts available (a product's own text, the approved claims):
%(material)s
%(notes)s

THE MESSAGE this email carries%(message)s

Write %(name)s's argument in the SHAPE of the reference's — its energy, its moves, its
contrast — not one-to-one: keep the beats that work for this brand, merge or drop the ones
that do not, re-order if that tells it better. Every beat RESTS on something named in the
material or the message; a beat with nothing to rest on (a guarantee the brand does not make,
a test nobody ran, a launch that is not happening) is turned to the nearest true thing or
dropped, and you say which. A contrast beat — the category's failing, what the reader has
settled for — NAMES WHOSE failing it is in its own words, so it can never read as the
brand's own product ("You know how most melamine goes." → the failings). No line implies what
is not true (a melamine plate is plastic; "the plastic is gone" is a lie by implication).
The hook means something on its own. The close is earned by what came before. Answer JSON:
{"hook": the headline stack's idea in a line,
 "beats": [{"beat": "...", "says": the beat in this brand's words — a line or two, the copy
            itself, "rests_on": the fact or claim it rests on, quoted from the material,
            "about": "the category" | "the reader" | "us" — whose failing or whose promise}],
 "turned": [what you turned or dropped and why],
 "close": the last line and the ask}"""


def decide_story(brief_: dict, kit_: dict, message: dict | None, *, tenant: str = "", entity_key: str = "") -> dict:
    """The argument for THIS brand, decided before the HTML. `{ok, story, why, calls}`.
    Owner, 2026-09-18: the maker had mapped the reference's copy slot by slot
    — a list of the category's failings landed beside Baci's own product with
    no frame, "NOT ALL MELAMINE" stood alone, "the plastic is gone" lied by
    implication. The story is one argument, held to the material, before a
    line is set."""
    arg = brief_.get("argument") or []
    if not arg:
        # an older brief with no argument read: the copy jobs stand in for it
        arg = [{"beat": f"section {sec.get('n')}", "says": "; ".join(str(c.get("job") or "") for c in sec.get("copy") or []),
                "does": sec.get("does") or "", "rests_on": "(not read)"} for sec in brief_.get("sections") or [] if sec.get("copy")]
    if not arg:
        return {"ok": True, "story": {}, "why": "the reference carries no copy to argue with", "calls": 0}
    theme = kit_.get("theme") or {}
    voice = kit_.get("voice") or {}
    never = list(voice.get("never_say") or []) + list((kb_ban(kit_.get("tenant", "")) or [])[:30])
    rules_brand = ("never say: " + ", ".join(map(str, never[:24])) + "\n") if never else ""
    if (kit_.get("rules") or {}).get("channel"):
        rules_brand += "the brand's email instructions: " + kit_["rules"]["channel"][:600] + "\n"
    prompt = _STORY_PROMPT % {
        "name": kit_.get("name") or theme.get("name") or "the brand",
        "positioning": kit_.get("positioning") or "", "voice": ", ".join(map(str, voice.get("tone") or [])) or "as the material reads",
        "rules_brand": rules_brand, "material": (_material(kit_, entity_key) or "(nothing beyond the product's name)")[:3000],
        "notes": kit_.get("_notes") or "",
        "argument": json.dumps(arg, ensure_ascii=False, indent=1)[:5000], "message": _message_text(message)}
    reply = _ask("email_compose", prompt, tenant=tenant, max_tokens=2500)
    got = _json(reply.text) if getattr(reply, "ok", False) else None
    if not isinstance(got, dict) or not got.get("beats"):
        return {"ok": False, "story": {}, "calls": 1,
                "why": "the writer did not answer with a story — " + str(getattr(reply, "error", "") or "no JSON")}
    return {"ok": True, "story": got, "why": "", "calls": 1}


def kb_ban(tenant: str) -> list:
    try:
        from . import kb
        return list(kb.banned_claims(tenant) or [])
    except Exception:                                             # noqa: BLE001
        return []


def _story_text(st: dict | None) -> str:
    if not st:
        return ""
    lines = [f"hook: {st.get('hook', '')}"]
    for b in st.get("beats") or []:
        lines.append(f"- [{b.get('beat', '')}] ({b.get('about', '')}) {b.get('says', '')}"
                     + (f"  — rests on: {b['rests_on']}" if b.get("rests_on") else ""))
    if st.get("close"):
        lines.append(f"close: {st['close']}")
    if st.get("turned"):
        lines.append("turned: " + "; ".join(map(str, st["turned"])))
    return "\n".join(lines)


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
            fitted: dict | None = None, html: str = "", findings=(), png: bytes = b"", story_: dict | None = None) -> dict:
    """`{ok, subject, preheader, html, why, edited}` — ONE MIND writes the
    copy and the HTML together; with `html` and `findings` it EDITS, LOOKING
    at `png` — its own email as a browser showed it. A designer who cannot
    see the render guesses sizes: the owner's run set a figure at 24 px and a
    script at 90 px beside a 520 px button and called the row centred
    (2026-09-17). The picture costs a few thousand tokens and ends that."""
    theme = kit_.get("theme") or {}
    seen_blocks: list = []
    if html and findings:
        prompt = _REVISE_PROMPT % {
            "findings": "\n".join(f'- [{f.get("severity", "")}] {f.get("where", "")}: {f.get("what", "")}'
                                  + (f' → {f["do"]}' if f.get("do") else "") for f in findings),
            "html": html,
            "story": ("THE STORY this email tells — an edit never changes a beat's meaning or drops its frame:\n"
                      + _story_text(story_) + "\n") if story_ else ""}
        if kit_.get("_notes"):
            prompt = kit_["_notes"] + "\n" + prompt
        if png:
            from . import pictures as ed
            try:
                _, edge = ed._tier_edge()
                seen_blocks = [ed._image_block(ed.contact_sheet(png, edge))] + \
                              [ed._image_block(p["png"]) for p in ed.strips(png, edge)[:4]]
                prompt = ("YOUR EMAIL AS A BROWSER SHOWS IT is above — whole, then top to bottom. LOOK before "
                          "you edit: what is tiny, what is clipped, what is off-centre, what is heavier or lighter "
                          "than you meant. Fix what you see as well as what the findings name.\n\n") + prompt
            except Exception:                                     # noqa: BLE001
                seen_blocks = []
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
            "logo_tone": (" — a LIGHT mark: it needs a dark ground" if kit_.get("logo_tone") == "light" else
                          " — a dark mark: it needs a light ground" if kit_.get("logo_tone") == "dark" else ""),
            "accent": ((theme.get("colors") or {}).get("accent") or "(none on file)"),
            "today": db.utcnow().strftime("%d %B %Y"),
            "handle": (kit_.get("handles") or {}).get("instagram") or "(none on file)",
            "address": (theme.get("footer") or {}).get("address") or "",
            "body_face": (theme.get("font") or {}).get("body") or "Helvetica, Arial, sans-serif",
            "heading_face": (theme.get("font") or {}).get("heading") or "(none — the body face)",
            "rules_brand": rules_brand,
            "brief": (json.dumps({k: brief_.get(k) for k in ("concept", "sections", "visual_system", "devices")},
                                 ensure_ascii=False, indent=1) if brief_.get("concept") else
                      "(no reference this time — DESIGN IT YOURSELF: a strong designed email in the standard "
                      "below, with one idea, one big picture, type at scale, the page in the picture's own tone, "
                      "a real device or two, one ask)"),
            "pictures": "\n".join(pics) or "(none)", "cut": cut,
            "message": _message_text(message),
            "exemplar": (kit_.get("_standard") or exemplar())[:14000],
            "standard_is": kit_.get("_standard_is") or "an email made by hand from another reference for another brand",
            "notes": kit_.get("_notes") or "",
            "story": ("\nTHE STORY — the argument this email makes, decided first; every line of copy belongs to a\n"
                      "beat and says what its beat says (its words may be tightened, never its meaning changed; a\n"
                      "beat marked \"the category\" keeps its frame so it never reads as ours).\n"
                      "A FAILING IS NEVER SET BESIDE THE PRODUCT: a beat about the category or the reader — what\n"
                      "they have settled for, how most of it goes — is set as TYPE ALONE on its ground, with no\n"
                      "photograph of this brand's product in that section, beside it, or directly above it; the\n"
                      "photograph arrives with the beat that answers it (\"Then there's …\"). Where the reference\n"
                      "paired its problem with a picture, that slot becomes type, or the picture moves down to the\n"
                      "answer. (The owner's run set \"STIFF. GENERIC. FORGOTTEN.\" beside a photograph of the\n"
                      "brand's own table, 2026-09-18 — it read as the product's failing.)\n"
                      + _story_text(story_) + "\n")
                     if story_ else "",
            "column": COLUMN, "size": HTML_MAX // 1000,
            "webview": " or {{VIEW_IN_BROWSER}}" if (kit_.get("esp") or {}).get("webview", True) else
                       " (this platform has no view-in-browser variable — offer none)"}
    asked = seen_blocks + [{"type": "text", "text": prompt}] if seen_blocks else prompt
    reply = _ask("email_compose", asked, tenant=tenant, max_tokens=16000)
    if not getattr(reply, "ok", False) and "Connection" in str(getattr(reply, "error", "")):
        # a dropped connection on a two-minute call is not the model's answer
        # — one more try before the round is lost (owner's run, 2026-09-17)
        reply = _ask("email_compose", asked, tenant=tenant, max_tokens=16000)
    if not getattr(reply, "ok", False):
        return {"ok": False, "html": "", "subject": "", "preheader": "", "edited": 0,
                "why": "the composer did not answer — " + str(getattr(reply, "error", ""))}
    subject, pre, out = _parse_email(reply.text)
    if "<table" not in out.lower() or getattr(reply, "stop_reason", "") == "max_tokens":
        cut = getattr(reply, "stop_reason", "") == "max_tokens"
        return {"ok": False, "html": "", "subject": "", "preheader": "", "edited": 0,
                "why": (f"the composer ran past the length limit ({len(reply.text or '')} characters) before the email was finished"
                        if cut else "the composer did not return an email")
                + (f" — it began: {(reply.text or '').strip()[:160]!r}" if (reply.text or "").strip() and not (reply.text or "").lstrip().startswith("Subject:") else "")}
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
        words = _norm(re.sub(r"<[^>]+>", " ", frag))[:200]
        if re.search(r"<img\b", frag, re.I):
            # a photograph is never pixels inside a picture — it stays an <img>
            # of its own (the owner's hero was baked into a 1200×800 PNG with
            # no alt, 2026-09-17); the block is left as HTML and said
            notes.append(f"not baked — a photograph inside the block: {words[:50] or '(no words)'}")
            out = out.replace(f"<!--bake-->{frag}<!--/bake-->", frag, 1)
            continue
        shot = shots.shoot_fragment(head, frag)
        if not shot.get("ok"):
            notes.append(f"a block could not be baked ({shot.get('why')}) — left as HTML")
            continue
        if shot.get("overflow"):
            notes.append(f"clipped: the baked block '{words[:40]}' is {shot['overflow']} px wider than its "
                         f"{shot.get('box', '?')} px box — its type must be smaller or its box wider")
        if shot.get("smallest_px") and float(shot["smallest_px"]) < 11:
            notes.append(f"unreadable: type at {float(shot['smallest_px']):.0f} px in the baked block "
                         f"'{words[:40]}' — 11 px is the floor for a phone")
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
    # 1. brand assets only — a filed picture, a cut of one (`fit` writes
    # `_WxH_crop_center` before the extension), the mark, or our own media
    # route (a baked device). A plausible file name on the brand's host that
    # is NOT on file is an invented picture: the maker wrote
    # `…_staged_tray_1200x800.png` and `Portofino_Collection_Range_…` on the
    # owner's third run (2026-09-17), both 404 — and this was a note.
    def _base(u: str) -> str:
        u = u.split("?", 1)[0]
        return re.sub(r"_\d+x\d*(?:_crop_\w+)?(\.\w+)$", r"\1", u)
    allowed = {_base(p["url"]) for p in kit_.get("pictures") or []} | ({_base(theme.get("logo_url"))} if theme.get("logo_url") else set())
    media_route = config.PUBLIC_BASE_URL.rstrip("/") + "/media/"
    hosts = set(kit_.get("hosts") or ())
    for im in w.imgs:
        src = im.get("src") or ""
        host = urlparse(src).netloc
        if src.startswith("data:") or src.startswith(media_route):
            continue
        if _base(src) not in allowed and host not in hosts:
            add("asset", "blocks", src[:100], "not one of the brand's own pictures")
        elif _base(src) not in allowed:
            add("asset_invented", "blocks", src[:100], "the brand's host, but no such picture on file — use a listed URL verbatim")
    # 2. nothing from the reference
    ref_words = brief_.get("reference_text") or []
    ref_grams = _grams(" ".join(map(str, ref_words)))
    hit = _grams(text) & ref_grams
    if hit:
        add("leak_words", "blocks", "copy", "five words in a row from the reference: " + sorted(hit)[0])
    from . import palette as _pal
    # a near-black, a near-white, a grey is nobody's colour — only the
    # reference's SATURATED colours can leak (#1a1a1a blocked a run, 2026-09-17)
    ref_hex = {_expand(h) for h in map(str, brief_.get("reference_hexes") or [])
               if _HEX.fullmatch(h.strip()) and _pal.saturation(_expand(h)) >= 0.15}
    ours_hex = {_expand(h) for h in _HEX.findall(html)}
    if ref_hex & ours_hex:
        add("leak_hex", "blocks", "colour", "the reference's own colour: " + ", ".join(sorted(ref_hex & ours_hex)[:3]))
    if reference_host and any(urlparse(im.get("src", "")).netloc == reference_host for im in w.imgs):
        add("leak_image", "blocks", "image", "a picture from the reference's host")
    seen_src: dict = {}
    for im in w.imgs:
        src = re.sub(r"\?.*$", "", im.get("src", ""))
        if src and src != re.sub(r"\?.*$", "", theme.get("logo_url") or "") and "/media/" not in src:
            seen_src[src] = seen_src.get(src, 0) + 1
    for src, n in seen_src.items():
        if n > 1:
            add("picture_twice", "blocks", src[-60:], f"the same photograph {n} times — a second slot gets a second picture")
            break
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
        def _alive(url: str) -> int:
            """The status a real visit gets: HEAD, and on a 429 or a 405 a
            GET after a breath — Shopify rate-limits scripted HEADs and answered
            429 for two live product pages on the owner's run (2026-09-17)."""
            import time as _t
            r = httpx.head(url, timeout=8, follow_redirects=True)
            if r.status_code in (429, 405):
                _t.sleep(2)
                r = httpx.get(url, timeout=12, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
            return r.status_code
        for href in sorted({h for h in w.links if h.startswith("http")}):
            try:
                code = _alive(href)
                if code == 429:
                    add("link_busy", "note", href[:80], "the site rate-limited the check (429) — not proven dead")
                elif code >= 400:
                    add("link", "blocks", href[:80], f"answers {code}")
            except Exception as e:                                # noqa: BLE001
                add("link", "blocks", href[:80], f"does not answer ({type(e).__name__})")
        # every picture resolves — a 404 is a broken image in every inbox
        for src in sorted({im.get("src") or "" for im in w.imgs}):
            if not src.startswith("http") or src.startswith(media_route):
                continue
            try:
                code = _alive(src)
                if code == 429:
                    add("link_busy", "note", src[:80], "the host rate-limited the check (429) — not proven missing")
                elif code >= 400:
                    add("picture_missing", "blocks", src[:80], f"the picture answers {code}")
            except Exception as e:                                # noqa: BLE001
                add("picture_missing", "blocks", src[:80], f"the picture does not answer ({type(e).__name__})")
    for href in w.links:
        if href in ("#", "") or href.startswith("#"):
            add("link_placeholder", "blocks", href or "#", "a placeholder link")
    return out


_SYSTEM = re.compile(r"<!--\s*system:(.*?)-->", re.S | re.I)


#: WCAG 2 AA: text reads at 4.5:1 against its ground; LARGE text — 24 px, or
#: 18.66 px at bold — at 3:1.
CONTRAST_BODY, CONTRAST_LARGE = 4.5, 3.0
#: A colour is a COLOUR (not a near-black, near-white or grey — nobody's)
#: from this much chroma, and it is the brand's or a photograph's when its hue
#: sits this close to one of theirs: a tint or a shade of it, not a new one.
CHROMA, HUE_SPREAD = 0.12, 25


def render_check(shot: dict, kit_: dict, cast_: dict | None = None) -> list[dict]:
    """READABILITY AND COHERENCE, measured on the render — what the reader sees.

    `check` reads contrast off the inline styles, and a new design routinely
    puts its colour where that cannot look: a class in a <style> block, a
    photograph behind the headline, rgb(), a link left in the browser's blue.
    `shots.shoot(read=True)` reads each line as the browser drew it — colour,
    size, weight, face — and shoots the page again with every letter
    transparent, so the ground under each line is its own pixels. Findings as
    `check` makes them: a line under the WCAG floor against nine-tenths of its
    ground, and a colour neither the brand's nor a tone of the photographs
    cast for this email. The faces and sizes the render shows are held to the
    composer's declared system by `system_check(seen=shot)`."""
    import io
    from PIL import Image, ImageStat
    from . import palette
    out: list[dict] = []
    add = lambda code, sev, where, what: out.append({"code": code, "severity": sev, "where": where, "what": what})  # noqa: E731
    texts = shot.get("texts") or []
    ground = Image.open(io.BytesIO(shot["ground"])).convert("RGB") if shot.get("ground") else None
    said: set = set()
    for t in texts if ground else []:
        r, g, b, a = _rgba(t["color"])
        a *= float(t.get("opacity") or 1)
        px: list = []
        spread = 0.0
        for x, y, w, h in t["rects"][:2]:
            box = (max(0, int(x)), max(0, int(y)),
                   min(ground.width, int(x + w) + 1), min(ground.height, int(y + h) + 1))
            if box[2] > box[0] and box[3] > box[1]:
                crop = ground.crop(box)
                spread = max(spread, *ImageStat.Stat(crop).stddev)
                crop.thumbnail((32, 8))
                px += list(crop.getdata())
        if not px:
            continue
        ratios = sorted(_ratio(tuple(round(a * c + (1 - a) * q) for c, q in zip((r, g, b), p)), p)
                        for p in px)
        ratio = ratios[len(ratios) // 10]
        large = t["size"] >= 24 or (t["size"] >= 18.66 and t["weight"] >= 700)
        floor = CONTRAST_LARGE if large else CONTRAST_BODY
        if ratio >= floor:
            continue
        mid = tuple(sorted(c)[len(c) // 2] for c in zip(*px))
        fg, under = palette.to_hex((r, g, b)), palette.to_hex(mid)
        if (fg, under) in said:
            continue
        said.add((fg, under))
        add("contrast", "blocks", t["text"][:40],
            f"{fg} on {under if spread <= 8 else f'a photograph (around {under})'} reads at {ratio:.1f}:1"
            f" — {floor:g}:1 is the floor for {'large' if large else 'body'} text")
    theme = kit_.get("theme") or {}
    ours = [h for h in (theme.get("colors") or {}).values() if isinstance(h, str) and palette.parse(h)]
    for pick in ((cast_ or {}).get("picks") or {}).values():
        ours += [h for h in (pick.get("colours") or {}).values() if isinstance(h, str) and palette.parse(h)]
    ours = sorted({palette.norm(h) for h in ours if _chroma(h) >= CHROMA})
    # WHAT IS PAINTED: a text colour carried by twenty letters or more, a
    # ground as big as a button or bigger — a badge-sized chip is not a colour
    # of the design.
    used: dict = {}
    for t in texts:
        h = palette.to_hex(_rgba(t["color"])[:3])
        used[h] = used.get(h, 0) + int(t.get("chars") or 0)
    used = {h: n for h, n in used.items() if n >= 20}
    for g_ in shot.get("grounds") or []:
        rgba = _rgba(g_["color"])
        if rgba[3] >= 0.5 and int(g_.get("area") or 0) >= 2000:
            h = palette.to_hex(rgba[:3])
            used[h] = used.get(h, 0) + int(g_["area"])
    strays = [h for h, _n in sorted(used.items(), key=lambda kv: -kv[1])
              if _chroma(h) >= CHROMA and not any(_hue_gap(h, o) <= HUE_SPREAD for o in ours)]
    for h in strays[:3]:
        add("off_palette", "blocks", "colour",
            f"{h} is neither the brand's colour nor a tone of its photographs — "
            + (f"use {', '.join(ours[:4])} or a tint of one" if ours else
               "this brand and its photographs are neutral here: keep to them"))
    return out


def _rgba(css: str) -> tuple:
    """`rgb(r, g, b)` / `rgba(r, g, b, a)`, as the browser reports a colour."""
    v = [float(x) for x in re.findall(r"[\d.]+", css or "")]
    return (int(v[0]), int(v[1]), int(v[2]), v[3] if len(v) > 3 else 1.0) if len(v) >= 3 else (0, 0, 0, 1.0)


def _ratio(fg: tuple, bg: tuple) -> float:
    a, b = _lum(*fg), _lum(*bg)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


@functools.lru_cache(maxsize=65536)
def _lum(r: int, g: int, b: int) -> float:
    from . import palette
    return palette.luminance(palette.to_hex((r, g, b)))


def _chroma(h: str) -> float:
    from . import palette
    rgb = palette.parse(h) or (0, 0, 0)
    return (max(rgb) - min(rgb)) / 255


def _hue_gap(a: str, b: str) -> float:
    import colorsys
    from . import palette
    ha, hb = (colorsys.rgb_to_hsv(*(c / 255 for c in (palette.parse(x) or (0, 0, 0))))[0] * 360
              for x in (a, b))
    d = abs(ha - hb)
    return min(d, 360 - d)


def system_check(html: str, seen: dict | None = None) -> list[dict]:
    """The composer is held to the system IT declared: the sizes it uses are
    its scale, the side insets its inset, the faces its four at most. Not a
    taste rule — its own word. The owner, 2026-09-17: "the padding is
    inconsistent per section so it looks choppy; too much variation in fonts
    and sizes." Baked blocks are pictures by now, so display type set inside
    them is not counted. `{code, severity, where, what}` findings.

    With `seen` — a shot read by `shots.shoot(read=True)` — the sizes and
    faces are the ones the RENDER shows; the inline styles miss a class in a
    <style> block, and a new design puts its type there."""
    out: list[dict] = []
    m = _SYSTEM.search(html)
    if not m:
        return [{"code": "system", "severity": "blocks", "where": "body",
                 "what": "no <!-- system: … --> declared at the top of <body> — set the faces, the scale, the "
                         "spacing steps and the inset first, then lay out from them"}]
    decl = m.group(1)
    body = html[m.end():]
    nums = lambda seg: [int(float(x)) for x in re.findall(r"\d+(?:\.\d+)?", seg)]  # noqa: E731
    seg = lambda key: (re.search(key + r"\s*:?(.*?)(?:·|\n|$)", decl, re.I | re.S) or [None, ""])[1]  # noqa: E731
    scale = [x for x in nums(seg("scale")) if x >= 8]     # "display=72 / headline=40 …" or "72/40/32/24/16/12"
    inset = nums(seg("inset"))[:1]
    texts = (seen or {}).get("texts")
    used_sizes = (sorted({round(t["size"]) for t in texts if t["size"] > 2}) if texts is not None else
                  sorted({int(float(x)) for x in re.findall(r"font-size:\s*(\d+(?:\.\d+)?)px", body) if float(x) > 2}))
    if scale:
        stray = [x for x in used_sizes if not any(abs(x - d) <= 1 for d in scale)]
        if len(stray) >= 2:
            out.append({"code": "system_scale", "severity": "blocks", "where": "type",
                        "what": f"font sizes {', '.join(map(str, stray))} px are not in the declared scale "
                                f"{'/'.join(map(str, scale))} — set each to a step of the scale"})
    sides: dict = {}
    # cell insets only — a button's own padding or a paragraph's is not the column's
    for td in re.findall(r"<td\b[^>]*>", body, re.I):
        pm = re.search(r"padding:\s*([^;\"]+)", td)
        if not pm:
            continue
        v = nums(pm.group(1).replace("!important", ""))
        if not v:
            continue
        r_, l_ = (v[0], v[0]) if len(v) == 1 else (v[1], v[1]) if len(v) in (2, 3) else (v[1], v[3])
        for x in (r_, l_):
            if x >= 12:
                sides[x] = sides.get(x, 0) + 1
    distinct = sorted(sides)
    if inset and len([x for x in distinct if abs(x - inset[0]) > 1]) > 3:
        out.append({"code": "system_inset", "severity": "blocks", "where": "spacing",
                    "what": f"side insets {', '.join(map(str, distinct))} px — the system declares {inset[0]}; the column "
                            f"content sits on {inset[0]}, a card may have one inner inset, nothing else"})
    faces = {re.split(r"\s*,", f.strip().strip("'\""))[0].strip("'\" ").lower()
             for f in ([t["family"] for t in texts] if texts is not None else
                       re.findall(r"font-family:\s*([^;\"]+)", body))}
    if len(faces) > 3:
        out.append({"code": "system_faces", "severity": "blocks", "where": "type",
                    "what": f"{len(faces)} faces in use ({', '.join(sorted(faces))}) — three at most: the brand's heading "
                            f"face, its body face, and one accent used once"})
    return out


def story_check(html: str, story_: dict | None, kit_: dict) -> list[dict]:
    """A beat about the category or the reader is never set in the same
    row as, or the row next to, a photograph of the brand's product. Held
    from the story the maker itself decided. `{code, severity, where, what}`."""
    if not story_:
        return []
    # a FAILING: the category's, or a problem/objection beat about the reader — an
    # invitation or an offer addressed to the reader sits beside the product happily
    beats = [b for b in (story_.get("beats") or [])
             if str(b.get("about") or "").lower() == "the category"
             or (str(b.get("about") or "").lower() == "the reader"
                 and re.search(r"problem|objection|pain|failing|doubt|scepticism|skepticism|settled", str(b.get("beat") or ""), re.I))]
    if not beats:
        return []
    theme = kit_.get("theme") or {}
    logo = re.sub(r"\?.*$", "", theme.get("logo_url") or "")
    media_route = config.PUBLIC_BASE_URL.rstrip("/") + "/media/"
    filed = {re.sub(r"\?.*$", "", p["url"]) for p in kit_.get("pictures") or []}
    def _product_img(chunk: str) -> bool:
        for src in re.findall(r"<img[^>]*src=\"([^\"]+)\"", chunk, re.I):
            base = re.sub(r"\?.*$", "", src)
            if base.startswith(media_route) or base == logo:
                continue
            stem = re.sub(r"_\d+x\d*(?:_crop_\w+)?(\.\w+)$", r"\1", base)
            if base in filed or stem in filed or any(f.startswith(stem.rsplit(".", 1)[0]) for f in filed):
                return True
        return False
    rows = re.split(r"(?=<tr\b)", html, flags=re.I)
    plain = [re.sub(r"\s+", " ", _norm(re.sub(r"<[^>]+>", " ", r))).lower() for r in rows]
    out: list[dict] = []
    for b in beats:
        key = " ".join(re.findall(r"[a-z0-9']+", _norm(str(b.get("says") or "")).lower())[:5])
        if len(key) < 12:
            continue
        for i, txt in enumerate(plain):
            if key in txt:
                near = rows[max(0, i - 1): i + 2]
                if any(_product_img(c) for c in near):
                    out.append({"code": "failing_beside_product", "severity": "blocks", "where": f"the beat '{key[:40]}…'",
                                "what": "a failing of the category is set beside or under a photograph of the brand's product "
                                        "— it reads as the product's failing; set the failing as type alone and move the "
                                        "photograph to the beat that answers it"})
                    break
    return out


def _material(kit_: dict, entity_key: str) -> str:
    """The product's own text — what the judge may hold ours to."""
    ents = kit_.get("entities") or []
    e = next((x for x in ents if x.get("key") == entity_key), None)
    lines = []
    if e:
        lines.append(f"{e.get('name', '')}: {str(e.get('description') or '')[:1200]}")
    for c in (kit_.get("claims") or [])[:12]:
        lines.append("claim: " + str(c.get("claim") or ""))
    return "\n".join(lines)


def _inline_media(html: str) -> str:
    """For the SHOT only: our own media route's pictures as data URIs, so the
    judge sees the baked devices whether or not this process has a server
    behind it (the runner on a laptop has none — the judge saw nine broken
    pictures and said so, 2026-09-17)."""
    import base64
    from . import media
    base = config.PUBLIC_BASE_URL.rstrip("/") + "/media/"
    def _one(m):
        try:
            blob, mime = media.get(m.group(1))
            if blob:
                return f"data:{mime or 'image/png'};base64," + base64.b64encode(blob).decode()
        except Exception:                                         # noqa: BLE001
            pass
        return m.group(0)
    return re.sub(re.escape(base) + r"([0-9a-f]{32})\.\w+", _one, html)


def blocking(findings) -> list[dict]:
    return [f for f in (findings or []) if f.get("severity") == "blocks"]


# ---------------------------------------------------------------------------
# 7. THE JUDGE — ours beside the reference; findings, never a score
# ---------------------------------------------------------------------------

#: The maker declares an HONEST TURN in a comment at the top of its HTML (see
#: `_COMPOSE_PROMPT`). Nothing read it, so the turn could not reach the judge —
#: which went on holding the reference's own concept and blocked the email for
#: not being about it. A brief whose concept named the reference's SUBJECT
#: ("a new pre-seasoned seafood SKU via a Taco Tuesday theme") therefore had no
#: winning move: carry the subject over and the brand has no such product, turn
#: it and the judge calls it not the reference's concept. Both ends of that
#: squeeze are closed — the brief writes form (above), and a declared turn is
#: now told to the judge and never blocks.
_TURNED = re.compile(r"<!--\s*turned\s*:(.*?)-->", re.S | re.I)


def turned(html: str) -> str:
    """What the maker said it turned, or "". The comment is its own record."""
    m = _TURNED.search(html or "")
    return " ".join((m.group(1) if m else "").split())[:400]


_JUDGE_PROMPT = """Two emails: first the REFERENCE (whole, then its top), then OURS (whole, then its top).
Ours was made to RECREATE the reference's design for another brand — a different product,
its own photographs, its own words, its own colours. The designer's brief of the reference:
concept: %(concept)s
devices: %(devices)s
%(turned)s
The pictures are labelled in their top band: REFERENCE, then OURS. Judge OURS — the email
made for the other brand — as an art director judges a finished email, and answer JSON only:
{"ours_first_words": the first eight words you can read in OURS, top to bottom — so we know
                     you looked at the right email,
 "same_concept": true|false,
 "devices_in_order": true|false,
 "weight_rhythm": one line on scale, spacing and visual weight compared,
 "one_system": true|false — ours reads as ONE email: the same inset down the column, the
               same gap between like things, one type scale with clear steps, two faces and
               at most one accent used once; where it breaks, a finding names the section
               and the value,
 "brand_material": true|false — everything in ours is the other brand's own,
 "would_send": true|false — as strong an idea, as bold a scale, as clear an ask as the
               reference, in this brand's things,
 "findings": [{"where": "section n / the headline / the post card",
               "what": what is WEAK — in the role the device plays, in this brand's terms,
               "do": the concrete edit that makes it strong, in this brand's terms,
               "severity": "blocks" if you would not send it without this, else "cosmetic"}]}
Every "do" is an edit the composer can make in HTML/CSS with the pictures already in the
email and web type — resize, re-set, re-colour, move, cut, rewrite the words, draw a simple
shape. Never "photograph", "stage", "shoot", "commission", "composite" or "source" a picture
that does not exist: a finding that needs a new picture is not a finding, say "cut it" or
name the picture in the email that should play the role instead.
The question is never "what differs from the reference" — a difference is correct by design.
The question is "would you send this": is the idea as sharp, the headline as loud, the hero
as big, the rhythm as tight, the ask as clear. Name what is timid, dead, cramped, unreadable,
broken, empty or generic, and say the edit.
THE COPY is judged as an editor judges it, in the same findings: does the hook mean something
on its own (a fragment that needs the next line to make sense is a fault); is every beat
clearly about WHOM — a list of the category's failings must carry its frame ("you know how
most … goes") or it reads as the brand's own product, and a failing set BESIDE or directly
under a photograph of the brand's product reads as the product's failing whatever the words
say — a fault, fixed by setting the failing as type alone and moving the picture to the
answer; does the close earn its ask from what
came before; is there a line that says nothing ("set the table like you mean it" is a mood,
not a claim — allowed once, as a closer, never as the argument).
%(notes)sDRESSING (a mascot, a handwritten aside, a badge, a sticker) is judged on whether it BELONGS
to this brand and EARNS its place: re-authored from this brand's world — its products, its
place, its voice — it is correct however much it differs from the reference's; a generic
stand-in (a random exclamation, an emoji, a doodle that means nothing) or the reference's own
instance in disguise is a fault — say "cut it" or say what of this brand's world should play
the role instead. Never ask for the reference's prop, word, mascot, lettering or colours, and
never quote the reference's words."""


_JUDGE_ALONE = """One email, ours (whole, then its top), made for a brand with no reference to follow.
Judge it as an art director would — against the standard of the best designed brand emails:
one idea, type at scale, the page in a photograph's own tone, a device or two drawn well,
one ask, nothing generic. Answer JSON only:
{"same_concept": true, "devices_in_order": true, "brand_material": true,
 "weight_rhythm": one line on scale, spacing and visual weight,
 "findings": [{"where": "...", "what": what falls short in a way that matters, "do": the concrete edit,
               "severity": "blocks" if it must change before sending, else "cosmetic"}]}"""


_TRUTH_PROMPT = """The words of an email, then the ONLY material the brand has on file about what it sells.
List every statement in the email about the product or the brand — an origin, a material, a
property (safe, free of, proof), a count, a place it is sold, an award, a claim of who uses
it, a guarantee, a test — that the material does not support, INCLUDING what a line implies
rather than says: "the plastic is gone" about a melamine plate implies it is not plastic;
"we're sure enough to put it on us" implies a guarantee; "tested" implies a test. A word that
merely describes (beautiful, complete, ready) is not a fact; a contrast that names the
CATEGORY's failing ("most melamine fades") is not a claim about this product — but a NUMBER about the
category (a temperature, a percentage, a year, a price band, "studies show") that the material
does not give is fabricated. Answer JSON only: {"fabricated": [{"words": the exact words in the
email, "why": what the material says instead, or that it says nothing}]}

THE EMAIL'S WORDS
%(words)s

THE MATERIAL
%(material)s"""


def _Walk_words(html: str) -> str:
    w = _Walk()
    w.feed(html)
    return w.words()


def _devices_text(brief_: dict) -> str:
    out = []
    for d in brief_.get("devices") or []:
        if isinstance(d, dict):
            out.append(f"[{d.get('kind') or 'device'}] {d.get('what') or ''} — role: {d.get('role') or ''}"
                       + (f"; effect: {d['effect']}" if d.get("effect") else ""))
        else:
            out.append(str(d))
    return "; ".join(out)


def truth(words: str, material: str, *, tenant: str = "") -> dict:
    """The fact check, apart from the design judge: every product statement in
    the email against the brand's own material. `{ok, findings, calls}`.
    Asked with the design questions, it got a ninth of the attention and let
    "BPA Free" through (2026-09-17); asked alone it is one short text call."""
    if not words.strip():
        return {"ok": True, "findings": [], "calls": 0}
    got, calls = None, 0
    for _ in range(2):
        reply = _ask("email_judge", [{"type": "text", "text": _TRUTH_PROMPT % {
            "words": words[:9000], "material": (material or "(nothing beyond the product's name)")[:5000]}}],
            tenant=tenant, max_tokens=2500)
        calls += 1
        got = _json(reply.text) if getattr(reply, "ok", False) else None
        if isinstance(got, dict):
            break
    if not isinstance(got, dict):
        # SAID, never silent: a truth pass that did not answer left a round
        # with "0 checks block" and fifteen fabrications (2026-09-20)
        return {"ok": False, "calls": calls, "why": "the truth pass did not answer — " + str(getattr(reply, "error", "") or "no JSON, twice"),
                "findings": [{"code": "truth_unread", "severity": "blocks", "where": "the words",
                              "what": "the fact check did not answer, so nothing here is proven true"}]}
    return {"ok": True, "calls": calls, "findings": [
        {"code": "fabricated", "severity": "blocks", "where": str(f.get("words") or "")[:120],
         "what": "not in the brand's material — " + str(f.get("why") or "")[:200]}
        for f in got.get("fabricated") or [] if isinstance(f, dict) and f.get("words")]}


def _stamp(png: bytes, label: str) -> bytes:
    """The label drawn INTO the picture, a black band across the top — so the
    judge cannot take the reference for ours. On the owner's run of
    2026-09-17 it did, twice: "the basket is cropped so the jar dominates",
    "'PICKLES' is not oversized" — about an email with no basket, jar or
    pickles — and the maker applied the edits. A label in the prompt alone
    was not enough; a label in the pixels is what it reads."""
    import io
    from PIL import Image, ImageDraw, ImageFont
    from . import llm, pictures as ed
    im = Image.open(io.BytesIO(png)).convert("RGB")
    band = max(28, im.width // 24)
    # the band must not push the picture past the model's edge or budget —
    # a sheet cut to exactly 1568 tall came back 1596 and was REFUSED, so the
    # article judge never answered (2026-09-20); shrink first, then stamp
    tier, edge = ed._tier_edge()
    w, h = llm.resized_size(im.width, im.height + band, edge, llm.IMAGE_TIERS[tier]["max_tokens"])
    if (w, h) != (im.width, im.height + band):
        im = im.resize((max(1, w), max(1, h - band)), Image.LANCZOS)
        band = min(band, max(20, im.width // 24))
    out = Image.new("RGB", (im.width, im.height + band), "#000000")
    out.paste(im, (0, band))
    d = ImageDraw.Draw(out)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", int(band * 0.7))
    except Exception:                                             # noqa: BLE001
        font = ImageFont.load_default()
    d.text((12, band // 6), label, fill="#ffffff", font=font)
    buf = io.BytesIO()
    out.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _confused(got: dict, brief_: dict) -> str:
    """Why a judgement is not about OUR email: the words it says it read in
    ours are the reference's. "" when it read ours."""
    said = _norm(str(got.get("ours_first_words") or "")).lower()
    if not said:
        return ""
    # a line of one short common word ("find", "shop") is no evidence; two
    # words, or one distinctive word, is
    lines = [_norm(str(x)).lower() for x in (brief_.get("reference_text") or [])
             if len(_norm(str(x)).split()) >= 2 or len(_norm(str(x))) >= 7]
    hit = [ln for ln in lines if f" {ln} " in f" {said} "]
    return f"it read the reference's words ({hit[0][:30]!r}) as ours" if hit else ""


def judge(reference_png: bytes, ours_png: bytes, brief_: dict, *, tenant: str = "", material: str = "",
          notes: str = "", turned_: str = "") -> dict:
    """`{ok, findings, verdict, why, calls}` — ours beside the reference, or
    ours alone when there is no reference. The pictures are stamped and
    labelled, the judge must say what it read in ours, and a judgement that
    read the reference as ours is refused as confused; a judge that answers
    no JSON is asked once more."""
    from . import pictures as ed
    if not ours_png:
        return {"ok": False, "findings": [], "verdict": {}, "why": "no picture to judge", "calls": 0}
    _, edge = ed._tier_edge()
    blocks = []
    try:
        pairs = [("REFERENCE", reference_png), ("OURS", ours_png)] if reference_png else [("OURS", ours_png)]
        for label, png in pairs:
            blocks.append({"type": "text", "text": f"{label} — the whole email:"})
            blocks.append(ed._image_block(_stamp(ed.contact_sheet(png, edge), f"{label} — whole")))
            blocks.append({"type": "text", "text": f"{label} — its top, legible:"})
            blocks.append(ed._image_block(_stamp(ed.strips(png, edge)[0]["png"], f"{label} — top")))
    except Exception as e:                                        # noqa: BLE001
        return {"ok": False, "findings": [], "verdict": {}, "why": f"a picture could not be cut: {e}", "calls": 0}
    blocks.append({"type": "text", "text": (_JUDGE_PROMPT % {
        "concept": brief_.get("concept"), "devices": _devices_text(brief_)[:1500], "notes": notes or "",
        "turned": (f"THE MAKER TURNED THE CONCEPT, and said so: {turned_}\nThat turn is the "
                   "design working, not a fault — this brand's material does not carry the "
                   "reference's subject. Judge OURS against the TURNED concept: the same FORM, "
                   "resting on what this brand actually has.\n") if turned_ else ""})
        if reference_png else _JUDGE_ALONE})
    calls = 0
    got, mixed = None, ""
    for _try in range(2):
        reply = _ask("email_judge", blocks, tenant=tenant, max_tokens=2500)
        calls += 1
        got = _json(reply.text) if getattr(reply, "ok", False) else None
        if not isinstance(got, dict):
            mixed = "no JSON"
            continue
        mixed = _confused(got, brief_) if reference_png else ""
        if not mixed:
            break
    if not isinstance(got, dict):
        return {"ok": False, "findings": [], "verdict": {}, "calls": calls,
                "why": "the judge did not answer — " + str(getattr(reply, "error", "") or "no JSON, twice")}
    if mixed:
        return {"ok": False, "findings": [], "verdict": {}, "calls": calls,
                "why": f"the judge was confused twice — {mixed}; its findings are not used"}
    finds = []
    for f in got.get("findings") or []:
        if isinstance(f, dict) and f.get("what"):
            finds.append({"code": "judge", "severity": "blocks" if str(f.get("severity", "")).lower() == "blocks" else "cosmetic",
                          "where": str(f.get("where") or "")[:80], "what": str(f.get("what"))[:300],
                          "do": str(f.get("do") or "")[:300]})
    verdict = {k: got.get(k) for k in ("same_concept", "devices_in_order", "weight_rhythm", "brand_material",
                                       "would_send", "one_system", "ours_first_words")}
    if verdict.get("same_concept") is False:
        # A DECLARED TURN IS NOT A FAULT. Blocking here is what trapped the
        # loop: obey a concept naming the reference's own product and the
        # brand has none of it, turn it and this fired. The turn stays on the
        # record as a cosmetic finding — visible, never fatal.
        finds.insert(0, {"code": "judge",
                         "severity": "cosmetic" if turned_ else "blocks",
                         "where": "the whole",
                         "what": ("the concept was turned, and ours follows the turn "
                                  f"rather than the reference: {turned_}" if turned_
                                  else "not the reference's concept"),
                         "do": ("" if turned_ else "recreate the concept the brief names")})
    return {"ok": True, "findings": finds, "verdict": verdict, "why": "", "calls": calls}


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
    # WHAT THE OWNER APPROVED IS THE STANDARD, AND WHAT THEY SAID IS REMEMBERED
    # (Phase 4). The bar rises with the brand's own best work instead of
    # staying at the hand-made email of 2026-09-12.
    from . import exemplars as _ex
    from .email_structures import note_of as _es_note
    _std, _std_is = _ex.standard(tenant, _ex.EMAIL, fallback=exemplar())
    kit_["_standard"], kit_["_standard_is"] = _std, _std_is
    kit_["_notes"] = _ex.notes_text(tenant, _ex.EMAIL)
    # AND WHAT THE OWNER SAID ABOUT THIS ONE DESIGN. Written on the shelf as
    # "why we keep this" — a field that only sat on a card would be the same
    # defect as a KB rule that never reaches a validator, so it rides with
    # the brand's standing notes and outranks the brief exactly as they do.
    _ref_note = _es_note(structure_id)
    if _ref_note:
        kit_["_notes"] = (kit_["_notes"] + "\n" if kit_["_notes"] else "") + (
            "WHAT THE OWNER HAS SAID ABOUT THIS DESIGN — their words, and they "
            "outrank the brief and the reference:\n- " + _ref_note + "\n")
        story.append(f"Held to what you said about this design: {_ref_note[:120]}")
    if _ex.notes(tenant, _ex.EMAIL):
        story.append(f"Held to what you have said about this brand's emails ({len(_ex.notes(tenant, _ex.EMAIL))} note(s)).")
    if entity_key and not any(e.get("key") == entity_key for e in kit_.get("entities") or []):
        # THE SUBJECT IS LOOKED UP IN THE CATALOGUE, NOT IN THE KIT'S SAMPLE.
        # The kit carries sixty products for the prompt; a store has hundreds,
        # and until 2026-09-23 any subject past the sixtieth was reported as
        # "not on file" — Baci's campaign email failed that way on a product
        # it stocks.
        from . import kb as _kbx
        hit = next((e for e in _kbx.entities(tenant, available_only=False)
                    if e.key == entity_key), None)
        if hit is not None and getattr(hit, "availability", "available") != "available":
            story.append(f"{hit.name!r} is on file but not available "
                         f"({hit.availability}) — an email should not sell it.")
            return _finish(FAILED, brief=brief_)
        if hit is not None:
            kit_["entities"].insert(0, _entity_row(hit))
    if entity_key and not any(e.get("key") == entity_key for e in kit_.get("entities") or []):
        # THE SUBJECT MUST EXIST. The owner's run asked for a key that was not
        # on file and the maker quietly sold a different product (2026-09-17).
        import difflib
        near = difflib.get_close_matches(entity_key, [e.get("key") or "" for e in kit_.get("entities") or []], n=3, cutoff=0.4)
        story.append(f"No product with the key {entity_key!r} on file"
                     + (f" — did you mean {', '.join(near)}?" if near else "."))
        return _finish(FAILED, brief=brief_)
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
    say("deciding the story")
    told_story = decide_story(brief_, kit_, message, tenant=tenant, entity_key=entity_key)
    calls += told_story.get("calls", 0)
    story_ = told_story.get("story") or None
    if story_:
        story_note = f"The story: {str(story_.get('hook') or '')[:90]} — {len(story_.get('beats') or [])} beats"
        if story_.get("turned"):
            story_note += "; turned: " + "; ".join(map(str, story_["turned"]))[:240]
        story.append(story_note + ".")
    elif told_story.get("why"):
        story.append("No story decided: " + str(told_story.get("why")) + ".")
    copy_ = {"claims": list((message or {}).get("claims") or [])}
    # the rounds
    ref_png, ref_host = _reference_png(structure_id)
    if aid and not ref_png:
        story.append("The reference picture could not be fetched — ours is judged on its own.")
    rounds: list[dict] = []
    html, raw, findings_prev, prev_png = "", "", [], b""
    ref_grams = _grams(" ".join(map(str, brief_.get("reference_text") or [])), 3) - _grams(
        " ".join(e.get("name", "") + " " + e.get("description", "") for e in kit_.get("entities") or []), 3)
    # the reference's own lines, whole — "PICKLES", "HOT GIRL", "mess-free" are one or two
    # words and no 3-gram catches them; a finding that quotes one is the reference talking
    brand_words = set(re.findall(r"[a-z0-9']+", " ".join(e.get("name", "") + " " + e.get("description", "")
                                                          for e in kit_.get("entities") or []).lower()))
    ref_lines = []
    for x in brief_.get("reference_text") or []:
        ln = re.sub(r"[^a-z0-9' ]+", " ", _norm(str(x)).lower()).strip()
        ln = re.sub(r"\s+", " ", ln)
        toks = ln.split()
        if (len(toks) >= 2 or len(ln) >= 7) and len(ln) <= 40 and toks and not all(t in brand_words for t in toks):
            ref_lines.append(ln)
    material_ = _material(kit_, entity_key)
    best_i, best_n = -1, 10 ** 6
    last_turn = ""
    for n in range(ROUNDS + 1):
        say(f"round {n}: " + ("writing the email" if n == 0 else "editing to the findings"))
        made = compose(brief_, kit_, cast_, message, tenant=tenant, fitted=fitted, html=raw, findings=findings_prev,
                       png=prev_png, story_=story_)
        calls += 1
        if not made.get("ok"):
            story.append(f"Round {n}: {made.get('why')}.")
            break
        raw = made["html"]                                   # the model's HTML, edited next round
        # SAY WHAT WAS TURNED. The turn is the honest answer to a reference
        # about a product this brand does not sell, and it used to happen in
        # a comment nobody read — so the run log showed the reference's own
        # subject and nothing about the swap. Recorded once, and again only
        # if a later round turns it differently.
        _turn = turned(raw)
        if _turn and _turn != last_turn:
            story.append(f"Round {n}: the concept was turned to what this brand has — {_turn}")
            last_turn = _turn
        html, baked = bake(raw, tenant)
        bake_findings = [{"code": "baked_" + n.split(":", 1)[0], "severity": "blocks", "where": "a baked block",
                          "what": n.split(":", 1)[1].strip()} for n in baked if n.startswith(("clipped:", "unreadable:"))]                      # what is checked, shot, judged and sent
        for b_ in baked:
            if not b_.startswith("baked:"):
                story.append(b_ + ".")
        copy_.update(subject=made.get("subject") or copy_.get("subject", ""),
                     preheader=made.get("preheader") or copy_.get("preheader", ""))
        checks = check(html, kit_, brief_, copy_, links=True, reference_host=ref_host)
        told = truth(_Walk_words(html), material_, tenant=tenant)
        calls += told.get("calls", 0)
        shot = shots.shoot(_inline_media(html), read=True)
        checks = checks + told["findings"] + bake_findings + system_check(html, seen=shot) + story_check(html, story_, kit_)
        if "texts" in shot:
            # MEASURED ON THE RENDER where it could be read, in place of what
            # the inline styles could say about contrast — they miss classes,
            # photographs and rgb(), which is where a new design puts colour.
            checks = ([f for f in checks if f["code"] not in ("contrast", "contrast_unresolved")]
                      + render_check(shot, kit_, cast_))
            shot.pop("ground", None)
        elif shot.get("read_why"):
            story.append(shot["read_why"] + " — contrast was read off the inline styles.")
        png_id = ""
        if shot.get("ok"):
            put = media.put(tenant, shot["png"], mime="image/png", origin="generated")
            png_id = put.get("id", "") if put.get("ok") else ""
        judged = (judge(ref_png, shot["png"], brief_, tenant=tenant, material=material_,
                        notes=kit_.get("_notes") or "", turned_=turned(raw)) if shot.get("ok")
                  else {"ok": False, "findings": [], "verdict": {}, "why": shot.get("why") or "no picture", "calls": 0})
        # THE JUDGE IS NOT A LEAK: a finding that carries the reference's own
        # words ("add CRUNCHYYY!!!", "a wire basket like the reference's") would
        # be implemented by the next edit — the owner's run of 2026-09-17 grew
        # a pickle brand's copy that way. Such findings are dropped and said.
        if ref_grams or ref_lines:
            kept, dropped = [], []
            for f in judged.get("findings") or []:
                text_ = f"{f.get('what', '')} {f.get('do', '')}"
                words = _grams(text_, 3)
                low = " " + re.sub(r"[^a-z0-9' ]+", " ", _norm(text_).lower()) + " "
                quoted = any(f" {ln} " in low for ln in ref_lines)
                (dropped if (words & ref_grams) or quoted else kept).append(f)
            if dropped:
                story.append(f"The judge asked for the reference's own words in {len(dropped)} finding(s) — ignored.")
                judged = {**judged, "findings": kept}
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
        if not findings_prev:
            story.append("Nothing to edit and no judgement — the round stands.")
            break
        prev_png = shot.get("png") or b""
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
                   models={"calls": calls, "door": best["shot"]["door"], "story": story_ or {}})


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


def job(tenant: str, *, mode: str = "run", structure: str = "", url: str = "",
        entity_key: str = "", seed: str = "", progress=None) -> dict:
    """THE QUEUE'S ONE DOOR INTO THIS MODULE — `app.jobs` calls a kind's target
    as `fn(tenant=..., **payload)`, and this dispatches to the three ways a
    recreation starts: a fresh one, a re-read, or a reference pasted as a link.

    It exists so the work runs in the WORKER. Every recreation used to run in
    a daemon thread inside the web service, where a full-page screenshot
    decodes to 16 MB and the judge stamps two of them per round — on a 512 MB
    instance that also serves the console, which is what restarted the
    instance under the owner on 2026-09-23.
    """
    if mode == "swipe":
        if not url:
            return {"ok": False, "why": "a reference needs its address"}
        return swipe(url, tenant, entity_key=entity_key, progress=progress)
    if not structure:
        return {"ok": False, "why": "a recreation needs a design to recreate"}
    if mode == "again":
        return again(structure, tenant, entity_key=entity_key, progress=progress)
    return run(structure, tenant, entity_key,
               seed=seed or f"{structure}:{tenant}:{db.utcnow().isoformat(timespec='minutes')}",
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
                "has_html": bool(r.html), "verdict": verdict, "via": (r.models or {}).get("via", ""),
                "story": (r.models or {}).get("story") or {}}


def html_of(recreation_id: str) -> str:
    with db.SessionLocal() as s:
        r = s.get(db.Recreation, recreation_id)
        return (r.html or "") if r else ""
