"""
Lumen RPG Core Constants

Centralized constants file to eliminate magic numbers throughout the codebase.
Organized by functional area for easy maintenance.

LUMEN LAW Compliance:
- Article IV: All tunable values should be in ConfigManager
- This file contains immutable game constants that rarely change
"""

# ============================================================================
# PLAYER CLASS BONUSES
# ============================================================================

CLASS_DESTROYER_STAMINA_BONUS = 0.75  # 25% faster stamina regen (multiplier)
CLASS_ADAPTER_ENERGY_BONUS = 0.75  # 25% faster energy regen (multiplier)
CLASS_INVOKER_SHRINE_BONUS = 1.25  # 25% bonus shrine rewards (multiplier)

# ============================================================================
# STAT ALLOCATION
# ============================================================================

MAX_POINTS_PER_STAT = 999  # Maximum points that can be allocated to single stat
POINTS_PER_LEVEL = 5  # Stat points granted per level up

# Base resource values (before stat allocation)
BASE_ENERGY = 100
BASE_STAMINA = 50
BASE_HP = 500

# Resource gains per stat point
ENERGY_PER_POINT = 10
STAMINA_PER_POINT = 5
HP_PER_POINT = 100

# ============================================================================
# LEVELING SYSTEM
# ============================================================================

MAX_LEVEL_UPS_PER_TRANSACTION = 10  # Safety cap to prevent infinite loops
MINOR_MILESTONE_INTERVAL = 5  # Every 5 levels
MAJOR_MILESTONE_INTERVAL = 10  # Every 10 levels

# Overcap bonuses
OVERCAP_THRESHOLD = 0.9  # Must be at 90%+ to get overcap bonus
OVERCAP_BONUS = 0.10  # 10% bonus resources on level up

# ============================================================================
# FUSION SYSTEM
# ============================================================================

MAX_FUSION_TIER = 12  # Cannot fuse tier 12+
FUSION_MAIDENS_REQUIRED = 2  # Always requires 2 maidens
SHARDS_FOR_GUARANTEED_FUSION = 100  # Shard redemption cost
MIN_SHARDS_PER_FAILURE = 1  # Minimum shards from failed fusion
MAX_SHARDS_PER_FAILURE = 12  # Maximum shards from failed fusion

# ============================================================================
# DROP SYSTEM
# ============================================================================

drop_CHARGES_MAX = 1  # Single charge system
drop_REGEN_SECONDS = 300  # 5 minutes
drop_REGEN_MINUTES = 5  # Alternative representation

# ============================================================================
# COMBAT & POWER
# ============================================================================

STRATEGIC_TEAM_SIZE = 6  # Best 6 maidens for strategic power
PITY_COUNTER_MAX = 90  # Guaranteed high-tier at 90 summons

# ============================================================================
# RESOURCE REGENERATION
# ============================================================================

ENERGY_REGEN_MINUTES = 5  # Base energy regen interval
STAMINA_REGEN_MINUTES = 10  # Base stamina regen interval

# ============================================================================
# DATABASE & PERFORMANCE
# ============================================================================

DEFAULT_QUERY_TIMEOUT_MS = 30000  # 30 seconds
DATABASE_HEALTH_CHECK_TIMEOUT_MS = 5000  # 5 seconds
DATABASE_HEALTH_DEGRADED_THRESHOLD_MS = 100  # 100ms = degraded
DATABASE_HEALTH_UNHEALTHY_THRESHOLD_MS = 1000  # 1s = unhealthy

# Connection pool limits (per instance)
DEFAULT_POOL_SIZE = 20
DEFAULT_MAX_OVERFLOW = 10
MAX_TOTAL_CONNECTIONS = 30  # pool_size + max_overflow

# ============================================================================
# RATE LIMITING
# ============================================================================

CIRCUIT_BREAKER_FAILURE_THRESHOLD = 5  # Failures before opening circuit
CIRCUIT_BREAKER_RECOVERY_SECONDS = 60  # Wait before retry
FUSION_LOCK_TIMEOUT_SECONDS = 10  # Max time to hold fusion lock
FUSION_LOCK_BLOCKING_TIMEOUT_SECONDS = 2  # Wait to acquire lock

# ============================================================================
# DISCORD EMBED LIMITS
# ============================================================================

DISCORD_EMBED_FIELD_LIMIT = 1024  # Max characters per field
DISCORD_EMBED_DESCRIPTION_LIMIT = 4096  # Max characters in description
DISCORD_EMBED_TITLE_LIMIT = 256  # Max characters in title
DISCORD_EMBED_FOOTER_LIMIT = 2048  # Max characters in footer

# ============================================================================
# LOGGING & METRICS
# ============================================================================

LOG_ROTATION_SIZE_MB = 10  # Rotate logs at 10MB
LOG_RETENTION_DAYS = 30  # Keep logs for 30 days
METRICS_AGGREGATION_WINDOW_SECONDS = 60  # Aggregate metrics every minute

# ============================================================================
# CACHE TTL (Time To Live) in seconds
# ============================================================================

CACHE_TTL_SHORT = 60  # 1 minute
CACHE_TTL_MEDIUM = 300  # 5 minutes
CACHE_TTL_LONG = 1800  # 30 minutes
CACHE_TTL_VERY_LONG = 3600  # 1 hour

# ============================================================================
# VALIDATION LIMITS
# ============================================================================

MAX_USERNAME_LENGTH = 100
MAX_COMMAND_NAME_LENGTH = 50
MAX_TRANSACTION_CONTEXT_LENGTH = 255
MIN_PLAYER_LEVEL = 1
MAX_TIER_NUMBER = 12

# ============================================================================
# EVENT SYSTEM
# ============================================================================

EVENT_PROCESSING_TIMEOUT_SECONDS = 30
MAX_EVENT_RETRIES = 3
EVENT_RETRY_DELAY_SECONDS = 5
