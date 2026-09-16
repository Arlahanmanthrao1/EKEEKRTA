from datetime import datetime, timedelta, timezone
import hashlib
import logging
import secrets
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app.models.user import User, UserRole
from app.schemas.user import UserCreate, UserOut, UserSessionOut
from app.schemas.auth import ForgotPassword, GoogleLogin, PasswordChange, PasswordReset, Token
from app.config import settings
from app.models.google_identity import GoogleIdentity
from app.models.password_reset import PasswordResetToken
from app.core.google_login import google_browser_context, verify_google_credential
from app.core.password_mail import recovery_email_enabled, send_password_reset_email
from app.core.security import hash_password, verify_password, create_access_token
from app.core.deps import get_authenticated_user, get_current_user, require_roles

from app.core.access import tenant, department_name
from app.core.cohorts import enroll_matching_compulsory_courses
from app.core.institution_domains import request_login_host, institution_for_host

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)
RESET_REQUEST_MESSAGE = "If an eligible account exists, a password reset link has been sent."


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(
    user_in: UserCreate,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_roles(UserRole.admin)),
):
    """Administrator-only student creation using the approved college domain."""
    return _create_account(user_in, UserRole.student, db, _admin)


@router.post("/register-faculty", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register_faculty(
    user_in: UserCreate,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_roles(UserRole.admin)),
):
    """Administrator-only faculty creation; the caller cannot choose privileges."""
    return _create_account(user_in, UserRole.faculty, db, _admin)


@router.post("/register-hod", response_model=UserOut, status_code=201)
def register_hod(user_in: UserCreate, db: Session = Depends(get_db),
                 admin: User = Depends(require_roles(UserRole.admin))):
    return _create_account(user_in, UserRole.hod, db, admin)


def _create_account(user_in: UserCreate, role: UserRole, db: Session, admin: User):
    institution_id = tenant(admin)
    if user_in.email.split("@")[-1] != admin.institution.email_domain:
        raise HTTPException(422, f"Email must belong to the {admin.institution.email_domain} domain")
    department = department_name(db, admin, user_in.department)
    if not user_in.institutional_id:
        raise HTTPException(422, "Faculty, HOD and student accounts require an official institution ID")
    if role == UserRole.student and (
        not user_in.program or not user_in.batch or user_in.semester_number is None or not user_in.section
    ):
        raise HTTPException(422, "Student accounts require registration ID, program, batch, semester and section")
    existing = db.query(User).filter(func.lower(User.email) == user_in.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    if db.query(User).filter(
        User.institution_id == institution_id,
        func.lower(User.institutional_id) == user_in.institutional_id.lower(),
    ).first():
        raise HTTPException(status_code=409, detail="Official institution ID is already registered")

    user = User(
        name=user_in.name,
        email=user_in.email,
        hashed_password=hash_password(user_in.password),
        role=role,
        department=department,
        program=user_in.program if role == UserRole.student else None,
        batch=user_in.batch if role == UserRole.student else None,
        semester_number=user_in.semester_number if role == UserRole.student else None,
        section=user_in.section if role == UserRole.student else None,
        institutional_id=user_in.institutional_id,
        institution_id=institution_id,
    )
    db.add(user)
    try:
        db.flush()
        if role == UserRole.student:
            enroll_matching_compulsory_courses(db, user)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Email already registered") from None
    db.refresh(user)
    return user


@router.post("/login", response_model=Token)
def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    # OAuth2PasswordRequestForm uses "username" as the field name; we treat it as email.
    host = request_login_host(request)
    query = db.query(User).filter(func.lower(User.email) == form_data.username.strip().lower())
    if host:
        query = query.filter(User.institution_id == institution_for_host(host, db).id)
    user = query.first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    return login_token(user, host)


def login_token(user: User, host: str | None):
    tenant(user)
    claims = {"sub": str(user.id), "role": user.role.value, "session_version": int(user.session_version or 0)}
    if host:
        claims["login_host"] = host
    token = create_access_token(data=claims)
    return Token(access_token=token)


@router.get("/password-recovery/config")
def password_recovery_config(response: Response):
    response.headers["Cache-Control"] = "no-store"
    return {"enabled": recovery_email_enabled()}


def _deliver_reset_email(user_id: int, email: str, name: str, reset_url: str) -> None:
    try:
        send_password_reset_email(email, name, reset_url)
    except Exception:
        logger.exception("Password reset email delivery failed for user_id=%s", user_id)


@router.post("/forgot-password")
def forgot_password(payload: ForgotPassword, request: Request, background_tasks: BackgroundTasks,
                    db: Session = Depends(get_db)):
    """Create a short-lived reset token without disclosing account existence."""
    if not recovery_email_enabled():
        raise HTTPException(503, "Password recovery email is not configured. Contact your institution administrator.")
    host = request_login_host(request)
    query = db.query(User).filter(func.lower(User.email) == payload.email.lower())
    if host:
        query = query.filter(User.institution_id == institution_for_host(host, db).id)
    user = query.first()
    # Always perform token generation and hashing, even for unknown addresses.
    raw_token = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    if not user:
        return {"message": RESET_REQUEST_MESSAGE}

    now = datetime.now(timezone.utc)
    recent_cutoff = now - timedelta(minutes=15)
    recent_count = db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.created_at >= recent_cutoff,
    ).count()
    # Quietly throttle repeated requests so the response remains non-enumerating.
    if recent_count >= 3:
        return {"message": RESET_REQUEST_MESSAGE}

    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.used_at.is_(None),
    ).update({PasswordResetToken.used_at: now}, synchronize_session=False)
    reset = PasswordResetToken(
        user_id=user.id,
        token_hash=token_hash,
        login_host=host,
        expires_at=now + timedelta(minutes=settings.password_reset_expire_minutes),
    )
    db.add(reset)
    db.commit()

    base_url = f"https://{host}" if host else settings.password_reset_base_url.rstrip("/")
    reset_url = f"{base_url}/reset-password?token={quote(raw_token)}"
    # Delivery starts after the HTTP response, reducing account-enumeration timing
    # differences and keeping SMTP outages out of the public response.
    background_tasks.add_task(_deliver_reset_email, user.id, user.email, user.name, reset_url)
    return {"message": RESET_REQUEST_MESSAGE}


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


@router.post("/reset-password")
def reset_password(payload: PasswordReset, request: Request, db: Session = Depends(get_db)):
    token_hash = hashlib.sha256(payload.token.encode("utf-8")).hexdigest()
    reset = db.query(PasswordResetToken).filter(
        PasswordResetToken.token_hash == token_hash,
        PasswordResetToken.used_at.is_(None),
    ).first()
    host = request_login_host(request)
    now = datetime.now(timezone.utc)
    if not reset or _as_utc(reset.expires_at) <= now or reset.login_host != host:
        raise HTTPException(400, "This password reset link is invalid or has expired.")
    user = db.get(User, reset.user_id)
    if not user:
        raise HTTPException(400, "This password reset link is invalid or has expired.")
    if user.institutional_id and payload.new_password == user.institutional_id:
        raise HTTPException(422, "Your new password cannot be your Official ID")
    user.hashed_password = hash_password(payload.new_password)
    user.must_change_password = False
    user.session_version = int(user.session_version or 0) + 1
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.used_at.is_(None),
    ).update({PasswordResetToken.used_at: now}, synchronize_session=False)
    db.commit()
    return {"message": "Password reset successfully. Sign in with your new password."}


@router.get("/google/config")
def google_config(request: Request, response: Response, db: Session = Depends(get_db)):
    host = request_login_host(request)
    if host:
        institution_for_host(host, db)
    response.headers["Cache-Control"] = "no-store"
    return {"client_id": settings.google_client_id or None}


@router.post("/google", response_model=Token)
def google_login(payload: GoogleLogin, request: Request, response: Response, db: Session = Depends(get_db)):
    host = google_browser_context(request)
    profile = verify_google_credential(payload.credential, payload.nonce)
    institution = institution_for_host(host, db) if host else None
    link = db.get(GoogleIdentity, profile["subject"])
    user = db.get(User, link.user_id) if link else db.query(User).filter(func.lower(User.email) == profile["email"]).first()
    # First-time linking requires Google's authoritative Workspace email to match
    # an existing administrator-provisioned account. Never auto-create a user.
    if (not user or not user.institution or user.email.lower() != profile["email"]
            or user.institution.email_domain != profile["domain"]
            or (institution and user.institution_id != institution.id)):
        raise HTTPException(403, "No matching college account is available here. Contact your institution administrator.")
    tenant(user)
    if not link:
        if db.query(GoogleIdentity).filter(GoogleIdentity.user_id == user.id).first():
            raise HTTPException(403, "This college account is linked to a different Google identity. Contact your administrator.")
        db.add(GoogleIdentity(subject=profile["subject"], user_id=user.id))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            # Concurrent login may have linked the same verified identity.
            link = db.get(GoogleIdentity, profile["subject"])
            if not link or link.user_id != user.id:
                raise HTTPException(403, "Google account linking could not be completed. Contact your administrator.") from None
    response.headers["Cache-Control"] = "no-store"
    return login_token(user, host)


@router.get("/me", response_model=UserSessionOut)
def read_me(current_user: User = Depends(get_authenticated_user)):
    return current_user


@router.post("/change-password")
def change_password(payload: PasswordChange, db: Session = Depends(get_db),
                    current_user: User = Depends(get_authenticated_user)):
    if not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(400, "Current password is incorrect")
    if payload.new_password == payload.current_password:
        raise HTTPException(422, "Choose a new password different from the temporary password")
    if current_user.institutional_id and payload.new_password == current_user.institutional_id:
        raise HTTPException(422, "Your new password cannot be your Official ID")
    current_user.hashed_password = hash_password(payload.new_password)
    current_user.must_change_password = False
    current_user.session_version = int(current_user.session_version or 0) + 1
    db.commit()
    return {"message": "Password changed successfully"}
