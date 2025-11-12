from __future__ import annotations
from datetime import datetime
from typing import Optional, Dict, Any, List

from sqlmodel import SQLModel, Field, Column
from sqlalchemy import Integer, BigInteger, String, DateTime, Index, UniqueConstraint, func, Boolean
from sqlalchemy.dialects.postgresql import JSONB


class GuildShrine(SQLModel, table=True):
    """
    Cooperative guild-wide shrine for collective yield generation.

    LUMEN LAW:
      - Immutable historical yield log (ring buffer, size 25)
      - Atomic upgrade and collection transactions (handled in service)
      - Treasury integration: shrine yields flow to guild treasury
      - Config-driven: shrine type behavior defined in ConfigManager

    Fields:
      guild_id: owning guild FK
      shrine_type: e.g. 'lesser', 'radiant'
      level: current shrine level
      last_collected_at: UTC timestamp for cooldown enforcement
      is_active: lifecycle toggle (soft delete)
      yield_history: JSONB ring buffer of past yields
      created_at / updated_at: server-managed timestamps
    """

    __tablename__ = "guild_shrines"
    __table_args__ = (
        UniqueConstraint("guild_id", "shrine_type", name="uq_guild_shrine_unique"),
        Index("ix_guild_shrines_guild_id", "guild_id"),
        Index("ix_guild_shrines_type", "shrine_type"),
        Index("ix_guild_shrines_active", "is_active"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    guild_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    shrine_type: str = Field(sa_column=Column(String(24), nullable=False))
    level: int = Field(default=1)
    last_collected_at: Optional[datetime] = Field(default=None)
    is_active: bool = Field(default=True, sa_column=Column(Boolean, nullable=False))

    yield_history: List[Dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSONB, nullable=False))
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )

    def __repr__(self) -> str:
        return f"<GuildShrine(guild={self.guild_id}, type={self.shrine_type}, lvl={self.level})>"
