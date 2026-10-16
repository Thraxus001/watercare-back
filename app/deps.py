from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from motor.motor_asyncio import AsyncIOMotorDatabase

from .database import get_db
from .models import User, UserRole
from .mongo import get_mongo_client, get_mongo_db
from .permissions import Permission
from .security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncIOMotorDatabase = Depends(get_mongo_db),
) -> User:
    user_id = decode_access_token(token)
    if not user_id:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Invalid or expired credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user_doc = await db["users"].find_one({"id": user_id})
    if not user_doc or not user_doc.get("is_active", True):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Invalid or expired credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return User(**user_doc)


def has_permission(user: User, perm: Permission) -> bool:
    if user.role == UserRole.admin:
        return True
    user_perms = {p if isinstance(p, str) else getattr(p, "permission", str(p)) for p in user.permissions}
    return perm.value in user_perms


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
