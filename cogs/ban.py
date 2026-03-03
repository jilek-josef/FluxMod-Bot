import fluxer
from fluxer import Cog
from fluxer.checks import has_permission
from typing import Any

class BanCog(Cog):
    def __init__(self, bot: fluxer.Bot):
        super().__init__(bot)

    def _build_embed(self, title: str, description: str, color: int = 0x5865F2):
        embed = fluxer.Embed(title=title, description=description, color=color)
        embed.set_footer(text="FluxMod Moderation System")
        return embed

    def _resolve_user_id(self, member: Any) -> int | None:
        if isinstance(member, fluxer.GuildMember):
            return member.user.id

        if isinstance(member, fluxer.User):
            return member.id

        if isinstance(member, int):
            return member

        if isinstance(member, str):
            value = member.strip()

            if value.startswith("<@") and value.endswith(">"):
                value = value[2:-1].replace("!", "")

            if value.isdigit():
                return int(value)

        return None

    @Cog.command(name="ban")
    @has_permission(fluxer.Permissions.BAN_MEMBERS)
    async def ban(self, ctx: fluxer.Message, member: Any, *, reason: str = "No reason provided"):

        if ctx.guild_id is None:
            await ctx.reply(
                embed=self._build_embed(
                    "Invalid Context",
                    "This command can only be used in a server.",
                    0xFF0000,
                )
            )
            return

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

        guild = await self.bot.fetch_guild(str(ctx.guild_id))

        try:
            embed_ban = self._build_embed(
                "User Banned",
                f"User with ID {user_id} has been banned.\nReason: {reason}",
                0xFF0000,
            )
            await guild.ban(user_id, reason=reason)
            await ctx.reply(embed=embed_ban)
        except Exception as e:
            embed_error = self._build_embed(
                "Error Banning User",
                f"Failed to ban user with ID {user_id}.\nPlease check with the bot owner for more details.",
                0xFF0000,
            )
            await ctx.reply(embed=embed_error)
            print(f"Error banning user: {e}")

    @Cog.command(name="unban")
    @has_permission(fluxer.Permissions.BAN_MEMBERS)
    async def unban(self, ctx: fluxer.Message, member: Any, *, reason: str = "No reason provided"):

        if ctx.guild_id is None:
            await ctx.reply(
                embed=self._build_embed(
                    "Invalid Context",
                    "This command can only be used in a server.",
                    0xFF0000,
                )
            )
            return

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

        guild = await self.bot.fetch_guild(str(ctx.guild_id))

        try:
            await guild.unban(user_id, reason=reason)
            embed_unban = self._build_embed(
                "User Unbanned",
                f"User with ID {user_id} has been unbanned.\nReason: {reason}",
                0x32CD32,
            )
            await ctx.reply(embed=embed_unban)
        except Exception as e:
            embed_error = self._build_embed(
                "Error Unbanning User",
                f"Failed to unban user with ID {user_id}.\nPlease check with the bot owner for more details.",
                0xFF0000,
            )
            await ctx.reply(embed=embed_error)
            print(f"Error unbanning user: {e}")

async def setup(bot: fluxer.Bot):
    await bot.add_cog(BanCog(bot))