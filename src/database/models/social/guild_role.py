"""
GuildRole — permissible guild roles.
"""

import enum


class GuildRole(str, enum.Enum):
    leader = "leader"
    officer = "officer"
    member = "member"
