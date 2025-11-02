from __future__ import annotations
from datetime import datetime
from typing import TYPE_CHECKING, Optional
from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import Index

if TYPE_CHECKING:
    from src.database.models.social.guild import Guild


class GuildMember(SQLModel, table=True):
    """
    Guild membership record linking players to guilds.

    RIKI LAW Compliance:
        - Relationship-safe association table
        - All joins indexed for performance
    """
    __tablename__ = "guild_members"
    __table_args__ = (
        Index("ix_guild_members_guild_id", "guild_id"),
        Index("ix_guild_members_player_id", "player_id"),
        # Composite index for guild rankings
        Index("ix_guild_members_guild_contribution", "guild_id", "contribution"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    guild_id: int = Field(foreign_key="guilds.id", index=True)
    player_id: int = Field(index=True)
    role: str = Field(default="member")  # leader, officer, member
    joined_at: datetime = Field(default_factory=datetime.utcnow)
    contribution: int = Field(default=0)

    guild: Optional["Guild"] = Relationship(back_populates="members")
