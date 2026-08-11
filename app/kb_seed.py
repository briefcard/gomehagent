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

from . import db, kb


def _claim(tenant: str, *args, **kw) -> None:
    """Add a claim, skipping one that already exists, and refuse to continue
    if a new one did not land.

    Two failure modes, both found by running this:

    1. The first run lost three claims silently — they carried tags from the
       shared vocabulary that the tenants' own vocabularies do not contain,
       `add_claim` correctly refused them, and the return value went nowhere.
       A seed that drops rows quietly is worse than one that crashes.

    2. Re-running duplicated every claim (baci 3 -> 6, ironside 1 -> 2). The
       tenant seeds are guarded by "does this tenant have a brand row", but
       claims are append-only, so a second run stacked a second copy of the
       whole proof library. Duplicated proof is worse than missing proof: the
       selector ranks by situation overlap, so two identical claims occupy
       both slots in a two-claim email and crowd out the second-best match.
    """
    text = args[0] if args else kw.get("claim", "")
    if any((c.claim or "").strip().lower() == str(text).strip().lower()
           for c in kb.claims(tenant)):
        return  # already present — re-running the seed must be a no-op
    before = len(kb.claims(tenant))
    msg = kb.add_claim(tenant, *args, **kw)
    if len(kb.claims(tenant)) == before:
        raise SystemExit(f"seed: claim REJECTED for {tenant} — {msg}")


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
        # Selection reaches the catalogue by matching what they said against
        # the product's own words. No numeric requirement applies to tableware.
        selection={"primary_type": "product", "modes": [{"mode": "keyword"}]},
        next_steps={
            "first_contact": {"ask": "point them at the piece that fits the occasion"},
            "follow_up": {"ask": "one specific piece, not the catalogue"},
            "default": {"ask": "answer the question, then name one piece"},
        },
    )

    # Baci's own diagnostic vocabulary. The shared set is agency-B2B language;
    # none of it fires on "wedding gift, something colourful".
    for tag, pats, desc in [
        ("gifting", [["gift"], ["present"], ["for my"], ["for her"], ["for a friend"]],
         "buying for someone else — the piece has to say something about them"),
        ("occasion_hosting", [["wedding"], ["dinner party"], ["hosting"],
                              ["housewarming"], ["holiday"], ["entertaining"]],
         "buying for an event they are hosting"),
        ("collector", [["collection"], ["add to"], ["complete the set"], ["matching"]],
         "already owns pieces and is extending the set"),
        ("replacement_reorder", [["broke"], ["broken"], ["replace"], ["chipped"],
                                 ["another one"]],
         "replacing something they already had"),
        ("quality_doubt", [["quality"], ["worth it"], ["durable"], ["dishwasher"],
                           ["chip"], ["how well"]],
         "wants reassurance the piece is worth the price"),
    ]:
        kb.add_situation("baci", tag, pats, desc, kind="who_they_are")

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

    _claim(
        "baci",
        "Designed in Milan by the Italian design house Baci Milano",
        "Italian design brand, Milan",
        ["gifting", "collector"],
        proof_type="certification",
        source="Brand origin — Italian DESIGN, not Italian manufacture")
    _claim(
        "baci",
        "Specified by Four Seasons and the Ritz-Carlton Yacht Collection",
        "Placements at Four Seasons and Ritz-Carlton Yacht Collection",
        ["quality_doubt", "collector"],
        proof_type="case_study",
        source="US market entry, established 2026")
    _claim(
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
        # A venue enquiry states a headcount. Which capacity it is measured
        # against depends on whether they said seated or standing — those are
        # different rooms, and answering with the wrong one loses the booking.
        selection={
            "primary_type": "space",
            "modes": [{"mode": "capacity_fit", "requirement": "headcount",
                       "attributes": {"seated": "seated_capacity",
                                      "default": "standing_capacity"}},
                      {"mode": "keyword"}],
        },
        next_steps={
            "first_contact": {"ask": "a walkthrough — the room decides it, not the deck"},
            "follow_up": {"ask": "hold the date while they decide"},
            "default": {"ask": "a walkthrough"},
        },
    )

    for tag, pats, desc in [
        ("venue_enquiry", [["venue"], ["space"], ["room"], ["book"], ["host"],
                           ["event"], ["guests"]],
         "looking for a room for a specific event"),
        ("capacity_fit", [["guests"], ["people"], ["headcount"], ["pax"],
                          ["attendees"], ["seated"], ["standing"]],
         "the headcount decides which spaces are even possible"),
        ("production_need", [["av"], ["stage"], ["led"], ["production"],
                             ["load-in"], ["load in"], ["rigging"]],
         "the technical requirement will decide the space"),
        ("date_pressure", [["march"], ["next month"], ["asap"], ["short notice"],
                           ["available on"]],
         "a date is set and the venue is the last unbooked piece"),
    ]:
        kb.add_situation("ironside", tag, pats, desc, kind="problem")

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

    _claim(
        "ironside",
        "Eight distinct spaces on one campus, from 60 to 400 guests",
        "Lounge 60 · Glassbox 250 · Gallery 62 300 · Event Space and Ironsbend 400",
        ["venue_enquiry", "capacity_fit"],
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
        selection={"primary_type": "product", "modes": [{"mode": "keyword"}]},
        next_steps={"default": {"ask": "the product that matches what they described"}},
    )
    for tag, pats, desc in [
        ("wellness_routine", [["daily"], ["routine"], ["stack"], ["regimen"],
                              ["take it with"]],
         "fitting a product into an existing routine"),
        ("subscription_lapse", [["cancel"], ["pause"], ["ran out"], ["reorder"],
                                ["subscription"]],
         "an existing customer at the point of lapsing"),
        ("ingredient_question", [["ingredient"], ["dosage"], ["how much"],
                                 ["contains"], ["allergen"]],
         "wants a factual answer about what is in it"),
    ]:
        kb.add_situation("eien", tag, pats, desc, kind="problem")
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
        selection={"primary_type": "product", "modes": [{"mode": "keyword"}]},
        next_steps={
            "first_contact": {"ask": "a sample to the studio"},
            "default": {"ask": "the spec sheet and a sample"},
        },
    )
    for tag, pats, desc in [
        ("trade_specification", [["spec"], ["specify"], ["submittal"], ["a&d"],
                                 ["architect"], ["designer"]],
         "a project reaching material selection"),
        ("sample_request", [["sample"], ["swatch"], ["send me"], ["chip"]],
         "wants material in hand before specifying"),
        ("dimension_check", [["size"], ["dimension"], ["thickness"], ["slab"],
                             ["square feet"], ["sq ft"]],
         "a dimension decides whether it works — a wrong number loses the job"),
    ]:
        kb.add_situation("coverings", tag, pats, desc, kind="problem")
    kb.add_audience(
        "coverings", "specifier", "Architect, designer or specifier",
        ["a wrong dimension loses the job",
         "samples that go nowhere",
         "long cycles with no visibility"],
        ["spec", "A&D", "sample", "slab", "finish", "submittal", "project"],
        buying_trigger="A project reaching material selection",
        decision_timeline="1–3 months")


def backfill() -> None:
    """Fill columns that did not exist when a tenant was first seeded.

    Auto-migration adds `selection` and `next_steps` to the table but cannot
    know their values, so a brand row seeded earlier comes back with both
    empty. For the agency that means the decision layer has nothing to propose
    and every brief returns a blank ask — a silent regression that only shows
    up in the output, which is the worst place to find one.
    """
    b = kb.brand("agency")
    if b and not (b.next_steps or {}):
        kb.set_brand(
            "agency",
            selection={"primary_type": "offer", "modes": [{"mode": "keyword"}]},
            next_steps={
                "referral_intro": {"entity_key": "fractional_cmo",
                                   "ask": "a 25-minute call this week"},
                "follow_up": {"entity_key": "diagnostic",
                              "ask": "pick the thread back up with one specific next step"},
                "dormant": {"entity_key": "diagnostic",
                            "ask": "pick the thread back up with one specific next step"},
                "first_contact": {"entity_key": "diagnostic",
                                  "ask": "the paid diagnostic"},
                "default": {"entity_key": "diagnostic", "ask": "the paid diagnostic"},
            })
        print("backfilled agency selection + next_steps")


def status() -> dict:
    """Same information as report(), shaped for an HTTP response."""
    out = {}
    for t in ("agency", "baci", "eien", "coverings", "ironside"):
        c = kb.completeness(t)
        out[t] = {"ready": c["ready"], "counts": c["counts"],
                  "open_questions": [g["q"] for g in kb.gaps(t)]}
    return out


def seed_all() -> dict:
    """Run every tenant seed. Idempotent — the individual seeds no-op when the
    rows already exist. Returns the resulting status rather than printing."""
    backfill()
    done = []
    for name, fn in (("baci", seed_baci), ("ironside", seed_ironside),
                     ("eien", seed_eien), ("coverings", seed_coverings)):
        fn()
        done.append(name)
    return {"seeded": done, "status": status(),
            "warning": "Eien's banned claims are a conservative default — review them."}


def report() -> None:
    for t in ("agency", "baci", "eien", "coverings", "ironside"):
        c = kb.completeness(t)
        g = kb.gaps(t)
        mark = "READY" if c["ready"] else "needs " + str(len(g))
        print(f"\n{t:10s} {mark:12s} {c['counts']}")
        for step in g:
            print(f"           · {step['q']}")
