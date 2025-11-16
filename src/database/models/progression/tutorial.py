"""
TutorialProgress — onboarding tutorial tracking.
Schema only (LUMEN LAW 2025).
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database.base import Base, IdMixin, TimestampMixin


class TutorialProgress(Base, IdMixin, TimestampMixin):
    """
    Tutorial step & reward tracking for players.
    """

    __tablename__ = "tutorial_progress"
    __table_args__ = (
        Index("ix_tutorial_progress_steps_gin", "steps_completed", postgresql_using="gin"),
        Index("ix_tutorial_progress_rewards_gin", "rewards_claimed", postgresql_using="gin"),
    )

    player_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("player_core.discord_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    steps_completed: Mapped[Dict[str, bool]] = mapped_column(
        JSONB, nullable=False, default=dict
    )

    rewards_claimed: Mapped[Dict[str, bool]] = mapped_column(
        JSONB, nullable=False, default=dict
    )

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
