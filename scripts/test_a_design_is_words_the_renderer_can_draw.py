"""A design is words the renderer can draw — never a colour, a face or a
copy line — and everything that is not is dropped and said.

INITIATIVE-email-design.md, Phase 1. The vocabulary (`email_design.SCHEMA`)
is one declarative structure that the validator, the RUNBOOK table and —
from Phase 4 — the painter test all derive from; this suite walks it rather
than listing it, so a field added tomorrow is covered the moment it exists.

  1. THE SCHEMA IS CLOSED AND CLEAN: every field has values, a default among
     them and a meaning; no value is a colour, a link or free text.
  2. NORMALISE KEEPS WHAT IS DRAWN AND SAYS WHAT IS NOT: a hex, a face, an
     unknown layout, a bad slot — each dropped with its reason; the result
     is complete and normalising it again changes nothing.
  3. THE HOUSE IS TODAY'S RENDERER: `house()` states the facts the live
     renderer paints, every one of the old look's combinations maps in with
     nothing dropped, and each axis moves the design it claims to.
  4. A DESIGN'S SEQUENCE IS THE RENDERER'S OWN BLOCKS, for every slot in
     every kind.
  5. THE LIBRARY CARRIES IT: filed, normalised, its drops reported; rows
     from before take the house at boot; a re-read carries a design forward.
  6. THE RUNBOOK TABLE IS GENERATED and byte-compared.

    python3 scripts/test_a_design_is_words_the_renderer_can_draw.py
"""
from __future__ import annotations

import itertools
import os
import pathlib
import re
import subprocess
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'ed.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, email_design as ed, email_render as er, email_structures as es, tenants  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _walk(o):
    """Every leaf value in a nested design, with its path."""
    if isinstance(o, dict):
        for k, v in o.items():
            for p, x in _walk(v):
                yield f"{k}.{p}" if p else k, x
    elif isinstance(o, list):
        for i, v in enumerate(o):
            for p, x in _walk(v):
                yield f"[{i}].{p}" if p else f"[{i}]", x
    else:
        yield "", o


_HEXY = re.compile(r"#[0-9a-fA-F]{3,8}\b|https?://")


def main() -> int:
    db.init_db()
    tenants.seed()

    print("— 1. the schema is closed and clean —")
    rows = ed.fields()
    ck("every field has values, a default among them, and a meaning",
       rows and all(v and m and ((d in v) if not isinstance(d, list) else all(x in v for x in d))
                    for _, _, v, d, m in rows), str(len(rows)))
    ck("no value anywhere in the vocabulary is a colour, a link or free text",
       all(not _HEXY.search(str(x)) and (not isinstance(x, str) or x == x.lower().strip())
           for _, _, v, _, _ in rows for x in v))
    ck("the walk covers every group of the schema and the section fields",
       {g for g, *_ in rows} == set(ed.SCHEMA) | {"section"}, str({g for g, *_ in rows}))
    ck("a section's ground may only be a role the brand fills",
       set(ed.SECTION["bg"].values) == set(ed.GROUNDS) and set(ed.GROUNDS) < set(ed.ROLES))

    print("\n— 2. normalise keeps what is drawn and says what is not —")
    raw = {"frame": {"page": "#ffffff", "width": "640", "corner": "round"},
           "type": {"display_family": "Futura", "scale": "poster", "body_size": "15"},
           "palette": {"accent_use": ["buttons", "glow"]},
           "header": {"rule": "true"},
           "sections": [{"kind": "hero", "layout": "overlay", "bg": "dark",
                         "slots": ["kicker", "headline", "image:1", "cta"]},
                        {"kind": "products", "layout": "grid3", "slots": ["products:3"]},
                        {"kind": "proof", "slots": ["quote", "banana", "products:9", "body:2"]},
                        {"kind": "carousel"}, "not a section"],
           "defaults": {"feature": {"bg": "tint"}, "widget": {}},
           "notes": "see https://example.com", "brand": "Acme"}
    d, dropped = ed.normalize(raw)
    said = "\n".join(dropped)
    ck("a hex is dropped and the reason is that a design never names a colour",
       d["frame"]["page"] == "page" and "frame.page '#ffffff': a design never names a colour" in said)
    ck("a face is dropped by name and the default used",
       d["type"]["display_family"] == "serif-editorial" and "'Futura': not a value the renderer draws" in said)
    ck("an unknown field and an unknown part are named",
       "frame.corner: not a field" in said and "brand: not a part of a design" in said)
    ck("a link anywhere is refused as a link", "notes: a design never carries a link" in said)
    ck("digits become the int the field takes; a word becomes the bool",
       d["frame"]["width"] == 640 and d["type"]["body_size"] == 15 and d["header"]["rule"] is True)
    ck("a multi-value field keeps the drawn ones and names the rest",
       d["palette"]["accent_use"] == ["buttons"] and "accent_use 'glow'" in said)
    ck("a bad slot, a count off the scale and a count on a slot that takes none are each said",
       d["sections"][2]["slots"] == ["quote", "products:1", "body"]
       and "slot 'banana': not a slot" in said and "'products:9': a count is 1–6" in said
       and "'body:2': only products and image take a count" in said)
    ck("an unknown kind drops the section; a non-section is dropped; both said",
       len(d["sections"]) == 3 and "kind 'carousel'" in said and "sections[4]: not a section" in said)
    ck("defaults are filled for every kind and an unknown kind is named",
       set(d["defaults"]) == set(ed.KINDS) and d["defaults"]["feature"]["bg"] == "tint"
       and "defaults.widget: not a section kind" in said)
    ck("the result is complete, and normalising it again changes nothing",
       ed.complete(d) and ed.normalize(d) == (d, []))
    def _off_schema(design: dict) -> list[str]:
        """Every leaf that is not a value its field names — walked from the
        schema, so a field added tomorrow is checked the moment it exists."""
        bad = []
        def _chk(fields, obj, path):
            for name, f in fields.items():
                v = obj.get(name)
                ok = (isinstance(v, list) and all(x in f.values for x in v)) if f.many \
                    else (v in f.values and type(v) is type(f.default))
                if not ok:
                    bad.append(f"{path}.{name}={v!r}")
            for name in obj:
                if name not in fields and name not in ("kind", "slots"):
                    bad.append(f"{path}.{name}: not a field")
        for group, fields in ed.SCHEMA.items():
            _chk(fields, design[group], group)
        for kind, sec in design["defaults"].items():
            _chk(ed.SECTION, sec, f"defaults.{kind}")
        for i, sec in enumerate(design["sections"]):
            _chk(ed.SECTION, sec, f"sections[{i}]")
            if sec["kind"] not in ed.KINDS:
                bad.append(f"sections[{i}].kind={sec['kind']!r}")
            for slot in sec["slots"]:
                nm, _, n = slot.partition(":")
                if nm not in ed.SLOTS or (n and (nm not in ed.COUNTED or not 1 <= int(n) <= ed.SLOT_MAX)):
                    bad.append(f"sections[{i}] slot {slot!r}")
        return bad
    ck("every leaf of a normalised design is a value its field names — walked from the schema",
       not _off_schema(d) and not _off_schema(ed.normalize(every_raw := {"sections": [
           {"kind": k, "slots": list(ed.SLOTS)} for k in ed.KINDS]})[0]), str(_off_schema(d)))
    ck("and the walk itself can go red: a design with a hex in a ground is off the schema",
       _off_schema({**d, "frame": {**d["frame"], "page": "#fff"}}) == ["frame.page='#fff'"])
    ck("nothing at all is a full design with nothing dropped",
       ed.normalize(None)[1] == [] and ed.complete(ed.normalize({})[0]))

    print("\n— 3. the house is today's renderer —")
    h = ed.house()
    facts = {("frame", "width"): 600, ("frame", "container"): "card", ("frame", "border"): True,
             ("header", "logo"): "left", ("header", "nav"): "inline", ("header", "case"): "upper",
             ("type", "display_family"): "serif-editorial", ("type", "body_family"): "sans",
             ("type", "body_size"): 16, ("type", "kicker"): "accent", ("type", "scale"): "modest",
             ("cta", "style"): "filled", ("cta", "radius"): "soft", ("dividers", "style"): "thin",
             ("footer", "align"): "center", ("footer", "socials"): "words", ("palette", "mood"): "light"}
    bad = {k: h[k[0]][k[1]] for k, v in facts.items() if h[k[0]][k[1]] != v}
    ck("house() states what the live renderer paints — the card, the mark left, the kicker "
       "in the accent, a filled soft button, a thin rule, a centred footer", not bad, str(bad))
    ck("the house has no fixed order and its hero is contained",
       h["sections"] == [] and h["defaults"]["hero"]["image"] == "contained"
       and h["defaults"]["hero"]["layout"] == "stack")
    ck("the house is complete and carries no colour or link",
       ed.complete(h) and not [p for p, x in _walk(h) if _HEXY.search(str(x))])
    axes = list(er.LOOK.items())
    keys = [k for k, _ in axes]
    combos = list(itertools.product(*[list(v) for _, v in axes]))
    houses = {c: ed.house(dict(zip(keys, c))) for c in combos}
    ck(f"every one of the {len(combos)} old looks maps into the vocabulary — walked, not listed",
       len(houses) == len(combos) and all(ed.complete(x) for x in houses.values()))
    moved = {}
    for i, (axis, vals) in enumerate(axes):
        base = list(combos[0])
        outs = []
        for v in vals:
            c = list(base); c[i] = v
            outs.append(repr(houses[tuple(c)]))
        moved[axis] = len(set(outs)) == len(vals)
    ck("each look axis moves the design — no axis is folded in as nothing",
       all(moved.values()), str({k: v for k, v in moved.items() if not v}))
    ov = houses[tuple("overlay" if k == "hero" else v for k, v in zip(keys, combos[0]))]
    ck("the overlay hero becomes words on a dark ground; a pill becomes a pill",
       ov["defaults"]["hero"] == {**ov["defaults"]["hero"], "layout": "overlay",
                                 "bg": "dark", "text_on_image": True}
       and ed.house({"cta": "pill"})["cta"]["radius"] == "pill")

    print("\n— 4. a design's sequence is the renderer's own blocks —")
    every = {"sections": [{"kind": k, "slots": list(ed.SLOTS) + ["products:2", "image:3"]}
                          for k in ed.KINDS]}
    seq = ed.sequence_of(ed.normalize(every)[0])
    ck("every slot in every kind becomes a block the renderer builds, or no block at all",
       seq and all(b in er._BLOCKS for b in seq), str(sorted(set(seq) - set(er._BLOCKS))))
    ck("a hero section is one hero block, then its ask",
       ed.sequence_of(ed.normalize({"sections": [{"kind": "hero", "slots": [
           "kicker", "headline", "sub", "image:1", "cta"]}]})[0]) == ["hero", "cta"])
    ck("the house has no sequence of its own", ed.sequence_of(h) == [])
    s = ed.summary(ed.normalize(every)[0])
    ck("the summary is one line naming the key, the type, the ask and the count",
       "\n" not in s and "key" in s and "over" in s and "ask" in s and "sections" in s, s)

    print("\n— 5. the library carries it —")
    a = es.file_structure(name="filed with a look", sequence=["hero", "heading", "text", "cta"],
                          source="hand", review="approved",
                          look={"hero": "split", "cta": "link", "products": "grid2"})
    row = next(r for r in es.library() if r["id"] == a["id"])
    ck("a structure filed with a look carries the house design with that look folded in",
       row["design"]["defaults"]["hero"]["layout"] == "split-left"
       and row["design"]["cta"]["style"] == "arrow"
       and row["design"]["defaults"]["products"]["layout"] == "grid2" and a["dropped"] == [])
    b = es.file_structure(name="filed with a design", sequence=["heading", "text", "cta"],
                          source="swipe", review="proposed",
                          design={"type": {"display_family": "Didot", "scale": "poster"},
                                  "frame": {"page": "#000"},
                                  "sections": [{"kind": "intro", "slots": ["headline", "body", "cta"]}]})
    rb = next(r for r in es.library() if r["id"] == b["id"])
    ck("a structure filed with a design stores it normalised and reports what was dropped",
       rb["design"]["type"]["scale"] == "poster" and rb["design"]["type"]["display_family"] == "serif-editorial"
       and rb["design"]["frame"]["page"] == "page" and len(b["dropped"]) == 2, str(b["dropped"]))
    again = es.file_structure(name="same sequence, a design now", sequence=["hero", "heading", "text", "cta"],
                              source="swipe", review="proposed",
                              design={"palette": {"mood": "dark"}})
    ra = next(r for r in es.library() if r["id"] == a["id"])
    ck("a re-read of an existing sequence carries its design forward, approval untouched",
       again["existing"] and again["id"] == a["id"] and ra["design"]["palette"]["mood"] == "dark"
       and ra["review"] == "approved")
    with db.SessionLocal() as s:
        for r in s.query(db.EmailStructure).all():
            r.design = {}
        s.commit()
    n = es.backfill_designs()
    rows2 = {r["id"]: r for r in es.library()}
    ck("rows from before designs existed take the house with their look at boot; a second boot writes nothing",
       n == 2 and rows2[a["id"]]["design"]["defaults"]["hero"]["layout"] == "split-left"
       and ed.complete(rows2[b["id"]]["design"]) and es.backfill_designs() == 0)
    with db.SessionLocal() as s:
        s.get(db.EmailStructure, a["id"]).design = {}
        s.commit()
    db.init_db()
    ck("init_db runs the backfill",
       next(r for r in es.library() if r["id"] == a["id"])["design"].get("frame"))
    ck("the column is on the model", hasattr(db.EmailStructure, "design"))

    print("\n— 6. the RUNBOOK table is generated —")
    gen = ROOT / "scripts" / "gen_email_design_doc.py"
    out = subprocess.run([sys.executable, str(gen), "--check"], capture_output=True, text=True)
    ck("RUNBOOK §6d's vocabulary table is byte-identical to what the code generates now",
       out.returncode == 0, (out.stdout + out.stderr).strip()[-160:])
    sys.path.insert(0, str(ROOT / "scripts"))
    import gen_email_design_doc as g  # noqa: E402
    doc = (ROOT / "RUNBOOK.md").read_text()
    stale = g.splice(doc, g.BEGIN + "\nstale\n" + g.END)
    ck("a stale table is a different document — the check can go red",
       stale != doc and g.splice(stale, g.render()) == doc)
    ck("every field of the vocabulary is a row of the table",
       all(f"`{grp}.{name}`" in doc for grp, name, *_ in ed.fields()))

    print("\n" + ("ALL PASSED" if not _fail else f"{len(_fail)} FAILED: {_fail}"))
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
