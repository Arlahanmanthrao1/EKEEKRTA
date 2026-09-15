"""Explicit custom-domain routing, in addition to existing tenant authorization.

The frontend Origin/header supplies routing context, never proof of identity.
Credentials and the user's stored institution remain authoritative.
"""
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.models.institution import Institution

PLATFORM_LOGIN_HOST = "ekeekrta.vercel.app"


def configured_login_origins() -> list[str]:
    return [f"https://{host}" for host in settings.institution_login_hosts]


def request_login_host(request: Request) -> str | None:
    header = request.headers.get("x-institution-host")
    origin = request.headers.get("origin")
    origin_host = None
    if origin:
        try:
            parsed = urlsplit(origin)
            hostname = parsed.hostname or ""
        except ValueError:
            raise HTTPException(400, "Invalid login origin") from None
        if hostname.startswith("ekeekrta.") and hostname != PLATFORM_LOGIN_HOST:
            if origin != f"https://{hostname}":
                raise HTTPException(400, "Institution login requires its exact HTTPS origin")
            origin_host = hostname
    # Older cached frontend bundles sent the platform hostname as if it were an
    # institution domain. Treat only this exact public platform address as generic.
    if header == PLATFORM_LOGIN_HOST:
        header = None
    if origin_host and header is not None and header != origin_host:
        raise HTTPException(403, "Institution login address does not match")
    host = origin_host or header
    if host is not None and host not in settings.institution_login_hosts:
        raise HTTPException(404, "This institution login address is not configured. Contact your institution administrator.")
    return host


def institution_for_host(host: str, db: Session) -> Institution:
    domain = settings.institution_login_hosts.get(host)
    institution = db.query(Institution).filter(Institution.email_domain == domain).first() if domain else None
    if institution is None:
        raise HTTPException(404, "This institution login address is not configured. Contact your institution administrator.")
    return institution
