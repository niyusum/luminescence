"""
Input Validation Layer for Lumen (2025)

Purpose
-------
Provide a centralized, security-first validation layer for all user inputs across
the Lumen RPG bot. Enforces type safety, bounds checking, and format validation to
prevent injection attacks, type errors, and database corruption.

This module is the single source of truth for low-level input validation rules,
ensuring consistent behavior, clear error messages, and defense-in-depth security
across Discord commands and services.

Responsibilities
----------------
- Validate and convert user inputs to correct types (int, str, list, etc.)
- Enforce bounds checking for numerical inputs (min/max validation)
- Validate Discord snowflake IDs and database IDs
- Validate stat allocation requests against available points
- Validate tier numbers against game constants
- Validate string length and character restrictions
- Validate choice inputs against allowed options
- Validate ID lists with duplicate detection
- Validate resource amounts (lumees, auric coin, etc.)
- Raise ValidationError with user-friendly error messages

Non-Responsibilities
--------------------
- Business logic validation (service layer concern)
- Database constraints and persistence (database/infra concern)
- Discord UI presentation (cog/view concern)
- Authorization and permissions (Discord decorators/guards)
- Transactions, locking, or side effects (service/infra concerns)

Lumen Engineering Standard 2025 Compliance
------------------------------------------
- Separation of concerns: validation only, no business logic
- Security-first design with explicit bounds and type validation
- Fail-fast behavior with domain-specific ValidationError
- No hard-coded game-balance values; pulled via constants module that
  is expected to be backed by ConfigManager
- Structured logging for validation failures (debug-level)

Observability
-------------
- Every validation failure is logged at debug level with:
  - field_name
  - raw_value (repr)
  - reason/message

This is intentionally low-level logging (debug only) to aid investigation
without polluting production logs at info/error levels.

Dependencies
------------
- src.core.exceptions.ValidationError
- src.core.constants.MAX_POINTS_PER_STAT
- src.core.constants.MAX_TIER_NUMBER
- src.core.logging.logger.get_logger
"""

from __future__ import annotations

from typing import Any, List, Optional, Sequence, NoReturn

from src.modules.shared.exceptions import ValidationError
from src.modules.shared.constants import MAX_POINTS_PER_STAT, MAX_TIER_NUMBER
from src.core.logging.logger import get_logger

logger = get_logger(__name__)


def _raise_validation_error(field_name: str, value: Any, message: str) -> NoReturn:
    """
    Centralized helper to log and raise a ValidationError.

    All validation failures go through this function to ensure consistent,
    structured logging and error construction.
    """
    logger.debug(
        "Input validation failed",
        extra={
            "field_name": field_name,
            "raw_value": repr(value),
            "reason": message,
        },
    )
    raise ValidationError(field_name, message)


class InputValidator:
    """
    Centralized input validation for all user inputs.

    All validation methods:
    - Are stateless and deterministic
    - Return validated values on success
    - Raise ValidationError on failure (never silently fail)
    """

    # =========================================================================
    # INTEGER VALIDATION
    # =========================================================================

    @staticmethod
    def validate_integer(
        value: Any,
        field_name: str,
        min_value: Optional[int] = None,
        max_value: Optional[int] = None,
        allow_zero: bool = True,
    ) -> int:
        """
        Validate and convert value to integer with optional bounds checking.

        Args:
            value: Input value to validate (string, int, etc.)
            field_name: Name of field for error messages/logging
            min_value: Minimum allowed value (inclusive)
            max_value: Maximum allowed value (inclusive)
            allow_zero: Whether zero is acceptable

        Returns:
            Validated integer value

        Raises:
            ValidationError: If validation fails
        """
        if value is None:
            _raise_validation_error(field_name, value, "Value is required")

        try:
            int_value = int(value)
        except (ValueError, TypeError):
            _raise_validation_error(
                field_name,
                value,
                f"Must be a whole number, got '{value}'",
            )

        if not allow_zero and int_value == 0:
            _raise_validation_error(field_name, int_value, "Cannot be zero")

        if min_value is not None and int_value < min_value:
            _raise_validation_error(
                field_name,
                int_value,
                f"Must be at least {min_value}, got {int_value}",
            )

        if max_value is not None and int_value > max_value:
            _raise_validation_error(
                field_name,
                int_value,
                f"Cannot exceed {max_value}, got {int_value}",
            )

        return int_value

    @staticmethod
    def validate_positive_integer(
        value: Any,
        field_name: str,
        max_value: Optional[int] = None,
    ) -> int:
        """
        Validate that value is a strictly positive integer (>= 1).
        """
        return InputValidator.validate_integer(
            value=value,
            field_name=field_name,
            min_value=1,
            max_value=max_value,
            allow_zero=False,
        )

    @staticmethod
    def validate_non_negative_integer(
        value: Any,
        field_name: str,
        max_value: Optional[int] = None,
    ) -> int:
        """
        Validate that value is a non-negative integer (>= 0).
        """
        return InputValidator.validate_integer(
            value=value,
            field_name=field_name,
            min_value=0,
            max_value=max_value,
            allow_zero=True,
        )

    # =========================================================================
    # STAT ALLOCATION VALIDATION
    # =========================================================================

    @staticmethod
    def validate_stat_allocation(
        stat_name: str,
        amount: Any,
        available_points: int,
    ) -> int:
        """
        Validate stat allocation input.

        Args:
            stat_name: Name of stat being allocated (e.g., "energy")
            amount: Amount to allocate (string or int)
            available_points: Player's available stat points

        Returns:
            Validated allocation amount

        Raises:
            ValidationError: If validation fails
        """
        validated_amount = InputValidator.validate_positive_integer(
            amount,
            field_name=f"{stat_name}_allocation",
            max_value=MAX_POINTS_PER_STAT,
        )

        if validated_amount > available_points:
            _raise_validation_error(
                f"{stat_name}_allocation",
                validated_amount,
                f"Not enough points available (have {available_points}, need {validated_amount})",
            )

        valid_stats = ("energy", "stamina", "hp")
        if stat_name.lower() not in valid_stats:
            _raise_validation_error(
                "stat_name",
                stat_name,
                f"Invalid stat '{stat_name}'. Must be one of: {', '.join(valid_stats)}",
            )

        return validated_amount

    # =========================================================================
    # TIER VALIDATION
    # =========================================================================

    @staticmethod
    def validate_tier(
        value: Any,
        field_name: str = "tier",
    ) -> int:
        """
        Validate maiden tier number.

        Args:
            value: Tier value to validate
            field_name: Name of field for error messages

        Returns:
            Validated tier within [1, MAX_TIER_NUMBER]

        Raises:
            ValidationError: If tier is invalid
        """
        return InputValidator.validate_integer(
            value=value,
            field_name=field_name,
            min_value=1,
            max_value=MAX_TIER_NUMBER,
            allow_zero=False,
        )

    # =========================================================================
    # ID VALIDATION
    # =========================================================================

    @staticmethod
    def validate_discord_id(
        value: Any,
        field_name: str = "discord_id",
    ) -> int:
        """
        Validate Discord ID (snowflake).

        Discord IDs are 64-bit positive integers.

        Args:
            value: Discord ID to validate
            field_name: Name of field for error messages

        Returns:
            Validated Discord ID

        Raises:
            ValidationError: If ID is invalid
        """
        validated_id = InputValidator.validate_positive_integer(
            value=value,
            field_name=field_name,
            max_value=2**63 - 1,  # max 64-bit signed integer
        )

        if validated_id < 1:
            _raise_validation_error(field_name, validated_id, "Discord ID must be positive")

        return validated_id

    @staticmethod
    def validate_maiden_id(
        value: Any,
        field_name: str = "maiden_id",
    ) -> int:
        """
        Validate maiden database ID as a positive integer.
        """
        return InputValidator.validate_positive_integer(value, field_name=field_name)

    # =========================================================================
    # STRING VALIDATION
    # =========================================================================

    @staticmethod
    def validate_string(
        value: Any,
        field_name: str,
        min_length: Optional[int] = None,
        max_length: Optional[int] = None,
        allowed_chars: Optional[str] = None,
    ) -> str:
        """
        Validate string input with optional length and character constraints.

        Args:
            value: String value to validate (any object, converted via str())
            field_name: Name of field for error messages
            min_length: Minimum string length
            max_length: Maximum string length
            allowed_chars: Regex character class for allowed characters
                           (e.g., 'a-zA-Z0-9 ')

        Returns:
            Validated string

        Raises:
            ValidationError: If validation fails
        """
        if value is None:
            _raise_validation_error(field_name, value, "Value is required")

        str_value = str(value).strip()

        if min_length is not None and len(str_value) < min_length:
            _raise_validation_error(
                field_name,
                str_value,
                f"Must be at least {min_length} characters",
            )

        if max_length is not None and len(str_value) > max_length:
            _raise_validation_error(
                field_name,
                str_value,
                f"Cannot exceed {max_length} characters",
            )

        if allowed_chars is not None:
            import re

            pattern = f"^[{allowed_chars}]+$"
            if not re.match(pattern, str_value):
                _raise_validation_error(
                    field_name,
                    str_value,
                    "Contains invalid characters",
                )

        return str_value

    # =========================================================================
    # CHOICE VALIDATION
    # =========================================================================

    @staticmethod
    def validate_choice(
        value: Any,
        field_name: str,
        valid_choices: Sequence[str],
    ) -> str:
        """
        Validate that value is one of the allowed choices (case-insensitive).

        Args:
            value: Value to validate
            field_name: Name of field for error messages
            valid_choices: Iterable of valid choice values

        Returns:
            Lowercased validated choice

        Raises:
            ValidationError: If choice is invalid
        """
        str_value = str(value).lower().strip()
        normalized_choices = {choice.lower() for choice in valid_choices}

        if str_value not in normalized_choices:
            choices_str = ", ".join(sorted(valid_choices))
            _raise_validation_error(
                field_name,
                value,
                f"Invalid choice '{value}'. Must be one of: {choices_str}",
            )

        return str_value

    # =========================================================================
    # BATCH VALIDATION
    # =========================================================================

    @staticmethod
    def validate_id_list(
        values: Any,
        field_name: str,
        min_count: Optional[int] = None,
        max_count: Optional[int] = None,
    ) -> List[int]:
        """
        Validate a list of IDs (integers) with optional count limits.

        Args:
            values: Sequence of ID-like values to validate
            field_name: Name of field for error messages
            min_count: Minimum number of IDs required
            max_count: Maximum number of IDs allowed

        Returns:
            List of validated integer IDs

        Raises:
            ValidationError: If validation fails
        """
        if not isinstance(values, (list, tuple)):
            _raise_validation_error(field_name, values, "Must be a list")

        if min_count is not None and len(values) < min_count:
            _raise_validation_error(
                field_name,
                values,
                f"Must provide at least {min_count} items",
            )

        if max_count is not None and len(values) > max_count:
            _raise_validation_error(
                field_name,
                values,
                f"Cannot provide more than {max_count} items",
            )

        validated_ids: List[int] = []

        for idx, raw_value in enumerate(values):
            try:
                validated_id = InputValidator.validate_positive_integer(
                    raw_value,
                    field_name=f"{field_name}[{idx}]",
                )
                validated_ids.append(validated_id)
            except ValidationError as exc:
                # Re-raise with aggregated context on the parent field
                _raise_validation_error(
                    field_name,
                    raw_value,
                    f"Item {idx}: {exc.validation_message}",
                )

        if len(validated_ids) != len(set(validated_ids)):
            _raise_validation_error(field_name, validated_ids, "List contains duplicate IDs")

        return validated_ids

    # =========================================================================
    # RESOURCE VALIDATION
    # =========================================================================

    @staticmethod
    def validate_resource_amount(
        value: Any,
        resource_name: str,
        max_value: Optional[int] = None,
    ) -> int:
        """
        Validate resource amount (lumees, auric coin, etc.).

        Args:
            value: Amount to validate
            resource_name: Name of resource (used for field_name)
            max_value: Optional maximum amount

        Returns:
            Validated positive integer amount

        Raises:
            ValidationError: If validation fails
        """
        field_name = f"{resource_name}_amount"
        return InputValidator.validate_positive_integer(
            value=value,
            field_name=field_name,
            max_value=max_value,
        )

