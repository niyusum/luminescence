"""
Lumen RPG Core Constants

Purpose
-------
Provide a centralized, typed collection of core constants for the Lumen RPG
engine. These values exist to eliminate "magic numbers" spread across the
codebase and to define true engine-level invariants.

IMPORTANT:
For *tunable* game-balance values (costs, rewards, rates, timers, limits),
ConfigManager should be the primary source of truth. This module serves as
a home for:
- Hard invariants (e.g., maximum tier)
- Engine defaults that ConfigManager may override at runtime
- Infra-level limits (timeouts, health thresholds) that are rarely changed

LUMEN LAW / LES 2025 Compliance
-------------------------------
- Article 1.4 (Config-Driven Game Balance):
  - These constants are treated as defaults and invariants.
  - Game-balance tuning should flow through ConfigManager.
- No Discord dependencies; pure data only.
- No side effects at import time.

Design Notes
------------
- Values are annotated with typing.Final where appropriate to signal they are
  intended as constants.
- Grouped by functional area (stats, leveling, fusion, drop system, etc.) to
  make scanning and maintenance easier.
"""

from __future__ import annotations

from typing import Final

# ============================================================================
# PLAYER CLASS BONUSES
# ============================================================================

CLASS_DESTROYER_STAMINA_BONUS: Final[float] = 0.75  # 25% faster stamina regen (multiplier)
CLASS_ADAPTER_ENERGY_BONUS: Final[float] = 0.75  # 25% faster energy regen (multiplier)
CLASS_INVOKER_SHRINE_BONUS: Final[float] = 1.25  # 25% bonus shrine rewards (multiplier)

# ============================================================================
# STAT ALLOCATION
# ============================================================================

MAX_POINTS_PER_STAT: Final[int] = 999  # Maximum points that can be allocated to single stat
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

MAX_LEVEL_UPS_PER_TRANSACTION: Final[int] = 10  # Safety cap to prevent infinite loops
MINOR_MILESTONE_INTERVAL: Final[int] = 5  # Every 5 levels
MAJOR_MILESTONE_INTERVAL: Final[int] = 10  # Every 10 levels

# Overcap bonuses
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
# DATABASE & PERFORMANCE
# ============================================================================

DEFAULT_QUERY_TIMEOUT_MS: Final[int] = 30_000  # 30 seconds
DATABASE_HEALTH_CHECK_TIMEOUT_MS: Final[int] = 5_000  # 5 seconds
DATABASE_HEALTH_DEGRADED_THRESHOLD_MS: Final[int] = 100  # 100ms = degraded
DATABASE_HEALTH_UNHEALTHY_THRESHOLD_MS: Final[int] = 1_000  # 1s = unhealthy

# Connection pool limits (per instance)
DEFAULT_POOL_SIZE: Final[int] = 20
DEFAULT_MAX_OVERFLOW: Final[int] = 10
MAX_TOTAL_CONNECTIONS: Final[int] = 30  # pool_size + max_overflow

# ============================================================================
# RATE LIMITING
# ============================================================================

CIRCUIT_BREAKER_FAILURE_THRESHOLD: Final[int] = 5  # Failures before opening circuit
CIRCUIT_BREAKER_RECOVERY_SECONDS: Final[int] = 60  # Wait before retry
FUSION_LOCK_TIMEOUT_SECONDS: Final[int] = 10  # Max time to hold fusion lock
FUSION_LOCK_BLOCKING_TIMEOUT_SECONDS: Final[int] = 2  # Wait to acquire lock

# ============================================================================
# DISCORD EMBED LIMITS
# ============================================================================

DISCORD_EMBED_FIELD_LIMIT: Final[int] = 1_024  # Max characters per field
DISCORD_EMBED_DESCRIPTION_LIMIT: Final[int] = 4_096  # Max characters in description
DISCORD_EMBED_TITLE_LIMIT: Final[int] = 256  # Max characters in title
DISCORD_EMBED_FOOTER_LIMIT: Final[int] = 2_048  # Max characters in footer

# ============================================================================
# LOGGING & METRICS
# ============================================================================

LOG_ROTATION_SIZE_MB: Final[int] = 10  # Rotate logs at 10MB
LOG_RETENTION_DAYS: Final[int] = 30  # Keep logs for 30 days
METRICS_AGGREGATION_WINDOW_SECONDS: Final[int] = 60  # Aggregate metrics every minute

# ============================================================================
# CACHE TTL (Time To Live) in seconds
# ============================================================================

CACHE_TTL_SHORT: Final[int] = 60  # 1 minute
CACHE_TTL_MEDIUM: Final[int] = 300  # 5 minutes
CACHE_TTL_LONG: Final[int] = 1_800  # 30 minutes
CACHE_TTL_VERY_LONG: Final[int] = 3_600  # 1 hour

# ============================================================================
# VALIDATION LIMITS
# ============================================================================

MAX_USERNAME_LENGTH: Final[int] = 100
MAX_COMMAND_NAME_LENGTH: Final[int] = 50
MAX_TRANSACTION_CONTEXT_LENGTH: Final[int] = 255
MIN_PLAYER_LEVEL: Final[int] = 1
MAX_TIER_NUMBER: Final[int] = 12

# ============================================================================
# EVENT SYSTEM
# ============================================================================

EVENT_PROCESSING_TIMEOUT_SECONDS: Final[int] = 30
MAX_EVENT_RETRIES: Final[int] = 3
EVENT_RETRY_DELAY_SECONDS: Final[int] = 5
