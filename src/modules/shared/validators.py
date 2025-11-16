"""
Lumen RPG Domain Validators

Purpose
-------
Domain validation utilities for enforcing business rules and data constraints.
These validators raise structured domain exceptions when validation fails,
providing clear feedback for services and cogs.

LUMEN LAW / LES 2025 Compliance
-------------------------------
- Domain validation only (business rules, game constraints)
- Raises domain exceptions (not generic ValueErrors)
- No infrastructure concerns
- No database access (validators operate on passed data)
- Clear, helpful error messages

Design Notes
------------
Validators:
- Accept data to validate as parameters
- Raise specific domain exceptions on failure
- Return None on success (raise-on-error pattern)
- Are reusable across services
- Have clear, documented behavior

Usage
-----
    from src.modules.shared.validators import validate_resource_cost

    validate_resource_cost("tokens", required=1000, available=500)
    # Raises: InsufficientResourcesError

    validate_level_range(level=150)
    # OK if within range, raises ValidationError if not
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from datetime import datetime


def validate_resource_cost(resource: str, required: int, available: int) -> None:
    """
    Validate that a player has sufficient resources.

    Args:
        resource: Name of the resource (e.g., "tokens", "energy")
        required: Amount required
        available: Amount player currently has

    Raises:
        InsufficientResourcesError: If available < required
    """
    from .exceptions import InsufficientResourcesError

    if available < required:
        raise InsufficientResourcesError(resource, required, available)


def validate_level_range(level: int, min_level: int = 1, max_level: int = 999) -> None:
    """
    Validate that a level is within allowed range.

    Args:
        level: Level to validate
        min_level: Minimum allowed level
        max_level: Maximum allowed level

    Raises:
        ValidationError: If level is out of range
    """
    from .exceptions import ValidationError

    if not (min_level <= level <= max_level):
        raise ValidationError(
            "level", f"Level must be between {min_level} and {max_level}, got {level}"
        )


def validate_tier_range(tier: int, min_tier: int = 1, max_tier: int = 12) -> None:
    """
    Validate that a tier is within allowed range.

    Args:
        tier: Tier to validate
        min_tier: Minimum allowed tier
        max_tier: Maximum allowed tier

    Raises:
        ValidationError: If tier is out of range
    """
    from .exceptions import ValidationError

    if not (min_tier <= tier <= max_tier):
        raise ValidationError(
            "tier", f"Tier must be between {min_tier} and {max_tier}, got {tier}"
        )


def validate_maiden_exists(maiden: Optional[Any], identifier: Any = None) -> None:
    """
    Validate that a maiden exists (is not None).

    Args:
        maiden: Maiden object to check
        identifier: Optional identifier for error message

    Raises:
        MaidenNotFoundError: If maiden is None
    """
    from .exceptions import MaidenNotFoundError

    if maiden is None:
        if isinstance(identifier, int):
            raise MaidenNotFoundError(maiden_id=identifier)
        elif isinstance(identifier, str):
            raise MaidenNotFoundError(maiden_name=identifier)
        else:
            raise MaidenNotFoundError()


def validate_maiden_ownership(
    maiden_player_id: int, requesting_player_id: int, maiden_identifier: Any = None
) -> None:
    """
    Validate that a maiden belongs to the requesting player.

    Args:
        maiden_player_id: ID of the player who owns the maiden
        requesting_player_id: ID of the player making the request
        maiden_identifier: Optional maiden identifier for error message

    Raises:
        InvalidOperationError: If player doesn't own the maiden
    """
    from .exceptions import InvalidOperationError

    if maiden_player_id != requesting_player_id:
        raise InvalidOperationError(
            action="access_maiden",
            reason=f"Maiden {maiden_identifier or 'unknown'} belongs to another player",
        )


def validate_fusion_eligible(
    tier: int, is_locked: bool, maiden_identifier: Any = None
) -> None:
    """
    Validate that a maiden is eligible for fusion.

    Args:
        tier: Maiden's current tier
        is_locked: Whether maiden is locked
        maiden_identifier: Optional maiden identifier for error messages

    Raises:
        InvalidFusionError: If maiden cannot be fused
    """
    from .constants import MAX_FUSION_TIER
    from .exceptions import InvalidFusionError

    if tier >= MAX_FUSION_TIER:
        raise InvalidFusionError(
            f"Maiden {maiden_identifier or ''} is already at max tier {MAX_FUSION_TIER}"
        )

    if is_locked:
        raise InvalidFusionError(
            f"Maiden {maiden_identifier or ''} is locked and cannot be used in fusion"
        )


def validate_cooldown(
    action: str, last_used: Optional[datetime], cooldown_seconds: int, now: datetime
) -> None:
    """
    Validate that an action is not on cooldown.

    Args:
        action: Name of the action
        last_used: Timestamp of last use (None if never used)
        cooldown_seconds: Cooldown duration in seconds
        now: Current timestamp

    Raises:
        CooldownActiveError: If action is still on cooldown
    """
    from .exceptions import CooldownActiveError

    if last_used is None:
        return

    elapsed = (now - last_used).total_seconds()
    if elapsed < cooldown_seconds:
        remaining = cooldown_seconds - elapsed
        raise CooldownActiveError(action, remaining)
