"""A job, as a file you can hand to Claude.

Owner, 2026-09-28: "make sure that every Job organizes the context in the
skill file and shows it in the job queue so I can take failed jobs and just
run them in a Claude chat in case it fails and I have to quickly turn it
around for a client."

One document per job, in the shape of a Claude skill file — frontmatter, the
instructions, then the context. The context is the SAME package the job's
skill reads (`resolve.resolve`, every part `bundle.PARTS` declares, in its
order), with what the job was asked and what went wrong. Pasted into a chat,
or uploaded as a skill, it carries everything the platform knew, so the work
can be finished by hand without gathering anything again.
"""
from __future__ import annotations

import json
import re

#: Parts of the package that describe the package rather than the account.
_META = {"tenant", "system", "tier", "coverage", "grounding",
         "correspondence_coverage", "perishable", "needs_lookup"}
#: One part's JSON beyond this is cut, and the cut is said.
PART_MAX = 12_000
#: Jobs whose work a chat can do from the brand's material. The rest (a sync,
#: a harvest, a scan) need the platform's own connections: their file is the
#: task, its inputs and the failure.
WRITES = {"system_run", "email_recreate", "ad_frames", "boards"}

#: What each skill hands back, said the way a person would brief it.
DELIVER = {
    "campaign_email": (
        "A campaign email: a subject line (under 60 characters), a preheader (under 90), and the "
        "complete HTML — table layout, every style inline, one centred 600 px column, email-safe "
        "fonts, the brand's footer with its postal address and a {{UNSUBSCRIBE}} link. Every link "
        "is a page that appears in the catalogue below; the plan's `link`, when there is one, is "
        "where the main button goes."),
    "blog_article": (
        "A blog article: a title, a meta description (under 155 characters), and the body as "
        "HTML, written for the keyword in the inputs — in the title, the first paragraph and one "
        "subheading, never stuffed. Link only to pages in the catalogue below."),
    "ad_copy": (
        "Ad copy variants (as many as the inputs ask, else three): each a primary text, a "
        "headline under 40 characters, a description and a call to action — one idea across all "
        "of them, the positioning in the inputs."),
    "gbp_post": (
        "A Google Business Profile post: the text (under 1,500 characters, the local keyword "
        "once, naturally), the button, and where it goes."),
    "reorder_prompt": (
        "A reorder email: subject, preheader and body, to the buyer the inputs name."),
}

RULES = """\
- Say only what the context below supports. A claim is quoted as it is written, or not at all.
- Never use a phrase the rules ban, and keep every line the rules say must appear.
- Invent nothing: no price, discount, deadline, review, quote, statistic or product fact that
  is not below. If the work needs a fact that is missing, leave it out and say so at the end.
- Write in the brand's voice as the rules describe it, for the audience below."""


def _json(value) -> str:
    text = json.dumps(value, ensure_ascii=False, indent=1, default=str)
    if len(text) > PART_MAX:
        cut = len(text) - PART_MAX
        text = text[:PART_MAX] + f"\n… ({cut:,} more characters — the platform holds the rest)"
    return text


def _empty(value) -> bool:
    """Nothing to read: blank, or a record whose every field is blank."""
    if isinstance(value, dict):
        return all(_empty(v) or v is False for v in value.values())
    return value is None or value == "" or value == []


def for_job(job_id: str) -> dict:
    """`{ok, name, markdown}` for one job — or `{ok: False, why}`."""
    from . import bundle, db, jobs, resolve, skill as skill_mod
    with db.SessionLocal() as s:
        row = s.get(db.JobQueue, job_id) if job_id else None
        if row is None:
            return {"ok": False, "why": "no such job"}
        job = jobs.as_dict(row)
        payload = dict(row.payload or {})
        run = s.get(db.SystemRun, row.run_id or payload.get("run_id") or "")
        plan = dict(((run.brief or {}).get("plan")) or {}) if run is not None else {}
        run_error = str(getattr(run, "error", "") or "")
        blocked = getattr(run, "blocked_on", None) or []
    tenant, kind = job["tenant"], job["kind"]
    sk = skill_mod.get(str(payload.get("key") or "")) if kind == "system_run" else None
    what = (sk.name if sk else "") or jobs.KINDS.get(kind, {}).get("what", kind)
    inputs = {**plan, **{k: v for k, v in payload.items()
                         if k not in ("key", "trigger", "run_id", "progress")}}
    name = re.sub(r"[^a-z0-9]+", "-", f"{tenant} {what}".lower()).strip("-")[:60] or "job"

    out = ["---", f"name: {name}",
           f"description: {what} for {tenant} — a job the platform ran"
           f"{' and could not finish' if job['state'] in ('failed', 'interrupted') else ''}; "
           "everything it knew, to finish by hand", "---", "",
           f"# {what} — {tenant}", "",
           "## What happened",
           f"- job: {job['kind']}{' · ' + job['system_key'] if job['system_key'] else ''} · "
           f"{job['state']} · attempt {job['attempts']} · {str(job['at'])[:16].replace('T', ' ')}",
           f"- the platform said: {job['says']}" + (f" — {job['detail']}" if job["detail"] else "")]
    if run_error:
        out.append(f"- the error: {run_error}")
    if blocked:
        out.append(f"- what stopped it: {blocked if isinstance(blocked, str) else '; '.join(map(str, blocked))}")
    out += ["", "## Your task",
            (sk.does if sk else jobs.KINDS.get(kind, {}).get("what", kind)).rstrip(".") + ".", ""]
    if kind not in WRITES:
        out += ["This job reads or writes through the platform's own connections, so a chat cannot "
                "do it. What it was asked is below; the failure above is what to fix, or to "
                "report, before running it again.", ""]
    else:
        out += ["### What to hand back", DELIVER.get(sk.key if sk else "", "What the task names, "
                "ready to use."), "", "### The rules", RULES, ""]
    out += ["## The inputs this job was given", "```json", _json(inputs), "```", ""]
    if kind in WRITES:
        got = resolve.resolve(tenant, system=(sk.system_key if sk else ""),
                              tier=(sk.tier if sk else 3),
                              entity_key=str(inputs.get("entity_key") or ""),
                              audience_key=str(inputs.get("audience_key") or ""))
        out += ["## The context — the brand package the job reads", ""]
        for key, part in bundle.PARTS.items():
            value = (got or {}).get(key)
            if _empty(value) and key in bundle.OWNER_INPUT:
                # THE OWNER'S INPUT RIDES THE PACKAGE, as `skill.run` puts it
                # there — What's new described as facts, not buried in the JSON.
                value = inputs.get(key)
            if key in _META or _empty(value):
                continue
            out += [f"### {key} — {part.get('what', '')}", "```json", _json(value), "```", ""]
        # THE SITE'S OWN PAGES — the only places a link may go. A chat given
        # the package without them wrote an article with no links at all and
        # asked for the booking page (2026-09-28).
        from . import links as _links
        pages = [{"page": d.get("label", ""), "url": d.get("url", "")}
                 for d in _links.destinations(tenant) if d.get("url")][:150]
        if pages:
            out += ["### links — the site's own pages; link only to these", "```json",
                    _json(pages), "```", ""]
    return {"ok": True, "name": name, "markdown": "\n".join(out)}
