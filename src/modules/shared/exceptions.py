"""
Domain exceptions for Lumen RPG Bot.

Purpose
-------
Define the structured, domain-specific exception hierarchy for Lumen game logic.
These exceptions are raised by services for business rule violations, resource
constraints, and player-facing errors. Cogs translate these into user-friendly
Discord embeds.

LUMEN LAW / LES 2025 Compliance
-------------------------------
- Domain exceptions only (game logic, business rules, player-facing errors)
- Clear base class (`LumenDomainException`) with structured, serializable metadata
- Severity levels for logging and user communication decisions
- Retry hints and error codes for programmatic handling
- Services use these for business rule violations
- Cogs translate these into friendly error messages

Design Notes
------------
- All domain exceptions inherit from `LumenDomainException`.
- Each exception carries:
  - `message`: human-readable description
  - `details`: additional structured context (dict-like)
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


class LumenDomainException(Exception):
    """
    Base exception for all Lumen domain-level errors.

    Provides structured error information with details for logging and user
    display. All domain exceptions should inherit from this base class.

    Args:
        message: Human-readable error message
        details: Additional structured data about the error (dict-like)
        severity: Error severity level for logging handlers
        is_retryable: Whether the operation can be retried
        error_code: Optional code for programmatic handling

    Example:
        >>> raise LumenDomainException(
        ...     "Fusion failed",
        ...     {"reason": "insufficient tier"}
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


class InsufficientResourcesError(LumenDomainException):
    """
    Raised when a player lacks required resources for an action.

    This is a normal, expected player-facing error representing insufficient
    funds, energy, stamina, or other game resources.

    Args:
        resource: Name of the resource type (e.g., "tokens", "energy")
        required: Amount required for the action
        current: Amount player currently has
    """

    DEFAULT_SEVERITY = ErrorSeverity.INFO
    DEFAULT_RETRYABLE = False

    def __init__(self, resource: str, required: int, current: int) -> None:
        self.resource = resource
        self.required = required
        self.current = current
        message = f"Insufficient {resource}: need {required:,}, have {current:,}"
        super().__init__(
            message,
            details={
                "resource": resource,
                "required": required,
                "current": current,
                "deficit": required - current,
            },
            error_code=f"INSUFFICIENT_{resource.upper()}",
        )


class NotFoundError(LumenDomainException):
    """
    Raised when a requested game resource cannot be found.

    Generic not-found error for game entities, items, or resources that
    the player attempted to access but don't exist.

    Args:
        resource_type: Type of resource (e.g., "Maiden", "Guild", "Item")
        identifier: Optional identifier for the missing resource
    """

    DEFAULT_SEVERITY = ErrorSeverity.INFO
    DEFAULT_RETRYABLE = False

    def __init__(self, resource_type: str, identifier: Optional[Any] = None) -> None:
        self.resource_type = resource_type
        self.identifier = identifier

        if identifier is not None:
            message = f"{resource_type} not found: {identifier}"
        else:
            message = f"{resource_type} not found"

        super().__init__(
            message,
            details={
                "resource_type": resource_type,
                "identifier": identifier,
            },
            error_code=f"{resource_type.upper()}_NOT_FOUND",
        )


class MaidenNotFoundError(LumenDomainException):
    """
    Raised when a maiden cannot be found in the player's collection.

    Specific case of NotFoundError for maiden entities.

    Args:
        maiden_id: Database ID of the missing maiden
        maiden_name: Optional name of the maiden for better error messages
    """

    DEFAULT_SEVERITY = ErrorSeverity.INFO
    DEFAULT_RETRYABLE = False

    def __init__(
        self,
        maiden_id: Optional[int] = None,
        maiden_name: Optional[str] = None,
    ) -> None:
        self.maiden_id = maiden_id
        self.maiden_name = maiden_name
        message = f"Maiden not found: {maiden_name or f'ID {maiden_id}'}"
        super().__init__(
            message,
            details={
                "maiden_id": maiden_id,
                "maiden_name": maiden_name,
            },
            error_code="MAIDEN_NOT_FOUND",
        )


class ValidationError(LumenDomainException):
    """
    Raised when user input fails domain validation.

    Represents validation failures for player inputs: invalid field values,
    out-of-range numbers, malformed data, etc.

    Args:
        field: Name of the field that failed validation
        message: Explanation of why validation failed
    """

    DEFAULT_SEVERITY = ErrorSeverity.INFO
    DEFAULT_RETRYABLE = False

    def __init__(self, field: str, message: str) -> None:
        self.field = field
        self.validation_message = message
        error_message = f"Validation error for {field}: {message}"
        super().__init__(
            error_message,
            details={
                "field": field,
                "validation_message": message,
            },
            error_code=f"VALIDATION_{field.upper()}",
        )


class InvalidFusionError(LumenDomainException):
    """
    Raised when a fusion operation fails for business logic reasons.

    Represents fusion rule violations: wrong tiers, incompatible maidens,
    locked maidens, etc.

    Args:
        reason: Explanation of why fusion is invalid
    """

    DEFAULT_SEVERITY = ErrorSeverity.INFO
    DEFAULT_RETRYABLE = False

    def __init__(self, reason: str) -> None:
        self.reason = reason
        message = f"Fusion failed: {reason}"
        super().__init__(
            message,
            details={"reason": reason},
            error_code="FUSION_FAILED",
        )


class CooldownActiveError(LumenDomainException):
    """
    Raised when an action is on cooldown.

    Represents game mechanic cooldowns that prevent action spam.

    Args:
        action: Name of the action on cooldown
        remaining_seconds: Time remaining until cooldown expires
    """

    DEFAULT_SEVERITY = ErrorSeverity.DEBUG
    DEFAULT_RETRYABLE = True

    def __init__(self, action: str, remaining_seconds: float) -> None:
        self.action = action
        self.remaining_seconds = remaining_seconds
        message = f"{action} is on cooldown: {remaining_seconds:.1f}s remaining"
        super().__init__(
            message,
            details={
                "action": action,
                "remaining": remaining_seconds,
                "retry_after": remaining_seconds,
            },
            error_code="COOLDOWN_ACTIVE",
            is_retryable=True,
        )


class RateLimitError(LumenDomainException):
    """
    Raised when a command rate limit is exceeded.

    Represents player-triggered rate limiting from command spam.

    Args:
        command: Name of the rate-limited command
        retry_after: Seconds until the player can retry
    """

    DEFAULT_SEVERITY = ErrorSeverity.DEBUG
    DEFAULT_RETRYABLE = True

    def __init__(self, command: str, retry_after: float) -> None:
        self.command = command
        self.retry_after = retry_after
        message = f"Rate limit exceeded for {command}: retry after {retry_after:.1f}s"
        super().__init__(
            message,
            details={
                "command": command,
                "retry_after": retry_after,
            },
            error_code="RATE_LIMIT_EXCEEDED",
            is_retryable=True,
        )


class InvalidOperationError(LumenDomainException):
    """
    Raised when a player attempts an action that violates game rules.

    Generic business rule violation: prerequisites not met, invalid state,
    operation not allowed in current context, etc.

    Args:
        action: Description of the invalid action
        reason: Explanation of why it's not allowed

    Example:
        >>> raise InvalidOperationError(
        ...     "ascend_floor",
        ...     "Player has not cleared previous floor"
        ... )
    """

    DEFAULT_SEVERITY = ErrorSeverity.INFO
    DEFAULT_RETRYABLE = False

    def __init__(self, action: str, reason: str) -> None:
        self.action = action
        self.reason = reason
        message = f"Invalid operation '{action}': {reason}"
        super().__init__(
            message,
            details={
                "action": action,
                "reason": reason,
            },
            error_code=f"INVALID_{action.upper()}",
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
    if isinstance(exc, LumenDomainException):
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
    if isinstance(exc, LumenDomainException):
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
