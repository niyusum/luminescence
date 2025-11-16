"""
Player Currencies Model
========================

All economy-related currencies and counters for players.

Schema-only representation of:
- Primary currencies (lumees, lumenite, auric_coin)
- Fusion shards by tier (JSON)
- Token and premium currency tracking

All behavior and game rules live in service/domain layers.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Dict, Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSON, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database.base import Base, IdMixin

if TYPE_CHECKING:
    from .player_core import PlayerCore


def _default_fusion_shards() -> Dict[str, int]:
    """Default fusion shard tracker for all tiers."""
    return {
        "tier_1": 0,
        "tier_2": 0,
        "tier_3": 0,
        "tier_4": 0,
        "tier_5": 0,
        "tier_6": 0,
        "tier_7": 0,
        "tier_8": 0,
        "tier_9": 0,
        "tier_10": 0,
        "tier_11": 0,
    }


class PlayerCurrencies(Base, IdMixin):
    """
    Player currencies and economy tracking.

    Tracks all economic resources: primary currencies (lumees, lumenite),
    premium currency (auric_coin), and fusion shards organized by tier.
    """

    # ========================================================================
    # TABLE CONFIGURATION
    # ========================================================================

    __tablename__ = "player_currencies"
    __table_args__ = (
        Index("ix_player_currencies_player_id", "player_id", unique=True),
        Index("ix_player_currencies_lumees", "lumees"),
    )

    # ========================================================================
    # PRIMARY KEY & FOREIGN KEY
    # ========================================================================

    player_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("player_core.discord_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
        doc="Reference to player core identity",
    )

    version: Mapped[int] = mapped_column(
        nullable=False,
        default=1,
        doc="Optimistic locking version for concurrent updates",
    )

    # ========================================================================
    # PRIMARY CURRENCIES
    # ========================================================================

    lumees: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=1000,
        doc="Primary soft currency for the game",
    )

    lumenite: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        doc="Premium crafting and upgrade currency",
    )

    auric_coin: Mapped[int] = mapped_column(
        nullable=False,
        default=5,
        doc="Premium gacha currency (tokens)",
    )

    # ========================================================================
    # DROP CHARGES
    # ========================================================================

    drop_charges: Mapped[int] = mapped_column(
        nullable=False,
        default=3,
        doc="Available drop charges for executing drops",
    )

    last_drop_charge_update: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        doc="Last time drop charges were updated (for regeneration)",
    )

    # ========================================================================
    # FUSION SHARDS
    # ========================================================================

    shards: Mapped[Dict[str, int]] = mapped_column(
        JSON,
        nullable=False,
        default=_default_fusion_shards,
        doc="Fusion shards organized by tier (tier_1 through tier_11)",
    )

    # ========================================================================
    # STATE & METADATA
    # ========================================================================

    state: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
        doc="Flexible state storage for currency-related data",
    )

    # ========================================================================
    # RELATIONSHIPS
    # ========================================================================

    player: Mapped["PlayerCore"] = relationship(
        "PlayerCore",
        back_populates="currencies",
        doc="Reference to player core data",
    )
