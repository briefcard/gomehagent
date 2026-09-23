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


def _dict_keys(node, fn=None):
    """The keys of a `dict(a=1, **b)` or `{"a": 1}` node — including the keys
    of any `**b` spread whose dict is built literally in `fn`, because that
    is how a route carries an ad's own words into a payload."""
    keys, spreads = set(), []
    if isinstance(node, ast.Call) and ast.unparse(node.func) == "dict":
        keys = {k.arg for k in node.keywords if k.arg}
        spreads = [k.value for k in node.keywords if k.arg is None]
    elif isinstance(node, ast.Dict):
        keys = {ast.unparse(k).strip("\"'") for k in node.keys if k is not None}
        spreads = [v for k, v in zip(node.keys, node.values) if k is None]
    else:
        return None
    for sp in spreads:
        if fn is not None and isinstance(sp, ast.Name):
            keys |= (_literal_keys(fn, sp.id) or set())
    return keys


def _queued_callee(call, ftxt, fn=None):
    """`(dotted callee, payload keys, accepted names)` for
    `_jobs.enqueue(tenant, "kind", payload=…)`, else None.

    The kind's registry entry names the function that will be handed the
    payload: `takes` when a wrapper forwards it, the target otherwise. Both
    signatures count as accepting, because the wrapper eats its own
    arguments (which model to draw with, which of three modes) and forwards
    the rest.
    """
    if not ftxt.endswith("enqueue") or len(call.args) < 2:
        return None
    if not (isinstance(call.args[1], ast.Constant) and isinstance(call.args[1].value, str)):
        return None
    from app import jobs as _jobs
    spec = _jobs.KINDS.get(call.args[1].value)
    if not spec:
        return None
    payload = next((k.value for k in call.keywords if k.arg == "payload"), None)
    keys = _dict_keys(payload, fn) if payload is not None else set()
    if keys is None:
        return None
    accepted: set = set()
    for dotted in (spec.get("takes"), spec["target"]):
        if not dotted:
            continue
        mod, _, fn_ = str(dotted).partition(":")
        target = _resolve(mod.split(".", 1)[-1] + "." + fn_, is_module=True)
        if target is not None:
            try:
                accepted |= set(inspect.signature(target).parameters)
            except (TypeError, ValueError):
                pass
    mod, _, fn_ = str(spec.get("takes") or spec["target"]).partition(":")
    return (mod.split(".", 1)[-1] + "." + fn_, set(keys), accepted)


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
            queued = _queued_callee(call, ftxt, fn)
            if queued:
                # A PRESS THAT QUEUES IS STILL A CALL. The heavy work moved
                # off the web service on 2026-09-23 and the payload became a
                # dict in a row — which made every one of these sites
                # invisible to this walker, `ad_frames` included. The kind
                # names its target, so the seam is still both-sided: the keys
                # the route puts in the payload are checked against the
                # signature that will be handed them, a tick later, in
                # another process.
                callee, sent, accepts = queued
            elif ftxt.endswith("_run_bg") and len(call.args) >= 2:
                callee = ast.unparse(call.args[1])
                sent = {k.arg for k in call.keywords if k.arg}
            elif spread:
                callee = ftxt
                sent = {k.arg for k in call.keywords if k.arg}
            else:
                continue
            if not queued:
                for sp in spread:
                    if isinstance(sp.value, ast.Name):
                        ks = _literal_keys(fn, sp.value.id)
                        if ks:
                            sent |= ks
            head = callee.split(".")[0]
            is_module = queued or head in aliases
            if not queued and is_module:
                callee = aliases[head] + callee[len(head):]
            if queued:
                out.append((fn.name, callee, sent, accepts))
                continue
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
            # the owner function is only needed to resolve a `**args` spread
            # inside a payload, and finding it walks every function in the
            # file — so look for it ONLY at a call that queues something
            q = None
            if ft.endswith("enqueue"):
                owner_fn = next((f_ for f_ in fns
                                 if any(n_ is node for n_ in ast.walk(f_))), None)
                q = _queued_callee(node, ft, owner_fn)
            is_it = (ft.split(".")[-1] == callee) or (
                ft.endswith("_run_bg") and len(node.args) >= 2
                and ast.unparse(node.args[1]).split(".")[-1] == callee) or (
                bool(q) and q[0].split(".")[-1] == callee)
            if q and is_it:
                passed |= q[1]
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
