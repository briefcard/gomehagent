"""Canva: per-account folders, PKCE, and the library agreeing with the account.

Two properties matter more than any individual call.

**A design cannot be filed into another client's folder**, because no caller can
say which folder to use — it is looked up from the tenant row. That is the same
reasoning as `tool_scope` stripping the account parameter out of a tool schema.

**What Canva holds and what the library records must agree**, and when they
drift somebody has to be told which direction.

Run: python3 scripts/test_canva.py
"""
import io
import os
import sys
import tempfile

_tmp = os.path.join(tempfile.mkdtemp(), "canva.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}"
os.environ["APPROVAL_SECRET"] = "test-secret"
os.environ["CANVA_CLIENT_ID"] = "cid"
os.environ["CANVA_CLIENT_SECRET"] = "csec"
os.environ["PUBLIC_BASE_URL"] = "https://example.onrender.com"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import canva, db, kb, oauth, tenants  # noqa: E402

_fails: list[str] = []
_sent: list[dict] = []


def ck(label: str, cond: bool, detail: str = "") -> None:
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fails.append(label)


def _fake(responses: dict, folders=None):
    made = folders if folders is not None else []

    def _c(tenant, method, path, *, payload=None, params=None):
        _sent.append({"tenant": tenant, "method": method, "path": path,
                      "payload": payload})
        if method == "POST" and path == "/folders":
            fid = f"fld_{len(made) + 1}"
            made.append({"id": fid, "name": (payload or {}).get("name", ""),
                         "parent": (payload or {}).get("parent_folder_id", "")})
            return {"ok": True, "data": {"folder": {"id": fid}}}
        for pat, res in responses.items():
            if pat in path:
                return res
        return {"ok": True, "data": {}}
    return _c, made


def main() -> int:
    db.init_db()
    tenants.seed()

    print("— ONE root folder, whatever the client count —")
    _made = []
    _real_call = canva.call

    def _fake_call(tenant, method, path, *, payload=None, **kw):
        if method == "POST" and path == "/folders":
            _made.append((payload["name"], payload["parent_folder_id"]))
            return {"ok": True, "data": {"folder": {"id": f"fld_{len(_made)}"}}}
        return {"ok": True, "data": {}}
    canva.call = _fake_call
    for _t in ("baci", "eien", "coverings"):
        canva.folder(_t)
    _roots = [m for m in _made if m[1] == "root"]
    ck("three accounts share ONE root folder, not one root each",
       len(_roots) == 1, f"{len(_roots)} roots: {[m[0] for m in _roots]}")
    ck("…and each account sits inside it",
       all(m[1] == "fld_1" for m in _made if m[1] != "root"),
       str([m[1] for m in _made]))
    ck("a second call reuses the remembered folder, never re-creating it",
       canva.folder("baci").get("created") is False)
    canva.call = _real_call
    # Leave no trace: the rest of this suite expects accounts with no folder
    # remembered and no root on file.
    with db.SessionLocal() as _s:
        for _t in _s.query(db.Tenant).all():
            _d = dict(_t.design or {})
            _d.pop("canva_folder_id", None)
            _t.design = _d
        _r = _s.get(db.Setting, "canva_root_folder")
        if _r:
            _s.delete(_r)
        _s.commit()

    print("— the health probe REPORTS, it does not create —")
    _touched = []
    _real = canva.call

    def _watch(tenant, method, path, *, payload=None, **kw):
        _touched.append(f"{method} {path}")
        return {"ok": True, "data": {"folder": {"id": "fld_x"}}}
    canva.call = _watch
    from fastapi.testclient import TestClient
    import app.web as _web
    # Keyed since the UI-overhaul step 0: /health/connections names client
    # accounts, so it refuses without the console key (test_render_smoke pins
    # the refusal). This suite's own concern — the probe REPORTS and never
    # creates — needs the report, so it authenticates.
    _body = (TestClient(_web.app)
             .get("/health/connections?key=test-secret").json())
    canva.call = _real
    ck("no folder is created by looking at the health page",
       not [c for c in _touched if "/folders" in c], str(_touched))
    ck("…and it names the shared connection as shared",
       any("shared by every account" in k for k in (_body.get("canva") or {})),
       str(list(_body.get("canva") or {})))

    print("— the sign-in that Canva requires —")
    ck("the flow is configured once the app credentials exist",
       oauth.configured("canva") == "", oauth.configured("canva"))
    v, c = oauth._pkce_pair()
    st = oauth.sign_state("baci", "canva", via="admin", verifier=v)
    ck("THE PKCE VERIFIER IS NOT READABLE IN THE STATE — a signed-but-plain "
       "state would hand it to anyone who can see the URL", v not in st)
    data, err = oauth.read_state(st)
    ck("  the state still verifies", not err, err)
    ck("  and only this service can recover the verifier",
       oauth.state_verifier(data) == v)
    url = oauth.authorize_url("canva", st, c)
    ck("  the challenge is sent as S256, never plain",
       "code_challenge_method=S256" in url and v not in url)
    ck("a provider without pkce is unaffected",
       "code_challenge" not in oauth.authorize_url(
           "google", oauth.sign_state("baci", "google"), ""))

    print("\n— every account gets its own folder —")
    canva.call = canva._call
    r = canva.upload_asset("baci", "https://x/y.png", "Y")
    ck("without a connection it refuses and names the fix",
       not r["ok"] and "Accounts tab" in r["error"], r.get("error", "")[:80])

    _sent.clear()
    fn, folders = _fake({})
    canva.call = fn
    f = canva.folder("baci")
    ck("a folder is created on first use", f["ok"] and f["created"], str(f))
    ck("  nested under one root, so our work is not loose in their workspace",
       len(folders) == 2 and folders[0]["parent"] == "root"
       and folders[1]["parent"] == folders[0]["id"],
       str([(x["name"], x["parent"]) for x in folders]))
    ck("  and named for the account", "baci" in folders[1]["name"],
       folders[1]["name"])

    again = canva.folder("baci")
    ck("it is REMEMBERED, not searched for again",
       again["folder_id"] == f["folder_id"] and not again["created"]
       and len(folders) == 2,
       f"{len(folders)} folders after a second call")

    eien = canva.folder("eien")
    ck("a second account gets a DIFFERENT folder",
       eien["folder_id"] != f["folder_id"], f"{eien['folder_id']} vs {f['folder_id']}")

    print("\n— a design lands in Canva and in the library —")
    _sent.clear()
    fn, _ = _fake({"/designs": {"ok": True, "data": {"design": {
        "id": "DES1", "urls": {"edit_url": "https://canva/e",
                               "view_url": "https://canva/v"},
        "thumbnail": {"url": "https://canva/t"}}}}})
    canva.call = fn
    d = canva.create_design("baci", title="Aqua pitchers ad",
                            entity_key="white-acrylic-pitcher-aqua")
    ck("the design is created", d["ok"] and d["design_id"] == "DES1")
    ck("  and filed into this account's folder", d["filed"], d.get("filed_error", ""))
    filed = [s for s in _sent if s["path"].endswith("/items")]
    ck("  by posting it to that folder, not to a caller-supplied one",
       filed and filed[0]["payload"]["item_id"] == "DES1", str(filed[:1]))

    rows = [a for a in kb.assets("baci") if a.canva_design_id == "DES1"]
    ck("IT IS ALSO RECORDED IN THE LIBRARY — a design nothing names is "
       "invisible to every skill", len(rows) == 1, f"{len(rows)} rows")
    ck("  as owned, so it may actually be published",
       rows and rows[0].rights == kb.OWNED)
    ck("  carrying the entity it is about",
       rows[0].entity_key == "white-acrylic-pitcher-aqua")
    ck("  and the canva id, so the two sides can be compared later",
       rows[0].canva_design_id == "DES1")

    print("\n— an uploaded asset keeps its rights answer —")
    fn, _ = _fake({"/asset-uploads": {"ok": True, "data": {"asset": {
        "id": "AST1", "name": "Pitcher", "tags": ["jug", "white"],
        "thumbnail": {"url": "https://canva/th"}}}}})
    canva.call = fn
    a = canva.upload_asset("baci", "https://cdn/p.png", "Pitcher",
                           entity_key="white-acrylic-pitcher-aqua")
    ck("an owned upload is recorded and publishable", a["ok"]
       and any(x.title == "Pitcher" for x in kb.assets("baci")))
    ck("  Canva's own smart tags are kept", "jug" in a["smart_tags"])
    ref = canva.upload_asset("baci", "https://rival/ad.png", "Rival ad",
                             rights=kb.REFERENCE)
    ck("A COMPETITOR REFERENCE STAYS UNPUBLISHABLE even though it came in "
       "through the same call",
       ref["ok"] and not any(x.title == "Rival ad" for x in kb.assets("baci"))
       and any(x.title == "Rival ad"
               for x in kb.assets("baci", publishable_only=False)))

    print("\n— do the two sides still agree —")
    fn, _ = _fake({"/items": {"ok": True, "data": {"items": [
        {"design": {"id": "DES1", "title": "Aqua pitchers ad"}},
        {"design": {"id": "DES_UNKNOWN", "title": "Made by hand in Canva"}}]}}})
    canva.call = fn
    rec = canva.reconcile("baci")
    ck("a design made by hand in Canva is reported as unrecorded",
       any(x["design_id"] == "DES_UNKNOWN"
           for x in rec["in_canva_not_recorded"]),
       str(rec["in_canva_not_recorded"]))
    ck("  and the one we made is not flagged", rec["recorded"] >= 1)

    kb.add_asset("baci", "https://canva/gone", rights=kb.OWNED,
                 title="Deleted in Canva", kind="design",
                 canva_design_id="DES_GONE", origin="human")
    rec = canva.reconcile("baci")
    ck("A ROW NAMING A DESIGN THAT NO LONGER EXISTS is reported — the "
       "dangerous direction, because a skill can still select it",
       any(x["design_id"] == "DES_GONE"
           for x in rec["recorded_not_in_canva"]),
       str(rec["recorded_not_in_canva"]))
    ck("  and `agrees` is false while either side is short", not rec["agrees"])

    print("\n— a finished base handed over as something still editable —")
    _jobs = {"n": 0}

    def _fake_bin(tenant, path, blob, name):
        _jobs["n"] += 1
        _jobs["bytes"] = len(blob)
        _jobs["name"] = name
        return {"ok": True, "data": {"job": {"id": "job1", "status": "in_progress"}}}

    def _fake_poll(tenant, method, path, *, payload=None, params=None):
        if path.startswith("/asset-uploads/"):
            return {"ok": True, "data": {"job": {"status": "success",
                                                 "asset": {"id": "AST_UP"}}}}
        if path == "/designs":
            return {"ok": True, "data": {"design": {
                "id": "DES_ED",
                "urls": {"edit_url": "https://canva/edit",
                         "view_url": "https://canva/view"}}}}
        return {"ok": True, "data": {}}

    canva.call_binary = _fake_bin
    canva.call = _fake_poll
    from PIL import Image as _I
    buf = io.BytesIO()
    _I.new("RGB", (400, 400), (220, 210, 195)).save(buf, format="PNG")
    r = canva.editable_from_image("baci", buf.getvalue(),
                                  title="Aqua pitchers — base",
                                  entity_key="white-acrylic-pitcher-aqua")
    ck("a rendered image goes up as BYTES", _jobs["n"] == 1 and _jobs["bytes"] > 0,
       "publishing a draft somewhere public just so Canva can fetch it back "
       "would be publishing it to get it reviewed")
    ck("  an async upload is waited on rather than returned half-done",
       r["ok"] and r["asset_id"] == "AST_UP", str(r)[:90])
    ck("  it becomes a design", r["design_id"] == "DES_ED")
    ck("  filed in this account's folder, like anything else", r["filed"])
    ck("  recorded in the library so a skill can find it later",
       any(x.canva_design_id == "DES_ED"
           for x in kb.assets("baci", publishable_only=False)))
    ck("  and it hands back an EDIT url — the point is that a person can still "
       "change it", r["edit_url"].startswith("https://"), r["edit_url"])
    ck("  nothing was published", "Nothing here is published" in r["note"]
       or "not published" in r["note"].lower(), r["note"][:70])

    canva.call_binary = lambda *a, **k: {"ok": True, "data": {"job": {
        "id": "j2", "status": "in_progress"}}}
    canva.call = lambda t, m, p, **k: ({"ok": True, "data": {"job": {
        "status": "in_progress"}}} if p.startswith("/asset-uploads/")
        else {"ok": True, "data": {}})
    slow = canva.upload_bytes("baci", b"x" * 10, "slow", poll=2)
    ck("an upload that never finishes says so instead of hanging",
       not slow["ok"] and "still processing" in slow["error"],
       slow.get("error", "")[:60])

    canva.call_binary = canva._call_binary
    canva.call = canva._call
    print()
    if _fails:
        print(f"{len(_fails)} FAILED:")
        for f in _fails:
            print(f"  - {f}")
        return 1
    print("all green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
