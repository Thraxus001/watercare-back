from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require_admin
from ..models import User, UserPermission, UserRole
from ..permissions import PERMISSION_DESCRIPTIONS
from ..schemas import PermissionInfo, PermissionsUpdate, UserCreate, UserOut, UserUpdate, user_out
from ..security import hash_password

router = APIRouter(prefix="/users", tags=["users (admin)"], dependencies=[Depends(require_admin)])


@router.get("/permissions", response_model=list[PermissionInfo])
def available_permissions():
    return [PermissionInfo(code=p.value, description=d) for p, d in PERMISSION_DESCRIPTIONS.items()]


@router.get("", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db)):
    return [user_out(u) for u in db.scalars(select(User).order_by(User.full_name))]


@router.post("", response_model=UserOut, status_code=201)
def create_user(payload: UserCreate, db: Session = Depends(get_db)):
    email = payload.email.lower()
    if db.scalar(select(User).where(func.lower(User.email) == email)):
        raise HTTPException(409, "A user with this email already exists")
    user = User(
        email=email,
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        role=payload.role,
        permissions=[UserPermission(permission=p.value) for p in set(payload.permissions)],
    )
    db.add(user)
    db.commit()
    return user_out(user)


@router.get("/{user_id}", response_model=UserOut)
def get_user(user_id: int, db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    return user_out(user)


@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: int, payload: UserUpdate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    data = payload.model_dump(exclude_unset=True)
    if user.id == admin.id and (data.get("is_active") is False or data.get("role") == UserRole.user):
        raise HTTPException(400, "You can't deactivate or demote your own account")
    if "password" in data:
        user.hashed_password = hash_password(data.pop("password"))
    for k, v in data.items():
        setattr(user, k, v)
    db.commit()
    return user_out(user)


@router.put("/{user_id}/permissions", response_model=UserOut)
def set_permissions(user_id: int, payload: PermissionsUpdate, db: Session = Depends(get_db)):
    """Replace the user's granted permissions with exactly this list."""
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    user.permissions = [UserPermission(permission=p.value) for p in set(payload.permissions)]
    db.commit()
    return user_out(user)
