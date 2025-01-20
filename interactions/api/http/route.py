from typing import TYPE_CHECKING, Any, ClassVar, Optional
from urllib.parse import quote as _uriquote

from interactions.client.const import __api_version__

if TYPE_CHECKING:
    from interactions.models.discord.snowflake import Snowflake_Type

__all__ = ("PAYLOAD_TYPE", "Route")

PAYLOAD_TYPE = dict[str, int | str | bool | list | None]


class Route:
    BASE: ClassVar[str] = f"https://discord.com/api/v{__api_version__}"
    path: str
    params: dict[str, str | int]

    webhook_id: Optional["Snowflake_Type"]
    webhook_token: Optional[str]

    def __init__(self, method: str, path: str, **parameters: Any) -> None:
        self.path: str = path
        self.method: str = method
        self.params = parameters

        self.channel_id = parameters.get("channel_id")
        self.guild_id = parameters.get("guild_id")
        self.webhook_id = parameters.get("webhook_id")
        self.webhook_token = parameters.get("webhook_token")

        self.known_bucket: Optional[str] = None

    def __eq__(self, other: "Route") -> bool:
        if isinstance(other, Route):
            return self.rl_bucket == other.rl_bucket
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.rl_bucket)

    def __repr__(self) -> str:
        return f"<Route {self.endpoint}>"

    def __str__(self) -> str:
        return self.endpoint

    @property
    def rl_bucket(self) -> str:
        """This route's full rate limit bucket"""
        if self.known_bucket:
            return self.known_bucket

        if self.webhook_token:
            return f"{self.webhook_id}{self.webhook_token}:{self.channel_id}:{self.guild_id}:{self.endpoint}"
        return f"{self.channel_id}:{self.guild_id}:{self.endpoint}"

    @property
    def major_params(self) -> dict[str, str | int]:
        """The major parameters for this route"""
        return {
            "channel_id": self.channel_id,
            "guild_id": self.guild_id,
            "webhook_id": self.webhook_id,
            "webhook_token": self.webhook_token,
        }

    @property
    def resolved_path(self) -> str:
        """The endpoint for this route, with all parameters resolved"""
        return self.path.format_map({k: _uriquote(v) if isinstance(v, str) else v for k, v in self.params.items()})

    @property
    def endpoint(self) -> str:
        """The endpoint for this route"""
        return f"{self.method} {self.path}"

    @property
    def resolved_endpoint(self) -> str:
        """The endpoint for this route, with all major parameters resolved"""
        path = self.path
        for key, value in self.major_params.items():
            path = path.replace(f"{{{key}}}", str(value))

        return f"{self.method} {path}"

    @property
    def url(self) -> str:
        """The full url for this route"""
        return f"{self.BASE}{self.resolved_path}"
