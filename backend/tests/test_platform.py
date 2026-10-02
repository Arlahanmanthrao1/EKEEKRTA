"""Platform operations security tests use an isolated in-memory database."""
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models
from app.core.security import create_access_token, hash_password
from app.database import Base, get_db
from app.models.course import Course
from app.models.institution import Institution, InstitutionStatus
from app.models.platform import PlatformAuditLog
from app.models.user import User, UserRole
from app.routers import auth, platform


class PlatformOperationsTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.db.add_all([
            Institution(id=1, name="Alpha University", email="office@alpha.edu", email_domain="alpha.edu",
                        status=InstitutionStatus.active.value),
            Institution(id=2, name="Beta Training", email="office@beta.edu", email_domain="beta.edu",
                        institution_type="training_institution", status=InstitutionStatus.pending.value),
        ])
        self.db.flush()
        password = hash_password("test-only-password")
        self.db.add_all([
            User(id=1, name="Ekeekrta Operator", email="operator@ekeekrta.org", hashed_password=password,
                 role=UserRole.platform_admin),
            User(id=2, name="Alpha Admin", email="admin@alpha.edu", hashed_password=password,
                 role=UserRole.admin, institution_id=1),
            User(id=3, name="Beta Admin", email="admin@beta.edu", hashed_password=password,
                 role=UserRole.admin, institution_id=2),
        ])
        self.db.flush()
        self.db.add(Course(name="Alpha Course", code="ALPHA-1", institution_id=1))
        self.db.commit()
        api = FastAPI()
        api.include_router(auth.router)
        api.include_router(platform.router)
        api.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(api)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        self.addCleanup(self.client.close)

    def headers(self, user_id):
        return {"Authorization": "Bearer " + create_access_token({"sub": str(user_id)})}

    def test_operator_login_and_tenant_isolation(self):
        normal = self.client.post("/auth/login", data={"username": "operator@ekeekrta.org", "password": "test-only-password"})
        self.assertEqual(normal.status_code, 403)
        login = self.client.post("/auth/platform-login", data={"username": "operator@ekeekrta.org", "password": "test-only-password"})
        self.assertEqual(login.status_code, 200, login.text)
        token = login.json()["access_token"]
        me = self.client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["role"], "platform_admin")
        self.assertIsNone(me.json()["institution"])
        self.assertNotIn("hashed_password", me.text)
        self.assertEqual(self.client.get("/platform/institutions", headers=self.headers(2)).status_code, 403)

    def test_pending_approval_suspension_and_audit(self):
        self.assertEqual(self.client.get("/auth/me", headers=self.headers(3)).status_code, 403)
        listing = self.client.get("/platform/institutions", headers=self.headers(1))
        self.assertEqual(listing.status_code, 200, listing.text)
        beta = next(entry for entry in listing.json() if entry["id"] == 2)
        self.assertEqual(beta["status"], "pending")
        self.assertEqual(beta["primary_administrator_email"], "admin@beta.edu")
        self.assertNotIn("password", listing.text.lower())

        approval = self.client.patch("/platform/institutions/2/status", headers=self.headers(1),
                                     json={"status": "active", "reason": "Registration verified"})
        self.assertEqual(approval.status_code, 200, approval.text)
        self.assertEqual(self.client.get("/auth/me", headers=self.headers(3)).status_code, 200)
        old_version = self.db.get(User, 3).session_version
        suspension = self.client.patch("/platform/institutions/2/status", headers=self.headers(1),
                                       json={"status": "suspended", "reason": "Verification expired"})
        self.assertEqual(suspension.status_code, 200, suspension.text)
        self.db.refresh(self.db.get(User, 3))
        self.assertEqual(self.db.get(User, 3).session_version, old_version + 1)
        self.assertEqual(self.client.get("/auth/me", headers=self.headers(3)).status_code, 401)
        audit = self.client.get("/platform/audit", headers=self.headers(1))
        self.assertEqual(audit.status_code, 200)
        self.assertEqual(len(audit.json()), 2)
        self.assertEqual(self.db.query(PlatformAuditLog).count(), 2)

    def test_restriction_requires_reason_and_summary_is_aggregate_only(self):
        denied = self.client.patch("/platform/institutions/1/status", headers=self.headers(1),
                                   json={"status": "suspended", "reason": None})
        self.assertEqual(denied.status_code, 422)
        summary = self.client.get("/platform/summary", headers=self.headers(1))
        self.assertEqual(summary.status_code, 200, summary.text)
        self.assertEqual(summary.json()["institutions_total"], 2)
        self.assertEqual(summary.json()["institution_users"], 2)
        self.assertEqual(summary.json()["courses"], 1)

    def test_permanent_deletion_is_operator_only_restricted_and_confirmed(self):
        self.db.add(Course(name="Beta Course", code="BETA-1", institution_id=2, faculty_id=3))
        self.db.commit()
        payload = {"confirmation_name": "Beta Training", "reason": "Duplicate test registration"}

        tenant_denied = self.client.request("DELETE", "/platform/institutions/2", headers=self.headers(2), json=payload)
        self.assertEqual(tenant_denied.status_code, 403)
        active_denied = self.client.request("DELETE", "/platform/institutions/1", headers=self.headers(1),
                                            json={**payload, "confirmation_name": "Alpha University"})
        self.assertEqual(active_denied.status_code, 409)
        mismatch = self.client.request("DELETE", "/platform/institutions/2", headers=self.headers(1),
                                       json={**payload, "confirmation_name": "Beta"})
        self.assertEqual(mismatch.status_code, 409)

        rejected = self.client.patch("/platform/institutions/2/status", headers=self.headers(1),
                                     json={"status": "rejected", "reason": "Duplicate registration"})
        self.assertEqual(rejected.status_code, 200, rejected.text)
        mismatch = self.client.request("DELETE", "/platform/institutions/2", headers=self.headers(1),
                                       json={**payload, "confirmation_name": "Beta"})
        self.assertEqual(mismatch.status_code, 422)

        deleted = self.client.request("DELETE", "/platform/institutions/2", headers=self.headers(1), json=payload)
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertEqual(deleted.json()["deleted_user_count"], 1)
        self.assertEqual(deleted.json()["deleted_course_count"], 1)
        self.assertIsNone(self.db.get(Institution, 2))
        self.assertIsNone(self.db.get(User, 3))
        self.assertEqual(self.db.query(Course).filter(Course.institution_id == 2).count(), 0)
        audit = self.db.query(PlatformAuditLog).filter(
            PlatformAuditLog.event_type == "institution_permanently_deleted"
        ).one()
        self.assertIsNone(audit.institution_id)
        self.assertEqual(audit.details["institution_name"], "Beta Training")
        self.assertEqual(self.db.get(User, 1).role, UserRole.platform_admin)


if __name__ == "__main__":
    unittest.main()
