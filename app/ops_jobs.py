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


FILE_PROMPT = """You are filing business documents into the Baci Milano USA
B2B Drive. EXISTING FOLDER STRUCTURE (paths relative to B2B):
{tree}

Given an email and its attachments, decide where each file belongs.
RULES:
1. STRONGLY prefer an existing folder whose purpose matches. Only propose a
   new path when nothing fits, and name it consistently with the existing
   structure, descriptive and specific (counterparty + PO/shipment/project,
   e.g. 'Purchase Orders/Four Seasons Naples' — NEVER vague names like
   'Baci Milano USA', 'Documents', 'Files').
2. Use the email thread context (sender, subject, conversation) to identify
   the PO / shipment / project the files belong to.
3. Superseded drafts/old revisions (filename or thread implies a newer
   version exists, e.g. v1 when v2 is attached, 'draft', struck quotes):
   mark "old_version" — they will be filed in an OLD VERSIONS subfolder of
   the same parent.
Respond JSON only:
{{"target_path": "<folder path under B2B>",
 "files": {{"<filename>": "current|old_version|skip"}},
 "why": "<one line>"}}"""


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
    alias = DOC_SWEEP_ALIAS
    b2b = drive_io.find_folder(alias, B2B_FOLDER_NAME)
    if not b2b:
        return f"FAILED: no folder named '{B2B_FOLDER_NAME}' found in {alias} Drive"

    _status("doc_sweep", state="mapping drive structure")
    tree = drive_io.folder_tree(alias, b2b, depth=3)
    tree_text = "\n".join(sorted(tree)) [:6000] or "(B2B is empty)"
    system = FILE_PROMPT.format(tree=tree_text)

    emails = gmail_client.fetch_with_attachments(alias, DOC_SWEEP_DAYS)
    _status("doc_sweep", state="filing", total_emails=len(emails), filed=0)
    filed, skipped = [], 0
    for idx, em in enumerate(emails, 1):
        _status("doc_sweep", progress=f"{idx}/{len(emails)} emails", filed=len(filed))
        try:
            msg = client.messages.create(
                model=config.CLAUDE_MODEL, max_tokens=400, system=system,
                messages=[{"role": "user", "content":
                           f"From: {em['from']}\nSubject: {em['subject']}\n"
                           f"Thread snippet: {em['snippet']}\n"
                           f"Files: {[a['filename'] for a in em['attachments']]}"}],
            )
            meta = _json_extract(msg.content[0].text)
        except Exception:  # noqa: BLE001
            log.exception("filing decision failed")
            continue
        decisions = meta.get("files", {})
        target = (meta.get("target_path") or "").strip().strip("/")
        if not target:
            skipped += len(em["attachments"])
            continue
        for att in em["attachments"]:
            verdict = decisions.get(att["filename"], "current")
            if verdict == "skip":
                skipped += 1
                continue
            path = target + ("/OLD VERSIONS" if verdict == "old_version" else "")
            try:
                folder_id = drive_io.ensure_path(alias, b2b, path)
                data = gmail_client.download_attachment(alias, em["id"], att["attachment_id"])
                result = drive_io.upload(alias, folder_id, att["filename"], data,
                                         att["mime"] or "application/octet-stream")
                if result != "exists":
                    filed.append(f"{path}/{att['filename']} (from {em['from'][:40]})")
            except Exception:  # noqa: BLE001
                log.exception("upload failed: %s", att["filename"])

    _status("doc_sweep", state="done", filed=len(filed))
    report = (
        f"Document sweep of [{alias}] — last {DOC_SWEEP_DAYS} days\n\n"
        f"Filed {len(filed)} documents into the existing B2B structure "
        f"(old revisions in OLD VERSIONS subfolders; exact duplicates and "
        f"{skipped} irrelevant attachments skipped):\n\n"
        + "\n".join(f"  • {f}" for f in filed[:120])
        + "\n\nIf anything landed in the wrong place, tell the assistant on "
          "WhatsApp — corrections become filing rules."
    )
    from . import emailfmt
    gmail_client.send_email(config.NOTIFY_FROM_ALIAS, config.APPROVER_EMAIL,
                            f"Document sweep done — {len(filed)} files organized",
                            report, html=emailfmt.text_to_html(report))
    return f"doc_sweep complete: {len(filed)} filed"


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


REFILE_PROMPT = """You are reorganizing a messy '_Agent Intake' staging area
inside the Baci Milano USA B2B Drive. EXISTING FOLDER STRUCTURE:
{tree}

For each file below (shown with its current intake path, which hints at its
origin), decide its proper home. Prefer existing folders; propose new
descriptive paths only when nothing fits (counterparty + PO/shipment —
never vague). Mark obvious old revisions to go into 'OLD VERSIONS' under
their parent. Respond JSON only:
{{"moves": {{"<file_id>": "<target path under B2B, or 'keep'>"}}}}"""


def refile_intake() -> str:
    """Reorganize everything in _Agent Intake into the real B2B structure."""
    alias = DOC_SWEEP_ALIAS
    b2b = drive_io.find_folder(alias, B2B_FOLDER_NAME)
    if not b2b:
        return "FAILED: B2B folder not found"
    intake = drive_io.ensure_subfolder(alias, b2b, INTAKE_NAME)
    _status("refile_intake", state="listing intake")
    files = drive_io.list_all_files_recursive(alias, intake)
    if not files:
        return "refile_intake: intake is empty"
    tree_text = "\n".join(sorted(drive_io.folder_tree(alias, b2b, depth=3)))[:6000]
    system = REFILE_PROMPT.format(tree=tree_text or "(B2B is empty)")

    moved, kept = [], 0
    _status("refile_intake", state="refiling", total=len(files), moved=0)
    for i in range(0, len(files), 20):
        batch = files[i:i + 20]
        listing = "\n".join(f"- id={f['id']} path={f['path']}" for f in batch)
        try:
            msg = client.messages.create(
                model=config.CLAUDE_MODEL, max_tokens=1500, system=system,
                messages=[{"role": "user", "content": listing}],
            )
            moves = _json_extract(msg.content[0].text).get("moves", {})
        except Exception:  # noqa: BLE001
            log.exception("refile decision failed")
            continue
        for f in batch:
            target = (moves.get(f["id"]) or "keep").strip().strip("/")
            if target.lower() == "keep":
                kept += 1
                continue
            try:
                folder_id = drive_io.ensure_path(alias, b2b, target)
                drive_io.move(alias, f["id"], folder_id)
                moved.append(f"{f['path']} -> {target}")
            except Exception:  # noqa: BLE001
                log.exception("move failed: %s", f["path"])
        _status("refile_intake", progress=f"{min(i + 20, len(files))}/{len(files)}",
                moved=len(moved))

    _status("refile_intake", state="done", moved=len(moved))
    from . import emailfmt
    report = (f"Intake reorganization complete.\n\nMoved {len(moved)} files into "
              f"the proper B2B structure ({kept} left in intake for your call):\n\n"
              + "\n".join(f"  • {m}" for m in moved[:120]))
    gmail_client.send_email(config.NOTIFY_FROM_ALIAS, config.APPROVER_EMAIL,
                            f"Intake reorganized — {len(moved)} files refiled",
                            report, html=emailfmt.text_to_html(report))
    return f"refile_intake complete: {len(moved)} moved, {kept} kept"


JOBS = {"recategorize": recategorize, "doc_sweep": doc_sweep,
        "shipment_audit": shipment_audit, "refile_intake": refile_intake}
