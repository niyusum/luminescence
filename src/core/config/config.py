"""
Static configuration management for Lumen (2025).

Purpose
-------
Provides centralized static configuration loaded from environment variables
with sensible defaults, type validation, and bounds checking. This module
handles non-dynamic configuration that is set at application startup.

Responsibilities
----------------
- Load configuration from environment variables with .env support
- Provide type-safe access to all static configuration values
- Validate critical settings on startup
- Create required directories (logs, data)
- Detect and warn about security issues in production
- Track configuration loading metrics

Non-Responsibilities
--------------------
- Dynamic configuration (handled by ConfigManager)
- Database-backed configuration (handled by ConfigManager)
- Runtime configuration changes (except safe reload)
- Secrets management (use environment variables)

LES 2025 Compliance
-------------------
- **Config-Driven**: All values from environment or documented defaults
- **Type Safety**: Strong type validation with bounds checking
- **Observability**: Configuration loading metrics and validation tracking
- **Security**: Detects default credentials and security issues
- **Environment Awareness**: Different behavior for dev/staging/production

Architecture Notes
------------------
- Singleton pattern via class methods (no instantiation)
- Auto-loads on module import via Config.validate()
- Supports safe reload for non-critical configs
- Metrics track which values came from environment vs defaults
- Directory paths relative to project root for portability

Configuration Categories
------------------------
1. Discord: Bot token, guild ID, command prefix
2. Database: PostgreSQL connection and pool settings
3. Redis: Redis connection and client settings
4. Environment: Environment type, debug mode, logging
5. Bot Metadata: Name, version, description
6. Rate Limiting: Cooldown and failover settings
7. UI Colors: Embed color constants
8. Game Defaults: Starting resources for new players
9. Circuit Breaker: Failure thresholds and recovery
10. Game Limits: Maximum values and transaction limits

Dependencies
------------
- python-dotenv: Environment variable loading
- pathlib: Cross-platform path handling
- logging: Basic logging (bootstrap only)

Environment Variables
---------------------
Required:
- DISCORD_TOKEN: Bot authentication token
- DATABASE_URL: PostgreSQL connection string

Optional (with defaults):
- DISCORD_GUILD_ID: Guild ID for testing
- COMMAND_PREFIX: Command prefix (default: "/")
- DATABASE_POOL_SIZE: Connection pool size (default: 20)
- REDIS_URL: Redis connection string (default: localhost)
- ENVIRONMENT: Environment type (default: development)
- DEBUG: Debug mode flag (default: False)
- LOG_LEVEL: Logging level (default: INFO)

See individual attributes for complete list.
"""

import os
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv

from src.ui.emojis import Emojis

# Load environment variables from .env file
load_dotenv()

# ============================================================================
# Enums and Constants
# ============================================================================


class Environment(Enum):
    """
    Deployment environment types.
    
    Defines valid environment values with strict type safety.
    """
    DEVELOPMENT = "development"
    TESTING = "testing"
    STAGING = "staging"
    PRODUCTION = "production"
    
    @classmethod
    def from_string(cls, value: str) -> "Environment":
        """
        Parse environment string safely with fallback.
        
        Parameters
        ----------
        value:
            Environment string to parse.
        
        Returns
        -------
        Environment
            Parsed environment enum value.
        
        Example
        -------
        >>> env = Environment.from_string("production")
        >>> env == Environment.PRODUCTION
        True
        >>> env = Environment.from_string("invalid")  # Logs warning
        >>> env == Environment.DEVELOPMENT
        True
        """
        try:
            return cls(value.lower())
        except ValueError:
            # Use basic logging during bootstrap (structured logger not yet initialized)
            import logging
            logging.warning(
                f"Unknown environment '{value}', defaulting to development"
            )
            return cls.DEVELOPMENT


# ============================================================================
# Configuration Metrics Tracker
# ============================================================================

class _ConfigLoadMetrics:
    """
    Internal metrics tracker for configuration loading.
    
    Tracks which configuration values came from environment variables
    versus defaults, and any validation errors encountered.
    
    Note: This is separate from ConfigMetrics in the metrics module,
    which tracks dynamic configuration operations.
    """
    
    def __init__(self):
        self.env_vars_loaded: Dict[str, bool] = {}
        self.validation_errors: Dict[str, str] = {}
        self.defaults_used: Dict[str, Any] = {}
        self.last_reload: Optional[str] = None
    
    def record_env_load(self, key: str, from_env: bool, value: Any, default: Any):
        """Record whether a config value came from environment."""
        self.env_vars_loaded[key] = from_env
        if not from_env:
            self.defaults_used[key] = default
    
    def record_validation_error(self, key: str, error: str):
        """Record a validation error."""
        self.validation_errors[key] = error
    
    def get_summary(self) -> Dict[str, Any]:
        """Get configuration loading summary."""
        return {
            "total_configs": len(self.env_vars_loaded),
            "from_environment": sum(1 for v in self.env_vars_loaded.values() if v),
            "from_defaults": sum(1 for v in self.env_vars_loaded.values() if not v),
            "validation_errors": len(self.validation_errors),
            "defaults_used": list(self.defaults_used.keys()),
            "last_reload": self.last_reload,
        }


# ============================================================================
# Main Configuration Class
# ============================================================================


class Config:
    """
    Centralized static configuration for Lumen RPG Discord Bot.
    
    All configuration values loaded from environment variables with sensible
    defaults. Validates critical settings on startup to prevent runtime failures.
    
    Features
    --------
    - Strong type validation with bounds checking
    - Comprehensive config metrics and observability
    - Detailed validation error messages
    - Safe fallback for invalid values
    - Config reload capability (non-critical settings only)
    - Secrets detection and security warnings
    - Environment-aware behavior
    
    Usage
    -----
    >>> # Access configuration values
    >>> token = Config.DISCORD_TOKEN
    >>> db_url = Config.DATABASE_URL
    >>> 
    >>> # Check environment
    >>> if Config.is_production():
    ...     logger.info("Running in production mode")
    >>> 
    >>> # Get config summary
    >>> summary = Config.get_config_summary()
    >>> logger.info("Config loaded", extra=summary)
    """
    
    # =========================================================================
    # Internal State
    # =========================================================================
    
    _metrics: Optional[_ConfigLoadMetrics] = None
    _enable_metrics: bool = True
    _validated: bool = False
    
    # =========================================================================
    # Discord Configuration
    # =========================================================================
    
    DISCORD_TOKEN: str = ""
    DISCORD_GUILD_ID: Optional[int] = None
    COMMAND_PREFIX: str = "/"
    
    # =========================================================================
    # Database Configuration
    # =========================================================================
    
    DATABASE_URL: str = ""
    DATABASE_POOL_SIZE: int = 20  # Reduced from 50 to prevent exhaustion
    DATABASE_MAX_OVERFLOW: int = 10  # Max 30 connections per instance
    DATABASE_ECHO: bool = False
    DATABASE_POOL_RECYCLE: int = 3600  # Recycle connections after 1 hour
    
    # =========================================================================
    # Redis Configuration
    # =========================================================================
    
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_PASSWORD: Optional[str] = None
    REDIS_MAX_CONNECTIONS: int = 50
    REDIS_DECODE_RESPONSES: bool = True
    REDIS_SOCKET_TIMEOUT: int = 5
    REDIS_RETRY_ON_TIMEOUT: bool = True
    
    # =========================================================================
    # Environment Configuration
    # =========================================================================
    
    ENVIRONMENT: str = "development"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    
    # =========================================================================
    # Directory Configuration
    # =========================================================================
    
    # Place logs + data at project root
    PROJECT_ROOT = Path(__file__).resolve().parents[3]
    LOGS_DIR = PROJECT_ROOT / "logs"
    DATA_DIR = PROJECT_ROOT / "data"
    
    # =========================================================================
    # Bot Metadata
    # =========================================================================
    
    BOT_NAME: str = "Lumen RPG"
    BOT_VERSION: str = "2.0.0"
    BOT_DESCRIPTION: str = "A Discord RPG featuring maidens, fusion, and strategic gameplay"
    
    # =========================================================================
    # Rate Limiting
    # =========================================================================
    
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_FAILOVER_TO_MEMORY: bool = True
    RATE_LIMIT_COOLDOWN_MESSAGE: str = (
        f"{Emojis.REGENERATING} Please wait {{remaining:.1f}} seconds before using this command again."
    )
    
    # =========================================================================
    # UI Colors
    # =========================================================================
    
    EMBED_COLOR_PRIMARY: int = 0x2c2d31
    EMBED_COLOR_SUCCESS: int = 0x2d5016
    EMBED_COLOR_ERROR: int = 0x8b0000
    EMBED_COLOR_WARNING: int = 0x8b6914
    EMBED_COLOR_INFO: int = 0x1e3a8a
    
    # =========================================================================
    # Game Defaults
    # =========================================================================
    
    DEFAULT_STARTING_LUMEES: int = 1000
    DEFAULT_STARTING_AURIC_COIN: int = 5  # Fixed: was lowercase auric_coin
    DEFAULT_STARTING_ENERGY: int = 100
    DEFAULT_STARTING_STAMINA: int = 50
    
    # =========================================================================
    # Circuit Breaker
    # =========================================================================
    
    CIRCUIT_BREAKER_FAILURE_THRESHOLD: int = 5
    CIRCUIT_BREAKER_RECOVERY_TIMEOUT: int = 60
    CIRCUIT_BREAKER_EXPECTED_EXCEPTION: tuple = (Exception,)
    
    # =========================================================================
    # Game Limits
    # =========================================================================
    
    MAX_FUSION_COST: int = 100_000_000
    MAX_LEVEL_UPS_PER_TRANSACTION: int = 10

    # =========================================================================
    # Helper Methods
    # =========================================================================
    
    @classmethod
    def _init_metrics(cls):
        """Initialize metrics tracking if enabled."""
        if cls._enable_metrics and cls._metrics is None:
            cls._metrics = _ConfigLoadMetrics()
    
    @classmethod
    def _safe_int(
        cls,
        key: str,
        default: int,
        min_val: Optional[int] = None,
        max_val: Optional[int] = None,
    ) -> int:
        """
        Safely parse integer from environment with validation.
        
        Parameters
        ----------
        key:
            Environment variable name.
        default:
            Default value if not set or invalid.
        min_val:
            Minimum allowed value (inclusive).
        max_val:
            Maximum allowed value (inclusive).
        
        Returns
        -------
        int
            Validated integer value.
        
        Example
        -------
        >>> Config._safe_int("DATABASE_POOL_SIZE", 20, min_val=1, max_val=200)
        20
        """
        cls._init_metrics()
        
        raw_value = os.getenv(key)
        
        if raw_value is None:
            if cls._metrics:
                cls._metrics.record_env_load(key, False, default, default)
            return default
        
        try:
            value = int(raw_value)
            
            # Validate bounds
            if min_val is not None and value < min_val:
                error = f"{key}={value} is below minimum {min_val}, using default {default}"
                import logging
                logging.warning(error)
                if cls._metrics:
                    cls._metrics.record_validation_error(key, error)
                return default
            
            if max_val is not None and value > max_val:
                error = f"{key}={value} exceeds maximum {max_val}, using default {default}"
                import logging
                logging.warning(error)
                if cls._metrics:
                    cls._metrics.record_validation_error(key, error)
                return default
            
            if cls._metrics:
                cls._metrics.record_env_load(key, True, value, default)
            
            return value
            
        except ValueError:
            error = f"{key}='{raw_value}' is not a valid integer, using default {default}"
            import logging
            logging.warning(error)
            if cls._metrics:
                cls._metrics.record_validation_error(key, error)
            return default
    
    @classmethod
    def _safe_bool(cls, key: str, default: bool) -> bool:
        """
        Safely parse boolean from environment.
        
        Recognizes: true/false, yes/no, 1/0, on/off (case-insensitive).
        
        Parameters
        ----------
        key:
            Environment variable name.
        default:
            Default value if not set or invalid.
        
        Returns
        -------
        bool
            Parsed boolean value.
        
        Example
        -------
        >>> Config._safe_bool("DEBUG", False)
        False
        """
        cls._init_metrics()
        
        raw_value = os.getenv(key)
        
        if raw_value is None:
            if cls._metrics:
                cls._metrics.record_env_load(key, False, default, default)
            return default
        
        normalized = raw_value.lower().strip()
        true_values = {"true", "yes", "1", "on"}
        false_values = {"false", "no", "0", "off"}
        
        if normalized in true_values:
            value = True
        elif normalized in false_values:
            value = False
        else:
            error = f"{key}='{raw_value}' is not a valid boolean, using default {default}"
            import logging
            logging.warning(error)
            if cls._metrics:
                cls._metrics.record_validation_error(key, error)
            return default
        
        if cls._metrics:
            cls._metrics.record_env_load(key, True, value, default)
        
        return value
    
    @classmethod
    def _safe_str(
        cls,
        key: str,
        default: str,
        required: bool = False,
    ) -> str:
        """
        Safely get string from environment.
        
        Parameters
        ----------
        key:
            Environment variable name.
        default:
            Default value if not set.
        required:
            Whether this config is required (raises if missing in production).
        
        Returns
        -------
        str
            Configuration value.
        
        Example
        -------
        >>> Config._safe_str("DISCORD_TOKEN", "", required=True)
        'your-token-here'
        """
        cls._init_metrics()
        
        value = os.getenv(key, default)
        from_env = key in os.environ
        
        if cls._metrics:
            cls._metrics.record_env_load(key, from_env, value, default)
        
        if required and not value:
            error = f"Required environment variable {key} is not set"
            import logging
            logging.error(error)
            if cls._metrics:
                cls._metrics.record_validation_error(key, error)
        
        return value
    
    @classmethod
    def _safe_optional_int(cls, key: str) -> Optional[int]:
        """
        Safely parse optional integer from environment.
        
        Parameters
        ----------
        key:
            Environment variable name.
        
        Returns
        -------
        Optional[int]
            Parsed integer or None if not set or invalid.
        
        Example
        -------
        >>> Config._safe_optional_int("DISCORD_GUILD_ID")
        None
        """
        cls._init_metrics()
        
        raw_value = os.getenv(key)
        
        if raw_value is None:
            if cls._metrics:
                cls._metrics.record_env_load(key, False, None, None)
            return None
        
        try:
            value = int(raw_value)
            if cls._metrics:
                cls._metrics.record_env_load(key, True, value, None)
            return value
        except ValueError:
            error = f"{key}='{raw_value}' is not a valid integer, ignoring"
            import logging
            logging.warning(error)
            if cls._metrics:
                cls._metrics.record_validation_error(key, error)
            return None
    
    # =========================================================================
    # Configuration Loading
    # =========================================================================
    
    @classmethod
    def load(cls) -> None:
        """
        Load all configuration from environment variables with validation.
        
        This method is called automatically on module import, but can be
        called again to reload non-critical configuration at runtime.
        
        Example
        -------
        >>> Config.load()
        >>> print(Config.DISCORD_TOKEN)
        'your-token-here'
        """
        cls._init_metrics()
        
        # Discord Configuration
        cls.DISCORD_TOKEN = cls._safe_str("DISCORD_TOKEN", "", required=True)
        cls.DISCORD_GUILD_ID = cls._safe_optional_int("DISCORD_GUILD_ID")
        cls.COMMAND_PREFIX = cls._safe_str("COMMAND_PREFIX", "/")
        
        # Database Configuration with validation
        cls.DATABASE_URL = cls._safe_str(
            "DATABASE_URL",
            "postgresql+psycopg://user:password@localhost:5432/lumen_rpg",
            required=True,
        )
        cls.DATABASE_POOL_SIZE = cls._safe_int(
            "DATABASE_POOL_SIZE", 20, min_val=1, max_val=200
        )
        cls.DATABASE_MAX_OVERFLOW = cls._safe_int(
            "DATABASE_MAX_OVERFLOW", 10, min_val=0, max_val=200
        )
        cls.DATABASE_ECHO = cls._safe_bool("DATABASE_ECHO", False)
        cls.DATABASE_POOL_RECYCLE = cls._safe_int(
            "DATABASE_POOL_RECYCLE", 3600, min_val=60
        )
        
        # Redis Configuration
        cls.REDIS_URL = cls._safe_str("REDIS_URL", "redis://localhost:6379/0")
        cls.REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")
        cls.REDIS_MAX_CONNECTIONS = cls._safe_int(
            "REDIS_MAX_CONNECTIONS", 50, min_val=1, max_val=500
        )
        cls.REDIS_SOCKET_TIMEOUT = cls._safe_int(
            "REDIS_SOCKET_TIMEOUT", 5, min_val=1, max_val=60
        )
        
        # Environment Configuration
        cls.ENVIRONMENT = cls._safe_str("ENVIRONMENT", "development")
        cls.DEBUG = cls._safe_bool("DEBUG", False)
        cls.LOG_LEVEL = cls._safe_str("LOG_LEVEL", "INFO")
        
        # Game Configuration
        cls.DEFAULT_STARTING_LUMEES = cls._safe_int(
            "DEFAULT_STARTING_LUMEES", 1000, min_val=0
        )
        cls.DEFAULT_STARTING_AURIC_COIN = cls._safe_int(
            "DEFAULT_STARTING_AURIC_COIN", 5, min_val=0
        )
        cls.DEFAULT_STARTING_ENERGY = cls._safe_int(
            "DEFAULT_STARTING_ENERGY", 100, min_val=0
        )
        cls.DEFAULT_STARTING_STAMINA = cls._safe_int(
            "DEFAULT_STARTING_STAMINA", 50, min_val=0
        )
        
        # Circuit Breaker
        cls.CIRCUIT_BREAKER_FAILURE_THRESHOLD = cls._safe_int(
            "CIRCUIT_BREAKER_FAILURE_THRESHOLD", 5, min_val=1, max_val=100
        )
        cls.CIRCUIT_BREAKER_RECOVERY_TIMEOUT = cls._safe_int(
            "CIRCUIT_BREAKER_RECOVERY_TIMEOUT", 60, min_val=10
        )
        
        # Game Limits
        cls.MAX_FUSION_COST = cls._safe_int("MAX_FUSION_COST", 100_000_000, min_val=1)
        cls.MAX_LEVEL_UPS_PER_TRANSACTION = cls._safe_int(
            "MAX_LEVEL_UPS_PER_TRANSACTION", 10, min_val=1, max_val=100
        )
        
        if cls._metrics:
            from datetime import datetime
            cls._metrics.last_reload = datetime.utcnow().isoformat()
    
    @classmethod
    def validate(cls) -> None:
        """
        Validate critical configuration values on startup.
        
        Raises
        ------
        ValueError:
            If required config values are missing or invalid in production.
        
        Example
        -------
        >>> Config.validate()
        >>> # Logs configuration summary and validates critical values
        """
        if cls._validated:
            return
        
        import logging
        logger = logging.getLogger(__name__)
        cls._init_metrics()
        
        try:
            # Load all configuration with validation
            cls.load()
            
            # Additional validation
            if not cls.DISCORD_TOKEN:
                raise ValueError("DISCORD_TOKEN environment variable is required")
            
            if not cls.DATABASE_URL:
                raise ValueError("DATABASE_URL environment variable is required")
            
            # Validate database URL format
            if cls.is_production() and "localhost" in cls.DATABASE_URL:
                logger.warning(
                    "Production environment using localhost database - "
                    "this may be incorrect"
                )
            
            # Validate log level
            valid_log_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
            if cls.LOG_LEVEL.upper() not in valid_log_levels:
                logger.warning(
                    f"Invalid LOG_LEVEL '{cls.LOG_LEVEL}', using INFO"
                )
                cls.LOG_LEVEL = "INFO"
            
            # Create directories
            cls.LOGS_DIR.mkdir(exist_ok=True)
            cls.DATA_DIR.mkdir(exist_ok=True)
            
            # Validate colors are valid hex
            color_attrs = [
                "EMBED_COLOR_PRIMARY",
                "EMBED_COLOR_SUCCESS",
                "EMBED_COLOR_ERROR",
                "EMBED_COLOR_WARNING",
                "EMBED_COLOR_INFO",
            ]
            for attr in color_attrs:
                color = getattr(cls, attr)
                if not (0 <= color <= 0xFFFFFF):
                    logger.warning(
                        f"{attr}={hex(color)} is not a valid color, using default"
                    )
            
            # Warn about default credentials in production
            if cls.is_production():
                if "user:password" in cls.DATABASE_URL:
                    logger.error(
                        f"{Emojis.WARNING}  SECURITY: Using default database credentials in production!"
                    )
                
                if cls.DEBUG:
                    logger.warning(f"{Emojis.WARNING}  DEBUG mode enabled in production!")
            
            cls._validated = True
            
            # Log configuration summary
            if cls._metrics:
                summary = cls._metrics.get_summary()
                logger.info(f"Configuration loaded: {summary}")
                
                if cls._metrics.validation_errors:
                    logger.warning(
                        f"Configuration warnings: {cls._metrics.validation_errors}"
                    )
            
        except Exception as e:
            logger.warning(f"Config validation warning (safe for tests): {e}")
            if cls.ENVIRONMENT.lower() == "production":
                logger.error(f"{Emojis.WARNING}  Configuration validation failed in production!")
                raise
    
    # =========================================================================
    # Environment Checks
    # =========================================================================
    
    @classmethod
    def is_production(cls) -> bool:
        """Check if running in production environment."""
        return cls.ENVIRONMENT.lower() == "production"
    
    @classmethod
    def is_development(cls) -> bool:
        """Check if running in development environment."""
        return cls.ENVIRONMENT.lower() == "development"
    
    @classmethod
    def is_testing(cls) -> bool:
        """Check if running in testing environment."""
        return cls.ENVIRONMENT.lower() == "testing"
    
    @classmethod
    def is_staging(cls) -> bool:
        """Check if running in staging environment."""
        return cls.ENVIRONMENT.lower() == "staging"
    
    # =========================================================================
    # Metrics & Summary
    # =========================================================================
    
    @classmethod
    def get_metrics(cls) -> Optional[_ConfigLoadMetrics]:
        """Get configuration loading metrics."""
        return cls._metrics
    
    @classmethod
    def get_config_summary(cls) -> Dict[str, Any]:
        """
        Get non-sensitive configuration summary for debugging.
        
        Returns
        -------
        Dict[str, Any]
            Dictionary with sanitized configuration values.
        
        Example
        -------
        >>> summary = Config.get_config_summary()
        >>> print(summary["environment"])
        'development'
        >>> print(summary["discord_token_set"])
        True
        """
        return {
            "environment": cls.ENVIRONMENT,
            "debug": cls.DEBUG,
            "log_level": cls.LOG_LEVEL,
            "database_pool_size": cls.DATABASE_POOL_SIZE,
            "database_max_overflow": cls.DATABASE_MAX_OVERFLOW,
            "redis_max_connections": cls.REDIS_MAX_CONNECTIONS,
            "rate_limit_enabled": cls.RATE_LIMIT_ENABLED,
            "bot_version": cls.BOT_VERSION,
            "discord_token_set": bool(cls.DISCORD_TOKEN),
            "database_url_set": bool(cls.DATABASE_URL),
            "redis_password_set": bool(cls.REDIS_PASSWORD),
        }
    
    @classmethod
    def reload_safe_configs(cls) -> None:
        """
        Reload non-critical configuration values at runtime.
        
        Only reloads settings that can be safely changed without restart:
        - Log level
        - Debug flag
        - Rate limiting settings
        - Game balance values
        
        Does NOT reload:
        - Discord token
        - Database/Redis URLs
        - Pool sizes
        
        Example
        -------
        >>> # Update .env file with new values
        >>> Config.reload_safe_configs()
        >>> # New values are now active
        """
        import logging
        logger = logging.getLogger(__name__)
        logger.info("Reloading safe configuration values...")
        
        cls.LOG_LEVEL = cls._safe_str("LOG_LEVEL", cls.LOG_LEVEL)
        cls.DEBUG = cls._safe_bool("DEBUG", cls.DEBUG)
        cls.RATE_LIMIT_ENABLED = cls._safe_bool(
            "RATE_LIMIT_ENABLED", cls.RATE_LIMIT_ENABLED
        )
        
        # Game balance values (safe to reload)
        cls.DEFAULT_STARTING_LUMEES = cls._safe_int(
            "DEFAULT_STARTING_LUMEES", cls.DEFAULT_STARTING_LUMEES, min_val=0
        )
        cls.DEFAULT_STARTING_AURIC_COIN = cls._safe_int(
            "DEFAULT_STARTING_AURIC_COIN", cls.DEFAULT_STARTING_AURIC_COIN, min_val=0
        )
        cls.MAX_FUSION_COST = cls._safe_int(
            "MAX_FUSION_COST", cls.MAX_FUSION_COST, min_val=1
        )
        
        logger.info("Safe configuration values reloaded successfully")


# Auto-validate on import
Config.validate()