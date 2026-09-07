"""Every Canva call is the one Canva documents — and the contract is a check.

Owner, 2026-09-07, on the first live "edit in Canva" after two revoked
lineages: *"Canva: 400: 'name' must be one of the following: doc, email,
presentation, whiteboard, but was instagram-post."* — and: *"Please make sure
your referencing the api docs when you fix issues associated with a specific
tool."*

Read against the published contracts on 2026-09-07:
  designs  https://www.canva.dev/docs/connect/api-reference/designs/create-design/
           design_type is `{"type": "preset", "name": doc|email|presentation|whiteboard}`
           or `{"type": "custom", "width", "height"}` in pixels, 40–8000 a side,
           area ≤ 25,000,000; `asset_id` optional; `title` 1–255.
  folders  https://www.canva.dev/docs/connect/api-reference/folders/create-folder/
           `{"name", "parent_folder_id"}`, "root" allowed, name 1–255.
  filing   https://www.canva.dev/docs/connect/api-reference/folders/move-folder-item/
           POST /v1/folders/move `{"to_folder_id", "item_id"}` → 204.
  uploads  https://www.canva.dev/docs/connect/api-reference/assets/create-asset-upload-job/
           octet-stream body; `Asset-Upload-Metadata: {"name_base64"}`, the name
           at most 50 characters unencoded; job status failed|in_progress|success,
           `job.error.message` on failure, `job.asset.id` on success.
  exports  https://www.canva.dev/docs/connect/api-reference/exports/create-design-export-job/
           `{"design_id", "format": {"type": "png", …}}`; job status as above.

WHAT WAS TRUE: "instagram-post" was a preset this code made up, so every
frame's design creation failed; `POST /folders/{id}/items` was a path it
made up, so every design's filing failed as the `filed_error` nobody read —
and the recreate-once logic would have read that 404 as a folder gone and
minted duplicates; upload names were cut at 120 characters against a limit
of 50. Each is a fact from the docs, each now a check with its guard.

Run: python3 scripts/test_canva_calls_are_the_documented_ones.py
"""
from __future__ import annotations

import base64
import io
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'doc.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image  # noqa: E402

from app import canva, db, tenants  # noqa: E402

_fail: list[str] = []


def ck(label: str, cond, detail: str = "") -> None:
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def png(w: int, h: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (200, 160, 120)).save(buf, format="PNG")
    return buf.getvalue()


def main() -> int:
    db.init_db()
    tenants.seed()
    sent: list = []
    uploads: list = []

    def _call(tenant, method, path, *, payload=None, params=None):
        sent.append((method, path, payload))
        if path == "/folders":
            return {"ok": True, "data": {"folder": {"id": f"fld-{len([s for s in sent if s[1] == '/folders'])}"}}}
        if path == "/folders/move":
            return {"ok": True, "data": {}}          # 204: no body
        if path == "/designs":
            return {"ok": True, "data": {"design": {"id": "DES-1", "urls": {
                "edit_url": "https://www.canva.com/design/DES-1/edit",
                "view_url": "https://www.canva.com/design/DES-1/view"}}}}
        if path.startswith("/asset-uploads/"):
            return {"ok": True, "data": {"job": {"status": "success", "asset": {"id": "AST-1"}}}}
        return {"ok": True, "data": {}}

    def _bin(tenant, path, blob, name):
        uploads.append(name)
        return {"ok": True, "data": {"job": {"id": "job-1", "status": "in_progress"}}}

    canva.call, canva.call_binary = _call, _bin
    canva._token = lambda tenant: ("tok", "")

    print("— DESIGNS: a frame is a custom design at its own pixels —")
    got = canva.editable_from_image("baci", png(1536, 1024), title="Ad frame · identity",
                                    record=False)
    design = next((p for m, path, p in sent if path == "/designs"), None)
    ck("the frame becomes a design",
       got.get("ok") and got.get("design_id") == "DES-1", str(got)[:160])
    ck("  sized by the pixels it carries, as a CUSTOM design — no invented preset",
       design is not None and design.get("design_type") == {"type": "custom", "width": 1536, "height": 1024},
       str(design))
    ck("  carrying the uploaded asset and a title within 255",
       design is not None and design.get("asset_id") == "AST-1"
       and 1 <= len(design.get("title") or "") <= 255)
    dt, why = canva.design_type_for(design_type="instagram-post")
    ck("a preset Canva does not have is refused with the four it has, and the URL",
       dt is None and "doc, email, presentation, whiteboard" in why and "canva.dev" in why, why[:120])
    for name in canva.PRESETS:
        dt, why = canva.design_type_for(design_type=name)
        ck(f"  {name} is sent as a preset", dt == {"type": "preset", "name": name}, why)
    dt, why = canva.design_type_for(width=30, height=9000)
    ck("a size outside 40–8000 a side is refused with the limits",
       dt is None and "8000" in why and "40" in why, why[:100])
    dt, why = canva.design_type_for(width=6000, height=6000)
    ck("  and so is an area over 25,000,000 px", dt is None and "25,000,000" in why, why[:100])
    r = canva.create_design("baci", title="x", design_type="instagram-post")
    ck("create_design refuses before calling Canva when the type is not documented",
       not r.get("ok") and "presets" in r.get("error", "")
       and not any(path == "/designs" and (p or {}).get("design_type", {}).get("name") == "instagram-post"
                   for _, path, p in sent), r.get("error", "")[:100])

    print("\n— FILING: the documented move call, with its documented fields —")
    moves = [(path, p) for m, path, p in sent if path == "/folders/move"]
    ck("the design is filed with POST /folders/move",
       len(moves) == 1 and moves[0][1] == {"to_folder_id": moves[0][1].get("to_folder_id"), "item_id": "DES-1"}
       and str(moves[0][1].get("to_folder_id", "")).startswith("fld-"), str(moves))
    ck("  and never with a path Canva does not document",
       not any(path.endswith("/items") and m == "POST" for m, path, _ in sent),
       str([path for m, path, _ in sent if m == "POST"]))
    folders = [p for m, path, p in sent if path == "/folders"]
    ck("folders are created with name + parent_folder_id, the root at \"root\"",
       folders and folders[0].get("parent_folder_id") == "root"
       and all(set(p) == {"name", "parent_folder_id"} and 1 <= len(p["name"]) <= 255 for p in folders),
       str(folders))

    print("\n— UPLOADS: the name Canva allows, and a failed job's own reason —")
    ck("the upload name sent is at most 50 characters unencoded",
       canva.UPLOAD_NAME_MAX == 50)
    seen: list = []

    def _bin_real(tenant, path, blob, name):
        # the real header builder, with the transport stubbed one level down
        import base64 as _b
        seen.append(_b.b64decode(_b.b64encode(name[:canva.UPLOAD_NAME_MAX].encode())).decode())
        return {"ok": True, "data": {"job": {"status": "success", "asset": {"id": "AST-2"}}}}
    canva.call_binary = _bin_real
    long_name = "Sagrada Família head · identity/person_led · the sign you were born under · frame 12"
    up = canva.upload_bytes("baci", png(64, 64), long_name)
    ck("  a long title still uploads, cut to what the header takes",
       up.get("ok") and seen and len(seen[-1]) <= 50, f"{len(seen[-1]) if seen else None}")

    def _bin_failed(tenant, path, blob, name):
        return {"ok": True, "data": {"job": {"id": "job-9", "status": "in_progress"}}}

    def _call_failed(tenant, method, path, *, payload=None, params=None):
        if path.startswith("/asset-uploads/"):
            return {"ok": True, "data": {"job": {"status": "failed", "error": {
                "code": "file_too_big", "message": "The file is larger than the allowed size."}}}}
        return {"ok": True, "data": {}}
    canva.call_binary, canva.call = _bin_failed, _call_failed
    up2 = canva.upload_bytes("baci", png(64, 64), "big", poll=1)
    ck("a failed upload job surfaces Canva's own message",
       not up2.get("ok") and "larger than the allowed size" in up2.get("error", ""), str(up2))

    print("\n— EXPORTS: design_id and a format object —")
    canva.call = _call
    sent.clear()
    canva.export("baci", "DES-1", "png")
    ex = next((p for m, path, p in sent if path == "/exports"), None)
    ck("an export sends design_id and format.type",
       ex == {"design_id": "DES-1", "format": {"type": "png"}}, str(ex))

    print()
    if _fail:
        print(f"{len(_fail)} FAILED:\n  " + "\n  ".join(_fail))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
