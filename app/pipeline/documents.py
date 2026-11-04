"""DOCUMENTS — PDFs a legal or coverage page links to, read like pages.

BUILD-MAP M9. A licence register or a terms PDF is often where the binding
figure lives, and a page reader never opens it. A PDF linked from a legal or
coverage page is fetched, its text extracted (pypdf), parsed as a plain-text
Document, stored as a snapshot under its own URL, and run through the same
readers. Its tier follows the page that links it (a PDF linked from a legal
page is legal, so its statements are BINDING).

Bounded per run (`MAX_PER_RUN`), and the bound is reported, never silent.
"""
from __future__ import annotations

import io
from urllib.parse import urljoin

from .. import compliance, statements
from . import account, extractors, fetch, parse

MAX_PER_RUN = 20
MAX_PAGES = 60


def pdf_text(data: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    return "\n".join((p.extract_text() or "") for p in reader.pages[:MAX_PAGES]).strip()


def pdf_links(doc: dict, page_url: str) -> list[str]:
    out = []
    for ln in doc.get("links", []):
        href = ln.get("href", "")
        u = urljoin(page_url, href).split("#", 1)[0]
        if u.lower().split("?", 1)[0].endswith(".pdf") and u not in out:
            out.append(u)
    return out


def read_linked(tenant: str, page_url: str, doc: dict, tier: str, apply: bool,
                seen: set, budget: dict, terms: tuple = ()) -> list[dict]:
    """Read the PDFs one page links to. Returns one report row per PDF."""
    if tier not in ("legal", "coverage"):
        return []
    rows = []
    for u in pdf_links(doc, page_url):
        if u in seen:
            continue
        seen.add(u)
        if budget["left"] <= 0:
            rows.append({"url": u, "status": "not read — the per-run document budget is spent"})
            continue
        budget["left"] -= 1
        status, data, ctype, err = fetch.download_bytes(u)
        if err or status != 200 or not data:
            rows.append({"url": u, "status": err or f"HTTP {status}"})
            continue
        try:
            text = pdf_text(data)
        except Exception as exc:  # noqa: BLE001
            rows.append({"url": u, "status": f"unreadable PDF ({exc.__class__.__name__})"})
            continue
        if not text.strip():
            rows.append({"url": u, "status": "no text — a scanned PDF needs OCR"})
            continue
        d = parse.parse_text(text)
        stmts, _c = extractors.run_all(d, terms)
        figs, _fc = account.unaccounted(d, stmts)
        binding = tier == "legal" or compliance.is_legal_url(u)
        if apply:
            fetch.store(tenant, u, text, d["text_hash"], document=d,
                        risk_tier="legal" if binding else tier)
            statements.record(tenant, u, [{**x, "field": "document"} for x in stmts],
                              authority="binding" if binding else "derived")
            account.record(tenant, u, figs)
        rows.append({"url": u, "status": "read", "linked_from": page_url,
                     "statements": len(stmts), "binding": binding})
    return rows
