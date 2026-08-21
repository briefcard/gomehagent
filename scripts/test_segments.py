"""Segments organized by business model — tenant-generic, high-value first.

Checks that the catalog resolves from a client's business_model (a shop and a
venue get different segments), that high-value leads, that a missing model is
refused by name, and that `reconcile` marks which recommended segments already
exist in the live ESP vs are still to build.

Run: python3 scripts/test_segments.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'seg.db')}"
os.environ["APPROVAL_SECRET"] = "s"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, esp, segments, tenants  # noqa: E402

_fail: list[str] = []


def ck(label: str, cond: bool, detail: str = "") -> None:
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    db.init_db()
    tenants.seed()

    print("— segments follow from the business model —")
    baci = segments.for_tenant("baci")       # ecom_inventory
    iron = segments.for_tenant("ironside")   # local_venue
    ck("baci (ecom) resolves to the inventory catalog",
       baci["ok"] and baci["business_model"] == "ecom_inventory"
       and any(s["key"] == "reorder_due" for s in baci["segments"]))
    ck("ironside (venue) resolves to a DIFFERENT catalog",
       iron["ok"] and iron["business_model"] == "local_venue"
       and any(s["key"] == "past_bookers" for s in iron["segments"])
       and not any(s["key"] == "reorder_due" for s in iron["segments"]))
    cov = segments.for_tenant("coverings")   # b2b_spec
    ck("coverings (b2b) gets sample/quote segments",
       cov["ok"] and any(s["key"] == "quote_no_order" for s in cov["segments"]))

    print("\n— high-value leads, common follows —")
    ck("baci's high-value list is non-empty and separate",
       len(baci["high_value"]) >= 3 and all(s["tier"] == "high_value"
                                            for s in baci["high_value"]))
    ck("the ordered list puts a high-value segment first",
       baci["segments"][0]["tier"] == "high_value")

    print("\n— tenant-generic: two clients of one model share the catalog —")
    eien = segments.for_tenant("eien")       # also ecom_inventory
    ck("baci and eien (both ecom) get the same segment keys",
       {s["key"] for s in baci["segments"]} == {s["key"] for s in eien["segments"]})

    print("\n— a missing model is refused by name, not guessed —")
    with db.SessionLocal() as s:
        row = s.get(db.Tenant, "coverings")
        row.business_model = ""
        s.commit()
    r = segments.for_tenant("coverings")
    ck("no business_model refuses and says how to fix it",
       not r["ok"] and "business_model" in r["error"], r.get("error", "")[:70])

    print("\n— reconcile marks what exists in the live ESP vs to build —")
    esp.audiences = lambda t: {"ok": True, "kind": "segment",
                               "audiences": [{"id": "s1", "name": "Reorder due",
                                              "count": 240}]}
    rec = segments.reconcile("baci")
    ck("a matching ESP segment is marked 'exists' with its id",
       rec["ok"] and any(s["key"] == "reorder_due" and s["state"] == "exists"
                         and s["esp_segment_id"] == "s1" for s in rec["segments"]))
    ck("the rest are 'to_build'",
       any(s["state"] == "to_build" for s in rec["segments"])
       and len(rec["to_build"]) >= 5)

    esp.audiences = lambda t: {"ok": False, "error": "no ESP connected"}
    rec2 = segments.reconcile("baci")
    ck("no ESP connection → everything to_build, and it says why",
       rec2["ok"] and not rec2["esp_read"] and not rec2["exists"]
       and "no ESP" in rec2["esp_note"])

    print("\n— materialize builds the gap in the LIVE ESP, dry-run first —")
    _created: list = []

    class _Adapter:
        # The real Omnisend table, deliberately: the shapes the suite pins are
        # the shapes the live create will send.
        from app.omnisend import segment_conditions_for as _scf
        segment_conditions_for = staticmethod(_scf)

        @staticmethod
        def create_segment(tenant, name, groups):
            _created.append({"tenant": tenant, "name": name, "groups": groups})
            return {"ok": True, "segment_id": f"sid-{len(_created)}"}

        @staticmethod
        def draft_from_html(**kw):                       # esp.backend contract
            return {"ok": True}

    esp.audiences = lambda t: {"ok": True, "kind": "segment",
                               "audiences": [{"id": "s1", "name": "Reorder due",
                                              "count": 240}]}
    esp.backend = lambda t: (_Adapter, "")
    esp.provider_for = lambda t: "omnisend"

    dry = segments.materialize("baci")
    ck("dry-run is the default and CREATES NOTHING",
       dry["ok"] and not dry["applied"] and not _created
       and "dry run" in dry["note"], str(len(_created)))
    ck("what exists is not re-proposed (reorder_due matched live)",
       any(e["key"] == "reorder_due" for e in dry["existing"])
       and not any(w["key"] == "reorder_due" for w in dry["would_create"]))
    ck("the buildable gap is listed by name",
       {w["key"] for w in dry["would_create"]}
       >= {"vip_high_aov", "lapsed_60_90", "repeat_buyers"})
    ck("what the adapter cannot express is UNMAPPED with a why, never guessed",
       any(u["key"] == "cart_abandoners" and "natively" in u["why"]
           for u in dry["unmapped"]))

    built = segments.materialize("baci", apply=True)
    ck("apply creates exactly the would_create list",
       built["applied"] and {c["key"] for c in built["created"]}
       == {w["key"] for w in dry["would_create"]}
       and all(c["segment_id"] for c in built["created"]))
    lapsed = next(c["groups"] for c in _created
                  if c["name"] == "Lapsed (60–90 days)")
    ck("conditions are the adapter's own table (90d has AND 60d hasNot)",
       lapsed[0]["conditions"][0]["filters"][0]["period"]["value"] == 90
       and lapsed[0]["conditions"][0]["filters"][1]["operator"] == "hasNot",
       str(lapsed)[:90])

    made = [c["name"] for c in _created]      # snapshot BEFORE the clear — the
    # lambda must not close over the list it is meant to represent the past of
    esp.audiences = lambda t: {"ok": True, "kind": "segment", "audiences": [
        {"id": f"sid-{i}", "name": n, "count": 0}
        for i, n in enumerate(made, 1)] + [{"id": "s1", "name": "Reorder due",
                                            "count": 240}]}
    _created.clear()
    again = segments.materialize("baci", apply=True)
    ck("a second apply is idempotent — everything built now reads as existing",
       again["ok"] and not again["created"] and not _created)

    esp.audiences = lambda t: {"ok": False, "error": "token revoked"}
    r = segments.materialize("baci", apply=True)
    ck("an unreadable ESP refuses BEFORE writing — never risks duplicates",
       not r["ok"] and "unreadable" in r["error"] and not _created,
       r.get("error", "")[:70])

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
