from __future__ import annotations
from datetime import datetime
from typing import TYPE_CHECKING, Optional, Dict, Any

from sqlmodel import SQLModel, Field, Relationship, Column
from sqlalchemy.dialects.postgresql import JSONB

if TYPE_CHECKING:
    from src.database.models.social.guild import Guild


class GuildAudit(SQLModel, table=True):
    """
    Immutable guild audit log.

    RIKI LAW Compliance:
        - Serves as durable, queryable log
        - All write operations in services mirror here
        - Used for analytics, moderation, rollback reconstruction
    """
    __tablename__ = "guild_audit"

    id: Optional[int] = Field(default=None, primary_key=True)
    guild_id: int = Field(foreign_key="guilds.id", index=True)
    actor_player_id: Optional[int] = Field(default=None, index=True)  # None = system action
    action: str = Field(index=True)  # e.g. 'create', 'join', 'leave', 'upgrade', 'donate'
    meta: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONB))
    created_at: datetime = Field(default_factory=datetime.utcnow)

    guild: Optional["Guild"] = Relationship(back_populates="audits")

    def __repr__(self):
        return f"<GuildAudit guild={self.guild_id} action={self.action}>"
