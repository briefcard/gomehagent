"""The keyword map: which phrases this account intends to rank for, and why that one next.

The gap this closes, in the owner's words (2026-08-25): a plan *"to rank
effectively in both long tailed and short tailed keywords ... able to be
verified against to show progress and ranking changes"*.

`systems.CATALOG["blog"]` has said "publishes grounded articles against the
keyword map" since it was written, and the keyword map was a phrase with no
implementation. What existed was `SeoSnapshot` — the top 50 keywords BY TRAFFIC
SHARE for a domain — which cannot answer the only question that matters here,
because a phrase you are TARGETING and do not yet rank for has no row in it.

Three things this module is, and one it is not:

* **Deterministic.** Tier, intent, cluster and priority are computed from data
  with thresholds written down. No model call. Which keyword to write next is
  catalogue arithmetic, not judgement, and the same reasoning that keeps
  `planner.py` model-free applies harder here: a ranking nobody can argue with
  is a ranking nobody can correct.
* **Two-level.** A head term is never targeted with an article. It is targeted
  with a PILLAR page and the long-tail SUPPORTS that link into it. `cluster_key`
  and `role` are that mechanism, which is what makes "rank for short-tail" a
  countable build instead of a hope.
* **Honest about what it does not know.** An absent KD scores neither penalty
  nor bonus; an absent reading is not position zero. The failure this avoids is
  the one where every unmeasured keyword sorts to the top.

It is NOT the measurement loop. Recording readings lives here because the GSC
harvest produces them on its way past; reading them back into a progress report
against a declared goal is Phase 3.
"""
from __future__ import annotations

import json
import math
import re

from . import db

# ---------------------------------------------------------------------------
# Tier — computed, with per-account thresholds
# ---------------------------------------------------------------------------
#
# A local venue's head term and a national e-commerce brand's are different
# volumes by an order of magnitude, and one global constant would file the
# whole of Ironside's map as long-tail. Keyed on `Tenant.business_model`, which
# `metrics.OUTCOMES` already uses for the same reason, and overridable per
# account through `Tenant.analytics` so a number nobody can change is not the
# only number available.
TIER_DEFAULTS: dict[str, dict] = {
    "local_venue":      {"head_volume": 300},
    "b2b_spec":         {"head_volume": 500},
    "digital_products": {"head_volume": 1000},
    "ecom_inventory":   {"head_volume": 2000},
}
GENERIC_THRESHOLDS = {"head_volume": 800}

#: Words that carry no topic. Used for tokenising, clustering and question
#: detection — one list, because three would drift.
STOPWORDS = frozenset("""
a an the and or but of for to in on at by with from as is are was were be been
your you my our their its it this that these those i we they he she
""".split())

_QUESTION_STARTS = frozenset("""
who what when where why how which can could do does did is are should will
would may might
""".split())


def thresholds_for(tenant: str) -> dict:
    """Tier thresholds for one account: business_model default, then override."""
    from . import tenants
    t = tenants.get(tenant)
    model = (getattr(t, "business_model", "") or "").strip()
    out = dict(TIER_DEFAULTS.get(model) or GENERIC_THRESHOLDS)
    for k, v in (getattr(t, "analytics", None) or {}).items():
        if k in out:
            try:
                out[k] = int(v)
            except (TypeError, ValueError):
                pass          # a typo must not silently retier the whole map
    return out


def _stem(word: str) -> str:
    """Crudest useful singulariser — enough for keyword sets, and no more.

    Clustering compared exact tokens and "acrylic jug" therefore did not
    contain "are acrylic jugs dishwasher safe", which is the single most
    common variation in any keyword set. A real stemmer is not wanted here: it
    would also fold "designs" into "design" and "designer" into the same
    bucket, and the map would silently merge two different intents.

    The `ss` guard is why this is a function and not a `rstrip("s")` —
    "glass", "dress" and "business" are not plurals of anything.
    """
    if len(word) <= 3 or word.endswith("ss"):
        return word
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("es") and len(word) > 4 and word[-3] in "sxzho":
        return word[:-2]
    return word[:-1] if word.endswith("s") else word


def tokens(phrase: str) -> list[str]:
    """Content words, lowercased and singularised. The basis for clustering."""
    words = re.findall(r"[a-z0-9']+", (phrase or "").lower())
    return [_stem(w) for w in words if w not in STOPWORDS]


def is_question(phrase: str) -> bool:
    p = (phrase or "").strip().lower()
    if "?" in p:
        return True
    first = re.findall(r"[a-z']+", p)
    return bool(first) and first[0] in _QUESTION_STARTS


def classify_tier(phrase: str, volume: int = 0, *, head_volume: int = 800) -> str:
    """head | body | long_tail, from shape first and volume second.

    Shape leads because it is the thing that does not move: a five-word
    question is long-tail whatever its volume this month. Volume only decides
    whether a SHORT phrase is genuinely a head term — "acrylic jug" at 40
    searches is not a head term, it is a body term nobody searches, and calling
    it head would put a pillar page behind it.
    """
    words = re.findall(r"[a-z0-9']+", (phrase or "").lower())
    if not words:
        return "long_tail"
    if len(words) >= 5 or is_question(phrase):
        return "long_tail"
    if len(words) <= 2 and int(volume or 0) >= head_volume:
        return "head"
    return "body"


# ---------------------------------------------------------------------------
# Intent — markers, in precedence order
# ---------------------------------------------------------------------------
#
# Ordered, and the order is the rule: "best acrylic jug price" is
# transactional, not commercial, because the money word wins. Checked as whole
# words so "cheap" does not fire inside "cheaper" by accident of substring.
INTENT_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("transactional", ("buy", "price", "prices", "pricing", "cost", "quote",
                       "hire", "rent", "rental", "book", "booking", "order",
                       "shop", "sale", "discount", "cheap", "deal", "deals",
                       "near me", "for sale", "how much")),
    ("commercial", ("best", "top", "vs", "versus", "review", "reviews",
                    "compare", "comparison", "alternative", "alternatives",
                    "brands")),
    ("informational", ("how", "what", "why", "when", "guide", "ideas", "tips",
                       "examples", "types", "meaning", "difference")),
)


def classify_intent(phrase: str, brand_tokens: set[str] | None = None) -> str:
    """What the searcher wants. Brand terms are navigational — you already rank
    for your own name, and scoring those beside real demand would put the
    easiest wins with the least value at the top of the plan."""
    p = f" {(phrase or '').lower()} "
    words = set(re.findall(r"[a-z0-9']+", p))
    if brand_tokens and (words & brand_tokens):
        return "navigational"
    for label, markers in INTENT_MARKERS:
        for m in markers:
            if " " in m:
                if m in p:
                    return label
            elif m in words:
                return label
    return "informational"


def brand_tokens_for(tenant: str) -> set[str]:
    """Words that name this brand — from the tenant name and its domain."""
    from . import tenants
    t = tenants.get(tenant)
    if not t:
        return set()
    host = (getattr(t, "domain", "") or "").split(".")[0]
    words = tokens(getattr(t, "name", "") or "") + tokens(host) + [tenant]
    return {w for w in words if len(w) > 2}


# ---------------------------------------------------------------------------
# Writing the map
# ---------------------------------------------------------------------------
#: Fields a harvester owns. Everything else on the row is the PLAN, and a
#: re-harvest never touches it — the same carry-forward rule `open_plan` uses,
#: for the same reason: a planner that overwrites the owner produces a plan
#: nobody wrote.
_HARVEST_FIELDS = ("database", "volume", "difficulty", "cpc", "source")


def upsert(tenant: str, phrase: str, *, volume: int = 0, difficulty=None,
           cpc: float = 0.0, source: str = "", database: str = "",
           **plan) -> db.KeywordTarget:
    """File or refresh one keyword. Idempotent per (tenant, phrase).

    A second harvest of the same phrase refreshes its metrics and re-derives
    its tier; it does not reset status, cluster, role or target_url. Metrics
    move week to week and the plan does not.
    """
    phrase = (phrase or "").strip()
    if not phrase:
        raise ValueError("a keyword needs a phrase")
    th = thresholds_for(tenant)
    brand = brand_tokens_for(tenant)
    with db.SessionLocal() as s:
        row = (s.query(db.KeywordTarget)
               .filter(db.KeywordTarget.tenant == tenant,
                       db.KeywordTarget.phrase == phrase).first())
        if row is None:
            row = db.KeywordTarget(tenant=tenant, phrase=phrase)
            s.add(row)
        if volume:
            row.volume = int(volume)
        # `is not None` and not truthiness: KD 0 is a real, easy keyword and
        # collapsing it into "unknown" is DEFECTS §1's "unknown collapsed into
        # a value" the other way round.
        if difficulty is not None:
            row.difficulty = float(difficulty)
        if cpc:
            row.cpc = float(cpc)
        if source and not row.source:
            row.source = source        # first finder keeps the credit
        if database:
            row.database = database
        row.tier = classify_tier(phrase, row.volume or 0,
                                 head_volume=th["head_volume"])
        row.intent = classify_intent(phrase, brand)
        for k, v in plan.items():
            if hasattr(row, k) and v not in (None, ""):
                setattr(row, k, v)
        s.commit()
        s.refresh(row)
        s.expunge(row)
    return row


#: What an owner may say about a keyword that the score cannot work out.
OWNER_PRIORITIES = ("", "pinned", "muted")


def set_priority(tenant: str, phrase: str, mode: str) -> dict:
    """Pin a keyword above the arithmetic, mute it out of the queue, or clear."""
    mode = (mode or "").strip().lower()
    if mode not in OWNER_PRIORITIES:
        return {"error": f"unknown priority {mode!r}. Use pinned, muted, or "
                         f"blank to clear."}
    with db.SessionLocal() as s:
        row = (s.query(db.KeywordTarget)
               .filter(db.KeywordTarget.tenant == tenant,
                       db.KeywordTarget.phrase == phrase).first())
        if row is None:
            return {"error": f"{phrase!r} is not in this account's map"}
        row.owner_priority = mode
        s.commit()
    return {"ok": True, "phrase": phrase, "owner_priority": mode or "cleared"}


def _owner_sort(rows: list) -> list:
    """Pinned first, muted last, the arithmetic in between.

    A separate sort key rather than a bonus added to the score, deliberately:
    a bonus large enough to always win is indistinguishable from a bug, and a
    small one gets outvoted by striking distance the week a page moves. An
    override that can be outvoted is not an override.
    """
    order = {"pinned": 0, "": 1, "muted": 2}
    return sorted(rows, key=lambda r: (order.get(r.owner_priority or "", 1),
                                       -(r.priority or 0)))


def targets(tenant: str, *, tier: str = "", status: str = "",
            cluster_key: str = "") -> list[db.KeywordTarget]:
    with db.SessionLocal() as s:
        q = s.query(db.KeywordTarget).filter(db.KeywordTarget.tenant == tenant)
        if tier:
            q = q.filter(db.KeywordTarget.tier == tier)
        if status:
            q = q.filter(db.KeywordTarget.status == status)
        if cluster_key:
            q = q.filter(db.KeywordTarget.cluster_key == cluster_key)
        rows = q.order_by(db.KeywordTarget.priority.desc()).all()
        for r in rows:
            s.expunge(r)
        return _owner_sort(rows)


# ---------------------------------------------------------------------------
# Clusters — the mechanism that makes a head term winnable
# ---------------------------------------------------------------------------
def slug(phrase: str) -> str:
    return "-".join(tokens(phrase))[:120] or "misc"


def cluster(tenant: str) -> dict:
    """Group the map into pillars and their supports.

    Head and body terms become PILLARS. A long-tail joins the pillar whose
    content words it CONTAINS — "how to clean an acrylic jug" contains
    "acrylic jug" — and among several, the most specific (most words) wins,
    because that is the page it should link to. A long-tail matching nothing
    becomes its own pillar: it has to carry itself, and saying so is better
    than filing it under a cluster it does not belong to.

    **Only `candidate` rows are re-assigned.** Once a keyword is planned or
    published its cluster is settled — recomputing it would move a published
    article's internal links out from under it, and an owner who reassigned one
    by hand would find it moved back on the next run.
    """
    rows = targets(tenant)
    pillars = [r for r in rows if r.tier in ("head", "body")]
    pillars.sort(key=lambda r: len(tokens(r.phrase)), reverse=True)
    moved, made_pillar = 0, 0
    with db.SessionLocal() as s:
        for r in rows:
            row = s.get(db.KeywordTarget, r.id)
            # SETTLED means "already assigned AND past candidate". The first
            # version skipped on status alone, which left every keyword
            # published before the map existed permanently unclustered — and
            # an unclustered pillar is invisible to `cluster_state`, so the
            # bonus for finishing its cluster could never fire. Protecting a
            # plan is not the same as refusing to make one.
            if row.cluster_key and row.status != "candidate":
                continue
            if r.tier in ("head", "body"):
                row.cluster_key, row.role = slug(r.phrase), "pillar"
                moved += 1
                continue
            mine = set(tokens(r.phrase))
            hit = next((p for p in pillars
                        if p.id != r.id and set(tokens(p.phrase)) <= mine), None)
            if hit:
                row.cluster_key, row.role = slug(hit.phrase), "support"
            else:
                row.cluster_key, row.role = slug(r.phrase), "pillar"
                made_pillar += 1
            moved += 1
        s.commit()
    return {"assigned": moved, "orphan_pillars": made_pillar,
            "clusters": len({r.cluster_key for r in targets(tenant) if r.cluster_key})}


def cluster_state(tenant: str) -> dict[str, dict]:
    """Per cluster: how many supports exist, how many are published, and
    whether the pillar is. This is what `score` reads to prefer FINISHING a
    cluster over starting one — a cluster half-built is the most common way
    this work produces nothing."""
    out: dict[str, dict] = {}
    for r in targets(tenant):
        if not r.cluster_key:
            continue
        c = out.setdefault(r.cluster_key, {"supports": 0, "supports_published": 0,
                                           "pillar_published": False,
                                           "pillar": ""})
        done = r.status in ("published", "won")
        if r.role == "pillar":
            c["pillar"] = r.phrase
            c["pillar_published"] = done
        else:
            c["supports"] += 1
            c["supports_published"] += 1 if done else 0
    return out


# ---------------------------------------------------------------------------
# Readings — the series everything is verified against
# ---------------------------------------------------------------------------
def record_reading(tenant: str, phrase: str, *, source: str = "gsc",
                   position=None, impressions: int = 0, clicks: int = 0,
                   ctr: float = 0.0, url: str = "", database: str = "") -> str:
    """One observation. `position=None` means NOT RANKING, which is a fact and
    not a zero — a zero here would read as position 0, the best rank there is."""
    with db.SessionLocal() as s:
        row = db.KeywordReading(
            tenant=tenant, phrase=(phrase or "").strip(), source=source,
            position=float(position) if position is not None else None,
            impressions=int(impressions or 0), clicks=int(clicks or 0),
            ctr=float(ctr or 0.0), url=url or "", database=database or "")
        s.add(row)
        s.commit()
        return row.id


def latest_reading(tenant: str, phrase: str, source: str = "gsc"):
    with db.SessionLocal() as s:
        row = (s.query(db.KeywordReading)
               .filter(db.KeywordReading.tenant == tenant,
                       db.KeywordReading.phrase == phrase,
                       db.KeywordReading.source == source)
               .order_by(db.KeywordReading.at.desc()).first())
        if row is not None:
            s.expunge(row)
        return row


def _latest_positions(tenant: str, source: str = "gsc") -> dict[str, float]:
    """phrase -> most recent position, in ONE query.

    `score` needs this for every row, and asking per keyword turned a ranking
    of two hundred phrases into two hundred round trips.
    """
    out: dict[str, float] = {}
    seen: set[str] = set()
    with db.SessionLocal() as s:
        for r in (s.query(db.KeywordReading)
                  .filter(db.KeywordReading.tenant == tenant,
                          db.KeywordReading.source == source)
                  .order_by(db.KeywordReading.at.desc()).all()):
            if r.phrase in seen:
                continue
            seen.add(r.phrase)
            if r.position is not None:
                out[r.phrase] = r.position
    return out


# ---------------------------------------------------------------------------
# Priority — which keyword to write next, and the arithmetic behind it
# ---------------------------------------------------------------------------
#
# Every weight here is a decision somebody can disagree with, so they are
# constants with reasons rather than numbers inside an expression.

#: Striking distance. Page two is the biggest single lever in the map: the page
#: already ranks, Google already considers it relevant, and the work is an
#: improvement rather than an introduction. Positions 1-3 score ZERO — they are
#: won, and re-writing a page that already ranks is how a site loses the
#: position it had.
STRIKING = ((0, 3, 0.0), (3, 10, 40.0), (10, 20, 60.0), (20, 50, 20.0),
            (50, 10_000, 5.0))

#: Finishing a cluster beats starting one. A pillar only ranks once its
#: supports exist, and a support only pays once its pillar does.
CLUSTER_SUPPORT_OF_PUBLISHED_PILLAR = 25.0
CLUSTER_PILLAR_WITH_PUBLISHED_SUPPORTS = 20.0

#: Demand, compressed. Volume is long-tailed enough that raw numbers would let
#: one head term outweigh a whole cluster of buyable long-tails.
DEMAND_WEIGHT = 10.0
INTENT_WEIGHT = {"transactional": 1.4, "commercial": 1.2,
                 "informational": 1.0, "navigational": 0.4}

#: Difficulty, applied ONLY when it is known. An absent KD scores nothing in
#: either direction — treating unknown as zero would sort every unmeasured
#: keyword to the top, which is the failure this whole module is written
#: against.
DIFFICULTY_WEIGHT = 25.0


def _striking_points(position) -> float:
    if position is None:
        return 0.0
    for lo, hi, pts in STRIKING:
        if lo < position <= hi:
            return pts
    return 0.0


def score(tenant: str) -> dict:
    """Rank every candidate, store the score AND its components.

    The components are stored because a ranking that cannot be argued with
    cannot be corrected. `priority_parts` is what the console shows when
    somebody asks why this keyword and not that one.
    """
    positions = _latest_positions(tenant)
    clusters = cluster_state(tenant)
    ranked = []
    with db.SessionLocal() as s:
        for row in (s.query(db.KeywordTarget)
                    .filter(db.KeywordTarget.tenant == tenant).all()):
            parts: dict = {}
            pos = positions.get(row.phrase)
            parts["striking"] = _striking_points(pos)
            parts["position"] = pos if pos is not None else "no reading"

            c = clusters.get(row.cluster_key or "", {})
            bonus = 0.0
            if row.role == "support" and c.get("pillar_published"):
                bonus = CLUSTER_SUPPORT_OF_PUBLISHED_PILLAR
            elif row.role == "pillar" and c.get("supports_published"):
                bonus = CLUSTER_PILLAR_WITH_PUBLISHED_SUPPORTS
            parts["cluster"] = bonus

            weight = INTENT_WEIGHT.get(row.intent, 1.0)
            parts["demand"] = round(
                math.log10((row.volume or 0) + 1) * DEMAND_WEIGHT * weight, 1)

            if row.difficulty is None:
                parts["difficulty"] = "unknown — no penalty, no credit"
                penalty = 0.0
            else:
                penalty = round(row.difficulty / 100.0 * DIFFICULTY_WEIGHT, 1)
                parts["difficulty"] = -penalty

            row.priority = round(parts["striking"] + parts["cluster"]
                                 + parts["demand"] - penalty, 1)
            row.priority_parts = parts
            ranked.append((row.priority, row.phrase))
        s.commit()
    ranked.sort(reverse=True)
    return {"scored": len(ranked), "top": ranked[:10]}


# ---------------------------------------------------------------------------
# Harvest — four sources, each answering a different question
# ---------------------------------------------------------------------------
#
# The four fetches are MODULE-LEVEL SEAMS, replaced wholesale by the offline
# suite. Everything interesting here is what happens to the rows after they
# arrive, and a pipeline that can only be tested against a live Semrush key is
# a pipeline nobody runs twice.

def _json_rows(raw) -> list[dict]:
    """Every tool in `seo_tools` / `google_seo` returns JSON on success and a
    SENTENCE on failure. Parsing defensively is not paranoia — it is the
    documented contract."""
    if isinstance(raw, list):
        return raw
    try:
        out = json.loads(raw)
    except (ValueError, TypeError):
        return []
    return out if isinstance(out, list) else []


def _fetch_gsc(profile: dict, days: int, limit: int) -> list[dict]:
    from . import google_seo
    return _json_rows(google_seo.gsc_top_queries(profile, days=days, limit=limit))


def _fetch_related(profile: dict, phrase: str, limit: int) -> list[dict]:
    from . import seo_guard, seo_tools
    return _json_rows(seo_tools.semrush_related_keywords(
        phrase, database=profile.get("database", ""), limit=limit,
        _tenant=seo_guard.tenant_for(profile)))


def _fetch_questions(profile: dict, phrase: str, limit: int) -> list[dict]:
    from . import seo_guard, seo_tools
    return _json_rows(seo_tools.semrush_questions(
        phrase, database=profile.get("database", ""), limit=limit,
        _tenant=seo_guard.tenant_for(profile)))


def _fetch_own(profile: dict, limit: int) -> list[dict]:
    """What this domain ALREADY ranks for, at any position.

    The bootstrap source, and its absence was a dead end the owner walked
    straight into: a brand-new account has no GSC history to read and
    `_fetch_gap` only looks at positions 11-30, so a first harvest could
    return nothing at all — and then `related` and `questions` had no seeds,
    because seeds come from head terms the empty map does not have. The run
    said "no seeds and no head terms yet — run with sources=('gsc','gap')
    first", which is exactly what had just been run. A refusal that instructs
    you to do the thing you did is worse than one that says nothing.

    Miami Ironside has 1,098 organic keywords in Semrush. Every one of them
    was invisible to this module.
    """
    from . import seo_guard, seo_tools
    return _json_rows(seo_tools.semrush_top_keywords(
        domain=profile.get("domain", ""), database=profile.get("database", ""),
        limit=limit, _tenant=seo_guard.tenant_for(profile)))


def _fetch_gap(profile: dict, limit: int) -> list[dict]:
    """Where the site already ranks but not well — Semrush's own
    striking-distance report, which is the market's view of the same question
    `_fetch_gsc` answers from your own data."""
    from . import seo_guard, seo_tools
    return _json_rows(seo_tools.semrush_opportunity_finder(
        domain=profile.get("domain", ""), database=profile.get("database", ""),
        limit=limit, exclude_terms=profile.get("exclude_terms") or [],
        _tenant=seo_guard.tenant_for(profile)))


def _fetch_serp(profile: dict, phrase: str, limit: int) -> list[dict]:
    """The rivals holding one phrase. The fifth seam, and the only one that is
    charged PER PHRASE rather than per account — which is why every caller of
    it goes through a cap."""
    from . import seo_guard, seo_tools
    return _json_rows(seo_tools.semrush_serp_rivals(
        phrase, database=profile.get("database", ""), limit=limit,
        _tenant=seo_guard.tenant_for(profile)))


#: Most seeds one harvest will expand, whoever asked. Each costs two Semrush
#: reports, so this is the difference between a bounded top-up and a bill.
MAX_SEEDS = 8

#: GSC positions worth harvesting as targets. Below 3 is won; past 40 the
#: query is not really about this site yet.
STRIKING_BAND = (3.0, 40.0)


def harvest(tenant: str, *, seeds: tuple = (), sources: tuple = (
        "gsc", "own", "gap", "related", "questions"), days: int = 28,
        limit: int = 40) -> dict:
    """Build or top up the map. Returns what each source contributed.

    Per-source counts rather than a total, because the four are not
    interchangeable and their yields should be comparable — a source that
    never produces a win is one to stop spending API calls on.
    """
    from . import sites
    profile = sites.get(tenant)
    added: dict[str, int] = {s: 0 for s in sources}
    notes: list[str] = []

    excl = [t for t in (profile.get("exclude_terms") or []) if t]

    def _excluded(phrase: str) -> bool:
        """The exclude list binds EVERY source, not just the gap fetch.

        `semrush_opportunity_finder` filtered server-side and the other four
        sources did not, so accepting a mute-lesson term stopped one entrance
        of five — the excluded family kept arriving via the domain's own
        rankings, GSC, related and questions, and the owner's accepted
        decision looked ignored.
        """
        low = f" {phrase.lower()} "
        return any(f" {t} " in low or t in phrase.lower() for t in excl)

    if "gsc" in sources:
        for r in _fetch_gsc(profile, days, limit * 3):
            phrase, pos = r.get("query"), r.get("position")
            if not phrase:
                continue
            # The reading is filed WHATEVER the position — the series is worth
            # more than the target, and a phrase outside the band today is one
            # whose movement we still want to see.
            record_reading(tenant, phrase, source="gsc", position=pos,
                           impressions=r.get("impressions", 0),
                           clicks=r.get("clicks", 0), ctr=r.get("ctr", 0.0))
            if (pos is not None and not _excluded(phrase)
                    and STRIKING_BAND[0] < pos <= STRIKING_BAND[1]):
                upsert(tenant, phrase, source="gsc_striking",
                       database=profile.get("database", ""))
                added["gsc"] += 1

    if "own" in sources:
        for r in _fetch_own(profile, limit):
            phrase = r.get("keyword") or r.get("Keyword")
            if not phrase or _excluded(phrase):
                continue
            upsert(tenant, phrase, source="semrush_own",
                   volume=int(float(r.get("volume") or 0)),
                   cpc=float(r.get("cpc") or 0.0),
                   database=profile.get("database", ""))
            added["own"] += 1

    if "gap" in sources:
        for r in _fetch_gap(profile, limit):
            phrase = r.get("keyword") or r.get("Keyword")
            if not phrase:
                continue
            upsert(tenant, phrase, source="semrush_gap",
                   volume=int(r.get("volume") or 0),
                   database=profile.get("database", ""))
            added["gap"] += 1

    # Related and questions EXPAND a seed, so they need seeds. Falling back to
    # the head terms already in the map makes the second run of `harvest`
    # deepen what the first found, rather than needing a person each time.
    if {"related", "questions"} & set(sources):
        # THE CAP BINDS BOTH BRANCHES. It used to sit on the fallback only —
        # `list(seeds) or [...][:8]` — so the eight applied to the phrases this
        # module chose for itself and not to the ones a caller passed. Since
        # `GET /admin/keywords_harvest?seeds=` builds that tuple straight from
        # a query string with no length of its own, a hand-typed URL was an
        # unbounded per-seed loop: 2 reports x N seeds x up to 200 lines each,
        # synchronous, in one request. The route's docstring already warned
        # that "one URL doing both is one somebody refreshes into a Semrush
        # bill" — it separated the routes and left the count open.
        pool = (list(seeds) or [r.phrase for r in targets(tenant)
                                if r.tier in ("head", "body")])[:MAX_SEEDS]
        if not pool:
            # Names what is actually missing rather than the command that was
            # just run. If `own` and `gap` both came back empty there is
            # nothing wrong with the sources — the domain has no Semrush
            # presence yet, and expansion has nothing to expand.
            notes.append(
                "nothing to expand from: Search Console returned no queries "
                "and Semrush found no keywords for this domain, so there are "
                "no head terms to seed related-and-questions with. Either the "
                "site is too new to have either, or the domain on this "
                "account is wrong. You can also pass seeds= to start from "
                "phrases you already know.")
        for seed in pool:
            if "related" in sources:
                for r in _fetch_related(profile, seed, limit):
                    if r.get("keyword") and not _excluded(r["keyword"]):
                        upsert(tenant, r["keyword"], source="semrush_related",
                               volume=int(r.get("volume") or 0),
                               cpc=float(r.get("cpc") or 0.0),
                               database=profile.get("database", ""))
                        added["related"] += 1
            if "questions" in sources:
                for r in _fetch_questions(profile, seed, limit):
                    if r.get("question") and not _excluded(r["question"]):
                        upsert(tenant, r["question"], source="semrush_questions",
                               volume=int(r.get("volume") or 0),
                               database=profile.get("database", ""))
                        added["questions"] += 1

    grouped = cluster(tenant)
    ranked = score(tenant)
    return {"tenant": tenant, "added": added, **grouped,
            "scored": ranked["scored"], "top": ranked["top"], "notes": notes}


def map_for(tenant: str) -> dict:
    """The map as somebody reads it: clusters, each with its pillar, its
    supports and how far through it is."""
    state = cluster_state(tenant)
    rows = targets(tenant)
    by_cluster: dict[str, list] = {}
    for r in rows:
        by_cluster.setdefault(r.cluster_key or "(unclustered)", []).append(r)
    out = []
    for key, members in by_cluster.items():
        members.sort(key=lambda r: (-(r.priority or 0), r.phrase))
        st = state.get(key, {})
        out.append({
            "cluster": key, "pillar": st.get("pillar", ""),
            "pillar_published": st.get("pillar_published", False),
            "supports": st.get("supports", 0),
            "supports_published": st.get("supports_published", 0),
            "keywords": [{"phrase": r.phrase, "tier": r.tier, "intent": r.intent,
                          "role": r.role, "status": r.status,
                          "volume": r.volume, "priority": r.priority}
                         for r in members]})
    out.sort(key=lambda c: -max((k["priority"] or 0) for k in c["keywords"]))
    counts: dict[str, int] = {}
    for r in rows:
        counts[r.tier] = counts.get(r.tier, 0) + 1
    return {"tenant": tenant, "keywords": len(rows), "by_tier": counts,
            "clusters": out}


# ---------------------------------------------------------------------------
# The measurement loop — what actually moved, and whether we can say why
# ---------------------------------------------------------------------------
#
# EVERY READING IS A WINDOW, NOT A DAY. A GSC row is an aggregate over its
# lookback, so two readings taken a fortnight apart are two overlapping 28-day
# windows — and SUMMING readings across syncs would count the same clicks
# several times. `progress` therefore compares the LATEST reading in each
# period rather than a total of them, which is the only arithmetic the data
# supports.

#: A tracked phrase at this position or better is `won`. Derived from readings
#: on every sync, in BOTH directions — a win that has been lost is not a win,
#: and a status that only ever ratchets upward is a status that lies.
WON_POSITION = 3.0

#: How long before a position change may be discussed beside a publish date.
#: Under this, `progress` reports the movement and withholds the attribution:
#: Google has not settled, and a fortnight-old article that jumped is a
#: coincidence until it holds.
ATTRIBUTION_DAYS = 14


def sync(tenant: str, *, days: int = 28, limit: int = 1000) -> dict:
    """Refresh readings from Search Console, then re-settle what is `won`.

    ONE CALL, matched locally. GSC will return thousands of rows in a single
    request and asking per phrase would spend the quota on a fortnight of
    checks. Phrases the API does not return get NO reading rather than a
    null one: absent from a truncated top-N is not the same fact as "not
    ranking", and writing the second when we only know the first is how a
    report acquires a number nobody can defend.
    """
    from . import sites
    profile = sites.get(tenant)
    rows = _fetch_gsc(profile, days, limit)
    tracked = {r.phrase for r in targets(tenant)}
    seen = 0
    for r in rows:
        phrase = r.get("query")
        if not phrase:
            continue
        record_reading(tenant, phrase, source="gsc", position=r.get("position"),
                       impressions=r.get("impressions", 0),
                       clicks=r.get("clicks", 0), ctr=r.get("ctr", 0.0))
        seen += 1
    settled = settle(tenant)
    # RE-SCORE, because the readings that just landed ARE the biggest input to
    # priority. Striking distance is worth up to 60 points and is read from the
    # latest position; without this the nightly sync updated every position and
    # left yesterday's ranking in place, so a keyword that moved 25 -> 14
    # overnight — the single best thing to write next — kept its old score
    # until somebody happened to press Re-score. The loop was broken at exactly
    # the point it was supposed to be tightest.
    ranked = score(tenant)
    return {"tenant": tenant, "readings": seen,
            "tracked_with_data": len(tracked & {r.get("query") for r in rows}),
            "tracked_without_data": len(tracked - {r.get("query") for r in rows}),
            "rescored": ranked["scored"], "top": ranked["top"][:5],
            **settled}


def settle(tenant: str) -> dict:
    """Set `won` from the readings, up AND down."""
    positions = _latest_positions(tenant)
    won, lost = 0, 0
    with db.SessionLocal() as s:
        for row in (s.query(db.KeywordTarget)
                    .filter(db.KeywordTarget.tenant == tenant).all()):
            pos = positions.get(row.phrase)
            if pos is None:
                continue
            # THE MARK IS RECORDED FOR ANY PAGE THAT IS WINNING, not only for
            # one that just started to. It was nested inside the transition —
            # `status in ("published", "planned")` — which a row already at
            # `won` cannot enter, so a page that was winning before `won_at`
            # existed, or that was marked `won` by any other path, never got
            # one. It then slipped, `settle` walked it back to `published`,
            # and it read as a page that had never ranked at all: the two owe
            # different work, and the more urgent one was invisible.
            if pos <= WON_POSITION and row.status in ("published", "planned",
                                                      "won"):
                if row.status != "won":
                    row.status, won = "won", won + 1
                # The HIGH-WATER MARK, set once and never cleared. `settle`
                # walks a page back to `published` as soon as it slips, so
                # this is the only thing that can tell "it ranked and stopped"
                # from "it never ranked".
                if row.won_at is None:
                    row.won_at = db.utcnow()
            elif pos > WON_POSITION and row.status == "won":
                row.status, lost = "published", lost + 1
        s.commit()
    return {"won": won, "lost": lost}


def _period_readings(tenant: str, days: int) -> tuple[dict, dict]:
    """(now, then) — the latest reading per phrase inside the window, and the
    latest before it. `then` is what makes a delta possible at all."""
    import datetime as dt
    cutoff = db.utcnow() - dt.timedelta(days=days)
    now: dict[str, db.KeywordReading] = {}
    then: dict[str, db.KeywordReading] = {}
    with db.SessionLocal() as s:
        for r in (s.query(db.KeywordReading)
                  .filter(db.KeywordReading.tenant == tenant,
                          db.KeywordReading.source == "gsc")
                  .order_by(db.KeywordReading.at.desc()).all()):
            # Through `db.as_utc`, always: SQLite drops the timezone even on a
            # DateTime(timezone=True) column while Postgres keeps it, so a bare
            # comparison works in production and raises the moment it runs
            # locally. The helper exists for exactly this and is the reason
            # this is not a fourth hand-rolled `_aware`.
            at = db.as_utc(r.at)
            bucket = now if at and at >= cutoff else then
            bucket.setdefault(r.phrase, r)
    return now, then


def _readings_astride(tenant: str, when: dict) -> tuple[dict, dict]:
    """Per phrase: the latest reading BEFORE its own moment, and after it.

    `_period_readings` splits on ONE cutoff for the whole account, which is
    right for "what moved this month" and wrong for "did refreshing work". A
    page refreshed 10 days into a 28-day window compared now-against-28-days-
    ago folds 18 days of PRE-refresh drift into the answer and calls it the
    refresh's doing. The split has to be each page's own refresh date.
    """
    before: dict[str, db.KeywordReading] = {}
    after: dict[str, db.KeywordReading] = {}
    if not when:
        return before, after
    with db.SessionLocal() as s:
        rows = (s.query(db.KeywordReading)
                .filter(db.KeywordReading.tenant == tenant,
                        db.KeywordReading.source == "gsc",
                        db.KeywordReading.phrase.in_(list(when)))
                .order_by(db.KeywordReading.at.desc()).all())
    for r in rows:
        at = db.as_utc(r.at)
        split = when.get(r.phrase)
        if at is None or split is None:
            continue
        (after if at >= split else before).setdefault(r.phrase, r)
    return before, after


def refresh_effect(tenant: str, *, days: int = 90) -> dict:
    """Did refreshing work — and can we honestly say it was the refresh.

    THE WHOLE LANE RESTS ON THIS AND NOTHING ANSWERED IT. Phase 1 made a
    published page that is not working visible; Phase 2 filed the plan; the
    revision arm rewrites the page that ranks. All of that is a bet that
    refreshing moves a page, and until this the system had no way to be told
    it was wrong. Adding a class of work without the measurement is adding it
    on faith, which is the thing this codebase refuses everywhere else.

    The same three refusals `progress` makes, for the same reasons:

    * **No claim without a control.** Refreshed pages are compared to
      published pages that were NOT refreshed over the same window. A quarter
      when the whole site rose is not a refresh working.
    * **No attribution Google has not settled.** A refresh inside
      `ATTRIBUTION_DAYS` is listed and flagged `too_early`, exactly as a
      publication is — the page may not have been re-crawled.
    * **No number where there is no reading.** A page with no reading from
      BEFORE its refresh cannot be judged at all: there is nothing to compare
      to. It is counted and named rather than dropped, because a silent drop
      makes a thin answer look like a confident one.

    Measured against each page's OWN refresh date, not the window's edge.
    """
    import datetime as dt
    cutoff = db.utcnow() - dt.timedelta(days=days)
    rows = targets(tenant)
    when, control_rows = {}, []
    for r in rows:
        ref = db.as_utc(r.refreshed_at) if r.refreshed_at else None
        if ref is not None and ref >= cutoff:
            when[r.phrase] = ref
        elif r.status in ("published", "won"):
            control_rows.append(r)

    before, after = _readings_astride(tenant, when)
    moved, early, blind = [], 0, []
    now_utc = db.utcnow()
    for phrase, ref_at in when.items():
        a, b = after.get(phrase), before.get(phrase)
        age = (now_utc - ref_at).days
        if b is None or b.position is None or a is None or a.position is None:
            # NAMED, NOT DROPPED. Most accounts will land here at first: a
            # refresh only becomes measurable once there is a reading on each
            # side of it, and reporting "0 refreshes helped" when the truth is
            # "none can be judged yet" is the more damaging of the two errors.
            blind.append({"phrase": phrase, "days_since_refresh": age,
                          "why": ("no reading from before the refresh"
                                  if b is None or b.position is None else
                                  "no reading since the refresh")})
            continue
        if age < ATTRIBUTION_DAYS:
            early += 1
        moved.append({"phrase": phrase, "days_since_refresh": age,
                      "from": b.position, "to": a.position,
                      "gain": round(b.position - a.position, 1),
                      "too_early": age < ATTRIBUTION_DAYS})
    moved.sort(key=lambda m: -m["gain"])

    # THE CONTROL, ASTRIDE THE SAME MOMENT. What an unrefreshed published page
    # did over a COMPARABLE span — which means splitting it on a date, not on
    # the window's edge. The first cut used `_period_readings(days)`, whose
    # `then` bucket holds only readings OLDER than the window: every control
    # page's history sat inside it, `then` was empty, and the control silently
    # came back as zero pages. A control that quietly evaluates to nothing is
    # worse than none — `lift` would have been withheld for the right-looking
    # wrong reason, and on an account with a real control it would have stayed
    # withheld forever.
    #
    # The median refresh date is the split: it is the moment the treated
    # cohort was representatively treated, so the control is measured over the
    # same calendar span rather than a longer or shorter one.
    c_gains: list[float] = []
    if when:
        dates = sorted(when.values())
        mid = dates[len(dates) // 2]
        keys = {r.phrase for r in control_rows}
        c_before, c_after = _readings_astride(tenant, {k: mid for k in keys})
        c_gains = [round(c_before[k].position - c_after[k].position, 1)
                   for k in keys
                   if k in c_before and k in c_after
                   and c_before[k].position is not None
                   and c_after[k].position is not None]

    judged = [m for m in moved if not m["too_early"]]
    notes: list[str] = []
    if blind:
        notes.append(f"{len(blind)} refreshed page(s) cannot be judged yet — "
                     f"a refresh needs a reading on each side of it.")
    if early:
        notes.append(f"{early} refresh(es) are inside the {ATTRIBUTION_DAYS}-day "
                     f"window and are listed but not attributed.")
    if not c_gains:
        notes.append("no control group: every published page with readings was "
                     "refreshed, so a rise here cannot be told apart from a "
                     "rise everywhere.")
    if not judged:
        notes.append("nothing is attributable yet — this is a baseline.")

    def _avg(xs):
        return round(sum(xs) / len(xs), 1) if xs else None

    return {
        "window_days": days,
        "refreshed": len(when),
        "judged": len(judged),
        "too_early": early,
        "unmeasurable": blind,
        "avg_gain": _avg([m["gain"] for m in judged]),
        "control_avg_gain": _avg(c_gains),
        "control_pages": len(c_gains),
        # THE ONLY NUMBER THAT ANSWERS THE QUESTION, and it is None whenever
        # either side is missing rather than falling back to the raw gain —
        # a lift computed against no control is the claim this refuses to make.
        "lift": (round(_avg([m["gain"] for m in judged]) - _avg(c_gains), 1)
                 if judged and c_gains else None),
        "movements": moved[:50],
        "notes": notes}


def _totals(readings: list) -> dict:
    ranked = [r.position for r in readings if r.position is not None]
    return {"phrases": len(readings),
            "clicks": sum(int(r.clicks or 0) for r in readings),
            "impressions": sum(int(r.impressions or 0) for r in readings),
            "avg_position": round(sum(ranked) / len(ranked), 1) if ranked else None}


def _delta(a: dict, b: dict) -> dict:
    """b -> a, with position inverted: a SMALLER position is an improvement,
    and a delta that reads -4 for a four-place gain is one somebody
    misreports the first time they quote it."""
    out = {"clicks": a["clicks"] - b["clicks"],
           "impressions": a["impressions"] - b["impressions"]}
    if a["avg_position"] is not None and b["avg_position"] is not None:
        out["position_gain"] = round(b["avg_position"] - a["avg_position"], 1)
    else:
        out["position_gain"] = None
    if b["clicks"]:
        out["clicks_pct"] = round((a["clicks"] - b["clicks"]) / b["clicks"] * 100, 1)
    else:
        out["clicks_pct"] = None      # no base is not zero growth
    return out


#: The three resolutions a person actually asks in. Owner, 2026-09-02: *"The
#: progress page as it stands isn't helpful being that it only checks 28 days
#: out. We need daily, weekly and monthly progress."*
#:
#: `days` has been a parameter all along, clamped 1-365 — with NO control that
#: sets it. So the page answered one question at one resolution and the other
#: two were reachable only by hand-editing a URL.
PROGRESS_WINDOWS = ((1, "yesterday"), (7, "this week"), (30, "this month"))


def progress_windows(tenant: str, windows=None) -> list:
    """The headline movement at several resolutions, each against its control.

    ONE ROW PER WINDOW, and each row carries the same honesty `progress` does:
    a window with no reading on the far side is a BASELINE, not a zero, and
    says so. A day-over-day view is the one most likely to be empty — Search
    Console lags and most accounts sync weekly — and printing 0 there would
    read as "nothing moved" when the truth is "nothing was measured".

    Cheap by construction: it reads this module's own tables, one pass per
    window, and makes no API call — the same reason `progress` can render on
    every visit.
    """
    out = []
    for days, label in (windows or PROGRESS_WINDOWS):
        now, then = _period_readings(tenant, days)
        rows = targets(tenant)
        tracked = {r.phrase for r in rows if r.status in ("published", "won")}
        t_now = _totals([v for k, v in now.items() if k in tracked])
        t_then = _totals([v for k, v in then.items() if k in tracked])
        c_now = _totals([v for k, v in now.items() if k not in tracked])
        c_then = _totals([v for k, v in then.items() if k not in tracked])
        # BOTH SIDES, not just the far one. Checking only `then` reported a
        # 1-day window as measurable while `now` was empty — Search Console
        # lags and most accounts sync weekly, so the near side is the one
        # usually missing. It rendered as a dash with no explanation, which is
        # the "0 reads as nothing moved" failure this row exists to avoid,
        # wearing a different mark.
        has_before = t_then["phrases"] > 0
        has_now = t_now["phrases"] > 0
        measurable = has_before and has_now
        ours = _delta(t_now, t_then) if measurable else {}
        theirs = (_delta(c_now, c_then)
                  if c_then["phrases"] and c_now["phrases"] else {})
        out.append({
            "days": days, "label": label,
            "measurable": measurable,
            "why_not": ("" if measurable else
                        f"no reading inside {days} day(s) — nothing was "
                        f"measured in this window, which is not the same as "
                        f"nothing moving" if not has_now else
                        f"no tracked reading older than {days} day(s) — this "
                        f"is a baseline, not a comparison"),
            "clicks": t_now["clicks"],
            "position_gain": ours.get("position_gain"),
            "clicks_pct": ours.get("clicks_pct"),
            # THE CONTROL AT THE SAME RESOLUTION. A week when the whole site
            # rose is not a week our work rose, and the answer differs by
            # window — which is most of why one window was not enough.
            "control_gain": theirs.get("position_gain"),
            "control_pages": c_now["phrases"],
        })
    return out


def progress(tenant: str, *, days: int = 28) -> dict:
    """Did the work move anything, and can we honestly say it was the work.

    Three things this refuses to do:

    * **Claim a rise without a control.** Tracked pages are compared to the
      REST of the site's queries over the same period. Without that a good
      quarter for the category reads as our work — and if the control group is
      empty the report says so instead of quietly comparing against nothing.
    * **Attribute a change Google has not settled.** Movements inside
      `ATTRIBUTION_DAYS` of publication are listed and flagged `too_early`,
      and left out of the attributable summary.
    * **Invent a target.** A goal is the owner's to declare; with none set the
      report names the missing field and still delivers every number that does
      not depend on it.
    """
    from . import systems
    now, then = _period_readings(tenant, days)
    rows = targets(tenant)
    tracked_phrases = {r.phrase for r in rows if r.status in ("published", "won")}

    def split(d: dict) -> tuple[list, list]:
        return ([v for k, v in d.items() if k in tracked_phrases],
                [v for k, v in d.items() if k not in tracked_phrases])

    t_now, c_now = split(now)
    t_then, c_then = split(then)
    tracked = {"now": _totals(t_now), "then": _totals(t_then)}
    control = {"now": _totals(c_now), "then": _totals(c_then)}
    tracked["change"] = _delta(tracked["now"], tracked["then"])
    control["change"] = _delta(control["now"], control["then"])

    notes: list[str] = []
    if not t_then:
        notes.append(f"no tracked readings older than {days} days — this is a "
                     "baseline, not a comparison. Run again next week.")
    if not c_now:
        notes.append("no control group: every phrase with data is one we are "
                     "targeting, so a rise here cannot be told apart from a "
                     "rise everywhere.")

    # --- per keyword, with the honesty attached --------------------------
    moves, too_early = [], 0
    for r in rows:
        if r.phrase not in tracked_phrases:
            continue
        a, b = now.get(r.phrase), then.get(r.phrase)
        if a is None or a.position is None:
            continue
        age = None
        if r.published_at:
            age = (db.utcnow() - db.as_utc(r.published_at)).days
        early = age is not None and age < ATTRIBUTION_DAYS
        too_early += 1 if early else 0
        moves.append({
            "phrase": r.phrase, "tier": r.tier, "cluster": r.cluster_key,
            "to": a.position,
            "from": b.position if b is not None else None,
            "gain": (round(b.position - a.position, 1)
                     if b is not None and b.position is not None else None),
            "clicks": int(a.clicks or 0),
            "days_since_publish": age if age is not None else "not recorded",
            "too_early": early})
    moves.sort(key=lambda m: (m["gain"] is None, -(m["gain"] or 0)))

    by_tier: dict[str, dict] = {}
    for m in moves:
        t = by_tier.setdefault(m["tier"] or "?", {"keywords": 0, "top3": 0, "top10": 0})
        t["keywords"] += 1
        t["top3"] += 1 if m["to"] <= 3 else 0
        t["top10"] += 1 if m["to"] <= 10 else 0

    # --- against a declared goal, or a named absence ----------------------
    sysrow = systems.find(tenant, "blog")
    goal = systems.goal_for(sysrow) if sysrow else {}
    top3 = sum(1 for m in moves if m["to"] <= 3)
    top10 = sum(1 for m in moves if m["to"] <= 10)
    if goal:
        against = {"declared": goal, "attainment": {}}
        pairs = (("organic_clicks", tracked["now"]["clicks"]),
                 ("top3", top3), ("top10", top10))
        for field, actual in pairs:
            if goal.get(field):
                against["attainment"][field] = {
                    "target": goal[field], "actual": actual,
                    "pct": round(actual / goal[field] * 100, 1)}
    else:
        against = {"declared": None, "attainment": {},
                   "missing": "no goal set for the blog system — set one with "
                              "systems.set_goal(organic_clicks=…, top3=…, "
                              "top10=…, horizon_days=…). Everything above is "
                              "reported without it; nothing below it is "
                              "invented to fill the gap."}
        notes.append(against["missing"])

    # DID REFRESHING WORK. The declared measure for the blog system is
    # "position change in `keywords.progress`, against a control" — and until
    # now that covered only PUBLISHING. A whole second class of work was added
    # (find a stalled page, plan a refresh, revise the live article) with no
    # way for the system to be told the bet was wrong. Its own window, longer
    # than the publish one, because a refresh is judged from its own date and
    # a 28-day view would drop most of them.
    refresh = refresh_effect(tenant, days=max(days, 90))
    return {
        "tenant": tenant, "window_days": days,
        "goal": against,
        "tracked": tracked, "control": control,
        "wins": {"top3": top3, "top10": top10, "by_tier": by_tier},
        "movements": moves[:50],
        "attributable": len(moves) - too_early,
        "too_early_to_attribute": too_early,
        "refresh": refresh,
        "notes": notes + [f"refresh: {n}" for n in refresh["notes"]]}


#: How often the map itself is refreshed. Distinct from the nightly reading
#: sync, and much rarer: positions move daily, the competitive landscape does
#: not, and each top-up spends Semrush calls across every account.
HARVEST_EVERY_DAYS = 7


def harvest_due(tenant: str) -> bool:
    """Has it been long enough since this account's map was last topped up?

    Read off the newest `first_seen` rather than stored as a marker: a row's
    own timestamp cannot drift from the thing it describes, and a "last
    harvested" setting is one more value to keep true.
    """
    import datetime as dt
    rows = targets(tenant)
    if not rows:
        return False           # nothing to top up; a FIRST harvest is a choice
    newest = max((db.as_utc(r.first_seen) for r in rows if r.first_seen),
                 default=None)
    if newest is None:
        return True
    return (db.utcnow() - newest).days >= HARVEST_EVERY_DAYS


def harvest_one(tenant: str, *, limit: int = 40) -> dict:
    """One account's weekly top-up, with its gates. The unit `harvest_all`
    loops and the worker shards: every skip is a dict that says why, so a
    sharded run reads the same as a serial one."""
    from . import systems
    if not systems.find(tenant, "blog"):
        return {"skipped": "no blog system installed"}
    if not harvest_due(tenant):
        return {"skipped": "topped up within the last "
                           f"{HARVEST_EVERY_DAYS} days"}
    try:
        return harvest(tenant, limit=limit)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{exc.__class__.__name__}: {str(exc)[:140]}"}


def harvest_all(*, limit: int = 40) -> dict:
    """Top up every account's map that is due, on the weekly schedule.

Only accounts that ALREADY have a map. A first harvest stays a deliberate
act — it is the moment somebody decides this account is being worked on,
and starting one automatically would spend a client's Semrush quota on a
map nobody asked for.

    ONE LOOP, ONE UNIT. This is `harvest_one` over every account and nothing
    else, so the worker can shard the same unit per tenant and the two paths
    cannot drift — `test_job_lease` compares them.
    """
    from . import systems, tenants
    return {t.key: harvest_one(t.key, limit=limit)
            for t in tenants.all_tenants()
            if systems.find(t.key, "blog")}

def sync_one(tenant: str, *, days: int = 28) -> dict:
    """One account's nightly readings, with its gates. See `harvest_one`."""
    from . import systems
    if not systems.find(tenant, "blog"):
        return {"skipped": "no blog system installed"}
    if not targets(tenant):
        return {"skipped": "no keyword map — nothing to measure"}
    try:
        return sync(tenant, days=days)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{exc.__class__.__name__}: {str(exc)[:140]}"}


def sync_all(*, days: int = 28) -> dict:
    """Every account whose blog system is installed and whose CMS is wired.

Scoped to those two facts on purpose. Syncing an account with no blog
system spends a client's Search Console quota on a map nobody is writing
against, and an account with no CMS cannot have published anything for the
readings to be about.

    ONE LOOP, ONE UNIT — `sync_one` over every account with a blog system.
    """
    from . import systems, tenants
    return {t.key: sync_one(t.key, days=days)
            for t in tenants.all_tenants()
            if systems.find(t.key, "blog")}

def _gsc_probe(tenant: str, profile: dict) -> dict:
    """Can we actually read Search Console for this site.

    A REAL CALL, not a capability lookup. `credentials` can only say whether a
    Google credential exists; whether the consent behind it covered
    `webmasters.readonly` is a different question, and the codebase has three
    different Google scope lists — `scripts/google_oauth.py` and
    `oauth.FLOWS["google"]` both request Search Console, `gmail_client.SCOPES`
    does not. An account can therefore read green on `inbox` forever while
    every GSC call fails. Asking the API is the only answer that is not a
    guess.
    """
    from . import google_seo
    try:
        listed = google_seo.gsc_list_sites(profile)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": f"{exc.__class__.__name__}: {str(exc)[:120]}",
                "fix": "re-run scripts/google_oauth.py for this alias, or "
                       "reconnect Google at /connect/<token>"}
    if not listed.strip().startswith(("[", "{")):
        # Every tool in this pack returns JSON on success and a SENTENCE on
        # failure — the documented contract, and the reason this is not a
        # try/except alone.
        return {"ok": False, "detail": listed[:200],
                "fix": "grant webmasters.readonly and confirm the Google "
                       "account has access to this property in Search Console"}
    matched = google_seo._resolve_gsc_site(profile)
    if not matched:
        return {"ok": False,
                "detail": f"the token reads Search Console, but no property "
                          f"matches {profile.get('domain')!r}",
                "fix": "add this domain to Search Console for the connected "
                       "Google account, or set gsc_site with seo_link_google"}
    return {"ok": True, "detail": f"reading {matched}"}


def readiness(tenant: str, *, probe: bool = True) -> dict:
    """Three questions, answered separately, each naming its own fix.

    Separately because they fail separately and the fixes are different people:
    connecting a store is the client, granting Search Console is whoever owns
    the Google account, and approving a claim is the owner.
    """
    from . import credentials, sites, systems, tenants, kb as kb_mod

    t = tenants.get(tenant)
    if not t:
        return {"tenant": tenant, "error": "unknown account"}
    caps = credentials.wired_capabilities(tenant)
    sysrow = systems.find(tenant, "blog")
    out: dict = {"tenant": tenant, "installed": bool(sysrow),
                 "status": getattr(sysrow, "status", "") or "not installed"}

    # --- 1. can it publish -------------------------------------------------
    pub: dict = {"ok": False}
    if "cms" not in caps:
        pub["detail"] = "no CMS connected"
        pub["fix"] = (f"connect {(t.cms or {}).get('platform') or 'a CMS'} at "
                      f"/connect/<token> — the platform follows from the "
                      f"connection")
    else:
        pub["via"] = caps["cms"]
        try:
            profile = sites.get(tenant)
            sites.backend(profile)
            blog_id = (t.cms or {}).get("blog_id") or ""
            if profile.get("platform") != "wordpress" and not blog_id:
                pub["detail"] = "connected, but no blog_id"
                pub["fix"] = ("a store can hold several blogs and the "
                              "skill refuses to guess — press 'Find the blogs "
                              "on this store' beside this line and pick one")
            else:
                pub.update(ok=True, detail=f"{profile['platform']} via {caps['cms']}")
        except sites.UnknownSite as exc:
            pub["detail"] = str(exc)[:180]
            pub["fix"] = "build a backend for this platform, or move the site"
    out["publish"] = pub

    # --- 2. can it measure -------------------------------------------------
    meas: dict = {"ok": False}
    if probe:
        try:
            meas = _gsc_probe(tenant, sites.get(tenant))
        except sites.UnknownSite as exc:
            meas = {"ok": False, "detail": str(exc)[:180], "fix": "see publish"}
    else:
        # UNKNOWN IS NOT OK. `ok=None`, never a boolean.
        #
        # This read `ok = "analytics" in caps`, so the Plan tab showed a green
        # tick beside Measure for an account whose Search Console returns 403
        # insufficientPermissions — the capability said wired because Google
        # was connected, and the capability is exactly what cannot answer this
        # question. That is §2.29's defect, on the page built to detect it,
        # introduced by the person who had spent the day removing it.
        #
        # A third state, which this console already speaks elsewhere:
        # `credentials.status` reports "not verifying" between connected and
        # missing for the same reason. Collapsing unknown into either one is
        # how a console starts lying.
        meas = {"ok": None,
                "detail": f"not checked ({caps.get('analytics', 'not wired')})",
                "fix": "the capability says a Google account is connected, "
                       "which is not the same as Search Console answering. "
                       "Check it to find out."}
    # Said explicitly, because it is the one people assume: the env-group
    # Google grants `inbox` ALONE (`ENV_GRANTS`), so an account can show a
    # working mailbox and have no Search Console at all.
    meas["capability"] = caps.get("analytics", "not wired")
    out["measure"] = meas

    # --- 3. does it know what to write -------------------------------------
    rows = targets(tenant)
    claims = kb_mod.claims(tenant) if hasattr(kb_mod, "claims") else []
    banned = kb_mod.banned_claims(tenant)
    know: dict = {"keywords": len(rows),
                  "candidates": len([r for r in rows if r.status == "candidate"]),
                  "claims": len(claims), "banned_claims": len(banned)}
    problems = []
    if not rows:
        problems.append("no keyword map — press Build the map, below")
    if not claims:
        problems.append("no approved claims — the skill refuses to draft "
                        "without one, and will not spend a model call")
    if not banned:
        problems.append("no banned_claims — a ban list is constitutive for an "
                        "article, so the skill is gated on it")
    # WHICH MARKET the research came from, said out loud. `database` falls
    # back to `config.SEO_DATABASE` ("us"), so an account outside the US with
    # nothing set gets US volumes, US competitors and US questions pulled into
    # its map — wrong data, correctly filed, invisible. The default stays,
    # because it is right for most of these accounts; what changes is that it
    # is now a STATED assumption rather than a hidden one.
    declared = ((t.analytics or {}).get("semrush_db") or "").strip()
    try:
        market = sites.get(tenant).get("database", "")
    except Exception:                                            # noqa: BLE001
        market = declared
    know["market"] = market
    # AN ADVISORY, NOT A BLOCKER — and the suite is what settled that. Putting
    # this in `problems` made an account with a map, approved claims and a ban
    # list read NOT READY purely for never having named a market whose default
    # is correct for most of these accounts. A warning that turns a working
    # account red is one somebody learns to scroll past, which costs more than
    # it saves. `notes` is seen and does not gate.
    notes: list[str] = []
    if not declared:
        notes.append(
            f"market not set — Semrush research is being pulled from "
            f"'{market}'. Right for a US audience; wrong volumes, competitors "
            f"and questions for anyone else. Set analytics.semrush_db to "
            f"change it.")

    know["ok"] = not problems
    know["fix"] = problems
    know["notes"] = notes
    out["knows_what_to_write"] = know

    # INSTALLED AND ON is part of the answer, not context beside it. The first
    # version returned ok=True for an account that had every connector wired
    # and no `blog` system at all — a green light on a pipeline that cannot
    # run, which is the precise shape of the false assurance this file exists
    # to refuse.
    live = bool(sysrow) and systems.is_on(sysrow)
    if not live:
        out["switch"] = {
            "ok": False,
            "detail": out["status"],
            # The id travels so the page can offer the switch itself. Telling
            # somebody to turn a system on and giving them nowhere to do it is
            # the same defect as naming a missing blog_id and sending them to
            # a URL bar — the owner met both in the same afternoon.
            "system_id": getattr(sysrow, "id", ""),
            "fix": ("install it — /admin/system_add, or the Systems tab"
                    if not sysrow else
                    f"the system is {out['status']}; turn it on to run")}
    else:
        out["switch"] = {"ok": True, "detail": "live"}
    # `meas["ok"] is True`, not truthiness: None must not read as ready.
    out["ok"] = bool(live and pub.get("ok") and meas.get("ok") is True
                     and know["ok"])

    # THE PLAN IS NOT THE PIPELINE, and conflating them made a whole page read
    # as broken (owner, 2026-08-26: *"the Publish path belongs to the blog
    # system anyways right? The plan is just the brain / architecture of our
    # content strategy"*).
    #
    # Three different questions with three different answers:
    #   can it PLAN     — the switch, and whether it knows what to write;
    #   can it PROVE it — Search Console;
    #   can it SHIP     — a CMS.
    #
    # Ironside can do the first today and cannot do the third until
    # Squarespace exists. Rendering that as a red verdict beside the others
    # says "this account is blocked" about the half that works — and a parked
    # decision shown as a blocker is one the owner learns to read past.
    out["can_plan"] = bool(live and know["ok"])
    out["downstream"] = {"publish": pub, "measure": meas}
    return out


def readiness_all(*, probe: bool = True) -> dict:
    from . import tenants
    return {t.key: readiness(t.key, probe=probe) for t in tenants.all_tenants()}


# ---------------------------------------------------------------------------
# The answer-engine half — and the line between measured and inferred
# ---------------------------------------------------------------------------
#
# This initiative PRODUCES for answer engines: answer-first opening paragraphs,
# H3 questions taken from what people actually searched, FAQPage JSON-LD. Until
# now it MEASURED only classic search — positions and clicks from Search
# Console — which meant the AEO half of the work had no evidence either way.
#
# What can honestly be measured from the data we hold:
#
#   * whether the questions people ask have been ANSWERED at all, which is the
#     coverage half and is entirely ours to know;
#   * whether question-shaped queries are gaining surface, which is Search
#     Console reporting its own numbers;
#   * where a page ranks well and is NOT being clicked, which is the signature
#     of an answer being taken above the result.
#
# What CANNOT, and is therefore not claimed: whether a given AI assistant cites
# this brand. That needs a retrieval-capable call per tracked question, and
# `llm.call` has no web-search tool wired — asking a model from memory would
# measure its training data, not its citations, and would be a fabricated
# number wearing a metric's clothes. `KeywordReading.source` is a free string,
# so `source="ai"` rows drop straight in the day a real check exists.

#: A page ranking here should be getting clicks. Below this position the
#: click-through question is about relevance, not about an answer being taken.
ANSWER_TAKEN_MAX_POSITION = 10.0

#: How far under its band's median CTR a keyword must sit before it is worth
#: naming. Half is deliberately blunt: this is a flag for a human to look at,
#: not a measurement, and a tighter threshold would imply a precision the
#: signal does not have.
ANSWER_TAKEN_CTR_RATIO = 0.5

#: A median of two numbers is not a baseline. Below this a band says so rather
#: than comparing against noise.
ANSWER_TAKEN_MIN_BAND = 5


def _median(values: list) -> float:
    if not values:
        return 0.0
    v = sorted(values)
    mid = len(v) // 2
    return v[mid] if len(v) % 2 else (v[mid - 1] + v[mid]) / 2


def aeo(tenant: str, *, days: int = 28) -> dict:
    """How the answer-engine work is doing, and what this cannot see.

    THE BASELINE IS THIS ACCOUNT'S OWN KEYWORDS, not a published CTR curve.
    Every such curve is somebody else's sample of somebody else's SERPs, and
    importing one would put an invented number at the centre of the finding.
    Comparing a keyword to the median of our own keywords at similar positions
    needs no outside assumption and answers the actual question: is this page
    being clicked less than our pages that rank where it ranks.
    """
    now, then = _period_readings(tenant, days)
    rows = targets(tenant)
    tracked = {r.phrase: r for r in rows if r.status in ("published", "won")}

    # --- coverage: have we answered the questions people ask ---------------
    questions = [r for r in rows if is_question(r.phrase)]
    answered = [r for r in questions if r.status in ("published", "won")]
    coverage = {
        "questions_in_map": len(questions),
        "answered": len(answered),
        "unanswered": len(questions) - len(answered),
        "planned": len([r for r in questions if r.status == "planned"])}

    # --- surface: are question-shaped queries gaining -----------------------
    def _tot(d: dict, only_questions: bool) -> dict:
        picked = [v for k, v in d.items()
                  if k in tracked and is_question(k) == only_questions]
        return _totals(picked)
    q_now, q_then = _tot(now, True), _tot(then, True)
    surface = {"now": q_now, "then": q_then, "change": _delta(q_now, q_then)}

    # --- the answer-taken flag ---------------------------------------------
    bands: dict[str, list] = {"1-3": [], "4-10": []}
    for phrase, r in now.items():
        if phrase not in tracked or r.position is None or not r.impressions:
            continue
        if r.position <= 3:
            bands["1-3"].append(r)
        elif r.position <= ANSWER_TAKEN_MAX_POSITION:
            bands["4-10"].append(r)

    flagged, band_notes = [], {}
    for band, members in bands.items():
        if len(members) < ANSWER_TAKEN_MIN_BAND:
            band_notes[band] = (f"only {len(members)} keyword(s) here — too few "
                                f"to have a median worth comparing against")
            continue
        med = _median([m.ctr or 0.0 for m in members])
        band_notes[band] = f"{len(members)} keyword(s), median CTR {med:.1f}%"
        if med <= 0:
            continue
        for m in members:
            if (m.ctr or 0.0) < med * ANSWER_TAKEN_CTR_RATIO:
                flagged.append({
                    "phrase": m.phrase, "position": m.position,
                    "ctr": m.ctr, "band_median_ctr": round(med, 1),
                    "impressions": m.impressions, "clicks": m.clicks,
                    "is_question": is_question(m.phrase)})
    flagged.sort(key=lambda f: -(f["impressions"] or 0))

    return {
        "tenant": tenant, "window_days": days,
        "coverage": coverage,
        "question_surface": surface,
        "answer_taken": {
            "flagged": flagged[:25],
            "bands": band_notes,
            "means": ("ranking well and not being clicked — consistent with an "
                      "answer engine or a featured snippet taking the answer "
                      "above the result. It is a FLAG to look at, not a "
                      "measurement: a dull title or a mismatched intent look "
                      "the same from here.")},
        "not_measured": (
            "Whether any AI assistant cites this brand. That needs a "
            "retrieval-capable call per tracked question; asking a model from "
            "memory would measure its training data, not its citations. "
            "`KeywordReading` already takes source='ai' rows the day a real "
            "check exists."),
    }


# ---------------------------------------------------------------------------
# The board — the map as the four questions somebody actually asks of it
# ---------------------------------------------------------------------------
#
# Owner, 2026-08-26: *"the plan should show a dynamic table of the brands
# current priorities, changes week to week and separate tables for keyword
# opportunities, next priorities etc. I need to visualize which keywords we are
# optimizing for as well in the blogs and content."*
#
# One flat table sorted by score answers none of those. Four do:
#
#   writing_next  what the ranking says to do now, WITH its arithmetic, so the
#                 order can be argued with instead of only obeyed;
#   moved         what changed since last week, from the readings — the only
#                 week-on-week fact this system actually holds;
#   opportunities the backlog nobody has claimed yet, by tier, because a head
#                 term and a long-tail are different decisions;
#   in_flight     which keyword each article was written FOR, which is the
#                 join between the plan and the content and was visible
#                 nowhere.
#
# **Priority history is not kept, and this does not pretend otherwise.**
# `moved` is position movement from `KeywordReading`, which is recorded; a
# score delta would need snapshots nothing writes, and inventing one from the
# current parts would be a number describing a week that was never measured.

#: How long a page gets before "not ranking" is a fact about the page rather
#: than about Google not having settled. Longer than `ATTRIBUTION_DAYS`, which
#: is the floor for ATTRIBUTING a movement — this is the floor for ACTING on
#: the absence of one, and acting is the more expensive mistake.
REFRESH_AFTER_DAYS = 30

#: And how long between refreshes of the same page. Refreshing something that
#: has not had time to be re-crawled measures nothing and spends the budget
#: that a page which HAS settled was waiting for.
REFRESH_COOLDOWN_DAYS = 60


def refresh_windows(tenant: str) -> tuple:
    """(settle, cooldown) in days, for THIS account.

    ONE READER, because two surfaces ask: `attention` decides what is
    `too_early` and what is still cooling, and the console renders both numbers
    beside the boxes that set them. Reading the cadence in one and the module
    constant in the other is how a knob starts being ignored by the very thing
    it was added to control.

    Falls back to the constants when no blog system exists — a keyword map can
    be read before a system is installed, and refusing there would make the
    board depend on an unrelated row.
    """
    from . import planner, systems
    row = systems.find(tenant, "blog")
    if row is None:
        return REFRESH_AFTER_DAYS, REFRESH_COOLDOWN_DAYS
    cad = planner.blog_cadence_for(row)
    return (int(cad.get("refresh_after_days") or REFRESH_AFTER_DAYS),
            int(cad.get("refresh_cooldown_days") or REFRESH_COOLDOWN_DAYS))


def cluster_support(tenant: str, cluster_key: str, rows: list | None = None) -> dict:
    """What a cluster's support layer actually looks like. Computed, not
    described.

    `_owed_for` tells a page at 11-30 that it needs "supports in its cluster,
    linking up". That sentence was the end of the line: nothing said WHICH
    supports, whether any were left to write, or whether the ones already
    written link up at all. Advice a surface cannot act on is a fix
    instruction where a control belongs.

    Returns the three counts that decide what to offer, and the phrases behind
    two of them so a control can file exactly those and no others.
    """
    # `rows` LETS THE CALLER READ ONCE. `attention` calls this per stalled
    # row, and reading the map inside turned one board render into a full
    # keyword_targets scan per row: 602 queries and 9.7 seconds on a
    # 600-keyword account, 588 of them thrown away by `top=12`. Quadratic in
    # the size of the thing this feature exists to manage.
    rows = [r for r in (targets(tenant) if rows is None else rows)
            if (r.cluster_key or "") == cluster_key]
    writable = [r.phrase for r in rows
                if (r.role or "") == "support" and r.status == "candidate"
                and (r.owner_priority or "") != "muted"]
    published = [r for r in rows if (r.role or "") == "support"
                 and r.status in ("published", "won")]
    return {"cluster": cluster_key,
            "writable": writable,
            "published": len(published),
            "in_flight": len([r for r in rows if (r.role or "") == "support"
                              and r.status == "planned"])}


def orphan_supports(tenant: str, *, top: int = 12) -> list[dict]:
    """Published supports whose body does not link up to their pillar.

    THE BAND RECOMMENDS THIS AND NOTHING CHECKED IT. `_owed_for` sends a
    stalled page its cluster's supports "linking up", the drafter is TOLD a
    support "links back to the pillar", and `_link_grounding` verifies that
    the links present RESOLVE — it never verifies a required link is THERE. So
    a support could ship with zero links up and pass every gate, and the
    mechanism the whole pillar/cluster model rests on was advice.

    A FLAG, NEVER A GATE. Owner, 2026-09-01, on requiring the link: *"I can
    see issues with it being required — for example clients who dont have a
    cms."* Right, and the reason generalises past the CMS: at drafting time
    the pillar may not be published yet, so the link CANNOT exist, and
    refusing the article would punish it for the order the work was done in.
    The honest handling is to notice later and offer the fix — which is a
    refresh, and a refresh is now a thing this system can file.

    Only supports whose pillar HAS an address are listed. One whose pillar has
    none is not an orphan, it is waiting — and `unlinked()` already reports
    the pillar as the thing to fix, which is the one action that helps both.
    """
    pillars = {}
    for r in targets(tenant):
        if (r.role or "") == "pillar" and (r.target_url or "").strip():
            pillars[r.cluster_key or ""] = r
    from . import links as _links
    cand = [r for r in targets(tenant)
            if (r.role or "") == "support"
            and r.status in ("published", "won")
            and (r.output_id or "")
            and pillars.get(r.cluster_key or "") is not None]
    out: list[dict] = []
    if not cand:
        return out
    # ONE QUERY FOR EVERY BODY, not one per support. The first cut asked
    # inside the loop, which is the same N+1 shape as `cluster_support` and on
    # the same page.
    with db.SessionLocal() as s:
        bodies = {a.output_id: (a.body or "") for a in
                  s.query(db.ArtifactBody)
                  .filter(db.ArtifactBody.output_id
                          .in_([r.output_id for r in cand])).all()}
    for r in cand:
        pillar = pillars[r.cluster_key or ""]
        if r.output_id not in bodies:
            continue
        if _links.points_at(bodies[r.output_id], pillar.target_url or ""):
            continue
        out.append({"phrase": r.phrase, "cluster": r.cluster_key or "",
                    "pillar": pillar.phrase,
                    "pillar_url": pillar.target_url or "",
                    "output_id": r.output_id,
                    "owed": (f"links nowhere — it should link up to "
                             f"{pillar.phrase!r}")})
    out.sort(key=lambda x: x["phrase"])
    return out[:top]


def unlinked(tenant: str, *, top: int = 12) -> list[dict]:
    """Articles that were APPROVED and have no URL. Flagged, never required.

    Owner, 2026-09-01: *"I can see issues with it being required — for example
    clients who don't have a CMS we would need to derive the link unless
    otherwise stated and associated. Lets prioritize linked support articles
    and raise a flag when an approved article has no link associated yet."*

    Right, and requiring it would have been the wrong shape twice over. A hard
    gate would block exactly the accounts that publish by hand — the ones where
    paste-and-record IS the workflow — and it would refuse an article for a
    fact nobody knew yet at drafting time. A URL is not something the writer
    withheld; it is something that does not exist until the page does.

    SO IT IS A FLAG, AND THE FLAG IS THE POINT: an approved article with no URL
    is invisible in every direction at once, and each direction is silent.

      · Nothing can link to it. `_run_blog_article` offers only siblings whose
        `target_url` resolves, so an unlinked pillar is a cluster with no hub
        and every support in it ships pointing nowhere.
      · Nothing can measure it. `attention` reads `published`/`won` and
        `progress` attributes the same, so the page is outside both lanes.
      · Nothing says so. It was approved, which reads as done.

    THE MOVE DEPENDS ON WHETHER THERE IS A CMS, which is why that is computed
    here rather than left to the reader. With one connected the URL is captured
    on publish already (`approvals._execute` takes it from the backend's own
    reply), so a row here means the page was published OUTSIDE the flow and the
    address needs fetching. With none, paste-and-record is the workflow and
    this is simply the second half of it, not yet done.
    """
    from . import tenants
    row = tenants.get(tenant)
    platform = str((getattr(row, "cms", None) or {}).get("platform") or "")
    rows = [r for r in targets(tenant)
            if not (r.target_url or "").strip() and (r.output_id or "").strip()]
    # WHO IS WAITING ON IT, counted rather than described. A pillar with six
    # supports behind it is a different-sized problem from a lone support, and
    # "some articles may be affected" is the kind of sentence that gets
    # scrolled past.
    by_cluster: dict[str, int] = {}
    for r in targets(tenant):
        if r.cluster_key:
            by_cluster[r.cluster_key] = by_cluster.get(r.cluster_key, 0) + 1
    out: list[dict] = []
    now_utc = db.utcnow()
    with db.SessionLocal() as s:
        for r in rows:
            o = s.get(db.Output, r.output_id)
            if o is None or (o.status or "") not in ("approved", "published"):
                continue
            decided = db.as_utc(o.published_at or o.created_at)
            out.append({
                "phrase": r.phrase, "role": r.role or "support",
                "cluster": r.cluster_key or "", "output_id": r.output_id,
                "waiting": max(0, by_cluster.get(r.cluster_key or "", 1) - 1),
                "days": (db.as_utc(now_utc) - decided).days if decided else None,
                "platform": platform,
                "owed": (f"published outside the flow — fetch the address from "
                         f"{platform}" if platform else
                         "paste the address it went live at"),
            })
    # A pillar first: an unlinked pillar is a cluster with no hub, and every
    # support written into it inherits the problem.
    out.sort(key=lambda x: (0 if x["role"] == "pillar" else 1,
                            -x["waiting"], -(x["days"] or 0)))
    return out[:top]


def attention(tenant: str, *, top: int = 12) -> list[dict]:
    """Published pages and what each one is owed. FOUR STATES, not one.

    Owner, 2026-09-01: *"keywords often need a few articles to start ranking
    for them right?"* Half right, and the half that matters is that a TOPIC
    needs several pages while a KEYWORD needs one — two pages aimed at one
    query cannibalise, and the engine picks one. So the answer is never a
    second article on the same phrase.

    The real gap was one step later. `writing_next` is `status == candidate`,
    so once a page is published its keyword is never proposed again WHATEVER
    IT DOES — while `progress()` has been measuring position against a control
    the whole time. The system measured whether a page ranked and did nothing
    with the answer.

    THE FOUR STATES OWE DIFFERENT THINGS, and lumping them together is what
    would make this lane noise:

      · `too_early`  — inside REFRESH_AFTER_DAYS. Nothing is owed; Google has
        not settled, and `progress` already refuses to attribute here.
      · `no_reading` — Search Console has nothing for the phrase. That is an
        INDEXATION question, not a content one, and a refresh does not answer
        it.
      · `slipping`   — it was `won` and is not now. The most urgent, because
        something that worked stopped working.
      · `stalled`    — past the window, ranking outside the top 3, and not
        refreshed lately.

    A page inside the cooldown is not listed at all: it was refreshed and is
    waiting to be re-crawled, and offering it again is asking for a decision
    that cannot yet be informed.
    """
    import datetime as _dt
    # THE ACCOUNT'S OWN WINDOWS, not the platform's. Owner, 2026-09-02: *"That
    # should be set in the UI based on the cadence."* A site Google crawls
    # weekly and one it crawls monthly cannot share a settle time, and these
    # were module constants no console could reach. The constants survive as
    # the DEFAULTS the cadence falls back to, so an account that has set
    # nothing behaves exactly as it did.
    settle, cooldown = refresh_windows(tenant)
    now_utc = _dt.datetime.now(_dt.timezone.utc)
    every = targets(tenant)          # read ONCE; `cluster_support` reuses it
    rows = [r for r in every
            if (r.owner_priority or "") != "muted"
            and r.status in ("published", "won")]
    readings, _then = _period_readings(tenant, 7)
    out: list[dict] = []
    for r in rows:
        pub = db.as_utc(r.published_at) if r.published_at else None
        age = (now_utc - pub).days if pub else None
        ref = db.as_utc(r.refreshed_at) if r.refreshed_at else None
        since_refresh = (now_utc - ref).days if ref else None
        if since_refresh is not None and since_refresh < cooldown:
            continue
        rd = readings.get(r.phrase)
        pos = rd.position if rd else None
        if age is not None and age < settle:
            state, act, owed = ("too_early", "wait",
                                "nothing yet — give it time to settle")
        elif pos is None:
            state, act, owed = ("no_reading", "index",
                                "Search Console has no reading — check it is "
                                "indexed before rewriting anything")
        elif r.status == "won" or pos <= WON_POSITION:
            continue                      # winning: nothing owed
        elif r.won_at is not None:
            # SLIPPING IS ALWAYS A REFRESH, whatever the band says. The band
            # answers "what is likely to move a page that never got there";
            # a page that DID get there and fell has already proved the intent
            # matches and the cluster carries it, so the question is what
            # changed on the page or past it — which is what a refresh asks.
            state, act, owed = ("slipping", "refresh",
                                "it ranked and stopped — refresh it first")
        else:
            state = "stalled"
            act, owed = _owed_for(pos)
        row_out = {"phrase": r.phrase, "status": r.status, "position": pos,
                   "role": r.role, "cluster": r.cluster_key,
                   "target_url": r.target_url, "published_days": age,
                   "since_refresh": since_refresh, "output_id": r.output_id,
                   "state": state, "action": act, "owed": owed,
                   "priority": r.priority}
        # WHAT "SUPPORTS IN ITS CLUSTER" ACTUALLY MEANS HERE. The band said
        # the words and stopped; a surface could render them and offer
        # nothing, because nothing said WHICH supports or whether any were
        # left to write. Computed only for the rows it applies to — asking
        # per row on a map of several hundred is a query per row, and the
        # other three actions have no use for the answer.
        if act == "supports":
            sup = cluster_support(tenant, r.cluster_key or "", every)
            row_out["supports"] = sup
            if not sup["writable"]:
                # THREE DIFFERENT SITUATIONS, SAID DIFFERENTLY. "Write
                # supports" when there are none left to write is advice that
                # cannot be taken, and a person who tries it and finds nothing
                # stops trusting the column.
                #
                # ALREADY PLANNED IS NOT NONE. The first cut folded
                # `in_flight` into the same sentence as `published` and then
                # printed only the published count — so a cluster whose whole
                # support layer had just been queued read as "0 support(s) and
                # none left to write — the map needs more keywords", telling
                # the owner to go harvest keywords for work already scheduled.
                # It did not need the new button either: the weekly run marks
                # each candidate `planned` as it files it.
                if sup["in_flight"]:
                    row_out["owed"] = (
                        f"{sup['in_flight']} support(s) are already planned "
                        f"for this cluster — nothing more to file; this page "
                        f"should move as they land")
                elif sup["published"]:
                    row_out["owed"] = (
                        f"its cluster has {sup['published']} support(s) and "
                        f"none left to write — the map needs more keywords "
                        f"for this topic before supports can help it")
                else:
                    row_out["owed"] = (
                        "this topic has no cluster around it yet — build the "
                        "map for it before spending anything on this page")
        out.append(row_out)
    order = {"slipping": 0, "stalled": 1, "no_reading": 2, "too_early": 3}
    out.sort(key=lambda x: (order.get(x["state"], 9), -(x["priority"] or 0)))
    return out[:top]


#: Where a page sits -> what that argues for, as (ceiling, action, sentence).
#:
#: ONE TABLE, because the planner acts on the action while the console shows
#: the sentence, and a band written in two places drifts in exactly the way
#: every other defect in this repo drifted: the surface goes on saying
#: "supports in its cluster" while the planner quietly files a refresh.
#: `_owed_for` returns both halves together so they cannot disagree.
#:
#:   4-10  the page is close, so depth, intent match and question coverage
#:         are what move it. Refresh THIS page.
#:   11-30 usually topical authority rather than page quality. Supports in
#:         the cluster, linking up to it.
#:   >30   usually intent mismatch or indexation, and a refresh rarely fixes
#:         either. Re-read what is actually ranking for the phrase before
#:         spending anything on it.
_MOVES = (
    (10.0, "refresh", "close — refresh this page (depth, intent, questions)"),
    (30.0, "supports", "supports in its cluster, linking up — not a rewrite"),
    (None, "reread", "re-read the intent: what ranks for this may not be this page"),
)


def _owed_for(position: float) -> tuple[str, str]:
    """Which move the position itself argues for: (action, sentence).

    Stated data, not a model's guess. See `_MOVES` for the bands and why
    both halves are returned from one place.
    """
    for ceiling, action, sentence in _MOVES:
        if ceiling is None or position <= ceiling:
            return action, sentence
    raise AssertionError("_MOVES must end in an open band")


def unanswered_questions(tenant: str) -> list:
    """Question-shaped keywords that could be FILED right now. ONE READER.

    `aeo()["coverage"]["unanswered"]` means "not published", which counts the
    ones already planned — so a button sized from it offered to plan work that
    was already scheduled and filed nothing when pressed. The button and the
    route were counting different populations, which is the split-contract
    shape this codebase keeps closing: two halves of one question, answered in
    two places.

    Highest priority first, because the monthly cap stops the filing long
    before a real backlog runs out and the ones that get in should be the ones
    worth writing.
    """
    return [r.phrase for r in targets(tenant)
            if is_question(r.phrase)
            and r.status == "candidate"
            and (r.owner_priority or "") != "muted"]


def next_to_write(tenant: str, *, top: int = 12) -> list:
    """The phrases the board is currently offering as work. ONE READER.

    `board()` computed this inline, and the mute route needed the same answer
    to say what a mute had CHANGED — two copies of "what is on the board"
    disagree the first time either is touched, and this is the list a person
    reads decisions off.

    Muted is EXCLUDED rather than sorted last, for the reason `board` gives:
    ranking a ruled-out keyword bottom still puts it on the page, so a
    decision already made is re-presented every week.
    """
    return [r.phrase for r in targets(tenant)
            if (r.owner_priority or "") != "muted"
            and r.status == "candidate"][:top]


# ---------------------------------------------------------------------------
# The mix — what the map is made of, and what share of it to plan
# ---------------------------------------------------------------------------
#
# Owner, 2026-09-04: *"I should be able to adjust the plan based on the
# percent of long tail / branded / short / specific topics etc and the app
# should recommend a base setting default based on the current status of the
# brand and where the best opportunities lie."*
#
# Three dimensions, each a PARTITION of the candidates, each read off the row:
# tier (head | body | long_tail — `classify_tier`), branded (the phrase names
# the brand — `brand_tokens_for`), and intent (buying — commercial or
# transactional — against informational; `classify_intent`). "Specific topics"
# are clusters, and pinning already does that: a pinned keyword sorts above
# the arithmetic and the mix never moves it.
#
# The RECOMMENDATION is arithmetic over the map as it stands — the share of
# candidates in each class, weighted toward striking distance (a page already
# on page two is the biggest single lever, so the tier it sits in gets more of
# the plan), with two rules a share cannot express: a head term is won with a
# pillar PLUS supports, so head never carries more than HEAD_CAP of the plan;
# and a cluster whose supports are published while its pillar is not is a head
# term half-won, so head never falls below HEAD_FLOOR while one exists. Every
# number comes with the sentence that produced it, because a recommendation
# nobody can argue with is one nobody can correct — the same rule `score`
# keeps with `priority_parts`.

#: The intents that mean the searcher is choosing what to buy.
BUYING_INTENTS = ("commercial", "transactional")

#: Head terms never carry more than this share of new articles. A head term is
#: won with a pillar and the supports that link into it, so the supports must
#: outnumber the pillars whatever the map says.
HEAD_CAP = 40

#: …and never less than this while a cluster has published supports and no
#: published pillar — those supports link to nothing until the pillar exists.
HEAD_FLOOR = 15

#: Striking distance counts this many times over in the recommendation: a
#: candidate already ranking 4–20 is the opportunity, and the tier it sits in
#: is where the plan should lean.
STRIKING_WEIGHT = 3

#: Branded phrases are navigational — the site ranks for its own name with or
#: without an article — so the recommendation caps them low, and lower once
#: the brand already ranks for one.
BRANDED_CAP = 20
BRANDED_WHEN_WON = 5

#: Buying intent: floor and cap. Informational pages are what earns links and
#: answer-engine citations; buying pages are what converts. Neither side of a
#: plan should be empty.
BUYING_FLOOR = 20
BUYING_CAP = 60


def _round5(x: float) -> int:
    return int(5 * round(float(x) / 5))


def _sum_to_100(shares: dict) -> dict:
    """Round each share to a multiple of 5 and make the trio sum to 100 by
    adjusting the largest — the one where five points is least visible."""
    out = {k: _round5(v) for k, v in shares.items()}
    diff = 100 - sum(out.values())
    if diff and out:
        top = max(out, key=lambda k: out[k])
        out[top] += diff
    return out


def is_branded(tenant: str, phrase: str, brand: set | None = None) -> bool:
    """Does this phrase name the brand? Read from the phrase, not from the
    stored intent, so a keyword harvested before the account had a domain is
    still counted as branded once it does."""
    toks = set(tokens(phrase))
    return bool(toks & (brand if brand is not None else brand_tokens_for(tenant)))


def mix_recommendation(tenant: str) -> dict:
    """The recommended mix, computed from the map as it stands, with its why.

    Returns `counts` (what the map holds), `recommended` (head / body /
    long_tail summing to 100, plus branded and buying as shares of the whole)
    and `why` (one sentence per number). `recommended` is None when the map
    has no candidates — nothing to recommend from is said, never defaulted.
    """
    brand = brand_tokens_for(tenant)
    positions = _latest_positions(tenant)
    state = cluster_state(tenant)
    rows = targets(tenant)
    cands = [r for r in rows if r.status == "candidate"
             and (r.owner_priority or "") != "muted"]
    tiers = ("head", "body", "long_tail")
    counts = {"candidates": len(cands),
              "tier": {t: 0 for t in tiers},
              "striking": {t: 0 for t in tiers},
              "published": {t: 0 for t in tiers},
              "branded": 0, "branded_won": 0, "buying": 0}
    weight = {t: 0.0 for t in tiers}
    buying_w = total_w = 0.0
    for r in rows:
        t = r.tier if r.tier in tiers else "body"
        pos = positions.get(r.phrase)
        done = r.status in ("published", "won")
        if done:
            counts["published"][t] += 1
        # Won once per phrase, whichever way it was won: a page that shipped,
        # or a reading in the top three.
        if is_branded(tenant, r.phrase, brand) and (
                done or (pos is not None and pos <= WON_POSITION)):
            counts["branded_won"] += 1
    for r in cands:
        t = r.tier if r.tier in tiers else "body"
        pos = positions.get(r.phrase)
        striking = pos is not None and 3 < pos <= 20
        counts["tier"][t] += 1
        if striking:
            counts["striking"][t] += 1
        w = STRIKING_WEIGHT if striking else 1
        weight[t] += w
        total_w += w
        if is_branded(tenant, r.phrase, brand):
            counts["branded"] += 1
        if r.intent in BUYING_INTENTS:
            counts["buying"] += 1
            buying_w += w
    why: list[str] = []
    if not cands:
        return {"counts": counts, "recommended": None,
                "why": ["no candidate keywords in the map — build the map "
                        "first; there is nothing to recommend a mix from"]}

    shares = {t: 100.0 * weight[t] / total_w for t in tiers}
    n = len(cands)
    why.append("of the %d candidates: %s" % (n, " · ".join(
        f"{counts['tier'][t]} {t.replace('_', '-')}" for t in tiers)))
    struck = sum(counts["striking"].values())
    if struck:
        why.append(f"{struck} already rank on page one or two (positions 4–20) "
                   f"and count {STRIKING_WEIGHT}× — that is where the plan "
                   f"should lean: " + ", ".join(
                       f"{counts['striking'][t]} {t.replace('_', '-')}"
                       for t in tiers if counts["striking"][t]))
    half_won = [c for c in state.values()
                if c.get("supports_published") and not c.get("pillar_published")
                and c.get("pillar")]
    if shares["head"] > HEAD_CAP:
        why.append(f"head terms capped at {HEAD_CAP}% — a head term is won with "
                   f"a pillar plus the supports that link into it, so the "
                   f"supports must outnumber the pillars")
        shares["head"] = float(HEAD_CAP)
    if half_won and counts["tier"]["head"] and shares["head"] < HEAD_FLOOR:
        why.append(f"head terms held at {HEAD_FLOOR}% — {len(half_won)} "
                   f"cluster(s) have published supports and no published "
                   f"pillar ({half_won[0]['pillar']!r}), and those supports "
                   f"link to nothing until it exists")
        shares["head"] = float(HEAD_FLOOR)
    rest = sum(v for t, v in shares.items() if t != "head")
    if rest > 0:
        scale = (100.0 - shares["head"]) / rest
        for t in ("body", "long_tail"):
            shares[t] *= scale
    else:
        shares["head"] = 100.0
    tier_rec = _sum_to_100(shares)

    if not counts["branded"]:
        branded = 0
        why.append("no branded phrases among the candidates — 0% branded")
    elif counts["branded_won"]:
        branded = BRANDED_WHEN_WON
        why.append(f"the brand already ranks for its own name — branded held "
                   f"at {BRANDED_WHEN_WON}%; a page each is enough")
    else:
        branded = min(BRANDED_CAP, _round5(100.0 * counts["branded"] / n))
        why.append(f"{counts['branded']} branded phrase(s) and nothing branded "
                   f"ranks yet — {branded}% branded, capped at {BRANDED_CAP}% "
                   f"because a site ranks for its own name with or without an "
                   f"article")

    if not counts["buying"]:
        buying = 0
        why.append("no buying-intent phrases among the candidates — 0% buying")
    else:
        raw = 100.0 * buying_w / total_w
        buying = max(BUYING_FLOOR, min(BUYING_CAP, _round5(raw)))
        why.append(f"{counts['buying']} phrase(s) carry buying intent "
                   f"({raw:.0f}% by weight) — {buying}% buying, held between "
                   f"{BUYING_FLOOR}% and {BUYING_CAP}% so neither the pages "
                   f"that earn links nor the pages that convert go missing")

    return {"counts": counts,
            "recommended": {**tier_rec, "branded": branded, "buying": buying},
            "why": why}


#: How deep a SERP we capture. Ten names everyone a page-one contender has to
#: pass; past that the domains are not competitors yet, and Semrush bills by
#: the LINE returned, so depth is half the cost of this feature.
RIVALS_DEPTH = 10

#: THE COST CONTROL, and the reason this feature is affordable at all. Rivals
#: are the one Semrush read charged PER PHRASE, so the population it runs over
#: has to be the words being worked and nothing wider. The owner set this scope
#: directly (2026-09-02): "just based on the words we're prioritizing. We dont
#: want an expensive solution that we dont actually need or use regularly."
#:
#: Twelve x ten lines is 120 lines per account per refresh. One `harvest()`
#: already pulls up to 880 Semrush lines (40 own + 200 gap + 8 seeds x 2
#: reports x 40), so a full rivals refresh costs about a seventh of one "Top up
#: the map" click — a button that already runs weekly, unattended.
RIVALS_MAX_PHRASES = 12

#: Do not re-ask about a phrase inside this window. A SERP does not turn over
#: fast enough for a fortnightly reading to miss anything that matters, and
#: without a gate the weekly sweep would pay the full price every Monday
#: forever, including on accounts where nothing has been published since.
RIVALS_EVERY_DAYS = 14


def _bare(domain: str) -> str:
    """A domain reduced to what two spellings of the same site share."""
    d = (domain or "").strip().lower()
    for cut in ("https://", "http://"):
        if d.startswith(cut):
            d = d[len(cut):]
    d = d.split("/")[0]
    return d[4:] if d.startswith("www.") else d


def rivals_scope(tenant: str, *, top: int = RIVALS_MAX_PHRASES) -> list[str]:
    """The words we are prioritising — the ONLY population rivals are read for.

    Both halves of "being worked", in the order they pay off. `attention` is
    published pages owed a move, where a rival is someone we are actively
    trying to pass; `next_to_write` is what the planner files next, where the
    rivals are who already owns the result we are about to enter. Both are
    already muted-excluded, pinned-first and priority-ordered, so this function
    inherits every decision the owner has made and invents no new ranking.

    `top` IS CLAMPED, not merely defaulted. `attention(top=)` and
    `next_to_write(top=)` both take a caller's number straight through, so a
    scope that only defaulted to the cap would let one wrong argument turn a
    120-line refresh into an unbounded charge — which is the exact shape of the
    `seeds=` overrun this work also fixed.
    """
    top = max(0, min(int(top or 0), RIVALS_MAX_PHRASES))
    if not top:
        return []
    ordered = [r["phrase"] for r in attention(tenant)] + list(next_to_write(tenant))
    seen, out = set(), []
    for phrase in ordered:
        low = (phrase or "").strip().lower()
        if not low or low in seen:
            continue
        seen.add(low)
        out.append(phrase)
    return out[:top]


def latest_serp(tenant: str, phrase: str):
    with db.SessionLocal() as s:
        return (s.query(db.KeywordSerp)
                .filter(db.KeywordSerp.tenant == tenant,
                        db.KeywordSerp.phrase == phrase)
                .order_by(db.KeywordSerp.at.desc()).first())


def _serp_fresh(tenant: str, phrase: str) -> bool:
    row = latest_serp(tenant, phrase)
    if row is None or not row.at:
        return False
    return (db.utcnow() - db.as_utc(row.at)).days < RIVALS_EVERY_DAYS


def rivals_refresh(tenant: str, *, top: int = RIVALS_MAX_PHRASES,
                   force: bool = False) -> dict:
    """Capture the SERP for the prioritised words. SPENDS API CALLS.

    Returns what it spent rather than what it found, because the number worth
    watching here is the bill: `fetched` is exactly the number of Semrush reads
    made, and it can never exceed `RIVALS_MAX_PHRASES`.

    A phrase whose fetch comes back empty is counted as `failed` and NOT
    stored. `_semrush` returns a SENTENCE on every failure — no key, timeout,
    plan limit — and `_json_rows` turns each of those into `[]`, so an
    unconfigured account would otherwise write a row saying "nobody ranks for
    this", which reads as a won SERP rather than as a broken one.
    """
    from . import sites
    profile = sites.get(tenant)
    own = _bare(profile.get("domain", ""))
    scope = rivals_scope(tenant, top=top)
    fetched = skipped = failed = 0
    for phrase in scope:
        if not force and _serp_fresh(tenant, phrase):
            skipped += 1
            continue
        rows = _fetch_serp(profile, phrase, RIVALS_DEPTH)
        fetched += 1
        if not rows:
            failed += 1
            continue
        ours, rivals = None, []
        for r in rows:
            dom = _bare(str(r.get("domain") or ""))
            try:
                pos = float(r.get("position") or 0) or None
            except (TypeError, ValueError):
                pos = None
            if not dom or pos is None:
                continue
            if own and dom == own:
                ours = pos if ours is None else min(ours, pos)
                continue
            rivals.append({"domain": dom, "position": pos,
                           "url": str(r.get("url") or "")})
        with db.SessionLocal() as s:
            s.add(db.KeywordSerp(
                tenant=tenant, phrase=phrase,
                database=profile.get("database", "") or "",
                our_position=ours, depth=len(rows), rivals=rivals))
            s.commit()
    return {"tenant": tenant, "scope": len(scope), "fetched": fetched,
            "skipped": skipped, "failed": failed, "cap": RIVALS_MAX_PHRASES,
            "depth": RIVALS_DEPTH}


def overtaking(tenant: str) -> list[dict]:
    """Who is ahead of us, and how many we have passed since the first reading.

    THE MEASURE OF SUCCESS, and the reason a baseline is kept rather than only
    the newest capture. "Six sites ahead" is a static number of the kind the
    Architecture page was already full of; "six ahead, two passed since June"
    is the same reading turned into a direction of travel.

    Reads only. Nothing here can spend an API call, which is what makes it safe
    to render on a page.
    """
    with db.SessionLocal() as s:
        rows = (s.query(db.KeywordSerp)
                .filter(db.KeywordSerp.tenant == tenant)
                .order_by(db.KeywordSerp.at.asc()).all())
        by_phrase: dict[str, list] = {}
        for r in rows:
            by_phrase.setdefault(r.phrase, []).append(
                {"at": db.as_utc(r.at), "our_position": r.our_position,
                 "rivals": list(r.rivals or [])})

    def _ahead(cap) -> set:
        pos = cap["our_position"]
        return {v["domain"] for v in cap["rivals"]
                if pos is None or (v.get("position") or 0) < pos}

    out = []
    for phrase, caps in by_phrase.items():
        first, last = caps[0], caps[-1]
        ahead_now = _ahead(last)
        passed = sorted(_ahead(first) - ahead_now)
        ranked = sorted(
            [v for v in last["rivals"] if v["domain"] in ahead_now],
            key=lambda v: v.get("position") or 99)
        out.append({
            "phrase": phrase,
            "our_position": last["our_position"],
            "ahead": ranked,
            "ahead_count": len(ahead_now),
            "passed": passed,
            "passed_count": len(passed),
            # A single capture has no baseline to have moved from, and saying
            # "0 passed" of one reading is the same false precision the static
            # numbers on this page already carried.
            "has_baseline": len(caps) > 1,
            "at": last["at"], "since": first["at"],
        })
    out.sort(key=lambda d: (-d["passed_count"], d["our_position"] or 999))
    return out


def mute_effect(tenant: str, phrase: str, before: list, *,
                top: int = 12) -> dict:
    """What muting actually changed on the board, computed from before/after.

    Owner, 2026-09-02: *"I want updates for muting some keywords to be pulled
    and replaced by high opportunity keywords that aren't already on the board
    but grow from those clusters."*

    REPORTED, NOT PROMISED. The obvious implementation picks "the best
    candidate in that cluster" and announces it — and is wrong whenever the
    board was not full, whenever the cluster is exhausted, or whenever the
    keyword that actually surfaced came from somewhere else because the muted
    one was not in the last slot. This reads the board on both sides of the
    change and names what genuinely appeared, which is the only version that
    cannot mislead.

    A mute that surfaced NOTHING is a real and useful answer: the cluster has
    no more candidates, which is an authoring or harvest gap rather than a
    silence.
    """
    rows = {r.phrase: r for r in targets(tenant)}
    muted = rows.get(phrase)
    cluster = (muted.cluster_key or "") if muted is not None else ""
    after = next_to_write(tenant, top=top)
    fresh = [p for p in after if p not in set(before)]
    same_cluster = [p for p in fresh
                    if (rows.get(p) and (rows[p].cluster_key or "") == cluster
                        and cluster)]
    # What the cluster still holds that nothing is offering — the honest
    # answer to "is there more here", separate from what surfaced today.
    held = [r.phrase for r in targets(tenant)
            if cluster and (r.cluster_key or "") == cluster
            and r.status == "candidate"
            and (r.owner_priority or "") != "muted"
            and r.phrase not in set(after)]
    return {"cluster": cluster, "surfaced": fresh,
            "from_cluster": same_cluster, "still_held": held}


def board(tenant: str, *, days: int = 7, top: int = 12) -> dict:
    """The map, split into the four questions worth asking of it."""
    rows = targets(tenant)
    by_phrase = {r.phrase: r for r in rows}
    now, then = _period_readings(tenant, days)

    def _row(r, extra: dict | None = None) -> dict:
        pos = (now.get(r.phrase).position if now.get(r.phrase) else None)
        return {"phrase": r.phrase, "tier": r.tier, "intent": r.intent,
                "role": r.role, "cluster": r.cluster_key, "status": r.status,
                "volume": r.volume, "difficulty": r.difficulty,
                "priority": r.priority, "parts": r.priority_parts or {},
                "position": pos, "target_url": r.target_url,
                "owner_priority": r.owner_priority or "",
                "output_id": r.output_id, **(extra or {})}

    # --- what to write next, and the arithmetic behind the order ----------
    #
    # MUTED IS EXCLUDED, not sorted last. Ranking a ruled-out keyword bottom
    # still puts it on the page, so a decision already made is re-presented
    # every week — which is the thing a mute was supposed to stop. It has its
    # own section, with the count and a way back.
    live = [r for r in rows if (r.owner_priority or "") != "muted"]
    # Through `next_to_write`, so the board and the mute route cannot disagree
    # about what is currently being offered.
    _offered = set(next_to_write(tenant, top=top))
    writing_next = [_row(r) for r in live
                    if r.status == "candidate" and r.phrase in _offered][:top]

    # --- what changed since last week -------------------------------------
    moved_up, moved_down, entered = [], [], []
    for phrase, a in now.items():
        r = by_phrase.get(phrase)
        b = then.get(phrase)
        if r is None or a.position is None:
            continue
        if b is None or b.position is None:
            # Ranking at all, for the first time we have a reading for.
            entered.append(_row(r, {"to": a.position}))
            continue
        gain = round(b.position - a.position, 1)
        if gain >= 1:
            moved_up.append(_row(r, {"from": b.position, "to": a.position, "gain": gain}))
        elif gain <= -1:
            moved_down.append(_row(r, {"from": b.position, "to": a.position, "gain": gain}))
    moved_up.sort(key=lambda x: -x["gain"])
    moved_down.sort(key=lambda x: x["gain"])

    # --- new to the map this week -----------------------------------------
    import datetime as dt
    cutoff = db.utcnow() - dt.timedelta(days=days)
    fresh = [_row(r) for r in rows
             if r.first_seen and db.as_utc(r.first_seen) >= cutoff]
    fresh.sort(key=lambda x: -(x["priority"] or 0))

    # --- the unclaimed backlog, by tier -----------------------------------
    opportunities: dict[str, list] = {}
    for r in live:
        if r.status != "candidate":
            continue
        opportunities.setdefault(r.tier or "?", []).append(_row(r))
    for v in opportunities.values():
        v.sort(key=lambda x: -(x["priority"] or 0))

    # --- which keyword each article was written for ------------------------
    in_flight = [_row(r) for r in rows
                 if r.status in ("planned", "published", "won")]
    in_flight.sort(key=lambda x: ({"won": 0, "published": 1, "planned": 2}
                                  .get(x["status"], 3), -(x["priority"] or 0)))

    counts: dict[str, int] = {}
    for r in rows:
        counts[r.status] = counts.get(r.status, 0) + 1

    return {
        "tenant": tenant, "window_days": days, "keywords": len(rows),
        "counts": counts,
        "writing_next": writing_next,
        "moved": {"up": moved_up[:top], "down": moved_down[:top],
                  "entered": entered[:top],
                  "note": ("position movement from Search Console readings. "
                           "Priority history is not stored, so this is what "
                           "changed in the RANKINGS, not what changed in the "
                           "plan's opinion of them.")},
        "new_this_week": fresh[:top],
        "opportunities": opportunities,
        "in_flight": in_flight,
        # WHAT A PUBLISHED PAGE IS OWED. `writing_next` answers "what should
        # we write"; nothing answered "what did we write that is not working",
        # which is where more winning pages actually come from.
        "attention": attention(tenant, top=top),
        "muted": [_row(r) for r in rows
                  if (r.owner_priority or "") == "muted"],
        "lessons": mute_lessons(tenant),
    }


# ---------------------------------------------------------------------------
# What a mute is worth — filed away, and read once there are enough of them
# ---------------------------------------------------------------------------
#
# Owner, 2026-08-26: *"how can we learn from muted/removed keywords? or just
# make sure they are filed away somewhere else not distracting"*. Both, and
# the second one first: a muted keyword sorted LAST but still appeared in
# Writing next and Opportunities, so a decision already made was re-presented
# every week. That is the thing a mute was supposed to stop.
#
# The learning half is a proposal, never an action. One mute is a preference;
# a dozen sharing a word is a pattern, and the word is a candidate for
# `exclude_terms` — which `semrush_opportunity_finder` already accepts, so the
# harvest can stop surfacing it at the source rather than the owner muting the
# same family of phrase every Monday.

#: Below this, a shared word is a coincidence. Three keywords sharing "wedding"
#: on a venue account says something; two says the alphabet is small.
MUTE_PATTERN_MIN = 3


def muted(tenant: str) -> list:
    """Everything the owner has ruled out, newest decision first."""
    return [r for r in targets(tenant) if (r.owner_priority or "") == "muted"]


def mute_lessons(tenant: str) -> dict:
    """What the mutes have in common — as proposals for a person to accept.

    Three questions, and each has a different remedy:

      a shared WORD      -> an exclude term, so the harvest stops finding that
                            family at all;
      a shared SOURCE    -> that harvester is producing noise for this account;
      a shared CLUSTER   -> the cluster itself is off-topic, and the pillar is
                            probably the mistake rather than its supports.

    Nothing here changes anything. An `exclude_terms` entry silently added
    from a pattern would quietly shrink every future harvest, and the owner
    would have no way to know why a keyword stopped appearing.
    """
    rows = muted(tenant)
    out: dict = {"muted": len(rows), "enough_to_read": len(rows) >= MUTE_PATTERN_MIN,
                 "terms": [], "sources": [], "clusters": []}
    if not out["enough_to_read"]:
        out["note"] = (f"{len(rows)} muted — under {MUTE_PATTERN_MIN} a shared "
                       f"word is a coincidence, not a pattern.")
        return out

    already = set()
    try:
        from . import sites
        already = {t.lower() for t in (sites.get(tenant).get("exclude_terms") or [])}
    except Exception:                                            # noqa: BLE001
        pass

    # NEVER THE BRAND'S OWN WORDS. Three muted "wedding … miami" phrases for
    # Miami Ironside proposed excluding "miami" — the account's own city, in
    # its name and its domain. An exclude term is a negative keyword, and a
    # brand cannot be negative about itself.
    brand = brand_tokens_for(tenant)

    word_hits: dict[str, list] = {}
    for r in rows:
        for w in set(tokens(r.phrase)):
            word_hits.setdefault(w, []).append(r.phrase)
    for w, hits in sorted(word_hits.items(), key=lambda kv: -len(kv[1])):
        if len(hits) < MUTE_PATTERN_MIN or w in already or w in brand:
            continue
        # A word that ALSO appears in what we are actively writing is not a
        # negative keyword, it is a common noun. "jug" would otherwise be
        # excluded off the back of three muted jug phrases.
        live = [r.phrase for r in targets(tenant)
                if (r.owner_priority or "") != "muted" and w in tokens(r.phrase)]
        if live:
            continue
        out["terms"].append({"term": w, "muted_with_it": hits[:6],
                             "proposal": f"add {w!r} to this account's "
                                         f"exclude_terms so the harvest stops "
                                         f"surfacing it"})

    src: dict[str, int] = {}
    for r in rows:
        if r.source:
            src[r.source] = src.get(r.source, 0) + 1
    total_by_src: dict[str, int] = {}
    for r in targets(tenant):
        if r.source:
            total_by_src[r.source] = total_by_src.get(r.source, 0) + 1
    for s, n in sorted(src.items(), key=lambda kv: -kv[1]):
        whole = total_by_src.get(s, n)
        if n >= MUTE_PATTERN_MIN and whole and n / whole >= 0.5:
            out["sources"].append({
                "source": s, "muted": n, "found": whole,
                "proposal": f"{n} of {whole} keywords from {s} were muted — "
                            f"that harvester is mostly noise for this account"})

    clus: dict[str, int] = {}
    for r in rows:
        if r.cluster_key:
            clus[r.cluster_key] = clus.get(r.cluster_key, 0) + 1
    for c, n in sorted(clus.items(), key=lambda kv: -kv[1]):
        members = [r for r in targets(tenant) if r.cluster_key == c]
        if n >= MUTE_PATTERN_MIN and members and n / len(members) >= 0.5:
            pillar = next((r.phrase for r in members if r.role == "pillar"), c)
            out["clusters"].append({
                "cluster": c, "muted": n, "of": len(members),
                "proposal": f"most of the {c!r} cluster is muted — the pillar "
                            f"{pillar!r} is likely the mistake, not its supports"})
    return out


# ---------------------------------------------------------------------------
# The publish write-back — the loop's missing wire
# ---------------------------------------------------------------------------
def mark_published(tenant: str, output_id: str, url: str = "",
                   article_id: str = "") -> dict:
    """An article went live: tell every table that has been waiting to hear.

    THE LOOP WAS OPEN HERE AND NOTHING SAID SO. The audit of 2026-08-26 found
    that no production code had ever written `KeywordTarget.target_url`,
    `published_at`, or `status="published"` — the approval executor sent the
    live URL into a WhatsApp message and discarded it. Consequences, each
    silent: the Plan board's "live page" link could never render; `progress`
    attributes only rows with status published/won, so its tracked cohort was
    structurally starved and every report would have read "no tracked
    readings" forever; and the cluster bonus for a published pillar could
    never fire off a real publish.

    One function, called from BOTH publish paths — the approval executor and
    the manual mark-as-published — so the write-back cannot drift between
    them. It touches this module's own tables directly and goes through
    `ledger.publish` for the Output row, keeping one writer per table.
    """
    from . import edits, ledger
    out: dict = {"tenant": tenant, "output_id": output_id, "url": url}
    with db.SessionLocal() as s:
        row = (s.query(db.KeywordTarget)
               .filter(db.KeywordTarget.tenant == tenant,
                       db.KeywordTarget.output_id == output_id).first())
        if row is not None:
            row.status = "published"
            # FIRST PUBLICATION STAYS FIRST PUBLICATION. Overwriting it made a
            # refreshed page read as brand new — `attention` would call it
            # `too_early` for another month and "days live" would be a lie
            # about a page that has been up for a year. A re-publish of a page
            # that already had a date is a REFRESH, and `refreshed_at` is the
            # field for it: it drives the cooldown, and it is the only way
            # "did refreshing work?" can ever be answered.
            #
            # Derived from the data rather than passed in, because the caller
            # that knows is not the caller that publishes: the executor and
            # the hand-carried "It's live here" both arrive here saying only
            # that a page went up.
            if row.published_at is None:
                row.published_at = db.utcnow()
            else:
                row.refreshed_at = db.utcnow()
                out["refresh"] = True
            if url:
                row.target_url = url
            # THE ID IS WHAT MAKES THE NEXT WRITE A REVISION. Without it a
            # refresh can only propose a create, which on a connected store
            # publishes a second page beside the one that ranks. Written here
            # because this is already the one function both publish paths
            # call, so the id cannot be captured on one and lost on the other.
            if article_id:
                row.cms_article_id = str(article_id)
            out["phrase"] = row.phrase
            run_id = row.run_id
        else:
            out["phrase"] = ""
            run_id = ""
        art = (s.query(db.ArtifactBody)
               .filter(db.ArtifactBody.output_id == output_id).first())
        draft, final = ((art.draft_body or "", art.body or "")
                        if art is not None else ("", ""))
        if art is not None and url:
            art.destination = url
        s.commit()

    ledger.publish(tenant, output_id, destination=url)

    # The declared measure, finally computed: draft vs what actually shipped.
    # Onto the RUN, because "is this system getting better" is the question
    # `SystemRun.edit_diff` was added for — same landing as the mail path's.
    if draft and final:
        d = edits.delta(draft, final)
        out["edit"] = {k: d.get(k) for k in ("as_is", "similarity",
                                             "lines_changed") if k in d}
        if run_id and d.get("measured"):
            try:
                with db.SessionLocal() as s:
                    run = s.get(db.SystemRun, run_id)
                    if run and not run.edit_diff:
                        run.edit_diff = d.get("sample") or (
                            "published unchanged" if d.get("as_is") else "")
                        run.decision = run.decision or (
                            "approved" if d.get("as_is") else "edited")
                        s.commit()
            except Exception:                                    # noqa: BLE001
                pass      # measuring must never block a publish
    return out
