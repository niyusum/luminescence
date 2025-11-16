"""
GuildMember — association of players to guilds.
Pure schema only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, String, Integer, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database.base import Base, IdMixin, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from .guild import Guild


class GuildMember(Base, IdMixin, TimestampMixin, SoftDeleteMixin):
    """
    Guild membership row.

    Schema-only:
    - guild_id (FK to guilds)
    - player_id (FK to player_core.discord_id)
    - role (guild role string)
    - contribution (guild contribution points)
    - created_at / updated_at (from TimestampMixin)
    - deleted_at (from SoftDeleteMixin for membership history)
    """

    __tablename__ = "guild_members"
    __table_args__ = (
        Index("ix_guild_members_guild_id", "guild_id"),
        Index("ix_guild_members_player_id", "player_id"),
        Index("ix_guild_members_guild_contribution", "guild_id", "contribution"),
    )

    guild_id: Mapped[int] = mapped_column(
        ForeignKey("guilds.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
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

    role: Mapped[str] = mapped_column(String(20), default="member")

    contribution: Mapped[int] = mapped_column(Integer, default=0)

    guild: Mapped["Guild"] = relationship("Guild", back_populates="members")
