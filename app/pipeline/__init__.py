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
                "writes": "page_snapshots.document", "version": 2},
    "extract": {"module": "app.pipeline.extractors", "reads": "document",
                "writes": "kb_statements", "version": 1},
    "account": {"module": "app.pipeline.account", "reads": "document + statements",
                "writes": "unaccounted_numbers", "version": 1},
    "reprocess": {"module": "app.pipeline.reprocess", "reads": "page_snapshots",
                  "writes": "kb_statements + unaccounted_numbers", "version": 1},
}
