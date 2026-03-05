from utils import tasks

import fluxer
import asyncio
import json # This is to test auto deleting data before using mongoDB
import os
import aiofiles
import re

from fluxer import Cog
from utils.log import log
from datetime import datetime, timedelta, timezone

# These data files are temporary and will be replaced with a proper database in the future. They are used to store warnings and logs for moderation actions.
WARN_DB = "data/warns.json"
LOG_DB = "data/logs.json"


class HelperCog(Cog):
    def __init__(self, bot: fluxer.Bot):
        super().__init__(bot)
        self.bot = bot
        self.warnings = self.load_json_sync(WARN_DB)
        self.log_channels = self.load_json_sync(LOG_DB)
        self._cleanup_run_count = 0
        self._cleanup_last_started_at: datetime | None = None
        self._cleanup_last_finished_at: datetime | None = None
        log("[AutoWarnDel] Initializing cleanup loop (interval=3 minutes).", "info")
        self.auto_warn_cleanup.start()
        log(f"[AutoWarnDel] Loop started: {self.auto_warn_cleanup.is_running}", "info")
        if self.auto_warn_cleanup.current_task is not None:
            log("[AutoWarnDel] Background task created successfully.", "info")

    def load_json_sync(self, path: str) -> dict:
        """Load a JSON file synchronously with safe defaults."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                json.dump({}, f)
            return {}

        try:
            with open(path, "r", encoding="utf-8") as file:
                return json.load(file)
        except (json.JSONDecodeError, FileNotFoundError):
            return {}


    async def save_json(self, path: str, data: dict):
        """Save data to JSON asynchronously."""
        async with aiofiles.open(path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(data, indent=4, ensure_ascii=False))

    async def send_mod_log(self, guild: fluxer.Guild, embed: fluxer.Embed):
        """Send an embed to the guild's mod log channel if configured."""
        channel_id = self.log_channels.get(str(guild.id))
        if not channel_id:
            return

        try:
            channel = await self.bot.fetch_channel(channel_id)
            if channel:
                await channel.send(embed=embed)
        except fluxer.NotFound:
            pass
        except fluxer.Forbidden:
            pass

    async def _run_cleanup_once(self):
        """Run one cleanup pass for warning expiry."""
        self._cleanup_run_count += 1
        self._cleanup_last_started_at = datetime.now(timezone.utc)
        log(
            f"[AutoWarnDel] Tick #{self._cleanup_run_count} started. Guilds tracked: {len(self.warnings)}",
            "info",
        )

        year_ago = datetime.now(timezone.utc) - timedelta(days=365)
        removed_count = 0
        guilds_scanned = 0
        users_scanned = 0
        warns_scanned = 0

        for guild_id, members in list(self.warnings.items()):
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
                valid_warns = []

                for warn in warns:
                    try:
                        raw_time = warn["timestamp"].replace("Z", "+00:00")

                        # Fix non-padded months/days (e.g. 2024-1-9 → 2024-01-09)
                        if re.match(r"^\d{4}-\d{1,2}-\d{1,2}T", raw_time):
                            parts = raw_time.split("T")
                            date_parts = parts[0].split("-")
                            if len(date_parts) == 3:
                                year, month, day = date_parts
                                raw_time = f"{int(year):04d}-{int(month):02d}-{int(day):02d}T{parts[1]}"

                        warn_time = datetime.fromisoformat(raw_time)
                        if warn_time.tzinfo is None:
                            warn_time = warn_time.replace(tzinfo=timezone.utc)

                        if warn_time > year_ago:
                            valid_warns.append(warn)

                    except (KeyError, ValueError):
                        # If timestamp invalid or missing, keep it (safe fallback)
                        valid_warns.append(warn)

                if len(valid_warns) < len(warns):
                    diff = len(warns) - len(valid_warns)
                    removed_count += diff
                    self.warnings[guild_id][member_id] = valid_warns
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
            await self.save_json(WARN_DB, self.warnings)
            self._cleanup_last_finished_at = datetime.now(timezone.utc)
            log(
                f"[AutoWarnDel] Tick #{self._cleanup_run_count} complete. Removed={removed_count}, GuildsScanned={guilds_scanned}, UsersScanned={users_scanned}, WarnsScanned={warns_scanned}",
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
        wait_ready = getattr(self.bot, "wait_until_ready", None)
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


    def cog_unload(self):
        """Cancel the background task when the cog is unloaded."""
        log("[AutoWarnDel] Cog unloading. Cleanup loop cancelled.", "warn")
        self.auto_warn_cleanup.cancel()
    
    @Cog.listener()
    async def on_message(self, message: fluxer.Message):
        # Ignore DMs
        if not message.guild:
            return

        # Only care about bot messages
        if not message.author.bot:
            return

        # Ignore THIS bot (the helper bot itself)
        if message.author.id == self.bot.user.id:
            return

        # Safety: check perms before trying to delete
        if not message.channel.permissions_for(message.guild.me).manage_messages:
            return

        # Delete after 5 seconds
        try:
            await message.delete(delay=5)
        except fluxer.NotFound:
            pass
        except fluxer.Forbidden:
            pass

async def setup(bot: fluxer.Bot):
    await bot.add_cog(HelperCog(bot))

    