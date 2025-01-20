from typing import TYPE_CHECKING, List, Optional, Dict, Any, Union

import attrs

from interactions.models.discord.asset import Asset
from interactions.models.discord.enums import TeamMembershipState
from interactions.models.discord.snowflake import to_snowflake
from .base import DiscordObject

if TYPE_CHECKING:
    from interactions.models.discord.user import User
    from interactions.models.discord.snowflake import Snowflake_Type, SnowflakeObject
    from interactions.client import Client

__all__ = ("Team", "TeamMember")


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class TeamMember(DiscordObject):
    membership_state: TeamMembershipState = attrs.field(repr=False, converter=TeamMembershipState)
    """Rhe user's membership state on the team"""
    # permissions: List[str] = attrs.field(repr=False, default=["*"])  # disabled until discord adds more team roles
    team_id: "Snowflake_Type" = attrs.field(repr=True)
    """Rhe id of the parent team of which they are a member"""
    user: "User" = attrs.field(
        repr=False,
    )  # TODO: cache partial user (avatar, discrim, id, username)
    """Rhe avatar, discriminator, id, and username of the user"""

    @classmethod
    def _process_dict(cls, data: Dict[str, Any], client: "Client") -> Dict[str, Any]:
        data["user"] = client.cache.place_user_data(data["user"])
        data["id"] = data["user"].id
        return data


@attrs.define(eq=False, order=False, hash=False, kw_only=True)
class Team(DiscordObject):
    icon: Optional[Asset] = attrs.field(repr=False, default=None)
    """A hash of the image of the team's icon"""
    members: List[TeamMember] = attrs.field(repr=False, factory=list)
    """The members of the team"""
    name: str = attrs.field(repr=True)
    """The name of the team"""
    owner_user_id: "Snowflake_Type" = attrs.field(repr=False, converter=to_snowflake)
    """The user id of the current team owner"""

    @classmethod
    def _process_dict(cls, data: Dict[str, Any], client: "Client") -> Dict[str, Any]:
        data["members"] = TeamMember.from_list(data["members"], client)
        if data["icon"]:
            data["icon"] = Asset.from_path_hash(client, f"team-icons/{data['id']}/{{}}", data["icon"])
        return data

    @property
    def owner(self) -> "User":
        """The owner of the team"""
        return self._client.cache.get_user(self.owner_user_id)

    def is_in_team(self, user: Union["SnowflakeObject", "Snowflake_Type"]) -> bool:
        """
        Returns True if the passed user or ID is a member within the team.

        Args:
            user: The user or user ID to check

        Returns:
            Boolean indicating whether the user is in the team

        """
        return to_snowflake(user) in [m.id for m in self.members]
