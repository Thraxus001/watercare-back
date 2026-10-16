import enum
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field


class UserRole(str, enum.Enum):
    admin = "admin"
    user = "user"


class CheckCategory(str, enum.Enum):
    operation = "operation"
    maintenance = "maintenance"


class InputType(str, enum.Enum):
    radio = "radio"
    checkbox = "checkbox"


class User(BaseModel):
    id: int
    email: str
    full_name: str
    hashed_password: str
    role: UserRole = UserRole.user
    is_active: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    permissions: list[str] = []
