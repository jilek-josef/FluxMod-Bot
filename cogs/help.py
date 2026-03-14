import fluxer
from fluxer import Cog


class HelpCog(Cog):
    def __init__(self, bot: fluxer.Bot):
        super().__init__(bot)
        self.bot = bot

    @Cog.command(name="help")
    async def help(self, ctx: fluxer.Message):
        prefix = getattr(getattr(self.bot, "command_prefix", None), "strip", lambda: "!")()
        if not isinstance(prefix, str) or not prefix:
            prefix = "fm!"

        embed_help = fluxer.Embed(
            title="FluxMod Command Help",
            description="Current commands available in this bot.",
            color=0x00BFFF,
        )

        embed_help.add_field(
            name="AutoMod Configuration",
            value=(
                f"`{prefix}set_automod_logs <#channel|channel_id>`\n"
                "Set the AutoMod log channel.\n\n"
                f"`{prefix}set_exempt_channels <#ch1>, <#ch2>, ...`\n"
                "Set channels that bypass AutoMod checks.\n\n"
                f"`{prefix}set_exempt_roles <@&role1>, <@&role2>, ...`\n"
                "Set roles that bypass AutoMod checks.\n\n"
                f"`{prefix}set_keywords <word1, word2, ...>`\n"
                "Set blocked keyword patterns (`*` wildcard supported).\n\n"
                f"`{prefix}set_allowed_keywords <word1, word2, ...>`\n"
                "Set allowed keyword patterns that override blocked matches.\n\n"
                f"`{prefix}set_regex_patterns <pattern1, pattern2, ...>`\n"
                "Set blocked regex patterns.\n\n"
                f"`{prefix}set_exempt_users <@user1>, <@user2>, ...`\n"
                "Set users that bypass AutoMod checks."
            ),
            inline=False,
        )

        embed_help.add_field(
            name="AutoMod Status",
            value=(
                f"`{prefix}toggle_automod`\n"
                "Enable or disable AutoMod for this server.\n\n"
                f"`{prefix}view_automod_rules`\n"
                "View current AutoMod settings and active values."
            ),
            inline=False,
        )

        embed_help.add_field(
            name="🤖 AI Moderation (Experimental)",
            value=(
                f"`{prefix}toggle_ai_mod`\n"
                "Enable or disable AI moderation.\n\n"
                f"`{prefix}ai_mod_settings`\n"
                "View current AI moderation settings.\n\n"
                f"`{prefix}set_ai_mod_threshold <0.0-1.0>`\n"
                "Set global detection threshold (default: 0.65).\n\n"
                f"`{prefix}set_ai_mod_category <category> <on/off> [threshold]`\n"
                "Configure a specific detection category.\n\n"
                f"`{prefix}set_ai_mod_exempt_roles <@&role1> ...`\n"
                "Set roles exempt from AI moderation.\n\n"
                f"`{prefix}set_ai_mod_exempt_channels <#ch1> ...`\n"
                "Set channels exempt from AI moderation.\n\n"
                f"`{prefix}ai_mod_status`\n"
                "Check AI inference server status.\n\n"
                f"`{prefix}test_ai_mod <text>`\n"
                "Test AI moderation on text.\n\n"
                f"`{prefix}ai_mod_help`\n"
                "Show detailed AI moderation help.\n\n"
                "⚠️ **Note:** This is an experimental feature that uses machine learning. "
                "It may produce false positives or negatives."
            ),
            inline=False,
        )

        embed_help.add_field(
            name="Warning System",
            value=(
                f"`{prefix}warnings <@user|user_id>`\n"
                "View warnings for a user.\n\n"
                f"{prefix}delwarn <@user|user_id> <index>`\n"
                "Delete one warning by index."
            ),
            inline=False,
        )

        embed_help.set_footer(text=f"Prefix: {prefix} | Use mentions or IDs where accepted")
        await ctx.reply(embed=embed_help)

async def setup(bot: fluxer.Bot):
    await bot.add_cog(HelpCog(bot))
