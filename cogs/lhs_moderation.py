"""
AI Moderation Cog (Experimental)

Provides AI-powered content moderation using the LHS (Language Harm Scanner) model.
This is an experimental feature that uses machine learning to detect harmful content.

Commands use "ai_mod" prefix for user-friendly access.
"""

import fluxer
import asyncio
from typing import Optional, Any

from utils.embed_builder import EmbedBuilder
from utils.datawrapper import DataWrapper
from utils.delete_after import delete_after
from utils.log import log
from utils.lhs_client import (
    get_lhs_client,
    LHSClient,
    GuildLHSSettings,
    CATEGORY_DISPLAY_NAMES,
    CATEGORY_DESCRIPTIONS,
    DEFAULT_LHS_SETTINGS,
    ALL_LHS_CATEGORIES,
)
from fluxer import Cog


class LHSModerationCog(Cog):
    """AI-powered moderation using LHS model (Experimental)"""
    
    def __init__(self, bot: fluxer.Bot):
        super().__init__(bot)
        self.bot = bot
        self.datawrapper = DataWrapper()
        self.lhs_client: LHSClient = get_lhs_client()
    
    def _extract_author_role_ids(self, author, member=None) -> set[str]:
        """Extract role IDs from author/member"""
        role_ids: set[str] = set()
        
        for role in getattr(author, "roles", []) or []:
            role_id = getattr(role, "id", role)
            if role_id is not None:
                role_ids.add(str(role_id))
        
        for role_id in getattr(author, "role_ids", []) or []:
            if role_id is not None:
                role_ids.add(str(role_id))
        
        if member is not None:
            for role in getattr(member, "roles", []) or []:
                role_id = getattr(role, "id", role)
                if role_id is not None:
                    role_ids.add(str(role_id))
            for role_id in getattr(member, "role_ids", []) or []:
                if role_id is not None:
                    role_ids.add(str(role_id))
        
        return role_ids
    
    def _is_exempt(
        self,
        message: fluxer.Message,
        settings: GuildLHSSettings,
    ) -> bool:
        """Check if message is exempt from AI moderation"""
        channel = getattr(message, "channel", None)
        channel_id = int(getattr(channel, "id", 0)) if channel else 0
        parent_channel_id = int(
            getattr(getattr(channel, "parent", None), "id", 0)
            or getattr(channel, "parent_id", 0)
        )
        
        # Check channel exemptions
        if channel_id and settings.is_exempt(channel_id, "channel"):
            return True
        if parent_channel_id and settings.is_exempt(parent_channel_id, "channel"):
            return True
        
        # Check user exemptions
        user_id = int(getattr(message.author, "id", 0))
        if user_id and settings.is_exempt(user_id, "user"):
            return True
        
        # Check role exemptions
        author_role_ids = self._extract_author_role_ids(
            message.author,
            getattr(message, "member", None),
        )
        for role_id_str in author_role_ids:
            try:
                role_id = int(role_id_str)
                if settings.is_exempt(role_id, "role"):
                    return True
            except ValueError:
                continue
        
        return False
    
    @staticmethod
    def _safe_inline(value: str, max_len: int = 120) -> str:
        """Safe string for inline display"""
        text = str(value or "").replace("`", "\\`").replace("\n", " ").strip()
        if len(text) > max_len:
            return text[: max_len - 3] + "..."
        return text
    
    @staticmethod
    def _truncate_content(content: str, max_len: int = 400) -> str:
        """Truncate content for display"""
        if not content:
            return ""
        if len(content) > max_len:
            return content[: max_len - 3] + "..."
        return content
    
    def _check_manage_guild_perm(self, member) -> bool:
        """Check if member has admin or manage guild permission"""
        permissions = getattr(member, "permissions", None)
        if not permissions:
            return False
        return (
            getattr(permissions, "administrator", False)
            or getattr(permissions, "manage_guild", False)
        )
    
    async def _resolve_automod_log_channel_id(self, guild_id: int) -> Optional[str]:
        """Resolve the AutoMod log channel ID"""
        config = await self.datawrapper.get_command_settings(guild_id) or {}
        
        for key in [
            "automod_log_channel",
            "automod_log_channel_id",
            "log_channel_id",
            "log_channel",
        ]:
            value = config.get(key)
            if value:
                return str(value).strip()
        
        return None
    
    async def _resolve_staff_ping_roles(self, guild_id: int) -> list[str]:
        """Resolve staff ping role IDs"""
        config = await self.datawrapper.get_command_settings(guild_id) or {}
        
        role_ids = []
        for key in [
            "staff_role_ids",
            "staff_roles",
            "staff_ping_role_ids",
            "automod_ping_role_ids",
        ]:
            value = config.get(key)
            if isinstance(value, list):
                role_ids.extend(str(item).strip() for item in value if str(item).strip())
            elif isinstance(value, str):
                role_ids.extend(part.strip() for part in value.split(",") if part.strip())
        
        seen = set()
        unique_roles = []
        for role_id in role_ids:
            if role_id not in seen and len(unique_roles) < 5:
                seen.add(role_id)
                unique_roles.append(role_id)
        
        return unique_roles
    
    async def send_lhs_log(
        self,
        guild: fluxer.Guild,
        embed: fluxer.Embed,
    ) -> bool:
        """Send AI moderation log to the configured channel"""
        guild_id = getattr(guild, "id", None)
        if guild_id is None:
            return False
        
        channel_id = await self._resolve_automod_log_channel_id(guild_id)
        staff_ping_role_ids = await self._resolve_staff_ping_roles(guild_id)
        
        if not channel_id:
            log(f"[AI Mod] Log skipped: no automod_log_channel configured for guild={guild_id}", "debug")
            return False
        
        try:
            channel = None
            
            get_channel = getattr(self.bot, "get_channel", None)
            if callable(get_channel):
                channel = get_channel(channel_id)
                if channel is None and channel_id.isdigit():
                    channel = get_channel(int(channel_id))
            
            if channel is None:
                channel = await self.bot.fetch_channel(channel_id)
            
            if channel:
                mention_content = " ".join([f"<@&{role_id}>" for role_id in staff_ping_role_ids])
                if mention_content:
                    await channel.send(content=mention_content, embed=embed)
                else:
                    await channel.send(embed=embed)
                log(f"[AI Mod] Log sent guild={guild_id} channel={channel_id}", "debug")
                return True
        
        except fluxer.NotFound:
            log(f"[AI Mod] Log failed: channel not found guild={guild_id} channel={channel_id}", "debug")
        except fluxer.Forbidden:
            log(f"[AI Mod] Log failed: forbidden guild={guild_id} channel={channel_id}", "debug")
        except Exception as exc:
            log(f"[AI Mod] Log failed: unexpected error guild={guild_id} channel={channel_id} error={exc}", "error")
        
        return False
    
    async def _take_action(
        self,
        message: fluxer.Message,
        settings: GuildLHSSettings,
        violations: list,
        guild: fluxer.Guild,
        channel: Any,
    ) -> str:
        """Take action on a violating message"""
        action = settings.get_action(channel.id if channel else None)
        severity = settings.get_severity(channel.id if channel else None)
        log_only = settings.is_log_only(channel.id if channel else None)
        
        is_low_severity = severity <= 1
        
        if log_only or is_low_severity:
            return "log-only"
        
        if action == "delete":
            try:
                await message.delete()
                
                if channel is not None:
                    warning_message = await channel.send(
                        embed=EmbedBuilder.error_embed(
                            "Message Removed",
                            f"{message.author.mention}, your message was removed by AI moderation."
                        )
                    )
                    asyncio.create_task(delete_after(warning_message, 5))
                
                return "deleted"
            except fluxer.Forbidden:
                return "delete-forbidden"
            except fluxer.NotFound:
                return "delete-not-found"
        
        elif action == "warn":
            return "warn-logged"
        
        elif action == "mute":
            return "mute-not-implemented"
        
        elif action == "kick":
            try:
                await guild.kick(message.author, reason="AI Moderation: Violation detected")
                return "kicked"
            except Exception:
                return "kick-failed"
        
        elif action == "ban":
            try:
                await guild.ban(message.author, reason="AI Moderation: Violation detected")
                return "banned"
            except Exception:
                return "ban-failed"
        
        return "unknown-action"
    
    @Cog.listener()
    async def on_message(self, message: fluxer.Message):
        """Process messages for AI moderation"""
        # Basic checks
        if message.author.bot:
            return
        
        if not getattr(message, "content", None):
            return
        
        if not message.guild:
            return
        
        guild_id = message.guild.id
        
        await self.datawrapper.ensure_guild(guild_id)
        
        settings = await self.datawrapper.get_lhs_settings(guild_id)
        
        if not settings.enabled:
            log(f"[AI Mod] Skipping guild={guild_id} - AI moderation not enabled", "debug")
            return
        
        if self._is_exempt(message, settings):
            log(f"[AI Mod] Message exempt guild={guild_id} user={message.author.id}", "debug")
            return
        
        channel_id = message.channel.id if message.channel else None
        
        result = await self.lhs_client.check_with_settings(
            message.content,
            settings,
            channel_id,
        )
        
        if not result:
            log(f"[AI Mod] Inference failed or no result guild={guild_id}", "debug")
            return
        
        if not result.is_harmful:
            log(f"[AI Mod] No violations detected guild={guild_id}", "debug")
            return
        
        violations = result.get_top_violations()
        violation_names = [v["display_name"] for v in violations]
        violation_details = "\n".join([
            f"• **{v['display_name']}** ({v['confidence']:.1%})"
            for v in violations
        ])
        
        log(
            f"[AI Mod] Violation detected guild={guild_id} user={message.author.id} "
            f"categories={result.detected_categories}",
            "info"
        )
        
        action_result = await self._take_action(
            message,
            settings,
            violations,
            message.guild,
            message.channel,
        )
        
        if message.channel and message.guild:
            truncated_content = self._truncate_content(message.content)
            
            embed = EmbedBuilder.create_embed(
                title="🤖 AI Moderation Violation (Experimental)",
                description=(
                    f"**User:** {message.author.mention} (`{message.author.id}`)\n"
                    f"**Channel:** {message.channel.mention} (`{message.channel.id}`)\n"
                    f"**Action:** `{action_result}`\n"
                    f"**Violations:**\n{violation_details}\n"
                    f"**Content:** {truncated_content}\n"
                    f"**Inference Time:** {result.inference_time_ms:.1f}ms\n"
                    f"**Time:** <t:{int(message.created_at.timestamp())}:F>"
                ),
                color=0xFF6B6B,
            )
            
            avatar = getattr(message.author, "display_avatar", None)
            avatar_url = getattr(avatar, "url", None)
            if avatar_url:
                embed.set_thumbnail(url=avatar_url)
            
            await self.send_lhs_log(message.guild, embed)
    
    # =======================================================================
    # AI Moderation Commands (Experimental)
    # =======================================================================
    
    @Cog.command(name="toggle_ai_mod")
    async def toggle_ai_mod(self, ctx: fluxer.Message):
        """
        Enable or disable AI moderation (Experimental)
        
        Requires Administrator or Manage Server permission.
        """
        member = getattr(ctx, "member", None) or ctx.author
        
        if not self._check_manage_guild_perm(member):
            await ctx.reply("❌ You need Administrator or Manage Server permission to use this command.")
            return
        
        guild = ctx.guild
        if not guild:
            await ctx.reply("❌ This command can only be used in a server.")
            return
        
        await self.datawrapper.ensure_guild(guild.id)
        settings = await self.datawrapper.get_lhs_settings(guild.id)
        
        new_state = not settings.enabled
        await self.datawrapper.set_lhs_enabled(guild.id, new_state)
        
        status = "enabled" if new_state else "disabled"
        emoji = "✅" if new_state else "🔴"
        
        embed = EmbedBuilder.create_embed(
            title=f"{emoji} AI Moderation {status.title()} (Experimental)",
            description=(
                f"AI moderation has been **{status}**.\n\n"
                f"⚠️ **Note:** This is an experimental feature. "
                f"It uses machine learning to detect harmful content and may produce false positives.\n\n"
                f"Use `fm!ai_mod_settings` to view and configure detection settings."
            ),
            color=0x00AA00 if new_state else 0xFF4444,
        )
        await ctx.reply(embed=embed)
    
    @Cog.command(name="ai_mod_settings")
    async def ai_mod_settings(self, ctx: fluxer.Message):
        """
        View current AI moderation settings (Experimental)
        
        Requires Administrator or Manage Server permission.
        """
        member = getattr(ctx, "member", None) or ctx.author
        
        if not self._check_manage_guild_perm(member):
            await ctx.reply("❌ You need Administrator or Manage Server permission to use this command.")
            return
        
        guild = ctx.guild
        if not guild:
            await ctx.reply("❌ This command can only be used in a server.")
            return
        
        await self.datawrapper.ensure_guild(guild.id)
        settings = await self.datawrapper.get_lhs_settings(guild.id)
        
        # Build categories info
        categories_text = []
        for cat in ALL_LHS_CATEGORIES[:6]:  # Show first 6
            cat_settings = settings.categories.get(cat, {})
            enabled = cat_settings.get("enabled", True)
            threshold = cat_settings.get("threshold", settings.global_threshold)
            display_name = CATEGORY_DISPLAY_NAMES.get(cat, cat)
            status = "🟢" if enabled else "🔴"
            categories_text.append(f"{status} {display_name}: {threshold:.0%}")
        
        # Exemptions
        exempt_roles = [f"<@&{r}>" for r in settings.exempt_roles[:3]]
        exempt_channels = [f"<#{c}>" for c in settings.exempt_channels[:3]]
        exempt_users = [f"<@{u}>" for u in settings.exempt_users[:3]]
        
        embed = EmbedBuilder.create_embed(
            title="🤖 AI Moderation Settings (Experimental)",
            description=(
                f"**Status:** {'✅ Enabled' if settings.enabled else '🔴 Disabled'}\n"
                f"**Global Threshold:** {settings.global_threshold:.0%}\n"
                f"**Action:** `{settings.action}`\n"
                f"**Severity:** `{settings.severity}`\n"
                f"**Log Only Mode:** {'Yes' if settings.log_only_mode else 'No'}\n\n"
                f"**Detection Categories:**\n" + "\n".join(categories_text) + "\n"
                f"*(and {len(ALL_LHS_CATEGORIES) - 6} more...)*\n\n"
                f"**Exempt Roles:** {', '.join(exempt_roles) if exempt_roles else 'None'}\n"
                f"**Exempt Channels:** {', '.join(exempt_channels) if exempt_channels else 'None'}\n"
                f"**Exempt Users:** {', '.join(exempt_users) if exempt_users else 'None'}"
            ),
            color=0x00BFFF if settings.enabled else 0x888888,
        )
        
        embed.set_footer(text="Use fm!ai_mod_help for command list | ⚠️ Experimental feature")
        await ctx.reply(embed=embed)
    
    @Cog.command(name="set_ai_mod_threshold")
    async def set_ai_mod_threshold(self, ctx: fluxer.Message, threshold: str = None):
        """
        Set the global AI moderation threshold (Experimental)
        
        Usage: fm!set_ai_mod_threshold <0.0-1.0>
        Higher values = less sensitive (fewer detections)
        Lower values = more sensitive (more detections)
        Default: 0.55 (55%)
        """
        member = getattr(ctx, "member", None) or ctx.author
        
        if not self._check_manage_guild_perm(member):
            await ctx.reply("❌ You need Administrator or Manage Server permission to use this command.")
            return
        
        if threshold is None:
            await ctx.reply(
                "Usage: `fm!set_ai_mod_threshold <0.0-1.0>`\n"
                "Example: `fm!set_ai_mod_threshold 0.6` (60% threshold)\n\n"
                "Higher values = less sensitive, fewer detections\n"
                "Lower values = more sensitive, more detections"
            )
            return
        
        try:
            thresh_val = float(threshold)
            if not 0.0 <= thresh_val <= 1.0:
                raise ValueError("Threshold must be between 0.0 and 1.0")
        except ValueError:
            await ctx.reply("❌ Threshold must be a number between 0.0 and 1.0 (e.g., 0.55)")
            return
        
        guild = ctx.guild
        if not guild:
            await ctx.reply("❌ This command can only be used in a server.")
            return
        
        await self.datawrapper.update_lhs_settings(guild.id, {"global_threshold": thresh_val})
        
        embed = EmbedBuilder.create_embed(
            title="🤖 AI Moderation Threshold Updated (Experimental)",
            description=(
                f"Global threshold set to **{thresh_val:.0%}**\n\n"
                f"This affects all categories unless overridden.\n"
                f"Use `fm!set_ai_mod_category` to set per-category thresholds."
            ),
            color=0x00AA00,
        )
        await ctx.reply(embed=embed)
    
    @Cog.command(name="set_ai_mod_category")
    async def set_ai_mod_category(self, ctx: fluxer.Message, category: str = None, 
                                   enabled: str = None, threshold: str = None):
        """
        Configure a specific AI moderation category (Experimental)
        
        Usage: 
          fm!set_ai_mod_category <category> <on/off> [threshold]
        
        Categories: hate_speech, harassment, toxicity, severe_toxicity, 
                   threat, insult, identity_attack, sexually_explicit,
                   dangerous_content, phish, spam
        
        Examples:
          fm!set_ai_mod_category toxicity off
          fm!set_ai_mod_category hate_speech on 0.7
        """
        member = getattr(ctx, "member", None) or ctx.author
        
        if not self._check_manage_guild_perm(member):
            await ctx.reply("❌ You need Administrator or Manage Server permission to use this command.")
            return
        
        if category is None or enabled is None:
            categories_list = "\n".join([
                f"• `{cat}` - {CATEGORY_DISPLAY_NAMES.get(cat, cat)}"
                for cat in ALL_LHS_CATEGORIES
            ])
            await ctx.reply(
                f"Usage: `fm!set_ai_mod_category <category> <on/off> [threshold]`\n\n"
                f"**Available Categories:**\n{categories_list}\n\n"
                f"Examples:\n"
                f"`fm!set_ai_mod_category toxicity off`\n"
                f"`fm!set_ai_mod_category hate_speech on 0.7`"
            )
            return
        
        category = category.lower()
        if category not in ALL_LHS_CATEGORIES:
            await ctx.reply(f"❌ Unknown category: `{category}`. Use `fm!set_ai_mod_category` to see available categories.")
            return
        
        enabled_val = enabled.lower() in ("on", "true", "yes", "1", "enable")
        
        update_data = {"enabled": enabled_val}
        
        if threshold is not None:
            try:
                thresh_val = float(threshold)
                if not 0.0 <= thresh_val <= 1.0:
                    raise ValueError
                update_data["threshold"] = thresh_val
            except ValueError:
                await ctx.reply("❌ Threshold must be a number between 0.0 and 1.0")
                return
        
        guild = ctx.guild
        if not guild:
            await ctx.reply("❌ This command can only be used in a server.")
            return
        
        await self.datawrapper.set_lhs_category(guild.id, category, 
                                                 enabled=enabled_val,
                                                 threshold=update_data.get("threshold"))
        
        display_name = CATEGORY_DISPLAY_NAMES.get(category, category)
        status = "enabled" if enabled_val else "disabled"
        
        desc = f"Category `{display_name}` has been **{status}**"
        if "threshold" in update_data:
            desc += f" with threshold **{update_data['threshold']:.0%}**"
        desc += "."
        
        embed = EmbedBuilder.create_embed(
            title="🤖 AI Moderation Category Updated (Experimental)",
            description=desc,
            color=0x00AA00 if enabled_val else 0xFFAA00,
        )
        await ctx.reply(embed=embed)
    
    @Cog.command(name="set_ai_mod_exempt_roles")
    async def set_ai_mod_exempt_roles(self, ctx: fluxer.Message, *, roles: str = None):
        """
        Set roles exempt from AI moderation (Experimental)
        
        Usage: fm!set_ai_mod_exempt_roles <@role1> [@role2] ...
        Use "none" to clear all exempt roles.
        """
        member = getattr(ctx, "member", None) or ctx.author
        
        if not self._check_manage_guild_perm(member):
            await ctx.reply("❌ You need Administrator or Manage Server permission to use this command.")
            return
        
        guild = ctx.guild
        if not guild:
            await ctx.reply("❌ This command can only be used in a server.")
            return
        
        if roles is None or roles.lower() == "none":
            # Clear exempt roles
            await self.datawrapper.set_lhs_exemptions(guild.id, roles=[])
            await ctx.reply("✅ AI moderation exempt roles cleared.")
            return
        
        # Parse role mentions/IDs
        import re
        role_ids = []
        for match in re.findall(r'<@&(\d+)>|(\d+)', roles):
            role_id = match[0] or match[1]
            if role_id:
                role_ids.append(int(role_id))
        
        if not role_ids:
            await ctx.reply("❌ No valid roles found. Use role mentions or IDs.")
            return
        
        await self.datawrapper.set_lhs_exemptions(guild.id, roles=role_ids)
        
        role_mentions = [f"<@&{r}>" for r in role_ids]
        embed = EmbedBuilder.create_embed(
            title="🤖 AI Moderation Exemptions Updated (Experimental)",
            description=f"Exempt roles: {', '.join(role_mentions)}",
            color=0x00AA00,
        )
        await ctx.reply(embed=embed)
    
    @Cog.command(name="set_ai_mod_exempt_channels")
    async def set_ai_mod_exempt_channels(self, ctx: fluxer.Message, *, channels: str = None):
        """
        Set channels exempt from AI moderation (Experimental)
        
        Usage: fm!set_ai_mod_exempt_channels <#channel1> [#channel2] ...
        Use "none" to clear all exempt channels.
        """
        member = getattr(ctx, "member", None) or ctx.author
        
        if not self._check_manage_guild_perm(member):
            await ctx.reply("❌ You need Administrator or Manage Server permission to use this command.")
            return
        
        guild = ctx.guild
        if not guild:
            await ctx.reply("❌ This command can only be used in a server.")
            return
        
        if channels is None or channels.lower() == "none":
            await self.datawrapper.set_lhs_exemptions(guild.id, channels=[])
            await ctx.reply("✅ AI moderation exempt channels cleared.")
            return
        
        import re
        channel_ids = []
        for match in re.findall(r'<#(\d+)>|(\d+)', channels):
            channel_id = match[0] or match[1]
            if channel_id:
                channel_ids.append(int(channel_id))
        
        if not channel_ids:
            await ctx.reply("❌ No valid channels found. Use channel mentions or IDs.")
            return
        
        await self.datawrapper.set_lhs_exemptions(guild.id, channels=channel_ids)
        
        channel_mentions = [f"<#{c}>" for c in channel_ids]
        embed = EmbedBuilder.create_embed(
            title="🤖 AI Moderation Exemptions Updated (Experimental)",
            description=f"Exempt channels: {', '.join(channel_mentions)}",
            color=0x00AA00,
        )
        await ctx.reply(embed=embed)
    
    @Cog.command(name="ai_mod_status")
    async def ai_mod_status(self, ctx: fluxer.Message):
        """
        Check AI moderation inference server status (Experimental)
        
        Shows server health, model status, and performance metrics.
        """
        member = getattr(ctx, "member", None) or ctx.author
        
        if not self._check_manage_guild_perm(member):
            await ctx.reply("❌ You need Administrator or Manage Server permission to use this command.")
            return
        
        async with ctx.channel.typing():
            health = await self.lhs_client.health_check()
        
        if health:
            embed = EmbedBuilder.create_embed(
                title="🤖 AI Moderation Server Status (Experimental)",
                description=(
                    f"**Status:** {health.get('status', 'unknown')}\n"
                    f"**Model Loaded:** {'✅ Yes' if health.get('model_loaded') else '❌ No'}\n"
                    f"**Queue Size:** {health.get('queue_size', 0)}\n"
                    f"**Total Requests:** {health.get('total_requests', 0)}\n"
                    f"**Device:** {health.get('device', 'unknown')}"
                ),
                color=0x00AA00,
            )
        else:
            embed = EmbedBuilder.error_embed(
                "🤖 AI Moderation Server Unavailable",
                "Could not connect to the AI moderation inference server. "
                "The feature may be temporarily unavailable or the server needs to be started."
            )
        
        await ctx.reply(embed=embed)
    
    @Cog.command(name="test_ai_mod")
    async def test_ai_mod(self, ctx: fluxer.Message, *, text: str = None):
        """
        Test AI moderation on text (Experimental)
        
        Usage: fm!test_ai_mod <text to analyze>
        Shows what the AI would detect in the given text.
        """
        if text is None:
            await ctx.reply("Usage: `fm!test_ai_mod <text to analyze>`")
            return
        
        member = getattr(ctx, "member", None) or ctx.author
        
        if not self._check_manage_guild_perm(member):
            await ctx.reply("❌ You need Administrator or Manage Server permission to use this command.")
            return
        
        async with ctx.channel.typing():
            result = await self.lhs_client.check_content(text)
        
        if not result:
            await ctx.reply("❌ Failed to analyze text. The AI moderation server may be unavailable.")
            return
        
        if result.is_harmful:
            violations = result.get_top_violations()
            violation_text = "\n".join([
                f"• **{v['display_name']}**: {v['confidence']:.1%}"
                for v in violations
            ])
            
            embed = EmbedBuilder.create_embed(
                title="🤖 AI Analysis: Harmful Content Detected (Experimental)",
                description=(
                    f"**Violations:**\n{violation_text}\n\n"
                    f"**Inference Time:** {result.inference_time_ms:.1f}ms"
                ),
                color=0xFF0000,
            )
        else:
            scores_text = "\n".join([
                f"• **{CATEGORY_DISPLAY_NAMES.get(cat, cat)}**: {pred['confidence']:.1%}"
                for cat, pred in sorted(
                    result.predictions.items(),
                    key=lambda x: x[1]['confidence'],
                    reverse=True
                )[:5]
            ])
            
            embed = EmbedBuilder.create_embed(
                title="🤖 AI Analysis: Clean (Experimental)",
                description=(
                    f"No harmful content detected.\n\n"
                    f"**Top Scores (below threshold):**\n{scores_text}\n\n"
                    f"**Inference Time:** {result.inference_time_ms:.1f}ms"
                ),
                color=0x00AA00,
            )
        
        embed.set_footer(text="⚠️ This is an experimental feature and may produce false positives/negatives.")
        await ctx.reply(embed=embed)
    
    @Cog.command(name="ai_mod_help")
    async def ai_mod_help(self, ctx: fluxer.Message):
        """
        Show AI moderation help (Experimental)
        
        Lists all available AI moderation commands.
        """
        prefix = getattr(getattr(self.bot, "command_prefix", None), "strip", lambda: "fm!")()
        if not isinstance(prefix, str) or not prefix:
            prefix = "fm!"
        
        embed = EmbedBuilder.create_embed(
            title="🤖 AI Moderation Help (Experimental)",
            description=(
                "⚠️ **This is an experimental feature.**\n"
                "AI moderation uses machine learning to detect harmful content. "
                "It may produce false positives or false negatives. "
                "Always review the moderation logs and adjust settings as needed."
            ),
            color=0x00BFFF,
        )
        
        embed.add_field(
            name="Enable/Disable",
            value=(
                f"`{prefix}toggle_ai_mod`\n"
                f"Enable or disable AI moderation for this server."
            ),
            inline=False,
        )
        
        embed.add_field(
            name="Configuration",
            value=(
                f"`{prefix}ai_mod_settings`\n"
                f"View current AI moderation settings.\n\n"
                f"`{prefix}set_ai_mod_threshold <0.0-1.0>`\n"
                f"Set the global detection threshold (default: 0.55).\n\n"
                f"`{prefix}set_ai_mod_category <category> <on/off> [threshold]`\n"
                f"Configure a specific detection category."
            ),
            inline=False,
        )
        
        embed.add_field(
            name="Exemptions",
            value=(
                f"`{prefix}set_ai_mod_exempt_roles <@role1> [@role2] ...`\n"
                f"Set roles that bypass AI moderation.\n\n"
                f"`{prefix}set_ai_mod_exempt_channels <#ch1> [#ch2] ...`\n"
                f"Set channels that bypass AI moderation."
            ),
            inline=False,
        )
        
        embed.add_field(
            name="Testing & Status",
            value=(
                f"`{prefix}ai_mod_status`\n"
                f"Check the AI inference server status.\n\n"
                f"`{prefix}test_ai_mod <text>`\n"
                f"Test how the AI would analyze specific text."
            ),
            inline=False,
        )
        
        embed.add_field(
            name="Detection Categories",
            value=(
                "`hate_speech` - Content attacking protected groups\n"
                "`harassment` - Content targeting individuals\n"
                "`toxicity` - General toxic behavior\n"
                "`severe_toxicity` - Extremely toxic content\n"
                "`threat` - Threats of violence or harm\n"
                "`insult` - Personal insults or attacks\n"
                "`identity_attack` - Attacks based on identity\n"
                "`sexually_explicit` - Sexual or NSFW content\n"
                "`dangerous_content` - Dangerous/illegal activities\n"
                "`phish` - Phishing attempts\n"
                "`spam` - Spam or repetitive content"
            ),
            inline=False,
        )
        
        embed.set_footer(text=f"Prefix: {prefix} | ⚠️ Experimental feature")
        await ctx.reply(embed=embed)


async def setup(bot: fluxer.Bot):
    await bot.add_cog(LHSModerationCog(bot))
