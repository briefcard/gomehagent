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
    replies = 0
    for i, p in enumerate(items, 1):
        kind = p.get("_kind", "")
        if kind and kind != "send_email":
            # A NON-REPLY approval rendered on the reply template promised
            # "Approve & send" over an article publish, a file refile, or the
            # nightly sweep — and its empty inbound_from/snippet fields drew a
            # card describing an email that never existed. Its own card says
            # what approving actually does.
            body = (p.get("body") or p.get("content")
                    or (p.get("fields") or {}).get("body_html", ""))
            act = {"seo_new_article": "publishes the article",
                   "seo_article_revision": "applies the revision",
                   "seo_update": "updates the live page",
                   "seo_new_page": "creates the page",
                   "seo_new_collection": "creates the collection",
                   "refile_moves": "moves the files",
                   "systems_update": "adopts the map",
                   "sweep": "records the decision — nothing executes",
                   }.get(kind, "records the decision")
            blocks.append(f"""
<div style="border:1px solid #dadce0;border-radius:8px;padding:18px 20px;margin:18px 0;">
  <p style="margin:0 0 6px;font-weight:bold;">{i}. {esc(p.get('summary', kind))}</p>
  <p style="margin:0 0 10px;{MUTED}">{esc(kind)} &middot; approving {esc(act)}</p>
  {f'<div style="background:#f8f9fa;border-radius:6px;padding:12px 16px;margin-bottom:14px;">{nl2br(esc(body)[:2500])}</div>' if body else ''}
  <a href="{p['approve_url']}" style="{BTN_OK}">Approve</a>
  <a href="{p['deny_url']}" style="{BTN_NO}">Deny</a>
</div>""")
            continue
        replies += 1
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
    n_other = len(items) - replies
    if intro:
        intro_html = f'<p style="margin:0 0 4px;">{esc(intro)}</p>'
    elif replies and not n_other:
        intro_html = (f'<p style="margin:0 0 4px;">Hi Gomeh — {len(items)} '
                      f'repl{"y is" if len(items) == 1 else "ies are"} ready '
                      f'for your review. Each one shows the incoming message, '
                      f'my read on it, and the reply I propose to send.</p>')
    else:
        # The old intro described every card as a reply; a mixed digest
        # opened by promising incoming messages that half the cards never
        # had.
        intro_html = (f'<p style="margin:0 0 4px;">Hi Gomeh — {len(items)} '
                      f'approval{"" if len(items) == 1 else "s"} waiting'
                      + (f' ({replies} repl'
                         f'{"y" if replies == 1 else "ies"}, {n_other} other)'
                         if replies else "") + '. Each card says what '
                      'approving it does.</p>')
    # The Drafts-folder edit tip is TRUE only of mail — on an article card it
    # directed the owner to a Gmail draft that does not exist.
    tip = ((f'<p style="{MUTED}">Want to edit a reply first? The same draft '
            f"is in that inbox's Drafts folder — edit and send it there, "
            f'then hit Deny here so I don\'t double-send.</p>')
           if replies else "")
    return wrap(intro_html + tip + "".join(blocks))


def _ack_row(item: dict, links: dict, with_client: bool = False) -> str:
    """One briefing line, with the three ways to close it.

    The controls are ON the line (design rule 1: act where you report). The
    owner reads this on a phone with no session, so a briefing that says
    "clear it in the console" is a briefing that never gets cleared — which
    is the state this replaced.
    """
    verbs = " &middot; ".join(
        f'<a href="{esc(links[v])}" style="color:#5b6470;text-decoration:'
        f'underline;">{label}</a>'
        for v, label in (("handled", "handled"), ("irrelevant", "irrelevant"),
                         ("updated", "updated")))
    # The tail sections span every account, so they name theirs. The client
    # blocks do not — the heading above them already said it, and repeating
    # it on every line is the same fact twice (design rule 8).
    who = (f'<span style="{MUTED}">[{esc(item.get("tenant") or "—")}] </span>'
           if with_client else "")
    return (f'<li style="margin:6px 0;">{who}{esc(item["title"])}'
            f'<span style="{MUTED}"> &mdash; {esc(item["detail"])}</span>'
            f'<br><span style="{MUTED}font-size:12px;">{verbs}</span></li>')


def _ack_list(items: list, linker, total: int = 0,
              with_client: bool = False) -> str:
    lis = "".join(_ack_row(i, linker(i), with_client) for i in items)
    more = ""
    if total and total > len(items):
        more = (f'<li style="{MUTED}margin:6px 0;">&hellip; and '
                f'{total - len(items)} more</li>')
    return f'<ul style="margin:4px 0 12px;padding-left:22px;">{lis}{more}</ul>'


def digest_email(brief: dict, when: str, linker) -> str:
    """The briefing: each client first, worst thing first, then the tail.

    Takes the same structure the plain-text version renders, so the two can
    never say different things — they did before, because each pulled its own
    rows in its own order.
    """
    parts = [f'<p style="margin:0 0 16px;">Good '
             f'{"morning" if "AM" in when else "evening"} Gomeh &mdash; '
             f'here\'s where things stand, worst first.</p>']
    for c in brief.get("clients", []):
        parts.append(heading(f"{c['name']} ({c['total']})"))
        parts.append(_ack_list(c["items"], linker, c["total"]))
    for key, title in (("upcoming", "Upcoming"),
                       ("stale", "Still open, older than a week"),
                       ("housekeeping",
                        "Housekeeping \u2014 done automatically, no action")):
        rows = brief.get(key) or []
        if not rows:
            continue
        parts.append(heading(f"{title} ({brief.get(key + '_total', len(rows))})"))
        parts.append(_ack_list(rows, linker, brief.get(key + "_total", 0),
                               with_client=True))
    if brief.get("cleared"):
        parts.append(f'<p style="{MUTED}margin-top:18px;font-size:12px;">'
                     f'{brief["cleared"]} item(s) you already cleared are not '
                     f'shown. They come back only if they change.</p>')
    if len(parts) == 1:
        parts.append('<p>Quiet stretch &mdash; nothing needs your attention '
                     'right now.</p>')
    return wrap("".join(parts))
