"""Explainable, role-scoped progress intelligence from EKEEKRTA records.

This module deliberately uses published thresholds instead of a hidden model.
It never changes a mark, attendance record, enrolment, or official ERP result.
"""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.access import course_access, courses_query, tenant, users_query
from app.models.assignment import Assignment, Submission
from app.models.attendance import Attendance, ClassSession
from app.models.course import Course, Enrollment
from app.models.programming import ProgrammingAssessment, ProgrammingSubmission
from app.models.quiz import Quiz, QuizAttempt
from app.models.user import User, UserRole


RISK_ORDER = {"critical": 0, "high": 1, "watch": 2, "stable": 3, "insufficient_data": 4}
RISK_THRESHOLDS = {
    "attendance_target_percent": 75,
    "critical_attendance_percent": 60,
    "watch_attendance_percent": 85,
    "high_performance_percent": 50,
    "critical_performance_percent": 40,
    "watch_performance_percent": 60,
    "high_missing_assignments": 2,
    "critical_missing_assignments": 3,
}


def _average(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


def _course_metrics(db: Session, student_id: int, course: Course) -> dict:
    enrollment = db.query(Enrollment).filter(
        Enrollment.student_id == student_id,
        Enrollment.course_id == course.id,
    ).first()
    # Only ended sessions are final evidence. A missing attendance row for an
    # enrolled student in an ended session is an absence, not "no data". Do
    # not penalize a student for sessions held before their enrolment.
    session_query = db.query(ClassSession.id).filter(
        ClassSession.course_id == course.id,
        ClassSession.ended_at.is_not(None),
    )
    if enrollment and enrollment.enrolled_at:
        session_query = session_query.filter(ClassSession.scheduled_at >= enrollment.enrolled_at)
    sessions = session_query.all()
    session_ids = [row[0] for row in sessions]
    attendance = db.query(Attendance).filter(
        Attendance.student_id == student_id,
        Attendance.session_id.in_(session_ids or [-1]),
    ).all()
    attended_count = len({row.session_id for row in attendance if row.present})
    attendance_percent = round(100 * attended_count / len(session_ids), 1) if session_ids else None

    assignments = db.query(Assignment).filter(Assignment.course_id == course.id).all()
    assignment_ids = [item.id for item in assignments]
    submission_rows = db.query(Submission).filter(
        Submission.student_id == student_id,
        Submission.assignment_id.in_(assignment_ids or [-1]),
    ).order_by(Submission.submitted_at, Submission.id).all()
    submissions = {item.assignment_id: item for item in submission_rows}
    submitted_ids = set(submissions)
    now = datetime.now(timezone.utc)
    missing_due = sum(
        1 for item in assignments
        if item.id not in submitted_ids and item.due_date is not None
        and (item.due_date if item.due_date.tzinfo else item.due_date.replace(tzinfo=timezone.utc)) <= now
    )
    assignments_by_id = {item.id: item for item in assignments}
    assignment_scores = [
        100 * item.marks_obtained / assignments_by_id[item.assignment_id].max_marks
        for item in submissions.values()
        if item.marks_obtained is not None
        and assignments_by_id.get(item.assignment_id)
        and assignments_by_id[item.assignment_id].max_marks
    ]

    quizzes = db.query(Quiz).filter(Quiz.course_id == course.id).all()
    quiz_ids = [item.id for item in quizzes]
    quiz_attempt_rows = db.query(QuizAttempt).filter(
        QuizAttempt.student_id == student_id,
        QuizAttempt.quiz_id.in_(quiz_ids or [-1]),
    ).order_by(QuizAttempt.submitted_at, QuizAttempt.id).all()
    latest_quiz_attempts = {item.quiz_id: item for item in quiz_attempt_rows}
    quiz_scores = [item.score for item in latest_quiz_attempts.values()]

    assessments = db.query(ProgrammingAssessment).filter(
        ProgrammingAssessment.course_id == course.id).all()
    assessment_ids = [item.id for item in assessments]
    programming_rows = db.query(ProgrammingSubmission).filter(
        ProgrammingSubmission.student_id == student_id,
        ProgrammingSubmission.assessment_id.in_(assessment_ids or [-1]),
    ).order_by(ProgrammingSubmission.submitted_at, ProgrammingSubmission.id).all()
    latest_programming = {item.assessment_id: item for item in programming_rows}
    programming_scores = [item.score for item in latest_programming.values()]

    performance_scores = assignment_scores + quiz_scores + programming_scores
    return {
        "course_id": course.id,
        "course_code": course.code,
        "course_name": course.name,
        "attendance": {
            "held": len(session_ids),
            "attended": attended_count,
            "percent": attendance_percent,
        },
        "assignments": {
            "total": len(assignments),
            "submitted": len(submitted_ids),
            "graded": len(assignment_scores),
            "average_percent": _average(assignment_scores),
            "missing_due": missing_due,
        },
        "quizzes": {
            "total": len(quizzes),
            "attempted": len(quiz_scores),
            "average_percent": _average(quiz_scores),
        },
        "programming": {
            "total": len(assessments),
            "attempted": len(programming_scores),
            "average_percent": _average(programming_scores),
        },
        "performance_average_percent": _average(performance_scores),
        "performance_evidence_count": len(performance_scores),
    }


def _classify(metrics: dict) -> tuple[str, list[str], list[str]]:
    reasons: list[str] = []
    actions: list[str] = []
    attendance = metrics["attendance"]["percent"]
    attendance_held = metrics["attendance"]["held"]
    missing = metrics["assignments"]["missing_due"]
    performance = metrics["performance_average_percent"]
    performance_count = metrics["performance_evidence_count"]

    if attendance_held:
        if attendance < RISK_THRESHOLDS["critical_attendance_percent"]:
            reasons.append(f"Attendance is {attendance}%, below the critical 60% threshold.")
            actions.append("Meet the faculty member and make an attendance recovery plan.")
        elif attendance < RISK_THRESHOLDS["attendance_target_percent"]:
            reasons.append(f"Attendance is {attendance}%, below the 75% target.")
            actions.append("Attend every upcoming class and review unavoidable absences with faculty.")
        elif attendance < RISK_THRESHOLDS["watch_attendance_percent"]:
            reasons.append(f"Attendance is {attendance}%, close to the 75% minimum.")
            actions.append("Protect the attendance margin by avoiding optional absences.")

    if missing:
        reasons.append(f"{missing} due assignment{'s are' if missing != 1 else ' is'} missing.")
        actions.append("Submit or discuss the oldest missing assignment first.")

    if performance is not None and performance_count >= 2:
        if performance < RISK_THRESHOLDS["critical_performance_percent"]:
            reasons.append(f"Average recorded performance is {performance}%, below 40%.")
            actions.append("Request a topic-level review using the lowest-scoring assessed work.")
        elif performance < RISK_THRESHOLDS["high_performance_percent"]:
            reasons.append(f"Average recorded performance is {performance}%, below 50%.")
            actions.append("Schedule targeted practice for the next assessed topic.")
        elif performance < RISK_THRESHOLDS["watch_performance_percent"]:
            reasons.append(f"Average recorded performance is {performance}%, below 60%.")
            actions.append("Use faculty-approved notes and complete one extra practice set this week.")

    evidence_count = attendance_held + performance_count + metrics["assignments"]["total"]
    if evidence_count == 0:
        return "insufficient_data", ["No attendance or assessment evidence is available yet."], [
            "Add real attendance or assessed work before making an academic intervention."
        ]

    critical = (
        (attendance_held >= 2 and attendance is not None and attendance < RISK_THRESHOLDS["critical_attendance_percent"])
        or missing >= RISK_THRESHOLDS["critical_missing_assignments"]
        or (performance_count >= 2 and performance is not None and performance < RISK_THRESHOLDS["critical_performance_percent"])
    )
    high = (
        (attendance_held >= 2 and attendance is not None and attendance < RISK_THRESHOLDS["attendance_target_percent"])
        or missing >= RISK_THRESHOLDS["high_missing_assignments"]
        or (performance_count >= 2 and performance is not None and performance < RISK_THRESHOLDS["high_performance_percent"])
    )
    watch = (
        (attendance is not None and attendance < RISK_THRESHOLDS["watch_attendance_percent"])
        or missing >= 1
        or (performance_count >= 2 and performance is not None and performance < RISK_THRESHOLDS["watch_performance_percent"])
    )
    level = "critical" if critical else "high" if high else "watch" if watch else "stable"
    if not reasons:
        reasons.append("No current threshold-based concern was found in the available records.")
        actions.append("Continue the current learning and attendance routine.")
    return level, reasons, list(dict.fromkeys(actions))


def _student_record(db: Session, student: User, courses: list[Course]) -> dict:
    course_metrics = [_course_metrics(db, student.id, course) for course in courses]
    combined = {
        "attendance": {
            "held": sum(item["attendance"]["held"] for item in course_metrics),
            "attended": sum(item["attendance"]["attended"] for item in course_metrics),
        },
        "assignments": {
            "total": sum(item["assignments"]["total"] for item in course_metrics),
            "submitted": sum(item["assignments"]["submitted"] for item in course_metrics),
            "graded": sum(item["assignments"]["graded"] for item in course_metrics),
            "missing_due": sum(item["assignments"]["missing_due"] for item in course_metrics),
        },
        "quizzes": {
            "total": sum(item["quizzes"]["total"] for item in course_metrics),
            "attempted": sum(item["quizzes"]["attempted"] for item in course_metrics),
        },
        "programming": {
            "total": sum(item["programming"]["total"] for item in course_metrics),
            "attempted": sum(item["programming"]["attempted"] for item in course_metrics),
        },
    }
    combined["attendance"]["percent"] = (
        round(100 * combined["attendance"]["attended"] / combined["attendance"]["held"], 1)
        if combined["attendance"]["held"] else None
    )
    performance_values: list[float] = []
    for item in course_metrics:
        for category in ("assignments", "quizzes", "programming"):
            value = item[category]["average_percent"]
            count_key = "graded" if category == "assignments" else "attempted"
            performance_values.extend([value] * item[category][count_key] if value is not None else [])
    combined["performance_average_percent"] = _average(performance_values)
    combined["performance_evidence_count"] = len(performance_values)
    risk_level, reasons, actions = _classify(combined)
    for item in course_metrics:
        item["risk_level"], item["risk_reasons"], item["recommended_actions"] = _classify(item)
    course_metrics.sort(key=lambda item: (RISK_ORDER[item["risk_level"]], item["course_code"]))
    return {
        "student_id": student.id,
        "student": student.name,
        "institutional_id": student.institutional_id,
        "department": student.department,
        "risk_level": risk_level,
        "risk_reasons": reasons,
        "recommended_actions": actions,
        "metrics": combined,
        "courses": course_metrics,
    }


def build_progress_insights(db: Session, user: User, course_id: int | None = None) -> dict:
    scoped_courses = courses_query(db, user).order_by(Course.code).all()
    selected_course = None
    if course_id is not None:
        selected_course = course_access(db, user, course_id)
        scoped_courses = [selected_course]

    if user.role == UserRole.student:
        students = [user]
        result_limited = False
    else:
        student_query = users_query(db, user).filter(User.role == UserRole.student)
        if selected_course:
            student_query = student_query.filter(User.id.in_(
                db.query(Enrollment.student_id).filter(Enrollment.course_id == selected_course.id)
            ))
        candidates = student_query.order_by(User.name).limit(251).all()
        result_limited = len(candidates) > 250
        students = candidates[:250]

    course_ids = {course.id for course in scoped_courses}
    records = []
    for student in students:
        if user.role == UserRole.student:
            student_courses = scoped_courses
        else:
            enrolled_ids = {row[0] for row in db.query(Enrollment.course_id).filter(
                Enrollment.student_id == student.id,
                Enrollment.course_id.in_(course_ids or [-1]),
            ).all()}
            student_courses = [course for course in scoped_courses if course.id in enrolled_ids]
        records.append(_student_record(db, student, student_courses))

    records.sort(key=lambda item: (RISK_ORDER[item["risk_level"]], item["student"].lower()))
    counts = {level: sum(item["risk_level"] == level for item in records) for level in RISK_ORDER}
    return {
        "stage": 5,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "role": user.role.value,
            "institution_id": tenant(user),
            "department": user.department if user.role == UserRole.hod else None,
            "course": ({"id": selected_course.id, "code": selected_course.code,
                        "name": selected_course.name} if selected_course else None),
            "maximum_students": 250,
            "result_limited": result_limited,
        },
        "summary": {"total_students": len(records), **counts},
        "thresholds": RISK_THRESHOLDS,
        "students": records,
        "data_basis": "Current EKEEKRTA attendance, due assignments, graded assignments, quizzes, and programming assessments.",
        "notice": "This is a transparent support indicator, not an official grade, diagnosis, or automatic decision.",
        "external_model": False,
    }
