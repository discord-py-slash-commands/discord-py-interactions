from typing import Awaitable, Callable

from interactions.models.discord.role import Role
from interactions.models.discord.snowflake import Snowflake_Type, to_snowflake
from interactions.models.discord.user import Member
from interactions.models.internal.context import BaseContext

__all__ = ("dm_only", "guild_only", "has_any_role", "has_id", "has_role", "is_owner")

TYPE_CHECK_FUNCTION = Callable[[BaseContext], Awaitable[bool]]


def has_role(role: Snowflake_Type | Role) -> TYPE_CHECK_FUNCTION:
    """
    Check if the user has the given role.

    Args:
        role: The Role or role id to check for

    """

    async def check(ctx: BaseContext) -> bool:
        if ctx.guild is None:
            return False
        author: Member = ctx.author  # pyright: ignore [reportGeneralTypeIssues]
        return author.has_role(role)

    return check


def has_any_role(*roles: Snowflake_Type | Role) -> TYPE_CHECK_FUNCTION:
    """
    Checks if the user has any of the given roles.

    Args:
        *roles: The Role(s) or role id(s) to check for

    """

    async def check(ctx: BaseContext) -> bool:
        if ctx.guild is None:
            return False

        author: Member = ctx.author  # pyright: ignore [reportGeneralTypeIssues]
        return any((author.has_role(to_snowflake(r)) for r in roles))

    return check


def has_id(user_id: int) -> TYPE_CHECK_FUNCTION:
    """
    Checks if the author has the desired ID.

    Args:
        user_id: id of the user to check for

    """

    async def check(ctx: BaseContext) -> bool:
        return ctx.author.id == user_id

    return check


def is_owner() -> TYPE_CHECK_FUNCTION:
    """Checks if the author is the owner of the bot. This respects the `client.owner_ids` list."""

    async def check(ctx: BaseContext) -> bool:
        _owner_ids: set = ctx.bot.owner_ids.copy()
        if ctx.bot.app.team:
            [_owner_ids.add(m.id) for m in ctx.bot.app.team.members]
        return ctx.author.id in _owner_ids

    return check


def guild_only() -> TYPE_CHECK_FUNCTION:
    """This command may only be ran in a guild."""

    async def check(ctx: BaseContext) -> bool:
        return ctx.guild is not None

    return check


def dm_only() -> TYPE_CHECK_FUNCTION:
    """This command may only be ran in a dm."""

    async def check(ctx: BaseContext) -> bool:
        return ctx.guild is None

    return check
