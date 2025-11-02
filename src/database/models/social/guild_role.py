import enum


class GuildRole(str, enum.Enum):
    """
    Enumerates all possible guild roles.
    Used by GuildMember and GuildService for permissions.
    """
    leader = "leader"
    officer = "officer"
    member = "member"
