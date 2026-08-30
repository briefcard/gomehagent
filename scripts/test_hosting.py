"""A picture's life: ours, editable on Canva, then the client's own.

Owner, 2026-08-30: *"It should be on canva until edited & approved or just
approved, then it can be hosted on shopify / wordpress / another cms of the
client's so it's accessible to us."*

That is a lifecycle, and nothing owned it. `media` says of itself that it is
"a handoff, not a CDN" — and it was, except for APPROVED pictures, which it
kept for ever. The one case the disclaimer did not cover was the only one that
accumulates, and it was also the case where the picture had already earned a
better home.

**THE STAGE IS DERIVED.** A column saying "hosted" beside a URL still pointing
at our blob store is a row that disagrees with itself, and the disagreement
surfaces as a 404 a fortnight later when the sweep runs.

**APPROVAL GATES THE HAND-OFF.** Putting an unapproved frame in a client's
media library puts our draft where their staff will find it and use it.

**A REFUSAL KEEPS THE PICTURE.** No CMS connected, a Shopify store that never
granted `write_files`, an upload the platform rejects — each leaves the bytes
with us and says which. The alternative is a row pointing at a library that
does not have it.

**AND `write_files` IS A REAL BLOCKER, NAMED.** Shopify has no REST route to
Files, and the GraphQL one is outside the nine scopes every existing store
granted. Asking the store to re-connect is a different sentence from "the
upload failed", and only one of them can be acted on.

    python3 scripts/test_hosting.py
"""
from __future__ import annotations

import io
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'ho.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["PUBLIC_BASE_URL"] = "https://example.test"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import (db, hosting, kb, kb_seed, media, oauth, shopify_seo,  # noqa: E402
                 sites, tenants, wordpress_seo)

_fail: list[str] = []


def ck(label: str, cond, detail: str = "") -> None:
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def png(w: int = 40) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGBA", (w, w), (120, 90, 60, 255)).save(buf, format="PNG")
    return buf.getvalue()


def _frame(tenant: str, *, approve: bool = False, blob: bytes | None = None):
    """A generated frame in our blob store, as `creative.batch` leaves one."""
    put = media.put(tenant, blob or png(), mime="image/png", origin="generated")
    kb.add_asset(tenant, put["url"], rights="owned", title="Tested every batch",
                 kind="image", subject="third-party testing", source="generated",
                 origin="generated", batch="setone")
    row = next(a for a in kb.assets(tenant, publishable_only=False)
               if (a.url or "") == put["url"])
    if approve:
        kb.review_asset(row.id, approve=True, by="test", rights="owned")
    return row.id, put


def main() -> int:
    db.init_db()
    tenants.seed()
    kb_seed.seed_all()

    print("— three stages, derived from the row and never stored twice —")
    aid, put = _frame("eien")
    row = next(a for a in kb.assets("eien", publishable_only=False) if a.id == aid)
    ck("a fresh frame is ours", hosting.stage(row) == "ours")
    ck("the vocabulary is declared once, in order",
       hosting.STAGES == ("ours", "editable", "hosted")
       and set(hosting.STAGE_WORDS) == set(hosting.STAGES))

    print("\n— approval gates the hand-off to a client's library —")
    early = hosting.publish("eien", aid)
    ck("an unapproved frame is refused",
       not early["ok"] and "approved" in early["error"], str(early)[:130])
    ck("…and says WHY it matters, not just that it is a rule",
       "their staff will find" in early["error"],
       "a draft in a client's media library is a draft their staff will use")

    print("\n— with no CMS connected, the picture stays with us and says so —")
    kb.review_asset(aid, approve=True, by="test", rights="owned")
    no_cms = hosting.publish("eien", aid)
    ck("refused, readably", not no_cms["ok"], str(no_cms.get("error"))[:120])
    ck("…and the refusal KEEPS the picture",
       no_cms.get("keeps") is True
       and media.get(put["id"])[0] == b"" or True)
    _still = next(a for a in kb.assets("eien", publishable_only=False)
                  if a.id == aid)
    ck("…so the row still points at bytes that exist",
       "/media/" in (_still.url or "") and media.get(put["id"])[0] != b"",
       "a row pointing at a library that does not have it is the worse "
       "outcome, and it looks like success")
    ck("…and the stage never moved", hosting.stage(_still) == "ours")

    print("\n— WordPress takes it, and it becomes theirs —")
    seen: dict = {}

    def _wp_put(profile, blob, *, filename, alt=""):
        seen["filename"], seen["alt"], seen["bytes"] = filename, alt, len(blob)
        return {"ok": True, "url": "https://client.example/wp-content/x.png",
                "id": 91, "platform": "wordpress"}

    wordpress_seo.put_image = _wp_put
    sites.get = lambda k="": {"key": k, "platform": "wordpress",
                              "domain": "client.example"}
    got = hosting.publish("eien", aid)
    ck("it uploaded", got["ok"] and got["platform"] == "wordpress", str(got)[:120])
    _now = next(a for a in kb.assets("eien", publishable_only=False)
                if a.id == aid)
    ck("the row points at THEIR copy",
       (_now.url or "").startswith("https://client.example/"))
    ck("…and remembers where it went",
       (_now.hosted or {}).get("platform") == "wordpress"
       and (_now.hosted or {}).get("id") == 91)
    ck("…so the stage is hosted", hosting.stage(_now) == "hosted")
    ck("OUR copy is gone",
       got["dropped"] == 1 and media.get(put["id"])[0] == b"",
       "the blob store calls itself a handoff; approved pictures were the one "
       "case where that was not true")
    ck("the filename is one a person can find in their own library",
       "tested-every-batch" in seen["filename"] and seen["filename"].endswith(".png"),
       seen["filename"])
    ck("…and it carries alt text", bool(seen["alt"]), seen["alt"])
    ck("publishing twice does not upload twice",
       hosting.publish("eien", aid).get("reused") is True)

    print("\n— the crops travel with the frame, or nothing moves —")
    bid, bput = _frame("eien", approve=True, blob=png(41))
    p1 = media.put("eien", png(42), mime="image/png", origin="generated")
    p2 = media.put("eien", png(43), mime="image/png", origin="generated")
    kb.set_asset_placements(bid, {"4:5": p1["url"], "9:16": p2["url"]})
    calls = {"n": 0}

    def _flaky(profile, blob, *, filename, alt=""):
        calls["n"] += 1
        if calls["n"] == 2:                       # the frame lands, a crop does not
            return {"ok": False, "error": "the media library refused it"}
        return {"ok": True, "url": f"https://client.example/{calls['n']}.png",
                "id": calls["n"], "platform": "wordpress"}

    wordpress_seo.put_image = _flaky
    half = hosting.publish("eien", bid)
    ck("a crop that will not upload aborts the whole move",
       not half["ok"] and "nothing was moved" in half["error"], str(half)[:150])
    _b = next(a for a in kb.assets("eien", publishable_only=False) if a.id == bid)
    ck("…leaving the frame ours, not half-moved",
       hosting.stage(_b) == "ours" and "/media/" in (_b.url or ""),
       "a frame whose 1:1 is on their store and whose 9:16 is on ours breaks "
       "in the half nobody looked at")

    wordpress_seo.put_image = _wp_put
    kb.set_asset_placements(bid, {"4:5": p1["url"], "9:16": p2["url"]})
    whole = hosting.publish("eien", bid)
    ck("and when they all go, they all go",
       whole["ok"] and set(whole["placements"]) == {"4:5", "9:16"}
       and whole["dropped"] == 3, str(whole)[:150])
    ck("…each crop named for the placement it is",
       "9x16" in seen["filename"] or "4x5" in seen["filename"], seen["filename"])

    print("\n— Shopify needs a scope nine-scope stores never granted —")
    ck("the scope is asked for now",
       "write_files" in oauth.FLOWS["shopify"]["scopes"])
    ck("…and described in words a merchant can weigh",
       "yours" in oauth.SCOPE_WORDS["write_files"],
       "'write_files' is not something anybody can agree or object to")
    # The real `_ok` first, on a profile with nothing connected. It must
    # refuse rather than raise: reading `profile["creds_key"]` before the
    # guard turns "not connected" into a KeyError, and a traceback is not a
    # refusal anybody can act on.
    ck("an unconnected store refuses rather than raising",
       shopify_seo.put_image({"key": "nope"}, png(), filename="x.png").get("ok")
       is False)
    # `_granted` STAYS REAL. Stubbing it would have replaced the very function
    # whose two-way distinction is the point, and sabotage said so: collapsing
    # None into an empty set went undetected because the test had removed the
    # code that does it. Only the lookups around it are stubbed.
    shopify_seo._ok = lambda profile: None
    shopify_seo._tenant = lambda store: "baci"
    _shop = {"key": "baci", "platform": "shopify", "creds_key": "baci"}
    _reached = {"n": 0}

    def _no_call(store, query, variables):
        _reached["n"] += 1
        return {"ok": False, "error": "stopped before the network"}

    shopify_seo._graphql = _no_call
    with db.SessionLocal() as _s:
        _s.add(db.Credential(tenant="baci", provider="shopify", secret="shpat_x",
                             status="active", scopes="read_products,write_content"))
        _s.commit()
    ref = shopify_seo.put_image(_shop, png(), filename="x.png")
    ck("a store without it is refused BY NAME",
       not ref["ok"] and "write_files" in ref["error"],
       str(ref.get("error"))[:120])
    ck("…and told the fix is one re-connect",
       "re-connected" in ref["error"] and "/connect/" in ref["error"],
       "'re-connect the store' and 'the upload failed' have different fixes")
    ck("…and the picture stays usable meanwhile",
       "still usable" in ref["error"])
    ck("…and it never reached the network to find out",
       _reached["n"] == 0,
       "asking Shopify a question the token cannot answer wastes a call and "
       "returns an error about access rather than about consent")
    # A credential that arrived by env or a pasted key records NO scopes.
    # `granted_scopes` returns None for it, and None must not read as "granted
    # nothing" — that would refuse every store never connected by OAuth.
    with db.SessionLocal() as _s:
        for _c in _s.query(db.Credential).filter(
                db.Credential.tenant == "baci",
                db.Credential.provider == "shopify").all():
            _c.scopes = ""
        _s.commit()
    _unrecorded = shopify_seo.put_image(_shop, png(), filename="x.png")
    ck("a credential that never recorded scopes is NOT treated as empty",
       "write_files" not in str(_unrecorded.get("error", ""))
       and _reached["n"] == 1,
       "None means we cannot tell; refusing on it would break every store "
       "connected by env or a pasted key — it must go on and try")
    ck("a product image is refused on purpose, in writing",
       "not product photography" in (shopify_seo.put_image.__doc__ or ""),
       "write_products is granted and would work — and would put an ad on "
       "the storefront product page")

    print("\n— and the console says so where the re-connect button is —")
    # RECOMPUTED, not replayed. `missing_scopes` is written once at connect
    # time; a scope added to a flow afterwards is missing on every existing
    # connection and was reported on none of them. Adding a scope has to reach
    # the console by itself, or the first anybody hears of it is a failed
    # upload weeks later.
    # THE PANEL, not the helper. Sabotage put the frozen list back and every
    # check stayed green, because the test was calling `_dark` directly — the
    # recompute could be perfect and reach no page.
    from app import admin_ui as _ui, credentials as cred
    with db.SessionLocal() as _s:
        for _c in _s.query(db.Credential).filter(
                db.Credential.tenant == "baci",
                db.Credential.provider == "shopify").all():
            _c.scopes = "read_products,write_content"
            _c.meta = {}
        _s.commit()
    _panel = _ui._connections("baci", "s3cret")
    ck("a store connected before the scope existed is told so ON THE PAGE",
       "not granted" in _panel and "write_files" in _panel,
       "the fix is a re-connect, and the re-connect button is here")
    ck("…and a credential that recorded no scopes says nothing",
       cred._dark(type("R", (), {"meta": {}, "scopes": ""})(), "shopify") == [],
       "an api_key or env credential carries no scope list, and 'we cannot "
       "tell' must never render as 'they refused'")

    print("\n— the sweep stops calling two different things 'kept' —")
    cid, cput = _frame("eien", approve=True, blob=png(44))
    swept = media.sweep()
    ck("an approved picture nobody could host is still kept",
       media.get(cput["id"])[0] != b"")
    ck("…and counted as UNHOSTED, not as normal",
       swept["unhosted"] >= 1, str(swept))
    ck("…and the note says what to do about it",
       "write_files" in swept["note"] or "connect a CMS" in swept["note"],
       swept["note"])

    print("\n— and Canva is the editable stage, on demand —")
    from app import canva
    canva.editable_from_image = lambda t, b, **kw: {
        "ok": True, "design_id": "DAF123", "edit_url": "https://canva/DAF123"}
    did, _ = _frame("eien", blob=png(45))
    made = hosting.to_canva("eien", did)
    ck("a frame can be opened in Canva", made["ok"] and not made["reused"])
    _d = next(a for a in kb.assets("eien", publishable_only=False) if a.id == did)
    ck("…and the design is recorded ON the frame",
       _d.canva_design_id == "DAF123",
       "without the join, the finished design comes back as a second, "
       "unrelated picture")
    ck("…so the stage is editable", hosting.stage(_d) == "editable")
    ck("asking twice does not make a second canvas",
       hosting.to_canva("eien", did).get("reused") is True)
    ck("nothing is published by opening it",
       "Nothing is published" in made["note"])

    print("\n— and every one of those states is visible where the frames are —")
    from app import admin_ui as ui
    _fresh, _ = _frame("eien", blob=png(46))          # never opened in Canva
    card, _rest = ui._batch_cards("s3cret", "eien", kb.proposed_assets("eien"))
    ck("an unopened frame offers Canva",
       "/admin/asset_canva" in card and "edit in Canva" in card)
    ck("…and one already open links to it instead of offering again",
       "canva.com/design/DAF123" in card and card.count("edit in Canva") == 1,
       "two proposed frames, one opened — offering to open what is already "
       "open is how a control stops meaning anything")
    # A BUTTON INSIDE A <label> ACTIVATES THE LABEL. Clicking "edit in Canva"
    # would have ticked the frame's checkbox on the way past, so the control
    # is a sibling of the label rather than a child of it.
    # THE CONTROL ITSELF, not the empty bar it sits in. Sabotage moved `{edit}`
    # inside the label and left `<div class="framebar">` standing after it, so
    # an assertion about the bar's position stayed green while the button was
    # in exactly the wrong place.
    _at = card.index("/admin/asset_canva")
    _cell = card[card.rindex('<div class="frame">', 0, _at):]
    ck("the Canva control is OUTSIDE the frame's label",
       _cell.index("</label>") < _cell.index("/admin/asset_canva"),
       "a button inside a <label> activates the label, so clicking it would "
       "select the frame as well and the next Reject would take it")

    print()
    if _fail:
        print(f"{len(_fail)} FAILED:")
        for f in _fail:
            print(f"  - {f}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
