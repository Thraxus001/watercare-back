from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from motor.motor_asyncio import AsyncIOMotorDatabase

from ..deps import get_current_user, require_any
from ..models import User, UserRole
from ..mongo import get_mongo_db, get_next_id
from ..permissions import Permission as P
from ..schemas import NoteCreate, NoteOut, NoteUpdate

router = APIRouter(tags=["notes"])


def _format_note_out(n: dict, author_name: str) -> NoteOut:
    return NoteOut(
        id=n["id"],
        machine_id=n["machine_id"],
        inspection_id=n.get("inspection_id"),
        author_id=n["author_id"],
        author_name=author_name,
        body=n["body"],
        created_at=n["created_at"],
        updated_at=n["updated_at"],
    )


@router.get("/machines/{machine_id}/notes", response_model=list[NoteOut], dependencies=[Depends(require_any(P.NOTES_VIEW))])
async def list_notes(
    machine_id: int,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncIOMotorDatabase = Depends(get_mongo_db),
):
    if not await db["machines"].find_one({"id": machine_id}):
        raise HTTPException(404, "Machine not found")

    docs = await db["notes"].find({"machine_id": machine_id}).sort([("created_at", -1), ("id", -1)]).skip(offset).limit(limit).to_list(limit)
    if not docs:
        return []

    author_ids = list({d["author_id"] for d in docs})
    authors = await db["users"].find({"id": {"$in": author_ids}}).to_list(len(author_ids))
    author_map = {a["id"]: a["full_name"] for a in authors}

    return [_format_note_out(d, author_map.get(d["author_id"], "Unknown")) for d in docs]


@router.post("/machines/{machine_id}/notes", response_model=NoteOut, status_code=201)
async def add_note(
    machine_id: int,
    payload: NoteCreate,
    db: AsyncIOMotorDatabase = Depends(get_mongo_db),
    user: User = Depends(require_any(P.NOTES_CREATE)),
):
    if not await db["machines"].find_one({"id": machine_id}):
        raise HTTPException(404, "Machine not found")

    if payload.inspection_id:
        insp = await db["inspections"].find_one({"id": payload.inspection_id})
        if not insp or insp.get("machine_id") != machine_id:
            raise HTTPException(422, "That inspection doesn't belong to this machine")

    new_id = await get_next_id(db, "note_id")
    now = datetime.now(timezone.utc)
    note_doc = {
        "id": new_id,
        "machine_id": machine_id,
        "inspection_id": payload.inspection_id,
        "author_id": user.id,
        "body": payload.body.strip(),
        "created_at": now,
        "updated_at": now,
    }
    await db["notes"].insert_one(note_doc)
    return _format_note_out(note_doc, user.full_name)


async def _own_or_admin(db: AsyncIOMotorDatabase, note_id: int, user: User) -> dict:
    note = await db["notes"].find_one({"id": note_id})
    if not note:
        raise HTTPException(404, "Note not found")
    if note["author_id"] != user.id and user.role != UserRole.admin:
        raise HTTPException(403, "You can only change your own notes")
    return note


@router.patch("/notes/{note_id}", response_model=NoteOut)
async def edit_note(
    note_id: int,
    payload: NoteUpdate,
    db: AsyncIOMotorDatabase = Depends(get_mongo_db),
    user: User = Depends(get_current_user),
):
    note = await _own_or_admin(db, note_id, user)
    body = payload.body.strip()
    now = datetime.now(timezone.utc)
    await db["notes"].update_one({"id": note_id}, {"$set": {"body": body, "updated_at": now}})
    note["body"] = body
    note["updated_at"] = now

    author = await db["users"].find_one({"id": note["author_id"]})
    return _format_note_out(note, author["full_name"] if author else "Unknown")


@router.delete("/notes/{note_id}", status_code=204)
async def delete_note(
    note_id: int,
    db: AsyncIOMotorDatabase = Depends(get_mongo_db),
    user: User = Depends(get_current_user),
):
    await _own_or_admin(db, note_id, user)
    await db["notes"].delete_one({"id": note_id})
