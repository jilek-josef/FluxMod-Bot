import asyncio
import fluxer
from fluxer import Cog
from typing import Any

from utils.resolvers import resolve_channel_id, resolve_guild_member, resolve_user_id
from utils.fluxer_user import FluxerUser
from utils.datawrapper import DataWrapper
from utils.delete_after import delete_after

class WarnSystemCog(Cog):
    def __init__(self, bot: fluxer.Bot):
        super().__init__(bot)
        self.bot = bot
        self.datawrapper = DataWrapper()

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

    def _has_required_permission(self, ctx, permission: Any) -> bool:
        """
        Local permission check to avoid hard failures from Fluxer's decorator path.
        If permission payload is unavailable in this context, fallback allows command.
        """
        author = getattr(ctx, "author", None)
        if author is None:
            return False

        perms = getattr(author, "permissions", None)
        if perms is None:
            # Fallback for gateway payloads that omit permission bitfields.
            return True

        user_perms = self._permission_value(perms)
        needed = self._permission_value(permission)
        if needed <= 0:
            return True
        return (user_perms & needed) == needed

    async def _ensure_permission_or_reply(self, ctx, permission: Any, label: str) -> bool:
        if self._has_required_permission(ctx, permission):
            return True

        warning_message = await ctx.reply(
            embed=self._build_embed(
                "Missing Permission",
                f"You need `{label}` to use this command.",
                0xFF0000,
            )
        )
        await delete_after(warning_message, 10)
        return False

    async def send_mod_log(self, guild: fluxer.Guild, embed: fluxer.Embed):
        await self.datawrapper.ensure_guild(guild.id)
        channel_id = await self.datawrapper.get_log_channel_id(guild.id)
        if channel_id is None:
            return

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
    async def setlogs_cmd(self, ctx, channel: Any):
        if not await self._ensure_permission_or_reply(ctx, fluxer.Permissions.MANAGE_CHANNELS, "MANAGE_CHANNELS"):
            return

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

        await self.datawrapper.ensure_guild(ctx.guild.id)
        await self.datawrapper.set_log_channel_id(ctx.guild.id, channel_obj.id)

        await self.respond_and_delete(
            ctx,
            embed=self._build_embed(
                "📝 Mod-Log Channel Set",
                f"Logs will now be sent to {channel_obj.mention}.",
                0x32CD32
            )
        )

    @Cog.command(name="warnings")
    async def warnings(self, ctx, member: Any):
        if not await self._ensure_permission_or_reply(ctx, fluxer.Permissions.MANAGE_MESSAGES, "MANAGE_MESSAGES"):
            return

        guild_id = ctx.guild.id
        user_id = resolve_user_id(member)
        if user_id is None:
            warning_message = await ctx.reply(embed=self._build_embed("Invalid User", "Use a mention or user ID.", 0xFF0000))
            await delete_after(warning_message, 10)
            return

        warning_list_raw = await self.datawrapper.get_warns(guild_id, user_id)
        warning_list = [
            f"{w.get('timestamp', 'Unknown time')}: {w.get('reason', 'No reason provided')}"
            for w in warning_list_raw
        ]

        if warning_list:
            await ctx.reply(embed=self._build_embed(f"Warnings for <@{user_id}>", "\n".join(warning_list), 0xFFFF00))
        else:
            await ctx.reply(embed=self._build_embed("No Warnings Found", f"No warnings found for <@{user_id}>.", 0x32CD32))

    @Cog.command(name="warn")
    async def warn_cmd(self, ctx, member: Any, reason: str = "No reason provided"):
        if not await self._ensure_permission_or_reply(ctx, fluxer.Permissions.MANAGE_MESSAGES, "MANAGE_MESSAGES"):
            return

        user_id = resolve_user_id(member)
        if user_id is None:
            warning_message = await ctx.reply(embed=self._build_embed("Invalid User", "Use a mention or user ID.", 0xFF0000))
            await delete_after(warning_message, 10)
            return

        guild_id = ctx.guild.id
        await self.datawrapper.add_warn(guild_id, user_id, ctx.author.id, reason)

        target_member = await resolve_guild_member(self.bot, ctx, member)
        display_name = target_member.display_name if target_member else str(user_id)
        mention = target_member.mention if target_member else f"<@{user_id}>"

        await self.respond_and_delete(ctx, embed=self._build_embed(f"⚠️ Warned {display_name}", f"Reason: {reason}", 0xFFA500))

        if target_member:
            dm_embed = self._build_embed("⚠️ You've received a warning!", f"Server: **{ctx.guild.name}**\nReason: {reason}")
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
    async def delwarn(self, ctx, member: Any, index: int):
        if not await self._ensure_permission_or_reply(ctx, fluxer.Permissions.MANAGE_MESSAGES, "MANAGE_MESSAGES"):
            return

        guild_id = ctx.guild.id
        user_id = resolve_user_id(member)
        if user_id is None:
            warning_message = await ctx.reply(embed=self._build_embed("Invalid User", "Use a mention or user ID.", 0xFF0000))
            await delete_after(warning_message, 10)
            return

        deleted = await self.datawrapper.remove_warn_by_index(guild_id, user_id, index)
        if deleted:
            confirmation_message = await ctx.reply(embed=self._build_embed("Warning Deleted", f"Deleted warning {index} for <@{user_id}>.", 0xFFA500))
            await delete_after(confirmation_message, 15)
        else:
            error_message = await ctx.reply(embed=self._build_embed("Invalid Warning Index", f"Invalid warning index for <@{user_id}>.", 0xFF0000))
            await delete_after(error_message, 10)


async def setup(bot: fluxer.Bot):
    await bot.add_cog(WarnSystemCog(bot))