import os
from typing import Any, Optional

from utils.json_utils import load_json_sync, save_json
from utils.mongodb import get_database


class WarnStorage:
    def __init__(
        self,
        warn_path: str,
        *,
        backend_env_key: str = "WARN_STORAGE_BACKEND",
        db_name: str = "warn_system",
    ):
        self.warn_path = warn_path
        self.storage_backend = os.getenv(backend_env_key, "json").strip().lower()
        self.db: Optional[Any] = None

        if self.storage_backend == "mongodb":
            try:
                self.db = get_database(db_name=db_name)
            except Exception:
                self.storage_backend = "json"

        self.warnings: dict[str, dict[str, list[dict[str, Any]]]] = load_json_sync(self.warn_path)

    def _is_mongodb_enabled(self) -> bool:
        return self.storage_backend == "mongodb" and self.db is not None

    def _ensure_guild_user(self, guild_id: str, user_id: str):
        self.warnings.setdefault(guild_id, {}).setdefault(user_id, [])

    def get_user_warnings(self, guild_id: str, user_id: str) -> list[dict[str, Any]]:
        if self._is_mongodb_enabled():
            docs = list(self.db.warnings.find({"guild_id": guild_id, "warning.user_id": user_id}))
            return [doc.get("warning", {}) for doc in docs]

        self._ensure_guild_user(guild_id, user_id)
        return list(self.warnings[guild_id][user_id])

    async def add_warning(self, guild_id: str, user_id: str, warning: dict[str, Any]):
        if self._is_mongodb_enabled():
            self.db.warnings.insert_one({"guild_id": guild_id, "warning": warning})
            return

        self._ensure_guild_user(guild_id, user_id)
        self.warnings[guild_id][user_id].append(warning)
        await save_json(self.warn_path, self.warnings)

    async def delete_warning_by_index(self, guild_id: str, user_id: str, index: int) -> bool:
        if self._is_mongodb_enabled():
            docs = list(self.db.warnings.find({"guild_id": guild_id, "warning.user_id": user_id}))
            if 0 <= index < len(docs):
                self.db.warnings.delete_one({"_id": docs[index]["_id"]})
                return True
            return False

        self._ensure_guild_user(guild_id, user_id)
        user_warnings = self.warnings[guild_id][user_id]
        if 0 <= index < len(user_warnings):
            user_warnings.pop(index)
            await save_json(self.warn_path, self.warnings)
            return True
        return False
