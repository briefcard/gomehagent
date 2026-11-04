"""A table or list under a heading that names a subject IS a count.

The Transak compliance page states its licences as a 19-row table under
"State licences" and never writes the number 19. A sweep for "<n> licences"
finds nothing there, and the one figure the page is the authority for is
lost. This reader turns "a table/list of N rows under a heading naming
licences / countries / states …" into a statement with qualifier `counted`,
located by its position on the page, so it sits beside the stated figures
and the disagreement between "19 rows" and "18+ licences" is visible.
"""
from __future__ import annotations

import re

from ... import statements

NAME = "enumerations"
VERSION = 1
USES_MODEL = False
#: A two-row table is a layout, not a census.
MIN_ROWS = 3


def subject_in(text: str, terms: tuple = ()) -> tuple[str, str]:
    """(subject, the word that named it) for the most specific heading text."""
    low = (text or "").lower()
    for term, subj in terms:
        if re.search(rf"\b{re.escape(term.lower())}\b", low):
            return subj, term
    for pat, subj in statements.SUBJECTS:
        m = re.search(rf"\b(?:{pat})\b", low, re.I)
        if m:
            return subj, m.group(0)
    # Singular header words: "Country", "State", "Licence".
    for word in re.findall(r"[a-z][a-z.]+", low):
        for cand in (word + "s", word[:-1] + "ies" if word.endswith("y") else ""):
            if cand and statements.subject_for(cand):
                return statements.subject_for(cand), word
    return "", ""


def _named(section: str, caption: str, headers: list[str], terms: tuple):
    """Deepest heading first, then caption, then the first column header."""
    parts = [p for p in (section or "").split(" › ") if p]
    for txt in [caption] + parts[::-1]:
        subj, word = subject_in(txt, terms)
        if subj:
            return subj, word, txt
    if headers:
        subj, word = subject_in(headers[0], terms)
        if subj:
            return subj, word, headers[0]
    return "", "", ""


def run(doc: dict, terms: tuple = ()) -> list[dict]:
    out = []
    for kind, items in (("table", doc.get("tables", [])), ("list", doc.get("lists", []))):
        for i, it in enumerate(items, 1):
            n = it.get("n_rows") if kind == "table" else it.get("n_items")
            if not n or n < MIN_ROWS:
                continue
            subj, word, named_by = _named(it.get("section", ""), it.get("caption", ""),
                                          it.get("headers", []), terms)
            if not subj:
                continue
            sample = (it.get("rows") or [[]])[0] if kind == "table" else it.get("items", [])[:3]
            out.append({
                "subject": subj, "value": str(n), "number": float(n),
                "qualifier": "counted", "unit": word, "match": f"{n} {kind} rows",
                "text": (f"{named_by}: a {kind} of {n} "
                         f"{'rows' if kind == 'table' else 'items'} "
                         f"(e.g. {', '.join(str(x) for x in sample)[:160]})"),
                "field": kind, "section": it.get("section", ""),
                "locator": f"{kind} {i}"})
    return out
