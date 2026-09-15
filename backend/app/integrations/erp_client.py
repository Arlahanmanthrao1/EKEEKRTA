"""Institution-scoped outbound ERP integration with a durable sync outbox."""

from __future__ import annotations

import ipaddress
import json
import os
from datetime import datetime, timezone
from urllib.parse import quote, urlsplit
from uuid import uuid4

import httpx
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from app.core.secret_box import decrypt_secret
from app.models.erp import ERPIntegration, ERPSyncEvent


ENDPOINTS = {"student": "students", "course": "courses", "attendance": "attendance"}
ERP_HTTP_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


def _is_allowed(integration: ERPIntegration, event_type: str) -> bool:
    return bool(integration.enabled and {
        "student": integration.sync_students,
        "course": integration.sync_courses,
        "attendance": integration.sync_attendance,
    }.get(event_type, False))


def _safe_base_url(value: str) -> str:
    parsed = urlsplit(value)
    host = (parsed.hostname or "").lower()
    local_development = not os.getenv("VERCEL") and parsed.scheme == "http" and host in {"localhost", "127.0.0.1", "::1"}
    if (parsed.scheme != "https" and not local_development) or not host or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("ERP endpoint must be a plain HTTPS base URL")
    if not local_development and (host == "localhost" or host.endswith(".localhost") or host.endswith(".local")):
        raise ValueError("ERP endpoint cannot use a local hostname")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address and not local_development and (address.is_private or address.is_loopback or address.is_link_local or address.is_reserved):
        raise ValueError("ERP endpoint cannot use a private or reserved IP address")
    return value.rstrip("/")


def _headers(integration: ERPIntegration, event_id: int | str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {decrypt_secret(integration.encrypted_api_token)}",
        "Content-Type": "application/json",
        "User-Agent": "EKEEKRTA-ERP-Connector/1.0",
        "Idempotency-Key": f"ekeekrta-{event_id}",
    }


def test_erp_connection(integration: ERPIntegration) -> tuple[bool, str]:
    try:
        response = httpx.get(f"{_safe_base_url(integration.base_url)}/api/ekeekrta/health",
                             headers=_headers(integration, f"health-{uuid4().hex}"), timeout=ERP_HTTP_TIMEOUT,
                             follow_redirects=False)
        if 200 <= response.status_code < 300:
            return True, "ERP connection verified"
        return False, f"ERP health check returned HTTP {response.status_code}"
    except (httpx.RequestError, ValueError) as exc:
        return False, str(exc)[:500]


def _fetch_erp_json(integration: ERPIntegration, path: str):
    response = httpx.get(
        f"{_safe_base_url(integration.base_url)}{path}",
        headers={"Authorization": f"Bearer {decrypt_secret(integration.encrypted_api_token)}",
                 "Accept": "application/json", "User-Agent": "EKEEKRTA-ERP-Connector/1.0"},
        timeout=ERP_HTTP_TIMEOUT,
        follow_redirects=False,
    )
    return response


def fetch_erp_users(integration: ERPIntegration) -> dict:
    """Pull role-labelled ERP identities, with a legacy student-export fallback."""
    response = _fetch_erp_json(integration, "/api/ekeekrta/users")
    if response.status_code == 404:
        legacy = _fetch_erp_json(integration, "/api/ekeekrta/students")
        legacy.raise_for_status()
        data = legacy.json()
        return {"institution_id": data.get("institution_id"),
                "users": [{"role": "student", **record} for record in data.get("students", [])]}
    response.raise_for_status()
    return response.json()


def fetch_erp_students(integration: ERPIntegration) -> dict:
    """Compatibility reader retained for existing student-only imports."""
    response = _fetch_erp_json(integration, "/api/ekeekrta/students")
    response.raise_for_status()
    return response.json()


def fetch_erp_academic_result(integration: ERPIntegration, institutional_id: str) -> dict:
    """Read one official result summary without modifying either system."""
    response = _fetch_erp_json(integration, f"/api/ekeekrta/results/{quote(institutional_id, safe='')}")
    response.raise_for_status()
    return response.json()


def enqueue_event(db: Session, institution_id: int, event_type: str, entity_key: str,
                  payload: dict, *, commit: bool = True) -> ERPSyncEvent | None:
    integration = db.query(ERPIntegration).filter(ERPIntegration.institution_id == institution_id).first()
    if not integration or not _is_allowed(integration, event_type):
        return None
    if payload.get("institution") is not None:
        payload["institution"]["external_id"] = integration.external_institution_id
    event = db.query(ERPSyncEvent).filter(
        ERPSyncEvent.institution_id == institution_id, ERPSyncEvent.event_type == event_type,
        ERPSyncEvent.entity_key == entity_key).first()
    encoded = json.dumps(payload, separators=(",", ":"), default=str)
    if event is None:
        event = ERPSyncEvent(institution_id=institution_id, event_type=event_type,
                             entity_key=entity_key, payload_json=encoded)
        db.add(event)
    else:
        event.payload_json = encoded
        event.revision += 1
        event.status = "pending"
        event.last_error = None
        event.response_code = None
        event.synced_at = None
    if commit:
        db.commit()
        db.refresh(event)
    return event


def deliver_event(db: Session, event: ERPSyncEvent) -> bool:
    integration = db.query(ERPIntegration).filter(ERPIntegration.institution_id == event.institution_id).first()
    if not integration or not _is_allowed(integration, event.event_type):
        return False
    event.attempts += 1
    try:
        response = httpx.post(f"{_safe_base_url(integration.base_url)}/api/ekeekrta/{ENDPOINTS[event.event_type]}/sync",
                              headers=_headers(integration, f"{event.id}-{event.revision}"), content=event.payload_json,
                              timeout=ERP_HTTP_TIMEOUT, follow_redirects=False)
        event.response_code = response.status_code
        if 200 <= response.status_code < 300:
            event.status = "synced"
            event.synced_at = datetime.now(timezone.utc)
            event.last_error = None
        else:
            event.status = "failed"
            event.last_error = f"ERP returned HTTP {response.status_code}"
    except (httpx.RequestError, ValueError, KeyError) as exc:
        event.status = "failed"
        event.last_error = str(exc)[:500]
    db.commit()
    return event.status == "synced"


def queue_and_deliver(db: Session, institution_id: int, event_type: str, entity_key: str, payload: dict) -> bool:
    """Best-effort delivery: ERP failures never roll back the LMS action."""
    try:
        event = enqueue_event(db, institution_id, event_type, entity_key, payload)
        return deliver_event(db, event) if event else False
    except SQLAlchemyError:
        db.rollback()
        return False


def institution_ref(institution) -> dict:
    return {"ekeekrta_id": institution.id, "name": institution.name,
            "email_domain": institution.email_domain}


def student_payload(student) -> dict:
    return {"event": "student.upsert", "institution": institution_ref(student.institution),
            "student": {"ekeekrta_id": student.id, "institutional_id": student.institutional_id,
                        "name": student.name, "email": student.email, "department": student.department,
                        "program": student.program, "batch": student.batch,
                        "semester_number": student.semester_number, "section": student.section},
            "occurred_at": datetime.now(timezone.utc).isoformat()}


def course_payload(course, institution) -> dict:
    return {"event": "course.upsert", "institution": institution_ref(institution),
            "course": {"ekeekrta_id": course.id, "code": course.code, "name": course.name,
                       "department": course.department, "course_type": course.course_type,
                       "program": course.program, "batch": course.batch,
                       "semester_number": course.semester_number, "section": course.section,
                       "enrollment_mode": course.enrollment_mode, "credits": course.credits,
                       "faculty": ({"ekeekrta_id": course.faculty.id,
                                    "institutional_id": course.faculty.institutional_id,
                                    "name": course.faculty.name, "email": course.faculty.email}
                                   if course.faculty else None)},
            "occurred_at": datetime.now(timezone.utc).isoformat()}


def attendance_payload(record, student, course, session) -> dict:
    return {"event": "attendance.upsert", "institution": institution_ref(student.institution),
            "student": {"ekeekrta_id": student.id, "institutional_id": student.institutional_id,
                        "email": student.email, "name": student.name},
            "course": {"ekeekrta_id": course.id, "code": course.code, "name": course.name},
            "class_session": {"ekeekrta_id": session.id, "scheduled_at": session.scheduled_at,
                              "ended_at": session.ended_at},
            "attendance": {"ekeekrta_id": record.id, "duration_minutes": round(record.duration_minutes, 2),
                           "present": record.present},
            "occurred_at": datetime.now(timezone.utc).isoformat()}


def sync_student_to_erp(db: Session, student) -> bool:
    return queue_and_deliver(db, student.institution_id, "student", str(student.id), student_payload(student))


def enqueue_student_to_erp(db: Session, student, *, commit: bool = True) -> ERPSyncEvent | None:
    return enqueue_event(db, student.institution_id, "student", str(student.id), student_payload(student), commit=commit)


def sync_course_to_erp(db: Session, course, institution) -> bool:
    return queue_and_deliver(db, course.institution_id, "course", str(course.id), course_payload(course, institution))


def enqueue_course_to_erp(db: Session, course, institution, *, commit: bool = True) -> ERPSyncEvent | None:
    return enqueue_event(db, course.institution_id, "course", str(course.id), course_payload(course, institution), commit=commit)


def sync_attendance_to_erp(db: Session, record, student, course, session) -> bool:
    return queue_and_deliver(db, course.institution_id, "attendance", str(record.id),
                             attendance_payload(record, student, course, session))


def enqueue_attendance_to_erp(db: Session, record, student, course, session, *, commit: bool = True) -> ERPSyncEvent | None:
    return enqueue_event(db, course.institution_id, "attendance", str(record.id),
                         attendance_payload(record, student, course, session), commit=commit)
