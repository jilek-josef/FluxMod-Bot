from typing import Any

import fluxer


def resolve_user_id(member: Any) -> int | None:
    if isinstance(member, fluxer.GuildMember):
        return member.user.id

    if isinstance(member, fluxer.User):
        return member.id

    if isinstance(member, int):
        return member

    if isinstance(member, str):
        value = member.strip()
        if value.startswith("<@") and value.endswith(">"):
            value = value[2:-1].replace("!", "")
        if value.isdigit():
            return int(value)

    return None


def resolve_channel_id(channel: Any) -> int | None:
    if hasattr(channel, "id"):
        return int(channel.id)

    if isinstance(channel, int):
        return channel

    if isinstance(channel, str):
        value = channel.strip()
        if value.startswith("<#") and value.endswith(">"):
            value = value[2:-1]
        if value.isdigit():
            return int(value)

    return None


async def resolve_guild_member(bot: fluxer.Bot, ctx: fluxer.Message, member: Any):
    user_id = resolve_user_id(member)
    if user_id is None or ctx.guild_id is None:
        return None

    try:
        guild = await bot.fetch_guild(str(ctx.guild_id))
        return await guild.fetch_member(user_id=user_id)
    except Exception:
        return None
