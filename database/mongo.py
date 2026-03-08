import os
from typing import Optional

from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from urllib.parse import quote_plus

load_dotenv()

_client: Optional[MongoClient] = None


def build_uri() -> str:
    uri = os.getenv("MONGODB_URI") or os.getenv("MONGO_URI")
    if uri:
        return uri

    host = os.getenv("DB_IP", "127.0.0.1")
    port = os.getenv("DB_PORT", "27017")
    username = os.getenv("DB_USER")
    password = os.getenv("DB_PASSWORD")
    auth_source = os.getenv("DB_AUTH_SOURCE", "admin")

    if username and password:
        safe_username = quote_plus(username)
        safe_password = quote_plus(password)
        return f"mongodb://{safe_username}:{safe_password}@{host}:{port}/?authSource={auth_source}"

    return f"mongodb://{host}:{port}/"


def get_client() -> MongoClient:
    global _client

    if _client is None:
        server_timeout_ms = int(os.getenv("DB_SERVER_SELECTION_TIMEOUT_MS", "8000"))
        connect_timeout_ms = int(os.getenv("DB_CONNECT_TIMEOUT_MS", "8000"))
        socket_timeout_ms = int(os.getenv("DB_SOCKET_TIMEOUT_MS", "8000"))
        _client = MongoClient(
            build_uri(),
            serverSelectionTimeoutMS=server_timeout_ms,
            connectTimeoutMS=connect_timeout_ms,
            socketTimeoutMS=socket_timeout_ms,
            connect=False,
        )

    return _client


def close_connection():
    global _client

    if _client:
        _client.close()
        _client = None


class MongoDB:

    def __init__(self, db_name: Optional[str] = None):
        name = db_name or os.getenv("DB_NAME")
        self.collection_name = os.getenv("COLLECTION_NAME")

        if not name:
            raise ValueError("DB_NAME must be set")
        
        if not self.collection_name:
            raise ValueError("COLLECTION_NAME must be set")

        self.db_name = name

        self.client = get_client()
        self.db: Database = self.client[name]
        self.default_collection: Collection = self.db[self.collection_name]

    def collection(self, name: str) -> Collection:
        # set collection name for later use
        self.collection_name = name
        return self.db[name]

    def ping(self) -> bool:
        try:
            self.client.admin.command("ping")
            return True
        except Exception:
            return False