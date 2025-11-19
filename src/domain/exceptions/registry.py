"""
Exception message template registry for Lumen RPG.

Purpose
-------
Single source of truth for exception-to-message mappings following LES 2025 standards.
Provides structured templates for converting domain exceptions into user-friendly
Discord embeds with consistent formatting and helpful guidance.

LUMEN LAW / LES 2025 Compliance
-------------------------------
- Centralized exception message templates (P0.1, P1.5)
- No hardcoded error messages in cogs or presentation layer
- Separation of domain exceptions (what happened) from presentation (how to display)
- Template-based message formatting with structured metadata

Design Notes
------------
Each template contains:
- title: Short, clear error title for embed
- template: Message template with {placeholder} interpolation
- help_text: Optional helpful guidance for the user
- severity: ErrorSeverity level for visual styling
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from src.core.exceptions import (
    CacheError,
    CircuitBreakerError,
    ConfigurationError,
    DatabaseError,
    EventBusError,
    LumenInfrastructureException,
    PlayerNotFoundError,
    RedisConnectionError,
)
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
)


class ExceptionTemplate:
    """Template for formatting exception messages."""

    def __init__(
        self,
        title: str,
        template: str,
        help_text: Optional[str] = None,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
    ):
        self.title = title
        self.template = template
        self.help_text = help_text
        self.severity = severity

    def format(self, exception: Exception) -> Dict[str, Any]:
        """
        Format exception using template.

        Args:
            exception: Exception instance to format

        Returns:
            Dict with 'title', 'description', 'help_text', 'severity'
        """
        # Extract details from exception
        details = {}
        if isinstance(exception, (LumenDomainException, LumenInfrastructureException)):
            details = exception.details.copy()

        # Format message using template
        try:
            description = self.template.format(**details)
        except KeyError:
            # Fallback to exception message if template interpolation fails
            description = str(exception)

        return {
            "title": self.title,
            "description": description,
            "help_text": self.help_text,
            "severity": self.severity,
        }


# ============================================================================
# EXCEPTION TEMPLATE REGISTRY
# ============================================================================

EXCEPTION_TEMPLATES: Dict[type, ExceptionTemplate] = {
    # Domain Exceptions
    InsufficientResourcesError: ExceptionTemplate(
        title="Insufficient Resources",
        template="You need **{required:,} {resource}**, but you only have **{current:,}**.",
        help_text="Check your inventory and try again.",
        severity=ErrorSeverity.INFO,
    ),
    NotFoundError: ExceptionTemplate(
        title="Not Found",
        template="{resource_type} not found.",
        help_text=None,
        severity=ErrorSeverity.INFO,
    ),
    MaidenNotFoundError: ExceptionTemplate(
        title="Maiden Not Found",
        template="The maiden you're looking for doesn't exist in your collection.",
        help_text="Use `/maidens` to view your available maidens.",
        severity=ErrorSeverity.INFO,
    ),
    ValidationError: ExceptionTemplate(
        title="Invalid Input",
        template="**{field}**: {validation_message}",
        help_text="Please check your input and try again.",
        severity=ErrorSeverity.INFO,
    ),
    InvalidFusionError: ExceptionTemplate(
        title="Fusion Failed",
        template="{reason}",
        help_text="Check the fusion requirements and try again.",
        severity=ErrorSeverity.INFO,
    ),
    CooldownActiveError: ExceptionTemplate(
        title="Cooldown Active",
        template="**{action}** is on cooldown. Wait **{remaining:.1f}s** before retrying.",
        help_text="Please be patient!",
        severity=ErrorSeverity.DEBUG,
    ),
    RateLimitError: ExceptionTemplate(
        title="Rate Limit Exceeded",
        template="You're using this command too frequently. Wait **{retry_after:.1f}s** before retrying.",
        help_text="Please slow down!",
        severity=ErrorSeverity.DEBUG,
    ),
    InvalidOperationError: ExceptionTemplate(
        title="Invalid Operation",
        template="{reason}",
        help_text=None,
        severity=ErrorSeverity.INFO,
    ),
    # Infrastructure Exceptions
    ConfigurationError: ExceptionTemplate(
        title="Configuration Error",
        template="A system configuration error occurred. Please contact support.",
        help_text="Error code: CONFIG_ERROR",
        severity=ErrorSeverity.CRITICAL,
    ),
    DatabaseError: ExceptionTemplate(
        title="Database Error",
        template="A database error occurred. Please try again in a moment.",
        help_text="If this persists, contact support.",
        severity=ErrorSeverity.ERROR,
    ),
    PlayerNotFoundError: ExceptionTemplate(
        title="Player Not Found",
        template="Your player profile could not be found. You may need to register first.",
        help_text="Use `/start` to create your profile.",
        severity=ErrorSeverity.WARNING,
    ),
    RedisConnectionError: ExceptionTemplate(
        title="Cache Error",
        template="A caching error occurred. Please try again.",
        help_text=None,
        severity=ErrorSeverity.ERROR,
    ),
    CacheError: ExceptionTemplate(
        title="Cache Error",
        template="A caching error occurred. Please try again.",
        help_text=None,
        severity=ErrorSeverity.WARNING,
    ),
    CircuitBreakerError: ExceptionTemplate(
        title="Service Temporarily Unavailable",
        template="The **{service}** service is temporarily unavailable. Retry after **{retry_after:.1f}s**.",
        help_text="We're experiencing high load. Please be patient!",
        severity=ErrorSeverity.WARNING,
    ),
    EventBusError: ExceptionTemplate(
        title="Event Processing Error",
        template="An error occurred processing your request. Please try again.",
        help_text=None,
        severity=ErrorSeverity.ERROR,
    ),
}


def get_exception_template(exception: Exception) -> Optional[ExceptionTemplate]:
    """
    Get the appropriate template for an exception type.

    Args:
        exception: Exception instance

    Returns:
        ExceptionTemplate if found, None otherwise
    """
    exception_type = type(exception)
    return EXCEPTION_TEMPLATES.get(exception_type)
