"""Email craft, as checks rather than as adjectives in a prompt.

The banned-claims validator settled the compliance half of this argument long
ago: a prompt mostly obeys, a validator always blocks. What was never encoded
is the CRAFT half — the difference between an email a person reads and one
they archive. That half had been living entirely inside the drafting prompt,
which means it held for whichever client the prompt was last tuned against and
drifted everywhere else.

So the rules below are code, and they come from the direct-response record
rather than from taste:

* **The subject is most of the work.** Ogilvy's measured line is that five
  times as many people read the headline as the body, so it is worth 80% of
  the effort. Chase Dimond's e-commerce version is narrower and more usable:
  3–8 words, and the preview text must EXTEND the subject rather than repeat
  it — repeating wastes the only other line the inbox shows.
* **Specificity or nothing.** Hopkins, 1923: "Platitudes and generalities roll
  off the human understanding like water from a duck." Every brand writes
  "premium quality"; a number, a material or a timeframe is what a reader
  actually believes.
* **Proof, when you ask.** Bencivenga's equation puts unquestionable proof
  beside the promise. An email that asks for money and offers no evidence is
  the shape that trains a list to ignore you.
* **Honest urgency.** Kennedy: there is always a reason to respond now. And
  Hormozi, on the same page: the most ethical scarcity strategy is honesty. A
  deadline the data cannot support is the one kind of urgency this system
  must be unable to produce — so it is checked against a source, not a mood.
* **Written to one person.** Halbert's A-pile: a personal-looking letter
  survives the sort a commercial-looking mailer does not. The Hustle's house
  rule operationalises it — write like you talk, sentences under 25 words.

TWO SEVERITIES, and the split is deliberate. `block` findings are ones where
shipping is worse than not shipping — an unbacked deadline is a lie in the
client's name. Everything else is `nudge`: real craft advice, handed to the
drafter to fix on the next pass, but never a reason to stop a campaign. A
9-word subject line is not a compliance event, and a system that treats it as
one teaches its owner to switch the checks off.
"""
from __future__ import annotations

import re

#: Words that promise something and deliver nothing — the ones every brand in
#: every category writes, which is exactly why they carry no information. Kept
#: deliberately short: this is a list of EMPTY superlatives, not a style
#: preference, and a long list becomes a vocabulary ban nobody can satisfy.
PLATITUDES = (
    "premium quality", "unmatched", "unparalleled", "world-class",
    "cutting-edge", "state-of-the-art", "elevate your", "game-changing",
    "revolutionary", "best-in-class", "top-notch", "second to none",
    "exceptional quality", "finest quality", "unbeatable",
)

#: Urgency language. Saying any of this without a real deadline or a real
#: count behind it is the manufactured scarcity both Kennedy and Hormozi warn
#: against — and the version a machine produces at scale is worse than the
#: version a person talks themselves into once.
URGENCY = (
    "last chance", "ends tonight", "ends today", "final hours", "hurry",
    "don't miss out", "act now", "limited time", "while supplies last",
    "only a few left", "selling fast", "almost gone", "expires",
    "deadline", "before it's gone", "running out",
)

SUBJECT_WORDS = (3, 8)
LONG_SENTENCE = 25


def _words(s: str) -> list[str]:
    return [w for w in re.split(r"\s+", str(s or "").strip()) if w]


def _sentences(s: str) -> list[str]:
    return [x.strip() for x in re.split(r"(?<=[.!?])\s+", str(s or "")) if x.strip()]


def _find(text: str, phrases) -> list[str]:
    low = str(text or "").lower()
    return [p for p in phrases if re.search(r"\b" + re.escape(p), low)]


def review(*, subject: str = "", preheader: str = "", body: str = "",
           intent: str = "", asks: bool = False, has_proof: bool = False,
           urgency_backed_by: str = "") -> list[dict]:
    """Craft findings for one email. `[]` means nothing to say.

    `urgency_backed_by` is the SOURCE of any deadline or scarcity — a plan's
    deadline field, a live inventory reading. Empty means there is none, and
    then urgency language is a claim with nothing under it.
    """
    out: list[dict] = []

    def add(sev, rule, detail, fix):
        out.append({"severity": sev, "rule": rule, "detail": detail, "fix": fix})

    # --- the subject and its second line ---------------------------------
    n = len(_words(subject))
    if subject and not (SUBJECT_WORDS[0] <= n <= SUBJECT_WORDS[1]):
        add("nudge", "subject_length",
            f"the subject is {n} words",
            f"aim for {SUBJECT_WORDS[0]}–{SUBJECT_WORDS[1]} words — long "
            f"subjects are cut by the inbox, and short ones are read")
    if subject and subject.strip() == subject.strip().upper() and n > 1:
        add("nudge", "subject_shouting", "the subject is in capitals",
            "write it in sentence case; capitals read as an advertisement "
            "and are a spam signal")
    if subject and preheader:
        s_low, p_low = subject.strip().lower(), preheader.strip().lower()
        if p_low == s_low or p_low.startswith(s_low[:24]) or s_low.startswith(p_low[:24]):
            add("nudge", "preheader_repeats",
                "the preview text repeats the subject",
                "the preview is a second line of real estate — use it to "
                "extend the subject, never to echo it")

    # --- what the words are actually worth --------------------------------
    said = _find(f"{subject} {preheader} {body}", PLATITUDES)
    if said:
        add("nudge", "platitude",
            "empty superlatives: " + ", ".join(sorted(set(said))[:4]),
            "replace each with something specific — a number, a material, a "
            "timeframe, a name — or cut the sentence")

    longs = [s for s in _sentences(body) if len(_words(s)) > LONG_SENTENCE]
    if len(longs) >= 2:
        add("nudge", "long_sentences",
            f"{len(longs)} sentences run over {LONG_SENTENCE} words",
            "break them up; email is read on a phone, at a glance")

    # --- the ask ----------------------------------------------------------
    if asks and not has_proof:
        add("nudge", "no_proof",
            "this send asks for the sale and carries no proof",
            "add a quote or a figure from an approved claim — a promise with "
            "nothing under it is the shape a list learns to ignore")

    urgent = _find(f"{subject} {preheader} {body}", URGENCY)
    if urgent and not urgency_backed_by:
        add("block", "unbacked_urgency",
            "urgency with nothing behind it: " + ", ".join(sorted(set(urgent))[:4]),
            "either put a real deadline or stock count on the plan — which "
            "this will then state exactly — or drop the urgency language; a "
            "deadline that does not exist is a lie told in the client's name")

    return out


def block_reasons(findings: list[dict]) -> list[dict]:
    return [f for f in findings or [] if f.get("severity") == "block"]


def as_prompt(findings: list[dict]) -> str:
    """The findings, written for the drafter's next attempt."""
    if not findings:
        return ""
    return ("\n\n## Craft problems with your draft — fix every one\n"
            + "\n".join(f"- {f['detail']} → {f['fix']}" for f in findings))
