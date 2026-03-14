from typing import List, Dict, Any
from datetime import datetime

from database.guilds import (
    get_guild,
    create_guild,
    get_command_settings,
    update_command_settings,
    get_log_channel_id,
    set_log_channel_id,
    get_lhs_settings,
    update_lhs_settings,
    set_lhs_enabled,
    set_lhs_category,
    set_lhs_exemptions,
    set_lhs_channel_override,
    delete_lhs_channel_override,
)
from database.automod import (
    get_rules,
    get_enabled_rules,
    get_rule,
    set_rules,
    set_rule,
    set_rule_enabled,
    delete_rule,
)
from database.warns import (
    add_warn,
    get_user_warns,
    remove_warn,
    clear_user_warns,
    remove_warn_by_index,
    get_warns_grouped_by_guild_user,
    delete_warns_older_than,
)
from utils.lhs_client import GuildLHSSettings


class DataWrapper:

    def __init__(self):

        self._automod_cache: Dict[int, List[dict]] = {}

    async def ensure_guild(self, guild_id: int):

        guild = get_guild(guild_id)

        if not guild:
            create_guild(guild_id)

    async def get_guild_data(self, guild_id: int) -> dict | None:

        return get_guild(guild_id)

    async def get_command_settings(self, guild_id: int) -> dict:

        return get_command_settings(guild_id)

    async def get_guild_config(self, guild_id: int) -> dict:

        return await self.get_command_settings(guild_id)

    async def update_command_settings(self, guild_id: int, settings: dict):

        update_command_settings(guild_id, settings)

    async def set_guild_config(self, guild_id: int, config: dict):

        await self.update_command_settings(guild_id, config)

    async def get_automod_rules(self, guild_id: int) -> List[dict]:

        if guild_id in self._automod_cache:
            return self._automod_cache[guild_id]

        rules = get_rules(guild_id)

        self._automod_cache[guild_id] = rules

        return rules
    
    async def get_enabled_automod_rules(self, guild_id: int) -> List[dict]:

        return get_enabled_rules(guild_id)
    
    async def get_automod_rule(self, guild_id: int, rule_name: str) -> dict | None:

        return get_rule(guild_id, rule_name)

    async def set_automod_rules(self, guild_id: int, rules: List[dict]):

        set_rules(guild_id, rules)
        self._automod_cache[guild_id] = rules

    async def set_automod_rule(self, guild_id: int, rule_name: str, rule_data: dict):

        set_rule(guild_id, rule_name, rule_data)
        await self.invalidate_automod_cache(guild_id)

    async def set_automod_rule_enabled(self, guild_id: int, rule_name: str, enabled: bool) -> bool:

        changed = set_rule_enabled(guild_id, rule_name, enabled)
        if changed:
            await self.invalidate_automod_cache(guild_id)
        return changed

    async def delete_automod_rule(self, guild_id: int, rule_name: str) -> bool:

        deleted = delete_rule(guild_id, rule_name)
        if deleted:
            await self.invalidate_automod_cache(guild_id)
        return deleted

    async def invalidate_automod_cache(self, guild_id: int):

        self._automod_cache.pop(guild_id, None)

    async def add_warn(self, guild_id: int, user_id: int, mod_id: int, reason: str):

        add_warn(guild_id, user_id, mod_id, reason)

    async def get_warns(self, guild_id: int, user_id: int):

        return get_user_warns(guild_id, user_id)
    
    async def remove_warn(self, guild_id: int, user_id: int, warn_id):
        
        remove_warn(guild_id, user_id, warn_id)

    async def clear_warns(self, guild_id: int, user_id: int):
        
        clear_user_warns(guild_id, user_id)

    async def remove_warn_by_index(self, guild_id: int, user_id: int, index: int) -> bool:

        return remove_warn_by_index(guild_id, user_id, index)

    async def get_warns_grouped(self) -> dict[int, dict[int, list[dict]]]:

        return get_warns_grouped_by_guild_user()

    async def delete_warns_older_than(self, cutoff: datetime) -> int:

        return delete_warns_older_than(cutoff)

    async def set_log_channel_id(self, guild_id: int, channel_id: int):

        set_log_channel_id(guild_id, channel_id)

    async def get_log_channel_id(self, guild_id: int) -> int | None:

        return get_log_channel_id(guild_id)

    # LHS (AI Moderation) methods

    async def get_lhs_settings(self, guild_id: int) -> GuildLHSSettings:
        """
        Get LHS settings for a guild as a GuildLHSSettings object.
        """
        settings_dict = get_lhs_settings(guild_id)
        settings_dict["guild_id"] = guild_id
        return GuildLHSSettings.from_dict(settings_dict)

    async def update_lhs_settings(self, guild_id: int, settings: Dict[str, Any]) -> None:
        """
        Update LHS settings for a guild.
        """
        update_lhs_settings(guild_id, settings)

    async def set_lhs_enabled(self, guild_id: int, enabled: bool) -> None:
        """
        Enable or disable LHS for a guild.
        """
        set_lhs_enabled(guild_id, enabled)

    async def set_lhs_category(self, guild_id: int, category: str, 
                               enabled: bool = None, threshold: float = None) -> None:
        """
        Update a specific category setting for LHS.
        """
        set_lhs_category(guild_id, category, enabled, threshold)

    async def set_lhs_exemptions(self, guild_id: int,
                                  roles: List[int] = None,
                                  channels: List[int] = None,
                                  users: List[int] = None) -> None:
        """
        Update LHS exemption lists.
        """
        set_lhs_exemptions(
            guild_id,
            roles=roles,
            channels=channels,
            users=users,
        )

    async def set_lhs_channel_override(self, guild_id: int, channel_id: int, 
                                       override: Dict[str, Any]) -> None:
        """
        Set per-channel LHS override settings.
        """
        set_lhs_channel_override(guild_id, channel_id, override)

    async def delete_lhs_channel_override(self, guild_id: int, channel_id: int) -> None:
        """
        Remove per-channel LHS override settings.
        """
        delete_lhs_channel_override(guild_id, channel_id)