import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import Base, engine, ensure_schema_compatibility, get_db
from app.models import (AcademicResult, AttendanceRecord, Course, OfflineClassSession,
                        Student, SyncReceipt, WhatsAppNotification)
from app.integrations.whatsapp import (configuration_status, notification_payload,
                                       send_absence_notification)
from app.schemas import (AttendanceSyncIn, CourseSyncIn, ERPResultUpsert, ERPStudentCreate,
                         ERPUserCreate, InstitutionRef, OfflineAttendanceCreate,
                         StudentSyncIn)

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


def _same_or_open(course_value, student_value) -> bool:
    return not course_value or (
        student_value is not None
        and str(course_value).strip().casefold() == str(student_value).strip().casefold()
    )


def _course_matches_student(course: Course, student: Student) -> bool:
    return all((
        _same_or_open(course.department, student.department),
        _same_or_open(course.program, student.program),
        _same_or_open(course.batch, student.batch),
        course.semester_number is None or course.semester_number == student.semester_number,
        _same_or_open(course.section, student.section),
    ))


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


@app.get("/api/academic-register-directory", dependencies=[Depends(require_token)])
def academic_register_directory(db: Session = Depends(get_db)):
    institution_id = settings.erp_institution_id.strip() or None
    query = db.query(Student).filter(
        Student.institution_external_id == institution_id,
        Student.role == "student",
    ).order_by(Student.institutional_id.asc())
    rows = query.limit(5001).all()
    if len(rows) > 5000:
        raise HTTPException(422, "Academic register directory exceeds 5,000 students")
    return {"students": [
        {"institutional_id": row.institutional_id, "name": row.name,
         "department": row.department, "program": row.program,
         "semester_number": row.semester_number, "section": row.section,
         "parent_name": row.parent_name,
         "parent_phone_last4": row.parent_phone[-4:] if row.parent_phone else None}
        for row in rows
    ]}


@app.get("/api/academic-register/{institutional_id}", dependencies=[Depends(require_token)])
def academic_register(institutional_id: str, db: Session = Depends(get_db)):
    """Return one student's real course and date-wise meeting attendance register."""
    institution_id = settings.erp_institution_id.strip() or None
    student = db.query(Student).filter(
        Student.institution_external_id == institution_id,
        Student.institutional_id == institutional_id,
        Student.role == "student",
    ).first()
    if not student:
        raise HTTPException(404, "Student not found in this ERP")

    course_rows = db.query(Course).filter(
        Course.institution_external_id == institution_id,
    ).order_by(Course.code.asc()).all()
    courses = [course for course in course_rows if _course_matches_student(course, student)]
    attendance_query = db.query(AttendanceRecord).filter(
        AttendanceRecord.institution_external_id == institution_id,
        AttendanceRecord.student_institutional_id == student.institutional_id,
    ).order_by(AttendanceRecord.session_started_at.asc(), AttendanceRecord.course_code.asc())
    attendance = attendance_query.limit(10001).all()
    if len(attendance) > 10000:
        raise HTTPException(422, "Academic register exceeds 10,000 attendance records")

    known_codes = {course.code for course in courses}
    course_payload = [
        {"code": course.code, "name": course.name, "course_type": course.course_type}
        for course in courses
    ]
    # A synchronized attendance record remains valid evidence even when its
    # course directory event has not arrived yet.
    for record in attendance:
        if record.course_code not in known_codes:
            course_payload.append({"code": record.course_code, "name": record.course_name,
                                   "course_type": None})
            known_codes.add(record.course_code)
    course_payload.sort(key=lambda item: item["code"].casefold())

    return {
        "student": {
            "institutional_id": student.institutional_id,
            "name": student.name,
            "department": student.department,
            "program": student.program,
            "batch": student.batch,
            "semester_number": student.semester_number,
            "section": student.section,
            "parent_name": student.parent_name,
            "parent_phone_last4": student.parent_phone[-4:] if student.parent_phone else None,
        },
        "courses": course_payload,
        "attendance": [
            {"course_code": record.course_code, "course_name": record.course_name,
             "class_session_id": record.class_session_id, "present": record.present,
             "duration_minutes": record.duration_minutes,
             "source": record.source,
             "session_started_at": record.session_started_at,
             "session_ended_at": record.session_ended_at}
            for record in attendance
        ],
    }


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
    for field in ("role", "institutional_id", "name", "department", "program", "batch",
                  "semester_number", "section", "parent_name", "parent_phone",
                  "parent_whatsapp_opt_in"):
        setattr(row, field, getattr(payload, field))
    if payload.role != "student":
        row.program = row.batch = row.section = None
        row.semester_number = None
        row.parent_name = None
        row.parent_phone = None
        row.parent_whatsapp_opt_in = False
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


@app.get("/api/offline-attendance/roster", dependencies=[Depends(require_token)])
def offline_attendance_roster(course_code: str, db: Session = Depends(get_db)):
    """Return the verified ERP roster for one course before faculty submission."""
    institution_id = settings.erp_institution_id.strip() or None
    course = db.query(Course).filter(
        Course.institution_external_id == institution_id,
        Course.code == course_code,
    ).first()
    if not course:
        raise HTTPException(404, "Course not found in this ERP")
    students = db.query(Student).filter(
        Student.institution_external_id == institution_id,
        Student.role == "student",
    ).order_by(Student.institutional_id.asc()).all()
    roster = [student for student in students if _course_matches_student(course, student)]
    faculty = db.query(Student).filter(
        Student.institution_external_id == institution_id,
        Student.role == "faculty",
    ).order_by(Student.name.asc()).all()
    return {
        "course": {"code": course.code, "name": course.name,
                   "faculty_institutional_id": course.faculty_institutional_id},
        "faculty": [{"institutional_id": row.institutional_id, "name": row.name}
                    for row in faculty],
        "students": [{"institutional_id": row.institutional_id, "name": row.name,
                      "department": row.department, "section": row.section}
                     for row in roster],
    }


@app.get("/api/offline-attendance/courses", dependencies=[Depends(require_token)])
def offline_attendance_courses(db: Session = Depends(get_db)):
    institution_id = settings.erp_institution_id.strip() or None
    rows = db.query(Course).filter(
        Course.institution_external_id == institution_id,
    ).order_by(Course.code.asc()).limit(5001).all()
    if len(rows) > 5000:
        raise HTTPException(422, "Offline attendance course directory exceeds 5,000 courses")
    return {"courses": [
        {"code": row.code, "name": row.name, "credits": row.credits,
         "department": row.department, "course_type": row.course_type,
         "program": row.program, "batch": row.batch,
         "semester_number": row.semester_number, "section": row.section,
         "faculty_institutional_id": row.faculty_institutional_id,
         "faculty_name": row.faculty_name}
        for row in rows
    ]}


@app.post("/api/offline-attendance", dependencies=[Depends(require_token)], status_code=201)
def submit_offline_attendance(payload: OfflineAttendanceCreate, db: Session = Depends(get_db)):
    """Finalize one physical class and alert opted-in parents for submitted absences."""
    institution_id = settings.erp_institution_id.strip() or None
    if payload.held_at > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise HTTPException(422, "Offline attendance can be submitted only for a class already held")
    course = db.query(Course).filter(
        Course.institution_external_id == institution_id,
        Course.code == payload.course_code,
    ).first()
    if not course:
        raise HTTPException(404, "Course not found in this ERP")
    faculty = db.query(Student).filter(
        Student.institution_external_id == institution_id,
        Student.institutional_id == payload.faculty_institutional_id,
        Student.role == "faculty",
    ).first()
    if not faculty:
        raise HTTPException(404, "Faculty member not found in this ERP")
    if (course.faculty_institutional_id and
            course.faculty_institutional_id.casefold() != faculty.institutional_id.casefold()):
        raise HTTPException(403, "Only the faculty assigned to this course can submit attendance")

    students = db.query(Student).filter(
        Student.institution_external_id == institution_id,
        Student.role == "student",
    ).order_by(Student.institutional_id.asc()).all()
    roster = [student for student in students if _course_matches_student(course, student)]
    roster_by_id = {row.institutional_id.casefold(): row for row in roster}
    submitted = {entry.student_institutional_id.casefold(): entry for entry in payload.attendance}
    if set(submitted) != set(roster_by_id):
        missing = sorted(row.institutional_id for key, row in roster_by_id.items() if key not in submitted)
        unknown = sorted(entry.student_institutional_id for key, entry in submitted.items()
                         if key not in roster_by_id)
        detail = "Submit one attendance status for every student in the verified course roster"
        if missing:
            detail += f"; missing: {', '.join(missing[:10])}"
        if unknown:
            detail += f"; not in roster: {', '.join(unknown[:10])}"
        raise HTTPException(422, detail)

    offline_class = OfflineClassSession(
        institution_external_id=institution_id,
        submission_id=str(payload.submission_id),
        course_code=course.code,
        course_name=course.name,
        faculty_institutional_id=faculty.institutional_id,
        faculty_name=faculty.name,
        held_at=payload.held_at,
        duration_minutes=payload.duration_minutes,
    )
    db.add(offline_class)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "This offline class attendance was already submitted") from None

    ended_at = payload.held_at + timedelta(minutes=payload.duration_minutes)
    records = []
    for index, student in enumerate(roster, start=1):
        entry = submitted[student.institutional_id.casefold()]
        record = AttendanceRecord(
            institution_external_id=institution_id,
            # Online EKEEKRTA IDs are positive. A stable negative namespace
            # keeps ERP-entered classes distinct without changing sync IDs.
            ekeekrta_id=-(offline_class.id * 1000 + index),
            student_institutional_id=student.institutional_id,
            student_name=student.name,
            course_code=course.code,
            course_name=course.name,
            class_session_id=-offline_class.id,
            duration_minutes=float(payload.duration_minutes if entry.present else 0),
            present=entry.present,
            session_started_at=payload.held_at,
            session_ended_at=ended_at,
            source="offline",
        )
        db.add(record)
        records.append((record, student))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Offline attendance could not be finalized") from None

    notifications = []
    for record, student in records:
        if not record.present:
            notifications.append(send_absence_notification(db, record, student))
    return {
        "status": "finalized",
        "offline_class_id": offline_class.id,
        "course_code": course.code,
        "students": len(records),
        "present": sum(1 for record, _ in records if record.present),
        "absent": sum(1 for record, _ in records if not record.present),
        "whatsapp_notifications": notifications,
    }


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
    row.source = "online"
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Attendance record could not be synchronized") from None
    student = db.query(Student).filter(
        Student.institution_external_id == institution_id,
        Student.institutional_id == row.student_institutional_id,
        Student.role == "student",
    ).first()
    notification = (send_absence_notification(db, row, student) if student else
                    {"status": "student_not_registered"})
    return {"status": "synced", "attendance_id": row.ekeekrta_id, "present": row.present,
            "whatsapp_notification": notification}


@app.get("/api/whatsapp-notifications", dependencies=[Depends(require_token)])
def whatsapp_notifications(db: Session = Depends(get_db)):
    institution_id = settings.erp_institution_id.strip() or None
    rows = db.query(WhatsAppNotification).filter(
        WhatsAppNotification.institution_external_id == institution_id,
    ).order_by(WhatsAppNotification.created_at.desc()).limit(500).all()
    return {"configuration": configuration_status(),
            "notifications": [notification_payload(row) for row in rows]}


@app.post("/api/whatsapp-notifications/{notification_id}/retry",
          dependencies=[Depends(require_token)])
def retry_whatsapp_notification(notification_id: int, db: Session = Depends(get_db)):
    institution_id = settings.erp_institution_id.strip() or None
    notification = db.query(WhatsAppNotification).filter(
        WhatsAppNotification.id == notification_id,
        WhatsAppNotification.institution_external_id == institution_id,
    ).first()
    if not notification:
        raise HTTPException(404, "WhatsApp notification not found")
    attendance = db.query(AttendanceRecord).filter(
        AttendanceRecord.id == notification.attendance_record_id,
        AttendanceRecord.institution_external_id == institution_id,
    ).first()
    student = db.query(Student).filter(
        Student.institution_external_id == institution_id,
        Student.institutional_id == notification.student_institutional_id,
        Student.role == "student",
    ).first()
    if not attendance or not student:
        raise HTTPException(409, "The attendance or student record is no longer available")
    return send_absence_notification(db, attendance, student)


@app.get("/api/dashboard", dependencies=[Depends(require_token)])
def dashboard_data(db: Session = Depends(get_db)):
    limit = settings.recent_record_limit
    users = db.query(Student)
    def dashboard_user(row: Student) -> dict:
        return {
            "id": row.id,
            "institution_external_id": row.institution_external_id,
            "role": row.role,
            "institutional_id": row.institutional_id,
            "name": row.name,
            "email": row.email,
            "department": row.department,
            "program": row.program,
            "batch": row.batch,
            "semester_number": row.semester_number,
            "section": row.section,
            "parent_name": row.parent_name,
            "parent_phone_last4": row.parent_phone[-4:] if row.parent_phone else None,
            "parent_whatsapp_opt_in": row.parent_whatsapp_opt_in,
            "synced_at": row.synced_at,
        }

    return {
        "name": settings.erp_name,
        "institution_id": settings.erp_institution_id or None,
        "counts": {"users": users.count(), "students": users.filter(Student.role == "student").count(),
                   "faculty": users.filter(Student.role == "faculty").count(),
                   "hod": users.filter(Student.role == "hod").count(), "courses": db.query(Course).count(),
                   "attendance": db.query(AttendanceRecord).count(), "results": db.query(AcademicResult).count(),
                   "offline_classes": db.query(OfflineClassSession).count(),
                   "whatsapp_alerts": db.query(WhatsAppNotification).count()},
        "users": [dashboard_user(row) for row in users.order_by(Student.synced_at.desc()).limit(limit).all()],
        "students": [dashboard_user(row) for row in users.filter(Student.role == "student")
                     .order_by(Student.synced_at.desc()).limit(limit).all()],
        "courses": db.query(Course).order_by(Course.synced_at.desc()).limit(limit).all(),
        "attendance": db.query(AttendanceRecord).order_by(AttendanceRecord.synced_at.desc()).limit(limit).all(),
        "results": db.query(AcademicResult).order_by(AcademicResult.updated_at.desc()).limit(limit).all(),
        "whatsapp": configuration_status(),
        "whatsapp_notifications": db.query(WhatsAppNotification).order_by(
            WhatsAppNotification.created_at.desc()).limit(limit).all(),
    }


@app.get("/", response_class=HTMLResponse)
def dashboard():
    with open(os.path.join(os.path.dirname(__file__), "templates", "dashboard.html"), encoding="utf-8") as page:
        return page.read()
