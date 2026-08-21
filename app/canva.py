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
        from . import oauth
        got = oauth.access_token("canva", secret)
        if not got.get("ok"):
            return "", (f"Canva would not renew the token for {tenant}: "
                        f"{got.get('error', '')} — reconnect it on the "
                        f"Accounts tab.")
        return got["token"], ""
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
    meta = _b64.b64encode(name[:120].encode()).decode()
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


from . import toolcalls as _tc  # noqa: E402
call = _tc.instrument('canva', _call)          # replaceable, so the suite can drive every path
call_binary = _call_binary


# ---------------------------------------------------------------------------
# Where a tenant's work lives
# ---------------------------------------------------------------------------

def _remember_folder(tenant: str, folder_id: str) -> None:
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
        design["canva_folder_id"] = folder_id
        row.design = design
        s.commit()


def folder(tenant: str) -> dict:
    """This account's folder id, creating the folder the first time.

    Returns `{ok, folder_id, created}`.
    """
    t = tenants.get(tenant)
    if not t:
        return {"ok": False, "error": f"unknown tenant {tenant!r}"}
    known = (t.design or {}).get("canva_folder_id") or ""
    if known:
        return {"ok": True, "folder_id": known, "created": False}

    # The root first, then the account inside it. Two levels, so a Canva team
    # that also works by hand is not looking at a flat list of client names at
    # the top of its own workspace.
    root = call(tenant, "POST", "/folders",
                payload={"name": ROOT_NAME, "parent_folder_id": "root"})
    if not root["ok"]:
        return root
    root_id = ((root["data"] or {}).get("folder") or {}).get("id", "")
    if not root_id:
        return {"ok": False, "error": "Canva created no root folder id."}

    made = call(tenant, "POST", "/folders",
                payload={"name": f"{t.name} ({tenant})",
                         "parent_folder_id": root_id})
    if not made["ok"]:
        return made
    fid = ((made["data"] or {}).get("folder") or {}).get("id", "")
    if not fid:
        return {"ok": False, "error": "Canva created no folder id."}
    _remember_folder(tenant, fid)
    return {"ok": True, "folder_id": fid, "created": True, "root_id": root_id}


def _file_into_folder(tenant: str, item_id: str) -> dict:
    f = folder(tenant)
    if not f["ok"]:
        return f
    return call(tenant, "POST", f"/folders/{f['folder_id']}/items",
                payload={"item_id": item_id})


# ---------------------------------------------------------------------------
# Assets and designs
# ---------------------------------------------------------------------------

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


def create_design(tenant: str, *, title: str, design_type: str = "",
                  asset_id: str = "", entity_key: str = "") -> dict:
    """Create a design, file it in this account's folder, record it.

    All three, or it says which part did not happen. A design sitting in Canva
    that nothing in the library names is invisible to every skill — it cannot
    be selected, cannot be credited when it is used, and cannot carry a result.
    """
    payload: dict = {"design_type": {"type": "preset",
                                     "name": design_type or "instagram-post"},
                     "title": title[:255]}
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
        origin="human")
    return {"ok": True, "design_id": did,
            "edit_url": urls.get("edit_url", ""),
            "view_url": urls.get("view_url", ""),
            "filed": filed.get("ok", False),
            "filed_error": "" if filed.get("ok") else filed.get("error", ""),
            "recorded": said}


def export(tenant: str, design_id: str, fmt: str = "png") -> dict:
    """Start an export. Returns the job — Canva finishes it asynchronously."""
    if fmt not in ("png", "jpg", "pdf", "gif", "mp4", "pptx"):
        return {"ok": False, "error": f"unsupported export format {fmt!r}"}
    res = call(tenant, "POST", "/exports",
               payload={"design_id": design_id, "format": {"type": fmt}})
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
                        entity_key: str = "",
                        design_type: str = "instagram-post") -> dict:
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
    up = upload_bytes(tenant, blob, title)
    if not up["ok"]:
        return {**up, "stage": "upload"}
    made = create_design(tenant, title=title, design_type=design_type,
                         asset_id=up["asset_id"], entity_key=entity_key)
    if not made["ok"]:
        return {**made, "stage": "design", "asset_id": up["asset_id"],
                "orphan": f"asset {up['asset_id']} is in Canva and no design "
                          f"references it"}
    return {**made, "stage": "done", "asset_id": up["asset_id"],
            "note": "the image is fixed and correct; the text and layout are "
                    "editable in Canva. Nothing here is published."}
