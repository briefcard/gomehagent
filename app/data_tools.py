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


# ---------- Email history ----------

def email_history_search(account: str, query: str) -> str:
    if account not in config.GMAIL_ACCOUNTS:
        return f"Account '{account}' unknown."
    try:
        svc = gmail_client.service_for(account)
        resp = svc.users().messages().list(userId="me", q=query, maxResults=8).execute()
        out = []
        for ref in resp.get("messages", []):
            msg = svc.users().messages().get(
                userId="me", id=ref["id"], format="metadata",
                metadataHeaders=["From", "To", "Subject", "Date"],
            ).execute()
            headers = {h["name"].lower(): h["value"]
                       for h in msg["payload"].get("headers", [])}
            out.append({"from": headers.get("from"), "to": headers.get("to"),
                        "subject": headers.get("subject"), "date": headers.get("date"),
                        "snippet": msg.get("snippet", "")})
        return json.dumps(out) if out else "No matching emails."
    except Exception as exc:  # noqa: BLE001
        return f"Email search failed: {exc.__class__.__name__}"


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
        "description": "Search past emails in an inbox using Gmail query syntax "
                       "(e.g. 'from:hana@cargohansa.com', 'subject:quote newer_than:90d'). "
                       "Use to find prior conversations, agreements, quotes.",
        "input_schema": {"type": "object", "properties": {
            "account": {"type": "string", "enum": ["personal", "baci", "eien"]},
            "query": {"type": "string"},
        }, "required": ["account", "query"]},
    },
]

TOOLS += [
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
    "onboarding_packet": onboarding_packet,
    "rfq_get": rfq_get,
    "rfq_record_quote": rfq_record_quote,
}


def dispatch(name: str, args: dict) -> str:
    try:
        return _HANDLERS[name](**args)[:8000]
    except Exception as exc:  # noqa: BLE001
        return f"Tool error ({exc.__class__.__name__}): {exc}"
