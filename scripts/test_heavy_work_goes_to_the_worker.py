"""Every heavy operation goes to the worker — read off the code, and pressed.

Owner, 2026-10-01: "When I press 'Revise' does it queue it back with the
worker as it should? This needs to be the approach with every single heavy
operation." It did not. Revise ran the whole skill inside the request — a
campaign email is minutes of model calls and renders — on the web service;
four more presses did a model's or an image model's work in the request, and
two threads inside the web service ran the operations sweeps and every
message to the assistant.

What this suite holds shut:

  · READ OFF THE CODE: no route reaches a model call, a browser render, a
    drawn picture or a whole skill run, through any depth of the app's own
    functions — the call graph is built from every module and walked. A
    route that grows one fails here, by name and by the path it takes.
  · No thread, task or background job is started inside the web service.
  · PRESSED: each of the seven queues its job and does none of the work —
    the heavy function is booby-trapped and never called — and what must
    be said at once (a refusal, the note) is said or kept at once.
  · The assistant's messages run one at a time, in order, across instances,
    and for the owner's account whatever its state; a typed message carries
    its chat id to the worker (the UnboundLocalError it used to hit).

    python3 scripts/test_heavy_work_goes_to_the_worker.py
"""
from __future__ import annotations

import ast
import json
import os
import pathlib
import sys
import tempfile
from urllib.parse import unquote

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'heavy.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["SEO_SITES_JSON"] = "{}"
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app import db, jobs, tenants, web  # noqa: E402

KEY = "s3cret"
_fail: list = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


# --- the call graph ----------------------------------------------------------
#: What makes an operation HEAVY: a model call, a browser render, a picture
#: drawn by an image model (their one network call each), a whole skill run.
PRIMITIVES = {"llm.call", "llm.ask", "shots._shoot", "shots.shoot", "shots.shoot_fragment",
              "skill.run", "imagegen._post", "gemini_images._post"}


#: A model's endpoint called past `llm` — the SDKs' own methods.
DIRECT = ("messages.create(", "messages.stream(", "chat.completions.create(", "responses.create(",
          "images.generate(", "images.edit(", "generate_content(")


def call_graph() -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {}
    for path in (ROOT / "app").glob("*.py"):
        mod = path.stem
        tree = ast.parse(path.read_text())
        top = {}
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.level == 1:
                for a in node.names:
                    top[a.asname or a.name] = f"{node.module}.{a.name}" if node.module else a.name
        defs = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                defs.setdefault(node.name, node)
        src = path.read_text()
        for name, fn in defs.items():
            alias = dict(top)
            for n in ast.walk(fn):
                if isinstance(n, ast.ImportFrom) and n.level == 1:
                    for a in n.names:
                        alias[a.asname or a.name] = f"{n.module}.{a.name}" if n.module else a.name
            out = set()
            for n in ast.walk(fn):
                if not isinstance(n, ast.Call):
                    continue
                f = n.func
                if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
                    base = alias.get(f.value.id)
                    if base and "." not in base:
                        out.add(f"{base}.{f.attr}")
                elif isinstance(f, ast.Name):
                    if f.id in defs:
                        out.add(f"{mod}.{f.id}")
                    elif f.id in alias and "." in alias[f.id]:
                        out.add(alias[f.id])
            # A MODEL CALLED DIRECTLY, past `llm` — the agent kernel's own
            # Anthropic client, an SDK's chat or image endpoint — is a model call
            body = ast.get_source_segment(src, fn) or ""
            if any(t in body for t in DIRECT):
                out.add("llm.call")
            graph[f"{mod}.{name}"] = out
    return graph


def heavy_set(graph: dict) -> set[str]:
    heavy = set(PRIMITIVES)
    grew = True
    while grew:
        grew = False
        for k, outs in graph.items():
            if k not in heavy and outs & heavy:
                heavy.add(k)
                grew = True
    return heavy


def path(graph: dict, heavy: set, start: str) -> list[str]:
    from collections import deque
    q, seen = deque([[start]]), {start}
    while q:
        p = q.popleft()
        if p[-1] in PRIMITIVES and len(p) > 1:
            return p
        for nx in sorted(graph.get(p[-1], ())):
            if nx in heavy and nx not in seen:
                seen.add(nx)
                q.append(p + [nx])
    return [start]


#: Routes the reading flags for a model path they never take — each PROVEN
#: light below by pressing it with that path booby-trapped, never taken on
#: trust. `responder.answer` drafts with a model only when asked to.
LIGHT_BY_DEFAULT = {"GET /admin/answer"}


def routes() -> list[tuple[str, str]]:
    tree = ast.parse((ROOT / "app" / "web.py").read_text())
    out = []
    for fn in tree.body:
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for d in fn.decorator_list:
            if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                    and isinstance(d.func.value, ast.Name) and d.func.value.id == "app"):
                where = d.args[0].value if d.args and isinstance(d.args[0], ast.Constant) else "?"
                out.append((f"{d.func.attr.upper()} {where}", fn.name))
    return out


def main() -> int:
    db.init_db()
    tenants.seed()
    c = TestClient(web.app)

    print("— read off the code: no route reaches heavy work —")
    graph = call_graph()
    heavy = heavy_set(graph)
    ck("the reading can see heavy work — a redraft is a skill run, a winning look a model call",
       {"skill_pack.redraft_artifact", "creative.learn_winning_look", "pictures.read_pictures",
        "articles.read_pattern", "creative.generate", "commands.job", "kernel.run",
        "creative.winning_look_job"} <= heavy,
       "a graph that finds nothing heavy would pass every route")
    reached = [(r, fn, path(graph, heavy, f"web.{fn}")) for r, fn in routes()
               if f"web.{fn}" in heavy and r not in LIGHT_BY_DEFAULT]
    ck(f"none of the {len(routes())} routes reaches a model, a browser, a drawn picture or a skill run",
       not reached, "; ".join(f"{r} via {' > '.join(p[1:4])}" for r, _fn, p in reached[:6]))
    started = [(f, n) for f in ("web.py", "admin_ui.py", "portal.py") if (ROOT / "app" / f).exists()
               for n in ("threading.Thread(", "Thread(target", "create_task(", "BackgroundTasks",
                         "ThreadPoolExecutor", "run_in_executor")
               if n in (ROOT / "app" / f).read_text()]
    ck("nothing is started in the background inside the web service", not started, str(started))
    for k in ("redraft", "article_picture", "pictures_read", "article_layout", "winning_look",
              "ops_job", "command"):
        ck(f"  the {k} job has a door in the worker", callable(jobs._resolve(jobs.KINDS[k]["target"])))

    print("\n— pressed: each queues its job and does none of the work —")
    from app import articles, creative, ops_jobs, pictures, skill_pack
    trapped: list = []

    def _trap(name):
        def _never(*a, **k):
            trapped.append(name)
            raise AssertionError(f"{name} ran inside the request")
        return _never
    for mod, name in ((skill_pack, "redraft_artifact"), (creative, "generate"),
                      (creative, "learn_winning_look"), (pictures, "read_pictures"),
                      (articles, "read_pattern")):
        setattr(mod, name, _trap(name))
    for name in list(ops_jobs.JOBS):
        ops_jobs.JOBS[name] = _trap(f"ops:{name}")

    def queued(kind, tenant=None):
        with db.SessionLocal() as s:
            q = s.query(db.JobQueue).filter(db.JobQueue.kind == kind, db.JobQueue.state == "queued")
            if tenant:
                q = q.filter(db.JobQueue.tenant == tenant)
            return [dict(r.payload or {}) for r in q.all()]

    with db.SessionLocal() as s:
        out = db.Output(tenant="baci", status="awaiting_approval", body="An email.", destination="")
        s.add(out); s.flush()
        s.add(db.ArtifactBody(output_id=out.id, tenant="baci", format="campaign_email", system_key="campaign_email",
                              body="<p>An email.</p>", meta={"keyword": "italian tableware"}))
        s.add(db.KeywordTarget(tenant="baci", phrase="italian tableware", output_id=out.id, status="drafted"))
        s.commit()
        oid = out.id
    r = c.post("/admin/work_redraft", params={"key": KEY}, follow_redirects=False,
               data={"key": KEY, "output_id": oid, "note": "The logo is there twice at the top.",
                     "part": "overall"})
    said = unquote(r.headers.get("location", ""))
    with db.SessionLocal() as s:
        noted = [f.note for f in s.query(db.FeedbackItem).filter(db.FeedbackItem.output_id == oid).all()]
    ck("Revise queues the redraft and returns at once — the skill never runs in the request",
       r.status_code == 303 and [p.get("output_id") for p in queued("redraft")] == [oid]
       and "redraft_artifact" not in trapped and "queued" in said, said[-160:])
    ck("  the note is filed at the press, so it outlives the queue",
       noted == ["The logo is there twice at the top."], str(noted))
    c.post("/admin/work_redraft", params={"key": KEY}, follow_redirects=False,
           data={"key": KEY, "output_id": oid, "note": "", "part": "overall"})
    ck("  pressed twice, it is one job", len(queued("redraft")) == 1)
    with db.SessionLocal() as s:
        s.get(db.Output, oid).destination = "omnisend:campaign/123"
        s.commit()
    r = c.post("/admin/work_redraft", params={"key": KEY}, follow_redirects=False,
               data={"key": KEY, "output_id": oid, "note": "", "part": "overall"})
    ck("  a draft that cannot be redrafted is refused at the press, not minutes later on the Queue",
       "already pushed to the ESP" in unquote(r.headers.get("location", "")) and len(queued("redraft")) == 1)

    r = c.post("/admin/article_picture", params={"key": KEY}, follow_redirects=False,
               data={"key": KEY, "output_id": oid})
    ck("drawing an article's picture is queued, nothing drawn in the request",
       [p.get("output_id") for p in queued("article_picture")] == [oid] and "generate" not in trapped,
       unquote(r.headers.get("location", ""))[-160:])
    r = c.post("/admin/pictures_read", params={"key": KEY}, follow_redirects=False,
               data={"key": KEY, "tenant": "baci"})
    ck("reading the pictures is queued", len(queued("pictures_read", "baci")) == 1 and "read_pictures" not in trapped)
    r = c.post("/admin/article_layout", params={"key": KEY}, follow_redirects=False,
               data={"key": KEY, "tenant": "baci", "url": "https://example.com/an-article"})
    ck("reading an article's layout is queued",
       [p.get("url") for p in queued("article_layout", "baci")] == ["https://example.com/an-article"]
       and "read_pattern" not in trapped)
    r = c.post("/admin/ad_winning_look", params={"key": KEY}, follow_redirects=False,
               data={"key": KEY, "tenant": "baci"})
    ck("learning the winning look is queued", len(queued("winning_look", "baci")) == 1
       and "learn_winning_look" not in trapped)
    r = c.get("/admin/run/doc_sweep", params={"key": KEY})
    st = c.get("/admin/status", params={"key": KEY}).json()
    ck("an operations sweep is queued for the worker, and its status is read off the queue",
       r.json().get("status") == "doc_sweep queued" and [p.get("job") for p in queued("ops_job")] == ["doc_sweep"]
       and not any(t.startswith("ops:") for t in trapped)
       and st.get("results", {}).get("doc_sweep", {}).get("state") == "queued", f"{r.json()} {st}")

    print("\n— the owner's diagnostics: queued, and answered whole —")
    from app import probes, responder
    responder._draft = _trap("responder._draft")
    r = c.get("/admin/answer", params={"key": KEY, "tenant": "baci", "q": "do you ship to Canada?"})
    ck("/admin/answer makes no model call — the route the reading lets through, pressed",
       r.status_code == 200 and "responder._draft" not in trapped, str(r.json())[:120])
    asked = c.get("/admin/ask", params={"key": KEY, "q": "where are our quick wins?", "role": "seo"}).text
    voice_ = c.get("/admin/propose_voice", params={"key": KEY, "tenant": "baci"}).json()
    rehearse = c.get("/admin/draft_test", params={"key": KEY, "tenant": "baci", "pick": "order"}).json()
    vocab = c.get("/admin/vocabulary", params={"key": KEY, "tenant": "baci", "model": "1"}).json()
    sweep_ = c.get("/admin/sweep", params={"key": KEY, "run": "1"}).json()
    names = sorted(p.get("name") for p in queued("probe"))
    ck("ask, the sweep, the voice, the rehearsal and the model's vocabulary pass are each queued",
       names == ["ask", "draft_test", "propose_voice", "sweep", "vocabulary"]
       and "/admin/probe/" in asked and all("result_at" in x for x in (voice_, rehearse, vocab["model_review"], sweep_)),
       str(names))
    ck("  while the vocabulary's own lexical checks still answer at once",
       "overlaps" in vocab and "neighbours" in vocab)
    probes.PROBES["propose_voice"] = lambda tenant, **k: {"tone": ["warm"], "tenant": tenant, "limit": k.get("limit")}
    with db.SessionLocal() as s:
        for row in s.query(db.JobQueue).filter(db.JobQueue.kind != "probe").all():
            row.state = "done"
        s.commit()
    pid = voice_["queued"]
    with db.SessionLocal() as s:
        for row in s.query(db.JobQueue).filter(db.JobQueue.kind == "probe", db.JobQueue.id != pid).all():
            row.state = "done"
        s.query(db.JobQueue).filter(db.JobQueue.id == pid).update({"state": "running", "holder": "t"})
        s.commit()
    jobs.run_one(pid)
    got = c.get(f"/admin/probe/{pid}", params={"key": KEY}).json()
    ck("the worker's answer is kept whole and read back at its address",
       got.get("state") == "done" and got.get("result") == {"tone": ["warm"], "tenant": "baci", "limit": 25},
       str(got)[:200])

    print("\n— the assistant's messages: queued, in order, with their chat —")
    web._handle_command("draft an email for baci", chat_id="12345")
    msgs = queued("command")
    ck("a typed message is queued for the worker with its chat id",
       [(m.get("kind"), m.get("payload"), m.get("chat_id")) for m in msgs]
       == [("text", "draft an email for baci", "12345")], str(msgs))
    web._handle_command("and one for eien", chat_id="12345")
    with db.SessionLocal() as s:
        for row in s.query(db.JobQueue).filter(db.JobQueue.kind != "command").all():
            row.state = "done"
        s.query(db.Tenant).filter(db.Tenant.key == web.OPS_ACCOUNT).update({"status": "paused"})
        s.commit()
    first = jobs.claim("", "instance-A")
    second = jobs.claim("", "instance-B")
    with db.SessionLocal() as s:
        f_row = s.get(db.JobQueue, first) if first else None
    ck("one message at a time: the next waits while one runs, even on the other instance",
       f_row is not None and f_row.kind == "command" and (f_row.payload or {}).get("payload") == "draft an email for baci"
       and second == "", f"{first} {second}")
    ck("  and the owner's account answers whatever its state", f_row is not None)
    jobs.finish(first, "done")
    nxt = jobs.claim("", "instance-B")
    with db.SessionLocal() as s:
        n_row = s.get(db.JobQueue, nxt) if nxt else None
    ck("  then the next, in the order they were sent",
       n_row is not None and (n_row.payload or {}).get("payload") == "and one for eien")
    from app import command_agent, channel, commands
    heard: list = []
    command_agent.handle = lambda text, tenant="", **k: heard.append((text, tenant)) or "done"
    channel.send_text = lambda text, *a, **k: None
    tenants.active = lambda user: "baci"
    tenants.user_for_chat = lambda chat_id: "gomeh" if chat_id == "12345" else None
    got = commands.job("agency", kind="text", payload="draft an email", chat_id="12345")
    ck("the worker answers a typed message with the account its sender is on — no UnboundLocalError",
       got.get("ok") and heard == [("draft an email", "baci")], f"{got} {heard}")

    print()
    print("ALL GREEN" if not _fail else f"FAILED: {len(_fail)}")
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
