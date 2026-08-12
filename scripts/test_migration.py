"""The migration has to survive a database that already has rows in it.

Every test in this repo builds a fresh database, where `create_all` produces the
right schema and the migration path is never exercised. Production is the
opposite case: tables that already exist, with data, and columns that have to be
added underneath them. That is the gap §2.8 fell into — the migration landed,
the tests passed, and behaviour regressed because existing rows came back empty.

So this builds a database with the PRE-tenant schema, puts rows in it, then runs
the real startup path over it.

    python3 scripts/test_migration.py
"""
from __future__ import annotations

import os
import sys
import tempfile

_DB = os.path.join(tempfile.mkdtemp(), "old.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_DB}"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sqlite3  # noqa: E402

_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


# The shape these tables had BEFORE the tenant column existed, written by hand
# so the test cannot drift with the models.
_OLD_SCHEMA = """
CREATE TABLE contacts (
  id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, name TEXT, company TEXT,
  role TEXT, entity TEXT, trusted TEXT DEFAULT 'no');
CREATE TABLE email_log (
  id TEXT PRIMARY KEY, seen_at TIMESTAMP, account TEXT NOT NULL,
  gmail_message_id TEXT UNIQUE NOT NULL, thread_id TEXT, sender TEXT,
  subject TEXT, category TEXT, action TEXT, detail TEXT);
CREATE TABLE memories (
  id TEXT PRIMARY KEY, created_at TIMESTAMP, topic TEXT NOT NULL,
  content TEXT NOT NULL, status TEXT DEFAULT 'active', scope TEXT DEFAULT 'global');
CREATE TABLE shipments (
  id TEXT PRIMARY KEY, created_at TIMESTAMP, updated_at TIMESTAMP,
  name TEXT UNIQUE NOT NULL, status TEXT DEFAULT 'quoting', eta TEXT,
  counterparty TEXT, docs TEXT, costs TEXT, notes TEXT DEFAULT '');
"""


def main() -> int:
    con = sqlite3.connect(_DB)
    con.executescript(_OLD_SCHEMA)
    con.executemany("INSERT INTO contacts (id,email,entity,trusted) VALUES (?,?,?,?)",
                    [("c1", "ana@fwd.com", "baci", "yes"),
                     ("c2", "bob@broker.com", "saias", "no"),
                     ("c3", "carl@x.com", "", "no")])
    con.executemany(
        "INSERT INTO email_log (id,account,gmail_message_id,subject) VALUES (?,?,?,?)",
        [("e1", "baci", "m1", "order"), ("e2", "nosuchalias", "m2", "spam")])
    con.executemany("INSERT INTO memories (id,topic,content,scope) VALUES (?,?,?,?)",
                    [("m1", "blog", "c", "system:baci:blog"),
                     ("m2", "rule", "c", "global")])
    con.execute("INSERT INTO shipments (id,name) VALUES ('s1','Turkey-Mar2026')")
    con.commit()
    con.close()
    print(f"built a pre-tenant database with rows in it\n  {_DB}\n")

    # --- the real startup path, over the old database --------------------
    from app import db, tenant_scope, tenants
    db.init_db()

    con = sqlite3.connect(_DB)
    cols = {t: {r[1] for r in con.execute(f"PRAGMA table_info({t})")}
            for t in ("contacts", "email_log", "memories", "shipments")}
    for t, c in cols.items():
        ck(f"{t}: tenant column added to the existing table", "tenant" in c)
    ck("existing rows survived the migration",
       con.execute("SELECT COUNT(*) FROM contacts").fetchone()[0] == 3)
    ck("and came back unassigned, not wrong",
       con.execute("SELECT COUNT(*) FROM contacts WHERE tenant IS NULL OR tenant=''"
                   ).fetchone()[0] == 3)
    con.close()

    # --- seeding tenants then attributing --------------------------------
    tenants.seed()
    filled = tenant_scope.backfill()
    print(f"\nbackfilled: {filled}\n")

    with db.SessionLocal() as s:
        ck("a contact tagged 'baci' became tenant baci",
           s.query(db.Contact).filter(db.Contact.email == "ana@fwd.com").first().tenant == "baci")
        ck("a contact tagged 'saias' became tenant agency",
           s.query(db.Contact).filter(db.Contact.email == "bob@broker.com").first().tenant == "agency")
        ck("a contact tagged with nothing stays unassigned",
           s.query(db.Contact).filter(db.Contact.email == "carl@x.com").first().tenant == db.UNASSIGNED)
        ck("mail on a known inbox is attributed",
           s.query(db.EmailLog).filter(db.EmailLog.gmail_message_id == "m1").first().tenant == "baci")
        ck("mail on an unknown inbox is NOT guessed",
           s.query(db.EmailLog).filter(
               db.EmailLog.gmail_message_id == "m2").first().tenant == db.UNASSIGNED)
        ck("a scoped memory is attributed",
           s.query(db.Memory).filter(db.Memory.id == "m1").first().tenant == "baci")
        ck("a global memory stays global",
           s.query(db.Memory).filter(db.Memory.id == "m2").first().tenant == db.UNASSIGNED)
        ck("the shipment survived and is unattributed",
           s.query(db.Shipment).first().tenant == db.UNASSIGNED)

    # --- and running startup twice changes nothing ------------------------
    db.init_db()
    again = tenant_scope.backfill()
    ck("a second startup + backfill is a no-op", again == {}, str(again))

    print("\nNOTE: SQLite cannot drop the old single-column UNIQUE, so on this")
    print("database `contacts.email` stays globally unique. Production is")
    print("Postgres, where _migrate_constraints() regrades it — that path is")
    print("NOT exercised here and must be confirmed against the live database.")

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
