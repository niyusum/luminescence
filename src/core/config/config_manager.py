"""
Dynamic game configuration management with database backing and caching.

Features:
- Hierarchical config access with dot notation (e.g., 'fusion_costs.base')
- In-memory caching with TTL and background refresh
- Hot-reload support for live balance changes
- Config validation and type checking
- Audit trail for all config changes
- Performance metrics tracking

RIKI LAW Compliance:
- Live config changes without redeploy (Article IV)
- Audit trails for all modifications (Article II)
- Graceful degradation to defaults (Article IX)
- Performance metrics and monitoring (Article X)

Security:
- All queries use parameterized SQLAlchemy statements
- No string interpolation in SQL queries
- User input treated as untrusted

Note:
- Element fusion combinations moved to maiden_constants.py (single source of truth)
- ConfigManager handles only tunable game balance values
"""

from typing import Any, Dict, Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
import asyncio
import time
from pathlib import Path
import yaml

from src.database.models.core.game_config import GameConfig
from src.core.logging.logger import get_logger

logger = get_logger(__name__)


class ConfigManager:
    """
    Dynamic game configuration management with database backing and caching.

    Provides hierarchical config access using dot notation (e.g., 'fusion_costs.base').
    Cached in memory with TTL and periodically refreshed.
    Allows live balance changes without redeploy (RIKI LAW Article IV).
    """

    _cache: Dict[str, Any] = {}
    _cache_timestamps: Dict[str, datetime] = {}
    _initialized: bool = False
    _cache_ttl: int = 300
    _refresh_task: Optional[asyncio.Task] = None
    
    # Metrics tracking
    _metrics = {
        "gets": 0,
        "sets": 0,
        "cache_hits": 0,
        "cache_misses": 0,
        "fallback_to_defaults": 0,
        "refresh_count": 0,
        "errors": 0,
        "total_get_time_ms": 0.0,
        "total_set_time_ms": 0.0,
    }

    # =========================================================================
    # DEFAULT CONFIGURATIONS
    # =========================================================================
    # RIKI LAW I.6: All game parameters MUST be externalized to YAML files.
    # This dict contains ONLY infrastructure defaults (fallback values).
    # Game balance parameters are loaded from config/ directory YAML files.
    _defaults: Dict[str, Any] = {}

    # =========================================================================
    # INITIALIZATION / REFRESH
    # =========================================================================

    @classmethod
    def _load_yaml_configs(cls) -> None:
        """
        Recursively load all YAML config files from config/ directory into cache.

        RIKI LAW I.6: All game parameters externalized to YAML files.
        Files are merged into _defaults first, then copied to _cache.
        Supports nested directory structure (e.g., config/fusion/rates.yaml).
        Gracefully handles missing yaml library or config files.
        """
        try:
            config_dir = Path("config")
            if not config_dir.exists():
                logger.warning("config/ directory not found, skipping YAML loading")
                return

            # Recursively find all YAML files in config/ and subdirectories
            yaml_files = list(config_dir.rglob("*.yaml")) + list(config_dir.rglob("*.yml"))
            if not yaml_files:
                logger.info("No YAML config files found in config/")
                return

            loaded_count = 0
            for yaml_file in yaml_files:
                try:
                    with open(yaml_file, 'r', encoding='utf-8') as f:
                        data = yaml.safe_load(f)
                        if data:
                            # Merge into defaults (preserves existing defaults)
                            cls._defaults.update(data)
                            loaded_count += 1
                            logger.debug(f"Loaded YAML config: {yaml_file.relative_to(config_dir)}")
                except Exception as e:
                    logger.warning(
                        f"Failed to load YAML config {yaml_file.relative_to(config_dir)}: {e}",
                        extra={"file": str(yaml_file), "error": str(e)}
                    )

            # Copy merged defaults to cache
            cls._cache = cls._defaults.copy()

            logger.info(
                f"Loaded {loaded_count} YAML config files from config/",
                extra={"yaml_count": loaded_count, "total_keys": len(cls._cache)}
            )

        except ImportError:
            logger.warning(
                "PyYAML not installed, skipping YAML config loading. "
                "Install with: pip install pyyaml"
            )
        except Exception as e:
            logger.error(
                f"Error loading YAML configs: {e}",
                extra={"error_type": type(e).__name__},
                exc_info=True
            )

    @classmethod
    async def initialize(cls) -> None:
        """
        Load configs from YAML files and database into cache.

        YAML files in config/ directory are loaded first, then merged with database configs.
        Database configs take precedence over YAML configs.

        Raises:
            Exception: If initialization fails critically
        """
        from src.core.infra.database_service import DatabaseService

        try:
            # Step 1: Load YAML configs from config/ directory
            cls._load_yaml_configs()

            # Step 2: Load database configs (overrides YAML)
            async with DatabaseService.get_session() as session:
                result = await session.execute(select(GameConfig))
                configs = result.scalars().all()

                if configs:
                    for cfg in configs:
                        cls._cache[cfg.config_key] = cfg.config_value
                        cls._cache_timestamps[cfg.config_key] = datetime.utcnow()
                    logger.info(
                        f"ConfigManager initialized: loaded {len(configs)} configs from database",
                        extra={"config_count": len(configs), "source": "database"}
                    )
                else:
                    # No DB configs, use defaults + YAML
                    if not cls._cache:
                        cls._cache = cls._defaults.copy()
                    logger.info(
                        "ConfigManager initialized: using defaults + YAML (no DB configs)",
                        extra={"config_count": len(cls._cache), "source": "defaults+yaml"}
                    )

                cls._initialized = True

                # Start background refresh task
                if cls._refresh_task is None:
                    cls._refresh_task = asyncio.create_task(cls._background_refresh())
                    logger.info(f"ConfigManager background refresh started (ttl={cls._cache_ttl}s)")

        except Exception as e:
            cls._metrics["errors"] += 1
            logger.error(
                f"Failed to initialize ConfigManager: {e}",
                extra={"error_type": type(e).__name__},
                exc_info=True
            )
            # Fallback to defaults to keep system running
            cls._cache = cls._defaults.copy()
            cls._initialized = True
            raise

    @classmethod
    async def _background_refresh(cls) -> None:
        """Periodically refresh configs from database."""
        from src.core.infra.database_service import DatabaseService
        
        while True:
            try:
                await asyncio.sleep(cls._cache_ttl)
                
                async with DatabaseService.get_session() as session:
                    result = await session.execute(select(GameConfig))
                    configs = result.scalars().all()
                    
                    for cfg in configs:
                        cls._cache[cfg.config_key] = cfg.config_value
                        cls._cache_timestamps[cfg.config_key] = datetime.utcnow()
                    
                    cls._metrics["refresh_count"] += 1
                    
                    logger.debug(
                        f"ConfigManager cache refreshed ({len(configs)} configs)",
                        extra={"config_count": len(configs), "refresh_count": cls._metrics["refresh_count"]}
                    )
                    
            except asyncio.CancelledError:
                logger.info("ConfigManager background refresh cancelled")
                break
            except Exception as e:
                cls._metrics["errors"] += 1
                logger.error(f"ConfigManager background refresh error: {e}", exc_info=True)

    @classmethod
    async def shutdown(cls) -> None:
        """Stop background refresh task and cleanup resources."""
        if cls._refresh_task:
            cls._refresh_task.cancel()
            try:
                await cls._refresh_task
            except asyncio.CancelledError:
                pass
            cls._refresh_task = None
            logger.info("ConfigManager shutdown complete")

    # =========================================================================
    # PUBLIC METHODS
    # =========================================================================
    
    @classmethod
    def get(cls, key: str, default: Any = None) -> Any:
        """
        Retrieve config value by dot notation path.
        
        Args:
            key: Dot-notation config path (e.g., 'fusion_costs.base')
            default: Default value if key not found
        
        Returns:
            Config value or default
        
        Example:
            >>> base_cost = ConfigManager.get('fusion_costs.base')
            >>> # 1000
            >>> 
            >>> event_boost = ConfigManager.get('event_modifiers.fusion_rate_boost', 0.0)
            >>> # 0.0
        """
        start_time = time.perf_counter()
        cls._metrics["gets"] += 1
        
        if not cls._initialized:
            logger.warning("ConfigManager not initialized, using defaults")
            cls._cache = cls._defaults.copy()
            cls._initialized = True
            cls._metrics["fallback_to_defaults"] += 1
        
        try:
            keys = key.split(".")
            value = cls._cache
            
            for k in keys:
                if isinstance(value, dict):
                    value = value.get(k)
                    if value is None:
                        cls._metrics["cache_misses"] += 1
                        fallback = cls._get_from_defaults(key)
                        if fallback is not None:
                            cls._metrics["fallback_to_defaults"] += 1
                        return fallback or default
                else:
                    cls._metrics["cache_misses"] += 1
                    fallback = cls._get_from_defaults(key)
                    if fallback is not None:
                        cls._metrics["fallback_to_defaults"] += 1
                    return fallback or default
            
            cls._metrics["cache_hits"] += 1
            
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            cls._metrics["total_get_time_ms"] += elapsed_ms
            
            return value if value is not None else default
            
        except Exception as e:
            cls._metrics["errors"] += 1
            logger.error(
                f"Error getting config: key={key} error={e}",
                extra={"config_key": key},
                exc_info=True
            )
            return cls._get_from_defaults(key) or default

    @classmethod
    def _get_from_defaults(cls, key: str) -> Any:
        """Traverse default dict using dot notation."""
        try:
            value = cls._defaults
            for k in key.split("."):
                if isinstance(value, dict):
                    value = value.get(k)
                    if value is None:
                        return None
                else:
                    return None
            return value
        except Exception:
            return None

    @classmethod
    async def set(
        cls,
        session: AsyncSession,
        key: str,
        value: Any,
        modified_by: str = "system"
    ) -> None:
        """
        Update config in database and cache.
        
        Args:
            session: Database session (must be in transaction)
            key: Dot-notation config path
            value: New value to set
            modified_by: Identifier of who made the change
        
        Raises:
            Exception: If update fails
        
        Example:
            >>> async with DatabaseService.get_transaction() as session:
            ...     await ConfigManager.set(
            ...         session,
            ...         'event_modifiers.fusion_rate_boost',
            ...         0.25,
            ...         modified_by='admin_123'
            ...     )
        """
        start_time = time.perf_counter()
        cls._metrics["sets"] += 1
        
        try:
            keys = key.split(".")
            top_key = keys[0]
            
            # Query using parameterized SQLAlchemy (SQL injection safe)
            result = await session.execute(
                select(GameConfig).where(GameConfig.config_key == top_key)
            )
            cfg = result.scalar_one_or_none()

            # Build nested value if dot notation used
            if len(keys) > 1:
                data = cfg.config_value.copy() if cfg else {}
                current = data
                for k in keys[1:-1]:
                    current = current.setdefault(k, {})
                current[keys[-1]] = value
                final_value = data
            else:
                final_value = value

            # Update or create config entry
            if cfg:
                cfg.config_value = final_value
                cfg.modified_by = modified_by
                cfg.last_modified = datetime.utcnow()
            else:
                cfg = GameConfig(
                    config_key=top_key,
                    config_value=final_value,
                    modified_by=modified_by
                )
                session.add(cfg)

            await session.commit()
            
            # Update cache
            cls._cache[top_key] = final_value
            cls._cache_timestamps[top_key] = datetime.utcnow()
            
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            cls._metrics["total_set_time_ms"] += elapsed_ms
            
            logger.info(
                f"ConfigManager updated: key={key} by={modified_by}",
                extra={
                    "config_key": key,
                    "modified_by": modified_by,
                    "set_time_ms": round(elapsed_ms, 2)
                }
            )

        except Exception as e:
            cls._metrics["errors"] += 1
            logger.error(
                f"Failed to update config: key={key} error={e}",
                extra={"config_key": key, "modified_by": modified_by},
                exc_info=True
            )
            await session.rollback()
            raise

    @classmethod
    def clear_cache(cls) -> None:
        """Clear memory cache and reset initialization state."""
        cls._cache.clear()
        cls._cache_timestamps.clear()
        cls._initialized = False
        logger.info("ConfigManager cache cleared")

    @classmethod
    def get_all_keys(cls) -> List[str]:
        """Get list of all top-level config keys."""
        return list(cls._cache.keys())

    @classmethod
    def get_cache_age(cls, key: str) -> Optional[int]:
        """
        Get age of cached config in seconds.
        
        Args:
            key: Top-level config key
        
        Returns:
            Age in seconds, or None if not cached
        """
        timestamp = cls._cache_timestamps.get(key)
        if timestamp:
            return int((datetime.utcnow() - timestamp).total_seconds())
        return None

    # =========================================================================
    # METRICS & MONITORING
    # =========================================================================
    
    @classmethod
    def get_metrics(cls) -> Dict[str, Any]:
        """
        Get ConfigManager performance metrics.
        
        Returns:
            Dictionary with operation counts, cache stats, timing
        
        Example:
            >>> metrics = ConfigManager.get_metrics()
            >>> print(f"Cache hit rate: {metrics['cache_hit_rate']:.1f}%")
            >>> print(f"Avg get time: {metrics['avg_get_time_ms']:.2f}ms")
        """
        total_gets = cls._metrics["gets"]
        cache_hit_rate = (
            (cls._metrics["cache_hits"] / total_gets * 100)
            if total_gets > 0 else 0.0
        )
        
        avg_get_time = (
            cls._metrics["total_get_time_ms"] / total_gets
            if total_gets > 0 else 0.0
        )
        
        avg_set_time = (
            cls._metrics["total_set_time_ms"] / cls._metrics["sets"]
            if cls._metrics["sets"] > 0 else 0.0
        )
        
        return {
            "gets": cls._metrics["gets"],
            "sets": cls._metrics["sets"],
            "cache_hits": cls._metrics["cache_hits"],
            "cache_misses": cls._metrics["cache_misses"],
            "cache_hit_rate": round(cache_hit_rate, 2),
            "fallback_to_defaults": cls._metrics["fallback_to_defaults"],
            "refresh_count": cls._metrics["refresh_count"],
            "errors": cls._metrics["errors"],
            "avg_get_time_ms": round(avg_get_time, 2),
            "avg_set_time_ms": round(avg_set_time, 2),
            "initialized": cls._initialized,
            "cached_configs": len(cls._cache),
        }
    
    @classmethod
    def reset_metrics(cls) -> None:
        """Reset all metrics counters."""
        cls._metrics = {
            "gets": 0,
            "sets": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "fallback_to_defaults": 0,
            "refresh_count": 0,
            "errors": 0,
            "total_get_time_ms": 0.0,
            "total_set_time_ms": 0.0,
        }
        logger.info("ConfigManager metrics reset")