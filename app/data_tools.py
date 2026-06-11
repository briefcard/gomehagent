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

def _shopify(store: str, path: str, params: dict | None = None) -> dict:
    cfg = config.SHOPIFY_STORES[store]
    r = httpx.get(
        f"https://{cfg['domain']}/admin/api/{API_VERSION}/{path}",
        headers={"X-Shopify-Access-Token": cfg["token"]},
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


# ---------- Dispatch ----------

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

_HANDLERS = {
    "shopify_find_orders": shopify_find_orders,
    "shopify_order_details": shopify_order_details,
    "drive_search": drive_search,
    "email_history_search": email_history_search,
}


def dispatch(name: str, args: dict) -> str:
    try:
        return _HANDLERS[name](**args)[:8000]
    except Exception as exc:  # noqa: BLE001
        return f"Tool error ({exc.__class__.__name__}): {exc}"
