"""The front door: a public page that says what this is and where to sign in.

The root URL served FastAPI's bare 404 JSON until 2026-08-21 — the owner's
words: "our routes make no sense". This is the product's face while it lives
on the Render host and after it moves to its own subdomain: MarketingThatWorks
— AI Governance & Agent Management.

**Public-safe is the design constraint, not the copy's tone.** This page is on
the open internet: it names NO client, shows NO count, exposes NO route beyond
the two sign-in doors that already exist (the owner console and the client
portal, each with its own authentication). Everything it claims about the
product is something the codebase actually enforces — the same honesty rule as
every generator, applied to our own marketing.
"""
from __future__ import annotations

import html as _html

BRAND = "MarketingThatWorks"
PRODUCT = "AI Governance & Agent Management"

_CSS = """
:root{--bg:#0e1116;--panel:#161b23;--ink:#e8eaee;--mut:#98a1ad;--acc:#5b8def;
--rule:#232a35}
*{margin:0;padding:0;box-sizing:border-box}
body{font:16px/1.6 -apple-system,'Segoe UI',Helvetica,Arial,sans-serif;
background:var(--bg);color:var(--ink);min-height:100vh;display:flex;
flex-direction:column}
.wrap{max-width:860px;margin:0 auto;padding:0 24px;width:100%}
header{padding:26px 0}
.brand{font-weight:700;letter-spacing:.01em}
.brand span{color:var(--acc)}
main{flex:1;display:flex;align-items:center;padding:40px 0 60px}
h1{font:600 2.1rem/1.2 Georgia,'Times New Roman',serif;margin-bottom:14px}
.sub{color:var(--mut);max-width:560px;margin-bottom:30px}
.doors{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:52px}
a.btn{display:inline-block;padding:12px 22px;border-radius:8px;font-weight:600;
text-decoration:none;border:1px solid var(--acc)}
a.btn.pri{background:var(--acc);color:#0b0e13}
a.btn.sec{color:var(--acc)}
.tri{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));
gap:14px}
.tri div{background:var(--panel);border:1px solid var(--rule);
border-radius:10px;padding:18px}
.tri h2{font-size:.95rem;margin-bottom:8px}
.tri p{font-size:.88rem;color:var(--mut)}
footer{padding:22px 0;color:var(--mut);font-size:.82rem;
border-top:1px solid var(--rule)}
form.key{display:flex;flex-direction:column;gap:12px;max-width:380px}
form.key input{padding:11px 12px;border-radius:8px;border:1px solid var(--rule);
background:var(--panel);color:var(--ink);font-size:1rem}
form.key button{padding:11px;border-radius:8px;border:0;background:var(--acc);
color:#0b0e13;font-weight:700;cursor:pointer;font-size:1rem}
.err{color:#e07a6a;font-size:.9rem}
a.back{color:var(--mut);font-size:.85rem;text-decoration:none}
"""


def _page(title: str, body: str) -> str:
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{_html.escape(title)}</title><style>{_CSS}</style></head>"
            f"<body><header><div class='wrap'><div class='brand'>{BRAND}"
            f"<span> · {PRODUCT}</span></div></div></header>"
            f"<main><div class='wrap'>{body}</div></main>"
            f"<footer><div class='wrap'>© {BRAND} — {PRODUCT}. "
            f"Access is by invitation; each client sees only their own "
            f"workspace.</div></footer></body></html>")


def render() -> str:
    """The public landing page. Every claim on it is enforced by code."""
    return _page(f"{BRAND} — {PRODUCT}", f"""
<div>
  <h1>AI that runs your marketing<br>without running unsupervised.</h1>
  <p class="sub">A governed execution layer for marketing operations: agents
  that draft from your approved knowledge — never from thin air — behind
  compliance gates, human approval, and a complete audit trail.</p>
  <div class="doors">
    <a class="btn pri" href="/admin/signin">Console sign-in</a>
    <a class="btn sec" href="/portal">Client portal</a>
  </div>
  <div class="tri">
    <div><h2>Grounded, not generated-at-will</h2>
      <p>Every draft is written from an approved, per-account knowledge base,
      and a deterministic validator blocks the claims a brand must never
      make — before anything is staged anywhere.</p></div>
    <div><h2>Humans hold the launch key</h2>
      <p>Content is prepared send-ready and stops at an approval. Nothing is
      published, sent, or spent without a person's sign-off.</p></div>
    <div><h2>Audited end to end</h2>
      <p>Every run, validation, and platform call is recorded per account —
      so what the system did, refused, and why is always answerable.</p></div>
  </div>
</div>""")


def signin(err: str = "") -> str:
    """The console door. The key travels in a POST body — never in a URL,
    never into browser history; a valid one becomes the session cookie."""
    msg = f'<p class="err">{_html.escape(err)}</p>' if err else ""
    return _page(f"Console — {BRAND}", f"""
<div>
  <h1>Console sign-in</h1>
  <p class="sub">For the {BRAND} operations team. Clients sign in through the
  <a class="back" href="/portal">client portal</a> instead.</p>
  {msg}
  <form class="key" method="post" action="/admin/signin">
    <input type="password" name="key" placeholder="console key"
           autocomplete="current-password" autofocus required>
    <button>Sign in</button>
  </form>
  <p style="margin-top:18px"><a class="back" href="/">&larr; back</a></p>
</div>""")
