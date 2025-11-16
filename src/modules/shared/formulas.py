"""
Lumen RPG Game Formulas

Purpose
-------
Pure calculation functions for game mechanics. These functions implement
the mathematical rules of the Lumen RPG system: leveling curves, stat
calculations, fusion probabilities, rarity multipliers, and reward formulas.

LUMEN LAW / LES 2025 Compliance
-------------------------------
- Pure functions only (no side effects)
- No infrastructure dependencies
- No database access
- No config access (all parameters passed in)
- Deterministic and testable

Design Notes
------------
All formulas:
- Accept parameters explicitly
- Return calculated values
- Have no external dependencies
- Are fully documented with examples
- Use type hints for clarity

Usage
-----
    from src.modules.shared.formulas import calculate_xp_for_level

    xp_needed = calculate_xp_for_level(50)
    success_rate = calculate_fusion_success_rate(tier=5, base_rate=0.15)
"""

from __future__ import annotations

from typing import List


def calculate_xp_for_level(level: int) -> int:
    """
    Calculate total XP required to reach a given level from level 1.

    Uses a quadratic scaling formula: XP = 100 * level^2

    Args:
        level: Target level

    Returns:
        Total XP required to reach the level

    Example:
        >>> calculate_xp_for_level(10)
        10000
        >>> calculate_xp_for_level(50)
        250000
    """
    return 100 * (level**2)


def calculate_level_from_xp(xp: int) -> int:
    """
    Calculate current level from total XP.

    Inverse of calculate_xp_for_level.

    Args:
        xp: Total XP accumulated

    Returns:
        Current level (minimum 1)

    Example:
        >>> calculate_level_from_xp(10000)
        10
        >>> calculate_level_from_xp(250000)
        50
    """
    if xp <= 0:
        return 1

    import math

    level = int(math.sqrt(xp / 100))
    return max(1, level)


def calculate_stat_value(
    base_value: int, points_allocated: int, value_per_point: int
) -> int:
    """
    Calculate final stat value from base + allocated points.

    Args:
        base_value: Base value before allocation
        points_allocated: Number of points allocated to this stat
        value_per_point: Stat gain per point

    Returns:
        Final stat value

    Example:
        >>> calculate_stat_value(base_value=100, points_allocated=50, value_per_point=10)
        600
    """
    return base_value + (points_allocated * value_per_point)


def calculate_overcap_bonus(
    current_resource: int, max_resource: int, level_gain: int, threshold: float
) -> int:
    """
    Calculate overcap bonus for leveling with full resources.

    If current resource is >= (threshold * max), apply bonus to level gain.

    Args:
        current_resource: Current resource amount
        max_resource: Maximum resource capacity
        level_gain: Base resource gain from leveling
        threshold: Overcap threshold (0.0-1.0, typically 0.9 for 90%)

    Returns:
        Bonus amount (0 if not overcap)

    Example:
        >>> calculate_overcap_bonus(95, 100, 50, 0.9)  # 95/100 >= 90%
        5  # 10% bonus on 50 = 5
        >>> calculate_overcap_bonus(80, 100, 50, 0.9)  # 80/100 < 90%
        0
    """
    if max_resource == 0:
        return 0

    current_ratio = current_resource / max_resource
    if current_ratio >= threshold:
        from .constants import OVERCAP_BONUS

        return int(level_gain * OVERCAP_BONUS)

    return 0


def calculate_rarity_multiplier(tier: int, base_multiplier: float = 1.0) -> float:
    """
    Calculate rarity multiplier based on tier.

    Higher tiers have exponentially higher multipliers.

    Args:
        tier: Maiden tier (1-12)
        base_multiplier: Base multiplier for tier 1

    Returns:
        Rarity multiplier for the tier

    Example:
        >>> calculate_rarity_multiplier(1)
        1.0
        >>> calculate_rarity_multiplier(5)
        2.0
        >>> calculate_rarity_multiplier(10)
        6.0
    """
    # Exponential scaling: multiplier = base * (1 + 0.25 * (tier - 1))
    return base_multiplier * (1.0 + 0.25 * (tier - 1))


def calculate_fusion_success_rate(
    tier: int, base_rate: float, pity_boost: float = 0.0
) -> float:
    """
    Calculate fusion success probability.

    Success rate decreases with tier, but pity boosts can help.

    Args:
        tier: Tier being fused to
        base_rate: Base success rate (0.0-1.0)
        pity_boost: Additional success rate from pity (0.0-1.0)

    Returns:
        Final success rate clamped to [0.0, 1.0]

    Example:
        >>> calculate_fusion_success_rate(tier=3, base_rate=0.15)
        0.13
        >>> calculate_fusion_success_rate(tier=3, base_rate=0.15, pity_boost=0.05)
        0.18
    """
    # Success rate decreases by 1% per tier
    tier_penalty = 0.01 * (tier - 1)
    final_rate = base_rate - tier_penalty + pity_boost
    return max(0.0, min(1.0, final_rate))


def calculate_fusion_cost(tier: int, base_cost: int) -> int:
    """
    Calculate token cost for fusion based on tier.

    Args:
        tier: Tier of maidens being fused
        base_cost: Base fusion cost for tier 1

    Returns:
        Token cost for fusion

    Example:
        >>> calculate_fusion_cost(tier=1, base_cost=100)
        100
        >>> calculate_fusion_cost(tier=5, base_cost=100)
        500
    """
    return base_cost * tier


def calculate_shard_reward(tier: int, min_shards: int, max_shards: int) -> int:
    """
    Calculate shards rewarded from a failed fusion.

    Higher tiers give more shards.

    Args:
        tier: Tier of the failed fusion
        min_shards: Minimum shards possible
        max_shards: Maximum shards possible

    Returns:
        Shard reward (scales with tier)

    Example:
        >>> calculate_shard_reward(tier=1, min_shards=1, max_shards=12)
        1
        >>> calculate_shard_reward(tier=12, min_shards=1, max_shards=12)
        12
    """
    # Linear scaling based on tier
    shard_range = max_shards - min_shards
    tier_fraction = (tier - 1) / 11  # 11 tiers (2-12)
    return min_shards + int(shard_range * tier_fraction)


def calculate_pity_boost(failed_attempts: int, boost_per_attempt: float) -> float:
    """
    Calculate pity boost to success rate based on failed attempts.

    Args:
        failed_attempts: Number of consecutive failures
        boost_per_attempt: Success rate boost per failure (e.g., 0.01 = 1%)

    Returns:
        Total pity boost to success rate

    Example:
        >>> calculate_pity_boost(failed_attempts=5, boost_per_attempt=0.01)
        0.05  # 5% boost
    """
    return failed_attempts * boost_per_attempt


def calculate_maiden_power(
    tier: int, level: int, base_power: int, tier_scaling: float, level_scaling: float
) -> int:
    """
    Calculate a maiden's power based on tier and level.

    Args:
        tier: Maiden tier (1-12)
        level: Maiden level
        base_power: Base power for tier 1, level 1
        tier_scaling: Power multiplier per tier
        level_scaling: Power gain per level

    Returns:
        Total power value

    Example:
        >>> calculate_maiden_power(
        ...     tier=5, level=10, base_power=100,
        ...     tier_scaling=1.5, level_scaling=10
        ... )
        850  # 100 + (4 * 150) + (9 * 10)
    """
    tier_bonus = (tier - 1) * (base_power * tier_scaling)
    level_bonus = (level - 1) * level_scaling
    return int(base_power + tier_bonus + level_bonus)


def calculate_strategic_power(maiden_powers: List[int], team_size: int) -> int:
    """
    Calculate strategic power from top N maidens.

    Args:
        maiden_powers: List of all maiden power values
        team_size: Number of maidens in strategic team

    Returns:
        Sum of top N maiden powers

    Example:
        >>> calculate_strategic_power([100, 200, 300, 50, 75], team_size=3)
        600  # 300 + 200 + 100
    """
    if not maiden_powers:
        return 0

    sorted_powers = sorted(maiden_powers, reverse=True)
    top_n = sorted_powers[:team_size]
    return sum(top_n)


def calculate_resource_value(
    current: int, maximum: int, regen_amount: int
) -> tuple[int, int]:
    """
    Calculate new resource value after regeneration, capped at maximum.

    Args:
        current: Current resource amount
        maximum: Maximum resource capacity
        regen_amount: Amount to regenerate

    Returns:
        Tuple of (new_value, actual_gain)

    Example:
        >>> calculate_resource_value(current=80, maximum=100, regen_amount=30)
        (100, 20)  # Capped at max, actual gain is 20
        >>> calculate_resource_value(current=50, maximum=100, regen_amount=30)
        (80, 30)  # Under cap, full regen applied
    """
    new_value = min(current + regen_amount, maximum)
    actual_gain = new_value - current
    return new_value, actual_gain


def calculate_reward_amount(
    base_reward: int, tier_multiplier: float, bonus_multiplier: float = 1.0
) -> int:
    """
    Calculate reward amount with tier and bonus multipliers.

    Args:
        base_reward: Base reward amount
        tier_multiplier: Multiplier based on tier
        bonus_multiplier: Additional bonus multiplier (e.g., class bonus, event bonus)

    Returns:
        Final reward amount

    Example:
        >>> calculate_reward_amount(base_reward=100, tier_multiplier=2.0)
        200
        >>> calculate_reward_amount(base_reward=100, tier_multiplier=2.0, bonus_multiplier=1.25)
        250  # 100 * 2.0 * 1.25
    """
    return int(base_reward * tier_multiplier * bonus_multiplier)
