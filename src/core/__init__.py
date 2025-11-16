"""
Core infrastructure layer for Lumen RPG (2025).

Purpose
-------
Provide a single, well-structured import surface for the core infrastructure
subsystems of Lumen:

- Configuration management (Config, ConfigManager)
- Database subsystem (DatabaseService, initialization helpers)
- Redis subsystem (RedisService for caching and locking)
- Logging (structured logging, logger factory)
- Health checks (UnifiedHealthCheck, HealthStatus)
- Validation utilities (InputValidator, TransactionValidator)
- Domain exceptions (LumenException hierarchy)

Responsibilities
----------------
- Re-export commonly used infra primitives for ergonomic imports in services
- Document the core infra capabilities in one place
- Maintain a stable, intentional public API via __all__

Non-Responsibilities
--------------------
- Implement infra logic (delegated to submodules)
- Business logic or Discord-facing behavior
- Any side effects beyond simple re-exports

Design Decisions
----------------
- This module is intentionally thin: no logic, no configuration, no I/O.
- Public API is explicit via __all__ to avoid leaking internal symbols.
- Only safe, infra-level constructs are re-exported; feature modules should
  still import from their own domains, not from src.core directly.

Lumen Engineering Standard 2025 Compliance
------------------------------------------
- Separation of concerns: infra aggregation only
- No business logic, no Discord dependencies
- Clear, documented boundaries for infra capabilities
"""

from __future__ import annotations

from src.core.config import Config, ConfigManager
from src.core.database import DatabaseService, initialize_database_subsystem

# Infrastructure exceptions (from core)
from src.core.exceptions import (
    CacheError,
    CircuitBreakerError,
    ConfigurationError,
    DatabaseError,
    ErrorSeverity,
    EventBusError,
    LumenInfrastructureException,
    PlayerNotFoundError,
    RedisConnectionError,
)

# Domain exceptions (from shared module) - re-exported for backward compatibility
from src.modules.shared.exceptions import (
    CooldownActiveError,
    InsufficientResourcesError,
    InvalidFusionError,
    InvalidOperationError,
    LumenDomainException,
    MaidenNotFoundError,
    NotFoundError,
    RateLimitError,
    ValidationError,
)

# Legacy aliases for backward compatibility
LumenException = LumenDomainException  # Old name for domain exception base
CooldownError = CooldownActiveError  # Old name for cooldown exception

from src.core.infra import HealthStatus, UnifiedHealthCheck
from src.core.logging import get_logger, setup_logging
from src.core.redis import RedisService
from src.core.validation import InputValidator, TransactionValidator

__all__ = [
    # Configuration
    "Config",
    "ConfigManager",
    # Database
    "DatabaseService",
    "initialize_database_subsystem",
    # Redis
    "RedisService",
    # Logging
    "setup_logging",
    "get_logger",
    # Validation
    "InputValidator",
    "TransactionValidator",
    # Health
    "UnifiedHealthCheck",
    "HealthStatus",
    # Infrastructure Exceptions
    "LumenInfrastructureException",
    "ConfigurationError",
    "DatabaseError",
    "PlayerNotFoundError",
    "RedisConnectionError",
    "CacheError",
    "CircuitBreakerError",
    "EventBusError",
    "ErrorSeverity",
    # Domain Exceptions (backward compatibility)
    "LumenDomainException",
    "LumenException",  # Legacy alias
    "ValidationError",
    "NotFoundError",
    "MaidenNotFoundError",
    "InsufficientResourcesError",
    "InvalidOperationError",
    "InvalidFusionError",
    "CooldownActiveError",
    "CooldownError",  # Legacy alias
    "RateLimitError",
]
