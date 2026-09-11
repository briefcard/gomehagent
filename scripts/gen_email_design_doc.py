"""Regenerate the design-vocabulary table in `RUNBOOK.md` §6d from the code.

The look table in §6d was hand-written on 2026-09-11 and would have gone
stale the first time an axis moved — the `SYSTEMS-REFERENCE.md` failure one
level down. So the vocabulary a design may use is written HERE, from
`email_design.SCHEMA`, between markers; the suite regenerates and
byte-compares, and the document cannot drift from the code without the
suite going red in the same commit that moved it (the owner's rule: generate
it, or delete it).

    python3 scripts/gen_email_design_doc.py           # rewrite in place
    python3 scripts/gen_email_design_doc.py --check    # exit 1 if stale
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
DOC = ROOT / "RUNBOOK.md"
BEGIN = "<!-- BEGIN GENERATED: the design vocabulary — scripts/gen_email_design_doc.py -->"
END = "<!-- END GENERATED: the design vocabulary -->"

from app import email_design as ed  # noqa: E402


def _val(v) -> str:
    if isinstance(v, bool):
        return "on" if v else "off"
    return str(v)


def render() -> str:
    lines = [BEGIN, "",
             "**The design vocabulary (INITIATIVE-email-design.md, Phase 1 — filed on "
             "every structure; drawn from Phase 4).** A design is the whole of how an "
             "email is built, in these words and no others: a ground is a ROLE the "
             "brand's palette fills, a face is a CLASS the brand's own face overrides, "
             "a slot is a KIND of content the drafter writes. Generated from "
             "`email_design.SCHEMA`; do not edit by hand.", "",
             "| field | values | default | what it means |", "|---|---|---|---|"]
    for group, name, values, default, meaning in ed.fields():
        vals = " · ".join(_val(v) for v in values)
        dflt = (", ".join(_val(v) for v in default) if isinstance(default, list)
                else _val(default))
        lines.append(f"| `{group}.{name}` | {vals} | {dflt} | {meaning} |")
    lines += ["",
              f"Section kinds: {' · '.join(ed.KINDS)}. Slots: {' · '.join(ed.SLOTS)} "
              f"({' and '.join(ed.COUNTED)} take a count, 1–{ed.SLOT_MAX}). "
              f"Grounds a design may name: {' · '.join(ed.GROUNDS)}; the roles a brand "
              f"supplies: {' · '.join(ed.ROLES)}.",
              "", END]
    return "\n".join(lines)


def splice(doc: str, block: str) -> str:
    a, b = doc.find(BEGIN), doc.find(END)
    if a < 0 or b < 0:
        raise SystemExit(f"markers not found in {DOC.name}")
    return doc[:a] + block + doc[b + len(END):]


def main() -> int:
    doc = DOC.read_text()
    new = splice(doc, render())
    if "--check" in sys.argv:
        if new != doc:
            print(f"{DOC.name} is stale — run: python3 scripts/gen_email_design_doc.py")
            return 1
        print(f"{DOC.name} matches the code")
        return 0
    DOC.write_text(new)
    print(f"wrote {DOC.name} — {len(ed.fields())} fields")
    return 0


if __name__ == "__main__":
    sys.exit(main())
