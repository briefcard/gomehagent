"""Empty one account, on purpose, with the damage shown first.

Wiping the whole database to see what onboarding looks like does not work —
`tenants.seed()` puts the five accounts back and `kb_seed` repopulates three of
them from hardcoded facts, ban lists included. You would get a pre-filled Baci
rather than a blank client. That is re-seeding, not onboarding.

What is genuinely useful is emptying **one** account: a client who has changed
direction, a demo after a pitch, or a real onboarding rehearsal on a tenant
that was never seeded.

Three rules, each of which exists because the alternative is worse:

**The table list comes from the schema, never a literal.** Every model carrying
a `tenant` column is included automatically. A hand-maintained list silently
misses the model somebody adds next month, and a reset that leaves rows behind
is worse than no reset — the account looks empty and is not.

**An empty tenant is refused.** `tenant=""` is `UNASSIGNED`, the marker for
rows whose owner could not be determined. Deleting on it would erase every
unattributed row in the system, belonging to nobody and to everybody.

**Credentials are opt-out of the default.** Deleting them costs your *client*
an afternoon redoing OAuth, not you. That deserves its own decision rather
than riding along with a knowledge reset.
"""
from __future__ import annotations

import inspect

from . import db

#: Tables that hold what the account KNOWS. Safe to clear and rebuild from a
#: crawl, an intake link and a catalogue sync.
# NOTE the singular `kb_brand`. I wrote `kb_brands` from memory and the
# unclassified report caught it — a knowledge reset would have left the brand
# row behind, positioning, voice and the entire ban list intact, while
# reporting success. That is the precise failure this whole file is built to
# avoid, found in the file itself.
KNOWLEDGE = {"kb_brand", "kb_claims", "kb_audiences", "kb_objections",
             "kb_situations", "kb_entities", "kb_unknowns", "kb_conflicts",
             "kb_embeddings", "harvested_pages", "kb_assets"}
# `kb_assets` was added with the creative library and classified nowhere, so the
# unclassified report named it for weeks and a knowledge reset left an account's
# entire picture library behind while reporting success — the `kb_brand` /
# `kb_brands` near-miss above, arrived at from the other direction.
#
# Knowledge, because the library is rebuilt by a crawl and a catalogue sync,
# which is what this group means. ONE THING IS LOST BY SAYING SO: `uses`,
# `last_used_at` and the per-channel results from `record_asset_outcome` live on
# the same row, they are the only record of which creative worked, and nothing
# can rebuild them. That is a table doing two jobs rather than a bad grouping —
# splitting outcomes into their own rows is the real fix and is not done here.

#: Tables that hold what the account DID. Conversations, outputs, mail,
#: documents, logistics. Rebuildable only from the source systems, and some of
#: it not at all.
OPERATIONS = {"conversations", "touches", "commitments", "outputs",
              "approvals", "email_log", "contacts", "deadlines", "shipments",
              "rfqs", "expenses", "doc_index", "systems", "system_runs",
              "memories", "lessons", "chat_messages", "usage", "wa_messages",
              "seo_snapshots", "voice_profiles", "follow_ups",
              "seo_site_config", "system_docs", "assurance_events",
              "tool_calls", "reported_figures"}
# `assurance_events` is operations, not knowledge: it records what the system
# DID — which drafts were checked and what was caught — and no crawl or sync
# can rebuild it. Classified in the same change that added the table, because
# the unclassified report caught it one commit after it caught `kb_assets`,
# which is the point of deriving the list from the schema.

#: Deleting these makes work for the CLIENT, not for you. Opt in explicitly.
# `users` is NOT here: it has `tenant_key`, not `tenant`, so it is not
# discovered — and deleting a client's login is a separate decision from
# clearing their data anyway.
ACCESS = {"credentials", "connect_links", "intake_links"}

GROUPS = {"knowledge": KNOWLEDGE, "operations": OPERATIONS, "access": ACCESS}


def _tenant_models() -> dict[str, object]:
    """Every model carrying a tenant column, discovered from the schema.

    Derived rather than listed for the same reason `test_tenant_isolation`
    walks the schema: the next model somebody adds is the one a literal list
    would miss, and it would be missed silently.
    """
    out = {}
    for name in dir(db):
        obj = getattr(db, name)
        if not (inspect.isclass(obj) and hasattr(obj, "__tablename__")):
            continue
        if obj is getattr(db, "Base", None):
            continue
        cols = {c.name for c in obj.__table__.columns}
        if "tenant" in cols:
            out[obj.__tablename__] = obj
    return out


def preview(tenant: str, groups: tuple[str, ...] = ("knowledge", "operations")
            ) -> dict:
    """What a reset would delete, per table, without deleting it."""
    return _run(tenant, groups, apply=False)


def reset(tenant: str, groups: tuple[str, ...] = ("knowledge", "operations"),
          apply: bool = False) -> dict:
    return _run(tenant, groups, apply=apply)


def _run(tenant: str, groups, apply: bool) -> dict:
    tenant = (tenant or "").strip()
    if not tenant:
        return {"error": "name an account. An empty tenant is UNASSIGNED — "
                         "the marker for rows whose owner could not be "
                         "determined — and deleting on it would erase every "
                         "unattributed row in the system."}
    from . import tenants
    if not tenants.get(tenant):
        return {"error": f"unknown account {tenant!r}. Nothing was touched."}

    wanted: set[str] = set()
    for g in groups:
        if g not in GROUPS:
            return {"error": f"unknown group {g!r}. "
                             f"Known: {', '.join(sorted(GROUPS))}"}
        wanted |= GROUPS[g]

    models = _tenant_models()
    # A table carrying `tenant` that no group claims is reported rather than
    # quietly skipped: the point of deriving the list is to notice these.
    unclassified = sorted(set(models) - KNOWLEDGE - OPERATIONS - ACCESS)

    counts, deleted = {}, 0
    with db.SessionLocal() as s:
        for table in sorted(wanted & set(models)):
            model = models[table]
            q = s.query(model).filter(model.tenant == tenant)
            n = q.count()
            if not n:
                continue
            counts[table] = n
            deleted += n
            if apply:
                q.delete(synchronize_session=False)
        if apply:
            s.commit()

    return {
        "tenant": tenant,
        "applied": bool(apply),
        "groups": list(groups),
        "rows": counts,
        "total": deleted,
        "tenant_row_kept": True,
        "unclassified_tables": unclassified,
        "note": (
            "nothing was deleted — add apply=1 to do it" if not apply else
            f"deleted {deleted} rows across {len(counts)} tables"),
        "warning": (
            "credentials were NOT touched — deleting those makes your CLIENT "
            "redo OAuth. Add the 'access' group deliberately if that is what "
            "you want." if "access" not in groups else
            "credentials WERE included — this client will have to reconnect "
            "every tool."),
    }
