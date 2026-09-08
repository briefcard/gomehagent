"""Canva Connect: assets and designs, filed per account on both sides.

Two things had to be true before this was worth building, and the second is the
one Gomeh asked for explicitly.

**Every call is scoped to one account.** A Canva connection is a whole team's
workspace. Nothing here takes a folder id from a caller — the folder is looked
up from the tenant row, and `_folder` creates it if it is missing. A design
cannot be filed into another client's folder because there is no argument for
saying which folder to use. That is the same reasoning as `tool_scope` stripping
the account parameter out of a tool's schema: a boundary the caller cannot
express is a boundary the caller cannot cross.

**What Canva holds and what we hold must agree.** A design that exists in Canva
and not in `KbAsset` is invisible to every skill and to the creative library's
feedback loops; a row that names a design nobody can open is worse. So
`create_design` does both and reports it, and `reconcile` is how you find out
they have drifted rather than assuming they have not.

Nothing here publishes. An exported file is a URL that goes into the ledger like
any other output and waits for the same approval.
"""
from __future__ import annotations

from . import credentials as cred, db, kb, tenants

BASE = "https://api.canva.com/rest/v1"
TIMEOUT = 60
# Everything this platform makes for a client lives under one root, so a team
# that also uses Canva by hand keeps its own work separate from ours.
ROOT_NAME = "Client work — gomehagent"


#: What a DEFINITIVE refusal of a stored token says. The provider said no —
#: not the network, not a timeout.
_REJECTED = ("revoked", "invalid_grant", "invalid grant", "sign-in was rejected",
             "rejected", "expired")


def _rejected(err: str) -> bool:
    low = (err or "").lower()
    if "connecterror" in low or "timeout" in low or "timed out" in low:
        return False
    return any(m in low for m in _REJECTED)


def which_account(tenant: str) -> dict:
    """Whose Canva serves this account right now — `client`, `agency` or
    "" — and, when it is the agency's BECAUSE the client's own connection
    failed, the sentence that says so. Read off durable state (the failed
    row, the resolver), so the frame, the run and the Accounts tab all say
    the same thing."""
    c = cred.resolve(tenant, "canva") or {}
    source = str(c.get("source") or "") if c.get("secret") else ""
    note = ""
    if source == "agency":
        with db.SessionLocal() as s:
            own = (s.query(db.Credential)
                   .filter(db.Credential.tenant == tenant,
                           db.Credential.provider == "canva",
                           db.Credential.status == "failed")
                   .order_by(db.Credential.granted_at.desc()).first())
            why = (own.last_error or "") if own is not None else ""
            had = own is not None
        if had:
            t = tenants.get(tenant)
            name = (getattr(t, "name", "") or tenant) if t else tenant
            note = (f"{name}'s own Canva connection was revoked ({why[:80]}); "
                    f"designs go to the agency's Canva, in the {name} folder. "
                    f"Reconnect theirs on the Accounts tab to switch back.")
    return {"source": source, "note": note}


def _token(tenant: str) -> tuple[str, str]:
    """A live access token, minted from the refresh token we stored.

    This used to hand the STORED secret to Canva as the bearer. `oauth.exchange`
    keeps the refresh token for this provider — deliberately, an access token
    dies in an hour and is not worth a row — so the value being sent was never
    one Canva would accept. Every call would have come back 401 while the
    console showed a green chip, which is the failure mode this codebase keeps
    writing down: a positive claim that has stopped being tested. It survived
    because no Canva call has ever been made for real.
    """
    c = cred.resolve(tenant, "canva")
    secret = (c or {}).get("secret", "")
    if secret:
        # THROUGH THE ONE DOOR. Minting here from the stored token on every
        # call spent Canva's single-use refresh token twice per edit and
        # took the lineage with it (owner, 2026-09-07: "Refresh token used
        # twice. All access tokens granted from this flow are now revoked").
        # `cred.bearer` caches the access token on the row for its lifetime
        # and stores each rotation before the token it bought is used.
        got = cred.bearer(tenant, "canva")
        if got.get("ok"):
            return got["token"], ""
        err = str(got.get("error", ""))
        # A REVOKED CONNECTION IS NOT A CONNECTION. Owner, 2026-09-07: *"Canva
        # would not renew the token for baci: Sign-in was rejected: Token
        # lineage has been revoked"* — returned as an error one line above
        # the text that promises the agency's connection serves every
        # account. `resolve` already falls through to the agency for a
        # client with no ACTIVE row; a revoked lineage left the row active
        # and failing, so the fallback that existed was never reached. A
        # DEFINITIVE rejection therefore marks the row failed — where the
        # Accounts tab shows it and says reconnect — and re-resolves. A
        # transient error does not: switching a client's designs into the
        # agency's Canva on a timeout is how "why is our design in their
        # Canva" starts.
        if (c or {}).get("source") == "client" and _rejected(err):
            cred.record_failure(tenant, "canva", err)
            shared = cred.resolve(tenant, "canva") or {}
            if shared.get("secret") and shared.get("source") == "agency":
                again = cred.bearer(tenant, "canva")
                if again.get("ok"):
                    return again["token"], ""
                return "", (f"{tenant}'s own Canva connection was revoked "
                            f"({err[:80]}) and the agency's would not renew "
                            f"either: {str(again.get('error', ''))[:80]} — "
                            f"reconnect on the Accounts tab.")
            return "", (f"{tenant}'s own Canva connection was revoked "
                        f"({err[:80]}) and the agency has no Canva connection "
                        f"to fall back to — connect one on the Accounts tab.")
        return "", (f"Canva would not renew the token for {tenant}: {err} — "
                    f"reconnect it on the Accounts tab.")
    if not secret:
        return "", (f"{tenant} has no Canva connection, and neither has the "
                    f"agency — connect one on the Accounts tab. The agency's "
                    f"own connection serves every account (each filed in its "
                    f"own folder), so connecting it once is usually enough; a "
                    f"client who connects their own overrides it. Canva "
                    f"Connect is OAuth, so it needs CANVA_CLIENT_ID / "
                    f"CANVA_CLIENT_SECRET set first.")
    return secret, ""


def _call(tenant: str, method: str, path: str, *, payload: dict | None = None,
          params: dict | None = None) -> dict:
    secret, why = _token(tenant)
    if why:
        return {"ok": False, "error": why}
    import httpx
    try:
        r = httpx.request(method, f"{BASE}{path}", timeout=TIMEOUT,
                          headers={"Authorization": f"Bearer {secret}",
                                   "Content-Type": "application/json"},
                          json=payload, params=params)
    except Exception as exc:                                     # noqa: BLE001
        return {"ok": False, "error": f"{exc.__class__.__name__}: {str(exc)[:160]}"}
    if r.status_code in (401, 403):
        return {"ok": False, "error": "Canva rejected the token — reconnect on "
                                      "the Accounts tab."}
    if r.status_code >= 400:
        try:
            body = r.json()
        except Exception:                                        # noqa: BLE001
            body = {}
        return {"ok": False,
                "error": f"{r.status_code}: "
                         f"{body.get('message') or r.text[:200]}"[:300]}
    try:
        return {"ok": True, "data": r.json()}
    except Exception:                                            # noqa: BLE001
        return {"ok": True, "data": {}}


UPLOAD_NAME_MAX = 50


def _call_binary(tenant: str, path: str, blob: bytes, name: str) -> dict:
    """Upload raw bytes. Canva takes the name base64'd in a header, not a form.

    The URL variant is no use for anything this platform composes: a rendered
    ad exists as bytes in memory, and putting it somewhere public purely so
    Canva can fetch it back would mean publishing an unapproved draft to get it
    reviewed.
    """
    import base64 as _b64

    secret, why = _token(tenant)
    if why:
        return {"ok": False, "error": why}
    import httpx
    # `name_base64` is capped at 50 characters UNENCODED —
    # https://www.canva.dev/docs/connect/api-reference/assets/create-asset-upload-job/
    meta = _b64.b64encode(name[:UPLOAD_NAME_MAX].encode()).decode()
    try:
        r = httpx.post(f"{BASE}{path}", timeout=TIMEOUT, content=blob,
                       headers={"Authorization": f"Bearer {secret}",
                                "Content-Type": "application/octet-stream",
                                "Asset-Upload-Metadata":
                                    '{"name_base64":"%s"}' % meta})
    except Exception as exc:                                     # noqa: BLE001
        return {"ok": False, "error": f"{exc.__class__.__name__}: {str(exc)[:160]}"}
    if r.status_code >= 400:
        return {"ok": False, "error": f"{r.status_code}: {r.text[:200]}"}
    try:
        return {"ok": True, "data": r.json()}
    except Exception:                                            # noqa: BLE001
        return {"ok": True, "data": {}}


#: DESIGN IMPORTS — the documented way a file becomes an editable design:
#: `POST /v1/imports`, body = the bytes, `Content-Type: application/octet-stream`,
#: `Import-Metadata: {"title_base64", "mime_type"}`; title ≤ 50 characters
#: unencoded; then `GET /v1/imports/{jobId}` until `success` (result.designs[])
#: or `failed` (error.message). PowerPoint is among the accepted types, and
#: each object on a slide arrives as its own element — which is how a frame
#: reaches Canva as LAYERS (`layers.deck`) rather than one flat picture.
IMPORTS_DOC = "https://www.canva.dev/docs/connect/api-reference/design-imports/create-design-import-job/"
PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
IMPORT_POLLS, IMPORT_POLL_S = 12, 1.5
#: A 5xx from the import is Canva's side: tried once more after a pause.
IMPORT_TRIES, IMPORT_RETRY_S = 2, 2.0


def _server_side(err: str) -> bool:
    """Whether an error text is Canva's own failure (a 5xx), not ours."""
    head = (err or "").strip()[:3]
    return head.isdigit() and head.startswith("5")


def _call_import(tenant: str, blob: bytes, title: str, mime: str) -> dict:
    """`POST /imports` exactly as documented (IMPORTS_DOC)."""
    import base64 as _b64

    secret, why = _token(tenant)
    if why:
        return {"ok": False, "error": why}
    import httpx
    meta = _b64.b64encode(title[:UPLOAD_NAME_MAX].encode()).decode()
    try:
        r = httpx.post(f"{BASE}/imports", timeout=TIMEOUT, content=blob,
                       headers={"Authorization": f"Bearer {secret}",
                                "Content-Type": "application/octet-stream",
                                "Import-Metadata":
                                    '{"title_base64":"%s","mime_type":"%s"}' % (meta, mime)})
    except Exception as exc:                                     # noqa: BLE001
        return {"ok": False, "error": f"{exc.__class__.__name__}: {str(exc)[:160]}"}
    if r.status_code in (401, 403):
        return {"ok": False, "error": "Canva rejected the token — reconnect on "
                                      "the Accounts tab."}
    if r.status_code >= 400:
        return {"ok": False, "error": f"{r.status_code}: {r.text[:200]}"}
    try:
        return {"ok": True, "data": r.json()}
    except Exception:                                            # noqa: BLE001
        return {"ok": True, "data": {}}


from . import toolcalls as _tc  # noqa: E402
call = _tc.instrument('canva', _call)          # replaceable, so the suite can drive every path
call_binary = _call_binary
call_import = _call_import


# ---------------------------------------------------------------------------
# The MCP transport — Canva's own server, called from THIS adapter.
#
# ARCHITECTURE.md: MCP is a transport, not an authority. These functions sit
# in the same seam as `call`, use the same per-tenant token, and file the same
# `toolcalls` rows — so switching a read from REST to MCP changes nothing
# about scoping, approval or the ledger. Tool NAMES are deliberately not
# guessed here: `/admin/canva_probe` lists the live server's real names first,
# and the adapter maps exact names as they are learned (the esp.PROFILES
# discipline, applied to tools).
# ---------------------------------------------------------------------------

def mcp_session(tenant: str):
    """An authenticated MCP session for this tenant: `(session, "")` or
    `(None, why)`. Uses the same OAuth token the REST calls mint — VERIFY on
    first live call whether Canva's MCP accepts it or wants its own grant."""
    from . import config, mcp_client
    if not config.CANVA_MCP_URL:
        return None, "CANVA_MCP_URL is empty — the MCP transport is disabled."
    secret, why = _token(tenant)
    if why:
        return None, why
    return mcp_client.open_session(config.CANVA_MCP_URL, secret)


def mcp_tools(tenant: str) -> dict:
    """The live server's tool inventory — the first probe's whole purpose."""
    from . import mcp_client
    sess, why = mcp_session(tenant)
    if why:
        _tc.record(tenant, "canva.mcp.tools", provider="canva", ok=False,
                   error=why[:200])
        return {"ok": False, "error": why}
    got = mcp_client.tools(sess)
    _tc.record(tenant, "canva.mcp.tools", provider="canva",
               ok=bool(got.get("ok")), error=(got.get("error") or "")[:200])
    return got


def mcp_call(tenant: str, tool: str, arguments: dict | None = None) -> dict:
    """One MCP tool call, instrumented like every other adapter round trip."""
    from . import mcp_client
    sess, why = mcp_session(tenant)
    if why:
        _tc.record(tenant, f"canva.mcp.{tool}", provider="canva", ok=False,
                   error=why[:200])
        return {"ok": False, "error": why}
    got = mcp_client.tool_call(sess, tool, arguments)
    _tc.record(tenant, f"canva.mcp.{tool}", provider="canva",
               ok=bool(got.get("ok")), error=(got.get("error") or "")[:200])
    return got


# ---------------------------------------------------------------------------
# Where a tenant's work lives
# ---------------------------------------------------------------------------

def _remember_folder(tenant: str, folder_id: str, source: str = "agency") -> None:
    """Keep the folder id on the tenant row so it is found, not searched for.

    Searching by name every time would eventually match a folder somebody
    renamed, or create a second one with the same name — and two folders called
    "Baci Milano USA" is exactly the state where work starts going into the
    wrong one.
    """
    with db.SessionLocal() as s:
        row = s.get(db.Tenant, tenant)
        if not row:
            return
        design = dict(row.design or {})
        # PER ACCOUNT. A folder made in Baci's own Canva does not exist in the
        # agency's; remembering one id for both is how the fallback made the
        # design and failed to file it (2026-09-07). The legacy key is left
        # as it was — `_remembered_folder` says whose it is.
        folders = dict(design.get("canva_folders") or {})
        folders[source] = folder_id
        design["canva_folders"] = folders
        row.design = design
        s.commit()


def _forget_folder(tenant: str, source: str) -> None:
    with db.SessionLocal() as s:
        row = s.get(db.Tenant, tenant)
        if not row:
            return
        design = dict(row.design or {})
        folders = dict(design.get("canva_folders") or {})
        folders.pop(source, None)
        design["canva_folders"] = folders
        row.design = design
        s.commit()


def _remembered_folder(tenant: str, design: dict, source: str) -> str:
    """The folder remembered for THIS account, or "". A folder remembered
    before accounts were told apart belongs to the account that made it: the
    client's if this client ever connected their own Canva, else the
    agency's."""
    known = dict(design.get("canva_folders") or {})
    if known.get(source):
        return str(known[source])
    legacy = str(design.get("canva_folder_id") or "")
    if not legacy:
        return ""
    with db.SessionLocal() as s:
        had_own = (s.query(db.Credential)
                   .filter(db.Credential.tenant == tenant,
                           db.Credential.provider == "canva").first()) is not None
    return legacy if (source == "client") == had_own else ""


def _root_key(tenant: str, source: str) -> str:
    """The agency's root is the legacy setting; a client's own Canva gets a
    root of its own, in their account."""
    return "canva_root_folder" if source == "agency" else f"canva_root_folder:{tenant}"


def folder(tenant: str) -> dict:
    """This account's folder id, creating the folder the first time.

    Returns `{ok, folder_id, created}`.
    """
    t = tenants.get(tenant)
    if not t:
        return {"ok": False, "error": f"unknown tenant {tenant!r}"}
    # WHOSE ACCOUNT, first: the folder is remembered per account, because a
    # folder made in the client's own Canva does not exist in the agency's.
    source = which_account(tenant).get("source") or "agency"
    known = _remembered_folder(tenant, dict(t.design or {}), source)
    if known:
        return {"ok": True, "folder_id": known, "created": False, "source": source}

    # The root first, then the account inside it. Two levels, so a Canva team
    # that also works by hand is not looking at a flat list of client names at
    # the top of its own workspace.
    #
    # The ROOT is remembered too, and it did not used to be. Only the
    # per-tenant folder id was cached, so the first run for every NEW account
    # created another root — five clients, five folders all called "Client
    # work — gomehagent" at the top of the workspace, each holding one client.
    # That is precisely the duplicate-by-name failure `_remember_folder` was
    # written to prevent, done to the level above it. The root is one folder
    # for the whole installation, so it belongs in a Setting rather than on a
    # tenant row.
    root_id = ""
    with db.SessionLocal() as _s:
        _row = _s.get(db.Setting, _root_key(tenant, source))
        root_id = (_row.value if _row else "") or ""
    if not root_id:
        root = call(tenant, "POST", "/folders",
                    payload={"name": ROOT_NAME, "parent_folder_id": "root"})
        if not root["ok"]:
            return root
        root_id = ((root["data"] or {}).get("folder") or {}).get("id", "")
        if not root_id:
            return {"ok": False, "error": "Canva created no root folder id."}
        with db.SessionLocal() as _s:
            _s.merge(db.Setting(key=_root_key(tenant, source), value=root_id))
            _s.commit()

    made = call(tenant, "POST", "/folders",
                payload={"name": f"{t.name} ({tenant})",
                         "parent_folder_id": root_id})
    if not made["ok"]:
        return made
    fid = ((made["data"] or {}).get("folder") or {}).get("id", "")
    if not fid:
        return {"ok": False, "error": "Canva created no folder id."}
    _remember_folder(tenant, fid, source)
    return {"ok": True, "folder_id": fid, "created": True, "root_id": root_id,
            "source": source}


def _file_into_folder(tenant: str, item_id: str) -> dict:
    f = folder(tenant)
    if not f.get("ok"):
        return f
    # THE DOCUMENTED CALL is POST /v1/folders/move with `to_folder_id` and
    # `item_id` (204 on success) —
    # https://www.canva.dev/docs/connect/api-reference/folders/move-folder-item/
    # `POST /folders/{id}/items` was a path this code invented; every design
    # it filed came back with a `filed_error` nobody read (2026-09-07).
    res = call(tenant, "POST", "/folders/move",
               payload={"to_folder_id": f["folder_id"], "item_id": item_id})
    if res.get("ok") or not _gone(str(res.get("error", ""))):
        return res
    # A REMEMBERED FOLDER THAT IS GONE — deleted by hand in Canva, or made in
    # another account — is forgotten and made again, ONCE. Failing the
    # design over a folder id is the "filed_error" nobody reads.
    _forget_folder(tenant, str(f.get("source") or "agency"))
    f2 = folder(tenant)
    if not f2.get("ok"):
        return f2
    res2 = call(tenant, "POST", "/folders/move",
                payload={"to_folder_id": f2["folder_id"], "item_id": item_id})
    return {**res2, "recreated": True}


def _gone(err: str) -> bool:
    low = (err or "").lower()
    return low.startswith("404") or "not found" in low


def upload_asset(tenant: str, url: str, name: str, *,
                 entity_key: str = "", tags: list[str] | None = None,
                 rights: str = kb.OWNED) -> dict:
    """Bring an image into Canva AND record it in the library.

    `rights` is passed through rather than defaulted quietly: a competitor's ad
    uploaded as inspiration and a client's own product shot are the same call
    with a different answer, and `kb.add_asset` refuses without one.
    """
    res = call(tenant, "POST", "/asset-uploads",
               payload={"url": url, "name": name[:255]})
    if not res["ok"]:
        return res
    asset = (res["data"] or {}).get("asset") or {}
    aid = asset.get("id", "")
    if not aid:
        return {"ok": False, "error": "Canva returned no asset id."}

    said = kb.add_asset(tenant, url, rights=rights, title=name, kind="image",
                        source=f"canva asset {aid}", entity_key=entity_key,
                        tags=list(tags or []) + list(asset.get("tags") or []),
                        thumbnail_url=((asset.get("thumbnail") or {})
                                       .get("url", "")),
                        origin="human")
    return {"ok": True, "asset_id": aid, "name": asset.get("name", name),
            "recorded": said, "smart_tags": (asset.get("tags") or [])}


#: THE DOCUMENTED CONTRACT for POST /v1/designs — read from
#: https://www.canva.dev/docs/connect/api-reference/designs/create-design/
#: on 2026-09-07, after a live 400: *"'name' must be one of the following:
#: doc, email, presentation, whiteboard, but was instagram-post"*. There is
#: no social preset; anything else is a CUSTOM design in pixels. Owner:
#: *"make sure you're referencing the api docs when you fix issues associated
#: with a specific tool."* — the URL is here so the next reader can.
PRESETS = ("doc", "email", "presentation", "whiteboard")
CUSTOM_MIN, CUSTOM_MAX, CUSTOM_AREA = 40, 8000, 25_000_000
DESIGNS_DOC = "https://www.canva.dev/docs/connect/api-reference/designs/create-design/"


def design_type_for(*, design_type: str = "", width: int = 0, height: int = 0) -> tuple:
    """The `design_type` object Canva documents, or `(None, why)`."""
    if width or height:
        w, h = int(width or 0), int(height or 0)
        if not (CUSTOM_MIN <= w <= CUSTOM_MAX and CUSTOM_MIN <= h <= CUSTOM_MAX
                and w * h <= CUSTOM_AREA):
            return None, (f"Canva takes custom designs from {CUSTOM_MIN} to "
                          f"{CUSTOM_MAX} px a side and at most {CUSTOM_AREA:,} px "
                          f"of area; {w}×{h} is outside that ({DESIGNS_DOC}).")
        return {"type": "custom", "width": w, "height": h}, ""
    if design_type in PRESETS:
        return {"type": "preset", "name": design_type}, ""
    return None, (f"Canva has no preset {design_type!r} — its presets are "
                  f"{', '.join(PRESETS)}; anything else is a custom design, so "
                  f"pass width and height in pixels ({DESIGNS_DOC}).")


def create_design(tenant: str, *, title: str, design_type: str = "",
                  asset_id: str = "", entity_key: str = "",
                  width: int = 0, height: int = 0, record: bool = True) -> dict:
    """Create a design, file it in this account's folder, record it.

    All three, or it says which part did not happen. A design sitting in Canva
    that nothing in the library names is invisible to every skill — it cannot
    be selected, cannot be credited when it is used, and cannot carry a result.

    `record=False` when the caller ALREADY holds the row the design belongs
    to — a frame handed to Canva by `hosting.to_canva` records the design id
    on itself. Recording it here as well filed a second row of
    `kind="design"` with the same thumbnail, which the pictures queue showed
    as another picture to review (owner, 2026-09-04: "it just duplicates the
    same image to be reviewed").

    `width`/`height` (px) create a CUSTOM-sized design instead of a preset —
    what an email hero needs, since no preset is 1200×600. VERIFY on first
    live call, like everything Canva: the custom design_type shape is from
    public docs and has never met the API.
    """
    dt, why = design_type_for(design_type=design_type, width=width, height=height)
    if why:
        return {"ok": False, "error": why}
    payload: dict = {"design_type": dt, "title": (title or "Design")[:255]}
    if asset_id:
        payload["asset_id"] = asset_id
    res = call(tenant, "POST", "/designs", payload=payload)
    if not res["ok"]:
        return res
    d = (res["data"] or {}).get("design") or {}
    did = d.get("id", "")
    if not did:
        return {"ok": False, "error": "Canva returned no design id."}

    filed = _file_into_folder(tenant, did)
    urls = d.get("urls") or {}
    said = kb.add_asset(
        tenant, urls.get("view_url") or f"https://www.canva.com/design/{did}",
        rights=kb.OWNED, title=title, kind="design",
        source="generated in Canva", entity_key=entity_key,
        canva_design_id=did,
        thumbnail_url=(d.get("thumbnail") or {}).get("url", ""),
        origin="human") if record else "not recorded — the caller's row carries it"
    return {"ok": True, "design_id": did,
            "edit_url": urls.get("edit_url", "") or f"https://www.canva.com/design/{did}/edit",
            "view_url": urls.get("view_url", ""),
            "filed": filed.get("ok", False),
            "filed_error": "" if filed.get("ok") else filed.get("error", ""),
            "recorded": said}


#: EXPORTS — `POST /v1/exports {design_id, format:{type, width?, height?}}`;
#: for png/jpg a `width`/`height` in pixels (40–25000) scales the export,
#: keeping the design's aspect (both given and mismatched → the larger wins).
#: The result's download URLs EXPIRE AFTER 24 HOURS, so `harvest` keeps the
#: bytes rather than the link.
EXPORTS_DOC = "https://www.canva.dev/docs/connect/api-reference/exports/create-design-export-job/"
EXPORT_RESULT_DOC = "https://www.canva.dev/docs/connect/api-reference/exports/get-design-export-job/"
EXPORT_SIDE_MIN, EXPORT_SIDE_MAX = 40, 25000


def export(tenant: str, design_id: str, fmt: str = "png", *,
           width: int = 0, height: int = 0) -> dict:
    """Start an export. Returns the job — Canva finishes it asynchronously.
    `width`/`height` (png/jpg only, EXPORTS_DOC) ask for the picture at a
    placement's size — Meta's recommended 1440×1800 for Feed 4:5, say —
    rather than at whatever size the design happens to be."""
    if fmt not in ("png", "jpg", "pdf", "gif", "mp4", "pptx"):
        return {"ok": False, "error": f"unsupported export format {fmt!r}"}
    form: dict = {"type": fmt}
    if fmt == "jpg":
        form["quality"] = 92
    if fmt in ("png", "jpg"):
        for k, v in (("width", int(width or 0)), ("height", int(height or 0))):
            if v:
                if not (EXPORT_SIDE_MIN <= v <= EXPORT_SIDE_MAX):
                    return {"ok": False, "error": f"export {k} {v} is outside Canva's "
                                                  f"{EXPORT_SIDE_MIN}–{EXPORT_SIDE_MAX} px"}
                form[k] = v
    res = call(tenant, "POST", "/exports",
               payload={"design_id": design_id, "format": form})
    if not res["ok"]:
        return res
    job = (res["data"] or {}).get("job") or {}
    return {"ok": True, "job_id": job.get("id", ""),
            "status": job.get("status", "in_progress"),
            "urls": [u for u in (job.get("urls") or [])]}


def export_result(tenant: str, job_id: str) -> dict:
    res = call(tenant, "GET", f"/exports/{job_id}")
    if not res["ok"]:
        return res
    job = (res["data"] or {}).get("job") or {}
    return {"ok": True, "status": job.get("status", ""),
            "urls": list(job.get("urls") or []),
            "error": (job.get("error") or {}).get("message", "")}


# ---------------------------------------------------------------------------
# Do the two sides still agree?
# ---------------------------------------------------------------------------

def reconcile(tenant: str) -> dict:
    """What Canva holds for this account versus what the library records.

    Drift is not hypothetical: somebody deletes a design in Canva, or moves one
    in by hand, and nothing tells us. Reporting both directions is the point —
    a row naming a design that no longer opens is a worse failure than a design
    nobody has recorded, because a skill will select it and produce output
    pointing at nothing.
    """
    f = folder(tenant)
    if not f["ok"]:
        return f
    res = call(tenant, "GET", f"/folders/{f['folder_id']}/items")
    if not res["ok"]:
        return res
    items = (res["data"] or {}).get("items") or []
    in_canva = {}
    for it in items:
        d = (it.get("design") or {})
        if d.get("id"):
            in_canva[d["id"]] = d.get("title", "")

    rows = kb.assets(tenant, publishable_only=False)
    recorded = {r.canva_design_id: r for r in rows if r.canva_design_id}

    missing_here = [{"design_id": k, "title": v}
                    for k, v in in_canva.items() if k not in recorded]
    missing_there = [{"design_id": k, "title": r.title, "asset_row": r.id}
                     for k, r in recorded.items() if k not in in_canva]
    return {"ok": True, "folder_id": f["folder_id"],
            "in_canva": len(in_canva), "recorded": len(recorded),
            "in_canva_not_recorded": missing_here,
            "recorded_not_in_canva": missing_there,
            "agrees": not missing_here and not missing_there,
            "note": ("a recorded design missing from Canva is the dangerous "
                     "direction — a skill can still select it and produce "
                     "output pointing at nothing")}


# ---------------------------------------------------------------------------
# The brand kit — what the theme deriver reads
# ---------------------------------------------------------------------------

def _normalize_kit(raw: dict) -> dict:
    """Best-effort extraction of {logo_url, colors[], fonts{heading,body}}.

    Written defensively across the shapes the API might plausibly return,
    because no real brand-kit response has ever been seen (VERIFY below) —
    anything unrecognised simply stays absent, and the deriver treats an empty
    kit as an unavailable source rather than inventing values for it.
    """
    colors: list[str] = []
    palettes = raw.get("color_palettes") or raw.get("palettes") or []
    if not palettes and raw.get("colors"):
        palettes = [raw]
    for pal in palettes:
        if not isinstance(pal, dict):
            continue
        for c in (pal.get("colors") or []):
            v = c.get("hex", "") if isinstance(c, dict) else (c if isinstance(c, str) else "")
            v = str(v).strip()
            if v and not v.startswith("#"):
                v = "#" + v
            if v and v not in colors:
                colors.append(v)

    fonts: dict[str, str] = {}
    for f in (raw.get("fonts") or raw.get("text_styles") or []):
        if not isinstance(f, dict):
            continue
        fam = f.get("family") or f.get("font_family") or ""
        if not fam and isinstance(f.get("font"), dict):
            fam = f["font"].get("family", "")
        if not fam:
            continue
        role = str(f.get("role") or f.get("usage") or f.get("name") or "").lower()
        if "head" in role or "title" in role:
            fonts.setdefault("heading", fam)
        elif "body" in role or "paragraph" in role or "text" in role:
            fonts.setdefault("body", fam)
        else:
            fonts.setdefault("heading" if "heading" not in fonts else "body", fam)

    logo = ""
    lg = raw.get("logo")
    if isinstance(lg, dict):
        logo = lg.get("url") or (lg.get("image") or {}).get("url", "")
    for entry in (raw.get("logos") or []):
        if logo:
            break
        if isinstance(entry, dict):
            logo = entry.get("url") or (entry.get("image") or {}).get("url", "")
    return {"logo_url": str(logo or ""), "colors": colors, "fonts": fonts}


def brand_kit(tenant: str) -> dict:
    """The client's Canva brand kit — logo, colours, fonts — normalised.

    Returns ``{ok, brand_kit_id, kit: {logo_url, colors[], fonts{}}}`` or a
    refusal that names the fix. `Tenant.design.canva_brand_id` says which kit
    when the workspace holds several — same rule as `credentials.resolve` with
    two Shopify sites: picking one silently would brand a client with another
    client's kit, so ambiguity refuses and names the choices.

    **VERIFY on the first real call.** Like every Canva path here, this has
    never met the live API — and Canva's public Connect docs are explicit about
    brand *templates* (Enterprise) while the brand-*kit* read below is
    best-effort. If it 404s for real, this refuses by name and the theme
    deriver falls through to the Shopify/site sources by design; that outcome
    is a finding to write down, not a crash.
    """
    t = tenants.get(tenant)
    if not t:
        return {"ok": False, "error": f"unknown tenant {tenant!r}"}
    want = (t.design or {}).get("canva_brand_id") or ""
    if want:
        res = call(tenant, "GET", f"/brand-kits/{want}")
        if not res["ok"]:
            return res
        raw = (res["data"] or {}).get("brand_kit") or res["data"] or {}
    else:
        res = call(tenant, "GET", "/brand-kits")
        if not res["ok"]:
            return res
        items = ((res["data"] or {}).get("items")
                 or (res["data"] or {}).get("brand_kits") or [])
        if not items:
            return {"ok": False,
                    "error": f"{tenant}'s Canva holds no brand kit to read."}
        if len(items) > 1:
            names = ", ".join(str(i.get("name") or i.get("id") or "?")
                              for i in items[:6] if isinstance(i, dict))
            return {"ok": False, "error": (
                f"{tenant}'s Canva holds {len(items)} brand kits — set "
                f"design.canva_brand_id on the tenant row to say which: {names}")}
        raw = items[0] if isinstance(items[0], dict) else {}
    return {"ok": True, "brand_kit_id": str(raw.get("id", "")),
            "kit": _normalize_kit(raw)}


# ---------------------------------------------------------------------------
# From a finished image to something a person can still change
# ---------------------------------------------------------------------------

def upload_bytes(tenant: str, blob: bytes, name: str, *,
                 poll: int = 6) -> dict:
    """Put a rendered image into Canva. Returns the asset id.

    The upload is a job rather than an answer, so this waits for it — but only
    a bounded number of times. A caller left holding "in_progress" has nothing
    to do with it, and an unbounded poll turns a Canva outage into a hung
    request.
    """
    if not blob:
        return {"ok": False, "error": "No image to upload."}
    res = call_binary(tenant, "/asset-uploads", blob, name)
    if not res["ok"]:
        return res
    job = (res["data"] or {}).get("job") or {}
    asset = job.get("asset") or {}
    if asset.get("id"):
        return {"ok": True, "asset_id": asset["id"]}

    job_id = job.get("id", "")
    if not job_id:
        return {"ok": False, "error": "Canva accepted the upload but returned "
                                      "neither an asset nor a job to follow."}
    import time
    for _ in range(max(1, poll)):
        time.sleep(1.2)
        got = call(tenant, "GET", f"/asset-uploads/{job_id}")
        if not got["ok"]:
            return got
        j = (got["data"] or {}).get("job") or {}
        if (j.get("status") or "") == "success":
            aid = ((j.get("asset") or {}).get("id")) or ""
            if aid:
                return {"ok": True, "asset_id": aid}
            return {"ok": False, "error": "upload finished with no asset id"}
        if (j.get("status") or "") == "failed":
            return {"ok": False,
                    "error": (j.get("error") or {}).get("message", "upload failed")}
    return {"ok": False, "error": "the upload was still processing after "
                                  "several checks — try again rather than "
                                  "assuming it failed", "job_id": job_id}


def editable_from_image(tenant: str, blob: bytes, *, title: str,
                        entity_key: str = "", design_type: str = "",
                        record: bool = True) -> dict:
    """A rendered base image, handed to Canva as something still editable.

    This is the join between the two halves. Everything upstream exists to make
    the picture *correct* — the real product, the client's own photograph, a
    claim that passed the validator. None of that survives being retyped, and
    none of it makes a layout a designer would sign off. So the base goes into
    Canva as an asset inside a design, and the typography and composition are
    done there by a person who can see it.

    **Render the base WITHOUT text for this.** Baked type is a picture of
    words: it cannot be corrected, re-weighted, translated or re-flowed for a
    story crop, and the whole reason for handing off to Canva is that those are
    the things a human will want to change. `compose.photo_with_headline` with
    an empty headline gives exactly that.
    """
    # AT THE PICTURE'S OWN SIZE. Canva has no social preset (its four are
    # doc, email, presentation, whiteboard — see PRESETS), so a frame is a
    # CUSTOM design measured off the pixels it carries; "instagram-post" was
    # a name this code made up, and Canva refused it with a 400 on the first
    # live edit (2026-09-07).
    width, height = _size_of(blob)
    if not (width and height) and not design_type:
        return {"ok": False, "stage": "measure",
                "error": "the picture could not be measured, so no design "
                         "size could be chosen"}
    up = upload_bytes(tenant, blob, title)
    if not up["ok"]:
        return {**up, "stage": "upload"}
    made = create_design(tenant, title=title, design_type=design_type,
                         width=width if not design_type else 0,
                         height=height if not design_type else 0,
                         asset_id=up["asset_id"], entity_key=entity_key,
                         record=record)
    if not made["ok"]:
        return {**made, "stage": "design", "asset_id": up["asset_id"],
                "orphan": f"asset {up['asset_id']} is in Canva and no design "
                          f"references it"}
    return {**made, "stage": "done", "asset_id": up["asset_id"],
            "note": "the image is fixed and correct; the text and layout are "
                    "editable in Canva. Nothing here is published."}


def _size_of(blob: bytes) -> tuple:
    """`(width, height)` of an image, or `(0, 0)`."""
    import io as _io
    try:
        from PIL import Image
        im = Image.open(_io.BytesIO(blob))
        return int(im.width), int(im.height)
    except Exception:                                            # noqa: BLE001
        return 0, 0


def import_design(tenant: str, blob: bytes, *, title: str,
                  mime: str = PPTX_MIME, poll: int = IMPORT_POLLS) -> dict:
    """A file — a `layers.deck` — as a new, editable design, filed in this
    account's folder. `{ok, design_id, edit_url, view_url, thumbnail_url,
    filed, filed_error}`; the caller's row records the id.

    The import is a job, so this waits for it a bounded number of times: a
    caller left holding "in_progress" has nothing to do with it, and an
    unbounded poll turns a Canva outage into a hung request.
    """
    if not blob:
        return {"ok": False, "error": "nothing to import"}
    import time as _time
    from . import toolcalls as _tc
    # RECORDED, AND RETRIED ONCE. Owner, 2026-09-08: "Canva: 500: server
    # error" on every layered import, with nothing anywhere saying so but
    # the flash. The call is filed like every other platform round trip,
    # and a 5xx — Canva's side — is tried once more after a pause before
    # the caller is told.
    res: dict = {}
    for attempt in range(IMPORT_TRIES):
        res = call_import(tenant, blob, title, mime)
        _tc.record(tenant, "canva:POST /imports", source="adapter", provider="canva",
                   ok=bool(res.get("ok")), error="" if res.get("ok") else str(res.get("error", "")),
                   bytes_back=len(blob))
        if res.get("ok") or not _server_side(str(res.get("error", ""))) or attempt + 1 >= IMPORT_TRIES:
            break
        _time.sleep(IMPORT_RETRY_S)
    if not res.get("ok"):
        return res
    job = (res.get("data") or {}).get("job") or {}
    job_id = str(job.get("id") or "")
    status = str(job.get("status") or "in_progress")
    import time as _time
    tries = 0
    while status == "in_progress":
        if not job_id:
            return {"ok": False, "error": "Canva accepted the file but returned no "
                                          "job to follow."}
        if tries >= max(1, poll):
            return {"ok": False, "job_id": job_id,
                    "error": "the import was still processing after several "
                             "checks — try again rather than assuming it failed"}
        _time.sleep(IMPORT_POLL_S)
        tries += 1
        got = call(tenant, "GET", f"/imports/{job_id}")
        if not got.get("ok"):
            return got
        job = (got.get("data") or {}).get("job") or {}
        status = str(job.get("status") or "in_progress")
    if status == "failed":
        return {"ok": False, "error": (job.get("error") or {}).get("message")
                or "Canva could not import the file"}
    designs = list(((job.get("result") or {}).get("designs")) or [])
    d = designs[0] if designs else {}
    did = str(d.get("id") or "")
    if not did:
        return {"ok": False, "error": "the import finished with no design id"}
    filed = _file_into_folder(tenant, did)
    urls = d.get("urls") or {}
    return {"ok": True, "design_id": did,
            "edit_url": urls.get("edit_url", "") or f"https://www.canva.com/design/{did}/edit",
            "view_url": urls.get("view_url", ""),
            "thumbnail_url": (d.get("thumbnail") or {}).get("url", ""),
            "filed": filed.get("ok", False),
            "filed_error": "" if filed.get("ok") else filed.get("error", "")}


# ---------------------------------------------------------------------------
# From a finished design to an image an email can actually use
# ---------------------------------------------------------------------------

#: How long to wait for Canva to render an export, and how often to ask.
#: Exports are asynchronous; a header image is a few seconds of work, and a
#: caller that cannot wait that long gets `pending` back rather than a block.
HARVEST_TIMEOUT_S, HARVEST_POLL_S = 25, 2.0


def _download(url: str) -> tuple:
    """`(bytes, mime)` of an export, or `(b"", "")`. A seam for the suite."""
    try:
        import httpx
        r = httpx.get(url, timeout=90, follow_redirects=True)
        if r.status_code >= 400 or not r.content:
            return b"", ""
        return r.content, (r.headers.get("content-type") or "image/png").split(";")[0].strip()
    except Exception:                                            # noqa: BLE001
        return b"", ""


download = _download


def _keep(tenant: str, url: str) -> str:
    """Canva's export link into OUR store, returning our URL — or "" and the
    caller keeps Canva's. The links expire after 24 hours
    (EXPORT_RESULT_DOC): a row pointing at one would 404 tomorrow, and an
    approved asset that is gone by the time it is uploaded to Meta is not an
    approved asset."""
    from . import media
    blob, mime = download(url)
    if not blob:
        return ""
    put = media.put(tenant, blob, mime=mime or "image/png", origin="generated")
    return str(put.get("url") or "") if put.get("ok") else ""


def _await_export(tenant: str, started: dict, wait: bool) -> tuple:
    """`(urls, job_id, failure)` once an export has rendered — or not."""
    import time as _time
    urls, job = list(started.get("urls") or []), str(started.get("job_id") or "")
    deadline = _time.monotonic() + (HARVEST_TIMEOUT_S if wait else 0)
    while not urls and job and _time.monotonic() < deadline:
        _time.sleep(HARVEST_POLL_S)
        got = export_result(tenant, job)
        if not got.get("ok"):
            return [], job, str(got.get("error", ""))[:100]
        if got.get("status") == "failed":
            return [], job, "Canva could not render it"
        urls = list(got.get("urls") or [])
    return urls, job, ""


def _harvest_placements(tenant: str, row, *, wait: bool = True) -> dict:
    """A frame's OTHER placements, each exported from its own layered design
    at Meta's recommended size (`compose.META_PLACEMENTS`) and recorded on
    the frame in place of the flat crop. `{filed, pending, failed}`."""
    from . import compose
    out: dict = {"filed": 0, "pending": [], "failed": []}
    designs = {k: str(v) for k, v in dict(row.canva_designs or {}).items()
               if k != "1:1" and v}
    if not designs:
        return out
    cut = dict(row.placements or {})
    for fmt, did in designs.items():
        want = ((compose.META_PLACEMENTS.get(fmt) or {}).get("recommended")
                or compose.SIZES.get(fmt) or (0, 0))
        started = export(tenant, did, "png", width=int(want[0]), height=int(want[1]))
        if not started.get("ok"):
            out["failed"].append(f"{row.title or did} {fmt}: {str(started.get('error', ''))[:100]}")
            continue
        urls, job, failure = _await_export(tenant, started, wait)
        if failure:
            out["failed"].append(f"{row.title or job} {fmt}: {failure}")
            continue
        if not urls:
            out["pending"].append({"design_id": did, "job_id": job,
                                   "title": f"{row.title or ''} {fmt}".strip()})
            continue
        cut[fmt] = _keep(tenant, urls[0]) or urls[0]
        out["filed"] += 1
    if out["filed"]:
        kb.set_asset_placements(row.id, cut)
    return out


def harvest(tenant: str, *, design_id: str = "", entity_key: str = "",
            wait: bool = True, asset_id: str = "") -> dict:
    """Export finished designs and file them as USABLE images.

    This was the missing half of the visual loop. `create_design` files a row
    of `kind="design"`, which `creative.hero_for_campaign` can never select —
    deliberately, because a blank canvas is not a photograph. The owner was
    then meant to finish it in Canva and have the result "enter the pictures
    queue", except nothing ever exported anything: `reconcile` reports drift
    and stops, and no caller existed at all. So a design could be created for
    ever and never become an image (owner, 2026-08-22).

    Each export is filed as `kind="image"`, owned, against the same entity as
    the design it came from — which is what makes it selectable as a hero on
    the next run. Idempotent by URL through `kb.add_asset`, so re-running
    re-files nothing.
    """
    every = kb.assets(tenant, publishable_only=False)

    def _designs(r) -> set:
        return {str(v) for v in dict(r.canva_designs or {}).values() if v} \
            | ({str(r.canva_design_id)} if r.canva_design_id else set())

    rows = [r for r in every
            if _designs(r) and (not design_id or design_id in _designs(r))
            and (not asset_id or r.id == asset_id)]
    if not rows:
        return {"ok": True, "filed": 0, "pending": [], "failed": [],
                "note": "no Canva designs are recorded for this account"}

    # A design that has ALREADY come back is finished with — an export row,
    # or a frame whose source says it was edited — so the sweep does not
    # re-export the same canvas every hour. Naming a design id is the
    # owner's "bring it back again" and overrides that.
    done = set() if (design_id or asset_id) else {
        r.canva_design_id for r in every
        if r.kind == "image" and r.canva_design_id
        and ("Canva" in str(r.source or ""))}
    filed, pending, failed = 0, [], []
    for r in rows:
        if r.canva_design_id and r.canva_design_id in done:
            continue
        # A FRAME THAT WENT TO CANVA COMES BACK AS ITSELF. `hosting.to_canva`
        # records the design on the frame precisely so the finished design is
        # the same picture; filing the export as a new row — which this did,
        # and then skipped the frame as "already an image" — made it a third
        # copy of one picture in the review queue.
        frame = r.kind == "image" and "exported from Canva" not in str(r.source or "")
        if frame and not r.canva_design_id:
            # Only placement designs — nothing to bring back as the frame itself.
            more = _harvest_placements(tenant, r, wait=wait)
            filed += more["filed"]
            pending.extend(more["pending"])
            failed.extend(more["failed"])
            continue
        started = export(tenant, r.canva_design_id, "png")
        if not started.get("ok"):
            failed.append(f"{r.title or r.canva_design_id}: "
                          f"{str(started.get('error', ''))[:100]}")
            continue
        urls, job, failure = _await_export(tenant, started, wait)
        if failure:
            failed.append(f"{r.title or job}: {failure}")
            continue
        if not urls:
            pending.append({"design_id": r.canva_design_id, "job_id": job,
                            "title": r.title or ""})
            continue
        # THE BYTES, NOT THE LINK: Canva's export URL is gone in 24 hours.
        kept = _keep(tenant, urls[0]) or urls[0]
        if frame:
            with db.SessionLocal() as s:
                got = s.get(db.KbAsset, r.id)
                if got is not None:
                    got.url = kept
                    if "edited in Canva" not in str(got.source or ""):
                        got.source = ((got.source or "generated")
                                      + " · edited in Canva")
                    s.commit()
                    filed += 1
            # AND ITS PLACEMENTS, each from its own layered design.
            more = _harvest_placements(tenant, r, wait=wait)
            filed += more["filed"]
            pending.extend(more["pending"])
            failed.extend(more["failed"])
            continue
        said = kb.add_asset(
            tenant, kept, rights=kb.OWNED,
            title=(r.title or "Canva design") + " (export)",
            kind="image", subject="graphic", source="exported from Canva",
            entity_key=entity_key or (r.entity_key or ""),
            canva_design_id=r.canva_design_id, origin="human")
        if str(said).startswith("Filed"):
            filed += 1
    return {"ok": True, "filed": filed, "pending": pending, "failed": failed,
            "note": ("an exported design is filed as an IMAGE, owned and "
                     "entity-scoped, which is what makes it selectable as an "
                     "email hero — the design row never was")}
