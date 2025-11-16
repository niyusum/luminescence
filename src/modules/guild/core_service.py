"""
GuildService - Business logic for core guild management
========================================================

Handles:
- Guild creation with treasury initialization
- Guild disbanding with cleanup
- Guild renaming and emblem updates
- Guild level and experience management
- Guild upgrades and perks
- Treasury management (deposits, withdrawals)
- Max member capacity calculations

All operations follow LUMEN LAW (2025):
- Pure business logic, no Discord/UI concerns
- Config-driven costs and progression
- Transaction safety with pessimistic locking
- Event emission for all state changes
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, Optional

from src.core.database.service import DatabaseService
from src.modules.shared.base_repository import BaseRepository
from src.modules.shared.exceptions import InvalidOperationError, NotFoundError
from src.modules.shared.base_service import BaseService
from src.core.validation.input_validator import InputValidator
from src.database.models.social.guild import Guild

if TYPE_CHECKING:
    from logging import Logger
    from src.core.config.manager import ConfigManager
    from src.core.event.bus import EventBus


class GuildService(BaseService):
    """
    GuildService handles core guild management operations.

    Business Logic:
    - Guild creation validates name uniqueness and costs
    - Treasury starts with 0 and accumulates from donations
    - Level progression uses config-driven XP curves
    - Upgrades unlock perks and increase member capacity
    - Renaming/emblem changes have cooldowns and costs
    """

    def __init__(
        self,
        config_manager: ConfigManager,
        event_bus: EventBus,
        logger: Logger,
    ):
        """Initialize GuildService with Guild repository."""
        super().__init__(config_manager, event_bus, logger)
        self._guild_repo = BaseRepository[Guild](Guild, self.log)

    # -------------------------------------------------------------------------
    # Core Operations
    # -------------------------------------------------------------------------

    async def create_guild(
        self,
        guild_name: str,
        founder_id: int,
        emblem: Optional[str] = None,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a new guild.

        Args:
            guild_name: Name of the guild
            founder_id: Discord ID of guild founder
            emblem: Optional emblem/icon identifier
            context: Operation context for audit

        Returns:
            Dict with guild data

        Raises:
            InvalidOperationError: Name already taken, invalid name
        """
        # Validation
        guild_name = InputValidator.validate_string(
            guild_name, "guild_name", min_length=3, max_length=32
        )
        founder_id = InputValidator.validate_discord_id(founder_id)

        # Get creation cost
        creation_cost = self.get_config("guilds.creation_cost", default=50000)

        async with DatabaseService.get_transaction() as session:
            # Check name uniqueness
            existing = await self._guild_repo.find_one_where(
                session,
                Guild.name == guild_name,
            )

            if existing:
                raise InvalidOperationError("create_guild", f"Guild name '{guild_name}' is already taken")

            # Create guild
            base_max_members = self.get_config("guilds.base_max_members", default=10)

            guild = Guild(
                name=guild_name,
                owner_id=founder_id,
                emblem=emblem,
                level=1,
                experience=0,
                treasury=0,
                max_members=base_max_members,
                member_count=0,  # Founder will be added separately
                is_recruiting=True,
            )

            session.add(guild)
            await session.flush()

            # Emit event
            await self.emit_event(
                "guild.created",
                {
                    "guild_id": guild.id,
                    "guild_name": guild_name,
                    "founder_id": founder_id,
                    "creation_cost": creation_cost,
                },
            )

            return {
                "guild_id": guild.id,
                "guild_name": guild.name,
                "owner_id": guild.owner_id,
                "level": guild.level,
                "max_members": guild.max_members,
                "creation_cost": creation_cost,
                "created_at": guild.created_at,
            }

    async def disband_guild(
        self,
        guild_id: int,
        requester_id: int,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Disband a guild (soft delete).

        Args:
            guild_id: Guild ID to disband
            requester_id: Discord ID of requester (must be owner)
            context: Operation context for audit

        Returns:
            Dict with disbanding confirmation

        Raises:
            NotFoundError: Guild not found
            InvalidOperationError: Requester is not owner
        """
        # Validation
        guild_id = InputValidator.validate_positive_integer(guild_id, "guild_id")
        requester_id = InputValidator.validate_discord_id(requester_id)

        async with DatabaseService.get_transaction() as session:
            # Get guild with pessimistic lock
            guild = await self._guild_repo.find_one_where(
                session,
                Guild.id == guild_id,
                for_update=True,
            )

            if not guild:
                raise NotFoundError(f"Guild {guild_id} not found")

            # Ownership check
            if guild.owner_id != requester_id:
                raise InvalidOperationError(
                    "disband_guild", "Only the guild owner can disband the guild"
                )

            # Soft delete
            guild.deleted_at = datetime.now(timezone.utc)

            # Emit event
            await self.emit_event(
                "guild.disbanded",
                {
                    "guild_id": guild_id,
                    "guild_name": guild.name,
                    "owner_id": guild.owner_id,
                    "member_count": guild.member_count,
                    "treasury_refund": guild.treasury,
                },
            )

            return {
                "guild_id": guild_id,
                "guild_name": guild.name,
                "disbanded_at": guild.deleted_at,
                "treasury_refund": guild.treasury,
            }

    async def rename_guild(
        self,
        guild_id: int,
        new_name: str,
        requester_id: int,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Rename a guild.

        Args:
            guild_id: Guild ID
            new_name: New guild name
            requester_id: Discord ID of requester (must be owner)
            context: Operation context for audit

        Returns:
            Dict with rename confirmation

        Raises:
            NotFoundError: Guild not found
            InvalidOperationError: Name taken, not owner, insufficient funds
        """
        # Validation
        guild_id = InputValidator.validate_positive_integer(guild_id, "guild_id")
        new_name = InputValidator.validate_string(
            new_name, "new_name", min_length=3, max_length=32
        )
        requester_id = InputValidator.validate_discord_id(requester_id)

        # Get rename cost
        rename_cost = self.get_config("guilds.name_change_cost", default=10000)

        async with DatabaseService.get_transaction() as session:
            # Get guild with pessimistic lock
            guild = await self._guild_repo.find_one_where(
                session,
                Guild.id == guild_id,
                for_update=True,
            )

            if not guild:
                raise NotFoundError(f"Guild {guild_id} not found")

            # Ownership check
            if guild.owner_id != requester_id:
                raise InvalidOperationError("rename_guild", "Only the guild owner can rename the guild")

            # Check name uniqueness
            existing = await self._guild_repo.find_one_where(
                session,
                Guild.name == new_name,
            )

            if existing and existing.id != guild_id:
                raise InvalidOperationError("rename_guild", f"Guild name '{new_name}' is already taken")

            # Update name
            old_name = guild.name
            guild.name = new_name

            # Emit event (cost deduction handled by listener)
            await self.emit_event(
                "guild.renamed",
                {
                    "guild_id": guild_id,
                    "old_name": old_name,
                    "new_name": new_name,
                    "requester_id": requester_id,
                    "rename_cost": rename_cost,
                },
            )

            return {
                "guild_id": guild_id,
                "old_name": old_name,
                "new_name": new_name,
                "rename_cost": rename_cost,
            }

    async def deposit_to_treasury(
        self,
        guild_id: int,
        amount: int,
        donor_id: int,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Deposit lumees to guild treasury.

        Args:
            guild_id: Guild ID
            amount: Amount to deposit
            donor_id: Discord ID of donor
            context: Operation context for audit

        Returns:
            Dict with deposit confirmation

        Raises:
            NotFoundError: Guild not found
            InvalidOperationError: Below minimum donation
        """
        # Validation
        guild_id = InputValidator.validate_positive_integer(guild_id, "guild_id")
        amount = InputValidator.validate_positive_integer(amount, "amount")
        donor_id = InputValidator.validate_discord_id(donor_id)

        # Check minimum donation
        min_donation = self.get_config("guilds.donation_minimum", default=1000)
        if amount < min_donation:
            raise InvalidOperationError(
                "deposit_to_treasury", f"Donation must be at least {min_donation} lumees"
            )

        async with DatabaseService.get_transaction() as session:
            # Get guild with pessimistic lock
            guild = await self._guild_repo.find_one_where(
                session,
                Guild.id == guild_id,
                for_update=True,
            )

            if not guild:
                raise NotFoundError(f"Guild {guild_id} not found")

            # Update treasury
            old_treasury = guild.treasury
            guild.treasury += amount
            new_treasury = guild.treasury

            # Emit event
            await self.emit_event(
                "guild.treasury_deposit",
                {
                    "guild_id": guild_id,
                    "donor_id": donor_id,
                    "amount": amount,
                    "old_treasury": old_treasury,
                    "new_treasury": new_treasury,
                },
            )

            return {
                "guild_id": guild_id,
                "amount_deposited": amount,
                "old_treasury": old_treasury,
                "new_treasury": new_treasury,
            }

    async def get_guild_info(
        self,
        guild_id: int,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get detailed guild information.

        Args:
            guild_id: Guild ID
            context: Operation context

        Returns:
            Dict with full guild details

        Raises:
            NotFoundError: Guild not found
        """
        # Validation
        guild_id = InputValidator.validate_positive_integer(guild_id, "guild_id")

        async with DatabaseService.get_transaction() as session:
            guild = await self._guild_repo.find_one_where(
                session,
                Guild.id == guild_id,
            )

            if not guild:
                raise NotFoundError(f"Guild {guild_id} not found")

            return {
                "guild_id": guild.id,
                "name": guild.name,
                "owner_id": guild.owner_id,
                "emblem_url": guild.emblem_url,
                "level": guild.level,
                "experience": guild.experience,
                "treasury": guild.treasury,
                "max_members": guild.max_members,
                "member_count": guild.member_count,
                "is_recruiting": guild.meta.get("is_recruiting", True) if guild.meta else True,
                "created_at": guild.created_at,
                "updated_at": guild.updated_at,
            }
