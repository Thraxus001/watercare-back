from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from motor.motor_asyncio import AsyncIOMotorDatabase

from ..deps import require_any
from ..models import CheckCategory, InputType, User
from ..mongo import get_mongo_db, get_next_id
from ..permissions import Permission as P
from ..schemas import AnswerOptionOut, AnswerOut, InspectionCreate, InspectionOut, InspectionSummary

router = APIRouter(prefix="/inspections", tags=["inspections"])

can_view = require_any(P.INSPECTIONS_VIEW)
can_create = require_any(P.INSPECTIONS_CREATE)
can_delete = require_any(P.INSPECTIONS_DELETE)


def _format_inspection_summary(doc: dict, machine_name: str, tech_name: str) -> InspectionSummary:
    return InspectionSummary(
        id=doc["id"],
        machine_id=doc["machine_id"],
        machine_name=machine_name,
        performed_by=doc["performed_by"],
        performed_by_name=tech_name,
        performed_at=doc["performed_at"],
        summary=doc.get("summary"),
    )


def _format_inspection_out(doc: dict, machine_name: str, tech_name: str) -> InspectionOut:
    raw_answers = doc.get("answers", [])
    answers = [
        AnswerOut(
            check_item_id=a.get("check_item_id"),
            label=a["check_item_label"],
            category=CheckCategory(a["category"]),
            input_type=InputType(a["input_type"]),
            options=[
                AnswerOptionOut(
                    option_id=o.get("option_id"),
                    label=o["option_label"],
                    is_checked=o.get("is_checked", False),
                )
                for o in a.get("options", [])
            ],
        )
        for a in raw_answers
    ]
    summary = _format_inspection_summary(doc, machine_name, tech_name)
    return InspectionOut(**summary.model_dump(), answers=answers)


@router.post("", response_model=InspectionOut, status_code=201)
async def submit_inspection(
    payload: InspectionCreate,
    db: AsyncIOMotorDatabase = Depends(get_mongo_db),
    user: User = Depends(can_create),
):
    machine = await db["machines"].find_one({"id": payload.machine_id})
    if not machine or not machine.get("is_active", True):
        raise HTTPException(404, "Machine not found or inactive")

    items = await db["check_items"].find({
        "machine_type_id": machine["machine_type_id"],
        "is_active": True,
    }).sort([("category", 1), ("sort_order", 1), ("id", 1)]).to_list(1000)

    if not items:
        raise HTTPException(400, "No checklist has been defined for this machine type yet")

    given: dict[int, set[int]] = {}
    for a in payload.answers:
        if a.check_item_id in given:
            raise HTTPException(422, f"Check item {a.check_item_id} was answered more than once")
        given[a.check_item_id] = set(a.selected_option_ids)

    item_ids = {i["id"] for i in items}
    unknown = set(given) - item_ids
    if unknown:
        raise HTTPException(422, f"Check items {sorted(unknown)} don't belong to this machine's checklist")

    errors, answers = [], []
    for item in items:
        options = [o for o in item.get("options", []) if o.get("is_active", True)]
        selected = given.get(item["id"], set())
        valid_opt_ids = {o["id"] for o in options}

        if selected - valid_opt_ids:
            errors.append(f"'{item['label']}': invalid option selected")
        if item["input_type"] == InputType.radio.value and len(selected) > 1:
            errors.append(f"'{item['label']}': only one option can be chosen")
        if item.get("is_required", False) and not selected:
            errors.append(f"'{item['label']}': this check is required")

        answers.append({
            "check_item_id": item["id"],
            "check_item_label": item["label"],
            "category": item["category"],
            "input_type": item["input_type"],
            "options": [
                {
                    "option_id": o["id"],
                    "option_label": o["label"],
                    "is_checked": o["id"] in selected,
                }
                for o in options
            ],
        })

    if errors:
        raise HTTPException(422, errors)

    new_id = await get_next_id(db, "inspection_id")
    now = datetime.now(timezone.utc)
    inspection_doc = {
        "id": new_id,
        "machine_id": machine["id"],
        "performed_by": user.id,
        "performed_at": now,
        "summary": payload.summary,
        "answers": answers,
    }
    await db["inspections"].insert_one(inspection_doc)

    if payload.note and payload.note.strip():
        note_id = await get_next_id(db, "note_id")
        await db["notes"].insert_one({
            "id": note_id,
            "machine_id": machine["id"],
            "inspection_id": new_id,
            "author_id": user.id,
            "body": payload.note.strip(),
            "created_at": now,
            "updated_at": now,
        })

    return _format_inspection_out(inspection_doc, machine["name"], user.full_name)


@router.get("", response_model=list[InspectionSummary], dependencies=[Depends(can_view)])
async def list_inspections(
    machine_id: Optional[int] = None,
    performed_by: Optional[int] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncIOMotorDatabase = Depends(get_mongo_db),
):
    query = {}
    if machine_id:
        query["machine_id"] = machine_id
    if performed_by:
        query["performed_by"] = performed_by
    if date_from or date_to:
        query["performed_at"] = {}
        if date_from:
            query["performed_at"]["$gte"] = date_from
        if date_to:
            query["performed_at"]["$lte"] = date_to

    docs = await db["inspections"].find(query).sort([("performed_at", -1), ("id", -1)]).skip(offset).limit(limit).to_list(limit)
    if not docs:
        return []

    machine_ids = list({d["machine_id"] for d in docs})
    user_ids = list({d["performed_by"] for d in docs})

    machines = await db["machines"].find({"id": {"$in": machine_ids}}).to_list(len(machine_ids))
    users = await db["users"].find({"id": {"$in": user_ids}}).to_list(len(user_ids))

    m_map = {m["id"]: m["name"] for m in machines}
    u_map = {u["id"]: u["full_name"] for u in users}

    return [
        _format_inspection_summary(d, m_map.get(d["machine_id"], "Unknown"), u_map.get(d["performed_by"], "Unknown"))
        for d in docs
    ]


@router.get("/{inspection_id}", response_model=InspectionOut, dependencies=[Depends(can_view)])
async def get_inspection(inspection_id: int, db: AsyncIOMotorDatabase = Depends(get_mongo_db)):
    i = await db["inspections"].find_one({"id": inspection_id})
    if not i:
        raise HTTPException(404, "Inspection not found")

    m = await db["machines"].find_one({"id": i["machine_id"]})
    u = await db["users"].find_one({"id": i["performed_by"]})

    return _format_inspection_out(
        i,
        m["name"] if m else "Unknown",
        u["full_name"] if u else "Unknown",
    )


@router.delete("/{inspection_id}", status_code=204, dependencies=[Depends(can_delete)])
async def delete_inspection(inspection_id: int, db: AsyncIOMotorDatabase = Depends(get_mongo_db)):
    res = await db["inspections"].delete_one({"id": inspection_id})
    if res.deleted_count == 0:
        raise HTTPException(404, "Inspection not found")
