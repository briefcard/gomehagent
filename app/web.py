"""Web service: health check, approval links, WhatsApp webhook."""
import hashlib
import hmac
import html
import json
import logging
import secrets

from fastapi import Depends, FastAPI, Request, Response
from fastapi.responses import HTMLResponse, PlainTextResponse

from . import approvals, config, db

log = logging.getLogger("web")
app = FastAPI(title="Saias Operations Assistant")


@app.on_event("startup")
def startup() -> None:
    db.init_db()


# ---------------------------------------------------------------------------
# Console session.
#
# Every admin route used to require `?key=<APPROVAL_SECRET>` on every request,
# so the credential rode in browser history, Referer headers and every access
# log — and each of the ten console forms re-embedded it to keep navigation
# working. The key is now accepted once, from the query string or an
# `X-Admin-Key` header, and exchanged for a session cookie.
#
# This is a session, not an auth layer: still one shared credential, still no
# per-user identity. It removes the leak surface, not the need for real auth
# before any client gets a login.
# ---------------------------------------------------------------------------

ADMIN_COOKIE = "console"
_COOKIE_MAX_AGE = 60 * 60 * 24 * 14        # 14 days
_GATED_PREFIXES = ("/admin", "/health/seo")


def _console_token() -> str:
    """What the cookie carries — derived from the secret, never the secret.

    APPROVAL_SECRET also signs approval decision links (`approvals.py`), so a
    cookie holding it verbatim would turn a stolen console session into the
    ability to forge approvals. This grants console access and nothing else,
    and is stable across restarts so sessions survive a deploy.
    """
    return hmac.new((config.APPROVAL_SECRET or "").encode(),
                    b"admin-console-v1", hashlib.sha256).hexdigest()


def _matches(supplied: str, expected: str) -> bool:
    """Constant-time compare. The old `key != SECRET` short-circuited on the
    first wrong byte, which is a timing oracle on a credential reachable from
    the open internet."""
    if not (supplied and expected):
        return False
    return secrets.compare_digest(supplied, expected)


def admin_key(request: Request, key: str = "") -> str:
    """Resolve the console credential from query, header, or session cookie.

    Returns the secret when authenticated, so every existing
    `if key != config.APPROVAL_SECRET` check downstream is unchanged, and ""
    when not — which those same checks already reject.
    """
    secret = config.APPROVAL_SECRET or ""
    if (_matches(key, secret)
            or _matches(request.headers.get("x-admin-key", ""), secret)
            or _matches(request.cookies.get(ADMIN_COOKIE, ""), _console_token())):
        return secret
    return ""


@app.exception_handler(Exception)
async def _console_error(request: Request, exc: Exception):
    """Show the operator what broke, instead of a bare Internal Server Error.

    A 500 on the console is a dead end: the traceback is in the Render log, the
    person who hit it is in a browser, and the two are only connected by
    guesswork about what was clicked. This prints the exception and a reference
    that matches the log line, and — for the console — a link back.

    Non-console paths (the Telegram and WhatsApp webhooks) keep the plain 500,
    because the caller there is a machine that retries.
    """
    ref = secrets.token_hex(4)
    log.exception("unhandled error [%s] on %s %s", ref, request.method,
                  request.url.path)
    if not request.url.path.startswith("/admin"):
        return PlainTextResponse("internal error", status_code=500)
    import html as _h
    return HTMLResponse(
        f"<h3>That action failed</h3>"
        f"<p><b>{_h.escape(exc.__class__.__name__)}</b>: "
        f"{_h.escape(str(exc)[:400])}</p>"
        f"<p>Reference <code>{ref}</code> — the full traceback is in the "
        f"service log under that reference.</p>"
        f"<p><a href='/admin/ui'>Back to the console</a></p>", status_code=500)


@app.middleware("http")
async def _console_session(request: Request, call_next):
    """Establish the cookie whenever a request arrives carrying a valid secret.

    Done in middleware rather than the dependency because several routes return
    a Response directly (the redirects after a form post), and FastAPI does not
    merge a dependency's response headers into those.
    """
    response = await call_next(request)
    if not request.url.path.startswith(_GATED_PREFIXES):
        return response
    supplied = (request.query_params.get("key", "")
                or request.headers.get("x-admin-key", ""))
    if _matches(supplied, config.APPROVAL_SECRET or "") and not _matches(
            request.cookies.get(ADMIN_COOKIE, ""), _console_token()):
        response.set_cookie(
            ADMIN_COOKIE, _console_token(), max_age=_COOKIE_MAX_AGE,
            httponly=True, samesite="lax",
            secure=request.url.scheme == "https")
    return response


@app.get("/admin/logout")
def admin_logout() -> dict:
    """Drop the console session on this browser."""
    r = Response(content='{"ok":true,"note":"console session cleared"}',
                 media_type="application/json")
    r.delete_cookie(ADMIN_COOKIE)
    return r


def _active_tenant(chat_id: str) -> str:
    """Which account this sender is working on, for the agent's context.

    `ops_commands` has always resolved this to scope its own answers; the agent
    beside it never received it, so `/use baci` changed what `/kb` reported and
    changed nothing about what the agent thought it was looking at.
    """
    from . import tenants as _tn
    try:
        return _tn.active(_tn.user_for_chat(chat_id)) if chat_id else ""
    except Exception:  # noqa: BLE001 — context is an enhancement, never a blocker
        return ""


@app.get("/health")
def health() -> dict:
    from . import channel
    return {"ok": True, "whatsapp": config.WHATSAPP_ENABLED,
            "telegram": config.TELEGRAM_ENABLED,
            "ops_channel": channel.active(),
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
            # Cached Gmail service is shared process-wide — go through the lock so
            # this health probe can't race a concurrent locked gmail call (exit 139).
            with gmail_client._google_lock:
                gmail_client.service_for(alias).users().getProfile(userId="me").execute()
            gmail_ok = "gmail ok"
        except Exception as exc:  # noqa: BLE001
            gmail_ok = f"gmail ERROR: {exc.__class__.__name__}"
        drive_res = data_tools.drive_search(alias, "test")
        drive_ok = ("drive ok" if not drive_res.startswith("Drive not accessible")
                    else "drive NOT AUTHORIZED (re-run google_oauth.py with new scopes)")
        report["google"][alias] = f"{gmail_ok} · {drive_ok}"
    return report


@app.get("/health/seo")
def health_seo(key: str = Depends(admin_key)) -> dict:
    """Exactly what the DEPLOYED service sees for the SEO agent (no secrets) —
    so setup can be verified without guessing. /health/seo?key=APPROVAL_SECRET"""
    if key != config.APPROVAL_SECRET:
        return {"error": "bad key"}
    from . import sites
    from .roles import ROLES

    with db.SessionLocal() as s:
        row = s.get(db.Setting, "wa_active")
    active = row.value if row else "(unset -> admin)"
    out = {
        "roles_registered": list(ROLES),        # must include 'seo'
        "whatsapp_active_agent": active,         # which agent the number is on
        "seo_model": config.SEO_MODEL,
        "google_alias": config.SEO_GOOGLE_ALIAS,
        "semrush_key_set": bool(config.SEMRUSH_API_KEY),
        "shopify_stores": list(config.SHOPIFY_STORES),
        "wordpress_sites": list(config.WORDPRESS_SITES),
        "sites": [{"key": p["key"], "domain": p["domain"], "platform": p["platform"],
                   "creds_key": p["creds_key"], "has_guardrail": bool(p.get("guardrail"))}
                  for p in sites.all_profiles().values()],
    }
    if config.SEMRUSH_API_KEY:
        try:
            from . import seo_tools
            primary = sites.get("")
            r = seo_tools.semrush_domain_overview(primary["domain"], primary["database"])
            out["semrush_probe"] = "ok" if r.startswith("{") and r != "{}" else r[:180]
        except Exception as exc:  # noqa: BLE001
            out["semrush_probe"] = f"ERROR: {exc.__class__.__name__}: {str(exc)[:160]}"
    return out


@app.get("/decide/{token}", response_class=HTMLResponse)
def decide(token: str) -> str:
    """Approve/deny links from approval emails."""
    outcome = approvals.decide(token)
    return f"<html><body style='font-family:sans-serif;padding:3em'><h2>{outcome}</h2></body></html>"


# ---- On-demand jobs ----

import threading

_job_status: dict = {}


@app.get("/admin/run/{job}")
def run_job(job: str, key: str = Depends(admin_key)) -> dict:
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
def job_status(key: str = Depends(admin_key)) -> dict:
    from . import ops_jobs

    if key != config.APPROVAL_SECRET:
        return {"error": "bad key"}
    return {"results": _job_status, "live_progress": ops_jobs.STATUS} \
        if (_job_status or ops_jobs.STATUS) else {"status": "no jobs run yet"}


@app.get("/admin/test_whatsapp")
def test_whatsapp(key: str = Depends(admin_key)) -> dict:
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
def stats(key: str = Depends(admin_key)) -> dict:
    """Approve/deny rates per bucket (last 30 days) — flip AUTO_SEND for a
    bucket once its approval_rate holds ~95%."""
    if key != config.APPROVAL_SECRET:
        return {"error": "bad key"}
    return approvals.autonomy_stats()


@app.get("/admin/usage")
def usage_report(key: str = Depends(admin_key), days: int = 7) -> dict:
    """Cost + cache-hit audit. Open in a browser:
    /admin/usage?key=SECRET&days=7"""
    from . import usage
    if key != config.APPROVAL_SECRET:
        return {"error": "bad key"}
    return usage.report(days)


@app.get("/admin/whatsapp_diag")
def whatsapp_diag(key: str = Depends(admin_key)) -> dict:
    """Delivery truth for WhatsApp: recent Meta status callbacks (delivered /
    read / FAILED + error codes) and the sending number's live standing.
    Empty statuses right after a test send = Meta's webhook callback URL is
    not pointing at this service."""
    if key != config.APPROVAL_SECRET:
        return {"error": "bad key"}
    import httpx

    from . import whatsapp as wa
    out: dict = {"recent_statuses": list(_wa_statuses)[-30:]}
    try:
        r = httpx.get(
            f"{wa.API}/{config.WHATSAPP_PHONE_ID}",
            params={"fields": "verified_name,display_phone_number,"
                              "quality_rating,code_verification_status"},
            headers={"Authorization": f"Bearer {config.WHATSAPP_TOKEN}"},
            timeout=30)
        out["phone_number"] = r.json()
    except Exception as exc:  # noqa: BLE001
        out["phone_number"] = f"ERROR: {exc.__class__.__name__}: {str(exc)[:150]}"
    return out


@app.get("/admin/pending", response_class=HTMLResponse)
def pending_page(key: str = Depends(admin_key)) -> str:
    """Browser fallback for the whole approval queue: every pending approval
    with working Approve/Deny links (relative URLs, so they work no matter
    what PUBLIC_BASE_URL says)."""
    if key != config.APPROVAL_SECRET:
        return "<h3>bad key</h3>"
    from . import approvals as ap_mod
    with db.SessionLocal() as s:
        aps = (s.query(db.Approval).filter(db.Approval.status == "pending")
               .order_by(db.Approval.created_at.desc()).all())
        rows = []
        for ap in aps:
            approve = "/decide/" + ap_mod._signer.dumps([ap.id, "approved"])
            deny = "/decide/" + ap_mod._signer.dumps([ap.id, "denied"])
            body = (ap.payload or {}).get("body") or (ap.payload or {}).get("content", "")
            rows.append(
                f"<li style='margin:0 0 14px'><b>{ap.created_at:%b %d}</b> — "
                f"{ap.summary}"
                + (f"<details><summary>details</summary><pre style='white-space:"
                   f"pre-wrap;background:#f6f6f6;padding:8px'>{body[:1500]}</pre>"
                   f"</details>" if body else "")
                + f" &nbsp;<a href='{approve}'>✅ Approve</a> · "
                  f"<a href='{deny}'>❌ Deny</a></li>")
    return ("<html><body style='font-family:sans-serif;max-width:760px;"
            "margin:2em auto'><h2>Pending approvals ("
            f"{len(rows)})</h2><ul style='list-style:none;padding:0'>"
            + "".join(rows) + "</ul></body></html>")


@app.get("/admin/renotify")
def renotify(key: str = Depends(admin_key)) -> dict:
    """Re-send notifications for ALL pending approvals (e.g. after a WhatsApp
    outage swallowed the cards): clears the notified/attempt flags and runs a
    notify cycle right now."""
    if key != config.APPROVAL_SECRET:
        return {"error": "bad key"}
    with db.SessionLocal() as s:
        aps = s.query(db.Approval).filter(db.Approval.status == "pending").all()
        reset = 0
        for ap in aps:
            if "_notified" in ap.payload or "_notify_attempts" in ap.payload:
                ap.payload = {k: v for k, v in ap.payload.items()
                              if k not in ("_notified", "_notify_attempts")}
                reset += 1
        s.commit()
        pending = len(aps)
    sent = approvals.notify_pending("Pending approvals (re-sent)")
    return {"pending": pending, "flags_reset": reset, "resent": sent}


@app.get("/admin/features")
def feature_requests(key: str = Depends(admin_key), status: str = "open") -> dict:
    """The agents' own upgrade queue — limitations they hit, with proposals.
    Feed the top ones to a dev session to implement. status=open|planned|built|
    rejected|all."""
    from . import systems_map
    if key != config.APPROVAL_SECRET:
        return {"error": "bad key"}
    return {"status": status, "requests": systems_map.features_list(status)}


@app.get("/admin/ask", response_class=PlainTextResponse)
def ask(key: str = Depends(admin_key), q: str = "", role: str = "admin", thread: str = "") -> str:
    """The conversational agents over HTTP, until each has its own WhatsApp
    number. Pick the agent with &role=admin|seo. Each agent has its OWN
    conversation thread (no context bleed); add &thread=<name> to run independent
    parallel conversations (e.g. one per client):
    /admin/ask?key=SECRET&role=seo&q=where are our quick-win keywords?
    /admin/ask?key=SECRET&role=seo&thread=eien&q=baseline for Eien"""
    if key != config.APPROVAL_SECRET:
        return "bad key"
    if not q:
        return "add &q=your question"
    try:
        from . import kernel
        from .roles import get as get_role

        thread_key = f"{role}:{thread}" if thread else role
        return kernel.run(get_role(role), q, thread=thread_key)
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
# Meta delivery receipts (sent/delivered/read/failed + error codes). Failures
# like the 131056 pair-rate storm are ONLY visible here — never at send time.
_wa_statuses: deque = deque(maxlen=100)


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
                    # If the lesson is generalizable, also share it with ALL
                    # agents (cross-agent learning), not just this inbox.
                    from . import memory
                    low = fb["text"].lower()
                    generalizable = any(k in low for k in (
                        "always", "never", "don't ", "do not", "make sure",
                        "verify", "confirm", "every"))
                    if generalizable:
                        memory.add_lesson(fb["text"], scope="global", origin="admin")
                    whatsapp.send_text(
                        f"Learned for [{account}]: \"{fb['text']}\""
                        + (" — and shared as a lesson for all agents."
                           if generalizable else
                           " — future drafts there will follow it."))
                else:  # edit -> requeue a revised draft (always the admin agent)
                    whatsapp.send_text(command_agent.handle(
                        f"Revise this draft per my instruction and queue it for "
                        f"approval (account {account}).\n\nDRAFT:\n{orig}\n\n"
                        f"MY EDIT:\n{fb['text']}", force_role="admin"))
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
            elif kind == "tg_voice":
                # Same shape as "voice", but Telegram's two-hop getFile flow.
                # Transcription runs here rather than in the webhook so the
                # handler can 200 immediately and avoid Telegram's retries.
                from . import channel, ops_commands, telegram
                try:
                    meta = json.loads(payload)
                except ValueError:
                    meta = {"file_id": payload, "chat_id": ""}
                audio, mime = telegram.download_media(meta["file_id"])
                transcript = telegram.transcribe(audio, mime)
                if not transcript:
                    channel.send_text("I couldn't make out that voice note — try again?")
                    continue
                channel.send_text(f"🎙 Heard: \"{transcript[:300]}\"")
                # Spoken ops commands must take the same fast path as typed
                # ones — otherwise "add claim: ..." dictated from the car goes
                # to the general agent and quietly does nothing.
                spoken = ops_commands.handle(transcript, meta.get("chat_id", ""))
                channel.send_text(spoken if spoken is not None
                                  else command_agent.handle(
                                      transcript, tenant=_active_tenant(meta.get("chat_id", ""))))
            else:  # text command — may carry a quoted message
                from . import channel
                text = payload
                if payload.startswith("{") and '"_quoted"' in payload:
                    q = json.loads(payload)
                    text = (f"[Replying to your earlier message, which said:\n"
                            f"\"{q['_quoted']}\"]\n\nMy reply: {q['text']}")
                channel.send_text(command_agent.handle(
                    text, tenant=_active_tenant(meta.get("chat_id", ""))))
        except RuntimeError:
            whatsapp.send_text("Voice notes need a transcription key — add "
                               "OPENAI_API_KEY in Render and I'll handle audio.")
        except Exception as exc:  # noqa: BLE001
            log.exception("command handler error")  # full traceback -> Render logs
            from . import whatsapp as wa
            wa.send_text(f"Something broke handling that: {exc.__class__.__name__}: "
                         f"{str(exc)[:400]}")
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
    # channel.* routes to Telegram when configured, WhatsApp otherwise — so a
    # tap made in Telegram is answered in Telegram, not on the other surface.
    from . import approvals, channel
    if action == "approve":
        channel.send_text(approvals.apply_decision(ap_id, "approved"))
    elif action == "deny":
        approvals.apply_decision(ap_id, "denied")
        _pending_feedback.update(mode="deny", approval_id=ap_id)
        channel.send_text("Denied. Tell me what was wrong (one line) and I'll "
                          "make it a permanent rule for that inbox — or reply "
                          "'skip'.")
    elif action == "edit":
        _pending_feedback.update(mode="edit", approval_id=ap_id)
        channel.send_text("Send me your edited version (or the change you "
                          "want) and I'll queue the revised draft.")


def _handle_voice(media_id: str) -> None:
    _enqueue("voice", media_id)


def _handle_command(text: str, quoted_id: str = "", chat_id: str = "") -> None:
    # Ops commands (switch tenant, list accounts, capture a claim) are instant
    # DB reads — answer them here rather than letting a model decide whether
    # "switch to baci" was a switch. Falls through when it isn't one.
    if chat_id:
        from . import channel, ops_commands
        reply = ops_commands.handle(text, chat_id)
        if reply is not None:
            channel.send_text(reply)
            return
    # Intercept deny-reason / edit replies tied to a recent button tap.
    if _pending_feedback["mode"]:
        _enqueue("feedback", json.dumps(
            {**_pending_feedback, "text": text}))
        _pending_feedback.update(mode=None, approval_id=None)
        return
    # If Gomeh replied to a specific agent message, resolve what he quoted.
    if quoted_id:
        from . import db
        with db.SessionLocal() as s:
            q = s.get(db.WaMessage, quoted_id)
        if q and q.approval_id:
            # Reply to an approval card = an edit instruction for that draft.
            _enqueue("feedback", json.dumps(
                {"mode": "edit", "approval_id": q.approval_id, "text": text}))
            return
        if q:
            _enqueue("text", json.dumps(
                {"_quoted": q.content[:2000], "text": text}))
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
                for st in change.get("value", {}).get("statuses", []):
                    _wa_statuses.append({
                        "at": st.get("timestamp"), "status": st.get("status"),
                        "wamid_tail": st.get("id", "")[-14:],
                        "errors": [{"code": e.get("code"),
                                    "detail": e.get("title", "")[:120]}
                                   for e in st.get("errors", [])],
                    })
                for msg in change.get("value", {}).get("messages", []):
                    # Only Gomeh may approve or command — ignore all others.
                    if config._norm_phone(msg.get("from", "")) != config.WHATSAPP_APPROVER_NUMBER:
                        continue
                    # Meta redelivers on webhook hiccups — process each once.
                    wamid = msg.get("id", "")
                    if wamid in _seen_wamids:
                        continue
                    _seen_wamids.append(wamid)
                    # If Gomeh used WhatsApp's reply feature, capture which
                    # message he quoted so the agent has exact context.
                    quoted_id = (msg.get("context") or {}).get("id", "")
                    if msg.get("type") == "interactive":
                        reply_id = msg["interactive"]["button_reply"]["id"]
                        action, ap_id = reply_id.split(":", 1)
                        _handle_button(action, ap_id)
                    elif msg.get("type") == "text":
                        _handle_command(msg["text"]["body"], quoted_id)
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


# ---------------------------------------------------------------------------
# Telegram — the ops channel (Aug 2026). Shares the SAME ordered command queue
# and button handlers as WhatsApp; only the transport differs. Chosen for ops
# because business-initiated messages need no 24h window and no template review.
# ---------------------------------------------------------------------------
_seen_tg_updates: deque = deque(maxlen=500)


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request) -> dict:
    from . import telegram

    # 1) Authenticate the CALLER. Telegram echoes the secret we set via
    #    setWebhook; anything without it is not Telegram and is dropped.
    expected = telegram.wire_secret()
    if expected:
        sent = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(sent, expected):
            log.warning("telegram webhook: bad or missing secret token")
            return {"status": "forbidden"}
    try:
        update = await request.json()
    except Exception:  # noqa: BLE001
        return {"status": "received"}

    try:
        # 2) Dedupe — Telegram redelivers until it gets a 200.
        uid = update.get("update_id")
        if uid is not None:
            if uid in _seen_tg_updates:
                return {"status": "duplicate"}
            _seen_tg_updates.append(uid)

        cq = update.get("callback_query")
        msg = update.get("message") or {}

        # 3) Authorise the SENDER. Fails closed — see config.TELEGRAM_ALLOWED_CHAT_IDS.
        chat_id = ((cq or {}).get("message", {}).get("chat", {}).get("id")
                   or msg.get("chat", {}).get("id"))
        if not telegram.is_allowed(chat_id):
            log.warning("telegram webhook: chat %s not in allowlist", chat_id)
            return {"status": "ignored"}

        if cq:
            # Always ack first or the client spins for ~30s.
            telegram.ack(cq.get("id", ""))
            data = cq.get("data", "") or ""
            if ":" in data:
                action, ref = data.split(":", 1)
                if action in ("approve", "deny", "edit"):
                    _handle_button(action, ref)
                    # Rewrite the prompt in place so the chat reads as a ledger
                    # rather than a scroll of stale buttons.
                    mark = {"approve": "✅ Approved",
                            "deny": "❌ Denied",
                            "edit": "✏️ Editing"}[action]
                    original = (cq.get("message") or {}).get("text", "")
                    telegram.resolve((cq.get("message") or {}).get("message_id"),
                                     f"{mark}\n\n{original[:3900]}")
            return {"status": "received"}

        # A reply to one of our messages carries the context the agent needs.
        quoted = msg.get("reply_to_message") or {}
        quoted_id = f"tg:{quoted['message_id']}" if quoted.get("message_id") else ""

        if msg.get("voice") or msg.get("audio"):
            media = msg.get("voice") or msg.get("audio")
            _enqueue("tg_voice", json.dumps({"file_id": media["file_id"],
                                             "chat_id": str(chat_id)}))
        elif msg.get("text"):
            _handle_command(msg["text"], quoted_id, str(chat_id))
    except Exception:  # noqa: BLE001 — always 200 so Telegram doesn't retry-storm
        log.exception("telegram webhook")
    return {"status": "received"}


@app.get("/admin/telegram_setup")
def telegram_setup(key: str = Depends(admin_key)) -> dict:
    """Register the webhook with Telegram. Run once per deploy target."""
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    if not config.TELEGRAM_ENABLED:
        return {"error": "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set"}
    from . import telegram
    base = config.PUBLIC_BASE_URL
    if not base.startswith("https://"):
        # Telegram only delivers webhooks over HTTPS — a localhost default here
        # would register a URL it can never reach and fail silently later.
        return {"error": f"PUBLIC_BASE_URL must be https, got {base!r}"}
    try:
        return {"ok": True, "result": telegram.set_webhook(base)}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{exc.__class__.__name__}: {exc}"}


@app.get("/admin/register_owner")
def register_owner(key: str = Depends(admin_key), chat_id: str = "", name: str = "Gomeh") -> dict:
    """Claim a Telegram chat as the owner. Run once."""
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    if not chat_id:
        return {"error": "chat_id required — message the bot, it will tell you yours"}
    from . import tenants
    tenants.seed()  # idempotent
    return {"ok": True, **tenants.seed_owner(chat_id, name),
            "tenants": [tenants.summary_line(t.key) for t in tenants.all_tenants()]}


@app.get("/admin/tenants")
def list_tenants(key: str = Depends(admin_key)) -> dict:
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    from . import tenants
    return {"tenants": [tenants.resolve(t.key) for t in tenants.all_tenants()]}


@app.get("/admin/tenant_set")
def tenant_set(key: str = Depends(admin_key), tenant: str = "", field: str = "",
               value: str = "") -> dict:
    """Update one connection field on a tenant, without a redeploy.

    /admin/tenant_set?key=SECRET&tenant=baci&field=gmail_alias&value=baci
    /admin/tenant_set?key=SECRET&tenant=coverings&field=esp&value={"provider":"klaviyo"}

    JSON fields (esp, ads, cms, analytics, design, crm, systems) take a JSON
    literal; the rest take a plain string. Values are keys into credential
    dicts or vault references — never secrets themselves.
    """
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    from . import tenants
    JSON_FIELDS = {"esp", "ads", "cms", "analytics", "design", "crm", "systems"}
    SCALAR = {"name", "kind", "status", "domain", "timezone",
              "gmail_alias", "shopify_store", "notes"}
    if field not in JSON_FIELDS | SCALAR:
        return {"error": f"unknown field; allowed: {sorted(JSON_FIELDS | SCALAR)}"}
    with db.SessionLocal() as s:
        t = s.get(db.Tenant, tenant)
        if not t:
            return {"error": f"unknown tenant {tenant!r}"}
        if field in JSON_FIELDS:
            try:
                parsed = json.loads(value)
            except ValueError as exc:
                return {"error": f"field {field} needs JSON: {exc}"}
            setattr(t, field, parsed)
        else:
            setattr(t, field, value)
        s.commit()
    return {"ok": True, **tenants.resolve(tenant)}


@app.get("/admin/tenant_add")
def tenant_add(key: str = Depends(admin_key), tenant: str = "", name: str = "",
               kind: str = "client", domain: str = "") -> dict:
    """Create a new account. Seeding only covers the original five.

    /admin/tenant_add?key=SECRET&tenant=acme&name=Acme+Co&domain=acme.com
    Connections are attached afterwards with /admin/tenant_set.
    """
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    tenant = (tenant or "").strip().lower()
    if not tenant or not tenant.replace("_", "").replace("-", "").isalnum():
        return {"error": "tenant must be a short alphanumeric key, e.g. 'acme'"}
    if not name:
        return {"error": "name required"}
    from . import tenants
    with db.SessionLocal() as s:
        if s.get(db.Tenant, tenant):
            return {"error": f"{tenant!r} already exists — use /admin/tenant_set"}
        s.add(db.Tenant(key=tenant, name=name, kind=kind, domain=domain,
                        systems=[], notes="created via /admin/tenant_add"))
        s.commit()
    return {"ok": True, "created": tenant, **tenants.resolve(tenant),
            "next": "attach connections with /admin/tenant_set, then seed its KB"}


@app.get("/admin/user_add")
def user_add(key: str = Depends(admin_key), chat_id: str = "", name: str = "",
             role: str = "client", tenant: str = "") -> dict:
    """Give someone access to the bot, scoped to one account.

    /admin/user_add?key=SECRET&chat_id=123&name=Ellis&role=client&tenant=coverings

    role=client     their own account: reports, approvals
    role=freelancer their own account, no reporting
    role=owner      every account, may switch freely
    """
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    if role not in ("owner", "client", "freelancer"):
        return {"error": "role must be owner | client | freelancer"}
    if role != "owner" and not tenant:
        return {"error": "a non-owner must be pinned to a tenant"}
    if not chat_id:
        return {"error": "chat_id required — have them message the bot first"}
    with db.SessionLocal() as s:
        if tenant and not s.get(db.Tenant, tenant):
            return {"error": f"unknown tenant {tenant!r}"}
        u = s.query(db.User).filter(db.User.telegram_chat_id == str(chat_id)).first()
        if u:
            u.name, u.role, u.tenant_key = name or u.name, role, tenant or None
        else:
            s.add(db.User(name=name, telegram_chat_id=str(chat_id), role=role,
                          tenant_key=tenant or None,
                          active_tenant=tenant or "agency"))
        s.commit()
    return {"ok": True, "name": name, "role": role,
            "scoped_to": tenant or "all accounts"}


@app.get("/admin/ui", response_class=HTMLResponse)
def admin_ui(request: Request, key: str = Depends(admin_key),
             tab: str = "accounts", tenant: str = "",
             started: str = "") -> str:
    """The console. Accounts wires connections; Systems runs the pipelines."""
    if key != config.APPROVAL_SECRET:
        return "<h3>bad key</h3>"
    from . import admin_ui as ui
    # Once the session cookie carries the credential, stop threading it through
    # every link and hidden field — that propagation is what put it in browser
    # history in the first place. The forms still post `key=`, now empty, and
    # the cookie authenticates them.
    link_key = key if request.query_params.get("key") else ""
    if tab == "systems":
        return ui.render_systems(link_key)
    if tab == "kb":
        return ui.render_kb(link_key, tenant,
                            err=request.query_params.get("err", ""))
    if tab == "schema":
        return ui.render_schema(link_key, tenant)
    if tab == "content":
        return ui.render_content(link_key, tenant, started=started,
                                 err=request.query_params.get("err", ""))
    q = request.query_params
    return ui.render(link_key, msg=q.get("ok", ""), err=q.get("err", ""),
                     link=q.get("link", ""))


@app.get("/admin/kb_add")
def kb_add(key: str = Depends(admin_key), tenant: str = "", step: str = "", text: str = ""):
    """Capture one KB answer. Same parser the Telegram intake uses, so a fact
    entered on a phone and one entered in the console land identically."""
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    from . import kb as kbm
    result = kbm.apply_answer(tenant, step, text)
    # Same test as the Telegram path: the data decides whether it took.
    if any(g["id"] == step for g in kbm.gaps(tenant)):
        return {"error": result, "step": step}
    from fastapi.responses import RedirectResponse
    return RedirectResponse(f"/admin/ui?key={key}&tab=kb&tenant={tenant}",
                            status_code=303)


@app.get("/admin/kb_unknown")
def kb_unknown(key: str = Depends(admin_key), tenant: str = "", id: str = "", value: str = ""):
    """Close one gap from the console. Same writer as the Telegram `/unknowns`
    reply, so the value lands on the entity identically either way."""
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    from . import kb as kbm
    result = kbm.resolve_unknown(id, value)
    # resolve_unknown returns prose either way; the row's status is the fact.
    still_open = any(u.id == id for u in kbm.unknowns(tenant))
    if still_open:
        return {"error": result, "id": id}
    from fastapi.responses import RedirectResponse
    return RedirectResponse(f"/admin/ui?key={key}&tab=kb&tenant={tenant}",
                            status_code=303)


@app.get("/admin/intake_new")
def intake_new(key: str = Depends(admin_key), tenant: str = "", label: str = "", days: int = 30):
    """Mint a private intake link for one client."""
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    import datetime as _dt
    import secrets
    from . import tenants as tn
    if not tn.get(tenant):
        return {"error": f"unknown tenant {tenant!r}"}
    token = secrets.token_urlsafe(24)
    with db.SessionLocal() as s:
        s.add(db.IntakeLink(
            token=token, tenant=tenant, label=label,
            expires_at=db.utcnow() + _dt.timedelta(days=max(1, days))))
        s.commit()
    return {"ok": True, "tenant": tenant,
            "url": f"{config.PUBLIC_BASE_URL}/intake/{token}",
            "expires_in_days": days,
            "note": "Send this to the client. It reaches one account and nothing else."}


@app.get("/admin/intake_links")
def intake_links(key: str = Depends(admin_key), tenant: str = "") -> dict:
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    with db.SessionLocal() as s:
        q = s.query(db.IntakeLink)
        if tenant:
            q = q.filter(db.IntakeLink.tenant == tenant)
        rows = q.order_by(db.IntakeLink.created_at.desc()).all()
        return {"links": [
            {"tenant": r.tenant, "label": r.label, "status": r.status,
             "answered": r.answered, "expires_at": str(r.expires_at),
             "url": f"{config.PUBLIC_BASE_URL}/intake/{r.token}"} for r in rows]}


@app.get("/admin/intake_revoke")
def intake_revoke(key: str = Depends(admin_key), token: str = "") -> dict:
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    with db.SessionLocal() as s:
        row = s.get(db.IntakeLink, token)
        if not row:
            return {"error": "no such link"}
        row.status = "revoked"
        s.commit()
    return {"ok": True, "revoked": token}


def _connect_link(token: str):
    """Resolve a connect token, or a reason it is not usable."""
    with db.SessionLocal() as s:
        link = s.get(db.ConnectLink, token)
        if link:
            s.expunge(link)
    if not link or link.status != "active":
        return None, "<h3>This link is no longer active.</h3>"
    if link.expires_at and db.as_utc(link.expires_at) < db.utcnow():
        return None, "<h3>This link has expired. Ask for a new one.</h3>"
    return link, ""


@app.get("/connect/{token}", response_class=HTMLResponse)
def connect_page(token: str, ok: str = "", err: str = "") -> str:
    """The client's own surface for connecting their accounts.

    Public by token, scoped to one tenant, and it reads nothing back — a
    credential that has been stored is shown as connected and never as a value.
    """
    from . import admin_ui as ui, credentials as cred
    link, problem = _connect_link(token)
    if problem:
        return problem
    rows = [r for r in cred.status(link.tenant)
            if r["provider"] in cred.needed_for(link.tenant)]
    return ui.render_connect(link, link.tenant, rows, msg=ok, err=err)


@app.post("/connect/{token}", response_class=HTMLResponse)
async def connect_submit(token: str, request: Request):
    """Take one credential, verify it live, store it encrypted.

    POST rather than GET, unlike every other form in this console: an API key in
    a query string lands in browser history, the Referer header and the access
    log. The value is read from the body, used once, and never echoed back.
    """
    from fastapi.responses import RedirectResponse

    from . import credentials as cred
    link, problem = _connect_link(token)
    if problem:
        return HTMLResponse(problem)

    form = await request.form()
    provider = str(form.get("provider", ""))
    spec = cred.PROVIDERS.get(provider)
    if not spec:
        return RedirectResponse(f"/connect/{token}?err=Unknown+provider", 303)
    meta = {f: str(form.get(f, "")) for f in spec["also"]}
    result = cred.store(link.tenant, provider, str(form.get("secret", "")),
                        meta=meta, granted_by=link.label or "")

    with db.SessionLocal() as s:
        row = s.get(db.ConnectLink, token)
        if row:
            row.last_used_at = db.utcnow()
            s.commit()

    from urllib.parse import quote
    if result["ok"]:
        detail = f" — {result['detail']}" if result.get("detail") else ""
        return RedirectResponse(
            f"/connect/{token}?ok={quote(spec['name'] + ' connected' + detail)}", 303)
    return RedirectResponse(f"/connect/{token}?err={quote(result['error'])}", 303)


@app.get("/connect/{token}/oauth/{provider}")
def connect_oauth_start(token: str, provider: str):
    """Send the client to the provider's consent screen.

    The connect token is the capability, so it is checked here rather than
    trusted from the state that comes back: a link revoked between this request
    and the callback must not complete.
    """
    from fastapi.responses import RedirectResponse
    from urllib.parse import quote

    from . import oauth
    link, problem = _connect_link(token)
    if problem:
        return HTMLResponse(problem)
    why = oauth.configured(provider)
    if why:
        return RedirectResponse(f"/connect/{token}?err={quote(why)}", 303)
    state = oauth.sign_state(link.tenant, provider, connect_token=token)
    return RedirectResponse(oauth.authorize_url(provider, state), 303)


@app.get("/admin/oauth/{provider}")
def admin_oauth_start(provider: str, request: Request,
                      key: str = Depends(admin_key), tenant: str = ""):
    """The same flow for the owner, for accounts he connects himself.

    Kept separate from the client link rather than minting a connect link and
    using it, because a link is a thing that gets sent to someone. This one
    needs the console session and reaches whichever tenant is named.
    """
    from fastapi.responses import RedirectResponse

    from . import oauth, tenants as tn
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    if not tn.get(tenant):
        return {"error": f"unknown tenant {tenant!r}"}
    why = oauth.configured(provider)
    if why:
        return {"error": why}
    state = oauth.sign_state(tenant, provider, via="admin")
    return RedirectResponse(oauth.authorize_url(provider, state), 303)


@app.get("/oauth/{provider}/callback", response_class=HTMLResponse)
def oauth_callback(provider: str, request: Request, code: str = "",
                   state: str = "", error: str = "",
                   key: str = Depends(admin_key)):
    """Where consent lands. One route for every provider, by design.

    The redirect URI is registered with Google and Meta and cannot vary per
    client, so this is the single place a sign-in completes. Everything that
    differs between providers is in `oauth.FLOWS`.
    """
    from urllib.parse import quote

    from fastapi.responses import RedirectResponse

    from . import credentials as cred, oauth

    data, why = oauth.read_state(state)
    if why:
        return HTMLResponse(f"<h3>{html.escape(why)}</h3>", status_code=400)
    back = (f"/connect/{data['t']}" if data.get("t")
            else f"/admin/ui?tab=accounts&tenant={quote(data.get('tenant', ''))}")

    # The user declining is the common non-success and it is not an error.
    if error or not code:
        msg = "Sign-in was cancelled." if error in ("access_denied", "") \
            else f"Sign-in failed: {error}"
        return RedirectResponse(f"{back}?err={quote(msg)}", 303)

    # Re-derive authority rather than trusting the state's own claim to it.
    if data.get("via") == "admin":
        if key != config.APPROVAL_SECRET:
            return HTMLResponse("<h3>Console session expired — sign in to the "
                                "console and try again.</h3>", status_code=403)
        tenant, granted_by = data.get("tenant", ""), "Gomeh"
    else:
        link, problem = _connect_link(data.get("t", ""))
        if problem:
            return HTMLResponse(problem)
        tenant, granted_by = link.tenant, (link.label or "")
        with db.SessionLocal() as s:
            row = s.get(db.ConnectLink, data["t"])
            if row:
                row.last_used_at = db.utcnow()
                s.commit()

    result = oauth.exchange(provider, code)
    if not result["ok"]:
        return RedirectResponse(f"{back}?err={quote(result['error'])}", 303)
    stored = cred.store_oauth(tenant, provider, result, granted_by=granted_by)
    if not stored["ok"]:
        return RedirectResponse(f"{back}?err={quote(stored['error'])}", 303)
    return RedirectResponse(f"{back}?ok={quote(stored['detail'])}", 303)


@app.get("/admin/connect_new")
def connect_new(key: str = Depends(admin_key), tenant: str = "",
                label: str = "", days: int = 30) -> dict:
    """Mint a private connect link for one client."""
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    import datetime as _dt
    import secrets as _secrets

    from . import tenants as tn
    if not tn.get(tenant):
        return {"error": f"unknown tenant {tenant!r}"}
    token = _secrets.token_urlsafe(24)
    with db.SessionLocal() as s:
        s.add(db.ConnectLink(
            token=token, tenant=tenant, label=label,
            expires_at=db.utcnow() + _dt.timedelta(days=max(1, days))))
        s.commit()
    return {"ok": True, "tenant": tenant,
            "url": f"{config.PUBLIC_BASE_URL}/connect/{token}",
            "expires_in_days": days,
            "note": "Send this to the client. It reaches one account and "
                    "connects nothing else."}


@app.get("/admin/connections")
def connections(key: str = Depends(admin_key), tenant: str = "") -> dict:
    """Every client, every provider, connected or not. Never returns a secret."""
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    from . import credentials as cred, tenants as tn
    keys = [tenant] if tenant else [t.key for t in tn.all_tenants(include_paused=True)]
    return {k: cred.status(k) for k in keys}


@app.get("/admin/connect_revoke")
def connect_revoke(key: str = Depends(admin_key), tenant: str = "",
                   provider: str = "") -> dict:
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    from . import credentials as cred
    return {"result": cred.revoke(tenant, provider)}


@app.post("/admin/connect_revoke")
async def connect_revoke_post(request: Request, key: str = Depends(admin_key)):
    """The console's disconnect button. POST, unlike its GET twin.

    DEFECTS records that console writes on GET can be fired by a browser
    prefetch or a link preview. That is tolerable for `seed_kb`, which is
    idempotent; it is not tolerable for the control that severs a client's
    connection. The GET stays because the runbook documents it for curl.
    """
    from fastapi.responses import RedirectResponse
    from urllib.parse import quote

    from . import credentials as cred
    if key != config.APPROVAL_SECRET:
        return HTMLResponse("<h3>unauthorized</h3>", status_code=403)
    form = await request.form()
    result = cred.revoke(str(form.get("tenant", "")),
                         str(form.get("provider", "")))
    return RedirectResponse(f"/admin/ui?tab=accounts&ok={quote(result)}", 303)


@app.post("/admin/connect_test")
async def connect_test_post(request: Request, key: str = Depends(admin_key)):
    """Re-verify a stored API key against the live provider, and record it.

    "Connected" was a claim made once, at the moment of pasting, and never
    tested again — so a rotated or provider-revoked key kept a green chip and a
    `last_verified` date from months earlier. This is the button that turns
    that back into a measurement.
    """
    from fastapi.responses import RedirectResponse
    from urllib.parse import quote

    from . import credentials as cred
    if key != config.APPROVAL_SECRET:
        return HTMLResponse("<h3>unauthorized</h3>", status_code=403)
    form = await request.form()
    tenant, provider = str(form.get("tenant", "")), str(form.get("provider", ""))
    r = cred.recheck(tenant, provider)
    name = (cred.PROVIDERS.get(provider) or {}).get("name", provider)
    if r["ok"]:
        msg = f"{name} still works" + (f" — {r['detail']}" if r.get("detail") else "")
        return RedirectResponse(f"/admin/ui?tab=accounts&ok={quote(msg)}", 303)
    return RedirectResponse(
        f"/admin/ui?tab=accounts&err={quote(f'{name}: ' + r['error'])}", 303)


@app.post("/admin/connect_link")
async def connect_link_post(request: Request, key: str = Depends(admin_key)):
    """Mint a connect link from the console and show it, rather than as JSON.

    `/admin/connect_new` returns the URL in a JSON body, which meant creating a
    link for a client required a terminal — so the one action onboarding is
    built around was the one action the console could not do.
    """
    import datetime as _dt
    import secrets as _secrets
    from urllib.parse import quote

    from fastapi.responses import RedirectResponse

    from . import tenants as tn
    if key != config.APPROVAL_SECRET:
        return HTMLResponse("<h3>unauthorized</h3>", status_code=403)
    form = await request.form()
    tenant = str(form.get("tenant", ""))
    if not tn.get(tenant):
        return RedirectResponse(
            f"/admin/ui?tab=accounts&err={quote(f'unknown tenant {tenant!r}')}", 303)
    try:
        days = max(1, min(365, int(str(form.get("days", "30")) or 30)))
    except ValueError:
        days = 30
    token = _secrets.token_urlsafe(24)
    with db.SessionLocal() as s:
        s.add(db.ConnectLink(
            token=token, tenant=tenant, label=str(form.get("label", "")),
            expires_at=db.utcnow() + _dt.timedelta(days=days)))
        s.commit()
    url = f"{config.PUBLIC_BASE_URL.rstrip('/')}/connect/{token}"
    return RedirectResponse(f"/admin/ui?tab=accounts&link={quote(url)}", 303)


@app.get("/intake/{token}", response_class=HTMLResponse)
def intake(token: str, answer: str = "", skip: str = "") -> str:
    """The client's own surface. Public by token, scoped to one tenant.

    Deliberately has no way to read anything back — a client fills their
    knowledge base here, they do not browse it. Everything they submit lands
    through the same parser the console and the bot use.
    """
    from . import admin_ui as ui, kb as kbm, systems as sysm
    with db.SessionLocal() as s:
        link = s.get(db.IntakeLink, token)
        if link:
            s.expunge(link)
    if not link or link.status != "active":
        return "<h3>This link is no longer active.</h3>"
    if link.expires_at and db.as_utc(link.expires_at) < db.utcnow():
        return "<h3>This link has expired. Ask for a new one.</h3>"

    tenant = link.tenant
    saved = ""
    if answer.strip():
        step = kbm.next_step(tenant)
        if step:
            saved = kbm.apply_answer(tenant, step["id"], answer,
                                     source=link.label or "client")
            with db.SessionLocal() as s:
                row = s.get(db.IntakeLink, token)
                row.answered = str(int(row.answered or "0") + 1)
                row.last_used_at = db.utcnow()
                s.commit()

    gaps = kbm.gaps(tenant)
    # Skipping moves past a question for this visit without recording an answer,
    # so it is asked again next time rather than being silently accepted.
    step = next((g for g in gaps if g["id"] != skip), None) if skip else \
        (gaps[0] if gaps else None)
    waiting = sysm.waiting_on(tenant).get(step["id"], []) if step else []
    total = max(len(gaps), 1)
    done = int(link.answered or "0")
    return ui.render_intake(link, tenant, step, min(done, total - 1) if step else total,
                            total, waiting, saved)


@app.get("/admin/claim_review")
def claim_review(key: str = Depends(admin_key), claim_id: str = "",
                 approve: str = "yes", tenant: str = "", ui: str = ""):
    """Approve or reject a client-submitted claim."""
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    from . import kb as kbm
    res = kbm.review_claim(claim_id, approve == "yes")
    return _back_to_content(tenant) if ui else {"result": res}


@app.get("/admin/kb")
def kb_json(key: str = Depends(admin_key), tenant: str = "") -> dict:
    """The whole knowledge base for one account, as data."""
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    from . import kb as kbm
    b = kbm.brand(tenant)
    return {
        "tenant": tenant,
        "completeness": kbm.completeness(tenant),
        "gaps": [g["q"] for g in kbm.gaps(tenant)],
        "brand": ({"display_name": b.display_name, "positioning": b.positioning,
                   "voice": b.voice, "banned_claims": b.banned_claims} if b else None),
        "claims": [{"claim": r.claim, "evidence": r.evidence,
                    "situations": r.situations, "source": r.source}
                   for r in kbm.claims(tenant)],
        "audiences": [{"key": r.key, "name": r.name, "pains": r.pains,
                       "vocabulary": r.vocabulary} for r in kbm.audiences(tenant)],
        "objections": [{"objection": r.objection, "response": r.response}
                       for r in kbm.objections(tenant)],
        "entities": [{"type": r.type, "key": r.key, "name": r.name,
                      "price": r.price, "attributes": r.attributes}
                     for r in kbm.entities(tenant, available_only=False)],
    }


# ---------------------------------------------------------------------------
# Systems — the registry behind the Systems tab.
#
# These redirect back to the tab rather than returning JSON: a contract is
# edited in a loop, and bouncing to a JSON body and back loses your place. The
# older tenant routes keep their JSON responses.
# ---------------------------------------------------------------------------

def _back_to_systems(key: str, msg: str = ""):
    from fastapi.responses import RedirectResponse
    url = f"/admin/ui?key={key}&tab=systems"
    if msg:
        from urllib.parse import quote
        url += f"&msg={quote(msg)}"
    return RedirectResponse(url, status_code=303)


@app.get("/admin/systems")
def list_systems(key: str = Depends(admin_key)) -> dict:
    """The board as JSON — same data the tab renders, for the bot and for MCP."""
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    from . import systems
    return {"systems": systems.board()}


@app.get("/admin/systems_seed")
def systems_seed(key: str = Depends(admin_key)):
    """Adopt every pipeline already named in Tenant.systems as a real row."""
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    from . import systems
    systems.seed_from_tenants()
    return _back_to_systems(key)


@app.get("/admin/system_add")
def system_add(key: str = Depends(admin_key), tenant: str = "", system: str = ""):
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    from . import systems
    if not tenant or not system:
        return {"error": "tenant and system are both required"}
    systems.create(tenant, system)
    return _back_to_systems(key)


@app.get("/admin/system_set")
def system_set(request: Request, key: str = Depends(admin_key), id: str = ""):
    """Update contract fields, status or autonomy on one system.

    Fields are read off the query string rather than declared one by one, so
    adding a contract field to the model doesn't need a signature change here.
    Empty values are dropped rather than written, so a form that only fills two
    contract boxes doesn't blank the other six.
    """
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    from . import systems
    settable = set(systems.CONTRACT_FIELDS) | {"name", "status", "autonomy", "notes"}
    clean = {k: v for k, v in request.query_params.items()
             if k in settable and v not in ("", None)}
    if not clean:
        return _back_to_systems(key)
    out = systems.update(id, **clean)
    if out.get("error"):
        return out  # a refused promotion should be read, not silently swallowed
    return _back_to_systems(key)


@app.get("/admin/system_promote")
def system_promote(key: str = Depends(admin_key), id: str = ""):
    """Move one rung up the autonomy ladder, if the run history has earned it."""
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    from . import systems
    out = systems.promote(id)
    if out.get("error"):
        return out
    return _back_to_systems(key)


@app.get("/admin/system_note")
def system_note(key: str = Depends(admin_key), id: str = "", text: str = "", drop: str = ""):
    """Add or archive a piece of standing guidance for one system."""
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    from . import systems
    if drop:
        systems.drop_note(drop)
        return _back_to_systems(key)
    row = systems.get(id)
    if not row:
        return {"error": "unknown system"}
    systems.note(row.tenant, row.key, text)
    return _back_to_systems(key)


@app.get("/admin/system_rule")
def system_rule(key: str = Depends(admin_key), id: str = "", phrase: str = ""):
    """Promote a correction into a banned claim the validator enforces."""
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    from . import systems
    row = systems.get(id)
    if not row:
        return {"error": "unknown system"}
    result = systems.promote_rule(row.tenant, phrase)
    if result.startswith("No KB brand row"):
        return {"error": result}
    return _back_to_systems(key)


@app.get("/admin/verify")
def verify_tenant(key: str = Depends(admin_key), tenant: str = "") -> dict:
    """Live-test a tenant's integrations. 'Configured' and 'working' are
    different questions — a revoked token still looks configured."""
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    from . import tenants
    if not tenant:
        return {"tenants": [tenants.verify(t.key) for t in tenants.all_tenants()]}
    return tenants.verify(tenant)


@app.get("/admin/seed_kb")
def seed_kb(key: str = Depends(admin_key), report_only: str = "") -> dict:
    """Seed the knowledge base for baci / ironside / eien / coverings.

    The data lives in app/kb_seed.py and was previously only runnable from a
    laptop with DATABASE_URL pointed at production — which meant it had never
    been run at all. Idempotent: individual seeds no-op when rows exist.

    /admin/seed_kb?key=SECRET&report_only=1   show gaps, change nothing
    /admin/seed_kb?key=SECRET                 seed, then show gaps
    """
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    from . import kb_seed
    if report_only:
        return {"status": kb_seed.status()}
    return kb_seed.seed_all()


def _back_to_content(tenant: str, started: str = "", err: str = ""):
    """Return to the Content tab. No key in the URL: by the time an action has
    run, the session cookie is already set (the middleware sets it on any
    request carrying a valid key), so putting the secret back into the address
    bar would undo the session for nothing."""
    from urllib.parse import quote

    from fastapi.responses import RedirectResponse
    q = f"/admin/ui?tab=content&tenant={tenant}"
    if started:
        q += f"&started={started}"
    if err:
        q += f"&err={quote(err)}"
    return RedirectResponse(q, status_code=303)


def _back_to_kb(tenant: str, err: str = ""):
    """Return to the Knowledge tab, carrying any refusal with it."""
    from urllib.parse import quote

    from fastapi.responses import RedirectResponse
    q = f"/admin/ui?tab=kb&tenant={tenant}"
    return RedirectResponse(q + (f"&err={quote(err)}" if err else ""),
                            status_code=303)


def _run_bg(label: str, fn, *args, **kw) -> None:
    """Run a slow action off the request.

    A 40-page compliance scan takes 16s locally and longer on a cold container,
    and a GET that blocks that long with no feedback is indistinguishable from a
    broken button — which is exactly how it was reported. The work continues;
    the page comes straight back and the result appears in the tab when it
    lands."""
    import threading

    def _go():
        try:
            fn(*args, **kw)
        except Exception:  # noqa: BLE001
            log.exception("%s failed", label)
    threading.Thread(target=_go, daemon=True).start()


@app.get("/admin/fill")
def fill_route(key: str = Depends(admin_key), tenant: str = "",
               apply: str = "", budget: int = 40, only: str = "") -> dict:
    """Run every source this account has wired, and report what is still missing.

    /admin/fill?tenant=ironside              a read-only rehearsal
    /admin/fill?tenant=baci&apply=1          file the proposals
    /admin/fill?tenant=baci&only=sent_mail   one source

    Sources declare themselves in `sources.SOURCES`; this route knows none of
    them by name, so adding one does not change this code.
    """
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    from . import sources
    if not tenant:
        return {"error": "an account is required"}
    return sources.fill(tenant, apply=bool(apply), budget=budget,
                        only=[o for o in only.split(",") if o] or None)


@app.get("/admin/email_harvest")
def email_harvest_route(key: str = Depends(admin_key), tenant: str = "",
                        days: int = 365, limit: int = 80, apply: str = "",
                        ui: str = ""):
    """Mine claims and objections out of this account's SENT mail.

    /admin/email_harvest?tenant=baci               what it would propose
    /admin/email_harvest?tenant=baci&apply=1       file them as proposals

    Threads are filtered by the bucket triage already assigned, so this reads
    the handful worth reading rather than the whole mailbox.
    """
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    from . import email_harvest as eh
    if ui:
        _run_bg("email_harvest", eh.mine, tenant, days=days, limit=limit,
                apply=True)
        return _back_to_content(tenant, "email")
    return eh.mine(tenant, days=days, limit=limit, apply=bool(apply))


@app.get("/admin/purge_proposals")
def purge_proposals_route(key: str = Depends(admin_key), tenant: str = "",
                          origin: str = "") -> dict:
    """What a purge WOULD delete. Always a dry run — this route never deletes.

    /admin/purge_proposals?tenant=baci                what it would delete
    /admin/purge_proposals?tenant=baci&origin=crawl   narrowed to one source

    A GET that deletes is fired by anything that causes a URL to load: a browser
    prefetch, a link preview, a scanner walking history. That is a listed defect
    for the console's other write routes and it is worst here, because this one
    is destructive. Deleting requires the POST below.
    """
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    from . import kb as kbm
    return kbm.purge_proposals(tenant=tenant, origin=origin, dry_run=True)


@app.post("/admin/purge_proposals", response_class=HTMLResponse)
async def purge_proposals_do(request: Request, key: str = Depends(admin_key)):
    """Clear every un-reviewed proposal for one account, in one action.

    Approved rows are never touched, and proposals are DELETED rather than
    rejected — `suggest_tags` learns what a bad claim looks like from retired
    rows, so filing a hundred pieces of parser noise as "rejected" would teach
    the tagger that noise is what rejection looks like.
    """
    if key != config.APPROVAL_SECRET:
        return HTMLResponse('<h3>unauthorized</h3>')
    from . import kb as kbm
    form = await request.form()
    tenant = str(form.get("tenant", ""))
    if not tenant:
        return HTMLResponse('<h3>an account is required</h3>', status_code=400)
    kbm.purge_proposals(tenant=tenant, origin=str(form.get("origin", "")),
                        dry_run=False)
    return _back_to_content(tenant)


@app.get("/admin/purge_scans")
def purge_scans_route(key: str = Depends(admin_key), tenant: str = "",
                      dry_run: str = "1") -> dict:
    """Drop recorded compliance scans so the tab stops showing a stale one."""
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    from . import compliance
    return compliance.purge_scans(
        tenant=tenant, dry_run=dry_run not in ("0", "false", "no"))


@app.post("/admin/proposal_review", response_class=HTMLResponse)
async def proposal_review(request: Request, key: str = Depends(admin_key)):
    """Approve or reject a proposed audience, objection, entity or situation.

    Claims have their own route because approving one edits it first and can be
    refused for want of a tag. Everything else is a straight yes or no, and
    approving it is what makes it usable AND final — from that point no crawl,
    upload or store sync may change it.
    """
    if key != config.APPROVAL_SECRET:
        return HTMLResponse('<h3>unauthorized</h3>')
    from . import kb as kbm
    form = await request.form()
    tenant = str(form.get("tenant", ""))
    kind, row_id = str(form.get("kind", "")), str(form.get("row_id", ""))
    # Scope is set BEFORE approval, not after: approving is what makes a row
    # final, and a row that goes final unscoped is claimed of the whole
    # catalogue. Writing it afterwards would mean the wrong version was
    # briefly true, and `may_write` refuses machine edits to approved rows.
    if kind == "objection" and form.get("entity_key") is not None:
        problem = kbm.update_objection(row_id,
                                       entity_key=str(form.get("entity_key", "")))
        if problem != "Saved.":
            return _back_to_content(tenant, err=problem)
    result = kbm.approve(kind, row_id, by="owner",
                         approve_it=str(form.get("action", "")) == "approve",
                         brand_wide=bool(form.get("brand_wide")))
    if result.startswith("Say what"):
        return _back_to_content(tenant, err=result)
    return _back_to_content(tenant)


@app.post("/admin/objection_edit", response_class=HTMLResponse)
async def objection_edit(request: Request, key: str = Depends(admin_key)):
    """Re-scope an objection that is already approved.

    The guard on approval stops new rows going final unscoped; it does nothing
    about the ones already in the database, which were filed brand-wide by the
    code this replaces and are the ones actually saying something false today.
    This is how those get fixed without deleting a real answer.
    """
    if key != config.APPROVAL_SECRET:
        return HTMLResponse("<h3>unauthorized</h3>")
    from . import kb as kbm
    form = await request.form()
    tenant = str(form.get("tenant", ""))
    result = kbm.update_objection(str(form.get("row_id", "")),
                                  entity_key=str(form.get("entity_key", "")))
    return _back_to_kb(tenant, err="" if result == "Saved." else result)


@app.post("/admin/conflict_resolve", response_class=HTMLResponse)
async def conflict_resolve(request: Request, key: str = Depends(admin_key)):
    """Settle a disagreement between two sources about an approved value."""
    if key != config.APPROVAL_SECRET:
        return HTMLResponse('<h3>unauthorized</h3>')
    from . import provenance as prov
    form = await request.form()
    tenant = str(form.get("tenant", ""))
    prov.resolve_conflict(str(form.get("conflict_id", "")),
                          str(form.get("keep", "approved")))
    return _back_to_content(tenant)


@app.post("/admin/claim_edit", response_class=HTMLResponse)
async def claim_edit(request: Request, key: str = Depends(admin_key)):
    """Edit a proposal, then save / approve / reject it.

    POST rather than GET, like the connect form: a claim body is long free text
    and belongs in a request body, not a query string that lands in the access
    log. One form, three buttons — because the point of proposing is that the
    thing gets corrected before it becomes something the generator may say.
    """
    if key != config.APPROVAL_SECRET:
        return HTMLResponse('<h3>unauthorized</h3>')
    from . import kb as kbm
    form = await request.form()
    claim_id = str(form.get("claim_id", ""))
    tenant = str(form.get("tenant", ""))
    action = str(form.get("action", "save"))

    if action == "reject":
        kbm.review_claim(claim_id, approve=False)
        return _back_to_content(tenant)

    msg = kbm.update_claim(
        claim_id,
        claim=str(form.get("claim", "")),
        evidence=str(form.get("evidence", "")),
        entity_key=str(form.get("entity_key", "")),
        tags=[str(t) for t in form.getlist("tags")])
    if msg != "Saved." and "catalogue" in msg:
        return HTMLResponse(f"<h3>{msg}</h3><p><a href='/admin/ui?tab=content"
                            f"&tenant={tenant}'>Back</a></p>", status_code=400)
    if action == "approve":
        # May refuse — an untagged claim cannot be approved, and the tab will
        # still show it with the reason.
        kbm.review_claim(claim_id, approve=True)
    return _back_to_content(tenant)


@app.get("/admin/harvest")
def harvest_route(key: str = Depends(admin_key), tenant: str = "",
                  limit: int = 25, apply: str = "", ui: str = ""):
    """Propose claims from a client's own site. Reads by default.

    /admin/harvest?tenant=baci            what it would propose
    /admin/harvest?tenant=baci&apply=1    file them as PENDING claims
    /admin/harvest?apply=1                every account

    Nothing becomes selectable here. Proposals are pending until approved on the
    Knowledge tab, anything using a banned phrase is dropped rather than queued,
    and a candidate that matches no situation tag is reported rather than stored
    with a guessed one.
    """
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    from . import harvest as hv
    if ui:
        _run_bg("harvest", hv.harvest if tenant else hv.harvest_all,
                *( (tenant,) if tenant else () ),
                limit=limit, apply=bool(apply))
        return _back_to_content(tenant, "harvest")
    return (hv.harvest(tenant, limit=limit, apply=bool(apply)) if tenant
            else hv.harvest_all(limit=limit, apply=bool(apply)))


@app.get("/admin/compliance_scan")
def compliance_scan(key: str = Depends(admin_key), tenant: str = "",
                    limit: int = 40, since: str = "", ui: str = ""):
    """Check a client's live website against its own banned claims.

    /admin/compliance_scan?tenant=baci             first full pass
    /admin/compliance_scan?tenant=baci&since=2026-08-01   only what changed

    Pages come from sitemap.xml, which every platform publishes — including
    Squarespace, which has no usable publishing API. Nothing is rewritten: the
    URL and the surrounding sentence are what make a violation fixable.
    """
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    from . import compliance
    if not tenant:
        return {"error": "name a tenant, e.g. ?tenant=baci"}
    def _scan_and_record():
        compliance.record_scan(tenant, compliance.scan(
            tenant, limit=limit, since=since))
    if ui:
        _run_bg("compliance scan", _scan_and_record)
        return _back_to_content(tenant, "scan")
    result = compliance.scan(tenant, limit=limit, since=since)
    compliance.record_scan(tenant, result)
    return result


@app.get("/admin/catalog_sync")
def catalog_sync(key: str = Depends(admin_key), tenant: str = "",
                 report_only: str = "", limit: int = 250, ui: str = ""):
    """Pull a client's Shopify catalogue into the knowledge base.

    /admin/catalog_sync?tenant=baci&report_only=1   what it would change
    /admin/catalog_sync?tenant=baci                 do it

    Also reports which products carry a phrase the account has banned — a
    brand's own copy is where its banned phrases live, and this is the list of
    pages to fix.
    """
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    from . import catalog_sync as cs
    if not tenant:
        return {"error": "name a tenant, e.g. ?tenant=baci"}
    if ui:
        _run_bg("catalog sync", cs.sync_shopify, tenant, limit=limit,
                dry_run=bool(report_only))
        return _back_to_content(tenant, "sync")
    return cs.sync_shopify(tenant, limit=limit, dry_run=bool(report_only))


@app.get("/admin/schema_check")
def schema_check(key: str = Depends(admin_key)) -> dict:
    """Did the migration actually land on THIS database?

    `_auto_migrate` adds columns and `_migrate_constraints` regrades the global
    uniques to per-client ones, but neither path can be exercised against
    Postgres from a laptop — SQLite cannot drop a constraint, so every local
    test covers the column half only. This asks the live database directly.

    Also reports which database the service is connected to, because
    `config.DATABASE_URL` falls back to a local SQLite file when the env var is
    missing: a service with no DATABASE_URL does not fail, it quietly serves an
    empty database that is wiped on every deploy.
    """
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    from sqlalchemy import inspect as sa_inspect

    from . import tenant_scope

    # Where are we actually pointed? Host and database name only — never the
    # credentials that are in the same string.
    url = db.engine.url
    where = {"dialect": url.get_backend_name(),
             "host": url.host or "(local file)",
             "database": url.database or ""}
    if url.get_backend_name() != "postgresql":
        where["WARNING"] = ("not Postgres — if this is the deployed service, "
                            "DATABASE_URL is missing and this is a throwaway "
                            "file that resets on every deploy")

    insp = sa_inspect(db.engine)
    tables = set(insp.get_table_names())

    uniques = {}
    for table, old_col, new_name, _cols in db._REGRADED_UNIQUES:
        if table not in tables:
            uniques[table] = "table does not exist yet"
            continue
        found = {u["name"]: (u.get("column_names") or [])
                 for u in insp.get_unique_constraints(table)}
        has_new = new_name in found
        # SQLite reports an inline column constraint with no name; Postgres
        # names it (contacts_email_key). Either way it is the stale one.
        stale = [n or f"(unnamed unique on {old_col})"
                 for n, c in found.items() if c == [old_col] and n != new_name]
        uniques[table] = {
            "per_client_constraint": new_name if has_new else "MISSING",
            "old_global_constraint": stale or "gone",
            "ok": has_new and not stale,
            "constraints_found": found,
        }

    missing_col = []
    for model in tenant_scope._SCOPED:
        t = model.__tablename__
        if t in tables and "tenant" not in {c["name"] for c in insp.get_columns(t)}:
            missing_col.append(t)

    all_ok = (where["dialect"] == "postgresql"
              and all(isinstance(v, dict) and v.get("ok") for v in uniques.values())
              and not missing_col)
    return {
        "ok": all_ok,
        "connected_to": where,
        "tenant_column_missing_from": missing_col or "none",
        "uniqueness": uniques,
        "note": ("ok=true means the migration landed: every scoped table has a "
                 "tenant column, and uniqueness is per client rather than global."),
    }


@app.get("/admin/tenant_scope")
def tenant_scope_admin(key: str = Depends(admin_key), report_only: str = "") -> dict:
    """Attribute the operational tables to a client.

    Fills every tenant that a row's own fields can prove — its inbox, its
    domain, its scope key — and leaves the rest unassigned rather than guessing.
    Idempotent; never overwrites a tenant that is already set.

    /admin/tenant_scope?key=SECRET&report_only=1   what it WOULD write
    /admin/tenant_scope?key=SECRET                 write it, then show the result

    The dry run predicts per row, not per table. "This table has a derivation
    rule" and "these 3,897 rows will be attributed" are different claims, and
    only the second one is worth acting on before a bulk write.
    """
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    from . import tenant_scope
    if report_only:
        return {"preview": tenant_scope.preview(),
                "report": tenant_scope.report(),
                "note": "nothing was written — drop report_only to apply"}
    filled = tenant_scope.backfill()
    return {"filled": filled, "report": tenant_scope.report(),
            "note": "unassigned rows are excluded from per-client queries by "
                    "default — set them by hand or leave them out of reports"}
