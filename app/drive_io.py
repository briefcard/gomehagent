"""Google Drive write helpers (Shared Drive aware)."""
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload

from . import gmail_client

FOLDER = "application/vnd.google-apps.folder"
_svc_cache: dict = {}
_folder_cache: dict = {}


def svc(alias: str):
    if alias not in _svc_cache:
        _svc_cache[alias] = build(
            "drive", "v3", credentials=gmail_client.creds_for(alias),
            cache_discovery=False,
        )
    return _svc_cache[alias]


def find_folder(alias: str, name: str) -> str | None:
    """Find a folder by exact name anywhere (My Drive + Shared Drives)."""
    resp = svc(alias).files().list(
        q=f"name = '{name}' and mimeType = '{FOLDER}' and trashed = false",
        fields="files(id,name,driveId)",
        includeItemsFromAllDrives=True, supportsAllDrives=True, pageSize=5,
    ).execute()
    files = resp.get("files", [])
    return files[0]["id"] if files else None


def ensure_subfolder(alias: str, parent_id: str, name: str) -> str:
    key = (alias, parent_id, name)
    if key in _folder_cache:
        return _folder_cache[key]
    safe = name.replace("'", " ")[:80]
    resp = svc(alias).files().list(
        q=f"name = '{safe}' and '{parent_id}' in parents and "
          f"mimeType = '{FOLDER}' and trashed = false",
        fields="files(id)", includeItemsFromAllDrives=True,
        supportsAllDrives=True, pageSize=1,
    ).execute()
    files = resp.get("files", [])
    if files:
        _folder_cache[key] = files[0]["id"]
    else:
        created = svc(alias).files().create(
            body={"name": safe, "mimeType": FOLDER, "parents": [parent_id]},
            fields="id", supportsAllDrives=True,
        ).execute()
        _folder_cache[key] = created["id"]
    return _folder_cache[key]


def file_exists(alias: str, folder_id: str, filename: str) -> bool:
    safe = filename.replace("'", " ")
    resp = svc(alias).files().list(
        q=f"name = '{safe}' and '{folder_id}' in parents and trashed = false",
        fields="files(id)", includeItemsFromAllDrives=True,
        supportsAllDrives=True, pageSize=1,
    ).execute()
    return bool(resp.get("files"))


def upload(alias: str, folder_id: str, filename: str, data: bytes,
           mime: str = "application/octet-stream") -> str:
    """Upload unless a same-named file already exists. Returns webViewLink."""
    if file_exists(alias, folder_id, filename):
        return "exists"
    created = svc(alias).files().create(
        body={"name": filename, "parents": [folder_id]},
        media_body=MediaInMemoryUpload(data, mimetype=mime, resumable=False),
        fields="webViewLink", supportsAllDrives=True,
    ).execute()
    return created.get("webViewLink", "uploaded")
