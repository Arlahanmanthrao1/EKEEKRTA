"""Custom-domain tests use disposable in-memory records only."""
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models
from app.config import Settings, settings
from app.core.security import create_access_token, hash_password, decode_access_token
from app.core.institution_domains import configured_login_origins
from app.database import Base, get_db
from app.models.institution import Institution
from app.models.user import User, UserRole
from app.routers import auth, institutions


class InstitutionDomainTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.db.add_all([Institution(id=1, name="Isolated Alpha", email_domain="alpha.edu", email="office@alpha.edu", address="Private address"),
                         Institution(id=2, name="Isolated Beta", email_domain="beta.edu")])
        self.db.flush()
        password = hash_password("test-only-password")
        for ident, domain in [(1, "alpha.edu"), (2, "beta.edu")]:
            self.db.add(User(id=ident, name="Isolated test admin", email=f"admin@{domain}", institution_id=ident,
                             role=UserRole.admin, hashed_password=password))
        self.db.commit()
        api = FastAPI()
        api.include_router(auth.router)
        api.include_router(institutions.router)
        api.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(api)
        hosts = patch.object(settings, "institution_login_hosts", {"ekeekrta.alpha.edu": "alpha.edu", "ekeekrta.beta.edu": "beta.edu"})
        hosts.start()
        self.addCleanup(hosts.stop)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        self.addCleanup(self.client.close)

    def login(self, domain="alpha.edu", headers=None):
        return self.client.post("/auth/login", data={"username": f"admin@{domain}", "password": "test-only-password"}, headers=headers)

    def test_generic_login_still_works(self):
        response = self.login()
        self.assertEqual(response.status_code, 200, response.text)
        token = response.json()["access_token"]
        self.assertNotIn("login_host", decode_access_token(token))
        self.assertEqual(self.client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code, 200)

    def test_public_vercel_address_is_always_the_generic_login(self):
        headers = {"Origin": "https://ekeekrta.vercel.app", "X-Institution-Host": "ekeekrta.vercel.app"}
        response = self.login(headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn("login_host", decode_access_token(response.json()["access_token"]))

    def test_custom_login_and_token_are_institution_scoped(self):
        headers = {"Origin": "https://ekeekrta.alpha.edu", "X-Institution-Host": "ekeekrta.alpha.edu"}
        response = self.login(headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        token = response.json()["access_token"]
        self.assertEqual(decode_access_token(token)["login_host"], "ekeekrta.alpha.edu")
        auth_header = {"Authorization": f"Bearer {token}"}
        self.assertEqual(self.client.get("/auth/me", headers={**headers, **auth_header}).status_code, 200)
        self.assertEqual(self.client.get("/auth/me", headers=auth_header).status_code, 401)
        self.assertEqual(self.client.get("/auth/me", headers={**auth_header, "Origin": "https://ekeekrta.beta.edu"}).status_code, 401)
        self.assertEqual(self.login("beta.edu", headers).status_code, 401)

    def test_origin_alone_cannot_bypass_scope_by_omitting_header(self):
        self.assertEqual(self.login(headers={"Origin": "https://ekeekrta.alpha.edu"}).status_code, 200)
        self.assertEqual(self.login("beta.edu", {"Origin": "https://ekeekrta.alpha.edu"}).status_code, 401)
        token = create_access_token({"sub": "2"})
        response = self.client.get("/auth/me", headers={"Origin": "https://ekeekrta.alpha.edu", "Authorization": f"Bearer {token}"})
        self.assertEqual(response.status_code, 401)

    def test_unknown_hosts_and_mismatching_headers_fail_closed(self):
        cases = [({"X-Institution-Host": "ekeekrta.unknown.edu"}, 404),
                 ({"Origin": "https://ekeekrta.unknown.edu"}, 404),
                 ({"Origin": "https://ekeekrta.alpha.edu", "X-Institution-Host": "ekeekrta.beta.edu"}, 403),
                 ({"Origin": "https://ekeekrta.alpha.edu", "X-Institution-Host": ""}, 403),
                 ({"Origin": "http://ekeekrta.alpha.edu"}, 400),
                 ({"Origin": "https://ekeekrta.alpha.edu:443"}, 400),
                 ({"X-Institution-Host": "ekeekrta.alpha.edu/path"}, 404)]
        for headers, status in cases:
            with self.subTest(headers=headers):
                self.assertEqual(self.login(headers=headers).status_code, status)

    def test_public_profile_contains_only_branding(self):
        response = self.client.get("/institutions/login-profile", headers={"X-Institution-Host": "ekeekrta.alpha.edu"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json()), {"name", "logo_url", "email_domain", "login_host"})
        self.assertEqual(response.json()["name"], "Isolated Alpha")
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertNotIn("Private address", response.text)
        self.assertEqual(self.client.get("/institutions/login-profile").status_code, 404)
        self.db.delete(self.db.get(User, 2))
        self.db.delete(self.db.get(Institution, 2))
        self.db.commit()
        self.assertEqual(self.client.get("/institutions/login-profile", headers={"X-Institution-Host": "ekeekrta.beta.edu"}).status_code, 404)

    def test_disabling_host_invalidates_portal_access(self):
        response = self.login(headers={"X-Institution-Host": "ekeekrta.alpha.edu"})
        token = response.json()["access_token"]
        with patch.object(settings, "institution_login_hosts", {}):
            response = self.client.get("/auth/me", headers={"X-Institution-Host": "ekeekrta.alpha.edu", "Authorization": f"Bearer {token}"})
            self.assertEqual(response.status_code, 404)

    def test_onboarding_is_only_available_on_main_site(self):
        payload = {"institution": {"name": "Isolated Gamma", "email": "office@gamma.edu"},
                   "administrator": {"name": "Test admin", "email": "admin@gamma.edu", "password": "test-only-password"}}
        response = self.client.post("/institutions/register", json=payload, headers={"Origin": "https://ekeekrta.alpha.edu"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.db.query(Institution).count(), 2)

    def test_admin_address_reports_config_not_dns_health(self):
        headers = {"Authorization": "Bearer " + create_access_token({"sub": "1"})}
        response = self.client.get("/institutions/current/login-address", headers=headers)
        self.assertEqual(response.json(), {"url": "https://ekeekrta.alpha.edu/login", "configured": True})
        with patch.object(settings, "institution_login_hosts", {}):
            self.assertFalse(self.client.get("/institutions/current/login-address", headers=headers).json()["configured"])
        self.db.get(User, 1).role = UserRole.student
        self.db.commit()
        self.assertEqual(self.client.get("/institutions/current/login-address", headers=headers).status_code, 403)

    def test_configuration_rejects_unsafe_or_ambiguous_hostnames(self):
        for host, domain in [("https://ekeekrta.alpha.edu", "alpha.edu"), ("ekeekrta.alpha.edu:443", "alpha.edu"),
                             ("ekeekrta.alpha.edu/path", "alpha.edu"), ("ekeekrta.alpha_edu.org", "alpha_edu.org"),
                             ("*.alpha.edu", "alpha.edu"), ("ekeekrta.alpha.edu", "beta.edu"),
                             ("ekeekrta.Alpha.edu", "Alpha.edu")]:
            with self.subTest(host=host), self.assertRaises(ValidationError):
                Settings(_env_file=None, institution_login_hosts={host: domain})
        config = Settings(_env_file=None, institution_login_hosts={"ekeekrta.alpha.edu": "alpha.edu"})
        self.assertEqual(config.institution_login_hosts, {"ekeekrta.alpha.edu": "alpha.edu"})

    def test_cors_allows_only_exact_configured_institution_origins(self):
        api = FastAPI()
        api.add_middleware(CORSMiddleware, allow_origins=configured_login_origins(), allow_methods=["*"], allow_headers=["*"])
        with TestClient(api) as client:
            for origin, status in [("https://ekeekrta.alpha.edu", 200), ("https://ekeekrta.beta.edu", 200),
                                   ("http://ekeekrta.alpha.edu", 400), ("https://ekeekrta.unknown.edu", 400)]:
                response = client.options("/auth/login", headers={"Origin": origin, "Access-Control-Request-Method": "POST",
                                                                 "Access-Control-Request-Headers": "x-institution-host,authorization,content-type"})
                self.assertEqual(response.status_code, status)
                if status == 200:
                    self.assertEqual(response.headers["access-control-allow-origin"], origin)
                else:
                    self.assertNotIn("access-control-allow-origin", response.headers)


if __name__ == "__main__":
    unittest.main()
