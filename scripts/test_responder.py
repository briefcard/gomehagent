"""The first thing in this platform that produces something, end to end.

    a real question  ->  resolve  ->  assemble  ->  validate  ->  ledger

No model call anywhere in it, and that is not a workaround for a capped API
key. An approved objection already carries the response a human wrote and
signed off; answering a question that matches it is retrieval and validation,
not authorship. A model would only make it sound bespoke, which is the last
thing to add rather than the first.

What this suite is really asserting is that the layer REFUSES correctly. Any
system can produce an answer. The claim being tested is that it declines to
when it cannot ground one, names the field that stopped it, and files the
refusal so the gap gets counted.

    python3 scripts/test_responder.py
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'rp.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import conversation as cv, db, kb, ledger, responder, tenants  # noqa: E402
from app.web import app  # noqa: E402

_fail = []

QUESTION = "Is this dishwasher safe or will it chip?"


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _seed():
    """Baci, shaped the way the live account actually is."""
    kb.ensure_brand("baci", "Baci Milano USA")
    kb.set_brand("baci", positioning="Italian-designed tableware for hosts.",
                 tone="formal, brisk")
    for phrase in ("made in Italy", "handmade", "hand-painted", "guarantee"):
        kb.add_banned("baci", phrase)
    kb.add_situation("baci", "quality_doubt", patterns=[["dishwasher"]],
                     description="Will it survive real use?", origin="seed")
    kb.add_situation("baci", "gifting", patterns=[],
                     description="Buying for someone else.", origin="seed")
    kb.add_claim("baci", "Every piece is tested on a normal dishwasher cycle.",
                 "tested across the porcelain range", ["quality_doubt"],
                 proof_type="data", source="seed", origin="human")
    kb.add_objection(
        "baci", "Will it break in the dishwasher?",
        "It is dishwasher safe — every piece is tested on a normal cycle.",
        situations=["quality_doubt"], origin="human")
    for r in kb.pending_claims("baci"):
        kb.review_claim(r.id, approve=True)
    kb.add_entity("baci", "product", "zodiac-cup", "Zodiac Vibe Cup",
                  attributes={"material": "porcelain"}, price="$45",
                  origin="human")


def main() -> int:
    with TestClient(app) as cl:  # noqa: F841
        tenants.seed()
        _seed()

        print("— a real question, answered from what a human approved —")
        r = responder.answer("baci", QUESTION, entity_key="zodiac-cup")
        ck("it answers", r["ok"], str(r.get("blocked_on"))[:90])
        ck("with the approved response, not an invention",
           r["draft"].startswith("It is dishwasher safe"), r["draft"][:60])
        ck("it says which question it is answering",
           "dishwasher" in r["answers"].lower(), r["answers"])
        ck("and it carries the proof",
           r["evidence"] and "tested" in r["evidence"][0]["claim"],
           str(r["evidence"])[:70])
        ck("the ban list was actually enforced, not assumed",
           r["rules_enforced"] == 4, str(r["rules_enforced"]))
        ck("nothing was sent", "nothing was sent" in r["note"])

        print("\n— and it is on the ledger, with the brief that produced it —")
        rows = ledger.recent("baci")
        ck("one output on file", len(rows) == 1, str(len(rows)))
        row = rows[0]
        ck("the situation is recorded", row.situation == "quality_doubt",
           row.situation)
        ck("so is the claim it leaned on",
           row.claim_ids and len(row.claim_ids) == 1, str(row.claim_ids))
        ck("and the objection that answered",
           bool(row.objection_id),
           "'why did we say that' is a lookup, not a reconstruction")

        print("\n— a barred phrase is blocked by CODE, not by a prompt —")
        bad = [o for o in kb.objections("baci", any_entity=True)][0]
        kb.update_objection(bad.id,
                            response="Every piece is handmade in Italy.")
        r = responder.answer("baci", QUESTION, entity_key="zodiac-cup")
        ck("it refuses", not r["ok"])
        ck("and names the phrase",
           any("handmade" in b for b in r["blocked_on"]), str(r["blocked_on"]))
        ck("the refusal is on the ledger too",
           any(x.status == "blocked" for x in ledger.recent("baci")),
           "a ledger of only what worked cannot tell you what stopped")
        kb.update_objection(
            bad.id,
            response="It is dishwasher safe — every piece is tested on a "
                     "normal cycle.")

        print("\n— a question it cannot place is refused, not guessed —")
        r = responder.answer("baci", "Do you ship pallets to Ohio on Tuesdays?")
        ck("it declines", not r["ok"])
        ck("and says why", any("could not be placed" in b or "no approved" in b
                               for b in r["blocked_on"]), str(r["blocked_on"]))

        print("\n— an out-of-stock product holds the answer back —")
        kb.add_entity("baci", "product", "sold-out", "Sold Out Cup",
                      origin="human")
        with db.SessionLocal() as s:
            e = s.query(db.KbEntity).filter(db.KbEntity.tenant == "baci",
                                            db.KbEntity.key == "sold-out").first()
            e.availability = "oos"
            s.commit()
        r = responder.answer("baci", QUESTION, entity_key="sold-out")
        ck("it refuses to route demand to an empty shelf", not r["ok"])
        ck("and names the product", any("oos" in b or "Sold Out" in b
                                        for b in r["blocked_on"]),
           str(r["blocked_on"]))

        print("\n— sending is a separate, idempotent act —")
        r = responder.answer("baci", QUESTION, entity_key="zodiac-cup")
        ck("a fresh draft exists", r["ok"])
        with db.SessionLocal() as s:
            c = db.Contact(tenant="baci", email="ask@shop.com", name="Ask")
            s.add(c)
            s.commit()
            s.refresh(c)
            cid = c.id
        conv, _ = cv.open_or_get("baci", cid, "service_desk")
        first = responder.send("baci", r["output_id"], conversation_id=conv.id)
        ck("it goes out once", first["ok"] and not first.get("already_sent"))
        again = responder.send("baci", r["output_id"], conversation_id=conv.id)
        ck("and a retry does NOT send it twice", again.get("already_sent"),
           "the output id is the idempotency key — this is the double-send "
           "the handoff flags as unfixed")

        print("\n— the same proof does not go out twice in a fortnight —")
        r2 = responder.answer("baci", QUESTION, entity_key="zodiac-cup")
        ck("the repeat is caught", not r2["ok"], str(r2.get("blocked_on"))[:80])
        ck("and it names the rule",
           any("repeat" in b for b in r2["blocked_on"]), str(r2["blocked_on"]))

        print("\n— hygiene refuses to conclude from four outputs —")
        u = ledger.unused_claims("baci")
        ck("it reports the list", "never_used" in u)
        ck("but withholds the ratio",
           u["enough_to_conclude"] is False and "do not act" in u["note"],
           u["note"][:60])

        print("\n— attribution needs one thing to have varied —")
        a = ledger.record("baci", "creative", situation="gifting",
                          entity_key="zodiac-cup", angle="A", theme="light")
        b = ledger.record("baci", "creative", situation="gifting",
                          entity_key="zodiac-cup", angle="B", theme="light")
        d = ledger.diff("baci", a.id, b.id)
        ck("one field differs, so a result is attributable",
           d["interpretable"] and list(d["varied"]) == ["angle"], str(d["varied"]))
        c = ledger.record("baci", "creative", situation="collector",
                          entity_key="other", angle="C", theme="dark")
        d2 = ledger.diff("baci", a.id, c.id)
        ck("four fields differ, so it is not",
           not d2["interpretable"] and "cannot be attributed" in d2["note"],
           str(list(d2["varied"])))

        print("\n— one account's ledger is invisible to another —")
        ck("eien sees nothing of baci's", ledger.recent("eien") == [])
        ck("and cannot diff its rows",
           "error" in ledger.diff("eien", a.id, b.id))

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
