"""Systems Map — the agents' durable knowledge of HOW Gomeh's world is organized.

Three problems this solves (Gomeh, Jul 2026):
1. Agents re-invented structure per task (e.g. the mis-organized Italy-shipments
   Drive folder) because nothing recorded the EXISTING structure. Now the map is
   read BEFORE any organizational write, and updated after — structure is decided
   once, then conformed to.
2. Context windows were stuffed with everything or starved of the essentials.
   The map injects a compact INDEX every turn (pinned docs in full, the rest as
   one-line entries) and agents pull full docs on demand with systems_get.
3. Agents silently worked around their own limitations. request_feature files
   the friction (problem + proposal) for Gomeh to review and ship.

Doc key conventions: 'drive:<account>' (folder taxonomy), 'conventions:<topic>'
(rules like filing), 'project:<name>' (active workstream state), 'registry:<x>'.
"""
import datetime as dt

from . import db

# Context budget for the every-turn injection block. Pinned docs are clipped
# per-doc; the whole block is clipped overall so the map can never crowd out
# the actual task context.
PIN_DOC_CHARS = 1200
BLOCK_CHARS = 4000
STALE_DAYS = 21


# ---------------------------------------------------------------------------
# Core doc store
# ---------------------------------------------------------------------------
def set_doc(key: str, content: str, title: str = "", updated_by: str = "",
            pinned: bool | None = None) -> str:
    """Create or update one Systems Map doc. Agents call this after any task
    that changed structure, so the map stays current."""
    key = key.strip().lower()
    if not key:
        return "systems_update needs a key (e.g. 'drive:baci', 'project:italy-imports')."
    with db.SessionLocal() as s:
        row = s.get(db.SystemDoc, key)
        if row is None:
            row = db.SystemDoc(key=key)
            s.add(row)
        row.content = content.strip()
        if title:
            row.title = title.strip()
        if pinned is not None:
            row.pinned = "true" if pinned else ""
        row.updated_by = updated_by
        row.updated_at = db.utcnow()
        s.commit()
    return f"Systems Map doc '{key}' saved ({len(content)} chars)."


def get_doc(key: str) -> str:
    key = (key or "").strip().lower()
    with db.SessionLocal() as s:
        row = s.get(db.SystemDoc, key)
        if row:
            return (f"[{row.key}] {row.title} (updated {row.updated_at:%b %d} "
                    f"by {row.updated_by or '?'})\n{row.content}")
        keys = [r.key for r in s.query(db.SystemDoc.key).all()]
    return f"No systems doc '{key}'. Existing docs: {keys or 'none yet'}."


def list_docs() -> str:
    with db.SessionLocal() as s:
        rows = s.query(db.SystemDoc).order_by(db.SystemDoc.key).all()
        if not rows:
            return ("Systems Map is empty. Seed it: map the Drive (run_job "
                    "map_drive) or save conventions with systems_update.")
        return "\n".join(
            f"- {r.key}: {r.title or '(untitled)'} — {len(r.content)} chars, "
            f"updated {r.updated_at:%b %d}{' [pinned]' if r.pinned else ''}"
            for r in rows)


def block(role: str = "") -> str:
    """The every-turn injection: pinned docs in full (clipped), everything else
    as an index line. Kept small by design — the map guides retrieval, it does
    not replace it."""
    with db.SessionLocal() as s:
        rows = s.query(db.SystemDoc).order_by(db.SystemDoc.key).all()
    if not rows:
        return ""
    lines = []
    for r in rows:
        if r.pinned:
            body = r.content[:PIN_DOC_CHARS]
            more = " …(clipped — systems_get for full)" if len(r.content) > PIN_DOC_CHARS else ""
            lines.append(f"### {r.key} — {r.title}\n{body}{more}")
        else:
            first = (r.content.splitlines() or [""])[0][:100]
            lines.append(f"- {r.key}: {r.title or first} (systems_get to read)")
    out = ("\n\nSYSTEMS MAP (how Gomeh's world is organized — READ the relevant "
           "doc BEFORE filing/creating/moving anything and CONFORM to it; update "
           "it after big tasks):\n" + "\n".join(lines))
    return out[:BLOCK_CHARS]


def ensure_seeds() -> None:
    """Idempotent: seed the conventions doc every deploy needs. Run at worker
    startup; never overwrites an existing doc."""
    with db.SessionLocal() as s:
        if s.get(db.SystemDoc, "conventions:filing"):
            return
    set_doc(
        "conventions:filing",
        "One shipment/order = ONE folder even if it carries several reference "
        "numbers (client PO, supplier order #, forwarder ref, invoice #) — list "
        "all refs in the shipment record notes, never split by ref. Subfolders "
        "are plain-English per ORDER (e.g. 'FS Amaala Sept 2026'); a healthy "
        "B2B tree has ~8-15 order subfolders, never one folder per file. "
        "Unmatched files -> '_Agent Intake/_REVIEW' and flag Gomeh. Old "
        "revisions -> 'OLD VERSIONS'; never delete. Import-shipment documents "
        "(BOL, commercial invoice, packing list, arrival notice — senders are "
        "forwarders/brokers/suppliers) are NOT customer-order documents "
        "(Shopify orders, retail invoices) — file them under the shipment, "
        "never mixed. Three accounts (personal/baci/eien) never cross-filed.",
        title="Filing conventions (hard rules)",
        updated_by="seed", pinned=True)


# ---------------------------------------------------------------------------
# Feature requests — the agent's own upgrade queue
# ---------------------------------------------------------------------------
def request_feature(role: str, title: str, problem: str, proposal: str = "") -> str:
    """File (or reinforce) a feature request. Dedupes by similar title so the
    hit count measures how often the same friction recurs."""
    title = title.strip()
    if not title or not problem.strip():
        return "request_feature needs a title and the concrete problem."
    with db.SessionLocal() as s:
        row = (s.query(db.FeatureRequest)
               .filter(db.FeatureRequest.title.ilike(title),
                       db.FeatureRequest.status.in_(["open", "planned"]))
               .first())
        if row:
            row.hits = str(int(row.hits or "1") + 1)
            if proposal and proposal.strip() not in (row.proposal or ""):
                row.proposal = (row.proposal or "") + "\n---\n" + proposal.strip()
            s.commit()
            return (f"Known friction — hit count now {row.hits} for '{title}' "
                    f"(status: {row.status}). Gomeh sees it in the weekly review.")
        s.add(db.FeatureRequest(role=role, title=title,
                                problem=problem.strip(),
                                proposal=proposal.strip()))
        s.commit()
    try:  # notify once, on first filing — recurrences ride the weekly digest
        from . import whatsapp
        whatsapp.send_text(f"💡 [{role}] feature request: {title}\n{problem.strip()[:300]}"
                           "\n(Full queue: /admin/features — implement in a dev session.)")
    except Exception:  # noqa: BLE001 — filing must never fail on notify
        pass
    return f"Feature request filed: '{title}'. Keep working with what you have."


def features_list(status: str = "open") -> list[dict]:
    with db.SessionLocal() as s:
        q = s.query(db.FeatureRequest)
        if status and status != "all":
            q = q.filter(db.FeatureRequest.status == status)
        rows = q.order_by(db.FeatureRequest.created_at.desc()).limit(50).all()
        return [{"id": r.id, "created": f"{r.created_at:%Y-%m-%d}", "role": r.role,
                 "title": r.title, "problem": r.problem, "proposal": r.proposal,
                 "status": r.status, "hits": r.hits} for r in rows]


# ---------------------------------------------------------------------------
# Weekly self-review — keeps the map current and surfaces the upgrade queue
# ---------------------------------------------------------------------------
def systems_review() -> str:
    """Weekly (worker cron): flag stale map docs + digest open feature requests
    to Gomeh. Light on purpose — the heavy updating is done by agents at
    task-time; this is the safety net that nothing rots silently."""
    from . import whatsapp

    def _aware(ts):  # sqlite returns naive; Postgres returns aware — normalize
        return ts.replace(tzinfo=dt.timezone.utc) if ts and ts.tzinfo is None else ts

    stale_cutoff = db.utcnow() - dt.timedelta(days=STALE_DAYS)
    with db.SessionLocal() as s:
        docs = s.query(db.SystemDoc).all()
        stale = [r.key for r in docs
                 if _aware(r.updated_at) and _aware(r.updated_at) < stale_cutoff]
        n_docs = len(docs)
    feats = features_list("open")
    if not stale and not feats:
        return f"systems_review: map healthy ({n_docs} docs), no open feature requests."
    parts = ["🗺 Weekly systems review:"]
    if n_docs == 0:
        parts.append("- Systems Map is EMPTY — run map_drive to seed the Drive "
                     "taxonomy so filing stops improvising.")
    if stale:
        parts.append(f"- {len(stale)} map doc(s) not updated in {STALE_DAYS}+ days: "
                     + ", ".join(stale[:6]) + " — still accurate? I'll refresh on request.")
    if feats:
        parts.append(f"- {len(feats)} open feature request(s) from the agents:")
        parts += [f"   • [{f['role']}] {f['title']} (hit {f['hits']}x)" for f in feats[:5]]
        parts.append("  Say the word and a dev session can implement the top ones.")
    msg = "\n".join(parts)
    whatsapp.send_text(msg)
    return msg
