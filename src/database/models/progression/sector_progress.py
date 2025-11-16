"""
SectorProgress — sublevel progress tracking.
Schema only (LUMEN LAW 2025).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Float, Boolean, Integer, DateTime, Index, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database.base import Base, IdMixin, TimestampMixin


class SectorProgress(Base, IdMixin, TimestampMixin):
    """
    Player progress for a sector + sublevel.
    """

    __tablename__ = "sector_progress"
    __table_args__ = (
        Index("ix_sector_progress_player_sector_sublevel", "player_id", "sector_id", "sublevel", unique=True),
        Index("ix_sector_progress_player", "player_id"),
        Index("ix_sector_progress_last_explored", "last_explored"),
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
    sublevel: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    progress: Mapped[float] = mapped_column(Float, default=0.0)
    miniboss_defeated: Mapped[bool] = mapped_column(Boolean, default=False)

    times_explored: Mapped[int] = mapped_column(default=0)
    total_lumees_earned: Mapped[int] = mapped_column(BigInteger, default=0)
    total_xp_earned: Mapped[int] = mapped_column(BigInteger, default=0)
    maidens_purified: Mapped[int] = mapped_column(default=0)

    last_explored: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    meta: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
        doc="Flexible metadata storage for sector-specific data",
    )
