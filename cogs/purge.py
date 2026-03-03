import fluxer

from fluxer import Cog
from fluxer.checks import has_permission

class PurgeCog(Cog):
    def __init__(self, bot: fluxer.Bot):
        super().__init__(bot)

    @Cog.command(name="purge")
    @has_permission(fluxer.Permissions.MANAGE_MESSAGES)
    async def purge(self, ctx: fluxer.Message, limit: int = 100):
        if ctx.guild_id is None:
            await ctx.reply("This command can only be used in a server.")
            return

        try:
            fetched_messages = await ctx.channel.fetch_messages(limit=limit + 1)

            fetched_message_ids: list[int | str] = [msg.id for msg in fetched_messages]
            deleted = await ctx.channel.delete_messages(message_ids=fetched_message_ids)
            deleted_count = limit
            await ctx.send(f"Deleted {deleted_count} messages.")
        except Exception as e:
            await ctx.reply("Failed to delete messages. Please check with the bot owner for more details.")
            print(f"Error purging messages: {e}")

async def setup(bot: fluxer.Bot):
    await bot.add_cog(PurgeCog(bot))