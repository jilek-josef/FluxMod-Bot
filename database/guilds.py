from database.mongo import MongoDB
from typing import Dict, Any, Optional

db = MongoDB()
guilds = db.collection("guild_settings")
bot_stats = db.collection("bot_stats")


# LHS Settings defaults
DEFAULT_LHS_SETTINGS = {
    "enabled": False,
    "global_threshold": 0.65,
    "categories": {},
    "exempt_roles": [],
    "exempt_channels": [],
    "exempt_users": [],
    "action": "delete",
    "severity": 2,
    "log_only_mode": False,
    "channel_overrides": {},
    "image_moderation": {
        "enabled": False,
        "scan_attachments": True,
        "scan_embeds": True,
        # All filters disabled by default - user must explicitly enable each
        # Each filter has its own action (delete, warn, kick, ban)
        "filters": {
            "general": {"enabled": False, "threshold": 0.2, "action": "delete"},
            "sensitive": {"enabled": False, "threshold": 0.8, "action": "delete"},
            "questionable": {"enabled": False, "threshold": 0.2, "action": "delete"},
            "explicit": {"enabled": False, "threshold": 0.2, "action": "delete"},
            "guro": {"enabled": False, "threshold": 0.3, "action": "delete"},
            "realistic": {"enabled": False, "threshold": 0.25, "action": "delete"},
            "csam_check": {"enabled": False, "threshold": 0.09, "action": "ban"},
        },
        "log_only_mode": False,
    },
}


def create_guild(guild_id: int):

    if guilds.find_one({"guild_id": guild_id}):
        return

    guilds.insert_one({
        "guild_id": guild_id,
        "automod_rules": [],
        "command_settings": {},
        "warns": []
    })


def update_bot_guild_count(count: int) -> None:
    """Persist current guild count for dashboard usage."""
    bot_stats.update_one(
        {"_id": "global"},
        {"$set": {"guild_count": max(int(count), 0)}},
        upsert=True,
    )


def get_guild(guild_id: int):
    return guilds.find_one({"guild_id": guild_id})


def get_command_settings(guild_id: int) -> dict:

    guild = guilds.find_one(
        {"guild_id": guild_id},
        {"command_settings": 1, "_id": 0}
    )

    if not guild:
        return {}

    return guild.get("command_settings", {})


def update_command_settings(guild_id: int, settings: dict):

    guilds.update_one(
        {"guild_id": guild_id},
        {
            "$set": {"command_settings": settings},
            "$setOnInsert": {
                "guild_id": guild_id,
                "automod_rules": [],
                "warns": [],
            },
        },
        upsert=True,
    )


def set_log_channel_id(guild_id: int, channel_id: int):

    guilds.update_one(
        {"guild_id": guild_id},
        {
            "$set": {"command_settings.log_channel_id": channel_id},
            "$setOnInsert": {
                "guild_id": guild_id,
                "automod_rules": [],
                "warns": [],
            },
        },
        upsert=True
    )


def get_log_channel_id(guild_id: int) -> int | None:

    guild = guilds.find_one(
        {"guild_id": guild_id},
        {"command_settings.log_channel_id": 1, "_id": 0}
    )

    if not guild:
        return None

    command_settings = guild.get("command_settings", {})
    channel_id = command_settings.get("log_channel_id")

    return channel_id if isinstance(channel_id, int) else None


def get_lhs_settings(guild_id: int) -> Dict[str, Any]:
    """
    Get LHS (AI Moderation) settings for a guild.
    Returns default settings if none exist.
    """
    guild = guilds.find_one(
        {"guild_id": guild_id},
        {"lhs_settings": 1, "_id": 0}
    )
    
    if not guild:
        return DEFAULT_LHS_SETTINGS.copy()
    
    stored_settings = guild.get("lhs_settings", {})
    
    # Merge with defaults
    settings = DEFAULT_LHS_SETTINGS.copy()
    settings.update(stored_settings)
    
    return settings


def update_lhs_settings(guild_id: int, settings: Dict[str, Any]) -> None:
    """
    Update LHS settings for a guild.
    """
    guilds.update_one(
        {"guild_id": guild_id},
        {
            "$set": {"lhs_settings": settings},
            "$setOnInsert": {
                "guild_id": guild_id,
                "automod_rules": [],
                "warns": [],
                "command_settings": {},
            },
        },
        upsert=True,
    )


def set_lhs_enabled(guild_id: int, enabled: bool) -> None:
    """Enable or disable LHS for a guild."""
    guilds.update_one(
        {"guild_id": guild_id},
        {
            "$set": {"lhs_settings.enabled": bool(enabled)},
            "$setOnInsert": {
                "guild_id": guild_id,
                "automod_rules": [],
                "warns": [],
                "command_settings": {},
            },
        },
        upsert=True,
    )


def set_lhs_category(guild_id: int, category: str, enabled: Optional[bool] = None, 
                     threshold: Optional[float] = None) -> None:
    """
    Update a specific category setting for LHS.
    """
    updates = {}
    
    if enabled is not None:
        updates[f"lhs_settings.categories.{category}.enabled"] = bool(enabled)
    
    if threshold is not None:
        updates[f"lhs_settings.categories.{category}.threshold"] = float(threshold)
    
    if updates:
        guilds.update_one(
            {"guild_id": guild_id},
            {
                "$set": updates,
                "$setOnInsert": {
                    "guild_id": guild_id,
                    "automod_rules": [],
                    "warns": [],
                    "command_settings": {},
                },
            },
            upsert=True,
        )


def set_lhs_exemptions(guild_id: int, 
                       roles: Optional[list] = None,
                       channels: Optional[list] = None,
                       users: Optional[list] = None) -> None:
    """Update LHS exemption lists."""
    updates = {}
    
    if roles is not None:
        updates["lhs_settings.exempt_roles"] = roles
    
    if channels is not None:
        updates["lhs_settings.exempt_channels"] = channels
    
    if users is not None:
        updates["lhs_settings.exempt_users"] = users
    
    if updates:
        guilds.update_one(
            {"guild_id": guild_id},
            {
                "$set": updates,
                "$setOnInsert": {
                    "guild_id": guild_id,
                    "automod_rules": [],
                    "warns": [],
                    "command_settings": {},
                },
            },
            upsert=True,
        )


def set_lhs_channel_override(guild_id: int, channel_id: int, override: Dict[str, Any]) -> None:
    """Set per-channel LHS override settings."""
    guilds.update_one(
        {"guild_id": guild_id},
        {
            "$set": {f"lhs_settings.channel_overrides.{channel_id}": override},
            "$setOnInsert": {
                "guild_id": guild_id,
                "automod_rules": [],
                "warns": [],
                "command_settings": {},
            },
        },
        upsert=True,
    )


def delete_lhs_channel_override(guild_id: int, channel_id: int) -> None:
    """Remove per-channel LHS override settings."""
    guilds.update_one(
        {"guild_id": guild_id},
        {
            "$unset": {f"lhs_settings.channel_overrides.{channel_id}": ""},
        },
    )