"""The client's view. Sidebar, one account, plain language.

Modelled on the shape a client already knows from tools like GoHighLevel: a
left sidebar that never moves, the account named at the top so you always know
whose data you are looking at, and each screen a small number of cards with one
idea each. The console's horizontal tab bar works for an operator who lives in
it; it does not survive somebody visiting once a month.

Three rules this follows that the console does not:

**No jargon on the page.** The client does not know what a `situation` or a
`bundle` is, and does not need to. "What people asked about" is the same number
with a name they can read.

**Nothing operational.** No systems, no autonomy rungs, no validator internals,
no other accounts. Not because it is secret, but because a screen that shows a
client machinery they cannot act on teaches them the tool is not for them.

**A missing number says why.** The same rule the reports follow: a figure we
cannot produce is shown with the reason and, where it is theirs to give, the
question — never left out so the page looks complete.
"""
from __future__ import annotations

from html import escape as _e

_CSS = """
*{box-sizing:border-box}
:root{--ink:#101828;--ink2:#475467;--mut:#98a2b3;--line:#e4e7ec;
--bg:#f9fafb;--panel:#fff;--acc:#155eef;--accs:#eff4ff;--ok:#067647;--oks:#ecfdf3;
--warn:#b54708;--warns:#fffaeb}
body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif}
a{color:var(--acc);text-decoration:none}
.shell{display:flex;min-height:100vh}
.side{width:236px;flex:0 0 236px;background:var(--panel);
border-right:1px solid var(--line);padding:20px 14px;display:flex;
flex-direction:column;gap:2px}
.brand{font-weight:700;font-size:1.02rem;padding:0 10px 16px;letter-spacing:-.01em}
.side a{display:flex;align-items:center;gap:10px;padding:9px 10px;border-radius:7px;
color:var(--ink2);font-weight:500;font-size:.92rem}
.side a:hover{background:var(--bg)}
.side a.on{background:var(--accs);color:var(--acc);font-weight:600}
.side .ico{width:18px;text-align:center;opacity:.85}
.side .foot{margin-top:auto;padding-top:14px;border-top:1px solid var(--line)}
.side .foot a{font-size:.85rem;color:var(--mut)}
.main{flex:1;min-width:0;padding:26px 32px 60px}
.top{display:flex;align-items:baseline;gap:12px;margin-bottom:22px;flex-wrap:wrap}
h1{font-size:1.45rem;margin:0;letter-spacing:-.02em}
.since{color:var(--mut);font-size:.88rem}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(232px,1fr));gap:14px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:11px;
padding:18px 20px}
.card h2{font-size:.82rem;margin:0 0 14px;text-transform:uppercase;
letter-spacing:.06em;color:var(--mut);font-weight:600}
.stat{font-size:2rem;font-weight:650;letter-spacing:-.03em;line-height:1.1}
.stat.none{font-size:1rem;font-weight:500;color:var(--mut);line-height:1.5}
.lab{color:var(--ink2);font-size:.88rem;margin-top:5px}
.why{color:var(--mut);font-size:.8rem;margin-top:8px;line-height:1.5}
.row{display:flex;justify-content:space-between;gap:14px;padding:9px 0;
border-bottom:1px solid var(--line);font-size:.92rem}
.row:last-child{border-bottom:0}
.row .n{font-variant-numeric:tabular-nums;color:var(--ink2)}
.pill{display:inline-block;font-size:.72rem;font-weight:600;padding:3px 9px;
border-radius:99px;background:var(--accs);color:var(--acc)}
.pill.ok{background:var(--oks);color:var(--ok)}
.pill.warn{background:var(--warns);color:var(--warn)}
.ask{background:var(--warns);border:1px solid #fedf89;border-radius:11px;
padding:18px 20px;margin-bottom:16px}
.ask h2{color:var(--warn)}
.ask li{margin-bottom:11px}
.empty{color:var(--mut);padding:6px 0}
.wide{grid-column:1/-1}
form.in{max-width:380px;margin:14vh auto;background:var(--panel);
border:1px solid var(--line);border-radius:12px;padding:30px}
form.in input{width:100%;padding:11px 13px;border:1px solid var(--line);
border-radius:8px;font-size:.95rem;margin:10px 0 14px}
form.in button{width:100%;padding:11px;border:0;border-radius:8px;
background:var(--acc);color:#fff;font-weight:600;font-size:.95rem;cursor:pointer}
.note{background:var(--accs);border-radius:8px;padding:12px 14px;
font-size:.88rem;color:var(--ink2);margin-top:14px}
@media(max-width:760px){.shell{flex-direction:column}
.side{width:auto;flex:none;flex-direction:row;overflow-x:auto;padding:10px}
.side .brand,.side .foot{display:none}.main{padding:18px}}
"""

_NAV = (("overview", "Overview", "◧"), ("results", "Results", "◈"),
        ("connections", "Connections", "⚯"), ("requests", "We need", "✎"))


def _page(title: str, body: str) -> str:
    return (f"<!doctype html><html><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{_e(title)}</title><style>{_CSS}</style></head>"
            f"<body>{body}</body></html>")


def render_signin(error: str = "", sent: bool = False) -> str:
    if sent:
        # Says what ACTUALLY happens. Nothing sends the link automatically, so
        # "check your email" would be a promise the system does not keep — the
        # client waits, nothing arrives, and the first thing they learn about
        # the portal is that it does not work. The same answer is given whether
        # or not the address is known, because a login form that confirms which
        # addresses have accounts is a customer list.
        inner = ("<h1>Request received</h1><p class='lab'>We have passed this "
                 "to your account manager, who will send you a sign-in link. "
                 "If you were expecting it sooner, reply to any email from us "
                 "and we will get it to you.</p>")
    else:
        inner = (
            "<h1>Sign in</h1>"
            "<p class='lab'>Ask for a link — there is no password to remember.</p>"
            + (f"<div class='note'>{_e(error)}</div>" if error else "")
            + "<form class='in' method='post' action='/portal/signin' "
              "style='margin:18px 0 0;padding:0;border:0'>"
              "<input name='email' type='email' placeholder='you@company.com' required>"
              "<button>Request a sign-in link</button></form>")
    return _page("Sign in", f"<form class='in' onsubmit='return false'>{inner}</form>")


def render(tenant: str, tab: str = "overview", days: int = 30,
           who: dict | None = None, notice: str = "") -> str:
    from . import client_report, metrics, tenants

    t = tenants.get(tenant)
    if not t:
        return _page("Not found", "<div class='main'><h1>No such account</h1></div>")
    rep = client_report.assemble(tenant, days)

    nav = "".join(
        f"<a class='{'on' if k == tab else ''}' href='/portal?tab={k}&days={days}'>"
        f"<span class='ico'>{i}</span>{_e(label)}</a>"
        for k, label, i in _NAV)
    side = (f"<div class='side'><div class='brand'>{_e(t.name)}</div>{nav}"
            f"<div class='foot'><a href='/portal/out'>Sign out</a></div></div>")

    if tab == "requests":
        body = _requests(tenant, rep, days, may_write=bool((who or {}).get("may_write")))
    else:
        body = {"overview": _overview, "results": _results,
                "connections": _connections}.get(tab, _overview)(tenant, rep, days)

    period = _e(f"{rep['period']['from']} to {rep['period']['to']}")
    banner = (f"<div class='ask'><h2>Not available on this account</h2>"
              f"<p>{_e(notice)}</p></div>") if notice else ""
    main = (f"<div class='main'>{banner}<div class='top'><h1>"
            f"{_e(dict((k, l) for k, l, _i in _NAV).get(tab, 'Overview'))}</h1>"
            f"<span class='since'>{period}</span></div>{body}</div>")
    return _page(f"{t.name} — {tab}", f"<div class='shell'>{side}{main}</div>")


def _stat(value, label: str, why: str = "") -> str:
    """One number. A missing one says why rather than showing a zero.

    Zero and unmeasured look identical on a dashboard and mean opposite things
    — the rule the reports already follow, carried onto the page a client sees.
    """
    if value in (None, "", {}, []):
        return (f"<div class='card'><div class='stat none'>Not measured yet</div>"
                f"<div class='lab'>{_e(label)}</div>"
                + (f"<div class='why'>{_e(why)}</div>" if why else "") + "</div>")
    return (f"<div class='card'><div class='stat'>{_e(str(value))}</div>"
            f"<div class='lab'>{_e(label)}</div>"
            + (f"<div class='why'>{_e(why)}</div>" if why else "") + "</div>")


def _overview(tenant: str, rep: dict, days: int) -> str:
    w, a = rep["work"], rep["assurance"]
    cards = [
        _stat(w["produced"], "Drafts prepared for you"),
        _stat(a["caught_total"], "Barred phrases stopped",
              "Wording your rules do not allow, caught before it went out"),
        _stat(w["self_corrected"] or None, "Rewritten automatically",
              "Caught, corrected and re-checked without anyone being asked"),
    ]
    asks = rep.get("awaiting_client") or []
    ask_card = ""
    if asks:
        items = "".join(f"<li><strong>{_e(x['label'])}</strong>"
                        + (f"<br><span class='why'>{_e(x['ask'])}</span>"
                           if x.get("ask") else "") + "</li>" for x in asks[:4])
        ask_card = (f"<div class='ask'><h2>We need {len(asks)} number(s) from you"
                    f"</h2><ul>{items}</ul></div>")
    return ask_card + f"<div class='grid'>{''.join(cards)}</div>"


def _results(tenant: str, rep: dict, days: int) -> str:
    figs = (rep.get("outcomes") or {}).get("figures") or []
    if not figs:
        return ("<div class='card'><div class='empty'>No headline numbers are "
                "set up for this account yet.</div></div>")
    cards = [_stat(f.get("value"), f["label"],
                   f.get("why", "") if f.get("value") is None else "")
             for f in figs]
    return f"<div class='grid'>{''.join(cards)}</div>"


def _connections(tenant: str, rep: dict, days: int) -> str:
    from . import credentials as cred
    rows = ""
    for r in cred.status(tenant):
        if r["kind"] == "oauth" and not r["self_serve"]:
            continue          # nothing the client can act on
        state = r["state"]
        pill = ("<span class='pill ok'>connected</span>" if state == "connected"
                else f"<span class='pill warn'>{_e(state)}</span>")
        rows += (f"<div class='row'><span>{_e(r['name'])}</span>"
                 f"<span class='n'>{pill}</span></div>")
    read = (rep.get("reach") or {}).get("platforms_read") or {}
    used = "".join(f"<div class='row'><span>{_e(k)}</span>"
                   f"<span class='n'>{v} times</span></div>" for k, v in read.items())
    return (f"<div class='grid'><div class='card wide'><h2>Your tools</h2>{rows}"
            f"</div><div class='card wide'><h2>What we read this period</h2>"
            + (used or "<div class='empty'>Nothing was read yet.</div>")
            + "<div class='why'>Connected means we can reach it. This is what "
              "we actually used.</div></div></div>")


def _requests(tenant: str, rep: dict, days: int, may_write: bool = False) -> str:
    asks = rep.get("awaiting_client") or []
    if not asks:
        return ("<div class='card'><div class='empty'>Nothing outstanding — "
                "we have everything we need for this period.</div></div>")

    def _box(a: dict) -> str:
        """The one place a client can change something, so the one place
        read-only has to be honoured. A read-only visitor sees the question and
        no field — a disabled input invites a support message about a broken
        form, where its absence with a line of explanation does not."""
        if not may_write:
            return ("<div class='why'>Your account is read-only, so send this "
                    "to us by reply and we will record it.</div>")
        return (f"<form method='post' action='/portal/figure' "
                f"style='display:flex;gap:8px;margin-top:12px'>"
                f"<input type='hidden' name='metric' value='{_e(a['metric'])}'>"
                f"<input name='value' placeholder='e.g. about 40' "
                f"style='flex:1;padding:9px 11px;border:1px solid var(--line);"
                f"border-radius:7px'>"
                f"<button style='padding:9px 16px;border:0;border-radius:7px;"
                f"background:var(--acc);color:#fff;font-weight:600;"
                f"cursor:pointer'>Send</button></form>")

    items = "".join(
        f"<div class='card wide'><h2>{_e(a['label'])}</h2>"
        + (f"<p>{_e(a['ask'])}</p>" if a.get("ask") else "")
        + (f"<div class='why'>{_e(a['why'])}</div>" if a.get("why") else "")
        + _box(a)
        + "</div>" for a in asks)
    return (f"<div class='grid'>{items}"
            "<div class='card wide'><div class='why'>Round numbers are fine. "
            "Your report shows where each figure came from, so an estimate is "
            "shown as an estimate.</div></div></div>")
