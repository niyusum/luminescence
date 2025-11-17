"""
Combat Formulas - LES 2025 Compliant
=====================================

Purpose
-------
Core damage calculation formulas for all combat systems.
Monster Warlord inspired: ATK vs DEF with element modifiers.

Domain
------
- Single-hit damage resolution
- ATK vs DEF differential calculation
- Element advantage application
- Critical hit handling (future)
- Damage variance (future)

LUMEN 2025 COMPLIANCE
---------------------
✓ Pure business logic - no Discord dependencies
✓ Config-driven - damage formulas configurable
✓ Observable - structured logging for damage events
✓ Type-safe - complete type hints
✓ Stateless - can be called from any context

Design Decisions
----------------
- Defense reduction: DEF * 0.7 applied to ATK differential
- Minimum damage: Always at least 1 damage
- Element multipliers applied after base calculation
- Negative ATK differentials clamped to 1 damage
- Damage variance off by default (deterministic combat)

Dependencies
------------
- ElementResolver: For element advantage multipliers
- ConfigManager: For damage formula tweaks (future)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.core.logging.logger import get_logger

if TYPE_CHECKING:
    from src.modules.combat.shared.elements import ElementResolver

logger = get_logger(__name__)


# ============================================================================
# Data Models
# ============================================================================


@dataclass(frozen=True)
class DamageInput:
    """
    Input parameters for damage calculation.
    """

    attacker_atk: int
    defender_def: int
    attacker_element: str
    defender_element: str


@dataclass(frozen=True)
class DamageResult:
    """
    Result of damage calculation with breakdown.
    """

    raw_damage: int  # ATK - (DEF * 0.7)
    element_multiplier: float  # Element advantage modifier
    final_damage: int  # raw * element, clamped to min 1
    has_advantage: bool  # Did attacker have advantage?
    has_disadvantage: bool  # Did attacker have disadvantage?


# ============================================================================
# CombatFormulas
# ============================================================================


class CombatFormulas:
    """
    Core combat damage calculation formulas.
    
    Implements Monster Warlord style damage resolution:
    1. Base damage = ATK - (DEF * defense_reduction_factor)
    2. Apply element multiplier
    3. Clamp to minimum damage
    
    Public Methods
    --------------
    - calculate_damage(input) -> Resolve single attack
    - calculate_multi_hit(input, hits) -> Multi-hit attack
    
    Configuration Keys (Future)
    ------------------
    - combat.formulas.defense_reduction_factor (default: 0.7)
    - combat.formulas.min_damage (default: 1)
    - combat.formulas.crit_chance (default: 0.0)
    - combat.formulas.crit_multiplier (default: 1.5)
    """

    def __init__(self, element_resolver: ElementResolver) -> None:
        """
        Initialize CombatFormulas with element resolver.
        
        Args:
            element_resolver: Element advantage resolver
        """
        self._elements = element_resolver
        self._logger = logger

        # Formula constants (future: load from config)
        self._defense_reduction = 0.7  # DEF effectiveness
        self._min_damage = 1  # Minimum damage per hit

        self._logger.info(
            "CombatFormulas initialized",
            extra={
                "defense_reduction": self._defense_reduction,
                "min_damage": self._min_damage,
            },
        )

    # ========================================================================
    # PUBLIC API - Single Hit Damage
    # ========================================================================

    def calculate_damage(self, inp: DamageInput) -> DamageResult:
        """
        Calculate damage for a single attack.
        
        Formula:
        1. raw_damage = max(ATK - (DEF * 0.7), 1)
        2. element_mult = get_multiplier(attacker_elem, defender_elem)
        3. final_damage = max(raw_damage * element_mult, 1)
        
        Args:
            inp: DamageInput with attacker/defender stats
        
        Returns:
            DamageResult with full damage breakdown
        
        Example:
            >>> result = combat_formulas.calculate_damage(DamageInput(
            ...     attacker_atk=1000,
            ...     defender_def=500,
            ...     attacker_element="fire",
            ...     defender_element="earth"
            ... ))
            >>> print(result.final_damage)  # ~780 (base 650 * 1.2 elem)
        """
        # Base damage calculation
        reduced_def = int(inp.defender_def * self._defense_reduction)
        raw_damage = max(inp.attacker_atk - reduced_def, self._min_damage)

        # Element multiplier
        element_mult = self._elements.get_multiplier(
            inp.attacker_element, inp.defender_element
        )

        # Apply element advantage
        final_damage = max(int(raw_damage * element_mult), self._min_damage)

        # Determine advantage/disadvantage
        has_advantage = element_mult > 1.0
        has_disadvantage = element_mult < 1.0

        result = DamageResult(
            raw_damage=raw_damage,
            element_multiplier=element_mult,
            final_damage=final_damage,
            has_advantage=has_advantage,
            has_disadvantage=has_disadvantage,
        )

        self._logger.debug(
            "Damage calculated",
            extra={
                "attacker_atk": inp.attacker_atk,
                "defender_def": inp.defender_def,
                "raw_damage": raw_damage,
                "element_mult": element_mult,
                "final_damage": final_damage,
                "has_advantage": has_advantage,
            },
        )

        return result

    # ========================================================================
    # PUBLIC API - Multi-Hit Damage
    # ========================================================================

    def calculate_multi_hit(self, inp: DamageInput, hits: int) -> DamageResult:
        """
        Calculate damage for multi-hit attack.
        
        Applies single-hit formula multiple times.
        Useful for abilities that hit N times.
        
        Args:
            inp: DamageInput with attacker/defender stats
            hits: Number of hits
        
        Returns:
            DamageResult with total damage across all hits
        
        Example:
            >>> result = combat_formulas.calculate_multi_hit(input, hits=3)
            >>> # Deals 3x single-hit damage
        """
        if hits <= 0:
            return DamageResult(
                raw_damage=0,
                element_multiplier=1.0,
                final_damage=0,
                has_advantage=False,
                has_disadvantage=False,
            )

        # Calculate single hit
        single_hit = self.calculate_damage(inp)

        # Multiply by hits
        return DamageResult(
            raw_damage=single_hit.raw_damage * hits,
            element_multiplier=single_hit.element_multiplier,
            final_damage=single_hit.final_damage * hits,
            has_advantage=single_hit.has_advantage,
            has_disadvantage=single_hit.has_disadvantage,
        )