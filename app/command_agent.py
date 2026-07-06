"""Conversational command agent — handles arbitrary free-text requests from
Gomeh (via WhatsApp, or any channel) by reasoning over the full toolset:
email, Drive, Shopify, Calendar, deadlines, and the maintenance jobs.

Same guardrails as everywhere: outbound email only via the approval queue,
money never moves, facts only from tools.
"""
import datetime as dt
import json
import logging

from googleapiclient.discovery import build

from . import approvals, config, data_tools, db, digest, gmail_client, memory, ops_jobs

log = logging.getLogger("cmd")

# The admin agent's behavioral DNA now lives in app/kernel.py (shared by every
# agent); its role-specific identity lives in app/roles/admin.py. This module is
# the admin TOOL PACK: the schemas below plus admin_dispatch(). handle() at the
# bottom is a thin shim that runs this role through the kernel.

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
    {"name": "organize_emails",
     "description": "Organize ANY category of emails/attachments into Drive — "
                    "not just imports. Pull matching emails, dedup by content, "
                    "read each item, group, and file. Examples: receipts for "
                    "taxes (query 'receipt OR invoice OR payment', scheme "
                    "'vendor' or 'month', save_emails true), subscriptions "
                    "(query 'subscription OR renewal'), import docs (scheme "
                    "'orders'). Runs async; emails a report.",
     "input_schema": {"type": "object", "properties": {
         "account": {"type": "string", "enum": ["baci", "eien", "personal"]},
         "query": {"type": "string", "description": "Gmail search (e.g. "
                   "'receipt OR invoice OR \"payment confirmation\"')"},
         "destination": {"type": "string", "description": "Drive folder name, "
                         "e.g. 'B2B', 'Tax Receipts 2026', 'Subscriptions'"},
         "scheme": {"type": "string", "enum": ["orders", "vendor", "month"]},
         "save_emails": {"type": "boolean", "description": "true to also save "
                         "attachment-less emails (receipts in the body) as Docs"}},
         "required": ["account", "query", "destination", "scheme"]}},
    {"name": "export_tax_receipts",
     "description": "Compile the expense ledger into an accountant-ready XLSX "
                    "in Drive for a given year. Returns the link + total.",
     "input_schema": {"type": "object", "properties": {
         "year": {"type": "string"}, "account": {"type": "string"},
         "destination": {"type": "string"}}}},
    {"name": "chase_invoices",
     "description": "Find invoices the owner sent that have no reply/payment and "
                    "queue tone-matched reminders for approval. account default "
                    "personal (Saias client invoices).",
     "input_schema": {"type": "object", "properties": {
         "account": {"type": "string", "enum": ["personal", "baci", "eien"]},
         "days": {"type": "integer"}}}},
    {"name": "business_pulse",
     "description": "One-page state of the business: 7-day sales per store, open "
                    "shipments, order issues, money due, pending approvals, and "
                    "the top 3 to-dos this week.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "meeting_scan",
     "description": "Scan recent email across all inboxes for proposed meetings/"
                    "calls not yet on the calendar (firm and tentative) and "
                    "surface new ones to schedule. Runs 3x daily automatically; "
                    "this triggers it on demand.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "spend_flags",
     "description": "Surface possible duplicate charges and recurring-vendor "
                    "spend patterns from the expense ledger.",
     "input_schema": {"type": "object", "properties": {
         "days": {"type": "integer"}}}},
    {"name": "schedule_brief",
     "description": "Summarize a day or range of calendar events for an account, "
                    "flagging conflicts and prep needed.",
     "input_schema": {"type": "object", "properties": {
         "account": {"type": "string", "enum": ["personal", "baci", "eien"]},
         "start": {"type": "string"}, "end": {"type": "string"}},
         "required": ["account", "start", "end"]}},
    {"name": "reschedule_event",
     "description": "Move an existing calendar event to a new time (and notify "
                    "guests). Use calendar_events first to get the event id.",
     "input_schema": {"type": "object", "properties": {
         "account": {"type": "string", "enum": ["personal", "baci", "eien"]},
         "event_id": {"type": "string"}, "start": {"type": "string"},
         "end": {"type": "string"}},
         "required": ["account", "event_id", "start", "end"]}},
    {"name": "log_inbound_inventory",
     "description": "Record an inbound shipment's quantities against a Shopify "
                    "store's inventory (adds stock at a location on arrival). "
                    "store: baci|eien.",
     "input_schema": {"type": "object", "properties": {
         "store": {"type": "string", "enum": ["baci", "eien"]},
         "items": {"type": "array", "items": {"type": "object", "properties": {
             "sku": {"type": "string"}, "quantity": {"type": "integer"}}}}},
         "required": ["store", "items"]}},
    {"name": "find_unsubscribes",
     "description": "Identify recurring promotional/newsletter senders in an "
                    "inbox and propose bulk unsubscribe/filter rules.",
     "input_schema": {"type": "object", "properties": {
         "account": {"type": "string", "enum": ["personal", "baci", "eien"]}}}},
    {"name": "sync_catalog",
     "description": "Refresh the master 'AI Document Catalog' Google Sheet — a "
                    "clean, labeled index of every filed document (type, order/"
                    "anchor, folder, link) usable by any AI agent or human. "
                    "Returns the sheet link.",
     "input_schema": {"type": "object", "properties": {
         "account": {"type": "string", "enum": ["baci", "eien", "personal"]},
         "destination": {"type": "string"}}}},
    {"name": "job_status",
     "description": "Live progress of running/finished jobs (doc sweep, "
                    "refiling, audits) — use when Gomeh asks how a task is going.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "get_digest",
     "description": "Current status digest: pending approvals, recent email "
                    "actions, money deadlines.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "usage_report",
     "description": "API cost + cache-hit-rate audit for the last N days "
                    "(spend, cache savings, projected monthly, by purpose).",
     "input_schema": {"type": "object", "properties": {
         "days": {"type": "integer"}}}},
    {"name": "list_deadlines",
     "description": "Open money deadlines from the ledger.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "queue_email_draft",
     "description": "Queue an outbound email for Gomeh's approval (it is NOT "
                    "sent until he approves). account: personal|baci|eien.",
     "input_schema": {"type": "object", "properties": {
         "account": {"type": "string", "enum": ["personal", "baci", "eien"]},
         "to": {"type": "string"}, "subject": {"type": "string"},
         "body": {"type": "string"},
         "cc": {"type": "string", "description": "comma-separated CC addresses"}},
         "required": ["account", "to", "subject", "body"]}},
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
     "description": "Save/update a durable note in YOUR working memory (ongoing "
                    "tasks, decisions, standing instructions). Same topic "
                    "overwrites. Set shared=true ONLY for a cross-cutting fact "
                    "every agent should see; otherwise it stays with this agent.",
     "input_schema": {"type": "object", "properties": {
         "topic": {"type": "string"}, "content": {"type": "string"},
         "shared": {"type": "boolean"}},
         "required": ["topic", "content"]}},
    {"name": "forget_memory",
     "description": "Archive one of your working-memory topics once it's resolved.",
     "input_schema": {"type": "object", "properties": {
         "topic": {"type": "string"}}, "required": ["topic"]}},
    {"name": "systems_list",
     "description": "Index of the Systems Map — the durable docs describing how "
                    "Gomeh's world is organized (Drive taxonomies, filing "
                    "conventions, registries, projects).",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "systems_get",
     "description": "Read one Systems Map doc in full. READ the relevant doc "
                    "BEFORE any filing/organizing/bulk move and conform to it "
                    "(e.g. 'drive:baci', 'conventions:filing', 'project:<name>').",
     "input_schema": {"type": "object", "properties": {
         "key": {"type": "string"}}, "required": ["key"]}},
    {"name": "systems_update",
     "description": "Create/update a Systems Map doc after structure changed or "
                    "a project advanced — the next agent inherits the map, not "
                    "your memory. Keys: 'drive:<account>', 'conventions:<topic>', "
                    "'project:<name>'. pinned=true only for docs every turn "
                    "must see (keep those short).",
     "input_schema": {"type": "object", "properties": {
         "key": {"type": "string"}, "content": {"type": "string"},
         "title": {"type": "string"}, "pinned": {"type": "boolean"}},
         "required": ["key", "content"]}},
    {"name": "request_feature",
     "description": "File a feature request when you hit a real limitation "
                    "(missing tool, a cap that cut results, work you had to "
                    "fudge). State the concrete problem + proposed fix, then "
                    "continue with what you have. Refiling the same title "
                    "raises its priority count.",
     "input_schema": {"type": "object", "properties": {
         "title": {"type": "string"}, "problem": {"type": "string"},
         "proposal": {"type": "string"}}, "required": ["title", "problem"]}},
    {"name": "email_gomeh",
     "description": "Send an email DIRECTLY TO GOMEH (and only Gomeh — the "
                    "recipient is fixed) with a report, list, or document "
                    "summary. Sends immediately, no approval needed (it's an "
                    "internal notification, not outbound mail). USE THIS the "
                    "moment you tell Gomeh something is coming by email — "
                    "never promise a future email without calling this in the "
                    "same turn. Counterparty email still goes through "
                    "queue_email_draft.",
     "input_schema": {"type": "object", "properties": {
         "subject": {"type": "string"},
         "body": {"type": "string",
                  "description": "Plain text; keep structure with short lines "
                                 "and simple lists"}},
         "required": ["subject", "body"]}},
    {"name": "calendar_create_event",
     "description": "Create a calendar event and optionally invite guests "
                    "(they get a Google Calendar invitation email).",
     "input_schema": {"type": "object", "properties": {
         "account": {"type": "string", "enum": ["personal", "baci", "eien"]},
         "title": {"type": "string"}, "start": {"type": "string"},
         "end": {"type": "string"}, "description": {"type": "string"},
         "guests": {"type": "array", "items": {"type": "string"},
                    "description": "Attendee email addresses to invite"},
         "location": {"type": "string"}},
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
    # Honest promise only: results come back as a WhatsApp message (✅/❌ above)
    # — some jobs ALSO email a report, but never promise email generically.
    return (f"{job} started in background — the result will arrive here as a "
            "WhatsApp message when it finishes. Tell Gomeh exactly that; do "
            "not promise an email.")


def admin_dispatch(name: str, args: dict, session_files: dict) -> str:
    """Execute one admin tool call. ``session_files`` carries any attachments
    from the current exchange (the kernel passes them in)."""
    try:
        if name == "run_job":
            return _run_job_async(args["job"])
        if name == "organize_emails":
            import threading

            from . import whatsapp
            def _run():
                try:
                    r = ops_jobs.organize(
                        account=args.get("account", "baci"), query=args["query"],
                        destination=args["destination"], scheme=args.get("scheme", "vendor"),
                        save_emails=args.get("save_emails", False))
                    whatsapp.send_text(f"✅ {r}")
                except Exception as exc:  # noqa: BLE001
                    whatsapp.send_text(f"❌ organize failed: {exc.__class__.__name__}")
            threading.Thread(target=_run, daemon=True).start()
            return (f"Organizing {args['account']} '{args['query']}' by "
                    f"{args.get('scheme')} into {args['destination']} — running "
                    "now, emailed report when done.")
        if name == "export_tax_receipts":
            from . import skills
            return skills.tax_receipt_export(args.get("year", ""),
                args.get("account", "baci"), args.get("destination", "B2B"))
        if name == "chase_invoices":
            from . import skills
            return skills.invoice_chase(args.get("account", "personal"),
                                        int(args.get("days", 120)))
        if name == "business_pulse":
            from . import skills
            return skills.business_pulse()
        if name == "meeting_scan":
            from . import skills
            return skills.meeting_scan()
        if name == "spend_flags":
            from . import skills
            return skills.spend_flags(int(args.get("days", 90)))
        if name == "schedule_brief":
            resp = _cal(args["account"]).events().list(
                calendarId="primary", timeMin=args["start"], timeMax=args["end"],
                singleEvents=True, orderBy="startTime", maxResults=50).execute()
            evs = [{"title": e.get("summary"), "start": e["start"].get("dateTime", e["start"].get("date")),
                    "end": e["end"].get("dateTime", e["end"].get("date")),
                    "where": e.get("location", ""),
                    "guests": [a.get("email") for a in e.get("attendees", [])]}
                   for e in resp.get("items", [])]
            return json.dumps(evs) or "no events in range"
        if name == "reschedule_event":
            cal = _cal(args["account"])
            ev = cal.events().get(calendarId="primary", eventId=args["event_id"]).execute()
            ev["start"] = {"dateTime": args["start"], "timeZone": "America/New_York"}
            ev["end"] = {"dateTime": args["end"], "timeZone": "America/New_York"}
            out = cal.events().update(calendarId="primary", eventId=args["event_id"],
                body=ev, sendUpdates="all").execute()
            return f"Rescheduled — {out.get('htmlLink', 'ok')}"
        if name == "log_inbound_inventory":
            items = ", ".join(f"{it.get('sku')}: +{it.get('quantity')}"
                              for it in args.get("items", []))
            # Recorded against the shipment; the actual Shopify stock write
            # goes through approval (it changes sellable inventory).
            approvals.request_approval(
                "send_email",  # generic approval surface for now
                f"[Inventory] Add stock for {args['store']}: {items}",
                {"account": "baci", "to": "(internal)", "subject": "Inbound inventory",
                 "body": f"Add to {args['store']} inventory:\n{items}",
                 "inbound_from": "inventory", "inbound_snippet": items,
                 "reason": "Inbound inventory from a received shipment",
                 "bucket": "logistics"})
            return (f"Inbound inventory for {args['store']} queued for your "
                    f"approval: {items}")
        if name == "find_unsubscribes":
            acct = args.get("account", "personal")
            from collections import Counter
            senders: Counter = Counter()
            # service_for() returns a process-wide CACHED Gmail client; touching it
            # outside _google_lock races the locked gmail_client.* funcs on the same
            # shared httplib2 connection (segfault / Render exit 139). Serialize it.
            with gmail_client._google_lock:
                svc = gmail_client.service_for(acct)
                resp = svc.users().messages().list(userId="me",
                    q="category:promotions newer_than:60d", maxResults=100).execute()
                for ref in resp.get("messages", [])[:100]:
                    m = svc.users().messages().get(userId="me", id=ref["id"],
                        format="metadata", metadataHeaders=["From"]).execute()
                    frm = next((h["value"] for h in m["payload"].get("headers", [])
                                if h["name"].lower() == "from"), "")
                    addr = frm.split("<")[-1].rstrip(">").strip().lower()
                    if addr:
                        senders[addr] += 1
            top = senders.most_common(15)
            return json.dumps([{"sender": a, "promo_emails_60d": n} for a, n in top])
        if name == "sync_catalog":
            return ops_jobs.sync_catalog(args.get("account", "baci"),
                                         args.get("destination", "B2B"))
        if name == "job_status":
            return json.dumps(ops_jobs.STATUS) or "no jobs have run yet"
        if name == "save_memory":
            return memory.remember(args["topic"], args["content"],
                                   scope="global" if args.get("shared") else "admin")
        if name == "forget_memory":
            return memory.forget(args["topic"], scope="admin")
        if name == "systems_list":
            from . import systems_map
            return systems_map.list_docs()
        if name == "systems_get":
            from . import systems_map
            return systems_map.get_doc(args["key"])
        if name == "systems_update":
            from . import systems_map
            return systems_map.set_doc(args["key"], args["content"],
                                       title=args.get("title", ""),
                                       updated_by="admin",
                                       pinned=args.get("pinned"))
        if name == "request_feature":
            from . import systems_map
            return systems_map.request_feature("admin", args["title"],
                                               args["problem"],
                                               args.get("proposal", ""))
        if name == "email_gomeh":
            # Recipient is HARDCODED to Gomeh — internal notification lane, so
            # no approval gate (jobs/digests already email him server-side).
            from . import emailfmt
            gmail_client.send_email(
                config.NOTIFY_FROM_ALIAS, config.APPROVER_EMAIL,
                args["subject"], args["body"],
                html=emailfmt.text_to_html(args["body"]))
            return (f"Sent to {config.APPROVER_EMAIL}: '{args['subject']}' — "
                    "confirmed, you can tell Gomeh it's in his inbox.")
        if name == "save_file_to_drive":
            from . import drive_io
            f = session_files.get(args["filename"])
            if f is None:
                return (f"No attachment named '{args['filename']}' in this "
                        f"conversation. Available: {list(session_files)}")
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
        if name == "usage_report":
            from . import usage
            return json.dumps(usage.report(int(args.get("days", 7))))
        if name == "list_deadlines":
            with db.SessionLocal() as s:
                rows = (s.query(db.Deadline)
                        .filter(db.Deadline.status.in_(["open", "alerted"]))
                        .order_by(db.Deadline.due_date).all())
            return json.dumps([{"due": r.due_date, "what": r.description,
                                "amount": r.amount, "account": r.account}
                               for r in rows]) or "none"
        if name == "queue_email_draft":
            # Actually create the Gmail draft so Gomeh gets a real link + it's
            # editable in his inbox; queue it for approval too.
            draft_id = gmail_client.create_draft(
                args["account"], args["to"], args["subject"], args["body"],
                cc=args.get("cc", ""))
            link = (f"https://mail.google.com/mail/u/0/#drafts?compose={draft_id}"
                    if draft_id else "https://mail.google.com/mail/u/0/#drafts")
            approvals.request_approval(
                "send_email",
                f"[via WhatsApp] to {args['to']}: {args['subject']}",
                {"account": args["account"], "to": args["to"],
                 "subject": args["subject"], "body": args["body"],
                 "cc": args.get("cc", ""),
                 "inbound_from": "command",
                 "inbound_snippet": "(drafted on your instruction)",
                 "reason": "Drafted via command agent", "bucket": "client_comms"},
            )
            preview = args["body"][:300] + ("…" if len(args["body"]) > 300 else "")
            return (f"Draft queued for your approval.\nTo: {args['to']}\n"
                    f"Subject: {args['subject']}\n\nPreview:\n{preview}\n\n"
                    f"Edit/view in Gmail: {link}\n"
                    "(Approve/Deny buttons are on the approval message.)")
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
            ev_body = {
                "summary": args["title"],
                "description": args.get("description", "Created by assistant"),
                "start": {"dateTime": args["start"], "timeZone": "America/New_York"},
                "end": {"dateTime": args["end"], "timeZone": "America/New_York"},
            }
            if args.get("location"):
                ev_body["location"] = args["location"]
            guests = args.get("guests") or []
            if guests:
                ev_body["attendees"] = [{"email": g} for g in guests]
            ev = _cal(args["account"]).events().insert(
                calendarId="primary", body=ev_body,
                sendUpdates="all" if guests else "none",  # actually email invites
            ).execute()
            who = f" — invited {', '.join(guests)}" if guests else ""
            return f"created: {ev.get('htmlLink', 'ok')}{who}"
        return data_tools.dispatch(name, args)  # falls through to data tools
    except Exception as exc:  # noqa: BLE001
        return f"Tool error ({exc.__class__.__name__}): {str(exc)[:200]}"


# ---------------------------------------------------------------------------
# One WhatsApp number, every agent. handle() is a ROUTER: a slash command like
# /seo or /admin switches the active agent (persisted), and your messages route
# to it on its own thread — no extra phone numbers, same chat experience.
# ---------------------------------------------------------------------------
def _active() -> tuple[str, str]:
    """(role, thread) the WhatsApp number is currently talking to. Defaults to
    admin so existing behavior is unchanged until you switch."""
    with db.SessionLocal() as s:
        row = s.get(db.Setting, "wa_active")
        val = row.value if row else ""
    role, _, thread = val.partition("|")
    return (role or "admin"), (thread or role or "admin")


def _set_active(role: str, thread: str) -> None:
    with db.SessionLocal() as s:
        s.merge(db.Setting(key="wa_active", value=f"{role}|{thread}"))
        s.commit()


def _agents_help() -> str:
    from . import sites as sites_mod

    role_name, thread = _active()
    cur = role_name + (f" · {thread.split(':', 1)[1]}" if ":" in thread else "")
    client_cmds = "  ".join("/" + k for k in sites_mod.all_profiles())
    return ("Agents on this number — switch anytime, no extra numbers:\n"
            "• /admin — ops: email, orders, docs, logistics\n"
            "• /seo — SEO/GEO: Semrush, GSC/GA4, on-site changes\n"
            "• per client (SEO): " + client_cmds + "\n\n"
            f"Now talking to: {cur}\n"
            "Switch: /admin  /seo  " + client_cmds + "   ·   /agents to repeat\n"
            "(Admin keeps sending its own alerts/approvals regardless of who "
            "you're chatting with.)")


def handle(text: str, attachments: list[dict] | None = None,
           force_role: str | None = None) -> str:
    """WhatsApp entrypoint + router. A leading /<agent> switches the active agent
    (e.g. /seo, /seo eien, /admin); everything else routes to the active agent on
    its own thread. force_role bypasses the router for internal admin-only calls
    (e.g. revising an admin draft) so they never leak to another agent."""
    from . import kernel
    from . import roles as roles_pkg

    if force_role:
        return kernel.run(roles_pkg.get(force_role), text, attachments,
                          thread=force_role)

    stripped = (text or "").strip()
    low = stripped.lower()
    if low in ("/agents", "/agent", "/help", "/menu", "/who", "/current"):
        return _agents_help()
    if low.startswith("/"):
        parts = stripped[1:].split(None, 1)
        cmd = parts[0].lower()
        if cmd in roles_pkg.ROLES:  # /admin, /seo  -> switch agent (+ opt sub-thread)
            sub = parts[1].strip().lower() if len(parts) > 1 else ""
            thread = f"{cmd}:{sub}" if sub else cmd
            _set_active(cmd, thread)
            label = cmd.upper() + (f" · {sub}" if sub else "")
            return (f"✅ Switched to the {label} agent — your messages now go here. "
                    "/agents to see all, /admin to switch back.")
        from . import sites as sites_mod
        if cmd in sites_mod.all_profiles():  # /baci, /eien, /mtw -> SEO on that client
            _set_active("seo", f"seo:{cmd}")
            dom = sites_mod.get(cmd).get("domain", cmd)
            return (f"✅ Now on the SEO agent for {cmd} ({dom}). Ask away. "
                    "/admin for ops · /agents for all.")
        # unrecognized slash: fall through and let the active agent handle it

    role_name, thread = _active()
    return kernel.run(roles_pkg.get(role_name), text, attachments, thread=thread)
