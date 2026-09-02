"""On `auto`, the blog publishes itself — and only the blog.

Owner, 2026-09-02: *"Yes Cleared should push."*

Before this, promoting a system to `auto` did not automate anything: it removed
the approval and put nothing in its place, which is strictly worse than staying
on shadow. `_disposition` returned `cleared`, `emit` queued an approval only on
`needs_approval`, and nothing branched on the difference.

THE SAME DECISION A PERSON MAKES, THROUGH THE SAME EXECUTOR. It would have been
shorter to call the CMS backend from the run; it would also have been a SECOND
publishing path, and this codebase has paid for a second path of anything every
time. `approvals.ship_unattended` goes through `apply_decision`, so the
approval row exists, `_execute` runs the same arm, the write-back fires, and
withdraw/supersede keep working.

AND IT IS MARKED. The run's decision reads `auto`, not `approved`, so "how many
pages went live with nobody looking" has an answer. Two records that look
identical are indistinguishable exactly when somebody needs to tell them apart.

PER SYSTEM, NEVER ONE SWITCH. "Push" is a different irreversible act in each:

  blog            publishes to the CMS. Revisable — the refresh lane exists to
                  do precisely that.
  campaign_email  OFF, by decision. Owner, 2026-08-31: *"Leave it human, in
                  the ESP."* A send cannot be recalled or refreshed.
  ad_creative     OFF, because there is nothing to turn on: no ad-platform
                  write is wired. Listing it True would promise a spend no
                  code performs.

Run: python3 scripts/test_auto_ships.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'as.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["SHOPIFY_STORES_JSON"] = (
    '{"baci": {"domain": "baci.myshopify.com", "token": "shpat_test"}}')
os.environ["SEO_SITES_JSON"] = (
    '{"baci": {"key": "baci", "domain": "bacimilanousa.com",'
    ' "platform": "shopify", "creds_key": "baci"}}')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import (approvals, db, kb, seo_tools, shopify_seo, skill,  # noqa: E402
                 skill_pack, systems, tenants)

_fail = []
approvals.notify_pending = lambda *a, **k: None
seo_tools._link_grounding = lambda *a, **k: None


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _setup(rung):
    kb.ensure_brand("baci", "Baci")
    row = systems.find("baci", "blog") or systems.create("baci", "blog")
    with db.SessionLocal() as s:
        r = s.get(db.System, row.id)
        r.status, r.autonomy = "live", rung
        b = s.get(db.KbBrand, "baci")
        b.positioning = "Mid-century tableware."
        b.voice = {"tone": ["plain"]}
        b.banned_claims = ["handmade"]
        t = s.get(db.Tenant, "baci")
        t.cms = {"platform": "shopify", "blog_id": "99"}
        s.commit()


def _seo(tenant="baci"):
    with db.SessionLocal() as s:
        return [a for a in s.query(db.Approval)
                .filter(db.Approval.tenant == tenant).all()
                if str(a.kind or "").startswith("seo")]


def main() -> int:
    db.init_db()
    tenants.seed()
    kb.add_claim("baci", "Baci jugs are dishwasher safe.", "lab report", [])
    skill_pack._draft_article_live = lambda *a, **k: (
        "<h1>Acrylic jugs</h1><p>An acrylic jug is a jug made of acrylic, and "
        "this sentence exists so the body is long enough to be an article.</p>",
        "")
    pushed = []
    shopify_seo.create_article = lambda profile, blog_id, fields: (
        pushed.append(fields.get("title")) or
        "https://baci.example/blogs/news/acrylic-jug — published · id 900")

    print("— the policy is per system, and each answer has a reason —")
    ck("blog may push", systems.may_auto_ship("blog"))
    ck("campaign_email may NOT",
       not systems.may_auto_ship("campaign_email"),
       "owner, 2026-08-31: 'Leave it human, in the ESP' — a send cannot be "
       "recalled or refreshed")
    ck("ad_creative may NOT",
       not systems.may_auto_ship("ad_creative"),
       "no ad-platform write is wired at all; True would promise a spend no "
       "code performs")
    ck("an unlisted system may not",
       not systems.may_auto_ship("reports") and not systems.may_auto_ship(""),
       "absence is not permission — the standing rule of this codebase")

    print()
    print("— on a manual rung the article waits, as it always did —")
    _setup("shadow")
    skill.run("blog_article", "baci", keyword="acrylic jug", role="pillar")
    aps = _seo()
    ck("a ship is queued", len(aps) == 1, str([a.kind for a in aps]))
    ck("  and it is still pending", aps[0].status == "pending", aps[0].status)
    ck("  nothing reached the CMS", pushed == [], str(pushed))

    print()
    print("— on `auto` it publishes itself, through the same executor —")
    _setup("auto")
    skill.run("blog_article", "baci", keyword="melamine bowl", role="support")
    aps2 = [a for a in _seo() if a.id != aps[0].id]
    ck("a second ship was queued", len(aps2) == 1, str(len(aps2)))
    ck("  and it was EXECUTED, not left pending",
       aps2[0].status == "executed", aps2[0].status)
    ck("  the CMS actually received it", len(pushed) == 1, str(pushed))
    ck("  and the earlier manual one is untouched",
       [a for a in _seo() if a.id == aps[0].id][0].status == "pending",
       "promoting the system must not sweep up what was already waiting")

    print()
    print("— and the keyword map learns the page went live —")
    # THE WRITE-BACK THAT NEVER FIRED. `keywords.mark_published` joins on
    # `KeywordTarget.output_id`, and that column was written AFTER the publish
    # block — harmless while every push waited for a person, fatal on `auto`
    # where the ship happens inside the same run. The page went live on the
    # client's site while the map still read `status=planned, target_url=''`:
    # live, unlinkable, unmeasurable, and silent.
    with db.SessionLocal() as s:
        kw = (s.query(db.KeywordTarget)
              .filter(db.KeywordTarget.tenant == "baci",
                      db.KeywordTarget.phrase == "melamine bowl").first())
    ck("the keyword knows its article",
       (kw.output_id or "") != "", kw.output_id)
    ck("  it is marked published, not left planned",
       (kw.status or "") == "published",
       f"status={kw.status!r} — the board would go on offering it as work "
       f"nobody had done")
    ck("  it carries the address the CMS gave it",
       (kw.target_url or "").startswith("http"), kw.target_url)
    ck("  and the platform id, so a refresh can revise it",
       (kw.cms_article_id or "") != "",
       "without it the next refresh proposes a CREATE and publishes a "
       "duplicate beside the page that ranks")

    print()
    print("— and the record says a machine decided, not a person —")
    with db.SessionLocal() as s:
        run = s.get(db.SystemRun, aps2[0].run_id) if aps2[0].run_id else None
    ck("the run's decision reads `auto`",
       run is not None and run.decision == "auto",
       f'{getattr(run, "decision", None)} — "approved" would make an '
       f'unattended publish indistinguishable from one somebody read')

    print()
    print("— it refuses rather than guessing —")
    ck("no pending ship is said, not assumed",
       approvals.ship_unattended("baci", "no-such-output").get("why")
       == "no pending ship for that output")

    print()
    print("— and the card tells each system the truth about its own rung —")
    ck("blog's auto card promises sending",
       "Sends without asking" in systems.autonomy_meaning("auto", "blog"))
    ck("  campaign_email's does not",
       "does not push on its own" in
       systems.autonomy_meaning("auto", "campaign_email"),
       "the platform answer is not the account's answer, and a card that "
       "inherits the general sentence promises a send that will not happen")
    ck("  and shadow still says every draft waits",
       "waits for your tap" in systems.autonomy_meaning("shadow", "blog"))
    # THE CARD THAT ACTUALLY RENDERS. The per-system reader existed and this
    # one call site still read the global `AUTONOMY_MEANING`, so the settings
    # card promised campaign_email "Sends without asking" on a system
    # `AUTO_SHIPS` deliberately holds back.
    from app import admin_ui
    mail_row = systems.find("baci", "campaign_email") or \
        systems.create("baci", "campaign_email")
    with db.SessionLocal() as s:
        s.get(db.System, mail_row.id).autonomy = "auto"
        s.commit()
    mail_row = systems.find("baci", "campaign_email")
    card = " ".join(admin_ui._rung("auto", mail_row.key).split())
    ck("the settings card says it too, per system",
       "does not push on its own" in card and "Sends without asking" not in card,
       card[:110])

    print()
    print("PASS" if not _fail else f"FAILED: {len(_fail)}")
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
