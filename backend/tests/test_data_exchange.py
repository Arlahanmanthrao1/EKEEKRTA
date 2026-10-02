"""University Data Exchange tests use only a disposable in-memory database."""
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.core.security import create_access_token
from app.database import Base, get_db
from app.models import (Assignment, Attendance, ClassSession, Course, Enrollment,
                        Quiz, QuizAttempt, Submission, User, UserRole)
from app.models.data_exchange import DataExchangeProfile
from app.models.institution import Institution, InstitutionType
from app.routers import data_exchange


class DataExchangeTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.db.add_all([
            Institution(id=1, name="Test University", email_domain="university.test",
                        institution_type=InstitutionType.university.value),
            Institution(id=2, name="Test Training", email_domain="training.test",
                        institution_type=InstitutionType.training_institution.value),
        ])
        self.db.flush()
        self.db.add_all([
            User(id=1, institution_id=1, name="Faculty One", email="faculty1@university.test",
                 hashed_password="unused", role=UserRole.faculty, department="CSE"),
            User(id=2, institution_id=1, name="Student One", email="student1@university.test",
                 hashed_password="unused", role=UserRole.student, department="CSE", program="B.Tech",
                 batch="2024-2028", semester_number=5, section="A", institutional_id="24CSE001"),
            User(id=3, institution_id=1, name="Faculty Two", email="faculty2@university.test",
                 hashed_password="unused", role=UserRole.faculty, department="CSE"),
            User(id=4, institution_id=2, name="Trainer", email="trainer@training.test",
                 hashed_password="unused", role=UserRole.faculty, department="Cloud"),
        ])
        self.db.flush()
        self.db.add_all([
            Course(id=1, institution_id=1, name="Operating Systems", code="CS501",
                   department="CSE", faculty_id=1),
            Course(id=2, institution_id=1, name="Networks", code="CS502",
                   department="CSE", faculty_id=3),
            Course(id=3, institution_id=2, name="Cloud Training", code="CT101",
                   department="Cloud", faculty_id=4),
        ])
        self.db.flush()
        self.db.add(Enrollment(student_id=2, course_id=1))
        session = ClassSession(id=1, course_id=1, jitsi_room_id="data-exchange-room")
        assignment = Assignment(id=1, course_id=1, title="Processes", max_marks=20)
        quiz = Quiz(id=1, course_id=1, title="Scheduling", total_marks=10)
        self.db.add_all([session, assignment, quiz])
        self.db.flush()
        self.db.add_all([
            Attendance(session_id=1, student_id=2, duration_minutes=42, present=True),
            Submission(assignment_id=1, student_id=2, file_url="https://example.test/work", marks_obtained=18),
            QuizAttempt(quiz_id=1, student_id=2, score=8),
        ])
        self.db.commit()

        api = FastAPI()
        api.include_router(data_exchange.router)
        api.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(api)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        self.addCleanup(self.client.close)

    def request(self, method, path, user, **kwargs):
        token = create_access_token({"sub": str(user)})
        return self.client.request(method, path, headers={"Authorization": f"Bearer {token}"}, **kwargs)

    @staticmethod
    def profile_payload(name="Exam portal"):
        return {
            "name": name,
            "target_platform": "University Exam Portal",
            "data_type": "roster",
            "template_headers": ["ROLL NO", "STUDENT NAME", "SUBJECT CODE"],
            "mapping": {
                "ROLL NO": {"source": "institutional_id", "transform": "uppercase"},
                "STUDENT NAME": {"source": "student_name", "transform": "uppercase"},
                "SUBJECT CODE": {"source": "course_code", "transform": "none"},
            },
        }

    def test_faculty_exports_only_an_assigned_university_course(self):
        roster = self.request("GET", "/data-exchange/source/roster?course_id=1", 1)
        self.assertEqual(roster.status_code, 200, roster.text)
        self.assertEqual(roster.json()["record_count"], 1)
        self.assertEqual(roster.json()["records"][0]["institutional_id"], "24CSE001")
        for dataset in ["attendance", "assignment_marks", "quiz_scores"]:
            response = self.request("GET", f"/data-exchange/source/{dataset}?course_id=1", 1)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["record_count"], 1)
        self.assertEqual(
            self.request("GET", "/data-exchange/source/roster?course_id=2", 1).status_code, 403)

    def test_training_institutions_cannot_use_data_exchange(self):
        self.assertEqual(self.request("GET", "/data-exchange/profiles", 4).status_code, 404)
        self.assertEqual(
            self.request("GET", "/data-exchange/source/roster?course_id=3", 4).status_code, 404)
        self.assertEqual(
            self.request("POST", "/data-exchange/profiles", 4,
                         json=self.profile_payload()).status_code, 404)

    def test_mapping_profiles_are_private_validated_and_reusable(self):
        created = self.request("POST", "/data-exchange/profiles", 1,
                               json=self.profile_payload())
        self.assertEqual(created.status_code, 201, created.text)
        profile_id = created.json()["id"]
        self.assertEqual(self.request("GET", "/data-exchange/profiles", 3).json(), [])
        self.assertEqual(
            self.request("POST", f"/data-exchange/profiles/{profile_id}/used", 3).status_code, 404)

        updated_payload = self.profile_payload("Updated exam portal")
        updated_payload["mapping"]["STUDENT NAME"]["transform"] = "lowercase"
        updated = self.request("PUT", f"/data-exchange/profiles/{profile_id}", 1,
                               json=updated_payload)
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["name"], "Updated exam portal")
        used = self.request("POST", f"/data-exchange/profiles/{profile_id}/used", 1)
        self.assertEqual(used.status_code, 200, used.text)
        self.assertEqual(used.json()["export_count"], 1)

        invalid = self.profile_payload("Invalid")
        invalid["mapping"]["ROLL NO"]["source"] = "private_field"
        self.assertEqual(
            self.request("POST", "/data-exchange/profiles", 1, json=invalid).status_code, 422)
        missing_mapping = self.profile_payload("Missing")
        del missing_mapping["mapping"]["SUBJECT CODE"]
        self.assertEqual(
            self.request("POST", "/data-exchange/profiles", 1, json=missing_mapping).status_code, 422)

        self.assertEqual(
            self.request("DELETE", f"/data-exchange/profiles/{profile_id}", 1).status_code, 204)
        self.assertIsNone(self.db.get(DataExchangeProfile, profile_id))


if __name__ == "__main__":
    unittest.main()
