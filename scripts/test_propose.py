"""An agent that does not know something should propose, not ask.

A question in the operator's inbox is a dead end: it interrupts, gets answered
once in a sentence nobody keeps, and the next time the same question arrives
the agent asks again. Nothing accumulates. That is why the inbox agent felt
like it never learned — it genuinely could not.

A proposal is the same instinct with a memory. Draft the answer, file it
against the thread that prompted it, and a human approves once. Every future
system then answers without asking anyone.

The invariant under test: NOTHING filed here is usable until approved.

    python3 scripts/test_propose.py
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'pp.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["READ_KEY"] = "r3adonly"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

import re  # noqa: E402

from app import embed, kb, propose, provenance as prov, tenants  # noqa: E402

_CONCEPTS = [
    {"when", "get", "here", "arrive", "ship", "shipping", "delivery", "days"},
    {"duty", "customs", "import", "tax", "charge"},
    {"gift", "wrap", "present", "packaging"},
]


def _stub(texts):
    out = []
    for t in texts:
        w = set(re.findall(r"[a-z]+", (t or "").lower()))
        out.append([float(len(w & c)) for c in _CONCEPTS] + [0.1])
    return out, ""
from app.web import app  # noqa: E402

_fail = []
REF = "thread t-88, customer asked 2026-08-14"


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    with TestClient(app) as cl:
        tenants.seed()
        embed.set_provider(_stub)
        kb.ensure_brand("baci", "Baci Milano USA")
        kb.add_banned("baci", "made in Italy")
        kb.add_situation("baci", "shipping_time", patterns=[],
                         description="When will it get here?", origin="seed")

        print("— an agent origin can never land usable —")
        ck("agent is not auto-approved",
           not prov.lands_approved("agent"),
           "the only reason an agent may write to the KB at all")

        print("\n— the objection it could not answer, with its draft —")
        r = propose.objection("baci", "Do you ship to Canada?",
                              "Yes — Canadian orders ship in 5-7 business days.",
                              source_ref=REF, situations=["shipping_time"])
        ck("it files", r["ok"], str(r))
        ck("and nothing became usable", kb.objections("baci") == [],
           "selection must not see it before a human does")
        pending = [o for o in kb.objections("baci", any_entity=True,
                                            include_proposed=True)
                   if (o.review or "") == prov.PROPOSED]
        ck("it IS on the review queue", len(pending) == 1, str(len(pending)))
        ck("carrying the thread that prompted it",
           REF in (pending[0].source or ""), pending[0].source or "(none)")

        print("\n— and approval still demands a scope decision —")
        # Not a bug in propose: approving an objection with no entity is
        # claiming it of the whole catalogue, which is DEFECTS 2.19 enforced at
        # the gate. The agent front-loads what it knows; the reviewer confirms.
        ck("the proposal says so up front",
           r["needs_at_approval"] and "brand-wide" in r["needs_at_approval"][0],
           "a confusing rejection later, turned into a decision now")
        refused = kb.approve("objection", pending[0].id, by="gomeh")
        ck("an unscoped approval is refused",
           "Say what this answer is true of" in refused, refused[:48])

        print("\n— approving it is what makes the agent stop asking —")
        kb.approve("objection", pending[0].id, by="gomeh", brand_wide=True)
        ck("now it is answerable", len(kb.objections("baci")) == 1)
        # THE INVARIANT. An agent proposing over a signed-off answer used to
        # OVERWRITE it: approve() leaves `origin` alone, so the row still read
        # as agent-origin and may_write's same-origin refresh let it through.
        # "Yes 5-7 days." silently became whatever the agent said next, still
        # marked approved, with no conflict recorded.
        again = propose.objection("baci", "Do you ship to Canada?",
                                  "ACTUALLY 20 DAYS AND WE LOSE PARCELS.",
                                  source_ref=REF)
        approved = kb.objections("baci")[0]
        ck("an agent CANNOT overwrite an approved answer",
           approved.response == "Yes — Canadian orders ship in 5-7 business days.",
           approved.response[:44])
        ck("the disagreement is recorded instead",
           len(prov.conflicts("baci")) == 1,
           "keep both, change neither — the spine's whole job")
        ck("and the agent is told, not silently ignored",
           "recorded, not applied" in again["message"], again["message"][:60])

        print("\n— a gap with no draft answer is refused —")
        r = propose.objection("baci", "Do you gift wrap?", "  ")
        ck("it refuses", not r["ok"])
        ck("because approving a blank is doing the work yourself",
           "done the work themselves" in r["why"], r["why"][:50])

        print("\n— a claim with no evidence is refused —")
        r = propose.claim("baci", "We ship 2,000 orders a month.", "")
        ck("it refuses", not r["ok"])
        ck("naming why a reviewer cannot check it",
           "take a machine's word" in r["why"], r["why"][:60])
        r = propose.claim("baci", "We ship 2,000 orders a month.",
                          "Shopify orders report, Jul 2026",
                          source_ref=REF, situations=["shipping_time"])
        ck("with evidence it files", r["ok"], str(r.get("message"))[:40])
        ck("still not selectable", kb.claims("baci") == [])

        print("\n— it cannot sprawl the vocabulary —")
        r = propose.situation("baci", "time_shipping",
                              "When will it get here?", source_ref=REF)
        ck("a reordered synonym of an existing tag is refused", not r["ok"],
           r.get("message", "")[:70])
        ck("and it points at the tag that already covers it",
           "already has" in r.get("message", ""), r.get("note", ""))
        # `delivery_time` vs `shipping_time`: no shared token, one idea. This
        # used to slip through and was written up as a known limit while
        # `situation` was already a valid embedding kind and nothing indexed
        # it. The stub gives the two descriptions an identical vector.
        slipped = propose.situation("baci", "delivery_time",
                                    "When will it get here?", source_ref=REF)
        ck("a true synonym with NO shared words is caught semantically",
           not slipped["ok"], slipped.get("message", "")[:70])
        ck("and it names the tag that already covers it",
           "shipping_time" in slipped.get("message", ""),
           "lexical could not see this; the embedding can")
        r = propose.situation("baci", "customs_duty",
                              "Who pays the import duty?", source_ref=REF)
        ck("a genuinely new one is proposed", r["ok"], r["message"][:40])
        ck("but cannot tag anything yet",
           "customs_duty" not in kb.situations("baci"),
           "proposed tags must not become usable vocabulary")

        print("\n— a bare tag with no meaning is refused —")
        ck("description is required",
           not propose.situation("baci", "misc", "")["ok"],
           "a tag nobody else can apply consistently is noise")

        print("\n— over HTTP, and only by POST —")
        r = cl.post("/propose", json={"tenant": "baci", "kind": "objection",
                                      "question": "Do you gift wrap?",
                                      "answer": "Yes, on request."})
        ck("no credential is refused", r.json().get("error") == "unauthorized")
        r = cl.post("/propose?key=r3adonly",
                    json={"tenant": "baci", "kind": "objection",
                          "question": "Do you gift wrap?",
                          "answer": "Yes, on request at checkout."})
        ck("the read key may propose", r.json().get("ok"), str(r.json())[:70])
        ck("a GET cannot file one", cl.get("/propose").status_code == 405,
           "a browser prefetch must never write to the knowledge base")
        r = cl.post("/propose?key=r3adonly",
                    json={"tenant": "baci", "kind": "nonsense"})
        ck("an unknown kind is named", "kind must be" in r.json()["error"])

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
