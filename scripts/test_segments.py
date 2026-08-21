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
