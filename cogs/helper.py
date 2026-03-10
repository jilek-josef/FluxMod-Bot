from utils import tasks

import fluxer
import asyncio

from fluxer import Cog
from utils.log import log
from utils.datawrapper import DataWrapper
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, cast


class HelperCog(Cog):
    def __init__(self, bot: fluxer.Bot):
        super().__init__(bot)
        self.bot = bot
        self.datawrapper = DataWrapper()
        self._cleanup_run_count = 0
        self._cleanup_last_started_at: datetime | None = None
        self._cleanup_last_finished_at: datetime | None = None
        log("[AutoWarnDel] Initializing cleanup loop (interval=3 minutes).", "info")
        self.auto_warn_cleanup.start()
        log(f"[AutoWarnDel] Loop started: {self.auto_warn_cleanup.is_running}", "info")
        if self.auto_warn_cleanup.current_task is not None:
            log("[AutoWarnDel] Background task created successfully.", "info")

    async def send_mod_log(self, guild: fluxer.Guild, embed: fluxer.Embed):
        """Send an embed to the guild's mod log channel if configured."""
        channel_id = await self.datawrapper.get_log_channel_id(guild.id)
        if not channel_id:
            return

        try:
            channel = await self.bot.fetch_channel(str(channel_id))
            if channel:
                await channel.send(embed=embed)
        except fluxer.NotFound:
            pass
        except fluxer.Forbidden:
            pass

    @staticmethod
    def _as_utc(dt: object) -> datetime | None:
        if not isinstance(dt, datetime):
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    async def _run_cleanup_once(self):
        """Run one cleanup pass for warning expiry."""
        self._cleanup_run_count += 1
        self._cleanup_last_started_at = datetime.now(timezone.utc)
        warnings_by_guild = await self.datawrapper.get_warns_grouped()
        log(
            f"[AutoWarnDel] Tick #{self._cleanup_run_count} started. Guilds tracked: {len(warnings_by_guild)}",
            "info",
        )

        year_ago = datetime.now(timezone.utc) - timedelta(days=30)  # Set to 30 days for testing; change to 365 for production
        removed_count = 0
        guilds_scanned = 0
        users_scanned = 0
        warns_scanned = 0

        for guild_id, members in list(warnings_by_guild.items()):
            try:
                guild = await self.bot.fetch_guild(str(guild_id))
            except Exception:
                guild = None

            if not guild:
                log(f"[AutoWarnDel] Skipping guild {guild_id}: unable to fetch guild.", "debug")
                continue

            guilds_scanned += 1

            for member_id, warns in list(members.items()):
                users_scanned += 1
                warns_scanned += len(warns)
                expired_count = sum(
                    1 for warn in warns
                    if (
                        (ts := self._as_utc(warn.get("timestamp"))) is not None
                        and ts < year_ago
                    )
                )

                if expired_count > 0:
                    diff = expired_count
                    removed_count += diff
                    log(
                        f"[AutoWarnDel] Removed {diff} expired warning(s) for user {member_id} in guild {guild_id}.",
                        "debug",
                    )

                    try:
                        member = await guild.fetch_member(user_id=int(member_id))
                    except Exception:
                        member = None
                    if member:
                        member_user = getattr(member, "user", member)
                        safe_member_id = getattr(member_user, "id", member_id)
                        safe_member_mention = getattr(member_user, "mention", f"<@{safe_member_id}>")

                        embed = fluxer.Embed(
                            title="🗑️ Warning Auto-Deleted",
                            description=(
                                f"**User:** {safe_member_mention} (`{safe_member_id}`)\n"
                                f"**Reason:** Warning expired (30+ days old)\n"
                                f"**Removed:** `{diff}` warning(s)\n"
                                f"**Time:** <t:{int(fluxer.utils.utcnow().timestamp())}:F>"
                            ),
                            color=0xFF4500,
                        )

                        avatar = getattr(member_user, "display_avatar", None)
                        avatar_url = getattr(avatar, "url", None)
                        if avatar_url:
                            embed.set_thumbnail(url=avatar_url)

                        await self.send_mod_log(guild, embed)

        if removed_count > 0:
            removed_in_db = await self.datawrapper.delete_warns_older_than(year_ago)
            self._cleanup_last_finished_at = datetime.now(timezone.utc)
            log(
                f"[AutoWarnDel] Tick #{self._cleanup_run_count} complete. Removed={removed_in_db}, GuildsScanned={guilds_scanned}, UsersScanned={users_scanned}, WarnsScanned={warns_scanned}",
                "success",
            )
        else:
            self._cleanup_last_finished_at = datetime.now(timezone.utc)
            log(
                f"[AutoWarnDel] Tick #{self._cleanup_run_count} complete. No expired warnings found. GuildsScanned={guilds_scanned}, UsersScanned={users_scanned}, WarnsScanned={warns_scanned}",
                "info",
            )

    @tasks.loop(days=1)
    async def auto_warn_cleanup(self):
        """Automatically remove warnings that are older than 30 days."""
        await self._run_cleanup_once()

    @auto_warn_cleanup.before_loop
    async def before_cleanup(self):
        """Wait until the bot is ready before starting the task."""
        log("[AutoWarnDel] Waiting for bot readiness before cleanup loop.", "info")
        wait_ready = cast(Callable[[], Awaitable[None]] | None, getattr(self.bot, "wait_until_ready", None))
        if callable(wait_ready):
            try:
                await asyncio.wait_for(wait_ready(), timeout=120)
                log("[AutoWarnDel] Bot is ready. Cleanup loop can execute.", "info")
            except asyncio.TimeoutError:
                log("[AutoWarnDel] wait_until_ready timed out after 120s; starting cleanup loop anyway.", "warn")
            except Exception as error:
                log(f"[AutoWarnDel] wait_until_ready failed: {error}. Starting cleanup loop anyway.", "warn")
        else:
            log("[AutoWarnDel] Bot has no wait_until_ready method. Starting cleanup loop immediately.", "warn")


    async def cog_unload(self):
        """Cancel the background task when the cog is unloaded."""
        log("[AutoWarnDel] Cog unloading. Cleanup loop cancelled.", "warn")
        self.auto_warn_cleanup.cancel()
        
async def setup(bot: fluxer.Bot):
    await bot.add_cog(HelperCog(bot))

    