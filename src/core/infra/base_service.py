"""
Base service class for RIKI LAW compliant domain services.

Provides common utilities and enforces architectural patterns
for all feature services in the RIKI RPG Bot.

RIKI LAW Compliance:
- Article II: Automatic transaction logging utilities
- Article III: Service layer pattern enforcement
- Article VII: Clean separation from Discord layer

Usage:
    Services should use static methods with AsyncSession parameters:

    >>> class MyService:
    ...     @staticmethod
    ...     async def do_something(session: AsyncSession, player_id: int):
    ...         # Use BaseService utilities
    ...         await BaseService.log_transaction(
    ...             session, player_id, "action", {"detail": "value"}
    ...         )

Design Philosophy:
    - Services use static methods (no instance state)
    - AsyncSession passed explicitly for transaction control
    - BaseService provides utility functions, not base class
    - Encourages functional composition over inheritance
"""

from typing import Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.infra.transaction_logger import TransactionLogger
from src.core.logging.logger import get_logger, LogContext

logger = get_logger(__name__)


class BaseService:
    """
    Utility class for common service operations.

    Not meant to be inherited - use as a namespace for shared utilities.
    Services should remain stateless with static methods.
    """

    # ========================================================================
    # TRANSACTION LOGGING UTILITIES
    # ========================================================================

    @staticmethod
    async def log_transaction(
        session: AsyncSession,
        player_id: int,
        action: str,
        details: Dict[str, Any],
        context: Optional[str] = None
    ) -> None:
        """
        Log a transaction for audit trail (RIKI LAW Article II).

        Convenience wrapper around TransactionLogger for consistent
        logging across all services.

        Args:
            session: Database session
            player_id: Player's Discord ID
            action: Action being performed (e.g., "ascension_attack")
            details: Dictionary with transaction details
            context: Optional context string for debugging

        Example:
            >>> await BaseService.log_transaction(
            ...     session,
            ...     player_id=123456789,
            ...     action="maiden_fusion",
            ...     details={
            ...         "tier_from": 5,
            ...         "tier_to": 6,
            ...         "cost": 1000
            ...     },
            ...     context="fusion_success"
            ... )
        """
        transaction_logger = TransactionLogger(session)
        await transaction_logger.log(
            user_id=player_id,
            action=action,
            details=details,
            context=context or action
        )

    # ========================================================================
    # ERROR HANDLING UTILITIES
    # ========================================================================

    @staticmethod
    def log_error(
        service_name: str,
        operation: str,
        error: Exception,
        player_id: Optional[int] = None,
        **kwargs
    ) -> None:
        """
        Log service errors with consistent formatting.

        Args:
            service_name: Name of the service (e.g., "AscensionService")
            operation: Operation that failed (e.g., "attack_boss")
            error: Exception that occurred
            player_id: Optional player ID for context
            **kwargs: Additional context to log

        Example:
            >>> try:
            ...     # some operation
            ... except InsufficientResourcesError as e:
            ...     BaseService.log_error(
            ...         "FusionService",
            ...         "perform_fusion",
            ...         e,
            ...         player_id=123456789,
            ...         required_rikis=1000,
            ...         player_rikis=500
            ...     )
            ...     raise
        """
        context = LogContext(
            service=service_name,
            operation=operation,
            player_id=player_id,
            **kwargs
        )
        logger.error(
            f"{service_name}.{operation} failed: {str(error)}",
            exc_info=error,
            extra={"context": context}
        )

    # ========================================================================
    # VALIDATION UTILITIES
    # ========================================================================

    @staticmethod
    def validate_positive(value: int, field_name: str) -> None:
        """
        Validate that a value is positive.

        Args:
            value: Value to check
            field_name: Name of field for error message

        Raises:
            ValueError: If value is not positive

        Example:
            >>> BaseService.validate_positive(5, "amount")  # OK
            >>> BaseService.validate_positive(-1, "amount")  # ValueError
        """
        if value <= 0:
            raise ValueError(f"{field_name} must be positive, got {value}")

    @staticmethod
    def validate_non_negative(value: int, field_name: str) -> None:
        """
        Validate that a value is non-negative.

        Args:
            value: Value to check
            field_name: Name of field for error message

        Raises:
            ValueError: If value is negative

        Example:
            >>> BaseService.validate_non_negative(0, "amount")  # OK
            >>> BaseService.validate_non_negative(-1, "amount")  # ValueError
        """
        if value < 0:
            raise ValueError(f"{field_name} must be non-negative, got {value}")

    @staticmethod
    def validate_range(
        value: int,
        min_val: int,
        max_val: int,
        field_name: str
    ) -> None:
        """
        Validate that a value is within a range.

        Args:
            value: Value to check
            min_val: Minimum allowed value (inclusive)
            max_val: Maximum allowed value (inclusive)
            field_name: Name of field for error message

        Raises:
            ValueError: If value is out of range

        Example:
            >>> BaseService.validate_range(5, 1, 10, "tier")  # OK
            >>> BaseService.validate_range(15, 1, 10, "tier")  # ValueError
        """
        if not (min_val <= value <= max_val):
            raise ValueError(
                f"{field_name} must be between {min_val} and {max_val}, got {value}"
            )

    # ========================================================================
    # SESSION UTILITIES
    # ========================================================================

    @staticmethod
    async def commit_with_logging(
        session: AsyncSession,
        operation: str,
        player_id: Optional[int] = None
    ) -> None:
        """
        Commit session with error logging on failure.

        Args:
            session: Database session to commit
            operation: Description of operation for logging
            player_id: Optional player ID for context

        Raises:
            Exception: Re-raises any commit errors after logging

        Example:
            >>> # After making changes
            >>> await BaseService.commit_with_logging(
            ...     session,
            ...     operation="fusion_completion",
            ...     player_id=123456789
            ... )
        """
        try:
            await session.commit()
        except Exception as e:
            await session.rollback()
            BaseService.log_error(
                "BaseService",
                "commit_with_logging",
                e,
                player_id=player_id,
                operation=operation
            )
            raise

    @staticmethod
    async def rollback_with_logging(
        session: AsyncSession,
        reason: str,
        player_id: Optional[int] = None
    ) -> None:
        """
        Rollback session with logging.

        Args:
            session: Database session to rollback
            reason: Reason for rollback
            player_id: Optional player ID for context

        Example:
            >>> if validation_failed:
            ...     await BaseService.rollback_with_logging(
            ...         session,
            ...         reason="Insufficient resources",
            ...         player_id=123456789
            ...     )
        """
        await session.rollback()
        logger.warning(
            f"Session rollback: {reason}",
            extra={
                "context": LogContext(
                    service="BaseService",
                    operation="rollback",
                    player_id=player_id,
                    reason=reason
                )
            }
        )
