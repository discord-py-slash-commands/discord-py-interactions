from enum import Enum, EnumMeta, IntEnum, IntFlag
from functools import reduce
from operator import or_
from typing import Iterator, Tuple, TypeVar, Type, Optional

from interactions.client.const import get_logger

__all__ = (
    "ActivityFlag",
    "ActivityType",
    "ApplicationFlags",
    "AuditLogEventType",
    "AutoArchiveDuration",
    "ButtonStyle",
    "ChannelFlags",
    "ChannelType",
    "CommandType",
    "ComponentType",
    "ContextType",
    "DefaultNotificationLevel",
    "ExplicitContentFilterLevel",
    "ForumLayoutType",
    "ForumSortOrder",
    "IntegrationExpireBehaviour",
    "IntegrationType",
    "Intents",
    "InteractionPermissionTypes",
    "InteractionType",
    "InviteTargetType",
    "MFALevel",
    "MemberFlags",
    "MentionType",
    "MessageActivityType",
    "MessageFlags",
    "MessageType",
    "NSFWLevel",
    "OnboardingMode",
    "OnboardingPromptType",
    "OverwriteType",
    "Permissions",
    "PollLayoutType",
    "PremiumTier",
    "PremiumType",
    "ScheduledEventPrivacyLevel",
    "ScheduledEventStatus",
    "ScheduledEventType",
    "StagePrivacyLevel",
    "Status",
    "StickerFormatType",
    "StickerTypes",
    "SystemChannelFlags",
    "TeamMembershipState",
    "UserFlags",
    "VerificationLevel",
    "VideoQualityMode",
    "WebSocketOPCode",
)


class AntiFlag:
    def __init__(self, anti=0) -> None:
        self.anti = anti

    def __get__(self, instance, cls) -> int:
        negative = ~cls(self.anti)
        return cls(reduce(or_, negative))


def _distinct(source) -> Tuple:
    return (x for x in source if (x.value & (x.value - 1)) == 0 and x.value != 0)


def _decompose(flag, value):  # noqa
    """
    Extract all members from the value.

    Source: Python 3.10.8 source
    """
    # _decompose is only called if the value is not named
    not_covered = value
    negative = value < 0
    members = []
    for member in flag:
        member_value = member.value
        if member_value and member_value & value == member_value:
            members.append(member)
            not_covered &= ~member_value
    if not negative:
        tmp = not_covered
        while tmp:
            flag_value = 2 ** (tmp.bit_length() - 1)
            if flag_value in flag._value2member_map_:
                members.append(flag._value2member_map_[flag_value])
                not_covered &= ~flag_value
            tmp &= ~flag_value
    if not members and value in flag._value2member_map_:
        members.append(flag._value2member_map_[value])
    members.sort(key=lambda m: m._value_, reverse=True)
    if len(members) > 1 and members[0].value == value:
        # we have the breakdown, don't need the value member itself
        members.pop(0)
    return members, not_covered


class DistinctFlag(EnumMeta):
    def __iter__(cls) -> Iterator:
        yield from _distinct(super().__iter__())

    def __call__(cls, value, names=None, *, module=None, qualname=None, type=None, start=1) -> "DistinctFlag":
        # To automatically convert string values into ints (eg for permissions)
        kwargs = {"names": names} if names else {}
        try:
            int_value = int(value)
            return super().__call__(int_value, module=module, qualname=qualname, type=type, start=start, **kwargs)
        except (TypeError, ValueError):
            return _return_cursed_enum(cls, value)


class DiscordIntFlag(IntFlag, metaclass=DistinctFlag):
    def __iter__(self) -> Iterator:
        yield from _decompose(self.__class__, self)[0]


SELF = TypeVar("SELF")


def _log_type_mismatch(cls, value) -> None:
    get_logger().warning(
        f"Class `{cls.__name__}` received an invalid and unexpected value `{value}`, a new enum item will be created to represent this value. Please update interactions.py or report this issue on GitHub - https://github.com/interactions-py/interactions.py/issues"
    )


def _return_cursed_enum(cls: Type[SELF], value) -> SELF:
    # log mismatch
    _log_type_mismatch(cls, value)

    new = int.__new__(cls)
    new._name_ = f"UNKNOWN-TYPE-{value}"
    new._value_ = value

    return cls._value2member_map_.setdefault(value, new)


class CursedIntEnum(IntEnum):
    @classmethod
    def _missing_(cls: Type[SELF], value) -> SELF:
        """Construct a new enum item to represent this new unknown type - without losing the value"""
        return _return_cursed_enum(cls, value)


class WebSocketOPCode(CursedIntEnum):
    """Codes used by the Gateway to signify events."""

    DISPATCH = 0
    """An event was dispatched"""
    HEARTBEAT = 1
    """Fired periodically by the client to keep the connection alive"""
    IDENTIFY = 2
    """Starts a new session during the initial handshake."""
    PRESENCE = 3
    """Update the client's presence."""
    VOICE_STATE = 4
    """Used to join/leave or move between voice channels."""
    VOICE_PING = 5
    RESUME = 6
    """Resume a previous session that was disconnected."""
    RECONNECT = 7
    """You should attempt to reconnect and resume immediately."""
    REQUEST_MEMBERS = 8
    """Request information about offline guild members in a large guild."""
    INVALIDATE_SESSION = 9
    """The session has been invalidated. You should reconnect and identify/resume accordingly."""
    HELLO = 10
    """Sent immediately after connecting, contains the `heartbeat_interval` to use."""
    HEARTBEAT_ACK = 11
    """Sent in response to receiving a heartbeat to acknowledge that it has been received."""
    GUILD_SYNC = 12


class Intents(DiscordIntFlag):  # type: ignore
    """
    When identifying to the gateway, you can specify an intents parameter which allows you to conditionally subscribe to pre-defined "intents", groups of events defined by Discord.

    info:
        For details about what intents do, or which intents you'll want, please read the [Discord API Documentation](https://discord.com/developers/docs/topics/gateway#gateway-intents)

    """

    GUILDS = 1 << 0
    GUILD_MEMBERS = 1 << 1
    GUILD_MODERATION = 1 << 2
    GUILD_EMOJIS_AND_STICKERS = 1 << 3
    GUILD_INTEGRATIONS = 1 << 4
    GUILD_WEBHOOKS = 1 << 5
    GUILD_INVITES = 1 << 6
    GUILD_VOICE_STATES = 1 << 7
    GUILD_PRESENCES = 1 << 8
    GUILD_MESSAGES = 1 << 9
    GUILD_MESSAGE_REACTIONS = 1 << 10
    GUILD_MESSAGE_TYPING = 1 << 11
    DIRECT_MESSAGES = 1 << 12
    DIRECT_MESSAGE_REACTIONS = 1 << 13
    DIRECT_MESSAGE_TYPING = 1 << 14
    MESSAGE_CONTENT = 1 << 15
    GUILD_SCHEDULED_EVENTS = 1 << 16
    AUTO_MODERATION_CONFIGURATION = 1 << 20
    AUTO_MODERATION_EXECUTION = 1 << 21
    GUILD_MESSAGE_POLLS = 1 << 24
    DIRECT_MESSAGE_POLLS = 1 << 25

    # Shortcuts/grouping/aliases
    MESSAGES = GUILD_MESSAGES | DIRECT_MESSAGES
    REACTIONS = GUILD_MESSAGE_REACTIONS | DIRECT_MESSAGE_REACTIONS
    TYPING = GUILD_MESSAGE_TYPING | DIRECT_MESSAGE_TYPING
    AUTO_MOD = AUTO_MODERATION_CONFIGURATION | AUTO_MODERATION_EXECUTION
    POLLS = GUILD_MESSAGE_POLLS | DIRECT_MESSAGE_POLLS

    PRIVILEGED = GUILD_PRESENCES | GUILD_MEMBERS | MESSAGE_CONTENT
    NON_PRIVILEGED = AntiFlag(PRIVILEGED)
    DEFAULT = NON_PRIVILEGED

    # Special members
    NONE = 0
    ALL = AntiFlag()

    @classmethod
    def new(
        cls,
        guilds=False,
        guild_members=False,
        guild_moderation=False,
        guild_emojis_and_stickers=False,
        guild_integrations=False,
        guild_webhooks=False,
        guild_invites=False,
        guild_voice_states=False,
        guild_presences=False,
        guild_messages=False,
        guild_message_polls=False,
        guild_message_reactions=False,
        guild_message_typing=False,
        direct_messages=False,
        direct_message_polls=False,
        direct_message_reactions=False,
        direct_message_typing=False,
        message_content=False,
        guild_scheduled_events=False,
        messages=False,
        polls=False,
        reactions=False,
        typing=False,
        privileged=False,
        non_privileged=False,
        default=False,
        all=False,
    ) -> "Intents":
        """Set your desired intents."""
        kwargs = locals()
        del kwargs["cls"]

        intents = cls.NONE
        for key in kwargs:
            if kwargs[key]:
                intents |= getattr(cls, key.upper())
        return intents


class UserFlags(DiscordIntFlag):  # type: ignore
    """Flags a user can have."""

    DISCORD_EMPLOYEE = 1 << 0
    """This person works for Discord"""
    PARTNERED_SERVER_OWNER = 1 << 1
    """User owns a partnered server"""
    HYPESQUAD_EVENTS = 1 << 2
    """User has helped with a hypesquad event"""
    BUG_HUNTER_LEVEL_1 = 1 << 3
    """User has passed the bug hunters quiz"""

    HOUSE_BRAVERY = 1 << 6
    """User belongs to the `bravery` house"""
    HOUSE_BRILLIANCE = 1 << 7
    """User belongs to the `brilliance` house"""
    HOUSE_BALANCE = 1 << 8
    """User belongs to the `balance` house"""
    EARLY_SUPPORTER = 1 << 9
    """This person had Nitro prior to Wednesday, October 10th, 2018"""

    TEAM_USER = 1 << 10
    """A team user"""

    BUG_HUNTER_LEVEL_2 = 1 << 14
    """User is a bug hunter level 2"""

    VERIFIED_BOT = 1 << 16
    """This bot has been verified by Discord"""
    EARLY_VERIFIED_BOT_DEVELOPER = 1 << 17
    """This user was one of the first to be verified"""
    DISCORD_CERTIFIED_MODERATOR = 1 << 18
    """This user is a certified moderator"""

    BOT_HTTP_INTERACTIONS = 1 << 19
    """Bot uses only HTTP interactions and is shown in the online member list"""

    SPAMMER = 1 << 20
    """A user who is suspected of spamming"""
    DISABLE_PREMIUM = 1 << 21
    """Nitro features disabled for this user. Only used by Discord Staff for testing"""
    ACTIVE_DEVELOPER = 1 << 22
    """This user is an active developer"""

    # Shortcuts/grouping/aliases
    HYPESQUAD = HOUSE_BRAVERY | HOUSE_BRILLIANCE | HOUSE_BALANCE
    BUG_HUNTER = BUG_HUNTER_LEVEL_1 | BUG_HUNTER_LEVEL_2

    # Special members
    NONE = 0
    ALL = AntiFlag()


class ApplicationFlags(DiscordIntFlag):  # type: ignore
    """Flags an application can have."""

    # Flags defined by the Discord API
    GATEWAY_PRESENCE = 1 << 12
    """Verified to use presence intent"""
    GATEWAY_PRESENCE_LIMITED = 1 << 13
    """Using presence intent, without verification"""
    GATEWAY_GUILD_MEMBERS = 1 << 14
    """Verified to use guild members intent"""
    GATEWAY_GUILD_MEMBERS_LIMITED = 1 << 15
    """Using members intent, without verification"""
    VERIFICATION_PENDING_GUILD_LIMIT = 1 << 16
    """Bot has hit guild limit, and has not been successfully verified"""
    EMBEDDED = 1 << 17
    """Application is a voice channel activity (ie YouTube Together)"""


class TeamMembershipState(CursedIntEnum):
    """Status of membership in the team."""

    INVITED = 1
    ACCEPTED = 2


class PremiumType(CursedIntEnum):
    """Types of premium membership."""

    NONE = 0
    """No premium membership"""
    NITRO_CLASSIC = 1
    """Using Nitro Classic"""
    NITRO = 2
    """Full Nitro membership"""
    NITRO_BASIC = 3
    """Basic Nitro membership"""


class MessageType(CursedIntEnum):
    """
    Types of message.

    Ref: https://discord.com/developers/docs/resources/channel#message-object-message-types
    """

    DEFAULT = 0
    RECIPIENT_ADD = 1
    RECIPIENT_REMOVE = 2
    CALL = 3
    CHANNEL_NAME_CHANGE = 4
    CHANNEL_ICON_CHANGE = 5
    CHANNEL_PINNED_MESSAGE = 6
    GUILD_MEMBER_JOIN = 7
    USER_PREMIUM_GUILD_SUBSCRIPTION = 8
    USER_PREMIUM_GUILD_SUBSCRIPTION_TIER_1 = 9
    USER_PREMIUM_GUILD_SUBSCRIPTION_TIER_2 = 10
    USER_PREMIUM_GUILD_SUBSCRIPTION_TIER_3 = 11
    CHANNEL_FOLLOW_ADD = 12
    GUILD_DISCOVERY_DISQUALIFIED = 14
    GUILD_DISCOVERY_REQUALIFIED = 15
    GUILD_DISCOVERY_GRACE_PERIOD_INITIAL_WARNING = 16
    GUILD_DISCOVERY_GRACE_PERIOD_FINAL_WARNING = 17
    THREAD_CREATED = 18
    REPLY = 19
    APPLICATION_COMMAND = 20
    THREAD_STARTER_MESSAGE = 21
    GUILD_INVITE_REMINDER = 22
    CONTEXT_MENU_COMMAND = 23
    AUTO_MODERATION_ACTION = 24
    ROLE_SUBSCRIPTION_PURCHASE = 25
    INTERACTION_PREMIUM_UPSELL = 26
    STAGE_START = 27
    STAGE_END = 28
    STAGE_SPEAKER = 29
    STAGE_TOPIC = 31
    GUILD_APPLICATION_PREMIUM_SUBSCRIPTION = 32
    GUILD_INCIDENT_ALERT_MODE_ENABLED = 36
    GUILD_INCIDENT_ALERT_MODE_DISABLED = 37
    GUILD_INCIDENT_REPORT_RAID = 38
    GUILD_INCIDENT_REPORT_FALSE_ALARM = 39
    PURCHASE_NOTIFICATION = 44
    POLL_RESULT = 46

    @classmethod
    def deletable(cls) -> Tuple["MessageType", ...]:
        """Return a tuple of message types that can be deleted."""
        return (
            cls.DEFAULT,
            cls.CHANNEL_PINNED_MESSAGE,
            cls.GUILD_MEMBER_JOIN,
            cls.USER_PREMIUM_GUILD_SUBSCRIPTION,
            cls.USER_PREMIUM_GUILD_SUBSCRIPTION_TIER_1,
            cls.USER_PREMIUM_GUILD_SUBSCRIPTION_TIER_2,
            cls.USER_PREMIUM_GUILD_SUBSCRIPTION_TIER_3,
            cls.CHANNEL_FOLLOW_ADD,
            cls.GUILD_DISCOVERY_DISQUALIFIED,
            cls.GUILD_DISCOVERY_REQUALIFIED,
            cls.GUILD_DISCOVERY_GRACE_PERIOD_INITIAL_WARNING,
            cls.GUILD_DISCOVERY_GRACE_PERIOD_FINAL_WARNING,
            cls.THREAD_CREATED,
            cls.REPLY,
            cls.APPLICATION_COMMAND,
            cls.GUILD_INVITE_REMINDER,
            cls.CONTEXT_MENU_COMMAND,
            cls.AUTO_MODERATION_ACTION,
            cls.ROLE_SUBSCRIPTION_PURCHASE,
            cls.INTERACTION_PREMIUM_UPSELL,
            cls.STAGE_START,
            cls.STAGE_END,
            cls.STAGE_SPEAKER,
            cls.STAGE_TOPIC,
            cls.GUILD_APPLICATION_PREMIUM_SUBSCRIPTION,
            cls.GUILD_INCIDENT_ALERT_MODE_ENABLED,
            cls.GUILD_INCIDENT_ALERT_MODE_DISABLED,
            cls.GUILD_INCIDENT_REPORT_RAID,
            cls.GUILD_INCIDENT_REPORT_FALSE_ALARM,
            cls.PURCHASE_NOTIFICATION,
            cls.POLL_RESULT,
        )


class EmbedType(Enum):
    """Types of embed."""

    RICH = "rich"
    IMAGE = "image"
    VIDEO = "video"
    GIFV = "gifv"
    ARTICLE = "article"
    LINK = "link"
    AUTOMOD_MESSAGE = "auto_moderation_message"
    AUTOMOD_NOTIFICATION = "auto_moderation_notification"
    POLL_RESULT = "poll_result"


class MessageActivityType(CursedIntEnum):
    """An activity object, similar to an embed."""

    JOIN = 1
    """Join the event"""
    SPECTATE = 2
    """Watch the event"""
    LISTEN = 3
    """Listen along to the event"""
    JOIN_REQUEST = 5
    """Asking a user to join the activity"""


class MessageFlags(DiscordIntFlag):  # type: ignore
    """Message flags."""

    CROSSPOSTED = 1 << 0
    """This message has been published to subscribed channels (via Channel Following)"""
    IS_CROSSPOST = 1 << 1
    """This message originated from a message in another channel (via Channel Following)"""
    SUPPRESS_EMBEDS = 1 << 2
    """Do not include any embeds when serializing this message"""
    SOURCE_MESSAGE_DELETED = 1 << 3
    """The source message for this crosspost has been deleted (via Channel Following)"""
    URGENT = 1 << 4
    """This message came from the urgent message system"""
    HAS_THREAD = 1 << 5
    """This message has an associated thread, with the same id as the message"""
    EPHEMERAL = 1 << 6
    """This message is only visible to the user who invoked the Interaction"""
    LOADING = 1 << 7
    """This message is an Interaction Response and the bot is "thinking"""
    FAILED_TO_MENTION_SOME_ROLES_IN_THREAD = 1 << 8
    """This message failed to mention some roles and add their members to the thread"""
    SHOULD_SHOW_LINK_NOT_DISCORD_WARNING = 1 << 10
    """This message contains a abusive website link, pops up a warning when clicked"""
    SILENT = 1 << 12
    """This message should not trigger push or desktop notifications"""
    VOICE_MESSAGE = 1 << 13
    """This message is a voice message"""

    SUPPRESS_NOTIFICATIONS = SILENT
    """Alias for :attr:`SILENT`"""

    # Special members
    NONE = 0
    ALL = AntiFlag()


class Permissions(DiscordIntFlag):  # type: ignore
    """Permissions a user or role may have."""

    # Permissions defined by Discord API
    CREATE_INSTANT_INVITE = 1 << 0
    """Allows creation of instant invites"""
    KICK_MEMBERS = 1 << 1
    """Allows kicking members"""
    BAN_MEMBERS = 1 << 2
    """Allows banning members"""
    ADMINISTRATOR = 1 << 3
    """Allows all permissions and bypasses channel permission overwrites"""
    MANAGE_CHANNELS = 1 << 4
    """Allows management and editing of channels"""
    MANAGE_GUILD = 1 << 5
    """Allows management and editing of the guild"""
    ADD_REACTIONS = 1 << 6
    """Allows for the addition of reactions to messages"""
    VIEW_AUDIT_LOG = 1 << 7
    """Allows for viewing of audit logs"""
    PRIORITY_SPEAKER = 1 << 8
    """Allows for using priority speaker in a voice channel"""
    STREAM = 1 << 9
    """Allows the user to go live"""
    VIEW_CHANNEL = 1 << 10
    """Allows guild members to view a channel, which includes reading messages in text channels and joining voice channels"""
    SEND_MESSAGES = 1 << 11
    """	Allows for sending messages in a channel (does not allow sending messages in threads)"""
    CREATE_POSTS = 1 << 11
    """Allow members to create posts in this channel. Alias to SEND_MESSAGES"""
    SEND_TTS_MESSAGES = 1 << 12
    """	Allows for sending of `/tts` messages"""
    MANAGE_MESSAGES = 1 << 13
    """Allows for deletion of other users messages"""
    EMBED_LINKS = 1 << 14
    """Links sent by users with this permission will be auto-embedded"""
    ATTACH_FILES = 1 << 15
    """Allows for uploading images and files"""
    READ_MESSAGE_HISTORY = 1 << 16
    """Allows for reading of message history"""
    MENTION_EVERYONE = 1 << 17
    """Allows for using the `@everyone` tag to notify all users in a channel, and the `@here` tag to notify all online users in a channel"""
    USE_EXTERNAL_EMOJIS = 1 << 18
    """Allows the usage of custom emojis from other servers"""
    VIEW_GUILD_INSIGHTS = 1 << 19
    """Allows for viewing guild insights"""
    CONNECT = 1 << 20
    """Allows for joining of a voice channel"""
    SPEAK = 1 << 21
    """Allows for speaking in a voice channel"""
    MUTE_MEMBERS = 1 << 22
    """Allows for muting members in a voice channel"""
    DEAFEN_MEMBERS = 1 << 23
    """Allows for deafening of members in a voice channel"""
    MOVE_MEMBERS = 1 << 24
    """Allows for moving of members between voice channels"""
    USE_VAD = 1 << 25
    """Allows for using voice-activity-detection in a voice channel"""
    CHANGE_NICKNAME = 1 << 26
    """Allows for modification of own nickname"""
    MANAGE_NICKNAMES = 1 << 27
    """Allows for modification of other users nicknames"""
    MANAGE_ROLES = 1 << 28
    """Allows management and editing of roles"""
    MANAGE_WEBHOOKS = 1 << 29
    """Allows management and editing of webhooks"""
    MANAGE_EMOJIS_AND_STICKERS = 1 << 30
    """Allows management and editing of emojis and stickers"""
    USE_APPLICATION_COMMANDS = 1 << 31
    """Allows members to use application commands, including slash commands and context menu commands"""
    REQUEST_TO_SPEAK = 1 << 32
    """Allows for requesting to speak in stage channels. (This permission is under active development and may be changed or removed.)"""
    MANAGE_EVENTS = 1 << 33
    """Allows for creating, editing, and deleting scheduled events"""
    MANAGE_THREADS = 1 << 34
    """Allows for deleting and archiving threads, and viewing all private threads"""
    USE_PUBLIC_THREADS = 1 << 35
    """	Allows for creating public and announcement threads"""
    USE_PRIVATE_THREADS = 1 << 36
    """Allows for creating private threads"""
    USE_EXTERNAL_STICKERS = 1 << 37
    """Allows the usage of custom stickers from other servers"""
    SEND_MESSAGES_IN_THREADS = 1 << 38
    """Allows for sending messages in threads"""
    START_EMBEDDED_ACTIVITIES = 1 << 39
    """Allows for using Activities (applications with the `EMBEDDED` flag) in a voice channel"""
    MODERATE_MEMBERS = 1 << 40
    """Allows for timing out users to prevent them from sending or reacting to messages in chat and threads, and from speaking in voice and stage channels"""
    VIEW_CREATOR_MONETIZATION_ANALYTICS = 1 << 41
    """Allows for viewing guild monetization insights"""
    USE_SOUNDBOARD = 1 << 42
    """Allows for using the soundboard in a voice channel"""
    CREATE_GUILD_EXPRESSIONS = 1 << 43
    """Allows for creating emojis, stickers, and soundboard sounds"""
    USE_EXTERNAL_SOUNDS = 1 << 45
    """Allows the usage of custom sounds from other servers"""
    SEND_VOICE_MESSAGES = 1 << 46
    """Allows for sending audio messages"""
    SEND_POLLS = 1 << 49
    """Allows sending polls"""

    # Shortcuts/grouping/aliases
    REQUIRES_MFA = (
        KICK_MEMBERS
        | BAN_MEMBERS
        | ADMINISTRATOR
        | MANAGE_CHANNELS
        | MANAGE_GUILD
        | MANAGE_MESSAGES
        | MANAGE_ROLES
        | MANAGE_WEBHOOKS
        | MANAGE_EMOJIS_AND_STICKERS
        | MANAGE_THREADS
        | MODERATE_MEMBERS
    )
    USE_SLASH_COMMANDS = USE_APPLICATION_COMMANDS
    """Legacy alias for :attr:`USE_APPLICATION_COMMANDS`"""

    # Special members
    NONE = 0
    ALL = AntiFlag()


class ChannelType(CursedIntEnum):
    """Types of channel."""

    GUILD_TEXT = 0
    """Text channel within a server"""
    DM = 1
    """Direct message between users"""
    GUILD_VOICE = 2
    """Voice channel within a server"""
    GROUP_DM = 3
    """Direct message between multiple users"""
    GUILD_CATEGORY = 4
    """Organizational category that contains up to 50 channels"""
    GUILD_NEWS = 5
    """Channel that users can follow and crosspost into their own server"""
    GUILD_NEWS_THREAD = 10
    """Temporary sub-channel within a GUILD_NEWS channel"""
    GUILD_PUBLIC_THREAD = 11
    """Temporary sub-channel within a GUILD_TEXT channel"""
    GUILD_PRIVATE_THREAD = 12
    """Temporary sub-channel within a GUILD_TEXT channel that is only viewable by those invited and those with the MANAGE_THREADS permission"""
    GUILD_STAGE_VOICE = 13
    """Voice channel for hosting events with an audience"""
    GUILD_FORUM = 15
    """A Forum channel"""
    GUILD_MEDIA = 16
    """Channel that can only contain threads, similar to `GUILD_FORUM` channels"""

    @property
    def guild(self) -> bool:
        """Whether this channel is a guild channel."""
        return self.value not in {1, 3}

    @property
    def voice(self) -> bool:
        """Whether this channel is a voice channel."""
        return self.value in {2, 13}


class ComponentType(CursedIntEnum):
    """The types of components supported by discord."""

    ACTION_ROW = 1
    """Container for other components"""
    BUTTON = 2
    """Button object"""
    STRING_SELECT = 3
    """Select menu for picking from text choices"""
    INPUT_TEXT = 4
    """Text input object"""
    USER_SELECT = 5
    """Select menu for picking from users"""
    ROLE_SELECT = 6
    """Select menu for picking from roles"""
    MENTIONABLE_SELECT = 7
    """Select menu for picking from mentionable objects"""
    CHANNEL_SELECT = 8
    """Select menu for picking from channels"""


class IntegrationType(CursedIntEnum):
    """The types of installation contexts supported by discord."""

    GUILD_INSTALL = 0
    USER_INSTALL = 1


class ContextType(CursedIntEnum):
    """The context of where an interaction can be used."""

    GUILD = 0
    BOT_DM = 1
    PRIVATE_CHANNEL = 2


class CommandType(CursedIntEnum):
    """The interaction commands supported by discord."""

    CHAT_INPUT = 1
    """Slash commands; a text-based command that shows up when a user types `/`"""
    USER = 2
    """A UI-based command that shows up when you right click or tap on a user"""
    MESSAGE = 3
    """A UI-based command that shows up when you right click or tap on a message"""


class InteractionType(CursedIntEnum):
    """The type of interaction received by discord."""

    PING = 1
    APPLICATION_COMMAND = 2
    MESSAGE_COMPONENT = 3
    AUTOCOMPLETE = 4
    MODAL_RESPONSE = 5


class InteractionPermissionTypes(CursedIntEnum):
    """The type of interaction permission received by discord."""

    ROLE = 1
    USER = 2
    CHANNEL = 3


class ButtonStyle(CursedIntEnum):
    """The styles of buttons supported."""

    # Based on discord api
    PRIMARY = 1
    """blurple"""
    SECONDARY = 2
    """grey"""
    SUCCESS = 3
    """green"""
    DANGER = 4
    """red"""
    LINK = 5
    """url button"""
    PREMIUM = 6
    """premium button"""

    # Aliases
    BLUE = 1
    BLURPLE = 1
    GRAY = 2
    GREY = 2
    GREEN = 3
    RED = 4
    URL = 5


class MentionType(str, Enum):
    """Types of mention."""

    EVERYONE = "everyone"
    ROLES = "roles"
    USERS = "users"


class OnboardingMode(CursedIntEnum):
    """Defines the criteria used to satisfy Onboarding constraints that are required for enabling."""

    ONBOARDING_DEFAULT = 0
    """Counts only Default Channels towards constraints"""
    ONBOARDING_ADVANCED = 1
    """Counts Default Channels and Questions towards constraints"""


class OnboardingPromptType(CursedIntEnum):
    """Types of Onboarding prompts."""

    MULTIPLE_CHOICE = 0
    DROPDOWN = 1


class OverwriteType(CursedIntEnum):
    """Types of permission overwrite."""

    ROLE = 0
    MEMBER = 1


class DefaultNotificationLevel(CursedIntEnum):
    """Default Notification levels for dms and guilds."""

    ALL_MESSAGES = 0
    ONLY_MENTIONS = 1


class ExplicitContentFilterLevel(CursedIntEnum):
    """Automatic filtering of explicit content."""

    DISABLED = 0
    MEMBERS_WITHOUT_ROLES = 1
    ALL_MEMBERS = 2


class MFALevel(CursedIntEnum):
    """Does the user use 2FA."""

    NONE = 0
    ELEVATED = 1


class VerificationLevel(CursedIntEnum):
    """Levels of verification needed by a guild."""

    NONE = 0
    """No verification needed"""
    LOW = 1
    """Must have a verified email on their Discord Account"""
    MEDIUM = 2
    """Must also be registered on Discord for longer than 5 minutes"""
    HIGH = 3
    """Must also be a member of this server for longer than 10 minutes"""
    VERY_HIGH = 4
    """Must have a verified phone number on their Discord Account"""


class NSFWLevel(CursedIntEnum):
    """A guilds NSFW Level."""

    DEFAULT = 0
    EXPLICIT = 1
    SAFE = 2
    AGE_RESTRICTED = 3


class PremiumTier(CursedIntEnum):
    """The boost level of a server."""

    NONE = 0
    """Guild has not unlocked any Server Boost perks"""
    TIER_1 = 1
    """Guild has unlocked Tier 1 Server Boost perks"""
    TIER_2 = 2
    """Guild has unlocked Tier 2 Server Boost perks"""
    TIER_3 = 3
    """Guild has unlocked Tier 3 Server Boost perks"""


class SystemChannelFlags(DiscordIntFlag):
    """System channel settings."""

    SUPPRESS_JOIN_NOTIFICATIONS = 1 << 0
    """Suppress member join notifications"""
    SUPPRESS_PREMIUM_SUBSCRIPTIONS = 1 << 1
    """Suppress server boost notifications"""
    SUPPRESS_GUILD_REMINDER_NOTIFICATIONS = 1 << 2
    """Suppress server setup tips"""
    SUPPRESS_JOIN_NOTIFICATION_REPLIES = 1 << 3
    """Hide member join sticker reply buttons"""

    # Special members
    NONE = 0
    ALL = AntiFlag()


class ChannelFlags(DiscordIntFlag):
    PINNED = 1 << 1
    """ Thread is pinned to the top of its parent forum channel """
    REQUIRE_TAG = 1 << 4
    """Whether a tag is required to be specified when creating a thread in a Guild Forum or Media channel."""
    CLYDE_THREAD = 1 << 8
    """This thread was created by Clyde"""
    HIDE_MEDIA_DOWNLOAD_OPTIONS = 1 << 15
    """when set hides the embedded media download options. Available only for media channels"""

    # Special members
    NONE = 0


class VideoQualityMode(CursedIntEnum):
    """Video quality settings."""

    AUTO = 1
    FULL = 2


class AutoArchiveDuration(CursedIntEnum):
    """Thread archive duration, in minutes."""

    ONE_HOUR = 60
    ONE_DAY = 1440
    THREE_DAY = 4320
    ONE_WEEK = 10080


class ActivityType(CursedIntEnum):
    """
    The types of presence activity that can be used in presences.

    !!! note
        Only `GAME` `STREAMING` `LISTENING` `WATCHING` and `COMPETING` are usable by bots

    """

    GAME = 0
    """Playing {name}; Example: Playing Rocket League"""
    STREAMING = 1
    """Streaming {details}; Example: Streaming Rocket League"""
    LISTENING = 2
    """Listening to {name}; Example: Listening to Spotify"""
    WATCHING = 3
    """Watching {name}; Example: Watching YouTube Together"""
    CUSTOM = 4
    """{emoji} {name}; Example: `:smiley: I am cool`"""
    COMPETING = 5
    """Competing in {name}; Example: Competing in Arena World Champions"""

    PLAYING = GAME
    """Alias for `GAME`"""


class ActivityFlag(DiscordIntFlag):
    INSTANCE = 1 << 0
    JOIN = 1 << 1
    SPECTATE = 1 << 2
    JOIN_REQUEST = 1 << 3
    SYNC = 1 << 4
    PLAY = 1 << 5
    PARTY_PRIVACY_FRIENDS = 1 << 6
    PARTY_PRIVACY_VOICE_CHANNEL = 1 << 7
    EMBEDDED = 1 << 8


class Status(str, Enum):
    """Represents the statuses a user may have."""

    ONLINE = "online"
    OFFLINE = "offline"
    DND = "dnd"
    IDLE = "idle"
    INVISIBLE = "invisible"

    AFK = IDLE
    DO_NOT_DISTURB = DND


class StagePrivacyLevel(CursedIntEnum):
    PUBLIC = 1
    GUILD_ONLY = 2


class IntegrationExpireBehaviour(CursedIntEnum):
    REMOVE_ROLE = 0
    KICK = 1


class InviteTargetType(CursedIntEnum):
    STREAM = 1
    EMBEDDED_APPLICATION = 2


class ScheduledEventPrivacyLevel(CursedIntEnum):
    """The privacy level of the scheduled event."""

    GUILD_ONLY = 2


class ScheduledEventType(CursedIntEnum):
    """The type of entity that the scheduled event is attached to."""

    STAGE_INSTANCE = 1
    """ Stage Channel """
    VOICE = 2
    """ Voice Channel """
    EXTERNAL = 3
    """ External URL """


class ScheduledEventStatus(CursedIntEnum):
    """The status of the scheduled event."""

    SCHEDULED = 1
    ACTIVE = 2
    COMPLETED = 3
    CANCELED = 4


class AuditLogEventType(CursedIntEnum):
    """
    The type of audit log entry type

    ref: https://discord.com/developers/docs/resources/audit-log#audit-log-entry-object-audit-log-events
    """

    GUILD_UPDATE = 1
    CHANNEL_CREATE = 10
    CHANNEL_UPDATE = 11
    CHANNEL_DELETE = 12
    CHANNEL_OVERWRITE_CREATE = 13
    CHANNEL_OVERWRITE_UPDATE = 14
    CHANNEL_OVERWRITE_DELETE = 15
    MEMBER_KICK = 20
    MEMBER_PRUNE = 21
    MEMBER_BAN_ADD = 22
    MEMBER_BAN_REMOVE = 23
    MEMBER_UPDATE = 24
    MEMBER_ROLE_UPDATE = 25
    MEMBER_MOVE = 26
    MEMBER_DISCONNECT = 27
    BOT_ADD = 28
    ROLE_CREATE = 30
    ROLE_UPDATE = 31
    ROLE_DELETE = 32
    INVITE_CREATE = 40
    INVITE_UPDATE = 41
    INVITE_DELETE = 42
    WEBHOOK_CREATE = 50
    WEBHOOK_UPDATE = 51
    WEBHOOK_DELETE = 52
    EMOJI_CREATE = 60
    EMOJI_UPDATE = 61
    EMOJI_DELETE = 62
    MESSAGE_DELETE = 72
    MESSAGE_BULK_DELETE = 73
    MESSAGE_PIN = 74
    MESSAGE_UNPIN = 75
    INTEGRATION_CREATE = 80
    INTEGRATION_UPDATE = 81
    INTEGRATION_DELETE = 82
    STAGE_INSTANCE_CREATE = 83
    STAGE_INSTANCE_UPDATE = 84
    STAGE_INSTANCE_DELETE = 85
    STICKER_CREATE = 90
    STICKER_UPDATE = 91
    STICKER_DELETE = 92
    GUILD_SCHEDULED_EVENT_CREATE = 100
    GUILD_SCHEDULED_EVENT_UPDATE = 101
    GUILD_SCHEDULED_EVENT_DELETE = 102
    THREAD_CREATE = 110
    THREAD_UPDATE = 111
    THREAD_DELETE = 112
    APPLICATION_COMMAND_PERMISSION_UPDATE = 121
    AUTO_MODERATION_RULE_CREATE = 140
    AUTO_MODERATION_RULE_UPDATE = 141
    AUTO_MODERATION_RULE_DELETE = 142
    AUTO_MODERATION_BLOCK_MESSAGE = 143
    AUTO_MODERATION_FLAG_TO_CHANNEL = 144
    AUTO_MODERATION_USER_COMMUNICATION_DISABLED = 145
    AUTO_MODERATION_QUARANTINE = 146
    CREATOR_MONETIZATION_REQUEST_CREATED = 150
    CREATOR_MONETIZATION_TERMS_ACCEPTED = 151
    ROLE_PROMPT_CREATE = 160
    ROLE_PROMPT_UPDATE = 161
    ROLE_PROMPT_DELETE = 162
    ON_BOARDING_QUESTION_CREATE = 163
    ON_BOARDING_QUESTION_UPDATE = 164
    ONBOARDING_UPDATE = 167
    GUILD_HOME_FEATURE_ITEM = 171
    GUILD_HOME_FEATURE_ITEM_UPDATE = 172
    BLOCKED_PHISHING_LINK = 180
    SERVER_GUIDE_CREATE = 190
    SERVER_GUIDE_UPDATE = 191
    VOICE_CHANNEL_STATUS_CREATE = 192
    VOICE_CHANNEL_STATUS_DELETE = 193
    CLYDE_AI_PROFILE_UPDATE = 194
    GUILD_SCHEDULED_EVENT_EXCEPTION_CREATE = 200
    GUILD_SCHEDULED_EVENT_EXCEPTION_UPDATE = 201
    GUILD_SCHEDULED_EVENT_EXCEPTION_DELETE = 202


class AutoModTriggerType(CursedIntEnum):
    KEYWORD = 1
    HARMFUL_LINK = 2
    SPAM = 3
    KEYWORD_PRESET = 4
    MENTION_SPAM = 5
    MEMBER_PROFILE = 6


class AutoModAction(CursedIntEnum):
    BLOCK_MESSAGE = 1
    ALERT_MESSAGE = 2
    TIMEOUT_USER = 3
    BLOCK_MEMBER_INTERACTION = 4


class AutoModEvent(CursedIntEnum):
    MESSAGE_SEND = 1
    MEMBER_UPDATE = 2


class AutoModLanuguageType(Enum):
    PROFANITY = "PROFANITY"
    SEXUAL = "SEXUAL_CONTENT"
    INSULTS_AND_SLURS = "SLURS"


class MemberFlags(DiscordIntFlag):
    DID_REJOIN = 1 << 0
    COMPLETED_ONBOARDING = 1 << 1
    BYPASSES_VERIFICATION = 1 << 2
    STARTED_ONBOARDING = 1 << 3


class StickerTypes(CursedIntEnum):
    """Types of sticker."""

    STANDARD = 1
    """An official sticker in a pack, part of Nitro or in a removed purchasable pack."""
    GUILD = 2
    """A sticker uploaded to a Boosted guild for the guild's members."""


class StickerFormatType(CursedIntEnum):
    """File formats for stickers."""

    PNG = 1
    APNG = 2
    LOTTIE = 3
    GIF = 4


class ForumLayoutType(CursedIntEnum):
    """The layout of a forum channel."""

    NOT_SET = 0
    LIST = 1
    GALLERY = 2


class ForumSortOrder(CursedIntEnum):
    """The order of a forum channel."""

    LATEST_ACTIVITY = 0
    CREATION_DATE = 1

    @classmethod
    def converter(cls, value: Optional[int]) -> "ForumSortOrder":
        return None if value is None else cls(value)


class EntitlementType(CursedIntEnum):
    """The type of entitlement."""

    PURCHASE = 1
    """Entitlement was purchased by user"""
    PREMIUM_SUBSCRIPTION = 2
    """Entitlement for Discord Nitro subscription"""
    DEVELOPER_GIFT = 3
    """Entitlement was gifted by developer"""
    TEST_MODE_PURCHASE = 4
    """Entitlement was purchased by a dev in application test mode"""
    FREE_PURCHASE = 5
    """Entitlement was granted when the SKU was free"""
    USER_GIFT = 6
    """Entitlement was gifted by another user"""
    PREMIUM_PURCHASE = 7
    """Entitlement was claimed by user for free as a Nitro Subscriber"""
    APPLICATION_SUBSCRIPTION = 8
    """Entitlement was purchased as an app subscription"""


class PollLayoutType(CursedIntEnum):
    """The layout of a poll."""

    DEFAULT = 1
