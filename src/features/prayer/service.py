"""
Prayer system business logic.

Manages prayer charge consumption, grace generation with modifiers,
and class-based bonuses. Integrates with ResourceService for grace granting.

RIKI LAW Compliance:
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
from src.features.resource.service import ResourceService
from src.core.config.config_manager import ConfigManager
from src.core.exceptions import InsufficientResourcesError, ValidationError
from src.core.logging.logger import get_logger

logger = get_logger(__name__)


class PrayerService:
    """
    Prayer system for grace generation.

    Players spend prayer charges to gain grace. Grace amounts are affected by:
    - Base grace per prayer (ConfigManager)
    - Leader income_boost modifier (via ResourceService)
    - Class bonuses (deprecated, now handled by ResourceService modifiers)
    """

    @staticmethod
    async def perform_prayer(
        session: AsyncSession,
        player: Player,
        charges: int = 1
    ) -> Dict[str, Any]:
        """
        Perform prayer to gain grace, consuming exactly 1 prayer charge.

        Uses ResourceService for grace granting, which applies:
        - Leader income_boost modifiers
        - Grace cap enforcement
        - Transaction logging

        Args:
            session: Database session (transaction managed by caller)
            player: Player object (must be locked with SELECT FOR UPDATE)
            charges: Must be exactly 1 (no multi-pray allowed)

        Returns:
            {
                "grace_gained": 1,
                "total_grace": 100,
                "modifiers_applied": {"income_boost": 1.2, "xp_boost": 1.0},
                "next_available": "4m 32s"
            }

        Raises:
            InsufficientResourcesError: Player lacks prayer charges
            ValidationError: Invalid charge amount (must be exactly 1)
        """
        # Validation
        if charges != 1:
            raise ValidationError("charges", "Can only spend exactly 1 prayer charge (no multi-pray)")

        if player.prayer_charges < charges:
            raise InsufficientResourcesError(
                resource="prayer_charges",
                required=charges,
                current=player.prayer_charges
            )

        # Store old values for result
        old_charges = player.prayer_charges
        old_grace = player.grace

        # Consume prayer charges
        player.prayer_charges -= charges

        # Start regen timer if transitioning from full
        if old_charges == player.max_prayer_charges and player.last_prayer_regen is None:
            from datetime import datetime
            player.last_prayer_regen = datetime.utcnow()

        # Calculate grace reward
        base_grace_per_prayer = ConfigManager.get("prayer_system.grace_per_prayer", 1)
        total_base_grace = base_grace_per_prayer * charges

        # Grant grace through ResourceService (applies modifiers)
        grant_result = await ResourceService.grant_resources(
            session=session,
            player=player,
            resources={"grace": total_base_grace},
            source="prayer_performed",
            apply_modifiers=True,
            context={
                "charges_spent": charges,
                "old_charges": old_charges,
                "new_charges": player.prayer_charges,
                "base_grace_per_prayer": base_grace_per_prayer
            }
        )

        # Update stats
        player.stats["prayers_performed"] = player.stats.get("prayers_performed", 0) + charges

        # Calculate actual grace gained
        grace_gained = grant_result["granted"].get("grace", 0)

        logger.info(
            f"Player {player.discord_id} prayed {charges}x: "
            f"grace_gained={grace_gained}, charges_remaining={player.prayer_charges}",
            extra={
                "player_id": player.discord_id,
                "charges_spent": charges,
                "grace_gained": grace_gained,
                "modifiers": grant_result["modifiers_applied"]
            }
        )

        return {
            "grace_gained": grace_gained,
            "total_grace": player.grace,
            "remaining_charges": player.prayer_charges,
            "charges_spent": charges,
            "modifiers_applied": grant_result["modifiers_applied"],
            "next_charge_in": player.get_prayer_regen_display(),
            "base_grace": total_base_grace,
            "caps_hit": grant_result.get("caps_hit", [])
        }

    @staticmethod
    def get_prayer_info(player: Player) -> Dict[str, Any]:
        """
        Get current prayer system state for player.

        Args:
            player: Player object

        Returns:
            {
                "charges": 1,
                "max_charges": 1,  # DEPRECATED field, always 1
                "next_regen": "Ready!",
                "grace_per_prayer": 1,
                "total_prayers": 142
            }
        """
        base_grace = ConfigManager.get("prayer_system.grace_per_prayer", 1)
        regen_minutes = ConfigManager.get("prayer_system.regen_minutes", 5)

        # Calculate modifiers for preview
        modifiers = ResourceService.calculate_modifiers(player, ["grace"])
        income_boost = modifiers.get("income_boost", 1.0)

        expected_grace = int(base_grace * income_boost)

        return {
            "charges": player.prayer_charges,
            "max_charges": player.max_prayer_charges,
            "next_regen": player.get_prayer_regen_display(),
            "regen_minutes": regen_minutes,
            "grace_per_prayer": expected_grace,
            "base_grace": base_grace,
            "income_boost": income_boost,
            "total_prayers": player.stats.get("prayers_performed", 0)
        }

    @staticmethod
    def calculate_grace_preview(player: Player, charges: int) -> Dict[str, Any]:
        """
        Preview grace gain from prayer without executing.

        Args:
            player: Player object
            charges: Number of charges to preview

        Returns:
            {
                "charges_to_spend": 1,
                "base_grace": 1,
                "expected_grace": 1,
                "modifiers": {"income_boost": 1.2},
                "can_afford": True
            }
        """
        if charges != 1:
            return {
                "error": "Invalid charge amount (only 1 allowed)",
                "can_afford": False
            }

        base_grace_per_prayer = ConfigManager.get("prayer_system.grace_per_prayer", 1)
        total_base_grace = base_grace_per_prayer * charges

        # Calculate modifiers
        modifiers = ResourceService.calculate_modifiers(player, ["grace"])
        income_boost = modifiers.get("income_boost", 1.0)

        expected_grace = int(total_base_grace * income_boost)

        return {
            "charges_to_spend": charges,
            "base_grace": total_base_grace,
            "expected_grace": expected_grace,
            "modifiers": modifiers,
            "can_afford": player.prayer_charges >= charges,
            "current_charges": player.prayer_charges,
            "grace_cap_warning": expected_grace + player.grace > ConfigManager.get("resource_system.grace_max_cap", 999999)
        }
