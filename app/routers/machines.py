from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require_any
from ..models import Inspection, Machine, MachineType, User
from ..permissions import Permission as P
from ..schemas import LastInspection, MachineCreate, MachineOut, MachineUpdate

router = APIRouter(prefix="/machines", tags=["machines"])

can_view = require_any(P.MACHINES_VIEW, P.MACHINES_MANAGE, P.INSPECTIONS_VIEW, P.INSPECTIONS_CREATE)
can_manage = require_any(P.MACHINES_MANAGE)


def last_inspections(db: Session, machine_ids: list[int]) -> dict[int, LastInspection]:
    if not machine_ids:
        return {}
    rows = db.execute(
        select(Inspection.machine_id, Inspection.id, Inspection.performed_at, User.full_name)
        .join(User, User.id == Inspection.performed_by)
        .where(Inspection.machine_id.in_(machine_ids))
        .distinct(Inspection.machine_id)
        .order_by(Inspection.machine_id, Inspection.performed_at.desc(), Inspection.id.desc())
    ).all()
    return {r[0]: LastInspection(id=r[1], performed_at=r[2], performed_by_name=r[3]) for r in rows}


def machine_out(m: Machine, last: Optional[LastInspection]) -> MachineOut:
    return MachineOut(
        id=m.id, name=m.name, serial_number=m.serial_number, location=m.location, installed_on=m.installed_on,
        is_active=m.is_active, machine_type_id=m.machine_type_id, machine_type_name=m.machine_type.name,
        last_inspection=last,
    )


@router.get("", response_model=list[MachineOut], dependencies=[Depends(can_view)])
def list_machines(
    q: Optional[str] = None,
    machine_type_id: Optional[int] = None,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
):
    stmt = select(Machine).order_by(Machine.name)
    if not include_inactive:
        stmt = stmt.where(Machine.is_active)
    if machine_type_id:
        stmt = stmt.where(Machine.machine_type_id == machine_type_id)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(Machine.name.ilike(like) | Machine.serial_number.ilike(like) | Machine.location.ilike(like))
    machines = db.scalars(stmt).all()
    last = last_inspections(db, [m.id for m in machines])
    return [machine_out(m, last.get(m.id)) for m in machines]


@router.get("/{machine_id}", response_model=MachineOut, dependencies=[Depends(can_view)])
def get_machine(machine_id: int, db: Session = Depends(get_db)):
    m = db.get(Machine, machine_id)
    if not m:
        raise HTTPException(404, "Machine not found")
    return machine_out(m, last_inspections(db, [m.id]).get(m.id))


@router.post("", response_model=MachineOut, status_code=201, dependencies=[Depends(can_manage)])
def create_machine(payload: MachineCreate, db: Session = Depends(get_db)):
    if not db.get(MachineType, payload.machine_type_id):
        raise HTTPException(422, "Unknown machine type")
    m = Machine(**payload.model_dump())
    db.add(m)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A machine with this serial number already exists")
    db.refresh(m)
    return machine_out(m, None)


@router.patch("/{machine_id}", response_model=MachineOut, dependencies=[Depends(can_manage)])
def update_machine(machine_id: int, payload: MachineUpdate, db: Session = Depends(get_db)):
    m = db.get(Machine, machine_id)
    if not m:
        raise HTTPException(404, "Machine not found")
    data = payload.model_dump(exclude_unset=True)
    if "machine_type_id" in data and not db.get(MachineType, data["machine_type_id"]):
        raise HTTPException(422, "Unknown machine type")
    for k, v in data.items():
        setattr(m, k, v)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A machine with this serial number already exists")
    db.refresh(m)
    return machine_out(m, last_inspections(db, [m.id]).get(m.id))
