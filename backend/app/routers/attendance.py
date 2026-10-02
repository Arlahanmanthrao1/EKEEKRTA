from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response
from sqlalchemy.orm import Session
import uuid
from datetime import datetime, timezone

from app.database import get_db
from app.models.attendance import ClassSession, Attendance
from app.models.user import User, UserRole
from app.models.course import Course, Enrollment
from app.models.institution import InstitutionType
from app.models.training import TrainingBatch, TrainingBatchEnrollment
from app.schemas.attendance import (
    SessionEvent,
    AttendanceOut,
    ClassSessionCreate,
    ClassSessionOut,
    FullscreenUpdate,
)
from app.core.deps import get_current_user, require_roles
from app.integrations.erp_client import (deliver_event_ids, enqueue_attendance_to_erp,
                                         sync_attendance_to_erp)
from app.config import settings
from app.integrations.video import meeting_connection

from app.core.access import course_access, courses_query, student_access, tenant
from app.core.session_lock import lock_course_sessions

router = APIRouter(prefix="/attendance", tags=["attendance"])

def _minutes_between(started_at: datetime, ended_at: datetime) -> float:
    """Handle SQLite's naive datetimes and timezone-aware API timestamps."""
    if started_at.tzinfo is None and ended_at.tzinfo is not None:
        ended_at = ended_at.replace(tzinfo=None)
    elif started_at.tzinfo is not None and ended_at.tzinfo is None:
        ended_at = ended_at.replace(tzinfo=timezone.utc)
    return (ended_at - started_at).total_seconds() / 60


def _get_session_or_404(session_id: int, db: Session) -> ClassSession:
    session = db.query(ClassSession).filter(ClassSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


def _require_course_manager(session: ClassSession, current_user: User, db: Session) -> None:
    course_access(db, current_user, session.course_id, manage=True)
    if session.training_batch_id and current_user.role == UserRole.faculty:
        batch = db.get(TrainingBatch, session.training_batch_id)
        if not batch or batch.trainer_id != current_user.id:
            raise HTTPException(403, "Only the assigned trainer can manage this batch class")


def _training_batch(db: Session, user: User, course_id: int, batch_id: int | None,
                    manage: bool = False) -> TrainingBatch | None:
    """Resolve an explicit batch for training institutions; universities stay course-based."""
    if not user.institution or user.institution.institution_type != InstitutionType.training_institution.value:
        if batch_id is not None:
            raise HTTPException(422, "Training batches are available only to training institutions")
        return None
    if batch_id is None:
        raise HTTPException(422, "Select a training batch")
    query = db.query(TrainingBatch).filter(
        TrainingBatch.id == batch_id,
        TrainingBatch.course_id == course_id,
        TrainingBatch.institution_id == tenant(user),
    )
    if user.role == UserRole.faculty:
        query = query.filter(TrainingBatch.trainer_id == user.id)
    elif user.role == UserRole.student:
        query = query.join(TrainingBatchEnrollment).filter(
            TrainingBatchEnrollment.student_id == user.id,
            TrainingBatchEnrollment.status.in_(["active", "completed"]),
        )
    batch = query.first()
    if not batch:
        raise HTTPException(404, "Training batch not found in your access scope")
    if manage and user.role not in (UserRole.admin, UserRole.faculty):
        raise HTTPException(403, "You cannot manage this training batch")
    return batch


@router.post("/sessions", response_model=ClassSessionOut, status_code=201)
def schedule_session(
    session_in: ClassSessionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.faculty, UserRole.admin)),
):
    course_access(db, current_user, session_in.course_id, manage=True)
    batch = _training_batch(db, current_user, session_in.course_id,
                            session_in.training_batch_id, manage=True)
    lock_course_sessions(db, session_in.course_id)

    active_session = (
        db.query(ClassSession)
        .filter(ClassSession.course_id == session_in.course_id,
                ClassSession.training_batch_id == (batch.id if batch else None),
                ClassSession.ended_at.is_(None))
        .order_by(ClassSession.scheduled_at.desc())
        .first()
    )
    if active_session:
        return active_session

    room_id = f"lms-{uuid.uuid4().hex[:16]}"
    session = ClassSession(course_id=session_in.course_id,
                           training_batch_id=batch.id if batch else None,
                           jitsi_room_id=room_id)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@router.get("/sessions/{course_id}", response_model=list[ClassSessionOut])
def list_sessions(
    course_id: int,
    include_ended: bool = False,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    course_access(db, _, course_id)
    query = db.query(ClassSession).filter(ClassSession.course_id == course_id)
    if _.institution and _.institution.institution_type == InstitutionType.training_institution.value:
        batch_ids = db.query(TrainingBatch.id).filter(TrainingBatch.institution_id == tenant(_), TrainingBatch.course_id == course_id)
        if _.role == UserRole.faculty:
            batch_ids = batch_ids.filter(TrainingBatch.trainer_id == _.id)
        elif _.role == UserRole.student:
            batch_ids = batch_ids.join(TrainingBatchEnrollment).filter(
                TrainingBatchEnrollment.student_id == _.id,
                TrainingBatchEnrollment.status.in_(["active", "completed"]),
            )
        query = query.filter(ClassSession.training_batch_id.in_(batch_ids))
    if not include_ended:
        query = query.filter(ClassSession.ended_at.is_(None))
    return query.order_by(ClassSession.scheduled_at.desc()).limit(200).all()


@router.get("/sessions/detail/{session_id}", response_model=ClassSessionOut)
def get_session_detail(session_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Used by the classroom page to poll the current fullscreen_required
    state while a class is in progress - a 3-segment path ("detail" is
    literal) so it can't collide with /sessions/{course_id} above."""
    session = _get_session_or_404(session_id, db)
    course_access(db, _, session.course_id)
    if session.training_batch_id:
        _training_batch(db, _, session.course_id, session.training_batch_id)
    return session


@router.post("/sessions/{session_id}/connection")
def get_meeting_connection(
    session_id: int,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mint a room-scoped token only after checking server-side membership."""
    session = _get_session_or_404(session_id, db)
    course = course_access(db, current_user, session.course_id)
    batch = _training_batch(db, current_user, course.id, session.training_batch_id) if session.training_batch_id else None
    moderator = current_user.role == UserRole.admin or (
        current_user.role == UserRole.faculty and
        ((batch and batch.trainer_id == current_user.id) or (not batch and course.faculty_id == current_user.id))
    )
    enrolled = current_user.role == UserRole.student and (
        (batch is not None) or db.query(Enrollment).filter(
            Enrollment.course_id == course.id, Enrollment.student_id == current_user.id
        ).first() is not None
    )
    if not moderator and not enrolled:
        raise HTTPException(403, "You are not authorized to join this class")
    if session.ended_at is not None:
        raise HTTPException(409, "Class has ended")
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return meeting_connection(session, current_user, moderator)


@router.patch("/sessions/{session_id}/fullscreen", response_model=ClassSessionOut)
def set_fullscreen_required(
    session_id: int,
    payload: FullscreenUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.faculty, UserRole.admin)),
):
    """Faculty toggles whether students in this session are held in
    fullscreen. Per the feature spec: students get pushed into fullscreen
    on join, faculty controls when they're released."""
    session = _get_session_or_404(session_id, db)
    _require_course_manager(session, current_user, db)
    if session.ended_at is not None:
        raise HTTPException(status_code=409, detail="Class has already ended")
    session.fullscreen_required = payload.fullscreen_required
    db.commit()
    db.refresh(session)
    return session


@router.patch("/sessions/{session_id}/end", response_model=ClassSessionOut)
def end_session(
    session_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.faculty, UserRole.admin)),
):
    """End a class durably and close every still-open attendance interval."""
    session = _get_session_or_404(session_id, db)
    _require_course_manager(session, current_user, db)
    if session.ended_at is not None:
        return session

    ended_at = datetime.now(timezone.utc)
    session.ended_at = ended_at
    records = db.query(Attendance).filter(Attendance.session_id == session.id).all()
    by_student = {record.student_id: record for record in records}
    enrolled_student_ids = [student_id for (student_id,) in db.query(Enrollment.student_id).filter(
        Enrollment.course_id == session.course_id).all()]
    # A learner who never joined must still receive a definitive absent record.
    # Without it, downstream ERP reports and parent alerts would silently omit
    # the most important absence case.
    for student_id in enrolled_student_ids:
        if student_id not in by_student:
            record = Attendance(session_id=session.id, student_id=student_id,
                                duration_minutes=0.0, present=False)
            db.add(record)
            records.append(record)
            by_student[student_id] = record

    for record in records:
        if record.last_joined_at is not None:
            elapsed_minutes = _minutes_between(record.last_joined_at, ended_at)
            if 0 < elapsed_minutes < 24 * 60:
                record.duration_minutes = (record.duration_minutes or 0) + elapsed_minutes
            record.last_joined_at = None
        record.present = (record.duration_minutes or 0) >= settings.minimum_attendance_minutes

    db.commit()
    db.refresh(session)

    course = db.query(Course).filter(Course.id == session.course_id).first()
    event_ids = []
    for record in records:
        student = db.query(User).filter(User.id == record.student_id).first()
        if student and course:
            event = enqueue_attendance_to_erp(db, record, student, course, session, commit=False)
            if event:
                db.flush()
                event_ids.append(event.id)
    db.commit()
    # Deliver after returning the classroom response. If the process stops, the
    # durable ERP outbox retains every event for the existing retry/dispatch API.
    background_tasks.add_task(deliver_event_ids, event_ids)
    return session


@router.post("/event")
def record_session_event(
    event: SessionEvent,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.student)),
):
    if event.student_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only record your own attendance")

    session = db.query(ClassSession).filter(ClassSession.jitsi_room_id == event.room_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    course_access(db, current_user, session.course_id)
    if session.training_batch_id:
        _training_batch(db, current_user, session.course_id, session.training_batch_id)
    if session.course_id != event.course_id:
        raise HTTPException(status_code=400, detail="Session does not belong to this course")
    enrolled = (
        db.query(Enrollment)
        .filter(Enrollment.course_id == event.course_id, Enrollment.student_id == current_user.id)
        .first()
    )
    if not enrolled:
        raise HTTPException(status_code=403, detail="You are not enrolled in this course")
    if event.event_type == "joined" and session.ended_at is not None:
        raise HTTPException(status_code=409, detail="Class has ended")

    record = (
        db.query(Attendance)
        .filter(Attendance.session_id == session.id, Attendance.student_id == event.student_id)
        .first()
    )
    if not record:
        record = Attendance(session_id=session.id, student_id=event.student_id, duration_minutes=0.0)
        db.add(record)

    if event.event_type == "joined":
        record.last_joined_at = event.timestamp
    elif event.event_type == "left":
        if record.last_joined_at is not None:
            elapsed_minutes = _minutes_between(record.last_joined_at, event.timestamp)
            if 0 < elapsed_minutes < 24 * 60:
                record.duration_minutes += elapsed_minutes
            record.last_joined_at = None
        record.present = record.duration_minutes >= settings.minimum_attendance_minutes

    db.commit()
    db.refresh(record)

    student = db.query(User).filter(User.id == event.student_id).first()
    course = db.query(Course).filter(Course.id == event.course_id).first()
    if student and course:
        sync_attendance_to_erp(db, record, student, course, session)

    return {"status": "recorded", "duration_minutes": record.duration_minutes, "present": record.present}


@router.get("/summary/{student_id}")
def get_attendance_summary(student_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    student_access(db, _, student_id)
    query = db.query(Attendance).join(ClassSession).filter(
        Attendance.student_id == student_id,
        ClassSession.course_id.in_(courses_query(db, _).with_entities(Course.id)),
    )
    if _.role == UserRole.faculty:
        query = query.filter(ClassSession.course_id.in_(db.query(Enrollment.course_id).filter(Enrollment.student_id == student_id)))
    records = query.all()
    if not records:
        return {"student_id": student_id, "total_sessions": 0, "present_count": 0, "percent": None}

    present_count = sum(1 for r in records if r.present)
    percent = round((present_count / len(records)) * 100)
    return {
        "student_id": student_id,
        "total_sessions": len(records),
        "present_count": present_count,
        "percent": percent,
    }


@router.get("/{course_id}/{student_id}", response_model=list[AttendanceOut])
def get_student_attendance(course_id: int, student_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    course_access(db, _, course_id)
    student_access(db, _, student_id)
    if _.role == UserRole.faculty and not db.query(Enrollment).filter(Enrollment.course_id == course_id, Enrollment.student_id == student_id).first():
        raise HTTPException(404, "Student is not enrolled in this course")
    return (
        db.query(Attendance)
        .join(ClassSession)
        .filter(ClassSession.course_id == course_id, Attendance.student_id == student_id)
        .all()
    )
