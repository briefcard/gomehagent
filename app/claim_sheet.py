"""The claims workbook — export by entity, review offline, upload the fixes.

Owner, 2026-11-06: *"When we export the claims I want this to be an excel
spreadsheet split by entities so that we can reupload them as well with fixes
if for example one claim is true for one entity and another another. This way
reviewers can look at claims per entity and approve them in that workflow.
Then we should be able to interpret this on upload and update the list of
places where the adjustments on … content needs to happen."*

One sheet per entity (the account's products/services, `kb_entities`), plus
"Brand-wide", "Not assigned" (code could not tell which entity) and "Not
about us" (marked as about a partner or the market). An "Entities" sheet
lists the vocabulary — the URLs and words that place a claim on an entity —
and a new row there creates an entity on upload.

A row is keyed by `claim_id`. Upload, per claim:

* the record fields (subject, entity, market, as-of, conditions, statement)
  are set as the REVIEWER's (claim_record.set_record);
* evidence columns add a link or the team's statement (claim_record.add_evidence);
* the same claim on two rows with two entities = "true for one entity and
  another for another": the first row keeps the claim, each further row
  becomes a new claim for that entity, with its own statement;
* the decision is applied through the same gates as the console: approve →
  kb.review_claim (refused, with the reason, when evidence or scope is
  missing); reject; history; replace on site / remove from site → a wording
  change with one task per page the claim appears on (change.create_wording),
  which is the list of places the content must be adjusted.

`check` reads and reports without writing anything — what would change and
what would be refused. `apply` does it. Same file, two presses.
"""
from __future__ import annotations

import io
import re

from . import claim_record, db

DECISIONS = ("", "approve", "reject", "history", "replace on site", "remove from site")
SPECIAL = {"brand-wide": "Brand-wide", "": "Not assigned", "_other": "Not about us"}

#: (header, field, width, editable). Order is the sheet's column order.
COLUMNS = [
    ("claim_id", "claim_id", 14, False),
    ("Claim as found on the site", "claim", 60, False),
    ("Appears on (pages)", "pages", 40, False),
    ("Page date", "as_of", 12, True),
    ("Kinds", "kinds", 16, False),
    ("Inconsistency group", "group", 16, False),
    ("Subject (self / partner / other / market / none)", "subject", 14, True),
    # How the record was reached — read-only, so a reviewer can start with
    # what the machine was least sure of (sort by confidence).
    ("Decided by", "decided_by", 12, False),
    ("Claude's reason", "why", 40, False),
    ("Claude's confidence", "confidence", 11, False),
    ("Said by / source (industry facts, quotes)", "source", 24, False),
    ("Topic (industry facts)", "topic", 20, False),
    ("Gives context to (products)", "supports", 20, False),
    ("Entity (key, several comma-separated, or brand-wide)", "entity", 20, True),
    ("Market", "market", 18, True),
    ("Jurisdiction", "jurisdiction", 16, True),
    ("Conditions (for whom / which method)", "conditions", 22, True),
    ("Statement — one sentence that stands alone (what prompts receive)", "statement", 60, True),
    ("Decision", "decision", 14, True),
    ("Replacement wording (for 'replace on site')", "replacement", 40, True),
    ("Evidence link", "ev_link", 30, True),
    ("Evidence statement / how we quantify", "ev_method", 40, True),
    ("Evidence as of (YYYY-MM-DD)", "ev_as_of", 14, True),
    ("Record still needed", "missing", 45, False),
    ("Proof (noted; can be added after approval)", "proof", 45, False),
    ("Reviewer", "reviewer", 14, True),
    ("Note / reason", "note", 30, True),
]
ENTITY_COLUMNS = [("key", 16), ("name", 24), ("type", 12), ("URL patterns (comma-separated)", 40),
                  ("Words (comma-separated)", 40), ("Status", 14),
                  ("Description — what it is, for whom", 50),
                  ("Reference pages (one per line)", 60)]
README = [
    "How to use this workbook",
    "",
    "One sheet per entity (product / service). Brand-wide, Not assigned and Not about us hold the rest.",
    "Edit only the light-yellow columns. claim_id ties a row to the claim; never change it.",
    "Move a claim to another entity: change its Entity cell (any sheet is fine — the cell decides).",
    "True of several entities: list them in the Entity cell, comma-separated (first = main). One",
    "  claim, attached to each — no copies.",
    "True for one entity in one way and another in another: copy the row, keep claim_id, set a",
    "  different Entity and Statement on each copy.",
    "Start with what the machine was least sure of: sort by 'Claude's confidence' (lowest first).",
    "  'Decided by' says whether code, Claude or a reviewer set the subject; 'Claude's reason' says why.",
    "Decision: approve | reject | history (true on its date, not now) | replace on site | remove from site.",
    "  approve is refused, with the reason, while 'Record still needed' is not empty (when the",
    "  account requires a complete record). Proof is noted; it can be added after approval.",
    "  replace / remove create one task per page the claim appears on (Review › Changes).",
    "Evidence: a link to the source of record, and/or the team's statement of how it is counted.",
    "Entities sheet: add a row to create an entity; URL patterns and words place claims on it.",
    "  Suggested rows are created only if you change their Status (e.g. to 'keep').",
    "Upload: Review › Claims › Upload workbook. 'Check' reports what would change; 'Apply' does it.",
]


def _sheet_title(name: str, used: set) -> str:
    bad = '[]:*?/\\'
    t = "".join("-" if c in bad else c for c in (name or "Entity"))[:31] or "Entity"
    base, n = t, 2
    while t.lower() in used:
        t = f"{base[:28]}~{n}"
        n += 1
    used.add(t.lower())
    return t


def rows(tenant: str, review: str = "proposed") -> list[dict]:
    """One dict per claim, in COLUMNS fields."""
    from . import claim_groups
    with db.SessionLocal() as s:
        q = s.query(db.KbClaim).filter(db.KbClaim.tenant == tenant)
        if review != "all":
            q = q.filter(db.KbClaim.review == review)
        claims = q.order_by(db.KbClaim.id).all()
        gm = {m.claim_id: g for m, g in (
            s.query(db.KbClaimMember, db.KbClaimGroup)
            .join(db.KbClaimGroup, db.KbClaimGroup.id == db.KbClaimMember.group_id)
            .filter(db.KbClaimMember.tenant == tenant, db.KbClaimGroup.kind == "inconsistency"))}
        ids = [c.id for c in claims]
        evs = claim_record.evidence_for(tenant, ids)
        out = []
        for c in claims:
            sc = c.scope or {}
            ev = evs.get(c.id, [])
            g = gm.get(c.id)
            out.append({
                "claim_id": c.id, "claim": c.claim or "",
                "pages": "\n".join(claim_groups.pages_of(c)[:10]),
                "as_of": sc.get("as_of") or sc.get("read_at") or "",
                "kinds": ", ".join(claim_record.kinds_of_row(c)),
                "group": (g.id[:8] if g else ""),
                # Every entity the claim is attached to, primary first —
                # ONE row however many; edit the list to attach or detach.
                "subject": c.subject or "", "entity": ", ".join(claim_record.entities_of(c)) or (
                    "brand-wide" if sc.get("brand_wide") else ""),
                "market": sc.get("market", ""), "jurisdiction": sc.get("jurisdiction", ""),
                "conditions": sc.get("conditions", ""),
                "decided_by": _DECIDED.get((c.scope_origin or {}).get("subject", ""), "") or (
                    "code" if c.subject else ""),
                "why": _why_text(sc.get("_why", "")),
                "confidence": _confidence(sc.get("_why", "")),
                "source": sc.get("source") or (c.subject_name if c.subject in ("partner", "other", "market")
                                               else "") or "",
                "topic": sc.get("topic", ""), "supports": sc.get("supports", ""),
                "statement": c.statement or "", "decision": "", "replacement": "",
                "ev_link": "\n".join(e["url"] for e in ev if e["kind"] == "link"),
                "ev_method": "\n".join((e["method"] or e["text"]) for e in ev
                                       if e["kind"] == "statement" or e["method"]),
                "ev_as_of": "", "missing": "\n".join(claim_record.record_missing(c)),
                "proof": ("on file" if not claim_record.proof_missing(tenant, c, ev) else
                          "pending — " + " ".join(claim_record.proof_missing(tenant, c, ev))),
                "reviewer": "", "note": "",
                "_sheet": ("_other" if c.subject in ("other", "market", "partner", "none") else
                           (c.entity_key or ("brand-wide" if sc.get("brand_wide") else ""))),
            })
    return out


_DECIDED = {"rule": "code", "vocabulary": "code", "page": "code", "url": "code",
            "claude": "Claude", "reviewer": "reviewer"}
_CONF = re.compile(r"\(Claude, confidence ([0-9.]+)\)\s*$")


def _confidence(why: str):
    m = _CONF.search(why or "")
    try:
        return float(m.group(1)) if m else None
    except ValueError:
        return None


def _why_text(why: str) -> str:
    return _CONF.sub("", why or "").strip()


def export(tenant: str, review: str = "proposed") -> bytes:
    """The workbook, as .xlsx bytes."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation

    vocab = claim_record.vocabulary(tenant)
    ents = vocab["entities"]
    data = rows(tenant, review)
    wb = Workbook()
    ws = wb.active
    ws.title = "How to use"
    for i, line in enumerate(README, 1):
        ws.cell(row=i, column=1, value=line).font = Font(bold=(i == 1))
    ws.column_dimensions["A"].width = 110

    used = {"how to use", "entities"}
    yellow = PatternFill("solid", fgColor="FFF7D6")
    head = Font(bold=True)
    wrap = Alignment(wrap_text=True, vertical="top")
    order = [(e["key"], e["name"]) for e in ents] + [
        ("brand-wide", SPECIAL["brand-wide"]), ("", SPECIAL[""]), ("_other", SPECIAL["_other"])]
    ent_keys = [e["key"] for e in ents] + ["brand-wide"]
    for key, name in order:
        mine = [r for r in data if r["_sheet"] == key]
        if not mine and key in ("_other",):
            continue
        sh = wb.create_sheet(_sheet_title(name, used))
        for j, (h, _f, w, ed) in enumerate(COLUMNS, 1):
            c = sh.cell(row=1, column=j, value=h)
            c.font = head
            c.alignment = wrap
            if ed:
                c.fill = yellow
            sh.column_dimensions[c.column_letter].width = w
        sh.freeze_panes = "C2"
        if mine:
            sh.auto_filter.ref = f"A1:{sh.cell(row=1, column=len(COLUMNS)).column_letter}{len(mine) + 1}"
        for i, r in enumerate(mine, 2):
            for j, (_h, f, _w, ed) in enumerate(COLUMNS, 1):
                c = sh.cell(row=i, column=j, value=r.get(f, ""))
                c.alignment = wrap
                if ed:
                    c.fill = yellow
        n = max(len(mine) + 200, 300)
        col = {f: j for j, (_h, f, _w, _e) in enumerate(COLUMNS, 1)}
        from openpyxl.utils import get_column_letter as L
        for field, choices in (("decision", [d for d in DECISIONS if d]),
                               ("subject", list(claim_record.SUBJECTS))):
            dv = DataValidation(type="list", formula1='"' + ",".join(choices) + '"',
                                allow_blank=True)
            sh.add_data_validation(dv)
            dv.add(f"{L(col[field])}2:{L(col[field])}{n}")
        if ent_keys and len(",".join(ent_keys)) < 250:
            dv = DataValidation(type="list", formula1='"' + ",".join(ent_keys) + '"',
                                allow_blank=True, showErrorMessage=False)
            sh.add_data_validation(dv)
            dv.add(f"{L(col['entity'])}2:{L(col['entity'])}{n}")

    es = wb.create_sheet("Entities")
    for j, (h, w) in enumerate(ENTITY_COLUMNS, 1):
        c = es.cell(row=1, column=j, value=h)
        c.font = head
        es.column_dimensions[c.column_letter].width = w
    for i, e in enumerate(ents, 2):
        for j, v in enumerate([e["key"], e["name"], e.get("type", ""), ", ".join(e["urls"]),
                               ", ".join(e["words"]), "existing", e.get("description", ""),
                               "\n".join(e.get("references") or [])], 1):
            es.cell(row=i, column=j, value=v)
    for i, (path, n) in enumerate(suggest_entities(tenant, {e["key"] for e in ents}),
                                  len(ents) + 2):
        for j, v in enumerate([path.strip("/").replace("/", "-"), path.strip("/").replace("-", " ").title(),
                               "product", path, "", f"suggested ({n} pages)"], 1):
            es.cell(row=i, column=j, value=v).fill = yellow
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def suggest_entities(tenant: str, have: set, limit: int = 25) -> list[tuple[str, int]]:
    """Top-level paths of the account's own pages that are not content
    sections — candidates a reviewer may keep or delete. Never created
    without the upload."""
    import collections
    import re
    skip = re.compile(r"^/(blog|news|press|articles?|buy|sell|convert|tag|category|author|"
                      r"page|legal|privacy|terms|cookie|careers?|about|contact|faq|help|"
                      r"search|wp-|cdn|static|assets|en|de|fr|es)(/|$)", re.I)
    with db.SessionLocal() as s:
        urls = [u for (u,) in s.query(db.PageSnapshot.url)
                .filter(db.PageSnapshot.tenant == tenant).all()]
    c = collections.Counter()
    for u in urls:
        host, _, path = u.split("://", 1)[-1].partition("/")
        if host.startswith(("docs.", "support.", "newsletter.", "help.")):
            continue
        p = "/" + path.split("?", 1)[0].split("/", 1)[0]
        if p != "/" and not skip.match(p):
            c[p] += 1
    return [(p, n) for p, n in c.most_common(limit) if p.strip("/").replace("/", "-") not in have]


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

def read(data: bytes) -> dict:
    """Parse a returned workbook: {claims: [row dicts], entities: [...], errors}."""
    from openpyxl import load_workbook
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001
        return {"claims": [], "entities": [], "errors": [f"not a readable .xlsx: {exc}"]}
    by_head = {h.strip().lower(): f for h, f, _w, _e in COLUMNS}
    # Headers of workbooks exported by earlier versions still read.
    by_head.update({"entity (key, or brand-wide)": "entity",
                    "subject (self / other / market)": "subject",
                    "still needed before approval": "missing"})
    out, ents, errors = [], [], []
    for ws in wb.worksheets:
        it = ws.iter_rows(values_only=True)
        try:
            header = next(it)
        except StopIteration:
            continue
        header = [(str(h or "").strip().lower()) for h in header]
        if ws.title == "Entities":
            for vals in it:
                v = [("" if x is None else str(x)).strip() for x in (vals or ())] + [""] * 8
                if not v[0]:
                    continue
                ents.append({"key": v[0], "name": v[1] or v[0], "type": v[2] or "product",
                             "urls": [x.strip() for x in v[3].split(",") if x.strip()],
                             "words": [x.strip() for x in v[4].split(",") if x.strip()],
                             "status": v[5], "description": v[6],
                             "references": [x.strip() for x in v[7].splitlines() if x.strip()]})
            continue
        fields = [by_head.get(h, "") for h in header]
        if "claim_id" not in fields:
            continue
        for n, vals in enumerate(it, 2):
            r = {f: ("" if v is None else str(v)).strip()
                 for f, v in zip(fields, vals) if f}
            if not r.get("claim_id"):
                continue
            r["_where"] = f"{ws.title}!{n}"
            out.append(r)
    return {"claims": out, "entities": ents, "errors": errors}


def _changed(r: dict, cur: dict) -> dict:
    """The editable fields this row changes against the current export."""
    keys = ("subject", "entity", "market", "jurisdiction", "conditions", "statement", "as_of")
    return {k: r.get(k, "") for k in keys if r.get(k, "") != (cur.get(k) or "")}


def plan(tenant: str, data: bytes) -> dict:
    """What an upload would do, row by row — nothing written."""
    parsed = read(data)
    if parsed["errors"]:
        return {"ok": False, "errors": parsed["errors"]}
    current = {r["claim_id"]: r for r in rows(tenant, "all")}
    ent_keys = {e["key"] for e in claim_record.vocabulary(tenant)["entities"]}
    # A suggested row is kept only when the reviewer changes its Status (to
    # "keep", or anything else): a suggestion left as it was creates nothing.
    new_ents = [e for e in parsed["entities"] if e["key"] and e["key"] not in ent_keys
                and not e["status"].lower().startswith("suggested")]
    # An existing entity whose row was edited (its URLs, words, description
    # or references) is updated — the Entities sheet is where they are kept.
    have = {e["key"]: e for e in claim_record.vocabulary(tenant)["entities"]}
    upd_ents = [e for e in parsed["entities"] if e["key"] in have and any(
        e[k] != have[e["key"]].get(k, [] if k in ("urls", "words", "references") else "")
        for k in ("urls", "words", "description", "references"))]
    known = ent_keys | {e["key"] for e in new_ents}
    steps, refused, seen = [], [], {}
    for r in parsed["claims"]:
        cid = r["claim_id"]
        cur = current.get(cid)
        if cur is None:
            refused.append({"where": r["_where"], "claim_id": cid,
                            "why": "no such claim on this account (deleted, or another account's file)"})
            continue
        _keys = claim_record.entity_keys_of(r.get("entity", ""))
        _bad = [k for k in _keys if k != "brand-wide" and k not in known]
        if _bad:
            refused.append({"where": r["_where"], "claim_id": cid,
                            "why": f"entity {', '.join(map(repr, _bad))} is not on the Entities sheet"})
            continue
        r["entity"] = ", ".join(_keys)
        dec = (r.get("decision") or "").strip().lower()
        if dec not in DECISIONS:
            refused.append({"where": r["_where"], "claim_id": cid,
                            "why": f"decision {dec!r} — use one of {', '.join(d for d in DECISIONS if d)}"})
            continue
        if dec == "replace on site" and not r.get("replacement"):
            refused.append({"where": r["_where"], "claim_id": cid,
                            "why": "replace on site needs the replacement wording"})
            continue
        if dec and not r.get("reviewer"):
            refused.append({"where": r["_where"], "claim_id": cid,
                            "why": "a decision needs the reviewer's name"})
            continue
        split = cid in seen and r.get("entity") != seen[cid]
        if cid in seen and not split:
            refused.append({"where": r["_where"], "claim_id": cid,
                            "why": "the same claim twice with the same entity — keep one row"})
            continue
        seen.setdefault(cid, r.get("entity", ""))
        ch = _changed(r, cur)
        ev = bool(r.get("ev_link") and r["ev_link"] != cur.get("ev_link")) or bool(
            r.get("ev_method") and r["ev_method"] != cur.get("ev_method"))
        if not (ch or ev or dec or split):
            continue
        steps.append({"where": r["_where"], "claim_id": cid, "split": split,
                      "changes": ch, "evidence": ev, "decision": dec, "row": r})
    return {"ok": True, "entities": new_ents, "entities_updated": upd_ents,
            "steps": steps, "refused": refused,
            "rows_read": len(parsed["claims"])}


def apply(tenant: str, data: bytes, by: str) -> dict:
    """Do what `plan` says. Returns the per-row outcome, and the change ids
    whose tasks are the places on the site to adjust."""
    from . import kb
    p = plan(tenant, data)
    if not p.get("ok"):
        return p
    for e in p["entities"] + p.get("entities_updated", []):
        kb.add_entity(tenant, e["type"] or "product", e["key"], e["name"],
                      description=e.get("description", ""),
                      attributes={"match": {"urls": e["urls"], "words": e["words"]},
                                  "references": e.get("references", [])},
                      source="claims workbook", origin="human")
    done, refused, changes = [], list(p["refused"]), []
    for st in p["steps"]:
        r, cid = st["row"], st["claim_id"]
        who = r.get("reviewer") or by
        target = cid
        if st["split"]:
            target = _split(tenant, cid, r, who)
            if not target:
                refused.append({"where": st["where"], "claim_id": cid,
                                "why": "could not copy the claim for the second entity"})
                continue
        scope = {k: r[k] for k in ("market", "jurisdiction", "conditions") if k in st["changes"]}
        if "as_of" in st["changes"]:
            scope["as_of"] = r["as_of"]
        res = claim_record.set_record(
            tenant, target, by=who, origin="reviewer",
            subject=(r["subject"] or None) if "subject" in st["changes"] or st["split"] else None,
            entity_key=(r.get("entity") or "") if ("entity" in st["changes"] or st["split"]) else None,
            scope=scope or None,
            statement=r["statement"] if ("statement" in st["changes"] or st["split"]) else None)
        if not res.get("ok"):
            refused.append({"where": st["where"], "claim_id": cid, "why": res.get("why", "")})
            continue
        if st["evidence"]:
            for link in [x for x in (r.get("ev_link") or "").split("\n") if x.strip()]:
                e = claim_record.add_evidence(tenant, target, who, "link", url=link.strip(),
                                              as_of=r.get("ev_as_of", ""))
                if not e.get("ok"):
                    refused.append({"where": st["where"], "claim_id": cid, "why": e["why"]})
            if (r.get("ev_method") or "").strip():
                e = claim_record.add_evidence(tenant, target, who, "statement",
                                              method=r["ev_method"], as_of=r.get("ev_as_of", ""))
                if not e.get("ok"):
                    refused.append({"where": st["where"], "claim_id": cid, "why": e["why"]})
        out = _decide(tenant, target, st["decision"], r, who)
        if out.get("change_id"):
            changes.append(out["change_id"])
        (refused if out.get("refused") else done).append(
            {"where": st["where"], "claim_id": target, "did": out.get("did", "updated"),
             **({"why": out["refused"]} if out.get("refused") else {})})
    return {"ok": True, "entities_added": [e["key"] for e in p["entities"]],
            "entities_updated": [e["key"] for e in p.get("entities_updated", [])],
            "applied": done, "refused": refused, "changes": changes}


def _split(tenant: str, claim_id: str, r: dict, by: str) -> str:
    """A copy of the claim for another entity — through kb.add_claim, the one
    writer of claims."""
    from . import kb
    with db.SessionLocal() as s:
        c = s.get(db.KbClaim, claim_id)
        if c is None:
            return ""
        args = dict(claim=r.get("statement") or c.claim, evidence=c.evidence or "",
                    tags=list(c.situations or []), proof_type=c.proof_type or "spec",
                    source=c.source or "", entity_key=(claim_record.entity_keys_of(r.get("entity", "")) or [""])[0]
                    if r.get("entity") != "brand-wide" else "",
                    proves="", context=c.context or "", attributed_to=c.attributed_to or "")
    kb.add_claim(tenant, status="pending", origin="human", assess=False, **args)
    with db.SessionLocal() as s:
        row = (s.query(db.KbClaim).filter(db.KbClaim.tenant == tenant,
                                          db.KbClaim.id != claim_id,
                                          db.KbClaim.claim == args["claim"],
                                          db.KbClaim.entity_key == args["entity_key"]).first())
        return row.id if row else ""


def _decide(tenant: str, claim_id: str, decision: str, r: dict, by: str) -> dict:
    from . import claim_groups, kb
    if not decision:
        return {"did": "updated"}
    if decision == "approve":
        msg = kb.review_claim(claim_id, True, by=by)
        return ({"did": "approved"} if msg.startswith("Approved") else {"refused": msg})
    if decision == "reject":
        kb.review_claim(claim_id, False, by=by)
        return {"did": "rejected"}
    if decision == "history":
        return kb.keep_as_history(claim_id, by=by, reason=r.get("note", ""))
    with db.SessionLocal() as s:
        c = s.get(db.KbClaim, claim_id)
        wording, pages = (c.claim or ""), claim_groups.pages_of(c)
    from . import change
    new = r.get("replacement", "") if decision == "replace on site" else ""
    locs = [{"kind": ("auto_edit" if (change._editable(u) and change._store_profile(tenant, u))
                      else "manual"),
             "location": u, "find": wording, "replace": new, "sentence": wording} for u in pages]
    res = change.create_wording(tenant, f"claim-{claim_id[:12]}", wording, new,
                                r.get("note") or decision, by, locs)
    if decision == "remove from site":
        kb.review_claim(claim_id, False, by=by)
    return {"did": f"{decision}: {res['tasks']} page task(s)", "change_id": res["change_id"]}
