#!/usr/bin/env python3
"""CLI wrapper. The data and seed logic live in app/kb_seed.py so the same
code is reachable from the web service (/admin/seed_kb) — a seed that only
runs from a laptop never runs against production.

    python3 scripts/seed_kb.py            # seed what's missing
    python3 scripts/seed_kb.py --report   # show what each account still needs
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, kb_seed  # noqa: E402


def main() -> int:
    db.init_db()
    if "--report" in sys.argv:
        kb_seed.report()
        return 0
    r = kb_seed.seed_all()
    for name in r["seeded"]:
        print(f"seeded {name}")
    print()
    kb_seed.report()
    print(f"\n{r['warning']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
