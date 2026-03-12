"""
LHS AI Moderation Cog

Provides AI-powered content moderation using the LHS (Language Harm Scanner) model.
Integrates with the existing AutoMod system for consistent behavior.
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
    DEFAULT_LHS_SETTINGS,
)
from fluxer import Cog


class LHSModerationCog(Cog):
    """AI-powered moderation using LHS model"""
    
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
        """Check if message is exempt from LHS moderation"""
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
    
    async def _resolve_automod_log_channel_id(self, guild_id: int) -> Optional[str]:
        """Resolve the AutoMod log channel ID"""
        # Try to get from command_settings
        config = await self.datawrapper.get_command_settings(guild_id) or {}
        
        # Check various possible keys
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
        
        # Remove duplicates and limit
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
        """Send LHS moderation log to the configured channel"""
        guild_id = getattr(guild, "id", None)
        if guild_id is None:
            return False
        
        channel_id = await self._resolve_automod_log_channel_id(guild_id)
        staff_ping_role_ids = await self._resolve_staff_ping_roles(guild_id)
        
        if not channel_id:
            log(f"[LHS] Log skipped: no automod_log_channel configured for guild={guild_id}", "debug")
            return False
        
        try:
            channel = None
            
            # Try cache first
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
                log(f"[LHS] Log sent guild={guild_id} channel={channel_id}", "debug")
                return True
        
        except fluxer.NotFound:
            log(f"[LHS] Log failed: channel not found guild={guild_id} channel={channel_id}", "debug")
        except fluxer.Forbidden:
            log(f"[LHS] Log failed: forbidden guild={guild_id} channel={channel_id}", "debug")
        except Exception as exc:
            log(f"[LHS] Log failed: unexpected error guild={guild_id} channel={channel_id} error={exc}", "error")
        
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
                
                # Send warning
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
            # Just log for now - warn system integration could be added
            return "warn-logged"
        
        elif action == "mute":
            # Mute action would require timeout/mute functionality
            return "mute-not-implemented"
        
        elif action == "kick":
            try:
                await guild.kick(message.author, reason="LHS AI Moderation: Violation detected")
                return "kicked"
            except Exception:
                return "kick-failed"
        
        elif action == "ban":
            try:
                await guild.ban(message.author, reason="LHS AI Moderation: Violation detected")
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
        
        # Ensure guild exists in DB
        await self.datawrapper.ensure_guild(guild_id)
        
        # Get LHS settings
        settings = await self.datawrapper.get_lhs_settings(guild_id)
        
        if not settings.enabled:
            log(f"[LHS] Skipping guild={guild_id} - LHS not enabled", "debug")
            return
        
        # Check exemptions
        if self._is_exempt(message, settings):
            log(f"[LHS] Message exempt guild={guild_id} user={message.author.id}", "debug")
            return
        
        channel_id = message.channel.id if message.channel else None
        
        # Check content with LHS
        result = await self.lhs_client.check_with_settings(
            message.content,
            settings,
            channel_id,
        )
        
        if not result:
            log(f"[LHS] Inference failed or no result guild={guild_id}", "debug")
            return
        
        if not result.is_harmful:
            log(f"[LHS] No violations detected guild={guild_id}", "debug")
            return
        
        # Get violation details
        violations = result.get_top_violations()
        violation_names = [v["display_name"] for v in violations]
        violation_details = "\n".join([
            f"• **{v['display_name']}** ({v['confidence']:.1%})"
            for v in violations
        ])
        
        log(
            f"[LHS] Violation detected guild={guild_id} user={message.author.id} "
            f"categories={result.detected_categories}",
            "info"
        )
        
        # Take action
        action_result = await self._take_action(
            message,
            settings,
            violations,
            message.guild,
            message.channel,
        )
        
        # Build and send log
        if message.channel and message.guild:
            truncated_content = self._truncate_content(message.content)
            
            embed = EmbedBuilder.create_embed(
                title="AI Moderation Violation",
                description=(
                    f"**User:** {message.author.mention} (`{message.author.id}`)\n"
                    f"**Channel:** {message.channel.mention} (`{message.channel.id}`)\n"
                    f"**Action:** `{action_result}`\n"
                    f"**Violations:**\n{violation_details}\n"
                    f"**Content:** {truncated_content}\n"
                    f"**Inference Time:** {result.inference_time_ms:.1f}ms\n"
                    f"**Time:** <t:{int(message.created_at.timestamp())}:F>"
                ),
                color=0xFF6B6B,  # Light red for AI moderation
            )
            
            # Set thumbnail to user avatar
            avatar = getattr(message.author, "display_avatar", None)
            avatar_url = getattr(avatar, "url", None)
            if avatar_url:
                embed.set_thumbnail(url=avatar_url)
            
            await self.send_lhs_log(message.guild, embed)
    
    @Cog.command(name="lhs_test")
    async def test_lhs(self, ctx: fluxer.Message, *, text: str = None):
        """Test LHS moderation on text (Admin only)"""
        if not text:
            await ctx.reply("Usage: `fm!lhs_test <text to analyze>`")
            return
        
        # Check if user has admin or manage guild
        member = getattr(ctx, "member", None) or ctx.author
        permissions = getattr(member, "permissions", None)
        
        has_perm = False
        if permissions:
            if getattr(permissions, "administrator", False):
                has_perm = True
            if getattr(permissions, "manage_guild", False):
                has_perm = True
        
        if not has_perm:
            await ctx.reply("You need Administrator or Manage Server permission to use this command.")
            return
        
        # Show typing indicator
        async with ctx.channel.typing():
            result = await self.lhs_client.check_content(text)
        
        if not result:
            await ctx.reply("Failed to analyze text. The LHS inference server may be unavailable.")
            return
        
        # Build result embed
        if result.is_harmful:
            violations = result.get_top_violations()
            violation_text = "\n".join([
                f"• **{v['display_name']}**: {v['confidence']:.1%}"
                for v in violations
            ])
            
            embed = EmbedBuilder.create_embed(
                title="AI Analysis: Harmful Content Detected",
                description=(
                    f"**Violations:**\n{violation_text}\n\n"
                    f"**Inference Time:** {result.inference_time_ms:.1f}ms"
                ),
                color=0xFF0000,
            )
        else:
            # Show all scores even if not flagged
            scores_text = "\n".join([
                f"• **{CATEGORY_DISPLAY_NAMES.get(cat, cat)}**: {pred['confidence']:.1%}"
                for cat, pred in sorted(
                    result.predictions.items(),
                    key=lambda x: x[1]['confidence'],
                    reverse=True
                )[:5]  # Top 5
            ])
            
            embed = EmbedBuilder.create_embed(
                title="AI Analysis: Clean",
                description=(
                    f"No harmful content detected.\n\n"
                    f"**Top Scores (below threshold):**\n{scores_text}\n\n"
                    f"**Inference Time:** {result.inference_time_ms:.1f}ms"
                ),
                color=0x00AA00,
            )
        
        await ctx.reply(embed=embed)
    
    @Cog.command(name="lhs_status")
    async def lhs_status(self, ctx: fluxer.Message):
        """Check LHS inference server status"""
        # Check permissions
        member = getattr(ctx, "member", None) or ctx.author
        permissions = getattr(member, "permissions", None)
        
        has_perm = False
        if permissions:
            if getattr(permissions, "administrator", False):
                has_perm = True
            if getattr(permissions, "manage_guild", False):
                has_perm = True
        
        if not has_perm:
            await ctx.reply("You need Administrator or Manage Server permission to use this command.")
            return
        
        async with ctx.channel.typing():
            health = await self.lhs_client.health_check()
        
        if health:
            embed = EmbedBuilder.create_embed(
                title="LHS Inference Server Status",
                description=(
                    f"**Status:** {health.get('status', 'unknown')}\n"
                    f"**Model Loaded:** {'Yes' if health.get('model_loaded') else 'No'}\n"
                    f"**Queue Size:** {health.get('queue_size', 0)}\n"
                    f"**Total Requests:** {health.get('total_requests', 0)}\n"
                    f"**Device:** {health.get('device', 'unknown')}"
                ),
                color=0x00AA00,
            )
        else:
            embed = EmbedBuilder.error_embed(
                "LHS Server Unavailable",
                "Could not connect to the LHS inference server. "
                "Please ensure it's running and accessible."
            )
        
        await ctx.reply(embed=embed)


async def setup(bot: fluxer.Bot):
    await bot.add_cog(LHSModerationCog(bot))
