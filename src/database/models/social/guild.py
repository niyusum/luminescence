from __future__ import annotations
from typing import TYPE_CHECKING, Optional, Dict, Any, List
from datetime import datetime
from sqlmodel import SQLModel, Field, Relationship, Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import Boolean, String, Integer, DateTime, Index, func

if TYPE_CHECKING:
    from src.database.models.social.guild_member import GuildMember
    from src.database.models.social.guild_invite import GuildInvite
    from src.database.models.social.guild_audit import GuildAudit


class Guild(SQLModel, table=True):
    """
    Guild (social organization) model.
    
    Represents a player-created guild with treasury, upgrades,
    and community functionality. Fully RIKI LAW compliant:
    - No logic here; schema-only
    - Indexed for performance and query speed
    - JSONB fields for flexible perks and audit history
    """
    __tablename__ = "guilds"
    __table_args__ = (
        Index("ix_guilds_name", "name", unique=True),
        Index("ix_guilds_owner_id", "owner_id"),
        Index("ix_guilds_level", "level"),
        Index("ix_guilds_treasury", "treasury"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True, nullable=False)
    owner_id: int = Field(index=True, nullable=False)
    description: Optional[str] = Field(default="A new guild begins.", max_length=250)
    emblem_url: Optional[str] = Field(default=None, max_length=512)
    is_active: bool = Field(default=True)

    level: int = Field(default=1)
    experience: int = Field(default=0)
    treasury: int = Field(default=0, ge=0)

    member_count: int = Field(default=1, ge=0)
    max_members: int = Field(default=10, ge=1)

    perks: Dict[str, int] = Field(
        default_factory=lambda: {"xp_boost": 0, "income_boost": 0},
        sa_column=Column(JSONB, nullable=False),
    )
    activity_log: List[Dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSONB, nullable=False)
    )

    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    )

    members: List["GuildMember"] = Relationship(back_populates="guild")
    invites: List["GuildInvite"] = Relationship(back_populates="guild")
    audits: List["GuildAudit"] = Relationship(back_populates="guild")

    def add_activity(self, action: str, user: str, meta: Optional[Dict[str, Any]] = None) -> None:
        """
        Append activity entry (capped at 25).
        """
        item = {
            "ts": datetime.utcnow().isoformat(),
            "user": user,
            "action": action,
        }
        if meta:
            item["meta"] = meta
        self.activity_log.insert(0, item)
        if len(self.activity_log) > 25:
            del self.activity_log[25:]

    def __repr__(self) -> str:
        return f"<Guild name={self.name!r} lvl={self.level} members={self.member_count}>"


