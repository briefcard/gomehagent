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
- Today's date: {today} (America/New_York).{memory_block}"""

ACTION_TOOLS = [
    {"name": "run_job",
     "description": "Run a maintenance job asynchronously. Jobs: doc_sweep "
                    "(file email attachments to Drive B2B intake), "
                    "shipment_audit (open shipments/quotes + follow-up drafts), "
                    "recategorize (re-bucket all inboxes).",
     "input_schema": {"type": "object", "properties": {
         "job": {"type": "string", "enum": ["doc_sweep", "shipment_audit", "recategorize"]}},
         "required": ["job"]}},
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
        if name == "save_memory":
            return memory.remember(args["topic"], args["content"])
        if name == "forget_memory":
            return memory.forget(args["topic"])
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
                           memory_block=memory.memory_block())
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
