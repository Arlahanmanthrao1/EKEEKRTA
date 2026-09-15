"""Shared, fail-closed institution and role boundaries for every API."""
from fastapi import HTTPException
from sqlalchemy import func, false, or_
from app.models.user import User, UserRole
from app.models.course import Course, Enrollment
from app.models.institution import Department


def tenant(user):
    if not user.institution_id or user.institution is None:
        raise HTTPException(403, "Your account needs institution setup. Contact your administrator.")
    return user.institution_id


def department_name(db, user, value):
    if not value or not value.strip():
        raise HTTPException(422, "Select a department created by your administrator")
    department = db.query(Department).filter(
        Department.institution_id == tenant(user),
        func.lower(Department.name) == value.strip().lower(),
    ).first()
    if not department:
        raise HTTPException(422, "Department does not belong to your institution")
    return department.name


def courses_query(db, user, catalog=False):
    query = db.query(Course).filter(Course.institution_id == tenant(user))
    if user.role == UserRole.faculty:
        query = query.filter(Course.faculty_id == user.id)
    elif user.role == UserRole.hod:
        query = query.filter(Course.department == user.department) if user.department else query.filter(false())
    elif user.role == UserRole.student:
        if catalog:
            query = query.filter(
                or_(Course.department.is_(None), func.lower(Course.department) == (user.department or "").lower()),
                or_(Course.program.is_(None), func.lower(Course.program) == (user.program or "").lower()),
                or_(Course.batch.is_(None), func.lower(Course.batch) == (user.batch or "").lower()),
                or_(Course.section.is_(None), func.lower(Course.section) == (user.section or "").lower()),
                or_(Course.semester_number.is_(None), Course.semester_number == user.semester_number),
            )
        else:
            query = query.filter(Course.id.in_(db.query(Enrollment.course_id).filter(Enrollment.student_id == user.id)))
    return query


def course_access(db, user, course_id, manage=False, catalog=False):
    course = db.query(Course).filter(Course.id == course_id, Course.institution_id == tenant(user)).first()
    if not course:
        raise HTTPException(404, "Course not found")
    if manage:
        allowed = user.role == UserRole.admin or (user.role == UserRole.faculty and course.faculty_id == user.id)
    else:
        allowed = courses_query(db, user, catalog).filter(Course.id == course_id).first() is not None
    if not allowed:
        raise HTTPException(403, "You do not have access to this course")
    return course


def users_query(db, user):
    query = db.query(User).filter(User.institution_id == tenant(user))
    if user.role == UserRole.hod:
        query = query.filter(User.role.in_([UserRole.faculty, UserRole.student]))
        query = query.filter(User.department == user.department) if user.department else query.filter(false())
    elif user.role == UserRole.faculty:
        query = query.filter(User.role == UserRole.student, User.id.in_(
            db.query(Enrollment.student_id).join(Course).filter(
                Course.faculty_id == user.id, Course.institution_id == tenant(user))))
    elif user.role == UserRole.student:
        query = query.filter(User.id == user.id)
    return query


def student_access(db, user, student_id):
    student = users_query(db, user).filter(User.id == student_id, User.role == UserRole.student).first()
    if not student:
        raise HTTPException(404, "Student not found in your access scope")
    return student


def resource_access(db, user, model, resource_id, manage=False):
    resource = db.get(model, resource_id)
    if not resource:
        raise HTTPException(404, "Resource not found")
    course_access(db, user, resource.course_id, manage=manage)
    return resource
