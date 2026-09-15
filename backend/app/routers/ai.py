import re
import secrets
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.access import course_access, courses_query, student_access, tenant, users_query
from app.core.cohorts import enroll_matching_compulsory_courses, enroll_matching_students
from app.core.deps import get_current_user
from app.core.security import hash_password
from app.database import get_db
from app.models.ai import AIAction, AIAuditLog, AICGPAGoal, AIKnowledgeSource, AILectureContent, AITrainingExample
from app.models.assignment import Assignment, Submission
from app.models.attendance import Attendance, ClassSession
from app.models.course import Course, Enrollment
from app.models.institution import Department
from app.models.erp import ERPIntegration
from app.models.programming import ProgrammingAssessment, ProgrammingSubmission
from app.models.quiz import Question, Quiz, QuizAttempt
from app.models.scheduled_class import ScheduledClass
from app.models.user import User, UserRole
from app.integrations.erp_client import enqueue_course_to_erp, fetch_erp_academic_result
from app.native_ai.intent_model import model
from app.native_ai.content_generator import ContentDraftError, build_assignment_draft, build_quiz_draft
from app.native_ai.course_retrieval import retrieve
from app.schemas.ai import (AIBulkAccountsIn, AICapabilitiesOut, AIActionOut, AICGPAPlanIn, AICommandIn,
                            AICommandOut, AICorrectionIn, AIContentDraftIn, AICourseQuestionIn,
                            AIKnowledgePublicationIn, AIKnowledgeSourceIn, AI_INTENTS)

router = APIRouter(prefix="/ai", tags=["native-ai"])

ROLE_INTENTS = {
    UserRole.student: {"student_progress", "course_question", "help"},
    UserRole.faculty: {"schedule_class", "draft_assignment", "draft_quiz", "student_progress", "create_course", "course_question", "help"},
    UserRole.hod: {"student_progress", "course_question", "help"},
    UserRole.admin: {"student_progress", "import_erp_students", "create_department", "create_course",
                     "bulk_create_accounts", "course_question", "help"},
}


def _audit(db: Session, user: User, event: str, action_id: int | None, details: dict | None = None):
    db.add(AIAuditLog(institution_id=tenant(user), user_id=user.id, action_id=action_id,
                      event_type=event, details=details or {}))


def _course_for_command(db: Session, user: User, command: str, course_id: int | None) -> Course:
    if course_id is not None:
        return course_access(db, user, course_id, manage=True)
    courses = courses_query(db, user).all()
    normalized = command.lower()
    matches = [course for course in courses if course.code.lower() in normalized or course.name.lower() in normalized]
    if len(matches) == 1:
        return matches[0]
    if not courses:
        raise HTTPException(422, "You do not manage any courses yet")
    choices = ", ".join(f"{course.name} ({course.code})" for course in courses[:8])
    if len(matches) > 1:
        raise HTTPException(422, f"More than one course matched. Choose a course: {choices}")
    raise HTTPException(422, f"Mention a course name/code or select one. Available: {choices}")


def _local_datetime(text: str, timezone_name: str, require_time: bool = True) -> datetime | None:
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        raise HTTPException(422, "Unknown timezone") from None
    now = datetime.now(zone)
    lowered = text.lower()
    date_value = None
    if "tomorrow" in lowered:
        date_value = now.date() + timedelta(days=1)
    elif "today" in lowered:
        date_value = now.date()
    else:
        iso = re.search(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b", lowered)
        local = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](20\d{2})\b", lowered)
        try:
            if iso:
                date_value = datetime(int(iso.group(1)), int(iso.group(2)), int(iso.group(3))).date()
            elif local:
                date_value = datetime(int(local.group(3)), int(local.group(2)), int(local.group(1))).date()
        except ValueError:
            raise HTTPException(422, "The date is not valid") from None
    clock = re.search(r"\b(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", lowered)
    if not clock:
        clock = re.search(r"\bat\s+(\d{1,2})(?::(\d{2}))?\b", lowered)
    if require_time and not clock:
        raise HTTPException(422, "Include a time, for example: tomorrow at 10:30 AM")
    if date_value is None:
        if not clock:
            return None
        date_value = now.date()
    hour, minute = (int(clock.group(1)), int(clock.group(2) or 0)) if clock else (23, 59)
    meridiem = clock.group(3).lower() if clock and clock.lastindex and clock.lastindex >= 3 and clock.group(3) else None
    if meridiem:
        if hour < 1 or hour > 12:
            raise HTTPException(422, "Use an hour from 1 to 12 with AM or PM")
        hour = (hour % 12) + (12 if meridiem == "pm" else 0)
    if hour > 23 or minute > 59:
        raise HTTPException(422, "The time is not valid")
    value = datetime.combine(date_value, time(hour, minute), zone)
    if value <= now:
        raise HTTPException(422, "Scheduled time must be in the future")
    return value.astimezone(timezone.utc)


def _topic(command: str, fallback: str) -> str:
    match = re.search(r"\b(?:on|about|topic)\s+(.+?)(?=\s+(?:for|in|due|with|worth|at|tomorrow|today)\b|$)", command, re.I)
    value = (match.group(1) if match else fallback).strip(" .,-")
    return value[:160] or fallback


def _department_payload(db: Session, user: User, command: str) -> tuple[dict, dict, bool, str]:
    match = re.search(r"\bdepartment\s+(?:called\s+|named\s+)?(.+)$", command, re.I)
    if not match:
        raise HTTPException(422, "Include the department name, for example: Create department Computer Science")
    name = re.sub(r"\s+", " ", match.group(1)).strip(" .,-")
    if len(name) < 2 or len(name) > 120:
        raise HTTPException(422, "Department name must contain 2 to 120 characters")
    if db.query(Department).filter(Department.institution_id == tenant(user),
                                   func.lower(Department.name) == name.lower()).first():
        raise HTTPException(409, "Department already exists")
    return {"name": name}, {"action": "Create department", "name": name}, True, "Review the department before it is created."


def _between(command: str, field: str, following: str) -> str | None:
    match = re.search(rf"\b{field}\s+(.+?)(?=\s+(?:{following})\b|$)", command, re.I)
    return re.sub(r"\s+", " ", match.group(1)).strip(" .,-") if match else None


def _course_setup_payload(db: Session, user: User, command: str) -> tuple[dict, dict, bool, str]:
    lowered = command.lower()
    code_match = re.search(r"\bcode\s+([a-z0-9_-]{2,30})\b", command, re.I)
    name_match = re.search(r"\bcourse\s+(.+?)\s+code\s+", command, re.I)
    if not code_match or not name_match:
        raise HTTPException(422, "Use: Create course <name> code <code> department <name> program <name> batch <years> semester <1-8> credits <number> faculty <email or employee ID>")
    name = re.sub(r"^(?:called|named)\s+", "", name_match.group(1).strip(), flags=re.I)[:160]
    code = code_match.group(1).upper()
    if db.query(Course).filter(Course.institution_id == tenant(user), func.lower(Course.code) == code.lower()).first():
        raise HTTPException(409, "Course code already exists")
    departments = db.query(Department).filter(Department.institution_id == tenant(user)).all()
    mentioned = [item for item in departments if item.name.lower() in lowered]
    if user.role == UserRole.faculty:
        if not user.department:
            raise HTTPException(422, "Your faculty account needs a department")
        department = user.department
        if mentioned and all(item.name.lower() != department.lower() for item in mentioned):
            raise HTTPException(403, "Create courses only in your assigned department")
        faculty_id = user.id
        faculty_name = user.name
    else:
        if len(mentioned) != 1:
            choices = ", ".join(item.name for item in departments[:10]) or "No departments created"
            raise HTTPException(422, f"Mention exactly one existing department. Available: {choices}")
        department = mentioned[0].name
        faculty = [entry for entry in users_query(db, user).filter(User.role == UserRole.faculty).all()
                   if entry.name.lower() in lowered or entry.email.lower() in lowered or
                   (entry.institutional_id and entry.institutional_id.lower() in lowered)]
        if len(faculty) != 1:
            raise HTTPException(422, "Mention exactly one faculty member by full name, email, or employee ID")
        if (faculty[0].department or "").lower() != department.lower():
            raise HTTPException(422, "The selected faculty member does not belong to that department")
        faculty_id, faculty_name = faculty[0].id, faculty[0].name
    course_type = "non_academic" if re.search(r"\bnon[ -]?academic\b", lowered) else "academic"
    following = "batch|semester|credits|section|faculty|compulsory|elective|academic|non"
    program = _between(command, "program", following)
    batch = _between(command, "batch", "semester|credits|section|faculty|compulsory|elective|academic|non")
    semester_match = re.search(r"\bsemester\s+([1-8])\b", lowered)
    section = _between(command, "section", "credits|faculty|compulsory|elective|academic|non")
    credits_match = re.search(r"\bcredits?\s+(\d+(?:\.\d+)?)\b", lowered)
    credits = float(credits_match.group(1)) if credits_match else None
    if credits is not None and not 0 < credits <= 50:
        raise HTTPException(422, "Course credits must be greater than 0 and at most 50")
    if course_type == "academic" and (not program or not batch or not semester_match):
        raise HTTPException(422, "Academic courses require program, batch and semester 1-8")
    semester_number = int(semester_match.group(1)) if semester_match else None
    enrollment_mode = "compulsory" if "compulsory" in lowered else "elective"
    payload = {"name": name, "code": code, "department": department, "course_type": course_type,
               "program": program, "batch": batch, "semester_number": semester_number,
               "section": section, "enrollment_mode": enrollment_mode, "credits": credits,
               "faculty_id": faculty_id}
    preview = {"action": "Create course", **{key: value for key, value in payload.items() if key != "faculty_id"},
               "faculty": faculty_name}
    return payload, preview, True, "Review the course structure before it is created."


def _progress_for_student(db: Session, viewer: User, student: User) -> dict:
    student_access(db, viewer, student.id)
    course_ids = [row[0] for row in courses_query(db, student).with_entities(Course.id).all()]
    if not course_ids:
        return {"student_id": student.id, "student": student.name, "courses": 0, "attendance_percent": None,
                "assignment_average": None, "quiz_average": None, "programming_average": None,
                "missing_assignments": 0, "risks": ["No course enrolments are available yet."]}
    attendance = db.query(Attendance).join(ClassSession).filter(
        Attendance.student_id == student.id, ClassSession.course_id.in_(course_ids)).all()
    attendance_percent = round(100 * sum(bool(row.present) for row in attendance) / len(attendance), 1) if attendance else None
    assignment_ids = [row[0] for row in db.query(Assignment.id).filter(Assignment.course_id.in_(course_ids)).all()]
    submissions = db.query(Submission).filter(Submission.student_id == student.id,
                                               Submission.assignment_id.in_(assignment_ids or [-1])).all()
    graded = [row for row in submissions if row.marks_obtained is not None]
    assignment_by_id = {row.id: row for row in db.query(Assignment).filter(Assignment.id.in_(assignment_ids or [-1])).all()}
    assignment_scores = [100 * row.marks_obtained / assignment_by_id[row.assignment_id].max_marks for row in graded
                         if assignment_by_id.get(row.assignment_id) and assignment_by_id[row.assignment_id].max_marks]
    quiz_ids = [row[0] for row in db.query(Quiz.id).filter(Quiz.course_id.in_(course_ids)).all()]
    quiz_scores = [row[0] for row in db.query(QuizAttempt.score).filter(
        QuizAttempt.student_id == student.id, QuizAttempt.quiz_id.in_(quiz_ids or [-1])).all()]
    assessment_ids = [row[0] for row in db.query(ProgrammingAssessment.id).filter(
        ProgrammingAssessment.course_id.in_(course_ids)).all()]
    programming_scores = [row[0] for row in db.query(ProgrammingSubmission.score).filter(
        ProgrammingSubmission.student_id == student.id,
        ProgrammingSubmission.assessment_id.in_(assessment_ids or [-1])).all()]
    submitted_ids = {row.assignment_id for row in submissions}
    risks = []
    if attendance_percent is not None and attendance_percent < 75:
        risks.append(f"Attendance is {attendance_percent}%, below the 75% target.")
    if assignment_scores and sum(assignment_scores) / len(assignment_scores) < 50:
        risks.append("Average graded assignment performance is below 50%.")
    missing = len(set(assignment_ids) - submitted_ids)
    if missing:
        risks.append(f"{missing} assignment{'s are' if missing != 1 else ' is'} not submitted.")
    return {
        "student_id": student.id, "student": student.name, "courses": len(course_ids),
        "attendance_percent": attendance_percent,
        "assignment_average": round(sum(assignment_scores) / len(assignment_scores), 1) if assignment_scores else None,
        "quiz_average": round(sum(quiz_scores) / len(quiz_scores), 1) if quiz_scores else None,
        "programming_average": round(sum(programming_scores) / len(programming_scores), 1) if programming_scores else None,
        "missing_assignments": missing, "risks": risks or ["No current threshold-based risks were found."],
    }


def _progress_payload(db: Session, user: User, command: AICommandIn) -> dict:
    if user.role == UserRole.student:
        return {"mode": "single", "records": [_progress_for_student(db, user, user)]}
    if command.student_id:
        student = student_access(db, user, command.student_id)
        return {"mode": "single", "records": [_progress_for_student(db, user, student)]}
    candidates = users_query(db, user).filter(User.role == UserRole.student).order_by(User.name).limit(200).all()
    lowered = command.command.lower()
    named = [student for student in candidates if student.name.lower() in lowered or
             (student.institutional_id and student.institutional_id.lower() in lowered)]
    selected = named if named else candidates
    records = [_progress_for_student(db, user, student) for student in selected]
    if "risk" in lowered:
        records = [record for record in records if any("No current" not in risk for risk in record["risks"])]
    return {"mode": "cohort" if not named else "single", "records": records, "record_count": len(records)}


def _build_action(db: Session, user: User, command: AICommandIn, intent: str, confidence: float) -> tuple[dict, dict, bool, str]:
    lowered = command.command.lower()
    if intent == "help":
        names = sorted(ROLE_INTENTS[user.role] - {"help"})
        return {}, {"available_actions": names}, False, "Here are the actions available for your role."
    if intent == "student_progress":
        progress = _progress_payload(db, user, command)
        return {}, progress, False, "Progress was calculated from current EKEEKRTA records."
    if intent == "create_department":
        return _department_payload(db, user, command.command)
    if intent == "create_course":
        return _course_setup_payload(db, user, command.command)
    if intent == "bulk_create_accounts":
        return ({}, {"action": "Open bulk account builder", "supported_roles": ["student", "faculty"],
                     "authentication": "Verified institution Google account",
                     "next_step": "Use the Bulk accounts panel below the command box."}, False,
                "Use the bulk account panel to paste and validate CSV records.")
    if intent == "import_erp_students":
        integration = db.query(ERPIntegration).filter(ERPIntegration.institution_id == tenant(user)).first()
        if not integration:
            raise HTTPException(409, "Configure the institution ERP connection before importing users")
        if not integration.enabled or not integration.sync_students:
            raise HTTPException(409, "Enable the ERP connection and user-directory import first")
        from app.routers.erp import _preview_response
        review = _preview_response(db, user, integration)
        payload = {"integration_id": integration.id, "confirmation_token": review.confirmation_token}
        preview = {"action": "Import reviewed student, faculty, and HOD profiles from the configured ERP",
                   "erp_base_url": integration.base_url, "passwords_or_tokens_exposed": False,
                   **review.model_dump(exclude={"confirmation_token"})}
        return payload, preview, True, "Review every ERP user decision and confirm within 15 minutes."
    course = _course_for_command(db, user, command.command, command.course_id)
    if intent == "schedule_class":
        starts_at = _local_datetime(command.command, command.timezone)
        title_match = re.search(r"\b(?:titled|called)\s+(.+?)(?=\s+(?:on|at|tomorrow|today)\b|$)", command.command, re.I)
        title = (title_match.group(1).strip(" .,-")[:160] if title_match else f"{course.name} class")
        payload = {"course_id": course.id, "title": title, "starts_at": starts_at.isoformat()}
        preview = {"action": "Schedule class", "course": course.name, "course_code": course.code,
                   "title": title, "starts_at": starts_at.isoformat(), "timezone": command.timezone}
        return payload, preview, True, "Review the class schedule before it is created."
    if intent == "draft_assignment":
        topic = _topic(command.command, course.name)
        marks_match = re.search(r"\b(?:worth|for|marks?)\s+(\d{1,3})\s*(?:marks?)?\b", lowered)
        max_marks = min(1000, max(1, int(marks_match.group(1)))) if marks_match else 100
        due_at = _local_datetime(command.command.split("due", 1)[1], command.timezone, False) if "due" in lowered else None
        payload = {"course_id": course.id, "title": f"{topic} assignment", "description":
                   f"Complete the faculty-reviewed assignment on {topic} and submit it through EKEEKRTA.",
                   "max_marks": max_marks, "due_date": due_at.isoformat() if due_at else None}
        preview = {"action": "Create assignment", "course": course.name, **{k: v for k, v in payload.items() if k != "course_id"}}
        return payload, preview, True, "This is a draft. Review it before publishing the assignment."
    if intent == "draft_quiz":
        topic = _topic(command.command, course.name)
        number = re.search(r"\b(\d{1,2})\s+(?:question|mcq)", lowered)
        count = min(50, max(1, int(number.group(1)))) if number else 5
        payload = {"course_id": course.id, "topic": topic, "suggested_question_count": count}
        preview = {"action": "Prepare quiz builder", "course": course.name, "topic": topic,
                   "suggested_question_count": count, "published": False,
                   "faculty_input_required": "Enter and verify every question, option and correct answer."}
        return payload, preview, False, "The quiz builder outline is ready. No answers were invented or published."
    raise HTTPException(422, "I could not safely understand that command")


@router.get("/capabilities", response_model=AICapabilitiesOut)
def capabilities(user: User = Depends(get_current_user)):
    labels = {
        "schedule_class": "Schedule a class", "draft_assignment": "Draft and publish an assignment",
        "draft_quiz": "Prepare a quiz outline or source-grounded review draft", "student_progress": "Analyse permitted student progress",
        "import_erp_students": "Import users by role from the configured ERP", "help": "Show available commands",
        "create_department": "Create an institution department", "create_course": "Create a structured course",
        "bulk_create_accounts": "Bulk-create student and faculty accounts",
        "course_question": "Ask questions using approved course sources",
    }
    available = [{"intent": intent, "label": labels[intent]} for intent in sorted(ROLE_INTENTS[user.role])]
    if user.role == UserRole.student:
        available.append({"intent": "cgpa_plan", "label": "Build a target-CGPA improvement roadmap"})
    return {"engine": "EKEEKRTA Native Intent Model v1", "external_models": False,
            "capabilities": available}


def _course_priority_records(db: Session, student: User, weekly_hours: float) -> list[dict]:
    courses = courses_query(db, student).order_by(Course.name).all()
    records = []
    for course in courses:
        session_ids = [row[0] for row in db.query(ClassSession.id).filter(ClassSession.course_id == course.id).all()]
        attendance_rows = db.query(Attendance).filter(
            Attendance.student_id == student.id, Attendance.session_id.in_(session_ids or [-1])).all()
        attendance_percent = (round(100 * sum(bool(row.present) for row in attendance_rows) / len(attendance_rows), 1)
                              if attendance_rows else None)

        assignments = db.query(Assignment).filter(Assignment.course_id == course.id).all()
        assignment_ids = [item.id for item in assignments]
        submissions = db.query(Submission).filter(
            Submission.student_id == student.id, Submission.assignment_id.in_(assignment_ids or [-1])).all()
        submitted_ids = {item.assignment_id for item in submissions}
        assignment_by_id = {item.id: item for item in assignments}
        assignment_scores = [100 * item.marks_obtained / assignment_by_id[item.assignment_id].max_marks
                             for item in submissions if item.marks_obtained is not None and
                             assignment_by_id.get(item.assignment_id) and assignment_by_id[item.assignment_id].max_marks]
        assignment_average = round(sum(assignment_scores) / len(assignment_scores), 1) if assignment_scores else None
        missing_assignments = len(set(assignment_ids) - submitted_ids)

        quiz_ids = [row[0] for row in db.query(Quiz.id).filter(Quiz.course_id == course.id).all()]
        quiz_scores = [row[0] for row in db.query(QuizAttempt.score).filter(
            QuizAttempt.student_id == student.id, QuizAttempt.quiz_id.in_(quiz_ids or [-1])).all()]
        quiz_average = round(sum(quiz_scores) / len(quiz_scores), 1) if quiz_scores else None

        assessment_ids = [row[0] for row in db.query(ProgrammingAssessment.id).filter(
            ProgrammingAssessment.course_id == course.id).all()]
        programming_scores = [row[0] for row in db.query(ProgrammingSubmission.score).filter(
            ProgrammingSubmission.student_id == student.id,
            ProgrammingSubmission.assessment_id.in_(assessment_ids or [-1])).all()]
        programming_average = round(sum(programming_scores) / len(programming_scores), 1) if programming_scores else None

        evidence, actions, score = [], [], 1.0
        if attendance_percent is not None:
            evidence.append(f"Attendance: {attendance_percent}%")
            if attendance_percent < 75:
                score += (75 - attendance_percent) * 0.8
                actions.append("Attend upcoming classes and recover the institution attendance requirement.")
        if missing_assignments:
            evidence.append(f"Missing assignments: {missing_assignments}")
            score += 12 * missing_assignments
            actions.append("Complete the missing assignments before starting optional practice.")
        for label, average in (("Assignment average", assignment_average), ("Quiz average", quiz_average),
                               ("Programming average", programming_average)):
            if average is not None:
                evidence.append(f"{label}: {average}%")
                if average < 60:
                    score += (60 - average) * 0.5
                    actions.append(f"Use a focused revision block to improve the {label.lower()}.")
        if not evidence:
            evidence.append("No graded LMS evidence is available yet.")
            actions.append("Set an initial weekly study block and review it after the first assessment.")
        elif not actions:
            actions.append("Maintain performance and practise the next assessed topic.")
        records.append({"course_id": course.id, "course_code": course.code, "course": course.name,
                        "priority_score": round(score, 1), "evidence": evidence,
                        "recommended_actions": list(dict.fromkeys(actions))})

    records.sort(key=lambda item: (-item["priority_score"], item["course"]))
    selected = records[:6]
    weight = sum(item["priority_score"] for item in selected) or 1
    for item in selected:
        item["weekly_hours"] = round(weekly_hours * item["priority_score"] / weight, 1)
    return selected


def _course_scenario_projection(db: Session, student: User, payload: AICGPAPlanIn) -> dict | None:
    if not payload.course_scenarios:
        return None
    enrolled = db.query(Course).join(Enrollment).filter(
        Enrollment.student_id == student.id,
        Course.institution_id == tenant(student),
        Course.id.in_([item.course_id for item in payload.course_scenarios]),
    ).all()
    by_id = {course.id: course for course in enrolled}
    rows, scenario_points, scenario_credits = [], 0.0, 0.0
    for item in payload.course_scenarios:
        course = by_id.get(item.course_id)
        if not course:
            raise HTTPException(403, "A grade scenario can include only your enrolled courses")
        if course.course_type != "academic":
            raise HTTPException(422, f"{course.code} is not an academic CGPA course")
        if course.credits is None:
            raise HTTPException(422, f"Credits are not configured for {course.code}")
        if item.expected_grade_point > payload.grading_scale_max:
            raise HTTPException(422, f"Expected grade point for {course.code} exceeds the institution scale")
        points = item.expected_grade_point * course.credits
        scenario_points += points
        scenario_credits += course.credits
        rows.append({"course_id": course.id, "course_code": course.code, "course": course.name,
                     "credits": course.credits, "expected_grade_point": item.expected_grade_point,
                     "quality_points": round(points, 2)})
    if scenario_credits > payload.remaining_credits + 1e-9:
        raise HTTPException(422, "Scenario course credits cannot exceed total remaining credits")
    projected = ((payload.current_cgpa * payload.completed_credits + scenario_points) /
                 (payload.completed_credits + scenario_credits))
    return {"scenario_credits": round(scenario_credits, 2),
            "projected_cgpa_after_scenario": round(projected, 2), "courses": rows}


def _cgpa_projection(payload: AICGPAPlanIn) -> dict:
    current_points = payload.current_cgpa * payload.completed_credits
    total_credits = payload.completed_credits + payload.remaining_credits
    required_points = payload.target_cgpa * total_credits - current_points
    required_average = required_points / payload.remaining_credits
    best_possible = (current_points + payload.grading_scale_max * payload.remaining_credits) / total_credits
    ratio = required_average / payload.grading_scale_max
    if required_average > payload.grading_scale_max + 1e-9:
        status, explanation = ("not_mathematically_reachable",
                               "The target is above the maximum possible CGPA for the remaining credits.")
    elif payload.target_cgpa <= payload.current_cgpa:
        status, explanation = ("target_already_reached",
                               "The current CGPA already meets this target; the roadmap focuses on maintaining it.")
    elif ratio >= 0.9:
        status, explanation = ("very_demanding",
                               "The target is mathematically possible but requires performance close to the grading maximum.")
    elif ratio >= 0.75:
        status, explanation = ("challenging",
                               "The target is possible but requires consistently strong remaining-semester performance.")
    else:
        status, explanation = ("achievable",
                               "The target is mathematically achievable with the calculated remaining-credit average.")

    planned_average = min(payload.grading_scale_max, max(0, required_average))
    credits_per_semester = payload.remaining_credits / payload.remaining_semesters
    milestones = []
    earned_points, earned_credits = current_points, payload.completed_credits
    for number in range(1, payload.remaining_semesters + 1):
        semester_credits = (payload.remaining_credits - credits_per_semester * (number - 1)
                            if number == payload.remaining_semesters else credits_per_semester)
        earned_points += planned_average * semester_credits
        earned_credits += semester_credits
        milestones.append({"remaining_semester": number, "planned_sgpa": round(planned_average, 2),
                           "projected_cgpa": round(earned_points / earned_credits, 2)})
    return {"status": status, "explanation": explanation,
            "required_average_for_remaining_credits": round(required_average, 2),
            "best_possible_final_cgpa": round(best_possible, 2),
            "total_credits_at_goal": round(total_credits, 2), "milestones": milestones}


def _goal_values(payload: AICGPAPlanIn, source: str) -> dict:
    return {"current_cgpa": payload.current_cgpa, "target_cgpa": payload.target_cgpa,
            "completed_credits": payload.completed_credits, "remaining_credits": payload.remaining_credits,
            "remaining_semesters": payload.remaining_semesters, "weekly_study_hours": payload.weekly_study_hours,
            "grading_scale_max": payload.grading_scale_max,
            "course_scenarios": [item.model_dump() for item in payload.course_scenarios], "data_source": source}


def _save_goal(db: Session, user: User, payload: AICGPAPlanIn, projection: dict, source: str) -> AICGPAGoal:
    goal = db.query(AICGPAGoal).filter(AICGPAGoal.institution_id == tenant(user),
                                       AICGPAGoal.student_id == user.id).first()
    if goal is None:
        goal = AICGPAGoal(institution_id=tenant(user), student_id=user.id)
        db.add(goal)
    for key, value in _goal_values(payload, source).items():
        setattr(goal, key, value)
    checkpoint = {"recorded_at": datetime.now(timezone.utc).isoformat(), "current_cgpa": payload.current_cgpa,
                  "target_cgpa": payload.target_cgpa, "required_average": projection["required_average_for_remaining_credits"],
                  "status": projection["status"], "source": source}
    goal.checkpoints = [*(goal.checkpoints or []), checkpoint][-24:]
    return goal


def _plan_result(db: Session, user: User, payload: AICGPAPlanIn, source: str) -> tuple[dict, dict]:
    projection = _cgpa_projection(payload)
    scenario = _course_scenario_projection(db, user, payload)
    result = {"projection": projection, "course_scenario": scenario,
              "course_priorities": _course_priority_records(db, user, payload.weekly_study_hours),
              "weekly_study_hours": payload.weekly_study_hours,
              "grading_rules": {"scale_max": payload.grading_scale_max,
                                  "passing_grade_point": user.institution.passing_grade_point},
              "roadmap": [
                  "Review this projection whenever official grades or remaining credits change.",
                  "Complete missing assessed work before adding optional study tasks.",
                  "Use the course-priority hours as a weekly starting point and adjust them with faculty guidance.",
                  "Check attendance, assignment, quiz, and programming progress every week.",
              ],
              "data_basis": ("Verified institution ERP result summary combined with current EKEEKRTA course evidence."
                             if source == "erp" else
                             "Student-entered official values combined with current EKEEKRTA course evidence."),
              "official_record_notice": "This is a planning projection, not an official result or a guarantee. The institution ERP remains the source of official CGPA.",
              "external_model": False}
    return projection, result


def _institution_payload(user: User, payload: AICGPAPlanIn) -> AICGPAPlanIn:
    scale = float(user.institution.grading_scale_max)
    if payload.current_cgpa > scale or payload.target_cgpa > scale:
        raise HTTPException(422, f"CGPA values must fit the institution grading scale of {scale:g}")
    return payload.model_copy(update={"grading_scale_max": scale})


@router.post("/cgpa-plan", response_model=AICommandOut, status_code=201)
def cgpa_plan(payload: AICGPAPlanIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role != UserRole.student:
        raise HTTPException(403, "Only students can create a personal CGPA roadmap")
    payload = _institution_payload(user, payload)
    projection, result = _plan_result(db, user, payload, "student")
    action = AIAction(institution_id=tenant(user), requester_id=user.id, intent="cgpa_plan", status="completed",
                      prompt=f"Plan from CGPA {payload.current_cgpa:g} to {payload.target_cgpa:g}", confidence=1.0,
                      payload=payload.model_dump(), preview=result, result=result, requires_confirmation=False,
                      executed_at=datetime.now(timezone.utc))
    db.add(action); db.flush()
    goal = _save_goal(db, user, payload, projection, "student")
    _audit(db, user, "cgpa_roadmap_created", action.id,
           {"status": projection["status"], "external_model": False})
    db.commit(); db.refresh(action)
    return {"message": "Your target-CGPA roadmap and checkpoint were saved.", "action": action}


@router.get("/cgpa-goal")
def cgpa_goal(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role != UserRole.student:
        raise HTTPException(403, "Only students can view a personal CGPA goal")
    goal = db.query(AICGPAGoal).filter(AICGPAGoal.institution_id == tenant(user),
                                       AICGPAGoal.student_id == user.id).first()
    if not goal:
        return {"goal": None}
    return {"goal": {key: getattr(goal, key) for key in (
        "current_cgpa", "target_cgpa", "completed_credits", "remaining_credits", "remaining_semesters",
        "weekly_study_hours", "grading_scale_max", "course_scenarios", "checkpoints", "data_source")}}


@router.post("/cgpa-goal/refresh-erp", response_model=AICommandOut)
def refresh_cgpa_goal_from_erp(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role != UserRole.student:
        raise HTTPException(403, "Only students can refresh a personal CGPA goal")
    if not user.institutional_id:
        raise HTTPException(409, "Your profile needs an official institution ID before ERP refresh")
    goal = db.query(AICGPAGoal).filter(AICGPAGoal.institution_id == tenant(user),
                                       AICGPAGoal.student_id == user.id).first()
    if not goal:
        raise HTTPException(409, "Create a CGPA goal before refreshing it from the ERP")
    integration = db.query(ERPIntegration).filter(ERPIntegration.institution_id == tenant(user)).first()
    if not integration or not integration.enabled or not integration.sync_students:
        raise HTTPException(409, "The institution ERP result connection is not enabled")
    try:
        exported = fetch_erp_academic_result(integration, user.institutional_id)
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 404:
            raise HTTPException(404, "No official ERP result was found for your institution ID") from None
        raise HTTPException(502, "The verified ERP result could not be read") from exc
    record = exported.get("result") or {}
    scale = float(user.institution.grading_scale_max)
    if float(record.get("grading_scale_max", scale)) != scale:
        raise HTTPException(409, "ERP and EKEEKRTA grading scales do not match; ask the administrator to review settings")
    try:
        payload = AICGPAPlanIn(current_cgpa=record["current_cgpa"], target_cgpa=goal.target_cgpa,
                               completed_credits=record["completed_credits"], remaining_credits=record["remaining_credits"],
                               remaining_semesters=goal.remaining_semesters, weekly_study_hours=goal.weekly_study_hours,
                               grading_scale_max=scale, course_scenarios=goal.course_scenarios or [])
    except (KeyError, ValueError) as exc:
        raise HTTPException(502, "The ERP academic result is incomplete or invalid") from exc
    projection, result = _plan_result(db, user, payload, "erp")
    action = AIAction(institution_id=tenant(user), requester_id=user.id, intent="cgpa_plan", status="completed",
                      prompt="Refresh CGPA roadmap from verified ERP result", confidence=1.0,
                      payload=payload.model_dump(), preview=result, result=result, requires_confirmation=False,
                      executed_at=datetime.now(timezone.utc))
    db.add(action); db.flush(); _save_goal(db, user, payload, projection, "erp")
    _audit(db, user, "cgpa_roadmap_refreshed_from_erp", action.id, {"external_model": False})
    db.commit(); db.refresh(action)
    return {"message": "Your roadmap was refreshed from the verified ERP result record.", "action": action}


@router.post("/commands", response_model=AICommandOut, status_code=201)
def command(payload: AICommandIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if re.search(r"\b(password|private key|api[_ -]?token|secret key)\b", payload.command, re.I):
        raise HTTPException(422, "Do not place passwords, private keys or API tokens in an AI command")
    intent, confidence = model.predict(payload.command)
    if confidence < 0.36:
        intent = "help"
    if intent not in ROLE_INTENTS[user.role]:
        _audit(db, user, "command_denied", None, {"intent": intent, "role": user.role.value})
        db.commit()
        raise HTTPException(403, "That AI action is not available for your role")
    action_payload, preview, confirmation, message = _build_action(db, user, payload, intent, confidence)
    status = "draft" if confirmation else "completed"
    action = AIAction(institution_id=tenant(user), requester_id=user.id, intent=intent, status=status,
                      prompt=payload.command.strip(), confidence=confidence, payload=action_payload,
                      preview=preview, result=preview if not confirmation else None,
                      requires_confirmation=confirmation, executed_at=datetime.now(timezone.utc) if not confirmation else None)
    db.add(action)
    db.flush()
    _audit(db, user, "command_interpreted", action.id, {"intent": intent, "confirmation_required": confirmation})
    db.commit()
    db.refresh(action)
    return {"message": message, "action": action}


@router.get("/actions", response_model=list[AIActionOut])
def actions(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(AIAction).filter(AIAction.institution_id == tenant(user),
                                     AIAction.requester_id == user.id).order_by(AIAction.id.desc()).limit(100).all()


@router.post("/content-drafts", response_model=AICommandOut, status_code=201)
def content_draft(payload: AIContentDraftIn, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    if user.role != UserRole.faculty:
        raise HTTPException(403, "Only faculty can generate teaching-content drafts")
    if re.search(r"\b(password|private key|api[_ -]?token|secret key)\b", payload.source_text, re.I):
        raise HTTPException(422, "Remove passwords, private keys and API tokens from the lesson notes")
    course = course_access(db, user, payload.course_id, manage=True)
    try:
        if payload.content_type == "assignment":
            generated = build_assignment_draft(payload.topic, payload.source_text)
            intent = "draft_assignment"
            action_payload = {"course_id": course.id, "title": generated["title"],
                              "description": generated["description"], "max_marks": payload.max_marks,
                              "due_date": payload.due_date.isoformat() if payload.due_date else None}
            preview = {"action": "Create source-grounded assignment", "course": course.name,
                       "course_code": course.code, **generated, "max_marks": payload.max_marks,
                       "due_date": action_payload["due_date"]}
        else:
            generated = build_quiz_draft(payload.topic, payload.source_text, payload.question_count)
            intent = "draft_quiz"
            action_payload = {"course_id": course.id, "title": generated["title"],
                              "total_marks": payload.max_marks, "questions": [
                                  {key: question[key] for key in ("text", "options", "correct_option")}
                                  for question in generated["questions"]]}
            preview = {"action": "Create source-grounded quiz", "course": course.name,
                       "course_code": course.code, **generated, "total_marks": payload.max_marks}
    except ContentDraftError as error:
        raise HTTPException(422, str(error)) from None
    preview.update({"engine": "EKEEKRTA Local Content Draft Engine v1", "external_model": False,
                    "grounding": "Generated only from faculty-provided lesson notes.",
                    "faculty_review_required": True, "published": False})
    action = AIAction(institution_id=tenant(user), requester_id=user.id, intent=intent, status="draft",
                      prompt=f"{payload.content_type.title()} draft on {payload.topic} for {course.code}",
                      confidence=1.0, payload=action_payload, preview=preview, result=None,
                      requires_confirmation=True)
    db.add(action); db.flush()
    _audit(db, user, "source_grounded_draft_created", action.id,
           {"intent": intent, "course_id": course.id, "source_characters": len(payload.source_text),
            "external_model": False})
    db.commit(); db.refresh(action)
    return {"message": "Review every generated item below. Nothing has been published yet.", "action": action}


def _knowledge_source_summary(source: AIKnowledgeSource, managed_by_lecture: bool = False) -> dict:
    return {"id": source.id, "course_id": source.course_id, "title": source.title,
            "source_type": source.source_type, "is_published": source.is_published,
            "managed_by_lecture": managed_by_lecture,
            "character_count": len(source.content), "created_by": source.created_by,
            "created_at": source.created_at, "updated_at": source.updated_at}


def _lecture_manages_source(db: Session, source_id: int, institution_id: int) -> bool:
    return db.query(AILectureContent.id).filter(
        AILectureContent.institution_id == institution_id,
        AILectureContent.knowledge_source_id == source_id).first() is not None


@router.post("/knowledge-sources", status_code=201)
def create_knowledge_source(payload: AIKnowledgeSourceIn, db: Session = Depends(get_db),
                            user: User = Depends(get_current_user)):
    if user.role not in (UserRole.faculty, UserRole.admin):
        raise HTTPException(403, "Only authorized faculty or administrators can add course knowledge")
    if re.search(r"\b(password|private key|api[_ -]?token|secret key)\b", payload.content, re.I):
        raise HTTPException(422, "Remove passwords, private keys and API tokens from the source")
    course = course_access(db, user, payload.course_id, manage=True)
    source = AIKnowledgeSource(institution_id=tenant(user), course_id=course.id, created_by=user.id,
                               title=payload.title, source_type=payload.source_type, content=payload.content,
                               is_published=payload.publish_to_students)
    db.add(source); db.flush()
    _audit(db, user, "course_knowledge_source_created", None,
           {"source_id": source.id, "course_id": course.id, "published": source.is_published,
            "characters": len(source.content)})
    db.commit(); db.refresh(source)
    return {"message": "The approved course source is ready for grounded questions.",
            "source": _knowledge_source_summary(source)}


@router.get("/knowledge-sources/course/{course_id}")
def list_knowledge_sources(course_id: int, db: Session = Depends(get_db),
                           user: User = Depends(get_current_user)):
    course_access(db, user, course_id)
    query = db.query(AIKnowledgeSource).filter(
        AIKnowledgeSource.institution_id == tenant(user), AIKnowledgeSource.course_id == course_id,
        AIKnowledgeSource.archived_at.is_(None))
    if user.role not in (UserRole.faculty, UserRole.admin):
        query = query.filter(AIKnowledgeSource.is_published.is_(True))
    sources = query.order_by(AIKnowledgeSource.id.desc()).all()
    source_ids = [source.id for source in sources]
    managed_ids = set()
    if source_ids:
        managed_ids = {row[0] for row in db.query(AILectureContent.knowledge_source_id).filter(
            AILectureContent.institution_id == tenant(user),
            AILectureContent.knowledge_source_id.in_(source_ids)).all()}
    return [_knowledge_source_summary(source, source.id in managed_ids) for source in sources]


@router.patch("/knowledge-sources/{source_id}/publication")
def change_knowledge_publication(source_id: int, payload: AIKnowledgePublicationIn,
                                 db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    source = db.query(AIKnowledgeSource).filter(
        AIKnowledgeSource.id == source_id, AIKnowledgeSource.institution_id == tenant(user),
        AIKnowledgeSource.archived_at.is_(None)).first()
    if not source:
        raise HTTPException(404, "Course source not found")
    course_access(db, user, source.course_id, manage=True)
    if _lecture_manages_source(db, source.id, tenant(user)):
        raise HTTPException(409, "Manage this source from lecture notes")
    source.is_published = payload.published
    _audit(db, user, "course_knowledge_publication_changed", None,
           {"source_id": source.id, "course_id": source.course_id, "published": source.is_published})
    db.commit(); db.refresh(source)
    return {"message": "Source visibility updated.", "source": _knowledge_source_summary(source)}


@router.delete("/knowledge-sources/{source_id}", status_code=204)
def archive_knowledge_source(source_id: int, db: Session = Depends(get_db),
                             user: User = Depends(get_current_user)):
    source = db.query(AIKnowledgeSource).filter(
        AIKnowledgeSource.id == source_id, AIKnowledgeSource.institution_id == tenant(user),
        AIKnowledgeSource.archived_at.is_(None)).first()
    if not source:
        raise HTTPException(404, "Course source not found")
    course_access(db, user, source.course_id, manage=True)
    if _lecture_manages_source(db, source.id, tenant(user)):
        raise HTTPException(409, "Manage this source from lecture notes")
    source.archived_at = datetime.now(timezone.utc)
    source.is_published = False
    _audit(db, user, "course_knowledge_source_archived", None,
           {"source_id": source.id, "course_id": source.course_id})
    db.commit()


@router.post("/course-question", response_model=AICommandOut, status_code=201)
def answer_course_question(payload: AICourseQuestionIn, db: Session = Depends(get_db),
                           user: User = Depends(get_current_user)):
    if re.search(r"\b(password|private key|api[_ -]?token|secret key)\b", payload.question, re.I):
        raise HTTPException(422, "Do not place passwords, private keys or API tokens in a question")
    course = course_access(db, user, payload.course_id)
    sources = db.query(AIKnowledgeSource).filter(
        AIKnowledgeSource.institution_id == tenant(user), AIKnowledgeSource.course_id == course.id,
        AIKnowledgeSource.is_published.is_(True), AIKnowledgeSource.archived_at.is_(None)).all()
    result = retrieve(payload.question, sources)
    result.update({"course_id": course.id, "course": course.name, "course_code": course.code,
                   "engine": "EKEEKRTA Local Course Retrieval v1", "external_model": False,
                   "grounding": "Only published, faculty-approved course text was searched."})
    action = AIAction(institution_id=tenant(user), requester_id=user.id, intent="course_question",
                      status="completed", prompt=payload.question, confidence=1.0 if result["answered"] else 0.0,
                      payload={"course_id": course.id}, preview=result, result=result,
                      requires_confirmation=False, executed_at=datetime.now(timezone.utc))
    db.add(action); db.flush()
    _audit(db, user, "course_question_answered", action.id,
           {"course_id": course.id, "answered": result["answered"],
            "citation_count": len(result["citations"]), "external_model": False})
    db.commit(); db.refresh(action)
    message = "Answer found in approved course sources." if result["answered"] else result["answer"]
    return {"message": message, "action": action}


def _bulk_validation(db: Session, user: User, records) -> tuple[list[dict], list[dict]]:
    departments = {item.name.lower(): item.name for item in db.query(Department).filter(
        Department.institution_id == tenant(user)).all()}
    seen_emails, seen_ids, normalized, errors = set(), set(), [], []
    for index, source in enumerate(records, start=2):
        row = source.model_dump(mode="json")
        email = str(row["email"]).lower()
        official_id = row["institutional_id"].strip()
        department = departments.get(row["department"].lower())
        problem = None
        if email.rsplit("@", 1)[-1] != user.institution.email_domain.lower():
            problem = f"Email must use @{user.institution.email_domain}"
        elif not department:
            problem = "Department does not exist in this institution"
        elif email in seen_emails or db.query(User).filter(func.lower(User.email) == email).first():
            problem = "Email is duplicated or already registered"
        elif official_id.lower() in seen_ids or db.query(User).filter(
            User.institution_id == tenant(user), func.lower(User.institutional_id) == official_id.lower()).first():
            problem = "Official ID is duplicated or already registered"
        elif row["role"] == "student" and (not row.get("program") or not row.get("batch") or
                                             row.get("semester_number") is None or not row.get("section")):
            problem = "Students require program, batch, semester and section"
        if problem:
            errors.append({"row": index, "email": email, "error": problem})
            continue
        seen_emails.add(email); seen_ids.add(official_id.lower())
        row.update({"email": email, "institutional_id": official_id, "department": department})
        if row["role"] == "faculty":
            row.update({"program": None, "batch": None, "semester_number": None, "section": None})
        normalized.append(row)
    return normalized, errors


@router.post("/bulk-accounts/preview", response_model=AICommandOut, status_code=201)
def bulk_accounts_preview(payload: AIBulkAccountsIn, db: Session = Depends(get_db),
                          user: User = Depends(get_current_user)):
    if user.role != UserRole.admin:
        raise HTTPException(403, "Only an administrator can bulk-create accounts")
    normalized, errors = _bulk_validation(db, user, payload.records)
    valid = not errors and len(normalized) == len(payload.records)
    preview = {"action": "Bulk-create accounts", "total_rows": len(payload.records),
               "valid_rows": len(normalized), "invalid_rows": len(errors), "errors": errors,
               "authentication": "Verified institution Google account; no shared password is generated"}
    action = AIAction(institution_id=tenant(user), requester_id=user.id, intent="bulk_create_accounts",
                      status="draft" if valid else "needs_changes", prompt="Bulk account CSV upload",
                      confidence=1.0, payload={"records": normalized} if valid else {}, preview=preview,
                      result=None, requires_confirmation=valid)
    db.add(action); db.flush()
    _audit(db, user, "bulk_accounts_validated", action.id,
           {"total_rows": len(payload.records), "valid_rows": len(normalized), "invalid_rows": len(errors)})
    db.commit(); db.refresh(action)
    return {"message": "All rows are ready for confirmation." if valid else "Correct the listed rows and preview the file again.",
            "action": action}


@router.get("/review/actions")
def review_actions(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role != UserRole.admin:
        raise HTTPException(403, "Only an administrator can review institution AI actions")
    rows = db.query(AIAction, User).join(User, User.id == AIAction.requester_id).filter(
        AIAction.institution_id == tenant(user), User.institution_id == tenant(user)).order_by(AIAction.id.desc()).limit(200).all()
    return [{"action": AIActionOut.model_validate(action).model_dump(),
             "requester": {"id": requester.id, "name": requester.name, "role": requester.role.value}}
            for action, requester in rows]


@router.post("/review/actions/{action_id}/reject", response_model=AIActionOut)
def administrator_reject(action_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role != UserRole.admin:
        raise HTTPException(403, "Only an administrator can review institution AI actions")
    action = db.query(AIAction).filter(AIAction.id == action_id,
                                       AIAction.institution_id == tenant(user)).first()
    if not action:
        raise HTTPException(404, "AI action not found")
    if action.status != "draft":
        raise HTTPException(409, "Only a pending draft can be rejected")
    action.status = "rejected"
    _audit(db, user, "administrator_rejected_action", action.id,
           {"intent": action.intent, "requester_id": action.requester_id})
    db.commit(); db.refresh(action)
    return action


@router.post("/actions/{action_id}/confirm", response_model=AICommandOut)
def confirm(action_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    action = db.query(AIAction).filter(AIAction.id == action_id, AIAction.institution_id == tenant(user),
                                       AIAction.requester_id == user.id).first()
    if not action:
        raise HTTPException(404, "AI action not found")
    if action.status == "completed":
        return {"message": "This action was already completed.", "action": action}
    if action.status != "draft" or not action.requires_confirmation:
        raise HTTPException(409, "This action cannot be confirmed")
    if action.intent not in ROLE_INTENTS[user.role]:
        raise HTTPException(403, "Your role can no longer perform this action")
    payload = action.payload
    try:
        if action.intent == "schedule_class":
            course_access(db, user, payload["course_id"], manage=True)
            starts_at = datetime.fromisoformat(payload["starts_at"])
            duplicate = db.query(ScheduledClass).filter(ScheduledClass.course_id == payload["course_id"],
                                                        ScheduledClass.starts_at == starts_at,
                                                        ScheduledClass.cancelled_at.is_(None)).first()
            if duplicate:
                raise HTTPException(409, "A class is already scheduled for this course at that time")
            record = ScheduledClass(course_id=payload["course_id"], title=payload["title"], starts_at=starts_at)
            db.add(record)
            db.flush()
            result = {"scheduled_class_id": record.id, "course_id": record.course_id, "title": record.title,
                      "starts_at": record.starts_at.isoformat()}
        elif action.intent == "draft_assignment":
            course_access(db, user, payload["course_id"], manage=True)
            record = Assignment(course_id=payload["course_id"], title=payload["title"],
                                description=payload.get("description"),
                                due_date=datetime.fromisoformat(payload["due_date"]) if payload.get("due_date") else None,
                                max_marks=payload["max_marks"])
            db.add(record)
            db.flush()
            result = {"assignment_id": record.id, "course_id": record.course_id, "title": record.title}
        elif action.intent == "draft_quiz":
            course_access(db, user, payload["course_id"], manage=True)
            questions = payload.get("questions") or []
            if not questions or len(questions) > 20:
                raise HTTPException(409, "The quiz draft has no valid questions")
            record = Quiz(course_id=payload["course_id"], title=payload["title"],
                          total_marks=payload["total_marks"])
            db.add(record); db.flush()
            for item in questions:
                options = item.get("options") or []
                correct = item.get("correct_option")
                if len(options) < 2 or len(options) > 6 or not isinstance(correct, int) or not 0 <= correct < len(options):
                    raise HTTPException(409, "The quiz draft contains an invalid answer set")
                db.add(Question(quiz_id=record.id, text=item["text"], options=options,
                                correct_option=correct))
            db.flush()
            result = {"quiz_id": record.id, "course_id": record.course_id, "title": record.title,
                      "question_count": len(questions)}
        elif action.intent == "import_erp_students":
            from app.routers.erp import confirm_user_import
            from app.schemas.erp import ERPUserImportConfirmIn
            imported = confirm_user_import(
                ERPUserImportConfirmIn(confirmation_token=payload["confirmation_token"]), db, user
            )
            result = imported.model_dump()
        elif action.intent == "create_department":
            if user.role != UserRole.admin:
                raise HTTPException(403, "Only an administrator can create departments")
            if db.query(Department).filter(Department.institution_id == tenant(user),
                                           func.lower(Department.name) == payload["name"].lower()).first():
                raise HTTPException(409, "Department already exists")
            record = Department(institution_id=tenant(user), name=payload["name"])
            db.add(record); db.flush()
            result = {"department_id": record.id, "name": record.name}
        elif action.intent == "create_course":
            faculty = db.query(User).filter(User.id == payload["faculty_id"], User.institution_id == tenant(user),
                                             User.role == UserRole.faculty).first()
            if not faculty or (user.role == UserRole.faculty and faculty.id != user.id):
                raise HTTPException(403, "The selected faculty assignment is no longer permitted")
            if db.query(Course).filter(Course.institution_id == tenant(user),
                                       func.lower(Course.code) == payload["code"].lower()).first():
                raise HTTPException(409, "Course code already exists")
            department = db.query(Department).filter(Department.institution_id == tenant(user),
                                                      func.lower(Department.name) == payload["department"].lower()).first()
            if not department or (faculty.department or "").lower() != department.name.lower():
                raise HTTPException(409, "Department or faculty assignment changed; create a new preview")
            values = {key: value for key, value in payload.items() if key != "faculty_id"}
            values["semester"] = f"Semester {values['semester_number']}" if values.get("semester_number") else None
            record = Course(**values, faculty_id=faculty.id, institution_id=tenant(user))
            db.add(record); db.flush(); enroll_matching_students(db, record)
            enqueue_course_to_erp(db, record, user.institution, commit=False)
            result = {"course_id": record.id, "name": record.name, "code": record.code,
                      "faculty_id": faculty.id, "faculty": faculty.name}
        elif action.intent == "bulk_create_accounts":
            if user.role != UserRole.admin:
                raise HTTPException(403, "Only an administrator can bulk-create accounts")
            records = action.payload.get("records", [])
            if not records:
                raise HTTPException(409, "The bulk preview contains no valid records")
            from app.schemas.ai import AIBulkAccountRecord
            checked, errors = _bulk_validation(db, user, [AIBulkAccountRecord.model_validate(item) for item in records])
            if errors or len(checked) != len(records):
                raise HTTPException(409, "Account data changed since preview; validate the CSV again")
            created_ids = []
            # These accounts authenticate through verified institution Google
            # identity. One freshly generated, undisclosed fallback hash avoids
            # hundreds of expensive bcrypt operations in a serverless request.
            disabled_password_hash = hash_password(secrets.token_urlsafe(48))
            for item in checked:
                account = User(institution_id=tenant(user), role=UserRole(item["role"]), name=item["name"],
                               email=item["email"], institutional_id=item["institutional_id"],
                               department=item["department"], program=item.get("program"), batch=item.get("batch"),
                               semester_number=item.get("semester_number"), section=item.get("section"),
                               hashed_password=disabled_password_hash)
                db.add(account); db.flush(); created_ids.append(account.id)
                if account.role == UserRole.student:
                    enroll_matching_compulsory_courses(db, account)
            result = {"created_count": len(created_ids), "account_ids": created_ids,
                      "authentication": "Verified institution Google account"}
        else:
            raise HTTPException(409, "This AI action has no write operation")
        action.status = "completed"
        action.result = result
        action.executed_at = datetime.now(timezone.utc)
        _audit(db, user, "action_confirmed", action.id, {"intent": action.intent, "result": result})
        db.commit()
        db.refresh(action)
        return {"message": "Action completed successfully.", "action": action}
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(500, "The action could not be completed safely") from None


@router.post("/actions/{action_id}/reject", response_model=AIActionOut)
def reject(action_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    action = db.query(AIAction).filter(AIAction.id == action_id, AIAction.institution_id == tenant(user),
                                       AIAction.requester_id == user.id).first()
    if not action:
        raise HTTPException(404, "AI action not found")
    if action.status != "draft":
        raise HTTPException(409, "Only a draft action can be rejected")
    action.status = "rejected"
    _audit(db, user, "action_rejected", action.id, {"intent": action.intent})
    db.commit()
    db.refresh(action)
    return action


@router.post("/actions/{action_id}/correction", status_code=201)
def correction(action_id: int, payload: AICorrectionIn, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    if not payload.consent:
        raise HTTPException(422, "Consent is required before a correction is stored for training")
    if payload.corrected_intent not in AI_INTENTS:
        raise HTTPException(422, "Unknown corrected intent")
    action = db.query(AIAction).filter(AIAction.id == action_id, AIAction.institution_id == tenant(user),
                                       AIAction.requester_id == user.id).first()
    if not action:
        raise HTTPException(404, "AI action not found")
    example = AITrainingExample(institution_id=tenant(user), submitted_by=user.id,
                                command_text=action.prompt, original_intent=action.intent,
                                corrected_intent=payload.corrected_intent,
                                corrected_payload=payload.corrected_payload, consented=True)
    db.add(example)
    _audit(db, user, "training_correction_saved", action.id,
           {"original_intent": action.intent, "corrected_intent": payload.corrected_intent})
    db.commit()
    return {"message": "Correction saved for a reviewed future EKEEKRTA model training run.", "example_id": example.id}
