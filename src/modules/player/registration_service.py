"""
Player Registration Service - LES 2025 Compliant
================================================

Purpose
-------
Orchestrates atomic creation of all player component records during new player
registration, ensuring data consistency across the decomposed player model.

Domain
------
- Atomic player registration across all 5 component tables
- Default value initialization from config
- First-time player onboarding
- Player component lifecycle management

LUMEN 2025 COMPLIANCE
---------------------
✓ Pure business logic - no Discord dependencies
✓ Transaction-safe - all writes in single atomic transaction
✓ Config-driven - default values from ConfigManager
✓ Domain exceptions - raises ValidationError, BusinessRuleViolation
✓ Event-driven - emits player.registered event
✓ Observable - structured logging, audit trail
✓ Orchestration pattern - coordinates multiple services

Dependencies
------------
- ConfigManager: For default starting values
- EventBus: For emitting player.registered event
- Logger: For structured logging
- DatabaseService: For transaction management
- AuditLogger: For registration audit trail
- PlayerCoreService: Creates PlayerCore record
- PlayerProgressionService: Creates PlayerProgression record
- PlayerStatsService: Creates PlayerStats record
- PlayerCurrenciesService: Creates PlayerCurrencies record
- PlayerActivityService: Creates PlayerActivity record
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional

from src.core.database.service import DatabaseService
from src.core.infra.audit_logger import AuditLogger
from src.core.logging.logger import get_logger
from src.core.validation.input_validator import InputValidator
from src.modules.shared.base_service import BaseService
from src.modules.shared.exceptions import (
    InvalidOperationError,
    ValidationError,
)

if TYPE_CHECKING:
    from logging import Logger

    from src.core.config.manager import ConfigManager
    from src.core.event.bus import EventBus
    from src.database.models.core.player.player_activity import PlayerActivity
    from src.database.models.core.player.player_core import PlayerCore
    from src.database.models.core.player.player_currencies import PlayerCurrencies
    from src.database.models.core.player.player_progression import (
        PlayerProgression,
    )
    from src.database.models.core.player.player_stats import PlayerStats


# ============================================================================
# PlayerRegistrationService
# ============================================================================


class PlayerRegistrationService(BaseService):
    """
    Service for orchestrating atomic player registration.

    This service coordinates the creation of all 5 player component records
    (PlayerCore, PlayerProgression, PlayerStats, PlayerCurrencies, PlayerActivity)
    in a single atomic transaction, ensuring complete player state initialization.

    Dependencies
    ------------
    - ConfigManager: For default starting values
    - EventBus: For emitting player.registered event
    - Logger: For structured logging
    - DatabaseService: For transaction management (injected via context)
    - AuditLogger: For audit trail (static)

    Public Methods
    --------------
    - register_player() -> Create all 5 player component records atomically
    - player_exists() -> Check if player is already registered
    """

    def __init__(
        self,
        config_manager: ConfigManager,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        """
        Initialize PlayerRegistrationService with required dependencies.

        Args:
            config_manager: Application configuration manager
            event_bus: Event bus for cross-module communication
            logger: Structured logger instance
        """
        super().__init__(config_manager, event_bus, logger)

        # Import models for direct repository creation
        from src.database.models.core.player.player_activity import PlayerActivity
        from src.database.models.core.player.player_core import PlayerCore
        from src.database.models.core.player.player_currencies import (
            PlayerCurrencies,
        )
        from src.database.models.core.player.player_progression import (
            PlayerProgression,
        )
        from src.database.models.core.player.player_stats import PlayerStats
        from src.modules.shared.base_repository import BaseRepository

        # Initialize repositories for direct database access
        # We use repositories directly instead of services to avoid nested transactions
        self._core_repo = BaseRepository[PlayerCore](
            model_class=PlayerCore,
            logger=get_logger(f"{__name__}.PlayerCoreRepository"),
        )
        self._progression_repo = BaseRepository[PlayerProgression](
            model_class=PlayerProgression,
            logger=get_logger(f"{__name__}.PlayerProgressionRepository"),
        )
        self._stats_repo = BaseRepository[PlayerStats](
            model_class=PlayerStats,
            logger=get_logger(f"{__name__}.PlayerStatsRepository"),
        )
        self._currencies_repo = BaseRepository[PlayerCurrencies](
            model_class=PlayerCurrencies,
            logger=get_logger(f"{__name__}.PlayerCurrenciesRepository"),
        )
        self._activity_repo = BaseRepository[PlayerActivity](
            model_class=PlayerActivity,
            logger=get_logger(f"{__name__}.PlayerActivityRepository"),
        )

    # ========================================================================
    # PUBLIC API - Read Operations
    # ========================================================================

    async def player_exists(self, discord_id: int) -> bool:
        """
        Check if a player is already registered.

        This is a **read-only** operation using get_session().

        Args:
            discord_id: Discord ID to check

        Returns:
            True if player exists, False otherwise

        Example:
            >>> exists = await service.player_exists(123456789)
            >>> if not exists:
            ...     await service.register_player(123456789, "PlayerName")
        """
        discord_id = InputValidator.validate_discord_id(discord_id)

        self.log_operation("player_exists", discord_id=discord_id)

        async with DatabaseService.get_session() as session:
            from src.database.models.core.player.player_core import PlayerCore

            player = await self._core_repo.find_one_where(
                session,
                PlayerCore.discord_id == discord_id,
            )
            return player is not None

    # ========================================================================
    # PUBLIC API - Write Operations
    # ========================================================================

    async def register_player(
        self,
        discord_id: int,
        username: str,
        discriminator: Optional[str] = None,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Register a new player by creating all 5 component records atomically.

        This is a **write operation** using get_transaction() to ensure all
        component records are created in a single atomic transaction.

        Creates:
        - PlayerCore: identity, leader_maiden_id, collection_metadata
        - PlayerProgression: xp, level, class, milestones, fusion/gacha tracking
        - PlayerStats: energy, stamina, hp, drop_charges, combat stats
        - PlayerCurrencies: lumees, lumenite, auric_coin, fusion_shards
        - PlayerActivity: last_seen, daily_counters, cooldowns

        Args:
            discord_id: Discord ID of the new player
            username: Discord username
            discriminator: Discord discriminator (optional)
            context: Optional command/system context

        Returns:
            Dict containing all created component records:
                - player_core: PlayerCore record dict
                - player_progression: PlayerProgression record dict
                - player_stats: PlayerStats record dict
                - player_currencies: PlayerCurrencies record dict
                - player_activity: PlayerActivity record dict
                - registration_timestamp: When registration occurred

        Raises:
            ValidationError: If discord_id or username is invalid
            BusinessRuleViolation: If player already exists

        Example:
            >>> result = await service.register_player(
            ...     discord_id=123456789,
            ...     username="NewPlayer",
            ...     discriminator="1234",
            ...     context="/start"
            ... )
            >>> print(result["player_core"]["discord_id"])
            123456789
        """
        # Step 1: Validate all inputs
        discord_id = InputValidator.validate_discord_id(discord_id)
        username = InputValidator.validate_string(
            username, field_name="username", min_length=1, max_length=100
        )
        if discriminator is not None:
            discriminator = InputValidator.validate_string(
                discriminator,
                field_name="discriminator",
                min_length=1,
                max_length=10,
            )

        # Step 2: Log operation start
        self.log_operation(
            "register_player",
            discord_id=discord_id,
            username=username,
        )

        # Step 3: Get default values from config
        starting_lumees = self.get_config("starting_lumees", default=0)
        starting_lumenite = self.get_config("starting_lumenite", default=0)
        starting_auric_coin = self.get_config("starting_auric_coin", default=0)
        starting_level = self.get_config("starting_level", default=1)
        starting_energy = self.get_config("stat_allocation.base_energy", default=100)
        starting_stamina = self.get_config(
            "stat_allocation.base_stamina", default=100
        )
        starting_hp = self.get_config("stat_allocation.base_hp", default=100)
        starting_drop_charges = self.get_config(
            "drop_charges.initial_charges", default=10
        )

        # Step 4: Atomic transaction - create all 5 component records
        async with DatabaseService.get_transaction() as session:
            from datetime import datetime, timezone

            from src.database.models.core.player.player_activity import (
                PlayerActivity,
            )
            from src.database.models.core.player.player_core import PlayerCore
            from src.database.models.core.player.player_currencies import (
                PlayerCurrencies,
            )
            from src.database.models.core.player.player_progression import (
                PlayerProgression,
            )
            from src.database.models.core.player.player_stats import PlayerStats

            # Check if player already exists
            existing_player = await self._core_repo.find_one_where(
                session,
                PlayerCore.discord_id == discord_id,
            )
            if existing_player:
                raise InvalidOperationError(
                    action="register_player",
                    reason=f"Player with discord_id {discord_id} is already registered"
                )

            registration_time = datetime.now(timezone.utc)

            # Create PlayerCore
            player_core = PlayerCore(
                discord_id=discord_id,
                username=username,
                discriminator=discriminator,
                leader_maiden_id=None,
                total_maidens_owned=0,
                unique_maidens=0,
            )
            session.add(player_core)
            await session.flush()  # Get player_core.discord_id for foreign keys

            # Create PlayerProgression
            player_progression = PlayerProgression(
                player_id=player_core.discord_id,
                xp=0,
                level=starting_level,
                class_name=None,
                total_fusions=0,
                successful_fusions=0,
                failed_fusions=0,
                total_summons=0,
                pity_counter=0,
                tutorial_completed=False,
                tutorial_step=0,
            )
            session.add(player_progression)

            # Create PlayerStats
            player_stats = PlayerStats(
                player_id=player_core.discord_id,
                energy=starting_energy,
                max_energy=starting_energy,
                stamina=starting_stamina,
                max_stamina=starting_stamina,
                hp=starting_hp,
                max_hp=starting_hp,
                drop_charges=starting_drop_charges,
                max_drop_charges=1,
                last_drop_regen=registration_time,
                total_attack=0,
                total_defense=0,
                total_power=0,
                stat_points_spent={
                    "energy": 0,
                    "stamina": 0,
                    "hp": 0,
                },
            )
            session.add(player_stats)

            # Create PlayerCurrencies
            player_currencies = PlayerCurrencies(
                player_id=player_core.discord_id,
                lumees=starting_lumees,
                lumenite=starting_lumenite,
                auric_coin=starting_auric_coin,
                shards={
                    "tier_1": 0,
                    "tier_2": 0,
                    "tier_3": 0,
                    "tier_4": 0,
                    "tier_5": 0,
                    "tier_6": 0,
                    "tier_7": 0,
                    "tier_8": 0,
                    "tier_9": 0,
                    "tier_10": 0,
                    "tier_11": 0,
                },
            )
            session.add(player_currencies)

            # Create PlayerActivity
            player_activity = PlayerActivity(
                player_id=player_core.discord_id,
                last_active=registration_time,
            )
            session.add(player_activity)

            # Step 5: Audit logging
            await AuditLogger.log(
                player_id=player_core.discord_id,
                transaction_type="player_registration",
                details={
                    "discord_id": discord_id,
                    "username": username,
                    "discriminator": discriminator,
                    "starting_lumees": starting_lumees,
                    "starting_lumenite": starting_lumenite,
                    "starting_auric_coin": starting_auric_coin,
                    "starting_level": starting_level,
                },
                context=context,
            )

            # Step 6: Event emission
            await self.emit_event(
                event_type="player.registered",
                data={
                    "player_id": player_core.discord_id,
                    "discord_id": discord_id,
                    "username": username,
                    "starting_level": starting_level,
                    "registration_timestamp": registration_time.isoformat(),
                },
            )

            # Step 7: Structured logging
            self.log.info(
                f"Player registered successfully: {username} (discord_id={discord_id})",
                extra={
                    "player_id": player_core.discord_id,
                    "discord_id": discord_id,
                    "username": username,
                    "starting_lumees": starting_lumees,
                    "starting_level": starting_level,
                },
            )

            # Step 8: Return results
            # Transaction auto-commits on exit
            return {
                "player_core": {
                    "discord_id": player_core.discord_id,
                    "username": player_core.username,
                    "discriminator": player_core.discriminator,
                    "leader_maiden_id": player_core.leader_maiden_id,
                    "total_maidens_owned": player_core.total_maidens_owned,
                    "unique_maidens": player_core.unique_maidens,
                },
                "player_progression": {
                    "player_id": player_progression.player_id,
                    "xp": player_progression.xp,
                    "level": player_progression.level,
                    "class_name": player_progression.class_name,
                },
                "player_stats": {
                    "player_id": player_stats.player_id,
                    "energy": player_stats.energy,
                    "max_energy": player_stats.max_energy,
                    "stamina": player_stats.stamina,
                    "max_stamina": player_stats.max_stamina,
                    "hp": player_stats.hp,
                    "max_hp": player_stats.max_hp,
                    "drop_charges": player_stats.drop_charges,
                },
                "player_currencies": {
                    "player_id": player_currencies.player_id,
                    "lumees": player_currencies.lumees,
                    "lumenite": player_currencies.lumenite,
                    "auric_coin": player_currencies.auric_coin,
                },
                "player_activity": {
                    "player_id": player_activity.player_id,
                    "last_active": player_activity.last_active.isoformat(),
                },
                "registration_timestamp": registration_time.isoformat(),
            }
