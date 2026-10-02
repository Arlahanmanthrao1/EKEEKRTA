import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models
from app.config import settings
from app.core.security import create_access_token
from app.core.secret_box import decrypt_secret
from app.database import Base, get_db
from app.models.google_drive import GoogleDriveConnection
from app.models.institution import Institution, InstitutionType
from app.models.user import User, UserRole
from app.routers import google_drive


class GoogleDriveOAuthTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        training = Institution(id=1, name="Training", email_domain="training.example",
                               institution_type=InstitutionType.training_institution.value)
        university = Institution(id=2, name="University", email_domain="university.example")
        self.db.add_all([training, university]); self.db.flush()
        self.db.add_all([
            User(id=1, institution_id=1, name="Trainer", email="trainer@training.example",
                 role=UserRole.faculty, hashed_password="unused"),
            User(id=2, institution_id=2, name="Faculty", email="faculty@university.example",
                 role=UserRole.faculty, hashed_password="unused"),
        ]); self.db.commit()
        api = FastAPI(); api.include_router(google_drive.router)
        api.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(api)
        self.addCleanup(self.engine.dispose); self.addCleanup(self.db.close); self.addCleanup(self.client.close)
        patches = [
            patch.object(settings, "google_drive_oauth_client_id", "client.apps.googleusercontent.com"),
            patch.object(settings, "google_drive_oauth_client_secret", SecretStr("client-secret")),
            patch.object(settings, "google_drive_oauth_redirect_uri", "https://api.example/connect/callback"),
            patch.object(settings, "google_drive_frontend_return_url", "https://app.example/faculty/create-course"),
        ]
        for item in patches: item.start(); self.addCleanup(item.stop)

    def request(self, method, path, user=1, **kwargs):
        token = create_access_token({"sub": str(user)})
        return self.client.request(method, path, headers={"Authorization": f"Bearer {token}"}, **kwargs)

    def test_trainer_connects_personal_account_and_token_is_encrypted(self):
        self.assertFalse(self.request("GET", "/integrations/google-drive/status").json()["connected"])
        connect = self.request("POST", "/integrations/google-drive/connect")
        self.assertEqual(connect.status_code, 200, connect.text)
        authorization = urlparse(connect.json()["authorization_url"])
        query = parse_qs(authorization.query)
        self.assertEqual(query["scope"][0].split()[-1], "https://www.googleapis.com/auth/drive.file")
        state = query["state"][0]
        with patch("app.routers.google_drive.httpx.post", return_value=httpx.Response(200, json={
                "access_token": "short-access", "refresh_token": "personal-refresh", "scope": query["scope"][0]})), patch(
                "app.routers.google_drive.httpx.get", return_value=httpx.Response(200, json={
                    "email": "trainer.personal@gmail.com", "email_verified": True})):
            callback = self.client.get(
                f"/integrations/google-drive/callback?code=one-time-code&state={state}",
                follow_redirects=False)
        self.assertEqual(callback.status_code, 303, callback.text)
        self.assertEqual(callback.headers["location"], "https://app.example/faculty/create-course?drive=connected")
        saved = self.db.query(GoogleDriveConnection).one()
        self.assertEqual(saved.user_id, 1)
        self.assertEqual(saved.google_email, "trainer.personal@gmail.com")
        self.assertNotIn("personal-refresh", saved.encrypted_refresh_token)
        self.assertEqual(decrypt_secret(saved.encrypted_refresh_token), "personal-refresh")
        self.assertTrue(self.request("GET", "/integrations/google-drive/status").json()["connected"])

    def test_university_faculty_cannot_connect_training_drive(self):
        response = self.request("POST", "/integrations/google-drive/connect", user=2)
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
