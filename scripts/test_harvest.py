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
    ck("tags, where present, come from the account's OWN vocabulary",
       all(set(p["tags"]) <= set(kb.situations("baci")) for p in r["proposed"]),
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
    ck("candidates it cannot tag are still proposed, not discarded",
       isinstance(r["proposed_without_tags"], list))
    ck("and they are counted", isinstance(r["untagged_count"], int))
    ck("every proposal carries the basis for its tags",
       all("tag_basis" in p for p in r["proposed"]))

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

    # ---- segmentation happens at approval, not at capture -----------------
    print("\n— an untagged proposal is segmented by a human —")
    untagged = kb.add_claim("baci", "A claim no pattern will ever match here.",
                            "some number", [], proof_type="data",
                            source="test", status="pending")
    ck("an untagged claim CAN be proposed", "review" in untagged.lower(), untagged[:60])
    row = [c for c in kb.pending_claims("baci")
           if c.claim.startswith("A claim no pattern")][0]
    msg = kb.review_claim(row.id, approve=True)
    ck("but CANNOT be approved untagged", "tag before approving" in msg, msg[:70])
    ck("and stays pending", kb.pending_claims("baci") and any(
        c.id == row.id for c in kb.pending_claims("baci")))
    tag = sorted(kb.situations("baci"))[0]
    ck("editing it accepts a real tag",
       kb.update_claim(row.id, tags=[tag]) == "Saved.")
    ck("an invented tag is refused",
       "Unknown tags" in kb.update_claim(row.id, tags=["not_a_real_tag"]))
    ck("now it approves", "Approved" in kb.review_claim(row.id, approve=True))
    ck("and is selectable", any(c.id == row.id for c in kb.claims("baci")))

    # ---- the tagger learns from what was approved -------------------------
    print("\n— the tagger learns —")
    g = kb.suggest_tags("baci", "A claim no pattern will ever match, 5 of them.")
    ck("a candidate resembling an approved claim inherits its tag",
       tag in g["tags"], f"{g['tags']} via {g['basis'][:40]}")
    ck("and says that is why", "resembles approved" in g["basis"] or
       g["basis"] == "pattern", g["basis"][:50])

    # ---- a customer's words are not the brand's ---------------------------
    # A review reworded as brand copy is a fabrication however true the
    # sentiment was: "the colours are better in person" said BY the brand is an
    # unevidenced claim, and said as a quote from a named customer it is a fact
    # about what someone said.
    print("\n— a testimonial may be quoted, not rewritten —")
    t_row = next((c for c in kb.pending_claims("baci") + kb.claims("baci")
                  if c.proof_type == "testimonial"), None)
    if t_row is None:
        kb.add_claim("baci", "The colours are better in person, genuinely.",
                     "5-star review from Dana", ["gifting"],
                     proof_type="testimonial", source="review on /x",
                     status="pending")
        t_row = next(c for c in kb.pending_claims("baci")
                     if c.proof_type == "testimonial")
    original = t_row.claim
    msg = kb.update_claim(t_row.id, claim="Our colours are better in person.")
    ck("rewording a testimonial is refused", "do not rewrite" in msg, msg[:70])
    ck("and the original survives untouched",
       next(c for c in kb.pending_claims("baci") + kb.claims("baci")
            if c.id == t_row.id).claim == original)
    ck("its tags can still be corrected",
       kb.update_claim(t_row.id, tags=["gifting"]) == "Saved.")
    ck("and its attribution can still be fixed",
       kb.update_claim(t_row.id, evidence="5-star review from Dana R.") == "Saved.")

    ck("a data claim CAN be reworded",
       kb.update_claim(
           next(c.id for c in kb.claims("baci") if c.proof_type == "data"),
           claim="Stocked in 4 Four Seasons properties.") == "Saved.")

    ck("every proof type states how it may be used",
       all(kb.usage_rule(t) for t in
           ("testimonial", "case_study", "data", "certification", "spec")))
    ck("the testimonial rule says quote, not paraphrase",
       "verbatim" in kb.usage_rule("testimonial").lower()
       and "never paraphrase" in kb.usage_rule("testimonial").lower())

    # ---- an account with no vocabulary ------------------------------------
    print("\n— an account that cannot tag anything —")
    with db.SessionLocal() as s:
        s.add(db.Tenant(key="bare", name="Bare Co", domain="bacimilanousa.com"))
        s.commit()
    kb.ensure_brand("bare", "Bare Co")
    rb = harvest.harvest("bare", limit=10, apply=True)
    # The old behaviour discarded these. Proposing them untagged is the point:
    # a brand-new account has no vocabulary yet, and its site is exactly where
    # the vocabulary should come from — so the candidates wait for a human
    # instead of being thrown away for want of a tag nobody has written.
    ck("candidates are still proposed for an account with no vocabulary",
       rb["proposed_count"] > 0, str(rb["proposed_count"]))
    ck("they are filed untagged", rb["untagged_count"] > 0,
       str(rb["untagged_count"]))
    bare_pending = kb.pending_claims("bare")
    ck("and land as pending, not active", bare_pending
       and all(c.status == "pending" for c in bare_pending))
    ck("none of them is selectable", not kb.claims("bare"))
    ck("and none can be approved until it is tagged",
       "tag before approving" in kb.review_claim(bare_pending[0].id, approve=True))

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
