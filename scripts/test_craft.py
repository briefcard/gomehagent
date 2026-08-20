"""What one account taught us, reaching a similar one — and never more than that.

This is the only thing in the system that crosses the tenant boundary, so it is
built with the narrowest licence the owner asked for: *low priority learning,
kept as secure as possible*. Three properties, and this file exists to hold
them.

**It shapes HOW, never WHAT.** A claim is a fact about a client's business and
carries a `claim_id`; a lesson is technique and can never become a citation. A
leak of technique is embarrassing. A leak of one client's facts into another
client's output is what the whole architecture exists to prevent.

**Reach is by business model.** A lesson from a venue must not arrive at a shop.

**The guard refuses, it does not scrub.** Rewriting a lesson to slip it past a
filter is not something code should do on somebody's behalf.

    python3 scripts/test_craft.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'cr.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import craft, db, kb, resolve as rs, tenants, web  # noqa: E402

_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    db.init_db()
    tenants.seed()
    kb.ensure_brand("baci", "Baci Milano USA")
    kb.ensure_brand("ironside", "Miami Ironside")
    kb.add_banned("baci", "hand-decorated")
    kb.add_situation("baci", "material_question", [["material"]], "what it is made of")
    kb.add_entity("baci", "product", "aqua-jug", "Aqua Pitcher",
                  origin="store_sync", source="shopify")

    print("— the guard refuses what identifies an account —")
    attempts = {
        "Baci Milano USA replies fastest when you lead with the number":
            "the account name",
        "Mention the Aqua Pitcher early — it converts":
            "a product name",
        "Chase them at jane@bacimilanousa.com if they go quiet":
            "an email address",
        "Point them at bacimilanousa.com/collections":
            "a domain",
        "Reference order 1043928 when apologising":
            "a long number",
    }
    for text, why in attempts.items():
        r = craft.propose(text)
        ck(f"  refuses {why}", not r["ok"], r.get("error", "")[:70])
        ck(f"    and names what it found",
           bool(r.get("error")) and "names:" in r["error"], r.get("error", "")[:60])

    print("\n— and it refuses rather than rewriting —")
    r = craft.propose("Lead with the number, like Baci Milano USA does")
    ck("nothing is stored on a refusal",
       not r["ok"] and not craft.pending(), str(len(craft.pending())))
    ck("  and the message says to reword it as technique",
       "technique" in r.get("error", ""), r.get("error", "")[:80])

    print("\n— technique with nobody's name in it is accepted —")
    good = craft.propose(
        "When someone asks what a piece is made of, answer with the material "
        "first and the reassurance second — the reverse reads as evasive.",
        business_model="ecom_inventory", situations=["material_question"],
        basis="fewer follow-up questions", learned_from="eien")
    ck("it is proposed", good["ok"], str(good))
    ck("  but NOT live until a person approves",
       not craft.for_account("baci"), "proposed is not approved")

    print("\n— a person approves, and only then does it reach anyone —")
    craft.approve(good["id"])
    reach = craft.for_account("baci", ["material_question"])
    ck("it reaches a matching account", len(reach) == 1, str(reach))
    ck("  and does NOT reach a different kind of business",
       not craft.for_account("ironside", ["material_question"]),
       "a lesson from a shop must not arrive at a venue")

    print("\n— it is the weakest thing in the brief, and says so —")
    block = craft.block("baci", ["material_question"])
    ck("the block is labelled as borrowed", "worked elsewhere" in block.lower())
    ck("  as the weakest input", "weakest" in block.lower(), block[:80])
    ck("  as technique rather than fact",
       "never as something to assert" in block or "not fact" in block)
    ck("  and it never names where it came from",
       "eien" not in block.lower(),
       "audit is for the owner; the prompt must not carry it")

    print("\n— it arrives in the bundle, below the account's own knowledge —")
    b = rs.resolve("baci", system="inbox_triage", utterance="what material is it?")
    ck("the bundle carries it", bool(b.get("craft")), str(b.get("craft"))[:60])
    ck("  and it can never be cited",
       all("claim_id" not in str(c) for c in [b.get("craft")]),
       "a claim is a fact about THIS client; craft is not")
    from app import grounding
    text = grounding.render(b)
    ck("  it renders after the account's own claims",
       "WHAT THIS ACCOUNT KNOWS" not in text
       or text.index("APPROVED CLAIMS") < text.index("worked elsewhere"),
       "borrowed technique must not outrank approved proof")

    print("\n— an account added later re-triggers the guard —")
    # A name that was harmless when the lesson was written may identify a
    # client onboarded since, so approval re-checks rather than trusting the
    # check made at proposal time.
    # The realistic version: a lesson uses an ordinary word, and a client is
    # later onboarded whose brand IS that word. Nothing about the lesson
    # changed; the world did.
    later = craft.propose(
        "Photograph the piece on a stonehouse table rather than a white sweep.")
    ck("it proposes cleanly", later["ok"], str(later)[:70])
    with db.SessionLocal() as s:
        s.add(db.Tenant(key="sthouse", name="Stonehouse",
                        business_model="b2b_spec"))
        s.commit()
    out = craft.approve(later["id"])
    ck("  approval refuses once that name exists",
       not out["ok"], str(out)[:90])
    ck("    naming what it now collides with",
       "Stonehouse" in str(out.get("error", "")), str(out.get("error"))[:80])
    ck("  and it is retired rather than left pending",
       not any(p["id"] == later["id"] for p in craft.pending()))

    print("\n— the console surfaces it, scoped —")
    c = TestClient(web.app)
    q = c.get("/admin/craft?key=s3cret&tenant=baci").json()
    ck("the owner can see what would reach an account",
       len(q.get("would_reach", [])) == 1, str(q.get("would_reach")))
    ck("  and what is waiting on them", "pending" in q)
    anon = TestClient(web.app)
    r = anon.get("/admin/craft")
    ck("unauthorised cannot read it",
       r.status_code >= 400 or "error" in r.json(), str(r.status_code))
    bad = c.get("/admin/craft_add?key=s3cret&lesson=Ask+for+Baci+Milano+USA+by+name").json()
    ck("the route refuses a leak too", not bad["ok"], bad.get("error", "")[:60])

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
