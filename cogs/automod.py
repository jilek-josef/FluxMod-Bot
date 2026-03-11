import fluxer
import re

from utils.embed_builder import EmbedBuilder
from utils.datawrapper import DataWrapper
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

    def handle_prohibited_content(self, content: str, rule: dict):
        content_lower = (content or "").lower()

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
                if regex.search(content_lower):
                    return True, f"keyword: `{pattern}`"

        if rule_type == "regex":
            for pattern in patterns:
                try:
                    if re.search(pattern, content, re.IGNORECASE):
                        return True, f"regex: `{pattern}`"
                except re.error:
                    continue

        # Support DB rules that store one regex in `pattern`.
        if isinstance(pattern_regex, str) and pattern_regex.strip():
            try:
                if re.search(pattern_regex, content, re.IGNORECASE):
                    return True, f"pattern: `{pattern_regex}`"
            except re.error:
                pass

        return False, None
    
    async def send_automod_log(self, guild: fluxer.Guild, embed: fluxer.Embed):
        """Send AutoMod logs to the configured guild channel."""
        guild_id = getattr(guild, "id", None)
        if guild_id is None:
            return

        config = await self.datawrapper.get_guild_config(guild_id) or {}
        channel_id = config.get("automod_log_channel")
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
            return
        
        for rule in rules:
            violated, reason = self.handle_prohibited_content(message.content, rule)
            if not violated:
                continue

            try:
                await message.delete()
                channel = message.channel
                if channel is not None:
                    await channel.send(
                        embed=EmbedBuilder.error_embed(
                            "Message Deleted",
                            f"{message.author.mention}, your message contained prohibited content and was removed ({reason})."
                        ),
                        delete_after=5,
                    )
                    # Optionally, log the violation to a mod log channel here.
                    guild = message.guild
                    embed = EmbedBuilder.create_embed(
                        title="AutoMod Violation",
                        description=(
                            f"**User:** {message.author.mention} (`{message.author.id}`)\n"
                            f"**Channel:** {channel.mention} (`{channel.id}`)\n"
                            f"**Reason:** {reason}\n"
                            f"**Content:** {message.content}\n"
                            f"**Time:** <t:{int(message.created_at.timestamp())}:F>"
                        ),
                        color=0xFF0000,
                    )
                    avatar = getattr(message.author, "display_avatar", None)
                    avatar_url = getattr(avatar, "url", None)
                    if avatar_url:
                        embed.set_thumbnail(url=avatar_url)
                    await self.send_automod_log(guild, embed)
            except fluxer.Forbidden:
                pass
            except fluxer.NotFound:
                pass

            return

async def setup(bot: fluxer.Bot):
    await bot.add_cog(AutoModCog(bot))