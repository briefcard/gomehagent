"""Proposed-skill playbooks: tax export, invoice chasing, business pulse,
contract-expiry watch, duplicate cleanup, spend-pattern flags, schedule brief,
landed-cost, inbound inventory. Each is a structured procedure (gather data ->
analyze -> deliver/queue), reusable as a job or a conversational tool.
"""
import datetime as dt
import io
import json
import logging

import anthropic

from . import approvals, config, data_tools, db, drive_io, emailfmt, gmail_client

log = logging.getLogger("skills")
client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


def _send_report(subject: str, body: str, also_whatsapp: bool = True) -> None:
    from . import whatsapp
    gmail_client.send_email(config.NOTIFY_FROM_ALIAS, config.APPROVER_EMAIL,
                            subject, body, html=emailfmt.text_to_html(body))
    if also_whatsapp:
        whatsapp.send_text(body[:3500])


# ---------------- Tax-Receipt Export ----------------

def tax_receipt_export(year: str = "", account: str = "baci",
                       destination: str = "B2B") -> str:
    """Compile the expense ledger into an accountant-ready XLSX in Drive."""
    from openpyxl import Workbook
    from googleapiclient.http import MediaInMemoryUpload

    year = year or str(dt.date.today().year)
    with db.SessionLocal() as s:
        rows = [r for r in s.query(db.Expense).order_by(db.Expense.expense_date).all()
                if (r.expense_date or "").startswith(year) or
                (r.seen_at and r.seen_at.year == int(year))]
    wb = Workbook()
    ws = wb.active
    ws.title = f"Expenses {year}"
    ws.append(["Date", "Vendor", "Amount", "Source Subject", "Captured"])
    total = 0.0
    for r in rows:
        amt = r.amount or ""
        try:
            total += float(str(amt).replace("$", "").replace(",", ""))
        except ValueError:
            pass
        ws.append([r.expense_date or "", r.vendor or "", amt,
                   r.source_subject or "",
                   r.seen_at.strftime("%Y-%m-%d") if r.seen_at else ""])
    ws.append([])
    ws.append(["", "TOTAL", f"${total:,.2f}"])
    buf = io.BytesIO()
    wb.save(buf)

    root = drive_io.find_folder(account, destination)
    if not root:
        return f"Destination '{destination}' not found in {account} Drive."
    folder = drive_io.ensure_subfolder(account, root, "Tax Exports")
    svc = drive_io.svc(account)
    if drive_io.file_exists(account, folder, f"Expenses_{year}.xlsx"):
        # overwrite by find+update
        existing = svc.files().list(
            q=f"name='Expenses_{year}.xlsx' and '{folder}' in parents and trashed=false",
            fields="files(id)", includeItemsFromAllDrives=True,
            supportsAllDrives=True).execute().get("files", [])
        media = MediaInMemoryUpload(buf.getvalue(),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        f = svc.files().update(fileId=existing[0]["id"], media_body=media,
                               fields="webViewLink", supportsAllDrives=True).execute()
    else:
        media = MediaInMemoryUpload(buf.getvalue(),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        f = svc.files().create(
            body={"name": f"Expenses_{year}.xlsx", "parents": [folder]},
            media_body=media, fields="webViewLink",
            supportsAllDrives=True).execute()
    link = f.get("webViewLink", "")
    return (f"Tax receipt export ready: {len(rows)} expenses totaling "
            f"${total:,.2f} for {year}.\n{link}")


# ---------------- Invoice Chasing (AR) ----------------

def invoice_chase(account: str = "personal", days: int = 120) -> str:
    """Find invoices the owner SENT with no reply/payment and queue tone-matched
    reminders for approval."""
    svc = gmail_client.service_for(account)
    resp = svc.users().threads().list(
        userId="me", q=f'in:sent (invoice OR "amount due" OR payment) '
        f'has:attachment newer_than:{days}d', maxResults=30).execute()
    queued = []
    for ref in resp.get("threads", [])[:30]:
        t = svc.users().threads().get(userId="me", id=ref["id"],
            format="metadata", metadataHeaders=["To", "Subject", "From", "Date"]).execute()
        msgs = t.get("messages", [])
        if not msgs:
            continue
        last = msgs[-1]
        h = {x["name"].lower(): x["value"] for x in last["payload"].get("headers", [])}
        me = config.GMAIL_ACCOUNTS[account]["email"].lower()
        # If the last message is from us and no reply came after, it's unpaid/unanswered.
        if me not in h.get("from", "").lower():
            continue
        to = (msgs[0]["payload"] and {x["name"].lower(): x["value"]
              for x in msgs[0]["payload"].get("headers", [])}.get("to", "")) or h.get("to", "")
        subject = h.get("subject", "Invoice")
        approvals.request_approval(
            "send_email", f"[Invoice reminder] {to}: {subject}",
            {"account": account, "to": to,
             "subject": subject if subject.lower().startswith("re:") else f"Re: {subject}",
             "body": ("Hi,\n\nJust following up on the invoice I sent — please let "
                      "me know if you need anything to process it, or if it's "
                      "already on the way. Thank you!\n\nBest,\nGomeh"),
             "inbound_from": to, "inbound_snippet": "(invoice unpaid/unanswered)",
             "reason": "AR follow-up: invoice with no reply", "bucket": "client_comms",
             "expect_reply": True})
        queued.append(f"{to}: {subject}")
    if queued:
        approvals.notify_pending(title=f"{len(queued)} invoice reminders ready")
    return (f"Invoice chase: {len(queued)} reminders queued for approval.\n"
            + "\n".join(f"  • {q}" for q in queued[:20]))


# ---------------- Weekly Business Pulse ----------------

def business_pulse() -> str:
    """One-page state of the business: sales (both stores), shipments, money
    due, customer issues, pending approvals, top 3 to-dos."""
    lines = [f"Weekly Business Pulse — {dt.date.today().strftime('%b %d, %Y')}\n"]

    # Sales: orders in last 7 days per store
    for store in config.SHOPIFY_STORES:
        try:
            since = (dt.date.today() - dt.timedelta(days=7)).isoformat()
            orders = data_tools._shopify(store, "orders.json",
                {"status": "any", "created_at_min": since + "T00:00:00Z",
                 "fields": "id,total_price", "limit": 250}).get("orders", [])
            rev = sum(float(o.get("total_price", 0) or 0) for o in orders)
            lines.append(f"🛒 {store.title()}: {len(orders)} orders, ${rev:,.2f} (7d)")
        except Exception:  # noqa: BLE001
            lines.append(f"🛒 {store.title()}: (data unavailable)")

    with db.SessionLocal() as s:
        ships = s.query(db.Shipment).filter(db.Shipment.status != "closed").count()
        wk = (dt.date.today() + dt.timedelta(days=7)).isoformat()
        deads = s.query(db.Deadline).filter(
            db.Deadline.status.in_(["open", "alerted"]),
            db.Deadline.due_date <= wk).all()
        pend = s.query(db.Approval).filter(db.Approval.status == "pending").count()
        issues = s.query(db.EmailLog).filter(
            db.EmailLog.category == "order_issue",
            db.EmailLog.seen_at >= db.utcnow() - dt.timedelta(days=7)).count()
    lines.append(f"📦 Open shipments: {ships}")
    lines.append(f"😖 Order issues this week: {issues}")
    lines.append(f"⏳ Pending your approval: {pend}")
    if deads:
        lines.append("\n💸 Money due (7 days):")
        lines += [f"  • {d.due_date} — {d.description} ({d.amount})" for d in deads]

    # Top-3 via the model from this snapshot
    try:
        msg = client.messages.create(model=config.CLAUDE_MODEL, max_tokens=400,
            messages=[{"role": "user", "content":
                "From this weekly business snapshot, give the owner the 3 most "
                "important things to do this week, one line each, concrete.\n\n"
                + "\n".join(lines)}])
        lines.append("\n🎯 Top 3 this week:\n" + msg.content[0].text.strip())
    except Exception:  # noqa: BLE001
        pass
    body = "\n".join(lines)
    _send_report("Weekly Business Pulse", body)
    return "business_pulse sent"


# ---------------- Contract / Document Expiry Watch ----------------

def contract_expiry_watch() -> str:
    """Read filed contracts/agreements for renewal/expiry dates -> deadlines."""
    with db.SessionLocal() as s:
        docs = s.query(db.DocIndex).filter(
            db.DocIndex.doc_type.ilike("%contract%") |
            db.DocIndex.doc_type.ilike("%agreement%") |
            db.DocIndex.filename.ilike("%agreement%") |
            db.DocIndex.filename.ilike("%contract%")).all()
    added = 0
    import base64 as _b64
    for d in docs[:40]:
        if not d.link:
            continue
        try:
            fid = d.link.split("/d/")[-1].split("/")[0] if "/d/" in d.link else ""
            if not fid:
                continue
            data = drive_io.download("baci", fid)
            if len(data) > 4_000_000 or not d.filename.lower().endswith(".pdf"):
                continue
            msg = client.messages.create(model=config.CLAUDE_MODEL, max_tokens=200,
                messages=[{"role": "user", "content": [
                    {"type": "document", "source": {"type": "base64",
                     "media_type": "application/pdf",
                     "data": _b64.standard_b64encode(data).decode()}},
                    {"type": "text", "text":
                     "Does this contract have a renewal or expiry date? Respond JSON: "
                     '{"date":"YYYY-MM-DD or empty","what":"one line"}'}]}])
            r = json.loads(msg.content[0].text[msg.content[0].text.find("{"):
                                               msg.content[0].text.rfind("}") + 1])
            if r.get("date"):
                with db.SessionLocal() as s:
                    if not s.query(db.Deadline).filter(
                            db.Deadline.description == r["what"]).first():
                        s.add(db.Deadline(account="baci", description=r["what"],
                            amount="", due_date=r["date"],
                            source_subject=d.filename))
                        s.commit()
                        added += 1
        except Exception:  # noqa: BLE001
            continue
    return f"Contract expiry watch: {added} renewal/expiry dates added to deadlines."


# ---------------- Duplicate & Version Cleanup ----------------

def duplicate_cleanup(account: str = "baci", destination: str = "B2B") -> str:
    """Find same-name / same-content files in a Drive tree, propose a cleanup
    plan for approval (never deletes outright)."""
    root = drive_io.find_folder(account, destination)
    if not root:
        return f"'{destination}' not found."
    files = drive_io.list_all_files_recursive(account, root)
    by_name: dict = {}
    for f in files:
        by_name.setdefault(f["name"].lower(), []).append(f)
    dups = {n: fs for n, fs in by_name.items() if len(fs) > 1}
    if not dups:
        return "No duplicate-named files found."
    plan = []
    for name, fs in list(dups.items())[:50]:
        keep = fs[0]["path"]
        for extra in fs[1:]:
            plan.append(f"{extra['path']}  (dup of {keep})")
    body = (f"Found {len(dups)} duplicate-named file groups in {destination}. "
            "Review and tell me which to move to OLD VERSIONS or delete:\n\n"
            + "\n".join(f"  • {p}" for p in plan[:80]))
    _send_report(f"Duplicate cleanup — {len(dups)} groups", body, also_whatsapp=False)
    return f"duplicate_cleanup: {len(dups)} duplicate groups flagged (emailed)."


# ---------------- Spend Pattern Flags ----------------

def spend_flags(days: int = 90) -> str:
    """Surface duplicate charges and spend spikes from the expense ledger."""
    since = db.utcnow() - dt.timedelta(days=days)
    with db.SessionLocal() as s:
        rows = s.query(db.Expense).filter(db.Expense.seen_at >= since).all()
    by_vendor: dict = {}
    seen_charge: dict = {}
    dups = []
    for r in rows:
        v = (r.vendor or "?").lower()
        by_vendor.setdefault(v, []).append(r)
        key = (v, r.amount, r.expense_date)
        if r.amount and key in seen_charge:
            dups.append(f"{r.vendor} {r.amount} on {r.expense_date} (possible double charge)")
        seen_charge[key] = True
    lines = []
    if dups:
        lines.append("⚠️ Possible duplicate charges:")
        lines += [f"  • {d}" for d in dups[:20]]
    # vendors with many charges
    frequent = sorted(((v, len(rs)) for v, rs in by_vendor.items()), key=lambda x: -x[1])[:5]
    if frequent:
        lines.append("\nTop recurring vendors:")
        lines += [f"  • {v}: {n} charges" for v, n in frequent]
    body = "Spend pattern review (last %dd):\n\n" % days + ("\n".join(lines) or "Nothing unusual.")
    return body
