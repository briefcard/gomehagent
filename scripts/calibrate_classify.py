"""Are the classifier's floors set right for THIS account's claims?

`kb.suggest_tags` refuses to place a tag below two floors — MIN_SHARED_WORDS
and MIN_LEARNED_SCORE. Those numbers were reasoned from the scoring arithmetic
and two constructed sentences. They have never been checked against a real
claim, and the two failure modes point in opposite directions:

    floor too LOW   a weak overlap places a tag nobody stands behind, and a
                    service desk answers with the wrong objection, confidently
    floor too HIGH  the classifier refuses claims it used to place, every
                    harvest lands untagged, and the review queue doubles

This prints `kb.calibration()` — leave-one-out over every approved claim a
human tagged. The same function backs `/admin/calibrate_classify`, so the
console and this script can never drift apart.

    DATABASE_URL='postgres://…' python3 scripts/calibrate_classify.py
    DATABASE_URL='postgres://…' python3 scripts/calibrate_classify.py baci agency

**Reads only.** It writes no row and deliberately does NOT call `db.init_db()`,
which would run `_auto_migrate` and issue ALTER statements. Importing `app.db`
builds an engine and nothing more.

If you have no local `DATABASE_URL` — which is the normal case, the live
database is Render's — use the console route instead:

    curl -b ~/.gomeh-console -s \\
      "https://assistant-web-zm2d.onrender.com/admin/calibrate_classify" | jq
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import kb  # noqa: E402

TENANTS = ("agency", "baci", "eien", "coverings", "ironside")


def _pct(n: int, total: int) -> str:
    return f"{(100 * n / total):5.1f}%" if total else "    — "


def report(res: dict) -> None:
    t, n = res["tenant"], res["n"]
    print(f"\n{'=' * 74}\n{t}  —  {n} approved claims carrying a human tag")
    if n == 0:
        print("  nothing tagged on this account; nothing to calibrate")
        return
    if not res["enough_to_calibrate"]:
        print(f"  !  n={n} is below {res['min_n']}. Read the rows; do NOT move a")
        print("     floor on this — a percentage over a handful is noise.")

    p = res["pattern"]
    if p["n"]:
        print(f"\n  PATTERNS  {p['n']} matched a pattern — a decision, which the "
              f"floors never see")
        print(f"            {p['agreed']}/{p['n']} agreed with the human tag")
        for r in p["misses"]:
            print(f"            x human={r['human']} got={r['tags']}  {r['claim']}")

    learned = res["rows"]
    if not learned:
        print("\n  no claims reached the learned path — nothing to sweep")
        return

    live = next((s for s in res["sweep"] if s["live"]), None)
    lf = res["live_floors"]
    print(f"\n  OUTCOMES at the live floors "
          f"(shared>={lf['min_shared']}, score>={lf['min_score']})")
    if live:
        tot = res["learned_n"]
        print(f"    placed correctly   {live['correct']:4d}  {_pct(live['correct'], tot)}")
        print(f"    placed WRONG       {live['wrong']:4d}  {_pct(live['wrong'], tot)}"
              f"   <- confident and mistagged: the dangerous one")
        print(f"    refused            {live['refused']:4d}  {_pct(live['refused'], tot)}"
              f"   <- the cost: lands untagged for a human")
        print(f"    no overlap at all  {live['no_overlap']:4d}  "
              f"{_pct(live['no_overlap'], tot)}")

    print("\n  SCORE DISTRIBUTION  (a floor should sit between these)")
    for label, key in (("correct tag on top", "correct_tag_on_top"),
                       ("wrong tag on top", "wrong_tag_on_top")):
        d = res["scores"][key]
        if d:
            print(f"    {label:22s} n={d['n']:3d}  p10={d['p10']:5.2f}  "
                  f"median={d['median']:5.2f}  p90={d['p90']:5.2f}")
        else:
            print(f"    {label:22s} none")
    if res["separable"]:
        lo, hi = res["separable_window"]
        print(f"    OK cleanly separable — any floor in ({lo:.2f}, {hi:.2f}] splits them")
    elif res["scores"]["correct_tag_on_top"] and res["scores"]["wrong_tag_on_top"]:
        print("    !! the distributions overlap — no floor separates them cleanly.")
        print("       Choose from the sweep by which error you would rather make.")

    print("\n  SWEEP")
    print("    shared  score |  correct    wrong  refused")
    for s in res["sweep"]:
        print(f"    {s['min_shared']:6d}  {s['min_score']:5.2f} |  "
              f"{s['correct']:7d}  {s['wrong']:7d}  {s['refused']:7d}"
              f"{'  <- live' if s['live'] else ''}")


def main() -> int:
    if not os.environ.get("DATABASE_URL"):
        print("No DATABASE_URL — this would read a local sqlite file, not the")
        print("live knowledge base. Either set it, or use the console route:")
        print("  curl -b ~/.gomeh-console -s \\")
        print("    'https://assistant-web-zm2d.onrender.com/admin/calibrate_classify'")
        return 2

    wanted = sys.argv[1:] or list(TENANTS)
    print(f"leave-one-out over {', '.join(wanted)}   (read-only; nothing written)")
    print(f"live floors: MIN_SHARED_WORDS={kb.MIN_SHARED_WORDS}  "
          f"MIN_LEARNED_SCORE={kb.MIN_LEARNED_SCORE}")

    grand = 0
    for t in wanted:
        try:
            res = kb.calibration(t)
        except Exception as exc:  # noqa: BLE001
            print(f"\n{t}: could not evaluate — {exc.__class__.__name__}: {exc}")
            continue
        grand += res["n"]
        report(res)

    print(f"\n{'=' * 74}")
    if grand < kb.CALIBRATION_MIN_N:
        print(f"TOTAL n={grand}, under {kb.CALIBRATION_MIN_N} across every account.")
        print("There is not enough tagged material to set a floor from evidence.")
        print("That is a finding about the knowledge base, not about the floors:")
        print("the classifier cannot be calibrated until there are claims to")
        print("calibrate it against. Leave the floors where they are and re-run")
        print("after the next harvest or authoring pass.")
    else:
        print(f"TOTAL n={grand}. Pick floors from the sweep, set them in app/kb.py")
        print("(MIN_SHARED_WORDS / MIN_LEARNED_SCORE), then re-run")
        print("scripts/test_classify.py — its two cases are pinned to the current")
        print("values and will tell you exactly what you changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
