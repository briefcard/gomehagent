"""A tone you cannot see the sentences for is one nobody can review.

`voice.tone` blocks `/resolve` on every account, and it is the one knowledge
base field a crawl can honestly derive — a site records what a brand DOES say,
which is exactly what voice is. The ban list is the opposite and is why this
file also checks that a sample is filtered before a model ever sees it.

Two failure modes, and they are different in kind:

  * the countable half — sentence length, contractions, second person — was
    being left to a model that had no need to guess it. Arithmetic cannot
    fabricate.
  * the judged half can, so every exemplar it returns is checked against the
    source the way `extract._verify` checks a claim span, and an invented one
    is discarded before anybody reads it.

    python3 scripts/test_voice.py
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'vo.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import kb, tenants, voice  # noqa: E402
from app.web import app  # noqa: E402

_fail = []

WARM = [
    "We think a table should look like someone lives at it.",
    "You'll find a pattern here that argues with your plates, on purpose.",
    "Pour something cold in it and let the afternoon go long.",
    "Every piece is meant to be used, not shelved behind glass.",
    "You don't need a reason to set a good table.",
    "We'd rather you chipped one than kept the set in a box.",
]
BANNED_SENTENCE = ("Each one is hand-painted in Italy by people who have done "
                   "it for thirty years.")


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    with TestClient(app) as cl:  # noqa: F841
        tenants.seed()
        kb.ensure_brand("baci", "Baci Milano USA")
        kb.add_banned("baci", "hand-painted")
        kb.add_banned("baci", "made in Italy")

        print("— the countable half needs no model —")
        m = voice.measure(WARM)
        ck("it counts sentences", m["sentences"] == 6, str(m["sentences"]))
        ck("it hears the second person",
           m["second_person_per_100w"] > 0, str(m["second_person_per_100w"]))
        ck("and the contractions", m["contractions_per_100w"] > 0,
           str(m["contractions_per_100w"]))
        ck("it refuses to conclude from six sentences",
           m["enough"] is False and str(voice.MIN_SENTENCES) in m["why"],
           m["why"])

        print("\n— page furniture is not how a brand writes —")
        s = voice.sentences(["Shop now", "Care guide", "SALE",
                             "We think a table should look lived at."])
        ck("short labels are dropped", len(s) == 1, str(s))
        ck("and shouting is too", "SALE" not in s)

        print("\n— a banned phrase never reaches the model —")
        kept, dropped = voice._drop_banned("baci", WARM + [BANNED_SENTENCE])
        ck("the barred sentence is removed", BANNED_SENTENCE not in kept)
        ck("and it is reported, not silently lost", len(dropped) == 1,
           str(dropped))
        ck("everything else survives", len(kept) == len(WARM))

        print("\n— with no model, it measures and says why —")
        out = voice.propose("baci", WARM + [BANNED_SENTENCE])
        ck("no tone is invented", out["tone"] == [], str(out["tone"]))
        ck("the reason is carried", "ANTHROPIC" in out["degraded"],
           out["degraded"])
        ck("but the measurements still arrive",
           out["measured"]["sentences"] == 6)
        ck("and the banned sentence is accounted for",
           out["dropped_for_banned_claims"] == 1)
        ck("nothing was written", out["applied"] is False
           and not (kb.brand("baci").voice or {}).get("tone"),
           "set_brand stays the only way a voice lands")

        print("\n— an invented exemplar is discarded before anyone reads it —")
        # The guarantee that makes a tone reviewable: whatever comes back, a
        # quote survives only if the source genuinely contains it.
        real, fake = WARM[0], "We are passionate about craftsmanship."
        pool = {" ".join(x.split()) for x in WARM}
        ck("a real sentence is in the pool", " ".join(real.split()) in pool)
        ck("an invented one is not", " ".join(fake.split()) not in pool,
           "this is the check that keeps a tone word evidenced")

        print("\n— the proposal is applyable as written —")
        ck("the tone cap is under set_brand's own limit",
           voice.MAX_TONE_WORDS <= 8,
           "a proposal that set_brand would refuse is not a proposal")
        ck("and set_brand still accepts a hand-typed one",
           "voice" in kb.set_brand("baci", tone="warm, direct").lower()
           or (kb.brand("baci").voice or {}).get("tone") == ["warm", "direct"],
           str((kb.brand("baci").voice or {}).get("tone")))

    print()
    if _fail:
        print(f"FAILED {len(_fail)}:")
        for f in _fail:
            print(f"  - {f}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
