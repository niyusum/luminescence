"""
Maiden Module - LES 2025 Compliant Services
============================================

This module provides all maiden-related services following the Lumen Engineering
Standard (LES) 2025.

Services
--------
- MaidenService: Player-owned maiden inventory and stack management
- MaidenBaseService: Maiden templates, gacha pools, power calculations
- PowerCalculationService: Maiden stat calculations and tier scaling
- LeaderSkillService: Leader effect calculations for combat

All services are transaction-safe, config-driven, and event-driven.
"""

from .base_service import MaidenBaseService
from .service import MaidenService
from .power_service import PowerCalculationService
from .leader_skill_service import LeaderSkillService

__all__ = [
    "MaidenService",
    "MaidenBaseService",
    "PowerCalculationService",
    "LeaderSkillService",
]
