"""
GuildMemberService - Business logic for guild membership management
====================================================================

Handles:
- Guild membership (join, leave, kick)
- Role promotions and demotions
- Contribution tracking
- Member count synchronization
- Membership validation and capacity checks

All operations follow LUMEN LAW (2025):
- Pure business logic, no Discord/UI concerns
- Config-driven membership limits
- Transaction safety with pessimistic locking
- Event emission for all state changes
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, Optional

from sqlalchemy import func, select

from src.core.database.service import DatabaseService
from src.modules.shared.base_repository import BaseRepository
from src.modules.shared.exceptions import InvalidOperationError, NotFoundError
from src.modules.shared.base_service import BaseService
from src.core.validation.input_validator import InputValidator
from src.database.models.social.guild import Guild
from src.database.models.social.guild_member import GuildMember
from src.database.models.social.guild_role import GuildRole

if TYPE_CHECKING:
    from logging import Logger
    from src.core.config.manager import ConfigManager
    from src.core.event.bus import EventBus


class GuildMemberService(BaseService):
    """
    GuildMemberService handles all guild membership operations.

    Business Logic:
    - Members can join guilds up to max capacity
    - Members can leave voluntarily
    - Leaders/officers can kick members
    - Role promotions follow hierarchy (member -> officer -> leader)
    - Contribution tracking for guild rewards
    - Member count always synchronized with Guild.member_count
    """

    def __init__(
        self,
        config_manager: ConfigManager,
        event_bus: EventBus,
        logger: Logger,
    ):
        """Initialize GuildMemberService."""
        super().__init__(config_manager, event_bus, logger)
        self._guild_repo = BaseRepository[Guild](Guild, self.log)
        self._member_repo = BaseRepository[GuildMember](GuildMember, self.log)

    # -------------------------------------------------------------------------
    # Core Operations
    # -------------------------------------------------------------------------

    async def join_guild(
        self,
        guild_id: int,
        player_id: int,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Add a player to a guild.

        Args:
            guild_id: Guild ID to join
            player_id: Discord ID of player
            context: Operation context for audit

        Returns:
            Dict with membership details

        Raises:
            NotFoundError: Guild not found
            InvalidOperationError: Already member, guild full
        """
        # Validation
        guild_id = InputValidator.validate_positive_integer(guild_id, "guild_id")
        player_id = InputValidator.validate_discord_id(player_id)

        async with DatabaseService.get_transaction() as session:
            # Get guild with pessimistic lock
            guild = await self._guild_repo.find_one_where(
                session,
                Guild.id == guild_id,
                for_update=True,
            )

            if not guild:
                raise NotFoundError(f"Guild {guild_id} not found")

            # Check if player is already a member
            existing_member = await self._member_repo.find_one_where(
                session,
                GuildMember.guild_id == guild_id,
                GuildMember.player_id == player_id,
            )

            if existing_member:
                raise InvalidOperationError(
                    "join_guild", f"Player {player_id} is already a member of guild {guild_id}"
                )

            # Check guild capacity
            if guild.member_count >= guild.max_members:
                raise InvalidOperationError(
                    "join_guild", f"Guild {guild_id} is full ({guild.member_count}/{guild.max_members})"
                )

            # Create membership
            member = GuildMember(
                guild_id=guild_id,
                player_id=player_id,
                role=GuildRole.member.value,
                contribution=0,
            )

            session.add(member)

            # Update guild member count
            guild.member_count += 1

            await session.flush()

            # Emit event
            await self.emit_event(
                "guild.member_joined",
                {
                    "guild_id": guild_id,
                    "guild_name": guild.name,
                    "player_id": player_id,
                    "role": member.role,
                    "new_member_count": guild.member_count,
                },
            )

            return {
                "guild_id": guild_id,
                "guild_name": guild.name,
                "player_id": player_id,
                "role": member.role,
                "member_count": guild.member_count,
                "max_members": guild.max_members,
                "joined_at": member.created_at,
            }

    async def leave_guild(
        self,
        guild_id: int,
        player_id: int,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Remove a player from a guild (voluntary leave).

        Args:
            guild_id: Guild ID
            player_id: Discord ID of player
            context: Operation context for audit

        Returns:
            Dict with leave confirmation

        Raises:
            NotFoundError: Guild or membership not found
            InvalidOperationError: Leader cannot leave (must transfer or disband)
        """
        # Validation
        guild_id = InputValidator.validate_positive_integer(guild_id, "guild_id")
        player_id = InputValidator.validate_discord_id(player_id)

        async with DatabaseService.get_transaction() as session:
            # Get guild with pessimistic lock
            guild = await self._guild_repo.find_one_where(
                session,
                Guild.id == guild_id,
                for_update=True,
            )

            if not guild:
                raise NotFoundError(f"Guild {guild_id} not found")

            # Get membership
            member = await self._member_repo.find_one_where(
                session,
                GuildMember.guild_id == guild_id,
                GuildMember.player_id == player_id,
                for_update=True,
            )

            if not member:
                raise NotFoundError(
                    f"Player {player_id} is not a member of guild {guild_id}"
                )

            # Leaders cannot leave - must transfer or disband
            if guild.owner_id == player_id:
                raise InvalidOperationError(
                    "leave_guild", "Guild leader cannot leave. Transfer leadership or disband the guild."
                )

            # Soft delete membership
            member.deleted_at = datetime.now(timezone.utc)

            # Update guild member count
            guild.member_count -= 1

            # Emit event
            await self.emit_event(
                "guild.member_left",
                {
                    "guild_id": guild_id,
                    "guild_name": guild.name,
                    "player_id": player_id,
                    "role": member.role,
                    "contribution": member.contribution,
                    "new_member_count": guild.member_count,
                },
            )

            return {
                "guild_id": guild_id,
                "guild_name": guild.name,
                "player_id": player_id,
                "contribution": member.contribution,
                "member_count": guild.member_count,
                "left_at": member.deleted_at,
            }

    async def kick_member(
        self,
        guild_id: int,
        target_player_id: int,
        kicker_id: int,
        reason: Optional[str] = None,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Kick a player from a guild.

        Args:
            guild_id: Guild ID
            target_player_id: Discord ID of player to kick
            kicker_id: Discord ID of player performing the kick
            reason: Optional reason for kick
            context: Operation context for audit

        Returns:
            Dict with kick confirmation

        Raises:
            NotFoundError: Guild or membership not found
            InvalidOperationError: Insufficient permissions, cannot kick leader
        """
        # Validation
        guild_id = InputValidator.validate_positive_integer(guild_id, "guild_id")
        target_player_id = InputValidator.validate_discord_id(target_player_id)
        kicker_id = InputValidator.validate_discord_id(kicker_id)

        async with DatabaseService.get_transaction() as session:
            # Get guild with pessimistic lock
            guild = await self._guild_repo.find_one_where(
                session,
                Guild.id == guild_id,
                for_update=True,
            )

            if not guild:
                raise NotFoundError(f"Guild {guild_id} not found")

            # Get kicker membership (verify permission)
            kicker_member = await self._member_repo.find_one_where(
                session,
                GuildMember.guild_id == guild_id,
                GuildMember.player_id == kicker_id,
            )

            if not kicker_member:
                raise InvalidOperationError(
                    "kick_member", f"Player {kicker_id} is not a member of guild {guild_id}"
                )

            # Only leader or officers can kick
            if kicker_member.role not in [GuildRole.leader.value, GuildRole.officer.value]:
                raise InvalidOperationError(
                    "kick_member", "Only leaders and officers can kick members"
                )

            # Get target membership
            target_member = await self._member_repo.find_one_where(
                session,
                GuildMember.guild_id == guild_id,
                GuildMember.player_id == target_player_id,
                for_update=True,
            )

            if not target_member:
                raise NotFoundError(
                    f"Player {target_player_id} is not a member of guild {guild_id}"
                )

            # Cannot kick the guild leader
            if guild.owner_id == target_player_id:
                raise InvalidOperationError("kick_member", "Cannot kick the guild leader")

            # Officers cannot kick other officers (only leader can)
            if (
                kicker_member.role == GuildRole.officer.value
                and target_member.role == GuildRole.officer.value
            ):
                raise InvalidOperationError("kick_member", "Officers cannot kick other officers")

            # Soft delete membership
            target_member.deleted_at = datetime.now(timezone.utc)

            # Update guild member count
            guild.member_count -= 1

            # Emit event
            await self.emit_event(
                "guild.member_kicked",
                {
                    "guild_id": guild_id,
                    "guild_name": guild.name,
                    "target_player_id": target_player_id,
                    "kicker_id": kicker_id,
                    "reason": reason,
                    "target_role": target_member.role,
                    "target_contribution": target_member.contribution,
                    "new_member_count": guild.member_count,
                },
            )

            return {
                "guild_id": guild_id,
                "guild_name": guild.name,
                "kicked_player_id": target_player_id,
                "kicked_by": kicker_id,
                "reason": reason,
                "member_count": guild.member_count,
                "kicked_at": target_member.deleted_at,
            }

    async def promote_member(
        self,
        guild_id: int,
        target_player_id: int,
        promoter_id: int,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Promote a guild member (member -> officer).

        Args:
            guild_id: Guild ID
            target_player_id: Discord ID of player to promote
            promoter_id: Discord ID of player performing promotion
            context: Operation context for audit

        Returns:
            Dict with promotion confirmation

        Raises:
            NotFoundError: Guild or membership not found
            InvalidOperationError: Insufficient permissions, already max role
        """
        # Validation
        guild_id = InputValidator.validate_positive_integer(guild_id, "guild_id")
        target_player_id = InputValidator.validate_discord_id(target_player_id)
        promoter_id = InputValidator.validate_discord_id(promoter_id)

        async with DatabaseService.get_transaction() as session:
            # Get guild
            guild = await self._guild_repo.find_one_where(
                session,
                Guild.id == guild_id,
            )

            if not guild:
                raise NotFoundError(f"Guild {guild_id} not found")

            # Only guild leader can promote
            if guild.owner_id != promoter_id:
                raise InvalidOperationError("promote_member", "Only the guild leader can promote members")

            # Get target membership
            target_member = await self._member_repo.find_one_where(
                session,
                GuildMember.guild_id == guild_id,
                GuildMember.player_id == target_player_id,
                for_update=True,
            )

            if not target_member:
                raise NotFoundError(
                    f"Player {target_player_id} is not a member of guild {guild_id}"
                )

            # Determine new role
            old_role = target_member.role
            if old_role == GuildRole.member.value:
                new_role = GuildRole.officer.value
            elif old_role == GuildRole.officer.value:
                raise InvalidOperationError(
                    "promote_member", f"Player {target_player_id} is already an officer (max promotion)"
                )
            else:
                raise InvalidOperationError("promote_member", f"Cannot promote player with role {old_role}")

            # Update role
            target_member.role = new_role

            # Emit event
            await self.emit_event(
                "guild.member_promoted",
                {
                    "guild_id": guild_id,
                    "guild_name": guild.name,
                    "target_player_id": target_player_id,
                    "promoter_id": promoter_id,
                    "old_role": old_role,
                    "new_role": new_role,
                },
            )

            return {
                "guild_id": guild_id,
                "guild_name": guild.name,
                "player_id": target_player_id,
                "old_role": old_role,
                "new_role": new_role,
                "promoted_by": promoter_id,
            }

    async def demote_member(
        self,
        guild_id: int,
        target_player_id: int,
        demoter_id: int,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Demote a guild member (officer -> member).

        Args:
            guild_id: Guild ID
            target_player_id: Discord ID of player to demote
            demoter_id: Discord ID of player performing demotion
            context: Operation context for audit

        Returns:
            Dict with demotion confirmation

        Raises:
            NotFoundError: Guild or membership not found
            InvalidOperationError: Insufficient permissions, already lowest role
        """
        # Validation
        guild_id = InputValidator.validate_positive_integer(guild_id, "guild_id")
        target_player_id = InputValidator.validate_discord_id(target_player_id)
        demoter_id = InputValidator.validate_discord_id(demoter_id)

        async with DatabaseService.get_transaction() as session:
            # Get guild
            guild = await self._guild_repo.find_one_where(
                session,
                Guild.id == guild_id,
            )

            if not guild:
                raise NotFoundError(f"Guild {guild_id} not found")

            # Only guild leader can demote
            if guild.owner_id != demoter_id:
                raise InvalidOperationError("demote_member", "Only the guild leader can demote members")

            # Get target membership
            target_member = await self._member_repo.find_one_where(
                session,
                GuildMember.guild_id == guild_id,
                GuildMember.player_id == target_player_id,
                for_update=True,
            )

            if not target_member:
                raise NotFoundError(
                    f"Player {target_player_id} is not a member of guild {guild_id}"
                )

            # Determine new role
            old_role = target_member.role
            if old_role == GuildRole.officer.value:
                new_role = GuildRole.member.value
            elif old_role == GuildRole.member.value:
                raise InvalidOperationError(
                    "demote_member", f"Player {target_player_id} is already a member (lowest role)"
                )
            else:
                raise InvalidOperationError("demote_member", f"Cannot demote player with role {old_role}")

            # Update role
            target_member.role = new_role

            # Emit event
            await self.emit_event(
                "guild.member_demoted",
                {
                    "guild_id": guild_id,
                    "guild_name": guild.name,
                    "target_player_id": target_player_id,
                    "demoter_id": demoter_id,
                    "old_role": old_role,
                    "new_role": new_role,
                },
            )

            return {
                "guild_id": guild_id,
                "guild_name": guild.name,
                "player_id": target_player_id,
                "old_role": old_role,
                "new_role": new_role,
                "demoted_by": demoter_id,
            }

    async def add_contribution(
        self,
        guild_id: int,
        player_id: int,
        contribution_amount: int,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Add contribution points to a guild member.

        Args:
            guild_id: Guild ID
            player_id: Discord ID of player
            contribution_amount: Contribution to add
            context: Operation context for audit

        Returns:
            Dict with updated contribution

        Raises:
            NotFoundError: Guild or membership not found
        """
        # Validation
        guild_id = InputValidator.validate_positive_integer(guild_id, "guild_id")
        player_id = InputValidator.validate_discord_id(player_id)
        contribution_amount = InputValidator.validate_positive_integer(
            contribution_amount, "contribution_amount"
        )

        async with DatabaseService.get_transaction() as session:
            # Get membership with pessimistic lock
            member = await self._member_repo.find_one_where(
                session,
                GuildMember.guild_id == guild_id,
                GuildMember.player_id == player_id,
                for_update=True,
            )

            if not member:
                raise NotFoundError(
                    f"Player {player_id} is not a member of guild {guild_id}"
                )

            # Update contribution
            old_contribution = member.contribution
            member.contribution += contribution_amount
            new_contribution = member.contribution

            # Emit event
            await self.emit_event(
                "guild.contribution_added",
                {
                    "guild_id": guild_id,
                    "player_id": player_id,
                    "contribution_added": contribution_amount,
                    "old_contribution": old_contribution,
                    "new_contribution": new_contribution,
                },
            )

            return {
                "guild_id": guild_id,
                "player_id": player_id,
                "contribution_added": contribution_amount,
                "total_contribution": new_contribution,
            }

    async def get_member_info(
        self,
        guild_id: int,
        player_id: int,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get guild membership information for a player.

        Args:
            guild_id: Guild ID
            player_id: Discord ID of player
            context: Operation context

        Returns:
            Dict with membership details

        Raises:
            NotFoundError: Membership not found
        """
        # Validation
        guild_id = InputValidator.validate_positive_integer(guild_id, "guild_id")
        player_id = InputValidator.validate_discord_id(player_id)

        async with DatabaseService.get_transaction() as session:
            member = await self._member_repo.find_one_where(
                session,
                GuildMember.guild_id == guild_id,
                GuildMember.player_id == player_id,
            )

            if not member:
                raise NotFoundError(
                    f"Player {player_id} is not a member of guild {guild_id}"
                )

            return {
                "guild_id": guild_id,
                "player_id": player_id,
                "role": member.role,
                "contribution": member.contribution,
                "joined_at": member.created_at,
                "updated_at": member.updated_at,
            }
