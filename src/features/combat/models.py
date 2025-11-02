# src/features/combat/models.py
"""
Combat domain models and data structures.

Immutable data classes for combat calculations, results, and state.
These are pure value objects with no business logic.

Usage:
    >>> damage = DamageResult(base=5000, final=7500, was_critical=True)
    >>> power = PowerStats(total=10000, maiden_count=25, average=400)
"""

from dataclasses import dataclass
from typing import List, Dict, Optional


@dataclass(frozen=True)
class PowerStats:
    """
    Player power statistics from maiden collection.
    
    Attributes:
        total: Total ATK value
        maiden_count: Number of unique maidens
        average: Average power per maiden
        leader_bonus_applied: Whether leader multiplier was included
    """
    total: int
    maiden_count: int
    average: int
    leader_bonus_applied: bool = False


@dataclass(frozen=True)
class MaidenContribution:
    """
    Single maiden's power contribution to player total.
    
    Attributes:
        maiden_id: Database ID
        name: Maiden name
        power: Calculated power value
        tier: Current tier
        element: Element type
        quantity: Number owned
        base_atk: Base ATK stat
        contribution_percent: Percentage of total power
    """
    maiden_id: int
    name: str
    power: int
    tier: int
    element: str
    quantity: int
    base_atk: int
    contribution_percent: float


@dataclass(frozen=True)
class DamageResult:
    """
    Result of damage calculation.
    
    Attributes:
        base: Base damage before modifiers
        final: Final damage after all modifiers
        was_critical: Whether this was a critical hit
        modifiers: Dict of modifier names to values
        attack_count: Number of attacks performed
    """
    base: int
    final: int
    was_critical: bool
    modifiers: Dict[str, float]
    attack_count: int


@dataclass(frozen=True)
class CombatOutcome:
    """
    Complete combat resolution outcome.
    
    Attributes:
        victory: True if attacker won
        damage_dealt: Damage dealt by attacker
        damage_taken: Damage taken by attacker
        attacker_hp_remaining: Attacker's HP after combat
        defender_hp_remaining: Defender's HP after combat
        turns: Number of combat turns
        log_entries: Combat event descriptions
    """
    victory: bool
    damage_dealt: int
    damage_taken: int
    attacker_hp_remaining: int
    defender_hp_remaining: int
    turns: int
    log_entries: List[str]


@dataclass(frozen=True)
class CombatStats:
    """
    Combat statistics for analytics and displays.
    
    Attributes:
        total_battles: Total number of battles
        victories: Number of victories
        defeats: Number of defeats
        total_damage_dealt: Cumulative damage dealt
        total_damage_taken: Cumulative damage taken
        average_damage_per_battle: Average damage per battle
        win_rate: Win rate percentage (0-100)
        critical_hit_rate: Critical hit rate percentage (0-100)
    """
    total_battles: int
    victories: int
    defeats: int
    total_damage_dealt: int
    total_damage_taken: int
    average_damage_per_battle: int
    win_rate: float
    critical_hit_rate: float
    
    @classmethod
    def empty(cls) -> "CombatStats":
        """Create empty combat stats."""
        return cls(
            total_battles=0,
            victories=0,
            defeats=0,
            total_damage_dealt=0,
            total_damage_taken=0,
            average_damage_per_battle=0,
            win_rate=0.0,
            critical_hit_rate=0.0
        )
    
    def calculate_win_rate(self) -> float:
        """Calculate win rate percentage."""
        if self.total_battles == 0:
            return 0.0
        return (self.victories / self.total_battles) * 100
    
    def calculate_average_damage(self) -> int:
        """Calculate average damage per battle."""
        if self.total_battles == 0:
            return 0
        return self.total_damage_dealt // self.total_battles