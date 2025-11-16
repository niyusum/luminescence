from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database.base import Base, IdMixin, TimestampMixin

class GameConfig(Base, IdMixin, TimestampMixin):
    """
    Dynamic game configuration stored in the database.

    Allows balance and system parameters to be tuned without redeploying the bot.
    Managed by ConfigManager at the service/infra layer.

    Schema-only model:
    - config_key: unique identifier for a configuration entry
    - config_value: arbitrary JSON payload containing configuration data
    - description: human-friendly description of the config entry
    - created_at / updated_at: timestamps from TimestampMixin
    - modified_by: identifier of the last modifier (e.g., username or id)
    """

    __tablename__ = "game_config"

    config_key: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
        index=True,
    )

    config_value: Mapped[Dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
    )

    description: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        default="",
    )

    modified_by: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )
