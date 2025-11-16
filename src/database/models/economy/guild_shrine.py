"""
GuildShrine — guild-wide shrine structure for yield generation.
Pure schema only (LUMEN LAW 2025).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database.base import Base, IdMixin, SoftDeleteMixin, TimestampMixin
from ..enums import ShrineType


class GuildShrine(Base, IdMixin, TimestampMixin, SoftDeleteMixin):
    """
    Cooperative guild shrine used for collective passive yield generation.

    Schema-only:
    - guild_id: guild foreign reference
    - shrine_type: e.g. 'lesser', 'radiant'
    - level: upgrade level
    - is_active: soft lifecycle toggle
    - last_collected_at: cooldown timestamp
    - yield_history: JSONB ring buffer (list[dict])
    """

    __tablename__ = "guild_shrines"
    __table_args__ = (
        UniqueConstraint("guild_id", "shrine_type", name="uq_guild_shrine_unique"),
        Index("ix_guild_shrines_guild_id", "guild_id"),
        Index("ix_guild_shrines_type", "shrine_type"),
        Index("ix_guild_shrines_active", "is_active"),
    )

    guild_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("guilds.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    version: Mapped[int] = mapped_column(
        nullable=False,
        default=1,
        doc="Optimistic locking version",
    )

    shrine_type: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        index=True,
    )

    level: Mapped[int] = mapped_column(
        nullable=False,
        default=1,
    )

    last_collected_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        index=True,
    )

    yield_history: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
    )
