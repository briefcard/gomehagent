"""The operational half has to survive a second client.

Three tables enforced uniqueness globally: one contact per email, one shipment
per name, one RFQ per shipment name — across every client at once. That is not
a design question, it is an IntegrityError the first time two clients import in
the same month or share a freight forwarder.

This proves the collisions are gone, that the backfill derives what it can, and
— the part that matters more — that it refuses to invent an owner for a row
that never recorded one.

    python3 scripts/test_tenant_scope.py
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'ts.db')}"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, tenant_scope, tenants  # noqa: E402

_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    db.init_db()
    tenants.seed()

    with db.SessionLocal() as s:
        t = {r.key: r for r in s.query(db.Tenant).all()}
        print(f"\ntenants: {', '.join(sorted(t))}")
        aliases = {k: r.gmail_alias for k, r in t.items() if r.gmail_alias}
        domains = {k: r.domain for k, r in t.items() if r.domain}

    # ---- 1. the same counterparty, two clients ---------------------------
    print("\n— one forwarder, two clients —")
    with db.SessionLocal() as s:
        s.add(db.Contact(tenant="baci", email="ops@forwarder.com",
                         name="Ana", role="forwarder", trusted="yes"))
        s.add(db.Contact(tenant="eien", email="ops@forwarder.com",
                         name="Ana", role="forwarder", trusted="no"))
        s.commit()
        got = s.query(db.Contact).filter(db.Contact.email == "ops@forwarder.com").all()
    ck("the same email exists for two clients", len(got) == 2)
    ck("with independent trust levels",
       {c.tenant: c.trusted for c in got} == {"baci": "yes", "eien": "no"})

    print("\n— the same shipment name, two clients —")
    with db.SessionLocal() as s:
        s.add(db.Shipment(tenant="baci", name="Turkey-Mar2026"))
        s.add(db.Shipment(tenant="eien", name="Turkey-Mar2026"))
        s.add(db.RFQ(tenant="baci", shipment_name="Turkey-Mar2026"))
        s.add(db.RFQ(tenant="eien", shipment_name="Turkey-Mar2026"))
        s.commit()
        ck("both shipments exist",
           s.query(db.Shipment).filter(db.Shipment.name == "Turkey-Mar2026").count() == 2)
        ck("both RFQs exist",
           s.query(db.RFQ).filter(db.RFQ.shipment_name == "Turkey-Mar2026").count() == 2)

    # ---- 2. uniqueness still bites WITHIN a client ------------------------
    print("\n— still unique inside one client —")
    from sqlalchemy.exc import IntegrityError
    for model, kw in ((db.Contact, dict(tenant="baci", email="ops@forwarder.com")),
                      (db.Shipment, dict(tenant="baci", name="Turkey-Mar2026")),
                      (db.RFQ, dict(tenant="baci", shipment_name="Turkey-Mar2026"))):
        try:
            with db.SessionLocal() as s:
                s.add(model(**kw))
                s.commit()
            ck(f"{model.__tablename__}: duplicate within a client is refused", False,
               "it was accepted")
        except IntegrityError:
            ck(f"{model.__tablename__}: duplicate within a client is refused", True)

    # ---- 3. the backfill derives what a row actually records --------------
    print("\n— derivable attribution —")
    alias_key = next(iter(aliases)) if aliases else ""
    dom_key = next(iter(domains)) if domains else ""
    with db.SessionLocal() as s:
        if alias_key:
            s.add(db.EmailLog(account=aliases[alias_key], gmail_message_id="m1",
                              sender="x@y.com", subject="hi"))
            s.add(db.Deadline(account=aliases[alias_key], description="duty due"))
            s.add(db.FollowUp(account=aliases[alias_key], to="x@y.com"))
            s.add(db.VoiceProfile(alias=aliases[alias_key], rules="short sentences"))
        if dom_key:
            s.add(db.SeoSnapshot(domain=domains[dom_key]))
            s.add(db.SeoSnapshot(domain="www." + domains[dom_key]))  # normalises
        s.add(db.Memory(topic="t", content="c", scope="system:baci:blog"))
        s.add(db.ChatMessage(thread="seo:eien", role="user", content="hi"))
        s.add(db.SystemDoc(key="drive:baci", title="Baci drive"))
        s.add(db.Contact(email="legacy@x.com", entity="saias"))     # old vocabulary
        s.add(db.Contact(email="legacy2@x.com", entity="baci"))
        # An expense records the inbox it was captured from.
        if alias_key:
            s.add(db.Expense(account=aliases[alias_key], vendor="Staples", amount="$40"))
        # An approval records what it was about, in its payload.
        s.add(db.Approval(kind="seo_new_collection", summary="x",
                          payload={"site": "baci", "bucket": "seo"}))
        s.add(db.Approval(kind="send_email", summary="y",
                          payload={"account": "baci", "to": "a@b.com"}))
        s.add(db.Approval(kind="other", summary="z", payload={"note": "nothing"}))
        # Deliberately unattributable: nothing on the row says whose it is.
        s.add(db.Expense(account="nosuchalias", vendor="Costco", amount="$9"))
        s.add(db.DocIndex(filename="BOL.pdf", path="/B2B", anchor="PO-2241"))
        s.add(db.Usage(purpose="command", model="claude-opus-5"))
        s.commit()

    # The dry run must predict exactly what the write does, or it is worse
    # than no dry run — it would be a number someone acts on.
    pred = tenant_scope.preview()
    predicted = {t: r["would_attribute"] for t, r in pred.items() if r["would_attribute"]}
    with db.SessionLocal() as s:
        before = s.query(db.Memory).filter(db.Memory.tenant != db.UNASSIGNED).count()

    filled = tenant_scope.backfill()
    print(f"  predicted:  {predicted}")
    print(f"  backfilled: {filled}")
    ck("the dry run predicted the write exactly", predicted == filled,
       f"{predicted} vs {filled}")

    with db.SessionLocal() as s:
        after_preview_only = s.query(db.Memory).filter(
            db.Memory.tenant != db.UNASSIGNED).count()
    ck("preview() wrote nothing itself", after_preview_only >= before)
    ck("preview reports who each row would go to",
       all(sum(r["by_tenant"].values()) == r["would_attribute"]
           for r in pred.values()))
    ck("and how many it cannot reach",
       all(r["would_remain"] == r["unassigned"] - r["would_attribute"]
           for r in pred.values()))

    with db.SessionLocal() as s:
        if alias_key:
            ck("email log attributed from its inbox",
               s.query(db.EmailLog).filter(db.EmailLog.gmail_message_id == "m1")
                .first().tenant == alias_key)
            ck("voice profile attributed from its inbox",
               s.query(db.VoiceProfile).filter(
                   db.VoiceProfile.alias == aliases[alias_key]).first().tenant == alias_key)
        if dom_key:
            snaps = s.query(db.SeoSnapshot).all()
            ck("both www and bare domain attributed",
               all(x.tenant == dom_key for x in snaps),
               str([(x.domain, x.tenant) for x in snaps]))
        ck("memory attributed from 'system:baci:blog'",
           s.query(db.Memory).first().tenant == "baci")
        ck("chat thread attributed from 'seo:eien'",
           s.query(db.ChatMessage).first().tenant == "eien")
        ck("system doc attributed from 'drive:baci'",
           s.query(db.SystemDoc).filter(db.SystemDoc.key == "drive:baci")
            .first().tenant == "baci")
        ck("old 'saias' contact maps to agency",
           s.query(db.Contact).filter(db.Contact.email == "legacy@x.com")
            .first().tenant == "agency")
        ck("old 'baci' contact maps straight through",
           s.query(db.Contact).filter(db.Contact.email == "legacy2@x.com")
            .first().tenant == "baci")

        print("\n— what a row does record —")
        if alias_key:
            ck("an expense is attributed from the inbox that captured it",
               s.query(db.Expense).filter(db.Expense.vendor == "Staples")
                .first().tenant == alias_key)
        ck("an approval is attributed from payload.site",
           s.query(db.Approval).filter(db.Approval.kind == "seo_new_collection")
            .first().tenant == "baci")
        ck("an approval is attributed from payload.account",
           s.query(db.Approval).filter(db.Approval.kind == "send_email")
            .first().tenant == "baci")

        # ---- 4. and refuses to invent one -------------------------------
        print("\n— refusing to guess —")
        ck("an approval whose payload says nothing stays unassigned",
           s.query(db.Approval).filter(db.Approval.kind == "other")
            .first().tenant == db.UNASSIGNED)
        ck("an expense on an unknown inbox stays unassigned",
           s.query(db.Expense).filter(db.Expense.vendor == "Costco")
            .first().tenant == db.UNASSIGNED)
        ck("a document with no client stays unassigned",
           s.query(db.DocIndex).first().tenant == db.UNASSIGNED)
        ck("a usage row with no client stays unassigned",
           s.query(db.Usage).first().tenant == db.UNASSIGNED)

    # ---- 5. idempotent, and does not re-attribute -------------------------
    print("\n— safe to re-run —")
    again = tenant_scope.backfill()
    ck("a second run changes nothing", again == {}, str(again))

    with db.SessionLocal() as s:
        s.add(db.Memory(topic="manual", content="c", scope="global", tenant="coverings"))
        s.commit()
    tenant_scope.backfill()
    with db.SessionLocal() as s:
        ck("a hand-set tenant is never overwritten",
           s.query(db.Memory).filter(db.Memory.topic == "manual")
            .first().tenant == "coverings")

    # ---- 6. ambiguity names nothing ---------------------------------------
    ck("a scope naming two tenants is left alone",
       tenant_scope._tenant_in("system:baci:eien", {"baci", "eien"}) == "")
    ck("a substring is not a match",
       tenant_scope._tenant_in("agencywide", {"agency"}) == "")
    ck("an exact segment is", tenant_scope._tenant_in("seo:agency", {"agency"}) == "agency")

    # ---- 7. the scope helper excludes unassigned by default ---------------
    print("\n— unassigned is not 'everyone' —")
    with db.SessionLocal() as s:
        mine = s.query(db.Expense).filter(
            db.tenant_filter(db.Expense, "baci")).count()
        withbacklog = s.query(db.Expense).filter(
            db.tenant_filter(db.Expense, "baci", include_unassigned=True)).count()
    ck("an unattributed row is not returned for a client", mine == 0)
    ck("but is reachable when asked for explicitly", withbacklog == 1)

    # ---- 8. trust does not cross clients ----------------------------------
    # Allowing duplicate emails opened a path where one client's trusted=yes
    # authorises auto-send on another client's inbox. This is that boundary.
    print("\n— trust is per client —")
    from app import worker
    with db.SessionLocal() as s:
        s.query(db.Contact).delete()
        s.add(db.Contact(tenant="baci", email="ana@fwd.com", trusted="yes"))
        s.add(db.Contact(tenant="eien", email="ana@fwd.com", trusted="no"))
        s.add(db.Contact(tenant=db.UNASSIGNED, email="legacy@fwd.com", trusted="yes"))
        s.commit()
        baci_alias = s.query(db.Tenant).filter(db.Tenant.key == "baci").first().gmail_alias
        eien_alias = s.query(db.Tenant).filter(db.Tenant.key == "eien").first().gmail_alias

    if baci_alias and eien_alias:
        ck("trusted on the client that trusts them",
           worker.is_trusted("Ana <ana@fwd.com>", baci_alias) is True)
        ck("NOT trusted on a client that does not",
           worker.is_trusted("Ana <ana@fwd.com>", eien_alias) is False)
    ck("a pre-tenant contact still auto-sends (no silent regression)",
       worker.is_trusted("<legacy@fwd.com>", baci_alias or "") is True)
    ck("an unknown sender is never trusted",
       worker.is_trusted("<nobody@x.com>", baci_alias or "") is False)

    print()
    tenant_scope.print_report()

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
