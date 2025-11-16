"""
Lumen RPG Infrastructure Constants

Purpose
-------
Provide infrastructure-level constants for system operation, reliability,
and platform integration. These are technical limits, timeouts, thresholds,
and configuration values that govern system behavior independently of game
mechanics.

IMPORTANT:
This module contains infrastructure constants only. Game mechanics, balance
values, and domain-specific constants belong in src/modules/shared/constants.py.

LUMEN LAW / LES 2025 Compliance
-------------------------------
- Infrastructure concerns only (database, caching, logging, Discord, events)
- No game balance or mechanics values
- No Discord dependencies; pure data only
- No side effects at import time

Design Notes
------------
- Values are annotated with typing.Final to signal immutability
- Grouped by functional area for easy scanning and maintenance
- Comments explain the purpose and rationale for limits
"""

from __future__ import annotations

from typing import Final

# ============================================================================
# DATABASE & PERFORMANCE
# ============================================================================

# Query execution limits
DEFAULT_QUERY_TIMEOUT_MS: Final[int] = 30_000  # 30 seconds
DATABASE_HEALTH_CHECK_TIMEOUT_MS: Final[int] = 5_000  # 5 seconds

# Health monitoring thresholds
DATABASE_HEALTH_DEGRADED_THRESHOLD_MS: Final[int] = 100  # 100ms = degraded
DATABASE_HEALTH_UNHEALTHY_THRESHOLD_MS: Final[int] = 1_000  # 1s = unhealthy

# Connection pool limits (per instance)
DEFAULT_POOL_SIZE: Final[int] = 20
DEFAULT_MAX_OVERFLOW: Final[int] = 10
MAX_TOTAL_CONNECTIONS: Final[int] = 30  # pool_size + max_overflow

# Safety limit to prevent runaway leveling loops
MAX_LEVEL_UPS_PER_TRANSACTION: Final[int] = 10

# ============================================================================
# RATE LIMITING & CIRCUIT BREAKERS
# ============================================================================

# Circuit breaker configuration
CIRCUIT_BREAKER_FAILURE_THRESHOLD: Final[int] = 5  # Failures before opening
CIRCUIT_BREAKER_RECOVERY_SECONDS: Final[int] = 60  # Wait before retry

# Redis lock timeouts for fusion operations
FUSION_LOCK_TIMEOUT_SECONDS: Final[int] = 10  # Max time to hold lock
FUSION_LOCK_BLOCKING_TIMEOUT_SECONDS: Final[int] = 2  # Wait to acquire lock

# ============================================================================
# DISCORD EMBED LIMITS
# ============================================================================

# Discord API platform constraints
DISCORD_EMBED_FIELD_LIMIT: Final[int] = 1_024  # Max characters per field
DISCORD_EMBED_DESCRIPTION_LIMIT: Final[int] = 4_096  # Max characters in description
DISCORD_EMBED_TITLE_LIMIT: Final[int] = 256  # Max characters in title
DISCORD_EMBED_FOOTER_LIMIT: Final[int] = 2_048  # Max characters in footer

# ============================================================================
# LOGGING & METRICS
# ============================================================================

# Log file management
LOG_ROTATION_SIZE_MB: Final[int] = 10  # Rotate logs at 10MB
LOG_RETENTION_DAYS: Final[int] = 30  # Keep logs for 30 days

# Metrics collection
METRICS_AGGREGATION_WINDOW_SECONDS: Final[int] = 60  # Aggregate every minute

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

# Input validation bounds
MAX_USERNAME_LENGTH: Final[int] = 100
MAX_COMMAND_NAME_LENGTH: Final[int] = 50
MAX_TRANSACTION_CONTEXT_LENGTH: Final[int] = 255

# ============================================================================
# EVENT SYSTEM
# ============================================================================

# Event processing reliability
EVENT_PROCESSING_TIMEOUT_SECONDS: Final[int] = 30
MAX_EVENT_RETRIES: Final[int] = 3
EVENT_RETRY_DELAY_SECONDS: Final[int] = 5
