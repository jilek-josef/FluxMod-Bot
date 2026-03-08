from database.mongo import MongoDB
from typing import List, Dict, Optional

db = MongoDB()
guilds = db.collection("guild_settings")


def get_rules(guild_id: int) -> List[Dict]:
    """Return all automod rules for a guild."""

    guild = guilds.find_one(
        {"guild_id": guild_id},
        {"automod_rules": 1, "_id": 0}
    )

    if not guild:
        return []

    return guild.get("automod_rules", [])


def get_enabled_rules(guild_id: int) -> List[Dict]:
    """Return only enabled rules."""

    rules = get_rules(guild_id)

    return [rule for rule in rules if rule.get("enabled", False)]


def get_rule(guild_id: int, rule_name: str) -> Optional[Dict]:
    """Return a specific rule by name."""

    rules = get_rules(guild_id)

    for rule in rules:
        if rule.get("rule_name") == rule_name:
            return rule

    return None