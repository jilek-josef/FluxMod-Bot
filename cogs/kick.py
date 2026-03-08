import fluxer
from fluxer import Cog
from typing import Any

class KickCog(Cog):
    def __init__(self, bot: fluxer.Bot):
        super().__init__(bot)

    def _build_embed(self, title: str, description: str, color: int = 0x5865F2):
        embed = fluxer.Embed(title=title, description=description, color=color)
        embed.set_footer(text="FluxMod Moderation System")
        return embed

    def _permission_value(self, permission: Any) -> int:
        raw_value = getattr(permission, "value", permission)
        try:
            return int(raw_value)
        except Exception:
            return 0

    def _has_required_permission(self, ctx: fluxer.Message, permission: Any) -> bool:
        author = getattr(ctx, "author", None)
        if author is None:
            return False

        perms = getattr(author, "permissions", None)
        if perms is None:
            return True

        user_perms = self._permission_value(perms)
        needed = self._permission_value(permission)
        if needed <= 0:
            return True
        return (user_perms & needed) == needed

    async def _ensure_permission_or_reply(self, ctx: fluxer.Message, permission: Any, label: str) -> bool:
        if self._has_required_permission(ctx, permission):
            return True

        await ctx.reply(
            embed=self._build_embed(
                "Missing Permission",
                f"You need `{label}` to use this command.",
                0xFF0000,
            )
        )
        return False

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
    async def kick(self, ctx: fluxer.Message, member: Any, *, reason: str = "No reason provided"):
        if not await self._ensure_permission_or_reply(ctx, fluxer.Permissions.KICK_MEMBERS, "KICK_MEMBERS"):
            return

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
            await member_in_guild.kick(reason=reason)
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