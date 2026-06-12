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


# ---- On-demand jobs ----

import threading

_job_status: dict = {}


@app.get("/admin/run/{job}")
def run_job(job: str, key: str = "") -> dict:
    """Trigger a job: /admin/run/doc_sweep?key=<APPROVAL_SECRET>.
    Jobs: recategorize | doc_sweep | shipment_audit. Runs in background;
    check /admin/status?key=... for results. Reports are emailed to Gomeh."""
    from . import ops_jobs

    if key != config.APPROVAL_SECRET:
        return {"error": "bad key"}
    if job not in ops_jobs.JOBS:
        return {"error": f"unknown job; available: {list(ops_jobs.JOBS)}"}
    if _job_status.get(job) == "running":
        return {"status": "already running"}

    def _run() -> None:
        _job_status[job] = "running"
        try:
            _job_status[job] = ops_jobs.JOBS[job]()
        except Exception as exc:  # noqa: BLE001
            _job_status[job] = f"FAILED: {exc.__class__.__name__}: {str(exc)[:300]}"

    threading.Thread(target=_run, daemon=True).start()
    return {"status": f"{job} started — report will be emailed"}


@app.get("/admin/status")
def job_status(key: str = "") -> dict:
    if key != config.APPROVAL_SECRET:
        return {"error": "bad key"}
    return _job_status or {"status": "no jobs run yet"}


@app.get("/admin/ask", response_class=PlainTextResponse)
def ask(key: str = "", q: str = "") -> str:
    """The conversational agent over HTTP, until WhatsApp is live:
    /admin/ask?key=SECRET&q=pending subscriptions that need cancelling"""
    from . import command_agent

    if key != config.APPROVAL_SECRET:
        return "bad key"
    if not q:
        return "add &q=your question"
    try:
        return command_agent.handle(q)
    except Exception as exc:  # noqa: BLE001
        return f"error: {exc.__class__.__name__}: {str(exc)[:300]}"


def _handle_command(text: str) -> None:
    """Free-text WhatsApp messages from Gomeh -> conversational agent with
    the full toolset (email, Drive, Shopify, Calendar, jobs, deadlines)."""
    from . import command_agent, whatsapp

    def _run() -> None:
        try:
            whatsapp.send_text(command_agent.handle(text))
        except Exception as exc:  # noqa: BLE001
            whatsapp.send_text(f"Something broke handling that: {exc.__class__.__name__}")

    threading.Thread(target=_run, daemon=True).start()


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
                    # Only Gomeh may approve or command — ignore all others.
                    if config._norm_phone(msg.get("from", "")) != config.WHATSAPP_APPROVER_NUMBER:
                        continue
                    if msg.get("type") == "interactive":
                        reply_id = msg["interactive"]["button_reply"]["id"]
                        action, ap_id = reply_id.split(":", 1)
                        decision = "approved" if action == "approve" else "denied"
                        approvals.apply_decision(ap_id, decision)
                    elif msg.get("type") == "text":
                        _handle_command(msg["text"]["body"])
    except Exception:  # noqa: BLE001 — always 200 so Meta doesn't retry-storm
        pass
    return {"status": "received"}
