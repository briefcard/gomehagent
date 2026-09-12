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
              "shows": what the picture must show for the device to work — the product in
              use, hands, food on it, the pack in a scene, a person — in the brand's terms},
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
    from . import email_design as ed
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


def copy_jobs(brief_: dict) -> list[dict]:
    """Every copy job in the brief, flat, in order, each with its section."""
    out = []
    for sec in brief_.get("sections") or []:
        for job in sec.get("copy") or []:
            if isinstance(job, dict) and job.get("id"):
                out.append({**job, "section": sec.get("n")})
    return out


# ---------------------------------------------------------------------------
# 2. THE KIT — the brand's material, gathered once
# ---------------------------------------------------------------------------

def kit(tenant: str) -> dict:
    """Everything the brand has that an email may be made of. Every item is
    already on file and already approved — this gathers, it invents nothing."""
    from . import brand_theme, email_design as ed, email_render as er, esp, kb
    b = kb.brand(tenant)
    theme = er._theme(brand_theme.live_theme(tenant) or {})
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

The brief's picture slots:
%(slots)s

For each slot pick the ONE picture that does that slot's job — what it must SHOW matters
more than its colours — and say why in a line. Prefer a picture not used lately
(%(recent)s), and among equals prefer the ones about %(subject)s. If no picture on the
sheet can do a slot's job, do not force one: list it under "none" with what would be needed.
Never pick the same picture for two slots.

Return JSON only: {"picks": [{"section": n, "cell": k, "why": "..."}],
                   "none": [{"section": n, "needs": "a photograph of ..."}]}"""


def _sheet(cells: list[bytes]) -> bytes:
    """A numbered contact sheet, 6 across, cells 250 px, PNG — under the
    reviewer's tier so nothing is downscaled."""
    import io
    from PIL import Image, ImageDraw, ImageFont
    cols, cell, pad = 6, 250, 10
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
    from . import email_design as ed
    slots = [sec for sec in brief_.get("sections") or []
             if str(((sec.get("asset") or {}).get("kind") or "none")).lower() in ("photograph", "illustration")]
    marks = [sec.get("n") for sec in brief_.get("sections") or []
             if str(((sec.get("asset") or {}).get("kind") or "")).lower() == "mark"]
    out = {"ok": True, "picks": {}, "none": [], "marks": marks, "said": [], "calls": 0}
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
# 3b. THE REWORK — a section the brand has no material for takes another job
# ---------------------------------------------------------------------------

_PROOF = re.compile(r"\b(quote|quotes|testimonial|testimonials|review|reviews|social proof|customer says|what people say|rating|ratings|stars)\b", re.I)


def rework(brief_: dict, kit_: dict) -> tuple[dict, list[str]]:
    """The brief with its SOCIAL-PROOF sections reworked when the brand has
    no proof on file — the same block, the same place, a different job.
    Owner, 2026-09-12: *"The social proof quote can be reworked into a
    different kind of content when social proof is missing — potentially
    educational content in the same block that doesn't pretend to be a
    review anymore."* A proof section with claims on file is left alone;
    the copy carries the claims verbatim. Returns the reworked brief and a
    sentence per section reworked."""
    has_proof = bool(kit_.get("claims"))
    if has_proof:
        return brief_, []
    out = json.loads(json.dumps(brief_))
    said: list[str] = []
    for sec in out.get("sections") or []:
        text = " ".join([str(sec.get("what") or ""), str(sec.get("does") or "")]
                        + [str(j.get("job") or "") for j in (sec.get("copy") or []) if isinstance(j, dict)])
        if not _PROOF.search(text):
            continue
        n = sec.get("n")
        sec["reworked_from"] = str(sec.get("what") or "")
        sec["what"] = ("the same block, set the same way, carrying a short piece of USEFUL content "
                       "instead of quotes: a tip, a how-to, or a fact the brand can stand behind — "
                       "no attribution, no quotation marks, nothing presented as what a customer said")
        sec["does"] = "gives the reader something worth knowing, where the reference gave proof"
        for j in sec.get("copy") or []:
            if isinstance(j, dict):
                j["job"] = ("a short useful note for this block — a tip or a fact from the brand's own "
                            "material; NOT a quote, not attributed to anyone, no quotation marks"
                            + (f" (was: {j.get('job')})" if j.get("job") else ""))
        said.append(f"section {n} reworked: the reference's social proof becomes useful content — "
                    "no claim or review is on file to quote")
    return out, said


# ---------------------------------------------------------------------------
# 4. THE COPY — written to the brief's jobs, in the brand's own terms
# ---------------------------------------------------------------------------

_COPY_PROMPT = """You write email copy for %(name)s. %(positioning)s

The email recreates a reference design. Its concept: %(concept)s
The subject of this email: %(subject)s
%(message)s
Write the copy for each job below. Every job's words must fit its job exactly — a hook that
turns on how the product is used, steps that name the real pieces, a closer that lands —
and every product, collection, place or fact named must be one of the brand's own listed
here. Nothing invented: no prices, figures, quotes or claims that are not listed.
%(rules)s
The brand's material:
%(material)s

The pictures the email will carry (write to what is in them):
%(pictures)s

Jobs:
%(jobs)s

Return JSON only: an object keyed by job id. A job whose limit says lines or steps is an
array of strings; every other job is one string. No markdown, no quotation marks around
the whole, no emoji."""


def copy(tenant: str, brief_: dict, kit_: dict, cast_: dict, *, entity_key: str = "",
         message: dict | None = None) -> dict:
    """`{ok, copy: {id: str|list}, findings: [...], calls}` — the words per
    job, gated by the brand's ban list (`validator._banned`).

    With a campaign `message` — the drafter's subject, angle, offer, the
    blocks it wrote and the claims it cited — every job is written to CARRY
    that message: the design is the reference's, the message is this send's
    (the campaign seam, INITIATIVE-email-recreation.md Phase 3)."""
    from . import validator
    jobs = copy_jobs(brief_)
    if not jobs:
        return {"ok": True, "copy": {}, "findings": [], "calls": 0}
    ents = kit_.get("entities") or []
    subj = next((e for e in ents if e["key"] == entity_key), None) or (ents[0] if ents else None)
    material = "\n".join(f'- {e["name"]}' + (f' ({e["type"]})' if e.get("type") else "")
                         + (f' — {e["description"][:160]}' if e.get("description") else "")
                         + (f' — {e["url"]}' if e.get("url") else "") for e in ents[:30])
    if kit_.get("claims"):
        material += "\nApproved claims:\n" + "\n".join(f'- {c["claim"]}' for c in kit_["claims"][:12])
    pictures = "\n".join(f'section {n}: {p.get("title")}' + (f' (about {p["entity_key"]})' if p.get("entity_key") else "")
                         for n, p in (cast_.get("picks") or {}).items()) or "none"
    rules = ""
    never = (kit_.get("voice") or {}).get("never_say") or []
    if never:
        rules += "Never say: " + ", ".join(map(str, never[:20])) + ".\n"
    if (kit_.get("rules") or {}).get("channel"):
        rules += "The brand's email instructions: " + kit_["rules"]["channel"][:800] + "\n"
    job_text = "\n".join(f'- id "{j["id"]}" (section {j.get("section")}): {j.get("job")}'
                         + (f' — limit: {j["limit"]}' if j.get("limit") else "") for j in jobs)
    msg = ""
    if message:
        lines = [f"- {k}: {v}" for k, v in (("subject line", message.get("subject")),
                                              ("preheader", message.get("preheader")),
                                              ("angle", message.get("angle")),
                                              ("offer", message.get("offer"))) if v]
        if message.get("text"):
            lines.append("- what the drafter wrote, to carry (its facts and its ask, not its shape):\n"
                         + str(message["text"])[:2200])
        if message.get("claims"):
            lines.append("- claims it cites — use them VERBATIM or not at all:\n"
                         + "\n".join(f"  · {c}" for c in message["claims"][:8]))
        msg = ("THE MESSAGE THIS EMAIL CARRIES — every job below must carry it; add no fact, "
               "product or claim that is not in it or in the brand's material:\n" + "\n".join(lines) + "\n")
    prompt = _COPY_PROMPT % {
        "name": kit_.get("name"), "positioning": kit_.get("positioning") or "", "concept": brief_.get("concept"),
        "subject": (f'{subj["name"]} — {subj.get("description", "")[:300]}' if subj else "the brand"),
        "message": msg,
        "rules": rules, "material": material or "(nothing on file)", "pictures": pictures, "jobs": job_text}
    reply = _ask("email_copy", prompt, tenant=tenant, max_tokens=2500)
    got = _json(reply.text) if getattr(reply, "ok", False) else None
    if not isinstance(got, dict):
        return {"ok": False, "copy": {}, "findings": [], "calls": 1,
                "why": "the drafter did not answer — " + str(getattr(reply, "error", "") or "no JSON")}
    out = {}
    for j in jobs:
        v = got.get(j["id"])
        if isinstance(v, list):
            v = [str(x).strip() for x in v if str(x).strip()]
        elif v is not None:
            v = str(v).strip()
        if v:
            out[j["id"]] = v
    findings = []
    flat = " ".join(" ".join(v) if isinstance(v, list) else v for v in out.values())
    for hit in validator._banned(tenant, flat) or []:
        findings.append({"code": "banned", "severity": "blocks", "where": "copy",
                         "what": f"the brand's ban list: {hit.get('phrase') or hit}"})
    missing = [j["id"] for j in jobs if j["id"] not in out]
    if missing:
        findings.append({"code": "copy_missing", "severity": "blocks", "where": "copy",
                         "what": "no words for " + ", ".join(missing)})
    return {"ok": True, "copy": out, "findings": findings, "calls": 1}


# ---------------------------------------------------------------------------
# 5. THE COMPOSITION — the model writes the email
# ---------------------------------------------------------------------------

_COMPOSE_RULES = """HTML rules (an email, not a web page):
- Table layout, every style inline, one centred column %(column)d px wide (a `width="%(column)d"`
  table with `max-width:%(column)dpx`), a full-width outer table painting the page ground.
- Only these image URLs may appear, verbatim: %(images)s. Every <img> has alt text and an
  explicit width. No <svg>, <script>, <form>, <video>, <iframe>, no background-image.
- Web fonts: a <link> to Google Fonts is allowed; every font-family names a fallback stack
  (Impact/'Arial Black' for a heavy display face, 'Brush Script MT'/cursive for a script,
  Helvetica/Arial for the rest). The brand's own body face: %(body_face)s.
- Every text colour must read on its ground at 4.5:1 or better. Use only hex colours.
- The footer carries, verbatim: "%(address)s", the token {{UNSUBSCRIBE}}%(webview)s.
  Use no other {{token}}.
- The copy below is used VERBATIM — every job's words, unchanged, no words added of your
  own except the brand's name, product names as listed, and the footer's fixed lines.
- Under %(size)d KB in total. Return the complete HTML document only, no commentary."""

_COMPOSE_PROMPT = """You are recreating a reference email's DESIGN for the brand %(name)s, with the brand's own
material. You never saw the reference's pixels; you have the designer's brief of it. Recreate
the design faithfully — its concept, every section in order, its devices, its type roles,
its colour logic and rhythm — and fill it with THIS brand: the pictures cast below, the
copy written below, the brand's mark and faces. A device the brief describes (a social post
shown as a post, a script closer, a bordered button) is drawn in HTML/CSS as described —
avatar, handle row, icon row and dots included, using simple shapes and characters, never
an image you were not given.

THE BRIEF
%(brief)s

THE BRAND
name: %(name)s
mark: %(logo)s (use it where the brief has the brand's mark)
handle: %(handle)s
palette measured from the cast photographs (use these as the page/card grounds and inks the
way the brief's colour logic says — the page may be a photograph's bold tone if the reference's is):
%(palette)s
brand accent: %(accent)s

THE CAST (section → picture)
%(cast)s
Slots the brief has that were CUT (no picture fits — leave the section out and keep the flow):
%(cut)s

THE COPY (by job id — verbatim)
%(copy)s

%(rules)s"""

_REVISE_PROMPT = """Below is the email you wrote and the judge's findings after comparing it to the reference.
EDIT the HTML to close each finding. Change only what a finding requires; every other line
stays exactly as it is. The copy stays verbatim. The same HTML rules apply. Return the
complete HTML document only.

FINDINGS
%(findings)s

THE HTML
%(html)s"""


def _palette_lines(cast_: dict, theme: dict) -> str:
    lines = []
    for n, p in (cast_.get("picks") or {}).items():
        c = p.get("colours") or {}
        if c:
            lines.append(f'section {n} ({p.get("title")}): ' + ", ".join(
                f"{k} {v}" for k, v in c.items() if isinstance(v, str)))
    pal = theme.get("palette") or {}
    if pal:
        lines.append("brand roles: " + ", ".join(f"{k} {v}" for k, v in pal.items() if isinstance(v, str))[:400])
    return "\n".join(lines) or "(no colours measured)"


def compose(brief_: dict, kit_: dict, cast_: dict, copy_: dict, *, tenant: str = "",
            html: str = "", findings=()) -> dict:
    """`{ok, html, why, edited}` — the model writes the email; with `html`
    and `findings` it EDITS that email to close the findings."""
    theme = kit_.get("theme") or {}
    images = [theme.get("logo_url")] if theme.get("logo_url") else []
    images += [p["url"] for p in (cast_.get("picks") or {}).values()]
    rules = _COMPOSE_RULES % {
        "column": COLUMN, "images": ", ".join(images) or "(none)",
        "body_face": (theme.get("font") or {}).get("body") or "Helvetica, Arial, sans-serif",
        "address": (theme.get("footer") or {}).get("address") or "", "size": HTML_MAX // 1000,
        "webview": " and the token {{VIEW_IN_BROWSER}} as the view-in-browser link"
                   if (kit_.get("esp") or {}).get("webview", True) else
                   " — and NO view-in-browser link: this brand's platform has no variable for one"}
    if html and findings:
        prompt = _REVISE_PROMPT % {
            "findings": "\n".join(f'- [{f.get("severity", "")}] {f.get("where", "")}: {f.get("what", "")}'
                                  + (f' → {f["do"]}' if f.get("do") else "") for f in findings),
            "html": html} + "\n\n" + rules
    else:
        brief_text = json.dumps({k: brief_.get(k) for k in ("concept", "sections", "visual_system", "devices")},
                                ensure_ascii=False, indent=1)
        cast_text = "\n".join(f'section {n}: {p["url"]} — {p.get("title")}' + (f' ({p["why"]})' if p.get("why") else "")
                              for n, p in (cast_.get("picks") or {}).items()) or "(none)"
        for n in cast_.get("marks") or []:
            cast_text += f"\nsection {n}: the brand's mark"
        cut = "\n".join(f'section {x["section"]}: needs {x["needs"]}' for x in cast_.get("none") or []) or "(none)"
        prompt = _COMPOSE_PROMPT % {
            "name": kit_.get("name"), "brief": brief_text, "logo": theme.get("logo_url") or "(no mark on file — set the name in type)",
            "handle": (kit_.get("handles") or {}).get("instagram") or "(none on file)",
            "palette": _palette_lines(cast_, theme), "accent": (theme.get("colors") or {}).get("accent") or "",
            "cast": cast_text, "cut": cut,
            "copy": json.dumps(copy_, ensure_ascii=False, indent=1), "rules": rules}
    reply = _ask("email_compose", prompt, tenant=tenant, max_tokens=12000)
    if not getattr(reply, "ok", False):
        return {"ok": False, "html": "", "why": "the composer did not answer — " + str(getattr(reply, "error", "")), "edited": 0}
    text = str(reply.text or "")
    m = re.search(r"```(?:html)?\s*(.*?)```", text, re.S)
    out = (m.group(1) if m else text).strip()
    if "<html" not in out.lower() and "<table" not in out.lower():
        return {"ok": False, "html": "", "why": "the composer did not return HTML", "edited": 0}
    edited = 0
    if html:
        import difflib
        edited = sum(1 for d in difflib.unified_diff(html.splitlines(), out.splitlines(), lineterm="", n=0)
                     if d.startswith(("+", "-")) and not d.startswith(("+++", "---")))
    return {"ok": True, "html": out, "why": "", "edited": edited}


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
    text = " ".join(w.text)
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
    # 3. copy verbatim
    norm_text = _norm(text)
    for jid, v in (copy_ or {}).items():
        parts = v if isinstance(v, list) else [v]
        for part in parts:
            if _norm(part) and _norm(part) not in norm_text:
                add("copy", "blocks", jid, f"the drafter's words changed or missing: {_norm(part)[:60]!r}")
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


def judge(reference_png: bytes, ours_png: bytes, brief_: dict, *, tenant: str = "") -> dict:
    """`{ok, findings, verdict, why, calls}`."""
    from . import email_design as ed
    if not reference_png or not ours_png:
        return {"ok": False, "findings": [], "verdict": {}, "why": "no picture to judge", "calls": 0}
    _, edge = ed._tier_edge()
    blocks = []
    try:
        for png in (reference_png, ours_png):
            blocks.append(ed._image_block(ed.contact_sheet(png, edge)))
            blocks.append(ed._image_block(ed.strips(png, edge)[0]["png"]))
    except Exception as e:                                        # noqa: BLE001
        return {"ok": False, "findings": [], "verdict": {}, "why": f"a picture could not be cut: {e}", "calls": 0}
    blocks.append({"type": "text", "text": _JUDGE_PROMPT % {
        "concept": brief_.get("concept"), "devices": "; ".join(map(str, brief_.get("devices") or []))[:1500]}})
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
    from . import email_design as ed
    with db.SessionLocal() as s:
        st = s.get(db.EmailStructure, structure_id)
        aid = st.source_asset_id if st else ""
        a = s.get(db.KbAsset, aid) if aid else None
        url = str(getattr(a, "url", "") or "") if a else ""
    return (ed._fetch(url) if url else b""), urlparse(url).netloc


def run(structure_id: str, tenant: str, entity_key: str = "", *, recent_media=(),
        seed: str = "", progress=None, message: dict | None = None, via: str = "press") -> dict:
    """One recreation of `structure_id` for `tenant`, stored as a `Recreation`
    row and returned as `{ok, id, status, note, findings, rounds, html, text,
    media_ids, blocking}`. With a campaign `message` the copy carries it and
    `via` says so on the row."""
    from . import media, shots
    say = progress or (lambda *_: None)
    story: list[str] = []
    with db.SessionLocal() as s:
        st = s.get(db.EmailStructure, structure_id)
        if not st:
            return {"ok": False, "why": "no structure at that id", "status": FAILED}
        brief_ = dict(st.brief or {})
        aid = st.source_asset_id or ""
        name = st.name or structure_id
        row = db.Recreation(tenant=tenant, structure_id=structure_id, entity_key=entity_key, status=RUNNING,
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
        text = "\n".join(" ".join(v) if isinstance(v, list) else str(v) for v in cp.values())
        return {"ok": status not in (FAILED,), "id": rid, "status": status, "note": " ".join(story),
                "findings": fields.get("findings", []), "rounds": fields.get("rounds", []), "calls": calls,
                "html": fields.get("html", ""), "text": text,
                "media_ids": [p.get("asset_id") for p in ((fields.get("cast") or {}).get("picks") or {}).values()
                              if p.get("asset_id")],
                "blocking": len(blocking(fields.get("findings", [])))}

    # the brief
    if not brief_:
        say("reading the reference into a brief")
        got = brief(aid, tenant=tenant) if aid else {"ok": False, "why": "the structure has no reference picture"}
        calls += got.get("calls", 0)
        if not got.get("ok"):
            story.append(f"The reference could not be read: {got.get('why')}.")
            return _finish(FAILED)
        brief_ = got["brief"]
        story.append(f"Read {name} into a brief: {brief_.get('concept')}")
    else:
        story.append(f"Brief on file: {brief_.get('concept')}")
    # the kit and the cast
    say("gathering the brand's material and casting its pictures")
    kit_ = kit(tenant)
    brief_, reworked = rework(brief_, kit_)
    story.extend(reworked)
    cast_ = cast(tenant, brief_, kit_, entity_key=entity_key, recent_media=recent_media, seed=seed)
    calls += cast_.get("calls", 0)
    story.extend(cast_.get("said") or [])
    photo_slots = [sec for sec in brief_.get("sections") or []
                   if str(((sec.get("asset") or {}).get("kind") or "")).lower() in ("photograph", "illustration")]
    if photo_slots and not cast_.get("picks"):
        story.append("Every photograph slot is cut, so the email cannot be made for this brand yet — "
                     + "; ".join(f"section {x['section']} needs {x['needs']}" for x in cast_.get("none") or []))
        return _finish(CANNOT, brief=brief_, cast=cast_,
                       findings=[{"code": "needs", "severity": "blocks", "where": f"section {x['section']}",
                                  "what": f"needs {x['needs']}"} for x in cast_.get("none") or []])
    # the copy
    say("writing the copy to the brief's jobs")
    cp = copy(tenant, brief_, kit_, cast_, entity_key=entity_key, message=message)
    calls += cp.get("calls", 0)
    if not cp.get("ok"):
        story.append(cp.get("why", "the copy did not land") + ".")
        return _finish(FAILED, brief=brief_, cast=cast_)
    copy_ = cp["copy"]
    copy_findings = cp.get("findings") or []
    # the rounds
    ref_png, ref_host = _reference_png(structure_id)
    if not ref_png:
        story.append("The reference picture could not be fetched, so the judge is skipped.")
    rounds: list[dict] = []
    html, findings_prev = "", []
    best_i, best_n = -1, 10 ** 6
    for n in range(ROUNDS + 1):
        say(f"round {n}: " + ("writing the email" if n == 0 else "editing to the findings"))
        made = compose(brief_, kit_, cast_, copy_, tenant=tenant, html=html, findings=findings_prev)
        calls += 1
        if not made.get("ok"):
            story.append(f"Round {n}: {made.get('why')}.")
            break
        html = made["html"]
        checks = check(html, kit_, brief_, copy_, links=True, reference_host=ref_host) + copy_findings
        shot = shots.shoot(html)
        png_id = ""
        if shot.get("ok"):
            put = media.put(tenant, shot["png"], mime="image/png", origin="generated")
            png_id = put.get("id", "") if put.get("ok") else ""
        judged = (judge(ref_png, shot["png"], brief_, tenant=tenant) if shot.get("ok") and ref_png
                  else {"ok": False, "findings": [], "verdict": {}, "why": shot.get("why") or "no reference", "calls": 0})
        calls += judged.get("calls", 0)
        open_ = blocking(checks) + blocking(judged.get("findings"))
        rounds.append({"n": n, "png_id": png_id, "check": checks, "judge": judged.get("findings", []),
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
