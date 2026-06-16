"""On-demand operations jobs, triggered via /admin/run/{job}:

- recategorize: re-run bucket labeling across all inboxes (fresh definitions)
- doc_sweep: pull PDF/doc attachments from email into the B2B Shared Drive
  under '_Agent Intake/<group>/', then email an index report
- shipment_audit: Opus review of recent logistics threads -> open shipments,
  pending quotes, prepared follow-up drafts, escalated action items
"""
import json
import logging

import anthropic

from . import approvals, config, db, drive_io, gmail_client, triage

log = logging.getLogger("ops")
client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

DOC_SWEEP_ALIAS = "baci"
DOC_SWEEP_DAYS = 180
B2B_FOLDER_NAME = "B2B"
INTAKE_NAME = "_Agent Intake"

# Live progress registry — readable via /admin/status and the WhatsApp agent.
STATUS: dict[str, dict] = {}


def _status(job: str, **kw) -> None:
    import datetime as dt
    STATUS.setdefault(job, {}).update(kw, updated=dt.datetime.now().strftime("%H:%M:%S"))


def _json_extract(text: str) -> dict:
    text = text.strip().strip("`")
    return json.loads(text[text.find("{"):text.rfind("}") + 1])


# Phase 1: read ONE document, extract its key data points.
EXTRACT_PROMPT = """Read this business document (included above) and extract its
key identifying data. Email context — From: {sender} | Subject: {subject}.
Respond JSON only:
{{"doc_type": "<commercial invoice|packing list|bill of lading|purchase order|"
 "quote|arrival notice|customs entry|other>",
 "counterparty": "<the company this involves, e.g. 'Primorous', 'Four Seasons "
 "Naples', 'ECU Worldwide' — the supplier/client/forwarder>",
 "order_ref": "<the strongest order/PO/shipment reference number on the doc, "
 "or '' if none>",
 "all_refs": ["<every reference number visible: PO, order#, invoice#, BOL#, "
 "container#>"],
 "date": "<YYYY-MM-DD or ''>",
 "is_old_version": false,
 "summary": "<one line: what this document is>"}}"""

# Phase 2: cluster ALL extracted docs into orders and assign folders ONCE.
CLUSTER_PROMPT = """You are organizing {n} business documents into the Baci
Milano USA B2B Drive. EXISTING FOLDERS (reuse these aggressively):
{tree}

Here is the extracted data for every document:
{docs}

Group them into ORDERS/SHIPMENTS. Critical rules:
1. Documents belong to the SAME order if they share a counterparty AND any
   reference number, OR clearly describe the same shipment (same parties,
   dates, goods). A single order has many docs (invoice + packing list + BOL)
   and many ref numbers — they are ONE group, ONE folder.
2. Map each group to an EXISTING folder when one fits. Create a new folder
   only when a group has no home; name it 'Orders/<Counterparty> <ref-or-date>'
   in plain English. Aim for a SMALL number of folders.
3. Never put one order's docs in two folders. Never make a folder per file.
4. Mark is_old_version docs to land in the group folder's 'OLD VERSIONS'.
Respond JSON only:
{{"groups": [{{"folder": "<path under B2B>", "existing": true/false,
  "anchor": "<counterparty + primary ref>", "doc_ids": [<int>, ...]}}]}}"""


def recategorize() -> str:
    with db.SessionLocal() as s:
        marker = s.get(db.Setting, "bucket_backfill_done")
        if marker:
            s.delete(marker)
            s.commit()
    from . import worker
    worker.bucket_backfill()
    return "recategorize complete"


def doc_sweep() -> str:
    """Three-phase pipeline:
    1. EXTRACT — pull every attachment, hash for dedup, read each PDF's key
       data points (counterparty, refs, doc type, date) ONCE.
    2. CLUSTER — group ALL docs into orders globally and assign each group one
       folder (reusing existing folders), so one order never splits.
    3. FILE — upload unique docs to their group folder; index with hash.
    """
    import base64 as _b64
    import hashlib

    from . import data_tools, emailfmt
    alias = DOC_SWEEP_ALIAS
    b2b = drive_io.find_folder(alias, B2B_FOLDER_NAME)
    if not b2b:
        return f"FAILED: no folder named '{B2B_FOLDER_NAME}' found in {alias} Drive"

    # ---------- Phase 1: EXTRACT ----------
    _status("doc_sweep", state="extracting")
    emails = gmail_client.fetch_with_attachments(alias, DOC_SWEEP_DAYS)
    docs: list[dict] = []          # one entry per UNIQUE attachment
    seen_hashes: set[str] = set()
    dup_in_run = dup_filed = 0
    for ei, em in enumerate(emails, 1):
        _status("doc_sweep", state="extracting", progress=f"{ei}/{len(emails)} emails",
                unique_docs=len(docs))
        for att in em["attachments"]:
            if not att["filename"].lower().endswith((".pdf", ".xlsx", ".xls", ".docx")):
                continue
            try:
                data = gmail_client.download_attachment(alias, em["id"], att["attachment_id"])
            except Exception:  # noqa: BLE001
                continue
            h = hashlib.sha256(data).hexdigest()
            if h in seen_hashes:
                dup_in_run += 1
                continue
            if data_tools.hash_already_filed(h):
                dup_filed += 1
                seen_hashes.add(h)
                continue
            seen_hashes.add(h)
            # read key data points from the document itself
            meta = {"doc_type": "other", "counterparty": "", "order_ref": "",
                    "all_refs": [], "date": "", "is_old_version": False,
                    "summary": att["filename"]}
            if att["filename"].lower().endswith(".pdf") and len(data) < 4_500_000:
                try:
                    msg = client.messages.create(
                        model=config.CLAUDE_MODEL, max_tokens=400,
                        messages=[{"role": "user", "content": [
                            {"type": "document", "source": {
                                "type": "base64", "media_type": "application/pdf",
                                "data": _b64.standard_b64encode(data).decode()}},
                            {"type": "text", "text": EXTRACT_PROMPT.format(
                                sender=em["from"][:60], subject=em["subject"][:120])},
                        ]}],
                    )
                    meta.update(_json_extract(msg.content[0].text))
                except Exception:  # noqa: BLE001
                    log.exception("extract failed: %s", att["filename"])
            docs.append({"i": len(docs), "filename": att["filename"], "data": data,
                         "mime": att["mime"], "hash": h, "from": em["from"], **meta})

    if not docs:
        return f"doc_sweep: no new documents ({dup_in_run + dup_filed} duplicates skipped)"

    # ---------- Phase 2: CLUSTER ----------
    _status("doc_sweep", state="clustering", unique_docs=len(docs))
    tree_text = "\n".join(sorted(drive_io.folder_tree(alias, b2b, depth=3)))[:6000]
    doc_lines = "\n".join(
        f"id={d['i']}: type={d['doc_type']}, counterparty='{d['counterparty']}', "
        f"order_ref='{d['order_ref']}', refs={d['all_refs']}, date={d['date']}, "
        f"old={d['is_old_version']}, file='{d['filename']}'" for d in docs)
    try:
        msg = client.messages.create(
            model=config.CLAUDE_MODEL, max_tokens=3000,
            messages=[{"role": "user", "content": CLUSTER_PROMPT.format(
                n=len(docs), tree=tree_text or "(empty)", docs=doc_lines)}],
        )
        groups = _json_extract(msg.content[0].text).get("groups", [])
    except Exception:  # noqa: BLE001
        log.exception("clustering failed")
        return "doc_sweep: clustering step failed — nothing filed"

    # ---------- Phase 3: FILE ----------
    _status("doc_sweep", state="filing", groups=len(groups))
    by_id = {d["i"]: d for d in docs}
    filed, new_folders = [], 0
    for g in groups:
        folder = (g.get("folder") or "_Agent Intake/_REVIEW").strip("/")
        if not g.get("existing", True):
            new_folders += 1
        for did in g.get("doc_ids", []):
            d = by_id.get(did)
            if not d:
                continue
            path = folder + ("/OLD VERSIONS" if d.get("is_old_version") else "")
            try:
                folder_id = drive_io.ensure_path(alias, b2b, path)
                link = drive_io.upload(alias, folder_id, d["filename"], d["data"],
                                       d["mime"] or "application/octet-stream")
                data_tools.index_document(
                    d["filename"], path, link if link.startswith("http") else "",
                    d["doc_type"], g.get("anchor", ""), "sweep", d["hash"])
                filed.append(f"{path}/{d['filename']}")
            except Exception:  # noqa: BLE001
                log.exception("upload failed: %s", d["filename"])

    _status("doc_sweep", state="done", filed=len(filed))
    report = (
        f"Document sweep — last {DOC_SWEEP_DAYS} days\n\n"
        f"{len(docs)} unique documents organized into {len(groups)} orders "
        f"({new_folders} new folders; {dup_in_run} in-batch duplicates and "
        f"{dup_filed} already-filed duplicates skipped).\n\n"
        + "\n".join(f"  • {f}" for f in filed[:150])
        + "\n\nWrong placement? Tell me on WhatsApp and the correction sticks."
    )
    gmail_client.send_email(config.NOTIFY_FROM_ALIAS, config.APPROVER_EMAIL,
                            f"Document sweep — {len(docs)} docs, {len(groups)} orders",
                            report, html=emailfmt.text_to_html(report))
    return (f"doc_sweep complete: {len(docs)} unique docs, {len(groups)} orders, "
            f"{dup_in_run + dup_filed} dupes skipped")


AUDIT_PROMPT = """You are auditing the Baci Milano USA import/logistics pipeline.
Below are recent email threads (subject, participants, latest snippet, date).
Identify:
1. OPEN SHIPMENTS: in motion or stalled — with current status and what's missing.
2. PENDING QUOTES: RFQs sent but not all answers in, or quotes awaiting a decision.
3. ACTION ITEMS: each as {"type": "followup"|"decision"|"signature",
   "counterparty_email": "...", "subject": "...", "what": "...",
   "draft_subject": "...", "draft_body": "..." }
   - "followup": a chase email is appropriate -> write the full draft (it will
     enter the approval queue; sign off: Best,\\n\\nBaci Milano Customer Care).
   - "decision"/"signature": Gomeh must act -> describe precisely what he must
     decide/sign and what happens if he's late.
Respond JSON only:
{"open_shipments": [...strings...], "pending_quotes": [...strings...],
 "action_items": [...]}"""


def shipment_audit() -> str:
    alias = "baci"
    svc = gmail_client.service_for(alias)
    resp = svc.users().threads().list(
        userId="me",
        q="newer_than:90d {shipment freight container customs quote RFQ "
          "forwarder pallet BOL \"packing list\"}",
        maxResults=40,
    ).execute()
    summaries = []
    for ref in resp.get("threads", [])[:40]:
        t = svc.users().threads().get(userId="me", id=ref["id"], format="metadata",
                                      metadataHeaders=["From", "Subject", "Date"]).execute()
        msgs = t.get("messages", [])
        if not msgs:
            continue
        last = msgs[-1]
        headers = {h["name"].lower(): h["value"] for h in last["payload"].get("headers", [])}
        summaries.append(f"- Subject: {headers.get('subject')} | last from: "
                         f"{headers.get('from')} | {headers.get('date')} | "
                         f"msgs: {len(msgs)} | snippet: {last.get('snippet', '')[:200]}")
    if not summaries:
        return "shipment_audit: no logistics threads found in 90 days"

    msg = client.messages.create(
        model=config.BUCKET_MODELS.get("logistics", config.CLAUDE_MODEL),
        max_tokens=4000, system=AUDIT_PROMPT,
        messages=[{"role": "user", "content": "\n".join(summaries)}],
    )
    text = msg.content[0].text.strip().strip("`")
    text = text[text.find("{"):text.rfind("}") + 1]
    audit = json.loads(text)

    drafts_made = 0
    escalations = []
    for item in audit.get("action_items", []):
        if item.get("type") == "followup" and item.get("draft_body"):
            approvals.request_approval(
                "send_email",
                f"[AUDIT followup] to {item.get('counterparty_email')}: {item.get('subject')}",
                {"account": alias, "to": item.get("counterparty_email", ""),
                 "subject": item.get("draft_subject") or f"Re: {item.get('subject')}",
                 "body": item["draft_body"],
                 "inbound_from": item.get("counterparty_email", ""),
                 "inbound_snippet": item.get("what", ""),
                 "reason": f"Shipment audit: {item.get('what', '')}"},
                notify=False,
            )
            drafts_made += 1
        else:
            escalations.append(f"  • [{item.get('type', '?').upper()}] "
                               f"{item.get('what', '')} ({item.get('subject', '')})")

    report = (
        "SHIPMENT & QUOTE AUDIT — Baci Milano USA (last 90 days)\n\n"
        "OPEN SHIPMENTS:\n" + "\n".join(f"  • {s}" for s in audit.get("open_shipments", ["none found"]))
        + "\n\nPENDING QUOTES:\n" + "\n".join(f"  • {q}" for q in audit.get("pending_quotes", ["none found"]))
        + f"\n\nFOLLOW-UP DRAFTS PREPARED: {drafts_made} (arriving in your next "
          "approval batch — one click each)\n\nNEEDS YOU PERSONALLY:\n"
        + ("\n".join(escalations) if escalations else "  • nothing")
    )
    from . import emailfmt
    gmail_client.send_email(config.NOTIFY_FROM_ALIAS, config.APPROVER_EMAIL,
                            "Shipment & quote audit — Baci Milano",
                            report, html=emailfmt.text_to_html(report))
    approvals.notify_pending(
        title=f"From the shipment audit: {drafts_made} follow-up drafts ready")
    return f"shipment_audit complete: {drafts_made} drafts, {len(escalations)} escalations"


REFILE_PROMPT = """You are deciding where ONE file from the '_Agent Intake'
staging area belongs in the Baci Milano USA B2B Drive. EXISTING STRUCTURE:
{tree}

File's current intake path: {path}
The file's CONTENTS are included above when readable — they are the primary
evidence (counterparty, PO/order numbers, dates, doc type).
You MUST pick an EXISTING folder from the structure above unless absolutely
nothing fits — new folders are a last resort (folder sprawl is a failure
mode). Old revisions -> parent's 'OLD VERSIONS'. If genuinely unsure, keep.
Respond JSON only: {{"target_path": "<path under B2B or 'keep'>",
"anchor": "<the entity that ties this file to others: counterparty + PO/"
"shipment id, e.g. 'Primorous PO-2241'>"}}"""

CONSOLIDATE_PROMPT = """You are finalizing a Drive reorganization plan.
EXISTING FOLDER STRUCTURE (paths under B2B):
{tree}

PROPOSED MOVES (file -> proposed target, with the anchor entity each file
belongs to):
{proposals}

Consolidate into a TETHER MAP: groups of files that belong together because
they share an anchor (same counterparty/PO/shipment). Rules:
1. ONE SHIPMENT = ONE FOLDER, even when ref numbers differ: a single order
   carries a client PO, supplier order #, forwarder ref, and invoice # —
   those are THE SAME entity. Tie them by counterparty + route + dates +
   product, not by matching strings.
2. REUSE EXISTING FOLDERS aggressively. A healthy result is ~8-15 order
   subfolders TOTAL — if your plan creates folders anywhere near the number
   of files, the plan is wrong; re-tether. New folder only when 2+ related
   files have no sensible existing home, named in plain English per order
   (e.g. 'FS Amaala Sept 2026').
3. Merge near-duplicate targets (e.g. 'Orders/Primorous' and
   'Primorous Order') into ONE folder, preferring the existing one.
4. Unmatched single files -> keep_in_intake (they surface in '_REVIEW' for
   Gomeh). One short rationale PER GROUP, never per file.
Respond JSON only:
{{"groups": [{{"target_path": "<folder under B2B>", "existing": true/false,
  "why": "<one line for the whole group>", "file_ids": ["..."]}}],
 "keep_in_intake": ["<file_id>", ...]}}"""


def refile_intake() -> str:
    """Read every intake file's contents, build a move plan, and queue it for
    Gomeh's approval. NOTHING MOVES until he approves the plan."""
    import base64 as _b64

    alias = DOC_SWEEP_ALIAS
    b2b = drive_io.find_folder(alias, B2B_FOLDER_NAME)
    if not b2b:
        return "FAILED: B2B folder not found"
    intake = drive_io.ensure_subfolder(alias, b2b, INTAKE_NAME)
    _status("refile_intake", state="listing intake")
    files = drive_io.list_all_files_recursive(alias, intake)[:150]
    if not files:
        return "refile_intake: intake is empty"
    tree_text = "\n".join(sorted(drive_io.folder_tree(alias, b2b, depth=3)))[:6000]

    plan, kept = [], 0
    _status("refile_intake", state="reading files", total=len(files))
    for idx, f in enumerate(files, 1):
        _status("refile_intake", progress=f"{idx}/{len(files)}", planned=len(plan))
        blocks: list = []
        if f["name"].lower().endswith(".pdf"):
            try:
                data = drive_io.download(alias, f["id"])
                if len(data) < 4_000_000:
                    blocks.append({"type": "document", "source": {
                        "type": "base64", "media_type": "application/pdf",
                        "data": _b64.standard_b64encode(data).decode()}})
            except Exception:  # noqa: BLE001
                pass
        blocks.append({"type": "text", "text": REFILE_PROMPT.format(
            tree=tree_text or "(empty)", path=f["path"])})
        try:
            msg = client.messages.create(
                model=config.CLAUDE_MODEL, max_tokens=200,
                messages=[{"role": "user", "content": blocks}],
            )
            verdict = _json_extract(msg.content[0].text)
            target = (verdict.get("target_path") or "keep").strip().strip("/")
        except Exception:  # noqa: BLE001
            log.exception("refile decision failed for %s", f["path"])
            verdict, target = {}, "keep"
        if target.lower() == "keep":
            kept += 1
        else:
            plan.append({"file_id": f["id"], "from": f["path"], "to": target,
                         "anchor": verdict.get("anchor", "")})

    _status("refile_intake", state="consolidating", proposals=len(plan))
    if not plan:
        return f"refile_intake: nothing to move ({kept} files stay in intake)"

    # Consolidation pass: tether map — group related files, collapse targets
    # into existing folders, never spawn a folder for a single stray.
    by_id = {m["file_id"]: m for m in plan}
    proposals = "\n".join(f"- id={m['file_id']} file='{m['from']}' -> "
                          f"'{m['to']}' anchor='{m['anchor']}'" for m in plan)
    try:
        msg = client.messages.create(
            model=config.CLAUDE_MODEL, max_tokens=2500,
            messages=[{"role": "user", "content": CONSOLIDATE_PROMPT.format(
                tree=tree_text or "(empty)", proposals=proposals)}],
        )
        result = _json_extract(msg.content[0].text)
        groups = result.get("groups", [])
        kept += len(result.get("keep_in_intake", []))
    except Exception:  # noqa: BLE001
        log.exception("consolidation failed — falling back to raw proposals")
        groups = [{"target_path": m["to"], "existing": False,
                   "why": m["anchor"], "file_ids": [m["file_id"]]} for m in plan]

    moves, map_lines, new_folders = [], [], 0
    for g in groups:
        ids = [i for i in g.get("file_ids", []) if i in by_id]
        if not ids:
            continue
        if not g.get("existing", True):
            new_folders += 1
        map_lines.append(f"\n📂 {g['target_path']}"
                         + ("  (new folder)" if not g.get("existing", True) else "")
                         + f"\n   Why: {g.get('why', '')}")
        for i in ids:
            map_lines.append(f"   – {by_id[i]['from']}")
            moves.append({"file_id": i, "from": by_id[i]["from"],
                          "to": g["target_path"]})

    _status("refile_intake", state="plan ready", planned=len(moves), kept=kept)
    if not moves:
        return f"refile_intake: nothing to move ({kept} stay in intake)"
    plan_text = ("TETHER MAP — files grouped by what binds them together:"
                 + "".join(map_lines)
                 + f"\n\n{kept} files stay in intake; "
                   f"{new_folders} new folder(s) proposed.")
    approvals.request_approval(
        "refile_moves",
        f"Refile plan: {len(moves)} files into {len(groups)} groups "
        f"({new_folders} new folders, {kept} stay put)",
        {"account": alias, "moves": moves,
         "subject": f"Refile plan: {len(moves)} files, {len(groups)} groups",
         "inbound_from": "Drive intake review",
         "inbound_snippet": "Content-based reorganization of _Agent Intake",
         "reason": "Grouped by shared counterparty/PO/shipment; existing "
                   "folders reused wherever possible.",
         "body": plan_text, "bucket": "logistics"},
    )
    return (f"refile plan queued: {len(moves)} files in {len(groups)} groups, "
            f"{new_folders} new folders — approve from the batch")


PACKET_SEARCHES = {
    "Power of Attorney": ["power of attorney", "POA"],
    "FDA": ["FDA"],
    "Commercial Invoice": ["commercial invoice"],
    "Packing List": ["packing list"],
    "Product Specs": ["product spec", "catalog", "line sheet"],
}

PICK_PROMPT = """Pick the single best candidate file to serve as the standing
'{doc_type}' in a freight-forwarder onboarding packet for Baci Milano USA
(an importer of Italian homeware). Prefer: most recent, final (not draft/old
version), company-level documents over one-off variants. Candidates:
{candidates}
Respond with ONLY the id of the best file, or NONE if none fit."""


def build_onboarding_packet() -> str:
    """Populate B2B/Forwarder Onboarding Packet from existing Drive files and
    email attachments; Gomeh reviews the emailed report and adjusts."""
    from . import data_tools, emailfmt
    alias = DOC_SWEEP_ALIAS
    b2b = drive_io.find_folder(alias, B2B_FOLDER_NAME)
    if not b2b:
        return "FAILED: B2B folder not found"
    packet = drive_io.ensure_subfolder(alias, b2b, data_tools.PACKET_FOLDER)
    placed, missing, ambiguous = [], [], []

    for doc_type, keywords in PACKET_SEARCHES.items():
        _status("build_onboarding_packet", state=f"searching: {doc_type}")
        if any(doc_type.lower() in f["name"].lower()
               for f in drive_io.list_files(alias, packet)):
            placed.append(f"{doc_type}: already in packet")
            continue
        # 1) Drive by filename
        candidates = []
        for kw in keywords:
            candidates += drive_io.name_search(alias, kw)
        seen, uniq = set(), []
        for c in candidates:
            if c["id"] not in seen:
                seen.add(c["id"])
                uniq.append(c)
        chosen = None
        if uniq:
            try:
                msg = client.messages.create(
                    model=config.CLAUDE_MODEL, max_tokens=50,
                    messages=[{"role": "user", "content": PICK_PROMPT.format(
                        doc_type=doc_type,
                        candidates="\n".join(f"- id={c['id']} name={c['name']} "
                                             f"modified={c['modifiedTime']}"
                                             for c in uniq[:10]))}],
                )
                pick = msg.content[0].text.strip()
                chosen = next((c for c in uniq if c["id"] in pick), None)
            except Exception:  # noqa: BLE001
                log.exception("pick failed")
        if chosen:
            link = drive_io.copy_file(alias, chosen["id"], packet,
                                      f"{doc_type} - {chosen['name']}")
            placed.append(f"{doc_type}: copied '{chosen['name']}' ({link})")
            if len(uniq) > 1:
                ambiguous.append(f"{doc_type}: also considered "
                                 + ", ".join(c["name"] for c in uniq[:4]
                                             if c["id"] != chosen["id"]))
            continue
        # 2) Email attachments fallback
        found = False
        try:
            svc = gmail_client.service_for(alias)
            resp = svc.users().messages().list(
                userId="me", q=f'has:attachment "{keywords[0]}"', maxResults=5,
            ).execute()
            for ref in resp.get("messages", []):
                full = svc.users().messages().get(userId="me", id=ref["id"],
                                                  format="full").execute()
                for att in gmail_client._extract_attachments(full["payload"]):
                    if att["filename"].lower().endswith((".pdf", ".docx", ".xlsx")):
                        data = gmail_client.download_attachment(alias, ref["id"],
                                                                att["attachment_id"])
                        drive_io.upload(alias, packet,
                                        f"{doc_type} - {att['filename']}", data,
                                        att["mime"] or "application/pdf")
                        placed.append(f"{doc_type}: pulled '{att['filename']}' "
                                      "from email")
                        found = True
                        break
                if found:
                    break
        except Exception:  # noqa: BLE001
            log.exception("email fallback failed for %s", doc_type)
        if not found:
            missing.append(doc_type)

    _status("build_onboarding_packet", state="done")
    report = ("Forwarder onboarding packet assembled — please review.\n\n"
              "PLACED:\n" + "\n".join(f"  • {p}" for p in placed))
    if ambiguous:
        report += ("\n\nOTHER CANDIDATES I CONSIDERED (swap if I picked wrong):\n"
                   + "\n".join(f"  • {a}" for a in ambiguous))
    if missing:
        report += ("\n\nSTILL MISSING — needs you:\n"
                   + "\n".join(f"  • {m}" for m in missing)
                   + "\n\nDrop these into B2B/" + data_tools.PACKET_FOLDER
                   + " (or tell me where they are) and the packet is complete.")
    gmail_client.send_email(config.NOTIFY_FROM_ALIAS, config.APPROVER_EMAIL,
                            "Onboarding packet ready for your review",
                            report, html=emailfmt.text_to_html(report))
    return (f"packet build complete: {len(placed)} placed, {len(missing)} missing")


WHATSAPP_FILE_PROMPT = """Gomeh just sent a document over WhatsApp to be filed
in the Baci Milano USA B2B Drive. EXISTING FOLDER STRUCTURE:
{tree}

RECENT CONVERSATION (context for what this document is and which order or
shipment it belongs to):
{chat}

Document: filename="{filename}", caption="{caption}"
The document itself is included above when readable — ITS CONTENTS ARE THE
PRIMARY EVIDENCE: read the counterparty, PO/order numbers, dates, and document
type straight from it. Conversation context is secondary; filename is the
weakest signal.

Decide where it belongs. Prefer existing folders; if naming a new one, be
specific (counterparty + PO/shipment), consistent with the structure.
Old revisions/drafts -> file under the parent's 'OLD VERSIONS'. Respond JSON only:
{{"target_path": "<folder path under B2B>",
 "rename_to": "<better filename or ''>",
 "note": "<one line: what this doc is>"}}"""


def file_whatsapp_document(media_id: str, filename: str, mime: str,
                           caption: str, chat_context: str) -> str:
    """Download a WhatsApp-sent document and file it into the B2B Drive."""
    from . import drive_io, whatsapp
    alias = DOC_SWEEP_ALIAS
    data, real_mime = whatsapp.download_media(media_id)
    b2b = drive_io.find_folder(alias, B2B_FOLDER_NAME)
    if not b2b:
        return "I couldn't find the B2B folder in Drive — document not filed."
    tree = "\n".join(sorted(drive_io.folder_tree(alias, b2b, depth=3)))[:6000]
    # The file itself is the primary context: pass PDFs/images into the
    # classification call so the model reads counterparty, PO numbers, dates.
    import base64 as _b64
    blocks: list = []
    eff_mime = (mime or real_mime or "").lower()
    if len(data) < 5_000_000:
        if "pdf" in eff_mime or filename.lower().endswith(".pdf"):
            blocks.append({"type": "document", "source": {
                "type": "base64", "media_type": "application/pdf",
                "data": _b64.standard_b64encode(data).decode()}})
        elif eff_mime.startswith("image/"):
            blocks.append({"type": "image", "source": {
                "type": "base64", "media_type": eff_mime,
                "data": _b64.standard_b64encode(data).decode()}})
    blocks.append({"type": "text", "text": WHATSAPP_FILE_PROMPT.format(
        tree=tree or "(empty)", chat=chat_context[:3000],
        filename=filename, caption=caption or "(none)")})
    try:
        msg = client.messages.create(
            model=config.CLAUDE_MODEL, max_tokens=300,
            messages=[{"role": "user", "content": blocks}],
        )
        meta = _json_extract(msg.content[0].text)
    except Exception:  # noqa: BLE001
        meta = {"target_path": f"{INTAKE_NAME}/WhatsApp", "rename_to": "",
                "note": "filed to intake (couldn't classify)"}
    target = (meta.get("target_path") or f"{INTAKE_NAME}/WhatsApp").strip("/")
    name = meta.get("rename_to") or filename
    folder_id = drive_io.ensure_path(alias, b2b, target)
    link = drive_io.upload(alias, folder_id, name, data,
                           mime or real_mime or "application/octet-stream")
    if link == "exists":
        return f"'{name}' already exists in B2B/{target} — skipped (no duplicate made)."
    return (f"Filed ✓ {meta.get('note', name)}\n→ B2B/{target}/{name}\n{link}")


JOBS = {"recategorize": recategorize, "doc_sweep": doc_sweep,
        "shipment_audit": shipment_audit, "refile_intake": refile_intake,
        "build_onboarding_packet": build_onboarding_packet}
