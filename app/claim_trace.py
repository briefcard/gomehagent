"""Which sentences of an output actually stand on an approved claim.

NAMED `claim_trace`, not `grounding`: `app/grounding.py` already exists
and does the opposite job — it renders the knowledge base INTO a prompt
for the mail path. This module reads a finished output BACK against the
claims. Two directions across the same data, and giving them one name
would be the two-things-one-word defect this codebase keeps paying for.

Owner, 2026-08-29, after an Eien Health article recommended glucosamine and
chondroitin — which Eien does not sell — and discussed knee pain:

    "This is the exact issue that this data layer is meant to fix … I don't
     want to see it as 'never say glucosamine & chondroitin' because we may
     want to generate articles that point out the deficits in the competition,
     but how come it doesn't know that? … we should have a feature in our
     review of all assets — blogs, ads, emails — that shows what part of the
     output is confirmed by a claim."

**WHY IT DID NOT KNOW.** `validator.check`'s citation rule is, in full:

    if require_citation and body.strip() and not ids:
        fail("uncited", "the draft carries no claim_id", …)

`not ids` — are ANY claim_ids attached. The blog attaches every claim the
account owns to every article, so the check passes on all of them whatever the
body says. Nothing ever verified that a sentence CORRESPONDS to a claim. The
ban list could not help either: nothing in that article is a forbidden phrase,
it is a page of unsupported assertions, and a ban list catches `forbidden`,
never `unsupported`.

`fitness.named_unfit` could not help for a third reason — it matches entities
the account HAS and must not promote. Glucosamine is not an Eien entity, so
there was nothing to match. Absence was read as permission again.

**WHAT THIS IS.** Not a gate. A READING, for the review surfaces: every
sentence, and the approved claim behind it when there is one. Highlighted
where it is backed, plain where nothing stands behind it — so an article that
is 4% grounded looks like one, and the fix is to correct or add a CLAIM rather
than to ban a word.

**IT UNDER-CREDITS ON PURPOSE.** A sentence counts as backed only when most of
a claim's own content words appear in it. Loose topical overlap — a claim about
omega-3 dosage and a sentence about omega-3 research — is NOT support, and
calling it support would be the worst possible failure here: a green mark on
an assertion nobody approved. Erring the other way merely asks a person to
look. There is no model in this path, deliberately: a model deciding "is this
supported" is the very judgement being checked.
"""
from __future__ import annotations

import re

#: Shared content words needed before a claim is considered to be behind a
#: sentence. Two, because one is almost always the subject noun and a single
#: shared noun is a topic, not a citation.
MIN_SHARED = 2

#: …and they must be most of the CLAIM, not most of the sentence. A long
#: sentence brushing past a short claim is not carrying it.
CLAIM_COVERAGE = 0.5

#: Outputs needed on EACH side of a window before `trend` will say which way
#: grounding moved. The assurance page's own rule, applied to the number most
#: likely to be quoted at somebody: a dashboard that leads with a rate
#: computed from four events teaches people to believe rates computed from
#: four events. Under this, `moved` is None — the average still renders,
#: because "these three averaged 40%" is a fact, while a direction drawn from
#: one output against two is noise wearing an arrow.
MIN_FOR_DIRECTION = 4

#: A CLAIM WITH A NUMBER IN IT IS ABOUT THAT NUMBER. Caught on the first real
#: article this was run against: "Each serving contains 1000mg of omega-3
#: fatty acids" was credited as the support for "Omega-3 fatty acids are
#: widely researched for their role in moderating inflammatory pathways" —
#: they share the ingredient and nothing else. A dosage claim standing behind
#: an efficacy sentence is the single worst mistake available here: a green
#: mark on a health assertion nobody approved. So when a claim carries
#: figures, the sentence has to carry one of them.
#: NOT a digit inside a name. The first version matched "3" out of "omega-3"
#: and "1" out of "GLP-1", so a dosage claim and an efficacy sentence shared a
#: "figure" and the guard passed the very case it was written for. A quantity
#: is a number that starts a word.
_FIGURE = re.compile(r"(?<![\w-])\d+(?:[.,]\d+)?")

#: Sentences that ASSERT something checkable, as opposed to prose that moves
#: the reader along. "You didn't do anything dramatic" needs no claim; "the
#: most studied supplements for knee pain" does. Marking every sentence
#: unbacked would bury the ones that matter, and a check that cries wolf gets
#: switched off — which costs more than the rare miss.
_ASSERTIVE = (
    # efficacy and evidence
    "studies", "studied", "research", "researched", "evidence", "clinical",
    "proven", "shown to", "demonstrated", "benchmark", "trials",
    "tested", "verified", "certified", "third-party",
    # effect on the body
    "supports", "support", "reduces", "reduce", "improves", "improve",
    "prevents", "treats", "heals", "rebuilds", "boosts", "regulates",
    "moderating", "relieves", "helps", "promotes", "increases", "decreases",
    # composition and quantity
    "contains", "made of", "made with", "formulated", "dose", "doses",
    "dosage", "mg", "grams", "per serving", "ingredients",
    # comparatives that imply a fact
    "most", "best", "highest", "strongest", "leading", "only",
)

_NUMBER = re.compile(r"\b\d")


#: Tags that end a line of reading. Kept as a newline rather than a space so
#: two things hold that did not before: a heading with no full stop is its own
#: sentence instead of being glued to the paragraph under it, and the review
#: surface can put the author's paragraphs back.
_BLOCK = re.compile(
    r"</?(?:p|div|br|li|h[1-6]|tr|td|th|section|article|header|footer"
    r"|blockquote|ul|ol|table|figure|figcaption)\b[^>]*>", re.I)


def _sentences(text: str) -> list[str]:
    """Split on sentence ends AND on line breaks.

    A line break is a hard boundary because a heading rarely carries a full
    stop: without this, "Glucosamine and chondroitin work" merges with the
    first sentence of the paragraph below it and the pair is scored as one.
    """
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", str(text or ""))
            if s.strip()]


#: What may sit BETWEEN two words of a sentence in the markup and still be the
#: same sentence to a reader: whitespace, a tag, an entity. `plain_text` throws
#: all three away, which is why the sentence the claim margin shows is almost
#: never a literal substring of the body it came from.
_GAP = r"(?:\s|<[^>]+>|&[A-Za-z#0-9]+;)+"


def replace_sentence(body: str, old: str, new: str) -> tuple[str, int]:
    """Swap one sentence in the MARKUP, matching it as a reader sees it.

    The claim margin reads `plain_text(body)` — tags stripped, entities
    decoded, whitespace collapsed — so `body.replace(old, new)` misses any
    sentence carrying a `<strong>`, a `&amp;` or a line break, which in real
    article prose is most of them. This matches the words in order, tolerating
    markup between them, and rewrites the span.

    Returns `(body, count)`. **Count matters more than the body**: 0 means the
    caller must say the draft was NOT changed rather than implying it was, and
    that honesty is the whole reason this returns a number at all.

    Only the FIRST occurrence is rewritten. A sentence appearing twice is two
    decisions, and silently changing both would be this function deciding one
    of them.

    Inline markup inside the sentence does not survive as EMPHASIS — the
    replacement is the plain corrected text, which is the right trade for a
    correction (the numbers matter, the italics do not). But the tags are
    RE-EMITTED after it, because dropping them is not the same trade at all: a
    sentence opening inside `<strong>` and closing after it would leave the
    tag unclosed and the rest of the article bold. Losing emphasis is a
    cosmetic loss; losing a closing tag corrupts the document.
    """
    words = [w for w in re.findall(r"[^\s]+", str(old or "")) if w]
    if not words or not str(body or ""):
        return body, 0
    pattern = _GAP.join(re.escape(w) for w in words)
    m = re.search(pattern, body, re.I)
    if not m:
        return body, 0
    n = len(re.findall(pattern, body, re.I))
    tags = "".join(re.findall(r"<[^>]+>", m.group(0)))
    return body[:m.start()] + str(new or "") + tags + body[m.end():], n


def plain_text(body: str) -> str:
    """Markup out, one space between everything. Headings are kept — an H2 can
    assert as loudly as a paragraph ("Glucosamine and chondroitin work")."""
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", str(body or ""),
               flags=re.I | re.S)
    t = _BLOCK.sub("\n", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = (t.replace("&amp;", "&").replace("&nbsp;", " ")
         .replace("&#39;", "'").replace("&quot;", '"'))
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r" ?\n ?", "\n", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


_HEADING = re.compile(r"<h([1-6])\b[^>]*>(.*?)</h\1>", re.I | re.S)


def headings(body: str) -> set:
    """Which lines were headings, so a review surface can render them as such.

    Deliberately NOT folded into `plain_text`. The scoring path wants the
    words and nothing else: turning `<h2>` into `# ` would put a hash inside
    the sentence text, and that text is quoted verbatim in every note, every
    `unbacked_assertions` entry and every marker tip.
    """
    return {t for t in (plain_text(m.group(2)) for m in _HEADING.finditer(
        str(body or ""))) if t}


def _tokens(s: str) -> set:
    from . import keywords as kw
    return set(kw.tokens(s or ""))


def is_assertion(sentence: str) -> bool:
    """Does this sentence claim something a reader could be misled by?

    A number, or one of the assertive markers. Deliberately broad — the cost
    of calling a harmless sentence an assertion is one extra unhighlighted
    line, and the cost of missing one is an unsupported health claim reading
    as ordinary prose.
    """
    low = f" {str(sentence or '').lower()} "
    if _NUMBER.search(low):
        return True
    return any(m in low for m in _ASSERTIVE)


def annotate(text: str, claims: list) -> dict:
    """Every sentence, and the claims standing behind it.

    `claims` are dicts or rows carrying at least `claim`; `id`/`claim_id` and
    `evidence` ride along when present so the reader can open the claim it
    matched. Returns:

        sentences  [{text, backed, assertion, note, claims:[{id, claim, …}]}]
                   `note` is a 1-based index over the sentences that assert
                   something, 0 for prose. Marker and panel entry share it.
        backed     how many sentences a claim stands behind
        assertions how many sentences assert something checkable
        unbacked_assertions  the ones that assert and have nothing behind them
        coverage_pct  backed assertions as a percentage of assertions

    `coverage_pct` is over ASSERTIONS, not over all sentences: an article that
    is mostly readable prose should not be scored down for the prose, and one
    that is mostly unsupported efficacy statements should not be flattered by
    it.
    """
    rows = []
    for c in claims or []:
        if isinstance(c, dict):
            txt = str(c.get("claim") or "")
            cid = str(c.get("claim_id") or c.get("id") or "")
            ev = str(c.get("evidence") or "")
        else:
            txt = str(getattr(c, "claim", "") or "")
            cid = str(getattr(c, "id", "") or "")
            ev = str(getattr(c, "evidence", "") or "")
        if txt.strip():
            rows.append({"id": cid, "claim": txt, "evidence": ev,
                         "tokens": _tokens(txt),
                         "figures": set(_FIGURE.findall(txt))})

    out = []
    for sent in _sentences(plain_text(text)):
        st = _tokens(sent)
        hits = []
        for r in rows:
            if not r["tokens"]:
                continue
            shared = r["tokens"] & st
            if r["figures"] and not (r["figures"] & set(_FIGURE.findall(sent))):
                continue
            if len(shared) >= MIN_SHARED and \
                    len(shared) >= CLAIM_COVERAGE * len(r["tokens"]):
                hits.append({"id": r["id"], "claim": r["claim"],
                             "evidence": r["evidence"]})
        # A SENTENCE A CLAIM MATCHED IS AN ASSERTION BY DEMONSTRATION.
        # `is_assertion` is a word-list heuristic and will always miss some —
        # "Every batch is third-party tested in a US facility" carries no
        # marker and no figure — and a backed sentence that did not count as
        # an assertion was excluded from the denominator, so real grounding
        # was reported as 0%. Matching a claim is stronger evidence than any
        # marker list.
        out.append({"text": sent, "backed": bool(hits),
                    "assertion": bool(hits) or is_assertion(sent),
                    "claims": hits, "note": 0})

    # THE NUMBER IS ASSIGNED HERE, ONCE, and every reader uses it. The old
    # gutter built a second list of cards in its own order and hoped card
    # three sat beside sentence three; nothing linked them, and on any body
    # where prose interleaved with assertions nothing did. A shared index
    # cannot drift, because there is only one.
    n = 0
    for s in out:
        if s["assertion"]:
            n += 1
            s["note"] = n

    assertions = [s for s in out if s["assertion"]]
    backed_assertions = [s for s in assertions if s["backed"]]
    return {
        "sentences": out,
        "backed": sum(1 for s in out if s["backed"]),
        "total": len(out),
        "assertions": len(assertions),
        "unbacked_assertions": [s["text"] for s in assertions
                                if not s["backed"]],
        "coverage_pct": (round(100 * len(backed_assertions) / len(assertions))
                         if assertions else None),
    }


def summary(report: dict) -> str:
    """One sentence a person can act on. `""` when there is nothing to say.

    THREE STATES, not two (design rule 2): an output with no assertions in it
    is not "0% grounded", it is "nothing here needed a claim" — and reporting
    those the same way is how a real 4% gets ignored.
    """
    if not report or not report.get("total"):
        return ""
    n = report.get("assertions") or 0
    if not n:
        return ("Nothing here asserts a checkable fact, so no claim was "
                "needed — this is prose, not a grounding failure.")
    pct = report.get("coverage_pct")
    left = len(report.get("unbacked_assertions") or [])
    if not left:
        return f"All {n} factual sentences trace to an approved claim."
    return (f"{pct}% of the {n} factual sentences here trace to an approved "
            f"claim. {left} assert something with nothing on file behind it "
            f"— correct or add the claim, then regenerate.")


# ---------------------------------------------------------------------------
# What the knowledge base has never heard of
# ---------------------------------------------------------------------------

#: Language that RECOMMENDS or RANKS rather than merely describing. The Eien
#: article's damage was not that it mentioned glucosamine — the owner wants
#: competitor-deficit articles, which must be able to name what the brand does
#: not sell. It was that it RECOMMENDED it: "remain the benchmark for
#: structural joint support". Mentioning is fine; steering the reader to a
#: thing this account has nothing in, with nothing on file about it, is not.
_RECOMMENDS = (
    "benchmark", "look for", "worth including", "worth noting",
    "choose", "opt for", "recommend", "the right", "best option",
    "most studied", "go-to", "gold standard", "should take", "should use",
    "worth adding", "the standard",
)


def vocabulary(tenant: str) -> set:
    """Every content word this account's knowledge base actually contains.

    Claims, entity names and descriptions, objections and their answers, and
    situation tags. One read of what the account knows, so "never heard of"
    means never heard of ANYWHERE rather than merely absent from the claims.
    """
    from . import kb as kbm
    words: set = set()
    try:
        for c in kbm.claims(tenant):
            words |= _tokens(getattr(c, "claim", "") or "")
            words |= _tokens(getattr(c, "evidence", "") or "")
        for e in kbm.entities(tenant, available_only=False):
            words |= _tokens(getattr(e, "name", "") or "")
            words |= _tokens(getattr(e, "description", "") or "")
        for o in kbm.objections(tenant):
            words |= _tokens(getattr(o, "objection", "") or "")
            words |= _tokens(getattr(o, "response", "") or "")
        for s_ in kbm.situation_rows(tenant):
            words |= _tokens(getattr(s_, "tag", "") or "")
            words |= _tokens(getattr(s_, "description", "") or "")
    except Exception:                                            # noqa: BLE001
        return set()
    return words


#: Words that mean the speaker — matched CASE-SENSITIVELY in running text,
#: plus their sentence-initial capitals. Lowercasing first looked harmless and
#: was not: "third-party tested in a US facility" matched the pronoun `us` and
#: the country code was read as the brand. Pronouns are lowercase mid-sentence;
#: US, UK and EU are not.
_FIRST_PERSON = ("we", "we're", "we've", "our", "ours", "us", "ourselves")
_PRONOUN = re.compile(
    r"(?:^|(?<=[\s(\"']))(?:" + "|".join(_FIRST_PERSON) + r")(?=[\s,.;:!?)\"']|$)")
_PRONOUN_START = re.compile(
    r"^(?:" + "|".join(w.capitalize() for w in _FIRST_PERSON) + r")\b")

#: Words too generic to identify anybody. A tenant called "Miami Event Spaces"
#: must not claim every sentence containing "event" as a statement about
#: itself — that would quietly reclassify most of a venue's copy as
#: brand claims and ask for approvals nobody owes.
_GENERIC_NAME = {
    "the", "and", "co", "inc", "llc", "ltd", "group", "brand", "company",
    "health", "beauty", "home", "shop", "store", "studio", "design", "designs",
    "event", "events", "spaces", "space", "usa", "us", "global", "world",
    "international", "solutions", "services", "products", "supply", "supplies",
}


def brand_marks(tenant: str) -> set:
    """The PHRASES that mean "this account" — its name, and its catalogue.

    Phrases, not tokens, and that is the whole care in this function. Tokenise
    "Eien Health" and the word `health` alone starts marking every sentence
    about health as a statement about the brand; tokenise "Zodiac Vibe cup"
    and `cup` does the same. A phrase says what a token cannot: this sentence
    named US, not our subject matter.

    Derived entirely from data every account already has, so it costs nothing
    per client and grows on its own as a catalogue is filled. Its emptiness is
    a real state and the caller must handle it — see `about_us`.
    """
    from . import kb as kbm
    from . import tenants as tn
    out: set = set()
    try:
        row = tn.get(tenant)
        name = str(getattr(row, "name", "") or "").strip().lower()
        if name:
            out.add(name)
            # …and the distinctive half of it on its own, because people write
            # "Eien" far more often than "Eien Health".
            for w in name.replace("-", " ").split():
                if len(w) >= 4 and w not in _GENERIC_NAME:
                    out.add(w)
        for e in kbm.entities(tenant, available_only=False):
            n = str(getattr(e, "name", "") or "").strip().lower()
            if len(n) >= 4:
                out.add(n)
    except Exception:                                            # noqa: BLE001
        return set()
    return out


def about_us(sentence: str, marks: set) -> bool:
    """Would this sentence still be true if the account did not exist?

    The owner's test, 2026-08-29, after a knee-pain article had every cited
    fact about the CONDITION reported as an unbacked brand claim: *"this isn't
    technically a claim because we're not claiming anything that the company
    does, has, is, or is associated with."* Right — and the reading had only
    one question for two different kinds of sentence.

    False here does NOT mean the sentence is free. It means it needs a source
    rather than an owner's approval. Two evidences, one for each kind of
    statement; neither is "nothing".
    """
    raw = str(sentence or "").strip()
    if _PRONOUN.search(raw) or _PRONOUN_START.match(raw):
        return True
    low = f" {raw.lower()} "
    return any(m in low for m in (marks or ()))


def off_catalogue(sentence: str, vocab: set) -> list:
    """Words this sentence recommends that the account has never mentioned.

    `[]` unless the sentence is RECOMMENDING. A mention is allowed on purpose:
    an article comparing this brand with what else is on the shelf has to be
    able to name the shelf. Only the steer is flagged, and it is flagged with
    the actual words so the reader can see whether it is a competitor
    comparison (fine) or a recommendation of something nobody sells (not).
    """
    low = f" {str(sentence or '').lower()} "
    if not vocab or not any(m in low for m in _RECOMMENDS):
        return []
    # The trigger words are not findings. "benchmark" appearing in the list
    # of things we have never heard of is noise that makes the real entries
    # harder to see.
    triggers = set()
    for m in _RECOMMENDS:
        triggers |= _tokens(m)
    unknown = [w for w in _tokens(sentence)
               if w not in vocab and w not in triggers and len(w) > 4]
    return sorted(set(unknown))[:4]


# ---------------------------------------------------------------------------
# The number, over time
# ---------------------------------------------------------------------------

def coverage_of(tenant: str, body: str, claim_ids: list | None = None) -> int:
    """The one number, for `ledger.record` to store on every output.

    `-1` when the output asserts nothing checkable — NOT 0, because "nothing
    here needed a claim" and "nothing here has one" are different facts and
    averaging them together is how a trend lies. Readers filter `>= 0`.
    """
    from . import kb as kbm
    try:
        ids = set(str(c) for c in (claim_ids or []) if c)
        claims = [c for c in kbm.claims(tenant)
                  if not ids or str(getattr(c, "id", "")) in ids]
        rep = annotate(body, claims)
    except Exception:                                            # noqa: BLE001
        return -1
    pct = rep.get("coverage_pct")
    return -1 if pct is None else int(pct)


def trend(tenant: str = "", days: int = 90) -> list:
    """Average grounding by system, and the direction it is moving.

    The reason the number is stored per output rather than recomputed: a
    recomputation reads TODAY's knowledge base, so an article written when the
    account had four claims would be scored against the forty it has now, and
    the trend would flatten itself every time somebody authored a claim. The
    stored number is what was true when it was written.
    """
    import datetime as dt

    from . import db
    since = db.utcnow() - dt.timedelta(days=max(1, int(days or 1)))
    with db.SessionLocal() as s:
        q = (s.query(db.Output)
             .filter(db.Output.created_at >= since,
                     db.Output.grounded_pct >= 0))
        if tenant:
            q = q.filter(db.Output.tenant == tenant)
        rows = q.order_by(db.Output.created_at.asc()).all()
        rows = [(r.system_key or "(none)", int(r.grounded_pct or 0),
                 db.as_utc(r.created_at)) for r in rows]

    by: dict = {}
    for key, pct, when in rows:
        by.setdefault(key, []).append((when, pct))
    out = []
    for key, pairs in sorted(by.items()):
        vals = [p for _w, p in pairs]
        half = max(1, len(vals) // 2)
        earlier, later = vals[:half], vals[half:] or vals[:half]
        was = round(sum(earlier) / len(earlier))
        now = round(sum(later) / len(later))
        # `moved` is None, not 0, when the window is too thin to say — the
        # same three-state shape `coverage_pct` uses for "asserted nothing".
        # Zero would read as "no change", which is a finding; this is the
        # absence of one.
        enough = min(len(earlier), len(later)) >= MIN_FOR_DIRECTION
        out.append({
            "system": key, "outputs": len(vals),
            "average": round(sum(vals) / len(vals)),
            "was": was, "now": now,
            "moved": (now - was) if enough else None,
            # The sparkline in the mockup: one point per output, oldest first.
            "series": vals[-24:],
        })
    return out


def proposed_claims(tenant: str) -> dict:
    """Sentences this account has already proposed as claims, awaiting review.

    ONE query, like `usage_counts`, because the alternative is a lookup per
    note on a page that can carry thirty of them.

    Keyed by `provenance.normalise` — the same comparable form the knowledge
    base uses to decide two claims are the same claim. Matching raw strings
    would show "Add claim" again on a sentence already proposed, because the
    stored row and the annotated sentence differ by a trailing full stop.
    """
    from . import db
    from . import provenance as prov
    out: dict = {}
    try:
        with db.SessionLocal() as s:
            rows = (s.query(db.KbClaim.id, db.KbClaim.claim)
                    .filter(db.KbClaim.tenant == tenant,
                            db.KbClaim.review == prov.PROPOSED).all())
        for cid, text in rows:
            key = prov.normalise(text or "")
            if key:
                out[key] = cid
    except Exception:                                            # noqa: BLE001
        return {}
    return out


def usage_counts(tenant: str) -> dict:
    """{claim_id: how many outputs cite it}. ONE query, not one per claim.

    "Used in 9 outputs" is what turns "this claim looks wrong" into "this
    claim is wrong in nine places", which is the difference between noticing
    something and fixing the cause of it.
    """
    from collections import Counter

    from . import db
    n: Counter = Counter()
    with db.SessionLocal() as s:
        for (ids,) in s.query(db.Output.claim_ids).filter(
                db.Output.tenant == tenant).all():
            for cid in (ids or []):
                n[str(cid)] += 1
    return dict(n)
