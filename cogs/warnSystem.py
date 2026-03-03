import fluxer
from fluxer import Cog
from typing import Any

from utils.mongodb import get_database

class WarnSystemCog(Cog):
    def __init__(self, bot: fluxer.Bot):
        super().__init__(bot)
        self.db = get_database(db_name="warn_system")

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

    @Cog.command(name="warnings")
    async def warnings(self, ctx, member: Any):
        """Retrieve and display all warnings for a user."""
        guild_id = ctx.guild_id
        user_id = self._resolve_user_id(member)
        if user_id is None:
            await ctx.reply(
                embed=self._build_embed(
                    "Invalid User",
                    "Use a mention or user ID.",
                    0xFF0000
                )
            )
            return

        warnings = self.db.warnings.find({"guild_id": guild_id, "warning.user_id": user_id})
        warning_list = [f"{w['warning']['timestamp']}: {w['warning']['reason']}" for w in warnings]

        if warning_list:
            await ctx.reply(
                embed=self._build_embed(
                    f"Warnings for <@{user_id}>",
                    "\n".join(warning_list),
                    0xFFFF00
                )
            )
        else:
            await ctx.reply(
                embed=self._build_embed(
                    "No Warnings Found",
                    f"No warnings found for <@{user_id}>.",
                    0x32CD32
                )
            )

    @Cog.command(name="warn")
    async def warn(self, ctx, member: Any, *, reason: str = "No reason provided"):
        """Warn a user and log the warning in the database."""
        guild_id = ctx.guild_id
        user_id = self._resolve_user_id(member)
        if user_id is None:
            await ctx.reply(
                embed=self._build_embed(
                    "Invalid User",
                    "Use a mention or user ID.",
                    0xFF0000
                )
            )
            return

        warning = {
            "user_id": user_id,
            "reason": reason,
            "timestamp": ctx.created_at.isoformat()
        }
        self.db.warnings.insert_one({"guild_id": guild_id, "warning": warning})
        await ctx.reply(
            embed=self._build_embed(
                "User Warned",
                f"User <@{user_id}> has been warned for: {reason}",
                0xFFA500
            )
        )

    @Cog.command(name="delwarn")
    async def delwarn(self, ctx, member: Any, index: int):
        """Delete a specific warning for a user."""
        guild_id = ctx.guild_id
        user_id = self._resolve_user_id(member)
        if user_id is None:
            await ctx.reply(
                embed=self._build_embed(
                    "Invalid User",
                    "Use a mention or user ID.",
                    0xFF0000
                )
            )
            return

        warnings = list(self.db.warnings.find({"guild_id": guild_id, "warning.user_id": user_id}))
        if 0 <= index < len(warnings):
            self.db.warnings.delete_one({"_id": warnings[index]["_id"]})
            await ctx.reply(
                embed=self._build_embed(
                    "Warning Deleted",
                    f"Deleted warning {index} for <@{user_id}>.",
                    0xFFA500
                )
            )
        else:
            await ctx.reply(
                embed=self._build_embed(
                    "Invalid Warning Index",
                    f"Invalid warning index for <@{user_id}>.",
                    0xFF0000
                )
            )

async def setup(bot: fluxer.Bot):
    await bot.add_cog(WarnSystemCog(bot))