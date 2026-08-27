"""Who is asking, and which account they are allowed to see.

The console has had exactly two credentials: `APPROVAL_SECRET` (full write) and
`READ_KEY` (read-only, every account). Neither is scoped to a client. The
`tenant=` query parameter is a FILTER, not a permission — anyone holding either
key can change it and read every account's claims, connections, spend and email
subjects. `DEFECTS` has carried that as architecture debt since the credential
layer landed, and it stopped being theoretical the moment clients were going to
log in.

This adds a third principal that is bound to one account, and one rule that
makes every view safe without every view having to remember it:

    **A client's tenant comes from their session, never from the URL.**

`resolve_tenant` REFUSES a mismatched `tenant=` rather than quietly
substituting the right one. Silently correcting it would make an attempt to
read another client's data indistinguishable from a stale bookmark, and the
first is worth seeing.

Sign-in is a single-use link, the same shape as `ConnectLink` and `IntakeLink`
— this codebase already had two scoped expiring key-free links, and a third
mechanism for the same job is how they drift. No password is stored, because a
password store is a liability this does not need: the mailbox is already the
recovery channel for every such system, so it may as well be the credential.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import secrets

from . import config, db

PORTAL_COOKIE = "portal"
_SESSION_DAYS = 14
_LINK_MINUTES = 30


def _sig(body: str) -> str:
    return hmac.new((config.APPROVAL_SECRET or "").encode(), body.encode(),
                    hashlib.sha256).hexdigest()[:32]


def _sign(user_id: str, tenant: str, role: str) -> str:
    exp = int((db.utcnow() + dt.timedelta(days=_SESSION_DAYS)).timestamp())
    body = f"{user_id}|{tenant}|{role}|{exp}"
    return f"{body}.{_sig(body)}"


def read_session(raw: str) -> dict:
    """The principal a cookie carries, or {} — never raises on junk."""
    try:
        body, sig = (raw or "").rsplit(".", 1)
        user_id, tenant, role, exp = body.split("|")
    except ValueError:
        return {}
    if not hmac.compare_digest(sig, _sig(body)):
        return {}
    if int(exp) < int(db.utcnow().timestamp()):
        return {}
    return {"user_id": user_id, "tenant": tenant, "role": role}


# ---------------------------------------------------------------------------
# Sign-in
# ---------------------------------------------------------------------------

def issue_link(email: str, issued_by: str = "") -> dict:
    """Create a single-use sign-in link for a known user.

    Refuses an unknown or inactive address rather than creating an account.
    Self-registration on a portal that shows one client's commercial data is
    not a feature, and "we could not find that address" is the correct answer
    even though it is the less helpful one.
    """
    email = (email or "").strip().lower()
    if not email:
        return {"ok": False, "error": "an email address is required"}
    with db.SessionLocal() as s:
        # Matched case-insensitively in Python rather than with a SQL
        # `lower()`: the user table is small, and an address that differs only
        # in case is the commonest way a real sign-in silently fails.
        user = next((u for u in s.query(db.User)
                     .filter(db.User.status == "active").all()
                     if (u.email or "").strip().lower() == email), None)
        if not user:
            return {"ok": False,
                    "error": f"no active user with the address {email!r}. "
                             f"Add them on the Connections tab's People card first "
                             f"(it is the form that records an email; "
                             f"/admin/user_add takes only a chat id) — this does "
                             f"not create accounts."}
        if user.role != "owner" and not (user.tenant_key or "").strip():
            # An owner sees everything by design; a client with no account
            # attached would inherit that, which is the whole failure.
            return {"ok": False,
                    "error": f"{email} has no account attached, so there is "
                             f"nothing to scope their session to. Set "
                             f"tenant_key on the user first."}
        token = secrets.token_urlsafe(24)
        s.add(db.PortalLink(
            token=token, user_id=user.id,
            tenant=(user.tenant_key or ""),
            expires_at=db.utcnow() + dt.timedelta(minutes=_LINK_MINUTES),
            issued_by=issued_by))
        s.commit()
        name, role = user.name, user.role
    base = (config.PUBLIC_BASE_URL or "").rstrip("/")
    return {"ok": True, "url": f"{base}/portal/in/{token}", "for": name,
            "role": role, "expires_in_minutes": _LINK_MINUTES,
            "note": "single use, and it expires — send it, do not store it"}


def redeem(token: str) -> dict:
    """Spend a link and return the session value to set as a cookie."""
    with db.SessionLocal() as s:
        link = s.get(db.PortalLink, token or "")
        if not link:
            return {"ok": False, "error": "that sign-in link is not valid"}
        if link.used_at:
            # Named rather than merged with "expired". A used link means
            # somebody already signed in with it, which is worth knowing.
            return {"ok": False,
                    "error": "that link has already been used — ask for a new one"}
        if link.expires_at and db.as_utc(link.expires_at) < db.utcnow():
            return {"ok": False,
                    "error": "that link has expired — ask for a new one"}
        user = s.get(db.User, link.user_id)
        if not user or user.status != "active":
            return {"ok": False, "error": "that account is no longer active"}
        link.used_at = db.utcnow()
        s.commit()
        return {"ok": True, "cookie": _sign(user.id, link.tenant or "", user.role),
                "tenant": link.tenant or "", "role": user.role,
                "name": user.name}


# ---------------------------------------------------------------------------
# The rule
# ---------------------------------------------------------------------------

def principal(request) -> dict:
    """Who is asking: owner, client, or nobody.

    The admin credential still wins — an owner working in the console is not
    made to sign in twice — but it is reported as `owner` so a view can tell
    the difference rather than assuming.
    """
    from .web import admin_key
    if admin_key(request, request.query_params.get("key", "")):
        return {"role": "owner", "tenant": "", "user_id": ""}
    got = read_session(request.cookies.get(PORTAL_COOKIE, ""))
    if got:
        return got
    return {"role": "", "tenant": "", "user_id": ""}


def resolve_tenant(request, asked: str = "") -> tuple[str, str]:
    """(tenant, refusal). The one function every portal view must go through.

    An owner may ask for any account. A client gets their own, and asking for
    another is REFUSED rather than silently corrected — a substitution makes an
    attempt to read someone else's data look exactly like a stale bookmark, and
    only one of those is worth seeing.
    """
    who = principal(request)
    if who["role"] == "owner":
        return asked, ""
    if not who["role"]:
        return "", "sign in first"
    mine = who["tenant"]
    if asked and asked != mine:
        return "", (f"this account is scoped to {mine!r} and cannot read "
                    f"{asked!r}")
    return mine, ""


def can_write(request) -> bool:
    """May this principal change anything?

    An owner always may. A client may only when somebody granted `full` — the
    column defaults to `read_only`, so access is something added rather than
    something forgotten to remove.
    """
    who = principal(request)
    if who["role"] == "owner":
        return True
    if not who.get("user_id"):
        return False
    with db.SessionLocal() as s:
        u = s.get(db.User, who["user_id"])
        return bool(u and u.status == "active"
                    and (u.access or "read_only") == "full")


def access_of(user_id: str) -> str:
    with db.SessionLocal() as s:
        u = s.get(db.User, user_id)
        return (u.access or "read_only") if u else ""


def people(tenant: str = "") -> list[dict]:
    """Who can reach the portal, and with what. Never returns a credential."""
    with db.SessionLocal() as s:
        q = s.query(db.User)
        if tenant:
            q = q.filter(db.User.tenant_key == tenant)
        rows = q.order_by(db.User.name).all()
        out = []
        for u in rows:
            live = [l for l in s.query(db.PortalLink)
                    .filter(db.PortalLink.user_id == u.id,
                            db.PortalLink.used_at.is_(None)).all()
                    if not l.expires_at or db.as_utc(l.expires_at) > db.utcnow()]
            out.append({
                "id": u.id, "name": u.name or "(no name)",
                "email": u.email or "", "role": u.role or "client",
                "tenant": u.tenant_key or "", "status": u.status or "active",
                "access": (u.access or "read_only"),
                "can_sign_in": bool((u.email or "").strip()
                                    and u.status == "active"),
                "unused_links": len(live)})
        return out


def set_access(user_id: str, access: str) -> str:
    if access not in ("read_only", "full"):
        return "access must be read_only or full"
    with db.SessionLocal() as s:
        u = s.get(db.User, user_id)
        if not u:
            return "no such person"
        u.access = access
        s.commit()
        return f"{u.name or u.email} is now {access.replace('_', ' ')}."


def revoke(user_id: str) -> str:
    """Turn a person off, and kill any link they have not used yet.

    Both halves matter. Marking the user revoked stops future sign-ins;
    without expiring the outstanding links, one already sitting in a mailbox
    still works — which is precisely the window somebody would use.
    """
    with db.SessionLocal() as s:
        u = s.get(db.User, user_id)
        if not u:
            return "no such person"
        u.status = "revoked"
        killed = 0
        for l in s.query(db.PortalLink).filter(
                db.PortalLink.user_id == user_id,
                db.PortalLink.used_at.is_(None)).all():
            l.expires_at = db.utcnow()
            killed += 1
        s.commit()
        return (f"{u.name or u.email} revoked"
                + (f", and {killed} unused sign-in link(s) killed." if killed
                   else ". No unused links were outstanding."))


def save_person(*, email: str, name: str, tenant: str, access: str = "read_only",
                role: str = "client") -> dict:
    """Add or update somebody who signs in with an email address.

    Separate from `/admin/user_add`, which is the Telegram path and requires a
    chat_id. A portal user has an email and may have no chat at all; forcing
    one identifier to stand for both is how a client ends up unable to sign in
    because they never messaged a bot.
    """
    email = (email or "").strip().lower()
    if not email:
        return {"ok": False, "error": "an email address is required"}
    if role != "owner" and not tenant:
        return {"ok": False, "error": "a client must be pinned to one account"}
    if access not in ("read_only", "full"):
        return {"ok": False, "error": "access must be read_only or full"}
    with db.SessionLocal() as s:
        if tenant and not s.get(db.Tenant, tenant):
            return {"ok": False, "error": f"unknown account {tenant!r}"}
        u = next((x for x in s.query(db.User).all()
                  if (x.email or "").strip().lower() == email), None)
        if u:
            u.name = name or u.name
            u.role, u.tenant_key, u.access = role, (tenant or None), access
            u.status = "active"
        else:
            u = db.User(name=name or email.split("@")[0], email=email,
                        role=role, tenant_key=tenant or None,
                        active_tenant=tenant or "agency", access=access)
            s.add(u)
        s.commit()
        return {"ok": True, "id": u.id, "email": email, "access": access,
                "tenant": tenant}
