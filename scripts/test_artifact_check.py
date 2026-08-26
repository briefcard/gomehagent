"""Does the rendered thing hold together — and is it kept.

Both halves of what the owner reported on 2026-08-26, driven by the ACTUAL
Baci campaign he pasted rather than by a fixture written to pass.

Four defects were in that one email and every one is findable without asking
a model anything, which is why this is deterministic code:

  * `picnic.nic.` — a word repeating its own tail;
  * the prose said "the Acrylic Pitcher & Glasses Set is the one" while every
    link and image in the artifact was the Blue Table Runner;
  * a pull-quote holding a catalogue description verbatim;
  * `<span>P.S.</span> <p>` opening a block inside an inline run.

    python3 scripts/test_artifact_check.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'ac.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import artifact_check, db, ledger  # noqa: E402

_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


# The real thing, trimmed to the parts that carry the defects.
EMAIL = (
    '<img width="600" alt="Blue Table Runner - Portofino" src="x">'
    '<p>It started with a pitcher. Someone brought it to a Sunday lunch.</p>'
    '<td style="font-style:italic;font-size:19px">A colorful acrylic pitcher '
    'with a set of 6 matching water glasses &mdash; shatterproof outdoor '
    'drinkware for patio, pool &amp; picnic.nic.</td>'
    '<p>If your setup leans brighter and more casual, the Acrylic Pitcher '
    '&amp; Glasses Set is the one. Shatterproof and cohesive.</p>'
    '<a href="https://bacimilanousa.com/products/blue-table-runner-portofino">'
    'Blue Table Runner - Portofino</a>'
    '<div><span style="font-weight:600">P.S.</span> <p>If you are not sure '
    'which piece fits, browse the full table.</p></div>'
    '<a href="[[unsubscribe_link]]">Unsubscribe</a>')


def main() -> int:
    db.init_db()
    found = {f["rule"]: f for f in artifact_check.check(EMAIL)}
    print("— the four defects in the real email —")
    ck("the mangled word is caught", "mangled_word" in found,
       found.get("mangled_word", {}).get("detail", ""))
    ck("and the fix names the cause, not the symptom",
       "cut and re-joined" in found.get("mangled_word", {}).get("fix", ""),
       "a copywriter cannot fix this; the source string can")
    ck("a product recommended and never linked is caught",
       "unlinked_subject" in found,
       found.get("unlinked_subject", {}).get("detail", ""))
    ck("catalogue copy in a quote slot is caught", "boilerplate_in_quote" in found)
    ck("a block tag inside an inline run is caught", "block_in_inline" in found)

    print("\n— severity is not uniform, deliberately —")
    ck("the mangled word BLOCKS", "mangled_word" in artifact_check.BLOCKING)
    ck("so does an instruction the reader cannot follow",
       "unlinked_subject" in artifact_check.BLOCKING,
       "'X is the one' with no link to X is a call to action with nowhere to go")
    ck("the two heuristics only FLAG",
       "boilerplate_in_quote" not in artifact_check.BLOCKING
       and "block_in_inline" not in artifact_check.BLOCKING,
       "a heuristic that stops a send is one somebody switches off")
    ck("blocking() returns exactly those",
       {f["rule"] for f in artifact_check.blocking(artifact_check.check(EMAIL))}
       == {"mangled_word", "unlinked_subject"})

    print("\n— and it does not fire on clean copy —")
    clean = ('<p>The Portofino runner is woven in a single blue.</p>'
             '<a href="https://x.com/products/blue-table-runner-portofino">'
             'Blue Table Runner - Portofino</a>'
             '<a href="[[unsubscribe_link]]">Unsubscribe</a>')
    ck("nothing flagged", artifact_check.check(clean) == [],
       str(artifact_check.check(clean))[:120])
    ck("a linked recommendation is fine",
       artifact_check.check(
           '<p>The Blue Table Runner is the one.</p>'
           '<a href="/products/blue-table-runner">Blue Table Runner</a>') == [])
    ck("a known ESP placeholder is not a leak",
       not [f for f in artifact_check.check(
           '<p>Hi [[contact.first_name]]</p>') if f["rule"] == "placeholder_leak"])
    ck("an unknown one is",
       [f for f in artifact_check.check('<p>Hi [[nobody.fills.this]]</p>')
        if f["rule"] == "placeholder_leak"])

    print("\n— the artifact is kept whole when there is nowhere to push it —")
    big = "<html>" + ("<p>a rendered article.</p>" * 200) + "</html>"
    out = ledger.record(tenant="baci", system_key="blog", format="cms_article",
                        body=big, status="draft")
    oid = out if isinstance(out, str) else getattr(out, "id", "")
    with db.SessionLocal() as s:
        row = s.get(db.Output, oid)
        kept = (s.query(db.ArtifactBody)
                .filter(db.ArtifactBody.output_id == oid).first())
    ck("the ledger row still holds only its short rendering",
       row is not None and len(row.body) <= 2000,
       "that table is a ledger of decisions and its queries depend on it")
    ck("but the artifact itself is kept", kept is not None and kept.bytes == len(big),
       "an approved article with no CMS connected existed nowhere in full")
    ck("with no destination, which is the case it exists for",
       kept is not None and kept.destination == "")
    ck("and it carries the format", kept is not None and kept.format == "cms_article")

    small = ledger.record(tenant="baci", system_key="service_desk",
                          format="gmail_draft", body="<p>short reply</p>",
                          status="draft")
    sid = small if isinstance(small, str) else getattr(small, "id", "")
    with db.SessionLocal() as s:
        ck("a short reply is NOT copied into it",
           s.query(db.ArtifactBody).filter(
               db.ArtifactBody.output_id == sid).first() is None,
           "this is for artifacts, not for every row")

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
