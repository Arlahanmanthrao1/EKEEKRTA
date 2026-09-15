"""Cohort matching and automatic enrollment without removing course history."""
from sqlalchemy.orm import Session

from app.models.course import Course, Enrollment
from app.models.user import User, UserRole


def _same(left, right):
    return (left or "").strip().casefold() == (right or "").strip().casefold()


def student_matches_course(student: User, course: Course) -> bool:
    """A populated course target is mandatory; blank targets mean all values."""
    if student.role != UserRole.student or student.institution_id != course.institution_id:
        return False
    for attribute in ("department", "program", "batch", "section"):
        target = getattr(course, attribute, None)
        if target and not _same(getattr(student, attribute, None), target):
            return False
    return course.semester_number is None or student.semester_number == course.semester_number


def enroll_student_if_needed(db: Session, student: User, course: Course) -> bool:
    if not student_matches_course(student, course):
        return False
    exists = db.query(Enrollment.id).filter(
        Enrollment.student_id == student.id, Enrollment.course_id == course.id
    ).first()
    if exists:
        return False
    db.add(Enrollment(student_id=student.id, course_id=course.id))
    return True


def enroll_matching_students(db: Session, course: Course) -> int:
    if course.enrollment_mode != "compulsory":
        return 0
    students = db.query(User).filter(
        User.institution_id == course.institution_id, User.role == UserRole.student
    ).all()
    return sum(enroll_student_if_needed(db, student, course) for student in students)


def enroll_matching_compulsory_courses(db: Session, student: User) -> int:
    courses = db.query(Course).filter(
        Course.institution_id == student.institution_id, Course.enrollment_mode == "compulsory"
    ).all()
    return sum(enroll_student_if_needed(db, student, course) for course in courses)
