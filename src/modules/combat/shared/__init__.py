"""
Combat Shared Modules - LES 2025 Compliant
===========================================

Shared combat utilities, data structures, and calculations.
"""

from src.modules.combat.shared.elements import ElementResolver
from src.modules.combat.shared.encounter import (
    CombatLogEntry,
    CombatOutcome,
    Encounter,
    EncounterType,
    EnemyStats,
    MaidenStats,
)
from src.modules.combat.shared.formulas import CombatFormulas, DamageInput, DamageResult
from src.modules.combat.shared.hp_scaling import HPScalingCalculator

__all__ = [
    # Encounter
    "Encounter",
    "EncounterType",
    "CombatOutcome",
    "MaidenStats",
    "EnemyStats",
    "CombatLogEntry",
    # Formulas
    "CombatFormulas",
    "DamageInput",
    "DamageResult",
    # Elements
    "ElementResolver",
    # HP Scaling
    "HPScalingCalculator",
]