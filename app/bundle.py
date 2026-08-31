"""The brand package — one declared shape that every system receives.

`resolve.resolve` has always returned the unified thing this platform runs on:
one account's voice, rules, proof, buyers, catalogue and history, assembled
once so a generator never gathers its own context and therefore cannot gather
it wrong. What it never had was a **declaration of what is in it**.

That absence is not cosmetic, and it cost two years of output. `bundle
["audiences"]` was read by `funnel.inputs_for` — the function that briefs the
ad, the email and the article on who is reading — and written by nobody.
There was no fallback (claims and objections have one; audiences did not), no
gap note, and no test: `test_funnel` hand-fed an audience straight to
`inputs_for` and stayed green while the live value was `None` in every
drafting system this platform has. Every ad, every campaign and every article
was written in the brand's words because the buyer's words never arrived.

Nothing was broken. Nothing was ever declared, so nothing could notice.

## What this module is

The package, named. `PARTS` says what each part IS, who SUPPLIES it, the tier
it arrives at, and what its ABSENCE means — and that last field is the one
that matters, because this codebase's rule is that a gap is reported and
almost never a veto (`grounding`: *"There should be NO block because of a lack
of data. If it's not there, then don't use it."*). A part whose absence merely
thins the work says so; the one part whose absence makes output UNVERIFIED
says that instead, and it is the only `blocks` in here.

Two checks fall out of the declaration, and they are the point of writing it:

* `verify(bundle)` — a produced bundle against what its tier promised. Runs at
  the end of `resolve`, so a part that stops being supplied is caught on the
  next run rather than by an owner reading thin copy months later.
* `audit()` — every `bundle.get(...)` in the codebase against `PARTS`. A
  consumer reading a part nobody declared is the `audiences` defect exactly,
  and this is what makes it impossible to ship twice.

## Why a declaration rather than a smarter static check

Both were tried on the way here. Inferring the contract from code shape gives
false positives that are worse than no check: `for _k in OWNER_INPUT:
bundle[_k] = ...` reads as "never written" to an AST walk looking for literal
subscripts, and a check that cries wolf about `offer` and `deadline` teaches
people to ignore it in the week it should have caught `audiences`. The
contract has to be *stated*, once, where both the writer and the reader can be
held to it.
"""
from __future__ import annotations

import ast
import pathlib

#: Parameters that are the OWNER'S INSTRUCTION for this run rather than
#: knowledge about the account. They ride the package because the drafters read
#: the package, but they are supplied per-run by a person, not by the KB.
#:
#: A generator inventing a discount or a deadline is the one failure in this
#: layer that costs real money, so both are fields somebody fills — and that is
#: defeated entirely if the field a person filled does not arrive. It did not,
#: for `campaign_email`, for exactly as long as the parameter went undeclared.
#: DEFINED HERE, ONCE. `skill.py` held a verbatim second copy — two
#: module-level constants with the same literal and near-identical comments,
#: neither importing the other, nothing pinning them equal. Adding a third
#: owner input to one would have left the other silently unaware: the exact
#: duplication this module exists to make impossible, reproduced inside it one
#: day after it was written.
#:
#: It lives on THIS side because `bundle` imports nothing from the app, so
#: `skill` can derive from it while the reverse closes a cycle.
#:
#: `revision_notes` belongs here too. Its absence is why three skills grew a
#: private params-to-bundle hop apiece — the very thing `run`'s comment says a
#: fourth skill would do — while `PARTS` declared `supplies="skill.run"` for a
#: key `run` never wrote.
OWNER_INPUT = ("offer", "deadline", "revision_notes")

#: `absent` vocabulary — what it MEANS that a part is not here.
THINS = "thins"          # the work is worse, and worth doing anyway
UNVERIFIED = "unverified"  # output cannot be checked; this is the one veto
SITUATIONAL = "situational"  # only present when the request supplies a subject

PARTS: dict[str, dict] = {
    # -- tier 1: identity and the constraints ------------------------------
    "tenant": dict(tier=1, absent=UNVERIFIED, supplies="resolve.resolve",
                   what="which account this package is for"),
    "system": dict(tier=1, absent=THINS, supplies="resolve.resolve",
                   what="which pipeline asked, so guidance is scoped to it"),
    "tier": dict(tier=1, absent=THINS, supplies="resolve.resolve",
                 what="how deep this package was assembled"),
    "rules": dict(tier=1, absent=UNVERIFIED, supplies="resolve._rules",
                  what="voice, positioning, the ban list, and what this "
                       "pipeline has been taught — the constraints that must "
                       "never be violated",
                  sub=("block", "guidance", "positioning", "voice_tone",
                       "banned_claims")),
    # -- tier 2: who is asking, what they doubt, who they are --------------
    "situations": dict(tier=2, absent=THINS, supplies="resolve._situated",
                       what="what this request is about, classified"),
    "objections": dict(tier=2, absent=THINS, supplies="resolve._situated",
                       what="the hesitations this account has approved "
                            "answers to"),
    "audiences": dict(tier=2, absent=THINS, supplies="kb.audiences",
                      what="the buyer in their own words — pains, vocabulary, "
                           "buying triggers. Read by `funnel.inputs_for` for "
                           "every drafter, and supplied by nobody until "
                           "2026-08-30"),
    # THINS, not SITUATIONAL, and the distinction is load-bearing: this key is
    # written unconditionally, so marking it situational would exclude it from
    # `promised()` and hide it from `verify()` for ever — the exact way
    # `audiences` stayed missing.
    "audience": dict(tier=2, absent=THINS, supplies="resolve.resolve",
                     what="the ONE reader this piece of mass marketing is "
                          "written for. Empty for one-to-one work, which has "
                          "an actual person instead of a persona"),
    "claims": dict(tier=2, absent=THINS, supplies="resolve.resolve",
                   what="approved proof, the only thing a draft may assert"),
    "contested_positioning": dict(tier=2, absent=THINS, supplies="resolve.resolve",
                                  what="claims that argue with the positioning"),
    # -- tier 3: the catalogue, the history, the perishable ----------------
    "entities": dict(tier=3, absent=THINS, supplies="resolve.resolve",
                     what="what is actually for sale, and whether it can be "
                          "bought right now"),
    "conversation": dict(tier=3, absent=SITUATIONAL, supplies="resolve.resolve",
                         what="what has already been promised to this contact"),
    "correspondence": dict(tier=3, absent=SITUATIONAL, supplies="resolve.resolve",
                           what="what this account has said before, retrieved"),
    "correspondence_coverage": dict(tier=3, absent=SITUATIONAL,
                                    supplies="resolve.resolve",
                                    what="how well that retrieval covered it"),
    "craft": dict(tier=2, absent=THINS, supplies="resolve.resolve",
                  what="borrowed technique matched to what is being asked"),
    "perishable": dict(tier=3, absent=THINS, supplies="ledger.perishable",
                       what="readings with a half-life, which stop being true"),
    "needs_lookup": dict(tier=2, absent=THINS, supplies="resolve.resolve",
                         what="what must be read live rather than remembered"),
    "action_required": dict(tier=2, absent=SITUATIONAL, supplies="resolve.resolve",
                            what="something this package found that needs a person"),
    # -- the receipt, always present ---------------------------------------
    "coverage": dict(tier=1, absent=UNVERIFIED, supplies="resolve.resolve",
                     what="what was searched, what was skipped, and whether "
                          "this package is complete — a thin package that "
                          "reads as complete is the failure the receipt exists "
                          "to prevent"),
    "grounding": dict(tier=1, absent=THINS, supplies="resolve.resolve",
                      what="how well-founded the package is"),
    "gaps": dict(tier=1, absent=THINS, supplies="resolve.resolve",
                 what="named holes, each with the fix that closes it"),
    "blocked_on": dict(tier=1, absent=THINS, supplies="resolve.resolve",
                       what="what makes output unsafe, not merely thinner"),
    # -- the owner's instruction for THIS run -------------------------------
    **{k: dict(tier=1, absent=SITUATIONAL, supplies="skill.run",
               what="the owner's own input for this run — a person fills it "
                    "so that no generator has to invent one")
       for k in OWNER_INPUT},
    "revision_notes": dict(tier=1, absent=SITUATIONAL, supplies="skill.run",
                           what="what the owner sent the last draft back for"),
    # -- parts a SKILL adds to the package before it drafts -----------------
    #
    # Not everything in the package comes from `resolve`. A skill that has
    # derived something the drafter needs puts it here rather than passing a
    # second argument down four call layers — `ad_prompt` and the campaign
    # brief both read the package and nothing else. Declared for the same
    # reason as the rest: read by a prompt builder and supplied by a caller
    # two files away is exactly how `audiences` stayed missing.
    "funnel": dict(tier=2, absent=SITUATIONAL, supplies="skill_pack (the run)",
                   what="where the reader is, and what this account can "
                        "actually say at that stage"),
    "positioning": dict(tier=2, absent=SITUATIONAL, supplies="skill_pack (the run)",
                        what="the hypothesis a batch is testing, so every "
                             "variant is one idea rather than five"),
    # -- the refusal --------------------------------------------------------
    "error": dict(tier=1, absent=SITUATIONAL, supplies="resolve.resolve",
                  what="this package could not be built at all — an unknown "
                       "account. Present INSTEAD of the package, never "
                       "beside it"),
}


def promised(tier: int) -> tuple:
    """Parts a package at this tier must carry. `SITUATIONAL` ones are not
    promised — they exist only when the request supplied a subject, and
    demanding them would make every ordinary run look broken."""
    return tuple(sorted(
        k for k, p in PARTS.items()
        if p["tier"] <= tier and p["absent"] != SITUATIONAL))


def verify(b: dict) -> list[str]:
    """What this package promised for its tier and did not carry.

    Absence of the KEY, not emptiness of the value: an account with no
    audiences on file legitimately carries `[]`, and an account whose package
    never had the key at all is the `audiences` defect. Those are different
    facts and only the second one is a bug in this layer.
    """
    if not isinstance(b, dict):
        return ["the package is not a mapping"]
    if b.get("error"):
        # A REFUSAL IS NOT AN INCOMPLETE PACKAGE. `resolve` returns
        # `{"error": ...}` instead of a bundle when the account is unknown,
        # and holding that shape to the tier's promises would report fifteen
        # missing parts for what is really one named refusal.
        return []
    try:
        tier = int(b.get("tier") or 1)
    except (TypeError, ValueError):
        tier = 1
    return [k for k in promised(tier) if k not in b]


def audit(root: str = "") -> dict:
    """Every consumer's reads, against the declaration. Static, no imports.

    `undeclared` is the `audiences` defect before it costs anything: somebody
    reads a part of the package that nothing promises to supply. `unread` is
    the opposite and much cheaper — a part carried for nobody.
    """
    base = pathlib.Path(root or pathlib.Path(__file__).parent)
    seen: dict[str, set] = {}
    for path in sorted(base.glob("*.py")):
        if path.name == "bundle.py":
            continue
        try:
            tree = ast.parse(path.read_text())
        except (SyntaxError, OSError):
            continue
        for node in ast.walk(tree):
            key = owner = None
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "get" and node.args
                    and isinstance(node.args[0], ast.Constant)):
                owner = (getattr(node.func.value, "attr", None)
                         or getattr(node.func.value, "id", None))
                key = node.args[0].value
            elif isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
                owner = (getattr(node.value, "attr", None)
                         or getattr(node.value, "id", None))
                key = node.slice.value
            if owner == "bundle" and isinstance(key, str):
                seen.setdefault(key, set()).add(f"{path.name}:{node.lineno}")
    undeclared = {k: sorted(v) for k, v in seen.items() if k not in PARTS}
    return {"read": {k: sorted(v) for k, v in seen.items()},
            "undeclared": undeclared,
            "unread": sorted(set(PARTS) - set(seen))}
