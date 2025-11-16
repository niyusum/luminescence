"""
LeaderboardSnapshot — cached leaderboard snapshots per category.
Schema only (LUMEN LAW 2025).
"""

from __future__ import annotations

from sqlalchemy import BigInteger, String, Integer, Index, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database.base import Base, IdMixin, TimestampMixin
from ..enums import LeaderboardCategory


class LeaderboardSnapshot(Base, IdMixin, TimestampMixin):
    """
    Snapshot of leaderboard position for a player & category.
    """

    __tablename__ = "leaderboard_snapshots"
    __table_args__ = (
        Index("ix_leaderboard_category_rank", "category", "rank"),
        Index("ix_leaderboard_player", "player_id"),
        Index("ix_leaderboard_updated", "updated_at"),
    )

    player_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("player_core.discord_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    username: Mapped[str] = mapped_column(String(100), nullable=False)

    category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    rank: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    rank_change: Mapped[int] = mapped_column(default=0)
    value: Mapped[int] = mapped_column(BigInteger, nullable=False)

    snapshot_version: Mapped[int] = mapped_column(default=1)
