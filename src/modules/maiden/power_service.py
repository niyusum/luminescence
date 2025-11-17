"""
Power Calculation Service - LES 2025 Compliant
===============================================

Purpose
-------
Single source of truth for maiden and team stat calculations.
Eliminates hardcoded multipliers and inconsistent formulas across codebase.

Domain
------
- Maiden stat calculation (ATK/DEF/Power) using config-driven formulas
- Tier scaling with milestone bonuses
- Quantity multipliers for maiden stacks
- Team aggregate power calculation
- Power breakdown analysis

LUMEN 2025 COMPLIANCE
---------------------
✓ Pure business logic - no Discord dependencies
✓ Config-driven - all formulas from maiden.power.tier_scaling
✓ Domain exceptions - raises NotFoundError, ValidationError
✓ Observable - structured logging for all calculations
✓ Read-only operations - uses get_session() pattern
✓ Type-safe - complete type hints throughout

Design Decisions
----------------
- Formula precedence: Config > Defaults > Fail-safe
- Tier bonuses stack multiplicatively
- Quantity multiplier applied after tier scaling
- Power = ATK + DEF (future: configurable weighting)
- Zero quantity/tier treated as zero contribution (no negative stats)

Dependencies
------------
- ConfigManager: For tier scaling formulas and bonuses
- DatabaseService: For session management
- Maiden, MaidenBase models: For stat queries
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, List, Tuple, TypedDict

from sqlalchemy import select

from src.core.config.manager import ConfigManager
from src.core.database.service import DatabaseService
from src.core.logging.logger import get_logger
from src.core.validation.input_validator import InputValidator
from src.modules.shared.exceptions import NotFoundError, ValidationError

if TYPE_CHECKING:
    from src.database.models.core.maiden import Maiden
    from src.database.models.core.maiden_base import MaidenBase

logger = get_logger(__name__)


# ============================================================================
# Data Models
# ============================================================================


class MaidenContributor(TypedDict):
    """
    Type definition for maiden contributor in power breakdown.

    Represents a single maiden's contribution to total power.
    """
    maiden_id: int
    maiden_base_id: int
    name: str
    tier: int
    quantity: int
    element: str
    attack: int
    defense: int
    power: int
    tier_multiplier: float
    contribution_pct: float


@dataclass(frozen=True)
class MaidenStats:
    """
    Computed stats for a single maiden instance.
    
    All values are post-calculation (tier scaling, quantity, bonuses applied).
    Immutable to prevent accidental modification.
    """

    maiden_id: int
    maiden_base_id: int
    player_id: int
    tier: int
    quantity: int
    element: str
    attack: int
    defense: int
    power: int  # attack + defense
    tier_multiplier: float  # For debugging/display


@dataclass(frozen=True)
class TeamPowerBreakdown:
    """
    Aggregate power analysis for a player's collection.
    """

    player_id: int
    total_attack: int
    total_defense: int
    total_power: int
    maiden_count: int
    unique_maidens: int
    top_contributors: List[MaidenContributor]  # Top N by power


# ============================================================================
# PowerCalculationService
# ============================================================================


class PowerCalculationService:
    """
    Service for maiden and team stat calculations.
    
    Centralizes all power/stat math to eliminate formula inconsistencies.
    All combat systems, displays, and leaderboards must use this service.
    
    Public Methods
    --------------
    - get_maiden_stats(maiden_id) -> Calculate stats for single maiden
    - get_player_total_power(player_id) -> Aggregate team power
    - get_power_breakdown(player_id, top_n) -> Detailed power analysis
    - calculate_raw_stats(base_atk, base_def, tier, quantity) -> Pure math
    
    Configuration Keys
    ------------------
    - maiden.power.tier_scaling.linear_step (default: 0.2)
    - maiden.power.tier_scaling.tier_bonuses (dict of tier: bonus_pct)
    """

    def __init__(self, config_manager: ConfigManager) -> None:
        """
        Initialize PowerCalculationService with config manager.
        
        Args:
            config_manager: Application configuration manager
        """
        self._config = config_manager
        self._logger = logger

        # Load tier scaling config
        tier_config = self._config.get("maiden.power.tier_scaling", default={})

        # Linear step multiplier (tier 1→2→3 progression)
        self._tier_step = float(tier_config.get("linear_step", 0.2))

        # Milestone tier bonuses (5, 10, 12 etc.)
        raw_bonuses = tier_config.get("tier_bonuses", {})
        self._tier_bonuses: Dict[int, float] = {}

        # Parse tier_bonuses from config (handles both int and string keys)
        for tier_key, bonus_data in raw_bonuses.items():
            try:
                tier_num = int(tier_key.replace("tier_", ""))
                # Handle both {"attack_bonus_pct": 0.05} and direct float values
                if isinstance(bonus_data, dict):
                    bonus_pct = float(bonus_data.get("attack_bonus_pct", 0.0))
                else:
                    bonus_pct = float(bonus_data)
                self._tier_bonuses[tier_num] = bonus_pct
            except (ValueError, AttributeError) as e:
                self._logger.warning(
                    "Failed to parse tier bonus",
                    extra={"tier_key": tier_key, "error": str(e)},
                )

        # Defaults if config is empty
        if not self._tier_bonuses:
            self._tier_bonuses = {5: 0.05, 10: 0.15, 12: 0.25}

        self._logger.info(
            "PowerCalculationService initialized",
            extra={
                "tier_step": self._tier_step,
                "tier_bonuses": self._tier_bonuses,
            },
        )

    # ========================================================================
    # PUBLIC API - Single Maiden Stats
    # ========================================================================

    async def get_maiden_stats(self, maiden_id: int) -> MaidenStats:
        """
        Calculate stats for a single maiden instance.
        
        Uses config-driven tier scaling formulas and milestone bonuses.
        This is a **read-only operation** using get_session().
        
        Args:
            maiden_id: Maiden instance ID
        
        Returns:
            MaidenStats with calculated ATK/DEF/Power
        
        Raises:
            NotFoundError: If maiden not found
            ValidationError: If maiden_id invalid
        
        Example:
            >>> stats = await power_service.get_maiden_stats(42)
            >>> print(f"ATK: {stats.attack}, DEF: {stats.defense}")
        """
        maiden_id = InputValidator.validate_positive_integer(maiden_id, "maiden_id")

        self._logger.debug(
            "Calculating maiden stats",
            extra={"maiden_id": maiden_id, "operation": "get_maiden_stats"},
        )

        async with DatabaseService.get_session() as session:
            from src.database.models.core.maiden import Maiden
            from src.database.models.core.maiden_base import MaidenBase

            query = (
                select(Maiden, MaidenBase)
                .join(MaidenBase, Maiden.maiden_base_id == MaidenBase.id)
                .where(Maiden.id == maiden_id)
                .where(Maiden.deleted_at.is_(None))
            )

            result = await session.execute(query)
            row = result.one_or_none()

            if row is None:
                raise NotFoundError("Maiden", maiden_id)

            maiden: Maiden = row[0]
            maiden_base: MaidenBase = row[1]

            atk, defense, tier_mult = self._calculate_maiden_atk_def(
                base_atk=maiden_base.base_atk,
                base_def=maiden_base.base_def,
                tier=maiden.tier,
                quantity=maiden.quantity,
            )

            power = atk + defense

            self._logger.debug(
                "Maiden stats calculated",
                extra={
                    "maiden_id": maiden_id,
                    "tier": maiden.tier,
                    "quantity": maiden.quantity,
                    "attack": atk,
                    "defense": defense,
                    "power": power,
                    "tier_multiplier": tier_mult,
                },
            )

            return MaidenStats(
                maiden_id=maiden.id,
                maiden_base_id=maiden.maiden_base_id,
                player_id=maiden.player_id,
                tier=maiden.tier,
                quantity=maiden.quantity,
                element=maiden.element,
                attack=atk,
                defense=defense,
                power=power,
                tier_multiplier=tier_mult,
            )

    # ========================================================================
    # PUBLIC API - Team Aggregate Power
    # ========================================================================

    async def get_player_total_power(self, player_id: int) -> Tuple[int, int, int]:
        """
        Calculate total_attack, total_defense, total_power for a player.
        
        Aggregates all owned maidens using config-driven formulas.
        This is a **read-only operation** using get_session().
        
        Args:
            player_id: Discord ID
        
        Returns:
            Tuple of (total_attack, total_defense, total_power)
        
        Example:
            >>> atk, defense, power = await power_service.get_player_total_power(123)
            >>> print(f"Total Power: {power}")
        """
        player_id = InputValidator.validate_discord_id(player_id)

        self._logger.debug(
            "Calculating player total power",
            extra={"player_id": player_id, "operation": "get_player_total_power"},
        )

        async with DatabaseService.get_session() as session:
            from src.database.models.core.maiden import Maiden
            from src.database.models.core.maiden_base import MaidenBase

            query = (
                select(Maiden, MaidenBase)
                .join(MaidenBase, Maiden.maiden_base_id == MaidenBase.id)
                .where(Maiden.player_id == player_id)
                .where(Maiden.deleted_at.is_(None))
            )

            result = await session.execute(query)
            rows = result.all()

            total_atk = 0
            total_def = 0

            for maiden, maiden_base in rows:
                atk, defense, _ = self._calculate_maiden_atk_def(
                    base_atk=maiden_base.base_atk,
                    base_def=maiden_base.base_def,
                    tier=maiden.tier,
                    quantity=maiden.quantity,
                )
                total_atk += atk
                total_def += defense

            total_power = total_atk + total_def

            self._logger.info(
                "Player total power calculated",
                extra={
                    "player_id": player_id,
                    "total_attack": total_atk,
                    "total_defense": total_def,
                    "total_power": total_power,
                    "maiden_count": len(rows),
                },
            )

            return total_atk, total_def, total_power

    # ========================================================================
    # PUBLIC API - Detailed Power Breakdown
    # ========================================================================

    async def get_power_breakdown(
        self, player_id: int, top_n: int = 10
    ) -> TeamPowerBreakdown:
        """
        Get detailed power analysis with top contributors.
        
        This is a **read-only operation** using get_session().
        
        Args:
            player_id: Discord ID
            top_n: Number of top maidens to include in breakdown
        
        Returns:
            TeamPowerBreakdown with aggregate stats and top contributors
        
        Example:
            >>> breakdown = await power_service.get_power_breakdown(123, top_n=5)
            >>> for maiden in breakdown.top_contributors:
            ...     print(f"{maiden['name']}: {maiden['power']}")
        """
        player_id = InputValidator.validate_discord_id(player_id)
        top_n = InputValidator.validate_positive_integer(top_n, "top_n")

        async with DatabaseService.get_session() as session:
            from src.database.models.core.maiden import Maiden
            from src.database.models.core.maiden_base import MaidenBase

            query = (
                select(Maiden, MaidenBase)
                .join(MaidenBase, Maiden.maiden_base_id == MaidenBase.id)
                .where(Maiden.player_id == player_id)
                .where(Maiden.deleted_at.is_(None))
            )

            result = await session.execute(query)
            rows = result.all()

            if not rows:
                return TeamPowerBreakdown(
                    player_id=player_id,
                    total_attack=0,
                    total_defense=0,
                    total_power=0,
                    maiden_count=0,
                    unique_maidens=0,
                    top_contributors=[],
                )

            # Calculate stats for each maiden
            maiden_stats_list = []
            total_atk = 0
            total_def = 0

            for maiden, maiden_base in rows:
                atk, defense, tier_mult = self._calculate_maiden_atk_def(
                    base_atk=maiden_base.base_atk,
                    base_def=maiden_base.base_def,
                    tier=maiden.tier,
                    quantity=maiden.quantity,
                )
                power = atk + defense

                total_atk += atk
                total_def += defense

                maiden_stats_list.append(
                    {
                        "maiden_id": maiden.id,
                        "maiden_base_id": maiden.maiden_base_id,
                        "name": maiden_base.name,
                        "tier": maiden.tier,
                        "quantity": maiden.quantity,
                        "element": maiden.element,
                        "attack": atk,
                        "defense": defense,
                        "power": power,
                        "tier_multiplier": tier_mult,
                    }
                )

            total_power = total_atk + total_def

            # Sort by power descending and take top N
            maiden_stats_list.sort(key=lambda x: x["power"], reverse=True)
            top_contributors = maiden_stats_list[:top_n]

            # Add contribution percentage to top contributors
            for contrib in top_contributors:
                contrib["contribution_pct"] = (
                    (contrib["power"] / total_power * 100) if total_power > 0 else 0.0
                )

            total_maiden_count = sum(m["quantity"] for m in maiden_stats_list)

            return TeamPowerBreakdown(
                player_id=player_id,
                total_attack=total_atk,
                total_defense=total_def,
                total_power=total_power,
                maiden_count=total_maiden_count,
                unique_maidens=len(rows),
                top_contributors=top_contributors,
            )

    # ========================================================================
    # PUBLIC API - Pure Calculation (No DB)
    # ========================================================================

    def calculate_raw_stats(
        self, base_atk: int, base_def: int, tier: int, quantity: int = 1
    ) -> Tuple[int, int, int]:
        """
        Pure stat calculation without database queries.
        
        Useful for previews, simulations, or external systems.
        
        Args:
            base_atk: Base attack from MaidenBase
            base_def: Base defense from MaidenBase
            tier: Tier level (1-12)
            quantity: Stack quantity (default 1)
        
        Returns:
            Tuple of (attack, defense, power)
        
        Example:
            >>> atk, def, power = power_service.calculate_raw_stats(
            ...     base_atk=100, base_def=80, tier=5, quantity=3
            ... )
        """
        base_atk = InputValidator.validate_non_negative_integer(base_atk, "base_atk")
        base_def = InputValidator.validate_non_negative_integer(base_def, "base_def")
        tier = InputValidator.validate_integer(tier, "tier", min_value=1, max_value=12)
        quantity = InputValidator.validate_positive_integer(quantity, "quantity")

        atk, defense, _ = self._calculate_maiden_atk_def(
            base_atk=base_atk, base_def=base_def, tier=tier, quantity=quantity
        )

        return atk, defense, atk + defense

    # ========================================================================
    # INTERNAL HELPERS
    # ========================================================================

    def _calculate_maiden_atk_def(
        self, base_atk: int, base_def: int, tier: int, quantity: int
    ) -> Tuple[int, int, float]:
        """
        Apply tier scaling and quantity multiplier to base stats.
        
        Formula:
            1. Base multiplier: 1.0 + (tier - 1) * tier_step
            2. Milestone bonuses: Multiplicative (e.g., tier 5: *1.05)
            3. Quantity multiplier: Applied last
        
        Args:
            base_atk: Base attack stat
            base_def: Base defense stat
            tier: Tier level (1-12)
            quantity: Stack quantity
        
        Returns:
            Tuple of (attack, defense, tier_multiplier)
        """
        # Start with base tier progression
        tier_multiplier = 1.0 + self._tier_step * max(tier - 1, 0)

        # Apply milestone bonuses multiplicatively
        for milestone_tier, bonus_pct in sorted(self._tier_bonuses.items()):
            if tier >= milestone_tier:
                tier_multiplier *= 1.0 + bonus_pct

        # Apply quantity multiplier
        final_multiplier = tier_multiplier * max(quantity, 0)

        atk = int(base_atk * final_multiplier)
        defense = int(base_def * final_multiplier)

        return atk, defense, tier_multiplier