from database.mongo import MongoDB
from typing import List, Dict, Optional, Any
import uuid

db = MongoDB()
guilds = db.collection("guild_settings")


def _as_string_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None]


def _normalize_rule(rule: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize incoming rule payload to the canonical DB schema."""
    if not isinstance(rule, dict):
        rule = {}

    rule_name = str(rule.get("name") or rule.get("rule_name") or "AutoMod Rule")
    pattern = rule.get("pattern", "")
    action = str(rule.get("action", "warn") or "warn")
    keywords = _as_string_list(rule.get("keywords", []))
    allowed_patterns = _as_string_list(rule.get("allowed_patterns", []))
    exempt_roles = _as_string_list(rule.get("exempt_roles", []))
    exempt_channels = _as_string_list(rule.get("exempt_channels", []))
    exempt_users = _as_string_list(rule.get("exempt_users", []))

    try:
        threshold = int(rule.get("threshold", 1))
    except Exception:
        threshold = 1

    return {
        "id": str(rule.get("id") or uuid.uuid4()),
        "name": rule_name,
        # Keep legacy alias for older callsites that still query by rule_name.
        "rule_name": rule_name,
        "pattern": pattern if isinstance(pattern, str) else "",
        "action": action,
        "keywords": keywords,
        "allowed_patterns": allowed_patterns,
        "threshold": threshold if threshold > 0 else 1,
        "enabled": bool(rule.get("enabled", True)),
        "exempt_roles": exempt_roles,
        "exempt_channels": exempt_channels,
        "exempt_users": exempt_users,
    }


def get_rules(guild_id: int) -> List[Dict]:
    """Return all automod rules for a guild."""

    guild = guilds.find_one(
        {"guild_id": guild_id},
        {"automod_rules": 1, "_id": 0}
    )

    if not guild:
        return []

    raw_rules = guild.get("automod_rules", [])
    if not isinstance(raw_rules, list):
        return []

    return [_normalize_rule(rule) for rule in raw_rules if isinstance(rule, dict)]


def get_enabled_rules(guild_id: int) -> List[Dict]:
    """Return only enabled rules."""

    rules = get_rules(guild_id)

    return [rule for rule in rules if rule.get("enabled", False)]


def get_rule(guild_id: int, rule_name: str) -> Optional[Dict]:
    """Return a specific rule by name."""

    rules = get_rules(guild_id)

    for rule in rules:
        if rule.get("rule_name") == rule_name or rule.get("name") == rule_name:
            return rule

    return None


def set_rules(guild_id: int, rules: List[Dict]) -> None:
    """Replace all automod rules for a guild."""

    normalized_rules = [_normalize_rule(rule) for rule in rules if isinstance(rule, dict)]

    guilds.update_one(
        {"guild_id": guild_id},
        {
            "$set": {"automod_rules": normalized_rules},
            "$setOnInsert": {
                "guild_id": guild_id,
                "command_settings": {},
                "warns": [],
            },
        },
        upsert=True,
    )


def set_rule(guild_id: int, rule_name: str, rule_data: Dict) -> None:
    """Create or replace a single automod rule identified by rule_name."""

    rules = get_rules(guild_id)
    updated = False
    next_rules: List[Dict] = []

    for rule in rules:
        if rule.get("rule_name") == rule_name or rule.get("name") == rule_name:
            next_rule = dict(rule_data)
            next_rule["rule_name"] = rule_name
            next_rule["name"] = rule_name
            next_rules.append(next_rule)
            updated = True
        else:
            next_rules.append(rule)

    if not updated:
        next_rule = dict(rule_data)
        next_rule["rule_name"] = rule_name
        next_rule["name"] = rule_name
        next_rules.append(next_rule)

    set_rules(guild_id, next_rules)


def set_rule_enabled(guild_id: int, rule_name: str, enabled: bool) -> bool:
    """Set enabled state for one rule. Returns False if rule does not exist."""

    rule = get_rule(guild_id, rule_name)
    if not rule:
        return False

    updated_rule = dict(rule)
    updated_rule["enabled"] = bool(enabled)
    set_rule(guild_id, rule_name, updated_rule)
    return True


def delete_rule(guild_id: int, rule_name: str) -> bool:
    """Delete one rule by name. Returns False if nothing was removed."""

    rules = get_rules(guild_id)
    next_rules = [
        rule
        for rule in rules
        if rule.get("rule_name") != rule_name and rule.get("name") != rule_name
    ]
    if len(next_rules) == len(rules):
        return False

    set_rules(guild_id, next_rules)
    return True