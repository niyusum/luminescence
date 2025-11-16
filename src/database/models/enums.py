"""
Database Model Enums
====================

Lightweight enumerations for database models.

These enums provide type-safe constants for various categorical fields
across the database schema. They are used in model definitions and
should be referenced by service layers for business logic.

All enums follow LUMEN LAW (2025) - they are declarative schema helpers,
not business logic containers.
"""

from __future__ import annotations

import enum


class ShrineType(str, enum.Enum):
    """
    Types of shrines in the game economy.

    Shrines are special locations where players can invest resources
    for various benefits.
    """

    PERSONAL = "personal"
    GUILD = "guild"
    WORLD = "world"


class QuestType(str, enum.Enum):
    """
    Types of quests available to players.

    Used by the daily quest and progression systems.
    """

    DAILY = "daily"
    WEEKLY = "weekly"
    STORY = "story"
    EVENT = "event"
    ACHIEVEMENT = "achievement"


class LeaderboardCategory(str, enum.Enum):
    """
    Categories for leaderboard rankings.

    Each category represents a different competitive metric.
    """

    TOTAL_POWER = "total_power"
    LEVEL = "level"
    MAIDEN_COLLECTION = "maiden_collection"
    ARENA_RANKING = "arena_ranking"
    GUILD_CONTRIBUTION = "guild_contribution"
    EXPLORATION_PROGRESS = "exploration_progress"
    ASCENSION_FLOOR = "ascension_floor"
    SEASONAL = "seasonal"


class TransactionType(str, enum.Enum):
    """
    Types of economic transactions.

    Used for tracking currency flows in the economy.
    """

    EARN = "earn"
    SPEND = "spend"
    TRANSFER = "transfer"
    REFUND = "refund"
    ADMIN_GRANT = "admin_grant"
    ADMIN_DEDUCT = "admin_deduct"


class GuildRole(str, enum.Enum):
    """
    Roles within a guild hierarchy.

    Determines permissions and responsibilities.
    """

    MASTER = "master"
    OFFICER = "officer"
    MEMBER = "member"
    RECRUIT = "recruit"
