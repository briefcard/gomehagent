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
                  "next_steps"),
        workflow=dict(
            unit="one thread's reply",
            artifact="gmail_draft",
            ship="approving sends the draft itself",
            measure="edits.py delta; sent-as-is rate")),
    "campaign_email": dict(
        name="Campaign email",
        does="Builds and schedules campaign sends from the catalogue and calendar.",
        requires=("esp",), requires_any=(), needs_kb=True,
        kb_needs=("tone", "banned_claims", "entity", "claim"),
        # The workflow declaration — see `workflow()`. `plan_fields` may only
        # name parameters the consuming skill declares TODAY; the suite pins
        # that, so growing the plan (subject line, planned hero) and teaching
        # the skill to honour it are forced to land in the same change.
        workflow=dict(
            unit="a campaign email to one segment",
            skill="campaign_email",
            cadence=dict(horizon_days=21, per_segment_monthly=1,
                         segment_rest_days=6),
            plan_fields=(
                dict(key="segment", label="Audience segment", required=True,
                     kind="segment"),
                # THE ANGLE IS DIRECTION, AND IT IS OPTIONAL. It was
                # required, which forced a person to invent a concept for
                # every send before anything could run — and the one thing a
                # model is genuinely good at here is proposing an angle from
                # the segment and what is in stock. Left blank the drafter
                # chooses one and the run records which, so the owner can read
                # it back and correct it next time.
                dict(key="goal", label="Angle / concept (optional)",
                     required=False),
                dict(key="subject", label="Subject line", required=False),
                # WHAT THE SEND IS FOR. Left blank the planner rotates it, so
                # a list is given to about three times for every time it is
                # asked; set here, the owner's choice stands. It is a choice
                # over a fixed vocabulary, not free text, for the same reason
                # segment is: an unknown value would silently mean "no intent".
                dict(key="intent", label="What this send is for",
                     required=False, kind="choice",
                     choices=("story", "education", "proof", "offer")),
                dict(key="entity_key", label="Featured entity", required=False,
                     kind="entity"),
                # The SOURCE for any urgency in the email. Blank means there
                # is no deadline — and then the craft check refuses to let the
                # copy imply one. Urgency is only honest when something real
                # is behind it, so the real thing is a field.
                dict(key="deadline", label="Real deadline or limit (optional)",
                     required=False),
                dict(key="draft_visual", label="Draft a Canva hero on a miss",
                     required=False, kind="flag"),
                # `draft_into_esp` is NOT a plan field. Producing the draft in
                # the client's ESP is what this system IS — a campaign that
                # stops short of the platform is not a lighter version of the
                # job, it is the job not done. The real choice sits one level
                # up, on the autonomy ladder: whether a human launches the
                # draft or the system is eventually trusted to. Offering it
                # per-plan invited a queue item that had quietly opted out of
                # its own purpose (owner, 2026-08-22). The parameter was removed
                # from the skill entirely later the same day: the draft is how
                # the owner SEES the work, so it is made whenever there is HTML
                # to make it from, and anything wrong with it rides in the
                # campaign name instead of withholding the draft.
            ),
            artifact="esp_campaign",
            ship="marks it launch-ready — launching stays human, in the ESP",
            measure="generated HTML vs the ESP draft at launch")),
    "moment_email": dict(
        name="Moments (windows worth writing into)",
        does="Watches for windows opening — a cart gone cold, an enquiry gone "
             "quiet — and lets what it finds decide which cohort the campaign "
             "planner writes to next, and when.",
        # `commerce` is not required: the inbox producer alone is a complete,
        # useful watcher for a venue or a specifier, and demanding a store
        # would make this switchable only for shops.
        requires=(), requires_any=("commerce", "inbox"), needs_kb=False,
        kb_needs=(),
        # NO `skill` AND NO `plan_fields`, deliberately — this system sends
        # nothing and owns no queue.
        #
        # The first cut gave it both: it filed one plan per PERSON, and every
        # one of those drafted a campaign bound to that person's whole
        # segment, because `esp_id_for` is what an Omnisend campaign targets.
        # Two cold carts would have been two identical sends to the entire
        # list. There is no per-contact sending surface here to fix that with
        # — per-contact logic lives in Automations, which nothing pushes
        # events to — so the honest shape is that moments INFORM
        # `campaign_rollout` rather than running beside it. One queue, one
        # decision about who gets written to, and nothing to collide with.
        workflow=dict(
            unit="a window noticed, and the cohort it argues for",
            artifact="none — it proposes nothing and sends nothing",
            ship="informs the campaign planner; the campaign system does the "
                 "sending, under its own switch and its own rung",
            measure="moments consumed into a plan vs moments that expired "
                    "unserved")),
    "blog": dict(
        name="Blog / content",
        does="Writes grounded articles against the keyword map, and publishes "
             "them where there is somewhere to publish to.",
        # NO `requires`, and that is the whole point (owner, 2026-08-26:
        # *"Remember we said if theres no CMS to publish to, just give me the
        # article copy"*).
        #
        # `requires=("cms",)` blocked GO-LIVE, so an account on Squarespace —
        # a platform with no content write API and no backend built — could
        # not run the system at all. But an article is real work before it is
        # a published page: it is drafted, checked against the ban list, run
        # through the validator and the structure checks, and kept whole in
        # `ArtifactBody`. Refusing to write it because there is nowhere to
        # push it withholds the nine-tenths that were possible.
        #
        # The publish half degrades instead of gating: `blog_article` reports
        # "DRAFTED ONLY, nothing queued" with the reason, and the copy is at
        # /admin/artifact/<output_id>?raw=1 to paste in by hand — which IS the
        # workflow on a platform with no write API, not a lesser version of it.
        requires=(), requires_any=(), needs_kb=True,
        kb_needs=("tone", "banned_claims", "audience", "claim"),
        # The planner and the skill landed together, 2026-08-25, which is what
        # the note here used to be waiting for.
        workflow=dict(
            unit="one article against one keyword",
            skill="blog_article",
            cadence=dict(horizon_days=45, articles_monthly=4),
            plan_fields=(
                # THE KEYWORD IS THE PLAN. Everything else about an article is
                # derivable from it once the map exists — which cluster, which
                # role, which questions to answer — so it is the one field the
                # planner must fill and the one a person may not leave blank.
                dict(key="keyword", label="Target keyword", required=True),
                # Derived by the planner from the map, editable by the owner.
                # A pillar and a support are different articles for the same
                # phrase, and getting it wrong is not a style difference: a
                # support that thinks it is a pillar links nowhere.
                dict(key="role", label="Pillar or support", required=False,
                     kind="choice", choices=("pillar", "support")),
                dict(key="cluster", label="Cluster", required=False),
                # OPTIONAL, and blank on purpose. No source holds an angle, so
                # the planner proposes none; the drafter picks one and the run
                # records which, so the owner can read it back and correct it.
                dict(key="angle", label="Angle (optional)", required=False),
                dict(key="entity_key", label="Featured entity", required=False,
                     kind="entity"),
            ),
            artifact="cms_article",
            ship="publishes the draft article, behind seo_guard",
            measure="draft-vs-published delta; position change in "
                    "`keywords.progress`, against a control")),
    "reorder_engine": dict(
        name="Reorder engine",
        does="Triggers replenishment prompts off purchase cadence.",
        requires=("commerce", "esp"), requires_any=(), needs_kb=False,
        kb_needs=("entity",),
        workflow=dict(
            unit="one replenishment prompt per cohort",
            artifact="esp_campaign",
            ship="marks it launch-ready — launching stays human",
            measure="provider stats, once `reports` exists")),
    "service_desk": dict(
        name="Service desk",
        does="Handles routine inbound support with a drafted, checked reply.",
        requires=("inbox",), requires_any=(), needs_kb=True,
        kb_needs=("tone", "banned_claims", "objection", "entity"),
        workflow=dict(
            unit="one thread's reply",
            artifact="gmail_draft",
            ship="approving sends the draft itself",
            measure="edits.py delta; sent-as-is rate")),
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
        kb_needs=("tone", "banned_claims", "audience", "claim", "entity"),
        workflow=dict(
            unit="one ad batch for one audience × entity",
            skill="ad_copy",
            plan_fields=(
                dict(key="entity_key", label="Entity", required=True),
                dict(key="audience_key", label="Audience", required=True),
                dict(key="variants", label="Variants (1–5)", required=False),
            ),
            artifact="proposal_rows",
            ship="marks the batch ready — no ad-platform write is wired, and "
                 "the surface says so",
            measure="asset outcomes per channel (fed by hand until the "
                    "output→ad-id join exists)")),
    "reports": dict(
        name="Reports",
        does="The weekly number, assembled from whatever is connected.",
        requires=(), requires_any=("analytics", "ads", "commerce"), needs_kb=False,
        kb_needs=(),
        workflow=dict(
            unit="the weekly number, one report",
            artifact="report_document",
            ship="sends it to the client, on approval",
            measure="none — the report IS the measurement")),
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
    # A plan is QUEUE, not activity: it has run nothing, decided nothing and
    # earned nothing. Counting planned rows here would let a system that
    # plans a lot and ships nothing inflate its own run total — and `runs`
    # feeds `can_promote`'s clean-tail check, where a planned row would
    # dilute the tail with rows no denial could ever appear on.
    rows = [r for r in runs(system_id, limit=0) if r.stage != PLANNED]
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
    # Planned rows are excluded BEFORE the window is cut, not after: a queue
    # of plans at the head of the ledger would otherwise push real denials
    # out of the tail and promote a system on rows nothing could deny.
    recent = [r for r in runs(system.id, limit=0) if r.stage != PLANNED]
    tail = [r for r in recent[:gate["clean_tail"]] if r.decision == "denied"]
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


def record_defects(run_id: str, rules: list) -> int:
    """File what was wrong with an output that still shipped. Returns how many.

    A campaign whose button pointed nowhere used to be withheld entirely, and
    the reason lived only in the run's notes — read once, by whoever happened
    to be looking. Now the draft goes to the ESP marked, and the REASON comes
    here, where `blocked_reasons` ranks it: one email needing a fix is noise,
    the same account shipping six sends with a dead button because nobody put
    a domain on file is a thing to go and fix at the source.
    """
    rules = [str(r) for r in (rules or []) if r]
    if not run_id or not rules:
        return 0
    with db.SessionLocal() as s:
        row = s.get(db.SystemRun, run_id)
        if row is None:
            return 0
        row.blocked_on = list(dict.fromkeys(list(row.blocked_on or []) + rules))
        s.commit()
        return len(rules)


#: What KIND of thing a refusal is, which decides who fixes it and where.
#: Ordered — the first pattern that matches wins — and deliberately small: a
#: taxonomy nobody can hold in their head gets ignored, and every unmatched
#: reason falls through to "other" rather than being forced into a bucket that
#: would send somebody to the wrong page.
#:
#: `where` is the console tab that can actually fix it. That is the whole point
#: of classifying at all — a list of things that went wrong is only useful if
#: each line knows where its fix lives (owner, 2026-08-23: the console should
#: let you act where it tells you something is wrong).
ATTENTION_KINDS = (
    ("connection", "Connection", "accounts",
     ("is not connected", "no credentials", "connect ", "not connected",
      # ready()'s OTHER connection sentence — "needs at least one of: …" —
      # matched no needle and fell to Diagnostics, where nothing connects.
      "needs at least one of", "no ESP", "token")),
    ("install", "Not installed or switched off", "systems",
     ("is not installed", "is designed", "is paused", "is retired",
      "the contract is optional", "turn it on")),
    ("knowledge", "Missing knowledge", "kb",
     ("nothing on file at", "cannot say anything true without",
      "no approved", "author one")),
    # SPLIT from "knowledge" 2026-08-26: the ban list is authored on the
    # BRAND tab ("Add hard rule"), and routing no_ban_list to Knowledge sent
    # the reader to a tab that cannot clear it.
    ("banlist", "Missing ban list", "brand",
     ("no_ban_list", "banned_claims")),
    ("compliance", "Compliance", "assurance",
     ("banned_claim", "unfit_entity_named", "unbacked_urgency")),
    ("quality", "Quality", "diagnostics",
     ("coherence:", "dead_link", "proof_repeated", "personalize_failed",
      "theme_incomplete")),
)


def classify_reason(reason: str) -> dict:
    """One refusal string → {kind, label, where}. Never raises, never guesses."""
    text = str(reason or "").lower()
    for kind, label, where, needles in ATTENTION_KINDS:
        if any(n.lower() in text for n in needles):
            return {"kind": kind, "label": label, "where": where}
    return {"kind": "other", "label": "Other", "where": "diagnostics"}


def attention(tenant: str = "", days: int = 30, system_key: str = "",
              examples: int = 3) -> list[dict]:
    """What needs attention, ranked, WITH THE RUNS THAT PROVE IT.

    `blocked_reasons` answers "what, and how often" and throws away everything
    else — no run id, no system, no timestamp, no body. The content was on the
    row the whole time and was never joined, so the console could rank the
    backlog and never show you one example of anything on it (owner,
    2026-08-23). This is that join.

    Differences from `blocked_reasons`, all deliberate:

    * `coherence:` rules are INCLUDED here and excluded there. That is not an
      inconsistency — the other list is the authoring backlog, and no amount
      of authoring fixes an incoherent email. This list is "what needs a
      person", and a quality failure needs one. It is labelled by kind so the
      two never get confused again.
    * Every entry carries the SYSTEMS it happened to, resolved through
      `System.key` rather than left as a bare `system_id`.
    * Every entry carries example runs with their own content — when, stage,
      the source ref, the error in the platform's words, and the head of
      whatever the run produced.
    """
    since = db.utcnow() - dt.timedelta(days=max(1, int(days or 1)))
    with db.SessionLocal() as s:
        q = (s.query(db.SystemRun)
             .filter(db.SystemRun.blocked_on.isnot(None),
                     db.SystemRun.created_at >= since))
        if tenant:
            q = q.filter(db.SystemRun.tenant == tenant)
        runs = q.order_by(db.SystemRun.created_at.desc()).all()
        # One extra query, not one per run: a per-row lookup here is the
        # classic N+1 on the page that is supposed to diagnose slowness.
        names = {r.id: r.key for r in s.query(db.System).all()}

    buckets: dict[str, dict] = {}
    for r in runs:
        skey = names.get(r.system_id or "", "") or "(unknown system)"
        if system_key and skey != system_key:
            continue
        for reason in (r.blocked_on or []):
            reason = str(reason)
            b = buckets.setdefault(reason, {
                "reason": reason, "count": 0, "systems": {},
                "tenants": set(), "first_at": r.created_at,
                "last_at": r.created_at, "examples": [],
                **classify_reason(reason)})
            b["count"] += 1
            b["systems"][skey] = b["systems"].get(skey, 0) + 1
            b["tenants"].add(r.tenant)
            if r.created_at and b["first_at"] and r.created_at < b["first_at"]:
                b["first_at"] = r.created_at
            if r.created_at and b["last_at"] and r.created_at > b["last_at"]:
                b["last_at"] = r.created_at
            if len(b["examples"]) < max(1, int(examples)):
                # THE CONTENT. Everything a person needs to judge the item
                # without opening a database — which is what "surface the
                # items and their content" means.
                b["examples"].append({
                    "run_id": r.id, "system": skey, "tenant": r.tenant,
                    "at": r.created_at, "stage": r.stage or "",
                    "ref": r.ref or "", "trigger": r.trigger or "",
                    "error": (r.error or "")[:400],
                    "output": (r.output or "")[:400],
                    "blocked_on": list(r.blocked_on or []),
                })

    out = list(buckets.values())
    for b in out:
        b["tenants"] = sorted(b["tenants"])
    # Frequency first, then most recent — a thing that happened nine times
    # last month outranks one that happened twice yesterday, but between
    # equals the live one comes first.
    out.sort(key=lambda b: (-b["count"], -(b["last_at"].timestamp()
                                           if b["last_at"] else 0)))
    return out


def per_system(tenant: str = "", days: int = 30) -> list[dict]:
    """One row per installed system: what it did in the window, and what bit.

    Reads the runs once and groups in Python rather than issuing a query per
    system — this page exists to diagnose slowness and must not be a source of
    it.
    """
    since = db.utcnow() - dt.timedelta(days=max(1, int(days or 1)))
    with db.SessionLocal() as s:
        sysq = s.query(db.System)
        if tenant:
            sysq = sysq.filter(db.System.tenant == tenant)
        rows = sysq.all()
        ids = {r.id: r for r in rows}
        runq = (s.query(db.SystemRun)
                .filter(db.SystemRun.created_at >= since))
        if tenant:
            runq = runq.filter(db.SystemRun.tenant == tenant)
        runs = runq.all()

    by_sys: dict[str, list] = {}
    for r in runs:
        by_sys.setdefault(r.system_id or "", []).append(r)

    SHIPPED = {"sent", "approved", "published"}
    out = []
    for sid, row in ids.items():
        mine = by_sys.get(sid, [])
        blocked = [r for r in mine if (r.stage or "") in ("blocked", "failed")]
        defective = [r for r in mine
                     if (r.blocked_on or []) and (r.stage or "") not in ("blocked", "failed")]
        last = max((r.created_at for r in mine if r.created_at), default=None)
        out.append({
            "key": row.key, "name": row.name, "system_id": sid,
            "tenant": row.tenant, "status": row.status or "",
            "autonomy": row.autonomy or "",
            "runs": len(mine),
            "shipped": len([r for r in mine if (r.stage or "") in SHIPPED]),
            "planned": len([r for r in mine if (r.stage or "") == "planned"]),
            "blocked": len(blocked),
            "defective": len(defective),
            "last_at": last,
            # The single most useful number on the row: of everything this
            # system attempted, how much needed a person. A system with a
            # hundred clean runs and a system with two are not comparable on
            # counts alone.
            "needs_person": len(blocked) + len(defective),
        })
    out.sort(key=lambda r: (-r["needs_person"], -r["runs"], r["key"]))
    return out


def blocked_reasons(tenant: str = "", days: int = 30) -> list[tuple[str, int]]:
    """What cost the pipelines an output or shipped a defective one, most
    frequent first — the backlog, ordered by how often each gap actually bit.

    Reads runs that were BLOCKED and runs that shipped with defects recorded,
    because after 2026-08-22 a campaign with a dead button is drafted rather
    than withheld — and if only blocked runs were counted, fixing the symptom
    (ship it anyway) would have silently emptied the list that says to fix the
    cause.
    """
    since = db.utcnow() - dt.timedelta(days=days)
    with db.SessionLocal() as s:
        q = s.query(db.SystemRun).filter(
            db.SystemRun.blocked_on.isnot(None),
            db.SystemRun.created_at >= since)
        if tenant:
            q = q.filter(db.SystemRun.tenant == tenant)
        rows = q.all()
    counts: dict[str, int] = {}
    for r in rows:
        for reason in (r.blocked_on or []):
            # `coherence:` rules are deliberately NOT the knowledge backlog.
            # This list ranks what to go and AUTHOR — a missing claim, an
            # unwritten objection. An artifact blocked because its hero was a
            # photograph of something else is a quality failure no amount of
            # authoring would have prevented, and counting it here would send
            # somebody to write rows that could not have helped.
            if str(reason).startswith("coherence:"):
                continue
            counts[reason] = counts.get(reason, 0) + 1
    return sorted(counts.items(), key=lambda kv: -kv[1])


# ---------------------------------------------------------------------------
# Plans — work declared in advance of execution
#
# The owner's requirement (2026-08-21): each system tracks its work through
# its own workflow, and a system executes only from a COMPLETE brief it was
# shown in advance. A plan is a `SystemRun` opened at stage `planned`, its
# fields in the `brief` JSON column, its stable item key in `ref` — no new
# table. When the item comes due the SAME row becomes the execution row
# (`take_plan` flips it to `brief` and `skill.run` advances it), so one row is
# one item and the attempt history stays where it always was.
#
# Two mechanisms, both structural rather than remembered:
#
# * SAVING — `save_plan` is the only writer of plan fields after proposal.
#   It validates every key against the system's declared `plan_fields`
#   (an unknown key is refused BY NAME, the `esp.personalize` pattern),
#   treats a blank form input as not-an-edit (the `brand_theme.approve`
#   rule), and records every accepted key in `brief["edited"]` — which is
#   what lets a planner re-propose around the owner's edits without ever
#   writing over them. A resave is a re-attestation.
#
# * COMPLETENESS — `plan_complete` names what a plan is still missing
#   (required fields + a date), and `take_plan`/`consumable` refuse an
#   incomplete plan BY NAME. The row STAYS `planned`: an under-specified
#   instruction is never executed and never fails — it waits, visibly.
#   This is deliberately NOT the knowledge gate: thin knowledge still
#   produces (enrich, don't gatekeep); an incomplete INSTRUCTION never
#   runs. The gaps are owner work on the Planned surface, not client
#   knowledge, so they are never filed through `record_unknowns`.
#
# The rung rule: consuming a plan on `shadow` or `approve_all` requires an
# explicit `approve_plan` first, because EXECUTION itself has side effects —
# `campaign_email` drafts into the live ESP whenever the copy validates, on
# any rung, and a run spends model budget. `approve_exceptions` and `auto`
# consume due plans without the extra tap. And no rung, ever, launches:
# `send_campaign(confirm=True)` stays uncalled by the substrate.
# ---------------------------------------------------------------------------

PLANNED = "planned"


def workflow(key: str) -> dict:
    """The system's workflow declaration, with every field present."""
    wf = dict(spec(key).get("workflow") or {})
    wf.setdefault("unit", "")
    wf.setdefault("skill", "")
    wf.setdefault("plan_fields", ())
    wf.setdefault("artifact", "")
    wf.setdefault("ship", "")
    wf.setdefault("measure", "")
    wf.setdefault("cadence", {})
    return wf


def set_cadence(system_id: str, horizon_days=None,
                per_segment_monthly=None, segment_rest_days=None) -> dict:
    """The owner's cadence override, onto `System.config["cadence"]`.

    Validated here rather than trusted at read time, because a bad value
    written silently sits behind a planner for weeks: a 900-day horizon or a
    50-a-month cap is refused BY NAME at the knob. Blank means "leave it" —
    the same blank-is-not-an-edit rule the plan form keeps.

    Three knobs, one planner. `horizon_days` and `per_segment_monthly` pace
    the calendar path; `segment_rest_days` is the floor under the pressure
    path, so a cohort with a bad week cannot be written to twice in three
    days.

    There is no per-PERSON knob, and its absence is deliberate rather than
    missing: every send goes to a segment whose membership the ESP knows and
    we do not, so a per-person number would be a claim rather than a rule.
    Offering the box would be worse than not having it.
    """
    from . import planner as _pl
    updates: dict[str, int] = {}
    for name, val, cap in (("horizon_days", horizon_days,
                            _pl.MAX_HORIZON_DAYS),
                           ("per_segment_monthly", per_segment_monthly,
                            _pl.MAX_PER_SEGMENT_MONTHLY),
                           ("segment_rest_days", segment_rest_days,
                            _pl.MAX_SEGMENT_REST_DAYS)):
        if val is None or str(val).strip() == "":
            continue
        try:
            n = int(str(val).strip())
        except (TypeError, ValueError):
            return {"error": f"{name} must be a whole number, got {val!r}"}
        if not 0 < n <= cap:
            return {"error": f"{name} must be between 1 and {cap}, got {n}"}
        updates[name] = n
    if not updates:
        return {"error": "nothing to set — every box was blank"}
    with db.SessionLocal() as s:
        row = s.get(db.System, system_id)
        if not row:
            return {"error": "unknown system"}
        cfg = dict(row.config or {})
        cad = dict(cfg.get("cadence") or {})
        cad.update(updates)
        cfg["cadence"] = cad
        row.config = cfg
        s.commit()
    return {"ok": True, **updates}


#: The growth goal, per system. Every field optional individually; at least one
#: required, because a goal with nothing in it is not a goal.
#:
#: There is NO DEFAULT and there will not be one. A target nobody chose is a
#: bar nobody can fail, and inventing "+20%" so a report has a number is the
#: exact shape of the false assurance `validator` and `seo_guard` refuse to
#: give. `keywords.progress` reports everything that does not depend on a goal
#: and NAMES this as missing — the system's own rule about refusing rather than
#: inventing, applied to the one input no amount of connected data supplies.
GOAL_FIELDS = {
    "organic_clicks": ("monthly organic clicks from tracked pages", 1_000_000),
    "top3": ("tracked keywords ranking 1-3", 10_000),
    "top10": ("tracked keywords ranking 1-10", 10_000),
    "horizon_days": ("days the goal runs for", 730),
}


def set_goal(system_id: str, **fields) -> dict:
    """The owner's growth goal, onto `System.config["goal"]`.

    Validated at the knob for the same reason `set_cadence` is: a bad value
    written silently sits behind a report for weeks. Blank means "leave it".
    """
    updates: dict[str, int] = {}
    for name, val in fields.items():
        if name not in GOAL_FIELDS:
            return {"error": f"unknown goal field {name!r}. "
                             f"Known: {', '.join(sorted(GOAL_FIELDS))}"}
        if val is None or str(val).strip() == "":
            continue
        try:
            n = int(str(val).strip())
        except (TypeError, ValueError):
            return {"error": f"{name} must be a whole number, got {val!r}"}
        cap = GOAL_FIELDS[name][1]
        if not 0 < n <= cap:
            return {"error": f"{name} must be between 1 and {cap}, got {n}"}
        updates[name] = n
    if not updates:
        return {"error": "nothing to set — every box was blank"}
    with db.SessionLocal() as s:
        row = s.get(db.System, system_id)
        if not row:
            return {"error": "unknown system"}
        cfg = dict(row.config or {})
        goal = dict(cfg.get("goal") or {})
        goal.update(updates)
        # Stamped so a goal can be seen to have gone stale. A target set for a
        # quarter and still being reported against a year later is worse than
        # no target, because it reads as current.
        goal["set_at"] = db.utcnow().date().isoformat()
        cfg["goal"] = goal
        row.config = cfg
        s.commit()
    return {"ok": True, **updates}


def goal_for(sysrow) -> dict:
    """The declared goal, or {} — never a default."""
    return dict(((sysrow.config or {}) if sysrow else {}).get("goal") or {})


def plan_capable(key: str) -> bool:
    """Does this system take plans at all? Declared, never inferred."""
    return bool(workflow(key)["plan_fields"])


def _plan_keys(key: str) -> dict[str, dict]:
    return {f["key"]: f for f in workflow(key)["plan_fields"]}


def _valid_date(value: str) -> bool:
    try:
        dt.date.fromisoformat(value)
        return True
    except (TypeError, ValueError):
        return False


def _today() -> str:
    return dt.date.today().isoformat()


def plan_complete(row_or_brief, key: str) -> dict:
    """Is this plan a complete instruction? If not, exactly what is absent.

    `planned_for` is generically required — a plan with no date can never
    come due, which reads as "queued" while meaning "lost".
    """
    brief = (row_or_brief if isinstance(row_or_brief, dict)
             else (getattr(row_or_brief, "brief", None) or {}))
    plan = brief.get("plan") or {}
    missing = [f["label"] or f["key"] for f in workflow(key)["plan_fields"]
               if f.get("required") and not str(plan.get(f["key"], "") or "").strip()]
    if not _valid_date(str(brief.get("planned_for", "") or "")):
        missing.append("planned date")
    return {"complete": not missing, "missing": missing}


def _segment_key_check(tenant: str, value: str) -> str:
    """'' when the value is a real segment key; the named refusal otherwise.

    A plan's segment is a REFERENCE into the account's segment catalog,
    never free text (owner, 2026-08-21): a key matching nothing slides
    through to `_segment_brief`'s generic stand-in and the campaign composes
    against a cohort that does not exist — the same hole the ESP binding
    closed, one layer up. Enforced here so a hand-built URL is refused the
    same way the form's select is constrained.
    """
    from . import segments as segmod
    got = segmod.for_tenant(tenant)
    if not got.get("ok"):
        return got.get("error", "segments unavailable")
    keys = [s["key"] for s in got["segments"]]
    if value in keys:
        return ""
    return (f"unknown segment {value!r} — this account's segments are: "
            + ", ".join(keys))


def _entity_key_check(tenant: str, value: str) -> str:
    """'' when the value is a real catalogue entity; the named refusal
    otherwise — same rule as segments: a plan field that references the KB
    must point at a row that exists, or the campaign features a stand-in."""
    rows = kb.entities(tenant, available_only=False)
    keys = [r.key for r in rows]
    if value in keys:
        return ""
    sample = ", ".join(keys[:8]) + (", …" if len(keys) > 8 else "")
    return (f"unknown entity {value!r} — pick one from this account's "
            f"catalogue" + (f" ({sample})" if keys else
                            " (it is empty — run the catalogue sync first)"))


def _check_plan_refs(tenant: str, key: str, values: dict) -> str:
    """Reference-kind plan fields must point at something real. Blank stays
    allowed — completeness owns 'required'; this owns 'genuine'."""
    checks = {"segment": _segment_key_check, "entity": _entity_key_check}
    for f in workflow(key)["plan_fields"]:
        v = str(values.get(f["key"], "") or "").strip()
        if not v:
            continue
        # A `choice` field carries its own vocabulary, so it is checked here
        # rather than against a live catalogue. Same reason as the reference
        # kinds: a value the skill does not know reads downstream as unset,
        # which silently changes what gets produced instead of refusing.
        if f.get("kind") == "choice":
            allowed = tuple(f.get("choices") or ())
            if allowed and v.lower() not in allowed:
                return (f"{f.get('label', f['key'])}: {v!r} is not one of "
                        + ", ".join(allowed))
            continue
        fn = checks.get(f.get("kind", ""))
        if fn is None:
            continue
        why = fn(tenant, v)
        if why:
            return why
    return ""


def _open_plan_row(s, system_id: str, ref: str):
    return (s.query(db.SystemRun)
            .filter(db.SystemRun.system_id == system_id,
                    db.SystemRun.ref == ref,
                    db.SystemRun.stage == PLANNED)
            .first())


def open_plan(tenant: str, key: str, *, ref: str, plan: dict | None = None,
              planned_for: str = "", trigger: str = "planner") -> dict:
    """File (or refresh) one planned item. The planner's only entry point.

    Idempotent per `ref` among OPEN planned rows: re-proposing an item
    updates only the fields the owner has NOT edited — owner edits carry
    forward, the same rule as theme edits surviving re-derives. A planner
    proposes only what it can read from data; a field it cannot fill stays
    absent and `plan_complete` names it, because a planner that invents a
    value produces a plan nobody wrote.
    """
    if not ref.strip():
        return {"error": "a plan needs a stable item key (ref) — without one "
                         "the planner cannot avoid filing the same item twice"}
    row = find(tenant, key)
    if not row:
        return {"error": f"the {key} system is not installed for {tenant}"}
    if not is_on(row):
        # The switch is the dictator, at the queue as well as at the run: a
        # planner filling work for a system somebody turned off is the same
        # defect as the tick evaluating `designed` systems, one stage earlier.
        return {"error": f"the {key} system is {row.status or 'not live'} — "
                         f"plans are only filed for a system that is on"}
    if not plan_capable(key):
        return {"error": f"the {key} system declares no plan fields — it does "
                         f"not take planned work"}
    fields = _plan_keys(key)
    bad = sorted(set(plan or {}) - set(fields))
    if bad:
        return {"error": f"unknown plan field(s): {', '.join(bad)} — this "
                         f"system's plan takes {', '.join(sorted(fields))}"}
    if planned_for and not _valid_date(planned_for):
        return {"error": f"planned_for must be an ISO date, got {planned_for!r}"}
    bad_ref = _check_plan_refs(tenant, key, plan or {})
    if bad_ref:
        return {"error": bad_ref}

    with db.SessionLocal() as s:
        existing = _open_plan_row(s, row.id, ref)
        if existing is not None:
            brief = dict(existing.brief or {})
            kept = dict(brief.get("plan") or {})
            edited = set(brief.get("edited") or [])
            preserved, refreshed = [], []
            for fk, fv in (plan or {}).items():
                if fk in edited:
                    preserved.append(fk)
                    continue
                kept[fk] = fv
                refreshed.append(fk)
            brief["plan"] = kept
            if planned_for and "planned_for" not in edited:
                brief["planned_for"] = planned_for
            elif planned_for:
                preserved.append("planned_for")
            existing.brief = brief
            s.commit()
            comp = plan_complete(brief, key)
            return {"ok": True, "run_id": existing.id, "updated": True,
                    "refreshed": sorted(refreshed),
                    "preserved": sorted(preserved), **comp}
        # NO DATE MEANS TODAY. A plan filed without one used to sit for ever:
        # `plan_complete` requires a date and the tick only consumes what is
        # due, so a dateless plan was permanently incomplete and permanently
        # invisible to both. Somebody filing an item by hand means "this one,
        # now" — the planner still sets its own spaced dates deliberately, and
        # this only fills a blank (owner, 2026-08-22).
        run = db.SystemRun(
            system_id=row.id, tenant=tenant, trigger=trigger, ref=ref,
            stage=PLANNED,
            brief={"plan": dict(plan or {}), "edited": [],
                   "planned_for": planned_for or _today()})
        s.add(run)
        s.commit()
        comp = plan_complete(run.brief, key)
        return {"ok": True, "run_id": run.id, "created": True, **comp}


def save_plan(run_id: str, edits: dict | None = None, *,
              planned_for: str = "") -> dict:
    """The owner's changes to one plan — the ONLY writer after proposal.

    Blank inputs are not edits (the form posts every field; absence of typing
    must not clear a value). Every accepted key joins `brief["edited"]`, so
    later re-proposals cannot write over a hand-set value. Editing a paused
    system's plan is allowed — fixing plans while stopped is legitimate work;
    CONSUMING one is not, and `consumable` refuses it.
    """
    with db.SessionLocal() as s:
        row = s.get(db.SystemRun, run_id)
        if not row:
            return {"error": "unknown plan"}
        if row.stage != PLANNED:
            return {"error": f"this plan was already consumed (stage "
                             f"{row.stage!r}) — changes now belong on the "
                             f"next item, not on the record of this one"}
        sysrow = s.get(db.System, row.system_id)
        key = sysrow.key if sysrow else ""
        fields = _plan_keys(key)
        cleaned = {k: v for k, v in (edits or {}).items()
                   if str(v or "").strip()}
        bad = sorted(set(cleaned) - set(fields))
        if bad:
            return {"error": f"unknown plan field(s): {', '.join(bad)} — this "
                             f"system's plan takes {', '.join(sorted(fields))}"}
        if planned_for and not _valid_date(planned_for):
            return {"error": f"planned_for must be an ISO date, got {planned_for!r}"}
        bad_ref = _check_plan_refs(row.tenant, key, cleaned)
        if bad_ref:
            return {"error": bad_ref}
        brief = dict(row.brief or {})
        plan = dict(brief.get("plan") or {})
        edited = set(brief.get("edited") or [])
        for k, v in cleaned.items():
            plan[k] = v
            edited.add(k)
        if planned_for:
            brief["planned_for"] = planned_for
            edited.add("planned_for")
        brief["plan"] = plan
        brief["edited"] = sorted(edited)
        row.brief = brief
        s.commit()
        comp = plan_complete(brief, key)
        return {"ok": True, "run_id": run_id, "edited": sorted(edited), **comp}


def approve_plan(run_id: str) -> dict:
    """The owner's explicit go-ahead for one plan — what `shadow` and
    `approve_all` require before a plan may be consumed. Refused while the
    plan is incomplete: approving an under-specified instruction would just
    move the refusal one step later and make it look like consent."""
    with db.SessionLocal() as s:
        row = s.get(db.SystemRun, run_id)
        if not row:
            return {"error": "unknown plan"}
        if row.stage != PLANNED:
            return {"error": f"not a plan any more (stage {row.stage!r})"}
        sysrow = s.get(db.System, row.system_id)
        comp = plan_complete(row.brief or {}, sysrow.key if sysrow else "")
        if comp["missing"]:
            return {"error": "this plan is not complete — still missing: "
                             + ", ".join(comp["missing"])}
        brief = dict(row.brief or {})
        brief["plan_approved_at"] = db.utcnow().isoformat()
        row.brief = brief
        s.commit()
        return {"ok": True, "run_id": run_id}


def skip_plan(run_id: str, reason: str = "") -> dict:
    """Decline one plan. A decision, recorded — never a silent delete."""
    row = None
    with db.SessionLocal() as s:
        row = s.get(db.SystemRun, run_id)
        if not row:
            return {"error": "unknown plan"}
        if row.stage != PLANNED:
            return {"error": f"not a plan any more (stage {row.stage!r})"}
        brief = dict(row.brief or {})
        if reason:
            brief["skip_reason"] = reason[:300]
        row.brief = brief
        s.commit()
    finish_run(run_id, "skipped", decision="denied",
               output="plan skipped before execution")
    return {"ok": True, "run_id": run_id}


def plans(tenant: str, key: str = "", due_by: str = "") -> list[db.SystemRun]:
    """Open planned rows for one account, soonest first.

    `due_by` (ISO date) narrows to plans whose date has arrived — dateless
    plans are NEVER due (they are incomplete, and `plan_complete` is already
    naming that; consuming one would execute an instruction with no when).
    """
    with db.SessionLocal() as s:
        q = (s.query(db.SystemRun)
             .filter(db.SystemRun.tenant == tenant,
                     db.SystemRun.stage == PLANNED))
        if key:
            ids = [r.id for r in s.query(db.System)
                   .filter(db.System.tenant == tenant, db.System.key == key)]
            q = q.filter(db.SystemRun.system_id.in_(ids or [""]))
        rows = q.all()
        s.expunge_all()
    def _when(r):
        return (r.brief or {}).get("planned_for") or "9999-12-31"
    rows.sort(key=lambda r: (_when(r), db.as_utc(r.created_at)))
    if due_by:
        rows = [r for r in rows
                if ((r.brief or {}).get("planned_for") or "") and _when(r) <= due_by]
    return rows


def plan_page(tenant: str, system_key: str, plan_id: str,
              per: int = 15) -> int:
    """Which page of the workflow board a plan renders on.

    The board paginates and every deep link (#plan-<id>) carried no page, so
    a plan past the first fifteen had an anchor pointing at nothing — the
    flash said "filed" over a board that did not show it. Computed from the
    SAME `plans()` ordering the board slices, so the two cannot drift.
    """
    rows = plans(tenant, system_key)
    for i, r in enumerate(rows):
        if r.id == plan_id:
            return i // per + 1
    return 1


def plans_needing_action(tenant: str) -> list[dict]:
    """Open plans waiting on a PERSON, across this account's systems.

    Two kinds, each named so the card can say what to do rather than that
    something is wrong: `complete` (fields are missing — the plan cannot run
    until they are filled) and `approve` (the plan is complete, and the
    system's rung requires the owner's explicit tap before execution).
    A complete plan on `approve_exceptions`/`auto` is NOT here — it needs
    nobody; it runs when due. Feeds the Review badge and the Review tab's
    plans card, so "is there work" costs zero clicks.
    """
    out: list[dict] = []
    by_id = {r.id: r for r in for_tenant(tenant)}
    for row in plans(tenant):
        sysrow = by_id.get(row.system_id)
        if sysrow is None:
            continue
        comp = plan_complete(row, sysrow.key)
        brief = row.brief or {}
        if not comp["complete"]:
            need, detail = "complete", ", ".join(comp["missing"])
        elif ((sysrow.autonomy or "shadow") in ("shadow", "approve_all")
                and not brief.get("plan_approved_at")):
            need, detail = "approve", "complete — awaiting your go-ahead"
        else:
            continue
        out.append({"run_id": row.id, "system_key": sysrow.key,
                    "system_name": sysrow.name or sysrow.key,
                    "ref": row.ref or "", "planned_for":
                        str(brief.get("planned_for") or ""),
                    "need": need, "detail": detail})
    return out


def consumable(row, sysrow) -> dict:
    """May this plan be executed now? One place decides, for every caller.

    Three gates, each named: the switch (only a live system runs), the
    completeness bar (an incomplete instruction waits, visibly), and the
    rung (shadow/approve_all put a person before EXECUTION — the run itself
    drafts into live platforms and spends model budget).
    """
    if not is_on(sysrow):
        return {"ok": False,
                "why": f"the {sysrow.key} system is {sysrow.status or 'off'} "
                       f"— a plan is only consumed by a system that is on"}
    comp = plan_complete(row, sysrow.key)
    if not comp["complete"]:
        return {"ok": False,
                "why": "this plan is not a complete instruction yet — "
                       "still missing: " + ", ".join(comp["missing"])}
    rung = sysrow.autonomy or "shadow"
    if rung in ("shadow", "approve_all") \
            and not (row.brief or {}).get("plan_approved_at"):
        return {"ok": False,
                "why": f"on the {rung} rung a plan needs your explicit "
                       f"approval before it runs — approve it on the "
                       f"Planned list"}
    return {"ok": True, "why": ""}


def take_plan(run_id: str, tenant: str, *, system_id: str,
              skill_params: tuple, caller_params: tuple = ()) -> dict:
    """Consume one plan: validate everything, flip it to the execution row.

    Called by `skill.run` when it is handed a `run_id` — the gate lives HERE
    so it is structural for every caller, not remembered by the tick. EVERY
    refusal happens before the flip, so on any of them the row stays
    `planned`, untouched; nothing extra is filed, because a daily blocked
    row per stuck plan is the exact noise the tick was cured of. Returns
    the plan's non-blank fields as the run's parameters.
    """
    with db.SessionLocal() as s:
        row = s.get(db.SystemRun, run_id)
        if not row:
            return {"ok": False, "why": f"no plan keyed {run_id!r}"}
        if row.stage != PLANNED:
            return {"ok": False,
                    "why": f"run {run_id} is not a plan (stage {row.stage!r})"}
        if row.tenant != tenant or row.system_id != system_id:
            # A mismatch is a caller error worth its own words: consuming
            # another account's plan is the tenant boundary, not a typo.
            return {"ok": False,
                    "why": "this plan belongs to a different account or "
                           "system than the one asked to run it"}
        sysrow = s.get(db.System, row.system_id)
        verdict = consumable(row, sysrow)
        if not verdict["ok"]:
            return {"ok": False, "why": verdict["why"]}
        plan = dict((row.brief or {}).get("plan") or {})
        params = {k: v for k, v in plan.items() if str(v or "").strip()}
        undeclared = sorted(set(params) - set(skill_params))
        if undeclared:
            # The declaration drifted from the skill. Refusing here — by name,
            # before the generic unknown-parameter refusal — keeps a drifted
            # plan waiting visibly instead of half-running.
            return {"ok": False,
                    "why": ("this plan carries field(s) the skill does not "
                            "accept: " + ", ".join(undeclared)
                            + " — the workflow declaration and the skill "
                              "have drifted; fix the declaration")}
        collide = sorted(set(params) & set(caller_params))
        if collide:
            # The plan is the REVIEWED instruction. A caller silently
            # overriding a field the owner may have set would make the plan
            # lie about what ran — refused, before the flip.
            return {"ok": False,
                    "why": ("these parameter(s) are set by the plan and may "
                            "not be overridden at the call: "
                            + ", ".join(collide))}
        row.stage = "brief"
        s.commit()
        return {"ok": True, "why": "", "params": params}


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
