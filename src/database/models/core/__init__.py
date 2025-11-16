"""
Core database models for the Lumen RPG system.

This package exports the foundational ORM models used across the system:
- Player models (DDD structure):
  - PlayerCore
  - PlayerProgression
  - PlayerStats
  - PlayerCurrencies
  - PlayerActivity
- Maiden
- MaidenBase
- GameConfig

All models follow LUMEN LAW (2025) and inherit from the shared SQLAlchemy Base.
"""

from src.core.database.base import Base

from .player import (
    PlayerActivity,
    PlayerCore,
    PlayerCurrencies,
    PlayerProgression,
    PlayerStats,
)
from .maiden import Maiden
from .maiden_base import MaidenBase
from .game_config import GameConfig

__all__ = [
    "Base",
    "PlayerCore",
    "PlayerProgression",
    "PlayerStats",
    "PlayerCurrencies",
    "PlayerActivity",
    "Maiden",
    "MaidenBase",
    "GameConfig",
]

