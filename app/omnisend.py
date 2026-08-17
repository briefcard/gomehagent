"""Omnisend: the send path for `campaign_email`.

Connecting Omnisend used to turn on the `esp` capability and nothing else —
`campaign_email` would install, pass readiness, go live in shadow, and have no
way to put an email anywhere. The only code that touched the provider was the
probe that validates its key.

The shape of the API decides the shape of this module, and it happens to match
the architecture already: **a campaign is created as a draft, and sending it is
a separate call.** So nothing here sends as a side effect of producing
something. `create_draft_campaign` is what a skill may reach; `send_campaign`
takes an explicit confirmation and is meant for the approval queue, never for a
skill's autonomy rung. An email campaign is irreversible and arrives in
thousands of inboxes at once — `auto` was never supposed to mean that.

Two rules taken from Omnisend's own documentation because getting them wrong is
expensive rather than merely broken:

  · `senderEmail` and `replyToEmail` are ALWAYS omitted. Which addresses a
    brand may send from follows from its sender setup, is not discoverable
    through the API, and an invented or copied address is rejected. Omitting
    them uses the brand's verified sender. If it has none the API returns 422
    `sender-email-not-available`, and that is a question for the owner, not a
    field to fill in — so it is surfaced with that wording rather than retried.

  · `language` is left unset unless given. It defaults to `en_US`, and a
    guessed locale fails on format or on value.
"""
from __future__ import annotations

from . import credentials as cred

BASE = "https://api.omnisend.com"
TIMEOUT = 30


def _key(tenant: str) -> tuple[str, str]:
    c = cred.resolve(tenant, "omnisend")
    secret = (c or {}).get("secret", "")
    if not secret:
        return "", (f"{tenant} has no Omnisend connection — connect it on the "
                    f"Accounts tab before anything can be drafted into it.")
    return secret, ""


def _call(tenant: str, method: str, path: str, *, payload: dict | None = None,
          params: dict | None = None) -> dict:
    """One authenticated call. Returns `{ok, data}` or `{ok: False, error}`.

    The API's own field and code are carried through rather than flattened into
    a sentence: "content.email.templateID required" tells the caller what to
    fix, and "Omnisend rejected the campaign" does not.
    """
    secret, why = _key(tenant)
    if why:
        return {"ok": False, "error": why}
    import httpx
    try:
        r = httpx.request(method, f"{BASE}{path}",
                          headers={"X-API-KEY": secret,
                                   "Content-Type": "application/json"},
                          json=payload, params=params, timeout=TIMEOUT)
    except Exception as exc:                                     # noqa: BLE001
        return {"ok": False, "error": f"{exc.__class__.__name__}: {str(exc)[:160]}"}

    if r.status_code in (401, 403):
        return {"ok": False, "error": "Omnisend rejected the API key — "
                                      "re-check it on the Accounts tab."}
    if r.status_code >= 400:
        try:
            body = r.json()
        except Exception:                                        # noqa: BLE001
            body = {}
        detail = ""
        for f in (body.get("fields") or body.get("errors") or []):
            if isinstance(f, dict):
                detail += f" · {f.get('field', '')}: {f.get('code', '') or f.get('message', '')}"
        msg = body.get("message") or body.get("error") or r.text[:160]
        if "sender-email-not-available" in str(body) + r.text:
            return {"ok": False, "needs_owner": True,
                    "error": ("Omnisend has no verified sender address for this "
                              "brand, so there is no address to send from. Add "
                              "and verify one in Omnisend's account settings — "
                              "retrying cannot fix it and an address invented "
                              "here would be rejected.")}
        return {"ok": False, "error": f"{r.status_code}: {msg}{detail}"[:400]}
    try:
        return {"ok": True, "data": r.json()}
    except Exception:                                            # noqa: BLE001
        return {"ok": True, "data": {}}


# Replaceable so the suite can drive every path — including the ones that would
# otherwise need a live account and a real send.
call = _call


def segments(tenant: str) -> dict:
    """Audience segments, for targeting a campaign."""
    res = call(tenant, "GET", "/api/segments")
    if not res["ok"]:
        return res
    rows = (res["data"] or {}).get("segments") or []
    return {"ok": True, "segments": [{"id": s.get("segmentID") or s.get("id"),
                                      "name": s.get("name", "")} for s in rows]}


def import_template(tenant: str, name: str, html: str) -> dict:
    """Turn finished HTML into an Omnisend template. Step one of two.

    `templateID` is required at campaign creation even for a draft — there is
    no "save an incomplete draft and finish it later" path — so the template
    has to exist first.
    """
    if not (html or "").strip():
        return {"ok": False, "error": "There is no HTML to import."}
    res = call(tenant, "POST", "/api/email-templates/import",
               payload={"name": name[:255] or "Untitled", "html": html})
    if not res["ok"]:
        return res
    d = res["data"] or {}
    tid = d.get("templateID") or d.get("id") or ""
    if not tid:
        return {"ok": False, "error": "Omnisend accepted the template but "
                                      "returned no id, so nothing can "
                                      "reference it."}
    return {"ok": True, "template_id": tid}


def create_draft_campaign(tenant: str, *, name: str, subject: str,
                          sender_name: str, template_id: str,
                          preheader: str = "",
                          include_segments: list[str] | None = None,
                          exclude_segments: list[str] | None = None) -> dict:
    """Create the campaign. It lands as a DRAFT and does not send.

    Deliberately takes no scheduling arguments. A schedule is a send with a
    delay on it, and the decision to send belongs to a human at the approval
    step — offering `scheduledAt` here would let a skill set one and call it
    drafting.
    """
    missing = [n for n, v in (("subject", subject), ("senderName", sender_name),
                              ("templateID", template_id)) if not (v or "").strip()]
    if missing:
        return {"ok": False,
                "error": f"Omnisend requires {', '.join(missing)} even for a "
                         f"draft — it rejects the create and saves nothing."}

    email: dict = {"subject": subject[:250], "senderName": sender_name[:250],
                   "templateID": template_id}
    if preheader:
        email["preheader"] = preheader[:250]
    payload: dict = {"name": (name or subject)[:250], "type": "regular",
                     "channel": "email", "content": {"email": email}}
    audience = {}
    if include_segments:
        audience["includedSegmentIDs"] = list(include_segments)
    if exclude_segments:
        audience["excludedSegmentIDs"] = list(exclude_segments)
    if audience:
        payload["audience"] = audience

    res = call(tenant, "POST", "/api/campaigns", payload=payload)
    if not res["ok"]:
        return res
    d = res["data"] or {}
    # The campaign id is the TOP-LEVEL id. `contentID` addresses the design and
    # `templateID` the source template, and using either as the campaign id
    # fails later, somewhere else.
    cid = d.get("id") or ""
    if not cid:
        return {"ok": False, "error": "Omnisend returned no campaign id."}
    return {"ok": True, "campaign_id": cid,
            "content_id": ((d.get("content") or {}).get("email") or {}).get("contentID", ""),
            "status": d.get("status", "draft"),
            "note": "draft — nothing has been sent. Sending is a separate, "
                    "explicit act."}


def send_campaign(tenant: str, campaign_id: str, confirm: bool = False) -> dict:
    """Send a drafted campaign. Irreversible.

    `confirm` exists so this cannot be reached by accident from a loop that was
    only meant to produce something. **The skill substrate never calls this.**
    It is here for the approval queue, where a human has read the draft and
    decided — the same boundary `ledger.publish` draws, at a much larger blast
    radius: an email campaign lands in thousands of inboxes at once and has no
    undo.
    """
    if not confirm:
        return {"ok": False, "error": "Refused: sending needs an explicit "
                                      "confirmation. Approve the draft rather "
                                      "than calling this directly."}
    res = call(tenant, "POST", f"/api/campaigns/{campaign_id}/send")
    if not res["ok"]:
        return res
    return {"ok": True, "campaign_id": campaign_id,
            "status": (res["data"] or {}).get("status", "started")}


def send_test(tenant: str, campaign_id: str, emails: list[str]) -> dict:
    """A test send to named addresses. The safe way to look at a draft."""
    if not emails:
        return {"ok": False, "error": "Name at least one address."}
    return call(tenant, "POST", f"/api/campaigns/{campaign_id}/test-email",
                payload={"emails": list(emails)})


def upload_image(tenant: str, url: str) -> dict:
    """Put an image into Omnisend by URL, for use inside an email."""
    if not (url or "").strip():
        return {"ok": False, "error": "No image URL."}
    res = call(tenant, "POST", "/api/images", payload={"url": url})
    if not res["ok"]:
        return res
    d = res["data"] or {}
    return {"ok": True, "image_id": d.get("imageID") or d.get("id", ""),
            "url": d.get("url", "")}


def draft_from_html(tenant: str, *, name: str, subject: str, sender_name: str,
                    html: str, preheader: str = "",
                    include_segments: list[str] | None = None) -> dict:
    """Finished HTML to a reviewable draft, in one call.

    Both halves are reported even when the second fails: a template that
    imported and a campaign that did not is a real state somebody has to clean
    up, and returning only the error would leave an orphan in the account with
    nothing naming it.
    """
    tpl = import_template(tenant, name, html)
    if not tpl["ok"]:
        return {**tpl, "stage": "template"}
    camp = create_draft_campaign(
        tenant, name=name, subject=subject, sender_name=sender_name,
        template_id=tpl["template_id"], preheader=preheader,
        include_segments=include_segments)
    if not camp["ok"]:
        return {**camp, "stage": "campaign", "template_id": tpl["template_id"],
                "orphan": f"template {tpl['template_id']} was created and is "
                          f"not referenced by any campaign"}
    return {**camp, "stage": "done", "template_id": tpl["template_id"]}
