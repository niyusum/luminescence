"""
Lumen RPG Domain Constants

Purpose
-------
Provide domain-level constants for game mechanics, balance, and gameplay rules.
These values define how the Lumen RPG system works from a player perspective:
class bonuses, stat allocation, leveling, fusion, drops, combat, and resource
regeneration.

IMPORTANT:
This module contains GAMEPLAY constants only. Infrastructure concerns (database
timeouts, cache TTLs, logging config) belong in src/core/constants.py.

LUMEN LAW / LES 2025 Compliance
-------------------------------
- Domain concerns only (game mechanics and balance)
- No infrastructure or technical limits
- No Discord dependencies; pure data only
- No side effects at import time

Design Notes
------------
- Values are annotated with typing.Final to signal immutability
- Grouped by game system (stats, leveling, fusion, etc.)
- These are currently hardcoded but could be migrated to ConfigManager
  for runtime tuning if needed
"""

from __future__ import annotations

from typing import Final

# ============================================================================
# PLAYER CLASS BONUSES
# ============================================================================

CLASS_DESTROYER_STAMINA_BONUS: Final[float] = 0.75  # 25% faster stamina regen
CLASS_ADAPTER_ENERGY_BONUS: Final[float] = 0.75  # 25% faster energy regen
CLASS_INVOKER_SHRINE_BONUS: Final[float] = 1.25  # 25% bonus shrine rewards

# ============================================================================
# STAT ALLOCATION
# ============================================================================

MAX_POINTS_PER_STAT: Final[int] = 999  # Maximum points in a single stat
POINTS_PER_LEVEL: Final[int] = 5  # Stat points granted per level up

# Base resource values (before stat allocation)
BASE_ENERGY: Final[int] = 100
BASE_STAMINA: Final[int] = 50
BASE_HP: Final[int] = 500

# Resource gains per stat point
ENERGY_PER_POINT: Final[int] = 10
STAMINA_PER_POINT: Final[int] = 5
HP_PER_POINT: Final[int] = 100

# ============================================================================
# LEVELING SYSTEM
# ============================================================================

MINOR_MILESTONE_INTERVAL: Final[int] = 5  # Every 5 levels
MAJOR_MILESTONE_INTERVAL: Final[int] = 10  # Every 10 levels

# Overcap bonuses (when leveling with full resources)
OVERCAP_THRESHOLD: Final[float] = 0.9  # Must be at 90%+ to get overcap bonus
OVERCAP_BONUS: Final[float] = 0.10  # 10% bonus resources on level up

# ============================================================================
# FUSION SYSTEM
# ============================================================================

MAX_FUSION_TIER: Final[int] = 12  # Cannot fuse tier 12+
FUSION_MAIDENS_REQUIRED: Final[int] = 2  # Always requires 2 maidens
SHARDS_FOR_GUARANTEED_FUSION: Final[int] = 100  # Shard redemption cost
MIN_SHARDS_PER_FAILURE: Final[int] = 1  # Minimum shards from failed fusion
MAX_SHARDS_PER_FAILURE: Final[int] = 12  # Maximum shards from failed fusion

# ============================================================================
# DROP SYSTEM
# ============================================================================

DROP_CHARGES_MAX: Final[int] = 1
DROP_REGEN_SECONDS: Final[int] = 300
DROP_REGEN_MINUTES: Final[int] = 5

# ============================================================================
# COMBAT & POWER
# ============================================================================

STRATEGIC_TEAM_SIZE: Final[int] = 6  # Best 6 maidens for strategic power
PITY_COUNTER_MAX: Final[int] = 90  # Guaranteed high-tier at 90 summons

# ============================================================================
# RESOURCE REGENERATION
# ============================================================================

ENERGY_REGEN_MINUTES: Final[int] = 5  # Base energy regen interval
STAMINA_REGEN_MINUTES: Final[int] = 10  # Base stamina regen interval

# ============================================================================
# VALIDATION RANGES
# ============================================================================

MIN_PLAYER_LEVEL: Final[int] = 1
MAX_TIER_NUMBER: Final[int] = 12  # Matches MAX_FUSION_TIER
