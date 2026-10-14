from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user, has_permission, require_any
from ..models import Inspection, Machine, MachineNote, User, UserRole
from ..permissions import Permission as P
from ..schemas import NoteCreate, NoteOut, NoteUpdate

router = APIRouter(tags=["notes"])


def note_out(n: MachineNote) -> NoteOut:
    return NoteOut(
        id=n.id, machine_id=n.machine_id, inspection_id=n.inspection_id, author_id=n.author_id,
        author_name=n.author.full_name, body=n.body, created_at=n.created_at, updated_at=n.updated_at,
    )


@router.get("/machines/{machine_id}/notes", response_model=list[NoteOut], dependencies=[Depends(require_any(P.NOTES_VIEW))])
def list_notes(machine_id: int, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    if not db.get(Machine, machine_id):
        raise HTTPException(404, "Machine not found")
    stmt = (
        select(MachineNote).where(MachineNote.machine_id == machine_id)
        .order_by(MachineNote.created_at.desc(), MachineNote.id.desc()).limit(limit).offset(offset)
    )
    return [note_out(n) for n in db.scalars(stmt).unique()]


@router.post("/machines/{machine_id}/notes", response_model=NoteOut, status_code=201)
def add_note(machine_id: int, payload: NoteCreate, db: Session = Depends(get_db), user: User = Depends(require_any(P.NOTES_CREATE))):
    if not db.get(Machine, machine_id):
        raise HTTPException(404, "Machine not found")
    if payload.inspection_id:
        insp = db.get(Inspection, payload.inspection_id)
        if not insp or insp.machine_id != machine_id:
            raise HTTPException(422, "That inspection doesn't belong to this machine")
    note = MachineNote(machine_id=machine_id, inspection_id=payload.inspection_id, author_id=user.id, body=payload.body.strip())
    db.add(note)
    db.commit()
    db.refresh(note)
    return note_out(note)


def _own_or_admin(db: Session, note_id: int, user: User) -> MachineNote:
    note = db.get(MachineNote, note_id)
    if not note:
        raise HTTPException(404, "Note not found")
    if note.author_id != user.id and user.role != UserRole.admin:
        raise HTTPException(403, "You can only change your own notes")
    return note


@router.patch("/notes/{note_id}", response_model=NoteOut)
def edit_note(note_id: int, payload: NoteUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    note = _own_or_admin(db, note_id, user)
    note.body = payload.body.strip()
    note.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(note)
    return note_out(note)


@router.delete("/notes/{note_id}", status_code=204)
def delete_note(note_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    db.delete(_own_or_admin(db, note_id, user))
    db.commit()
