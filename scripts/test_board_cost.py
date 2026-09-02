"""Rendering the board is linear in the map, not quadratic.

`attention()` calls `cluster_support()` for every row in the 11-30 band, and
the first cut of `cluster_support` read the whole keyword map itself. On a
600-keyword account where every page sits in that band, one board render
issued 602 full `keyword_targets` scans and took ~10 seconds — and 588 of
those were thrown away by `top=12`. Quadratic in the size of the thing this
feature exists to manage, on the page somebody opens to manage it.

Counted rather than timed: a timing assertion on a shared machine is a flake,
and the property is "how many times does it read the map", which is exact.

Run: python3 scripts/test_board_cost.py
"""
import datetime as dt
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'bc.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, keywords, tenants  # noqa: E402

_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    db.init_db()
    tenants.seed()

    N = 120
    with db.SessionLocal() as s:
        for i in range(N):
            s.add(db.KeywordTarget(
                tenant="baci", phrase=f"phrase {i}", status="published",
                role="support", cluster_key=f"c{i % 6}",
                published_at=db.utcnow() - dt.timedelta(days=90)))
        s.commit()
        for i in range(N):
            s.add(db.KeywordReading(tenant="baci", phrase=f"phrase {i}",
                                    position=18.0, source="gsc"))
        s.commit()

    rows = keywords.attention("baci")
    ck("every row is in the band this is about",
       rows and all(r["action"] == "supports" for r in rows),
       f"{len(rows)} row(s) — without this the count below proves nothing, "
       f"because `cluster_support` is only called for that action")

    calls = {"n": 0}
    real = keywords.targets

    def _counting(*a, **k):
        calls["n"] += 1
        return real(*a, **k)

    keywords.targets = _counting
    try:
        keywords.attention("baci")
    finally:
        keywords.targets = real

    ck("the map is read a fixed number of times, not once per row",
       calls["n"] <= 2,
       f"{calls['n']} read(s) for {len(rows)} listed row(s) of {N} keywords — "
       f"one per row is 602 scans and ~10s on a real account, and `top` "
       f"throws most of them away")

    print()
    print("PASS" if not _fail else f"FAILED: {len(_fail)}")
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
