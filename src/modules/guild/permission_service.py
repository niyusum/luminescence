"""
GuildPermissionService - Business logic for guild permission management
=======================================================================

Handles:
- Permission checking for guild actions
- Role-based access control (leader, officer, member)
- Config-driven permission trees
- Action gating and validation

All operations follow LUMEN LAW (2025):
- Pure business logic, no Discord/UI concerns
- Config-driven permission definitions
- Transaction safety with pessimistic locking
- Event emission for all state changes
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

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


class GuildPermissionService(BaseService):
    """
    GuildPermissionService handles guild permission checks.

    Business Logic:
    - Leaders have all permissions
    - Officers have subset of permissions (invite, kick members, etc.)
    - Members have basic permissions (view, leave, contribute)
    - Permissions are config-driven for easy tuning
    - Permission checks verify membership and role
    """

    def __init__(
        self,
        config_manager: ConfigManager,
        event_bus: EventBus,
        logger: Logger,
    ):
        """Initialize GuildPermissionService."""
        super().__init__(config_manager, event_bus, logger)
        self._guild_repo = BaseRepository[Guild](Guild, self.log)
        self._member_repo = BaseRepository[GuildMember](GuildMember, self.log)

    # -------------------------------------------------------------------------
    # Permission Constants (can be overridden by config)
    # -------------------------------------------------------------------------

    DEFAULT_PERMISSIONS = {
        GuildRole.leader.value: [
            "disband",
            "rename",
            "change_emblem",
            "upgrade",
            "invite",
            "kick",
            "promote",
            "demote",
            "manage_shrine",
            "withdraw_treasury",
            "deposit_treasury",
            "view_audit",
            "manage_recruiting",
        ],
        GuildRole.officer.value: [
            "invite",
            "kick",  # Can only kick members, not other officers
            "manage_shrine",
            "deposit_treasury",
            "view_audit",
        ],
        GuildRole.member.value: [
            "leave",
            "deposit_treasury",
            "view_info",
        ],
    }

    # -------------------------------------------------------------------------
    # Core Operations
    # -------------------------------------------------------------------------

    async def check_permission(
        self,
        guild_id: int,
        player_id: int,
        action: str,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Check if a player has permission to perform an action.

        Args:
            guild_id: Guild ID
            player_id: Discord ID of player
            action: Action to check (e.g., "kick", "invite", "upgrade")
            context: Operation context

        Returns:
            Dict with permission result

        Raises:
            NotFoundError: Guild or membership not found
        """
        # Validation
        guild_id = InputValidator.validate_positive_integer(guild_id, "guild_id")
        player_id = InputValidator.validate_discord_id(player_id)
        action = InputValidator.validate_string(action, "action", min_length=1, max_length=50)

        async with DatabaseService.get_transaction() as session:
            # Get guild
            guild = await self._guild_repo.find_one_where(
                session,
                Guild.id == guild_id,
            )

            if not guild:
                raise NotFoundError(f"Guild {guild_id} not found")

            # Get player membership
            member = await self._member_repo.find_one_where(
                session,
                GuildMember.guild_id == guild_id,
                GuildMember.player_id == player_id,
            )

            if not member:
                raise NotFoundError(
                    f"Player {player_id} is not a member of guild {guild_id}"
                )

            # Get permission tree for role
            permissions = self._get_permissions_for_role(member.role)

            # Check if action is permitted
            has_permission = action in permissions

            return {
                "guild_id": guild_id,
                "player_id": player_id,
                "action": action,
                "role": member.role,
                "has_permission": has_permission,
            }

    async def require_permission(
        self,
        guild_id: int,
        player_id: int,
        action: str,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Require a player to have permission (raises exception if not).

        Args:
            guild_id: Guild ID
            player_id: Discord ID of player
            action: Action to check
            context: Operation context

        Returns:
            Dict with permission confirmation

        Raises:
            NotFoundError: Guild or membership not found
            InvalidOperationError: Permission denied
        """
        result = await self.check_permission(
            guild_id=guild_id,
            player_id=player_id,
            action=action,
            context=context,
        )

        if not result["has_permission"]:
            raise InvalidOperationError(
                "require_permission",
                f"Player {player_id} does not have permission to '{action}' (role: {result['role']})"
            )

        return result

    async def get_player_permissions(
        self,
        guild_id: int,
        player_id: int,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get all permissions for a player in a guild.

        Args:
            guild_id: Guild ID
            player_id: Discord ID of player
            context: Operation context

        Returns:
            Dict with permission list

        Raises:
            NotFoundError: Guild or membership not found
        """
        # Validation
        guild_id = InputValidator.validate_positive_integer(guild_id, "guild_id")
        player_id = InputValidator.validate_discord_id(player_id)

        async with DatabaseService.get_transaction() as session:
            # Get guild
            guild = await self._guild_repo.find_one_where(
                session,
                Guild.id == guild_id,
            )

            if not guild:
                raise NotFoundError(f"Guild {guild_id} not found")

            # Get player membership
            member = await self._member_repo.find_one_where(
                session,
                GuildMember.guild_id == guild_id,
                GuildMember.player_id == player_id,
            )

            if not member:
                raise NotFoundError(
                    f"Player {player_id} is not a member of guild {guild_id}"
                )

            # Get all permissions for role
            permissions = self._get_permissions_for_role(member.role)

            return {
                "guild_id": guild_id,
                "player_id": player_id,
                "role": member.role,
                "permissions": permissions,
            }

    async def get_role_permissions(
        self,
        role: str,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get all permissions for a specific role.

        Args:
            role: Role name (leader, officer, member)
            context: Operation context

        Returns:
            Dict with permission list

        Raises:
            InvalidOperationError: Invalid role
        """
        # Validate role
        valid_roles = [r.value for r in GuildRole]
        if role not in valid_roles:
            raise InvalidOperationError(
                "get_role_permissions",
                f"Invalid role '{role}'. Valid roles: {', '.join(valid_roles)}"
            )

        # Get permissions for role
        permissions = self._get_permissions_for_role(role)

        return {
            "role": role,
            "permissions": permissions,
        }

    async def can_manage_member(
        self,
        guild_id: int,
        actor_id: int,
        target_id: int,
        action: str,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Check if a player can manage another member (kick, promote, demote).

        Args:
            guild_id: Guild ID
            actor_id: Discord ID of player performing action
            target_id: Discord ID of target player
            action: Action to perform (kick, promote, demote)
            context: Operation context

        Returns:
            Dict with permission result

        Raises:
            NotFoundError: Guild or membership not found
            InvalidOperationError: Permission denied
        """
        # Validation
        guild_id = InputValidator.validate_positive_integer(guild_id, "guild_id")
        actor_id = InputValidator.validate_discord_id(actor_id)
        target_id = InputValidator.validate_discord_id(target_id)

        async with DatabaseService.get_transaction() as session:
            # Get guild
            guild = await self._guild_repo.find_one_where(
                session,
                Guild.id == guild_id,
            )

            if not guild:
                raise NotFoundError(f"Guild {guild_id} not found")

            # Get actor membership
            actor_member = await self._member_repo.find_one_where(
                session,
                GuildMember.guild_id == guild_id,
                GuildMember.player_id == actor_id,
            )

            if not actor_member:
                raise NotFoundError(
                    f"Player {actor_id} is not a member of guild {guild_id}"
                )

            # Get target membership
            target_member = await self._member_repo.find_one_where(
                session,
                GuildMember.guild_id == guild_id,
                GuildMember.player_id == target_id,
            )

            if not target_member:
                raise NotFoundError(
                    f"Player {target_id} is not a member of guild {guild_id}"
                )

            # Check basic permission
            actor_permissions = self._get_permissions_for_role(actor_member.role)
            if action not in actor_permissions:
                raise InvalidOperationError(
                    "can_manage_member",
                    f"Player {actor_id} does not have permission to '{action}'"
                )

            # Additional checks for member management
            can_manage = True
            reason = None

            # Cannot manage guild leader
            if guild.owner_id == target_id:
                can_manage = False
                reason = "Cannot manage the guild leader"

            # Officers cannot manage other officers
            elif (
                actor_member.role == GuildRole.officer.value
                and target_member.role == GuildRole.officer.value
            ):
                can_manage = False
                reason = "Officers cannot manage other officers"

            # Promote/demote only for leader
            elif action in ["promote", "demote"] and actor_member.role != GuildRole.leader.value:
                can_manage = False
                reason = "Only the guild leader can promote or demote members"

            if not can_manage:
                assert reason is not None  # Type narrowing: reason is always set when can_manage is False
                raise InvalidOperationError("can_manage_member", reason)

            return {
                "guild_id": guild_id,
                "actor_id": actor_id,
                "target_id": target_id,
                "action": action,
                "can_manage": True,
                "actor_role": actor_member.role,
                "target_role": target_member.role,
            }

    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------

    def _get_permissions_for_role(self, role: str) -> List[str]:
        """
        Get permission list for a role.

        Args:
            role: Role name

        Returns:
            List of permitted actions
        """
        # Try to get from config first
        config_permissions = self.get_config(
            f"guilds.permissions.{role}",
            default=None,
        )

        if config_permissions is not None:
            return config_permissions

        # Fall back to defaults
        return self.DEFAULT_PERMISSIONS.get(role, [])
