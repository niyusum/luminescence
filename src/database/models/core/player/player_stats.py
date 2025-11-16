"""
Player Stats Model
==================

Combat statistics and resource pools for players.

Schema-only representation of:
- Resource pools (energy, stamina, hp)
- Resource regeneration timestamps
- Drop charges
- Combat power aggregates (attack, defense, total power)
- Stat allocation tracking (JSON)
- Battle statistics (JSON)

All behavior and game rules live in service/domain layers.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Dict, Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSON, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database.base import Base, IdMixin

if TYPE_CHECKING:
    from .player_core import PlayerCore


def _default_stat_points_spent() -> Dict[str, int]:
    """Default stat point allocation tracker."""
    return {"energy": 0, "stamina": 0, "hp": 0}


def _default_stats() -> Dict[str, int]:
    """Default battle and activity statistics."""
    return {
        "battles_fought": 0,
        "battles_won": 0,
        "total_lumees_earned": 0,
        "total_lumees_spent": 0,
        "drops_performed": 0,
        "shards_earned": 0,
        "shards_spent": 0,
        "level_ups": 0,
        "overflow_energy_gained": 0,
        "overflow_stamina_gained": 0,
        "total_explorations": 0,
        "total_miniboss_defeats": 0,
        "total_maidens_purified": 0,
        "total_floor_attempts": 0,
        "total_floor_victories": 0,
    }


class PlayerStats(Base, IdMixin):
    """
    Player combat statistics and resource pools.

    Tracks current and maximum values for all player resources,
    regeneration timestamps, combat power aggregates, and detailed
    battle/activity statistics.
    """

    # ========================================================================
    # TABLE CONFIGURATION
    # ========================================================================

    __tablename__ = "player_stats"
    __table_args__ = (
        Index("ix_player_stats_player_id", "player_id", unique=True),
        Index("ix_player_stats_total_power", "total_power"),
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
    # ENERGY RESOURCES
    # ========================================================================

    energy: Mapped[int] = mapped_column(
        nullable=False,
        default=100,
        doc="Current energy points",
    )

    max_energy: Mapped[int] = mapped_column(
        nullable=False,
        default=100,
        doc="Maximum energy capacity",
    )

    # ========================================================================
    # STAMINA RESOURCES
    # ========================================================================

    stamina: Mapped[int] = mapped_column(
        nullable=False,
        default=50,
        doc="Current stamina points",
    )

    max_stamina: Mapped[int] = mapped_column(
        nullable=False,
        default=50,
        doc="Maximum stamina capacity",
    )

    # ========================================================================
    # HP RESOURCES
    # ========================================================================

    hp: Mapped[int] = mapped_column(
        nullable=False,
        default=500,
        doc="Current health points",
    )

    max_hp: Mapped[int] = mapped_column(
        nullable=False,
        default=500,
        doc="Maximum health points",
    )

    # ========================================================================
    # DROP CHARGES
    # ========================================================================

    drop_charges: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        doc="Current drop charges available",
    )

    max_drop_charges: Mapped[int] = mapped_column(
        nullable=False,
        default=1,
        doc="Maximum drop charge capacity",
    )

    last_drop_regen: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp of last drop charge regeneration",
    )

    # ========================================================================
    # COMBAT POWER AGGREGATES
    # ========================================================================

    total_attack: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        doc="Aggregate attack power from all maidens",
    )

    total_defense: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        doc="Aggregate defense power from all maidens",
    )

    total_power: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        index=True,
        doc="Total combat power (attack + defense)",
    )

    # ========================================================================
    # STAT ALLOCATION TRACKING
    # ========================================================================

    stat_points_spent: Mapped[Dict[str, int]] = mapped_column(
        JSON,
        nullable=False,
        default=_default_stat_points_spent,
        doc="Tracker for stat points allocated to each resource type",
    )

    # ========================================================================
    # BATTLE & ACTIVITY STATISTICS
    # ========================================================================

    stats: Mapped[Dict[str, int]] = mapped_column(
        JSON,
        nullable=False,
        default=_default_stats,
        doc="Comprehensive battle and activity statistics",
    )

    # ========================================================================
    # STATE & METADATA
    # ========================================================================

    state: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
        doc="Flexible state storage for stats-related data",
    )

    # ========================================================================
    # RELATIONSHIPS
    # ========================================================================

    player: Mapped["PlayerCore"] = relationship(
        "PlayerCore",
        back_populates="stats",
        doc="Reference to player core data",
    )
