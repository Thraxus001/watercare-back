import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase

from ..deps import require_any
from ..mongo import get_mongo_db, get_next_id
from ..permissions import Permission as P
from ..schemas import LastInspection, MachineOut, PlantCreate, PlantOut, PlantUpdate
from .machines import _format_machine_out, last_inspections

router = APIRouter(prefix="/plants", tags=["plants"])

can_view = require_any(P.PLANTS_VIEW, P.PLANTS_MANAGE, P.MACHINES_VIEW, P.MACHINES_MANAGE, P.INSPECTIONS_VIEW, P.INSPECTIONS_CREATE)
can_manage = require_any(P.PLANTS_MANAGE, P.MACHINES_MANAGE)


async def _format_plant_out(p: dict, db: AsyncIOMotorDatabase) -> PlantOut:
    plant_id = p["id"]
    all_machines = await db["machines"].find({"plant_id": plant_id}).to_list(500)
    total_count = len(all_machines)
    active_count = sum(1 for m in all_machines if m.get("is_active", True))

    last_ins = None
    if all_machines:
        m_ids = [m["id"] for m in all_machines]
        last_map = await last_inspections(db, m_ids)
        # Find the most recent inspection among all machines in this plant
        all_last = [l for l in last_map.values() if l is not None]
        if all_last:
            all_last.sort(key=lambda x: x.performed_at, reverse=True)
            last_ins = all_last[0]

    return PlantOut(
        id=p["id"],
        name=p["name"],
        code=p.get("code"),
        location=p["location"],
        latitude=p.get("latitude"),
        longitude=p.get("longitude"),
        description=p.get("description"),
        is_active=p.get("is_active", True),
        machine_count=total_count,
        active_machines_count=active_count,
        last_inspection=last_ins,
    )


@router.get("", response_model=list[PlantOut], dependencies=[Depends(can_view)])
async def list_plants(
    q: Optional[str] = None,
    location: Optional[str] = None,
    include_inactive: bool = False,
    db: AsyncIOMotorDatabase = Depends(get_mongo_db),
):
    query = {}
    if not include_inactive:
        query["is_active"] = True
    if location:
        escaped_loc = re.escape(location.strip())
        query["location"] = {"$regex": f"^{escaped_loc}$", "$options": "i"}
    if q:
        escaped = re.escape(q.strip())
        pattern = {"$regex": escaped, "$options": "i"}
        query["$or"] = [{"name": pattern}, {"code": pattern}, {"location": pattern}, {"description": pattern}]

    plants = await db["plants"].find(query).sort([("location", 1), ("name", 1)]).to_list(1000)
    return [await _format_plant_out(p, db) for p in plants]


@router.get("/{plant_id}", response_model=PlantOut, dependencies=[Depends(can_view)])
async def get_plant(plant_id: int, db: AsyncIOMotorDatabase = Depends(get_mongo_db)):
    p = await db["plants"].find_one({"id": plant_id})
    if not p:
        raise HTTPException(404, "Plant not found")
    return await _format_plant_out(p, db)


@router.get("/{plant_id}/machines", response_model=list[MachineOut], dependencies=[Depends(can_view)])
async def get_plant_machines(
    plant_id: int,
    include_inactive: bool = False,
    db: AsyncIOMotorDatabase = Depends(get_mongo_db),
):
    p = await db["plants"].find_one({"id": plant_id})
    if not p:
        raise HTTPException(404, "Plant not found")

    query = {"plant_id": plant_id}
    if not include_inactive:
        query["is_active"] = True

    machines = await db["machines"].find(query).sort("name", 1).to_list(500)
    if not machines:
        return []

    type_ids = list({m["machine_type_id"] for m in machines})
    types = await db["machine_types"].find({"id": {"$in": type_ids}}).to_list(len(type_ids))
    type_map = {t["id"]: t["name"] for t in types}
    last_map = await last_inspections(db, [m["id"] for m in machines])

    return [
        _format_machine_out(
            m,
            type_map.get(m["machine_type_id"], "Unknown"),
            last_map.get(m["id"]),
            p,
        )
        for m in machines
    ]


@router.post("", response_model=PlantOut, status_code=201, dependencies=[Depends(can_manage)])
async def create_plant(payload: PlantCreate, db: AsyncIOMotorDatabase = Depends(get_mongo_db)):
    name = payload.name.strip()
    loc = payload.location.strip()
    code = payload.code.strip() if payload.code else None

    if await db["plants"].find_one({"name": {"$regex": f"^{re.escape(name)}$", "$options": "i"}, "location": {"$regex": f"^{re.escape(loc)}$", "$options": "i"}}):
        raise HTTPException(409, "A plant with this name already exists at this location")

    new_id = await get_next_id(db, "plant_id")
    p_data = {
        "id": new_id,
        "name": name,
        "code": code,
        "location": loc,
        "latitude": payload.latitude,
        "longitude": payload.longitude,
        "description": payload.description.strip() if payload.description else None,
        "is_active": True,
        "created_at": datetime.now(timezone.utc),
    }
    await db["plants"].insert_one(p_data)
    return await _format_plant_out(p_data, db)


@router.patch("/{plant_id}", response_model=PlantOut, dependencies=[Depends(can_manage)])
async def update_plant(
    plant_id: int,
    payload: PlantUpdate,
    db: AsyncIOMotorDatabase = Depends(get_mongo_db),
):
    p = await db["plants"].find_one({"id": plant_id})
    if not p:
        raise HTTPException(404, "Plant not found")

    data = payload.model_dump(exclude_unset=True)
    latitude = data.get("latitude", p.get("latitude"))
    longitude = data.get("longitude", p.get("longitude"))
    if (latitude is None) != (longitude is None):
        raise HTTPException(422, "Latitude and longitude must be provided together")

    if "name" in data and data["name"] is not None:
        data["name"] = data["name"].strip()
    if "location" in data and data["location"] is not None:
        data["location"] = data["location"].strip()
    if "code" in data and data["code"] is not None:
        data["code"] = data["code"].strip()
    if "description" in data and data["description"] is not None:
        data["description"] = data["description"].strip()

    if data:
        await db["plants"].update_one({"id": plant_id}, {"$set": data})
        p.update(data)

    return await _format_plant_out(p, db)


@router.delete("/{plant_id}", status_code=204, dependencies=[Depends(can_manage)])
async def delete_plant(plant_id: int, db: AsyncIOMotorDatabase = Depends(get_mongo_db)):
    p = await db["plants"].find_one({"id": plant_id})
    if not p:
        raise HTTPException(404, "Plant not found")

    # Soft delete / deactivate plant
    await db["plants"].update_one({"id": plant_id}, {"$set": {"is_active": False}})
