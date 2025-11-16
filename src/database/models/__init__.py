"""
Database Models Package
========================

This package contains all SQLAlchemy ORM models for the Luminescent RPG system,
organized by domain following DDD (Domain-Driven Design) principles.

All models follow LUMEN LAW (2025):
- Schema-only, no business logic
- Use Mapped[] syntax with mapped_column()
- Inherit from appropriate mixins (IdMixin, TimestampMixin, SoftDeleteMixin)
- Explicit foreign key constraints with CASCADE rules
- Optimistic locking via version fields for mutable models
- JSONB fields for extensibility with GIN indexes

Domain Organization:
--------------------
- core: Foundational models (Player DDD split, Maiden, GameConfig)
- economy: Economic systems (Shrines, Tokens, Transactions)
- progression: Player progression (Quests, Sectors, Ascension, Leaderboards)
- social: Social features (Guilds, Members, Invites, Audit logs)
- enums: Shared type-safe enumerations

For detailed model documentation, see individual domain packages.
"""

from src.core.database.base import Base

# Core models
from .core import (
    PlayerCore,
    PlayerProgression,
    PlayerStats,
    PlayerCurrencies,
    PlayerActivity,
    Maiden,
    MaidenBase,
    GameConfig,
)

# Economy models
from .economy import (
    GuildShrine,
    PlayerShrine,
    Token,
    TransactionLog,
)

# Progression models
from .progression import (
    AscensionProgress,
    DailyQuest,
    ExplorationMastery,
    LeaderboardSnapshot,
    SectorProgress,
    TutorialProgress,
)

# Social models
from .social import (
    Guild,
    GuildMember,
    GuildInvite,
    GuildAudit,
)

# Enums
from . import enums

__all__ = [
    # Base
    "Base",
    # Core
    "PlayerCore",
    "PlayerProgression",
    "PlayerStats",
    "PlayerCurrencies",
    "PlayerActivity",
    "Maiden",
    "MaidenBase",
    "GameConfig",
    # Economy
    "GuildShrine",
    "PlayerShrine",
    "Token",
    "TransactionLog",
    # Progression
    "AscensionProgress",
    "DailyQuest",
    "ExplorationMastery",
    "LeaderboardSnapshot",
    "SectorProgress",
    "TutorialProgress",
    # Social
    "Guild",
    "GuildMember",
    "GuildInvite",
    "GuildAudit",
    # Enums module
    "enums",
]
