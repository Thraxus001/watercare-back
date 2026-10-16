from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from .models import CheckCategory, InputType, User, UserRole
from .permissions import Permission


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ───────────── Auth / users ─────────────
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    permissions: list[str]  # effective permissions (admins get all)


def user_out(u: User) -> UserOut:
    if u.role == UserRole.admin:
        perms = [p.value for p in Permission]
    else:
        perms = sorted(p if isinstance(p, str) else getattr(p, "permission", str(p)) for p in u.permissions)
    return UserOut(
        id=u.id, email=u.email, full_name=u.full_name, role=u.role, is_active=u.is_active, permissions=perms
    )


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=150)
    password: str = Field(min_length=8, max_length=72)
    role: UserRole = UserRole.user
    permissions: list[Permission] = []


class UserUpdate(BaseModel):
    full_name: Optional[str] = Field(None, min_length=1, max_length=150)
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None
    password: Optional[str] = Field(None, min_length=8, max_length=72)


class PermissionsUpdate(BaseModel):
    permissions: list[Permission]


class PermissionInfo(BaseModel):
    code: str
    description: str


# ───────────── Machine types & checklists ─────────────
class MachineTypeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    description: Optional[str] = None


class MachineTypeUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=150)
    description: Optional[str] = None


class MachineTypeOut(ORM):
    id: int
    name: str
    description: Optional[str]


class OptionIn(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    sort_order: int = 0


class OptionUpdate(BaseModel):
    label: Optional[str] = Field(None, min_length=1, max_length=200)
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class OptionOut(ORM):
    id: int
    label: str
    sort_order: int
    is_active: bool


def min_options(input_type: InputType) -> int:
    return 2 if input_type == InputType.radio else 1


class CheckItemCreate(BaseModel):
    category: CheckCategory
    label: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    input_type: InputType
    is_required: bool = False
    sort_order: int = 0
    options: list[OptionIn]

    @model_validator(mode="after")
    def check_options(self):
        need = min_options(self.input_type)
        if len(self.options) < need:
            raise ValueError(f"A {self.input_type.value} check needs at least {need} option(s)")
        labels = [o.label.strip().lower() for o in self.options]
        if len(set(labels)) != len(labels):
            raise ValueError("Option labels must be unique within a check")
        return self


class CheckItemUpdate(BaseModel):
    # input_type is intentionally not editable once created
    category: Optional[CheckCategory] = None
    label: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    is_required: Optional[bool] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class CheckItemOut(BaseModel):
    id: int
    machine_type_id: int
    category: CheckCategory
    label: str
    description: Optional[str]
    input_type: InputType
    is_required: bool
    sort_order: int
    is_active: bool
    options: list[OptionOut]


# ───────────── Plants ─────────────
class PlantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    code: Optional[str] = Field(None, max_length=50)
    location: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None


class PlantUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=150)
    code: Optional[str] = Field(None, max_length=50)
    location: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    is_active: Optional[bool] = None


class PlantOut(BaseModel):
    id: int
    name: str
    code: Optional[str] = None
    location: str
    description: Optional[str] = None
    is_active: bool = True
    machine_count: int = 0
    active_machines_count: int = 0
    last_inspection: Optional["LastInspection"] = None


# ───────────── Machines ─────────────
class MachineCreate(BaseModel):
    plant_id: Optional[int] = None
    machine_type_id: int
    name: str = Field(min_length=1, max_length=150)
    serial_number: str = Field(min_length=1, max_length=100)
    location: Optional[str] = None
    installed_on: Optional[date] = None


class MachineUpdate(BaseModel):
    plant_id: Optional[int] = None
    machine_type_id: Optional[int] = None
    name: Optional[str] = Field(None, min_length=1, max_length=150)
    serial_number: Optional[str] = Field(None, min_length=1, max_length=100)
    location: Optional[str] = None
    installed_on: Optional[date] = None
    is_active: Optional[bool] = None


class LastInspection(BaseModel):
    id: int
    performed_at: datetime
    performed_by_name: str


class MachineOut(BaseModel):
    id: int
    plant_id: Optional[int] = None
    plant_name: Optional[str] = None
    plant_location: Optional[str] = None
    name: str
    serial_number: str
    location: Optional[str]
    installed_on: Optional[date]
    is_active: bool
    machine_type_id: int
    machine_type_name: str
    last_inspection: Optional[LastInspection] = None


# ───────────── Inspections ─────────────
class AnswerIn(BaseModel):
    check_item_id: int
    selected_option_ids: list[int] = []


class InspectionCreate(BaseModel):
    machine_id: int
    summary: Optional[str] = None
    note: Optional[str] = Field(None, description="Optional note saved on the machine and linked to this checkup")
    answers: list[AnswerIn]


class AnswerOptionOut(BaseModel):
    option_id: Optional[int]
    label: str
    is_checked: bool


class AnswerOut(BaseModel):
    check_item_id: Optional[int]
    label: str
    category: CheckCategory
    input_type: InputType
    options: list[AnswerOptionOut]


class InspectionSummary(BaseModel):
    id: int
    machine_id: int
    machine_name: str
    performed_by: int
    performed_by_name: str
    performed_at: datetime
    summary: Optional[str]


class InspectionOut(InspectionSummary):
    answers: list[AnswerOut]


# ───────────── Notes ─────────────
class NoteCreate(BaseModel):
    body: str = Field(min_length=1, max_length=5000)
    inspection_id: Optional[int] = None


class NoteUpdate(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


class NoteOut(BaseModel):
    id: int
    machine_id: int
    inspection_id: Optional[int]
    author_id: int
    author_name: str
    body: str
    created_at: datetime
    updated_at: datetime
