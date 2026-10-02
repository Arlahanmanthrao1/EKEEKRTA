"""Per-trainer Google Drive authorization for training recordings."""
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import secrets
from urllib.parse import urlencode, urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.core.access import tenant
from app.core.deps import require_roles
from app.core.secret_box import decrypt_secret, encrypt_secret
from app.database import get_db
from app.integrations.google_drive import (DRIVE_SCOPE, DriveUploadError,
                                           drive_oauth_configured,
                                           refresh_access_token,
                                           validate_drive_folder)
from app.models.google_drive import GoogleDriveConnection, GoogleDriveOAuthState
from app.models.institution import InstitutionType
from app.models.user import User, UserRole


router = APIRouter(prefix="/integrations/google-drive", tags=["google-drive"])


class FolderIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    folder_id: str = Field(min_length=10, max_length=180)


def _trainer(user: User) -> None:
    if user.institution.institution_type != InstitutionType.training_institution.value:
        raise HTTPException(403, "Personal Drive recording is available only to training-institution trainers")


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _return_url(status: str) -> str:
    target = settings.google_drive_frontend_return_url.strip()
    parsed = urlparse(target)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(500, "Google Drive frontend return URL is invalid")
    separator = "&" if parsed.query else "?"
    return f"{target}{separator}drive={status}"


@router.get("/status")
def status(db: Session = Depends(get_db), user: User = Depends(require_roles(UserRole.faculty))):
    _trainer(user)
    item = db.query(GoogleDriveConnection).filter(
        GoogleDriveConnection.user_id == user.id,
        GoogleDriveConnection.institution_id == tenant(user),
        GoogleDriveConnection.revoked_at.is_(None)).first()
    return {"oauth_configured": drive_oauth_configured(), "connected": bool(item),
            "google_email": item.google_email if item else None}


@router.post("/connect")
def connect(db: Session = Depends(get_db), user: User = Depends(require_roles(UserRole.faculty))):
    _trainer(user)
    if not drive_oauth_configured():
        raise HTTPException(503, "Google Drive OAuth is not configured by the Ekeekrta operator")
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    db.add(GoogleDriveOAuthState(institution_id=tenant(user), user_id=user.id,
        state_hash=hashlib.sha256(state.encode()).hexdigest(),
        encrypted_code_verifier=encrypt_secret(verifier),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10)))
    db.commit()
    query = urlencode({
        "client_id": settings.google_drive_oauth_client_id.strip(),
        "redirect_uri": settings.google_drive_oauth_redirect_uri.strip(),
        "response_type": "code", "scope": f"openid email {DRIVE_SCOPE}",
        "access_type": "offline", "prompt": "consent",
        "include_granted_scopes": "true", "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256",
    })
    return {"authorization_url": f"https://accounts.google.com/o/oauth2/v2/auth?{query}"}


@router.get("/callback", include_in_schema=False)
def callback(code: str = Query(min_length=1), state: str = Query(min_length=1),
             db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    item = db.query(GoogleDriveOAuthState).filter(
        GoogleDriveOAuthState.state_hash == hashlib.sha256(state.encode()).hexdigest(),
        GoogleDriveOAuthState.used_at.is_(None)).first()
    if not item or _utc(item.expires_at) <= now:
        raise HTTPException(400, "Google Drive authorization expired; return to Ekeekrta and connect again")
    item.used_at = now
    try:
        token_response = httpx.post("https://oauth2.googleapis.com/token", data={
            "client_id": settings.google_drive_oauth_client_id.strip(),
            "client_secret": settings.google_drive_oauth_client_secret.get_secret_value().strip(),
            "code": code, "code_verifier": decrypt_secret(item.encrypted_code_verifier),
            "grant_type": "authorization_code",
            "redirect_uri": settings.google_drive_oauth_redirect_uri.strip(),
        }, timeout=20)
        token_payload = token_response.json()
        access_token = token_payload.get("access_token")
        refresh_token = token_payload.get("refresh_token")
        if token_response.status_code != 200 or not access_token:
            raise ValueError("token exchange rejected")
        profile_response = httpx.get("https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {access_token}"}, timeout=20)
        profile = profile_response.json()
        if profile_response.status_code != 200 or not profile.get("email") or not profile.get("email_verified"):
            raise ValueError("verified Google email unavailable")
    except (httpx.HTTPError, ValueError):
        db.commit()
        raise HTTPException(502, "Google Drive authorization could not be completed") from None
    connection = db.query(GoogleDriveConnection).filter(GoogleDriveConnection.user_id == item.user_id).first()
    if not connection:
        if not refresh_token:
            db.commit()
            raise HTTPException(502, "Google did not issue an offline authorization; connect again")
        connection = GoogleDriveConnection(institution_id=item.institution_id, user_id=item.user_id,
            google_email=profile["email"], encrypted_refresh_token=encrypt_secret(refresh_token),
            scopes=token_payload.get("scope") or DRIVE_SCOPE)
        db.add(connection)
    else:
        connection.google_email = profile["email"]
        connection.institution_id = item.institution_id
        connection.revoked_at = None
        connection.scopes = token_payload.get("scope") or DRIVE_SCOPE
        if refresh_token:
            connection.encrypted_refresh_token = encrypt_secret(refresh_token)
    db.commit()
    return RedirectResponse(_return_url("connected"), status_code=303)


@router.post("/access-token")
def picker_token(db: Session = Depends(get_db), user: User = Depends(require_roles(UserRole.faculty))):
    _trainer(user)
    try:
        return refresh_access_token(db, user.id)
    except DriveUploadError as error:
        raise HTTPException(409, str(error).replace("_", " ")) from None


@router.post("/validate-folder")
def validate_folder(payload: FolderIn, db: Session = Depends(get_db),
                    user: User = Depends(require_roles(UserRole.faculty))):
    _trainer(user)
    try:
        return validate_drive_folder(db, user.id, payload.folder_id)
    except DriveUploadError as error:
        raise HTTPException(422, str(error).replace("_", " ")) from None


@router.delete("/connection", status_code=204)
def disconnect(db: Session = Depends(get_db), user: User = Depends(require_roles(UserRole.faculty))):
    _trainer(user)
    item = db.query(GoogleDriveConnection).filter(
        GoogleDriveConnection.user_id == user.id,
        GoogleDriveConnection.institution_id == tenant(user),
        GoogleDriveConnection.revoked_at.is_(None)).first()
    if item:
        try:
            refresh_token = decrypt_secret(item.encrypted_refresh_token)
            httpx.post("https://oauth2.googleapis.com/revoke", params={"token": refresh_token}, timeout=10)
        except (ValueError, httpx.HTTPError):
            pass
        item.revoked_at = datetime.now(timezone.utc)
        db.commit()
