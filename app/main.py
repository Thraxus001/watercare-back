import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .models import UserRole
from .mongo import close_mongo, get_mongo_db, get_next_id, init_mongo, ping_mongo
from .permissions import Permission
from .routers import auth, checklists, inspections, machines, notes, plants, users
from .security import hash_password

log = logging.getLogger("watercare")


async def _ensure_admin(db) -> None:
    """Seed initial admin from env vars if no admin exists yet."""
    admin = await db["users"].find_one({"role": UserRole.admin.value})
    if admin:
        return

    admin_id = await get_next_id(db, "user_id")
    await db["users"].insert_one({
        "id": admin_id,
        "email": settings.first_admin_email.lower(),
        "full_name": settings.first_admin_name,
        "hashed_password": hash_password(settings.first_admin_password),
        "role": UserRole.admin.value,
        "is_active": True,
        "created_at": datetime.now(timezone.utc),
        "permissions": [p.value for p in Permission],
    })
    log.warning(
        "Created first admin '%s'. Please change the password after first login.",
        settings.first_admin_email,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await init_mongo()
        db = get_mongo_db()

        # If DB is completely empty, seed demo data
        user_count = await db["users"].count_documents({})
        if user_count == 0:
            log.info("Empty database – seeding demo data...")
            try:
                from seed import seed_database  # noqa: PLC0415
                await seed_database(db, drop=False)
                log.info("Demo seed complete.")
            except Exception as seed_err:
                log.error("Demo seed failed: %s – continuing with admin-only seed.", seed_err)
                await _ensure_admin(db)
        else:
            await _ensure_admin(db)

    except Exception as exc:
        log.error("Database initialisation failed: %s", exc)
        raise

    yield

    await close_mongo()


app = FastAPI(
    title="WaterCare – Operation & Maintenance Tracker",
    version="1.0.0",
    lifespan=lifespan,
    # Hide /docs and /redoc in production if desired – keep enabled for now
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (
    auth.router,
    users.router,
    checklists.router,
    plants.router,
    machines.router,
    inspections.router,
    notes.router,
):
    app.include_router(r)


@app.get("/health", tags=["meta"])
async def health():
    mongo_status = await ping_mongo()
    return {
        "status": "ok" if mongo_status.get("status") == "connected" else "degraded",
        "database": {"type": "mongodb_atlas", "connection": mongo_status},
    }
