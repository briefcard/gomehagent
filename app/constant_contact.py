"""Constant Contact: the second send path for `campaign_email`.

Omnisend was the only ESP with an adapter, so a client on Constant Contact
could connect it, turn on `esp`, watch `campaign_email` pass readiness, and
have nowhere to put an email — the exact gap `app/omnisend.py` was written to
close, one provider along.

The architecture survives the move because Constant Contact splits the same
way: **`POST /emails` creates a campaign in DRAFT, and scheduling it is a
different endpoint.** Nothing here sends as a side effect of producing
something. `send_campaign` takes `confirm=True` and the substrate never calls
it, for the reason it never calls Omnisend's: a campaign is irreversible and
lands in thousands of inboxes at once, which is not what `auto` means.

Three things differ from Omnisend, and each is a place this could have been
written wrong by assuming the two APIs are the same shape:

  · **The sender cannot be omitted.** Omnisend's verified sender applies when
    the field is left out, which is why that module always leaves it out.
    Constant Contact REQUIRES `from_email` and `reply_to_email`, and will only
    accept an address already confirmed on the account. So it is read from the
    account (`senders`) rather than invented, and when the account has more
    than one confirmed address and the caller named none, this refuses and
    lists them. Guessing which address a brand sends from is a mistake that
    reaches the recipient.

  · **A campaign cannot be scheduled until contacts are attached**, by a
    separate PUT. Scheduling without that step fails at the last call in the
    chain, after a draft exists, which is the worst place to discover it — so
    `send_campaign` checks first and says so.

  · **`format_type` must be 5.** The V3 API can only create custom-code
    emails; the other formats can be read and scheduled but not created.

Built against the documented request shapes. **No call has been made against a
real Constant Contact account** — same standing as Canva and, until Gomeh runs
it, Omnisend.
"""
from __future__ import annotations

from . import credentials as cred

BASE = "https://api.cc.email/v3"
TIMEOUT = 30
#: The V3 API creates custom-code emails only. Documented, not chosen.
FORMAT_CUSTOM_CODE = 5


def _token(tenant: str) -> tuple[str, str]:
    """A live access token for this account, or why there is not one.

    The stored secret is a refresh token — `oauth` deliberately never keeps the
    hour-long access token — so every call mints one. `oauth.access_token`
    already does that for Google and Canva and caches nothing, which is right:
    a cached token outlives a revocation.
    """
    c = cred.resolve(tenant, "constant_contact")
    if c.get("error"):
        return "", c["error"]
    if not c.get("secret"):
        return "", (f"{tenant} has no Constant Contact connection — connect it "
                    f"on the Accounts tab before anything can be drafted "
                    f"into it.")
    from . import oauth
    got = oauth.access_token("constant_contact", c["secret"])
    if not got.get("ok"):
        return "", got.get("error", "Constant Contact would not renew the token.")
    return got["token"], ""


def _call(tenant: str, method: str, path: str, *,
          payload: dict | None = None, params: dict | None = None) -> dict:
    """One authenticated call. `{ok, data}` or `{ok: False, error}`.

    The API's own error text is carried through rather than flattened into a
    sentence of ours: "from_email is not a confirmed account email" is
    actionable and "Constant Contact rejected the campaign" is not.
    """
    token, why = _token(tenant)
    if why:
        return {"ok": False, "error": why}
    import httpx
    try:
        r = httpx.request(method, f"{BASE}{path}",
                          headers={"Authorization": f"Bearer {token}",
                                   "Content-Type": "application/json"},
                          json=payload, params=params, timeout=TIMEOUT)
    except Exception as exc:                                     # noqa: BLE001
        return {"ok": False, "error": f"{exc.__class__.__name__}: {str(exc)[:160]}"}

    if r.status_code in (401, 403):
        return {"ok": False,
                "error": "Constant Contact rejected the token — reconnect the "
                         "account on the Accounts tab."}
    if r.status_code >= 400:
        return {"ok": False, "error": _error_text(r)}
    try:
        return {"ok": True, "data": r.json() if r.content else {}}
    except ValueError:
        return {"ok": True, "data": {}}


def _error_text(r) -> str:
    """Constant Contact answers with a LIST of errors, not one.

    Reading `[0]` would hide the rest, and a create that is wrong in three
    fields would then take three round trips to fix — one field revealed per
    attempt. All of them are reported.
    """
    try:
        body = r.json()
    except ValueError:
        return f"HTTP {r.status_code}: {r.text[:160]}"
    if isinstance(body, list):
        parts = [f"{e.get('error_key', '')}: {e.get('error_message', '')}".strip(": ")
                 for e in body if isinstance(e, dict)]
        if parts:
            return f"HTTP {r.status_code} — " + "; ".join(parts[:5])
    if isinstance(body, dict) and body.get("error_message"):
        return f"HTTP {r.status_code} — {body['error_message']}"
    return f"HTTP {r.status_code}: {str(body)[:160]}"


#: The seam the offline suite replaces. Every public function goes through this
#: name rather than `_call` directly, so the tests can assert the REQUEST this
#: module builds without reaching Constant Contact — which is the only part of
#: the behaviour that is ours to get right.
call = _call


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def senders(tenant: str) -> dict:
    """The account's CONFIRMED from-addresses.

    Only confirmed ones are returned. An unconfirmed address is on the account
    and cannot be sent from, so offering it would produce a draft that fails at
    schedule time with an error about a field the caller was handed by us.
    """
    got = call(tenant, "GET", "/account/emails")
    if not got["ok"]:
        return got
    rows = got["data"] if isinstance(got["data"], list) else []
    ok = [r.get("email_address", "") for r in rows
          if str(r.get("confirm_status", "")).upper() == "CONFIRMED"]
    return {"ok": True, "senders": [e for e in ok if e],
            "unconfirmed": [r.get("email_address", "") for r in rows
                            if str(r.get("confirm_status", "")).upper()
                            != "CONFIRMED"]}


def contact_lists(tenant: str) -> dict:
    got = call(tenant, "GET", "/contact_lists")
    if not got["ok"]:
        return got
    rows = (got["data"] or {}).get("lists") or []
    return {"ok": True, "lists": [{"id": r.get("list_id", ""),
                                   "name": r.get("name", ""),
                                   "count": r.get("membership_count", 0)}
                                  for r in rows]}


# ---------------------------------------------------------------------------
# Write — a draft, and only a draft
# ---------------------------------------------------------------------------

def draft_from_html(tenant: str, *, name: str, subject: str, html: str,
                    from_name: str, from_email: str = "",
                    reply_to: str = "", physical_address: dict | None = None,
                    preheader: str = "") -> dict:
    """Create a campaign in DRAFT. Never sends, never schedules.

    `from_email` is resolved against the account rather than accepted on faith:
    given one, it must already be confirmed there; given none, it is used only
    when the account has exactly one confirmed address. Anything else refuses
    and names the candidates. A brand sending from the wrong address is not a
    bug the recipient can see past.
    """
    if not html.strip():
        return {"ok": False, "error": "Nothing to send — the HTML is empty."}

    known = senders(tenant)
    if not known["ok"]:
        return known
    available = known["senders"]
    if not available:
        pending = known.get("unconfirmed") or []
        return {"ok": False, "error": (
            "This Constant Contact account has no confirmed from-address, so "
            "nothing can be sent from it yet"
            + (f" — {', '.join(pending[:3])} still needs confirming."
               if pending else ". Add and confirm one in Constant Contact "
                               "first."))}
    if from_email and from_email not in available:
        return {"ok": False, "error": (
            f"{from_email} is not a confirmed address on this account. "
            f"Confirmed: {', '.join(available)}.")}
    if not from_email:
        if len(available) > 1:
            return {"ok": False, "error": (
                "This account can send from more than one address, so say "
                "which: " + ", ".join(available))}
        from_email = available[0]

    activity = {
        "format_type": FORMAT_CUSTOM_CODE,
        "from_name": from_name,
        "from_email": from_email,
        "reply_to_email": reply_to or from_email,
        "subject": subject,
        "html_content": html,
    }
    if preheader:
        activity["preheader"] = preheader
    if physical_address:
        # Left OUT when not supplied, so the account's own footer address
        # applies. Inventing one would put a wrong postal address on a
        # commercial email, which is the field CAN-SPAM is actually about.
        activity["physical_address_in_footer"] = physical_address

    got = call(tenant, "POST", "/emails", payload={
        "name": name,
        "email_campaign_activities": [{"role": "primary_email", **activity}]})
    if not got["ok"]:
        return got
    data = got["data"] or {}
    acts = data.get("campaign_activities") or []
    primary = next((a for a in acts
                    if a.get("role") == "primary_email"), acts[0] if acts else {})
    return {"ok": True,
            "campaign_id": data.get("campaign_id", ""),
            "activity_id": primary.get("campaign_activity_id", ""),
            "status": data.get("current_status", "DRAFT"),
            "from_email": from_email,
            "detail": f"Draft created in Constant Contact as {name!r}."}


def set_recipients(tenant: str, activity_id: str,
                   list_ids: list[str]) -> dict:
    """Attach the contact lists a draft will go to. Still does not send."""
    if not list_ids:
        return {"ok": False, "error": "No contact list given."}
    return call(tenant, "PUT", f"/emails/activities/{activity_id}",
                 payload={"contact_list_ids": list_ids})


def send_campaign(tenant: str, activity_id: str, *, confirm: bool = False,
                  when: str = "0") -> dict:
    """Schedule the send. `when="0"` is Constant Contact's "now".

    `confirm` is not ceremony. This is the one call in the module that cannot
    be undone, and the substrate never makes it — an email campaign belongs in
    the approval queue whatever rung the system is on.
    """
    if not confirm:
        return {"ok": False, "error": (
            "Sending a campaign is irreversible and reaches every contact on "
            "the attached lists at once. Call with confirm=True, from an "
            "approval, never from a skill.")}
    return call(tenant, "POST", f"/emails/activities/{activity_id}/schedules",
                 payload={"scheduled_date": when})


def send_test(tenant: str, activity_id: str, emails: list[str]) -> dict:
    """A preview to named addresses. Safe, and the thing to reach for first."""
    if not emails:
        return {"ok": False, "error": "No address to send the test to."}
    return call(tenant, "POST", f"/emails/activities/{activity_id}/tests",
                 payload={"email_addresses": emails})
