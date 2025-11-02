from __future__ import annotations

from datetime import datetime
from typing import Optional, List, Dict, Any

from sqlmodel import SQLModel, Field, Column
from sqlalchemy import BigInteger, String, Integer, DateTime, Boolean, Index, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB


class PlayerShrine(SQLModel, table=True):
    """
    Player-owned Shrine (personal passive-yield structure).

    RIKI LAW:
      - Pure schema (no business logic here).
      - Indexed for hot paths (player lookups, type filtering).
      - JSONB ring buffer for quick UI history without heavy joins.

    Uniqueness:
      A player can own up to N shrines *per type*, tracked by `slot`.
      (N is config-driven: `shrines.<type>.max_shrines`)

    Fields:
      player_id: Discord/user PK (BigInt) — owner of the shrine
      shrine_type: e.g. 'lesser', 'radiant' (defined by ConfigManager)
      slot: 1..N (multiple shrines of same type)
      level: upgrade level (>=1)
      last_collected_at: UTC timestamp for cooldown gating (nullable = never collected)
      is_active: soft-delete / resale marker
      yield_history: [{'ts': iso, 'amount': int}] last 10 entries for UI
      metadata: free-form (e.g., cosmetics, counters)
    """
    __tablename__ = "player_shrines"
    __table_args__ = (
        UniqueConstraint("player_id", "shrine_type", "slot", name="uq_player_shrine_slot"),
        Index("ix_player_shrines_player_id", "player_id"),
        Index("ix_player_shrines_type", "shrine_type"),
        Index("ix_player_shrines_active", "is_active"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)

    player_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    shrine_type: str = Field(sa_column=Column(String(24), nullable=False))
    slot: int = Field(default=1, sa_column=Column(Integer, nullable=False))

    level: int = Field(default=1)
    last_collected_at: Optional[datetime] = Field(default=None)
    is_active: bool = Field(default=True, sa_column=Column(Boolean, nullable=False))

    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )

    yield_history: List[Dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSONB, nullable=False))
    metadata: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))

    # -------- Convenience (non-mutating) --------
    def __repr__(self) -> str:
        return f"<PlayerShrine(player={self.player_id}, type={self.shrine_type}, slot={self.slot}, lvl={self.level})>"
