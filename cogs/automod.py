import fluxer
import re

from utils.json_utils import load_json_sync
from utils.embed_builder import EmbedBuilder
from fluxer import Cog



class AutoModCog(Cog):
    def __init__(self, bot: fluxer.Bot):
        super().__init__(bot)

        presets = load_json_sync("data/automod_presets.json")
        self.rule_config = presets.get("Medium Security (Recommended)", {})

        self.keyword_patterns = self._normalize_pattern_list(self.rule_config.get("keyword_filter", []))
        self.allowed_patterns = self._normalize_pattern_list(self.rule_config.get("allowed_keywords", []))
        self.regex_patterns = [
            p for p in self.rule_config.get("regex_patterns", []) if isinstance(p, str) and p
        ]

        self.exempt_roles = {str(rid) for rid in self.rule_config.get("exempt_roles", [])}
        self.exempt_channels = {str(cid) for cid in self.rule_config.get("exempt_channels", [])}

        self._compiled_keyword_patterns = []
        for pattern in self.keyword_patterns:
            compiled = self._compile_wildcard_pattern(pattern)
            if compiled:
                self._compiled_keyword_patterns.append((pattern, compiled))

        self._compiled_allowed_patterns = []
        for pattern in self.allowed_patterns:
            compiled = self._compile_wildcard_pattern(pattern)
            if compiled:
                self._compiled_allowed_patterns.append((pattern, compiled))

        self._compiled_regex_patterns = []
        for pattern in self.regex_patterns:
            try:
                self._compiled_regex_patterns.append((pattern, re.compile(pattern, re.IGNORECASE)))
            except re.error:
                # Ignore invalid regex so one bad pattern cannot disable AutoMod.
                continue

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

    def _is_exempt(self, message: fluxer.Message) -> bool:
        channel_id = str(getattr(message.channel, "id", ""))
        if channel_id and channel_id in self.exempt_channels:
            return True

        author_roles = getattr(message.author, "roles", []) or []
        author_role_ids = {str(getattr(role, "id", "")) for role in author_roles}
        return bool(self.exempt_roles.intersection(author_role_ids))

    def _is_allowed_content(self, content: str) -> bool:
        for _, allowed_pattern in self._compiled_allowed_patterns:
            if allowed_pattern.search(content):
                return True
        return False

    def handle_prohibited_content(self, content: str):
        content_lower = (content or "").lower()

        if not content_lower:
            return False, None

        if self._is_allowed_content(content_lower):
            return False, None

        for pattern, regex in self._compiled_keyword_patterns:
            if regex.search(content_lower):
                return True, f"keyword: `{pattern}`"

        for pattern, regex in self._compiled_regex_patterns:
            if regex.search(content):
                return True, f"regex: `{pattern}`"

        return False, None

    
                                                                                 

    @Cog.listener()
    async def on_message(self, message: fluxer.Message):
        if message.author.bot:
            return

        if self._is_exempt(message):
            return

        if not getattr(message, "content", None):
            return
        
        violated, reason = self.handle_prohibited_content(message.content)
        if violated:
            try:
                await message.delete()
                channel = message.channel
                if channel is not None:
                    await channel.send(
                        embed=EmbedBuilder.error_embed(
                            "Message Deleted",
                            f"{message.author.mention}, your message contained prohibited content and was removed ({reason})."
                        )
                    )
            except fluxer.Forbidden:
                pass
            except fluxer.NotFound:
                pass

async def setup(bot: fluxer.Bot):
    await bot.add_cog(AutoModCog(bot))