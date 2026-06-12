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
                                            "shipment_audit", "recategorize"]}},
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
                    "in_transit|customs|arrived|received|closed.",
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


def handle(text: str) -> str:
    """Process one free-text command with full conversational continuity."""
    system = SYSTEM.format(today=dt.datetime.now().strftime("%A %Y-%m-%d"),
                           memory_block=memory.memory_block(),
                           shipments_block=memory.shipments_block())
    tools = data_tools.TOOLS + ACTION_TOOLS
    messages = memory.load_chat_history()
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
