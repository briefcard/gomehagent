"""ACCOUNT — every figure on a page is a statement, a known non-fact, or listed.

BUILD-MAP §4 ACCOUNT. The fact readers have a vocabulary; a page does not.
"Transak's own pages give seven different country counts" was found by a
person, not the capture, because nothing said which figures the capture had
NOT understood. This stage says so: every number token on the page minus
those inside a recorded statement, minus the explicit non-facts below, is an
UNACCOUNTED figure, kept with its sentence for a reviewer.

A reviewer's answer is reusable: `ignore` applies to the same sentence on
every page, and `label` teaches the account a term (`KbStatementTerm`) so
every later read — and a re-read of stored pages — records it as a statement.
"""
from __future__ import annotations

import datetime as dt
import re

from .. import db
from .. import provenance as prov

#: A figure: digits, optional separators, an optional trailing "+".
_TOKEN = re.compile(r"(?<![\w.\-/#:])\d[\d,]*(?:\.\d+)?\+?(?![\w\-/:])")
_MONTHS = r"jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec"
#: Explicit non-facts. Listed, so what is excluded is a decision on record.
NON_FACTS = {
    "year": lambda tok, ln, at: re.fullmatch(r"(19|20)\d\d", tok) is not None,
    "price": lambda tok, ln, at: at > 0 and ln[at - 1] in "$€£¥",
    "small": lambda tok, ln, at: not tok.endswith("+") and _num(tok) < 3,
    "date": lambda tok, ln, at: re.search(rf"\b({_MONTHS})[a-z]*\.?\s*$", ln[:at], re.I) is not None
            or re.match(rf"\s*({_MONTHS})", ln[at + len(tok):], re.I) is not None,
    "phone": lambda tok, ln, at: re.search(r"\+?\d[\d\s().-]{8,}\d", ln[max(0, at - 6):at + len(tok) + 12]) is not None
             and len(re.sub(r"\D", "", ln[max(0, at - 6):at + len(tok) + 12])) >= 9,
}
#: The most figures listed for one page — reported when hit, never silent.
MAX_PER_PAGE = 200


def _num(tok: str) -> float:
    try:
        return float(tok.rstrip("+").replace(",", ""))
    except ValueError:
        return 0.0


def unaccounted(doc: dict, stmts: list[dict]) -> tuple[list[dict], dict]:
    """(figures no reader explained, counts) for one Document."""
    explained: dict[str, set[str]] = {}
    for st in stmts:
        line = " ".join((st.get("text") or "").split())[:400]
        explained.setdefault(line, set()).update(_TOKEN.findall(st.get("match", "")))
    # A table or list a reader COUNTED is itself the statement: the row
    # labels and cell values inside it ("State 3", "MT-1002") are its rows,
    # not separate figures to explain.
    counted = {st.get("locator") for st in stmts if st.get("qualifier") == "counted"}
    enum_text = []
    for kind, items in (("table", doc.get("tables", [])), ("list", doc.get("lists", []))):
        for i, it in enumerate(items, 1):
            if f"{kind} {i}" in counted:
                cells = ([c for row in [it.get("headers", [])] + it.get("rows", []) for c in row]
                         if kind == "table" else it.get("items", []))
                enum_text.append(" ".join(" ".join(cells).split()))
    enum_blob = " \n ".join(enum_text)
    out, seen = [], set()
    counts = {"numbers": 0, "accounted": 0, "in_counted_table": 0, "non_fact": 0,
              "unaccounted": 0}
    for ln in doc.get("lines", []) + doc.get("page_data", []):
        key = " ".join(ln.split())[:400]
        if enum_blob and key and key in enum_blob:
            n = len(_TOKEN.findall(ln))
            counts["numbers"] += n
            counts["in_counted_table"] += n
            continue
        for m in _TOKEN.finditer(ln):
            tok, at = m.group(0), m.start()
            counts["numbers"] += 1
            if tok in explained.get(key, ()) or tok.rstrip("+") in {
                    t.rstrip("+") for t in explained.get(key, ())}:
                counts["accounted"] += 1
                continue
            if any(rule(tok, ln, at) for rule in NON_FACTS.values()):
                counts["non_fact"] += 1
                continue
            counts["unaccounted"] += 1
            # Keyed on the fingerprint, the same identity the table's unique
            # constraint holds: "Chicago IL, 60661" and "Chicago, IL 60661"
            # are two lines and one sentence.
            k = (tok, prov.fingerprint(key))
            if k in seen:
                continue
            seen.add(k)
            out.append({"number_text": tok, "context": ln[:400],
                        "context_hash": k[1]})
    counts["listed"] = min(len(out), MAX_PER_PAGE)
    counts["cut"] = len(out) > MAX_PER_PAGE
    return out[:MAX_PER_PAGE], counts


def record(tenant: str, url: str, items: list[dict]) -> int:
    """Replace this page's figures, carrying a reviewer's decisions forward —
    including a decision made about the same sentence on another page."""
    now = dt.datetime.now(dt.timezone.utc)
    with db.SessionLocal() as s:
        decided = {(r.number_text, r.context_hash): (r.status, r.label_subject)
                   for r in s.query(db.UnaccountedNumber)
                   .filter(db.UnaccountedNumber.tenant == tenant,
                           db.UnaccountedNumber.status != "open")}
        old = {(r.number_text, r.context_hash): r
               for r in s.query(db.UnaccountedNumber)
               .filter(db.UnaccountedNumber.tenant == tenant,
                       db.UnaccountedNumber.url == url)}
        keep = set()
        for it in items:
            k = (it["number_text"], it["context_hash"])
            keep.add(k)
            row = old.get(k)
            if row is None:
                row = db.UnaccountedNumber(tenant=tenant, url=url, **it)
                s.add(row)
                old[k] = row    # a repeat in this batch finds it, not a 2nd INSERT
            row.last_seen = now
            if k in decided:
                row.status, row.label_subject = decided[k]
        for k, row in old.items():
            if k not in keep:
                s.delete(row)
        s.commit()
    return len(keep)


def open_figures(tenant: str, limit: int = 200) -> list[dict]:
    """Open figures, one per sentence, with how many pages carry it."""
    with db.SessionLocal() as s:
        rows = (s.query(db.UnaccountedNumber)
                .filter(db.tenant_filter(db.UnaccountedNumber, tenant),
                        db.UnaccountedNumber.status == "open")
                .order_by(db.UnaccountedNumber.context_hash).all())
    by: dict[tuple, dict] = {}
    for r in rows:
        g = by.setdefault((r.number_text, r.context_hash), {
            "id": r.id, "number": r.number_text, "context": r.context, "pages": []})
        g["pages"].append(r.url)
    out = sorted(by.values(), key=lambda g: (-len(g["pages"]), g["context"]))
    for g in out:
        g["page_count"] = len(g["pages"])
    return out[:limit]


def _same(s, tenant: str, fig_id: str):
    r = s.get(db.UnaccountedNumber, fig_id)
    if r is None or r.tenant != tenant:
        return None, []
    return r, (s.query(db.UnaccountedNumber)
               .filter(db.UnaccountedNumber.tenant == tenant,
                       db.UnaccountedNumber.number_text == r.number_text,
                       db.UnaccountedNumber.context_hash == r.context_hash).all())


def ignore(tenant: str, fig_id: str) -> int:
    """Not a fact (a step number, a model number …), on every page."""
    with db.SessionLocal() as s:
        r, group = _same(s, tenant, fig_id)
        for g in group:
            g.status = "ignored"
        s.commit()
        return len(group)


def term_after(number_text: str, context: str) -> str:
    """The word a figure counts: the first word after it ("40 corridors")."""
    at = context.find(number_text)
    m = re.match(r"\s*\+?\s*(?:[kKmM]\b|million|thousand|billion)?\s*([A-Za-z][A-Za-z-]+)",
                 context[at + len(number_text):] if at >= 0 else "")
    return m.group(1).lower() if m else ""


def label(tenant: str, fig_id: str, subject: str, term: str = "",
          by: str = "") -> dict:
    """This figure IS a statement of `subject`: teach the account its word."""
    subject = (subject or "").strip()
    if not re.fullmatch(r"[a-z_]+\.[a-z_]+", subject):
        return {"error": "subject must look like area.name, e.g. coverage.corridors"}
    with db.SessionLocal() as s:
        r, group = _same(s, tenant, fig_id)
        if r is None:
            return {"error": "no such figure for this account"}
        term = (term or term_after(r.number_text, r.context)).strip().lower()
        if not term:
            return {"error": "could not tell which word the figure counts; pass term"}
        if not (s.query(db.KbStatementTerm)
                .filter(db.KbStatementTerm.tenant == tenant,
                        db.KbStatementTerm.term == term).one_or_none()):
            s.add(db.KbStatementTerm(tenant=tenant, term=term, subject=subject,
                                     added_by=by))
        for g in group:
            g.status, g.label_subject = "labelled", subject
        s.commit()
    return {"term": term, "subject": subject, "figures": len(group),
            "note": "Recorded as a statement on the next read; run reprocess "
                    "to apply it to stored pages now."}
