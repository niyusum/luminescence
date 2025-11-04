"""
Domain exceptions for RIKI RPG Bot.

RIKI LAW Compliance:
- Domain exceptions only (no Discord imports)
- Structured error data for logging
- Service layer raises these, cogs convert to embeds
- Clear hierarchy with single base class

Production Enhancements:
- Better debugging with __str__ and __repr__
- Severity levels for logging handlers
- Retry hints for transient errors
- Exception codes for programmatic handling
"""

from enum import Enum
from typing import Optional, Any, Dict


class ErrorSeverity(Enum):
    """Error severity levels for logging and alerting."""
    DEBUG = "debug"       # Expected, not concerning (e.g., cooldowns)
    INFO = "info"         # Normal operation (e.g., validation failures)
    WARNING = "warning"   # Concerning but handled (e.g., retryable errors)
    ERROR = "error"       # Unexpected errors requiring attention
    CRITICAL = "critical" # System-level failures requiring immediate action


class RIKIException(Exception):
    """
    Base exception for all RIKI RPG errors.
    
    Provides structured error information with details for logging and user display.
    All custom exceptions should inherit from this base class.
    
    Args:
        message: Human-readable error message
        details: Additional structured data about the error
        severity: Error severity level for logging handlers
        is_retryable: Whether operation can be retried
        error_code: Optional code for programmatic handling
    
    Example:
        >>> raise RIKIException("Something went wrong", {"context": "fusion"})
    """
    
    # Default severity and retry behavior (subclasses can override)
    DEFAULT_SEVERITY = ErrorSeverity.ERROR
    DEFAULT_RETRYABLE = False
    
    def __init__(
        self,
        message: str,
        details: Optional[Any] = None,
        severity: Optional[ErrorSeverity] = None,
        is_retryable: Optional[bool] = None,
        error_code: Optional[str] = None
    ):
        self.message = message
        self.details = details or {}
        self.severity = severity or self.DEFAULT_SEVERITY
        self.is_retryable = is_retryable if is_retryable is not None else self.DEFAULT_RETRYABLE
        self.error_code = error_code or self.__class__.__name__
        super().__init__(self.message)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for logging/serialization."""
        return {
            "error_type": self.__class__.__name__,
            "error_code": self.error_code,
            "message": self.message,
            "details": self.details,
            "severity": self.severity.value,
            "is_retryable": self.is_retryable
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


class InsufficientResourcesError(RIKIException):
    """Raised when player lacks required resources for an action."""
    
    DEFAULT_SEVERITY = ErrorSeverity.INFO  # Expected user error
    DEFAULT_RETRYABLE = False
    
    def __init__(self, resource: str, required: int, current: int):
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
                "deficit": required - current
            },
            error_code=f"INSUFFICIENT_{resource.upper()}"
        )


class MaidenNotFoundError(RIKIException):
    """Raised when a maiden cannot be found in player's collection."""
    
    DEFAULT_SEVERITY = ErrorSeverity.INFO  # Expected user error
    DEFAULT_RETRYABLE = False
    
    def __init__(self, maiden_id: Optional[int] = None, maiden_name: Optional[str] = None):
        self.maiden_id = maiden_id
        self.maiden_name = maiden_name
        message = f"Maiden not found: {maiden_name or f'ID {maiden_id}'}"
        super().__init__(
            message,
            details={
                "maiden_id": maiden_id,
                "maiden_name": maiden_name
            },
            error_code="MAIDEN_NOT_FOUND"
        )


class PlayerNotFoundError(RIKIException):
    """Raised when a player cannot be found in the database."""
    
    DEFAULT_SEVERITY = ErrorSeverity.WARNING  # Should exist, investigate
    DEFAULT_RETRYABLE = False
    
    def __init__(self, discord_id: int):
        self.discord_id = discord_id
        message = f"Player not found: {discord_id}"
        super().__init__(
            message,
            details={"discord_id": discord_id},
            error_code="PLAYER_NOT_FOUND"
        )


class ValidationError(RIKIException):
    """Raised when user input fails validation."""
    
    DEFAULT_SEVERITY = ErrorSeverity.INFO  # Expected user error
    DEFAULT_RETRYABLE = False
    
    def __init__(self, field: str, message: str):
        self.field = field
        self.validation_message = message
        error_message = f"Validation error for {field}: {message}"
        super().__init__(
            error_message,
            details={
                "field": field,
                "validation_message": message
            },
            error_code=f"VALIDATION_{field.upper()}"
        )


class InvalidFusionError(RIKIException):
    """Raised when fusion operation fails for business logic reasons."""
    
    DEFAULT_SEVERITY = ErrorSeverity.INFO  # Expected business rule
    DEFAULT_RETRYABLE = False
    
    def __init__(self, reason: str):
        self.reason = reason
        message = f"Fusion failed: {reason}"
        super().__init__(
            message,
            details={"reason": reason},
            error_code="FUSION_FAILED"
        )


class CooldownError(RIKIException):
    """Raised when action is on cooldown."""
    
    DEFAULT_SEVERITY = ErrorSeverity.DEBUG  # Expected rate limiting
    DEFAULT_RETRYABLE = True  # Can retry after cooldown
    
    def __init__(self, action: str, remaining_seconds: float):
        self.action = action
        self.remaining_seconds = remaining_seconds
        message = f"{action} is on cooldown: {remaining_seconds:.1f}s remaining"
        super().__init__(
            message,
            details={
                "action": action,
                "remaining": remaining_seconds,
                "retry_after": remaining_seconds
            },
            error_code="COOLDOWN_ACTIVE",
            is_retryable=True
        )


class ConfigurationError(RIKIException):
    """
    Raised when a configuration key is invalid or missing.
    
    Args:
        config_key: The configuration key that has issues
        message: Description of the configuration problem
    """
    
    DEFAULT_SEVERITY = ErrorSeverity.CRITICAL  # System configuration issue
    DEFAULT_RETRYABLE = False
    
    def __init__(self, config_key: str, message: str):
        self.config_key = config_key
        error_message = f"Configuration error for {config_key}: {message}"
        super().__init__(
            error_message,
            details={
                "config_key": config_key,
                "message": message
            },
            error_code="CONFIG_ERROR"
        )


class DatabaseError(RIKIException):
    """Raised when database operations fail."""
    
    DEFAULT_SEVERITY = ErrorSeverity.ERROR  # Infrastructure failure
    DEFAULT_RETRYABLE = True  # Many DB errors are transient
    
    def __init__(self, operation: str, original_error: Exception):
        self.operation = operation
        self.original_error = original_error
        message = f"Database error during {operation}: {str(original_error)}"
        super().__init__(
            message,
            details={
                "operation": operation,
                "error": str(original_error),
                "error_type": type(original_error).__name__
            },
            error_code="DATABASE_ERROR",
            is_retryable=True
        )


class RateLimitError(RIKIException):
    """Raised when command rate limit is exceeded."""
    
    DEFAULT_SEVERITY = ErrorSeverity.DEBUG  # Expected rate limiting
    DEFAULT_RETRYABLE = True  # Can retry after delay
    
    def __init__(self, command: str, retry_after: float):
        self.command = command
        self.retry_after = retry_after
        message = f"Rate limit exceeded for {command}: retry after {retry_after:.1f}s"
        super().__init__(
            message,
            details={
                "command": command,
                "retry_after": retry_after
            },
            error_code="RATE_LIMIT_EXCEEDED",
            is_retryable=True
        )


class InvalidOperationError(RIKIException):
    """
    Raised when a player attempts an action that is not allowed 
    or violates game rules.
    
    Args:
        action: Description of the invalid action
        reason: Explanation of why it's not allowed
    
    Example:
        >>> raise InvalidOperationError("ascend_floor", "Player has not cleared previous floor")
    """
    
    DEFAULT_SEVERITY = ErrorSeverity.INFO  # Expected game rule violation
    DEFAULT_RETRYABLE = False
    
    def __init__(self, action: str, reason: str):
        self.action = action
        self.reason = reason
        message = f"Invalid operation '{action}': {reason}"
        super().__init__(
            message,
            details={
                "action": action,
                "reason": reason
            },
            error_code=f"INVALID_{action.upper()}"
        )


# Utility functions for exception handling patterns

def is_transient_error(exc: Exception) -> bool:
    """
    Check if an exception represents a transient error that can be retried.
    
    Args:
        exc: Exception to check
        
    Returns:
        True if error is retryable, False otherwise
    """
    if isinstance(exc, RIKIException):
        return exc.is_retryable
    return False


def get_error_severity(exc: Exception) -> ErrorSeverity:
    """
    Get the severity level of an exception for logging.
    
    Args:
        exc: Exception to check
        
    Returns:
        ErrorSeverity level
    """
    if isinstance(exc, RIKIException):
        return exc.severity
    return ErrorSeverity.ERROR  # Default for unknown exceptions


def should_alert(exc: Exception) -> bool:
    """
    Determine if an exception should trigger alerting.
    
    Args:
        exc: Exception to check
        
    Returns:
        True if severity is ERROR or CRITICAL
    """
    severity = get_error_severity(exc)
    return severity in (ErrorSeverity.ERROR, ErrorSeverity.CRITICAL)