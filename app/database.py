"""Database access module migrated to MongoDB Atlas."""
from .mongo import get_db, get_mongo_client, get_mongo_db

__all__ = ["get_db", "get_mongo_client", "get_mongo_db"]
