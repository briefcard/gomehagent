"""Common and high-value audience segments, organized by BUSINESS MODEL.

Who a campaign should target is not a per-client guess — it follows from what
KIND of business it is. An inventory e-com store has lapsed buyers, a reorder
cadence and VIPs; a local venue has past bookers and warm enquiries; a B2B spec
seller has sample-requesters and quote-stage prospects. So the catalog is keyed
on `Tenant.business_model` (already on the row, from the reporting work), which
is what makes it tenant-GENERIC: onboarding a client of a known model gets that
model's segments for free, and adding a model is a row here — never a per-client
fork. Locked decision #3, applied to segmentation.

Each segment declares:

    key          stable id, used to target a campaign
    name         what an operator calls it
    definition   the cohort in plain words — the criteria, not a query
    tier         "high_value" | "common" — high_value = worth a campaign now
    source       where the cohort comes from: "esp" (list/segment engagement),
                 "commerce" (purchase behaviour), or "lifecycle" (time since)
    angle        the campaign you would actually run to it

`for_tenant(tenant)` resolves a client's model to its segments, high-value
first. It does NOT invent a client's data — it says which segments are worth
building. `reconcile(tenant)` then asks the client's live ESP which of these
already EXIST as segments and which are still to build, so the operator sees the
gap rather than a flat wishlist.
"""
from __future__ import annotations

from . import tenants

# ---------------------------------------------------------------------------
# The catalog. High-value segments are the ones a campaign should be aimed at
# first — they convert or they retain revenue; common segments are the standard
# lifecycle coverage every program wants. Ordered within each model by that.
# ---------------------------------------------------------------------------
CATALOG: dict[str, list[dict]] = {
    "ecom_inventory": [
        dict(key="reorder_due", name="Reorder due", tier="high_value",
             source="lifecycle",
             definition="Bought a consumable and are near the end of a typical "
                        "cycle since (≈30–45 days for most SKUs).",
             angle="A one-tap reorder before they run out — the highest-intent "
                   "moment in a consumables business."),
        dict(key="vip_high_aov", name="VIP / high value", tier="high_value",
             source="commerce",
             definition="Top spenders by lifetime value or order value — the "
                        "small share of buyers who are most of the revenue.",
             angle="Early access, a thank-you, or a loyalty perk — protect the "
                   "relationship that matters most."),
        dict(key="lapsed_60_90", name="Lapsed (60–90 days)", tier="high_value",
             source="lifecycle",
             definition="Bought before, nothing in 60–90 days — cooling but not "
                        "gone.",
             angle="A reason to come back now, while the habit is recoverable "
                   "and before a win-back discount is needed."),
        dict(key="repeat_buyers", name="Repeat buyers", tier="high_value",
             source="commerce",
             definition="Two or more orders — proven demand, the cohort most "
                        "likely to buy again.",
             angle="Cross-sell the complements to what they already trust."),
        dict(key="cart_abandoners", name="Cart abandoners", tier="common",
             source="commerce",
             definition="Added to cart, did not check out, within a few days.",
             angle="A nudge back to the exact cart, with the objection answered."),
        dict(key="first_time_buyers", name="First-time buyers", tier="common",
             source="commerce",
             definition="Exactly one order — the make-or-break window for a "
                        "second.",
             angle="A post-purchase welcome that earns the second order."),
        dict(key="new_subscribers", name="New subscribers (no purchase)",
             tier="common", source="esp",
             definition="Joined the list, never bought.",
             angle="A welcome that leads with the strongest proof and a first-"
                   "order reason."),
        dict(key="engaged_non_buyers", name="Engaged, not buying", tier="common",
             source="esp",
             definition="Opens and clicks, no purchase — interested, unconvinced.",
             angle="Answer the hesitation directly; the objection is what stands "
                   "between interest and a first order."),
        dict(key="win_back", name="Win-back (120+ days)", tier="common",
             source="lifecycle",
             definition="Lapsed past the point a normal reminder works.",
             angle="A real reason to return — a genuine offer or what's new "
                   "since they left."),
        dict(key="unengaged_sunset", name="Unengaged (sunset)", tier="common",
             source="esp",
             definition="No opens or clicks in 90+ days — deliverability risk.",
             angle="One last re-engagement, then suppress — sending to the dead "
                   "hurts everyone else's inbox placement."),
    ],
    "ecom_dtc": [  # alias-ish to inventory but leaner; reuse the strong ones
        dict(key="repeat_buyers", name="Repeat buyers", tier="high_value",
             source="commerce",
             definition="Two or more orders.",
             angle="Cross-sell what pairs with what they bought."),
        dict(key="lapsed_60_90", name="Lapsed (60–90 days)", tier="high_value",
             source="lifecycle", definition="Cooling buyers.",
             angle="A timely reason to return."),
        dict(key="new_subscribers", name="New subscribers", tier="common",
             source="esp", definition="Joined, never bought.",
             angle="A welcome with the strongest proof."),
        dict(key="cart_abandoners", name="Cart abandoners", tier="common",
             source="commerce", definition="Added, didn't buy.",
             angle="Back to the cart, objection answered."),
    ],
    "local_venue": [
        dict(key="past_bookers", name="Past bookers", tier="high_value",
             source="commerce",
             definition="Have booked an event before — the warmest audience a "
                        "venue has.",
             angle="An invitation to book again for the next occasion, referencing "
                   "what they held before."),
        dict(key="hot_enquiries", name="Warm enquiries (no booking)",
             tier="high_value", source="esp",
             definition="Enquired recently, have not booked — highest intent, "
                        "cooling fast.",
             angle="Answer the deciding question (date, capacity, price band) and "
                   "make the next step easy."),
        dict(key="corporate_planners", name="Corporate planners", tier="high_value",
             source="esp",
             definition="Enquired for corporate/off-site events — larger, "
                        "repeatable spend.",
             angle="Lead with the corporate offer and the capacity/AV proof they "
                   "actually screen on."),
        dict(key="seasonal_interest", name="Seasonal interest", tier="common",
             source="lifecycle",
             definition="Interest tied to a season (holiday parties, weddings, "
                        "summer).",
             angle="Reach them before the season's dates fill."),
        dict(key="newsletter", name="Newsletter / general list", tier="common",
             source="esp", definition="On the list, no specific stage.",
             angle="Keep the venue top of mind with real events and availability."),
    ],
    "b2b_spec": [
        dict(key="quote_no_order", name="Quoted, no order", tier="high_value",
             source="esp",
             definition="Requested a quote, did not proceed — a live deal that "
                        "stalled.",
             angle="Remove the blocker: lead time, a sample, a spec question — "
                   "the thing that stalled it."),
        dict(key="sample_requested", name="Sample requested", tier="high_value",
             source="esp",
             definition="Requested samples, not yet specified — deep in "
                        "evaluation.",
             angle="Support the spec decision with the technical proof and the "
                   "projects it has been used on."),
        dict(key="trade_accounts", name="Trade accounts", tier="high_value",
             source="esp",
             definition="Architects, designers, contractors — repeat "
                        "specifiers, not one-off buyers.",
             angle="Trade pricing, new material drops, and CEU/spec resources."),
        dict(key="catalog_downloaders", name="Catalog / spec downloaders",
             tier="common", source="esp",
             definition="Downloaded a catalog or spec sheet — early research.",
             angle="Nurture with application ideas and proof, toward a sample "
                   "request."),
        dict(key="newsletter", name="Newsletter / general list", tier="common",
             source="esp", definition="On the list, no stage.",
             angle="New materials and completed projects."),
    ],
    "digital_products": [
        dict(key="trial_no_convert", name="Trial, not converted", tier="high_value",
             source="esp",
             definition="Started a trial or free tier, did not upgrade.",
             angle="Show the outcome they came for and remove the upgrade "
                   "friction."),
        dict(key="churned", name="Churned", tier="high_value", source="esp",
             definition="Was paying, cancelled.",
             angle="What's changed since they left, and a reason to come back."),
        dict(key="upsell_candidates", name="Upsell candidates", tier="high_value",
             source="esp",
             definition="Active and near a plan limit or using the feature that "
                        "gates the next tier.",
             angle="The next tier framed as the thing they are already reaching "
                   "for."),
        dict(key="leads", name="Leads (not started)", tier="common", source="esp",
             definition="Signed up for content or a list, no product yet.",
             angle="A clear first step and the proof it works."),
        dict(key="onboarding", name="Onboarding", tier="common",
             source="lifecycle",
             definition="New, in the first-value window.",
             angle="Get them to the first real result fast."),
    ],
}


def by_model(model: str) -> list[dict]:
    """The segment templates for one business model, high-value first."""
    rows = list(CATALOG.get(model or "", []))
    rows.sort(key=lambda s: (s["tier"] != "high_value", s["name"]))
    return rows


#: Cohorts that already know the brand — they have bought, booked, quoted or
#: trialled. Everyone else is treated as cold.
_WARM = {"reorder_due", "vip_high_aov", "lapsed_60_90", "repeat_buyers",
         "first_time_buyers", "win_back", "past_bookers", "hot_enquiries",
         "quote_no_order", "sample_requested", "trade_accounts",
         "trial_no_convert", "churned", "upsell_candidates"}


def warmth(key: str) -> str:
    """`warm` if this cohort already knows the brand, else `cold`.

    This is the one genuine fork in the email-craft literature, and it is
    settled by AUDIENCE rather than by taste. Halbert's A-pile argument (a
    personal-looking letter survives a sort that a commercial-looking mailer
    does not) and the plain-text school pull one way; e-commerce's designed
    templates pull the other. Chase Dimond's resolution is the one worth
    encoding: people who have bought from you do better on a letter that
    reads like a person wrote it, while people who might not remember who you
    are need the designed frame to place you.

    Unknown keys are COLD on purpose. A designed email is merely less
    intimate for a warm reader; a bare letter from a brand a cold reader does
    not recognise is a stranger's email, and that is the worse failure.
    """
    return "warm" if str(key or "") in _WARM else "cold"


def for_tenant(tenant: str) -> dict:
    """The segments worth building for this client, from its business model.

    Refuses BY NAME when the account has no `business_model` set — that field
    decides everything here, and guessing it (a venue is not a shop) is the one
    error that makes the whole list wrong. Reporting it unset is a one-field fix,
    not a mystery.
    """
    t = tenants.get(tenant)
    if not t:
        return {"ok": False, "error": f"unknown account {tenant!r}"}
    model = (t.business_model or "").strip()
    if not model:
        # The fix has an exact address — a refusal that says "set it on the
        # account" without naming WHERE sent the owner hunting through tabs
        # for a control that existed all along (2026-08-21).
        return {"ok": False, "error": (
            f"{tenant} has no business_model set — the control is on the "
            f"Connections tab, on this account's card (“Business "
            f"model”, one save); its segments follow from it.")}
    rows = by_model(model)
    if not rows:
        return {"ok": False, "error": (
            f"no segment catalog for business model {model!r} yet — add one in "
            f"segments.CATALOG.")}
    return {"ok": True, "tenant": tenant, "business_model": model,
            "high_value": [s for s in rows if s["tier"] == "high_value"],
            "common": [s for s in rows if s["tier"] == "common"],
            "segments": rows}


def _norm(s: str) -> str:
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())


# ---------------------------------------------------------------------------
# The remembered link — catalog key → the ESP's own segment id.
#
# Stored on `Tenant.esp["segments"]`, INSIDE the ESP connection block on
# purpose: the map belongs to that connection, and switching providers makes
# it visibly stale rather than silently wrong. The rule is the Canva-folder
# rule, verbatim: the id is remembered, never searched for by name again —
# a name search eventually matches a renamed segment or misses it entirely,
# and `materialize` would then build a DUPLICATE in a live account.
# ---------------------------------------------------------------------------

def links(tenant: str) -> dict:
    """The stored key → {id, name} map. Empty when nothing was ever linked."""
    t = tenants.get(tenant)
    return dict(((t.esp or {}).get("segments") or {})) if t else {}


def _store_links(tenant: str, found: dict) -> None:
    from . import db
    if not found:
        return
    with db.SessionLocal() as s:
        t = s.get(db.Tenant, tenant)
        if not t:
            return
        cfg = dict(t.esp or {})
        cur = dict(cfg.get("segments") or {})
        cur.update(found)
        cfg["segments"] = cur
        t.esp = cfg
        s.commit()


def reconcile(tenant: str) -> dict:
    """Cross the catalog against the client's LIVE ESP segments. Read-only.

    Matching is ID-FIRST: a remembered id wins even when the segment was
    renamed in the ESP (that is what remembering is for); the loose name
    compare is only for segments nothing has linked yet. Alongside the rows
    it returns `drift` — the findings a maintainer acts on, each named:
    a remembered id that vanished from the ESP, a rename (informational —
    still linked), and a segment reporting literally zero members. A count
    the provider never sent is ABSENT, not zero, and raises nothing.

    If the ESP is not connected it returns the catalog with everything
    `to_build` and says the ESP could not be read, rather than pretending
    nothing exists.
    """
    base = for_tenant(tenant)
    if not base.get("ok"):
        return base

    from . import esp
    live = esp.audiences(tenant)
    rows_live = (live.get("audiences") or []) if live.get("ok") else []
    by_id = {a.get("id", ""): a for a in rows_live if a.get("id")}
    by_name = {_norm(a["name"]): a for a in rows_live}
    stored = links(tenant)

    out, drift = [], []
    for s in base["segments"]:
        remembered = (stored.get(s["key"]) or {}).get("id", "")
        match, linked_by, lost = None, "", False
        if remembered:
            match = by_id.get(remembered)
            if match is not None:
                linked_by = "id"
            elif live.get("ok"):
                lost = True
                drift.append({"key": s["key"], "name": s["name"],
                              "what": (f"the remembered segment id for "
                                       f"{s['name']!r} no longer exists in "
                                       f"the ESP — deleted, or the account "
                                       f"changed; sync re-links by name if "
                                       f"one still matches")})
        if match is None:
            match = by_name.get(_norm(s["name"])) or next(
                (a for k, a in by_name.items()
                 if _norm(s["key"]) in k or k in _norm(s["name"])), None)
            if match is not None:
                linked_by = "name"
        esp_name = (match or {}).get("name", "")
        if linked_by == "id" and _norm(esp_name) != _norm(s["name"]):
            drift.append({"key": s["key"], "name": s["name"],
                          "what": (f"renamed in the ESP to {esp_name!r} — "
                                   f"still linked by its remembered id")})
        count = (match or {}).get("count")
        if match is not None and isinstance(count, (int, float)) and count == 0:
            drift.append({"key": s["key"], "name": s["name"],
                          "what": "exists in the ESP and reports zero "
                                  "members — the conditions may not match "
                                  "anybody"})
        out.append({**s, "state": "exists" if match else "to_build",
                    "esp_segment_id": (match or {}).get("id", ""),
                    "esp_name": esp_name, "linked_by": linked_by,
                    "lost_id": lost,
                    "esp_count": "" if count is None else count})

    return {"ok": True, "tenant": tenant,
            "business_model": base["business_model"],
            "esp_read": live.get("ok", False),
            "esp_note": "" if live.get("ok") else live.get("error", ""),
            "exists": [s for s in out if s["state"] == "exists"],
            "to_build": [s for s in out if s["state"] == "to_build"],
            "drift": drift,
            "segments": out}


def materialize(tenant: str, apply: bool = False, rec: dict | None = None) -> dict:
    """Build the missing catalog segments IN the client's live ESP.

    Dry-run by default — the harvest pattern: without `apply` it reports what
    WOULD be created and touches nothing, because Eien's first live probe
    (2026-08-21) came back `audiences: []` and the answer to an empty ESP must
    not be a route that writes to it on page load. `sabotage.segments_dry_run
    _gate` removes the gate and the suite fails.

    Per segment, one of four named outcomes: `exists` (reconcile matched it),
    `created` / `would_create` (the adapter expressed it natively), or
    `unmapped` — the adapter cannot express it yet and SAYS SO, because a
    guessed condition builds a segment that silently matches nobody, which is
    worse than a named gap. A segment is created only from the adapter's own
    condition table; nothing here invents criteria.
    """
    rec = rec if rec is not None else reconcile(tenant)
    if not rec.get("ok"):
        return rec
    if not rec.get("esp_read"):
        return {"ok": False, "error": (
            f"the live ESP could not be read ({rec.get('esp_note', '')}) — "
            f"building against an unreadable ESP risks duplicating every "
            f"segment it already holds.")}

    from . import esp
    mod, refusal = esp.backend(tenant)
    if refusal:
        return {"ok": False, "error": refusal}
    conditions_for = getattr(mod, "segment_conditions_for", None)
    create = getattr(mod, "create_segment", None)
    if not (conditions_for and create):
        return {"ok": False, "error": (
            f"{esp.provider_for(tenant)} has no segment-building surface in "
            f"its adapter yet — segments must be created in its own UI, or "
            f"the adapter needs `segment_conditions_for`/`create_segment`.")}

    done, would, unmapped, failed = [], [], [], []
    for s in rec["to_build"]:
        groups = conditions_for(s["key"])
        if not groups:
            unmapped.append({"key": s["key"], "name": s["name"],
                             "why": "the adapter cannot express this cohort "
                                    "natively yet — see its condition table "
                                    "for what is missing"})
            continue
        if not apply:
            would.append({"key": s["key"], "name": s["name"]})
            continue
        got = create(tenant, s["name"], groups)
        if got.get("ok"):
            done.append({"key": s["key"], "name": s["name"],
                         "segment_id": got["segment_id"]})
        else:
            failed.append({"key": s["key"], "name": s["name"],
                           "error": got.get("error", "")[:300]})
    # The id is remembered AT CREATION — the one moment it is known for
    # certain — never left for a later name search to rediscover.
    _store_links(tenant, {d["key"]: {"id": d["segment_id"], "name": d["name"]}
                          for d in done})
    return {"ok": True, "tenant": tenant, "applied": bool(apply),
            "existing": [{"key": s["key"], "name": s["name"],
                          "esp_segment_id": s["esp_segment_id"]}
                         for s in rec["exists"]],
            "created": done, "would_create": would,
            "unmapped": unmapped, "failed": failed,
            "note": ("" if apply else
                     "dry run — nothing was created; add apply=1 to build "
                     "the would_create list in the live ESP")}


# ---------------------------------------------------------------------------
# Maintenance — sync remembers, the sweep watches, nothing here writes to
# the live ESP. Creating segments stays `materialize(apply=1)`, an explicit
# act behind its dry-run gate; maintenance only keeps OUR map true and says
# what drifted.
# ---------------------------------------------------------------------------

def sync(tenant: str) -> dict:
    """Reconcile against the live ESP, REMEMBER every link, report drift.

    The write is to our own map (`Tenant.esp["segments"]`) and our own
    stored state — never to the client's ESP. Refuses when the ESP cannot
    be read: a sync against silence would report every remembered id as
    drift and unlink a healthy account.
    """
    import datetime as _dt
    import json as _json

    rec = reconcile(tenant)
    if not rec.get("ok"):
        return rec
    if not rec.get("esp_read"):
        return {"ok": False, "error": (
            f"the live ESP could not be read ({rec.get('esp_note', '')}) — "
            f"nothing was re-linked, because syncing against silence would "
            f"read every remembered segment as missing.")}

    stored = links(tenant)
    found = {}
    for s in rec["segments"]:
        if s["state"] != "exists" or not s["esp_segment_id"]:
            continue
        cur = stored.get(s["key"]) or {}
        live_name = s.get("esp_name") or s["name"]
        if cur.get("id") != s["esp_segment_id"] or cur.get("name") != live_name:
            found[s["key"]] = {"id": s["esp_segment_id"], "name": live_name}
    _store_links(tenant, found)

    # The dry half of materialize rides along so the stored state can say
    # what is still to build and what the adapter cannot express — the card
    # renders from THIS record, never from a live call on page load.
    mat = materialize(tenant, apply=False, rec=rec)
    state = {
        "at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "esp_read": True,
        "linked": [{"key": s["key"], "name": s["name"],
                    "esp_name": s.get("esp_name", ""),
                    "esp_segment_id": s["esp_segment_id"],
                    "esp_count": s.get("esp_count", ""),
                    "linked_by": s.get("linked_by", "")}
                   for s in rec["exists"]],
        "to_build": ([{"key": w["key"], "name": w["name"]}
                      for w in mat.get("would_create", [])]
                     if mat.get("ok") else
                     [{"key": s["key"], "name": s["name"]}
                      for s in rec["to_build"]]),
        "unmapped": mat.get("unmapped", []) if mat.get("ok") else [],
        "build_note": "" if mat.get("ok") else mat.get("error", ""),
        "drift": rec["drift"],
        "relinked": sorted(found),
    }
    from . import db
    with db.SessionLocal() as s:
        row = s.get(db.Setting, f"segments_state:{tenant}")
        if row is None:
            s.add(db.Setting(key=f"segments_state:{tenant}",
                             value=_json.dumps(state)))
        else:
            row.value = _json.dumps(state)
        s.commit()
    return {"ok": True, **state}


def stored_state(tenant: str) -> dict | None:
    """The last sync's record, for surfaces — a page render must never be
    the moment a live ESP call happens. None means never synced, which is a
    different fact from synced-and-empty."""
    import json as _json

    from . import db
    with db.SessionLocal() as s:
        row = s.get(db.Setting, f"segments_state:{tenant}")
    if row is None or not (row.value or "").strip():
        return None
    try:
        return _json.loads(row.value)
    except ValueError:
        return None


def esp_id_for(tenant: str, key: str) -> dict:
    """The ESP segment id one campaign should target, or a named absence.

    The remembered map wins and costs no network call. A live name-match is
    the fallback for a segment nothing has linked yet — used for this draft
    and NOT persisted (the draft path stays read-only; `sync` remembers).
    Returns {id, name, via, why}; an empty id always carries a why.
    """
    stored = links(tenant).get(key) or {}
    if stored.get("id"):
        return {"id": stored["id"], "name": stored.get("name", ""),
                "via": "remembered", "why": ""}
    rec = reconcile(tenant)
    if rec.get("ok") and rec.get("esp_read"):
        for s in rec["segments"]:
            if s["key"] == key and s["state"] == "exists" and s["esp_segment_id"]:
                return {"id": s["esp_segment_id"],
                        "name": s.get("esp_name") or s["name"],
                        "via": "name-match",
                        "why": ("linked by name for this draft — run Sync "
                                "on the Segments card to remember the id")}
        return {"id": "", "name": "", "via": "",
                "why": (f"segment {key!r} does not exist in the ESP yet — "
                        f"build it from the Segments card")}
    return {"id": "", "name": "", "via": "",
            "why": ("the ESP could not be read ("
                    + (rec.get("esp_note") or rec.get("error", ""))[:200]
                    + ") — the draft is untargeted")}
