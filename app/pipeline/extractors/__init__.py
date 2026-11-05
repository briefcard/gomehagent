"""EXTRACT — every registered reader over one Document, same Statement record.

BUILD-MAP §3.3. An extractor is a module with `NAME`, `VERSION`,
`USES_MODEL` and `run(doc, terms) -> list[statement]`. Adding a reader is
adding a module to `EXTRACTORS`; bumping its VERSION makes `reprocess`
re-read every stored page with it, with zero fetches.

Every statement carries `extractor` and `extractor_version`, so the Site facts
view can say which reader saw a figure, and a broken reader can be switched
off (`DISABLED`) without stopping the others.
"""
from __future__ import annotations

from . import availability, enumerations, numbers, structured

EXTRACTORS = [numbers, enumerations, structured, availability]
#: Kill switch per reader (BUILD-MAP §10): names listed here do not run.
DISABLED: set[str] = set()


def registry() -> list[dict]:
    return [{"name": e.NAME, "version": e.VERSION, "uses_model": e.USES_MODEL,
             "enabled": e.NAME not in DISABLED} for e in EXTRACTORS]


def run_all(doc: dict, terms: tuple = ()) -> tuple[list[dict], dict]:
    """(statements, per-extractor counts) for one Document."""
    out: list[dict] = []
    counts: dict[str, int] = {}
    for e in EXTRACTORS:
        if e.NAME in DISABLED:
            counts[e.NAME] = -1
            continue
        got = e.run(doc, terms)
        for st in got:
            st.setdefault("extractor", e.NAME)
            st.setdefault("extractor_version", e.VERSION)
        counts[e.NAME] = len(got)
        out += got
    return out, counts
