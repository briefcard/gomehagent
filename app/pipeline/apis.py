"""DATA FEEDS — a public API as a source of figures (BUILD-MAP M9).

Transak publishes its supported cryptocurrencies, fiat currencies and
countries through public API endpoints; the website's "160+ countries" is a
rounding of a list the API returns in full. A feed registered here is read
on every harvest: the list at `list_path` is counted and recorded as a
statement of `subject` (field `api`), under the feed's URL — so QA can make
the feed the source of truth and the answer follows the live list.
"""
from __future__ import annotations

import json
import re

from .. import db, statements


def feeds(tenant: str) -> list:
    with db.SessionLocal() as s:
        rows = (s.query(db.KbApiSource).filter(db.tenant_filter(db.KbApiSource, tenant))
                .order_by(db.KbApiSource.subject).all())
        s.expunge_all()
        return rows


def add(tenant: str, url: str, subject: str, list_path: str = "", label: str = "",
        filter_key: str = "", by: str = "") -> dict:
    url, subject = (url or "").strip(), (subject or "").strip()
    if not url.startswith("https://"):
        return {"error": "a feed URL must be https://"}
    if not re.fullmatch(r"[a-z_]+\.[a-z_]+", subject):
        return {"error": "subject must look like area.name, e.g. coverage.countries"}
    with db.SessionLocal() as s:
        row = (s.query(db.KbApiSource).filter(db.KbApiSource.tenant == tenant,
                                              db.KbApiSource.url == url,
                                              db.KbApiSource.subject == subject).one_or_none())
        if row is None:
            row = db.KbApiSource(tenant=tenant, url=url, subject=subject)
            s.add(row)
        row.list_path, row.label, row.filter_key, row.added_by = list_path, label, filter_key, by
        s.commit()
        return {"id": row.id}


def _at(data, path: str):
    for part in [p for p in (path or "").split(".") if p]:
        if isinstance(data, dict):
            data = data.get(part)
        elif isinstance(data, list) and part.isdigit():
            data = data[int(part)] if int(part) < len(data) else None
        else:
            return None
    return data


def read_feed(feed) -> dict:
    """{ok, count, sample} or {ok: False, error} — network + count, no storage."""
    import httpx
    try:
        r = httpx.get(feed.url, timeout=25, headers={"Accept": "application/json"})
        if r.status_code != 200:
            return {"ok": False, "error": f"HTTP {r.status_code}"}
        data = json.loads(r.text)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": exc.__class__.__name__}
    items = _at(data, feed.list_path)
    if not isinstance(items, list):
        return {"ok": False, "error": f"no list at {feed.list_path or '(root)'}"}
    if feed.filter_key:
        # e.g. "isAllowed": count only entries whose flag is true.
        items = [x for x in items if isinstance(x, dict) and x.get(feed.filter_key) in (True, "true", 1)]
    names = [str(x.get("name") or x.get("symbol") or x.get("code") or "") if isinstance(x, dict)
             else str(x) for x in items[:8]]
    return {"ok": True, "count": len(items), "sample": [n for n in names if n]}


def read_all(tenant: str, apply: bool = False) -> list[dict]:
    out = []
    for f in feeds(tenant):
        got = read_feed(f)
        if got.get("ok") and apply:
            statements.record(tenant, f.url, [{
                "subject": f.subject, "value": str(got["count"]), "number": float(got["count"]),
                "qualifier": "counted", "unit": f.list_path or "items",
                "text": f"{f.label or f.url}: the feed lists {got['count']} "
                        f"(e.g. {', '.join(got['sample'])[:160]})",
                "field": "api", "extractor": "api", "locator": f.list_path}],
                authority="derived")
        out.append({"url": f.url, "subject": f.subject, **got})
    return out
