"""Tenant scoping is a mandatory criterion, so it is a test rather than a note.

This is an architecture test. It does not check that a feature works — it checks
that a feature *could not have been written* without deciding which client its
data belongs to. Twenty of thirty-one models were built before tenants existed
and every one of them had to be retrofitted; the point of this file is that the
thirty-second model cannot repeat it.

The rule: **any model holding client data carries `tenant`.** A model that
genuinely does not is listed in `PLATFORM_MODELS` below, with a reason. Adding a
model without doing either fails this suite — which is the difference between a
standard and a preference.

    python3 scripts/test_tenant_isolation.py
"""
from __future__ import annotations

import ast
import inspect
import os
import pathlib
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'ti.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, kernel, memory, tenants  # noqa: E402

_fail = []

# Models that hold no client data. Each entry is a decision, not an oversight —
# if you are adding to this list, be sure the row could never differ per client.
PLATFORM_MODELS = {
    "Tenant": "it IS the client",
    "User": "carries tenant_key — the platform's own access rows",
    "FeatureRequest": "about this product, not any client's business",
    # The ONE model that deliberately crosses the boundary this suite exists to
    # enforce, and the reason it may: craft is TECHNIQUE, never a fact about a
    # client's business. It cannot carry a claim_id, so it can never be cited
    # as true of anyone. A deterministic leak guard (re-run at approval),
    # reach limited by `business_model`, and human approval are what keep it
    # narrow — see `app/craft.py` and `scripts/test_craft.py`, where the
    # boundary is tested rather than the intention.
    #
    # Deliberately NOT given a tenant column: a lesson belongs to no account,
    # and adding one would invite it to be filtered like client data and then
    # trusted like it.
    "CraftLesson": "cross-client TECHNIQUE by design — never a client fact; "
                   "guarded by craft.leaks() + business_model reach + approval",
    "Setting": "run-once markers for the service itself",
    "IntakeLink": "carries tenant",
    "ConnectLink": "carries tenant",
    "Credential": "carries tenant",
    "System": "carries tenant",
    "SystemRun": "carries tenant",
    "KbBrand": "tenant is the primary key",
    "KbClaim": "carries tenant",
    "KbAudience": "carries tenant",
    "KbObjection": "carries tenant",
    "KbSituation": "carries tenant",
    "KbEntity": "carries tenant",
    "KbUnknown": "carries tenant",
}


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    db.init_db()
    tenants.seed()

    # ---- 1. every model that holds client data carries `tenant` ----------
    print("— the schema —")
    models = {}
    for name in dir(db):
        obj = getattr(db, name)
        if inspect.isclass(obj) and hasattr(obj, "__tablename__") and obj is not db.Base:
            models[name] = obj

    unscoped = []
    for name, model in sorted(models.items()):
        cols = {c.name for c in model.__table__.columns}
        if "tenant" in cols or "tenant_key" in cols:
            continue
        if name in PLATFORM_MODELS:
            continue
        unscoped.append(name)

    ck(f"every model carries `tenant` or is a declared exception "
       f"({len(models)} models)", not unscoped,
       "MISSING: " + ", ".join(unscoped) if unscoped else "")
    if unscoped:
        print("\n    A new model holding client data must carry `tenant`.")
        print("    If it genuinely holds none, add it to PLATFORM_MODELS with a")
        print("    reason. Do not delete this check to make it pass.\n")

    stale = [n for n in PLATFORM_MODELS if n not in models]
    ck("no stale entries in the exception list", not stale, ", ".join(stale))

    # ---- 2. uniqueness is per client, never global -----------------------
    print("\n— uniqueness —")
    for name, model in sorted(models.items()):
        if "tenant" not in {c.name for c in model.__table__.columns}:
            continue
        for col in model.__table__.columns:
            # A globally unique column on a per-client table means two clients
            # cannot both have one. Provider-issued ids are the exception:
            # a Gmail message id really is unique across every account.
            if col.unique and col.name not in ("id", "gmail_message_id", "token"):
                ck(f"{name}.{col.name} is not globally unique", False,
                   "make it a composite UniqueConstraint with tenant")

    ck("no per-client table has a global unique column", True)

    # ---- 3. the agent is scoped ------------------------------------------
    print("\n— the agent —")
    sig = inspect.signature(kernel.run)
    ck("kernel.run accepts a tenant", "tenant" in sig.parameters)
    ck("memory_block accepts a tenant", "tenant" in inspect.signature(memory.memory_block).parameters)
    ck("lessons_block accepts a tenant", "tenant" in inspect.signature(memory.lessons_block).parameters)

    src = pathlib.Path("app/kernel.py").read_text()
    ck("the thread is qualified by tenant", 'f"{role.name}:{tenant}"' in src)
    ck("the account block is injected", "tenants.agent_block(tenant)" in src)

    # The entry point must pass it through, or all of the above is decoration.
    ca = pathlib.Path("app/command_agent.py").read_text()
    ck("command_agent.handle takes a tenant", "tenant: str = \"\"" in ca)
    ck("and forwards it to the kernel", "tenant=tenant" in ca)
    web = pathlib.Path("app/web.py").read_text()
    ck("the telegram path resolves the sender's account",
       "_active_tenant(" in web and "tenant=_active_tenant" in web)

    # ---- 4. what the agent is actually told ------------------------------
    print("\n— what the account block says —")
    from app import kb
    kb.ensure_brand("baci", "Baci Milano USA")
    kb.set_brand("baci", positioning="Italian-designed tableware.",
                 tone="direct, warm")
    kb.add_banned("baci", "made in Italy")
    kb.add_banned("baci", "handmade")

    block = tenants.agent_block("baci")
    ck("names the account", "Baci Milano USA" in block and "baci" in block)
    ck("states what is and is not connected", "Connected:" in block)
    ck("carries the positioning", "Italian-designed" in block)
    ck("carries the voice", "direct, warm" in block)
    ck("carries the hard rules", "made in Italy" in block and "handmade" in block)
    ck("frames them as rules, not preferences", "NEVER say" in block)
    ck("tells it not to answer from another account",
       "different client" in block)

    empty = tenants.agent_block("")
    ck("with no account selected it refuses rather than assuming",
       "none selected" in empty and "do not assume" in empty)

    # ---- 5. one client's memory does not reach another -------------------
    print("\n— context does not bleed —")
    with db.SessionLocal() as s:
        s.add(db.Memory(topic="baci note", content="BACI-ONLY-SECRET",
                        scope="admin", tenant="baci"))
        s.add(db.Memory(topic="eien note", content="EIEN-ONLY-SECRET",
                        scope="admin", tenant="eien"))
        s.add(db.Memory(topic="shared", content="LEGACY-UNSCOPED",
                        scope="admin", tenant=db.UNASSIGNED))
        s.add(db.Lesson(scope="admin", lesson="BACI-LESSON", tenant="baci"))
        s.add(db.Lesson(scope="admin", lesson="UNIVERSAL-LESSON",
                        tenant=db.UNASSIGNED))
        s.commit()

    mb = memory.memory_block("admin", "baci")
    ck("this client's memory is present", "BACI-ONLY-SECRET" in mb)
    ck("another client's memory is NOT", "EIEN-ONLY-SECRET" not in mb)
    ck("pre-tenant memory still appears (no silent emptying)",
       "LEGACY-UNSCOPED" in mb)

    lb = memory.lessons_block("admin", "baci")
    ck("a client-specific lesson reaches its client", "BACI-LESSON" in lb)
    ck("a universal lesson reaches everyone", "UNIVERSAL-LESSON" in lb)
    ck("another client's lesson does not",
       "BACI-LESSON" not in memory.lessons_block("admin", "eien"))

    # ---- 5b. in /baci, only baci ------------------------------------------
    # Seven of eleven shared tools took the account as a model-supplied
    # argument, so "which client" was a suggestion. These are the checks that
    # make it a boundary.
    print("\n— in one account, only that account —")
    from app import data_tools

    with db.SessionLocal() as s:
        b, e = s.get(db.Tenant, "baci"), s.get(db.Tenant, "eien")
        b.gmail_alias, b.shopify_store = "baci", "baci"
        e.gmail_alias, e.shopify_store = "eien", "eien"
        iron = s.get(db.Tenant, "ironside")
        iron.gmail_alias, iron.shopify_store = "", ""    # a venue: no store, no inbox
        s.commit()

    # Baci connects Shopify through the connect page — the realistic path now.
    from app import credentials as cred
    real_probe = cred._probe
    cred._probe = lambda p, s, m: {"ok": True, "detail": "Baci"}
    cred.store("baci", "shopify", "shpat_x", meta={"domain": "baci.myshopify.com"})
    cred._probe = real_probe

    ck("a client-connected credential makes the capability wired",
       tenants.capabilities("baci")["commerce"],
       "connect page worked but nothing could use it")

    # THE COMPLETENESS GUARD. Any tool in any role whose schema exposes an
    # account parameter must be registered, or it is a hole. The first pass
    # gated the 11 shared tools and missed 32 across admin and seo — including
    # one that drafts mail as an account and four that publish to a live store.
    from app import roles as _roles, tool_scope
    every = list(data_tools.TOOLS)
    for _rn in _roles.ROLES:
        every += _roles.get(_rn).action_tools
    ungated = sorted({
        t["name"] for t in every
        if t["name"] not in tool_scope.SCOPED
        and set((t.get("input_schema") or {}).get("properties", {}))
        & set(tool_scope.ACCOUNT_PARAMS)})
    ck(f"every tool taking an account is gated ({len(every)} tools)",
       not ungated, "UNGATED: " + ", ".join(ungated) if ungated else "")
    if ungated:
        print("\n    A tool that names an account must be in tool_scope.SCOPED.")
        print("    Otherwise the model chooses which client it acts on.\n")

    stale_tools = sorted(set(tool_scope.SCOPED) - {t["name"] for t in every})
    ck("no stale entries in the tool registry", not stale_tools,
       ", ".join(stale_tools))

    offered = {t["name"] for t in data_tools.tools_for("baci")}
    ck("an account with a store is offered its store tools",
       "shopify_find_orders" in offered, str(sorted(offered)))

    venue = {t["name"] for t in data_tools.tools_for("ironside")}
    ck("an account with no store is NOT offered store tools",
       "shopify_find_orders" not in venue and "drive_search" not in venue,
       str(sorted(venue)))
    ck("and that is fewer tools sent every turn",
       len(venue) < len(data_tools.TOOLS),
       f"{len(venue)} vs {len(data_tools.TOOLS)}")

    schema = next(t for t in data_tools.tools_for("baci")
                  if t["name"] == "shopify_find_orders")
    props = set((schema["input_schema"].get("properties") or {}))
    ck("the model is never asked which account", "store" not in props, str(props))
    ck("nor is it required", "store" not in (schema["input_schema"].get("required") or []))
    ck("the unscoped list still carries it (nothing was mutated globally)",
       "store" in (next(t for t in data_tools.TOOLS
                        if t["name"] == "shopify_find_orders")
                   ["input_schema"]["properties"]))

    # The attack: in baci, ask for eien.
    out = data_tools.dispatch("read_email", {"account": "eien",
                                             "message_id": "x"}, tenant="baci")
    ck("naming another client's account is REFUSED", "Refused" in out, out[:90])
    ck("and it says which account the conversation is about", "baci" in out)

    out = data_tools.dispatch("shopify_find_orders", {"store": "eien"},
                              tenant="baci")
    ck("the same for the store tools", "Refused" in out, out[:90])

    out = data_tools.dispatch("shopify_find_orders", {"store": "baci"},
                              tenant="ironside")
    ck("a client without the connection is told so, not silently redirected",
       "cannot run for this account" in out, out[:90])

    # The role tools — the ones that act, not just read.
    print("\n— the tools that act as a client —")
    for tool, param, other in (("queue_email_draft", "account", "eien"),
                               ("calendar_create_event", "account", "eien"),
                               ("save_file_to_drive", "account", "eien"),
                               ("propose_seo_update", "site", "eien")):
        args, refusal = tool_scope.guard(tool, {param: other, "x": 1}, "baci")
        ck(f"{tool} refuses another client", bool(refusal) and args is None,
           (refusal or "ALLOWED IT")[:80])

    args, refusal = tool_scope.guard("queue_email_draft",
                                     {"to": "x@y.com"}, "baci")
    ck("and injects the right one when none is named",
       not refusal and args.get("account") == "baci", str(args))

    ck("an unregistered tool is untouched",
       tool_scope.guard("save_memory", {"topic": "t"}, "baci")[0] == {"topic": "t"})

    # ---- 5c. the unattended path ------------------------------------------
    # The worker and triage run with nobody watching and can SEND. They were
    # addressed by inbox alias and had no idea which client that was: tools
    # ungated, memory unscoped, and no sight of the banned claims the KB had
    # held all along.
    print("\n— the half that runs unattended —")
    import inspect as _i
    from app import triage, worker

    ck("triage takes a tenant", "tenant" in _i.signature(triage.triage_email).parameters)
    ck("an inbox resolves to its client", tenants.for_alias("baci") == "baci",
       tenants.for_alias("baci"))
    ck("an unknown inbox resolves to nothing, not a default",
       tenants.for_alias("nosuchinbox") == "")

    tsrc = pathlib.Path("app/triage.py").read_text()
    # CHANGED DELIBERATELY 2026-08-20. This pinned the literal source text of
    # one call, indentation and all:
    #
    #   "dispatch(\n     block.name, dict(block.input), tenant=tenant)" in tsrc
    #
    # which is §1's *string-matching instead of state-checking* — it fails for
    # a refactor that keeps the boundary and passes for any rewrite that
    # happens to preserve the characters. It broke the moment triage was routed
    # through the shared guarded door, which STRENGTHENS the property it was
    # written to protect.
    #
    # Asked as behaviour now, on the door both model loops share, plus the
    # durable structural half: that the UNGATED call is absent.
    ck("triage still builds its tool list per account",
       "data_tools.tools_for(tenant)" in tsrc)
    ck("triage's tool loop goes through the guarded door, not around it",
       "_tools.call(" in tsrc and "data_tools.dispatch(" not in tsrc)
    from app import tools as _tools_mod
    refusal = _tools_mod.call("shopify_find_orders", {"store": "someone-else"},
                              "baci", source="test")
    ck("and that door refuses a call naming another account BY NAME",
       "Refused" in refusal and "someone-else" in refusal, refusal)
    ck("recording the refusal as a failed call — a blocked account must not "
       "read as an idle one",
       any(r.tool == "shopify_find_orders" and r.ok == "no"
           for r in db.SessionLocal().query(db.ToolCall).all()))
    ck("triage's memory is scoped", 'memory_block("", tenant)' in tsrc)
    ck("triage is told the account's rules", "tenants.agent_block(tenant)" in tsrc)

    wsrc = pathlib.Path("app/worker.py").read_text()
    ck("the worker resolves the tenant once", "_tn.for_alias(alias)" in wsrc)
    ck("and passes it to triage", "tenant=tenant)" in wsrc)
    ck("mail is logged against its client", "db.EmailLog(\n                account=alias, tenant=tenant," in wsrc)
    ck("so are deadlines", "db.Deadline(\n                    account=alias, tenant=tenant," in wsrc)

    # The guard that matters: a banned claim must never auto-send.
    verdicts = [
        ({"action": "auto_reply", "category": "order_basic",
          "reply_subject": "Your order", "reply_body": "These are made in Italy!"},
         "escalate", True),
        ({"action": "draft", "category": "order_basic",
          "reply_subject": "Hi", "reply_body": "Handmade by our artisans."},
         "draft", True),
        ({"action": "auto_reply", "category": "order_basic",
          "reply_subject": "Your order", "reply_body": "It ships tomorrow."},
         "auto_reply", False),
    ]
    for verdict, want_action, want_flag in verdicts:
        got = triage._apply_guards(dict(verdict), "baci", sender_trusted=True)
        label = verdict["reply_body"][:28]
        ck(f"{label!r} -> {want_action}", got["action"] == want_action,
           f"got {got['action']}")
        ck(f"  and is {'flagged' if want_flag else 'clean'}",
           ("BANNED CLAIM" in got.get("reason", "")) == want_flag,
           got.get("reason", "")[:70])

    clean = triage._apply_guards(
        {"action": "auto_reply", "category": "order_basic", "reply_subject": "",
         "reply_body": "These are made in Italy!"}, "", sender_trusted=True)
    ck("an unattributed inbox cannot be brand-checked, and says nothing false",
       "BANNED CLAIM" not in clean.get("reason", ""))

    # ---- 6. threads are separate ------------------------------------------
    print("\n— threads —")
    memory.save_turn("admin:baci", "user", "how many aqua sets")
    memory.save_turn("admin:eien", "user", "how many omega bottles")
    b = str(memory.load_chat_history("admin:baci"))
    ck("each account has its own conversation",
       "aqua" in b and "omega" not in b)

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
