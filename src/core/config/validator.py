"""
Configuration validation and schema management for Lumen (2025).

Purpose
-------
- Define and enforce recursive schemas for nested configuration structures.
- Validate configuration values against type expectations and structural rules.
- Provide schema-based validation for configuration writes.

Responsibilities
----------------
- Define `ConfigSchema` class for recursive validation of nested configs.
- Maintain schema registry for known configuration keys.
- Perform type checking and structural validation.
- Reject invalid configuration writes with detailed error messages.

Non-Responsibilities
--------------------
- Configuration storage or persistence (handled by ConfigManager).
- Configuration caching or retrieval (handled by ConfigManager).
- Transaction management (handled by DatabaseService).

Lumen 2025 Compliance
---------------------
- **Separation of concerns**: Pure validation logic; no database or caching concerns.
- **Type safety**: Strong typing with Union types and isinstance checks.
- **Observability**: Clear error messages with dot-notation paths for debugging.
- **Extensibility**: Schema registry allows adding new configuration schemas.

Architecture Notes
------------------
- Recursive validation using nested `ConfigSchema` instances.
- Type coercion for int→float compatibility.
- Unknown keys allowed by default (sparse configs supported).
- Schemas are conservative: only well-understood fields are specified.

Dependencies
------------
- ConfigWriteError from manager module (exceptions).
- Standard library only (typing, Mapping).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Union

# Centralized config exception hierarchy (no circular imports)
from src.core.config.errors import ConfigWriteError


# ============================================================================
# Recursive Schema Objects
# ============================================================================


SchemaField = Union[type, "ConfigSchema"]


@dataclass(slots=True)
class ConfigSchema:
    """
    Recursive schema for nested configuration validation.

    Each schema describes the expected shape of a configuration subtree:

    - Keys map to:
        - Python types (`int`, `float`, `str`, etc.), or
        - Nested `ConfigSchema` instances.
    - Unknown keys are allowed by default but can be forbidden via `allow_extra`.
    """

    fields: Mapping[str, SchemaField]
    allow_extra: bool = True

    def validate(self, value: Any, path: str = "") -> Any:
        """
        Validate `value` against this schema.

        Parameters
        ----------
        value:
            The value to validate (typically a dict subtree).
        path:
            Dot-notation path for error messages, e.g. "fusion_costs.curve.a".

        Returns
        -------
        Any
            The original value, if valid.

        Raises
        ------
        ConfigWriteError
            If validation fails.
        """
        if not isinstance(value, Mapping):
            raise ConfigWriteError(
                f"Config value at '{path or '<root>'}' must be a mapping; "
                f"got {type(value).__name__}"
            )

        # Validate known fields.
        for key, expected in self.fields.items():
            full_path = f"{path}.{key}" if path else key
            if key not in value:
                # Missing keys are allowed; configs may be sparse.
                continue

            raw = value[key]

            if isinstance(expected, ConfigSchema):
                expected.validate(raw, path=full_path)
            else:
                # Simple type check; allow ints where float is expected.
                if expected is float and isinstance(raw, int):
                    continue
                if not isinstance(raw, expected):
                    raise ConfigWriteError(
                        f"Config value at '{full_path}' must be {expected.__name__}; "
                        f"got {type(raw).__name__}"
                    )

        # Optionally reject unknown fields.
        if not self.allow_extra:
            unknown_keys = set(value.keys()) - set(self.fields.keys())
            if unknown_keys:
                raise ConfigWriteError(
                    f"Unexpected config keys at '{path or '<root>'}': "
                    f"{', '.join(sorted(str(k) for k in unknown_keys))}"
                )

        return value


# ============================================================================
# Schema Registry
# ============================================================================

# Structured schema definitions per top-level key.
# NOTE: This is intentionally conservative; only well-understood fields are
# specified. Unknown keys still pass validation when `allow_extra=True`.
_SCHEMAS: Dict[str, ConfigSchema] = {
    "fusion_costs": ConfigSchema(
        fields={
            "base": int,
            "curve": ConfigSchema(
                fields={
                    "a": float,
                    "b": float,
                },
                allow_extra=True,
            ),
        },
        allow_extra=True,
    ),
    "event_modifiers": ConfigSchema(
        fields={
            "fusion_rate_boost": float,
        },
        allow_extra=True,
    ),
    "exploration": ConfigSchema(
        fields={
            "energy_costs": ConfigSchema(
                fields={
                    # Zone keys are typically ints but represented as numbers.
                    "zone1": int,
                    "zone2": int,
                },
                allow_extra=True,
            )
        },
        allow_extra=True,
    ),
    "core": ConfigSchema(
        fields={
            "config_cache_ttl_seconds": int,
        },
        allow_extra=True,
    ),
}


def get_schema_for_top_key(top_key: str) -> Optional[ConfigSchema]:
    """
    Return the schema for a given top-level key, if any.

    Parameters
    ----------
    top_key:
        The top-level configuration key (e.g., "fusion_costs", "core").

    Returns
    -------
    Optional[ConfigSchema]
        The schema if defined, otherwise None.
    """
    return _SCHEMAS.get(top_key)


# ============================================================================
# Validation Functions
# ============================================================================


def validate_config_value(top_key: str, value: Any) -> Any:
    """
    Validate a top-level configuration value against its schema (if any).

    Parameters
    ----------
    top_key:
        The top-level configuration key.
    value:
        The value to validate.

    Returns
    -------
    Any
        The validated value (same as input if valid).

    Raises
    ------
    ConfigWriteError
        If validation fails.
    """
    schema = get_schema_for_top_key(top_key)
    if not schema:
        return value

    return schema.validate(value, path=top_key)
