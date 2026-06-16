"""Web service: health check, approval links, WhatsApp webhook."""
import json

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
    from . import ops_jobs

    if key != config.APPROVAL_SECRET:
        return {"error": "bad key"}
    return {"results": _job_status, "live_progress": ops_jobs.STATUS} \
        if (_job_status or ops_jobs.STATUS) else {"status": "no jobs run yet"}


@app.get("/admin/test_whatsapp")
def test_whatsapp(key: str = "") -> dict:
    """Send a test WhatsApp message and surface Meta's raw response."""
    import httpx

    from . import whatsapp as wa

    if key != config.APPROVAL_SECRET:
        return {"error": "bad key"}
    if not config.WHATSAPP_ENABLED:
        return {"error": "whatsapp env vars incomplete"}
    r = httpx.post(
        f"{wa.API}/{config.WHATSAPP_PHONE_ID}/messages",
        headers={"Authorization": f"Bearer {config.WHATSAPP_TOKEN}"},
        json={"messaging_product": "whatsapp",
              "to": config.WHATSAPP_APPROVER_NUMBER,
              "type": "text", "text": {"body": "Test ping from your assistant ✅"}},
        timeout=30,
    )
    try:
        body = r.json()
    except Exception:  # noqa: BLE001
        body = {"raw": r.text[:500]}
    return {"status_code": r.status_code, "to": config.WHATSAPP_APPROVER_NUMBER,
            "phone_id": config.WHATSAPP_PHONE_ID, "meta_response": body}


@app.get("/admin/stats")
def stats(key: str = "") -> dict:
    """Approve/deny rates per bucket (last 30 days) — flip AUTO_SEND for a
    bucket once its approval_rate holds ~95%."""
    if key != config.APPROVAL_SECRET:
        return {"error": "bad key"}
    return approvals.autonomy_stats()


@app.get("/admin/usage")
def usage_report(key: str = "", days: int = 7) -> dict:
    """Cost + cache-hit audit. Open in a browser:
    /admin/usage?key=SECRET&days=7"""
    from . import usage
    if key != config.APPROVAL_SECRET:
        return {"error": "bad key"}
    return usage.report(days)


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


# ---------------------------------------------------------------------------
# Ordered command queue: ONE consumer thread processes Gomeh's messages
# sequentially. Thread-per-message caused concurrent Google API access
# (segfault / exit 139) and memory spikes under bursts.
# ---------------------------------------------------------------------------
import queue
from collections import deque

_commands: "queue.Queue[tuple[str, str]]" = queue.Queue()
_consumer_started = False
_seen_wamids: deque = deque(maxlen=500)


def _consume() -> None:
    from . import command_agent, whatsapp

    while True:
        kind, payload = _commands.get()
        try:
            if kind == "feedback":
                from . import db, voice_learn
                fb = json.loads(payload)
                if fb["text"].strip().lower() in ("skip", "no", "nvm", "nm"):
                    whatsapp.send_text("Okay, nothing learned from that one.")
                    continue
                with db.SessionLocal() as s:
                    ap = s.get(db.Approval, fb["approval_id"])
                    account = (ap.payload or {}).get("account", "baci") if ap else "baci"
                    orig = (ap.payload or {}).get("body", "") if ap else ""
                if fb["mode"] == "deny":
                    voice_learn.add_rule(account, fb["text"])
                    whatsapp.send_text(f"Learned for [{account}]: \"{fb['text']}\" "
                                       "— future drafts there will follow it.")
                else:  # edit -> requeue a revised draft
                    whatsapp.send_text(command_agent.handle(
                        f"Revise this draft per my instruction and queue it for "
                        f"approval (account {account}).\n\nDRAFT:\n{orig}\n\n"
                        f"MY EDIT:\n{fb['text']}"))
            elif kind == "file":
                meta = json.loads(payload)
                data, real_mime = whatsapp.download_media(meta["media_id"])
                text = (meta["caption"] or
                        f"[I'm sending you a file: {meta['filename']}] — "
                        "handle it appropriately given our conversation.")
                reply = command_agent.handle(
                    text,
                    attachments=[{"filename": meta["filename"], "data": data,
                                  "mime": meta["mime"] or real_mime}],
                )
                whatsapp.send_text(reply)
            elif kind == "voice":
                audio, mime = whatsapp.download_media(payload)
                transcript = whatsapp.transcribe(audio, mime)
                if not transcript:
                    whatsapp.send_text("I couldn't make out that voice note — try again?")
                    continue
                whatsapp.send_text(f"🎙 Heard: \"{transcript[:300]}\"")
                whatsapp.send_text(command_agent.handle(transcript))
            else:
                whatsapp.send_text(command_agent.handle(payload))
        except RuntimeError:
            whatsapp.send_text("Voice notes need a transcription key — add "
                               "OPENAI_API_KEY in Render and I'll handle audio.")
        except Exception as exc:  # noqa: BLE001
            from . import whatsapp as wa
            wa.send_text(f"Something broke handling that: {exc.__class__.__name__}")
        finally:
            _commands.task_done()


def _enqueue(kind: str, payload: str) -> None:
    global _consumer_started
    if not _consumer_started:
        threading.Thread(target=_consume, daemon=True).start()
        _consumer_started = True
    _commands.put((kind, payload))


# When Gomeh taps Deny or Edit, we await his next text as feedback/edit and
# tie it to that approval — this is how button taps become learning.
_pending_feedback: dict = {"mode": None, "approval_id": None}


def _handle_button(action: str, ap_id: str) -> None:
    from . import approvals, whatsapp
    if action == "approve":
        whatsapp.send_text(approvals.apply_decision(ap_id, "approved"))
    elif action == "deny":
        approvals.apply_decision(ap_id, "denied")
        _pending_feedback.update(mode="deny", approval_id=ap_id)
        whatsapp.send_text("Denied. Tell me what was wrong (one line) and I'll "
                           "make it a permanent rule for that inbox — or reply "
                           "'skip'.")
    elif action == "edit":
        _pending_feedback.update(mode="edit", approval_id=ap_id)
        whatsapp.send_text("Send me your edited version (or the change you "
                           "want) and I'll queue the revised draft.")


def _handle_voice(media_id: str) -> None:
    _enqueue("voice", media_id)


def _handle_command(text: str) -> None:
    # Intercept deny-reason / edit replies tied to a recent button tap.
    if _pending_feedback["mode"]:
        _enqueue("feedback", json.dumps(
            {**_pending_feedback, "text": text}))
        _pending_feedback.update(mode=None, approval_id=None)
        return
    _enqueue("text", text)


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
                    # Meta redelivers on webhook hiccups — process each once.
                    wamid = msg.get("id", "")
                    if wamid in _seen_wamids:
                        continue
                    _seen_wamids.append(wamid)
                    if msg.get("type") == "interactive":
                        reply_id = msg["interactive"]["button_reply"]["id"]
                        action, ap_id = reply_id.split(":", 1)
                        _handle_button(action, ap_id)
                    elif msg.get("type") == "text":
                        _handle_command(msg["text"]["body"])
                    elif msg.get("type") == "audio":
                        _handle_voice(msg["audio"]["id"])
                    elif msg.get("type") in ("document", "image"):
                        m = msg[msg["type"]]
                        _enqueue("file", json.dumps({
                            "media_id": m["id"],
                            "filename": m.get("filename")
                                        or f"whatsapp-{msg['type']}-{m['id'][:8]}.jpg",
                            "mime": m.get("mime_type", ""),
                            "caption": m.get("caption", ""),
                        }))
    except Exception:  # noqa: BLE001 — always 200 so Meta doesn't retry-storm
        pass
    return {"status": "received"}
