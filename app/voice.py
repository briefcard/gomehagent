"""Propose a brand's voice from what it has already written.

`voice.tone` blocks `/resolve` on every account, and unlike the rest of the
knowledge base it is genuinely derivable. The contrast is exact: a crawler can
never derive `banned_claims`, because a site records what a brand *does* say
and the ban list is what it must *not* — and voice is entirely the first of
those. Baci's own site saying "handmade in Italy" is why the ban list has to be
authored; it is also, in the same breath, evidence of how they write.

Two halves, deliberately, because they have different failure modes:

**Measured** — sentence length, contractions, second person, questions,
exclamations. Pure arithmetic over the text, no model, nothing to fabricate.
These are the parts of "voice" that are actually countable, and they were
being left to a model that had no need to guess them.

**Inferred** — the tone words themselves. A judgement, so a model makes it,
which decision #1 permits at the edges. But it comes back with **verbatim
exemplar sentences**, and every exemplar is checked against the source the same
way `extract._verify` checks a claim span. A tone word you cannot see the
evidence for is a tone word nobody can review.

Nothing here writes. It proposes; `kb.set_brand` is still the only way a voice
lands, and a human still types it. The system refuses rather than invents, and
"the model suggested it" is not a reason to skip the person.

**Samples are filtered through `banned_claims` first.** Deriving voice from a
site that says "hand-painted in Italy" would otherwise hand back exemplar
sentences the brand is not allowed to use — teaching the voice layer the exact
phrasing the compliance layer exists to catch.
"""
from __future__ import annotations

import logging
import re

from . import config, kb

log = logging.getLogger("voice")

#: `kb.set_brand` refuses a tone longer than eight words, so a proposal that
#: cannot be applied is not a proposal. Kept below it on purpose.
MAX_TONE_WORDS = 6

#: Enough sentences for the arithmetic to mean anything. Below this the
#: measurements are reported and the conclusion is not, which is the same rule
#: `CALIBRATION_MIN_N` applies to the classifier.
MIN_SENTENCES = 20

_CONTRACTION = re.compile(r"\b\w+'(s|t|re|ve|ll|d|m)\b", re.I)
_SECOND = re.compile(r"\b(you|your|yours|you're|you'll|you've)\b", re.I)
_FIRST_PL = re.compile(r"\b(we|our|ours|we're|we've|us)\b", re.I)


def sentences(texts: list[str]) -> list[str]:
    """Split to sentences, dropping the fragments that are page furniture.

    A nav label and a button are not how a brand writes, and `_clean` keeps
    both — a known defect in the crawler. Length is the cheap filter that gets
    most of it: "Shop now" and "Care guide" do not survive a four-word floor.
    """
    out = []
    for t in texts or []:
        for s in re.split(r"(?<=[.!?])\s+", (t or "").strip()):
            s = " ".join(s.split())
            if len(s.split()) >= 4 and not s.isupper():
                out.append(s)
    return out


def measure(texts: list[str]) -> dict:
    """The countable half of voice. No model, so nothing to verify."""
    sents = sentences(texts)
    if not sents:
        return {"sentences": 0, "enough": False,
                "why": "no prose long enough to measure"}
    words = [w for s in sents for w in s.split()]
    n = len(sents)
    return {
        "sentences": n,
        "enough": n >= MIN_SENTENCES,
        "avg_sentence_words": round(len(words) / n, 1),
        "avg_word_length": round(sum(len(w) for w in words) / max(len(words), 1), 1),
        "contractions_per_100w": round(
            100 * len(_CONTRACTION.findall(" ".join(sents))) / max(len(words), 1), 1),
        "second_person_per_100w": round(
            100 * len(_SECOND.findall(" ".join(sents))) / max(len(words), 1), 1),
        "first_person_plural_per_100w": round(
            100 * len(_FIRST_PL.findall(" ".join(sents))) / max(len(words), 1), 1),
        "questions_pct": round(100 * sum(1 for s in sents if s.endswith("?")) / n, 1),
        "exclamations_pct": round(100 * sum(1 for s in sents if s.endswith("!")) / n, 1),
        "why": ("" if n >= MIN_SENTENCES else
                f"{n} sentences is under {MIN_SENTENCES} — read the numbers, "
                f"do not lean on them"),
    }


def describe(m: dict) -> list[dict]:
    """Turn the measurements into words, deterministically.

    Not an inference — a restatement. Each descriptor carries the number it
    came from, so it can be disagreed with by looking rather than by trusting.
    That is what separates this from the model half: no judgement is being
    made, a threshold is being crossed.

    It exists because the model half can be unavailable — an exhausted key, a
    spend limit — and an account still needs a voice to unblock `/resolve`.
    Measured-only has to be worth something on its own.
    """
    if not m.get("sentences"):
        return []
    out = []

    def add(word, why):
        out.append({"word": word, "because": why})

    c = m["contractions_per_100w"]
    if c < 0.5:
        add("formal", f"{c} contractions per 100 words — it writes 'do not'")
    elif c > 2.0:
        add("conversational", f"{c} contractions per 100 words")

    w = m["avg_sentence_words"]
    if w < 12:
        add("brisk", f"{w} words per sentence")
    elif w > 20:
        add("expansive", f"{w} words per sentence")

    if m["exclamations_pct"] < 1:
        add("understated", f"{m['exclamations_pct']}% of sentences exclaim")
    elif m["exclamations_pct"] > 5:
        add("energetic", f"{m['exclamations_pct']}% of sentences exclaim")

    if m["second_person_per_100w"] > 2:
        add("direct", f"{m['second_person_per_100w']} 'you' per 100 words")
    if m["avg_word_length"] < 5.2:
        add("plain", f"{m['avg_word_length']} letters per word")
    return out[:MAX_TONE_WORDS]


def sample_warnings(m: dict) -> list[str]:
    """What about this sample would mislead a reader of the numbers.

    A brand does not ask 13.9% of its sentences as questions — an FAQ page
    does, and its headings are customer objections rather than brand voice.
    Reporting the metric without this makes the sample look like a voice it is
    not. (Those headings are worth mining as objections, which is a different
    job for `extract.extract_qa`.)
    """
    out = []
    if m.get("questions_pct", 0) > 8:
        out.append(
            f"{m['questions_pct']}% of sentences are questions — that is an "
            f"FAQ in the sample, not a brand that asks things. The tone words "
            f"are still fair; the question rate is not a voice trait here.")
    if m.get("sentences", 0) < MIN_SENTENCES:
        out.append(f"only {m['sentences']} sentences — too few to lean on")
    return out


def _drop_banned(tenant: str, sents: list[str]) -> tuple[list[str], list[str]]:
    """Remove anything the brand has barred itself from saying.

    A sample containing "hand-painted" would produce exemplars the brand cannot
    use, which is worse than no proposal: it teaches the voice layer the exact
    phrasing the compliance layer exists to catch.
    """
    banned = [b.lower() for b in (kb.banned_claims(tenant) or [])]
    if not banned:
        return sents, []
    kept, dropped = [], []
    for s in sents:
        low = s.lower()
        (dropped if any(b in low for b in banned) else kept).append(s)
    return kept, dropped


_PROMPT = """You are reading sentences a brand has published, to describe HOW
it writes and — strictly from what is in front of you — WHAT it does.

Return JSON only:
{"tone": ["word", "word"], "exemplars": ["<verbatim sentence>", ...],
 "positioning": "one sentence: what they do, and for whom",
 "elevator": "the one-liner a stranger could repeat correctly"}

Rules:
- At most %d tone words. Plain adjectives a copywriter would use.
- Every exemplar must be copied EXACTLY from the input, character for
  character. Anything else is discarded by code before you are read.
- Choose exemplars that show the tone words. 2-5 of them.
- Describe voice, not products. "warm" not "colourful tableware".
- positioning and elevator may assert ONLY what these sentences assert: no
  numbers, origins, materials, guarantees or superlatives that are not in
  the input. If the copy never says what they do, return "" for both — an
  empty answer beats an invented one.
"""


def _infer(tenant: str, sents: list[str]) -> tuple[dict, str]:
    """Tone words plus exemplars, with the exemplars verified. Never raises."""
    if not config.ANTHROPIC_API_KEY:
        return {}, "ANTHROPIC_API_KEY is not set — measured metrics only"
    try:
        import json as _json

        import anthropic
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        sample = sents[:120]
        msg = client.messages.create(
            model=config.CLAUDE_MODEL, max_tokens=800,
            system=_PROMPT % MAX_TONE_WORDS,
            messages=[{"role": "user", "content": "\n".join(sample)}])
        raw = msg.content[0].text.strip()
        try:
            from . import usage
            usage.log_usage("voice_propose", config.CLAUDE_MODEL, msg,
                            tenant=tenant)
        except Exception:  # noqa: BLE001 — never fail on accounting
            pass

        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end < 0:
            return {}, "model did not return JSON"
        data = _json.loads(raw[start:end + 1])

        # The same guarantee `extract._verify` gives a claim span: whatever the
        # model returned, an exemplar survives only if it is genuinely in the
        # source. A quote nobody said is not evidence.
        pool = {" ".join(s.split()) for s in sample}
        kept, invented = [], []
        for ex in data.get("exemplars", []):
            norm = " ".join(str(ex).split())
            (kept if norm in pool else invented).append(norm)

        tone = [str(w).strip().lower() for w in data.get("tone", []) if str(w).strip()]
        return {"tone": tone[:MAX_TONE_WORDS], "exemplars": kept[:5],
                "discarded_exemplars": invented,
                # Syntheses, not quotes — they cannot be verbatim-verified the
                # way exemplars are, which is exactly why they land as a
                # PROPOSAL a person reads before anything is saved. Clipped so
                # a runaway paragraph cannot masquerade as a one-liner.
                "positioning": str(data.get("positioning") or "").strip()[:300],
                "elevator": str(data.get("elevator") or "").strip()[:200]}, ""
    except Exception as exc:  # noqa: BLE001
        return {}, f"{exc.__class__.__name__}: {str(exc)[:120]}"


def propose(tenant: str, texts: list[str]) -> dict:
    """Measure the voice, infer a tone for it, and write nothing.

    The return is something a person reads and then types, or edits. That is
    the point: `set_brand` remains the only way a voice lands.
    """
    raw = sentences(texts)
    kept, dropped = _drop_banned(tenant, raw)
    stats = measure(kept)
    inferred, why = _infer(tenant, kept) if kept else ({}, "nothing to read")

    measured_words = describe(stats)
    # The model's tone words when they exist, the measured ones when they do
    # not. An account still needs a voice to unblock a draft, and an exhausted
    # key is not a reason to leave the field empty when the arithmetic already
    # said something defensible.
    tone = inferred.get("tone", []) or [d["word"] for d in measured_words]
    return {
        "tenant": tenant,
        "measured": stats,
        "measured_descriptors": measured_words,
        "sample_warnings": sample_warnings(stats),
        "tone": tone,
        "tone_from": ("model, with evidence" if inferred.get("tone")
                      else "measurement only — no model ran"),
        # Empty when the model did not run or the copy never says what the
        # business does — arithmetic can describe a voice, it cannot state a
        # positioning, and inventing one here would put words in the brand's
        # mouth at the exact spot built to prevent that.
        "positioning": inferred.get("positioning", ""),
        "elevator": inferred.get("elevator", ""),
        "suggested_command": (
            f"set tone: {', '.join(tone)}" if tone else ""),
        "evidence": inferred.get("exemplars", []),
        "discarded_exemplars": inferred.get("discarded_exemplars", []),
        "sentences_read": len(kept),
        "dropped_for_banned_claims": len(dropped),
        "dropped_examples": dropped[:3],
        "degraded": why,
        "applied": False,
        "note": ("proposed only — nothing was written. Read the evidence, then "
                 "set it on the Knowledge tab. A tone you cannot see the "
                 "sentences for is one nobody can review."),
    }


def gather(tenant: str, limit: int = 25) -> tuple[list[str], str]:
    """Prose from this account's own site. Returns (texts, note).

    The site is the source every account has. Sent mail is the better signal —
    it is how they actually talk to one customer rather than how an agency
    wrote their homepage — and `email_harvest` already walks it, so wiring that
    in is the next increment rather than a second crawler here.
    """
    import httpx

    from . import compliance, tenants
    t = tenants.get(tenant)
    if not t or not t.domain:
        return [], "no domain on file for this account"
    pages, how = compliance.discover_pages(t.domain, limit=limit * 4)
    texts, read = [], 0
    for p in pages:
        if read >= limit:
            break
        url = p.get("url") if isinstance(p, dict) else p
        if not url or compliance.skip_url(url):
            continue
        try:
            r = httpx.get(url, timeout=25, follow_redirects=True,
                          headers=compliance.HEADERS)
            if r.status_code != 200:
                continue
            blocks = compliance.text_blocks(r.text)
            if compliance.is_dead_page(r.text, " ".join(blocks)):
                continue
            texts.extend(blocks)
            read += 1
        except Exception as exc:  # noqa: BLE001 — one bad page is not a failure
            log.debug("voice gather skipped %s: %s", url, exc)
    return texts, f"read {read} pages via {how}"
