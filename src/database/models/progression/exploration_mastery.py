"""
ExplorationMastery — 3-rank mastery progression for exploration sectors.
Schema only (LUMEN LAW 2025).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Integer, Boolean, Index, UniqueConstraint, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database.base import Base, IdMixin, TimestampMixin


class ExplorationMastery(Base, IdMixin, TimestampMixin):
    """
    Player mastery ranks (1–3) for a given sector.
    """

    __tablename__ = "exploration_mastery"
    __table_args__ = (
        UniqueConstraint("player_id", "sector_id", name="uq_player_sector_exploration_mastery"),
        Index("ix_exploration_mastery_player", "player_id"),
        Index("ix_exploration_mastery_sector", "sector_id"),
        Index("ix_exploration_mastery_rank1", "rank_1_complete"),
        Index("ix_exploration_mastery_rank2", "rank_2_complete"),
        Index("ix_exploration_mastery_rank3", "rank_3_complete"),
    )

    player_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("player_core.discord_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    version: Mapped[int] = mapped_column(
        nullable=False,
        default=1,
        doc="Optimistic locking version",
    )

    sector_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    rank_1_complete: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    rank_2_complete: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    rank_3_complete: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    rank_1_completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    rank_2_completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    rank_3_completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    meta: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
        doc="Flexible metadata storage for mastery-specific data",
    )
