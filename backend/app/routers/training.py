import csv
import io
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.core.access import tenant
from app.core.deps import get_current_user, require_roles
from app.database import get_db
from app.integrations.google_drive import DriveUploadError, validate_drive_folder
from app.models.assignment import Assignment, Submission
from app.models.attendance import Attendance, ClassSession
from app.models.course import Course, Enrollment
from app.models.institution import InstitutionType
from app.models.quiz import Quiz, QuizAttempt
from app.models.scheduled_class import ScheduledClass
from app.models.training import (TrainingBatch, TrainingBatchEnrollment, TrainingCertificate,
                                 TrainingLesson, TrainingLessonCompletion, TrainingModule)
from app.models.user import User, UserRole
from app.schemas.training import (BatchEnrollmentCreate, BatchEnrollmentOut, CertificateOut,
                                  TrainingBatchCreate, TrainingBatchOut, TrainingBatchUpdate,
                                  TrainingLessonCreate, TrainingLessonUpdate, TrainingModuleCreate, TrainingModuleOut,
                                  TrainingOrderUpdate,
                                  TrainingModuleUpdate)

router = APIRouter(prefix="/training", tags=["training institutions"])


def _require_training(user: User) -> None:
    if not user.institution or user.institution.institution_type != InstitutionType.training_institution.value:
        raise HTTPException(404, "Training workspace is not available for this institution")


def _batch_query(db: Session, user: User):
    _require_training(user)
    query = db.query(TrainingBatch).filter(TrainingBatch.institution_id == tenant(user))
    if user.role == UserRole.faculty:
        query = query.filter(TrainingBatch.trainer_id == user.id)
    elif user.role == UserRole.student:
        query = query.filter(TrainingBatch.id.in_(db.query(TrainingBatchEnrollment.batch_id).filter(
            TrainingBatchEnrollment.student_id == user.id,
            TrainingBatchEnrollment.status.in_(["active", "completed"]),
        )))
    elif user.role != UserRole.admin:
        query = query.filter(False)
    return query


def _batch(db: Session, user: User, batch_id: int, manage: bool = False) -> TrainingBatch:
    batch = _batch_query(db, user).filter(TrainingBatch.id == batch_id).first()
    if not batch:
        raise HTTPException(404, "Training batch not found")
    if manage and user.role not in (UserRole.admin, UserRole.faculty):
        raise HTTPException(403, "You cannot manage this training batch")
    return batch


def _batch_data(db: Session, batch: TrainingBatch) -> dict:
    learners = db.query(func.count(TrainingBatchEnrollment.id)).filter(
        TrainingBatchEnrollment.batch_id == batch.id,
        TrainingBatchEnrollment.status.in_(["active", "completed"]),
    ).scalar() or 0
    return {
        "id": batch.id, "institution_id": batch.institution_id, "course_id": batch.course_id,
        "trainer_id": batch.trainer_id, "name": batch.name, "code": batch.code,
        "start_date": batch.start_date, "end_date": batch.end_date, "status": batch.status,
        "capacity": batch.capacity, "certificate_enabled": batch.certificate_enabled,
        "certificate_min_progress": batch.certificate_min_progress,
        "certificate_min_attendance": batch.certificate_min_attendance,
        "recording_drive_folder_configured": bool(batch.recording_drive_folder_id),
        "created_at": batch.created_at, "course_name": batch.course.name,
        "course_code": batch.course.code, "trainer_name": batch.trainer.name,
        "learner_count": learners,
    }


def _trainer(db: Session, user: User, trainer_id: int | None) -> User:
    selected = user.id if user.role == UserRole.faculty else trainer_id
    if not selected:
        raise HTTPException(422, "Select a trainer")
    trainer = db.query(User).filter(
        User.id == selected, User.institution_id == tenant(user), User.role == UserRole.faculty
    ).first()
    if not trainer:
        raise HTTPException(422, "Trainer does not belong to this institution")
    if user.role == UserRole.faculty and trainer.id != user.id:
        raise HTTPException(403, "Trainers can create batches only for themselves")
    return trainer


def _ensure_course_enrollment(db: Session, batch: TrainingBatch, student_id: int) -> None:
    if not db.query(Enrollment).filter_by(course_id=batch.course_id, student_id=student_id).first():
        db.add(Enrollment(course_id=batch.course_id, student_id=student_id))


def _enroll(db: Session, batch: TrainingBatch, student: User) -> tuple[TrainingBatchEnrollment, bool]:
    if student.role != UserRole.student or student.institution_id != batch.institution_id:
        raise HTTPException(422, "Learner does not belong to this training institution")
    if batch.course.department and student.department != batch.course.department:
        raise HTTPException(422, "Learner belongs to a different domain")
    existing = db.query(TrainingBatchEnrollment).filter_by(batch_id=batch.id, student_id=student.id).first()
    if existing:
        if existing.status == "withdrawn":
            existing.status = "active"; existing.completed_at = None
        _ensure_course_enrollment(db, batch, student.id)
        return existing, False
    active = db.query(func.count(TrainingBatchEnrollment.id)).filter(
        TrainingBatchEnrollment.batch_id == batch.id,
        TrainingBatchEnrollment.status.in_(["active", "completed"]),
    ).scalar() or 0
    if active >= batch.capacity:
        raise HTTPException(409, "Batch capacity has been reached")
    record = TrainingBatchEnrollment(batch_id=batch.id, student_id=student.id)
    db.add(record); _ensure_course_enrollment(db, batch, student.id)
    return record, True


@router.get("/batches", response_model=list[TrainingBatchOut])
def list_batches(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = _batch_query(db, user).options(joinedload(TrainingBatch.course), joinedload(TrainingBatch.trainer)).order_by(
        TrainingBatch.start_date.desc(), TrainingBatch.id.desc()).all()
    return [_batch_data(db, row) for row in rows]


@router.post("/batches", response_model=TrainingBatchOut, status_code=201)
def create_batch(payload: TrainingBatchCreate, db: Session = Depends(get_db),
                 user: User = Depends(require_roles(UserRole.admin, UserRole.faculty))):
    _require_training(user)
    course = db.query(Course).filter(Course.id == payload.course_id, Course.institution_id == tenant(user)).first()
    if not course:
        raise HTTPException(422, "Training program does not belong to this institution")
    trainer = _trainer(db, user, payload.trainer_id)
    if course.department and trainer.department != course.department:
        raise HTTPException(422, "Trainer and program must belong to the same domain")
    values = payload.model_dump()
    values["trainer_id"] = trainer.id
    folder = values.get("recording_drive_folder_id")
    if folder:
        if user.role != UserRole.faculty:
            raise HTTPException(422, "The assigned trainer must connect and select their personal Drive folder")
        try:
            validate_drive_folder(db, user.id, folder)
        except DriveUploadError as error:
            raise HTTPException(422, str(error).replace("_", " ")) from None
    batch = TrainingBatch(**values, institution_id=tenant(user))
    db.add(batch)
    try:
        db.commit()
    except IntegrityError:
        db.rollback(); raise HTTPException(409, "Batch code already exists in this institution") from None
    db.refresh(batch)
    return _batch_data(db, batch)


@router.get("/batches/{batch_id}", response_model=TrainingBatchOut)
def get_batch(batch_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    batch = _batch(db, user, batch_id)
    return _batch_data(db, batch)


@router.patch("/batches/{batch_id}", response_model=TrainingBatchOut)
def update_batch(batch_id: int, payload: TrainingBatchUpdate, db: Session = Depends(get_db),
                 user: User = Depends(require_roles(UserRole.admin, UserRole.faculty))):
    batch = _batch(db, user, batch_id, manage=True)
    values = payload.model_dump(exclude_unset=True)
    if "trainer_id" in values:
        if user.role != UserRole.admin:
            raise HTTPException(403, "Only administrators can reassign trainers")
        trainer = _trainer(db, user, values["trainer_id"])
        if batch.course.department and trainer.department != batch.course.department:
            raise HTTPException(422, "Trainer and program must belong to the same domain")
        if trainer.id != batch.trainer_id:
            batch.recording_drive_folder_id = None
    if "recording_drive_folder_id" in values:
        folder = values.pop("recording_drive_folder_id")
        if user.role != UserRole.faculty:
            raise HTTPException(422, "The assigned trainer must select their personal Drive folder")
        try:
            validate_drive_folder(db, user.id, folder or "")
        except DriveUploadError as error:
            raise HTTPException(422, str(error).replace("_", " ")) from None
        batch.recording_drive_folder_id = folder
    for key, value in values.items():
        setattr(batch, key, value)
    if batch.end_date < batch.start_date:
        raise HTTPException(422, "Batch end date must be on or after its start date")
    learner_count = db.query(func.count(TrainingBatchEnrollment.id)).filter(
        TrainingBatchEnrollment.batch_id == batch.id,
        TrainingBatchEnrollment.status.in_(["active", "completed"])).scalar() or 0
    if batch.capacity < learner_count:
        raise HTTPException(422, "Capacity cannot be lower than current enrollment")
    if batch.status == "completed":
        db.query(TrainingBatchEnrollment).filter_by(batch_id=batch.id, status="active").update({
            TrainingBatchEnrollment.status: "completed",
            TrainingBatchEnrollment.completed_at: datetime.now(timezone.utc),
        }, synchronize_session=False)
    db.commit(); db.refresh(batch)
    return _batch_data(db, batch)


@router.get("/batches/{batch_id}/learners", response_model=list[BatchEnrollmentOut])
def list_learners(batch_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    batch = _batch(db, user, batch_id)
    rows = db.query(TrainingBatchEnrollment).options(joinedload(TrainingBatchEnrollment.student)).filter(
        TrainingBatchEnrollment.batch_id == batch.id).order_by(TrainingBatchEnrollment.enrolled_at).all()
    return [{"id": row.id, "batch_id": row.batch_id, "student_id": row.student_id,
             "status": row.status, "enrolled_at": row.enrolled_at, "completed_at": row.completed_at,
             "student_name": row.student.name, "student_email": row.student.email,
             "institutional_id": row.student.institutional_id} for row in rows]


@router.get("/batches/{batch_id}/available-learners")
def available_learners(batch_id: int, db: Session = Depends(get_db),
                       user: User = Depends(require_roles(UserRole.admin, UserRole.faculty))):
    batch = _batch(db, user, batch_id, manage=True)
    enrolled = db.query(TrainingBatchEnrollment.student_id).filter(
        TrainingBatchEnrollment.batch_id == batch.id,
        TrainingBatchEnrollment.status.in_(["active", "completed"]),
    )
    query = db.query(User).filter(
        User.institution_id == batch.institution_id,
        User.role == UserRole.student,
        ~User.id.in_(enrolled),
    )
    if batch.course.department:
        query = query.filter(func.lower(User.department) == batch.course.department.lower())
    return [{"id": row.id, "name": row.name, "email": row.email,
             "institutional_id": row.institutional_id, "department": row.department}
            for row in query.order_by(User.name, User.id).limit(2000).all()]


@router.post("/batches/{batch_id}/learners", response_model=BatchEnrollmentOut, status_code=201)
def add_learner(batch_id: int, payload: BatchEnrollmentCreate, db: Session = Depends(get_db),
                user: User = Depends(require_roles(UserRole.admin, UserRole.faculty))):
    batch = _batch(db, user, batch_id, manage=True)
    student = db.get(User, payload.student_id)
    record, created = _enroll(db, batch, student) if student else (None, False)
    if not student:
        raise HTTPException(404, "Learner not found")
    db.commit(); db.refresh(record)
    if not created:
        raise HTTPException(409, "Learner is already enrolled in this batch")
    return {"id": record.id, "batch_id": record.batch_id, "student_id": student.id,
            "status": record.status, "enrolled_at": record.enrolled_at, "completed_at": None,
            "student_name": student.name, "student_email": student.email,
            "institutional_id": student.institutional_id}


@router.post("/batches/{batch_id}/learners/csv")
async def import_learners_csv(batch_id: int, file: UploadFile = File(...), db: Session = Depends(get_db),
                              user: User = Depends(require_roles(UserRole.admin, UserRole.faculty))):
    batch = _batch(db, user, batch_id, manage=True)
    data = await file.read(1_000_001)
    if len(data) > 1_000_000:
        raise HTTPException(413, "CSV exceeds the 1 MB limit")
    try:
        reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
    except UnicodeDecodeError:
        raise HTTPException(422, "CSV must use UTF-8 encoding") from None
    fields = {str(value).strip().lower() for value in (reader.fieldnames or [])}
    if not fields.intersection({"email", "institutional_id"}):
        raise HTTPException(422, "CSV requires an email or institutional_id column")
    added, existing, errors, seen = 0, 0, [], set()
    for line, raw in enumerate(reader, start=2):
        row = {str(key).strip().lower(): (value or "").strip() for key, value in raw.items() if key}
        email, official_id = row.get("email", "").lower(), row.get("institutional_id", "")
        identity = (email, official_id)
        if not any(identity) or identity in seen:
            errors.append({"line": line, "error": "Missing or duplicate learner identity"}); continue
        seen.add(identity)
        student = db.query(User).filter(
            User.institution_id == tenant(user), User.role == UserRole.student,
            or_(User.email == email if email else False,
                User.institutional_id == official_id if official_id else False),
        ).first()
        if not student:
            errors.append({"line": line, "error": "Learner account not found"}); continue
        try:
            _, created = _enroll(db, batch, student)
            added += int(created); existing += int(not created)
            db.flush()
        except HTTPException as error:
            errors.append({"line": line, "error": error.detail})
    db.commit()
    return {"added": added, "already_enrolled": existing, "errors": errors,
            "processed": added + existing + len(errors)}


@router.delete("/batches/{batch_id}/learners/{student_id}", status_code=204)
def remove_learner(batch_id: int, student_id: int, db: Session = Depends(get_db),
                   user: User = Depends(require_roles(UserRole.admin, UserRole.faculty))):
    batch = _batch(db, user, batch_id, manage=True)
    record = db.query(TrainingBatchEnrollment).filter_by(batch_id=batch.id, student_id=student_id).first()
    if not record or record.status == "withdrawn":
        raise HTTPException(404, "Learner is not enrolled in this batch")
    record.status = "withdrawn"; record.completed_at = None
    other = db.query(TrainingBatchEnrollment).join(TrainingBatch).filter(
        TrainingBatchEnrollment.student_id == student_id,
        TrainingBatchEnrollment.status.in_(["active", "completed"]),
        TrainingBatch.course_id == batch.course_id,
        TrainingBatchEnrollment.batch_id != batch.id,
    ).first()
    if not other:
        db.query(Enrollment).filter_by(course_id=batch.course_id, student_id=student_id).delete()
    db.commit(); return Response(status_code=204)


@router.get("/batches/{batch_id}/modules", response_model=list[TrainingModuleOut])
def list_modules(batch_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    batch = _batch(db, user, batch_id)
    query = db.query(TrainingModule).options(joinedload(TrainingModule.lessons)).filter(
        TrainingModule.batch_id == batch.id)
    if user.role == UserRole.student:
        query = query.filter(TrainingModule.published.is_(True))
    modules = query.order_by(TrainingModule.position).all()
    completed = set()
    if user.role == UserRole.student:
        completed = {value for (value,) in db.query(TrainingLessonCompletion.lesson_id).filter(
            TrainingLessonCompletion.student_id == user.id).all()}
    return [{"id": module.id, "batch_id": module.batch_id, "title": module.title,
             "description": module.description, "position": module.position, "published": module.published,
             "lessons": [{"id": lesson.id, "module_id": lesson.module_id, "title": lesson.title,
                           "description": lesson.description, "resource_url": lesson.resource_url,
                           "position": lesson.position, "estimated_minutes": lesson.estimated_minutes,
                           "required": lesson.required, "completed": lesson.id in completed}
                          for lesson in module.lessons]} for module in modules]


@router.post("/batches/{batch_id}/modules", response_model=TrainingModuleOut, status_code=201)
def create_module(batch_id: int, payload: TrainingModuleCreate, db: Session = Depends(get_db),
                  user: User = Depends(require_roles(UserRole.admin, UserRole.faculty))):
    batch = _batch(db, user, batch_id, manage=True)
    position = payload.position or ((db.query(func.max(TrainingModule.position)).filter_by(batch_id=batch.id).scalar() or 0) + 1)
    module = TrainingModule(batch_id=batch.id, **payload.model_dump(exclude={"position"}), position=position)
    db.add(module)
    try:
        db.commit()
    except IntegrityError:
        db.rollback(); raise HTTPException(409, "Another module already uses this position") from None
    db.refresh(module)
    return {"id": module.id, "batch_id": module.batch_id, "title": module.title,
            "description": module.description, "position": module.position,
            "published": module.published, "lessons": []}


@router.patch("/modules/{module_id}", response_model=TrainingModuleOut)
def update_module(module_id: int, payload: TrainingModuleUpdate, db: Session = Depends(get_db),
                  user: User = Depends(require_roles(UserRole.admin, UserRole.faculty))):
    module = db.query(TrainingModule).options(joinedload(TrainingModule.lessons)).filter_by(id=module_id).first()
    if not module:
        raise HTTPException(404, "Module not found")
    _batch(db, user, module.batch_id, manage=True)
    for key, value in payload.model_dump(exclude_unset=True).items(): setattr(module, key, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback(); raise HTTPException(409, "Another module already uses this position") from None
    db.refresh(module)
    return {"id": module.id, "batch_id": module.batch_id, "title": module.title,
            "description": module.description, "position": module.position,
            "published": module.published, "lessons": module.lessons}


@router.put("/batches/{batch_id}/modules/order", status_code=204)
def reorder_modules(batch_id: int, payload: TrainingOrderUpdate, db: Session = Depends(get_db),
                    user: User = Depends(require_roles(UserRole.admin, UserRole.faculty))):
    batch = _batch(db, user, batch_id, manage=True)
    rows = db.query(TrainingModule).filter(TrainingModule.batch_id == batch.id).all()
    if len(payload.ordered_ids) != len(set(payload.ordered_ids)) or set(payload.ordered_ids) != {row.id for row in rows}:
        raise HTTPException(422, "Provide every module in this batch exactly once")
    by_id = {row.id: row for row in rows}
    for index, module_id in enumerate(payload.ordered_ids, start=1):
        by_id[module_id].position = -index
    db.flush()
    for index, module_id in enumerate(payload.ordered_ids, start=1):
        by_id[module_id].position = index
    db.commit()
    return Response(status_code=204)


@router.post("/modules/{module_id}/lessons", status_code=201)
def create_lesson(module_id: int, payload: TrainingLessonCreate, db: Session = Depends(get_db),
                  user: User = Depends(require_roles(UserRole.admin, UserRole.faculty))):
    module = db.get(TrainingModule, module_id)
    if not module:
        raise HTTPException(404, "Module not found")
    _batch(db, user, module.batch_id, manage=True)
    position = payload.position or ((db.query(func.max(TrainingLesson.position)).filter_by(module_id=module.id).scalar() or 0) + 1)
    values = payload.model_dump(exclude={"position"})
    if values.get("resource_url") is not None: values["resource_url"] = str(values["resource_url"])
    lesson = TrainingLesson(module_id=module.id, position=position, **values)
    db.add(lesson)
    try:
        db.commit()
    except IntegrityError:
        db.rollback(); raise HTTPException(409, "Another lesson already uses this position") from None
    db.refresh(lesson)
    return lesson


@router.patch("/lessons/{lesson_id}")
def update_lesson(lesson_id: int, payload: TrainingLessonUpdate, db: Session = Depends(get_db),
                  user: User = Depends(require_roles(UserRole.admin, UserRole.faculty))):
    lesson = db.query(TrainingLesson).options(joinedload(TrainingLesson.module)).filter_by(id=lesson_id).first()
    if not lesson:
        raise HTTPException(404, "Lesson not found")
    _batch(db, user, lesson.module.batch_id, manage=True)
    values = payload.model_dump(exclude_unset=True)
    if values.get("resource_url") is not None:
        values["resource_url"] = str(values["resource_url"])
    for key, value in values.items():
        setattr(lesson, key, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback(); raise HTTPException(409, "Another lesson already uses this position") from None
    db.refresh(lesson)
    return lesson


@router.put("/modules/{module_id}/lessons/order", status_code=204)
def reorder_lessons(module_id: int, payload: TrainingOrderUpdate, db: Session = Depends(get_db),
                    user: User = Depends(require_roles(UserRole.admin, UserRole.faculty))):
    module = db.get(TrainingModule, module_id)
    if not module:
        raise HTTPException(404, "Module not found")
    _batch(db, user, module.batch_id, manage=True)
    rows = db.query(TrainingLesson).filter(TrainingLesson.module_id == module.id).all()
    if len(payload.ordered_ids) != len(set(payload.ordered_ids)) or set(payload.ordered_ids) != {row.id for row in rows}:
        raise HTTPException(422, "Provide every lesson in this module exactly once")
    by_id = {row.id: row for row in rows}
    for index, lesson_id in enumerate(payload.ordered_ids, start=1):
        by_id[lesson_id].position = -index
    db.flush()
    for index, lesson_id in enumerate(payload.ordered_ids, start=1):
        by_id[lesson_id].position = index
    db.commit()
    return Response(status_code=204)


@router.get("/batches/{batch_id}/classes")
def batch_classes(batch_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    batch = _batch(db, user, batch_id)
    plans = db.query(ScheduledClass).filter(ScheduledClass.training_batch_id == batch.id).order_by(
        ScheduledClass.starts_at.desc()).limit(200).all()
    sessions = db.query(ClassSession).filter(ClassSession.training_batch_id == batch.id).order_by(
        ClassSession.scheduled_at.desc()).limit(200).all()
    return {
        "scheduled": [{"id": row.id, "title": row.title, "starts_at": row.starts_at,
                       "session_id": row.session_id,
                       "status": "cancelled" if row.cancelled_at else
                                 "ended" if row.session and row.session.ended_at else
                                 "live" if row.session_id else "scheduled"}
                      for row in plans],
        "sessions": [{"id": row.id, "course_id": row.course_id,
                      "training_batch_id": row.training_batch_id,
                      "scheduled_at": row.scheduled_at, "ended_at": row.ended_at,
                      "recording_url": row.recording_url}
                     for row in sessions],
    }


@router.post("/lessons/{lesson_id}/complete", status_code=201)
def complete_lesson(lesson_id: int, db: Session = Depends(get_db),
                    user: User = Depends(require_roles(UserRole.student))):
    lesson = db.query(TrainingLesson).join(TrainingModule).filter(
        TrainingLesson.id == lesson_id, TrainingModule.published.is_(True)).first()
    if not lesson:
        raise HTTPException(404, "Published lesson not found")
    _batch(db, user, lesson.module.batch_id)
    existing = db.query(TrainingLessonCompletion).filter_by(lesson_id=lesson.id, student_id=user.id).first()
    if existing: return {"status": "already_completed", "completed_at": existing.completed_at}
    row = TrainingLessonCompletion(lesson_id=lesson.id, student_id=user.id)
    db.add(row); db.commit(); db.refresh(row)
    return {"status": "completed", "completed_at": row.completed_at}


def _progress(db: Session, batch: TrainingBatch, student: User) -> dict:
    lesson_ids = [value for (value,) in db.query(TrainingLesson.id).join(TrainingModule).filter(
        TrainingModule.batch_id == batch.id, TrainingModule.published.is_(True), TrainingLesson.required.is_(True)).all()]
    lessons_done = db.query(func.count(TrainingLessonCompletion.id)).filter(
        TrainingLessonCompletion.student_id == student.id,
        TrainingLessonCompletion.lesson_id.in_(lesson_ids)).scalar() if lesson_ids else 0
    assignment_ids = [value for (value,) in db.query(Assignment.id).filter(Assignment.course_id == batch.course_id).all()]
    assignments_done = db.query(func.count(Submission.id)).filter(
        Submission.student_id == student.id, Submission.assignment_id.in_(assignment_ids)).scalar() if assignment_ids else 0
    quiz_ids = [value for (value,) in db.query(Quiz.id).filter(Quiz.course_id == batch.course_id).all()]
    quizzes_done = db.query(func.count(func.distinct(QuizAttempt.quiz_id))).filter(
        QuizAttempt.student_id == student.id, QuizAttempt.quiz_id.in_(quiz_ids)).scalar() if quiz_ids else 0
    session_ids = [value for (value,) in db.query(ClassSession.id).filter(ClassSession.training_batch_id == batch.id).all()]
    attended = db.query(func.count(Attendance.id)).filter(
        Attendance.student_id == student.id, Attendance.session_id.in_(session_ids), Attendance.present.is_(True)).scalar() if session_ids else 0
    rates = {
        "lessons": round(100 * lessons_done / len(lesson_ids)) if lesson_ids else None,
        "assignments": round(100 * assignments_done / len(assignment_ids)) if assignment_ids else None,
        "quizzes": round(100 * quizzes_done / len(quiz_ids)) if quiz_ids else None,
        "attendance": round(100 * attended / len(session_ids)) if session_ids else None,
    }
    weights = {"lessons": 40, "assignments": 25, "quizzes": 20, "attendance": 15}
    available = [(rates[key], weight) for key, weight in weights.items() if rates[key] is not None]
    overall = round(sum(value * weight for value, weight in available) / sum(weight for _, weight in available)) if available else 0
    attendance_ok = (batch.certificate_min_attendance <= 0 if rates["attendance"] is None
                     else rates["attendance"] >= batch.certificate_min_attendance)
    eligible = bool(batch.certificate_enabled and batch.status == "completed" and
                    overall >= batch.certificate_min_progress and attendance_ok)
    return {"student_id": student.id, "student_name": student.name, "institutional_id": student.institutional_id,
            "lesson_completed": lessons_done, "lesson_total": len(lesson_ids),
            "assignment_completed": assignments_done, "assignment_total": len(assignment_ids),
            "quiz_completed": quizzes_done, "quiz_total": len(quiz_ids),
            "sessions_attended": attended, "session_total": len(session_ids),
            "rates": rates, "overall_percent": overall, "certificate_eligible": eligible}


@router.get("/batches/{batch_id}/progress")
def batch_progress(batch_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    batch = _batch(db, user, batch_id)
    if user.role == UserRole.student:
        return {"batch": _batch_data(db, batch), "learners": [_progress(db, batch, user)]}
    students = db.query(User).join(TrainingBatchEnrollment, TrainingBatchEnrollment.student_id == User.id).filter(
        TrainingBatchEnrollment.batch_id == batch.id,
        TrainingBatchEnrollment.status.in_(["active", "completed"])).order_by(User.name).all()
    return {"batch": _batch_data(db, batch), "learners": [_progress(db, batch, student) for student in students]}


def _certificate_data(row: TrainingCertificate) -> dict:
    return {"id": row.id, "batch_id": row.batch_id, "student_id": row.student_id,
            "certificate_number": row.certificate_number, "issued_at": row.issued_at,
            "eligibility_snapshot": row.eligibility_snapshot, "revoked_at": row.revoked_at,
            "learner_name": row.student.name, "batch_name": row.batch.name,
            "course_name": row.batch.course.name, "institution_name": row.batch.institution.name}


@router.get("/batches/{batch_id}/certificates", response_model=list[CertificateOut])
def list_certificates(batch_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    batch = _batch(db, user, batch_id)
    query = db.query(TrainingCertificate).options(
        joinedload(TrainingCertificate.student), joinedload(TrainingCertificate.batch).joinedload(TrainingBatch.course),
        joinedload(TrainingCertificate.batch).joinedload(TrainingBatch.institution)).filter(
            TrainingCertificate.batch_id == batch.id)
    if user.role == UserRole.student: query = query.filter(TrainingCertificate.student_id == user.id)
    return [_certificate_data(row) for row in query.order_by(TrainingCertificate.issued_at.desc()).all()]


@router.post("/batches/{batch_id}/certificates/{student_id}", response_model=CertificateOut, status_code=201)
def issue_certificate(batch_id: int, student_id: int, db: Session = Depends(get_db),
                      user: User = Depends(require_roles(UserRole.admin, UserRole.faculty))):
    batch = _batch(db, user, batch_id, manage=True)
    membership = db.query(TrainingBatchEnrollment).filter(
        TrainingBatchEnrollment.batch_id == batch.id, TrainingBatchEnrollment.student_id == student_id,
        TrainingBatchEnrollment.status.in_(["active", "completed"])).first()
    student = db.get(User, student_id)
    if not membership or not student: raise HTTPException(404, "Learner is not enrolled in this batch")
    progress = _progress(db, batch, student)
    if not progress["certificate_eligible"]:
        raise HTTPException(409, "Learner has not met the certificate requirements")
    existing = db.query(TrainingCertificate).filter_by(batch_id=batch.id, student_id=student.id).first()
    if existing and not existing.revoked_at: return _certificate_data(existing)
    if existing:
        existing.revoked_at = None; existing.issued_at = datetime.now(timezone.utc)
        existing.issued_by = user.id; existing.eligibility_snapshot = progress; row = existing
    else:
        row = TrainingCertificate(batch_id=batch.id, student_id=student.id, issued_by=user.id,
                                  certificate_number=f"EKT-{batch.id:05d}-{student.id:06d}-{secrets.token_hex(3).upper()}",
                                  eligibility_snapshot=progress)
        db.add(row)
    membership.status = "completed"; membership.completed_at = membership.completed_at or datetime.now(timezone.utc)
    db.commit(); db.refresh(row)
    return _certificate_data(row)


@router.get("/analytics")
def training_analytics(db: Session = Depends(get_db),
                       user: User = Depends(require_roles(UserRole.admin, UserRole.faculty))):
    batches = _batch_query(db, user).all()
    batch_rows, learner_ids, progress_values, attendance_values, eligible = [], set(), [], [], 0
    total_memberships = completed_memberships = 0
    for batch in batches:
        memberships = db.query(TrainingBatchEnrollment).options(joinedload(TrainingBatchEnrollment.student)).filter(
            TrainingBatchEnrollment.batch_id == batch.id,
            TrainingBatchEnrollment.status.in_(["active", "completed"])).all()
        rows = [_progress(db, batch, membership.student) for membership in memberships]
        learner_ids.update(membership.student_id for membership in memberships)
        progress_values.extend(row["overall_percent"] for row in rows)
        attendance_values.extend(row["rates"]["attendance"] for row in rows
                                 if row["rates"]["attendance"] is not None)
        total_memberships += len(memberships)
        completed_memberships += sum(1 for membership in memberships if membership.status == "completed")
        eligible += sum(1 for row in rows if row["certificate_eligible"])
        recorded_attendance = [row["rates"]["attendance"] for row in rows
                               if row["rates"]["attendance"] is not None]
        batch_rows.append({**_batch_data(db, batch),
                           "average_progress": round(sum(row["overall_percent"] for row in rows) / len(rows)) if rows else 0,
                           "average_attendance": round(sum(recorded_attendance) / len(recorded_attendance))
                                                 if recorded_attendance else None,
                           "eligible_certificates": sum(1 for row in rows if row["certificate_eligible"])})
    statuses = {status: sum(1 for batch in batches if batch.status == status)
                for status in ("planned", "active", "completed", "archived")}
    capacity = sum(batch.capacity for batch in batches)
    return {"batch_count": len(batches), "statuses": statuses, "unique_learners": len(learner_ids),
            "average_progress": round(sum(progress_values) / len(progress_values)) if progress_values else 0,
            "average_attendance": round(sum(attendance_values) / len(attendance_values)) if attendance_values else None,
            "capacity_utilization": round(100 * total_memberships / capacity) if capacity else 0,
            "completion_percent": round(100 * completed_memberships / total_memberships) if total_memberships else 0,
            "eligible_certificates": eligible, "batches": batch_rows}
