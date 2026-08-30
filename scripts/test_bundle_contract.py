"""The brand package is DECLARED, and both checks on it actually bite.

`bundle["audiences"]` was read by `funnel.inputs_for` — the function that
briefs the ad, the email and the article on who is reading — and written by
nobody, for the life of the codebase. No fallback, no gap note, no test: the
funnel suite hand-fed an audience straight to `inputs_for` and stayed green
while the live value was `None` in every drafting system. Nothing was broken;
nothing was declared, so nothing could notice.

This suite is what makes that unrepeatable. It checks the declaration against
the code (`audit`) and a built package against the declaration (`verify`) —
and, because a check that cannot fail is decoration, it checks that each one
FAILS when it should.

Run: python3 scripts/test_bundle_contract.py
"""
import os
import pathlib
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'bc.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import bundle as pkg, db, kb, resolve, tenants  # noqa: E402

_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    db.init_db()
    tenants.seed()
    t = "baci"
    kb.ensure_brand(t, "Baci")
    kb.set_brand(t, positioning="Italian-designed tableware.", tone="warm")
    kb.add_banned(t, "made in Italy")
    kb.add_audience(t, "host", "The host", ["chipped mismatched sets"],
                    ["tablescape"], buying_trigger="a dinner party booked")

    print("— every part of the package is declared —")
    a = pkg.audit()
    ck("no consumer reads a part nobody declares",
       not a["undeclared"],
       "; ".join(f"{k} at {v[0]}" for k, v in a["undeclared"].items()) or "clean")
    ck("every declared part names who supplies it",
       all(p.get("supplies") for p in pkg.PARTS.values()),
       str([k for k, p in pkg.PARTS.items() if not p.get("supplies")]))
    ck("every declared part says what its absence MEANS",
       all(p.get("absent") in (pkg.THINS, pkg.UNVERIFIED, pkg.SITUATIONAL)
           for p in pkg.PARTS.values()),
       "a gap that does not say whether it thins the work or makes it "
       "unverifiable cannot be triaged")

    print("\n— a built package carries what its tier promised —")
    for tier in (1, 2, 3):
        b = resolve.resolve(t, system="campaign_email", tier=tier)
        ck(f"tier {tier} carries every promised part", not pkg.verify(b),
           str(pkg.verify(b)))
    b3 = resolve.resolve(t, system="campaign_email", tier=3)
    ck("  and the receipt reports no absence",
       not b3["coverage"].get("promised_but_absent"),
       str(b3["coverage"].get("promised_but_absent")))

    print("\n— the regression itself: the buyer is IN the package —")
    ck("`audiences` is a declared part", "audiences" in pkg.PARTS)
    ck("  and a tier-2 package actually carries it",
       "audiences" in resolve.resolve(t, system="campaign_email", tier=2),
       "read by funnel.inputs_for for every drafter; supplied by nobody "
       "until 2026-08-30")
    ck("  with the buyer's own vocabulary in it",
       any(x.get("vocabulary") for x in (b3.get("audiences") or [])),
       str(b3.get("audiences"))[:120])

    print("\n— a refusal is not an incomplete package —")
    r = resolve.resolve("no-such-account", system="campaign_email", tier=3)
    ck("an unknown account refuses instead of promising", bool(r.get("error")))
    ck("  and is not reported as fifteen missing parts", not pkg.verify(r),
       str(pkg.verify(r))[:90])

    # ---- the checks must be able to FAIL ---------------------------------
    print("\n— and both checks actually bite —")
    starved = dict(b3)
    starved.pop("audiences")
    missing = pkg.verify(starved)
    ck("verify NAMES a promised part that is not carried",
       missing == ["audiences"], str(missing))
    ck("  and stays quiet about a situational one",
       not pkg.verify({k: v for k, v in b3.items() if k != "conversation"}),
       "a part that only exists when the request supplied a subject must "
       "not read as a missing promise")

    tmp = pathlib.Path(tempfile.mkdtemp())
    (tmp / "consumer.py").write_text(
        "def f(bundle):\n"
        "    return bundle.get('a_part_nobody_declares')\n")
    rogue = pkg.audit(str(tmp))
    ck("audit CATCHES a consumer reading an undeclared part",
       "a_part_nobody_declares" in rogue["undeclared"],
       str(rogue["undeclared"]))

    print("\n" + ("all checks passed" if not _fail
                  else f"{len(_fail)} FAILED:\n  - " + "\n  - ".join(_fail)))
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
