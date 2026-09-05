"""The panel sits BEFORE the drafter: Hormozi and Piliero on the concepts.

Owner, 2026-09-04: *"every ad copy goes through the 'Alex Hormozi' and 'Sam
Piliero' test to self-justify — show what each would say and apply the
improvements BEFORE the variants are generated."* `ad_craft.review` ran AFTER
each draft, on the words, one variant at a time; no panel existed and nothing
was shown. This pins the order and the join, not the label:

  · ONE panel pass over the batch's CONCEPTS (angle x claim x offer x reader)
    runs before the first draft — the call order is recorded, not inferred;
  · each variant is drafted against ITS rewritten brief, which rides the
    bundle into `ad_prompt` ahead of the ruleset's angle;
  · the board shows what each reviewer said and the brief the copy was
    written to, per variant, and Piliero's verdict on the batch;
  · when the panel cannot sit, the run says so by name and the drafts still
    happen on the ruleset alone — never a silent skip.

    python3 scripts/test_ad_panel.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'adp.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import ad_craft, db, kb, skill, skill_pack, systems, tenants, web  # noqa: E402

KEY = "s3cret"
_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


_ALL = {c: True for c in tenants.CAPABILITIES}
tenants.capabilities = lambda key: dict(_ALL) if tenants.get(key) else \
    {c: False for c in tenants.CAPABILITIES}

LOG: list[tuple] = []


class FakePanel:
    """Stands in for `panel_ad` and REMEMBERS the concepts it was shown."""

    def __init__(self, answer=None, why=""):
        self.answer, self.why = answer, why
        self.concepts: list = []
        self.bundles: list = []

    def __call__(self, bundle, concepts):
        LOG.append(("panel", len(concepts)))
        self.concepts.append(list(concepts))
        self.bundles.append(bundle)
        if self.why:
            return {}, self.why
        return ({"variants": {c["n"]: {"hormozi": f"HORMOZI-{c['n']}: lead with effort",
                                       "piliero": f"PILIERO-{c['n']}: open on the reader",
                                       "brief": f"PANELBRIEF-{c['n']}"}
                              for c in concepts},
                 "batch": {"piliero": "three distinct entries",
                           "verdict": "distinct"}}, "")


class FakeDraft:
    def __init__(self):
        self.bundles: list = []
        self.n = 0

    def __call__(self, bundle, claim, angle, objections):
        LOG.append(("draft", str((bundle.get("panel") or {}).get("brief") or "")))
        self.bundles.append(bundle)
        self.n += 1
        # A VALID CAPTION, so this suite tests the PANEL and not the craft
        # gate: since the Instagram rules landed, a bare line with no ask is
        # blocked and redrafted once, which doubled the calls and made the
        # brief assertion read as a failure when nothing about the panel had
        # changed.
        return (f"HEADLINE: Which host are you\nLEVERS: dream_outcome, effort\n---\n"
                f"Ad line {self.n}: {str(claim.get('claim') or '')[:40]}\n\n"
                f"Tap to shop it.", "")


def contract(row, autonomy):
    systems.update(row.id, **{f: "declared for the test"
                              for f, _l, _h in systems.CONTRACT})
    systems.update(row.id, status="live", autonomy=autonomy)
    return systems.get(row.id)


def board(anchor):
    with db.SessionLocal() as s:
        art = (s.query(db.ArtifactBody)
               .filter(db.ArtifactBody.output_id == anchor).first())
        s.expunge_all()
    return art, (json.loads(art.body) if art else None)


def main() -> int:
    db.init_db()
    tenants.seed()
    kb.ensure_brand("baci", "Baci")
    kb.set_brand("baci", positioning="Italian-designed tableware.", tone="direct, warm")
    kb.add_banned("baci", "hand-decorated")
    for c, ev in (("Dishwasher safe at 65 degrees.", "lab report"),
                  ("Made of shatter-resistant acrylic.", "spec sheet"),
                  ("Designed in Milan.", "brand file")):
        kb.add_claim("baci", c, ev, [], origin="human", status="active")
    kb.add_audience("baci", "hosts", "Hosts who entertain",
                    ["dull tables"], ["colour", "set"], origin="human")
    kb.add_entity("baci", "product", "aqua-plate", "Aqua Plate",
                  description="A generous 32 cm plate.", origin="human")
    row = systems.find("baci", "ad_creative") or systems.create("baci", "ad_creative")
    contract(row, autonomy="approve_all")

    print("— the real seam names its absence offline —")
    got, why = skill_pack._panel_ad_live({"tenant": "baci"},
                                         [{"n": 1, "claim": {"claim": "x"}, "angle": "identity"}])
    ck("with no key the panel says which key", got == {} and "ANTHROPIC_API_KEY" in why, why)
    ck("  and nothing to sit on is said too",
       "nothing to sit on" in skill_pack._panel_ad_live({}, [])[1])

    print("\n— parse: the shape asked, or nothing —")
    good = json.dumps({"variants": [{"n": 1, "hormozi": "h", "piliero": "p", "brief": "b"},
                                    {"n": "2", "brief": "b2"}],
                       "batch": {"piliero": "fine", "verdict": "Distinct"}})
    parsed = ad_craft.panel_parse("Sure, here it is:\n" + good + "\nDone.")
    ck("a JSON answer parses, keyed by variant number",
       parsed["variants"][1]["brief"] == "b" and parsed["variants"][2]["brief"] == "b2"
       and parsed["batch"]["verdict"] == "distinct", str(parsed)[:120])
    ck("junk is nothing, not a crash", ad_craft.panel_parse("no json here") == {}
       and ad_craft.panel_parse("") == {})
    ck("an answer naming no variants is nothing",
       ad_craft.panel_parse('{"batch": {"verdict": "distinct"}}') == {})
    ck("the drafter's section is absent when there is no brief",
       ad_craft.panel_brief({}) == "" and ad_craft.panel_brief({"hormozi": "h"}) == "")

    print("\n— the panel sits first, on the concepts —")
    LOG.clear()
    fake_panel, fake_draft = FakePanel(), FakeDraft()
    skill_pack.panel_ad, skill_pack.draft_ad = fake_panel, fake_draft
    r = skill.run("ad_copy", "baci", entity_key="aqua-plate",
                  audience_key="hosts", variants=3)
    ck("three variants produced", r["status"] == "produced" and len(r["items"]) == 3,
       f"{r['status']}, {len(r.get('items') or [])}")
    ck("the panel was called ONCE, and before any draft",
       LOG and LOG[0][0] == "panel" and [x[0] for x in LOG].count("panel") == 1
       and all(x[0] == "draft" for x in LOG[1:]), str(LOG))
    ck("  on all three concepts", LOG[0][1] == 3 and len(fake_panel.concepts[0]) == 3)
    cons = fake_panel.concepts[0]
    ck("  each concept carries its claim and its angle",
       all(c.get("claim", {}).get("claim") and c.get("angle") in ad_craft.ANGLES
           for c in cons), str([(c["angle"], c["claim"]["claim"][:20]) for c in cons]))
    shown = "\n".join(ad_craft.panel_prompt(fake_panel.bundles[0], cons))
    ck("  the panel is shown the reader, the claims and the angles — not copy",
       "Hosts who entertain" in shown and "Dishwasher safe" in shown
       and "### Concept 1" in shown and "Ad line" not in shown, shown[:200])
    ck("  and told there is no offer and no deadline, rather than left to invent",
       "OFFER: none" in shown and "DEADLINE: none" in shown)

    print("\n— each variant is drafted on ITS rewritten brief —")
    briefs = [x[1] for x in LOG if x[0] == "draft"]
    ck("draft 1, 2, 3 each carried its own panel brief",
       briefs == ["PANELBRIEF-1", "PANELBRIEF-2", "PANELBRIEF-3"], str(briefs))
    b1 = fake_draft.bundles[0]
    claim = {"claim": "Dishwasher safe at 65 degrees.", "evidence": "lab report",
             "claim_id": "x"}
    prompt = "\n".join(skill_pack.ad_prompt(b1, claim, "identity", []))
    ck("the brief reaches the drafter's prompt",
       "PANELBRIEF-1" in prompt and "HORMOZI-1" in prompt and "PILIERO-1" in prompt,
       prompt[-300:])
    # THE BRIEF IS THE LAST WORD, and the angle above it says so. It used to
    # come BEFORE `## Angle` and the two contradict by design: reproduced
    # 2026-09-05 with a brief saying "drop the identity-quiz angle entirely"
    # sitting above a heading telling the model to open with "which one are
    # you". The generic instruction was last, under a heading, so it won.
    ck("  AFTER the ruleset's angle, because the brief has to be the last word",
       prompt.index("## Angle") < prompt.index("WRITE THIS"),
       "the panel's whole job is to say what this concept should stop doing")
    ck("  and it says outright that it overrides the angle",
       "OVERRIDES the angle" in prompt and "the brief wins" in prompt)
    ck("  while the angle above says it is where the concept STARTED",
       "This is where the concept STARTED" in prompt)
    plain = "\n".join(skill_pack.ad_prompt(
        {**b1, "panel": {}}, claim, "identity", []))
    ck("  a concept with no brief keeps the angle as its instruction",
       "STARTED" not in plain and "## Angle" in plain,
       "demoting it with nothing to replace it would leave no instruction")
    ck("the run says the panel sat, with Piliero's verdict on the batch",
       any("the panel sat on 3 concept(s)" in n and "distinct" in n for n in r["notes"]),
       str([n for n in r["notes"] if "panel" in n])[:200])

    print("\n— the board shows what each said, per variant and for the batch —")
    anchor = r["items"][0]["output_id"]
    art, batch = board(anchor)
    ck("every variant row carries its panel",
       batch and [v["panel"]["brief"] for v in batch["variants"]]
       == ["PANELBRIEF-1", "PANELBRIEF-2", "PANELBRIEF-3"], str(batch and batch.get("variants"))[:120])
    ck("  and the batch carries the verdict",
       batch["panel"]["sat"] is True and batch["panel"]["verdict"] == "distinct")
    c = TestClient(web.app, base_url="https://testserver")
    page = c.get(f"/admin/work/{anchor}?key={KEY}").text
    ck("the board renders the panel beside each variant",
       "The reviewers" in page and "PANELBRIEF-2" in page
       and "HORMOZI-3" in page, "")
    # SECONDARY EVIDENCE, not the headline. Owner, 2026-09-05.
    ck("  folded, because the ad is the product and this is the working",
       "<details class=\"sec\"><summary>The reviewers" in page
       and "<details class=\"sec\" open><summary>The reviewers" not in page, "")
    ck("  and a variant they passed says so in one line",
       "they read it back and passed it" in page, "")
    ck("  and Piliero on the batch", "batch: distinct" in page
       and "three distinct entries" in page)

    print("\n— AND THE REVIEWERS READ THEIR OWN DRAFTS BACK —")
    # Owner, 2026-09-05: "it leaves us with a need to apply the edits provided
    # and summarized … check against their opinions when you generate the
    # first draft." The brief was an instruction and nothing verified it
    # landed; `ad_craft.review` measures the SHAPE and a draft can pass all of
    # it while keeping the mechanic the brief told it to drop.
    LOG.clear()
    seen_checks: list = []
    redrafts: list = []

    class _Drafter:
        def __init__(self):
            self.n = 0

        def __call__(self, bundle, claim, angle, objections):
            self.n += 1
            rules = str((bundle.get("rules") or {}).get("block") or "")
            if "DID NOT FOLLOW THE BRIEF" in rules:
                redrafts.append(rules)
                return ("HEADLINE: The bowl that survived\nLEVERS: effort, dream_outcome\n---\n"
                        "FIXED DRAFT: no quiz, leads with effort.\n\nTap to shop.", "")
            return ("HEADLINE: Which host are you\nLEVERS: effort, dream_outcome\n---\n"
                    "IGNORED THE BRIEF: which one are you?\n\nTap to shop.", "")

    def _check(bundle, drafts):
        seen_checks.append(list(drafts))
        return ({d["n"]: {"followed": d["n"] != 1,
                          "ignored": ["kept the identity quiz the brief said to drop"],
                          "fix": "open on the moment of worry, not a quiz"}
                 for d in drafts}, "")

    skill_pack.panel_ad = FakePanel()
    skill_pack.draft_ad = _Drafter()
    skill_pack.panel_check = _check
    r3 = skill.run("ad_copy", "baci", entity_key="aqua-plate",
                   audience_key="hosts", variants=3)
    ck("the reviewers are given the drafts with the briefs they were written to",
       len(seen_checks) == 1 and len(seen_checks[0]) == 3
       and seen_checks[0][0]["brief"] == "PANELBRIEF-1"
       and "IGNORED THE BRIEF" in seen_checks[0][0]["text"],
       "one call for the batch, not one per variant")
    ck("  and it is ONE call, after the drafting, not before",
       len(seen_checks) == 1, str(len(seen_checks)))
    ck("a variant that ignored its brief is WRITTEN AGAIN",
       len(redrafts) == 1 and "kept the identity quiz" in redrafts[0],
       f"{len(redrafts)} redraft(s)")
    ck("  with the reviewers' own objection in front of it",
       "DID NOT FOLLOW THE BRIEF" in redrafts[0]
       and "open on the moment of worry" in redrafts[0], "")
    _, b3 = board(r3["items"][0]["output_id"])
    v1 = b3["variants"][0]
    ck("  and the AD THAT IS FILED is the corrected one",
       "FIXED DRAFT" in v1["text"] and "IGNORED THE BRIEF" not in v1["text"],
       v1["text"][:80])
    ck("  the row records what was applied, not just what was said",
       v1["panel_applied"] == ["kept the identity quiz the brief said to drop"]
       and v1["panel_followed"] is True, str(v1.get("panel_applied")))
    ck("a variant that DID follow is left alone",
       "IGNORED THE BRIEF" in b3["variants"][1]["text"]
       and not b3["variants"][1]["panel_applied"],
       "rewriting work that was already right is how a good draft gets worse")
    page3 = c.get(f"/admin/work/{r3['items'][0]['output_id']}?key={KEY}").text
    ck("the board LEADS with what was applied, not with the critique",
       "Applied from the panel" in page3
       and "kept the identity quiz" in page3, "")
    ck("the run says which variant was rewritten and why",
       any("did not follow its brief" in n and "Written again" in n
           for n in r3["notes"]),
       str([n for n in r3["notes"] if "did not follow" in n])[:200])

    print("\n— a rewrite that obeys the brief and breaks the craft is refused —")
    # Following the brief is the point; trading a blocked hook for it is not.
    # Without this case nothing exercises the comparison, and the guard that
    # protects it reported MISSED.
    class _WorseDrafter:
        def __call__(self, bundle, claim, angle, objections):
            rules = str((bundle.get("rules") or {}).get("block") or "")
            if "DID NOT FOLLOW THE BRIEF" in rules:
                # Obeys the brief, and opens on an adjective with no ask:
                # `hook_is_vague` plus `no_call_to_action`.
                return ("HEADLINE: Elegant\nLEVERS: effort, dream_outcome\n---\n"
                        "Elegant acrylic that follows the brief exactly.", "")
            return ("HEADLINE: The bowl that survived\nLEVERS: effort, dream_outcome\n---\n"
                    "A first draft that reads fine.\n\nTap to shop.", "")

    skill_pack.draft_ad = _WorseDrafter()
    skill_pack.panel_check = lambda b, d: (
        {x["n"]: {"followed": False, "ignored": ["kept the quiz"],
                  "fix": "open on the worry"} for x in d}, "")
    r5 = skill.run("ad_copy", "baci", entity_key="aqua-plate",
                   audience_key="hosts", variants=1)
    _, b5 = board(r5["items"][0]["output_id"])
    ck("the first draft stands when the rewrite breaks the craft rules",
       "A first draft that reads fine" in b5["variants"][0]["text"]
       and "Elegant acrylic" not in b5["variants"][0]["text"],
       b5["variants"][0]["text"][:80])
    ck("  and the row says the change was asked for and not made",
       b5["variants"][0]["panel_followed"] is False
       and b5["variants"][0]["panel_applied"] == ["kept the quiz"],
       str(b5["variants"][0].get("panel_applied")))
    ck("  the run says why, rather than silently keeping the first draft",
       any("broke the craft rules" in n for n in r5["notes"]),
       str([n for n in r5["notes"] if "craft rules" in n])[:160])
    page5 = c.get(f"/admin/work/{r5['items'][0]['output_id']}?key={KEY}").text
    ck("  and the board says the change is still owed",
       "did not make" in page5 and "Request changes" in page5, "")

    print("\n— a check that cannot run says so, and files the first draft —")
    skill_pack.draft_ad = _Drafter()
    skill_pack.panel_check = lambda b, d: ({}, "ANTHROPIC_API_KEY is not set")
    r4 = skill.run("ad_copy", "baci", entity_key="aqua-plate",
                   audience_key="hosts", variants=2)
    ck("the run names why the drafts were not read back",
       any("did not read the drafts back" in n and "ANTHROPIC_API_KEY" in n
           for n in r4["notes"]),
       str([n for n in r4["notes"] if "read the drafts" in n])[:200])
    ck("  and the first draft is filed rather than nothing",
       len(r4["items"]) == 2)

    print("\n— when the panel cannot sit, the run says so and drafts anyway —")
    LOG.clear()
    skill_pack.panel_ad = FakePanel(why="ANTHROPIC_API_KEY is not set")
    fake_draft2 = FakeDraft()
    skill_pack.draft_ad = fake_draft2
    r2 = skill.run("ad_copy", "baci", entity_key="aqua-plate",
                   audience_key="hosts", variants=2)
    ck("the variants were still drafted", r2["status"] == "produced" and len(r2["items"]) == 2)
    ck("  the run names why the panel did not sit",
       any("the panel did not sit" in n and "ANTHROPIC_API_KEY" in n for n in r2["notes"]),
       str([n for n in r2["notes"] if "panel" in n])[:200])
    ck("  and the drafter got no invented brief",
       all(not (b.get("panel") or {}) for b in fake_draft2.bundles))
    _, b2 = board(r2["items"][0]["output_id"])
    page2 = c.get(f"/admin/work/{r2['items'][0]['output_id']}?key={KEY}").text
    ck("  the board says the panel did not sit, and why",
       b2["panel"]["sat"] is False and "ANTHROPIC_API_KEY" in b2["panel"]["why_not"]
       and "The panel did not sit" in page2)

    print()
    if _fail:
        print(f"{len(_fail)} FAILED: {_fail}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
