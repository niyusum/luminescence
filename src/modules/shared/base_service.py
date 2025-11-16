"""
Base Service Foundation

Purpose
-------
Provides the foundational class for all domain services in Lumen RPG.
Services implement pure business logic, manage transactions, enforce
business rules, and emit domain events.

LUMEN LAW / LES 2025 Compliance
-------------------------------
- Pure business logic layer
- No Discord dependencies
- No UI concerns
- Config-driven (loads values from ConfigManager)
- Emits domain events for cross-module communication
- Raises domain exceptions (never raw exceptions)

Design Notes
------------
This base class provides:
- Structured logging with operation context
- Safe config access patterns
- Event emission helpers
- Validation error wrapping
- Common error handling patterns

What this class does NOT do:
- Manage database transactions (that's DatabaseService's job)
- Wrap infrastructure services
- Handle SQLAlchemy sessions
- Contain game-specific logic

Usage
-----
    class FusionService(BaseService):
        def __init__(self, db_service, config_manager, event_bus, logger):
            super().__init__(config_manager, event_bus, logger)
            self.db = db_service

        async def fuse_maidens(self, player_id: int, maiden_ids: list[int]):
            # Service logic here, using self.log, self.get_config, self.emit_event
            pass
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from logging import Logger

    from src.core.config.manager import ConfigManager
    from src.core.event.bus import EventBus


class BaseService:
    """
    Base class for all domain services.

    Provides structured logging, config access, and event emission capabilities
    without managing infrastructure concerns.

    Args:
        config_manager: Application configuration manager
        event_bus: Event bus for cross-module communication
        logger: Structured logger instance
    """

    def __init__(
        self,
        config_manager: ConfigManager,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        """
        Initialize base service with required dependencies.

        Args:
            config_manager: Configuration manager instance
            event_bus: Event bus instance
            logger: Structured logger instance
        """
        self._config = config_manager
        self._events = event_bus
        self.log = logger

    def get_config(
        self, key: str, default: Optional[Any] = None, required: bool = False
    ) -> Any:
        """
        Safely retrieve configuration value.

        Args:
            key: Configuration key to retrieve
            default: Default value if key not found
            required: If True, raise exception if key missing

        Returns:
            Configuration value

        Raises:
            ConfigurationError: If required=True and key is missing
        """
        from src.core.exceptions import ConfigurationError

        value = self._config.get(key, default)
        if required and value is None:
            raise ConfigurationError(
                key, f"Required configuration key '{key}' is missing"
            )
        return value

    async def emit_event(
        self,
        event_type: str,
        data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Emit a domain event for cross-module communication.

        Args:
            event_type: Type/name of the event
            data: Event payload data
            context: Optional additional context (user_id, guild_id, etc.)
        """
        await self._events.publish(event_type, {**data, **(context or {})})

    def bind_context(self, **context: Any) -> None:
        """
        Bind additional context to the service logger.

        Args:
            **context: Key-value pairs to add to logging context

        Note:
            This is a no-op for standard Python logging compatibility.
            Use LogContext from src.core.logging.logger for context propagation.
        """
        # Standard logging doesn't support bind like structlog
        # Context should be managed via LogContext context manager instead
        pass

    def log_operation(
        self, operation: str, **context: Any
    ) -> None:
        """
        Log a service operation with structured context.

        Args:
            operation: Name of the operation being performed
            **context: Additional context data
        """
        self.log.info(
            f"Service operation: {operation}",
            extra={"operation": operation, **context},
        )

    def log_error(
        self,
        operation: str,
        error: Exception,
        **context: Any,
    ) -> None:
        """
        Log a service error with full context.

        Args:
            operation: Name of the operation that failed
            error: The exception that occurred
            **context: Additional context data
        """
        self.log.error(
            f"Service error during {operation}: {str(error)}",
            extra={
                "operation": operation,
                "error_type": type(error).__name__,
                "error_message": str(error),
                **context,
            },
        )

    def validate_positive_int(self, value: int, name: str) -> None:
        """
        Validate that a value is a positive integer.

        Args:
            value: Value to validate
            name: Name of the value (for error messages)

        Raises:
            ValidationError: If value is not positive
        """
        from .exceptions import ValidationError

        if not isinstance(value, int) or value <= 0:
            raise ValidationError(
                name, f"{name} must be a positive integer, got {value}"
            )

    def validate_non_negative_int(self, value: int, name: str) -> None:
        """
        Validate that a value is a non-negative integer.

        Args:
            value: Value to validate
            name: Name of the value (for error messages)

        Raises:
            ValidationError: If value is negative
        """
        from .exceptions import ValidationError

        if not isinstance(value, int) or value < 0:
            raise ValidationError(
                name, f"{name} must be a non-negative integer, got {value}"
            )

    def validate_range(
        self, value: int, name: str, min_val: int, max_val: int
    ) -> None:
        """
        Validate that a value is within a specified range.

        Args:
            value: Value to validate
            name: Name of the value (for error messages)
            min_val: Minimum allowed value (inclusive)
            max_val: Maximum allowed value (inclusive)

        Raises:
            ValidationError: If value is out of range
        """
        from .exceptions import ValidationError

        if not (min_val <= value <= max_val):
            raise ValidationError(
                name,
                f"{name} must be between {min_val} and {max_val}, got {value}",
            )
