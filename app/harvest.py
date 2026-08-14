"""Gather claim candidates from a client's own site — as proposals, never facts.

The knowledge base is thin on every account and the material is sitting on their
websites. The temptation is to scrape it in. The reason not to is that a brand's
own marketing copy is where its banned phrases live, and passing a blocklist is
not the same as being true: "trusted by 500 restaurants" clears every one of
Baci's 24 rules and still has no evidence behind it.

`KbClaim` requires claim + evidence + proof_type + source. Scraped prose supplies
the first and none of the others. So nothing here is ever added as fact:

  * Candidates land as `status="pending"` — the same door client-submitted
    claims already use, invisible to selection until a human approves them.
  * Anything matching the account's `banned_claims` is dropped outright and
    never proposed. The brand banned it; a crawler does not get to reintroduce
    it through a review queue.
  * Situation tags come from matching the account's own `situation_patterns`.
    A candidate that matches none cannot be tagged, so it is REPORTED rather
    than stored with a guessed tag — `add_claim` refuses unknown tags and it is
    right to.

Reviews are the strongest source and the reason this is worth doing at all. A
review has real provenance: `proof_type="testimonial"`, a source that names
where it came from, and a claim phrased as what a customer said rather than what
the brand asserts about itself.
"""
from __future__ import annotations

import html as html_lib
import json
import re

from . import compliance, extract, kb, provenance as prov, tenants

_MIN, _MAX = 25, 240

# Boilerplate that appears on every page of every storefront. None of it is a
# claim, and all of it would otherwise pass a "contains a number" filter.
_NOISE = re.compile(
    r"free shipping|subscribe|newsletter|cookie|privacy|copyright|all rights"
    r"|add to cart|sold out|quantity|sign up|log in|©|terms of service"
    r"|returns? policy|use code|off your first"
    # Blog and CMS furniture. All of these arrived in a real review queue.
    r"|read more|continue reading|posted on|posted in|filed under|min read"
    r"|share this|leave a (comment|reply)|\d+ comments?|related posts?"
    r"|previous post|next post|older posts|newer posts|tagged with"
    r"|click here|learn more|skip to (content|main)|back to top"
    r"|all rights reserved|powered by|lorem ipsum|sample page"
    # Error-page prose. `skip_url` and the title check catch these first; this
    # is the third layer, because a site that serves its 404 copy inside a real
    # page defeats both of the others.
    r"|\b40[0-9]\b|not found|page you (requested|are looking for)"
    r"|does(n't| not) exist|try again later|temporarily unavailable", re.I)

# A claim worth proposing carries a number — that is what makes it checkable.
#
# It must be a number in the PROSE. Before `_clean` unescaped entities, every
# curly apostrophe reached this filter as `&#8217;` and matched, so ordinary
# blog copy looked checkable and filled the queue. The filter was working; it
# was being fed manufactured digits.
_HAS_NUMBER = re.compile(r"\d")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")

# A real sentence has a verb-ish word in it. Headings and menu runs do not.
#
# The irregular list is not padding. `\w+ed` covers "raised", "doubled",
# "recovered" — but the strongest claims a business makes open on an irregular
# past tense, and without these "Took a regional produce brand from $300k to
# $1M/year" (a real seeded agency claim) was dropped as a fragment.
_VERBISH = re.compile(
    r"\b(is|are|was|were|be|been|has|have|had|can|will|do|does|did"
    r"|took|take|built|build|ran|run|led|lead|grew|grow|sold|sell|made|make"
    r"|won|win|brought|bring|drove|drive|cut|kept|keep|held|hold|spent|spend"
    r"|got|went|began|broke|chose|drew|found|gave|left|lost|met|paid|put"
    r"|saw|sent|set|taught|told|wrote|knew|thought|rose|stands|serves"
    r"|\w+(?:s|ed|es))\b", re.I)


# A measurement, in any of the forms a spec table uses.
#
# No bare `m` or `l`, and never after a currency symbol: "$6M to $20M in 18
# months" read as two metre measurements and got a real revenue claim dropped
# as a spec table. Millions look exactly like metres, so the unit list has to
# be the ones a spec sheet actually uses.
_MEASURE = re.compile(
    r"(?<![$£€\d])\d+[\d.,]*\s*(?:cm|mm|ml|cl|kg|oz|lb|inch(?:es)?|in|g)\b",
    re.I)
# Spec-sheet vocabulary. These are field LABELS, not things a brand asserts.
_SPEC_LABEL = re.compile(
    r"\b(dimensions?|material|collection|care (?:&|and) use|specifications?"
    r"|frequently asked|weight|capacity|colou?r|finish|sku|ref\.?|model"
    r"|hand wash|dishwasher safe|microwave safe|indoor only|made of"
    r"|designed in|h\s*\d|w\s*\d|d\s*\d)\b", re.I)


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE.split(text or "") if s.strip()]


def _is_spec_run(s: str) -> bool:
    """A run of specification data rather than a sentence.

    Real examples that reached the queue, all of them one block in the markup
    and none of them a claim:

        "Ø 25 cm, h 14 cm Specifications Material Polyresin Dimensions
         Ø 25 cm; H 14 cm Collection Joke Care & use Hand wash recommended"
        "32 CM (32 CM) Is it dishwasher safe?"
        "Dedicated to cultural innovators … Ø 13 cm, H 5.5 cm"

    Two or more measurements, or a measurement sitting next to spec-sheet
    vocabulary, means this is a table someone flattened — not prose.
    """
    measures = len(_MEASURE.findall(s))
    if measures >= 2:
        return True
    labels = len(_SPEC_LABEL.findall(s))
    if measures and labels:
        return True
    return labels >= 2


def _looks_like_heading(s: str) -> bool:
    """Title Case with no terminal punctuation is a heading, not a claim.

    "Powerful Closures: Leaving a Lasting Impression" is a section title that
    got proposed as proof. Headings restate what the body already says, so
    dropping them costs nothing and clears a good share of the queue.
    """
    words = [w for w in s.split() if w[:1].isalpha()]
    if len(words) < 3:
        return True
    capped = sum(1 for w in words if w[:1].isupper())
    return capped / len(words) > 0.6 and not s.rstrip().endswith((".", "!", "?"))


def _quality(s: str) -> str:
    """Why this sentence is not worth proposing, or "" if it is.

    Deterministic, and it reports a reason rather than a verdict — the point of
    a filter that drops most of what it sees is that you can check what it
    dropped. A model deciding this would be a model deciding what counts as
    proof, which is the one judgement the review queue exists to keep human.
    """
    if not (_MIN <= len(s) <= _MAX):
        return "wrong length"
    if _NOISE.search(s):
        return "page furniture"
    if not _HAS_NUMBER.search(s):
        return "no number, so nothing to check"
    if _looks_like_heading(s):
        return "reads as a heading, not a sentence"
    if s.rstrip().endswith("?"):
        return "a question — an FAQ heading, not an assertion"
    if _is_spec_run(s):
        return "specification data, not a claim"
    # Catches the carousel run "Pitcher $135 Cake stand $195" as well as menu
    # fragments. A dedicated price-list rule was tried here and removed: two
    # currency figures in a sentence is far more often a real before-and-after
    # claim ("$6M to $20M", "$300k to $1M") than a price list, and it was
    # dropping the best proof the agency has.
    if not _VERBISH.search(s):
        return "no verb — a fragment or a menu run"
    letters = sum(c.isalpha() for c in s)
    if letters < len(s) * 0.5:
        return "mostly punctuation, digits or markup residue"
    # A price on its own, a date on its own, a phone number: real numbers that
    # are not evidence of anything.
    stripped = re.sub(r"[\d\s.,:$%/£€-]+", "", s)
    if len(stripped) < 12:
        return "a bare figure with no assertion around it"
    return ""


def _jsonld(html: str) -> list[dict]:
    """Every JSON-LD block on a page, flattened. Reviews live here.

    Review apps (Judge.me, Loox, Okendo, Yotpo) all emit structured data, so
    this is a real parse rather than a guess at markup — the difference between
    a testimonial with provenance and a sentence that looked like one.
    """
    out: list[dict] = []
    for block in re.findall(
            r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html or "",
            re.S | re.I):
        try:
            data = json.loads(block.strip())
        except Exception:  # noqa: BLE001 — malformed JSON-LD is common
            continue
        stack = [data]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, dict):
                out.append(item)
                stack.extend(v for v in item.values()
                             if isinstance(v, (dict, list)))
    return out


def _reviews_from(html: str, url: str) -> list[dict]:
    """Testimonials with attribution, from structured data only."""
    found = []
    for node in _jsonld(html):
        if str(node.get("@type", "")).lower() != "review":
            continue
        body = (node.get("reviewBody") or node.get("description") or "").strip()
        if not (_MIN <= len(body) <= _MAX * 3):
            continue
        author = node.get("author")
        if isinstance(author, dict):
            author = author.get("name", "")
        rating = node.get("reviewRating") or {}
        stars = rating.get("ratingValue") if isinstance(rating, dict) else ""
        found.append({
            "text": body[:_MAX * 3],
            "evidence": (f"{stars}-star review" if stars else "customer review")
                        + (f" from {author}" if author else ""),
            "proof_type": "testimonial",
            "source": f"review on {url}",
        })
    return found


def _faqs_from(html: str, url: str) -> list[dict]:
    """Question-and-answer pairs, from FAQPage structured data only.

    This is the highest-value thing on a product page and it was being thrown
    away twice over — first flattened into prose (`"32 CM (32 CM) Is it
    dishwasher safe?"`), then dropped as junk.

    An FAQ entry is *exactly* the shape of a `KbObjection`: a reason someone
    hesitates, and the answer the brand has already approved. Objections are
    zero on all five accounts and have been described throughout this codebase
    as human-authored and underivable. That is true of brand-level objections.
    It is not true of a product FAQ, which the brand has already written and
    published — so this is the one place they can be derived, and the reason
    they must carry an entity is that the answer is only correct about that
    product.

    Structured data only, exactly as reviews are read: Baci's PDP template
    emits FAQPage JSON-LD, and guessing at accordion markup would put invented
    pairings in front of a reviewer.
    """
    out = []
    for node in _jsonld(html):
        if str(node.get("@type", "")).lower() != "question":
            continue
        q = (node.get("name") or node.get("text") or "").strip()
        ans = node.get("acceptedAnswer") or node.get("suggestedAnswer") or {}
        if isinstance(ans, list):
            ans = ans[0] if ans else {}
        a = (ans.get("text") if isinstance(ans, dict) else "") or ""
        a = re.sub(r"<[^>]+>", " ", a)
        a = " ".join(html_lib.unescape(a).split())
        if len(q) < 8 or len(a) < 8:
            continue
        out.append({"question": q[:300], "answer": a[:900],
                    "source": f"FAQ on {url}"})
    return out


def _claims_from(text: str, url: str,
                 dropped: dict | None = None) -> list[dict]:
    """Sentences that assert something checkable — i.e. that carry a number."""
    out = []
    for s in _sentences(text):
        why = _quality(s)
        if why:
            if dropped is not None:
                dropped[why] = dropped.get(why, 0) + 1
            continue
        out.append({"text": s, "evidence": "", "proof_type": "data",
                    "source": f"stated on {url}"})
    return out


def _tags_for(tenant: str, text: str) -> list[str]:
    """Situation tags this text matches, from the account's OWN vocabulary."""
    low = (text or "").lower()
    hits = []
    for tag, patterns in kb.situation_patterns(tenant).items():
        for pat in patterns:
            if all(str(word).lower() in low for word in pat):
                hits.append(tag)
                break
    return hits


def harvest(tenant: str, limit: int = 25, apply: bool = False,
            use_model: bool | None = None) -> dict:
    """Read a client's site and propose what it finds. Writes nothing unless
    `apply` is set, and even then only as pending claims."""
    t = tenants.get(tenant)
    if not t:
        return {"error": f"unknown tenant {tenant!r}"}
    if not t.domain:
        return {"error": f"{tenant} has no domain recorded"}

    banned = [b.lower() for b in kb.banned_claims(tenant) if b]
    vocab = kb.situation_patterns(tenant)
    pages, source = compliance.discover_pages(t.domain, limit=max(limit * 3, 90))
    if not pages:
        return {"error": f"could not enumerate any pages at {t.domain}"}

    # Claims already on file, so a repeat run does not re-propose the same line.
    # Matched on the shared normalised fingerprint rather than a lowercased
    # string: a re-crawl after someone fixed a typo, or the same sentence with
    # different punctuation, is the same claim and must not queue twice.
    known = {prov.fingerprint(c.claim)
             for c in kb.claims(tenant) + kb.pending_claims(tenant)}

    proposed, rejected, untaggable, faqs = [], [], [], []
    not_verbatim: list[str] = []          # spans the model returned that the
                                          # page does not actually contain
    used_model = False
    extractor_note = ""
    model_on = extract.available() if use_model is None else use_model
    dropped: dict[str, int] = {}          # why candidates were not proposed
    skipped: list[dict] = []              # pages not worth reading, and why

    # Pages the catalogue already owns, by handle. A product page crawled off
    # the storefront is a strictly worse copy of what the Shopify API serves
    # properly — the same prose, plus the spec table, the FAQ accordion and the
    # related-items carousel, with no structure to tell them apart. That is
    # where every incoherent proposal came from, and it is redundant besides:
    # `catalog_sync` already imported the description, the price and the stock.
    owned = {e.key for e in kb.entities(tenant, available_only=False)}

    # --- pass 1: read the pages, keep candidates, write nothing -----------
    # Two passes because boilerplate can only be recognised by looking across
    # pages. A sentence is furniture not because of what it says but because it
    # says it on every page, and that is not visible one page at a time.
    import httpx
    per_page: list[tuple[str, list[dict]]] = []
    for p in pages[:limit]:
        url = p["url"]
        if compliance.skip_url(url):
            skipped.append({"url": url, "why": "not brand copy"})
            continue
        # A product page is not skipped and not flattened. What it holds is
        # true OF that product, so it is harvested against the entity the
        # catalogue already knows — which is what makes the FAQ and the copy
        # usable instead of nonsense.
        handle = url.rstrip("/").rsplit("/", 1)[-1].lower()
        entity = handle if ("/products/" in url.lower() and handle in owned) else ""
        html = p.get("html", "")
        if not html:
            try:
                r = httpx.get(url, timeout=25, follow_redirects=True,
                              headers=compliance.HEADERS)
                if r.status_code != 200:
                    skipped.append({"url": url, "why": f"HTTP {r.status_code}"})
                    continue
                html = r.text
            except Exception as exc:  # noqa: BLE001
                skipped.append({"url": url, "why": exc.__class__.__name__})
                continue
        # One string per block, never one string for the page. Sentences are
        # only split WITHIN a block, so a spec cell and the FAQ heading beside
        # it can never become one candidate.
        blocks = compliance.text_blocks(html)
        text = " ".join(blocks)
        # Reviews are read BEFORE the page is judged. A product page carries
        # its testimonials in JSON-LD and often has almost no prose — judging
        # it on prose length would throw away the strongest source there is.
        reviews = _reviews_from(html, url)
        # A page served 200 with an error title, or with no prose and no
        # structured data, has no claim on it. Plenty of themes return 200 for
        # a missing page, which is why the title is checked at all.
        dead = compliance.is_dead_page(html, text,
                                       min_chars=0 if reviews else 200)
        if dead:
            skipped.append({"url": url, "why": dead})
            continue
        cands = [{**r, "entity_key": entity} for r in reviews]
        if model_on:
            # The model judges what is a claim; every guard below still runs.
            res = extract.extract(tenant, url, blocks, entity_key=entity)
            used_model = used_model or res["used"] == "model"
            if res["used"] == "model":
                cands += res["claims"]
                not_verbatim += res["rejected_not_verbatim"]
            else:
                extractor_note = res.get("note") or res.get("error") or res["used"]
                for block in blocks:
                    cands += [{**c, "entity_key": entity}
                              for c in _claims_from(block, url, dropped)]
        else:
            # The deterministic floor. Known 0% recall on qualitative claims —
            # kept as the offline path, not as the judge.
            for block in blocks:
                cands += [{**c, "entity_key": entity}
                          for c in _claims_from(block, url, dropped)]
        per_page.append((url, cands))
        for f in _faqs_from(html, url):
            faqs.append({**f, "entity_key": entity, "url": url})

    # --- how often does each candidate appear across the site? ------------
    seen_on: dict[str, int] = {}
    for _, cands in per_page:
        for fp in {prov.fingerprint(c["text"]) for c in cands}:
            seen_on[fp] = seen_on.get(fp, 0) + 1
    n_pages = max(len(per_page), 1)
    # A third of the site saying the same sentence is a template, not a claim.
    # Computed per site, so it needs no hand-maintained list and works for a
    # storefront, a blog and a venue site alike — the same document-frequency
    # trick `kb.match_entities` uses to discount uninformative words.
    boilerplate = {fp for fp, n in seen_on.items()
                   if n_pages >= 4 and n > 0.33 * n_pages}

    # --- pass 2: propose what survived ------------------------------------
    for url, cands in per_page:
        for cand in cands:
            body = cand["text"].strip()
            low = body.lower()
            fp = prov.fingerprint(body)
            if fp in known:
                continue
            if fp in boilerplate:
                dropped["appears site-wide — a template, not a claim"] = \
                    dropped.get("appears site-wide — a template, not a claim", 0) + 1
                known.add(fp)
                continue
            hit = next((b for b in banned if b in low), "")
            if hit:
                # The brand banned this phrase. A crawler does not get to
                # reintroduce it through a review queue.
                rejected.append({"text": body[:160], "banned_phrase": hit,
                                 "url": url})
                continue
            # Every candidate is proposed WITH its best-guess tags, and an
            # untaggable one is proposed untagged rather than discarded — the
            # segmentation happens when a human approves it, which is the only
            # point at which anyone actually knows the answer.
            # The model tagged this while it could still see the page it came
            # off. `suggest_tags` only sees the sentence, so it is the fallback
            # now rather than the decision — it was never able to get from
            # "trained across 30+ seminars" to "credibility", and on an account
            # whose situation patterns were never authored it returned nothing
            # at all, for everything.
            guess = kb.suggest_tags(tenant, body,
                                    entity_key=cand.get("entity_key", ""))
            tags = [s for s in (cand.get("situations") or []) if s] or guess["tags"]
            if not tags:
                untaggable.append({"text": body[:160], "url": url})
            known.add(fp)
            entry = {**cand, "text": body, "tags": tags,
                     "tag_basis": ("model, at extraction"
                                   if cand.get("situations") else guess["basis"]),
                     "similar_to_rejected": guess["similar_to_rejected"]}
            proposed.append(entry)
            if apply:
                kb.add_claim(tenant, body, cand["evidence"], tags,
                             proof_type=cand["proof_type"],
                             source=cand["source"], status="pending",
                             origin="crawl",
                             entity_key=cand.get("entity_key", ""),
                             proves=cand.get("proves", ""),
                             context=cand.get("context", ""))

    # A tag the model reached for and could not find is the account telling us
    # its vocabulary is short. Filed as a PROPOSAL like everything else — it is
    # a machine's opinion about how this brand talks, and that is exactly the
    # kind of thing a human signs off.
    wanted = sorted({c["needs_situation"] for _u, cs in per_page for c in cs
                     if c.get("needs_situation")})
    filed_situations, covered_already = [], []
    if apply:
        for tag in wanted:
            if tag in kb.situations(tenant, include_proposed=True):
                continue
            near = kb.similar_situation(tenant, tag)
            if near:
                # Already expressible. Recorded so a run that keeps reaching
                # for the same missing idea is visible, without the vocabulary
                # growing a synonym for it.
                covered_already.append(f"{tag} -> {near}")
                continue
            if len(filed_situations) >= kb.MAX_NEW_SITUATIONS:
                # Past this, the shortfall is the vocabulary, not the site.
                # Filing fifteen tags nobody chose is how a controlled list
                # stops being controlled.
                break
            msg = kb.add_situation(tenant, tag, patterns=[], origin="crawl",
                                   source="proposed while reading the site")
            if msg.startswith(("Added", "Updated")):
                filed_situations.append(tag)

    filed_faqs = 0
    if apply:
        for f in faqs:
            msg = kb.add_objection(tenant, f["question"], f["answer"],
                                   origin="crawl", source=f["source"],
                                   entity_key=f["entity_key"])
            if msg.startswith("Added"):
                filed_faqs += 1

    return {
        "tenant": tenant, "domain": t.domain, "applied": apply,
        # Three different things used to report as "deterministic filter": the
        # key being absent, every page having nothing worth sending, and the
        # API failing mid-crawl. Only the first is a configuration problem, and
        # telling them apart is the difference between "set an env var" and
        # "the crawler read nothing".
        "extractor": ("model" if used_model
                      else ("deterministic filter" if extract.available()
                            else "deterministic filter (no ANTHROPIC_API_KEY)")),
        "extractor_note": extractor_note,
        "rejected_not_verbatim": not_verbatim[:10],
        "not_verbatim_count": len(not_verbatim),
        "situations_wanted": wanted,
        "situations_proposed": filed_situations,
        "situations_already_covered": covered_already,
        "situations_capped": (
            f"stopped after {kb.MAX_NEW_SITUATIONS}; {len(wanted)} were wanted "
            f"— review the vocabulary rather than adding more"
            if len(filed_situations) >= kb.MAX_NEW_SITUATIONS else ""),
        "faqs_found": len(faqs),
        "faqs_filed_as_objections": filed_faqs,
        "faqs": [{"q": f["question"][:90], "entity": f["entity_key"] or "(brand)"}
                 for f in faqs[:12]],
        "page_source": source,
        "pages_enumerated": len(pages),
        "pages_read": len(per_page),
        "pages_skipped": len(skipped),
        "skipped_examples": skipped[:10],
        "vocabulary_tags": len(vocab),
        "proposed": proposed,
        "proposed_count": len(proposed),
        # What the quality gate threw away, and why. A filter that drops most
        # of what it sees has to be auditable, or the next person to look at a
        # thin queue cannot tell a clean site from a broken crawler.
        "dropped_by_reason": dict(sorted(dropped.items(), key=lambda kv: -kv[1])),
        "rejected_for_banned_claim": rejected,
        "proposed_without_tags": untaggable[:15],
        "untagged_count": len(untaggable),
        "note": ("Proposals land as PENDING claims — invisible to selection "
                 "until approved at /admin/ui?tab=content. Anything using a "
                 "banned phrase was dropped, not queued. Candidates the tagger "
                 "could not place are proposed untagged — approval refuses "
                 "until a tag is chosen, so they are segmented by a human "
                 "rather than guessed at or thrown away. `dropped_by_reason` "
                 "and `skipped_examples` say what the crawl chose not to show "
                 "you, so a thin queue can be told apart from a broken read."),
    }


def harvest_all(limit: int = 25, apply: bool = False) -> dict:
    """Every active account. One failing site must not stop the rest."""
    out = {}
    for t in tenants.all_tenants(include_paused=False):
        try:
            out[t.key] = harvest(t.key, limit=limit, apply=apply)
        except Exception as exc:  # noqa: BLE001
            out[t.key] = {"error": f"{exc.__class__.__name__}: {str(exc)[:160]}"}
    return {"accounts": out, "applied": apply}
