"""Emptying one account, with the damage shown before it is done.

Wiping everything to rehearse onboarding does not test onboarding: the seed
puts the five accounts back and repopulates three of them from hardcoded
facts. What is worth having is emptying ONE account — a client who changed
direction, a demo after a pitch, a real rehearsal on a tenant nobody seeded.

The checks that matter are the refusals. A reset that deletes slightly more or
slightly less than it said is worse than none, because the account then looks
empty and is not.

    python3 scripts/test_reset.py
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'rs.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import db, kb, reset, tenants  # noqa: E402
from app.web import app  # noqa: E402

_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    with TestClient(app) as cl:
        tenants.seed()
        for t in ("baci", "eien"):
            kb.ensure_brand(t, t.title())
            kb.add_banned(t, "made in Italy")
            kb.add_situation(t, "quality_doubt", patterns=[["dishwasher"]],
                             origin="seed")
            kb.add_claim(t, f"A claim belonging to {t}.", "evidence",
                         ["quality_doubt"], proof_type="data", source="seed",
                         origin="human")
        with db.SessionLocal() as s:
            s.add(db.Contact(tenant="baci", email="a@b.com", name="A"))
            s.add(db.Credential(tenant="baci", provider="shopify",
                                secret="x"))
            s.commit()

        print("— an empty tenant is refused, not treated as a wildcard —")
        r = reset.preview("")
        ck("it refuses", "error" in r)
        ck("and says why UNASSIGNED is dangerous",
           "unattributed" in r["error"],
           "tenant='' would match every row nobody could attribute")

        print("\n— an unknown account touches nothing —")
        ck("refused by name", "unknown account" in reset.preview("nope")["error"])

        print("\n— the preview does not delete —")
        p = reset.preview("baci")
        ck("it counts real rows", p["total"] > 0, str(p["rows"]))
        ck("but applied is false", p["applied"] is False)
        ck("and the rows are still there", len(kb.claims("baci")) == 1)

        print("\n— credentials are NOT in the default —")
        ck("no credential row is counted", "credentials" not in p["rows"],
           str(list(p["rows"])))
        ck("and it says whose time that protects",
           "redo OAuth" in p["warning"], p["warning"][:60])
        withacc = reset.preview("baci", groups=("knowledge", "operations",
                                                "access"))
        ck("asking for them explicitly includes them",
           "credentials" in withacc["rows"], str(list(withacc["rows"])))

        print("\n— the table list comes from the SCHEMA, not a literal —")
        models = reset._tenant_models()
        ck("every tenant-carrying model is discovered",
           "kb_claims" in models and "conversations" in models
           and "outputs" in models, str(len(models)) + " models")
        ck("and anything unclassified is reported, not skipped quietly",
           "unclassified_tables" in p, str(p["unclassified_tables"]))
        # This report caught `kb_brands` vs the real `kb_brand`: a knowledge
        # reset would have left the ban list intact and said it succeeded.
        ck("every tenant-carrying table is now classified",
           p["unclassified_tables"] == [], str(p["unclassified_tables"]))
        ck("and the brand row IS in the knowledge group",
           "kb_brand" in reset.KNOWLEDGE, "singular, checked against the schema")

        print("\n— it empties one account and leaves the other alone —")
        done = reset.reset("baci", apply=True)
        ck("it deleted", done["applied"] and done["total"] > 0, str(done["total"]))
        ck("baci is empty", kb.claims("baci") == [])
        ck("including the ban list — the row that was nearly missed",
           not (kb.brand("baci") and kb.brand("baci").banned_claims),
           "a reset that leaves the rules behind is worse than none")
        ck("eien is untouched", len(kb.claims("eien")) == 1,
           "the whole point of scoping")
        with db.SessionLocal() as s:
            ck("and baci's credential survived a knowledge reset",
               s.query(db.Credential).filter(
                   db.Credential.tenant == "baci").count() == 1)

        print("\n— the account itself stays, so onboarding can start —")
        ck("the tenant row is kept", tenants.get("baci") is not None,
           "an emptied account is still an account")

        print("\n— behind the admin key, and reporting by default —")
        r = cl.get("/admin/tenant_reset", params={"tenant": "eien"})
        ck("no credential is refused", r.json().get("error") == "unauthorized")
        r = cl.get("/admin/tenant_reset", params={"tenant": "eien",
                                                  "key": "s3cret"})
        ck("the route reports without deleting",
           r.json()["applied"] is False and len(kb.claims("eien")) == 1,
           "a GET that deletes is fired by a browser prefetch")

    print()
    if _fail:
        print(f"FAILED {len(_fail)}:")
        for f in _fail:
            print(f"  - {f}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
