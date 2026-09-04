"""What makes an ad work, as rules a generator can be held to.

The sibling of `email_craft`, and it exists for the same reason that one does:
the validator is excellent at stopping a draft that is FALSE and says nothing
at all about a draft that is DULL. Email got a craft ruleset and improved. Ads
never did — the entire creative instruction the model received was

    "You are writing one short ad for this brand … Do not introduce a second
     factual claim, a price, a material, an origin or a guarantee … Match the
     house voice … Two or three short lines."

which is one hundred percent prohibition and zero percent craft: nothing about
the hook, the offer, specificity, the reader, or why anybody would stop
scrolling. The owner's verdict on the output (2026-08-29) was "completely
terrible", and that brief is the reason.

**None of this is invented here.** It is the pipeline already written down in
`.claude/skills/baci-ad-intelligence/references/copy-system.md`, built from
Hormozi (the value equation — WHAT the copy must contain) and Piliero (concept
diversity and hook discipline — HOW MANY and HOW DIFFERENT), and validated
against a live account. It found the defect that mattered in the previous
copy: the offer buried at character 142–261 on four of five texts, past the
~125 characters Meta shows before "… more". That document has existed for
weeks and no generator has ever read it — the same shape as a KB rule that
never reaches a validator.

WHAT THIS FILE IS NOT. It is not a style preference and not a vocabulary ban.
Every check here is either a MEASUREMENT (where does the offer fall, how long
is the headline, how many value levers are present) or a list of words that
carry no information in any category. A rule that cannot be pointed at is a
taste argument, and a taste argument encoded in a gate is how a generator
becomes unusable.
"""
from __future__ import annotations

import re

from .email_craft import PLATITUDES, URGENCY, _find, _words

#: What Meta shows in a feed before "… more". Copy past this is not read by
#: most people, so an offer that lands after it was not made. Measured in
#: characters because that is what the truncation counts.
TRUNCATION = 125

#: A headline longer than this is cut on the placements that matter.
HEADLINE_MAX = 40

# ---------------------------------------------------------------------------
# The caption, as Instagram actually renders it
# ---------------------------------------------------------------------------
#
# Owner, 2026-09-04: *"the copy format must be optimised for Instagram."* The
# reply format asked for "two or three short lines" and nothing about the
# shape a caption is READ in, so the drafter produced a paragraph — correct
# prose, and the wrong object. Everything below is a MEASUREMENT of that
# shape, in the same spirit as `offer_position`: where the fold falls, whether
# the text is broken, whether there is one ask, how many hashtags.
#
# THE FIRST LINE IS THE CAPTION. Instagram truncates at about `TRUNCATION`
# characters and collapses everything after it behind "… more" — and it breaks
# at the fold whether or not the sentence has finished. An opening line longer
# than the fold is therefore not "a long first line", it is a sentence the
# reader is shown half of.

#: A caption with no break at all, longer than this, is a wall. Under it, one
#: block is a perfectly good caption and demanding a line break would be a
#: style rule rather than a measurement.
CAPTION_BREAK_AT = 180

#: More than this reads as reach-farming, which Instagram's own guidance and
#: every credible test agree suppresses rather than helps. Zero is a fine
#: answer and the format says so.
HASHTAGS_MAX = 5

#: One ask, in the reader's own verbs. Deliberately a list of ACTIONS rather
#: than a sentiment test: "is there a call to action" is answerable by looking
#: for the words that ask for one, and anything cleverer is a taste argument
#: in a gate.
CTA_MARKERS = (
    "shop", "buy", "order", "book", "reserve", "tap", "click", "swipe up",
    "comment", "dm", "message us", "save this", "link in bio", "in our bio",
    "get yours", "browse", "pre-order", "sign up", "subscribe", "learn more",
)

_HASHTAG = re.compile(r"#(\w+)")


def first_line(text: str) -> str:
    """The line the reader is shown before "… more"."""
    for ln in str(text or "").splitlines():
        if ln.strip():
            return ln.strip()
    return ""


def hashtags(text: str) -> list[str]:
    return _HASHTAG.findall(str(text or ""))


def has_cta(text: str) -> bool:
    low = f" {str(text or '').lower()} "
    return any(m in low for m in CTA_MARKERS)

#: Words that describe how the writer feels rather than what the reader gets.
#: Distinct from `email_craft.PLATITUDES` (empty superlatives) — these are
#: aesthetic adjectives that are perfectly true and carry no information,
#: which is exactly why every tableware, venue and supplement ad contains
#: them. The scorecard's "specificity" criterion is this list plus a demand
#: for a concrete noun or number.
VAGUE = (
    "beautiful", "elegant", "stunning", "gorgeous", "lovely", "exquisite",
    "timeless", "effortless", "curated", "thoughtfully", "perfect for",
    "luxurious", "sophisticated", "chic", "iconic", "must-have",
)

#: THE FIVE ANGLES (copy-system step 2). Five texts on one angle collapse into
#: one Entity ID at Meta and compete with each other; five genuinely different
#: psychological entries do not. `brief` is what the drafter is told.
ANGLES = {
    "identity": {
        "label": "Identity",
        "brief": "Open with who the reader IS, not what the product is — "
                 "'which one are you'. The reader should recognise "
                 "themselves in the first line and read on to find out "
                 "which one they are.",
    },
    "gifting": {
        "label": "Gifting",
        "brief": "Write to the person BUYING FOR SOMEONE ELSE. Their fear is "
                 "giving something generic; the promise is a gift that "
                 "proves they know the recipient.",
    },
    "occasion": {
        "label": "Occasion / scene",
        "brief": "Put the reader inside the moment this is used — a specific "
                 "scene with a time and people in it, not a category. The "
                 "dinner that ran past midnight, not 'entertaining'.",
    },
    "objection": {
        "label": "Objection-killer",
        "brief": "Name the hesitation in the first line and answer it with "
                 "the claim. Price, durability, 'will I actually use it'. "
                 "Do not invent a hesitation nobody has.",
    },
    "offer": {
        "label": "Offer-led",
        "brief": "Lead with the offer in plain direct-response voice. The "
                 "offer is the first thing read, stated the same way it is "
                 "stated everywhere else, with no throat-clearing.",
    },
}

#: THE VALUE EQUATION (copy-system step 3). Hormozi's four levers. A text that
#: pulls none of them describes a product; a text that pulls two or more makes
#: an argument. `MIN_LEVERS` is the bar the scorecard enforces.
VALUE_LEVERS = {
    "dream_outcome": "what their life looks like after — the table people "
                     "talk about, the gift they remember",
    "likelihood": "why it will work FOR THEM — proof, numbers, how many "
                  "others, what sold out",
    "time_delay": "how fast — in stock now, ships in time for the dinner",
    "effort": "what they DON'T have to do — it is a set, nothing to curate; "
              "shatterproof, nothing to worry about",
}
MIN_LEVERS = 2

#: THE HEADLINE BANK (copy-system step 4). One of each, never five of one.
HEADLINE_TYPES = {
    "identity_question": "Which one are you?",
    "outcome_claim": "the result, stated flat",
    "offer": "the offer or the deadline, in the fewest words",
    "mechanism": "why it works / what it is made of",
    "curiosity": "a concrete, odd, specific detail",
}


#: Angles that make sense for any business. `gifting` is NOT among them: it is
#: the one angle that depends on the category. A venue, a showroom or a
#: supplement brand advertising "the most personal gift" is writing an ad for
#: somebody else's product, and the five-angle matrix in `copy-system.md` was
#: derived for a giftable goods brand where it is the second-best performer.
UNIVERSAL_ANGLES = ("identity", "occasion", "objection", "offer")

#: What has to be TRUE of the account before `gifting` is offered — evidence in
#: the knowledge base, never a guess about the category. Matched against
#: audience names and pains, situation names and claim text.
_GIFT_EVIDENCE = ("gift", "gifting", "present", "registry", "occasion gift",
                  "for someone", "holiday")


def angles_for(evidence: str = "") -> tuple:
    """The angles this account may actually use, decided by its own data.

    `evidence` is whatever the caller can cheaply concatenate — audience names
    and pains, situations, claim text. Gifting is added only when that text
    shows the account sells something people buy FOR SOMEBODY ELSE. Everything
    else is universal.

    Data rather than taste, and the reason is concrete: with a fixed five, an
    events venue would have had one of every five ads written to a gift-buyer
    who does not exist, and nothing in the pipeline would have said so — the
    validator only checks that a draft is TRUE, and "the most personal gift"
    is not false, it is simply about a different business.
    """
    low = str(evidence or "").lower()
    if any(w in low for w in _GIFT_EVIDENCE):
        return ("identity", "gifting", "occasion", "objection", "offer")
    return UNIVERSAL_ANGLES


def _first_words(text: str, n: int = 5) -> str:
    return " ".join(_words(text)[:n])


def offer_position(body: str, offer: str) -> int:
    """Where the offer first appears, in characters. -1 when it is absent.

    Case-insensitive and whitespace-tolerant, because "15% off" and "15% OFF"
    are the same offer and a check that misses one is worse than no check.
    """
    if not offer or not body:
        return -1
    hay = re.sub(r"\s+", " ", body).lower()
    needle = re.sub(r"\s+", " ", offer).strip().lower()
    return hay.find(needle)


def levers_present(text: str, levers: list[str] | None) -> list[str]:
    """Which value levers the DRAFTER declared it pulled, filtered to real ones.

    Declared rather than detected on purpose. Detecting "does this sentence
    convey a dream outcome" is a judgement, and a regex pretending to make it
    would fail in both directions — passing a mood board that happens to
    contain a number, failing a real argument phrased unusually. The drafter
    states which levers it pulled and the copy is reviewed against that
    statement, the same way a claim carries its `claim_id` rather than having
    its truth inferred.
    """
    return [x for x in (levers or []) if x in VALUE_LEVERS]


def review(*, body: str = "", headline: str = "", angle: str = "",
           offer: str = "", levers: list[str] | None = None,
           urgency_backed_by: str = "", proof: str = "") -> list[dict]:
    """Craft findings for one ad variant. `[]` means nothing to say.

    Severities match `email_craft`: "block" is a defect the owner should not
    have to catch, "nudge" is a note. Nothing here edits the copy — every
    finding names what is wrong and what would fix it, and the redraft path
    is what applies it.
    """
    out: list[dict] = []

    def add(sev, rule, detail, fix):
        out.append({"severity": sev, "rule": rule, "detail": detail, "fix": fix})

    text = (body or "").strip()

    # --- the hook: the first five words are the whole audition -------------
    if text:
        opener = _first_words(text)
        low = opener.lower()
        if any(v in low for v in VAGUE):
            add("block", "hook_is_vague",
                f"the ad opens on {opener!r}",
                "the first five words are the only ones most people read — "
                "open on a concrete noun, a number, or the reader "
                "themselves, never an adjective")
        # A first line that names the brand before it gives a reason to care.
        if re.match(r"^(introducing|discover|meet |welcome to)\b", low):
            add("block", "hook_is_an_announcement",
                f"the ad opens on {opener!r}",
                "nobody is waiting to be introduced to anything — lead with "
                "what the reader gets or who they are")

    # --- one idea ---------------------------------------------------------
    sentences = [s for s in re.split(r"[.!?]\s+", text) if s.strip()]
    if len(sentences) > 4:
        add("nudge", "more_than_one_idea",
            f"{len(sentences)} sentences",
            "an ad carries one idea; a second idea does not add to the "
            "first, it competes with it")

    # --- specificity ------------------------------------------------------
    vague_hits = _find(text, VAGUE)
    if vague_hits:
        add("block", "vague_adjectives",
            ", ".join(sorted(set(vague_hits))[:4]),
            "replace each with the concrete thing it is standing in for — a "
            "material, a number, a moment. These words are true of every "
            "competitor's product too, which is why they persuade nobody")
    plat = _find(text, PLATITUDES)
    if plat:
        add("block", "platitudes", ", ".join(sorted(set(plat))[:4]),
            "an empty superlative is a claim the reader has already "
            "discounted; say the specific thing instead")
    if text and not re.search(r"\d", text) and not proof:
        add("nudge", "nothing_concrete",
            "no number and no proof anywhere in the ad",
            "one number — a count, a size, a time, a price — does more for "
            "belief than any adjective")

    # --- the offer has to be READ, not merely present ---------------------
    if offer:
        at = offer_position(text, offer)
        if at < 0:
            add("block", "offer_missing",
                f"the offer {offer!r} is not in the copy",
                "state it exactly as it is stated everywhere else — an offer "
                "worded differently in each ad reads as a different offer")
        elif at > TRUNCATION:
            add("block", "offer_past_the_fold",
                f"the offer first appears at character {at}",
                f"Meta shows about {TRUNCATION} characters before '… more'. "
                f"An offer after that was not made — move it earlier")

    # --- the headline -----------------------------------------------------
    if headline:
        if len(headline) > HEADLINE_MAX:
            add("block", "headline_too_long",
                f"{len(headline)} characters",
                f"headlines are cut past about {HEADLINE_MAX} — say less")
        if headline.strip().lower() == text[:len(headline)].strip().lower():
            add("nudge", "headline_repeats_the_body",
                "the headline restates the first line",
                "the headline is a second entry point, not an echo")
        if _find(headline, VAGUE) or _find(headline, PLATITUDES):
            add("block", "headline_is_vague",
                headline[:60],
                "a headline has no room to recover from a wasted word")

    # --- the value equation -----------------------------------------------
    got = levers_present(text, levers)
    if len(got) < MIN_LEVERS:
        add("block", "not_enough_value_levers",
            f"{len(got)} of the four levers declared ({', '.join(got) or 'none'})",
            f"an ad pulling fewer than {MIN_LEVERS} of "
            f"{', '.join(VALUE_LEVERS)} is a mood board, not an ad — say what "
            f"their life looks like after, why it will work for them, how "
            f"fast, or what they do not have to do")

    # --- urgency, the same rule email is held to --------------------------
    urg = _find(text, URGENCY) + _find(headline or "", URGENCY)
    if urg and not urgency_backed_by:
        add("block", "urgency_without_a_deadline",
            ", ".join(sorted(set(urg))[:3]),
            "there is no deadline or count behind this — manufactured "
            "scarcity is the one thing a machine writing at scale must "
            "never do; state the real thing or drop the pressure")

    # --- the caption shape, measured -------------------------------------
    if text:
        opener = first_line(text)
        if len(opener) > TRUNCATION:
            add("block", "first_line_past_the_fold",
                f"the first line runs to {len(opener)} characters",
                f"Instagram cuts at about {TRUNCATION} and breaks mid-sentence "
                f"— the opening line has to be a complete thought inside the "
                f"fold, with the rest below it")
        if "\n" not in text.strip() and len(text) > CAPTION_BREAK_AT:
            add("block", "one_unbroken_block",
                f"{len(text)} characters with no line break",
                "a caption is read in glances — break it: the hook, then the "
                "payoff, then the ask, with blank lines between them")
        if not has_cta(text):
            add("block", "no_call_to_action",
                "nothing in the caption asks the reader to do anything",
                "give it one ask, on its own line — shop, book, tap, comment, "
                "save. An ad with no ask is a post")
        tags = hashtags(text)
        if len(tags) > HASHTAGS_MAX:
            add("block", "too_many_hashtags",
                f"{len(tags)} hashtags",
                f"at most {HASHTAGS_MAX}, each a phrase somebody would "
                f"actually search. A wall of tags reads as reach-farming and "
                f"none at all is a fine answer")
        elif tags:
            # LOWERCASED AND STRIPPED OF PUNCTUATION. `email_craft._words`
            # splits on whitespace and keeps both, so "party." never matched
            # "#party" and the check passed over every hashtag that did in
            # fact repeat the caption — green, and reading nothing.
            body_words = set(re.findall(r"[a-z0-9]+",
                                        text.split("#")[0].lower()))
            earned = [t for t in tags if t.lower() not in body_words]
            if not earned:
                add("nudge", "hashtags_that_earn_nothing",
                    ", ".join("#" + t for t in tags[:3]),
                    "every one of these repeats a word the caption already "
                    "says, so they add no way to be found — drop them or "
                    "make them the terms a buyer would type")

    # --- the angle actually used ------------------------------------------
    if angle and angle not in ANGLES:
        add("nudge", "unknown_angle", angle,
            "the angles that exist are: " + ", ".join(ANGLES))

    return out


def score(findings: list[dict]) -> dict:
    """The scorecard (copy-system step 6), computed from the findings.

    Ten points, two per criterion, and a block costs both. Returned rather
    than enforced here: the caller decides whether a 6/10 is redrafted or
    shown to the owner with its reasons, and that policy belongs with the
    skill, not with the ruleset.
    """
    blocks = [f for f in findings if f["severity"] == "block"]
    by_rule = {f["rule"] for f in blocks}
    criteria = {
        "hook": {"hook_is_vague", "hook_is_an_announcement"},
        "one_idea": {"more_than_one_idea"},
        "specificity": {"vague_adjectives", "platitudes", "headline_is_vague"},
        "offer": {"offer_missing", "offer_past_the_fold"},
        "value": {"not_enough_value_levers", "urgency_without_a_deadline"},
        # THE SHAPE IT IS READ IN, scored beside what it says. A caption that
        # is true, specific and unreadable in a feed is not a working ad.
        "caption": {"first_line_past_the_fold", "one_unbroken_block",
                    "no_call_to_action", "too_many_hashtags"},
    }
    points = {k: (0 if by_rule & v else 2) for k, v in criteria.items()}
    total = sum(points.values())
    of = 2 * len(criteria)
    # PROPORTIONAL, so the documented bar survives a sixth criterion.
    # copy-system.md says ship at 8/10; adding a criterion and keeping the
    # literal 8 would have quietly loosened it to 8/12.
    return {"total": total, "of": of, "points": points,
            "blocks": len(blocks),
            "ship": total >= 0.8 * of and not blocks}


def block_reasons(findings: list[dict]) -> list[dict]:
    """The findings that stop a variant. Mirrors `email_craft.block_reasons`."""
    return [f for f in findings or [] if f.get("severity") == "block"]


def as_prompt(findings: list[dict]) -> str:
    """The findings, written for the drafter's next attempt."""
    if not findings:
        return ""
    return ("\n\n## Craft problems with your draft — fix every one\n"
            + "\n".join(f"- {f['detail']} → {f['fix']}" for f in findings))


# ---------------------------------------------------------------------------
# The panel — Hormozi and Piliero, BEFORE the variants are written
# ---------------------------------------------------------------------------
#
# Owner, 2026-09-04: *"every ad copy goes through the 'Alex Hormozi' and 'Sam
# Piliero' test to self-justify — show what each would say and apply the
# improvements BEFORE the variants are generated."* `review` above runs AFTER
# a draft, on the words, one variant at a time, and can only say what is wrong
# with a line already written. This sits before the drafter, on the CONCEPTS —
# angle x claim x offer x reader — and rewrites each variant's brief, so the
# improvement is in the instruction the writer receives rather than in a
# repair of what they wrote. One pass over the whole batch, because Piliero's
# question is about the batch: are these N genuinely different psychological
# entries, or one idea five ways.
#
# Nothing here is a taste argument. The two reviewers are the two halves of
# `copy-system.md`: Hormozi for WHAT the copy must contain (the value
# equation, the offer stated once and early), Piliero for HOW MANY and HOW
# DIFFERENT (the hook, one idea, no two variants that Meta would fold into one
# Entity ID). The model plays both; the code decides what they are shown and
# where their answer goes.

PANEL_SYSTEM = """You are two reviewers sitting on a batch of ad concepts BEFORE
the copy is written. Speak as each in turn, in the first person, briefly, and
then rewrite the brief the writer will follow. You never write the ad.

ALEX HORMOZI — the value equation and the offer. For each concept: which of
the four levers (dream outcome, perceived likelihood, time delay, effort and
sacrifice) this claim can honestly pull for THIS reader, which one it should
lead with, and whether the offer (if any) is stated once, early, and exactly.
A concept that can pull fewer than two levers is a mood board — say so and
say which lever the claim's evidence could add.

SAM PILIERO — the hook, one idea, and diversity across the batch. For each
concept: what the first five words must do (open on a concrete noun, a number
or the reader; never an adjective, never an announcement), the ONE idea it
carries, and what to cut. For the BATCH: are these genuinely different
psychological entries, or restatements Meta would fold into one? Name any two
that overlap and say what one of them should become instead.

THE REWRITTEN BRIEF, per concept: one paragraph of plain instruction the
writer must follow — the lever to lead with, the hook shape, the one idea,
where the offer sits, what to avoid — specific to this claim and this reader.
Never invent a fact, a number, a price, an origin or a deadline that is not
in the concept; the hard rules are enforced in code after the copy is written.

Answer in JSON only, in exactly this shape:
{"variants": [{"n": 1, "hormozi": "<2-4 sentences>", "piliero": "<2-4 sentences>",
               "brief": "<one paragraph>"}],
 "batch": {"piliero": "<2-4 sentences on diversity across the batch>",
           "verdict": "distinct" | "overlapping"}}"""


def panel_prompt(bundle: dict, concepts: list[dict]) -> list[str]:
    """Everything the panel is shown, as inspectable parts — the concepts, not
    the copy. Split out for the same reason `ad_prompt` is: a brief nobody
    can read without spending money is a brief nobody checks."""
    parts = ["## The batch — concepts, before a word is written"]
    aud = bundle.get("audience") or {}
    reader = (aud.get("name") or aud.get("key") or "") if isinstance(aud, dict) else ""
    if reader:
        pains = "; ".join(list(aud.get("pains") or [])[:3]) if isinstance(aud, dict) else ""
        parts.append(f"READER: {reader}" + (f" — cares about: {pains}" if pains else ""))
    else:
        parts.append("READER: not named — write the brief for the most likely "
                     "buyer the claim implies, and say that you had to")
    if str(bundle.get("positioning") or "").strip():
        parts.append(f"POSITIONING UNDER TEST: {str(bundle['positioning']).strip()}")
    fun = bundle.get("funnel") or {}
    if isinstance(fun, dict) and fun.get("label"):
        parts.append(f"FUNNEL STAGE: {fun['label']} — the reader {fun.get('reader', '')}")
    offer = str(bundle.get("offer") or "").strip()
    parts.append(f"OFFER: {offer}" if offer else "OFFER: none — no discount, no code; do not invent one")
    deadline = str(bundle.get("deadline") or "").strip()
    parts.append(f"REAL DEADLINE: {deadline}" if deadline else "DEADLINE: none — urgency is not available")
    ents = bundle.get("entities") or []
    if ents:
        parts.append("ADVERTISED: " + "; ".join(
            f"{e.get('name', '')} — {str(e.get('description') or '')[:160]}"
            for e in ents[:3]))
    for c in concepts:
        a = ANGLES.get(c.get("angle", ""), {})
        cl = c.get("claim") or {}
        parts.append(
            f"\n### Concept {c.get('n')}\n"
            f"angle: {a.get('label', c.get('angle', ''))} — {a.get('brief', '')}\n"
            f"claim: {str(cl.get('claim') or '').strip()}"
            + (f"\nevidence: {str(cl.get('evidence') or '').strip()}" if cl.get("evidence") else "")
            + (f"\nhesitation it answers: {c['objection']}" if c.get("objection") else ""))
    parts.append("\nSpeak as Hormozi, then as Piliero, per concept; then Piliero on "
                 "the batch; then the rewritten brief for each. JSON only.")
    return parts


def panel_parse(raw: str) -> dict:
    """The panel's answer as `{variants: {n: {hormozi, piliero, brief}}, batch:
    {piliero, verdict}}`, or {} when it did not answer in the shape asked —
    the run then says the panel did not sit, which is the honest outcome."""
    import json as _json
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        data = _json.loads(text[text.index("{"):text.rindex("}") + 1])
    except Exception:                                            # noqa: BLE001
        return {}
    out: dict = {"variants": {}, "batch": {}}
    for v in (data.get("variants") or []):
        if not isinstance(v, dict):
            continue
        try:
            n = int(v.get("n"))
        except (TypeError, ValueError):
            continue
        out["variants"][n] = {"hormozi": str(v.get("hormozi") or "").strip(),
                              "piliero": str(v.get("piliero") or "").strip(),
                              "brief": str(v.get("brief") or "").strip()}
    b = data.get("batch") or {}
    if isinstance(b, dict):
        out["batch"] = {"piliero": str(b.get("piliero") or "").strip(),
                        "verdict": str(b.get("verdict") or "").strip().lower()}
    return out if out["variants"] else {}


def panel_brief(panel_row: dict) -> str:
    """The panel's verdicts and rewritten brief, written for the drafter."""
    if not panel_row or not str(panel_row.get("brief") or "").strip():
        return ""
    return ("\n## The panel sat on this concept before you — follow its brief\n"
            f"Hormozi: {panel_row.get('hormozi', '')}\n"
            f"Piliero: {panel_row.get('piliero', '')}\n"
            f"THE BRIEF: {panel_row['brief']}")


#: The format the drafter answers in. Two labelled lines and the ad, because a
#: headline and the value levers cannot be inferred from prose — the levers
#: especially: see `levers_present` on why they are DECLARED rather than
#: detected. Parsed forgivingly by `parse` below; a model that ignores the
#: format loses its headline, not its ad.
REPLY_FORMAT = """Answer in exactly this shape and nothing else:

HEADLINE: <under 40 characters>
LEVERS: <two or more of: dream_outcome, likelihood, time_delay, effort>
---
<FIRST LINE: the hook. A complete thought in under 125 characters, because
Instagram cuts here and everything after it is hidden behind "… more". If
there is an offer, it belongs in this line.>

<one or two short lines that pay the hook off, separated by blank lines. A
single unbroken paragraph is not read in a feed.>

<the ask, on its own line: shop, book, tap, comment, save. One ask.>

<hashtags ONLY if they earn their place: at most 5, each a phrase a buyer
would really search, none of them a word the caption already says. None at
all is a fine answer.>"""


def parse(raw: str) -> dict:
    """Split a drafter reply into {headline, levers, body}.

    FORGIVING BY DESIGN. A model that ignores the format should lose its
    headline, not have its ad thrown away — so anything before a `---` that
    does not parse as a labelled line is treated as part of the ad, and a
    reply with no markers at all is all body. The craft review then judges
    what actually arrived, which is the honest outcome either way.
    """
    text = str(raw or "").strip()
    headline, levers = "", []
    body = text
    if "---" in text:
        head, _, body = text.partition("---")
        body = body.strip()
    else:
        head = ""
        lines = text.split("\n")
        keep = []
        for ln in lines:
            if re.match(r"^\s*(HEADLINE|LEVERS)\s*:", ln, re.I):
                head += ln + "\n"
            else:
                keep.append(ln)
        if head:
            body = "\n".join(keep).strip()
    for ln in head.split("\n"):
        m = re.match(r"^\s*HEADLINE\s*:\s*(.+)$", ln, re.I)
        if m:
            headline = m.group(1).strip()
        m = re.match(r"^\s*LEVERS\s*:\s*(.+)$", ln, re.I)
        if m:
            levers = [x.strip().lower().replace(" ", "_")
                      for x in re.split(r"[,;/]", m.group(1)) if x.strip()]
    return {"headline": headline, "levers": levers_present(body, levers),
            "body": body}
