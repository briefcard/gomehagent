"""Every drafting skill obeys the same contract — computed, not remembered.

The owner's question, 2026-08-31: "Are you making sure all of these updates are
true of existing and incoming systems?" The honest answer was no. Each rule was
true because somebody put it in that file, one skill at a time — which is the
exact failure this codebase keeps closing: `bundle["audiences"]` was read by
every drafter and supplied by nobody because nothing DECLARED the obligation.

So the obligations are computed from the registry rather than listed here. A
skill added next month is measured by the same walk, and a new one that misses
any of them fails this suite instead of shipping half-wired.

WHAT IS ASSERTED, and why each is load-bearing:

  · A draft or a proposal COMMITS to a subject, and that commitment reaches
    `emit`. `Context.emit` runs the coherence axis only when `commitment` is
    not None, so a skill that builds one and does not pass it silently runs
    ZERO coherence rules — which is exactly what `blog_article` did.
  · Every declared parameter is READ. An accepted-and-ignored parameter is the
    caller believing it asked for something it did not get (`audience_key` on
    campaign_email was one for a fortnight).
  · Every parameter READ is declared, or `run` refuses it at the door and the
    read is dead code that can never fire (`offer` was one).
  · One-to-many work names its reader, and only where a reader is a coherent
    idea — a report has no audience and a reply has an actual person.

Run: python3 scripts/test_skill_conformance.py
"""
import ast
import os
import pathlib
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'sc.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import skill, systems  # noqa: E402

_fail = []

#: Skills that produce a draft or a proposal but are ONE-TO-ONE: the reader is
#: an actual person on the other end, not a persona. Owner, 2026-08-31:
#: "Audience only applies in plural to segments in mass marketing."
#: Listed rather than derived because it is a judgement about the WORK, and a
#: new skill should have to state which kind it is rather than inherit one.
# A reply to one person has its reader by definition; the rule that a piece
# written for everybody is written for nobody is about one-to-many work.
# `lead_reply` is the same responder as `inbound_reply` under its own
# governance envelope (2026-09-03), so it is one-to-one for the same reason.
ONE_TO_ONE = {"inbound_reply", "lead_reply"}

#: Draft/proposal skills that legitimately have no reader to name. An article
#: is read by whoever searched, so its subject comes from the keyword rather
#: than from a segment somebody chose.
NO_SEGMENT = {"blog_article", "catalog_seo_rewrite"}


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _walk():
    """(skill_key, Skill, reachable-fn-names, source) for the whole pack."""
    src = pathlib.Path(__file__).resolve().parent.parent / "app" / "skill_pack.py"
    text = src.read_text()
    tree = ast.parse(text)
    fns = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    runfn = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "Skill":
            kw = {k.arg: k.value for k in n.keywords}
            runfn[kw["key"].value] = getattr(kw.get("run"), "id", "")

    def reach(fn, seen=None):
        seen = seen or set()
        if fn in seen or fn not in fns:
            return set()
        seen.add(fn)
        out = {fn}
        for x in ast.walk(fns[fn]):
            if isinstance(x, ast.Call) and isinstance(x.func, ast.Name) \
                    and x.func.id in fns:
                out |= reach(x.func.id, seen)
        return out
    return fns, runfn, reach


def main() -> int:
    skill.registered()
    fns, runfn, reach = _walk()
    drafters = [(k, s) for k, s in sorted(skill.REGISTRY.items())
                if s.produces in ("draft", "proposal")]
    ck("the pack has drafting skills to measure", len(drafters) >= 3,
       str([k for k, _ in drafters]))

    print("\n— every draft commits to a subject, and the gate receives it —")
    for k, sk in drafters:
        emits, withc, commits = 0, 0, 0
        for f in reach(runfn.get(k, "")):
            for x in ast.walk(fns[f]):
                if not isinstance(x, ast.Call) or not isinstance(x.func, ast.Attribute):
                    continue
                if x.func.attr == "commit":
                    commits += 1
                if x.func.attr == "emit":
                    emits += 1
                    if any(kw.arg == "commitment" for kw in x.keywords):
                        withc += 1
        ck(f"  {k} declares what it is about", commits >= 1,
           "coherence.commit is how every skill states its subject")
        ck(f"  {k} hands that commitment to emit", emits and withc == emits,
           f"{withc} of {emits} emit site(s) — a commitment that stops short "
           f"of emit runs ZERO coherence rules")

    # ...AND THE WALK ITSELF BITES. A conformance check that has been quietly
    # neutered passes exactly like one that is working, and nothing else in the
    # repo would notice — the sabotage harness reported MISSED on precisely
    # that mutant. So the walk is run against a body that IS in violation, and
    # is required to see it.
    _probe = ast.parse(
        "def _v(ctx):\n"
        "    c = coherence.commit('entity', 'x')\n"
        "    return ctx.emit('body', fmt='x')\n")
    _pf = {n.name: n for n in ast.walk(_probe) if isinstance(n, ast.FunctionDef)}
    _e = _w = 0
    for x in ast.walk(_pf["_v"]):
        if isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute) \
                and x.func.attr == "emit":
            _e += 1
            if any(kw.arg == "commitment" for kw in x.keywords):
                _w += 1
    ck("the walk CATCHES a body that commits and never hands it over",
       _e == 1 and _w == 0,
       "a check that cannot fail is decoration, and this one guards every "
       "skill written from here on")

    print("\n— declared and read agree, in both directions —")
    # Parameters the RUNNER consumes on the skill's behalf, so a body that
    # never touches `ctx.params` for them is correct rather than negligent.
    # `OWNER_INPUT` is derived from `skill` rather than restated, so a new
    # owner-input parameter is covered here the day it is added — restating it
    # would be the second list that goes stale, which is the defect this whole
    # suite exists to prevent.
    RUNNER_READS = ({"utterance", "contact_id", "entity_key", "thread_id",
                     "override_needs", "audience_key", "revision_notes"}
                    | set(skill.OWNER_INPUT))
    for k, sk in sorted(skill.REGISTRY.items()):
        read = set()
        for f in reach(runfn.get(k, "")):
            for x in ast.walk(fns[f]):
                if (isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute)
                        and x.func.attr == "get"
                        and isinstance(x.func.value, ast.Attribute)
                        and x.func.value.attr == "params"
                        and x.args and isinstance(x.args[0], ast.Constant)):
                    read.add(x.args[0].value)
        orphan = sorted(read - set(sk.params))
        ck(f"  {k} reads nothing it did not declare", not orphan,
           f"{orphan} — `run` refuses undeclared params, so these reads can "
           f"never fire" if orphan else "")
        dead = sorted(set(sk.params) - read - RUNNER_READS)
        ck(f"  {k} declares nothing it never reads", not dead,
           f"{dead} — accepted and silently ignored" if dead else "")

    print("\n— one-to-many work names its reader —")
    for k, sk in drafters:
        if k in ONE_TO_ONE or k in NO_SEGMENT:
            # REPORTED, not asserted. The exemption is a fact about the
            # DECLARATION above, and printing [ ok ] for each one made the
            # exempt skills look checked rather than skipped.
            print(f"       skipped: {k} is exempt — "
                  + ("one-to-one" if k in ONE_TO_ONE else "no chosen segment"))
            continue
        ck(f"  {k} requires a reader", "audience_key" in (sk.requires or ()),
           "a campaign or an ad written for everybody is written for nobody")
        ck(f"  {k} only requires one where one can exist",
           sk.requires_when is not None,
           "an account that has authored no persona must still produce")

    print("\n— one vocabulary, one definition —")
    # The owner, 2026-08-31: "I hope you do not have duplicates / reworking of
    # the same inputs inside the system." There were two `OWNER_INPUT` tuples —
    # `bundle.py` and `skill.py`, same literal, near-identical comments,
    # neither importing the other and nothing pinning them equal. Adding a
    # third owner input to one would have left the other silently unaware.
    from app import bundle as _pkg
    ck("OWNER_INPUT has exactly one definition",
       skill.OWNER_INPUT is _pkg.OWNER_INPUT,
       "derived, not restated — a second copy is the drift this suite exists "
       "to prevent")
    ck("  and every member of it is a declared package part",
       all(k in _pkg.PARTS for k in _pkg.OWNER_INPUT),
       str([k for k in _pkg.OWNER_INPUT if k not in _pkg.PARTS]))
    # ...AND THE HOP ACTUALLY CARRIES THEM. `PARTS` declared `revision_notes`
    # as `supplies="skill.run"` while `run` wrote only offer and deadline, so
    # the declared supplier was fiction and three skills quietly supplied it
    # with a private hop apiece.
    _src = (pathlib.Path(__file__).resolve().parent.parent
            / "app" / "skill_pack.py").read_text()
    ck("no skill keeps a private params-to-bundle hop",
       'ctx.bundle["revision_notes"] =' not in _src,
       "the one route in `skill.run` is the route, or a fourth skill invents "
       "a fifth")

    print("\n— every skill binds to a real system —")
    for k, sk in sorted(skill.REGISTRY.items()):
        ck(f"  {k} names a system in the catalogue",
           sk.system_key in systems.CATALOG, sk.system_key)

    print("\n" + ("all checks passed" if not _fail
                  else f"{len(_fail)} FAILED:\n  - " + "\n  - ".join(_fail)))
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
