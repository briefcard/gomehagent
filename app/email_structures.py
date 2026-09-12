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
                   notes: str = "", by: str = "", look: dict | None = None,
                   design: dict | None = None, read_info: dict | None = None) -> dict:
    """Put one structure in the library, once per distinct sequence.

    `design` is the whole of how the email is built, in `email_design.SCHEMA`'s
    vocabulary; it goes through `email_design.normalize`, which keeps what the
    renderer draws and RETURNS what it did not (`dropped`, on the result) —
    a reading that volunteered a hex or a face is told so, never trimmed in
    silence. Without one the structure carries `email_design.house(look)`:
    today's renderer as a design, the look folded in.

    `look` is the old six-axis arrangement — kept, in `profile["look"]`, until
    Phase 4 of INITIATIVE-email-design.md retires the renderer's `LOOK`; the
    design already carries everything it says.

    `notes` are checked with `craft.leaks` BEFORE filing: a structure that
    names a brand, a URL or a person is one that would carry another account's
    fact into every email built on it, and the library is shared.
    """
    from . import craft, email_design
    seq = [str(t).strip().lower() for t in (sequence or []) if str(t).strip()]
    unknown = [t for t in seq if t not in block_types()]
    dropped: list[str] = []
    if design is not None:
        dsg, dropped = email_design.normalize(design)
    else:
        dsg = email_design.house(look)
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
        lk = look_of(look)
        if lk or design is not None:
            with db.SessionLocal() as s:
                row = s.get(db.EmailStructure, have.id)
                prof = dict(row.profile or {})
                if lk and prof.get("look") != lk:
                    prof["look"] = lk
                    row.profile = prof
                # A re-read carries its design forward the same way; a design
                # read where none was is the house with the look folded in.
                if design is not None or not (row.design or {}):
                    row.design = dsg if design is not None else email_design.house(
                        prof.get("look"))
                if read_info is not None:
                    prof["read"] = dict(read_info)
                    # A re-read's notes replace the old — they were checked
                    # for leaks above like the first ones; blank ones (the
                    # quoted-copy gate emptied them) leave the old standing.
                    if notes:
                        prof["notes"] = notes[:600]
                    row.profile = prof
                s.commit()
        return {"ok": True, "id": have.id, "existing": True,
                "name": have.name, "review": have.review, "dropped": dropped}
    prof = dict(profile or profile_of([{"type": t} for t in seq]))
    if notes:
        prof["notes"] = notes[:600]
    if read_info is not None:
        prof["read"] = dict(read_info)
    if lk := look_of(look):
        prof["look"] = lk
    with db.SessionLocal() as s:
        row = db.EmailStructure(
            name=(name or signature(seq))[:120], source=source,
            source_url=source_url[:500], source_asset_id=source_asset_id,
            sequence=seq, profile=prof, design=dsg,
            fits_intents=[i for i in fits_intents if i in INTENTS],
            fits_formats=[f for f in fits_formats if f in FORMATS] or ["designed"],
            requires=requires_of(seq), review=review,
            reviewed_by=by if review == "approved" else "",
            reviewed_at=db.utcnow() if review == "approved" else None)
        s.add(row)
        s.commit()
        return {"ok": True, "id": row.id, "existing": False, "name": row.name,
                "review": row.review, "dropped": dropped}


def file_from_output(output_id: str, *, by: str = "owner") -> dict:
    """An email of ours that was APPROVED joins the library as a structure.

    The owner's rule. Filed from `Output.shape`, which is the block sequence
    the email was built from, and only once per distinct sequence — the
    library grows by shapes, not by sends. Approved on arrival, because the
    approval was the decision.
    """
    from . import email_design
    with db.SessionLocal() as s:
        out = s.get(db.Output, output_id)
        if out is None:
            return {"ok": False, "why": "no such output"}
        seq = list(out.shape or [])
        angle = str(out.angle or "")
        theme = str(out.theme or "")
        tenant = str(out.tenant or "")
        # THE DESIGN THE SEND WAS BUILT ON rides the artifact's meta (Phase
        # 5 — `Context.emit` writes the same meta onto `ArtifactBody`); an
        # approved send files it with its shape, so the library keeps how
        # approved emails looked, not only their order.
        art = (s.query(db.ArtifactBody).filter(db.ArtifactBody.output_id == output_id)
               .order_by(db.ArtifactBody.created_at.desc()).first())
        design = dict(((getattr(art, "meta", None) or {}).get("design") or {}))
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
                         fits_formats=[theme] if theme in FORMATS else [], by=by,
                         design=design if design else None)
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


def sequence_from_brief(brief: dict) -> list:
    """A rough block order read off a brief's sections — ONLY so the rules
    that bind at use keep working (`requires_of`: products need a catalogue,
    proof needs claims, a hero needs a picture; `recent_shapes` keeps the
    same people from the same shape twice running). Never drawn from: the
    email is made from the brief, not from this."""
    out: list[str] = []
    first_photo = True
    for sec in brief.get("sections") or []:
        what = str(sec.get("what") or "").lower()
        kind = str(((sec.get("asset") or {}).get("kind") or "")).lower()
        jobs = " ".join(str(j.get("job") or "") for j in (sec.get("copy") or []) if isinstance(j, dict)).lower()
        if kind in ("photograph", "illustration"):
            out.append("hero" if first_photo else "image")
            first_photo = False
        if "quote" in what or "testimonial" in what or "review" in what:
            out.append("quote")
        if "grid" in what and "product" in what or "flavour" in what or "flavor" in what:
            out.append("products")
        if "step" in jobs or "list" in what or "recipe" in what:
            out.append("list")
        if any(w in what or w in jobs for w in ("headline", "hook", "title")):
            out.append("heading")
        if any(w in what or w in jobs for w in ("cta", "button", "shop", "ask")):
            out.append("cta")
        if not out or out[-1] in ("hero", "image", "quote", "products", "cta"):
            if jobs and "step" not in jobs:
                out.append("text")
    seq = [t for t in out if t in block_types()]
    return seq if len(seq) >= 2 else ["hero", "text", "cta"]


def file_reference(asset_id: str, *, brief: dict, source_url: str = "") -> dict:
    """ONE STRUCTURE PER REFERENCE PICTURE — keyed by the swipe's asset, never
    by a block sequence, because two references can share a rough order and
    be nothing alike; the brief is the design now. Lands IN THE ROTATION —
    the review beside it is there to take it out or to make it the standing
    choice, never a step before it may be used."""
    name = str(brief.get("concept") or "a reference")[:120]
    with db.SessionLocal() as s:
        a = s.get(db.KbAsset, asset_id)
        row = (s.query(db.EmailStructure).filter(db.EmailStructure.source_asset_id == asset_id)
               .order_by(db.EmailStructure.created_at.desc()).first())
        if row is None:
            from . import email_design
            seq = sequence_from_brief(brief)
            row = db.EmailStructure(
                name=name, source="swipe", source_url=(source_url or (a.source if a else "") or "")[:500],
                source_asset_id=asset_id, sequence=seq, profile=profile_of([{"type": t} for t in seq]),
                # fits any intent and any format — the design is the design;
                # IN THE ROTATION on arrival (owner, 2026-09-12: "let it
                # randomly be chosen for the email campaigns I generate"),
                # and "Not this one" takes it out.
                fits_intents=[], fits_formats=[], requires=requires_of(seq),
                design=email_design.house(), review="approved")
            s.add(row)
        row.brief = dict(brief)
        if not row.name or (a is not None and row.name == (a.title or "")):
            row.name = name
        s.commit()
        return {"ok": True, "id": row.id, "name": row.name, "review": row.review}


#: Where the standing choice lives: on the brand's own row, under `visual`
#: — it is a fact about how THIS brand's emails look, written through
#: `kb.set_brand` like every other brand field (the register keeps one
#: writer per table; `Setting` has none and is not given a twelfth).
DESIGNATED_FIELD = "email_design"


def standing_designation(tenant: str) -> str:
    """The design every campaign of this brand is built on until the owner
    says otherwise — "" when campaigns draw at random."""
    from . import kb
    b = kb.brand(tenant)
    return str(((getattr(b, "visual", None) or {}).get(DESIGNATED_FIELD) or "")) if b else ""


def designate(tenant: str, structure_id: str = "") -> str:
    """Set (or, with "", clear) the standing choice. Owner, 2026-09-12: *"I
    should be able to choose it or let it randomly be chosen for the email
    campaigns I generate."* A plan's own `structure` field still outranks
    this for that one send."""
    if structure_id:
        st = next((r for r in library() if r["id"] == structure_id), None)
        if st is None:
            return "no design with that id"
        if st["review"] != "approved":
            return f"{st['name']!r} is not in the rotation yet — use it first"
        ok, why = usable_for(tenant, st)
        if not ok:
            return f"{st['name']!r} is not for this brand — {why}"
    from . import kb
    b = kb.ensure_brand(tenant)
    visual = dict(getattr(b, "visual", None) or {})
    visual[DESIGNATED_FIELD] = structure_id
    kb.set_brand(tenant, visual=visual)
    return ("every campaign now uses this design until you say otherwise" if structure_id
            else "campaigns draw at random from the rotation again")


def library(*, review: str = "") -> list[dict]:
    with db.SessionLocal() as s:
        q = s.query(db.EmailStructure)
        if review:
            q = q.filter(db.EmailStructure.review == review)
        rows = q.order_by(db.EmailStructure.created_at.desc()).all()
        return [_row(r) for r in rows]


def backfill_designs() -> int:
    """Every structure filed before designs existed takes `house(look)`. Run
    at boot; writes only where the design is empty, so a read design is
    never overwritten and a second boot changes nothing. Returns how many."""
    from . import email_design
    n = 0
    with db.SessionLocal() as s:
        for row in s.query(db.EmailStructure).all():
            if row.design:
                continue
            row.design = email_design.house((row.profile or {}).get("look"))
            n += 1
        if n:
            s.commit()
    return n


def _row(r) -> dict:
    return {"id": r.id, "name": r.name, "source": r.source,
            "source_url": r.source_url, "sequence": list(r.sequence or []),
            "profile": dict(r.profile or {}), "design": dict(r.design or {}),
            "fits_intents": list(r.fits_intents or []),
            "fits_formats": list(r.fits_formats or []),
            "requires": list(r.requires or []), "review": r.review,
            "brief": dict(getattr(r, "brief", None) or {}),
            "source_asset_id": r.source_asset_id or "",
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
    if _is_reference(structure):
        # A DESIGN WITH A BRIEF is made by the recreation, which casts what
        # the brand has and CUTS what it lacks, saying so per section — so a
        # missing claim or product does not refuse the whole design here. The
        # words gate above still binds. (Owner, 2026-09-12: a campaign fell
        # back to the house design while a reference sat in the rotation.)
        return True, ""
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


def _is_reference(st: dict) -> bool:
    """A design made by the recreation — it has a brief, or a reference
    picture the brief is read from at the first use."""
    return bool(st.get("brief") or st.get("source_asset_id"))


def eligible(tenant: str, *, intent: str = "", fmt: str = "",
             recent_shapes: list | None = None, recent_designs: list | None = None) -> list[dict]:
    """Every structure this send COULD be built on: approved, usable for this
    brand, fitting the send's intent and form where it declares any, and not
    one this list received lately — by DESIGN for a reference (a rough block
    order is shared between designs that are nothing alike), by shape for
    the older, order-only structures."""
    recent = {signature(s) for s in (recent_shapes or []) if s}
    recent_ids = {d for d in (recent_designs or []) if d}
    out = []
    for st in library(review="approved"):
        if intent and st["fits_intents"] and intent not in st["fits_intents"]:
            continue
        if fmt and st["fits_formats"] and fmt not in st["fits_formats"]:
            continue
        if _is_reference(st):
            if st["id"] in recent_ids:
                continue
        elif signature(st["sequence"]) in recent:
            continue
        ok, _why = usable_for(tenant, st)
        if not ok:
            continue
        out.append(st)
    return out


def least_recent(candidates: list[dict], recent_designs: list | None, recent_shapes: list | None) -> list[dict]:
    """THE CLOCK RESETS (owner, 2026-09-12: *"if there are only five design
    options and we've sent five different emails, then which is the least
    recent?"*): among designs this list has all seen, the ones seen longest
    ago — `recent_*` are newest first, so the largest index is the oldest;
    a design not in the history at all is older than any that is."""
    ids = [d or "" for d in (recent_designs or [])]
    shapes = [signature(s) if s else "" for s in (recent_shapes or [])]

    def age(st: dict) -> int:
        key = st["id"] if _is_reference(st) else signature(st["sequence"])
        seq = ids if _is_reference(st) else shapes
        try:
            return seq.index(key)
        except ValueError:
            return 10 ** 6
    if not candidates:
        return []
    oldest = max(age(st) for st in candidates)
    return [st for st in candidates if age(st) == oldest]


def pick(tenant: str, *, intent: str = "", fmt: str = "",
         recent_shapes: list | None = None, designated: str = "",
         recent_designs: list | None = None) -> dict:
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
    # THE STANDING CHOICE, when the plan names none: what the owner picked
    # on the Designs page for every campaign of this brand.
    designated = designated or standing_designation(tenant)
    if designated:
        st = next((r for r in library() if r["id"] == designated), None)
        if st is None:
            return {"structure": None, "designated": True,
                    "why": f"no structure with id {designated!r} — designed fresh"}
        if st["review"] != "approved":
            return {"structure": None, "designated": True,
                    "why": (f"{st['name']!r} is {st['review']}, not in the rotation — "
                            f"use it on the Designs page first; designed fresh")}
        ok, why = usable_for(tenant, st)
        if not ok:
            return {"structure": None, "designated": True,
                    "why": f"{st['name']!r} is not for this brand — {why}; designed fresh"}
        return {"structure": st, "designated": True,
                "why": f"designated: {st['name']}"}
    pool = eligible(tenant, intent=intent, fmt=fmt, recent_shapes=recent_shapes,
                    recent_designs=recent_designs)
    if pool:
        st = random.choice(pool)
        return {"structure": st, "designated": False,
                "why": f"drawn from {len(pool)} that fit: {st['name']}"}
    # THE ROTATION BEFORE THE HOUSE (owner, 2026-09-12: a campaign came out
    # in "the old design which is not in our references"), AND THE CLOCK
    # RESETS: when this list has seen every design in the rotation, the one
    # it saw longest ago is used (a draw among ties), and the note says so.
    # A design excluded only by the send's intent or form is likewise used.
    # The house is built on only when the rotation holds nothing this brand
    # may use at all.
    any_usable = [st for st in library(review="approved") if usable_for(tenant, st)[0]]
    if any_usable:
        seen = any(recent_designs or []) or any(recent_shapes or [])
        oldest = least_recent(any_usable, recent_designs, recent_shapes) if seen else any_usable
        st = random.choice(oldest or any_usable)
        return {"structure": st, "designated": False,
                "why": (f"this list has seen every design in the rotation ({len(any_usable)}) — "
                        f"the clock resets and the least recent is used: {st['name']}" if seen else
                        f"none of the {len(any_usable)} in the rotation declares this send's intent "
                        f"or form — used anyway: {st['name']}")}
    return {"structure": None, "designated": False,
            "why": "nothing in the rotation this brand may use — designed fresh, the house way"}


def mark_used(structure_id: str) -> None:
    with db.SessionLocal() as s:
        row = s.get(db.EmailStructure, structure_id)
        if row is not None:
            row.used_count = int(row.used_count or 0) + 1
            row.last_used_at = db.utcnow()
            s.commit()


def brief(structure: dict) -> str:
    """The words the drafter gets. The ORDER, and why — never any copy. A
    structure carrying a design with a concrete order is briefed by that
    (`email_design.brief`: its sections, their slots, the limits the type
    scale imposes); the shape facts and the notes ride beneath either way."""
    from . import email_design
    prof = structure.get("profile") or {}
    seq = structure.get("sequence") or []
    bf = structure.get("brief") or {}
    if bf.get("concept"):
        # THE DESIGN IN WORDS. The drafter writes the MESSAGE — subject, angle,
        # the claims and products it carries; the recreation writes each of
        # the design's copy jobs to carry that message and builds the email.
        jobs = []
        for sec in bf.get("sections") or []:
            for j in sec.get("copy") or []:
                if isinstance(j, dict) and j.get("job"):
                    jobs.append(f"    - {j['job']}" + (f" ({j['limit']})" if j.get("limit") else ""))
        return ("\n## THE DESIGN THIS SEND IS BUILT IN: " + str(bf["concept"])[:300]
                + "\nWrite the MESSAGE — the subject, the angle, the products and claims it "
                  "carries, the ask — in blocks as usual. The email itself is then written "
                  "in this design with your message poured into its copy jobs, which are:\n"
                + "\n".join(jobs[:14]) + "\n  Keep the message tight enough to fit them.")
    dsg = email_design.brief(structure.get("design") or {})
    if dsg:
        lines = [dsg]
        if prof.get("notes"):
            lines.append("  What it does well: " + str(prof["notes"])[:400])
        return "\n".join(lines)
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


def read_swipe(asset_id: str) -> dict:
    """Look at one swipe and propose the structure it uses — its whole DESIGN
    (`email_design.read`: strips cut to the reviewer's tier, three passes,
    the vocabulary from the schema). PROPOSED, not approved: a reading is a
    generator's opinion and generators propose."""
    from . import email_design
    return email_design.read(asset_id)
