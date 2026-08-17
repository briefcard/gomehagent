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

import inspect
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'hv.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import compliance, db, extract, harvest, kb, kb_seed, tenants  # noqa: E402

# This suite must never touch the network, and that includes the model. Without
# this a developer who happens to have ANTHROPIC_API_KEY set would make a live
# call per page here — slow, billable, and non-deterministic in a suite whose
# whole value is that it is none of those. The extractor has its own benchmark.
extract.available = lambda: False

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
    ck("they are marked proposed, and attributed to the crawl",
       all(c.review == "proposed" and c.origin == "crawl" for c in pending))
    # `add_claim`'s return used to go nowhere, so "proposed 40" and "wrote 40"
    # were the same number whether or not anything landed. Every proposal must
    # now be accounted for as filed, corroborated, or refused BY NAME.
    accounted = (r2["filed_count"] + r2["corroborated_count"]
                 + r2["write_refused_count"])
    ck("every attempted write is accounted for",
       accounted == r2["proposed_count"],
       f"{accounted} accounted vs {r2['proposed_count']} proposed")
    ck("and the count that landed is reported separately from the count mined",
       r2["filed_count"] == len(pending), f"filed={r2['filed_count']}")
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
    # Approval no longer refuses an untagged claim. The old rule rested on
    # "an untagged claim can never be selected", which `claims()` contradicts:
    # it filters on situation only when a caller asks for one, so untagged
    # proof is brand-wide proof. Approval now infers a situation where the
    # classifier is confident and files it brand-wide where it is not — and
    # says which happened, because a silent choice between those two is the
    # absence-collapsed-into-a-value pattern all over again.
    ck("an untagged claim CAN now be approved", "Approved" in msg, msg[:80])
    ck("and it says how the situations were settled",
       "inferred" in msg or "brand-wide proof" in msg, msg[:120])
    ck("it is no longer pending",
       not any(c.id == row.id for c in kb.pending_claims("baci")))
    ck("and it is selectable as brand-wide proof",
       any(c.id == row.id for c in kb.claims("baci")))
    tag = sorted(kb.situations("baci"))[0]
    ck("editing it still accepts a real tag",
       kb.update_claim(row.id, tags=[tag]) == "Saved.")
    ck("an invented tag is still refused",
       "Unknown tags" in kb.update_claim(row.id, tags=["not_a_real_tag"]))
    ck("and now it answers a situated query too",
       any(c.id == row.id for c in kb.claims("baci", situations=[tag])))

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
    ck("and land as proposed, not approved", bare_pending
       and all(c.review == "proposed" for c in bare_pending))
    ck("none of them is selectable", not kb.claims("bare"))
    # An account with no vocabulary is the case the old approve-time gate hurt
    # most: nothing could ever be tagged, so nothing could ever be approved,
    # so a brand-new client's own website could not seed its knowledge base.
    approved = kb.review_claim(bare_pending[0].id, approve=True)
    ck("an account with NO vocabulary can still approve its proof",
       "Approved" in approved, approved[:80])
    ck("and it lands as brand-wide, which is the honest description",
       "brand-wide proof" in approved, approved[:120])
    ck("and is now selectable", bool(kb.claims("bare")))

    # ---- every client ------------------------------------------------------
    print("\n— all accounts —")
    allr = harvest.harvest_all(limit=5)
    ck("every account is attempted", len(allr["accounts"]) >= 5,
       str(list(allr["accounts"])))
    ck("one failing site does not stop the rest",
       any("error" in v for v in allr["accounts"].values())
       or all("proposed_count" in v for v in allr["accounts"].values()))

    httpx.get = real
    # ---- the quality gate -------------------------------------------------
    # Everything below is verbatim from a real review queue, except the last
    # three, which are real claims that must survive. The gate is worth having
    # only if it keeps those.
    print("\n— the quality gate —")
    import html as _htmllib
    JUNK = [
        ("an entity-encoded heading",
         "Powerful Closures: Leaving a Lasting Impression Concluding your blog "
         "post isn&#8217;t just about wrapping things up &#8211; it&#8217;s "
         "your final opportunity to leave a strong impact."),
        ("a nav run", "Book a 25-min intro Start the intake Agentic Core SEO Fig."),
        ("blog meta", "Posted on March 3, 2026 by admin | 4 Comments"),
        ("WordPress' default page", "Sample Page This is an example page."),
        ("error copy", "404 Not Found. The page you requested does not exist."),
        ("a bare price", "$95.00"),
    ]
    for label, raw in JUNK:
        ck(f"dropped: {label}",
           bool(harvest._quality(_htmllib.unescape(raw))),
           harvest._quality(_htmllib.unescape(raw)))
    KEEP = [
        "Baci Milano tableware is stocked in 4 Four Seasons properties worldwide.",
        "We took a coaching company from $6M to $20M in 18 months.",
        "Our team has directed over $60M in ad spend across a decade.",
    ]
    for good in KEEP:
        ck(f"kept: {good[:44]}…", not harvest._quality(good),
           harvest._quality(good))

    # The root cause, pinned. `&#8217;` contains 8217, and "carries a number"
    # is the whole test for whether a sentence is checkable — so every curly
    # apostrophe on the page was manufacturing evidence.
    entity = "Concluding your post isn&#8217;t just about wrapping it up."
    ck("an un-decoded entity would have faked the number test",
       harvest._HAS_NUMBER.search(entity) is not None)
    ck("and decoding it removes the fake number",
       harvest._HAS_NUMBER.search(_htmllib.unescape(entity)) is None)

    # ---- page selection ---------------------------------------------------
    print("\n— pages not worth reading —")
    for url in ("https://x.com/sample-page", "https://x.com/tag/gifts",
                "https://x.com/author/admin", "https://x.com/page/4",
                "https://x.com/404", "https://x.com/cart"):
        ck(f"skipped {url.split('.com')[1]}", compliance.skip_url(url))
    ck("a real page is not skipped", not compliance.skip_url("https://x.com/about"))
    ck("a 200 that is really a 404 is caught by its title",
       "error or placeholder" in compliance.is_dead_page(
           "<title>404 – Page Not Found</title><body>" + "x" * 500 + "</body>"))
    ck("a page with reviews but little prose is still read",
       not compliance.is_dead_page("<title>Aqua</title><body>Six pieces.</body>",
                                   min_chars=0))

    # ---- furniture and entities ------------------------------------------
    print("\n— what _clean returns —")
    page = ("<html><head><title>About</title></head><body>"
            "<nav>Home Shop Book a 25-min intro</nav>"
            "<main><p>Concluding isn&#8217;t the end &#8211; we shipped 1,200 "
            "orders in 2025.</p></main>"
            "<footer>&copy; 2026 All rights reserved</footer></body></html>")
    text = compliance._clean(page)
    ck("nav is dropped", "Book a 25-min intro" not in text)
    ck("footer is dropped", "All rights reserved" not in text)
    ck("entities are decoded", "’" in text and "&#8217;" not in text)
    ck("the actual copy survives", "we shipped 1,200 orders in 2025" in text.lower())

    print("\n— the crawl walks the site instead of restarting it —")
    from app import harvest as _hv
    _hv.forget_pages("baci")
    ck("a fresh account has read nothing", not _hv._page_state("baci"))

    first = harvest.harvest("baci", limit=2, apply=True)
    ck("a run reads pages", first["pages_read"] > 0, str(first["pages_read"]))
    ck("and remembers them", len(_hv._page_state("baci")) == first["pages_read"])

    first_urls = set(_hv._page_state("baci"))
    again = harvest.harvest("baci", limit=2, apply=True)
    second_urls = set(_hv._page_state("baci"))
    # The property that matters: run 2 covers ground run 1 did not. It should
    # NOT report unchanged pages — spending the budget on new pages first is
    # the point; unchanged only shows once new ground runs out.
    ck("a second run reads pages the first one did not",
       second_urls > first_urls,
       "the same first N pages were read again — the bug this exists to fix")
    ck("and says how much of the site is left",
       "pages_remaining" in again, str(sorted(again)[:6]))

    # With a budget big enough to exhaust the new pages, it re-encounters the
    # read ones and skips them on their content hash rather than re-reading.
    # The requirement in one assertion: nothing is read twice. Capture when
    # each known page was read, run again, and confirm those timestamps did
    # not move — a re-read would refresh them.
    from app import db as _db
    def _read_times():
        with _db.SessionLocal() as s:
            return {r.url: r.read_at for r in s.query(_db.HarvestedPage)
                    .filter(_db.HarvestedPage.tenant == "baci").all()}

    before_times = _read_times()
    wide = harvest.harvest("baci", limit=20, apply=True)
    after_times = _read_times()
    ck("no already-read page is read a second time",
       all(after_times[u] == ts for u, ts in before_times.items()),
       "a page was re-read — the run is repeating work, not advancing")
    ck("and the run advanced onto new pages",
       len(after_times) > len(before_times),
       f"{len(before_times)} -> {len(after_times)}")
    ck("discovery reaches the whole site, not a 90-page slice",
       wide["pages_discovered"] > 200, str(wide["pages_discovered"]))
    ck("and the report says how much is left to cover",
       wide["pages_remaining"] > 0, str(wide["pages_remaining"]))

    # A rehearsal must consume nothing — recording during a dry run was the
    # obvious optimisation and it silently starves the apply that follows.
    _hv.forget_pages("baci")
    harvest.harvest("baci", limit=2, apply=False)
    ck("a rehearsal consumes no page budget", not _hv._page_state("baci"),
       "the apply after a rehearsal would skip the page and file nothing")

    ck("recrawl ignores the memory",
       harvest.harvest("baci", limit=2, apply=False,
                       recrawl=True)["pages_read"] > 0)

    print("\n— a thin queue must say WHY it is thin —")
    check_known_drops_are_counted(ck)

    print()
    if _fail:
        print(f"{len(_fail)} FAILED:")
        for f in _fail:
            print(f"  - {f}")
        return 1
    print("all checks passed")
    return 0



def check_known_drops_are_counted(ck):
    """A thin queue must be readable as "we already have this", not as silence.

    A live Baci crawl returned 5 proposals. The cause was not the site: the
    account had never been purged, so its existing claims populated `known`
    and every repeat was dropped by `if fp in known: continue` — with no
    counter. `dropped_by_reason` named every other rejection and said nothing
    about the one doing all the work, so the run read as "the site says little
    that is checkable" when it meant "we have all of this already".
    """
    from app import harvest as hv, kb, provenance as prov

    src = inspect.getsource(hv.harvest)
    ck("the already-on-file branch increments a counter",
       "already on file" in src,
       "a silent `continue` here is indistinguishable from a thin site")
    ck("and the counter rides in the reported drop reasons",
       "dropped_by_reason" in src)

    # The dedupe key is the fingerprint, so the reflow fix must not split one
    # fact into two — a stored source-form claim and a re-crawled one have to
    # collide.
    ck("a reflowed claim still fingerprints as the same fact",
       prov.fingerprint("Designed in Milan\n  since 1993.")
       == prov.fingerprint("Designed in Milan since 1993."))


if __name__ == "__main__":
    raise SystemExit(main())