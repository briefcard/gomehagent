"""The ledger can say what went to whom — Phase 2.1 of INITIATIVE-moments.

Every column this suite covers already existed on `Output`, and for a campaign
email three of them were never written. So the table that holds a record of
every send could not answer the first question anybody asks of it: what have we
already pushed at these people, about which products, and how recently. It came
back empty in the way that looks like "nothing was sent" rather than "nobody
wrote it down" — and any strategy built on it would have been built on a blank.

What is pinned here:

  1. A CAMPAIGN ROW NAMES ITS SUBJECT AND ITS LIST — `entity_key` is the
     product somebody actually chose, `audience_key` is the segment,
     `situation` is the intent. `ad_copy` has passed these since it was
     written; this path never did.
  2. `media_ids` IS THE PHOTOGRAPH THAT WENT OUT, not the one that was picked.
     A letter drops the hero block, and crediting an asset nobody received
     would corrupt the only feedback signal the creative library has.
  3. `destination` IS AN OUTCOME. It used to be written ~90 lines before the
     ESP call that may refuse — so it said `esp:omnisend` whether or not
     anything reached Omnisend. Now it names a campaign somebody can open, or
     says plainly that nothing was created. And it is still not a SEND: a
     draft in the platform is not an email a customer got.
  4. `sends_to` ANSWERS THE QUESTION — for one list over a window: which
     intents, which products, which claims, which angles, at what spacing.
  5. A REJECTED DRAFT IS NOT A SEND. `repaired` marks an attempt the validator
     threw away and a later one replaced. It keeps `angle` and `format` and
     loses `theme` and `shape`, so it read as a real send with no intent —
     diluting the four-row window the drafter varies against, and inflating
     any count of what a list has been sent.

Run: python3 scripts/test_strategy_ledger.py
"""
import datetime as dt
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'sl.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import (brand_theme, db, esp, kb, ledger, skill,  # noqa: E402
                 skill_pack, systems, tenants)

_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


_ALL = {c: True for c in tenants.CAPABILITIES}
tenants.capabilities = lambda key: dict(_ALL) if tenants.get(key) else \
    {c: False for c in tenants.CAPABILITIES}

_drafted = []
_esp_ok = {"v": True}


def _fake_esp():
    esp.provider_for = lambda t: "omnisend"
    esp.personalize = lambda t, html: {"ok": True,
                                       "html": html.replace("{{FIRST_NAME}}", "‹NAME›")}

    class _Mod:
        @staticmethod
        def draft_from_html(tenant, *, name, subject, sender_name, html,
                            preheader="", include_segments=None):
            _drafted.append({"subject": subject})
            if not _esp_ok["v"]:
                return {"ok": False, "error": "list is locked", "stage": "campaign"}
            return {"ok": True, "campaign_id": "camp_77", "stage": "done"}
    esp.backend = lambda t: (_Mod, "")


def _seed_live(tenant):
    kb.ensure_brand(tenant, tenant.title())
    kb.set_brand(tenant, positioning="Italian-designed tableware for the table.",
                 tone="direct, warm")
    # Without this the validator has nothing to check against and refuses to
    # let anything out — every row would come back `blocked` and the assertions
    # below would be about a fixture that never produced a send.
    kb.add_banned(tenant, "made in Italy")
    kb.add_situation(tenant, "quality", patterns=[["quality"]],
                     description="Is it any good?", origin="seed")
    kb.add_claim(tenant, "Designed in Milan and used in leading hotels.",
                 "brand brief", ["quality"], origin="human", status="active")
    row = systems.find(tenant, "campaign_email") or systems.create(tenant, "campaign_email")
    with db.SessionLocal() as s:
        r = s.get(db.System, row.id)
        r.status = "live"
        s.commit()


def _rows_for(run_id):
    with db.SessionLocal() as s:
        return (s.query(db.Output).filter(db.Output.run_id == run_id)
                .order_by(db.Output.created_at.asc()).all())


def _designed(cited, with_hero=True):
    """A drafter that returns a designed email — hero, product, CTA."""
    def _d(bundle, seg, goal, craft=None):
        claims = bundle.get("claims") or []
        cid = claims[0]["claim_id"] if claims else ""
        blocks = ([{"type": "hero"}] if with_hero else []) + [
            {"type": "heading", "text": "Back on the shelf", "level": 1},
            {"type": "text", "html": "<p>Designed in Milan.</p>"},
            {"type": "products", "keys": ["aqua-pitcher"]},
            {"type": "cta", "label": "Reorder", "url": "https://x/reorder"}]
        return ({"subject": "Back on the shelf", "preheader": "one tap",
                 "blocks": blocks, "claim_ids": [cid] if cid and cited else [],
                 "cta_label": "Reorder", "cta_url": "https://x/reorder"},
                "model", "")
    return _d


def main():
    db.init_db()
    tenants.seed()
    _seed_live("baci")
    _fake_esp()
    ok = brand_theme.approve("baci", {"footer.address":
                                      "2875 NE 191st St, Aventura, FL 33180"})
    assert ok.get("ok") and ok["gaps"] == [], ok

    kb.add_entity("baci", "product", "aqua-pitcher", "Aqua pitcher",
                  description="Acrylic, shatterproof.",
                  attributes={"image": "https://cdn/aqua.jpg",
                              "availability": "in stock"})
    kb.add_asset("baci", "https://cdn.example/aqua-hero.jpg", rights=kb.OWNED,
                 title="Aqua pitcher on linen", entity_key="aqua-pitcher",
                 origin="human")

    # ---------------------------------------------------------------- 1 ----
    print("— a campaign row names its subject and its list —")
    skill_pack.draft_campaign = _designed(cited=True)
    r = skill.run("campaign_email", "baci", segment="reorder_due",
                  entity_key="aqua-pitcher")
    ck("the skill produced an email", r["status"] == "produced", str(r.get("status")))
    item = (r.get("items") or [{}])[0]
    rows = [o for o in _rows_for(r["run_id"]) if o.status not in ledger.NOT_A_SEND]
    ck("exactly one surviving row was filed", len(rows) == 1, str(len(rows)))
    row = rows[0]

    ck("entity_key is the product somebody CHOSE",
       row.entity_key == "aqua-pitcher", repr(row.entity_key))
    ck("audience_key is the segment the plan named",
       row.audience_key == "reorder_due", repr(row.audience_key))
    ck("situation carries the intent, and matches what the item reports",
       bool(row.situation) and row.situation == item.get("meta", {}).get("intent"),
       f"row={row.situation!r} item={item.get('meta', {}).get('intent')!r}")
    ck("the claim it drew on is still recorded",
       bool(row.claim_ids), str(row.claim_ids))
    ck("the shape it was built from is still recorded",
       "hero" in (row.shape or []), str(row.shape))

    # ---------------------------------------------------------------- 2 ----
    print("\n— media_ids is the photograph that WENT OUT —")
    ck("the hero the email carried is credited on the row",
       len(row.media_ids or []) == 1, str(row.media_ids))
    _asset_id = (row.media_ids or [""])[0]
    ck("and it is a real, publishable asset — publish would accept it",
       kb.may_publish(_asset_id)[0] if _asset_id else False,
       "" if _asset_id else "no asset id filed")

    # The drafter omitting a hero proves nothing — the assembler puts one back
    # when the library has one. The state that really produces a heroless email
    # is a library with nothing publishable in it, so that is the one tested:
    # the picture is withdrawn the way an owner withdraws one.
    kb.review_asset(_asset_id, approve=False)
    ck("the withdrawn picture is genuinely unreachable now",
       not kb.may_publish(_asset_id)[0], kb.may_publish(_asset_id)[1])
    skill_pack.draft_campaign = _designed(cited=True, with_hero=False)
    r2 = skill.run("campaign_email", "baci", segment="reorder_due",
                   entity_key="aqua-pitcher")
    row2 = [o for o in _rows_for(r2["run_id"]) if o.status not in ledger.NOT_A_SEND][0]
    # The email still shows a picture — the product's own photograph is the
    # fallback hero — but that is not a LIBRARY asset, so there is nothing to
    # credit and nothing `publish` could check the rights of. An empty list
    # here is the true answer, not a missed write.
    ck("a hero that came from the product, not the library, credits nothing",
       (row2.media_ids or []) == [] and "hero" in (row2.shape or []),
       f"media={row2.media_ids} shape={row2.shape}")
    # Retiring is not reversible by re-approving, so the library gets a fresh
    # picture — Part 5 below has to compare a row that DOES carry a credit
    # against one that does not, and two empty lists would prove nothing.
    kb.add_asset("baci", "https://cdn.example/aqua-hero-2.jpg", rights=kb.OWNED,
                 title="Aqua pitcher, second look", entity_key="aqua-pitcher",
                 origin="human")

    # ---------------------------------------------------------------- 3 ----
    # RETARGETED (UI overhaul 3.3, owner 2026-08-27): review-before-push.
    # Emit records HELD-FOR-REVIEW — nothing reaches the ESP before the
    # approval-time push — and the campaign id lands on the row only when
    # the push actually creates one. A push the ESP refuses leaves the row
    # honestly held, never faking a landing.
    print("\n— destination is an outcome, not an intention —")
    ck("an emitted campaign is HELD, not pre-drafted into the ESP",
       row.destination == "esp:omnisend:held-for-review",
       repr(row.destination))
    got_p = skill_pack.push_campaign_to_esp("baci", row.id)
    row_p = [o for o in _rows_for(row.run_id)
             if o.status not in ledger.NOT_A_SEND][0]
    ck("…and the push names the campaign somebody can open",
       got_p.get("ok") is True
       and row_p.destination.startswith("esp:omnisend:campaign/"),
       f"{got_p!r} · {row_p.destination!r}")
    ck("and it is NOT recorded as sent — a draft is not a send",
       row_p.status != "published" and row_p.published_at is None,
       str(row_p.status))

    _esp_ok["v"] = False
    skill_pack.draft_campaign = _designed(cited=True)
    r3 = skill.run("campaign_email", "baci", segment="reorder_due",
                   entity_key="aqua-pitcher")
    row3 = [o for o in _rows_for(r3["run_id"]) if o.status not in ledger.NOT_A_SEND][0]
    got_r = skill_pack.push_campaign_to_esp("baci", row3.id)
    row3b = [o for o in _rows_for(r3["run_id"])
             if o.status not in ledger.NOT_A_SEND][0]
    ck("an ESP refusal is recorded as one, not as a landing",
       got_r.get("ok") is not True
       and row3b.destination == "esp:omnisend:held-for-review",
       f"{got_r.get('error', '')[:60]!r} · {row3b.destination!r}")
    _esp_ok["v"] = True

    # ---------------------------------------------------------------- 4 ----
    print("\n— sends_to answers the question the ledger was built for —")
    now = db.utcnow()

    def _file(days_ago, *, status="cleared", intent="give", entity="",
              angle="win_back", audience="win_back", claims=(), theme_fmt="letter"):
        o = ledger.record("baci", "campaign_email", situation=intent,
                          entity_key=entity, audience_key=audience,
                          claim_ids=list(claims), angle=angle,
                          format="campaign_email", status=status,
                          theme=f"{intent}|{theme_fmt}", body="x")
        with db.SessionLocal() as s:
            r = s.get(db.Output, o.id)
            r.created_at = now - dt.timedelta(days=days_ago)
            s.commit()
        return o.id

    _file(40, intent="story", entity="aqua-pitcher", claims=["c1"])
    _file(26, intent="education", entity="", claims=["c2"])
    _file(12, intent="offer", entity="aqua-pitcher", claims=["c1", "c3"])
    # The fixture HAS the things being excluded — an absence check against an
    # empty table passes for the wrong reason.
    _file(20, status="repaired", intent="", entity="aqua-pitcher")
    _file(19, status="superseded", intent="")
    _file(18, status="blocked", intent="offer")
    # A row from before `audience_key` was ever written: segment on `angle`
    # only. History must not begin at the fix.
    _file(60, intent="proof", entity="", audience="", angle="win_back",
          claims=["c9"])

    got = ledger.sends_to("baci", "win_back", days=90)
    ck("every real send is returned, and only those",
       len(got) == 4, f"{len(got)} rows: {[g['intent'] for g in got]}")
    ck("the legacy row matched on `angle` alone is included",
       any(g["intent"] == "proof" for g in got),
       str([g["intent"] for g in got]))
    ck("a repaired attempt is not counted as a send",
       all(g["status"] != "repaired" for g in got))
    ck("nor a superseded one, nor a blocked one",
       all(g["status"] not in ("superseded", "blocked") for g in got))

    ck("which intents — in order, oldest first",
       [g["intent"] for g in got] == ["proof", "story", "education", "offer"],
       str([g["intent"] for g in got]))
    ck("which products",
       [g["entity_key"] for g in got] == ["", "aqua-pitcher", "", "aqua-pitcher"],
       str([g["entity_key"] for g in got]))
    ck("which claims", sorted({c for g in got for c in g["claim_ids"]})
       == ["c1", "c2", "c3", "c9"],
       str(sorted({c for g in got for c in g["claim_ids"]})))
    ck("which angles", {g["angle"] for g in got} == {"win_back"})
    ck("at what spacing — the gap before the first is unknown, not zero",
       got[0]["gap_days"] is None, str(got[0]["gap_days"]))
    ck("and every later gap is measured from the one before it",
       [g["gap_days"] for g in got[1:]] == [20.0, 14.0, 14.0],
       str([g["gap_days"] for g in got[1:]]))

    ck("a window shorter than the history cuts it off",
       len(ledger.sends_to("baci", "win_back", days=30)) == 2,
       str(len(ledger.sends_to("baci", "win_back", days=30))))
    ck("a list nothing was sent to comes back empty",
       ledger.sends_to("baci", "never_used", days=90) == [])

    # ---------------------------------------------------------------- 5 ----
    print("\n— the indexes those queries need actually get created —")
    from sqlalchemy import inspect as sa_inspect, text
    _want = {"ix_outputs_audience_key", "ix_outputs_theme",
             "ix_outputs_angle", "ix_outputs_format"}
    with db.engine.begin() as c:
        for name in sorted(_want):
            c.execute(text(f'DROP INDEX IF EXISTS "{name}"'))
    have = {i["name"] for i in sa_inspect(db.engine).get_indexes("outputs")}
    # The fixture has to be missing them, or "they exist" passes for the wrong
    # reason — `create_all` made them when the table was new.
    ck("the table really is missing them before the migration runs",
       not (_want & have), str(sorted(_want & have)))
    # Through `_auto_migrate`, which is what startup actually calls — a
    # migration that works and is never reached is the same as no migration,
    # and that is a mistake this repo has already made once with a KB rule
    # nothing was wired to read.
    db._auto_migrate()
    have = {i["name"] for i in sa_inspect(db.engine).get_indexes("outputs")}
    ck("an index declared on an EXISTING table is created, not just declared",
       _want <= have, str(sorted(_want - have)))
    db._auto_migrate()        # a second pass must be free, not an error
    ck("running it again is a no-op rather than a failure",
       _want <= {i["name"] for i in sa_inspect(db.engine).get_indexes("outputs")})

    print("\n— a rejected draft never enters the anti-repeat window —")
    calls = {"n": 0}

    def _first_banned(bundle, seg, goal, craft=None):
        calls["n"] += 1
        bad = calls["n"] == 1
        return ({"subject": "A clean subject line", "preheader": "second line",
                 "blocks": [{"type": "text", "html":
                             "<p>Our tableware is made in Italy.</p>" if bad
                             else "<p>Designed in Milan.</p>"},
                            {"type": "cta", "label": "Shop", "url": "https://x/s"}],
                 "claim_ids": [], "cta_label": "Shop", "cta_url": "https://x/s"},
                "model", "")

    skill_pack.draft_campaign = _first_banned
    r4 = skill.run("campaign_email", "baci", segment="lapsed_60_90")
    it = (r4.get("items") or [{}])[0]
    all4 = _rows_for(r4["run_id"])
    ck("the run really did repair — the fixture has a repaired row in it",
       it.get("repairs") == 1 and any(o.status == "repaired" for o in all4),
       f"repairs={it.get('repairs')} statuses={[o.status for o in all4]}")

    hist = skill_pack._recent_sends("baci", "lapsed_60_90")
    ck("the window shows the send, not the draft that was thrown away",
       len(hist) == 1, f"{len(hist)} rows: {[h['intent'] for h in hist]}")
    ck("and the one it shows has its intent intact",
       bool(hist and hist[0]["intent"]), str(hist[:1]))

    surviving = [o for o in all4 if o.status not in ledger.NOT_A_SEND]
    ck("only the surviving row was filed as a send",
       len(surviving) == 1, str([o.status for o in all4]))
    ck("the surviving row DOES credit the photograph it carried",
       len(surviving[0].media_ids or []) == 1, str(surviving[0].media_ids))
    ck("and the attempt it replaced credits nothing — one email, one credit",
       all((o.media_ids or []) == [] for o in all4 if o.status == "repaired"),
       str([(o.status, o.media_ids) for o in all4]))

    print("\n" + ("FAILURES: " + ", ".join(_fail) if _fail else "all good"))
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
