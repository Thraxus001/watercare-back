from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require_any
from ..models import CheckItem, CheckItemOption, Machine, MachineType
from ..permissions import Permission as P
from ..schemas import (
    CheckItemCreate, CheckItemOut, CheckItemUpdate, MachineTypeCreate, MachineTypeOut,
    MachineTypeUpdate, OptionIn, OptionOut, OptionUpdate, min_options,
)

router = APIRouter(tags=["checklists"])

can_view = require_any(P.CHECKLISTS_VIEW, P.CHECKLISTS_MANAGE, P.INSPECTIONS_CREATE, P.MACHINES_VIEW)
can_manage = require_any(P.CHECKLISTS_MANAGE)


def item_out(item: CheckItem, include_inactive: bool = False) -> CheckItemOut:
    opts = [o for o in item.options if include_inactive or o.is_active]
    return CheckItemOut(
        id=item.id, machine_type_id=item.machine_type_id, category=item.category, label=item.label,
        description=item.description, input_type=item.input_type, is_required=item.is_required,
        sort_order=item.sort_order, is_active=item.is_active,
        options=[OptionOut.model_validate(o) for o in opts],
    )


def get_item(db: Session, item_id: int) -> CheckItem:
    item = db.get(CheckItem, item_id)
    if not item:
        raise HTTPException(404, "Check item not found")
    return item


# ───────────── Machine types ─────────────
@router.get("/machine-types", response_model=list[MachineTypeOut], dependencies=[Depends(can_view)])
def list_machine_types(db: Session = Depends(get_db)):
    return db.scalars(select(MachineType).order_by(MachineType.name)).all()


@router.post("/machine-types", response_model=MachineTypeOut, status_code=201, dependencies=[Depends(can_manage)])
def create_machine_type(payload: MachineTypeCreate, db: Session = Depends(get_db)):
    mt = MachineType(**payload.model_dump())
    db.add(mt)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A machine type with this name already exists")
    return mt


@router.patch("/machine-types/{type_id}", response_model=MachineTypeOut, dependencies=[Depends(can_manage)])
def update_machine_type(type_id: int, payload: MachineTypeUpdate, db: Session = Depends(get_db)):
    mt = db.get(MachineType, type_id)
    if not mt:
        raise HTTPException(404, "Machine type not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(mt, k, v)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A machine type with this name already exists")
    return mt


@router.delete("/machine-types/{type_id}", status_code=204, dependencies=[Depends(can_manage)])
def delete_machine_type(type_id: int, db: Session = Depends(get_db)):
    mt = db.get(MachineType, type_id)
    if not mt:
        raise HTTPException(404, "Machine type not found")
    if db.scalar(select(Machine.id).where(Machine.machine_type_id == type_id).limit(1)):
        raise HTTPException(409, "Machines still use this type; reassign or deactivate them first")
    db.delete(mt)
    db.commit()


# ───────────── Check items ─────────────
@router.get("/machine-types/{type_id}/check-items", response_model=list[CheckItemOut], dependencies=[Depends(can_view)])
def list_check_items(type_id: int, include_inactive: bool = False, db: Session = Depends(get_db)):
    if not db.get(MachineType, type_id):
        raise HTTPException(404, "Machine type not found")
    q = select(CheckItem).where(CheckItem.machine_type_id == type_id)
    if not include_inactive:
        q = q.where(CheckItem.is_active)
    q = q.order_by(CheckItem.category, CheckItem.sort_order, CheckItem.id)
    return [item_out(i, include_inactive) for i in db.scalars(q)]


@router.post("/machine-types/{type_id}/check-items", response_model=CheckItemOut, status_code=201, dependencies=[Depends(can_manage)])
def create_check_item(type_id: int, payload: CheckItemCreate, db: Session = Depends(get_db)):
    if not db.get(MachineType, type_id):
        raise HTTPException(404, "Machine type not found")
    data = payload.model_dump(exclude={"options"})
    item = CheckItem(machine_type_id=type_id, **data)
    item.options = [
        CheckItemOption(label=o.label.strip(), sort_order=o.sort_order or idx) for idx, o in enumerate(payload.options)
    ]
    db.add(item)
    db.commit()
    return item_out(item)


@router.patch("/check-items/{item_id}", response_model=CheckItemOut, dependencies=[Depends(can_manage)])
def update_check_item(item_id: int, payload: CheckItemUpdate, db: Session = Depends(get_db)):
    item = get_item(db, item_id)
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(item, k, v)
    db.commit()
    return item_out(item, include_inactive=True)


@router.delete("/check-items/{item_id}", status_code=204, dependencies=[Depends(can_manage)])
def archive_check_item(item_id: int, db: Session = Depends(get_db)):
    """Archives the check (keeps past checkups intact); it no longer appears on new checkups."""
    get_item(db, item_id).is_active = False
    db.commit()


# ───────────── Options ─────────────
@router.post("/check-items/{item_id}/options", response_model=OptionOut, status_code=201, dependencies=[Depends(can_manage)])
def add_option(item_id: int, payload: OptionIn, db: Session = Depends(get_db)):
    item = get_item(db, item_id)
    if any(o.is_active and o.label.strip().lower() == payload.label.strip().lower() for o in item.options):
        raise HTTPException(409, "This check already has an option with that label")
    opt = CheckItemOption(check_item_id=item.id, label=payload.label.strip(), sort_order=payload.sort_order)
    db.add(opt)
    db.commit()
    return opt


def _active_count(item: CheckItem, excluding: Optional[int] = None) -> int:
    return sum(1 for o in item.options if o.is_active and o.id != excluding)


@router.patch("/check-item-options/{option_id}", response_model=OptionOut, dependencies=[Depends(can_manage)])
def update_option(option_id: int, payload: OptionUpdate, db: Session = Depends(get_db)):
    opt = db.get(CheckItemOption, option_id)
    if not opt:
        raise HTTPException(404, "Option not found")
    item = get_item(db, opt.check_item_id)
    data = payload.model_dump(exclude_unset=True)
    if data.get("is_active") is False and _active_count(item, opt.id) < min_options(item.input_type):
        raise HTTPException(400, f"A {item.input_type.value} check needs at least {min_options(item.input_type)} active option(s)")
    for k, v in data.items():
        setattr(opt, k, v)
    db.commit()
    return opt


@router.delete("/check-item-options/{option_id}", status_code=204, dependencies=[Depends(can_manage)])
def archive_option(option_id: int, db: Session = Depends(get_db)):
    opt = db.get(CheckItemOption, option_id)
    if not opt:
        raise HTTPException(404, "Option not found")
    item = get_item(db, opt.check_item_id)
    if _active_count(item, opt.id) < min_options(item.input_type):
        raise HTTPException(400, f"A {item.input_type.value} check needs at least {min_options(item.input_type)} active option(s)")
    opt.is_active = False
    db.commit()
