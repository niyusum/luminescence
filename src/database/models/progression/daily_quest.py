"""
DailyQuest — daily quest state for each player.
Schema only (LUMEN LAW 2025).
"""

from __future__ import annotations

from datetime import datetime, date
from typing import Dict, Optional

from sqlalchemy import BigInteger, Date, Index, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database.base import Base, IdMixin, TimestampMixin


class DailyQuest(Base, IdMixin, TimestampMixin):
    """
    Daily quest tracking for players.
    One row per player per day.
    """

    __tablename__ = "daily_quests"
    __table_args__ = (
        Index("ix_daily_quests_player_date", "player_id", "quest_date"),
        Index("ix_daily_quests_completed_gin", "quests_completed", postgresql_using="gin"),
        Index("ix_daily_quests_progress_gin", "quest_progress", postgresql_using="gin"),
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

    quest_date: Mapped[date] = mapped_column(Date, nullable=False, index=True, default=date.today)

    quests_completed: Mapped[Dict[str, bool]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )

    quest_progress: Mapped[Dict[str, int]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )

    rewards_claimed: Mapped[bool] = mapped_column(Boolean, default=False)
    bonus_streak: Mapped[int] = mapped_column(default=0)
