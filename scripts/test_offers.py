"""Offers: harvested from real sends, proposed, and unusable until approved.

The offer is the one thing in a send a generator must never invent — a
discount nobody authorised, over the client's own sending domain, at list
scale. So it is a field a person fills. On an existing brand that field is
blank on day one and the history that would fill it is sitting in the
archive, which is what `offers.harvest` reads.

What this pins: the extraction is conservative, the proposals are NOT usable,
a proposed offer still reaches the draft but HOLDS it, approving one releases
it, and the email is only held when the copy actually states the offer.

Run: python3 scripts/test_offers.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'of.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import (brand_theme, db, esp, kb, ledger, offers,  # noqa: E402
                 skill, skill_pack, systems, tenants)
from app import provenance as prov  # noqa: E402

_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


_ALL = {c: True for c in tenants.CAPABILITIES}
tenants.capabilities = lambda k: dict(_ALL) if tenants.get(k) else \
    {c: False for c in tenants.CAPABILITIES}


def main() -> int:
    db.init_db()
    tenants.seed()
    t = "baci"
    kb.ensure_brand(t, "Baci")
    kb.set_brand(t, positioning="Italian-designed tableware.", tone="warm")
    kb.add_banned(t, "made in Italy")
    row = systems.find(t, "campaign_email") or systems.create(t, "campaign_email")
    with db.SessionLocal() as s:
        s.get(db.System, row.id).status = "live"
        s.commit()
    brand_theme.approve(t, {"footer.address": "2875 NE 191st St, Aventura, FL"})
    esp.provider_for = lambda x: "omnisend"
    esp.personalize = lambda x, html: {"ok": True, "html": html}

    print("— the extraction is conservative —")
    body = ("Your table, refreshed.\n"
            "20% off everything in the Aqua range until Sunday.\n"
            "Is this a question about 15% off?\n"
            "We think you will love the new collection.\n"
            "Free shipping on orders over $50.")
    got = offers.phrases(body)
    ck("a stated discount is found", any("20% off" in p for p in got), str(got))
    ck("free shipping is found", any("Free shipping" in p for p in got))
    ck("a QUESTION about a discount is not an offer",
       not any("15% off" in p for p in got),
       "a drafter asking a rhetorical question has not made an offer")
    ck("ordinary prose is not an offer",
       not any("love the new collection" in p for p in got))
    ck("the whole SENTENCE is kept, not the fragment",
       any(p.startswith("20% off everything") for p in got),
       "a reviewer approving '20% off' is approving something they cannot check")

    print("\n— the bootstrap reads real sends and REPORTS before it writes —")
    for i in range(2):
        ledger.record(t, "campaign_email", format="campaign_email",
                      status="sent", body=body, audience_key="reorder_due")
    dry = offers.harvest(t)
    ck("a dry run finds the offers", len(dry["proposals"]) >= 2,
       f"{len(dry['proposals'])} from {dry['sends_read']} send(s)")
    ck("  and writes nothing", dry["filed"] == 0 and not known_keys(t),
       "a sweep that files rows the first time it is pressed is a surprise")
    live = offers.harvest(t, apply=True)
    ck("applying files them", live["filed"] >= 2, str(live["filed"]))
    ck("  deduped across sends — the same line twice is one offer",
       len(known_keys(t)) == len(dry["proposals"]), str(known_keys(t)))
    ck("  a second sweep proposes nothing new",
       offers.harvest(t, apply=True)["filed"] == 0)

    print("\n— a harvested offer is NOT usable —")
    ck("proposals are hidden from every generator",
       not offers.known(t), "kb.entities() excludes review=proposed")
    ck("  but visible to a reviewer", len(offers.known(t, True)) >= 2)
    app = offers.applicable(t, segment="reorder_due")
    ck("applicable finds one and says it cannot be used",
       app["ok"] and not app["usable"], str(app)[:90])

    print("\n— a proposed offer reaches the draft and HOLDS it —")
    skill_pack.draft_campaign = lambda bundle, seg, goal, craft=None: (
        {"subject": "A note", "preheader": "p", "claim_ids": [],
         "body_html": f"<p>{bundle.get('offer') or 'nothing'}</p>",
         "cta_label": "Shop", "cta_url": "https://x/s"}, "model", "")
    r = skill.run("campaign_email", t, segment="reorder_due", intent="offer")
    ck("the derived offer reached the copy",
       "20% off" in ((r.get("items") or [{}])[0].get("meta", {}).get("html", "")
                     + str(r.get("notes"))),
       str(r.get("notes"))[-160:])
    ck("  the run says it is not publishable",
       any("cannot be published" in n for n in r.get("notes") or []),
       str([n for n in r.get("notes") or [] if "offer" in n])[:160])
    defects = (r.get("detail") or {}).get("defects") or []
    ck("  and it is held as a defect, by name",
       any("proposed and not approved" in d for d in defects), str(defects)[:140])
    ck("  which withholds it from the ESP entirely",
       "withheld" in (ledger.recent(t, "campaign_email", 1)[0].destination or ""),
       str(ledger.recent(t, "campaign_email", 1)[0].destination))

    print("\n— an email that does not STATE the offer is not held over it —")
    # RUN WHILE ONLY PROPOSALS EXIST. Once an offer is approved `applicable`
    # prefers it, `derived_offer` is never set, and this check would pass for
    # a reason that has nothing to do with the guard it claims to cover — the
    # sabotage caught exactly that and reported MISSED.
    _prev = skill_pack.draft_campaign
    skill_pack.draft_campaign = lambda bundle, seg, goal, craft=None: (
        {"subject": "A story", "preheader": "p", "claim_ids": [],
         "body_html": "<p>A quiet note about the table.</p>",
         "cta_label": "Shop", "cta_url": "https://x/s"}, "model", "")
    r3 = skill.run("campaign_email", t, segment="reorder_due", intent="story")
    d3 = (r3.get("detail") or {}).get("defects") or []
    ck("a proposed offer WAS derived for it",
       any("PROPOSED offer was used" in n for n in r3.get("notes") or []),
       "otherwise this check proves nothing")
    ck("  but a send that never mentions it ships free of the offer block",
       not any("not approved" in d for d in d3),
       "read from the WORDS, not assumed from the parameter")
    skill_pack.draft_campaign = _prev

    print("\n— approving the offer releases the send —")
    prop = offers.known(t, True)[0]
    with db.SessionLocal() as s:
        eid = s.query(db.KbEntity).filter(
            db.KbEntity.tenant == t,
            db.KbEntity.key == prop.key).first().id
    said = kb.review_entity(eid, approve=True)
    ck("a proposed entity can actually be approved", "Approved" in said, said[:80])
    ck("  and is then usable", bool(offers.known(t)), str(len(offers.known(t))))
    r2 = skill.run("campaign_email", t, segment="reorder_due", intent="offer")
    d2 = (r2.get("detail") or {}).get("defects") or []
    ck("the same send is no longer held over the offer",
       not any("not approved" in d for d in d2), str(d2)[:140])

    print("\n" + ("all checks passed" if not _fail
                  else f"{len(_fail)} FAILED:\n  - " + "\n  - ".join(_fail)))
    return 1 if _fail else 0


def known_keys(t):
    return sorted(e.key for e in offers.known(t, include_proposed=True))


if __name__ == "__main__":
    sys.exit(main())
