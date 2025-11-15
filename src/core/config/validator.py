"""
Configuration validation and schema management for Lumen (2025).

Purpose
-------
Provides recursive schema-based validation for nested configuration structures.
Ensures type safety and structural integrity of configuration values before
persisting to database or updating cache.

Responsibilities
----------------
- Define ConfigSchema class for recursive validation
- Maintain schema registry for known configuration keys
- Perform type checking and structural validation
- Reject invalid configuration writes with detailed error messages
- Support type coercion for compatible types (int→float)

Non-Responsibilities
--------------------
- Configuration storage or persistence (handled by ConfigManager)
- Configuration caching or retrieval (handled by ConfigManager)
- Transaction management (handled by DatabaseService)
- Metrics tracking (handled by ConfigMetrics)

LES 2025 Compliance
-------------------
- **Separation of Concerns**: Pure validation logic; no database or caching
- **Type Safety**: Strong typing with Union types and isinstance checks
- **Observability**: Clear error messages with dot-notation paths
- **Extensibility**: Schema registry allows adding new schemas dynamically
- **Domain Exceptions**: Uses ConfigValidationError for validation failures

Architecture Notes
------------------
- Recursive validation using nested ConfigSchema instances
- Type coercion for int→float compatibility (common in configs)
- Unknown keys allowed by default (sparse configs supported)
- Schemas are conservative: only well-understood fields specified
- Dot-notation paths in errors for precise error location

Key Validation Rules
--------------------
1. All config values must be Mapping types (dict-like)
2. Known fields are validated against specified types or nested schemas
3. Type coercion: int values accepted where float expected
4. Missing fields are allowed (sparse configuration support)
5. Unknown fields allowed by default (set allow_extra=False to forbid)
6. Nested schemas validated recursively with path tracking

Dependencies
------------
- ConfigValidationError from errors module
- Standard library: dataclasses, typing, Mapping

Performance Characteristics
---------------------------
- Validation complexity: O(n) where n = total fields in config tree
- Memory overhead: O(d) where d = depth of nesting
- No caching or memoization (validation on every write)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Union

from src.core.config.errors import ConfigValidationError


# Type alias for schema field definitions
SchemaField = Union[type, "ConfigSchema"]


@dataclass(slots=True)
class ConfigSchema:
    """
    Recursive schema for nested configuration validation.
    
    Defines the expected shape of a configuration subtree including
    type requirements and nested structures. Supports recursive
    validation with detailed error reporting.
    
    Attributes
    ----------
    fields:
        Mapping of field names to expected types or nested schemas.
    allow_extra:
        Whether to allow fields not defined in the schema.
    
    Examples
    --------
    >>> # Simple schema with primitive types
    >>> schema = ConfigSchema(fields={"count": int, "rate": float})
    >>> schema.validate({"count": 10, "rate": 0.5})
    {'count': 10, 'rate': 0.5}
    
    >>> # Nested schema
    >>> schema = ConfigSchema(
    ...     fields={
    ...         "costs": ConfigSchema(
    ...             fields={"base": int, "multiplier": float}
    ...         )
    ...     }
    ... )
    >>> schema.validate({"costs": {"base": 100, "multiplier": 1.5}})
    {'costs': {'base': 100, 'multiplier': 1.5}}
    
    >>> # Type mismatch error
    >>> try:
    ...     schema.validate({"count": "not_an_int"})
    ... except ConfigValidationError as e:
    ...     print(e)
    Config value at 'count' must be int; got str
    """

    fields: Mapping[str, SchemaField]
    allow_extra: bool = True

    def validate(self, value: Any, path: str = "") -> Any:
        """
        Validate value against this schema with detailed error reporting.
        
        Recursively validates nested structures and provides precise error
        locations using dot-notation paths.
        
        Parameters
        ----------
        value:
            The value to validate (typically a dict/mapping).
        path:
            Dot-notation path for error messages (e.g., "fusion_costs.curve.a").
        
        Returns
        -------
        Any
            The original value if validation succeeds.
        
        Raises
        ------
        ConfigValidationError
            If validation fails with detailed error message including path.
        
        Examples
        --------
        >>> schema = ConfigSchema(fields={"count": int})
        >>> schema.validate({"count": 10})
        {'count': 10}
        
        >>> schema.validate({"count": "invalid"})
        Traceback (most recent call last):
            ...
        ConfigValidationError: Config value at 'count' must be int; got str
        
        >>> schema.validate("not_a_dict")
        Traceback (most recent call last):
            ...
        ConfigValidationError: Config value at '<root>' must be a mapping; got str
        """
        # Verify value is a mapping type
        if not isinstance(value, Mapping):
            raise ConfigValidationError(
                f"Config value at '{path or '<root>'}' must be a mapping; "
                f"got {type(value).__name__}"
            )

        # Validate known fields against schema
        for key, expected in self.fields.items():
            full_path = f"{path}.{key}" if path else key
            
            # Missing fields are allowed (sparse configs)
            if key not in value:
                continue

            raw = value[key]

            # Recursive validation for nested schemas
            if isinstance(expected, ConfigSchema):
                expected.validate(raw, path=full_path)
            else:
                # Type validation with int→float coercion
                if expected is float and isinstance(raw, int):
                    # Allow int where float is expected (common in configs)
                    continue
                
                if not isinstance(raw, expected):
                    raise ConfigValidationError(
                        f"Config value at '{full_path}' must be {expected.__name__}; "
                        f"got {type(raw).__name__}"
                    )

        # Optionally reject unknown fields
        if not self.allow_extra:
            unknown_keys = set(value.keys()) - set(self.fields.keys())
            if unknown_keys:
                unknown_list = ', '.join(sorted(str(k) for k in unknown_keys))
                raise ConfigValidationError(
                    f"Unexpected config keys at '{path or '<root>'}': {unknown_list}"
                )

        return value


# ============================================================================
# Schema Registry
# ============================================================================

# Structured schema definitions per top-level configuration key.
#
# DESIGN NOTE: This is intentionally conservative - only well-understood
# fields are specified. Unknown keys still pass validation when allow_extra=True,
# which is the default. This allows for forward compatibility and gradual
# schema evolution without breaking existing configs.

_SCHEMAS: Dict[str, ConfigSchema] = {
    # Fusion system configuration
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
    
    # Event modifier configuration
    "event_modifiers": ConfigSchema(
        fields={
            "fusion_rate_boost": float,
            "drop_rate_boost": float,
        },
        allow_extra=True,
    ),
    
    # Exploration system configuration
    "exploration": ConfigSchema(
        fields={
            "energy_costs": ConfigSchema(
                fields={
                    # Zone keys are typically integers
                    "zone1": int,
                    "zone2": int,
                    "zone3": int,
                },
                allow_extra=True,  # Allow additional zones
            ),
            "rewards": ConfigSchema(
                fields={
                    "base_lumees": int,
                    "multiplier": float,
                },
                allow_extra=True,
            ),
        },
        allow_extra=True,
    ),
    
    # Core system configuration
    "core": ConfigSchema(
        fields={
            "config_cache_ttl_seconds": int,
            "max_refresh_failures": int,
        },
        allow_extra=True,
    ),
    
    # Cache system configuration
    "cache": ConfigSchema(
        fields={
            "ttl": ConfigSchema(
                fields={
                    "player_resources": int,
                    "active_modifiers": int,
                    "maiden_collection": int,
                },
                allow_extra=True,  # Allow additional cache types
            ),
            "health": ConfigSchema(
                fields={
                    "max_errors": int,
                    "min_hit_rate": float,
                },
                allow_extra=True,
            ),
        },
        allow_extra=True,
    ),
}


def get_schema_for_top_key(top_key: str) -> Optional[ConfigSchema]:
    """
    Return the validation schema for a given top-level configuration key.
    
    Parameters
    ----------
    top_key:
        The top-level configuration key (e.g., "fusion_costs", "core").
    
    Returns
    -------
    Optional[ConfigSchema]
        The schema if defined, otherwise None (no validation performed).
    
    Examples
    --------
    >>> schema = get_schema_for_top_key("fusion_costs")
    >>> schema.validate({"base": 100, "curve": {"a": 1.5, "b": 2.0}})
    {'base': 100, 'curve': {'a': 1.5, 'b': 2.0}}
    
    >>> schema = get_schema_for_top_key("unknown_key")
    >>> schema is None
    True
    """
    return _SCHEMAS.get(top_key)


def register_schema(top_key: str, schema: ConfigSchema) -> None:
    """
    Register a new schema for a top-level configuration key.
    
    Allows dynamic schema registration for plugin systems or
    runtime schema extensions.
    
    Parameters
    ----------
    top_key:
        The top-level configuration key to register.
    schema:
        The ConfigSchema instance to use for validation.
    
    Example
    -------
    >>> schema = ConfigSchema(fields={"enabled": bool, "rate": float})
    >>> register_schema("my_plugin", schema)
    >>> get_schema_for_top_key("my_plugin") is schema
    True
    """
    _SCHEMAS[top_key] = schema


def unregister_schema(top_key: str) -> Optional[ConfigSchema]:
    """
    Unregister a schema for a top-level configuration key.
    
    Returns the schema that was removed, if any.
    
    Parameters
    ----------
    top_key:
        The top-level configuration key to unregister.
    
    Returns
    -------
    Optional[ConfigSchema]
        The schema that was removed, or None if not found.
    
    Example
    -------
    >>> schema = ConfigSchema(fields={"test": int})
    >>> register_schema("test_key", schema)
    >>> removed = unregister_schema("test_key")
    >>> removed is schema
    True
    """
    return _SCHEMAS.pop(top_key, None)


def validate_config_value(top_key: str, value: Any) -> Any:
    """
    Validate a top-level configuration value against its schema.
    
    This is the main entry point for configuration validation.
    If no schema is registered for the key, the value passes
    validation unchanged (permissive by default).
    
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
    ConfigValidationError:
        If validation fails with detailed error message.
    
    Examples
    --------
    >>> # Successful validation
    >>> validate_config_value("fusion_costs", {"base": 100})
    {'base': 100}
    
    >>> # Validation error
    >>> try:
    ...     validate_config_value("fusion_costs", {"base": "invalid"})
    ... except ConfigValidationError as e:
    ...     print(e)
    Config value at 'fusion_costs.base' must be int; got str
    
    >>> # No schema registered - value passes through
    >>> validate_config_value("unknown_key", {"any": "value"})
    {'any': 'value'}
    """
    schema = get_schema_for_top_key(top_key)
    
    # No schema registered - permissive validation
    if schema is None:
        return value

    # Validate against registered schema
    return schema.validate(value, path=top_key)


# Export all public interfaces
__all__ = [
    "ConfigSchema",
    "SchemaField",
    "get_schema_for_top_key",
    "register_schema",
    "unregister_schema",
    "validate_config_value",
]