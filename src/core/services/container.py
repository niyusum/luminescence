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
from src.modules.maiden import (
    MaidenBaseService,
    MaidenService,
    PowerCalculationService,
    LeaderSkillService,
)

# Exploration services
from src.modules.exploration import (
    ExplorationMasteryService,
    SectorProgressService,
    MatronService,
)

# Ascension services
from src.modules.ascension import AscensionProgressService, AscensionTokenService

# Combat services
from src.modules.combat import (
    CombatService,
    ElementalTeamEngine,
    PvPEngine,
    AggregateEngine,
)
from src.modules.combat.shared.elements import ElementResolver
from src.modules.combat.shared.formulas import CombatFormulas
from src.modules.combat.shared.hp_scaling import HPScalingCalculator

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
        self._power_calculation: Optional[PowerCalculationService] = None
        self._leader_skill: Optional[LeaderSkillService] = None

        # Progression services
        self._tutorial: Optional[TutorialService] = None
        self._daily_quest: Optional[DailyQuestService] = None
        self._sector_progress: Optional[SectorProgressService] = None
        self._exploration_mastery: Optional[ExplorationMasteryService] = None
        self._matron: Optional[MatronService] = None
        self._ascension_progress: Optional[AscensionProgressService] = None
        self._ascension_token: Optional[AscensionTokenService] = None
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

        # Combat services
        self._element_resolver: Optional[ElementResolver] = None
        self._combat_formulas: Optional[CombatFormulas] = None
        self._hp_scaling: Optional[HPScalingCalculator] = None
        self._elemental_engine: Optional[ElementalTeamEngine] = None
        self._pvp_engine: Optional[PvPEngine] = None
        self._aggregate_engine: Optional[AggregateEngine] = None
        self._combat: Optional[CombatService] = None

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

            # Power and leader skill services (config-only)
            start = time.perf_counter()
            self._power_calculation = PowerCalculationService(self._config_manager)
            self._service_init_times["power_calculation"] = time.perf_counter() - start

            start = time.perf_counter()
            self._leader_skill = LeaderSkillService(self._config_manager)
            self._service_init_times["leader_skill"] = time.perf_counter() - start

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

            # Ascension token service (needs token_service)
            if not self._token:
                raise RuntimeError("TokenService must be initialized before AscensionTokenService")
            start = time.perf_counter()
            self._ascension_token = AscensionTokenService(
                config_manager=self._config_manager,
                event_bus=self._event_bus,
                logger=get_logger("src.modules.ascension.token_service.AscensionTokenService"),
                token_service=self._token,
            )
            self._service_init_times["ascension_token"] = time.perf_counter() - start

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

            # Initialize combat helper services
            start = time.perf_counter()
            self._element_resolver = ElementResolver(self._config_manager)
            self._service_init_times["element_resolver"] = time.perf_counter() - start

            start = time.perf_counter()
            self._combat_formulas = CombatFormulas(self._element_resolver)
            self._service_init_times["combat_formulas"] = time.perf_counter() - start

            start = time.perf_counter()
            self._hp_scaling = HPScalingCalculator(self._config_manager)
            self._service_init_times["hp_scaling"] = time.perf_counter() - start

            # Initialize combat engines (need power, leader, elements, formulas, hp_scaling, player_progression)
            if not self._power_calculation or not self._leader_skill:
                raise RuntimeError("Power and Leader services must be initialized before combat engines")
            if not self._player_progression:
                raise RuntimeError("PlayerProgressionService must be initialized before combat engines")

            start = time.perf_counter()
            self._elemental_engine = ElementalTeamEngine(
                config_manager=self._config_manager,
                power_service=self._power_calculation,
                leader_service=self._leader_skill,
                element_resolver=self._element_resolver,
                combat_formulas=self._combat_formulas,
                hp_scaling=self._hp_scaling,
                player_progression_service=self._player_progression,
            )
            self._service_init_times["elemental_engine"] = time.perf_counter() - start

            start = time.perf_counter()
            self._pvp_engine = PvPEngine(
                config_manager=self._config_manager,
                power_service=self._power_calculation,
                leader_service=self._leader_skill,
                element_resolver=self._element_resolver,
                combat_formulas=self._combat_formulas,
                hp_scaling=self._hp_scaling,
            )
            self._service_init_times["pvp_engine"] = time.perf_counter() - start

            start = time.perf_counter()
            self._aggregate_engine = AggregateEngine(
                config_manager=self._config_manager,
                power_service=self._power_calculation,
                leader_service=self._leader_skill,
                element_resolver=self._element_resolver,
                combat_formulas=self._combat_formulas,
                hp_scaling=self._hp_scaling,
            )
            self._service_init_times["aggregate_engine"] = time.perf_counter() - start

            # Initialize combat service (needs engines + ascension services)
            if not self._ascension_token:
                raise RuntimeError("AscensionTokenService must be initialized before CombatService")
            if not self._ascension_progress:
                raise RuntimeError("AscensionProgressService must be initialized before CombatService")

            start = time.perf_counter()
            self._combat = CombatService(
                config_manager=self._config_manager,
                event_bus=self._event_bus,
                logger=get_logger("src.modules.combat.service.CombatService"),
                elemental_engine=self._elemental_engine,
                pvp_engine=self._pvp_engine,
                aggregate_engine=self._aggregate_engine,
                ascension_token_service=self._ascension_token,
                ascension_progress_service=self._ascension_progress,
            )
            self._service_init_times["combat"] = time.perf_counter() - start

            # Initialize matron service (needs combat + sector_progress + player services)
            if not self._sector_progress:
                raise RuntimeError("SectorProgressService must be initialized before MatronService")
            if not self._player_currencies:
                raise RuntimeError("PlayerCurrenciesService must be initialized before MatronService")
            if not self._player_progression:
                raise RuntimeError("PlayerProgressionService must be initialized before MatronService")
            if not self._player_stats:
                raise RuntimeError("PlayerStatsService must be initialized before MatronService")

            start = time.perf_counter()
            self._matron = MatronService(
                config_manager=self._config_manager,
                event_bus=self._event_bus,
                logger=get_logger("src.modules.exploration.matron_service.MatronService"),
                combat_service=self._combat,
                sector_progress_service=self._sector_progress,
                player_currencies_service=self._player_currencies,
                player_progression_service=self._player_progression,
                player_stats_service=self._player_stats,
            )
            self._service_init_times["matron"] = time.perf_counter() - start

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
            and len(self._service_init_times) == 35,
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

    @property
    def power_calculation(self) -> PowerCalculationService:
        if not self._initialized or self._power_calculation is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._power_calculation

    @property
    def leader_skill(self) -> LeaderSkillService:
        if not self._initialized or self._leader_skill is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._leader_skill

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
    def matron(self) -> MatronService:
        if not self._initialized or self._matron is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._matron

    @property
    def ascension_progress(self) -> AscensionProgressService:
        if not self._initialized or self._ascension_progress is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._ascension_progress

    @property
    def ascension_token(self) -> AscensionTokenService:
        if not self._initialized or self._ascension_token is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._ascension_token

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
    # Combat Services
    # ========================================================================

    @property
    def element_resolver(self) -> ElementResolver:
        if not self._initialized or self._element_resolver is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._element_resolver

    @property
    def combat_formulas(self) -> CombatFormulas:
        if not self._initialized or self._combat_formulas is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._combat_formulas

    @property
    def hp_scaling(self) -> HPScalingCalculator:
        if not self._initialized or self._hp_scaling is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._hp_scaling

    @property
    def elemental_engine(self) -> ElementalTeamEngine:
        if not self._initialized or self._elemental_engine is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._elemental_engine

    @property
    def pvp_engine(self) -> PvPEngine:
        if not self._initialized or self._pvp_engine is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._pvp_engine

    @property
    def aggregate_engine(self) -> AggregateEngine:
        if not self._initialized or self._aggregate_engine is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._aggregate_engine

    @property
    def combat(self) -> CombatService:
        if not self._initialized or self._combat is None:
            raise RuntimeError("ServiceContainer not initialized. Call initialize() first.")
        return self._combat

    # ========================================================================
    # Utility
    # ========================================================================

    @property
    def is_initialized(self) -> bool:
        """Check if container is initialized."""
        return self._initialized