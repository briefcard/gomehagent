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

DOC_CLASSIFY = """Classify this email attachment for filing. Respond JSON only:
{"category": "purchase_order|shipment_doc|invoice_payable|quote|other",
 "group": "<short folder name: PO/order/shipment identifier or counterparty,
            e.g. 'PO-FourSeasons-Naples' or 'Shipment-Turkey-Mar2026';
            use sender company if nothing better>"}"""


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
    intake = drive_io.ensure_subfolder(alias, b2b, INTAKE_NAME)

    emails = gmail_client.fetch_with_attachments(alias, DOC_SWEEP_DAYS)
    filed, skipped = [], 0
    for em in emails:
        try:
            msg = client.messages.create(
                model=config.CLASSIFY_MODEL, max_tokens=120, system=DOC_CLASSIFY,
                messages=[{"role": "user", "content":
                           f"From: {em['from']}\nSubject: {em['subject']}\n"
                           f"Snippet: {em['snippet']}\n"
                           f"Files: {[a['filename'] for a in em['attachments']]}"}],
            )
            text = msg.content[0].text.strip().strip("`")
            text = text[text.find("{"):text.rfind("}") + 1]
            meta = json.loads(text)
        except Exception:  # noqa: BLE001
            meta = {"category": "other", "group": "Unsorted"}
        if meta.get("category") == "other":
            skipped += len(em["attachments"])
            continue
        group_folder = drive_io.ensure_subfolder(alias, intake, meta["group"])
        for att in em["attachments"]:
            try:
                data = gmail_client.download_attachment(alias, em["id"], att["attachment_id"])
                result = drive_io.upload(alias, group_folder, att["filename"], data,
                                         att["mime"] or "application/octet-stream")
                if result != "exists":
                    filed.append(f"{meta['group']}/{att['filename']} "
                                 f"({meta['category']}, from {em['from'][:40]})")
            except Exception:  # noqa: BLE001
                log.exception("upload failed: %s", att["filename"])

    report = (
        f"Document sweep of [{alias}] — last {DOC_SWEEP_DAYS} days\n\n"
        f"Filed {len(filed)} documents into B2B/{INTAKE_NAME}/ "
        f"(grouped by PO/shipment; duplicates skipped automatically; "
        f"{skipped} non-business attachments ignored):\n\n"
        + "\n".join(f"  • {f}" for f in filed[:120])
        + "\n\nReview the _Agent Intake folder and tell the assistant where "
          "anything should live differently — nothing in your existing B2B "
          "structure was touched."
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


JOBS = {"recategorize": recategorize, "doc_sweep": doc_sweep,
        "shipment_audit": shipment_audit}
