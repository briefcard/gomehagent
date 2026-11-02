"""The substrate as an MCP server — the item ARCHITECTURE.md queued, built.

Owner, 2026-10-22: the app's email agent "is constantly writing bad drafts
that I have to re-write and it wastes money"; the data layer should be a
layer that scheduled automation calls, with Claude itself as the generator.
On 2026-10-02 one direct session had beaten the whole layered pipeline, and
what the pipeline lacked was never the model: it was the WHOLE package in
front of a capable model, a loop with tools, and a check before anything was
filed. This module is how a routine running outside the app gets those.

FIVE TOOLS. A tool is added only after a session needed it — get_plan and
get_results were needed on 2026-11-02, when a Claude Code session asked to
plan and analyse across the systems had a package to write from and nothing
that said what was due, what was stuck or what had worked:

    get_package   the brand package — every part `bundle.PARTS` declares, in
                  its order, with what is missing NAMED — as the markdown the
                  job file already hands a chat (`handoff.package_sections`,
                  one builder for both readers)
    check         every deterministic gate this codebase has, on one draft.
                  No model reads its own work here — `validator.py`'s rule.
    record        file a finished draft exactly where a skill run's lands: the
                  ledger, the artifact store, ONE pending `skill_output`
                  approval in the owner's queue. A draft with blocks is
                  recorded as blocked and queues nothing.
    get_plan      what is due, what waits on the owner, what is stuck and why,
                  per system — the Systems and Review tabs' own functions
    get_results   what worked — ad outcomes by the data layer's dimensions
                  (`results.by`) and what became of every draft: shipped,
                  blocked, approved, denied, and the gates that caught it
    inbox_search  the account's OWN inbox, searched (Gmail query syntax)
    inbox_thread  one thread of that inbox, every message, with attachments
    inbox_draft   a reply DRAFT in that thread — never sent. Owner, 2026-11-02:
                  answer Silvia, Chanel and Baci customer service from Claude
                  Code; the owner reads and sends from Gmail. It runs the
                  triage guard first (`validator.check`, ban list, fail closed).

THE INBOX IS THE ACCOUNT'S, NEVER THE CALLER'S. No inbox tool takes an alias:
`Tenant.gmail_alias` is resolved here, so a call about baci cannot read eien's
mail, and a thread id from another inbox is a 404 from Gmail itself. An
account without an inbox (coverings, ironside today) is refused by name.
`agency` resolves to the owner's personal inbox and is refused too — the
personal inbox is not client data and this server serves clients.

THE TRUST BOUNDARY HOLDS (ARCHITECTURE.md). Nothing here acts outward: no
send, push or publish. Approving in the console is the owner's act, through
the same door every system uses, and `record` never files an approval whose
payload carries an executor key (`EXECUTOR_KEYS`) — the suite asserts that
against `approvals.apply_decision`'s own list, not against this comment.

AUTH. One static bearer, `MCP_KEY`, read at request time, compared in
constant time. A SEPARATE credential from APPROVAL_SECRET because it will sit
in a Claude connector's settings, and a leaked connector key must not forge
an approval or open the console. Unset means every request is refused — the
fail-closed shape READ_KEY already has.

HOST CHECK OFF, DELIBERATELY. FastMCP >= 1.2x defaults `host` to 127.0.0.1
and then enables DNS-rebinding protection allowing only localhost Host
headers — so behind Render's domain every request was a 421 "Invalid Host
header" (found 2026-11-02; the suite's TestClient Host was refused the same
way). Rebinding is an attack on an UNAUTHENTICATED local server; this one is
public and every request needs the bearer, which a rebinding page cannot
supply. The suite now calls with the production Host header.

TRANSPORT. Streamable HTTP, stateless, JSON responses, one Route at `/mcp`.
A Route rather than a Mount because Starlette's Mount matches `/mcp/…` and
answers a bare `/mcp` with a redirect, which a POSTing client does not follow.
The session manager is created afresh on every startup: the SDK's `run()` is
once-per-instance, and a test client that opens the app twice is a restart.
"""
# NO `from __future__ import annotations` HERE, deliberately: FastMCP 1.12 reads
# each tool's parameter annotations as objects (`issubclass(param.annotation,
# Context)`) and the future import turns them into strings, which took the web
# app down at import on 2026-10-26 — ship gate 2 caught it. `list[str] | None`
# is a runtime object on every Python this SDK supports (>= 3.10).
import json
import logging
import secrets
from typing import Any

from mcp.server.fastmcp import FastMCP

try:                                   # absent in SDKs older than the host check
    from mcp.server.transport_security import TransportSecuritySettings
except ImportError:                    # pragma: no cover
    TransportSecuritySettings = None

from . import config

log = logging.getLogger("mcp_server")

NAME = "gomehagent"
#: The tools, by name. The suite asserts the live list IS this tuple, so a
#: fourth tool is a deliberate edit here, with its reason, not an accident.
TOOLS = ("get_package", "check", "record", "get_plan", "get_results",
         "inbox_search", "inbox_thread", "inbox_draft")
#: skill key -> (the exemplars kind, the ledger format). A format in
#: `ledger.ARTIFACT_FORMATS` keeps the WHOLE artifact beside its ledger row;
#: ad copy is short and lives in the row itself.
KIND_FORMAT = {"campaign_email": ("email", "esp_campaign"),
               "blog_article": ("article", "cms_article"),
               "gbp_post": ("", "gbp_post"),
               "ad_copy": ("", "ad_copy")}
#: Approval-payload keys that give `approvals.apply_decision` something to
#: EXECUTE on approve (an ESP push, a Business Profile publish, a mail send).
#: `record` must never write one — see the module docstring.
EXECUTOR_KEYS = ("esp_push", "gbp_post", "send_mail")
#: An exemplar's HTML beyond this is cut, and the cut is said.
EXEMPLAR_MAX = 12_000

INSTRUCTIONS = (
    "The gomehagent data layer for five client brands. Call get_package "
    "first and write ONLY from what it returns; a fact it does not carry is "
    "a fact you do not have — leave it out and say so. inbox_search, "
    "inbox_thread and inbox_draft reach the account's own inbox; a draft is "
    "never sent. get_plan says what is "
    "due and what is stuck; get_results what worked. Run check on every "
    "draft and fix its blocks before you record. record files the draft in "
    "the owner's approval queue; nothing is sent, pushed or published by "
    "these tools.")


def _refusal(why: str, **more) -> str:
    """A refusal names what would unblock it — the house rule."""
    return json.dumps({"ok": False, "why": why, **more}, ensure_ascii=False, indent=1)


# ---------------------------------------------------------------------------
# The gates, composed — plain function so `record` and the suite share it
# ---------------------------------------------------------------------------

def run_checks(tenant: str, body: str, *, kind: str = "email", subject: str = "",
               preheader: str = "", headline: str = "",
               claim_ids: list[str] | None = None, entity_key: str = "") -> dict:
    """`{ok, blocks, advice, checked}` — every gate, fail-closed.

    A gate that raises becomes a BLOCK naming the gate, never a pass: the
    dangerous default is the validator that could not run and reported clean
    (`validator.py`, `compliance.scan`). Each gate is tried on its own so one
    broken gate costs its own verdict and not the others'.
    """
    from . import (ad_craft, artifact_check, coherence, email_craft, fitness,
                   kb, tenants, validator)
    blocks: list[dict] = []
    advice: list[dict] = []
    checked: list[str] = []
    body = body or ""
    ids = [c for c in (claim_ids or []) if c]

    def block(rule, detail, fix):
        blocks.append({"rule": rule, "detail": detail, "fix": fix})

    def gate(name, fn):
        checked.append(name)
        try:
            fn()
        except Exception as exc:                                  # noqa: BLE001
            block(f"gate_failed:{name}", f"{exc.__class__.__name__}: {exc}",
                  "the gate could not run, so this is not clean — fix the gate "
                  "or the input it choked on, then check again")

    tn = tenants.get(tenant)
    if tn is None:
        block("unknown_account", f"no account {tenant!r}",
              "use one of: " + ", ".join(sorted(t.key for t in tenants.all_tenants())))
        return {"ok": False, "blocks": blocks, "advice": advice, "checked": ["account"]}

    # 1. the ban list, citation, selectable claims
    def _rules():
        v = validator.check(tenant, body, claim_ids=ids, entity_key=entity_key,
                            require_citation=True)
        for f in v.get("failures") or []:
            block(f.get("rule", "rule"), f.get("detail", ""), f.get("fix", ""))
    gate("rules", _rules)

    # 2. the rendered thing holds together
    def _structure():
        if "<" not in body:
            return
        hard = set(artifact_check.BLOCKING)
        for f in artifact_check.check(body):
            (block if f.get("rule") in hard else
             lambda r, d, x: advice.append({"rule": r, "detail": d, "fix": x}))(
                "structure:" + str(f.get("rule", "")), str(f.get("detail", "")),
                str(f.get("fix", "")))
    gate("structure", _structure)

    # 3. the craft review for this kind
    def _craft():
        if kind == "email":
            found = email_craft.review(subject=subject, preheader=preheader, body=body)
        elif kind == "ad":
            found = ad_craft.review(body=body, headline=headline)
        else:
            return
        for f in found:
            row = {"rule": "craft:" + str(f.get("rule", "")),
                   "detail": str(f.get("detail", "")), "fix": str(f.get("fix", ""))}
            (blocks if f.get("severity") == "block" else advice).append(row)
    gate("craft", _craft)

    # 4. a thing this brand may not feature, named in the copy
    ents: list = []

    def _fitness():
        nonlocal ents
        ents = kb.entities(tenant, available_only=False)
        model = str(getattr(tn, "business_model", "") or "")
        for n in fitness.named_unfit(model, " ".join([subject, headline, body]), ents):
            block("unfit_entity_named",
                  f"the draft names {n.get('name', '')}, but {n.get('why', '')}",
                  "feature something the brand may feature, or have the owner "
                  "name it under What's new on the plan")
    gate("fitness", _fitness)

    # 5. one subject, and its parts agree — only when a subject was named
    def _coherence():
        if not entity_key:
            return
        ent = next((e for e in ents if getattr(e, "key", "") == entity_key), None)
        brand = kb.brand(tenant)
        commitment = coherence.commit(
            "entity", entity_key, label=getattr(ent, "name", "") or entity_key)
        got = coherence.parts(text=body, prominent=" ".join([subject, headline]).strip())
        for f in coherence.review(commitment, got,
                                  brand_name=getattr(brand, "display_name", "") or tenant):
            row = {"rule": "coherence:" + str(f.get("rule", "")),
                   "detail": str(f.get("detail", "")), "fix": str(f.get("fix", ""))}
            (blocks if f.get("severity") == "block" else advice).append(row)
    gate("coherence", _coherence)

    return {"ok": not blocks, "blocks": blocks, "advice": advice, "checked": checked}


# ---------------------------------------------------------------------------
# The server and its three tools
# ---------------------------------------------------------------------------

# `-> dict[str, Any]`, not `-> dict`: the SDK gives a tool STRUCTURED output only
# for a return annotation it can model, and a bare `dict` is not one — the client
# then gets text alone. Found by the suite's first run, 2026-10-26.
_security = ({"transport_security": TransportSecuritySettings(
    enable_dns_rebinding_protection=False)} if TransportSecuritySettings else {})
server = FastMCP(NAME, instructions=INSTRUCTIONS,
                 stateless_http=True, json_response=True, **_security)


@server.tool()
def get_package(tenant: str, system: str = "campaign_email",
                entity_key: str = "", audience_key: str = "") -> str:
    """The brand package for one account, as a brief you write from and nothing else.

    Every part the platform declares, in order: the rules (voice, positioning,
    the BAN LIST, what this pipeline has been taught), approved claims WITH
    THEIR IDS (quote a claim as written and pass its id to check/record),
    objections, audiences in the buyer's words, the chosen product's own
    catalogue facts, the site's own pages (the only places a link may go), the
    owner's news, the last piece the owner approved (the standard), and the
    owner's notes (taste, in their words). Parts that arrived empty are NAMED
    under "What is missing" — write around them, never invent.

    `system` is the pipeline asking and scopes the rules: campaign_email,
    blog_article, ad_copy or gbp_post. `entity_key` is the product or thing
    the piece is about; `audience_key` the reader.
    """
    from . import exemplars, handoff, skill, tenants
    if tenants.get(tenant) is None:
        return _refusal(f"unknown account {tenant!r}",
                        known=sorted(t.key for t in tenants.all_tenants()))
    sk = skill.get(system)
    if sk is None:
        return _refusal(f"unknown system {system!r}", known=sorted(KIND_FORMAT))
    kind, _fmt = KIND_FORMAT.get(system, ("", ""))
    lines, got = handoff.package_sections(
        tenant, system=sk.system_key, tier=sk.tier,
        entity_key=entity_key, audience_key=audience_key)

    out = ["---", f"name: {tenant}-{system}",
           f"description: the brand package for {sk.name} — {tenant}", "---", "",
           f"# {sk.name} — {tenant}", "",
           "## Your task", (sk.does or "").rstrip(".") + ".", "",
           "### What to hand back",
           handoff.DELIVER.get(system, "What the task names, ready to use."), "",
           "### The rules", handoff.RULES, ""]

    missing = [f"- BLOCKED — {b}" for b in (got.get("blocked_on") or [])]
    missing += [f"- {g.get('missing', '')}: {g.get('means', '')}"
                + (f" (fix: {g['fix']})" if g.get("fix") else "")
                for g in (got.get("gaps") or []) if isinstance(g, dict)]
    out += ["## What is missing — write around it, never invent it"]
    out += missing or ["- nothing the platform knows to be missing"]
    out += [""]

    out += lines

    if kind:
        html, said = exemplars.standard(tenant, kind)
        if html:
            cut = len(html) - EXEMPLAR_MAX
            out += [f"### exemplar — {said}; the standard of craft this is held to",
                    "```html", html[:EXEMPLAR_MAX]
                    + (f"\n… ({cut:,} more characters — the platform holds the rest)"
                       if cut > 0 else ""), "```", ""]
        notes = exemplars.notes_text(tenant, kind)
        if notes.strip():
            out += [f"### the owner's notes on this brand's {kind}s — taste, in their words",
                    notes.strip(), ""]
    return "\n".join(out)


@server.tool()
def check(tenant: str, body: str, kind: str = "email", subject: str = "",
          preheader: str = "", headline: str = "",
          claim_ids: list[str] | None = None, entity_key: str = "") -> dict[str, Any]:
    """Every gate this platform runs on a draft — no model in the loop.

    The ban list (matched across hyphens and spaces), that every fact is
    backed by a claim id you pass and that each id is still selectable,
    structural faults in rendered HTML (a mangled word, a product recommended
    and never linked), the craft review for the kind (email: subject,
    preheader, body; ad: body, headline), whether a named product may be
    featured for this brand, and — when `entity_key` is given — whether the
    piece is about that one thing and its parts agree.

    Returns {ok, blocks, advice, checked}. A block is a defect the owner
    should never have to catch: fix it and check again before you record.
    Advice rides along and is reported with the draft.
    """
    return run_checks(tenant, body, kind=kind, subject=subject, preheader=preheader,
                      headline=headline, claim_ids=claim_ids, entity_key=entity_key)


@server.tool()
def record(tenant: str, system: str, body: str, kind: str = "email",
           subject: str = "", preheader: str = "", title: str = "",
           entity_key: str = "", audience_key: str = "",
           claim_ids: list[str] | None = None, notes: str = "") -> dict[str, Any]:
    """File a finished draft where the owner reviews everything.

    Runs check first. A clean draft lands on the output ledger, in the
    artifact store, and as ONE pending approval in the console's queue, with
    a review_url the owner opens. A draft with blocks is recorded as blocked
    and queues no approval; the blocks come back so you can fix and record
    again. Nothing is sent, pushed or published by this call — approving in
    the console is the owner's act.

    `system` is the pipeline (campaign_email, blog_article, ad_copy,
    gbp_post). `notes` is anything the owner should know when reviewing —
    what you could not verify, what you left out and why.
    """
    from . import approvals, assurance, ledger, skill, systems, tenants
    if tenants.get(tenant) is None:
        return {"ok": False, "why": f"unknown account {tenant!r}",
                "known": sorted(t.key for t in tenants.all_tenants())}
    sk = skill.get(system)
    if sk is None:
        return {"ok": False, "why": f"unknown system {system!r}",
                "known": sorted(KIND_FORMAT)}
    verdict = run_checks(tenant, body, kind=kind, subject=subject, preheader=preheader,
                         claim_ids=claim_ids, entity_key=entity_key)
    _kind, fmt = KIND_FORMAT.get(system, (kind, ""))
    ok = bool(verdict["ok"])
    row = ledger.record(
        tenant, sk.system_key, entity_key=entity_key, audience_key=audience_key,
        claim_ids=list(claim_ids or []), format=fmt,
        status="draft" if ok else "blocked",
        blocked_on=[f"{b['rule']}: {b['detail']}" for b in verdict["blocks"]],
        body=body,
        meta={"subject": subject, "preheader": preheader, "title": title,
              "kind": kind, "source": "mcp", "notes": notes})
    try:
        assurance.record(tenant, source="mcp", system_key=sk.system_key,
                         output_id=row.id, attempt=1,
                         checked=list(verdict["checked"]),
                         caught=[b["rule"] for b in verdict["blocks"]],
                         verdict="passed" if ok else "blocked",
                         grounded=bool(claim_ids))
    except Exception:                                             # noqa: BLE001
        log.exception("assurance.record failed for %s", row.id)
    approval_id = ""
    if ok:
        payload = {"tenant": tenant, "skill": system, "output_id": row.id,
                   "body": body[:2000], "subject": subject, "preheader": preheader,
                   "title": title, "source": "mcp", "notes": notes}
        # THE TRUST BOUNDARY, as code: no key that `apply_decision` executes.
        assert not (set(payload) & set(EXECUTOR_KEYS)), "record must not arm an executor"
        sysrow = systems.find(tenant, sk.system_key)
        approval_id = approvals.request_approval(
            "skill_output",
            f"{sk.name} for {tenant}: {(subject or title or body)[:80]}",
            payload, notify=False, system_id=(sysrow.id if sysrow else ""))
    url = f"{config.PUBLIC_BASE_URL.rstrip('/')}/admin/work/{row.id}"
    return {"ok": ok, "status": "draft" if ok else "blocked",
            "output_id": row.id, "approval_id": approval_id, "review_url": url,
            "blocks": verdict["blocks"], "advice": verdict["advice"],
            "says": ("filed; one approval waits for the owner at review_url" if ok else
                     "recorded as blocked and NOT queued — fix the blocks and record again")}


# ---------------------------------------------------------------------------
# Planning and results — read-only, the console's own functions
# ---------------------------------------------------------------------------

#: How many rows a list in get_plan / get_results carries before it is cut.
#: The cut is said, never silent.
LIST_MAX = 25


def _plain(v):
    """JSON-safe: datetimes become ISO strings, sets become sorted lists."""
    import datetime as _dt
    if isinstance(v, (_dt.datetime, _dt.date)):
        return v.isoformat()
    if isinstance(v, dict):
        return {str(k): _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    if isinstance(v, set):
        return sorted(_plain(x) for x in v)
    return v


def _cut(rows: list, key: str, out: dict) -> list:
    if len(rows) > LIST_MAX:
        out.setdefault("cut", {})[key] = f"{len(rows)} rows, first {LIST_MAX} shown"
    return rows[:LIST_MAX]


def _part(out: dict, name: str, fn) -> None:
    """One section; a section that raises is NAMED, not dropped and not fatal —
    a plan with a hole nobody can see is worse than one that says where it is."""
    try:
        out[name] = _plain(fn())
    except Exception as exc:                                      # noqa: BLE001
        out.setdefault("unavailable", {})[name] = f"{exc.__class__.__name__}: {exc}"


@server.tool()
def get_plan(tenant: str, days: int = 30) -> dict[str, Any]:
    """What is planned, due, waiting on the owner and stuck — for one account.

    Read before deciding what to make. `systems`: every installed system with
    its status, autonomy and the last `days` of runs (shipped, planned,
    blocked, needs_person). `plans`: open planned work, soonest first, with
    the date it is planned for. `needs_action`: plans waiting on the owner
    (fields to complete, or a go-ahead). `waiting_on`: knowledge-base answers
    that block a system, and which systems. `attention`: why runs were
    blocked, most frequent first, with one example run each.

    Nothing here changes anything.
    """
    from . import systems, tenants
    if tenants.get(tenant) is None:
        return {"ok": False, "why": f"unknown account {tenant!r}",
                "known": sorted(t.key for t in tenants.all_tenants())}
    days = max(1, min(int(days or 30), 365))
    out: dict[str, Any] = {"ok": True, "tenant": tenant, "days": days}
    _part(out, "systems", lambda: _cut(systems.per_system(tenant, days), "systems", out))

    def _plans():
        names = {r.id: r.key for r in systems.for_tenant(tenant)}
        rows = []
        for r in systems.plans(tenant):
            brief = r.brief or {}
            rows.append({"run_id": r.id, "system": names.get(r.system_id, ""),
                         "planned_for": str(brief.get("planned_for") or ""),
                         "ref": r.ref or "",
                         "brief": {k: brief[k] for k in
                                   ("entity_key", "audience_key", "angle", "positioning",
                                    "theme", "keyword", "title", "subject")
                                   if brief.get(k)}})
        return _cut(rows, "plans", out)
    _part(out, "plans", _plans)
    _part(out, "needs_action", lambda: systems.plans_needing_action(tenant))
    _part(out, "waiting_on", lambda: systems.waiting_on(tenant))

    def _attention():
        rows = systems.attention(tenant, days, examples=1)
        for b in rows:
            b.pop("tenants", None)
        return _cut(rows, "attention", out)
    _part(out, "attention", _attention)
    return out


@server.tool()
def get_results(tenant: str, dimension: str = "", days: int = 90) -> dict[str, Any]:
    """What worked, for one account — read before planning the next piece.

    `ads`: measured ad outcomes grouped by the data layer's own dimensions
    (positioning, audience, funnel_stage, angle, entity, claim) — one
    dimension when `dimension` is named, all of them otherwise — with
    `headline`, the positioning that won if one did. An unmeasured row is
    counted, never averaged as a zero. `drafts`: in the last `days`, every
    output per system by status (draft, blocked, approved, published).
    `verdicts`: the owner's decisions on queued drafts, by status.
    `caught`: which gates blocked drafts and how often — what to fix in the
    data layer or the brief.
    """
    from . import results, tenants
    from . import db
    import datetime as _dt
    if tenants.get(tenant) is None:
        return {"ok": False, "why": f"unknown account {tenant!r}",
                "known": sorted(t.key for t in tenants.all_tenants())}
    if dimension and dimension not in results.DIMENSIONS:
        return {"ok": False, "why": f"unknown dimension {dimension!r}",
                "known": list(results.DIMENSIONS)}
    days = max(1, min(int(days or 90), 730))
    since = db.utcnow() - _dt.timedelta(days=days)
    out: dict[str, Any] = {"ok": True, "tenant": tenant, "days": days}
    _part(out, "ads", lambda: (results.by(tenant, dimension) if dimension
                               else results.scoreboard(tenant)))
    _part(out, "headline", lambda: results.headline(tenant))

    def _drafts():
        tally: dict = {}
        with db.SessionLocal() as s:
            for key, status in (s.query(db.Output.system_key, db.Output.status)
                                .filter(db.tenant_filter(db.Output, tenant),
                                        db.Output.created_at >= since)):
                row = tally.setdefault(key or "(none)", {})
                row[status or "(none)"] = row.get(status or "(none)", 0) + 1
        return tally
    _part(out, "drafts", _drafts)

    def _verdicts():
        tally: dict = {}
        with db.SessionLocal() as s:
            for kind, status in (s.query(db.Approval.kind, db.Approval.status)
                                 .filter(db.tenant_filter(db.Approval, tenant),
                                         db.Approval.created_at >= since)):
                row = tally.setdefault(kind or "(none)", {})
                row[status or "(none)"] = row.get(status or "(none)", 0) + 1
        return tally
    _part(out, "verdicts", _verdicts)

    def _caught():
        tally: dict = {}
        with db.SessionLocal() as s:
            for (caught,) in (s.query(db.AssuranceEvent.caught)
                              .filter(db.tenant_filter(db.AssuranceEvent, tenant),
                                      db.AssuranceEvent.created_at >= since)):
                for rule in (caught or []):
                    tally[str(rule)] = tally.get(str(rule), 0) + 1
        return dict(sorted(tally.items(), key=lambda kv: -kv[1])[:LIST_MAX])
    _part(out, "caught", _caught)
    return out


# ---------------------------------------------------------------------------
# The inbox — read, and draft a reply. Nothing here sends.
# ---------------------------------------------------------------------------

#: Accounts whose resolved inbox is NOT client mail. `agency`'s alias is the
#: owner's personal inbox; the three accounts are never mixed (DNA #9).
INBOX_REFUSED = ("agency",)


def _inbox(tenant: str):
    """`(alias, None)` or `(None, refusal)` — the ONE place an inbox is chosen."""
    from . import tenants
    tn = tenants.get(tenant)
    if tn is None:
        return None, {"ok": False, "why": f"unknown account {tenant!r}",
                      "known": sorted(t.key for t in tenants.all_tenants())}
    if tenant in INBOX_REFUSED:
        return None, {"ok": False, "why": f"{tenant!r} resolves to the owner's "
                      "personal inbox, which this server does not serve"}
    alias = getattr(tn, "gmail_alias", "") or ""
    if not alias:
        with_inbox = sorted(t.key for t in tenants.all_tenants()
                            if getattr(t, "gmail_alias", "") and t.key not in INBOX_REFUSED)
        return None, {"ok": False, "why": f"{tenant!r} has no inbox connected",
                      "accounts_with_an_inbox": with_inbox}
    return alias, None


def _failed(exc: Exception) -> dict:
    return {"ok": False, "why": f"the inbox call failed: {exc.__class__.__name__}: {exc}"}


@server.tool()
def inbox_search(tenant: str, query: str = "", days: int = 30,
                 limit: int = 20) -> dict[str, Any]:
    """Search ONE account's own inbox (baci or eien), newest threads first.

    `query` is Gmail search syntax (from:, subject:, "exact phrase", is:unread,
    has:attachment …); `days` bounds it (newer_than), 0 for no bound. Returns
    a summary per thread: subject, first and last sender, date, message count,
    unread, whether the last message is ours (answered) and a snippet. Read a
    thread with inbox_thread before replying to it.
    """
    from . import gmail_client
    alias, refusal = _inbox(tenant)
    if refusal:
        return refusal
    q = " ".join(x for x in [query.strip(),
                             f"newer_than:{int(days)}d" if int(days or 0) > 0 else ""] if x)
    try:
        threads = gmail_client.search_threads(alias, q, max_results=limit)
    except Exception as exc:                                      # noqa: BLE001
        return _failed(exc)
    return {"ok": True, "tenant": tenant, "query": q, "count": len(threads),
            "threads": threads}


@server.tool()
def inbox_thread(tenant: str, thread_id: str) -> dict[str, Any]:
    """One thread of the account's own inbox, every message oldest first.

    Each message: from, to, cc, reply_to, date, subject, whether it is ours
    (sent from this inbox), its text, and attachment file names. Write a reply
    from what the thread says and what get_package carries — never invent an
    order status, a date, a price or a stock level.
    """
    from . import gmail_client
    alias, refusal = _inbox(tenant)
    if refusal:
        return refusal
    try:
        msgs = gmail_client.thread_messages(alias, thread_id)
    except Exception as exc:                                      # noqa: BLE001
        return _failed(exc)
    return {"ok": True, "tenant": tenant, "thread_id": thread_id,
            "messages": msgs}


@server.tool()
def inbox_draft(tenant: str, thread_id: str, body: str, to: str = "",
                cc: str = "", subject: str = "") -> dict[str, Any]:
    """Draft a reply in a thread of the account's own inbox. It is NOT sent.

    The draft lands in that inbox's Gmail Drafts, threaded, for the owner to
    read, edit and send. `to` defaults to the last message that is not ours
    (its Reply-To, else its From); `subject` to "Re: " + the thread's subject.
    Plain text body, signed the way the brand signs.

    Runs the guard the triage path runs before anything can send: the ban list
    and an unavailable product are hard blocks, and a guard that cannot run is
    a block (fail closed). A blocked draft is NOT created; the blocks come back.
    """
    from . import assurance, gmail_client, validator
    alias, refusal = _inbox(tenant)
    if refusal:
        return refusal
    if not (body or "").strip():
        return {"ok": False, "why": "the body is empty"}
    try:
        msgs = gmail_client.thread_messages(alias, thread_id)
    except Exception as exc:                                      # noqa: BLE001
        return _failed(exc)
    theirs = [m for m in msgs if not m.get("ours")]
    if not to:
        last = theirs[-1] if theirs else {}
        to = last.get("reply_to") or last.get("from") or ""
    if not to:
        return {"ok": False, "why": "no recipient: the thread has no message "
                "that is not ours — pass `to`"}
    if not subject:
        base = (msgs[0].get("subject") if msgs else "") or ""
        subject = base if base.lower().startswith("re:") else f"Re: {base}".strip()

    try:
        report = validator.check(tenant, f"{subject} {body}", claim_ids=[],
                                 require_citation=False)
        hard = [f for f in report.get("failures") or []
                if f.get("rule") in ("banned_claim", "entity_unavailable")]
        checked = list(report.get("checked") or [])
    except Exception as exc:                                      # noqa: BLE001
        hard = [{"rule": "gate_failed:validator",
                 "detail": f"{exc.__class__.__name__}: {exc}",
                 "fix": "the guard could not run, so this is not clean"}]
        checked = []
    try:
        assurance.record(tenant, source="mcp-mail", system_key="inbox_reply",
                         checked=checked, caught=[f["rule"] for f in hard],
                         verdict="blocked" if hard else "passed", grounded=False)
    except Exception:                                             # noqa: BLE001
        log.exception("assurance.record failed for an inbox draft")
    if hard:
        return {"ok": False, "status": "blocked", "blocks": hard,
                "says": "NOT drafted — fix the blocks and draft again"}

    try:
        draft_id = gmail_client.create_draft(alias, to, subject, body,
                                             thread_id=thread_id, cc=cc)
    except Exception as exc:                                      # noqa: BLE001
        return _failed(exc)
    return {"ok": True, "status": "drafted", "draft_id": draft_id,
            "to": to, "cc": cc, "subject": subject,
            "says": "a draft in the inbox's Gmail Drafts, threaded — NOT sent; "
                    "the owner reads and sends it"}


# ---------------------------------------------------------------------------
# Auth and mounting
# ---------------------------------------------------------------------------

class _Bearer:
    """ASGI wrapper: `Authorization: Bearer <MCP_KEY>` or 401, constant-time.

    Reads `config.MCP_KEY` per request so the suite can prove the unset case
    without re-importing the app. An empty expected value never matches.
    """

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.inner(scope, receive, send)
        headers = {k.lower(): v for k, v in (scope.get("headers") or [])}
        auth = headers.get(b"authorization", b"").decode("latin-1")
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        expected = str(getattr(config, "MCP_KEY", "") or "")
        if not (token and expected and secrets.compare_digest(token, expected)):
            body = json.dumps({
                "error": "unauthorized",
                "detail": ("MCP_KEY is not set on this deployment, so every request is refused"
                           if not expected else
                           "present the deployment's MCP_KEY as `Authorization: Bearer …`")
            }).encode()
            await send({"type": "http.response.start", "status": 401,
                        "headers": [(b"content-type", b"application/json"),
                                    (b"www-authenticate", b"Bearer"),
                                    (b"content-length", str(len(body)).encode())]})
            await send({"type": "http.response.body", "body": body})
            return
        return await self.inner(scope, receive, send)


class _Handler:
    """Hands each request to WHATEVER session manager is current — the one the
    latest startup built — so a restart never serves a manager whose `run()`
    has already exited."""

    async def __call__(self, scope, receive, send):
        await server.session_manager.handle_request(scope, receive, send)


_run_ctx = None


def _fresh_manager() -> None:
    # The SDK builds the manager lazily inside `streamable_http_app()` and
    # `run()` is once-per-instance; a restart (and every test client that
    # re-enters the app) needs a new one, which means dropping the cached one.
    server._session_manager = None            # noqa: SLF001 — the SDK's cache
    server.streamable_http_app()


def mount(app) -> None:
    """One route, `/mcp`, behind the bearer; the session manager runs with the app."""
    _fresh_manager()
    app.add_route("/mcp", _Bearer(_Handler()), methods=["GET", "POST", "DELETE"],
                  include_in_schema=False)

    @app.on_event("startup")
    async def _mcp_start() -> None:
        global _run_ctx
        _fresh_manager()
        _run_ctx = server.session_manager.run()
        await _run_ctx.__aenter__()
        log.info("mcp: /mcp up (%s), key %s", ", ".join(TOOLS),
                 "set" if config.MCP_KEY else "NOT SET — every request refused")

    @app.on_event("shutdown")
    async def _mcp_stop() -> None:
        global _run_ctx
        if _run_ctx is not None:
            try:
                await _run_ctx.__aexit__(None, None, None)
            finally:
                _run_ctx = None
