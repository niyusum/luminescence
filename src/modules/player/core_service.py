"""
Player Core Service - LES 2025 Compliant
==========================================

Purpose
-------
Manages player core identity and collection metadata with full transaction safety,
audit logging, and event emission.

Domain
------
- Player registration and creation
- Identity updates (username, discriminator)
- Leader maiden selection
- Collection metadata (total maidens, unique maidens)
- Player lookups and queries

LUMEN 2025 COMPLIANCE
---------------------
✓ Pure business logic - no Discord dependencies
✓ Transaction-safe - all writes in atomic transactions
✓ Config-driven - no hardcoded game balance values
✓ Domain exceptions - raises NotFoundError, ValidationError
✓ Event-driven - emits events for state changes
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
    NotFoundError,
    ValidationError,
)

if TYPE_CHECKING:
    from logging import Logger

    from src.core.config.manager import ConfigManager
    from src.core.event.bus import EventBus
    from src.database.models.core.player.player_core import PlayerCore


# ============================================================================
# Repository
# ============================================================================


class PlayerCoreRepository(BaseRepository["PlayerCore"]):
    """Repository for PlayerCore model."""

    pass  # Inherits all CRUD from BaseRepository


# ============================================================================
# PlayerCoreService
# ============================================================================


class PlayerCoreService(BaseService):
    """
    Service for managing player core identity and collection metadata.

    Handles player registration, identity updates, leader maiden selection,
    and collection statistics tracking.

    Dependencies
    ------------
    - ConfigManager: For config access
    - EventBus: For emitting player-related events
    - Logger: For structured logging
    - DatabaseService: For transaction management (injected via context)
    - AuditLogger: For audit trail (static)

    Public Methods
    --------------
    - get_player() -> Get player by discord_id
    - create_player() -> Register a new player
    - update_username() -> Update player username/discriminator
    - set_leader_maiden() -> Set player's leader maiden
    - update_collection_metadata() -> Update total/unique maiden counts
    - player_exists() -> Check if player exists
    """

    def __init__(
        self,
        config_manager: ConfigManager,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        """
        Initialize PlayerCoreService with required dependencies.

        Args:
            config_manager: Application configuration manager
            event_bus: Event bus for cross-module communication
            logger: Structured logger instance
        """
        super().__init__(config_manager, event_bus, logger)

        # Initialize repository with proper logger
        from src.database.models.core.player.player_core import PlayerCore

        self._player_repo = PlayerCoreRepository(
            model_class=PlayerCore,
            logger=get_logger(f"{__name__}.PlayerCoreRepository"),
        )

    # ========================================================================
    # PUBLIC API - Read Operations
    # ========================================================================

    async def get_player(self, discord_id: int) -> Dict[str, Any]:
        """
        Get player by Discord ID.

        This is a **read-only** operation using get_session().

        Args:
            discord_id: Discord user ID

        Returns:
            Dict with player information:
                {
                    "discord_id": int,
                    "username": str,
                    "discriminator": Optional[str],
                    "leader_maiden_id": Optional[int],
                    "total_maidens_owned": int,
                    "unique_maidens": int,
                    "created_at": datetime,
                    "updated_at": datetime
                }

        Raises:
            NotFoundError: If player not found

        Example:
            >>> player = await core_service.get_player(123456789)
            >>> print(player["username"])  # "PlayerName"
        """
        discord_id = InputValidator.validate_discord_id(discord_id)

        self.log_operation("get_player", discord_id=discord_id)

        # Read-only operation - use get_session()
        async with DatabaseService.get_session() as session:
            player = await self._player_repo.get(session, discord_id)

            if not player:
                raise NotFoundError("PlayerCore", discord_id)

            return {
                "discord_id": player.discord_id,
                "username": player.username,
                "discriminator": player.discriminator,
                "leader_maiden_id": player.leader_maiden_id,
                "total_maidens_owned": player.total_maidens_owned,
                "unique_maidens": player.unique_maidens,
                "created_at": player.created_at,
                "updated_at": player.updated_at,
            }

    async def player_exists(self, discord_id: int) -> bool:
        """
        Check if a player exists.

        Convenience method for existence checks.

        Args:
            discord_id: Discord user ID

        Returns:
            True if player exists, False otherwise
        """
        discord_id = InputValidator.validate_discord_id(discord_id)

        self.log_operation("player_exists", discord_id=discord_id)

        async with DatabaseService.get_session() as session:
            return await self._player_repo.exists(
                session,
                self._player_repo.model_class.discord_id == discord_id,
            )

    # ========================================================================
    # PUBLIC API - Write Operations
    # ========================================================================

    async def create_player(
        self,
        discord_id: int,
        username: str,
        discriminator: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a new player record.

        This is a **write operation** using get_transaction().

        Args:
            discord_id: Discord user ID (primary key)
            username: Discord username
            discriminator: Discord discriminator (optional, legacy)

        Returns:
            Dict with created player information

        Raises:
            ValidationError: If player already exists or inputs invalid

        Example:
            >>> player = await core_service.create_player(
            ...     discord_id=123456789,
            ...     username="NewPlayer",
            ...     discriminator="0001"
            ... )
        """
        discord_id = InputValidator.validate_discord_id(discord_id)
        username = InputValidator.validate_string(
            username,
            field_name="username",
            min_length=1,
            max_length=100,
        )

        if discriminator:
            discriminator = InputValidator.validate_string(
                discriminator,
                field_name="discriminator",
                min_length=1,
                max_length=10,
            )

        self.log_operation(
            "create_player",
            discord_id=discord_id,
            username=username,
        )

        async with DatabaseService.get_transaction() as session:
            # Check if player already exists
            existing = await self._player_repo.exists(
                session,
                self._player_repo.model_class.discord_id == discord_id,
            )

            if existing:
                raise ValidationError(
                    "discord_id",
                    f"Player {discord_id} already exists",
                )

            # Create new player
            from src.database.models.core.player.player_core import PlayerCore

            new_player = PlayerCore(
                discord_id=discord_id,
                username=username,
                discriminator=discriminator,
                total_maidens_owned=0,
                unique_maidens=0,
                leader_maiden_id=None,
            )

            self._player_repo.add(session, new_player)
            await session.flush()

            # Audit logging
            await AuditLogger.log(
                player_id=discord_id,
                transaction_type="player_created",
                details={"username": username, "discriminator": discriminator},
                context="registration",
            )

            # Event emission
            await self.emit_event(
                event_type="player.created",
                data={
                    "discord_id": discord_id,
                    "username": username,
                    "discriminator": discriminator,
                },
            )

            self.log.info(
                f"Player created: {username}",
                extra={
                    "discord_id": discord_id,
                    "username": username,
                },
            )

            return {
                "discord_id": new_player.discord_id,
                "username": new_player.username,
                "discriminator": new_player.discriminator,
                "total_maidens_owned": new_player.total_maidens_owned,
                "unique_maidens": new_player.unique_maidens,
                "created_at": new_player.created_at,
            }

    async def update_username(
        self,
        discord_id: int,
        username: str,
        discriminator: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Update player username and discriminator.

        This is a **write operation** using get_transaction() with pessimistic locking.

        Args:
            discord_id: Discord user ID
            username: New username
            discriminator: New discriminator (optional)

        Returns:
            Dict with updated player information

        Raises:
            NotFoundError: If player not found
            ValidationError: If inputs invalid

        Example:
            >>> result = await core_service.update_username(
            ...     discord_id=123456789,
            ...     username="UpdatedName",
            ...     discriminator=None
            ... )
        """
        discord_id = InputValidator.validate_discord_id(discord_id)
        username = InputValidator.validate_string(
            username,
            field_name="username",
            min_length=1,
            max_length=100,
        )

        if discriminator:
            discriminator = InputValidator.validate_string(
                discriminator,
                field_name="discriminator",
                min_length=1,
                max_length=10,
            )

        self.log_operation(
            "update_username",
            discord_id=discord_id,
            username=username,
        )

        async with DatabaseService.get_transaction() as session:
            # Lock the player row for update
            player = await self._player_repo.get_for_update(session, discord_id)

            if not player:
                raise NotFoundError("PlayerCore", discord_id)

            old_username = player.username
            old_discriminator = player.discriminator

            # Apply changes
            player.username = username
            player.discriminator = discriminator

            # Audit logging
            await AuditLogger.log(
                player_id=discord_id,
                transaction_type="username_updated",
                details={
                    "old_username": old_username,
                    "new_username": username,
                    "old_discriminator": old_discriminator,
                    "new_discriminator": discriminator,
                },
                context="profile_update",
            )

            # Event emission
            await self.emit_event(
                event_type="player.username_updated",
                data={
                    "discord_id": discord_id,
                    "old_username": old_username,
                    "new_username": username,
                },
            )

            self.log.info(
                f"Username updated: {old_username} -> {username}",
                extra={
                    "discord_id": discord_id,
                    "old_username": old_username,
                    "new_username": username,
                },
            )

            return {
                "discord_id": player.discord_id,
                "username": player.username,
                "discriminator": player.discriminator,
                "old_username": old_username,
                "old_discriminator": old_discriminator,
            }

    async def set_leader_maiden(
        self,
        discord_id: int,
        maiden_id: Optional[int],
        reason: str = "leader_selection",
    ) -> Dict[str, Any]:
        """
        Set or clear player's leader maiden.

        This is a **write operation** using get_transaction() with pessimistic locking.

        Args:
            discord_id: Discord user ID
            maiden_id: Maiden ID to set as leader (None to clear)
            reason: Reason for the change (for audit trail)

        Returns:
            Dict with updated leader information

        Raises:
            NotFoundError: If player not found

        Example:
            >>> result = await core_service.set_leader_maiden(
            ...     discord_id=123456789,
            ...     maiden_id=42,
            ...     reason="player_selection"
            ... )
        """
        discord_id = InputValidator.validate_discord_id(discord_id)

        if maiden_id is not None:
            maiden_id = InputValidator.validate_positive_integer(
                maiden_id, field_name="maiden_id"
            )

        self.log_operation(
            "set_leader_maiden",
            discord_id=discord_id,
            maiden_id=maiden_id,
        )

        async with DatabaseService.get_transaction() as session:
            # Lock the player row for update
            player = await self._player_repo.get_for_update(session, discord_id)

            if not player:
                raise NotFoundError("PlayerCore", discord_id)

            old_leader_id = player.leader_maiden_id

            # Apply change
            player.leader_maiden_id = maiden_id

            # Audit logging
            await AuditLogger.log(
                player_id=discord_id,
                transaction_type="leader_maiden_changed",
                details={
                    "old_leader_id": old_leader_id,
                    "new_leader_id": maiden_id,
                    "reason": reason,
                },
                context="leader_selection",
            )

            # Event emission
            await self.emit_event(
                event_type="player.leader_changed",
                data={
                    "discord_id": discord_id,
                    "old_leader_id": old_leader_id,
                    "new_leader_id": maiden_id,
                    "reason": reason,
                },
            )

            self.log.info(
                f"Leader maiden changed: {old_leader_id} -> {maiden_id}",
                extra={
                    "discord_id": discord_id,
                    "old_leader_id": old_leader_id,
                    "new_leader_id": maiden_id,
                },
            )

            return {
                "discord_id": discord_id,
                "old_leader_id": old_leader_id,
                "new_leader_id": maiden_id,
            }

    async def update_collection_metadata(
        self,
        discord_id: int,
        total_maidens_delta: int = 0,
        unique_maidens_delta: int = 0,
        reason: str = "collection_update",
    ) -> Dict[str, Any]:
        """
        Update player's collection metadata (total and unique maiden counts).

        This is a **write operation** using get_transaction() with pessimistic locking.

        Args:
            discord_id: Discord user ID
            total_maidens_delta: Change in total maidens owned (can be negative)
            unique_maidens_delta: Change in unique maidens (can be negative)
            reason: Reason for the update

        Returns:
            Dict with updated collection metadata

        Raises:
            NotFoundError: If player not found

        Example:
            >>> result = await core_service.update_collection_metadata(
            ...     discord_id=123456789,
            ...     total_maidens_delta=5,
            ...     unique_maidens_delta=2,
            ...     reason="summon_batch"
            ... )
        """
        discord_id = InputValidator.validate_discord_id(discord_id)

        self.log_operation(
            "update_collection_metadata",
            discord_id=discord_id,
            total_delta=total_maidens_delta,
            unique_delta=unique_maidens_delta,
        )

        async with DatabaseService.get_transaction() as session:
            # Lock the player row for update
            player = await self._player_repo.get_for_update(session, discord_id)

            if not player:
                raise NotFoundError("PlayerCore", discord_id)

            old_total = player.total_maidens_owned
            old_unique = player.unique_maidens

            # Apply changes (ensure non-negative)
            player.total_maidens_owned = max(0, old_total + total_maidens_delta)
            player.unique_maidens = max(0, old_unique + unique_maidens_delta)

            # Audit logging
            await AuditLogger.log(
                player_id=discord_id,
                transaction_type="collection_metadata_updated",
                details={
                    "old_total": old_total,
                    "new_total": player.total_maidens_owned,
                    "old_unique": old_unique,
                    "new_unique": player.unique_maidens,
                    "reason": reason,
                },
                context="collection_management",
            )

            # Event emission
            await self.emit_event(
                event_type="player.collection_updated",
                data={
                    "discord_id": discord_id,
                    "old_total": old_total,
                    "new_total": player.total_maidens_owned,
                    "old_unique": old_unique,
                    "new_unique": player.unique_maidens,
                    "total_delta": total_maidens_delta,
                    "unique_delta": unique_maidens_delta,
                    "reason": reason,
                },
            )

            self.log.info(
                f"Collection metadata updated: total {old_total} -> {player.total_maidens_owned}, "
                f"unique {old_unique} -> {player.unique_maidens}",
                extra={
                    "discord_id": discord_id,
                    "old_total": old_total,
                    "new_total": player.total_maidens_owned,
                    "old_unique": old_unique,
                    "new_unique": player.unique_maidens,
                },
            )

            return {
                "discord_id": discord_id,
                "old_total": old_total,
                "new_total": player.total_maidens_owned,
                "old_unique": old_unique,
                "new_unique": player.unique_maidens,
                "total_delta": total_maidens_delta,
                "unique_delta": unique_maidens_delta,
            }
