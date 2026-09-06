"""The picture generator's model is a setting, like every other model here.

Every text model on this platform has been overridable for months —
`CLAUDE_MODEL`, `CLASSIFY_MODEL`, `SWEEP_MODEL`, `SEO_MODEL`,
`CREATIVE_REVIEW_MODEL` — each with a `config` row and, for the purpose-scoped
ones, a `llm.PURPOSE_MODEL` entry. `imagegen` hardcoded `MODEL` and `BASE`.

So the one call the owner is unhappy with was the only one that could not be
changed, compared or A/B'd without a deploy. `CREATIVE_REVIEW_MODEL`'s own
config comment already makes the argument — "overridable because the frontier
moves and this is the one call whose model choice somebody will want to change
without a deploy" — and it was written about the JUDGE while the GENERATOR
stayed nailed down.

There is a per-call override too, because the point of this is an experiment:
ranking three models against one fixed brief should be a script, not three
deploys and a wait.

WHAT THIS IS NOT: a provider abstraction. `IMAGE_API_BASE` is a row, not a
seam. A provider with a different request shape needs more than a URL, and a
seam that fails at its first real use is worse than an honest constant.

    python3 scripts/test_the_image_model_is_a_setting.py
"""
from __future__ import annotations

import os
import pathlib
import re
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'im.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["SEO_SITES_JSON"] = "{}"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config, imagegen, llm  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _sent(**kw) -> dict:
    box: dict = {}
    imagegen.post = lambda path, **k: (box.update(k.get("json_body") or {})
                                       or {"ok": True, "images": [b"x"]})
    imagegen.plate("a room", **kw)
    return box


def main() -> int:
    print("— the model is a setting —")
    ck("config carries a row for it", hasattr(config, "IMAGE_MODEL"),
       getattr(config, "IMAGE_MODEL", "<missing>"))
    ck("  read from the environment, like every other model",
       'os.environ.get("IMAGE_MODEL"' in (ROOT / "app" / "config.py").read_text())
    ck("  and the endpoint too", hasattr(config, "IMAGE_API_BASE"))
    ck("imagegen reads them rather than declaring them",
       imagegen.MODEL == config.IMAGE_MODEL
       and imagegen.BASE == config.IMAGE_API_BASE, imagegen.MODEL)
    ck("  the default is unchanged, so nothing moves by accident",
       config.IMAGE_MODEL == "gpt-image-1", config.IMAGE_MODEL)

    print("\n— and one run can use a different one, which is the point —")
    ck("the default reaches the request", _sent().get("model") == "gpt-image-1")
    ck("a per-call override reaches the request",
       _sent(model="some-other-image-model").get("model")
       == "some-other-image-model",
       "ranking three models should be a script, not three deploys")
    ck("  and an empty override falls back rather than sending nothing",
       _sent(model="").get("model") == "gpt-image-1")

    print("\n— COMPUTED, not asserted: no model id is hardcoded outside config —")
    # Derive the population from the code rather than re-stating the claim.
    #
    # NAMING a model is not CHOOSING one. `usage.py` keys a price table by
    # model id — "claude-sonnet-4-6": (3.0, 15.0) — and that is data ABOUT
    # models which has to name them. The defect class is a model id used as a
    # CHOICE: assigned to a *_MODEL name, or sent as the "model" field of a
    # request. That is what this looks for, and the first version of this
    # assertion did not distinguish the two and flagged the price table.
    ident = r'(?:gpt|claude|text-embedding|dall-e)[a-z0-9.\-]*'
    chosen = re.compile(r'(?:MODEL\s*=\s*"(' + ident + r')"'
                        r'|"model"\s*:\s*"(' + ident + r')")')
    offenders = []
    for f in sorted((ROOT / "app").glob("*.py")):
        if f.name == "config.py":
            continue
        for m in chosen.finditer(f.read_text()):
            offenders.append(f"{f.name}: {m.group(1) or m.group(2)}")
    ck("no module outside config CHOOSES a model id",
       not offenders, str(offenders[:4]))
    priced = re.compile(r'"(' + ident + r')"\s*:\s*\(')
    ck("  while the price table may still NAME them, which is data not choice",
       bool(priced.search((ROOT / "app" / "usage.py").read_text())),
       "an assertion that cannot tell those apart flags the wrong file")

    print("\n— the purpose table still resolves to real rows —")
    unresolved = [v for v in llm.PURPOSE_MODEL.values() if not hasattr(config, v)]
    ck("every PURPOSE_MODEL entry names a config attribute that exists",
       not unresolved, str(unresolved))
    ck("  and an unknown purpose still falls back rather than failing",
       llm.model_for("no-such-purpose") == config.CLAUDE_MODEL
       if hasattr(llm, "model_for") else True, "")

    print()
    if _fail:
        print(f"{len(_fail)} FAILED: {_fail}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
