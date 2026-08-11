"""Single-page console for wiring accounts.

Everything here is also reachable as bare /admin/* URLs, but hand-typing JSON
into a browser bar is how connections get mis-set. This page renders the same
operations as forms, with the how-to-get-this-value instructions sitting next
to the field they belong to rather than in a document you have to cross-read.

Server-rendered, no build step, no external assets — it has to work from a
phone on a hotel wifi.
"""
from __future__ import annotations

import html
import json

from . import config, db, systems, tenants

# The instructions that used to live in a separate manual. Kept beside the
# fields so a value is never entered from memory.
FIELD_HELP = {
    "gmail_alias": (
        "Inbox monitoring + sending drafts",
        "A key from GMAIL_ACCOUNTS_JSON — not an email address. "
        "To add a new one: run scripts/google_oauth.py locally, sign in as that "
        "mailbox, and add the resulting entry to GMAIL_ACCOUNTS_JSON in Render. "
        "For a client, they must grant access to their own Google account."),
    "shopify_store": (
        "Products, inventory, orders",
        "A key from SHOPIFY_STORES_JSON. To create one: in their Shopify admin go to "
        "Settings → Apps and sales channels → Develop apps → Create an app → "
        "Configure Admin API scopes (read_products, read_orders, read_inventory) → "
        "Install → reveal the Admin API access token. Store the token in Render, "
        "put the KEY here."),
    "esp": (
        "Email campaigns, segments, holdouts",
        "Omnisend: Store settings → Integrations & API → API keys → create one. "
        "Klaviyo: Settings → API keys → create a Private Key. "
        "Constant Contact is OAuth, not a key — it needs the auth layer first. "
        "Put the API key in a Render env var and reference its NAME here."),
    "cms": (
        "Blog and page publishing",
        "Shopify: same custom app as commerce, add read_content/write_content. "
        "WordPress: an application password on an editor account. "
        "Squarespace has no usable publishing API — those tenants generate and hand off."),
    "ads": (
        "Spend, ROAS, creative performance",
        "Meta: Business Manager → the ad account → the ID in the URL or account "
        "dropdown (digits only, no 'act_' prefix). "
        "Google Ads: the 10-digit customer ID at the top right, dashes removed."),
    "analytics": (
        "Traffic, rankings, attribution",
        "GA4: Admin → Property settings → Property ID (numeric). "
        "Search Console: the property exactly as verified, including the "
        "sc-domain: prefix if it's a domain property. "
        "semrush_db is the country database, usually 'us'."),
    "crm": (
        "Deal and contact context on inbound",
        "Salesforce: a Connected App with API access; store the credentials in "
        "Render and reference them here. HubSpot: a private app token."),
    "design": (
        "Canva assets for posts and flyers",
        "NOT CONNECTED YET. Canva Connect is OAuth, so it needs the auth layer "
        "built before this field does anything. Leave blank."),
    "systems": (
        "Which pipelines run for this account",
        "A JSON list. Currently meaningful: lead_responder, campaign_email, "
        "blog, reorder_engine, service_desk, reports."),
}

_CSS = """
:root{--bg:#f6f7fa;--panel:#fff;--ink:#15171d;--ink2:#3d434f;--mut:#6e7686;
--rule:#dfe3ea;--rule2:#eef0f4;--acc:#2f4b7c;--accs:#e8edf6;--ok:#2a6357;--oks:#e3efeb;
--gap:#95602a;--gaps:#f6ebdc}
@media(prefers-color-scheme:dark){:root{--bg:#101218;--panel:#171a22;--ink:#e9ebf0;
--ink2:#b9bfcc;--mut:#858d9e;--rule:#2a2f3b;--rule2:#212632;--acc:#87a6d8;--accs:#1c2434;
--ok:#66ad99;--oks:#152621;--gap:#d2a063;--gaps:#2a2115}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 -apple-system,
BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;-webkit-font-smoothing:antialiased}
.w{max-width:960px;margin:0 auto;padding:32px 20px 80px;display:flex;flex-direction:column;gap:30px}
h1{font:600 1.7rem/1.2 Georgia,serif;margin:0}
h2{font:600 1.15rem/1.2 Georgia,serif;margin:0}
h3{font:600 .98rem/1.3 Georgia,serif;margin:0}
.mut{color:var(--mut);font-size:.86rem}
.card{background:var(--panel);border:1px solid var(--rule);border-radius:7px;padding:16px 18px;
display:flex;flex-direction:column;gap:12px}
.head{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:baseline;
border-bottom:1px solid var(--rule);padding-bottom:10px}
.head h2{flex:1 1 auto}
.chips{display:flex;flex-wrap:wrap;gap:5px}
.chip{font-size:.68rem;padding:.2em .5em;border-radius:3px;font-weight:700;letter-spacing:.03em}
.chip.on{background:var(--oks);color:var(--ok);border:1px solid var(--ok)}
.chip.off{background:var(--gaps);color:var(--gap);border:1px solid var(--gap)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}
.f{display:flex;flex-direction:column;gap:5px;border:1px solid var(--rule);border-radius:5px;
padding:11px 13px;background:var(--rule2)}
.f label{font-size:.72rem;text-transform:uppercase;letter-spacing:.07em;font-weight:700;color:var(--acc)}
.f .what{font-size:.8rem;color:var(--ink2)}
.f details{font-size:.79rem;color:var(--mut)}
.f summary{cursor:pointer;color:var(--acc);font-weight:600;font-size:.75rem}
.f details p{margin:6px 0 0}
input,select{font:inherit;font-size:.85rem;padding:6px 8px;border:1px solid var(--rule);
border-radius:4px;background:var(--panel);color:var(--ink);width:100%}
button{font:inherit;font-size:.82rem;font-weight:600;padding:6px 13px;border-radius:5px;
border:1px solid var(--acc);background:var(--acc);color:var(--panel);cursor:pointer}
button.sec{background:transparent;color:var(--acc)}
.row{display:flex;gap:7px;align-items:center;flex-wrap:wrap}
code{font-family:ui-monospace,Menlo,monospace;font-size:.82em;background:var(--rule2);
padding:.1em .35em;border-radius:3px}
.cur{background:var(--accs);border-left:3px solid var(--acc)}
.note{background:var(--gaps);border-left:3px solid var(--gap);padding:10px 14px;
border-radius:0 4px 4px 0;font-size:.85rem;color:var(--ink2)}
.ok{background:var(--oks);border-left:3px solid var(--ok);padding:10px 14px;
border-radius:0 4px 4px 0;font-size:.85rem;color:var(--ink2)}
.tabs{display:flex;gap:4px;border-bottom:1px solid var(--rule);flex-wrap:wrap}
.tabs a{text-decoration:none;font-size:.85rem;font-weight:600;color:var(--mut);
padding:8px 15px;border:1px solid transparent;border-bottom:none;border-radius:5px 5px 0 0;
position:relative;bottom:-1px}
.tabs a.on{color:var(--acc);background:var(--panel);border-color:var(--rule);
border-bottom:1px solid var(--panel)}
textarea{font:inherit;font-size:.85rem;padding:6px 8px;border:1px solid var(--rule);
border-radius:4px;background:var(--panel);color:var(--ink);width:100%;resize:vertical}
.sysgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px}
.stat{display:flex;gap:16px;flex-wrap:wrap;font-size:.8rem;color:var(--mut)}
.stat b{color:var(--ink);font-weight:600}
.thread{display:flex;flex-direction:column;gap:7px}
.msg{border-left:2px solid var(--rule);padding:3px 0 3px 11px;font-size:.85rem}
.msg .when{font-size:.72rem;color:var(--mut)}
.rung{display:flex;gap:6px;flex-wrap:wrap;align-items:center;font-size:.8rem}
.rung .step{padding:.15em .5em;border-radius:3px;border:1px solid var(--rule);color:var(--mut);font-size:.72rem}
.rung .step.at{background:var(--accs);border-color:var(--acc);color:var(--acc);font-weight:700}
.rung .step.done{color:var(--ok);border-color:var(--ok)}
ul.bl{margin:0;padding-left:18px;font-size:.85rem;color:var(--ink2)}
ul.bl li{margin:2px 0}
"""

_TABS = (("accounts", "Accounts"), ("systems", "Systems"))


def _shell(key: str, tab: str, title: str, body: str) -> str:
    nav = "".join(
        f'<a class="{"on" if t == tab else ""}" '
        f'href="/admin/ui?key={_esc(key)}&amp;tab={t}">{label}</a>'
        for t, label in _TABS)
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)} — Saias Ops</title><style>{_CSS}</style></head><body><div class="w">
<div class="tabs">{nav}</div>
{body}
</div></body></html>"""


def _esc(v) -> str:
    return html.escape(str(v or ""), quote=True)


def _chips(caps: dict) -> str:
    return "".join(
        f'<span class="chip {"on" if ok else "off"}">{c}</span>'
        for c, ok in caps.items())


def _field(t, key: str, name: str) -> str:
    title, howto = FIELD_HELP.get(name, (name, ""))
    raw = getattr(t, name, None)
    val = json.dumps(raw) if isinstance(raw, (dict, list)) else (raw or "")
    return f"""
    <form class="f" method="get" action="/admin/tenant_set">
      <input type="hidden" name="key" value="{_esc(key)}">
      <input type="hidden" name="tenant" value="{_esc(t.key)}">
      <input type="hidden" name="field" value="{name}">
      <label>{name}</label>
      <div class="what">{_esc(title)}</div>
      <input name="value" value="{_esc(val)}" placeholder="empty">
      <div class="row"><button>Save</button></div>
      <details><summary>How do I get this?</summary><p>{_esc(howto)}</p></details>
    </form>"""


def render(key: str) -> str:
    rows = tenants.all_tenants(include_paused=True)
    if not rows:
        body = ('<div class="note">No accounts yet. Run '
                '<code>/admin/register_owner</code> first — it seeds the five.</div>')
    else:
        body = ""
        for t in rows:
            caps = tenants.capabilities(t.key)
            missing = [c for c, ok in caps.items() if not ok]
            fields = "".join(_field(t, key, f) for f in
                             ("gmail_alias", "shopify_store", "esp", "cms",
                              "ads", "analytics", "crm", "design", "systems"))
            body += f"""
            <div class="card">
              <div class="head">
                <h2>{_esc(t.name)}</h2>
                <code>{_esc(t.key)}</code>
                <span class="mut">{_esc(t.kind)} · {_esc(t.domain) or 'no domain'}</span>
              </div>
              <div class="chips">{_chips(caps)}</div>
              <div class="mut">Missing: {', '.join(missing) or 'nothing — fully wired'}</div>
              <div class="row">
                <a href="/admin/verify?key={_esc(key)}&amp;tenant={_esc(t.key)}"><button class="sec" type="button">Test connections</button></a>
                <span class="mut">chips show what is <em>configured</em>; this calls each one to see if it <em>works</em></span>
              </div>
              <div class="grid">{fields}</div>
            </div>"""

    return _shell(key, "accounts", "Accounts", f"""
<div>
  <h1>Accounts</h1>
  <p class="mut">Values here are <strong>keys into</strong> credential dictionaries or
  env-var names — never the secrets themselves. API keys and tokens live in
  Render env vars.</p>
</div>

<div class="card">
  <div class="head"><h2>Add an account</h2></div>
  <form method="get" action="/admin/tenant_add" class="grid">
    <input type="hidden" name="key" value="{_esc(key)}">
    <div class="f"><label>tenant key</label>
      <div class="what">Short and lowercase — you'll type it often</div>
      <input name="tenant" placeholder="acme" required></div>
    <div class="f"><label>name</label>
      <div class="what">Shown in /clients</div>
      <input name="name" placeholder="Acme Co" required></div>
    <div class="f"><label>domain</label>
      <div class="what">Used for enrichment</div>
      <input name="domain" placeholder="acme.com"></div>
    <div class="f"><label>kind</label>
      <div class="what">'own' for your businesses, 'client' otherwise</div>
      <select name="kind"><option value="client">client</option>
        <option value="own">own</option></select>
      <div class="row"><button>Create</button></div></div>
  </form>
</div>

<div class="card">
  <div class="head"><h2>Give someone bot access</h2></div>
  <p class="mut">They message the bot first — it replies with their chat id
  because it doesn't recognise them. Paste that id here.</p>
  <form method="get" action="/admin/user_add" class="grid">
    <input type="hidden" name="key" value="{_esc(key)}">
    <div class="f"><label>chat id</label>
      <div class="what">From their first message to the bot</div>
      <input name="chat_id" placeholder="123456789" required></div>
    <div class="f"><label>name</label><div class="what">For your reference</div>
      <input name="name" placeholder="Ellis"></div>
    <div class="f"><label>role</label>
      <div class="what">client and freelancer are pinned to one account</div>
      <select name="role"><option>client</option><option>freelancer</option>
        <option>owner</option></select></div>
    <div class="f"><label>tenant</label>
      <div class="what">Required unless owner</div>
      <input name="tenant" placeholder="coverings">
      <div class="row"><button>Grant access</button></div></div>
  </form>
  <div class="note"><strong>Not yet.</strong> Ops commands are scoped correctly, but
  free-text questions fall through to an agent that is not tenant-scoped. Hold off
  on client access until reporting and agent scoping land.</div>
</div>

{body}

<p class="mut">Saving reloads to a JSON response — hit back to return here.
Changes take effect immediately; no redeploy.</p>
""")


# ---------------------------------------------------------------------------
# Systems tab
# ---------------------------------------------------------------------------

def _rung(current: str) -> str:
    at = systems.AUTONOMY.index(current if current in systems.AUTONOMY else "shadow")
    steps = "".join(
        f'<span class="step {"at" if i == at else ("done" if i < at else "")}">'
        f'{r.replace("_", " ")}</span>'
        for i, r in enumerate(systems.AUTONOMY))
    return (f'<div class="rung">{steps}</div>'
            f'<div class="mut">{_esc(systems.AUTONOMY_MEANING.get(current, ""))}</div>')


def _contract_form(key: str, row) -> str:
    fields = "".join(f"""
      <div class="f"><label>{label}</label>
        <div class="what">{_esc(hint)}</div>
        <textarea name="{f}" rows="2" placeholder="empty">{_esc(getattr(row, f, "") or "")}</textarea>
      </div>""" for f, label, hint in systems.CONTRACT)
    return f"""
    <details><summary>The contract — 8 questions a system answers before it runs</summary>
      <form method="get" action="/admin/system_set" style="margin-top:10px">
        <input type="hidden" name="key" value="{_esc(key)}">
        <input type="hidden" name="id" value="{_esc(row.id)}">
        <div class="sysgrid">{fields}</div>
        <div class="row" style="margin-top:10px"><button>Save contract</button>
        <span class="mut">A system can't go live until every one is filled.</span></div>
      </form>
    </details>"""


def _thread(key: str, row) -> str:
    msgs = systems.notes(row.tenant, row.key)
    if msgs:
        body = "".join(f"""
        <div class="msg"><div>{_esc(m.content)}</div>
          <div class="when">{m.created_at:%b %d, %H:%M} ·
            <a href="/admin/system_note?key={_esc(key)}&amp;drop={_esc(m.id)}">archive</a></div>
        </div>""" for m in msgs)
    else:
        body = ('<p class="mut">Nothing yet. Corrections you write here are injected '
                'into this system\'s drafting prompt — and only this one.</p>')
    return f"""
    <details><summary>Thread — guidance and corrections ({len(msgs)})</summary>
      <div class="thread" style="margin-top:10px">{body}</div>
      <form method="get" action="/admin/system_note" style="margin-top:12px">
        <input type="hidden" name="key" value="{_esc(key)}">
        <input type="hidden" name="id" value="{_esc(row.id)}">
        <div class="f"><label>guidance</label>
          <div class="what">Prose. Shapes how this system drafts — it does not enforce.</div>
          <textarea name="text" rows="2" placeholder="Lead with the number, not the greeting."></textarea>
          <div class="row"><button>Add to thread</button></div>
        </div>
      </form>
      <form method="get" action="/admin/system_rule" style="margin-top:8px">
        <input type="hidden" name="key" value="{_esc(key)}">
        <input type="hidden" name="id" value="{_esc(row.id)}">
        <div class="f"><label>hard rule</label>
          <div class="what">A phrase that must never appear. Enforced by the validator,
          which is code and fails closed — use this for anything that must ALWAYS hold.</div>
          <input name="phrase" placeholder="handcrafted">
          <div class="row"><button>Make it a rule</button></div>
        </div>
      </form>
    </details>"""


def _runs(row, total: int) -> str:
    rows = systems.runs(row.id, limit=8)
    if not rows:
        return ('<details><summary>Runs (0)</summary>'
                '<p class="mut" style="margin-top:10px">Nothing has run yet.</p></details>')
    lines = "".join(f"""
      <div class="msg"><div><code>{_esc(r.stage)}</code>
        {_esc(r.decision or "")} {_esc((r.blocked_on or [""])[0] if r.stage == "blocked" else "")}</div>
        <div class="when">{r.created_at:%b %d, %H:%M} · {_esc(r.trigger or "")}</div></div>"""
        for r in rows)
    more = f" — showing the last {len(rows)}" if total > len(rows) else ""
    return (f'<details><summary>Runs ({total}){more}</summary>'
            f'<div class="thread" style="margin-top:10px">{lines}</div></details>')


def _system_card(key: str, row) -> str:
    r = systems.ready(row)
    st = systems.stats(row.id)
    nxt = systems.can_promote(row)

    if r["ready"]:
        gate = '<div class="ok">Ready. Everything it needs is connected and the contract is complete.</div>'
    else:
        gate = ('<div class="note"><strong>Blocked.</strong><ul class="bl">'
                + "".join(f"<li>{_esc(b)}</li>" for b in r["blockers"])
                + "</ul></div>")

    if nxt["can"]:
        promo = (f'<a href="/admin/system_promote?key={_esc(key)}&amp;id={_esc(row.id)}">'
                 f'<button type="button">Promote to {_esc(nxt["target"].replace("_", " "))}</button></a>')
    elif nxt["target"]:
        promo = f'<span class="mut">Next rung ({_esc(nxt["target"].replace("_", " "))}): {_esc(nxt["why"])}</span>'
    else:
        promo = '<span class="mut">Top of the ladder.</span>'

    live = ""
    if row.status != "live" and r["ready"]:
        live = (f'<a href="/admin/system_set?key={_esc(key)}&amp;id={_esc(row.id)}&amp;status=live">'
                f'<button type="button">Switch on</button></a>')
    elif row.status == "live":
        live = (f'<a href="/admin/system_set?key={_esc(key)}&amp;id={_esc(row.id)}&amp;status=paused">'
                f'<button class="sec" type="button">Pause</button></a>')

    return f"""
    <div class="card">
      <div class="head">
        <h3>{_esc(row.name)}</h3>
        <code>{_esc(row.key)}</code>
        <span class="chips">
          <span class="chip {'on' if row.status == 'live' else 'off'}">{_esc(row.status)}</span>
          <span class="chip {'on' if row.autonomy == 'auto' else 'off'}">{_esc(row.autonomy)}</span>
        </span>
      </div>
      <div class="mut">{_esc(systems.spec(row.key)["does"])}</div>
      {gate}
      {_rung(row.autonomy or "shadow")}
      <div class="stat">
        <span><b>{st['total']}</b> runs</span>
        <span><b>{st['approved']}</b> approved</span>
        <span><b>{st['edited']}</b> edited</span>
        <span><b>{st['denied']}</b> denied</span>
        <span><b>{st['blocked']}</b> blocked</span>
      </div>
      <div class="row">{live}{promo}</div>
      {_contract_form(key, row)}
      {_thread(key, row)}
      {_runs(row, st['total'])}
    </div>"""


def render_systems(key: str) -> str:
    rows = systems.all_systems()

    if not rows:
        body = ('<div class="note">No systems yet. '
                '<a href="/admin/systems_seed?key=' + _esc(key) + '">Adopt the ones already '
                'named on each account</a> — it reads <code>Tenant.systems</code> and '
                'creates a row for each, with an empty contract.</div>')
    else:
        by_tenant: dict[str, list] = {}
        for r in rows:
            by_tenant.setdefault(r.tenant, []).append(r)
        body = ""
        for tkey, group in by_tenant.items():
            t = tenants.get(tkey)
            cards = "".join(_system_card(key, r) for r in group)
            live = sum(1 for r in group if r.status == "live")
            body += f"""
            <div>
              <div class="head" style="margin-bottom:12px">
                <h2>{_esc(t.name if t else tkey)}</h2>
                <code>{_esc(tkey)}</code>
                <span class="mut">{live} of {len(group)} live</span>
              </div>
              {cards}
            </div>"""

    backlog = systems.blocked_reasons()
    backlog_html = ""
    if backlog:
        items = "".join(f"<li><b>{n}×</b> {_esc(reason)}</li>" for reason, n in backlog[:10])
        backlog_html = f"""
        <div class="card">
          <div class="head"><h2>What the systems refused on</h2></div>
          <p class="mut">Last 30 days, most frequent first. This is the knowledge-base
          backlog ranked by how often each gap actually cost an output — fix from the top.</p>
          <ul class="bl">{items}</ul>
        </div>"""

    opts = "".join(f'<option value="{k}">{v["name"]}</option>'
                   for k, v in systems.CATALOG.items())
    tenant_opts = "".join(f'<option value="{_esc(t.key)}">{_esc(t.name)}</option>'
                          for t in tenants.all_tenants(include_paused=True))

    return _shell(key, "systems", "Systems", f"""
<div>
  <h1>Systems</h1>
  <p class="mut">One row per installed pipeline. A system is not on because it has a
  name — it is on when its contract is answered, its connections work, and the
  knowledge base can ground it. Everything below refuses in public rather than
  guessing in private.</p>
</div>

{backlog_html}

<div class="card">
  <div class="head"><h2>Install a system</h2></div>
  <form method="get" action="/admin/system_add" class="grid">
    <input type="hidden" name="key" value="{_esc(key)}">
    <div class="f"><label>account</label>
      <div class="what">Who it runs for</div>
      <select name="tenant">{tenant_opts}</select></div>
    <div class="f"><label>system</label>
      <div class="what">Starts as designed / shadow — it records but sends nothing</div>
      <select name="system">{opts}</select>
      <div class="row"><button>Install</button></div></div>
  </form>
</div>

{body}

<p class="mut">Guidance shapes drafting. Rules are enforced by code. When a correction
matters every single time, make it a rule — a prompt that usually obeys is not a control.</p>
""")
