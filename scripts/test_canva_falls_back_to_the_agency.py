"""A revoked client connection is not a connection: the agency's Canva serves
them, filed in their own folder, and the frame says so.

Owner, 2026-09-07: *"Canva: Canva would not renew the token for baci: Sign-in
was rejected: Token lineage has been revoked — reconnect it on the Accounts
tab."* — and: *"We agreed that when a specific client is not connected it will
resolve to organize by folders in Canva."*

WHAT WAS TRUE. `canva._token` resolves a credential — the client's own, when
they ever connected — and when THAT one will not renew it returns the error,
one line above the text that promises the agency's connection serves every
account. `credentials.resolve` already falls back to the agency for a client
with no ACTIVE row; a revoked lineage left Baci's row active and failing, so
the fallback that exists was never reached.

AND THE FOLDER. Baci's remembered folder was created in Baci's Canva. The
agency's token cannot file into it, so the fallback alone would have made the
design and failed to file it — the "filed_error" nobody reads.

Three facts, each with its guard: a DEFINITIVE rejection (revoked, invalid
grant) marks the client's row failed — where the Accounts tab shows it and
says reconnect — and the agency serves them; a TRANSIENT error (a timeout)
changes nothing, because switching a client's designs into the agency's Canva
on a blip is how "why is our design in their Canva" starts; a folder is
remembered per account and a stale one is recreated once, not failed on.

AND THE OWNER CAN LOOK BEFORE EDITING: every frame carries a viewer — full
size, zoomable — with the edit control inside it.

Run: python3 scripts/test_canva_falls_back_to_the_agency.py
"""
from __future__ import annotations

import io
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'cv.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["PUBLIC_BASE_URL"] = "https://example.test"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image  # noqa: E402

from app import (admin_ui as ui, canva, credentials as cred, db, hosting, kb,  # noqa: E402
                 media, oauth, tenants)

KEY = "s3cret"
_fail: list[str] = []


def ck(label: str, cond, detail: str = "") -> None:
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def png(colour=(200, 160, 120, 255)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (64, 64), colour).save(buf, format="PNG")
    return buf.getvalue()


def _seed(tenant: str, secret: str, by: str) -> None:
    with db.SessionLocal() as s:
        s.add(db.Credential(tenant=tenant, provider="canva", kind="oauth",
                            secret=cred._encrypt(secret), meta={},
                            status="active", granted_by=by))
        s.commit()


def _canva_row(tenant: str):
    with db.SessionLocal() as s:
        rows = (s.query(db.Credential)
                .filter(db.Credential.tenant == tenant,
                        db.Credential.provider == "canva").all())
        s.expunge_all()
        return rows


RENEW = {
    "agency-refresh": {"ok": True, "token": "agency-access"},
    "baci-refresh": {"ok": False, "error": "Sign-in was rejected: Token lineage "
                                           "has been revoked"},
    "eien-refresh": {"ok": False, "error": "ConnectError: timed out"},
}


def main() -> int:
    db.init_db()
    tenants.seed()
    _seed("agency", "agency-refresh", "gomeh")
    _seed("baci", "baci-refresh", "client")
    _seed("eien", "eien-refresh", "client")
    oauth.access_token = lambda provider, refresh: dict(RENEW.get(refresh) or
                                                       {"ok": False, "error": "no such token"})

    print("— A REVOKED CONNECTION IS NOT A CONNECTION —")
    tok, why = canva._token("baci")
    ck("Baci's revoked lineage resolves to the AGENCY's token, not an error",
       tok == "agency-access" and why == "", f"tok={tok!r} why={why[:90]!r}")
    row = next((r for r in _canva_row("baci")), None)
    ck("  the revocation is RECORDED on Baci's row — failed, with the reason",
       row is not None and row.status == "failed"
       and "revoked" in (row.last_error or "").lower(),
       f"{getattr(row, 'status', None)} {getattr(row, 'last_error', '')[:60]!r}")
    st = next((r for r in cred.status("baci") if r["provider"] == "canva"), {})
    ck("  and the Accounts tab shows it as failed, where reconnecting happens",
       st.get("state") == "failed" and "revoked" in str(st.get("detail") or "").lower(),
       str(st)[:160])
    ck("  after which the resolver itself hands Baci the agency's connection",
       cred.resolve("baci", "canva").get("source") == "agency")
    acct = canva.which_account("baci")
    ck("  and the account in use is SAID: the agency's, because Baci's was revoked",
       acct.get("source") == "agency" and "revoked" in acct.get("note", "").lower()
       and "agency" in acct.get("note", "").lower(), str(acct)[:200])

    print("\n— A TRANSIENT ERROR CHANGES NOTHING —")
    tok2, why2 = canva._token("eien")
    row2 = next((r for r in _canva_row("eien")), None)
    ck("a timeout on Eien's own connection is an error, not a switch of accounts",
       tok2 == "" and "ConnectError" in why2 and row2 is not None
       and row2.status == "active" and not (row2.last_error or ""),
       f"tok={tok2!r} why={why2[:80]!r} status={getattr(row2, 'status', None)}")
    ck("  and Eien is still served by its own connection",
       cred.resolve("eien", "canva").get("source") == "client")

    print("\n— THE FOLDER: remembered per account, a stale one recreated once —")
    calls: list = []
    n = [0]

    def _fake_call(tenant, method, path, *, payload=None, params=None):
        calls.append((tenant, method, path, payload))
        if path == "/folders":
            n[0] += 1
            return {"ok": True, "data": {"folder": {"id": f"folder-{n[0]}"}}}
        if path == "/folders/move":
            fid = str((payload or {}).get("to_folder_id") or "")
            # `/folders` makes the ROOT first (folder-1), then the client's
            # folder (folder-2) — and that one is deleted by hand in Canva
            # before anything is filed in it: the folder that is gone.
            if fid in ("stale-baci-folder", "folder-2"):
                return {"ok": False, "error": "404: folder not found"}
            return {"ok": True, "data": {}}
        if path == "/designs":
            return {"ok": True, "data": {"design": {
                "id": "des-1", "urls": {"edit_url": "https://www.canva.com/design/des-1/edit",
                                         "view_url": "https://www.canva.com/design/des-1/view"}}}}
        return {"ok": True, "data": {}}

    canva.call = _fake_call
    canva.upload_bytes = lambda tenant, blob, name, **k: {"ok": True, "asset_id": "asset-1"}
    # Baci's folder, remembered from when Baci's own Canva made it.
    with db.SessionLocal() as s:
        t = s.get(db.Tenant, "baci")
        t.design = {**(t.design or {}), "canva_folder_id": "stale-baci-folder"}
        s.commit()
    kb.add_asset("baci", "https://example.test/m/frame-1.png", rights=kb.OWNED,
                 title="Ad frame 1", kind="image", subject=kb.SCENE, origin="generated",
                 batch="set-1", tags=["identity", "effort", "during", "person_led"])
    hosting._bytes = lambda row: (png(), "")
    aid = next(a.id for a in kb.assets("baci", publishable_only=False)
               if a.url == "https://example.test/m/frame-1.png")
    got = hosting.to_canva("baci", aid)
    ck("the frame opens in Canva through the agency's connection",
       got.get("ok") and got.get("design_id") == "des-1", str(got)[:200])
    filed = [(c[3] or {}).get("to_folder_id", "") for c in calls if c[2] == "/folders/move"]
    ck("  Baci's own remembered folder is never tried through the agency's account",
       "stale-baci-folder" not in filed, str(filed))
    ck("  a folder that is gone is recreated once and the design filed in the new one",
       filed == ["folder-2", "folder-3"] and not got.get("filed_error"), str(filed))
    ck("  without a second root — the root is remembered for the agency's account",
       sum(1 for c in calls if c[2] == "/folders" and (c[3] or {}).get("parent_folder_id") == "root") == 1,
       str([c[3] for c in calls if c[2] == "/folders"]))
    with db.SessionLocal() as s:
        design = dict((s.get(db.Tenant, "baci").design or {}))
    ck("  and the new folder is remembered for the AGENCY's account, apart from Baci's",
       (design.get("canva_folders") or {}).get("agency") == "folder-3"
       and design.get("canva_folder_id") == "stale-baci-folder",
       str(design)[:160])
    ck("  the result says whose Canva it went into and where",
       "agency" in str(got.get("note") or "").lower()
       and "folder" in str(got.get("note") or "").lower(), str(got.get("note"))[:160])

    print("\n— THE CONSOLE: said on the frame, and the frame can be looked at first —")
    page = ui.render_content(KEY, tenant="baci", sub="pictures")
    ck("the set card says the frame went to the agency's Canva because Baci's was revoked",
       "agency" in page.lower() and "revoked" in page.lower())
    ck("every frame carries a viewer, full size, with the edit control inside",
       'id="lb"' in page and 'class="lbbtn"' in page
       and 'data-full="https://example.test/m/frame-1.png"' in page)
    ck("  and the viewer zooms",
       "lb.classList.toggle('zoomed')" in page or "classList.toggle(\"zoomed\")" in page)

    print()
    if _fail:
        print(f"{len(_fail)} FAILED:\n  " + "\n  ".join(_fail))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
