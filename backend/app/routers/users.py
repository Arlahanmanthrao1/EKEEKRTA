from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User, UserRole
from app.models.ai import AIAction, AIAuditLog, AIKnowledgeSource, AILectureContent, AITrainingExample
from app.models.assignment import Submission
from app.models.attendance import Attendance
from app.models.course import Course, Enrollment
from app.models.google_identity import GoogleIdentity
from app.models.material import StudyMaterial
from app.models.programming import ProgrammingSubmission
from app.models.quiz import QuizAttempt
from app.models.erp import ERPIntegration
from app.schemas.user import UserOut
from app.core.deps import require_roles

from app.core.access import users_query, department_name
from app.core.cohorts import enroll_matching_compulsory_courses

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/", response_model=list[UserOut])
def list_users(
    db: Session = Depends(get_db),
    _=Depends(require_roles(UserRole.admin, UserRole.hod, UserRole.faculty)),
):
    return users_query(db, _).order_by(User.name).all()


class AccountDetails(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=2, max_length=120)
    department: str | None = None
    program: str | None = Field(default=None, max_length=120)
    batch: str | None = Field(default=None, max_length=40)
    semester_number: int | None = Field(default=None, ge=1, le=8)
    section: str | None = Field(default=None, max_length=40)
    institutional_id: str | None = Field(default=None, min_length=2, max_length=120)


@router.patch("/{user_id}", response_model=UserOut)
def update_account(user_id: int, payload: AccountDetails, db: Session = Depends(get_db),
                   admin: User = Depends(require_roles(UserRole.admin))):
    account = users_query(db, admin).filter(User.id == user_id).first()
    if not account:
        raise HTTPException(404, "Account not found")
    if account.role == UserRole.student and db.query(ERPIntegration).filter(
        ERPIntegration.institution_id == admin.institution_id,
        ERPIntegration.enabled.is_(True),
        ERPIntegration.sync_students.is_(True),
    ).first():
        raise HTTPException(409, "Student profiles are managed by the ERP. Update the ERP record and import again.")
    account.name = payload.name
    account.department = department_name(db, admin, payload.department) if account.role != UserRole.admin or payload.department else None
    if account.role != UserRole.admin:
        official_id = payload.institutional_id if "institutional_id" in payload.model_fields_set else account.institutional_id
        if not official_id:
            raise HTTPException(422, "Faculty, HOD and student accounts require an official institution ID")
        duplicate = db.query(User).filter(User.institution_id == admin.institution_id, User.id != account.id,
                                           func.lower(User.institutional_id) == official_id.lower()).first()
        if duplicate:
            raise HTTPException(409, "Official institution ID is already registered")
        account.institutional_id = official_id
    if account.role == UserRole.student:
        values = {}
        for field in ("program", "batch", "semester_number", "section", "institutional_id"):
            values[field] = getattr(payload, field) if field in payload.model_fields_set else getattr(account, field)
        if not all(values.values()):
            raise HTTPException(422, "Student accounts require registration ID, program, batch, semester and section")
        for field, value in values.items():
            setattr(account, field, value)
        enroll_matching_compulsory_courses(db, account)
    db.commit()
    db.refresh(account)
    return account


@router.delete("/{user_id}", status_code=204)
def delete_account(user_id: int, db: Session = Depends(get_db),
                   admin: User = Depends(require_roles(UserRole.admin))):
    account = users_query(db, admin).filter(User.id == user_id).first()
    if not account:
        raise HTTPException(404, "Account not found")
    if account.id == admin.id:
        raise HTTPException(409, "You cannot delete your own administrator account")

    protected_records = (
        db.query(Attendance.id).filter(Attendance.student_id == account.id).first()
        or db.query(Submission.id).filter(Submission.student_id == account.id).first()
        or db.query(QuizAttempt.id).filter(QuizAttempt.student_id == account.id).first()
        or db.query(ProgrammingSubmission.id).filter(ProgrammingSubmission.student_id == account.id).first()
        or db.query(StudyMaterial.id).filter(StudyMaterial.uploaded_by == account.id).first()
        or db.query(AIAction.id).filter(AIAction.requester_id == account.id).first()
        or db.query(AIAuditLog.id).filter(AIAuditLog.user_id == account.id).first()
        or db.query(AITrainingExample.id).filter(AITrainingExample.submitted_by == account.id).first()
        or db.query(AIKnowledgeSource.id).filter(AIKnowledgeSource.created_by == account.id).first()
        or db.query(AILectureContent.id).filter(AILectureContent.submitted_by == account.id).first()
    )
    if protected_records:
        raise HTTPException(
            409,
            "This account has academic or audit history and cannot be deleted. Its records must be preserved.",
        )

    # Course records remain available if their former faculty account is removed.
    db.query(Course).filter(Course.faculty_id == account.id).update(
        {Course.faculty_id: None}, synchronize_session=False
    )
    db.query(Enrollment).filter(Enrollment.student_id == account.id).delete(synchronize_session=False)
    db.query(GoogleIdentity).filter(GoogleIdentity.user_id == account.id).delete(synchronize_session=False)
    db.delete(account)
    db.commit()


class SemesterPromotion(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    department: str
    program: str = Field(min_length=2, max_length=120)
    batch: str = Field(min_length=2, max_length=40)
    from_semester: int = Field(ge=1, le=7)
    to_semester: int = Field(ge=2, le=8)


@router.post("/students/promote")
def promote_students(payload: SemesterPromotion, db: Session = Depends(get_db),
                     admin: User = Depends(require_roles(UserRole.admin))):
    if db.query(ERPIntegration).filter(
        ERPIntegration.institution_id == admin.institution_id,
        ERPIntegration.enabled.is_(True),
        ERPIntegration.sync_students.is_(True),
    ).first():
        raise HTTPException(409, "Student semesters are managed by the ERP. Update them there and import again.")
    if payload.to_semester != payload.from_semester + 1:
        raise HTTPException(422, "Students can be promoted only to the next semester")
    department = department_name(db, admin, payload.department)
    students = db.query(User).filter(
        User.institution_id == admin.institution_id,
        User.role == UserRole.student,
        User.department == department,
        func.lower(User.program) == payload.program.lower(),
        func.lower(User.batch) == payload.batch.lower(),
        User.semester_number == payload.from_semester,
    ).all()
    enrolled = 0
    for student in students:
        student.semester_number = payload.to_semester
        enrolled += enroll_matching_compulsory_courses(db, student)
    db.commit()
    return {"promoted_count": len(students), "new_enrollment_count": enrolled, "semester_number": payload.to_semester}
