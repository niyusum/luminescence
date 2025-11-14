"""
DROP system business logic.

Manages drop charge consumption, auric coin generation with modifiers,
and class-based bonuses. Integrates with ResourceService for auric coin granting.

LUMEN LAW Compliance:
- Article III: Pure business logic service
- Article I.6: Session-first parameter pattern
- Article IV: ConfigManager for all tunables
- Article II: Transaction logging via ResourceService
- Article VII: Domain exceptions only, no Discord imports
- Article I: Stateless @staticmethod pattern
"""

from typing import Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models.core.player import Player
from src.modules.resource.service import ResourceService
from src.core.config import ConfigManager
from src.core.exceptions import InsufficientResourcesError, ValidationError
from src.core.logging.logger import get_logger

logger = get_logger(__name__)


class DropService:
    """
    DROP system for auric coin generation.

    Players spend drop charges to gain auric coin. AuricCoin amounts are affected by:
    - Base auric coin per drop (ConfigManager)
    - Leader income_boost modifier (via ResourceService)
    - Class bonuses (deprecated, now handled by ResourceService modifiers)
    """

    @staticmethod
    async def perform_drop(
        session: AsyncSession,
        player: Player,
        charges: int = 1
    ) -> Dict[str, Any]:
        """
        Perform drop to gain auric coin, consuming exactly 1 drop charge.

        Uses ResourceService for auric coin granting, which applies:
        - Leader income_boost modifiers
        - AuricCoin cap enforcement
        - Transaction logging

        Args:
            session: Database session (transaction managed by caller)
            player: Player object (must be locked with SELECT FOR UPDATE)
            charges: Must be exactly 1 (no multi-drop allowed)

        Returns:
            {
                "auric_coin_gained": 1,
                "total_auric_coin": 100,
                "modifiers_applied": {"income_boost": 1.2, "xp_boost": 1.0},
                "next_available": "4m 32s",
                "has_charge": False
            }

        Raises:
            InsufficientResourcesError: Player lacks drop charges
            ValidationError: Invalid charge amount (must be exactly 1)
        """
        # Validation
        if charges != 1:
            raise ValidationError("charges", "Can only spend exactly 1 drop charge (no multi-drop)")

        if player.DROP_CHARGES < charges:
            raise InsufficientResourcesError(
                resource="DROP_CHARGES",
                required=charges,
                current=player.DROP_CHARGES
            )

        # Store old values for result
        old_charges = player.DROP_CHARGES
        old_auric_coin = player.auric_coin

        # Consume drop charge (set to 0)
        player.DROP_CHARGES = 0

        # Start regen timer
        from datetime import datetime
        player.last_drop_regen = datetime.utcnow()

        # Calculate auric coin reward
        base_auric_coin_per_drop = ConfigManager.get("drop_system.auric_coin_per_drop", 1)
        total_base_auric_coin = base_auric_coin_per_drop * charges

        # Grant auric coin through ResourceService (applies modifiers)
        grant_result = await ResourceService.grant_resources(
            session=session,
            player=player,
            resources={"auric_coin": total_base_auric_coin},
            source="drop_performed",
            apply_modifiers=True,
            context={
                "charges_spent": charges,
                "old_charges": old_charges,
                "new_charges": player.DROP_CHARGES,
                "base_auric_coin_per_drop": base_auric_coin_per_drop
            }
        )

        # Update stats
        player.stats["drops_performed"] = player.stats.get("drops_performed", 0) + charges

        # Calculate actual auric coin gained
        auric_coin_gained = grant_result["granted"].get("auric_coin", 0)

        logger.info(
            f"Player {player.discord_id} charged: "
            f"auric_coin_gained={auric_coin_gained}, has_charge={player.DROP_CHARGES >= 1}",
            extra={
                "player_id": player.discord_id,
                "auric_coin_gained": auric_coin_gained,
                "has_charge": player.DROP_CHARGES >= 1,
                "modifiers": grant_result["modifiers_applied"]
            }
        )

        return {
            "auric_coin_gained": auric_coin_gained,
            "total_auric_coin": player.auric_coin,
            "has_charge": player.DROP_CHARGES >= 1,
            "modifiers_applied": grant_result["modifiers_applied"],
            "next_available": player.get_drop_regen_display(),
            "base_auric_coin": total_base_auric_coin,
            "caps_hit": grant_result.get("caps_hit", [])
        }

    @staticmethod
    def get_drop_info(player: Player) -> Dict[str, Any]:
        """
        Get current drop system state for player.

        Args:
            player: Player object

        Returns:
            {
                "has_charge": True,
                "next_regen": "Ready!",
                "auric_coin_per_drop": 1,
                "total_drops": 142,
                "regen_interval_seconds": 300
            }
        """
        base_auric_coin = ConfigManager.get("drop_system.auric_coin_per_drop", 1)
        regen_interval = ConfigManager.get("drop_system.regen_interval_seconds", 300)

        # Calculate modifiers for preview
        modifiers = ResourceService.calculate_modifiers(player, ["auric_coin"])
        income_boost = modifiers.get("income_boost", 1.0)

        expected_auric_coin = int(base_auric_coin * income_boost)

        return {
            "has_charge": player.DROP_CHARGES >= 1,
            "next_regen": player.get_drop_regen_display(),
            "regen_interval_seconds": regen_interval,
            "auric_coin_per_drop": expected_auric_coin,
            "base_auric_coin": base_auric_coin,
            "income_boost": income_boost,
            "total_drops": player.stats.get("drops_performed", 0)
        }

    @staticmethod
    def calculate_auric_coin_preview(player: Player, charges: int) -> Dict[str, Any]:
        """
        Preview auric coin gain from drop without executing.

        Args:
            player: Player object
            charges: Number of charges to preview

        Returns:
            {
                "base_auric_coin": 1,
                "expected_auric_coin": 1,
                "modifiers": {"income_boost": 1.2},
                "can_afford": True,
                "has_charge": True
            }
        """
        if charges != 1:
            return {
                "error": "Invalid charge amount (only 1 allowed)",
                "can_afford": False
            }

        base_auric_coin_per_drop = ConfigManager.get("drop_system.auric_coin_per_drop", 1)
        total_base_auric_coin = base_auric_coin_per_drop * charges

        # Calculate modifiers
        modifiers = ResourceService.calculate_modifiers(player, ["auric_coin"])
        income_boost = modifiers.get("income_boost", 1.0)

        expected_auric_coin = int(total_base_auric_coin * income_boost)

        return {
            "base_auric_coin": total_base_auric_coin,
            "expected_auric_coin": expected_auric_coin,
            "modifiers": modifiers,
            "can_afford": player.DROP_CHARGES >= 1,
            "has_charge": player.DROP_CHARGES >= 1,
            "auric_coin_cap_warning": expected_auric_coin + player.auric_coin > ConfigManager.get("resource_system.auric_coin_max_cap", 999999)
        }
