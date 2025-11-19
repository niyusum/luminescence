"""
Domain models package for Lumen RPG.

Purpose
-------
Rich domain models with business logic following LES 2025 standards.
These models encapsulate game rules, validation, and state transitions.

LUMEN LAW / LES 2025 Compliance
-------------------------------
- Domain models contain business logic (P1.2, P1.3)
- Separation from database models (anemic data schemas)
- Single source of truth for game rules
- Services orchestrate domain models, not manipulate data directly

Design Notes
------------
Domain models are separate from database models:
- Database models (src/database/models/): Anemic SQLAlchemy schemas
- Domain models (src/domain/models/): Rich objects with business logic

Services convert between database models and domain models as needed.

Base Classes (P1.1)
-------------------
- Entity: Objects with identity
- ValueObject: Immutable value types
- AggregateRoot: Consistency boundaries
- DomainEvent: State change notifications
"""

# Base domain model classes (P1.1)
from .base import (
    AggregateRoot,
    DomainEvent,
    DomainValidationError,
    Entity,
    ValueObject,
    validate_non_negative,
    validate_not_empty,
    validate_positive,
    validate_range,
)

# Domain models (P1.2)
from .player import Player, PlayerCurrencies, PlayerIdentity, PlayerProgression
from .maiden import Maiden, MaidenBaseStats, MaidenIdentity, MaidenMetadata

__all__ = [
    # Base classes
    "Entity",
    "ValueObject",
    "AggregateRoot",
    "DomainEvent",
    "DomainValidationError",
    # Validators
    "validate_positive",
    "validate_non_negative",
    "validate_range",
    "validate_not_empty",
    # Domain models (P1.2)
    "Player",
    "PlayerIdentity",
    "PlayerProgression",
    "PlayerCurrencies",
    "Maiden",
    "MaidenIdentity",
    "MaidenBaseStats",
    "MaidenMetadata",
]
