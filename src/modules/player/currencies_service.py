"""
Player Currencies Service - LES 2025 Compliant
================================================

Purpose
-------
Manages player economic resources (lumees, lumenite, auric_coin) and fusion shards
with full transaction safety, audit logging, and event emission.

Domain
------
- Primary currencies: lumees (soft), lumenite (premium crafting), auric_coin (premium gacha)
- Fusion shards: tier-based shards for fusion failures
- Transfer operations between players
- Balance queries and sufficiency checks

LUMEN 2025 COMPLIANCE
---------------------
✓ Pure business logic - no Discord dependencies
✓ Transaction-safe - all writes in atomic transactions
✓ Config-driven - no hardcoded game balance values
✓ Domain exceptions - raises InsufficientResourcesError, ValidationError
✓ Event-driven - emits events for resource changes
✓ Observable - structured logging, audit trail, timing metrics
✓ Pessimistic locking - uses SELECT FOR UPDATE for all writes
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional

from src.core.database.service import DatabaseService
from src.core.infra.audit_logger import AuditLogger
from src.core.logging.logger import get_logger
from src.core.validation.input_validator import InputValidator
from src.modules.shared.base_repository import BaseRepository
from src.modules.shared.base_service import BaseService
from src.modules.shared.exceptions import (
    InsufficientResourcesError,
    NotFoundError,
    ValidationError,
)

if TYPE_CHECKING:
    from logging import Logger

    from src.core.config.manager import ConfigManager
    from src.core.event.bus import EventBus
    from src.database.models.core.player.player_currencies import PlayerCurrencies


# ============================================================================
# Repository
# ============================================================================


class PlayerCurrenciesRepository(BaseRepository["PlayerCurrencies"]):
    """Repository for PlayerCurrencies model."""

    pass  # Inherits all CRUD from BaseRepository


# ============================================================================
# PlayerCurrenciesService
# ============================================================================


class PlayerCurrenciesService(BaseService):
    """
    Service for managing player economic resources.

    Handles all currency operations: addition, subtraction, transfers, and
    balance queries with full transaction safety and audit logging.

    Dependencies
    ------------
    - ConfigManager: For resource limits and transfer fees
    - EventBus: For emitting resource change events
    - Logger: For structured logging
    - DatabaseService: For transaction management (injected via context)
    - AuditLogger: For audit trail (static)

    Public Methods
    --------------
    - get_balance() -> Read current resource balances
    - add_resource() -> Add currency to player
    - subtract_resource() -> Remove currency from player
    - transfer_resource() -> Transfer currency between players
    - has_sufficient_resources() -> Check if player can afford cost
    - add_shards() -> Add fusion shards for a specific tier
    - subtract_shards() -> Remove fusion shards for a specific tier
    - get_shards() -> Get shard balance for a specific tier
    """

    def __init__(
        self,
        config_manager: ConfigManager,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        """
        Initialize PlayerCurrenciesService with required dependencies.

        Args:
            config_manager: Application configuration manager
            event_bus: Event bus for cross-module communication
            logger: Structured logger instance
        """
        super().__init__(config_manager, event_bus, logger)

        # Initialize repository with proper logger
        from src.database.models.core.player.player_currencies import (
            PlayerCurrencies,
        )

        self._currencies_repo = PlayerCurrenciesRepository(
            model_class=PlayerCurrencies,
            logger=get_logger(f"{__name__}.PlayerCurrenciesRepository"),
        )

    # ========================================================================
    # PUBLIC API - Read Operations
    # ========================================================================

    async def get_balance(
        self, player_id: int, resource_type: str
    ) -> Dict[str, Any]:
        """
        Get current balance for a specific resource.

        This is a **read-only** operation using get_session().

        Args:
            player_id: Discord ID of the player
            resource_type: Type of resource ("lumees", "lumenite", "auric_coin")

        Returns:
            Dict with balance information:
                {
                    "player_id": int,
                    "resource_type": str,
                    "amount": int
                }

        Raises:
            NotFoundError: If player currencies record not found
            ValidationError: If resource_type is invalid

        Example:
            >>> balance = await currencies_service.get_balance(123, "lumees")
            >>> print(balance["amount"])  # 10000
        """
        # Validation
        player_id = InputValidator.validate_discord_id(player_id)
        resource_type = self._validate_resource_type(resource_type)

        self.log_operation(
            "get_balance",
            player_id=player_id,
            resource_type=resource_type,
        )

        # Read-only operation - use get_session()
        async with DatabaseService.get_session() as session:
            currencies = await self._currencies_repo.find_one_where(
                session,
                self._currencies_repo.model_class.player_id == player_id,
            )

            if not currencies:
                raise NotFoundError("PlayerCurrencies", player_id)

            amount = getattr(currencies, resource_type, 0)

            return {
                "player_id": player_id,
                "resource_type": resource_type,
                "amount": amount,
            }

    async def has_sufficient_resources(
        self, player_id: int, resource_type: str, required_amount: int
    ) -> bool:
        """
        Check if player has enough of a resource.

        Convenience method for affordability checks.

        Args:
            player_id: Discord ID of the player
            resource_type: Type of resource
            required_amount: Amount needed

        Returns:
            True if player has >= required_amount, False otherwise
        """
        try:
            balance = await self.get_balance(player_id, resource_type)
            return balance["amount"] >= required_amount
        except NotFoundError:
            return False

    # ========================================================================
    # PUBLIC API - Write Operations (Primary Currencies)
    # ========================================================================

    async def add_resource(
        self,
        player_id: int,
        resource_type: str,
        amount: int,
        reason: str,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Add currency to a player's balance.

        This is a **write operation** using get_transaction() with pessimistic locking.

        Args:
            player_id: Discord ID of the player
            resource_type: Type of resource ("lumees", "lumenite", "auric_coin")
            amount: Amount to add (must be positive)
            reason: Reason for the addition (for audit trail)
            context: Optional command/system context

        Returns:
            Dict with updated balance:
                {
                    "player_id": int,
                    "resource_type": str,
                    "old_value": int,
                    "new_value": int,
                    "delta": int
                }

        Raises:
            NotFoundError: If player currencies record not found
            ValidationError: If inputs are invalid

        Example:
            >>> result = await currencies_service.add_resource(
            ...     player_id=123,
            ...     resource_type="lumees",
            ...     amount=1000,
            ...     reason="daily_reward",
            ...     context="/daily"
            ... )
        """
        # Validation
        player_id = InputValidator.validate_discord_id(player_id)
        resource_type = self._validate_resource_type(resource_type)
        amount = InputValidator.validate_positive_integer(
            amount, field_name="amount"
        )
        InputValidator.validate_string(
            reason, field_name="reason", min_length=1, max_length=200
        )

        self.log_operation(
            "add_resource",
            player_id=player_id,
            resource_type=resource_type,
            amount=amount,
            reason=reason,
        )

        # Config-driven: Check max resource limit
        max_limit = self.get_config(f"MAX_{resource_type.upper()}", default=999_999_999)

        # Atomic transaction with pessimistic locking
        async with DatabaseService.get_transaction() as session:
            # Lock the row for update
            currencies = await self._currencies_repo.find_one_where(
                session,
                self._currencies_repo.model_class.player_id == player_id,
                for_update=True,  # SELECT FOR UPDATE
            )

            if not currencies:
                raise NotFoundError("PlayerCurrencies", player_id)

            # Get old value
            old_value: int = getattr(currencies, resource_type)

            # Calculate new value with cap
            new_value = min(old_value + amount, max_limit)
            actual_delta = new_value - old_value

            # Apply change
            setattr(currencies, resource_type, new_value)

            # Audit logging (async, non-blocking)
            await AuditLogger.log_resource_change(
                player_id=player_id,
                resource_type=resource_type,
                old_value=old_value,
                new_value=new_value,
                reason=reason,
                context=context,
            )

            # Event emission for downstream systems
            await self.emit_event(
                event_type="resource.added",
                data={
                    "player_id": player_id,
                    "resource_type": resource_type,
                    "old_value": old_value,
                    "new_value": new_value,
                    "delta": actual_delta,
                    "reason": reason,
                },
            )

            self.log.info(
                f"Resource added: {resource_type} +{actual_delta}",
                extra={
                    "player_id": player_id,
                    "resource_type": resource_type,
                    "old_value": old_value,
                    "new_value": new_value,
                    "requested_amount": amount,
                    "actual_delta": actual_delta,
                    "reason": reason,
                },
            )

            # Transaction auto-commits on exit
            return {
                "player_id": player_id,
                "resource_type": resource_type,
                "old_value": old_value,
                "new_value": new_value,
                "delta": actual_delta,
            }

    async def subtract_resource(
        self,
        player_id: int,
        resource_type: str,
        amount: int,
        reason: str,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Subtract currency from a player's balance.

        This is a **write operation** using get_transaction() with pessimistic locking.

        Args:
            player_id: Discord ID of the player
            resource_type: Type of resource ("lumees", "lumenite", "auric_coin")
            amount: Amount to subtract (must be positive)
            reason: Reason for the subtraction (for audit trail)
            context: Optional command/system context

        Returns:
            Dict with updated balance (same format as add_resource)

        Raises:
            NotFoundError: If player currencies record not found
            InsufficientResourcesError: If player doesn't have enough
            ValidationError: If inputs are invalid

        Example:
            >>> result = await currencies_service.subtract_resource(
            ...     player_id=123,
            ...     resource_type="lumees",
            ...     amount=500,
            ...     reason="fusion_cost",
            ...     context="/fuse"
            ... )
        """
        # Validation
        player_id = InputValidator.validate_discord_id(player_id)
        resource_type = self._validate_resource_type(resource_type)
        amount = InputValidator.validate_positive_integer(
            amount, field_name="amount"
        )
        InputValidator.validate_string(
            reason, field_name="reason", min_length=1, max_length=200
        )

        self.log_operation(
            "subtract_resource",
            player_id=player_id,
            resource_type=resource_type,
            amount=amount,
            reason=reason,
        )

        # Atomic transaction with pessimistic locking
        async with DatabaseService.get_transaction() as session:
            # Lock the row for update
            currencies = await self._currencies_repo.find_one_where(
                session,
                self._currencies_repo.model_class.player_id == player_id,
                for_update=True,  # SELECT FOR UPDATE
            )

            if not currencies:
                raise NotFoundError("PlayerCurrencies", player_id)

            # Get old value
            old_value: int = getattr(currencies, resource_type)

            # Check sufficiency
            if old_value < amount:
                raise InsufficientResourcesError(
                    resource=resource_type,
                    required=amount,
                    current=old_value,
                )

            # Calculate new value
            new_value = old_value - amount

            # Apply change
            setattr(currencies, resource_type, new_value)

            # Audit logging
            await AuditLogger.log_resource_change(
                player_id=player_id,
                resource_type=resource_type,
                old_value=old_value,
                new_value=new_value,
                reason=reason,
                context=context,
            )

            # Event emission
            await self.emit_event(
                event_type="resource.subtracted",
                data={
                    "player_id": player_id,
                    "resource_type": resource_type,
                    "old_value": old_value,
                    "new_value": new_value,
                    "delta": -amount,
                    "reason": reason,
                },
            )

            self.log.info(
                f"Resource subtracted: {resource_type} -{amount}",
                extra={
                    "player_id": player_id,
                    "resource_type": resource_type,
                    "old_value": old_value,
                    "new_value": new_value,
                    "amount": amount,
                    "reason": reason,
                },
            )

            # Transaction auto-commits on exit
            return {
                "player_id": player_id,
                "resource_type": resource_type,
                "old_value": old_value,
                "new_value": new_value,
                "delta": -amount,
            }

    async def transfer_resource(
        self,
        from_player_id: int,
        to_player_id: int,
        resource_type: str,
        amount: int,
        reason: str,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Transfer currency from one player to another.

        Demonstrates multi-entity locking within a single transaction.

        Args:
            from_player_id: Source player Discord ID
            to_player_id: Destination player Discord ID
            resource_type: Type of resource to transfer
            amount: Amount to transfer
            reason: Reason for transfer
            context: Optional command/system context

        Returns:
            Dict with both players' balance changes

        Raises:
            NotFoundError: If either player not found
            InsufficientResourcesError: If source doesn't have enough
            ValidationError: If players are the same or inputs invalid

        Example:
            >>> result = await currencies_service.transfer_resource(
            ...     from_player_id=123,
            ...     to_player_id=456,
            ...     resource_type="lumees",
            ...     amount=1000,
            ...     reason="guild_donation",
            ...     context="/donate"
            ... )
        """
        # Validation
        from_player_id = InputValidator.validate_discord_id(
            from_player_id, field_name="from_player_id"
        )
        to_player_id = InputValidator.validate_discord_id(
            to_player_id, field_name="to_player_id"
        )

        if from_player_id == to_player_id:
            raise ValidationError(
                "player_ids", "Cannot transfer resources to yourself"
            )

        resource_type = self._validate_resource_type(resource_type)
        amount = InputValidator.validate_positive_integer(
            amount, field_name="amount"
        )

        self.log_operation(
            "transfer_resource",
            from_player_id=from_player_id,
            to_player_id=to_player_id,
            resource_type=resource_type,
            amount=amount,
        )

        # Config-driven: Transfer fee (if any)
        transfer_fee_pct = self.get_config("RESOURCE_TRANSFER_FEE_PCT", default=0.0)
        fee = int(amount * transfer_fee_pct)
        amount_after_fee = amount - fee

        # Atomic transaction with multi-entity locking
        async with DatabaseService.get_transaction() as session:
            # Lock both players (in deterministic order to prevent deadlocks)
            player_ids = sorted([from_player_id, to_player_id])

            # Lock first player
            from_currencies = await self._currencies_repo.find_one_where(
                session,
                self._currencies_repo.model_class.player_id == from_player_id,
                for_update=True,
            )

            # Lock second player
            to_currencies = await self._currencies_repo.find_one_where(
                session,
                self._currencies_repo.model_class.player_id == to_player_id,
                for_update=True,
            )

            if not from_currencies:
                raise NotFoundError("PlayerCurrencies", from_player_id)
            if not to_currencies:
                raise NotFoundError("PlayerCurrencies", to_player_id)

            # Check source has enough
            from_old = getattr(from_currencies, resource_type)
            if from_old < amount:
                raise InsufficientResourcesError(
                    resource=resource_type,
                    required=amount,
                    current=from_old,
                )

            # Perform transfer
            to_old = getattr(to_currencies, resource_type)
            from_new = from_old - amount
            to_new = to_old + amount_after_fee

            setattr(from_currencies, resource_type, from_new)
            setattr(to_currencies, resource_type, to_new)

            # Audit both changes
            await AuditLogger.log_resource_change(
                player_id=from_player_id,
                resource_type=resource_type,
                old_value=from_old,
                new_value=from_new,
                reason=f"transfer_out: {reason}",
                context=context,
            )

            await AuditLogger.log_resource_change(
                player_id=to_player_id,
                resource_type=resource_type,
                old_value=to_old,
                new_value=to_new,
                reason=f"transfer_in: {reason}",
                context=context,
            )

            # Event emission
            await self.emit_event(
                event_type="resource.transferred",
                data={
                    "from_player_id": from_player_id,
                    "to_player_id": to_player_id,
                    "resource_type": resource_type,
                    "amount": amount,
                    "fee": fee,
                    "amount_received": amount_after_fee,
                    "reason": reason,
                },
            )

            self.log.info(
                f"Resource transferred: {resource_type} {amount} (fee: {fee})",
                extra={
                    "from_player_id": from_player_id,
                    "to_player_id": to_player_id,
                    "resource_type": resource_type,
                    "amount": amount,
                    "fee": fee,
                    "amount_received": amount_after_fee,
                },
            )

            return {
                "from_player": {
                    "player_id": from_player_id,
                    "old_value": from_old,
                    "new_value": from_new,
                },
                "to_player": {
                    "player_id": to_player_id,
                    "old_value": to_old,
                    "new_value": to_new,
                },
                "fee": fee,
            }

    # ========================================================================
    # PUBLIC API - Fusion Shards Operations
    # ========================================================================

    async def add_shards(
        self,
        player_id: int,
        tier: int,
        amount: int,
        reason: str,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Add fusion shards for a specific tier.

        Args:
            player_id: Discord ID of the player
            tier: Tier level (1-11)
            amount: Amount of shards to add
            reason: Reason for the addition
            context: Optional command/system context

        Returns:
            Dict with updated shard balance

        Raises:
            NotFoundError: If player currencies record not found
            ValidationError: If tier is invalid
        """
        player_id = InputValidator.validate_discord_id(player_id)
        tier = InputValidator.validate_integer(tier, "tier", min_value=1, max_value=11)
        amount = InputValidator.validate_positive_integer(amount, "amount")

        self.log_operation(
            "add_shards",
            player_id=player_id,
            tier=tier,
            amount=amount,
        )

        shard_key = f"tier_{tier}"

        async with DatabaseService.get_transaction() as session:
            currencies = await self._currencies_repo.find_one_where(
                session,
                self._currencies_repo.model_class.player_id == player_id,
                for_update=True,
            )

            if not currencies:
                raise NotFoundError("PlayerCurrencies", player_id)

            old_value = currencies.shards.get(shard_key, 0)
            new_value = old_value + amount
            currencies.shards[shard_key] = new_value

            # Mark the JSON field as modified (SQLAlchemy doesn't auto-detect dict changes)
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(currencies, "shards")

            await AuditLogger.log_resource_change(
                player_id=player_id,
                resource_type=f"shards_{shard_key}",
                old_value=old_value,
                new_value=new_value,
                reason=reason,
                context=context,
            )

            await self.emit_event(
                event_type="shards.added",
                data={
                    "player_id": player_id,
                    "tier": tier,
                    "old_value": old_value,
                    "new_value": new_value,
                    "delta": amount,
                    "reason": reason,
                },
            )

            self.log.info(
                f"Shards added: tier_{tier} +{amount}",
                extra={
                    "player_id": player_id,
                    "tier": tier,
                    "old_value": old_value,
                    "new_value": new_value,
                },
            )

            return {
                "player_id": player_id,
                "tier": tier,
                "old_value": old_value,
                "new_value": new_value,
                "delta": amount,
            }

    async def subtract_shards(
        self,
        player_id: int,
        tier: int,
        amount: int,
        reason: str,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Subtract fusion shards for a specific tier.

        Args:
            player_id: Discord ID of the player
            tier: Tier level (1-11)
            amount: Amount of shards to subtract
            reason: Reason for the subtraction
            context: Optional command/system context

        Returns:
            Dict with updated shard balance

        Raises:
            NotFoundError: If player currencies record not found
            InsufficientResourcesError: If not enough shards
            ValidationError: If tier is invalid
        """
        player_id = InputValidator.validate_discord_id(player_id)
        tier = InputValidator.validate_integer(tier, "tier", min_value=1, max_value=11)
        amount = InputValidator.validate_positive_integer(amount, "amount")

        self.log_operation(
            "subtract_shards",
            player_id=player_id,
            tier=tier,
            amount=amount,
        )

        shard_key = f"tier_{tier}"

        async with DatabaseService.get_transaction() as session:
            currencies = await self._currencies_repo.find_one_where(
                session,
                self._currencies_repo.model_class.player_id == player_id,
                for_update=True,
            )

            if not currencies:
                raise NotFoundError("PlayerCurrencies", player_id)

            old_value = currencies.shards.get(shard_key, 0)

            if old_value < amount:
                raise InsufficientResourcesError(
                    resource=f"shards_{shard_key}",
                    required=amount,
                    current=old_value,
                )

            new_value = old_value - amount
            currencies.shards[shard_key] = new_value

            # Mark the JSON field as modified
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(currencies, "shards")

            await AuditLogger.log_resource_change(
                player_id=player_id,
                resource_type=f"shards_{shard_key}",
                old_value=old_value,
                new_value=new_value,
                reason=reason,
                context=context,
            )

            await self.emit_event(
                event_type="shards.subtracted",
                data={
                    "player_id": player_id,
                    "tier": tier,
                    "old_value": old_value,
                    "new_value": new_value,
                    "delta": -amount,
                    "reason": reason,
                },
            )

            self.log.info(
                f"Shards subtracted: tier_{tier} -{amount}",
                extra={
                    "player_id": player_id,
                    "tier": tier,
                    "old_value": old_value,
                    "new_value": new_value,
                },
            )

            return {
                "player_id": player_id,
                "tier": tier,
                "old_value": old_value,
                "new_value": new_value,
                "delta": -amount,
            }

    async def get_shards(self, player_id: int, tier: int) -> Dict[str, Any]:
        """
        Get shard balance for a specific tier.

        Args:
            player_id: Discord ID of the player
            tier: Tier level (1-11)

        Returns:
            Dict with shard balance

        Raises:
            NotFoundError: If player currencies record not found
            ValidationError: If tier is invalid
        """
        player_id = InputValidator.validate_discord_id(player_id)
        tier = InputValidator.validate_integer(tier, "tier", min_value=1, max_value=11)

        self.log_operation("get_shards", player_id=player_id, tier=tier)

        async with DatabaseService.get_session() as session:
            currencies = await self._currencies_repo.find_one_where(
                session,
                self._currencies_repo.model_class.player_id == player_id,
            )

            if not currencies:
                raise NotFoundError("PlayerCurrencies", player_id)

            shard_key = f"tier_{tier}"
            amount = currencies.shards.get(shard_key, 0)

            return {
                "player_id": player_id,
                "tier": tier,
                "amount": amount,
            }

    # ========================================================================
    # PRIVATE HELPERS
    # ========================================================================

    def _validate_resource_type(self, resource_type: str) -> str:
        """
        Validate and normalize resource type.

        Args:
            resource_type: Resource type string

        Returns:
            Normalized lowercase resource type

        Raises:
            ValidationError: If resource type is invalid
        """
        valid_types = ("lumees", "lumenite", "auric_coin")
        return InputValidator.validate_choice(
            resource_type,
            field_name="resource_type",
            valid_choices=valid_types,
        )
