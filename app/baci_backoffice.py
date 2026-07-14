"""Thin client for the Baci Backoffice inbound-logistics API (the rep/backoffice
PWA at BACI_BACKOFFICE_URL — a separate Render service, repo briefcard/baci-backoffice).

That system is the SOURCE OF TRUTH for inbound shipments + their customs/freight
document set. This agent is its conversational front-end over WhatsApp: it resolves
which shipment a forwarded PDF belongs to, uploads the file to Google Drive, and
registers the metadata + Drive link here. See AGENT-API.md in that repo for the
contract and the hard rules (dedup, match-before-write, explicit approvals).

Auth: a single bearer token (BACI_AGENT_TOKEN) that the backoffice accepts on its
inbound + documents endpoints only. All writes land in that system's timeline as
the synthetic identity 'agent@whatsapp'.
"""
import logging

import httpx

from . import config

log = logging.getLogger("baci_bo")

TIMEOUT = httpx.Timeout(20.0, connect=8.0)


class BackofficeError(RuntimeError):
    """A non-2xx response (other than the handled 409-duplicate)."""


class DuplicateShipment(RuntimeError):
    """POST /api/inbound hit the backoffice dedup guard. Carries the existing shipment."""

    def __init__(self, message: str, existing: dict):
        super().__init__(message)
        self.existing = existing


def enabled() -> bool:
    return bool(config.BACI_BACKOFFICE_URL and config.BACI_AGENT_TOKEN)


def _req(method: str, path: str, *, params: dict | None = None,
         json_body: dict | None = None) -> dict:
    if not enabled():
        raise BackofficeError(
            "Baci Backoffice is not configured — set BACI_BACKOFFICE_URL and "
            "BACI_AGENT_TOKEN.")
    url = config.BACI_BACKOFFICE_URL.rstrip("/") + path
    headers = {"Authorization": f"Bearer {config.BACI_AGENT_TOKEN}"}
    try:
        resp = httpx.request(method, url, params=params, json=json_body,
                             headers=headers, timeout=TIMEOUT)
    except httpx.HTTPError as exc:
        raise BackofficeError(f"Backoffice unreachable: {exc}") from exc
    if resp.status_code == 409:
        body = _safe_json(resp)
        if body.get("duplicate") and body.get("existing"):
            raise DuplicateShipment(body.get("error", "duplicate shipment"),
                                    body["existing"])
    if resp.status_code >= 400:
        body = _safe_json(resp)
        raise BackofficeError(body.get("error") or f"{resp.status_code} {resp.text[:200]}")
    return _safe_json(resp)


def _safe_json(resp: httpx.Response) -> dict:
    try:
        return resp.json()
    except ValueError:
        return {}


# ---- Reads (the agent's context) ----

def context() -> dict:
    """Live shipments + per-shipment doc checklists + company docs + required set."""
    return _req("GET", "/api/agent/shipments")


def get_shipment(shipment_id: str) -> dict:
    return _req("GET", f"/api/agent/shipments/{shipment_id}")


def match(query: str) -> list[dict]:
    """Resolve which shipment a ref / container / tracking number belongs to.
    Returns matches ranked strongest-first (reference > tracking > notes)."""
    return _req("GET", "/api/agent/match", params={"q": query}).get("matches", [])


# ---- Shipments (create / update) ----

def create_shipment(*, reference: str | None = None, origin: str | None = None,
                    status: str | None = None, eta: str | None = None,
                    carrier: str | None = None, tracking: str | None = None,
                    notes: str | None = None, lines: list[dict] | None = None,
                    allow_duplicate: bool = False) -> dict:
    """Create an inbound shipment. Raises DuplicateShipment if one already exists
    under the same canonical reference (unless allow_duplicate=True)."""
    body = _prune({
        "reference": reference, "origin": origin, "status": status, "eta": eta,
        "carrier": carrier, "tracking": tracking, "notes": notes, "lines": lines,
    })
    if allow_duplicate:
        body["allowDuplicate"] = True
    return _req("POST", "/api/inbound", json_body=body).get("shipment", {})


def update_shipment(shipment_id: str, **fields) -> dict:
    body = _prune({
        "status": fields.get("status"), "eta": fields.get("eta"),
        "origin": fields.get("origin"), "reference": fields.get("reference"),
        "carrier": fields.get("carrier"), "tracking": fields.get("tracking"),
        "notes": fields.get("notes"), "statusNote": fields.get("status_note"),
        "paymentStatus": fields.get("payment_status"),
        "paidAmount": fields.get("paid_amount"),
        "invoiceTotal": fields.get("invoice_total"),
    })
    return _req("POST", f"/api/inbound/{shipment_id}", json_body=body).get("shipment", {})


# ---- Documents ----

def register_document(shipment_id: str, *, doc_type: str, status: str = "received",
                      drive_url: str | None = None, drive_file_id: str | None = None,
                      filename: str | None = None, notes: str | None = None) -> dict:
    body = _prune({
        "docType": doc_type, "status": status, "driveUrl": drive_url,
        "driveFileId": drive_file_id, "filename": filename, "notes": notes,
    })
    return _req("POST", f"/api/inbound/{shipment_id}/documents", json_body=body)


def update_document(shipment_id: str, doc_id: str, **fields) -> dict:
    body = _prune({
        "status": fields.get("status"), "driveUrl": fields.get("drive_url"),
        "driveFileId": fields.get("drive_file_id"), "notes": fields.get("notes"),
    })
    return _req("POST", f"/api/inbound/{shipment_id}/documents/{doc_id}", json_body=body)


def create_company_document(*, doc_type: str, status: str = "filed",
                            expires_at: str | None = None, drive_url: str | None = None,
                            drive_file_id: str | None = None, filename: str | None = None,
                            notes: str | None = None) -> dict:
    body = _prune({
        "docType": doc_type, "status": status, "expiresAt": expires_at,
        "driveUrl": drive_url, "driveFileId": drive_file_id, "filename": filename,
        "notes": notes,
    })
    return _req("POST", "/api/documents", json_body=body).get("document", {})


def list_company_documents() -> list[dict]:
    return _req("GET", "/api/documents").get("documents", [])


def _prune(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None}
