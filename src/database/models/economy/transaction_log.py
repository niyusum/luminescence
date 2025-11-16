"""
TransactionLog — economy audit log (immutable).
Pure schema only.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import BigInteger, Index, Text, String, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database.base import Base, IdMixin
from ..enums import TransactionType


class TransactionLog(Base, IdMixin):
    """
    Audit log for all significant player economy actions.

    Schema-only:
    - player_id
    - transaction_type
    - details (JSON)
    - context
    - timestamp
    """

    __tablename__ = "transaction_logs"
    __table_args__ = (
        Index("ix_transaction_logs_player_time", "player_id", "timestamp"),
        Index("ix_transaction_logs_type", "transaction_type"),
        Index("ix_transaction_logs_timestamp", "timestamp"),
    )

    player_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("player_core.discord_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    transaction_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )

    details: Mapped[Dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    context: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        index=True,
    )
