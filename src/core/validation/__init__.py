"""
Lumen Validation Package (2025)

Purpose
-------
Expose the core validation primitives used across the Lumen RPG system.

This package provides:
- Input validation utilities (`InputValidator`) for all user-supplied data
- Transaction log validation (`TransactionValidator`) for audit trail safety

Responsibilities
----------------
- Act as the canonical import surface for validation components
- Provide a stable, well-named namespace for other layers (cogs, services, infra)

Non-Responsibilities
--------------------
- Business rule enforcement (handled by services)
- Persistence or transaction management (handled by infra)
- Discord UI behavior (handled by cogs/views)

Design Notes
------------
- Re-exports are explicit via __all__ to keep the public API intentional.
- Package is read-only and stateless; all classes are pure utility/validation.
"""

from src.core.validation.input_validator import InputValidator
from src.core.validation.transaction_validator import TransactionValidator

__all__ = [
    "InputValidator",
    "TransactionValidator",
]
