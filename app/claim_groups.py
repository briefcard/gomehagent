"""Claim groups — one claim, every place and every wording it appears in.

Owner, 2026-11-06: *"the goal is to be able to quickly understand where
mistruths exist by grouping mistruths or inconsistent language and being able
to surgically replace, update or remove it. We need at least 99% accuracy as
we will be using this to assess compliance."* Design: BUILD-MAP §16.

THREE KINDS OF GROUP

* **inconsistency** — the same sentence frame stated with a DIFFERENT number,
  or with and without a negation ("coverage across 25+ countries" / "coverage
  across 160+ countries"; "we charge no fees" / "we charge fees"). These are
  the mistruth candidates and come first.
* **variants** — the same claim in different wording (punctuation, case, or —
  proposed only — different words with the same meaning).
* **family** — one pattern with a different VALUE per member ("Transak supports
  USDC on {Sui, Apechain, …}"). Each member is its own fact; the family is one
  review item listing every value. Never treated as duplicates.

HOW 99% IS EARNED, NOT ASSERTED

1. **Hard blocking first.** Embeddings cannot see numbers or "not" (BUILD-MAP
   §16.2), so two claims are only ever VARIANTS if their numbers, negation and
   product scope are identical. A different number is never a variant.
2. **Automatic grouping only by deterministic, explainable rules** (`METHODS`):
   identical after normalisation; identical except one numeric slot or a
   negation (inconsistency); identical except one non-numeric slot (family).
3. **Similarity-only matches are PROPOSALS** a reviewer confirms. They become
   automatic only when that method's measured precision — every reviewer
   decision is a label — has a 95% Wilson lower bound of at least 99%.
4. **Every method is measured the same way**, deterministic ones included. A
   method whose lower bound falls below 99% after enough labels stops
   grouping automatically and its groups become proposals (fail closed).

SURGICAL FIXES

A decision on a group ("this wording is right", "remove everywhere") creates a
change (`change.py`) with one task per wording per page: the exact wording to
find and its replacement (or removal). A task on a connected store can be
proposed as an approval; every task closes only when the page, read again, no
longer carries the old wording.
"""
from __future__ import annotations

import datetime as dt
import math
import re
import unicodedata

from . import db
from . import provenance as prov

#: The rules, each measured separately (`accuracy`). `auto` = may group without
#: a person while its measured precision holds.
METHODS = {
    "normalised_equal":  {"kind": "variants", "auto": True,
                          "why": "the same words once case, spacing and punctuation are ignored"},
    "number_slot":       {"kind": "inconsistency", "auto": True,
                          "why": "the same sentence with a different number"},
    "negation":          {"kind": "inconsistency", "auto": True,
                          "why": "the same sentence with and without a negation"},
    "value_slot":        {"kind": "family", "auto": True,
                          "why": "the same sentence with one different name or value"},
    "similar_wording":   {"kind": "variants", "auto": False,
                          "why": "nearly the same words, differing beyond a number or a single value"},
    "similar_meaning":   {"kind": "variants", "auto": False,
                          "why": "different words, very similar meaning (embedding similarity)"},
    "similar_frame_different_number": {"kind": "inconsistency", "auto": False,
                          "why": "very similar sentences stating a different number"},
}
#: Similarity proposal band (claim-matching practice: 0.88 ≈ 95% precise).
PROPOSE_AT = 0.88
#: Accuracy bar and the labels needed before a method's auto status is judged.
TARGET = 0.99
MIN_LABELS = 30
#: Smallest family worth one review item.
FAMILY_MIN = 3

_NEG = {"not", "no", "never", "without", "cannot", "can't", "don't", "doesn't", "isn't",
        "aren't", "won't", "nor", "none", "zero", "neither"}
_AUX = {"do", "does", "did", "is", "are", "was", "were", "will", "can", "could", "would",
        "should", "has", "have", "had", "may", "might", "must", "shall"}
_NUM = re.compile(r"^[$€£¥]?\d[\d,]*(?:\.\d+)?(?:\+|%|k|m|bn|x)?$", re.I)
_URL = re.compile(r"https?://[^\s,;)\"']+")


def _now():
    return dt.datetime.now(dt.timezone.utc)


# --- reading one claim ----------------------------------------------------

def canon(text: str) -> str:
    """The claim's words with case, spacing, quotes and trailing punctuation
    normalised — "Transak supports USDC on Sui." == "transak supports usdc on sui"."""
    t = unicodedata.normalize("NFKC", text or "").lower()
    t = t.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    t = re.sub(r"(\d)\s+\+", r"\1+", t)                 # "136 +" -> "136+"
    t = re.sub(r"(\d),(\d{3})", r"\1\2", t)             # 1,200 -> 1200
    t = re.sub(r"[^\w\s$€£¥%+.'-]", " ", t)
    t = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", t)           # full stops, not decimals
    return " ".join(t.split())


def tokens(text: str) -> list[str]:
    return canon(text).split()


#: A number right after one of these words LABELS something (Step 2, Q3,
#: Tier 1, Version 4) — it does not measure anything, so it never makes two
#: sentences contradict each other.
_LABEL_WORDS = {"step", "steps", "tier", "phase", "part", "version", "v", "chapter",
                "section", "clause", "article", "q1", "q2", "q3", "q4", "q", "level",
                "plan", "page", "slide", "figure", "table", "item", "no", "number",
                "id", "#", "round", "season", "episode", "day", "week", "month", "year"}


def _is_measure(toks: list[str], i: int) -> bool:
    """Does the number at toks[i] MEASURE something (a count, amount, share)?
    Years, labels and identifiers do not."""
    t = toks[i]
    if not _NUM.match(t):
        return False
    bare = t.strip("$€£¥+%").replace(",", "")
    try:
        val = float(re.sub(r"[a-z]+$", "", bare))
    except ValueError:
        return False
    if re.fullmatch(r"(19|20)\d\d", bare):
        return False                                   # a year
    if len(re.sub(r"\D", "", bare)) >= 6 and not t.endswith(("+", "%")) and not t.startswith(("$", "€", "£")):
        return False                                   # an identifier
    if i > 0 and toks[i - 1] in _LABEL_WORDS:
        return False                                   # a label
    return val is not None


def signature(text: str) -> dict:
    """What must be IDENTICAL for two claims to be the same claim.

    `numbers` are the MEASURES only (counts, amounts, shares); a year, a step
    or section label and an identifier stay literal in the frame, so "Step 1
    Connect" and "Step 2 Connect" are different sentences, never a
    contradiction."""
    toks = tokens(text)
    measure = [_is_measure(toks, i) for i in range(len(toks))]
    nums = tuple(t for t, m in zip(toks, measure) if m)
    neg = any(t in _NEG for t in toks) or "n't" in canon(text)
    # The negation and the helper verb it needs ("do not", "is not", "can't")
    # leave the frame, so "We do not charge fees" and "We charge fees" share it.
    # Helper verbs leave every frame (they carry no claim), and a trailing "s"
    # is folded ("stores" / "doesn't store"), the same on both sides.
    def _fold(t: str) -> str:
        return t[:-1] if len(t) > 3 and t.endswith("s") and not t.endswith("ss") else t
    frame = " ".join("{N}" if m else _fold(t) for t, m in zip(toks, measure)
                     if not (t in _NEG or t.endswith("n't") or t in _AUX))
    return {"tokens": toks, "numbers": nums, "negated": neg, "frame": frame}


def pages_of(row) -> list[str]:
    """Every page a claim was read on: its source and each corroborating one."""
    refs = [getattr(row, "source", "") or ""]
    refs += [str(e.get("ref") or "") for e in (getattr(row, "also_seen", None) or [])
             if isinstance(e, dict)]
    out = []
    for r in refs:
        for u in _URL.findall(r):
            u = u.rstrip(".")
            if u not in out:
                out.append(u)
    return out


def authority(url: str) -> int:
    """Lower is more authoritative: legal 0, product/marketing 1, docs 2,
    help 3, newsletter 4, blog/news/press 5 (BUILD-MAP §16.2 survivorship)."""
    from . import compliance
    u = (url or "").lower()
    if compliance.is_legal_url(u):
        return 0
    if "newsletter." in u:
        return 4
    if re.search(r"/(blog|news|press|articles?)(/|$)", u):
        return 5
    if "docs." in u or "/docs" in u:
        return 2
    if "support." in u or "help." in u or "/help" in u:
        return 3
    return 1


def _rank(c) -> tuple:
    pages = pages_of(c)
    return (min((authority(u) for u in pages), default=9), -len(pages), c.id)


# --- the grouping ---------------------------------------------------------

def _live_claims(tenant: str) -> list:
    with db.SessionLocal() as s:
        rows = (s.query(db.KbClaim)
                .filter(db.tenant_filter(db.KbClaim, tenant),
                        db.KbClaim.review.in_((prov.PROPOSED, prov.APPROVED)))
                .order_by(db.KbClaim.id).all())
        s.expunge_all()
    return [r for r in rows if (r.status or "") not in ("retired", "rejected")]


def method_is_auto(stats: dict, method: str) -> bool:
    """A method groups without a person only while its measured precision
    holds. Deterministic rules start trusted and lose it on evidence; a
    similarity rule must EARN it (fail closed)."""
    m = stats.get(method) or {}
    n, lb = m.get("labels", 0), m.get("lower_bound")
    if METHODS[method]["auto"]:
        return not (n >= MIN_LABELS and lb is not None and lb < TARGET)
    return n >= MIN_LABELS and lb is not None and lb >= TARGET


#: Words that qualify a figure: changing one changes the claim ("25" vs
#: "over 25"), so a difference in them is an inconsistency, not a rewording.
_QUALIFIERS = {"over", "more", "than", "up", "to", "at", "least", "around", "about",
               "nearly", "almost", "approximately", "under", "below", "above", "+", "plus"}
#: Lexical candidate cut-off (RapidFuzz token_sort_ratio, 0-100). Every pair
#: below it is unrelated; every pair above it is CLASSIFIED, never trusted.
CANDIDATE_AT = 85
#: Complete-linkage distance for groups: every member within this of every
#: other (1 - similarity), so a group cannot chain (BUILD-MAP §16.2).
LINK_DISTANCE = 0.15


def _figures(toks: list[str]) -> str:
    """The measures in a sentence with the qualifier before each ("over 25",
    "26+"), for showing what differs between two versions."""
    out = []
    for i, t in enumerate(toks):
        if _is_measure(toks, i):
            q = []
            j = i - 1
            while j >= 0 and toks[j] in _QUALIFIERS and len(q) < 2:
                if toks[j] == "to" and not (j > 0 and toks[j - 1] == "up"):
                    break                       # "to 130+" is a preposition, "up to" a qualifier
                q.insert(0, toks[j])
                j -= 1
            out.append(" ".join(q + [t]))
    return ", ".join(out)


def _span(ta: list[str], tb: list[str]) -> tuple[int, int, int]:
    """(start, end in a, end in b) of the ONE stretch where two token lists
    differ, between their common beginning and common end."""
    p = 0
    while p < min(len(ta), len(tb)) and ta[p] == tb[p]:
        p += 1
    q = 0
    while q < min(len(ta), len(tb)) - p and ta[-1 - q] == tb[-1 - q]:
        q += 1
    return p, len(ta) - q, len(tb) - q


def classify(a: str, b: str) -> tuple[str, str, str]:
    """What separates two similar claims: (method, value in a, value in b).

    The DIFFERENCE decides, never the similarity score alone: RapidFuzz scores
    97 for a rewording, for a different fact ("to BHD" / "to BMD") and for a
    contradiction ("25" / "over 25") alike. "" = blocked: never one group."""
    from rapidfuzz.distance import Levenshtein
    ta, tb = tokens(a), tokens(b)
    if ta == tb:
        return "normalised_equal", "", ""
    ops = [o for o in Levenshtein.opcodes(ta, tb) if o.tag != "equal"]
    ia = [i for o in ops for i in range(o.src_start, o.src_end)]
    ib = [i for o in ops for i in range(o.dest_start, o.dest_end)]
    da, db_ = [ta[i] for i in ia], [tb[i] for i in ib]
    changed = da + db_
    meas = [_is_measure(ta, i) for i in ia] + [_is_measure(tb, i) for i in ib]
    # A changed token with digits that is NOT a measure is an identifier, a
    # year or a label: two different records, never one claim.
    if any(re.search(r"\d", t) and not m for t, m in zip(changed, meas)):
        return "", "", ""
    if changed and all(m or t in _QUALIFIERS for t, m in zip(changed, meas)):
        return "number_slot", _figures(ta), _figures(tb)
    if changed and all(t in _NEG or t.endswith("n't") or t in _AUX for t in changed):
        return "negation", ("negated" if any(t in _NEG or t.endswith("n't") for t in da) else "affirmed"), \
            ("negated" if any(t in _NEG or t.endswith("n't") for t in db_) else "affirmed")
    p, ea, eb = _span(ta, tb)
    va, vb = ta[p:ea], tb[p:eb]
    if (1 <= len(va) <= 4 and 1 <= len(vb) <= 4 and not any(meas)
            and not set(va + vb) & (_QUALIFIERS | _NEG | _AUX)):
        return "value_slot", " ".join(va), " ".join(vb)
    sa, sb = signature(a), signature(b)
    if sa["negated"] != sb["negated"]:
        return "", "", ""
    if sa["numbers"] != sb["numbers"]:
        if sa["numbers"] and sb["numbers"]:
            return "similar_frame_different_number", _figures(ta), _figures(tb)
        return "", "", ""
    return "similar_wording", "", ""


def _complete_link(ids: list[str], dist) -> list[list[str]]:
    """Clusters in which EVERY member is within LINK_DISTANCE of every other
    (scikit-learn, complete linkage). One bridging pair can never join two
    unrelated groups, which is how connected components over-merge."""
    if len(ids) < 3:
        return [ids]
    import numpy as np
    from sklearn.cluster import AgglomerativeClustering
    D = np.array([[0.0 if a == b else dist(a, b) for b in ids] for a in ids])
    labels = AgglomerativeClustering(n_clusters=None, distance_threshold=LINK_DISTANCE,
                                     metric="precomputed", linkage="complete").fit_predict(D)
    out: dict[int, list] = {}
    for cid, lab in zip(ids, labels):
        out.setdefault(int(lab), []).append(cid)
    return list(out.values())


def compute(tenant: str, use_embeddings: bool = True) -> list[dict]:
    """Every group the claims imply now. Pure read; `rebuild` stores it.

    1. Candidates: every pair of claims RapidFuzz scores at CANDIDATE_AT or
       above (one batched `cdist`, ~1 s for Transak's 1,823 claims), same
       product scope only.
    2. Each pair's DIFFERENCE is classified (`classify`).
    3. Groups per method by complete linkage; pattern families by the shared
       template either side of the one differing value.
    4. Meaning-only matches from stored embeddings, as proposals."""
    import numpy as np
    from rapidfuzz import fuzz, process
    claims = _live_claims(tenant)
    by_id = {c.id: c for c in claims}
    stats = accuracy(tenant)
    groups: list[dict] = []
    if len(claims) < 2:
        return groups

    def add(kind, method, key, members, values=None, score=None):
        mem = sorted(set(members), key=lambda cid: _rank(by_id[cid]))
        if len(mem) < 2:
            return
        groups.append({
            "kind": kind, "method": method, "key": key,
            "fingerprint": prov.fingerprint(f"{kind}|{method}|{key}"),
            "members": mem, "values": values or {},
            "auto": method_is_auto(stats, method), "score": score})

    texts = [canon(c.claim) for c in claims]
    M = process.cdist(texts, texts, scorer=fuzz.token_sort_ratio,
                      score_cutoff=CANDIDATE_AT, dtype=np.uint8, workers=1)
    edges: dict[str, dict] = {m: {} for m in METHODS}
    values: dict[str, dict] = {m: {} for m in METHODS}
    templates: dict[tuple, dict] = {}
    score = {}
    for i, j in zip(*np.nonzero(M)):
        if i >= j:
            continue
        a, b = claims[i], claims[j]
        if (a.entity_key or "") != (b.entity_key or ""):
            continue
        method, va, vb = classify(a.claim, b.claim)
        if not method:
            continue
        score[(a.id, b.id)] = score[(b.id, a.id)] = float(M[i, j]) / 100
        edges[method].setdefault(a.id, set()).add(b.id)
        edges[method].setdefault(b.id, set()).add(a.id)
        if va or vb:
            values[method].setdefault(a.id, va)
            values[method].setdefault(b.id, vb)
        if method == "value_slot":
            ta = tokens(a.claim)
            p, ea, _eb = _span(ta, tokens(b.claim))
            key = (" ".join(ta[:p]), " ".join(ta[ea:]), a.entity_key or "")
            fam = templates.setdefault(key, {})
            fam[a.id], fam[b.id] = va, vb

    fam_of = {}
    for key, fam in templates.items():
        for c in fam:
            fam_of.setdefault(c, set()).add(key)
    for x in list(edges["similar_wording"]):
        edges["similar_wording"][x] = {y for y in edges["similar_wording"][x]
                                       if not (fam_of.get(x, set()) & fam_of.get(y, set()))}
    edges["similar_wording"] = {x: ys for x, ys in edges["similar_wording"].items() if ys}

    def dist(x, y):
        return 1.0 - score.get((x, y), 0.0)

    def components(adj: dict) -> list[list[str]]:
        seen, out = set(), []
        for start in adj:
            if start in seen:
                continue
            comp, stack = [], [start]
            while stack:
                n = stack.pop()
                if n in seen:
                    continue
                seen.add(n)
                comp.append(n)
                stack.extend(adj.get(n, ()))
            out.append(sorted(comp))
        return out

    in_exact: dict[str, int] = {}
    for method, kind in (("normalised_equal", "variants"), ("number_slot", "inconsistency"),
                         ("negation", "inconsistency"), ("similar_wording", "variants"),
                         ("similar_frame_different_number", "inconsistency")):
        if method == "similar_frame_different_number":
            # A pair already in one exact inconsistency group is not reported
            # again as a looser one.
            for x in list(edges[method]):
                edges[method][x] = {y for y in edges[method][x]
                                    if not (x in in_exact and in_exact.get(y) == in_exact[x])}
            edges[method] = {x: ys for x, ys in edges[method].items() if ys}
        for comp in components(edges[method]):
            clusters = [comp] if method == "normalised_equal" else _complete_link(comp, dist)
            for cl in clusters:
                if method == "number_slot" and len(cl) > 1:
                    gid = len(in_exact) + 1
                    for c in cl:
                        in_exact.setdefault(c, gid)
                add(kind, method, "|".join(sorted(cl)), cl,
                    values={c: values[method].get(c, "") for c in cl},
                    score=min((score.get((x, y), 1.0) for x in cl for y in cl if x < y), default=None))
    # One family per claim: the largest pattern it belongs to wins, so a claim
    # is never reviewed twice ("MetaMask USD" in a 9-member and a 3-member one).
    placed: set[str] = set()
    for (pre, post, ent), fam in sorted(templates.items(), key=lambda kv: -len(kv[1])):
        fam = {c: v for c, v in fam.items() if c not in placed}
        if len(fam) >= FAMILY_MIN and len(set(fam.values())) == len(fam):
            add("family", "value_slot", f"{ent}|{pre} {{X}} {post}", list(fam), values=fam)
            placed |= set(fam)

    if use_embeddings:
        _meaning_groups(tenant, claims, by_id, add)
    return groups


def _meaning_groups(tenant, claims, by_id, add) -> None:
    """Rewordings that share few words, from the stored embeddings — always
    blocked first (numbers, negation, scope), always proposals until measured."""
    from . import embed
    try:
        rows = {r.row_id: r for r in embed.BACKEND.rows(tenant, "claim") if r.vector}
    except Exception:  # noqa: BLE001 — no index means no proposals, never a guess
        return
    live = [c for c in claims if c.id in rows]
    if len(live) < 2:
        return
    pairs = embed._matches([rows[c.id] for c in live], [rows[c.id] for c in live],
                           PROPOSE_AT, same=True)
    sc, adj = {}, {}
    for i, j, s_ in pairs:
        a, b = live[i], live[j]
        if (a.entity_key or "") != (b.entity_key or ""):
            continue
        sa, sb = signature(a.claim), signature(b.claim)
        if sa["numbers"] != sb["numbers"] or sa["negated"] != sb["negated"]:
            continue
        if canon(a.claim) == canon(b.claim):
            continue
        sc[(a.id, b.id)] = sc[(b.id, a.id)] = s_
        adj.setdefault(a.id, set()).add(b.id)
        adj.setdefault(b.id, set()).add(a.id)
    seen = set()
    for start in adj:
        if start in seen:
            continue
        comp, stack = [], [start]
        while stack:
            n = stack.pop()
            if n not in seen:
                seen.add(n)
                comp.append(n)
                stack.extend(adj.get(n, ()))
        for cl in _complete_link(sorted(comp), lambda x, y: 1.0 - sc.get((x, y), 0.0)):
            add("variants", "similar_meaning", "|".join(sorted(cl)), cl,
                score=min((sc.get((x, y), 1.0) for x in cl for y in cl if x < y), default=None))


# --- storing, keeping every decision -------------------------------------

def rebuild(tenant: str, use_embeddings: bool = True) -> dict:
    """Bring stored groups in line with `compute`, keeping every reviewer
    decision: a confirmed or rejected membership stays as decided, and a
    decided group stays as history even if its claims change."""
    want = {g["fingerprint"]: g for g in compute(tenant, use_embeddings)}
    made = dropped = 0
    with db.SessionLocal() as s:
        have = {g.fingerprint: g for g in s.query(db.KbClaimGroup)
                .filter(db.KbClaimGroup.tenant == tenant)}
        for fp, g in want.items():
            row = have.get(fp)
            if row is None:
                row = db.KbClaimGroup(tenant=tenant, fingerprint=fp)
                s.add(row)
                made += 1
            row.kind, row.method, row.auto = g["kind"], g["method"], 1 if g["auto"] else 0
            row.canonical_claim_id = row.canonical_claim_id or g["members"][0]
            row.member_count = len(g["members"])
            row.updated_at = _now()
            s.flush()
            old = {m.claim_id: m for m in s.query(db.KbClaimMember)
                   .filter(db.KbClaimMember.group_id == row.id)}
            for cid in g["members"]:
                m = old.pop(cid, None)
                if m is None:
                    m = db.KbClaimMember(tenant=tenant, group_id=row.id, claim_id=cid,
                                         band="auto" if g["auto"] else "proposed")
                    s.add(m)
                elif m.band in ("auto", "proposed"):
                    m.band = "auto" if g["auto"] else "proposed"
                m.value = (g["values"] or {}).get(cid, "")
                m.score = g.get("score")
            for m in old.values():               # no longer implied
                if m.band in ("auto", "proposed"):
                    s.delete(m)
        for fp, row in have.items():
            if fp not in want and row.status == "open":
                s.query(db.KbClaimMember).filter(db.KbClaimMember.group_id == row.id).delete()
                s.delete(row)
                dropped += 1
        s.commit()
    try:
        from . import stages
        kinds: dict = {}
        for g in want.values():
            kinds[g["kind"]] = kinds.get(g["kind"], 0) + 1
        stages.record(tenant, "group",
                      n_in=len({c for g in want.values() for c in g["members"]}),
                      n_out=len(want), details={"by_kind": kinds, "new": made,
                                                "gone": dropped})
    except Exception:  # noqa: BLE001 — accounting never breaks the work
        pass
    return {"groups": len(want), "new": made, "dropped": dropped}


# --- what the reviewer sees ----------------------------------------------

_KIND_ORDER = {"inconsistency": 0, "variants": 1, "family": 2}


def listing(tenant: str, status: str = "open", kind: str = "") -> list[dict]:
    """Groups for review: inconsistencies first, legal pages first, widest reach
    first. Each member carries its wording, value and every page."""
    with db.SessionLocal() as s:
        q = s.query(db.KbClaimGroup).filter(db.tenant_filter(db.KbClaimGroup, tenant))
        if status != "all":
            q = q.filter(db.KbClaimGroup.status == status)
        if kind:
            q = q.filter(db.KbClaimGroup.kind == kind)
        groups = q.all()
        ids = [g.id for g in groups]
        mems = (s.query(db.KbClaimMember).filter(db.KbClaimMember.group_id.in_(ids or [""])).all())
        cids = {m.claim_id for m in mems}
        claims = {c.id: c for c in s.query(db.KbClaim).filter(db.KbClaim.id.in_(cids or [""]))}
        s.expunge_all()
    by_group: dict[str, list] = {}
    for m in mems:
        c = claims.get(m.claim_id)
        if c is None:
            continue
        pages = pages_of(c)
        by_group.setdefault(m.group_id, []).append({
            "member_id": m.id, "claim_id": c.id, "wording": c.claim, "value": m.value or "",
            "band": m.band, "score": m.score, "pages": pages, "page_count": len(pages),
            "authority": min((authority(u) for u in pages), default=9),
            "legal": any(authority(u) == 0 for u in pages), "review": c.review})
    out = []
    for g in groups:
        ms = sorted(by_group.get(g.id, []), key=lambda m: (m["authority"], -m["page_count"]))
        if len(ms) < 2 and g.status == "open":
            continue
        reach = sum(m["page_count"] for m in ms)
        legal = any(m["legal"] for m in ms)
        out.append({"id": g.id, "kind": g.kind, "method": g.method,
                    "why": METHODS.get(g.method, {}).get("why", ""), "auto": bool(g.auto),
                    "status": g.status, "decision": g.decision or "", "reason": g.reason or "",
                    "decided_by": g.decided_by or "", "canonical_claim_id": g.canonical_claim_id,
                    "members": ms, "reach": reach, "legal": legal,
                    "severity": ("P1" if g.kind == "inconsistency" and legal
                                 else "P2" if g.kind == "inconsistency" else "P3")})
    return sorted(out, key=lambda g: (_KIND_ORDER.get(g["kind"], 9), not g["legal"], -g["reach"]))


# --- decisions -----------------------------------------------------------

DECISIONS = ("confirm", "use_wording", "remove_everywhere", "not_a_problem", "split_member")


def decide(tenant: str, group_id: str, decision: str, reason: str, by: str = "",
           member_id: str = "", replacement: str = "") -> dict:
    """A reviewer acts on a group. Reason and reviewer are required; every
    membership the decision touches is a LABEL for `accuracy`.

    confirm            the grouping is right (every member's band -> confirmed)
    split_member       this member does not belong (-> rejected, a label against
                       the method)
    use_wording        this member's wording (or `replacement`) is right: a change
                       with a task to replace every OTHER wording on every page
    remove_everywhere  the claim should not be stated: a task to remove every
                       wording on every page
    not_a_problem      an inconsistency that is correct (different products,
                       dates): closed, members confirmed as grouped correctly
    """
    if decision not in DECISIONS:
        return {"error": f"decision must be one of {', '.join(DECISIONS)}"}
    if not (reason or "").strip():
        return {"error": "a one-line reason is required — it is the audit trail"}
    by = by or "owner"
    groups = {g["id"]: g for g in listing(tenant, "all")}
    g = groups.get(group_id)
    if g is None:
        return {"error": "no such group for this account"}
    with db.SessionLocal() as s:
        row = s.get(db.KbClaimGroup, group_id)
        mems = {m.id: m for m in s.query(db.KbClaimMember)
                .filter(db.KbClaimMember.group_id == group_id)}
        if decision == "split_member":
            m = mems.get(member_id)
            if m is None:
                return {"error": "name the member that does not belong"}
            m.band, m.decided_by, m.reason = "rejected", by, reason
            s.commit()
            return {"ok": True, "decision": decision}
        for m in mems.values():
            if m.band in ("auto", "proposed"):
                m.band, m.decided_by = "confirmed", by
        row.status, row.decision, row.reason, row.decided_by, row.decided_at = (
            "decided" if decision != "confirm" else "open", decision, reason, by, _now())
        if decision == "use_wording" and member_id in mems:
            row.canonical_claim_id = mems[member_id].claim_id
        s.commit()
    if decision in ("use_wording", "remove_everywhere"):
        keep = None
        if decision == "use_wording":
            keep = next((m for m in g["members"] if m["member_id"] == member_id), None)
            if keep is None and not replacement.strip():
                return {"error": "choose the member whose wording is right, or give the wording"}
        new_text = (replacement.strip() or (keep["wording"] if keep else "")) if decision == "use_wording" else ""
        return {"ok": True, "decision": decision,
                **_fix(tenant, g, keep["claim_id"] if keep else None, new_text, reason, by)}
    return {"ok": True, "decision": decision}


def _fix(tenant: str, g: dict, keep_claim: str | None, new_text: str, reason: str, by: str) -> dict:
    """One change; one task per wording per page — the exact wording found
    and what replaces it ('' = remove)."""
    from . import change
    locs = []
    for m in g["members"]:
        if m["claim_id"] == keep_claim and not (new_text and new_text != m["wording"]):
            continue
        for u in m["pages"]:
            kind = ("auto_edit" if (change._editable(u) and change._store_profile(tenant, u))
                    else "manual")
            locs.append({"kind": kind, "location": u, "find": m["wording"],
                         "replace": new_text, "sentence": m["wording"]})
    old = " | ".join(sorted({m["wording"][:80] for m in g["members"] if m["claim_id"] != keep_claim}))
    return change.create_wording(tenant, g["id"], old, new_text, reason, by, locs)


# --- accuracy ------------------------------------------------------------

def wilson_lower(k: int, n: int) -> float | None:
    """95% Wilson lower bound on a proportion (scipy) — what "at least 99%"
    is judged on."""
    if n == 0:
        return None
    from scipy.stats import binomtest
    return float(binomtest(k, n).proportion_ci(confidence_level=0.95, method="wilson").low)


def accuracy(tenant: str) -> dict:
    """Per method: reviewer labels (confirmed = right, rejected = wrong),
    precision and its 95% lower bound, and whether it may group automatically."""
    with db.SessionLocal() as s:
        rows = (s.query(db.KbClaimGroup.method, db.KbClaimMember.band)
                .join(db.KbClaimMember, db.KbClaimMember.group_id == db.KbClaimGroup.id)
                .filter(db.KbClaimGroup.tenant == tenant,
                        db.KbClaimMember.band.in_(("confirmed", "rejected"))).all())
    out: dict = {}
    for method in METHODS:
        k = sum(1 for m, b in rows if m == method and b == "confirmed")
        n = sum(1 for m, b in rows if m == method)
        out[method] = {"labels": n, "correct": k,
                       "precision": round(k / n, 4) if n else None,
                       "lower_bound": round(wilson_lower(k, n), 4) if n else None,
                       "needed_for_99": labels_needed()}
    for method in METHODS:
        out[method]["auto"] = method_is_auto(out, method)
    return out


def labels_needed(target: float = TARGET) -> int:
    """Error-free labels needed for a 95% lower bound of `target` (~380 for 99%)."""
    n = 1
    while (wilson_lower(n, n) or 0) < target:
        n += 1
    return n


def job(tenant: str, progress=None) -> dict:
    return rebuild(tenant)
