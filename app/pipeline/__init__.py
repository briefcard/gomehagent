"""The truth pipeline, as stages (BUILD-MAP-truth-pipeline.md §3).

    DISCOVER → FETCH → PARSE → EXTRACT → ACCOUNT → COMPARE → CHECKS → CHANGE

Each stage is a module with one job, a stored output and a version. The
harvest is the coordinator; a stage never reaches into another's internals —
it reads the stored output (a snapshot, a document, statements) instead.

`STAGES` is the registry the build map's §3.1 names: what each stage reads,
what it writes, and the version that keys its idempotency. A stage whose
version is bumped re-runs over what is already stored; nothing is refetched.
"""
from __future__ import annotations

STAGES: dict[str, dict] = {
    "fetch":   {"module": "app.pipeline.fetch",   "reads": "url",
                "writes": "page_snapshots", "version": 1},
    "parse":   {"module": "app.pipeline.parse",   "reads": "page_snapshots",
                "writes": "page_snapshots.document", "version": 1},
}
