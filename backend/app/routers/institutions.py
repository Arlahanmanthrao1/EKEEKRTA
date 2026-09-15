from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.institution import Institution, Department
from app.models.user import User, UserRole
from app.schemas.institution import (InstitutionGradingUpdate, InstitutionProfile, InstitutionOut,
                                     InstitutionThemeUpdate, DepartmentCreate, DepartmentOut)
from app.schemas.user import UserCreate, UserOut
from app.core.security import hash_password
from app.core.deps import get_current_user, require_roles
from app.core.access import tenant
from app.config import settings
from app.core.institution_domains import request_login_host, institution_for_host

router = APIRouter(prefix="/institutions", tags=["institutions"])


class InstitutionRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    institution: InstitutionProfile
    administrator: UserCreate


@router.post("/register", response_model=UserOut, status_code=201)
def register_institution(payload: InstitutionRegistration, request: Request, db: Session = Depends(get_db)):
    """Atomically create a new isolated institution and its first administrator.

    This is self-service onboarding, not verification of domain ownership.
    """
    if request_login_host(request):
        raise HTTPException(403, "Register new institutions from the main EKEEKRTA site")
    profile, admin = payload.institution, payload.administrator
    domain = str(profile.email).lower().split("@")[-1]
    if admin.email.split("@")[-1] != domain:
        raise HTTPException(422, "Administrator email must use the institution email domain")
    if len(admin.password) < 12:
        raise HTTPException(422, "Administrator password must contain at least 12 characters")
    if admin.department:
        raise HTTPException(422, "Create departments after institution registration")
    values = profile.model_dump(mode="json")
    values["email"] = str(profile.email).lower()
    institution = Institution(**values, email_domain=domain)
    try:
        db.add(institution)
        db.flush()
        user = User(name=admin.name, email=admin.email, hashed_password=hash_password(admin.password),
                    role=UserRole.admin, institution_id=institution.id)
        db.add(user)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Institution domain or account email is already registered. Contact the existing administrator.") from None
    db.refresh(user)
    return user


@router.get("/login-profile")
def login_profile(request: Request, response: Response, db: Session = Depends(get_db)):
    host = request_login_host(request)
    if not host:
        raise HTTPException(404, "An institution login address is required")
    institution = institution_for_host(host, db)
    # The same API URL serves different hostname contexts; never cache branding
    # by URL alone at a shared proxy or CDN.
    response.headers["Cache-Control"] = "no-store"
    # Public branding only: no contact details, account list or internal IDs.
    return {"name": institution.name, "logo_url": institution.logo_url,
            "email_domain": institution.email_domain, "login_host": host}


@router.get("/current/login-address")
def login_address(user: User = Depends(require_roles(UserRole.admin))):
    domain = user.institution.email_domain
    host = f"ekeekrta.{domain}"
    return {"url": f"https://{host}/login",
            "configured": settings.institution_login_hosts.get(host) == domain}


@router.get("/current", response_model=InstitutionOut)
def current_institution(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.get(Institution, tenant(user))


@router.patch("/current", response_model=InstitutionOut)
def update_institution(payload: InstitutionProfile, db: Session = Depends(get_db),
                       user: User = Depends(require_roles(UserRole.admin))):
    institution = db.get(Institution, tenant(user))
    if str(payload.email).lower().split("@")[-1] != institution.email_domain:
        raise HTTPException(422, "Contact email must use your registered institution domain")
    for key, value in payload.model_dump(mode="json").items():
        setattr(institution, key, value)
    db.commit()
    db.refresh(institution)
    return institution


@router.patch("/current/theme", response_model=InstitutionOut)
def update_institution_theme(payload: InstitutionThemeUpdate, db: Session = Depends(get_db),
                             user: User = Depends(require_roles(UserRole.admin))):
    institution = db.get(Institution, tenant(user))
    institution.default_theme = payload.default_theme
    db.commit()
    db.refresh(institution)
    return institution


@router.patch("/current/grading", response_model=InstitutionOut)
def update_institution_grading(payload: InstitutionGradingUpdate, db: Session = Depends(get_db),
                               user: User = Depends(require_roles(UserRole.admin))):
    institution = db.get(Institution, tenant(user))
    institution.grading_scale_max = payload.grading_scale_max
    institution.passing_grade_point = payload.passing_grade_point
    db.commit()
    db.refresh(institution)
    return institution


@router.get("/departments", response_model=list[DepartmentOut])
def departments(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    query = db.query(Department).filter(Department.institution_id == tenant(user))
    if user.role == UserRole.hod:
        query = query.filter(Department.name == user.department)
    return query.order_by(Department.name).all()


@router.post("/departments", response_model=DepartmentOut, status_code=201)
def create_department(payload: DepartmentCreate, db: Session = Depends(get_db),
                      user: User = Depends(require_roles(UserRole.admin))):
    if db.query(Department).filter(Department.institution_id == tenant(user),
                                   func.lower(Department.name) == payload.name.lower()).first():
        raise HTTPException(409, "Department already exists")
    department = Department(name=payload.name, institution_id=tenant(user))
    db.add(department)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Department already exists") from None
    db.refresh(department)
    return department
