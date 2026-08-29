"""Did it work — asked of the data layer's own dimensions.

Owner, 2026-08-29: *"Make sure we leverage this data correctly when evaluating
the success on the plan tab and in the reports system that we will be
making."*

**THE POINT IS THE DIMENSION, NOT THE METRIC.** "Clicks were up" is a fact
about a month and tells nobody what to do next. "The positioning that set the
testing claim against the food-safety objection returned twice the click-rate
of the design-led one, to the same audience" is a fact about the KNOWLEDGE
BASE, and it says what to author next. Every dimension here is one the data
layer is already organised by, so a result lands on the thing that produced
it rather than beside it.

**ONE WRITER, TWO READERS.** The Plan tab renders this and the reports system
will consume the same function. A report and a console that compute the same
number twice are a report and a console that disagree by the end of the
quarter — this codebase has paid for that at least twice.

**AN UNMEASURED ROW IS NOT A ZERO.** An ad nobody has run yet did not perform
badly; it has not performed. Averaging the two together makes a new idea look
like a failed one, which is exactly backwards for the thing this exists to
encourage. Unmeasured rows are counted and named, never folded into the mean.
"""
from __future__ import annotations

from . import db

#: What a result can be grouped BY. Each is a column the data layer already
#: fills, and each answers a question somebody actually asks:
#:
#:   positioning   which IDEA worked
#:   audience      who it worked on
#:   funnel_stage  where in the journey our work pays
#:   angle         how to say it
#:   entity        what to advertise
#:   claim         which proof carries its weight — the KB's own return
#:
#: A dimension not on this list is not supported rather than silently
#: producing an empty table, because a table nobody can tell is broken is
#: worse than a refusal.
DIMENSIONS = ("positioning", "audience", "funnel_stage", "angle",
              "entity", "claim")

#: Formats whose results this can read. Ads today, because `meta_ads.match` is
#: the only join from an output to a live platform record. Named as a list
#: rather than assumed, so the day a campaign or an article gains a join the
#: change is one entry and not a rewrite.
MEASURED_FORMATS = ("ad_copy",)


def _cells(row, dim: str) -> list:
    """Which group(s) this row belongs to. A list, because one output can
    rest on several claims — an ad citing two claims is evidence about both,
    and forcing it into one loses half the signal."""
    if dim == "positioning":
        return [row.positioning] if row.positioning else []
    if dim == "audience":
        return [row.audience_key or "(no audience named)"]
    if dim == "funnel_stage":
        return [row.funnel_stage] if row.funnel_stage else []
    if dim == "angle":
        return [row.angle] if row.angle else []
    if dim == "entity":
        return [row.entity_key or "(brand-wide)"]
    if dim == "claim":
        return list(row.claim_ids or [])
    return []


def by(tenant: str, dim: str = "positioning", *,
      formats: tuple = MEASURED_FORMATS) -> dict:
    """Outcomes grouped by one dimension of the data layer.

    Returns `{dimension, groups, measured, unmeasured, note}`. `groups` is
    sorted measured-first then by click-rate, because an unmeasured group is a
    question and a measured one is an answer, and sorting them together would
    rank a thing nobody has tried above a thing that failed.
    """
    if dim not in DIMENSIONS:
        return {"dimension": dim, "groups": [], "measured": 0,
                "unmeasured": 0,
                "error": f"cannot group results by {dim!r} — the ones that "
                         f"exist are: " + ", ".join(DIMENSIONS)}

    groups: dict = {}
    measured = unmeasured = 0
    with db.SessionLocal() as s:
        rows = (s.query(db.Output)
                .filter(db.tenant_filter(db.Output, tenant),
                        db.Output.format.in_(list(formats))).all())
        for r in rows:
            m = r.outcome if isinstance(r.outcome, dict) else {}
            has = bool(m.get("impressions"))
            measured += 1 if has else 0
            unmeasured += 0 if has else 1
            for cell in _cells(r, dim):
                g = groups.setdefault(str(cell), {
                    "key": str(cell), "variants": 0, "measured": 0,
                    "impressions": 0, "clicks": 0, "spend": 0.0,
                    "grounded": []})
                g["variants"] += 1
                # GROUNDING TRAVELS WITH THE RESULT. "The ads that stood on a
                # claim did better" is the single most useful thing this can
                # say about whether the knowledge base is worth filling, and
                # it is one column away.
                if (r.grounded_pct or -1) >= 0:
                    g["grounded"].append(int(r.grounded_pct))
                if not has:
                    continue
                g["measured"] += 1
                for k in ("impressions", "clicks"):
                    g[k] += int(float(m.get(k) or 0))
                g["spend"] += float(m.get("spend") or 0)

    out = []
    for g in groups.values():
        gr = g.pop("grounded")
        g["grounded_pct"] = round(sum(gr) / len(gr)) if gr else None
        g["ctr_pct"] = (round(100 * g["clicks"] / g["impressions"], 2)
                        if g["impressions"] else None)
        g["spend"] = round(g["spend"], 2)
        out.append(g)
    out.sort(key=lambda g: (-g["measured"], -(g["ctr_pct"] or 0), g["key"]))

    return {"dimension": dim, "groups": out, "measured": measured,
            "unmeasured": unmeasured,
            "note": _note(measured, unmeasured, out)}


def _note(measured: int, unmeasured: int, groups: list) -> str:
    """One sentence saying how far this can be trusted.

    A table of two rows and a table of two hundred look identical at a glance
    and mean entirely different things, so the count travels with the numbers
    rather than being left for the reader to go and find.
    """
    if not groups:
        return ("nothing to compare yet — no ad has been matched to a live "
                "one, so there are no results to group")
    if not measured:
        return (f"{unmeasured} draft(s) and no results: run "
                f"`meta_ads.match` once the ads are live, or nothing here "
                f"will ever be more than a list of what was written")
    if measured < 8:
        return (f"only {measured} of {measured + unmeasured} have results — "
                f"read the direction, not the decimal")
    return f"{measured} of {measured + unmeasured} have results"


def scoreboard(tenant: str) -> dict:
    """Every dimension at once — the shape a report or a tab wants.

    Built as one call because both readers want the whole picture and neither
    should have to know the list of dimensions to ask for it. Adding a
    dimension therefore reaches the Plan tab and the weekly report on the same
    commit, which is the failure mode this codebase keeps closing: a thing
    added in one place and rendered in one place while the other quietly goes
    on showing last month's set.
    """
    return {d: by(tenant, d) for d in DIMENSIONS}


def headline(tenant: str) -> str:
    """The one line worth putting at the top, or an honest absence.

    Names the BEST-PERFORMING POSITIONING against the next one, because a
    winner with nothing to beat is not a finding. Returns "" rather than a
    hedge when there is nothing to say — a report that manufactures a
    sentence every week teaches people to skip the first paragraph.
    """
    got = by(tenant, "positioning")
    ranked = [g for g in got["groups"] if g["measured"] and g["ctr_pct"]]
    if len(ranked) < 2:
        return ""
    best, second = ranked[0], ranked[1]
    if best["ctr_pct"] <= second["ctr_pct"]:
        return ""
    lift = round(best["ctr_pct"] / second["ctr_pct"], 1) if second["ctr_pct"] else 0
    return (f"“{best['key']}” is the positioning that worked: {best['ctr_pct']}% "
            f"click-rate over {best['measured']} ad(s), "
            + (f"{lift}× " if lift and lift > 1 else "")
            + f"the {second['ctr_pct']}% of “{second['key']}”.")
