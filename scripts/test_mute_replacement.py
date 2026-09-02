"""Muting says what took the keyword's place — or that nothing can.

Owner, 2026-09-02: *"In the Board — I want updates for muting some keywords to
be pulled and replaced by high opportunity keywords that aren't already on the
board but grow from those clusters."*

Muting already removed the keyword and let the next candidate slide up. What it
never did was SAY so, and the thing that slid up was whatever ranked next
anywhere in the map rather than anything to do with the cluster you were
pruning.

REPORTED, NOT PROMISED. The obvious build picks "the best candidate in that
cluster" and announces it — and is wrong whenever the board was not full,
whenever the cluster is exhausted, and whenever the keyword that actually
surfaced came from elsewhere because the muted one was not in the last slot.
This reads the board on both sides of the change and names what genuinely
appeared, which is the only version that cannot mislead somebody looking at
the board while they read it.

A mute that surfaced NOTHING is a real answer, not a silence: the cluster has
no more candidates, which is a harvest gap.

Run: python3 scripts/test_mute_replacement.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'mr.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from urllib.parse import unquote_plus  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app import db, keywords, tenants, web  # noqa: E402

KEY = "s3cret"
_fail = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}"
          + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def _kw(phrase, cluster, priority):
    keywords.upsert("baci", phrase, cluster_key=cluster, status="candidate",
                    priority=priority, role="support")


def _mute(phrase):
    r = TestClient(web.app).get(
        f"/admin/keyword_priority?key={KEY}&tenant=baci"
        f"&phrase={phrase.replace(' ', '%20')}&mode=muted&ui=1",
        follow_redirects=False)
    return unquote_plus(r.headers.get("location", ""))


def main() -> int:
    db.init_db()
    tenants.seed()

    print("— the board and the mute route read ONE list —")
    for i in range(14):
        _kw(f"kw {i:02d}", "big", 100 - i)
    board = [r["phrase"] for r in keywords.board("baci")["writing_next"]]
    ck("what the board offers and what `next_to_write` says agree",
       board == keywords.next_to_write("baci"),
       "two copies of 'what is on the board' disagree the first time either "
       "is touched, and this is the list decisions are read off")

    print()
    print("— muting names what came up from the same cluster —")
    top = keywords.next_to_write("baci")
    ck("the board is full, so muting frees a slot",
       len(top) == 12, f"{len(top)} offered")
    said = _mute(top[0])
    ck("the message says it was muted", "muted" in said, said[-90:])
    ck("  and names what took its place",
       "Taking its place from the same cluster" in said, said[-120:])
    ck("  which is a keyword that was NOT on the board before",
       any(p in said for p in ("kw 12", "kw 13")),
       f"{said[-70:]} — the next by priority, from the cluster being pruned")

    print()
    print("— a cluster with nothing left says THAT, and it is not silence —")
    # HIGH ENOUGH TO BE OFFERED. At priority 50 it sat below the cut, so
    # muting it freed no slot and the assertion below was about a keyword
    # the board was never showing.
    _kw("lonely one", "small", 999)
    before = keywords.next_to_write("baci")
    ck("the lonely keyword is on the board",
       "lonely one" in before, str(before[-3:]))
    said2 = _mute("lonely one")
    # THE HONEST BRANCH, and the one the first version of this test expected
    # wrongly. The 'small' cluster has nothing else, so the freed slot filled
    # from the BIG cluster — and the message says "from elsewhere in the map"
    # rather than crediting the cluster being pruned. That refusal to
    # mis-credit is the whole point of computing the delta instead of picking
    # a replacement and announcing it.
    ck("it does not credit the pruned cluster",
       "from the same cluster" not in said2, said2[-120:])
    ck("  it says the slot filled from elsewhere",
       "from elsewhere in the map" in said2, said2[-110:])

    print()
    print("— and with no slot to fill, it says the cluster is exhausted —")
    # A SEPARATE ACCOUNT with a board too small to be full, so muting frees a
    # slot that nothing can fill and the third branch is reachable at all.
    keywords.upsert("wm", "only one", cluster_key="tiny", status="candidate",
                    priority=90, role="support")
    r = TestClient(web.app).get(
        f"/admin/keyword_priority?key={KEY}&tenant=wm&phrase=only%20one"
        f"&mode=muted&ui=1", follow_redirects=False)
    said3 = unquote_plus(r.headers.get("location", ""))
    ck("it names the cluster that has nothing ready",
       "Nothing else in 'tiny' is ready to write" in said3, said3[-130:])
    ck("  and calls it a harvest gap, not a failure",
       "needs more keywords" in said3,
       "a cluster with one keyword is a map that was never finished for that "
       "topic")

    print()
    print("— a slot filled from elsewhere is not claimed as the cluster's —")
    # Mute the LAST offered keyword of the big cluster while a higher-priority
    # candidate exists in another cluster: the slot fills, but not from here.
    _kw("outsider", "other", 999)
    before3 = keywords.next_to_write("baci")
    ck("the outsider already leads, so it is not the replacement",
       before3[0] == "outsider", str(before3[:2]))
    eff = keywords.mute_effect("baci", "kw 05",
                               before3)  # not yet muted: nothing changed
    ck("with no change, nothing is reported as surfaced",
       eff["surfaced"] == [],
       "a message that names a replacement when the board did not move is "
       "the version that cannot be checked against the page")

    print()
    print("— and what the cluster still holds is counted —")
    held = keywords.mute_effect("baci", "kw 01",
                               keywords.next_to_write("baci"))["still_held"]
    ck("keywords below the cut are named as still there",
       len(held) >= 1,
       f"{len(held)} below the cut — 'nothing surfaced' and 'nothing exists' "
       f"are different, and only one of them is a harvest gap")

    print()
    print("PASS" if not _fail else f"FAILED: {len(_fail)}")
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
