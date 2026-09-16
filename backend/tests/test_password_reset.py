"""Password recovery tests use a disposable database and a captured mail sender."""
import hashlib
import unittest
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models
from app.config import settings
from app.core.security import hash_password, verify_password
from app.database import Base, get_db
from app.models.institution import Institution
from app.models.password_reset import PasswordResetToken
from app.models.user import User, UserRole
from app.routers import auth


class PasswordResetTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.db.add(Institution(id=1, name="Isolated College", email_domain="college.edu"))
        self.db.add(User(id=1, institution_id=1, name="Student One", email="student@college.edu",
                         institutional_id="STUDENT-1", role=UserRole.student,
                         hashed_password=hash_password("original-password")))
        self.db.commit()
        api = FastAPI(); api.include_router(auth.router)
        api.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(api)
        self.messages = []
        patches = [
            patch.object(settings, "smtp_host", "smtp.test.invalid"),
            patch.object(settings, "smtp_from_email", "no-reply@college.edu"),
            patch.object(settings, "password_reset_base_url", "https://app.example.com"),
            patch("app.routers.auth.send_password_reset_email", side_effect=lambda *args: self.messages.append(args)),
        ]
        for item in patches:
            item.start(); self.addCleanup(item.stop)
        self.addCleanup(self.cleanup_resources)

    def cleanup_resources(self):
        self.client.close()
        self.db.close()
        self.engine.dispose()

    def request_token(self):
        response = self.client.post("/auth/forgot-password", json={"email": "student@college.edu"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn("student@college.edu", response.text)
        self.assertEqual(len(self.messages), 1)
        reset_url = self.messages[0][2]
        return parse_qs(urlsplit(reset_url).query)["token"][0]

    def test_reset_token_is_hashed_single_use_and_revokes_existing_session(self):
        login = self.client.post("/auth/login", data={"username":"student@college.edu", "password":"original-password"})
        old_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        token = self.request_token()
        stored = self.db.query(PasswordResetToken).one()
        self.assertNotEqual(stored.token_hash, token)
        self.assertEqual(stored.token_hash, hashlib.sha256(token.encode()).hexdigest())
        response = self.client.post("/auth/reset-password", json={"token": token, "new_password":"new-secure-password"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(verify_password("new-secure-password", self.db.get(User, 1).hashed_password))
        self.assertEqual(self.client.post("/auth/reset-password", json={"token":token,"new_password":"another-password"}).status_code, 400)
        self.assertEqual(self.client.get("/auth/me", headers=old_headers).status_code, 401)
        self.assertEqual(self.client.post("/auth/login", data={"username":"student@college.edu", "password":"original-password"}).status_code, 401)
        self.assertEqual(self.client.post("/auth/login", data={"username":"student@college.edu", "password":"new-secure-password"}).status_code, 200)

    def test_unknown_email_has_same_response_and_no_token(self):
        real = self.client.post("/auth/forgot-password", json={"email":"student@college.edu"})
        self.messages.clear()
        unknown = self.client.post("/auth/forgot-password", json={"email":"unknown@college.edu"})
        self.assertEqual((real.status_code, real.json()), (unknown.status_code, unknown.json()))
        self.assertEqual(self.messages, [])
        self.assertEqual(self.db.query(PasswordResetToken).count(), 1)

    def test_recovery_configuration_and_password_rules(self):
        self.assertEqual(self.client.get("/auth/password-recovery/config").json(), {"enabled": True})
        with patch.object(settings, "smtp_host", ""):
            self.assertEqual(self.client.get("/auth/password-recovery/config").json(), {"enabled": False})
            self.assertEqual(self.client.post("/auth/forgot-password", json={"email":"student@college.edu"}).status_code, 503)
        token = self.request_token()
        self.assertEqual(self.client.post("/auth/reset-password", json={"token":token,"new_password":"too-short"}).status_code, 422)
        self.assertEqual(self.client.post("/auth/reset-password", json={"token":token,"new_password":"STUDENT-1"}).status_code, 422)


if __name__ == "__main__":
    unittest.main()
