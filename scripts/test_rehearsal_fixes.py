"""What the dress rehearsal found the night before a client presentation.

Running every system offline against the seeded accounts surfaced defects no
suite had: a bare `KeyError: 'domain'` where an account with no store needed
"connect a store"; a client email listing "?: SystemRun.edit_diff…" for every
unmeasured figure; and inbound mail drafted under the service desk's guidance
whatever system owned it. Each is held here so it cannot come back quietly.

Run: python3 scripts/test_rehearsal_fixes.py
"""
import os
import re
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'rf.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["SEO_SITES_JSON"] = "{}"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import client_report, data_tools, db, kb, shopify_seo, skill, skill_pack, systems, tenants  # noqa: E402,F401

_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    db.init_db()
    tenants.seed()
    kb.ensure_brand("baci", "Baci Milano")
    kb.add_banned("baci", "handmade")
    _ALL = {c: True for c in tenants.CAPABILITIES}
    tenants.capabilities = lambda k: dict(_ALL)

    # ---- an unconnected store is refused by name, on every path -------------
    try:
        shopify_seo._cfg("nowhere")
        said = ""
    except RuntimeError as e:
        said = str(e)
    except KeyError as e:
        said = f"KeyError {e}"
    ck("shopify_seo names the missing store", "no Shopify store is connected" in said and "nowhere" in said, said[:90])
    try:
        data_tools._store_cfg("nowhere")
        said2 = ""
    except RuntimeError as e:
        said2 = str(e)
    except KeyError as e:
        said2 = f"KeyError {e}"
    ck("data_tools names it too — the same sentence", "no Shopify store is connected" in said2, said2[:90])
    for key in ("catalog_compliance", "catalog_seo_rewrite"):
        row = systems.find("baci", key) or systems.create("baci", key)
        with db.SessionLocal() as s:
            s.get(db.System, row.id).status = "live"
            s.commit()
    got = skill.run("catalog_compliance", "baci")
    blocked = " ".join(got.get("blocked_on") or [])
    ck("the catalogue skill blocks on the sentence, not on KeyError",
       "KeyError" not in blocked and ("store" in blocked or got.get("status") != "failed"),
       f"status={got.get('status')} blocked_on={blocked[:100]}")

    # ---- the client email names figures, never fields ----------------------
    rep = client_report.assemble("baci", 7)
    msg = client_report.render_email(rep)
    ck("the client email never shows an internal identifier",
       "SystemRun" not in msg["text"] and "edit_diff" not in msg["text"] and "?:" not in msg["text"],
       msg["text"][:200].replace("\n", " | "))
    ck("  and names the figures it cannot yet give — the pair",
       "revenue and orders" in msg["text"] or not rep.get("not_yet_measured"),
       str([u.get("figure") for u in rep.get("not_yet_measured") or []]))
    ck("  with a fix a client can act on, not a catalogue reference",
       all("CATALOG" not in (u.get("fix") or "") for u in rep.get("not_yet_measured") or []))

    # ---- inbound mail is drafted under its routed system --------------------
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "app", "web.py")).read()
    ck("the inbound draft route chooses the system by the mail's bucket",
       bool(re.search(r"_owner = replies\.route\(r\.category", src))
       and "system_key=(_owner if _owner in systems.CATALOG" in src,
       "a hardcoded service_desk drafts every lead with the wrong guidance")

    print()
    print("PASS" if not _fail else f"FAILED: {len(_fail)}")
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
