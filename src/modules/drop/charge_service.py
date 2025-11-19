"""
DropChargeService - Business logic for drop charge system
==========================================================

Handles:
- Drop charge regeneration with time-based calculations
- Charge capacity management (upgrades, tier-based increases)
- Drop execution (spend charge, award auric coin)
- Class-specific bonuses
- Charge state queries

All operations follow LUMEN LAW (2025):
- Pure business logic, no Discord/UI concerns
- Config-driven regeneration rates and capacities
- Transaction safety with pessimistic locking
- Event emission for all state changes
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, Optional

from src.core.database.service import DatabaseService
from src.modules.shared.base_repository import BaseRepository
from src.modules.shared.exceptions import InvalidOperationError, NotFoundError
from src.modules.shared.base_service import BaseService
from src.core.validation.input_validator import InputValidator
from src.database.models.core.player import PlayerCurrencies

if TYPE_CHECKING:
    from logging import Logger
    from src.core.config.manager import ConfigManager
    from src.core.event.bus import EventBus


class DropChargeService(BaseService):
    """
    DropChargeService handles all drop charge mechanics.

    Business Logic:
    - Charges regenerate over time (1 charge per configured interval)
    - Max capacity increases with player progression
    - Using a charge awards auric coin (premium currency)
    - Class bonuses apply to rewards
    - No charge accumulation beyond max capacity
    """

    def __init__(
        self,
        config_manager: ConfigManager,
        event_bus: EventBus,
        logger: Logger,
    ):
        """Initialize DropChargeService."""
        super().__init__(config_manager, event_bus, logger)
        self._currencies_repo = BaseRepository[PlayerCurrencies](PlayerCurrencies, self.log)

    # -------------------------------------------------------------------------
    # Core Operations
    # -------------------------------------------------------------------------

    async def execute_drop(
        self,
        player_id: int,
        player_class: Optional[str] = None,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Execute a drop command, consuming one charge and awarding auric coin.

        Args:
            player_id: Discord ID of player
            player_class: Player's class for bonuses (optional)
            context: Operation context for audit

        Returns:
            Dict with drop results (auric_earned, charges_remaining, next_charge_at)

        Raises:
            ResourceNotFoundError: Player currencies not found
            BusinessRuleViolation: No charges available
        """
        # Validation
        player_id = InputValidator.validate_discord_id(player_id)

        # SAFETY: Observability - Wrap in try-except for error path logging
        try:
            async with DatabaseService.get_transaction() as session:
                # Get player currencies with pessimistic lock
                currencies = await self._currencies_repo.find_one_where(
                    session,
                    PlayerCurrencies.player_id == player_id,
                    for_update=True,
                )

                if not currencies:
                    raise NotFoundError("PlayerCurrencies", player_id)

                # Calculate current charges (regeneration)
                current_charges = self._calculate_current_charges(currencies)

                # SAFETY: idempotency - Prevent duplicate drops from network retries/button mashing
                # Check minimum time between drops (configurable cooldown window)
                min_seconds_between_drops = self.get_config("drop_system.min_seconds_between_drops", default=1.0)  # SAFETY: config
                if currencies.last_drop_charge_update:
                    time_since_last_drop = (datetime.now(timezone.utc) - currencies.last_drop_charge_update).total_seconds()
                    if time_since_last_drop < min_seconds_between_drops:
                        raise InvalidOperationError(
                            "execute_drop",
                            f"Drop executed too recently. Please wait {min_seconds_between_drops - time_since_last_drop:.1f} more seconds."
                        )

                # Check if player has charges
                if current_charges <= 0:
                    next_charge_at = self._calculate_next_charge_time(currencies)
                    raise InvalidOperationError(
                        "execute_drop",
                        f"No drop charges available. Next charge at: {next_charge_at}"
                    )

                # Calculate auric coin reward
                base_reward = self.get_config("drop_system.auric_coin_per_drop", default=1)
                class_bonus = self._get_class_bonus(player_class)
                auric_earned = int(base_reward * class_bonus)

                # Update currencies
                currencies.auric_coin += auric_earned
                currencies.drop_charges = current_charges - 1
                currencies.last_drop_charge_update = datetime.now(timezone.utc)

                # Calculate next charge time
                next_charge_at = self._calculate_next_charge_time(currencies)
                max_charges = self._get_max_charges(currencies)

                # Emit event
                await self.emit_event(
                    "drop.executed",
                    {
                        "player_id": player_id,
                        "auric_earned": auric_earned,
                        "charges_consumed": 1,
                        "charges_remaining": currencies.drop_charges,
                        "class_bonus": class_bonus,
                    },
                )

                # SAFETY: observability - Log success with full economic context
                self.log.info(
                    f"Drop executed: player {player_id} earned {auric_earned} auric coin",
                    extra={
                        "player_id": player_id,
                        "amount": auric_earned,
                        "charges_consumed": 1,
                        "charges_remaining": currencies.drop_charges,
                        "class_bonus": class_bonus,
                        "success": True,
                        "error": None,  # SAFETY: Explicit null error
                        "reason": "drop_execution",
                    },
                )

                return {
                    "auric_earned": auric_earned,
                    "charges_remaining": currencies.drop_charges,
                    "max_charges": max_charges,
                    "next_charge_at": next_charge_at,
                    "class_bonus": class_bonus,
                }

        except Exception as e:
            # SAFETY: Observability - Exception path logging
            self.log.error(
                f"Failed to execute drop: {e}",
                extra={
                    "player_id": player_id,
                    "reason": "drop_execution",
                    "success": False,  # SAFETY: Explicit failure flag
                    "error": str(e),   # SAFETY: Explicit error message
                },
                exc_info=True,
            )
            raise

    async def get_charge_status(
        self,
        player_id: int,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get current drop charge status for a player.

        Args:
            player_id: Discord ID of player
            context: Operation context

        Returns:
            Dict with charge status (current_charges, max_charges, next_charge_at)

        Raises:
            ResourceNotFoundError: Player currencies not found
        """
        # Validation
        player_id = InputValidator.validate_discord_id(player_id)

        async with DatabaseService.get_transaction() as session:
            currencies = await self._currencies_repo.find_one_where(
                session,
                PlayerCurrencies.player_id == player_id,
            )

            if not currencies:
                raise NotFoundError("PlayerCurrencies", player_id)

            # Calculate current charges
            current_charges = self._calculate_current_charges(currencies)
            max_charges = self._get_max_charges(currencies)
            next_charge_at = self._calculate_next_charge_time(currencies)
            is_at_max = current_charges >= max_charges

            return {
                "player_id": player_id,
                "current_charges": current_charges,
                "max_charges": max_charges,
                "next_charge_at": next_charge_at if not is_at_max else None,
                "is_at_max": is_at_max,
                "regen_seconds": self.get_config("drop_charges.regen_seconds", default=3600),
            }

    async def increase_max_charges(
        self,
        player_id: int,
        increase_amount: int = 1,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Increase a player's max drop charge capacity.

        Args:
            player_id: Discord ID of player
            increase_amount: Amount to increase capacity by
            context: Operation context

        Returns:
            Dict with updated capacity info

        Raises:
            ResourceNotFoundError: Player currencies not found
            BusinessRuleViolation: Would exceed hard cap
        """
        # Validation
        player_id = InputValidator.validate_discord_id(player_id)
        increase_amount = InputValidator.validate_positive_integer(
            increase_amount, "increase_amount"
        )

        async with DatabaseService.get_transaction() as session:
            # Get player currencies with pessimistic lock
            currencies = await self._currencies_repo.find_one_where(
                session,
                PlayerCurrencies.player_id == player_id,
                for_update=True,
            )

            if not currencies:
                raise NotFoundError("PlayerCurrencies", player_id)

            # Get hard cap and current max from state or config
            hard_cap = self.get_config("drop_charges.max_capacity", default=10)
            default_max = self.get_config("drop_charges.default_max", default=3)

            # Store max in state JSON field since drop_charge_max column doesn't exist
            if not currencies.state:
                currencies.state = {}
            old_max = currencies.state.get("drop_charge_max", default_max)
            new_max = old_max + increase_amount

            # Check hard cap
            if new_max > hard_cap:
                raise InvalidOperationError(
                    "increase_max_charges",
                    f"Cannot increase capacity to {new_max}. Hard cap is {hard_cap}"
                )

            # Update capacity in state
            currencies.state["drop_charge_max"] = new_max

            # Emit event
            await self.emit_event(
                "drop.capacity_increased",
                {
                    "player_id": player_id,
                    "old_max": old_max,
                    "new_max": new_max,
                    "increase_amount": increase_amount,
                },
            )

            return {
                "player_id": player_id,
                "old_max": old_max,
                "new_max": new_max,
                "hard_cap": hard_cap,
            }

    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------

    def _calculate_current_charges(self, currencies: PlayerCurrencies) -> int:
        """
        Calculate current charges including regeneration.

        Args:
            currencies: PlayerCurrencies instance

        Returns:
            Current charge count (capped at max)
        """
        now = datetime.now(timezone.utc)
        last_update = currencies.last_drop_charge_update or now
        stored_charges = currencies.drop_charges

        # Get regen config
        regen_seconds = self.get_config("drop_charges.regen_seconds", default=3600)
        max_charges = self._get_max_charges(currencies)

        # Calculate time elapsed
        time_elapsed = (now - last_update).total_seconds()

        # Calculate charges regenerated
        charges_regenerated = int(time_elapsed / regen_seconds)

        # Calculate current charges (capped at max)
        current_charges = min(stored_charges + charges_regenerated, max_charges)

        return current_charges

    def _calculate_next_charge_time(self, currencies: PlayerCurrencies) -> datetime:
        """
        Calculate when the next charge will regenerate.

        Args:
            currencies: PlayerCurrencies instance

        Returns:
            DateTime of next charge regeneration
        """
        now = datetime.now(timezone.utc)
        last_update = currencies.last_drop_charge_update or now
        stored_charges = currencies.drop_charges

        # Get regen config
        regen_seconds = self.get_config("drop_charges.regen_seconds", default=3600)
        max_charges = self._get_max_charges(currencies)

        # If at max, no next charge time
        current_charges = self._calculate_current_charges(currencies)
        if current_charges >= max_charges:
            return now  # Already at max

        # Calculate time elapsed since last update
        time_elapsed = (now - last_update).total_seconds()

        # Calculate time until next charge
        time_until_next = regen_seconds - (time_elapsed % regen_seconds)

        return now + timedelta(seconds=time_until_next)

    def _get_max_charges(self, currencies: PlayerCurrencies) -> int:
        """
        Get max charges for a player.

        Args:
            currencies: PlayerCurrencies instance

        Returns:
            Max charge capacity
        """
        # Get from state JSON field since drop_charge_max column doesn't exist
        default_max = self.get_config("drop_charges.default_max", default=3)
        if currencies.state:
            return currencies.state.get("drop_charge_max", default_max)
        return default_max

    def _get_class_bonus(self, player_class: Optional[str]) -> float:
        """
        Get class-specific drop bonus multiplier.

        Args:
            player_class: Player's class name

        Returns:
            Bonus multiplier (1.0 = no bonus)
        """
        if not player_class:
            return 1.0

        class_bonuses = self.get_config("drop_system.class_bonuses", default={})
        return class_bonuses.get(player_class.lower(), 1.0)
