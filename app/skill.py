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

import traceback
from dataclasses import dataclass, field
from typing import Callable

from . import kb, ledger, resolve as rs, systems, tenants, validator

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
    needs: tuple = ()               # dotted bundle paths it cannot work without
    params: tuple = ()              # accepted inputs; anything else is refused
    writes: bool = False            # does it mutate anything outside the ledger
    produces: str = "report"        # report | draft | proposal
    run: Callable = None            # (Context) -> dict


REGISTRY: dict[str, Skill] = {}


def register(skill: Skill) -> Skill:
    if skill.key in REGISTRY:
        raise ValueError(f"skill {skill.key!r} is already registered")
    REGISTRY[skill.key] = skill
    return skill


def get(key: str) -> Skill | None:
    return REGISTRY.get(key)


def catalogue(tenant: str = "") -> list[dict]:
    """Every skill, and — if a tenant is named — whether it can run for them.

    This is what an agent should be shown instead of a list of tools. A skill
    that is blocked says so here, with the missing field, so the agent does not
    discover it by failing.
    """
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
             redraft=None, meta: dict | None = None) -> dict:
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
        """
        cite = (self.skill.produces in ("draft", "proposal")
                if require_citation is None else require_citation)

        def _check(text):
            return validator.check(
                self.tenant, text, claim_ids=claim_ids or [],
                entity_key=entity_key, conversation_id=conversation_id,
                require_citation=cite)

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
                run_id=self.run_id)

        row = ledger.record(
            self.tenant, self.skill.system_key,
            situation=situation, entity_key=entity_key,
            audience_key=audience_key, claim_ids=claim_ids or [],
            angle=angle, format=fmt or self.skill.produces,
            status=status,
            blocked_on=[f["rule"] for f in verdict["failures"]],
            destination=destination, body=body,
            conversation_id=conversation_id, run_id=self.run_id)

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
                try:
                    kb.record_unknowns(
                        self.tenant,
                        [{"key": entity_key, "name": entity_key,
                          "attribute": n["needs"]} for n in needs],
                        asked_for=body[:300])
                except Exception:                                # noqa: BLE001
                    pass                    # never let bookkeeping lose output
            self.note(
                f"could not be said within the rules after "
                f"{len(attempts)} repair attempt(s). "
                + (needs[0]["why"] if needs else
                   "; ".join(f["fix"] for f in verdict["failures"])[:200]))

        item = {"body": body, "ok": verdict["ok"],
                "failures": verdict["failures"], "checked": verdict["checked"],
                "disposition": disposition, "status": status,
                "output_id": row.id, "entity_key": entity_key,
                "claim_ids": list(claim_ids or []),
                "repairs": len(attempts),
                "repair_history": attempts,
                "needs": needs, "meta": meta or {}}
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
    if autonomy == "approve_all":
        return "needs_approval"
    return "recorded"          # shadow: it happened, it does not leave


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
            f"install it on the Systems tab, then fill its 8-part contract"]}
    if row.status == "retired":
        return {"status": "blocked",
                "blocked_on": [f"the {sk.system_key} system is retired"]}

    gate = systems.ready(row)
    if not gate["ready"]:
        return {"status": "blocked", "blocked_on": gate["blockers"],
                "autonomy": row.autonomy, "system_id": row.id}
    return {"status": "ready", "blocked_on": [], "autonomy": row.autonomy,
            "system_id": row.id}


def run(key: str, tenant: str, *, trigger: str = "manual", ref: str = "",
        **params) -> dict:
    """Run one skill for one account. The only entry point.

    Everything a caller needs to decide what happens next is in the return:
    what was searched, what could not be grounded, what was produced and what
    each produced thing is allowed to do.
    """
    sk = get(key)
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
        run_id = ""
        if pre["status"] == "blocked":
            if pre.get("system_id"):
                run_id = systems.start_run(pre["system_id"], tenant,
                                           trigger=trigger, ref=ref or key)
                systems.finish_run(run_id, "blocked",
                                   blocked_on="; ".join(pre["blocked_on"]))
            ledger.record(tenant, sk.system_key if sk else key,
                          status="blocked", blocked_on=pre["blocked_on"],
                          run_id=run_id, format=sk.produces if sk else "")
        return {"skill": key, "tenant": tenant, "status": pre["status"],
                "blocked_on": pre["blocked_on"], "items": [], "notes": [],
                "coverage": {}, "run_id": run_id}

    unknown = [p for p in params if p not in sk.params]
    if unknown:
        # Refuse rather than ignore. A silently dropped parameter is the
        # caller believing it asked for something it did not get.
        return {"skill": key, "tenant": tenant, "status": "refused",
                "blocked_on": [f"unknown parameter(s): {', '.join(sorted(unknown))}"
                               f" — this skill accepts {', '.join(sk.params) or 'none'}"],
                "items": [], "notes": [], "coverage": {}, "run_id": ""}

    run_id = systems.start_run(pre["system_id"], tenant, trigger=trigger,
                               ref=ref or key)

    bundle = rs.resolve(tenant, system=sk.system_key, tier=sk.tier,
                        utterance=str(params.get("utterance") or ""),
                        contact_id=str(params.get("contact_id") or ""),
                        entity_key=str(params.get("entity_key") or ""))

    coverage = bundle.get("coverage") or {}
    blocked = list(bundle.get("blocked_on") or [])
    missing = [p for p in sk.needs if not _dig(bundle, p)]
    if missing:
        blocked.append("the bundle carried nothing at: " + ", ".join(missing))

    if blocked:
        systems.finish_run(run_id, "blocked", blocked_on="; ".join(blocked))
        ledger.record(tenant, sk.system_key, status="blocked",
                      blocked_on=blocked, run_id=run_id,
                      format=sk.produces)
        return {"skill": key, "tenant": tenant, "status": "blocked",
                "blocked_on": blocked, "items": [], "notes": [],
                "coverage": coverage, "gaps": bundle.get("gaps") or [],
                "run_id": run_id}

    ctx = Context(tenant=tenant, skill=sk, bundle=bundle, params=params,
                  run_id=run_id, autonomy=pre["autonomy"])

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

    systems.finish_run(run_id, stage,
                       output=f"{len(ctx.items)} item(s)",
                       brief=f"{sk.key} · tier {sk.tier}")

    return {"skill": key, "tenant": tenant, "status": status,
            "blocked_on": [], "items": ctx.items, "notes": ctx.notes,
            "coverage": coverage, "gaps": bundle.get("gaps") or [],
            "autonomy": ctx.autonomy, "run_id": run_id,
            "summary": result.get("summary", ""), "detail": result}
