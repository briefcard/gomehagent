"""FETCH — a page's bytes, fetched once per change and stored for every reader.

BUILD-MAP §4 FETCH. `get` is the one way a reader obtains a page: it serves
the stored copy when it is fresh enough, otherwise fetches, and stores what
it fetched when `store` is set. A rehearsal passes `store=False` and writes
nothing (§1.6).
"""
from __future__ import annotations

import datetime as dt
import zlib

from .. import db
from .. import provenance as prov

#: The largest page kept. Bigger pages are still READ; only the stored copy is
#: capped, and the cap is reported on the row (`bytes` > len of stored html).
MAX_STORED = 3_000_000


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def text_hash(text: str) -> str:
    """How a page's CONTENT is hashed — the same rule the harvest has always
    used (text, not markup), so a changed analytics tag is not a change."""
    return prov.fingerprint((text or "")[:20000])


def download(url: str) -> tuple[int, str, str]:
    """(status, html, error). Network only; no storage."""
    import httpx
    from .. import compliance
    try:
        r = httpx.get(url, timeout=25, follow_redirects=True,
                      headers=compliance.HEADERS)
        return r.status_code, (r.text if r.status_code == 200 else ""), ""
    except Exception as exc:  # noqa: BLE001
        return 0, "", exc.__class__.__name__


def download_bytes(url: str, max_bytes: int = 15_000_000) -> tuple[int, bytes, str, str]:
    """(status, bytes, content-type, error) — for documents (PDFs)."""
    import httpx
    from .. import compliance
    try:
        r = httpx.get(url, timeout=40, follow_redirects=True, headers=compliance.HEADERS)
        body = getattr(r, "content", None)
        if body is None:
            body = (getattr(r, "text", "") or "").encode("latin-1", "replace")
        ctype = (getattr(r, "headers", {}) or {}).get("content-type", "")
        return r.status_code, body[:max_bytes], ctype, ""
    except Exception as exc:  # noqa: BLE001
        return 0, b"", "", exc.__class__.__name__


def store(tenant: str, url: str, html: str, content_hash: str,
          source_label: str = "", http_status: int = 200,
          rendered: int = 0, document: dict | None = None,
          risk_tier: str = "") -> bool:
    """Keep this page as fetched. Returns True when its content changed."""
    raw = (html or "").encode("utf-8", "replace")
    with db.SessionLocal() as s:
        row = (s.query(db.PageSnapshot)
               .filter(db.PageSnapshot.tenant == tenant,
                       db.PageSnapshot.url == url).one_or_none())
        changed = row is None or row.content_hash != content_hash
        if row is None:
            row = db.PageSnapshot(tenant=tenant, url=url)
            s.add(row)
        elif changed:
            row.prev_hash = row.content_hash
            # KEEP THE OLD COPY (owner, 2026-11-04: the crawl is a source in
            # its own right — SEO/AEO, snapshots over time). Appended only, with
            # no comparison here: the crawl stays cheap, and duplicates and
            # copies past the last five are cleaned passively, nightly
            # (`pipeline.retention.clean`).
            if row.html_z and row.content_hash:
                s.add(db.PageVersion(tenant=tenant, url=url, content_hash=row.content_hash,
                                     html_z=row.html_z, bytes_=row.bytes_,
                                     risk_tier=row.risk_tier or "",
                                     first_seen=row.changed_at or row.fetched_at,
                                     last_seen=_now()))
        if changed:
            row.changed_at = _now()
            row.parser_version = 0          # the document is stale
            row.document = {}
        row.html_z = zlib.compress(raw[:MAX_STORED])
        row.bytes_ = len(raw)
        row.content_hash = content_hash
        row.http_status = http_status
        # 0 = not needed, 1 = drawn in a browser, 2 = needed one, did not get it
        row.rendered = int(rendered or 0)
        row.source_label = source_label or row.source_label or ""
        row.fetched_at = _now()
        if risk_tier:
            row.risk_tier = risk_tier
        if document is not None:
            row.document = document
            row.parser_version = document.get("version", 0)
            row.summary = summarise(document)
        s.commit()
    return changed


def html_of(row) -> str:
    """The page's stored HTML. A light row (from `snapshots`) carries no bytes:
    they are read here, for that one page only."""
    z = getattr(row, "html_z", None)
    if z is None and getattr(row, "id", None) and not isinstance(row, (db.PageSnapshot, db.PageVersion)):
        with db.SessionLocal() as s:
            z = s.query(db.PageSnapshot.html_z).filter(db.PageSnapshot.id == row.id).scalar()
    if not z:
        return ""
    return zlib.decompress(z).decode("utf-8", "replace")


def latest(tenant: str, url: str):
    with db.SessionLocal() as s:
        row = (s.query(db.PageSnapshot)
               .filter(db.PageSnapshot.tenant == tenant,
                       db.PageSnapshot.url == url).one_or_none())
        if row is not None:
            s.expunge(row)
        return row


#: The columns a LISTING needs. Never the stored HTML or the parsed Document:
#: Transak's 879 pages loaded whole are hundreds of MB, and the web service
#: has 512 MB — loading them to list or count pages took production down
#: (2026-11-06). A full page is read one at a time (`latest`, `html_of`).
_LIGHT = ("id", "tenant", "url", "source_label", "http_status", "content_hash",
          "prev_hash", "bytes_", "rendered", "risk_tier", "parser_version",
          "fetched_at", "changed_at", "summary")


def snapshots(tenant: str) -> list:
    """Every stored page of one account, WITHOUT its bytes or Document."""
    from types import SimpleNamespace
    cols = [getattr(db.PageSnapshot, c) for c in _LIGHT]
    with db.SessionLocal() as s:
        rows = (s.query(*cols)
                .filter(db.tenant_filter(db.PageSnapshot, tenant))
                .order_by(db.PageSnapshot.url).all())
    return [SimpleNamespace(**dict(zip(_LIGHT, r))) for r in rows]


def summarise(doc: dict) -> dict:
    """The listing's view of one page: small, and enough to search by title."""
    heads = [h.get("text", "") for h in (doc or {}).get("headings", [])]
    return {"title": heads[0] if heads else "", "headings": heads[:6],
            "words": len(" ".join((doc or {}).get("blocks", [])).split()),
            "links": len((doc or {}).get("links", [])), "tables": len((doc or {}).get("tables", [])),
            "lists": len((doc or {}).get("lists", [])), "has_jsonld": bool((doc or {}).get("jsonld")),
            "version": (doc or {}).get("version", 0)}


def set_summary(row_id: str, summary: dict) -> None:
    with db.SessionLocal() as s:
        r = s.get(db.PageSnapshot, row_id)
        if r is not None:
            r.summary = summary
            s.commit()


def document_of(row_id: str):
    """One stored page's (Document, parser_version) — read alone."""
    with db.SessionLocal() as s:
        got = (s.query(db.PageSnapshot.document, db.PageSnapshot.parser_version)
               .filter(db.PageSnapshot.id == row_id).one_or_none())
    return (got[0] or {}, got[1] or 0) if got else ({}, 0)


def get(tenant: str, url: str, max_age_hours: float = 0, store_it: bool = False,
        source_label: str = "") -> dict:
    """The page, from the store when fresh, otherwise from the network.

    Returns {status, html, error, from_store}. `max_age_hours=0` always
    fetches (the harvest's default: it exists to see the live site)."""
    if max_age_hours > 0:
        row = latest(tenant, url)
        if row is not None and row.fetched_at is not None:
            at = row.fetched_at if row.fetched_at.tzinfo else \
                row.fetched_at.replace(tzinfo=dt.timezone.utc)
            if _now() - at <= dt.timedelta(hours=max_age_hours):
                return {"status": row.http_status, "html": html_of(row),
                        "error": "", "from_store": True}
    status, html, err = download(url)
    if store_it and status == 200 and html:
        from .parse import parse
        doc = parse(html)
        store(tenant, url, html, doc["text_hash"], source_label, status,
              document=doc)
    return {"status": status, "html": html, "error": err, "from_store": False}


def set_tier(tenant: str, url: str, tier: str) -> None:
    with db.SessionLocal() as s:
        row = (s.query(db.PageSnapshot)
               .filter(db.PageSnapshot.tenant == tenant,
                       db.PageSnapshot.url == url).one_or_none())
        if row is not None:
            row.risk_tier = tier
            s.commit()


def versions(tenant: str, url: str) -> list:
    """Earlier copies of one page, newest first (the current copy is `latest`)."""
    with db.SessionLocal() as s:
        rows = (s.query(db.PageVersion)
                .filter(db.tenant_filter(db.PageVersion, tenant), db.PageVersion.url == url)
                .order_by(db.PageVersion.last_seen.desc()).all())
        s.expunge_all()
        return rows
