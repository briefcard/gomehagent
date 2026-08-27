"""Every surface renders, and every class the markup uses, the CSS defines.

The Plan tab shipped with SIX classes its renderer used and the stylesheet
never defined — `.cards .lbl .big .grp .warn .bad` — so the readiness strip
rendered as unstyled stacked divs and an ERROR on that tab rendered as plain
body text, for weeks, while every suite passed. No test looked at the page the
way a person does: as markup that has to meet its own stylesheet. This one
does, mechanically, for every tab, every sub-view, and the client surfaces.

It also carries the step-0 behaviour pins from INITIATIVE-ui-overhaul.md —
each one a defect that was live at ed54385:

  · the portal sign-in form actually submits (it was dead HTML: a nested
    <form> start tag is DROPPED by the HTML parser, so the button submitted an
    outer `onsubmit='return false'` wrapper and no client could ever request
    a link);
  · /health is liveness + build identity without the key, and the full report
    (inbox aliases, oauth redirect URIs) needs it;
  · /health/connections — the probe that names client accounts — refuses
    without the key instead of printing the roster to anyone;
  · the sidebar's Client-view link carries NO key (the credential used to ride
    into the portal's own access logs);
  · portal sessions fail CLOSED on an empty APPROVAL_SECRET (an HMAC keyed on
    "" verifies anything, including a forged role=owner cookie);
  · intake links have a console surface (mint/list/revoke lived as raw-JSON
    URLs for months).

    python3 scripts/test_render_smoke.py
"""
import os
import re
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'smoke.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import admin_ui, config, db, portal, tenants, web  # noqa: E402

KEY = "s3cret"
_fail: list[str] = []


def ck(label: str, cond, detail: str = "") -> None:
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


# One keyed client for walking pages; FRESH clients for every unauthenticated
# assertion — TestClient keeps a cookie jar, and an auth check against a
# client that already signed in passes for the wrong reason (the documented
# trap that has bitten this repo twice).
c = TestClient(web.app, base_url="https://testserver")


def anon() -> TestClient:
    return TestClient(web.app, base_url="https://testserver")


db.init_db()
tenants.seed()
keys = [t.key for t in tenants.all_tenants()]
ck("seed produced accounts", len(keys) >= 2, str(keys))
T1, T2 = keys[0], keys[1]

# ---------------------------------------------------------------------------
# Class coverage. `defined` = every `.token` in the served <style> blocks;
# `used` = every token in every class attribute. A used token the stylesheet
# does not know is exactly the Plan-tab failure, caught at render time.
# ---------------------------------------------------------------------------
STYLE_RE = re.compile(r"<style[^>]*>(.*?)</style>", re.S)
CLASS_ATTR_RE = re.compile(r"class=(?:\"([^\"]*)\"|'([^']*)')")
DEFINED_RE = re.compile(r"\.([A-Za-z_][\w-]*)")

#: Pre-existing intentionally-bare hooks, each with the reason it is allowed.
#: This list may SHRINK (step 1's token sheet styles or removes them) and must
#: never grow — a new class belongs in the stylesheet, not here.
ALLOWED_BARE = {
    "anchor",     # positioning hook only (offset for the sticky bulkbar)
}


def coverage(label: str, html: str) -> None:
    css = "\n".join(STYLE_RE.findall(html))
    defined = set(DEFINED_RE.findall(css))
    used: set[str] = set()
    for a, b in CLASS_ATTR_RE.findall(html):
        used.update((a or b).split())
    missing = sorted(used - defined - ALLOWED_BARE)
    ck(f"{label}: every class the markup uses is defined",
       not missing, ("undefined: " + ", ".join(missing[:14])) if missing else "")


def page(label: str, path: str, want: str = 'class="side"') -> str:
    r = c.get(path)
    ck(f"{label}: 200", r.status_code == 200, f"got {r.status_code}")
    html = r.text
    if want:
        ck(f"{label}: framed", want in html)
    coverage(label, html)
    return html


# ---------------------------------------------------------------------------
# Walk every tab and sub-view on one account, the fall-through tabs on a
# second, and the deliberately-pooled views on All accounts.
# ---------------------------------------------------------------------------
SUBS = [k for k, _l in admin_ui.REVIEW_SUBS]
walk = ([("content", "")] + [("content", f"&sub={s}") for s in SUBS]
        + [("kb", ""), ("brand", ""), ("plan", ""),
           ("systems", ""), ("systems", "&sub=available"),
           ("assurance", ""), ("diagnostics", ""),
           ("diagnostics", "&view=systems"),
           ("accounts", ""), ("schema", "")])
accounts_html = ""
for tab, extra in walk:
    html = page(f"{tab}{extra or ''} · {T1}",
                f"/admin/ui?key={KEY}&tab={tab}&tenant={T1}{extra}")
    if tab == "accounts" and not extra:
        accounts_html = html
for tab in ("content", "accounts"):
    page(f"{tab} · {T2}", f"/admin/ui?key={KEY}&tab={tab}&tenant={T2}")
for tab in ("content", "systems", "assurance", "diagnostics"):
    page(f"{tab} · all-accounts", f"/admin/ui?key={KEY}&tab={tab}&tenant=*")

# ---------------------------------------------------------------------------
# Pin: the Client-view link carries no key.
# ---------------------------------------------------------------------------
ck("Client view link is keyless",
   f'href="/portal?tenant={T1}"' in accounts_html
   and f'/portal?tenant={T1}&amp;key=' not in accounts_html)

# ---------------------------------------------------------------------------
# Pin: the intake-links card exists and the mint flow lands back as a flash.
# ---------------------------------------------------------------------------
ck("intake links have a console surface", "Intake links —" in accounts_html)
r = c.get(f"/admin/intake_new?key={KEY}&tenant={T1}&label=Smoke&ui=1",
          follow_redirects=False)
ck("intake mint (ui=1) redirects back", r.status_code == 303
   and "ilink=" in r.headers.get("location", ""), r.headers.get("location", ""))
flashed = c.get(r.headers["location"]).text
ck("minted intake link is flashed, copyable",
   "Intake link — send this" in flashed and "/intake/" in flashed)
with db.SessionLocal() as s:
    tok = (s.query(db.IntakeLink)
           .filter(db.IntakeLink.tenant == T1).first().token)
r = c.get(f"/admin/intake_revoke?key={KEY}&token={tok}&tenant={T1}&ui=1",
          follow_redirects=False)
ck("intake revoke (ui=1) redirects back with a flash",
   r.status_code == 303 and "ok=" in r.headers.get("location", ""))

# ---------------------------------------------------------------------------
# Pin: the portal sign-in form submits. The card wrapper must never be a
# <form> again — a nested form start tag is silently dropped by the parser,
# which is how the front door shipped dead.
# ---------------------------------------------------------------------------
signin = anon().get("/portal").text
ck("portal sign-in renders", "action='/portal/signin'" in signin
   and "method='post'" in signin)
ck("sign-in card wrapper is not a form", "onsubmit" not in signin)
coverage("portal sign-in", signin)

r = anon().post("/portal/signin", data={"email": "nobody@example.com"})
ck("sign-in POST answers without enumerating",
   r.status_code == 200 and "Request received" in r.text)

# Bad token renders the sign-in page, not a bare error.
r = anon().get("/portal/in/not-a-token")
ck("bad sign-in link lands on sign-in", r.status_code == 200
   and "not valid" in r.text)

# Owner's client view: nav carries the tenant, so the second click holds.
pview = c.get(f"/portal?tenant={T1}&key={KEY}")
ck("owner client-view renders", pview.status_code == 200)
ck("portal nav carries tenant for the owner",
   f"tab=results&days=30&tenant={T1}" in pview.text)
coverage(f"portal · {T1}", pview.text)

# ---------------------------------------------------------------------------
# Pin: /health is liveness-only without the key; the roster needs it.
# ---------------------------------------------------------------------------
h = anon().get("/health").json()
ck("/health unauth answers liveness", h.get("ok") is True and "commit" in h
   and "skills" in h)
ck("/health unauth names no inboxes or oauth",
   "inboxes" not in h and "oauth" not in h, str(sorted(h)))
hk = c.get(f"/health?key={KEY}").json()
ck("/health with key carries the full report", "inboxes" in hk and "oauth" in hk)
r = anon().get("/health/connections")
ck("/health/connections refuses without the key", r.status_code == 401,
   f"got {r.status_code}")

# ---------------------------------------------------------------------------
# Pin: portal sessions fail CLOSED on an empty secret.
# ---------------------------------------------------------------------------
import hashlib  # noqa: E402
import hmac as _hmac  # noqa: E402

_old = config.APPROVAL_SECRET
try:
    config.APPROVAL_SECRET = ""
    body = "u1|" + T1 + "|owner|9999999999"
    forged = body + "." + _hmac.new(b"", body.encode(),
                                    hashlib.sha256).hexdigest()[:32]
    ck("empty secret rejects a forged owner cookie",
       portal.read_session(forged) == {})
    raised = False
    try:
        portal._sign("u1", T1, "owner")
    except RuntimeError:
        raised = True
    ck("empty secret refuses to mint a session", raised)
finally:
    config.APPROVAL_SECRET = _old

# ---------------------------------------------------------------------------
# The frame (step 2b): badges that mean "waiting on a person", one h1, a
# Sign out that exists, no silent wrong-tab, one pager vocabulary.
# ---------------------------------------------------------------------------
with db.SessionLocal() as s:
    s.add(db.Approval(kind="send_email", status="pending",
                      summary="SMOKE ship row", payload={}, tenant=T1))
    s.commit()

badged = c.get(f"/admin/ui?key={KEY}&tab=content&tenant={T1}").text
ck("the Review badge counts the pending decision",
   'title="decisions waiting on you">1</span>' in badged)
ck("…and the queue actually shows it — the badge is the list's number",
   "SMOKE ship row" in badged)
ck("exactly one h1 on the page (the pagehead)", badged.count("<h1") == 1,
   f'found {badged.count("<h1")}')
star = c.get(f"/admin/ui?key={KEY}&tab=systems&tenant=*").text
ck("All accounts rolls the count up onto the switcher row",
   star.count('title="decisions waiting on you">1</span>') == 1)
ck("Sign out exists in the frame", 'href="/admin/logout"' in badged)

r = c.get(f"/admin/ui?key={KEY}&tab=bogus&tenant={T1}", follow_redirects=False)
ck("an unknown tab redirects and says so", r.status_code == 303
   and "tab=content" in r.headers.get("location", "")
   and "err=" in r.headers.get("location", ""),
   r.headers.get("location", ""))
aliased = c.get(f"/admin/ui?key={KEY}&tab=diagnostics&tenant={T1}&sub=systems").text
ck("`sub=` reaches the Diagnostics sub-view (view= still accepted)",
   "Systems check" in aliased)

# ---------------------------------------------------------------------------
# The workroom (step 3): the old address redirects, the draft survives every
# edit, versions append, Save-for-later is INDEXED, and feedback lands in a
# real channel at filing time — the loop, not a complaint box.
# ---------------------------------------------------------------------------
from app import kb as _kb  # noqa: E402

_kb.ensure_brand(T1, T1)      # the save path's ban-list gate needs the row —
_kb.add_banned(T1, "smokedummyrule")   # and the gate is CONSTITUTIVE: an
                                       # empty ban list refuses the edit
                                       # rather than passing it unchecked
with db.SessionLocal() as s:
    s.add(db.ArtifactBody(tenant=T1, output_id="smk-art-1", run_id="",
                          system_key="blog", format="cms_article",
                          body="<p>Workroom smoke body</p>",
                          draft_body="<p>the frozen draft</p>", bytes=28))
    s.commit()

r = c.get(f"/admin/article/smk-art-1?key={KEY}", follow_redirects=False)
ck("the old article address redirects to the workroom", r.status_code == 303
   and r.headers.get("location", "").startswith("/admin/work/smk-art-1"),
   r.headers.get("location", ""))
wr = c.get(f"/admin/work/smk-art-1?key={KEY}").text
ck("the workroom renders, framed", 'class="side"' in wr
   and "Workroom smoke body" in wr and "article_save" in wr)
coverage("workroom", wr)

r = c.post("/admin/article_save",
           data={"key": KEY, "output_id": "smk-art-1", "action": "later",
                 "title": "Held", "body": "<p>edited, held for later</p>"},
           follow_redirects=False)
ck("Save for later lands back on the workroom", r.status_code == 303
   and "/admin/work/smk-art-1" in r.headers.get("location", "")
   and "ok=" in r.headers.get("location", ""), r.headers.get("location", ""))
with db.SessionLocal() as s:
    _art = s.query(db.ArtifactBody).filter_by(output_id="smk-art-1").first()
    _vs = s.query(db.ArtifactVersion).filter_by(output_id="smk-art-1").all()
    s.expunge_all()
ck("the edit persisted and the hold is real",
   "held for later" in (_art.body or "") and _art.state == "in_review")
ck("the draft SURVIVES the edit — v1 stays frozen",
   _art.draft_body == "<p>the frozen draft</p>")
ck("the save appended a version", len(_vs) == 1 and _vs[0].n == 2
   and _vs[0].author == "owner")
strip = c.get(f"/admin/ui?key={KEY}&tab=content&tenant={T1}").text
ck("Save-for-later is INDEXED — the In-progress strip finds it",
   "In progress" in strip and "/admin/work/smk-art-1" in strip)

r = c.post("/admin/feedback_add",
           data={"key": KEY, "output_id": "smk-art-1", "system_key": "blog",
                 "part": "body", "category": "tone", "level": "system",
                 "note": "lead with the number, not the greeting"},
           follow_redirects=False)
ck("system-level feedback files", r.status_code == 303
   and "ok=" in r.headers.get("location", ""), r.headers.get("location", ""))
from app import systems as _sys  # noqa: E402
ck("…and REACHES the prompt channel",
   "lead with the number" in _sys.feedback_block(T1, "blog"))
c.post("/admin/feedback_add",
       data={"key": KEY, "output_id": "smk-art-1", "system_key": "blog",
             "part": "body", "category": "brand", "level": "rule",
             "note": "smokebannedphrase"}, follow_redirects=False)
with db.SessionLocal() as s:
    _brand = s.query(db.KbBrand).filter_by(tenant=T1).first()
    banned = list(_brand.banned_claims or []) if _brand else []
ck("rule-level feedback REACHES the validator's ban list",
   any("smokebannedphrase" in str(b) for b in banned), str(banned)[:120])

# ---------------------------------------------------------------------------
# Draft products are not even OFFERED (owner, 2026-08-27): the plan's entity
# picker must list an available product, label an out-of-stock one, and show
# a draft/archived one never — fitness screens the drafter's pool, this pins
# the owner-facing select.
# ---------------------------------------------------------------------------
from app import provenance as _prov  # noqa: E402

with db.SessionLocal() as s:
    s.add(db.KbEntity(tenant=T1, key="smk-live", name="Smoke Live Product",
                      type="product", availability="available",
                      status="active", review=_prov.APPROVED))
    s.add(db.KbEntity(tenant=T1, key="smk-oos", name="Smoke OOS Product",
                      type="product", availability="oos",
                      status="active", review=_prov.APPROVED))
    s.add(db.KbEntity(tenant=T1, key="smk-drafty", name="Smoke Draft Product",
                      type="product", availability="draft",
                      status="active", review=_prov.APPROVED))
    s.commit()
_sel = admin_ui._plan_field_input({"key": "entity_key", "kind": "entity",
                                   "label": "Featured"}, "", tenant=T1)
ck("the entity picker offers the live product", "smk-live" in _sel)
ck("…labels the out-of-stock one", "smk-oos" in _sel
   and "out of stock" in _sel)
ck("…and a DRAFT product is not offered at all", "smk-drafty" not in _sel)

# ---------------------------------------------------------------------------
# Light mode (step 2): the second token block defines every token the dark
# root does — the parity that stops one palette silently falling behind the
# other — the toggle persists in a cookie, and the choice reaches <body>.
# ---------------------------------------------------------------------------
_css = admin_ui._CSS


def _tokens(block_start: str) -> set:
    seg = _css.split(block_start, 1)[1].split("}", 1)[0]
    return set(re.findall(r"--([\w-]+)\s*:", seg))


dark_tokens = _tokens(":root{") - {"sans", "mono"}   # type stacks are
light_tokens = _tokens("body[data-theme=light]{")    # theme-invariant
ck("light defines every dark token", dark_tokens <= light_tokens,
   "missing: " + ", ".join(sorted(dark_tokens - light_tokens)))
# Light restates the per-account tint formulas (dark's live on body{}); it
# must not otherwise invent tokens the dark set lacks.
ck("light adds only the tint formulas",
   light_tokens - dark_tokens <= {"tone", "tones"},
   str(sorted(light_tokens - dark_tokens - {"tone", "tones"})))

r = c.get(f"/admin/theme?key={KEY}&to=light&tab=content&tenant={T1}&sub=ship",
          follow_redirects=False)
ck("theme toggle redirects back to the exact page", r.status_code == 303
   and r.headers.get("location", "").endswith(
       f"tab=content&tenant={T1}&sub=ship"),
   r.headers.get("location", ""))
def _body_tag(html: str) -> str:
    # Assert on the real body TAG: search AFTER </head>, because the served
    # stylesheet's own comments have now false-positived this check twice —
    # once mentioning data-theme="light", once mentioning <body> itself. A
    # check that greps a page greps the page's prose too.
    m = re.search(r"<body[^>]*>", html.split("</head>", 1)[-1])
    return m.group(0) if m else ""


lightpage = c.get(f"/admin/ui?key={KEY}&tab=content&tenant={T1}").text
ck("light choice reaches the body tag",
   'data-theme="light"' in _body_tag(lightpage), _body_tag(lightpage))
coverage(f"content · {T1} · light", lightpage)
c.get(f"/admin/theme?key={KEY}&to=dark", follow_redirects=False)
darkpage = c.get(f"/admin/ui?key={KEY}&tab=content&tenant={T1}").text
ck("dark is the default and renders with no attribute",
   "data-theme" not in _body_tag(darkpage), _body_tag(darkpage))

r = c.get("/admin/logout", follow_redirects=False)
ck("Sign out lands on the sign-in door", r.status_code == 303
   and r.headers.get("location", "") == "/admin/signin")

# ---------------------------------------------------------------------------
print(f"\n{len(_fail)} failure(s)" if _fail else "\nall render-smoke checks pass")
sys.exit(1 if _fail else 0)
