"""
ConfigManager: dynamic, cache-backed game configuration access for Lumen (2025).

Purpose
-------
- Provide hierarchical, dot-notation access to tunable game configuration values.
- Back configuration with YAML defaults plus database overrides.
- Maintain a warm in-memory cache with periodic background refresh.
- Enable hot balance changes without redeploys, with full audit + optional events.

Responsibilities
----------------
- Load and merge infrastructure + balance defaults from the `config/` directory.
- Overlay database-backed overrides on top of YAML defaults.
- Serve configuration reads from an in-memory cache with metrics and stale detection.
- Apply atomic, transactional updates to configuration values with pessimistic locking.
- Validate configuration structures using recursive schema objects.
- Emit transaction logs and optionally publish EventBus events on changes.

Lumen 2025 Compliance
---------------------
- **Separation of concerns**: Pure infra; no Discord or game-domain logic.
- **Transaction discipline**:
  - All writes use `DatabaseService.get_transaction()`; no manual commits/rollbacks.
  - Writes lock the relevant `GameConfig` row via `SELECT ... FOR UPDATE`.
- **Config-driven balance**:
  - No hard-coded game parameters; tunables live in YAML or DB.
  - TTL for config cache is itself configurable via YAML *and* DB.
- **Observability**:
  - Structured logs for init, refresh, reads, writes, validation, and errors.
  - Metrics for hits, misses, stale reads, latencies, and error counts.
  - Health and metrics snapshots for infra dashboards.
- **Transaction logging & events**:
  - Every mutation logs a transaction via `TransactionLogger`.
  - Optional EventBus publish for config change events.
- **Graceful degradation**:
  - Falls back to YAML/defaults if DB is unavailable or config is invalid.
  - Background refresh errors are logged but do not crash the loop.

Key Design Decisions
--------------------
- YAML is the single source for **defaults**; the database stores **overrides**.
- Top-level config keys map to rows in `GameConfig`; nested config keys are
  stored as nested dictionaries in `config_value`.
- Cache refresh uses a configurable TTL. TTL can come from:
  1. Hardcoded infra fallback (300s) – last resort.
  2. YAML (`core.config_cache_ttl_seconds`).
  3. Database (`core.config_cache_ttl_seconds`) – highest precedence.
- A custom recursive `ConfigSchema` type enforces nested structure and types
  per top-level key without external dependencies.
- Reads include time-aware stale detection relative to TTL, tracked in metrics.

Dependencies
------------
- `src.database.models.core.game_config.GameConfig` – DB model for persisted config.
- `src.core.database.service.DatabaseService` – async DB sessions and transactions.
- `src.core.infra.transaction_logger.TransactionLogger` – audit logging for mutations.
- `src.core.event.bus.EventBus` – optional EventBus publishing on config changes.
- `src.core.logging.logger.get_logger` – structured logging interface.
- `src.core.config.validator` – configuration validation and schema management.
- `src.core.config.metrics` – metrics tracking and health snapshots.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Optional

from sqlalchemy import select

from src.core.config.metrics import (
    ConfigMetrics,
    get_health_snapshot,
    get_metrics_snapshot,
)
from src.core.config.validator import get_schema_for_top_key
from src.core.logging.logger import get_logger
from src.database.models.core.game_config import GameConfig

logger = get_logger(__name__)


# ============================================================================
# Exceptions
# ============================================================================


class ConfigManagerError(RuntimeError):
    """Base error type for ConfigManager-related failures."""


class ConfigInitializationError(ConfigManagerError):
    """Raised when ConfigManager cannot initialize correctly."""


class ConfigWriteError(ConfigManagerError):
    """Raised when a configuration write or validation fails."""


# Export ConfigWriteError from validator for backward compatibility
__all__ = ["ConfigManager", "ConfigManagerError", "ConfigInitializationError", "ConfigWriteError"]


# ============================================================================
# ConfigManager
# ============================================================================


class ConfigManager:
    """
    Dynamic game configuration management with database backing and caching.

    Features
    --------
    - Hierarchical config access with dot notation (e.g. `"fusion_costs.base"`).
    - In-memory caching with periodic background refresh.
    - Hot-reload support for live balance changes.
    - Recursive schema-based validation for nested configuration structures.
    - Audit trail via `TransactionLogger` and optional EventBus events.
    - Performance metrics, stale-read detection, and health snapshots.
    """

    # In-memory cache of fully materialized configuration values.
    _cache: Dict[str, Any] = {}
    _cache_timestamps: Dict[str, datetime] = {}

    # Initialization & lifecycle state.
    _initialized: bool = False
    _refresh_task: Optional[asyncio.Task[None]] = None

    # Locks.
    _init_lock: asyncio.Lock = asyncio.Lock()
    _cache_lock: asyncio.Lock = asyncio.Lock()

    # Cache refresh interval (seconds).
    # Precedence: hardcoded default < YAML < DB.
    _cache_ttl_seconds: int = 300

    # Metrics container.
    _metrics: ConfigMetrics = ConfigMetrics()

    # YAML + infra defaults (non-gameplay fallbacks only).
    _defaults: Dict[str, Any] = {}

    # Optional validators: full dot key -> callable(value) -> value
    _validators: Dict[str, Callable[[Any], Any]] = {}

    # Event emission control (global toggle).
    _emit_events: bool = True

    # =========================================================================
    # YAML LOADING & DEFAULTS
    # =========================================================================

    @staticmethod
    def _deep_merge_dict(
        target: MutableMapping[str, Any],
        source: MutableMapping[str, Any],
    ) -> None:
        """Recursively merge `source` into `target` (in-place)."""
        for key, value in source.items():
            if (
                isinstance(value, dict)
                and isinstance(target.get(key), dict)
            ):
                ConfigManager._deep_merge_dict(
                    target[key], value  # type: ignore[index]
                )
            else:
                target[key] = value

    @classmethod
    def _load_yaml_configs(cls) -> None:
        """
        Recursively load all YAML config files from `config/` into `_defaults`.

        - Deep-merges all YAML dictionaries to allow modular composition.
        - Only infra defaults and balance defaults belong here; no secrets.
        - Gracefully handles missing `config/` directory or missing PyYAML.
        """
        try:
            import yaml  # type: ignore[import]
        except ImportError:
            logger.warning(
                "PyYAML not installed; skipping YAML config loading. "
                "Install with: pip install pyyaml"
            )
            return

        config_dir = Path("config")
        if not config_dir.exists():
            logger.warning(
                "Config directory not found; using built-in defaults only",
                extra={"config_dir": str(config_dir)},
            )
            return

        yaml_files = list(config_dir.rglob("*.yaml")) + list(config_dir.rglob("*.yml"))
        if not yaml_files:
            logger.info(
                "No YAML config files discovered; using built-in defaults only",
                extra={"config_dir": str(config_dir)},
            )
            return

        loaded_count = 0

        for yaml_file in yaml_files:
            try:
                with yaml_file.open("r", encoding="utf-8") as handle:
                    data = yaml.safe_load(handle)
                if isinstance(data, dict):
                    cls._deep_merge_dict(cls._defaults, data)
                    loaded_count += 1
                    logger.debug(
                        "Loaded YAML config",
                        extra={
                            "file": str(yaml_file.relative_to(config_dir)),
                            "absolute_path": str(yaml_file),
                        },
                    )
                elif data is not None:
                    logger.warning(
                        "Ignoring non-dict YAML root object",
                        extra={
                            "file": str(yaml_file.relative_to(config_dir)),
                            "root_type": type(data).__name__,
                        },
                    )
            except Exception as exc:
                logger.warning(
                    "Failed to load YAML config",
                    extra={
                        "file": str(yaml_file.relative_to(config_dir)),
                        "absolute_path": str(yaml_file),
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                    },
                    exc_info=True,
                )

        # Copy defaults into cache as initial in-memory state.
        cls._cache = dict(cls._defaults)

        logger.info(
            "YAML configs loaded",
            extra={
                "yaml_file_count": loaded_count,
                "total_cache_keys": len(cls._cache),
            },
        )

        # Allow YAML to define cache TTL; DB can override later.
        cls._refresh_cache_ttl_from_cache_locked()

    @classmethod
    def _refresh_cache_ttl_from_cache_locked(cls) -> None:
        """
        Inspect current cache for TTL configuration and update `_cache_ttl_seconds`.

        Precedence:
        - `core.config_cache_ttl_seconds` in cache (DB overrides YAML).
        - Leaves existing value unchanged if no valid override present.

        NOTE: Must be called only when `_cache_lock` is already held OR in
        single-threaded initialization scenarios.
        """
        core_cfg = cls._cache.get("core")
        ttl_candidate: Optional[int] = None

        if isinstance(core_cfg, Mapping):
            raw = core_cfg.get("config_cache_ttl_seconds")
            if isinstance(raw, int) and raw > 0:
                ttl_candidate = raw

        if ttl_candidate is not None and ttl_candidate != cls._cache_ttl_seconds:
            old_ttl = cls._cache_ttl_seconds
            cls._cache_ttl_seconds = ttl_candidate
            logger.info(
                "Config cache TTL updated from cache",
                extra={
                    "old_cache_ttl_seconds": old_ttl,
                    "new_cache_ttl_seconds": cls._cache_ttl_seconds,
                },
            )

    # =========================================================================
    # INITIALIZATION / REFRESH
    # =========================================================================

    @classmethod
    async def initialize(cls) -> None:
        """
        Initialize ConfigManager from YAML and the database (idempotent).

        Steps
        -----
        - Load YAML defaults from the `config/` directory.
        - Materialize DB-backed overrides onto the in-memory cache.
        - Validate DB overrides against schemas where available.
        - Start the background refresh task if not already running.

        Raises
        ------
        ConfigInitializationError
            If initialization fails in a way that should abort startup.
        """
        from src.core.database.service import DatabaseService

        # Double-checked locking to avoid racing initializers.
        if cls._initialized:
            return

        async with cls._init_lock:
            if cls._initialized:
                return

            init_start = time.perf_counter()

            # Step 1: always (re)load YAML defaults into `_defaults` and `_cache`.
            cls._load_yaml_configs()

            try:
                async with DatabaseService.get_session() as session:
                    result = await session.execute(select(GameConfig))
                    configs: List[GameConfig] = list(result.scalars().all())

                    async with cls._cache_lock:
                        if configs:
                            for cfg in configs:
                                # Validate with schema if available.
                                schema = get_schema_for_top_key(cfg.config_key)
                                if schema:
                                    try:
                                        schema.validate(
                                            cfg.config_value,
                                            path=cfg.config_key,
                                        )
                                    except ConfigWriteError as validation_exc:
                                        cls._metrics.errors += 1
                                        logger.error(
                                            "Invalid config in database; "
                                            "skipping override and using defaults",
                                            extra={
                                                "config_key": cfg.config_key,
                                                "error": str(validation_exc),
                                                "error_type": type(validation_exc).__name__,
                                            },
                                            exc_info=True,
                                        )
                                        # Do not override YAML/defaults for this key.
                                        continue

                                cls._cache[cfg.config_key] = cfg.config_value
                                cls._cache_timestamps[cfg.config_key] = datetime.now(
                                    timezone.utc
                                )

                            logger.info(
                                "ConfigManager initialized from database",
                                extra={
                                    "config_count": len(configs),
                                    "source": "database+yaml",
                                },
                            )
                        else:
                            # No DB overrides; rely on YAML + built-in defaults.
                            if not cls._cache:
                                cls._cache = dict(cls._defaults)
                            logger.info(
                                "ConfigManager initialized without DB overrides; "
                                "using defaults",
                                extra={
                                    "config_count": len(cls._cache),
                                    "source": "yaml+defaults",
                                },
                            )

                        # Allow DB overrides to set cache TTL.
                        cls._refresh_cache_ttl_from_cache_locked()

                cls._initialized = True

                if cls._refresh_task is None or cls._refresh_task.done():
                    cls._refresh_task = asyncio.create_task(cls._background_refresh())
                    logger.info(
                        "ConfigManager background refresh started",
                        extra={"cache_ttl_seconds": cls._cache_ttl_seconds},
                    )

                elapsed_ms = (time.perf_counter() - init_start) * 1000
                logger.info(
                    "ConfigManager initialization completed",
                    extra={"latency_ms": round(elapsed_ms, 2)},
                )

            except Exception as exc:
                cls._metrics.errors += 1
                # Keep the system limping along with defaults where possible.
                async with cls._cache_lock:
                    if not cls._cache:
                        cls._cache = dict(cls._defaults)

                cls._initialized = True  # Mark as initialized in degraded mode.

                logger.error(
                    "ConfigManager initialization failed; falling back to defaults",
                    extra={
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                        "cache_keys_after_fallback": len(cls._cache),
                    },
                    exc_info=True,
                )
                raise ConfigInitializationError("Failed to initialize ConfigManager") from exc

    @classmethod
    async def _background_refresh(cls) -> None:
        """
        Periodically refresh configuration overrides from the database.

        - Runs forever until cancelled via `shutdown()`.
        - Uses `_cache_ttl_seconds` as the sleep interval (TTL from YAML/DB).
        - Validates incoming configs against schemas where available.
        - Never raises to the task loop; all errors are logged and counted.
        """
        from src.core.database.service import DatabaseService

        logger.debug(
            "ConfigManager background refresh loop starting",
            extra={"cache_ttl_seconds": cls._cache_ttl_seconds},
        )

        try:
            while True:
                try:
                    await asyncio.sleep(cls._cache_ttl_seconds)

                    async with DatabaseService.get_session() as session:
                        result = await session.execute(select(GameConfig))
                        configs: List[GameConfig] = list(result.scalars().all())

                        async with cls._cache_lock:
                            for cfg in configs:
                                schema = get_schema_for_top_key(cfg.config_key)
                                if schema:
                                    try:
                                        schema.validate(
                                            cfg.config_value,
                                            path=cfg.config_key,
                                        )
                                    except ConfigWriteError as validation_exc:
                                        cls._metrics.errors += 1
                                        logger.error(
                                            "Invalid config in database during refresh; "
                                            "skipping update and preserving existing cache",
                                            extra={
                                                "config_key": cfg.config_key,
                                                "error": str(validation_exc),
                                                "error_type": type(validation_exc).__name__,
                                            },
                                            exc_info=True,
                                        )
                                        continue

                                cls._cache[cfg.config_key] = cfg.config_value
                                cls._cache_timestamps[cfg.config_key] = datetime.now(
                                    timezone.utc
                                )

                            cls._metrics.refresh_count += 1

                            # DB overrides can update TTL.
                            cls._refresh_cache_ttl_from_cache_locked()

                        logger.debug(
                            "ConfigManager cache refreshed from database",
                            extra={
                                "config_count": len(configs),
                                "refresh_count": cls._metrics.refresh_count,
                            },
                        )
                except asyncio.CancelledError:
                    logger.info("ConfigManager background refresh task cancelled")
                    raise
                except Exception as exc:
                    cls._metrics.errors += 1
                    logger.error(
                        "ConfigManager background refresh error",
                        extra={
                            "error": str(exc),
                            "error_type": type(exc).__name__,
                        },
                        exc_info=True,
                    )
        except asyncio.CancelledError:
            logger.info("ConfigManager background refresh loop terminated")

    @classmethod
    async def shutdown(cls) -> None:
        """
        Stop the background refresh task and clean up resources.

        Safe to call multiple times.
        """
        task = cls._refresh_task
        if task is None:
            return

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        finally:
            cls._refresh_task = None
            logger.info("ConfigManager shutdown complete")

    # =========================================================================
    # EVENT EMISSION CONTROL
    # =========================================================================

    @classmethod
    def set_event_emission(cls, enabled: bool) -> None:
        """Globally enable or disable EventBus publishing on config changes."""
        cls._emit_events = enabled
        logger.info(
            "ConfigManager event emission updated",
            extra={"emit_events": enabled},
        )

    @classmethod
    def enable_events(cls) -> None:
        """Enable EventBus publishing on config changes."""
        cls.set_event_emission(True)

    @classmethod
    def disable_events(cls) -> None:
        """Disable EventBus publishing on config changes."""
        cls.set_event_emission(False)

    # =========================================================================
    # VALIDATION HOOKS
    # =========================================================================

    @classmethod
    def register_validator(cls, key: str, validator: Callable[[Any], Any]) -> None:
        """
        Register a validator for a specific configuration key path.

        Validators are invoked on write and must either:
        - return a (possibly transformed) value, or
        - raise an exception to block the write.

        Parameters
        ----------
        key:
            Exact dot-notation key to validate (e.g. `"fusion_costs.base"`).
        validator:
            Callable that accepts the proposed value and returns the value to persist.
        """
        cls._validators[key] = validator
        logger.info(
            "ConfigManager validator registered",
            extra={
                "config_key": key,
                "validator": getattr(validator, "__name__", "anonymous"),
            },
        )

    @classmethod
    def _apply_validator(cls, key: str, value: Any) -> Any:
        """
        Apply a validator for the key if registered; otherwise, return the value.

        Validators are best-effort: any exception is logged and counted, but will
        be re-raised as a `ConfigWriteError` to keep semantics explicit.
        """
        validator = cls._validators.get(key)
        if not validator:
            return value

        try:
            return validator(value)
        except Exception as exc:
            cls._metrics.errors += 1
            logger.error(
                "Config validation failed",
                extra={
                    "config_key": key,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
            raise ConfigWriteError(f"Validation failed for config key '{key}'") from exc

    @classmethod
    def _apply_schema_validation_for_write(
        cls,
        top_key: str,
        final_value: Any,
    ) -> Any:
        """
        Validate a top-level configuration payload against its schema (if any).

        Intended for writes: failure results in `ConfigWriteError` and blocks
        the write operation.
        """
        from src.core.config.validator import validate_config_value

        return validate_config_value(top_key, final_value)

    # =========================================================================
    # READ API
    # =========================================================================

    @classmethod
    def _get_from_defaults(cls, key: str) -> Any:
        """Traverse default config using dot notation; returns `None` if missing."""
        value: Any = cls._defaults
        for k in key.split("."):
            if isinstance(value, dict):
                value = value.get(k)
                if value is None:
                    return None
            else:
                return None
        return value

    @classmethod
    def is_stale(cls, key: str) -> bool:
        """
        Check whether a cached top-level configuration entry is stale.

        Staleness is defined as cache age strictly greater than the current TTL.

        Parameters
        ----------
        key:
            Either a full dot key or a top-level key. Only the top-level segment is used.

        Returns
        -------
        bool
            True if the cache age exceeds TTL; False if fresh or unknown.
        """
        top_key = key.split(".")[0]
        timestamp = cls._cache_timestamps.get(top_key)
        if not timestamp:
            return False

        age_seconds = (datetime.now(timezone.utc) - timestamp).total_seconds()
        return age_seconds > cls._cache_ttl_seconds

    @classmethod
    def get(cls, key: str, default: Any = None) -> Any:
        """
        Retrieve a configuration value by dot-notation path.

        Parameters
        ----------
        key:
            Dot-notation config path (e.g. `"fusion_costs.base"`).
        default:
            Value to return if the key is not found in cache or defaults.

        Returns
        -------
        Any
            The resolved configuration value, or `default` if not present.

        Notes
        -----
        - This method is **read-only** and never touches the database.
        - Time-aware stale detection is performed per read; stale reads are
          counted in metrics and may be inspected via `get_metrics()`.

        Examples
        --------
        >>> base_cost = ConfigManager.get("fusion_costs.base")
        >>> event_boost = ConfigManager.get("event_modifiers.fusion_rate_boost", 0.0)
        """
        start_time = time.perf_counter()
        cls._metrics.gets += 1

        if not cls._initialized:
            # Lazily bootstrap from defaults if we haven't been explicitly initialized.
            logger.warning(
                "ConfigManager accessed before explicit initialization; "
                "falling back to defaults only"
            )
            cls._cache = dict(cls._defaults)
            cls._initialized = True
            cls._metrics.fallback_to_defaults += 1

        try:
            parts = key.split(".")
            value: Any = cls._cache

            for part in parts:
                if isinstance(value, dict):
                    value = value.get(part)
                    if value is None:
                        cls._metrics.cache_misses += 1
                        fallback = cls._get_from_defaults(key)
                        if fallback is not None:
                            cls._metrics.fallback_to_defaults += 1
                            return fallback
                        return default
                else:
                    cls._metrics.cache_misses += 1
                    fallback = cls._get_from_defaults(key)
                    if fallback is not None:
                        cls._metrics.fallback_to_defaults += 1
                        return fallback
                    return default

            cls._metrics.cache_hits += 1

            # Time-aware stale detection.
            if cls.is_stale(key):
                cls._metrics.stale_reads += 1
                logger.debug(
                    "Stale configuration read detected",
                    extra={
                        "config_key": key,
                        "cache_ttl_seconds": cls._cache_ttl_seconds,
                        "cache_age_seconds": cls.get_cache_age(key.split(".")[0]),
                    },
                )

            return value if value is not None else default

        except Exception as exc:
            cls._metrics.errors += 1
            logger.error(
                "Error resolving configuration value",
                extra={
                    "config_key": key,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
            fallback = cls._get_from_defaults(key)
            if fallback is not None:
                cls._metrics.fallback_to_defaults += 1
                return fallback
            return default
        finally:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            cls._metrics.total_get_time_ms += elapsed_ms

    @classmethod
    def get_all_keys(cls) -> List[str]:
        """Return a list of all top-level configuration keys currently in cache."""
        return list(cls._cache.keys())

    @classmethod
    def get_cache_age(cls, key: str) -> Optional[int]:
        """
        Get age of a cached top-level configuration in seconds.

        Parameters
        ----------
        key:
            Top-level configuration key.

        Returns
        -------
        Optional[int]
            Age in seconds, or `None` if the key has never been cached.
        """
        timestamp = cls._cache_timestamps.get(key)
        if not timestamp:
            return None
        return int((datetime.now(timezone.utc) - timestamp).total_seconds())

    # =========================================================================
    # WRITE API
    # =========================================================================

    @classmethod
    async def set(
        cls,
        key: str,
        value: Any,
        modified_by: str = "system",
        emit_event: bool = True,
    ) -> None:
        """
        Atomically update a configuration value in the database and cache.

        This method:
        - Runs inside `DatabaseService.get_transaction()` (no manual commit).
        - Applies pessimistic locking on the underlying `GameConfig` row.
        - Validates nested structure via schemas (top-level) where defined.
        - Applies registered per-key validators for the exact key, if any.
        - Updates the in-memory cache and cache timestamps.
        - Emits a transaction log entry via `TransactionLogger`.
        - Optionally publishes an EventBus event on change.

        Parameters
        ----------
        key:
            Dot-notation configuration path (e.g. `"event_modifiers.fusion_rate_boost"`).
        value:
            New value to persist.
        modified_by:
            Identifier for the actor making the change (e.g. admin id, system).
        emit_event:
            Whether to attempt to publish an EventBus event for this change.
            Subject to the global `_emit_events` flag.

        Raises
        ------
        ConfigWriteError
            If the write fails or validation fails.

        Examples
        --------
        >>> await ConfigManager.set(
        ...     "event_modifiers.fusion_rate_boost",
        ...     0.25,
        ...     modified_by="admin_123",
        ... )
        """
        from src.core.database.service import DatabaseService
        from src.core.infra.transaction_logger import TransactionLogger

        start_time = time.perf_counter()
        cls._metrics.sets += 1

        # Apply per-key validator (for full dot key).
        value_to_persist = cls._apply_validator(key, value)

        parts = key.split(".")
        top_key = parts[0]

        previous_value: Any = None
        final_value: Any

        try:
            # Atomic, pessimistic-locking write.
            async with DatabaseService.get_transaction() as session:
                stmt = (
                    select(GameConfig)
                    .where(GameConfig.config_key == top_key)  # type: ignore[arg-type]
                    .with_for_update()
                )
                result = await session.execute(stmt)
                cfg: Optional[GameConfig] = result.scalar_one_or_none()

                previous_value = cfg.config_value if cfg is not None else None

                # Build nested value if dot-notation is used.
                if len(parts) > 1:
                    base: Dict[str, Any]
                    if isinstance(previous_value, dict):
                        base = dict(previous_value)
                    else:
                        base = {}

                    current: Dict[str, Any] = base
                    for segment in parts[1:-1]:
                        nested = current.get(segment)
                        if not isinstance(nested, dict):
                            nested = {}
                            current[segment] = nested
                        current = nested  # type: ignore[assignment]

                    current[parts[-1]] = value_to_persist
                    final_value = base
                else:
                    final_value = value_to_persist

                # Schema validation for the full top-level payload.
                final_value = cls._apply_schema_validation_for_write(
                    top_key=top_key,
                    final_value=final_value,
                )

                if cfg is None:
                    cfg = GameConfig(
                        config_key=top_key,
                        config_value=final_value,
                        modified_by=modified_by,
                    )
                    session.add(cfg)
                else:
                    cfg.config_value = final_value
                    cfg.modified_by = modified_by
                    cfg.updated_at = datetime.now(timezone.utc)

            # Transaction committed successfully at this point.

            # Update in-memory cache outside of the DB transaction.
            async with cls._cache_lock:
                cls._cache[top_key] = final_value
                cls._cache_timestamps[top_key] = datetime.now(timezone.utc)
                # DB-level TTL override might have changed.
                if top_key == "core":
                    cls._refresh_cache_ttl_from_cache_locked()

            elapsed_ms = (time.perf_counter() - start_time) * 1000
            cls._metrics.total_set_time_ms += elapsed_ms

            logger.info(
                "Configuration updated",
                extra={
                    "config_key": key,
                    "top_level_key": top_key,
                    "modified_by": modified_by,
                    "latency_ms": round(elapsed_ms, 2),
                },
            )

            # Best-effort transaction log; failure here must not break writes.
            try:
                await TransactionLogger.log_transaction(
                    player_id=0,  # System transaction (no player)
                    transaction_type="config_change",
                    details={
                        "config_key": key,
                        "top_level_key": top_key,
                        "previous_value": previous_value,
                        "new_value": final_value,
                        "latency_ms": round(elapsed_ms, 2),
                    },
                    context="ConfigManager",
                    meta={"modified_by": modified_by},
                )
            except Exception as log_exc:
                cls._metrics.errors += 1
                logger.error(
                    "Failed to emit config change transaction log",
                    extra={
                        "config_key": key,
                        "error": str(log_exc),
                        "error_type": type(log_exc).__name__,
                    },
                    exc_info=True,
                )

            # Optional EventBus publish.
            if emit_event and cls._emit_events:
                try:
                    from src.core.event import event_bus

                    await event_bus.publish(
                        "config.changed",
                        {
                            "config_key": key,
                            "top_level_key": top_key,
                            "previous_value": previous_value,
                            "new_value": final_value,
                            "modified_by": modified_by,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "latency_ms": round(elapsed_ms, 2),
                        },
                    )
                except Exception as event_exc:
                    cls._metrics.errors += 1
                    logger.error(
                        "Failed to publish config change event",
                        extra={
                            "config_key": key,
                            "error": str(event_exc),
                            "error_type": type(event_exc).__name__,
                        },
                        exc_info=True,
                    )

        except ConfigWriteError:
            # Validation failures already logged and wrapped.
            raise
        except Exception as exc:
            cls._metrics.errors += 1
            logger.error(
                "Config update failed",
                extra={
                    "config_key": key,
                    "modified_by": modified_by,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
            raise ConfigWriteError(f"Failed to update config '{key}'") from exc

    # =========================================================================
    # CACHE CONTROL & METRICS
    # =========================================================================

    @classmethod
    def clear_cache(cls) -> None:
        """
        Clear the in-memory cache and reset initialization status.

        Intended for testing and controlled maintenance operations.
        """
        cls._cache.clear()
        cls._cache_timestamps.clear()
        cls._initialized = False
        logger.info("ConfigManager cache cleared")

    @classmethod
    async def get_metrics(cls) -> Dict[str, Any]:
        """
        Return a snapshot of ConfigManager performance metrics.

        Returns
        -------
        Dict[str, Any]
            Metrics including cache hit rate, stale reads, and average latencies.

        Examples
        --------
        >>> metrics = await ConfigManager.get_metrics()
        >>> metrics["cache_hit_rate"]
        >>> metrics["avg_get_time_ms"]
        >>> metrics["stale_reads"]
        """
        return await get_metrics_snapshot(
            metrics=cls._metrics,
            initialized=cls._initialized,
            cached_configs=len(cls._cache),
            cache_ttl_seconds=cls._cache_ttl_seconds,
        )

    @classmethod
    async def reset_metrics(cls) -> None:
        """Reset all metrics counters to zero."""
        await cls._metrics.reset()
        logger.info("ConfigManager metrics reset")

    @classmethod
    def health_snapshot(cls) -> Dict[str, Any]:
        """
        Return a compact health snapshot suitable for infra dashboards.

        Includes:
        - initialization status
        - background task status
        - cache size
        - recent error count
        - refresh count
        - current TTL
        """
        refresh_running = cls._refresh_task is not None and not cls._refresh_task.done()
        return get_health_snapshot(
            initialized=cls._initialized,
            background_refresh_running=refresh_running,
            cached_configs=len(cls._cache),
            errors=cls._metrics.errors,
            refresh_count=cls._metrics.refresh_count,
            cache_ttl_seconds=cls._cache_ttl_seconds,
        )
