"""Does the rendered thing hold together — checked mechanically, before it ships.

The owner, 2026-08-26, with a real Baci campaign in hand: *"the copy is still
not making full sense when it tries to plug in items and it doesn't have a
self-evaluation script to ensure the email actually makes sense before it's
used."*

Four defects were in that one email, and **every one of them is findable
without asking a model anything**:

  * `picnic.nic.` — a word repeating its own tail, which is a string bug and
    not a judgement call;
  * the prose said *"the Acrylic Pitcher & Glasses Set is the one"* while every
    link and image in the artifact was the Blue Table Runner. It SOLD one
    product and LINKED another, so a reader who did exactly what the copy told
    them had nowhere to go;
  * the pull-quote — a slot styled for a written line — held a catalogue
    description verbatim, ending in that same mangled word;
  * `<span>P.S.</span> <p>…` opened a block inside an inline run, so the P.S.
    broke onto its own line in every client.

That is why this is deterministic code and not a model reading its own work.
`validator` refuses on RULES and this refuses on STRUCTURE; between them the
question "would a person wince at this" is mostly answered without anybody
having to guess. What is left over — is the argument any good — is what the
human approval is for, and no amount of self-evaluation replaces it.

**Findings are advisory by default and one is not.** `mangled_word` and
`unlinked_subject` block: the first is always a bug, and the second means the
call to action cannot be followed. The rest are flagged for a person, because
a heuristic that stops a send is one somebody switches off.
"""
from __future__ import annotations

import html as _html
import re

#: Template placeholders that are SUPPOSED to survive into the artifact — the
#: ESP fills them at send. Anything else in `[[ ]]` is a variable nobody
#: resolved, which reaches a reader as punctuation.
KNOWN_PLACEHOLDERS = ("contact.", "unsubscribe_link", "subscriber.", "shop.")

#: Words that make a Title Case phrase look like a product rather than a
#: proper noun. Deliberately narrow: this feeds a FLAG, and a wide net here
#: would fire on every brand name and city in every article.
_PRODUCT_TAIL = ("set", "sets", "pitcher", "glasses", "mug", "mugs", "runner",
                 "plate", "plates", "bowl", "bowls", "jug", "tray", "napkin",
                 "collection", "dinnerware", "tumbler", "tumblers", "carafe")

BLOCKING = ("mangled_word", "unlinked_subject")


def _text(doc: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", doc))).strip()


def _linked_labels(doc: str) -> set[str]:
    """Everything the artifact actually points at or shows, lowercased.

    Link text, image alts and product slugs together: a reader can reach a
    thing if it is linked, and can see it if it is pictured. Either counts.
    """
    out: set[str] = set()
    for alt in re.findall(r'alt="([^"]{2,80})"', doc):
        out.add(_html.unescape(alt).lower())
    for slug in re.findall(r"/products/([a-z0-9-]+)", doc):
        out.add(slug.replace("-", " ").lower())
    for inner in re.findall(r"<a\b[^>]*>(.*?)</a>", doc, re.S):
        label = _text(inner).lower()
        if 2 < len(label) < 80:
            out.add(label)
    return out


def _named_subjects(text: str) -> list[str]:
    """Title Case phrases that read like a product being recommended."""
    seen: list[str] = []
    for m in re.finditer(
            r"\b((?:[A-Z][a-z]+|&)(?:\s+(?:[A-Z][a-z]+|&|of|and)){1,5})\b", text):
        phrase = re.sub(r"\s+", " ", m.group(1)).strip()
        if phrase.split()[-1].lower() in _PRODUCT_TAIL and phrase not in seen:
            seen.append(phrase)
    return seen


def check(doc: str, *, kind: str = "email") -> list[dict]:
    """Every structural fault in one rendered artifact, worst first."""
    out: list[dict] = []
    text = _text(doc)

    # --- a word that repeats its own tail ---------------------------------
    for m in re.finditer(r"\b(\w{4,})([.!?])(\w{2,})\2", text):
        head, tail = m.group(1), m.group(3)
        if head.lower().endswith(tail.lower()):
            out.append({
                "rule": "mangled_word", "detail": f"{m.group(0)!r}",
                "fix": f"'{tail}' is already the end of '{head}' — the text was "
                       f"cut and re-joined. Fix the source string, not the copy."})

    # --- sold here, buyable nowhere ---------------------------------------
    linked = _linked_labels(doc)
    for phrase in _named_subjects(text):
        low = phrase.lower()
        if any(low in lab or lab in low for lab in linked):
            continue
        # Only when the copy actually POINTS at it. A passing mention is
        # prose; "X is the one" is an instruction with no way to comply.
        window = ""
        i = text.find(phrase)
        if i >= 0:
            window = text[i:i + len(phrase) + 60].lower()
        if re.search(r"\b(is the one|is what you want|start (?:here|with)|"
                     r"reach for|pick up|go for|try the)\b", window):
            out.append({
                "rule": "unlinked_subject", "detail": f"{phrase!r} is recommended and never linked",
                "fix": "link it, or recommend something the artifact actually "
                       "shows. A reader who does what the copy says has nowhere "
                       "to go."})

    # --- a quote slot holding catalogue copy -------------------------------
    for quote in re.findall(r"font-style:italic[^>]*>([^<]{20,400})<", doc):
        q = _html.unescape(quote).strip()
        if re.search(r"\b(shatterproof|dishwasher safe|BPA|set of \d|"
                     r"measures|dimensions|microwave safe)\b", q, re.I):
            out.append({
                "rule": "boilerplate_in_quote",
                "detail": f"{q[:90]!r}",
                "fix": "this slot is styled as a written line and holds a "
                       "product description. Write the line, or drop the slot."})

    # --- a block tag opening inside an inline run --------------------------
    for m in re.finditer(r"</(?:span|strong|b|em)>\s*<(p|div|table)\b", doc):
        out.append({
            "rule": "block_in_inline", "detail": m.group(0)[:60],
            "fix": f"a <{m.group(1)}> after an inline label breaks the line in "
                   f"every client — use a <span> or move the label inside."})

    # --- a variable nobody filled ------------------------------------------
    for var in set(re.findall(r"\[\[([^\]]{1,60})\]\]", doc)):
        if not any(k in var for k in KNOWN_PLACEHOLDERS):
            out.append({
                "rule": "placeholder_leak", "detail": f"[[{var}]]",
                "fix": "nothing resolves this, so it reaches the reader as "
                       "punctuation. Fill it or remove it."})

    # --- the same sentence twice -------------------------------------------
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.strip()) > 40]
    for s in {x for x in sents if sents.count(x) > 1}:
        out.append({"rule": "repeated_sentence", "detail": s[:90],
                    "fix": "said twice in one artifact"})

    out.sort(key=lambda f: f["rule"] not in BLOCKING)
    return out


def blocking(findings: list) -> list[dict]:
    """The subset that must stop an artifact rather than annotate it."""
    return [f for f in findings if f["rule"] in BLOCKING]
