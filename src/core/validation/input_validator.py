"""
Input validation layer for all user inputs.

Provides type-safe validation with security checks for all Discord commands.
Prevents injection attacks, type errors, and database corruption.

RIKI LAW Compliance:
- Article VII: Domain validation without Discord dependencies
- Security-first design with explicit bounds checking
- Clear error messages for user feedback
"""

from typing import Any, Optional, Union, List, Dict
from src.core.exceptions import ValidationError
from src.core.constants import MAX_POINTS_PER_STAT, MAX_TIER_NUMBER


class InputValidator:
    """
    Centralized input validation for all user inputs.

    All validation methods raise ValidationError with user-friendly messages.
    Never silently fails - always raises or returns validated value.
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
        allow_zero: bool = True
    ) -> int:
        """
        Validate and convert value to integer with bounds checking.

        Args:
            value: Input value to validate
            field_name: Name of field for error messages
            min_value: Minimum allowed value (inclusive)
            max_value: Maximum allowed value (inclusive)
            allow_zero: Whether zero is acceptable

        Returns:
            Validated integer value

        Raises:
            ValidationError: If validation fails

        Example:
            >>> validate_integer("5", "stat_points", min_value=0, max_value=999)
            5
            >>> validate_integer("-1", "stat_points", min_value=0)
            ValidationError: stat_points must be at least 0
        """
        # Type validation
        if value is None:
            raise ValidationError(field_name, "Value is required")

        # Convert to int
        try:
            int_value = int(value)
        except (ValueError, TypeError) as e:
            raise ValidationError(field_name, f"Must be a whole number, got '{value}'")

        # Zero check
        if not allow_zero and int_value == 0:
            raise ValidationError(field_name, "Cannot be zero")

        # Bounds checking
        if min_value is not None and int_value < min_value:
            raise ValidationError(field_name, f"Must be at least {min_value}, got {int_value}")

        if max_value is not None and int_value > max_value:
            raise ValidationError(field_name, f"Cannot exceed {max_value}, got {int_value}")

        return int_value

    @staticmethod
    def validate_positive_integer(value: Any, field_name: str, max_value: Optional[int] = None) -> int:
        """Validate that value is a positive integer (>= 1)."""
        return InputValidator.validate_integer(
            value, field_name,
            min_value=1,
            max_value=max_value,
            allow_zero=False
        )

    @staticmethod
    def validate_non_negative_integer(value: Any, field_name: str, max_value: Optional[int] = None) -> int:
        """Validate that value is a non-negative integer (>= 0)."""
        return InputValidator.validate_integer(
            value, field_name,
            min_value=0,
            max_value=max_value,
            allow_zero=True
        )

    # =========================================================================
    # STAT ALLOCATION VALIDATION
    # =========================================================================

    @staticmethod
    def validate_stat_allocation(stat_name: str, amount: Any, available_points: int) -> int:
        """
        Validate stat allocation input.

        Args:
            stat_name: Name of stat being allocated
            amount: Amount to allocate
            available_points: Player's available stat points

        Returns:
            Validated allocation amount

        Raises:
            ValidationError: If validation fails
        """
        # Validate amount is positive integer
        validated_amount = InputValidator.validate_positive_integer(
            amount, f"{stat_name}_allocation", max_value=MAX_POINTS_PER_STAT
        )

        # Check player has enough points
        if validated_amount > available_points:
            raise ValidationError(
                f"{stat_name}_allocation",
                f"Not enough points available (have {available_points}, need {validated_amount})"
            )

        # Validate stat name
        valid_stats = ["energy", "stamina", "hp"]
        if stat_name.lower() not in valid_stats:
            raise ValidationError("stat_name", f"Invalid stat '{stat_name}'. Must be one of: {', '.join(valid_stats)}")

        return validated_amount

    # =========================================================================
    # TIER VALIDATION
    # =========================================================================

    @staticmethod
    def validate_tier(value: Any, field_name: str = "tier") -> int:
        """
        Validate maiden tier number.

        Args:
            value: Tier value to validate
            field_name: Name of field for error messages

        Returns:
            Validated tier (1-12)

        Raises:
            ValidationError: If tier invalid
        """
        return InputValidator.validate_integer(
            value, field_name,
            min_value=1,
            max_value=MAX_TIER_NUMBER,
            allow_zero=False
        )

    # =========================================================================
    # ID VALIDATION
    # =========================================================================

    @staticmethod
    def validate_discord_id(value: Any, field_name: str = "discord_id") -> int:
        """
        Validate Discord ID (snowflake).

        Discord IDs are 64-bit integers.

        Args:
            value: Discord ID to validate
            field_name: Name of field for error messages

        Returns:
            Validated Discord ID

        Raises:
            ValidationError: If ID invalid
        """
        validated_id = InputValidator.validate_positive_integer(
            value, field_name,
            max_value=2**63 - 1  # Max 64-bit signed integer
        )

        # Discord snowflakes are always > 0
        if validated_id < 1:
            raise ValidationError(field_name, "Discord ID must be positive")

        return validated_id

    @staticmethod
    def validate_maiden_id(value: Any, field_name: str = "maiden_id") -> int:
        """Validate maiden database ID."""
        return InputValidator.validate_positive_integer(value, field_name)

    # =========================================================================
    # STRING VALIDATION
    # =========================================================================

    @staticmethod
    def validate_string(
        value: Any,
        field_name: str,
        min_length: Optional[int] = None,
        max_length: Optional[int] = None,
        allowed_chars: Optional[str] = None
    ) -> str:
        """
        Validate string input.

        Args:
            value: String value to validate
            field_name: Name of field for error messages
            min_length: Minimum string length
            max_length: Maximum string length
            allowed_chars: Regex pattern for allowed characters

        Returns:
            Validated string

        Raises:
            ValidationError: If validation fails
        """
        if value is None:
            raise ValidationError(field_name, "Value is required")

        # Convert to string
        str_value = str(value).strip()

        # Length validation
        if min_length is not None and len(str_value) < min_length:
            raise ValidationError(field_name, f"Must be at least {min_length} characters")

        if max_length is not None and len(str_value) > max_length:
            raise ValidationError(field_name, f"Cannot exceed {max_length} characters")

        # Character validation
        if allowed_chars is not None:
            import re
            if not re.match(f"^[{allowed_chars}]+$", str_value):
                raise ValidationError(field_name, f"Contains invalid characters")

        return str_value

    # =========================================================================
    # CHOICE VALIDATION
    # =========================================================================

    @staticmethod
    def validate_choice(value: Any, field_name: str, valid_choices: List[str]) -> str:
        """
        Validate that value is one of the allowed choices.

        Args:
            value: Value to validate
            field_name: Name of field for error messages
            valid_choices: List of valid choice values

        Returns:
            Validated choice

        Raises:
            ValidationError: If choice invalid
        """
        str_value = str(value).lower().strip()

        if str_value not in valid_choices:
            choices_str = ", ".join(valid_choices)
            raise ValidationError(
                field_name,
                f"Invalid choice '{value}'. Must be one of: {choices_str}"
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
        max_count: Optional[int] = None
    ) -> List[int]:
        """
        Validate list of IDs.

        Args:
            values: List of IDs to validate
            field_name: Name of field for error messages
            min_count: Minimum number of IDs required
            max_count: Maximum number of IDs allowed

        Returns:
            List of validated IDs

        Raises:
            ValidationError: If validation fails
        """
        # Type check
        if not isinstance(values, (list, tuple)):
            raise ValidationError(field_name, "Must be a list")

        # Count validation
        if min_count is not None and len(values) < min_count:
            raise ValidationError(field_name, f"Must provide at least {min_count} items")

        if max_count is not None and len(values) > max_count:
            raise ValidationError(field_name, f"Cannot provide more than {max_count} items")

        # Validate each ID
        validated_ids = []
        for idx, value in enumerate(values):
            try:
                validated_id = InputValidator.validate_positive_integer(
                    value, f"{field_name}[{idx}]"
                )
                validated_ids.append(validated_id)
            except ValidationError as e:
                raise ValidationError(field_name, f"Item {idx}: {e.validation_message}")

        # Check for duplicates
        if len(validated_ids) != len(set(validated_ids)):
            raise ValidationError(field_name, "List contains duplicate IDs")

        return validated_ids

    # =========================================================================
    # RESOURCE VALIDATION
    # =========================================================================

    @staticmethod
    def validate_resource_amount(
        value: Any,
        resource_name: str,
        max_value: Optional[int] = None
    ) -> int:
        """
        Validate resource amount (rikis, grace, etc.).

        Args:
            value: Amount to validate
            resource_name: Name of resource
            max_value: Optional max amount

        Returns:
            Validated amount

        Raises:
            ValidationError: If validation fails
        """
        return InputValidator.validate_positive_integer(
            value, f"{resource_name}_amount", max_value=max_value
        )
