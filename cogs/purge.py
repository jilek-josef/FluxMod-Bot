import fluxer

from fluxer import Cog
from fluxer.checks import has_permission
from typing import Any

class PurgeCog(Cog):
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
    
    #TODO: Add optional user filter to only delete messages from a specific user. This would involve checking the author of each message against the resolved user ID before deletion.

    @Cog.command(name="purge")
    @has_permission(fluxer.Permissions.MANAGE_MESSAGES)
    async def purge(self, ctx: fluxer.Message, limit: int = 100):
        if ctx.guild_id is None:
            await ctx.reply(
                embed=self._build_embed(
                    "Invalid Context",
                    "This command can only be used in a server.",
                    0xFF0000,
                )
            )
            return
            
        try:

        
            fetched_messages = await ctx.channel.fetch_messages(limit=limit + 1)

            fetched_message_ids: list[int | str] = [msg.id for msg in fetched_messages]
            deleted = await ctx.channel.delete_messages(message_ids=fetched_message_ids)
            deleted_count = limit
            embed = self._build_embed(
                "Purge Completed",
                f"Deleted {deleted_count} messages.",
                0x00FF00,
            )
            await ctx.send(embed=embed)

        except Exception as e:
            await ctx.reply(
                embed=self._build_embed(
                    "Error Purging Messages",
                    "Failed to delete messages. Please check with the bot owner for more details.",
                    0xFF0000,
                )
            )
            print(f"Error purging messages: {e}")

async def setup(bot: fluxer.Bot):
    await bot.add_cog(PurgeCog(bot))