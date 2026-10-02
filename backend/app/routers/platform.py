from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.deps import require_roles
from app.core.tenant_deletion import delete_institution_records, remove_private_recording_files
from app.database import get_db
from app.models.course import Course
from app.models.institution import Institution, InstitutionStatus, InstitutionType
from app.models.platform import PlatformAuditLog
from app.models.user import User, UserRole
from app.schemas.platform import (
    PlatformAuditOut,
    PlatformInstitutionDeleteOut,
    PlatformInstitutionDeleteRequest,
    PlatformInstitutionOut,
    PlatformInstitutionStatusUpdate,
    PlatformSummaryOut,
)

router = APIRouter(prefix="/platform", tags=["platform operations"])
operator_only = require_roles(UserRole.platform_admin)


def _institution_view(db: Session, institution: Institution) -> PlatformInstitutionOut:
    administrators = db.query(User).filter(
        User.institution_id == institution.id,
        User.role == UserRole.admin,
    ).order_by(User.created_at.asc(), User.id.asc()).all()
    return PlatformInstitutionOut(
        id=institution.id,
        name=institution.name,
        email=institution.email,
        email_domain=institution.email_domain,
        logo_url=institution.logo_url,
        address=institution.address,
        institution_type=institution.institution_type,
        status=institution.status,
        status_reason=institution.status_reason,
        created_at=institution.created_at,
        reviewed_at=institution.reviewed_at,
        user_count=db.query(User).filter(User.institution_id == institution.id).count(),
        course_count=db.query(Course).filter(Course.institution_id == institution.id).count(),
        administrator_count=len(administrators),
        primary_administrator_name=administrators[0].name if administrators else None,
        primary_administrator_email=administrators[0].email if administrators else None,
    )


@router.get("/summary", response_model=PlatformSummaryOut)
def platform_summary(db: Session = Depends(get_db), _operator: User = Depends(operator_only)):
    status_counts = dict(db.query(Institution.status, func.count(Institution.id)).group_by(Institution.status).all())
    type_counts = dict(db.query(Institution.institution_type, func.count(Institution.id)).group_by(Institution.institution_type).all())
    return PlatformSummaryOut(
        institutions_total=db.query(Institution).count(),
        pending=status_counts.get(InstitutionStatus.pending.value, 0),
        active=status_counts.get(InstitutionStatus.active.value, 0),
        suspended=status_counts.get(InstitutionStatus.suspended.value, 0),
        rejected=status_counts.get(InstitutionStatus.rejected.value, 0),
        universities=type_counts.get(InstitutionType.university.value, 0),
        training_institutions=type_counts.get(InstitutionType.training_institution.value, 0),
        institution_users=db.query(User).filter(User.institution_id.is_not(None)).count(),
        courses=db.query(Course).count(),
    )


@router.get("/institutions", response_model=list[PlatformInstitutionOut])
def list_institutions(
    status_filter: str | None = Query(default=None, alias="status"),
    institution_type: str | None = None,
    search: str | None = None,
    db: Session = Depends(get_db),
    _operator: User = Depends(operator_only),
):
    valid_statuses = {entry.value for entry in InstitutionStatus}
    valid_types = {entry.value for entry in InstitutionType}
    if status_filter and status_filter not in valid_statuses:
        raise HTTPException(422, "Unknown institution status")
    if institution_type and institution_type not in valid_types:
        raise HTTPException(422, "Unknown institution type")
    query = db.query(Institution)
    if status_filter:
        query = query.filter(Institution.status == status_filter)
    if institution_type:
        query = query.filter(Institution.institution_type == institution_type)
    if search and search.strip():
        term = f"%{search.strip().lower()}%"
        query = query.filter(or_(
            func.lower(Institution.name).like(term),
            func.lower(Institution.email_domain).like(term),
            func.lower(Institution.email).like(term),
        ))
    institutions = query.order_by(Institution.created_at.desc(), Institution.id.desc()).all()
    return [_institution_view(db, institution) for institution in institutions]


@router.get("/institutions/{institution_id}", response_model=PlatformInstitutionOut)
def institution_details(institution_id: int, db: Session = Depends(get_db),
                        _operator: User = Depends(operator_only)):
    institution = db.get(Institution, institution_id)
    if not institution:
        raise HTTPException(404, "Institution not found")
    return _institution_view(db, institution)


@router.patch("/institutions/{institution_id}/status", response_model=PlatformInstitutionOut)
def update_institution_status(
    institution_id: int,
    payload: PlatformInstitutionStatusUpdate,
    db: Session = Depends(get_db),
    operator: User = Depends(operator_only),
):
    institution = db.get(Institution, institution_id)
    if not institution:
        raise HTTPException(404, "Institution not found")
    if payload.status in {InstitutionStatus.suspended.value, InstitutionStatus.rejected.value} and not payload.reason:
        raise HTTPException(422, "Give a reason before suspending or rejecting an institution")

    previous_status = institution.status
    institution.status = payload.status
    institution.status_reason = payload.reason or None
    institution.reviewed_at = datetime.now(timezone.utc)
    institution.reviewed_by = operator.id
    if payload.status in {InstitutionStatus.suspended.value, InstitutionStatus.rejected.value}:
        db.query(User).filter(User.institution_id == institution.id).update(
            {User.session_version: User.session_version + 1}, synchronize_session=False
        )
    db.add(PlatformAuditLog(
        operator_id=operator.id,
        institution_id=institution.id,
        event_type="institution_status_changed",
        details={
            "previous_status": previous_status,
            "new_status": payload.status,
            "reason": payload.reason or None,
        },
    ))
    db.commit()
    db.refresh(institution)
    return _institution_view(db, institution)


@router.delete("/institutions/{institution_id}", response_model=PlatformInstitutionDeleteOut)
def delete_institution(
    institution_id: int,
    payload: PlatformInstitutionDeleteRequest,
    db: Session = Depends(get_db),
    operator: User = Depends(operator_only),
):
    institution = db.get(Institution, institution_id)
    if not institution:
        raise HTTPException(404, "Institution not found")
    if institution.status not in {InstitutionStatus.suspended.value, InstitutionStatus.rejected.value}:
        raise HTTPException(409, "Suspend or reject the institution before permanently deleting it")
    if payload.confirmation_name != institution.name:
        raise HTTPException(422, "Institution name confirmation does not match")

    snapshot = {
        "institution_id": institution.id,
        "institution_name": institution.name,
        "institution_type": institution.institution_type,
        "email_domain": institution.email_domain,
        "previous_status": institution.status,
    }
    try:
        deleted = delete_institution_records(db, institution)
        db.add(PlatformAuditLog(
            operator_id=operator.id,
            institution_id=None,
            event_type="institution_permanently_deleted",
            details={
                **snapshot,
                "reason": payload.reason,
                "deleted_user_count": deleted["user_count"],
                "deleted_course_count": deleted["course_count"],
            },
        ))
        db.commit()
    except Exception:
        db.rollback()
        raise
    remove_private_recording_files(deleted["recording_keys"])
    return PlatformInstitutionDeleteOut(
        institution_id=snapshot["institution_id"],
        institution_name=snapshot["institution_name"],
        deleted_user_count=deleted["user_count"],
        deleted_course_count=deleted["course_count"],
    )


@router.get("/audit", response_model=list[PlatformAuditOut])
def audit_log(limit: int = Query(default=100, ge=1, le=250), db: Session = Depends(get_db),
              _operator: User = Depends(operator_only)):
    records = db.query(PlatformAuditLog).order_by(PlatformAuditLog.created_at.desc(), PlatformAuditLog.id.desc()).limit(limit).all()
    operator_ids = {record.operator_id for record in records}
    institution_ids = {record.institution_id for record in records if record.institution_id}
    operators = {user.id: user for user in db.query(User).filter(User.id.in_(operator_ids)).all()} if operator_ids else {}
    institutions = {entry.id: entry for entry in db.query(Institution).filter(Institution.id.in_(institution_ids)).all()} if institution_ids else {}
    return [PlatformAuditOut(
        id=record.id,
        operator_id=record.operator_id,
        operator_name=operators[record.operator_id].name if record.operator_id in operators else "Former operator",
        operator_email=operators[record.operator_id].email if record.operator_id in operators else "Unavailable",
        institution_id=record.institution_id,
        institution_name=institutions[record.institution_id].name if record.institution_id in institutions else None,
        event_type=record.event_type,
        details=record.details or {},
        created_at=record.created_at,
    ) for record in records]
