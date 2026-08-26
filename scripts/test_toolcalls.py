"""The platforms that run every day are the ones that were not being recorded.

`toolcalls.record` had exactly TWO callers, both in `kernel.py`, plus three
adapters wrapped through `instrument` — Omnisend, Constant Contact and Canva.
Every one of those three has never been called for real.

Meanwhile `shopify_seo`, `wordpress_seo` and `data_tools` reach live stores and
sites all day through plain `httpx` and recorded nothing, because `instrument`
fits a signature that begins with a tenant and those modules are keyed by a
store key and a site profile instead.

So the telemetry covered the code that never runs and missed the code that runs
constantly, which is why Diagnostics reports most of this system as untimed —
and an untimed call reads as fast rather than as unmeasured.

    python3 scripts/test_toolcalls.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'tc.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
os.environ["SHOPIFY_STORES_JSON"] = json.dumps(
    {"baci": {"domain": "baci.myshopify.com", "token": "shpat_x"}})
os.environ["SEO_SITES_JSON"] = json.dumps(
    {"baci": {"domain": "bacimilanousa.com", "platform": "shopify",
              "creds_key": "baci"}})
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import connections, db, shopify_seo, tenants, toolcalls  # noqa: E402

_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def rows():
    with db.SessionLocal() as s:
        return s.query(db.ToolCall).order_by(db.ToolCall.at).all()


class Resp:
    def __init__(self, payload, status=200):
        self._p, self.status_code = payload, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._p


def main() -> int:
    db.init_db()
    tenants.seed()

    # --- the join telemetry depends on -----------------------------------
    print("— a store key becomes an account —")
    ck("baci's store key resolves to baci",
       connections.tenant_for_store("baci") == "baci")
    ck("an unknown store resolves to NOTHING, never a default account — "
       "attributing one client's calls to another is worse than to nobody",
       connections.tenant_for_store("no-such-store") == "")

    # --- a successful round trip is recorded ------------------------------
    print("\n— a Shopify read lands in the ledger —")
    import httpx
    real_get = httpx.get
    httpx.get = lambda *a, **kw: Resp({"products": []})
    try:
        before = len(rows())
        shopify_seo._get("baci", "products.json", {"limit": 5})
    finally:
        httpx.get = real_get
    got = rows()
    ck("a row was written", len(got) == before + 1, f"{before} -> {len(got)}")
    r = got[-1]
    ck("attributed to the account", r.tenant == "baci", r.tenant)
    ck("naming the platform", r.provider == "shopify", r.provider)
    ck("filed as an adapter call, not a kernel one", r.source == "adapter", r.source)
    ck("carrying the verb and path", r.tool == "shopify:GET products.json", r.tool)
    ck("marked ok", r.ok == "yes", r.ok)
    ck("and TIMED — an untimed call reads as fast rather than unmeasured",
       int(r.ms) >= 0 and r.ms != "", repr(r.ms))

    # --- ids must not reach our telemetry --------------------------------
    print("\n— a client's ids stay out of our ledger —")
    httpx.get = lambda *a, **kw: Resp({"product": {}})
    try:
        shopify_seo._get("baci", "products/8123456789.json")
    finally:
        httpx.get = real_get
    r = rows()[-1]
    ck("the id is dropped from the recorded path", "8123456789" not in r.tool, r.tool)
    ck("and what remains is coarse enough to group by",
       r.tool == "shopify:GET products", r.tool)

    # --- the failing call is the one worth having -------------------------
    print("\n— a dead connection is recorded, and still raises —")
    httpx.request = lambda *a, **kw: Resp({}, status=401)
    raised = False
    before = len(rows())
    try:
        shopify_seo._send("baci", "PUT", "products/9.json", {"x": 1})
    except Exception:                                            # noqa: BLE001
        raised = True
    ck("the exception still reaches the caller — swallowing it would turn a "
       "broken connection into a silent empty answer", raised)
    got = rows()
    ck("and the failure was recorded", len(got) == before + 1)
    r = got[-1]
    ck("marked not ok", r.ok == "no", r.ok)
    ck("with the reason kept", "HTTP 401" in (r.error or ""), r.error)
    ck("the verb comes from the call, not the wrapper",
       r.tool.startswith("shopify:PUT "), r.tool)

    # --- attribution must never break the call ----------------------------
    print("\n— a broken join costs a label, never the call —")
    real = connections.tenant_for_store
    connections.tenant_for_store = lambda k: (_ for _ in ()).throw(RuntimeError("boom"))
    httpx.get = lambda *a, **kw: Resp({"ok": 1})
    try:
        out = shopify_seo._get("baci", "shop.json")
        ck("the call still returned", out == {"ok": 1}, str(out))
        ck("and it was still filed, unattributed rather than lost",
           rows()[-1].tool == "shopify:GET shop.json", rows()[-1].tool)
        ck("with no account guessed", rows()[-1].tenant == "", repr(rows()[-1].tenant))
    finally:
        connections.tenant_for_store = real
        httpx.get = real_get

    # --- adding a layer must not corrupt the number read first ------------
    # A model tool call that reaches Shopify now files TWO rows: the tool the
    # model named and the HTTP round trip under it. Counting both doubles the
    # provider total -- and HALVES the failure rate, because
    # `data_tools.dispatch` catches the exception and returns a "Tool error"
    # string, so the platform row records a failure while the tool row records
    # a success for the same call.
    #
    # Measured before the fix: a completely dead token read 0.5. `report`'s own
    # comment says most-of-the-time is a broken connection and occasionally is
    # the internet, so a dead credential landed exactly on the line between
    # them -- the instrumentation would have made the headline number worse.
    print("\n— one layer per provider, so a dead token reads as dead —")
    from app import tenants as _tn, tools as _tools
    _tn.seed()
    for row in rows():
        pass
    with db.SessionLocal() as sess:
        sess.query(db.ToolCall).delete()
        sess.commit()

    httpx.get = lambda *a, **kw: Resp({}, status=401)
    try:
        _tools.call("shopify_find_orders", {"customer_email": "a@b.com"},
                    "baci", source="admin")
    finally:
        httpx.get = real_get

    filed = {r.source for r in rows()}
    ck("both layers are still FILED — they are different facts",
       filed == {"adapter", "admin"}, str(filed))

    rep = toolcalls.report("baci", days=1)
    prov = rep["by_provider"].get("shopify", {})
    ck("but the provider is counted once, not twice",
       prov.get("calls") == 1, str(prov))
    ck("a dead token reads as a TOTAL failure, not a coin flip",
       rep["failing"] and rep["failing"][0]["failure_rate"] == 1.0,
       str(rep["failing"]))
    ck("and the count says which layer it came from, so a provider measured "
       "at the tool layer is not mistaken for a measured round trip",
       prov.get("layer") == "platform", str(prov.get("layer")))
    ck("by_tool still carries both — they answer different questions",
       len([t for t in rep["by_tool"] if "shopify" in t]) == 2,
       str(list(rep["by_tool"])))

    # --- the seams have to be CALLABLE, not just instrumented -------------
    # Found while reading the call sites in order to wrap them.
    # `wordpress_seo._send(profile, method, path, body)` takes `body`
    # positionally and has no `params`, and both blog READS called it as
    # `_send(profile, "GET", path, params={...})` — an unexpected keyword and a
    # missing positional, so they raised TypeError before reaching WordPress.
    #
    # They are the "review and revise existing articles" half of the blog path.
    # Nothing had ever called them, which is the only reason a TypeError on the
    # happy path survived being shipped — and is why this drives the functions
    # rather than reading their source.
    print("\n— the WordPress blog reads actually run —")
    from app import wordpress_seo
    prof = {"key": "mtw", "domain": "marketingthatworks.co",
            "platform": "wordpress", "creds_key": "wp"}
    real_cfg = wordpress_seo._cfg
    wordpress_seo._cfg = lambda p: {"base_url": "https://example.com",
                                    "user": "u", "app_password": "p"}
    httpx.get = lambda *a, **kw: Resp([{"id": 1, "status": "publish",
                                        "title": {"rendered": "Hi"},
                                        "link": "https://example.com/hi"}])
    try:
        out = wordpress_seo.list_articles(prof, limit=5)
        ck("list_articles returns instead of raising TypeError",
           "Hi" in out, out[:80])
        httpx.get = lambda *a, **kw: Resp({"id": 1, "title": {"raw": "Hi"},
                                           "content": {"raw": "body"},
                                           "link": "https://example.com/hi"})
        out = wordpress_seo.get_article(prof, article_id=1)
        ck("and so does get_article", "Hi" in out, out[:80])
    except TypeError as exc:
        ck("the WordPress blog reads are callable", False, f"TypeError: {exc}")
    finally:
        wordpress_seo._cfg = real_cfg
        httpx.get = real_get

    # --- Semrush: one key, five accounts, and until now no way to tell --
    #
    # Every other platform reaches its API through `http_seam` and lands here
    # with an account attached. `seo_tools` imported `toolcalls` NOWHERE, so
    # Semrush — the one provider whose quota is genuinely shared across every
    # client — was absent from Diagnostics entirely. "Which account spent the
    # units" was unanswerable, and a dying key would have looked like thin
    # harvests rather than an error.
    print("\n— every Semrush round trip names the account it was for —")
    from app import config as _cfg, seo_tools as _st
    _cfg.SEMRUSH_API_KEY = "fake-key"
    _real = _st.httpx.get

    class _R:
        def __init__(self, t):
            self.text, self.status_code = t, 200
    try:
        _st.httpx.get = lambda *a, **k: _R("Keyword;Search Volume\njug;5000")
        _st._semrush("phrase_related", _tenant="baci", phrase="jug")
        _st.httpx.get = lambda *a, **k: _R("ERROR 50 :: NOTHING FOUND")
        _st._semrush("phrase_questions", _tenant="eien", phrase="zzz")

        def _boom(*a, **k):
            raise TimeoutError("slow")
        _st.httpx.get = _boom
        _st._semrush("domain_organic", _tenant="baci", domain="x")
    finally:
        _st.httpx.get = _real

    # NOT `rows` — this suite already has a `rows()` helper, and binding the
    # name here makes Python treat every earlier call to it as a local read.
    with db.SessionLocal() as s:
        sem = [r for r in s.query(db.ToolCall).all() if r.provider == "semrush"]
    by = {(r.tenant, r.tool): r.ok for r in sem}
    ck("a successful read is filed against the account that asked",
       by.get(("baci", "semrush_phrase_related")) == "yes", str(by))
    ck("another account's call is filed against THAT account",
       by.get(("eien", "semrush_phrase_questions")) == "yes",
       "one key, five clients — an unattributed unit is a shared quota "
       "nobody can budget")
    ck("'nothing found' is an ANSWER, not a failure",
       by.get(("eien", "semrush_phrase_questions")) == "yes",
       "a quiet niche must not read as a broken key on the failure rate")
    ck("a timeout IS a failure", by.get(("baci", "semrush_domain_organic")) == "no")
    ck("and it carries the provider, so Diagnostics can group it",
       all(r.provider == "semrush" for r in sem) and len(sem) == 3, str(len(sem)))
    ck("the account is never something the model can name",
       not any("_tenant" in str(t.get("input_schema", {}))
               for t in _st.TOOLS),
       "`_tenant` is absent from every schema — the agent cannot pick whose "
       "quota to spend, the same rule tool_scope enforces for accounts")

    print()
    if _fail:
        print(f"{len(_fail)} FAILED: " + "; ".join(_fail))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
