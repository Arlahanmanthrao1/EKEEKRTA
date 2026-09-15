"""ERP tests use only disposable in-memory records and mocked HTTP calls."""

import json
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models
from app.core.security import create_access_token, hash_password, verify_password
from app.database import Base, get_db
from app.models import Attendance, ClassSession, Course, User, UserRole
from app.models.erp import ERPIntegration, ERPSyncEvent
from app.models.institution import Institution
from app.routers.erp import router


class ERPIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.db.add_all([
            Institution(id=1, name="Test Alpha", email_domain="alpha.edu"),
            Institution(id=2, name="Test Beta", email_domain="beta.edu"),
        ])
        self.db.flush()
        self.db.add_all([
            User(id=1, institution_id=1, name="Alpha Admin", email="admin@alpha.edu", role=UserRole.admin, hashed_password="unused"),
            User(id=2, institution_id=1, institutional_id="A-001", name="Alpha Student", email="student@alpha.edu",
                 role=UserRole.student, department="CS", program="B.Tech", batch="2026-2030", semester_number=1,
                 section="A", hashed_password="unused"),
            User(id=3, institution_id=2, name="Beta Admin", email="admin@beta.edu", role=UserRole.admin, hashed_password="unused"),
            User(id=4, institution_id=2, institutional_id="B-001", name="Beta Student", email="student@beta.edu",
                 role=UserRole.student, department="CS", program="B.Tech", batch="2026-2030", semester_number=1,
                 section="A", hashed_password="unused"),
        ])
        self.db.flush()
        self.db.add_all([
            Course(id=1, institution_id=1, faculty_id=1, name="Alpha Course", code="AL101", department="CS"),
            Course(id=2, institution_id=2, faculty_id=3, name="Beta Course", code="BE101", department="CS"),
        ])
        self.db.flush()
        self.db.add_all([
            ClassSession(id=1, course_id=1, jitsi_room_id="alpha-room"),
            ClassSession(id=2, course_id=2, jitsi_room_id="beta-room"),
        ])
        self.db.flush()
        self.db.add_all([
            Attendance(id=1, session_id=1, student_id=2, duration_minutes=45, present=True),
            Attendance(id=2, session_id=2, student_id=4, duration_minutes=10, present=False),
        ])
        self.db.commit()
        api = FastAPI()
        api.include_router(router)
        api.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(api)

    def tearDown(self):
        self.client.close()
        self.db.close()
        self.engine.dispose()

    def headers(self, user_id):
        return {"Authorization": "Bearer " + create_access_token({"sub": str(user_id)})}

    def request(self, method, path, user_id=1, **kwargs):
        return self.client.request(method, path, headers=self.headers(user_id) if user_id else {}, **kwargs)

    def configure(self, user_id=1, **changes):
        payload = {"base_url": "https://erp.alpha.example", "api_token": "isolated-erp-token-12345",
                   "external_institution_id": "ALPHA", "enabled": True, "sync_students": True,
                   "sync_courses": True, "sync_attendance": True, **changes}
        return self.request("PUT", "/erp/configuration", user_id, json=payload)

    def test_configuration_is_admin_only_and_secret_is_never_returned(self):
        self.assertEqual(self.request("GET", "/erp/configuration", None).status_code, 401)
        self.assertEqual(self.request("GET", "/erp/configuration", 2).status_code, 403)
        created = self.configure()
        self.assertEqual(created.status_code, 200, created.text)
        self.assertTrue(created.json()["token_configured"])
        self.assertNotIn("isolated-erp-token-12345", created.text)
        encrypted = self.db.query(ERPIntegration).filter_by(institution_id=1).one().encrypted_api_token
        self.assertNotIn("isolated-erp-token-12345", encrypted)
        # Updating other fields with a blank token preserves the encrypted secret.
        payload = {**created.json(), "api_token": None}
        for read_only in ["configured", "token_configured", "last_tested_at", "last_test_success", "last_test_message"]:
            payload.pop(read_only, None)
        self.assertEqual(self.request("PUT", "/erp/configuration", json=payload).status_code, 200)
        self.assertEqual(self.db.query(ERPIntegration).filter_by(institution_id=1).one().encrypted_api_token, encrypted)
        self.assertEqual(self.request("PUT", "/erp/configuration", json={**payload, "base_url": "http://erp.example.com"}).status_code, 422)
        self.assertEqual(self.request("PUT", "/erp/configuration", json={**payload, "base_url": "http://127.0.0.1:9000"}).status_code, 200)

    def test_health_check_uses_bearer_token_without_exposing_it(self):
        self.configure()
        with patch("app.integrations.erp_client.httpx.get") as get:
            get.return_value.status_code = 200
            response = self.request("POST", "/erp/test")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["last_test_success"])
        self.assertEqual(get.call_args.kwargs["headers"]["Authorization"], "Bearer isolated-erp-token-12345")
        self.assertNotIn("isolated-erp-token-12345", response.text)

    def test_full_sync_sends_only_the_administrators_institution(self):
        self.configure()
        erp_students = {"institution_id": "ALPHA", "students": [{
            "institutional_id": "A-001", "name": "Alpha Student", "email": "student@alpha.edu",
            "department": "CS", "program": "B.Tech", "batch": "2026-2030",
            "semester_number": 1, "section": "A",
        }]}
        with patch("app.integrations.erp_client.httpx.post") as post:
            post.return_value.status_code = 202
            response = self.request("POST", "/erp/sync")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["queued"], 2)
        self.assertEqual(response.json()["updated"], 0)
        self.assertEqual(response.json()["synced"], 2)
        self.assertEqual(post.call_count, 2)
        payloads = [json.loads(call.kwargs["content"]) for call in post.call_args_list]
        self.assertTrue(all(payload["institution"]["email_domain"] == "alpha.edu" for payload in payloads))
        self.assertTrue(all(payload["institution"]["external_id"] == "ALPHA" for payload in payloads))
        self.assertNotIn("beta.edu", json.dumps(payloads))
        events = self.request("GET", "/erp/events").json()
        self.assertEqual({event["event_type"] for event in events}, {"course", "attendance"})
        self.assertTrue(all(event["status"] == "synced" for event in events))
        self.assertTrue(all(call.kwargs["headers"]["Idempotency-Key"].endswith("-1") for call in post.call_args_list))
        self.assertEqual(self.request("GET", "/erp/events", 3).json(), [])

        with patch("app.integrations.erp_client.httpx.post") as second_post:
            second_post.return_value.status_code = 200
            repeated = self.request("POST", "/erp/sync")
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertTrue(all(call.kwargs["headers"]["Idempotency-Key"].endswith("-2") for call in second_post.call_args_list))

    def test_students_are_imported_from_erp_and_updated_by_official_id(self):
        self.configure(sync_courses=False, sync_attendance=False)
        student = {"institutional_id": "A-009", "name": "ERP Student", "email": "erp.student@alpha.edu",
                   "department": "ECE", "program": "B.Tech", "batch": "2026-2030",
                   "semester_number": 1, "section": "B"}
        with patch("app.routers.erp.fetch_erp_students",
                   return_value={"institution_id": "ALPHA", "students": [student]}):
            response = self.request("POST", "/erp/import-students")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["imported"], 1)
        imported = self.db.query(User).filter_by(institution_id=1, institutional_id="A-009").one()
        self.assertEqual(imported.role, UserRole.student)
        self.assertEqual(imported.department, "ECE")
        self.assertEqual(imported.section, "B")
        self.assertTrue(verify_password("A-009", imported.hashed_password))
        self.assertTrue(imported.must_change_password)
        self.assertTrue(imported.erp_password_initialized)

        imported.hashed_password = hash_password("student-selected-password")
        imported.must_change_password = False
        self.db.commit()
        changed = {**student, "name": "Updated ERP Student", "semester_number": 2}
        with patch("app.routers.erp.fetch_erp_students",
                   return_value={"institution_id": "ALPHA", "students": [changed]}):
            response = self.request("POST", "/erp/import-students")
        self.assertEqual(response.json()["updated"], 1)
        self.assertEqual(self.db.query(User).filter_by(id=imported.id).one().semester_number, 2)
        self.assertTrue(verify_password("student-selected-password", imported.hashed_password))
        self.assertFalse(verify_password("A-009", imported.hashed_password))
        self.assertEqual(self.db.query(User).filter_by(institution_id=1, institutional_id="A-009").count(), 1)

    def test_student_import_rejects_another_erp_institution(self):
        self.configure()
        with patch("app.routers.erp.fetch_erp_students", return_value={"institution_id": "BETA", "students": []}):
            response = self.request("POST", "/erp/import-students")
        self.assertEqual(response.status_code, 409)

    def test_role_based_user_import_requires_preview_and_confirmation(self):
        self.configure(sync_courses=False, sync_attendance=False)
        export = {"institution_id": "ALPHA", "users": [
            {"role": "student", "institutional_id": "A-009", "name": "ERP Student",
             "email": "erp.student@alpha.edu", "department": "ECE", "program": "B.Tech",
             "batch": "2026-2030", "semester_number": 1, "section": "B"},
            {"role": "faculty", "institutional_id": "EMP-9", "name": "ERP Faculty",
             "email": "faculty@alpha.edu", "department": "ECE"},
            {"role": "hod", "institutional_id": "HOD-9", "name": "ERP HOD",
             "email": "hod@alpha.edu", "department": "ECE"},
            {"role": "admin", "institutional_id": "ADM-9", "name": "Unsafe Admin",
             "email": "unsafe.admin@alpha.edu"},
        ]}
        with patch("app.routers.erp.fetch_erp_users", return_value=export):
            preview = self.request("POST", "/erp/import-users/preview")
        self.assertEqual(preview.status_code, 200, preview.text)
        review = preview.json()
        self.assertEqual((review["creates"], review["updates"], review["skipped"]), (3, 0, 1))
        self.assertEqual(review["role_counts"], {"student": 1, "faculty": 1, "hod": 1})
        self.assertIn("cannot be imported", review["records"][3]["reason"])
        self.assertEqual(self.db.query(User).filter(User.id > 4).count(), 0)

        with patch("app.routers.erp.fetch_erp_users", return_value=export):
            confirmed = self.request("POST", "/erp/import-users/confirm",
                                     json={"confirmation_token": review["confirmation_token"]})
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertEqual(confirmed.json()["imported"], 3)
        accounts = {row.institutional_id: row for row in self.db.query(User).filter(User.id > 4).all()}
        self.assertEqual(set(accounts), {"A-009", "EMP-9", "HOD-9"})
        self.assertEqual(accounts["A-009"].role, UserRole.student)
        self.assertEqual(accounts["A-009"].semester_number, 1)
        self.assertTrue(verify_password("A-009", accounts["A-009"].hashed_password))
        self.assertTrue(accounts["A-009"].must_change_password)
        self.assertEqual(accounts["EMP-9"].role, UserRole.faculty)
        self.assertTrue(verify_password("EMP-9", accounts["EMP-9"].hashed_password))
        self.assertIsNone(accounts["EMP-9"].semester_number)
        self.assertEqual(accounts["HOD-9"].role, UserRole.hod)
        self.assertEqual(self.db.query(User).filter_by(email="unsafe.admin@alpha.edu").count(), 0)

    def test_user_import_skips_role_conflicts_and_stale_previews(self):
        self.configure(sync_courses=False, sync_attendance=False)
        conflict = {"institution_id": "ALPHA", "users": [{
            "role": "faculty", "institutional_id": "A-001", "name": "Role Change",
            "email": "student@alpha.edu", "department": "CS",
        }]}
        with patch("app.routers.erp.fetch_erp_users", return_value=conflict):
            preview = self.request("POST", "/erp/import-users/preview")
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertEqual(preview.json()["skipped"], 1)
        self.assertIn("role conflicts", preview.json()["records"][0]["reason"])

        original = {"institution_id": "ALPHA", "users": [{
            "role": "faculty", "institutional_id": "EMP-10", "name": "Original Name",
            "email": "faculty10@alpha.edu", "department": "CS",
        }]}
        changed = {"institution_id": "ALPHA", "users": [{**original["users"][0], "name": "Changed Name"}]}
        with patch("app.routers.erp.fetch_erp_users", return_value=original):
            fresh = self.request("POST", "/erp/import-users/preview").json()
        with patch("app.routers.erp.fetch_erp_users", return_value=changed):
            stale = self.request("POST", "/erp/import-users/confirm",
                                 json={"confirmation_token": fresh["confirmation_token"]})
        self.assertEqual(stale.status_code, 409, stale.text)
        self.assertEqual(self.db.query(User).filter_by(institutional_id="EMP-10").count(), 0)

    def test_user_import_preview_is_scoped_to_the_admin_and_institution(self):
        self.configure(sync_courses=False, sync_attendance=False)
        export = {"institution_id": "ALPHA", "users": [{
            "role": "faculty", "institutional_id": "EMP-11", "name": "Scoped Faculty",
            "email": "faculty11@alpha.edu", "department": "CS",
        }]}
        with patch("app.routers.erp.fetch_erp_users", return_value=export):
            token = self.request("POST", "/erp/import-users/preview").json()["confirmation_token"]
        response = self.request("POST", "/erp/import-users/confirm", 3,
                                json={"confirmation_token": token})
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(self.db.query(User).filter_by(institutional_id="EMP-11").count(), 0)

    def test_failed_event_is_recorded_and_can_be_retried(self):
        self.configure(sync_students=False, sync_courses=False)
        with patch("app.integrations.erp_client.httpx.post") as post:
            post.return_value.status_code = 503
            first = self.request("POST", "/erp/sync")
        self.assertEqual(first.json()["failed"], 1)
        event = self.db.query(ERPSyncEvent).one()
        self.assertEqual(event.status, "failed")
        self.assertEqual(event.last_error, "ERP returned HTTP 503")
        with patch("app.integrations.erp_client.httpx.post") as post:
            post.return_value.status_code = 200
            retried = self.request("POST", f"/erp/events/{event.id}/retry")
        self.assertEqual(retried.status_code, 200, retried.text)
        self.assertEqual(retried.json()["status"], "synced")
        self.assertEqual(retried.json()["attempts"], 2)


if __name__ == "__main__":
    unittest.main()
