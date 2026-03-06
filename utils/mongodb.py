import os
import importlib
from typing import Any, Optional
from urllib.parse import quote_plus

from dotenv import load_dotenv


load_dotenv()

_client: Optional[Any] = None

class MongoDB:
    def __init__(self, uri: Optional[str] = None, db_name: Optional[str] = None):
        self.uri = uri or build_mongodb_uri()
        self.db_name = db_name or os.getenv("DB_NAME", "").strip()
        if not self.db_name:
            raise ValueError("MongoDB database name is required. Set DB_NAME or pass db_name.")
        self.client = get_mongo_client()
        self.db = self.client[self.db_name]

    def get_collection(self, collection_name: str) -> Any:
        return self.db[collection_name]


def build_mongodb_uri() -> str:
    """Build MongoDB URI from MONGODB_URI or DB_* env vars."""
    direct_uri = os.getenv("MONGODB_URI", "").strip()
    if direct_uri:
        return direct_uri

    host = os.getenv("DB_IP", "127.0.0.1").strip() or "127.0.0.1"
    port = os.getenv("DB_PORT", "27017").strip() or "27017"
    username = os.getenv("DB_USER", "").strip()
    password = os.getenv("DB_PASSWORD", "").strip()
    auth_source = os.getenv("DB_AUTH_SOURCE", "admin").strip() or "admin"

    if username and password:
        safe_username = quote_plus(username)
        safe_password = quote_plus(password)
        return f"mongodb://{safe_username}:{safe_password}@{host}:{port}/?authSource={auth_source}"

    return f"mongodb://{host}:{port}/"


def get_mongo_client(*, ping: bool = False) -> Any:
    """Return a cached MongoDB client."""
    global _client

    if _client is None:
        pymongo = importlib.import_module("pymongo")
        MongoClient = getattr(pymongo, "MongoClient")
        _client = MongoClient(build_mongodb_uri())

    client = _client
    if client is None:
        raise RuntimeError("Failed to initialize MongoDB client.")

    if ping:
        client.admin.command("ping")

    return client


def get_database(db_name: Optional[str] = None, *, ping: bool = False) -> Any:
    """Return a MongoDB database using explicit name or DB_NAME env var."""
    resolved_name = (db_name or os.getenv("DB_NAME", "")).strip()
    if not resolved_name:
        raise ValueError("MongoDB database name is required. Set DB_NAME or pass db_name.")

    client = get_mongo_client(ping=ping)
    return client[resolved_name]


def close_mongo_connection() -> None:
    """Close and reset the cached MongoDB client."""
    global _client

    if _client is not None:
        _client.close()
        _client = None
