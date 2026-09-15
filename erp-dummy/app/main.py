import os
import secrets
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import Base, engine, ensure_schema_compatibility, get_db
from app.models import AcademicResult, AttendanceRecord, Course, Student, SyncReceipt
from app.schemas import (AttendanceSyncIn, CourseSyncIn, ERPResultUpsert, ERPStudentCreate,
                         ERPUserCreate, InstitutionRef, StudentSyncIn)

on_vercel = bool(os.getenv("VERCEL"))
configured_token = settings.erp_api_token.get_secret_value()
if on_vercel and (len(configured_token) < 24 or configured_token.startswith("replace-")):
    raise RuntimeError("Set ERP_API_TOKEN to a random value of at least 24 characters")
if on_vercel and not settings.erp_institution_id.strip():
    raise RuntimeError("Set ERP_INSTITUTION_ID before deploying the ERP sandbox")

Base.metadata.create_all(bind=engine)
ensure_schema_compatibility()

app = FastAPI(title=settings.erp_name, version="1.0.0",
              docs_url=None if on_vercel else "/docs", redoc_url=None if on_vercel else "/redoc",
              openapi_url=None if on_vercel else "/openapi.json")


def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
    expected = settings.erp_api_token.get_secret_value()
    supplied = authorization[7:] if authorization and authorization.startswith("Bearer ") else ""
    if not expected:
        raise HTTPException(503, "ERP_API_TOKEN is not configured")
    if not secrets.compare_digest(supplied, expected):
        raise HTTPException(401, "Invalid ERP API token", headers={"WWW-Authenticate": "Bearer"})


def require_institution(institution: InstitutionRef) -> str:
    expected = settings.erp_institution_id.strip()
    if expected and institution.external_id != expected:
        raise HTTPException(403, "This ERP does not accept records for that institution")
    return institution.external_id or f"ekeekrta:{institution.ekeekrta_id}"


def already_received(db: Session, idempotency_key: str, event_type: str) -> bool:
    if db.query(SyncReceipt).filter(SyncReceipt.idempotency_key == idempotency_key).first():
        return True
    db.add(SyncReceipt(idempotency_key=idempotency_key, event_type=event_type))
    return False


def require_idempotency(value: Annotated[str | None, Header(alias="Idempotency-Key")] = None) -> str:
    if not value or len(value) > 200:
        raise HTTPException(422, "A valid Idempotency-Key header is required")
    return value


@app.get("/api/ekeekrta/health", dependencies=[Depends(require_token)])
def health():
    return {"status": "ok", "service": "erp-sandbox", "institution_id": settings.erp_institution_id or None}


@app.get("/api/ekeekrta/students", dependencies=[Depends(require_token)])
def export_students(db: Session = Depends(get_db)):
    """Expose ERP-owned student master records for an authenticated EKEEKRTA import."""
    rows = db.query(Student).filter(Student.role == "student").order_by(Student.institutional_id.asc()).all()
    return {
        "institution_id": settings.erp_institution_id or None,
        "students": [
            {"institutional_id": row.institutional_id, "name": row.name, "email": row.email,
             "department": row.department, "program": row.program, "batch": row.batch,
             "semester_number": row.semester_number, "section": row.section}
            for row in rows
        ],
    }


@app.get("/api/ekeekrta/users", dependencies=[Depends(require_token)])
def export_users(db: Session = Depends(get_db)):
    rows = db.query(Student).order_by(Student.role, Student.institutional_id.asc()).all()
    return {
        "institution_id": settings.erp_institution_id or None,
        "users": [
            {"role": row.role, "institutional_id": row.institutional_id, "name": row.name,
             "email": row.email, "department": row.department, "program": row.program,
             "batch": row.batch, "semester_number": row.semester_number, "section": row.section}
            for row in rows
        ],
    }


@app.get("/api/ekeekrta/results/{institutional_id}", dependencies=[Depends(require_token)])
def export_academic_result(institutional_id: str, db: Session = Depends(get_db)):
    institution_id = settings.erp_institution_id.strip() or None
    row = db.query(AcademicResult).filter(
        AcademicResult.institution_external_id == institution_id,
        AcademicResult.student_institutional_id == institutional_id,
    ).first()
    if not row:
        raise HTTPException(404, "Academic result not found")
    return {"institution_id": settings.erp_institution_id or None,
            "result": {"student_institutional_id": row.student_institutional_id,
                       "current_cgpa": row.current_cgpa, "completed_credits": row.completed_credits,
                       "remaining_credits": row.remaining_credits, "grading_scale_max": row.grading_scale_max,
                       "updated_at": row.updated_at}}


def _upsert_erp_user(payload: ERPUserCreate, db: Session):
    institution_id = settings.erp_institution_id.strip() or None
    row = db.query(Student).filter(
        Student.institution_external_id == institution_id,
        Student.institutional_id == payload.institutional_id,
    ).first()
    email_owner = db.query(Student).filter(Student.email == str(payload.email).lower()).first()
    if email_owner and (row is None or email_owner.id != row.id):
        raise HTTPException(409, "Email is already assigned to another ERP user")
    created = row is None
    if created:
        row = Student(institution_external_id=institution_id, ekeekrta_id=0,
                      institutional_id=payload.institutional_id, name=payload.name,
                      email=str(payload.email).lower(), role=payload.role)
        db.add(row)
    for field in ("role", "institutional_id", "name", "department", "program", "batch", "semester_number", "section"):
        setattr(row, field, getattr(payload, field))
    if payload.role != "student":
        row.program = row.batch = row.section = None
        row.semester_number = None
    row.email = str(payload.email).lower()
    db.commit(); db.refresh(row)
    return {"status": "created" if created else "updated", "institutional_id": row.institutional_id,
            "role": row.role}


@app.post("/api/users", dependencies=[Depends(require_token)], status_code=201)
def create_or_update_erp_user(payload: ERPUserCreate, db: Session = Depends(get_db)):
    """Create or update an ERP-owned student, faculty, or HOD identity."""
    return _upsert_erp_user(payload, db)


@app.post("/api/students", dependencies=[Depends(require_token)], status_code=201)
def create_or_update_erp_student(payload: ERPStudentCreate, db: Session = Depends(get_db)):
    """Create or update a real student master record directly in the ERP Sandbox."""
    return _upsert_erp_user(ERPUserCreate(role="student", **payload.model_dump()), db)


@app.post("/api/results", dependencies=[Depends(require_token)], status_code=201)
def create_or_update_academic_result(payload: ERPResultUpsert, db: Session = Depends(get_db)):
    institution_id = settings.erp_institution_id.strip() or None
    student = db.query(Student).filter(Student.institution_external_id == institution_id,
                                       Student.institutional_id == payload.student_institutional_id,
                                       Student.role == "student").first()
    if not student:
        raise HTTPException(404, "Register this student in the ERP before adding an academic result")
    row = db.query(AcademicResult).filter(AcademicResult.institution_external_id == institution_id,
                                          AcademicResult.student_institutional_id == payload.student_institutional_id).first()
    created = row is None
    if row is None:
        row = AcademicResult(institution_external_id=institution_id,
                             student_institutional_id=payload.student_institutional_id)
        db.add(row)
    for field in ("current_cgpa", "completed_credits", "remaining_credits", "grading_scale_max"):
        setattr(row, field, getattr(payload, field))
    db.commit(); db.refresh(row)
    return {"status": "created" if created else "updated", "student_institutional_id": row.student_institutional_id}


@app.post("/api/ekeekrta/students/sync", dependencies=[Depends(require_token)])
def sync_student(payload: StudentSyncIn, idempotency_key: str = Depends(require_idempotency),
                 db: Session = Depends(get_db)):
    institution_id = require_institution(payload.institution)
    if already_received(db, idempotency_key, "student"):
        db.rollback()
        return {"status": "already_synced", "institutional_id": payload.student.institutional_id}
    row = db.query(Student).filter(Student.institution_external_id == institution_id,
                                   Student.institutional_id == payload.student.institutional_id).first()
    if row is None:
        row = Student(institution_external_id=institution_id, institutional_id=payload.student.institutional_id,
                      ekeekrta_id=payload.student.ekeekrta_id, name=payload.student.name,
                      email=str(payload.student.email), role="student")
        db.add(row)
    elif row.role != "student":
        raise HTTPException(409, "The ERP identity is not a student")
    for field in ("ekeekrta_id", "institutional_id", "name", "department", "program", "batch", "semester_number", "section"):
        setattr(row, field, getattr(payload.student, field))
    row.email = str(payload.student.email)
    db.commit()
    return {"status": "synced", "institutional_id": row.institutional_id}


@app.post("/api/ekeekrta/courses/sync", dependencies=[Depends(require_token)])
def sync_course(payload: CourseSyncIn, idempotency_key: str = Depends(require_idempotency),
                db: Session = Depends(get_db)):
    institution_id = require_institution(payload.institution)
    if already_received(db, idempotency_key, "course"):
        db.rollback()
        return {"status": "already_synced", "course_code": payload.course.code}
    row = db.query(Course).filter(Course.institution_external_id == institution_id,
                                  Course.code == payload.course.code).first()
    if row is None:
        row = Course(institution_external_id=institution_id, code=payload.course.code,
                     ekeekrta_id=payload.course.ekeekrta_id, name=payload.course.name)
        db.add(row)
    for field in ("ekeekrta_id", "code", "name", "department", "course_type", "program", "batch",
                  "semester_number", "section", "enrollment_mode", "credits"):
        setattr(row, field, getattr(payload.course, field))
    row.faculty_institutional_id = payload.course.faculty.institutional_id if payload.course.faculty else None
    row.faculty_name = payload.course.faculty.name if payload.course.faculty else None
    db.commit()
    return {"status": "synced", "course_code": row.code}


@app.post("/api/ekeekrta/attendance/sync", dependencies=[Depends(require_token)])
def sync_attendance(payload: AttendanceSyncIn, idempotency_key: str = Depends(require_idempotency),
                    db: Session = Depends(get_db)):
    institution_id = require_institution(payload.institution)
    if already_received(db, idempotency_key, "attendance"):
        db.rollback()
        return {"status": "already_synced", "attendance_id": payload.attendance.ekeekrta_id}
    row = db.query(AttendanceRecord).filter(AttendanceRecord.institution_external_id == institution_id,
                                            AttendanceRecord.ekeekrta_id == payload.attendance.ekeekrta_id).first()
    if row is None:
        row = AttendanceRecord(institution_external_id=institution_id,
                               ekeekrta_id=payload.attendance.ekeekrta_id,
                               student_institutional_id=payload.student.institutional_id,
                               student_name=payload.student.name, course_code=payload.course.code,
                               course_name=payload.course.name,
                               class_session_id=payload.class_session.ekeekrta_id)
        db.add(row)
    row.student_institutional_id = payload.student.institutional_id
    row.student_name = payload.student.name
    row.course_code = payload.course.code
    row.course_name = payload.course.name
    row.class_session_id = payload.class_session.ekeekrta_id
    row.duration_minutes = payload.attendance.duration_minutes
    row.present = payload.attendance.present
    row.session_started_at = payload.class_session.scheduled_at
    row.session_ended_at = payload.class_session.ended_at
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Attendance record could not be synchronized") from None
    return {"status": "synced", "attendance_id": row.ekeekrta_id, "present": row.present}


@app.get("/api/dashboard", dependencies=[Depends(require_token)])
def dashboard_data(db: Session = Depends(get_db)):
    limit = settings.recent_record_limit
    users = db.query(Student)
    return {
        "name": settings.erp_name,
        "institution_id": settings.erp_institution_id or None,
        "counts": {"users": users.count(), "students": users.filter(Student.role == "student").count(),
                   "faculty": users.filter(Student.role == "faculty").count(),
                   "hod": users.filter(Student.role == "hod").count(), "courses": db.query(Course).count(),
                   "attendance": db.query(AttendanceRecord).count(), "results": db.query(AcademicResult).count()},
        "users": users.order_by(Student.synced_at.desc()).limit(limit).all(),
        "students": users.filter(Student.role == "student").order_by(Student.synced_at.desc()).limit(limit).all(),
        "courses": db.query(Course).order_by(Course.synced_at.desc()).limit(limit).all(),
        "attendance": db.query(AttendanceRecord).order_by(AttendanceRecord.synced_at.desc()).limit(limit).all(),
        "results": db.query(AcademicResult).order_by(AcademicResult.updated_at.desc()).limit(limit).all(),
    }


@app.get("/", response_class=HTMLResponse)
def dashboard():
    with open(os.path.join(os.path.dirname(__file__), "templates", "dashboard.html"), encoding="utf-8") as page:
        return page.read()
