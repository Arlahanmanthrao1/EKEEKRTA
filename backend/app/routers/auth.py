from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app.models.user import User, UserRole
from app.schemas.user import UserCreate, UserOut, UserSessionOut
from app.schemas.auth import Token, GoogleLogin, PasswordChange
from app.config import settings
from app.models.google_identity import GoogleIdentity
from app.core.google_login import google_browser_context, verify_google_credential
from app.core.security import hash_password, verify_password, create_access_token
from app.core.deps import get_authenticated_user, get_current_user, require_roles

from app.core.access import tenant, department_name
from app.core.cohorts import enroll_matching_compulsory_courses
from app.core.institution_domains import request_login_host, institution_for_host

router = APIRouter(prefix="/auth", tags=["auth"])


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
    claims = {"sub": str(user.id), "role": user.role.value}
    if host:
        claims["login_host"] = host
    token = create_access_token(data=claims)
    return Token(access_token=token)


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
    db.commit()
    return {"message": "Password changed successfully"}
