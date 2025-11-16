"""
Service Template - YOUR_MODULE_NAMEService (Lumen 2025)

Purpose
-------
[Brief description of what this service does - 1-2 sentences]

Example:
    Manages player inventory operations including item acquisition, consumption,
    and equipment with full transaction safety and audit logging.

Domain
------
[List the core domain responsibilities]

Example:
    - Add items to player inventory
    - Remove items from player inventory
    - Equip/unequip items
    - Check item ownership
    - Enforce inventory capacity limits

LUMEN 2025 COMPLIANCE
---------------------
✓ Pure business logic - no Discord dependencies
✓ Transaction-safe - all writes in atomic transactions
✓ Config-driven - no hardcoded game balance values
✓ Domain exceptions - raises appropriate exceptions
✓ Event-driven - emits events for state changes
✓ Observable - structured logging, audit trail
✓ Pessimistic locking - uses SELECT FOR UPDATE for writes

Dependencies
------------
- ConfigManager: For [specific config values used]
- EventBus: For emitting [list event types]
- Logger: For structured logging
- DatabaseService: For transaction management
- AuditLogger: For audit trail (optional but recommended)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from src.core.database.service import DatabaseService
from src.core.infra.audit_logger import AuditLogger  # Optional
from src.core.logging.logger import get_logger
from src.core.validation.input_validator import InputValidator
from src.modules.shared.base_repository import BaseRepository
from src.modules.shared.base_service import BaseService

# Import domain exceptions you need:
# from src.modules.shared.exceptions import (
#     InsufficientResourcesError,
#     NotFoundError,
#     ValidationError,
#     InvalidOperationError,
# )

if TYPE_CHECKING:
    from logging import Logger

    from src.core.config.manager import ConfigManager
    from src.core.event.bus import EventBus
    # from src.database.models.YOUR_MODEL import YourModel


# ============================================================================
# Repository (if needed)
# ============================================================================


class YourModelRepository(BaseRepository["YourModel"]):  # type: ignore[name-defined]
    """
    Repository for YourModel.

    Add custom query methods here if BaseRepository doesn't provide them:

    async def find_by_player_and_status(
        self,
        session: AsyncSession,
        player_id: int,
        status: str,
    ) -> List[YourModel]:
        '''Find all entities matching player and status.'''
        return await self.find_many_where(
            session,
            YourModel.player_id == player_id,
            YourModel.status == status,
        )
    """

    pass


# ============================================================================
# Service
# ============================================================================


class YourModuleService(BaseService):
    """
    Service for [brief description].

    [Longer description of what this service manages and how it fits into
    the larger system architecture]

    Public Methods
    --------------
    List all public methods with brief descriptions:
    - method_name() -> What it does
    - another_method() -> What it does

    Example:
        - get_inventory() -> Get player's current inventory
        - add_item() -> Add an item to inventory
        - remove_item() -> Remove an item from inventory
    """

    def __init__(
        self,
        config_manager: ConfigManager,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        """
        Initialize YourModuleService with required dependencies.

        Args:
            config_manager: Application configuration manager
            event_bus: Event bus for cross-module communication
            logger: Structured logger instance
        """
        super().__init__(config_manager, event_bus, logger)

        # Initialize repositories
        # from src.database.models.YOUR_MODEL import YourModel
        # self._your_repo = YourModelRepository(
        #     model_class=YourModel,
        #     logger=get_logger(f"{__name__}.YourModelRepository"),
        # )

    # ========================================================================
    # PUBLIC API - Read Operations
    # ========================================================================

    async def read_operation_example(
        self, player_id: int, some_param: str
    ) -> Dict[str, Any]:
        """
        [Description of what this read operation does]

        This is a **read-only** operation using get_session().

        Args:
            player_id: Discord ID of the player
            some_param: Description of parameter

        Returns:
            Dict containing:
                - key1: description
                - key2: description

        Raises:
            NotFoundError: If [condition]
            ValidationError: If [condition]

        Example:
            >>> result = await service.read_operation_example(123, "test")
            >>> print(result["key1"])
        """
        # Step 1: Validate all inputs
        player_id = InputValidator.validate_discord_id(player_id)
        # Add more validation as needed

        # Step 2: Log operation start
        self.log_operation(
            "read_operation_example",
            player_id=player_id,
            some_param=some_param,
        )

        # Step 3: Read-only database access
        async with DatabaseService.get_session() as session:
            # Query database using repository
            # entity = await self._your_repo.find_one_where(
            #     session,
            #     YourModel.player_id == player_id,
            # )

            # Step 4: Build and return response
            return {
                "player_id": player_id,
                # ... your data
            }

    # ========================================================================
    # PUBLIC API - Write Operations
    # ========================================================================

    async def write_operation_example(
        self,
        player_id: int,
        amount: int,
        reason: str,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        [Description of what this write operation does]

        This is a **write operation** using get_transaction() with pessimistic locking.

        Args:
            player_id: Discord ID of the player
            amount: Amount to process (must be positive)
            reason: Reason for the operation (for audit)
            context: Optional command/system context

        Returns:
            Dict containing operation results

        Raises:
            NotFoundError: If [condition]
            ValidationError: If [condition]
            InsufficientResourcesError: If [condition]

        Example:
            >>> result = await service.write_operation_example(
            ...     player_id=123,
            ...     amount=100,
            ...     reason="reward",
            ...     context="/claim"
            ... )
        """
        # Step 1: Validate all inputs
        player_id = InputValidator.validate_discord_id(player_id)
        amount = InputValidator.validate_positive_integer(
            amount, field_name="amount"
        )
        InputValidator.validate_string(
            reason, field_name="reason", min_length=1, max_length=200
        )

        # Step 2: Log operation start
        self.log_operation(
            "write_operation_example",
            player_id=player_id,
            amount=amount,
            reason=reason,
        )

        # Step 3: Get config values if needed
        # max_limit = self.get_config("MAX_SOME_VALUE", default=999_999)

        # Step 4: Atomic transaction with pessimistic locking
        async with DatabaseService.get_transaction() as session:
            # Lock the entity for update
            # entity = await self._your_repo.find_one_where(
            #     session,
            #     YourModel.player_id == player_id,
            #     for_update=True,  # SELECT FOR UPDATE
            # )

            # if not entity:
            #     raise NotFoundError("YourModel", player_id)

            # Get old value
            # old_value = entity.some_field

            # Perform business logic
            # new_value = old_value + amount
            # entity.some_field = new_value

            # Step 5: Audit logging (optional but recommended)
            # await AuditLogger.log(
            #     player_id=player_id,
            #     transaction_type="your_operation_type",
            #     details={
            #         "old_value": old_value,
            #         "new_value": new_value,
            #         "amount": amount,
            #         "reason": reason,
            #     },
            #     context=context,
            # )

            # Step 6: Event emission
            # await self.emit_event(
            #     event_type="your_module.event_name",
            #     data={
            #         "player_id": player_id,
            #         "amount": amount,
            #         "reason": reason,
            #     },
            # )

            # Step 7: Structured logging
            # self.log.info(
            #     f"Operation completed: +{amount}",
            #     extra={
            #         "player_id": player_id,
            #         "old_value": old_value,
            #         "new_value": new_value,
            #         "amount": amount,
            #         "reason": reason,
            #     },
            # )

            # Step 8: Return results
            # Transaction auto-commits on exit
            return {
                "player_id": player_id,
                # ... your results
            }

    # ========================================================================
    # PRIVATE HELPERS
    # ========================================================================

    def _validate_custom_field(self, value: str) -> str:
        """
        Validate and normalize a custom domain-specific field.

        Args:
            value: Raw value to validate

        Returns:
            Normalized value

        Raises:
            ValidationError: If value is invalid

        Example:
            >>> normalized = self._validate_custom_field("Test")
            >>> print(normalized)  # "test"
        """
        # Example: validate against allowed choices
        # valid_choices = ("option1", "option2", "option3")
        # return InputValidator.validate_choice(
        #     value,
        #     field_name="custom_field",
        #     valid_choices=valid_choices,
        # )
        raise NotImplementedError("Replace this with your validation logic")

    def _calculate_something(self, base_value: int, multiplier: float) -> int:
        """
        Calculate a domain-specific value.

        Private helper methods should be pure functions when possible.

        Args:
            base_value: Base value to calculate from
            multiplier: Multiplier to apply

        Returns:
            Calculated value
        """
        return int(base_value * multiplier)


# ============================================================================
# USAGE EXAMPLE (remove this section in real implementation)
# ============================================================================

"""
How to instantiate and use this service:

# In your module's __init__.py or service factory:
from src.core.config.manager import ConfigManager
from src.core.event.bus import event_bus
from src.core.logging.logger import get_logger

config = ConfigManager()
logger = get_logger("your_module.service")

your_service = YourModuleService(
    config_manager=config,
    event_bus=event_bus,
    logger=logger,
)

# In your cog:
async def your_command(self, ctx):
    try:
        result = await your_service.write_operation_example(
            player_id=ctx.author.id,
            amount=100,
            reason="command_reward",
            context=ctx.command.name,
        )
        # Build success embed
    except InsufficientResourcesError as e:
        # Build error embed
    except ValidationError as e:
        # Build validation error embed
"""
