"""Isolated enrollment tests; no production or local application database is used."""
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models
from app.core.security import create_access_token
from app.database import Base, get_db
from app.models.user import User, UserRole
from app.models.institution import Institution, Department
from app.models.course import Course, Enrollment
from app.models.assignment import Assignment, Submission
from app.models.attendance import Attendance, ClassSession
from app.models.quiz import Quiz, QuizAttempt
from app.routers.courses import router
from app.routers.users import router as users_router


class CourseEnrollmentTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.db.add(Institution(id=1, name="Isolated test institution", email_domain="college.edu"))
        self.db.flush()
        self.db.add(Department(institution_id=1, name="CS"))
        self.db.commit()
        for ident, role in [(1, UserRole.faculty), (2, UserRole.faculty), (3, UserRole.student),
                            (4, UserRole.student), (5, UserRole.hod), (6, UserRole.admin)]:
            self.db.add(User(institution_id=1, id=ident, name=f"Test {ident}", email=f"test{ident}@hitam.org", role=role,
                             department="CS" if role != UserRole.admin else None, hashed_password="unused",
                             program="B.Tech CS" if role == UserRole.student else None,
                             batch="2026-2030" if role == UserRole.student else None,
                             semester_number=3 if ident == 3 else 4 if ident == 4 else None,
                             section="A" if role == UserRole.student else None))
        self.db.flush()
        self.db.add_all([Course(institution_id=1, id=10, name="Owned", code="OWN", faculty_id=1),
                         Course(institution_id=1, id=20, name="Other", code="OTHER", faculty_id=2)])
        self.db.flush()
        self.db.add_all([Enrollment(student_id=3, course_id=10), Enrollment(student_id=4, course_id=10),
                         Enrollment(student_id=3, course_id=20)])
        self.db.add_all([Assignment(id=10, course_id=10, title="Work"), Quiz(id=10, course_id=10, title="Quiz"),
                         ClassSession(id=10, course_id=10, jitsi_room_id="test-history")])
        self.db.flush()
        self.db.add_all([Submission(assignment_id=10, student_id=3, marks_obtained=85, file_url="https://example.com/test"),
                         QuizAttempt(quiz_id=10, student_id=3, score=90),
                         Attendance(session_id=10, student_id=3, duration_minutes=45, present=True)])
        self.db.commit()
        api = FastAPI()
        api.include_router(router)
        api.include_router(users_router)
        api.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(api)
        self.client.headers.update(self.auth(1))

    def auth(self, ident):
        return {"Authorization": "Bearer " + create_access_token({"sub": str(ident)})}

    def tearDown(self):
        self.client.close()
        self.db.close()
        self.engine.dispose()

    def test_roster_contains_only_enrolled_students_and_safe_fields(self):
        result = self.client.get("/courses/10/students")
        self.assertEqual(result.status_code, 200)
        self.assertEqual([row["id"] for row in result.json()], [3, 4])
        self.assertNotIn("password", result.text)
        self.assertNotIn("hashed_password", result.text)

    def test_removal_preserves_account_other_enrollments_and_history(self):
        result = self.client.delete("/courses/10/students/3")
        self.assertEqual(result.status_code, 204, result.text)
        self.assertEqual(result.content, b"")
        self.assertEqual(self.db.query(User).count(), 6)
        self.assertEqual(self.db.query(Course).count(), 2)
        self.assertEqual(self.db.query(Enrollment).count(), 2)
        self.assertEqual([row["id"] for row in self.client.get("/courses/10/students").json()], [4])
        self.assertEqual([row["id"] for row in self.client.get("/courses/enrolled", headers=self.auth(3)).json()], [20])
        self.assertEqual(self.db.query(Submission).one().marks_obtained, 85)
        self.assertEqual(self.db.query(QuizAttempt).one().score, 90)
        history = self.db.query(Attendance).one()
        self.assertEqual(history.duration_minutes, 45)
        self.assertTrue(history.present)

    def test_other_faculty_cannot_list_or_remove(self):
        for method, url in [("get", "/courses/10/students"), ("delete", "/courses/10/students/3")]:
            self.assertEqual(getattr(self.client, method)(url, headers=self.auth(2)).status_code, 403)
        self.assertEqual(self.db.query(Enrollment).count(), 3)

    def test_anonymous_and_non_faculty_are_denied(self):
        for method, url in [("get", "/courses/10/students"), ("delete", "/courses/10/students/3")]:
            self.assertEqual(getattr(self.client, method)(url, headers={"Authorization": ""}).status_code, 401)
            for ident in [3, 5, 6]:
                self.assertEqual(getattr(self.client, method)(url, headers=self.auth(ident)).status_code, 403)
        self.assertEqual(self.db.query(Enrollment).count(), 3)

    def test_missing_course_or_enrollment(self):
        self.assertEqual(self.client.get("/courses/999/students").status_code, 404)
        self.assertEqual(self.client.delete("/courses/999/students/3").status_code, 404)
        self.assertEqual(self.client.delete("/courses/10/students/999").status_code, 404)
        self.assertEqual(self.client.delete("/courses/10/students/1").status_code, 404)
        self.assertEqual(self.db.query(Enrollment).count(), 3)

    def test_repeated_removal_and_reenrollment(self):
        self.assertEqual(self.client.delete("/courses/10/students/3").status_code, 204)
        self.assertEqual(self.client.delete("/courses/10/students/3").status_code, 404)
        self.assertEqual(self.client.post("/courses/10/enroll", headers=self.auth(3)).status_code, 201)
        self.assertEqual(self.db.query(Enrollment).count(), 3)
        self.assertEqual(self.db.query(Submission).count(), 1)

    def test_legacy_duplicate_enrollments_are_removed_together(self):
        self.db.add(Enrollment(student_id=3, course_id=10))
        self.db.commit()
        self.assertEqual(len(self.client.get("/courses/10/students").json()), 2)
        self.assertEqual(self.client.delete("/courses/10/students/3").status_code, 204)
        self.assertEqual(self.db.query(Enrollment).count(), 2)

    def test_compulsory_course_auto_enrolls_only_matching_cohort(self):
        response = self.client.post("/courses/", json={"name":"Cohort course","code":"COH301","department":"CS",
            "course_type":"academic","program":"B.Tech CS","batch":"2026-2030","semester_number":3,
            "section":"A","enrollment_mode":"compulsory"})
        self.assertEqual(response.status_code,201,response.text)
        course_id=response.json()["id"]
        enrolled = [row[0] for row in self.db.query(Enrollment.student_id).filter(Enrollment.course_id==course_id).all()]
        self.assertEqual(enrolled,[3])

    def test_elective_catalog_and_enrollment_are_cohort_restricted(self):
        matching=Course(institution_id=1,name="Matching elective",code="EL301",faculty_id=1,department="CS",
                        program="B.Tech CS",batch="2026-2030",semester_number=3,section="A",enrollment_mode="elective")
        other=Course(institution_id=1,name="Other semester",code="EL401",faculty_id=1,department="CS",
                     program="B.Tech CS",batch="2026-2030",semester_number=4,section="A",enrollment_mode="elective")
        self.db.add_all([matching,other]);self.db.commit()
        catalog=self.client.get("/courses/",headers=self.auth(3))
        self.assertIn(matching.id,[entry["id"] for entry in catalog.json()])
        self.assertNotIn(other.id,[entry["id"] for entry in catalog.json()])
        self.assertEqual(self.client.post(f"/courses/{matching.id}/enroll",headers=self.auth(3)).status_code,201)
        self.assertEqual(self.client.post(f"/courses/{other.id}/enroll",headers=self.auth(3)).status_code,403)

    def test_admin_promotion_preserves_history_and_adds_next_compulsory_course(self):
        next_course=Course(institution_id=1,name="Next semester",code="NEXT401",faculty_id=1,department="CS",
                           program="B.Tech CS",batch="2026-2030",semester_number=4,section="A",enrollment_mode="compulsory")
        self.db.add(next_course);self.db.commit()
        response=self.client.post("/users/students/promote",headers=self.auth(6),json={"department":"CS","program":"B.Tech CS",
            "batch":"2026-2030","from_semester":3,"to_semester":4})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()["promoted_count"],1)
        self.assertEqual(self.db.get(User,3).semester_number,4)
        self.assertIsNotNone(self.db.query(Enrollment).filter_by(student_id=3,course_id=next_course.id).first())
        self.assertIsNotNone(self.db.query(Enrollment).filter_by(student_id=3,course_id=10).first())


if __name__ == "__main__":
    unittest.main()
