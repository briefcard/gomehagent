"""The visual boards and the copy instructions by channel live on the Brand
tab, and a channel's instruction reaches every draft of that channel — the
drafter as a rule, the ad panel as a judge — and no other channel's.

Owner, 2026-09-07: *"the visual boards live in the review page right now,
but they should live permanently in the 'Brand' tab as this affects all of
the brands creatives. Same for copy instructions across different
channels."*

WHAT WAS TRUE. The boards card rendered on the Pictures page (the per-run
selector on each form was already right). The voice record was one and
brand-wide — tone, do-say, never-say — so an instruction true only of email
had nowhere to go but every draft, or nowhere.

Run: python3 scripts/test_the_brand_tab_owns_the_boards_and_the_channel_rules.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from urllib.parse import unquote

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'brandtab.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["PUBLIC_BASE_URL"] = "https://example.test"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import (ad_craft, admin_ui as ui, bundle as _pkg, db, kb, kb_seed,  # noqa: E402
                 resolve, skill_pack, tenants, web)

KEY = "s3cret"
_fail: list[str] = []
ADS = "Never an exclamation mark. One idea per line. End on the offer, never on a question."
EMAIL = "Open with the reader's situation, not the product. Sign as Gomeh."


def ck(label: str, cond, detail: str = "") -> None:
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    db.init_db()
    tenants.seed()
    kb_seed.seed_all()
    kb.add_board("baci", "Studio", note="on white, hard shadow")
    kb.add_asset("baci", "https://cdn.example/linen.png", rights=kb.OWNED, title="linen",
                 subject=kb.SCENE, origin="human")
    linen = next(a.id for a in kb.assets("baci") if "linen" in (a.url or ""))
    kb.set_board_role(linen, "studio", "look", True)
    kb.set_brand("baci", tone="warm, direct")
    client = TestClient(web.app)

    print("— THE BRAND TAB OWNS THE BOARDS —")
    page = ui.render_brand(KEY, tenant="baci")
    ck("the boards card renders on the Brand tab, each board by name",
       "Visual boards" in page and 'id="board"' in page and 'id="board-studio"' in page)
    # INSPIRATION IS ONE PLACE (owner, 2026-09-12: "I just wanted to
    # centralize inspiration"): the reference emails sit beside the boards,
    # with the swipe form; the designs they are read into are the email
    # system's, on its page.
    # THE REFERENCE EMAILS ARE THE EMAIL SYSTEM'S (owner, 2026-09-12: "emails
    # to begin with are part of the email system"): they live on its Designs
    # page with the recreations; Brand says so and carries neither.
    ck("  the reference emails are not on Brand — it says where they are",
       "Reference emails" not in page and 'action="/admin/email_reference"' not in page
       and "under Designs" in page and "Email structures" not in page)
    ck("  the Brand tab reads in the order an email is made: sound, look, pictures, boards, sources",
       page.index("Identity") < page.index("Look — how their email is dressed")
       < page.index("Pictures — what they have") < page.index("Visual boards")
       < page.index("Sources — their website and landing pages"))
    pics = ui.render_content(KEY, tenant="baci", sub="pictures")
    ck("  and no longer on the Pictures page, which says where the boards are",
       'id="board"' not in pics and "Brand tab" in pics)
    ck("  the form that starts a run keeps the per-run choice",
       'name="boards" multiple' in ui.boards_select("baci") and "Brand tab" in ui.boards_select("baci"))
    ck("  an account with no boards is told so on the run form, pointing at the Brand tab",
       "no boards" in ui.boards_select("coverings") and "Brand tab" in ui.boards_select("coverings"))
    r = client.post("/admin/board_add", params={"key": KEY},
                    data={"tenant": "baci", "name": "Gift guide"}, follow_redirects=False)
    loc = unquote(r.headers.get("location", ""))
    ck("creating a board returns to the Brand tab, at the boards",
       r.status_code == 303 and "tab=brand" in loc and loc.endswith("#board")
       and "gift-guide" in kb.boards("baci"), loc[:160])
    r = client.post("/admin/board_pin", params={"key": KEY},
                    data={"tenant": "baci", "action": "pin_look", "board": "gift-guide",
                          "asset_ids": [linen]}, follow_redirects=False)
    ck("  so does pinning", "tab=brand" in unquote(r.headers.get("location", "")))
    r = client.post("/admin/board_remove", params={"key": KEY},
                    data={"tenant": "baci", "board": "gift-guide"}, follow_redirects=False)
    ck("  and removing", "tab=brand" in unquote(r.headers.get("location", ""))
       and "gift-guide" not in kb.boards("baci"))

    print("\n— COPY INSTRUCTIONS BY CHANNEL, ON THE BRAND TAB —")
    ck("the card offers one field per channel and names the systems that read each",
       'id="channels"' in page
       and all(f'name="channel_{ch}"' in page for ch, _l, _r in kb.CHANNELS)
       and "read by Ad creative" in page and "read by Campaign email" in page
       and "Blog / content" in page, "")
    ck("  the channel table names only systems that exist",
       all(k in __import__("app.systems", fromlist=["CATALOG"]).CATALOG
           for _c, _l, readers in kb.CHANNELS for k in readers))
    r = client.post("/admin/brand_update", params={"key": KEY},
                    data={"tenant": "baci", "channel_ads": ADS, "channel_email": EMAIL},
                    follow_redirects=False)
    loc = unquote(r.headers.get("location", ""))
    v = dict(kb.brand("baci").voice or {})
    ck("saving the card stores each channel's text on the brand's voice and returns to the card",
       r.status_code == 303 and loc.endswith("#channels")
       and (v.get("channels") or {}).get("ads") == ADS
       and (v.get("channels") or {}).get("email") == EMAIL, str(v)[:200])
    ck("  without touching the tone", v.get("tone") == ["warm", "direct"], str(v.get("tone")))
    client.post("/admin/brand_update", params={"key": KEY},
                data={"tenant": "baci", "tone": "warm, direct, unhurried"}, follow_redirects=False)
    v2 = dict(kb.brand("baci").voice or {})
    ck("  and saving the identity form leaves the channels alone",
       (v2.get("channels") or {}).get("ads") == ADS and v2.get("tone") == ["warm", "direct", "unhurried"])
    page2 = ui.render_brand(KEY, tenant="baci")
    ck("  the card shows what is set, and counts it",
       ADS in page2 and "2\n    of 5 set" in page2 or ("2" in page2 and "of 5 set" in page2))

    print("\n— A CHANNEL'S INSTRUCTION REACHES ITS OWN DRAFTS, AND NO OTHER'S —")
    ck("a system maps to its channel, and a system outside the table to none",
       kb.channel_for("ad_creative") == "ads" and kb.channel_for("campaign_email") == "email"
       and kb.channel_for("blog") == "blog" and kb.channel_for("gbp_post") == "gbp"
       and kb.channel_for("reports") == "", "")
    ck("  channel_rules reads by system key or by channel",
       kb.channel_rules("baci", "ad_creative") == ADS and kb.channel_rules("baci", channel="email") == EMAIL
       and kb.channel_rules("baci", "blog") == "" and kb.channel_rules("baci", "reports") == "")
    ads_b = resolve.resolve("baci", system="ad_creative", utterance="the zodiac cups", tier=1)
    email_b = resolve.resolve("baci", system="campaign_email", utterance="the zodiac cups", tier=1)
    blog_b = resolve.resolve("baci", system="blog", utterance="the zodiac cups", tier=1)
    ck("the ad bundle carries the ads instruction, structured and in the rules block every drafter reads",
       ads_b["rules"].get("channel") == ADS and ADS in ads_b["rules"]["block"]
       and "HOW THIS BRAND WRITES FOR ADS" in ads_b["rules"]["block"], str(ads_b.get("error", ""))[:100])
    ck("  the email bundle carries the email one and NOT the ads one",
       email_b["rules"].get("channel") == EMAIL and EMAIL in email_b["rules"]["block"]
       and ADS not in email_b["rules"]["block"])
    ck("  a channel with nothing set adds nothing",
       blog_b["rules"].get("channel") == "" and ADS not in blog_b["rules"]["block"]
       and EMAIL not in blog_b["rules"]["block"])
    ck("  the bundle contract promises the channel",
       "channel" in (_pkg.PARTS["rules"].get("sub") or ()))
    claim = {"claim_id": "c1", "claim": "Twelve zodiac cups, one per sign", "evidence": "", "scope": "brand-wide"}
    drafter = "\n".join(skill_pack.ad_prompt(ads_b, claim, "identity", []))
    ck("the ad drafter's brief carries the ads instruction",
       ADS in drafter and "HOW THIS BRAND WRITES FOR ADS" in drafter)
    panel = "\n".join(ad_craft.panel_prompt(ads_b, []))
    ck("  and so does the panel's — the rule reaches the judge, not only the writer",
       ADS in panel and "HOW THIS BRAND WRITES FOR ADS" in panel)
    ck("  the article and campaign drafters read the same rules block (structural)",
       'bundle["rules"]["block"]' in open(skill_pack.__file__).read()
       and open(skill_pack.__file__).read().count('.get("block"') >= 3)

    print()
    if _fail:
        print(f"{len(_fail)} FAILED:\n  " + "\n  ".join(_fail))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
