import asyncio
import fluxer
from fluxer import Cog
from fluxer.checks import has_permission
from typing import Any

from utils.json_utils import load_json_sync, save_json
from utils.resolvers import resolve_channel_id, resolve_guild_member, resolve_user_id
from utils.warn_storage import WarnStorage
from utils.fluxer_user import FluxerUser

WARN_DB = "data/warns.json"
LOGS_DB = "data/logs.json"

class WarnSystemCog(Cog):
    def __init__(self, bot: fluxer.Bot):
        super().__init__(bot)
        self.bot = bot
        self.warn_storage = WarnStorage(WARN_DB)
        self.log_channels = load_json_sync(LOGS_DB)

    def _build_embed(self, title: str, description: str, color: int = 0x5865F2):
        embed = fluxer.Embed(title=title, description=description, color=color)
        embed.set_footer(text="FluxMod Moderation System")
        return embed

    async def send_mod_log(self, guild: fluxer.Guild, embed: fluxer.Embed):
        guild_id = str(guild.id)
        if guild_id not in self.log_channels:
            return

        channel_id = self.log_channels[guild_id]
        if isinstance(channel_id, str):
            value = channel_id.strip()
            if value.startswith("<#") and value.endswith(">"):
                value = value[2:-1]
            if value.isdigit():
                channel_id = int(value)

        try:
            channel = await self.bot.fetch_channel(str(channel_id))
            if channel:
                await channel.send(embed=embed)
        except fluxer.NotFound:
            pass
        except fluxer.Forbidden:
            pass

    async def dm_user(self, member: fluxer.User | fluxer.GuildMember, embed: fluxer.Embed):
        try:
            fluxer_user = FluxerUser(member)
            await fluxer_user.send_dm(embed=embed)
        except fluxer.Forbidden:
            pass
        except fluxer.NotFound:
            pass

    async def respond_and_delete(self, ctx, content=None, embed: fluxer.Embed | None = None, delay=5):
        if embed is None:
            msg = await ctx.send(content=content)
        else:
            msg = await ctx.send(content=content, embed=embed)
        await asyncio.sleep(delay)
        try:
            await msg.delete()
        except (fluxer.NotFound, fluxer.Forbidden):
            pass

    # ------------------- Commands -------------------

    @Cog.command(name="setlogs")
    @has_permission(fluxer.Permissions.MANAGE_CHANNELS)
    async def setlogs_cmd(self, ctx, channel: Any):
        channel_obj = None
        channel_id = resolve_channel_id(channel)
        if channel_id is not None:
            try:
                channel_obj = await self.bot.fetch_channel(str(channel_id))
            except (fluxer.NotFound, fluxer.Forbidden):
                channel_obj = None

        if not channel_obj:
            await self.respond_and_delete(
                ctx,
                embed=self._build_embed("Invalid Channel", "Use a channel mention or ID.", 0xFF0000)
            )
            return

        self.log_channels[str(ctx.guild.id)] = channel_obj.id
        await save_json(LOGS_DB, self.log_channels)

        await self.respond_and_delete(
            ctx,
            embed=self._build_embed(
                "📝 Mod-Log Channel Set",
                f"Logs will now be sent to {channel_obj.mention}.",
                0x32CD32
            )
        )

    @Cog.command(name="warnings")
    @has_permission(fluxer.Permissions.MANAGE_MESSAGES)
    async def warnings(self, ctx, member: Any):
        guild_id = str(ctx.guild.id)
        user_id = resolve_user_id(member)
        if user_id is None:
            await ctx.reply(embed=self._build_embed("Invalid User", "Use a mention or user ID.", 0xFF0000))
            return

        warning_list_raw = self.warn_storage.get_user_warnings(guild_id, str(user_id))
        warning_list = [f"{w.get('timestamp', 'Unknown time')}: {w.get('reason', 'No reason provided')}" for w in warning_list_raw]

        if warning_list:
            await ctx.reply(embed=self._build_embed(f"Warnings for <@{user_id}>", "\n".join(warning_list), 0xFFFF00))
        else:
            await ctx.reply(embed=self._build_embed("No Warnings Found", f"No warnings found for <@{user_id}>.", 0x32CD32))

    @Cog.command(name="warn")
    @has_permission(fluxer.Permissions.MANAGE_MESSAGES)
    async def warn_cmd(self, ctx, member: Any, reason: str = "No reason provided"):
        user_id = resolve_user_id(member)
        if user_id is None:
            await ctx.reply(embed=self._build_embed("Invalid User", "Use a mention or user ID.", 0xFF0000))
            return

        guild_id = str(ctx.guild.id)
        warning_payload = {
            "user_id": str(user_id),
            "reason": reason,
            "moderator": str(ctx.author.id),
            "timestamp": fluxer.utils.utcnow().isoformat()
        }
        await self.warn_storage.add_warning(guild_id, str(user_id), warning_payload)

        target_member = await resolve_guild_member(self.bot, ctx, member)
        display_name = target_member.display_name if target_member else str(user_id)
        mention = target_member.mention if target_member else f"<@{user_id}>"

        await self.respond_and_delete(ctx, embed=self._build_embed(f"⚠️ Warned {display_name}", f"Reason: {reason}", 0xFFA500))

        if target_member:
            dm_embed = self._build_embed("⚠️ You’ve received a warning!", f"Server: **{ctx.guild.name}**\nReason: {reason}")
            await self.dm_user(target_member, dm_embed)

        log_embed = self._build_embed(
            "⚠️ User Warned",
            f"**User:** {mention} ({user_id})\n**Moderator:** {ctx.author.mention} ({ctx.author.id})\n**Reason:** {reason}\n**Timestamp:** <t:{int(fluxer.utils.utcnow().timestamp())}:F>",
            0xFFA500
        )
        if target_member:
            target_user = getattr(target_member, "user", target_member)
            avatar = getattr(target_user, "display_avatar", None)
            avatar_url = getattr(avatar, "url", None)
            if avatar_url:
                log_embed.set_thumbnail(url=avatar_url)
        await self.send_mod_log(ctx.guild, log_embed)

    @Cog.command(name="delwarn")
    @has_permission(fluxer.Permissions.MANAGE_MESSAGES)
    async def delwarn(self, ctx, member: Any, index: int):
        guild_id = str(ctx.guild.id)
        user_id = resolve_user_id(member)
        if user_id is None:
            await ctx.reply(embed=self._build_embed("Invalid User", "Use a mention or user ID.", 0xFF0000))
            return

        deleted = await self.warn_storage.delete_warning_by_index(guild_id, str(user_id), index)
        if deleted:
            await ctx.reply(embed=self._build_embed("Warning Deleted", f"Deleted warning {index} for <@{user_id}>.", 0xFFA500))
        else:
            await ctx.reply(embed=self._build_embed("Invalid Warning Index", f"Invalid warning index for <@{user_id}>.", 0xFF0000))


async def setup(bot: fluxer.Bot):
    await bot.add_cog(WarnSystemCog(bot))