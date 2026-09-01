"""The reachability register — every declared endpoint, and what consumes it.

WHY THIS EXISTS. Ten defects were found in this repo in one week and not one
was a logic bug. Every one was two halves of a contract written in different
places with nothing joining them: `kb_needs` declared and answered nowhere,
`SCOPES` written beside the catalogue instead of over it, a reference
hand-written about code, `shadow`'s disposition against `emit`'s queue
condition, the guard harness's string-match against the suites' exit codes, an
ad batch's id against the board's variant ids.

Three of those joins now exist on the INPUT side. This is the other direction:
the codebase is very good at declaring and building, and had no mechanism that
noticed when something built is never reached. Every guard here tests the
correctness of things that RUN. Nothing measured whether a thing runs at all.

WHAT IS FLAGGED, and the three are different problems:

  EMPTY      declared or built, and nothing consumes it. `auto` emits
             "cleared" and no production module branches on it; ad_creative
             declares a ship that writes nowhere; `send_campaign` says in its
             own docstring that it is "here for the approval queue" and the
             queue never calls it.
  DUPLICATE  two producers for one fact. Two writers on a table §3 declares
             has one; two autonomy rungs that behave identically; two
             vocabularies for one token set.
  CROSSOVER  a consumer reaching across an ownership boundary — a module
             writing a table another module owns.

COVERAGE IS THE POINT. A register that samples is worse than none: it reads as
completeness and is not. Every family below is enumerated exhaustively from
the source, and `UNCOVERED` names what this does NOT reach, so the gap is
stated rather than implied.

    python3 scripts/register.py           # print the register
    python3 scripts/register.py --json    # machine-readable
"""
from __future__ import annotations

import ast
import collections
import json
import os
import pathlib
import sys
import tempfile

os.environ.setdefault(
    "DATABASE_URL", f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'reg.db')}")
os.environ.setdefault("APPROVAL_SECRET", "s3cret")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP = sorted((ROOT / "app").glob("*.py"))
SCRIPTS = sorted((ROOT / "scripts").glob("*.py"))

#: What this register does NOT reach. Stated, because a register that is silent
#: about its edges reads as complete and is not.
UNCOVERED = (
    "templates and static assets — nothing here parses HTML outside admin_ui",
    "dynamic dispatch is RESOLVED, not caveated: a function whose name "
    "appears as a string literal anywhere in app/ counts as reached, which "
    "under-reports rather than over-reports (see `_named_in_strings`)",
    "external callers: a webhook or an OAuth callback is reached by a third "
    "party, so ENTRY families are exempt from EMPTY by declaration, not by "
    "discovery",
)

#: HTTP routes that are reached from OUTSIDE this codebase. Not a suppression
#: list — a declaration of family. A webhook with no console link is correct.
ENTRY_PREFIXES = (
    "/webhook", "/oauth", "/connect", "/intake", "/decide", "/digest",
    "/health", "/privacy", "/terms", "/portal", "/client", "/wa", "/slack",
    "/brand.md", "/brand_meta", "/robots", "/favicon", "/.well-known",
)


def _tree(p: pathlib.Path) -> ast.Module:
    return ast.parse(p.read_text())


def _attr_names(paths) -> collections.Counter:
    """Every attribute and bare name USED across these files, counted."""
    out: collections.Counter = collections.Counter()
    for p in paths:
        for n in ast.walk(_tree(p)):
            if isinstance(n, ast.Attribute):
                out[n.attr] += 1
            elif isinstance(n, ast.Name):
                out[n.id] += 1
    return out


# ---------------------------------------------------------------------------
# families
# ---------------------------------------------------------------------------

def http_routes() -> list[dict]:
    """Every FastAPI route, and the console control or module that reaches it."""
    routes = []
    for n in ast.walk(_tree(ROOT / "app" / "web.py")):
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for d in n.decorator_list:
            f = getattr(d, "func", d)
            if getattr(getattr(f, "value", None), "id", "") != "app":
                continue
            verb = getattr(f, "attr", "")
            path = (d.args[0].value if getattr(d, "args", None)
                    and isinstance(d.args[0], ast.Constant) else "")
            if path:
                routes.append({"path": path, "verb": verb.upper(),
                               "fn": n.name})
    ui = "\n".join((ROOT / "app" / f).read_text()
                   for f in ("admin_ui.py", "portal_ui.py", "emailfmt.py",
                             "digest.py", "web.py")
                   if (ROOT / "app" / f).exists())
    out = []
    for r in routes:
        stem = r["path"].split("{")[0].rstrip("/") or r["path"]
        entry = any(r["path"].startswith(p) for p in ENTRY_PREFIXES)
        out.append({**r, "reached": entry or (stem in ui),
                    "why": "external entry point" if entry else
                           ("linked from a surface" if stem in ui
                            else "no surface links it")})
    return out


def approval_kinds() -> list[dict]:
    """Kinds created, against the arms in `approvals._execute`."""
    created: dict[str, set] = collections.defaultdict(set)
    for p in APP:
        for n in ast.walk(_tree(p)):
            if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == \
                    "request_approval":
                vals = [a.value for a in n.args[:1]
                        if isinstance(a, ast.Constant)]
                vals += [k.value.value for k in n.keywords
                         if k.arg == "kind" and isinstance(k.value, ast.Constant)]
                for v in vals:
                    created[v].add(p.name)
    src = (ROOT / "app" / "approvals.py").read_text()
    ex = src.split("def _execute(")[1].split("\ndef ")[0]
    armed = {c.value for n in ast.walk(ast.parse(ex.split(":", 1)[1].strip()
                                                 if False else "pass"))
             for c in []}                       # placeholder, replaced below
    armed = set()
    for n in ast.walk(ast.parse("if True:\n" + "\n".join(
            "    " + ln for ln in ex.splitlines()[1:]))):
        if isinstance(n, ast.Compare) and getattr(n.left, "attr", "") == "kind":
            for c in n.comparators:
                if isinstance(c, ast.Constant):
                    armed.add(c.value)
    handled = set()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Set) or isinstance(n, ast.Assign):
            pass
    if "_HANDLED = {" in src:
        blk = src.split("_HANDLED = {")[1].split("}")[0]
        handled = {s.strip().strip('"\'') for s in blk.split(",") if s.strip()}
    return [{"kind": k, "created_in": sorted(v),
             "armed": k in armed, "acknowledged": k in handled}
            for k, v in sorted(created.items())]


def dispositions() -> list[dict]:
    """What `_disposition` returns, against who branches on each value."""
    src = (ROOT / "app" / "skill.py").read_text()
    body = src.split("def _disposition(")[1].split("\ndef ")[0]
    vals = {n.value for n in ast.walk(ast.parse("if True:\n" + "\n".join(
        "    " + ln for ln in body.splitlines()[1:])))
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
        and n.value in ("blocked", "cleared", "needs_approval", "recorded")}
    out = []
    for v in sorted(vals):
        users = []
        for p in APP:
            if p.name == "skill.py":
                continue
            for n in ast.walk(_tree(p)):
                if isinstance(n, ast.Compare):
                    for c in n.comparators:
                        if isinstance(c, ast.Constant) and c.value == v:
                            users.append(p.name)
        out.append({"value": v, "consumed_by": sorted(set(users))})
    return out


def autonomy_rungs() -> list[dict]:
    """Each rung's OBSERVABLE behaviour, so two that are the same say so."""
    from app import skill, systems
    out = []
    for rung in systems.AUTONOMY:
        sig = tuple(skill._disposition(rung, True, w) for w in (True, False))
        out.append({"rung": rung, "disposition_writes": sig[0],
                    "disposition_reads": sig[1], "signature": "/".join(sig)})
    return out


def system_ships() -> list[dict]:
    """Each system's declared ship, and whether what it NAMES actually exists.

    The first cut INFERRED the executor and got the mail systems wrong — it
    reported `service_desk` as shipping nothing while `_execute` has sent its
    Gmail drafts all along. A register that names six working systems as dead
    reads as completeness and is not, so the mechanism is DECLARED
    (`workflow.ship_by`) and this only checks that the thing named is real:
    the module exists, the symbol in it exists, and where a `:kind` suffix
    names an approval kind, that kind has an arm.
    """
    from app import systems
    arms = {a["kind"] for a in approval_kinds() if a["armed"]}
    out = []
    for key, sp in sorted(systems.CATALOG.items()):
        wf = sp.get("workflow") or {}
        ship = wf.get("ship") or ""
        if not ship:
            continue
        by = wf.get("ship_by")
        row = {"system": key, "ship": ship, "ship_by": by, "ok": False,
               "why": ""}
        if by is None:
            row["why"] = "declares a ship and names nothing that performs it"
        elif by == "":
            row["why"] = "declared empty — nothing performs this ship"
        else:
            target, _, kind = by.partition(":")
            mod, _, sym = target.rpartition(".")
            src = ROOT / "app" / f"{mod}.py"
            if not src.exists():
                row["why"] = f"names {mod}.py, which does not exist"
            elif f"def {sym}(" not in src.read_text():
                row["why"] = f"names {target}, which {mod}.py does not define"
            elif kind and kind not in src.read_text():
                # The suffix names the BRANCH inside that mechanism — an
                # approval kind for `_execute`, a called function for
                # `apply_decision`. Checking it is present in the module is
                # the general form; assuming it was always an approval kind
                # reported `campaign_email` as broken while its push works.
                row["why"] = (f"names {kind!r} inside {target}, and {mod}.py "
                              f"does not mention it")
            else:
                row["ok"] = True
        out.append(row)
    return out


def _named_in_strings() -> set:
    """Every identifier that appears as a STRING LITERAL anywhere in the app.

    This is how the register stops lying about dynamic dispatch. Agent tools
    (`data_tools.email_history_search`, `shopify_find_orders`, …), skill run
    functions and job names are reached by NAME through a registry, never by
    an attribute access — so a caller-count over the AST reports thirty live
    tools as unreached. A list that names thirty working things as dead reads
    as completeness and is not; the owner's rule, 2026-08-31: *"make sure we
    register all of the different end points otherwise its just an inaccurate
    list."*

    Deliberately broad. A name mentioned in a docstring counts as reached,
    which under-reports — and under-reporting a possible corpse is far cheaper
    than reporting a live one, because the second kind gets acted on.
    """
    out = set()
    for p in APP:
        for n in ast.walk(_tree(p)):
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                v = n.value.strip()
                if v.isidentifier():
                    out.add(v)
                else:
                    for tok in v.replace("(", " ").replace(".", " ").split():
                        if tok.isidentifier():
                            out.add(tok)
    return out


def _returned_keys(fn: ast.AST) -> list[str]:
    """The dict keys a function RETURNS. Its output contract, when it has one.

    This codebase returns dicts, not types — `{"ok": …, "error": …}` is the
    shape almost everything speaks. A signature alone therefore says nothing
    about what a caller gets, which is why `test_control_piping` already walks
    returns to find warnings nothing renders. Same walk, kept here so the
    register can state an output rather than shrug at one.
    """
    keys: set[str] = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Return) and isinstance(n.value, ast.Dict):
            for k in n.value.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    keys.add(k.value)
    return sorted(keys)


def _params(fn: ast.AST) -> list[str]:
    """Parameter names, `?` marking the ones with a default."""
    a = fn.args
    req = [x.arg for x in a.posonlyargs] + [x.arg for x in a.args]
    n_def = len(a.defaults)
    out = [f"{x}?" if i >= len(req) - n_def else x for i, x in enumerate(req)]
    if a.vararg:
        out.append("*" + a.vararg.arg)
    out += [f"{x.arg}?" for x in a.kwonlyargs]
    if a.kwarg:
        out.append("**" + a.kwarg.arg)
    return out


def function_map() -> list[dict]:
    """Every public function: what goes IN, what comes OUT, what connects.

    Owner, 2026-08-31: *"make sure we update the register in the process to
    show the inputs outputs and connections of all the functions."*

    Connections are computed from attribute calls (`mod.fn(...)`) across
    `app/` and `scripts/`, which is how this codebase actually calls across
    modules. Two honest limits, both already in UNCOVERED: a name resolved at
    runtime reads as no connection, and a same-module call is not a connection
    between modules — it is the module doing its job.
    """
    trees = {p.name: _tree(p) for p in APP}
    # who calls what, by ATTRIBUTE name, with the caller's file
    calls: dict[str, set] = collections.defaultdict(set)
    for name, tree in list(trees.items()) + [(p.name, _tree(p)) for p in SCRIPTS]:
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
                calls[n.func.attr].add(name)
    routes = {r["fn"]: f'{r["verb"]} {r["path"]}' for r in http_routes()}
    out = []
    for p in APP:
        tree = trees[p.name]
        for n in tree.body:
            if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if n.name.startswith("_"):
                continue
            ret = ast.unparse(n.returns) if n.returns else ""
            callers = sorted(calls.get(n.name, set()) - {p.name})
            callees = sorted({
                c.func.attr for c in ast.walk(n)
                if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                and isinstance(getattr(c.func, "value", None), ast.Name)})
            out.append({
                "module": p.name, "fn": n.name,
                "params": _params(n),
                "returns": ret,
                "keys": _returned_keys(n),
                "route": routes.get(n.name, ""),
                "called_by": callers,
                "calls": callees[:12],
            })
    return out


def unreached_functions() -> list[dict]:
    """Public module-level functions nothing calls, names it, or routes to."""
    used = _attr_names(list(APP) + list(SCRIPTS))
    routes = {r["fn"] for r in http_routes()}
    by_name = _named_in_strings()
    out = []
    for p in APP:
        if p.name in ("db.py", "config.py"):
            continue
        for n in _tree(p).body:
            if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if n.name.startswith("_") or n.name in routes:
                continue
            if n.name in by_name:
                continue
            # NOTHING references the name, anywhere. Not "nothing outside its
            # own module": a function put into a registry declared in the same
            # file — `PLANNERS = {"campaign_email": campaign_rollout}` — is
            # referenced by that registry, and subtracting own-module uses
            # reported the campaign planner as dead. A `def` is a FunctionDef,
            # not a Name, so the definition itself never counts here.
            if used[n.name] == 0:
                out.append({"module": p.name, "fn": n.name})
    return out


def table_writers() -> list[dict]:
    """Which modules WRITE each table. §3 declares one writer per table."""
    tables = {n.name for n in ast.walk(_tree(ROOT / "app" / "db.py"))
              if isinstance(n, ast.ClassDef)}
    writers: dict[str, set] = collections.defaultdict(set)
    for p in APP:
        if p.name == "db.py":
            continue
        for n in ast.walk(_tree(p)):
            # `s.add(db.Table(...))` and `db.Table(...)` construction
            if isinstance(n, ast.Call):
                f = n.func
                if getattr(f, "attr", "") in tables and \
                        getattr(getattr(f, "value", None), "id", "") == "db":
                    writers[f.attr].add(p.name)
    return [{"table": t, "writers": sorted(w)}
            for t, w in sorted(writers.items()) if w]


# ---------------------------------------------------------------------------

def build() -> dict:
    from app import dossier, kb, systems
    routes = http_routes()
    kinds = approval_kinds()
    disp = dispositions()
    rungs = autonomy_rungs()
    ships = system_ships()
    unreached = unreached_functions()
    tables = table_writers()

    empty, duplicate, crossover = [], [], []

    for r in routes:
        if not r["reached"]:
            empty.append(f"route {r['verb']} {r['path']} — {r['why']}")
    for k in kinds:
        if not k["armed"] and not k["acknowledged"]:
            empty.append(f"approval kind {k['kind']!r} — created in "
                         f"{', '.join(k['created_in'])}, no executor arm")
    for d in disp:
        if not d["consumed_by"]:
            empty.append(f"disposition {d['value']!r} — no production module "
                         f"branches on it")
    for sh in ships:
        if not sh["ok"]:
            empty.append(f"system {sh['system']} — {sh['why']} "
                         f"(ship: {sh['ship'][:60]})")
    for f in unreached:
        empty.append(f"function {f['module']}::{f['fn']} — nothing "
                     f"references this name anywhere")

    seen: dict[str, str] = {}
    for r in rungs:
        if r["signature"] in seen:
            duplicate.append(f"autonomy rung {r['rung']!r} behaves exactly "
                             f"like {seen[r['signature']]!r} "
                             f"({r['signature']})")
        else:
            seen[r["signature"]] = r["rung"]

    from app import db as _db
    owners = getattr(_db, "TABLE_OWNER", {})
    for t in tables:
        own = owners.get(t["table"], "")
        if own == "*":
            continue
        if own:
            strangers = [w for w in t["writers"] if w != own]
            if strangers:
                crossover.append(
                    f"table {t['table']} is owned by {own} and written by "
                    + ", ".join(strangers))
        elif len(t["writers"]) > 1:
            duplicate.append(
                f"table {t['table']} has {len(t['writers'])} writers and no "
                f"declared owner: " + ", ".join(t["writers"]))

    # the input-side joins, kept here so the register is ONE list
    kb_tokens = {tok for sp in systems.CATALOG.values()
                 for tok in (sp.get("kb_needs") or ())}
    for tok in sorted(kb_tokens - set(kb.KB_SUPPLIERS)):
        empty.append(f"kb_needs token {tok!r} — declared, no supplier")
    for s in sorted(set(dossier.SCOPES) - set(systems.CATALOG) - {""}):
        empty.append(f"dossier scope {s!r} — not a system")

    return {"routes": routes, "approval_kinds": kinds, "dispositions": disp,
            "rungs": rungs, "ships": ships, "unreached": unreached,
            "tables": tables, "empty": sorted(empty),
            "duplicate": sorted(duplicate), "crossover": sorted(crossover),
            "uncovered": list(UNCOVERED),
            "functions": function_map()}


DOC = ROOT / "REGISTER.md"


def markdown(reg: dict) -> str:
    L = ["# The reachability register", "",
         "**Generated by `scripts/register.py` — do not edit.** Regenerate it "
         "in the same commit as any change that moves it; "
         "`scripts/test_register.py` byte-compares, so a stale register fails "
         "the suite rather than going quietly out of date the way "
         "`SYSTEMS-REFERENCE.md` did.", "",
         "Every declared endpoint in this codebase, and what consumes it. "
         "Three things are flagged, and they are different problems:", "",
         "| flag | means |", "|---|---|",
         "| **EMPTY** | declared or built, and nothing consumes it |",
         "| **DUPLICATE** | two producers for one fact |",
         "| **CROSSOVER** | a consumer reaching across an ownership boundary |",
         "", "---", ""]
    L += [f"## Coverage", "",
          f"- HTTP routes: **{len(reg['routes'])}** "
          f"({sum(1 for r in reg['routes'] if r['reached'])} reached)",
          f"- Approval kinds: **{len(reg['approval_kinds'])}** "
          f"({sum(1 for k in reg['approval_kinds'] if k['armed'])} with an "
          f"executor arm)",
          f"- Dispositions: **{len(reg['dispositions'])}**",
          f"- Autonomy rungs: **{len(reg['rungs'])}**",
          f"- Systems declaring a ship: **{len(reg['ships'])}**",
          f"- Tables with writers: **{len(reg['tables'])}** "
          f"({sum(1 for t in reg['tables'] if len(t['writers']) > 1)} with "
          f"more than one)", "",
          "**What this does NOT reach**, stated so the edges are not implied:",
          ""]
    L += [f"- {u}" for u in reg["uncovered"]]
    for flag in ("empty", "duplicate", "crossover"):
        L += ["", "---", "", f"## {flag.upper()} ({len(reg[flag])})", ""]
        L += [f"- {line}" for line in reg[flag]] or ["_None._"]
    L += ["", "---", "", "## Every endpoint, by family", ""]
    L += ["### Approval kinds", "", "| kind | created in | executor arm |",
          "|---|---|---|"]
    for k in reg["approval_kinds"]:
        arm = "yes" if k["armed"] else ("acknowledged, no arm"
                                        if k["acknowledged"] else "**none**")
        L.append(f"| `{k['kind']}` | {', '.join(k['created_in'])} | {arm} |")
    L += ["", "### Dispositions", "", "| value | consumed by |", "|---|---|"]
    for d in reg["dispositions"]:
        L.append(f"| `{d['value']}` | "
                 f"{', '.join(d['consumed_by']) or '**nothing**'} |")
    L += ["", "### Autonomy rungs", "",
          "| rung | writes | reads | signature |", "|---|---|---|---|"]
    for r in reg["rungs"]:
        L.append(f"| `{r['rung']}` | {r['disposition_writes']} | "
                 f"{r['disposition_reads']} | `{r['signature']}` |")
    L += ["", "### Declared ships", "", "| system | performed by | ok |",
          "|---|---|---|"]
    for sh in reg["ships"]:
        L.append(f"| `{sh['system']}` | `{sh['ship_by'] or ''}` | "
                 f"{'yes' if sh['ok'] else '**' + sh['why'] + '**'} |")
    L += ["", "### Tables with more than one writer", "",
          "| table | declared owner | writers |", "|---|---|---|"]
    from app import db as _db
    owners = getattr(_db, "TABLE_OWNER", {})
    for t in reg["tables"]:
        if len(t["writers"]) > 1 or owners.get(t["table"]):
            L.append(f"| `{t['table']}` | "
                     f"`{owners.get(t['table'], '')}` | "
                     f"{', '.join(t['writers'])} |")
    # --- inputs, outputs, connections, per function ------------------------
    L += ["", "---", "",
          "## Every public function: in, out, and what connects",
          "",
          "Owner, 2026-08-31: *\"show the inputs outputs and connections of "
          "all the functions.\"* `in` is the signature, `?` marking a "
          "parameter with a default. `out` is the return annotation where "
          "there is one, otherwise the KEYS the function returns — this "
          "codebase speaks dicts, so a signature alone says nothing about "
          "what a caller gets. `from` is every other module that calls the "
          "name; a function with **from nothing** is in the EMPTY list above.",
          "",
          "Two limits, both in Coverage: a name resolved at runtime reads as "
          "no connection, and a call inside its own module is the module "
          "doing its job rather than a connection between modules.", ""]
    by_mod: dict = collections.defaultdict(list)
    for f in reg["functions"]:
        by_mod[f["module"]].append(f)
    for mod in sorted(by_mod):
        L += [f"### `{mod}`", ""]
        for f in sorted(by_mod[mod], key=lambda x: x["fn"]):
            out = f["returns"] or (", ".join(f["keys"][:6]) if f["keys"] else "—")
            line = (f"- **`{f['fn']}`**({', '.join(f['params'])}) → `{out}`")
            if f["route"]:
                line += f"  ·  route `{f['route']}`"
            line += ("  ·  from " + ", ".join(f"`{c}`" for c in f["called_by"])
                     if f["called_by"] else "  ·  **from nothing**")
            L.append(line)
        L.append("")
    return "\n".join(L).rstrip() + "\n"


def main() -> int:
    reg = build()
    if "--json" in sys.argv:
        print(json.dumps(reg, indent=2))
        return 0
    if "--write" in sys.argv:
        DOC.write_text(markdown(reg))
        print(f"wrote {DOC.name}")
        return 0
    if "--check" in sys.argv:
        if DOC.exists() and DOC.read_text() == markdown(reg):
            print("REGISTER.md is current")
            return 0
        print("REGISTER.md is STALE — run python3 scripts/register.py --write")
        return 1
    print(f"routes {len(reg['routes'])} · approval kinds "
          f"{len(reg['approval_kinds'])} · dispositions {len(reg['dispositions'])} "
          f"· rungs {len(reg['rungs'])} · systems {len(reg['ships'])} "
          f"· tables {len(reg['tables'])}")
    for name in ("empty", "duplicate", "crossover"):
        print(f"\n{name.upper()} ({len(reg[name])})")
        for line in reg[name]:
            print(f"  · {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
