"""
CombatEncounter — stores encounter state for resumption/replay.
Schema only (LUMEN LAW 2025).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database.base import Base, TimestampMixin


class CombatEncounter(Base, TimestampMixin):
    """
    Combat encounter state persistence.

    Schema-only:
    - encounter_id (UUID primary key)
    - player_id (for queries)
    - encounter_type (ascension, pvp, pve)
    - encounter_data (full JSON serialized encounter)
    - resolved_at (null if ongoing)
    - expires_at (TTL for cleanup)

    Purpose:
    - Allow mid-battle save/resume
    - Store combat logs for replay
    - Support async combat (future)

    TTL:
    - Unresolved encounters expire after 1 hour
    - Resolved encounters expire after 24 hours
    """

    __tablename__ = "combat_encounters"
    __table_args__ = (
        Index("ix_combat_encounters_player_id", "player_id"),
        Index("ix_combat_encounters_type", "encounter_type"),
        Index("ix_combat_encounters_resolved", "resolved_at"),
        Index("ix_combat_encounters_expires", "expires_at"),
        Index("ix_combat_encounters_player_unresolved", "player_id", "resolved_at"),
    )

    # Primary key is encounter_id (UUID)
    encounter_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        nullable=False,
    )

    player_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        index=True,
        doc="Player discord ID for queries",
    )

    encounter_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
        doc="Combat type: ascension, pvp, pve, world_boss",
    )

    # Serialized encounter data (from Encounter.to_dict())
    encounter_data: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        doc="Full encounter state serialized as JSON",
    )

    # Resolution tracking
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        index=True,
        doc="When combat was resolved (null if ongoing)",
    )

    # TTL for cleanup
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        doc="Expiration time for cleanup",
    )

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"<CombatEncounter("
            f"id={self.encounter_id}, "
            f"player={self.player_id}, "
            f"type={self.encounter_type}, "
            f"resolved={self.resolved_at is not None}"
            f")>"
        )
