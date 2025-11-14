"""
Core infrastructure layer for Lumen RPG (2025).

Provides foundational subsystems:
- Bot infrastructure (Discord.py integration, lifecycle, cog loading)
- Cache subsystem (Redis-backed caching)
- Configuration management (static and dynamic config)
- Database subsystem (SQLAlchemy async engine, sessions, health)
- Event system (event bus, listeners, routing)
- Infrastructure services (health checks, audit logging)
- Logging (structured logging, context tracking)
- Redis (connection pooling, locking, resilience)
- Validation (input validation, transaction validation)

All subsystems follow LUMEN LAW 2025 compliance standards.
"""

# Re-export commonly used items for convenience
from src.core.config import Config, ConfigManager
from src.core.database import DatabaseService, initialize_database_subsystem
from src.core.exceptions import (
    ConfigurationError,
    CooldownError,
    DatabaseError,
    InsufficientResourcesError,
    InvalidFusionError,
    InvalidOperationError,
    LumenException,
    MaidenNotFoundError,
    NotFoundError,
    PlayerNotFoundError,
    RateLimitError,
    ValidationError,
)
from src.core.infra import HealthStatus, UnifiedHealthCheck
from src.core.logging import get_logger, setup_logging
from src.core.redis import RedisService
from src.core.validation import InputValidator

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
    # Health
    "UnifiedHealthCheck",
    "HealthStatus",
    # Exceptions
    "LumenException",
    "ValidationError",
    "NotFoundError",
    "MaidenNotFoundError",
    "PlayerNotFoundError",
    "InsufficientResourcesError",
    "InvalidOperationError",
    "InvalidFusionError",
    "CooldownError",
    "ConfigurationError",
    "DatabaseError",
    "RateLimitError",
]
