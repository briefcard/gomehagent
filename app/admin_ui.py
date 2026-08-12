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

from . import config, db, kb, systems, tenants

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
.chip.nb{background:var(--rule2);color:var(--ink2);border:1px solid var(--rule)}
.kv{display:grid;grid-template-columns:130px 1fr;gap:5px 14px;margin:0;font-size:.85rem}
.kv dt{color:var(--mut);font-size:.72rem;text-transform:uppercase;letter-spacing:.06em;
font-weight:700;padding-top:2px}
.kv dd{margin:0;color:var(--ink2);min-width:0;overflow-wrap:anywhere}
@media(max-width:560px){.kv{grid-template-columns:1fr;gap:1px 0}.kv dd{margin-bottom:7px}}
details.sec{border:1px solid var(--rule);border-radius:5px;padding:9px 12px;background:var(--rule2)}
details.sec>summary{cursor:pointer;font-weight:600;font-size:.88rem;color:var(--acc)}
details.sec[open]>summary{margin-bottom:9px;border-bottom:1px solid var(--rule);padding-bottom:7px}
.msg.gone{opacity:.62}
.msg.esc{border-left-color:var(--gap)}\n.tags{display:flex;flex-wrap:wrap;gap:4px 10px}\n.tags .tag{font-size:.78rem;color:var(--ink2);display:flex;align-items:center;gap:4px;white-space:nowrap}\n.tags input{width:auto}
"""

_TABS = (("accounts", "Accounts"), ("systems", "Systems"), ("kb", "Knowledge"),
         ("content", "Content"))


def _shell(key: str, tab: str, title: str, body: str, suffix: str = "") -> str:
    nav = "".join(
        f'<a class="{"on" if t == tab else ""}" '
        f'href="/admin/ui?key={_esc(key)}&amp;tab={t}{suffix if t == tab else ""}">{label}</a>'
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


# ---------------------------------------------------------------------------
# Knowledge tab
#
# The KB had no read surface at all — `/kb` returned four counts, which tells
# you a claim exists but never which one, or whether it is any good. Everything
# the generators will be grounded in is shown here in full, because proof you
# cannot read is proof you cannot trust.
# ---------------------------------------------------------------------------

def _kb_add_form(key: str, tenant: str, step_id: str, label: str,
                 hint: str, rows: int = 2) -> str:
    return f"""
    <form class="f" method="get" action="/admin/kb_add">
      <input type="hidden" name="key" value="{_esc(key)}">
      <input type="hidden" name="tenant" value="{_esc(tenant)}">
      <input type="hidden" name="step" value="{step_id}">
      <label>{_esc(label)}</label>
      <div class="what">{_esc(hint)}</div>
      <textarea name="text" rows="{rows}" placeholder="{_esc(hint)}"></textarea>
      <div class="row"><button>Add</button></div>
    </form>"""


def _kb_list(title: str, items: list[str], empty: str, open: bool = False) -> str:
    if not items:
        return (f'<details class="sec"><summary>{_esc(title)} (0)</summary>'
                f'<p class="mut" style="margin-top:10px">{_esc(empty)}</p></details>')
    body = "".join(f'<div class="msg">{i}</div>' for i in items)
    return (f'<details class="sec"{" open" if open else ""}>'
            f'<summary>{_esc(title)} ({len(items)})</summary>'
            f'<div class="thread">{body}</div></details>')


# --- value formatters -------------------------------------------------------
#
# Every one of these renders "not set" differently from "set to nothing useful",
# because the whole premise of the KB is that a missing field blocks a pipeline.
# A blank space where a value should be tells the reader nothing at all.

def _mut(msg: str) -> str:
    return f'<span class="mut">{_esc(msg)}</span>'


def _kv(pairs: list[tuple[str, str]]) -> str:
    """Label/value rows. Pairs whose value is empty are dropped by the caller,
    never silently — an absent field gets an explicit 'not set' value instead."""
    body = "".join(f"<dt>{_esc(k)}</dt><dd>{v}</dd>" for k, v in pairs)
    return f'<dl class="kv">{body}</dl>'


def _words(items, empty: str = "not set") -> str:
    """A list of short values. A bare string is treated as one value, not as a
    list of characters — `voice.do_say` has no writer that normalises it, and
    rendering "d, i, r, e, c, t" would look like corrupted data rather than a
    shape mismatch."""
    if isinstance(items, str):
        items = [items] if items.strip() else []
    items = [str(i) for i in (items or []) if str(i).strip()]
    return _esc(", ".join(items)) if items else _mut(empty)


def _attr_chips(d: dict) -> str:
    if not d:
        return ""
    return '<div class="chips">' + "".join(
        f'<span class="chip nb">{_esc(str(k).replace("_", " "))} '
        f'<b>{_esc(v)}</b></span>' for k, v in d.items()) + "</div>"


def _date(v) -> str:
    if not v:
        return ""
    try:
        return db.as_utc(v).date().isoformat()
    except Exception:
        return str(v)[:10]


def _selection_line(cfg: dict) -> str:
    """How this tenant's catalogue gets ranked — the thing that decided a
    200-seat room was offered for 220 guests. It belongs on screen."""
    if not cfg:
        return _mut("not set — falls back to keyword relevance over every type")
    bits = []
    if cfg.get("primary_type"):
        bits.append(f'ranks <code>{_esc(cfg["primary_type"])}</code>')
    for m in cfg.get("modes") or []:
        mode = m.get("mode", "")
        if not mode:
            continue
        detail = ""
        if m.get("requirement"):
            detail = f' on <code>{_esc(m["requirement"])}</code>'
            attrs = m.get("attributes") or {}
            if attrs:
                detail += " → " + ", ".join(
                    f'{_esc(k)}: <code>{_esc(v)}</code>' for k, v in attrs.items())
        bits.append(f"<b>{_esc(mode)}</b>{detail}")
    return " · ".join(bits) if bits else _mut("not set")


def _approval_policy_html(policy: dict) -> str:
    """Which assets go out unattended and which need a signature. An empty policy
    is not 'no policy' — it decides behaviour, so it is shown either way."""
    if not policy:
        return ('<div class="mut">Approval policy not set — nothing is marked '
                'auto-publishable, so everything waits for a human.</div>')
    auto = policy.get("auto_publish") or []
    signoff = policy.get("requires_signoff") or []
    return _kv([
        ("auto publish", _words(auto, "nothing — all output waits for approval")),
        ("needs signoff", _words(signoff, "nothing listed")),
    ])


def _next_steps_line(steps: dict) -> str:
    """What the tenant asks for at the end of a draft. Silently emptied once by
    a migration, which produced blank asks on every agency brief and was visible
    nowhere but the rendered output."""
    if not steps:
        return _mut("not set — every draft ends with a blank ask")
    return "<br>".join(
        f'<code>{_esc(stage)}</code> {_esc((v or {}).get("ask", ""))}'
        for stage, v in steps.items())


def render_kb(key: str, tenant: str = "") -> str:
    rows = tenants.all_tenants(include_paused=True)
    tenant = tenant or (rows[0].key if rows else "")
    t = tenants.get(tenant)

    picker = "".join(
        f'<a class="{"on" if r.key == tenant else ""}" '
        f'href="/admin/ui?key={_esc(key)}&amp;tab=kb&amp;tenant={_esc(r.key)}">'
        f'{_esc(r.name)}</a>' for r in rows)

    if not t:
        return _shell(key, "kb", "Knowledge",
                      '<div class="note">No accounts yet. Run '
                      '<code>/admin/register_owner</code> first.</div>')

    c = kb.completeness(tenant)
    gaps = kb.gaps(tenant)
    b = kb.brand(tenant)
    voice = (b.voice or {}) if b else {}

    if gaps:
        nxt = gaps[0]
        ask = f"""
        <div class="card">
          <div class="head"><h2>Next most useful question</h2>
            <span class="chip off">{len(gaps)} missing</span></div>
          <p><strong>{_esc(nxt['q'])}</strong></p>
          <p class="mut">{_esc(nxt['hint'])}</p>
          <form class="f" method="get" action="/admin/kb_add">
            <input type="hidden" name="key" value="{_esc(key)}">
            <input type="hidden" name="tenant" value="{_esc(tenant)}">
            <input type="hidden" name="step" value="{nxt['id']}">
            <textarea name="text" rows="2" placeholder="{_esc(nxt['hint'])}"></textarea>
            <div class="row"><button>Answer</button>
            <span class="mut">or send <code>/next</code> to the bot and reply there</span></div>
          </form>
        </div>"""
    else:
        ask = ('<div class="card"><div class="head"><h2>Complete</h2>'
               '<span class="chip on">ready</span></div>'
               '<p class="mut">Everything the pipeline requires is present. More proof '
               'is still better than less — keep adding claims as they are earned.</p></div>')

    banned = (b.banned_claims or []) if b else []
    banned_html = "".join(f'<span class="chip off">{_esc(p)}</span>' for p in banned) \
        or '<span class="mut">None — the validator has nothing to enforce.</span>'

    # --- claims, split by whether they can actually be used ------------------
    inv = kb.claim_inventory(tenant)

    def _claim_msg(r, note: str = "", cls: str = "") -> str:
        meta = " · ".join(x for x in [
            _esc(r.strength or ""), _esc(r.proof_type or ""),
            f"verified {_date(r.verified_at)}" if r.verified_at else "",
            f"expires {_date(r.expires_at)}" if r.expires_at else "",
        ] if x)
        tags = " ".join(r.situations or []) or "untagged — can never be selected"
        return (f'<div class="msg {cls}">'
                f"<div>{_esc(r.claim)}</div>"
                + (f'<div class="when"><strong>{_esc(r.evidence)}</strong></div>'
                   if r.evidence else
                   '<div class="when"><span class="mut">no evidence recorded</span></div>')
                + f'<div class="when"><code>{_esc(tags)}</code></div>'
                + f'<div class="when">{meta}{" · " if meta else ""}'
                f'{_esc(r.source or "source not recorded")}</div>'
                + (f'<div class="when"><b>{_esc(kb.usage_rule(r.proof_type))}</b></div>'
                   if kb.usage_rule(r.proof_type or "") else "")
                + (f'<div class="when"><b>{_esc(note)}</b></div>' if note else "")
                + "</div>")

    def _claim_block(title: str, rows_, empty: str, note: str = "",
                     cls: str = "", open_: bool = False) -> str:
        if not rows_:
            return (f'<details class="sec"><summary>{_esc(title)} (0)</summary>'
                    f'<p class="mut" style="margin-top:10px">{_esc(empty)}</p></details>')
        body = "".join(_claim_msg(r, note, cls) for r in rows_)
        return (f'<details class="sec"{" open" if open_ else ""}>'
                f'<summary>{_esc(title)} ({len(rows_)})</summary>'
                f'<div class="thread">{body}</div></details>')

    claims_html = (
        _claim_block("Claims — selectable", inv["selectable"],
                     "No usable proof. Any draft that needs a number is blocked.")
        + _claim_block("Claims — awaiting review", inv["pending"],
                       "Nothing submitted for review.",
                       "not selectable until approved", "gone")
        + _claim_block("Claims — expired", inv["expired"],
                       "Nothing has gone stale.",
                       "past its expiry date, so selection skips it", "gone")
        + _claim_block("Claims — retired", inv["retired"],
                       "Nothing retired.", "withdrawn from selection", "gone"))

    aud_html = _kb_list("Audiences", [
        f"<div><strong>{_esc(r.name)}</strong> <code>{_esc(r.key)}</code></div>"
        + _kv([("pains", _words(r.pains, "none recorded")),
               ("their words", _words(r.vocabulary,
                                      "none — selection cannot recognise this buyer")),
               ("buying trigger", _esc(r.buying_trigger) or _mut("not set")),
               ("decides in", _esc(r.decision_timeline) or _mut("not set"))]
              + ([("notes", _esc(r.notes))] if r.notes else []))
        for r in kb.audiences(tenant)],
        "No segments. Selection cannot narrow to a buyer.")

    obj_html = _kb_list("Objections", [
        f'<div><strong>{_esc(r.objection)}</strong>'
        + (' <span class="chip off">escalate</span>'
           if (r.escalate or "").lower() == "yes" else "")
        + "</div>"
        + f"<div>{_esc(r.response)}</div>"
        + f'<div class="when">'
        + (f"segment <code>{_esc(r.audience_key)}</code>"
           if r.audience_key else "applies to everyone")
        + (f" · paired proof <code>{_esc(r.claim_id)}</code>" if r.claim_id else "")
        + "</div>"
        for r in kb.objections(tenant)],
        "None. This is human-authored and it is half of the intake.")

    ents = kb.entities(tenant, available_only=False)
    ent_html = _kb_list("Things they sell", [
        f'<div><strong>{_esc(r.name)}</strong> <code>{_esc(r.type)}</code> '
        f"{_esc(r.price) or _mut('no price')}"
        + ("" if (r.availability or "available") == "available"
           else f' <span class="chip off">{_esc(r.availability)}</span>')
        + "</div>"
        + f'<div class="when">{_esc(r.description) or _mut("no description")}</div>'
        + _attr_chips(r.attributes or {})
        + f'<div class="when"><code>{_esc(r.key)}</code> · '
        + _esc(r.source or "source not recorded")
        + (f" · verified {_date(r.verified_at)}" if r.verified_at else "")
        + (f" · goes stale after {_esc(r.freshness_days)} days"
           if r.freshness_days else "")
        + "</div>"
        for r in ents],
        "Nothing catalogued. Selection has nothing to offer.")

    # --- the tenant's own diagnostic vocabulary ------------------------------
    sits = kb.situation_rows(tenant)
    if sits:
        sit_body = "".join(
            f'<div class="msg"><div><code>{_esc(r.tag)}</code> '
            f'<span class="chip nb">{_esc(r.kind or "problem")}</span></div>'
            f'<div class="when">{_esc(r.description) or _mut("no description")}</div>'
            f'<div class="when">triggers on: '
            + (_esc(", ".join(" ".join(p) for p in (r.patterns or []) if p))
               or _mut("no patterns — diagnosis can never assign this tag"))
            + "</div></div>" for r in sits)
        sit_note = (f'<p class="mut">These {len(sits)} tags are the only ones a claim '
                    f'for {_esc(t.name)} may carry. A claim tagged with anything else '
                    f'is refused on the way in.</p>')
    else:
        sit_body = ""
        sit_note = ('<div class="note">No vocabulary authored, so this account '
                    'silently inherits the agency\'s B2B language — which no venue '
                    'or product enquiry will ever match. Claims tagged in this '
                    'account\'s own words will be refused until tags exist here.</div>')

    # --- gaps the selection loop actually hit --------------------------------
    unk = kb.unknowns(tenant)
    closed = len(kb.unknowns(tenant, status="answered")) + \
        len(kb.unknowns(tenant, status="not_applicable"))
    if unk:
        unk_body = "".join(
            f'<div class="msg"><div><strong>{_esc(r.entity_name or r.entity_key)}</strong> '
            f'— {_esc((r.attribute or "").replace("_", " "))} unknown</div>'
            f'<div class="when">blocked an answer {_esc(r.hits)}× · last asked: '
            f'{_esc(r.asked_for or "—")}</div>'
            f'<form class="f" method="get" action="/admin/kb_unknown" '
            f'style="margin-top:6px">'
            f'<input type="hidden" name="key" value="{_esc(key)}">'
            f'<input type="hidden" name="tenant" value="{_esc(tenant)}">'
            f'<input type="hidden" name="id" value="{_esc(r.id)}">'
            f'<div class="row"><input name="value" placeholder="the value, or n/a">'
            f'<button>Save</button></div></form></div>' for r in unk)
        unk_card = f"""
    <div class="card">
      <div class="head"><h2>Gaps that cost an answer</h2>
        <span class="chip off">{len(unk)} open</span></div>
      <p class="mut">Ranked by how often each one blocked a real enquiry — not every
      empty field, only the ones that lost something. Answering writes the value
      straight onto the item and it becomes matchable immediately.</p>
      <div class="thread">{unk_body}</div>
    </div>"""
    else:
        unk_card = f"""
    <div class="card">
      <div class="head"><h2>Gaps that cost an answer</h2>
        <span class="chip on">none open</span></div>
      <p class="mut">Nothing has been asked for that this account could not answer.
      {closed} gap(s) closed so far.</p>
    </div>"""

    forms = (
        _kb_add_form(key, tenant, "claim", "Add a claim",
                     "claim | evidence | situation tags (spaces)")
        + _kb_add_form(key, tenant, "objection", "Add an objection",
                       "objection | your approved answer")
        + _kb_add_form(key, tenant, "audience", "Add an audience",
                       "key | name | pains (semicolons) | their words (semicolons)")
        + _kb_add_form(key, tenant, "entity", "Add something they sell",
                       "type | key | name | price | description")
        + _kb_add_form(key, tenant, "banned_claims", "Add a hard rule",
                       "phrases the validator must reject, separated by semicolons", 1)
        + _kb_add_form(key, tenant, "positioning", "Set positioning",
                       "one sentence: what they do, and for whom")
        + _kb_add_form(key, tenant, "tone", "Set voice",
                       "three or four words, comma separated", 1))

    return _shell(key, "kb", "Knowledge", f"""
<div>
  <h1>Knowledge</h1>
  <p class="mut">Everything the generators are allowed to say, per account. A draft
  may assert nothing that is not on this page — which is why an empty section here
  is a blocked pipeline there, not a cosmetic gap.</p>
</div>

<div class="tabs">{picker}</div>

<div class="card">
  <div class="head">
    <h2>{_esc(t.name)}</h2><code>{_esc(tenant)}</code>
    <span class="chips">
      <span class="chip {'on' if c['ready'] else 'off'}">{'ready' if c['ready'] else 'not ready'}</span>
    </span>
  </div>
  <div class="stat">
    <span><b>{c['counts'].get('claims', 0)}</b> claims</span>
    <span><b>{c['counts'].get('audiences', 0)}</b> audiences</span>
    <span><b>{c['counts'].get('objections', 0)}</b> objections</span>
    <span><b>{c['counts'].get('entities', 0)}</b> entities</span>
    <span><b>{len(sits)}</b> situations</span>
    <span><b>{len(banned)}</b> hard rules</span>
    <span><b>{len(unk)}</b> open gaps</span>
  </div>
  {_kv([
    ("positioning", _esc(b.positioning if b else "") or _mut("not set")),
    ("elevator", _esc((b.elevator or {}).get("sentence", "") if b else "")
                 or _mut("not set")),
    ("tone", _words(voice.get("tone"))),
    ("do say", _words(voice.get("do_say"), "nothing specified")),
    ("never say", _words(voice.get("never_say"), "nothing specified")),
    ("selection", _selection_line(kb.selection_config(tenant))),
    ("next steps", _next_steps_line((b.next_steps or {}) if b else {})),
  ])}
  <div><span class="mut">Hard rules the validator enforces:</span></div>
  <div class="chips">{banned_html}</div>
  {_approval_policy_html((b.approval_policy or {}) if b else {})}
</div>

{ask}

<div class="card">
  <div class="head"><h2>Situations — this account's vocabulary</h2>
    <span class="chip {'on' if sits else 'off'}">{len(sits)} tags</span></div>
  {sit_note}
  <div class="thread">{sit_body}</div>
</div>

<div class="card">
  <div class="head"><h2>What is in there</h2></div>
  {claims_html}
  {aud_html}
  {obj_html}
  {ent_html}
</div>

{unk_card}

<div class="card">
  <div class="head"><h2>Add to {_esc(t.name)}</h2></div>
  <div class="grid">{forms}</div>
</div>

<p class="mut">The same captures work from Telegram — <code>/next</code> asks these
one at a time and reads your reply as the answer.</p>
""", suffix=f"&amp;tenant={tenant}")


# ---------------------------------------------------------------------------
# Client intake — the one surface a client ever sees.
#
# Scoped to a single tenant by an unguessable token. No secret key, no other
# account reachable, no schema on display: one question at a time in the words
# the client already uses. Answers go through the SAME parser as the console and
# the bot, so a fact entered here and one entered by Gomeh land identically —
# which is the property that makes onboarding client #6 cost days, not weeks.
# ---------------------------------------------------------------------------

_INTAKE_CSS = _CSS + """
.w{max-width:680px}
.prog{display:flex;gap:4px;margin-bottom:4px}
.prog i{flex:1;height:4px;border-radius:2px;background:var(--rule)}
.prog i.on{background:var(--ok)}
.q{font:600 1.35rem/1.3 Georgia,serif;margin:0}
.why{font-size:.83rem;color:var(--acc);font-weight:600}
.done{text-align:center;padding:30px 0}
"""


def render_intake(link, tenant, step, done: int, total: int,
                  waiting: list[str], saved: str = "") -> str:
    """One question. No navigation, no schema, no way to reach anything else."""
    t = tenants.get(tenant)
    name = _esc(t.name if t else tenant)

    if step is None:
        body = f"""
        <div class="card done">
          <h1>That's everything — thank you.</h1>
          <p class="mut">We have what we need to start writing for {name}.
          Nothing you sent goes out without being reviewed first.</p>
        </div>"""
    else:
        bars = "".join(f'<i class="{"on" if i < done else ""}"></i>'
                       for i in range(max(total, 1)))
        why = ""
        if waiting:
            why = (f'<div class="why">Needed by: {_esc(", ".join(waiting))}</div>')
        body = f"""
        <div class="card">
          <div class="prog">{bars}</div>
          <div class="mut">Question {done + 1} of {total}</div>
          <h2 class="q">{_esc(step['q'])}</h2>
          <p class="mut">{_esc(step['hint'])}</p>
          {why}
          <form method="get" action="/intake/{_esc(link.token)}">
            <textarea name="answer" rows="3" autofocus
              placeholder="{_esc(step['hint'])}"></textarea>
            <div class="row" style="margin-top:10px">
              <button>Save and continue</button>
              <a href="/intake/{_esc(link.token)}?skip={_esc(step['id'])}"
                 class="mut">skip this one</a>
            </div>
          </form>
        </div>"""

    note = f'<div class="ok">{_esc(saved)}</div>' if saved else ""

    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{name} — setup</title><style>{_INTAKE_CSS}</style></head><body><div class="w">
<div>
  <h1>{name}</h1>
  <p class="mut">A few questions so we can write in your voice and never say
  anything you wouldn't. Answer what you can — anything you skip, we'll ask
  again later rather than guess.</p>
</div>
{note}
{body}
<p class="mut">This link is private to {name}. Nothing here is published.</p>
</div></body></html>"""


# ---------------------------------------------------------------------------
# Content tab — what the site says, what the catalogue holds, what is proposed.
#
# The three things behind this tab were built as JSON routes and nothing else,
# which is §2.13 committed again: a compliance report that lives only in the
# response that triggered it has to be re-run to be read twice. The queue of
# proposals matters most — approving one meant finding its id in JSON and
# hand-writing a URL, which nobody does thirty times, and an unreviewed queue
# is worse than no queue because `pending` rows look like progress while being
# invisible to selection.
# ---------------------------------------------------------------------------

_STARTED = {
    "scan": "Scan started. It reads the live site, so give it a minute — "
            "refresh this page and the result will be below.",
    "harvest": "Harvest started. Proposals will appear above when it finishes.",
    "sync": "Catalogue sync started. Refresh in a moment.",
}


def _act(key: str, action: str, label: str, tenant: str = "",
         extra: dict | None = None, small: bool = False) -> str:
    """A one-click button that runs something and comes back to this tab."""
    hidden = "".join(
        f'<input type="hidden" name="{_esc(k)}" value="{_esc(v)}">'
        for k, v in {"key": key, "tenant": tenant, "ui": "1",
                     **(extra or {})}.items() if v != "")
    cls = ' class="sec"' if small else ""
    return (f'<form method="get" action="{_esc(action)}" style="display:inline">'
            f'{hidden}<button{cls}>{_esc(label)}</button></form>')


def render_content(key: str, tenant: str = "", started: str = "") -> str:
    from . import compliance, credentials as cred, kb as kbm

    rows = tenants.all_tenants(include_paused=True)
    tenant = tenant or (rows[0].key if rows else "")
    t = tenants.get(tenant)
    if not t:
        return _shell(key, "content", "Content",
                      '<div class="note">No accounts yet.</div>')

    picker = "".join(
        f'<a class="{"on" if r.key == tenant else ""}" '
        f'href="/admin/ui?key={_esc(key)}&amp;tab=content&amp;tenant={_esc(r.key)}">'
        f'{_esc(r.name)}</a>' for r in rows)

    # --- proposals ---------------------------------------------------------
    pending = kbm.pending_claims(tenant)
    vocab = sorted(kbm.situations(tenant))
    if pending:
        def _card(p) -> str:
            chosen = set(p.situations or [])
            # A testimonial's wording IS its evidence. The field is read-only
            # rather than merely discouraged, because rewording a review turns a
            # record of what a customer said into something the brand asserts.
            verbatim = (p.proof_type or "") in kbm.VERBATIM_ONLY
            usage = kbm.usage_rule(p.proof_type or "")
            rule = (f'<div class="note">{_esc(usage)}</div>'
                    if verbatim and usage else
                    (f'<div class="when">{_esc(usage)}</div>' if usage else ""))
            # The vocabulary as checkboxes: a tag can only ever be one the
            # account actually has, so a correction cannot invent a tag that
            # selection will never match.
            tagbox = "".join(
                f'<label class="tag"><input type="checkbox" name="tags" '
                f'value="{_esc(t)}"{" checked" if t in chosen else ""}> '
                f'{_esc(t)}</label>' for t in vocab)
            warn = ""
            if not chosen:
                warn = ('<div class="note">No tag matched. Pick at least one — '
                        'approval is refused without it, because an untagged '
                        'claim can never be selected.</div>')
            return f"""
            <form class="f" method="post" action="/admin/claim_edit">
              <input type="hidden" name="claim_id" value="{_esc(p.id)}">
              <input type="hidden" name="tenant" value="{_esc(tenant)}">
              <label>{"Quoted — a customer's own words"
                      if verbatim else "Claim"}</label>
              <textarea name="claim" rows="2"{" readonly" if verbatim else ""
                        }>{_esc(p.claim)}</textarea>
              {rule}
              <label>{"Attribution" if verbatim
                      else "Evidence — the number or the proof"}</label>
              <input name="evidence" value="{_esc(p.evidence or '')}"
                     placeholder="what makes this checkable">
              <div class="when">{_esc(p.proof_type or '')} · {_esc(p.source or '')}</div>
              {warn}
              <label>Situations</label>
              <div class="tags">{tagbox}</div>
              <div class="row">
                <button name="action" value="approve">Save &amp; approve</button>
                <button class="sec" name="action" value="save">Save only</button>
                <button class="sec" name="action" value="reject">Reject</button>
              </div>
            </form>"""
        proposals = f'<div class="grid" style="grid-template-columns:1fr">' \
                    + "".join(_card(p) for p in pending) + "</div>"
    else:
        proposals = ('<p class="mut">Nothing waiting. Harvest reads the account\'s '
                     'own site and files what it finds here — as proposals, never '
                     'as facts.</p>')

    # --- compliance --------------------------------------------------------
    scan = compliance.last_scan(tenant)
    if not scan:
        comp = ('<p class="mut">Never scanned. This checks every public page '
                'against this account\'s banned claims and lists the ones that '
                'break them.</p>')
    elif scan.get("stage") == "blocked":
        comp = ('<div class="note">Could not scan: '
                + _esc("; ".join(scan.get("blocked_on") or [])) + "</div>")
    else:
        n = scan.get("violations", 0)
        head = (f'<div class="stat"><span><b>{scan.get("pages_checked", 0)}</b> '
                f'pages checked</span><span><b>{n}</b> with a violation</span>'
                f'<span>{_esc(scan["at"].strftime("%b %d, %H:%M")) if scan.get("at") else ""}</span></div>')
        if not n:
            comp = head + '<p class="mut">Nothing on the live site breaks the rules.</p>'
        else:
            ranked = "".join(
                f'<span class="chip off">{_esc(p)} ×{c}</span>'
                for p, c in sorted((scan.get("by_phrase") or {}).items(),
                                   key=lambda kv: -kv[1]))
            items = "".join(
                f'<div class="msg esc">'
                f'<div><a href="{_esc(d["url"])}" target="_blank" rel="noopener">'
                f'{_esc(d["url"])}</a></div>'
                f'<div class="when">{_esc(", ".join(d["phrases"]))}</div>'
                f'<div class="when">“{_esc(d.get("context", ""))}”</div></div>'
                for d in (scan.get("detail") or []))
            more = (f'<p class="mut">+{scan["truncated"]} more not shown.</p>'
                    if scan.get("truncated") else "")
            comp = (head + f'<div class="chips">{ranked}</div>'
                    + f'<div class="thread">{items}</div>' + more)

    # --- catalogue ---------------------------------------------------------
    ents = kbm.entities(tenant, available_only=False)
    oos = [e for e in ents if (e.availability or "available") != "available"]
    flagged = [e for e in ents if (e.attributes or {}).get("_compliance")]
    synced = [e for e in ents if e.source == "shopify"]
    last = max((e.verified_at for e in synced if e.verified_at), default=None)
    has_store = cred.status(tenant) and tenants.capabilities(tenant).get("commerce")
    cat = (f'<div class="stat"><span><b>{len(ents)}</b> catalogued</span>'
           f'<span><b>{len(synced)}</b> from the store</span>'
           f'<span><b>{len(oos)}</b> out of stock</span>'
           f'<span><b>{len(flagged)}</b> with flagged copy</span>'
           + (f'<span>synced {_esc(db.as_utc(last).strftime("%b %d, %H:%M"))}</span>'
              if last else "") + "</div>")
    if flagged:
        cat += ('<div class="chips">' + "".join(
            f'<span class="chip off">{_esc(e.name)}</span>' for e in flagged[:10])
            + "</div><p class=\"mut\">Their storefront copy uses a banned phrase, "
              "so it was not imported. Fix the product page to clear the flag.</p>")
    if not has_store:
        cat += ('<p class="mut">No store connected, so there is nothing to sync. '
                'Products can still be added by hand on the Knowledge tab.</p>')

    banner = (f'<div class="ok">{_esc(_STARTED.get(started, ""))}</div>'
              if started in _STARTED else "")

    return _shell(key, "content", "Content", f"""
{banner}
<div>
  <h1>Content</h1>
  <p class="mut">What this account's site actually says, what its catalogue holds,
  and what has been proposed but not yet approved. Nothing here is published —
  it is the difference between what the brand allows and what is live.</p>
</div>

<div class="tabs">{picker}</div>

<div class="card">
  <div class="head"><h2>Proposed, awaiting you</h2>
    <span class="chip {'off' if pending else 'on'}">{len(pending)} pending</span></div>
  <p class="mut">Found on {_esc(t.name)}'s own site. Invisible to every generator
  until approved. Anything using a banned phrase was dropped, not queued.</p>
  {proposals}
  <div class="row">{_act(key, "/admin/harvest", "Find proposals", tenant, {"apply": "1"})}
    <span class="mut">reads the site and files what it finds</span></div>
</div>

<div class="card">
  <div class="head"><h2>Live site compliance</h2></div>
  {comp}
  <div class="row">{_act(key, "/admin/compliance_scan", "Scan now", tenant)}
    <span class="mut">checks every public page against this account's rules</span></div>
</div>

<div class="card">
  <div class="head"><h2>Catalogue</h2></div>
  {cat}
  <div class="row">{_act(key, "/admin/catalog_sync", "Sync from store", tenant)}
    <span class="mut">names, prices and live stock — the store owns those</span></div>
</div>
""", suffix=f"&amp;tenant={tenant}")


# ---------------------------------------------------------------------------
# Client connect page — the other half of onboarding.
#
# Same guarantees as the intake link: one tenant, no admin key, nothing else
# reachable. One difference that matters — this form POSTs. Every other form in
# this console is a GET, which is fine for a step id and a sentence and very much
# not fine for an API key: a query string lands in browser history, the Referer
# header and every access log on the way.
# ---------------------------------------------------------------------------

_CONNECT_CSS = _CSS + """
.w{max-width:720px}
.prov{display:flex;flex-direction:column;gap:9px;border:1px solid var(--rule);
border-radius:6px;padding:14px 16px;background:var(--panel)}
.prov.done{background:var(--oks);border-color:var(--ok)}
.prov h3{display:flex;align-items:baseline;gap:9px}
.prov .how{font-size:.82rem;color:var(--ink2);border-left:2px solid var(--rule);
padding-left:10px}
.lock{font-size:.78rem;color:var(--mut)}
"""


def render_connect(link, tenant, rows: list[dict], msg: str = "",
                   err: str = "") -> str:
    """One row per provider this account needs. Secrets are never rendered back."""
    from . import credentials as cred
    t = tenants.get(tenant)
    name = _esc(t.name if t else tenant)

    blocks = []
    for r in rows:
        spec = cred.PROVIDERS[r["provider"]]
        done = r["state"] == "connected"
        chip = (f'<span class="chip on">connected</span>' if done else
                f'<span class="chip off">{_esc(r["state"])}</span>')
        if not r["self_serve"]:
            blocks.append(f"""
            <div class="prov">
              <h3>{_esc(r['name'])} <span class="chip nb">on a call</span></h3>
              <div class="how">{_esc(spec['howto'])}</div>
            </div>""")
            continue
        extra = "".join(
            f'<label>{_esc(hint)}</label>'
            f'<input name="{_esc(f)}" placeholder="{_esc(hint)}" required>'
            for f, hint in spec["also"].items())
        detail = (f'<div class="mut">{_esc(r["detail"])}'
                  + (f' · last checked {_esc(r["last_verified"])}'
                     if r["last_verified"] else "") + "</div>") if done else ""
        blocks.append(f"""
        <div class="prov{' done' if done else ''}">
          <h3>{_esc(r['name'])} {chip}</h3>
          {detail}
          <details class="how"><summary>Where do I find this?</summary>
            <p>{_esc(spec['howto'])}</p></details>
          <form class="f" method="post" action="/connect/{_esc(link.token)}">
            <input type="hidden" name="provider" value="{_esc(r['provider'])}">
            {extra}
            <label>{_esc(spec['field'])}</label>
            <input name="secret" type="password" autocomplete="off"
                   placeholder="{_esc(spec['field'])}" required>
            <div class="row"><button>{'Replace' if done else 'Connect'}</button></div>
          </form>
        </div>""")

    note = f'<div class="ok">{_esc(msg)}</div>' if msg else ""
    if err:
        note += f'<div class="note">{_esc(err)}</div>'

    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{name} — connect your accounts</title><style>{_CONNECT_CSS}</style></head>
<body><div class="w">
<div>
  <h1>Connect {name}</h1>
  <p class="mut">So we can work on your behalf without asking you for exports.
  Each one is checked the moment you paste it, so you will know immediately if
  it is right. You can disconnect any of them at any time.</p>
</div>
{note}
<div class="grid" style="grid-template-columns:1fr">{''.join(blocks)}</div>
<p class="lock">Keys are encrypted before they are stored and are never shown
again — not on this page, and not to us. This link is private to {name}.</p>
</div></body></html>"""
