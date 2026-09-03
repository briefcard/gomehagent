"""Regenerate the per-system half of `SYSTEMS-REFERENCE.md` from the code.

The document said `campaign_email` needs "tone, banned_claims, entity, claim".
`systems.CATALOG` declared seven tokens. It had been wrong since the walk that
added the other three, and nothing said so — because a hand-written reference
has no way to notice that what it describes has moved.

So the half that IS derivable is derived. Everything between the GENERATED
markers is written by this script from `systems.CATALOG`, `skill.REGISTRY`,
`planner.PLANNERS` and `dossier.SCOPES`; everything outside them is judgement
that no walk produces — the design rules §6 pays for in defects, the
integration notes, the cross-system joins — and stays hand-written where it
is. Splicing rather than splitting keeps `SYSTEMS-REFERENCE §6` resolving from
the eight places that cite it, `app/kb.py` included.

`test_catalog_vocabulary.py` regenerates and byte-compares, so the document
cannot drift from the code again without the suite going red in the same
commit that moved it.

    python3 scripts/gen_systems_reference.py           # rewrite in place
    python3 scripts/gen_systems_reference.py --check    # exit 1 if stale
"""
import os
import pathlib
import sys
import tempfile

os.environ.setdefault(
    "DATABASE_URL", f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'gen.db')}")
os.environ.setdefault("APPROVAL_SECRET", "s3cret")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOC = ROOT / "SYSTEMS-REFERENCE.md"

BEGIN = "<!-- BEGIN GENERATED: the ten systems — scripts/gen_systems_reference.py -->"
END = "<!-- END GENERATED -->"

from app import dossier, planner, skill, systems  # noqa: E402
import app.skill_pack  # noqa: F401,E402  (registers the skills)


def _skill_for(key: str):
    for sk in skill.REGISTRY.values():
        if getattr(sk, "system_key", "") == key:
            return sk
    return None


def _plan_field(f: dict) -> str:
    star = "*" if f.get("required") else ""
    kind = f.get("kind") or ""
    choices = f.get("choices") or ()
    bits = [b for b in (kind, "|".join(choices)) if b]
    return f"`{f['key']}`{star}" + (f" ({', '.join(bits)})" if bits else "")


def body() -> str:
    out = [
        "",
        f"## 2. The {len(systems.CATALOG)} systems",
        "",
        "**Generated — do not edit between the markers.** Every line below is "
        "read out of `systems.CATALOG`, `skill.REGISTRY`, `planner.PLANNERS` "
        "and `dossier.SCOPES` by `scripts/gen_systems_reference.py`. The prose "
        "sections around it are judgement and stay hand-written.",
        "",
    ]
    for key in sorted(systems.CATALOG):
        sp = systems.CATALOG[key]
        wf = sp.get("workflow") or {}
        sk = _skill_for(key)
        out += [f"### `{key}` — {sp['name']}", "", f"{sp['does']}", ""]

        req = ", ".join(f"`{c}`" for c in sp.get("requires") or ()) or "—"
        any_ = ", ".join(f"`{c}`" for c in sp.get("requires_any") or ())
        conn = req if not any_ else (f"{req}; at least one of {any_}"
                                     if req != "—" else f"at least one of {any_}")
        needs = ", ".join(f"`{n}`" for n in sp.get("kb_needs") or ()) or "—"
        out += [
            f"- **Connections:** {conn}",
            f"- **Knowledge (`kb_needs`):** {needs}"
            + ("" if sp.get("kb_needs") else
               f"  ·  `needs_kb={bool(sp.get('needs_kb'))}`, so readiness "
               f"falls back to `kb.completeness`"),
        ]
        if sk:
            params = ", ".join(f"`{p}`" for p in sk.params) or "—"
            const = ", ".join(f"`{c}`" for c in (sk.constitutive or ())) or "none"
            out += [
                f"- **Skill** `{sk.key}` — produces `{sk.produces}`, "
                f"tier {sk.tier}, writes={bool(sk.writes)}",
                f"  - parameters: {params}",
                f"  - constitutive (no draft without it): {const}",
            ]
        elif wf.get("skill"):
            out.append(f"- **Skill** `{wf['skill']}` — DECLARED, not in the "
                       f"registry")
        else:
            out.append("- **Skill:** none — nothing generates for this system")

        out.append(f"- **Planner:** "
                   + (f"`{planner.PLANNERS[key].__name__}`" if key in planner.PLANNERS
                      else "none — plans are filed by hand or by another system"))
        if wf.get("cadence"):
            out.append("- **Cadence knobs:** "
                       + ", ".join(f"`{k}`={v}"
                                   for k, v in sorted(wf["cadence"].items())))
        if wf.get("plan_fields"):
            out.append("- **Plan fields** (the plan UI; `*` required): "
                       + ", ".join(_plan_field(f) for f in wf["plan_fields"]))
        for label, k in (("Unit", "unit"), ("Artifact", "artifact"),
                         ("Ship", "ship"), ("Measure", "measure")):
            if wf.get(k):
                out.append(f"- **{label}:** {wf[k]}")
        out.append(f"- **Brand-document scope:** "
                   + ", ".join(dossier.SCOPES[key]))
        out.append("")
    out += ["### 2c. The effectiveness map — what measures each system, and "
            "what learns from it", "",
            "Read out of `systems.EFFECTIVENESS` and resolved to callables by "
            "`systems.effectiveness()`. A blank cell is a named gap, never an "
            "omission; `edits.record` wrote draft-vs-sent deltas on every "
            "reply for weeks and no generator read one, which is the defect "
            "this table exists to make visible.", "",
            "| system | measured by | learns into | gap |",
            "|---|---|---|---|"]
    for r in systems.effectiveness():
        mf = f"`{r['measure_fn']}`" + ("" if r["measure_ok"] else " ✗") if r["measure_fn"] else "—"
        li = f"`{r['learns_into']}`" + ("" if r["learns_ok"] else " ✗") if r["learns_into"] else "—"
        out.append(f"| `{r['system']}` | {mf} | {li} | {r['gap'] or r['how']} |")
    out.append("")
    return "\n".join(out)


def rendered() -> str:
    doc = DOC.read_text()
    head, _, rest = doc.partition(BEGIN)
    _, _, tail = rest.partition(END)
    assert head and tail, "the GENERATED markers are missing from the document"
    return head + BEGIN + "\n" + body() + END + tail


def main() -> int:
    new = rendered()
    if "--check" in sys.argv:
        if DOC.read_text() == new:
            print("SYSTEMS-REFERENCE.md is current")
            return 0
        print("SYSTEMS-REFERENCE.md is STALE — run "
              "python3 scripts/gen_systems_reference.py")
        return 1
    DOC.write_text(new)
    print(f"wrote {DOC.name} — {len(systems.CATALOG)} systems")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
