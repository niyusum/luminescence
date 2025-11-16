"""
Player Models Package (DDD Structure)
======================================

Domain-driven design structure for player-related models.

This package contains the player domain split into logical components:

- PlayerCore: Identity, timestamps, relationships
- PlayerProgression: Levels, XP, milestones, class
- PlayerStats: Combat stats, resources, power aggregates
- PlayerCurrencies: All economic currencies and shards
- PlayerActivity: Activity tracking and engagement

All models are schema-only and follow LUMEN LAW (2025).
Business logic lives in service/domain layers.

Usage
-----
    from src.database.models.core.player import (
        PlayerCore,
        PlayerProgression,
        PlayerStats,
        PlayerCurrencies,
        PlayerActivity,
    )
"""

from .player_activity import PlayerActivity
from .player_core import PlayerCore
from .player_currencies import PlayerCurrencies
from .player_progression import PlayerProgression
from .player_stats import PlayerStats

__all__ = [
    "PlayerCore",
    "PlayerProgression",
    "PlayerStats",
    "PlayerCurrencies",
    "PlayerActivity",
]
