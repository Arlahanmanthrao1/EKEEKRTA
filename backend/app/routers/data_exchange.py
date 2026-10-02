from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.access import course_access, tenant
from app.core.deps import require_roles
from app.database import get_db
from app.models.assignment import Assignment, Submission
from app.models.attendance import Attendance, ClassSession
from app.models.course import Enrollment
from app.models.data_exchange import DataExchangeProfile
from app.models.institution import InstitutionType
from app.models.quiz import Quiz, QuizAttempt
from app.models.user import User, UserRole
from app.schemas.data_exchange import DataExchangeProfileCreate, DataExchangeProfileOut

router = APIRouter(prefix="/data-exchange", tags=["university data exchange"])
faculty_only = require_roles(UserRole.faculty)

DATASETS = {
    "roster": [
        ("institutional_id", "Official ID"), ("student_name", "Student name"),
        ("email", "Email"), ("department", "Department"), ("program", "Program"),
        ("batch", "Academic batch"), ("semester_number", "Semester"), ("section", "Section"),
        ("course_code", "Course code"), ("course_name", "Course name"),
    ],
    "attendance": [
        ("institutional_id", "Official ID"), ("student_name", "Student name"),
        ("course_code", "Course code"), ("course_name", "Course name"),
        ("session_date", "Class date/time"), ("duration_minutes", "Minutes attended"),
        ("present", "Present"),
    ],
    "assignment_marks": [
        ("institutional_id", "Official ID"), ("student_name", "Student name"),
        ("course_code", "Course code"), ("course_name", "Course name"),
        ("assessment_title", "Assignment title"), ("maximum_marks", "Maximum marks"),
        ("marks_obtained", "Marks obtained"), ("submitted_at", "Submitted date/time"),
    ],
    "quiz_scores": [
        ("institutional_id", "Official ID"), ("student_name", "Student name"),
        ("course_code", "Course code"), ("course_name", "Course name"),
        ("assessment_title", "Quiz title"), ("maximum_marks", "Maximum marks"),
        ("marks_obtained", "Score"), ("submitted_at", "Attempt date/time"),
    ],
}


def _university_faculty(user: User) -> None:
    if not user.institution or user.institution.institution_type != InstitutionType.university.value:
        raise HTTPException(404, "Data Exchange is available only to university faculty")


def _iso(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _bounded(query):
    rows = query.limit(20001).all()
    if len(rows) > 20000:
        raise HTTPException(422, "This dataset exceeds 20,000 rows; use a narrower course export")
    return rows


def _validate_profile(payload: DataExchangeProfileCreate) -> None:
    if payload.data_type not in DATASETS:
        raise HTTPException(422, "Unsupported university dataset")
    allowed = {name for name, _ in DATASETS[payload.data_type]} | {"__blank__"}
    if set(payload.mapping) != set(payload.template_headers):
        raise HTTPException(422, "Map every destination column exactly once")
    for rule in payload.mapping.values():
        if rule.source not in allowed:
            raise HTTPException(422, f"Unknown source field: {rule.source}")
        if rule.transform not in {"none", "uppercase", "lowercase", "date_dmy", "present_pa", "present_10"}:
            raise HTTPException(422, f"Unsupported transformation: {rule.transform}")


def _owned_profile(db: Session, user: User, profile_id: int) -> DataExchangeProfile:
    row = db.query(DataExchangeProfile).filter(
        DataExchangeProfile.id == profile_id,
        DataExchangeProfile.institution_id == tenant(user),
        DataExchangeProfile.owner_id == user.id,
    ).first()
    if not row:
        raise HTTPException(404, "Mapping profile not found")
    return row


@router.get("/profiles", response_model=list[DataExchangeProfileOut])
def profiles(db: Session = Depends(get_db), user: User = Depends(faculty_only)):
    _university_faculty(user)
    return db.query(DataExchangeProfile).filter(
        DataExchangeProfile.institution_id == tenant(user),
        DataExchangeProfile.owner_id == user.id,
    ).order_by(DataExchangeProfile.updated_at.desc()).all()


@router.post("/profiles", response_model=DataExchangeProfileOut, status_code=201)
def create_profile(payload: DataExchangeProfileCreate, db: Session = Depends(get_db),
                   user: User = Depends(faculty_only)):
    _university_faculty(user)
    _validate_profile(payload)
    row = DataExchangeProfile(institution_id=tenant(user), owner_id=user.id,
                              **payload.model_dump(mode="json"))
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback(); raise HTTPException(409, "A mapping profile with this name already exists") from None
    db.refresh(row)
    return row


@router.put("/profiles/{profile_id}", response_model=DataExchangeProfileOut)
def update_profile(profile_id: int, payload: DataExchangeProfileCreate,
                   db: Session = Depends(get_db), user: User = Depends(faculty_only)):
    _university_faculty(user)
    _validate_profile(payload)
    row = _owned_profile(db, user, profile_id)
    for field, value in payload.model_dump(mode="json").items():
        setattr(row, field, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A mapping profile with this name already exists") from None
    db.refresh(row)
    return row


@router.delete("/profiles/{profile_id}", status_code=204)
def delete_profile(profile_id: int, db: Session = Depends(get_db), user: User = Depends(faculty_only)):
    _university_faculty(user)
    row = _owned_profile(db, user, profile_id)
    db.delete(row); db.commit()
    return Response(status_code=204)


@router.post("/profiles/{profile_id}/used")
def profile_used(profile_id: int, db: Session = Depends(get_db), user: User = Depends(faculty_only)):
    _university_faculty(user)
    row = _owned_profile(db, user, profile_id)
    from datetime import datetime
    row.export_count += 1; row.last_used_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "recorded", "export_count": row.export_count}


@router.get("/source/{data_type}")
def source_data(data_type: str, course_id: int, db: Session = Depends(get_db),
                user: User = Depends(faculty_only)):
    _university_faculty(user)
    if data_type not in DATASETS:
        raise HTTPException(404, "University dataset not found")
    course = course_access(db, user, course_id, manage=True)
    students = db.query(User).join(Enrollment, Enrollment.student_id == User.id).filter(
        Enrollment.course_id == course.id, User.institution_id == tenant(user),
        User.role == UserRole.student).order_by(User.name).all()
    if len(students) > 5000:
        raise HTTPException(422, "This export exceeds 5,000 learners; narrow the course scope")
    records = []
    if data_type == "roster":
        records = [{"institutional_id": student.institutional_id, "student_name": student.name,
                    "email": student.email, "department": student.department, "program": student.program,
                    "batch": student.batch, "semester_number": student.semester_number,
                    "section": student.section, "course_code": course.code, "course_name": course.name}
                   for student in students]
    elif data_type == "attendance":
        rows = _bounded(db.query(Attendance, ClassSession, User).join(
            ClassSession, ClassSession.id == Attendance.session_id).join(
            User, User.id == Attendance.student_id).filter(
            ClassSession.course_id == course.id,
            User.institution_id == tenant(user)).order_by(ClassSession.scheduled_at, User.name))
        records = [{"institutional_id": student.institutional_id, "student_name": student.name,
                    "course_code": course.code, "course_name": course.name,
                    "session_date": _iso(session.scheduled_at),
                    "duration_minutes": round(attendance.duration_minutes or 0, 2),
                    "present": bool(attendance.present)}
                   for attendance, session, student in rows]
    elif data_type == "assignment_marks":
        rows = _bounded(db.query(Submission, Assignment, User).join(
            Assignment, Assignment.id == Submission.assignment_id).join(
            User, User.id == Submission.student_id).filter(
            Assignment.course_id == course.id,
            User.institution_id == tenant(user)).order_by(Assignment.title, User.name))
        records = [{"institutional_id": student.institutional_id, "student_name": student.name,
                    "course_code": course.code, "course_name": course.name,
                    "assessment_title": assessment.title, "maximum_marks": assessment.max_marks,
                    "marks_obtained": submission.marks_obtained,
                    "submitted_at": _iso(submission.submitted_at)}
                   for submission, assessment, student in rows]
    else:
        rows = _bounded(db.query(QuizAttempt, Quiz, User).join(
            Quiz, Quiz.id == QuizAttempt.quiz_id).join(User, User.id == QuizAttempt.student_id).filter(
            Quiz.course_id == course.id,
            User.institution_id == tenant(user)).order_by(Quiz.title, User.name))
        records = [{"institutional_id": student.institutional_id, "student_name": student.name,
                    "course_code": course.code, "course_name": course.name,
                    "assessment_title": assessment.title, "maximum_marks": assessment.total_marks,
                    "marks_obtained": attempt.score, "submitted_at": _iso(attempt.submitted_at)}
                   for attempt, assessment, student in rows]
    return {"data_type": data_type,
            "fields": [{"name": name, "label": label} for name, label in DATASETS[data_type]],
            "records": records, "record_count": len(records),
            "course": {"id": course.id, "code": course.code, "name": course.name}}
