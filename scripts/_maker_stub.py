"""THE MAKER, FAKED — for suites that exercise the campaign system without a
model. The real maker is a model call (`recreate.run`); a suite with no
model gets this stand-in: a plain designed email built from the drafter's
message — its subject, its text, the products it names, the brand's mark
and address, the unsubscribe token — returned shippable, so every gate
downstream of the maker (claims, coherence, offers, the ledger, the
workroom, the push) is exercised on real words. Nothing here is a path
the app can take."""
from __future__ import annotations

import html as _html


def install(status: str = "shippable") -> None:
    from app import brand_theme, kb, recreate

    def fake_run(structure_id: str, tenant: str, entity_key: str = "", *, message=None, via="press", **kw) -> dict:
        m = dict(message or {})
        t = brand_theme.filled(brand_theme.live_theme(tenant) or {})
        subject = str(m.get("subject") or "An email from " + (t.get("name") or tenant))
        pre = str(m.get("preheader") or "")
        body = _html.escape(str(m.get("text") or ""))
        pics = [a for a in kb.assets(tenant) if (a.kind or "image") == "image" and a.url][:2]
        extra = [x for x in (kw.get("extra_pictures") or []) if x.get("url")]
        rows = ""
        for x in extra:
            rows += f'<tr><td><img src="{x["url"]}" alt="{_html.escape(str(x.get("title") or ""))}" width="600" style="width:100%"></td></tr>'
        if t.get("logo_url"):
            rows += f'<tr><td align="center" style="padding:24px"><img src="{t["logo_url"]}" alt="{_html.escape(t.get("name") or "")}" width="140"></td></tr>'
        for a in pics:
            rows += f'<tr><td><img src="{a.url}" alt="{_html.escape(a.title or "")}" width="600" style="width:100%"></td></tr>'
        rows += f'<tr><td style="padding:24px;font-family:Helvetica,Arial,sans-serif;font-size:15px;color:#1c1e22"><h1>{_html.escape(subject)}</h1><p>{body}</p></td></tr>'
        for p in (m.get("products") or [])[:4]:
            rows += f'<tr><td style="padding:0 24px 12px;font-family:Helvetica,Arial,sans-serif;color:#1c1e22"><a href="{p.get("url") or "#"}">{_html.escape(str(p.get("name") or ""))}</a> {_html.escape(str(p.get("price") or ""))}</td></tr>'
        for c in (m.get("claims") or [])[:3]:
            rows += f'<tr><td style="padding:0 24px 12px;font-family:Helvetica,Arial,sans-serif;color:#1c1e22">{_html.escape(str(c))}</td></tr>'
        rows += (f'<tr><td align="center" style="padding:24px;font-family:Helvetica,Arial,sans-serif;font-size:11px;color:#6b7280">'
                 f'{_html.escape(t["footer"].get("address") or "")}<br><a href="{{{{UNSUBSCRIBE}}}}">Unsubscribe</a></td></tr>')
        html = (f'<!DOCTYPE html><html><head><meta charset="utf-8"><title>{_html.escape(subject)}</title></head>'
                f'<body style="margin:0;background:#f2f3f5"><table role="presentation" width="100%"><tr><td align="center">'
                f'<table role="presentation" width="600" style="width:600px;max-width:600px;background:#ffffff">{rows}</table>'
                f'</td></tr></table></body></html>')
        text = " ".join(x for x in [subject, pre, str(m.get("text") or "")] + [str(c) for c in (m.get("claims") or [])]
                        + [str(p.get("name") or "") for p in (m.get("products") or [])] + [t["footer"].get("address") or ""] if x)
        return {"ok": True, "id": "fake", "status": status, "note": "made by the suite's stand-in maker",
                "findings": [], "rounds": [{"n": 0, "blocking": 0, "judged": True}], "calls": 0,
                "html": html, "text": text, "subject": subject, "preheader": pre,
                "media_ids": [x["id"] for x in extra if x.get("id")] + [a.id for a in pics], "blocking": 0}
    recreate.run = fake_run
