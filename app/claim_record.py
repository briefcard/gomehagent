"""THE CLAIM RECORD — who a claim is about, what it is true of, as of when,
and what it rests on (BUILD-MAP §17).

Owner, 2026-11-06, on the Transak harvest: *"not only do these facts on their
own lack the context to have any significance, but a reviewer would have no
way of verifying, supporting or approving them"* — and *"which markets are we
talking about? Every claim needs to have this context because it will also
serve as part of our prompts."* The site stated seventeen different country
counts (18+ … 190+): different products, different things counted, different
years. None of them is approvable, or usable in a prompt, as a bare sentence.

Researched before built (§17.1):

* a claim is a record linked to its reference, approved once and retired
  when obsolete — the pharma claims-library pattern (Veeva PromoMats);
* the evidence a claim needs depends on its kind and must exist before it is
  published — CAP Code 3.7, the FTC reasonable-basis doctrine, FCA FG23/3 /
  MiCA Art. 66 "fair, clear and not misleading";
* scope is RESTRICTIVE QUALIFIERS (Wikidata's model): point in time, applies
  to part, valid in place, jurisdiction — a consumer that drops one changes
  what the statement says, so the prompt line carries them all;
* a sentence made to stand alone is "decontextualization" (Choi et al.
  2021), whose honest outcome for a fragment is INFEASIBLE, not a guess.

Division of labour, under the 2026-10-22 rule (no judges inside the app):
CODE derives what the page itself states — the date, a market in the URL or
text, sandbox wording, whether the account names itself, which entity's
pages it sits on. CLAUDE (through MCP `propose_claim_record`) proposes what
needs reading: the subject when the sentence does not name it, the
standalone statement, a dropped condition. A REVIEWER confirms, in the
console or in the spreadsheet (`claim_sheet`). A reviewer's value is never
overwritten by a re-derive.

The rules are the same for every company; the vocabulary (self names, the
account's entities and the words/URLs that identify them) is the client's.
"""
from __future__ import annotations

import datetime as dt
import re

from . import claim_context, db

#: Origins, strongest last: a re-derive overwrites only `page`/`url`/`rule`/
#: `vocabulary`; `claude` only replaces those; `reviewer` is final.
DERIVED = ("page", "url", "rule", "vocabulary")
RANK = {"": 0, "page": 1, "url": 1, "rule": 1, "vocabulary": 1, "claude": 2, "reviewer": 3}

QUALIFIERS = ("as_of", "read_at", "market", "jurisdiction", "audience", "environment",
              "conditions", "counts", "brand_wide", "history")
SUBJECTS = ("self", "other", "market")

#: What a claim of each kind must rest on before it is approved. `needs`:
#:   link            — a link (that resolves) to the source of record
#:   method          — the team's statement of how it is counted / what it holds under
#:   link_and_method — both (documentary evidence + the basis of the comparison)
#:   statement       — the team's statement (consent, confirmation)
#:   recent_statement— the team's confirmation dated within RECENT_DAYS
#:   link_or_method  — either
#: `qualifiers` must be known (or ruled brand-wide) before approval.
EVIDENCE: dict[str, dict] = {
    "regulatory": {"needs": "link", "qualifiers": ["jurisdiction"],
                   "ask": "a link to the regulator's public register entry (or the licence "
                          "itself) — and the jurisdiction it covers"},
    "comparative": {"needs": "link_and_method", "qualifiers": [],
                    "ask": "documentary evidence covering every competitor compared, and a "
                           "statement of the measure and date compared on"},
    "superlative": {"needs": "link_and_method", "qualifiers": [],
                    "ask": "the ranking, report or market-share data behind it, and what was "
                           "measured"},
    "coverage": {"needs": "link_or_method", "qualifiers": ["entity"],
                 "ask": "the system of record it is counted from (a link), or the team's "
                        "statement of what is counted and how — and which product it is for"},
    "testimonial": {"needs": "statement", "qualifiers": [],
                    "ask": "the team's confirmation that the customer agreed to be quoted, and "
                           "that the quote is exact"},
    "relationship": {"needs": "recent_statement", "qualifiers": [],
                     "ask": "the team's confirmation that the partnership or integration is "
                            "active, dated within the last 90 days — or a link that shows it"},
    "absolute": {"needs": "method", "qualifiers": [],
                 "ask": "the conditions it holds under (for whom, where, which method) — or "
                        "soften the wording"},
    "statement": {"needs": "link_or_method", "qualifiers": [],
                  "ask": "a link to the source of record, or the team's statement of how it "
                         "is known"},
}
#: Strictest first: a claim with several kinds is held to every one.
_ORDER = ("regulatory", "comparative", "superlative", "coverage", "testimonial",
          "relationship", "absolute")
RECENT_DAYS = 90

#: Regulators and regimes → the jurisdiction they imply. Generic, not one
#: client's: every regulated company names its regulator.
REGULATORS = {
    "FCA": "United Kingdom", "FinCEN": "United States", "SEC": "United States",
    "NYDFS": "United States (New York)", "AUSTRAC": "Australia", "ASIC": "Australia",
    "FINTRAC": "Canada", "MiCA": "European Union", "ESMA": "European Union",
    "BaFin": "Germany", "AMF": "France", "CONSOB": "Italy", "Bank of Lithuania": "Lithuania",
    "MAS": "Singapore", "VARA": "United Arab Emirates (Dubai)", "CySEC": "Cyprus",
    "MFSA": "Malta", "FSA": "Japan", "SFC": "Hong Kong", "FINMA": "Switzerland",
    "CBI": "Ireland", "DNB": "Netherlands", "AFM": "Netherlands", "CNMV": "Spain",
}
#: Regions spoken of as markets; matched as whole words.
REGIONS = {"EU": "European Union", "EEA": "European Economic Area", "Europe": "Europe",
           "European Union": "European Union", "LATAM": "Latin America",
           "Latin America": "Latin America", "APAC": "Asia-Pacific", "Asia": "Asia",
           "Africa": "Africa", "Middle East": "Middle East", "MENA": "Middle East & North Africa",
           "US": "United States", "USA": "United States", "U.S.": "United States",
           "UK": "United Kingdom", "U.K.": "United Kingdom", "UAE": "United Arab Emirates"}
#: Country names that are also ordinary words or US states: matched only in a
#: URL, never in prose.
_AMBIGUOUS = {"Georgia", "Jersey", "Chad", "Jordan", "Niger", "Guinea", "Turkey",
              "Chile", "Togo", "Mali", "Oman", "Peru", "Cuba", "Dominica"}

_FIRST_PERSON = re.compile(r"\b(we|we're|we've|our|ours|us)\b", re.I)


# ---------------------------------------------------------------------------
# Vocabulary — the client's words; everything else is shared
# ---------------------------------------------------------------------------

def vocabulary(tenant: str) -> dict:
    """{self_names, entities: [{key, name, urls, words}], evidence_required}."""
    with db.SessionLocal() as s:
        b = s.get(db.KbBrand, tenant)
        conf = dict((b.claim_scope or {}) if b is not None else {})
        names = [n for n in (conf.get("self_names") or []) if n]
        if not names and b is not None and b.display_name:
            names = [b.display_name]
        ents = []
        for e in (s.query(db.KbEntity).filter(db.KbEntity.tenant == tenant,
                                              db.KbEntity.status == "active").all()):
            m = (e.attributes or {}).get("match") or {}
            ents.append({"key": e.key, "name": e.name, "type": e.type,
                         "urls": [u for u in (m.get("urls") or []) if u],
                         "words": [w for w in (m.get("words") or []) if w],
                         "description": e.description or "",
                         "references": list((e.attributes or {}).get("references") or [])})
    return {"self_names": names, "entities": ents,
            "record_required": bool(conf.get("record_required")),
            "evidence_required": bool(conf.get("evidence_required"))}


def set_vocabulary(tenant: str, by: str, self_names: list[str] | None = None,
                   evidence_required: bool | None = None,
                   record_required: bool | None = None) -> dict:
    with db.SessionLocal() as s:
        b = s.get(db.KbBrand, tenant)
        if b is None:
            return {"ok": False, "why": "this account has no brand row yet"}
        conf = dict(b.claim_scope or {})
        if self_names is not None:
            conf["self_names"] = [n.strip() for n in self_names if n.strip()]
        if evidence_required is not None:
            conf["evidence_required"] = bool(evidence_required)
        if record_required is not None:
            conf["record_required"] = bool(record_required)
        conf["updated_by"] = by
        b.claim_scope = conf
        s.commit()
    return {"ok": True, "claim_scope": conf}


# ---------------------------------------------------------------------------
# Derivation — what the page itself states, by code
# ---------------------------------------------------------------------------

_COUNTRIES: dict[str, str] | None = None


def _countries() -> dict[str, str]:
    """name (and common/official names) → canonical name, from pycountry."""
    global _COUNTRIES
    if _COUNTRIES is None:
        out: dict[str, str] = {}
        try:
            import pycountry
            for c in pycountry.countries:
                canon = getattr(c, "common_name", None) or c.name
                for n in {c.name, canon, getattr(c, "official_name", None)}:
                    if n and "," not in n:
                        out[n] = canon
        except Exception:  # noqa: BLE001 — no library: markets from regions only
            pass
        _COUNTRIES = out
    return _COUNTRIES


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def markets_in(text: str, url: str = "") -> tuple[list[str], str]:
    """Markets named by the URL (a country page) or the sentence. (names, origin)."""
    names = _countries()
    path = url.split("://", 1)[-1].split("?", 1)[0].lower()
    segs = [p for p in path.split("/")[1:] if p]
    by_slug = {_slug(k): v for k, v in names.items()}
    for seg in reversed(segs):
        if seg in by_slug:
            return [by_slug[seg]], "url"
    found: list[str] = []
    t = text or ""
    for k, v in REGIONS.items():
        if re.search(r"(?<![\w.])" + re.escape(k) + r"(?![\w])", t) and v not in found:
            found.append(v)
    for k, v in names.items():
        if k in _AMBIGUOUS or len(k) < 4:
            continue
        if re.search(r"\b" + re.escape(k) + r"\b", t) and v not in found:
            found.append(v)
    return found, ("rule" if found else "")


def jurisdiction_in(text: str) -> str:
    for reg, place in REGULATORS.items():
        if re.search(r"\b" + re.escape(reg) + r"\b", text or ""):
            return place
    return ""


def subject_of(text: str, vocab: dict, own_page: bool = True) -> tuple[str, str]:
    """('self', name) when the sentence names the account or speaks as it.
    ('', '') otherwise: who a sentence is about when it does not say is a
    reading, so it is proposed (Claude) and confirmed (reviewer), not guessed."""
    for n in vocab.get("self_names") or []:
        if re.search(r"\b" + re.escape(n) + r"(?:'s)?\b", text or "", re.I):
            return "self", n
    if own_page and _FIRST_PERSON.search(text or ""):
        return "self", "first person"
    return "", ""


def _own_marketing_page(url: str) -> bool:
    """A product, marketing or legal page of the account's own site: there an
    unattributed headline ("Coverage of 18+ countries") is the account
    speaking — the advertiser owns every claim on its own ad. A blog post,
    help article or newsletter mixes in market facts and partners' words, so
    there the subject is left to be read."""
    from . import claim_groups
    return bool(url) and claim_groups.authority(url) in (0, 1)


def entity_of(text: str, url: str, section: str, title: str, vocab: dict) -> tuple[str, list[str]]:
    """The one entity whose URLs or words this claim sits on. ('', candidates)
    when none or several match — never a pick between two."""
    path = "/" + url.split("://", 1)[-1].split("/", 1)[-1].lower() if url else ""
    words_in = " ".join([text or "", section or "", title or ""]).lower()
    hits, by_url = [], []
    for e in vocab.get("entities") or []:
        on_url = any(u.lower() in path for u in e["urls"])
        if on_url:
            by_url.append(e["key"])
        if on_url or any(
                re.search(r"\b" + re.escape(w.lower()) + r"\b", words_in) for w in e["words"]):
            hits.append(e["key"])
    # The page a claim sits on outranks a product merely NAMED in it: a claim
    # on /off-ramp that mentions "buy crypto" is the off-ramp's. Only one
    # URL match decides; two still leave it to a person.
    if len(by_url) == 1:
        return by_url[0], [by_url[0]]
    if len(by_url) > 1:
        return "", by_url                  # two products' pages: a person decides
    # Named products, on a neutral page: the claim is about EACH of them
    # ("one integration covers on-ramp and off-ramp"), so it is attached to
    # all — one claim, several entities (owner, 2026-11-07).
    return (hits[0], hits) if hits else ("", [])


def derive(tenant: str, row, vocab: dict | None = None, docs: dict | None = None) -> dict:
    """The record code can state for one claim: {subject, subject_name, kinds,
    entity_key, entity_candidates, scope, scope_origin, where}."""
    from . import claim_groups
    vocab = vocab or vocabulary(tenant)
    docs = docs if docs is not None else {}
    pages = claim_groups.pages_of(row)
    ctx = claim_context.context_for(tenant, row.claim or "", pages, row.proof_type or "", docs=docs)
    first = ctx["where"][0] if ctx["where"] else {}
    url = first.get("url", "")
    scope, origin = {}, {}
    if ctx["newest_date"]:
        scope["as_of"], origin["as_of"] = ctx["newest_date"], "page"
    read = _read_at(tenant, url)
    if read:
        scope["read_at"], origin["read_at"] = read, "page"
    text = " ".join([row.claim or "", row.context or ""])
    mk, mo = markets_in(row.claim or "", url)
    if not mk and row.context:
        mk, mo = markets_in(row.context, "")
    if mk:
        scope["market"], origin["market"] = ", ".join(mk), mo
    j = jurisdiction_in(text)
    if j:
        scope["jurisdiction"], origin["jurisdiction"] = j, "rule"
    if ctx["sandbox"]:
        scope["environment"], origin["environment"] = "sandbox / staging only", "page"
    kinds = list(ctx["kinds"])
    if claim_context.is_history(row.claim or "") and ctx.get("age_days") is not None:
        scope["history"], origin["history"] = True, "rule"
    subj, sname = subject_of(row.claim or "", vocab)
    if not subj and _own_marketing_page(url) and (row.proof_type or "") != "testimonial":
        subj, sname = "self", "own product page"
    ent, cands = entity_of(row.claim or "", url, first.get("section", ""),
                           first.get("title", ""), vocab)
    return {"subject": subj, "subject_name": sname, "kinds": kinds,
            "entity_key": ent, "entity_candidates": cands,
            "scope": scope, "scope_origin": origin, "where": ctx["where"],
            "flags": ctx["flags"], "checks": ctx["checks"]}


def _read_at(tenant: str, url: str) -> str:
    if not url:
        return ""
    with db.SessionLocal() as s:
        t = (s.query(db.PageSnapshot.fetched_at)
             .filter(db.PageSnapshot.tenant == tenant, db.PageSnapshot.url == url).scalar())
    return t.date().isoformat() if t else ""


def refresh(tenant: str, limit: int | None = None) -> dict:
    """Derive every live claim's record; never overwrite claude/reviewer values.
    Keeps what it determined as a `record` stage report (app.stages)."""
    from . import stages
    started = stages.now()
    vocab, docs = vocabulary(tenant), {}
    n = changed = 0
    tally = {"about the account (named or own page)": 0, "placed on an entity": 0,
             "on several entities": 0, "market found": 0, "page date found": 0,
             "dated news (history)": 0, "sandbox / staging only": 0}
    left = {"subject left for a person": 0, "entity left for a person (two products' pages)": 0}
    with db.SessionLocal() as s:
        q = (s.query(db.KbClaim).filter(db.KbClaim.tenant == tenant,
                                       db.KbClaim.review != "rejected"))
        rows = q.all() if limit is None else q.limit(limit).all()
        for row in rows:
            n += 1
            d = derive(tenant, row, vocab, docs)
            before = (row.subject, row.kinds, dict(row.scope or {}), row.entity_key)
            _merge(row, d, "derived")
            if (row.subject, row.kinds, dict(row.scope or {}), row.entity_key) != before:
                changed += 1
            sc = row.scope or {}
            tally["about the account (named or own page)"] += row.subject == "self"
            tally["placed on an entity"] += bool(row.entity_key)
            tally["on several entities"] += bool(row.also_entities)
            tally["market found"] += bool(sc.get("market"))
            tally["page date found"] += bool(sc.get("as_of"))
            tally["dated news (history)"] += bool(sc.get("history"))
            tally["sandbox / staging only"] += bool(sc.get("environment"))
            left["subject left for a person"] += not row.subject
            left["entity left for a person (two products' pages)"] += (
                not row.entity_key and len(d.get("entity_candidates") or []) > 1)
        s.commit()
    stages.record(tenant, "record", started_at=started, n_in=n,
                  n_out=tally["about the account (named or own page)"], dropped=left,
                  details={"derived": tally, "changed": changed})
    return {"ok": True, "claims": n, "changed": changed}


def _merge(row, d: dict, how: str) -> None:
    """Fold derived values into a claim, below claude/reviewer values."""
    so = dict(row.scope_origin or {})
    sc = dict(row.scope or {})
    for k, v in (d.get("scope") or {}).items():
        o = (d.get("scope_origin") or {}).get(k, "rule")
        if RANK.get(so.get(k, ""), 0) <= RANK[o]:
            sc[k], so[k] = v, o
    if RANK.get(so.get("subject", ""), 0) <= 1 and d.get("subject"):
        row.subject, row.subject_name, so["subject"] = d["subject"], d.get("subject_name", ""), "rule"
    if d.get("entity_key") and not row.entity_key and RANK.get(so.get("entity", ""), 0) <= 1:
        row.entity_key, so["entity"] = d["entity_key"], "vocabulary"
        row.also_entities = [k for k in (d.get("entity_candidates") or []) if k != d["entity_key"]]
    row.kinds = "|".join(d.get("kinds") or [])
    row.scope, row.scope_origin = sc, so
    if not row.record_status:
        row.record_status = how


# ---------------------------------------------------------------------------
# Setting the record — Claude proposes, a reviewer confirms
# ---------------------------------------------------------------------------

def entity_keys_of(value) -> list[str]:
    """'a, b' | ['a', 'b'] | 'a' -> ['a', 'b'] — the first is the primary."""
    if isinstance(value, (list, tuple)):
        items = [str(v) for v in value]
    else:
        items = str(value or "").replace("\n", ",").split(",")
    out = []
    for k in (i.strip() for i in items):
        if k and k not in out:
            out.append(k)
    return out


def entities_of(row) -> list[str]:
    """Every entity a claim is attached to, primary first."""
    return [k for k in [row.entity_key or ""] + list(getattr(row, "also_entities", None) or []) if k]


def set_record(tenant: str, claim_id: str, by: str, origin: str = "reviewer",
               subject: str | None = None, subject_name: str | None = None,
               entity_key: "str | list | None" = None, scope: dict | None = None,
               statement: str | None = None, infeasible: bool = False,
               why: str = "") -> dict:
    """Write record fields at `origin` (claude | reviewer). Claude never
    overwrites a reviewer's value; a reviewer's write confirms the record."""
    if origin not in ("claude", "reviewer"):
        return {"ok": False, "why": f"unknown origin {origin!r}"}
    if subject is not None and subject not in SUBJECTS + ("",):
        return {"ok": False, "why": f"subject must be one of {', '.join(SUBJECTS)}"}
    bad = [k for k in (scope or {}) if k not in QUALIFIERS]
    if bad:
        return {"ok": False, "why": f"unknown qualifier(s) {', '.join(bad)}",
                "known": list(QUALIFIERS)}
    with db.SessionLocal() as s:
        row = s.get(db.KbClaim, claim_id)
        if row is None or row.tenant != tenant:
            return {"ok": False, "why": "no such claim on this account"}
        so = dict(row.scope_origin or {})
        sc = dict(row.scope or {})
        held = []

        def may(field: str) -> bool:
            if RANK.get(so.get(field, ""), 0) > RANK[origin]:
                held.append(field)
                return False
            return True

        if subject is not None and may("subject"):
            row.subject, so["subject"] = subject, origin
            if subject_name is not None:
                row.subject_name = subject_name
        if entity_key is not None and may("entity"):
            keys = entity_keys_of(entity_key)
            if keys and keys != ["brand-wide"]:
                if "brand-wide" in keys:
                    return {"ok": False, "why": "brand-wide cannot be combined with entities"}
                known = {k for (k,) in s.query(db.KbEntity.key).filter(
                    db.KbEntity.tenant == tenant, db.KbEntity.key.in_(keys))}
                bad = [k for k in keys if k not in known]
                if bad:
                    return {"ok": False, "why": f"no entity {', '.join(map(repr, bad))} on this account"}
                row.entity_key, row.also_entities = keys[0], keys[1:]
                sc.pop("brand_wide", None)
            elif keys == ["brand-wide"]:
                row.entity_key, row.also_entities, sc["brand_wide"] = "", [], True
                so["brand_wide"] = origin
            else:
                row.entity_key, row.also_entities = "", []
            so["entity"] = origin
        for k, v in (scope or {}).items():
            if may(k):
                if v in ("", None):
                    sc.pop(k, None)
                else:
                    sc[k] = v
                so[k] = origin
        if statement is not None and (RANK.get(row.statement_origin or "", 0) <= RANK[origin]):
            row.statement, row.statement_origin = statement.strip(), origin
        elif statement is not None:
            held.append("statement")
        row.scope, row.scope_origin = sc, so
        if infeasible:
            row.record_status = "infeasible"
        elif origin == "reviewer":
            row.record_status = "confirmed"
        elif row.record_status != "confirmed":
            row.record_status = "proposed"
        row.record_by, row.record_at = by, db.utcnow()
        if why:
            sc["_why"] = why[:500]
            row.scope = sc
        s.commit()
    return {"ok": True, "claim_id": claim_id, "held_by_reviewer": held}


# ---------------------------------------------------------------------------
# Evidence — a link, or the team's statement of how it is counted
# ---------------------------------------------------------------------------

def add_evidence(tenant: str, target_id: str, by: str, kind: str = "link", url: str = "",
                 text: str = "", method: str = "", as_of: str = "", target: str = "claim",
                 check: bool = True) -> dict:
    kind = (kind or "").strip().lower()
    url, text, method = (url or "").strip(), (text or "").strip(), (method or "").strip()
    if kind not in ("link", "statement"):
        return {"ok": False, "why": "evidence is a link or a statement"}
    if kind == "link" and not re.match(r"https?://\S+$", url):
        return {"ok": False, "why": "a link must be a full http(s) address"}
    if kind == "statement" and not (text or method):
        return {"ok": False, "why": "say what the team knows, and how it is counted"}
    if as_of:
        try:
            dt.date.fromisoformat(as_of[:10])
            as_of = as_of[:10]
        except ValueError:
            return {"ok": False, "why": "as-of must be a date, YYYY-MM-DD"}
    if not by:
        return {"ok": False, "why": "evidence needs the name of who gave it"}
    model = {"claim": db.KbClaim, "fact": db.KbFactValue, "group": db.KbClaimGroup}.get(target)
    if model is None:
        return {"ok": False, "why": f"unknown target {target!r}"}
    with db.SessionLocal() as s:
        t = s.get(model, target_id)
        if t is None or t.tenant != tenant:
            return {"ok": False, "why": f"no such {target} on this account"}
        dup = (s.query(db.KbEvidence)
               .filter(db.KbEvidence.tenant == tenant, db.KbEvidence.target_id == target_id,
                       db.KbEvidence.status == "active", db.KbEvidence.kind == kind,
                       db.KbEvidence.url == url, db.KbEvidence.text == text,
                       db.KbEvidence.method == method).first())
        if dup:
            return {"ok": True, "id": dup.id, "duplicate": True}
        ev = db.KbEvidence(tenant=tenant, target=target, target_id=target_id, kind=kind,
                           url=url, text=text, method=method, as_of=as_of, provided_by=by)
        s.add(ev)
        s.commit()
        eid = ev.id
    if kind == "link" and check:
        check_link(tenant, eid)
    return {"ok": True, "id": eid}


def check_link(tenant: str, evidence_id: str) -> str:
    """ok | broken — one request; a link that does not resolve supports nothing."""
    with db.SessionLocal() as s:
        ev = s.get(db.KbEvidence, evidence_id)
        if ev is None or ev.tenant != tenant or not ev.url:
            return ""
        url = ev.url
    status = "broken"
    try:
        import requests
        r = requests.get(url, timeout=10, allow_redirects=True, stream=True,
                         headers={"User-Agent": "Mozilla/5.0 (compatible; evidence-check)"})
        status = "ok" if r.status_code < 400 else "broken"
        r.close()
    except Exception:  # noqa: BLE001
        status = "broken"
    with db.SessionLocal() as s:
        ev = s.get(db.KbEvidence, evidence_id)
        ev.link_status, ev.link_checked_at = status, db.utcnow()
        s.commit()
    return status


def withdraw_evidence(tenant: str, evidence_id: str, by: str, reason: str) -> dict:
    if not reason.strip():
        return {"ok": False, "why": "say why it no longer supports the claim"}
    with db.SessionLocal() as s:
        ev = s.get(db.KbEvidence, evidence_id)
        if ev is None or ev.tenant != tenant:
            return {"ok": False, "why": "no such evidence on this account"}
        ev.status, ev.withdrawn_by, ev.withdrawn_reason = "withdrawn", by, reason.strip()
        s.commit()
    return {"ok": True}


def evidence_for(tenant: str, target_ids: list[str], include_withdrawn: bool = False) -> dict:
    out: dict[str, list] = {}
    if not target_ids:
        return out
    with db.SessionLocal() as s:
        q = s.query(db.KbEvidence).filter(db.KbEvidence.tenant == tenant,
                                          db.KbEvidence.target_id.in_(list(target_ids)))
        if not include_withdrawn:
            q = q.filter(db.KbEvidence.status == "active")
        for e in q.order_by(db.KbEvidence.created_at).all():
            out.setdefault(e.target_id, []).append(
                {"id": e.id, "kind": e.kind, "url": e.url, "text": e.text, "method": e.method,
                 "as_of": e.as_of, "by": e.provided_by, "status": e.status,
                 "link_status": e.link_status,
                 "at": e.created_at.date().isoformat() if e.created_at else ""})
    return out


# ---------------------------------------------------------------------------
# The gate — what is still missing before this claim may be approved
# ---------------------------------------------------------------------------

def kinds_of_row(row) -> list[str]:
    k = [x for x in (row.kinds or "").split("|") if x]
    return k or claim_context.kinds_of(row.claim or "", row.proof_type or "")


def requirements(row) -> list[dict]:
    ks = kinds_of_row(row)
    reqs = [dict(EVIDENCE[k], kind=k) for k in _ORDER if k in ks]
    return reqs or [dict(EVIDENCE["statement"], kind="statement")]


def _satisfies(need: str, evs: list[dict], today: dt.date) -> bool:
    links = [e for e in evs if e["kind"] == "link" and e.get("link_status") != "broken"]
    methods = [e for e in evs if (e.get("method") or (e["kind"] == "statement" and e.get("text")))]
    stmts = [e for e in evs if e["kind"] == "statement" and (e.get("text") or e.get("method"))]
    if need == "link":
        return bool(links)
    if need == "method":
        return bool(methods)
    if need == "link_and_method":
        return bool(links) and bool(methods)
    if need == "link_or_method":
        return bool(links) or bool(methods)
    if need == "statement":
        return bool(stmts)
    if need == "recent_statement":
        def recent(e):
            d = e.get("as_of") or e.get("at") or ""
            try:
                return (today - dt.date.fromisoformat(d[:10])).days <= RECENT_DAYS
            except ValueError:
                return False
        return any(recent(e) for e in stmts) or bool(links)
    return False


def missing(tenant: str, row, evs: list[dict] | None = None,
            today: dt.date | None = None) -> list[str]:
    """Everything still open on a claim: the record, then the proof."""
    return record_missing(row) + proof_missing(tenant, row, evs, today)


def proof_missing(tenant: str, row, evs: list[dict] | None = None,
                  today: dt.date | None = None) -> list[str]:
    """What proof the claim's kinds call for and do not yet have.

    Owner, 2026-11-07: *"For now we should note proof but not require it. We
    can always add proof after the approval process as a separate role."* So
    this is NOTED everywhere (card, workbook, the prompt's `proof` field) and
    blocks approval only on an account that turns `evidence_required` on."""
    today = today or dt.date.today()
    evs = evs if evs is not None else evidence_for(tenant, [row.id]).get(row.id, [])
    out = []
    for r in requirements(row):
        if not _satisfies(r["needs"], evs, today):
            out.append(f"Evidence ({r['kind']}): {r['ask']}.")
    return list(dict.fromkeys(out))


def record_missing(row) -> list[str]:
    """What the claim's RECORD still lacks — who it is about, what it is true
    of, the qualifiers its kinds need, a statement that stands alone. Without
    these a claim cannot be understood, by a reviewer or by a prompt."""
    out = []
    if row.subject != "self":
        out.append("Say who this is about. Only a claim the account makes about itself can be "
                   "approved as its claim" + (" — this one is marked as about "
                                              f"{row.subject_name or row.subject}."
                                              if row.subject in ("other", "market") else "."))
    if row.record_status == "infeasible":
        out.append("It was marked as not able to stand alone — rewrite it as a full sentence, "
                   "or reject it.")
    sc = row.scope or {}
    if sc.get("history"):
        out.append("It is dated news — keep it as history (true on its date), not as a "
                   "current claim.")
    if sc.get("environment") and "sandbox" not in (row.statement or "").lower() \
            and "staging" not in (row.statement or "").lower():
        out.append(f"It is scoped to {sc['environment']}: say so in the statement, or "
                   "reject it as a general claim.")
    if not (row.statement or "").strip():
        out.append("Write the statement as one sentence that stands alone (who, what, for "
                   "which product and market, as of when).")
    for r in requirements(row):
        for q in r["qualifiers"]:
            if q == "entity" and not (row.entity_key or sc.get("brand_wide")):
                out.append("Which product is this true of? Pick the entity, or rule it "
                           "brand-wide.")
            elif q != "entity" and not sc.get(q):
                out.append(f"Give the {q.replace('_', ' ')}.")
    seen, uniq = set(), []
    for m in out:
        if m and m not in seen:
            seen.add(m)
            uniq.append(m)
    return uniq


def gate(tenant: str, row) -> str:
    """'' when approval may go ahead; else the refusal.

    Two switches per account (`claim_scope`): `record_required` blocks a claim
    whose record is incomplete; `evidence_required` also blocks one whose
    proof is missing. Proof is otherwise noted, not required (owner,
    2026-11-07) — added after approval, as its own role."""
    v = vocabulary(tenant)
    m = (record_missing(row) if v["record_required"] else []) + (
        proof_missing(tenant, row) if v["evidence_required"] else [])
    return ("Not approved — this claim is missing:\n• " + "\n• ".join(m)) if m else ""


def proof_state(tenant: str, row, evs: list[dict] | None = None) -> str:
    """'on file' | 'pending' — carried to prompts and the workbook."""
    return "pending" if proof_missing(tenant, row, evs) else "on file"


# ---------------------------------------------------------------------------
# What a prompt receives
# ---------------------------------------------------------------------------

def qualifier_line(row, entity_names: dict | None = None) -> str:
    sc = row.scope or {}
    parts = []
    if row.entity_key:
        parts.append(" + ".join((entity_names or {}).get(k, k) for k in entities_of(row)))
    elif sc.get("brand_wide"):
        parts.append("brand-wide")
    for k in ("market", "jurisdiction", "audience", "environment", "conditions", "counts"):
        if sc.get(k):
            parts.append(f"{k.replace('_', ' ')}: {sc[k]}")
    if sc.get("as_of"):
        parts.append(f"as of {sc['as_of']}")
    elif sc.get("read_at"):
        parts.append(f"on the site {sc['read_at']}")
    return "; ".join(parts)


def job(tenant: str, progress=None) -> dict:
    return refresh(tenant)
