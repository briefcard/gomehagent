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
VERSION = 2
USES_MODEL = False
#: A two-row table is a layout, not a census.
MIN_ROWS = 3
#: A label names what follows. A longer heading, or one holding a figure, is a
#: sentence: "Transak supports 136+ cryptocurrencies across 45+ blockchains"
#: says nothing about the table beneath it being a list of crypto assets.
MAX_LABEL_WORDS = 6
#: This share of a list's items being links makes it a menu, not a census.
MENU_SHARE = 0.8
#: A table naming this many US states is a state count, whatever it is titled.
MIN_STATES = 10
#: The same licence-naming heading this many times is a licence count: a
#: compliance page can state each licence as its own section and never a table.
MIN_HEADINGS = 3
US_STATES = frozenset("""alabama|alaska|arizona|arkansas|california|colorado|
connecticut|delaware|florida|georgia|hawaii|idaho|illinois|indiana|iowa|kansas|
kentucky|louisiana|maine|maryland|massachusetts|michigan|minnesota|mississippi|
missouri|montana|nebraska|nevada|new hampshire|new jersey|new mexico|new york|
north carolina|north dakota|ohio|oklahoma|oregon|pennsylvania|rhode island|
south carolina|south dakota|tennessee|texas|utah|vermont|virginia|washington|
west virginia|wisconsin|wyoming""".replace("\n", "").split("|"))


def _is_label(text: str) -> bool:
    return (bool(text) and not re.search(r"\d", text)
            and len(text.split()) <= MAX_LABEL_WORDS)


def _is_menu(items: list[str], doc: dict) -> bool:
    """A list of the page's own links: a footer, a sidebar, a contents box."""
    links = {" ".join((x.get("text") or "").split()).lower()
             for x in doc.get("links", [])}
    hits = sum(1 for i in items if " ".join(i.split()).lower() in links)
    return bool(items) and hits / len(items) >= MENU_SHARE


def _states_named(kind: str, it: dict) -> list[str]:
    cells = ([r[0] for r in it.get("rows", []) if r] if kind == "table"
             else it.get("items", []))
    seen = {" ".join(c.split()).lower() for c in cells}
    return sorted(seen & US_STATES)


def subject_in(text: str, terms: tuple = (), singular: bool = False) -> tuple[str, str]:
    """(subject, the word that named it) for the most specific heading text.

    `singular` is for a column header, where "State" means a column of states.
    In a heading the same word is an adjective: "U.S. State Privacy Notice"."""
    low = (text or "").lower()
    for term, subj in terms:
        if re.search(rf"\b{re.escape(term.lower())}\b", low):
            return subj, term
    for pat, subj in statements.SUBJECTS:
        m = re.search(rf"\b(?:{pat})\b", low, re.I)
        if m:
            return subj, m.group(0)
    if not singular:
        return "", ""
    # Singular header words: "Country", "State", "Licence".
    for word in re.findall(r"[a-z][a-z.]+", low):
        for cand in (word + "s", word[:-1] + "ies" if word.endswith("y") else ""):
            if cand and statements.subject_for(cand):
                return statements.subject_for(cand), word
    return "", ""


def _named(section: str, caption: str, headers: list[str], terms: tuple):
    """Caption, then the NEAREST heading, then the first column header.

    Only the nearest: a footer list sits under "Company", and walking up to
    the page's title turned its eight links into "Supported Countries: 8"."""
    parts = [p for p in (section or "").split(" › ") if p]
    for txt in [caption] + parts[-1:]:
        if not _is_label(txt):
            continue
        subj, word = subject_in(txt, terms)
        if subj:
            return subj, word, txt
    if headers:
        subj, word = subject_in(headers[0], terms, singular=True)
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
            if kind == "list" and _is_menu(it.get("items", []), doc):
                continue
            states = _states_named(kind, it)
            if len(states) >= MIN_STATES:
                k = len(states)
                out.append({
                    "subject": "coverage.states", "value": str(k), "number": float(k),
                    "qualifier": "counted", "unit": "states",
                    "match": f"{k} {kind} rows",
                    "text": (f"A {kind} naming {k} US states "
                             f"(e.g. {', '.join(s.title() for s in states[:3])})"),
                    "field": kind, "section": it.get("section", ""),
                    "locator": f"{kind} {i}"})
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
    named = [h["text"] for h in doc.get("headings", [])
             if _is_label(h.get("text", ""))
             and subject_in(h["text"], terms)[0] == "legal.licences"]
    if len(named) >= MIN_HEADINGS:
        k = len(named)
        out.append({
            "subject": "legal.licences", "value": str(k), "number": float(k),
            "qualifier": "counted", "unit": "licences", "match": f"{k} headings",
            "text": f"{k} sections each headed as a licence (e.g. {named[0]})",
            "field": "headings", "section": "", "locator": "headings"})
    return out
