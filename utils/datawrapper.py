from typing import List, Dict
from datetime import datetime

from database.guilds import (
    get_guild,
    create_guild,
    get_command_settings,
    update_command_settings,
    get_log_channel_id,
    set_log_channel_id,
)
from database.automod import get_rules, get_enabled_rules, get_rule
from database.warns import (
    add_warn,
    get_user_warns,
    remove_warn,
    clear_user_warns,
    remove_warn_by_index,
    get_warns_grouped_by_guild_user,
    delete_warns_older_than,
)


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

    async def update_command_settings(self, guild_id: int, settings: dict):

        update_command_settings(guild_id, settings)

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