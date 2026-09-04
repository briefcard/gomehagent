"""The listing IS the ranking surface — the audit, as a rubric with a score.

INITIATIVE-gbp §4b: in local search the fields that move the map pack are
the primary category, the secondary categories, the services, the business
description, the hours, the photos and the reviews — none of which is a
post. `gbp_listing` sweeps the live listing through the read adapter, scores
it against this rubric, files a dated report (the Reports room on the
system's page, like every compliance check) and proposes the fixes it can
WRITE as approvals — approving one patches the profile; nothing is written
before that.

Owner, 2026-09-04: "For the audit — how are they to run and review the
results of each audit? How does it align with the overall Plan and Planned
Strategy?" The answers are structural: it runs every Monday and on demand
from the Reports room; each report is dated and lands there; the fixes
wait under "Waiting on you"; the score is the system's declared measure
(`trend`); and the report's ALIGNMENT section reads the same keyword map
the blog plans read and the same post queue the post planner fills, so a
head term the listing never says, or a cadence with no post planned, is a
finding here and a line on the Plan tab's strategy page (`latest`).

Every check is a MEASUREMENT of a field Google returned. Nothing here is a
taste; a check that cannot be pointed at is not a check.
"""
from __future__ import annotations

import re

#: What each check is worth. The weights sum to 100 so the score reads as a
#: percentage without a second number beside it.
WEIGHTS = {
    "primary_category": 15,
    "additional_categories": 10,
    "description": 15,
    "hours": 10,
    "website": 10,
    "phone": 5,
    "services": 10,
    "photos": 10,
    "reviews_answered": 10,
    "post_freshness": 5,
}
assert sum(WEIGHTS.values()) == 100

DESCRIPTION_MIN, DESCRIPTION_MAX = 250, 750
MIN_ADDITIONAL_CATEGORIES = 2
MIN_SERVICES = 3
MIN_PHOTOS = 10
ANSWERED_SHARE = 0.8
#: A post older than this reads as a stale listing. Twice the weekly
#: cadence, so one missed week is not a finding.
STALE_POST_DAYS = 14


def _host(url: str) -> str:
    u = str(url or "").strip().lower()
    u = re.sub(r"^https?://", "", u)
    u = u.split("/", 1)[0]
    return u[4:] if u.startswith("www.") else u


def _words(s: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9']+", str(s or "").lower()) if len(w) > 2]


def audit(*, listing: dict, state: dict | None, reviews: dict | None,
          posts: dict | None, media: dict | None, banned: list[str],
          keywords: list[str], entities: list, domain: str,
          open_post_plans: int, today=None) -> dict:
    """Score one listing. Pure: everything it reads is passed in.

    Returns ``{score, of, checks, gaps, fixes, alignment}``. A `fix` is a
    change this system can WRITE (a `updateMask` + `body` for
    `gbp.patch_location`); a gap it cannot write says what the owner does in
    the profile instead. Reads that were refused arrive as None and are
    scored as unknown — NOT as failing — and named as unread.
    """
    import datetime as _dt
    today = today or _dt.date.today()
    raw = dict(listing.get("raw") or {})
    checks: list[dict] = []
    fixes: list[dict] = []
    unread: list[str] = []

    def check(key, ok, what, fix=""):
        checks.append({"key": key, "ok": bool(ok), "weight": WEIGHTS[key],
                       "points": WEIGHTS[key] if ok else 0,
                       "what": what, "fix": fix})

    # --- categories ---------------------------------------------------------
    primary = str(listing.get("primary_category") or "")
    check("primary_category", bool(primary),
          f"primary category: {primary or 'NOT SET'}",
          "" if primary else "set the one category the business IS — the "
                             "single highest-leverage field on a listing")
    extra = list(listing.get("additional_categories") or [])
    check("additional_categories", len(extra) >= MIN_ADDITIONAL_CATEGORIES,
          f"{len(extra)} additional categor{'y' if len(extra) == 1 else 'ies'}"
          + (f": {', '.join(extra[:4])}" if extra else ""),
          "" if len(extra) >= MIN_ADDITIONAL_CATEGORIES else
          f"add the long tail — at least {MIN_ADDITIONAL_CATEGORIES} more "
          f"categories the business genuinely is (a venue that is only "
          f"'event venue' is invisible for 'wedding venue')")

    # --- the description --------------------------------------------------
    desc = str((raw.get("profile") or {}).get("description") or "").strip()
    low = desc.lower()
    hits = [b for b in (banned or []) if b and b.lower() in low]
    kw_named = any(all(w in low for w in _words(k)) for k in keywords if _words(k))
    desc_ok = bool(desc) and DESCRIPTION_MIN <= len(desc) <= DESCRIPTION_MAX and not hits
    what = ("no description" if not desc else
            f"{len(desc)} characters"
            + (f" — carries a banned phrase: {', '.join(hits[:2])}" if hits else "")
            + ("" if kw_named or not keywords else " — names none of the map's "
                                                    "head terms"))
    check("description", desc_ok, what,
          "" if desc_ok else
          ("write one: 250–750 characters, in the brand voice, naming the "
           "category and the place, through the ban list" if not desc else
           "rewrite it within 250–750 characters, clean against the ban list"))
    # The description is the one field a drafter writes; the skill proposes
    # it (model, gated) and files it as a fix. This module only says so.

    # --- hours --------------------------------------------------------------
    periods = list((raw.get("regularHours") or {}).get("periods") or [])
    check("hours", bool(periods),
          f"{len(periods)} opening period(s)" if periods else "no regular hours",
          "" if periods else "set the hours — a listing without them is "
                             "'may be closed' in the pack")

    # --- website ------------------------------------------------------------
    site = str(listing.get("website") or raw.get("websiteUri") or "")
    want = f"https://{_host(domain)}" if domain else ""
    site_ok = bool(site) and (not domain or _host(site) == _host(domain))
    check("website", site_ok,
          (f"website: {site}" if site else "no website on the listing")
          + ("" if site_ok or not site else f" — not the account's {_host(domain)}"),
          "" if site_ok else "point it at the account's own site")
    if not site_ok and want:
        fixes.append({"field": "websiteUri", "label": "website",
                      "updateMask": "websiteUri", "body": {"websiteUri": want},
                      "why": (f"the listing names {site!r}" if site else
                              "the listing has no website") + f"; the account's is {want}"})

    # --- phone --------------------------------------------------------------
    phone = str((raw.get("phoneNumbers") or {}).get("primaryPhone") or "")
    check("phone", bool(phone), "phone set" if phone else "no phone number",
          "" if phone else "add the number — the Call button needs it")

    # --- services -----------------------------------------------------------
    services = list(raw.get("serviceItems") or [])
    names = [str(e.name or "") for e in (entities or []) if getattr(e, "name", "")]
    check("services", len(services) >= MIN_SERVICES,
          f"{len(services)} service item(s)",
          "" if len(services) >= MIN_SERVICES else
          ("list the services — from the catalogue: " + ", ".join(names[:6])
           if names else "list at least three services"))

    # --- photos -------------------------------------------------------------
    if media is None:
        unread.append("photos")
        n_media = -1
    else:
        n_media = int(media.get("count") or 0)
    check("photos", n_media >= MIN_PHOTOS if n_media >= 0 else False,
          (f"{n_media} photo(s)" if n_media >= 0 else "photos not read"),
          "" if n_media >= MIN_PHOTOS else
          f"at least {MIN_PHOTOS} photos, exterior, interior and the product — "
          f"from the approved library")

    # --- reviews ------------------------------------------------------------
    if reviews is None:
        unread.append("reviews")
        share, total, unanswered = 0.0, 0, 0
    else:
        total = int(reviews.get("total") or 0)
        answered = int(reviews.get("answered") or 0)
        unanswered = int(reviews.get("unanswered") or 0)
        share = (answered / max(1, answered + unanswered)) if (answered + unanswered) else 1.0
    r_ok = reviews is not None and share >= ANSWERED_SHARE
    check("reviews_answered", r_ok,
          (f"{int(share * 100)}% of reviews answered ({unanswered} waiting"
           f" of {total})" if reviews is not None else "reviews not read"),
          "" if r_ok else "answer every review, in the brand voice — the "
                          "answered share is a ranking signal and a trust one")

    # --- posts: the freshness half ---------------------------------------
    last = str((posts or {}).get("last") or "") if posts is not None else ""
    age = None
    if last:
        try:
            age = (today - _dt.date.fromisoformat(last[:10])).days
        except ValueError:
            age = None
    fresh = age is not None and age <= STALE_POST_DAYS
    if posts is None:
        unread.append("posts")
    check("post_freshness", fresh,
          ("posts not read" if posts is None else
           f"last post {age} day(s) ago" if age is not None else "no post yet"),
          "" if fresh else
          (f"{open_post_plans} post(s) are planned — they keep it fresh"
           if open_post_plans else
           "nothing is planned — the post planner files one a week once the "
           "gbp_post system is on; or plan one by hand"))

    # --- alignment with the Plan ------------------------------------------
    # What the listing SAYS, for the head terms: the description, the
    # categories, the services — and the name and the address, because a
    # listing in Miami says Miami on every result without the description
    # repeating it.
    addr = dict(raw.get("storefrontAddress") or {})
    said = " ".join([desc, primary, " ".join(extra), str(listing.get("title") or ""),
                     str(addr.get("locality") or ""),
                     str(addr.get("administrativeArea") or ""),
                     " ".join(str((s.get("freeFormServiceItem") or {})
                                  .get("label", {}).get("displayName") or "")
                              for s in services if isinstance(s, dict))]).lower()
    missing = [k for k in keywords if _words(k)
               and not all(w in said for w in _words(k))]
    alignment = {"keywords": list(keywords), "missing": missing,
                 "open_post_plans": int(open_post_plans)}

    score = sum(c["points"] for c in checks)
    gaps = [c for c in checks if not c["ok"]]
    return {"score": score, "of": 100, "checks": checks, "gaps": gaps,
            "fixes": fixes, "alignment": alignment, "unread": unread,
            "live": bool((state or {}).get("live")) if state else None}


def render(report: dict, *, when: str, title: str, proposed: int) -> str:
    """The report as text. LINE 3 IS THE HEADLINE — the Reports room reads
    it as the row's summary, so the list and the document cannot disagree.
    `proposed` is how many fixes were filed as approvals, so the headline
    says what waits under 'Waiting on you'."""
    gaps = report["gaps"]
    head = (f"Score {report['score']}/{report['of']} — no gaps."
            if not gaps else
            f"Score {report['score']}/{report['of']} — {len(gaps)} gap(s), "
            f"{proposed} fix(es) proposed for approval.")
    lines = [f"Business Profile audit — {title} — {when}", "", head, ""]
    if report.get("live") is False:
        lines += ["THE LISTING IS NOT LIVE (not verified, or suspended) — "
                  "nothing below ranks until it is.", ""]
    lines.append("WHAT THE LISTING SAYS")
    for c in report["checks"]:
        lines.append(f"  [{'ok' if c['ok'] else 'GAP'}] {c['what']}"
                     + (f" — {c['fix']}" if c["fix"] else ""))
    if report.get("unread"):
        lines += ["", "NOT READ THIS SWEEP: " + ", ".join(report["unread"])
                  + " — Google refused those reads; the score treats them as gaps."]
    al = report["alignment"]
    lines += ["", "ALIGNMENT WITH THE PLAN"]
    if al["keywords"]:
        lines.append("  head terms from the keyword map: " + ", ".join(al["keywords"][:6]))
        lines.append("  the listing never says: "
                     + (", ".join(al["missing"][:6]) if al["missing"] else "— none; every head term is on the listing"))
    else:
        lines.append("  no keyword map yet — build it on the Plan tab; the "
                     "listing's description and services should say its head terms")
    lines.append(f"  posts planned: {al['open_post_plans']}"
                 + ("" if al["open_post_plans"] else
                    " — the post planner keeps the listing fresh once the "
                    "gbp_post system is on"))
    if report["fixes"]:
        lines += ["", "FIXES PROPOSED (each waits for your approval; approving writes it)"]
        for f in report["fixes"]:
            lines.append(f"  - {f['label']}: {f['why']}")
    return "\n".join(lines)


_SCORE = re.compile(r"Score (\d+)/(\d+)")


def _reports(tenant: str) -> list:
    from . import db
    with db.SessionLocal() as s:
        rows = (s.query(db.ArtifactBody)
                .filter(db.tenant_filter(db.ArtifactBody, tenant),
                        db.ArtifactBody.system_key == "gbp_listing",
                        db.ArtifactBody.format == "report")
                .order_by(db.ArtifactBody.created_at.desc()).limit(24).all())
        s.expunge_all()
    return rows


def latest(tenant: str) -> dict:
    """The newest audit, for the Plan tab: score, gaps, when, where it is."""
    rows = _reports(tenant)
    if not rows:
        return {"audited": False}
    r = rows[0]
    m = _SCORE.search(r.body or "")
    meta = dict(r.meta or {})
    return {"audited": True, "score": int(m.group(1)) if m else None,
            "of": int(m.group(2)) if m else 100,
            "gaps": int(meta.get("gaps") or 0), "fixes": int(meta.get("fixes") or 0),
            "missing": list(meta.get("missing") or []),
            "when": str(r.created_at or "")[:10], "output_id": r.output_id}


def trend(tenant: str) -> dict:
    """The score, sweep over sweep — the system's declared measure. Computed
    from the filed reports, so it cannot disagree with what was shown."""
    scores = []
    for r in _reports(tenant):
        m = _SCORE.search(r.body or "")
        if m:
            scores.append((str(r.created_at or "")[:10], int(m.group(1))))
    if not scores:
        return {"n": 0, "latest": None, "previous": None, "direction": "unmeasured"}
    latest_, previous = scores[0][1], (scores[1][1] if len(scores) > 1 else None)
    direction = ("unmeasured" if previous is None else
                 "up" if latest_ > previous else "down" if latest_ < previous else "flat")
    return {"n": len(scores), "latest": latest_, "previous": previous,
            "direction": direction, "series": scores[:12]}
