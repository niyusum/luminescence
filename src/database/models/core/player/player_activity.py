"""
Player Activity Model
======================

Activity tracking and engagement metrics for players.

Schema-only representation of:
- Last active timestamp
- Daily activity counters
- Cooldown tracking
- Engagement metrics

All behavior and game rules live in service/domain layers.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database.base import Base, IdMixin

if TYPE_CHECKING:
    from .player_core import PlayerCore


class PlayerActivity(Base, IdMixin):
    """
    Player activity and engagement tracking.

    Tracks when the player was last active and other engagement-related
    metrics that help drive retention and activity-based features.
    """

    # ========================================================================
    # TABLE CONFIGURATION
    # ========================================================================

    __tablename__ = "player_activity"
    __table_args__ = (
        Index("ix_player_activity_player_id", "player_id", unique=True),
        Index("ix_player_activity_last_active", "last_active"),
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
    # ACTIVITY TRACKING
    # ========================================================================

    last_active: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
        doc="Timestamp of most recent player activity",
    )

    # ========================================================================
    # STATE & METADATA
    # ========================================================================

    state: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
        doc="Flexible state storage for activity-related data (cooldowns, daily counters, etc.)",
    )

    # ========================================================================
    # RELATIONSHIPS
    # ========================================================================

    player: Mapped["PlayerCore"] = relationship(
        "PlayerCore",
        back_populates="activity",
        doc="Reference to player core data",
    )
