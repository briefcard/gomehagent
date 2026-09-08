"""The layers deck is a standard PowerPoint package, and a Canva import that
fails is recorded, retried once, and falls back to the flat picture — said as
flat on the frame, with the layers tried again on the next press.

Owner, 2026-09-08: *"Canva: 500: {"statusCode":500,"error":"server error"} —
I am getting this since our latest update with the 'powerpoint' approach."*

WHAT WAS TRUE. The deck was assembled by hand — the thirteen parts
PowerPoint opens — and Canva's importer answered 500 on it; the import call
was not recorded anywhere, was not retried, and its failure closed the door
that had worked the day before: the button showed the flash and nothing was
in Canva.

Run: python3 scripts/test_a_canva_import_that_fails_falls_back_to_the_picture.py
"""
from __future__ import annotations

import io
import os
import sys
import tempfile
import zipfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'flat.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["PUBLIC_BASE_URL"] = "https://example.test"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image  # noqa: E402

from app import (admin_ui as ui, canva, compose, credentials as cred, db,  # noqa: E402
                 hosting, kb, kb_seed, layers, media, oauth, tenants, toolcalls)

KEY = "s3cret"
_fail: list[str] = []
FIVE_HUNDRED = '500: {"statusCode":500,"error":"server error"}'


def ck(label: str, cond, detail: str = "") -> None:
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def png(colour, w: int = 512, h: int = 512) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), colour).save(buf, format="PNG")
    return buf.getvalue()


def _seed(tenant: str, secret: str, by: str) -> None:
    with db.SessionLocal() as s:
        s.add(db.Credential(tenant=tenant, provider="canva", kind="oauth",
                            secret=cred._encrypt(secret), meta={},
                            status="active", granted_by=by))
        s.commit()


def main() -> int:
    db.init_db()
    tenants.seed()
    kb_seed.seed_all()
    _seed("baci", "baci-refresh", "client")
    oauth.access_token = lambda provider, refresh: {"ok": True, "token": "baci-access"}
    hosting._logo = lambda theme: b""

    print("— THE DECK IS A STANDARD PACKAGE, WRITTEN BY THE STANDARD WRITER —")
    d = layers.deck(png((30, 40, 60), 1024, 1024), size=compose.SIZES["4:5"],
                    headline="The sign you were born under", ask="Shop the Zodiac cups",
                    theme={"colors": {"accent": "#b5473b"}, "font": {"heading": "Georgia"}})
    names = set(zipfile.ZipFile(io.BytesIO(d["pptx"])).namelist())
    ck("the package carries the parts every importer expects, not the thirteen a hand-built one had",
       {"ppt/presProps.xml", "ppt/viewProps.xml", "ppt/tableStyles.xml", "ppt/presentation.xml",
        "ppt/slides/slide1.xml", "ppt/slideMasters/slideMaster1.xml"} <= names
       and len(names) > 30, f"{len(names)} parts")
    r = layers.read_layers(d["pptx"])
    by = {L["name"]: L for L in r["layers"]}
    ck("  and the layers read back the same: photo cropped to the ratio, headline, CTA in the accent",
       r["size"] == (1080, 1350) and by["Photo"]["cropped"] and by["Photo"]["box"]["w"] == 1080
       and by["Headline"]["text"] == "The sign you were born under" and by["Headline"]["font"] == "Georgia"
       and by["CTA"]["fill"] == "B5473B" and by["CTA"]["geometry"] == "roundRect",
       str({k: (v["box"], v["font"], v["fill"]) for k, v in by.items()}))
    ck("  the writer is the library, not the hand", "from pptx import Presentation" in open(layers.__file__).read()
       and "_content_types" not in open(layers.__file__).read())

    print("\n— A 500 FROM CANVA IS RECORDED, RETRIED ONCE, AND FALLS BACK TO THE FLAT PICTURE —")
    calls: list = []
    imports: list = []
    mode = {"import": "500"}
    n = {"folder": 0, "job": 0}

    def _call(tenant, method, path, *, payload=None, params=None):
        calls.append((method, path, payload))
        if path == "/folders" and method == "POST":
            n["folder"] += 1
            return {"ok": True, "data": {"folder": {"id": f"folder-{n['folder']}"}}}
        if path == "/folders/move":
            return {"ok": True, "data": {}}
        if path == "/designs":
            return {"ok": True, "data": {"design": {"id": "FLAT1", "urls": {
                "edit_url": "https://www.canva.com/design/FLAT1/edit"}}}}
        if path.startswith("/imports/"):
            job = path.rsplit("/", 1)[-1]
            return {"ok": True, "data": {"job": {"id": job, "status": "success", "result": {
                "designs": [{"id": "LAYERED1", "urls": {"edit_url": "https://www.canva.com/design/LAYERED1/edit"}}]}}}}
        return {"ok": False, "error": f"unexpected {method} {path}"}

    def _import(tenant, blob, title, mime):
        imports.append(title)
        if mode["import"] == "500":
            return {"ok": False, "error": FIVE_HUNDRED}
        n["job"] += 1
        return {"ok": True, "data": {"job": {"id": f"job-{n['job']}", "status": "in_progress"}}}
    canva.call, canva.call_import = _call, _import
    canva.upload_bytes = lambda tenant, blob, name, **k: {"ok": True, "asset_id": "AST1"}
    canva.IMPORT_POLL_S, canva.IMPORT_RETRY_S = 0, 0
    url = media.put("baci", png((30, 40, 60), 1024, 1024), mime="image/png", origin="generated")["url"]
    kb.add_asset("baci", url, rights=kb.OWNED, title="Zodiac · identity", kind="image",
                 subject=kb.OBJECT, origin="generated", batch="b1")
    aid = next(a.id for a in kb.assets("baci", publishable_only=False) if a.url == url)
    got = hosting.to_canva("baci", aid, "4:5")
    row = next(a for a in kb.assets("baci", publishable_only=False) if a.id == aid)
    ck("the import is tried twice — a 5xx is Canva's side — before the caller is told",
       len(imports) == 2, f"{len(imports)} import(s)")
    ck("  every attempt is filed as a tool call with Canva's own answer",
       sum(1 for c in toolcalls._rows("baci", 1) if "imports" in (c.tool or "") and c.ok == "no"
           and "server error" in (c.error or "")) == 2)
    ck("  the frame still opens in Canva — as ONE flat picture — and the note says so and why",
       got.get("ok") and got.get("flat") is True and got.get("design_id") == "FLAT1"
       and "flat" in got.get("note", "").lower() and "server error" in got.get("note", "")
       and any(p == "/designs" for _, p, _ in calls), str(got)[:220])
    ck("  the flat design is recorded on the placement, marked flat",
       (row.canva_designs or {}).get("4:5") == "FLAT1" and hosting.is_flat(row, "4:5"))
    kb.review_asset(aid, approve=True, rights="owned")
    page = ui.render_content(KEY, tenant="baci", sub="pictures")
    ck("  the card says 'flat in Canva' for that ratio and offers the layers again",
       "flat in Canva" in page and "try the layers again" in page, "")

    print("\n— THE NEXT PRESS TRIES THE LAYERS AGAIN, AND THEY REPLACE THE FLAT ONE —")
    mode["import"] = "ok"
    got2 = hosting.to_canva("baci", aid, "4:5")
    row2 = next(a for a in kb.assets("baci", publishable_only=False) if a.id == aid)
    ck("a flat placement is not 'reused' — the layered import is tried again and wins",
       got2.get("ok") and not got2.get("reused") and got2.get("design_id") == "LAYERED1"
       and (row2.canva_designs or {}).get("4:5") == "LAYERED1" and not hosting.is_flat(row2, "4:5"),
       str(got2)[:200])
    got3 = hosting.to_canva("baci", aid, "4:5")
    ck("  and once layered it is reused", got3.get("reused") is True and got3.get("design_id") == "LAYERED1")
    page2 = ui.render_content(KEY, tenant="baci", sub="pictures")
    ck("  the card now says layers", "layers in Canva" in page2 and "flat in Canva" not in page2)
    mode["import"] = "500"
    imports.clear()
    got4 = hosting.to_canva("baci", aid, "9:16")
    ck("a 5xx is retried, a 4xx is not",
       len(imports) == 2 and got4.get("flat") is True, str(got4)[:120])
    imports.clear()
    canva.call_import = lambda tenant, blob, title, mime: {"ok": False, "error": "400: invalid file"}
    got5 = hosting.to_canva("baci", aid, "1:1")
    ck("  a 4xx is told once and still falls back",
       got5.get("flat") is True and "400" in got5.get("note", ""), got5.get("note", "")[:120])

    print()
    if _fail:
        print(f"{len(_fail)} FAILED:\n  " + "\n  ".join(_fail))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
