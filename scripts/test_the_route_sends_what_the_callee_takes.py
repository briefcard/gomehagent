"""Every kwargs spread from a web route reaches a callee that accepts it.

`fb00ed1` made `web.ad_frames` send `situation=row.situation` into
`creative.batch(**args)` and did not add `situation` to `batch`'s signature.
Every "Make frames" click from 2026-09-05 17:03 raised TypeError inside
`_run_bg` — which catches and RECORDS, so the button still returned 303 —
for two days, and nothing caught it:

  · the suite spied on `_run_bg` and never ran the receiver;
  · no suite calls `ad_frames` through to the real `batch`;
  · `/health` reports the commit, not whether a button works.

A SEAM IS ONLY TESTED WHEN BOTH SIDES EXECUTE. This suite is the cheap,
class-wide half of that rule: for every call in `app/web.py` that spreads a
dict or passes through `_run_bg`, compute the keys it sends and the keys the
callee's signature accepts, and refuse any difference. Computed from the AST
and `inspect.signature`, so it fails on `fb00ed1` as it was written and on any
future one-sided change — in either direction, on any route.

    python3 scripts/test_the_route_sends_what_the_callee_takes.py
"""
from __future__ import annotations

import ast
import importlib
import inspect
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'rt.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["SEO_SITES_JSON"] = "{}"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import web  # noqa: E402

_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _literal_keys(fn, name):
    """Keys of `name = dict(k=..)` or `name = {..}` inside fn, else None."""
    for n in ast.walk(fn):
        if isinstance(n, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == name for t in n.targets):
            v = n.value
            if isinstance(v, ast.Call) and ast.unparse(v.func) == "dict":
                return {k.arg for k in v.keywords if k.arg}
            if isinstance(v, ast.Dict):
                return {ast.unparse(k).strip("\"'") for k in v.keys if k is not None}
    return None


def _resolve(dotted, *, is_module=False):
    """`is_module` means the head came from a `from . import x` alias inside
    the route — an app MODULE by construction. It must be imported, never
    looked up on `web`: web.py has a ROUTE FUNCTION named `creative`, so
    `getattr(web, "creative")` returned that handler, `.batch` was not on it,
    and the walker silently skipped ad_frames→batch — the one site that had
    actually broken in production. The first run of this suite reported seven
    clean sites and never examined the eighth."""
    parts = dotted.split(".")
    obj = None
    if not is_module:
        obj = getattr(web, parts[0], None)
        if obj is not None and not inspect.ismodule(obj) and len(parts) > 1:
            obj = None                     # a function/route shadowing a module name
    if obj is None:
        try:
            obj = importlib.import_module("app." + parts[0])
        except Exception:                                        # noqa: BLE001
            return None
    for p in parts[1:]:
        obj = getattr(obj, p, None)
        if obj is None:
            return None
    return obj if callable(obj) else None


def spread_sites():
    """(route, callee, sent, accepted) for every kwargs-spreading call."""
    src = open(os.path.join(ROOT, "app", "web.py")).read()
    tree = ast.parse(src)
    out = []
    for fn in [n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        aliases = {}
        for n in ast.walk(fn):
            if isinstance(n, ast.ImportFrom) and n.module is None:
                for a in n.names:
                    aliases[a.asname or a.name] = a.name
        for call in [n for n in ast.walk(fn) if isinstance(n, ast.Call)]:
            ftxt = ast.unparse(call.func)
            spread = [k for k in call.keywords if k.arg is None]
            if ftxt.endswith("_run_bg") and len(call.args) >= 2:
                callee = ast.unparse(call.args[1])
            elif spread:
                callee = ftxt
            else:
                continue
            sent = {k.arg for k in call.keywords if k.arg}
            for sp in spread:
                if isinstance(sp.value, ast.Name):
                    ks = _literal_keys(fn, sp.value.id)
                    if ks:
                        sent |= ks
            head = callee.split(".")[0]
            is_module = head in aliases
            if is_module:
                callee = aliases[head] + callee[len(head):]
            target = _resolve(callee, is_module=is_module)
            if target is None:
                continue
            try:
                params = inspect.signature(target).parameters
            except (TypeError, ValueError):
                continue
            if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()):
                continue                       # **kwargs accepts anything; nothing to check
            out.append((fn.name, callee, sent, set(params)))
    return out


def main() -> int:
    sites = spread_sites()
    print(f"— {len(sites)} kwargs-spreading call sites in web.py, each checked "
          f"against its callee's real signature —")
    ck("the check found the site that broke in production",
       any(r == "ad_frames" and c.endswith("batch") for r, c, _, _ in sites),
       "if ad_frames→batch is not in this list the walker is broken, not the code")
    for route, callee, sent, accepted in sites:
        bad = sorted(sent - accepted)
        ck(f"{route}() -> {callee} sends only what it accepts",
           not bad, f"NOT accepted: {bad}")
    ck("no callee is exempted by having **kwargs where a real signature is expected",
       all(c != "creative.batch" or "situation" in a for _, c, _, a in sites),
       "batch must name its parameters; a **kwargs sink would hide this class forever")

    print("\n— the inverse: parameters a generator DECLARES that the paths which need "
          "them actually PASS —")
    # The owner's phrase: "fill the technical gaps that are preventing execution
    # due to missing parameters". A kwarg the callee takes but no caller sends
    # is a default silently standing in for a fact — `situation` was one
    # (creative.py never forwarded it), `channel` was one (pick never got it),
    # `entity_key` on the mail harvester was one (every reply filed brand-wide).
    REQUIRED = {
        ("app/web.py", "batch"): {"situation", "prominent", "output_id", "entity_key"},
        ("app/creative.py", "pick"): {"situation", "channel", "entity_key"},
        ("app/creative.py", "brief_for"): {"situation", "prominent", "entity_key"},
        ("app/resolve.py", "claims"): {"entity_keys"},
        ("app/email_harvest.py", "add_claim"): {"entity_key"},
    }
    for (path, callee), need in REQUIRED.items():
        src = open(os.path.join(ROOT, path)).read()
        tree = ast.parse(src)
        fns = [f_ for f_ in ast.walk(tree) if isinstance(f_, (ast.FunctionDef, ast.AsyncFunctionDef))]
        passed = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            ft = ast.unparse(node.func)
            # `_run_bg(label, fn, *args, **kw)` IS a call to fn — the forward
            # walker above already treats it so; the first version of this
            # inverse check did not, and reported web.py never passing
            # anything to batch when batch is the second positional of _run_bg.
            is_it = (ft.split(".")[-1] == callee) or (
                ft.endswith("_run_bg") and len(node.args) >= 2
                and ast.unparse(node.args[1]).split(".")[-1] == callee)
            if is_it:
                passed |= {kw.arg for kw in node.keywords if kw.arg}
                for kw in node.keywords:
                    if kw.arg is None and isinstance(kw.value, ast.Name):
                        owner = next((f_ for f_ in fns if any(n_ is node for n_ in ast.walk(f_))), None)
                        ks = _literal_keys(owner, kw.value.id) if owner else None
                        if ks:
                            passed |= ks
        missing = sorted(need - passed)
        ck(f"{path} -> {callee}() is passed {sorted(need)}", not missing,
           f"NEVER PASSED: {missing} — a default is standing in for a fact")

    print()
    if _fail:
        print(f"{len(_fail)} FAILED: {_fail}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
