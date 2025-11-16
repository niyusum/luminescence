"""
PlayerShrine — personal passive-yield shrine.
Pure schema only (LUMEN LAW 2025).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database.base import Base, IdMixin, SoftDeleteMixin, TimestampMixin
from ..enums import ShrineType


class PlayerShrine(Base, IdMixin, TimestampMixin, SoftDeleteMixin):
    """
    Player-owned shrine instance.

    Schema-only:
    - player_id
    - shrine_type
    - slot
    - level
    - is_active
    - last_collected_at
    - yield_history
    - metadata
    """

    __tablename__ = "player_shrines"
    __table_args__ = (
        UniqueConstraint("player_id", "shrine_type", "slot", name="uq_player_shrine_slot"),
        Index("ix_player_shrines_player_id", "player_id"),
        Index("ix_player_shrines_type", "shrine_type"),
        Index("ix_player_shrines_active", "is_active"),
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

    shrine_type: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        index=True,
    )

    slot: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
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

    metadata: Mapped[Dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )

