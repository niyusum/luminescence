"""
Player Core Model
==================

Core identity and metadata for Discord users in Lumen RPG.

Schema-only representation of:
- Primary identity (discord_id as PK, username, discriminator)
- Timestamps (created_at, updated_at)
- Leader maiden relationship
- Collection metadata (total maidens, unique maidens)
- Relationships to all player-related models

All behavior and game rules live in service/domain layers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import BigInteger, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database.base import Base, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from ..maiden import Maiden
    from .player_activity import PlayerActivity
    from .player_currencies import PlayerCurrencies
    from .player_progression import PlayerProgression
    from .player_stats import PlayerStats


class PlayerCore(Base, TimestampMixin, SoftDeleteMixin):
    """
    Core player identity and metadata.

    This is the central player entity that all other player-related models
    reference. Uses discord_id as the primary key for efficient lookups
    and direct relationship mapping.
    """

    # ========================================================================
    # TABLE CONFIGURATION
    # ========================================================================

    __tablename__ = "player_core"
    __table_args__ = (
        Index("ix_player_core_discord_id", "discord_id", unique=True),
        Index("ix_player_core_username", "username"),
    )

    # ========================================================================
    # PRIMARY KEY & IDENTITY
    # ========================================================================

    discord_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        nullable=False,
        doc="Discord user ID (primary key)",
    )

    version: Mapped[int] = mapped_column(
        nullable=False,
        default=1,
        doc="Optimistic locking version for concurrent updates",
    )

    username: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="Unknown",
        doc="Discord username",
    )

    discriminator: Mapped[Optional[str]] = mapped_column(
        String(10),
        nullable=True,
        default=None,
        doc="Discord discriminator (legacy, optional)",
    )

    # ========================================================================
    # COLLECTION METADATA
    # ========================================================================

    leader_maiden_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("maidens.id", ondelete="SET NULL"),
        nullable=True,
        doc="Currently selected leader maiden",
    )

    total_maidens_owned: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        doc="Total number of maidens owned (including duplicates)",
    )

    unique_maidens: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        doc="Number of unique maiden types collected",
    )

    # ========================================================================
    # RELATIONSHIPS
    # ========================================================================

    # Maiden relationships
    maidens: Mapped[List["Maiden"]] = relationship(
        "Maiden",
        back_populates="player",
        primaryjoin="PlayerCore.discord_id == Maiden.player_id",
        foreign_keys="Maiden.player_id",
        lazy="selectin",
        doc="All maidens owned by this player",
    )

    leader_maiden: Mapped[Optional["Maiden"]] = relationship(
        "Maiden",
        foreign_keys="PlayerCore.leader_maiden_id",
        lazy="joined",
        doc="The currently selected leader maiden",
    )

    # Player component relationships (one-to-one)
    progression: Mapped[Optional["PlayerProgression"]] = relationship(
        "PlayerProgression",
        back_populates="player",
        uselist=False,
        lazy="joined",
        doc="Player progression data (level, xp, etc.)",
    )

    stats: Mapped[Optional["PlayerStats"]] = relationship(
        "PlayerStats",
        back_populates="player",
        uselist=False,
        lazy="joined",
        doc="Player combat stats and resources",
    )

    currencies: Mapped[Optional["PlayerCurrencies"]] = relationship(
        "PlayerCurrencies",
        back_populates="player",
        uselist=False,
        lazy="joined",
        doc="Player currencies and economy data",
    )

    activity: Mapped[Optional["PlayerActivity"]] = relationship(
        "PlayerActivity",
        back_populates="player",
        uselist=False,
        lazy="joined",
        doc="Player activity and engagement tracking",
    )
