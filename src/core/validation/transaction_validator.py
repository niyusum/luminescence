"""
Transaction log validation and size limiting (SEC-07).

Purpose
-------
Provide a dedicated validation layer for transaction log entries to ensure the
audit trail is safe, bounded in size, and free of sensitive information.

Features
--------
- Schema validation for transaction log details by transaction type
- Size limit enforcement (10KB max per transaction's JSON payload)
- PII scrubbing for sensitive data fields and nested structures
- Clear, domain-specific error messages for validation failures
- Structured logging for schema drift and validation issues

Lumen Engineering Standard 2025 Compliance
------------------------------------------
- Article II: Ensures transaction log integrity
- Observability-first: structured logs for unexpected fields and failures
- No direct side effects beyond validation and logging
- Designed as a pure helper for services/infra that emit transaction logs

Responsibilities
----------------
- Validate the structure and size of transaction `details`
- Enforce known schemas per transaction type where available
- Scrub PII-like fields from transaction details
- Provide dynamic registration of new transaction types/schemas

Non-Responsibilities
--------------------
- Writing logs to the database or log storage (infra concern)
- Managing transactions or locks (service/infra concern)
- Business rule enforcement beyond schema/shape validation

Dependencies
------------
- src.core.exceptions.ValidationError
- src.core.logging.logger.get_logger
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, NoReturn
import json

from src.core.exceptions import ValidationError
from src.core.logging.logger import get_logger

logger = get_logger(__name__)


def _raise_validation_error(field_name: str, value: Any, message: str) -> NoReturn:
    """
    Centralized helper to log and raise a ValidationError for transaction data.
    """
    logger.debug(
        "Transaction validation failed",
        extra={
            "field_name": field_name,
            "raw_value": repr(value),
            "reason": message,
        },
    )
    raise ValidationError(field_name, message)


class TransactionValidator:
    """
    Validates transaction log data to ensure integrity and prevent abuse.

    Enforces:
    - Schema validation per transaction type (when known)
    - 10KB size limit per transaction details payload
    - PII scrubbing (email, IP addresses, tokens, etc.)
    - Required field validation for known transaction types

    This class is stateless; all methods are pure helpers.
    """

    # Maximum size for transaction details (10KB)
    MAX_DETAILS_SIZE_BYTES: int = 10 * 1024

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
        # Additional required-field mappings can be registered at runtime.
    }

    # PII patterns to scrub (basic implementation)
    PII_FIELDS: Set[str] = {
        "email",
        "ip_address",
        "password",
        "token",
        "api_key",
        "secret",
    }

    @staticmethod
    def validate_transaction(
        transaction_type: str,
        details: Dict[str, Any],
        allow_unknown_types: bool = True,
    ) -> Dict[str, Any]:
        """
        Validate and sanitize transaction log data.

        Args:
            transaction_type: Type of transaction (e.g., "resource_change_lumees")
            details: Transaction details dictionary (will be scrubbed/sanitized)
            allow_unknown_types: If False, unknown transaction types raise ValidationError

        Returns:
            Sanitized details dictionary

        Raises:
            ValidationError: If validation fails
        """
        # 1. Validate transaction type
        if not transaction_type:
            _raise_validation_error("transaction_type", transaction_type, "Transaction type is required")

        if not isinstance(transaction_type, str):
            _raise_validation_error("transaction_type", transaction_type, "Transaction type must be a string")

        if len(transaction_type) > 100:
            _raise_validation_error(
                "transaction_type",
                transaction_type,
                "Transaction type too long (max 100 characters)",
            )

        # 2. Validate details is a dict
        if not isinstance(details, dict):
            _raise_validation_error("details", details, "Transaction details must be a dictionary")

        # 3. Check size limit (10KB)
        details_json = json.dumps(details, default=str)
        size_bytes = len(details_json.encode("utf-8"))

        if size_bytes > TransactionValidator.MAX_DETAILS_SIZE_BYTES:
            size_kb = size_bytes / 1024
            max_kb = TransactionValidator.MAX_DETAILS_SIZE_BYTES / 1024
            _raise_validation_error(
                "details",
                f"{size_kb:.1f}KB",
                f"Transaction details too large ({size_kb:.1f}KB exceeds {max_kb:.0f}KB limit). "
                "Please reduce the amount of data being logged.",
            )

        # 4. Scrub PII
        sanitized_details = TransactionValidator._scrub_pii(details)

        # 5. Validate schema if transaction type is known
        if transaction_type in TransactionValidator.TRANSACTION_SCHEMAS:
            allowed_fields = TransactionValidator.TRANSACTION_SCHEMAS[transaction_type]
            required_fields = TransactionValidator.REQUIRED_FIELDS.get(transaction_type, set())

            missing_fields = required_fields - sanitized_details.keys()
            if missing_fields:
                _raise_validation_error(
                    "details",
                    sanitized_details,
                    f"Missing required fields for {transaction_type}: {', '.join(sorted(missing_fields))}",
                )

            extra_fields = set(sanitized_details.keys()) - allowed_fields
            if extra_fields:
                # Schema drift is not fatal, but must be observable.
                logger.warning(
                    "Transaction details contain unexpected fields",
                    extra={
                        "transaction_type": transaction_type,
                        "extra_fields": sorted(extra_fields),
                    },
                )

        elif not allow_unknown_types:
            known_types = sorted(TransactionValidator.TRANSACTION_SCHEMAS.keys())
            _raise_validation_error(
                "transaction_type",
                transaction_type,
                f"Unknown transaction type: {transaction_type}. Known types: {', '.join(known_types)}",
            )

        return sanitized_details

    @staticmethod
    def _scrub_pii(details: Dict[str, Any]) -> Dict[str, Any]:
        """
        Remove or redact PII-like fields from transaction details.

        This function is recursive and will scrub:
        - Direct PII fields on the root dict
        - Nested dicts
        - Lists of dicts

        Args:
            details: Transaction details dictionary

        Returns:
            Sanitized dictionary with PII removed/redacted
        """
        sanitized: Dict[str, Any] = {}

        for key, value in details.items():
            lower_key = key.lower()

            if any(pii_field in lower_key for pii_field in TransactionValidator.PII_FIELDS):
                sanitized[key] = "[REDACTED]"
                continue

            if isinstance(value, dict):
                sanitized[key] = TransactionValidator._scrub_pii(value)
            elif isinstance(value, list):
                sanitized_list: List[Any] = []
                for item in value:
                    if isinstance(item, dict):
                        sanitized_list.append(TransactionValidator._scrub_pii(item))
                    else:
                        sanitized_list.append(item)
                sanitized[key] = sanitized_list
            else:
                sanitized[key] = value

        return sanitized

    @staticmethod
    def validate_context(context: Optional[str]) -> str:
        """
        Validate a transaction context string.

        Args:
            context: Context string (command name, event name, etc.)

        Returns:
            Validated context string (defaults to "unknown" if None)

        Raises:
            ValidationError: If context type or length is invalid
        """
        if context is None:
            return "unknown"

        if not isinstance(context, str):
            _raise_validation_error("context", context, "Context must be a string")

        if len(context) > 500:
            _raise_validation_error("context", context, "Context too long (max 500 characters)")

        return context

    @staticmethod
    def add_transaction_type_schema(
        transaction_type: str,
        allowed_fields: Set[str],
        required_fields: Optional[Set[str]] = None,
    ) -> None:
        """
        Register or override a transaction type schema at runtime.

        Useful for plugins or dynamically-added transaction types.

        Args:
            transaction_type: Name of the transaction type
            allowed_fields: Set of allowed field names
            required_fields: Optional set of required field names
        """
        TransactionValidator.TRANSACTION_SCHEMAS[transaction_type] = set(allowed_fields)

        if required_fields:
            TransactionValidator.REQUIRED_FIELDS[transaction_type] = set(required_fields)

        logger.info(
            "Registered transaction schema",
            extra={
                "transaction_type": transaction_type,
                "allowed_fields": sorted(allowed_fields),
                "required_fields": sorted(required_fields) if required_fields else [],
            },
        )

    @staticmethod
    def get_supported_transaction_types() -> List[str]:
        """
        Get a sorted list of all supported transaction types.
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
        """
        if transaction_type not in TransactionValidator.TRANSACTION_SCHEMAS:
            return None

        return {
            "allowed_fields": TransactionValidator.TRANSACTION_SCHEMAS[transaction_type],
            "required_fields": TransactionValidator.REQUIRED_FIELDS.get(transaction_type, set()),
        }

