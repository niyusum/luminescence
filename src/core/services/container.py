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

Non-Responsibilities
--------------------
- Application-level lifecycle orchestration (delegated to ApplicationContext)
- Bot initialization (delegated to LumenBot)
- Infrastructure initialization order (delegated to ApplicationContext)

LUMEN 2025 COMPLIANCE
---------------------
✓ Separation of concerns - infrastructure only
✓ No business logic
✓ Config-driven service initialization
✓ Fail-fast on critical services (all services are critical)
✓ Minimal observability (timing + health check)

Architecture Notes
------------------
- ServiceContainer is instantiated and initialized by ApplicationContext
- Receives dependencies (ConfigManager, EventBus) via constructor injection
- All domain services follow the same constructor pattern: (config_manager, event_bus, logger)
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Dict, Optional

from src.core.config.manager import ConfigManager
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
    from src.core.event.bus import EventBus  # type-only import

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

        # Minimal observability (LES 2025)
        self._service_init_times: Dict[str, float] = {}
        self._init_start: Optional[float] = None
        self._init_end: Optional[float] = None

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

        self._init_start = time.perf_counter()
        self._logger.info("Service container initialization starting...")

        try:
            # Initialize player services
            self._player_registration = self._create_service(
                "player_registration",
                PlayerRegistrationService,
            )

            self._player_core = self._create_service(
                "player_core",
                PlayerCoreService,
            )

            self._player_progression = self._create_service(
                "player_progression",
                PlayerProgressionService,
            )

            self._player_stats = self._create_service(
                "player_stats",
                PlayerStatsService,
            )

            self._player_currencies = self._create_service(
                "player_currencies",
                PlayerCurrenciesService,
            )

            self._player_activity = self._create_service(
                "player_activity",
                PlayerActivityService,
            )

            # Initialize maiden services
            self._maiden = self._create_service(
                "maiden",
                MaidenService,
            )

            self._maiden_base = self._create_service(
                "maiden_base",
                MaidenBaseService,
            )

            # Initialize progression services
            self._tutorial = self._create_service(
                "tutorial",
                TutorialService,
            )

            self._daily_quest = self._create_service(
                "daily_quest",
                DailyQuestService,
            )

            self._sector_progress = self._create_service(
                "sector_progress",
                SectorProgressService,
            )

            self._exploration_mastery = self._create_service(
                "exploration_mastery",
                ExplorationMasteryService,
            )

            self._ascension_progress = self._create_service(
                "ascension_progress",
                AscensionProgressService,
            )

            self._leaderboard = self._create_service(
                "leaderboard",
                LeaderboardService,
            )

            # Initialize economy services
            self._shrine = self._create_service(
                "shrine",
                ShrineService,
            )

            self._guild_shrine = self._create_service(
                "guild_shrine",
                GuildShrineService,
            )

            self._token = self._create_service(
                "token",
                TokenService,
            )

            self._transaction_log = self._create_service(
                "transaction_log",
                TransactionLogService,
            )

            # Initialize drop services
            self._drop_charge = self._create_service(
                "drop_charge",
                DropChargeService,
            )

            # Initialize social services (guild)
            self._guild = self._create_service(
                "guild",
                GuildService,
            )

            self._guild_member = self._create_service(
                "guild_member",
                GuildMemberService,
            )

            self._guild_invite = self._create_service(
                "guild_invite",
                GuildInviteService,
            )

            self._guild_audit = self._create_service(
                "guild_audit",
                GuildAuditService,
            )

            self._guild_permission = self._create_service(
                "guild_permission",
                GuildPermissionService,
            )

            self._init_end = time.perf_counter()
            self._initialized = True

            extra_data: Dict[str, Any] = {
                "total_time_seconds": round(self._init_end - self._init_start, 3),
                "service_count": len(self._service_init_times),
            }

            if self._service_init_times:
                slowest = max(
                    self._service_init_times,
                    key=self._service_init_times.__getitem__,
                )
                extra_data["slowest_service"] = slowest
                extra_data["slowest_duration"] = round(
                    self._service_init_times[slowest],
                    3,
                )

            self._logger.info(
                "Service container initialized successfully",
                extra=extra_data,
            )

        except Exception as e:
            self._logger.critical(
                "Service container initialization failed - bot cannot start",
                exc_info=True,
                extra={"error": str(e)},
            )
            raise

    def _create_service(self, name: str, cls: type) -> Any:
        """
        Minimal LES-compliant service constructor with timing.

        Args:
            name: Service name for logging and tracking
            cls: Service class to instantiate

        Returns:
            Initialized service instance

        Raises:
            Exception: If service initialization fails
        """
        start = time.perf_counter()

        try:
            instance = cls(
                config_manager=self._config_manager,
                event_bus=self._event_bus,
                logger=get_logger(f"{cls.__module__}.{cls.__name__}"),
            )
        except Exception:
            self._logger.error(f"Failed to initialize {name}", exc_info=True)
            raise

        duration = time.perf_counter() - start
        self._service_init_times[name] = duration
        self._logger.debug(f"Initialized {name} in {duration:.3f}s")

        return instance

    async def shutdown(self) -> None:
        """
        Shutdown all services.

        Call this during application shutdown for graceful cleanup.
        """
        if not self._initialized:
            return

        self._logger.info("Shutting down service container...")

        # Hook for future service-level cleanup

        self._initialized = False
        self._logger.info("Service container shut down")

    async def health_check(self) -> Dict[str, bool | float | int | None]:
        """
        Internal LES-compliant health snapshot for /status or admin diagnostics.
        """
        return {
            "initialized": self._initialized,
            "service_count": len(self._service_init_times),
            "total_init_time_seconds": (
                round(self._init_end - self._init_start, 3)
                if self._init_start and self._init_end
                else None
            ),
            "all_services_available": self._initialized
            and len(self._service_init_times) == 24,
        }

    # ========================================================================
    # Player Services
    # ========================================================================

    @property
    def player_registration(self) -> PlayerRegistrationService:
        if not self._initialized or self._player_registration is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._player_registration

    @property
    def player_core(self) -> PlayerCoreService:
        if not self._initialized or self._player_core is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._player_core

    @property
    def player_progression(self) -> PlayerProgressionService:
        if not self._initialized or self._player_progression is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._player_progression

    @property
    def player_stats(self) -> PlayerStatsService:
        if not self._initialized or self._player_stats is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._player_stats

    @property
    def player_currencies(self) -> PlayerCurrenciesService:
        if not self._initialized or self._player_currencies is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._player_currencies

    @property
    def player_activity(self) -> PlayerActivityService:
        if not self._initialized or self._player_activity is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._player_activity

    # ========================================================================
    # Maiden Services
    # ========================================================================

    @property
    def maiden(self) -> MaidenService:
        if not self._initialized or self._maiden is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._maiden

    @property
    def maiden_base(self) -> MaidenBaseService:
        if not self._initialized or self._maiden_base is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._maiden_base

    # ========================================================================
    # Progression Services
    # ========================================================================

    @property
    def tutorial(self) -> TutorialService:
        if not self._initialized or self._tutorial is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._tutorial

    @property
    def daily_quest(self) -> DailyQuestService:
        if not self._initialized or self._daily_quest is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._daily_quest

    @property
    def sector_progress(self) -> SectorProgressService:
        if not self._initialized or self._sector_progress is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._sector_progress

    @property
    def exploration_mastery(self) -> ExplorationMasteryService:
        if not self._initialized or self._exploration_mastery is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._exploration_mastery

    @property
    def ascension_progress(self) -> AscensionProgressService:
        if not self._initialized or self._ascension_progress is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._ascension_progress

    @property
    def leaderboard(self) -> LeaderboardService:
        if not self._initialized or self._leaderboard is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._leaderboard

    # ========================================================================
    # Economy Services
    # ========================================================================

    @property
    def shrine(self) -> ShrineService:
        if not self._initialized or self._shrine is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._shrine

    @property
    def guild_shrine(self) -> GuildShrineService:
        if not self._initialized or self._guild_shrine is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._guild_shrine

    @property
    def token(self) -> TokenService:
        if not self._initialized or self._token is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._token

    @property
    def transaction_log(self) -> TransactionLogService:
        if not self._initialized or self._transaction_log is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._transaction_log

    # ========================================================================
    # Drop Services
    # ========================================================================

    @property
    def drop_charge(self) -> DropChargeService:
        if not self._initialized or self._drop_charge is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._drop_charge

    # ========================================================================
    # Social Services (Guild)
    # ========================================================================

    @property
    def guild(self) -> GuildService:
        if not self._initialized or self._guild is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._guild

    @property
    def guild_member(self) -> GuildMemberService:
        if not self._initialized or self._guild_member is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._guild_member

    @property
    def guild_invite(self) -> GuildInviteService:
        if not self._initialized or self._guild_invite is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._guild_invite

    @property
    def guild_audit(self) -> GuildAuditService:
        if not self._initialized or self._guild_audit is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._guild_audit

    @property
    def guild_permission(self) -> GuildPermissionService:
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