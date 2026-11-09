"""The Overview (INITIATIVE-review-surface Phase 1): what the system read,
what it determined, what people decided, what is missing.

Owner, 2026-11-07: "We need to be able to clearly understand what AI is
crawling and determining, what users are finding, what gaps need filling."

Run: python3 scripts/test_overview.py
"""
import datetime as dt
import os
import sys
import tempfile

os.environ.setdefault("DATABASE_URL", f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'ov.db')}")
os.environ.setdefault("APPROVAL_SECRET", "s3cret")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, kb, kb_seed, tenants  # noqa: E402

_fail: list[str] = []
T = "baci"
SITE = "https://bacimilanousa.com"


def ck(name, ok, detail=""):
    print(f"[{'  ok  ' if ok else ' FAIL '}] {name}" + (f"  — {detail}" if detail and not ok else ""))
    if not ok:
        _fail.append(name)


def page(path, body, title="Page"):
    from app.pipeline import fetch, parse
    html = (f"<html><head><title>{title}</title></head><body><main><h1>{title}</h1>{body}"
            f"<p>{'Filler words for the body. ' * 30}</p></main></body></html>")
    fetch.store(T, SITE + path, html, parse.parse(html)["text_hash"])
    return SITE + path


def claim(text, url, subject=""):
    with db.SessionLocal() as s:
        c = db.KbClaim(tenant=T, claim=text, source=f"stated on {url}", proof_type="data",
                       review="proposed", status="active", origin="crawl", subject=subject)
        s.add(c)
        s.commit()
        return c.id


def main() -> int:
    db.init_db()
    tenants.seed()
    kb_seed.seed_all()
    from app import claim_groups, claim_record as cr, harvest, mcp_server, overview, stages

    # --- the harvest keeps its own account, on apply only ------------------
    fake = {"pages_discovered": 40, "pages_read": 25, "pages_skipped": 9, "pages_unchanged": 6,
            "template_pages_skipped": 3, "pages_needing_render_count": 2, "truncated_page_count": 4,
            "proposed_count": 30, "filed_count": 28, "corroborated_count": 2,
            "dropped_by_reason": {"navigation text": 7}, "not_verbatim_count": 3,
            "rejected_for_banned_claim": ["x"], "write_refused_count": 0,
            "statements_found": 51, "unaccounted_figures": 12, "skipped_examples": []}
    real = harvest._harvest
    harvest._harvest = lambda *a, **k: dict(fake)
    try:
        harvest.harvest(T, apply=False)
        ck("STAGES a dry-run harvest records nothing", not stages.latest(T))
        harvest.harvest(T, apply=True)
    finally:
        harvest._harvest = real
    last = stages.last_of_each(T)
    ck("STAGES an applied harvest keeps a crawl report: in → out, and what was not read and why",
       last.get("crawl", {}).get("in") == 40 and last["crawl"]["out"] == 25
       and last["crawl"]["dropped"].get("needs a browser to read") == 2
       and last["crawl"]["details"].get("partly_read") == 4, str(last.get("crawl")))
    ck("STAGES ... and a read report: claims filed, and what the guards dropped",
       last.get("read", {}).get("out") == 28 and last["read"]["dropped"].get("banned phrase") == 1
       and last["read"]["dropped"].get("not word-for-word on the page") == 3
       and last["read"]["dropped"].get("navigation text") == 7, str(last.get("read")))
    # cost is the usage logged for this account during the run
    with db.SessionLocal() as s:
        s.add(db.Usage(tenant=T, purpose="harvest_extract", model="claude-sonnet-4-6",
                       input_tokens="1000000", output_tokens="0", at=stages.now()))
        s.add(db.Usage(tenant="eien", purpose="harvest_extract", model="claude-sonnet-4-6",
                       input_tokens="1000000", output_tokens="0", at=stages.now()))
        s.commit()
    c = stages.cost_between(T, stages.now() - dt.timedelta(minutes=5))
    ck("STAGES a run's cost is this account's model spend in that window — never another's",
       abs(c - 3.0) < 0.01, str(c))

    # --- record + group reports -------------------------------------------
    cr.set_vocabulary(T, "qa", self_names=["Acme"])
    kb.add_entity(T, "product", "offramp", "Off-ramp",
                  attributes={"match": {"urls": ["/off-ramp"], "words": ["off-ramp"]}})
    u = page("/off-ramp", "<p>Integrate Off-Ramp to 18 + Countries</p>", "Off-ramp")
    b = page("/blog/market", "<p>The stablecoin market processed $33 trillion in 2025.</p>")
    c1 = claim("Integrate Off-Ramp to 18 + Countries", u)
    c2 = claim("Integrate Off-Ramp to 25 + Countries", u)
    c3 = claim("The stablecoin market processed $33 trillion in 2025.", b, subject="market")
    claim("A sentence on a blog nobody has attributed.", b)
    cr.refresh(T)
    claim_groups.rebuild(T, use_embeddings=False)
    last = stages.last_of_each(T)
    ck("STAGES the record stage says what code determined and what it left for a person",
       last.get("record", {}).get("details", {}).get("derived", {}).get("placed on an entity", 0) >= 2
       and "subject left for a person" in last["record"]["dropped"], str(last.get("record")))
    ck("STAGES the group stage reports the groups it found",
       last.get("group", {}).get("out", 0) >= 1, str(last.get("group")))

    # --- the overview ------------------------------------------------------
    o = overview.overview(T)
    gaps = {g["key"]: g for g in o["gaps"]}
    ck("OVERVIEW whose-claim counts include market facts, which skip review",
       o["determined"]["subject"]["market fact (skips review)"] >= 1)
    ck("OVERVIEW a gap for claims nobody has attributed, owned by Claude → Reviewer",
       gaps.get("subject", {}).get("count", 0) >= 1 and "Claude" in gaps["subject"]["owner"])
    ck("OVERVIEW a gap for the account's claims with no statement",
       gaps.get("statement", {}).get("count", 0) >= 2)
    ck("OVERVIEW a gap for inconsistent wording (18+ vs 25+ on one page)",
       gaps.get("inconsistent", {}).get("count", 0) >= 1, str(gaps.keys()))
    ck("OVERVIEW no known answers is a gap, not a zero",
       gaps.get("known", {}).get("missing_flag") is True)
    ck("OVERVIEW an unmeasured automated step says so instead of showing a number",
       o["determined"]["accuracy"]["entity (code)"]["precision"] is None
       and "not measured" in o["determined"]["accuracy"]["entity (code)"]["note"])
    ck("OVERVIEW market facts are shown for a spot check",
       any(m["id"] == c3 for m in o["market_skipped_sample"]))
    ck("OVERVIEW cost is reported for the account", o["cost"].get("est_cost_usd", 0) >= 3.0, str(o["cost"]))
    m = mcp_server.get_overview(T)
    ck("MCP get_overview returns the same overview", m["ok"] and m["gaps"] == o["gaps"])
    ck("MCP get_overview refuses an unknown account", not mcp_server.get_overview("nope")["ok"])

    # --- the console --------------------------------------------------------
    from app import admin_ui
    html = admin_ui.render_content("s3cret", tenant=T, sub="overview")
    ck("CONSOLE Review › Overview renders the four answers",
       all(h in html for h in ("What the system read", "Gaps — what is missing",
                               "What the system determined", "What people decided")))
    ck("CONSOLE every gap row links to the place it is closed",
       html.count("/content?sub=") >= len(o["gaps"]))
    ck("CONSOLE the crawl's dropped reasons are shown", "needs a browser to read" in html)
    from fastapi.testclient import TestClient
    from app import web as _web
    cl = TestClient(_web.app)
    r = cl.post("/admin/claim_record?key=s3cret", data={"tenant": T, "claim_id": c3,
                                                         "subject": "self", "by": "qa-ana"},
                follow_redirects=False)
    with db.SessionLocal() as s:
        row = s.get(db.KbClaim, c3)
        ok = row.subject == "self" and (row.scope_origin or {}).get("subject") == "reviewer"
    ck("CONSOLE the spot check's 'This is the account's own claim' moves it back to review",
       r.status_code in (200, 303) and ok)
    print(f"\n{'FAILED: ' + ', '.join(_fail) if _fail else 'all checks passed'}")
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
