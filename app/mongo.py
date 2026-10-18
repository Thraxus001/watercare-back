import logging
from typing import Optional
from fastapi import HTTPException, status
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
import pymongo

from .config import settings

log = logging.getLogger("watercare.mongo")

client: Optional[AsyncIOMotorClient] = None


async def get_next_id(db: AsyncIOMotorDatabase, sequence_name: str) -> int:
    """Atomically generate the next sequential integer ID for a given sequence."""
    doc = await db["counters"].find_one_and_update(
        {"_id": sequence_name},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=pymongo.ReturnDocument.AFTER,
    )
    return doc["seq"]


async def create_indexes(db: AsyncIOMotorDatabase):
    """Ensure all required collections and unique indexes are created."""
    try:
        await db["users"].create_index([("email", pymongo.ASCENDING)], unique=True)
        await db["users"].create_index([("id", pymongo.ASCENDING)], unique=True)
        await db["machine_types"].create_index([("name", pymongo.ASCENDING)], unique=True)
        await db["machine_types"].create_index([("id", pymongo.ASCENDING)], unique=True)
        await db["plants"].create_index([("id", pymongo.ASCENDING)], unique=True)
        await db["plants"].create_index([("location", pymongo.ASCENDING)])
        await db["machines"].create_index([("serial_number", pymongo.ASCENDING)], unique=True)
        await db["machines"].create_index([("id", pymongo.ASCENDING)], unique=True)
        await db["machines"].create_index([("plant_id", pymongo.ASCENDING)])
        await db["machines"].create_index([("machine_type_id", pymongo.ASCENDING)])
        await db["check_items"].create_index([("id", pymongo.ASCENDING)], unique=True)
        await db["check_items"].create_index([("machine_type_id", pymongo.ASCENDING)])
        await db["check_items"].create_index([("options.id", pymongo.ASCENDING)])
        await db["inspections"].create_index([("id", pymongo.ASCENDING)], unique=True)
        await db["inspections"].create_index([("machine_id", pymongo.ASCENDING)])
        await db["inspections"].create_index([("performed_at", pymongo.DESCENDING)])
        await db["notes"].create_index([("id", pymongo.ASCENDING)], unique=True)
        await db["notes"].create_index([("machine_id", pymongo.ASCENDING)])
        log.info("MongoDB indexes verified.")
    except Exception as exc:
        log.warning("Could not create indexes on MongoDB: %s", exc)


async def init_mongo() -> Optional[AsyncIOMotorClient]:
    """Initialize MongoDB connection pool on application startup."""
    global client
    url = settings.effective_mongo_url
    if not url:
        log.warning("No MongoDB URL configured. Please set MONGODB_URL in your .env file.")
        return None

    masked_url = url
    if "@" in url:
        prefix, rest = url.split("://", 1)
        creds, host = rest.split("@", 1)
        masked_url = f"{prefix}://*****@{host}"

    try:
        import certifi
        ca_file = certifi.where()
    except Exception:
        ca_file = None

    try:
        log.info("Connecting to MongoDB Atlas at %s...", masked_url)
        opts = {"serverSelectionTimeoutMS": 4000}
        if ca_file:
            opts["tlsCAFile"] = ca_file

        atlas_client = AsyncIOMotorClient(url, **opts)
        await atlas_client.admin.command("ping")
        client = atlas_client
        log.info("Successfully connected to MongoDB Atlas (database: %s)", settings.mongodb_db_name)

        db = client[settings.mongodb_db_name]
        await create_indexes(db)
        return client
    except Exception as exc:
        log.warning(
            "Could not connect to MongoDB Atlas at %s: %s. "
            "Falling back to in-memory store so authentication and application features remain available.",
            masked_url,
            exc,
        )
        try:
            import mongomock_motor
            mock_client = mongomock_motor.AsyncMongoMockClient()
            client = mock_client
            log.info("Initialized resilient in-memory MongoDB store (database: %s)", settings.mongodb_db_name)
            db = client[settings.mongodb_db_name]
            await create_indexes(db)
            return client
        except Exception as mock_exc:
            log.error("Failed to initialize database: %s", mock_exc)
            raise exc


async def close_mongo() -> None:
    """Close MongoDB connection pool on application shutdown."""
    global client
    if client is not None:
        log.info("Closing MongoDB connection pool...")
        client.close()
        client = None


def get_mongo_client() -> AsyncIOMotorClient:
    """FastAPI dependency to retrieve the active AsyncIOMotorClient."""
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MongoDB service is not configured or unavailable. Check MONGODB_URL in .env",
        )
    return client


def get_mongo_db() -> AsyncIOMotorDatabase:
    """FastAPI dependency to retrieve the active AsyncIOMotorDatabase."""
    c = get_mongo_client()
    return c[settings.mongodb_db_name]


# Drop-in alias for get_db
get_db = get_mongo_db


async def ping_mongo() -> dict:
    """Utility function to check MongoDB connectivity status (e.g. for /health)."""
    if client is None:
        return {"status": "disconnected", "error": "client not initialized"}
    try:
        await client.admin.command("ping")
        return {"status": "connected", "database": settings.mongodb_db_name}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}
