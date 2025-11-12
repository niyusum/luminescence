"""
Transaction log validation and size limiting (SEC-07).

Features:
- Schema validation for transaction log details by transaction type
- Size limit enforcement (10KB max per transaction)
- PII scrubbing for sensitive data
- Clear error messages for validation failures

LUMEN LAW Compliance:
- Article II: Ensures transaction log integrity
- Article IX: Graceful error handling with clear messages
"""

from typing import Dict, Any, Optional, Set, List
import json
from datetime import datetime

from src.core.exceptions import ValidationError


class TransactionValidator:
    """
    Validates transaction log data to ensure integrity and prevent abuse.

    Enforces:
    - Schema validation per transaction type
    - 10KB size limit per transaction
    - PII scrubbing (email, IP addresses, etc.)
    - Required field validation
    """

    # Maximum size for transaction details (10KB)
    MAX_DETAILS_SIZE_BYTES = 10 * 1024

    # Allowed fields per transaction type
    TRANSACTION_SCHEMAS: Dict[str, Set[str]] = {
        # Resource changes
        "resource_change_lumees": {"resource", "old_value", "new_value", "delta", "reason"},
        "resource_change_auric_coin": {"resource", "old_value", "new_value", "delta", "reason"},
        "resource_change_energy": {"resource", "old_value", "new_value", "delta", "reason"},
        "resource_change_stamina": {"resource", "old_value", "new_value", "delta", "reason"},
        "resource_change_hp": {"resource", "old_value", "new_value", "delta", "reason"},
        "resource_change_drop_charges": {"resource", "old_value", "new_value", "delta", "reason"},
        "resource_change_lumenite": {"resource", "old_value", "new_value", "delta", "reason"},
        "resource_change_experience": {"resource", "old_value", "new_value", "delta", "reason"},

        # Maiden operations
        "maiden_acquired": {"maiden_id", "maiden_name", "tier", "quantity_change", "action", "source"},
        "maiden_fused": {"maiden_id", "maiden_name", "tier", "quantity_change", "action", "target_tier"},
        "maiden_consumed": {"maiden_id", "maiden_name", "tier", "quantity_change", "action", "reason"},

        # Game operations
        "fusion_attempt": {"success", "input_tier", "result_tier", "cost", "outcome", "roll", "success_rate"},
        "summon_attempt": {"tier", "maiden_name", "maiden_base", "cost", "source", "pity_used"},
        "drop_performed": {"shrine_type", "cost", "rewards", "success", "multiplier"},
        "level_up": {"old_level", "new_level", "stat_points_awarded", "full_refresh"},
        "quest_completed": {"quest_id", "quest_name", "sector", "rewards", "completion_time"},
        "combat_result": {"opponent_type", "opponent_level", "victory", "rewards", "damage_dealt", "damage_taken"},
        "ascension_attempt": {"floor", "success", "rewards", "damage_taken", "time_elapsed"},
        "stat_allocation": {"energy_points", "stamina_points", "hp_points", "total_points"},
        "guild_contribution": {"guild_id", "contribution_type", "amount", "bonus_applied"},

        # Admin/system operations
        "admin_grant": {"resource", "amount", "admin_id", "reason"},
        "admin_revoke": {"resource", "amount", "admin_id", "reason"},
        "system_correction": {"correction_type", "old_value", "new_value", "reason"},
    }

    # Required fields per transaction type
    REQUIRED_FIELDS: Dict[str, Set[str]] = {
        "resource_change_lumees": {"resource", "old_value", "new_value", "delta", "reason"},
        "resource_change_auric_coin": {"resource", "old_value", "new_value", "delta", "reason"},
        "resource_change_energy": {"resource", "old_value", "new_value", "delta", "reason"},
        "resource_change_stamina": {"resource", "old_value", "new_value", "delta", "reason"},
        "resource_change_hp": {"resource", "old_value", "new_value", "delta", "reason"},
        "resource_change_drop_charges": {"resource", "old_value", "new_value", "delta", "reason"},
        "resource_change_lumenite": {"resource", "old_value", "new_value", "delta", "reason"},
        "resource_change_experience": {"resource", "old_value", "new_value", "delta", "reason"},
        "fusion_attempt": {"success", "input_tier", "cost", "outcome"},
        "summon_attempt": {"tier", "maiden_name", "cost"},
        "level_up": {"old_level", "new_level", "stat_points_awarded"},
        # Add more as needed
    }

    # PII patterns to scrub (basic implementation)
    PII_FIELDS = {"email", "ip_address", "password", "token", "api_key", "secret"}

    @staticmethod
    def validate_transaction(
        transaction_type: str,
        details: Dict[str, Any],
        allow_unknown_types: bool = True
    ) -> Dict[str, Any]:
        """
        Validate and sanitize transaction log data.

        Args:
            transaction_type: Type of transaction
            details: Transaction details dictionary
            allow_unknown_types: If True, allow transaction types not in schema (default True)

        Returns:
            Sanitized details dictionary

        Raises:
            ValidationError: If validation fails

        Example:
            >>> details = {"resource": "lumees", "old_value": 100, "new_value": 150, "delta": 50, "reason": "quest"}
            >>> sanitized = TransactionValidator.validate_transaction("resource_change_lumees", details)
        """
        # 1. Validate transaction type
        if not transaction_type:
            raise ValidationError("transaction_type", "Transaction type is required")

        if not isinstance(transaction_type, str):
            raise ValidationError("transaction_type", "Transaction type must be a string")

        if len(transaction_type) > 100:
            raise ValidationError("transaction_type", "Transaction type too long (max 100 characters)")

        # 2. Validate details is a dict
        if not isinstance(details, dict):
            raise ValidationError("details", "Transaction details must be a dictionary")

        # 3. Check size limit (10KB)
        details_json = json.dumps(details, default=str)
        size_bytes = len(details_json.encode('utf-8'))

        if size_bytes > TransactionValidator.MAX_DETAILS_SIZE_BYTES:
            size_kb = size_bytes / 1024
            max_kb = TransactionValidator.MAX_DETAILS_SIZE_BYTES / 1024
            raise ValidationError(
                "details",
                f"Transaction details too large ({size_kb:.1f}KB exceeds {max_kb:.0f}KB limit). "
                "Please reduce the amount of data being logged."
            )

        # 4. Scrub PII
        sanitized_details = TransactionValidator._scrub_pii(details)

        # 5. Validate schema if transaction type is known
        if transaction_type in TransactionValidator.TRANSACTION_SCHEMAS:
            allowed_fields = TransactionValidator.TRANSACTION_SCHEMAS[transaction_type]
            required_fields = TransactionValidator.REQUIRED_FIELDS.get(transaction_type, set())

            # Check required fields
            missing_fields = required_fields - sanitized_details.keys()
            if missing_fields:
                raise ValidationError(
                    "details",
                    f"Missing required fields for {transaction_type}: {', '.join(missing_fields)}"
                )

            # Check for extra fields (warning, not error)
            extra_fields = set(sanitized_details.keys()) - allowed_fields
            if extra_fields:
                # Log warning but don't fail - allows for schema evolution
                from src.core.logging.logger import get_logger
                logger = get_logger(__name__)
                logger.warning(
                    f"Transaction {transaction_type} has unexpected fields: {extra_fields}. "
                    "Consider updating TRANSACTION_SCHEMAS."
                )

        elif not allow_unknown_types:
            raise ValidationError(
                "transaction_type",
                f"Unknown transaction type: {transaction_type}. "
                f"Known types: {', '.join(sorted(TransactionValidator.TRANSACTION_SCHEMAS.keys()))}"
            )

        return sanitized_details

    @staticmethod
    def _scrub_pii(details: Dict[str, Any]) -> Dict[str, Any]:
        """
        Remove or redact PII fields from transaction details.

        Args:
            details: Transaction details dictionary

        Returns:
            Sanitized dictionary with PII removed
        """
        sanitized = {}

        for key, value in details.items():
            # Check if field name suggests PII
            if any(pii_field in key.lower() for pii_field in TransactionValidator.PII_FIELDS):
                sanitized[key] = "[REDACTED]"
            elif isinstance(value, dict):
                # Recursively scrub nested dicts
                sanitized[key] = TransactionValidator._scrub_pii(value)
            elif isinstance(value, list):
                # Scrub lists of dicts
                sanitized[key] = [
                    TransactionValidator._scrub_pii(item) if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                sanitized[key] = value

        return sanitized

    @staticmethod
    def validate_context(context: Optional[str]) -> str:
        """
        Validate transaction context string.

        Args:
            context: Context string (command name, event, etc.)

        Returns:
            Validated context string (defaults to "unknown" if None)

        Raises:
            ValidationError: If context is invalid
        """
        if context is None:
            return "unknown"

        if not isinstance(context, str):
            raise ValidationError("context", "Context must be a string")

        if len(context) > 500:
            raise ValidationError("context", "Context too long (max 500 characters)")

        return context

    @staticmethod
    def add_transaction_type_schema(
        transaction_type: str,
        allowed_fields: Set[str],
        required_fields: Optional[Set[str]] = None
    ) -> None:
        """
        Register a new transaction type schema at runtime.

        Useful for plugins or dynamically-added transaction types.

        Args:
            transaction_type: Name of the transaction type
            allowed_fields: Set of allowed field names
            required_fields: Optional set of required field names

        Example:
            >>> TransactionValidator.add_transaction_type_schema(
            ...     "custom_event",
            ...     {"event_id", "event_type", "participants", "rewards"},
            ...     {"event_id", "event_type"}
            ... )
        """
        TransactionValidator.TRANSACTION_SCHEMAS[transaction_type] = allowed_fields

        if required_fields:
            TransactionValidator.REQUIRED_FIELDS[transaction_type] = required_fields

    @staticmethod
    def get_supported_transaction_types() -> List[str]:
        """
        Get list of all supported transaction types.

        Returns:
            Sorted list of transaction type names
        """
        return sorted(TransactionValidator.TRANSACTION_SCHEMAS.keys())

    @staticmethod
    def get_schema_for_type(transaction_type: str) -> Optional[Dict[str, Any]]:
        """
        Get schema information for a transaction type.

        Args:
            transaction_type: Name of the transaction type

        Returns:
            Dictionary with 'allowed_fields' and 'required_fields', or None if unknown

        Example:
            >>> schema = TransactionValidator.get_schema_for_type("fusion_attempt")
            >>> print(schema['required_fields'])
            {'success', 'input_tier', 'cost', 'outcome'}
        """
        if transaction_type not in TransactionValidator.TRANSACTION_SCHEMAS:
            return None

        return {
            "allowed_fields": TransactionValidator.TRANSACTION_SCHEMAS[transaction_type],
            "required_fields": TransactionValidator.REQUIRED_FIELDS.get(transaction_type, set())
        }
