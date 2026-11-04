"""Re-read every STORED page with the current readers — zero fetches.

BUILD-MAP M3 acceptance: "bump a version → re-run on stored docs with zero
fetches". Used when an extractor improves, a reviewer teaches the account a
term, or the parser changes. It reads `page_snapshots` only; a page never
stored is not reached (the report says how many pages it read, so "the site"
and "what we have stored of it" are never confused).
"""
from __future__ import annotations

from .. import compliance, statements
from . import account, extractors, fetch, parse


def reprocess(tenant: str, apply: bool = False) -> dict:
    terms = statements.terms(tenant)
    pages = statements_n = unacc = 0
    by_extractor: dict[str, int] = {}
    for row in fetch.snapshots(tenant):
        doc = parse.document(tenant, row.url) if apply else parse.parse(fetch.html_of(row))
        if not doc:
            continue
        stmts, counts = extractors.run_all(doc, terms)
        figs, _c = account.unaccounted(doc, stmts)
        pages += 1
        statements_n += len(stmts)
        unacc += len(figs)
        for k, v in counts.items():
            by_extractor[k] = by_extractor.get(k, 0) + max(v, 0)
        if apply:
            entity = ""
            prev = statements.rows_for_url(tenant, row.url)
            if prev:
                entity = prev[0].entity_key or ""
            statements.record(tenant, row.url, stmts,
                              authority=("binding" if compliance.is_legal_url(row.url)
                                         else "derived"), entity_key=entity)
            account.record(tenant, row.url, figs)
    return {"tenant": tenant, "applied": apply, "pages_read_from_store": pages,
            "pages_fetched": 0, "statements": statements_n,
            "statements_by_extractor": by_extractor, "unaccounted_figures": unacc,
            "extractors": extractors.registry(), "parser_version": parse.VERSION}
