"""The moment spine — a window, not a cart. Phases 1.1–1.3 of the initiative.

Every email this system sends is scheduled: a planner picks a segment and a
date. A moment is the other thing — a signal that a KNOWN PERSON is in a window
where a message is welcome.

The constraint that shaped it: this platform serves an e-commerce store, a
venue, a B2B specifier and a digital-products account. A property rental has no
carts; it has enquiries that go quiet. So the load-bearing test in this file is
not that either producer works. It is that **a venue enquiry going quiet and a
cart going cold land in the same table, and neither producer knows what the
other is for** — asserted against the source, because with one vertical the
vertical bakes into the generic layer and nobody finds out for a year.

Also pinned:

  1. THE CATALOGUE REFUSES BY NAME — no `business_model`, no moments, and the
     refusal says where the control is.
  2. THREE STATES, NOT TWO — live, unwatched (no connection) and unproduced
     (nothing files it). The fixes are different jobs and collapsing them is
     how a missing producer waits a year for the wrong person.
  3. THE WINDOW IS THE KIND'S, NOT THE CALLER'S — `due_at` and `expires_at`
     come from the declaration, so two producers cannot hold two ideas of a
     cold cart.
  4. FILING IS IDEMPOTENT — webhooks retry and sweeps overlap. That is normal
     traffic, not an error.
  5. AN ORDER CLOSES THE CART — the one thing the commerce producer does that
     files nothing, and the difference between a wasted send and a send that
     tells a customer nobody is watching.
  6. THE ENDPOINT IS VERIFIED — same HMAC over the raw body as the compliance
     route, same 401, because a second slightly-different implementation of a
     signature check is how one of them ends up weaker.

Run: python3 scripts/test_moments.py
"""
import base64
import datetime as dt
import hashlib
import hmac
import json
import os
import pathlib
import re
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'mo.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["SHOPIFY_CLIENT_ID"] = "test-client-id"
os.environ["SHOPIFY_CLIENT_SECRET"] = "test-client-secret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import (commerce_events, credentials as cred, db,  # noqa: E402
                 inbox_events, moments, segments, tenants, web)

_fail: list[str] = []
SHOP = "acme.myshopify.com"
SECRET = b"test-client-secret"
ROOT = pathlib.Path(__file__).resolve().parent.parent


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def sign(raw: bytes) -> str:
    return base64.b64encode(hmac.new(SECRET, raw, hashlib.sha256).digest()).decode()


def post(c, topic, payload, shop=SHOP, sig=None):
    raw = json.dumps(payload).encode()
    return c.post("/webhooks/shopify/commerce", content=raw,
                  headers={"X-Shopify-Hmac-Sha256": sig if sig is not None
                           else sign(raw),
                           "X-Shopify-Topic": topic,
                           "X-Shopify-Shop-Domain": shop,
                           "Content-Type": "application/json"})


def _open_conversation(tenant, email, *, quiet_hours, subject="Wedding, June"):
    """One open enquiry whose last touch was `quiet_hours` ago."""
    with db.SessionLocal() as s:
        con = db.Contact(tenant=tenant, email=email, name="A Planner")
        s.add(con)
        s.flush()
        conv = db.Conversation(
            tenant=tenant, contact_id=con.id, system_key="lead_responder",
            subject=subject, status="open", entity_key="",
            last_touch_at=db.utcnow() - dt.timedelta(hours=quiet_hours))
        s.add(conv)
        s.commit()
        return conv.id


def main() -> int:
    db.init_db()
    tenants.seed()
    c = TestClient(web.app)
    with db.SessionLocal() as s:
        s.add(db.Credential(tenant="baci", provider="shopify", kind="api_key",
                            secret=cred._encrypt("shpat_secret"),
                            meta={"domain": SHOP}, status="active"))
        s.commit()

    # ---------------------------------------------------------------- 1 ----
    print("— the catalogue follows the business model, and refuses by name —")
    with db.SessionLocal() as s:
        t = s.get(db.Tenant, "baci")
        _kept, t.business_model = t.business_model, ""
        s.commit()
    got = moments.for_tenant("baci")
    ck("no business_model is a refusal, not an empty list",
       not got["ok"] and "business_model" in got["error"], str(got)[:90])
    ck("and it names the control that fixes it",
       "Connections tab" in got["error"], got["error"][:70])
    with db.SessionLocal() as s:
        t = s.get(db.Tenant, "baci")
        t.business_model = _kept
        s.commit()

    shop_moments = moments.for_tenant("baci")
    venue_moments = moments.for_tenant("ironside")
    ck("a shop and a venue get different moments",
       shop_moments["ok"] and venue_moments["ok"]
       and {m["key"] for m in shop_moments["moments"]}
       != {m["key"] for m in venue_moments["moments"]})
    ck("the venue's moments contain no cart",
       not any("cart" in m["key"] for m in venue_moments["moments"]),
       str([m["key"] for m in venue_moments["moments"]]))

    ck("every moment bridges to a segment its own model really has",
       all(m["segment"] in {s["key"] for s in segments.CATALOG[model]}
           for model, rows in moments.CATALOG.items() for m in rows))

    # ---------------------------------------------------------------- 2 ----
    print("\n— live, unwatched and unproduced are three different problems —")
    ck("the fixture really has an unproduced moment in it",
       any(not m["producer"] for m in venue_moments["moments"]),
       "otherwise the split below passes for the wrong reason")
    ck("a declared-but-unwritten producer is reported as unproduced",
       {m["key"] for m in venue_moments["unproduced"]}
       == {"date_approaching", "event_just_held"},
       str([m["key"] for m in venue_moments["unproduced"]]))
    ck("and it says so in words, not by being absent",
       all("nothing files it" in m["why"] for m in venue_moments["unproduced"]))
    ck("no moment is in more than one of the three states",
       len(venue_moments["live"]) + len(venue_moments["unwatched"])
       + len(venue_moments["unproduced"]) == len(venue_moments["moments"]))

    # ---------------------------------------------------------------- 3 ----
    print("\n— the window belongs to the KIND, not to whoever files it —")
    bad = moments.record("ironside", "cart_cooling", "x@y.com",
                         dedup_key="nope")
    ck("a venue cannot be given a cart moment",
       not bad["ok"] and "not a moment for a local_venue" in bad["error"],
       str(bad)[:100])
    ck("and the refusal lists what this account CAN have",
       "enquiry_quiet" in bad["error"], bad["error"][-70:])
    anon = moments.record("baci", "cart_cooling", "  ", dedup_key="anon")
    ck("a moment with nobody to write to is refused",
       not anon["ok"] and "NAMED person" in anon["error"], str(anon)[:80])

    at = db.utcnow() - dt.timedelta(hours=1)
    got = moments.record("baci", "cart_cooling", "Buyer@Example.COM",
                         dedup_key="cart:1", occurred_at=at,
                         entity_key="aqua-pitcher")
    spec = moments.spec("ecom_inventory", "cart_cooling")
    ck("due_at is the declaration's, measured from the signal",
       abs((db.as_utc(got["due_at"]) - at).total_seconds()
           - spec["due_after_hours"] * 3600) < 2, str(got["due_at"]))
    ck("expires_at likewise",
       abs((db.as_utc(got["expires_at"]) - at).total_seconds()
           - spec["expires_after_hours"] * 3600) < 2)
    with db.SessionLocal() as s:
        row = s.get(db.Moment, got["moment_id"])
        ck("the identity is normalised, so one person is one person",
           row.person_key == "buyer@example.com", row.person_key)

    again = moments.record("baci", "cart_cooling", "buyer@example.com",
                           dedup_key="cart:1")
    ck("filing the same thing twice is one moment, not an error",
       again["ok"] and not again["created"]
       and again["moment_id"] == got["moment_id"], str(again))

    # ---------------------------------------------------------------- 4 ----
    print("\n— the commerce producer: a cart goes cold, an order closes it —")
    r = post(c, "checkouts/create", {
        "token": "chk_1", "currency": "USD",
        "customer": {"email": "shopper@example.com"},
        "line_items": [{"handle": "aqua-pitcher", "quantity": 1}]})
    ck("a verified checkout is accepted", r.status_code == 200, str(r.status_code))
    open_now = [m for m in moments.due("baci") if m.kind == "cart_cooling"]
    with db.SessionLocal() as s:
        cart = (s.query(db.Moment)
                .filter(db.Moment.dedup_key == "cart_cooling:chk_1").first())
    ck("it filed a cart moment for that person",
       cart is not None and cart.person_key == "shopper@example.com",
       str(cart and cart.person_key))
    ck("it is NOT due yet — a cart is not cold the instant it is left",
       cart.id not in {m.id for m in open_now},
       "writing immediately reads as surveillance")
    ck("and it recorded what it is about",
       cart.entity_key == "aqua-pitcher", cart.entity_key)

    post(c, "checkouts/update", {
        "token": "chk_1", "customer": {"email": "shopper@example.com"},
        "line_items": [{"handle": "aqua-pitcher", "quantity": 3}]})
    with db.SessionLocal() as s:
        n = (s.query(db.Moment)
             .filter(db.Moment.kind == "cart_cooling",
                     db.Moment.person_key == "shopper@example.com").count())
    ck("editing the basket four times is still one moment", n == 1, str(n))

    post(c, "orders/create", {
        "id": 991, "customer": {"email": "shopper@example.com", "orders_count": 1},
        "line_items": [{"handle": "aqua-pitcher"}]})
    with db.SessionLocal() as s:
        cart = (s.query(db.Moment)
                .filter(db.Moment.dedup_key == "cart_cooling:chk_1").first())
    ck("buying closes the cart moment", cart.status == "suppressed", cart.status)
    ck("and it is closed with a REASON, not deleted",
       "they ordered" in (cart.closed_reason or ""), cart.closed_reason)

    post(c, "orders/fulfilled", {
        "id": 991, "order_number": 1001,
        "customer": {"email": "shopper@example.com", "orders_count": 1},
        "line_items": [{"handle": "aqua-pitcher"}]})
    post(c, "orders/fulfilled", {
        "id": 992, "order_number": 1002,
        "customer": {"email": "regular@example.com", "orders_count": 7},
        "line_items": [{"handle": "aqua-pitcher"}]})
    with db.SessionLocal() as s:
        firsts = (s.query(db.Moment)
                  .filter(db.Moment.kind == "first_order_landed").all())
    ck("a first order is a moment; a seventh is not",
       [m.person_key for m in firsts] == ["shopper@example.com"],
       str([m.person_key for m in firsts]))

    print("\n  the endpoint is verified, exactly like the compliance one")
    before = _count()
    r = post(c, "checkouts/create",
             {"token": "chk_evil", "customer": {"email": "e@x.com"}},
             sig="not-a-signature")
    ck("an unsigned delivery is 401", r.status_code == 401, str(r.status_code))
    ck("and nothing was filed from it", _count() == before, str(_count()))

    # ---------------------------------------------------------------- 5 ----
    print("\n— the inbox producer: an enquiry goes quiet —")
    fresh = _open_conversation("ironside", "fresh@example.com", quiet_hours=2)
    quiet = _open_conversation("ironside", "quiet@example.com", quiet_hours=96)
    ancient = _open_conversation("ironside", "ancient@example.com",
                                 quiet_hours=24 * 60)
    got = inbox_events.sweep("ironside")
    with db.SessionLocal() as s:
        rows = s.query(db.Moment).filter(db.Moment.kind == "enquiry_quiet").all()
        who = {r.person_key for r in rows}
    ck("the quiet enquiry became a moment", "quiet@example.com" in who, str(who))
    ck("a conversation touched two hours ago did not",
       "fresh@example.com" not in who)
    ck("and one quiet for two months did not — that is a post-mortem",
       "ancient@example.com" not in who,
       "filing it would create a row that can never be served")

    with db.SessionLocal() as s:
        m = (s.query(db.Moment)
             .filter(db.Moment.person_key == "quiet@example.com").first())
    ck("its clock starts at the LAST TOUCH, not at the sweep",
       abs((db.as_utc(m.occurred_at) - db.utcnow()).total_seconds()
           + 96 * 3600) < 120, str(m.occurred_at))
    ck("so it is due now, rather than three days after a cron happened to run",
       m.id in {x.id for x in moments.due("ironside")})
    ck("it carries the thread it came from",
       m.conversation_id == quiet, m.conversation_id)

    again = inbox_events.sweep("ironside")
    ck("sweeping again files nothing new", again["filed"] == 0, str(again))

    # ---------------------------------------------------------------- 6 ----
    print("\n— THE PROOF: two verticals, one table, two ignorant producers —")
    with db.SessionLocal() as s:
        kinds = {(r.tenant, r.kind, r.source) for r in s.query(db.Moment).all()}
    ck("a cart going cold and an enquiry going quiet are both Moments",
       ("baci", "cart_cooling", "commerce") in kinds
       and ("ironside", "enquiry_quiet", "inbox") in kinds, str(sorted(kinds)))

    commerce_src = (ROOT / "app" / "commerce_events.py").read_text().lower()
    inbox_src = (ROOT / "app" / "inbox_events.py").read_text().lower()
    spine_src = (ROOT / "app" / "moments.py").read_text().lower()
    # Docstrings state the constraint, so they are excluded — what must be
    # clean is the CODE. Prose explaining why a cart must not leak in is not
    # a cart leaking in.
    commerce_code = _code_only(commerce_src)
    inbox_code = _code_only(inbox_src)
    ck("the commerce producer's code says nothing about conversations",
       not _leaks(commerce_code, ("conversation", "enquiry", "venue", "booking")),
       _leaks(commerce_code, ("conversation", "enquiry", "venue", "booking")))
    ck("the inbox producer's code says nothing about carts",
       not _leaks(inbox_code, ("cart", "checkout", "order", "shopify")),
       _leaks(inbox_code, ("cart", "checkout", "order", "shopify")))
    ck("and neither producer imports the other",
       "inbox_events" not in commerce_code and "commerce_events" not in inbox_code)
    ck("the inbox producer reaches for no commerce module at all",
       "shopify" not in inbox_code and "catalog_sync" not in inbox_code,
       _first_import_hit(inbox_code))
    # The CATALOGUE is data and is SUPPOSED to name verticals — that is what a
    # catalogue is. What must stay neutral is the LOGIC, so this reads only
    # from the first top-level `def` onward: no function in the spine may
    # mention a cart, a checkout, a booking or a venue.
    spine_logic = _code_only(_functions_only(spine_src))
    ck("no FUNCTION in the spine mentions a vertical — the catalogue may",
       not _leaks(spine_logic, ("cart", "checkout", "shopify", "booking",
                                "venue", "enquiry")),
       _leaks(spine_logic, ("cart", "checkout", "shopify", "booking",
                            "venue", "enquiry")))
    ck("and the fixture proves that check can see the catalogue it excluded",
       _leaks(_code_only(spine_src), ("cart", "booking")) != "",
       "if the CATALOG were invisible too, the assertion above would be empty")

    # ---------------------------------------------------------------- 7 ----
    print("\n— what expires, closes —")
    old = moments.record("baci", "cart_cooling", "gone@example.com",
                         dedup_key="cart:old",
                         occurred_at=db.utcnow() - dt.timedelta(days=40))
    ck("the fixture has a past-window moment in it", old["ok"] and old["created"])
    with db.SessionLocal() as s:
        s.get(db.Moment, old["moment_id"]).status = "open"
        s.commit()
    n = moments.expire_stale()
    with db.SessionLocal() as s:
        row = s.get(db.Moment, old["moment_id"])
    ck("a moment past its window is expired, not served",
       n >= 1 and row.status == "expired", f"{n} closed, status={row.status}")
    ck("and it says why", "window closed" in (row.closed_reason or ""),
       row.closed_reason)
    ck("expired moments are never returned as due",
       row.id not in {m.id for m in moments.due("baci")})

    print("\n" + ("FAILURES: " + ", ".join(_fail) if _fail else "all good"))
    return 1 if _fail else 0


def _count() -> int:
    with db.SessionLocal() as s:
        return s.query(db.Moment).count()


def _code_only(src: str) -> str:
    """Source with docstrings and comments stripped — what actually RUNS."""
    out, in_doc = [], False
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.count('"""') == 2:
            continue
        if '"""' in stripped:
            in_doc = not in_doc
            continue
        if in_doc or stripped.startswith("#"):
            continue
        out.append(line.split("  #")[0])
    return "\n".join(out)


def _first_import_hit(code: str) -> str:
    return next((ln.strip() for ln in code.splitlines()
                 if "shopify" in ln or "catalog_sync" in ln), "")


def _functions_only(src: str) -> str:
    """Everything from the first top-level `def` — the logic, not the data."""
    m = re.search(r"^def ", src, re.M)
    return src[m.start():] if m else src


def _leaks(code: str, words) -> str:
    """The first vertical word used as a WORD, or "".

    Word boundaries matter: `.order_by(` is a SQL clause and `order` inside it
    is not a commerce concept. A substring match called that a leak and would
    have had this suite failing on correct code — which is how an
    architectural test gets switched off.
    """
    for w in words:
        m = re.search(rf"\b{w}s?\b", code)
        if m:
            i = m.start()
            return ("leaked %r: ..." % m.group(0)
                    + code[max(0, i - 40):i + 40].replace("\n", " "))
    return ""


if __name__ == "__main__":
    sys.exit(main())
