"""The collective library of email structures, and the swipe board that feeds it.

Owner, 2026-09-11, on Really Good Emails: mimic many styles — *"and you will
need to make sure that brand rules are respected given the structure / layout
/ references you generate based on the emails. Anytime we build out new email
structures, we should save any approved structure to our collective library of
email structures so we can reuse them in the future for different copy /
campaigns."*

**A STRUCTURE IS HOW AN EMAIL IS BUILT, NEVER WHAT IT SAYS.** The rule the
visual boards already run on — a reference pin contributes words, never pixels
— applied to email: a swiped email contributes a structural reading in words
(where the hero sits, how many asks and where, how dense, what kind of proof)
and never its markup or its copy. Every email in that gallery is some brand's
copyrighted creative; what is legitimate is the pattern, applied with our own
words and pictures.

**BRAND RULES ARE RESPECTED AT THE MOMENT OF USE, in two places, and both are
named here because a rule that reaches no validator does not exist.**

  1. SELECTION — `usable_for(tenant, structure)`. A structure is refused for a
     brand when its own notes trip that brand's ban list (a structure
     described around "hand-crafted" never reaches Baci's drafter), when it
     REQUIRES something the brand cannot supply (products it has none of,
     proof it holds no approved claim for), or when its notes identify another
     account (`craft.leaks`). The generator that receives a structure is the
     campaign drafter, through `craft["structure"]` and `_craft_brief`.
  2. OUTPUT — the drafted email goes through every gate it went through
     before: the ban list, the citation check, the coherence commitment.
     A structure cannot put a word on the page; it can only say where a block
     goes. So nothing it does can bypass a validator, because it never touches
     what the validators read.

**TWO WAYS IN.** A swipe arrives PROPOSED and waits for a person: a reading is
a generator's opinion, and generators propose. A run — one of our own emails
the owner approved — arrives APPROVED, because that approval was the decision,
and it is filed once per distinct block sequence so the library grows by
shapes rather than by sends.
"""
from __future__ import annotations

import datetime as dt
import json
import re

import httpx

from . import config, db

#: The vocabulary a structure may use — the renderer's own, READ from it so a
#: structure can never name a block that cannot be built.
def block_types() -> tuple:
    from . import email_render
    return tuple(email_render._BLOCKS)


#: What a block asks the brand to have. A sequence that includes one of these
#: is only usable by a brand that can supply it.
_REQUIRES = {"products": "products", "quote": "proof", "stat": "proof",
             "hero": "hero"}

INTENTS = ("story", "education", "proof", "offer")
FORMATS = ("letter", "designed")

#: Where swipes are filed: the agency's own account, on one named board. The
#: asset machinery gives them rights=reference for free, which is the property
#: that matters — a swipe can never be selected as a picture for anything.
SWIPE_TENANT = "agency"
#: NOT ON A VISUAL BOARD, deliberately. The boards feed the picture ladder
#: and `creative.drawable`: a "look" pin is a style the brand's pictures are
#: drawn in. A screenshot of somebody's email is not that, and pinning it
#: would make the agency account "drawable" from email layouts. Swipes are
#: their own kind (`email_swipe`), which every picture read ignores, and they
#: are SEEN beside the structure each one produced — the reference next to
#: what was read off it.
SWIPE_KIND = "email_swipe"
SWIPE_HOST = "reallygoodemails.com"

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


# ---------------------------------------------------------------------------
# Reading a structure off real blocks
# ---------------------------------------------------------------------------
def signature(sequence) -> str:
    """The identity of a structure: its block types, in order."""
    return " > ".join(str(t).strip().lower() for t in (sequence or []) if str(t).strip())


def profile_of(blocks: list) -> dict:
    """What a block list is doing, as facts a drafter can be briefed with."""
    types = [str(b.get("type", "")).lower() for b in (blocks or []) if isinstance(b, dict)]
    n = len(types)
    ctas = [i for i, t in enumerate(types) if t in ("cta", "button")]
    return {
        "blocks": n,
        "hero": "hero" in types,
        "hero_first": bool(types) and types[0] == "hero",
        "asks": len(ctas),
        "first_ask_at": (ctas[0] + 1) if ctas else None,
        "products": types.count("products"),
        "proof": sum(types.count(t) for t in ("quote", "stat")),
        "list": "list" in types,
        "banner": "banner" in types,
        "ps": "ps" in types,
        "density": ("short" if n <= 5 else "medium" if n <= 8 else "long"),
    }


def look_of(raw: dict | None) -> dict:
    """The arrangement a swipe was read to have, kept to the renderer's own
    vocabulary (`email_render.LOOK`): a key the renderer does not draw is
    dropped, a value it does not know is dropped, and what is left is what
    the structure will actually reproduce. Colours and typefaces are not in
    the vocabulary, so a reading cannot carry them even if the model
    volunteered them — the brand's theme is the only source of those."""
    from . import email_render
    out = {}
    for k, vals in email_render.LOOK.items():
        v = (raw or {}).get(k)
        if k == "bands":
            if isinstance(v, bool):
                out[k] = v
        elif isinstance(v, str) and v.strip().lower() in vals:
            out[k] = v.strip().lower()
    return out


def requires_of(sequence) -> list:
    """What a brand needs to have before this structure can be used."""
    out = []
    for t in (sequence or []):
        need = _REQUIRES.get(str(t).lower())
        if need and need not in out:
            out.append(need)
    return out


# ---------------------------------------------------------------------------
# The library
# ---------------------------------------------------------------------------
def find_by_sequence(sequence) -> db.EmailStructure | None:
    sig = signature(sequence)
    if not sig:
        return None
    with db.SessionLocal() as s:
        for row in s.query(db.EmailStructure).all():
            if signature(row.sequence) == sig:
                s.expunge(row)
                return row
    return None


def file_structure(*, name: str, sequence: list, source: str, review: str,
                   profile: dict | None = None, fits_intents=(), fits_formats=(),
                   source_url: str = "", source_asset_id: str = "",
                   notes: str = "", by: str = "", look: dict | None = None) -> dict:
    """Put one structure in the library, once per distinct sequence.

    `look` is the arrangement (hero treatment, type scale, density, bands,
    button style, product layout) — filtered through `look_of` so only what
    the renderer can draw is kept. It lives in `profile["look"]`, beside the
    facts about the sequence, and rides to the renderer at use.

    `notes` are checked with `craft.leaks` BEFORE filing: a structure that
    names a brand, a URL or a person is one that would carry another account's
    fact into every email built on it, and the library is shared.
    """
    from . import craft
    seq = [str(t).strip().lower() for t in (sequence or []) if str(t).strip()]
    unknown = [t for t in seq if t not in block_types()]
    if unknown:
        return {"ok": False, "why": f"unknown block type(s) {unknown} — a "
                                    f"structure may only use blocks the "
                                    f"renderer can build"}
    if len(seq) < 2:
        return {"ok": False, "why": "a structure is at least two blocks"}
    if notes and (found := craft.leaks(notes)):
        return {"ok": False, "why": ("these notes identify an account ("
                                     + ", ".join(found) + ") — a shared "
                                     "structure carries technique, never a "
                                     "fact about anyone")}
    have = find_by_sequence(seq)
    if have is not None:
        # A structure filed before the look was read (or read again after
        # the renderer learned a new axis) takes the arrangement now; its
        # sequence, name and review are untouched, so a re-read never undoes
        # an approval.
        if lk := look_of(look):
            with db.SessionLocal() as s:
                row = s.get(db.EmailStructure, have.id)
                prof = dict(row.profile or {})
                if prof.get("look") != lk:
                    prof["look"] = lk
                    row.profile = prof
                    s.commit()
        return {"ok": True, "id": have.id, "existing": True,
                "name": have.name, "review": have.review}
    prof = dict(profile or profile_of([{"type": t} for t in seq]))
    if notes:
        prof["notes"] = notes[:600]
    if lk := look_of(look):
        prof["look"] = lk
    with db.SessionLocal() as s:
        row = db.EmailStructure(
            name=(name or signature(seq))[:120], source=source,
            source_url=source_url[:500], source_asset_id=source_asset_id,
            sequence=seq, profile=prof,
            fits_intents=[i for i in fits_intents if i in INTENTS],
            fits_formats=[f for f in fits_formats if f in FORMATS] or ["designed"],
            requires=requires_of(seq), review=review,
            reviewed_by=by if review == "approved" else "",
            reviewed_at=db.utcnow() if review == "approved" else None)
        s.add(row)
        s.commit()
        return {"ok": True, "id": row.id, "existing": False, "name": row.name,
                "review": row.review}


def file_from_output(output_id: str, *, by: str = "owner") -> dict:
    """An email of ours that was APPROVED joins the library as a structure.

    The owner's rule. Filed from `Output.shape`, which is the block sequence
    the email was built from, and only once per distinct sequence — the
    library grows by shapes, not by sends. Approved on arrival, because the
    approval was the decision.
    """
    with db.SessionLocal() as s:
        out = s.get(db.Output, output_id)
        if out is None:
            return {"ok": False, "why": "no such output"}
        seq = list(out.shape or [])
        angle = str(out.angle or "")
        theme = str(out.theme or "")
        tenant = str(out.tenant or "")
    if len(seq) < 2:
        return {"ok": False, "why": "this output recorded no block sequence"}
    # NAMED BY WHAT IT DOES, never by whose it was. The library is shared, so
    # "Baci's September offer" would carry an account into every account.
    prof = profile_of([{"type": t} for t in seq])
    label = (f"{'hero-led ' if prof['hero_first'] else ''}"
             f"{prof['density']} {angle or 'email'}, "
             f"{prof['asks']} ask{'s' if prof['asks'] != 1 else ''}"
             + (f", {prof['products']} product block"
                f"{'s' if prof['products'] != 1 else ''}" if prof["products"] else "")
             + (", with proof" if prof["proof"] else ""))
    got = file_structure(name=label, sequence=seq, source="run",
                         review="approved", fits_intents=[angle] if angle in INTENTS else [],
                         fits_formats=[theme] if theme in FORMATS else [], by=by)
    got["from_tenant_note"] = ("filed from an approved send; the account is "
                               "not recorded on the structure") if tenant else ""
    return got


def approve(structure_id: str, *, by: str = "owner") -> str:
    return _review(structure_id, "approved", by)


def reject(structure_id: str, *, by: str = "owner") -> str:
    return _review(structure_id, "rejected", by)


def _review(structure_id: str, verdict: str, by: str) -> str:
    with db.SessionLocal() as s:
        row = s.get(db.EmailStructure, structure_id)
        if row is None:
            return "no such structure"
        row.review, row.reviewed_by, row.reviewed_at = verdict, by, db.utcnow()
        s.commit()
        return f"{verdict}: {row.name}"


def library(*, review: str = "") -> list[dict]:
    with db.SessionLocal() as s:
        q = s.query(db.EmailStructure)
        if review:
            q = q.filter(db.EmailStructure.review == review)
        rows = q.order_by(db.EmailStructure.created_at.desc()).all()
        return [_row(r) for r in rows]


def _row(r) -> dict:
    return {"id": r.id, "name": r.name, "source": r.source,
            "source_url": r.source_url, "sequence": list(r.sequence or []),
            "profile": dict(r.profile or {}), "fits_intents": list(r.fits_intents or []),
            "fits_formats": list(r.fits_formats or []),
            "requires": list(r.requires or []), "review": r.review,
            "used_count": int(r.used_count or 0),
            "last_used_at": (db.as_utc(r.last_used_at).isoformat(timespec="minutes")
                             if r.last_used_at else "")}


# ---------------------------------------------------------------------------
# Brand rules, at the moment of use
# ---------------------------------------------------------------------------
def usable_for(tenant: str, structure: dict) -> tuple[bool, str]:
    """"(True, "") when this brand may build on this structure, else why not.

    THE GATE THE OWNER ASKED FOR. Three refusals, each a different rule:

    * its notes trip THIS brand's ban list — a structure read off a gallery
      email built around "handcrafted" or "cures" is refused for a brand whose
      rules forbid the word, before a drafter ever sees it;
    * it requires something the brand cannot supply — a products block needs
      entities, a proof block needs an approved claim, a hero needs a
      publishable picture or the ability to draw one;
    * its notes identify an account — refused at filing and again here, in
      case a hand-edited row got past.
    """
    from . import craft, kb, validator
    notes = " ".join(str(v) for v in [structure.get("name", "")]
                     + [structure.get("profile", {}).get("notes", "")])
    if (found := craft.leaks(notes)):
        return False, "its notes identify an account (" + ", ".join(found) + ")"
    if notes.strip():
        # THE BAN LIST ITSELF, not the whole draft validator. `validator.check`
        # refuses an account with NO ban list, because a ban list is
        # constitutive for a draft — and that is the right rule for a draft
        # and the wrong one here: a structure's notes with nothing to trip
        # against are fine, not blocked. Word-boundary matched, like every
        # other use of the list.
        hits = validator._banned(tenant, notes)
        if hits:
            bad = ", ".join(sorted({str(h.get("phrase", "")) for h in hits}))
            return False, (f"its description uses words this brand bars — "
                           f"{bad}")
    for need in structure.get("requires") or []:
        if need == "products" and not kb.entities(tenant):
            return False, "it needs product blocks and this brand has no products on file"
        if need == "proof" and not kb.claims(tenant):
            return False, "it needs proof blocks and this brand has no approved claim"
        if need == "hero" and not can_hero(tenant):
            return False, ("it leads with a picture and this brand has none to "
                           "lead with — no publishable photograph, no product "
                           "with a store image, and nothing it can draw")
    return True, ""


def can_hero(tenant: str) -> bool:
    """Whether an EMAIL for this brand can open on a picture.

    NOT the same question as `creative.can_illustrate`, and the difference
    refused a usable structure on 2026-09-11. The campaign run has a fallback
    the library count does not see: when no library photograph fits, it leads
    with the subject product's own store image — the same URL the catalogue
    sync files as owned — and says so. So a brand can send hero-led emails
    with an empty picture library, and a check that only read the library
    told the owner the Ayoh structure was "not for this brand" while that
    brand's emails were going out with a hero on them.
    """
    from . import creative, kb
    if creative.can_illustrate(tenant).get("ok"):
        return True
    # `kb.entities` returns rows; the store image lives in the typed
    # attributes bag, which is where the catalogue sync files it and where the
    # run reads it from (`ents` is built from that bag).
    return any(((getattr(e, "attributes", None) or {}).get("image") or "").strip()
               for e in kb.entities(tenant))


def eligible(tenant: str, *, intent: str = "", fmt: str = "",
             recent_shapes: list | None = None) -> list[dict]:
    """Every structure this send COULD be built on: approved, usable for this
    brand, fitting the send's intent and form where it declares any, and not
    one of the last shapes this list received."""
    recent = {signature(s) for s in (recent_shapes or []) if s}
    out = []
    for st in library(review="approved"):
        if intent and st["fits_intents"] and intent not in st["fits_intents"]:
            continue
        if fmt and st["fits_formats"] and fmt not in st["fits_formats"]:
            continue
        if signature(st["sequence"]) in recent:
            continue
        ok, _why = usable_for(tenant, st)
        if not ok:
            continue
        out.append(st)
    return out


def pick(tenant: str, *, intent: str = "", fmt: str = "",
         recent_shapes: list | None = None, designated: str = "") -> dict:
    """The structure to build this send on — RANDOM among the eligible, unless
    one is designated. Owner, 2026-09-11: *"It should be random unless
    designated specifically (optional)."*

    Random rather than least-recently-used, because rotation is a schedule
    and a schedule is a pattern a list learns to see; a draw is not. Recent
    shapes are still excluded, so the same people never get the same layout
    twice running, which is the one regularity worth keeping.

    A DESIGNATED structure is used when it may be, and REFUSED WITH THE REASON
    when it may not — never silently swapped. The brand's rules do not bend
    for a request, and the person who asked deserves to know why. Returns
    `{structure, why, designated}`; `structure` None means design fresh.
    """
    import random
    if designated:
        st = next((r for r in library() if r["id"] == designated), None)
        if st is None:
            return {"structure": None, "designated": True,
                    "why": f"no structure with id {designated!r} — designed fresh"}
        if st["review"] != "approved":
            return {"structure": None, "designated": True,
                    "why": (f"{st['name']!r} is {st['review']}, not approved — "
                            f"approve it on the Brand tab first; designed fresh")}
        ok, why = usable_for(tenant, st)
        if not ok:
            return {"structure": None, "designated": True,
                    "why": f"{st['name']!r} is not for this brand — {why}; designed fresh"}
        return {"structure": st, "designated": True,
                "why": f"designated: {st['name']}"}
    pool = eligible(tenant, intent=intent, fmt=fmt, recent_shapes=recent_shapes)
    if not pool:
        return {"structure": None, "designated": False,
                "why": "nothing in the library fits this send — designed fresh"}
    st = random.choice(pool)
    return {"structure": st, "designated": False,
            "why": f"drawn from {len(pool)} that fit: {st['name']}"}


def mark_used(structure_id: str) -> None:
    with db.SessionLocal() as s:
        row = s.get(db.EmailStructure, structure_id)
        if row is not None:
            row.used_count = int(row.used_count or 0) + 1
            row.last_used_at = db.utcnow()
            s.commit()


def brief(structure: dict) -> str:
    """The words the drafter gets. The ORDER, and why — never any copy."""
    prof = structure.get("profile") or {}
    seq = structure.get("sequence") or []
    lines = [f"\n## THE STRUCTURE THIS SEND IS BUILT ON: {structure.get('name', '')}",
             "Compose the blocks in THIS order, each filled with this brand's own "
             "words, claims and pictures — the structure is borrowed, nothing "
             "in it is:",
             "  " + " → ".join(seq)]
    facts = []
    if prof.get("hero_first"):
        facts.append("it opens on the picture")
    if prof.get("asks"):
        facts.append(f"{prof['asks']} ask(s), the first at block {prof.get('first_ask_at')}")
    if prof.get("proof"):
        facts.append("proof is given room before the ask")
    if prof.get("density"):
        facts.append(f"{prof['density']} — {prof.get('blocks', len(seq))} blocks")
    if facts:
        lines.append("  Shape: " + "; ".join(facts) + ".")
    if prof.get("notes"):
        lines.append("  What it does well: " + str(prof["notes"])[:400])
    if lk := prof.get("look"):
        said = ", ".join(f"{k} {str(v).lower()}" for k, v in lk.items())
        lines.append("  The renderer will arrange it as: " + said + ". Write for "
                     "that shape — a display headline is short; a grid of "
                     "products needs each name to stand on its own; a text-link "
                     "ask is one plain sentence.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The swipe board
# ---------------------------------------------------------------------------
def swipe_url(raw: str) -> tuple[str, str]:
    """`(clean_url, why_not)`. Only the gallery's own email pages, one at a
    time — the owner curates and the system reads what they chose. No
    walking the site."""
    text = (raw or "").strip()
    if not text:
        return "", "no link"
    m = re.match(r"^(?:https?://)?(?:www\.)?reallygoodemails\.com/(emails/[A-Za-z0-9\-]+)/?$",
                 text)
    if not m:
        return "", ("a swipe is one email's page on reallygoodemails.com, like "
                    "reallygoodemails.com/emails/<slug> — not a category or a "
                    "search")
    return f"https://{SWIPE_HOST}/{m.group(1)}", ""


def _page_meta(html: str) -> dict:
    """The screenshot and title the page declares for itself, from its own
    Open Graph tags — the part meant to be read by other sites."""
    def _meta(prop: str) -> str:
        m = re.search(rf'<meta[^>]+property=["\']{re.escape(prop)}["\'][^>]+content=["\']([^"\']+)["\']',
                      html, re.I) or re.search(
            rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']{re.escape(prop)}["\']',
            html, re.I)
        return (m.group(1).strip() if m else "")
    title = _meta("og:title") or ""
    if not title:
        t = re.search(r"<title>([^<]+)</title>", html, re.I)
        title = t.group(1).strip() if t else ""
    return {"image": _meta("og:image"), "title": title[:160],
            "description": _meta("og:description")[:300]}


def add_swipe(raw_url: str, *, tenant: str = SWIPE_TENANT) -> dict:
    """File one gallery email as a REFERENCE picture on the swipe board.

    Reference by construction — `kb.add_asset(rights=REFERENCE)` — so the
    screenshot can never be picked as a hero or drawn from as a product: it is
    there to be READ, once, into a structure.
    """
    from . import kb
    url, why = swipe_url(raw_url)
    if why:
        return {"ok": False, "why": why}
    try:
        r = httpx.get(url, headers={"User-Agent": _UA}, timeout=25,
                      follow_redirects=True)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "why": f"could not fetch it ({exc.__class__.__name__})"}
    if r.status_code != 200:
        return {"ok": False, "why": f"the page answered {r.status_code}"}
    meta = _page_meta(r.text)
    if not meta["image"]:
        return {"ok": False, "why": "the page declares no screenshot to read"}
    kb.add_asset(tenant, meta["image"], rights=kb.REFERENCE,
                 title=meta["title"] or url, kind=SWIPE_KIND,
                 source=url)
    with db.SessionLocal() as s:
        row = (s.query(db.KbAsset)
               .filter(db.KbAsset.tenant == tenant, db.KbAsset.url == meta["image"])
               .order_by(db.KbAsset.created_at.desc()).first())
        aid = row.id if row is not None else ""
    return {"ok": True, "asset_id": aid, "url": url, "title": meta["title"],
            "image": meta["image"]}


def swipes(tenant: str = SWIPE_TENANT) -> list[dict]:
    """Every swiped screenshot, with the structure it was read into — or the
    fact that it was not. The place to SEE the references."""
    with db.SessionLocal() as s:
        rows = (s.query(db.KbAsset)
                .filter(db.KbAsset.tenant == tenant, db.KbAsset.kind == SWIPE_KIND,
                        db.KbAsset.status == "active")
                .order_by(db.KbAsset.created_at.desc()).all())
        by_asset = {str(r.source_asset_id): r for r in
                    s.query(db.EmailStructure).all() if r.source_asset_id}
        out = []
        for a in rows:
            st = by_asset.get(a.id)
            out.append({"asset_id": a.id, "image": a.url or "", "title": a.title or "",
                        "source_url": a.source or "",
                        "structure_id": st.id if st is not None else "",
                        "structure_name": st.name if st is not None else "",
                        "review": st.review if st is not None else "unread"})
        return out


_READ = """You are looking at a screenshot of a marketing email from a public gallery.
Describe its STRUCTURE only — never its words, brand, products, prices or
offer. Answer as JSON with exactly these keys:
  "sequence": the blocks in order, using ONLY these types: {types}
  "fits_intents": which of {intents} this shape suits
  "fits_formats": which of {formats} it is ("letter" = mostly prose, "designed" = built from visual blocks)
  "notes": one or two sentences on what the structure does well — the
           arrangement, the rhythm, where the ask lands. No brand names, no
           product names, no copy, no URLs.
  "look": how it is ARRANGED, as an object with exactly these keys and only
          these values —
            "hero": "contained" (picture, then headline under it) |
                    "bleed" (picture edge to edge, no rounding) |
                    "overlay" (headline ON the picture) |
                    "split" (picture one side, headline the other)
            "scale": "modest" (headline about body size x1.5) | "display" (very large headline)
            "density": "tight" | "regular" | "airy" (how much space between sections)
            "bands": true if sections sit on alternating background bands, else false
            "cta": "block" (a button) | "full" (a full-width bar) | "pill" (rounded button) | "link" (a text link with an arrow)
            "products": "rows" (one product per row) | "grid2" (two across) | "grid3" (three across)
          Describe the arrangement only — never a colour, a typeface or a picture's content.
Nothing outside the JSON."""


def read_swipe(asset_id: str) -> dict:
    """Look at one swipe and propose the structure it uses. PROPOSED, not
    approved: a reading is a generator's opinion and generators propose."""
    import base64 as _b64
    from . import imagegen, llm
    with db.SessionLocal() as s:
        row = s.get(db.KbAsset, asset_id)
        if row is None:
            return {"ok": False, "why": "no such swipe"}
        url, title, src = row.url or "", row.title or "", (row.source or "")
        from . import kb
        if (row.rights or kb.REFERENCE) != kb.REFERENCE:
            return {"ok": False, "why": "not a reference swipe — a brand's own "
                                        "picture is not read for structure"}
    try:
        blob = httpx.get(url, headers={"User-Agent": _UA}, timeout=25,
                         follow_redirects=True).content
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "why": f"could not fetch the screenshot ({exc.__class__.__name__})"}
    if not blob:
        return {"ok": False, "why": "the screenshot was empty"}
    blocks = [{"type": "image", "source": {"type": "base64",
                                           "media_type": imagegen._mime(blob),
                                           "data": _b64.standard_b64encode(blob).decode()}},
              {"type": "text", "text": _READ.format(
                  types=", ".join(block_types()), intents=", ".join(INTENTS),
                  formats=", ".join(FORMATS))}]
    reply = llm.ask("creative_review", blocks, tenant=SWIPE_TENANT, max_tokens=600)
    if not getattr(reply, "ok", False):
        return {"ok": False, "why": getattr(reply, "error", "") or "the reading could not run"}
    text = str(getattr(reply, "text", "") or "")
    m = re.search(r"\{.*\}", text, re.S)
    try:
        data = json.loads(m.group(0)) if m else {}
    except ValueError:
        data = {}
    if not isinstance(data, dict) or not data.get("sequence"):
        return {"ok": False, "why": "the reading did not answer in the shape asked"}
    got = file_structure(
        name=(title or "swiped structure")[:120], sequence=data.get("sequence") or [],
        source="swipe", review="proposed",
        fits_intents=data.get("fits_intents") or [],
        fits_formats=data.get("fits_formats") or [],
        source_url=src or url, source_asset_id=asset_id,
        notes=str(data.get("notes") or ""),
        look=data.get("look") if isinstance(data.get("look"), dict) else None)
    got["read"] = data
    return got
