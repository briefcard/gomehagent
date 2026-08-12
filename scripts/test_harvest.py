"""What a site says becomes a proposal, never a fact.

The material to fill the knowledge base is sitting on the clients' websites and
the temptation is to scrape it in. The reason not to: a brand's own copy is
where its banned phrases live, and clearing a blocklist is not the same as being
true. "Trusted by 500 restaurants" passes all 24 of Baci's rules and still has
nothing behind it.

So the invariants worth locking down are all refusals — what must NOT end up in
the knowledge base, and what must not become selectable without a human.

    python3 scripts/test_harvest.py
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'hv.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, harvest, kb, kb_seed, tenants  # noqa: E402

_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


SITEMAP = """<?xml version="1.0"?><urlset>
  <url><loc>https://bacimilanousa.com/pages/about</loc></url>
  <url><loc>https://bacimilanousa.com/products/aqua</loc></url>
</urlset>"""

ABOUT = """<html><body>
<p>Baci Milano tableware is stocked in 4 Four Seasons properties worldwide.</p>
<p>All 6 pieces are handmade in Italy by our artisans.</p>
<p>Free shipping on orders over $95.</p>
<p>We think colour belongs on the table.</p>
<p>Subscribe to our newsletter for 10% off your first order.</p>
</body></html>"""

# Real JSON-LD, on one line per block — a literal newline inside a JSON string
# is invalid and json.loads rejects the whole block.
AQUA = """<html><body>
<script type="application/ld+json">
{"@type":"Review","reviewBody":"I bought this as a gift for a housewarming and the colours are even better in person.","author":{"name":"Marta R."},"reviewRating":{"ratingValue":5}}
</script>
<script type="application/ld+json">
{"@type":"Review","reviewBody":"Quality you can feel, and it is well made in Italy which is why I keep buying it.","author":{"name":"Dana"},"reviewRating":{"ratingValue":5}}
</script>
<p>The Aqua set. Six pieces.</p>
</body></html>"""


class _Resp:
    def __init__(self, text, code=200):
        self.text, self.status_code = text, code


def _get(url, **kw):
    if url.endswith("/sitemap.xml"):
        return _Resp(SITEMAP)
    if url.endswith("/pages/about"):
        return _Resp(ABOUT)
    if url.endswith("/products/aqua"):
        return _Resp(AQUA)
    return _Resp("", 404)


def main() -> int:
    db.init_db()
    tenants.seed()
    kb_seed.seed_all()

    import httpx
    real = httpx.get
    httpx.get = _get

    # Give baci a vocabulary hit these candidates can match.
    kb.add_situation("baci", "gift_moment", [["gift"], ["housewarming"]],
                     "buying for someone else")
    kb.add_situation("baci", "quality_doubt", [["quality"], ["four", "seasons"]],
                     "wants proof it is good")

    # ---- the dry run ------------------------------------------------------
    print("— reading the site —")
    r = harvest.harvest("baci", limit=10)
    ck("it read the pages", r["pages_read"] == 2, str(r.get("pages_read")))
    ck("and wrote nothing", not r["applied"] and not kb.pending_claims("baci"))

    texts = [p["text"] for p in r["proposed"]]

    # ---- the refusal that matters ----------------------------------------
    print("\n— banned phrases are dropped, not queued —")
    ck("nothing proposed uses a banned phrase",
       not any("handmade" in t.lower() or "made in italy" in t.lower()
               for t in texts), str(texts))
    rejected = " ".join(x["text"].lower() for x in r["rejected_for_banned_claim"])
    ck("the artisan line was rejected", "artisan" in rejected or "handmade" in rejected,
       str(r["rejected_for_banned_claim"])[:120])
    ck("and a REVIEW using a banned phrase is rejected too",
       not any("well made in italy" in t.lower() for t in texts),
       "a customer saying it does not make it sayable")
    ck("the rejection names the phrase",
       all(x["banned_phrase"] for x in r["rejected_for_banned_claim"]))

    # ---- what it did propose ----------------------------------------------
    print("\n— what it proposes —")
    ck("a checkable claim is proposed",
       any("Four Seasons" in t for t in texts), str(texts)[:140])
    ck("a clean review is proposed",
       any("housewarming" in t.lower() for t in texts))
    review = next((p for p in r["proposed"] if "housewarming" in p["text"].lower()), None)
    ck("a review carries testimonial provenance",
       review and review["proof_type"] == "testimonial"
       and "Marta" in review["evidence"], str(review)[:120] if review else "")
    ck("every proposal cites where it came from",
       all(p["source"] for p in r["proposed"]))
    ck("every proposal carries tags from the account's OWN vocabulary",
       all(p["tags"] and set(p["tags"]) <= set(kb.situations("baci"))
           for p in r["proposed"]),
       str([(p["text"][:24], p["tags"]) for p in r["proposed"]]))

    # ---- noise ------------------------------------------------------------
    print("\n— boilerplate is not a claim —")
    ck("free shipping is not proposed",
       not any("free shipping" in t.lower() for t in texts))
    ck("a newsletter discount is not proposed",
       not any("newsletter" in t.lower() for t in texts))
    ck("a sentence with no number is not proposed as data",
       not any("colour belongs on the table" in t.lower() for t in texts))

    # ---- untaggable is reported, never guessed ---------------------------
    print("\n— what it cannot tag —")
    ck("untaggable candidates are reported rather than stored",
       isinstance(r["found_but_untaggable"], list))

    # ---- applying ---------------------------------------------------------
    print("\n— filing them —")
    before_selectable = len(kb.claims("baci"))
    r2 = harvest.harvest("baci", limit=10, apply=True)
    pending = kb.pending_claims("baci")
    ck("proposals are filed", len(pending) == r2["proposed_count"] > 0,
       f"{len(pending)} pending")
    ck("and are NOT selectable", len(kb.claims("baci")) == before_selectable,
       "a crawl must not change what the generator may say")
    ck("they are marked pending", all(c.status == "pending" for c in pending))
    ck("approving one makes it selectable",
       "Approved" in kb.review_claim(pending[0].id, approve=True)
       and len(kb.claims("baci")) == before_selectable + 1)

    # ---- idempotent -------------------------------------------------------
    print("\n— running it again —")
    r3 = harvest.harvest("baci", limit=10, apply=True)
    ck("the same lines are not proposed twice", r3["proposed_count"] == 0,
       str(r3["proposed_count"]))

    # ---- an account with no vocabulary ------------------------------------
    print("\n— an account that cannot tag anything —")
    with db.SessionLocal() as s:
        s.add(db.Tenant(key="bare", name="Bare Co", domain="bacimilanousa.com"))
        s.commit()
    kb.ensure_brand("bare", "Bare Co")
    rb = harvest.harvest("bare", limit=10, apply=True)
    ck("nothing is filed without a vocabulary to tag against",
       rb["proposed_count"] == 0 and not kb.pending_claims("bare"))
    ck("but the candidates are reported so the gap is visible",
       rb["untaggable_count"] > 0, str(rb["untaggable_count"]))

    # ---- every client ------------------------------------------------------
    print("\n— all accounts —")
    allr = harvest.harvest_all(limit=5)
    ck("every account is attempted", len(allr["accounts"]) >= 5,
       str(list(allr["accounts"])))
    ck("one failing site does not stop the rest",
       any("error" in v for v in allr["accounts"].values())
       or all("proposed_count" in v for v in allr["accounts"].values()))

    httpx.get = real
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
