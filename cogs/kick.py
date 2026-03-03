import fluxer
from fluxer import Cog
from fluxer.checks import has_permission
from typing import Any

class KickCog(Cog):
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

    @Cog.command(name="kick")
    @has_permission(fluxer.Permissions.KICK_MEMBERS)   
    async def kick(self, ctx: fluxer.Message, member: Any, *, reason: str = "No reason provided"):

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
        member_in_guild = await guild.fetch_member(user_id=user_id)

        try:
            await member_in_guild.kick(guild_id=int(ctx.guild_id), reason=reason)
            embed_kick = self._build_embed(
                "User Kicked",
                f"User with ID {user_id} has been kicked.\nReason: {reason}",
                0xFFA500,
            )
            await ctx.reply(embed=embed_kick)
        except Exception as e:
            embed_error = self._build_embed(
                "Error Kicking User",
                f"Failed to kick user with ID {user_id}.\nPlease check with the bot owner for more details.",
                0xFF0000,
            )
            await ctx.reply(embed=embed_error)
            print(f"Error kicking user: {e}")

async def setup(bot: fluxer.Bot):
    await bot.add_cog(KickCog(bot))