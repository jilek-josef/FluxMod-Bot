"""
AutoMod Manager - Handles storage and retrieval of AutoMod settings
Abstracted to support database migration and dashboard integration
"""

import asyncio
from typing import Dict, Optional, List
from .automod_models import GuildAutoModSettings, AutoModPreset, AutoModEvent, AutoModRule, ExemptEntity
from database.mongo import MongoDB

from dotenv import load_dotenv
import os

load_dotenv()
LOAD_DB = os.getenv("DB_NAME")


class AutoModManager:
    """
    Manager for AutoMod settings storage and retrieval.
    Designed for easy migration to database backends.
    """

    def __init__(self, data_dir: str = "data/automod"):
        self.data_dir = data_dir
        self._lock = asyncio.Lock()
        self.db = MongoDB(db_name=LOAD_DB)
        self.guild_settings_collection = self.db.collection("guild_settings")

        self.guild_settings_collection.create_index("guild_id", unique=True)
        self.guild_settings_collection.create_index([("guild_id", 1), ("automod_events.timestamp", -1)])

    # --- Guild Settings Operations ---

    async def get_guild_settings(self, guild_id: int) -> GuildAutoModSettings:
        """Get settings for a guild, create default if not exists"""
        data = self.guild_settings_collection.find_one({"guild_id": guild_id}, {"_id": 0})
        if data:
            return GuildAutoModSettings.from_dict(data)
        return GuildAutoModSettings(guild_id=guild_id)

    async def save_guild_settings(self, settings: GuildAutoModSettings) -> None:
        """Save guild settings"""
        self.guild_settings_collection.update_one(
            {"guild_id": settings.guild_id},
            {"$set": settings.to_dict()},
            upsert=True,
        )

    async def delete_guild_settings(self, guild_id: int) -> bool:
        """Delete all settings for a guild"""
        result = self.guild_settings_collection.delete_one({"guild_id": guild_id})
        return result.deleted_count > 0

    async def list_guild_settings(self) -> List[int]:
        """List all configured guild IDs"""
        cursor = self.guild_settings_collection.find({}, {"guild_id": 1, "_id": 0})
        return [doc["guild_id"] for doc in cursor if "guild_id" in doc]

    # --- Rule Operations ---

    async def add_rule(self, guild_id: int, rule: AutoModRule) -> None:
        """Add a rule to a guild"""
        settings = await self.get_guild_settings(guild_id)
        settings.add_rule(rule)
        await self.save_guild_settings(settings)

    async def remove_rule(self, guild_id: int, rule_id: str) -> bool:
        """Remove a rule from a guild"""
        settings = await self.get_guild_settings(guild_id)
        removed = settings.remove_rule(rule_id)
        if removed:
            await self.save_guild_settings(settings)
        return removed

    async def update_rule(self, guild_id: int, rule: AutoModRule) -> None:
        """Update an existing rule"""
        settings = await self.get_guild_settings(guild_id)
        settings.add_rule(rule)
        await self.save_guild_settings(settings)

    async def get_rule(self, guild_id: int, rule_id: str) -> Optional[AutoModRule]:
        """Get a specific rule"""
        settings = await self.get_guild_settings(guild_id)
        return settings.get_rule(rule_id)

    async def get_rules(self, guild_id: int, enabled_only: bool = True) -> List[AutoModRule]:
        """Get all rules for a guild"""
        settings = await self.get_guild_settings(guild_id)
        if enabled_only:
            return [r for r in settings.rules if r.enabled]
        return settings.rules

    # --- Exemption Operations ---

    async def add_exempt_entity(self, guild_id: int, entity_id: int, entity_type: str, name: str = "") -> None:
        """Add an exempt entity (role, user, or channel)"""
        settings = await self.get_guild_settings(guild_id)
        entity = ExemptEntity(id=entity_id, type=entity_type, name=name)
        
        if entity_type == "role":
            if not any(e.id == entity_id for e in settings.exempt_roles):
                settings.exempt_roles.append(entity)
        elif entity_type == "user":
            if not any(e.id == entity_id for e in settings.exempt_users):
                settings.exempt_users.append(entity)
        elif entity_type == "channel":
            if not any(e.id == entity_id for e in settings.exempt_channels):
                settings.exempt_channels.append(entity)
        
        await self.save_guild_settings(settings)

    async def remove_exempt_entity(self, guild_id: int, entity_id: int, entity_type: str) -> bool:
        """Remove an exempt entity"""
        settings = await self.get_guild_settings(guild_id)
        
        if entity_type == "role":
            original_len = len(settings.exempt_roles)
            settings.exempt_roles = [e for e in settings.exempt_roles if e.id != entity_id]
            removed = len(settings.exempt_roles) < original_len
        elif entity_type == "user":
            original_len = len(settings.exempt_users)
            settings.exempt_users = [e for e in settings.exempt_users if e.id != entity_id]
            removed = len(settings.exempt_users) < original_len
        elif entity_type == "channel":
            original_len = len(settings.exempt_channels)
            settings.exempt_channels = [e for e in settings.exempt_channels if e.id != entity_id]
            removed = len(settings.exempt_channels) < original_len
        else:
            removed = False
        
        if removed:
            await self.save_guild_settings(settings)
        return removed

    async def get_exempt_entities(self, guild_id: int, entity_type: str) -> List[ExemptEntity]:
        """Get all exempt entities of a type"""
        settings = await self.get_guild_settings(guild_id)
        if entity_type == "role":
            return settings.exempt_roles
        elif entity_type == "user":
            return settings.exempt_users
        elif entity_type == "channel":
            return settings.exempt_channels
        return []

    async def is_exempt(self, guild_id: int, entity_id: int, entity_type: str) -> bool:
        """Check if an entity is exempt"""
        settings = await self.get_guild_settings(guild_id)
        return settings.is_exempt(entity_id, entity_type)

    # --- Preset Operations ---

    async def get_presets(self) -> Dict[str, AutoModPreset]:
        """Get all available presets"""
        return {}

    async def get_preset(self, preset_id: str) -> Optional[AutoModPreset]:
        """Get a specific preset"""
        presets = await self.get_presets()
        return presets.get(preset_id)

    async def save_presets(self, presets: Dict[str, AutoModPreset]) -> None:
        """Save presets"""
        return

    async def apply_preset(self, guild_id: int, preset_id: str) -> bool:
        """Apply a preset to a guild"""
        return False

    # --- Settings Operations ---

    async def set_log_channel(self, guild_id: int, channel_id: int) -> None:
        """Set the log channel for a guild"""
        settings = await self.get_guild_settings(guild_id)
        settings.log_channel_id = channel_id
        await self.save_guild_settings(settings)

    async def get_log_channel(self, guild_id: int) -> Optional[int]:
        """Get the log channel ID for a guild"""
        settings = await self.get_guild_settings(guild_id)
        return settings.log_channel_id

    async def set_enabled(self, guild_id: int, enabled: bool) -> None:
        """Enable or disable AutoMod for a guild"""
        settings = await self.get_guild_settings(guild_id)
        settings.enabled = enabled
        await self.save_guild_settings(settings)

    # --- Event Logging (for analytics/dashboard) ---

    async def log_event(self, event: AutoModEvent) -> None:
        """Log an AutoMod event"""
        async with self._lock:
            max_events_per_guild = 10000
            self.guild_settings_collection.update_one(
                {"guild_id": event.guild_id},
                {
                    "$setOnInsert": {"guild_id": event.guild_id},
                    "$push": {
                        "automod_events": {
                            "$each": [event.to_dict()],
                            "$slice": -max_events_per_guild,
                        }
                    },
                },
                upsert=True,
            )

    async def get_events(self, guild_id: Optional[int] = None, limit: int = 100) -> List[AutoModEvent]:
        """Get logged events, optionally filtered by guild"""
        events_data: List[dict] = []

        if guild_id is not None:
            doc = self.guild_settings_collection.find_one(
                {"guild_id": guild_id},
                {"automod_events": 1, "_id": 0},
            )
            if not doc:
                return []
            events_data = doc.get("automod_events", [])
        else:
            for doc in self.guild_settings_collection.find({}, {"automod_events": 1, "_id": 0}):
                events_data.extend(doc.get("automod_events", []))

        events_data = sorted(events_data, key=lambda e: e.get("timestamp", 0))
        if limit > 0:
            events_data = events_data[-limit:]
        return [AutoModEvent.from_dict(e) for e in events_data]

    async def get_events_for_rule(self, guild_id: int, rule_id: str, limit: int = 100) -> List[AutoModEvent]:
        """Get events for a specific rule"""
        events = await self.get_events(guild_id=guild_id, limit=max(limit * 5, limit))
        return [e for e in events if e.rule_id == rule_id][-limit:]
