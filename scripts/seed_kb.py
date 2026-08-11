"""Seed the knowledge base for the four accounts that have none.

Rule this file obeys: **nothing here is invented.** Every row carries the source
it came from, and where a field was never established it is left empty so the
intake asks for it rather than the pipeline guessing. A thin KB that knows it is
thin produces a refusal; a KB filled with plausible-sounding guesses produces a
wrong email to a real client.

One deliberate exception, marked inline: Eien's banned claims are a CONSERVATIVE
DEFAULT, not an established fact. Over-banning is fail-safe — the validator
refuses a draft it could have allowed. Under-banning a supplement brand with a
GLP-1 product is the highest-risk gap in the portfolio. Gomeh must review it, but
an empty list was not a responsible place to leave it.

    python3 scripts/seed_kb.py            # seed what's missing
    python3 scripts/seed_kb.py --report   # show what each account still needs
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, kb  # noqa: E402


# ---------------------------------------------------------------------------
# BACI MILANO USA
# Sources: brand-origin memory (2026-06-16/17), no-customization memory,
# bundle-cap rule (2026-07-14), Meta ads analysis (Jul 2026, account
# 949335500698690), US-market-entry placements.
# ---------------------------------------------------------------------------

def seed_baci() -> None:
    kb.set_brand(
        "baci",
        display_name="Baci Milano USA",
        positioning="The Italian design house Baci Milano, brought to the US "
                    "market — colourful, pattern-led tableware and glassware for "
                    "people who host.",
    )

    # Hard compliance boundary. Every phrase below is a real, established rule
    # with a documented reason — origin and production-method claims are an
    # FTC/false-advertising exposure, and physical customisation is operationally
    # off the table.
    for phrase in [
        # country of origin — the brand is Italian-DESIGNED, mass-manufactured
        "made in Italy", "made in italy", "from Italy", "Italian-made",
        "imported from Italy",
        # production method — not handcraft
        "handmade", "hand-made", "hand crafted", "hand-crafted", "handcrafted",
        "hand-painted", "hand painted", "artisan", "artisanal", "craftsmanship",
        # physical customisation is not offered
        "monogram", "monogrammed", "engraved", "engraving", "made-to-order",
        "made to order", "custom-made", "bespoke",
        # outcome promises
        "guarantee", "guaranteed",
    ]:
        kb.add_banned("baci", phrase)

    # Buyer segments — from six months of Meta delivery and Shopify sales,
    # not from a persona workshop.
    kb.add_audience(
        "baci", "core_hostess", "Women 35–44 — the core buyer",
        ["generic tableware that says nothing about her",
         "wants a gift that feels chosen, not bought",
         "hosting for people whose opinion she cares about"],
        ["set", "sign", "gift", "hosting", "table", "colour"],
        buying_trigger="A birthday, a housewarming, or her own table feeling tired",
        decision_timeline="days")
    kb.add_audience(
        "baci", "established_host", "Women 45–54 — efficient and under-funded",
        ["already owns plenty; needs a reason for another set",
         "quality anxiety when buying colourful pieces"],
        ["quality", "dishwasher", "everyday", "collection"],
        buying_trigger="Replacing a broken piece, or a milestone gift",
        decision_timeline="days")
    kb.add_audience(
        "baci", "price_led", "Women 25–34 — volume, price-sensitive",
        ["wants the look at a reachable price", "buys into a bundle over a single piece"],
        ["deal", "bundle", "starter", "affordable"],
        buying_trigger="A sale, or a first apartment",
        decision_timeline="same day")

    kb.add_claim(
        "baci",
        "Designed in Milan by the Italian design house Baci Milano",
        "Italian design brand, Milan",
        ["gifting", "collector"],
        proof_type="certification",
        source="Brand origin — Italian DESIGN, not Italian manufacture")
    kb.add_claim(
        "baci",
        "Specified by Four Seasons and the Ritz-Carlton Yacht Collection",
        "Placements at Four Seasons and Ritz-Carlton Yacht Collection",
        ["trade_specification", "collector"],
        proof_type="case_study",
        source="US market entry, established 2026")
    kb.add_claim(
        "baci",
        "The Zodiac Vibe cup is sold by sign — the piece is chosen for the person",
        "Best-selling line; Cancer, Leo and Gemini reached 100/100/91% sell-through in season",
        ["gifting", "occasion_hosting"],
        proof_type="data",
        source="Shopify sell-through + Meta delivery, Jul 2026")

    kb.add_entity("baci", "product", "zodiac-vibe-cup", "Zodiac Vibe cup",
                  description="Sold per zodiac sign. The hero SKU of the catalogue.",
                  price="$65", source="Shopify catalogue, verified Jul 2026")

    # Standing commercial rule — the owner's, dated and explicit.
    kb.set_brand("baci", approval_policy={
        "requires_signoff": ["outbound_email", "campaign", "bundle_pricing"],
        "auto_publish": [],
        "rules": ["A bundle is never more than 10% off the summed retail of its "
                  "components (owner rule, 2026-07-14).",
                  "All tracking must be consent-gated through Shopify's Customer "
                  "Privacy API — open CIPA/pixel demand, litigation hold in effect."],
    })


# ---------------------------------------------------------------------------
# MIAMI IRONSIDE
# Sources: venue specs read from the live pages 2026-06-18 via the Chrome
# extension, with the team's corrections applied to Glassbox and Outdoor Stage.
# ---------------------------------------------------------------------------

_VENUES = [
    ("glassbox", "Glassbox", 250, 200, "4,000 sq ft",
     "Glass-walled event space."),
    ("lemon-grove", "Lemon Grove", 200, None, "open-air",
     "Open-air garden setting, catering-ready."),
    ("event-space", "Event Space", 400, 300, "10,000 sq ft",
     "The largest indoor room on the campus."),
    ("lounge", "Lounge", 60, 40, "1,500 sq ft",
     "Intimate room for receptions and breakouts."),
    ("gallery-62", "Gallery 62", 300, 200, "4,500 sq ft",
     "Gallery space suited to exhibitions and seated dinners."),
    ("ironsbend", "Ironsbend", 400, 300, "10,000 sq ft",
     "Two bays; the most configurable space on the campus."),
    ("outdoor-stage", "Outdoor Stage", 150, 80, "1,500 sq ft",
     "Outdoor performance and presentation setting."),
    ("virtual-set", "Virtual Set", None, None, "",
     "LED walls, lighting and an AV team. No seated capacity — a production space."),
]


def seed_ironside() -> None:
    kb.set_brand(
        "ironside",
        display_name="Miami Ironside",
        positioning="A design-district campus of eight event spaces in Miami, "
                    "from a 60-person lounge to a 10,000 sq ft hall, with "
                    "production, catering and parking on site.",
    )

    # The system must keep refusing to quote until a rate card exists. These
    # phrases are how an invented quote would actually surface in a draft.
    for phrase in ["starting at", "per person", "our rate", "the price is",
                   "all-inclusive package", "we can do it for"]:
        kb.add_banned("ironside", phrase)

    for key, name, standing, seated, size, desc in _VENUES:
        attrs = {"size": size} if size else {}
        if standing:
            attrs["standing_capacity"] = standing
        if seated:
            attrs["seated_capacity"] = seated
        kb.add_entity("ironside", "space", key, name, description=desc,
                      attributes=attrs,
                      source="Live venue pages, read 2026-06-18 (team corrections applied)")

    kb.add_audience(
        "ironside", "corporate_planner", "Corporate event planner or agency producer",
        ["needs a room that fits an exact headcount",
         "load-in, power and AV decide the venue before aesthetics",
         "enquiries that go unanswered for days"],
        ["headcount", "load-in", "breakout", "AV", "walkthrough", "site visit"],
        buying_trigger="A date is set and the venue is the last unbooked piece",
        decision_timeline="2–8 weeks")

    kb.add_claim(
        "ironside",
        "Eight distinct spaces on one campus, from 60 to 400 guests",
        "Lounge 60 · Glassbox 250 · Gallery 62 300 · Event Space and Ironsbend 400",
        ["venue_enquiry", "capacity_fit", "local_venue"],
        proof_type="spec",
        source="Live venue pages, read 2026-06-18")


# ---------------------------------------------------------------------------
# EIEN HEALTH
# The banned list below is a CONSERVATIVE DEFAULT, not an established fact —
# see the module docstring. Everything else is left empty on purpose.
# ---------------------------------------------------------------------------

def seed_eien() -> None:
    kb.set_brand(
        "eien",
        display_name="Eien Health",
        positioning="",  # never established — intake will ask
    )
    for phrase in [
        # disease claims — the line between a supplement and an unapproved drug
        "cure", "cures", "treat", "treats", "prevent", "prevents",
        "diagnose", "reverses", "eliminates", "heals",
        # regulatory misstatements
        "FDA approved", "FDA-approved", "clinically proven", "doctor recommended",
        # outcome promises
        "guaranteed", "guarantee", "lose weight fast", "no side effects",
        "miracle", "risk-free",
    ]:
        kb.add_banned("eien", phrase)


# ---------------------------------------------------------------------------
# COVERINGS ETC
# Little is established beyond the commercial model. Left thin on purpose.
# ---------------------------------------------------------------------------

def seed_coverings() -> None:
    kb.set_brand(
        "coverings",
        display_name="Coverings Etc",
        positioning="B2B surfacing and materials sold into architecture, design "
                    "and construction — specification sales, not retail.",
    )
    kb.add_audience(
        "coverings", "specifier", "Architect, designer or specifier",
        ["a wrong dimension loses the job",
         "samples that go nowhere",
         "long cycles with no visibility"],
        ["spec", "A&D", "sample", "slab", "finish", "submittal", "project"],
        buying_trigger="A project reaching material selection",
        decision_timeline="1–3 months")


def report() -> None:
    for t in ("agency", "baci", "eien", "coverings", "ironside"):
        c = kb.completeness(t)
        g = kb.gaps(t)
        mark = "READY" if c["ready"] else "needs " + str(len(g))
        print(f"\n{t:10s} {mark:12s} {c['counts']}")
        for step in g:
            print(f"           · {step['q']}")


def main() -> int:
    db.init_db()
    if "--report" in sys.argv:
        report()
        return 0
    for name, fn in (("baci", seed_baci), ("ironside", seed_ironside),
                     ("eien", seed_eien), ("coverings", seed_coverings)):
        fn()
        print(f"seeded {name}")
    print()
    report()
    print("\nEien's banned claims are a conservative default — review them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
