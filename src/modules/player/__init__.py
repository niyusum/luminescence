"""
Player Module - LES 2025 Compliant Services
============================================

This module provides all player-related services following the Lumen Engineering
Standard (LES) 2025.

Services
--------
- PlayerRegistrationService: Atomic player registration (orchestrates all components)
- PlayerCoreService: Player identity and collection metadata
- PlayerProgressionService: Leveling, XP, class, milestones, fusion/gacha tracking
- PlayerStatsService: Resource pools, combat stats, battle statistics
- PlayerCurrenciesService: Economic resources and fusion shards
- PlayerActivityService: Activity tracking, cooldowns, daily counters

All services are transaction-safe, config-driven, and event-driven.
"""

from .activity_service import PlayerActivityService
from .core_service import PlayerCoreService
from .currencies_service import PlayerCurrenciesService
from .progression_service import PlayerProgressionService
from .registration_service import PlayerRegistrationService
from .stats_service import PlayerStatsService

__all__ = [
    "PlayerRegistrationService",
    "PlayerCoreService",
    "PlayerProgressionService",
    "PlayerStatsService",
    "PlayerCurrenciesService",
    "PlayerActivityService",
]
