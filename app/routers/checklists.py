import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase

from ..deps import require_any
from ..models import CheckCategory, InputType
from ..mongo import get_mongo_db, get_next_id
from ..permissions import Permission as P
from ..schemas import (
    CheckItemCreate, CheckItemOut, CheckItemUpdate, MachineTypeCreate, MachineTypeOut,
    MachineTypeUpdate, OptionIn, OptionOut, OptionUpdate, min_options,
)

router = APIRouter(tags=["checklists"])

can_view = require_any(P.CHECKLISTS_VIEW, P.CHECKLISTS_MANAGE, P.INSPECTIONS_CREATE, P.MACHINES_VIEW)
can_manage = require_any(P.CHECKLISTS_MANAGE)


def _format_item_out(doc: dict, include_inactive: bool = False) -> CheckItemOut:
    raw_options = doc.get("options", [])
    opts = [o for o in raw_options if include_inactive or o.get("is_active", True)]
    return CheckItemOut(
        id=doc["id"],
        machine_type_id=doc["machine_type_id"],
        category=CheckCategory(doc["category"]),
        label=doc["label"],
        description=doc.get("description"),
        input_type=InputType(doc["input_type"]),
        is_required=doc.get("is_required", False),
        sort_order=doc.get("sort_order", 0),
        is_active=doc.get("is_active", True),
        options=[
            OptionOut(
                id=o["id"],
                label=o["label"],
                sort_order=o.get("sort_order", 0),
                is_active=o.get("is_active", True),
            )
            for o in opts
        ],
    )


# ───────────── Machine types ─────────────
@router.get("/machine-types", response_model=list[MachineTypeOut], dependencies=[Depends(can_view)])
async def list_machine_types(db: AsyncIOMotorDatabase = Depends(get_mongo_db)):
    docs = await db["machine_types"].find().sort("name", 1).to_list(1000)
    return [MachineTypeOut(id=d["id"], name=d["name"], description=d.get("description")) for d in docs]


@router.post("/machine-types", response_model=MachineTypeOut, status_code=201, dependencies=[Depends(can_manage)])
async def create_machine_type(payload: MachineTypeCreate, db: AsyncIOMotorDatabase = Depends(get_mongo_db)):
    name = payload.name.strip()
    existing = await db["machine_types"].find_one({"name": {"$regex": f"^{re.escape(name)}$", "$options": "i"}})
    if existing:
        raise HTTPException(409, "A machine type with this name already exists")

    new_id = await get_next_id(db, "machine_type_id")
    data = {"id": new_id, "name": name, "description": payload.description}
    await db["machine_types"].insert_one(data)
    return MachineTypeOut(**data)


@router.patch("/machine-types/{type_id}", response_model=MachineTypeOut, dependencies=[Depends(can_manage)])
async def update_machine_type(
    type_id: int,
    payload: MachineTypeUpdate,
    db: AsyncIOMotorDatabase = Depends(get_mongo_db),
):
    mt = await db["machine_types"].find_one({"id": type_id})
    if not mt:
        raise HTTPException(404, "Machine type not found")

    data = payload.model_dump(exclude_unset=True)
    if "name" in data:
        name = data["name"].strip()
        conflict = await db["machine_types"].find_one(
            {"name": {"$regex": f"^{re.escape(name)}$", "$options": "i"}, "id": {"$ne": type_id}}
        )
        if conflict:
            raise HTTPException(409, "A machine type with this name already exists")
        data["name"] = name

    if data:
        await db["machine_types"].update_one({"id": type_id}, {"$set": data})
        mt.update(data)

    return MachineTypeOut(id=mt["id"], name=mt["name"], description=mt.get("description"))


@router.delete("/machine-types/{type_id}", status_code=204, dependencies=[Depends(can_manage)])
async def delete_machine_type(type_id: int, db: AsyncIOMotorDatabase = Depends(get_mongo_db)):
    mt = await db["machine_types"].find_one({"id": type_id})
    if not mt:
        raise HTTPException(404, "Machine type not found")

    if await db["machines"].find_one({"machine_type_id": type_id}):
        raise HTTPException(409, "Machines still use this type; reassign or deactivate them first")

    await db["machine_types"].delete_one({"id": type_id})


# ───────────── Check items ─────────────
@router.get("/machine-types/{type_id}/check-items", response_model=list[CheckItemOut], dependencies=[Depends(can_view)])
async def list_check_items(
    type_id: int,
    include_inactive: bool = False,
    db: AsyncIOMotorDatabase = Depends(get_mongo_db),
):
    if not await db["machine_types"].find_one({"id": type_id}):
        raise HTTPException(404, "Machine type not found")

    query = {"machine_type_id": type_id}
    if not include_inactive:
        query["is_active"] = True

    docs = await db["check_items"].find(query).sort([("category", 1), ("sort_order", 1), ("id", 1)]).to_list(1000)
    return [_format_item_out(d, include_inactive) for d in docs]


@router.post("/machine-types/{type_id}/check-items", response_model=CheckItemOut, status_code=201, dependencies=[Depends(can_manage)])
async def create_check_item(
    type_id: int,
    payload: CheckItemCreate,
    db: AsyncIOMotorDatabase = Depends(get_mongo_db),
):
    if not await db["machine_types"].find_one({"id": type_id}):
        raise HTTPException(404, "Machine type not found")

    new_id = await get_next_id(db, "check_item_id")
    options = []
    for idx, o in enumerate(payload.options):
        opt_id = await get_next_id(db, "option_id")
        options.append({
            "id": opt_id,
            "label": o.label.strip(),
            "sort_order": o.sort_order if o.sort_order is not None else idx,
            "is_active": True,
        })

    item_data = {
        "id": new_id,
        "machine_type_id": type_id,
        "category": payload.category.value,
        "label": payload.label.strip(),
        "description": payload.description,
        "input_type": payload.input_type.value,
        "is_required": payload.is_required,
        "sort_order": payload.sort_order,
        "is_active": True,
        "created_at": datetime.now(timezone.utc),
        "options": options,
    }
    await db["check_items"].insert_one(item_data)
    return _format_item_out(item_data, include_inactive=True)


@router.patch("/check-items/{item_id}", response_model=CheckItemOut, dependencies=[Depends(can_manage)])
async def update_check_item(
    item_id: int,
    payload: CheckItemUpdate,
    db: AsyncIOMotorDatabase = Depends(get_mongo_db),
):
    item = await db["check_items"].find_one({"id": item_id})
    if not item:
        raise HTTPException(404, "Check item not found")

    data = payload.model_dump(exclude_unset=True)
    if "category" in data and isinstance(data["category"], CheckCategory):
        data["category"] = data["category"].value

    if data:
        await db["check_items"].update_one({"id": item_id}, {"$set": data})
        item.update(data)

    return _format_item_out(item, include_inactive=True)


@router.delete("/check-items/{item_id}", status_code=204, dependencies=[Depends(can_manage)])
async def archive_check_item(item_id: int, db: AsyncIOMotorDatabase = Depends(get_mongo_db)):
    """Archives the check (keeps past checkups intact); it no longer appears on new checkups."""
    res = await db["check_items"].update_one({"id": item_id}, {"$set": {"is_active": False}})
    if res.matched_count == 0:
        raise HTTPException(404, "Check item not found")


# ───────────── Options ─────────────
@router.post("/check-items/{item_id}/options", response_model=OptionOut, status_code=201, dependencies=[Depends(can_manage)])
async def add_option(
    item_id: int,
    payload: OptionIn,
    db: AsyncIOMotorDatabase = Depends(get_mongo_db),
):
    item = await db["check_items"].find_one({"id": item_id})
    if not item:
        raise HTTPException(404, "Check item not found")

    label = payload.label.strip()
    for o in item.get("options", []):
        if o.get("is_active", True) and o["label"].strip().lower() == label.lower():
            raise HTTPException(409, "This check already has an option with that label")

    opt_id = await get_next_id(db, "option_id")
    new_opt = {
        "id": opt_id,
        "label": label,
        "sort_order": payload.sort_order,
        "is_active": True,
    }
    await db["check_items"].update_one({"id": item_id}, {"$push": {"options": new_opt}})
    return OptionOut(**new_opt)


@router.patch("/check-item-options/{option_id}", response_model=OptionOut, dependencies=[Depends(can_manage)])
async def update_option(
    option_id: int,
    payload: OptionUpdate,
    db: AsyncIOMotorDatabase = Depends(get_mongo_db),
):
    item = await db["check_items"].find_one({"options.id": option_id})
    if not item:
        raise HTTPException(404, "Option not found")

    curr_opt = next((o for o in item["options"] if o["id"] == option_id), None)
    if not curr_opt:
        raise HTTPException(404, "Option not found")

    data = payload.model_dump(exclude_unset=True)
    if data.get("is_active") is False:
        active_count = sum(1 for o in item["options"] if o.get("is_active", True) and o["id"] != option_id)
        input_type = InputType(item["input_type"])
        if active_count < min_options(input_type):
            raise HTTPException(400, f"A {input_type.value} check needs at least {min_options(input_type)} active option(s)")

    update_fields = {}
    for k, v in data.items():
        update_fields[f"options.$.{k}"] = v
        curr_opt[k] = v

    if update_fields:
        await db["check_items"].update_one({"options.id": option_id}, {"$set": update_fields})

    return OptionOut(**curr_opt)


@router.delete("/check-item-options/{option_id}", status_code=204, dependencies=[Depends(can_manage)])
async def archive_option(option_id: int, db: AsyncIOMotorDatabase = Depends(get_mongo_db)):
    item = await db["check_items"].find_one({"options.id": option_id})
    if not item:
        raise HTTPException(404, "Option not found")

    active_count = sum(1 for o in item["options"] if o.get("is_active", True) and o["id"] != option_id)
    input_type = InputType(item["input_type"])
    if active_count < min_options(input_type):
        raise HTTPException(400, f"A {input_type.value} check needs at least {min_options(input_type)} active option(s)")

    await db["check_items"].update_one({"options.id": option_id}, {"$set": {"options.$.is_active": False}})
