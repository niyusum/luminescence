"""
Guild — Social guild entity for players.
Pure schema (LUMEN LAW 2025).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TYPE_CHECKING
from datetime import datetime

from sqlalchemy import String, Integer, DateTime, Index, BigInteger, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database.base import Base, IdMixin, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from .guild_member import GuildMember
    from .guild_invite import GuildInvite
    from .guild_audit import GuildAudit


class Guild(Base, IdMixin, TimestampMixin, SoftDeleteMixin):
    """
    Player-created guild.

    Schema-only:
    - name, owner, description, emblem
    - level, xp, treasury
    - perks JSONB
    - activity_log JSONB
    - meta JSONB for extensibility
    """

    __tablename__ = "guilds"
    __table_args__ = (
        Index("ix_guilds_name", "name", unique=True),
        Index("ix_guilds_owner_id", "owner_id"),
        Index("ix_guilds_level", "level"),
        Index("ix_guilds_treasury", "treasury"),
        Index("ix_guilds_perks_gin", "perks", postgresql_using="gin"),
        Index("ix_guilds_activity_log_gin", "activity_log", postgresql_using="gin"),
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    owner_id: Mapped[int] = mapped_column(
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

    description: Mapped[Optional[str]] = mapped_column(String(250), default="A new guild begins.")
    emblem_url: Mapped[Optional[str]] = mapped_column(String(512), default=None)

    level: Mapped[int] = mapped_column(Integer, default=1)
    experience: Mapped[int] = mapped_column(Integer, default=0)
    treasury: Mapped[int] = mapped_column(Integer, default=0)

    member_count: Mapped[int] = mapped_column(Integer, default=1)
    max_members: Mapped[int] = mapped_column(Integer, default=10)

    perks: Mapped[Dict[str, int]] = mapped_column(JSONB, default=dict)
    activity_log: Mapped[List[Dict[str, Any]]] = mapped_column(JSONB, default=list)

    meta: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
        doc="Flexible metadata storage for guild-specific data",
    )

    # Relationships
    members: Mapped[List["GuildMember"]] = relationship(
        back_populates="guild",
        lazy="selectin",
    )
    invites: Mapped[List["GuildInvite"]] = relationship(
        back_populates="guild",
        lazy="selectin",
    )
    audits: Mapped[List["GuildAudit"]] = relationship(
        back_populates="guild",
        lazy="selectin",
    )

