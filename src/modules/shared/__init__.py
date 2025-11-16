"""
Lumen Shared Module

Purpose
-------
Provides domain-level foundations for all game modules:
- Domain exceptions and error handling
- Base service and repository patterns
- Gameplay constants and formulas
- Domain validation utilities

This module enforces LES 2025 architectural boundaries by separating
domain concerns (game logic, business rules) from infrastructure concerns
(database, caching, Discord integration).

LUMEN LAW / LES 2025 Compliance
-------------------------------
- Domain layer only (no infrastructure dependencies)
- Services use these foundations to implement game logic
- No Discord imports or UI concerns
- Pure business logic and calculation functions

Architecture
------------
- BaseService: Foundation for service classes (logging, config, events)
- BaseRepository: Type-safe database access patterns
- Domain exceptions: Game-facing errors and business rule violations
- Formulas: Pure calculation functions for game mechanics
- Validators: Domain validation with structured error raising
- Constants: Game mechanic values and balance numbers

Usage
-----
    from src.modules.shared import (
        BaseService,
        BaseRepository,
        InsufficientResourcesError,
        calculate_fusion_success_rate,
        validate_resource_cost,
    )
"""

from __future__ import annotations

# Base patterns
from .base_repository import BaseRepository
from .base_service import BaseService

# Domain exceptions
from .exceptions import (
    CooldownActiveError,
    ErrorSeverity,
    InsufficientResourcesError,
    InvalidFusionError,
    InvalidOperationError,
    LumenDomainException,
    MaidenNotFoundError,
    NotFoundError,
    RateLimitError,
    ValidationError,
    get_error_severity,
    is_transient_error,
    should_alert,
)

# Domain constants
from .constants import (
    BASE_ENERGY,
    BASE_HP,
    BASE_STAMINA,
    CLASS_ADAPTER_ENERGY_BONUS,
    CLASS_DESTROYER_STAMINA_BONUS,
    CLASS_INVOKER_SHRINE_BONUS,
    DROP_CHARGES_MAX,
    DROP_REGEN_MINUTES,
    DROP_REGEN_SECONDS,
    ENERGY_PER_POINT,
    ENERGY_REGEN_MINUTES,
    FUSION_MAIDENS_REQUIRED,
    HP_PER_POINT,
    MAJOR_MILESTONE_INTERVAL,
    MAX_FUSION_TIER,
    MAX_POINTS_PER_STAT,
    MAX_SHARDS_PER_FAILURE,
    MAX_TIER_NUMBER,
    MIN_PLAYER_LEVEL,
    MIN_SHARDS_PER_FAILURE,
    MINOR_MILESTONE_INTERVAL,
    OVERCAP_BONUS,
    OVERCAP_THRESHOLD,
    PITY_COUNTER_MAX,
    POINTS_PER_LEVEL,
    SHARDS_FOR_GUARANTEED_FUSION,
    STAMINA_PER_POINT,
    STAMINA_REGEN_MINUTES,
    STRATEGIC_TEAM_SIZE,
)

# Formulas
from .formulas import (
    calculate_fusion_cost,
    calculate_fusion_success_rate,
    calculate_level_from_xp,
    calculate_maiden_power,
    calculate_overcap_bonus,
    calculate_pity_boost,
    calculate_rarity_multiplier,
    calculate_resource_value,
    calculate_reward_amount,
    calculate_shard_reward,
    calculate_stat_value,
    calculate_strategic_power,
    calculate_xp_for_level,
)

# Validators
from .validators import (
    validate_cooldown,
    validate_fusion_eligible,
    validate_level_range,
    validate_maiden_exists,
    validate_maiden_ownership,
    validate_resource_cost,
    validate_tier_range,
)

__all__ = [
    # Base patterns
    "BaseService",
    "BaseRepository",
    # Exceptions
    "LumenDomainException",
    "ErrorSeverity",
    "InsufficientResourcesError",
    "NotFoundError",
    "MaidenNotFoundError",
    "ValidationError",
    "InvalidFusionError",
    "CooldownActiveError",
    "RateLimitError",
    "InvalidOperationError",
    "is_transient_error",
    "get_error_severity",
    "should_alert",
    # Constants
    "CLASS_DESTROYER_STAMINA_BONUS",
    "CLASS_ADAPTER_ENERGY_BONUS",
    "CLASS_INVOKER_SHRINE_BONUS",
    "MAX_POINTS_PER_STAT",
    "POINTS_PER_LEVEL",
    "BASE_ENERGY",
    "BASE_STAMINA",
    "BASE_HP",
    "ENERGY_PER_POINT",
    "STAMINA_PER_POINT",
    "HP_PER_POINT",
    "MINOR_MILESTONE_INTERVAL",
    "MAJOR_MILESTONE_INTERVAL",
    "OVERCAP_THRESHOLD",
    "OVERCAP_BONUS",
    "MAX_FUSION_TIER",
    "FUSION_MAIDENS_REQUIRED",
    "SHARDS_FOR_GUARANTEED_FUSION",
    "MIN_SHARDS_PER_FAILURE",
    "MAX_SHARDS_PER_FAILURE",
    "DROP_CHARGES_MAX",
    "DROP_REGEN_SECONDS",
    "DROP_REGEN_MINUTES",
    "STRATEGIC_TEAM_SIZE",
    "PITY_COUNTER_MAX",
    "ENERGY_REGEN_MINUTES",
    "STAMINA_REGEN_MINUTES",
    "MIN_PLAYER_LEVEL",
    "MAX_TIER_NUMBER",
    # Formulas
    "calculate_xp_for_level",
    "calculate_level_from_xp",
    "calculate_stat_value",
    "calculate_overcap_bonus",
    "calculate_rarity_multiplier",
    "calculate_fusion_success_rate",
    "calculate_fusion_cost",
    "calculate_shard_reward",
    "calculate_pity_boost",
    "calculate_maiden_power",
    "calculate_strategic_power",
    "calculate_resource_value",
    "calculate_reward_amount",
    # Validators
    "validate_resource_cost",
    "validate_level_range",
    "validate_tier_range",
    "validate_maiden_exists",
    "validate_maiden_ownership",
    "validate_fusion_eligible",
    "validate_cooldown",
]
