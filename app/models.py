import enum
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class UserRole(str, enum.Enum):
    admin = "admin"
    user = "user"


class CheckCategory(str, enum.Enum):
    operation = "operation"
    maintenance = "maintenance"


class InputType(str, enum.Enum):
    radio = "radio"
    checkbox = "checkbox"


def pg_enum(cls, name):
    # the enum types are created by schema.sql, so don't try to create them here
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e], create_type=False)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    full_name: Mapped[str] = mapped_column(String(150))
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(pg_enum(UserRole, "user_role"), default=UserRole.user)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    permissions: Mapped[list["UserPermission"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )


class UserPermission(Base):
    __tablename__ = "user_permissions"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    permission: Mapped[str] = mapped_column(String(50), primary_key=True)


class MachineType(Base):
    __tablename__ = "machine_types"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text)


class Machine(Base):
    __tablename__ = "machines"
    id: Mapped[int] = mapped_column(primary_key=True)
    machine_type_id: Mapped[int] = mapped_column(ForeignKey("machine_types.id"))
    name: Mapped[str] = mapped_column(String(150))
    serial_number: Mapped[str] = mapped_column(String(100), unique=True)
    location: Mapped[Optional[str]] = mapped_column(String(255))
    installed_on: Mapped[Optional[date]] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    machine_type: Mapped[MachineType] = relationship(lazy="joined")


class CheckItem(Base):
    __tablename__ = "check_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    machine_type_id: Mapped[int] = mapped_column(ForeignKey("machine_types.id", ondelete="CASCADE"))
    category: Mapped[CheckCategory] = mapped_column(pg_enum(CheckCategory, "check_category"))
    label: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text)
    input_type: Mapped[InputType] = mapped_column(pg_enum(InputType, "input_type"))
    is_required: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    options: Mapped[list["CheckItemOption"]] = relationship(
        order_by="CheckItemOption.sort_order, CheckItemOption.id",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class CheckItemOption(Base):
    __tablename__ = "check_item_options"
    id: Mapped[int] = mapped_column(primary_key=True)
    check_item_id: Mapped[int] = mapped_column(ForeignKey("check_items.id", ondelete="CASCADE"))
    label: Mapped[str] = mapped_column(String(200))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Inspection(Base):
    __tablename__ = "inspections"
    id: Mapped[int] = mapped_column(primary_key=True)
    machine_id: Mapped[int] = mapped_column(ForeignKey("machines.id"))
    performed_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    performed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    summary: Mapped[Optional[str]] = mapped_column(Text)
    machine: Mapped[Machine] = relationship(lazy="joined")
    technician: Mapped[User] = relationship(lazy="joined")
    answers: Mapped[list["InspectionAnswer"]] = relationship(
        order_by="InspectionAnswer.id", cascade="all, delete-orphan", lazy="selectin"
    )


class InspectionAnswer(Base):
    __tablename__ = "inspection_answers"
    id: Mapped[int] = mapped_column(primary_key=True)
    inspection_id: Mapped[int] = mapped_column(ForeignKey("inspections.id", ondelete="CASCADE"))
    check_item_id: Mapped[Optional[int]] = mapped_column(ForeignKey("check_items.id", ondelete="SET NULL"))
    check_item_label: Mapped[str] = mapped_column(String(255))
    category: Mapped[CheckCategory] = mapped_column(pg_enum(CheckCategory, "check_category"))
    input_type: Mapped[InputType] = mapped_column(pg_enum(InputType, "input_type"))
    options: Mapped[list["InspectionAnswerOption"]] = relationship(
        order_by="InspectionAnswerOption.id", cascade="all, delete-orphan", lazy="selectin"
    )


class InspectionAnswerOption(Base):
    __tablename__ = "inspection_answer_options"
    id: Mapped[int] = mapped_column(primary_key=True)
    answer_id: Mapped[int] = mapped_column(ForeignKey("inspection_answers.id", ondelete="CASCADE"))
    option_id: Mapped[Optional[int]] = mapped_column(ForeignKey("check_item_options.id", ondelete="SET NULL"))
    option_label: Mapped[str] = mapped_column(String(200))
    is_checked: Mapped[bool] = mapped_column(Boolean, default=False)


class MachineNote(Base):
    __tablename__ = "machine_notes"
    id: Mapped[int] = mapped_column(primary_key=True)
    machine_id: Mapped[int] = mapped_column(ForeignKey("machines.id", ondelete="CASCADE"))
    inspection_id: Mapped[Optional[int]] = mapped_column(ForeignKey("inspections.id", ondelete="SET NULL"))
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    author: Mapped[User] = relationship(lazy="joined")
