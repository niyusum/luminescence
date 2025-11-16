"""
Token — player token inventory for redemption.
Pure schema; no business logic.
"""

from __future__ import annotations

from datetime import datetime
from sqlalchemy import BigInteger, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database.base import Base, IdMixin, TimestampMixin


class Token(Base, IdMixin, TimestampMixin):
    """
    Player token inventory.

    Tokens redeem for maidens (tier-based). Pure schema definition.
    """

    __tablename__ = "tokens"
    __table_args__ = (
        UniqueConstraint("player_id", "token_type", name="uq_player_token_type"),
    )

    player_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("player_core.discord_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    token_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )

    quantity: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
    )
