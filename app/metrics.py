"""What each system is worth reporting, declared per system as data.

Two audiences, and conflating them is why reports get ignored. A TECHNICAL
metric answers "is this working" — checks run, catches, coverage, failures. A
BUSINESS metric answers "what did it do for me" — replies answered, objections
handled, money. The first belongs to Gomeh; the second is what the client is
paying for, and a report that leads with validator counts is a report about us.

**Declared on the system, never coded per system.** A metric is a row with a
`source` saying where it comes from, so adding one is data and the assembler
does not grow a clause. That is the same rule `kb_needs` and `SCOPED` follow,
and the same rule `oauth.configured` broke.

Four sources, and the third and fourth are the honest ones:

  `ledger` / `kb` / `assurance`  we compute it from our own record.
  `provider`                    the client's platform holds it, and it needs
                                the `reports` system, which is not built.
  `blocked`                     we could compute it if something upstream
                                were written. `% drafts sent as-is` needs
                                `SystemRun.edit_diff`, which nothing writes.
  `asked`                       NOT OURS TO COMPUTE. What a support reply
                                costs in staff time is a fact about the
                                client's business. A platform that guesses it
                                puts an invented number in a document the
                                client forwards to somebody else.

`asked` is also the privacy path. A client who declines to connect their store
is not a client who gets a report with a silent hole in it — the figures move
to `asked` and `request_email` composes the ask.
"""
from __future__ import annotations

import datetime as dt

from . import db

#: Metrics per system. `key` is stable; `label` is what a client reads.
CATALOG: dict[str, list[dict]] = {
    "service_desk": [
        {"key": "replies_sent", "label": "Emails answered",
         "kind": "business", "source": "ledger",
         "how": "outputs of format 'reply' that were approved or published"},
        {"key": "situations_seen", "label": "What people asked about",
         "kind": "business", "source": "ledger",
         "how": "replies grouped by the situation the question was placed in"},
        {"key": "objections_handled", "label": "Objections answered",
         "kind": "business", "source": "ledger",
         "how": "distinct approved objections an outgoing reply drew on"},
        {"key": "claims_discovered", "label": "New proof found",
         "kind": "business", "source": "kb",
         "how": "claims first recorded in the period, whatever found them"},
        {"key": "checks_run", "label": "Replies checked before sending",
         "kind": "technical", "source": "assurance"},
        {"key": "caught", "label": "Barred phrases stopped",
         "kind": "business", "source": "assurance",
         "how": "the model wrote it, deterministic code stopped it — without "
                "this the phrase goes out"},
        {"key": "sent_as_is", "label": "Drafts sent without an edit",
         "kind": "business", "source": "ledger",
         "how": "approvals whose sent text matched the drafted text — measured "
                "from the Gmail draft that actually went out, not from a copy"},
    ],
    "catalog_compliance": [
        {"key": "violations_found", "label": "Barred claims found in the catalogue",
         "kind": "business", "source": "ledger",
         "how": "findings on compliance runs in the period"},
        {"key": "checks_run", "label": "Checks run", "kind": "technical",
         "source": "assurance"},
        {"key": "products_read", "label": "Products read",
         "kind": "technical", "source": "provider",
         "needs": "the reports system, which is declared and not built"},
    ],
    "campaign_email": [
        {"key": "drafts", "label": "Campaigns drafted", "kind": "business",
         "source": "ledger"},
        {"key": "caught", "label": "Barred phrases stopped", "kind": "business",
         "source": "assurance"},
        {"key": "sends", "label": "Sends, opens and clicks", "kind": "business",
         "source": "provider",
         "needs": "the reports system, which is declared and not built"},
    ],
    "ad_creative": [
        {"key": "drafts", "label": "Ad variants drafted", "kind": "business",
         "source": "ledger"},
        {"key": "caught", "label": "Barred phrases stopped", "kind": "business",
         "source": "assurance"},
        {"key": "spend_return", "label": "Spend and return", "kind": "business",
         "source": "provider",
         "needs": "the reports system, which is declared and not built"},
    ],
}


#: The headline numbers a report is judged on, per business model.
#:
#: These are ACCOUNT-level, not system-level, and they are deliberately the
#: figures a client already tracks and could recite from memory. The first
#: version of this asked "what does one support reply cost you in staff time" —
#: owner's correction: *"they won't have that answer"*. He is right, and the
#: mistake is worth naming: that is an ops-accounting question we wanted the
#: answer to in order to derive a number OURSELVES. Asking a client to do our
#: arithmetic gets no reply, and deserves none.
#:
#: The model decides the vocabulary. A venue is measured in enquiries and events
#: booked; a store in revenue and average order value. Reporting a venue's
#: "average order value" is not a small error — it is the client concluding we
#: do not know what their business is.
#:
#: Vocabulary reused from `kb.SITUATIONS`' "who they are" set rather than a
#: second taxonomy invented here.
OUTCOMES: dict[str, list[dict]] = {
    "ecom_inventory": [
        {"key": "revenue", "label": "Revenue", "capability": "commerce"},
        {"key": "orders", "label": "Orders", "capability": "commerce"},
        {"key": "aov", "label": "Average order value", "capability": "commerce"},
        {"key": "returning_rate", "label": "Share of orders from returning customers",
         "capability": "commerce"},
    ],
    "ecom_dtc": [
        {"key": "revenue", "label": "Revenue", "capability": "commerce"},
        {"key": "orders", "label": "Orders", "capability": "commerce"},
        {"key": "aov", "label": "Average order value", "capability": "commerce"},
    ],
    "local_venue": [
        {"key": "enquiries", "label": "Enquiries received"},
        {"key": "calls_booked", "label": "Calls or site visits booked"},
        {"key": "events_booked", "label": "Events booked"},
        {"key": "avg_event_value", "label": "Average event value"},
    ],
    "b2b_spec": [
        {"key": "samples_requested", "label": "Samples or specs requested"},
        {"key": "quotes_issued", "label": "Quotes issued"},
        {"key": "projects_won", "label": "Projects won"},
        {"key": "avg_project_value", "label": "Average project value"},
    ],
    "digital_products": [
        {"key": "leads", "label": "New leads"},
        {"key": "calls_booked", "label": "Calls booked"},
        {"key": "closed", "label": "Clients closed"},
        {"key": "avg_contract_value", "label": "Average contract value"},
    ],
    "coaching": [
        {"key": "leads", "label": "New leads"},
        {"key": "calls_booked", "label": "Calls booked"},
        {"key": "closed", "label": "Clients closed"},
    ],
    "real_estate": [
        {"key": "viewings", "label": "Viewings booked"},
        {"key": "offers", "label": "Offers received"},
        {"key": "closed", "label": "Deals closed"},
    ],
    "food_bev": [
        {"key": "covers", "label": "Covers served"},
        {"key": "bookings", "label": "Bookings taken"},
        {"key": "avg_spend", "label": "Average spend per cover"},
    ],
}


def outcomes(tenant: str, days: int = 30) -> list[dict]:
    """The client's headline numbers, resolved to where each must come from.

    Three states, and keeping them apart is what stops us asking a client for
    something we could already read:

      `our record`  not used yet — no outcome is computed from our tables.
      `not wired`   the capability IS connected, so this is OURS to read and
                    the `reports` system is what is missing. NEVER asked.
      `asked`       there is no connection that could answer it, so it is the
                    client's to tell us.

    An account nobody has classified reports that, rather than being handed a
    shop's vocabulary by default.
    """
    from . import credentials as cred, tenants

    t = tenants.get(tenant)
    if not t:
        return []
    model = (getattr(t, "business_model", "") or "").strip()
    if not model:
        return [{"key": "_unclassified", "label": "Business model not set",
                 "value": None, "unavailable": "unknown business model",
                 "why": "outcomes depend on what the business IS — a venue is "
                        "measured in events booked, a store in average order "
                        "value",
                 "fix": "set business_model on the account"}]
    if model not in OUTCOMES:
        return [{"key": "_unknown_model", "label": f"No outcomes for {model!r}",
                 "value": None, "unavailable": "model not in OUTCOMES",
                 "why": "nobody has said what this kind of business is judged "
                        "on", "fix": "add it to metrics.OUTCOMES"}]

    wired = cred.wired_capabilities(tenant)
    out = []
    for o in OUTCOMES[model]:
        row = {"key": o["key"], "label": o["label"], "kind": "business",
               "model": model}
        cap = o.get("capability", "")
        supplied = _supplied(tenant, o["key"],
                             db.utcnow() - dt.timedelta(days=days))
        if supplied:
            row.update(value=supplied.value, unit=supplied.unit or "",
                       source=f"supplied by {supplied.supplied_by or 'the client'}")
        elif cap and cap in wired:
            # OURS to read. Asking for it would be asking a client to do work
            # we have already been given access to do.
            row.update(value=None, unavailable="not wired",
                       why=f"{cap} is connected, so this is ours to read — the "
                           f"reports system is what is missing",
                       fix="build the reports system")
        else:
            row.update(value=None, unavailable="waiting on the client",
                       why=(f"no {cap} connection" if cap
                            else "nothing we can connect to holds this"))
        out.append(row)
    return out


def for_system(key: str) -> list[dict]:
    return list(CATALOG.get(key, []))


def compute(tenant: str, system_key: str, days: int = 30) -> list[dict]:
    """Every declared metric, with a value or a named reason there is none.

    A metric that cannot be produced is RETURNED, not skipped. Skipping it
    makes a short report look complete, and the whole point of declaring
    metrics per system is that the gaps are as visible as the numbers.
    """
    since = db.utcnow() - dt.timedelta(days=days)
    out = []
    for m in for_system(system_key):
        row = {k: m[k] for k in ("key", "label", "kind") if k in m}
        row["how"] = m.get("how", "")
        src = m["source"]
        if src == "asked":
            supplied = _supplied(tenant, m["key"], since)
            if supplied:
                row.update(value=supplied.value, unit=supplied.unit,
                           source=f"supplied by {supplied.supplied_by or 'the client'}",
                           supplied_at=db.as_utc(supplied.at).date().isoformat())
            else:
                row.update(value=None, unavailable="waiting on the client",
                           ask=m.get("ask", ""), why=m.get("why", ""))
        elif src == "blocked":
            row.update(value=None, unavailable="not measurable yet",
                       why=m.get("needs", ""), fix=m.get("fix", ""))
        elif src == "provider":
            row.update(value=None, unavailable="not wired",
                       why=m.get("needs", ""))
        else:
            row.update(value=_from_record(tenant, system_key, m, since),
                       source="our record")
        out.append(row)
    return out


def _supplied(tenant: str, key: str, since) -> db.ReportedFigure | None:
    """The client's own answer, if it covers this period.

    Scoped by period on purpose. Last quarter's average order value is not this
    quarter's, and silently carrying one forward is how a report becomes
    fiction that the client signed off on.
    """
    with db.SessionLocal() as s:
        rows = (s.query(db.ReportedFigure)
                .filter(db.ReportedFigure.tenant == tenant,
                        db.ReportedFigure.metric_key == key)
                .order_by(db.ReportedFigure.at.desc()).all())
        for r in rows:
            if not r.period_end or r.period_end >= since.date().isoformat():
                s.expunge(r)
                return r
    return None


def _from_record(tenant: str, system_key: str, m: dict, since):
    """Compute one metric from our own tables."""
    from . import assurance, kb
    key = m["key"]

    if m["source"] == "assurance":
        rep = assurance.report(tenant, 3650)
        if key == "checks_run":
            return rep.get("events", 0)
        if key == "caught":
            return rep.get("caught_total", 0)
        return None

    if m["source"] == "kb":
        if key == "claims_discovered":
            with db.SessionLocal() as s:
                return (s.query(db.KbClaim)
                        .filter(db.KbClaim.tenant == tenant,
                                db.KbClaim.verified_at >= since).count())
        return None

    with db.SessionLocal() as s:
        q = (s.query(db.Output)
             .filter(db.Output.tenant == tenant,
                     db.Output.system_key == system_key,
                     db.Output.created_at >= since))
        rows = q.all()

    sent = [o for o in rows if o.status in ("approved", "published")]
    if key == "replies_sent":
        return len([o for o in sent if (o.format or "") == "reply"])
    if key == "situations_seen":
        counts: dict[str, int] = {}
        for o in sent:
            if o.situation:
                counts[o.situation] = counts.get(o.situation, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))
    if key == "objections_handled":
        return len({o.objection_id for o in sent if o.objection_id})
    if key in ("drafts", "violations_found"):
        return len(rows)
    if key == "sent_as_is":
        # Unblocked by the draft/approval sync: the delta is recorded on the
        # approval when the draft is sent, so this is a count rather than an
        # apology. Reported as "n of m" rather than a bare percentage — a
        # percentage of three replies is not a rate, and rounding it to one
        # looks like a measurement.
        with db.SessionLocal() as s2:
            aps = [a for a in s2.query(db.Approval)
                   .filter(db.Approval.tenant == tenant,
                           db.Approval.kind == "send_email",
                           db.Approval.created_at >= since).all()
                   if (a.payload or {}).get("edit")]
        if not aps:
            return None
        clean = sum(1 for a in aps if (a.payload or {})["edit"].get("as_is"))
        return f"{clean} of {len(aps)}"
    return None


def asks(tenant: str, days: int = 30) -> list[dict]:
    """Every figure this account's systems need FROM THE CLIENT.

    The privacy path. A client who will not connect their store still gets a
    complete report — the figures move here and are asked for, once, in one
    message rather than five.
    """
    from . import systems
    out = []
    for row in systems.for_tenant(tenant):
        for m in compute(tenant, row.key, days):
            if m.get("unavailable") == "waiting on the client":
                out.append({**m, "system": row.key})
    # The headline outcomes, and ONLY the ones no connection could answer.
    # A figure marked "not wired" is ours to read and must never be asked for:
    # asking a client for a number we already have access to is asking them to
    # do our work, and it is how a report request stops being answered.
    for o in outcomes(tenant, days):
        if o.get("unavailable") == "waiting on the client":
            out.append({**o, "system": "outcomes"})
    return out


def record_figure(tenant: str, metric_key: str, value: str, *,
                  period_start: str = "", period_end: str = "",
                  unit: str = "", supplied_by: str = "",
                  note: str = "") -> str:
    """File a number the client sent back. Stored as given, never coerced."""
    if not (tenant and metric_key and str(value).strip()):
        return "tenant, metric and value are all required."
    with db.SessionLocal() as s:
        s.add(db.ReportedFigure(
            tenant=tenant, metric_key=metric_key, value=str(value).strip(),
            period_start=period_start, period_end=period_end, unit=unit,
            supplied_by=supplied_by, note=note))
        s.commit()
    return (f"{metric_key} recorded for {tenant}"
            + (f" ({period_start} to {period_end})" if period_end else "")
            + (f", supplied by {supplied_by}" if supplied_by else "") + ".")


def request_email(tenant: str, days: int = 30, *, to: str = "",
                  queue: bool = False) -> dict:
    """Compose the one message that asks the client for what we cannot read.

    ONE message, not one per figure. A client who declines to connect their
    store is already choosing friction; five separate emails asking for a
    number each is how that choice turns into no report at all.

    Every ask carries WHY. "What does a support reply cost you in staff time"
    reads as an odd question until it is followed by "we multiply it by the
    replies we answered", and a client who understands what a number is for
    sends a considered one instead of a round one.

    **Composed, never sent.** `queue=True` puts it in the approval queue, which
    is where anything leaving the building belongs — the substrate has never
    sent anything as a side effect of producing it, and a report request going
    out under Gomeh's name without him reading it would be the first.
    """
    from . import tenants

    t = tenants.get(tenant)
    if not t:
        return {"ok": False, "error": f"no account keyed {tenant!r}"}
    wanted = asks(tenant, days)
    if not wanted:
        return {"ok": True, "needed": 0,
                "note": "nothing needs asking — every figure is either on our "
                        "record or named as unmeasurable"}

    end = db.utcnow().date()
    start = end - dt.timedelta(days=days)
    lines = [
        f"Hello,",
        "",
        f"I am putting together the {start.isoformat()} to {end.isoformat()} "
        f"report for {t.name}. Most of it comes from our own records. These "
        f"{len(wanted)} are the headline numbers we cannot see from here, "
        f"because we are not connected to the system that holds them:",
        "",
    ]
    for i, m in enumerate(wanted, 1):
        lines.append(f"{i}. {m['label']}")
        if m.get("ask"):
            lines.append(f"   {m['ask']}")
        lines.append("")
    lines += [
        "Round numbers are fine. The report says where each figure came from, "
        "so an estimate is shown as an estimate rather than presented as "
        "measured.",
        "",
        "If you would rather we read any of these directly, we can connect to "
        "the system that holds them and stop asking.",
        "",
        "Thank you,",
    ]
    body = "\n".join(lines)
    subject = (f"{t.name} — {len(wanted)} figure(s) for the "
               f"{start.isoformat()} to {end.isoformat()} report")

    out = {"ok": True, "needed": len(wanted), "to": to, "subject": subject,
           "body": body, "metrics": [m["key"] for m in wanted], "queued": False}
    if queue:
        from . import approvals
        out["approval_id"] = approvals.request_approval(
            kind="send_email",
            summary=f"Ask {t.name} for {len(wanted)} report figure(s)",
            # `account` is what `_execute` sends FROM and it indexes the key
            # directly. This payload never carried it, so approving the
            # figures request raised KeyError instead of sending — found
            # building `reports`, which leaves by the same door.
            payload={"to": to, "subject": subject, "body": body,
                     "tenant": tenant,
                     "account": getattr(t, "gmail_alias", "") or ""},
            notify=False)
        out["queued"] = True
    return out
