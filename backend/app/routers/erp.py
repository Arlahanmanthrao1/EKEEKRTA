from datetime import datetime, timedelta, timezone
import hashlib
import json
import secrets

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import ValidationError
from jose import JWTError
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.access import tenant
from app.core.deps import require_roles
from app.core.secret_box import encrypt_secret
from app.core.security import create_access_token, decode_access_token, hash_password
from app.core.cohorts import enroll_matching_compulsory_courses
from app.database import get_db
from app.integrations.erp_client import (
    attendance_payload,
    course_payload,
    deliver_event,
    enqueue_event,
    fetch_erp_students,
    fetch_erp_users,
    test_erp_connection,
)
from app.models.attendance import Attendance, ClassSession
from app.models.course import Course
from app.models.erp import ERPIntegration, ERPSyncEvent
from app.models.institution import Department, Institution
from app.models.user import User, UserRole
from app.schemas.erp import (
    ERPConfigurationIn,
    ERPConfigurationOut,
    ERPStudentExport,
    ERPStudentImportResult,
    ERPUserExport,
    ERPUserImportConfirmIn,
    ERPUserImportPreviewOut,
    ERPUserImportResult,
    ERPSyncEventOut,
    ERPSyncResult,
)

router = APIRouter(prefix="/erp", tags=["erp"])


def _configuration(row: ERPIntegration | None) -> ERPConfigurationOut:
    if row is None:
        return ERPConfigurationOut(configured=False)
    return ERPConfigurationOut(
        configured=True, base_url=row.base_url, external_institution_id=row.external_institution_id,
        token_configured=bool(row.encrypted_api_token), enabled=row.enabled,
        sync_students=row.sync_students, sync_courses=row.sync_courses,
        sync_attendance=row.sync_attendance, last_tested_at=row.last_tested_at,
        last_test_success=row.last_test_success, last_test_message=row.last_test_message,
    )


@router.get("/configuration", response_model=ERPConfigurationOut)
def get_configuration(db: Session = Depends(get_db), admin: User = Depends(require_roles(UserRole.admin))):
    return _configuration(db.query(ERPIntegration).filter(ERPIntegration.institution_id == tenant(admin)).first())


@router.put("/configuration", response_model=ERPConfigurationOut)
def save_configuration(payload: ERPConfigurationIn, db: Session = Depends(get_db),
                       admin: User = Depends(require_roles(UserRole.admin))):
    institution_id = tenant(admin)
    row = db.query(ERPIntegration).filter(ERPIntegration.institution_id == institution_id).first()
    if row is None and not payload.api_token:
        raise HTTPException(422, "Enter the ERP API token when creating the connection")
    if row is None:
        row = ERPIntegration(institution_id=institution_id, base_url=str(payload.base_url),
                             encrypted_api_token=encrypt_secret(payload.api_token or ""))
        db.add(row)
    row.base_url = str(payload.base_url).rstrip("/")
    row.external_institution_id = payload.external_institution_id
    row.enabled = payload.enabled
    row.sync_students = payload.sync_students
    row.sync_courses = payload.sync_courses
    row.sync_attendance = payload.sync_attendance
    if payload.api_token:
        row.encrypted_api_token = encrypt_secret(payload.api_token)
    db.commit()
    db.refresh(row)
    return _configuration(row)


def _row_or_404(db: Session, institution_id: int) -> ERPIntegration:
    row = db.query(ERPIntegration).filter(ERPIntegration.institution_id == institution_id).first()
    if not row:
        raise HTTPException(404, "Configure the ERP connection first")
    return row


@router.post("/test", response_model=ERPConfigurationOut)
def test_connection(db: Session = Depends(get_db), admin: User = Depends(require_roles(UserRole.admin))):
    row = _row_or_404(db, tenant(admin))
    success, message = test_erp_connection(row)
    row.last_tested_at = datetime.now(timezone.utc)
    row.last_test_success = success
    row.last_test_message = message
    db.commit()
    db.refresh(row)
    return _configuration(row)


def _import_students(db: Session, admin: User, integration: ERPIntegration) -> ERPStudentImportResult:
    try:
        export = ERPStudentExport.model_validate(fetch_erp_students(integration))
    except (httpx.HTTPError, ValueError, ValidationError) as exc:
        db.rollback()
        raise HTTPException(502, f"Could not read valid student data from the ERP: {str(exc)[:300]}") from None

    expected = (integration.external_institution_id or "").strip()
    if expected and export.institution_id != expected:
        raise HTTPException(409, "ERP institution ID does not match this EKEEKRTA connection")

    institution = db.get(Institution, tenant(admin))
    imported = updated = skipped = 0
    for record in export.students:
        email = str(record.email).lower()
        if email.rsplit("@", 1)[-1] != institution.email_domain.lower() or len(record.institutional_id.encode("utf-8")) > 72:
            skipped += 1
            continue
        student = db.query(User).filter(
            User.institution_id == institution.id,
            func.lower(User.institutional_id) == record.institutional_id.lower(),
        ).first()
        if student and student.role != UserRole.student:
            skipped += 1
            continue
        email_owner = db.query(User).filter(func.lower(User.email) == email).first()
        if email_owner and (student is None or email_owner.id != student.id):
            skipped += 1
            continue
        department = db.query(Department).filter(
            Department.institution_id == institution.id,
            func.lower(Department.name) == record.department.lower(),
        ).first()
        if department is None:
            department = Department(institution_id=institution.id, name=record.department)
            db.add(department)
            db.flush()
        if student is None:
            student = User(
                institution_id=institution.id,
                institutional_id=record.institutional_id,
                role=UserRole.student,
                hashed_password=hash_password(record.institutional_id),
                must_change_password=True,
                erp_password_initialized=True,
                name=record.name,
                email=email,
            )
            db.add(student)
            db.flush()
            imported += 1
        else:
            updated += 1
            if not student.erp_password_initialized:
                student.hashed_password = hash_password(record.institutional_id)
                student.must_change_password = True
                student.erp_password_initialized = True
        student.name = record.name
        student.email = email
        student.department = department.name
        student.program = record.program
        student.batch = record.batch
        student.semester_number = record.semester_number
        student.section = record.section
        enroll_matching_compulsory_courses(db, student)
    db.commit()
    return ERPStudentImportResult(
        imported=imported,
        updated=updated,
        skipped=skipped,
        message=f"Imported {imported}, updated {updated}, skipped {skipped} ERP student records",
    )


@router.post("/import-students", response_model=ERPStudentImportResult)
def import_students(db: Session = Depends(get_db), admin: User = Depends(require_roles(UserRole.admin))):
    integration = _row_or_404(db, tenant(admin))
    if not integration.enabled or not integration.sync_students:
        raise HTTPException(409, "Enable the ERP connection and student import before synchronizing")
    return _import_students(db, admin, integration)


def _user_export(integration: ERPIntegration) -> ERPUserExport:
    try:
        return ERPUserExport.model_validate(fetch_erp_users(integration))
    except (httpx.HTTPError, ValueError, ValidationError) as exc:
        raise HTTPException(502, f"Could not read valid user data from the ERP: {str(exc)[:300]}") from None


def _require_matching_erp(export: ERPUserExport, integration: ERPIntegration):
    expected = (integration.external_institution_id or "").strip()
    if expected and export.institution_id != expected:
        raise HTTPException(409, "ERP institution ID does not match this EKEEKRTA connection")


def _user_import_plan(db: Session, institution: Institution, export: ERPUserExport) -> list[dict]:
    plan = []
    seen_ids, seen_emails = set(), set()
    for row, record in enumerate(export.users, start=1):
        data = record.model_dump(mode="json")
        data["email"] = str(record.email).lower()
        identity_key, email_key = record.institutional_id.casefold(), data["email"].casefold()
        action, reason = "create", None
        existing = db.query(User).filter(
            User.institution_id == institution.id,
            func.lower(User.institutional_id) == record.institutional_id.lower(),
        ).first()
        email_owner = db.query(User).filter(func.lower(User.email) == data["email"]).first()
        if identity_key in seen_ids:
            action, reason = "skip", "Official institution ID is duplicated in the ERP export"
        elif email_key in seen_emails:
            action, reason = "skip", "Email is duplicated in the ERP export"
        elif record.role == "admin":
            action, reason = "skip", "Administrator accounts cannot be imported from an ERP"
        elif len(record.institutional_id.encode("utf-8")) > 72:
            action, reason = "skip", "Official institution ID is too long to use as the temporary password"
        elif data["email"].rsplit("@", 1)[-1] != institution.email_domain.lower():
            action, reason = "skip", f"Email must use @{institution.email_domain}"
        elif existing and existing.role.value != record.role:
            action, reason = "skip", f"Existing {existing.role.value} role conflicts with ERP {record.role}; manual review required"
        elif email_owner and (existing is None or email_owner.id != existing.id):
            action, reason = "skip", "Email is already assigned to another account"
        elif existing:
            action = "update"
        plan.append({"row": row, "record": data, "action": action, "reason": reason})
        seen_ids.add(identity_key)
        seen_emails.add(email_key)
    return plan


def _plan_fingerprint(export: ERPUserExport, plan: list[dict]) -> str:
    value = {"institution_id": export.institution_id, "plan": plan}
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _preview_response(db: Session, admin: User, integration: ERPIntegration) -> ERPUserImportPreviewOut:
    export = _user_export(integration)
    _require_matching_erp(export, integration)
    institution = db.get(Institution, tenant(admin))
    plan = _user_import_plan(db, institution, export)
    fingerprint = _plan_fingerprint(export, plan)
    token = create_access_token({"sub": str(admin.id), "scope": "erp_user_import",
                                 "institution_id": institution.id, "fingerprint": fingerprint},
                                expires_delta=timedelta(minutes=15))
    role_counts = {role: sum(1 for item in plan if item["record"]["role"] == role and item["action"] != "skip")
                   for role in ("student", "faculty", "hod")}
    return ERPUserImportPreviewOut(
        confirmation_token=token, expires_in_minutes=15, total=len(plan),
        creates=sum(item["action"] == "create" for item in plan),
        updates=sum(item["action"] == "update" for item in plan),
        skipped=sum(item["action"] == "skip" for item in plan), role_counts=role_counts,
        records=[{"row": item["row"], "role": item["record"]["role"],
                  "institutional_id": item["record"]["institutional_id"], "name": item["record"]["name"],
                  "email": item["record"]["email"], "department": item["record"].get("department"),
                  "action": item["action"], "reason": item["reason"]} for item in plan])


@router.post("/import-users/preview", response_model=ERPUserImportPreviewOut)
def preview_user_import(db: Session = Depends(get_db), admin: User = Depends(require_roles(UserRole.admin))):
    integration = _row_or_404(db, tenant(admin))
    if not integration.enabled or not integration.sync_students:
        raise HTTPException(409, "Enable the ERP connection and user import before previewing")
    return _preview_response(db, admin, integration)


@router.post("/import-users/confirm", response_model=ERPUserImportResult)
def confirm_user_import(payload: ERPUserImportConfirmIn, db: Session = Depends(get_db),
                        admin: User = Depends(require_roles(UserRole.admin))):
    try:
        claims = decode_access_token(payload.confirmation_token)
    except JWTError:
        raise HTTPException(422, "The ERP import preview expired or is invalid; create a new preview") from None
    if (claims.get("scope") != "erp_user_import" or claims.get("sub") != str(admin.id)
            or claims.get("institution_id") != tenant(admin)):
        raise HTTPException(403, "This ERP import preview does not belong to this administrator and institution")
    integration = _row_or_404(db, tenant(admin))
    if not integration.enabled or not integration.sync_students:
        raise HTTPException(409, "ERP user import is no longer enabled")
    export = _user_export(integration)
    _require_matching_erp(export, integration)
    institution = db.get(Institution, tenant(admin))
    plan = _user_import_plan(db, institution, export)
    if not secrets.compare_digest(claims.get("fingerprint", ""), _plan_fingerprint(export, plan)):
        raise HTTPException(409, "ERP or EKEEKRTA user data changed after preview; review a new preview")

    imported = updated = skipped = 0
    role_counts = {"student": 0, "faculty": 0, "hod": 0}
    for item in plan:
        if item["action"] == "skip":
            skipped += 1
            continue
        record = item["record"]
        account = db.query(User).filter(
            User.institution_id == institution.id,
            func.lower(User.institutional_id) == record["institutional_id"].lower(),
        ).first()
        department = db.query(Department).filter(
            Department.institution_id == institution.id,
            func.lower(Department.name) == record["department"].lower(),
        ).first()
        if department is None:
            department = Department(institution_id=institution.id, name=record["department"])
            db.add(department); db.flush()
        if account is None:
            account = User(institution_id=institution.id, institutional_id=record["institutional_id"],
                           role=UserRole(record["role"]), hashed_password=hash_password(record["institutional_id"]),
                           must_change_password=True, erp_password_initialized=True,
                           name=record["name"], email=record["email"])
            db.add(account); db.flush(); imported += 1
        else:
            updated += 1
            if not account.erp_password_initialized:
                account.hashed_password = hash_password(record["institutional_id"])
                account.must_change_password = True
                account.erp_password_initialized = True
        account.name = record["name"]
        account.email = record["email"]
        account.department = department.name
        if account.role == UserRole.student:
            for field in ("program", "batch", "semester_number", "section"):
                setattr(account, field, record[field])
            enroll_matching_compulsory_courses(db, account)
        else:
            account.program = account.batch = account.section = None
            account.semester_number = None
        role_counts[record["role"]] += 1
    db.commit()
    return ERPUserImportResult(imported=imported, updated=updated, skipped=skipped, role_counts=role_counts,
                               message=f"Imported {imported}, updated {updated}, skipped {skipped} ERP user records. New users sign in with their Official ID and must change it immediately")


@router.post("/sync", response_model=ERPSyncResult)
def full_sync(db: Session = Depends(get_db), admin: User = Depends(require_roles(UserRole.admin))):
    institution_id = tenant(admin)
    integration = _row_or_404(db, institution_id)
    if not integration.enabled:
        raise HTTPException(409, "Enable the ERP connection before synchronizing")
    institution = db.get(Institution, institution_id)
    queued = 0
    if integration.sync_courses:
        for course in db.query(Course).filter(Course.institution_id == institution_id).all():
            queued += enqueue_event(db, institution_id, "course", str(course.id), course_payload(course, institution), commit=False) is not None
    if integration.sync_attendance:
        rows = db.query(Attendance, User, Course, ClassSession).join(User, User.id == Attendance.student_id).join(
            ClassSession, ClassSession.id == Attendance.session_id).join(Course, Course.id == ClassSession.course_id).filter(
            Course.institution_id == institution_id).all()
        for record, student, course, session in rows:
            queued += enqueue_event(db, institution_id, "attendance", str(record.id),
                                    attendance_payload(record, student, course, session), commit=False) is not None
    db.commit()
    result = _dispatch(db, institution_id, queued)
    result.message = f"Outbound ERP sync: {result.synced} sent, {result.pending} waiting. User imports require a reviewed preview."
    return result


def _dispatch(db: Session, institution_id: int, queued: int = 0, limit: int = 25) -> ERPSyncResult:
    events = db.query(ERPSyncEvent).filter(ERPSyncEvent.institution_id == institution_id,
                                           ERPSyncEvent.status.in_(("pending", "failed"))).order_by(
        ERPSyncEvent.updated_at.asc()).limit(limit).all()
    synced = sum(1 for event in events if deliver_event(db, event))
    failed = len(events) - synced
    pending = db.query(ERPSyncEvent).filter(ERPSyncEvent.institution_id == institution_id,
                                            ERPSyncEvent.status.in_(("pending", "failed"))).count()
    return ERPSyncResult(queued=queued, synced=synced, failed=failed, pending=pending,
                         message="ERP sync batch completed" if events else "Nothing is waiting to synchronize")


@router.post("/dispatch", response_model=ERPSyncResult)
def dispatch_waiting(limit: int = Query(25, ge=1, le=100), db: Session = Depends(get_db),
                     admin: User = Depends(require_roles(UserRole.admin))):
    return _dispatch(db, tenant(admin), limit=limit)


@router.get("/events", response_model=list[ERPSyncEventOut])
def sync_events(limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db),
                admin: User = Depends(require_roles(UserRole.admin))):
    return db.query(ERPSyncEvent).filter(ERPSyncEvent.institution_id == tenant(admin)).order_by(
        ERPSyncEvent.updated_at.desc()).limit(limit).all()


@router.post("/events/{event_id}/retry", response_model=ERPSyncEventOut)
def retry_event(event_id: int, db: Session = Depends(get_db),
                admin: User = Depends(require_roles(UserRole.admin))):
    event = db.query(ERPSyncEvent).filter(ERPSyncEvent.id == event_id,
                                          ERPSyncEvent.institution_id == tenant(admin)).first()
    if not event:
        raise HTTPException(404, "ERP sync event not found")
    event.status = "pending"
    event.last_error = None
    db.commit()
    deliver_event(db, event)
    db.refresh(event)
    return event
