"""The campaign workroom says WHICH state it is in. Nothing rendered it before.

No suite in this repo rendered a campaign workroom at all, which is why the
owner had to find this by using it: four unrelated mechanisms suppress the
Approve control, and all four collapsed into one grey sentence that named none
of them — while prescribing "a clean redraft re-queues one", which is false for
three of the four.

The states, and why each is silent in a different way:
  · the `shadow` rung — the DEFAULT, since `System.autonomy` defaults to it and
    `systems.create` never sets it. Runs and records; sends nothing.
  · the `auto` rung — `_disposition` returns `cleared`, which nothing in the
    codebase consumes, so a campaign stops there too.
  · a WITHDRAWN approval — and two of its causes (a missing CAN-SPAM address,
    ESP personalization) are account data a redraft can never clear.
  · defects recorded on the run.

Run: python3 scripts/test_workroom_email.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'wr.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import (admin_ui, approvals, brand_theme, db, esp, kb,  # noqa: E402
                 skill, skill_pack, systems, tenants, web)

_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


_ALL = {c: True for c in tenants.CAPABILITIES}
tenants.capabilities = lambda k: dict(_ALL) if tenants.get(k) else \
    {c: False for c in tenants.CAPABILITIES}


def _seed(t, *, theme=True):
    kb.ensure_brand(t, t.title())
    kb.set_brand(t, positioning="Italian-designed tableware.", tone="warm")
    kb.add_banned(t, "made in Italy")
    kb.add_audience(t, "core_hostess", "The host", ["mismatched"], ["tablescape"])
    row = systems.find(t, "campaign_email") or systems.create(t, "campaign_email")
    with db.SessionLocal() as s:
        s.get(db.System, row.id).status = "live"
        s.commit()
    if theme:
        brand_theme.approve(t, {"footer.address": "2875 NE 191st St, Aventura FL"})
    return row


def _draft(t):
    r = skill.run("campaign_email", t, segment="reorder_due",
                  audience_key="core_hostess")
    return (r.get("items") or [{}])[0].get("output_id", ""), r


def _page(oid):
    art, kw, ap = web._article_bundle(oid)
    return admin_ui.render_workroom("s3cret", oid, art, kw, ap)


def main() -> int:
    db.init_db()
    tenants.seed()
    esp.provider_for = lambda x: "omnisend"
    esp.personalize = lambda x, h: {"ok": True, "html": h}

    class _M:
        @staticmethod
        def draft_from_html(tenant, *, name, subject, sender_name, html,
                            preheader="", include_segments=None):
            return {"ok": True, "campaign_id": "c1"}
    esp.backend = lambda x: (_M, "")
    skill_pack.draft_campaign = lambda b, seg, goal, craft=None: (
        {"subject": "A note", "preheader": "p", "claim_ids": [],
         "body_html": "<p>Something quiet about the table.</p>",
         "cta_label": "Shop", "cta_url": "https://x/s"}, "model", "")

    print("— the shadow rung: the default, and the silent one —")
    _seed("baci")
    oid, _ = _draft("baci")
    page = _page(oid)
    ck("it names the rung rather than saying nothing",
       "shadow" in page and "Nothing is queued for approval" in page,
       "`autonomy` defaults to shadow and `systems.create` never sets it")
    ck("  and says what to do about it, with the link",
       "approve_all" in page and "system=campaign_email" in page,
       "a fix instruction with no control is design rule 1 broken")
    ck("  and can finally name the platform",
       "omnisend" in page,
       "the recipe is on the artifact even when no approval exists — the page "
       "could not previously say the word")

    print("\n— the auto rung cannot push either, and says so —")
    _row = systems.find("baci", "campaign_email")
    systems.update(_row.id, autonomy="auto")
    ck("auto is named as a stop, not as a send",
       "auto" in _page(oid) and "stops here" in _page(oid),
       "_disposition returns `cleared`, which nothing consumes")

    print("\n— a withdrawn approval prints the reason it recorded —")
    systems.update(_row.id, autonomy="approve_all")
    oid2, r2 = _draft("baci")
    approvals.withdraw(r2.get("run_id") or "",
                       "footer.address — CAN-SPAM requires a physical mailing "
                       "address")
    p2 = _page(oid2)
    ck("the withdrawal reason is on the page, verbatim",
       "CAN-SPAM" in p2, "it was stored on the payload and rendered nowhere")
    ck("  and it says a redraft cannot clear account data",
       "cannot clear that" in p2,
       "'a clean redraft re-queues one' was false for this state")

    print("\n— and the ordinary case still reads as before —")
    oid3, r3 = _draft("baci")
    ck("a queued approval still offers Approve",
       "Approve" in _page(oid3) and "pushes the draft" in _page(oid3),
       "the read-path change must not disturb the working state")

    print("\n" + ("all checks passed" if not _fail
                  else f"{len(_fail)} FAILED:\n  - " + "\n  - ".join(_fail)))
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
