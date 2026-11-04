"""RETENTION — the crawl's history, kept useful and bounded, off the crawl path.

Owner, 2026-11-04: *"Lets keep the last 5 but only save files that have any
difference from a previous version that is already crawled. That can be
checked and cleaned passively not at the moment of crawl."*

The crawl appends an earlier copy whenever a page's content changes
(`fetch.store`) and compares nothing. This runs nightly, per page:

1. a copy whose content is IDENTICAL to a newer copy, or to the page as it
   is now, is dropped — a page that flipped back to an older text keeps that
   text once, at its newest date;
2. of what remains, the newest `KEEP_VERSIONS` are kept and older ones go.

"Identical" is the page's text hash (`fetch.text_hash`) — the same rule that
decides whether a page changed at all, so a new analytics tag or cache-buster
is not a version. The current copy (`page_snapshots`) is never touched.
"""
from __future__ import annotations

from .. import db

#: Earlier copies kept per page, besides the current one.
KEEP_VERSIONS = 5


def clean(tenant: str = "", apply: bool = True) -> dict:
    """Drop duplicate and surplus earlier copies. Every account when `tenant`
    is empty. Returns what it found and (on apply) removed."""
    dup = surplus = kept = pages = 0
    with db.SessionLocal() as s:
        q = s.query(db.PageVersion)
        if tenant:
            q = q.filter(db.tenant_filter(db.PageVersion, tenant))
        by_page: dict[tuple, list] = {}
        for v in q.all():
            by_page.setdefault((v.tenant, v.url), []).append(v)
        current = {(r.tenant, r.url): r.content_hash
                   for r in s.query(db.PageSnapshot.tenant, db.PageSnapshot.url,
                                    db.PageSnapshot.content_hash)}
        for key, vers in by_page.items():
            pages += 1
            vers.sort(key=lambda v: (v.last_seen or v.first_seen), reverse=True)
            seen = {current.get(key)} - {None}
            keep = []
            for v in vers:
                if v.content_hash in seen:
                    dup += 1
                    if apply:
                        s.delete(v)
                    continue
                seen.add(v.content_hash)
                keep.append(v)
            for v in keep[KEEP_VERSIONS:]:
                surplus += 1
                if apply:
                    s.delete(v)
            kept += min(len(keep), KEEP_VERSIONS)
        if apply:
            s.commit()
    return {"pages": pages, "kept": kept, "dropped_duplicates": dup,
            "dropped_beyond_last": surplus, "keep_versions": KEEP_VERSIONS,
            "applied": apply}


def job(tenant: str, progress=None) -> dict:
    return clean(tenant, apply=True)
