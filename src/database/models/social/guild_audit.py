"""
GuildAudit — immutable guild audit log.
Pure schema only (LUMEN LAW 2025).
"""

from __future__ import annotations

from typing import Optional, Dict, Any, TYPE_CHECKING

from sqlalchemy import BigInteger, Index, String, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database.base import Base, IdMixin, TimestampMixin

if TYPE_CHECKING:
    from .guild import Guild


class GuildAudit(Base, IdMixin, TimestampMixin):
    """
    Durable audit trail for guild actions.

    Schema-only:
    - guild_id (FK to guilds)
    - actor_player_id (FK to player_core.discord_id, nullable for system actions)
    - action (type of guild action)
    - meta (JSONB for action details)
    - created_at (from TimestampMixin)

    Note: No SoftDeleteMixin - audit logs are immutable.
    """

    __tablename__ = "guild_audit"
    __table_args__ = (
        Index("ix_guild_audit_guild_created", "guild_id", "created_at"),
        Index("ix_guild_audit_meta_gin", "meta", postgresql_using="gin"),
    )

    guild_id: Mapped[int] = mapped_column(
        ForeignKey("guilds.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    actor_player_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("player_core.discord_id", ondelete="SET NULL"),
        index=True,
    )

    action: Mapped[str] = mapped_column(String(50), index=True)

    meta: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict)

    guild: Mapped["Guild"] = relationship("Guild", back_populates="audits")

