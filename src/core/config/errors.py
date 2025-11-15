"""
Configuration error hierarchy for Lumen (2025).

Purpose
-------
Provides domain-specific exceptions for configuration management operations
with clear error classification and helpful error messages.

Responsibilities
----------------
- Define exception hierarchy for configuration errors
- Provide clear error messages for different failure scenarios
- Enable precise error handling and recovery strategies

Non-Responsibilities
--------------------
- Error logging (handled by logger)
- Error recovery logic (handled by ConfigManager)
- Metrics tracking (handled by ConfigMetrics)

LES 2025 Compliance
-------------------
- **Domain Exceptions**: Clear exception hierarchy for config errors
- **Error Handling**: Precise error classification for proper handling
- **Observability**: Structured error information for logging
- **Type Safety**: Proper exception class hierarchy

Architecture Notes
------------------
All exceptions inherit from ConfigError base class for easy catching.
Each exception type represents a specific failure scenario.

Dependencies
------------
- Standard library only (Exception base class)

Exception Hierarchy
-------------------
ConfigError (base)
├── ConfigValidationError (schema/type validation failures)
├── ConfigWriteError (database write failures)
└── ConfigInitializationError (startup/init failures)
"""


class ConfigError(Exception):
    """
    Base exception for all configuration-related errors.
    
    All configuration exceptions inherit from this class to enable
    catching all config-related errors with a single except clause.
    
    Example
    -------
    >>> try:
    ...     await ConfigManager.set("invalid.key", value)
    ... except ConfigError as e:
    ...     logger.error(f"Config operation failed: {e}")
    """
    pass


class ConfigValidationError(ConfigError):
    """
    Raised when configuration validation fails.
    
    This exception is raised when:
    - Schema validation fails (wrong type, invalid structure)
    - Value bounds checking fails (out of range)
    - Required fields are missing
    - Type coercion fails
    
    Example
    -------
    >>> try:
    ...     await ConfigManager.set("fusion_costs.base", "not_an_int")
    ... except ConfigValidationError as e:
    ...     logger.error(f"Validation failed: {e}")
    """
    pass


class ConfigWriteError(ConfigError):
    """
    Raised when configuration write operation fails.
    
    This exception is raised when:
    - Database transaction fails during config update
    - Pessimistic lock cannot be acquired
    - Network/connection issues prevent write
    - Constraint violations occur
    
    Note: This includes validation errors during writes for backward
    compatibility with existing code.
    
    Example
    -------
    >>> try:
    ...     await ConfigManager.set("fusion_costs", invalid_data)
    ... except ConfigWriteError as e:
    ...     logger.error(f"Write failed: {e}")
    ...     # Retry or fallback logic
    """
    pass


class ConfigInitializationError(ConfigError):
    """
    Raised when ConfigManager initialization fails.
    
    This exception is raised when:
    - YAML config files cannot be loaded
    - Database connection fails during initialization
    - Required configuration is missing or invalid
    - Cache initialization fails
    
    This is a critical error that typically requires intervention
    before the application can continue.
    
    Example
    -------
    >>> try:
    ...     await ConfigManager.initialize()
    ... except ConfigInitializationError as e:
    ...     logger.critical(f"Cannot start - config init failed: {e}")
    ...     sys.exit(1)
    """
    pass


# Export all exception classes
__all__ = [
    "ConfigError",
    "ConfigValidationError",
    "ConfigWriteError",
    "ConfigInitializationError",
]