"""A review that did not run is not a pass, and an ad's pictures learn from it.

Two defects with one cause: the system could not tell "judged and fine" from
"never judged".

  · `creative.assess` returns {"ok": False, "why": ...} with NO `failed` key on
    every failure path — no model, no JSON, nothing to assess. `_integrated`
    asked `"integration" not in (verdict.get("failed") or [])`, which is True
    for an empty list, so a vision outage passed EVERY composited frame and
    `batch` reported "N of N passed review". Not a silent failure — a
    misreported one, which is worse, because the number is the only thing that
    shows before somebody opens twenty pictures.

  · `record_asset_outcome` had exactly one caller: the ESP publish arm, with
    the channel hardcoded to "email". That is CORRECT there — it is the email
    arm. The defect was that the ad path recorded nothing, so
    `proven_assets(channel="meta")` scored every row 0.0 and `creative.pick`'s
    top rung — "it has carried this product before and the result was
    recorded" — had never once fired on the ad path. Which photograph went
    into a Baci frame was decided by insertion order. It could not be fixed
    until a frame knew which variant it was made for (`fb00ed1`).

    python3 scripts/test_review_is_honest.py
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'rh.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["SEO_SITES_JSON"] = "{}"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import creative, db, kb, meta_ads, systems, tenants  # noqa: E402

_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _frame(tenant, output_id, name):
    return creative._file_frame(
        tenant, name.encode() * 40, {"subject": "a long lunch"},
        {"angle": "identity", "lever": "proof", "moment": "before",
         "framing": "product_led"}, "b1", entity_key="", prompt=name,
        review=False, output_id=output_id,
        verdict={"ok": True, "failed": [], "overall": "fine"})


def main() -> int:
    db.init_db()
    tenants.seed()
    systems.create("baci", "ad_creative")

    print("— an outage is not a clean batch —")
    outage = {"ok": False, "why": "the review did not answer in JSON"}
    ck("assess's failure shape carries NO `failed` key, which is the trap",
       "failed" not in outage and not (outage.get("failed") or []),
       "so `\"integration\" not in []` was True and everything passed")
    filed = creative._file_frame(
        "baci", b"PNGPNGPNG", {"subject": "s"},
        {"angle": "identity", "lever": "proof", "moment": "before",
         "framing": "product_led"}, "b0", entity_key="", prompt="p",
        review=True, verdict=outage)
    fr = filed.get("frame") or {}
    ck("a frame whose review did not run is marked unreviewed",
       fr.get("reviewed") is False, str(fr)[:120])
    ck("  and it is NOT marked failed either — three states, not two",
       fr.get("failed") == [], str(fr.get("failed")))
    good = creative._file_frame(
        "baci", b"OTHERBYTES", {"subject": "s"},
        {"angle": "occasion", "lever": "proof", "moment": "before",
         "framing": "context"}, "b0", entity_key="", prompt="p2",
        review=True, verdict={"ok": True, "failed": [], "overall": "fine"})
    ck("a frame the reviewer DID read is marked reviewed",
       (good.get("frame") or {}).get("reviewed") is True, "")

    print("\n— and the gate no longer opens on an outage —")
    import inspect
    src = inspect.getsource(creative._integrated)
    ck("the first-attempt gate tests that the review ran",
       'verdict.get("ok") and "integration" not in' in src, "")
    ck("  and so does the second-plate retry",
       'v2.get("ok") and "integration" not in' in src, "")
    ck("the batch counts a clean frame as reviewed AND unfailed",
       'not f["failed"] and f.get("reviewed")' in inspect.getsource(creative.batch),
       "")
    ck("  and says out loud how many could not be judged",
       "could NOT be reviewed" in inspect.getsource(creative.batch), "")

    print("\n— an ad's result reaches the pictures that ran in it —")
    vid = "var-1"
    _frame("baci", vid, "AAAA")
    _frame("baci", vid, "BBBB")
    with db.SessionLocal() as s:
        row = db.Output(tenant="baci", system_key="ad_creative",
                        format="ad_copy", status="approved", body="the copy")
        s.add(row)
        s.commit()
        oid = row.id
    for a in kb.assets("baci", publishable_only=False):
        if f"output:{vid}" in list(a.tags or []):
            with db.SessionLocal() as s:
                t = s.get(db.KbAsset, a.id)
                t.tags = [x for x in t.tags if x != f"output:{vid}"] + [f"output:{oid}"]
                s.commit()

    meta_ads._cfg = lambda tenant: ({"token": "t", "account": "a"}, "")
    meta_ads._get = lambda cfg, path, params: {"data": [{
        "id": "ad9", "name": "A", "effective_status": "ACTIVE",
        "creative": {"body": "the copy"},
        "insights": {"data": [{"impressions": "9000", "clicks": "90",
                               "spend": "100", "ctr": "1.0", "cpc": "1.1"}]}}]}
    res = meta_ads.match("baci")
    ck("the copy row joined to the live ad", res.get("matched") == 1, str(res)[:110])
    ck("  and BOTH of its frames were scored", res.get("frames_scored") == 2,
       str(res.get("frames_scored")))
    scored = [a for a in kb.assets("baci", publishable_only=False)
              if (a.outcome or {}).get("meta")]
    ck("the outcome is filed under the META channel, not email",
       len(scored) == 2 and all("email" not in (a.outcome or {}) for a in scored),
       str([(a.outcome or {}) for a in scored])[:150])
    # WHAT `proven_assets` ACTUALLY NEEDS. It ranks by
    # `outcome[channel][metric]` — but only over assets that are publishable
    # AND have been used, which is a separate and correct gate. The defect
    # this fixes is the SCORE, not those gates: before, `outcome` had no
    # "meta" key at all, so every ad-channel score was 0.0 no matter how well
    # the frame did, and the ranking degenerated to insertion order.
    scores = [float(((a.outcome or {}).get("meta") or {}).get("ctr", 0))
              for a in scored]
    ck("  so a meta-channel score is a real number now, not 0.0",
       scores and all(s > 0 for s in scores), str(scores))
    ck("  which is the input pick's top rung ranks on",
       "outcome" in inspect.getsource(kb.proven_assets)
       and "channel" in inspect.getsource(kb.proven_assets), "")

    print()
    if _fail:
        print(f"{len(_fail)} FAILED: {_fail}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
