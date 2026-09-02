"""Klaviyo, as far as a DRAFT and not one step further.

Owner, 2026-09-02, testing the email system on Ironside: *"Approved — but the
push to the ESP failed: ironside is connected to Klaviyo, but its send adapter
is not built yet."* The message was correct — `esp.PROFILES` carried a Klaviyo
profile naming an adapter module that did not exist, and `esp.backend` said so
by name rather than returning a None the generator would trip over three calls
later. This is that module.

IT CANNOT SEND, AND THAT IS THE DESIGN. Owner, 2026-08-31: *"Leave it human,
in the ESP."* A campaign created here has no send job attached, so it sits in
Klaviyo as a draft until a person opens it and sends it. There is deliberately
no `send_campaign` in this file — not an unfinished one, not a guarded one.
The absence is the guarantee: code that cannot send cannot send by accident,
and an adapter that could would be one config flag away from a send nobody
reviewed. Omnisend has one because that path was built and reviewed before the
rule was stated; a new adapter starts on the right side of it.

THE LIVE ROUND TRIP IS UNVERIFIED. Every shape here follows Klaviyo's
documented API, and the suite drives each path through the seam below — but no
call has been made against a real Klaviyo account, because none is connected
here. What that means precisely: the request shapes, the auth, the refusals
and the draft-only guarantee are tested; whether Klaviyo accepts these exact
bodies is not. The first real push is the proof, and its errors surface
verbatim rather than as "Klaviyo rejected it" so that first attempt is
diagnosable.
"""
from . import config, credentials as cred

BASE = "https://a.klaviyo.com/api"
TIMEOUT = 30

#: Klaviyo versions its API by DATE and rejects a call with no `revision`
#: header. Pinned rather than floating: a new revision changes response shapes,
#: and an adapter that silently follows the newest one breaks on a day nobody
#: deployed anything.
REVISION = getattr(config, "KLAVIYO_API_REVISION", "") or "2024-10-15"


def _key(tenant: str) -> tuple:
    c = cred.resolve(tenant, "klaviyo")
    secret = (c or {}).get("secret", "")
    if not secret:
        return "", (f"{tenant} has no Klaviyo connection — connect it on the "
                    f"Accounts tab before anything can be drafted into it.")
    return secret, ""


def _call(tenant: str, method: str, path: str, *, payload=None, params=None) -> dict:
    """One authenticated call. `{ok, data}` or `{ok: False, error}`.

    Klaviyo returns a JSON:API error array whose `detail` names the field it
    refused and why. That is carried through verbatim — "campaign-messages
    relationship is required" tells somebody what to fix, and "Klaviyo
    rejected the campaign" does not, which matters most on the first real call
    from an adapter no live account has exercised.
    """
    secret, why = _key(tenant)
    if why:
        return {"ok": False, "error": why}
    import httpx
    try:
        r = httpx.request(
            method, f"{BASE}{path}",
            headers={"Authorization": f"Klaviyo-API-Key {secret}",
                     "accept": "application/vnd.api+json",
                     "content-type": "application/vnd.api+json",
                     "revision": REVISION},
            json=payload, params=params, timeout=TIMEOUT)
    except Exception as exc:                                     # noqa: BLE001
        return {"ok": False, "error": f"{exc.__class__.__name__}: {str(exc)[:160]}"}

    if r.status_code in (401, 403):
        return {"ok": False, "error": "Klaviyo rejected the API key — re-check "
                                      "it on the Accounts tab. A private key "
                                      "(pk_…) is required; a public site id "
                                      "cannot create campaigns."}
    if r.status_code >= 400:
        try:
            body = r.json()
        except Exception:                                        # noqa: BLE001
            body = {}
        detail = " · ".join(
            str(e.get("detail") or e.get("title") or "")
            for e in (body.get("errors") or []) if isinstance(e, dict))
        return {"ok": False,
                "error": f"{r.status_code}: {detail or r.text[:160]}"[:400]}
    try:
        return {"ok": True, "data": r.json()}
    except Exception:                                            # noqa: BLE001
        return {"ok": True, "data": {}}


# Replaceable so the suite can drive every path without a live account.
from . import toolcalls as _tc  # noqa: E402
call = _tc.instrument('klaviyo', _call)


def segments(tenant: str) -> dict:
    """The audiences a campaign can be aimed at.

    `esp.PROFILES["klaviyo"]["audience_fn"]` names this, and the console reads
    it to offer the owner a list rather than a box to type an id into.
    """
    got = call(tenant, "GET", "/segments/", params={"page[size]": 100})
    if not got["ok"]:
        return {"ok": False, "error": got["error"], "segments": []}
    out = []
    for row in (got["data"] or {}).get("data") or []:
        attrs = row.get("attributes") or {}
        out.append({"id": row.get("id", ""), "name": attrs.get("name", "")})
    return {"ok": True, "segments": out}


def create_template(tenant: str, name: str, html: str) -> dict:
    """File the HTML as a reusable template, which the message then points at."""
    got = call(tenant, "POST", "/templates/", payload={
        "data": {"type": "template",
                 "attributes": {"name": name[:120], "editor_type": "CODE",
                                "html": html}}})
    if not got["ok"]:
        return {"ok": False, "error": got["error"]}
    tid = ((got["data"] or {}).get("data") or {}).get("id", "")
    if not tid:
        return {"ok": False, "error": "Klaviyo accepted the template and "
                                      "returned no id, so nothing can "
                                      "reference it."}
    return {"ok": True, "template_id": tid}


def create_draft_campaign(tenant: str, *, name: str, subject: str,
                          sender_name: str, preheader: str = "",
                          include_segments=None) -> dict:
    """A campaign with NO send job — a draft, and nothing more.

    `send_strategy` is deliberately absent. Klaviyo only sends when a send job
    is created against the campaign, and nothing in this module creates one.
    """
    segs = [s for s in (include_segments or []) if str(s or "").strip()]
    if not segs:
        # NAMED, not defaulted to everybody. A campaign aimed at the whole list
        # because nobody chose is the one mistake an ESP cannot undo.
        return {"ok": False,
                "error": ("no audience — a Klaviyo campaign needs at least one "
                          "segment or list, and sending to everyone because "
                          "nothing was chosen is not a default worth having.")}
    got = call(tenant, "POST", "/campaigns/", payload={
        "data": {
            "type": "campaign",
            "attributes": {
                "name": name[:120],
                "audiences": {"included": segs, "excluded": []},
                "campaign-messages": {"data": [{
                    "type": "campaign-message",
                    "attributes": {
                        "definition": {
                            "channel": "email",
                            "label": name[:120],
                            "content": {
                                "subject": subject[:150],
                                "preview_text": preheader[:150],
                                "from_label": sender_name[:100],
                            }}}}]},
            }}})
    if not got["ok"]:
        return {"ok": False, "error": got["error"]}
    data = (got["data"] or {}).get("data") or {}
    cid = data.get("id", "")
    if not cid:
        return {"ok": False, "error": "Klaviyo accepted the campaign and "
                                      "returned no id, so nothing here can "
                                      "point at it."}
    msg_id = ""
    for rel in ((data.get("relationships") or {})
                .get("campaign-messages", {}).get("data") or []):
        msg_id = rel.get("id", "") or msg_id
    return {"ok": True, "campaign_id": cid, "message_id": msg_id}


def assign_template(tenant: str, message_id: str, template_id: str) -> dict:
    """Point the campaign's message at the template holding the HTML."""
    if not message_id:
        return {"ok": False, "error": "the campaign returned no message id, so "
                                      "there is nothing to attach the HTML to."}
    got = call(tenant, "POST", "/campaign-message-assign-template/", payload={
        "data": {"type": "campaign-message",
                 "id": message_id,
                 "relationships": {"template": {
                     "data": {"type": "template", "id": template_id}}}}})
    return {"ok": True} if got["ok"] else {"ok": False, "error": got["error"]}


def draft_from_html(tenant: str, *, name: str, subject: str, sender_name: str,
                    html: str, preheader: str = "",
                    include_segments=None) -> dict:
    """Finished HTML to a reviewable draft, in one call. NEVER a send.

    Both halves are reported even when the second fails: a template that
    imported and a campaign that did not is a real state somebody has to clean
    up in Klaviyo, and returning only the error would leave an orphan in the
    account with nothing naming it. Same contract as Omnisend's, because
    `esp.backend` calls them through one name.
    """
    tpl = create_template(tenant, name, html)
    if not tpl["ok"]:
        return {**tpl, "stage": "template"}
    camp = create_draft_campaign(
        tenant, name=name, subject=subject, sender_name=sender_name,
        preheader=preheader, include_segments=include_segments)
    if not camp["ok"]:
        return {**camp, "stage": "campaign", "template_id": tpl["template_id"],
                "orphan": f"template {tpl['template_id']} was created and is "
                          f"not referenced by any campaign"}
    att = assign_template(tenant, camp.get("message_id", ""),
                          tpl["template_id"])
    if not att["ok"]:
        return {**att, "stage": "attach", "campaign_id": camp["campaign_id"],
                "template_id": tpl["template_id"],
                "orphan": f"campaign {camp['campaign_id']} exists with no HTML "
                          f"attached — open it in Klaviyo or delete it"}
    return {"ok": True, "stage": "done", "campaign_id": camp["campaign_id"],
            "template_id": tpl["template_id"]}
