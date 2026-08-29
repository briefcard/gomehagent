"""What part of an output is confirmed by a claim — and what is not.

Owner, 2026-08-29, after an Eien Health article recommended glucosamine and
chondroitin (which Eien does not sell) and discussed knee pain:

    "I don't want to see it as 'never say glucosamine & chondroitin' because
     we may want to generate articles that point out the deficits in the
     competition, but how come it doesn't know that? … we should have a
     feature in our review of all assets — blogs, ads, emails — that shows
     what part of the output is confirmed by a claim."

WHY IT DID NOT KNOW, pinned below: `validator.check`'s citation rule is
`if require_citation and body.strip() and not ids` — are ANY claim_ids
attached. The blog attaches every claim the account owns to every article, so
it passes whatever the body says. Nothing verified CORRESPONDENCE.

    python3 scripts/test_claim_trace.py
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'ct.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import claim_trace, db, kb, kb_seed, tenants, validator  # noqa: E402

_fail: list[str] = []


def _esc_q(t: str) -> str:
    """The sentence as it appears inside the JSON payload."""
    import json as _j
    return _j.dumps(t)[1:-1].replace('&', '&amp;').replace(
        '"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')


def ck(label: str, cond, detail: str = "") -> None:
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


DOSE = {"id": "c2", "claim": "Each serving contains 1000mg of omega-3 fatty acids.",
        "evidence": "spec sheet"}
TEST = {"id": "c1", "claim": "Every batch is third-party tested in a US facility.",
        "evidence": "COA 2026"}


def main() -> int:
    db.init_db()
    tenants.seed()
    kb_seed.seed_all()

    print("— the gap this exists for: citation is PRESENCE, not correspondence —")
    kb.add_claim("eien", "Every batch is third-party tested in a US facility.",
                 "COA 2026", [], proof_type="certification", origin="human",
                 status="active")
    cid = kb.claims("eien")[0].id
    off_topic = ("<p>Glucosamine and chondroitin are the most studied "
                 "supplements for knee pain, and they rebuild cartilage.</p>")
    res = validator.check("eien", off_topic, claim_ids=[cid])
    ck("the validator passes an article about something else entirely",
       res.get("ok") is True,
       "attaching a true claim licenses any body — that is the defect")

    print("\n— and this reading catches it —")
    rep = claim_trace.annotate(off_topic, kb.claims("eien"))
    ck("the assertion is seen as an assertion", rep["assertions"] >= 1)
    ck("…and nothing stands behind it", rep["coverage_pct"] == 0,
       str(rep["coverage_pct"]))
    ck("…and it is named, so it can be acted on",
       any("glucosamine" in u.lower() for u in rep["unbacked_assertions"]),
       str(rep["unbacked_assertions"])[:90])

    print("\n— a dosage claim does NOT back an efficacy sentence —")
    # The first false positive this hit on the real article, and the worst
    # error available: a green mark on an unapproved health claim.
    eff = "Omega-3 fatty acids are widely researched for moderating inflammation."
    ck("research prose is not backed by a milligram figure",
       not claim_trace.annotate(eff, [DOSE])["sentences"][0]["backed"],
       "they share the ingredient and nothing else")
    ck("…while a sentence that states the dose IS backed",
       claim_trace.annotate("Each serving contains 1000mg of omega-3 fatty "
                            "acids.", [DOSE])["sentences"][0]["backed"])
    ck("a digit inside a name is not a quantity",
       claim_trace._FIGURE.findall("omega-3 and GLP-1") == [],
       "matching '3' out of 'omega-3' defeated the guard on its first run")
    ck("…but a real quantity still is",
       claim_trace._FIGURE.findall("contains 1000mg") == ["1000"])

    print("\n— three states, so the loud one stays loud —")
    mixed = ("You just stood up from your desk. "
             "Every batch is third-party tested in a US facility. "
             "Glucosamine rebuilds cartilage and is the most studied option.")
    r = claim_trace.annotate(mixed, [TEST])
    kinds = [("backed" if s["backed"] else
              "unbacked" if s["assertion"] else "prose") for s in r["sentences"]]
    ck("prose, backed and unbacked are told apart",
       kinds == ["prose", "backed", "unbacked"], str(kinds))
    ck("coverage counts ASSERTIONS, not prose",
       r["assertions"] == 2 and r["coverage_pct"] == 50, str(r["coverage_pct"]))
    ck("an output with no assertions is not scored 0%",
       claim_trace.annotate("You stood up from your desk.",
                            [TEST])["coverage_pct"] is None,
       "'nothing needed a claim' and '0% grounded' are different facts")
    ck("…and says so in words",
       "no claim was needed" in claim_trace.summary(
           claim_trace.annotate("You stood up from your desk.", [TEST])))

    print("\n— it under-credits rather than over-credits —")
    ck("one shared topic word is not a citation",
       not claim_trace.annotate("Testing matters.", [TEST])["sentences"][0]["backed"],
       "a topic is not support")
    ck("markup never reaches the reader as text",
       "<p>" not in claim_trace.plain_text("<p>hello</p>")
       and "hello" in claim_trace.plain_text("<p>hello</p>"))
    ck("a heading asserts as loudly as a paragraph and is read",
       claim_trace.annotate("<h2>Glucosamine rebuilds cartilage</h2>",
                            [TEST])["assertions"] == 1)

    print("\n— the review surface renders it for ANY artifact —")
    from app import admin_ui

    class Art:
        tenant = "eien"; body = off_topic; format = "cms_article"
        system_key = "blog"; output_id = "o1"

    card = admin_ui._grounding_card("eien", Art())
    ck("the workroom shows the card", bool(card))
    ck("…with the coverage on the head", "0% grounded" in card)
    ck("…marks the unbacked assertion", "nothing on file says this" in card)
    ck("…and says the fix is the CLAIM, not a ban",
       "correct or add the CLAIM" in card or "add the CLAIM" in card,
       "banning the word would stop competitor-deficit articles too")

    class Ad:
        tenant = "eien"; body = '{"variants":[{"text":"Rebuilds cartilage."}]}'
        format = "ad_batch"; system_key = "ad_creative"; output_id = "o2"

    ck("an ad batch is annotated on its variants, not its JSON",
       "variants" not in admin_ui._grounding_card("eien", Ad()),
       "annotating raw JSON would mark up field names")

    print("\n— a MENTION is allowed; only the RECOMMENDATION is flagged —")
    # The owner's constraint, and the reason this is not a ban-list entry:
    # "we may want to generate articles that point out the deficits in the
    # competition", which requires naming what the brand does not sell.
    vocab = claim_trace.vocabulary("eien")
    ck("the account's vocabulary is read from its whole knowledge base",
       len(vocab) > 3, str(len(vocab)))
    ck("recommending something never mentioned is flagged",
       "glucosamine" in claim_trace.off_catalogue(
           "Glucosamine and chondroitin remain the benchmark for joint support.",
           vocab))
    ck("…merely NAMING it is not — a competitor comparison must be possible",
       claim_trace.off_catalogue(
           "Some competitors lead with glucosamine and chondroitin.", vocab) == [],
       "banning the word would kill the comparison articles too")
    ck("the trigger word is not itself reported as unknown",
       "benchmark" not in claim_trace.off_catalogue(
           "Glucosamine remains the benchmark.", vocab),
       "noise makes the real entries harder to see")
    ck("our own claim's words are known",
       claim_trace.off_catalogue(
           "Look for third-party testing in a US facility.", vocab) == []
       or "test" not in claim_trace.off_catalogue(
           "Look for third-party testing in a US facility.", vocab))

    print("\n— the number is recorded on every output, by ONE writer —")
    from app import ledger
    cid2 = kb.claims("eien")[0].id
    bad = ledger.record("eien", "blog", claim_ids=[cid2], format="cms_article",
                        body="Glucosamine rebuilds cartilage and is most studied.")
    good = ledger.record("eien", "blog", claim_ids=[cid2], format="cms_article",
                         body="Every batch is third-party tested in a US facility.")
    prose = ledger.record("eien", "blog", claim_ids=[cid2], format="cms_article",
                          body="You stood up from your desk.")
    ck("an unsupported output records 0", bad.grounded_pct == 0,
       str(bad.grounded_pct))
    ck("a supported one records 100", good.grounded_pct == 100,
       str(good.grounded_pct))
    ck("one that asserts NOTHING records -1, not 0", prose.grounded_pct == -1,
       "averaging 'needed no claim' with 'has no claim' is how a trend lies")

    print("\n— and the trend reads what was true AT THE TIME —")
    t = claim_trace.trend("eien", 90)
    blog = next((x for x in t if x["system"] == "blog"), None)
    ck("the trend groups by system", blog is not None, str(t))
    ck("…counts only outputs that asserted something",
       blog and blog["outputs"] == 2,
       "the prose row must not drag the average down")
    ck("…and carries a series to draw", blog and len(blog["series"]) == 2)
    ck("claim usage is one query, not one per claim",
       claim_trace.usage_counts("eien").get(cid2, 0) >= 3,
       str(claim_trace.usage_counts("eien")))
    ck("…and refuses to draw a direction off two outputs",
       blog and blog["moved"] is None,
       "None, not 0 — 0 reads as 'no change', which is a finding")

    print("\n— a direction, once there is enough to draw one —")
    # Eight grounded outputs: four unsupported, then four supported. The
    # window has to be able to SAY it improved, or the floor above is not a
    # floor, it is a mute button.
    for _ in range(claim_trace.MIN_FOR_DIRECTION):
        ledger.record("eien", "seo", claim_ids=[cid2], format="cms_article",
                      body="Glucosamine rebuilds cartilage and is most studied.")
    for _ in range(claim_trace.MIN_FOR_DIRECTION):
        ledger.record("eien", "seo", claim_ids=[cid2], format="cms_article",
                      body="Every batch is third-party tested in a US facility.")
    seo = next((x for x in claim_trace.trend("eien", 90)
                if x["system"] == "seo"), None)
    ck("with enough on each side it reports the movement",
       seo and seo["moved"] == 100, str(seo))

    print("\n— and the trend is RENDERED where the page asks the question —")
    from app import admin_ui as _ui
    page = _ui.render_assurance("", tenant="eien", days=90)
    ck("the assurance page carries the grounding trend",
       "How much of it stands on an approved claim" in page,
       "trend() sat with no reader for a day — that is the unpiped-unit "
       "defect, authored by me")
    ck("…with the systems it grouped", "seo" in page and "spark" in page)

    print("\n— a proposal, never an approval —")
    # THROUGH THE ROUTE, not around it. The first version called add_claim
    # directly and so asserted a property of add_claim; the endpoint could
    # have been changed to write an approved row and the suite would have
    # stayed green. Caught by sabotage, not by reading.
    from fastapi.testclient import TestClient

    from app import kb as _kbm, ledger as _ldg, provenance as _prov
    from app.web import app as _app
    _sentence = "Omega-3 is studied for joint comfort in adults."
    _art = _ldg.record("eien", "blog", claim_ids=[], format="cms_article",
                       body=_sentence)
    # The workroom reads the BODY table, not the ledger row — the route looks
    # the artifact up the same way the page does.
    with db.SessionLocal() as _s:
        _s.add(db.ArtifactBody(tenant="eien", output_id=_art.id,
                               system_key="blog", format="cms_article",
                               body=f"<p>{_sentence}</p>"))
        _s.commit()
    _c = TestClient(_app)
    _r = _c.post("/admin/claim_from_note?key=s3cret", follow_redirects=False,
                 data={"key": "s3cret", "output_id": _art.id,
                       "sentence": _sentence})
    ck("…and does not report success on a failure",
       "err=" not in _r.headers.get("location", ""),
       _r.headers.get("location", ""))
    ck("the route accepts the note", _r.status_code == 303, str(_r.status_code))
    with db.SessionLocal() as _s:
        _row = (_s.query(db.KbClaim)
                .filter(db.KbClaim.source ==
                        f"proposed from draft {_art.id}").one())
    ck("a claim added from a note lands PROPOSED",
       _row.review == _prov.PROPOSED,
       "approving it in one click would let the model author its own evidence")
    ck("…and no generator can select it",
       all("joint comfort" not in c.claim for c in _kbm.claims("eien")))
    ck("…with evidence and proof type left empty for a person",
       not (_row.evidence or "") and not (_row.proof_type or ""),
       "a field filled in by something that cannot know it is how "
       "'Eien Health Research' got under a real statement")

    print("\n— nothing is inserted into the artifact —")
    import re as _re2
    from app import admin_ui as ui

    class Long:
        tenant = "eien"; format = "cms_article"; system_key = "blog"
        output_id = "L"
        body = ("<h2>What the label tells you</h2>"
                "<p>Glucosamine remains the benchmark for joints. "
                "You stood up from your desk.</p>"
                "<p>Roughly one in four adults over 50 reports knee pain. "
                "The kettle had boiled twice.</p>"
                "<p>Our softgel dissolves in under 20 minutes.</p>"
                "<p>Every batch is third-party tested in a US facility.</p>")

    class Short:
        tenant = "eien"; format = "ad_batch"; system_key = "ad_creative"
        output_id = "S"
        body = '{"variants":[{"text":"Rebuilds cartilage fast."}]}'

    long_card = ui._grounding_card("eien", Long())
    short_card = ui._grounding_card("eien", Short())
    read = long_card.split('class="gread"', 1)[1].split('class="gpanel"', 1)[0]

    ck("no marker is inside the reading",
       'class="mk"' not in read,
       "a marker in the flow moves where lines wrap — and on an ad, the fold")
    ck("a wrapped sentence is a span and nothing else",
       ui._sentence_html({"text": "Every batch is tested.", "assertion": True,
                          "note": 4}, "gap")
       == '<span class="s" data-note="4" data-state="gap">'
          'Every batch is tested.</span>',
       ui._sentence_html({"text": "Every batch is tested.", "assertion": True,
                          "note": 4}, "gap"))
    ck("no commentary is inside the reading",
       "nothing on file says this" not in read,
       "that is the mixing the owner rejected")

    mk = _re2.findall(r'class="mk" data-note="(\d+)" data-state="(\w+)"', long_card)
    nt = _re2.findall(r'class="gnote" data-note="(\d+)" data-state="(\w+)"', long_card)
    ck("marker n and note n are the same n",
       bool(mk) and sorted(mk) == sorted(nt), f"markers={mk} notes={nt}")

    # THE CARD IS THE PREVIEW NOW. An article's body is rendered byte-for-byte
    # and the sentences are located with DOM Ranges, so not even a wrapper
    # span goes in — the second Preview card was deleted on the strength of
    # this, and if it ever stops holding the owner is reading a paraphrase.
    ck("an article's own HTML is emitted verbatim",
       Long.body in long_card,
       "a paraphrase in place of the preview is how the double started")
    ck("…with nothing inserted into it, not even a wrapper",
       read.count('class="s"') == 0 and 'data-notes=' in read)
    # SCOPED TO THE PAYLOAD, not to the card. The first version looked for
    # the sentence anywhere in `long_card` and found it in the panel note, so
    # emptying data-notes entirely left the suite green — the walker would
    # have had nothing to locate and nothing said so. Caught by sabotage.
    _payload = long_card.split('data-notes="', 1)[1].split('"', 1)[0]
    ck("…and every note rides in the payload the walker reads",
       len(mk) > 0 and all(f"&quot;n&quot;: &quot;{n}&quot;" in _payload
                           for n, _ in mk),
       "a marker whose sentence is not in the payload stacks at the top of "
       "the gutter pointing at nothing, and the Preview card is gone")
    ck("…carrying the sentence itself, not just the number",
       "Glucosamine remains the benchmark" in _payload.replace("&quot;", '"'),
       _payload[:120])

    # The span path still exists for what cannot be rendered live.
    short_read = short_card.split('class="gread"', 1)[1].split('class="gpanel"', 1)[0]
    ck("a flattened ad batch still gets wrapped sentences",
       'class="s"' in short_read and 'data-notes=' not in short_read,
       "its body is JSON — there is no artifact HTML to render")
    ck("both formats carry the at-a-glance bar",
       'class="meter"' in long_card and 'class="meter"' in short_card)
    ck("the panel is filterable by state",
       'data-f="gap"' in long_card and 'data-f="ok"' in long_card)

    print("\n— a fact about the world is not a claim about the company —")
    marks = claim_trace.brand_marks("eien")
    ck("the account's own name and catalogue are the marks",
       "eien" in marks, sorted(marks))
    ck("a general fact is about the world",
       not claim_trace.about_us(
           "Roughly one in four adults over 50 reports knee pain.", marks))
    ck("…and the surface says so rather than calling it unbacked",
       'data-state="world"' in long_card and
       "no approval is owed" in long_card,
       "the owner's article had every cited fact about the CONDITION "
       "reported as an unfounded company claim")
    ck("a first-person assertion is still about the company",
       claim_trace.about_us("Our softgel dissolves in 20 minutes.", marks)
       and 'data-f="gap"' in long_card)
    ck("a country code is not a pronoun",
       not claim_trace.about_us("Tested in a US facility by a third party.",
                                set()),
       "lowercasing first made 'a US facility' match the pronoun 'us'")
    ck("a generic word in the account name marks nothing",
       "health" not in marks,
       "every sentence about health would have become a claim about Eien")

    print("\n— and a judgement can be filed where it was formed —")
    ck("each note can be dropped from the redraft",
       long_card.count('name="level" value="draft"') == len(
           _re2.findall(r'class="gnote" data-note=', long_card)))
    ck("…and taught to the system for future drafts",
       long_card.count('name="level" value="system"') >= 1
       and "Never again" in long_card)
    ck("no note offers to ban the phrase",
       'value="rule"' not in long_card,
       "banning 'glucosamine' would also stop the competitor comparisons "
       "the owner explicitly wants — the lesson is the behaviour, not the noun")
    ck("a note can propose the sentence as a claim",
       long_card.count('action="/admin/claim_from_note"') >= 1)
    ck("…but never on an off-catalogue steer",
       long_card.split('data-state="off"', 1)[1].split("</li>", 1)[0]
       .count("claim_from_note") == 0,
       "\u201cglucosamine is the benchmark\u201d is not a claim to file")
    ck("…nor on one that already has a claim",
       long_card.split('data-state="ok"', 1)[1].split("</li>", 1)[0]
       .count("claim_from_note") == 0)
    ck("the standing guidance quotes what provoked it",
       "It happened here" in long_card,
       "guidance nobody can trace back to a draft is a slogan")

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
