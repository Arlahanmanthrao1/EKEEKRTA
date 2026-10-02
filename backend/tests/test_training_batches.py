"""Disposable coverage for training batch isolation and delivery workflows."""
import unittest
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models
from app.core.security import create_access_token
from app.database import Base, get_db
from app.models.course import Course
from app.models.institution import Department, Institution, InstitutionType
from app.models.training import TrainingBatchEnrollment
from app.models.user import User, UserRole
from app.routers import attendance, schedule, training


class TrainingBatchTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        institution = Institution(id=1, name="Skills Academy", email_domain="skills.example",
                                  institution_type=InstitutionType.training_institution.value)
        university = Institution(id=2, name="University", email_domain="university.example")
        self.db.add_all([institution, university]); self.db.flush()
        self.db.add(Department(institution_id=1, name="Software"))
        self.db.add_all([
            User(id=1, institution_id=1, name="Admin", email="admin@skills.example", role=UserRole.admin, hashed_password="x"),
            User(id=2, institution_id=1, name="Trainer", email="trainer@skills.example", role=UserRole.faculty, department="Software", hashed_password="x"),
            User(id=3, institution_id=1, name="Learner One", email="one@skills.example", role=UserRole.student, department="Software", institutional_id="L001", hashed_password="x"),
            User(id=4, institution_id=1, name="Learner Two", email="two@skills.example", role=UserRole.student, department="Software", institutional_id="L002", hashed_password="x"),
            User(id=5, institution_id=2, name="Other Admin", email="admin@university.example", role=UserRole.admin, hashed_password="x"),
        ]); self.db.flush()
        self.db.add(Course(id=1, institution_id=1, name="Full Stack", code="FS", department="Software", course_type="academic", enrollment_mode="elective"))
        self.db.commit()
        api = FastAPI()
        for module in (training, attendance, schedule): api.include_router(module.router)
        api.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(api)
        self.addCleanup(self.client.close); self.addCleanup(self.db.close); self.addCleanup(self.engine.dispose)

    def request(self, method, path, user=1, **kwargs):
        token = create_access_token({"sub": str(user)})
        return self.client.request(method, path, headers={"Authorization": f"Bearer {token}"}, **kwargs)

    def create_batch(self):
        response = self.request("POST", "/training/batches", json={
            "course_id": 1, "trainer_id": 2, "name": "October Morning", "code": "FS-OCT-A",
            "start_date": "2026-10-01", "end_date": "2026-12-01", "capacity": 1,
            "certificate_min_progress": 0, "certificate_min_attendance": 0,
        })
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_batch_capacity_modules_progress_and_certificate(self):
        batch = self.create_batch()
        self.assertEqual(self.request("POST", f"/training/batches/{batch['id']}/learners", json={"student_id": 3}).status_code, 201)
        self.assertEqual(self.request("POST", f"/training/batches/{batch['id']}/learners", json={"student_id": 4}).status_code, 409)
        module = self.request("POST", f"/training/batches/{batch['id']}/modules", user=2,
                              json={"title": "Foundations", "published": True}).json()
        lesson = self.request("POST", f"/training/modules/{module['id']}/lessons", user=2,
                              json={"title": "Environment setup"}).json()
        self.assertEqual(self.request("POST", f"/training/lessons/{lesson['id']}/complete", user=3).status_code, 201)
        completed = self.request("PATCH", f"/training/batches/{batch['id']}", json={"status": "completed"})
        self.assertEqual(completed.status_code, 200, completed.text)
        certificate = self.request("POST", f"/training/batches/{batch['id']}/certificates/3", user=2)
        self.assertEqual(certificate.status_code, 201, certificate.text)
        self.assertTrue(certificate.json()["certificate_number"].startswith("EKT-"))

    def test_sessions_require_explicit_batch_membership(self):
        batch = self.create_batch()
        self.request("POST", f"/training/batches/{batch['id']}/learners", json={"student_id": 3})
        session = self.request("POST", "/attendance/sessions", user=2,
                               json={"course_id": 1, "training_batch_id": batch["id"]})
        self.assertEqual(session.status_code, 201, session.text)
        self.assertEqual(session.json()["training_batch_id"], batch["id"])
        self.assertEqual(self.request("GET", f"/attendance/sessions/detail/{session.json()['id']}", user=3).status_code, 200)
        self.assertIn(self.request("GET", f"/attendance/sessions/detail/{session.json()['id']}", user=4).status_code, (403, 404))

    def test_trainer_schedule_is_batch_scoped(self):
        batch = self.create_batch()
        start = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        response = self.request("POST", "/schedule", user=2, json={
            "course_id": 1, "training_batch_id": batch["id"], "title": "API workshop", "starts_at": start,
        })
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["training_batch_id"], batch["id"])

    def test_university_cannot_open_training_workspace(self):
        self.assertEqual(self.request("GET", "/training/batches", user=5).status_code, 404)


if __name__ == "__main__":
    unittest.main()
