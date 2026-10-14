from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from .database import get_db
from .models import User, UserRole
from .permissions import Permission
from .security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    user_id = decode_access_token(token)
    user = db.get(User, user_id) if user_id else None
    if not user or not user.is_active:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Invalid or expired credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def has_permission(user: User, perm: Permission) -> bool:
    return user.role == UserRole.admin or perm.value in {p.permission for p in user.permissions}


def require_any(*perms: Permission):
    """Dependency: the user needs at least one of the given permissions (admins always pass)."""

    def dep(user: User = Depends(get_current_user)) -> User:
        if not any(has_permission(user, p) for p in perms):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You don't have permission to do this")
        return user

    return dep


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin access required")
    return user
