"""Everything that costs money is recorded, and nothing is priced by guess.

Owner, 2026-08-29: "Please go ahead and make sure the spend report is
complete."

I had told him the report was missing every direct SDK call. That was WRONG —
I read `llm.py`'s docstring note about "nine of the twenty-six" as current
when it is historical, and every direct Anthropic call site does log by hand.
Computing it instead of remembering it found the real gaps, and they were not
Anthropic at all:

  * `embed.py` called OpenAI over raw HTTP and logged NOTHING. It runs on
    every tier-3 resolve — one per inbound mail on the path that answers
    customers — so a recurring per-email cost was absent from the report.
  * `imagegen.py` did the same for `gpt-image-1`. An image is worth roughly
    two thousand text calls, which made the most expensive single thing the
    system does the one thing the spend page could not see.
  * `_cost` fell back to Sonnet's rate for any model not in PRICES, so an
    embedding logged at 150x its true cost would have looked precise. There
    was a second copy of that fallback inside the cache-savings figure.

The two structural claims below are COMPUTED from the source, because "every
call site logs" is exactly the kind of claim that is true on the day it is
made and quietly false a month later.

    python3 scripts/test_spend_complete.py
"""
from __future__ import annotations

import ast
import os
import pathlib
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 's.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, usage  # noqa: E402

APP = pathlib.Path(__file__).resolve().parent.parent / "app"
_fail: list[str] = []

#: Every way this codebase reaches a paid provider. A new one added here is a
#: new thing to attribute; a new one NOT added here is why this file exists.
PAID = ("messages.create", "embeddings.create", "images.generate",
        "/v1/embeddings", "/images/generations", "/images/edits")


def ck(label: str, cond, detail: str = "") -> None:
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _records(body: str) -> bool:
    return ("log_usage" in body or "log_tokens" in body or "log_image" in body)


def _paying_functions() -> list[tuple[str, str, bool]]:
    """(module, function, does it record) for everything that spends money.

    DELEGATION COUNTS, one level. `imagegen.plate` names the endpoint but
    hands the request to `_post`, which is where the charge lives — putting it
    at that single seam is what stops a generator being added without it, so a
    test that demanded logging in `plate` itself would be arguing against the
    better design. What is NOT allowed is a function that names an endpoint,
    delegates to nothing that records, and records nothing itself.
    """
    out = []
    for f in sorted(APP.glob("*.py")):
        src = f.read_text()
        tree = ast.parse(src)
        # Which functions in THIS module record, so delegation can be resolved.
        logs_here = {
            fn.name for fn in ast.walk(tree)
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
            and _records(ast.get_source_segment(src, fn) or "")}
        # `post = _post` and friends: an alias points at the same body.
        for n in ast.walk(tree):
            if isinstance(n, ast.Assign) and isinstance(n.value, ast.Name) \
                    and n.value.id in logs_here:
                for t in n.targets:
                    if isinstance(t, ast.Name):
                        logs_here.add(t.id)
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            body = ast.get_source_segment(src, fn) or ""
            if not any(p in body for p in PAID):
                continue
            called = {(ast.get_source_segment(src, n.func) or "").rsplit(".", 1)[-1]
                      for n in ast.walk(fn) if isinstance(n, ast.Call)}
            out.append((f.name, fn.name,
                        _records(body) or bool(called & logs_here)))
    return out


def main() -> int:
    db.init_db()

    print("— every function that spends money records it —")
    rows = _paying_functions()
    ck("there are paying functions to check", len(rows) >= 10, str(len(rows)))
    silent = [(m, fn) for m, fn, rec in rows if not rec]
    ck("none of them is silent", not silent,
       f"{silent} — a call that costs money and records nothing is not a "
       f"missing row, it is a wrong total")

    print("\n— and both providers are covered, not just the loud one —")
    mods = {m for m, _fn, _r in rows}
    ck("the embedding path is in the list", "embed.py" in mods, str(sorted(mods)))
    ck("the image path is in the list", "imagegen.py" in mods)

    print("\n— nothing is priced by guess —")
    ck("an unknown model costs 0, not Sonnet's rate",
       usage._cost("model-nobody-has-priced", 10**6, 10**6, 0, 0) == 0.0,
       "$18 of invented spend per million tokens, on a report whose whole "
       "job is to be trusted")
    ck("…and the report names it rather than hiding it",
       "unpriced_models" in usage.report(days=1))
    ck("embeddings are priced as embeddings",
       abs(usage._cost("text-embedding-3-small", 10**6, 0, 0, 0) - 0.02) < 1e-9,
       "Sonnet's rate would be 150x")
    ck("images are priced per image, not per token",
       usage._cost("gpt-image-1", 4, 0, 0, 0) == 4 * usage.IMAGE_PRICES["gpt-image-1"])
    ck("the cache-savings figure uses the same rules",
       "PRICES.get(r.model, UNPRICED)" in (APP / "usage.py").read_text(),
       "the second copy of the Sonnet fallback hid inside 'saved by cache'")

    print("\n— driven for real, with the provider stubbed —")
    # THE STRUCTURAL CHECK ABOVE IS NOT ENOUGH, and sabotage said so: it
    # asserts the logging call EXISTS, which stays true when the value passed
    # to it is zeroed. These drive the actual paths and read the row back.
    import base64 as _b64
    import httpx as _httpx

    from app import config as _cfg
    from app import embed as _embed
    from app import imagegen as _img

    class _Resp:
        def __init__(self, payload):
            self.status_code = 200
            self._p = payload
            self.text = ""

        def json(self):
            return self._p

    def _rows(purpose):
        with db.SessionLocal() as s_:
            return [r for r in s_.query(db.Usage)
                    .filter(db.Usage.purpose == purpose).all()]

    _real = _httpx.post
    try:
        _cfg.OPENAI_API_KEY = _cfg.OPENAI_API_KEY or "test-key"
        _httpx.post = lambda *a, **k: _Resp(
            {"data": [{"index": 0, "embedding": [0.1, 0.2]}],
             "usage": {"prompt_tokens": 4242}})
        _embed.embed_texts(["hello"])
        er = _rows("embed")
        ck("an embedding records the tokens it actually used",
           len(er) == 1 and int(er[0].input_tokens) == 4242,
           str([(r.model, r.input_tokens) for r in er]))
        ck("…against the embedding model, so it is priced as one",
           bool(er) and er[0].model == _cfg.EMBED_MODEL)

        _httpx.post = lambda *a, **k: _Resp(
            {"data": [{"b64_json": _b64.b64encode(b"x").decode()},
                      {"b64_json": _b64.b64encode(b"y").decode()}]})
        _img._post("/images/generations", json_body={})
        ir = _rows("image_generate")
        ck("a generation records how many images came back",
           len(ir) == 1 and int(ir[0].input_tokens) == 2,
           str([(r.model, r.input_tokens) for r in ir]))
        _img._post("/images/edits", json_body={})
        ck("…and an edit is charged too, under its own purpose",
           len(_rows("image_edit")) == 1)
    finally:
        _httpx.post = _real

    print("\n— and the rows land where the report can see them —")
    before = usage.report(days=1)
    usage.log_tokens("embed", "text-embedding-3-small", input_tokens=500_000)
    usage.log_image("image_generate", "gpt-image-1", 2)
    rep = usage.report(days=1)
    ck("both shapes are counted",
       rep["calls"] - before["calls"] == 2,
       f'{before["calls"]} -> {rep["calls"]}')
    ck("…and cost what they should",
       abs((rep["est_cost_usd"] - before["est_cost_usd"])
           - round(0.01 + 2 * 0.04, 2)) < 0.005,
       f'{before["est_cost_usd"]} -> {rep["est_cost_usd"]}')
    ck("an unattributed row is named, never split across clients",
       "unattributed" in rep["by_tenant"],
       "a client's bill inflated by shared overhead is worse than one that "
       "admits what it cannot split")

    print()
    if _fail:
        print(f"{len(_fail)} FAILED:")
        for f in _fail:
            print(f"  - {f}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
