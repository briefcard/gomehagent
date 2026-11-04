"""Every "<number> <unit>" a page states — body, furniture and page data."""
from __future__ import annotations

from ... import statements

NAME = "numbers"
VERSION = 1
USES_MODEL = False


def run(doc: dict, terms: tuple = ()) -> list[dict]:
    return statements.sweep_lines(doc.get("lines", []), doc.get("page_data", []),
                                  doc.get("body_blocks", []), terms)
