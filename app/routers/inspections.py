from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require_any
from ..models import (
    CheckItem, InputType, Inspection, InspectionAnswer, InspectionAnswerOption, Machine, MachineNote, User,
)
from ..permissions import Permission as P
from ..schemas import AnswerOptionOut, AnswerOut, InspectionCreate, InspectionOut, InspectionSummary

router = APIRouter(prefix="/inspections", tags=["inspections"])

can_view = require_any(P.INSPECTIONS_VIEW)
can_create = require_any(P.INSPECTIONS_CREATE)
can_delete = require_any(P.INSPECTIONS_DELETE)


def summary_out(i: Inspection) -> InspectionSummary:
    return InspectionSummary(
        id=i.id, machine_id=i.machine_id, machine_name=i.machine.name, performed_by=i.performed_by,
        performed_by_name=i.technician.full_name, performed_at=i.performed_at, summary=i.summary,
    )


def inspection_out(i: Inspection) -> InspectionOut:
    answers = [
        AnswerOut(
            check_item_id=a.check_item_id, label=a.check_item_label, category=a.category, input_type=a.input_type,
            options=[AnswerOptionOut(option_id=o.option_id, label=o.option_label, is_checked=o.is_checked) for o in a.options],
        )
        for a in i.answers
    ]
    return InspectionOut(**summary_out(i).model_dump(), answers=answers)


@router.post("", response_model=InspectionOut, status_code=201)
def submit_inspection(payload: InspectionCreate, db: Session = Depends(get_db), user: User = Depends(can_create)):
    machine = db.get(Machine, payload.machine_id)
    if not machine or not machine.is_active:
        raise HTTPException(404, "Machine not found or inactive")

    items = db.scalars(
        select(CheckItem)
        .where(CheckItem.machine_type_id == machine.machine_type_id, CheckItem.is_active)
        .order_by(CheckItem.category, CheckItem.sort_order, CheckItem.id)
    ).all()
    if not items:
        raise HTTPException(400, "No checklist has been defined for this machine type yet")

    given: dict[int, set[int]] = {}
    for a in payload.answers:
        if a.check_item_id in given:
            raise HTTPException(422, f"Check item {a.check_item_id} was answered more than once")
        given[a.check_item_id] = set(a.selected_option_ids)

    unknown = set(given) - {i.id for i in items}
    if unknown:
        raise HTTPException(422, f"Check items {sorted(unknown)} don't belong to this machine's checklist")

    errors, answers = [], []
    for item in items:
        options = [o for o in item.options if o.is_active]
        selected = given.get(item.id, set())
        if selected - {o.id for o in options}:
            errors.append(f"'{item.label}': invalid option selected")
        if item.input_type == InputType.radio and len(selected) > 1:
            errors.append(f"'{item.label}': only one option can be chosen")
        if item.is_required and not selected:
            errors.append(f"'{item.label}': this check is required")
        answers.append(
            InspectionAnswer(
                check_item_id=item.id, check_item_label=item.label, category=item.category, input_type=item.input_type,
                options=[
                    InspectionAnswerOption(option_id=o.id, option_label=o.label, is_checked=o.id in selected)
                    for o in options
                ],
            )
        )
    if errors:
        raise HTTPException(422, errors)

    inspection = Inspection(machine_id=machine.id, performed_by=user.id, summary=payload.summary, answers=answers)
    db.add(inspection)
    db.flush()
    if payload.note and payload.note.strip():
        db.add(MachineNote(machine_id=machine.id, inspection_id=inspection.id, author_id=user.id, body=payload.note.strip()))
    db.commit()
    db.refresh(inspection)
    return inspection_out(inspection)


@router.get("", response_model=list[InspectionSummary], dependencies=[Depends(can_view)])
def list_inspections(
    machine_id: Optional[int] = None,
    performed_by: Optional[int] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    stmt = select(Inspection).order_by(Inspection.performed_at.desc(), Inspection.id.desc())
    if machine_id:
        stmt = stmt.where(Inspection.machine_id == machine_id)
    if performed_by:
        stmt = stmt.where(Inspection.performed_by == performed_by)
    if date_from:
        stmt = stmt.where(Inspection.performed_at >= date_from)
    if date_to:
        stmt = stmt.where(Inspection.performed_at <= date_to)
    return [summary_out(i) for i in db.scalars(stmt.limit(limit).offset(offset)).unique()]


@router.get("/{inspection_id}", response_model=InspectionOut, dependencies=[Depends(can_view)])
def get_inspection(inspection_id: int, db: Session = Depends(get_db)):
    i = db.get(Inspection, inspection_id)
    if not i:
        raise HTTPException(404, "Inspection not found")
    return inspection_out(i)


@router.delete("/{inspection_id}", status_code=204, dependencies=[Depends(can_delete)])
def delete_inspection(inspection_id: int, db: Session = Depends(get_db)):
    i = db.get(Inspection, inspection_id)
    if not i:
        raise HTTPException(404, "Inspection not found")
    db.delete(i)
    db.commit()
