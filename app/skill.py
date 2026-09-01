"""Skills — the one way an agent runs a pipeline it did not have to assemble.

A skill is not a function an agent calls with context it gathered. It is a
declaration of *what context this work needs*, and the substrate below fetches
it. That inversion is the whole point: the agent picks a skill by name and
never picks context, so it cannot pick the wrong context, retrieve half of it,
or quietly proceed on none of it.

Three things every skill gets for free, and none of which a skill can opt out
of:

* **One `resolve()` call, at the tier the skill declared.** The bundle and its
  coverage receipt are handed in. A skill that goes hunting for more has a bug,
  because the receipt already said whether more exists.
* **The validator on every output.** `Context.emit()` is the only way to return
  something, and it runs `validator.check` before the caller ever sees the
  text. There is no path from a skill's body to a returned draft that skips the
  gate — which is a structural guarantee rather than a convention somebody has
  to remember.
* **A run row and an autonomy rung.** `start_run` / `finish_run` bracket every
  execution, so a skill is governable the day it is written. This was the gap:
  the whole retrieval half of this layer existed with `start_run` having two
  callers, neither of them in it, which meant anything built on top would have
  produced ungoverned output with no record of what it refused.

## Absence, again

Every refusal here names the field. `status` is never a bare boolean:

    ready      the skill can run
    blocked    a named thing is missing — `blocked_on` says which
    refused    the request itself is wrong (unknown skill, unknown account)
    produced   it ran and emitted at least one item
    empty      it ran, correctly, and there was nothing to emit

`empty` and `blocked` are the pair this codebase keeps collapsing (DEFECTS §1).
"a sweep that found no violations" and "a sweep that could not run" are
opposite outcomes and must not both arrive as an empty list.
"""
from __future__ import annotations

import inspect
import traceback
from dataclasses import dataclass, field
from typing import Callable

from . import bundle as _pkg
from . import (assurance, coherence, kb, ledger, resolve as rs, systems,
               tenants, validator)

# ---------------------------------------------------------------------------
# The contract
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Skill:
    """One unit of work an agent can name.

    `system_key` binds the skill to a row in `systems.CATALOG`, which is what
    supplies the run ledger, the readiness blockers and the autonomy rung. A
    skill without one would be a script.
    """

    key: str
    name: str
    does: str                       # one line — this becomes the tool description
    system_key: str
    tier: int = 3                   # the resolve() tier this work actually needs
    needs: tuple = ()               # dotted bundle paths that make it THINNER
    # Knowledge without which the output would be FALSE, not merely thinner.
    #
    # `needs` is a label; this is a gate, and the difference is whether the
    # work still means anything. A reply drafted without an approved objection
    # is a worse reply and worth having — the owner's rule, and the reason
    # nothing else here blocks on absent data. A compliance sweep run against
    # an empty ban list is not a worse report, it is a report that says CLEAN
    # about a catalogue nobody checked, which is the false assurance
    # `validator.check` refuses to give for the same reason.
    #
    # Almost always empty. If you are reaching for it, the question to answer
    # is "would the output be a lie without this", and "it would be vaguer" is
    # a no.
    constitutive: tuple = ()        # kb fields whose absence makes output false
    params: tuple = ()              # accepted inputs; anything else is refused
    # Parameters this work CANNOT be done without — checked on every caller,
    # not just the plan path.
    #
    # `params` is an accept-list with no notion of required, so the one gate
    # that already knew a reader was mandatory (`plan_fields[].required`, via
    # `plan_complete`) covered the console and nothing else: the agent tool,
    # the raw HTTP route, the worker tick and the workroom redraft all reach
    # `run()` without it. A guard covering one of five doors is not a guard.
    #
    # THE BAR IS "A CHOICE THAT EXISTS AND WAS NOT MADE", not "data is
    # missing". `requires_when` names a predicate: the requirement binds only
    # when the account can actually satisfy it. An account with no personas on
    # file still runs — thinly, saying so — because refusing there would stop
    # work on the strength of an absence, which is the rule this layer is
    # built on. An account WITH personas that named none is a decision
    # somebody skipped, and that is what this refuses.
    requires: tuple = ()
    requires_when: Callable = None   # (tenant) -> bool; None means always
    writes: bool = False            # does it mutate anything outside the ledger
    produces: str = "report"        # report | draft | proposal
    run: Callable = None            # (Context) -> dict


#: Parameters that are the OWNER'S INSTRUCTION for this run rather than
#: knowledge, and that the drafters therefore read off the bundle. A generator
#: inventing a discount or a deadline is the one failure in this layer that
#: costs real money, so both are fields a person fills, never things a model
#: decides — and the whole point is defeated if the field a person filled does
#: not arrive. See the hop in `run`.
#: DERIVED, never restated — see `bundle.OWNER_INPUT`, which owns it because
#: that module imports nothing from the app.
OWNER_INPUT = _pkg.OWNER_INPUT

REGISTRY: dict[str, Skill] = {}

_PACK_LOADED = False


def _ensure_pack() -> None:
    """The registry loads its own contents on first read.

    Registration is an import side effect of `skill_pack`, and WHO imported
    it was left to chance: only `tool_description` — the agent path — did.
    So the kernel agent worked while the web process's Run-now route and the
    worker's compliance sweep both reached `run()` with an EMPTY registry:
    the owner pressed Run now on a real campaign plan and was told no skill
    keyed 'campaign_email' existed while skill_pack.py sat one import away,
    and the Monday catalog sweep had been refusing the same way with nobody
    logging it (2026-08-21). Structural now: every registry read loads the
    pack first, so a caller cannot forget. The flag is set BEFORE the
    import because skill_pack imports this module back.
    """
    global _PACK_LOADED
    if _PACK_LOADED:
        return
    _PACK_LOADED = True
    try:
        from . import skill_pack  # noqa: F401 — importing registers the pack
    except Exception:
        _PACK_LOADED = False
        raise


def registered() -> int:
    """How many skills the registry holds — the pack loaded first. On
    /health so 'is the pack actually wired in THIS process' is a curl, not
    an incident."""
    _ensure_pack()
    return len(REGISTRY)


def register(skill: Skill) -> Skill:
    if skill.key in REGISTRY:
        raise ValueError(f"skill {skill.key!r} is already registered")
    REGISTRY[skill.key] = skill
    return skill


def get(key: str) -> Skill | None:
    _ensure_pack()
    return REGISTRY.get(key)


def catalogue(tenant: str = "") -> list[dict]:
    """Every skill, and — if a tenant is named — whether it can run for them.

    This is what an agent should be shown instead of a list of tools. A skill
    that is blocked says so here, with the missing field, so the agent does not
    discover it by failing.
    """
    _ensure_pack()
    out = []
    for sk in sorted(REGISTRY.values(), key=lambda s: s.key):
        row = {"key": sk.key, "name": sk.name, "does": sk.does,
               "system": sk.system_key, "produces": sk.produces,
               "writes": sk.writes, "params": list(sk.params)}
        if tenant:
            gate = preflight(sk.key, tenant)
            row["status"] = gate["status"]
            row["blocked_on"] = gate["blocked_on"]
            row["autonomy"] = gate.get("autonomy", "")
        out.append(row)
    return out


# ---------------------------------------------------------------------------
# What a skill is handed
# ---------------------------------------------------------------------------


# How many times a failing draft may be handed its own failures and asked
# again. Three: the first repair fixes the ordinary case (a banned phrase
# reworded), the second catches a repair that introduced a new problem, and the
# third is the margin Gomeh asked for before anything is given up on. Past that
# the drafter is not converging, and further attempts buy latency and API spend
# rather than a better answer — so it is blocked and flagged, not retried on.
MAX_REPAIRS = 3

# What each validator rule means the KNOWLEDGE BASE is missing. Repair rewrites
# a draft; it cannot conjure a fact that was never recorded, and pretending
# otherwise would just be inventing. So a terminal failure names the row an
# operator should go and create — which fixes every future draft, not this one.
#
# Rules absent from this map are draft-level problems a rewrite genuinely can
# solve (`banned_claim`, `repeat`), so they produce no knowledge task.
_NEEDS = {
    "uncited": ("an approved claim for this situation",
                "there was no approved proof to cite, so the draft could only "
                "assert. Add or approve a claim covering this."),
    "claim_not_selectable": ("an approved, in-date claim",
                             "the cited proof is retired, expired or still in "
                             "review — approve it or replace it."),
    "unknown_entity": ("this product or space on file",
                       "the thing being written about is not in the entity "
                       "list, so nothing about it can be verified."),
    "entity_unavailable": ("current availability for this entity",
                           "the entity is on file but marked unavailable."),
    "no_ban_list": ("brand.banned_claims",
                    "the validator has no rules to check against, so nothing "
                    "here can be trusted."),
    "unknown_account": ("a KB brand row for this account",
                        "there is no brand record, so no rule, voice or claim "
                        "exists to write from."),
    "commitment_conflict": ("a resolved commitment for this conversation",
                            "the draft contradicts something already promised "
                            "to this contact."),
}


def _knowledge_needed(failures: list[dict]) -> list[dict]:
    """The KB rows that would have prevented these failures, deduplicated."""
    out, seen = [], set()
    for f in failures:
        hit = _NEEDS.get(f.get("rule", ""))
        if not hit or hit[0] in seen:
            continue
        seen.add(hit[0])
        out.append({"rule": f["rule"], "needs": hit[0], "why": hit[1]})
    return out


@dataclass
class Context:
    """Everything a skill body is allowed to know, and the only way out.

    A skill reads `bundle` and `params` and calls `emit()`. It does not touch
    the ledger, the validator or the run row — those are applied around it, so
    that a skill written carelessly is still governed.
    """

    tenant: str
    skill: Skill
    bundle: dict
    params: dict
    run_id: str
    autonomy: str
    #: What the bundle could not carry. Set by `run` and carried onto every
    #: assurance row, so a clean check on a thin bundle is never mistaken for
    #: a clean check on a complete one.
    thin: list = field(default_factory=list)
    items: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    # -- reading -----------------------------------------------------------

    @property
    def rules(self) -> dict:
        return self.bundle.get("rules") or {}

    @property
    def claims(self) -> list:
        return self.bundle.get("claims") or []

    @property
    def banned(self) -> list:
        return list(self.rules.get("banned_claims") or [])

    def note(self, text: str) -> None:
        """Something the operator should see that is not an output."""
        self.notes.append(text)

    # -- writing -----------------------------------------------------------

    def emit(self, body: str, *, claim_ids: list | None = None,
             entity_key: str = "", situation: str = "", audience_key: str = "",
             angle: str = "", fmt: str = "", destination: str = "",
             conversation_id: str = "", require_citation: bool | None = None,
             redraft=None, meta: "dict | callable | None" = None,
             lookups: list | None = None, shape=None, theme: str = "",
             positioning: str = "", funnel_stage: str = "",
             media_ids: "list | callable | None" = None,
             commitment: dict | None = None,
             parts: "dict | callable | None" = None) -> dict:
        """Validate one produced thing, repair it if it fails, file it.

        The only exit. `require_citation` defaults to whether the skill claims
        to produce a draft — a compliance *report* quotes the site's own words
        back and has no claim to cite, whereas a draft that asserts something
        must say where it came from.

        **`redraft` is what stops a rejection becoming a manual-review gap.**
        Pass `redraft(previous_body, failures) -> str` and a failing draft is
        handed its own failures — each of which already carries a `fix`, which
        was never decoration — and asked again, up to `MAX_REPAIRS` times.

        A validator that only says no teaches nothing and leaves a hole for a
        human to patch one output at a time. The rule is not relaxed to achieve
        this: every repaired attempt is re-validated by the same deterministic
        check, and a draft that cannot be fixed is still blocked. What changes
        is that the system explains and adjusts first, and that the attempt
        history is on the record — so `repair_rate` is measurable and a rule
        that fires constantly is visible as a rule to revisit rather than as
        background noise.

        **`meta` may be a zero-argument callable, and then it is read AFTER the
        repair loop settles.** A repair replaces the body; a `meta` dict built
        before that describes the draft that was REPLACED. campaign_email hit
        exactly this: the rendered HTML was built from the pre-repair copy, so
        a repaired email filed the repaired text and shipped the failing HTML
        to the ESP. Anything whose meta is derived from the body — a render, a
        word count, a diff — passes a callable so the two cannot drift.
        """
        cite = (self.skill.produces in ("draft", "proposal")
                if require_citation is None else require_citation)

        # THE SECOND AXIS. `validator.check` answers "does this say anything
        # forbidden"; it reads a STRING and therefore could never answer "is
        # this about one thing, and do its parts agree" — the hero image and
        # the product cards are not in the string. Both axes run in ONE loop so
        # a single repair addresses whichever failed, and so the thing that was
        # checked is the thing that ships.
        #
        # Coherence rules are NAMESPACED `coherence:`. A blocked output feeds
        # `systems.blocked_reasons`, which ranks the knowledge-base backlog by
        # what actually cost an output — and an incoherent email is a quality
        # failure that no amount of authoring would have prevented. Filing it
        # there unnamespaced would inflate the backlog with work nobody can do.
        _brand = (self.bundle.get("rules", {}) or {}).get("brand_name", "") \
            or self.tenant

        def _coherence(text):
            if commitment is None:
                return []
            if callable(parts):
                # The CURRENT text is offered to the callable, because a repair
                # replaces the body and a parts dict that closed over the old
                # one would describe the draft that was thrown away — the exact
                # defect `meta` being a callable already exists to prevent.
                # A zero-argument callable (one that rebuilds from its own
                # state, as campaign_email does) is still honoured.
                try:
                    _n = len(inspect.signature(parts).parameters)
                except (TypeError, ValueError):
                    _n = 0
                got = parts(text) if _n else parts()
            else:
                got = parts
            if got is None:
                return []
            found = coherence.review(commitment, got, brand_name=_brand)
            return [{**f, "rule": "coherence:" + f["rule"]} for f in found]

        def _structure(text):
            """Does the RENDERED thing hold together, mechanically.

            A third axis beside the rules and the subject. `validator` asks
            whether the artifact says anything it may not; `coherence` asks
            whether it is about the thing it committed to; this asks whether
            it is intact — a word cut and re-joined, a product recommended
            and never linked, a variable nobody filled. All three are
            deterministic, and none of them is a model reading its own work.
            """
            from . import artifact_check
            if "<" not in text:            # not a rendered artifact
                return []
            found = artifact_check.check(text)
            block = set(artifact_check.BLOCKING)
            return [{**f, "rule": "structure:" + f["rule"],
                     "severity": "block" if f["rule"] in block else "advice"}
                    for f in found]

        def _check(text):
            verdict = validator.check(
                self.tenant, text, claim_ids=claim_ids or [],
                entity_key=entity_key, conversation_id=conversation_id,
                require_citation=cite)
            found = _coherence(text) + _structure(text)
            if not found:
                return verdict
            hard = [f for f in found if f.get("severity") == "block"]
            return {**verdict,
                    "ok": verdict["ok"] and not hard,
                    "failures": list(verdict["failures"]) + hard,
                    "checked": list(verdict.get("checked") or [])
                               + ["coherence", "structure"],
                    # Advice survives the loop so it can be reported once the
                    # body has settled; only blocks stop the artifact.
                    "coherence_advice": [f for f in found
                                         if f.get("severity") != "block"]}

        verdict = _check(body)
        attempts = []          # every rejected draft, in order, with its reasons

        while not verdict["ok"] and redraft and len(attempts) < MAX_REPAIRS:
            attempts.append({"body": body, "failures": verdict["failures"]})
            try:
                fixed = (redraft(body, verdict["failures"]) or "").strip()
            except Exception as exc:                             # noqa: BLE001
                self.note(f"repair raised {exc.__class__.__name__} — keeping "
                          f"the blocked draft rather than losing it")
                break
            if not fixed or fixed == body:
                # No change is not a repair. Stopping here keeps the loop from
                # spending attempts on a drafter that has nothing more to give.
                break
            body, verdict = fixed, _check(fixed)

        disposition = _disposition(self.autonomy, verdict["ok"],
                                   self.skill.writes)
        status = "blocked" if not verdict["ok"] else disposition

        # The rejected attempts are filed too, as `repaired` when a later one
        # succeeded. They are deliberately NOT `blocked`: `blocked` means an
        # output was lost, and `blocked_reasons()` ranks the KB backlog by it —
        # counting self-corrections there would inflate the backlog with
        # problems the system already solved on its own.
        for att in attempts:
            ledger.record(
                self.tenant, self.skill.system_key,
                situation=situation, entity_key=entity_key,
                audience_key=audience_key, claim_ids=claim_ids or [],
                angle=angle, format=fmt or self.skill.produces,
                status="repaired" if verdict["ok"] else "superseded",
                blocked_on=[f["rule"] for f in att["failures"]],
                body=att["body"], conversation_id=conversation_id,
                lookups=list(lookups or []), run_id=self.run_id)

        row = ledger.record(
            self.tenant, self.skill.system_key,
            situation=situation, entity_key=entity_key,
            audience_key=audience_key, claim_ids=claim_ids or [],
            angle=angle, format=fmt or self.skill.produces,
            # What KIND of thing this was, in the skill's own vocabulary —
            # campaign_email files its intent here (story / education / proof /
            # offer), which is what lets the next send read back how often this
            # list has been given to versus asked.
            theme=theme, status=status,
            blocked_on=[f["rule"] for f in verdict["failures"]],
            destination=destination, body=body,
            # Which LIVE lookups fed this. A skill that answered partly from a
            # stock reading produces a sentence that stops being true; the
            # ledger has to know which, or `ledger.perishable` cannot tell a
            # brand fact from a reading a fortnight later.
            lookups=list(lookups or []),
            # The STRUCTURE that was produced, when the skill has one. Read
            # after the repair loop for the same reason `meta` is: a repair can
            # change the layout, and recording the shape of a superseded draft
            # would teach the next send to avoid the wrong thing.
            shape=list((shape() if callable(shape) else shape) or []),
            # IDENTITY TRAVELS WITH THE ARTIFACT. The same `meta` the item
            # carries is written onto `ArtifactBody`, so what the thing IS
            # (its title, its SEO title, its meta description) survives past
            # the pending approval that used to be its only home — read after
            # the repair loop, like `shape`, so it describes what finally
            # passed rather than a superseded draft.
            meta=(meta() if callable(meta) else meta) or {},
            # WHICH ASSET CARRIED IT. `Output.media_ids` has existed since the
            # table did and nothing ever wrote it, so `ledger.publish` — whose
            # whole second job is crediting the creative that went out — has
            # been crediting an empty list, and "which photograph actually
            # worked" had no answer for any skill that used one.
            #
            # On the SURVIVING row only. The superseded attempts above are the
            # same email drafted again; crediting the hero to each of them
            # would count one photograph three times in any question about
            # which creative was used.
            # A CALLABLE for the same reason `shape` is: a repair can rewrite
            # the layout, and the hero block is one of the things it can drop.
            media_ids=list((media_ids() if callable(media_ids) else media_ids)
                           or []),
            # What this output was TESTING, on every row of the batch, so the
            # question "which positioning did better" is one GROUP BY rather
            # than a join through the run.
            positioning=positioning, funnel_stage=funnel_stage,
            conversation_id=conversation_id, run_id=self.run_id)

        # Every attempt is filed as a CHECK, not just the ones that produced
        # something. The ledger records what was produced; without this, "how
        # many drafts did the validator clear" has no answer and a layer that
        # is working looks identical to one that is switched off.
        for i, att in enumerate(attempts):
            assurance.record(
                self.tenant, source="skill", system_key=self.skill.system_key,
                run_id=self.run_id, attempt=i,
                checked=verdict.get("checked") or [],
                caught=[f["rule"] for f in att["failures"]],
                verdict="repaired" if verdict["ok"] else "superseded",
                grounded=bool(claim_ids), thin=self.thin)
        assurance.record(
            self.tenant, source="skill", system_key=self.skill.system_key,
            run_id=self.run_id, output_id=row.id, attempt=len(attempts),
            checked=verdict.get("checked") or [],
            caught=[f["rule"] for f in verdict["failures"]],
            verdict=("blocked" if not verdict["ok"]
                     else ("repaired" if attempts else "passed")),
            grounded=bool(claim_ids), thin=self.thin)

        # An item that needs a human gets an approval linked to THIS RUN, which
        # is the only way the decision can travel back and let the system earn
        # its next rung.
        #
        # `notify=False` is not an optimisation. A skill emitting thirty items
        # would otherwise fire thirty notifications, and this codebase has
        # already had that incident once: a poller re-triggered a slow endpoint,
        # ~200 queued drafts went out at 400 sends/minute, Meta rate-limited the
        # pair and ~200 fallback emails landed in a minute. The existing digest
        # poller batches and caps; nothing here should send directly.
        if verdict["ok"] and disposition == "needs_approval":
            try:
                from . import approvals
                sysrow = systems.find(self.tenant, self.skill.system_key)
                approvals.request_approval(
                    "skill_output",
                    f"{self.skill.name} for {self.tenant}: {body[:80]}",
                    {"tenant": self.tenant, "skill": self.skill.key,
                     "output_id": row.id, "body": body[:2000]},
                    notify=False, run_id=self.run_id,
                    system_id=sysrow.id if sysrow else "")
            except Exception as exc:                             # noqa: BLE001
                self.note(f"could not queue an approval "
                          f"({exc.__class__.__name__}) — the output is on the "
                          f"ledger, but nothing will prompt you to decide it")

        # Terminal failure is a knowledge problem, not a queue item. Say what
        # would have prevented it, so the fix lands in the KB and holds for
        # every future draft instead of being applied to this one by hand.
        needs: list[dict] = []
        if not verdict["ok"]:
            needs = _knowledge_needed(verdict["failures"])
            if needs:
                # `basis="unknown"` is what `record_unknowns` FILTERS ON, and
                # this call never passed it — so the one mechanism that turns a
                # lost draft into a knowledge task recorded NOTHING, on every
                # skill, while returning cleanly into an `except: pass`. The
                # `thin` call further down this file found and fixed exactly
                # this and left the reason in a comment; the two calls had
                # simply drifted. Asserting the COUNT rather than trusting the
                # return is the §1 rule about bulk writes, applied here too.
                try:
                    filed = kb.record_unknowns(
                        self.tenant,
                        [{"basis": "unknown", "key": entity_key,
                          "name": entity_key, "attribute": n["needs"]}
                         for n in needs],
                        asked_for=body[:300])
                    if not filed:
                        self.note("what would have unblocked this could not "
                                  "be filed as a knowledge task")
                except Exception:                                # noqa: BLE001
                    pass                    # never let bookkeeping lose output
            self.note(
                f"could not be said within the rules after "
                f"{len(attempts)} repair attempt(s). "
                + (needs[0]["why"] if needs else
                   "; ".join(f["fix"] for f in verdict["failures"])[:200]))

        # Coherence ADVICE — the nudges, reported once the body has settled so
        # they describe what shipped rather than a draft that was replaced.
        for f in (verdict.get("coherence_advice") or []):
            self.note(f"coherence ({f['severity']}): {f['detail']} → {f['fix']}")

        item = {"body": body, "ok": verdict["ok"],
                "failures": verdict["failures"], "checked": verdict["checked"],
                # What this artifact was committed to, on the item, so a run
                # can be read back and the question "what was this supposed to
                # be about" has an answer that is not a guess.
                "commitment": dict(commitment or {}),
                "disposition": disposition, "status": status,
                "output_id": row.id, "entity_key": entity_key,
                "claim_ids": list(claim_ids or []),
                "repairs": len(attempts),
                "repair_history": attempts,
                # Read now, not at call time: a callable meta describes what
                # FINALLY passed, after any repair rewrote the body.
                "needs": needs, "meta": (meta() if callable(meta) else meta) or {}}
        self.items.append(item)
        return item


def _disposition(autonomy: str, valid: bool, writes: bool) -> str:
    """What may happen to a validated item at this rung.

    A validator failure outranks every rung — `auto` does not mean "send the
    thing that failed the check", it means "do not ask a human about the things
    that passed". That distinction is the reason this is a function and not a
    lookup.
    """
    if not valid:
        return "blocked"
    if autonomy == "auto":
        return "cleared"
    if autonomy == "approve_exceptions":
        # A write is the exception, always. Reading and reporting at this rung
        # goes through; changing a live store does not.
        return "needs_approval" if writes else "cleared"
    # `shadow` — the one manual rung, and the change of 2026-08-31.
    #
    # Shadow returned "recorded" — it happened, it does not leave — and `emit`
    # queues an approval ONLY on `needs_approval` (this file, ~line 523). So
    # the LEARNING rung produced drafts that nobody could ever approve. Shadow
    # is also the DEFAULT: `db.System.autonomy` defaults to it and
    # `systems.create` never sets anything else, so every system a client
    # installs and does not promote sits there. In practice the commonest
    # state of this platform was a finished draft with no decision on it, and
    # a workroom whose only offer was an explanation of which rung to move to
    # in order to get one. `admin_ui` had already written that down —
    # "the commonest and the most silent" — beside the sentence explaining it.
    #
    # The owner's rule, stated in the campaign_email walk and again on
    # 2026-08-31: shadow is the Learning phase and MANUAL APPROVAL IS
    # AVAILABLE INSIDE IT. "Sends nothing" always meant "sends nothing BY
    # ITSELF", which is exactly what a queued approval preserves — a human
    # taps, or nothing happens. A drafted thing now offers the same two
    # decisions at every rung but `auto`: approve it, or send it back.
    return "needs_approval"


# ---------------------------------------------------------------------------
# Running one
# ---------------------------------------------------------------------------


def _dig(bundle: dict, path: str):
    cur = bundle
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def tool_description(tenant: str = "") -> str:
    """What the agent is shown instead of a list of tools.

    This is the point of `catalogue()`. A tool list makes the model choose the
    work AND assemble the context for it, and it will assemble the context
    wrong — with the wrong client, the wrong tier, unapproved material — in
    ways nothing downstream can see. Here it picks a NAME, and the substrate
    resolves everything else.

    Blocked skills are listed WITH what they are waiting on rather than hidden.
    A model that cannot see `catalog_compliance` concludes the system cannot
    check a catalogue; one that sees "blocked: not connected: commerce" can say
    so to the person asking, which is the answer they actually needed.
    """
    rows = catalogue(tenant) if tenant else []  # catalogue loads the pack
    if not rows:
        return ("Run one of the data layer's skills. No account is active, so "
                "there is nothing to list — switch to a client first.")

    ready = [r for r in rows if r["status"] == "ready"]
    blocked = [r for r in rows if r["status"] != "ready"]

    lines = ["Run one governed piece of work from the data layer. You pick the "
             "SKILL; the substrate resolves the context, validates whatever is "
             "produced, files it to the ledger and applies the autonomy rung. "
             "Never assemble a brief yourself and never pick an account."]
    if ready:
        lines.append("\nReady now:")
        for r in ready:
            params = ", ".join(r["params"]) or "no parameters"
            lines.append(f"  · {r['key']} — {r['does']} (accepts: {params})")
    if blocked:
        lines.append("\nInstalled but waiting — say what each is waiting on if "
                     "somebody asks for it:")
        for r in blocked:
            why = "; ".join(r.get("blocked_on") or []) or r["status"]
            lines.append(f"  · {r['key']} — {why}")
    return "\n".join(lines)


def preflight(key: str, tenant: str) -> dict:
    """Can this skill run for this account, and if not exactly what is absent.

    Separated from `run` so the agent can be *shown* a blocked skill rather
    than discovering it by calling one. Everything here is cheap — no resolve,
    no network.
    """
    sk = get(key)
    if not sk:
        return {"status": "refused", "blocked_on": [f"no skill keyed {key!r}"],
                "known": sorted(REGISTRY)}
    if not tenants.get(tenant):
        return {"status": "refused",
                "blocked_on": [f"no account keyed {tenant!r}"]}

    row = systems.find(tenant, sk.system_key)
    if not row:
        return {"status": "blocked", "blocked_on": [
            f"the {sk.system_key} system is not installed for {tenant} — "
            f"install it on the Systems tab — the contract is optional"]}
    # The switch, not a list of bad statuses. This checked `retired` only, so a
    # PAUSED system went on running skills — pausing something is the one
    # action whose whole meaning is "stop", and it did not.
    if not systems.is_on(row):
        return {"status": "blocked", "blocked_on": [
            f"the {sk.system_key} system is {row.status or 'not live'} — turn "
            f"it on on the Systems tab if it should be running"]}

    gate = systems.ready(row)
    if not gate["can_produce"]:
        # The ONLY blocking case left: a connection that does not exist. Every
        # other gap makes the output thinner, not impossible, and thinner is
        # what `thin` carries down to the run so it can be said on the output.
        return {"status": "blocked", "blocked_on": gate["impossible"],
                "autonomy": row.autonomy, "system_id": row.id,
                "thin": gate["thin"]}
    return {"status": "ready", "blocked_on": [], "autonomy": row.autonomy,
            "system_id": row.id, "thin": gate["thin"]}


def run(key: str, tenant: str, *, trigger: str = "manual", ref: str = "",
        run_id: str = "", **params) -> dict:
    """Run one skill for one account. The only entry point.

    Everything a caller needs to decide what happens next is in the return:
    what was searched, what could not be grounded, what was produced and what
    each produced thing is allowed to do.

    `run_id` names a PLANNED row to consume: the plan's fields become the
    run's parameters and the same row advances through the stages, so one
    row is one item. The gates (switch, completeness, rung) live in
    `systems.take_plan`, structurally — a caller cannot reach execution
    around them. On any refusal the plan stays `planned`, untouched.
    """
    sk = get(key)

    # One reply per conversation, whoever writes it — and checked FIRST.
    #
    # `run_skill` is a kernel tool, so the WhatsApp agent can reach a drafting
    # skill directly: a second entry point that never passes through triage. A
    # guard covering one of two doors is not a guard.
    #
    # Before `preflight` deliberately. "Another system already answered this
    # thread" is true whether or not this one is installed or connected, it is
    # the cheapest check here, and it is the one whose refusal a caller can act
    # on — "not connected: inbox" would send somebody to wire a credential when
    # the real answer is that the reply has already been written.
    thread = str(params.get("thread_id") or "")
    if thread and sk and sk.produces == "draft":
        from . import replies
        may = replies.may_reply(tenant, thread, sk.system_key)
        if not may["ok"]:
            return {"skill": key, "tenant": tenant, "status": "refused",
                    "blocked_on": [may["why"]], "items": [], "notes": [],
                    "coverage": {}, "run_id": ""}

    pre = preflight(key, tenant)
    if pre["status"] != "ready":
        # A refusal that leaves no trace is a gap nobody can rank. `blocked`
        # here is the most common real outcome — the system is not installed,
        # the contract is blank, the ban list is empty — and it is exactly what
        # `blocked_reasons()` exists to count. The first version of this
        # returned before `start_run`, so the failures most worth fixing were
        # the only ones never recorded.
        #
        # `refused` is different and stays unrecorded: an unknown skill or an
        # unknown account is a caller error, not something this account is
        # missing, and filing it would put noise on the authoring backlog.
        #
        # A CONSUME call is a third case: the plan row already carries the
        # item, so nothing extra is filed and the plan stays `planned` — a
        # daily blocked row per stuck plan is the tick noise this codebase
        # was already cured of once.
        logged = ""
        if pre["status"] == "blocked" and not run_id:
            if pre.get("system_id"):
                logged = systems.start_run(pre["system_id"], tenant,
                                           trigger=trigger, ref=ref or key)
                systems.finish_run(logged, "blocked",
                                   blocked_on="; ".join(pre["blocked_on"]))
            ledger.record(tenant, sk.system_key if sk else key,
                          status="blocked", blocked_on=pre["blocked_on"],
                          run_id=logged, format=sk.produces if sk else "")
        return {"skill": key, "tenant": tenant, "status": pre["status"],
                "blocked_on": pre["blocked_on"], "items": [], "notes": [],
                "coverage": {}, "run_id": logged}

    #: Accepted by EVERY skill, so it is taken out before the per-skill check
    #: rather than declared nine times. A skill that had to list it would be a
    #: skill that could forget to, and the one it forgot would be the one
    #: somebody needed to waive at two in the morning.
    override = str(params.pop("override_needs", "") or "").strip()

    unknown = [p for p in params if p not in sk.params]
    if unknown:
        # Refuse rather than ignore. A silently dropped parameter is the
        # caller believing it asked for something it did not get. Checked on
        # the CALLER's params before any plan is consumed, so a bad call
        # cannot flip a plan and then bail, stranding the row mid-stage.
        return {"skill": key, "tenant": tenant, "status": "refused",
                "blocked_on": [f"unknown parameter(s): {', '.join(sorted(unknown))}"
                               f" — this skill accepts {', '.join(sk.params) or 'none'}"],
                "items": [], "notes": [], "coverage": {}, "run_id": ""}

    consuming = bool(run_id)
    if consuming:
        grab = systems.take_plan(run_id, tenant,
                                 system_id=pre["system_id"],
                                 skill_params=sk.params,
                                 caller_params=tuple(params))
        if not grab["ok"]:
            # The plan stays `planned` — every take_plan refusal happens
            # before the flip, so a held plan waits visibly on the Planned
            # list rather than half-consuming.
            return {"skill": key, "tenant": tenant, "status": "refused",
                    "blocked_on": [grab["why"]], "items": [], "notes": [],
                    "coverage": {}, "run_id": ""}
        params = {**grab["params"], **params}
    else:
        run_id = systems.start_run(pre["system_id"], tenant, trigger=trigger,
                                   ref=ref or key)

    # WHAT THIS WORK CANNOT BE DONE WITHOUT. After the plan merge on purpose:
    # a plan legitimately carrying the field would otherwise be refused before
    # its values were read. `take_plan` drops blank fields, so a required field
    # left empty on a plan arrives here as absent, which is correct.
    if sk.requires:
        _binds = True
        if sk.requires_when:
            try:
                _binds = bool(sk.requires_when(tenant))
            except Exception:                                    # noqa: BLE001
                _binds = False      # a predicate that cannot run must not stop work
        if _binds:
            _absent_p = [r for r in sk.requires
                         if not str(params.get(r) or "").strip()]
            if _absent_p:
                systems.finish_run(run_id, "blocked",
                                   blocked_on="; ".join(_absent_p))
                return {
                    "skill": key, "tenant": tenant, "status": "blocked",
                    "blocked_on": [
                        f"{p} is required for this work and was not given"
                        for p in _absent_p],
                    "items": [], "notes": [], "coverage": {}, "thin": [],
                    "run_id": run_id}

    from . import systems as _sysm
    bundle = rs.resolve(tenant, system=sk.system_key, tier=sk.tier,
                        utterance=str(params.get("utterance") or ""),
                        contact_id=str(params.get("contact_id") or ""),
                        entity_key=str(params.get("entity_key") or ""),
                        # AND THE REST OF WHAT THE PIECE IS ABOUT. A hero is
                        # one thing; a piece about a location is about its
                        # venues, and each venue's facts are the evidence for
                        # the brand-level claim that there are several. Empty
                        # for everything that names one subject, so nothing
                        # moves for an ordinary run.
                        entity_keys=_sysm.entity_list(
                            params.get("entity_keys") or ""),
                        # WHO THIS IS FOR. `resolve` has accepted and used
                        # `audience_key` since it was written; nothing ever
                        # passed it from here, so the one parameter that names
                        # the reader stopped at the skill boundary.
                        audience_key=str(params.get("audience_key") or ""))

    # OWNER INPUT, ONTO THE BUNDLE — one route, here, for every skill.
    #
    # `resolve` builds the bundle from the DATA LAYER; these are this run's
    # instruction, and the drafters read the bundle. `ad_copy` grew a private
    # two-line hop for exactly this while `campaign_email` read the params
    # directly and never declared the parameter, so the same fact arrived by
    # two routes, one of which was a dead end, and a third skill would have
    # invented a fourth. Doing it once here is what stops that.
    #
    # Only what the skill DECLARES, so this can never smuggle in a parameter
    # `run` would otherwise have refused, and only non-blank values, so an
    # absent offer stays absent rather than becoming an empty string that
    # reads as "there is one".
    for _k in OWNER_INPUT:
        if _k in sk.params and str(params.get(_k) or "").strip():
            bundle[_k] = str(params[_k]).strip()

    coverage = bundle.get("coverage") or {}

    # What the bundle could not carry is a LABEL on the work, never a reason to
    # refuse it. This used to append `sk.needs` misses to `blocked` and return
    # before the skill ever ran, so an account with no approved objection got
    # silence instead of a reply — a gate built on absent data, which is §2.27
    # in the one place it costs a customer an answer.
    #
    # The gap still has to survive to the output, or this trades a refusal for
    # a confident-sounding draft with nothing behind it, which is worse. So it
    # is carried three ways: a note the caller can read, `thin` on the result,
    # and a knowledge task filed where the operator already works.
    thin = list(bundle.get("blocked_on") or []) + list(pre.get("thin") or [])
    # A DECLARED PART THAT DID NOT ARRIVE IS A BUG, AND IT TRAVELS THE SAME PIPE.
    #
    # `bundle.verify` compares the built package against what `PARTS` promised
    # and `resolve` logs the shortfall — to the LOG, which nobody reads. It is
    # the highest-signal thing this layer can say (the `audiences` defect is
    # exactly this, undetected for the life of the codebase), so it rides
    # `thin` like every other gap and lands on Assurance beside them, per
    # system. No new column, no second pipe: the one that already works.
    for _absent in (coverage.get("promised_but_absent") or []):
        thin.append(f"package:{_absent} — declared and not supplied")
    missing = [p for p in sk.needs if not _dig(bundle, p)]
    if missing:
        thin.append("nothing on file at: " + ", ".join(missing))

    # The one gate left that is about knowledge, and it is per skill rather
    # than a global bar — see `constitutive`.
    absent = kb.needs_met(tenant, sk.constitutive) if sk.constitutive else []
    # THE OVERRIDE, and what it may not reach. Owner, 2026-08-29: a system
    # that requires an approval must block on it "OR approval override".
    #
    # A REASON, NOT A FLAG. `override_needs=1` is turning the check off;
    # `override_needs="the ban list is being rebuilt, this is an internal
    # draft"` is a decision somebody signed. Empty is refused, because an
    # override nobody can be asked about later is indistinguishable from a bug.
    #
    # AND NOT EVERY NEED YIELDS TO IT. A missing claim makes an output
    # THINNER; a missing ban list makes every output UNVERIFIED, because the
    # validator then has nothing to refuse against. Those are different kinds
    # of missing and they do not get the same rights — `systems.NEEDS` says
    # which is which and why, in one place both this gate and the console read.
    if absent and override:
        from . import systems as _sysm
        hard = [a for a in absent
                if not (_sysm.NEEDS.get(a.split(" (")[0].strip(), {})
                        .get("overridable", True))]
        if hard:
            absent = [f"{a} — CANNOT be overridden: "
                      + (_sysm.NEEDS.get(a.split(" (")[0].strip(), {})
                         .get("why_not", "")) for a in hard]
        else:
            # Proceeds, and says so everywhere the run is read: a note, the
            # `thin` list the assurance ledger keeps, and the run row itself.
            # A draft produced under an override must never be mistaken for
            # one produced under the gate.
            thin.append(f"OVERRIDDEN: ran without {', '.join(absent)} — "
                        f"{override}")
            absent = []
    if absent:
        why = [f"{sk.key} cannot say anything true without: " + ", ".join(absent)]
        systems.finish_run(run_id, "blocked", blocked_on="; ".join(why))
        ledger.record(tenant, sk.system_key, status="blocked",
                      blocked_on=why, run_id=run_id, format=sk.produces)
        return {"skill": key, "tenant": tenant, "status": "blocked",
                "blocked_on": why, "items": [], "notes": [], "thin": thin,
                "coverage": coverage, "gaps": bundle.get("gaps") or [],
                "run_id": run_id}

    ctx = Context(tenant=tenant, skill=sk, bundle=bundle, params=params,
                  run_id=run_id, autonomy=pre["autonomy"], thin=thin)
    for gap in thin:
        ctx.note(f"working without: {gap}")
    if thin:
        # `basis="unknown"` and `attribute` are what record_unknowns FILTERS ON
        # — the first version of this call passed `field`/`why` and would have
        # recorded nothing at all while returning cleanly. Asserting the count
        # rather than trusting the return is the §1 rule about bulk writes.
        try:
            filed = kb.record_unknowns(
                tenant, [{"basis": "unknown", "attribute": g} for g in thin],
                asked_for=f"{sk.system_key} produced without it")
            if not filed:
                ctx.note("this gap could not be filed as a knowledge task")
        except Exception:                                       # noqa: BLE001
            pass    # a knowledge task that cannot be filed must not lose the draft

    try:
        result = sk.run(ctx) or {}
    except Exception as exc:                                    # noqa: BLE001
        systems.finish_run(run_id, "failed", error=f"{exc.__class__.__name__}: {exc}")
        return {"skill": key, "tenant": tenant, "status": "failed",
                "blocked_on": [f"{exc.__class__.__name__}: {exc}"],
                "trace": traceback.format_exc(limit=4),
                "items": [], "notes": ctx.notes, "coverage": coverage,
                "run_id": run_id}

    # `empty` is a real outcome and is not `blocked`. A sweep that found no
    # violations has succeeded; reporting it the same way as one that could not
    # run is the defect this codebase has met five times.
    status = "produced" if ctx.items else "empty"
    stage = "draft" if ctx.items else "sent"
    if ctx.items and all(i["status"] == "blocked" for i in ctx.items):
        stage, status = "blocked", "produced"

    # A consumed plan KEEPS its brief — the plan is the record of what this
    # run was asked to do, and overwriting it here was how the instruction
    # would have vanished at the exact moment it was carried out. (The old
    # write was also a plain string into a JSON column — §1's signature
    # defect, one writer and no reader.)
    finish_fields = dict(output=f"{len(ctx.items)} item(s)")
    if not consuming:
        finish_fields["brief"] = {"skill": sk.key, "tier": sk.tier}
    systems.finish_run(run_id, stage, **finish_fields)

    return {"skill": key, "tenant": tenant, "status": status,
            "blocked_on": [], "items": ctx.items, "notes": ctx.notes,
            "coverage": coverage, "gaps": bundle.get("gaps") or [],
            # What it produced this WITHOUT. Empty means fully grounded; a
            # caller rendering an item is expected to say so when it is not,
            # the same way `ad_copy` carries `basis`.
            "thin": thin,
            "autonomy": ctx.autonomy, "run_id": run_id,
            "summary": result.get("summary", ""), "detail": result}
