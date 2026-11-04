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


def store(tenant: str, url: str, html: str, content_hash: str,
          source_label: str = "", http_status: int = 200,
          rendered: bool = False, document: dict | None = None) -> bool:
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
        if changed:
            row.changed_at = _now()
            row.parser_version = 0          # the document is stale
            row.document = {}
        row.html_z = zlib.compress(raw[:MAX_STORED])
        row.bytes_ = len(raw)
        row.content_hash = content_hash
        row.http_status = http_status
        row.rendered = 1 if rendered else 0
        row.source_label = source_label or row.source_label or ""
        row.fetched_at = _now()
        if document is not None:
            row.document = document
            row.parser_version = document.get("version", 0)
        s.commit()
    return changed


def html_of(row) -> str:
    if row is None or not row.html_z:
        return ""
    return zlib.decompress(row.html_z).decode("utf-8", "replace")


def latest(tenant: str, url: str):
    with db.SessionLocal() as s:
        row = (s.query(db.PageSnapshot)
               .filter(db.PageSnapshot.tenant == tenant,
                       db.PageSnapshot.url == url).one_or_none())
        if row is not None:
            s.expunge(row)
        return row


def snapshots(tenant: str) -> list:
    with db.SessionLocal() as s:
        rows = (s.query(db.PageSnapshot)
                .filter(db.tenant_filter(db.PageSnapshot, tenant))
                .order_by(db.PageSnapshot.url).all())
        s.expunge_all()
        return rows


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
