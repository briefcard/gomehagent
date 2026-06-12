"""Conversational command agent — handles arbitrary free-text requests from
Gomeh (via WhatsApp, or any channel) by reasoning over the full toolset:
email, Drive, Shopify, Calendar, deadlines, and the maintenance jobs.

Same guardrails as everywhere: outbound email only via the approval queue,
money never moves, facts only from tools.
"""
import datetime as dt
import json
import logging

import anthropic
from googleapiclient.discovery import build

from . import approvals, config, data_tools, db, digest, gmail_client, memory, ops_jobs

log = logging.getLogger("cmd")
client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

SYSTEM = """You are Gomeh Saias's operations assistant for Baci Milano USA,
Eien Distributions (Eien Health), and Saias Consulting. He messages you on the
go; answer like a sharp chief of staff: concise, concrete, mobile-friendly
(no markdown tables, short lines).

You have tools: email search across all 3 inboxes, Google Drive search,
Shopify orders (both stores), Calendar (read/create), the deadline ledger,
maintenance jobs (doc_sweep, shipment_audit, recategorize), the current
digest, and queue_email_draft.

BIG-TASK PROTOCOL — for any multi-step or exhaustive request (audits,
"find all X", reorganizations, anything touching many emails/files):
1. ACKNOWLEDGE first: restate what you understood and lay out your plan in
   2-4 short lines (what you'll search, where, how you'll know you're done)
   BEFORE diving in. If the request is ambiguous, ask one sharp question.
2. BE EXHAUSTIVE: one search query is never enough. Enumerate variants —
   for subscriptions: 'receipt', 'invoice', 'payment confirmation', 'renewal',
   'subscription', 'billed', plus known vendor names — across ALL relevant
   inboxes, and paginate. Deduplicate before presenting.
3. REPORT COVERAGE: state what you actually searched ("6 query patterns
   across 3 inboxes, 12 months") and what you might have missed. NEVER
   present partial results as complete — say "found 14; areas I couldn't
   cover: X" rather than implying totality.
4. CLOSE LOOPS: end with what happens next — drafts queued, memory saved,
   follow-ups armed, or what you need from Gomeh.

HARD RULES (set by Gomeh Jun 12, 2026 — non-negotiable):
- ACTION CONFIRMATION: never state an action is completed unless a tool
  result explicitly confirmed it. Otherwise say "queued" or "pending".
  Applies to filing, refunds, cancellations, emails, payments — everything.
- TETHERING: one shipment/order may carry several reference numbers (client
  PO, supplier order #, forwarder ref, invoice #). They are ONE entity: one
  folder, one shipment record listing ALL refs in its notes. Never split a
  shipment across folders because a ref looks different.
- FILING DISCIPLINE: subfolders are plain-English per ORDER (e.g. "FS Amaala
  Sept 2026"). Group files by order — a healthy B2B tree has ~8-15 order
  subfolders, never one folder per file. Unmatched files -> '_Agent
  Intake/_REVIEW', flagged to Gomeh. Old revisions -> 'OLD VERSIONS'; never
  delete anything. Filing reports state: X filed to Y orders, X to OLD
  VERSIONS, X flagged for review.
- THREE ACCOUNTS, NEVER MIXED: personal / baci / eien each have their own
  inbox and Drive. Never cross-file documents between accounts.
- REFUNDS & CANCELLATIONS: push back first — understand the issue, offer a
  fix (replacement, exchange, troubleshooting, discount). If unresolvable,
  look up the order in Shopify and queue the refund/cancellation for Gomeh's
  approval. NEVER tell a customer it is processed before it actually is.

RULES:
- NEVER send email directly — queue_email_draft puts it in his approval queue.
- Money never moves on your say-so. Cancelling subscriptions, paying, booking:
  gather the facts, list what HE must do or queue drafts for counterparties.
- Facts only from tools or the conversation. If you can't verify, say so.
- For requests like "pending subscriptions to cancel": search email history
  for renewal/receipt patterns, cross-check the deadline ledger, and present
  a clean list with amounts and dates.
- For "organize my calendar": read events first, propose, then create blocks.
- Long jobs (doc_sweep etc.) run async — tell him the report comes by email.
- MEMORY: you carry the recent conversation, and you have save_memory /
  forget_memory tools. Whenever a task spans time (a shipment being chased,
  a quote pending, an instruction Gomeh gives like "always cc Jeff on X"),
  SAVE it. Update the same topic as it progresses; forget it when done.
  Your working memory is shown below and is shared with the email triage
  agent, so what you record changes how emails get handled too.
- SHIPMENTS: use upsert_shipment to keep structured records current as you
  learn things (booked, ETA changes, docs received, costs). These records are
  the source of truth shown to the email triage agent too.
- DOCUMENTS Gomeh sends on WhatsApp appear inline in the conversation — READ
  them (contents are the primary evidence: counterparty, PO numbers, dates).
  Decide from the conversation what he wants: usually save_file_to_drive into
  the right B2B folder (content-derived path and a clean descriptive name),
  but he may instead want data extracted, a quote recorded, or a question
  answered. Confirm what you did with path + link. If his text implies a file
  that hasn't arrived in the conversation yet, say you're ready for it —
  never claim "nothing was sent."
- FEEDBACK: when Gomeh critiques a draft or sets a writing preference, call
  add_voice_rule for that inbox so every future draft obeys it.
- Today's date: {today} (America/New_York).{memory_block}{shipments_block}"""

ACTION_TOOLS = [
    {"name": "run_job",
     "description": "Run a maintenance job asynchronously. Jobs: doc_sweep "
                    "(file email attachments into the B2B Drive structure), "
                    "refile_intake (reorganize the _Agent Intake staging area "
                    "into proper folders), shipment_audit (open shipments/"
                    "quotes + follow-up drafts), recategorize (re-bucket inboxes).",
     "input_schema": {"type": "object", "properties": {
         "job": {"type": "string", "enum": ["doc_sweep", "refile_intake",
                                            "shipment_audit", "recategorize",
                                            "build_onboarding_packet"]}},
         "required": ["job"]}},
    {"name": "job_status",
     "description": "Live progress of running/finished jobs (doc sweep, "
                    "refiling, audits) — use when Gomeh asks how a task is going.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "get_digest",
     "description": "Current status digest: pending approvals, recent email "
                    "actions, money deadlines.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "list_deadlines",
     "description": "Open money deadlines from the ledger.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "queue_email_draft",
     "description": "Queue an outbound email for Gomeh's approval (it is NOT "
                    "sent until he approves). account: personal|baci|eien.",
     "input_schema": {"type": "object", "properties": {
         "account": {"type": "string", "enum": ["personal", "baci", "eien"]},
         "to": {"type": "string"}, "subject": {"type": "string"},
         "body": {"type": "string"}}, "required": ["account", "to", "subject", "body"]}},
    {"name": "calendar_events",
     "description": "List calendar events for an account between two ISO "
                    "datetimes (America/New_York).",
     "input_schema": {"type": "object", "properties": {
         "account": {"type": "string", "enum": ["personal", "baci", "eien"]},
         "start": {"type": "string"}, "end": {"type": "string"}},
         "required": ["account", "start", "end"]}},
    {"name": "save_file_to_drive",
     "description": "Save a document Gomeh just sent in this conversation "
                    "into the B2B Drive. filename must match the attachment; "
                    "target_path is the folder under B2B (prefer existing "
                    "folders; specific names: counterparty + PO/shipment); "
                    "rename_to optional for a cleaner descriptive name.",
     "input_schema": {"type": "object", "properties": {
         "filename": {"type": "string"},
         "account": {"type": "string", "enum": ["baci", "eien", "personal"],
                     "description": "Which entity's Drive — NEVER cross-file "
                                    "between accounts. Default baci."},
         "target_path": {"type": "string"},
         "rename_to": {"type": "string",
                       "description": "Convention: DocType_Counterparty_ID_Date"
                                      ", e.g. BOL_Primorous_PO2241_2026-04-09.pdf"},
         "anchor": {"type": "string",
                    "description": "What ties this doc to others: counterparty"
                                   " + PO/shipment, e.g. 'Primorous PO-2241'"},
         "doc_type": {"type": "string",
                      "description": "BOL, commercial invoice, packing list, "
                                     "POA, quote..."}},
         "required": ["filename", "target_path"]}},
    {"name": "rfq_start",
     "description": "Launch an RFQ round: creates the RFQ + shipment records "
                    "and queues a quote-request email to each forwarder (all "
                    "go to Gomeh's approval first). Gather the cargo details "
                    "from Gomeh before calling: what/volume/weight/pallets, "
                    "pickup origin, incoterm, ready date, destination "
                    "(default: 4360 NW 135th St, Opa-locka, FL 33054).",
     "input_schema": {"type": "object", "properties": {
         "shipment_name": {"type": "string", "description": "e.g. 'Italy-Jun2026'"},
         "cargo": {"type": "string", "description": "full cargo description"},
         "origin": {"type": "string"}, "incoterm": {"type": "string"},
         "ready_date": {"type": "string"},
         "forwarder_emails": {"type": "array", "items": {"type": "string"}},
         "include_onboarding_packet": {"type": "boolean",
                                       "description": "true for NEW forwarders"}},
         "required": ["shipment_name", "cargo", "origin", "forwarder_emails"]}},
    {"name": "add_voice_rule",
     "description": "When Gomeh gives feedback about a draft or how replies "
                    "should be written ('too formal', 'never offer refunds "
                    "before photos'), save it as a permanent writing rule for "
                    "that inbox. Applies to all future drafts immediately.",
     "input_schema": {"type": "object", "properties": {
         "account": {"type": "string", "enum": ["personal", "baci", "eien"]},
         "rule": {"type": "string"}}, "required": ["account", "rule"]}},
    {"name": "upsert_shipment",
     "description": "Create or update a structured shipment record. Only pass "
                    "fields that changed. docs example: {\"BOL\": \"missing\", "
                    "\"packing list\": \"have\"}. status: quoting|booked|"
                    "in_transit|customs|arrived|received|closed. Record ALL "
                    "reference numbers (client PO, supplier order #, forwarder "
                    "ref, invoice #) in notes — they all identify this ONE "
                    "shipment.",
     "input_schema": {"type": "object", "properties": {
         "name": {"type": "string"}, "status": {"type": "string"},
         "eta": {"type": "string"}, "counterparty": {"type": "string"},
         "docs": {"type": "object"}, "costs": {"type": "object"},
         "notes": {"type": "string"}}, "required": ["name"]}},
    {"name": "list_shipments",
     "description": "All open shipment records with status, ETA, docs, costs.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "save_memory",
     "description": "Save/update a durable note in shared working memory "
                    "(ongoing tasks, decisions, standing instructions). Same "
                    "topic overwrites — use it to track task progress.",
     "input_schema": {"type": "object", "properties": {
         "topic": {"type": "string"}, "content": {"type": "string"}},
         "required": ["topic", "content"]}},
    {"name": "forget_memory",
     "description": "Archive a working-memory topic once it's resolved.",
     "input_schema": {"type": "object", "properties": {
         "topic": {"type": "string"}}, "required": ["topic"]}},
    {"name": "calendar_create_event",
     "description": "Create a calendar event (primary calendar).",
     "input_schema": {"type": "object", "properties": {
         "account": {"type": "string", "enum": ["personal", "baci", "eien"]},
         "title": {"type": "string"}, "start": {"type": "string"},
         "end": {"type": "string"}, "description": {"type": "string"}},
         "required": ["account", "title", "start", "end"]}},
]


RFQ_TEMPLATE = """Hello,

We'd like to request a quote for an upcoming shipment for Baci Milano USA:

Cargo: {cargo}
Pickup / origin: {origin}
Incoterm: {incoterm}
Ready date: {ready_date}
Delivery to: 4360 NW 135th St, Opa-locka, FL 33054

Please provide ALL-IN pricing covering: freight, origin charges, destination
charges, customs clearance, ISF (if ocean), chassis/drayage to our warehouse,
and an estimated duties figure. Please state explicitly anything excluded.
{packet_line}
We're collecting quotes this week and will confirm promptly.

Best,

Baci Milano Customer Care"""


def _rfq_start(args: dict) -> str:
    import datetime as dt

    shipment = args["shipment_name"]
    details = {"cargo": args["cargo"], "origin": args["origin"],
               "incoterm": args.get("incoterm", "to be advised"),
               "ready_date": args.get("ready_date", "as soon as possible")}
    emails = [e.strip().lower() for e in args["forwarder_emails"]]

    packet_line = ""
    if args.get("include_onboarding_packet"):
        packet = json.loads(data_tools.onboarding_packet())
        links = [f"- {k}: {v['link']}" for k, v in packet.items()
                 if isinstance(v, dict) and v.get("link")]
        missing = [k for k, v in packet.items() if v == "MISSING"]
        if links:
            packet_line = ("\nFor your files, our standing documentation:\n"
                           + "\n".join(links) + "\n")
        if missing:
            packet_line += (f"\n[NOTE TO GOMEH — not sent: packet is missing "
                            f"{', '.join(missing)}; add them to B2B/"
                            f"{data_tools.PACKET_FOLDER} and I'll include them "
                            f"in follow-ups.]\n")

    with db.SessionLocal() as s:
        if s.query(db.RFQ).filter(db.RFQ.shipment_name == shipment).first():
            return f"RFQ '{shipment}' already exists — use rfq_get."
        s.add(db.RFQ(shipment_name=shipment, details=details, forwarders=emails))
        if not s.query(db.Shipment).filter(db.Shipment.name == shipment).first():
            s.add(db.Shipment(name=shipment, status="quoting",
                              notes=f"RFQ sent {dt.date.today().isoformat()}"))
        s.commit()

    body = RFQ_TEMPLATE.format(**details, packet_line=packet_line)
    for to in emails:
        approvals.request_approval(
            "send_email",
            f"[RFQ {shipment}] quote request to {to}",
            {"account": "baci", "to": to,
             "subject": f"Quote request — {shipment} ({details['origin']} to Miami)",
             "body": body, "inbound_from": to,
             "inbound_snippet": f"RFQ round for {shipment}",
             "reason": "RFQ launched by Gomeh", "bucket": "logistics",
             "expect_reply": True},
            notify=False,
        )
    approvals.notify_pending(title=f"RFQ '{shipment}': {len(emails)} quote "
                                   "requests ready to send")
    memory.remember(f"RFQ {shipment}",
                    f"Sent to {len(emails)} forwarders {dt.date.today().isoformat()}; "
                    "awaiting quotes; chase via follow-up engine")
    return (f"RFQ '{shipment}' created. {len(emails)} quote-request drafts are "
            "in the approval queue. Replies will be recorded automatically and "
            "non-responders chased after 3 days.")


def _cal(alias: str):
    return build("calendar", "v3", credentials=gmail_client.creds_for(alias),
                 cache_discovery=False)


def _run_job_async(job: str) -> str:
    import threading

    from . import whatsapp

    def _run() -> None:
        try:
            result = ops_jobs.JOBS[job]()
            whatsapp.send_text(f"✅ {job}: {result}")
        except Exception as exc:  # noqa: BLE001
            whatsapp.send_text(f"❌ {job} failed: {exc.__class__.__name__}")

    threading.Thread(target=_run, daemon=True).start()
    return f"{job} started in background; emailed report on completion."


def _dispatch(name: str, args: dict) -> str:
    try:
        if name == "run_job":
            return _run_job_async(args["job"])
        if name == "job_status":
            return json.dumps(ops_jobs.STATUS) or "no jobs have run yet"
        if name == "save_memory":
            return memory.remember(args["topic"], args["content"])
        if name == "forget_memory":
            return memory.forget(args["topic"])
        if name == "save_file_to_drive":
            from . import drive_io
            f = _session_files.get(args["filename"])
            if f is None:
                return (f"No attachment named '{args['filename']}' in this "
                        f"conversation. Available: {list(_session_files)}")
            account = args.get("account", "baci")
            if account == "baci":
                root = drive_io.find_folder("baci", "B2B")
                if not root:
                    return "B2B folder not found in the Baci Drive."
            else:
                # eien/personal: file under that account's own 'Agent Filed'
                root = (drive_io.find_folder(account, "Agent Filed")
                        or drive_io.ensure_subfolder(account, "root", "Agent Filed"))
            folder_id = drive_io.ensure_path(account, root,
                                             args["target_path"].strip("/"))
            name_final = args.get("rename_to") or args["filename"]
            link = drive_io.upload(account, folder_id, name_final,
                                   f["data"], f["mime"])
            if link == "exists":
                return f"'{name_final}' already exists in B2B/{args['target_path']} — skipped."
            data_tools.index_document(
                name_final, args["target_path"].strip("/"), link,
                args.get("doc_type", ""), args.get("anchor", ""), "whatsapp")
            return f"Saved to B2B/{args['target_path']}/{name_final} — {link}"
        if name == "rfq_start":
            return _rfq_start(args)
        if name == "add_voice_rule":
            from . import voice_learn
            return voice_learn.add_rule(args["account"], args["rule"])
        if name == "upsert_shipment":
            with db.SessionLocal() as s:
                sh = (s.query(db.Shipment)
                      .filter(db.Shipment.name == args["name"]).first())
                if sh is None:
                    sh = db.Shipment(name=args["name"])
                    s.add(sh)
                for field in ("status", "eta", "counterparty", "notes"):
                    if args.get(field) is not None:
                        setattr(sh, field, args[field])
                if args.get("docs"):
                    sh.docs = {**(sh.docs or {}), **args["docs"]}
                if args.get("costs"):
                    sh.costs = {**(sh.costs or {}), **args["costs"]}
                sh.updated_at = db.utcnow()
                s.commit()
            return f"Shipment '{args['name']}' saved."
        if name == "list_shipments":
            with db.SessionLocal() as s:
                rows = (s.query(db.Shipment)
                        .filter(db.Shipment.status != "closed").all())
            return json.dumps([
                {"name": r.name, "status": r.status, "eta": r.eta,
                 "counterparty": r.counterparty, "docs": r.docs,
                 "costs": r.costs, "notes": r.notes} for r in rows]) or "none"
        if name == "get_digest":
            return digest.build_digest()
        if name == "list_deadlines":
            with db.SessionLocal() as s:
                rows = (s.query(db.Deadline)
                        .filter(db.Deadline.status.in_(["open", "alerted"]))
                        .order_by(db.Deadline.due_date).all())
            return json.dumps([{"due": r.due_date, "what": r.description,
                                "amount": r.amount, "account": r.account}
                               for r in rows]) or "none"
        if name == "queue_email_draft":
            approvals.request_approval(
                "send_email",
                f"[via WhatsApp] to {args['to']}: {args['subject']}",
                {"account": args["account"], "to": args["to"],
                 "subject": args["subject"], "body": args["body"],
                 "inbound_from": "command", "inbound_snippet": "(requested by Gomeh)",
                 "reason": "Drafted on Gomeh's instruction via command agent"},
            )
            return "Draft queued for approval."
        if name == "calendar_events":
            resp = _cal(args["account"]).events().list(
                calendarId="primary", timeMin=args["start"], timeMax=args["end"],
                singleEvents=True, orderBy="startTime", maxResults=30,
            ).execute()
            return json.dumps([
                {"title": e.get("summary"), "start": e["start"].get("dateTime", e["start"].get("date")),
                 "end": e["end"].get("dateTime", e["end"].get("date"))}
                for e in resp.get("items", [])
            ]) or "no events"
        if name == "calendar_create_event":
            ev = _cal(args["account"]).events().insert(calendarId="primary", body={
                "summary": args["title"],
                "description": args.get("description", "Created by assistant"),
                "start": {"dateTime": args["start"], "timeZone": "America/New_York"},
                "end": {"dateTime": args["end"], "timeZone": "America/New_York"},
            }).execute()
            return f"created: {ev.get('htmlLink', 'ok')}"
        return data_tools.dispatch(name, args)  # falls through to data tools
    except Exception as exc:  # noqa: BLE001
        return f"Tool error ({exc.__class__.__name__}): {str(exc)[:200]}"


# Attachments from the current WhatsApp exchange, readable by tools.
_session_files: dict[str, dict] = {}


def handle(text: str, attachments: list[dict] | None = None) -> str:
    """Process one message (optionally with documents/images) with full
    conversational continuity. attachments: [{filename, data, mime}]."""
    import base64 as _b64

    system = SYSTEM.format(today=dt.datetime.now().strftime("%A %Y-%m-%d"),
                           memory_block=memory.memory_block(),
                           shipments_block=memory.shipments_block())
    tools = data_tools.TOOLS + ACTION_TOOLS
    messages = memory.load_chat_history()

    _session_files.clear()
    if attachments:
        blocks: list = []
        for att in attachments:
            _session_files[att["filename"]] = att
            mime = (att.get("mime") or "").lower()
            if len(att["data"]) < 5_000_000:
                if "pdf" in mime or att["filename"].lower().endswith(".pdf"):
                    blocks.append({"type": "document", "source": {
                        "type": "base64", "media_type": "application/pdf",
                        "data": _b64.standard_b64encode(att["data"]).decode()}})
                elif mime.startswith("image/"):
                    blocks.append({"type": "image", "source": {
                        "type": "base64", "media_type": mime,
                        "data": _b64.standard_b64encode(att["data"]).decode()}})
        blocks.append({"type": "text", "text": text})
        messages.append({"role": "user", "content": blocks})
    else:
        messages.append({"role": "user", "content": text})
    memory.save_turn("user", text)
    reply = "I hit my step limit on that one — try breaking it into smaller asks."
    for _ in range(10):
        msg = client.messages.create(
            model=config.CLAUDE_MODEL, max_tokens=2000,
            system=system, tools=tools, messages=messages,
        )
        if msg.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": msg.content})
            results = []
            for block in msg.content:
                if block.type == "tool_use":
                    results.append({"type": "tool_result", "tool_use_id": block.id,
                                    "content": _dispatch(block.name, dict(block.input))[:8000]})
            messages.append({"role": "user", "content": results})
            continue
        reply = next((b.text for b in msg.content if b.type == "text"),
                     "Done (no further output).").strip()
        break
    memory.save_turn("assistant", reply)
    return reply
