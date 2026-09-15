"""Registration tests use only a disposable in-memory database."""
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models
from app.config import settings
from app.database import Base, get_db
from app.models.user import User, UserRole
from app.models.institution import Institution, Department
from app.models.erp import ERPIntegration
from app.core.security import verify_password, hash_password, create_access_token
from app.routers.auth import router
from app.routers.courses import router as courses_router


class RegistrationTest(unittest.TestCase):
    endpoint = "/auth/register"
    expected_role = "student"

    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.db.add(Institution(id=1, name="Isolated test institution", email_domain="college.edu"))
        self.db.flush()
        self.db.add(Department(institution_id=1, name="CS"))
        self.db.commit()
        api = FastAPI()
        api.include_router(router)
        api.include_router(courses_router)
        api.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(api)
        self.db.add(User(institution_id=1, id=100, name="Test Admin", email="admin@college.edu", hashed_password="unused", role=UserRole.admin))
        self.db.commit()
        self.client.headers["Authorization"] = "Bearer " + create_access_token({"sub": "100"})
        p = patch.object(settings, "allowed_email_domain", "college.edu")
        p.start()
        self.addCleanup(p.stop)
        self.payload = dict(name=" Test Student ", email="test@college.edu", password="Test-password-123", department=" CS ",
                            institutional_id="TEST-001", program="B.Tech CS", batch="2026-2030", semester_number=1, section="A")

    def tearDown(self):
        self.client.close()
        self.db.close()
        self.engine.dispose()

    def test_register_and_login(self):
        response = self.client.post(self.endpoint, json=self.payload)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["role"], self.expected_role)
        self.assertNotIn("password", response.text)
        user = self.db.query(User).filter(User.email == self.payload["email"]).one()
        self.assertEqual(user.name, "Test Student")
        self.assertEqual(user.department, "CS")
        self.assertTrue(verify_password(self.payload["password"], user.hashed_password))
        login = self.client.post("/auth/login", data={"username": "TEST@COLLEGE.EDU", "password": self.payload["password"]})
        self.assertEqual(login.status_code, 200, login.text)
        self.assertIn("access_token", login.json())

    def test_temporary_official_id_password_must_be_changed(self):
        user = User(institution_id=1, name="Imported Student", email="imported@college.edu",
                    institutional_id="ERP-001", role=UserRole.student,
                    hashed_password=hash_password("ERP-001"),
                    must_change_password=True, erp_password_initialized=True)
        self.db.add(user); self.db.commit()
        login = self.client.post("/auth/login", data={"username": user.email, "password": "ERP-001"}, headers={"Authorization": ""})
        self.assertEqual(login.status_code, 200, login.text)
        headers = {"Authorization": "Bearer " + login.json()["access_token"]}
        profile = self.client.get("/auth/me", headers=headers)
        self.assertTrue(profile.json()["must_change_password"])
        self.assertEqual(self.client.get("/courses/", headers=headers).status_code, 403)
        self.assertEqual(self.client.post("/auth/change-password", headers=headers,
                                         json={"current_password": "wrong", "new_password": "new-secure-password"}).status_code, 400)
        self.assertEqual(self.client.post("/auth/change-password", headers=headers,
                                         json={"current_password": "ERP-001", "new_password": "ERP-001"}).status_code, 422)
        changed = self.client.post("/auth/change-password", headers=headers,
                                   json={"current_password": "ERP-001", "new_password": "new-secure-password"})
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertFalse(self.db.get(User, user.id).must_change_password)
        self.assertEqual(self.client.post("/auth/login", data={"username": user.email, "password": "ERP-001"}, headers={"Authorization": ""}).status_code, 401)
        self.assertEqual(self.client.post("/auth/login", data={"username": user.email, "password": "new-secure-password"}, headers={"Authorization": ""}).status_code, 200)

    def test_roles_cannot_be_requested(self):
        for role in ["student", "faculty", "hod", "admin"]:
            response = self.client.post(self.endpoint, json={**self.payload, "role": role})
            self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.db.query(User).count(), 1)

    def test_duplicate_email_case_insensitive(self):
        self.assertEqual(self.client.post(self.endpoint, json=self.payload).status_code, 201)
        response = self.client.post(self.endpoint, json={**self.payload, "email": "TEST@COLLEGE.EDU"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.db.query(User).count(), 2)

    def test_duplicate_registration_number_is_rejected(self):
        self.assertEqual(self.client.post(self.endpoint, json=self.payload).status_code, 201)
        response = self.client.post(self.endpoint, json={**self.payload, "email": "other@college.edu"})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("Official institution ID", response.json()["detail"])

    def test_reject_wrong_domain_and_invalid_fields(self):
        for invalid in [{"email": "test@example.com"}, {"email": "test@evilcollege.edu"},
                        {"password": "short"}, {"password": "a" * 73}, {"password": "é" * 37},
                        {"name": "   "}, {"confirmPassword": "extra-field"}]:
            self.assertEqual(self.client.post(self.endpoint, json={**self.payload, **invalid}).status_code, 422)
        self.assertEqual(self.db.query(User).count(), 1)

    def test_existing_staff_login_unchanged(self):
        self.client.post(self.endpoint, json=self.payload)
        user = self.db.query(User).filter(User.email == self.payload["email"]).one()
        user.role = UserRole.faculty
        self.db.commit()
        response = self.client.post("/auth/login", data={"username": self.payload["email"], "password": self.payload["password"]})
        self.assertEqual(response.status_code, 200)
        me = self.client.get("/auth/me", headers={"Authorization": "Bearer " + response.json()["access_token"]})
        self.assertEqual(me.json()["role"], "faculty")

    def test_hitam_domain_policy(self):
        self.db.get(Institution, 1).email_domain = "hitam.org"
        self.db.commit()
        with patch.object(settings, "allowed_email_domain", "unused.example"):
            accepted = self.client.post(self.endpoint, json={**self.payload, "email": "test@HITAM.ORG"})
            self.assertEqual(accepted.status_code, 201, accepted.text)
            self.assertEqual(accepted.json()["email"], "test@hitam.org")
            for email in ["test@college.edu", "test@fakehitam.org", "test@hitam.org.example.com"]:
                self.assertEqual(self.client.post(self.endpoint, json={**self.payload, "email": email}).status_code, 422)

    def test_anonymous_and_non_admin_cannot_register(self):
        response = self.client.post(self.endpoint, json=self.payload, headers={"Authorization": ""})
        self.assertEqual(response.status_code, 401)
        for ident, role in [(101, UserRole.student), (102, UserRole.faculty), (103, UserRole.hod)]:
            self.db.add(User(institution_id=1, id=ident, name="Denied User", email=f"denied{ident}@college.edu", hashed_password="unused", role=role))
            self.db.commit()
            token = create_access_token({"sub": str(ident)})
            response = self.client.post(self.endpoint, json=self.payload, headers={"Authorization": "Bearer " + token})
            self.assertEqual(response.status_code, 403)
        self.assertIsNone(self.db.query(User).filter(User.email == self.payload["email"]).first())

    def test_admin_can_register_student_when_erp_import_is_enabled(self):
        self.db.add(ERPIntegration(institution_id=1, base_url="https://erp.college.edu",
                                   encrypted_api_token="encrypted-test-value", enabled=True,
                                   sync_students=True, sync_courses=True, sync_attendance=True))
        self.db.commit()
        response = self.client.post(self.endpoint, json=self.payload)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["institutional_id"], "TEST-001")


class FacultyRegistrationTest(RegistrationTest):
    endpoint = "/auth/register-faculty"
    expected_role = "faculty"

    def test_cannot_reuse_student_email(self):
        self.assertEqual(self.client.post("/auth/register", json=self.payload).status_code, 201)
        response = self.client.post(self.endpoint, json={**self.payload, "email": "TEST@COLLEGE.EDU"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.db.query(User).filter(User.email == self.payload["email"]).one().role, UserRole.student)

    def test_new_faculty_can_login_and_create_course(self):
        created = self.client.post(self.endpoint, json=self.payload)
        self.assertEqual(created.status_code, 201)
        login = self.client.post("/auth/login", data={"username": self.payload["email"], "password": self.payload["password"]})
        self.assertEqual(login.status_code, 200)
        headers = {"Authorization": "Bearer " + login.json()["access_token"]}
        self.assertEqual(self.client.get("/auth/me", headers=headers).json()["role"], "faculty")
        course = self.client.post("/courses/", headers=headers, json={"name": "Test Course", "code": "TEST101", "department": "CS",
                                                                       "program": "B.Tech CS", "batch": "2026-2030", "semester_number": 1})
        self.assertEqual(course.status_code, 201, course.text)
        self.assertEqual(course.json()["faculty_id"], created.json()["id"])
        self.assertEqual(course.json()["course_type"], "academic")


if __name__ == "__main__":
    unittest.main()
