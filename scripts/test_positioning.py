"""A position is true of a range, not of the world.

Owner, 2026-08-23, on a Baci Milano send that was otherwise the best yet:

    "That's the quiet trick of a well-considered table. It doesn't announce
    itself."

    "The issue with this is that even though this positioning is true of the
    Joke collection, as a brand Baci Milano has many maximalist designs so we
    dont want to sell the idea of a good evening as one where the table doesn't
    take too much attention because the next email might say the opposite."

Nothing in that email was false. It was not incoherent — one subject, one
product, proof in scope. It argued a THEORY OF TASTE built out of one range,
and the range next door argues the opposite, so the brand would be caught on
both sides of its own aesthetic.

THE ROOT CAUSE IS IN THE DATA LAYER, and it is one column: `positioning` exists
on `KbBrand` and nowhere else. One brand, one position. There was no way to
record that Joke is minimal and Baroque & Rock is maximal, so a drafter handed
one brand positioning and a minimalist product generalised — reasonably.

Three layers, pinned here:

  1. POSITIONING IS A PROOF KIND, so it is scoped, reviewed, and arrives with
     what its scope permits — the same machinery every other claim rides.
  2. THE BUNDLE CARRIES THE DISAGREEMENT. A drafter that is told which ranges
     hold which positions has the fact it was missing; told abstractly to
     "avoid generalising", it has only advice.
  3. A LINT CATCHES THE SHAPE, advisory on purpose. It cannot know whether the
     brand holds the position — it knows the sentence claims it of a CATEGORY
     rather than of the thing being sold.

Run: python3 scripts/test_positioning.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'pos.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, email_craft, kb, resolve, tenants  # noqa: E402

_fails = []

# The email the owner quoted, near enough verbatim.
SEND = ("It started with a Sunday lunch that ran four hours longer than anyone "
        "planned. Nobody checked their phone. The plates were simple — white, "
        "clean, nothing competing for attention. "
        "That's the quiet trick of a well-considered table. It doesn't "
        "announce itself. "
        "The Joke 18-Piece White Melamine Set is built for exactly that. "
        "Eighteen pieces. One decision. Done.")


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fails.append(label)


def main() -> int:
    db.init_db()
    tenants.seed()

    print("— the data layer can hold two positions at once —")
    kb.add_entity("baci", "collection", "joke", "Joke",
                  description="Minimal white melamine.")
    kb.add_entity("baci", "collection", "baroque", "Baroque & Rock",
                  description="Maximalist pattern and colour.")
    kb.add_claim("baci", "The Joke range is minimal: white, clean, nothing "
                 "competing for attention.", "brand brief", [], origin="human",
                 status="active", entity_key="joke", proof_type="positioning")
    kb.add_claim("baci", "Baroque & Rock is maximalist — pattern, colour, "
                 "presence at the table.", "brand brief", [], origin="human",
                 status="active", entity_key="baroque",
                 proof_type="positioning")

    # A BRAND-WIDE position too, because the distinction is the whole point:
    # "Italian-designed" IS true of everything, and must not be reported as a
    # thing the ranges disagree about. Without this row in the fixture,
    # relaxing the scope filter changes nothing and the check passes for the
    # wrong reason — which is exactly what sabotage.py reported first time.
    kb.add_claim("baci", "Baci Milano is a design house based in Milan.",
                 "brand brief", [], origin="human", status="active",
                 proof_type="positioning")

    contested = kb.contested_positioning("baci")
    ck("both range positions are recorded, scoped to their ranges",
       {c.entity_key for c in contested} == {"joke", "baroque"},
       str([(c.entity_key, c.claim[:24]) for c in contested]))
    ck("…and the brand-wide one is NOT among them — the whole point is that a "
       "range position is not a brand position",
       all((c.entity_key or "") for c in contested)
       and not any("design house" in c.claim for c in contested),
       str([c.claim[:30] for c in contested]))

    print("\n— what the kind PERMITS rides with it —")
    rule = kb.usage_rule("positioning")
    ck("positioning is a proof kind", bool(rule))
    ck("…and its rule forbids the generalisation, in words a drafter can obey",
       "never" in rule.lower() and "taste" in rule.lower(), rule[:80])
    ck("it is not verbatim-only like a testimonial — a position may be "
       "rewritten, it may not be widened",
       "positioning" not in kb.VERBATIM_ONLY)

    print("\n— the bundle carries the disagreement to every generator —")
    b = resolve.resolve("baci", entity_key="joke", tier=3)
    got = b.get("contested_positioning") or []
    ck("a bundle for the minimal range knows the maximal one exists",
       {c["scope"] for c in got} == {"joke", "baroque"},
       str([(c["scope"], c["claim"][:20]) for c in got]))
    ck("…and the scoped claim arrives with its usage rule attached",
       any("never" in (c.get("usage_rule") or "").lower()
           for c in (b.get("claims") or []) if c.get("scope") == "joke"),
       str([c.get("usage_rule", "")[:40] for c in (b.get("claims") or [])]))

    print("\n— the lint catches the shape, on the owner's own email —")
    hits = email_craft.generalisations(SEND)
    ck("the theory-of-taste sentence is caught",
       any("well-considered table" in h for h in hits), str(hits))
    ck("…and its follow-on", any("announce itself" in h for h in hits), str(hits))
    ck("the product sentence is NOT caught — describing what you sell is the "
       "whole job",
       not any("Melamine" in h for h in hits), str(hits))

    print("\n— a sentence that NAMES what is being sold is a description —")
    named = email_craft.generalisations(
        "A well-considered Joke set doesn't announce itself.", "Joke set")
    ck("naming the subject exempts it", not named, str(named))
    plain = email_craft.generalisations(
        "The Joke set is minimal, white and dishwasher safe.", "Joke set")
    ck("plain product copy is never touched", not plain, str(plain))

    print("\n— it advises rather than blocks —")
    found = email_craft.review(subject="Six that do not shatter", body=SEND,
                               featured="Joke 18-Piece Set")
    mine = [f for f in found if f["rule"] == "generalised_positioning"]
    ck("it is reported", bool(mine))
    ck("…as a NUDGE, because code cannot know whether the brand holds the "
       "position — only that the sentence claims it of a category",
       all(f["severity"] == "nudge" for f in mine),
       str([f["severity"] for f in mine]))
    ck("…and the fix names what to do instead",
       any("by name" in f["fix"] for f in mine), str([f["fix"][:40] for f in mine]))

    print("\n" + ("all checks passed" if not _fails
                  else f"{len(_fails)} FAILED: " + "; ".join(_fails)))
    return 1 if _fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
