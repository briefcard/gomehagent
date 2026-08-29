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


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", str(text or ""))
            if s.strip()]


def plain_text(body: str) -> str:
    """Markup out, one space between everything. Headings are kept — an H2 can
    assert as loudly as a paragraph ("Glucosamine and chondroitin work")."""
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", str(body or ""),
               flags=re.I | re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    t = (t.replace("&amp;", "&").replace("&nbsp;", " ")
         .replace("&#39;", "'").replace("&quot;", '"'))
    return re.sub(r"[ \t]+", " ", t).strip()


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

        sentences  [{text, backed, assertion, claims:[{id, claim, evidence}]}]
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
                    "claims": hits})

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
        out.append({
            "system": key, "outputs": len(vals),
            "average": round(sum(vals) / len(vals)),
            "was": round(sum(earlier) / len(earlier)),
            "now": round(sum(later) / len(later)),
            # The sparkline in the mockup: one point per output, oldest first.
            "series": vals[-24:],
        })
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
