import fluxer
from fluxer import Cog
from typing import Any

from database.guilds import update_bot_guild_count
from utils.log import log

class GuildsCog(Cog):
    def __init__(self, bot: fluxer.Bot):
        super().__init__(bot)
        self.bot = bot

    @staticmethod
    def _guild_id(guild: Any) -> int | str:
        if isinstance(guild, dict):
            return guild.get("id", "unknown")
        return getattr(guild, "id", "unknown")

    @Cog.listener()
    async def on_guild_join(self, guild: fluxer.Guild | dict):
        guild_id = self._guild_id(guild)
        try:
            update_bot_guild_count(len(getattr(self.bot, "guilds", []) or []))
        except Exception as error:
            log(f"Failed to update MongoDB on guild join ({guild_id}): {error}", "warn")
        log(f"Joined new guild ID: {guild_id}", "info")

    @Cog.listener()
    async def on_guild_remove(self, guild: fluxer.Guild | dict):
        guild_id = self._guild_id(guild)
        try:
            update_bot_guild_count(len(getattr(self.bot, "guilds", []) or []))
        except Exception as error:
            log(f"Failed to update MongoDB on guild remove ({guild_id}): {error}", "warn")
        log(f"Removed from guild ID: {guild_id}", "info")

async def setup(bot):
    await bot.add_cog(GuildsCog(bot))