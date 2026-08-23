"""One artifact, one subject — checked in code, at the one door everything exits.

The failure this exists to stop, in the owner's words (2026-08-22): an email
whose hero photograph was a tablecloth, whose subject line and body were about
shatterproof glasses, and whose product card was a pitcher bundle — with the
brand's Four Seasons placement asserted twice and "designed in Milan" asserted
twice. Nothing in it was false. Every part was individually grounded. It was
still not client-facing, because the parts did not agree with each other.

That is a class of defect the banned-claims validator cannot see, and not
because it is weak: `validator.check` reads a STRING. The hero image, the
product cards and the citations are not in that string, so no rule written
there could ever have caught a wrong picture. The gap is structural, so the
fix is structural.

THE CONTRACT
------------
1. A COMMITMENT is declared BEFORE any selector runs — what this artifact is
   about, who it is for, what it asks. It is typed by referent, because half
   the systems here have no product: a reply's subject is the question asked,
   an SEO rewrite's is a product plus a query intent, a report's is a period.
2. NO SELECTOR MAY RUN BEFORE THE COMMITMENT IS FINAL. The tablecloth was
   picked by code that ran fifty lines before the drafter said what the email
   was about; a selector that runs early cannot cohere by luck.
3. EVERY PART TRACES TO THE COMMITMENT, or is marked background and stays
   inside a budget. Background is the brand-wide material — true of the
   company, not of the subject — which is exactly what stuffed that email.

WHY IT LIVES HERE AND NOT IN THE EMAIL CODE
-------------------------------------------
The check is channel-independent in FORM. A reply has no images, so the image
clause is vacuous and the same function still catches "the customer asked about
shipping and the reply also pitched the collection". Writing it per-skill would
mean writing it five times and getting a sixth system wrong.

NO MODEL CALL IN THIS FILE, for the same reason `validator.py` forbids one: a
model checking a model can be wrong in the same direction, and nothing notices.

WHAT THIS IS NOT
----------------
It is not a taste check and it does not reword. Like the validator it names a
failure and the fix; unlike the validator a coherence failure is a QUALITY
failure, not legal exposure, and `skill.emit` files it distinguishably so the
knowledge-base backlog is not inflated with problems that no amount of
authoring would fix.
"""
from __future__ import annotations

import re

#: The referent kinds a commitment may have. The list is deliberately short and
#: deliberately not "entity or other": a new system that fits none of these is
#: telling you something about itself, and should be argued about rather than
#: quietly filed under a catch-all.
KINDS = {
    "entity":    "one product, service or thing in the catalogue",
    "situation": "one question or circumstance a person is in",
    "topic":     "one subject a piece of content is about",
    "audience":  "one cohort, where the cohort itself is the subject",
    "period":    "one span of time",
    # The declared escape. A month report that covers one product is BROKEN,
    # so single-subject is the wrong check for it — and forcing reports through
    # the wrong gate is how a gate gets weakened for everyone or bypassed
    # entirely. In survey mode the check INVERTS: multiplicity is expected and
    # what matters is that nothing is said twice.
    "survey":    "many subjects on purpose — a report, a digest, a round-up",
}

#: How many BACKGROUND claims — true of the brand, not of the subject — may be
#: used as proof in one artifact. One is a credential; three is a company
#: profile wearing a product email's clothes.
BACKGROUND_BUDGET = 1

#: Below this many words, `subject_absent` advises rather than blocks — a stem
#: match over a label needs enough text to be trustworthy.
SUBJECT_MATCH_MIN_WORDS = 40

_STOP = {
    "the", "and", "for", "with", "from", "this", "that", "they", "their",
    "have", "has", "was", "were", "are", "our", "your", "its", "it",
    "designed", "made", "set", "sets", "new", "one", "two", "all", "more",
    "collection", "collections", "product", "products",
}


def commit(kind: str, key: str = "", *, label: str = "", audience: str = "",
           action: str = "", also: list | None = None,
           expects: list | None = None, proof_scopes: list | None = None) -> dict:
    """Declare what one artifact is about, before anything is selected.

    `also` is the COMPANION set — the other keys this artifact may legitimately
    feature, named at commit time rather than discovered at render time. A
    campaign email may show three products; what it may not do is show three
    products nobody decided on. That distinction is the whole point: the set
    was never wrong in the failing email, it simply was never committed, so it
    drifted between the four selectors that each read it separately.

    `expects` is survey-mode only — the things a round-up is supposed to cover,
    so the inverted check has something to measure completeness against.

    `proof_scopes` is which entity keys' claims are legitimately ABOUT this
    subject, and it is deliberately separate from `also`. A claim filed against
    a GROUP — "every Aqua piece is acrylic" — is true of each member, which is
    why `kb.claims` walks the ancestor chain; but the group is not a thing that
    may be featured on a card. Folding ancestry into `also` would have made
    every collection featurable as a product. Defaults to the subject and its
    companions, so a caller that knows of no groups need not think about it.
    """
    kind = (kind or "").strip().lower()
    return {"kind": kind if kind in KINDS else "",
            "key": (key or "").strip(),
            "label": (label or key or "").strip(),
            "audience": (audience or "").strip(),
            "action": (action or "").strip(),
            "also": [k for k in (also or []) if k],
            "expects": [e for e in (expects or []) if e],
            "proof_scopes": [k for k in (proof_scopes or []) if k]}


def parts(*, text: str = "", prominent: str = "", images: list | None = None,
          items: list | None = None, claims: list | None = None) -> dict:
    """The artifact as its PARTS, which is what makes it checkable.

    `prominent` is whatever a person reads before deciding to keep reading — a
    subject line and headline for an email, a meta title for a page, the first
    line of a reply. It is separated from the body because a subject line that
    promises a different thing from the body is the single most expensive
    incoherence: it is the part that earns the open, and the reader is already
    annoyed by the time the body corrects it.

    `images` entries carry `subject_key` — WHICH thing the picture is of — and
    `basis`, how it was chosen. An image with no `subject_key` is not assumed
    innocent; it is reported, because "we could not tell what this is a picture
    of" is the state that shipped a tablecloth.
    """
    return {"text": str(text or ""), "prominent": str(prominent or ""),
            "images": list(images or []), "items": list(items or []),
            "claims": list(claims or [])}


def _distinctive(claim_text: str, brand: str = "") -> list[str]:
    """The phrases that make one claim recognisable when it is restated.

    Anchored on the CLAIM rather than on the copy, and that is the load-bearing
    choice. Scanning the copy for repeated capitalised phrases finds the brand's
    own name in every paragraph and calls it a defect. Scanning it for phrases
    that came from a specific piece of proof finds "the Four Seasons" twice and
    can say WHICH claim was spent twice — which is a finding somebody can act
    on, rather than a complaint about repetition in general.
    """
    text = str(claim_text or "")
    brand_words = {w.lower() for w in re.findall(r"[A-Za-z]+", brand or "")}
    out: list[str] = []
    # Proper-noun runs: "Four Seasons", "Ritz-Carlton Yacht Collection", "Milan".
    for m in re.finditer(r"\b([A-Z][\w&'’-]*(?:\s+[A-Z][\w&'’-]*){0,3})", text):
        phrase = m.group(1).strip()
        words = [w for w in re.findall(r"[A-Za-z]+", phrase)]
        if not words:
            continue
        # A single word that is also the brand, a stop word, or too short is
        # not evidence of anything.
        if len(words) == 1:
            w = words[0].lower()
            if w in _STOP or w in brand_words or len(w) < 5:
                continue
        elif all(w.lower() in brand_words for w in words):
            continue
        out.append(phrase)
    # Figures carry proof too — "90 days", "6 glasses" — and a number restated
    # is the same spend as a name restated.
    out += [m.group(0) for m in re.finditer(r"\b\d[\d.,]*\s*%?\b", text)
            if len(m.group(0)) > 1]
    seen, uniq = set(), []
    for p in out:
        k = p.lower()
        if k not in seen:
            seen.add(k)
            uniq.append(p)
    return uniq[:6]


def _words(s: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9']+", str(s or ""))


#: Consecutive content words from a claim that, appearing twice, mean the proof
#: was spent twice. Three is the shortest run that is not a coincidence.
RESTATED_RUN = 3


def _stems(text: str) -> list[str]:
    """Content words reduced to stems, in order.

    Proper nouns and figures catch a proof restated by NAME — "the Four
    Seasons" twice, "Milan" twice. They cannot catch it restated in ordinary
    words: "pours without dripping … it really does pour without dripping" is
    the same proof spent twice and every word of it is lowercase. Comparing
    stem SEQUENCES catches that, and stemming is what makes "pours" and "pour"
    the same spend.
    """
    out = []
    for w in re.findall(r"[A-Za-z]+", str(text or "")):
        if len(w) < 4 or w.lower() in _STOP:
            continue
        out.append(w.lower()[:max(4, len(w) - 2)])
    return out


def _restated(claim_text: str, artifact_text: str) -> str:
    """The run of the claim's own words that this artifact says twice, or ""."""
    claim = _stems(claim_text)
    body = _stems(artifact_text)
    if len(claim) < RESTATED_RUN or len(body) < RESTATED_RUN * 2:
        return ""
    for i in range(len(claim) - RESTATED_RUN + 1):
        window = claim[i:i + RESTATED_RUN]
        hits = sum(1 for j in range(len(body) - RESTATED_RUN + 1)
                   if body[j:j + RESTATED_RUN] == window)
        if hits > 1:
            return " ".join(window)
    return ""


def _count(text: str, phrase: str) -> int:
    return len(re.findall(r"(?<![\w-])" + re.escape(phrase) + r"(?![\w-])",
                          text, flags=re.IGNORECASE))


def _mentions(text: str, label: str) -> bool:
    """Is this label spoken about anywhere in the text?

    STEMMED, not exact, and that is not laxness — it is the difference between
    a safety net and a tripwire. Matching whole words, a product called "GLP-1
    Support" was judged absent from a paragraph reading "Supports natural GLP-1
    production", and a perfectly good email was blocked over a plural. This
    check exists to catch an artifact that LOST its subject somewhere between
    the plan and the page; the precise checks — the picture, the cards, the
    proof — are the ones that carry the weight, and they match on keys.
    """
    toks = [w for w in re.findall(r"[A-Za-z]{4,}", str(label or ""))
            if w.lower() not in _STOP]
    if not toks:
        return True                     # nothing to look for is not an absence
    for t in toks:
        stem = t[:max(4, len(t) - 2)]
        if re.search(r"(?<![\w-])" + re.escape(stem) + r"\w*", text,
                     flags=re.IGNORECASE):
            return True
    return False


def review(commitment: dict, artifact: dict, *,
           brand_name: str = "",
           background_budget: int = BACKGROUND_BUDGET) -> list[dict]:
    """Findings for one artifact against its commitment. `[]` means it coheres.

    Every finding carries `severity`, `rule`, `detail` and `fix` — the same
    shape `validator.check` and `email_craft.review` return, so `skill.emit`
    can hand them all to the same repair loop without a translation layer.
    """
    c = commitment or {}
    kind = str(c.get("kind") or "")
    a = artifact or {}
    text = str(a.get("text") or "")
    prominent = str(a.get("prominent") or "")
    # NEVER COUNT THE SAME WORDS TWICE. `whole` is what the repetition rules
    # read, so a caller that passes one string as BOTH — which is the natural
    # thing to do for an artifact that is all headline, like a meta
    # description — made every phrase in it look asserted twice and blocked a
    # perfectly good rewrite. Concatenating is only correct when the two parts
    # are genuinely different text.
    whole = text if prominent and prominent.strip() in text else \
        f"{prominent}\n{text}".strip()
    out: list[dict] = []

    def add(sev, rule, detail, fix):
        out.append({"severity": sev, "rule": rule, "detail": detail, "fix": fix})

    # --- the commitment itself --------------------------------------------
    if not kind:
        # Fails closed, exactly as the validator does with a missing ban list.
        # "No commitment" must never read as "coheres" — that is the state the
        # whole system was in when the tablecloth shipped.
        add("block", "no_commitment",
            "this artifact was produced without declaring what it is about",
            "call coherence.commit() before selecting anything, and pass the "
            "result to emit(commitment=…)")
        return out

    if kind == "survey":
        return _survey(c, a, out, add)

    # WHAT THE PARTS MUST AGREE WITH. For an entity commitment that is the
    # subject and its declared companions. For everything else — an email
    # committed only to an audience, a reply committed to a question — there is
    # no entity subject to be off, so the parts are held to agreeing with EACH
    # OTHER instead: a hero of one product over a card for a different one is
    # incoherent whether or not anybody declared a subject.
    item_keys = {str(i.get("key") or "") for i in (a.get("items") or [])
                 if i.get("key")}
    if kind == "entity":
        committed = {k for k in ([c.get("key")] + list(c.get("also") or [])) if k}
    else:
        committed = set(item_keys)

    # --- the subject is actually present ----------------------------------
    #
    # An artifact that commits to a subject and never mentions it is not a
    # coherent artifact about something else; it is an artifact that lost its
    # subject somewhere between the plan and the page.
    label = str(c.get("label") or "")
    if label and kind in ("entity", "topic"):
        if not _mentions(whole, label):
            # SEVERITY FOLLOWS HOW RELIABLE THE MATCH CAN BE. This is a coarse
            # stem match over the label, and its false-positive rate scales
            # inversely with length: across an email it is near-certain to find
            # the subject if the subject is there, but an ad is two sentences
            # and may name the thing only by what it does. Destroying a short
            # artifact on a weak signal reproduces the exact failure of
            # withholding a draft "for its own good" (DEFECTS §2.79), so below
            # the threshold it advises instead.
            add("block" if len(_words(whole)) >= SUBJECT_MATCH_MIN_WORDS
                else "nudge", "subject_absent",
                f"this was committed to {label!r} and the copy never mentions it",
                "write about the committed subject, or commit to what was "
                "actually written")

    # --- what the reader sees first ---------------------------------------
    if prominent and label and kind == "entity":
        if not _mentions(prominent, label) and not any(
                _mentions(prominent, str(i.get("name") or ""))
                for i in (a.get("items") or [])):
            add("nudge", "prominent_off_subject",
                f"the subject line and headline never name {label!r} or a "
                f"featured item",
                "say what it is about in the part that earns the open")

    # --- the picture is of the thing --------------------------------------
    for img in (a.get("images") or []):
        key = str(img.get("subject_key") or "")
        basis = str(img.get("basis") or "")
        where = str(img.get("alt") or img.get("url") or "an image")[:60]
        if not key:
            add("block", "image_unattributed",
                f"the image ({where}) is not attributed to any subject, so "
                f"nothing can tell what it is a picture of",
                "carry subject_key on every image, or do not place it")
        elif key == "brand-wide":
            if not basis:
                add("nudge", "image_brand_wide",
                    f"a brand-wide photograph ({where}) is standing in for "
                    f"the subject",
                    "say why a brand image was chosen, or approve a "
                    "photograph of the subject itself")
        elif committed and key not in committed:
            add("block", "image_off_subject",
                f"the image ({where}) is of {key!r}, which this artifact is "
                f"not about",
                f"use a photograph of {c.get('key') or 'the subject'}, or "
                f"commit to {key!r} as a companion")

    # --- the things shown are the things committed to ---------------------
    for it in (a.get("items") or []):
        k = str(it.get("key") or "")
        if kind == "entity" and k and committed and k not in committed:
            add("block", "item_off_subject",
                f"{it.get('name') or k!r} is featured and was never committed "
                f"to",
                "feature the committed subject and its companions, or name it "
                "as a companion at commit time")

    # --- proof spent once -------------------------------------------------
    #
    # The Four Seasons line twice and Milan twice is not emphasis. It is the
    # model demonstrating it read the brief, and it reads to a customer as a
    # brand with one thing to say.
    # WHOSE PROOF IS THIS? A claim scoped to a different product is not
    # evidence about this one, and labelling it would not make it one. The
    # email path filters these before drafting; nothing CHECKED it, so any
    # generator that skipped the filter — or was given no entity to filter by —
    # could substantiate one product with another product's facts.
    proof_ok = set(c.get("proof_scopes") or []) or set(committed)
    background = 0
    for cl in (a.get("claims") or []):
        scope = str(cl.get("scope") or "brand-wide")
        body = str(cl.get("text") or cl.get("claim") or "")
        cid = str(cl.get("claim_id") or "?")
        if scope == "brand-wide":
            background += 1
        elif kind == "entity" and proof_ok and scope not in proof_ok:
            add("block", "proof_off_subject",
                f"claim {cid} is about {scope!r}, and this is about "
                f"{c.get('key') or 'something else'}",
                "prove this subject with its own claims, or with a brand-wide "
                "one — another product's facts are not evidence about it")
        said_twice, times = "", 0
        for phrase in _distinctive(body, brand_name):
            n = _count(whole, phrase)
            if n > 1:
                said_twice, times = phrase, n
                break          # one finding per claim, not one per phrase
        if not said_twice:
            run = _restated(body, whole)
            said_twice, times = (run, 2) if run else ("", 0)
        if said_twice:
            add("block", "proof_repeated",
                f"{said_twice!r} (claim {cid}) is asserted {times} times",
                "make the point once and spend the space on something "
                "else — a proof restated reads as a brand with one thing "
                "to say")

    # Only an ENTITY commitment has background. When the subject is the brand
    # itself — a story email, a reply about the company — its own credentials
    # are the proof, not a distraction from it, and budgeting them would block
    # the only thing such an artifact can say.
    if kind == "entity" and background > max(0, int(background_budget)):
        add("block", "background_overrun",
            f"{background} brand-wide claims are used as proof and the budget "
            f"is {background_budget}",
            "keep the one credential that serves this subject and drop the "
            "rest — they are true of the company, not of what this is about")

    return out


def _survey(c: dict, a: dict, out: list, add) -> list[dict]:
    """The inverted check: many subjects are the point, saying one twice is not.

    A month report that covers one product is broken, so `subject_absent` and
    `item_off_subject` are simply wrong here. What still holds is that nothing
    should be said twice, and that a round-up which was told what it covers
    should cover it.
    """
    whole = f"{a.get('prominent') or ''}\n{a.get('text') or ''}"
    for want in (c.get("expects") or []):
        if not _mentions(whole, str(want)):
            add("nudge", "survey_incomplete",
                f"{want!r} was expected in this round-up and is not in it",
                "cover it, or stop expecting it")
    seen: dict = {}
    for it in (a.get("items") or []):
        k = str(it.get("key") or "")
        if k:
            seen[k] = seen.get(k, 0) + 1
    for k, n in seen.items():
        if n > 1:
            add("nudge", "survey_repeats",
                f"{k!r} appears {n} times in one round-up",
                "merge the entries — a reader counts them as separate items")
    return out


def block_reasons(findings: list) -> list[dict]:
    """The findings that stop an artifact reaching a customer."""
    return [f for f in (findings or []) if f.get("severity") == "block"]


def as_prompt(findings: list) -> str:
    """The findings as redraft direction. Same shape `email_craft.as_prompt`
    produces, so a repair loop can concatenate the two without caring which
    check produced which line."""
    rows = [f for f in (findings or []) if f.get("severity") == "block"]
    if not rows:
        return ""
    lines = ["\n\n## This draft was about more than one thing",
             "Each line below is a part that did not agree with the rest. "
             "Fix them without introducing a new subject:"]
    lines += [f"- {f['detail']} → {f['fix']}" for f in rows]
    return "\n".join(lines)
