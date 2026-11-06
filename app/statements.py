"""What a site STATES, as structured facts — subject, value, page — compared.

Owner, 2026-11-04: *"Transak's own pages give seven different country counts
(26, 60+, 64+, 75, 90, 145, 162). The compliance page shows 19 state licences;
the coverage page shows 45 states served"* — and the harvest had captured
none of it, because the claim extractor is a model choosing sentences to KEEP
and a headline figure in a stat tile is not a sentence. Also: *"I still see
the claims as text strings in the UI instead of the new structure we
described."*

This module is the first piece of that structure (INITIATIVE-claims-
reconciliation.md §4.8): a deterministic SWEEP that records every
"<number> <coverage word>" a page states as a `KbStatement` — subject, value,
qualifier, unit, the sentence, the page, whether it sat in the body, the site
furniture or the page's embedded data, and whether the page is legal
(binding). It does not decide what is true. It makes disagreement VISIBLE:
`summary` groups by subject and flags every subject stated with more than one
value, with the pages for each.

Why a sweep and not the model: recall. A model asked for claims will skip a
"162+ Countries" tile on one page and keep "25+ countries" on another, and a
reconciliation step built on that sample would report agreement that does not
exist. Code reads every occurrence, every time, on the full text — including
the header and footer the claim reader strips, because a footer's "available
in 160+ countries" is stated on every page of the site.
"""
from __future__ import annotations

import html as _html
import json
import re

from . import db
from . import provenance as prov

#: unit word (regex) -> subject. Order matters: the longer phrase first.
SUBJECTS: list[tuple[str, str]] = [
    (r"fiat currencies|fiat currency|fiat", "coverage.fiat_currencies"),
    (r"crypto[- ]?currencies|crypto[- ]?assets|digital assets|cryptos|tokens|coins",
     "coverage.crypto_assets"),
    (r"block ?chains|networks|chains", "coverage.blockchains"),
    (r"payment methods|payment options|ways to pay", "coverage.payment_methods"),
    (r"licen[cs]es(?: and registrations)?|registrations|licen[cs]e",
     "legal.licences"),
    (r"countries|country", "coverage.countries"),
    (r"(?:u\.?s\.? )?states", "coverage.states"),
    (r"regions|markets|jurisdictions|territories", "coverage.markets"),
    (r"languages", "coverage.languages"),
    (r"currencies", "coverage.currencies"),
    (r"applications|apps|dapps|wallets", "scale.apps"),
    (r"partners|integrations|clients|brands|businesses", "scale.partners"),
    (r"users|customers|people|members", "scale.users"),
]

_UNITS = "|".join(f"(?:{u})" for u, _s in SUBJECTS)
_NUM = r"(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)"
_SCALE = r"(k|m|bn|b|million|thousand|billion)?"
#: <qualifier?> <number> <+?> <scale?> <+?> <up to 3 filler words> <unit>
_FACT = re.compile(
    r"(?<![\w$€£.#/])(?:(over|more than|at least|up to|around|about|nearly|almost)\s+)?"
    + _NUM + r"\s*(\+)?\s*" + _SCALE + r"\b\s*(\+)?\s*"
    + r"((?:[A-Za-z][\w.'&-]*\s+){0,3}?)"
    + r"(" + _UNITS + r")\b",
    re.I)
_MULT = {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6,
         "b": 1e9, "bn": 1e9, "billion": 1e9}
#: Filler that turns a figure into something else ("25 new countries this
#: year" is still a count; "2 of our countries" is not a coverage figure, but
#: is rare enough to keep — QA sees the sentence).
_NOT_FILLER = re.compile(r"\b(per|each|every|percent|years?|days?|months?|hours?|minutes?)\b", re.I)

_SINGULAR = {"country", "license", "licence"}

#: A word that names the number after it as a place in a document.
_MARKER_WORD = re.compile(r"(?:section|clause|article|paragraph|step|part|§)\s*$", re.I)


def _is_marker(text: str, m, qual, num, plus, scale, filler, unit) -> bool:
    """The number numbers the line, it does not count the unit.

    From Transak's legal and help pages (2026-11-06), each read as a figure
    and the first two as BINDING, because they sat on legal pages:
    "11.2 Payment Methods" (Terms of Service), "20.1 For Vermont
    Members/Customers:" (Privacy Policy), and a step badge read into the
    step's text, "2 Select fiat currency and payment method" (105 pages).
    A stat tile has the same shape ("162+ Countries", "20 Supported
    Countries"), so the test is narrow: nothing qualifies the number, it opens
    the line, and either it is a section number (11.2) followed by a
    capital, or a capitalised word starts a sentence the unit is lower-case
    in. A word before it ("Section 4", "Step 2") is a marker anywhere."""
    if _MARKER_WORD.search(text[:m.start()]):
        return True
    if qual or plus or scale or text[:m.start()].strip(" \t•·-–—#(").strip():
        return False
    first = (filler or unit).lstrip()[:1]
    if "." in num and first.isupper():
        return True
    return bool(filler) and filler[:1].isupper() and unit[:1].islower()

_SCRIPT = re.compile(r"<script\b[^>]*>(.*?)</script>", re.I | re.S)
_STYLE = re.compile(r"<style\b[^>]*>.*?</style>", re.I | re.S)
_TAGS = re.compile(r"<[^>]+>")
_BLOCKY = re.compile(r"</?(?:p|div|li|h[1-6]|tr|td|th|section|article|br|ul|ol|"
                     r"table|header|footer|nav|main|span)\b[^>]*>", re.I)


def subject_for(unit: str) -> str:
    u = (unit or "").lower()
    for pat, subj in SUBJECTS:
        if re.fullmatch(pat, u, re.I):
            return subj
    return ""


def _lines(html_text: str) -> list[str]:
    """The page as lines of visible text, furniture INCLUDED, one per block."""
    raw = _STYLE.sub(" ", _SCRIPT.sub(" ", html_text or ""))
    raw = _BLOCKY.sub("\n", raw)
    raw = _TAGS.sub(" ", raw)
    out = []
    for ln in _html.unescape(raw).split("\n"):
        ln = " ".join(ln.split())
        if ln:
            out.append(ln)
    return _join_fragments(out)


def _join_fragments(lines: list[str]) -> list[str]:
    """A stat tile's "162+" and "Countries" are separate elements: join a short
    line to the next so the figure and its unit are read together."""
    from .extract import merge_short
    return merge_short(lines)


def page_data_lines(html_text: str) -> list[str]:
    """Visible strings inside a page's embedded JSON (Next.js `__NEXT_DATA__`,
    JSON-LD, any `application/json` script). A site drawn by JavaScript ships
    its copy here and the HTML body is nearly empty — read it rather than
    reporting the page as having nothing to say."""
    out: list[str] = []
    for m in re.finditer(r"<script\b([^>]*)>(.*?)</script>", html_text or "", re.I | re.S):
        attrs, body = m.group(1).lower(), m.group(2).strip()
        if "json" not in attrs and "__next_data__" not in attrs:
            continue
        try:
            data = json.loads(body)
        except ValueError:
            continue
        stack = [data]
        while stack:
            cur = stack.pop()
            if isinstance(cur, dict):
                stack.extend(cur.values())
            elif isinstance(cur, list):
                stack.extend(cur)
            elif isinstance(cur, str):
                s = " ".join(_TAGS.sub(" ", _html.unescape(cur)).split())
                if 6 <= len(s) <= 600 and re.search(r"[A-Za-z]{3}", s) \
                        and not s.startswith(("http", "/", "{", "data:")):
                    out.append(s)
    return out


def _fact_re(extra: tuple[tuple[str, str], ...] = ()):
    """The figure pattern, widened by an account's own terms (QA labels)."""
    if not extra:
        return _FACT
    return _fact_re_cached(extra)


from functools import lru_cache  # noqa: E402


@lru_cache(maxsize=64)
def _fact_re_cached(extra: tuple[tuple[str, str], ...]):
    units = "|".join([f"(?:{re.escape(t)})" for t, _s in extra] + [_UNITS])
    return re.compile(
        r"(?<![\w$€£.#/])(?:(over|more than|at least|up to|around|about|nearly|almost)\s+)?"
        + _NUM + r"\s*(\+)?\s*" + _SCALE + r"\b\s*(\+)?\s*"
        + r"((?:[A-Za-z][\w.'&-]*\s+){0,3}?)"
        + r"(" + units + r")\b", re.I)


def find(text: str, extra: tuple[tuple[str, str], ...] = ()) -> list[dict]:
    """Every "<number> <unit>" fact in one line of text.

    `extra` is the account's own vocabulary — (term, subject) pairs a reviewer
    added by labelling an unaccounted figure (`label_number`) — so "40
    corridors" becomes a statement once someone has said what a corridor is."""
    found = []
    terms = {t.lower(): subj for t, subj in extra}
    for m in _fact_re(extra).finditer(text or ""):
        qual, num, plus1, scale, plus2, filler, unit = m.groups()
        if filler and _NOT_FILLER.search(filler):
            continue
        if _is_marker(text, m, qual, num, plus1 or plus2, scale, filler, unit):
            continue
        subj = terms.get(unit.lower()) or subject_for(unit)
        if not subj:
            continue
        try:
            n = float(num.replace(",", ""))
        except ValueError:
            continue
        if scale:
            n *= _MULT.get(scale.lower(), 1)
        # A count takes the plural. "45123 Country Code" and "Alpha-2 country
        # codes" are a number beside a word, not a figure about countries.
        if unit.lower() in _SINGULAR and n != 1:
            continue
        if subj != "scale.users" and 1900 <= n <= 2100 and not (plus1 or plus2):
            continue            # a year, not a count
        q = (qual or "").lower()
        qualifier = ("at least" if (plus1 or plus2 or q in ("over", "more than", "at least"))
                     else "about" if q in ("around", "about", "nearly", "almost")
                     else "up to" if q == "up to" else "")
        sc = "" if not scale else (scale if len(scale) <= 2 else " " + scale)
        value = ((q + " ") if q else "") + num + sc + ("+" if (plus1 or plus2) else "")
        found.append({"subject": subj, "value": value, "number": n,
                      "qualifier": qualifier, "unit": unit.lower(),
                      "match": " ".join(m.group(0).split()),
                      "text": text.strip()[:400]})
    return found


def sweep(html_text: str, body_lines: list[str] | None = None,
          extra: tuple[tuple[str, str], ...] = ()) -> list[dict]:
    """Every coverage/scale fact on one page, each tagged with WHERE it sat.

    `body_lines` are the page's main-content blocks as the claim reader saw
    them (`compliance.text_blocks`); a fact found there is `body`, a fact only
    in the full page is `furniture` (header, footer, nav), and one only in the
    embedded data is `page_data`."""
    return sweep_lines(_lines(html_text), page_data_lines(html_text),
                       body_lines, extra)


def sweep_lines(lines: list[str], data_lines: list[str],
                body_lines: list[str] | None = None,
                extra: tuple[tuple[str, str], ...] = ()) -> list[dict]:
    """`sweep` over an already-parsed page (`pipeline.parse` Document)."""
    body = set(" ".join(b.split()) for b in (body_lines or []))
    body_text = " ".join(body).lower()
    seen, out = set(), []
    for field, group in (("visible", lines), ("page_data", data_lines)):
        for ln in group:
            for f in find(ln, extra):
                key = (f["subject"], f["value"], f["text"])
                if key in seen:
                    continue
                seen.add(key)
                if field == "visible":
                    f["field"] = ("body" if f["match"].lower() in body_text
                                  else "furniture")
                else:
                    f["field"] = "page_data"
                out.append(f)
    return out


def terms(tenant: str) -> tuple[tuple[str, str], ...]:
    """The account's own figure vocabulary, as (term, subject) pairs."""
    with db.SessionLocal() as s:
        rows = (s.query(db.KbStatementTerm)
                .filter(db.tenant_filter(db.KbStatementTerm, tenant))
                .order_by(db.KbStatementTerm.term).all())
        return tuple((r.term, r.subject) for r in rows)


def record(tenant: str, url: str, facts: list[dict], authority: str = "derived",
           entity_key: str = "") -> int:
    """Replace this page's statements with what it says now."""
    with db.SessionLocal() as s:
        (s.query(db.KbStatement)
         .filter(db.KbStatement.tenant == tenant, db.KbStatement.url == url)
         .delete(synchronize_session=False))
        seen = set()
        for f in facts:
            fp = prov.fingerprint(f"{f['subject']}|{f['value']}|{f['text']}|"
                                  f"{f.get('locator', '')}")
            if fp in seen:
                continue
            seen.add(fp)
            s.add(db.KbStatement(
                tenant=tenant, url=url, subject=f["subject"], value=f["value"],
                number=f["number"], qualifier=f["qualifier"], unit=f["unit"],
                text=f["text"], field=f.get("field", "body"),
                # A legal page's own text binds; the site footer around it
                # does not become law by being printed there.
                authority=("derived" if f.get("field") == "furniture" else authority),
                entity_key=entity_key, fingerprint=fp,
                origin=f.get("extractor", "sweep"),
                extractor=f.get("extractor", "numbers"),
                extractor_version=f.get("extractor_version", 1),
                section=f.get("section", ""), locator=f.get("locator", ""),
                kind=f.get("kind", "count"), currency=f.get("currency", "")))
        s.commit()
    return len(seen)


def rows(tenant: str, subject: str = "") -> list:
    with db.SessionLocal() as s:
        q = s.query(db.KbStatement).filter(db.KbStatement.tenant == tenant)
        if subject:
            q = q.filter(db.KbStatement.subject == subject)
        out = q.order_by(db.KbStatement.subject, db.KbStatement.number,
                         db.KbStatement.url).all()
        s.expunge_all()
    return out


def rows_for_url(tenant: str, url: str) -> list:
    with db.SessionLocal() as s:
        out = (s.query(db.KbStatement)
               .filter(db.KbStatement.tenant == tenant, db.KbStatement.url == url).all())
        s.expunge_all()
    return out


def summary(tenant: str, subject: str = "") -> list[dict]:
    """One entry per subject: every distinct value stated, the pages for each,
    and whether the site disagrees with itself (`conflict`).

    A value is the number AND its qualifier: "25+" and "26+" are two
    different statements of one subject, and so are "162" and "162+". Binding
    (legal-page) values are marked — those are where a reconciliation starts.
    """
    by: dict[str, dict] = {}
    for r in rows(tenant, subject):
        sub = by.setdefault(r.subject, {"subject": r.subject, "values": {}})
        key = r.value.lower()
        v = sub["values"].setdefault(key, {
            "value": r.value, "number": r.number, "qualifier": r.qualifier,
            "pages": [], "binding": False, "fields": set(), "example": r.text})
        if r.url not in v["pages"]:
            v["pages"].append(r.url)
        v["binding"] = v["binding"] or r.authority == "binding"
        v["fields"].add(r.field or "body")
    out = []
    for sub in by.values():
        vals = sorted(sub["values"].values(), key=lambda v: (v["number"] or 0))
        for v in vals:
            v["fields"] = sorted(v["fields"])
            v["page_count"] = len(v["pages"])
        out.append({"subject": sub["subject"],
                    "distinct_values": len(vals),
                    "conflict": len({(v["number"], v["qualifier"]) for v in vals}) > 1,
                    "binding_values": [v["value"] for v in vals if v["binding"]],
                    "values": vals})
    return sorted(out, key=lambda x: (not x["conflict"], x["subject"]))
