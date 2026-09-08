"""Bespoke, governed campaign visuals: the approved library first, a Canva
draft on a miss — never an unapproved pixel in a customer's inbox.

The owner's requirement (2026-08-21): campaign emails will often need a
bespoke marketing visual per email. The governed loop that delivers that
without breaking "launch is always human-approved":

1. **Select** — the hero image comes from the creative library via
   `kb.assets(publishable_only=True)`, which is the safe read: approved
   (review gate) AND `rights == owned` (a competitor's photograph saved for
   inspiration is structurally unreachable from here). Entity-scoped
   photographs beat brand-wide ones; logos are never heroes.

2. **Draft on miss** — when nothing usable exists and the caller opted in,
   a Canva design is CREATED (right-sized for an email hero, filed in the
   tenant's folder, recorded in the library as a `design`). A design is not
   pixels: it cannot be selected as a hero, so nothing generated here can
   leak into an email in the same run. The owner finishes it in Canva; the
   exported photograph enters the pictures review queue like any other
   candidate, and the NEXT campaign run selects it. Two steps, and the
   second one is the human.

3. **Absence survives** — no image is a labelled state, not a blank: the
   campaign email renders imageless (the renderer is built for it) and the
   run notes exactly why and what would change it.

Tenant-generic: nothing here names a client, sizes come from constants, and
the Canva transport (REST today, MCP as tool names are learned — see
ARCHITECTURE.md) is the adapter's business, not this module's.
"""
from __future__ import annotations

import re

from . import kb

#: Email-hero canvas, px. 1200×600 renders crisply at the renderer's 600px
#: width on 2× displays; 2:1 keeps the hero from swallowing the fold.
HERO_W, HERO_H = 1200, 600


def _usable(rows: list, entity_keys) -> list:
    """Publishable images, heroes only, in the caller's order of preference.

    `kb.assets` already enforced approved+owned; this layer only ORDERS and
    excludes logos — a brand mark as the hero reads as a letterhead, and the
    header already carries the logo from the theme.

    `entity_keys` is a SEQUENCE and its order is honoured: the caller passes
    the thing the artifact is actually about first, then whatever else it
    features. A set discarded that, so an email about the glasses could take a
    photograph scoped to a companion — technically "entity-scoped", and still
    the wrong picture. Ranking by position makes the caller's priority the
    picture's priority.
    """
    order = {k: i for i, k in enumerate(
        [k for k in (entity_keys or []) if k])}
    heroes = [r for r in rows if (r.subject or "") != kb.LOGO and (r.url or "")]
    scoped = sorted((r for r in heroes if (r.entity_key or "") in order),
                    key=lambda r: order[r.entity_key or ""])
    brandwide = [r for r in heroes if not (r.entity_key or "")]
    return scoped + brandwide


def hero_for_campaign(tenant: str, *, segment_key: str = "",
                      entity_keys: list[str] | None = None,
                      title: str = "", draft_if_missing: bool = False,
                      boards: tuple | list = (),
                      draw_first: bool = False,
                      commitment: dict | None = None, claim: str = "",
                      prominent: str = "", situation: str = "",
                      image_model: str = "") -> dict:
    """The hero image for one campaign email, or the governed path to one.

    Returns one of:
      {ok, basis: "generated", image: {url, alt}, asset_id, model, note}
      {ok, basis: "approved_asset", image: {url, alt}, asset_id}
      {ok, basis: "drafted_in_canva", image: None, drafted: {...}, note}
      {ok, basis: "none", image: None, why}   — absence, named
    and `drawn_why` on any of them when a drawing was attempted and dropped.

    DRAWN FIRST (owner, 2026-09-08: *"I want this on all the systems. Emails
    and blogs are still not leveraging this generative feature at all"*).
    With `draw_first` on and the brand's own pictures to draw from
    (`drawable`), the hero is what the ad set makes: drawn from the
    product's photographs in the board's look, judged against those
    photographs, filed PROPOSED — and the draft the owner reviews carries
    it. `FORMATS["email_hero"]` says why it outranks the catalogue shot: a
    product shot at the top of an email is a catalogue page. Approving the
    email approves the picture in it (`push_campaign_to_esp` →
    `kb.approve_generated`); nothing reaches the platform that a person did
    not look at. A drawing that was NOT the product is dropped and said, and
    the approved-photograph ladder below it stands exactly as before.
    """
    ordered = list(dict.fromkeys(k for k in (entity_keys or []) if k))
    ents = set(ordered)
    drawn_why = ""
    if draw_first and drawable(tenant, ordered[0] if ordered else "", boards):
        subject = ordered[0] if ordered else ""
        made = generate(tenant, commitment=commitment, fmt="email_hero",
                        entity_key=subject, claim=claim, prominent=prominent,
                        situation=situation, boards=boards,
                        image_model=image_model)
        if made.get("ok"):
            return {"ok": True, "basis": "generated",
                    "asset_id": made["asset_id"],
                    "subject_key": subject or "brand-wide",
                    "image": {"url": made["url"],
                              "alt": made.get("subject") or segment_key or ""},
                    "model": made.get("model", ""),
                    "assessment": made.get("assessment") or {},
                    "fidelity": made.get("fidelity"),
                    "note": (f"drawn by {made.get('model', '')} — "
                             f"{made.get('basis', '')}; PROPOSED — approving "
                             f"this email approves the picture")}
        drawn_why = ("a picture was drawn and dropped: "
                     + str(made.get("error") or "generation failed")[:200] + ". ")
    rows: list = []
    # The brand-wide shelf ("" ) is ALWAYS fetched alongside the scoped keys.
    # It used to be fetched only when no entity was named — so the moment a
    # campaign carried entities, an approved brand photograph became
    # structurally unreachable and the email went imageless past a perfectly
    # good hero. Ordering still prefers scoped over brand-wide (`_usable`).
    for ek in ents | {""}:
        rows += kb.assets(tenant, publishable_only=True, kind="image",
                          entity_key=ek or "")
    seen: set[str] = set()
    rows = [r for r in rows if not (r.id in seen or seen.add(r.id))]
    # THE BOARD FIRST, within each rung. `_usable` keeps this order inside its
    # scoped-then-brand-wide split, so a pinned photograph of the product
    # beats an unpinned one and a pinned look beats a shelf shot — the email
    # hero reaches the boards the ad set reaches (owner, 2026-09-06).
    rows.sort(key=lambda r: 0 if kb.pinned(r, boards) else 1)
    pick = next(iter(_usable(rows, ordered)), None)
    if pick is not None:
        # Belt to the braces `kb.assets` already provides: the use-gate names
        # its own refusal, and a row that fails it is skipped, not shipped.
        allowed, why = kb.may_publish(pick.id)
        if allowed:
            # WHAT THIS IS A PICTURE OF, carried out with the picture. The
            # caller placing a hero had no way to know whether it depicted the
            # product the email is about or a brand-wide shelf photograph, so
            # nothing could tell a fitting hero from a tablecloth on an email
            # about glasses (owner, 2026-08-22). `coherence.review` reads this
            # field; without it an image is unattributed and reported as such.
            return {"ok": True, "basis": "approved_asset",
                    "asset_id": pick.id,
                    "subject_key": (getattr(pick, "entity_key", "") or ""
                                    ) or "brand-wide",
                    "image": {"url": pick.url,
                              "alt": pick.title or segment_key or ""},
                    "drawn_why": drawn_why}

    if not draft_if_missing:
        return {"ok": True, "basis": "none", "image": None,
                "why": (drawn_why
                        + "no approved, owned photograph fits this campaign "
                        "(entity-scoped or brand-wide) — approve one in the "
                        "pictures queue, or pass draft_visual to have a "
                        "bespoke Canva draft created for review.")}

    from . import canva, credentials as cred
    if not (cred.resolve(tenant, "canva") or {}).get("secret"):
        return {"ok": True, "basis": "none", "image": None,
                "why": (drawn_why
                        + "no approved photograph fits, and no Canva is "
                        "connected to draft one — connect Canva on the "
                        "Accounts tab, or approve a picture in the queue.")}
    made = canva.create_design(
        tenant, title=(title or f"Email hero — {segment_key or 'campaign'}")[:120],
        entity_key=next(iter(ents), ""), width=HERO_W, height=HERO_H)
    if not made.get("ok"):
        return {"ok": True, "basis": "none", "image": None,
                "why": f"Canva could not draft a hero: {made.get('error', '')[:200]}"}
    return {"ok": True, "basis": "drafted_in_canva", "image": None,
            "drafted": {"design_id": made.get("design_id", ""),
                        "edit_url": made.get("edit_url", "")},
            "note": ("a bespoke hero was drafted in Canva — finish it there, "
                     "export it, and the picture lands in the review queue; "
                     "the next run of this campaign will use it once "
                     "approved. Nothing unapproved ships meanwhile.")}


# ---------------------------------------------------------------------------
# Photographs the client already has, in Drive
# ---------------------------------------------------------------------------

#: Image types worth filing. Anything else in a Drive folder is a document.
_DRIVE_IMAGE_TYPES = ("image/jpeg", "image/png", "image/webp")


#: What a generated image is filed as. `owned` because the client
#: commissioned it and the model's output is theirs to publish; `generated` as
#: the origin so it is never mistaken for a photograph somebody took.
#: `kb.GENERATED_ORIGIN` is the same word — kb reads it to settle a generated
#: picture on the strength of its artifact's approval, and the suite holds the
#: two equal.
GENERATED_RIGHTS = "owned"
GENERATED_ORIGIN = "generated"


def drawable(tenant: str, entity_key: str = "", boards: tuple | list = ()) -> bool:
    """Whether `generate` would have the brand's own pictures to draw FROM —
    the same reading `board_inputs` makes, without fetching a byte: the
    boards are on, and the selected boards carry a look, or the piece is
    about a product that is pinned or photographed. A piece that is not
    drawable falls to the approved-photograph ladder, so a run never draws
    a nameless scene where a real photograph was on file."""
    every = kb.board(tenant)
    if not (every["look"] or every["product"]):
        return False
    sel = kb.board(tenant, boards) if boards else every
    if sel["look"]:
        return True
    ent = entity_key or ""
    if not ent:
        return False
    if any((r.entity_key or "") == ent for r in sel["product"]):
        return True
    return any((r.entity_key or "") == ent
               and (r.origin or "") != GENERATED_ORIGIN
               and (r.subject or "") != kb.LOGO
               for r in kb.assets(tenant, publishable_only=True, kind="image"))


def brand_model(tenant: str) -> tuple[str, str]:
    """The model a system draws with when its form did not say — the brand's
    default from the Brand tab (`kb.image_model`), honoured when its key is
    set, else the system default — and WHY when the brand's could not be
    honoured, so the run says it rather than drawing with something else
    silently. Owner, 2026-09-08: *"I want this on all the systems. Emails and
    blogs are still not leveraging this generative feature at all."* The ad
    set's form starts from this value; the email hero and the article
    pictures, drawn inside a run with no form in front of them, read it here."""
    from . import imagegen
    models, why = imagegen.chosen("", default=kb.image_model(tenant))
    return (models[0] if models else imagegen.MODEL), why


#: WHAT THE PICTURE IS FOR, per format. Not sizes — jobs.
#:
#: Owner, 2026-08-29: *"if it's an email about knee pain - it should probably
#: have something to do with that … For Ads this is ESPECIALLY important.
#: Every ad we generate will live or die by its creative."* The first version
#: of this brief built one prompt from the account's standing knowledge, so an
#: Eien email about knee pain would have produced a photograph of a softgel:
#: on-brand, and about nothing the reader opened the email for.
#:
#: The three do different work and a prompt that does not say so gets the
#: average of the three, which is a stock photograph.
#: The default, and it is the right one for a hero that has to read as a
#: photograph somebody took.
_TREATMENT_PHOTOGRAPHIC = (
    "Photographic and real. NO text, lettering, watermark or logo of any "
    "kind. Nothing that reads as a stock photograph.")

#: An ad is a made thing and may look like one. This does NOT choose a style —
#: the brand's own direction does that, and it arrives after this line so it
#: has the last word. What this does is stop demanding a documentary
#: photograph from a format whose job is to argue.
_TREATMENT_DESIGNED = (
    "THIS IS AN ADVERTISEMENT AND MAY LOOK LIKE ONE. Do not imitate a candid "
    "documentary photograph. A designed frame is fully legitimate here — a "
    "flat colour ground, a graphic field, a bold crop, one object treated as "
    "the hero with deliberate space around it. Compose it: decide where the "
    "eye lands first and give that thing room. Keep one clear band free of "
    "busy detail where a headline will be set afterwards. NO text, lettering, "
    "watermark or logo of any kind — the words are set later, by hand.")

FORMATS = {
    "email_hero": dict(
        shape="landscape",
        job="An invitation. The reader has just opened this; the picture has "
            "to make the subject feel like theirs before they read a word. "
            "Show the PERSON'S SITUATION rather than the product — a product "
            "shot at the top of an email is a catalogue page, and it is "
            "skipped.",
        extra=("on_subject", "audience_fit")),
    "article_hero": dict(
        shape="landscape",
        job="An editorial illustration of what the article is about. It sits "
            "under a headline in a search result and on a blog index, so it "
            "must read as journalism rather than as an advertisement. No "
            "packshot, no staged selling.",
        extra=("on_subject",)),
    "article_body": dict(
        # NOT THE HERO'S JOB. The hero sits under a headline in a search
        # result and has to summarise the whole piece; a body image sits
        # inside one section and has to make THAT passage concrete. Selecting
        # both with one rule is how an article ends up with two versions of
        # the same picture — the hero repeated halfway down, which reads as a
        # rendering fault rather than as illustration.
        shape="landscape",
        job="Illustration for ONE passage of an article, not for the article. "
            "It sits beside a specific paragraph and its whole job is to make "
            "that paragraph concrete — the thing being described, at the "
            "moment being described. It must not restate the headline, and it "
            "must not read as an advertisement any more than the hero does.",
        extra=("on_subject",)),
    "ad_frame": dict(
        shape="square",
        job="AN ARGUMENT, not a decoration. It has to stop a thumb and land "
            "one idea before anybody reads the copy beside it. It must argue "
            "the SAME idea the copy argues — a frame that says something else "
            "splits the ad in two and neither half lands.",
        treatment=_TREATMENT_DESIGNED,
        craft="Would this stop a stranger mid-scroll, and does it look "
              "deliberately DESIGNED for this brand rather than a pleasant "
              "picture any brand could have run? Judge it as an ad, not as a "
              "photograph: a graphic, built frame is a good answer here.",
        extra=("on_subject", "audience_fit", "stops_the_scroll",
               "lands_the_positioning")),
}

#: What the finished image is checked against. The spine holds for every
#: format; `FORMATS[...]["extra"]` adds what that format lives or dies by.
#:
#: `no_text` is here because it is the commonest practical failure of an image
#: model and the one a person notices last — words baked into a picture cannot
#: be edited, translated or corrected, and they survive into every placement.
CRITERIA = {
    "on_subject": "Does the picture depict what this piece is ABOUT? "
                  "Not the brand, not the product for its own sake — the "
                  "subject named below.",
    # POLARITY IS UNIFORM AND IT WAS NOT. `_ASSESS` never said what `pass`
    # meant, and two of these were written so that the honest answer to the
    # question sets `pass: true` ON A FAILURE — "does it show anything that
    # would contradict the claim" answered yes is a picture that contradicts
    # the claim, filed as passing. Every question below is now phrased so YES
    # is the good answer, and `_ASSESS` says so. Changing one without the
    # others is worse than changing none: the number gets less trustworthy
    # while looking more so.
    "claim_safe": "Is everything the picture shows consistent with the claim "
                  "quoted below — nothing that contradicts it, and nothing "
                  "that implies more than it says?",
    "no_text": "Is the image completely free of text, lettering, watermarks "
               "and logos? Any at all means no.",
    "audience_fit": "Would the audience described below recognise "
                    "themselves, or the moment they are in?",
    "craft": "Does it look like a photograph somebody was paid to take, "
             "rather than like generic stock?",
    "stops_the_scroll": "In one glance and at thumbnail size, is there a "
                        "reason to stop?",
    "lands_the_positioning": "Does it argue the specific idea below, rather "
                             "than being pleasant and unrelated?",
    # THE ONE THAT GATES. Asked only of a frame with a real photograph
    # composited into it, because it is the only frame that can fail this way
    # — and it is the failure the owner reported: "pasted onto another image".
    "integration": "The product in this image is a real photograph placed "
                   "into a generated scene. Does it look PHOTOGRAPHED THERE — "
                   "light coming from the same direction as everything else, "
                   "the same colour temperature, a contact shadow that agrees "
                   "with the scene's other shadows, edges that belong? "
                   "Answer no if it reads as cut out and pasted on, or if a "
                   "person would notice.",
}


def _subject_of(commitment: dict | None, situation: str, entity_label: str,
                prominent: str) -> str:
    """What this piece is ABOUT, in the words the artifact already committed to.

    `coherence.commit` has carried this since it was written — its `KINDS`
    include `topic` ("one subject a piece of content is about") and
    `situation` ("one question or circumstance a person is in"), declared
    BEFORE anything is selected and checked at emit. The first image brief
    read `entity_key` and nothing else, which is one of the six kinds; for an
    article about knee pain the commitment is a situation and there is no
    entity at all, so the picture had nothing to be of.
    """
    c = commitment or {}
    label = str(c.get("label") or "").strip()
    if label and c.get("kind") in ("topic", "situation", "audience", "period"):
        return label
    for candidate in (situation, label, entity_label, prominent):
        if str(candidate or "").strip():
            return str(candidate).strip()
    return ""


def brief_for(tenant: str, *, commitment: dict | None = None,
              fmt: str = "email_hero", prominent: str = "",
              entity_key: str = "", claim: str = "", situation: str = "",
              audience_key: str = "", positioning: str = "",
              composited: bool = False) -> dict:
    """Everything the picture has to do, and everything it will be judged on.

    STRUCTURED, not a prompt string. A video renderer needs the same subject,
    the same constraints and the same criteria, and would otherwise have to
    parse them back out of English — so the prompt is one field of this rather
    than the whole of it.

    Returns `{prompt, subject, criteria, palette, shape, fmt, thin}`.
    """
    from . import kb as kbmod
    spec = FORMATS.get(fmt) or FORMATS["email_hero"]
    parts, thin = [], []

    ent = None
    if entity_key:
        try:
            ent = next((e for e in kbmod.entities(tenant, available_only=False)
                        if getattr(e, "key", "") == entity_key), None)
        except Exception:                                        # noqa: BLE001
            ent = None

    subject = _subject_of(commitment, situation,
                          getattr(ent, "name", "") if ent else "", prominent)
    if subject:
        parts.append(f"WHAT THIS PICTURE IS ABOUT: {subject}. Everything else "
                     f"below is a constraint on how to show THAT.")
    else:
        thin.append("nothing says what this piece is about, so the picture "
                    "can only be generically on-brand — which is the "
                    "stock-photograph failure")

    parts.append(f"WHAT IT IS FOR: {spec['job']}")

    if prominent:
        parts.append(f"It sits beside these words, and must not repeat them "
                     f"literally: “{prominent[:160]}”")
    if ent is not None:
        parts.append(f"If a product appears it is {ent.name}"
                     + (f" — {str(ent.description or '')[:160]}"
                        if ent.description else "") + ".")
    if positioning:
        parts.append(f"THE IDEA THIS MUST ARGUE: {positioning[:200]}")
    elif fmt == "ad_frame":
        thin.append("no positioning given, so the frame has no idea to argue "
                    "and can only be decorative — which is how an ad dies")

    if claim:
        parts.append(f"It must be consistent with this, which the copy says: "
                     f"“{claim[:180]}”. Show nothing that would contradict it "
                     f"or imply more than it says.")
    else:
        thin.append("no claim, so nothing constrains what the picture implies")

    aud = None
    if audience_key:
        try:
            aud = next((x for x in kbmod.audiences(tenant)
                        if getattr(x, "key", "") == audience_key), None)
        except Exception:                                        # noqa: BLE001
            aud = None
    if aud is not None:
        parts.append(f"WHO IT IS FOR: {aud.name}"
                     + (f", who care about: " + "; ".join(list(aud.pains)[:3])
                        if (aud.pains or []) else "") + ".")
    else:
        thin.append("no audience, so nobody in particular is meant to see "
                    "themselves in it")

    palette = []
    try:
        b = kbmod.brand(tenant)
        theme = (getattr(b, "theme", None) or {}) if b else {}
        colours = theme.get("colors") or theme.get("colours") or {}
        palette = [v for v in colours.values()
                   if isinstance(v, str) and v.startswith("#")][:4]
    except Exception:                                            # noqa: BLE001
        palette = []
    if palette:
        parts.append("Brand palette: " + ", ".join(palette) + ".")
    else:
        thin.append("no brand theme colours on file, so the palette is the "
                    "model's taste rather than the brand's")

    # THE TREATMENT, PER FORMAT — and this line was the single most damaging
    # string in the pipeline. "Photographic and real" was appended to EVERY
    # brief including `ad_frame`, so the owner's "everything is trying to
    # pretend to be a real photo instead of an ad" was not a description of a
    # model's failure; it was a restatement of our own instruction. It is
    # correct for an article hero, which must read as journalism, and exactly
    # backwards for an ad. The no-lettering rule stays everywhere: a model
    # rendering type is still bad type, and the type layer is a person's or a
    # renderer's job.
    parts.append(spec.get("treatment") or _TREATMENT_PHOTOGRAPHIC)

    # WHAT HAS ALREADY WORKED ON THIS ACCOUNT. Owner, 2026-09-04: read the
    # winning ads into a look the brief cites. It is a DESCRIPTION, never the
    # images — a generator handed somebody's finished ad produces a copy of
    # it, and the point is the qualities they share. Absent until the owner
    # presses the button; `thin` says so, because "we have never looked at
    # what worked" is a real gap in an ad brief.
    look = {}
    try:
        from . import systems as _sysm
        look = _sysm.winning_look(tenant)
    except Exception:                                            # noqa: BLE001
        look = {}
    if look.get("look"):
        parts.append(
            f"WHAT HAS WORKED FOR THIS BRAND, from its own best-performing "
            f"ads (ranked by {look.get('ranked_by') or 'performance'}): "
            f"{str(look['look'])[:600]} Match those qualities — the light, "
            f"the framing, the palette, the styling. Do NOT reproduce any "
            f"particular one of them.")
    elif fmt == "ad_frame":
        thin.append("nothing has been read from this account's best-performing "
                    "ads, so the look is this model's taste rather than what "
                    "has actually worked here")

    # AND THE GATE STOPS ENFORCING WHAT THE BRIEF STOPPED ASKING FOR. `craft`
    # asked "does it look like a photograph somebody was paid to take, or like
    # generic stock?" — both answers are photographs, so a frame that looked
    # like an AD was marked down by our own reviewer. The prompt and the gate
    # agreed with each other and both disagreed with the owner.
    names = ("on_subject", "claim_safe", "no_text", "craft") + tuple(
        k for k in spec["extra"] if k not in ("on_subject",)) + (
        ("integration",) if composited else ())
    asks = dict(CRITERIA)
    if spec.get("craft"):
        asks["craft"] = spec["craft"]
    return {"prompt": " ".join(parts), "subject": subject, "fmt": fmt,
            "shape": spec["shape"], "palette": palette, "thin": thin,
            "criteria": [{"key": k, "ask": asks[k]} for k in dict.fromkeys(names)],
            "claim": claim, "positioning": positioning,
            "audience": getattr(aud, "name", "") if aud else ""}


_ASSESS = """You are reviewing one generated image before a person is asked to
approve it. You are not being asked whether it is pretty.

WHAT IT WAS SUPPOSED TO DO
{job}

THE SUBJECT IT MUST DEPICT: {subject}
{claim_line}{positioning_line}{audience_line}

Answer each question about the image, honestly and without flattery. A picture
that is technically fine and about the wrong thing FAILS — that is the whole
reason this check exists.

EVERY QUESTION BELOW IS WRITTEN SO THAT **YES** IS THE GOOD ANSWER. Set
"pass": true when the honest answer to the question is yes, and false when it
is no. Do not reverse this for any question, however it is phrased.

{questions}

Respond with JSON only:
{{"verdicts": [{{"key": "<the key>", "pass": true|false,
                "why": "<one short sentence, concrete>"}}],
  "overall": "<one sentence: is this usable, and if not what is wrong>",
  "fix": "<if it fails, ONE instruction that would fix it next time>"}}"""


def assess(blob: bytes, brief: dict, tenant: str = "") -> dict:
    """Ask a model whether the picture did the job the brief set it.

    NOT A GATE, and that is on purpose — the same conclusion `imagegen`
    already reached about `similarity`, for the same reason: a measurement
    that can veto will veto good work, and the cost of a false refusal here is
    a person doing by hand what the system was built to do. What it produces
    is a verdict attached to the asset, so whoever approves it is told what to
    look at rather than being handed a picture and a shrug.

    It IS allowed to trigger one regeneration, which is the same shape as the
    copy path's `redraft(previous, failures)` — draft, check, repair once,
    keep the better of the two.
    """
    if not blob:
        return {"ok": False, "why": "nothing to assess"}
    import base64 as _b64
    import json as _json

    from . import llm
    q = "\n".join(f"- {c['key']}: {c['ask']}" for c in brief.get("criteria") or [])
    text = _ASSESS.format(
        job=FORMATS.get(brief.get("fmt") or "", FORMATS["email_hero"])["job"],
        subject=brief.get("subject") or "(nothing was declared — say so)",
        claim_line=(f"THE CLAIM IT MUST NOT CONTRADICT: {brief['claim']}\n"
                    if brief.get("claim") else ""),
        positioning_line=(f"THE IDEA IT MUST ARGUE: {brief['positioning']}\n"
                          if brief.get("positioning") else ""),
        audience_line=(f"WHO IT IS FOR: {brief['audience']}\n"
                       if brief.get("audience") else ""),
        questions=q)
    reply = llm.ask("creative_review", [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                     "data": _b64.standard_b64encode(blob).decode()}},
        {"type": "text", "text": text}], tenant=tenant, max_tokens=700)
    if not getattr(reply, "ok", False):
        # A review that could not run is NOT a pass. Said, and carried.
        return {"ok": False, "why": getattr(reply, "degraded", "")
                or getattr(reply, "error", "the review could not run"),
                "verdicts": [], "failed": [], "overall": "", "fix": ""}
    raw = (reply.text or "").strip()
    try:
        data = _json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
    except Exception:                                            # noqa: BLE001
        return {"ok": False, "why": "the review did not answer in JSON",
                "verdicts": [], "failed": [], "overall": "", "fix": ""}
    verdicts = [v for v in (data.get("verdicts") or []) if isinstance(v, dict)]
    failed = [str(v.get("key") or "") for v in verdicts if not v.get("pass")]
    return {"ok": True, "verdicts": verdicts, "failed": failed,
            "overall": str(data.get("overall") or ""),
            "fix": str(data.get("fix") or ""), "why": ""}


_LOOK = """These are the best-performing ads from one brand's own account.

Describe, in one paragraph, WHAT THEY HAVE IN COMMON as photographs — the
light (direction, hardness, colour), the framing and camera height, the
palette, the styling and props, whether people appear and how, and the
overall finish. Write it as direction somebody could shoot to.

Say nothing about the words on them, nothing about the products themselves,
and do not describe any single image — if they have little in common, say
that plainly rather than inventing a shared style."""


_BOARD_LOOK = """These are pictures a brand saved as REFERENCES for how its own
pictures should look. They are not the brand's pictures and not its
products.

Describe, in one paragraph, WHAT THEY HAVE IN COMMON as photographs — the
light (direction, hardness, colour), the framing and camera height, the
palette, the styling, surfaces and props, whether people appear and how,
and the overall finish. Write it as direction somebody could shoot to.

Say nothing about any words on them, name no brand or product in them, and
do not describe any single image — if they have little in common, say that
plainly rather than inventing a shared style."""


def read_board_direction(tenant: str, slug: str, *, limit: int = 8) -> dict:
    """Look at a board's REFERENCE pins once and write down what they look
    like — the words path for pictures the brand may not send as pixels.

    Owner's card has said since 2026-09-06 that a reference pin "is read for
    direction, in words, and never sent"; until 2026-09-08 nothing read it.
    Same shape as `learn_winning_look`: one vision call, a description
    stored (`kb.set_board_direction`), the pictures dropped. `{ok, text,
    from, why}`.
    """
    from . import db, imagegen, llm
    have = kb.boards(tenant)
    if slug not in have:
        return {"ok": False, "why": f"no board named {slug!r}", "from": 0}
    rows = [r for r in kb.board(tenant, [slug])["look"]
            if (r.rights or kb.REFERENCE) != kb.OWNED]
    if not rows:
        return {"ok": False, "from": 0,
                "why": "no reference pins on this board — owned pins are sent as "
                       "pixels and need no reading"}
    import base64 as _b64
    blocks: list = []
    for r in rows[:max(1, limit)]:
        blob = _fetch(r.url or "")
        if not blob:
            continue
        blocks.append({"type": "image",
                       "source": {"type": "base64", "media_type": imagegen._mime(blob),
                                  "data": _b64.standard_b64encode(blob).decode()}})
    if not blocks:
        return {"ok": False, "from": 0,
                "why": "none of the reference pins could be fetched, so there is "
                       "nothing to look at"}
    blocks.append({"type": "text", "text": _BOARD_LOOK})
    reply = llm.ask("creative_review", blocks, tenant=tenant, max_tokens=500)
    if not getattr(reply, "ok", False):
        return {"ok": False, "from": len(blocks) - 1,
                "why": (getattr(reply, "degraded", "")
                        or getattr(reply, "error", "the reading could not run"))}
    text = (reply.text or "").strip()
    if not text:
        return {"ok": False, "from": len(blocks) - 1, "why": "the reading came back empty"}
    kb.set_board_direction(tenant, slug, {"text": text[:1500], "from": len(blocks) - 1,
                                          "read_at": db.utcnow().isoformat()})
    return {"ok": True, "text": text[:1500], "from": len(blocks) - 1, "why": ""}


def _direction_brief(refs: dict) -> str:
    """The reference boards' direction, as prompt text — or nothing."""
    text = str((refs or {}).get("direction") or "").strip()
    if not text:
        return ""
    return ("\n\nTHE BRAND'S VISUAL DIRECTION, read from the pictures it saved as "
            "references (match it — the light, the framing, the palette, the "
            "styling; it names no product and none is to be invented from it):\n"
            + text)


def learn_winning_look(tenant: str, *, top: int = 3) -> dict:
    """Look at this account's best ads and write down what they look like.

    ON THE OWNER'S CLICK, NEVER ON A SCHEDULE. It spends a Meta read, N image
    fetches and one vision call, and §5's standing rule is that recurring
    spend on a client's quota is declared rather than defaulted on. There is
    no caller but the button.

    IT STORES A DESCRIPTION, not the pictures. A generator handed a finished
    ad reproduces it; what transfers is the light, the framing and the
    palette — so the images are read once, described, and dropped.
    """
    from . import db, llm, meta_ads, systems as _sysm
    row = _sysm.find(tenant, "ad_creative")
    if row is None:
        return {"ok": False, "why": f"no ad_creative system on {tenant}"}
    got = meta_ads.winners(tenant, top=top)
    if not got["ok"]:
        return {"ok": False, "why": got["why"]}
    blocks: list = []
    used: list = []
    for ad in got["ads"]:
        url = ad.get("image_url") or ad.get("thumbnail_url")
        blob = _fetch(url)
        if not blob:
            continue
        import base64 as _b64
        blocks.append({"type": "image",
                       "source": {"type": "base64", "media_type": "image/jpeg",
                                  "data": _b64.standard_b64encode(blob).decode()}})
        used.append({"ad_id": ad["ad_id"], "name": ad["name"],
                     "ctr": ad["ctr"], "roas": ad["roas"]})
    if not blocks:
        return {"ok": False,
                "why": ("the winning ads were found but none of their images "
                        "could be fetched, so there is nothing to look at")}
    blocks.append({"type": "text", "text": _LOOK})
    reply = llm.ask("creative_review", blocks, tenant=tenant, max_tokens=600)
    if not getattr(reply, "ok", False):
        return {"ok": False,
                "why": (getattr(reply, "degraded", "")
                        or getattr(reply, "error", "the reading could not run"))}
    look = {"look": (reply.text or "").strip(),
            "ranked_by": got["ranked_by"], "from": used,
            "considered": got.get("considered", 0),
            "read_at": db.utcnow().isoformat()}
    _sysm.set_winning_look(row.id, look)
    return {"ok": True, **look}


def _fetch(url: str) -> bytes:
    """One image, or nothing. A seam, so the suite never reaches the network."""
    if not url:
        return b""
    import httpx
    try:
        r = httpx.get(url, timeout=30, follow_redirects=True)
        return r.content if r.status_code < 400 else b""
    except Exception:                                            # noqa: BLE001
        return b""


#: Commitment kinds whose artifact is ABOUT A THING in the catalogue. The
#: ladder is different on either side of this line, and not by ranking — a
#: product photograph on a topic-led piece is not a worse choice, it is the
#: wrong picture, which is the whole of the knee-pain complaint.
PRODUCT_LED = ("entity",)


def _tokens(text: str) -> set:
    from . import provenance as prov
    return {w for w in prov.normalise(text).split() if len(w) > 3}


def _about(asset, subject: str) -> bool:
    """Is this picture about that subject? Token overlap, deliberately loose.

    Generated assets carry the subject they were made for; crawled ones carry
    an entity or nothing. Exact matching would find almost nothing, and the
    cost of a loose match here is one picture a person rejects — against a
    ladder that never finds anything and generates every time.
    """
    want = _tokens(subject)
    if not want:
        return False
    have = _tokens(f"{asset.subject or ''} {asset.title or ''}")
    return len(want & have) >= min(2, len(want))


def pick(tenant: str, *, commitment: dict | None = None, fmt: str = "email_hero",
         entity_key: str = "", audience_key: str = "", claim: str = "",
         prominent: str = "", positioning: str = "", channel: str = "",
         situation: str = "", boards: tuple | list = ()) -> dict:
    """The best picture this account already has for this piece, or the brief
    to make one.

    THE BOARDS ARE ON THIS LADDER TOO. A picture the owner pinned as the
    product's own shot outranks whichever photograph of it sorted first; a
    picture pinned as the brand's look outranks an arbitrary brand-wide one.
    Both sit below `proven`, because a recorded result beats an opinion, and
    both are still `may_publish`-gated: a reference pin is never a hero.

    ONE LADDER, THREE SYSTEMS. The email hero, the article image and the ad
    frame were each going to grow their own selection rule, and three rules
    for one question is how the answer starts depending on which page you are
    on.

    IT DOES NOT GENERATE, and that is the load-bearing decision. Generation
    takes up to three minutes, costs about two thousand text calls, and lands
    `proposed` — so a draft that generated inline would block for minutes to
    produce something that draft is not allowed to attach. `pick` is cheap and
    synchronous: it selects, or it hands back the brief and says generate this
    somewhere else.

    THE RUNGS, and which ladder is used depends on what the piece is about:

      product-led   proven for that product · a photograph of it · brand-wide
      topic-led     proven about the subject · a picture about the subject
                    · NEVER a product shot

    That last one is an exclusion rather than a ranking. An article about knee
    pain with a photograph of a bottle is not a slightly worse article, and
    ordering would have let it through the moment nothing better existed —
    which is exactly when it matters.
    """
    from . import kb as kbmod
    kind = str((commitment or {}).get("kind") or "")
    ent = entity_key or str((commitment or {}).get("key") or "")
    product_led = bool(entity_key) or kind in PRODUCT_LED
    # THE HERO IS CHOSEN AGAINST THE SAME SUBJECT THE FRAME IS BRIEFED ON.
    # `batch` learned `situation` on 2026-09-07 and briefed the frame with it
    # while this — the brief that picks the photograph — stayed blind to it.
    brief = brief_for(tenant, situation=situation, commitment=commitment, fmt=fmt,
                      prominent=prominent, entity_key=ent if product_led else "",
                      claim=claim, audience_key=audience_key,
                      positioning=positioning)
    subject = brief["subject"]

    def _out(row, rung, why):
        return {"ok": True, "asset_id": row.id, "url": row.url or "",
                "rung": rung, "why": why, "should_generate": False,
                "brief": brief, "subject": subject}

    try:
        pool = list(kbmod.assets(tenant, publishable_only=True))
    except Exception:                                            # noqa: BLE001
        pool = []
    heroes = [r for r in pool
              if (r.subject or "") != kbmod.LOGO and (r.url or "")]
    try:
        proven = [r for r in kbmod.proven_assets(tenant, channel=channel,
                                                 metric="ctr" if channel else "")
                  if (r.url or "")]
    except Exception:                                            # noqa: BLE001
        proven = []

    if product_led:
        for r in proven:
            if (r.entity_key or "") == ent and ent:
                return _out(r, "proven", "it has carried this product before "
                                         "and the result was recorded")
        usable = {r.id: r for r in heroes}
        pins = kbmod.board(tenant, boards)
        for r in pins["product"]:
            if (r.entity_key or "") == ent and ent and r.id in usable:
                return _out(usable[r.id], "pinned_product",
                            "pinned on the board as this product's own shot")
        for r in heroes:
            if (r.entity_key or "") == ent and ent:
                return _out(r, "photograph",
                            "a real photograph of the thing being sold, which "
                            "beats anything generated")
        for r in pins["look"]:
            if (r.entity_key or "") in ("", ent) and r.id in usable:
                return _out(usable[r.id], "pinned_look",
                            "no photograph of this product, so the picture "
                            "pinned as the brand's look — on brand by "
                            "definition, and not a picture of this product")
        for r in heroes:
            if not (r.entity_key or ""):
                return _out(r, "brand_wide",
                            "no photograph of this product, so a brand-wide "
                            "one — weaker, and worth replacing")
    else:
        for r in proven:
            if _about(r, subject):
                return _out(r, "proven", "it has carried this subject before")
        for r in heroes:
            if _about(r, subject):
                return _out(r, "about_the_subject",
                            "an approved picture about what this piece is "
                            "about")
        # AND NOTHING ELSE. The brand-wide rung does not exist on this side of
        # the ladder: brand-wide, for an account that sells things, means a
        # product shot.

    return {"ok": False, "asset_id": "", "url": "", "rung": "none",
            "why": ("nothing approved fits this piece" + (
                "" if product_led else
                " — and a product photograph would be the wrong picture, not "
                "a lesser one")),
            "should_generate": True, "brief": brief, "subject": subject}


def _render(tenant: str, text: str, shape: str, source: bytes,
            model: str = "") -> tuple:
    """One image, using the product's own pixels when there are any to protect.
    The masked route is OpenAI's edit endpoint whatever `model` says — a
    Google model draws from references (`with_references`) or draws scenery."""
    from . import imagegen
    if source:
        res = imagegen.place_product(source, text, shape=shape, n=1)
        best = (res.get("candidates") or [{}])[0] if res.get("ok") else {}
        return res, best.get("image") or b"", \
            "product masked — its pixels are the real ones"
    res = imagegen.plate(text, shape=shape, n=1, model=model)
    return res, ((res.get("images") or [b""])[0] if res.get("ok") else b""), \
        "generated scenery — no product in frame"


def generate(tenant: str, *, commitment: dict | None = None,
             fmt: str = "email_hero", prominent: str = "",
             entity_key: str = "", claim: str = "", situation: str = "",
             audience_key: str = "", positioning: str = "",
             prompt: str = "", review: bool = True,
             boards: tuple | list = (), image_model: str = "") -> dict:
    """Make one image, check it did the job, and FILE IT so something can use it.

    JUDGED LIKE THE AD SET (owner, 2026-09-08: *"I want this on all the
    systems"*). Drawn from the product's photographs, CANDIDATES are asked
    for and each is judged against those photographs with the checklist as
    the rubric — the closest kept, redrawn with its faults named up to
    REDRAFTS times, and a near miss DROPPED and said (`_judged`, the same
    helper `batch` runs). An email hero of an almost-product is the same
    wrong picture in a different place. `image_model` is the form's choice;
    blank means the brand's default (`brand_model`), then the system's.

    DRAWN FROM THE BOARDS when the account has them (owner, 2026-09-06:
    *"accessible by the other systems as well not just ads"*): the same
    `board_inputs` the ad set uses, so an article hero and an ad frame are
    drawn from the same pictures under the same rights gate. Without a board,
    the masked-product route of before, unchanged.

    DRAFT, CHECK, REPAIR ONCE — the same shape the copy path already runs,
    deliberately, because it is the shape that works there and a second
    vocabulary for the same idea is how two halves of a system drift. The
    check is `assess`, which is a REVIEWER and not a gate: a failing image is
    still filed, still proposed, and carries its verdict so the person
    approving it is told what to look at instead of being handed a picture and
    a shrug.

    The repair is attempted once and kept only if the verdict improved. A
    second attempt that fails differently is not progress, and swapping the
    image because the newest one is newest is how a repair loop makes things
    worse quietly.
    """
    from . import kb as kbmod, media

    brief = brief_for(tenant, commitment=commitment, fmt=fmt,
                      prominent=prominent, entity_key=entity_key, claim=claim,
                      situation=situation, audience_key=audience_key,
                      positioning=positioning)
    text = prompt.strip() or brief["prompt"]

    source, source_id = b"", ""
    if entity_key:
        try:
            rows = [a for a in kbmod.assets(tenant, publishable_only=True)
                    if getattr(a, "entity_key", "") == entity_key and (a.url or "")]
            if rows:
                import httpx
                got = httpx.get(rows[0].url, timeout=60, follow_redirects=True)
                if got.status_code < 400:
                    source, source_id = got.content, rows[0].id
        except Exception:                                        # noqa: BLE001
            source, source_id = b"", ""
    if entity_key and not source:
        brief["thin"].append(
            f"no usable photograph of {entity_key!r} on file, so the frame is "
            f"scenery and the product is not in it")

    refs = board_inputs(tenant, entity_key, source_id, boards=boards)
    from_board = bool(refs["product"] or refs["look"])
    drawn = bool(refs["product"])
    # THE MODEL: the form's choice, else the brand's default, else the
    # system's — said when the brand's could not be taken.
    model, model_why = (image_model, "") if image_model else brand_model(tenant)
    if model_why:
        brief["thin"].append(model_why)
    # THE PRODUCT'S CHECKLIST AND THE JUDGE, exactly as the ad set has them.
    feats = (product_features(tenant, entity_key, refs["product"]) if drawn
             else {"ok": False, "features": [], "cached": False, "why": ""})
    checklist = list(feats.get("features") or [])
    fidelity = {"judged": 0, "kept": 0, "dropped": 0, "redrafted": 0,
                "not_the_product": 0, "why_dropped": [],
                "checklist": bool(checklist), "why": ""}

    def _draw(text_: str) -> tuple:
        """One kept picture for this text: `(res, blob, basis)`, `res["fid"]`
        the judge's verdict on it when there was one. Drawn from the
        photographs, CANDIDATES are judged and the closest kept; a near miss
        is dropped and `res["dropped"]` says so."""
        text_ = text_ + _direction_brief(refs)
        if from_board:
            got_ = _with_references(text_, brief["shape"],
                                    CANDIDATES if drawn else 1, refs,
                                    checklist=checklist, model=model)
            images_ = ([b for b in (got_.get("images") or []) if b]
                       if got_.get("ok") else [])
            basis_ = (f"drawn from the brand's own pictures — {len(refs['product'])} of "
                      f"the product, {len(refs['look'])} of the look")
            if drawn and images_:
                j = _judged(tenant, images_, text_, refs, checklist,
                            lambda t: _with_references(t, brief["shape"], PER_PROMPT,
                                                       refs, checklist=checklist,
                                                       model=model),
                            fidelity=fidelity)
                images_ = j["images"]
                if not images_:
                    why_ = (fidelity["why_dropped"][-1] if fidelity["why_dropped"]
                            else "not the product")
                    return ({"ok": False, "dropped": True,
                             "error": ("the picture drawn was NOT the product — "
                                       + why_ + " — dropped rather than filed")},
                            b"", basis_)
                got_["fid"] = j["fids"].get(id(images_[0]))
                basis_ += (f"; {fidelity['judged']} candidate(s) judged against the "
                           f"product's photographs, the closest kept"
                           if fidelity["judged"] else
                           "; fidelity was not judged"
                           + (f" — {fidelity['why']}" if fidelity["why"] else ""))
            return got_, (images_[0] if images_ else b""), basis_
        return _render(tenant, text_, brief["shape"], source, model=model)

    res, blob, basis = _draw(text)
    if not res.get("ok") or not blob:
        return {"ok": False, "error": res.get("error", "generation failed"),
                "dropped": bool(res.get("dropped")), "judged": fidelity,
                "model": model, "thin": brief["thin"]}

    verdict = assess(blob, brief, tenant) if review else {
        "ok": False, "why": "not reviewed", "failed": [], "verdicts": [],
        "overall": "", "fix": ""}
    attempts = 1

    # ONE repair, on the reviewer's own instruction, kept only if it is better.
    if verdict.get("ok") and verdict.get("failed") and verdict.get("fix"):
        again_text = (text + "\n\nThe previous attempt was rejected for: "
                      + ", ".join(verdict["failed"]) + ". " + verdict["fix"])
        res2, blob2, basis2 = _draw(again_text)
        if res2.get("ok") and blob2:
            attempts = 2
            v2 = assess(blob2, brief, tenant)
            if v2.get("ok") and len(v2.get("failed") or []) < len(verdict["failed"]):
                blob, verdict, basis, text, res = blob2, v2, basis2, again_text, res2
    fid = dict(res.get("fid") or {}) or None
    if fid:
        fidelity["kept"] = 1

    put = media.put(tenant, blob, mime="image/png", origin=GENERATED_ORIGIN)
    if not put["ok"]:
        return {"ok": False, "error": put["error"], "thin": brief["thin"]}

    said = kbmod.add_asset(
        tenant, put["url"], rights=GENERATED_RIGHTS,
        title=(f"Generated: {brief['subject'] or fmt}")[:120],
        kind="image", subject=brief["subject"][:200], source="generated",
        prompt=text[:2000], entity_key=entity_key,
        derived_from=(list(refs["pins"]) if from_board
                      else [source_id] if source_id else []),
        # WHICH MODEL DREW IT, on the picture — the same tag a frame carries.
        tags=[f"model:{model}"],
        origin=GENERATED_ORIGIN)

    asset_id = ""
    try:
        rows = [a for a in kbmod.assets(tenant, publishable_only=False)
                if (a.url or "") == put["url"]]
        asset_id = rows[0].id if rows else ""
    except Exception:                                            # noqa: BLE001
        asset_id = ""
    # THE VERDICT TRAVELS WITH THE PICTURE. Whoever approves it is the person
    # who needs it, and a review that lives only in a return value is a review
    # nobody reads.
    if asset_id:
        try:
            kbmod.set_asset_assessment(
                asset_id, {**verdict, "fidelity": fid} if fid else verdict)
        except Exception:                                        # noqa: BLE001
            pass

    return {"ok": True, "url": put["url"], "asset_id": asset_id,
            "reused": put["reused"], "basis": basis, "said": said,
            "prompt": text, "thin": brief["thin"], "subject": brief["subject"],
            "attempts": attempts, "assessment": verdict,
            # THE JUDGE'S WORD ON THIS PICTURE, and the count of what it saw.
            "model": model, "fidelity": fid, "judged": fidelity,
            "board": {"on": refs["on"], "drawn": bool(refs["product"]),
                      "product": len(refs["product"]), "look": len(refs["look"]),
                      "pins": list(refs["pins"]), "excluded": refs["excluded"],
                      "boards": list(refs["boards"]),
                      "unknown": list(refs["unknown"])},
            "review": "proposed — it cannot be used until somebody approves "
                      "it on Review · Pictures"}


#: The VISUAL axes. `ad_craft` already owns the copy axes — five angles and
#: four value levers, from Piliero's concept diversity and Hormozi's value
#: equation — and those decide what a frame ARGUES. These two decide what it
#: SHOWS, and they are here rather than there because they are properties of a
#: photograph and mean nothing to a sentence.
#:
#: The point of a grid rather than a loop: thirty re-rolls of one prompt are
#: thirty photographs of the same table. Thirty combinations are thirty
#: different arguments for the same positioning, which is what the owner asked
#: for and what a carousel is for.
MOMENTS = {
    "before": "the moment BEFORE — the problem as it is actually lived, "
              "without the product anywhere in frame",
    "during": "the moment OF USE — hands, movement, the thing happening",
    "after": "the moment AFTER — the calm on the other side of it",
}

FRAMINGS = {
    "person_led": "a person is the subject; the product is incidental or "
                  "absent",
    "product_led": "the object is the subject, shot close and honestly",
    "detail": "one detail, very close — texture, edge, finish",
    "context": "wide, the whole setting, the product small within it",
}

#: How many images per distinct prompt. Two, because `imagegen` takes n up to
#: four in ONE call and within-prompt variation is free diversity — while the
#: real diversity has to come from the grid above, which needs a call each.
PER_PROMPT = 2

#: THE SAME GRID WITH THE PRODUCT IN EVERY CELL, for a set drawn from the
#: product's own photographs. Two entries of the vocabulary above put the
#: product OUT of frame — "incidental or absent", "without the product
#: anywhere" — which was right when a generated product could only be the
#: wrong one, and is the "nameless white mug" once the model has been handed
#: the right one. No cell excludes the product here, and `before` is not
#: walked at all.
FRAMINGS_DRAWN = {
    **FRAMINGS,
    "person_led": "a person is the subject, and they are using or holding "
                  "the product — it is recognisably in their hands or in "
                  "front of them",
    "context": "wide, the whole setting, the product clearly present within it",
}
DRAWN_MOMENTS = ("during", "after")


def axes(*, angles: tuple = (), levers: tuple = (), framings: tuple = (),
         limit: int = 8, moments: tuple = ()) -> list:
    """The grid, as a list of `{angle, lever, moment, framing}`.

    Walked diagonally rather than nested, so the first four entries differ on
    EVERY axis instead of sharing an angle and differing only in framing. A
    nested loop is the reason a "20 variation" set usually contains four ideas
    and sixteen restatements: the first axis barely moves.
    """
    from . import ad_craft
    a = tuple(angles or ad_craft.UNIVERSAL_ANGLES)
    lv = tuple(levers or tuple(ad_craft.VALUE_LEVERS))
    mo = tuple(moments or MOMENTS)
    fr = tuple(framings or FRAMINGS)
    if not fr:
        return []
    # MIXED RADIX, not four independent counters. `i % len` on every axis
    # looks diagonal and is not: with four angles, four levers, three moments
    # and four framings it has period TWELVE — so a set of twenty-four is
    # twelve approaches generated twice, and `identity` is welded to
    # `dream_outcome` for ever. Each axis therefore carries the CARRY from the
    # ones before it, which is ordinary place-value counting; adding `i` on
    # top keeps every axis moving at every step, so no two neighbouring frames
    # differ in one thing only.
    la, ll, lm, lf = len(a), len(lv), len(mo), len(fr)
    out = []
    for i in range(max(1, int(limit or 8))):
        out.append({
            "angle": a[i % la],
            "lever": lv[(i + i // la) % ll],
            "moment": mo[(i + i // (la * ll)) % lm],
            "framing": fr[(i + i // (la * ll * lm)) % lf]})
    return out


def _axis_brief(cell: dict, *, drawn: bool = False) -> str:
    from . import ad_craft
    framings = FRAMINGS_DRAWN if drawn else FRAMINGS
    return (f"\n\nTHIS FRAME'S APPROACH — one of several, and it must be "
            f"visibly different from the others:\n"
            f"- angle: {ad_craft.ANGLES.get(cell['angle'], {}).get('brief', cell['angle'])}\n"
            f"- what it dramatises: {ad_craft.VALUE_LEVERS.get(cell['lever'], cell['lever'])}\n"
            f"- moment: {MOMENTS.get(cell['moment'], '')}\n"
            f"- framing: {framings.get(cell['framing'], '')}")


#: Framings that need the REAL product in the frame, and therefore cannot be
#: generated. `imagegen.plate` appends `_PLATE_RULE` — scenery only, nothing
#: that could be the wrong product — because a generated pitcher is not this
#: client's pitcher, and Canva produced four ads with four invented ones the
#: last time that was tried. So these framings generate the SCENE and
#: composite the photograph onto it, which is what `compose.product_on_scene`
#: has been able to do since it was written and has never been asked to.
NEEDS_THE_PRODUCT = ("product_led", "detail")
#: …UNLESS THE MODEL IS HANDED THE PRODUCT. With the account's board on,
#: `batch` sends the product's own photographs as image inputs and every
#: framing is drawn, this pair included — see `board_inputs`.

#: AND THE OTHER HALF, which had no name because the prohibition was global.
#: `person_led` is briefed "a person is the subject" and was then told, in the
#: same prompt, that there must be no people in the frame.
PEOPLE_ARE_THE_SUBJECT = ("person_led",)


def _judged(tenant: str, images: list, text: str, refs: dict, checklist: list,
            redraw, *, fidelity: dict) -> dict:
    """The candidates judged against the product's photographs; the closest
    kept, redrawn with its faults named, a near miss dropped and said.

    ONE JUDGE FOR EVERY SYSTEM. This was the ad set's loop, inline in
    `batch`; the email hero and the article pictures now draw through
    `generate`, and an almost-product at the top of an email is the same
    wrong picture the owner would run by mistake in an ad (2026-09-08). The
    loop moved here unchanged so the two cannot drift: `redraw(text)` is the
    caller's own draw (its shape, its people, its model), `fidelity` is the
    caller's counters, updated in place, and the return is `{"images": [the
    kept one] or [], "fids": {id(blob): verdict}, "below": the closest
    dropped attempt or None}` — `below` so a caller can SHOW what was drawn
    when the judge kept nothing (2026-09-08: a run that made nothing showed
    nothing), without ever counting it as a frame.
    """
    fids: dict = {}
    below = None
    if images:
        # JUDGED AGAINST THE PHOTOGRAPHS; THE CLOSEST IS KEPT. Four came
        # back; one is filed. A kept candidate still wrong is redrawn
        # ONCE with its differences named, and kept only if closer.
        pick_ = _closest(images, refs["product"], checklist, tenant,
                         cast=refs.get("cast") or [])
        if pick_["ok"]:
            fidelity["judged"] += pick_["judged"]
            best_b, best_v = pick_["blob"], pick_["verdict"]
            redrafted = False
            wrong = (best_v.get("match", 0) < FIDELITY_KEEP
                     and best_v.get("differences"))
            # REDRAWN WITH ITS FAULTS NAMED, up to REDRAFTS times, for any
            # of three faults: not the product, painted lettering, or
            # another product drawn into the scene. Each redraw is kept
            # only if it scores better; a lettered or product-strewn
            # redraw never replaces a clean original.
            tries = 0
            while ((wrong or best_v.get("lettering") or best_v.get("invented"))
                   and tries < REDRAFTS):
                tries += 1
                fixes = list(best_v.get("differences") or []) if wrong else []
                if best_v.get("lettering"):
                    fixes.append("REMOVE every piece of lettering, every logo and "
                                 "every button-, badge- or label-like component — "
                                 "the words are set later, by hand, as layers")
                if best_v.get("invented"):
                    fixes.append("REMOVE every invented decoration, pattern, "
                                 "ornament or design feature — the product and the "
                                 "other pieces on the table carry exactly the "
                                 "designs and patterns in the reference images, in "
                                 "the same line, and nothing more")
                again = redraw(
                    text + "\n\nTHE PREVIOUS ATTEMPT GOT THIS WRONG — CORRECT "
                           "exactly these, and change nothing else:\n"
                    + "\n".join(f"- {d}" for d in fixes))
                again_imgs = [b for b in (again.get("images") or []) if b]
                if not (again.get("ok") and again_imgs):
                    break
                pick2 = _closest(again_imgs, refs["product"], checklist, tenant,
                                 cast=refs.get("cast") or [])
                if not pick2["ok"]:
                    break
                fidelity["judged"] += pick2["judged"]
                v1, v2 = best_v, pick2["verdict"]
                if _fidelity_score(v2) > _fidelity_score(v1):
                    best_b, best_v, redrafted = pick2["blob"], v2, True
                    fidelity["redrafted"] += 1
                wrong = (best_v.get("match", 0) < FIDELITY_KEEP
                         and best_v.get("differences"))
            fidelity["dropped"] += len(images) - 1
            # NOT THE PRODUCT, NOT FILED. A near miss that survives the
            # redraws is dropped and SAID, with the difference the judge
            # named — a frame of a glass that is almost the glass is the
            # one the owner would run by mistake.
            if wrong or best_v.get("invented"):
                fidelity["not_the_product"] += 1
                why = "; ".join(list(best_v.get("differences") or [])[:2]) or (
                    "decoration was invented on the product or the pieces around it"
                    if best_v.get("invented") else "")
                if why and why[:160] not in fidelity["why_dropped"]:
                    fidelity["why_dropped"].append(why[:160])
                images = []
                below = {"blob": best_b, "verdict": best_v,
                         "candidates": pick_["judged"], "redrafted": redrafted}
            else:
                images = [best_b]
                fids[id(best_b)] = {"match": best_v.get("match", 0),
                                    "differences": list(best_v.get("differences") or []),
                                    "candidates": pick_["judged"],
                                    "redrafted": redrafted,
                                    "lettering": bool(best_v.get("lettering"))}
        else:
            # NOT JUDGED, NOT PRETENDED. The usual two are kept and the
            # set says fidelity was not judged, and why.
            fidelity["why"] = fidelity["why"] or pick_.get("why", "")
            images = images[:PER_PROMPT]
    return {"images": images, "fids": fids, "below": below}


def batch(tenant: str, *, commitment: dict | None = None,
          positioning: str = "", entity_key: str = "", audience_key: str = "",
          claim: str = "", prominent: str = "", headline: str = "",
          subline: str = "", fmt: str = "ad_frame", output_id: str = "",
          situation: str = "", plates: int = 4, review: bool = True,
          boards: tuple | list = (), image_model: str = "",
          progress=None) -> dict:
    """A set of frames for one ad, filed together under one batch id.

    `progress(text)` — when the caller hands one (`web._run_bg` does) — is
    told after every cell where the set stands, so a twenty-minute run is
    not a blank card for nineteen of them (owner, 2026-09-08).

    Owner, 2026-08-30: *"each ad will need a carousel of images - potentially
    up to 20-30 variations of different images with different ways of
    approaching the same ad test."* Twenty-four of those is `plates=12`.

    THIRTY VARIATIONS IS NOT THIRTY GENERATIONS. It is N points on the grid
    above, each generated `PER_PROMPT` times in one call. Twelve prompts at two
    images each is twenty-four frames in twelve calls, about a dollar; thirty
    separate generations would be a dollar fifty, a quarter of an hour, and
    thirty photographs of the same table.

    TWO ROUTES, CHOSEN BY THE FRAMING, because "make a picture" is two
    different jobs:

      person_led, context   the generated scene IS the frame. Nothing in it
                            claims to be a product, so nothing can be the
                            wrong one.
      product_led, detail   the generated scene is a PLATE, and the client's
                            own photograph is composited onto it with a
                            contact shadow. The product in the ad is then the
                            product, as a matter of how the file was made
                            rather than as something to check afterwards.

    AND IF THERE IS NO PHOTOGRAPH, THOSE FRAMINGS ARE DROPPED AND SAID. Not
    quietly swapped for a generated stand-in — that is the one failure this
    whole route exists to prevent, and it would be invisible in the output.

    A THIRD ROUTE, CHOSEN BY THE BOARD (owner, 2026-09-06: *"each brand
    should be able to share a visual board … from which the AI should mimic
    styling and positioning"*). With anything pinned, the product's own
    photographs and the board's owned pins go INTO the request as images,
    and every cell is drawn from them — the product-led ones included, so no
    composite, and the person-led ones included, so no nameless mug. A
    reference pin is never sent; `board_inputs` keeps it out and names it.

    EVERY FRAME IS FILED AND EVERY FRAME IS PROPOSED. The owner asked to see
    all of them and reject individually or reject the set, so nothing here
    infers approval from a sibling: the batch id exists so the review can draw
    them as one card, not so they can share one decision.

    Frames are cut at ONE shape. The other placements are cut on approval by
    `placements`, because cutting 4:5 and 9:16 of a picture nobody kept is
    exactly the storage the owner closed on 2026-08-29.
    """
    import uuid as _uuid

    from . import kb as kbmod, media, imagegen
    batch_id = _uuid.uuid4().hex
    # THE MODEL: the form's choice, else the brand's default (Brand tab),
    # else the system's — said in the note when the brand's could not be
    # taken. `batch_each` names its models outright.
    model_why = ""
    if not image_model:
        image_model, model_why = brand_model(tenant)
    # `situation` IS WHAT `_subject_of` READS FIRST. `fb00ed1` made the
    # caller send it and did not teach this function to take it, so every
    # "Make frames" from 2026-09-05 17:03 raised TypeError inside `_run_bg`
    # and the button still returned 303. The sender changed; the receiver
    # did not; the test spied on the sender and never let the receiver run.
    base = brief_for(tenant, commitment=commitment, fmt=fmt,
                     prominent=prominent, entity_key=entity_key, claim=claim,
                     audience_key=audience_key, positioning=positioning,
                     situation=situation)

    # WHICH PHOTOGRAPH, asked once. `pick` is the one ladder every system
    # uses, so the frame that carries the product carries the same one the
    # email hero would have — and `rung` says why it was that one.
    # THE CHANNEL, WITHOUT WHICH THE OUTCOME LOOP IS DEAD. `5a95333` started
    # recording ad results onto the assets that ran in them, under the `meta`
    # channel — and `pick` defaults `channel=""`, so `proven_assets` scored on
    # raw use count and never read them. A fact recorded and never read is the
    # same defect as one never recorded, wearing a commit message.
    shot = pick(tenant, commitment=commitment, fmt=fmt, entity_key=entity_key,
                channel="meta" if fmt == "ad_frame" else "",
                situation=situation,
                audience_key=audience_key, claim=claim, prominent=prominent,
                positioning=positioning)
    # A PINNED PRODUCT SHOT IS A PHOTOGRAPH OF THE PRODUCT — the one the owner
    # chose. `pinned_look` is not: it is the brand's look, and a set that
    # composited the look as if it were the product would be the wrong
    # picture with a confident file name.
    product_id = (shot.get("asset_id") or "") if not shot.get("should_generate") \
        and shot.get("rung") in ("proven", "photograph", "pinned_product") else ""

    # THE BOARD, if the account has one — its own pictures as bytes, and the
    # reference pins it was NOT allowed to send, named. Asked once per set.
    refs = board_inputs(tenant, entity_key, product_id, boards=boards)
    drawn = bool(refs["product"])
    # THE PRODUCT'S CHECKLIST, once per set: what a careful observer checks,
    # read off the photographs. It reaches the prompt and is the judge's
    # rubric — the same words on both sides of the comparison.
    feats = (product_features(tenant, entity_key, refs["product"]) if drawn
             else {"ok": False, "features": [], "cached": False, "why": ""})
    checklist = list(feats.get("features") or [])
    fidelity = {"judged": 0, "kept": 0, "dropped": 0, "redrafted": 0,
                "not_the_product": 0, "why_dropped": [], "shown_below": 0,
                "checklist": bool(checklist), "why": ""}
    framings = tuple(FRAMINGS) if (product_id or drawn) else tuple(
        f for f in FRAMINGS if f not in NEEDS_THE_PRODUCT)
    dropped = [f for f in FRAMINGS if f not in framings]

    # THE BRIEF A COMPOSITE IS JUDGED ON carries one extra criterion, because
    # only a composite can fail it. Built once, beside the plain brief.
    comp_brief = brief_for(tenant, commitment=commitment, fmt=fmt,
                           prominent=prominent, entity_key=entity_key,
                           claim=claim, audience_key=audience_key,
                           positioning=positioning, situation=situation,
                           composited=True)

    frames, errors, repeats, pasted, cells = [], [], 0, 0, 0
    attempts: list = []
    plan = list(axes(framings=framings, limit=max(1, int(plates or 4)),
                     moments=DRAWN_MOMENTS if drawn else ()))
    for cell in plan:
        cells += 1
        text = base["prompt"] + _axis_brief(cell, drawn=drawn) + _direction_brief(refs)
        needs = cell["framing"] in NEEDS_THE_PRODUCT
        # THE ROUTE. Drawn from the brand's pictures when it has the product
        # to draw from; a look-only board styles the cells that carry no
        # product; otherwise the plate-and-composite of before, unchanged.
        direct = drawn or bool(refs["look"] and not needs)
        if direct:
            res = _with_references(
                text, base["shape"], CANDIDATES if drawn else PER_PROMPT, refs,
                with_people=cell["framing"] in PEOPLE_ARE_THE_SUBJECT,
                checklist=checklist, model=image_model)
        else:
            res = _plates(text, base["shape"], PER_PROMPT, for_product=needs,
                          with_people=cell["framing"] in PEOPLE_ARE_THE_SUBJECT)
        if not res.get("ok"):
            errors.append(f"{cell['angle']}/{cell['framing']}: "
                          f"{res.get('error', 'generation failed')}")
            continue
        images = [b for b in (res.get("images") or []) if b]
        fids: dict = {}
        if drawn and images:
            j = _judged(tenant, images, text, refs, checklist,
                        lambda t: _with_references(
                            t, base["shape"], PER_PROMPT, refs,
                            with_people=cell["framing"] in PEOPLE_ARE_THE_SUBJECT,
                            checklist=checklist, model=image_model),
                        fidelity=fidelity)
            images, fids = j["images"], j["fids"]
            if j.get("below"):
                attempts.append((j["below"], cell, text))
        for blob in images:
            verdict = None
            if needs and not direct:
                got = _integrated(tenant, product_id, blob, base, comp_brief,
                                  cell, text, review=review)
                if got.get("error"):
                    errors.append(f"{cell['framing']}: {got['error']}")
                    if got.get("pasted"):
                        pasted += 1
                    continue
                blob, verdict = got["image"], got["verdict"]
            filed = _file_frame(tenant, blob, base, cell, batch_id,
                                entity_key=entity_key, prompt=text,
                                review=review, verdict=verdict,
                                output_id=output_id,
                                product_id=product_id if (needs or drawn) else "",
                                derived_from=refs["pins"] if direct else [],
                                fidelity=fids.get(id(blob)),
                                model=image_model or imagegen.MODEL)
            if not filed.get("duplicate") and not filed.get("error") and fids.get(id(blob)):
                fidelity["kept"] += 1
            if filed.get("duplicate"):
                repeats += 1
                continue
            if filed.get("error"):
                errors.append(filed["error"])
                continue
            frames.append(filed["frame"])
        if progress:
            try:
                progress(f"cell {cells} of {len(plan)} — {len(frames)} kept, "
                         f"{fidelity['not_the_product']} not the product, "
                         f"{len(errors)} failed")
            except Exception:                                    # noqa: BLE001
                pass

    # THE CLOSEST ATTEMPT OF EACH DROPPED CELL, filed under the set APART
    # from its frames (`kb.NOT_THE_PRODUCT` tag — `kb.batches` keeps them out
    # of `made` and `clean`). Owner, 2026-09-08, on a run the judge emptied:
    # *"Nothing landed back into the drafts we expected."* A near miss is
    # still not the product and is never counted as one; it is shown, with
    # its match and its named differences, so the owner can see what the
    # model drew and decide for themselves. Not assessed against the brief —
    # a picture of the wrong product does not need a second opinion.
    for b, cell_, text_ in attempts:
        v = b["verdict"]
        filed = _file_frame(
            tenant, b["blob"], base, cell_, batch_id, entity_key=entity_key,
            prompt=text_, review=False,
            verdict={"ok": False, "failed": [], "verdicts": [], "overall": "",
                     "fix": "", "why": "not reviewed — the judge found it is not the product"},
            output_id=output_id, product_id=product_id, derived_from=refs["pins"],
            fidelity={"match": v.get("match", 0),
                      "differences": list(v.get("differences") or []),
                      "candidates": b["candidates"], "redrafted": b["redrafted"],
                      "lettering": bool(v.get("lettering")),
                      "invented": bool(v.get("invented")), "below": True},
            model=image_model or imagegen.MODEL, extra_tags=[kbmod.NOT_THE_PRODUCT])
        if filed.get("frame"):
            fidelity["shown_below"] += 1

    # THREE STATES, NOT TWO. A frame the reviewer could not read is not
    # a frame that passed; counting it clean is how an outage arrives
    # looking like a good batch.
    clean = [f for f in frames if not f["failed"] and f.get("reviewed")]
    unreviewed = [f for f in frames if not f.get("reviewed")]
    # WHAT THE BOARD CONTRIBUTED, SAID — including what it was not allowed
    # to. A reference pin kept out silently is a pin the owner thinks is
    # working.
    board_said = ""
    if refs["on"]:
        board_said = (f" — drawn from {len(refs['product'])} photograph(s) of "
                      f"the product"
                      + (f", {len(refs['cast'])} of its companions "
                         f"({', '.join(refs['cast_names'][:3])})" if refs.get("cast") else "")
                      + f" and {len(refs['look'])} board pin(s)"
                      if (refs["product"] or refs["look"]) else
                      " — the board is on, but none of its pictures could be used")
        if refs["excluded"]:
            # THE FIRST SENTENCE OF THE REASON, whole. Cut at 90 characters
            # it read "not licensed for use. Generate something of our ow",
            # which the owner took for a broken sentence rather than a rule.
            board_said += (f"; {len(refs['excluded'])} pin(s) kept out of the "
                           "request: " + "; ".join(
                               str(e["why"]).split(". ")[0] for e in refs["excluded"][:3]))
    if refs["unknown"]:
        board_said += ("; no board named " + ", ".join(refs["unknown"])
                       + " — nothing was pulled from it")
    if model_why:
        board_said += f"; {model_why}"
    # WHY CELLS FAILED, SAID — and FIRST when nothing was made. Owner,
    # 2026-09-08: a Lifestyle run reported "made 0 · clean 0 — nothing was
    # generated — drawn from 0 photograph(s) … 4 board pin(s)" and nothing
    # else, while every cell's refusal sat in `errors`, which no note and
    # no surface read. A run that did nothing for no stated reason is a
    # button that looks broken; the API's own words are the reason.
    distinct: list = []
    for e in errors:
        why = str(e).split(": ", 1)[-1].strip()
        if why and why not in distinct:
            distinct.append(why)
    failed_said = ""
    if errors:
        failed_said = (f"{len(errors)} of {cells} cell(s) failed: {distinct[0][:220]}"
                       + (f"; also: {distinct[1][:120]}" if len(distinct) > 1 else ""))
    # WHAT THE JUDGE DID, SAID. "Four candidates, one kept" is a fact about
    # the set; "fidelity was not judged" is a different fact and must not
    # look like the first.
    if drawn:
        if fidelity["judged"]:
            board_said += (f"; {fidelity['judged']} candidate(s) judged against "
                           f"the product's photographs, {fidelity['kept']} kept — "
                           f"closest to the product"
                           + (f", {fidelity['redrafted']} redrawn with its "
                              f"differences named" if fidelity["redrafted"] else "")
                           + (f", {fidelity['not_the_product']} cell(s) dropped — NOT "
                              f"the product: " + "; ".join(fidelity["why_dropped"][:2])
                              + (f" (the closest attempt of each is under the set, "
                                 f"marked not the product)" if fidelity["shown_below"] else "")
                              if fidelity["not_the_product"] else "")
                           + ("" if checklist else "; no checklist could be derived"
                              + (f" ({feats.get('why')})" if feats.get("why") else "")))
        else:
            board_said += ("; fidelity was not judged"
                           + (f" — {fidelity['why']}" if fidelity["why"] else "")
                           + ", so the usual two per cell were kept unranked")
    return {"ok": bool(frames), "batch": batch_id, "frames": frames,
            "model": image_model or imagegen.MODEL,
            "made": len(frames), "clean": len(clean),
            "subject": base["subject"], "thin": base["thin"],
            "errors": errors, "product_asset": product_id,
            "shape": base["shape"],
            "board": {"on": refs["on"], "drawn": drawn,
                      "product": len(refs["product"]), "look": len(refs["look"]),
                      "pins": list(refs["pins"]), "excluded": refs["excluded"],
                      "boards": list(refs["boards"]),
                      "unknown": list(refs["unknown"])},
            "fidelity": fidelity,
            "checklist": checklist,
            # SAID, not left to be counted. A set where nineteen of twenty
            # frames failed their review is a set with a brief problem, and
            # the number is the only place that shows before somebody opens
            # twenty pictures.
            "repeats": repeats,
            "pasted": pasted,
            # THE LINE THE TYPE SHOULD SAY, carried rather than burned. The
            # caller computes it from the ad's own opening line so the
            # picture and the post argue the same thing; it now travels to
            # the person who sets it in Canva instead of into the pixels.
            "headline": headline,
            "unreviewed": len(unreviewed),
            "note": ((f"{len(clean)} of {len(frames)} passed review"
                      + (f" — {len(unreviewed)} could NOT be reviewed, so "
                         f"nothing has judged them; open those before you "
                         f"run them" if unreviewed and review else "")
                      + (f" — review was not asked for on this run"
                         if unreviewed and not review else "")
                      + (f" — {repeats} came back identical to a picture "
                         f"already on file and were not filed twice"
                         if repeats else "")
                      + (f"; {pasted} were dropped because the product still "
                         f"read as pasted on after a second plate"
                         if pasted else "")
                      + (f"; {failed_said}" if failed_said else "")
                      + board_said
                      + ". No type is set into these — open one in Canva to "
                        "add the headline"
                      + (f" (“{headline[:60]}”)" if headline else ""))
                     if frames else
                     ("nothing was generated"
                      + (f" — {failed_said}" if failed_said else "")
                      + board_said
                      + (f" — {pasted} composite(s) were dropped because the "
                         f"product read as pasted on" if pasted else ""))),
            "held_back": (
                f"no usable photograph of this product, so "
                f"{', '.join(dropped)} were not attempted — a generated "
                f"product would not be this client's product"
                if dropped else "")}


def batch_each(tenant: str, *, models: list, progress=None, **kw) -> dict:
    """One set per model, on the same brief, board and words — the owner's
    "or if to use both" (2026-09-08). Each set is a `batch` of its own, its
    frames tagged with the model, so the Pictures page shows them side by
    side; the summary says what each made. `{ok, made, clean, errors, note,
    sets: [{model, batch, made, clean, note}]}`."""
    sets, made, clean, errors = [], 0, 0, []
    names = [str(x) for x in (models or []) if str(x)]
    for i, m in enumerate(names, 1):
        # THE MODEL IN FRONT OF EVERY PROGRESS LINE, so "cell 3 of 8" says
        # whose cell it is.
        say = ((lambda text, i=i, m=m: progress(f"model {i} of {len(names)} ({m}): {text}"))
               if progress else None)
        got = batch(tenant, image_model=m, progress=say, **kw)
        # THE WHOLE NOTE. Cut at 140 characters it read "14 candidate(s)
        # judged against the product's photograp ‖" and the owner could not
        # learn that every cell had been dropped, or why (2026-09-08).
        sets.append({"model": m, "batch": got.get("batch", ""), "made": got.get("made", 0),
                     "clean": got.get("clean", 0), "note": str(got.get("note") or "")[:700]})
        made += int(got.get("made", 0) or 0)
        clean += int(got.get("clean", 0) or 0)
        errors += [f"{m}: {e}" for e in (got.get("errors") or [])]
    note = " ‖ ".join(f"{x['model']}: {x['made']} made, {x['clean']} clean — {x['note'][:600]}"
                      for x in sets) or "no model was named"
    return {"ok": made > 0, "made": made, "clean": clean, "errors": errors,
            "sets": sets, "models": [x["model"] for x in sets], "note": note}


def _composite(tenant: str, product_id: str, plate: bytes, shape: str, *,
               headline: str = "", subline: str = "") -> dict:
    """The photograph onto the plate, at the one shape this set is cut at.

    NO TYPE IS BURNED IN. Owner, 2026-09-04: *"type belongs in Canva now that
    the door works — stop burning it into frames."* `compose._draw_text` set
    the headline in DejaVu or whatever font the host happened to have, at a
    fixed position, permanently — so a frame arrived with the brand's words
    in a font the brand does not own and no way to move them. The Canva door
    (`hosting.to_canva`) is per frame and shipped, so the type is set there,
    on the picture somebody actually kept.

    `headline` and `subline` stay in the signature and are deliberately
    unused: every caller still has them, and dropping the parameters would
    move the decision into the callers rather than stating it here.
    """
    from . import compose
    fmt = _PLACEMENT.get(shape, "1:1")
    got = compose.product_on_scene(tenant, product_id, plate,
                                   headline="", subline="",
                                   formats=[fmt])
    if not got.get("ok"):
        return {"ok": False, "error": str(got.get("error") or "compositing failed")}
    return {"ok": True, "image": got["images"][fmt]}


def _integrated(tenant: str, product_id: str, plate: bytes, base: dict,
                comp_brief: dict, cell: dict, prompt: str, *,
                review: bool) -> dict:
    """Composite the photograph in, and REFUSE the frame if it reads as pasted.

    Owner, 2026-09-04, on the frames: the product looked *"pasted onto another
    image"*. It was — `compose.product_on_scene` alpha-composites the real
    cutout onto a generated plate, which is the only route that cannot be
    wrong about WHICH product it is, and pays for that with light that came
    from a different room.

    `assess` has been able to see this since it was written and its verdict
    was attached to the asset as advice — the owner's instruction is that
    INTEGRATION becomes *"a gate rather than a note"*. So it gates, and only
    here: a person-led or context frame has no composited product and cannot
    fail this, and gating those on a vision model's taste is exactly the false
    refusal `assess`'s docstring refuses to build.

    ONE RETRY, on a FRESH PLATE, because that is the half we can change. The
    product photograph is fixed and correct; what fails is the scene it was
    dropped into, and a plate lit from a different angle is a different
    answer. A second failure drops the frame and SAYS so — a set that quietly
    returns four frames instead of eight is the silent degradation this
    codebase keeps closing.
    """
    from . import compose  # noqa: F401  (product_on_scene via _composite)
    made = _composite(tenant, product_id, plate, base["shape"])
    if not made.get("ok"):
        return {"error": str(made.get("error") or "compositing failed")}
    if not review:
        return {"image": made["image"], "verdict": None}
    verdict = assess(made["image"], comp_brief, tenant)
    # A REVIEW THAT DID NOT RUN IS NOT A PASS. `assess` returns
    # {"ok": False, "why": ...} with NO `failed` key on every failure
    # path — no model, no JSON, nothing to assess — so `"integration"
    # not in []` was True and a vision outage passed every composited
    # frame. The batch then reported "N of N passed review". Not a
    # silent failure: a MISREPORTED one, which is worse.
    if verdict.get("ok") and "integration" not in (verdict.get("failed") or []):
        return {"image": made["image"], "verdict": verdict}

    again = _plates(prompt, base["shape"], 1, for_product=True)
    if again.get("ok") and (again.get("images") or []):
        retry = _composite(tenant, product_id, again["images"][0], base["shape"])
        if retry.get("ok"):
            v2 = assess(retry["image"], comp_brief, tenant)
            if v2.get("ok") and "integration" not in (v2.get("failed") or []):
                return {"image": retry["image"], "verdict": v2}
            verdict = v2
    return {"error": (f"{cell['framing']}: the product still read as pasted "
                      f"onto the scene after a second plate — "
                      f"{str(verdict.get('overall') or '')[:120]}"),
            "pasted": True}


#: `imagegen` names shapes; `compose` names Meta placements. One mapping, here,
#: rather than each caller guessing — two vocabularies for one idea is how a
#: story frame ends up cut square.
_PLACEMENT = {"square": "1:1", "portrait": "4:5", "landscape": "1:1"}


def _file_frame(tenant: str, blob: bytes, base: dict, cell: dict,
                batch_id: str, *, entity_key: str, prompt: str, review: bool,
                product_id: str = "", output_id: str = "",
                verdict: dict | None = None, model: str = "",
                derived_from: list | None = None,
                fidelity: dict | None = None,
                extra_tags: list | None = None) -> dict:
    """Store the bytes, judge them, and file the asset. One frame's whole life.

    `fidelity` is the judge's verdict against the product's photographs —
    the match, the named differences, how many candidates it beat — kept on
    the frame's record beside the brief review, and said on the card.

    `derived_from` is the board: the ids of the pictures this frame was drawn
    from, recorded on the frame so the set can say so and the outcome loop
    can one day say which pins made the frames that worked.

    THE TAGS NAMED THE GRID AND NOT THE ARGUMENT. `[angle, lever, moment,
    framing]` says where on the walk a frame came from, which is what a
    reviewer wants and not what a SHIP wants: the export lists copy variants,
    and nothing filed here said which variant a picture was made for. That
    binding lived in this function's caller's stack frame and died when it
    returned, so the owner paired twenty-four unlabelled frames by eye.
    `output:<id>` is written alongside the cell so `/admin/ad_export` can put
    each variant's pictures under its words.
    """
    from . import kb as kbmod, media
    put = media.put(tenant, blob, mime="image/png", origin=GENERATED_ORIGIN)
    if not put["ok"]:
        return {"error": put["error"]}
    # A PICTURE WE ALREADY HOLD IS NOT A NEW VARIATION. `media.put` is
    # content-addressed and `add_asset` dedupes on the URL, so two identical
    # frames become one row — and the set would then report a frame it does
    # not have, with one asset answering to two cells of the grid. Counted and
    # said instead: "24 asked for, 22 distinct" is a fact about the brief.
    if put["reused"]:
        return {"duplicate": True}
    # ALREADY JUDGED? A composited frame was assessed by the integration gate
    # against the richer brief; asking again would be a second vision call per
    # frame for a worse answer.
    if verdict is None:
        verdict = assess(blob, base, tenant) if review else {}
    if fidelity:
        verdict = {**(verdict or {}), "fidelity": dict(fidelity)}
    kbmod.add_asset(
        tenant, put["url"], rights=GENERATED_RIGHTS,
        title=f"{base['subject'] or 'ad'} · {cell['angle']}/{cell['framing']}"[:120],
        kind="image", subject=base["subject"][:200], source="generated",
        prompt=prompt[:2000], entity_key=entity_key,
        origin=GENERATED_ORIGIN, batch=batch_id,
        derived_from=list(derived_from or []),
        tags=([cell["angle"], cell["lever"], cell["moment"], cell["framing"]]
              + ([f"output:{output_id}"] if output_id else [])
              # WHICH MODEL DREW IT, on the frame — so two sets made on the
              # same brief by two models can be told apart on the card.
              + ([f"model:{model}"] if model else [])
              + [str(x) for x in (extra_tags or []) if str(x)]))
    row = next((a for a in kbmod.assets(tenant, publishable_only=False)
                if (a.url or "") == put["url"]), None)
    if row is None:
        return {"error": "the picture was stored but the asset did not file"}
    if verdict:
        try:
            kbmod.set_asset_assessment(row.id, verdict)
        except Exception:                                        # noqa: BLE001
            pass
    return {"frame": {"asset_id": row.id, "url": put["url"], "cell": cell,
                      "reused": put["reused"], "product": product_id,
                      "fidelity": dict(fidelity) if fidelity else None,
                      "failed": list(verdict.get("failed") or []),
                      # WHETHER THE JUDGE SPOKE, kept apart from what it said.
                      "reviewed": bool(verdict.get("ok")),
                      "overall": verdict.get("overall", "")}}


def placements(tenant: str, asset_id: str) -> dict:
    """The other two crops, cut once somebody has KEPT the frame.

    Meta wants 1:1 and 4:5 in feed and 9:16 in stories, and re-cropping an
    export by hand is how the story version ends up with the headline off the
    top. `compose` has cut all three since it was written and has never been
    asked to.

    CUT ON APPROVAL, not on generation. Owner, 2026-08-29: *"lets make sure we
    are only storing long term the images that have been approved."* Three
    crops of twenty-four proposals is seventy-two pictures nobody asked for;
    three crops of the two that were kept is six.

    THEY ARE NOT NEW ASSETS. They are recorded ON the frame, because a 9:16
    crop filed as its own row would be selectable by `pick` as an email hero,
    and would arrive in the review queue asking for a decision that was just
    made about the picture it was cut from.
    """
    from . import compose, kb as kbmod, media, provenance as prov

    row = next((a for a in kbmod.assets(tenant, publishable_only=False)
                if a.id == asset_id), None)
    if row is None:
        return {"ok": False, "error": "no such picture"}
    if str(row.review or "") != prov.APPROVED:
        return {"ok": False, "error": (
            "only an approved frame is cut for placement — this one is "
            f"{row.review or 'unreviewed'}")}
    blob, _mime = media.get(str(row.url or "").rsplit("/", 1)[-1])
    if not blob:
        return {"ok": False, "error": "the picture's bytes are gone"}

    # The frame already carries the product if it ever did, so this cuts the
    # FINISHED frame rather than re-running the composite — re-compositing
    # would place the product a second time.
    made = compose.crop_placements(blob, formats=["4:5", "9:16"])
    if not made.get("ok"):
        return {"ok": False, "error": str(made.get("error") or "cutting failed")}
    cut = {}
    for fmt, data in (made.get("images") or {}).items():
        put = media.put(tenant, data, mime="image/png", origin=GENERATED_ORIGIN)
        if not put["ok"]:
            return {"ok": False, "error": put["error"]}
        cut[fmt] = put["url"]
    kbmod.set_asset_placements(row.id, cut)
    return {"ok": True, "cut": cut,
            "note": f"{len(cut)} placement(s) cut from an approved frame"}


def _plates(text: str, shape: str, n: int, *, for_product: bool = False,
            with_people: bool = False) -> dict:
    """The seam every plate goes through. `for_product` asks for a scene LIT
    AND FRAMED to receive a real photograph — a parameter accepted and not
    forwarded is the two-halves defect this codebase keeps finding, so it is
    passed here and nowhere else."""
    from . import imagegen
    return imagegen.plate(text, shape=shape, n=max(1, min(4, int(n or 1))),
                          for_product=for_product, with_people=with_people)


def _with_references(text: str, shape: str, n: int, refs: dict, *,
                     with_people: bool = False, checklist: list | None = None,
                     model: str = "") -> dict:
    """The seam every board-drawn frame goes through; `_plates` says why."""
    from . import imagegen
    return imagegen.with_references(
        text, product=refs["product"], look=refs["look"], shape=shape,
        n=max(1, min(4, int(n or 1))), with_people=with_people,
        checklist=list(checklist or []), model=model,
        cast=list(refs.get("cast") or []), cast_names=list(refs.get("cast_names") or []))


# ---------------------------------------------------------------------------
# THE PRODUCT, JUDGED AGAINST ITS OWN PHOTOGRAPHS. Owner, 2026-09-07: *"the
# photos are better but they are still not recreating the product photos
# exactly. How can we improve this?"* A frame drawn from the photographs was
# filed as it came — two candidates, both kept, neither compared to what it
# was drawn from — and the prompt said "reproduce exactly" and named nothing.
# Three moves: the product's CHECKLIST (what a careful observer would check,
# derived once from the photographs) reaches the prompt and is the judge's
# rubric; every candidate is JUDGED against the photographs with the
# differences NAMED and the closest is the one kept, four asked for so there
# is a choice; a kept candidate still wrong is redrawn ONCE with its
# differences in the prompt and kept only if closer. The judge ranks; it
# never vetoes — a set with no faithful candidate still files its closest,
# and says so.
# ---------------------------------------------------------------------------

#: Candidates per drawn cell. The API returns up to four in one call; four
#: is a choice, two was a coin toss.
CANDIDATES = 4
#: Below this match the kept candidate is redrawn once with its differences.
FIDELITY_KEEP = 90
#: How many times a cell's best candidate is redrawn with its faults named —
#: not the product, painted lettering, other products in the scene — before
#: the cell is given up. Owner, 2026-09-08: an "almost" product (a glass
#: generalised to its type, a plate given an embellishment) is a different
#: product; at 85 it was filed as a near miss, and the owner saw it.
REDRAFTS = 2
#: Look pins that ride along when the product is in the request. Four
#: against four split the model's attention evenly; the product is the
#: subject, so the look yields.
LOOK_INPUTS_WITH_PRODUCT = 2

_FEATURES_PROMPT = """These are photographs of ONE product. Write the checklist a
careful observer would use to tell THIS product from a look-alike: material and
finish, form and proportions, colours, pattern, any marks, glyphs, text or
hardware, and how the parts meet. Six to ten items, each a short phrase that is
TRUE OF THE PHOTOGRAPHS — nothing inferred, nothing about the setting.
Answer in JSON only: {"features": ["…", "…"]}"""

_COMPARE_PROMPT = """The FIRST image is a generated picture. The next {k} image(s) are
photographs of the real product it was meant to show.{cast_said} Judge the
product first: is the object in the first image this exact product?

CHECKLIST — what a careful observer checks on this product:
{checklist}

Answer in JSON only:
{{"match": <0-100, 100 = indistinguishable from the photographs>,
  "differences": ["<one concrete difference the observer would notice>", …],
  "same_product": <true|false>,
  "lettering": <true|false>}}
Name only differences on the PRODUCT itself (shape, pattern, marks, colours,
proportions, finish) — not the setting, the light, or the crop. An empty
differences list means it is the product.
"ALMOST" IS NOT THE PRODUCT. A different silhouette (stem, rim, foot, handle,
facets, wall thickness, height-to-width), a different or added decoration,
pattern, embellishment or edge treatment, a different colour, material or
transparency, or a generalised version of the type ("a wine glass" where the
photographs show THIS wine glass) is a DIFFERENT product: same_product=false
and match no higher than 60, with the difference named.
"invented" is true if the picture ADDS any decoration, pattern, ornament,
embellishment, colour or design feature — to the product OR to the other
pieces of tableware on the table — that the reference images do not show, or
shows a piece in another brand's look: an invented design. Other pieces that
follow the references' designs and patterns, in the same line, are fine.
Plain incidental props (linen, food, flowers, cutlery, hands) are not judged.
"lettering" is true if the picture carries ANY rendered text, lettering,
logo, button, badge, price tag, sticker or interface-like component anywhere
— the words are set later, by hand, and any at all counts.
Answer with all five keys: match, differences, same_product, lettering and
invented."""


def _fingerprint(blobs: list) -> str:
    import hashlib
    h = hashlib.sha256()
    for b in blobs:
        h.update(hashlib.sha256(b or b"").digest())
    return h.hexdigest()[:24]


def _product_features_live(tenant: str, entity_key: str, product: list,
                           **_ignored) -> dict:
    """The product's checklist, derived ONCE from its photographs and cached
    on a Setting keyed by the photographs themselves — a changed shot
    re-derives, an unchanged one costs nothing. `{ok, features, cached, why}`.
    Descriptive, not a claim: it says what the photographs show, and it is
    never asserted to a buyer."""
    import base64 as _b64
    import json as _json
    from . import db as _db, llm
    blobs = [b for b in (product or []) if b]
    if not entity_key or not blobs:
        return {"ok": False, "features": [], "cached": False,
                "why": "no product photographs to read"}
    key = f"features:{tenant}:{entity_key}"
    fp = _fingerprint(blobs)
    with _db.SessionLocal() as s:
        row = s.get(_db.Setting, key)
        if row is not None and row.value:
            try:
                kept = _json.loads(row.value)
            except Exception:                                    # noqa: BLE001
                kept = {}
            if kept.get("fingerprint") == fp and kept.get("features"):
                return {"ok": True, "features": list(kept["features"]),
                        "cached": True, "why": ""}
    content = [{"type": "image", "source": {
        "type": "base64", "media_type": "image/png",
        "data": _b64.standard_b64encode(b).decode()}} for b in blobs[:4]]
    content.append({"type": "text", "text": _FEATURES_PROMPT})
    reply = llm.ask("creative_review", content, tenant=tenant, max_tokens=500)
    if not getattr(reply, "ok", False):
        return {"ok": False, "features": [], "cached": False,
                "why": getattr(reply, "degraded", "") or getattr(reply, "error", "")
                or "the checklist could not be derived"}
    raw = (reply.text or "").strip()
    try:
        data = _json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
    except Exception:                                            # noqa: BLE001
        return {"ok": False, "features": [], "cached": False,
                "why": "the checklist did not come back as JSON"}
    feats = [str(f).strip() for f in (data.get("features") or []) if str(f).strip()][:10]
    if not feats:
        return {"ok": False, "features": [], "cached": False,
                "why": "the checklist came back empty"}
    with _db.SessionLocal() as s:
        s.merge(_db.Setting(key=key, value=_json.dumps(
            {"features": feats, "fingerprint": fp})))
        s.commit()
    return {"ok": True, "features": feats, "cached": False, "why": ""}


product_features = _product_features_live      # replaceable, so the suite can drive every path


def _compare_product_live(candidate: bytes, product: list, features: list,
                          tenant: str = "", cast: list | None = None) -> dict:
    """One candidate against the photographs, with the checklist as the
    rubric. `{ok, match, differences, same, why}`. Ranks; never vetoes."""
    import base64 as _b64
    import json as _json
    from . import llm
    refs = [b for b in (product or []) if b][:4]
    if not candidate or not refs:
        return {"ok": False, "match": 0, "differences": [], "same": False,
                "why": "nothing to compare"}
    extra = [b for b in (cast or []) if b][:CAST_INPUTS]
    content = [{"type": "image", "source": {
        "type": "base64", "media_type": "image/png",
        "data": _b64.standard_b64encode(b).decode()}} for b in [candidate] + refs + extra]
    cast_said = (f" The {len(extra)} image(s) after those are photographs of the "
                 f"brand's OTHER products that may appear as supporting pieces."
                 if extra else "")
    content.append({"type": "text", "text": _COMPARE_PROMPT.format(
        k=len(refs), cast_said=cast_said,
        checklist="\n".join(f"- {f}" for f in (features or [])) or "- (none derived)")})
    reply = llm.ask("creative_review", content, tenant=tenant, max_tokens=500)
    if not getattr(reply, "ok", False):
        return {"ok": False, "match": 0, "differences": [], "same": False,
                "why": getattr(reply, "degraded", "") or getattr(reply, "error", "")
                or "the judge could not run"}
    raw = (reply.text or "").strip()
    try:
        data = _json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
    except Exception:                                            # noqa: BLE001
        return {"ok": False, "match": 0, "differences": [], "same": False,
                "why": "the judge did not answer in JSON"}
    try:
        match = max(0, min(100, int(data.get("match") or 0)))
    except (TypeError, ValueError):
        match = 0
    diffs = [str(d).strip() for d in (data.get("differences") or []) if str(d).strip()][:6]
    return {"ok": True, "match": match, "differences": diffs,
            "same": bool(data.get("same_product")) or (match >= FIDELITY_KEEP and not diffs),
            "lettering": bool(data.get("lettering")),
            "invented": bool(data.get("invented")), "why": ""}


compare_product = _compare_product_live        # replaceable, so the suite can drive every path


def _fidelity_score(v: dict) -> int:
    """One number to rank verdicts by: the match, minus a hundred for painted
    lettering and fifty for invented decoration — so neither fault is ever
    'a good likeness with a flaw'."""
    return (int(v.get("match", 0) or 0)
            - (100 if v.get("lettering") else 0)
            - (50 if v.get("invented") else 0))


def _closest(candidates: list, product: list, features: list, tenant: str,
             cast: list | None = None) -> dict:
    """Every candidate judged; the closest returned with its verdict.
    `{ok, blob, verdict, judged, why}` — `ok` False when the judge could not
    run, in which case nothing has been ranked and the caller must say so."""
    verdicts = []
    for blob in candidates:
        v = (compare_product(blob, product, features, tenant, cast=cast) if cast
             else compare_product(blob, product, features, tenant))
        if not v.get("ok"):
            return {"ok": False, "blob": b"", "verdict": v, "judged": 0,
                    "why": v.get("why", "")}
        verdicts.append((v, blob))
    if not verdicts:
        return {"ok": False, "blob": b"", "verdict": {}, "judged": 0, "why": "no candidates"}
    # A CLEAN CANDIDATE FIRST, then the highest match; a tie goes to the
    # first, which is the API's own first choice. Painted lettering, logos or
    # button-like components are not "a good likeness with a flaw" — they are
    # type burned into the picture where the owner wanted a layer (2026-09-07),
    # and no product match makes up for it.
    best_v, best_b = max(verdicts, key=lambda vb: (0 if vb[0].get("lettering") else 1,
                                                    0 if vb[0].get("invented") else 1,
                                                    vb[0].get("match", 0)))
    return {"ok": True, "blob": best_b, "verdict": best_v, "judged": len(verdicts), "why": ""}


#: How many pictures of each kind go into one request. The API takes sixteen;
#: four of the product and four of the look is plenty to fix a product's form
#: and a board's palette, and every extra one is upload time on a call that
#: already takes a minute.
BOARD_INPUTS = 4
#: How many of the brand's OTHER products ride along as supporting pieces —
#: only the ones the owner PINNED as the product on the chosen board.
#: Owner, 2026-09-08, after a day of companions drawn from the catalogue:
#: "all their relative proportions are off … it's almost better if we stick
#: to letting the visual boards set the reference and let the AI generate
#: the photos." A photograph of a cup and one of a plate each fill their own
#: frame; the model has no scale between them, and guesses. So companions
#: are an explicit choice on the board, and nothing is added on its own.
CAST_INPUTS = 3


def board_inputs(tenant: str, entity_key: str, product_id: str = "",
                 boards: tuple | list = ()) -> dict:
    """The brand's own pictures, as bytes, for one piece — or nothing, and why.

    THE ONE SEAM TO THE BOARDS, for every system that makes a picture: the
    ad set, the article hero, and whatever comes next. Owner, 2026-09-06:
    *"make sure this is accessible by the other systems as well not just
    ads."* A generator that reaches the boards any other way has built a
    second rights check, or none.

    THE BOARDS ARE THE SWITCH. An account with nothing pinned gets the route
    it had yesterday, because the day this shipped must not have been the day
    every account's frames quietly changed. Pin one thing and the account's
    pictures are drawn from its own: the LOOK from the `look` pins of the
    boards this run selected (all of them, unless it said), the PRODUCT from
    its photographs — the `product` pins for this item first, then every
    photograph of it on file, because a catalogue shot is a photograph of the
    product and the owner should not have to pin each one. A piece about no
    product in particular carries no product.

    A board named that does not exist is returned under `unknown` and pulled
    from not at all — never quietly widened to every board.

    RIGHTS, at the one place bytes are fetched. Every row goes through
    `kb.may_publish` — the gate `compose._guard` uses — so a reference pin is
    not fetched, not sent, and is NAMED in `excluded` with the reason. Kept
    out and said; not kept out and silent.
    """
    from . import imagegen, kb as kbmod
    every = kbmod.board(tenant)
    on = bool(every["look"] or every["product"])
    sel = kbmod.board(tenant, boards) if boards else every
    out = {"product": [], "look": [], "pins": [], "excluded": [], "on": on,
           "boards": list(sel["boards"]), "unknown": list(sel["unknown"]),
           "direction": "", "cast": [], "cast_names": []}
    if not on:
        return out
    ent = entity_key or ""
    product_rows = []
    if ent:
        product_rows = [r for r in sel["product"] if (r.entity_key or "") == ent]
        seen = {r.id for r in product_rows}
        rest = [r for r in kbmod.assets(tenant, publishable_only=True, kind="image")
                if (r.entity_key or "") == ent and r.id not in seen
                and (r.origin or "") != GENERATED_ORIGIN
                and (r.subject or "") != kbmod.LOGO]
        # `pick`'s choice first among the photographs: the one the rest of
        # the system would have used is the one the model should match most.
        rest.sort(key=lambda r: 0 if r.id == product_id else 1)
        product_rows += rest
    # THE CAST — the brand's OTHER products the owner pinned as the product
    # on the selected boards: DESIGN AND PATTERN references for the other
    # pieces on the table, never objects to reproduce at a guessed scale
    # (2026-09-08: separately photographed pieces carry no size between
    # them). Nothing is added from the catalogue on its own. Only when the
    # product itself is in the request.
    cast_rows: list = []
    if ent and product_rows:
        cast_rows = [r for r in sel["product"] if (r.entity_key or "") != ent]
        names = {}
        for e in kbmod.entities(tenant, available_only=False):
            names[str(e.key)] = str(e.name or e.key)
        for r in cast_rows[:CAST_INPUTS]:
            out["cast_names"].append(names.get(str(r.entity_key or ""), str(r.title or "")))
    # THE WORDS PATH. What the selected boards' reference pins look like,
    # read once and stored on the board; a reference pin contributes this
    # and nothing else.
    out["direction"] = kbmod.board_direction(tenant, boards)
    for role, rows in (("product", product_rows), ("cast", cast_rows), ("look", sel["look"])):
        # THE LOOK YIELDS TO THE PRODUCT. With the product in the request the
        # look pins are direction, not the subject; four of each split the
        # model's attention evenly, which is where the product's marks went.
        cap = (LOOK_INPUTS_WITH_PRODUCT if (role == "look" and product_rows)
               else CAST_INPUTS if role == "cast" else BOARD_INPUTS)
        for r in rows:
            if len(out[role]) >= cap:
                break
            ok, why = kbmod.may_publish(r.id)
            if not ok:
                out["excluded"].append({"asset_id": r.id, "role": role, "why": why})
                continue
            # A PRODUCT INPUT IS TRIMMED TO THE PRODUCT: a catalogue cutout is
            # mostly margin, and the margin is what the model was matching.
            blob, _mime = imagegen.input_image(_fetch(r.url or ""),
                                               trim=(role in ("product", "cast")))
            if not blob:
                out["excluded"].append({"asset_id": r.id, "role": role,
                                        "why": "the picture could not be fetched"})
                continue
            out[role].append(blob)
            out["pins"].append(r.id)
    out["cast_names"] = out["cast_names"][:len(out["cast"])]
    return out


def _drive_service(alias: str):
    """The seam every Drive read goes through.

    Built inline before, which meant the paging loop below could only be
    exercised against Google. `_plates` already carries this lesson for the
    image generator — a step with no seam is a step whose logic is tested by
    hoping.
    """
    from googleapiclient.discovery import build
    from . import gmail_client
    return build("drive", "v3", credentials=gmail_client.creds_for(alias),
                 cache_discovery=False)


def harvest_drive(tenant: str, *, folder: str = "", limit: int = 40) -> dict:
    """File the client's own Drive photographs into the pictures queue.

    A brand's real photography — the shoot, the lifestyle set, the founder
    portrait — sits in Drive, and the creative library only ever contained
    Shopify product shots. So an email could be imageless while a folder of
    perfectly good pictures sat one connection away (owner, 2026-08-22).

    **These land PROPOSED, not approved, and that is the point.** A Shopify
    product photo is published on the client's own storefront, which is why
    `store_sync` is auto-approved. A file in Drive has no such provenance: it
    may be a supplier's catalogue shot, a stock image, a competitor's picture
    saved for reference, or a photograph of a customer who never agreed to
    appear in an advertisement. The rights gate exists for exactly that, so
    these go to the queue for a human, and `hero_for_campaign` cannot select
    one until somebody says yes.
    """
    from . import data_tools, tenants
    t = tenants.get(tenant)
    alias = (getattr(t, "gmail_alias", "") or "").strip()
    if not alias:
        return {"ok": False, "error": f"{tenant} has no Google account wired"}
    try:
        svc = _drive_service(alias)
        q = ["trashed=false",
             "(" + " or ".join(f"mimeType='{m}'" for m in _DRIVE_IMAGE_TYPES) + ")"]
        if folder:
            q.append(f"'{folder}' in parents")
        # ONE PAGE WAS READ AND REPORTED AS THE SET. Drive returns at most
        # 100 files per call and this asked once, so a brand with 400
        # photographs in the folder was harvested down to the newest 40 and
        # the reply said `seen: 40` — a number that looks like an answer.
        # Asset scarcity was never this platform's problem; a harvest that
        # stops early and does not say so manufactures it.
        want = max(1, int(limit or 40))
        files, token = [], None
        while len(files) < want:
            resp = svc.files().list(
                q=" and ".join(q), pageSize=min(want - len(files), 100),
                orderBy="modifiedTime desc", pageToken=token,
                fields="nextPageToken,files(id,name,mimeType,webViewLink,"
                       "imageMediaMetadata/width,"
                       "imageMediaMetadata/height)").execute()
            files.extend(resp.get("files") or [])
            token = resp.get("nextPageToken")
            if not token:
                break
        # A CEILING THAT SAYS SO. `limit` is a real bound and hitting it is
        # not an error — but a caller that cannot tell "that was everything"
        # from "that was the first 40" has been given a number it will read
        # as the former.
        more = bool(token)
        files = files[:want]
    except Exception as exc:                                     # noqa: BLE001
        return {"ok": False,
                "error": f"Drive not readable for {alias} ({exc.__class__.__name__})"}

    # WHICH PRODUCT IS THIS A PICTURE OF? A filename usually says — "firenze
    # -set-table.jpg", "Portofino pitcher hero.png" — and an approver should
    # be shown that guess rather than made to type it. It is a RECOMMENDATION:
    # entity-scoped assets are preferred as heroes for that product, so a
    # wrong guess would put the wrong photograph on the wrong email. The
    # suggestion rides on the row for review; nothing acts on it unsupervised.
    prods = [(e.key, (e.name or "").lower()) for e in
             kb.entities(tenant, available_only=False) if (e.type or "") != "collection"]

    def _guess(name: str) -> str:
        low = re.sub(r"[^a-z0-9]+", " ", (name or "").lower())
        best, score = "", 0
        for key, pname in prods:
            words = [w for w in re.split(r"[^a-z0-9]+", pname) if len(w) > 3]
            hits = sum(1 for w in words if w in low)
            if key.replace("-", " ") in low:
                hits += 2
            if hits > score:
                best, score = key, hits
        return best if score >= 1 else ""

    filed, skipped, guessed = 0, 0, 0
    for f in files:
        meta = f.get("imageMediaMetadata") or {}
        # A hero is 1200 wide. Anything under 600 is a thumbnail, an icon or a
        # screenshot, and filing it only makes the queue longer.
        if int(meta.get("width") or 0) and int(meta["width"]) < 600:
            skipped += 1
            continue
        hit = _guess(f.get("name", ""))
        said = kb.add_asset(
            tenant, f"https://drive.google.com/uc?id={f['id']}",
            rights=kb.REFERENCE, title=f.get("name", "")[:160], kind="image",
            subject="photo", source=f.get("webViewLink", "") or "Google Drive",
            entity_key=hit, origin="drive_sync")
        if str(said).startswith("Filed"):
            filed += 1
            guessed += 1 if hit else 0
    return {"ok": True, "seen": len(files), "filed": filed,
            "skipped_small": skipped, "matched_to_a_product": guessed,
            "more_in_drive": more,
            "note": ("filed as REFERENCE and awaiting review — Drive carries "
                     "no proof of who owns a picture, so each needs 'Approve "
                     "for use' in the pictures queue before an email can "
                     "select it. Where the filename named a product, that "
                     "product is suggested on the row; check it before "
                     "approving, since a wrong match puts the wrong "
                     "photograph on that product's emails."
                     + (f" There are MORE than {len(files)} pictures in this "
                        f"folder — this read the newest {len(files)}; raise "
                        f"the limit to take more."
                        if more else ""))}
