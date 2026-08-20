"""The nightly sweep: joining the ledgers nobody joins, and saying what it sees.

The owner's question was *"how are we making sure that we are finding
correlations and getting all the context I have all the time"*, and the honest
answer was that context is PULLED when a task asks for it and nothing watches.
The July finding that mattered most — ad spend holding while the zodiac ranges
went out of stock — was found by hand, and every input it needed was already in
these tables.

**The correlation is deterministic. The model only makes it read well.**

That is the whole cost design, and it is also the codebase's own rule (AI at
the edges, deterministic code between). Every number below is computed in
Python from rows we already wrote; the model is handed those numbers and asked
for a sentence. So the sweep costs a few hundred output tokens a night on the
cheapest model, and — this is the part that matters — **if the model is absent
or fails, the finding still stands**, in plainer words. A sweep that goes
silent when an API key expires is worse than one that reads awkwardly.

**Findings, never conclusions.** Each carries its evidence and the numbers it
was computed from, so a person can disagree with it. None of them acts.

**Computed, never stored.** Same reasoning as `scope_conflicts` and the
duplicate sweep: a finding that has been dealt with stops appearing on its own,
and one that recurs is still true. A `findings` table would need somebody to
mark rows resolved, and a queue of stale findings is one that stops being read.
"""
from __future__ import annotations

import datetime as dt

from . import db

#: A provider failing this often is a broken connection rather than the
#: internet. Below it, occasional failure is normal and reporting it nightly
#: would teach somebody to ignore the sweep.
FAILING_RATE = 0.34

#: A draft waiting longer than this is a queue nobody is working, which is a
#: different problem from a system that is not producing.
STALE_DRAFT_DAYS = 3

#: Below this, a "pattern" is a coincidence. Three of anything is the smallest
#: number that can show a trend without inviting one to be read into noise.
MIN_PATTERN = 3


def _since(days: int) -> dt.datetime:
    return db.utcnow() - dt.timedelta(days=max(1, days))


def sweep(tenant: str, days: int = 7) -> list[dict]:
    """Everything worth a person's attention for one account, computed.

    Ordered by what it costs, not by how interesting it is: a dead connection
    outranks a knowledge gap, which outranks a queue nobody has worked.
    """
    out: list[dict] = []
    for fn in (_dead_connection, _knowledge_gap_cost, _rule_keeps_firing,
               _queue_not_worked, _spend_without_output, _grounding_not_landing):
        try:
            out.extend(fn(tenant, days) or [])
        except Exception as exc:                                 # noqa: BLE001
            # A finding that cannot be computed is reported as such rather than
            # dropped: a sweep that silently skips half its checks reads as a
            # clean night.
            out.append({
                "kind": "sweep_error", "weight": 0, "account": tenant,
                "headline": f"one check could not run ({fn.__name__})",
                "evidence": [f"{exc.__class__.__name__}: {str(exc)[:120]}"],
                "suggests": "this is our bug, not the account's"})
    out.sort(key=lambda f: -f["weight"])
    return out


# ---------------------------------------------------------------------------
# The checks. Each returns findings or nothing, and each states its evidence.
# ---------------------------------------------------------------------------

def _dead_connection(tenant: str, days: int) -> list[dict]:
    """A platform that is mostly failing. Costs everything downstream of it."""
    from . import toolcalls
    rep = toolcalls.report(tenant, days)
    out = []
    for p in rep.get("failing", []):
        if p["failure_rate"] < FAILING_RATE or p["calls"] < MIN_PATTERN:
            continue
        out.append({
            "kind": "dead_connection", "weight": 100, "account": tenant,
            "headline": f"{p['provider']} failed {p['failed']} of "
                        f"{p['calls']} calls",
            "evidence": [f"failure rate {p['failure_rate']:.0%} over {days} days",
                         f"last error: {p['last_error'][:140]}"],
            "suggests": "reconnect it on the Connections tab — everything that "
                        "reads this platform is producing thinner work until "
                        "it is fixed"})
    return out


def _knowledge_gap_cost(tenant: str, days: int) -> list[dict]:
    """What the pipelines refused on, ranked by how much output it cost.

    `systems.blocked_reasons` already ranks this; the finding is the JOIN it
    was missing — a gap is worth reporting when it cost real output, not when
    it merely occurred once.
    """
    from . import systems
    # `blocked_reasons` reads stage == "blocked" only, so escalations and
    # not-yet-built generators no longer reach here — see `db.SystemRun.stage`.
    # Before that fix this finding was dominated by "no generator yet", which
    # no amount of writing into the knowledge base could ever satisfy.
    rows = systems.blocked_reasons(tenant, days)
    out = []
    for reason, n in rows[:3]:
        if n < MIN_PATTERN:
            continue
        out.append({
            "kind": "knowledge_gap", "weight": 70 + n, "account": tenant,
            "headline": f"{n} runs refused on the same missing thing",
            "evidence": [f"blocked on: {reason}",
                         f"{n} times in {days} days"],
            "suggests": "answer this one on the Knowledge tab and those runs "
                        "start producing — it is the highest-value thing to "
                        "write this week"})
    return out


def _rule_keeps_firing(tenant: str, days: int) -> list[dict]:
    """A ban the model keeps writing into drafts.

    A catch is the layer working. The SAME catch, repeatedly, is a different
    finding: the guidance is not reaching the drafter, and a validator catching
    it every time is a cost being paid nightly rather than a problem solved.
    """
    from . import assurance
    rep = assurance.report(tenant, days)
    out = []
    for rule, n in (rep.get("caught") or {}).items():
        if n < MIN_PATTERN:
            continue
        out.append({
            "kind": "rule_keeps_firing", "weight": 60 + n, "account": tenant,
            "headline": f"the same rule caught {n} drafts",
            "evidence": [f"rule: {rule}", f"{n} catches in {days} days",
                         "each one was stopped — this is about cost, not risk"],
            "suggests": "the drafter keeps reaching for it, so the guidance is "
                        "not landing. Add it as standing guidance on the "
                        "system, where it shapes the draft instead of being "
                        "caught after"})
    return out


def _queue_not_worked(tenant: str, days: int) -> list[dict]:
    """Drafts waiting on a person. Not a fault, and easy to stop noticing."""
    cutoff = db.utcnow() - dt.timedelta(days=STALE_DRAFT_DAYS)
    with db.SessionLocal() as s:
        n = (s.query(db.Approval)
             .filter(db.Approval.tenant == tenant,
                     db.Approval.status == "pending",
                     db.Approval.created_at < cutoff).count())
    if n < MIN_PATTERN:
        return []
    return [{
        "kind": "queue_not_worked", "weight": 50 + n, "account": tenant,
        "headline": f"{n} approvals have waited more than "
                    f"{STALE_DRAFT_DAYS} days",
        "evidence": [f"{n} pending, oldest beyond {STALE_DRAFT_DAYS} days"],
        "suggests": "work them or turn the system down a rung — a queue "
                    "nobody clears is a system that is not running, and it "
                    "looks identical to one that is"}]


def _spend_without_output(tenant: str, days: int) -> list[dict]:
    """Model cost with nothing produced for it."""
    from . import usage
    rep = usage.report(days=days, tenant=tenant)
    cost = rep.get("est_cost_usd", 0) or 0
    if cost < 1:
        return []
    since = _since(days)
    with db.SessionLocal() as s:
        produced = (s.query(db.Output)
                    .filter(db.Output.tenant == tenant,
                            db.Output.created_at >= since,
                            db.Output.status.in_(["approved", "published"]))
                    .count())
    if produced:
        return []
    return [{
        "kind": "spend_without_output", "weight": 55, "account": tenant,
        "headline": f"${cost} of model spend produced nothing that shipped",
        "evidence": [f"${cost} over {days} days",
                     "0 outputs reached approved or published"],
        "suggests": "either the work is being blocked before it produces, or "
                    "it is producing and nobody is approving — the two "
                    "findings above say which"}]


def _grounding_not_landing(tenant: str, days: int) -> list[dict]:
    """Approved claims exist and the drafts are not citing them.

    The specific thing to watch after the grounding work: if the rate stays at
    zero while claims are on file, the prompt is being ignored rather than the
    knowledge being absent — and those are opposite fixes.
    """
    from . import assurance, kb
    if not kb.claims(tenant):
        return []          # nothing to cite; not a finding
    rep = assurance.report(tenant, days)
    g = rep.get("grounding") or {}
    measured, cited = g.get("measured") or 0, g.get("with_a_claim_id") or 0
    if measured < MIN_PATTERN or cited:
        return []
    return [{
        "kind": "grounding_not_landing", "weight": 65, "account": tenant,
        "headline": f"{measured} drafts, none cited an approved claim",
        "evidence": [f"{len(kb.claims(tenant))} approved claims are on file",
                     f"{measured} drafts measured, {cited} carried a claim_id"],
        "suggests": "the knowledge is reaching the prompt and not being used. "
                    "That is a prompt problem, not a knowledge one — check "
                    "what the bundle rendered before writing more claims"}]


# ---------------------------------------------------------------------------
# Words around the numbers. Cheap, optional, and never load-bearing.
# ---------------------------------------------------------------------------

def narrate(findings: list[dict]) -> str:
    """One short paragraph over a night's findings, on the cheap model.

    Deliberately the LAST step and deliberately optional. The findings are
    already complete sentences with their evidence attached; this only makes
    the digest read like something a person wrote. If it cannot run, the
    fallback is not silence — it is the same findings, plainer, and the digest
    says which it used.
    """
    from . import config
    if not findings:
        return ""
    if not config.ANTHROPIC_API_KEY:
        return ""
    try:
        import anthropic
        lines = "\n".join(
            f"- [{f['account']}] {f['headline']} — {'; '.join(f['evidence'])}"
            for f in findings[:12])
        msg = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY).messages.create(
            model=config.SWEEP_MODEL, max_tokens=220,
            system=("You summarise an ops sweep for the person who runs it. "
                    "Two or three sentences. Say what matters most and why, "
                    "in plain words. Invent NOTHING — every number you use "
                    "must appear below. If the findings do not agree with "
                    "each other, say so rather than smoothing it over."),
            messages=[{"role": "user", "content": lines}])
        from . import usage
        usage.log_usage("sweep", config.SWEEP_MODEL, msg)
        return next((b.text for b in msg.content if b.type == "text"), "").strip()
    except Exception:                                            # noqa: BLE001
        return ""          # the findings carry themselves


def nightly(days: int = 7) -> dict:
    """Every account, one digest. Scheduled — see `worker.start`.

    ONE message for the whole sweep, never one per finding. This codebase has
    had the other version: a path that notified per item put ~200 sends through
    in a minute and rate-limited the number.
    """
    from . import tenants
    all_findings: list[dict] = []
    for t in tenants.all_tenants():
        all_findings.extend(sweep(t.key, days))
    all_findings.sort(key=lambda f: -f["weight"])

    if not all_findings:
        # Not silence, and not "all clear" either — a week where nothing ran at
        # all produces exactly this, and the two mean opposite things.
        return {"findings": [], "delivered": False,
                "note": f"nothing stood out across {days} days. That is either "
                        f"a quiet week or a system that did not run; the "
                        f"Diagnostics tab says which."}

    summary = narrate(all_findings)
    body = (summary + "\n\n" if summary else "")
    body += "\n".join(
        f"[{f['account']}] {f['headline']}\n"
        f"    {'; '.join(f['evidence'])}\n"
        f"    → {f['suggests']}" for f in all_findings[:12])
    if not summary:
        body = ("(written without the summariser — the findings below are "
                "computed and complete)\n\n" + body)

    try:
        from . import approvals
        approvals.request_approval(
            "sweep", f"Nightly sweep — {len(all_findings)} finding(s)",
            {"body": body, "findings": all_findings[:12]}, notify=False)
    except Exception:                                            # noqa: BLE001
        pass
    return {"findings": all_findings, "delivered": True,
            "narrated": bool(summary), "body": body}
