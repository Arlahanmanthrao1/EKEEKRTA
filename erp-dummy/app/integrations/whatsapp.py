import re
from datetime import datetime, timezone

import httpx
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models import AttendanceRecord, Student, WhatsAppNotification


def configuration_status() -> dict:
    version = settings.whatsapp_graph_api_version.strip()
    phone_number_id = settings.whatsapp_phone_number_id.strip()
    token = settings.whatsapp_access_token.get_secret_value().strip()
    template = settings.whatsapp_absence_template_name.strip()
    language = settings.whatsapp_template_language.strip()
    configured = bool(
        re.fullmatch(r"v\d+\.\d+", version)
        and phone_number_id.isdigit()
        and len(token) >= 20
        and template
        and language
    )
    return {
        "enabled": settings.whatsapp_notifications_enabled,
        "configured": configured,
        "template_name": template or None,
        "language": language or None,
    }


def notification_payload(row: WhatsAppNotification) -> dict:
    return {
        "id": row.id,
        "attendance_record_id": row.attendance_record_id,
        "attendance_source": row.attendance_source,
        "student_institutional_id": row.student_institutional_id,
        "parent_phone_last4": row.parent_phone_last4,
        "status": row.status,
        "attempts": row.attempts,
        "provider_message_id": row.provider_message_id,
        "last_error": row.last_error,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "sent_at": row.sent_at,
    }


def _notification_row(db: Session, attendance: AttendanceRecord) -> WhatsAppNotification:
    row = db.query(WhatsAppNotification).filter(
        WhatsAppNotification.attendance_record_id == attendance.id,
        WhatsAppNotification.notification_type == "class_absence",
    ).first()
    if row:
        return row
    row = WhatsAppNotification(
        institution_external_id=attendance.institution_external_id,
        attendance_record_id=attendance.id,
        notification_type="class_absence",
        attendance_source=attendance.source,
        student_institutional_id=attendance.student_institutional_id,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        row = db.query(WhatsAppNotification).filter(
            WhatsAppNotification.attendance_record_id == attendance.id,
            WhatsAppNotification.notification_type == "class_absence",
        ).one()
    else:
        db.refresh(row)
    return row


def _error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
        message = body.get("error", {}).get("message")
        if message:
            return str(message)[:500]
    except (ValueError, TypeError, AttributeError):
        pass
    return f"Meta WhatsApp API returned HTTP {response.status_code}"


def send_absence_notification(db: Session, attendance: AttendanceRecord,
                              student: Student) -> dict:
    """Send one approved-template alert after the class has definitively ended."""
    if attendance.session_ended_at is None:
        return {"status": "not_final"}
    if attendance.present:
        return {"status": "not_absent"}

    row = _notification_row(db, attendance)
    if row.status == "sent":
        return notification_payload(row)

    row.attendance_source = attendance.source
    row.parent_phone_last4 = student.parent_phone[-4:] if student.parent_phone else None
    if not student.parent_phone:
        row.status = "missing_parent_phone"
        row.last_error = "Add a parent or guardian WhatsApp number to the ERP student profile"
        db.commit()
        return notification_payload(row)
    if not student.parent_whatsapp_opt_in:
        row.status = "opt_in_required"
        row.last_error = "Parent or guardian WhatsApp consent is not recorded"
        db.commit()
        return notification_payload(row)

    config = configuration_status()
    if not config["enabled"]:
        row.status = "disabled"
        row.last_error = "WhatsApp absence notifications are disabled"
        db.commit()
        return notification_payload(row)
    if not config["configured"]:
        row.status = "configuration_required"
        row.last_error = "Complete the official Meta WhatsApp Cloud API configuration"
        db.commit()
        return notification_payload(row)
    if row.attempts >= settings.whatsapp_max_attempts:
        row.status = "retry_limit_reached"
        row.last_error = "Notification retry limit reached"
        db.commit()
        return notification_payload(row)

    started = attendance.session_started_at
    class_time = started.strftime("%d %b %Y, %I:%M %p") if started else "the scheduled class"
    parameters = [
        student.name,
        f"{attendance.course_code} - {attendance.course_name}",
        class_time,
        f"{attendance.duration_minutes:.0f}",
        settings.erp_name,
    ]
    request_body = {
        "messaging_product": "whatsapp",
        "to": student.parent_phone.removeprefix("+"),
        "type": "template",
        "template": {
            "name": settings.whatsapp_absence_template_name.strip(),
            "language": {"code": settings.whatsapp_template_language.strip()},
            "components": [{
                "type": "body",
                "parameters": [{"type": "text", "text": value[:1000]} for value in parameters],
            }],
        },
    }
    endpoint = (
        f"https://graph.facebook.com/{settings.whatsapp_graph_api_version.strip()}/"
        f"{settings.whatsapp_phone_number_id.strip()}/messages"
    )
    row.status = "sending"
    row.attempts += 1
    row.last_error = None
    db.commit()
    try:
        response = httpx.post(
            endpoint,
            headers={"Authorization": f"Bearer {settings.whatsapp_access_token.get_secret_value().strip()}",
                     "Content-Type": "application/json"},
            json=request_body,
            timeout=settings.whatsapp_request_timeout_seconds,
        )
        if response.status_code not in {200, 201}:
            row.status = "failed"
            row.last_error = _error_message(response)
        else:
            body = response.json()
            message_id = ((body.get("messages") or [{}])[0]).get("id")
            if not message_id:
                row.status = "failed"
                row.last_error = "Meta WhatsApp API did not return a message ID"
            else:
                row.status = "sent"
                row.provider_message_id = str(message_id)[:240]
                row.sent_at = datetime.now(timezone.utc)
    except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
        row.status = "failed"
        row.last_error = f"WhatsApp delivery failed: {type(exc).__name__}"[:500]
    db.commit()
    db.refresh(row)
    return notification_payload(row)
