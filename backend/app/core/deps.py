from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.security import decode_access_token
from app.models.user import User, UserRole
from app.models.institution import InstitutionStatus
from app.core.access import tenant
from app.core.institution_domains import request_login_host, institution_for_host

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def ensure_institution_active(user: User) -> None:
    institution = user.institution
    status_value = getattr(institution, "status", InstitutionStatus.active.value) if institution else None
    if status_value == InstitutionStatus.pending.value:
        raise HTTPException(status_code=403, detail="Institution registration is awaiting Ekeekrta review.")
    if status_value == InstitutionStatus.suspended.value:
        raise HTTPException(status_code=403, detail="Institution access is suspended. Contact Ekeekrta support.")
    if status_value == InstitutionStatus.rejected.value:
        raise HTTPException(status_code=403, detail="Institution registration was not approved. Contact Ekeekrta support.")
    if status_value != InstitutionStatus.active.value:
        raise HTTPException(status_code=403, detail="Institution access is unavailable. Contact Ekeekrta support.")


def get_authenticated_user(request: Request, token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(token)
        user_id = payload.get("sub")
        if user_id is None:
            raise credentials_exception
        user_id = int(user_id)
    except (JWTError, ValueError, TypeError):
        raise credentials_exception

    user = db.query(User).filter(User.id == int(user_id)).first()
    if user is None:
        raise credentials_exception
    if int(payload.get("session_version", 0)) != int(user.session_version or 0):
        raise credentials_exception
    host = request_login_host(request)
    if payload.get("login_host") and payload["login_host"] != host:
        raise credentials_exception
    if user.role == UserRole.platform_admin:
        # Platform operators are deliberately outside every institution tenant.
        if user.institution_id is not None or host:
            raise credentials_exception
    else:
        tenant(user)
        ensure_institution_active(user)
        if host and institution_for_host(host, db).id != user.institution_id:
            raise credentials_exception
    return user


def get_current_user(current_user: User = Depends(get_authenticated_user)) -> User:
    if current_user.must_change_password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Change your temporary password before using EKEEKRTA",
        )
    return current_user


def require_roles(*roles: UserRole):
    """Dependency factory - e.g. Depends(require_roles(UserRole.faculty, UserRole.admin))"""

    def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action",
            )
        return current_user

    return role_checker
