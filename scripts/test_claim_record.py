"""The claim record (BUILD-MAP §17): who a claim is about, what it is true
of, as of when, what it rests on — and the per-entity workbook round trip.

Owner, 2026-11-06, on three Transak claims: "KYC is instantly approved" (a
staging help page), "secures 6 new US state licenses" (a point in time, not a
total), "the partnership between StellaSwap and Transak" (is it still in
place?) — "a reviewer would have no way of verifying, supporting or
approving them." And: "we should be able to input the evidence manually
either with a link or a statement from the team", and the export "split by
entities so that we can reupload them with fixes".

Run: python3 scripts/test_claim_record.py
"""
import datetime as dt
import io
import os
import sys
import tempfile

os.environ.setdefault("DATABASE_URL", f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'cr.db')}")
os.environ.setdefault("APPROVAL_SECRET", "s3cret")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, kb, kb_seed, tenants  # noqa: E402

_fail: list[str] = []
T = "baci"
SITE = "https://bacimilanousa.com"


def ck(name, ok, detail=""):
    print(f"[{'  ok  ' if ok else ' FAIL '}] {name}" + (f"  — {detail}" if detail and not ok else ""))
    if not ok:
        _fail.append(name)


def page(path, body, date="", title="Page"):
    from app.pipeline import fetch, parse
    meta = f'<meta property="article:published_time" content="{date}T09:00:00Z">' if date else ""
    html = (f"<html><head><title>{title}</title>{meta}</head><body><main><h1>{title}</h1>"
            f"{body}<p>{'Filler words for the page body. ' * 30}</p></main></body></html>")
    url = SITE + path
    fetch.store(T, url, html, parse.parse(html)["text_hash"])
    return url


def claim(text, url, proof="spec", context=""):
    with db.SessionLocal() as s:
        c = db.KbClaim(tenant=T, claim=text, source=f"stated on {url}", proof_type=proof,
                       context=context, review="proposed", status="active", origin="crawl")
        s.add(c)
        s.commit()
        return c.id


def get(cid):
    with db.SessionLocal() as s:
        r = s.get(db.KbClaim, cid)
        s.expunge(r)
        return r


def check_kinds():
    from app import claim_context as cc
    k = cc.kinds_of
    ck("KINDS 'secures 6 new licenses' is dated news and an increment — never a licence total",
       {"event", "increment"} <= set(k("Acme secures 6 new US state licenses")))
    ck("KINDS 'instantly approved' is absolute wording", "absolute" in k("KYC is instantly approved."))
    ck("KINDS a named partnership is a relationship",
       "relationship" in k("The partnership between StellaSwap and Acme ensures a smooth journey."))
    ck("KINDS a licence is regulatory", "regulatory" in k("Acme is registered with the FCA."))
    ck("KINDS a count of countries is coverage", "coverage" in k("Coverage of 18 + countries"))
    ck("KINDS 'higher conversion than competitors' is comparative",
       "comparative" in k("Acme has a higher conversion rate compared to our competitors."))
    ck("KINDS 'now live' is dated news", "event" in k("With this integration now live, users can buy."))
    ck("KINDS 'the first … provider to' is a superlative",
       "superlative" in k("Acme became the first crypto on/off-ramp provider to attain SOC II."))
    for t in ("The user is handed off only once.", "It broke $65B for the first time.",
              "We support multiple integration paths.", "available only for verified partners"):
        ck(f"KINDS no rank or relationship read into: {t!r}",
           not ({"superlative", "relationship"} & set(k(t))), str(k(t)))


def check_derive():
    from app import claim_record as cr
    cr.set_vocabulary(T, "qa-anna", self_names=["Acme"], evidence_required=True, record_required=True)
    kb.add_entity(T, "product", "offramp", "Off-ramp",
                  attributes={"match": {"urls": ["/sell", "/off-ramp"], "words": ["off-ramp"]}})
    kb.add_entity(T, "product", "stream", "Stream",
                  attributes={"match": {"urls": ["/stream"], "words": ["Acme Stream"]}})
    u_kyc = page("/help/kyc-staging", "<h2>Is KYC required on the staging environment?</h2>"
                 "<p>KYC is instantly approved.</p>", title="Is KYC required on the staging environment?")
    u_press = page("/blog/acme-secures-licenses", "<p>Acme secures 6 new US state licenses.</p>",
                   date=(dt.date.today() - dt.timedelta(days=500)).isoformat(), title="Acme secures licenses")
    u_part = page("/blog/stellaswap", "<p>The partnership between StellaSwap and Acme ensures a smooth "
                  "end to end user journey.</p>", date="2023-02-01", title="StellaSwap partners with Acme")
    u_off = page("/off-ramp", "<p>Integrate Off-Ramp to 18 + Countries</p>", title="Off-ramp")
    u_and = page("/buy/aave/andorra", "<p>Buy 136 + Cryptocurrencies in Andorra with Acme</p>")
    u_fca = page("/legal/uk", "<p>Acme Limited is a registered cryptoasset firm with the FCA.</p>")
    u_3p = page("/blog/market", "<p>ANZ Bank minted its A$DC stablecoin in March 2022.</p>", date="2024-01-01")
    ids = {
        "kyc": claim("KYC is instantly approved.", u_kyc),
        "press": claim("Acme secures 6 new US state licenses.", u_press),
        "part": claim("The partnership between StellaSwap and Acme ensures a smooth end to end user journey.", u_part),
        "off": claim("Integrate Off-Ramp to 18 + Countries", u_off, "data"),
        "and": claim("Buy 136 + Cryptocurrencies in Andorra with Acme", u_and, "data"),
        "fca": claim("Acme Limited is a registered cryptoasset firm with the FCA.", u_fca, "certification"),
        "3p": claim("ANZ Bank minted its A$DC stablecoin in March 2022.", u_3p, "case_study"),
    }
    out = cr.refresh(T)
    ck("DERIVE refresh reads every live claim", out["claims"] >= len(ids), str(out))
    r = {k: get(v) for k, v in ids.items()}
    ck("DERIVE the staging help page scopes 'instantly approved' to the sandbox",
       "sandbox" in (r["kyc"].scope or {}).get("environment", ""), str(r["kyc"].scope))
    ck("DERIVE a press item over a year old is history, with its date",
       (r["press"].scope or {}).get("history") is True and (r["press"].scope or {}).get("as_of"),
       str(r["press"].scope))
    ck("DERIVE the page date comes from the page's own markup",
       (r["part"].scope or {}).get("as_of") == "2023-02-01", str(r["part"].scope))
    ck("DERIVE the account naming itself makes it the account's claim",
       r["and"].subject == "self" and r["press"].subject == "self")
    ck("DERIVE an unattributed headline on the account's own product page is the account's",
       r["off"].subject == "self" and r["off"].subject_name == "own product page")
    ck("DERIVE a sentence about a third party is NOT made the account's (left for Claude / a reviewer)",
       r["3p"].subject == "", r["3p"].subject)
    ck("DERIVE the entity comes from the entity's own URL patterns",
       r["off"].entity_key == "offramp", r["off"].entity_key)
    v = cr.vocabulary(T)
    ck("DERIVE the page a claim sits on outranks a product merely named in it",
       cr.entity_of("Acme Stream users can also use the off-ramp.", SITE + "/stream", "", "", v)[0] == "stream")
    ck("DERIVE two products named on a neutral page are left to a person",
       cr.entity_of("Acme Stream and the off-ramp both settle fast.", SITE + "/blog/x", "", "", v)[0] == "")
    ck("DERIVE the market comes from a country page's address",
       (r["and"].scope or {}).get("market") == "Andorra", str(r["and"].scope))
    ck("DERIVE the regulator names the jurisdiction",
       (r["fca"].scope or {}).get("jurisdiction") == "United Kingdom", str(r["fca"].scope))
    ck("DERIVE every derived value says where it came from",
       all(k in (r["and"].scope_origin or {}) for k in (r["and"].scope or {})))
    return ids


def check_gate_and_evidence(ids):
    from app import claim_record as cr
    msg = kb.review_claim(ids["off"], True, by="qa-anna")
    ck("GATE a coverage count cannot be approved without its statement and evidence",
       msg.startswith("Not approved") and "Evidence (coverage)" in msg, msg[:200])
    ck("GATE a link must be a full address", not cr.add_evidence(T, ids["off"], "qa", "link", url="transak.com")["ok"])
    ck("GATE evidence needs who gave it", not cr.add_evidence(T, ids["off"], "", "statement", method="x")["ok"])
    cr.set_record(T, ids["off"], by="qa-anna", statement="As of Nov 2026, Acme's off-ramp is available in 18+ countries.")
    e = cr.add_evidence(T, ids["off"], "qa-anna", "statement",
                        method="Countries where off-ramp is enabled in the admin config", as_of="2026-11-01")
    ck("EVIDENCE the team's statement of how it is counted is recorded", e["ok"], str(e))
    msg = kb.review_claim(ids["off"], True, by="qa-anna")
    ck("GATE with statement, entity and the team's evidence it is approved", msg.startswith("Approved"), msg[:200])
    ck("GATE a third-party fact can never be approved as the account's claim",
       "Say who this is about" in kb.review_claim(ids["3p"], True, by="qa-anna"))
    cr.set_record(T, ids["kyc"], by="qa-anna", subject="self", entity_key="brand-wide",
                  statement="KYC is instantly approved.")
    cr.add_evidence(T, ids["kyc"], "qa-anna", "statement", method="dev docs say so")
    msg = kb.review_claim(ids["kyc"], True, by="qa-anna")
    ck("GATE a sandbox-only claim is refused until the statement says so",
       "sandbox" in msg and msg.startswith("Not approved"), msg[:200])
    cr.set_record(T, ids["part"], by="qa-anna", subject="self", entity_key="brand-wide",
                  statement="Acme is integrated into StellaSwap.")
    cr.add_evidence(T, ids["part"], "qa-anna", "statement", method="confirmed with partnerships",
                    as_of=(dt.date.today() - dt.timedelta(days=200)).isoformat())
    msg = kb.review_claim(ids["part"], True, by="qa-anna")
    ck("GATE a partnership needs confirmation it is still active — 200 days old is not",
       "partnership" in msg and msg.startswith("Not approved"), msg[:200])
    cr.add_evidence(T, ids["part"], "qa-anna", "statement", method="confirmed active with partnerships",
                    as_of=dt.date.today().isoformat())
    ck("GATE ... and a confirmation dated this week is", kb.review_claim(ids["part"], True, by="qa-anna").startswith("Approved"))
    # Regulatory needs a LINK; a broken one does not count.
    cr.set_record(T, ids["fca"], by="qa-anna", entity_key="brand-wide",
                  statement="Acme Limited is registered with the UK FCA as a cryptoasset firm.")
    cr.add_evidence(T, ids["fca"], "qa-anna", "statement", method="we are registered")
    ck("GATE a regulatory claim needs a link to the register, not only a statement",
       "Evidence (regulatory)" in kb.review_claim(ids["fca"], True, by="qa-anna"))
    e = cr.add_evidence(T, ids["fca"], "qa-anna", "link", url="https://register.fca.org.uk/s/firm?id=X", check=False)
    with db.SessionLocal() as s:
        s.get(db.KbEvidence, e["id"]).link_status = "broken"
        s.commit()
    ck("GATE a broken link supports nothing", "Evidence (regulatory)" in kb.review_claim(ids["fca"], True, by="qa"))
    with db.SessionLocal() as s:
        s.get(db.KbEvidence, e["id"]).link_status = "ok"
        s.commit()
    ck("GATE ... a resolving one does", kb.review_claim(ids["fca"], True, by="qa").startswith("Approved"))
    w = cr.withdraw_evidence(T, e["id"], "qa", "")
    ck("EVIDENCE withdrawing needs a reason", not w["ok"])
    ck("EVIDENCE withdrawn evidence is kept, marked", cr.withdraw_evidence(T, e["id"], "qa", "superseded")["ok"]
       and cr.evidence_for(T, [ids["fca"]], include_withdrawn=True)[ids["fca"]][-1]["status"] == "withdrawn")
    # History is kept and never selectable.
    kb.keep_as_history(ids["press"], by="qa-anna", reason="true on its date")
    ck("HISTORY a dated announcement kept as history is never offered to a draft",
       ids["press"] not in {c.id for c in kb.claims(T)})
    # Reviewer's word is final.
    cr.set_record(T, ids["and"], by="qa-anna", scope={"market": "Andorra (EU card users)"})
    cr.refresh(T)
    ck("RECORD a re-derive never overwrites the reviewer's value",
       get(ids["and"]).scope["market"] == "Andorra (EU card users)")
    from app import mcp_server
    out = mcp_server.propose_claim_record(T, ids["and"], market="Spain", statement="x")
    ck("RECORD Claude's proposal never overwrites the reviewer's value",
       get(ids["and"]).scope["market"] == "Andorra (EU card users)" and "market" in out["held_by_reviewer"],
       str(out))
    out = mcp_server.propose_claim_record(T, ids["3p"], subject="other", subject_name="ANZ Bank",
                                          why="the sentence is about ANZ")
    ck("RECORD Claude may propose who a sentence is about — proposed, not confirmed",
       out["ok"] and get(ids["3p"]).subject == "other" and get(ids["3p"]).record_status == "proposed")
    ck("RECORD an infeasible fragment says so instead of being guessed",
       mcp_server.propose_claim_record(T, ids["kyc"], infeasible=True)["ok"]
       and "not able to stand alone" in " ".join(cr.missing(T, get(ids["kyc"]))))
    ck("PROMPT the qualifiers ride with the claim",
       "on the site" in cr.qualifier_line(get(ids["off"])) and "offramp" in cr.qualifier_line(get(ids["off"])),
       cr.qualifier_line(get(ids["off"])))
    # Owner, 2026-11-07: proof is NOTED, not required — added after approval.
    cr.set_vocabulary(T, "qa", evidence_required=False, record_required=True)
    u = page("/nft-checkout", "<p>Allow users to buy NFTs from 26 + countries.</p>", title="NFT")
    nid = claim("Allow users to buy NFTs from 26 + countries.", u, "data")
    cr.refresh(T)
    msg = kb.review_claim(nid, True, by="qa-anna")
    ck("PROOF-LATER an incomplete RECORD still stops approval when the record is required",
       msg.startswith("Not approved") and "Evidence" not in msg, msg[:200])
    cr.set_record(T, nid, by="qa-anna", entity_key="brand-wide",
                  statement="Acme's NFT checkout lets users buy NFTs from 26+ countries.")
    msg = kb.review_claim(nid, True, by="qa-anna")
    ck("PROOF-LATER a complete record with no proof is approved — proof noted, not required",
       msg.startswith("Approved"), msg[:200])
    ck("PROOF-LATER ... and its proof reads as pending, for the writer and the reviewer",
       cr.proof_state(T, get(nid)) == "pending" and cr.proof_missing(T, get(nid)))
    cr.add_evidence(T, nid, "proof-role", "statement", method="countries enabled for NFT checkout")
    ck("PROOF-LATER proof added after approval turns it 'on file'", cr.proof_state(T, get(nid)) == "on file")
    cr.set_vocabulary(T, "qa", evidence_required=False, record_required=False)
    ck("GATE an account with neither switch on approves as before",
       cr.gate(T, get(ids["3p"])) == "")
    cr.set_vocabulary(T, "qa", evidence_required=True, record_required=True)


def cr_voc(t):
    from app import claim_record
    return claim_record.vocabulary(t)["entities"]


def check_workbook(ids):
    from openpyxl import load_workbook
    from app import change, claim_sheet as cs
    data = cs.export(T, "all")
    wb = load_workbook(io.BytesIO(data))
    names = [w.title for w in wb.worksheets]
    ck("WORKBOOK one sheet per entity, plus brand-wide, unassigned and the Entities sheet",
       {"Off-ramp", "Stream", "Brand-wide", "Not assigned", "Entities", "How to use"} <= set(names), str(names))
    sh = wb["Off-ramp"]
    hdr = [c.value for c in sh[1]]
    col = {f: hdr.index(h) + 1 for h, f, _w, _e in cs.COLUMNS}
    ck("WORKBOOK the off-ramp claim is on the Off-ramp sheet with its evidence",
       any(sh.cell(r, 1).value == ids["off"] and "admin config" in (sh.cell(r, col["ev_method"]).value or "")
           for r in range(2, sh.max_row + 1)))
    where = {}
    for w in wb.worksheets:
        if w.title in ("How to use", "Entities"):
            continue
        for r in range(2, w.max_row + 1):
            where[w.cell(r, 1).value] = (w, r)
    na, _ = where[ids["and"]]
    row_of = {na.cell(r, 1).value: r for r in range(2, na.max_row + 1)}
    # 1) split the Andorra claim across two entities; 2) replace the 3rd-party line on site; 3) a bad decision.
    cid = ids["and"]
    src = row_of[cid]
    vals = [na.cell(src, j).value for j in range(1, len(hdr) + 1)]
    na.cell(src, col["entity"]).value = "offramp"
    na.cell(src, col["statement"]).value = "Andorra: off-ramp copy."
    nr = na.max_row + 1
    for j, v in enumerate(vals, 1):
        na.cell(nr, j).value = v
    na.cell(nr, col["entity"]).value = "stream"
    na.cell(nr, col["statement"]).value = "Andorra: Stream copy."
    w3, r3 = where[ids["3p"]]
    ck("WORKBOOK a sentence about someone else sits on 'Not about us'", w3.title == "Not about us", w3.title)
    w3.cell(r3, col["decision"]).value = "remove from site"
    w3.cell(r3, col["reviewer"]).value = "qa-anna"
    w3.cell(r3, col["note"]).value = "a market fact, not ours"
    bad = nr + 1
    na.cell(bad, 1).value = ids["kyc"]
    na.cell(bad, col["decision"]).value = "maybe"
    es = wb["Entities"]
    es.cell(es.max_row + 1, 1).value = "nft-checkout"
    es.cell(es.max_row, 2).value = "NFT Checkout"
    es.cell(es.max_row, 4).value = "/nft-checkout"
    es.cell(es.max_row, 7).value = "Buy or mint NFTs with fiat."
    es.cell(es.max_row, 8).value = SITE + "/nft-checkout\n" + SITE + "/blog/nft-guide"
    for rr in range(2, es.max_row + 1):
        if es.cell(rr, 1).value == "stream":
            es.cell(rr, 7).value = "Crypto-to-cash via an assigned wallet address."
    buf = io.BytesIO()
    wb.save(buf)
    up = buf.getvalue()
    before = get(cid).entity_key
    p = cs.plan(T, up)
    ck("WORKBOOK 'check' writes nothing", get(cid).entity_key == before and p["ok"])
    ck("WORKBOOK 'check' names the bad decision with its sheet and row",
       any("maybe" in x["why"] and x["where"].startswith(na.title + "!") for x in p["refused"]), str(p["refused"]))
    a = cs.apply(T, up, "qa-anna")
    ck("WORKBOOK a new row on the Entities sheet creates the entity", "nft-checkout" in a["entities_added"])
    voc = {e["key"]: e for e in cr_voc(T)}
    ck("WORKBOOK the entity keeps its description and its reference pages",
       voc["nft-checkout"]["description"] == "Buy or mint NFTs with fiat."
       and voc["nft-checkout"]["references"] == [SITE + "/nft-checkout", SITE + "/blog/nft-guide"],
       str(voc.get("nft-checkout")))
    ck("WORKBOOK an edited existing entity is updated",
       "stream" in a["entities_updated"] and voc["stream"]["description"].startswith("Crypto-to-cash"))
    with db.SessionLocal() as s:
        copies = s.query(db.KbClaim).filter(db.KbClaim.tenant == T,
                                            db.KbClaim.entity_key.in_(("offramp", "stream")),
                                            db.KbClaim.statement.like("Andorra:%")).all()
        got = {(c.entity_key, c.statement) for c in copies}
    ck("WORKBOOK one claim, two rows, two entities = two claims, each with its own statement",
       got == {("offramp", "Andorra: off-ramp copy."), ("stream", "Andorra: Stream copy.")}, str(got))
    ch = next((x for x in change.listing(T) if x["subject"].startswith("wording:claim-")), None)
    ck("WORKBOOK 'remove from site' lists every page the claim is on as a task",
       ch is not None and any(t["location"].endswith("/blog/market") and t["replace"] in ("", None)
                              for t in ch["tasks"]), str(ch and ch["tasks"]))
    ck("WORKBOOK ... and the claim leaves the queue", get(ids["3p"]).review == "rejected")
    ck("WORKBOOK refusals come back with their row", any("!" in x["where"] and "maybe" in x["why"] for x in a["refused"]))


def check_console_controls():
    """Every new control, pressed over HTTP."""
    from fastapi.testclient import TestClient
    from app import web as _web, claim_record as cr, claim_sheet as cs
    c = TestClient(_web.app)
    u = page("/stream", "<p>Acme Stream is available across 18 + countries.</p>", title="Stream")
    cid = claim("Acme Stream is available across 18 + countries.", u, "data")
    cr.refresh(T)
    r = c.post("/admin/claim_record?key=s3cret", data={
        "tenant": T, "claim_id": cid, "subject": "self", "entity": "stream", "market": "",
        "statement": "As of Nov 2026, Acme Stream is available in 18+ countries.", "by": "qa-ben"},
        follow_redirects=False)
    row = get(cid)
    ck("CONSOLE 'Save record' sets the record as the reviewer's",
       r.status_code in (200, 303) and row.statement.startswith("As of Nov 2026")
       and row.scope_origin.get("entity") == "reviewer" and row.record_by == "qa-ben")
    r = c.post("/admin/claim_evidence?key=s3cret", data={
        "tenant": T, "claim_id": cid, "url": "", "method": "Countries enabled for Stream in config",
        "as_of": "2026-11-01", "by": "qa-ben", "action": "add"}, follow_redirects=False)
    ck("CONSOLE 'Add evidence' records the team's statement",
       r.status_code in (200, 303) and cr.evidence_for(T, [cid]).get(cid))
    eid = cr.evidence_for(T, [cid])[cid][0]["id"]
    r = c.post("/admin/claim_evidence?key=s3cret", data={
        "tenant": T, "claim_id": cid, "evidence_id": eid, "reason": "wrong system", "by": "qa-ben",
        "action": "withdraw"}, follow_redirects=False)
    ck("CONSOLE 'Withdraw' marks it withdrawn", not cr.evidence_for(T, [cid]).get(cid))
    r = c.post("/admin/claim_vocab?key=s3cret", data={
        "tenant": T, "self_names": "Acme, Acme Inc", "evidence_required": "1",
        "record_required": "1", "by": "qa-ben"},
        follow_redirects=False)
    ck("CONSOLE 'Save' names the account and keeps evidence required",
       cr.vocabulary(T)["self_names"] == ["Acme", "Acme Inc"] and cr.vocabulary(T)["evidence_required"]
       and cr.vocabulary(T)["record_required"])
    r = c.get(f"/admin/claims_workbook?key=s3cret&tenant={T}&review=proposed")
    ck("CONSOLE 'Download workbook' returns an .xlsx",
       r.status_code == 200 and r.content[:2] == b"PK" and "spreadsheetml" in r.headers.get("content-type", ""))
    r = c.post("/admin/claims_workbook_upload?key=s3cret", data={"tenant": T, "action": "check", "by": "qa"},
               files={"file": ("w.xlsx", r.content, "application/octet-stream")})
    ck("CONSOLE 'Check' reports and writes nothing", r.status_code == 200 and "Nothing has been written" in r.text)
    r = c.post("/admin/claims_workbook_upload?key=s3cret", data={"tenant": T, "action": "apply", "by": "qa"},
               files={"file": ("w.xlsx", cs.export(T, "proposed"), "application/octet-stream")})
    ck("CONSOLE 'Apply' applies and reports", r.status_code == 200 and "Applied" in r.text)
    r = c.post("/admin/claim_groups_rebuild_queued?key=s3cret", data={"tenant": T, "sub": "byentity"},
               follow_redirects=False)
    from app import jobs
    with db.SessionLocal() as s:
        kinds = {j.kind for j in s.query(db.JobQueue).filter(db.JobQueue.tenant == T)}
    ck("CONSOLE 'Recompute' queues the work on the worker, not the web process",
       r.status_code in (200, 303) and {"claim_records", "claim_groups"} <= kinds, str(kinds))
    from app import admin_ui
    html = admin_ui.render_content("s3cret", tenant=T, sub="byentity")
    ck("CONSOLE the Claims-by-entity tab renders its controls",
       "/admin/claims_workbook_upload" in html and "/admin/claim_vocab" in html)
    html = admin_ui.render_content("s3cret", tenant=T, sub="claims")
    ck("CONSOLE every queue card carries its record and the evidence form",
       "/admin/claim_record" in html and "/admin/claim_evidence" in html and "Before this can be approved" in html)


def check_rescan():
    """Owner, 2026-11-07: "run a new scan completely and toss the old info" —
    without tossing what people decided."""
    from fastapi.testclient import TestClient
    from app import web as _web, claim_record as cr, kb as _kb
    c = TestClient(_web.app)
    u = page("/pricing", "<p>Acme charges 1% per transaction.</p>", title="Pricing")
    crawled = claim("Acme charges 1% per transaction.", u, "data")
    _kb.add_claim(T, "Acme was founded in 2019.", "", [], origin="human", assess=False)
    with db.SessionLocal() as s:
        human = s.query(db.KbClaim).filter(db.KbClaim.tenant == T,
                                           db.KbClaim.claim == "Acme was founded in 2019.").one().id
        n_pages = s.query(db.PageSnapshot).filter(db.PageSnapshot.tenant == T).count()
    r = c.post("/admin/rescan?key=s3cret", data={"tenant": T, "confirm": "", "by": "qa"},
               follow_redirects=False)
    ck("RESCAN without typing the account's key nothing is removed",
       get(crawled) is not None and n_pages > 0)
    r = c.post("/admin/rescan?key=s3cret", data={"tenant": T, "confirm": T, "by": "qa"},
               follow_redirects=False)
    with db.SessionLocal() as s:
        pages_left = s.query(db.PageSnapshot).filter(db.PageSnapshot.tenant == T).count()
        crawled_left = s.get(db.KbClaim, crawled)
        human_left = s.get(db.KbClaim, human)
        ents = {e.key for e in s.query(db.KbEntity).filter(db.KbEntity.tenant == T)}
        job = (s.query(db.JobQueue).filter(db.JobQueue.tenant == T, db.JobQueue.kind == "harvest")
               .order_by(db.JobQueue.created_at.desc()).first())
        stmts = s.query(db.KbStatement).filter(db.KbStatement.tenant == T).count()
    ck("RESCAN removes the stored pages, the crawled claims and what was read off them",
       r.status_code in (200, 303) and pages_left == 0 and crawled_left is None and stmts == 0,
       f"pages {pages_left}, statements {stmts}")
    ck("RESCAN keeps a claim a person entered", human_left is not None)
    ck("RESCAN keeps the entities and the account's names and switches",
       {"offramp", "stream"} <= ents and "Acme" in cr.vocabulary(T)["self_names"]
       and cr.vocabulary(T)["record_required"])
    ck("RESCAN queues a full re-crawl on the worker",
       job is not None and (job.payload or {}).get("recrawl") is True
       and (job.payload or {}).get("limit", 0) >= 1000 and (job.payload or {}).get("apply") is True,
       str(job and job.payload))


def check_no_duplicates_and_mcp():
    """Owner, 2026-11-07: "make sure that the claims are connected not
    duplicated on upload. Also we should make MCP endpoint for this"."""
    from openpyxl import load_workbook
    from app import claim_record as cr, claim_sheet as cs, jobs, mcp_server
    def n_claims():
        with db.SessionLocal() as s:
            return s.query(db.KbClaim).filter(db.KbClaim.tenant == T).count()
    # Attaching via the workbook relinks the claim; uploading twice adds nothing.
    u = page("/otc", "<p>Acme OTC sources liquidity from 10+ exchanges.</p>", title="OTC")
    cid = claim("Acme OTC sources liquidity from 10+ exchanges.", u, "data")
    cr.refresh(T)
    data = cs.export(T, "all")
    wb = load_workbook(io.BytesIO(data))
    hdr = None
    for w in wb.worksheets:
        if w.title in ("How to use", "Entities"):
            continue
        hdr = [c.value for c in w[1]]
        col = {f: hdr.index(h) + 1 for h, f, _w, _e in cs.COLUMNS}
        for r in range(2, w.max_row + 1):
            if w.cell(r, 1).value == cid:
                w.cell(r, col["entity"]).value = "stream"
    buf = io.BytesIO(); wb.save(buf); up = buf.getvalue()
    before = n_claims()
    cs.apply(T, up, "qa")
    ck("NO-DUP attaching a claim to an entity relinks THAT claim — no copy is made",
       n_claims() == before and get(cid).entity_key == "stream", f"{before} -> {n_claims()}")
    cs.apply(T, up, "qa")
    ck("NO-DUP uploading the same workbook again adds nothing", n_claims() == before)
    # MCP: entities, bulk records, recompute.
    out = mcp_server.propose_entity(T, "otc", "Acme OTC", "product", description="Large trades.",
                                    url_patterns=["/otc"], words=["Acme OTC"],
                                    references=[SITE + "/otc"])
    again = mcp_server.propose_entity(T, "otc", "Acme OTC", "product", description="Large crypto trades.",
                                      url_patterns=["/otc"], words=["Acme OTC"], references=[SITE + "/otc"])
    with db.SessionLocal() as s:
        rows = s.query(db.KbEntity).filter(db.KbEntity.tenant == T, db.KbEntity.key == "otc").all()
        rv = rows[0].review if rows else ""
    ck("MCP propose_entity files a PROPOSED entity with its match rules and references",
       out["ok"] and rv == "proposed")
    ck("MCP proposing the same key again updates it — never a second entity", len(rows) == 1 and again["ok"])
    ents = {e["key"]: e for e in mcp_server.get_entities(T)["entities"]}
    ck("MCP get_entities returns match rules, references and claim counts",
       ents["otc"]["match"]["urls"] == ["/otc"] and ents["otc"]["references"] == [SITE + "/otc"]
       and "urls" not in ents["otc"] and isinstance(ents["stream"]["claims"], dict))
    before = n_claims()
    res = mcp_server.propose_claim_records(T, [{"claim_id": cid, "entity_key": "otc", "why": "on /otc"},
                                               {"claim_id": "nope", "entity_key": "otc"}])
    ck("MCP propose_claim_records attaches in bulk and reports what failed",
       res["written"] == 1 and res["failed"] == 1 and n_claims() == before)
    ck("MCP ... but never moves a claim a reviewer placed", get(cid).entity_key == "stream")
    ck("MCP propose_claim_records refuses more than its limit",
       not mcp_server.propose_claim_records(T, [{"claim_id": "x"}] * 501)["ok"])
    r = mcp_server.recompute_claim_records(T)
    with db.SessionLocal() as s:
        kinds = [j.kind for j in s.query(db.JobQueue).filter(db.JobQueue.tenant == T)]
    ck("MCP recompute_claim_records queues the work on the worker",
       r["ok"] and "claim_records" in kinds and "claim_groups" in kinds)


def main() -> int:
    db.init_db()
    tenants.seed()
    kb_seed.seed_all()
    check_kinds()
    ids = check_derive()
    check_gate_and_evidence(ids)
    check_workbook(ids)
    check_console_controls()
    check_no_duplicates_and_mcp()
    check_rescan()
    print(f"\n{'FAILED: ' + ', '.join(_fail) if _fail else 'all checks passed'}")
    return 1 if _fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
