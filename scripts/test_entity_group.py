"""Grouping is a decision somebody can actually make, from the console.

`kb.assign_to_group` has existed since the scope work with NO CALLER. The only
manual path was one `/admin/entity_group?...` GET per entity — for a forty-item
range, forty URLs pasted by hand — so the path the collection import
deliberately leaves to a person was one nobody could realistically walk. The
import is opt-in precisely because a group claim is asserted about every member
and inherited silently; leaving the manual half unusable meant the safe default
had no safe alternative.

    python3 scripts/test_entity_group.py
"""
import os
import sys
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'eg.db')}"
os.environ["APPROVAL_SECRET"] = "s3cret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import db, kb, tenants, web  # noqa: E402

_fail: list[str] = []


def ck(label, cond, detail=""):
    print(f"[{'  ok  ' if cond else ' FAIL '}] {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)


def main() -> int:
    db.init_db()
    tenants.seed()
    kb.ensure_brand("baci", "Baci")
    kb.add_entity("baci", "collection", "aqua", "Aqua", origin="human")
    kb.add_entity("baci", "collection", "acrylic", "Acrylic", origin="human")
    kb.add_entity("baci", "product", "aqua-jug", "Aqua Jug", origin="human")
    kb.add_entity("baci", "product", "aqua-plate", "Aqua Plate", origin="human")

    c = TestClient(web.app)
    c.get("/admin/ui?key=s3cret&tab=kb&tenant=baci")   # sets the session cookie

    print("— the form is on the page, not in a runbook —")
    page = c.get("/admin/ui?key=s3cret&tab=kb&tenant=baci").text
    ck("the grouping form renders", 'action="/admin/entity_group"' in page)
    ck("  collections are offered as groups", ">Aqua<" in page)
    ck("  and non-collections as members", 'value="aqua-jug"' in page)
    ck("  it says a group claim is inherited by every member",
       "true of every member" in page,
       "the whole reason collection import is opt-in")

    def post(**data):
        return c.post("/admin/entity_group?key=s3cret", data=data,
                      follow_redirects=False)

    print("\n— many at once, which is the point —")
    r = post(tenant="baci", group="aqua", entity_keys=["aqua-jug", "aqua-plate"])
    ck("two are added in one request", r.status_code == 303
       and "2%20of%202" in r.headers.get("location", ""),
       r.headers.get("location", "")[:70])
    ck("  and both are really members",
       sorted(e.key for e in kb.group_members("baci", "aqua"))
       == ["aqua-jug", "aqua-plate"])

    print("\n— membership is additive —")
    post(tenant="baci", group="acrylic", entity_keys=["aqua-jug"])
    ck("joining a second group does not evict the first",
       sorted(kb.ancestors("baci", "aqua-jug")) == ["acrylic", "aqua"],
       "a white Aqua pitcher is in its range AND its material; forcing a "
       "choice would decide which kind of fact can be said once")

    print("\n— refusals reach the operator —")
    r = post(tenant="baci", group="aqua")
    ck("nothing selected is said plainly, not silently ignored",
       "Nothing%20was%20selected" in r.headers.get("location", ""))
    r = post(tenant="baci", group="nope", entity_keys=["aqua-jug"])
    ck("an unknown group is refused by name",
       "err=" in r.headers.get("location", "")
       and "nope" in r.headers.get("location", ""))
    r = post(tenant="baci", group="aqua", entity_keys=["ghost"])
    ck("a partial failure is NOT reported as success",
       "err=" in r.headers.get("location", ""),
       "dropping the refusals would report 0-of-1 as done")

    print("\n— it mutates, so it is a POST —")
    ck("the write path is POST",
       any(r.path == "/admin/entity_group" and "POST" in r.methods
           for r in web.app.routes if hasattr(r, "methods")),
       "a console write on a GET can be fired by a browser prefetch, and this "
       "one rewrites what claims apply to what")

    print()
    if _fail:
        print(f"{len(_fail)} FAILED:")
        for f in _fail:
            print(f"  - {f}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
