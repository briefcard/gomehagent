"""Dress rehearsal, IN THE GATE: run every system offline against every seeded account and READ what it produces.

Not a test — a report — but it exits non-zero on anything a suite would never
see and a client would: a crash, a bare KeyError in a note, a Python
identifier in a client-facing string, a page that 500s. Built the night before
a client presentation, when every suite was green and the images were not
being made; the pass line was true and the artifacts were not read.

    python3 scripts/test_rehearse.py           # everything, every seeded account
    python3 scripts/test_rehearse.py --only skills   # skills | pages | decisions | jobs | surfaces
    python3 scripts/test_rehearse.py --accounts baci,ironside

Model, ESP, CMS, image and network calls are stubbed with the suites' own
seams; what is exercised is every gate, refusal, note, artifact shape, approval
payload, executor and scheduled job, across accounts in different states.
"""
import argparse, importlib.util, json, os, re, sys, tempfile, traceback

os.environ.setdefault("DATABASE_URL", f"sqlite:///{tempfile.mkdtemp()}/rehearse.db")
os.environ.setdefault("APPROVAL_SECRET", "s3cret")
os.environ.setdefault("SEO_SITES_JSON", "{}")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import httpx  # noqa: E402


class NoNetwork(RuntimeError):
    pass


def _no(*a, **k):
    raise NoNetwork("network disabled in rehearsal")


httpx.get = httpx.post = httpx.put = httpx.delete = _no

from app import (approvals, client_report, db, digest, gmail_client, imagegen, kb, kb_seed,  # noqa: E402
                 llm, planner, portal_ui, skill, skill_pack, systems, tenants, whatsapp, worker)

LEAKS = (r"Traceback", r"KeyError", r"AttributeError", r"NoneType", r">None<", r"\?: ",
         r"SystemRun\.", r"systems\.CATALOG", r"\{\{", r"build map step")
PROBLEMS: list[str] = []


def problem(where: str, what: str) -> None:
    PROBLEMS.append(f"{where}: {what}")


def leaks(text: str) -> list[str]:
    return [p for p in LEAKS if re.search(p, text or "")]


def _stub_world() -> None:
    """The suites' own seams, in one place."""
    spec = importlib.util.spec_from_file_location("tce", os.path.join(ROOT, "scripts", "test_campaign_email.py"))
    tce = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tce)
    _all = {c: True for c in tenants.CAPABILITIES}
    tenants.capabilities = lambda k: dict(_all)
    llm.ask = lambda purpose, prompt, **k: llm.Reply(
        text='{"headline":"Made for the table","primary":"Designed in Milan.","description":"Italian-designed tableware.",'
             '"variants":[{"headline":"Made for the table","primary":"Designed in Milan.","description":"For every table."}]}',
        ok=True, purpose=purpose)
    skill_pack._draft_article_live = lambda *a, **k: (
        "<h1>Guide</h1><h2>Why it matters</h2><p>Designed in Milan and used in leading hotels.</p>"
        "<!--IMAGE: the table set--><h2>How to choose</h2><p>Pick the set that fits the table.</p>", "")
    imagegen.plate = lambda *a, **k: {"ok": True, "image": b"\x89PNG\r\n\x1a\n" + b"0" * 64, "prompt": "plate"}
    gmail_client.send_email = lambda alias, to, subject, body, thread_id=None, html=None, cc="": "m1"
    gmail_client.send_draft = lambda alias, draft_id: "m2"
    gmail_client.read_draft = lambda alias, draft_id: {"body": "as sent"}
    whatsapp.send_text = lambda *a, **k: None
    tce._fake_esp()
    return tce


PARAMS = {
    "blog_article": lambda t: {"keyword": "corporate event venues miami" if t == "ironside" else "aqua pitcher set"},
    "campaign_email": lambda t: {"segment": "reorder_due"},
    "inbound_reply": lambda t: {"utterance": "Is the aqua pitcher dishwasher safe?", "draft_with_model": True},
    "lead_reply": lambda t: {"utterance": "Can you host 200 for dinner in November?", "draft_with_model": True},
    "weekly_report": lambda t: {"to": "client@example.com"},
}


def _install_all(tenant: str) -> None:
    for key in systems.CATALOG:
        row = systems.find(tenant, key) or systems.create(tenant, key)
        with db.SessionLocal() as s:
            s.get(db.System, row.id).status = "live"
            s.commit()


def rehearse_skills(accounts, tce) -> list[dict]:
    out = []
    for tenant in accounts:
        _install_all(tenant)
        if tenant == "baci":
            tce._seed_live("baci")
        for sk_key, sk in sorted(skill.REGISTRY.items()):
            params = PARAMS.get(sk_key, lambda t: {})(tenant)
            line = {"tenant": tenant, "skill": sk_key, "system": sk.system_key}
            try:
                got = skill.run(sk_key, tenant, **params)
                line.update(status=got.get("status"), blocked_on=(got.get("blocked_on") or [])[:3],
                            notes=[str(n)[:120] for n in (got.get("notes") or [])[:4]],
                            items=len(got.get("items") or []))
                for txt in line["blocked_on"] + line["notes"]:
                    for p in leaks(txt):
                        problem(f"{tenant}/{sk_key}", f"leak {p!r} in: {txt[:90]}")
                items = got.get("items") or []
                if items:
                    it = items[0]; body = str(it.get("body") or ""); meta = it.get("meta") or {}
                    line["artifact"] = {"chars": len(body), "h2": body.count("<h2"), "img": body.count("<img"),
                                        "markers_left": body.count("<!--IMAGE"), "subject": (meta.get("subject") or "")[:60]}
            except NoNetwork as e:
                problem(f"{tenant}/{sk_key}", f"would call the network: {e}")
                line["status"] = "NETWORK"
            except Exception as e:
                problem(f"{tenant}/{sk_key}", f"crashed: {e.__class__.__name__}: {str(e)[:100]}")
                line["status"] = f"EXCEPTION {e.__class__.__name__}"
            out.append(line)
        for key, fn in planner.PLANNERS.items():
            try:
                r = fn(systems.find(tenant, key)); out.append({"tenant": tenant, "planner": key, "result": {k: v for k, v in r.items() if k != "weeks"}})
            except Exception as e:
                problem(f"{tenant}/planner {key}", f"crashed: {e.__class__.__name__}: {str(e)[:100]}")
        try:
            msg = client_report.render_email(client_report.assemble(tenant, 7))
            for p in leaks(msg["text"]):
                problem(f"{tenant}/report email", f"leak {p!r}")
            out.append({"tenant": tenant, "report_subject": msg["subject"]})
        except Exception as e:
            problem(f"{tenant}/report email", f"crashed: {e.__class__.__name__}: {str(e)[:100]}")
    return out


def rehearse_decisions(accounts) -> list[dict]:
    out = []
    with db.SessionLocal() as s:
        pend = [(a.id, a.kind, a.tenant, (a.summary or "")[:50]) for a in s.query(db.Approval)
                .filter(db.Approval.status == "pending").all() if not accounts or a.tenant in accounts or not a.tenant]
    for ap_id, kind, tenant, summ in pend:
        try:
            said = approvals.apply_decision(ap_id, "approved")
        except Exception as e:
            said = f"EXCEPTION {e.__class__.__name__}: {str(e)[:100]}"
            problem(f"{tenant}/approve {kind}", said)
        for p in leaks(said):
            problem(f"{tenant}/approve {kind}", f"leak {p!r} in: {said[:90]}")
        out.append({"tenant": tenant, "kind": kind, "summary": summ, "said": said[:140]})
    return out


def rehearse_jobs() -> list[dict]:
    out = []
    src = open(os.path.join(ROOT, "app", "worker.py")).read()
    for name in re.findall(r"sched\.add_job\(_safe\(([\w.]+),", src):
        if name.startswith("ops_jobs.JOBS"):
            continue
        mod, _, fn = name.rpartition(".")
        try:
            obj = importlib.import_module(f"app.{mod}") if mod else worker
            r = getattr(obj, fn)()
            out.append({"job": name, "ok": True, "result": str(r)[:100]})
        except Exception as e:
            problem(f"job {name}", f"crashed: {e.__class__.__name__}: {str(e)[:100]}")
            out.append({"job": name, "ok": False, "error": f"{e.__class__.__name__}: {str(e)[:100]}"})
    return out


def rehearse_pages(accounts) -> list[dict]:
    from fastapi.testclient import TestClient
    from app import admin_ui, web
    c = TestClient(web.app, raise_server_exceptions=False)
    tabs = [t for t, *_ in admin_ui._TABS]
    subs = {"plan": [v for v, _ in getattr(admin_ui, "PLAN_SUBS", [])], "content": ["pictures", "drafts"]}
    out = []
    for tenant in accounts:
        for tab in tabs:
            for sub in [""] + subs.get(tab, []):
                url = f"/admin/ui?key={os.environ['APPROVAL_SECRET']}&tab={tab}&tenant={tenant}" + (f"&sub={sub}" if sub else "")
                r = c.get(url)
                hits = leaks(r.text)
                if r.status_code != 200 or hits:
                    problem(f"{tenant}/page {tab}/{sub or '-'}", f"status {r.status_code} leaks {hits}")
                out.append({"tenant": tenant, "tab": tab, "sub": sub, "status": r.status_code, "leaks": hits})
    return out


def rehearse_surfaces(accounts) -> list[dict]:
    out = []
    for tenant in accounts:
        for tab in ("overview", "report", "work"):
            try:
                html = portal_ui.render(tenant, tab, 30)
                for p in leaks(html):
                    problem(f"{tenant}/portal {tab}", f"leak {p!r}")
                out.append({"tenant": tenant, "portal": tab, "chars": len(html)})
            except Exception as e:
                problem(f"{tenant}/portal {tab}", f"crashed: {e.__class__.__name__}: {str(e)[:100]}")
    try:
        html = digest.build_digest(12)
        for p in leaks(html):
            problem("digest", f"leak {p!r}")
        out.append({"digest": len(html)})
    except Exception as e:
        problem("digest", f"crashed: {e.__class__.__name__}: {str(e)[:100]}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="skills|pages|decisions|jobs|surfaces")
    ap.add_argument("--accounts", default="", help="comma-separated tenant keys (default: every seeded)")
    ap.add_argument("--out", default="", help="write the full report as JSON here")
    a = ap.parse_args()
    db.init_db(); tenants.seed(); kb_seed.seed_all()
    tce = _stub_world()
    accounts = [x for x in a.accounts.split(",") if x] or [t.key for t in tenants.all_tenants()]
    want = {a.only} if a.only else {"skills", "pages", "decisions", "jobs", "surfaces"}
    report: dict = {"accounts": accounts}
    if "skills" in want:
        report["skills"] = rehearse_skills(accounts, tce)
    if "decisions" in want:
        report["decisions"] = rehearse_decisions(accounts)
    if "jobs" in want:
        report["jobs"] = rehearse_jobs()
    if "pages" in want:
        report["pages"] = rehearse_pages(accounts)
    if "surfaces" in want:
        report["surfaces"] = rehearse_surfaces(accounts)
    report["problems"] = PROBLEMS
    if a.out:
        json.dump(report, open(a.out, "w"), indent=1, default=str)
    for line in report.get("skills", []):
        if line.get("skill"):
            print(f"{line['tenant']:10} {line['skill']:22} {str(line.get('status')):10} {' | '.join(line.get('blocked_on') or line.get('notes') or [])[:110]}")
    for j in report.get("jobs", []):
        if not j["ok"]:
            print(f"JOB {j['job']}: {j['error']}")
    print()
    print(f"accounts: {', '.join(accounts)} · problems: {len(PROBLEMS)}")
    for p in PROBLEMS:
        print("  -", p)
    print("PASS" if not PROBLEMS else "FAILED")
    return 1 if PROBLEMS else 0


if __name__ == "__main__":
    raise SystemExit(main())
