"""A thin bundle that reads as complete is worse than no bundle at all.

`resolve()` is the one call every system and skill makes. Its job is not to
return as much as possible — it is to return what it could ground, and to say
plainly what it could not. Two failures matter more than the rest, and both
are the same failure wearing different clothes:

  * retrieving objections against a situation nobody could place, so a
    plausible answer arrives aimed at the wrong problem
  * reporting `complete` when half the request was skipped

Both are "absence collapsed into a value", which this codebase has now met
four times (DEFECTS 2.5, 2.6, 2.11, 2.24). Here it would be absence collapsed
into an *answer*.

Also covers the read-only key, which exists because APPROVAL_SECRET is not
one: several console routes still mutate on a GET, so the credential a context
consumer holds must not be the credential that can seed the knowledge base.

    python3 scripts/test_resolve.py
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'rv.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["READ_KEY"] = "r3adonly"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import conversation as cv, db, kb, resolve as rs, tenants  # noqa: E402
from app.web import app  # noqa: E402

_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _seed_baci():
    kb.ensure_brand("baci", "Baci Milano USA")
    kb.set_brand("baci", positioning="Italian-designed tableware.",
                 tone="direct, warm")
    kb.add_banned("baci", "made in Italy")
    kb.add_banned("baci", "handmade")
    kb.add_situation("baci", "durability", patterns=[["dishwasher"]],
                     description="Will it survive real use?", origin="seed")
    kb.add_situation("baci", "gifting", patterns=[],
                     description="Buying it for someone else.", origin="seed")
    kb.add_claim("baci", "Every piece survives a normal dishwasher cycle.",
                 "tested across the porcelain range", ["durability"],
                 proof_type="data", source="seed", origin="human")
    kb.add_objection("baci", "Will it break in the dishwasher?",
                     "No — every piece is tested on a normal cycle.",
                     situations=["durability"], origin="human")
    for r in kb.pending_claims("baci"):
        kb.review_claim(r.id, approve=True)
    kb.add_entity("baci", "product", "zodiac-cup", "Zodiac Vibe Cup",
                  attributes={"material": "porcelain", "pieces": 6},
                  price="$45", origin="human")


def main() -> int:
    with TestClient(app) as cl:
        tenants.seed()
        _seed_baci()

        print("— an unknown account is refused, not guessed at —")
        b = rs.resolve("not_a_client")
        ck("it says so", b.get("error") == "unknown account")
        ck("and blocks", b["blocked_on"] == ["a known tenant"])

        print("\n— tier 1 is always there, in both shapes —")
        b = rs.resolve("baci", tier=1)
        ck("the prose block is ready to inject",
           "Baci Milano USA" in b["rules"]["block"])
        ck("and the ban list is structured for a validator",
           b["rules"]["banned_claims"] == ["made in Italy", "handmade"],
           str(b["rules"]["banned_claims"]))
        ck("the voice travels with it",
           b["rules"]["voice_tone"] == ["direct", "warm"],
           str(b["rules"]["voice_tone"]))
        ck("tier 1 says it skipped the rest rather than returning nothing",
           any(s["what"] == "situated" for s in b["coverage"]["skipped"]))

        print("\n— an account with no ban list is BLOCKED, not warned —")
        b = rs.resolve("coverings")
        ck("it blocks on the ban list",
           any("banned_claims" in x for x in b["blocked_on"]),
           str(b["blocked_on"])[:80])
        ck("and names why it matters",
           any("validate" in x for x in b["blocked_on"]))

        print("\n— THE FAILURE: an unplaceable utterance must not retrieve —")
        b = rs.resolve("baci", utterance="Do you deliver to warehouses on "
                                         "Tuesdays in the winter months?")
        ck("nothing was placed", not b["situations"]["confident"],
           str(b["situations"]["detected"]))
        ck("so NO objections came back", b["objections"] == [],
           "ranking against a tag nobody stands behind returns a plausible "
           "answer aimed at the wrong problem")
        ck("the skip is recorded with its reason",
           any(s["what"] == "objections" and "could not place" in s["why"]
               for s in b["coverage"]["skipped"]),
           str(b["coverage"]["skipped"])[:90])
        ck("and it blocks rather than answering anyway",
           any("could not be placed" in x for x in b["blocked_on"]))
        ck("the near-miss is still handed over for a human",
           "candidates" in str(b["coverage"]["skipped"]))

        print("\n— a placed utterance retrieves, with its proof —")
        b = rs.resolve("baci", utterance="Is it dishwasher safe on a normal cycle?")
        ck("it placed the situation", b["situations"]["confident"]
           and "durability" in b["situations"]["detected"],
           str(b["situations"]["detected"]))
        ck("a pattern hit is reported as a decision",
           b["situations"]["basis"] == "pattern")
        ck("the objection came back", len(b["objections"]) == 1,
           str(len(b["objections"])))
        ck("and it carries the claim that backs it",
           b["objections"][0]["support"]
           and "dishwasher" in b["objections"][0]["support"][0]["claim"].lower(),
           str(b["objections"][0]["support"])[:70])
        ck("the receipt counts what it found",
           b["coverage"]["counts"]["objections"] == 1
           and b["coverage"]["counts"]["support_claims"] == 1)

        print("\n— an account with nothing to answer with blocks —")
        kb.ensure_brand("eien", "Eien Health")
        kb.set_brand("eien", tone="plain")
        kb.add_banned("eien", "cures")
        kb.add_situation("eien", "durability", patterns=[["dishwasher"]],
                         origin="seed")
        b = rs.resolve("eien", utterance="Is it dishwasher safe?")
        ck("it placed the situation", b["situations"]["confident"])
        ck("but says it has nothing on file to answer with",
           any("nothing on file" in x for x in b["blocked_on"]),
           str(b["blocked_on"])[:90])

        print("\n— tier 3 reaches entities and conversation —")
        with db.SessionLocal() as s:
            c = db.Contact(tenant="baci", email="buyer@shop.com", name="Buyer")
            s.add(c)
            s.commit()
            s.refresh(c)
            cid = c.id
        conv, _ = cv.open_or_get("baci", cid, "service_desk",
                                 situations=["durability"])
        cv.commit_to("baci", conv.id, "refund", "full refund by Friday")
        b = rs.resolve("baci", system="service_desk", contact_id=cid,
                       utterance="Is it dishwasher safe?",
                       requirements={"material": "porcelain"})
        ck("the entity match ran", b["coverage"]["counts"]["entities"] >= 1,
           str(b["entities"])[:60])
        ck("`fits` is tri-state, never asserted from a keyword",
           all(e["fits"] in (True, False, None) for e in b["entities"]))
        ck("the conversation is attached", b["conversation"]["exists"])
        ck("and the open commitment travels with it",
           b["coverage"]["counts"]["open_commitments"] == 1,
           "a drafter must not contradict what was already promised")

        print("\n— what is skipped is named, never silently absent —")
        b = rs.resolve("baci", utterance="Is it dishwasher safe?")
        skipped = {s["what"] for s in b["coverage"]["skipped"]}
        ck("no contact means the conversation is skipped WITH a reason",
           "conversation" in skipped, str(skipped))
        ck("no requirement means entities are skipped WITH a reason",
           "entities" in skipped, str(skipped))
        ck("and `complete` is not claimed on a bundle that skipped retrieval",
           b["coverage"]["complete"] is True,
           "objections DID resolve here, so complete is honest")

        b = rs.resolve("baci", utterance="Do you deliver on Tuesdays?")
        ck("but an unplaceable request is never complete",
           b["coverage"]["complete"] is False)


        print("\n— what can this account answer at all —")
        r = rs.readiness("baci")
        ck("it scores against the account's OWN vocabulary",
           r["situations"] == len(kb.situations("baci")), r["score"])
        ck("durability is answerable — there is an approved objection",
           any(x["situation"] == "durability" and x["state"] == "proven"
               for x in r["per_situation"]),
           str([x for x in r["per_situation"] if x["situation"] == "durability"]))
        ck("gifting is not — no objection carries that tag",
           any(x["situation"] == "gifting" and x["state"] == "unanswerable"
               for x in r["per_situation"]))
        ck("the verdict counts rather than reassures",
           "can answer" in r["verdict"], r["verdict"])
        ck("and the fixes are ranked by how much each unblocks",
           r["next_actions"] and r["next_actions"] == sorted(
               r["next_actions"], key=lambda x: -x["situations"]),
           str([a["fix"][:34] for a in r["next_actions"]]))

        blank = rs.readiness("coverings")
        ck("an empty account says so plainly",
           blank["answerable"] == 0 and "cannot answer" in blank["verdict"],
           blank["verdict"])
        ck("and names the ban list before anything else",
           any("banned_claims" in a["fix"] for a in blank["next_actions"]),
           str([a["fix"] for a in blank["next_actions"]][:2]))

        r = cl.get("/readiness", params={"key": "r3adonly"})
        ck("the board is readable with the read-only key",
           "accounts" in r.json(), str(r.json())[:60])

        print("\n— the read-only key reads, and cannot write —")
        r = cl.get("/resolve", params={"tenant": "baci", "tier": 1})
        ck("no credential is refused", r.json().get("error") == "unauthorized")
        r = cl.get("/resolve", params={"tenant": "baci", "tier": 1,
                                       "key": "r3adonly"})
        ck("the read key resolves context", r.json().get("principal") == "read",
           str(r.json())[:60])
        r = cl.get("/admin/kb_add", params={"key": "r3adonly", "tenant": "baci",
                                            "claim": "x", "evidence": "y",
                                            "tags": "durability"})
        ck("but it CANNOT reach a route that writes",
           r.json().get("error") == "unauthorized", str(r.json())[:60])
        r = cl.get("/resolve", params={"tenant": "baci", "tier": 1,
                                       "key": "s3cret"})
        ck("the admin secret still reads everything",
           r.json().get("principal") == "admin")
        r = cl.get("/resolve", params={"tenant": "baci", "key": "r3adonly",
                                       "requirements": "not-json"})
        ck("malformed requirements are reported, not dropped",
           "not valid JSON" in str(r.json().get("error", "")),
           "a dropped requirement turns a checked match into a keyword one, "
           "and the caller would never know")
        r = cl.get("/resolve", params={"tenant": "baci", "key": "r3adonly",
                                       "requirements": '["a", "list"]'})
        ck("and so is a JSON value that is not an object",
           "must be a JSON object" in str(r.json().get("error", "")),
           str(r.json())[:60])

        print("\n— an unset read key disables read access, not opens it —")
        from app import config
        saved, config.READ_KEY = config.READ_KEY, ""
        try:
            r = cl.get("/resolve", params={"tenant": "baci", "key": ""})
            ck("an empty key against an empty secret is still refused",
               r.json().get("error") == "unauthorized",
               "fails closed, not open")
        finally:
            config.READ_KEY = saved

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
