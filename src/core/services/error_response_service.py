"""
Error Response Service for Lumen RPG.

Purpose
-------
Centralized service for formatting domain and infrastructure exceptions into
user-friendly Discord embed responses following LES 2025 standards.

LUMEN LAW / LES 2025 Compliance
-------------------------------
- Presentation layer logic extracted from cogs (P0.1)
- Single responsibility: exception → user-friendly message transformation
- Uses centralized exception registry (P1.5)
- No business logic, only formatting and presentation concerns

Responsibilities
----------------
- Format domain exceptions using EXCEPTION_TEMPLATES registry
- Format infrastructure exceptions with appropriate user messages
- Provide structured response dicts for EmbedBuilder
- Handle fallback for unknown exception types

Non-Responsibilities
--------------------
- Logging (handled by cogs/services)
- Exception creation or domain logic
- Discord embed creation (delegated to EmbedBuilder)

Architecture Notes
------------------
This service sits between the domain/infra layers and the presentation layer:
- Services raise domain exceptions with structured details
- ErrorResponseService formats them into user-friendly messages
- Cogs use EmbedBuilder to create Discord embeds from formatted messages
"""

from __future__ import annotations

from typing import Any, Dict

from src.core.exceptions import LumenInfrastructureException
from src.domain.exceptions.registry import (
    EXCEPTION_TEMPLATES,
    ExceptionTemplate,
    get_exception_template,
)
from src.modules.shared.exceptions import ErrorSeverity, LumenDomainException


class ErrorResponseService:
    """
    Service for formatting exceptions into user-friendly response messages.

    This service provides a clean separation between:
    - What went wrong (domain/infrastructure exceptions)
    - How to communicate it to users (formatted messages)
    """

    async def format_error(
        self, error: Exception
    ) -> Dict[str, Any]:
        """
        Format an exception into a user-friendly response structure.

        Args:
            error: Exception to format (domain or infrastructure)

        Returns:
            Dict containing:
                - title: Short error title
                - description: Detailed error message
                - help_text: Optional helpful guidance
                - severity: ErrorSeverity level for visual styling

        Example:
            >>> response = await error_service.format_error(
            ...     InsufficientResourcesError("lumees", 1000, 500)
            ... )
            >>> # Returns:
            >>> # {
            >>> #     "title": "Insufficient Resources",
            >>> #     "description": "You need 1,000 lumees, but you only have 500.",
            >>> #     "help_text": "Check your inventory and try again.",
            >>> #     "severity": ErrorSeverity.INFO
            >>> # }
        """
        # Try to get template from registry
        template = get_exception_template(error)

        if template is not None:
            # Use template to format the error
            return template.format(error)

        # Fallback for unknown exception types
        return self._format_fallback_error(error)

    def _format_fallback_error(self, error: Exception) -> Dict[str, Any]:
        """
        Format an unknown exception with a generic message.

        Args:
            error: Exception without a registered template

        Returns:
            Generic error response dict
        """
        # Check if it's a known base type with severity metadata
        if isinstance(error, LumenDomainException):
            severity = error.severity
            description = str(error)
        elif isinstance(error, LumenInfrastructureException):
            severity = error.severity
            description = "A system error occurred. Please try again in a moment."
        else:
            severity = ErrorSeverity.ERROR
            description = "An unexpected error occurred."

        return {
            "title": "Something Went Wrong",
            "description": description,
            "help_text": "The issue has been logged. If this persists, contact support.",
            "severity": severity,
        }

    def format_error_sync(self, error: Exception) -> Dict[str, Any]:
        """
        Synchronous version of format_error for compatibility.

        Args:
            error: Exception to format

        Returns:
            Formatted error response dict
        """
        # Try to get template from registry
        template = get_exception_template(error)

        if template is not None:
            return template.format(error)

        return self._format_fallback_error(error)
