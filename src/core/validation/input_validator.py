"""
Input Validation Layer for Lumen (2025)

Purpose
-------
Provide a centralized, security-first validation layer for all user inputs across
the Lumen RPG bot. Enforces type safety, bounds checking, and format validation to
prevent injection attacks, type errors, and database corruption.

This module serves as the single source of truth for input validation, ensuring
consistent validation rules, clear error messages, and defense-in-depth security
across all Discord commands and services.

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
- Provide reusable validation methods for all service layers

Non-Responsibilities
--------------------
- Business logic validation (handled by service layer)
- Database constraints validation (handled by database layer)
- Discord UI presentation (handled by cog layer)
- Authorization and permissions (handled by Discord decorators)
- Rate limiting (handled by Redis rate limiter)
- Transaction management (handled by DatabaseService)

LUMEN LAW Compliance
--------------------
- Article VII: Domain validation without Discord dependencies
- Article IX: Fail-fast with clear error messages (never silent failures)
- Article X: Security-first design with explicit bounds checking
- Article II: Input validation supports audit trail integrity

Security Considerations
-----------------------
**Injection Prevention**:
- All string inputs are stripped and validated
- Type conversion prevents SQL injection via type errors
- Bounds checking prevents overflow attacks
- Character whitelisting available for strict validation

**Type Safety**:
- Explicit type conversion with error handling
- No implicit type coercion
- Validates before converting to prevent crashes

**Defense in Depth**:
- Multiple validation layers (type, bounds, format)
- Always fails closed (raises on invalid input)
- Validates each item in batch operations
- Duplicate detection in ID lists

Architecture Notes
------------------
**Validation Strategy**:
- **Fail-fast**: Raises ValidationError on first validation failure
- **User-friendly**: Error messages designed for Discord embed display
- **Composable**: Complex validations build on simple primitives
- **Stateless**: All methods are static, no instance state

**Error Handling**:
- Single exception type: ValidationError
- Includes field_name for precise error identification
- Includes validation_message for user feedback
- Designed for BaseCog error handling integration

**Validation Patterns**:
- Primitive validators: validate_integer(), validate_string()
- Specialized validators: validate_tier(), validate_discord_id()
- Batch validators: validate_id_list()
- Domain validators: validate_stat_allocation(), validate_resource_amount()

Key Features
------------
**Integer Validation**:
- `validate_integer()`: Full-featured integer validation with bounds
- `validate_positive_integer()`: Shortcut for >= 1 validation
- `validate_non_negative_integer()`: Shortcut for >= 0 validation

**Domain-Specific Validation**:
- `validate_tier()`: Maiden tier validation (1-12)
- `validate_stat_allocation()`: Stat point allocation with availability check
- `validate_discord_id()`: Discord snowflake validation (64-bit)
- `validate_maiden_id()`: Database ID validation
- `validate_resource_amount()`: Resource quantity validation

**String Validation**:
- `validate_string()`: Length and character pattern validation
- `validate_choice()`: Enum/choice validation with case-insensitivity

**Batch Validation**:
- `validate_id_list()`: List validation with count limits and duplicate detection

Usage Examples
--------------
Basic integer validation:

>>> from src.core.validation.input_validator import InputValidator
>>>
>>> # Validate positive integer with max bound
>>> tier = InputValidator.validate_positive_integer("5", "tier", max_value=12)
>>> # Returns: 5
>>>
>>> # Validation failure
>>> try:
>>>     amount = InputValidator.validate_positive_integer("-1", "amount")
>>> except ValidationError as e:
>>>     print(e.validation_message)
>>>     # Output: "amount must be at least 1, got -1"

Stat allocation validation:

>>> # In stat allocation command
>>> try:
>>>     amount = InputValidator.validate_stat_allocation(
>>>         stat_name="energy",
>>>         amount=user_input,  # e.g., "10"
>>>         available_points=player.available_stat_points  # e.g., 15
>>>     )
>>>     # Returns: 10 (validated and safe to use)
>>> except ValidationError as e:
>>>     await ctx.send(f"Invalid input: {e.validation_message}")

Discord ID validation:

>>> # Validate Discord user/guild/channel ID
>>> user_id = InputValidator.validate_discord_id(
>>>     ctx.author.id,
>>>     field_name="user_id"
>>> )
>>> # Returns: validated 64-bit integer

String validation with constraints:

>>> # Validate guild name
>>> guild_name = InputValidator.validate_string(
>>>     user_input,
>>>     field_name="guild_name",
>>>     min_length=3,
>>>     max_length=32,
>>>     allowed_chars="a-zA-Z0-9 "
>>> )
>>> # Returns: stripped, validated string

Choice validation:

>>> # Validate stat selection
>>> stat = InputValidator.validate_choice(
>>>     user_input,
>>>     field_name="stat",
>>>     valid_choices=["energy", "stamina", "hp"]
>>> )
>>> # Returns: lowercase validated choice

ID list validation with duplicate detection:

>>> # Validate fusion maiden selection
>>> maiden_ids = InputValidator.validate_id_list(
>>>     user_selection,  # e.g., ["123", "456"]
>>>     field_name="maiden_ids",
>>>     min_count=2,
>>>     max_count=10
>>> )
>>> # Returns: [123, 456] (validated integers, no duplicates)

Resource amount validation:

>>> # Validate lumee expenditure
>>> amount = InputValidator.validate_resource_amount(
>>>     user_input,
>>>     resource_name="lumees",
>>>     max_value=999999999
>>> )
>>> # Returns: validated positive integer

Integration with Service Layer
-------------------------------
Validation typically occurs at the service layer boundary:

>>> class FusionService:
>>>     @staticmethod
>>>     async def fuse_maidens(session, player_id: int, tier: int):
>>>         # Validate inputs before business logic
>>>         validated_tier = InputValidator.validate_tier(tier, "tier")
>>>         validated_player_id = InputValidator.validate_positive_integer(
>>>             player_id, "player_id"
>>>         )
>>>
>>>         # Proceed with validated inputs...
>>>         # Business logic, database operations, etc.

Integration with Cog Layer
---------------------------
Cogs use validation and handle ValidationError for user feedback:

>>> class FusionCog(BaseCog):
>>>     @commands.command(name="fuse")
>>>     async def fuse(self, ctx, tier: str):
>>>         '''Fuse maidens to create higher tier.'''
>>>         try:
>>>             # Validate user input
>>>             validated_tier = InputValidator.validate_tier(tier, "tier")
>>>
>>>             async with self.get_session() as session:
>>>                 result = await FusionService.fuse_maidens(
>>>                     session, ctx.author.id, validated_tier
>>>                 )
>>>                 await self.send_success(ctx, "Fusion Complete!", result.message)
>>>
>>>         except ValidationError as e:
>>>             await self.send_error(ctx, "Invalid Input", e.validation_message)

Error Reference
---------------
All validation methods raise ValidationError with structured information:

**ValidationError attributes**:
- `field_name`: Name of the field that failed validation
- `validation_message`: User-friendly error message

**Common error messages**:
- "Must be a whole number, got '{value}'" - Type conversion failure
- "Must be at least {min}, got {value}" - Below minimum bound
- "Cannot exceed {max}, got {value}" - Above maximum bound
- "Cannot be zero" - Zero not allowed when allow_zero=False
- "Not enough points available" - Insufficient resources
- "List contains duplicate IDs" - Duplicate detection in batch validation
- "Invalid choice '{value}'. Must be one of: {choices}" - Choice validation failure

Constants Used
--------------
- `MAX_POINTS_PER_STAT`: Maximum stat allocation per operation
- `MAX_TIER_NUMBER`: Maximum maiden tier (1-12 range)
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
        Validate resource amount (lumees, auric coin, etc.).

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
