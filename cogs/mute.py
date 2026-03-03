import asyncio

import fluxer
from fluxer import Cog
from fluxer.checks import has_permission
from typing import Any

from utils.mongodb import get_database

def get_mute_role_id(guild_id: int) -> int:
    db = get_database()
    config_collection = db["guild_configs"]
    config = config_collection.find_one({"guild_id": guild_id})
    if config and "mute_role_id" in config:
        return config["mute_role_id"]
    else:
        raise ValueError(f"Mute role ID not found for guild {guild_id}. Please set it up first.")

class MuteCog(Cog):
    def __init__(self, bot: fluxer.Bot):
        super().__init__(bot)

    def _build_embed(self, title: str, description: str, color: int = 0x5865F2):
        embed = fluxer.Embed(title=title, description=description, color=color)
        embed.set_footer(text="FluxMod Moderation System")
        return embed

    def _resolve_user_id(self, member: Any) -> int | None:
        if isinstance(member, fluxer.GuildMember):
            return member.user.id

        if isinstance(member, int):
            return member

        if isinstance(member, str):
            value = member.strip()

            if value.startswith("<@") and value.endswith(">"):
                value = value[2:-1].replace("!", "")

            if value.isdigit():
                return int(value)

        return None

    


    @Cog.command(name="mute")
    @has_permission(fluxer.Permissions.MODERATE_MEMBERS)
    async def mute(
        self,
        ctx: fluxer.Message,
        member: Any,
        duration: int = 3600,
        *,
        reason: str = "No reason provided"
    ):
        if ctx.guild_id is None:
            await ctx.reply(
                embed=self._build_embed(
                    "Invalid Context",
                    "This command can only be used in a server.",
                    0xFF0000,
                )
            )
            return
        guild_id = int(ctx.guild_id)

        user_id = self._resolve_user_id(member)
        if user_id is None:
            await ctx.reply(
                embed=self._build_embed(
                    "Invalid User",
                    "Use a mention or user ID.",
                    0xFF0000,
                )
            )
            return

        guild = await self.bot.fetch_guild(str(guild_id))
        member_in_guild = await guild.fetch_member(user_id=user_id)

        hours, remainder = divmod(duration, 3600)
        minutes, seconds = divmod(remainder, 60)

        parts = []
        if hours:
            parts.append(f"{hours}h")
        if minutes:
            parts.append(f"{minutes}m")
        if seconds or not parts:
            parts.append(f"{seconds}s")

        try:
            MUTE_ROLE_ID = get_mute_role_id(guild_id)
            await member_in_guild.add_role(role_id=MUTE_ROLE_ID, guild_id=guild_id, reason=reason)

            embed = self._build_embed(
                "User Muted",
                f"User with ID {user_id} has been muted for {' '.join(parts)}.\nReason: {reason}",
                0xFF4500,
            )
            await ctx.reply(embed=embed)

             # Schedule unmute after duration
            async def unmute_after_delay():
                await asyncio.sleep(duration)
                try:
                    MUTE_ROLE_ID = get_mute_role_id(guild_id)
                    await member_in_guild.remove_role(role_id=MUTE_ROLE_ID, guild_id=guild_id, reason="Mute duration expired")
                except Exception as e:
                    print(f"Error auto-unmuting user: {e}")

            # Start the unmute task
            asyncio.create_task(unmute_after_delay())

        except Exception as e:
            await ctx.reply(
                embed=self._build_embed(
                    "Error Muting User",
                    "Failed to mute user.",
                    0xFF0000,
                )
            )
            print(f"Error muting user: {e}")

    @Cog.command(name="unmute")
    @has_permission(fluxer.Permissions.MODERATE_MEMBERS)
    async def unmute(
        self,
        ctx: fluxer.Message,
        member: Any,
        *,
        reason: str = "No reason provided"
    ):

        if ctx.guild_id is None:
            await ctx.reply(
                embed=self._build_embed(
                    "Invalid Context",
                    "This command can only be used in a server.",
                    0xFF0000,
                )
            )
            return
        guild_id = int(ctx.guild_id)

        user_id = self._resolve_user_id(member)
        if user_id is None:
            await ctx.reply(
                embed=self._build_embed(
                    "Invalid User",
                    "Use a mention or user ID.",
                    0xFF0000,
                )
            )
            return

        guild = await self.bot.fetch_guild(str(guild_id))
        member_in_guild = await guild.fetch_member(user_id=user_id)

        try:
            MUTE_ROLE_ID = get_mute_role_id(guild_id)
            await member_in_guild.remove_role(role_id=MUTE_ROLE_ID, guild_id=guild_id, reason=reason)

            embed_unmuted = self._build_embed(
                "User Unmuted",
                f"User with ID {user_id} has been unmuted.",
                0x32CD32,
            )
            await ctx.reply(embed=embed_unmuted)
        except Exception as e:
            embed_error = self._build_embed(
                "Error Unmuting User",
                f"Failed to unmute user with ID {user_id}.\nPlease check with the bot owner for more details.",
                0xFF0000,
            )
            await ctx.reply(embed=embed_error)
            print(f"Error unmuting user: {e}")

async def setup(bot: fluxer.Bot):
    await bot.add_cog(MuteCog(bot))