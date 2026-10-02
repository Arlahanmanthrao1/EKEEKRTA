from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app.models.course import Course, Enrollment
from app.models.user import User, UserRole
from app.models.institution import InstitutionType
from app.schemas.course import CourseCreate, CourseCreditsUpdate, CourseOut, EnrollmentOut
from app.schemas.user import UserOut
from app.core.deps import get_current_user, require_roles

from app.core.access import course_access, courses_query, department_name, tenant
from app.core.cohorts import enroll_matching_students, student_matches_course
from app.integrations.erp_client import sync_course_to_erp
from app.integrations.google_drive import DriveUploadError, validate_drive_folder

router = APIRouter(prefix="/courses", tags=["courses"])


@router.post("/", response_model=CourseOut, status_code=201)
def create_course(
    course_in: CourseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.faculty, UserRole.admin)),
):
    existing = db.query(Course).filter(Course.code == course_in.code, Course.institution_id == tenant(current_user)).first()
    if existing:
        raise HTTPException(status_code=400, detail="Course code already exists")

    values = course_in.model_dump()
    is_training = current_user.institution.institution_type == InstitutionType.training_institution.value
    legacy_training_delivery = False
    if not is_training and values["course_type"] == "academic" and (
        not values["program"] or not values["batch"] or values["semester_number"] is None
    ):
        raise HTTPException(422, "Academic courses require program, batch and semester")
    if is_training:
        # A training course is a reusable program. Dates, trainer assignment,
        # capacity and recording destination belong to TrainingBatch.
        values["course_type"] = "academic"
        values["enrollment_mode"] = "elective"
        legacy_training_delivery = bool(values.get("batch") or values.get("recording_drive_folder_id"))
        if legacy_training_delivery:
            if not values.get("batch") or not values.get("recording_drive_folder_id"):
                raise HTTPException(422, "Legacy training delivery requires both a batch name and Drive folder")
            if current_user.role != UserRole.faculty:
                raise HTTPException(422, "A trainer must select the personal Drive folder")
            try:
                validate_drive_folder(db, current_user.id, values["recording_drive_folder_id"])
            except DriveUploadError as error:
                raise HTTPException(422, str(error).replace("_", " ")) from None
            values["enrollment_mode"] = course_in.enrollment_mode
        for field in ("program", "semester_number", "section", "semester"):
            values[field] = None
        if not legacy_training_delivery:
            values["batch"] = None
            values["recording_drive_folder_id"] = None
    else:
        if values.get("recording_drive_folder_id"):
            raise HTTPException(422, "Drive recording folders are configured only for training batches")
        values["recording_drive_folder_id"] = None
    values["department"] = department_name(db, current_user, course_in.department)
    if values["semester_number"] is not None:
        values["semester"] = f"Semester {values['semester_number']}"
    if current_user.role == UserRole.faculty and values["department"] != current_user.department:
        raise HTTPException(403, "Create courses only in your assigned department")
    course = Course(**values,
                    faculty_id=current_user.id if current_user.role == UserRole.faculty else None,
                    institution_id=tenant(current_user))
    db.add(course)
    try:
        db.flush()
        if not is_training or legacy_training_delivery:
            enroll_matching_students(db, course)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Course code already exists in your institution") from None
    db.refresh(course)
    sync_course_to_erp(db, course, current_user.institution)
    return course


@router.get("/", response_model=list[CourseOut])
def list_courses(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return courses_query(db, _, catalog=True).all()


@router.get("/enrolled", response_model=list[CourseOut])
def list_my_enrolled_courses(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.student)),
):
    """Powers the student dashboard's course list - only courses this
    student is actually enrolled in, not every course in the system."""
    return (
        db.query(Course)
        .join(Enrollment)
        .filter(Enrollment.student_id == current_user.id, Course.institution_id == tenant(current_user))
        .all()
    )


@router.get("/{course_id}", response_model=CourseOut)
def get_course(course_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    return course_access(db, _, course_id, catalog=True)


@router.patch("/{course_id}/credits", response_model=CourseOut)
def update_course_credits(course_id: int, payload: CourseCreditsUpdate, db: Session = Depends(get_db),
                          current_user: User = Depends(require_roles(UserRole.faculty, UserRole.admin))):
    course = course_access(db, current_user, course_id, manage=True)
    course.credits = payload.credits
    db.commit(); db.refresh(course)
    sync_course_to_erp(db, course, current_user.institution)
    return course


@router.post("/{course_id}/enroll", response_model=EnrollmentOut, status_code=201)
def enroll(
    course_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.student)),
):
    course = course_access(db, current_user, course_id, catalog=True)
    if current_user.institution.institution_type == InstitutionType.training_institution.value:
        raise HTTPException(403, "Learners are enrolled into batches by an administrator or trainer")
    if not student_matches_course(current_user, course):
        raise HTTPException(status_code=403, detail="This course is assigned to a different student cohort")

    existing = (
        db.query(Enrollment)
        .filter(Enrollment.course_id == course_id, Enrollment.student_id == current_user.id)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Already enrolled")

    enrollment = Enrollment(student_id=current_user.id, course_id=course_id)
    db.add(enrollment)
    db.commit()
    db.refresh(enrollment)
    return enrollment


def _require_owned_course(course_id: int, current_user: User, db: Session) -> Course:
    return course_access(db, current_user, course_id, manage=True)


@router.get("/{course_id}/students", response_model=list[UserOut])
def list_course_students(
    course_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.faculty)),
):
    _require_owned_course(course_id, current_user, db)
    return (
        db.query(User)
        .join(Enrollment, Enrollment.student_id == User.id)
        .filter(Enrollment.course_id == course_id, User.institution_id == tenant(current_user))
        .distinct()
        .order_by(User.name, User.id)
        .all()
    )


@router.delete("/{course_id}/students/{student_id}", status_code=204)
def remove_course_student(
    course_id: int,
    student_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.faculty)),
):
    """Remove only the enrollment, preserving the account and academic history."""
    _require_owned_course(course_id, current_user, db)
    removed = db.query(Enrollment).filter(
        Enrollment.course_id == course_id, Enrollment.student_id == student_id
    ).delete(synchronize_session=False)
    if not removed:
        db.rollback()
        raise HTTPException(status_code=404, detail="Student is not enrolled in this course")
    db.commit()
    return Response(status_code=204)
