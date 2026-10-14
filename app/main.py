import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from .config import settings
from .database import SessionLocal
from .models import User, UserRole
from .routers import auth, checklists, inspections, machines, notes, users
from .security import hash_password

log = logging.getLogger("watercare")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create the first admin account if none exists yet.
    with SessionLocal() as db:
        try:
            if not db.scalar(select(User.id).where(User.role == UserRole.admin).limit(1)):
                db.add(User(
                    email=settings.first_admin_email.lower(), full_name=settings.first_admin_name,
                    hashed_password=hash_password(settings.first_admin_password), role=UserRole.admin,
                ))
                db.commit()
                log.warning("Created first admin %s – change its password!", settings.first_admin_email)
        except Exception:
            log.exception("Could not seed admin. Did you run schema.sql on the database?")
            raise
    yield


app = FastAPI(title="WaterCare – Operation & Maintenance Tracker", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

for r in (auth.router, users.router, checklists.router, machines.router, inspections.router, notes.router):
    app.include_router(r)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}
