"""Live data tools the triage agent can call before drafting a reply:
Shopify orders (both stores), Google Drive search, past email history.

Every tool returns a STRING (JSON or message) — errors come back as readable
messages so the agent can say "couldn't verify" instead of crashing.
"""
import json

import httpx
from googleapiclient.discovery import build

from . import config, gmail_client

API_VERSION = "2024-10"


# ---------- Shopify ----------
# Supports both auth styles:
#   legacy static token:   {"domain": "...", "token": "shpat_..."}
#   Dev Dashboard (2026+): {"domain": "...", "client_id": "...", "client_secret": "..."}
# Dev Dashboard tokens expire every 24h — fetched and refreshed automatically
# via the client credentials grant.

import time as _time

_shopify_tokens: dict[str, tuple[str, float]] = {}  # store -> (token, expires_at)


def _shopify_token(store: str) -> str:
    cfg = config.SHOPIFY_STORES[store]
    if cfg.get("token"):
        return cfg["token"]
    cached = _shopify_tokens.get(store)
    if cached and cached[1] > _time.time() + 300:  # 5-min safety margin
        return cached[0]
    r = httpx.post(
        f"https://{cfg['domain']}/admin/oauth/access_token",
        json={
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
            "grant_type": "client_credentials",
        },
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    token = data["access_token"]
    _shopify_tokens[store] = (token, _time.time() + int(data.get("expires_in", 86399)))
    return token


def _shopify(store: str, path: str, params: dict | None = None) -> dict:
    cfg = config.SHOPIFY_STORES[store]
    r = httpx.get(
        f"https://{cfg['domain']}/admin/api/{API_VERSION}/{path}",
        headers={"X-Shopify-Access-Token": _shopify_token(store)},
        params=params or {},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def shopify_find_orders(store: str, customer_email: str = "", order_number: str = "") -> str:
    if store not in config.SHOPIFY_STORES:
        return f"Store '{store}' not configured. Available: {list(config.SHOPIFY_STORES)}"
    params: dict = {"status": "any", "limit": 5,
                    "fields": "id,name,email,created_at,financial_status,"
                              "fulfillment_status,total_price,line_items"}
    if customer_email:
        params["email"] = customer_email.strip().lower()
    if order_number:
        params["name"] = order_number if order_number.startswith("#") else f"#{order_number}"
    orders = _shopify(store, "orders.json", params).get("orders", [])
    if not orders:
        return "No orders found."
    slim = [
        {
            "id": o["id"], "name": o["name"], "created_at": o["created_at"],
            "paid": o["financial_status"], "fulfillment": o["fulfillment_status"],
            "total": o["total_price"],
            "items": [f"{li['quantity']}x {li['title']}" for li in o.get("line_items", [])][:10],
        }
        for o in orders
    ]
    return json.dumps(slim)


def shopify_order_details(store: str, order_id: str) -> str:
    if store not in config.SHOPIFY_STORES:
        return f"Store '{store}' not configured."
    o = _shopify(store, f"orders/{order_id}.json").get("order", {})
    fulfillments = [
        {
            "status": f.get("status"),
            "tracking_company": f.get("tracking_company"),
            "tracking_numbers": f.get("tracking_numbers"),
            "tracking_urls": f.get("tracking_urls"),
            "updated_at": f.get("updated_at"),
        }
        for f in o.get("fulfillments", [])
    ]
    return json.dumps({
        "name": o.get("name"), "email": o.get("email"),
        "created_at": o.get("created_at"), "paid": o.get("financial_status"),
        "fulfillment_status": o.get("fulfillment_status"),
        "total": o.get("total_price"),
        "shipping_address": o.get("shipping_address"),
        "items": [f"{li['quantity']}x {li['title']}" for li in o.get("line_items", [])],
        "fulfillments": fulfillments,
        "cancelled_at": o.get("cancelled_at"),
    })


# ---------- Google Drive ----------

def drive_search(account: str, query: str) -> str:
    if account not in config.GMAIL_ACCOUNTS:
        return f"Account '{account}' unknown. Available: {list(config.GMAIL_ACCOUNTS)}"
    try:
        creds = gmail_client.creds_for(account)
        svc = build("drive", "v3", credentials=creds, cache_discovery=False)
        safe = query.replace("'", " ")
        resp = svc.files().list(
            q=f"fullText contains '{safe}' and trashed=false",
            pageSize=8,
            fields="files(id,name,mimeType,modifiedTime,webViewLink)",
        ).execute()
        files = resp.get("files", [])
        if not files:
            return "No matching Drive files."
        out = []
        for f in files:
            entry = {"name": f["name"], "modified": f["modifiedTime"],
                     "link": f["webViewLink"], "type": f["mimeType"]}
            if f["mimeType"] == "application/vnd.google-apps.document":
                try:
                    text = svc.files().export(fileId=f["id"], mimeType="text/plain").execute()
                    entry["content_preview"] = text.decode(errors="replace")[:1500]
                except Exception:  # noqa: BLE001
                    pass
            out.append(entry)
        return json.dumps(out)
    except Exception as exc:  # noqa: BLE001
        return (f"Drive not accessible for '{account}' ({exc.__class__.__name__}). "
                "Likely needs re-authorization with Drive scope.")


# ---------- Email history: TIERED retrieval ----------
# Spend tokens proportional to the question (Gomeh, Jul 2026): honor the asked
# scope; scan cheap metadata wide; deep-read ONLY what a relevance pass keeps;
# always report coverage so partial results can never masquerade as complete.

_SEARCH_MAX_IDS = 500     # id-scan ceiling per search (tier 0)
_SEARCH_MAX_META = 150    # metadata fetches per search (tier 1)
_SEARCH_MAX_DEEP = 25     # full-body reads per search (tier 3)
_SEARCH_OUT_BUDGET = 7200  # chars — the kernel truncates tool results at 8000


def _relevance_filter(intent: str, metas: list[dict]) -> list[int] | None:
    """Tier 2: one cheap classify call — which matches plausibly serve the
    intent? Returns indexes, or None on any failure (caller keeps everything:
    fail OPEN, never silently drop matches)."""
    try:
        import anthropic

        from . import usage
        lines = "\n".join(
            f"{i}|{m['date'][:16]}|{m['from'][:40]}|{m['subject'][:60]}|{m['snippet'][:60]}"
            for i, m in enumerate(metas))
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model=config.CLASSIFY_MODEL, max_tokens=400,
            system="You filter email search results. Reply with ONLY a JSON "
                   "array of the line numbers plausibly relevant to the goal. "
                   "Keep borderline cases (recall over precision).",
            messages=[{"role": "user",
                       "content": f"GOAL: {intent}\n\nLINES (idx|date|from|subject|snippet):\n{lines}"}])
        usage.log_usage("search_filter", config.CLASSIFY_MODEL, msg)
        text = next((b.text for b in msg.content if b.type == "text"), "")
        arr = json.loads(text[text.index("["):text.rindex("]") + 1])
        keep = sorted({int(i) for i in arr if 0 <= int(i) < len(metas)})
        return keep or None
    except Exception:  # noqa: BLE001 — fail open
        return None


def email_history_search(account: str, query: str, window_days: int = 0,
                         intent: str = "") -> str:
    """Tiered Gmail search. window_days bounds the scope EXACTLY as asked
    (0 = no time bound). intent triggers the relevance filter + full-body reads
    of the survivors; without intent you get metadata only (cheap recon)."""
    if account not in config.GMAIL_ACCOUNTS:
        return f"Account '{account}' unknown."
    q = query.strip()
    if window_days:
        q += f" newer_than:{int(window_days)}d"
    try:
        # Tier 0+1 under the Google lock (shared cached client — never race it)
        with gmail_client._google_lock:
            svc = gmail_client.service_for(account)
            ids: list[str] = []
            page = None
            while True:
                resp = svc.users().messages().list(
                    userId="me", q=q, maxResults=100, pageToken=page).execute()
                ids += [m["id"] for m in resp.get("messages", [])]
                page = resp.get("nextPageToken")
                if not page or len(ids) >= _SEARCH_MAX_IDS:
                    break
            matched, beyond_scan = len(ids), bool(page)
            metas = []
            for mid in ids[:_SEARCH_MAX_META]:
                m = svc.users().messages().get(
                    userId="me", id=mid, format="metadata",
                    metadataHeaders=["From", "To", "Subject", "Date"]).execute()
                h = {x["name"].lower(): x["value"]
                     for x in m["payload"].get("headers", [])}
                metas.append({"id": mid, "date": h.get("date", "")[:22],
                              "from": h.get("from", ""), "subject": h.get("subject", ""),
                              "snippet": m.get("snippet", "")[:100]})
        if not metas:
            return (f"COVERAGE: query='{q}' -> 0 matches. Complete within scope"
                    + (f" (last {window_days}d)." if window_days else "."))

        # Tier 2 (outside the lock — it's an Anthropic call, not Google)
        keep = list(range(len(metas)))
        filtered = False
        if intent and len(metas) > 12:
            f = _relevance_filter(intent, metas)
            if f is not None:
                keep, filtered = f, True

        # Tier 3: deep-read only the survivors, bounded
        deep: dict[int, str] = {}
        if intent:
            with gmail_client._google_lock:
                svc = gmail_client.service_for(account)
                for i in keep[:_SEARCH_MAX_DEEP]:
                    m = svc.users().messages().get(
                        userId="me", id=metas[i]["id"], format="full").execute()
                    body = gmail_client._extract_text(m["payload"])
                    atts = [p.get("filename") for p in
                            m["payload"].get("parts", []) if p.get("filename")]
                    deep[i] = body[:700] + (f" [attachments: {', '.join(atts)}]"
                                            if atts else "")

        receipt = (f"COVERAGE: query='{q}' -> matched {matched}"
                   f"{'+' if beyond_scan else ''}; metadata scanned {len(metas)}"
                   + (f"; relevance-kept {len(keep)}" if filtered else "")
                   + (f"; read {len(deep)} in full" if deep else
                      "; metadata only — pass intent= to read bodies"))
        if beyond_scan or matched > len(metas):
            receipt += (f". ⚠ INCOMPLETE: matches beyond the scan ceiling — "
                        f"narrow window_days or refine the query, then re-run.")
        else:
            receipt += (f". Complete within scope"
                        + (f" (last {window_days}d)." if window_days else "."))

        # Assemble within the output budget — announce anything cut, never hide it
        kept_set = set(keep)
        items = []
        for i, meta in enumerate(metas):
            if filtered and i not in kept_set:
                continue
            it = dict(meta)
            if i in deep:
                it["body"] = deep[i]
            items.append(it)
        out, shown = receipt + "\n", 0
        for it in items:
            s = json.dumps(it)
            if len(out) + len(s) > _SEARCH_OUT_BUDGET:
                out += (f"…output budget reached: {len(items) - shown} more "
                        "matches not shown — narrow the scope and re-run.")
                break
            out += s + "\n"
            shown += 1
        if filtered and len(keep) < len(metas):
            dropped = [metas[i]["subject"][:50] for i in range(len(metas))
                       if i not in kept_set][:15]
            out += f"(filtered out as off-goal: {'; '.join(dropped)})"
        return out
    except Exception as exc:  # noqa: BLE001
        return f"Email search failed: {exc.__class__.__name__}: {str(exc)[:150]}"


def read_email(account: str, message_id: str) -> str:
    """Full body + headers of ONE email by id (ids come from
    email_history_search). The precision tool after a wide scan."""
    if account not in config.GMAIL_ACCOUNTS:
        return f"Account '{account}' unknown."
    try:
        with gmail_client._google_lock:
            svc = gmail_client.service_for(account)
            m = svc.users().messages().get(
                userId="me", id=message_id, format="full").execute()
        h = {x["name"].lower(): x["value"]
             for x in m["payload"].get("headers", [])}
        atts = [p.get("filename") for p in m["payload"].get("parts", [])
                if p.get("filename")]
        return json.dumps({
            "from": h.get("from"), "to": h.get("to"), "cc": h.get("cc", ""),
            "date": h.get("date"), "subject": h.get("subject"),
            "thread_id": m.get("threadId"),
            "body": gmail_client._extract_text(m["payload"])[:6000],
            "attachments": atts or "none — use read_email_attachment if listed"})
    except Exception as exc:  # noqa: BLE001
        return f"read_email failed: {exc.__class__.__name__}: {str(exc)[:150]}"


def _pdf_text(data: bytes) -> str:
    import io

    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    return "\n".join((p.extract_text() or "") for p in reader.pages[:25]).strip()


def read_email_attachment(account: str, message_id: str, filename: str = "") -> str:
    """Read a PDF/text attachment's CONTENT from one email — the on-demand
    counterpart of triage's automatic PDF reading, so interactive asks about a
    document never rely on the snippet."""
    if account not in config.GMAIL_ACCOUNTS:
        return f"Account '{account}' unknown."
    try:
        with gmail_client._google_lock:
            svc = gmail_client.service_for(account)
            m = svc.users().messages().get(
                userId="me", id=message_id, format="full").execute()
        parts = [p for p in m["payload"].get("parts", []) if p.get("filename")]
        if not parts:
            return "That email has no attachments."
        want = filename.strip().lower()
        part = next((p for p in parts if want and want in p["filename"].lower()),
                    parts[0] if not want else None)
        if part is None:
            return f"No attachment matching '{filename}'. Available: " \
                   f"{[p['filename'] for p in parts]}"
        att_id = part["body"].get("attachmentId")
        if not att_id:
            return f"'{part['filename']}' has no downloadable body."
        data = gmail_client.download_attachment(account, message_id, att_id)
        name = part["filename"]
        if name.lower().endswith(".pdf"):
            text = _pdf_text(data)
            if not text:
                return (f"'{name}' has no text layer (likely a scanned image "
                        "PDF) — I can't read it here; flag it to Gomeh.")
            return f"[{name}, {len(data)} bytes]\n{text[:6500]}"
        if name.lower().endswith((".txt", ".csv")):
            return f"[{name}]\n{data.decode(errors='replace')[:6500]}"
        return (f"'{name}' ({part.get('mimeType', '?')}) — I can read pdf/txt/csv "
                "here. Others: save to Drive and open there.")
    except Exception as exc:  # noqa: BLE001
        return f"read_email_attachment failed: {exc.__class__.__name__}: {str(exc)[:150]}"


# ---------- Contacts (derived from real correspondence) ----------

def find_contacts(account: str, who: str) -> str:
    """Find email addresses for a person/company from actual mail history —
    powers invitee suggestions and 'who do I email about X'. No extra scope:
    derived from who Gomeh has corresponded with."""
    if account not in config.GMAIL_ACCOUNTS:
        return f"Account '{account}' unknown."
    try:
        # Shared cached Gmail client — always under the Google lock.
        with gmail_client._google_lock:
            svc = gmail_client.service_for(account)
            resp = svc.users().messages().list(
                userId="me", q=f"({who}) (in:sent OR in:inbox)", maxResults=15,
            ).execute()
            msgs = [svc.users().messages().get(
                        userId="me", id=ref["id"], format="metadata",
                        metadataHeaders=["From", "To"]).execute()
                    for ref in resp.get("messages", [])]
        seen: dict[str, str] = {}
        import re
        for msg in msgs:
            for h in msg["payload"].get("headers", []):
                for m in re.finditer(r"([\w.+-]+@[\w.-]+\.\w+)", h["value"]):
                    addr = m.group(1).lower()
                    if addr not in config.GMAIL_ACCOUNTS and addr not in seen:
                        name = h["value"].split("<")[0].strip(' "') if "<" in h["value"] else ""
                        seen[addr] = name
        if not seen:
            return f"No contacts found matching '{who}'."
        return json.dumps([{"email": a, "name": n} for a, n in list(seen.items())[:10]])
    except Exception as exc:  # noqa: BLE001
        return f"Contact lookup failed: {exc.__class__.__name__}"


# ---------- Document registry ----------

def index_document(filename: str, path: str, link: str = "", doc_type: str = "",
                   anchor: str = "", source: str = "", content_hash: str = "") -> None:
    """Record a filed document for instant recall. Updates on re-file."""
    from . import db
    with db.SessionLocal() as s:
        row = (s.query(db.DocIndex)
               .filter(db.DocIndex.filename == filename).first())
        if row:
            row.path, row.created_at = path, db.utcnow()
            if link:
                row.link = link
            if anchor:
                row.anchor = anchor
            if doc_type:
                row.doc_type = doc_type
            if content_hash:
                row.content_hash = content_hash
        else:
            s.add(db.DocIndex(filename=filename, path=path, link=link,
                              doc_type=doc_type, anchor=anchor, source=source,
                              content_hash=content_hash))
        s.commit()


def hash_already_filed(content_hash: str) -> str | None:
    """If a document with this exact content is already filed, return its path."""
    from . import db
    if not content_hash:
        return None
    with db.SessionLocal() as s:
        row = (s.query(db.DocIndex)
               .filter(db.DocIndex.content_hash == content_hash).first())
        return f"B2B/{row.path}/{row.filename}" if row else None


def find_documents(query: str) -> str:
    """Search the document registry by counterparty, PO/shipment, doc type,
    or filename. Much more reliable than Drive full-text search."""
    from . import db
    q = f"%{query.strip()}%"
    with db.SessionLocal() as s:
        rows = (s.query(db.DocIndex)
                .filter(db.DocIndex.filename.ilike(q)
                        | db.DocIndex.path.ilike(q)
                        | db.DocIndex.anchor.ilike(q)
                        | db.DocIndex.doc_type.ilike(q))
                .order_by(db.DocIndex.created_at.desc()).limit(15).all())
    if not rows:
        return ("No registry matches — try drive_search as fallback "
                "(registry only covers documents filed by the agent).")
    return json.dumps([{"file": r.filename, "path": f"B2B/{r.path}",
                        "link": r.link, "type": r.doc_type,
                        "anchor": r.anchor} for r in rows])


# ---------- RFQ & forwarder onboarding ----------

PACKET_FOLDER = "Forwarder Onboarding Packet"
PACKET_REQUIRED = ["Power of Attorney", "FDA", "Commercial Invoice",
                   "Packing List", "Product Specs"]


def onboarding_packet() -> str:
    """Locate the standing forwarder-onboarding documents in the B2B Drive.
    Returns each required doc with its link, or 'MISSING'."""
    from . import drive_io
    alias = "baci"
    b2b = drive_io.find_folder(alias, "B2B")
    if not b2b:
        return "B2B folder not found in Drive."
    folder = drive_io.ensure_subfolder(alias, b2b, PACKET_FOLDER)
    files = drive_io.list_files(alias, folder)
    with gmail_client._google_lock:  # cached drive client — serialized lane
        detail = drive_io.svc(alias).files().list(
            q=f"'{folder}' in parents and trashed = false",
            fields="files(id,name,webViewLink)", includeItemsFromAllDrives=True,
            supportsAllDrives=True, pageSize=100,
        ).execute().get("files", [])
    by_name = {f["name"]: f.get("webViewLink", "") for f in detail}
    out = {}
    for req in PACKET_REQUIRED:
        match = next((n for n in by_name if req.lower() in n.lower()), None)
        out[req] = {"file": match, "link": by_name.get(match, "")} if match else "MISSING"
    out["_other_files"] = [n for n in by_name
                           if not any(r.lower() in n.lower() for r in PACKET_REQUIRED)]
    out["_folder"] = f"B2B/{PACKET_FOLDER}"
    return json.dumps(out)


def rfq_get(shipment_name: str) -> str:
    from . import db
    with db.SessionLocal() as s:
        r = s.query(db.RFQ).filter(db.RFQ.shipment_name == shipment_name).first()
        if not r:
            names = [x.shipment_name for x in s.query(db.RFQ).all()]
            return f"No RFQ named '{shipment_name}'. Existing: {names}"
        return json.dumps({"shipment": r.shipment_name, "status": r.status,
                           "details": r.details, "sent_to": r.forwarders,
                           "quotes": r.quotes})


def rfq_record_quote(shipment_name: str, forwarder_email: str, total: str,
                     breakdown: str = "", notes: str = "") -> str:
    """Record a quote received from a forwarder. Pings Gomeh when all
    forwarders have answered."""
    import datetime as dt

    from . import db, whatsapp
    with db.SessionLocal() as s:
        r = s.query(db.RFQ).filter(db.RFQ.shipment_name == shipment_name).first()
        if not r:
            return f"No RFQ named '{shipment_name}' — create it first."
        r.quotes = {**(r.quotes or {}), forwarder_email.lower(): {
            "total": total, "breakdown": breakdown, "notes": notes,
            "received": dt.date.today().isoformat()}}
        answered = set(r.quotes)
        expected = {f.lower() for f in (r.forwarders or [])}
        complete = expected and expected <= answered
        if complete:
            r.status = "complete"
        s.commit()
    if complete:
        whatsapp.send_text(f"📋 All quotes are in for '{shipment_name}'. "
                           f"Say 'compare quotes for {shipment_name}' and I'll "
                           "lay them out with a recommendation.")
    return f"Quote recorded for {shipment_name} from {forwarder_email}." + \
           (" ALL QUOTES NOW IN." if complete else "")

TOOLS = [
    {
        "name": "shopify_find_orders",
        "description": "Find recent Shopify orders by customer email and/or order "
                       "number. Stores: 'baci' (Baci Milano), 'eien' (Eien Health). "
                       "Use when a customer asks about their order.",
        "input_schema": {"type": "object", "properties": {
            "store": {"type": "string", "enum": ["baci", "eien"]},
            "customer_email": {"type": "string"},
            "order_number": {"type": "string"},
        }, "required": ["store"]},
    },
    {
        "name": "shopify_order_details",
        "description": "Full order details including fulfillment status, tracking "
                       "numbers and tracking URLs. Use after shopify_find_orders.",
        "input_schema": {"type": "object", "properties": {
            "store": {"type": "string", "enum": ["baci", "eien"]},
            "order_id": {"type": "string"},
        }, "required": ["store", "order_id"]},
    },
    {
        "name": "drive_search",
        "description": "Full-text search Google Drive of an account ('personal', "
                       "'baci', 'eien'). Returns file names, links, and content "
                       "previews for Google Docs. Use for price lists, shipment "
                       "documents, catalogs, agreements.",
        "input_schema": {"type": "object", "properties": {
            "account": {"type": "string", "enum": ["personal", "baci", "eien"]},
            "query": {"type": "string"},
        }, "required": ["account", "query"]},
    },
    {
        "name": "email_history_search",
        "description": "TIERED email search (Gmail query syntax, e.g. "
                       "'from:hana@cargohansa.com', 'subject:invoice'). Honors "
                       "scope EXACTLY: window_days=30 when Gomeh says 'past "
                       "month' — don't sweep all history unless he asked. Pass "
                       "intent (what you're actually after) to relevance-filter "
                       "the matches and read the survivors in full; omit it for "
                       "a cheap metadata recon. ALWAYS repeat the returned "
                       "COVERAGE line to Gomeh — never present a ⚠ INCOMPLETE "
                       "result as complete.",
        "input_schema": {"type": "object", "properties": {
            "account": {"type": "string", "enum": ["personal", "baci", "eien"]},
            "query": {"type": "string"},
            "window_days": {"type": "integer",
                            "description": "Time scope in days; 0/omit = no bound"},
            "intent": {"type": "string",
                       "description": "The goal, e.g. 'recurring monthly "
                                      "charges we still pay' — enables filter + "
                                      "full-body reads"},
        }, "required": ["account", "query"]},
    },
    {
        "name": "read_email",
        "description": "Full body + headers + attachment list of ONE email by "
                       "message id (ids come from email_history_search). Use "
                       "for precision after a wide scan.",
        "input_schema": {"type": "object", "properties": {
            "account": {"type": "string", "enum": ["personal", "baci", "eien"]},
            "message_id": {"type": "string"},
        }, "required": ["account", "message_id"]},
    },
    {
        "name": "read_email_attachment",
        "description": "Read the CONTENT of a pdf/txt/csv attachment on an "
                       "email (message id from email_history_search or "
                       "read_email). Use whenever a document's contents matter "
                       "— never answer about a PDF from the snippet.",
        "input_schema": {"type": "object", "properties": {
            "account": {"type": "string", "enum": ["personal", "baci", "eien"]},
            "message_id": {"type": "string"},
            "filename": {"type": "string",
                         "description": "Which attachment (substring match); "
                                        "omit if there's only one"},
        }, "required": ["account", "message_id"]},
    },
]

TOOLS += [
    {"name": "find_contacts",
     "description": "Find email addresses for a person or company from "
                    "correspondence history. Use to suggest calendar invitees "
                    "or to know who to email about something. account: "
                    "personal|baci|eien.",
     "input_schema": {"type": "object", "properties": {
         "account": {"type": "string", "enum": ["personal", "baci", "eien"]},
         "who": {"type": "string"}}, "required": ["account", "who"]}},
    {"name": "find_documents",
     "description": "Search the document registry — every file the agent has "
                    "filed, indexed by counterparty, PO/shipment anchor, doc "
                    "type, filename. USE THIS FIRST when an email or request "
                    "references a document ('send the BOL for the Primorous "
                    "order'); returns paths + Drive links. Fall back to "
                    "drive_search only if the registry has no match.",
     "input_schema": {"type": "object", "properties": {
         "query": {"type": "string"}}, "required": ["query"]}},
    {"name": "onboarding_packet",
     "description": "The standing forwarder-onboarding documents (Power of "
                    "Attorney, FDA docs, sample commercial invoice/packing "
                    "list) with Drive links. USE THIS whenever a freight "
                    "forwarder or customs broker requests company documents — "
                    "include the links in the reply. Anything MISSING or "
                    "needing signature -> escalate.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "rfq_get",
     "description": "Status of an RFQ round: details, who was asked, quotes in.",
     "input_schema": {"type": "object", "properties": {
         "shipment_name": {"type": "string"}}, "required": ["shipment_name"]}},
    {"name": "rfq_record_quote",
     "description": "Record a freight quote received from a forwarder (use "
                    "when an email contains pricing for an open RFQ). Total "
                    "should be the all-in figure; note exclusions in notes.",
     "input_schema": {"type": "object", "properties": {
         "shipment_name": {"type": "string"}, "forwarder_email": {"type": "string"},
         "total": {"type": "string"}, "breakdown": {"type": "string"},
         "notes": {"type": "string"}},
         "required": ["shipment_name", "forwarder_email", "total"]}},
]

_HANDLERS = {
    "shopify_find_orders": shopify_find_orders,
    "shopify_order_details": shopify_order_details,
    "drive_search": drive_search,
    "email_history_search": email_history_search,
    "read_email": read_email,
    "read_email_attachment": read_email_attachment,
    "find_contacts": find_contacts,
    "find_documents": find_documents,
    "onboarding_packet": onboarding_packet,
    "rfq_get": rfq_get,
    "rfq_record_quote": rfq_record_quote,
}


def dispatch(name: str, args: dict) -> str:
    try:
        return _HANDLERS[name](**args)[:8000]
    except Exception as exc:  # noqa: BLE001
        return f"Tool error ({exc.__class__.__name__}): {exc}"
