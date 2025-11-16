"""
Infrastructure exceptions for Lumen RPG Bot.

Purpose
-------
Define the structured exception hierarchy for infrastructure-level concerns:
database failures, configuration errors, system integrity violations, and other
engineering-level issues that require immediate technical attention.

LUMEN LAW / LES 2025 Compliance
-------------------------------
- Infrastructure exceptions only (no game logic)
- Clear base class (`LumenInfrastructureException`) with structured metadata
- Severity levels for logging and alerting decisions
- Retry hints and error codes for programmatic handling
- Services/infra components use these for technical failures
- Cogs translate these into user-facing error embeds

Design Notes
------------
- All infrastructure exceptions inherit from `LumenInfrastructureException`.
- Each exception carries:
  - `message`: human-readable description
  - `details`: additional structured context (dict)
  - `severity`: `ErrorSeverity` value for logging/alerting
  - `is_retryable`: whether the operation can be retried
  - `error_code`: short, stable identifier for programmatic use
- Helper functions (`is_transient_error`, `get_error_severity`, `should_alert`)
  centralize common exception handling patterns.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional


class ErrorSeverity(Enum):
    """Error severity levels for logging and alerting."""

    DEBUG = "debug"  # Expected, not concerning (e.g., cooldowns)
    INFO = "info"  # Normal operation (e.g., validation failures)
    WARNING = "warning"  # Concerning but handled (e.g., retryable errors)
    ERROR = "error"  # Unexpected errors requiring attention
    CRITICAL = "critical"  # System-level failures requiring immediate action


class LumenInfrastructureException(Exception):
    """
    Base exception for all Lumen infrastructure-level errors.

    Provides structured error information with details for logging and alerting.
    All infrastructure exceptions should inherit from this base class.

    Args:
        message: Human-readable error message
        details: Additional structured data about the error
        severity: Error severity level for logging handlers
        is_retryable: Whether the operation can be retried
        error_code: Optional code for programmatic handling

    Example:
        >>> raise LumenInfrastructureException(
        ...     "Database connection failed",
        ...     {"host": "localhost", "port": 5432}
        ... )
    """

    # Default severity and retry behavior (subclasses can override)
    DEFAULT_SEVERITY: ErrorSeverity = ErrorSeverity.ERROR
    DEFAULT_RETRYABLE: bool = False

    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        severity: Optional[ErrorSeverity] = None,
        is_retryable: Optional[bool] = None,
        error_code: Optional[str] = None,
    ) -> None:
        self.message: str = message
        self.details: Dict[str, Any] = details or {}
        self.severity: ErrorSeverity = severity or self.DEFAULT_SEVERITY
        self.is_retryable: bool = (
            is_retryable if is_retryable is not None else self.DEFAULT_RETRYABLE
        )
        self.error_code: str = error_code or self.__class__.__name__
        super().__init__(self.message)

    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for logging/serialization."""
        return {
            "error_type": self.__class__.__name__,
            "error_code": self.error_code,
            "message": self.message,
            "details": self.details,
            "severity": self.severity.value,
            "is_retryable": self.is_retryable,
        }

    def __str__(self) -> str:
        """String representation for logging."""
        details_str = f" | Details: {self.details}" if self.details else ""
        return f"[{self.error_code}] {self.message}{details_str}"

    def __repr__(self) -> str:
        """Detailed representation for debugging."""
        return (
            f"{self.__class__.__name__}("
            f"message={self.message!r}, "
            f"details={self.details!r}, "
            f"severity={self.severity.value!r}, "
            f"is_retryable={self.is_retryable!r}"
            ")"
        )


class ConfigurationError(LumenInfrastructureException):
    """
    Raised when a configuration key is invalid or missing.

    This represents a critical system misconfiguration that prevents
    normal operation and requires immediate engineering attention.

    Args:
        config_key: The configuration key that has issues
        message: Description of the configuration problem
    """

    DEFAULT_SEVERITY = ErrorSeverity.CRITICAL
    DEFAULT_RETRYABLE = False

    def __init__(self, config_key: str, message: str) -> None:
        self.config_key = config_key
        error_message = f"Configuration error for {config_key}: {message}"
        super().__init__(
            error_message,
            details={
                "config_key": config_key,
                "message": message,
            },
            error_code="CONFIG_ERROR",
        )


class DatabaseError(LumenInfrastructureException):
    """
    Raised when database operations fail.

    Represents infrastructure-level database failures that may be transient
    (connection issues, timeouts) or persistent (schema errors, constraints).

    Args:
        operation: Description of the database operation that failed
        original_error: The underlying database exception
    """

    DEFAULT_SEVERITY = ErrorSeverity.ERROR
    DEFAULT_RETRYABLE = True  # Many DB errors are transient

    def __init__(self, operation: str, original_error: Exception) -> None:
        self.operation = operation
        self.original_error = original_error
        message = f"Database error during {operation}: {str(original_error)}"
        super().__init__(
            message,
            details={
                "operation": operation,
                "error": str(original_error),
                "error_type": type(original_error).__name__,
            },
            error_code="DATABASE_ERROR",
            is_retryable=True,
        )


class PlayerNotFoundError(LumenInfrastructureException):
    """
    Raised when a player cannot be found in the database.

    This is treated as an infrastructure concern because players should always
    exist after registration. A missing player suggests a data integrity issue
    or system corruption that requires investigation.

    Args:
        discord_id: The Discord user ID that was not found
    """

    DEFAULT_SEVERITY = ErrorSeverity.WARNING
    DEFAULT_RETRYABLE = False

    def __init__(self, discord_id: int) -> None:
        self.discord_id = discord_id
        message = f"Player not found: {discord_id}"
        super().__init__(
            message,
            details={"discord_id": discord_id},
            error_code="PLAYER_NOT_FOUND",
        )


class RedisConnectionError(LumenInfrastructureException):
    """
    Raised when Redis connection or operations fail.

    Args:
        operation: Description of the Redis operation that failed
        original_error: The underlying Redis exception
    """

    DEFAULT_SEVERITY = ErrorSeverity.ERROR
    DEFAULT_RETRYABLE = True

    def __init__(self, operation: str, original_error: Exception) -> None:
        self.operation = operation
        self.original_error = original_error
        message = f"Redis error during {operation}: {str(original_error)}"
        super().__init__(
            message,
            details={
                "operation": operation,
                "error": str(original_error),
                "error_type": type(original_error).__name__,
            },
            error_code="REDIS_ERROR",
            is_retryable=True,
        )


class CacheError(LumenInfrastructureException):
    """
    Raised when cache operations fail.

    Args:
        operation: Description of the cache operation that failed
        cache_key: The cache key involved in the failure
        original_error: The underlying exception (if any)
    """

    DEFAULT_SEVERITY = ErrorSeverity.WARNING
    DEFAULT_RETRYABLE = True

    def __init__(
        self,
        operation: str,
        cache_key: str,
        original_error: Optional[Exception] = None,
    ) -> None:
        self.operation = operation
        self.cache_key = cache_key
        self.original_error = original_error
        error_msg = str(original_error) if original_error else "Cache operation failed"
        message = f"Cache error during {operation} for key '{cache_key}': {error_msg}"
        super().__init__(
            message,
            details={
                "operation": operation,
                "cache_key": cache_key,
                "error": error_msg,
                "error_type": (
                    type(original_error).__name__ if original_error else None
                ),
            },
            error_code="CACHE_ERROR",
            is_retryable=True,
        )


class CircuitBreakerError(LumenInfrastructureException):
    """
    Raised when a circuit breaker is open and blocking operations.

    Args:
        service: Name of the service with an open circuit breaker
        failure_count: Number of consecutive failures that opened the circuit
        retry_after: Seconds until circuit breaker can be retried
    """

    DEFAULT_SEVERITY = ErrorSeverity.WARNING
    DEFAULT_RETRYABLE = True

    def __init__(
        self, service: str, failure_count: int, retry_after: float
    ) -> None:
        self.service = service
        self.failure_count = failure_count
        self.retry_after = retry_after
        message = (
            f"Circuit breaker open for {service} "
            f"({failure_count} failures, retry after {retry_after:.1f}s)"
        )
        super().__init__(
            message,
            details={
                "service": service,
                "failure_count": failure_count,
                "retry_after": retry_after,
            },
            error_code="CIRCUIT_BREAKER_OPEN",
            is_retryable=True,
        )


class EventBusError(LumenInfrastructureException):
    """
    Raised when event bus operations fail.

    Args:
        operation: Description of the event operation that failed
        event_type: Type of event involved
        original_error: The underlying exception
    """

    DEFAULT_SEVERITY = ErrorSeverity.ERROR
    DEFAULT_RETRYABLE = True

    def __init__(
        self, operation: str, event_type: str, original_error: Exception
    ) -> None:
        self.operation = operation
        self.event_type = event_type
        self.original_error = original_error
        message = (
            f"Event bus error during {operation} "
            f"for event '{event_type}': {str(original_error)}"
        )
        super().__init__(
            message,
            details={
                "operation": operation,
                "event_type": event_type,
                "error": str(original_error),
                "error_type": type(original_error).__name__,
            },
            error_code="EVENT_BUS_ERROR",
            is_retryable=True,
        )


# Utility functions for exception handling patterns


def is_transient_error(exc: Exception) -> bool:
    """
    Check if an exception represents a transient error that can be retried.

    Args:
        exc: Exception to check

    Returns:
        True if error is retryable, False otherwise.
    """
    if isinstance(exc, LumenInfrastructureException):
        return exc.is_retryable
    return False


def get_error_severity(exc: Exception) -> ErrorSeverity:
    """
    Get the severity level of an exception for logging.

    Args:
        exc: Exception to check

    Returns:
        ErrorSeverity level.
    """
    if isinstance(exc, LumenInfrastructureException):
        return exc.severity
    return ErrorSeverity.ERROR  # Default for unknown exceptions


def should_alert(exc: Exception) -> bool:
    """
    Determine if an exception should trigger alerting.

    Args:
        exc: Exception to check

    Returns:
        True if severity is ERROR or CRITICAL, False otherwise.
    """
    severity = get_error_severity(exc)
    return severity in (ErrorSeverity.ERROR, ErrorSeverity.CRITICAL)
