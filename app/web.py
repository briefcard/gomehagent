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


def read_key(request: Request, key: str = "") -> str:
    """Resolve a READ credential. Returns 'admin', 'read', or ''.

    Deliberately a different shape from `admin_key`, which returns the secret
    itself so that every `if key != config.APPROVAL_SECRET` downstream keeps
    working. That is exactly why a read-only key cannot be threaded through the
    same dependency: it would have to return the admin secret to satisfy those
    checks, and would then unlock the GET routes that mutate.

    So the split is structural rather than a matter of discipline. Read routes
    depend on this and accept either principal; every write route keeps
    `admin_key` and there is no value this can return that satisfies one.

    An unset `READ_KEY` means read-only access is off — `_matches` refuses an
    empty expected value, so this fails closed.
    """
    if admin_key(request, key):
        return "admin"
    expected = config.READ_KEY or ""
    if (_matches(key, expected)
            or _matches(request.headers.get("x-read-key", ""), expected)):
        return "read"
    return ""


@app.get("/resolve")
def resolve_context(request: Request, auth: str = Depends(read_key),
                    tenant: str = "", system: str = "", utterance: str = "",
                    contact_id: str = "", entity_key: str = "",
                    audience_key: str = "", requirements: str = "",
                    tier: int = 3, limit: int = 3) -> dict:
    """Hand a caller its context in one call. Reads only.

    `requirements` is a JSON object of what the buyer actually asked for —
    `{"seated_capacity": 220}`. Malformed JSON is reported rather than
    silently ignored, because a dropped requirement turns a checked match into
    a keyword one and the caller would never know.

    Read `blocked_on` first. A non-empty list means this account cannot safely
    produce output for this request, and each entry names the field to fill.
    """
    if not auth:
        return {"error": "unauthorized"}
    reqs, bad = {}, ""
    if requirements:
        try:
            reqs = json.loads(requirements)
            if not isinstance(reqs, dict):
                reqs, bad = {}, "requirements must be a JSON object"
        except Exception as exc:  # noqa: BLE001
            reqs, bad = {}, f"requirements is not valid JSON: {exc}"
    if bad:
        return {"error": bad}

    from . import resolve as rs
    out = rs.resolve(tenant, system=system, utterance=utterance,
                     contact_id=contact_id, entity_key=entity_key,
                     audience_key=audience_key, requirements=reqs,
                     tier=tier, limit=limit)
    out["principal"] = auth
    return out


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
    """Liveness, and WHICH BUILD is answering.

    The commit was added after half an hour was spent guessing whether a
    route's absence meant a failed deploy, a stale container or a mistake in
    the code — while the dashboard said everything had shipped. A service that
    cannot say what it is running turns every deploy question into archaeology.

    `RENDER_GIT_COMMIT` is set by Render itself, so this is what is actually
    executing rather than what a dashboard believes.
    """
    from . import channel
    import os as _os
    return {"ok": True, "whatsapp": config.WHATSAPP_ENABLED,
            "telegram": config.TELEGRAM_ENABLED,
            "ops_channel": channel.active(),
            "inboxes": list(config.GMAIL_ACCOUNTS),
            "commit": (_os.environ.get("RENDER_GIT_COMMIT") or "unknown")[:12],
            "routes": len({r.path for r in app.routes})}


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


@app.get("/admin/esp_probe")
def esp_probe(key: str = Depends(admin_key), tenant: str = "eien") -> dict:
    """Prove a client's live ESP end to end — READ ONLY, no draft, no send.

    Admin-gated because it returns segment/list NAMES (client data). It is the
    first real call any of this makes against a live ESP, so it doubles as a
    diagnosis: `connected: False` means the ESP was NOT connected via the
    Credential store (the /connect flow or the Accounts tab) — ESP creds are
    read from there ONLY, never from an env var, so an env-set key will not
    resolve and must be reconnected through the console.
    """
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    from . import esp
    provider = esp.provider_for(tenant)
    if not provider:
        return {"tenant": tenant, "connected": False,
                "note": "No ESP resolves for this account. ESP credentials are "
                        "read from the Credential store only — connect Omnisend "
                        "on the Accounts tab (or a /connect link); an env var is "
                        "not read for ESPs."}
    aud = esp.audiences(tenant)   # read-only: GET segments / lists
    return {"tenant": tenant, "provider": provider, "connected": True,
            "audiences": aud}


# ---------------------------------------------------------------------------
# Brand theme — derive and approve POSTs. The review PAGE is the console's
# Brand tab (`admin_ui.render_brand`, /admin/ui?tab=brand): it began life as a
# standalone page here and the owner's verdict was that a page reached by one
# hyperlink is not a place — so the surface moved into the frame beside
# Knowledge, and the old URL below redirects rather than 404ing bookmarks.
# ---------------------------------------------------------------------------


@app.get("/admin/brand_theme")
def brand_theme_page(request: Request, key: str = Depends(admin_key),
                     tenant: str = ""):
    """The old standalone review page — now a bookmark-safe redirect to the
    console's Brand tab, where the surface lives."""
    from urllib.parse import quote

    from fastapi.responses import RedirectResponse
    if key != config.APPROVAL_SECRET:
        return HTMLResponse("<h3>unauthorized</h3>", status_code=403)
    back = f"/admin/ui?tab=brand&tenant={quote(tenant)}"
    if request.query_params.get("key"):
        back += f"&key={quote(str(request.query_params['key']))}"
    if request.query_params.get("ok"):
        back += f"&ok={quote(str(request.query_params['ok']))}"
    return RedirectResponse(back, 303)


@app.post("/admin/brand_theme/derive")
async def brand_theme_derive(request: Request, key: str = Depends(admin_key)):
    """Run the deriver and re-show the review page. Writes the PROPOSAL only —
    a POST because it writes, even though nothing a customer sees changes."""
    from urllib.parse import quote

    from fastapi.responses import RedirectResponse

    from . import brand_theme
    if key != config.APPROVAL_SECRET:
        return HTMLResponse("<h3>unauthorized</h3>", status_code=403)
    form = await request.form()
    tenant = str(form.get("tenant", ""))
    got = brand_theme.derive(tenant)
    arg = (("ok", "derived — review below") if got.get("ok")
           else ("err", got.get("error", "derive failed")))
    back = (f"/admin/ui?tab=brand&tenant={quote(tenant)}"
            f"&{arg[0]}={quote(arg[1])}")
    if form.get("key"):
        back += f"&key={quote(str(form['key']))}"
    return RedirectResponse(back, 303)


@app.post("/admin/brand_theme/approve")
async def brand_theme_approve(request: Request, key: str = Depends(admin_key)):
    """The owner's approval — the ONLY path that writes the live theme."""
    from urllib.parse import quote

    from fastapi.responses import RedirectResponse

    from . import brand_theme
    if key != config.APPROVAL_SECRET:
        return HTMLResponse("<h3>unauthorized</h3>", status_code=403)
    from . import admin_ui as ui
    form = await request.form()
    tenant = str(form.get("tenant", ""))
    edits = {path: str(form.get(path, ""))
             for path, _label, _hint in ui._THEME_EDIT_FIELDS
             if str(form.get(path, "")).strip()}
    got = brand_theme.approve(tenant, edits)
    arg = (("ok", "approved" + (" — " + got["note"] if got.get("note") else ""))
           if got.get("ok") else ("err", got.get("error", "approve failed")))
    back = (f"/admin/ui?tab=brand&tenant={quote(tenant)}"
            f"&{arg[0]}={quote(arg[1])}")
    if form.get("key"):
        back += f"&key={quote(str(form['key']))}"
    return RedirectResponse(back, 303)


@app.get("/admin/canva_probe")
def canva_probe(key: str = Depends(admin_key), tenant: str = "agency") -> dict:
    """Prove a client's live Canva end to end — READ ONLY, and a TEACHER.

    Two questions, both answered without creating anything: does the REST
    token work (`/users/me` would need a wrapper, so the cheap read here is
    the folder lookup path's precondition — the token mint itself), and what
    does Canva's MCP server actually offer (tools/list — the REAL tool names,
    so the adapter maps exact names instead of guessed ones; ARCHITECTURE.md).
    Admin-gated because tool inventories and error strings are account data.
    """
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    from . import canva
    token, why = canva._token(tenant)
    rest = ({"ok": True, "note": "token minted — the REST surface will "
                                 "authenticate"} if token
            else {"ok": False, "error": why})
    mcp = canva.mcp_tools(tenant)
    return {"tenant": tenant, "rest": rest, "mcp": mcp,
            "next": ("wire exact MCP tool names into the canva adapter from "
                     "the list above" if mcp.get("ok") else
                     "fix the named blocker, then re-run this probe")}


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
    # `outcome` carries the approval summary, which is built from an email's
    # sender and subject (worker.py) — attacker-controlled text on an
    # unauthenticated page. Escape it, or a crafted subject line is stored XSS.
    return ("<html><body style='font-family:sans-serif;padding:3em'>"
            f"<h2>{html.escape(outcome)}</h2></body></html>")


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
def usage_report(key: str = Depends(admin_key), days: int = 7,
                 tenant: str = "") -> dict:
    """Cost + cache-hit audit. Open in a browser:
    /admin/usage?key=SECRET&days=7"""
    from . import usage
    if key != config.APPROVAL_SECRET:
        return {"error": "bad key"}
    return usage.report(days, tenant)


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
def pending_page(key: str = Depends(admin_key), tenant: str = "") -> str:
    """Browser fallback for the approval queue: every pending approval with
    working Approve/Deny links (relative URLs, so they work no matter what
    PUBLIC_BASE_URL says).

    Scoped by `tenant=` — the console's "N waiting" links here carrying the
    selected account, and a page that widened back to every client on the way
    in is how one client's reply gets approved while looking at another's
    console. `*` and an absent value both mean every account; which one you
    are reading is stated in the heading rather than inferred from the URL.
    """
    if key != config.APPROVAL_SECRET:
        return "<h3>bad key</h3>"
    from . import approvals as ap_mod, tenants as t_mod
    scoped = tenant and tenant != "*"
    who = tenant if scoped else ""
    if scoped:
        row = t_mod.get(tenant)
        who = (row.name if row else tenant)
    with db.SessionLocal() as s:
        q = s.query(db.Approval).filter(db.Approval.status == "pending")
        if scoped:
            q = q.filter(db.Approval.tenant == tenant)
        aps = q.order_by(db.Approval.created_at.desc()).all()
        rows = []
        for ap in aps:
            approve = "/decide/" + ap_mod._signer.dumps([ap.id, "approved"])
            deny = "/decide/" + ap_mod._signer.dumps([ap.id, "denied"])
            body = (ap.payload or {}).get("body") or (ap.payload or {}).get("content", "")
            # Which client this belongs to, on every row. An approval whose
            # account was never resolved says so rather than reading as this
            # one's -- an unattributed row folded into whoever is looking is
            # exactly the leak this page is being scoped to close.
            owner = (ap.tenant or "").strip() or "unattributed"
            # Everything from the approval — summary (email sender + subject),
            # body (model/email content), owner key — is escaped before it
            # reaches the console DOM. Unescaped, one crafted subject line runs
            # JS against the httpOnly session, and dozens of /admin GETs mutate.
            rows.append(
                f"<li style='margin:0 0 14px'><b>{ap.created_at:%b %d}</b> "
                f"<span style='font-size:.8em;background:#eef0f4;padding:1px 7px;"
                f"border-radius:99px'>{html.escape(owner)}</span> — "
                f"{html.escape(ap.summary or '')}"
                + (f"<details><summary>details</summary><pre style='white-space:"
                   f"pre-wrap;background:#f6f6f6;padding:8px'>"
                   f"{html.escape(body[:1500])}</pre>"
                   f"</details>" if body else "")
                + f" &nbsp;<a href='{approve}'>✅ Approve</a> · "
                  f"<a href='{deny}'>❌ Deny</a></li>")
    head = (f"Pending approvals — {html.escape(who)} ({len(rows)})" if scoped
            else f"Pending approvals — all accounts ({len(rows)})")
    other = ("" if scoped else
             "<p style='font-size:.85em;color:#6e7686'>Every account. "
             "Each row names the client it belongs to.</p>")
    return ("<html><body style='font-family:sans-serif;max-width:760px;"
            f"margin:2em auto'><h2>{head}</h2>{other}"
            "<ul style='list-style:none;padding:0'>"
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


def _verify_meta_sig(raw: bytes, header: str) -> bool:
    """Is this really Meta's delivery? HMAC-SHA256 of the RAW body under the app
    secret — the signature Meta sends in X-Hub-Signature-256 as 'sha256=...'.

    Fails CLOSED: with no META_APP_SECRET set we cannot verify, and this
    endpoint approves, executes and commands the agent, so an unverifiable
    delivery is refused rather than trusted. `compare_digest`, never `==`, on a
    value reachable from the open internet. Same shape as the Shopify webhook.
    """
    secret = (config.META_APP_SECRET or "").encode()
    if not secret or not header:
        return False
    want = "sha256=" + hmac.new(secret, raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(want, header)


@app.post("/webhooks/whatsapp")
async def whatsapp_incoming(request: Request) -> Response:
    """Handle button replies (approve:<id> / deny:<id>) and free-text messages.

    Verified on the RAW body before anything is parsed. The only gate used to be
    `msg["from"] == approver` — a field of the caller's own JSON — so a forged
    POST reached approve/execute and the command agent with no cryptographic
    check at all. An unsigned or wrongly-signed delivery is now refused 401.
    """
    raw = await request.body()
    if not _verify_meta_sig(raw, request.headers.get("x-hub-signature-256", "")):
        log.warning("whatsapp webhook: signature check failed — refused. "
                    "Set META_APP_SECRET to enable inbound WhatsApp.")
        return Response('{"status":"unverified"}', status_code=401,
                        media_type="application/json")
    try:
        body = json.loads(raw)
    except ValueError:
        return Response('{"status":"received"}', media_type="application/json")
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
    return Response('{"status":"received"}', media_type="application/json")


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
    #    setWebhook. Fails CLOSED: with no secret set we cannot prove a delivery
    #    is Telegram's, and this endpoint approves, executes and commands the
    #    agent, so an unverifiable call is refused rather than trusted. Telegram
    #    is the live ops channel and `render.yaml` generates the secret, so this
    #    only bites a deploy that forgot it. The sender allowlist below is a
    #    second gate — but on a chat id in the caller's OWN body; the secret is
    #    the one it cannot forge.
    expected = telegram.wire_secret()
    sent = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not (expected and hmac.compare_digest(sent, expected)):
        log.warning("telegram webhook: secret check failed — refused. "
                    "Set TELEGRAM_WEBHOOK_SECRET to enable the ops channel.")
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
              "gmail_alias", "shopify_store", "notes", "business_model"}
    if field not in JSON_FIELDS | SCALAR:
        return {"error": f"unknown field; allowed: {sorted(JSON_FIELDS | SCALAR)}"}
    if field == "business_model" and value:
        # Validated here as well as on create. A field settable through two
        # paths and checked on one is a field that will be set wrong through
        # the other, and a typo is silent until a client reads the report.
        from . import metrics
        if value not in metrics.OUTCOMES:
            return {"error": f"unknown business_model {value!r}",
                    "known": sorted(metrics.OUTCOMES)}
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
               kind: str = "client", domain: str = "",
               business_model: str = "") -> dict:
    """Create a new account. Seeding only covers the original five.

    /admin/tenant_add?key=SECRET&tenant=acme&name=Acme+Co&domain=acme.com
    Connections are attached afterwards with /admin/tenant_set.

    `business_model` decides which headline numbers this account's reports
    carry — a venue is measured in events booked, a store in average order
    value. Asked at CREATION rather than left to be noticed later, because the
    account that never gets one is the account whose first report says
    "business model not set" in front of the client.
    """
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    tenant = (tenant or "").strip().lower()
    if not tenant or not tenant.replace("_", "").replace("-", "").isalnum():
        return {"error": "tenant must be a short alphanumeric key, e.g. 'acme'"}
    if not name:
        return {"error": "name required"}
    from . import metrics, tenants
    business_model = (business_model or "").strip()
    if business_model and business_model not in metrics.OUTCOMES:
        # Refused rather than stored. A typo here is silent: the account is
        # created, looks fine, and its first report says "no outcomes for
        # 'ecomm_inventory'" weeks later in front of the client.
        return {"error": f"unknown business_model {business_model!r}",
                "known": sorted(metrics.OUTCOMES)}
    with db.SessionLocal() as s:
        if s.get(db.Tenant, tenant):
            return {"error": f"{tenant!r} already exists — use /admin/tenant_set"}
        s.add(db.Tenant(key=tenant, name=name, kind=kind, domain=domain,
                        business_model=business_model,
                        systems=[], notes="created via /admin/tenant_add"))
        s.commit()
    out = {"ok": True, "created": tenant, **tenants.resolve(tenant),
           "next": "attach connections with /admin/tenant_set, then seed its KB"}
    if not business_model:
        out["warning"] = (
            "no business_model set, so this account's reports carry no "
            "headline outcomes — set it with /admin/tenant_set")
        out["known_models"] = sorted(metrics.OUTCOMES)
    return out


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
             tab: str = "content", tenant: str = "",
             started: str = "") -> str:
    """The console. Opens on Review — the tab the day starts on (owner,
    2026-08-21: the fastest path to the actual work). It landed on
    Connections for historical reasons: that tab existed first."""
    if key != config.APPROVAL_SECRET:
        return "<h3>bad key</h3>"
    from . import admin_ui as ui
    # Once the session cookie carries the credential, stop threading it through
    # every link and hidden field — that propagation is what put it in browser
    # history in the first place. The forms still post `key=`, now empty, and
    # the cookie authenticates them.
    link_key = key if request.query_params.get("key") else ""
    if tab == "systems":
        return ui.render_systems(link_key, tenant)
    if tab == "kb":
        return ui.render_kb(link_key, tenant,
                            err=request.query_params.get("err", ""))
    if tab == "brand":
        return ui.render_brand(link_key, tenant,
                               msg=request.query_params.get("ok", ""),
                               err=request.query_params.get("err", ""))
    if tab == "assurance":
        try:
            days = int(request.query_params.get("days", "30"))
        except ValueError:
            days = 30
        return ui.render_assurance(link_key, tenant, days=max(1, min(days, 365)))
    if tab == "diagnostics":
        def _int(name: str, default: int, lo: int, hi: int) -> int:
            try:
                return max(lo, min(int(request.query_params.get(name, default)), hi))
            except ValueError:
                return default
        return ui.render_diagnostics(
            link_key, tenant,
            days=_int("days", 7, 1, 365),
            level=request.query_params.get("level", ""),
            system=request.query_params.get("system", ""),
            limit=_int("limit", 200, 10, 1000),
            live=_int("live", 0, 0, 300))
    if tab == "schema":
        return ui.render_schema(link_key, tenant)
    if tab == "content":
        try:
            cp = int(request.query_params.get("cpage", "1"))
        except ValueError:
            cp = 1
        return ui.render_content(link_key, tenant, started=started,
                                 err=request.query_params.get("err", ""),
                                 msg=request.query_params.get("ok", ""),
                                 cpage=cp)
    q = request.query_params
    return ui.render(link_key, tenant, msg=q.get("ok", ""), err=q.get("err", ""),
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
    # `covered_by` is set on a provider whose capability a sibling already
    # supplies — the second ESP, once they have one. It is dropped here rather
    # than shown greyed out: this page is a client's to-do list, and the only
    # honest length for it is the number of things still to do.
    needed = cred.needed_for(link.tenant)
    rows = [r for r in cred.status(link.tenant)
            if r["provider"] in needed and not r["covered_by"]]
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


def _oauth_shop(request: Request) -> tuple[str, str]:
    """The shop a shop-scoped flow is for, validated, or a reason it is not.

    Read from the query rather than a body because the connect page links here
    with the domain the client typed. Validation is `oauth.shop_host`, and the
    refusal names the shape rather than echoing the value back — an error page
    that reflects arbitrary input is its own small problem.
    """
    from . import credentials as _cred, oauth
    raw = str(request.query_params.get("shop", "")).strip()
    if not raw:
        return "", ("This connection needs the store's .myshopify.com domain. "
                    "Go back and enter it, then try again.")
    # The same normalisation a person gets when pasting into the API-key form,
    # so `admin.shopify.com/store/<handle>` works here too — then the gate.
    fixed, _why = _cred._normalize_meta("shopify", {"domain": raw})
    shop = oauth.shop_host(fixed.get("domain") or raw)
    if not shop:
        return "", ("That is not a myshopify.com store domain. It looks like "
                    "your-handle.myshopify.com — visible in your browser bar "
                    "as admin.shopify.com/store/your-handle.")
    return shop, ""


@app.get("/connect/{token}/oauth/{provider}")
def connect_oauth_start(token: str, provider: str, request: Request):
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
    # A shop-scoped flow needs to know WHICH shop before it can send anyone
    # anywhere — the consent screen lives on the merchant's own domain.
    shop = ""
    if oauth.FLOWS.get(provider, {}).get("shop_scoped"):
        shop, why = _oauth_shop(request)
        if why:
            return RedirectResponse(f"/connect/{token}?err={quote(why)}", 303)
    # PKCE where the provider demands it. The verifier rides encrypted inside
    # the signed state, so it survives the round trip without appearing in any
    # address bar — see `oauth.sign_state`.
    verifier, challenge = oauth._pkce_pair() if oauth.FLOWS.get(
        provider, {}).get("pkce") else ("", "")
    state = oauth.sign_state(link.tenant, provider, connect_token=token,
                             verifier=verifier, shop=shop)
    return RedirectResponse(
        oauth.authorize_url(provider, state, challenge, shop=shop), 303)


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
    shop = ""
    if oauth.FLOWS.get(provider, {}).get("shop_scoped"):
        shop, why = _oauth_shop(request)
        if why:
            return {"error": why}
    verifier, challenge = oauth._pkce_pair() if oauth.FLOWS.get(
        provider, {}).get("pkce") else ("", "")
    state = oauth.sign_state(tenant, provider, via="admin", verifier=verifier,
                             shop=shop)
    return RedirectResponse(
        oauth.authorize_url(provider, state, challenge, shop=shop), 303)


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

    # The provider's OWN signature, where the provider signs.
    #
    # `state` proves we started this flow; it does not prove who finished it.
    # It is a bearer value travelling in an address bar, through browser
    # history and any referrer, so replaying it with a chosen `code` is exactly
    # what the provider's signature closes. Checked before the code is spent.
    why = oauth.verify_callback(provider, dict(request.query_params))
    if why:
        return HTMLResponse(f"<h3>{html.escape(why)}</h3>", status_code=400)

    # A shop-scoped flow completes against the shop it STARTED with. Shopify
    # sends `shop` on the callback too, and taking it from there would let a
    # forged link begin for one store and finish against another — the token
    # would then be filed under a client who never authorised it.
    shop = str(data.get("shop") or "")
    if oauth.FLOWS.get(provider, {}).get("shop_scoped"):
        came_back = oauth.shop_host(str(request.query_params.get("shop", "")))
        if not shop or (came_back and came_back != shop):
            return HTMLResponse(
                "<h3>That sign-in came back for a different store than it "
                "started for. Nothing was connected — start again from the "
                "connect page.</h3>", status_code=400)
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

    # The verifier comes back out of the state it went in with.
    result = oauth.exchange(provider, code,
                            code_verifier=oauth.state_verifier(data),
                            shop=shop)
    if not result["ok"]:
        return RedirectResponse(f"{back}?err={quote(result['error'])}", 303)
    stored = cred.store_oauth(tenant, provider, result, granted_by=granted_by)
    if not stored["ok"]:
        return RedirectResponse(f"{back}?err={quote(stored['error'])}", 303)
    return RedirectResponse(f"{back}?ok={quote(stored['detail'])}", 303)


@app.get("/admin/memory")
def admin_memory(key: str = Depends(admin_key), tenant: str = "") -> dict:
    """What the agent currently believes, and what has been cleared.

    None of this was visible anywhere, which is how a stale note saying a
    breach may be under way went on inflating every security-shaped email for
    weeks. It is injected into every triage as current truth; a person has to
    be able to read it before they can retire it.
    """
    from . import memory
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    return {"tenant": tenant or "all",
            "working_memory": memory.working_notes(tenant),
            "cleared": memory.concerns(tenant),
            "note": "retire a note with /admin/forget_note?id=… — it stops "
                    "being injected immediately"}


@app.get("/admin/allclear")
def admin_allclear(key: str = Depends(admin_key), what: str = "",
                   because: str = "", tenant: str = "") -> dict:
    """"That was me / I have looked at it." Stops the same escalation recurring.

    Describe the EVENT, not the category: "the Klaviyo TOTP MFA added on 20 Aug
    was me" stays true for ever, while "ignore Authorize.net alerts" would
    suppress the carding attack that is actually happening. The injected block
    says so explicitly, so a new instance of the same kind of thing is still
    raised.
    """
    from . import memory
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    if not what:
        return {"error": "say what is cleared, e.g. "
                         "what=Klaviyo+TOTP+MFA+added+20+Aug&because=that+was+me"}
    return {"ok": True, "result": memory.clear_concern(what, because,
                                                       tenant=tenant)}


@app.get("/admin/forget_note")
def admin_forget_note(key: str = Depends(admin_key), id: str = "") -> dict:
    """Retire one working-memory note so it stops being injected."""
    from . import memory
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    return {"ok": True, "result": memory.retire(id)}


@app.get("/admin/sweep")
def admin_sweep(key: str = Depends(admin_key), tenant: str = "",
                days: int = 7, run: int = 0) -> dict:
    """What the nightly sweep would say, on demand.

    `run=1` delivers it to the queue as the scheduled job would; without it
    this only computes and returns, so it can be read a dozen times without
    filling the approval queue with duplicates.
    """
    from . import correlate
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    days = max(1, min(days, 90))
    if run:
        return correlate.nightly(days)
    if tenant:
        return {"tenant": tenant, "days": days,
                "findings": correlate.sweep(tenant, days)}
    from . import tenants as tn
    return {"days": days, "findings": [
        f for t in tn.all_tenants() for f in correlate.sweep(t.key, days)]}


@app.get("/admin/craft")
def craft_list(key: str = Depends(admin_key), tenant: str = "") -> dict:
    """Cross-client lessons: what is waiting, and what would reach one account.

    `tenant` shows what THAT account would actually see, which is the only way
    to check the reach rule by looking rather than by reasoning.
    """
    from . import craft
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    out = {"pending": craft.pending()}
    if tenant:
        out["would_reach"] = craft.for_account(tenant)
        out["tenant"] = tenant
    return out


@app.get("/admin/craft_add")
def craft_add(key: str = Depends(admin_key), lesson: str = "",
              business_model: str = "", situations: str = "",
              basis: str = "", learned_from: str = "") -> dict:
    """Propose a lesson. Refused by name if it identifies an account."""
    from . import craft
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    return craft.propose(
        lesson, business_model=business_model, basis=basis,
        learned_from=learned_from,
        situations=[s.strip() for s in situations.split(",") if s.strip()])


@app.get("/admin/craft_review")
def craft_review(key: str = Depends(admin_key), id: str = "",
                 approve: int = 1) -> dict:
    """Approve or retire one lesson. Re-checks the leak guard on the way in."""
    from . import craft
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    return craft.approve(id, approve_it=bool(approve))


@app.post("/webhooks/shopify/compliance")
async def shopify_compliance(request: Request):
    """Shopify's three mandatory privacy webhooks, on one endpoint.

    One URL for all three topics rather than three routes: the payloads differ
    but the verification, the recording and the "who is this shop" lookup are
    identical, and `X-Shopify-Topic` already says which arrived. Register the
    same URL against each of the three in the app config.

    The body is read as BYTES and verified before anything parses it — a digest
    over re-serialised JSON does not round-trip and would fail valid
    deliveries. An unverified request gets 401, which is what Shopify's own
    checks look for; answering 200 to whatever arrives is the failure the
    signature exists to prevent.
    """
    from fastapi.responses import JSONResponse

    from . import shopify_webhooks as swh

    raw = await request.body()
    if not swh.verify(raw, request.headers.get("X-Shopify-Hmac-Sha256", "")):
        return JSONResponse({"error": "unverified"}, status_code=401)

    topic = request.headers.get("X-Shopify-Topic", "")
    shop = request.headers.get("X-Shopify-Shop-Domain", "")
    try:
        payload = json.loads(raw or b"{}")
        if not isinstance(payload, dict):
            payload = {"_raw": str(payload)[:500]}
    except Exception:                                            # noqa: BLE001
        payload = {}

    # Never 500. Shopify retries a failed delivery for days, so an exception
    # here turns one malformed payload into a flood — and the request would
    # still be unrecorded, which is the half that matters legally.
    try:
        swh.handle(topic, shop, payload)
    except Exception:                                            # noqa: BLE001
        log.exception("shopify compliance webhook failed: %s", topic)
    return JSONResponse({"ok": True})


@app.get("/admin/privacy_requests")
def privacy_requests(key: str = Depends(admin_key), open_only: bool = True) -> dict:
    """What Shopify has asked us to do about somebody's data, and what is left.

    Thirty days is the deadline and the queue is the only proof it was worked,
    so this is a read of the record rather than a computation over it.
    """
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    with db.SessionLocal() as s:
        q = s.query(db.ComplianceEvent)
        if open_only:
            q = q.filter(db.ComplianceEvent.handled_at == None)  # noqa: E711
        rows = q.order_by(db.ComplianceEvent.created_at.desc()).limit(200).all()
        return {"open_only": open_only, "count": len(rows), "requests": [{
            "id": r.id, "at": db.as_utc(r.created_at).isoformat(),
            "topic": r.topic, "shop": r.shop, "tenant": r.tenant,
            "done_automatically": r.acted or [],
            "needs_a_person": r.needs_human or "",
        } for r in rows]}


@app.get("/admin/privacy_close")
def privacy_close(key: str = Depends(admin_key), id: str = "") -> dict:
    """Mark one privacy request handled, once a person has done it."""
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    with db.SessionLocal() as s:
        row = s.get(db.ComplianceEvent, id)
        if not row:
            return {"error": f"no privacy request {id!r}"}
        row.handled_at = db.utcnow()
        s.commit()
        return {"ok": True, "id": id, "topic": row.topic}


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
                   provider: str = "", site: str = "") -> dict:
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    from . import credentials as cred
    return {"result": cred.revoke(tenant, provider, site)}


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
                         str(form.get("provider", "")),
                         str(form.get("site", "")))
    return RedirectResponse(f"/admin/ui?tab=accounts&ok={quote(result)}", 303)


@app.post("/admin/connect_save")
async def connect_save(request: Request, key: str = Depends(admin_key)):
    """Connect one provider for one account, from the console.

    The owner could not do this. Every API-key provider on the Accounts tab
    said "client pastes this on their connect link" — so connecting your own
    Shopify meant minting a client link and using it yourself, or hand-editing
    a JSON blob in the Render environment.

    The fields arrive one per input and the shape is assembled here, which is
    what `credentials.store` has always wanted: it normalises the meta,
    validates the prefix, probes the live API and refuses to save what fails.
    Nobody should be composing `{"baci": {"domain": ..., "token": ...}}` by
    hand to connect a store.
    """
    from fastapi.responses import RedirectResponse
    from urllib.parse import quote

    from . import credentials as cred
    if key != config.APPROVAL_SECRET:
        return HTMLResponse("<h3>unauthorized</h3>", status_code=403)
    form = await request.form()
    tenant = str(form.get("tenant", ""))
    provider = str(form.get("provider", ""))
    spec = cred.PROVIDERS.get(provider)
    if not spec:
        return RedirectResponse(
            f"/admin/ui?tab=accounts&err={quote(f'unknown provider {provider}')}",
            status_code=303)

    meta = {f: str(form.get(f, "")) for f in spec["also"]}
    res = cred.store(tenant, provider, str(form.get("secret", "")),
                     meta=meta, granted_by="owner (console)")
    if res.get("ok"):
        msg = f"{spec['name']} connected for {tenant}"
        if res.get("detail"):
            msg += f" — {res['detail']}"
        return RedirectResponse(f"/admin/ui?tab=accounts&ok={quote(msg)}",
                                status_code=303)
    return RedirectResponse(
        f"/admin/ui?tab=accounts&err={quote(spec['name'] + ': ' + res['error'])}",
        status_code=303)


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
    site = str(form.get("site", ""))
    r = cred.recheck(tenant, provider, site)
    name = (cred.PROVIDERS.get(provider) or {}).get("name", provider)
    if r["ok"]:
        msg = (f"{name}{f' ({site})' if site else ''} still works"
               + (f" — {r['detail']}" if r.get("detail") else ""))
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
                 approve: str = "yes", tenant: str = "", ui: str = "",
                 next: str = "", cpage: int = 1):
    """Approve or reject a client-submitted claim. From the console (`ui=1`)
    it lands back at the next card on the same queue page rather than at the
    top — a decision must never cost the reader their place."""
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    from . import kb as kbm
    res = kbm.review_claim(claim_id, approve == "yes")
    if ui:
        return _back_to_content(tenant,
                                anchor=(f"c-{next}" if next else "proposals"),
                                cpage=cpage)
    return {"result": res}


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


@app.get("/admin/calibrate_classify")
def calibrate_classify(key: str = Depends(admin_key), tenant: str = "") -> dict:
    """Are the classifier's floors right for this account's real claims?

    Leave-one-out over every approved, human-tagged claim. Reads only — no row
    is written and no floor is changed; moving one is an edit to
    `kb.MIN_SHARED_WORDS` / `kb.MIN_LEARNED_SCORE` after reading `sweep`.

    Omit `tenant` for every account at once. Read `n` before any percentage:
    under `min_n` the numbers are real but the conclusion is not.
    """
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    from . import kb as kbm, tenants as tn
    keys = [tenant] if tenant else [t.key for t in tn.all_tenants()]
    out, total = {}, 0
    for k in keys:
        try:
            res = kbm.calibration(k)
        except Exception as exc:  # noqa: BLE001 — one bad account must not
            out[k] = {"error": f"{exc.__class__.__name__}: {exc}"}
            continue
        total += res["n"]
        out[k] = res
    return {"accounts": out, "total_tagged_claims": total,
            "enough_to_calibrate": total >= kbm.CALIBRATION_MIN_N,
            "read_only": True}


@app.get("/admin/answer")
def admin_answer(key: str = Depends(admin_key), tenant: str = "", q: str = "",
                 entity: str = "", contact_id: str = "",
                 system: str = "service_desk") -> dict:
    """Answer a real customer question from what this account actually knows.

    resolve -> assemble -> validate -> ledger, with no model call in it. An
    approved objection already carries the response a human signed off, so
    this is retrieval and validation rather than authorship.

    Returns a DRAFT and files it. Nothing is sent — publishing is a separate
    act, so the default stays shadow.

    Read `blocked_on` when it refuses: every refusal names the field that would
    unblock it, and is recorded so the gap gets counted rather than forgotten.
    """
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    if not (tenant and q):
        return {"error": "need tenant= and q="}
    from . import responder
    return responder.answer(tenant, q, entity_key=entity,
                            contact_id=contact_id, system_key=system)


@app.get("/admin/ledger")
def admin_ledger(key: str = Depends(admin_key), tenant: str = "",
                 system: str = "", limit: int = 20) -> dict:
    """What this account has produced, and what stopped when it did not."""
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    if not tenant:
        return {"error": "need tenant="}
    from . import ledger as lg
    rows = lg.recent(tenant, system_key=system, limit=limit)
    return {
        "tenant": tenant, "outputs": len(rows),
        "rows": [{"id": r.id, "system": r.system_key, "status": r.status,
                  "situation": r.situation, "entity_key": r.entity_key,
                  "claim_ids": r.claim_ids, "objection_id": r.objection_id,
                  "blocked_on": r.blocked_on, "body": (r.body or "")[:160],
                  "created_at": r.created_at, "published_at": r.published_at}
                 for r in rows],
        "hygiene": lg.unused_claims(tenant),
    }


@app.get("/admin/propose_voice")
def propose_voice(key: str = Depends(admin_key), tenant: str = "",
                  limit: int = 25) -> dict:
    """Suggest a brand voice from what this account has already published.

    Reads their site, measures the countable half (sentence length,
    contractions, second person, questions), and asks for tone words backed by
    **verbatim** exemplar sentences — every one checked against the source, so
    a quote nobody wrote is discarded before you see it.

    Samples are filtered through `banned_claims` first: deriving voice from a
    page that says "hand-painted in Italy" would hand back exemplars the brand
    is barred from using.

    **Writes nothing.** `set_brand` is still the only way a voice lands, and a
    person still types it.
    """
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    if not tenant:
        return {"error": "name a tenant — this one crawls, so it is per account"}
    from . import voice as vc
    texts, how = vc.gather(tenant, limit=limit)
    if not texts:
        return {"tenant": tenant, "error": how, "applied": False}
    out = vc.propose(tenant, texts)
    out["source"] = how
    return out


@app.get("/admin/repair_fingerprints")
def repair_fingerprints(key: str = Depends(admin_key), tenant: str = "",
                        apply: int = 0) -> dict:
    """Rewrite claim fingerprints so dedup starts working again.

    `update_claim` computed `fingerprint(claim)` where `add_claim` computes
    `fingerprint(claim, entity_key)`, so any edited row stopped matching a
    fresh add of the same claim on the same product — and got filed twice.
    Reports by default; `apply=1` writes.

    Merges nothing. Duplicate groups are reported for a human to resolve from
    `/admin/label_conflicts`, because the surviving row's id is what every
    objection's `claim_id` still points at.
    """
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    from . import kb as kbm, tenants as tn
    keys = [tenant] if tenant else [t.key for t in tn.all_tenants()]
    out = {}
    for k in keys:
        try:
            out[k] = kbm.repair_fingerprints(k, apply=bool(apply))
        except Exception as exc:  # noqa: BLE001
            out[k] = {"error": f"{exc.__class__.__name__}: {exc}"}
    return {"accounts": out, "applied": bool(apply)}


@app.get("/admin/label_conflicts")
def label_conflicts(key: str = Depends(admin_key), tenant: str = "",
                    min_score: float = 0.0) -> dict:
    """Near-identical claims your account tagged differently.

    The queue that fixes calibration rather than chasing it. A classifier
    cannot beat the labels it learns from, and three of Baci's four "wrong"
    placements were one pair of claims saying the same thing under opposite
    tags — the worst at 0.9672, higher than most correct placements, so no
    threshold anywhere separates them.

    Reported, never merged: which tag is right is a judgement about the
    business. Reads only, and costs no provider call.
    """
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    from . import kb as kbm, tenants as tn
    floor = min_score or kbm.LABEL_CONFLICT_SCORE
    keys = [tenant] if tenant else [t.key for t in tn.all_tenants()]
    out, total = {}, 0
    for k in keys:
        try:
            rows = kbm.label_conflicts(k, min_score=floor)
        except Exception as exc:  # noqa: BLE001
            out[k] = {"error": f"{exc.__class__.__name__}: {exc}"}
            continue
        total += len(rows)
        out[k] = {"conflicts": len(rows), "pairs": rows}
    return {"min_score": floor, "accounts": out, "total": total,
            "read_only": True,
            "note": ("each pair is one tagging decision to make; fixing it "
                     "improves every future placement, which moving a floor "
                     "cannot")}


@app.get("/brand.md", response_class=PlainTextResponse)
def brand_markdown(request: Request, auth: str = Depends(read_key),
                   tenant: str = "", system: str = "") -> str:
    """This account's knowledge base, compiled into a document you can paste.

    The layer supporting the `.md` approach rather than competing with it. At
    a corpus this size a cached document beats per-question retrieval — it is
    nearly free after the first call and it cannot surface the wrong thing,
    because everything is present.

    What it adds over a hand-written file is that it is generated from
    APPROVED rows only, regenerates itself, and carries the same ban list the
    validator enforces on the way out — so what a drafter was told and what it
    will be held to cannot drift apart.

    `?system=service_desk|creative|campaign_email|lead_responder` narrows it.
    Sections run stable-first so the prompt cache actually hits; the volatile
    catalogue is last for the same reason.
    """
    if not auth:
        return "unauthorized"
    if not tenant:
        return "name an account: /brand.md?tenant=baci"
    from . import dossier
    doc = dossier.build(tenant, system)
    if doc.get("error"):
        return doc["error"]
    return doc["markdown"]


@app.get("/brand_meta")
def brand_markdown_meta(request: Request, auth: str = Depends(read_key),
                        tenant: str = "", system: str = "") -> dict:
    """Size, etag and cache advice for the document, without the document.

    The etag IS the cache key: re-fetch this, compare, and skip the model call
    entirely when nothing has changed. `within_context_budget` is the crossover
    signal — when it goes false, that surface should move to /resolve.
    """
    if not auth:
        return {"error": "unauthorized"}
    if not tenant:
        return {"error": "need tenant="}
    from . import dossier
    doc = dossier.build(tenant, system)
    doc.pop("markdown", None)
    return doc


@app.get("/admin/archive_attachments")
def archive_attachments(key: str = Depends(admin_key), tenant: str = "",
                        limit: int = 50) -> dict:
    """Pull the documents that arrived ON threads, and keep what they say.

    `read_email_attachment` has extracted PDF text on demand for months and
    returned it into a chat that ends — so the same bill of lading was
    re-parsed for every question and none of it was searchable. Worse, an agent
    had to SUSPECT an attachment mattered before it would look; if it did not,
    it asked a human.

    Filed against the thread it came on, so "what was attached to the
    conversation where we agreed the credit" becomes a query.
    """
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    if not tenant:
        return {"error": "need tenant="}
    from . import archive
    return archive.fetch_attachments(tenant, limit=limit)


@app.get("/admin/threads")
def admin_threads(key: str = Depends(admin_key), tenant: str = "",
                  pick: str = "", q: str = "", limit: int = 25,
                  full: int = 0) -> dict:
    """What is actually in this inbox's archive, so you can look at it.

    Search answers "find me the one about X" and `draft_test` shows the ones it
    happened to choose. Neither lets you browse, and until you can see what is
    in there you cannot tell a thin archive from a thin filter.

    `by_bucket` first, because that is the shape of the account: it tells you
    what `pick=` is worth trying and how much of the inbox is noise. Each row
    carries its `message_id` so it can be handed straight to `draft_test`.

    `indexed` is the one that matters — a row can hold a body and still be
    unsearchable if nothing embedded it.
    """
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    if not tenant:
        return {"error": "need tenant="}
    from . import archive, embed

    with db.SessionLocal() as s:
        base = s.query(db.EmailLog).filter(db.tenant_filter(db.EmailLog, tenant))
        by_bucket: dict[str, dict] = {}
        for r in base.all():
            b = by_bucket.setdefault(r.category or "(unclassified)",
                                     {"total": 0, "with_body": 0})
            b["total"] += 1
            if (r.body_excerpt or "").strip():
                b["with_body"] += 1

        rows_q = base
        if pick:
            rows_q = rows_q.filter(db.EmailLog.category == pick)
        if q:
            like = f"%{q}%"
            rows_q = rows_q.filter(db.EmailLog.subject.ilike(like))
        rows = rows_q.order_by(db.EmailLog.seen_at.desc()).limit(limit).all()
        s.expunge_all()

    indexed = {e.row_id.split("#")[0] for e in embed.BACKEND.rows(tenant, "thread")}
    out = []
    for r in rows:
        body = (r.body_excerpt or "").strip()
        ok, why = archive.indexable(r.category or "", r.sender or "", body or "x" * 999)
        out.append({
            "message_id": r.gmail_message_id,
            "subject": r.subject or "(no subject)",
            "from": r.sender or "",
            "bucket": r.category or "",
            "when": r.seen_at,
            "has_body": bool(body),
            "indexed": r.id in indexed,
            "would_keep": ok,
            "skipped_because": "" if ok else why,
            "excerpt": body if full else body[:220],
        })

    return {
        "tenant": tenant,
        "by_bucket": dict(sorted(by_bucket.items(),
                                 key=lambda kv: -kv[1]["total"])),
        "shown": len(out),
        "threads": out,
        "how_to": ("pass a message_id to /admin/draft_test to rehearse a reply "
                   "to that exact thread; add full=1 here to read one whole"),
    }


@app.get("/admin/draft_test")
def draft_test(key: str = Depends(admin_key), tenant: str = "",
               message_id: str = "", pick: str = "", limit: int = 3) -> dict:
    """Draft a reply to a REAL thread from this inbox, and show the working.

    The rehearsal that answers "would this have been any good". Names a
    message, or `pick=` a bucket and it takes the most recent that has a body.

    Nothing is sent and nothing is filed as a draft on the thread — this
    produces text and the validator's verdict on it, so a rehearsal can be
    read and thrown away.
    """
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    if not tenant:
        return {"error": "need tenant="}
    from . import responder

    with db.SessionLocal() as s:
        q = (s.query(db.EmailLog)
             .filter(db.tenant_filter(db.EmailLog, tenant),
                     db.EmailLog.body_excerpt.isnot(None)))
        if message_id:
            q = q.filter(db.EmailLog.gmail_message_id == message_id)
        if pick:
            q = q.filter(db.EmailLog.category == pick)
        rows = q.order_by(db.EmailLog.seen_at.desc()).limit(limit).all()
        s.expunge_all()

    if not rows:
        return {"error": "no thread with a stored body matches — run "
                         "/admin/archive_fetch first, or widen `pick`"}

    out = []
    for r in rows:
        body = (r.body_excerpt or "").strip()
        res = responder.answer(tenant, body[:2000],
                               system_key="service_desk",
                               draft_with_model=True)
        out.append({
            "thread": {"subject": r.subject, "from": r.sender,
                       "bucket": r.category, "when": r.seen_at,
                       "they_wrote": body[:400]},
            "mode": res.get("mode") or res.get("stage") or "answered",
            "grounding": (res.get("grounding") or {}).get("level"),
            "draft": res.get("draft") or "",
            "blocked": res.get("draft_blocked_by") or res.get("blocked_on") or "",
            "validated": res.get("validated"),
            "checks_run": res.get("checks_run", []),
            "prior_threads_used": [
                h.get("subject") for h in
                ((res.get("bundle") or {}).get("correspondence")
                 or (res.get("context") or {}).get("correspondence") or [])],
            "gaps": [g.get("missing") for g in (res.get("gaps") or [])],
        })
    return {"tenant": tenant, "tested": len(out), "results": out,
            "note": ("nothing was sent and nothing was filed on the thread. "
                     "Read `blocked` — a draft the validator threw away is "
                     "the system working, not failing.")}


@app.get("/admin/archive_fetch")
def archive_fetch(key: str = Depends(admin_key), tenant: str = "",
                  limit: int = 200) -> dict:
    """Fetch what old threads said, for rows logged before there was a column.

    `/admin/archive_index` finds nothing to embed on a mature account because
    every historical `EmailLog` row holds sender and subject and no body. This
    fills them from Gmail, then the index route embeds what landed.

    The bucket filter runs BEFORE the network call — triage decided months ago
    that a blast was a blast, and re-learning it costs an API round trip.
    """
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    if not tenant:
        return {"error": "need tenant="}
    from . import archive
    return archive.backfill_bodies(tenant, limit=limit)


@app.get("/admin/archive_index")
def archive_index(key: str = Depends(admin_key), tenant: str = "",
                  kind: str = "thread", limit: int = 200) -> dict:
    """Make this account's correspondence answerable instead of catalogued.

    `EmailLog` recorded that a message arrived and not a word of what it said;
    `DocIndex` recorded that a bill of lading exists and not what was on it. So
    an agent asked to reference a prior thread could only ask or guess — which
    looks like a stupid model and is a storage problem.

    Reports `no_text_stored` separately: rows that are catalogued but hold no
    body are findable by subject and unanswerable in content, and that count is
    the size of the remaining gap.
    """
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    if not tenant:
        return {"error": "need tenant="}
    from . import archive
    return archive.index(tenant, kind=kind, limit=limit)


@app.get("/archive_search")
def archive_search(request: Request, auth: str = Depends(read_key),
                   tenant: str = "", q: str = "", limit: int = 5) -> dict:
    """Find prior correspondence by MEANING, with coverage stated.

    "The pallet damage" and "the broken crates from the March shipment" are the
    same event with no words in common — the case keyword search returns
    nothing for, and the agent then asks a question it should not have needed
    to ask.
    """
    if not auth:
        return {"error": "unauthorized"}
    if not (tenant and q):
        return {"error": "need tenant= and q="}
    from . import archive
    return archive.search(tenant, q, limit=limit)


@app.get("/admin/tenant_reset")
def tenant_reset(key: str = Depends(admin_key), tenant: str = "",
                 groups: str = "knowledge,operations", apply: int = 0) -> dict:
    """Empty ONE account, showing the damage before doing it.

    Wiping the whole database to rehearse onboarding does not work:
    `tenants.seed()` puts the five accounts back and `kb_seed` repopulates
    three of them from hardcoded facts, ban lists included. You get a
    pre-filled Baci, not a blank client.

    Reports by default. `apply=1` deletes. `groups=` is any of
    knowledge | operations | access — and **access is excluded by default**,
    because deleting credentials makes your client redo OAuth rather than
    making work for you.

    Refuses an empty tenant: that is UNASSIGNED, and deleting on it would
    erase every unattributed row in the system.
    """
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    from . import reset as rs_reset
    picked = tuple(g.strip() for g in groups.split(",") if g.strip())
    return rs_reset.reset(tenant, groups=picked, apply=bool(apply))


@app.post("/propose")
async def propose_row(request: Request, auth: str = Depends(read_key)) -> dict:
    """An agent filing what it did NOT know, with its best answer attached.

    POST because it writes, unlike most of this console — the GET-that-mutates
    debt in DEFECTS is not worth adding to, and a browser prefetch must never
    file a proposal.

    Body: {tenant, kind: objection|claim|situation, ...fields}. Nothing lands
    usable: `origin="agent"` is not in AUTO_APPROVED, so every row written here
    is PROPOSED and invisible to selection until a human approves it.

    This is the alternative to asking. A question in an inbox gets answered
    once and kept nowhere; a proposal gets approved once and answers every
    future system.
    """
    if not auth:
        return {"error": "unauthorized"}
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return {"error": "send a JSON body"}

    from . import propose as pr
    tenant = (body.get("tenant") or "").strip()
    kind = (body.get("kind") or "").strip()
    if not tenant:
        return {"error": "need tenant"}
    ref = body.get("source_ref") or ""

    if kind == "objection":
        return pr.objection(tenant, body.get("question", ""),
                            body.get("answer", ""), source_ref=ref,
                            situations=body.get("situations") or [],
                            entity_key=body.get("entity_key", ""))
    if kind == "claim":
        return pr.claim(tenant, body.get("claim", ""), body.get("evidence", ""),
                        source_ref=ref,
                        situations=body.get("situations") or [],
                        entity_key=body.get("entity_key", ""))
    if kind == "situation":
        return pr.situation(tenant, body.get("tag", ""),
                            body.get("description", ""), source_ref=ref)
    return {"error": "kind must be objection, claim or situation"}


@app.get("/readiness")
def readiness(request: Request, auth: str = Depends(read_key),
              tenant: str = "") -> dict:
    """Which clients this layer can actually serve, and what to fix first.

    `/resolve` answers whether ONE request can be grounded. This answers how
    many can, before anything is sent — the question an agency onboarding a
    client is really asking.

    Probes each account against its OWN situation vocabulary rather than
    invented questions, and ranks the fixes by how many situations each one
    unblocks. Counting rows: no model call, no network.
    """
    if not auth:
        return {"error": "unauthorized"}
    from . import resolve as rs, tenants as tn
    keys = [tenant] if tenant else [t.key for t in tn.all_tenants()]
    out, ready = {}, 0
    for k in keys:
        try:
            r = rs.readiness(k)
        except Exception as exc:  # noqa: BLE001
            out[k] = {"error": f"{exc.__class__.__name__}: {exc}"}
            continue
        ready += bool(r["answerable"])
        out[k] = r
    return {"accounts": out, "accounts_that_can_answer_anything": ready,
            "of": len(keys),
            "note": ("a situation is 'answerable' when an approved objection "
                     "carries that tag, and 'proven' when a claim backs it")}


@app.get("/embed_status")
def embed_status(request: Request, auth: str = Depends(read_key),
                 tenant: str = "") -> dict:
    """Is scanning vectors in process still the right answer?

    The case for keeping vectors in Postgres instead of an index is a claim
    about size, and a claim about size needs a number. This is that number:
    how many vectors exist, how long scanning all of them takes, and how much
    headroom is left before a `Backend` swap is worth measuring.

    Read-gated rather than admin-gated — it carries no client content, and a
    monitor that has to hold the console secret to watch a threshold is the
    problem the read key exists to solve.
    """
    if not auth:
        return {"error": "unauthorized"}
    from . import embed
    return embed.stats(tenant)


@app.get("/admin/embed_backfill")
def embed_backfill(key: str = Depends(admin_key), tenant: str = "",
                   kind: str = "claim", report_only: int = 1) -> dict:
    """Index this account's rows for semantic recall.

    `report_only=1` (the default) says what WOULD be embedded and what it would
    cost, without calling the provider. Drop it to actually write.

    Approving a claim already embeds it, so this is for the backlog that
    existed before the semantic path did — and for re-indexing after a model
    change, which invalidates every stored vector because cosine between two
    models is a number with no meaning.
    """
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    from . import embed, kb as kbm, tenants as tn
    if kind not in embed.KINDS:
        return {"error": f"kind must be one of {', '.join(embed.KINDS)}"}
    keys = [tenant] if tenant else [t.key for t in tn.all_tenants()]

    out, planned = {}, 0
    for k in keys:
        if kind == "claim":
            # `claims()` with no entity_key returns BRAND-level rows only —
            # that default is right for selection (a fact true of one product
            # must not turn up in a newsletter about another) and wrong here,
            # where the job is to index everything so retrieval can scope it
            # later. On an account with 251 entities that quietly skipped most
            # of the corpus. `claim_inventory` is the unscoped, approved set.
            items = [(r.id, f"{r.claim} {r.evidence or ''}".strip())
                     for r in kbm.claim_inventory(k)["selectable"]]
        elif kind == "objection":
            items = [(r.id, f"{r.objection} {r.response or ''}".strip())
                     for r in kbm.objections(k, any_entity=True)]
        elif kind == "entity":
            items = [(r.id, f"{r.name} {r.description or ''}".strip())
                     for r in kbm.entities(k, available_only=False)]
        else:
            items = []
        if report_only:
            stale = [i for i, t in items
                     if embed.BACKEND.hash_for(k, kind, i) != embed.text_hash(t)]
            planned += len(stale)
            out[k] = {"rows": len(items), "would_embed": len(stale)}
        else:
            out[k] = embed.backfill(k, kind, items)
    ok, why = (True, "") if report_only else embed.available()
    return {"kind": kind, "accounts": out, "report_only": bool(report_only),
            "would_embed_total": planned if report_only else None,
            "provider_available": ok, "provider_note": why}


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


@app.get("/admin/system_on")
def system_on(key: str = Depends(admin_key), system: str = "",
              tenant: str = "", install: int = 0, off: int = 0) -> dict:
    """Switch one system on (or off) across accounts, BY NAME.

    `system_set` takes a system's uuid, which means turning one thing on for
    five accounts is five lookups and five calls — enough friction that it does
    not get done, which is how `content_compliance` sat switched off with a
    working scanner behind it.

    Reports per account and REFUSES BY NAME: going live is gated on readiness,
    so an account with no ban list is told that rather than silently skipped.
    Those refusals are the useful half of the output — they are the list of
    what to go and fix.

    `install=1` creates the system where it is missing. Off by default, because
    installing is a decision and a route that quietly installs across every
    account is how somebody finds a pipeline they never chose.
    `off=1` pauses instead, using the same addressing.
    """
    from . import systems, tenants as tn
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    if not system:
        return {"error": "name a system, e.g. ?system=content_compliance",
                "known": sorted(systems.CATALOG)}
    if system not in systems.CATALOG:
        return {"error": f"unknown system {system!r}",
                "known": sorted(systems.CATALOG)}

    want = [tn.get(tenant)] if tenant else tn.all_tenants()
    want = [t for t in want if t]
    if not want:
        return {"error": f"unknown account {tenant!r}"}

    out: dict[str, str] = {}
    for t in want:
        row = systems.find(t.key, system)
        if not row:
            if not install:
                out[t.key] = ("not installed — add &install=1 if it should be")
                continue
            row = systems.create(t.key, system)
        if off:
            systems.update(row.id, status="paused")
            out[t.key] = "paused"
            continue
        res = systems.update(row.id, status="live")
        if res.get("error"):
            # Named, not swallowed. "not ready to go live" alone sends nobody
            # anywhere; the blockers say which connection or which knowledge.
            out[t.key] = f"{res['error']}: " + "; ".join(res.get("blockers", []))
        else:
            out[t.key] = "live"
    return {"system": system, "accounts": out,
            "note": "refusals name what is missing — that list is the work"}


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


# ---------------------------------------------------------------------------
# The skill bridge.
#
# These four routes exist so a Claude skill — the Coverings trio, the marketing
# pack, anything authored later — can run on this data layer instead of on a
# workbook it keeps its own copy of.
#
# The design constraint that shaped them: handing a skill the knowledge and
# letting it draft in its own session takes the draft OUTSIDE `Context.emit`,
# and `emit` is the only reason any of this is safe. The validator, the ledger
# and the autonomy rung would all be bypassed silently — banned claims
# unenforced, no record the output existed, nothing for anti-repeat to read.
#
# So the bridge is not "read the KB". It is read → draft → **come back through
# the gate**. `/admin/agent_context` hands over the brief and states the
# obligation in the payload; `/admin/agent_emit` is the gate, and returns
# `may_send` rather than the draft, so a skill that skips it has nothing to
# quote as permission.
#
# What the bundle contains is already safe: `kb.claims` and `kb.objections`
# both filter on `review == APPROVED`, so nothing in review can reach a
# customer through here.
# ---------------------------------------------------------------------------

@app.get("/admin/collections_sync")
def collections_sync(key: str = Depends(admin_key), tenant: str = "",
                     adopt: str = "", dry_run: str = "") -> dict:
    """Import Shopify collections as groups. `adopt` is a comma-separated list.

    Call it once with no `adopt` to see what exists, then again naming the
    collections that are genuine product ranges.
    """
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    from . import catalog_sync
    if not tenant:
        return {"error": "tenant is required"}
    return catalog_sync.sync_collections(
        tenant, adopt=[a for a in adopt.split(",") if a.strip()],
        dry_run=bool(dry_run))


@app.get("/admin/entity_group")
def entity_group(key: str = Depends(admin_key), tenant: str = "",
                 entity: str = "", group: str = "") -> dict:
    """Add one entity to a group by hand, or clear its groups with an empty one.

    Membership is additive and an entity may sit in several: its range, its
    material, its type. Adding one never removes another.

    The manual path for what the collection import cannot decide: a product in
    several collections, a range that is not a Shopify collection at all, or a
    grouping that only makes sense to a person.

    Both arguments go through `resolve_entity_ref`, so either can be given as a
    key, a display name, or a unique partial of one.
    """
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    from . import kb as kbm
    if not tenant or not entity:
        return {"error": "tenant and entity are required"}
    ekey, problem = kbm.resolve_entity_ref(tenant, entity)
    if problem or not ekey:
        return {"error": problem or f"no entity matched {entity!r}"}
    gkey = ""
    if group:
        gkey, gproblem = kbm.resolve_entity_ref(tenant, group)
        if gproblem or not gkey:
            return {"error": gproblem or f"no group matched {group!r}"}
    result = (kbm.join_group(tenant, ekey, gkey) if gkey
              else kbm.leave_group(tenant, ekey))
    return {"entity": ekey, "group": gkey, "result": result,
            "groups": kbm.ancestors(tenant, ekey)}


@app.post("/admin/entity_group")
async def entity_group_post(request: Request, key: str = Depends(admin_key)):
    """Put SEVERAL entities into one group, from the console.

    `kb.assign_to_group` has existed since the scope work and had no caller at
    all — the only way to group anything was one `/admin/entity_group?...` GET
    per product, which for a forty-item range is forty URLs pasted by hand, and
    is why the manual path was never actually used.

    POST because this mutates. The GET twin stays for the runbook, but a
    console write on a GET can be fired by a browser prefetch or a link
    preview, and this one rewrites what claims apply to what.
    """
    from fastapi.responses import RedirectResponse
    from urllib.parse import quote

    from . import kb as kbm
    if key != config.APPROVAL_SECRET:
        return HTMLResponse("<h3>unauthorized</h3>", status_code=403)
    form = await request.form()
    tenant = str(form.get("tenant", ""))
    group = str(form.get("group", "")).strip()
    keys = [str(k) for k in form.getlist("entity_keys") if str(k).strip()]

    def back(msg: str = "", err: str = "") -> RedirectResponse:
        q = f"&ok={quote(msg)}" if msg else (f"&err={quote(err)}" if err else "")
        return RedirectResponse(
            f"/admin/ui?tab=kb&tenant={quote(tenant)}{q}#groups", 303)

    if not tenant or not group:
        return back(err="Pick a group first.")
    if not keys:
        return back(err="Nothing was selected, so nothing was grouped.")

    gkey, problem = kbm.resolve_entity_ref(tenant, group)
    if problem or not gkey:
        return back(err=problem or f"no group matched {group!r}")

    res = kbm.assign_to_group(tenant, gkey, keys)
    # The refusals are the interesting half — a loop guard, a missing entity, a
    # row already in the group — and dropping them would report a partial
    # success as a whole one.
    msg = f"{res['assigned']} of {len(keys)} added to {gkey}"
    if res["refused"]:
        return back(err=msg + " — " + "; ".join(res["refused"][:3]))
    return back(msg=msg + ".")


@app.get("/admin/scope_conflicts")
def scope_conflicts_route(key: str = Depends(admin_key), tenant: str = "") -> dict:
    """Claims that answer the same situation at different scopes.

    Reported, never resolved — the narrower one is selected either way, and
    whether that is a refinement or a contradiction is a judgement.
    """
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    from . import kb as kbm
    if not tenant:
        return {"error": "tenant is required"}
    rows = kbm.scope_conflicts(tenant)
    return {"tenant": tenant, "count": len(rows), "conflicts": rows}


@app.get("/admin/creative")
def creative(key: str = Depends(admin_key), tenant: str = "", asset: str = "",
             prompt: str = "", shape: str = "square", mode: str = "scene",
             headline: str = "", subline: str = "", inspiration: str = "",
             background: str = "#EFEAE3", fmt: str = "1:1"):
    """Make one creative and return the PNG itself, so curl can save it.

    Returning the image rather than JSON is the point: a 1024px frame as a
    base64 blob in a terminal is something you cannot look at, and looking at
    it is the entire test.

        curl "…/admin/creative?key=…&tenant=baci&asset=<id>&prompt=…" -o ad.png

    `mode=scene`  generates the surroundings with the product masked, so its
                  pixels come back as sent.
    `mode=flat`   composites the product onto a brand colour. No model, no key,
                  nothing to go wrong.
    """
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    from fastapi.responses import Response

    from . import compose, imagegen, kb as kbm
    if not tenant or not asset:
        return {"error": "tenant and asset are both required — asset is a "
                         "KbAsset id from the creative library"}

    if mode == "flat":
        res = compose.product_on_colour(
            tenant, asset, headline=headline or prompt, subline=subline,
            background=background, formats=[fmt])
        if not res["ok"]:
            return {"error": res["error"]}
        return Response(content=res["images"][fmt], media_type="image/png",
                        headers={"X-Font-Used": res["font"],
                                 "X-Treatment": "product_on_colour"})

    # Scene: the product's own pixels, generated surroundings.
    ok, why = kbm.may_publish(asset)
    if not ok:
        return {"error": f"that asset cannot be used: {why}"}
    with db.SessionLocal() as s:
        row = s.get(db.KbAsset, asset)
        if not row or row.tenant != tenant:
            return {"error": "no such asset for this account"}
        url = row.url
    import httpx
    try:
        got = httpx.get(url, timeout=60, follow_redirects=True)
        got.raise_for_status()
    except Exception as exc:                                     # noqa: BLE001
        return {"error": f"could not fetch the product image: "
                         f"{exc.__class__.__name__}"}

    res = imagegen.place_product(got.content, prompt or "a bright, simple "
                                 "table setting", shape=shape, n=1,
                                 inspiration=inspiration)
    if not res["ok"]:
        return {"error": res.get("error", "generation failed")}
    best = res["candidates"][0]
    return Response(content=best["image"], media_type="image/png",
                    headers={"X-Similarity": str(best["similarity"]),
                             "X-Protected": "product masked — pixels as sent",
                             "X-Caveat": "similarity is a diagnostic, not a gate"})


@app.post("/admin/assets_decide", response_class=HTMLResponse)
async def assets_decide(request: Request, key: str = Depends(admin_key)):
    """Approve or reject pictures, many at a time.

    The crawler files fifty-six images from one site. Deciding those one
    request at a time is the same failure the claim queue had, and the same
    fix: a checkbox per card bound to one form.
    """
    from . import kb as kbm
    if key != config.APPROVAL_SECRET:
        return HTMLResponse("<h3>unauthorized</h3>", status_code=403)
    form = await request.form()
    tenant = str(form.get("tenant", ""))
    action = str(form.get("action", ""))
    ids = [str(i) for i in form.getlist("asset_ids") if str(i).strip()]
    if not ids:
        return _back_to_content(tenant, msg="no pictures were selected")
    approve = action == "approve"
    for aid in ids:
        kbm.review_asset(aid, approve=approve)
    verb = "approved" if approve else "rejected"
    return _back_to_content(tenant, msg=f"{verb} {len(ids)} picture(s)",
                            anchor="pics")


@app.post("/admin/asset_add", response_class=HTMLResponse)
async def asset_add(request: Request, key: str = Depends(admin_key)):
    """Put a photograph into the creative library.

    Until now the only way in was a Shopify sync, which is fine for Baci and
    useless for every client that does not sell products — Ironside's venue
    photographs and Coverings' installation shots have no store to come from,
    so the creative path was unreachable for exactly the accounts the
    photograph-based treatment was built for.

    `rights` is required and has no default here either. The whole point of
    that axis is that a competitor's shot and a client's own look identical.
    """
    from fastapi.responses import RedirectResponse
    from urllib.parse import quote

    from . import kb as kbm
    if key != config.APPROVAL_SECRET:
        return HTMLResponse("<h3>unauthorized</h3>", status_code=403)
    form = await request.form()
    tenant = str(form.get("tenant", ""))
    url = str(form.get("url", "")).strip()
    rights = str(form.get("rights", ""))

    subject = str(form.get("subject", "")).strip()
    if url and not subject:
        # Guess from the pixels rather than making somebody choose on every
        # upload — a cutout is an object, anything else is safest as a scene.
        try:
            import httpx
            got = httpx.get(url, timeout=30, follow_redirects=True)
            got.raise_for_status()
            subject = kbm.detect_subject(got.content)
        except Exception:                                        # noqa: BLE001
            subject = kbm.SCENE

    ent = str(form.get("entity_key", "")).strip()
    if ent:
        ent, problem = kbm.resolve_entity_ref(tenant, ent)
        if problem:
            return _back_to_content(tenant, err=problem)

    said = kbm.add_asset(tenant, url, rights=rights,
                         title=str(form.get("title", "")),
                         kind=str(form.get("kind", "image")),
                         subject=subject, entity_key=ent,
                         source=str(form.get("source", "")), origin="human")
    bad = said.lower().startswith(("an asset needs", "rights must"))
    return _back_to_content(tenant, err=said if bad else "",
                            msg="" if bad else f"{said} ({subject})")


@app.get("/admin/creative_assets")
def creative_assets(key: str = Depends(admin_key), tenant: str = "") -> dict:
    """The asset ids `/admin/creative` takes, so they can be found without SQL."""
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    from . import kb as kbm
    rows = kbm.assets(tenant, publishable_only=False)
    return {"tenant": tenant, "assets": [
        {"id": a.id, "title": a.title, "kind": a.kind,
         "rights": a.rights or "reference (no answer stored)",
         "usable_in_a_creative": (a.rights or "") == kbm.OWNED,
         "entity_key": a.entity_key, "uses": a.uses} for a in rows]}


@app.get("/admin/agent_context")
def agent_context(key: str = Depends(admin_key), tenant: str = "",
                  system: str = "", utterance: str = "", entity_key: str = "",
                  audience_key: str = "", contact_id: str = "",
                  tier: int = 3, limit: int = 3) -> dict:
    """The resolved brief for one request, as JSON, for a skill to draft from.

    Read `blocked_on` before anything else: non-empty means this account cannot
    safely produce output for this request, and each entry names the field to
    go and fill.
    """
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    from . import resolve as _resolve, tenants as _tenants
    if not tenant:
        return {"error": "tenant is required — name the client explicitly"}
    row = _tenants.get(tenant)
    bundle = _resolve.resolve(tenant, system=system, utterance=utterance,
                              contact_id=contact_id, entity_key=entity_key,
                              audience_key=audience_key, tier=tier, limit=limit)
    if bundle.get("error"):
        return bundle
    return {
        **bundle,
        # Named back to the caller so a skill that resolved the wrong client
        # says so in its own output instead of being quietly wrong about who
        # it is speaking for.
        "acting_for": {"tenant": tenant, "name": row.name if row else ""},
        "obligation": {
            "before_sending": "POST /admin/agent_emit",
            "why": "the banned-claim rules in this bundle are enforced there, "
                   "not here, and nothing you send is on the record until you "
                   "do it",
            "refuse_if": "blocked_on is non-empty, or a fact you need is "
                         "absent — say you will check rather than guessing",
        },
    }


@app.post("/admin/agent_emit")
async def agent_emit(request: Request, key: str = Depends(admin_key)) -> dict:
    """The gate. Validate a skill-written draft, file it, say whether it may go.

    Deliberately returns `may_send` and not the draft. A skill cannot treat
    calling this as a formality and send regardless — there is nothing here to
    quote as permission unless it passed.
    """
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    from . import ledger, systems, validator
    body = await request.json()
    tenant = str(body.get("tenant", "")).strip()
    system_key = str(body.get("system_key", "")).strip()
    text = str(body.get("body", "")).strip()
    if not tenant or not system_key or not text:
        return {"error": "tenant, system_key and body are all required"}

    claim_ids = [str(c) for c in (body.get("claim_ids") or [])]
    entity_key = str(body.get("entity_key", ""))
    result = validator.check(
        tenant, text, claim_ids=claim_ids, entity_key=entity_key,
        conversation_id=str(body.get("conversation_id", "")),
        require_citation=bool(body.get("require_citation", True)))

    row = systems.find(tenant, system_key)
    autonomy = (row.autonomy if row else "") or "shadow"
    # The rung decides how far a PASSING draft travels; it never rescues a
    # failing one. Same precedence as `skill._disposition` — the validator
    # outranks the rung, and `auto` means "do not ask about what passed".
    if not result["ok"]:
        may_send, disposition = False, "blocked"
    elif autonomy == "auto":
        may_send, disposition = True, "send"
    elif autonomy == "shadow":
        may_send, disposition = False, "shadow — record only, send nothing"
    else:
        may_send, disposition = False, "needs approval"

    from . import assurance
    assurance.record(
        tenant, source="bridge", system_key=system_key,
        checked=result.get("checked") or [],
        caught=[f["rule"] for f in result["failures"]],
        verdict="passed" if result["ok"] else "blocked",
        grounded=bool(claim_ids))

    out = ledger.record(
        tenant, system_key, body=text, claim_ids=claim_ids,
        entity_key=entity_key, audience_key=str(body.get("audience_key", "")),
        situation=str(body.get("situation", "")),
        angle=str(body.get("angle", "")), format=str(body.get("format", "")),
        conversation_id=str(body.get("conversation_id", "")),
        status="draft" if result["ok"] else "blocked",
        blocked_on=[f["rule"] for f in result["failures"]])

    # A refusal that just says no leaves the caller nothing to do but escalate,
    # and a queue of human rewrites is not a QA layer — it is the same mistake
    # made repeatedly with a person absorbing it. So a rejection carries the
    # instruction to fix it, and, where a rewrite genuinely cannot (the proof
    # does not exist), it names the KB row that would.
    from . import skill as _skill
    retry: dict = {}
    if not result["ok"]:
        needs = _skill._knowledge_needed(result["failures"])
        retry = {
            "action": "rewrite and POST again",
            "attempts_advised": _skill.MAX_REPAIRS,
            "changes": [f"{f['detail']} → {f['fix']}"
                        for f in result["failures"]],
            "do_not": "relax the rule, argue with it, or send this anyway — "
                      "the same check runs on every attempt",
            "knowledge_missing": needs,
            "if_unfixable": ("stop rewriting and report the knowledge_missing "
                             "entries — no wording satisfies a rule when the "
                             "fact it needs was never recorded")
            if needs else "",
        }

    return {"ok": result["ok"], "may_send": may_send,
            "disposition": disposition, "autonomy": autonomy,
            "failures": result["failures"], "checked": result["checked"],
            "retry": retry,
            "output_id": out.id, "system_installed": bool(row),
            "note": ("" if row else
                     f"no {system_key!r} system installed for {tenant!r} — the "
                     f"draft is on the ledger but has no rung, so it is being "
                     f"treated as shadow")}


@app.get("/admin/assurance")
def assurance_report(key: str = Depends(admin_key), tenant: str = "",
                     days: int = 30, catches: bool = False) -> dict:
    """The same numbers the console renders, as data.

    Separate from the tab because a weekly digest, a client report and a
    console page should not each recompute this differently — the tab renders
    exactly what this returns.
    """
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    from . import assurance
    days = max(1, min(int(days or 30), 365))
    out = assurance.report(tenant, days)
    if catches:
        out["catch_list"] = assurance.catches(tenant, days)
    return out


@app.get("/admin/diagnostics")
def diagnostics_route(key: str = Depends(admin_key), tenant: str = "",
                      days: int = 7, level: str = "", system: str = "",
                      limit: int = 200) -> dict:
    """The Diagnostics tab as JSON — same assembler, no rendering.

    `tenant` is REQUIRED and `*` is the explicit cross-account value, matching
    the console: an absent account here would have to mean either "all" or
    "the first one", and a diagnostics feed guessing between those is how a
    monitor ends up watching the wrong client. Reads only what is on record
    and calls nothing.
    """
    from . import diagnostics
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    if not tenant:
        return {"error": "tenant is required — pass a key, or * for every account"}
    return diagnostics.report("" if tenant == "*" else tenant,
                              days=max(1, min(days, 365)), level=level,
                              system=system, limit=max(10, min(limit, 1000)))


@app.get("/admin/client_report")
def client_report_route(key: str = Depends(admin_key), tenant: str = "",
                        days: int = 30) -> dict:
    """One period, one client — everything on record, and what is not.

    Deliberately reads only what is already stored. Assembling a report must
    not be the moment a dead Shopify token is discovered, and a report that
    takes forty seconds and half-fails is worse than one built from the record.
    """
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    if not tenant:
        return {"error": "tenant is required"}
    from . import client_report
    return client_report.assemble(tenant, max(1, min(int(days or 30), 365)))


@app.get("/admin/tool_calls")
def tool_calls_route(key: str = Depends(admin_key), tenant: str = "",
                     days: int = 30) -> dict:
    """Which tools ran, which failed, and how slow they were."""
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    from . import toolcalls
    return toolcalls.report(tenant, max(1, min(int(days or 30), 365)))


@app.post("/admin/report_figure")
async def report_figure(request: Request, key: str = Depends(admin_key)):
    """Record a number the client sent back.

    POST because it writes, and stored AS GIVEN rather than coerced: a client
    who answers "about £18, maybe £20 at peak" has told us something a float
    would destroy, and a report that says "£18 (their estimate)" is more honest
    than one that says 18.0.
    """
    from fastapi.responses import JSONResponse

    from . import metrics
    if key != config.APPROVAL_SECRET:
        return JSONResponse({"error": "unauthorized"}, status_code=403)
    form = await request.form()
    return {"result": metrics.record_figure(
        str(form.get("tenant", "")), str(form.get("metric", "")),
        str(form.get("value", "")),
        period_start=str(form.get("period_start", "")),
        period_end=str(form.get("period_end", "")),
        unit=str(form.get("unit", "")),
        supplied_by=str(form.get("supplied_by", "")),
        note=str(form.get("note", "")))}


@app.get("/admin/report_request")
def report_request(key: str = Depends(admin_key), tenant: str = "",
                   days: int = 30, to: str = "", queue: bool = False) -> dict:
    """Compose the ask for what only the client can tell us.

    `queue=true` puts it in the approval queue. It is never sent from here —
    nothing in this system sends as a side effect of producing something, and a
    request going out under Gomeh's name without him reading it would be the
    first.
    """
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    if not tenant:
        return {"error": "tenant is required"}
    from . import metrics
    return metrics.request_email(tenant, max(1, min(int(days or 30), 365)),
                                 to=to, queue=bool(queue))


# ---------------------------------------------------------------------------
# The client portal. Every view here goes through `portal.resolve_tenant`,
# which takes the account from the SESSION and refuses a mismatched `tenant=`
# rather than substituting the right one.
# ---------------------------------------------------------------------------

@app.get("/portal", response_class=HTMLResponse)
def portal_home(request: Request, tab: str = "overview", days: int = 30) -> str:
    from . import portal, portal_ui
    asked = request.query_params.get("tenant", "")
    tenant, refusal = portal.resolve_tenant(request, asked)
    if refusal == "sign in first":
        return portal_ui.render_signin()
    if refusal:
        # Signed in, but reaching for an account that is not theirs. Showing a
        # SIGN-IN form here would be nonsense — they are signed in — and would
        # read as "your session broke" rather than "that is not yours".
        who = portal.principal(request)
        return portal_ui.render(who["tenant"], tab=tab, days=days, who=who,
                                notice=refusal)
    if not tenant:
        return portal_ui.render_signin("Pick an account with ?tenant=")
    who = portal.principal(request)
    who["may_write"] = portal.can_write(request)
    return portal_ui.render(tenant, tab=tab, days=max(1, min(int(days or 30), 365)),
                            who=who)


@app.get("/portal/signin", response_class=HTMLResponse)
def portal_signin() -> str:
    from . import portal_ui
    return portal_ui.render_signin()


@app.post("/portal/signin")
async def portal_signin_post(request: Request):
    """Ask for a sign-in link.

    Answers the SAME way whether or not the address is known. Telling a
    stranger which addresses have accounts turns a login form into a customer
    list, and this one is on the open internet.
    """
    from fastapi.responses import HTMLResponse as _H

    from . import channel, portal, portal_ui
    form = await request.form()
    email = str(form.get("email", "")).strip()
    got = portal.issue_link(email)

    # Nothing sends the link, by the owner's choice — so the REQUEST has to
    # reach him, or it dies in a log line and the client waits for an email
    # that was never going to arrive. This is the whole difference between
    # "manual" and "broken".
    if got.get("ok"):
        note = (f"🔑 Portal access requested by {email} ({got['for']}). "
                f"Mint and send their link from the Accounts tab → People, "
                f"or use:\n{got['url']}")
    else:
        # An unknown address is worth seeing too: it is either a client using
        # a different address from the one on file — the commonest real cause —
        # or somebody probing. Both want a human to look.
        note = (f"🔑 Portal access requested by {email}, which is not on file. "
                f"Either add them under Accounts → People, or ignore it.")
    try:
        channel.send_text(note)
    except Exception:                                            # noqa: BLE001
        log.exception("could not notify ops about a portal sign-in request")
    return _H(portal_ui.render_signin(sent=True))


@app.get("/portal/in/{token}")
def portal_in(token: str):
    from fastapi.responses import RedirectResponse

    from . import portal, portal_ui
    got = portal.redeem(token)
    if not got.get("ok"):
        return HTMLResponse(portal_ui.render_signin(got.get("error", "")))
    resp = RedirectResponse("/portal", status_code=303)
    resp.set_cookie(portal.PORTAL_COOKIE, got["cookie"], max_age=60 * 60 * 24 * 14,
                    httponly=True, secure=True, samesite="lax")
    return resp


@app.post("/portal/figure")
async def portal_figure(request: Request):
    """A client sending us one of the numbers only they have.

    Gated on `can_write`, which is the whole reason read-only exists: this
    figure is printed in a report with their name on it, so who may supply one
    is a real permission rather than a UI preference.
    """
    from fastapi.responses import RedirectResponse

    from . import metrics, portal
    tenant, refusal = portal.resolve_tenant(request, "")
    if refusal or not tenant:
        return RedirectResponse("/portal/signin", status_code=303)
    if not portal.can_write(request):
        # Refused server-side as well as hidden in the UI. A form nobody is
        # shown is still a form somebody can post to.
        return RedirectResponse("/portal?tab=requests", status_code=303)
    form = await request.form()
    who = portal.principal(request)
    name = ""
    with db.SessionLocal() as s:
        u = s.get(db.User, who.get("user_id") or "")
        name = (u.name or u.email or "") if u else ""
    metrics.record_figure(
        tenant, str(form.get("metric", "")), str(form.get("value", "")),
        period_end=db.utcnow().date().isoformat(),
        supplied_by=name or "the client")
    return RedirectResponse("/portal?tab=requests", status_code=303)


@app.get("/portal/out")
def portal_out():
    from fastapi.responses import RedirectResponse

    from . import portal
    resp = RedirectResponse("/portal/signin", status_code=303)
    resp.delete_cookie(portal.PORTAL_COOKIE)
    return resp


@app.post("/admin/person_save")
async def person_save(request: Request, key: str = Depends(admin_key)):
    """Add or update somebody who can sign in to a client's portal."""
    from fastapi.responses import RedirectResponse
    from urllib.parse import quote

    from . import portal
    if key != config.APPROVAL_SECRET:
        return HTMLResponse("<h3>unauthorized</h3>", status_code=403)
    form = await request.form()
    tenant = str(form.get("tenant", ""))
    got = portal.save_person(
        email=str(form.get("email", "")), name=str(form.get("name", "")),
        tenant=tenant, access=str(form.get("access", "read_only")))
    q = (f"&ok={quote(got['email'] + ' can sign in (' + got['access'].replace('_', ' ') + ')')}"
         if got.get("ok") else f"&err={quote(got.get('error', ''))}")
    return RedirectResponse(f"/admin/ui?tab=accounts&tenant={quote(tenant)}{q}#people",
                            status_code=303)


@app.post("/admin/person_access")
async def person_access(request: Request, key: str = Depends(admin_key)):
    """Move somebody between read-only and full, or revoke them outright."""
    from fastapi.responses import RedirectResponse
    from urllib.parse import quote

    from . import portal
    if key != config.APPROVAL_SECRET:
        return HTMLResponse("<h3>unauthorized</h3>", status_code=403)
    form = await request.form()
    tenant = str(form.get("tenant", ""))
    action = str(form.get("action", ""))
    uid = str(form.get("user_id", ""))
    if action == "revoke":
        msg = portal.revoke(uid)
    elif action in ("read_only", "full"):
        msg = portal.set_access(uid, action)
    else:
        msg = "unknown action"
    return RedirectResponse(
        f"/admin/ui?tab=accounts&tenant={quote(tenant)}&ok={quote(msg)}#people",
        status_code=303)


@app.get("/admin/portal_link")
def portal_link(key: str = Depends(admin_key), email: str = "") -> dict:
    """Mint a sign-in link for a client, to send them yourself.

    Returned rather than sent, on purpose: a login link is a credential, and
    this system has never sent anything as a side effect of producing it.
    """
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    from . import portal
    return portal.issue_link(email, issued_by="owner")


@app.get("/admin/skill_catalogue")
def skill_catalogue(key: str = Depends(admin_key), tenant: str = "") -> dict:
    """Every registered skill and whether it can run for this account."""
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    from . import skill, skill_pack  # noqa: F401 — import registers the pack
    return {"tenant": tenant, "skills": skill.catalogue(tenant)}


@app.post("/admin/skill_run")
async def skill_run(request: Request, key: str = Depends(admin_key)) -> dict:
    """Run one registered skill end to end, governed the whole way.

    Preferred over context+emit when a registered skill already does the job:
    `skill.run` opens a run, validates every emission and closes the run, so
    nothing depends on the caller remembering to come back.
    """
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    from . import skill, skill_pack  # noqa: F401 — import registers the pack
    body = await request.json()
    name = str(body.get("skill", "")).strip()
    tenant = str(body.get("tenant", "")).strip()
    if not name or not tenant:
        return {"error": "skill and tenant are both required"}
    if not skill.get(name):
        return {"error": f"unknown skill {name!r}",
                "available": [s["key"] for s in skill.catalogue(tenant)]}
    params = {k: v for k, v in (body.get("params") or {}).items()}
    return skill.run(name, tenant, trigger=str(body.get("trigger", "manual")),
                     ref=str(body.get("ref", "")), **params)


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


def _back_to_content(tenant: str, started: str = "", err: str = "",
                     msg: str = "", anchor: str = "", cpage: int = 0):
    """Return to the Content tab. No key in the URL: by the time an action has
    run, the session cookie is already set (the middleware sets it on any
    request carrying a valid key), so putting the secret back into the address
    bar would undo the session for nothing.

    `anchor` puts the reader back where they were. Deciding one claim in a
    queue of forty used to return them to the top of the page, so every
    decision cost a scroll — which is how a review queue stops being worked.
    `cpage` finishes that job now the queue paginates: an anchor on page two
    is unreachable from page one, so the redirect must carry the page or the
    anchor silently lands at the top — the exact bounce this exists to stop.
    """
    from urllib.parse import quote

    from fastapi.responses import RedirectResponse
    q = f"/admin/ui?tab=content&tenant={tenant}"
    if started:
        q += f"&started={started}"
    if err:
        q += f"&err={quote(err)}"
    if msg:
        q += f"&ok={quote(msg)}"
    try:
        if int(cpage) > 1:
            q += f"&cpage={int(cpage)}"
    except (TypeError, ValueError):
        pass
    if anchor:
        q += f"#{anchor}"
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
    lands.

    The outcome is RECORDED, not only logged. The first version caught the
    exception, wrote it to the service log and returned — so a background
    action that failed looked exactly like one still running: the banner said
    "proposals will appear above when it finishes" and they never did. That is
    the same broken-button experience this function was written to remove,
    moved one layer down. The traceback was in Render and the operator was in
    a browser, and nothing joined them.

    A successful run that produced nothing is recorded too, for the same
    reason: "read 40 pages, proposed 0, everything already on file" and "the
    button did nothing" are different facts and must not look alike.
    """
    import json as _json
    import threading

    tenant = kw.get("tenant") or (args[0] if args else "")

    def _mark(state: str, detail: str = "") -> None:
        with db.SessionLocal() as s:
            key = f"bg:{label}:{tenant}"
            row = s.get(db.Setting, key) or db.Setting(key=key)
            row.value = _json.dumps({"state": state, "detail": detail[:1500],
                                     "at": db.utcnow().isoformat()})
            s.merge(row)
            s.commit()

    def _go():
        try:
            result = fn(*args, **kw)
        except Exception as exc:  # noqa: BLE001
            log.exception("%s failed", label)
            _mark("failed", f"{exc.__class__.__name__}: {exc}")
            return
        _mark("done", _summarise(result))

    _mark("running")
    threading.Thread(target=_go, daemon=True).start()


def _summarise(result) -> str:
    """The two or three numbers that say whether a run was worth anything."""
    if not isinstance(result, dict):
        return ""
    if result.get("error"):
        return f"error: {result['error']}"
    keep = ("proposed_count", "pages_read", "pages_unchanged", "pages_remaining",
            "faqs_filed_as_objections", "claims_count", "objections_count",
            "threads_seen", "added", "updated", "violations", "extractor")
    bits = [f"{k} {result[k]}" for k in keep if result.get(k) not in (None, "")]
    note = result.get("extractor_note") or ""
    return " · ".join(bits) + (f" — {note[:200]}" if note else "")


def bg_status(label: str, tenant: str) -> dict:
    """What the last background run of this action did, if anything."""
    import json as _json
    with db.SessionLocal() as s:
        row = s.get(db.Setting, f"bg:{label}:{tenant}")
        try:
            return _json.loads(row.value) if row and row.value else {}
        except Exception:  # noqa: BLE001
            return {}


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
            return _back_to_content(tenant, err=problem, anchor="others")
    result = kbm.approve(kind, row_id, by="owner",
                         approve_it=str(form.get("action", "")) == "approve",
                         brand_wide=bool(form.get("brand_wide")))
    if result.startswith("Say what"):
        return _back_to_content(tenant, err=result, anchor="others")
    return _back_to_content(tenant, anchor="others")


@app.get("/admin/vocabulary")
def vocabulary_review(key: str = Depends(admin_key), tenant: str = "",
                      model: str = "") -> dict:
    """Situations that are probably one situation, and the map between them.

    The deterministic check runs always; `model=1` adds the pass that can see
    two tags meaning the same thing in different words, which no lexical
    measure can.
    """
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    from . import extract, kb as kbm
    out = {"tenant": tenant,
           "overlaps": kbm.situation_overlaps(tenant),
           "neighbours": {r.tag: kbm.situation_neighbours(tenant, r.tag)
                          for r in kbm.situation_rows(tenant)}}
    if model in ("1", "true"):
        out["model_review"] = extract.review_vocabulary(tenant)
    return out


@app.post("/admin/merge_situation", response_class=HTMLResponse)
async def merge_situation(request: Request, key: str = Depends(admin_key)):
    """Fold one situation into another. POST — it retags every row using it."""
    if key != config.APPROVAL_SECRET:
        return HTMLResponse("<h3>unauthorized</h3>", status_code=403)
    from . import kb as kbm
    form = await request.form()
    tenant = str(form.get("tenant", ""))
    r = kbm.merge_situations(tenant, str(form.get("keep", "")),
                             str(form.get("drop", "")), dry_run=False)
    return _back_to_kb(tenant, err=r.get("error", "") or r.get("note", ""))


@app.get("/admin/harvest_pages")
def harvest_pages(key: str = Depends(admin_key), tenant: str = "",
                  forget: str = "") -> dict:
    """How much of each site has been read, and a way to start it over."""
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    from . import harvest as hv, tenants as tn
    if tenant and forget in ("1", "true"):
        return {"result": hv.forget_pages(tenant)}
    keys = [tenant] if tenant else [t.key for t in tn.all_tenants()]
    out = {}
    for k in keys:
        seen = hv._page_state(k)
        out[k] = {"pages_read": len(seen)}
    return out


@app.get("/admin/mail_cursor")
def mail_cursor(key: str = Depends(admin_key), tenant: str = "",
                reset: str = "") -> dict:
    """How far each mailbox has been read, and a way to start over."""
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    from . import email_harvest as eh, tenants as tn
    if tenant and reset in ("1", "true"):
        return {"result": eh.reset_cursor(tenant)}
    keys = [tenant] if tenant else [t.key for t in tn.all_tenants()]
    return {k: eh.cursor(k) for k in keys}


@app.get("/admin/purge_harvested")
def purge_harvested_report(request: Request, key: str = Depends(admin_key),
                           tenant: str = "") -> dict:
    """What a purge WOULD remove. Reports only — deleting needs the POST."""
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    from . import kb as kbm
    return kbm.purge_harvested(
        tenant, include_entities=str(
            request.query_params.get("entities", "")).lower() in ("1", "true"),
        dry_run=True)


@app.post("/admin/purge_harvested")
async def purge_harvested_apply(request: Request, key: str = Depends(admin_key)):
    """Actually clear the machine-read claims and objections for one account.

    POST because it deletes. The GET above reports and never removes anything,
    for the reason DEFECTS gives about console writes on GET: a link preview
    must not be able to empty a knowledge base.
    """
    if key != config.APPROVAL_SECRET:
        return {"error": "unauthorized"}
    from . import kb as kbm
    form = await request.form()
    tenant = str(form.get("tenant", ""))
    result = kbm.purge_harvested(
        tenant,
        include_entities=str(form.get("entities", "")).lower() in ("1", "true"),
        dry_run=False)
    if form.get("ui"):
        gone = sum(v.get("total", 0) for v in (result.get("deleted") or {}).values())
        return _back_to_content(
            tenant, err=f"Cleared {gone} crawled and mailed rows. Run Fill from "
                        f"every source to re-harvest — the ban list, vocabulary "
                        f"and catalogue were kept.")
    return result


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


@app.post("/admin/claims_decide", response_class=HTMLResponse)
async def claims_decide(request: Request, key: str = Depends(admin_key)):
    """Decide many proposals in one submit.

    Reviewing was one request per claim, and every one of them reloaded the tab
    and returned the reader to the top of a long queue — so working through
    forty harvested claims meant forty scrolls back to where you were. That is
    the whole reason the queue stopped being read.

    `reject_covered` recomputes which proposals an approved brand-level claim
    already covers, rather than trusting a list the browser built: the page may
    have been rendered before the last approval landed, and acting on a stale
    list would retire something nothing covers.
    """
    if key != config.APPROVAL_SECRET:
        return HTMLResponse('<h3>unauthorized</h3>')
    from . import kb as kbm
    form = await request.form()
    tenant = str(form.get("tenant", ""))
    action = str(form.get("action", ""))
    try:
        cpage = int(form.get("cpage") or 1)
    except ValueError:
        cpage = 1

    if action == "reject_covered":
        pairs = kbm.brand_level_duplicates(tenant)
        for cid, _why in pairs:
            kbm.review_claim(cid, approve=False)
        n = len(pairs)
        return _back_to_content(
            tenant, msg=(f"retired {n} narrower cop{'y' if n == 1 else 'ies'} "
                         f"of claims already approved brand-level"
                         if n else "nothing was covered brand-level"),
            anchor="proposals", cpage=cpage)

    ids = [str(i) for i in form.getlist("claim_ids") if str(i).strip()]
    if not ids:
        return _back_to_content(tenant, msg="nothing was selected",
                                anchor="proposals", cpage=cpage)

    approve = action == "approve"
    done, refused = 0, []
    for cid in ids:
        res = kbm.review_claim(cid, approve=approve)
        # `review_claim` refuses an untagged claim, and that refusal is the
        # point of the whole review step — surfacing the count without the
        # reasons would look like a partial success with no explanation.
        if isinstance(res, str) and res.lower().startswith(("cannot", "needs",
                                                            "refus")):
            refused.append(res)
        else:
            done += 1
    verb = "approved" if approve else "rejected"
    msg = f"{verb} {done} of {len(ids)}"
    if refused:
        msg += f" — {len(refused)} refused: {refused[0][:120]}"
    return _back_to_content(tenant, msg=msg, anchor="proposals", cpage=cpage)


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

    # The next card, so approving walks DOWN the queue instead of bouncing to
    # the top of it. Read before the decision, while this row is still pending.
    nxt = str(form.get("next_id", ""))
    try:
        cpage = int(form.get("cpage") or 1)
    except ValueError:
        cpage = 1

    if action == "reject":
        kbm.review_claim(claim_id, approve=False)
        return _back_to_content(tenant, anchor=f"c-{nxt or claim_id}",
                                cpage=cpage)

    if action == "never":
        # Timeless, and approved in the same move. Marking a claim permanent
        # while leaving it in the queue would be an odd half-decision — the
        # reviewer is looking at it and saying "this one does not go stale",
        # which is an approval with an extra fact attached.
        kbm.set_claim_expiry(claim_id, never=True)
        kbm.review_claim(claim_id, approve=True)
        return _back_to_content(tenant, anchor=f"c-{nxt or claim_id}",
                                cpage=cpage)

    # Whatever was typed into the entity box, resolved to a real key — by name,
    # by slug, or by a unique partial of either. Refusing here rather than
    # writing it through matters: `update_claim` would take an unknown key at
    # face value and scope the claim to a thing that does not exist, which
    # reads as "not selectable" much later and far from the cause.
    ent_raw = str(form.get("entity_key", ""))
    ent_key, ent_problem = kbm.resolve_entity_ref(tenant, ent_raw)
    if ent_problem:
        return _back_to_content(tenant, err=ent_problem,
                                anchor=f"c-{claim_id}", cpage=cpage)

    msg = kbm.update_claim(
        claim_id,
        claim=str(form.get("claim", "")),
        evidence=str(form.get("evidence", "")),
        entity_key=ent_key,
        proves=str(form.get("proves", "")),
        context=str(form.get("context", "")) if form.get("context") is not None else None,
        tags=[str(t) for t in form.getlist("tags")])
    if msg != "Saved." and "catalogue" in msg:
        return HTMLResponse(f"<h3>{msg}</h3><p><a href='/admin/ui?tab=content"
                            f"&tenant={tenant}'>Back</a></p>", status_code=400)
    if action == "approve":
        # May refuse — an untagged claim cannot be approved, and the tab will
        # still show it with the reason.
        refusal = kbm.review_claim(claim_id, approve=True)
        if isinstance(refusal, str) and refusal.lower().startswith(
                ("cannot", "needs", "refus")):
            return _back_to_content(tenant, err=refusal,
                                    anchor=f"c-{claim_id}", cpage=cpage)
    return _back_to_content(tenant, anchor=f"c-{nxt or claim_id}", cpage=cpage)


@app.get("/admin/harvest")
def harvest_route(key: str = Depends(admin_key), tenant: str = "",
                  limit: int = 25, apply: str = "", ui: str = "",
                  recrawl: str = ""):
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
