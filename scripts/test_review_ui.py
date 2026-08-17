"""Reviewing a harvest queue: batch decisions, duplicates, entity lookup.

These are workflow defects, not logic ones, and they are the reason a queue of
forty proposals stops being worked:

  · one request per claim, each returning the reader to the top of the page
  · the same fact filed once per product, when one brand-level row covers all
  · an entity picker searchable only by slug, when the reviewer knows the name

Run: python3 scripts/test_review_ui.py
"""
import os
import sys
import tempfile

_tmp = os.path.join(tempfile.mkdtemp(), "review.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}"
os.environ["APPROVAL_SECRET"] = "test-secret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import db, kb, tenants  # noqa: E402
from app.web import app  # noqa: E402

KEY = "test-secret"
client = TestClient(app)
_fails: list[str] = []


def ck(label: str, cond: bool, detail: str = "") -> None:
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fails.append(label)


def _pending(tenant="baci"):
    return [e["row"] for e in kb.proposals(tenant, kind="claim").get("claim", [])]


def main() -> int:
    db.init_db()
    tenants.seed()

    kb.set_brand("baci", tone="Warm, precise.")
    kb.add_banned("baci", "hand-decorated")
    kb.add_situation("baci", "care", patterns=[["dishwasher"]], origin="human")
    kb.add_entity("baci", "product", "bm-aq-din-25", "Aqua Dinner Plate",
                  description="A dinner plate")
    kb.add_entity("baci", "product", "bm-tu-mug-30", "Tulip Mug",
                  description="A mug")

    print("— finding the entity a claim belongs to —")
    ck("by its display name", kb.resolve_entity_ref("baci", "Aqua Dinner Plate")
       == ("bm-aq-din-25", ""))
    ck("by a unique partial, in any order",
       kb.resolve_entity_ref("baci", "plate aqua")[0] == "bm-aq-din-25")
    ck("by the slug, which still works",
       kb.resolve_entity_ref("baci", "bm-tu-mug-30")[0] == "bm-tu-mug-30")
    ck("by what the picker actually submits",
       kb.resolve_entity_ref("baci", "bm-tu-mug-30 — Tulip Mug")[0]
       == "bm-tu-mug-30")
    ck("blank stays blank — brand-level is a real answer, not a failure",
       kb.resolve_entity_ref("baci", "") == ("", ""))
    key, why = kb.resolve_entity_ref("baci", "nope")
    ck("an unmatched entity is REFUSED, not written through", not key and why,
       "a claim scoped to a thing that does not exist reads as 'not "
       "selectable' much later, far from the cause")
    kb.add_entity("baci", "product", "bm-aq-sal-21", "Aqua Salad Plate",
                  description="A salad plate")
    key, why = kb.resolve_entity_ref("baci", "aqua")
    ck("an ambiguous one names the candidates instead of guessing",
       not key and "matches 2" in why, why[:80])

    print("\n— deciding a queue in one pass —")
    kb.add_claim("baci", "Dishwasher and microwave safe throughout.",
                 "EN 12875-1", ["care"], origin="human")          # approved
    for i in range(4):
        kb.add_claim("baci", f"Proposal number {i} about care.", "crawl",
                     ["care"], status="pending", origin="crawl")
    ids = [c.id for c in _pending()]
    ck("four proposals are waiting", len(ids) == 4, str(len(ids)))

    # `key` goes in the query string, not the body: `admin_key` resolves it
    # from query, `x-admin-key`, or the session cookie a browser already has.
    r = client.post("/admin/claims_decide", params={"key": KEY},
                    data={"tenant": "baci", "action": "approve",
                          "claim_ids": ids[:3]}, follow_redirects=False)
    ck("a batch approve is accepted", r.status_code == 303, str(r.status_code))
    ck("  three decided in ONE request, not three",
       len(_pending()) == 1, f"{len(_pending())} still pending")
    ck("  and it reports what it did", "ok=" in r.headers.get("location", ""),
       r.headers.get("location", ""))

    r = client.post("/admin/claims_decide", params={"key": KEY},
                    data={"tenant": "baci", "action": "reject",
                          "claim_ids": [ids[3]]}, follow_redirects=False)
    ck("a batch reject works the same way", len(_pending()) == 0,
       f"{len(_pending())} left")
    r = client.post("/admin/claims_decide", params={"key": KEY},
                    data={"tenant": "baci", "action": "approve"},
                    follow_redirects=False)
    ck("selecting nothing says so rather than silently succeeding",
       "nothing+was+selected" in r.headers.get("location", "")
       or "nothing%20was%20selected" in r.headers.get("location", ""),
       r.headers.get("location", ""))

    print("\n— the duplicates mass harvest leaves behind —")
    kb.add_claim("baci", "Dishwasher and microwave safe throughout.",
                 "aqua product page", ["care"], status="pending",
                 origin="crawl", entity_key="bm-aq-din-25")
    kb.add_claim("baci", "Dishwasher and microwave safe throughout.",
                 "mug product page", ["care"], status="pending",
                 origin="crawl", entity_key="bm-tu-mug-30")
    kb.add_claim("baci", "Packed in recycled board.", "crawl", ["care"],
                 status="pending", origin="crawl")
    covered = kb.brand_level_duplicates("baci")
    ck("per-entity copies of an approved brand-level claim are spotted",
       len(covered) == 2, f"{len(covered)} found")
    ck("  a genuinely new claim is NOT swept up with them",
       len(_pending()) == 3 and len(covered) == 2)

    r = client.post("/admin/claims_decide", params={"key": KEY},
                    data={"tenant": "baci", "action": "reject_covered"},
                    follow_redirects=False)
    left = _pending()
    ck("one action retires every covered copy", len(left) == 1, str(len(left)))
    ck("  and leaves the one that adds something",
       left and "recycled board" in left[0].claim, left[0].claim if left else "")

    print("\n— not losing your place —")
    kb.add_claim("baci", "First in the queue.", "crawl", ["care"],
                 status="pending", origin="crawl")
    q = _pending()
    first = q[0].id
    r = client.post("/admin/claim_edit", params={"key": KEY},
                    data={"tenant": "baci", "claim_id": first,
                          "next_id": "SOMEONE-ELSE", "claim": q[0].claim,
                          "evidence": "crawl", "tags": ["care"],
                          "entity_key": "", "action": "approve"},
                    follow_redirects=False)
    loc = r.headers.get("location", "")
    ck("deciding one card returns you to the NEXT one, not the top",
       loc.endswith("#c-SOMEONE-ELSE"), loc)

    html = client.get("/admin/ui",
                      params={"key": KEY, "tab": "content",
                              "tenant": "baci"}).text
    ck("the queue renders its bulk bar", 'id="bulk"' in html)
    ck("  with a checkbox per card bound to it",
       'name="claim_ids"' in html and 'form="bulk"' in html)
    ck("  and the entity list is searchable by name",
       "— Aqua Dinner Plate" in html)

    installer()
    connecting()

    print()
    if _fails:
        print(f"{len(_fails)} FAILED:")
        for f in _fails:
            print(f"  - {f}")
        return 1
    print("all green")
    return 0




def installer() -> int:
    """The Systems installer: per account, with prerequisites shown before you
    commit. It used to be two blind dropdowns — every system whether or not it
    was installed, and nothing about what any of them needed."""
    from app import systems

    print("\n— installing a system, with its prerequisites visible —")
    rows = systems.installable("baci")
    ck("the whole catalogue is offered for one account",
       len(rows) == len(systems.CATALOG), f"{len(rows)} of {len(systems.CATALOG)}")
    ck("  what can be switched on now comes first",
       [r["ready"] for r in rows if not r["installed"]][:1] == [True],
       str([(r["key"], r["ready"]) for r in rows[:3]]))

    # This fixture wires no store, so the ready one is the compliance system
    # that needs nothing but the ban list — DEFECTS section 3's "cheapest
    # system to switch on was gated like the most expensive one".
    comp = next(r for r in rows if r["key"] == "content_compliance")
    ck("a system needing only the ban list reads as ready",
       comp["ready"], str(comp["missing"]))
    cat = next(r for r in rows if r["key"] == "catalog_compliance")
    ck("  and one needing a store it does not have does not",
       not cat["ready"]
       and any(i["name"] == "commerce" for i in cat["missing"]),
       str([i["name"] for i in cat["missing"]]))

    camp = next(r for r in rows if r["key"] == "campaign_email")
    ck("campaign_email is blocked, and says by what", not camp["ready"])
    # Both kinds must be distinguishable somewhere in the list: a missing
    # connection is a credential to go and wire, a missing knowledge field is
    # something to go and write, and one sentence lumping them together is what
    # made the old dropdown a guess.
    kinds = {i["kind"] for r in rows for i in r["missing"]}
    ck("  a missing CONNECTION and a missing KNOWLEDGE field are told apart",
       kinds == {"connection", "knowledge"}, str(kinds))
    ck("  esp is named as the missing connection",
       any(i["name"] == "esp" for i in camp["missing"]),
       str([i["name"] for i in camp["missing"]]))

    ck("the contract is NOT a prerequisite to install — it is one to go live",
       all(i["kind"] in ("connection", "knowledge")
           for r in rows for i in r["items"]))

    systems.create("baci", "content_compliance")
    after = {r["key"]: r for r in systems.installable("baci")}
    ck("an installed system reads as installed, not as available again",
       after["content_compliance"]["installed"])
    ck("  and carries its id so the contract can be filled",
       bool(after["content_compliance"]["system_id"]))

    html = client.get("/admin/ui", params={"key": KEY, "tab": "systems",
                                           "tenant": "baci"}).text
    ck("the tab renders per account", 'tab=systems&amp;tenant=baci' in html
       or 'tab=systems&tenant=baci' in html)
    ck("  with a met and an unmet prerequisite chip",
       'class="pre yes"' in html and 'class="pre no"' in html)
    ck("  and an install link carrying the account",
       'system_add' in html and 'tenant=baci' in html)
    return 0




def connecting() -> int:
    """Connecting an account from the console.

    Every API-key provider used to say "client pastes this on their connect
    link" — so the owner could not connect their own Shopify without minting a
    client link, or hand-editing a JSON blob in the Render environment.
    """
    from app import credentials as cred

    print("\n— connecting an account from the console —")
    html = client.get("/admin/ui", params={"key": KEY, "tab": "accounts"}).text
    ck("no provider tells the owner to go and use a client link",
       "client pastes" not in html)

    keyed = [p for p, s in cred.PROVIDERS.items() if s["kind"] == "api_key"]
    ck(f"all {len(keyed)} API-key providers have a form",
       all(f'value="{p}"' in html for p in keyed), str(keyed))
    ck("  each asks for its own named field, not a generic 'key'",
       "Admin API access token" in html and "Application password" in html)
    ck("  and carries that provider's own instructions",
       "Settings → Apps and sales channels" in html)
    ck("  the extra fields a provider needs are separate inputs, so nobody "
       "composes JSON by hand",
       'name="domain"' in html and 'name="site"' in html
       and 'name="username"' in html)
    ck("OAuth says what is missing AND the redirect URI to register",
       "not set in the env group" in html and "/oauth/google/callback" in html)

    r = client.post("/admin/connect_save", params={"key": KEY},
                    data={"tenant": "baci", "provider": "shopify",
                          "secret": "not-a-real-token", "domain": "x.myshopify.com"},
                    follow_redirects=False)
    loc = r.headers.get("location", "")
    ck("a key that fails its own format check is refused before saving",
       "err=" in loc and "shpat_" in loc.replace("%5F", "_"), loc[:120])
    ck("  and nothing was stored",
       not any(s["state"] == "connected" and s["provider"] == "shopify"
               for s in cred.status("baci")),
       str([(s["provider"], s["state"]) for s in cred.status("baci")]))

    r = client.post("/admin/connect_save", params={"key": KEY},
                    data={"tenant": "baci", "provider": "shopify",
                          "secret": "shpat_looksrightbutisnot"},
                    follow_redirects=False)
    ck("a missing required field is named, not swallowed",
       "err=" in r.headers.get("location", ""),
       r.headers.get("location", "")[:120])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
