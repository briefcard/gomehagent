#!/usr/bin/env python3
"""Inspect what the brief assembler decides, before anything is drafted.

Two modes, because they prove different things:

  RULES MODE (no API key needed) — exercises diagnose -> select -> decide, the
  deterministic majority of the pipeline. This is where "generic vs specific"
  is actually won or lost.

      python3 scripts/brief_demo.py --demo
      python3 scripts/brief_demo.py --say "our ads stopped working and margin is thin" \\
                                    --type ecom_inventory
      python3 scripts/brief_demo.py --say "we need more corporate bookings" \\
                                    --type local_venue --stage referral_intro

  LIVE MODE (needs ANTHROPIC_API_KEY) — full chain including extraction from a
  real email and enrichment from the prospect's own site.

      python3 scripts/brief_demo.py --email prospect.txt
      pbpaste | python3 scripts/brief_demo.py

Uses a local sqlite file and seeds the agency KB on first run. Touches nothing
in production.
"""
import argparse
import json
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite:///brief_test.db")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import brief, db, kb  # noqa: E402

DEMO = [
    ("E-comm — ads degraded, margin thin", "ecom_inventory", "first_contact",
     "Our Meta ads worked for a year then stopped, and our margin is getting thin", ""),
    ("Venue — referral, wants bookings", "local_venue", "referral_intro",
     "We need more corporate bookings", ""),
    ("Coaching — deliverability broken", "digital_products", "first_contact",
     "Our emails are landing in spam and the last launch flopped",
     "You're one person, can you really handle this?"),
    ("B2B — invisible in search", "b2b_spec", "first_contact",
     "Nobody finds us, we don't rank for anything in our category", ""),
    ("E-comm — scared to raise prices", "ecom_inventory", "follow_up",
     "We know we're underpriced but raising prices feels too risky", ""),
]


def show(b: brief.Brief, label: str = "") -> None:
    if label:
        print(f"\n\033[1m{label}\033[0m")
    if b.blocked:
        print(f"  BLOCKED — missing: {', '.join(b.missing)}")
        return
    print(f"  situations : {', '.join(b.situations) or '(none)'}")
    print(f"  constraint : {b.constraint}")
    for c in b.claims:
        print(f"  proof      : {c['evidence']}")
        print(f"               ↳ {c['source']}")
    if b.objection:
        print(f"  pre-empt   : {b.objection['objection']}")
    print(f"  ask        : {b.ask}" + (f"  →  {b.offer['key']}" if b.offer else ""))
    if b.enrichment:
        print(f"  enrichment : {json.dumps(b.enrichment)}")
    if b.sources_failed:
        print(f"  not checked: {', '.join(b.sources_failed)}")


def rules_brief(say: str, audience: str, stage: str, objection: str) -> brief.Brief:
    """Skip extraction; feed the assembler a hand-built classification."""
    payload = {
        "contact_name": "Test", "company": "Test Co", "domain": "",
        "source": "inbound_form", "stage": stage, "audience_key": audience,
        "verbatim_ask": say, "voiced_objection": objection,
        "keywords": say.split(),
    }
    return brief.assemble("agency", say, "test@example.com",
                          model_fn=lambda s, u: json.dumps(payload))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--demo", action="store_true", help="run all preset scenarios")
    p.add_argument("--say", help="what the prospect said")
    p.add_argument("--type", default="", help="ecom_inventory|digital_products|local_venue|b2b_spec")
    p.add_argument("--stage", default="first_contact")
    p.add_argument("--objection", default="")
    p.add_argument("--email", help="path to a real email (needs ANTHROPIC_API_KEY)")
    p.add_argument("--reseed", action="store_true")
    a = p.parse_args()

    db.init_db()
    r = kb.seed_agency(force=a.reseed)
    c = kb.completeness("agency")
    print(f"KB: {c['counts']} — {r['status']}")

    if a.demo:
        for label, aud, stage, say, obj in DEMO:
            show(rules_brief(say, aud, stage, obj), label)
        print("\nRules mode: no model was called. Extraction is the only stage skipped.")
        return

    if a.say:
        show(rules_brief(a.say, a.type, a.stage, a.objection), "Your scenario")
        return

    text = open(a.email).read() if a.email else (
        sys.stdin.read() if not sys.stdin.isatty() else "")
    if not text.strip():
        p.print_help()
        return
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("\nLIVE mode needs ANTHROPIC_API_KEY. Either export it, or use\n"
              "  --demo / --say  to test the deterministic stages without one.")
        return
    show(brief.assemble("agency", text, ""), "Live brief")


if __name__ == "__main__":
    main()
