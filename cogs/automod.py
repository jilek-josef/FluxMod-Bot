import fluxer
import re
import asyncio
from typing import Any

from utils.embed_builder import EmbedBuilder
from utils.datawrapper import DataWrapper
from utils.delete_after import delete_after
from utils.log import log
from fluxer import Cog



class AutoModCog(Cog):
    def __init__(self, bot: fluxer.Bot):
        super().__init__(bot)
        self.bot = bot
        self.datawrapper = DataWrapper()

    @staticmethod
    def _compile_wildcard_pattern(pattern: str):
        try:
            escaped = re.escape(pattern).replace(r"\*", ".*")
            return re.compile(escaped, re.IGNORECASE)
        except re.error:
            return None

    @staticmethod
    def _normalize_pattern_list(raw_patterns):
        normalized = []
        for pattern in raw_patterns:
            if not isinstance(pattern, str):
                continue

            # Some preset entries are accidentally saved as "a, b" in one slot.
            for part in pattern.split(","):
                clean = part.strip().lower()
                if clean:
                    normalized.append(clean)

        return normalized

    @staticmethod
    def _extract_author_role_ids(author) -> set[str]:
        role_ids: set[str] = set()

        # Common shape: list of Role objects.
        for role in getattr(author, "roles", []) or []:
            role_id = getattr(role, "id", role)
            if role_id is not None:
                role_ids.add(str(role_id))

        # Some libraries expose raw IDs directly.
        for role_id in getattr(author, "role_ids", []) or []:
            if role_id is not None:
                role_ids.add(str(role_id))

        return role_ids

    def _is_exempt(
        self,
        message: fluxer.Message,
        exempt_roles: set[str],
        exempt_channels: set[str],
        exempt_users: set[str],
    ) -> bool:
        channel = getattr(message, "channel", None)
        channel_id = str(getattr(channel, "id", ""))
        parent_channel_id = str(
            getattr(getattr(channel, "parent", None), "id", "")
            or getattr(channel, "parent_id", "")
        )
        if (channel_id and channel_id in exempt_channels) or (
            parent_channel_id and parent_channel_id in exempt_channels
        ):
            return True

        user_id = str(getattr(message.author, "id", ""))
        if user_id and user_id in exempt_users:
            return True

        author_role_ids = self._extract_author_role_ids(message.author)
        return bool(exempt_roles.intersection(author_role_ids))

    def _is_allowed_content(self, content: str, compiled_allowed_patterns):
        for _, allowed_pattern in compiled_allowed_patterns:
            if allowed_pattern.search(content):
                return True
        return False

    @staticmethod
    def _safe_inline(value: str, max_len: int = 120) -> str:
        text = str(value or "").replace("`", "\\`").replace("\n", " ").strip()
        if len(text) > max_len:
            return text[: max_len - 3] + "..."
        return text

    @staticmethod
    def _highlight_match_in_message(content: str, matched_text: str, max_len: int = 400) -> str:
        source = str(content or "")
        if not source:
            return ""

        highlighted = source
        needle = str(matched_text or "").strip()
        if needle:
            try:
                highlighted = re.sub(
                    re.escape(needle),
                    lambda m: f"**{m.group(0)}**",
                    source,
                    count=1,
                    flags=re.IGNORECASE,
                )
            except re.error:
                highlighted = source

        if len(highlighted) > max_len:
            return highlighted[: max_len - 3] + "..."
        return highlighted

    def handle_prohibited_content(self, content: str, rule: dict):
        content_lower = (content or "").lower()
        rule_name = str(rule.get("name") or rule.get("rule_name") or "AutoMod Rule")

        if not content_lower:
            return False, None

        # Support both legacy schema (patterns) and current DB schema (keywords).
        patterns = self._normalize_pattern_list(
            rule.get("patterns", rule.get("keywords", []))
        )
        allowed_patterns = self._normalize_pattern_list(rule.get("allowed_patterns", []))
        rule_type = str(rule.get("rule_type", "")).lower()
        pattern_regex = rule.get("pattern")

        compiled_patterns = []
        for pattern in patterns:
            compiled = self._compile_wildcard_pattern(pattern)
            if compiled:
                compiled_patterns.append((pattern, compiled))

        compiled_allowed_patterns = []
        for pattern in allowed_patterns:
            compiled = self._compile_wildcard_pattern(pattern)
            if compiled:
                compiled_allowed_patterns.append((pattern, compiled))

        if self._is_allowed_content(content_lower, compiled_allowed_patterns):
            return False, None

        # Default to keyword matching when a rule includes keyword lists.
        if rule_type == "keyword" or (not rule_type and patterns):
            for pattern, regex in compiled_patterns:
                match = regex.search(content)
                if match:
                    return True, {
                        "rule_name": rule_name,
                        "match_type": "keyword",
                        "matched_pattern": pattern,
                        "matched_text": match.group(0),
                        "reason": "Matched AutoMod rule",
                    }

        if rule_type == "regex":
            for pattern in patterns:
                try:
                    match = re.search(pattern, content, re.IGNORECASE)
                    if match:
                        return True, {
                            "rule_name": rule_name,
                            "match_type": "regex",
                            "matched_pattern": pattern,
                            "matched_text": match.group(0),
                            "reason": "Matched AutoMod rule",
                        }
                except re.error:
                    continue

        # Support DB rules that store one regex in `pattern`.
        if isinstance(pattern_regex, str) and pattern_regex.strip():
            try:
                match = re.search(pattern_regex, content, re.IGNORECASE)
                if match:
                    return True, {
                        "rule_name": rule_name,
                        "match_type": "regex",
                        "matched_pattern": pattern_regex,
                        "matched_text": match.group(0),
                        "reason": "Matched AutoMod rule",
                    }
            except re.error:
                pass

        return False, None

    @staticmethod
    def _resolve_channel_id_from_payload(payload: Any) -> str | None:
        """Recursively resolve AutoMod log channel ID from inconsistent DB payloads."""
        candidate_keys = (
            "automod_log_channel",
            "automod_log_channel_id",
            "log_channel_id",
            "log_channel",
            "logChannelId",
        )

        if not isinstance(payload, dict):
            return None

        # Direct key lookup first.
        for key in candidate_keys:
            value = payload.get(key)
            if value is None:
                continue
            normalized = str(value).strip()
            if normalized:
                return normalized

        # Then recurse into nested objects.
        for value in payload.values():
            if isinstance(value, dict):
                nested = AutoModCog._resolve_channel_id_from_payload(value)
                if nested:
                    return nested

        return None

    async def _resolve_automod_log_channel_id(self, guild_id: int) -> str | None:
        # Primary path: command_settings from DataWrapper.get_guild_config.
        config = await self.datawrapper.get_guild_config(guild_id) or {}
        channel_id = self._resolve_channel_id_from_payload(config)
        log(f"[AutoMod] Log config lookup guild={guild_id} config_channel={channel_id}", "debug")

        # Fallback path: full guild payloads with nested command_settings/automod_settings.
        if not channel_id:
            guild_data = await self.datawrapper.get_guild_data(guild_id) or {}
            channel_id = self._resolve_channel_id_from_payload(guild_data)
        log(f"[AutoMod] Log fallback lookup guild={guild_id} resolved_channel={channel_id}", "debug")

        if not channel_id:
            return None
        return channel_id
    
    async def send_automod_log(self, guild: fluxer.Guild, embed: fluxer.Embed):
        """Send AutoMod logs to the configured guild channel."""
        guild_id = getattr(guild, "id", None)
        if guild_id is None:
            log("[AutoMod] Log skipped: missing guild id", "debug")
            return False

        channel_id = await self._resolve_automod_log_channel_id(guild_id)

        if not channel_id:
            log(f"[AutoMod] Log skipped: no automod_log_channel configured for guild={guild_id}", "debug")
            return False

        try:
            channel: Any = None

            # Try cache first if available on this library version.
            get_channel = getattr(self.bot, "get_channel", None)
            if callable(get_channel):
                channel = get_channel(channel_id)
                if channel is None and channel_id.isdigit():
                    channel = get_channel(int(channel_id))
            log(
                f"[AutoMod] Cache lookup guild={guild_id} channel={channel_id} hit={'yes' if channel else 'no'}",
                "debug",
            )

            if channel is None:
                channel = await self.bot.fetch_channel(channel_id)
                log(f"[AutoMod] Fetch lookup guild={guild_id} channel={channel_id} success={'yes' if channel else 'no'}", "debug")

            if channel:
                await channel.send(embed=embed)
                log(f"[AutoMod] Log sent guild={guild_id} channel={channel_id}", "debug")
                return True
        except fluxer.NotFound:
            log(f"[AutoMod] Log failed: channel not found guild={guild_id} channel={channel_id}", "debug")
            pass
        except fluxer.Forbidden:
            log(f"[AutoMod] Log failed: forbidden guild={guild_id} channel={channel_id}", "debug")
            pass
        except Exception as exc:
            log(f"[AutoMod] Log failed: unexpected error guild={guild_id} channel={channel_id} error={exc}", "error")
            pass

        return False

    @Cog.command(name="test")
    async def test_automod_log(self, ctx: fluxer.Message):
        """Send a test message to the configured AutoMod log channel."""
        guild = getattr(ctx, "guild", None)
        guild_id = getattr(guild, "id", None)
        if guild_id is None or guild is None:
            await ctx.reply("This command can only be used in a server.")
            return

        channel_id = await self._resolve_automod_log_channel_id(guild_id)
        if not channel_id:
            await ctx.reply("AutoMod log channel is not configured. Use `fm!set_automod_logs #channel` first.")
            return

        embed = EmbedBuilder.create_embed(
            title="AutoMod Log Test",
            description=(
                f"Test triggered by {ctx.author.mention} (`{ctx.author.id}`)\n"
                f"Guild: `{guild_id}`\n"
                f"Configured Channel: <#{channel_id}> (`{channel_id}`)"
            ),
            color=0x00AAFF,
        )

        sent = await self.send_automod_log(guild, embed)
        if sent:
            await ctx.reply(f"Test sent to <#{channel_id}>.")
        else:
            await ctx.reply(
                f"Test failed for <#{channel_id}>. Turn on `DEBUG=true` and check `[AutoMod]` logs for details."
            )

    
                                                                                 

    @Cog.listener()
    async def on_message(self, message: fluxer.Message):
        if message.author.bot:
            return

        if not getattr(message, "content", None):
            return

        if not message.guild:
            return

        guild_id = message.guild.id
        await self.datawrapper.ensure_guild(guild_id)
        rules = await self.datawrapper.get_enabled_automod_rules(guild_id)
        log(f"[AutoMod] Message check guild={guild_id} enabled_rules={len(rules)}", "debug")

        if not rules:
            return

        exempt_roles = {
            str(role_id)
            for rule in rules
            for role_id in rule.get("exempt_roles", [])
        }
        exempt_channels = {
            str(channel_id)
            for rule in rules
            for channel_id in rule.get("exempt_channels", [])
        }
        exempt_users = {
            str(user_id)
            for rule in rules
            for user_id in rule.get("exempt_users", [])
        }

        if self._is_exempt(message, exempt_roles, exempt_channels, exempt_users):
            log(
                f"[AutoMod] Message exempt guild={guild_id} user={getattr(message.author, 'id', 'unknown')} channel={getattr(getattr(message, 'channel', None), 'id', 'unknown')}",
                "debug",
            )
            return
        
        for rule in rules:
            violated, match_info = self.handle_prohibited_content(message.content, rule)
            if not violated:
                continue

            match_info = match_info or {}
            reason = str(match_info.get("reason") or "Matched AutoMod rule")
            matched_rule_name = self._safe_inline(match_info.get("rule_name") or "AutoMod Rule")
            match_type = self._safe_inline(match_info.get("match_type") or "unknown")
            matched_pattern = self._safe_inline(match_info.get("matched_pattern") or "", max_len=220)
            matched_text = self._safe_inline(match_info.get("matched_text") or "")
            highlighted_content = self._highlight_match_in_message(message.content, matched_text)

            channel = message.channel
            guild = message.guild
            delete_status = "deleted"

            try:
                await message.delete()
                log(
                    f"[AutoMod] Deleted message guild={guild_id} user={getattr(message.author, 'id', 'unknown')} reason={reason}",
                    "debug",
                )
                if channel is not None:
                    warning_message = await channel.send(
                        embed=EmbedBuilder.error_embed(
                            "Message Deleted",
                            f"{message.author.mention}, your message contained prohibited content and was removed."
                        )
                    )
                    asyncio.create_task(delete_after(warning_message, 5))
            except fluxer.Forbidden:
                delete_status = "delete-forbidden"
                log(f"[AutoMod] Delete failed: forbidden guild={guild_id}", "debug")
            except fluxer.NotFound:
                delete_status = "delete-not-found"
                log(f"[AutoMod] Delete failed: message not found guild={guild_id}", "debug")

            # Always attempt to write a mod log even when deletion fails.
            if channel is not None and guild is not None:
                embed = EmbedBuilder.create_embed(
                    title="AutoMod Violation",
                    description=(
                        f"**User:** {message.author.mention} (`{message.author.id}`)\n"
                        f"**Channel:** {channel.mention} (`{channel.id}`)\n"
                        f"**Rule:** `{matched_rule_name}`\n"
                        f"**Match Type:** `{match_type}`\n"
                        f"**Matched Pattern:** `{matched_pattern or 'N/A'}`\n"
                        f"**Matched Text:** `{matched_text or 'N/A'}`\n"
                        f"**Reason:** {reason}\n"
                        f"**Action:** {delete_status}\n"
                        f"**Content:** {highlighted_content or message.content}\n"
                        f"**Time:** <t:{int(message.created_at.timestamp())}:F>"
                    ),
                    color=0xFF0000,
                )
                avatar = getattr(message.author, "display_avatar", None)
                avatar_url = getattr(avatar, "url", None)
                if avatar_url:
                    embed.set_thumbnail(url=avatar_url)
                await self.send_automod_log(guild, embed)

            return

async def setup(bot: fluxer.Bot):
    await bot.add_cog(AutoModCog(bot))