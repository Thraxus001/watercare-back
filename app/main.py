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


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Connect to MongoDB Atlas and verify indexes
    try:
        await init_mongo()
        db = get_mongo_db()

        # Seed initial admin account in MongoDB Atlas if none exists
        admin = await db["users"].find_one({"role": UserRole.admin.value})
        if not admin:
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
            log.warning("Created first admin user '%s' in MongoDB Atlas.", settings.first_admin_email)

        # Seed default plants if none exist, and map existing machines
        plant_count = await db["plants"].count_documents({})
        if plant_count == 0:
            now = datetime.now(timezone.utc)
            default_plants = [
                {
                    "id": 1,
                    "name": "Reverse Osmosis Treatment Plant",
                    "code": "PLT-RO-01",
                    "location": "Main Water Facility",
                    "description": "Primary high-recovery RO membrane skid and backup line for process water.",
                    "is_active": True,
                    "created_at": now,
                },
                {
                    "id": 2,
                    "name": "Water Softening & Utility Plant",
                    "code": "PLT-SFT-02",
                    "location": "Utility Wing",
                    "description": "Ion exchange water softeners for boiler feed and cooling tower makeup.",
                    "is_active": True,
                    "created_at": now,
                },
                {
                    "id": 3,
                    "name": "UV Disinfection Plant",
                    "code": "PLT-UV-03",
                    "location": "Cleanroom Facility",
                    "description": "Inline germicidal UV reactor with lamp intensity and sleeve monitors.",
                    "is_active": True,
                    "created_at": now,
                },
                {
                    "id": 4,
                    "name": "Effluent Treatment Plant (ETP)",
                    "code": "PLT-ETP-04",
                    "location": "South Industrial Yard",
                    "description": "Biological and chemical effluent treatment with clarification and filtration.",
                    "is_active": True,
                    "created_at": now,
                },
            ]
            await db["plants"].insert_many(default_plants)
            await db["counters"].update_one({"_id": "plant_id"}, {"$set": {"seq": 4}}, upsert=True)

            # Associate existing machines to their respective plants
            await db["machines"].update_many({"id": {"$in": [1, 2]}}, {"$set": {"plant_id": 1}})
            await db["machines"].update_many({"id": {"$in": [3, 4]}}, {"$set": {"plant_id": 2}})
            await db["machines"].update_many({"id": 5}, {"$set": {"plant_id": 3}})
            await db["machines"].update_many({"id": 6}, {"$set": {"plant_id": 4}})
            log.info("Initialized default plants and linked existing machines.")
    except Exception as exc:
        log.error("MongoDB Atlas initialization failed: %s", exc)
        raise exc

    yield

    # Gracefully close connection on shutdown
    await close_mongo()


app = FastAPI(
    title="WaterCare – Operation & Maintenance Tracker",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (auth.router, users.router, checklists.router, plants.router, machines.router, inspections.router, notes.router):
    app.include_router(r)


@app.get("/health", tags=["meta"])
async def health():
    mongo_status = await ping_mongo()
    return {
        "status": "ok" if mongo_status.get("status") == "connected" else "degraded",
        "database": {
            "type": "mongodb_atlas",
            "connection": mongo_status,
        },
    }
