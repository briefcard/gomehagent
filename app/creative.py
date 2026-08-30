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
              audience_key: str = "", positioning: str = "") -> dict:
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

    names = ("on_subject", "claim_safe", "no_text", "craft") + tuple(
        k for k in spec["extra"] if k not in ("on_subject",))
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
