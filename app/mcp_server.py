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
    get_statements every FIGURE the account's sites state — subject, value,
                  page, where on the page, binding or not — grouped by
                  subject with the subjects the site disagrees with itself on
                  first; JSON or CSV. Owner, 2026-11-04: seven country counts
                  across Transak's pages, none of them in the claims.
    get_trust     how far the capture can be trusted for one account: known
                  answers (facts QA wrote down) passing or failing, audit
                  recall, legal/coverage pages read in full, open figures no
                  reader understood — a grade with its reasons. Read before
                  relying on get_statements. Read-only.
    get_truth     the APPROVED answer per subject × scope (what QA decided is
                  true, from which source, why, by whom) and the open
                  findings: pages that disagree with it, subjects the site
                  states several ways with no answer chosen — and open
                  CHANGES: a changed answer with every page, draft and
                  unreadable page still to update. Draft from the approved
                  answers; never from a disputed figure. Read-only.
    get_pages     the CRAWL itself: every page of the account's sites as
                  fetched — tier, title, headings, size, links, when it last
                  changed — searchable; one page in full (blocks, headings,
                  tables, lists, links, structured data) with its earlier
                  copies. For SEO/AEO and snapshot work. Read-only.
    get_claims    the whole claims register — proposed, approved, rejected —
                  with evidence, source page and tags, filtered and paged,
                  plus how much of the account's sites the harvest has read.
                  Owner, 2026-11-04: what a harvest captures must be
                  exportable to a Claude session to dig into. Read-only.
    inbox_search  the account's OWN inbox, searched (Gmail query syntax)
    inbox_thread  one thread of that inbox, every message, with attachments
    inbox_attachment the TEXT of one attachment on one message of that inbox
                  (pdf, xlsx, csv, txt, eml). Owner, 2026-11-02: duty is in
                  the inbox's records, on the broker's 7501 entries and
                  invoices, which inbox_thread lists by name only.
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
         "get_claims", "propose_claim_record",
         "get_statements", "get_trust", "get_truth", "get_pages",
         "inbox_search", "inbox_thread", "inbox_attachment", "inbox_draft")
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
    "inbox_thread, inbox_attachment and inbox_draft reach the account's own "
    "inbox; a draft is "
    "never sent. get_plan says what is "
    "due and what is stuck; get_results what worked; get_claims lists every "
    "claim in an account's knowledge base with its evidence and source, "
    "including proposals awaiting the owner. Run check on every "
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



def _absent(kind: str, exemplar_html: str, notes: str, entity_key: str,
            utterance: str) -> list[str]:
    """The absences the resolver never lists, each with what would fill it."""
    out = []
    if kind and not exemplar_html:
        out.append(f"- no approved exemplar for this brand's {kind}s yet — the first "
                   f"approval becomes the standard; hold the work to the brand's own "
                   f"best, not to a generic one")
    if kind and not notes.strip():
        out.append(f"- no owner notes for this brand's {kind}s yet — nothing the owner "
                   f"has said about them is on file; ask after the review and record it")
    if not entity_key:
        out.append("- no entity_key was given — the package carries no product's own "
                   "facts; pass the product's key, or state no product fact")
    if not utterance.strip():
        out.append("- no utterance was given — objections and situations were not "
                   "searched; pass what this piece answers (the hesitation, the "
                   "occasion) to get the approved answers")
    return out


def _inventory(got: dict, exemplar_html: str, notes: str) -> str:
    """One line a reader can check the package against."""
    def n(key):
        v = got.get(key)
        return len(v) if isinstance(v, (list, dict)) else (1 if v else 0)
    pages = 0
    try:
        from . import links as _links
        pages = len([d for d in _links.destinations(got.get("tenant", ""), fetch=False)
                     if d.get("url")])
    except Exception:                                             # noqa: BLE001
        pages = -1
    return (f"claims {n('claims')} · objections {n('objections')} · audiences "
            f"{n('audiences')} · entities {n('entities')} · site pages "
            f"{pages if pages >= 0 else '?'} · exemplar {'yes' if exemplar_html else 'no'}"
            f" · owner notes {'yes' if notes.strip() else 'no'}")


@server.tool()
def get_package(tenant: str, system: str = "campaign_email",
                entity_key: str = "", audience_key: str = "",
                utterance: str = "", news: str = "") -> str:
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
    the piece is about — without it there are no product facts; `audience_key`
    the reader. `utterance` is what the piece answers (the hesitation, the
    occasion, the question) — without it no objections are searched. `news` is
    the owner's facts for THIS piece, stated as given and never as a claim.
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
        entity_key=entity_key, audience_key=audience_key,
        utterance=utterance, inputs=({"news": news} if news.strip() else None))
    html, said = exemplars.standard(tenant, kind) if kind else ("", "")
    notes = exemplars.notes_text(tenant, kind) if kind else ""

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
    # WHAT THE RESOLVER DOES NOT REPORT AS A GAP, said anyway. The first live
    # read of the Baci package (2026-11-03) carried no exemplar, no notes, no
    # product and no objections, and this block said "nothing the platform
    # knows to be missing" — a false reassurance handed to the generator.
    missing += _absent(kind, html, notes, entity_key, utterance)
    out += ["## What is missing — write around it, never invent it"]
    out += missing or ["- nothing the platform knows to be missing"]
    out += ["", "## What this package holds", _inventory(got, html, notes), ""]

    # LEGAL STATEMENTS — binding. Owner, 2026-11-04: what the brand's legal
    # pages say is "critical in terms of importance and should never be
    # contradicted". Listed ahead of everything a writer selects from, so no
    # draft can be built without them in front of it.
    from . import kb
    legal = kb.legal_claims(tenant)
    if legal:
        out += ["## Legal statements — BINDING. Never contradict, soften or "
                "paraphrase these; if a draft cannot agree with one, leave the "
                "point out."]
        out += [f"- {c.claim} [{c.id}] — {c.source}" for c in legal]
        out += [""]
    # THE APPROVED ANSWERS (BUILD-MAP M7): figures QA decided are true, per
    # scope. A draft stating any of these subjects must use these values —
    # `check` blocks one that does not — and must leave out a subject that is
    # still disputed.
    from . import findings as _fd, truth as _truth
    answers = [a for a in _truth.table(tenant) if not a["unknown"]]
    if answers:
        out += ["## Approved figures — use exactly these; `check` blocks any other value"]
        out += [f"- {a['question'].replace('do we say we', 'do we')} {a['value']} "
                f"({a['scope']}{'; follows ' + a['source_url'] if a['mode'] == 'follows_source' else ''})"
                for a in answers]
        out += [""]
    disputed = sorted({f["subject"] for f in _fd.listing(tenant)
                       if f["kind"] in ("unresolved", "binding_conflict")})
    if disputed:
        out += ["## Disputed figures — do NOT state these; the site disagrees with "
                "itself and no answer is approved yet"]
        out += [f"- {_truth.question(sbj)}" for sbj in disputed]
        out += [""]

    out += lines

    if kind:
        if html:
            cut = len(html) - EXEMPLAR_MAX
            out += [f"### exemplar — {said}; the standard of craft this is held to",
                    "```html", html[:EXEMPLAR_MAX]
                    + (f"\n… ({cut:,} more characters — the platform holds the rest)"
                       if cut > 0 else ""), "```", ""]
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


#: get_statements' CSV columns, one row per statement.
STATEMENT_CSV_COLUMNS = ("subject", "value", "number", "qualifier", "unit",
                         "authority", "field", "url", "text", "entity_key",
                         "market", "observed_at", "subject_conflict",
                         "extractor", "section", "locator", "kind", "currency")


@server.tool()
def get_statements(tenant: str, subject: str = "", conflicts_only: bool = False,
                   format: str = "json") -> dict[str, Any]:
    """Every figure one account's sites state, by subject — where the site disagrees with itself.

    A statement is a fact as DATA — subject (coverage.countries,
    coverage.states, legal.licences, scale.users …), value as written
    ("162+", "more than 90"), the page, where on it (body, furniture =
    header/footer, page_data = loaded by JavaScript) and `authority`
    (binding = a legal/compliance page). Recorded by code from every page on
    every harvest, so it is a census, not a sample.

    JSON: `subjects` — one entry per subject with every distinct value, the
    pages for each, and `conflict` when the site states more than one value;
    conflicting subjects first. `subject` narrows to one; `conflicts_only`
    keeps the disagreements. `format="csv"`: one row per statement in `csv`,
    with `subject_conflict` so it can be filtered in a sheet, and the reader
    that saw it (`extractor`: numbers | enumerations = a counted table/list |
    structured), its heading path (`section`) and position (`locator`).
    `unaccounted` lists figures no reader understood, with their sentence and
    pages — the capture's known gaps. Read-only.
    """
    from . import statements, tenants
    if tenants.get(tenant) is None:
        return {"ok": False, "why": f"unknown account {tenant!r}",
                "known": sorted(t.key for t in tenants.all_tenants())}
    fmt = (format or "json").strip().lower()
    if fmt not in ("json", "csv"):
        return {"ok": False, "why": f"unknown format {format!r}", "known": ["json", "csv"]}
    subjects = statements.summary(tenant, subject)
    if conflicts_only:
        subjects = [x for x in subjects if x["conflict"]]
    out: dict[str, Any] = {
        "ok": True, "tenant": tenant, "format": fmt,
        "subjects_total": len(subjects),
        "subjects_in_conflict": sum(1 for x in subjects if x["conflict"]),
    }
    # Figures on the site no reader understood — the capture's own gaps,
    # stated so a clean summary is never mistaken for a complete one.
    from .pipeline import account as _acc
    figs = _acc.open_figures(tenant, limit=500)
    out["unaccounted_open"] = len(figs)
    if fmt == "json":
        out["subjects"] = subjects
        out["unaccounted"] = figs[:100]
        return out
    import csv as _csv
    import io as _io
    conflict = {x["subject"]: x["conflict"] for x in subjects}
    buf = _io.StringIO()
    w = _csv.writer(buf)
    w.writerow(STATEMENT_CSV_COLUMNS)
    n = 0
    for r in statements.rows(tenant, subject):
        if r.subject not in conflict:
            continue
        w.writerow([r.subject, r.value, r.number, r.qualifier, r.unit, r.authority,
                    r.field, r.url, r.text, r.entity_key, r.market,
                    r.observed_at.isoformat() if r.observed_at else "",
                    "yes" if conflict[r.subject] else "",
                    r.extractor or "", r.section or "", r.locator or "",
                    r.kind or "count", r.currency or ""])
        n += 1
    out["rows"] = n
    out["csv"] = buf.getvalue()
    return out


@server.tool()
def get_trust(tenant: str) -> dict[str, Any]:
    """How far one account's captured site facts can be trusted, and why.

    `grade` is green / amber / red with `reasons`. Red means a known answer
    (a fact QA wrote down in advance, e.g. "19 licences on /compliance") was
    not captured correctly, or a legal/coverage page was only partly read —
    do not rely on `get_statements` for that account until it is fixed.
    Includes each known answer's result, audit recall (pages a person checked
    against what was recorded) and the count of figures no reader understood.
    Read-only."""
    from . import tenants
    from .pipeline import checks
    if tenants.get(tenant) is None:
        return {"ok": False, "why": f"unknown account {tenant!r}",
                "known": sorted(t.key for t in tenants.all_tenants())}
    return {"ok": True, **checks.trust(tenant)}


@server.tool()
def get_truth(tenant: str, subject: str = "", include_closed: bool = False) -> dict[str, Any]:
    """The approved truth for one account, and every open disagreement with it.

    `answers`: one row per subject × scope QA approved — value, scope
    (brand-wide, a product, a market), mode (pinned, or follows a source page
    so it moves when that page changes), source, reason, who decided.
    `findings`: open questions, P1 first — `unresolved` (the site states
    several values, none chosen), `contradiction` (pages disagree with the
    answer), `binding_conflict` (a LEGAL page disagrees — the answer itself is
    suspect), `missing_known` (a known answer was not captured).
    Use an answer as fact; treat a subject with an open finding as disputed.
    Decisions are made by a person in the console, never here. Read-only."""
    from . import change, findings, tenants, truth
    if tenants.get(tenant) is None:
        return {"ok": False, "why": f"unknown account {tenant!r}",
                "known": sorted(t.key for t in tenants.all_tenants())}
    answers = [a for a in truth.table(tenant) if not subject or a["subject"] == subject]
    fs = findings.listing(tenant, "all" if include_closed else "open")
    fs = [f for f in fs if not subject or f["subject"] == subject]
    return {"ok": True, "tenant": tenant, "answers": answers,
            "findings": fs[:200], "findings_total": len(fs),
            "p1_open": sum(1 for f in fs if f["severity"] == "P1" and f["status"] == "open"),
            "sources": [{"url": x.ref, "governs": x.governs or [], "by": x.created_by}
                        for x in truth.sources(tenant)],
            # Changed answers and every place still stating the old one.
            "changes": [c for c in change.listing(tenant, "open")
                        if not subject or c["subject"] == subject][:50]}


#: Most pages one get_pages listing returns; page with `offset`.
PAGES_MAX = 200


@server.tool()
def get_pages(tenant: str, url: str = "", query: str = "", tier: str = "",
              changed_since: str = "", version: str = "", offset: int = 0,
              limit: int = 50) -> dict[str, Any]:
    """The account's crawl as data — every stored page, or one page in full.

    LISTING (no `url`): one row per page — url, risk tier (legal, coverage,
    product, support, marketing, blog), title, top headings, words, links,
    tables, lists, figures recorded, fetched_at, changed_at, earlier copies,
    and whether it needed a browser. `query` matches url, title, headings and
    body text; `tier` filters; `changed_since` (YYYY-MM-DD) keeps pages whose
    content changed on or after that date. Paged by `offset`/`limit`.

    ONE PAGE (`url`): its parsed Document — headings, body blocks, every
    visible line incl. header/footer, tables, lists, links, JSON-LD and
    embedded page data — plus `versions`, the earlier copies kept when it
    changed. `version=<content_hash>` returns that earlier copy's text.
    For SEO / AEO work (titles, headings, internal links, structured data,
    what changed when). Read-only; never fetches the live site."""
    from sqlalchemy import func

    from . import db, statements, tenants
    from .pipeline import fetch, parse
    if tenants.get(tenant) is None:
        return {"ok": False, "why": f"unknown account {tenant!r}",
                "known": sorted(t.key for t in tenants.all_tenants())}

    def _when(d):
        return d.isoformat() if d else ""

    if url:
        row = fetch.latest(tenant, url)
        if row is None:
            return {"ok": False, "why": f"{url} is not in this account's crawl"}
        vers = fetch.versions(tenant, url)
        out = {"ok": True, "tenant": tenant, "url": url, "tier": row.risk_tier,
               "fetched_at": _when(row.fetched_at), "changed_at": _when(row.changed_at),
               "rendered": row.rendered or 0,
               "versions": [{"content_hash": v.content_hash, "first_seen": _when(v.first_seen),
                             "replaced_at": _when(v.last_seen), "bytes": v.bytes_} for v in vers]}
        if version:
            v = next((v for v in vers if v.content_hash == version), None)
            if v is None:
                return {"ok": False, "why": f"no earlier copy {version!r} of {url}"}
            d = parse.parse(fetch.html_of(v))
            out.update({"version": version, "blocks": d["blocks"][:600],
                        "headings": d["headings"], "lines": d["lines"][:800]})
            return out
        d = parse.document(tenant, url)
        out.update({k: d.get(k) for k in ("headings", "tables", "lists", "jsonld",
                                           "interactive", "from_page_data", "numbers_total")})
        out.update({"blocks": d.get("blocks", [])[:600], "lines": d.get("lines", [])[:800],
                    "links": d.get("links", [])[:500], "page_data": d.get("page_data", [])[:300],
                    "statements": [{"subject": r.subject, "value": r.value, "field": r.field,
                                    "authority": r.authority, "text": r.text[:200]}
                                   for r in statements.rows_for_url(tenant, url)]})
        return out

    q = (query or "").strip().lower()
    since = (changed_since or "").strip()
    rows = []
    for r in fetch.snapshots(tenant):
        if tier and (r.risk_tier or "") != tier:
            continue
        if since and (not r.changed_at or r.changed_at.date().isoformat() < since):
            continue
        # The page's stored summary — no Document opened to list it. An older
        # row without one gets it now, once; a text search beyond the title
        # and headings reads that one page's blocks.
        sm = r.summary or {}
        if not sm or sm.get("version") != parse.VERSION:
            sm = fetch.summarise(parse.document(tenant, r.url))
            fetch.set_summary(r.id, sm)
        heads = sm.get("headings", [])
        if q and q not in r.url.lower() and not any(q in h.lower() for h in heads):
            d, _ver = fetch.document_of(r.id)
            if q not in " ".join(d.get("blocks", [])).lower():
                continue
        rows.append({"url": r.url, "tier": r.risk_tier, "title": sm.get("title", ""),
                     "headings": heads[:6], "words": sm.get("words", 0),
                     "links": sm.get("links", 0), "tables": sm.get("tables", 0),
                     "lists": sm.get("lists", 0), "has_jsonld": bool(sm.get("has_jsonld")),
                     "fetched_at": _when(r.fetched_at), "changed_at": _when(r.changed_at),
                     "rendered": r.rendered or 0, "source": r.source_label})
    with db.SessionLocal() as s:
        nver = dict(s.query(db.PageVersion.url, func.count(db.PageVersion.id))
                    .filter(db.PageVersion.tenant == tenant).group_by(db.PageVersion.url).all())
    for x in rows:
        x["earlier_copies"] = nver.get(x["url"], 0)
    limit = max(1, min(int(limit or 50), PAGES_MAX))
    return {"ok": True, "tenant": tenant, "total": len(rows), "offset": offset,
            "returned": len(rows[offset:offset + limit]), "pages": rows[offset:offset + limit]}


#: Most claims one get_claims call returns. Page with `offset` past this.
CLAIMS_MAX = 500
#: The review states a claim can be in, plus "all".
CLAIM_REVIEWS = ("all", "proposed", "approved", "rejected")
#: get_claims' CSV columns, in order — every field a row carries.
CLAIM_CSV_COLUMNS = ("id", "legal", "review", "claim", "evidence", "proof_type",
                     "source", "host", "context", "proves", "attributed_to",
                     "situations", "entity_key", "status", "origin", "strength",
                     "verified_at", "expires_at")


def _host(text: str) -> str:
    """The host a claim's `source` names — "stated on https://x.y/z" → x.y."""
    import re as _re
    m = _re.search(r"https?://([^/\s]+)", text or "")
    return (m.group(1).lower().removeprefix("www.") if m else "")


@server.tool()
def get_claims(tenant: str, review: str = "all", query: str = "",
               source: str = "", legal_only: bool = False, offset: int = 0,
               limit: int = 200, format: str = "json") -> dict[str, Any]:
    """Every claim in one account's knowledge base, with its evidence — to read, sort and dig into.

    Owner, 2026-11-04: the claims a harvest captures must be exportable so a
    Claude session can work through them directly. get_package hands over
    only the APPROVED claims a pipeline selects; this is the whole register:
    proposed (awaiting the owner), approved and rejected, each with its
    evidence, proof type, the page it came from, its situation tags, the
    entity it is true of and when it was verified.

    `review`: all | proposed | approved | rejected. `query`: words to find in
    the claim, its evidence or its source. `source`: only claims whose source
    names this (a host such as support.transak.com, or a path). Paged:
    `offset` + `limit` (max 500); `next_offset` is set while more remain.
    `harvest` says how much of the account's own sites has been read, by
    host — the coverage behind the register. Read-only: nothing is approved,
    changed or filed here.

    LEGAL claims — stated on a privacy, terms, cookie, legal, disclaimer or
    policy page — carry `legal: true`, come FIRST, and are binding: never
    contradict, soften or paraphrase them. `legal_only` returns just those.

    `format="csv"` returns the same page of claims as one CSV text in `csv`
    (a header row, one row per claim, situations joined with "|"), ready to
    save as a file and clean in a spreadsheet or with AI. Page through with
    `next_offset` exactly as for JSON.
    """
    from . import db, provenance as prov, tenants
    if tenants.get(tenant) is None:
        return {"ok": False, "why": f"unknown account {tenant!r}",
                "known": sorted(t.key for t in tenants.all_tenants())}
    fmt = (format or "json").strip().lower()
    if fmt not in ("json", "csv"):
        return {"ok": False, "why": f"unknown format {format!r}", "known": ["json", "csv"]}
    review = (review or "all").strip().lower()
    if review not in CLAIM_REVIEWS:
        return {"ok": False, "why": f"unknown review {review!r}",
                "known": list(CLAIM_REVIEWS)}
    offset = max(0, int(offset or 0))
    limit = max(1, min(int(limit or 200), CLAIMS_MAX))
    words = [w for w in (query or "").lower().split() if w]
    want_src = (source or "").strip().lower()

    from . import kb
    with db.SessionLocal() as s:
        rows = (s.query(db.KbClaim)
                .filter(db.KbClaim.tenant == tenant)
                .order_by(db.KbClaim.verified_at.desc(), db.KbClaim.id).all())
        pages = (s.query(db.HarvestedPage)
                 .filter(db.HarvestedPage.tenant == tenant).all())
        s.expunge_all()

    def _review_of(c) -> str:
        r = (c.review or "").strip()
        return r if r in (prov.PROPOSED, prov.APPROVED, prov.REJECTED) else prov.APPROVED

    counts = {"proposed": 0, "approved": 0, "rejected": 0}
    by_host: dict[str, int] = {}
    matched = []
    legal_n = 0
    # Legal claims first — stable within each group, so paging is stable.
    rows = sorted(rows, key=lambda c: not kb.is_legal_claim(c))
    for c in rows:
        r = _review_of(c)
        is_legal = kb.is_legal_claim(c)
        legal_n += is_legal
        counts[r] = counts.get(r, 0) + 1
        h = _host(c.source or "") or "(no url)"
        by_host[h] = by_host.get(h, 0) + 1
        if review != "all" and r != review:
            continue
        hay = " ".join((c.claim or "", c.evidence or "", c.source or "")).lower()
        if words and not all(w in hay for w in words):
            continue
        if want_src and want_src not in (c.source or "").lower():
            continue
        if legal_only and not is_legal:
            continue
        matched.append((c, r, is_legal))

    def _iso(v):
        return v.isoformat() if v else ""

    claims = [{
        "id": c.id, "legal": is_legal, "claim": c.claim or "",
        "evidence": c.evidence or "",
        "proof_type": c.proof_type or "", "source": c.source or "",
        "host": _host(c.source or ""), "attributed_to": c.attributed_to or "",
        "context": c.context or "", "proves": c.proves or "",
        "situations": list(c.situations or []), "entity_key": c.entity_key or "",
        "review": r, "status": c.status or "", "origin": c.origin or "",
        "strength": c.strength or "", "verified_at": _iso(c.verified_at),
        "expires_at": _iso(c.expires_at),
        # The claim record (BUILD-MAP §17) — what a reviewer still needs.
        "subject": c.subject or "", "kinds": c.kinds or "",
        "scope": {k: v for k, v in (c.scope or {}).items() if not k.startswith("_")},
        "statement": c.statement or "", "record_status": c.record_status or "",
    } for c, r, is_legal in matched[offset:offset + limit]]

    pages_by_host: dict[str, int] = {}
    for p in pages:
        h = _host(p.url or "") or "(unknown)"
        pages_by_host[h] = pages_by_host.get(h, 0) + 1
    nxt = offset + limit
    csv_text = ""
    if fmt == "csv":
        import csv as _csv
        import io as _io
        buf = _io.StringIO()
        w = _csv.writer(buf)
        cols = list(CLAIM_CSV_COLUMNS)
        w.writerow(cols)
        for row in claims:
            w.writerow(["|".join(row[k]) if isinstance(row[k], list)
                        else ("yes" if row[k] is True else "" if row[k] is False
                              else row[k]) for k in cols])
        csv_text = buf.getvalue()
    return {
        "ok": True, "tenant": tenant, "review": review, "format": fmt,
        "total_in_account": len(rows), "legal_in_account": legal_n,
        "by_review": counts,
        "by_source_host": dict(sorted(by_host.items(), key=lambda kv: -kv[1])),
        "matched": len(matched), "offset": offset, "returned": len(claims),
        "next_offset": nxt if nxt < len(matched) else None,
        **({"csv": csv_text} if fmt == "csv" else {"claims": claims}),
        "harvest": {
            "pages_read": len(pages),
            "pages_by_host": dict(sorted(pages_by_host.items(), key=lambda kv: -kv[1])),
            "pages_with_claims": sum(1 for p in pages if (p.claims_found or 0) > 0),
            "pages_truncated": sum(1 for p in pages if p.truncated == "yes"),
            "last_read": _iso(max((p.read_at for p in pages if p.read_at), default=None)),
        },
    }


@server.tool()
def propose_claim_record(tenant: str, claim_id: str, subject: str = "",
                         subject_name: str = "", entity_key: str = "",
                         market: str = "", jurisdiction: str = "", conditions: str = "",
                         audience: str = "", counts: str = "", statement: str = "",
                         infeasible: bool = False, why: str = "") -> dict[str, Any]:
    """PROPOSE what one claim is about and the sentence it stands as — a reviewer confirms.

    The claim record (BUILD-MAP §17): a claim harvested from a site is a
    sentence without its scope — "Coverage of 18+ countries" does not say
    which product, which countries, or as of when. Read the claim with
    `get_claims` (its page, section, context and the record code already
    derived), then propose only what the page itself supports:

    * `subject`: self (the account says it of itself) | other (about a named
      partner or third party — put the name in `subject_name`) | market (an
      industry or market fact). Only `self` can ever be approved as a claim.
    * `entity_key`: which of the account's entities it is true of, or
      "brand-wide". Leave empty when the page does not say.
    * `market`, `jurisdiction`, `conditions` (for whom / which method / which
      KYC level), `audience` (partners or end users), `counts` (what a number
      counts): restrictive qualifiers — the claim is false without them.
    * `statement`: ONE sentence that stands alone — subject named, every
      qualifier in it, nothing the page does not say. If the fragment cannot be
      made to stand alone from its page, pass `infeasible=True` instead of
      guessing (decontextualization's honest outcome).

    Nothing here approves anything, and a reviewer's value is never
    overwritten. `why`: one line on what in the page supports the proposal.
    """
    from . import claim_record, tenants
    if tenants.get(tenant) is None:
        return {"ok": False, "why": f"unknown account {tenant!r}"}
    scope = {k: v for k, v in (("market", market), ("jurisdiction", jurisdiction),
                               ("conditions", conditions), ("audience", audience),
                               ("counts", counts)) if v}
    return claim_record.set_record(
        tenant, claim_id, by="claude (mcp)", origin="claude",
        subject=subject or None, subject_name=subject_name or None,
        entity_key=entity_key or None, scope=scope or None,
        statement=statement or None, infeasible=infeasible, why=why)


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


#: Attachment text returned per call. A customs entry or freight invoice is a
#: page or two; this caps a catalogue someone attached.
ATTACHMENT_MAX_CHARS = 12000


def _attachment_text(name: str, data: bytes) -> str | None:
    """Text of a PDF, spreadsheet or plain-text file; None for anything else."""
    low = name.lower()
    if low.endswith(".pdf"):
        from .data_tools import _pdf_text
        return _pdf_text(data)
    if low.endswith((".xlsx", ".xlsm")):
        import io

        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        rows = []
        for ws in wb.worksheets:
            rows.append(f"## {ws.title}")
            for r in ws.iter_rows(values_only=True):
                if any(c not in (None, "") for c in r):
                    rows.append("\t".join("" if c is None else str(c) for c in r))
        return "\n".join(rows)
    if low.endswith((".txt", ".csv", ".eml")):
        return data.decode(errors="replace")
    return None


@server.tool()
def inbox_attachment(tenant: str, message_id: str, filename: str = "") -> dict[str, Any]:
    """Read the TEXT of one attachment on one message of the account's own inbox.

    Use the message `id` from inbox_thread. `filename` picks the attachment by
    a case-insensitive substring; empty returns the list of attachments. Reads
    PDF (text layer), xlsx, csv, txt and eml: customs entries (7501),
    freight and broker invoices, packing lists. Read-only; nothing is stored
    or sent. A scanned PDF with no text layer says so instead of guessing.
    """
    from . import gmail_client
    alias, refusal = _inbox(tenant)
    if refusal:
        return refusal
    try:
        atts = gmail_client.message_attachments(alias, message_id)
    except Exception as exc:                                      # noqa: BLE001
        return _failed(exc)
    names = [a.get("filename", "") for a in atts]
    want = (filename or "").strip().lower()
    if not want:
        return {"ok": True, "tenant": tenant, "message_id": message_id,
                "attachments": names}
    hit = next((a for a in atts if want in a.get("filename", "").lower()), None)
    if hit is None:
        return {"ok": False, "why": f"no attachment matching {filename!r}",
                "attachments": names}
    try:
        data = gmail_client.download_attachment(alias, message_id, hit["attachment_id"])
        text = _attachment_text(hit["filename"], data)
    except Exception as exc:                                      # noqa: BLE001
        return _failed(exc)
    if text is None:
        return {"ok": False, "why": f"{hit['filename']!r} is not a type this tool reads "
                "(pdf, xlsx, csv, txt, eml)", "attachments": names}
    if not text.strip():
        return {"ok": False, "why": f"{hit['filename']!r} has no text layer "
                "(likely a scanned image); read it by eye", "attachments": names}
    return {"ok": True, "tenant": tenant, "message_id": message_id,
            "filename": hit["filename"], "chars": len(text),
            "truncated": len(text) > ATTACHMENT_MAX_CHARS,
            "text": text[:ATTACHMENT_MAX_CHARS]}


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
