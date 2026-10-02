from datetime import datetime, timezone, timedelta
import uuid
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, AwareDatetime, field_validator
from sqlalchemy.orm import Session, joinedload
from app.database import get_db
from app.core.access import course_access, courses_query
from app.core.deps import require_roles
from app.core.session_lock import lock_course_sessions
from app.models.course import Course
from app.models.user import UserRole
from app.models.attendance import ClassSession
from app.models.institution import InstitutionType
from app.models.scheduled_class import ScheduledClass
from app.models.training import TrainingBatch
from app.schemas.attendance import ClassSessionOut

router = APIRouter(prefix="/schedule", tags=["scheduled classes"])
faculty = require_roles(UserRole.faculty)


class ScheduleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    course_id: int = Field(gt=0)
    training_batch_id: int | None = Field(default=None, gt=0)
    title: str = Field(min_length=1, max_length=200)
    starts_at: AwareDatetime

    @field_validator("starts_at")
    @classmethod
    def future_date(cls, value):
        value = value.astimezone(timezone.utc)
        now = datetime.now(timezone.utc)
        if not now < value <= now + timedelta(days=366):
            raise ValueError("Choose a future date within the next year")
        return value


def as_utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def plan_data(plan):
    status = "scheduled"
    if plan.cancelled_at:
        status = "cancelled"
    elif plan.session_id:
        status = "ended" if plan.session.ended_at else "live"
    return {"id": plan.id, "course_id": plan.course_id,
            "training_batch_id": plan.training_batch_id, "title": plan.title,
            "course_name": plan.course.name, "course_code": plan.course.code,
            "starts_at": as_utc(plan.starts_at), "session_id": plan.session_id, "status": status}


@router.get("")
def list_plans(response: Response, db: Session = Depends(get_db), user=Depends(faculty)):
    scope = courses_query(db, user).with_entities(Course.id)
    query = db.query(ScheduledClass).outerjoin(ClassSession, ScheduledClass.session_id == ClassSession.id).filter(
        ScheduledClass.course_id.in_(scope), ScheduledClass.cancelled_at.is_(None), ClassSession.ended_at.is_(None),
    )
    if user.institution and user.institution.institution_type == InstitutionType.training_institution.value:
        query = query.filter(ScheduledClass.training_batch_id.in_(
            db.query(TrainingBatch.id).filter(TrainingBatch.trainer_id == user.id)))
    plans = query.options(joinedload(ScheduledClass.course), joinedload(ScheduledClass.session)).order_by(
        ScheduledClass.starts_at).limit(501).all()
    if len(plans) > 500:
        raise HTTPException(422, "Too many pending classes. Cancel old plans before adding more")
    response.headers["Cache-Control"] = "no-store"
    return [plan_data(plan) for plan in plans]


@router.post("", status_code=201)
def create_plan(payload: ScheduleCreate, db: Session = Depends(get_db), user=Depends(faculty)):
    course_access(db, user, payload.course_id, manage=True)
    batch = None
    if user.institution and user.institution.institution_type == InstitutionType.training_institution.value:
        if payload.training_batch_id is None:
            raise HTTPException(422, "Select a training batch")
        batch = db.query(TrainingBatch).filter(
            TrainingBatch.id == payload.training_batch_id,
            TrainingBatch.course_id == payload.course_id,
            TrainingBatch.institution_id == user.institution_id,
            TrainingBatch.trainer_id == user.id,
        ).first()
        if not batch:
            raise HTTPException(404, "Training batch not found in your access scope")
        if batch.status in ("completed", "archived"):
            raise HTTPException(409, "Completed or archived batches cannot schedule new classes")
    elif payload.training_batch_id is not None:
        raise HTTPException(422, "Training batches are available only to training institutions")
    lock_course_sessions(db, payload.course_id)
    duplicate = db.query(ScheduledClass).filter(
        ScheduledClass.course_id == payload.course_id, ScheduledClass.starts_at == payload.starts_at,
        ScheduledClass.training_batch_id == (batch.id if batch else None),
        ScheduledClass.cancelled_at.is_(None),
    ).first()
    if duplicate:
        raise HTTPException(409, "This course already has a class at that date and time")
    plan = ScheduledClass(**payload.model_dump())
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan_data(plan)


def editable_plan(db, user, plan_id):
    plan = db.get(ScheduledClass, plan_id)
    if not plan:
        raise HTTPException(404, "Scheduled class not found")
    course_access(db, user, plan.course_id, manage=True)
    if plan.training_batch_id and user.role == UserRole.faculty:
        batch = db.get(TrainingBatch, plan.training_batch_id)
        if not batch or batch.trainer_id != user.id:
            raise HTTPException(403, "Only the assigned trainer can manage this batch class")
    lock_course_sessions(db, plan.course_id)
    db.refresh(plan)
    return plan


@router.post("/{plan_id}/start", response_model=ClassSessionOut)
def start_plan(plan_id: int, db: Session = Depends(get_db), user=Depends(faculty)):
    plan = editable_plan(db, user, plan_id)
    if plan.cancelled_at:
        raise HTTPException(409, "This scheduled class was cancelled")
    if plan.session_id:
        if plan.session.ended_at:
            raise HTTPException(409, "This class has already ended")
        return plan.session
    active = db.query(ClassSession).filter(
        ClassSession.course_id == plan.course_id,
        ClassSession.training_batch_id == plan.training_batch_id,
        ClassSession.ended_at.is_(None)).first()
    if active:
        raise HTTPException(409, "This course already has a live class. End it before starting another")
    session = ClassSession(course_id=plan.course_id, training_batch_id=plan.training_batch_id,
                           jitsi_room_id=f"lms-{uuid.uuid4().hex}",
                           scheduled_at=datetime.now(timezone.utc))
    db.add(session)
    db.flush()
    plan.session_id = session.id
    db.commit()
    db.refresh(session)
    return session


@router.post("/{plan_id}/cancel", status_code=204)
def cancel_plan(plan_id: int, db: Session = Depends(get_db), user=Depends(faculty)):
    plan = editable_plan(db, user, plan_id)
    if plan.session_id:
        raise HTTPException(409, "A started class cannot be cancelled. End it from the classroom")
    if not plan.cancelled_at:
        plan.cancelled_at = datetime.now(timezone.utc)
        db.commit()
