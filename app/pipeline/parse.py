"""PARSE — a stored page becomes a Document: blocks, sections, tables, lists, data.

BUILD-MAP §4 PARSE. Code only, deterministic, keyed by (snapshot, version).
Every reader downstream reads THIS, never the raw HTML, so a table is a
table (header × row × cell) rather than a run of short lines, a list under
"Supported countries" is a list of N items, and content a slider or tab keeps
off-screen is still read — it is in the markup — and FLAGGED, so a reviewer
knows the page holds content a visitor may not see at first glance.

What the claim reader always saw is kept as `blocks` (same function, same
JS fallback), so moving the harvest onto Documents changes nothing it reads.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser

from .. import compliance, statements
from . import fetch as _fetch

#: Bump when the Document changes shape or content; stored documents at an
#: older version are re-parsed from the stored bytes, never refetched.
VERSION = 2
#: Body text below this many characters means the page is drawn by JavaScript
#: and its copy is in the embedded data (same floor as harvest.JS_THIN_CHARS).
JS_THIN_CHARS = 200

_HEAD = {"h1", "h2", "h3", "h4", "h5", "h6"}
_SKIP = {"script", "style", "noscript", "svg"}
#: Markup that keeps content off-screen until a visitor clicks or swipes.
_INTERACTIVE = re.compile(
    r"swiper|slick|carousel|slider|tab-?pane|tabs?__|accordion|collaps|modal|"
    r"toggle|dropdown|disclosure", re.I)
_NUM_TOKEN = re.compile(r"(?<![\w.])\d[\d,.]*\+?")


class _Walker(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.heading: list[str] = [""] * 6
        self.in_head: int | None = None
        self.head_buf: list[str] = []
        self.headings: list[dict] = []
        self.tables: list[dict] = []
        self.tstack: list[dict] = []
        self.cell: list[str] | None = None
        self.row: list[str] | None = None
        self.row_is_head = False
        self.lists: list[dict] = []
        self.lstack: list[dict] = []
        self.item: list[str] | None = None
        self.hints: set[str] = set()
        self.hidden = 0
        self.depth_hidden: list[str] = []

    # -- helpers
    def _section(self) -> str:
        return " › ".join(h for h in self.heading if h)

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if tag in _SKIP:
            self.skip += 1
            return
        cls = a.get("class", "") + " " + a.get("id", "")
        m = _INTERACTIVE.search(cls)
        if m:
            self.hints.add(m.group(0).lower())
        if ("hidden" in a or a.get("aria-hidden") == "true"
                or re.search(r"display\s*:\s*none", a.get("style", ""), re.I)):
            self.hidden += 1
        if tag in ("details", "template"):
            self.hints.add(tag)
        if tag in _HEAD:
            self.in_head, self.head_buf = int(tag[1]), []
        elif tag == "table":
            self.tstack.append({"section": self._section(), "caption": "",
                                "headers": [], "rows": []})
        elif tag == "caption" and self.tstack:
            self.cell = []
        elif tag == "tr" and self.tstack:
            self.row, self.row_is_head = [], False
        elif tag in ("td", "th") and self.tstack:
            self.cell = []
            if tag == "th":
                self.row_is_head = True
        elif tag in ("ul", "ol"):
            self.lstack.append({"section": self._section(), "items": []})
        elif tag == "li" and self.lstack:
            self.item = []

    def handle_endtag(self, tag):
        if tag in _SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if tag in _HEAD and self.in_head is not None:
            text = " ".join(" ".join(self.head_buf).split())
            lvl = self.in_head
            self.heading[lvl - 1] = text
            for i in range(lvl, 6):
                self.heading[i] = ""
            if text:
                self.headings.append({"level": lvl, "text": text})
            self.in_head = None
        elif tag == "caption" and self.tstack and self.cell is not None:
            self.tstack[-1]["caption"] = " ".join(" ".join(self.cell).split())
            self.cell = None
        elif tag in ("td", "th") and self.cell is not None and self.row is not None:
            self.row.append(" ".join(" ".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None and self.tstack:
            t = self.tstack[-1]
            if any(self.row):
                if self.row_is_head and not t["headers"] and not t["rows"]:
                    t["headers"] = self.row
                else:
                    t["rows"].append(self.row)
            self.row = None
        elif tag == "table" and self.tstack:
            t = self.tstack.pop()
            if t["rows"] or t["headers"]:
                t["n_rows"] = len(t["rows"])
                self.tables.append(t)
        elif tag == "li" and self.item is not None and self.lstack:
            txt = " ".join(" ".join(self.item).split())
            if txt:
                self.lstack[-1]["items"].append(txt)
            self.item = None
        elif tag in ("ul", "ol") and self.lstack:
            lst = self.lstack.pop()
            if lst["items"]:
                lst["n_items"] = len(lst["items"])
                self.lists.append(lst)

    def handle_data(self, data):
        if self.skip:
            return
        if self.in_head is not None:
            self.head_buf.append(data)
        if self.cell is not None:
            self.cell.append(data)
        if self.item is not None:
            self.item.append(data)


def parse(html: str) -> dict:
    """The Document for one page. Pure: same HTML, same Document."""
    html = html or ""
    blocks = compliance.text_blocks(html)
    text = " ".join(blocks)
    data_lines = statements.page_data_lines(html)
    from_data = False
    read_blocks = blocks
    if len(text) < JS_THIN_CHARS and len(" ".join(data_lines)) > len(text):
        read_blocks, text, from_data = data_lines, " ".join(data_lines), True
    w = _Walker()
    try:
        w.feed(html)
        w.close()
    except Exception:  # noqa: BLE001 — malformed markup still yields blocks
        pass
    lines = statements._lines(html)
    jsonld = []
    import json as _json
    for m in re.finditer(r"<script\b[^>]*ld\+json[^>]*>(.*?)</script>", html, re.I | re.S):
        try:
            jsonld.append(_json.loads(m.group(1).strip()))
        except ValueError:
            continue
    numbers_total = sum(len(_NUM_TOKEN.findall(x)) for x in lines + data_lines)
    return {
        "version": VERSION,
        "text_hash": _fetch.text_hash(text),
        "blocks": read_blocks,                 # what the claim reader reads
        "body_blocks": blocks,                 # <main> minus furniture
        "lines": lines,                        # everything visible, furniture too
        "page_data": data_lines,               # embedded JSON strings
        "from_page_data": from_data,
        "headings": w.headings,
        "tables": w.tables,
        "lists": w.lists,
        "jsonld": jsonld,
        "interactive": sorted(w.hints),
        "hidden_elements": w.hidden,
        "size_blocks": len(read_blocks),
        "numbers_total": numbers_total,
    }


def document(tenant: str, url: str) -> dict:
    """The stored page's Document, re-parsed from stored bytes when the parser
    is newer than the stored one. {} when the page was never stored."""
    from .. import db
    row = _fetch.latest(tenant, url)
    if row is None:
        return {}
    if row.parser_version == VERSION and row.document:
        return row.document
    doc = parse(_fetch.html_of(row))
    with db.SessionLocal() as s:
        r = s.get(db.PageSnapshot, row.id)
        if r is not None:
            r.document, r.parser_version = doc, VERSION
            s.commit()
    return doc
