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
        return rows


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


def _fetch_gap(profile: dict, limit: int) -> list[dict]:
    """Where the site already ranks but not well — Semrush's own
    striking-distance report, which is the market's view of the same question
    `_fetch_gsc` answers from your own data."""
    from . import seo_guard, seo_tools
    return _json_rows(seo_tools.semrush_opportunity_finder(
        domain=profile.get("domain", ""), database=profile.get("database", ""),
        limit=limit, exclude_terms=profile.get("exclude_terms") or [],
        _tenant=seo_guard.tenant_for(profile)))


#: GSC positions worth harvesting as targets. Below 3 is won; past 40 the
#: query is not really about this site yet.
STRIKING_BAND = (3.0, 40.0)


def harvest(tenant: str, *, seeds: tuple = (), sources: tuple = (
        "gsc", "gap", "related", "questions"), days: int = 28,
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
            if pos is not None and STRIKING_BAND[0] < pos <= STRIKING_BAND[1]:
                upsert(tenant, phrase, source="gsc_striking",
                       database=profile.get("database", ""))
                added["gsc"] += 1

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
        pool = list(seeds) or [r.phrase for r in targets(tenant)
                               if r.tier in ("head", "body")][:8]
        if not pool:
            notes.append("no seeds and no head terms yet — run with "
                         "sources=('gsc','gap') first, or pass seeds=")
        for seed in pool:
            if "related" in sources:
                for r in _fetch_related(profile, seed, limit):
                    if r.get("keyword"):
                        upsert(tenant, r["keyword"], source="semrush_related",
                               volume=int(r.get("volume") or 0),
                               cpc=float(r.get("cpc") or 0.0),
                               database=profile.get("database", ""))
                        added["related"] += 1
            if "questions" in sources:
                for r in _fetch_questions(profile, seed, limit):
                    if r.get("question"):
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
            if pos <= WON_POSITION and row.status in ("published", "planned"):
                row.status, won = "won", won + 1
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

    return {
        "tenant": tenant, "window_days": days,
        "goal": against,
        "tracked": tracked, "control": control,
        "wins": {"top3": top3, "top10": top10, "by_tier": by_tier},
        "movements": moves[:50],
        "attributable": len(moves) - too_early,
        "too_early_to_attribute": too_early,
        "notes": notes}


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


def harvest_all(*, limit: int = 40) -> dict:
    """Top up every account's map that is due, on the weekly schedule.

    Only accounts that ALREADY have a map. A first harvest stays a deliberate
    act — it is the moment somebody decides this account is being worked on,
    and starting one automatically would spend a client's Semrush quota on a
    map nobody asked for.
    """
    from . import systems, tenants
    out: dict[str, dict] = {}
    for t in tenants.all_tenants():
        if not systems.find(t.key, "blog"):
            continue
        if not harvest_due(t.key):
            out[t.key] = {"skipped": "topped up within the last "
                                     f"{HARVEST_EVERY_DAYS} days"}
            continue
        try:
            out[t.key] = harvest(t.key, limit=limit)
        except Exception as exc:  # noqa: BLE001 — one account must not stop the rest
            out[t.key] = {"error": f"{exc.__class__.__name__}: {str(exc)[:140]}"}
    return out


def sync_all(*, days: int = 28) -> dict:
    """Every account whose blog system is installed and whose CMS is wired.

    Scoped to those two facts on purpose. Syncing an account with no blog
    system spends a client's Search Console quota on a map nobody is writing
    against, and an account with no CMS cannot have published anything for the
    readings to be about.
    """
    from . import systems, tenants
    out: dict[str, dict] = {}
    for t in tenants.all_tenants():
        if not systems.find(t.key, "blog"):
            continue
        # Gated on having a MAP, not on having a CMS. The first version
        # checked `cms`, which is the wrong question twice over: Search
        # Console reports on a domain whether or not we can write to it, and
        # a site with rankings we did not publish is exactly the baseline this
        # loop needs. What makes a sync pointless is nothing to measure.
        if not targets(t.key):
            out[t.key] = {"skipped": "no keyword map — nothing to measure"}
            continue
        try:
            out[t.key] = sync(t.key, days=days)
        except Exception as exc:  # noqa: BLE001 — one account must not stop the rest
            out[t.key] = {"error": f"{exc.__class__.__name__}: {str(exc)[:140]}"}
    return out


# ---------------------------------------------------------------------------
# Readiness — can this account actually run the blog pipeline, end to end
# ---------------------------------------------------------------------------
#
# `systems.ready()` answers whether the SYSTEM may run: it checks the `requires`
# the catalogue declares, which for `blog` is `cms`. That is the right gate for
# PUBLISHING and it is not the whole pipeline, because the measurement half
# needs Search Console and no catalogue field says so.
#
# Making `analytics` a hard `requires` would be worse, not better: it would
# refuse to publish an article because nobody had connected the thing that
# reports on it afterwards. Publishing and measuring fail independently and
# should be reported independently — which is what this does.

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
                pub["fix"] = ("a store can hold several blogs and the skill "
                              "refuses to guess — call list_blogs, then set it "
                              "with /admin/tenant_set")
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
        problems.append("no keyword map — run /admin/keywords_harvest")
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
