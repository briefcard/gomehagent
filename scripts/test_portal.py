"""A client can sign in, and can only ever see their own account.

The console has had two credentials — `APPROVAL_SECRET` and `READ_KEY` — and
NEITHER is scoped to a client. `tenant=` is a filter, not a permission, so
anyone holding either key can change it and read every account. That was
tolerable while only the owner had a login. It stops being tolerable the moment
a client does, and no amount of visual work makes it safe.

The rule everything else rests on: **a client's tenant comes from their
session, never from the URL**, and a mismatch is REFUSED rather than silently
corrected — a substitution makes reading someone else's data look exactly like
a stale bookmark.

    python3 scripts/test_portal.py
"""
import datetime as dt
import html
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'po.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["PUBLIC_BASE_URL"] = "https://x.example.com"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import db, ledger, portal, tenants, web  # noqa: E402

_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    db.init_db()
    tenants.seed()
    with db.SessionLocal() as s:
        s.add(db.User(name="Ellis", email="Ellis@Cov.Example", role="client",
                      tenant_key="coverings", active_tenant="coverings"))
        s.add(db.User(name="Mara", email="mara@baci.example", role="client",
                      tenant_key="baci", active_tenant="baci"))
        s.add(db.User(name="Ghost", email="ghost@x.example", role="client",
                      tenant_key="", status="active"))
        s.commit()
    ledger.record("coverings", "service_desk", body="hi", format="reply",
                  status="published")

    print("— a sign-in link is a credential, and behaves like one —")
    ck("an unknown address gets no link",
       not portal.issue_link("nobody@x.example")["ok"],
       "self-registration on a portal showing commercial data is not a feature")
    ck("a user with no account attached is refused",
       "no account attached" in portal.issue_link("ghost@x.example")["error"],
       "otherwise they inherit the owner's unscoped view")
    link = portal.issue_link("ellis@cov.example")
    ck("a known address gets one, case-insensitively", link["ok"],
       "an address differing only in case is the commonest silent failure")
    tok = link["url"].rsplit("/", 1)[-1]
    ck("redeeming works once", portal.redeem(tok)["ok"])
    ck("  and only once",
       "already been used" in portal.redeem(tok)["error"],
       "a reusable link sits in a mailbox waiting to be forwarded")

    fresh = portal.issue_link("ellis@cov.example")["url"].rsplit("/", 1)[-1]
    with db.SessionLocal() as s:
        row = s.get(db.PortalLink, fresh)
        row.expires_at = db.utcnow() - dt.timedelta(minutes=1)
        s.commit()
    ck("an expired link is refused", "expired" in portal.redeem(fresh)["error"])

    print("\n— the session cannot be forged —")
    good = portal.issue_link("ellis@cov.example")["url"].rsplit("/", 1)[-1]
    cookie = portal.redeem(good)["cookie"]
    ck("a valid cookie resolves to its account",
       portal.read_session(cookie)["tenant"] == "coverings")
    ck("one flipped character is rejected",
       portal.read_session(cookie[:-1] + ("0" if cookie[-1] != "0" else "1")) == {})
    forged = "someone|baci|client|9999999999.deadbeef"
    ck("a hand-written cookie is rejected", portal.read_session(forged) == {},
       "the tenant is INSIDE the signature, so it cannot be edited")

    print("\n— the rule —")
    # base_url must be https: the cookie is secure=True, and over http the
    # client silently sends nothing — which reads as a passing test while
    # actually exercising the signed-out path.
    c = TestClient(web.app, base_url="https://testserver")
    tok = portal.issue_link("ellis@cov.example")["url"].rsplit("/", 1)[-1]
    c.get(f"/portal/in/{tok}", follow_redirects=False)

    mine = c.get("/portal").text
    ck("a signed-in client sees their own account", "Coverings Etc" in mine)
    other = c.get("/portal?tenant=baci")
    body = html.unescape(other.text)
    ck("asking for another account is REFUSED", "cannot read" in body)
    ck("  by name, not silently corrected", "coverings" in body and "baci" in body,
       "a substitution makes an attempt look like a stale bookmark")
    ck("  and none of the other account leaks", "Baci Milano" not in other.text)
    ck("  while staying signed in", "Sign out" in other.text,
       "showing a sign-in form to somebody who IS signed in reads as a broken "
       "session rather than a boundary")

    print("\n— signed out is signed out —")
    anon = TestClient(web.app, base_url="https://testserver")
    ck("no cookie means the sign-in page", "Sign in" in anon.get("/portal").text)
    ck("  and no account name is rendered",
       "Coverings Etc" not in anon.get("/portal").text)
    ck("signing out clears the cookie",
       c.get("/portal/out", follow_redirects=False).status_code == 303)

    print("\n— the sign-in form is not a customer list —")
    sent = []
    from app import channel as _ch
    _real = _ch.send_text
    _ch.send_text = lambda body, **kw: sent.append(body)
    try:
        r1 = c.post("/portal/signin", data={"email": "ellis@cov.example"})
        r2 = c.post("/portal/signin", data={"email": "stranger@nowhere.example"})
    finally:
        _ch.send_text = _real
    ck("a known and an unknown address answer identically",
       r1.text == r2.text,
       "otherwise the login form tells a stranger which addresses have accounts")
    ck("  and the page does not promise an email that nothing sends",
       "Check your email" not in r1.text and "Request received" in r1.text,
       "nothing sends the link, so saying it is on its way is a promise the "
       "system does not keep")

    print("\n— a manual link still has to reach a human —")
    ck("a known request pings ops with the link ready",
       any("Portal access requested" in m and "/portal/in/" in m for m in sent),
       "otherwise the request dies in a log line and the client waits for an "
       "email that was never coming")
    ck("  an unknown address is reported too, differently",
       any("not on file" in m for m in sent),
       "either a client using another address, or somebody probing — both "
       "want a human to look")

    print("\n— every screen renders, scoped —")
    tok = portal.issue_link("ellis@cov.example")["url"].rsplit("/", 1)[-1]
    c.get(f"/portal/in/{tok}", follow_redirects=False)
    for tab in ("overview", "results", "connections", "requests"):
        page = c.get(f"/portal?tab={tab}").text
        ck(f"  {tab}", "Coverings Etc" in page and "Baci Milano" not in page)

    print("\n— read only is the default, and it is enforced —")
    saved = portal.save_person(email="new@cov.example", name="Sam",
                               tenant="coverings")
    ck("a new person is read-only unless somebody says otherwise",
       saved["access"] == "read_only",
       "least privilege: access is added, never forgotten to remove")
    ck("a client must be pinned to an account",
       not portal.save_person(email="x@y.z", name="X", tenant="")["ok"])
    ck("an unknown account is refused",
       not portal.save_person(email="x@y.z", name="X", tenant="nope")["ok"])

    ro = TestClient(web.app, base_url="https://testserver")
    tk = portal.issue_link("new@cov.example")["url"].rsplit("/", 1)[-1]
    ro.get(f"/portal/in/{tk}", follow_redirects=False)
    page = ro.get("/portal?tab=requests").text
    ck("a read-only client sees the question but no field",
       "read-only" in page and "/portal/figure" not in page,
       "a disabled input invites a support message about a broken form")

    before = len(db.SessionLocal().query(db.ReportedFigure).all())
    ro.post("/portal/figure", data={"metric": "projects_won", "value": "9"},
            follow_redirects=False)
    after = len(db.SessionLocal().query(db.ReportedFigure).all())
    ck("  and posting anyway is refused server-side", after == before,
       "a form nobody is shown is still a form somebody can post to")

    print("\n— full access can send a figure —")
    portal.set_access(saved["id"], "full")
    tk = portal.issue_link("new@cov.example")["url"].rsplit("/", 1)[-1]
    ro.get(f"/portal/in/{tk}", follow_redirects=False)
    ck("the field appears", "/portal/figure" in ro.get("/portal?tab=requests").text)
    ro.post("/portal/figure", data={"metric": "projects_won", "value": "about 9"},
            follow_redirects=False)
    with db.SessionLocal() as s:
        fig = (s.query(db.ReportedFigure)
               .filter(db.ReportedFigure.metric_key == "projects_won").first())
    ck("  the figure lands", fig is not None and fig.value == "about 9")
    ck("  attributed to the person who sent it", fig and "Sam" in (fig.supplied_by or ""),
       "a client-supplied number in a client-facing report must be traceable "
       "to the client who supplied it")

    print("\n— revoking closes the door AND the ones already open —")
    fresh = portal.issue_link("new@cov.example")["url"].rsplit("/", 1)[-1]
    msg = portal.revoke(saved["id"])
    ck("revoking reports the unused links it killed", "link(s) killed" in msg, msg)
    ck("  and that link no longer works",
       not portal.redeem(fresh)["ok"],
       "without this, a link already in a mailbox outlives the revocation")
    ck("  and no new link can be issued",
       not portal.issue_link("new@cov.example")["ok"])

    print()
    if _fail:
        print(f"{len(_fail)} FAILED:")
        for f in _fail:
            print(f"  - {f}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
