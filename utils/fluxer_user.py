from typing import Any
from fluxer import User
from fluxer import GuildMember
import fluxer


class FluxerUser:
    """
    Unified wrapper for fluxer.User and fluxer.GuildMember.
    Provides common properties and DM/send handling.
    """

    def __init__(self, member: User | GuildMember):
        if isinstance(member, GuildMember):
            self._member = member
            self._user = member.user
        elif isinstance(member, User):
            self._member = None
            self._user = member
        else:
            raise TypeError(f"Expected User or GuildMember, got {type(member)}")

    @property
    def id(self) -> int:
        return self._user.id

    @property
    def display_name(self) -> str:
        return self._member.display_name if self._member else self._user.display_name

    @property
    def mention(self) -> str:
        return self._member.mention if self._member else self._user.mention

    @property
    def avatar_url(self) -> str | None:
        if self._member and self._member.guild_avatar_url:
            return self._member.guild_avatar_url
        return self._user.avatar_url

    async def send_dm(
        self,
        content: str | None = None,
        *,
        embed: Any | None = None,
        embeds: list[Any] | None = None
    ) -> fluxer.Message:
        """Send a DM to the user (works for both User & GuildMember)."""
        return await self._user.send(content=content, embed=embed, embeds=embeds)

    def raw(self) -> User | GuildMember:
        """Return the original object."""
        return self._member or self._user