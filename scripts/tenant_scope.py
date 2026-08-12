#!/usr/bin/env python3
"""CLI wrapper. The logic lives in app/tenant_scope.py so the same code is
reachable from the web service (/admin/tenant_scope) — a backfill that only
runs from a laptop never runs against production.

    python3 scripts/tenant_scope.py --report   # what is unattributed
    python3 scripts/tenant_scope.py            # attribute, then report
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, tenant_scope  # noqa: E402


def main() -> int:
    db.init_db()
    if "--report" not in sys.argv:
        filled = tenant_scope.backfill()
        for table, n in sorted(filled.items()):
            print(f"attributed {n:>4} rows in {table}")
        if not filled:
            print("nothing new to attribute")
        print()
    tenant_scope.print_report()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
