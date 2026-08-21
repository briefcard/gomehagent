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
        return {"ok": False, "error": (
            f"{tenant} has no business_model set — set it on the account "
            f"(ecom_inventory, local_venue, b2b_spec, digital_products…) and its "
            f"segments follow from it.")}
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


def reconcile(tenant: str) -> dict:
    """Cross the catalog against the client's LIVE ESP segments.

    Says which recommended segments already EXIST in the ESP (matched by a
    loose name compare) and which are still TO BUILD — so the operator sees the
    gap, not a flat wishlist. Read-only. If the ESP is not connected it returns
    the catalog with everything `to_build` and says the ESP could not be read,
    rather than pretending nothing exists.
    """
    base = for_tenant(tenant)
    if not base.get("ok"):
        return base

    from . import esp
    live = esp.audiences(tenant)
    existing = {_norm(a["name"]): a for a in (live.get("audiences") or [])} \
        if live.get("ok") else {}

    out = []
    for s in base["segments"]:
        match = existing.get(_norm(s["name"])) or next(
            (a for k, a in existing.items()
             if _norm(s["key"]) in k or k in _norm(s["name"])), None)
        out.append({**s, "state": "exists" if match else "to_build",
                    "esp_segment_id": (match or {}).get("id", ""),
                    "esp_count": (match or {}).get("count", "")})

    return {"ok": True, "tenant": tenant,
            "business_model": base["business_model"],
            "esp_read": live.get("ok", False),
            "esp_note": "" if live.get("ok") else live.get("error", ""),
            "exists": [s for s in out if s["state"] == "exists"],
            "to_build": [s for s in out if s["state"] == "to_build"],
            "segments": out}


def materialize(tenant: str, apply: bool = False) -> dict:
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
    rec = reconcile(tenant)
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
    return {"ok": True, "tenant": tenant, "applied": bool(apply),
            "existing": [{"key": s["key"], "name": s["name"],
                          "esp_segment_id": s["esp_segment_id"]}
                         for s in rec["exists"]],
            "created": done, "would_create": would,
            "unmapped": unmapped, "failed": failed,
            "note": ("" if apply else
                     "dry run — nothing was created; add apply=1 to build "
                     "the would_create list in the live ESP")}
