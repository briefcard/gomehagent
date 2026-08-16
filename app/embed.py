"""Semantic recall, behind the contract the classifier already publishes.

`kb.suggest_tags` returns `confident` / `score` / `basis`, and everything
downstream — `resolve()`, the coverage receipt, the refusal — reads those and
nothing else. This module changes what computes them. Nothing above it moves,
which is the whole reason a swap like this is safe now and would not have been
safe as a starting point.

**Storage is a seam, not a decision.** `Backend` is the interface; `JsonRows`
is the implementation that ships. Brute-force cosine over a few thousand
vectors is single-digit milliseconds, needs no extension, no cluster and no
second copy of the truth — and at this corpus size it beats a network round
trip to anything. pgvector or a search cluster becomes another `Backend` when a
measured number says so. That is the sixth locked decision applied one layer
down: the vendor sits behind our interface.

**Two sources of truth is the thing being avoided.** Approval state,
`may_write` precedence and conflicts live in Postgres and always will. An
external index would be an index *over* that, and every approval, retirement
and purge would have to propagate — with a window in which a generator can
still retrieve a claim that was retired. That failure is already the most
common shape in this project's defect log; it does not need a network hop
added to it.

**Degrading is allowed. Degrading silently is not.** No key, no network, no
rows — the caller is told which path ran and why, because a fallback that
looks like a working path is exactly how the extractor ran at 0% recall for
weeks with nothing but the `extractor` field to give it away.
"""
from __future__ import annotations

import hashlib
import logging
import math

from . import config, db

log = logging.getLogger("embed")

KINDS = ("claim", "objection", "situation", "entity", "media")

#: Cosine floor for a semantic match to count. text-embedding-3 puts unrelated
#: English in the 0.0–0.25 band and genuine paraphrase well above 0.45, so this
#: sits in the gap rather than on either side of it. Like the word-overlap
#: floors it is reasoned, not tuned — `kb.calibration()` is what will move it,
#: and it reports the semantic path separately so the two can be compared on
#: the same claims.
MIN_SEMANTIC_SCORE = 0.45

# numpy turns a few thousand dot products from seconds into milliseconds, but
# it must not be a hard requirement: every suite in this project runs offline
# and several environments here have no numpy. Present, it is used; absent, the
# pure-Python path is correct and merely slower.
try:  # pragma: no cover - environment dependent
    import numpy as _np
except Exception:  # noqa: BLE001
    _np = None


def text_hash(text: str) -> str:
    return hashlib.sha256((text or "").strip().lower().encode()).hexdigest()[:32]


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------

def _openai_embed(texts: list[str]) -> tuple[list[list[float]] | None, str]:
    """Call OpenAI. Returns (vectors, note); never raises.

    httpx rather than the SDK, matching `whatsapp.transcribe` — one fewer
    dependency, and the call is four lines.
    """
    if not config.OPENAI_API_KEY:
        return None, "OPENAI_API_KEY is not set"
    import httpx
    try:
        r = httpx.post(
            "https://api.openai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}"},
            json={"model": config.EMBED_MODEL, "input": texts,
                  "dimensions": config.EMBED_DIMS},
            timeout=30)
        if r.status_code != 200:
            return None, f"provider returned {r.status_code}: {r.text[:120]}"
        data = sorted(r.json()["data"], key=lambda d: d["index"])
        return [d["embedding"] for d in data], ""
    except Exception as exc:  # noqa: BLE001
        return None, f"{exc.__class__.__name__}: {str(exc)[:120]}"


#: Swappable so the suites can run offline with a known geometry. Tests set a
#: deterministic stub; nothing in production replaces it.
_PROVIDER = _openai_embed


def set_provider(fn) -> None:
    """Replace the embedding provider. For tests and for a future vendor."""
    global _PROVIDER
    _PROVIDER = fn


def embed_texts(texts: list[str]) -> tuple[list[list[float]] | None, str]:
    if not texts:
        return [], ""
    return _PROVIDER(texts)


def available() -> tuple[bool, str]:
    """Whether the semantic path can run at all, and why not when it cannot."""
    vecs, note = embed_texts(["probe"])
    if vecs:
        return True, ""
    return False, note or "embedding provider unavailable"


# ---------------------------------------------------------------------------
# Similarity
# ---------------------------------------------------------------------------

def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    if _np is not None:
        va, vb = _np.asarray(a, dtype=float), _np.asarray(b, dtype=float)
        na, nb = float(_np.linalg.norm(va)), float(_np.linalg.norm(vb))
        return float(va.dot(vb) / (na * nb)) if na and nb else 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


# ---------------------------------------------------------------------------
# Storage backends
# ---------------------------------------------------------------------------

class Backend:
    """Where vectors live. Implement three methods to add pgvector or a cluster."""

    def upsert(self, tenant, kind, row_id, vector, model, dims, th): ...
    def rows(self, tenant: str, kind: str) -> list: ...
    def hash_for(self, tenant: str, kind: str, row_id: str) -> str: ...


class JsonRows(Backend):
    """Vectors as JSON in Postgres, scored in process.

    Correct at this scale and beyond it: 5,000 vectors at 512 dimensions is a
    couple of million multiply-adds, which is milliseconds with numpy and still
    well under a second without. The cost of being wrong here is a backend
    swap, not a migration of the truth.
    """

    def upsert(self, tenant, kind, row_id, vector, model, dims, th):
        with db.SessionLocal() as s:
            row = (s.query(db.KbEmbedding)
                   .filter(db.KbEmbedding.tenant == tenant,
                           db.KbEmbedding.kind == kind,
                           db.KbEmbedding.row_id == row_id).first())
            if not row:
                row = db.KbEmbedding(tenant=tenant, kind=kind, row_id=row_id)
                s.add(row)
            row.vector, row.model, row.dims, row.text_hash = vector, model, dims, th
            row.updated_at = db.utcnow()
            s.commit()

    def rows(self, tenant, kind):
        with db.SessionLocal() as s:
            out = (s.query(db.KbEmbedding)
                   .filter(db.tenant_filter(db.KbEmbedding, tenant),
                           db.KbEmbedding.kind == kind).all())
            s.expunge_all()
            return out

    def hash_for(self, tenant, kind, row_id):
        with db.SessionLocal() as s:
            row = (s.query(db.KbEmbedding)
                   .filter(db.KbEmbedding.tenant == tenant,
                           db.KbEmbedding.kind == kind,
                           db.KbEmbedding.row_id == row_id).first())
            return (row.text_hash or "") if row else ""


BACKEND: Backend = JsonRows()


# ---------------------------------------------------------------------------
# The public two calls
# ---------------------------------------------------------------------------

def ensure(tenant: str, kind: str, row_id: str, text: str) -> tuple[bool, str]:
    """Embed one row if its text has changed. Returns (wrote, note).

    Gated on `text_hash`, which is the difference between embedding a corpus
    once and embedding it on every harvest for ever.
    """
    if kind not in KINDS:
        return False, f"unknown kind {kind!r}"
    text = (text or "").strip()
    if not text:
        return False, "nothing to embed"
    th = text_hash(text)
    if BACKEND.hash_for(tenant, kind, row_id) == th:
        return False, "unchanged"
    vecs, note = embed_texts([text])
    if not vecs:
        return False, note
    BACKEND.upsert(tenant, kind, row_id, vecs[0], config.EMBED_MODEL,
                   len(vecs[0]), th)
    return True, ""


def forget(tenant: str, kind: str, row_id: str) -> bool:
    """Drop a row's vector when the row stops being usable.

    Retrieval already refuses to act on a stale hit — `suggest_tags` looks each
    one up in `claim_inventory["selectable"]` and drops what is no longer
    there — so this cannot change an answer. It is here because an index that
    accumulates rows its source has retired is the drift that argued against
    keeping retrieval in a separate datastore, and it would be no more
    acceptable for having been built in-house.
    """
    with db.SessionLocal() as s:
        row = (s.query(db.KbEmbedding)
               .filter(db.KbEmbedding.tenant == tenant,
                       db.KbEmbedding.kind == kind,
                       db.KbEmbedding.row_id == row_id).first())
        if not row:
            return False
        s.delete(row)
        s.commit()
        return True


def backfill(tenant: str, kind: str, items: list[tuple[str, str]]) -> dict:
    """Embed many rows. `items` is [(row_id, text)]. Reports, never raises.

    **"Unchanged" and "empty" are counted apart**, and the first version of
    this collapsed them into one `skipped`. That made a run reporting
    `wrote: 0, skipped: 8` unreadable: already-indexed and had-no-text-to-index
    are opposite situations with opposite fixes, and the number could not tell
    them apart. Same shape as every other entry in DEFECTS §1 — a status
    nobody can act on. `examples` carries the first few row ids per reason so
    the answer is a row you can go and look at, not an inference.
    """
    wrote = unchanged = empty = failed = 0
    reason = ""
    examples: dict[str, list] = {"unchanged": [], "empty": [], "failed": []}
    for row_id, text in items:
        ok, note = ensure(tenant, kind, row_id, text)
        if ok:
            wrote += 1
        elif note == "unchanged":
            unchanged += 1
            if len(examples["unchanged"]) < 3:
                examples["unchanged"].append(row_id)
        elif note == "nothing to embed":
            empty += 1
            if len(examples["empty"]) < 3:
                examples["empty"].append(row_id)
        else:
            failed += 1
            reason = reason or note
            if len(examples["failed"]) < 3:
                examples["failed"].append({"row_id": row_id, "why": note})
    return {"tenant": tenant, "kind": kind,
            "considered": len(items), "wrote": wrote,
            "unchanged": unchanged, "empty": empty, "failed": failed,
            "skipped": unchanged + empty,   # kept: the old field, now derived
            "why": reason, "examples": examples}


#: The row count above which brute force stops being obviously right. Below it,
#: scanning every vector beats a network round trip to any index; above it, a
#: `Backend` swap to pgvector or a cluster is worth measuring. Deliberately a
#: number rather than a feeling — "swap when it gets big" is how a decision
#: gets deferred for ever.
BRUTE_FORCE_CEILING = 20000


def stats(tenant: str = "") -> dict:
    """How much is indexed, how long a scan takes, and whether that is still fine.

    The argument for keeping vectors in Postgres and scanning them in process
    is a claim about size, and a claim about size needs a measurement or it is
    just a preference. This is the measurement.
    """
    import time
    with db.SessionLocal() as s:
        q = s.query(db.KbEmbedding)
        if tenant:
            q = q.filter(db.tenant_filter(db.KbEmbedding, tenant))
        rows = q.all()
        s.expunge_all()

    by = {}
    for r in rows:
        d = by.setdefault(r.tenant, {})
        d[r.kind] = d.get(r.kind, 0) + 1

    # Time the part that would actually get slower: the scan, not the provider.
    probe_ms, widest = None, max((len(rs) for rs in
                                  ([r for r in rows if r.tenant == t]
                                   for t in by)), default=0)
    if rows:
        vec = list(rows[0].vector or [])
        t0 = time.perf_counter()
        for r in rows:
            cosine(vec, list(r.vector or []))
        probe_ms = round((time.perf_counter() - t0) * 1000, 2)

    return {
        "backend": BACKEND.__class__.__name__,
        "numpy": _np is not None,
        "total_vectors": len(rows),
        "largest_account": widest,
        "by_account": by,
        "scan_ms_for_total": probe_ms,
        "brute_force_ceiling": BRUTE_FORCE_CEILING,
        "headroom": BRUTE_FORCE_CEILING - widest,
        "swap_backend_yet": widest >= BRUTE_FORCE_CEILING,
        "note": ("still well inside brute force — a network hop to an index "
                 "would cost more than this scan"
                 if widest < BRUTE_FORCE_CEILING else
                 "past the ceiling: measure a pgvector Backend against this"),
    }


def search(tenant: str, kind: str, query: str, limit: int = 5,
           min_score: float = MIN_SEMANTIC_SCORE
           ) -> tuple[list[dict], str, dict]:
    """Nearest rows of one kind. Returns (hits, degraded_reason, stats).

    A non-empty second value means the semantic path did NOT run — no key, no
    network, nothing indexed. Callers must report it rather than presenting
    a fallback as though it were this.

    The third carries what was scanned and how long it took, so the decision to
    keep scanning in process stays evidence-based rather than assumed.
    """
    import time
    _t0 = time.perf_counter()

    def _stat(n: int) -> dict:
        return {"scanned": n,
                "ms": round((time.perf_counter() - _t0) * 1000, 2),
                "backend": BACKEND.__class__.__name__}
    # Order matters here, and it cost a test to find out. Checking rows first
    # and returning "nothing embedded" is the PROXIMATE reason and it
    # misdirects the fix: when the index is empty *because* there is no key,
    # that message sends someone to run a backfill which cannot succeed. Ask
    # the provider first, so an unavailable one is reported as the root cause
    # and an empty index is only reported when filling it would actually work.
    # Keeping the question with the provider also keeps this backend-agnostic.
    vecs, note = embed_texts([query])
    if not vecs:
        return [], note, _stat(0)
    rows = BACKEND.rows(tenant, kind)
    if not rows:
        return [], "nothing embedded for this account yet", _stat(0)
    q = vecs[0]
    model = config.EMBED_MODEL
    hits = []
    for r in rows:
        # Cosine between two models is a number with no meaning. Skip rather
        # than compare, and say so if it empties the result.
        if r.model and r.model != model:
            continue
        score = cosine(q, list(r.vector or []))
        if score >= min_score:
            hits.append({"row_id": r.row_id, "score": round(score, 4),
                         "kind": kind})
    if not hits and all(r.model and r.model != model for r in rows):
        return ([], f"every indexed row is from another model ({rows[0].model})",
                _stat(len(rows)))
    hits.sort(key=lambda h: -h["score"])
    return hits[:limit], "", _stat(len(rows))
