from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from motor.motor_asyncio import AsyncIOMotorDatabase

from ..deps import get_current_user
from ..models import User
from ..mongo import get_mongo_db
from ..schemas import Token, UserOut, user_out
from ..security import create_access_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=Token)
async def login(
    form: OAuth2PasswordRequestForm = Depends(),
    db: AsyncIOMotorDatabase = Depends(get_mongo_db),
):
    """Form fields: username (the email) and password."""
    email = form.username.strip().lower()
    user_doc = await db["users"].find_one({"email": email})
    if not user_doc or not verify_password(form.password, user_doc["hashed_password"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    if not user_doc.get("is_active", True):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This account has been deactivated")
    return Token(access_token=create_access_token(user_doc["id"]))


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return user_out(user)
