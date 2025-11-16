"""
GuildInvite — persistent invitation to a guild.
Pure schema (LUMEN LAW 2025).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, BigInteger, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database.base import Base, IdMixin, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from .guild import Guild


class GuildInvite(Base, IdMixin, TimestampMixin, SoftDeleteMixin):
    """
    Guild invitation from one player to another.

    Schema-only:
    - guild_id (FK to guilds)
    - inviter_player_id (FK to player_core.discord_id)
    - target_player_id (FK to player_core.discord_id)
    - expires_at (invite expiration timestamp)
    - created_at / updated_at (from TimestampMixin)
    - deleted_at (from SoftDeleteMixin for soft-deletion)
    """

    __tablename__ = "guild_invites"
    __table_args__ = (
        Index("ix_guild_invites_guild_target", "guild_id", "target_player_id"),
        Index("ix_guild_invites_inviter", "inviter_player_id"),
    )

    guild_id: Mapped[int] = mapped_column(
        ForeignKey("guilds.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    inviter_player_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("player_core.discord_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    target_player_id: Mapped[int] = mapped_column(
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

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.utcnow() + timedelta(days=3),
        nullable=False,
    )

    guild: Mapped["Guild"] = relationship("Guild", back_populates="invites")
