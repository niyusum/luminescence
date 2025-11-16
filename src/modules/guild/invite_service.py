"""
GuildInviteService - Business logic for guild invitation management
===================================================================

Handles:
- Creating guild invitations
- Auto-expiration checking
- Revoking invitations
- Accepting invitations (creates membership)
- Duplicate invite prevention
- Maximum pending invite limits

All operations follow LUMEN LAW (2025):
- Pure business logic, no Discord/UI concerns
- Config-driven expiration and limits
- Transaction safety with pessimistic locking
- Event emission for all state changes
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Dict, Optional

from sqlalchemy import and_, func, select

from src.core.database.service import DatabaseService
from src.modules.shared.base_repository import BaseRepository
from src.modules.shared.exceptions import InvalidOperationError, NotFoundError
from src.modules.shared.base_service import BaseService
from src.core.validation.input_validator import InputValidator
from src.database.models.social.guild import Guild
from src.database.models.social.guild_member import GuildMember
from src.database.models.social.guild_invite import GuildInvite
from src.database.models.social.guild_role import GuildRole

if TYPE_CHECKING:
    from logging import Logger
    from src.core.config.manager import ConfigManager
    from src.core.event.bus import EventBus


class GuildInviteService(BaseService):
    """
    GuildInviteService handles guild invitation operations.

    Business Logic:
    - Members with invite permission can create invites
    - Invites auto-expire after configured duration
    - Cannot invite players already in guild
    - Cannot invite if guild is full
    - Max pending invites per guild/player enforced
    - Accepting invite creates membership
    - Duplicate invites prevented
    """

    def __init__(
        self,
        config_manager: ConfigManager,
        event_bus: EventBus,
        logger: Logger,
    ):
        """Initialize GuildInviteService."""
        super().__init__(config_manager, event_bus, logger)
        self._guild_repo = BaseRepository[Guild](Guild, self.log)
        self._member_repo = BaseRepository[GuildMember](GuildMember, self.log)
        self._invite_repo = BaseRepository[GuildInvite](GuildInvite, self.log)

    # -------------------------------------------------------------------------
    # Core Operations
    # -------------------------------------------------------------------------

    async def create_invite(
        self,
        guild_id: int,
        inviter_id: int,
        target_player_id: int,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a guild invitation.

        Args:
            guild_id: Guild ID
            inviter_id: Discord ID of inviter
            target_player_id: Discord ID of target player
            context: Operation context for audit

        Returns:
            Dict with invite details

        Raises:
            NotFoundError: Guild or inviter membership not found
            InvalidOperationError: Various validation failures
        """
        # Validation
        guild_id = InputValidator.validate_positive_integer(guild_id, "guild_id")
        inviter_id = InputValidator.validate_discord_id(inviter_id)
        target_player_id = InputValidator.validate_discord_id(target_player_id)

        # Cannot invite self
        if inviter_id == target_player_id:
            raise InvalidOperationError("create_invite", "Cannot invite yourself to a guild")

        async with DatabaseService.get_transaction() as session:
            # Get guild with pessimistic lock
            guild = await self._guild_repo.find_one_where(
                session,
                Guild.id == guild_id,
                for_update=True,
            )

            if not guild:
                raise NotFoundError(f"Guild {guild_id} not found")

            # Check if guild is recruiting (from meta field)
            is_recruiting = guild.meta.get("is_recruiting", True) if guild.meta else True
            if not is_recruiting:
                raise InvalidOperationError(
                    "create_invite", f"Guild {guild.name} is not currently recruiting"
                )

            # Get inviter membership (verify permission)
            inviter_member = await self._member_repo.find_one_where(
                session,
                GuildMember.guild_id == guild_id,
                GuildMember.player_id == inviter_id,
            )

            if not inviter_member:
                raise InvalidOperationError(
                    "create_invite", f"Player {inviter_id} is not a member of guild {guild_id}"
                )

            # Only leader and officers can invite (configurable)
            can_invite_roles = self.get_config(
                "guilds.invite_roles",
                default=[GuildRole.leader.value, GuildRole.officer.value],
            )
            if inviter_member.role not in can_invite_roles:
                raise InvalidOperationError(
                    "create_invite", f"Only {', '.join(can_invite_roles)} can invite members"
                )

            # Check if target is already a member
            existing_member = await self._member_repo.find_one_where(
                session,
                GuildMember.guild_id == guild_id,
                GuildMember.player_id == target_player_id,
            )

            if existing_member:
                raise InvalidOperationError(
                    "create_invite", f"Player {target_player_id} is already a member of this guild"
                )

            # Check guild capacity
            if guild.member_count >= guild.max_members:
                raise InvalidOperationError(
                    "create_invite", f"Guild is full ({guild.member_count}/{guild.max_members})"
                )

            # Check for existing active invite
            now = datetime.now(timezone.utc)
            existing_invite = await self._invite_repo.find_one_where(
                session,
                GuildInvite.guild_id == guild_id,
                GuildInvite.target_player_id == target_player_id,
                GuildInvite.expires_at > now,
                GuildInvite.deleted_at.is_(None),
            )

            if existing_invite:
                raise InvalidOperationError(
                    "create_invite", f"An active invite already exists for player {target_player_id}"
                )

            # Check max pending invites for guild
            max_pending_invites = self.get_config(
                "guilds.max_pending_invites_per_guild", default=50
            )
            pending_invite_count = await session.scalar(
                select(func.count(GuildInvite.id)).where(
                    and_(
                        GuildInvite.guild_id == guild_id,
                        GuildInvite.expires_at > now,
                        GuildInvite.deleted_at.is_(None),
                    )
                )
            )

            if pending_invite_count >= max_pending_invites:
                raise InvalidOperationError(
                    "create_invite", f"Guild has too many pending invites ({pending_invite_count}/{max_pending_invites})"
                )

            # Check max pending invites for target player
            max_pending_invites_per_player = self.get_config(
                "guilds.max_pending_invites_per_player", default=10
            )
            player_invite_count = await session.scalar(
                select(func.count(GuildInvite.id)).where(
                    and_(
                        GuildInvite.target_player_id == target_player_id,
                        GuildInvite.expires_at > now,
                        GuildInvite.deleted_at.is_(None),
                    )
                )
            )

            if player_invite_count >= max_pending_invites_per_player:
                raise InvalidOperationError(
                    "create_invite", f"Player {target_player_id} has too many pending invites"
                )

            # Create invite
            invite_duration_days = self.get_config("guilds.invite_duration_days", default=3)
            expires_at = now + timedelta(days=invite_duration_days)

            invite = GuildInvite(
                guild_id=guild_id,
                inviter_player_id=inviter_id,
                target_player_id=target_player_id,
                expires_at=expires_at,
            )

            session.add(invite)
            await session.flush()

            # Emit event
            await self.emit_event(
                "guild.invite_created",
                {
                    "invite_id": invite.id,
                    "guild_id": guild_id,
                    "guild_name": guild.name,
                    "inviter_id": inviter_id,
                    "target_player_id": target_player_id,
                    "expires_at": expires_at.isoformat(),
                },
            )

            return {
                "invite_id": invite.id,
                "guild_id": guild_id,
                "guild_name": guild.name,
                "inviter_id": inviter_id,
                "target_player_id": target_player_id,
                "expires_at": expires_at,
                "created_at": invite.created_at,
            }

    async def revoke_invite(
        self,
        invite_id: int,
        revoker_id: int,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Revoke a guild invitation.

        Args:
            invite_id: Invite ID
            revoker_id: Discord ID of player revoking
            context: Operation context for audit

        Returns:
            Dict with revocation confirmation

        Raises:
            NotFoundError: Invite not found
            InvalidOperationError: Insufficient permissions
        """
        # Validation
        invite_id = InputValidator.validate_positive_integer(invite_id, "invite_id")
        revoker_id = InputValidator.validate_discord_id(revoker_id)

        async with DatabaseService.get_transaction() as session:
            # Get invite with pessimistic lock
            invite = await self._invite_repo.find_one_where(
                session,
                GuildInvite.id == invite_id,
                for_update=True,
            )

            if not invite:
                raise NotFoundError(f"Invite {invite_id} not found")

            # Check if already revoked
            if invite.deleted_at is not None:
                raise InvalidOperationError("revoke_invite", "Invite has already been revoked")

            # Get revoker membership (verify permission)
            revoker_member = await self._member_repo.find_one_where(
                session,
                GuildMember.guild_id == invite.guild_id,
                GuildMember.player_id == revoker_id,
            )

            # Only inviter, leader, or officers can revoke
            can_revoke = (
                revoker_id == invite.inviter_player_id
                or (
                    revoker_member is not None
                    and revoker_member.role
                    in [GuildRole.leader.value, GuildRole.officer.value]
                )
            )

            if not can_revoke:
                raise InvalidOperationError(
                    "revoke_invite", "Only the inviter, leader, or officers can revoke invites"
                )

            # Soft delete invite
            invite.deleted_at = datetime.now(timezone.utc)

            # Emit event
            await self.emit_event(
                "guild.invite_revoked",
                {
                    "invite_id": invite_id,
                    "guild_id": invite.guild_id,
                    "revoker_id": revoker_id,
                    "target_player_id": invite.target_player_id,
                },
            )

            return {
                "invite_id": invite_id,
                "guild_id": invite.guild_id,
                "target_player_id": invite.target_player_id,
                "revoked_by": revoker_id,
                "revoked_at": invite.deleted_at,
            }

    async def accept_invite(
        self,
        invite_id: int,
        accepting_player_id: int,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Accept a guild invitation (creates membership).

        Args:
            invite_id: Invite ID
            accepting_player_id: Discord ID of player accepting
            context: Operation context for audit

        Returns:
            Dict with membership details

        Raises:
            NotFoundError: Invite not found
            InvalidOperationError: Expired, wrong target, guild full
        """
        # Validation
        invite_id = InputValidator.validate_positive_integer(invite_id, "invite_id")
        accepting_player_id = InputValidator.validate_discord_id(accepting_player_id)

        async with DatabaseService.get_transaction() as session:
            # Get invite with pessimistic lock
            invite = await self._invite_repo.find_one_where(
                session,
                GuildInvite.id == invite_id,
                for_update=True,
            )

            if not invite:
                raise NotFoundError(f"Invite {invite_id} not found")

            # Check if already used/revoked
            if invite.deleted_at is not None:
                raise InvalidOperationError("accept_invite", "Invite has been revoked")

            # Check expiration
            now = datetime.now(timezone.utc)
            if invite.expires_at < now:
                raise InvalidOperationError("accept_invite", "Invite has expired")

            # Verify target player
            if invite.target_player_id != accepting_player_id:
                raise InvalidOperationError(
                    "accept_invite", f"This invite is for player {invite.target_player_id}, not {accepting_player_id}"
                )

            # Get guild with pessimistic lock
            guild = await self._guild_repo.find_one_where(
                session,
                Guild.id == invite.guild_id,
                for_update=True,
            )

            if not guild:
                raise NotFoundError(f"Guild {invite.guild_id} not found")

            # Check if player is already a member
            existing_member = await self._member_repo.find_one_where(
                session,
                GuildMember.guild_id == guild.id,
                GuildMember.player_id == accepting_player_id,
            )

            if existing_member:
                raise InvalidOperationError("accept_invite", "You are already a member of this guild")

            # Check guild capacity
            if guild.member_count >= guild.max_members:
                raise InvalidOperationError(
                    "accept_invite", f"Guild is full ({guild.member_count}/{guild.max_members})"
                )

            # Create membership
            member = GuildMember(
                guild_id=guild.id,
                player_id=accepting_player_id,
                role=GuildRole.member.value,
                contribution=0,
            )

            session.add(member)

            # Update guild member count
            guild.member_count += 1

            # Mark invite as used (soft delete)
            invite.deleted_at = datetime.now(timezone.utc)

            await session.flush()

            # Emit event
            await self.emit_event(
                "guild.invite_accepted",
                {
                    "invite_id": invite_id,
                    "guild_id": guild.id,
                    "guild_name": guild.name,
                    "player_id": accepting_player_id,
                    "inviter_id": invite.inviter_player_id,
                    "new_member_count": guild.member_count,
                },
            )

            return {
                "guild_id": guild.id,
                "guild_name": guild.name,
                "player_id": accepting_player_id,
                "role": member.role,
                "inviter_id": invite.inviter_player_id,
                "member_count": guild.member_count,
                "joined_at": member.created_at,
            }

    async def cleanup_expired_invites(
        self,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Cleanup expired guild invites (soft delete).

        Args:
            context: Operation context

        Returns:
            Dict with cleanup stats

        Raises:
            None
        """
        async with DatabaseService.get_transaction() as session:
            now = datetime.now(timezone.utc)

            # Find expired invites
            expired_invites = await self._invite_repo.find_many_where(
                session,
                GuildInvite.expires_at < now,
                GuildInvite.deleted_at.is_(None),
            )

            # Soft delete expired invites
            count = 0
            for invite in expired_invites:
                invite.deleted_at = now
                count += 1

            # Emit event
            if count > 0:
                await self.emit_event(
                    "guild.invites_cleaned_up",
                    {
                        "expired_count": count,
                        "cleaned_at": now.isoformat(),
                    },
                )

            return {
                "expired_count": count,
                "cleaned_at": now,
            }

    async def get_pending_invites_for_guild(
        self,
        guild_id: int,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get all pending invites for a guild.

        Args:
            guild_id: Guild ID
            context: Operation context

        Returns:
            Dict with invite list

        Raises:
            NotFoundError: Guild not found
        """
        # Validation
        guild_id = InputValidator.validate_positive_integer(guild_id, "guild_id")

        async with DatabaseService.get_transaction() as session:
            # Verify guild exists
            guild = await self._guild_repo.find_one_where(
                session,
                Guild.id == guild_id,
            )

            if not guild:
                raise NotFoundError(f"Guild {guild_id} not found")

            # Get pending invites
            now = datetime.now(timezone.utc)
            invites = await self._invite_repo.find_many_where(
                session,
                GuildInvite.guild_id == guild_id,
                GuildInvite.expires_at > now,
                GuildInvite.deleted_at.is_(None),
            )

            invite_list = [
                {
                    "invite_id": inv.id,
                    "inviter_id": inv.inviter_player_id,
                    "target_player_id": inv.target_player_id,
                    "expires_at": inv.expires_at,
                    "created_at": inv.created_at,
                }
                for inv in invites
            ]

            return {
                "guild_id": guild_id,
                "guild_name": guild.name,
                "pending_invites": invite_list,
                "count": len(invite_list),
            }

    async def get_pending_invites_for_player(
        self,
        player_id: int,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get all pending invites for a player.

        Args:
            player_id: Discord ID of player
            context: Operation context

        Returns:
            Dict with invite list

        Raises:
            None
        """
        # Validation
        player_id = InputValidator.validate_discord_id(player_id)

        async with DatabaseService.get_transaction() as session:
            # Get pending invites
            now = datetime.now(timezone.utc)
            invites = await self._invite_repo.find_many_where(
                session,
                GuildInvite.target_player_id == player_id,
                GuildInvite.expires_at > now,
                GuildInvite.deleted_at.is_(None),
            )

            # Fetch guild names
            invite_list = []
            for inv in invites:
                guild = await self._guild_repo.find_one_where(
                    session,
                    Guild.id == inv.guild_id,
                )

                invite_list.append(
                    {
                        "invite_id": inv.id,
                        "guild_id": inv.guild_id,
                        "guild_name": guild.name if guild else "Unknown",
                        "inviter_id": inv.inviter_player_id,
                        "expires_at": inv.expires_at,
                        "created_at": inv.created_at,
                    }
                )

            return {
                "player_id": player_id,
                "pending_invites": invite_list,
                "count": len(invite_list),
            }
