"""HTML email formatting — every agent->Gomeh email should read and look
like a competent human assistant wrote it in Gmail."""
import html as _html

FONT = "font-family:Arial,Helvetica,sans-serif;"
MUTED = "color:#5f6368;font-size:13px;"
BTN_OK = ("display:inline-block;padding:9px 22px;background:#1a73e8;color:#ffffff;"
          "text-decoration:none;border-radius:4px;font-size:14px;" + FONT)
BTN_NO = ("display:inline-block;padding:9px 22px;background:#ffffff;color:#5f6368;"
          "text-decoration:none;border:1px solid #dadce0;border-radius:4px;"
          "font-size:14px;margin-left:8px;" + FONT)


def esc(s: str) -> str:
    return _html.escape(s or "")


def nl2br(s: str) -> str:
    return esc(s).replace("\n", "<br>")


def wrap(body_html: str) -> str:
    return (
        f'<div style="{FONT}color:#202124;font-size:14px;line-height:1.55;'
        f'max-width:640px;">{body_html}'
        f'<p style="{MUTED}margin-top:28px;">— Your assistant</p></div>'
    )


def heading(text: str) -> str:
    return (f'<p style="font-size:15px;font-weight:bold;margin:22px 0 8px;">'
            f'{esc(text)}</p>')


def bullets(items: list[str]) -> str:
    lis = "".join(f'<li style="margin:3px 0;">{esc(i)}</li>' for i in items)
    return f'<ul style="margin:4px 0 12px;padding-left:22px;">{lis}</ul>'


def text_to_html(text: str) -> str:
    """Convert the agent's plain-text reports (•-bullets, UPPERCASE headers)
    into clean HTML paragraphs and lists."""
    out, buf = [], []

    def flush() -> None:
        if buf:
            out.append(bullets(buf))
            buf.clear()

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("•", "-", "*")):
            buf.append(stripped.lstrip("•-* ").strip())
            continue
        flush()
        if not stripped:
            continue
        if (stripped.rstrip(":").isupper() and len(stripped) > 3) or stripped.endswith(":"):
            out.append(heading(stripped.rstrip(":").title()))
        else:
            out.append(f'<p style="margin:8px 0;">{esc(stripped)}</p>')
    flush()
    return wrap("".join(out))


def approval_email(items: list[dict], intro: str | None = None) -> str:
    """items: {summary, account, inbound_from, subject, inbound_snippet,
    reason, body, approve_url, deny_url}"""
    blocks = []
    for i, p in enumerate(items, 1):
        needs_facts = "NEEDS-FACTS" in (p.get("reason") or "")
        flag = ('<span style="color:#d93025;font-weight:bold;"> — needs facts '
                'from you before sending</span>' if needs_facts else "")
        blocks.append(f"""
<div style="border:1px solid #dadce0;border-radius:8px;padding:18px 20px;margin:18px 0;">
  <p style="margin:0 0 2px;font-weight:bold;">{i}. {esc(p.get('subject', ''))}{flag}</p>
  <p style="margin:0 0 12px;{MUTED}">{esc(p.get('inbound_from', ''))} &middot; {esc(p.get('account', ''))} inbox</p>
  <blockquote style="margin:0 0 12px;padding:8px 14px;border-left:3px solid #dadce0;{MUTED}">
    {nl2br(p.get('inbound_snippet', '')[:400])}</blockquote>
  <p style="margin:0 0 6px;{MUTED}">My read: {esc(p.get('reason', ''))}</p>
  {f'<p style="margin:0 0 6px;color:#1a73e8;">💡 {esc(p.get("suggestion"))}</p>' if p.get('suggestion') else ''}
  <p style="margin:14px 0 6px;font-weight:bold;">Proposed reply:</p>
  <div style="background:#f8f9fa;border-radius:6px;padding:12px 16px;margin-bottom:14px;">
    {nl2br(p.get('body', '')[:2500])}</div>
  <a href="{p['approve_url']}" style="{BTN_OK}">Approve &amp; send</a>
  <a href="{p['deny_url']}" style="{BTN_NO}">Deny</a>
</div>""")
    intro_html = (f'<p style="margin:0 0 4px;">{esc(intro)}</p>' if intro else
                  f'<p style="margin:0 0 4px;">Hi Gomeh — {len(items)} '
                  f'repl{"y is" if len(items) == 1 else "ies are"} ready for '
                  f'your review. Each one shows the incoming message, my read '
                  f'on it, and the reply I propose to send.</p>')
    tip = (f'<p style="{MUTED}">Want to edit one first? The same draft is in '
           f"that inbox's Drafts folder — edit and send it there, then hit "
           f'Deny here so I don\'t double-send.</p>')
    return wrap(intro_html + tip + "".join(blocks))


def digest_email(deadlines: list, pending: list, sections: dict,
                 when: str) -> str:
    parts = [f'<p style="margin:0 0 16px;">Good {"morning" if "AM" in when else "evening"} '
             f'Gomeh — here\'s where things stand.</p>']
    if deadlines:
        parts.append(heading("Money deadlines, next 7 days"))
        parts.append(bullets([f"{d.due_date} — {d.description} ({d.amount}), "
                              f"{d.account} inbox" for d in deadlines]))
    if pending:
        parts.append(heading(f"Waiting on you ({len(pending)})"))
        parts.append(bullets([ap.summary for ap in pending]))
    titles = {"auto_replied": "Handled automatically",
              "drafted": "Drafted for your review",
              "escalated": "Escalated to you",
              "ignored": "Filtered out (no action needed)"}
    for key, title in titles.items():
        items = sections.get(key, [])
        if not items:
            continue
        parts.append(heading(f"{title} ({len(items)})"))
        parts.append(bullets([f"{e.sender} — {e.subject} ({e.account})"
                              for e in items[:15]]))
    if len(parts) == 1:
        parts.append('<p>Quiet stretch — nothing needs your attention right now.</p>')
    return wrap("".join(parts))
