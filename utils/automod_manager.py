"""
AutoMod Manager - Handles storage and retrieval of AutoMod settings
Abstracted to support database migration and dashboard integration
"""

import asyncio
from typing import Dict, Optional, List
from .automod_models import GuildAutoModSettings, AutoModPreset, AutoModEvent, AutoModRule, ActionType, RuleType, ExemptEntity, AutoModAction
from .mongodb import get_database


class AutoModManager:
    """
    Manager for AutoMod settings storage and retrieval.
    Designed for easy migration to database backends.
    """

    def __init__(self, data_dir: str = "data/automod"):
        self.data_dir = data_dir
        self._lock = asyncio.Lock()
        self.db = get_database()
        self.guild_settings_collection = self.db["automod_guild_settings"]
        self.presets_collection = self.db["automod_presets"]
        self.events_collection = self.db["automod_events"]
        self._presets_initialized = False

        self.guild_settings_collection.create_index("guild_id", unique=True)
        self.presets_collection.create_index("id", unique=True)
        self.events_collection.create_index([("guild_id", 1), ("timestamp", -1)])
        self.events_collection.create_index([("guild_id", 1), ("rule_id", 1), ("timestamp", -1)])

    async def _ensure_default_presets(self) -> None:
        """Ensure default presets exist in MongoDB"""
        if self._presets_initialized:
            return

        async with self._lock:
            if self._presets_initialized:
                return

            if self.presets_collection.count_documents({}) == 0:
                await self._init_default_presets()

            self._presets_initialized = True

    async def _init_default_presets(self) -> None:
        """Initialize default presets"""
        default_presets = {
            "lenient": AutoModPreset(
                id="lenient",
                name="Lenient",
                description="Basic spam and obvious profanity detection",
                rules=[
                    AutoModRule(
                        id="lenient_spam",
                        name="Spam Detection",
                        rule_type=RuleType.SPAM,
                        patterns=["repeat_threshold:10"],
                        action=AutoModAction(ActionType.DELETE),
                        severity=1,
                    )
                ]
            ),
            "moderate": AutoModPreset(
                id="moderate",
                name="Moderate",
                description="Balanced protection with common rules",
                rules=[
                    AutoModRule(
                        id="moderate_spam",
                        name="Spam Detection",
                        rule_type=RuleType.SPAM,
                        patterns=["repeat_threshold:5"],
                        action=AutoModAction(ActionType.DELETE),
                        severity=2,
                    ),
                    AutoModRule(
                        id="moderate_caps",
                        name="Excessive Caps",
                        rule_type=RuleType.CAPS,
                        patterns=["percentage:70"],
                        action=AutoModAction(ActionType.DELETE),
                        severity=2,
                    ),
                ]
            ),
            "strict": AutoModPreset(
                id="strict",
                name="Strict",
                description="Heavy moderation with warnings and mutes",
                rules=[
                    AutoModRule(
                        id="strict_spam",
                        name="Spam Detection",
                        rule_type=RuleType.SPAM,
                        patterns=["repeat_threshold:3"],
                        action=AutoModAction(ActionType.WARN),
                        severity=4,
                    ),
                    AutoModRule(
                        id="strict_caps",
                        name="Excessive Caps",
                        rule_type=RuleType.CAPS,
                        patterns=["percentage:50"],
                        action=AutoModAction(ActionType.WARN),
                        severity=3,
                    ),
                    AutoModRule(
                        id="strict_mentions",
                        name="Mention Spam",
                        rule_type=RuleType.MENTIONS,
                        patterns=["count:5"],
                        action=AutoModAction(ActionType.MUTE, duration_seconds=3600),
                        severity=4,
                    ),
                ]
            ),
        }
        await self.save_presets(default_presets)

    # --- Guild Settings Operations ---

    async def get_guild_settings(self, guild_id: int) -> GuildAutoModSettings:
        """Get settings for a guild, create default if not exists"""
        data = self.guild_settings_collection.find_one({"guild_id": guild_id}, {"_id": 0})
        if data:
            return GuildAutoModSettings.from_dict(data)
        return GuildAutoModSettings(guild_id=guild_id)

    async def save_guild_settings(self, settings: GuildAutoModSettings) -> None:
        """Save guild settings"""
        self.guild_settings_collection.replace_one(
            {"guild_id": settings.guild_id},
            settings.to_dict(),
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
        await self._ensure_default_presets()
        presets: Dict[str, AutoModPreset] = {}
        for doc in self.presets_collection.find({}, {"_id": 0}):
            preset = AutoModPreset.from_dict(doc)
            presets[preset.id] = preset
        return presets

    async def get_preset(self, preset_id: str) -> Optional[AutoModPreset]:
        """Get a specific preset"""
        presets = await self.get_presets()
        return presets.get(preset_id)

    async def save_presets(self, presets: Dict[str, AutoModPreset]) -> None:
        """Save presets"""
        docs = [preset.to_dict() for preset in presets.values()]
        self.presets_collection.delete_many({})
        if docs:
            self.presets_collection.insert_many(docs)

    async def apply_preset(self, guild_id: int, preset_id: str) -> bool:
        """Apply a preset to a guild"""
        preset = await self.get_preset(preset_id)
        if not preset:
            return False
        
        settings = await self.get_guild_settings(guild_id)
        settings.rules = [
            AutoModRule(
                id=f"{preset_id}_{rule.id}",
                name=rule.name,
                rule_type=rule.rule_type,
                patterns=rule.patterns,
                allowed_patterns=rule.allowed_patterns,
                action=rule.action,
                severity=rule.severity,
            )
            for rule in preset.rules
        ]
        await self.save_guild_settings(settings)
        return True

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
            self.events_collection.insert_one(event.to_dict())

            # Keep only last 50000 events to prevent collection bloat
            max_events = 50000
            total_events = self.events_collection.count_documents({})
            if total_events > max_events:
                overflow = total_events - max_events
                oldest_docs = list(
                    self.events_collection.find({}, {"_id": 1})
                    .sort([("timestamp", 1), ("_id", 1)])
                    .limit(overflow)
                )
                if oldest_docs:
                    self.events_collection.delete_many(
                        {"_id": {"$in": [doc["_id"] for doc in oldest_docs]}}
                    )

    async def get_events(self, guild_id: Optional[int] = None, limit: int = 100) -> List[AutoModEvent]:
        """Get logged events, optionally filtered by guild"""
        query = {"guild_id": guild_id} if guild_id is not None else {}
        events_data = list(
            self.events_collection.find(query, {"_id": 0})
            .sort("timestamp", -1)
            .limit(limit)
        )
        events_data.reverse()
        return [AutoModEvent.from_dict(e) for e in events_data]

    async def get_events_for_rule(self, guild_id: int, rule_id: str, limit: int = 100) -> List[AutoModEvent]:
        """Get events for a specific rule"""
        events_data = list(
            self.events_collection.find(
                {"guild_id": guild_id, "rule_id": rule_id},
                {"_id": 0},
            )
            .sort("timestamp", -1)
            .limit(limit)
        )
        events_data.reverse()
        return [AutoModEvent.from_dict(e) for e in events_data]
