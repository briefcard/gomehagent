"""Web service: health check, approval links, WhatsApp webhook."""
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse

from . import approvals, config, db

app = FastAPI(title="Saias Operations Assistant")


@app.on_event("startup")
def startup() -> None:
    db.init_db()


@app.get("/health")
def health() -> dict:
    return {"ok": True, "whatsapp": config.WHATSAPP_ENABLED,
            "inboxes": list(config.GMAIL_ACCOUNTS)}


@app.get("/health/connections")
def health_connections() -> dict:
    """Live-test every data connection. Open in a browser to verify setup."""
    from . import data_tools, gmail_client  # lazy: avoid slowing basic health

    report: dict = {"shopify": {}, "google": {}}
    for store in config.SHOPIFY_STORES:
        try:
            shop = data_tools._shopify(store, "shop.json")["shop"]
            report["shopify"][store] = f"ok — {shop['name']}"
        except Exception as exc:  # noqa: BLE001
            report["shopify"][store] = f"ERROR: {exc.__class__.__name__}: {str(exc)[:200]}"
    if not config.SHOPIFY_STORES:
        report["shopify"] = "SHOPIFY_STORES_JSON not set"
    for alias in config.GMAIL_ACCOUNTS:
        try:
            gmail_client.service_for(alias).users().getProfile(userId="me").execute()
            gmail_ok = "gmail ok"
        except Exception as exc:  # noqa: BLE001
            gmail_ok = f"gmail ERROR: {exc.__class__.__name__}"
        drive_res = data_tools.drive_search(alias, "test")
        drive_ok = ("drive ok" if not drive_res.startswith("Drive not accessible")
                    else "drive NOT AUTHORIZED (re-run google_oauth.py with new scopes)")
        report["google"][alias] = f"{gmail_ok} · {drive_ok}"
    return report


@app.get("/decide/{token}", response_class=HTMLResponse)
def decide(token: str) -> str:
    """Approve/deny links from approval emails."""
    outcome = approvals.decide(token)
    return f"<html><body style='font-family:sans-serif;padding:3em'><h2>{outcome}</h2></body></html>"


# ---- WhatsApp Cloud API webhook (active once Meta app is configured) ----

@app.get("/webhooks/whatsapp")
def whatsapp_verify(request: Request):
    """Meta webhook verification handshake."""
    params = request.query_params
    if (params.get("hub.mode") == "subscribe"
            and params.get("hub.verify_token") == config.WHATSAPP_VERIFY_TOKEN):
        return PlainTextResponse(params.get("hub.challenge", ""))
    return PlainTextResponse("forbidden", status_code=403)


@app.post("/webhooks/whatsapp")
async def whatsapp_incoming(request: Request) -> dict:
    """Handle button replies (approve:<id> / deny:<id>) and free-text messages."""
    body = await request.json()
    try:
        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                for msg in change.get("value", {}).get("messages", []):
                    if msg.get("type") == "interactive":
                        reply_id = msg["interactive"]["button_reply"]["id"]
                        action, ap_id = reply_id.split(":", 1)
                        decision = "approved" if action == "approve" else "denied"
                        approvals.apply_decision(ap_id, decision)
                    # Free-text commands ("status", "where do we stand") arrive
                    # here too — routed to the agent loop in Phase 2.
    except Exception:  # noqa: BLE001 — always 200 so Meta doesn't retry-storm
        pass
    return {"status": "received"}
