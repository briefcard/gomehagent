"""Shopify's three mandatory privacy webhooks, and the line between them.

Every public app must handle `customers/data_request`, `customers/redact` and
`shop/redact`; app review checks it, and they carry a thirty-day legal
deadline. Two things this file holds.

**The signature is over the RAW body.** Verifying a re-serialised payload does
not round-trip — `json.loads` then `json.dumps` reorders and re-spaces — so a
digest computed after parsing fails on valid deliveries. An unverified request
must be 401, not 200: answering 200 to whatever arrives is precisely the
failure the signature exists to prevent.

**What code may decide, and what it may not.** `shop/redact` is mechanical.
The customer topics are not: this system stores no Shopify customer records
(they are read live, which is why `lookups` exists), but it does store REPLIES,
and whether a sentence in a drafted email is "the customer's personal data" is
a judgement about content. A redactor that guessed would either delete a
client's correspondence or claim a deletion it did not make.

    python3 scripts/test_shopify_compliance.py
"""
import base64
import hashlib
import hmac
import json
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'sc.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["SHOPIFY_CLIENT_ID"] = "test-client-id"
os.environ["SHOPIFY_CLIENT_SECRET"] = "test-client-secret"
os.environ["PUBLIC_BASE_URL"] = "https://ops.example.com"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import credentials as cred, db, kb, tenants, web  # noqa: E402

_fail: list[str] = []
SHOP = "acme.myshopify.com"
SECRET = b"test-client-secret"


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def sign(raw: bytes) -> str:
    return base64.b64encode(hmac.new(SECRET, raw, hashlib.sha256).digest()).decode()


def post(c, topic, payload, shop=SHOP, tamper=False, sig=None):
    raw = json.dumps(payload).encode()
    header = sig if sig is not None else sign(raw)
    if tamper:
        payload = {**payload, "injected": True}
        raw = json.dumps(payload).encode()      # signed body != sent body
    return c.post("/webhooks/shopify/compliance", content=raw,
                  headers={"X-Shopify-Hmac-Sha256": header,
                           "X-Shopify-Topic": topic,
                           "X-Shopify-Shop-Domain": shop,
                           "Content-Type": "application/json"})


def main() -> int:
    db.init_db()
    tenants.seed()
    c = TestClient(web.app)

    print("— nothing is believed without Shopify's signature —")
    body = {"shop_domain": SHOP}
    ck("an unsigned delivery is 401",
       post(c, "shop/redact", body, sig="").status_code == 401,
       "200 to whatever arrives is the failure this check exists to prevent")
    ck("  a forged signature is 401",
       post(c, "shop/redact", body, sig="AAAA").status_code == 401)
    ck("  a signature that no longer covers the body is 401",
       post(c, "shop/redact", body, tamper=True).status_code == 401,
       "signed one payload, sent another")
    ck("  and a valid one is accepted",
       post(c, "shop/redact", body).status_code == 200)
    with db.SessionLocal() as s:
        n = s.query(db.ComplianceEvent).count()
    ck("only the verified one was recorded", n == 1, str(n))

    print("\n— shop/redact is mechanical, and does exactly its own job —")
    cred.store("baci", "shopify", "shpat_" + "x" * 20,
               meta={"domain": SHOP}) if False else None
    # Store a credential directly: `store()` probes the live API, which this
    # suite must not do.
    with db.SessionLocal() as s:
        s.add(db.Credential(tenant="baci", provider="shopify", kind="api_key",
                            secret=cred._encrypt("shpat_secret"),
                            meta={"domain": SHOP}, status="active"))
        s.commit()
    kb.ensure_brand("baci", "Baci Milano USA")
    kb.add_entity("baci", "product", "aqua-jug", "Aqua Jug",
                  origin="store_sync", source="shopify")
    kb.add_claim("baci", "A claim a human wrote", "somewhere", [])

    r = post(c, "shop/redact", {"shop_domain": SHOP})
    ck("it is accepted", r.status_code == 200)
    ck("  the store's credential is gone",
       not cred.resolve("baci", "shopify").get("secret"))
    ck("  and what we copied from its catalogue with it",
       not [e for e in kb.entities("baci", available_only=False)
            if e.key == "aqua-jug"])
    ck("  but NOT the client's own knowledge base",
       kb.brand("baci") is not None and len(kb.claims("baci")) >= 0,
       "an uninstall must not destroy material that never came from Shopify")

    print("\n— the customer topics refuse to guess, and say what we hold —")
    with db.SessionLocal() as s:
        s.add(db.Output(tenant="baci", body="Reply to jane@example.com about her order",
                        status="published"))
        s.commit()
    post(c, "customers/redact",
         {"shop_domain": SHOP, "customer": {"email": "jane@example.com"},
          "orders_to_redact": [123]})
    with db.SessionLocal() as s:
        ev = (s.query(db.ComplianceEvent)
              .filter(db.ComplianceEvent.topic == "customers/redact").first())
        note = ev.needs_human
    ck("it is queued for a person", bool(note), note)
    ck("  naming where the address appears", "output" in note, note)
    ck("  and saying these are ours, not Shopify's",
       "not Shopify" in note or "OUR correspondence" in note, note)
    with db.SessionLocal() as s:
        still = s.query(db.Output).filter(
            db.Output.body.ilike("%jane@example.com%")).count()
    ck("  and NOTHING was deleted on a guess", still == 1,
       "deleting a client's correspondence to satisfy a request that never "
       "covered it is worse than saying what we hold")

    print("\n— a customer we have never seen is answered honestly —")
    post(c, "customers/data_request",
         {"shop_domain": SHOP, "customer": {"email": "nobody@example.com"}})
    with db.SessionLocal() as s:
        ev = (s.query(db.ComplianceEvent)
              .filter(db.ComplianceEvent.topic == "customers/data_request")
              .first())
    ck("it says we hold no Shopify customer records",
       "read live" in ev.needs_human, ev.needs_human)
    ck("  rather than reporting an empty success", "Confirm and close" in ev.needs_human)

    print("\n— an unknown topic is recorded, not rejected —")
    r = post(c, "orders/create", {"id": 1})
    ck("it is still 200", r.status_code == 200,
       "a 4xx on an unexpected topic looks like a broken endpoint to their tests")
    with db.SessionLocal() as s:
        ev = (s.query(db.ComplianceEvent)
              .filter(db.ComplianceEvent.topic == "orders/create").first())
    ck("  and it says nothing was done", "nothing was done" in ev.needs_human)

    print("\n— a malformed body never 500s —")
    raw = b"{not json"
    r = c.post("/webhooks/shopify/compliance", content=raw,
               headers={"X-Shopify-Hmac-Sha256": sign(raw),
                        "X-Shopify-Topic": "shop/redact",
                        "X-Shopify-Shop-Domain": SHOP})
    ck("it is accepted rather than retried for days", r.status_code == 200,
       "Shopify retries a failure for days — one bad payload becomes a flood")

    print("\n— the owner can see and close what is outstanding —")
    q = c.get("/admin/privacy_requests?key=s3cret").json()
    ck("the open queue is readable", q["count"] >= 3, str(q.get("count")))
    ck("  each says what was done automatically",
       any(r["done_automatically"] for r in q["requests"]))
    rid = q["requests"][0]["id"]
    ck("  and one can be closed", c.get(
        f"/admin/privacy_close?key=s3cret&id={rid}").json().get("ok") is True)
    after = c.get("/admin/privacy_requests?key=s3cret").json()
    ck("  which takes it off the open list", after["count"] == q["count"] - 1)
    # A FRESH client, because the one above authenticated earlier and carries
    # the console session cookie — testing "no key" on it reads as authorised
    # and the assertion passes for the wrong reason. This codebase has been
    # caught by that cookie before.
    anon = TestClient(web.app)
    r = anon.get("/admin/privacy_requests")
    ck("unauthorised cannot read it",
       r.status_code >= 400 or "error" in r.json(),
       f"{r.status_code} {str(r.json())[:60]}")

    print("\n— the new table is classified, so a reset cannot silently spare it —")
    from app import reset
    ck("no unclassified tables", not reset.preview("baci")["unclassified_tables"],
       str(reset.preview("baci")["unclassified_tables"]),)

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
