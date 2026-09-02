"""Why an account cannot publish is stated, with the fix, where it is reported.

Owner, 2026-09-01: *"I have shopify connected to one of the clients and it says
'No CMS' so it doesnt publish directly."* And: *"It should guide us to fill in
whatever is missing."*

HE WAS RIGHT AND THE CONSOLE WAS WORSE THAN WRONG. `('shopify','cms')` requires
the `write_content` scope, so a Shopify connection approved WITHOUT it reports
no `cms` capability at all — the account reads as unconnected. `backend()` then
refuses with "has no CMS connected — connect a site or store", which is correct
for an account that connected nothing and is the WRONG INSTRUCTION here: it
sends somebody to redo a connection that already exists instead of re-granting
one scope.

FOUR ABSENCES WERE COLLAPSED INTO FOUR WORDS, and they have four fixes:

  no domain     the tenant row is skipped entirely, so no profile exists and
                nothing downstream can even be diagnosed
  missing scope connected and working for everything else — reconnect and
                approve the one scope
  no backend    Squarespace has no write API, so paste-and-record IS the
                workflow rather than a lesser version of one
  no blog       a store holding several, where guessing writes to the wrong
                place

Run: python3 scripts/test_publish_gap.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'pg.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import credentials, db, sites, tenants  # noqa: E402

_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _tenant(key, *, domain="", cms=None):
    with db.SessionLocal() as s:
        row = s.get(db.Tenant, key)
        if row is None:
            row = db.Tenant(key=key, name=key.title())
            s.add(row)
        row.domain = domain
        row.cms = cms or {}
        s.commit()


def _connect(tenant, provider, scopes):
    with db.SessionLocal() as s:
        s.query(db.Credential).filter(db.Credential.tenant == tenant,
                                      db.Credential.provider == provider).delete()
        s.add(db.Credential(tenant=tenant, provider=provider, site="",
                            kind="oauth", secret=credentials._encrypt("tok"),
                            meta={"domain": f"{tenant}.myshopify.com"},
                            scopes=scopes, status="active",
                            granted_at=db.utcnow()))
        s.commit()


def main() -> int:
    db.init_db()
    tenants.seed()

    print("— the one the owner hit: connected, minus one scope —")
    _tenant("storeco", domain="storeco.com")
    _connect("storeco", "shopify", "read_products,write_products")
    gap = sites.publish_gap("storeco")
    ck("it is not publishable", gap["ok"] is False)
    ck("  and it does NOT say the store is unconnected",
       "Shopify is connected" in gap["why"],
       gap["why"][:120] + " — 'No CMS' sent somebody to redo a connection "
                          "that already exists")
    ck("  it names the scope that is missing",
       "write_content" in gap["why"] and "write_content" in gap["fix"],
       gap["fix"])
    ck("  and says the rest of the connection is fine",
       "keeps working" in gap["why"],
       "otherwise the obvious reading is that Shopify is broken")
    ck("  and points at the page that fixes it",
       "tab=accounts" in gap["where"], gap["where"]
       + " — `accounts` is the tab KEY; 'Connections' is only its label, and "
         "a link naming the label lands on no tab at all")

    print()
    print("— with the scope, it publishes —")
    _connect("storeco", "shopify",
             "read_products,write_products,write_content")
    _tenant("storeco", domain="storeco.com",
            cms={"platform": "shopify", "blog_id": "77"})
    ok = sites.publish_gap("storeco")
    ck("no gap is reported", ok["ok"] is True, ok["why"])

    print()
    print("— a store with several blogs and none chosen —")
    _tenant("storeco", domain="storeco.com", cms={"platform": "shopify"})
    g2 = sites.publish_gap("storeco")
    ck("it says which decision is missing",
       g2["ok"] is False and "several blogs" in g2["why"], g2["why"])
    ck("  and it is a CHOICE, not a connection problem",
       "Choose" in g2["fix"] and "connect" not in g2["fix"].lower(), g2["fix"])

    print()
    print("— no address on file at all —")
    _tenant("blankco", domain="")
    g3 = sites.publish_gap("blankco")
    ck("it says that is upstream of everything else",
       g3["ok"] is False and "no website address" in g3["why"],
       "the tenant row is skipped when building profiles, so nothing further "
       "can even be diagnosed")

    print()
    print("— a platform nothing can write to is not a failure —")
    _tenant("squareco", domain="squareco.com",
            cms={"platform": "squarespace"})
    g4 = sites.publish_gap("squareco")
    ck("it names the platform", "squarespace" in g4["why"], g4["why"][:90])
    ck("  and calls paste-and-record THE workflow, not a lesser one",
       "IS the workflow" in g4["why"],
       "an account that can never push should not read as permanently broken")
    ck("  and offers no page to go fix it",
       g4["where"] == "",
       "a link to Connections there would be a fix instruction for a thing "
       "no connection can fix")

    print()
    print("— nothing connected says exactly that —")
    _tenant("newco", domain="newco.com")
    g5 = sites.publish_gap("newco")
    ck("it is the generic sentence, for the generic case",
       g5["ok"] is False and "Nothing that can publish" in g5["why"],
       g5["why"])
    ck("  which is a DIFFERENT sentence from the missing-scope one",
       g5["why"] != gap["why"],
       "collapsing them is the defect: one says connect something, the other "
       "says re-approve one scope on what is already connected")

    print()
    print("— and it is on the page that reported the absence —")
    from app import admin_ui, kb, skill_pack
    kb.ensure_brand("storeco", "Storeco")
    _tenant("storeco", domain="storeco.com")
    _connect("storeco", "shopify", "read_products,write_products")
    with db.SessionLocal() as s:
        out = db.Output(tenant="storeco", system_key="blog",
                        format="cms_article", status="draft")
        s.add(out)
        s.commit()
        oid = out.id
        s.add(db.ArtifactBody(tenant="storeco", system_key="blog",
                              format="cms_article", output_id=oid,
                              body="<h1>A</h1><p>B</p>"))
        s.commit()
    from app.web import _article_bundle
    art, kwrow, aprow = _article_bundle(oid)
    page = " ".join(admin_ui.render_workroom("s3cret", oid, art, kwrow,
                                             aprow).split())
    ck("the workroom states the real gap",
       "write_content" in page,
       "the page said 'No CMS to push to' — four words for four situations")
    ck("  and gives the action",
       "Reconnect Shopify" in page)
    ck("  and a way to get there",
       "tab=accounts" in page,
       "act where you report: the fix is a click from the absence")

    print()
    print("PASS" if not _fail else f"FAILED: {len(_fail)}")
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
