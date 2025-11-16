"""
GuildAuditService - Business logic for guild audit trail management
===================================================================

Handles:
- Creating audit entries for guild actions
- Querying and filtering audit history
- Auto-cleanup of old audit records
- Audit data formatting for UI display

All operations follow LUMEN LAW (2025):
- Pure business logic, no Discord/UI concerns
- Config-driven retention policies
- Transaction safety with pessimistic locking
- Event emission for all state changes
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from sqlalchemy import delete, desc, select

from src.core.database.service import DatabaseService
from src.modules.shared.base_repository import BaseRepository
from src.modules.shared.exceptions import NotFoundError
from src.modules.shared.base_service import BaseService
from src.core.validation.input_validator import InputValidator
from src.database.models.social.guild import Guild
from src.database.models.social.guild_audit import GuildAudit

if TYPE_CHECKING:
    from logging import Logger
    from src.core.config.manager import ConfigManager
    from src.core.event.bus import EventBus


class GuildAuditService(BaseService):
    """
    GuildAuditService handles guild audit trail operations.

    Business Logic:
    - All guild actions create immutable audit entries
    - Audit entries include actor, action, and metadata
    - System actions have nullable actor_player_id
    - Old audits auto-cleaned based on retention policy
    - Audit queries support filtering and pagination
    """

    def __init__(
        self,
        config_manager: ConfigManager,
        event_bus: EventBus,
        logger: Logger,
    ):
        """Initialize GuildAuditService."""
        super().__init__(config_manager, event_bus, logger)
        self._guild_repo = BaseRepository[Guild](Guild, self.log)
        self._audit_repo = BaseRepository[GuildAudit](GuildAudit, self.log)

    # -------------------------------------------------------------------------
    # Core Operations
    # -------------------------------------------------------------------------

    async def create_audit_entry(
        self,
        guild_id: int,
        action: str,
        meta: Optional[Dict[str, Any]] = None,
        actor_player_id: Optional[int] = None,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create an audit trail entry.

        Args:
            guild_id: Guild ID
            action: Action type (e.g., "member_joined", "treasury_deposit")
            meta: Metadata dict with action details
            actor_player_id: Discord ID of actor (None for system actions)
            context: Operation context

        Returns:
            Dict with audit entry details

        Raises:
            NotFoundError: Guild not found
        """
        # Validation
        guild_id = InputValidator.validate_positive_integer(guild_id, "guild_id")
        action = InputValidator.validate_string(action, "action", min_length=1, max_length=50)

        if actor_player_id is not None:
            actor_player_id = InputValidator.validate_discord_id(actor_player_id)

        if meta is None:
            meta = {}

        async with DatabaseService.get_transaction() as session:
            # Verify guild exists
            guild = await self._guild_repo.find_one_where(
                session,
                Guild.id == guild_id,
            )

            if not guild:
                raise NotFoundError(f"Guild {guild_id} not found")

            # Create audit entry
            audit = GuildAudit(
                guild_id=guild_id,
                actor_player_id=actor_player_id,
                action=action,
                meta=meta,
            )

            session.add(audit)
            await session.flush()

            # Emit event
            await self.emit_event(
                "guild.audit_entry_created",
                {
                    "audit_id": audit.id,
                    "guild_id": guild_id,
                    "action": action,
                    "actor_player_id": actor_player_id,
                },
            )

            return {
                "audit_id": audit.id,
                "guild_id": guild_id,
                "action": action,
                "actor_player_id": actor_player_id,
                "meta": meta,
                "created_at": audit.created_at,
            }

    async def get_audit_history(
        self,
        guild_id: int,
        action_filter: Optional[str] = None,
        actor_filter: Optional[int] = None,
        limit: int = 100,
        offset: int = 0,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get audit history for a guild with optional filtering.

        Args:
            guild_id: Guild ID
            action_filter: Optional action type filter
            actor_filter: Optional actor player ID filter
            limit: Maximum number of entries to return
            offset: Pagination offset
            context: Operation context

        Returns:
            Dict with audit history list

        Raises:
            NotFoundError: Guild not found
        """
        # Validation
        guild_id = InputValidator.validate_positive_integer(guild_id, "guild_id")
        limit = InputValidator.validate_positive_integer(limit, "limit")

        if limit > 1000:
            limit = 1000  # Hard cap

        async with DatabaseService.get_transaction() as session:
            # Verify guild exists
            guild = await self._guild_repo.find_one_where(
                session,
                Guild.id == guild_id,
            )

            if not guild:
                raise NotFoundError(f"Guild {guild_id} not found")

            # Build query
            conditions = [GuildAudit.guild_id == guild_id]

            if action_filter:
                conditions.append(GuildAudit.action == action_filter)

            if actor_filter is not None:
                actor_filter = InputValidator.validate_discord_id(actor_filter)
                conditions.append(GuildAudit.actor_player_id == actor_filter)

            # Execute query with pagination
            stmt = (
                select(GuildAudit)
                .where(*conditions)
                .order_by(desc(GuildAudit.created_at))
                .limit(limit)
                .offset(offset)
            )

            result = await session.execute(stmt)
            audits = result.scalars().all()

            # Format results
            audit_list = [
                {
                    "audit_id": audit.id,
                    "action": audit.action,
                    "actor_player_id": audit.actor_player_id,
                    "meta": audit.meta,
                    "created_at": audit.created_at,
                }
                for audit in audits
            ]

            return {
                "guild_id": guild_id,
                "guild_name": guild.name,
                "audit_entries": audit_list,
                "count": len(audit_list),
                "limit": limit,
                "offset": offset,
            }

    async def cleanup_old_audits(
        self,
        retention_days: Optional[int] = None,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Delete audit entries older than retention period.

        Args:
            retention_days: Number of days to retain (None = use config)
            context: Operation context

        Returns:
            Dict with cleanup stats

        Raises:
            None
        """
        if retention_days is None:
            retention_days = self.get_config("guilds.audit_retention_days", default=90)

        assert retention_days is not None  # Type narrowing after config assignment

        async with DatabaseService.get_transaction() as session:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)

            # Delete old audits
            delete_stmt = delete(GuildAudit).where(GuildAudit.created_at < cutoff_date)

            result = await session.execute(delete_stmt)
            deleted_count = result.rowcount  # type: ignore[reportAttributeAccessIssue]

            # Emit event
            if deleted_count > 0:
                await self.emit_event(
                    "guild.audits_cleaned_up",
                    {
                        "deleted_count": deleted_count,
                        "retention_days": retention_days,
                        "cutoff_date": cutoff_date.isoformat(),
                    },
                )

            return {
                "deleted_count": deleted_count,
                "retention_days": retention_days,
                "cutoff_date": cutoff_date,
            }

    async def get_recent_actions(
        self,
        guild_id: int,
        action_types: List[str],
        hours: int = 24,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get recent audit entries of specific action types.

        Args:
            guild_id: Guild ID
            action_types: List of action types to filter
            hours: Number of hours to look back
            context: Operation context

        Returns:
            Dict with recent actions

        Raises:
            NotFoundError: Guild not found
        """
        # Validation
        guild_id = InputValidator.validate_positive_integer(guild_id, "guild_id")
        hours = InputValidator.validate_positive_integer(hours, "hours")

        async with DatabaseService.get_transaction() as session:
            # Verify guild exists
            guild = await self._guild_repo.find_one_where(
                session,
                Guild.id == guild_id,
            )

            if not guild:
                raise NotFoundError(f"Guild {guild_id} not found")

            # Calculate cutoff time
            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)

            # Query recent actions
            stmt = (
                select(GuildAudit)
                .where(
                    GuildAudit.guild_id == guild_id,
                    GuildAudit.action.in_(action_types),
                    GuildAudit.created_at >= cutoff_time,
                )
                .order_by(desc(GuildAudit.created_at))
            )

            result = await session.execute(stmt)
            audits = result.scalars().all()

            # Format results
            action_list = [
                {
                    "audit_id": audit.id,
                    "action": audit.action,
                    "actor_player_id": audit.actor_player_id,
                    "meta": audit.meta,
                    "created_at": audit.created_at,
                }
                for audit in audits
            ]

            return {
                "guild_id": guild_id,
                "guild_name": guild.name,
                "action_types": action_types,
                "hours": hours,
                "recent_actions": action_list,
                "count": len(action_list),
            }

    async def get_player_actions(
        self,
        guild_id: int,
        player_id: int,
        limit: int = 50,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get audit history for a specific player in a guild.

        Args:
            guild_id: Guild ID
            player_id: Discord ID of player
            limit: Maximum number of entries to return
            context: Operation context

        Returns:
            Dict with player's audit history

        Raises:
            NotFoundError: Guild not found
        """
        # Validation
        guild_id = InputValidator.validate_positive_integer(guild_id, "guild_id")
        player_id = InputValidator.validate_discord_id(player_id)
        limit = InputValidator.validate_positive_integer(limit, "limit")

        if limit > 500:
            limit = 500  # Hard cap

        async with DatabaseService.get_transaction() as session:
            # Verify guild exists
            guild = await self._guild_repo.find_one_where(
                session,
                Guild.id == guild_id,
            )

            if not guild:
                raise NotFoundError(f"Guild {guild_id} not found")

            # Query player actions
            stmt = (
                select(GuildAudit)
                .where(
                    GuildAudit.guild_id == guild_id,
                    GuildAudit.actor_player_id == player_id,
                )
                .order_by(desc(GuildAudit.created_at))
                .limit(limit)
            )

            result = await session.execute(stmt)
            audits = result.scalars().all()

            # Format results
            action_list = [
                {
                    "audit_id": audit.id,
                    "action": audit.action,
                    "meta": audit.meta,
                    "created_at": audit.created_at,
                }
                for audit in audits
            ]

            return {
                "guild_id": guild_id,
                "guild_name": guild.name,
                "player_id": player_id,
                "actions": action_list,
                "count": len(action_list),
            }
