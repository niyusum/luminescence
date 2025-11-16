from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database.base import Base, IdMixin, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from .player import PlayerCore
    from .maiden_base import MaidenBase


class Maiden(Base, IdMixin, TimestampMixin, SoftDeleteMixin):
    """
    Player-owned maiden instance.

    Represents a stack of maidens of a specific (maiden_base, tier, element)
    owned by a single player.

    Fields (schema only):
    - player_id: Discord user ID of the owner (FK to player_core.discord_id)
    - maiden_base_id: FK to MaidenBase
    - quantity: stack count of this base-tier combination
    - tier: upgrade level (1-12)
    - element: elemental affinity string
    - created_at / updated_at: audit timestamps (from TimestampMixin)
    - acquired_from: acquisition source label
    - times_fused: how many times this maiden has been used in fusion
    - is_locked: prevents accidental use in fusion / consumption
    - deleted_at: soft-delete support (from SoftDeleteMixin)
    """

    __tablename__ = "maidens"
    __table_args__ = (
        UniqueConstraint(
            "player_id",
            "maiden_base_id",
            "tier",
            name="uq_player_maiden_tier",
        ),
        Index("ix_maidens_player_id", "player_id"),
        Index("ix_maidens_base_id", "maiden_base_id"),
        Index("ix_maidens_tier", "tier"),
        Index("ix_maidens_element", "element"),
        Index("ix_maidens_fusable", "player_id", "tier", "quantity"),
    )

    # Ownership / base linkage
    player_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("player_core.discord_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    maiden_base_id: Mapped[int] = mapped_column(
        ForeignKey("maiden_bases.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # Stack + progression
    quantity: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=1,
    )

    tier: Mapped[int] = mapped_column(
        nullable=False,
        default=1,
    )

    element: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
    )

    # Acquisition metadata
    acquired_from: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="summon",
    )

    times_fused: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
    )

    is_locked: Mapped[bool] = mapped_column(
        nullable=False,
        default=False,
    )

    # Relationships
    player: Mapped["PlayerCore"] = relationship(
        "PlayerCore",
        back_populates="maidens",
        primaryjoin="Maiden.player_id == PlayerCore.discord_id",
        foreign_keys="Maiden.player_id",
    )

    maiden_base: Mapped["MaidenBase"] = relationship(
        "MaidenBase",
        back_populates="maidens",
    )
