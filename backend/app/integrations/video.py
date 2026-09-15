"""Server-only video credentials. No private key or JWT is logged."""
from pathlib import Path
import re
import time

from fastapi import HTTPException
from jose import jwt

from app.config import settings


def meeting_connection(session, user, is_moderator: bool) -> dict:
    if settings.video_provider == "jitsi":
        domain = settings.jitsi_domain.strip()
        if not re.fullmatch(r"[a-zA-Z0-9.-]+(?::[0-9]+)?", domain):
            raise HTTPException(503, "JITSI_DOMAIN must be a hostname, without https:// or a path.")
        return dict(provider="jitsi", domain=domain,
                    script_url=f"https://{domain}/external_api.js",
                    room_name=session.jitsi_room_id, jwt=None, expires_at=None)

    app_id = settings.jaas_app_id.strip()
    key_id = settings.jaas_api_key_id.strip()
    private_key = settings.jaas_private_key.get_secret_value()
    if not app_id or not key_id or not (private_key or settings.jaas_private_key_path):
        raise HTTPException(503, "JaaS setup required: configure JAAS_APP_ID, JAAS_API_KEY_ID and either JAAS_PRIVATE_KEY or JAAS_PRIVATE_KEY_PATH on the backend, then restart/redeploy.")
    if not re.fullmatch(r"vpaas-magic-cookie-[a-zA-Z0-9]+", app_id) or not key_id.startswith(app_id + "/"):
        raise HTTPException(503, "JaaS App ID and full API Key ID must match the values in your JaaS console.")

    key_path = Path(settings.jaas_private_key_path)
    if not key_path.is_absolute():
        key_path = Path(__file__).resolve().parents[2] / key_path
    now = int(time.time())
    expires_at = now + settings.jaas_token_expire_minutes * 60
    claims = {
        "aud": "jitsi", "iss": "chat", "sub": app_id,
        "iat": now, "nbf": now - 30, "exp": expires_at,
        "room": session.jitsi_room_id,
        "context": {
            "room": {"regex": False},
            # Keep the authenticated EKEEKRTA account identity stable across
            # every class token. JaaS billing still identifies MAUs by device.
            "user": {"id": str(user.id), "name": user.name,
                     "moderator": "true" if is_moderator else "false"},
            "features": {name: False for name in (
                "recording", "livestreaming", "transcription", "sip-inbound-call",
                "sip-outbound-call", "inbound-call", "outbound-call", "file-upload")},
        },
    }
    try:
        signing_key = private_key.replace("\\n", "\n") if private_key else key_path.read_text(encoding="utf-8")
        token = jwt.encode(claims, signing_key,
                           algorithm="RS256", headers={"kid": key_id})
    except Exception:
        # File paths and signing errors can contain sensitive configuration.
        raise HTTPException(503, "JaaS signing key could not be loaded. Check the private key file and its permissions on the backend.") from None
    return dict(provider="jaas", domain="8x8.vc",
                script_url=f"https://8x8.vc/{app_id}/external_api.js",
                room_name=f"{app_id}/{session.jitsi_room_id}",
                jwt=token, expires_at=expires_at)
