"""Sandbox ERP tests use only disposable in-memory records."""

import unittest

from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models import AcademicResult, AttendanceRecord, Course, Student, SyncReceipt


class ERPSandboxTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        app.dependency_overrides[get_db] = lambda: self.db
        self.old_token, self.old_institution = settings.erp_api_token, settings.erp_institution_id
        settings.erp_api_token = SecretStr("isolated-sandbox-token-123456")
        settings.erp_institution_id = "ALPHA"
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.db.close()
        self.engine.dispose()
        app.dependency_overrides.clear()
        settings.erp_api_token, settings.erp_institution_id = self.old_token, self.old_institution

    @property
    def auth(self):
        return {"Authorization": "Bearer isolated-sandbox-token-123456"}

    def post(self, path, payload, key, headers=None):
        return self.client.post(path, json=payload, headers={**self.auth, "Idempotency-Key": key, **(headers or {})})

    def institution(self, external_id="ALPHA"):
        return {"ekeekrta_id": 1, "external_id": external_id, "name": "Alpha College", "email_domain": "alpha.edu"}

    def student(self, semester=1):
        return {"event": "student.upsert", "institution": self.institution(),
                "student": {"ekeekrta_id": 10, "institutional_id": "A-001", "name": "Test Student",
                            "email": "student@alpha.edu", "department": "CS", "program": "B.Tech",
                            "batch": "2026-2030", "semester_number": semester, "section": "A"},
                "occurred_at": "2026-09-05T10:00:00Z"}

    def course(self):
        return {"event": "course.upsert", "institution": self.institution(),
                "course": {"ekeekrta_id": 20, "code": "CS101", "name": "Test Course", "department": "CS",
                           "course_type": "academic", "program": "B.Tech", "batch": "2026-2030",
                           "semester_number": 1, "section": "A", "enrollment_mode": "compulsory",
                           "faculty": {"ekeekrta_id": 3, "institutional_id": "EMP-3", "name": "Test Faculty",
                                       "email": "faculty@alpha.edu"}},
                "occurred_at": "2026-09-05T10:00:00Z"}

    def attendance(self, minutes=35):
        return {"event": "attendance.upsert", "institution": self.institution(),
                "student": {"ekeekrta_id": 10, "institutional_id": "A-001", "name": "Test Student",
                            "email": "student@alpha.edu"},
                "course": {"ekeekrta_id": 20, "code": "CS101", "name": "Test Course"},
                "class_session": {"ekeekrta_id": 30, "scheduled_at": "2026-09-05T09:00:00Z", "ended_at": None},
                "attendance": {"ekeekrta_id": 40, "duration_minutes": minutes, "present": minutes >= 30},
                "occurred_at": "2026-09-05T10:00:00Z"}

    def test_authentication_health_and_institution_scope(self):
        self.assertEqual(self.client.get("/api/ekeekrta/health").status_code, 401)
        self.assertEqual(self.client.get("/api/ekeekrta/health", headers=self.auth).status_code, 200)
        wrong = self.student(); wrong["institution"] = self.institution("BETA")
        self.assertEqual(self.post("/api/ekeekrta/students/sync", wrong, "wrong-1").status_code, 403)
        self.assertEqual(self.db.query(Student).count(), 0)

    def test_real_records_upsert_and_idempotency_revision(self):
        first = self.post("/api/ekeekrta/students/sync", self.student(), "student-1-1")
        self.assertEqual(first.status_code, 200, first.text)
        # Replaying the same delivery is harmless and does not apply changed content.
        self.assertEqual(self.post("/api/ekeekrta/students/sync", self.student(2), "student-1-1").json()["status"], "already_synced")
        self.assertEqual(self.db.query(Student).one().semester_number, 1)
        # A new record revision updates the same official ERP student.
        self.assertEqual(self.post("/api/ekeekrta/students/sync", self.student(2), "student-1-2").status_code, 200)
        self.assertEqual(self.db.query(Student).count(), 1)
        self.assertEqual(self.db.query(Student).one().semester_number, 2)
        self.assertEqual(self.post("/api/ekeekrta/courses/sync", self.course(), "course-1-1").status_code, 200)
        self.assertEqual(self.db.query(Course).one().faculty_institutional_id, "EMP-3")
        self.assertEqual(self.post("/api/ekeekrta/attendance/sync", self.attendance(15), "attendance-1-1").status_code, 200)
        self.assertEqual(self.post("/api/ekeekrta/attendance/sync", self.attendance(45), "attendance-1-2").status_code, 200)
        record = self.db.query(AttendanceRecord).one()
        self.assertEqual(record.duration_minutes, 45)
        self.assertTrue(record.present)
        self.assertEqual(self.db.query(SyncReceipt).count(), 5)

    def test_dashboard_is_protected_and_contains_only_synced_data(self):
        self.post("/api/ekeekrta/students/sync", self.student(), "student-dash-1")
        self.assertEqual(self.client.get("/api/dashboard").status_code, 401)
        response = self.client.get("/api/dashboard", headers=self.auth)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["counts"], {"users": 1, "students": 1, "faculty": 0,
                                                     "hod": 0, "courses": 0, "attendance": 0, "results": 0})
        self.assertNotIn("isolated-sandbox-token", response.text)
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("ERP Sandbox", page.text)
        self.assertIn("HYDERABAD INSTITUTE OF TECHNOLOGY", page.text)
        self.assertIn("ACADEMIC REGISTER", page.text)
        self.assertIn("STUDENT ATTENDANCE", page.text)
        self.assertIn("ADD USER", page.text)
        self.assertIn("USER DIRECTORY", page.text)
        self.assertIn("'add-user','results'", page.text)
        self.assertIn("No sample records are generated", page.text)
        self.assertNotIn("Aisha Khan", page.text)

    def test_erp_student_entry_is_exported_to_ekeekrta(self):
        payload = {"institutional_id": "A-009", "name": "ERP Student", "email": "erp.student@alpha.edu",
                   "department": "CS", "program": "B.Tech", "batch": "2026-2030",
                   "semester_number": 1, "section": "A"}
        self.assertEqual(self.client.post("/api/students", headers=self.auth, json=payload).status_code, 201)
        self.assertEqual(self.db.query(Student).one().ekeekrta_id, 0)
        self.assertEqual(self.client.get("/api/ekeekrta/students").status_code, 401)
        exported = self.client.get("/api/ekeekrta/students", headers=self.auth)
        self.assertEqual(exported.status_code, 200, exported.text)
        self.assertEqual(exported.json()["institution_id"], "ALPHA")
        self.assertEqual(exported.json()["students"], [payload])

    def test_erp_directory_exports_users_by_role_and_keeps_legacy_students_filtered(self):
        records = [
            {"role": "student", "institutional_id": "A-010", "name": "Role Student",
             "email": "role.student@alpha.edu", "department": "CS", "program": "B.Tech",
             "batch": "2026-2030", "semester_number": 1, "section": "A"},
            {"role": "faculty", "institutional_id": "EMP-10", "name": "Role Faculty",
             "email": "role.faculty@alpha.edu", "department": "CS"},
            {"role": "hod", "institutional_id": "HOD-10", "name": "Role HOD",
             "email": "role.hod@alpha.edu", "department": "CS"},
        ]
        for payload in records:
            response = self.client.post("/api/users", headers=self.auth, json=payload)
            self.assertEqual(response.status_code, 201, response.text)
        exported = self.client.get("/api/ekeekrta/users", headers=self.auth)
        self.assertEqual(exported.status_code, 200, exported.text)
        self.assertEqual({item["role"] for item in exported.json()["users"]}, {"student", "faculty", "hod"})
        students = self.client.get("/api/ekeekrta/students", headers=self.auth).json()["students"]
        self.assertEqual(len(students), 1)
        self.assertEqual(students[0]["institutional_id"], "A-010")
        counts = self.client.get("/api/dashboard", headers=self.auth).json()["counts"]
        self.assertEqual((counts["users"], counts["students"], counts["faculty"], counts["hod"]), (3, 1, 1, 1))
        rejected = self.client.post("/api/users", headers=self.auth, json={**records[1], "role": "admin"})
        self.assertEqual(rejected.status_code, 422)

    def test_official_result_requires_registered_student_and_is_exported_privately(self):
        result = {"student_institutional_id": "A-020", "current_cgpa": 7.4,
                  "completed_credits": 82, "remaining_credits": 78, "grading_scale_max": 10}
        missing = self.client.post("/api/results", headers=self.auth, json=result)
        self.assertEqual(missing.status_code, 404)
        student = {"institutional_id": "A-020", "name": "Result Student", "email": "result@alpha.edu",
                   "department": "CS", "program": "B.Tech", "batch": "2026-2030",
                   "semester_number": 5, "section": "A"}
        self.client.post("/api/students", headers=self.auth, json=student)
        created = self.client.post("/api/results", headers=self.auth, json=result)
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(self.db.query(AcademicResult).count(), 1)
        self.assertEqual(self.client.get("/api/ekeekrta/results/A-020").status_code, 401)
        exported = self.client.get("/api/ekeekrta/results/A-020", headers=self.auth)
        self.assertEqual(exported.status_code, 200, exported.text)
        self.assertEqual(exported.json()["result"]["current_cgpa"], 7.4)
        self.assertEqual(self.client.get("/api/ekeekrta/results/A-999", headers=self.auth).status_code, 404)


if __name__ == "__main__":
    unittest.main()
