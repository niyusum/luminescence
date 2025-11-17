"""
HP Scaling Module - LES 2025 Compliant
=======================================

Purpose
-------
Converts unit-based damage (maiden vs maiden) to player HP damage.
Critical for Ascension and PvP where player has consolidated HP pool.

Domain
------
- Unit damage → Player HP translation
- Defense effectiveness application
- Minimum damage enforcement
- Configurable scaling factors per combat type

LUMEN 2025 COMPLIANCE
---------------------
✓ Pure calculation - no side effects
✓ Config-driven - all scaling from config
✓ Type-safe - complete type hints
✓ Stateless - can be called from any context
✓ Deterministic - same inputs = same outputs

Design Decisions
----------------
Formula: player_damage = raw_unit_damage * hp_scale_factor
- Smaller scale factor = player takes less damage per unit hit
- Larger scale factor = player more fragile
- Different scale factors for Ascension vs PvP vs PvE
- Minimum damage always enforced (can't deal 0 damage)

Dependencies
------------
- ConfigManager: For scaling factors
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.core.logging.logger import get_logger

if TYPE_CHECKING:
    from src.core.config.manager import ConfigManager

logger = get_logger(__name__)


# ============================================================================
# HPScalingCalculator
# ============================================================================


class HPScalingCalculator:
    """
    Converts unit combat damage to player HP damage.
    
    Monster Warlord style: Unit battles happen, but player has one HP pool.
    This translator applies configurable scaling to make combat feel right.
    
    Public Methods
    --------------
    - convert_unit_damage_to_player_hp(raw_unit_damage, combat_type) -> int
    - get_scale_factor(combat_type) -> float
    """

    def __init__(self, config_manager: ConfigManager) -> None:
        """
        Initialize HP scaling calculator.
        
        Args:
            config_manager: Application configuration manager
        """
        self._config = config_manager
        self._logger = logger

        # Load default scale factors
        self._ascension_scale = float(
            self._config.get("combat.ascension.hp_scale_factor", default=0.005)
        )
        self._pvp_scale = float(
            self._config.get("combat.pvp.hp_scale_factor", default=0.003)
        )
        self._pve_scale = float(
            self._config.get("combat.pve.hp_scale_factor", default=0.005)
        )

        # Minimum damage constraints
        self._min_damage_ascension = int(
            self._config.get("combat.ascension.min_player_damage", default=1)
        )
        self._min_damage_pvp = int(
            self._config.get("combat.pvp.min_damage", default=1)
        )
        self._min_damage_pve = int(
            self._config.get("combat.pve.min_damage", default=1)
        )

        self._logger.info(
            "HPScalingCalculator initialized",
            extra={
                "ascension_scale": self._ascension_scale,
                "pvp_scale": self._pvp_scale,
                "pve_scale": self._pve_scale,
            },
        )

    # ========================================================================
    # PUBLIC API
    # ========================================================================

    def convert_unit_damage_to_player_hp(
        self, raw_unit_damage: int, combat_type: str = "ascension"
    ) -> int:
        """
        Convert raw unit damage to player HP damage.
        
        Formula:
            player_damage = max(int(raw_unit_damage * scale_factor), min_damage)
        
        Args:
            raw_unit_damage: Damage from unit combat calculation (ATK - DEF)
            combat_type: "ascension", "pvp", or "pve"
        
        Returns:
            Player HP damage (scaled and clamped)
        
        Example:
            >>> calc = HPScalingCalculator(config)
            >>> # Monster deals 1000 unit damage
            >>> player_damage = calc.convert_unit_damage_to_player_hp(1000, "ascension")
            >>> print(player_damage)  # 5 (1000 * 0.005)
        """
        # Get appropriate scale factor
        scale_factor = self.get_scale_factor(combat_type)
        min_damage = self._get_min_damage(combat_type)

        # Apply scaling
        scaled_damage = int(raw_unit_damage * scale_factor)
        final_damage = max(scaled_damage, min_damage)

        self._logger.debug(
            "HP scaling applied",
            extra={
                "raw_unit_damage": raw_unit_damage,
                "combat_type": combat_type,
                "scale_factor": scale_factor,
                "scaled_damage": scaled_damage,
                "final_damage": final_damage,
            },
        )

        return final_damage

    def get_scale_factor(self, combat_type: str = "ascension") -> float:
        """
        Get HP scale factor for combat type.
        
        Args:
            combat_type: "ascension", "pvp", or "pve"
        
        Returns:
            Scale factor (float)
        """
        combat_type = combat_type.lower()

        if combat_type == "ascension":
            return self._ascension_scale
        elif combat_type == "pvp":
            return self._pvp_scale
        elif combat_type in ("pve", "exploration", "world_boss", "raid"):
            return self._pve_scale
        else:
            self._logger.warning(
                "Unknown combat type, using ascension scale",
                extra={"combat_type": combat_type},
            )
            return self._ascension_scale

    # ========================================================================
    # INTERNAL HELPERS
    # ========================================================================

    def _get_min_damage(self, combat_type: str) -> int:
        """Get minimum damage for combat type."""
        combat_type = combat_type.lower()

        if combat_type == "ascension":
            return self._min_damage_ascension
        elif combat_type == "pvp":
            return self._min_damage_pvp
        else:
            return self._min_damage_pve