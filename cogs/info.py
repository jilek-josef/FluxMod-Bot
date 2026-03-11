import fluxer
from datetime import datetime, timezone
from fluxer import Cog

class InfoCog(Cog):
    def __init__(self, bot: fluxer.Bot):
        super().__init__(bot)
        self.bot = bot

    @staticmethod
    def _get_system_latency_text(ctx) -> str:
        """Measure system latency from message creation to command handling."""
        created_at = getattr(ctx, "created_at", None)
        if created_at is None:
            return "Unavailable"

        now = datetime.now(timezone.utc)
        latency_ms = max((now - created_at).total_seconds() * 1000, 0)
        return f"{latency_ms:.2f} ms"

    @Cog.command(name="info")
    async def info(self, ctx):
        user = self.bot.user
        if user is None:
            await ctx.send("Bot information is unavailable.")
            return

        embed = fluxer.Embed(
            title="FluxMod Information",
            description="A modular Fluxer bot built with Fluxer.py.",
            color=0x00ff00
        )
        embed.add_field(name="Developer", value="UncleMelo", inline=False)
        embed.add_field(name="Library", value="[Fluxer.py](https://github.com/akarealemil/fluxer.py)", inline=False)
        guild_count = len(getattr(self.bot, "guilds", []) or [])
        embed.add_field(name="Guilds", value=str(guild_count), inline=False)
        embed.add_field(name="System Latency", value=self._get_system_latency_text(ctx), inline=False)
        embed.set_footer(text=f"Bot ID: {user.id}")

        try:
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"Failed to send info embed: {e}")

async def setup(bot):
    await bot.add_cog(InfoCog(bot))