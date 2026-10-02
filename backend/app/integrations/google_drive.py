"""Trainer-owned Google Drive OAuth and recording uploads."""
from __future__ import annotations

from pathlib import Path
import re
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.core.secret_box import decrypt_secret
from app.models.google_drive import GoogleDriveConnection


DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"
_FOLDER_ID = re.compile(r"^[A-Za-z0-9_-]{10,180}$")


class DriveUploadError(RuntimeError):
    """Stable error code safe to show without leaking Google credentials."""


def extract_drive_folder_id(value: str | None) -> str | None:
    """Compatibility parser; authorization is still verified through OAuth."""
    if not value:
        return None
    try:
        parsed = urlparse(value.strip())
        segments = [part for part in parsed.path.split("/") if part]
        index = segments.index("folders")
        folder_id = segments[index + 1]
    except (ValueError, IndexError):
        return None
    return folder_id if parsed.scheme == "https" and parsed.hostname == "drive.google.com" and _FOLDER_ID.fullmatch(folder_id) else None


def drive_oauth_configured() -> bool:
    return bool(settings.google_drive_oauth_client_id.strip()
                and settings.google_drive_oauth_client_secret.get_secret_value().strip()
                and settings.google_drive_oauth_redirect_uri.strip())


def _connection(db: Session, trainer_id: int) -> GoogleDriveConnection:
    item = db.query(GoogleDriveConnection).filter(
        GoogleDriveConnection.user_id == trainer_id,
        GoogleDriveConnection.revoked_at.is_(None),
    ).first()
    if not item:
        raise DriveUploadError("trainer_drive_not_connected")
    return item


def refresh_access_token(db: Session, trainer_id: int) -> dict:
    if not drive_oauth_configured():
        raise DriveUploadError("drive_oauth_not_configured")
    connection = _connection(db, trainer_id)
    try:
        refresh_token = decrypt_secret(connection.encrypted_refresh_token)
        response = httpx.post("https://oauth2.googleapis.com/token", data={
            "client_id": settings.google_drive_oauth_client_id.strip(),
            "client_secret": settings.google_drive_oauth_client_secret.get_secret_value().strip(),
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }, timeout=20)
        payload = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise DriveUploadError("drive_authorization_unavailable") from error
    if response.status_code != 200 or not payload.get("access_token"):
        raise DriveUploadError("drive_authorization_expired")
    return {"access_token": payload["access_token"],
            "expires_in": int(payload.get("expires_in", 3600))}


def validate_drive_folder(db: Session, trainer_id: int, folder_id: str) -> dict:
    """Confirm that the trainer granted this app access to a real folder."""
    if not _FOLDER_ID.fullmatch(folder_id or ""):
        raise DriveUploadError("drive_folder_invalid")
    token = refresh_access_token(db, trainer_id)["access_token"]
    try:
        response = httpx.get(
            f"https://www.googleapis.com/drive/v3/files/{folder_id}",
            params={"fields": "id,name,mimeType,trashed", "supportsAllDrives": "true"},
            headers={"Authorization": f"Bearer {token}"}, timeout=20)
        payload = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise DriveUploadError("drive_folder_check_unavailable") from error
    if response.status_code != 200:
        raise DriveUploadError("drive_folder_not_authorized")
    if payload.get("mimeType") != "application/vnd.google-apps.folder" or payload.get("trashed"):
        raise DriveUploadError("drive_folder_invalid")
    return {"id": payload["id"], "name": payload.get("name") or "Selected folder"}


def upload_file_to_drive(db: Session, trainer_id: int, path: Path, filename: str,
                         content_type: str, folder_id: str) -> dict:
    """Stream a recording into the folder selected by this trainer."""
    path = path.resolve()
    if not path.is_file() or path.stat().st_size <= 0:
        raise DriveUploadError("drive_source_recording_missing")
    validate_drive_folder(db, trainer_id, folder_id)
    token = refresh_access_token(db, trainer_id)["access_token"]
    size = path.stat().st_size
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Type": content_type,
        "X-Upload-Content-Length": str(size),
    }
    try:
        started = httpx.post(
            "https://www.googleapis.com/upload/drive/v3/files",
            params={"uploadType": "resumable", "fields": "id,webViewLink", "supportsAllDrives": "true"},
            headers=headers, json={"name": filename[:180], "parents": [folder_id]}, timeout=30)
        if started.status_code not in (200, 201) or not started.headers.get("Location"):
            raise DriveUploadError("drive_upload_session_rejected")
        location = started.headers["Location"]
        chunk_size = settings.google_drive_upload_chunk_mb * 1024 * 1024
        with path.open("rb") as source:
            offset = 0
            while offset < size:
                chunk = source.read(min(chunk_size, size - offset))
                end = offset + len(chunk) - 1
                response = httpx.put(location, content=chunk, headers={
                    "Authorization": f"Bearer {token}", "Content-Type": content_type,
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {offset}-{end}/{size}",
                }, timeout=120)
                if response.status_code == 308:
                    offset = end + 1
                    continue
                if response.status_code not in (200, 201):
                    raise DriveUploadError("drive_upload_failed")
                result = response.json()
                if not result.get("id"):
                    raise DriveUploadError("drive_upload_response_invalid")
                return {"file_id": result["id"],
                        "web_url": result.get("webViewLink") or f"https://drive.google.com/file/d/{result['id']}/view"}
    except DriveUploadError:
        raise
    except (httpx.HTTPError, OSError, ValueError) as error:
        raise DriveUploadError("drive_upload_unavailable") from error
    raise DriveUploadError("drive_upload_incomplete")
