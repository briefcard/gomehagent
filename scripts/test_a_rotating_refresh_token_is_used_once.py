"""A rotating refresh token is spent once, its rotation is kept, and every call
shares the access token it bought.

Owner, 2026-09-07, minutes after reconnecting Canva: *"Sign-in was rejected:
Refresh token used twice. All access tokens granted from this flow are now
revoked."* — the second lineage in a day, and the first ("Token lineage has
been revoked") died the same way.

WHAT WAS TRUE. Canva's refresh tokens are single-use: every refresh returns a
NEW refresh token and spends the old one. `oauth.access_token` hands the new
one back — its own comment says dropping it "would mean the connection works
once and then dies, which looks exactly like a revocation and would be
debugged as one" — and no caller kept it. `canva._token` minted a fresh access
token from the STORED refresh token on EVERY call and discarded the rotation,
so one "edit in Canva" (upload, poll, design, folder: four calls) spent the
same token twice by its second call and took the lineage with it. Constant
Contact mints the same way. Google survived only because its tokens do not
rotate — which is why this was never seen before Canva.

The rules, each with its guard: a refresh's rotation is STORED before the
access token it bought is used; an access token is REUSED for its lifetime
(one refresh per lifetime, not per call); two callers arriving together
refresh ONCE; a row that is revoked or failed serves no cached token, so
Disconnect still takes effect; and every provider mints through the one door.

Run: python3 scripts/test_a_rotating_refresh_token_is_used_once.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import time

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'rot.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import canva, constant_contact, credentials as cred, db, oauth, tenants  # noqa: E402

_fail: list[str] = []


def ck(label: str, cond, detail: str = "") -> None:
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


class RotatingEndpoint:
    """Canva's token endpoint, as it behaves: a refresh token works ONCE and
    returns its successor; a second use revokes the whole lineage."""

    def __init__(self, first: str = "r0", slow: float = 0.0):
        self.valid = {first}
        self.prefix = first.rstrip("0123456789") or "r"
        self.n = 0
        self.refreshes: list[str] = []
        self.slow = slow
        self.lock = threading.Lock()

    def __call__(self, provider: str, refresh: str) -> dict:
        with self.lock:
            self.refreshes.append(refresh)
            if refresh not in self.valid:
                self.valid.clear()
                return {"ok": False, "error": ("Sign-in was rejected: Refresh token "
                                               "used twice. All access tokens granted "
                                               "from this flow are now revoked.")}
            self.valid.discard(refresh)
            self.n += 1
            new = f"{self.prefix}{self.n}"
            self.valid.add(new)
        if self.slow:
            time.sleep(self.slow)
        return {"ok": True, "token": f"a{self.n}", "new_refresh": new,
                "expires_in": 14400}


def _seed(tenant: str, provider: str, secret: str, by: str = "client") -> None:
    with db.SessionLocal() as s:
        s.add(db.Credential(tenant=tenant, provider=provider, kind="oauth",
                            secret=cred._encrypt(secret), meta={},
                            status="active", granted_by=by))
        s.commit()


def _row(tenant: str, provider: str):
    with db.SessionLocal() as s:
        r = (s.query(db.Credential).filter(db.Credential.tenant == tenant,
                                           db.Credential.provider == provider).first())
        s.expunge_all()
        return r


def main() -> int:
    db.init_db()
    tenants.seed()
    _seed("baci", "canva", "r0")
    endpoint = RotatingEndpoint("r0")
    oauth.access_token = endpoint

    print("— ONE EDIT IS SEVERAL CALLS, AND THE TOKEN IS SPENT ONCE —")
    first, why1 = canva._token("baci")
    second, why2 = canva._token("baci")
    third, why3 = canva._token("baci")
    ck("three calls in a row all get a token — the second does not kill the lineage",
       first == "a1" and second == "a1" and third == "a1" and not (why1 or why2 or why3),
       f"{first!r} {second!r} {third!r} — {why2[:90]!r}")
    ck("  because the refresh token was spent ONCE for three calls",
       endpoint.refreshes == ["r0"], str(endpoint.refreshes))
    row = _row("baci", "canva")
    ck("  and its rotation was STORED before the access token was used",
       row is not None and cred._decrypt(row.secret) == "r1"
       and row.status == "active" and not (row.last_error or ""),
       f"secret={cred._decrypt(row.secret) if row else None!r} status={getattr(row, 'status', None)}")
    ck("  the access token is cached on the row, with its expiry — never in a process",
       bool((row.meta or {}).get("access_token")) and int((row.meta or {}).get("access_expires_at") or 0) > 0
       and (row.meta or {}).get("access_token") != "a1",
       "a cache in memory would be lost on the next worker and refreshed there with a spent token")

    print("\n— THE LIFETIME ENDS: ONE more refresh, with the token that was kept —")
    real_now = cred._now
    cred._now = lambda: real_now() + 5 * 3600
    later, why4 = canva._token("baci")
    ck("after the lifetime a new access token is minted from the ROTATED token",
       later == "a2" and not why4 and endpoint.refreshes == ["r0", "r1"],
       f"{later!r} {why4[:80]!r} {endpoint.refreshes}")
    ck("  and the newest rotation is stored again",
       cred._decrypt(_row("baci", "canva").secret) == "r2")
    cred._now = real_now

    print("\n— TWO CALLERS AT ONCE REFRESH ONCE —")
    _seed("eien", "canva", "e0")
    slow = RotatingEndpoint("e0", slow=0.15)
    oauth.access_token = slow
    got: list = []

    def _go():
        got.append(canva._token("eien"))

    ts = [threading.Thread(target=_go) for _ in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    ck("four simultaneous callers all get the same token and the endpoint saw ONE refresh",
       len(got) == 4 and all(g[0] == "a1" and not g[1] for g in got)
       and slow.refreshes == ["e0"], f"{[g[0] or g[1][:40] for g in got]} {slow.refreshes}")

    print("\n— DISCONNECT STILL TAKES EFFECT —")
    oauth.access_token = endpoint
    with db.SessionLocal() as s:
        r = (s.query(db.Credential).filter(db.Credential.tenant == "baci",
                                           db.Credential.provider == "canva").first())
        r.status = "revoked"
        s.commit()
    tok, why = canva._token("baci")
    ck("a revoked row serves NO cached access token",
       tok == "" and "Accounts tab" in why, f"{tok!r} {why[:80]!r}")

    print("\n— EVERY PROVIDER MINTS THROUGH THE ONE DOOR —")
    _seed("eien", "constant_contact", "c0")
    cc = RotatingEndpoint("c0")
    oauth.access_token = cc
    t1, w1 = constant_contact._token("eien")
    t2, w2 = constant_contact._token("eien")
    ck("Constant Contact, which also rotates, spends its token once for two calls",
       t1 == "a1" and t2 == "a1" and not (w1 or w2) and cc.refreshes == ["c0"]
       and cred._decrypt(_row("eien", "constant_contact").secret) == "c1",
       f"{t1!r} {t2!r} {w2[:60]!r} {cc.refreshes}")

    print()
    if _fail:
        print(f"{len(_fail)} FAILED:\n  " + "\n  ".join(_fail))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
