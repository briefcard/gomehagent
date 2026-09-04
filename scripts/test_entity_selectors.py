"""Every entity picker is a select fed from the entity table, and every write
that carries an entity key refuses one the table does not have.

Owner, 2026-09-04: "All the Entity selectors should be drop downs … in ad
creative, email, etc we should not have to know the slug. It should sync with
the entity table and make sure to associate them." Two halves, and both are
COMPUTED here rather than surveyed by eye:

  · the OFFER — no console surface renders an entity as a text box, and every
    option a picker offers is a key the table holds now. Walked: every tab of
    the console for every seeded account, plus the plan form of every system
    that declares an entity field;
  · the ASSOCIATION — the plan declarations (`kind="entity"` is what both the
    picker and `_check_plan_refs` key on), the plan writer, and the objection
    writer all refuse a key that is not in the table, and file a real one.

The ad-creative plan form started this: its field declared no `kind`, so it
drew a bare text box AND the reference check skipped it — two halves of one
contract, missing together.

Run: python3 scripts/test_entity_selectors.py
"""
import os
import pathlib
import re
import sys
import tempfile
from urllib.parse import unquote

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'es.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = pathlib.Path(__file__).resolve().parent.parent
KEY = "s3cret"

from app import admin_ui, db, kb, kb_seed, systems, tenants, web  # noqa: E402

_fail: list[str] = []


def ck(label: str, cond: bool, detail: str = "") -> None:
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    db.init_db()
    tenants.seed()
    kb_seed.seed_all()
    with db.SessionLocal() as s:
        accounts = sorted(t.key for t in s.query(db.Tenant).all())

    print("— 1. declarations: a plan field that names an entity says so —")
    offenders = []
    for k, sp in systems.CATALOG.items():
        for f in (sp.get("workflow") or {}).get("plan_fields") or ():
            if f["key"] == "entity_key" and f.get("kind") != "entity":
                offenders.append(f"{k}.entity_key")
            if f["key"] == "entity_keys" and f.get("kind") != "entity_list":
                offenders.append(f"{k}.entity_keys")
    ck("every plan field keyed entity_key / entity_keys declares its kind — "
       "the picker AND the reference check both key on it",
       not offenders, str(offenders))

    print("\n— 2. the source: no entity text box, no entity datalist —")
    src = (ROOT / "app" / "admin_ui.py").read_text()
    boxes = re.findall(r'<input[^>]*name="entity_key"', src)
    lists = re.findall(r'<datalist id="(?:ents|objents|pents)"', src)
    ck("admin_ui.py renders no <input name=\"entity_key\"> and no entity "
       "datalist", not boxes and not lists,
       f"{len(boxes)} text box(es), {len(lists)} datalist(s)")

    print("\n— 3. every console page, every account: pickers are selects "
          "synced to the table —")
    from fastapi.testclient import TestClient
    c = TestClient(web.app, raise_server_exceptions=False)
    ent_systems = sorted(
        k for k, sp in systems.CATALOG.items()
        if any(f["key"] in ("entity_key", "entity_keys")
               for f in (sp.get("workflow") or {}).get("plan_fields") or ()))
    rich = max(accounts,
               key=lambda t: len(kb.entities(t, available_only=False)))
    for k in ent_systems:
        row = systems.find(rich, k) or systems.create(rich, k)
        with db.SessionLocal() as s:
            s.get(db.System, row.id).status = "live"
            s.commit()
    tabs = [t for t, *_ in admin_ui._TABS]
    subs = {"plan": [v for v, _ in getattr(admin_ui, "PLAN_SUBS", [])],
            "content": ["pictures", "drafts", "other", "queue"],
            "kb": ["objections", "claims", "audiences", "entities"]}
    urls: list[tuple[str, str]] = []
    for t in accounts:
        for tab in tabs:
            for sub in [""] + subs.get(tab, []):
                urls.append((t, f"/admin/ui?key={KEY}&tab={tab}&tenant={t}"
                             + (f"&sub={sub}" if sub else "")))
    plan_urls = {k: f"/admin/ui?key={KEY}&tab=systems&tenant={rich}"
                    f"&system={k}&wf=planned" for k in ent_systems}
    urls += [(rich, u) for u in plan_urls.values()]

    keys_of = {t: {e.key for e in kb.entities(t, available_only=False)}
               for t in accounts}
    bad_inputs, bad_opts, n_pickers, per_url, offered = [], [], 0, {}, set()
    for t, url in urls:
        html = c.get(url).text
        for m in re.finditer(r'<input(?![^>]*type="(?:checkbox|hidden)")'
                             r'[^>]*name="entity_keys?"[^>]*>', html):
            bad_inputs.append((url[:70], m.group(0)[:80]))
        sels = re.findall(r'<select name="entity_keys?"[^>]*>(.*?)</select>',
                          html, re.S)
        per_url[url] = len(sels)
        n_pickers += len(sels)
        for body in sels:
            for v, lab in re.findall(r'<option value="([^"]*)"[^>]*>([^<]*)',
                                     body):
                if v and v not in keys_of[t]:
                    bad_opts.append((url[:70], v))
                if v:
                    offered.add((t, v, lab))
    ck(f"no page renders an entity as a text box ({len(urls)} pages walked)",
       not bad_inputs, str(bad_inputs[:3]))
    ck(f"every option every picker offers is a key the table holds now "
       f"({n_pickers} pickers)", n_pickers > 0 and not bad_opts,
       str(bad_opts[:3]))
    for k in ent_systems:
        ck(f"{k}'s plan form offers the catalogue in a select",
           per_url.get(plan_urls[k], 0) >= 1,
           f"{per_url.get(plan_urls[k])} pickers")
    ent = sorted(kb.entities(rich, available_only=False),
                 key=lambda e: e.name)[0]
    ck("the picker names the entity, not its slug",
       (rich, ent.key, admin_ui._esc(ent.name)) in offered,
       f"{ent.key!r} shown as {ent.name!r}?")

    print("\n— 4. association: a ghost key is refused, a real one associates —")
    out = systems.open_plan(rich, "ad_creative", ref="entpick:1")
    ck("an ad plan opens", bool(out.get("run_id")), str(out)[:120])
    err = systems.save_plan(out["run_id"],
                            {"entity_key": "ghost-product"}).get("error") or ""
    ck("an ad plan refuses an entity the table lacks — at plan time, by name",
       "unknown entity 'ghost-product'" in err, err[:100])
    ck("…and associates a real one",
       systems.save_plan(out["run_id"], {"entity_key": ent.key}).get("ok")
       is True)
    also = systems.save_plan(out["run_id"], {"entity_keys":
                                             f"{ent.key}, ghost-2"}
                             ).get("error") or ""
    ck("the several-entities field is checked the same way",
       "unknown entity 'ghost-2'" in also, also[:100])

    # The multi-select submits one value per pick; the plan reader joins them
    # the way `systems.entity_list` reads them — through the real route.
    others = [e.key for e in kb.entities(rich, available_only=False)
              if e.key != ent.key]
    picks = [ent.key] + others[:1]
    q = "&".join(f"entity_keys={p}" for p in picks)
    c.get(f"/admin/plan_new?key={KEY}&tenant={rich}&system=blog"
          f"&keyword=entity-pick-check&{q}", follow_redirects=False)
    blog_row = systems.find(rich, "blog")
    with db.SessionLocal() as s:
        filed = [r for r in s.query(db.SystemRun)
                 .filter(db.SystemRun.system_id == blog_row.id).all()
                 if ((r.brief or {}).get("plan") or {}).get("keyword")
                 == "entity-pick-check"]
        stored = ((filed[0].brief or {}).get("plan") or {}).get("entity_keys") \
            if filed else None
    ck("a multi-select's picks reach the plan as the list the run reads",
       filed and systems.entity_list(stored) == picks,
       f"stored={stored!r} picks={picks}")

    before = len(kb.objections(rich, any_entity=True))
    r = c.post(f"/admin/objection_add?key={KEY}",
               data={"tenant": rich, "objection": "Does it ship flat?",
                     "response": "Yes, in a sleeve.",
                     "entity_key": "ghost-product"},
               follow_redirects=False)
    where = unquote(r.headers.get("location") or "")
    ck("an objection typed against an unknown entity is refused by name — "
       "through the route, not the writer",
       r.status_code in (302, 303) and "no entity matches" in where
       and len(kb.objections(rich, any_entity=True)) == before,
       where[:120])
    c.post(f"/admin/objection_add?key={KEY}",
           data={"tenant": rich, "objection": "Does it ship flat?",
                 "response": "Yes, in a sleeve.", "entity_key": ent.key},
           follow_redirects=False)
    got = [o for o in kb.objections(rich, any_entity=True)
           if o.objection == "Does it ship flat?"]
    ck("…and a real one lands associated with that entity",
       len(got) == 1 and got[0].entity_key == ent.key,
       str([(o.entity_key) for o in got]))

    print()
    if _fail:
        print(f"{len(_fail)} FAILED:")
        for f in _fail:
            print(f"  - {f}")
        return 1
    print("all checks passed — every entity is picked from the table, and "
          "every write refuses one it does not hold")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
