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
