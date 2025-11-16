"""
AscensionProgress — tracks infinite tower progression.
Schema only (LUMEN LAW 2025).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Index, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database.base import Base, IdMixin, TimestampMixin


class AscensionProgress(Base, IdMixin, TimestampMixin):
    """
    Player ascension tower progression.

    Schema-only:
    - player_id
    - current_floor
    - highest_floor
    - lifetime stats (attempts, victories, defeats)
    - lifetime rewards (lumees, xp)
    """

    __tablename__ = "ascension_progress"
    __table_args__ = (
        Index("ix_ascension_progress_player", "player_id", unique=True),
        Index("ix_ascension_progress_highest_floor", "highest_floor"),
        Index("ix_ascension_progress_last_attempt", "last_attempt"),
    )

    player_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("player_core.discord_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    version: Mapped[int] = mapped_column(
        nullable=False,
        default=1,
        doc="Optimistic locking version",
    )

    current_floor: Mapped[int] = mapped_column(Integer, default=0)
    highest_floor: Mapped[int] = mapped_column(Integer, default=0, index=True)

    total_floors_cleared: Mapped[int] = mapped_column(default=0)
    total_attempts: Mapped[int] = mapped_column(default=0)
    total_victories: Mapped[int] = mapped_column(default=0)
    total_defeats: Mapped[int] = mapped_column(default=0)

    total_lumees_earned: Mapped[int] = mapped_column(BigInteger, default=0)
    total_xp_earned: Mapped[int] = mapped_column(BigInteger, default=0)

    last_attempt: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)
    last_victory: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
