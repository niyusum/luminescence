"""
Combat Module - LES 2025 Compliant
===================================

Lumen RPG combat system with three engines:
- ElementalTeamEngine: Ascension tower combat
- PvPEngine: Player duels
- AggregateEngine: Exploration/world boss/raids

All combat coordinated through CombatService.
"""

from src.modules.combat.aggregate_engine import AggregateEngine
from src.modules.combat.elemental_engine import ElementalTeamEngine
from src.modules.combat.pvp_engine import PvPEngine
from src.modules.combat.service import CombatService

__all__ = [
    "CombatService",
    "ElementalTeamEngine",
    "PvPEngine",
    "AggregateEngine",
]