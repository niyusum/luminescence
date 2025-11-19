"""
Base domain model classes for Lumen RPG (LES 2025).

Purpose
-------
Provide foundational abstractions for rich domain models that encapsulate
business logic, validation, and state transitions following Domain-Driven Design
and LES 2025 architectural standards.

Responsibilities
----------------
- Define base Entity class with identity and equality semantics
- Define base ValueObject class for immutable value types
- Define base AggregateRoot class for consistency boundaries
- Provide validation framework for business rules
- Track domain events for event-driven architecture

Non-Responsibilities
--------------------
- Persistence (handled by repositories)
- Database schema (handled by SQLAlchemy models)
- Service orchestration (handled by service layer)

LUMEN LAW / LES 2025 Compliance
-------------------------------
- Business logic belongs in domain models (P1.2, P1.3)
- Domain models are separate from database models
- Services orchestrate domain models, not manipulate data directly
- Rich domain models replace anemic data structures

Design Patterns
---------------
- **Entity**: Objects with identity that persist over time
- **Value Object**: Immutable objects defined by their attributes
- **Aggregate Root**: Consistency boundary for domain operations
- **Domain Events**: Communicate state changes to other parts of the system

Usage Example
-------------
>>> # Entity with identity
>>> class Player(Entity):
...     def __init__(self, player_id: int, name: str, level: int):
...         super().__init__(player_id)
...         self.name = name
...         self.level = level
...
...     def level_up(self) -> None:
...         '''Business logic for leveling up.'''
...         self.level += 1
...         self.add_domain_event("player.leveled_up", {
...             "player_id": self.id,
...             "new_level": self.level,
...         })
...
>>> # Value object (immutable)
>>> class Stats(ValueObject):
...     def __init__(self, strength: int, agility: int, intelligence: int):
...         self.strength = strength
...         self.agility = agility
...         self.intelligence = intelligence
...         self._validate()
...
...     def _validate(self) -> None:
...         if self.strength < 0 or self.agility < 0 or self.intelligence < 0:
...             raise ValueError("Stats must be non-negative")
"""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone


# ============================================================================
# DOMAIN EVENTS
# ============================================================================


@dataclass
class DomainEvent:
    """
    Represents a domain event that has occurred.

    Domain events communicate state changes to other parts of the system
    via the event bus without creating coupling between domain models.

    Attributes
    ----------
    event_name : str
        Event name (e.g., "player.leveled_up")
    payload : Dict[str, Any]
        Event payload with relevant data
    occurred_at : datetime
        When the event occurred (UTC)
    """

    event_name: str
    payload: Dict[str, Any]
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ============================================================================
# VALUE OBJECT
# ============================================================================


class ValueObject(ABC):
    """
    Base class for immutable value objects.

    Value objects are defined by their attributes, not by identity.
    Two value objects with the same attributes are considered equal.

    Characteristics
    ---------------
    - Immutable: Cannot be changed after creation
    - No identity: Equality based on attributes, not ID
    - Side-effect free: Methods return new instances
    - Self-validating: Validates invariants in constructor

    LES 2025 Compliance
    -------------------
    - Encapsulates business rules for value types
    - Immutability prevents invalid states
    - Rich domain behavior instead of primitive obsession

    Usage
    -----
    Subclasses should:
    1. Define all attributes in __init__
    2. Implement _validate() to enforce invariants
    3. Make all attributes read-only (no setters)
    4. Implement behavior as methods that return new instances
    """

    def __eq__(self, other: object) -> bool:
        """Value objects are equal if all attributes are equal."""
        if not isinstance(other, self.__class__):
            return False
        return self.__dict__ == other.__dict__

    def __hash__(self) -> int:
        """Value objects can be used as dict keys."""
        return hash(tuple(sorted(self.__dict__.items())))

    def _validate(self) -> None:
        """
        Validate business invariants.

        Subclasses should override this to enforce domain rules.
        Raise ValueError or domain-specific exceptions for violations.
        """
        pass


# ============================================================================
# ENTITY
# ============================================================================


class Entity(ABC):
    """
    Base class for entities with identity.

    Entities are defined by their identity (ID), not their attributes.
    Two entities with the same ID are considered the same entity, even if
    their attributes differ.

    Characteristics
    ---------------
    - Identity: Unique ID that persists over time
    - Mutable: Attributes can change while identity remains
    - Lifecycle: Can be created, modified, and deleted
    - Domain Events: Can emit events to communicate state changes

    LES 2025 Compliance
    -------------------
    - Encapsulates business logic for stateful domain concepts
    - Methods modify state according to business rules
    - Emits domain events for important state transitions
    - Separates domain logic from persistence concerns

    Usage
    -----
    Subclasses should:
    1. Call super().__init__(entity_id) in constructor
    2. Define business methods that modify state
    3. Emit domain events for significant state changes
    4. Validate invariants before/after state changes
    """

    def __init__(self, entity_id: int) -> None:
        """
        Initialize entity with identity.

        Parameters
        ----------
        entity_id : int
            Unique identifier for this entity
        """
        self._id = entity_id
        self._domain_events: List[DomainEvent] = []

    @property
    def id(self) -> int:
        """Get entity ID (immutable)."""
        return self._id

    def __eq__(self, other: object) -> bool:
        """Entities are equal if they have the same ID."""
        if not isinstance(other, Entity):
            return False
        return self.id == other.id

    def __hash__(self) -> int:
        """Entities can be used as dict keys based on ID."""
        return hash(self.id)

    def add_domain_event(self, event_name: str, payload: Dict[str, Any]) -> None:
        """
        Add a domain event to be published.

        Domain events communicate state changes without coupling
        domain models to infrastructure concerns.

        Parameters
        ----------
        event_name : str
            Event name (e.g., "player.leveled_up")
        payload : Dict[str, Any]
            Event payload with relevant data

        Examples
        --------
        >>> self.add_domain_event("player.leveled_up", {
        ...     "player_id": self.id,
        ...     "old_level": old_level,
        ...     "new_level": self.level,
        ... })
        """
        event = DomainEvent(event_name=event_name, payload=payload)
        self._domain_events.append(event)

    def clear_domain_events(self) -> List[DomainEvent]:
        """
        Clear and return all domain events.

        This is typically called by the repository after persisting
        the entity and publishing its events.

        Returns
        -------
        List[DomainEvent]
            All domain events that occurred since last clear
        """
        events = self._domain_events.copy()
        self._domain_events.clear()
        return events

    def get_pending_events(self) -> List[DomainEvent]:
        """
        Get domain events without clearing them.

        Returns
        -------
        List[DomainEvent]
            All pending domain events
        """
        return self._domain_events.copy()


# ============================================================================
# AGGREGATE ROOT
# ============================================================================


class AggregateRoot(Entity):
    """
    Base class for aggregate roots.

    An aggregate is a cluster of domain objects that are treated as a single
    unit for data changes. The aggregate root is the entry point for all
    operations on the aggregate.

    Characteristics
    ---------------
    - Consistency Boundary: Ensures invariants across related entities
    - Transactional: All changes to the aggregate are atomic
    - Reference by ID: External objects reference aggregates by ID only
    - Event Source: Publishes domain events for state changes

    LES 2025 Compliance
    -------------------
    - Enforces consistency boundaries
    - Prevents direct access to internal entities
    - Single source of truth for aggregate invariants
    - Coordinates complex business operations

    Usage
    -----
    Subclasses should:
    1. Expose business methods that maintain aggregate invariants
    2. Protect internal entities (don't expose mutable collections)
    3. Emit domain events for significant state transitions
    4. Validate aggregate-level invariants

    Examples
    --------
    >>> class PlayerAggregate(AggregateRoot):
    ...     def __init__(self, player_id: int, name: str):
    ...         super().__init__(player_id)
    ...         self.name = name
    ...         self._maidens: List[Maiden] = []
    ...
    ...     def add_maiden(self, maiden: Maiden) -> None:
    ...         '''Business logic with invariant checking.'''
    ...         if len(self._maidens) >= MAX_MAIDENS:
    ...             raise ValueError("Cannot exceed maximum maidens")
    ...         self._maidens.append(maiden)
    ...         self.add_domain_event("player.maiden_added", {
    ...             "player_id": self.id,
    ...             "maiden_id": maiden.id,
    ...         })
    """

    pass  # Inherits all behavior from Entity


# ============================================================================
# DOMAIN MODEL VALIDATION
# ============================================================================


class DomainValidationError(Exception):
    """
    Exception raised when domain model validation fails.

    This is the base exception for all business rule violations
    in domain models.
    """

    def __init__(self, message: str, field: Optional[str] = None):
        """
        Initialize validation error.

        Parameters
        ----------
        message : str
            Human-readable error message
        field : Optional[str]
            Field name that failed validation (if applicable)
        """
        super().__init__(message)
        self.field = field


def validate_positive(value: int, field_name: str) -> None:
    """
    Validate that a value is positive.

    Parameters
    ----------
    value : int
        Value to validate
    field_name : str
        Name of the field (for error messages)

    Raises
    ------
    DomainValidationError
        If value is not positive
    """
    if value <= 0:
        raise DomainValidationError(
            f"{field_name} must be positive, got {value}",
            field=field_name,
        )


def validate_non_negative(value: int, field_name: str) -> None:
    """
    Validate that a value is non-negative.

    Parameters
    ----------
    value : int
        Value to validate
    field_name : str
        Name of the field (for error messages)

    Raises
    ------
    DomainValidationError
        If value is negative
    """
    if value < 0:
        raise DomainValidationError(
            f"{field_name} must be non-negative, got {value}",
            field=field_name,
        )


def validate_range(value: int, min_val: int, max_val: int, field_name: str) -> None:
    """
    Validate that a value is within a range.

    Parameters
    ----------
    value : int
        Value to validate
    min_val : int
        Minimum allowed value (inclusive)
    max_val : int
        Maximum allowed value (inclusive)
    field_name : str
        Name of the field (for error messages)

    Raises
    ------
    DomainValidationError
        If value is outside the range
    """
    if not (min_val <= value <= max_val):
        raise DomainValidationError(
            f"{field_name} must be between {min_val} and {max_val}, got {value}",
            field=field_name,
        )


def validate_not_empty(value: str, field_name: str) -> None:
    """
    Validate that a string is not empty.

    Parameters
    ----------
    value : str
        Value to validate
    field_name : str
        Name of the field (for error messages)

    Raises
    ------
    DomainValidationError
        If value is empty or whitespace-only
    """
    if not value or not value.strip():
        raise DomainValidationError(
            f"{field_name} cannot be empty",
            field=field_name,
        )
