from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase

from ..deps import require_admin
from ..models import User, UserRole
from ..mongo import get_mongo_db, get_next_id
from ..permissions import PERMISSION_DESCRIPTIONS
from ..schemas import PermissionInfo, PermissionsUpdate, UserCreate, UserOut, UserUpdate, user_out
from ..security import hash_password

router = APIRouter(prefix="/users", tags=["users (admin)"], dependencies=[Depends(require_admin)])


@router.get("/permissions", response_model=list[PermissionInfo])
def available_permissions():
    return [PermissionInfo(code=p.value, description=d) for p, d in PERMISSION_DESCRIPTIONS.items()]


@router.get("", response_model=list[UserOut])
async def list_users(db: AsyncIOMotorDatabase = Depends(get_mongo_db)):
    docs = await db["users"].find().sort("full_name", 1).to_list(1000)
    return [user_out(User(**d)) for d in docs]


@router.post("", response_model=UserOut, status_code=201)
async def create_user(payload: UserCreate, db: AsyncIOMotorDatabase = Depends(get_mongo_db)):
    email = payload.email.lower()
    if await db["users"].find_one({"email": email}):
        raise HTTPException(409, "A user with this email already exists")

    new_id = await get_next_id(db, "user_id")
    user_data = {
        "id": new_id,
        "email": email,
        "full_name": payload.full_name,
        "hashed_password": hash_password(payload.password),
        "role": payload.role.value if isinstance(payload.role, UserRole) else payload.role,
        "is_active": True,
        "created_at": datetime.now(timezone.utc),
        "permissions": [p.value for p in set(payload.permissions)],
    }
    await db["users"].insert_one(user_data)
    return user_out(User(**user_data))


@router.get("/{user_id}", response_model=UserOut)
async def get_user(user_id: int, db: AsyncIOMotorDatabase = Depends(get_mongo_db)):
    doc = await db["users"].find_one({"id": user_id})
    if not doc:
        raise HTTPException(404, "User not found")
    return user_out(User(**doc))


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int,
    payload: UserUpdate,
    db: AsyncIOMotorDatabase = Depends(get_mongo_db),
    admin: User = Depends(require_admin),
):
    doc = await db["users"].find_one({"id": user_id})
    if not doc:
        raise HTTPException(404, "User not found")

    data = payload.model_dump(exclude_unset=True)
    if user_id == admin.id and (data.get("is_active") is False or data.get("role") == UserRole.user):
        raise HTTPException(400, "You can't deactivate or demote your own account")

    if "password" in data:
        data["hashed_password"] = hash_password(data.pop("password"))
    if "role" in data and isinstance(data["role"], UserRole):
        data["role"] = data["role"].value

    if data:
        await db["users"].update_one({"id": user_id}, {"$set": data})
        doc.update(data)

    return user_out(User(**doc))


@router.put("/{user_id}/permissions", response_model=UserOut)
async def set_permissions(
    user_id: int,
    payload: PermissionsUpdate,
    db: AsyncIOMotorDatabase = Depends(get_mongo_db),
):
    """Replace the user's granted permissions with exactly this list."""
    doc = await db["users"].find_one({"id": user_id})
    if not doc:
        raise HTTPException(404, "User not found")

    perms = [p.value for p in set(payload.permissions)]
    await db["users"].update_one({"id": user_id}, {"$set": {"permissions": perms}})
    doc["permissions"] = perms
    return user_out(User(**doc))
