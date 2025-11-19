"""
Domain exceptions package for Lumen RPG.

Purpose
-------
Centralized domain exception definitions and error message templates following
LES 2025 standards. Provides structured exception hierarchy and message formatting
for all business rule violations.

Exports
-------
- All domain exception classes (re-exported from modules.shared.exceptions for compatibility)
- EXCEPTION_TEMPLATES: Registry mapping exception types to user-friendly templates
- ErrorResponseService: Service for formatting exceptions into user-facing messages
"""

# Re-export domain exceptions for backward compatibility
# These are still defined in src/modules/shared/exceptions.py
from src.modules.shared.exceptions import (
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

from .registry import EXCEPTION_TEMPLATES

__all__ = [
    # Exception classes
    "LumenDomainException",
    "InsufficientResourcesError",
    "NotFoundError",
    "MaidenNotFoundError",
    "ValidationError",
    "InvalidFusionError",
    "CooldownActiveError",
    "RateLimitError",
    "InvalidOperationError",
    "ErrorSeverity",
    # Utilities
    "is_transient_error",
    "get_error_severity",
    "should_alert",
    # Registry
    "EXCEPTION_TEMPLATES",
]
