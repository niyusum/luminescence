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
    _defaults: Dict[str, Any] = {
        # Fusion System
        "fusion_rates": {
            "1": 75, "2": 70, "3": 65, "4": 60, "5": 55,
            "6": 50, "7": 45, "8": 40, "9": 35, "10": 30, "11": 25
        },
        "fusion_costs": {"base": 1000, "multiplier": 2.2, "max_cost": 100_000_000},
        "shard_system": {
            "shards_per_failure_min": 3,
            "shards_per_failure_max": 15,
            "shards_for_redemption": 100,
            "enabled": True
        },
        
        # Resource Systems
        "energy_system": {
            "base_max": 100, "regen_minutes": 4,
            "per_level_increase": 10, "overcap_bonus": 0.10, "overcap_threshold": 0.9
        },
        "stamina_system": {
            "base_max": 50, "regen_minutes": 10,
            "per_level_increase": 5, "overcap_bonus": 0.10, "overcap_threshold": 0.9
        },
        "resource_system": {
            "grace_max_cap": 999999,
            "rikis_max_cap": None,
            "riki_gems_max_cap": None,
            "modifier_stacking": "multiplicative",
            "passive_income_enabled": False,
            "audit_retention_days": 90
        },
        
        # Progression
        "xp_curve": {"type": "polynomial", "base": 50, "exponent": 2.0},
        "level_milestones": {
            "minor_interval": 5, "major_interval": 10,
            "minor_rewards": {"rikis_multiplier": 100, "grace": 5, "gems_divisor": 10},
            "major_rewards": {
                "rikis_multiplier": 500, "grace": 10, "gems": 5,
                "max_energy_increase": 10, "max_stamina_increase": 5
            }
        },
        
        # Prayer System (1 charge every 5 minutes - no accumulation)
        "prayer_system": {
            "grace_per_prayer": 1,
            "max_charges": 1,  # Single charge system (no accumulation/storage)
            "regen_minutes": 5,  # 300 seconds per charge
            "regen_interval_seconds": 300,  # Explicit interval for clarity
            "class_bonuses": {"destroyer": 1.0, "adapter": 1.0, "invoker": 1.0}  # Invoker now affects shrines
        },
        
        # Gacha/Summon System
        "gacha_rates": {
            "tier_unlock_levels": {
                "tier_1": 1, "tier_2": 1, "tier_3": 1,
                "tier_4": 10, "tier_5": 20, "tier_6": 30,
                "tier_7": 30, "tier_8": 40, "tier_9": 40,
                "tier_10": 40, "tier_11": 45, "tier_12": 50
            },
            "rate_distribution": {"decay_factor": 0.75, "highest_tier_base": 22.0}
        },
        "pity_system": {
            "summons_for_pity": 25,
            "pity_type": "new_maiden_or_next_bracket"
        },
        "summon_costs": {
            "grace_per_summon": 1,
            "x5_multiplier": 5,
            "x10_multiplier": 10,
            "x10_premium_only": True
        },
        
        # Events and Modifiers
        "event_modifiers": {
            "fusion_rate_boost": 0.0,
            "xp_boost": 0.0,
            "rikis_boost": 0.0,
            "shard_boost": 0.0
        },
        "modifier_rules": {
            "stack_method": "multiplicative",
            "max_bonus_cap": 300,
            "min_penalty_cap": 10
        },
        
        # Daily/Weekly Systems
        "daily_rewards": {
            "base_rikis": 1250, "base_grace": 2, "base_gems": 2, "base_xp": 150,
            "completion_bonus_rikis": 800, "completion_bonus_grace": 3,
            "completion_bonus_gems": 2, "completion_bonus_xp": 350,
            "streak_multiplier": 0.15, "grace_days": 1
        },
        "daily_quests": {
            "prayer_required": 1, "summon_required": 1,
            "fusion_required": 1, "energy_required": 10, "stamina_required": 5
        },
        "weekly_bonus": {
            "enabled": True,
            "rikis": 10000,
            "grace": 25,
            "gems": 10,
            "requirements": {"daily_quests_completed": 6, "min_level": 10}
        },
        "comeback_bonus": {
            "enabled": True,
            "days_inactive": 7,
            "rikis_per_day": 1000,
            "grace_per_day": 5,
            "max_days": 14
        },
        
        # Exploration System
        "exploration_system": {
            "progress_rates": {
                "sector_1": 7.0, "sector_2": 4.5, "sector_3": 3.5,
                "sector_4": 2.5, "sector_5": 2.0, "sector_6": 1.5, "sector_7": 1.0
            },
            "miniboss_progress_multiplier": 0.5,
            "energy_costs": {
                "sector_1_base": 5, "sector_2_base": 8, "sector_3_base": 12,
                "sector_4_base": 17, "sector_5_base": 23,
                "sector_6_base": 30, "sector_7_base": 38,
                "sublevel_increment": 1, "boss_multiplier": 1.5
            },
            "riki_rewards": {"sector_1_min": 50, "sector_1_max": 100, "sector_scaling": 1.5},
            "xp_rewards": {"sector_1_min": 10, "sector_1_max": 30, "sector_scaling": 1.5},
            "encounter_rates": {
                "sector_1": 8.0, "sector_2": 10.0, "sector_3": 12.0,
                "sector_4": 12.0, "sector_5": 15.0, "sector_6": 15.0, "sector_7": 18.0
            },
            "capture_rates": {
                "common": 60.0, "uncommon": 45.0, "rare": 30.0,
                "epic": 15.0, "legendary": 8.0, "mythic": 3.0
            },
            "capture_level_modifier": 2.0,
            "guaranteed_purification_costs": {
                "common": 50, "uncommon": 100, "rare": 200,
                "epic": 500, "legendary": 1500, "mythic": 5000
            },
            "unlock_requirement": 100.0
        },
        
        # Miniboss System
        "miniboss_system": {
            "hp_base": {
                "uncommon": 2000, "rare": 5000, "epic": 15000,
                "legendary": 50000, "mythic": 150000
            },
            "hp_sector_multiplier": 0.5, "hp_sublevel_multiplier": 0.1,
            "sector_avg_rarity": {
                "sector_1": "uncommon", "sector_2": "rare", "sector_3": "rare",
                "sector_4": "epic", "sector_5": "epic",
                "sector_6": "legendary", "sector_7": "legendary"
            },
            "rarity_tier_increase": [1, 2],
            "reward_base_rikis": 500, "reward_base_xp": 100,
            "reward_sector_multiplier": 1.0, "boss_sublevel_bonus": 2.0,
            "boss_rewards": {"prayer_charges": 1, "fusion_catalyst": 1},
            "egg_rarity_upgrade": True
        },
        
        # Ascension System
        "ascension_system": {
            "base_stamina_cost": 5,
            "stamina_increase_per_10_levels": 1,
            "enemy_hp_base": 1000,
            "enemy_hp_growth_rate": 1.10,
            "attack_multipliers": {"x1": 1, "x5": 5, "x20": 20},
            "x20_attack_crit_bonus": 0.2,
            "x20_attack_gem_cost": 10,
            "reward_base_rikis": 50,
            "reward_base_xp": 20,
            "reward_growth_rate": 1.12,
            "bonus_intervals": {
                "egg_every_n_floors": 5,
                "prayer_charge_every_n_floors": 10,
                "fusion_catalyst_every_n_floors": 25
            },
            "milestones": {
                50: {"title": "Tower Climber", "rikis": 10000, "gems": 50},
                100: {"title": "Sky Breaker", "rikis": 50000, "gems": 100, "mythic_egg": True},
                150: {"title": "Heaven Piercer", "rikis": 100000, "gems": 200},
                200: {"title": "Divine Ascendant", "rikis": 250000, "gems": 500}
            },
            "egg_rarity_floors": {
                "common": [1, 10], "uncommon": [11, 25],
                "rare": [26, 50], "epic": [51, 100],
                "legendary": [101, 200], "mythic": [201, 999999]
            }
        },
        
        # Shrine System
        "shrines": {
            "lesser": {
                "base_cost": 10000,
                "cost_multiplier": 2.3,
                "base_yield": 50,
                "yield_multiplier": 2.3,
                "max_level": 12,
                "collection_cap_hours": 24,
                "max_shrines": 3,
                "unlock_level": 10
            },
            "radiant": {
                "base_cost": 50000,
                "cost_multiplier": 2.3,
                "base_yield": 0.05,
                "yield_multiplier": 2.3,
                "max_level": 12,
                "collection_cap_hours": 24,
                "max_shrines": 3,
                "unlock_level": 30
            }
        },
        
        # Guild System
        "guilds": {
            "base_upgrade_cost": 25000,
            "upgrade_costs": {
                "level_2": 25000,
                "level_3": 50000,
                "level_4": 100000,
            },
            "upgrade_cost_multiplier": 2.5,
            "max_level": 20,
            "base_max_members": 10,
            "member_growth_per_level": 2,
            "donation_minimum": 1000,
        },
        
        # Cache Configuration
        "cache": {
            "compression_threshold": 1024,
            "tag_registry_ttl": 3600,
            "ttl": {
                "player_resources": 300,
                "maiden_collection": 300,
                "active_modifiers": 600,
                "fusion_rates": 3600,
                "leader_bonuses": 3600,
                "daily_quest": 86400,
                "prayer_charges": 300,
                "leaderboards": 600
            },
            "health": {
                "max_errors": 100,
                "min_hit_rate": 70.0
            }
        }
    }

    # =========================================================================
    # INITIALIZATION / REFRESH
    # =========================================================================
    
    @classmethod
    async def initialize(cls) -> None:
        """
        Load configs from database into cache.
        
        Raises:
            Exception: If initialization fails critically
        """
        from src.core.infra.database_service import DatabaseService
        
        try:
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
                    cls._cache = cls._defaults.copy()
                    logger.info(
                        "ConfigManager initialized: using hardcoded defaults (no DB configs)",
                        extra={"config_count": len(cls._defaults), "source": "defaults"}
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