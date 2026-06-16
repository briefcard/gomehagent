"""Google Drive write helpers (Shared Drive aware)."""
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload

from . import gmail_client

FOLDER = "application/vnd.google-apps.folder"
_svc_cache: dict = {}
_folder_cache: dict = {}

# Share the Gmail module's lock: one serialized lane for ALL Google API calls
# in this process (httplib2 is not thread-safe; concurrency segfaults).
from .gmail_client import _google_lock  # noqa: E402


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


def folder_tree(alias: str, root_id: str, depth: int = 3,
                _prefix: str = "") -> dict[str, str]:
    """Map of 'path/under/root' -> folder_id, excluding _Agent Intake."""
    out: dict[str, str] = {}
    if depth <= 0:
        return out
    resp = svc(alias).files().list(
        q=f"'{root_id}' in parents and mimeType = '{FOLDER}' and trashed = false",
        fields="files(id,name)", includeItemsFromAllDrives=True,
        supportsAllDrives=True, pageSize=100,
    ).execute()
    for f in resp.get("files", []):
        if f["name"].startswith("_Agent") or f["name"] == "OLD VERSIONS":
            continue
        path = f"{_prefix}{f['name']}"
        out[path] = f["id"]
        out.update(folder_tree(alias, f["id"], depth - 1, path + "/"))
    return out


def list_files(alias: str, folder_id: str) -> list[dict]:
    resp = svc(alias).files().list(
        q=f"'{folder_id}' in parents and mimeType != '{FOLDER}' and trashed = false",
        fields="files(id,name)", includeItemsFromAllDrives=True,
        supportsAllDrives=True, pageSize=200,
    ).execute()
    return resp.get("files", [])


def list_all_files_recursive(alias: str, folder_id: str, _prefix: str = "",
                             depth: int = 4) -> list[dict]:
    """Every file under a folder with its relative path — for intake refiling."""
    out = [dict(f, path=f"{_prefix}{f['name']}") for f in list_files(alias, folder_id)]
    if depth <= 0:
        return out
    resp = svc(alias).files().list(
        q=f"'{folder_id}' in parents and mimeType = '{FOLDER}' and trashed = false",
        fields="files(id,name)", includeItemsFromAllDrives=True,
        supportsAllDrives=True, pageSize=100,
    ).execute()
    for f in resp.get("files", []):
        out.extend(list_all_files_recursive(alias, f["id"],
                                            f"{_prefix}{f['name']}/", depth - 1))
    return out


def upload_html_as_doc(alias: str, folder_id: str, name: str, html: str) -> str:
    """Save an email body as a readable Google Doc (for receipts/notices that
    have no attachment — the email IS the record)."""
    from googleapiclient.http import MediaInMemoryUpload
    if file_exists(alias, folder_id, name):
        return "exists"
    created = svc(alias).files().create(
        body={"name": name, "parents": [folder_id],
              "mimeType": "application/vnd.google-apps.document"},
        media_body=MediaInMemoryUpload(html.encode("utf-8"), mimetype="text/html"),
        fields="webViewLink", supportsAllDrives=True,
    ).execute()
    return created.get("webViewLink", "uploaded")


def create_or_update_sheet(alias: str, name: str, csv_text: str,
                           parent_id: str | None = None,
                           existing_id: str | None = None) -> tuple[str, str]:
    """Create (or replace contents of) a Google Sheet from CSV. Returns
    (file_id, webViewLink). Uses Drive's CSV->Sheet conversion (no extra scope)."""
    from googleapiclient.http import MediaInMemoryUpload
    media = MediaInMemoryUpload(csv_text.encode("utf-8"), mimetype="text/csv",
                                resumable=False)
    if existing_id:
        f = svc(alias).files().update(
            fileId=existing_id, media_body=media,
            fields="id,webViewLink", supportsAllDrives=True).execute()
        return f["id"], f.get("webViewLink", "")
    body = {"name": name, "mimeType": "application/vnd.google-apps.spreadsheet"}
    if parent_id:
        body["parents"] = [parent_id]
    f = svc(alias).files().create(
        body=body, media_body=media, fields="id,webViewLink",
        supportsAllDrives=True).execute()
    return f["id"], f.get("webViewLink", "")


def download(alias: str, file_id: str) -> bytes:
    return svc(alias).files().get_media(fileId=file_id,
                                        supportsAllDrives=True).execute()


def move(alias: str, file_id: str, new_parent_id: str) -> None:
    meta = svc(alias).files().get(fileId=file_id, fields="parents",
                                  supportsAllDrives=True).execute()
    svc(alias).files().update(
        fileId=file_id, addParents=new_parent_id,
        removeParents=",".join(meta.get("parents", [])),
        supportsAllDrives=True,
    ).execute()


def ensure_path(alias: str, root_id: str, path: str) -> str:
    """Get-or-create nested folders 'A/B/C' under root; returns final id."""
    parent = root_id
    for segment in [p for p in path.split("/") if p.strip()]:
        parent = ensure_subfolder(alias, parent, segment.strip())
    return parent


def name_search(alias: str, keyword: str, limit: int = 8) -> list[dict]:
    """Files whose NAME contains the keyword (any folder, all drives)."""
    safe = keyword.replace("'", " ")
    resp = svc(alias).files().list(
        q=f"name contains '{safe}' and mimeType != '{FOLDER}' and trashed = false",
        fields="files(id,name,webViewLink,modifiedTime)",
        includeItemsFromAllDrives=True, supportsAllDrives=True,
        pageSize=limit, orderBy="modifiedTime desc",
    ).execute()
    return resp.get("files", [])


def copy_file(alias: str, file_id: str, dest_folder_id: str,
              new_name: str | None = None) -> str:
    body = {"parents": [dest_folder_id]}
    if new_name:
        body["name"] = new_name
    created = svc(alias).files().copy(
        fileId=file_id, body=body, fields="webViewLink", supportsAllDrives=True,
    ).execute()
    return created.get("webViewLink", "copied")


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


def _serialize(fn):
    def wrapped(*args, **kwargs):
        with _google_lock:
            return fn(*args, **kwargs)
    wrapped.__name__ = fn.__name__
    return wrapped


for _name in ("find_folder", "ensure_subfolder", "folder_tree", "list_files",
              "list_all_files_recursive", "move", "ensure_path", "name_search",
              "copy_file", "file_exists", "upload", "download",
              "upload_html_as_doc", "create_or_update_sheet"):
    globals()[_name] = _serialize(globals()[_name])
