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
                      title: str = "", draft_if_missing: bool = False) -> dict:
    """The hero image for one campaign email, or the governed path to one.

    Returns one of:
      {ok, basis: "approved_asset", image: {url, alt}, asset_id}
      {ok, basis: "drafted_in_canva", image: None, drafted: {...}, note}
      {ok, basis: "none", image: None, why}   — absence, named
    """
    ordered = list(dict.fromkeys(k for k in (entity_keys or []) if k))
    ents = set(ordered)
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
                              "alt": pick.title or segment_key or ""}}

    if not draft_if_missing:
        return {"ok": True, "basis": "none", "image": None,
                "why": ("no approved, owned photograph fits this campaign "
                        "(entity-scoped or brand-wide) — approve one in the "
                        "pictures queue, or pass draft_visual to have a "
                        "bespoke Canva draft created for review.")}

    from . import canva, credentials as cred
    if not (cred.resolve(tenant, "canva") or {}).get("secret"):
        return {"ok": True, "basis": "none", "image": None,
                "why": ("no approved photograph fits, and no Canva is "
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
GENERATED_RIGHTS = "owned"
GENERATED_ORIGIN = "generated"


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
    "claim_safe": "Does it show anything that would contradict, or imply "
                  "more than, the claim quoted below?",
    "no_text": "Is there any text, lettering, watermark or logo in the "
               "image? Any at all counts as a failure.",
    "audience_fit": "Would the audience described below recognise "
                    "themselves, or the moment they are in?",
    "craft": "Does it look like a photograph somebody was paid to take, or "
             "like generic stock?",
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
                   "with the scene's other shadows, edges that belong? Or "
                   "does it read as cut out and pasted on? Say FAIL if a "
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

    parts.append("Photographic and real. NO text, lettering, watermark or "
                 "logo of any kind. Nothing that reads as a stock photograph.")

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

    names = ("on_subject", "claim_safe", "no_text", "craft") + tuple(
        k for k in spec["extra"] if k not in ("on_subject",)) + (
        ("integration",) if composited else ())
    return {"prompt": " ".join(parts), "subject": subject, "fmt": fmt,
            "shape": spec["shape"], "palette": palette, "thin": thin,
            "criteria": [{"key": k, "ask": CRITERIA[k]} for k in dict.fromkeys(names)],
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
         prominent: str = "", positioning: str = "", channel: str = "") -> dict:
    """The best picture this account already has for this piece, or the brief
    to make one.

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
    brief = brief_for(tenant, commitment=commitment, fmt=fmt,
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
        for r in heroes:
            if (r.entity_key or "") == ent and ent:
                return _out(r, "photograph",
                            "a real photograph of the thing being sold, which "
                            "beats anything generated")
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


def _render(tenant: str, text: str, shape: str, source: bytes) -> tuple:
    """One image, using the product's own pixels when there are any to protect."""
    from . import imagegen
    if source:
        res = imagegen.place_product(source, text, shape=shape, n=1)
        best = (res.get("candidates") or [{}])[0] if res.get("ok") else {}
        return res, best.get("image") or b"", \
            "product masked — its pixels are the real ones"
    res = imagegen.plate(text, shape=shape, n=1)
    return res, ((res.get("images") or [b""])[0] if res.get("ok") else b""), \
        "generated scenery — no product in frame"


def generate(tenant: str, *, commitment: dict | None = None,
             fmt: str = "email_hero", prominent: str = "",
             entity_key: str = "", claim: str = "", situation: str = "",
             audience_key: str = "", positioning: str = "",
             prompt: str = "", review: bool = True) -> dict:
    """Make one image, check it did the job, and FILE IT so something can use it.

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

    res, blob, basis = _render(tenant, text, brief["shape"], source)
    if not res.get("ok") or not blob:
        return {"ok": False, "error": res.get("error", "generation failed"),
                "thin": brief["thin"]}

    verdict = assess(blob, brief, tenant) if review else {
        "ok": False, "why": "not reviewed", "failed": [], "verdicts": [],
        "overall": "", "fix": ""}
    attempts = 1

    # ONE repair, on the reviewer's own instruction, kept only if it is better.
    if verdict.get("ok") and verdict.get("failed") and verdict.get("fix"):
        again_text = (text + "\n\nThe previous attempt was rejected for: "
                      + ", ".join(verdict["failed"]) + ". " + verdict["fix"])
        res2, blob2, basis2 = _render(tenant, again_text, brief["shape"], source)
        if res2.get("ok") and blob2:
            attempts = 2
            v2 = assess(blob2, brief, tenant)
            if v2.get("ok") and len(v2.get("failed") or []) < len(verdict["failed"]):
                blob, verdict, basis, text = blob2, v2, basis2, again_text

    put = media.put(tenant, blob, mime="image/png", origin=GENERATED_ORIGIN)
    if not put["ok"]:
        return {"ok": False, "error": put["error"], "thin": brief["thin"]}

    said = kbmod.add_asset(
        tenant, put["url"], rights=GENERATED_RIGHTS,
        title=(f"Generated: {brief['subject'] or fmt}")[:120],
        kind="image", subject=brief["subject"][:200], source="generated",
        prompt=text[:2000], entity_key=entity_key,
        derived_from=[source_id] if source_id else [],
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
            kbmod.set_asset_assessment(asset_id, verdict)
        except Exception:                                        # noqa: BLE001
            pass

    return {"ok": True, "url": put["url"], "asset_id": asset_id,
            "reused": put["reused"], "basis": basis, "said": said,
            "prompt": text, "thin": brief["thin"], "subject": brief["subject"],
            "attempts": attempts, "assessment": verdict,
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


def axes(*, angles: tuple = (), levers: tuple = (), framings: tuple = (),
         limit: int = 8) -> list:
    """The grid, as a list of `{angle, lever, moment, framing}`.

    Walked diagonally rather than nested, so the first four entries differ on
    EVERY axis instead of sharing an angle and differing only in framing. A
    nested loop is the reason a "20 variation" set usually contains four ideas
    and sixteen restatements: the first axis barely moves.
    """
    from . import ad_craft
    a = tuple(angles or ad_craft.UNIVERSAL_ANGLES)
    lv = tuple(levers or tuple(ad_craft.VALUE_LEVERS))
    mo = tuple(MOMENTS)
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


def _axis_brief(cell: dict) -> str:
    from . import ad_craft
    return (f"\n\nTHIS FRAME'S APPROACH — one of several, and it must be "
            f"visibly different from the others:\n"
            f"- angle: {ad_craft.ANGLES.get(cell['angle'], {}).get('brief', cell['angle'])}\n"
            f"- what it dramatises: {ad_craft.VALUE_LEVERS.get(cell['lever'], cell['lever'])}\n"
            f"- moment: {MOMENTS.get(cell['moment'], '')}\n"
            f"- framing: {FRAMINGS.get(cell['framing'], '')}")


#: Framings that need the REAL product in the frame, and therefore cannot be
#: generated. `imagegen.plate` appends `_PLATE_RULE` — scenery only, nothing
#: that could be the wrong product — because a generated pitcher is not this
#: client's pitcher, and Canva produced four ads with four invented ones the
#: last time that was tried. So these framings generate the SCENE and
#: composite the photograph onto it, which is what `compose.product_on_scene`
#: has been able to do since it was written and has never been asked to.
NEEDS_THE_PRODUCT = ("product_led", "detail")


def batch(tenant: str, *, commitment: dict | None = None,
          positioning: str = "", entity_key: str = "", audience_key: str = "",
          claim: str = "", prominent: str = "", headline: str = "",
          subline: str = "", fmt: str = "ad_frame", output_id: str = "",
          plates: int = 4, review: bool = True) -> dict:
    """A set of frames for one ad, filed together under one batch id.

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

    EVERY FRAME IS FILED AND EVERY FRAME IS PROPOSED. The owner asked to see
    all of them and reject individually or reject the set, so nothing here
    infers approval from a sibling: the batch id exists so the review can draw
    them as one card, not so they can share one decision.

    Frames are cut at ONE shape. The other placements are cut on approval by
    `placements`, because cutting 4:5 and 9:16 of a picture nobody kept is
    exactly the storage the owner closed on 2026-08-29.
    """
    import uuid as _uuid

    from . import kb as kbmod, media
    batch_id = _uuid.uuid4().hex
    base = brief_for(tenant, commitment=commitment, fmt=fmt,
                     prominent=prominent, entity_key=entity_key, claim=claim,
                     audience_key=audience_key, positioning=positioning)

    # WHICH PHOTOGRAPH, asked once. `pick` is the one ladder every system
    # uses, so the frame that carries the product carries the same one the
    # email hero would have — and `rung` says why it was that one.
    shot = pick(tenant, commitment=commitment, fmt=fmt, entity_key=entity_key,
                audience_key=audience_key, claim=claim, prominent=prominent,
                positioning=positioning)
    product_id = (shot.get("asset_id") or "") if not shot.get("should_generate") \
        and shot.get("rung") in ("proven", "photograph") else ""

    framings = tuple(FRAMINGS) if product_id else tuple(
        f for f in FRAMINGS if f not in NEEDS_THE_PRODUCT)
    dropped = [f for f in FRAMINGS if f not in framings]

    # THE BRIEF A COMPOSITE IS JUDGED ON carries one extra criterion, because
    # only a composite can fail it. Built once, beside the plain brief.
    comp_brief = brief_for(tenant, commitment=commitment, fmt=fmt,
                           prominent=prominent, entity_key=entity_key,
                           claim=claim, audience_key=audience_key,
                           positioning=positioning, composited=True)

    frames, errors, repeats, pasted = [], [], 0, 0
    for cell in axes(framings=framings, limit=max(1, int(plates or 4))):
        text = base["prompt"] + _axis_brief(cell)
        needs = cell["framing"] in NEEDS_THE_PRODUCT
        res = _plates(text, base["shape"], PER_PROMPT, for_product=needs)
        if not res.get("ok"):
            errors.append(f"{cell['angle']}/{cell['framing']}: "
                          f"{res.get('error', 'generation failed')}")
            continue
        for blob in res.get("images") or []:
            if not blob:
                continue
            verdict = None
            if needs:
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
                                product_id=product_id if needs else "")
            if filed.get("duplicate"):
                repeats += 1
                continue
            if filed.get("error"):
                errors.append(filed["error"])
                continue
            frames.append(filed["frame"])

    # THREE STATES, NOT TWO. A frame the reviewer could not read is not
    # a frame that passed; counting it clean is how an outage arrives
    # looking like a good batch.
    clean = [f for f in frames if not f["failed"] and f.get("reviewed")]
    unreviewed = [f for f in frames if not f.get("reviewed")]
    return {"ok": bool(frames), "batch": batch_id, "frames": frames,
            "made": len(frames), "clean": len(clean),
            "subject": base["subject"], "thin": base["thin"],
            "errors": errors, "product_asset": product_id,
            "shape": base["shape"],
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
                      + ". No type is set into these — open one in Canva to "
                        "add the headline"
                      + (f" (“{headline[:60]}”)" if headline else ""))
                     if frames else
                     ("nothing was generated"
                      + (f" — {pasted} composite(s) were dropped because the "
                         f"product read as pasted on" if pasted else ""))),
            "held_back": (
                f"no usable photograph of this product, so "
                f"{', '.join(dropped)} were not attempted — a generated "
                f"product would not be this client's product"
                if dropped else "")}


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
                verdict: dict | None = None) -> dict:
    """Store the bytes, judge them, and file the asset. One frame's whole life.

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
    kbmod.add_asset(
        tenant, put["url"], rights=GENERATED_RIGHTS,
        title=f"{base['subject'] or 'ad'} · {cell['angle']}/{cell['framing']}"[:120],
        kind="image", subject=base["subject"][:200], source="generated",
        prompt=prompt[:2000], entity_key=entity_key,
        origin=GENERATED_ORIGIN, batch=batch_id,
        tags=([cell["angle"], cell["lever"], cell["moment"], cell["framing"]]
              + ([f"output:{output_id}"] if output_id else [])))
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


def _plates(text: str, shape: str, n: int, *, for_product: bool = False) -> dict:
    """The seam every plate goes through. `for_product` asks for a scene LIT
    AND FRAMED to receive a real photograph — a parameter accepted and not
    forwarded is the two-halves defect this codebase keeps finding, so it is
    passed here and nowhere else."""
    from . import imagegen
    return imagegen.plate(text, shape=shape, n=max(1, min(4, int(n or 1))),
                          for_product=for_product)


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
        from googleapiclient.discovery import build
        from . import gmail_client
        svc = build("drive", "v3", credentials=gmail_client.creds_for(alias),
                    cache_discovery=False)
        q = ["trashed=false",
             "(" + " or ".join(f"mimeType='{m}'" for m in _DRIVE_IMAGE_TYPES) + ")"]
        if folder:
            q.append(f"'{folder}' in parents")
        resp = svc.files().list(
            q=" and ".join(q), pageSize=min(int(limit or 40), 100),
            orderBy="modifiedTime desc",
            fields="files(id,name,mimeType,webViewLink,imageMediaMetadata/width,"
                   "imageMediaMetadata/height)").execute()
        files = resp.get("files") or []
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
            "note": ("filed as REFERENCE and awaiting review — Drive carries "
                     "no proof of who owns a picture, so each needs 'Approve "
                     "for use' in the pictures queue before an email can "
                     "select it. Where the filename named a product, that "
                     "product is suggested on the row; check it before "
                     "approving, since a wrong match puts the wrong "
                     "photograph on that product's emails.")}
