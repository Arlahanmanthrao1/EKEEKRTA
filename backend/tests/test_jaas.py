"""Isolated tests: no production DB, network calls, or saved private keys."""
import time
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jose import jwt, JWTError
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models
from app.config import settings
from app.database import Base, get_db
from app.core.deps import get_current_user
from app.models.user import User, UserRole
from app.models.institution import Institution, Department
from app.models.course import Course, Enrollment
from app.models.attendance import ClassSession
from app.routers.attendance import router


class JaaSTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.private = key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
        cls.public = key.public_key().public_bytes(serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo).decode()

    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.db.add(Institution(id=1, name="Isolated test institution", email_domain="college.edu"))
        self.db.flush()
        self.db.add(Department(institution_id=1, name="CS"))
        self.db.commit()
        for ident, role in [(1, UserRole.faculty), (2, UserRole.student),
                            (3, UserRole.student), (4, UserRole.faculty),
                            (5, UserRole.admin), (6, UserRole.hod)]:
            self.db.add(User(institution_id=1, id=ident, name=f"Test {ident}", email=f"test{ident}@example.invalid",
                             hashed_password="unused", role=role))
        self.db.add(Course(institution_id=1, id=1, code="TEST", name="Isolated test course", faculty_id=1))
        self.db.add(Enrollment(student_id=2, course_id=1))
        self.db.add(ClassSession(id=1, course_id=1, jitsi_room_id="lms-testroom"))
        self.db.commit()
        self.current_user = self.db.get(User, 2)
        api = FastAPI()
        api.include_router(router)
        api.dependency_overrides[get_db] = lambda: self.db
        api.dependency_overrides[get_current_user] = lambda: self.current_user
        self.client = TestClient(api)
        for name, value in dict(video_provider="jaas", jaas_app_id="vpaas-magic-cookie-test",
                                jaas_private_key=SecretStr(""),
                                jaas_api_key_id="vpaas-magic-cookie-test/keyid",
                                jaas_private_key_path="unused-test.pem").items():
            p = patch.object(settings, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = patch("app.integrations.video.Path.read_text", return_value=self.private)
        self.read_key = p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        self.client.close()
        self.db.close()
        self.engine.dispose()

    def connect(self, user_id=2, session_id=1):
        self.current_user = self.db.get(User, user_id)
        return self.client.post(f"/attendance/sessions/{session_id}/connection")

    def decode(self, response):
        self.assertEqual(response.status_code, 200, response.text)
        return jwt.decode(response.json()["jwt"], self.public, algorithms=["RS256"], audience="jitsi", issuer="chat")

    def test_student_room_scope_and_signature(self):
        response = self.connect()
        claims = self.decode(response)
        self.assertEqual(claims["room"], "lms-testroom")
        self.assertFalse(claims["context"]["room"]["regex"])
        self.assertEqual(claims["context"]["user"]["moderator"], "false")
        self.assertEqual(claims["context"]["user"]["id"], "2")
        self.assertFalse(any(claims["context"]["features"].values()))
        self.assertGreater(claims["exp"], time.time())
        self.assertEqual(claims["exp"] - claims["iat"], settings.jaas_token_expire_minutes * 60)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertNotIn("PRIVATE KEY", response.text)
        data = response.json()
        self.assertEqual(data["room_name"], "vpaas-magic-cookie-test/lms-testroom")
        self.assertEqual(data["script_url"], "https://8x8.vc/vpaas-magic-cookie-test/external_api.js")
        self.assertEqual(jwt.get_unverified_header(data["jwt"])["kid"], settings.jaas_api_key_id)
        # Changing a signed claim must invalidate the token.
        forged = jwt.encode({**claims, "room": "other-room"}, "wrong-secret", algorithm="HS256")
        with self.assertRaises(JWTError):
            jwt.decode(forged, self.public, algorithms=["RS256"], audience="jitsi")

    def test_student_identity_is_stable_across_classes(self):
        first = self.decode(self.connect())
        self.db.add(ClassSession(id=2, course_id=1, jitsi_room_id="lms-secondroom"))
        self.db.commit()
        second = self.decode(self.connect(session_id=2))

        self.assertNotEqual(first["room"], second["room"])
        self.assertEqual(first["context"]["user"]["id"], "2")
        self.assertEqual(second["context"]["user"]["id"], "2")

    def test_instructor_and_admin_moderate_same_room(self):
        student = self.connect().json()
        for user_id in [1, 5]:
            response = self.connect(user_id)
            self.assertEqual(self.decode(response)["context"]["user"]["moderator"], "true")
            self.assertEqual(response.json()["room_name"], student["room_name"])

    def test_unauthorized_users_do_not_receive_tokens(self):
        for user_id in [3, 4, 6]:
            self.assertEqual(self.connect(user_id).status_code, 403)
        self.read_key.assert_not_called()

    def test_ended_and_missing_sessions(self):
        self.assertEqual(self.connect(session_id=999).status_code, 404)
        self.db.get(ClassSession, 1).ended_at = datetime.now(timezone.utc)
        self.db.commit()
        self.assertEqual(self.connect().status_code, 409)
        self.read_key.assert_not_called()

    def test_missing_and_mismatched_credentials_fail_closed(self):
        with patch.object(settings, "jaas_app_id", ""):
            response = self.connect()
            self.assertEqual(response.status_code, 503)
            self.assertIn("JaaS setup required", response.text)
        with patch.object(settings, "jaas_api_key_id", "wrong-app/key"):
            self.assertEqual(self.connect().status_code, 503)

    def test_key_failures_do_not_leak_details(self):
        self.read_key.side_effect = OSError("sensitive-path")
        response = self.connect()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("sensitive-path", response.text)
        self.read_key.side_effect = None
        self.read_key.return_value = "invalid private key"
        self.assertEqual(self.connect().status_code, 503)

    def test_explicit_public_or_college_server_mode(self):
        with patch.object(settings, "video_provider", "jitsi"), patch.object(settings, "jitsi_domain", "meet.college.example"):
            response = self.connect()
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["domain"], "meet.college.example")
            self.assertIsNone(response.json()["jwt"])
            self.assertEqual(self.connect(3).status_code, 403)
        self.read_key.assert_not_called()

    def test_cloud_secret_key_without_local_file(self):
        with patch.object(settings, "jaas_private_key", SecretStr(self.private.replace("\n", "\\n"))), patch.object(settings, "jaas_private_key_path", ""):
            response = self.connect()
            self.assertEqual(self.decode(response)["context"]["user"]["moderator"], "false")
            self.read_key.assert_not_called()


if __name__ == "__main__":
    unittest.main()
