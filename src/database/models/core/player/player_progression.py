"""
Player Progression Model
=========================

All long-term progression tracking for players.

Schema-only representation of:
- Level and experience
- Player class
- Stat point allocation
- Milestone tracking (highest sector, floor, tier)
- Fusion system counters
- Gacha system (summons, pity)
- Tutorial progress

All behavior and game rules live in service/domain layers.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database.base import Base, IdMixin

if TYPE_CHECKING:
    from .player_core import PlayerCore


class PlayerProgression(Base, IdMixin):
    """
    Player progression and milestone tracking.

    Tracks all long-term advancement: levels, experience, class selection,
    stat allocation, milestone achievements, fusion progress, gacha state,
    and tutorial completion.
    """

    # ========================================================================
    # STAT ALLOCATION CONSTANTS (kept as static config values)
    # ========================================================================

    BASE_ENERGY = 100
    BASE_STAMINA = 50
    BASE_HP = 500

    ENERGY_PER_POINT = 10
    STAMINA_PER_POINT = 5
    HP_PER_POINT = 100
    POINTS_PER_LEVEL = 5

    # Player classes (used by services for bonus logic)
    DESTROYER = "destroyer"
    ADAPTER = "adapter"
    INVOKER = "invoker"

    VALID_CLASSES = [DESTROYER, ADAPTER, INVOKER]

    # ========================================================================
    # TABLE CONFIGURATION
    # ========================================================================

    __tablename__ = "player_progression"
    __table_args__ = (
        Index("ix_player_progression_player_id", "player_id", unique=True),
        Index("ix_player_progression_level", "level"),
        Index("ix_player_progression_class_level", "class_name", "level"),
        Index("ix_player_progression_highest_sector", "highest_sector"),
        Index("ix_player_progression_highest_floor", "highest_floor"),
    )

    # ========================================================================
    # PRIMARY KEY & FOREIGN KEY
    # ========================================================================

    player_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("player_core.discord_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
        doc="Reference to player core identity",
    )

    version: Mapped[int] = mapped_column(
        nullable=False,
        default=1,
        doc="Optimistic locking version for concurrent updates",
    )

    # ========================================================================
    # LEVEL & EXPERIENCE
    # ========================================================================

    level: Mapped[int] = mapped_column(
        nullable=False,
        default=1,
        index=True,
        doc="Current player level",
    )

    xp: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        doc="Current experience points",
    )

    last_level_up: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        doc="Timestamp of most recent level up",
    )

    # ========================================================================
    # PLAYER CLASS
    # ========================================================================

    class_name: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        index=True,
        doc="Selected player class (destroyer, adapter, invoker)",
    )

    # ========================================================================
    # STAT POINT ALLOCATION
    # ========================================================================

    stat_points: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        doc="Unallocated stat points available",
    )

    # ========================================================================
    # PROGRESSION MILESTONES
    # ========================================================================

    highest_sector: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        doc="Highest sector reached in exploration",
    )

    highest_floor: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        doc="Highest floor ascended in tower",
    )

    highest_tier: Mapped[int] = mapped_column(
        nullable=False,
        default=1,
        doc="Highest maiden tier achieved through fusion",
    )

    # ========================================================================
    # FUSION SYSTEM
    # ========================================================================

    total_fusions: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        doc="Total fusion attempts made",
    )

    successful_fusions: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        doc="Number of successful fusions",
    )

    failed_fusions: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        doc="Number of failed fusions",
    )

    # ========================================================================
    # GACHA SYSTEM
    # ========================================================================

    total_summons: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        doc="Total number of summons performed",
    )

    pity_counter: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        doc="Current pity counter for gacha system",
    )

    # ========================================================================
    # TUTORIAL SYSTEM
    # ========================================================================

    tutorial_completed: Mapped[bool] = mapped_column(
        nullable=False,
        default=False,
        doc="Whether the tutorial has been completed",
    )

    tutorial_step: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        doc="Current tutorial step (0 = not started)",
    )

    # ========================================================================
    # STATE & METADATA
    # ========================================================================

    state: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
        doc="Flexible state storage for progression-related data",
    )

    # ========================================================================
    # RELATIONSHIPS
    # ========================================================================

    player: Mapped["PlayerCore"] = relationship(
        "PlayerCore",
        back_populates="progression",
        doc="Reference to player core data",
    )
