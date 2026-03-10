import fluxer
import re
from fluxer import Cog
from typing import Any

from utils.resolvers import resolve_channel_id, resolve_user_id
from utils.datawrapper import DataWrapper
from utils.delete_after import delete_after


class ConfigsCog(Cog):
    def __init__(self, bot: fluxer.Bot):
        super().__init__(bot)
        self.bot = bot
        self.datawrapper = DataWrapper()

    def _permission_value(self, permission: Any) -> int:
        raw_value = getattr(permission, "value", permission)
        try:
            return int(raw_value)
        except Exception:
            return 0

    def _build_embed(self, title: str, description: str, color: int = 0x5865F2):
        embed = fluxer.Embed(title=title, description=description, color=color)
        embed.set_footer(text="FluxMod AutoMod Config")
        return embed

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

    def _resolve_channel_id(self, channel_str: str) -> str | None:
        resolved = resolve_channel_id(channel_str)
        return str(resolved) if resolved else None
    

    def _resolve_user_id(self, user_str: str) -> str | None:
        resolved = resolve_user_id(user_str)
        return str(resolved) if resolved else None

    def _resolve_role_id(self, role_str: str) -> str | None:
        value = str(role_str).strip()
        if value.startswith("<@&") and value.endswith(">"):
            value = value[3:-1]
        if value.isdigit():
            return value
        return None
    
    def _normalize_pattern_list(self, raw_patterns):
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
    
    def _compile_wildcard_pattern(self, pattern: str):
        try:
            escaped = re.escape(pattern).replace(r"\*", ".*")
            return re.compile(escaped, re.IGNORECASE)
        except re.error:
            return None

    def _default_automod_rule(self) -> dict:
        return {
            "name": "AutoMod Rule",
            "action": "warn",
            "pattern": "",
            "keywords": [],
            "allowed_patterns": [],
            "threshold": 1,
            "enabled": True,
            "exempt_roles": [],
            "exempt_channels": [],
            "exempt_users": [],
        }

    async def _get_primary_rule(self, guild_id: int) -> dict:
        rules = await self.datawrapper.get_automod_rules(guild_id)
        if rules:
            return dict(rules[0])
        return self._default_automod_rule()

    async def _save_primary_rule(self, guild_id: int, rule: dict):
        rule_name = str(rule.get("name") or rule.get("rule_name") or "AutoMod Rule")
        await self.datawrapper.set_automod_rule(guild_id, rule_name, rule)
        
    @Cog.command(name="set_automod_logs")
    async def set_automod_logs(self, ctx: fluxer.Message, channel: str):
        """Set the channel for AutoMod logs."""
        if not await self._ensure_permission_or_reply(ctx, fluxer.Permissions.MANAGE_GUILD, "MANAGE_GUILD"):
            return

        channel_id = self._resolve_channel_id(channel)
        if not channel_id:
            await ctx.reply("Could not find a valid channel from your input. Please provide a channel mention or ID.")
            return

        guild_id = getattr(ctx.guild, "id", None)
        if not guild_id:
            await ctx.reply("This command can only be used in a server.")
            return

        config = await self.datawrapper.get_guild_config(guild_id) or {}
        config["automod_log_channel"] = channel_id
        await self.datawrapper.set_guild_config(guild_id, config)

        await ctx.reply(f"AutoMod log channel has been set to <#{channel_id}>.")

    @Cog.command(name="set_exempt_channels")
    async def set_exempt_channels(self, ctx: fluxer.Message, *, channels: str):
        """Set channels that are exempt from AutoMod rules."""
        if not await self._ensure_permission_or_reply(ctx, fluxer.Permissions.MANAGE_GUILD, "MANAGE_GUILD"):
            return

        channel_ids = set()
        for part in channels.split(","):
            channel_id = self._resolve_channel_id(part.strip())
            if channel_id:
                channel_ids.add(channel_id)

        guild_id = getattr(ctx.guild, "id", None)
        if not guild_id:
            await ctx.reply("This command can only be used in a server.")
            return

        rule = await self._get_primary_rule(guild_id)
        rule["exempt_channels"] = sorted(channel_ids)
        await self._save_primary_rule(guild_id, rule)

        await ctx.reply(f"Exempt channels have been updated. Current exempt channels: {', '.join(f'<#{cid}>' for cid in channel_ids)}")

    @Cog.command(name="set_exempt_roles")
    async def set_exempt_roles(self, ctx: fluxer.Message, *, roles: str):
        """Set roles that are exempt from AutoMod rules."""
        if not await self._ensure_permission_or_reply(ctx, fluxer.Permissions.MANAGE_GUILD, "MANAGE_GUILD"):
            return

        role_ids = set()
        for part in roles.split(","):
            role_id = self._resolve_role_id(part.strip())
            if role_id:
                role_ids.add(role_id)

        guild_id = getattr(ctx.guild, "id", None)
        if not guild_id:
            await ctx.reply("This command can only be used in a server.")
            return

        rule = await self._get_primary_rule(guild_id)
        rule["exempt_roles"] = sorted(role_ids)
        await self._save_primary_rule(guild_id, rule)

        await ctx.reply(f"Exempt roles have been updated. Current exempt roles: {', '.join(f'<@&{rid}>' for rid in role_ids)}")

    @Cog.command(name="set_exempt_users")
    async def set_exempt_users(self, ctx: fluxer.Message, *, users: str):
        """Set users that are exempt from AutoMod rules."""
        if not await self._ensure_permission_or_reply(ctx, fluxer.Permissions.MANAGE_GUILD, "MANAGE_GUILD"):
            return

        user_ids = set()
        for part in users.split(","):
            user_id = self._resolve_user_id(part.strip())
            if user_id:
                user_ids.add(user_id)

        guild_id = getattr(ctx.guild, "id", None)
        if not guild_id:
            await ctx.reply("This command can only be used in a server.")
            return

        rule = await self._get_primary_rule(guild_id)
        rule["exempt_users"] = sorted(user_ids)
        await self._save_primary_rule(guild_id, rule)

        await ctx.reply(f"Exempt users have been updated. Current exempt users: {', '.join(f'<@{uid}>' for uid in user_ids)}")

    @Cog.command(name="set_keywords")
    async def set_keywords(self, ctx: fluxer.Message, *, keywords: str):
        """Set keywords that trigger AutoMod actions."""
        if not await self._ensure_permission_or_reply(ctx, fluxer.Permissions.MANAGE_GUILD, "MANAGE_GUILD"):
            return
        keyword_list = self._normalize_pattern_list(keywords.split(","))
        guild_id = getattr(ctx.guild, "id", None)
        if not guild_id:
            await ctx.reply("This command can only be used in a server.")
            return

        rule = await self._get_primary_rule(guild_id)
        rule["keywords"] = keyword_list
        await self._save_primary_rule(guild_id, rule)

        await ctx.reply(f"AutoMod keywords have been updated. Current keywords: {', '.join(keyword_list)}")
    
    @Cog.command(name="set_allowed_keywords")
    async def set_allowed_keywords(self, ctx: fluxer.Message, *, keywords: str):
        """Set keywords that are allowed and do not trigger AutoMod actions."""
        if not await self._ensure_permission_or_reply(ctx, fluxer.Permissions.MANAGE_GUILD, "MANAGE_GUILD"):
            return
        allowed_keyword_list = self._normalize_pattern_list(keywords.split(","))
        guild_id = getattr(ctx.guild, "id", None)
        if not guild_id:
            await ctx.reply("This command can only be used in a server.")
            return

        rule = await self._get_primary_rule(guild_id)
        rule["allowed_patterns"] = allowed_keyword_list
        await self._save_primary_rule(guild_id, rule)

        await ctx.reply(f"Allowed keywords have been updated. Current allowed keywords: {', '.join(allowed_keyword_list)}")

    @Cog.command(name="set_regex_patterns")
    async def set_regex_patterns(self, ctx: fluxer.Message, *, patterns: str):
        """Set regex patterns that trigger AutoMod actions."""
        if not await self._ensure_permission_or_reply(ctx, fluxer.Permissions.MANAGE_GUILD, "MANAGE_GUILD"):
            return

        pattern_list = self._normalize_pattern_list(patterns.split(","))
        guild_id = getattr(ctx.guild, "id", None)
        if not guild_id:
            await ctx.reply("This command can only be used in a server.")
            return

        combined_pattern = "|".join(f"(?:{pattern})" for pattern in pattern_list)
        rule = await self._get_primary_rule(guild_id)
        rule["pattern"] = combined_pattern
        await self._save_primary_rule(guild_id, rule)

        await ctx.reply(f"AutoMod regex patterns have been updated. Current patterns: {', '.join(pattern_list)}")

    @Cog.command(name="toggle_automod")
    async def toggle_automod(self, ctx: fluxer.Message):
        """Toggle AutoMod on or off."""
        if not await self._ensure_permission_or_reply(ctx, fluxer.Permissions.MANAGE_GUILD, "MANAGE_GUILD"):
            return
        guild_id = getattr(ctx.guild, "id", None)
        if not guild_id:
            await ctx.reply("This command can only be used in a server.")
            return

        rule = await self._get_primary_rule(guild_id)
        current_status = bool(rule.get("enabled", True))
        rule["enabled"] = not current_status
        await self._save_primary_rule(guild_id, rule)

        status_text = "enabled" if rule["enabled"] else "disabled"
        await ctx.reply(f"AutoMod has been {status_text}.")

    @Cog.command(name="view_automod_rules")
    async def view_automod_rules(self, ctx: fluxer.Message):
        if not await self._ensure_permission_or_reply(ctx, fluxer.Permissions.MANAGE_GUILD, "MANAGE_GUILD"):
            return

        """View current AutoMod rules and settings."""
        guild_id = getattr(ctx.guild, "id", None)
        if not guild_id:
            await ctx.reply("This command can only be used in a server.")
            return

        config = await self.datawrapper.get_guild_config(guild_id) or {}
        rule = await self._get_primary_rule(guild_id)

        log_channel_id = config.get("automod_log_channel")
        exempt_channels = rule.get("exempt_channels", [])
        exempt_roles = rule.get("exempt_roles", [])
        exempt_users = rule.get("exempt_users", [])
        keywords = rule.get("keywords", [])
        allowed_keywords = rule.get("allowed_patterns", [])
        regex_pattern = str(rule.get("pattern", "")).strip()
        enabled = bool(rule.get("enabled", False))

        embed = fluxer.Embed(title="AutoMod Configuration", color=0x00FF00)
        embed.add_field(name="Status", value="Enabled" if enabled else "Disabled", inline=False)
        embed.add_field(name="Log Channel", value=f"<#{log_channel_id}>" if log_channel_id else "Not set", inline=False)
        embed.add_field(name="Exempt Channels", value=", ".join(f"<#{cid}>" for cid in exempt_channels) if exempt_channels else "None", inline=False)
        embed.add_field(name="Exempt Roles", value=", ".join(f"<@&{rid}>" for rid in exempt_roles) if exempt_roles else "None", inline=False)
        embed.add_field(name="Exempt Users", value=", ".join(f"<@{uid}>" for uid in exempt_users) if exempt_users else "None", inline=False)
        embed.add_field(name="Keywords", value=", ".join(keywords) if keywords else "None", inline=False)
        embed.add_field(name="Allowed Keywords", value=", ".join(allowed_keywords) if allowed_keywords else "None", inline=False)
        embed.add_field(name="Regex Pattern", value=regex_pattern if regex_pattern else "None", inline=False)

        await ctx.reply(embed=embed)

async def setup(bot: fluxer.Bot):
    await bot.add_cog(ConfigsCog(bot))