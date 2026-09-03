"""Client intake: a scoped link that lets a client fill their own KB.

Guards worth keeping: the page must never leak the admin key or another
account, a client-submitted claim must not become selectable without review,
and a misrouted answer must never become a banned phrase (fail-closed in the
wrong direction is still wrong).

    python3 scripts/test_intake.py
"""
import os,sys,tempfile
os.environ["DATABASE_URL"]=f"sqlite:///{os.path.join(tempfile.mkdtemp(),'i.db')}"
os.environ["APPROVAL_SECRET"]="s3cret"; os.environ["PUBLIC_BASE_URL"]="https://x.test"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fastapi.testclient import TestClient
from app import db,kb,kb_seed,systems,tenants
from app.web import app
fails=[]
def ck(l,c,d=""):
    print(f"[{'  ok  ' if c else ' FAIL '}] {l}"+(f"  — {d}" if d else ""));  fails.append(l) if not c else None
with TestClient(app) as cl:
    tenants.seed(); kb.seed_agency(); systems.seed_from_tenants()
    kb_seed.seed_coverings()

    r=cl.get("/admin/intake_new",params={"key":"s3cret","tenant":"coverings","label":"Ellis"})
    url=r.json()["url"]; tok=url.rsplit("/",1)[1]
    ck("a scoped link is minted", r.status_code==200 and tok, url[:46]+"…")

    p=cl.get(f"/intake/{tok}")
    ck("client sees one question, no schema, no key",
       p.status_code==200 and "Coverings Etc" in p.text and "s3cret" not in p.text)
    ck("and it says which system is waiting on it", "Needed by" in p.text,
       [l for l in p.text.split("\n") if "Needed by" in l][:1])

    p2=cl.get(f"/intake/{tok}",params={"answer":"direct, technical, unfussy"})
    ck("an answer lands in the KB",
       (kb.brand("coverings").voice or {}).get("tone")==["direct","technical","unfussy"])

    # drive by whatever the intake actually asks next, not a guessed order
    ANS={"banned_claims":"cheapest; guaranteed lead time",
         "objection":"We only sell trade | Correct — we route you to a dealer.",
         "entity":"product | bio-glass-emerald | Bio-Glass Emerald Forest | POA | recycled glass slab",
         "audience":"gc | General contractor | schedule slips;wrong dims | submittal;lead time",
         "next_steps":"a sample to the studio",
         "claim":"We are the best supplier in Florida | everyone says so | trade_specification"}
    seen=set()
    while True:
        st=kb.next_step("coverings")
        if not st or st["id"] in seen or st["id"] not in ANS: break
        seen.add(st["id"])
        cl.get(f"/intake/{tok}",params={"answer":ANS[st["id"]]})
    ck("a misrouted pipe answer never becomes a banned phrase",
       not any("|" in p for p in kb.banned_claims("coverings")), str(kb.banned_claims("coverings")))
    # The loop above routes every answer to its OWN step, so a pipe never
    # reaches banned_claims and the check above cannot fail — it passed with
    # the refusal deleted. This sends the misrouted answer on purpose.
    before=list(kb.banned_claims("coverings"))
    said=kb.apply_answer("coverings","banned_claims","cheap | fast | guaranteed")
    ck("  and one sent to the wrong step is refused, not filed",
       kb.banned_claims("coverings")==before and "|" not in " ".join(kb.banned_claims("coverings")),
       f"{said[:80]!r}; banned now {kb.banned_claims('coverings')}")
    # A client's answer counts as answered — the intake must not re-ask it —
    # while staying unusable until someone approves it. Two different questions
    # of the same row, which is why gaps() and objections() disagree here.
    ck("progress advances through the gaps",
       len(kb.objections("coverings", include_proposed=True))==1)
    ck("but a client's objection is not usable until approved",
       len(kb.objections("coverings"))==0
       and kb.completeness("coverings")["awaiting_review"]["objections"]==1)
    before=len(kb.claims("coverings"))
    ck("a CLIENT claim is not selectable until reviewed",
       len(kb.claims("coverings"))==before and len(kb.pending_claims("coverings"))==1)
    pend=kb.pending_claims("coverings")[0]
    ck("and it is attributed to who sent it", "Ellis" in (pend.source or ""), pend.source)
    cl.get("/admin/claim_review",params={"key":"s3cret","claim_id":pend.id,"approve":"no"})
    ck("rejecting keeps it out of selection",
       len(kb.claims("coverings"))==before and not kb.pending_claims("coverings"))

    r=cl.get("/admin/intake_revoke",params={"key":"s3cret","token":tok})
    ck("a revoked link stops working", "no longer active" in cl.get(f"/intake/{tok}").text)

    r=cl.get("/admin/intake_new",params={"key":"s3cret","tenant":"nope"})
    ck("a link cannot be minted for an unknown account", "error" in r.json())
    ck("intake needs no admin key", cl.get(f"/intake/{tok}").status_code==200)
print(); print(f"{len(fails)} FAILED: {fails}" if fails else "all checks passed")
raise SystemExit(1 if fails else 0)
