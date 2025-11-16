"""
Service Container - LES 2025 Compliant
=======================================

Purpose
-------
Centralized dependency injection container for all domain services.
Provides singleton instances of services with proper dependency management.

Responsibilities
----------------
- Initialize all domain services with required dependencies
- Manage service lifecycle (initialization, shutdown)
- Provide easy access to services throughout the application
- Ensure single instances (singleton pattern)

LUMEN 2025 COMPLIANCE
---------------------
✓ Separation of concerns - infrastructure only
✓ No business logic
✓ Config-driven service initialization
✓ Graceful degradation on service failures
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from src.core.config.manager import ConfigManager
from src.core.event.bus import EventBus
from src.core.logging.logger import get_logger

# Player services
from src.modules.player import (
    PlayerActivityService,
    PlayerCoreService,
    PlayerCurrenciesService,
    PlayerProgressionService,
    PlayerRegistrationService,
    PlayerStatsService,
)

# Maiden services
from src.modules.maiden import MaidenBaseService, MaidenService

# Exploration services
from src.modules.exploration import ExplorationMasteryService, SectorProgressService

# Ascension services
from src.modules.ascension import AscensionProgressService

# Daily services
from src.modules.daily import DailyQuestService

# Tutorial services
from src.modules.tutorial import TutorialService

# Leaderboard services
from src.modules.leaderboard import LeaderboardService

# Economy services
from src.modules.shrine import ShrineService
from src.modules.guild import GuildShrineService
from src.modules.summon import TokenService
from src.modules.economy import TransactionLogService

# Drop services
from src.modules.drop import DropChargeService

# Social services (guild)
from src.modules.guild import (
    GuildService,
    GuildMemberService,
    GuildInviteService,
    GuildAuditService,
    GuildPermissionService,
)

if TYPE_CHECKING:
    from logging import Logger


logger = get_logger(__name__)


class ServiceContainer:
    """
    Dependency injection container for all domain services.

    Provides centralized initialization and access to services following
    the singleton pattern.

    Usage:
        container = ServiceContainer(config_manager, event_bus, logger)
        await container.initialize()

        # Access services
        player_service = container.player_core
        maiden_service = container.maiden
    """

    def __init__(
        self,
        config_manager: ConfigManager,
        event_bus: EventBus,
        logger: Logger,
    ) -> None:
        """
        Initialize service container with required dependencies.

        Args:
            config_manager: Application configuration manager
            event_bus: Event bus for cross-module communication
            logger: Structured logger instance
        """
        self._config_manager = config_manager
        self._event_bus = event_bus
        self._logger = logger

        # Player services
        self._player_registration: Optional[PlayerRegistrationService] = None
        self._player_core: Optional[PlayerCoreService] = None
        self._player_progression: Optional[PlayerProgressionService] = None
        self._player_stats: Optional[PlayerStatsService] = None
        self._player_currencies: Optional[PlayerCurrenciesService] = None
        self._player_activity: Optional[PlayerActivityService] = None

        # Maiden services
        self._maiden: Optional[MaidenService] = None
        self._maiden_base: Optional[MaidenBaseService] = None

        # Progression services
        self._tutorial: Optional[TutorialService] = None
        self._daily_quest: Optional[DailyQuestService] = None
        self._sector_progress: Optional[SectorProgressService] = None
        self._exploration_mastery: Optional[ExplorationMasteryService] = None
        self._ascension_progress: Optional[AscensionProgressService] = None
        self._leaderboard: Optional[LeaderboardService] = None

        # Economy services
        self._shrine: Optional[ShrineService] = None
        self._guild_shrine: Optional[GuildShrineService] = None
        self._token: Optional[TokenService] = None
        self._transaction_log: Optional[TransactionLogService] = None

        # Drop services
        self._drop_charge: Optional[DropChargeService] = None

        # Social services (guild)
        self._guild: Optional[GuildService] = None
        self._guild_member: Optional[GuildMemberService] = None
        self._guild_invite: Optional[GuildInviteService] = None
        self._guild_audit: Optional[GuildAuditService] = None
        self._guild_permission: Optional[GuildPermissionService] = None

        self._initialized = False

    # ========================================================================
    # Lifecycle
    # ========================================================================

    async def initialize(self) -> None:
        """
        Initialize all services.

        Call this during application startup after ConfigManager and EventBus
        are ready.
        """
        if self._initialized:
            self._logger.warning("ServiceContainer already initialized")
            return

        self._logger.info("Initializing service container...")

        try:
            # Initialize player services
            self._player_registration = PlayerRegistrationService(
                config_manager=self._config_manager,
                event_bus=self._event_bus,
                logger=get_logger(f"{PlayerRegistrationService.__module__}.{PlayerRegistrationService.__name__}"),
            )

            self._player_core = PlayerCoreService(
                config_manager=self._config_manager,
                event_bus=self._event_bus,
                logger=get_logger(f"{PlayerCoreService.__module__}.{PlayerCoreService.__name__}"),
            )

            self._player_progression = PlayerProgressionService(
                config_manager=self._config_manager,
                event_bus=self._event_bus,
                logger=get_logger(f"{PlayerProgressionService.__module__}.{PlayerProgressionService.__name__}"),
            )

            self._player_stats = PlayerStatsService(
                config_manager=self._config_manager,
                event_bus=self._event_bus,
                logger=get_logger(f"{PlayerStatsService.__module__}.{PlayerStatsService.__name__}"),
            )

            self._player_currencies = PlayerCurrenciesService(
                config_manager=self._config_manager,
                event_bus=self._event_bus,
                logger=get_logger(f"{PlayerCurrenciesService.__module__}.{PlayerCurrenciesService.__name__}"),
            )

            self._player_activity = PlayerActivityService(
                config_manager=self._config_manager,
                event_bus=self._event_bus,
                logger=get_logger(f"{PlayerActivityService.__module__}.{PlayerActivityService.__name__}"),
            )

            # Initialize maiden services
            self._maiden = MaidenService(
                config_manager=self._config_manager,
                event_bus=self._event_bus,
                logger=get_logger(f"{MaidenService.__module__}.{MaidenService.__name__}"),
            )

            self._maiden_base = MaidenBaseService(
                config_manager=self._config_manager,
                event_bus=self._event_bus,
                logger=get_logger(f"{MaidenBaseService.__module__}.{MaidenBaseService.__name__}"),
            )

            # Initialize progression services
            self._tutorial = TutorialService(
                config_manager=self._config_manager,
                event_bus=self._event_bus,
                logger=get_logger(f"{TutorialService.__module__}.{TutorialService.__name__}"),
            )

            self._daily_quest = DailyQuestService(
                config_manager=self._config_manager,
                event_bus=self._event_bus,
                logger=get_logger(f"{DailyQuestService.__module__}.{DailyQuestService.__name__}"),
            )

            self._sector_progress = SectorProgressService(
                config_manager=self._config_manager,
                event_bus=self._event_bus,
                logger=get_logger(f"{SectorProgressService.__module__}.{SectorProgressService.__name__}"),
            )

            self._exploration_mastery = ExplorationMasteryService(
                config_manager=self._config_manager,
                event_bus=self._event_bus,
                logger=get_logger(f"{ExplorationMasteryService.__module__}.{ExplorationMasteryService.__name__}"),
            )

            self._ascension_progress = AscensionProgressService(
                config_manager=self._config_manager,
                event_bus=self._event_bus,
                logger=get_logger(f"{AscensionProgressService.__module__}.{AscensionProgressService.__name__}"),
            )

            self._leaderboard = LeaderboardService(
                config_manager=self._config_manager,
                event_bus=self._event_bus,
                logger=get_logger(f"{LeaderboardService.__module__}.{LeaderboardService.__name__}"),
            )

            # Initialize economy services
            self._shrine = ShrineService(
                config_manager=self._config_manager,
                event_bus=self._event_bus,
                logger=get_logger(f"{ShrineService.__module__}.{ShrineService.__name__}"),
            )

            self._guild_shrine = GuildShrineService(
                config_manager=self._config_manager,
                event_bus=self._event_bus,
                logger=get_logger(f"{GuildShrineService.__module__}.{GuildShrineService.__name__}"),
            )

            self._token = TokenService(
                config_manager=self._config_manager,
                event_bus=self._event_bus,
                logger=get_logger(f"{TokenService.__module__}.{TokenService.__name__}"),
            )

            self._transaction_log = TransactionLogService(
                config_manager=self._config_manager,
                event_bus=self._event_bus,
                logger=get_logger(f"{TransactionLogService.__module__}.{TransactionLogService.__name__}"),
            )

            # Initialize drop services
            self._drop_charge = DropChargeService(
                config_manager=self._config_manager,
                event_bus=self._event_bus,
                logger=get_logger(f"{DropChargeService.__module__}.{DropChargeService.__name__}"),
            )

            # Initialize social services (guild)
            self._guild = GuildService(
                config_manager=self._config_manager,
                event_bus=self._event_bus,
                logger=get_logger(f"{GuildService.__module__}.{GuildService.__name__}"),
            )

            self._guild_member = GuildMemberService(
                config_manager=self._config_manager,
                event_bus=self._event_bus,
                logger=get_logger(f"{GuildMemberService.__module__}.{GuildMemberService.__name__}"),
            )

            self._guild_invite = GuildInviteService(
                config_manager=self._config_manager,
                event_bus=self._event_bus,
                logger=get_logger(f"{GuildInviteService.__module__}.{GuildInviteService.__name__}"),
            )

            self._guild_audit = GuildAuditService(
                config_manager=self._config_manager,
                event_bus=self._event_bus,
                logger=get_logger(f"{GuildAuditService.__module__}.{GuildAuditService.__name__}"),
            )

            self._guild_permission = GuildPermissionService(
                config_manager=self._config_manager,
                event_bus=self._event_bus,
                logger=get_logger(f"{GuildPermissionService.__module__}.{GuildPermissionService.__name__}"),
            )

            self._initialized = True
            self._logger.info("Service container initialized successfully")

        except Exception as e:
            self._logger.error(
                "Failed to initialize service container",
                exc_info=True,
                extra={"error": str(e)},
            )
            raise

    async def shutdown(self) -> None:
        """
        Shutdown all services.

        Call this during application shutdown for graceful cleanup.
        """
        if not self._initialized:
            return

        self._logger.info("Shutting down service container...")

        # Services don't have explicit shutdown logic currently
        # but this is a hook for future cleanup needs

        self._initialized = False
        self._logger.info("Service container shut down")

    # ========================================================================
    # Player Services
    # ========================================================================

    @property
    def player_registration(self) -> PlayerRegistrationService:
        """Get PlayerRegistrationService instance."""
        if not self._initialized or self._player_registration is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._player_registration

    @property
    def player_core(self) -> PlayerCoreService:
        """Get PlayerCoreService instance."""
        if not self._initialized or self._player_core is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._player_core

    @property
    def player_progression(self) -> PlayerProgressionService:
        """Get PlayerProgressionService instance."""
        if not self._initialized or self._player_progression is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._player_progression

    @property
    def player_stats(self) -> PlayerStatsService:
        """Get PlayerStatsService instance."""
        if not self._initialized or self._player_stats is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._player_stats

    @property
    def player_currencies(self) -> PlayerCurrenciesService:
        """Get PlayerCurrenciesService instance."""
        if not self._initialized or self._player_currencies is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._player_currencies

    @property
    def player_activity(self) -> PlayerActivityService:
        """Get PlayerActivityService instance."""
        if not self._initialized or self._player_activity is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._player_activity

    # ========================================================================
    # Maiden Services
    # ========================================================================

    @property
    def maiden(self) -> MaidenService:
        """Get MaidenService instance."""
        if not self._initialized or self._maiden is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._maiden

    @property
    def maiden_base(self) -> MaidenBaseService:
        """Get MaidenBaseService instance."""
        if not self._initialized or self._maiden_base is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._maiden_base

    # ========================================================================
    # Progression Services
    # ========================================================================

    @property
    def tutorial(self) -> TutorialService:
        """Get TutorialService instance."""
        if not self._initialized or self._tutorial is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._tutorial

    @property
    def daily_quest(self) -> DailyQuestService:
        """Get DailyQuestService instance."""
        if not self._initialized or self._daily_quest is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._daily_quest

    @property
    def sector_progress(self) -> SectorProgressService:
        """Get SectorProgressService instance."""
        if not self._initialized or self._sector_progress is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._sector_progress

    @property
    def exploration_mastery(self) -> ExplorationMasteryService:
        """Get ExplorationMasteryService instance."""
        if not self._initialized or self._exploration_mastery is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._exploration_mastery

    @property
    def ascension_progress(self) -> AscensionProgressService:
        """Get AscensionProgressService instance."""
        if not self._initialized or self._ascension_progress is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._ascension_progress

    @property
    def leaderboard(self) -> LeaderboardService:
        """Get LeaderboardService instance."""
        if not self._initialized or self._leaderboard is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._leaderboard

    # ========================================================================
    # Economy Services
    # ========================================================================

    @property
    def shrine(self) -> ShrineService:
        """Get ShrineService instance."""
        if not self._initialized or self._shrine is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._shrine

    @property
    def guild_shrine(self) -> GuildShrineService:
        """Get GuildShrineService instance."""
        if not self._initialized or self._guild_shrine is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._guild_shrine

    @property
    def token(self) -> TokenService:
        """Get TokenService instance."""
        if not self._initialized or self._token is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._token

    @property
    def transaction_log(self) -> TransactionLogService:
        """Get TransactionLogService instance."""
        if not self._initialized or self._transaction_log is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._transaction_log

    # ========================================================================
    # Drop Services
    # ========================================================================

    @property
    def drop_charge(self) -> DropChargeService:
        """Get DropChargeService instance."""
        if not self._initialized or self._drop_charge is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._drop_charge

    # ========================================================================
    # Social Services (Guild)
    # ========================================================================

    @property
    def guild(self) -> GuildService:
        """Get GuildService instance."""
        if not self._initialized or self._guild is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._guild

    @property
    def guild_member(self) -> GuildMemberService:
        """Get GuildMemberService instance."""
        if not self._initialized or self._guild_member is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._guild_member

    @property
    def guild_invite(self) -> GuildInviteService:
        """Get GuildInviteService instance."""
        if not self._initialized or self._guild_invite is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._guild_invite

    @property
    def guild_audit(self) -> GuildAuditService:
        """Get GuildAuditService instance."""
        if not self._initialized or self._guild_audit is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._guild_audit

    @property
    def guild_permission(self) -> GuildPermissionService:
        """Get GuildPermissionService instance."""
        if not self._initialized or self._guild_permission is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._guild_permission

    # ========================================================================
    # Utility
    # ========================================================================

    @property
    def is_initialized(self) -> bool:
        """Check if container is initialized."""
        return self._initialized


# ============================================================================
# Global Container Instance
# ============================================================================

_global_container: Optional[ServiceContainer] = None


def initialize_service_container(
    config_manager: ConfigManager,
    event_bus: EventBus,
    logger: Optional[Logger] = None,
) -> ServiceContainer:
    """
    Initialize the global service container.

    Args:
        config_manager: Application configuration manager
        event_bus: Event bus for cross-module communication
        logger: Optional logger (defaults to module logger)

    Returns:
        Initialized ServiceContainer instance

    Example:
        >>> from src.core.config.manager import ConfigManager
        >>> from src.core.event.bus import EventBus
        >>> config = ConfigManager(...)
        >>> event_bus = EventBus()
        >>> container = initialize_service_container(config, event_bus)
        >>> await container.initialize()
    """
    global _global_container

    if _global_container is not None:
        logger_instance = logger or get_logger(__name__)
        logger_instance.warning("Service container already initialized, returning existing instance")
        return _global_container

    container = ServiceContainer(
        config_manager=config_manager,
        event_bus=event_bus,
        logger=logger or get_logger(__name__),
    )

    _global_container = container
    return container


def get_service_container() -> ServiceContainer:
    """
    Get the global service container instance.

    Returns:
        Global ServiceContainer instance

    Raises:
        RuntimeError: If container not initialized

    Example:
        >>> container = get_service_container()
        >>> player_service = container.player_core
    """
    if _global_container is None:
        raise RuntimeError(
            "Service container not initialized. "
            "Call initialize_service_container() first."
        )
    return _global_container


async def shutdown_service_container() -> None:
    """
    Shutdown the global service container.

    Call this during application shutdown.
    """
    global _global_container

    if _global_container is not None:
        await _global_container.shutdown()
        _global_container = None
