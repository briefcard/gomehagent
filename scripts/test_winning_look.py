"""The frames are briefed on what has actually worked for this account.

Owner, 2026-09-04: read the account's winning ads — *"add `creative{image_url,
thumbnail_url}` to the Meta fields, rank by CTR/ROAS"* — into a "winning look"
the brief cites, *"on the owner's click, never unattended."*

`meta_ads.live_ads` returned copy and insights and NO creative image URL at
all, so nothing in this codebase had ever seen what a winning ad looked like.
Every generated frame was therefore the image model's taste, on an account
whose own best creative was sitting in Meta unread.

What must hold, each asserted against the thing itself:

  · the image URLs are ASKED FOR — the field list is checked, not assumed;
  · ranking is by ROAS when the account reports purchase values and by CTR
    when it does not, and a high rate on a handful of impressions is excluded
    rather than promoted;
  · what is stored is a DESCRIPTION, never the pictures, and it reaches the
    ad-frame brief;
  · an account that has never been read SAYS so on the brief's `thin` list
    and on the card;
  · nothing calls it on a schedule — the only caller is the button.

    python3 scripts/test_winning_look.py
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'wl.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["SEO_SITES_JSON"] = "{}"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import creative, db, llm, meta_ads, systems, tenants, web  # noqa: E402

KEY = "s3cret"
_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


ASKED: dict = {}


def _ad(i, *, ctr, impressions, spend=100.0, value=None, image=True):
    m = {"impressions": str(impressions), "clicks": "10", "spend": str(spend),
         "ctr": str(ctr), "cpc": "1"}
    if value is not None:
        m["action_values"] = [{"action_type": "omni_purchase",
                               "value": str(value)}]
    return {"id": f"ad{i}", "name": f"Ad {i}", "effective_status": "ACTIVE",
            "creative": {"body": f"Line {i}",
                         **({"image_url": f"https://img/{i}.jpg",
                             "thumbnail_url": f"https://t/{i}.jpg"} if image else {})},
            "insights": {"data": [m]}}


def _stub_meta(ads):
    meta_ads._cfg = lambda tenant: ({"token": "t", "account": "act_1"}, "")

    def _get(cfg, path, params):
        ASKED["fields"] = params.get("fields", "")
        return {"data": list(ads)}
    meta_ads._get = _get


def main() -> int:
    db.init_db()
    tenants.seed()
    systems.create("baci", "ad_creative")

    print("— the picture is asked for, which it never was —")
    _stub_meta([_ad(1, ctr=2.0, impressions=5000)])
    meta_ads.live_ads("baci")
    ck("the ads query asks Meta for the creative's image",
       "image_url" in ASKED["fields"] and "thumbnail_url" in ASKED["fields"],
       ASKED["fields"][:120])
    ck("  and for what the purchases were worth, not only their count",
       "action_values" in ASKED["fields"] and "action_values" in meta_ads.FIELDS)
    got = meta_ads.live_ads("baci")
    ck("  and carries them back on the row",
       got["ads"][0]["image_url"] == "https://img/1.jpg"
       and got["ads"][0]["thumbnail_url"] == "https://t/1.jpg", str(got["ads"][0])[:120])

    print("\n— ranked by what sold, when the account says what sold —")
    _stub_meta([_ad(1, ctr=9.0, impressions=5000, spend=100, value=100),
                _ad(2, ctr=1.0, impressions=5000, spend=100, value=900),
                _ad(3, ctr=5.0, impressions=5000, spend=100, value=200)])
    w = meta_ads.winners("baci", top=3)
    ck("ROAS wins over click rate where both exist",
       w["ok"] and w["ranked_by"] == "roas"
       and [a["ad_id"] for a in w["ads"]] == ["ad2", "ad3", "ad1"],
       str([(a["ad_id"], a["roas"], a["ctr"]) for a in w["ads"]]))
    _stub_meta([_ad(1, ctr=9.0, impressions=5000),
                _ad(2, ctr=1.0, impressions=5000)])
    w = meta_ads.winners("baci", top=2)
    ck("  and CTR is used when no purchase values are reported",
       w["ranked_by"] == "ctr" and w["ads"][0]["ad_id"] == "ad1",
       str([(a["ad_id"], a["ctr"]) for a in w["ads"]]))

    print("\n— a big rate on a handful of impressions is not a winner —")
    _stub_meta([_ad(1, ctr=40.0, impressions=40),
                _ad(2, ctr=3.0, impressions=9000)])
    w = meta_ads.winners("baci", top=2)
    ck("the 40-impression ad is excluded, not ranked first",
       [a["ad_id"] for a in w["ads"]] == ["ad2"],
       str([(a["ad_id"], a["impressions"], a["ctr"]) for a in w["ads"]]))
    _stub_meta([_ad(1, ctr=5.0, impressions=9000, image=False)])
    w = meta_ads.winners("baci")
    ck("an ad with no picture cannot teach a look, and is refused by name",
       not w["ok"] and "picture" in w["why"], w["why"])

    print("\n— what is stored is a DESCRIPTION, never the pictures —")
    _stub_meta([_ad(1, ctr=9.0, impressions=5000, value=900),
                _ad(2, ctr=3.0, impressions=5000, value=100)])
    fetched: list = []
    creative._fetch = lambda url: (fetched.append(url) or b"JPEGBYTES")
    seen: list = []

    class _Reply:
        ok, text, degraded, error = True, "Hard side light, low camera, warm linen.", "", ""

    llm.ask = lambda purpose, blocks, **k: (seen.append(blocks) or _Reply())
    out = creative.learn_winning_look("baci", top=2)
    ck("it reads the top ads' images", out["ok"] and len(fetched) == 2,
       str(fetched))
    ck("  and asks about the pictures, not the words",
       any(b.get("type") == "image" for b in seen[0])
       and "in common" in seen[0][-1]["text"]
       and "nothing about the words" in seen[0][-1]["text"], "")
    stored = systems.winning_look("baci")
    ck("the description is stored on the system row, with its provenance",
       stored["look"].startswith("Hard side light")
       and stored["ranked_by"] == "roas" and len(stored["from"]) == 2
       and stored["read_at"], str(stored)[:140])
    ck("  and the pictures are NOT stored",
       "JPEGBYTES" not in str(stored) and "img/1.jpg" not in str(stored),
       "a generator handed a finished ad reproduces it")

    print("\n— and the brief cites it —")
    brief = creative.brief_for("baci", fmt="ad_frame", positioning="p")
    ck("an ad frame is briefed on what worked",
       "Hard side light" in brief["prompt"]
       and "WHAT HAS WORKED FOR THIS BRAND" in brief["prompt"], "")
    ck("  told to match the qualities and NOT to reproduce one",
       "Do NOT reproduce" in brief["prompt"], "")
    ck("  and the ranking is named, so the owner can judge the source",
       "ranked by roas" in brief["prompt"], "")
    ck("  it is no longer listed as a gap",
       not any("best-performing" in t for t in brief["thin"]), str(brief["thin"]))

    print("\n— an account nobody has read SAYS so —")
    systems.create("eien", "ad_creative")
    b2 = creative.brief_for("eien", fmt="ad_frame", positioning="p")
    ck("the gap is named on the brief",
       any("best-performing" in t for t in b2["thin"]), str(b2["thin"]))
    ck("  and no winning-look text is invented",
       "WHAT HAS WORKED" not in b2["prompt"])
    b3 = creative.brief_for("baci", fmt="email_hero")
    ck("a non-ad format is not nagged about ad creative",
       not any("best-performing" in t for t in b3["thin"]), str(b3["thin"]))

    print("\n— the card states it, with the one control that costs money —")
    c = TestClient(web.app)
    page = c.get(f"/admin/ui?key={KEY}&tab=content&sub=pictures&tenant=baci").text
    ck("the Pictures room shows the look on file",
       'id="winning"' in page and "Hard side light" in page
       and "ranked by roas" in page)
    ck("  with the control to read them again",
       'action="/admin/ad_winning_look"' in page and "Read them again" in page)
    empty = c.get(f"/admin/ui?key={KEY}&tab=content&sub=pictures&tenant=eien").text
    ck("an unread account is told what it is missing, and what it costs",
       "never on a schedule" in empty
       and "Read this account" in empty, "")
    r = c.post("/admin/ad_winning_look", data={"key": KEY, "tenant": "baci"},
               follow_redirects=False)
    ck("the button reads them and says what it found",
       r.status_code == 303 and "Read%202" in r.headers.get("location", ""),
       r.headers.get("location", ""))
    meta_ads._cfg = lambda tenant: ({}, "no Meta connection on this account")
    r = c.post("/admin/ad_winning_look", data={"key": KEY, "tenant": "baci"},
               follow_redirects=False)
    ck("  and a refusal is read where the button was, by name",
       "no%20Meta%20connection" in r.headers.get("location", ""),
       r.headers.get("location", ""))

    print("\n— nothing calls it unattended —")
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    # A CALL, not a mention: `meta_ads.winners` names this function in its
    # own docstring to say who its caller is, and counting that as a caller
    # is the "grep matched the comment documenting the absence" smell.
    callers = [f.name for f in (root / "app").glob("*.py")
               if "learn_winning_look(" in f.read_text()
               and f.name not in ("creative.py", "web.py")]
    ck("the only callers are the module itself and the route",
       not callers, str(callers))
    ck("  and the worker schedules nothing for it",
       "learn_winning_look" not in (root / "app" / "worker.py").read_text(),
       "recurring spend on a client's quota is the owner's call")

    print()
    if _fail:
        print(f"{len(_fail)} FAILED: {_fail}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
