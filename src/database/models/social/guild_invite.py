from __future__ import annotations
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional

from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import Boolean, DateTime, func

if TYPE_CHECKING:
    from src.database.models.social.guild import Guild


class GuildInvite(SQLModel, table=True):
    """
    Persistent guild invitation model.

    LUMEN LAW Compliance:
        - De-duplication via unique (guild_id, target_player_id)
        - Lifecycle control via `active` flag
        - Expiry timestamps for auto-clean tasks
    """
    __tablename__ = "guild_invites"

    id: Optional[int] = Field(default=None, primary_key=True)
    guild_id: int = Field(foreign_key="guilds.id", index=True)
    inviter_player_id: int = Field(index=True)
    target_player_id: int = Field(index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: datetime = Field(default_factory=lambda: datetime.utcnow() + timedelta(days=3))
    active: bool = Field(default=True)

    guild: Optional["Guild"] = Relationship(back_populates="invites")

    def revoke(self):
        """Mark invite as inactive."""
        self.active = False

    def is_expired(self) -> bool:
        """Return True if invite has passed expiry."""
        return not self.active or (self.expires_at and self.expires_at < datetime.utcnow())

    def __repr__(self):
        return f"<GuildInvite guild={self.guild_id} target={self.target_player_id} active={self.active}>"
