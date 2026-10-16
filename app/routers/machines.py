import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase

from ..deps import require_any
from ..mongo import get_mongo_db, get_next_id
from ..permissions import Permission as P
from ..schemas import LastInspection, MachineCreate, MachineOut, MachineUpdate

router = APIRouter(prefix="/machines", tags=["machines"])

can_view = require_any(P.MACHINES_VIEW, P.MACHINES_MANAGE, P.PLANTS_VIEW, P.PLANTS_MANAGE, P.INSPECTIONS_VIEW, P.INSPECTIONS_CREATE)
can_manage = require_any(P.MACHINES_MANAGE, P.PLANTS_MANAGE)


async def last_inspections(db: AsyncIOMotorDatabase, machine_ids: list[int]) -> dict[int, LastInspection]:
    if not machine_ids:
        return {}

    pipeline = [
        {"$match": {"machine_id": {"$in": machine_ids}}},
        {"$sort": {"performed_at": -1, "id": -1}},
        {
            "$group": {
                "_id": "$machine_id",
                "id": {"$first": "$id"},
                "performed_at": {"$first": "$performed_at"},
                "performed_by": {"$first": "$performed_by"},
            }
        },
    ]
    cursor = db["inspections"].aggregate(pipeline)
    groups = await cursor.to_list(len(machine_ids))
    if not groups:
        return {}

    user_ids = list({g["performed_by"] for g in groups if "performed_by" in g})
    users_cursor = db["users"].find({"id": {"$in": user_ids}})
    user_map = {u["id"]: u["full_name"] async for u in users_cursor}

    return {
        g["_id"]: LastInspection(
            id=g["id"],
            performed_at=g["performed_at"],
            performed_by_name=user_map.get(g.get("performed_by"), "Unknown"),
        )
        for g in groups
    }


def _format_machine_out(
    m: dict,
    type_name: str,
    last: Optional[LastInspection],
    plant: Optional[dict] = None,
) -> MachineOut:
    return MachineOut(
        id=m["id"],
        plant_id=m.get("plant_id"),
        plant_name=plant.get("name") if plant else m.get("plant_name"),
        plant_location=plant.get("location") if plant else m.get("plant_location"),
        name=m["name"],
        serial_number=m["serial_number"],
        location=m.get("location"),
        installed_on=m.get("installed_on"),
        is_active=m.get("is_active", True),
        machine_type_id=m["machine_type_id"],
        machine_type_name=type_name,
        last_inspection=last,
    )


@router.get("", response_model=list[MachineOut], dependencies=[Depends(can_view)])
async def list_machines(
    q: Optional[str] = None,
    plant_id: Optional[int] = None,
    machine_type_id: Optional[int] = None,
    include_inactive: bool = False,
    db: AsyncIOMotorDatabase = Depends(get_mongo_db),
):
    query = {}
    if not include_inactive:
        query["is_active"] = True
    if plant_id is not None:
        query["plant_id"] = plant_id
    if machine_type_id:
        query["machine_type_id"] = machine_type_id
    if q:
        escaped = re.escape(q.strip())
        pattern = {"$regex": escaped, "$options": "i"}
        query["$or"] = [{"name": pattern}, {"serial_number": pattern}, {"location": pattern}]

    machines = await db["machines"].find(query).sort("name", 1).to_list(1000)
    if not machines:
        return []

    type_ids = list({m["machine_type_id"] for m in machines})
    types = await db["machine_types"].find({"id": {"$in": type_ids}}).to_list(len(type_ids))
    type_map = {t["id"]: t["name"] for t in types}

    plant_ids = list({m["plant_id"] for m in machines if m.get("plant_id")})
    plants = await db["plants"].find({"id": {"$in": plant_ids}}).to_list(len(plant_ids)) if plant_ids else []
    plant_map = {p["id"]: p for p in plants}

    last_map = await last_inspections(db, [m["id"] for m in machines])
    return [
        _format_machine_out(
            m,
            type_map.get(m["machine_type_id"], "Unknown"),
            last_map.get(m["id"]),
            plant_map.get(m.get("plant_id")),
        )
        for m in machines
    ]


@router.get("/{machine_id}", response_model=MachineOut, dependencies=[Depends(can_view)])
async def get_machine(machine_id: int, db: AsyncIOMotorDatabase = Depends(get_mongo_db)):
    m = await db["machines"].find_one({"id": machine_id})
    if not m:
        raise HTTPException(404, "Machine not found")

    mt = await db["machine_types"].find_one({"id": m["machine_type_id"]})
    plant = await db["plants"].find_one({"id": m["plant_id"]}) if m.get("plant_id") else None
    last_map = await last_inspections(db, [machine_id])
    return _format_machine_out(m, mt["name"] if mt else "Unknown", last_map.get(machine_id), plant)


@router.post("", response_model=MachineOut, status_code=201, dependencies=[Depends(can_manage)])
async def create_machine(payload: MachineCreate, db: AsyncIOMotorDatabase = Depends(get_mongo_db)):
    mt = await db["machine_types"].find_one({"id": payload.machine_type_id})
    if not mt:
        raise HTTPException(422, "Unknown machine type")

    plant = None
    if payload.plant_id:
        plant = await db["plants"].find_one({"id": payload.plant_id})
        if not plant:
            raise HTTPException(422, "Unknown plant")

    serial = payload.serial_number.strip()
    if await db["machines"].find_one({"serial_number": {"$regex": f"^{re.escape(serial)}$", "$options": "i"}}):
        raise HTTPException(409, "A machine with this serial number already exists")

    new_id = await get_next_id(db, "machine_id")
    m_data = {
        "id": new_id,
        "plant_id": payload.plant_id,
        "machine_type_id": payload.machine_type_id,
        "name": payload.name.strip(),
        "serial_number": serial,
        "location": payload.location or (plant.get("location") if plant else None),
        "installed_on": payload.installed_on.isoformat() if payload.installed_on else None,
        "is_active": True,
        "created_at": datetime.now(timezone.utc),
    }
    await db["machines"].insert_one(m_data)
    return _format_machine_out(m_data, mt["name"], None, plant)


@router.patch("/{machine_id}", response_model=MachineOut, dependencies=[Depends(can_manage)])
async def update_machine(
    machine_id: int,
    payload: MachineUpdate,
    db: AsyncIOMotorDatabase = Depends(get_mongo_db),
):
    m = await db["machines"].find_one({"id": machine_id})
    if not m:
        raise HTTPException(404, "Machine not found")

    data = payload.model_dump(exclude_unset=True)
    if "machine_type_id" in data:
        if not await db["machine_types"].find_one({"id": data["machine_type_id"]}):
            raise HTTPException(422, "Unknown machine type")

    if "plant_id" in data and data["plant_id"] is not None:
        if not await db["plants"].find_one({"id": data["plant_id"]}):
            raise HTTPException(422, "Unknown plant")

    if "serial_number" in data:
        serial = data["serial_number"].strip()
        conflict = await db["machines"].find_one(
            {"serial_number": {"$regex": f"^{re.escape(serial)}$", "$options": "i"}, "id": {"$ne": machine_id}}
        )
        if conflict:
            raise HTTPException(409, "A machine with this serial number already exists")
        data["serial_number"] = serial

    if "installed_on" in data and data["installed_on"] is not None:
        data["installed_on"] = data["installed_on"].isoformat()

    if data:
        await db["machines"].update_one({"id": machine_id}, {"$set": data})
        m.update(data)

    mt = await db["machine_types"].find_one({"id": m["machine_type_id"]})
    plant = await db["plants"].find_one({"id": m["plant_id"]}) if m.get("plant_id") else None
    last_map = await last_inspections(db, [machine_id])
    return _format_machine_out(m, mt["name"] if mt else "Unknown", last_map.get(machine_id), plant)
