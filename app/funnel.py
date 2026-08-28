"""Where the reader is, and therefore what the marketing should be about.

Owner, 2026-08-29: *"You should [be] using the objections and situations as
information for what people actually care about to create ads in different
parts of the funnel … the same is true when we are creating any marketing
material, the objections we identify, situations we have and claims we make
should inform our content strategy alongside the keywords."*

That is a correction to how this knowledge base was being used, not a new
feature. Until now:

* **claims** were GROUNDING — the list of things a draft is permitted to
  assert. Nothing chose *which* claim on the basis of who was reading.
* **objections** fed exactly one ad angle, and only the first one in the list.
* **situations** fed ads not at all, despite `KbSituation.kind` already
  carrying `who_they_are | problem | doubt` — which is a funnel in the schema,
  written down months ago and never read as one.
* **keywords** informed the blog and nothing else.

So this module is a READER over data that already exists. It invents no
taxonomy: the four stages map onto the three situation kinds plus objections,
and every stage says which knowledge leads, which supports, and — the part
that matters most — WHAT IS MISSING.

**"IF THEY ARE AVAILABLE, OF COURSE" (owner, same message).** A stage whose
leading input is absent is not silently downgraded to whatever is present.
It reports the gap by name, because a generator that quietly writes an
awareness ad out of a bottom-of-funnel objection has produced something
plausible and wrong, and nobody downstream can tell. That is the same rule
`skill.Context.thin` already applies to knowledge gaps, moved up to strategy.
"""
from __future__ import annotations

#: The four stages, ordered. `leads` and `supports` name KINDS OF KNOWLEDGE,
#: not fields — `inputs_for` resolves them against one account's data.
#:
#: The mapping is derived, not chosen: `KbSituation.kind` is already
#: who_they_are / problem / doubt, which is recognisably "who is this for" /
#: "what is wrong" / "what stops them", and an objection is a doubt that has
#: reached the point of being said out loud.
STAGES = {
    "awareness": {
        "label": "Awareness",
        "reader": "do not know you exist, and may not have named the "
                  "problem yet",
        "brief": "Name the SITUATION, not the product. The reader should "
                 "recognise their own week in the first line. Nothing is for "
                 "sale here — the win is that they realise this is about "
                 "them.",
        "leads": ("situation:problem",),
        "supports": ("situation:who_they_are", "audience_pains", "keyword"),
        "angles": ("identity", "occasion"),
        "asks": False,
    },
    "interest": {
        "label": "Interest",
        "reader": "have the problem and are looking at how it gets solved",
        "brief": "Connect the situation to what you actually do. Name the "
                 "mechanism — what it IS, how it works — not the benefit in "
                 "the abstract. One claim, used as explanation rather than "
                 "as boast.",
        "leads": ("situation:who_they_are", "entity"),
        "supports": ("claim", "keyword", "situation:problem"),
        "angles": ("identity", "occasion", "objection"),
        "asks": False,
    },
    "consideration": {
        "label": "Consideration",
        "reader": "are comparing you with the alternatives, including doing "
                  "nothing",
        "brief": "Lead with the DOUBT and answer it. This is where objections "
                 "belong: the reader has already decided they want the "
                 "outcome and is looking for the reason not to buy. Give "
                 "them the answer before they have to ask.",
        "leads": ("objection", "situation:doubt"),
        "supports": ("claim_with_evidence", "entity"),
        "angles": ("objection", "identity"),
        "asks": False,
    },
    "bottom": {
        "label": "Bottom of funnel",
        "reader": "want it and have one thing left in the way",
        "brief": "The last objection, the proof, and the offer — in that "
                 "order. Nothing new is introduced here; a new idea at the "
                 "bottom of the funnel restarts the decision.",
        "leads": ("objection", "offer"),
        "supports": ("claim_with_evidence",),
        "angles": ("objection", "offer"),
        "asks": True,
    },
}

#: What each input kind is called when it is missing, and what its absence
#: costs. Written as consequences rather than field names, because the note
#: lands in front of a person deciding whether to run anything at all.
_COST = {
    "situation:problem":
        "no problem situations are on file, so an awareness ad has nothing "
        "to open on but the product — which is an interest-stage ad wearing "
        "an awareness label",
    "situation:who_they_are":
        "no who-they-are situations are on file, so nothing says which "
        "reader this is for",
    "situation:doubt":
        "no doubt situations are on file",
    "objection":
        "no approved objections are on file, so there is nothing the reader "
        "hesitates over to answer — consideration and bottom-of-funnel work "
        "is guessing without them",
    "claim": "no approved claim is in scope, so nothing may be asserted",
    "claim_with_evidence":
        "no approved claim carries evidence, so the proof this stage turns "
        "on would be an assertion with nothing under it",
    "entity": "nothing in the catalogue is named, so the ad cannot say what "
              "it is about",
    "audience_pains": "no audience records a pain",
    "keyword": "no keyword targets are on file, so the copy uses our words "
               "for this rather than the reader's",
    "offer": "no offer was given, so a bottom-of-funnel ad has nothing to "
             "close on",
}


def normalise(stage: str) -> str:
    """One vocabulary. Accepts the shorthands people actually type."""
    s = str(stage or "").strip().lower().replace("-", "_").replace(" ", "_")
    alias = {"tof": "awareness", "top": "awareness", "top_of_funnel": "awareness",
             "mof": "consideration", "middle": "consideration",
             "mid": "consideration", "middle_of_funnel": "consideration",
             "bof": "bottom", "bottom_of_funnel": "bottom",
             "sales": "bottom", "purchase": "bottom", "conversion": "bottom",
             "consider": "consideration", "aware": "awareness",
             "interest": "interest"}
    s = alias.get(s, s)
    return s if s in STAGES else ""


def inputs_for(tenant: str, stage: str, *, claims: list | None = None,
               objections: list | None = None, entities: list | None = None,
               audiences: list | None = None, offer: str = "") -> dict:
    """What this account can actually say at this stage, and what it cannot.

    Reads the knowledge base, and takes the run's already-resolved bundle
    pieces when it has them so the caller does not pay for the same query
    twice. Returns:

        have    — {kind: [items]} for every input kind that IS present
        leads   — the kinds this stage leads with, that exist
        missing — the kinds this stage NEEDS and does not have
        thin    — the SUPPORTING kinds that are absent (a weaker note)
        note    — one sentence per gap, in consequences

    Nothing here refuses. Refusing is the caller's decision — a stage with a
    missing lead is still runnable and might be exactly what the owner asked
    for; what is not acceptable is running it and saying nothing.
    """
    from . import keywords as kwmod
    from . import kb as kbmod

    st = STAGES.get(normalise(stage) or "", None)
    if st is None:
        return {"stage": "", "error": f"unknown funnel stage {stage!r}",
                "known": sorted(STAGES)}
    stage = normalise(stage)

    rows = []
    try:
        rows = kbmod.situation_rows(tenant)
    except Exception:                                            # noqa: BLE001
        rows = []
    by_kind: dict[str, list] = {}
    for r in rows:
        by_kind.setdefault(str(getattr(r, "kind", "") or "problem"),
                           []).append(r)

    if claims is None:
        try:
            claims = kbmod.claims(tenant)
        except Exception:                                        # noqa: BLE001
            claims = []
    if objections is None:
        try:
            objections = kbmod.objections(tenant)
        except Exception:                                        # noqa: BLE001
            objections = []

    def _txt(x, *names):
        for n in names:
            v = x.get(n) if isinstance(x, dict) else getattr(x, n, None)
            if v:
                return v
        return ""

    have: dict[str, list] = {}
    for kind in ("problem", "who_they_are", "doubt"):
        if by_kind.get(kind):
            have[f"situation:{kind}"] = [
                {"tag": r.tag, "description": r.description or ""}
                for r in by_kind[kind]]
    if objections:
        have["objection"] = [
            {"objection": _txt(o, "objection"), "response": _txt(o, "response")}
            for o in objections]
    if claims:
        have["claim"] = [{"claim": _txt(c, "claim"),
                          "evidence": _txt(c, "evidence")} for c in claims]
        withev = [c for c in have["claim"] if c["evidence"]]
        if withev:
            have["claim_with_evidence"] = withev
    if entities:
        have["entity"] = list(entities)
    pains = [p for a in (audiences or [])
             for p in (_txt(a, "pains") or []) if p]
    if pains:
        have["audience_pains"] = pains
    try:
        kws = kwmod.targets(tenant)
    except Exception:                                            # noqa: BLE001
        kws = []
    if kws:
        have["keyword"] = [getattr(k, "phrase", str(k)) for k in kws]
    if str(offer or "").strip():
        have["offer"] = [str(offer).strip()]

    leads = [k for k in st["leads"] if k in have]
    missing = [k for k in st["leads"] if k not in have]
    thin = [k for k in st["supports"] if k not in have]
    note = [_COST.get(k, f"no {k} on file") for k in missing]

    return {"stage": stage, "label": st["label"], "reader": st["reader"],
            "brief": st["brief"], "angles": st["angles"], "asks": st["asks"],
            "have": have, "leads": leads, "missing": missing, "thin": thin,
            "note": note}


def brief(plan: dict) -> str:
    """The stage, written for a drafter. `plan` is `inputs_for`'s return.

    THE LEADING KNOWLEDGE IS QUOTED, not summarised. A drafter told "lead with
    an objection" writes a generic objection ad; a drafter shown the three
    objections this account's own customers actually raise writes about those.
    That is the entire point of the correction this module exists for.
    """
    if not plan or plan.get("error"):
        return ""
    out = [f"\n## WHERE THE READER IS: {plan['label']}",
           f"They {plan['reader']}.", plan["brief"]]
    if plan["asks"]:
        out.append("This one MAKES THE ASK.")
    else:
        out.append("This one does NOT ask for the sale. Pushing here loses "
                   "the reader you were about to earn.")

    have = plan.get("have") or {}
    for kind in plan.get("leads", []):
        items = have.get(kind) or []
        if not items:
            continue
        if kind.startswith("situation:"):
            out.append(f"\n## LEAD WITH ONE OF THESE SITUATIONS — the reader's "
                       f"own words for what is going on")
            for it in items[:5]:
                out.append(f"- {it['tag']}"
                           + (f": {it['description']}" if it["description"] else ""))
        elif kind == "objection":
            out.append("\n## LEAD WITH ONE OF THESE HESITATIONS — these are "
                       "real, said by real customers. Do not invent a "
                       "different one")
            for it in items[:5]:
                out.append(f"- {it['objection']}"
                           + (f"  (the honest answer: {it['response']})"
                              if it["response"] else ""))
        elif kind == "offer":
            out.append(f"\n## THE OFFER TO CLOSE ON\n{items[0]}")
        elif kind == "entity":
            out.append("\n## WHAT IS BEING SOLD")
            for it in items[:3]:
                nm = it.get("name", "") if isinstance(it, dict) else str(it)
                out.append(f"- {nm}")

    supports = [k for k in ("claim_with_evidence", "keyword",
                            "audience_pains", "situation:problem")
                if k in have and k not in plan.get("leads", [])]
    for kind in supports:
        items = have[kind]
        if kind == "claim_with_evidence":
            out.append("\n## PROOF YOU MAY USE (nothing outside this list)")
            for it in items[:4]:
                out.append(f"- {it['claim']} ({it['evidence']})")
        elif kind == "keyword":
            out.append("\n## THE READER'S OWN WORDS FOR THIS — prefer these "
                       "over ours\n" + ", ".join(str(x) for x in items[:8]))
        elif kind == "audience_pains":
            out.append("\n## WHAT THIS AUDIENCE FINDS HARD\n"
                       + "; ".join(str(x) for x in items[:5]))
        elif kind == "situation:problem":
            out.append("\n## SITUATIONS THIS ACCOUNT KNOWS ABOUT\n"
                       + ", ".join(i["tag"] for i in items[:8]))

    # THE GAPS, to the drafter as well as to the operator. A model told it is
    # missing the thing this stage turns on writes more carefully than one
    # left to assume it has everything.
    if plan.get("missing"):
        out.append("\n## WHAT THIS ACCOUNT DOES NOT HAVE FOR THIS STAGE\n"
                   + "\n".join(f"- {n}" for n in plan["note"])
                   + "\nWrite what can honestly be written without it. Do not "
                     "invent a situation, a hesitation or a proof to fill the "
                     "gap — an invented one is worse than a shorter ad.")
    return "\n".join(out)


def angles_for_stage(stage: str, available: tuple = ()) -> tuple:
    """The angles that make sense at this stage, narrowed to the ones this
    account may use at all (`ad_craft.angles_for`).

    An offer-led ad at awareness is asking a stranger to buy; an
    objection-killer at awareness answers a hesitation nobody has yet. Both
    are well-formed ads aimed at the wrong reader, which is the failure this
    whole module exists to stop — and neither the validator nor the craft
    ruleset can see it, because both are about the ad and not about who is
    reading it.
    """
    st = STAGES.get(normalise(stage) or "", None)
    if st is None:
        return tuple(available)
    want = tuple(st["angles"])
    if not available:
        return want
    keep = tuple(a for a in want if a in available)
    return keep or tuple(available)
