"""Systems registry — an installed pipeline as an object rather than a label.

Until now a "system" was a string in `Tenant.systems`: `["campaign_email",
"reports"]`. That is enough to render a chip and nothing else. It could not
answer whether the system was safe to switch on, what it had produced, whether
a human kept rewriting its output, or whether it should be killed.

This module makes it answerable. Three things live here:

  1. READINESS  — a system is not "on" because someone typed its name. It is on
     when its contract is complete, its tenant's capabilities are wired, and
     (if it writes) the KB can ground it. `ready()` returns the named blockers,
     in the same refuse-and-name style as the brief assembler.

  2. AUTONOMY   — the earned ladder as a state machine with gates, not a
     principle in a document. Promotion requires run history, so "it's been
     fine" has to be a number before it becomes a permission.

  3. FEEDBACK   — the per-system thread. Prose guidance becomes a scoped Memory
     injected into that system's drafting prompt. A *rule* gets promoted into
     the KB where the deterministic validator enforces it. The distinction is
     the whole point: a prompt mostly obeys, a validator always blocks.
"""
from __future__ import annotations

import datetime as dt

from . import db, kb, tenants

# The lifecycle of the system itself, distinct from how much rope it has.
STATUSES = ("designed", "live", "paused", "retired")

# The earned-autonomy ladder (locked decision #7). Order is meaningful — the
# index is the rung, and promotion may only ever move up by one.
AUTONOMY = ("shadow", "approve_all", "approve_exceptions", "auto")

AUTONOMY_MEANING = {
    "shadow": "Runs and records, sends nothing. You compare against what you'd have done.",
    "approve_all": "Every output waits for your tap before it leaves.",
    "approve_exceptions": "Routine output sends itself; anything the rules flag waits for you.",
    "auto": "Sends without asking. Alerts on anomaly. Kill criteria are armed.",
}

# The 8-part contract. ADVISORY since 2026-08-20 (owner's call): it is
# computed, shown on the card, and gates promotion to `auto` — the rung where
# nobody reads the output — and nothing else. Requiring eight prose answers
# before a system may run stopped work it did not protect, and filed those
# answers onto the knowledge queue as gaps the ACCOUNT was missing.
CONTRACT = (
    ("job_replaced", "Job replaced", "The human task this removes. If nobody was doing it, this is a feature, not a system."),
    ("owner", "Owner", "Who is accountable when it misbehaves. A name, not a team."),
    ("baseline", "Baseline", "The number before it existed. Without this nothing can be proven later."),
    ("primary_metric", "Primary metric", "The one number that says it works. One."),
    ("counterfactual", "Counterfactual", "How you'd know the change wasn't seasonality or something else you did."),
    ("kill_criteria", "Kill criteria", "What makes you switch it off. Decided now, while it's cheap to be honest."),
    ("failure_mode", "Failure mode", "How it breaks, and who notices first."),
    ("weekly_artifact", "Weekly artifact", "What lands in the client's inbox on Friday."),
)
CONTRACT_FIELDS = tuple(f for f, _, _ in CONTRACT)

# Promotion gates. A rung is earned with evidence, so these are thresholds
# rather than judgement. Tunable, but never zero.
GATES = {
    "approve_exceptions": {"min_runs": 20, "min_approval_rate": 0.90, "clean_tail": 10},
    "auto": {"min_runs": 50, "min_approval_rate": 0.95, "clean_tail": 20},
}


# ---------------------------------------------------------------------------
# Catalogue — what kinds of system exist, and what each one needs to function.
#
# `requires` is an AND: every capability must be wired. `requires_any` is an OR:
# at least one. Reports needs *some* data source but doesn't care which, and
# collapsing that into a single AND list would either block it wrongly or wave
# through a report with nothing behind it.
# ---------------------------------------------------------------------------

CATALOG = {
    "lead_responder": dict(
        name="Lead responder",
        does="Answers an inbound enquiry with a grounded, approved draft.",
        requires=("inbox",), requires_any=(), needs_kb=True,
        kb_needs=("tone", "banned_claims", "audience", "objection", "claim",
                  "next_steps")),
    "campaign_email": dict(
        name="Campaign email",
        does="Builds and schedules campaign sends from the catalogue and calendar.",
        requires=("esp",), requires_any=(), needs_kb=True,
        kb_needs=("tone", "banned_claims", "entity", "claim")),
    "blog": dict(
        name="Blog / content",
        does="Publishes grounded articles against the keyword map.",
        requires=("cms",), requires_any=(), needs_kb=True,
        kb_needs=("tone", "banned_claims", "audience", "claim")),
    "reorder_engine": dict(
        name="Reorder engine",
        does="Triggers replenishment prompts off purchase cadence.",
        requires=("commerce", "esp"), requires_any=(), needs_kb=False,
        kb_needs=("entity",)),
    "service_desk": dict(
        name="Service desk",
        does="Handles routine inbound support with a drafted, checked reply.",
        requires=("inbox",), requires_any=(), needs_kb=True,
        kb_needs=("tone", "banned_claims", "objection", "entity")),
    "content_compliance": dict(
        name="Website content compliance",
        does="Checks the live site against the brand's own banned claims and "
             "reports the pages that break them.",
        # Needs no connection: the site is public. It needs the RULES, which is
        # the whole point — an account with no banned_claims has nothing to
        # check against and the system says so rather than passing everything.
        requires=(), requires_any=(), needs_kb=True,
        kb_needs=("banned_claims",)),
    "catalog_compliance": dict(
        name="Catalogue compliance",
        does="Checks product copy and SEO metadata in the store against the "
             "brand's own banned claims, and proposes compliant replacements.",
        # Distinct from content_compliance, which reads the public site. The
        # crawler only ever sees rendered prose — `<head>` is stripped before
        # matching — so an SEO meta description carrying a banned claim is
        # invisible to it while being the field most likely to hold one,
        # because meta descriptions get templated across a whole catalogue.
        requires=("commerce",), requires_any=(), needs_kb=True,
        kb_needs=("banned_claims",)),
    "ad_creative": dict(
        name="Ad creative",
        does="Drafts grounded ad copy from approved claims against an audience "
             "and an entity. Copy only — imagery waits on the media layer.",
        requires=(), requires_any=("ads", "commerce"), needs_kb=True,
        kb_needs=("tone", "banned_claims", "audience", "claim", "entity")),
    "reports": dict(
        name="Reports",
        does="The weekly number, assembled from whatever is connected.",
        requires=(), requires_any=("analytics", "ads", "commerce"), needs_kb=False,
        kb_needs=()),
}


def spec(key: str) -> dict:
    return CATALOG.get(key, dict(name=key.replace("_", " ").title(),
                                 does="", requires=(), requires_any=(),
                                 needs_kb=False, kb_needs=()))


def prerequisites(tenant: str, key: str) -> dict:
    """What one system needs for one account, item by item, met or not.

    `ready()` answers the same question for a system that is already installed
    and returns prose. This answers it BEFORE installing and returns the items
    separately, because the two failures have different fixes and lumping them
    into one sentence is what made the install dropdown a guess: a missing
    connection is a credential to go and wire, a missing knowledge field is
    something to go and write, and neither is visible until you have already
    committed to the system.

    The 8-part contract is deliberately absent here, and is no longer a
    prerequisite for going live either — it is advisory, and gates only
    promotion to `auto`. A system starts in shadow with an empty contract
    on purpose, so that filling it is a decision made while looking at the
    thing rather than a toll gate before seeing it.
    """
    sp = spec(key)
    caps = tenants.capabilities(tenant)
    items: list[dict] = []

    for c in sp["requires"]:
        items.append({"kind": "connection", "name": c, "met": bool(caps.get(c)),
                      "note": "required"})
    if sp["requires_any"]:
        met = any(caps.get(c) for c in sp["requires_any"])
        items.append({"kind": "connection",
                      "name": " or ".join(sp["requires_any"]),
                      "met": met, "note": "at least one"})

    needs = tuple(sp.get("kb_needs") or ())
    if needs:
        absent = set(kb.needs_met(tenant, needs))
        for f in needs:
            items.append({"kind": "knowledge", "name": f,
                          "met": f not in absent, "note": ""})
    elif sp["needs_kb"]:
        c = kb.completeness(tenant)
        items.append({"kind": "knowledge", "name": "knowledge base",
                      "met": bool(c["ready"]),
                      "note": ", ".join(c["missing"])[:80]})

    missing = [i for i in items if not i["met"]]
    return {"key": key, "name": sp["name"], "does": sp["does"],
            "items": items, "missing": missing, "ready": not missing}


def installable(tenant: str) -> list[dict]:
    """Every catalogue system for this account, installed or not, with why.

    Sorted so what can be switched on now comes first — the point of the list
    is to answer "what can I turn on", and burying two ready systems under six
    blocked ones answers it badly.
    """
    have = {r.key: r for r in for_tenant(tenant)}
    out = []
    for key in CATALOG:
        pre = prerequisites(tenant, key)
        row = have.get(key)
        pre["installed"] = bool(row)
        pre["system_id"] = row.id if row else ""
        pre["status"] = row.status if row else ""
        pre["autonomy"] = row.autonomy if row else ""
        out.append(pre)
    return sorted(out, key=lambda p: (p["installed"], not p["ready"],
                                      p["name"]))


def waiting_on(tenant: str) -> dict[str, list[str]]:
    """Which installed systems are blocked on each outstanding KB answer.

    This is what makes intake scale: a system declares the knowledge it needs,
    and the questions a client is asked are generated from the systems actually
    switched on for them. Adding a system later adds its questions automatically
    — nobody has to remember to update an onboarding form.
    """
    from . import kb
    open_steps = {g["id"] for g in kb.gaps(tenant)}
    out: dict[str, list[str]] = {}
    for row in for_tenant(tenant):
        if row.status == "retired":
            continue
        for step in spec(row.key).get("kb_needs", ()):
            if step in open_steps:
                out.setdefault(step, []).append(row.name)
    return out


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def get(system_id: str) -> db.System | None:
    with db.SessionLocal() as s:
        row = s.get(db.System, system_id)
        if row:
            s.expunge(row)
        return row


def find(tenant: str, key: str) -> db.System | None:
    with db.SessionLocal() as s:
        row = s.query(db.System).filter(db.System.tenant == tenant,
                                        db.System.key == key).first()
        if row:
            s.expunge(row)
        return row


def for_tenant(tenant: str) -> list[db.System]:
    with db.SessionLocal() as s:
        rows = (s.query(db.System).filter(db.System.tenant == tenant)
                .order_by(db.System.key).all())
        s.expunge_all()
        return rows


#: Systems whose work is done by a pipeline of its own, not by the substrate.
#:
#: `inbox_triage` is the mail path: `worker.process_emails` calls
#: `triage.triage_email`, which drafts, guards and files its OWN runs. Its
#: System row exists to hold that ledger, not to declare that the substrate
#: should generate for it.
#:
#: Without this it was swept up by `systems_tick` — the loop that evaluates the
#: catalogue — and reported "no generator yet" every day, so the one pipeline
#: actually answering the owner's email was the loudest thing in the backlog
#: claiming it could not run. It had been drafting all along.
def is_on(system) -> bool:
    """THE switch. One question, one answer, everywhere.

    Owner's rule, 2026-08-20: *"The off/on mechanism needs to be the dictator
    of whether a system is running or not."* Before this there were three
    different answers — `skill.preflight` blocked only `retired`, so a PAUSED
    system still ran skills; `systems_tick` evaluated `live` AND `designed`;
    and run re-homing checked nothing at all but existence. A switch that three
    call sites interpret differently is not a switch.

    Only `live` is on. `designed` means built and not yet switched on, which is
    off — the previous behaviour of evaluating designed systems was a
    deliberate choice to collect blockers early, and it is exactly what filled
    the log with daily rows for pipelines nobody had turned on.

    Takes a row or None, so a caller does not have to check twice.
    """
    return (getattr(system, "status", "") or "") == "live"


#: Systems with a generator that runs on a schedule of its OWN, not the tick.
#:
#: `compliance_sweep` runs both of these weekly. Before it existed they were
#: genuinely un-run, and the tick's "no generator yet" was true; now it would
#: be a daily row claiming a check does not exist five days after it swept the
#: whole site.
SCHEDULED_ELSEWHERE = ("content_compliance", "catalog_compliance")


def externally_driven() -> frozenset:
    """Systems whose runs are filed by something other than `systems_tick`.

    Two kinds, and neither is missing a generator:

    * the mail path's — read from `replies.HANDLED_BY_MAIL` so the routing
      table is the single place that decides. A system receiving triage's runs
      is having its work done, and evaluating it here would file "no generator
      yet" against a pipeline that answered nine emails that morning.
    * `SCHEDULED_ELSEWHERE` — a generator with its own weekly slot.

    The tick evaluates what is left: systems whose generator genuinely does not
    exist yet, which is the honest use of that message.
    """
    from . import replies
    return replies.HANDLED_BY_MAIL | frozenset(SCHEDULED_ELSEWHERE)


#: Kept for callers that want the plain name. See `externally_driven()`.
EXTERNALLY_DRIVEN = ("inbox_triage",)


def all_systems() -> list[db.System]:
    with db.SessionLocal() as s:
        rows = (s.query(db.System)
                .order_by(db.System.tenant, db.System.key).all())
        s.expunge_all()
        return rows


def create(tenant: str, key: str, name: str = "") -> db.System:
    existing = find(tenant, key)
    if existing:
        return existing
    with db.SessionLocal() as s:
        row = db.System(tenant=tenant, key=key,
                        name=name or spec(key)["name"])
        s.add(row)
        s.commit()
        s.refresh(row)
        s.expunge(row)
        return row


def update(system_id: str, **fields) -> dict:
    """Set contract fields, status or autonomy. Refuses anything it doesn't know."""
    allowed = set(CONTRACT_FIELDS) | {"name", "status", "autonomy", "notes"}
    bad = set(fields) - allowed
    if bad:
        return {"error": f"unknown field(s): {sorted(bad)}"}
    with db.SessionLocal() as s:
        row = s.get(db.System, system_id)
        if not row:
            return {"error": "unknown system"}
        if "status" in fields and fields["status"] not in STATUSES:
            return {"error": f"status must be one of {STATUSES}"}
        if "autonomy" in fields and fields["autonomy"] not in AUTONOMY:
            return {"error": f"autonomy must be one of {AUTONOMY}"}
        # Going live is gated on readiness: connections and the knowledge the
        # system declared it needs. NOT on the contract — that became advisory
        # on 2026-08-20 (see `ready`), because requiring eight prose answers
        # before a system may run was stopping work it did not protect. The
        # contract still gates `auto`, which is the rung it was written for.
        if fields.get("status") == "live" and row.status != "live":
            r = ready(row)
            if not r["ready"]:
                return {"error": "not ready to go live", "blockers": r["blockers"]}
            row.went_live_at = db.utcnow()
        for k, v in fields.items():
            setattr(row, k, v)
        s.commit()
        return {"ok": True, "system": row.id}


# ---------------------------------------------------------------------------
# Readiness — named blockers, never a bare boolean
# ---------------------------------------------------------------------------

def ready(system: db.System) -> dict:
    """Can this system safely run? If not, exactly what is absent."""
    sp = spec(system.key)
    # Sorted as they are FOUND, never re-derived from the message text.
    #
    # The first version of this classified `impossible` with
    # `b.startswith("not connected:")` — string-matching against prose this
    # same function had assembled three lines earlier, which is §1's
    # "string-matching instead of state-checking" written by the person who
    # had just quoted that rule. Rewording a blocker, an innocuous edit,
    # would have silently reclassified every connection gap as `thin`, and a
    # system with no mailbox would have started producing replies it had no
    # way to send. The two lists are built where the facts are known.
    impossible: list[str] = []      # producing is not possible at all
    thin: list[str] = []            # producing is possible, and worse

    # The contract is ADVISORY. Owner's call, 2026-08-20: *"Every system
    # currently has to fill in the contract otherwise the system fails. That
    # doesn't need to happen."*
    #
    # It stays computed and visible — `contract_complete` is what the Systems
    # card renders, and the eight questions are genuinely worth answering — but
    # it is no longer a `thin` gap. As one it was reported as something the
    # account was MISSING on every tick, filed through `record_unknowns` onto
    # the knowledge queue, and rendered in the backlog as "would have run
    # without: contract: Job replaced, Owner, ..." — three of the top four
    # items on a real week's ranking of what to go and write, none of which is
    # knowledge and none of which any amount of writing about the client would
    # ever satisfy.
    #
    # It is kept as a gate on ONE thing only: see `can_promote`. Running
    # unattended without kill criteria or a failure mode is the case the eight
    # questions were written for, and it is the only case where the answer is
    # load-bearing rather than useful.
    missing_contract = [label for f, label, _ in CONTRACT
                        if not (getattr(system, f, "") or "").strip()]

    caps = tenants.capabilities(system.tenant)
    absent = [c for c in sp["requires"] if not caps.get(c)]
    if absent:
        impossible.append("not connected: " + ", ".join(absent))
    if sp["requires_any"] and not any(caps.get(c) for c in sp["requires_any"]):
        impossible.append("needs at least one of: " + ", ".join(sp["requires_any"]))

    # Gate on what THIS system declared it needs, not on a single global bar.
    # `kb_needs` was declared per system and read nowhere — `ready` called
    # `completeness()`, so every system was blocked until the whole knowledge
    # base was populated. Compliance, which uses one field, was held to the same
    # bar as the lead responder, which uses six; and `next_steps`, which the
    # lead responder does need, was checked by neither.
    needs = tuple(sp.get("kb_needs") or ())
    if needs:
        absent_kb = kb.needs_met(system.tenant, needs)
        if absent_kb:
            thin.append("knowledge base: " + ", ".join(absent_kb))
    elif sp["needs_kb"]:
        # Declares it needs the KB but names no fields — fall back to the old
        # global bar rather than silently letting it through.
        c = kb.completeness(system.tenant)
        if not c["ready"]:
            thin.append("knowledge base: " + ", ".join(c["missing"]))

    # Two questions, and they are NOT the same question.
    #
    # `ready` answers "may this system act unsupervised" — go-live, promotion.
    # A blank contract and a thin knowledge base belong there: both are reasons
    # not to trust it loose.
    #
    # `can_produce` answers "may this system make something a human will read".
    # Only an absent CONNECTION belongs there, because that is the one gap that
    # makes producing impossible rather than merely thinner — you cannot answer
    # mail you cannot fetch. Missing knowledge makes a draft worse, and a worse
    # draft that says what it is missing beats no draft at all.
    #
    # Conflating them is why an approved objection was standing between a
    # customer and a reply. Owner's rule, and the one this file already claims
    # to follow: enrich, do not gatekeep.
    blockers = impossible + thin
    return {"ready": not blockers, "blockers": blockers,
            "contract_complete": not missing_contract,
            "missing_contract": missing_contract,
            "can_produce": not impossible, "impossible": impossible,
            "thin": thin}


# ---------------------------------------------------------------------------
# Autonomy — evidence, then permission
# ---------------------------------------------------------------------------

def stats(system_id: str) -> dict:
    """Run history, reduced to the numbers a promotion decision needs."""
    rows = runs(system_id, limit=0)
    decided = [r for r in rows if r.decision in ("approved", "denied", "edited", "auto")]
    approved = [r for r in decided if r.decision in ("approved", "auto")]
    edited = [r for r in decided if r.decision == "edited"]
    denied = [r for r in decided if r.decision == "denied"]
    blocked = [r for r in rows if r.stage == "blocked"]
    rate = (len(approved) / len(decided)) if decided else 0.0
    return {"total": len(rows), "decided": len(decided),
            "approved": len(approved), "edited": len(edited),
            "denied": len(denied), "blocked": len(blocked),
            "approval_rate": round(rate, 3)}


def can_promote(system: db.System) -> dict:
    """Is the next rung earned? Returns the target and why not, if not."""
    try:
        i = AUTONOMY.index(system.autonomy or "shadow")
    except ValueError:
        i = 0
    if i >= len(AUTONOMY) - 1:
        return {"can": False, "target": "", "why": "already fully autonomous"}
    target = AUTONOMY[i + 1]

    r = ready(system)
    if not r["ready"]:
        return {"can": False, "target": target,
                "why": "not ready: " + "; ".join(r["blockers"])}

    # The contract gates the UNATTENDED rung and nothing else.
    #
    # Everywhere else it is advisory (see `ready`). Here it is not: `auto` is
    # the rung where no human reads the output, and the questions that matter
    # then are exactly the ones the contract asks — what makes us switch this
    # off, how does it break, and who notices. A system running loose with
    # those blank is the case the eight questions exist for.
    if target == "auto":
        gaps = [label for f, label, _ in CONTRACT
                if not (getattr(system, f, "") or "").strip()]
        if gaps:
            return {"can": False, "target": target,
                    "why": ("nothing reads the output on `auto`, so the "
                            "contract has to be answered first — still blank: "
                            + ", ".join(gaps))}

    gate = GATES.get(target)
    if not gate:  # shadow -> approve_all needs readiness only; nothing has run yet
        return {"can": True, "target": target, "why": ""}

    st = stats(system.id)
    if st["decided"] < gate["min_runs"]:
        return {"can": False, "target": target,
                "why": f"{st['decided']} decided runs, needs {gate['min_runs']}"}
    if st["approval_rate"] < gate["min_approval_rate"]:
        return {"can": False, "target": target,
                "why": f"approval rate {st['approval_rate']:.0%}, "
                       f"needs {gate['min_approval_rate']:.0%}"}
    tail = [r for r in runs(system.id, limit=gate["clean_tail"])
            if r.decision == "denied"]
    if tail:
        return {"can": False, "target": target,
                "why": f"a denial inside the last {gate['clean_tail']} runs"}
    return {"can": True, "target": target, "why": ""}


def promote(system_id: str) -> dict:
    """Move up exactly one rung, and only if the gate is met."""
    sysrow = get(system_id)
    if not sysrow:
        return {"error": "unknown system"}
    verdict = can_promote(sysrow)
    if not verdict["can"]:
        return {"error": verdict["why"] or "cannot promote",
                "autonomy": sysrow.autonomy}
    return {**update(system_id, autonomy=verdict["target"]),
            "autonomy": verdict["target"]}


def demote(system_id: str, reason: str = "") -> dict:
    """Drop a rung. Always allowed — pulling rope back never needs a gate."""
    sysrow = get(system_id)
    if not sysrow:
        return {"error": "unknown system"}
    i = max(0, AUTONOMY.index(sysrow.autonomy or "shadow") - 1)
    out = update(system_id, autonomy=AUTONOMY[i])
    if reason:
        note(sysrow.tenant, sysrow.key, f"Demoted to {AUTONOMY[i]}: {reason}")
    return {**out, "autonomy": AUTONOMY[i]}


# ---------------------------------------------------------------------------
# Runs — the ledger
# ---------------------------------------------------------------------------

def start_run(system_id: str, tenant: str, trigger: str = "manual",
              ref: str = "") -> str:
    with db.SessionLocal() as s:
        row = db.SystemRun(system_id=system_id, tenant=tenant,
                           trigger=trigger, ref=ref, stage="brief")
        s.add(row)
        s.commit()
        return row.id


def finish_run(run_id: str, stage: str, **fields) -> None:
    """Close a run out. `blocked` and `failed` are outcomes too — recorded, not
    dropped, because the pattern in what a system refuses is the KB backlog."""
    allowed = {"blocked_on", "brief", "output", "approval_id", "decision",
               "edit_diff", "outcome", "error"}
    with db.SessionLocal() as s:
        row = s.get(db.SystemRun, run_id)
        if not row:
            return
        row.stage = stage
        for k, v in fields.items():
            if k in allowed:
                setattr(row, k, v)
        # `skipped` joins the terminal set: a run that correctly produced
        # nothing (promo mail, a notification) is FINISHED, and leaving it open
        # would have it reported later as a run that died.
        if stage in ("sent", "blocked", "failed", "approved", "skipped",
                     "escalated", "not_built"):
            row.finished_at = db.utcnow()
        s.commit()


def runs(system_id: str, limit: int = 10) -> list[db.SystemRun]:
    with db.SessionLocal() as s:
        q = (s.query(db.SystemRun).filter(db.SystemRun.system_id == system_id)
             .order_by(db.SystemRun.created_at.desc()))
        if limit:
            q = q.limit(limit)
        rows = q.all()
        s.expunge_all()
        return rows


def blocked_reasons(tenant: str = "", days: int = 30) -> list[tuple[str, int]]:
    """What the pipelines refused on, most frequent first — the KB backlog,
    ordered by how often each gap actually cost an output."""
    since = db.utcnow() - dt.timedelta(days=days)
    with db.SessionLocal() as s:
        q = s.query(db.SystemRun).filter(db.SystemRun.stage == "blocked",
                                         db.SystemRun.created_at >= since)
        if tenant:
            q = q.filter(db.SystemRun.tenant == tenant)
        rows = q.all()
    counts: dict[str, int] = {}
    for r in rows:
        for reason in (r.blocked_on or []):
            counts[reason] = counts.get(reason, 0) + 1
    return sorted(counts.items(), key=lambda kv: -kv[1])


# ---------------------------------------------------------------------------
# The per-system thread
#
# Conversation reuses ChatMessage.thread, which already isolates cleanly per
# agent; the key just gets more specific. Durable guidance is a scoped Memory,
# because a note that only exists in a transcript stops affecting output the
# moment it scrolls out of the window.
# ---------------------------------------------------------------------------

def thread_key(tenant: str, key: str) -> str:
    return f"system:{tenant}:{key}"


def note(tenant: str, key: str, text: str) -> str:
    """Durable guidance for one system. Injected into its drafting prompt.

    This is the soft channel. Anything that must ALWAYS hold belongs in
    `promote_rule` instead — see the docstring there.
    """
    text = (text or "").strip()
    if not text:
        return "Nothing to note."
    scope = thread_key(tenant, key)
    stamp = db.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    with db.SessionLocal() as s:
        s.add(db.Memory(topic=f"{key} · {stamp}", content=text, scope=scope))
        s.commit()
    return f"Noted on {tenant}/{key}."


def notes(tenant: str, key: str, limit: int = 25) -> list[db.Memory]:
    with db.SessionLocal() as s:
        rows = (s.query(db.Memory)
                .filter(db.Memory.scope == thread_key(tenant, key),
                        db.Memory.status == "active")
                .order_by(db.Memory.created_at.desc()).limit(limit).all())
        s.expunge_all()
        return rows


def drop_note(note_id: str) -> str:
    with db.SessionLocal() as s:
        row = s.get(db.Memory, note_id)
        if not row:
            return "No such note."
        row.status = "archived"
        s.commit()
    return "Archived."


def feedback_block(tenant: str, key: str) -> str:
    """The system's own guidance, formatted for injection at drafting time.

    Generators call this. It is deliberately separate from the tenant's voice:
    voice is how the brand sounds everywhere, this is what you learned about
    THIS pipeline — and mixing them makes a lesson from one system quietly
    change the output of another.
    """
    rows = notes(tenant, key)
    if not rows:
        return ""
    lines = [f"- {r.content} ({r.created_at:%b %d})" for r in rows]
    return ("\n\nSTANDING GUIDANCE for this system (corrections you were given; "
            "treat as current instruction):\n" + "\n".join(lines))


def edit_lessons(tenant: str, key: str, limit: int = 5) -> str:
    """What a human actually changed, fed back to the thing that wrote it.

    `SystemRun.edit_diff` was the last of the declared-and-dead columns; it is
    written now, and until this it was read only by two REPORTS. A system that
    measures how much it gets rewritten and never sees the rewrites is not
    learning, it is keeping score.

    Three decisions, and the second is the one that keeps this honest.

    **Only edited runs.** A run sent as-is teaches nothing and would dilute the
    signal with confirmation.

    **Labelled as OBSERVED, never as instruction.** One person's one-off tidy
    is not a rule, and a model told "you were corrected" will over-fit to it —
    it will start writing every reply the way the last one was rewritten. The
    wording says these are the lines a human changed and asks it to notice the
    pattern, which is what a person reading their own edits would do. Anything
    that must hold EVERY time belongs in `promote_rule`, where a validator
    enforces it and no prompt is involved.

    **Scoped to the account and capped.** The samples are the client's own
    correspondence; they may inform that client's next draft and no other's.
    """
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=60)
    with db.SessionLocal() as s:
        ids = [r.id for r in s.query(db.System).filter(
            db.System.tenant == tenant, db.System.key == key).all()]
        if not ids:
            return ""
        rows = (s.query(db.SystemRun)
                .filter(db.SystemRun.system_id.in_(ids),
                        db.SystemRun.tenant == tenant,
                        db.SystemRun.created_at >= since,
                        db.SystemRun.edit_diff != None,      # noqa: E711
                        db.SystemRun.edit_diff != "",
                        db.SystemRun.decision == "edited")
                .order_by(db.SystemRun.created_at.desc())
                .limit(max(1, limit)).all())
        samples = [(r.created_at, (r.edit_diff or "").strip()) for r in rows]
    samples = [(w, t) for w, t in samples if t and t != "sent unchanged"]
    if not samples:
        return ""
    lines = []
    for when, text in samples:
        # One block per run, already capped by `edits.delta` at 12 lines/1200
        # chars. Trimmed again here because several of them share a prompt.
        lines.append(f"--- {when:%b %d} ---\n{text[:600]}")
    return ("\n\nWHAT A HUMAN CHANGED in your recent drafts for this system "
            "(observed, not instructions — read them for the pattern and write "
            "the next one closer to it; if something must hold every single "
            "time it belongs in the rules, not here):\n" + "\n".join(lines))


def guidance_block(tenant: str, key: str) -> str:
    """Everything this pipeline has been taught, for injection at drafting.

    The two halves answer to different authorities and are kept apart in the
    text for that reason: `feedback_block` is what somebody TOLD this system,
    `edit_lessons` is what somebody DID to its output. A correction that was
    stated is a stronger signal than one inferred from a diff, and collapsing
    them would hide which is which from the only reader that matters.
    """
    if not tenant or not key:
        return ""
    try:
        return feedback_block(tenant, key) + edit_lessons(tenant, key)
    except Exception:                                            # noqa: BLE001
        return ""       # guidance that cannot be read must not lose the draft


def promote_rule(tenant: str, phrase: str) -> str:
    """Turn a piece of feedback into a hard rule the validator enforces.

    The distinction this exists for: "stop saying handcrafted" as a note is a
    prompt nudge that usually works. As a banned claim it is a deterministic
    check that fails closed. Anything phrased as never/always belongs here —
    a model must never be the thing standing between a rule and an output.
    """
    phrase = (phrase or "").strip()
    if not phrase:
        return "A rule needs a phrase to match on."
    with db.SessionLocal() as s:
        brand = s.get(db.KbBrand, tenant)
        if not brand:
            return (f"No KB brand row for {tenant} — create the brand record "
                    f"before adding rules, or the validator has nothing to read.")
        current = list(brand.banned_claims or [])
        if phrase.lower() in [c.lower() for c in current]:
            return f"Already a rule for {tenant}."
        brand.banned_claims = current + [phrase]
        s.commit()
    return (f"Hard rule added for {tenant}: any draft containing "
            f"“{phrase}” is now rejected by the validator.")


# ---------------------------------------------------------------------------
# Seed — adopt the pipelines already named on each tenant
# ---------------------------------------------------------------------------

def seed_from_tenants() -> dict:
    """Turn every string in Tenant.systems into a real row.

    Idempotent. Everything lands as designed/shadow with an empty contract,
    which is the honest starting state: naming a pipeline was never the same
    as having decided how you'd know it worked.
    """
    added, existing = [], []
    for t in tenants.all_tenants(include_paused=True):
        for key in (t.systems or []):
            if find(t.key, key):
                existing.append(f"{t.key}/{key}")
                continue
            create(t.key, key)
            added.append(f"{t.key}/{key}")
    return {"added": added, "existing": existing}


def board() -> list[dict]:
    """Everything, flattened — what the Systems tab and `/systems` both read."""
    out = []
    for row in all_systems():
        r = ready(row)
        out.append({
            "id": row.id, "tenant": row.tenant, "key": row.key,
            "name": row.name, "status": row.status, "autonomy": row.autonomy,
            "does": spec(row.key)["does"],
            "ready": r["ready"], "blockers": r["blockers"],
            "stats": stats(row.id),
            "next_rung": can_promote(row),
        })
    return out
