from typing import Any, Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
import asyncio

from src.database.models.core.game_config import GameConfig
from src.core.logger import get_logger

logger = get_logger(__name__)


class ConfigManager:
    """
    Dynamic game configuration management with database backing and caching.

    Provides hierarchical config access using dot notation (e.g., 'fusion_costs.base').
    Cached in memory with TTL and periodically refreshed.
    Allows live balance changes without redeploy (RIKI LAW Article I.4).

    SECURITY NOTE - SQL Injection Prevention:
    ==========================================
    All database queries in this module use SQLAlchemy's parameterized queries,
    which automatically prevent SQL injection attacks. Example (line 340):

        ✅ SAFE: select(GameConfig).where(GameConfig.config_key == top_key)
        ❌ NEVER DO: f"SELECT * FROM game_config WHERE config_key = '{top_key}'"

    IMPORTANT FOR DEVELOPERS:
    - NEVER use string interpolation (f-strings, %) for SQL queries
    - ALWAYS use SQLAlchemy's query builders or parameterized queries
    - If you need raw SQL, use session.execute(text(sql), {"param": value})
    - All user input must be treated as untrusted and parameterized

    This applies to ALL database operations across the entire codebase.
    """

    _cache: Dict[str, Any] = {}
    _cache_timestamps: Dict[str, datetime] = {}
    _initialized: bool = False
    _cache_ttl: int = 300
    _refresh_task: Optional[asyncio.Task] = None

    # =========================================================================
    # DEFAULT CONFIGURATIONS
    # =========================================================================
    _defaults: Dict[str, Any] = {
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
        "energy_system": {
            "base_max": 100, "regen_minutes": 4,
            "per_level_increase": 10, "overcap_bonus": 0.10, "overcap_threshold": 0.9
        },
        "stamina_system": {
            "base_max": 50, "regen_minutes": 10,
            "per_level_increase": 5, "overcap_bonus": 0.10, "overcap_threshold": 0.9
        },
        "xp_curve": {"type": "polynomial", "base": 50, "exponent": 2.0},
        "level_milestones": {
            "minor_interval": 5, "major_interval": 10,
            "minor_rewards": {"rikis_multiplier": 100, "grace": 5, "gems_divisor": 10},
            "major_rewards": {
                "rikis_multiplier": 500, "grace": 10, "gems": 5,
                "max_energy_increase": 10, "max_stamina_increase": 5
            }
        },
        "prayer_system": {
            "grace_per_prayer": 1,
            "max_charges": 5,
            "regen_minutes": 5,
            "class_bonuses": {"destroyer": 1.0, "adapter": 1.0, "invoker": 1.2}
        },
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
        "event_modifiers": {
            "fusion_rate_boost": 0.0,
            "xp_boost": 0.0,
            "rikis_boost": 0.0,
            "shard_boost": 0.0
        },
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
        "element_combinations": {
            "infernal|infernal": "infernal", "infernal|abyssal": "umbral",
            "infernal|tempest": "radiant", "infernal|earth": "tempest",
            "infernal|radiant": "earth", "infernal|umbral": "abyssal",
            "abyssal|abyssal": "abyssal", "abyssal|tempest": "earth",
            "abyssal|earth": "umbral", "abyssal|radiant": "tempest",
            "abyssal|umbral": "infernal", "tempest|tempest": "tempest",
            "tempest|earth": "radiant", "tempest|radiant": "umbral",
            "tempest|umbral": "abyssal", "earth|earth": "earth",
            "earth|radiant": "abyssal", "earth|umbral": "tempest",
            "radiant|radiant": "radiant", "radiant|umbral": "infernal",
            "umbral|umbral": "umbral"
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
        "resource_system": {
            "grace_max_cap": 999999,
            "rikis_max_cap": None,
            "riki_gems_max_cap": None,
            "modifier_stacking": "multiplicative",
            "passive_income_enabled": False,
            "audit_retention_days": 90
        },
        "modifier_rules": {
            "stack_method": "multiplicative",
            "max_bonus_cap": 300,
            "min_penalty_cap": 10
        },
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
        },
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
            }
        }
    }

    # =========================================================================
    # INITIALIZATION / REFRESH
    # =========================================================================
    @classmethod
    async def initialize(cls, session: AsyncSession) -> None:
        """Load configs from DB into cache."""
        try:
            result = await session.execute(select(GameConfig))
            configs = result.scalars().all()

            if configs:
                for cfg in configs:
                    cls._cache[cfg.config_key] = cfg.config_value
                    cls._cache_timestamps[cfg.config_key] = datetime.utcnow()
                logger.info(f"ConfigManager initialized with {len(configs)} DB configs")
            else:
                cls._cache = cls._defaults.copy()
                logger.info("ConfigManager initialized with hardcoded defaults")

            cls._initialized = True
            if cls._refresh_task is None:
                cls._refresh_task = asyncio.create_task(cls._background_refresh())
        except Exception as e:
            logger.error(f"Failed to initialize ConfigManager: {e}")
            cls._cache = cls._defaults.copy()
            cls._initialized = True
            raise

    @classmethod
    async def _background_refresh(cls) -> None:
        """Periodically refresh configs from DB."""
        from src.core.database_service import DatabaseService
        while True:
            try:
                await asyncio.sleep(cls._cache_ttl)
                async with DatabaseService.get_session() as session:
                    result = await session.execute(select(GameConfig))
                    configs = result.scalars().all()
                    for cfg in configs:
                        cls._cache[cfg.config_key] = cfg.config_value
                        cls._cache_timestamps[cfg.config_key] = datetime.utcnow()
                    logger.debug(f"ConfigManager cache refreshed ({len(configs)} entries)")
            except asyncio.CancelledError:
                logger.info("ConfigManager background refresh cancelled")
                break
            except Exception as e:
                logger.error(f"ConfigManager background refresh error: {e}")

    # =========================================================================
    # PUBLIC METHODS
    # =========================================================================
    @classmethod
    def get(cls, key: str, default: Any = None) -> Any:
        """Retrieve config value by dot path."""
        if not cls._initialized:
            logger.warning("ConfigManager not initialized, using defaults")
            cls._cache = cls._defaults.copy()
            cls._initialized = True
        keys = key.split(".")
        value = cls._cache
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
                if value is None:
                    return cls._get_from_defaults(key) or default
            else:
                return cls._get_from_defaults(key) or default
        return value if value is not None else default

    @classmethod
    def _get_from_defaults(cls, key: str) -> Any:
        """Traverse default dict using dot notation."""
        value = cls._defaults
        for k in key.split("."):
            if isinstance(value, dict):
                value = value.get(k)
                if value is None:
                    return None
            else:
                return None
        return value

    @classmethod
    async def set(cls, session: AsyncSession, key: str, value: Any, modified_by: str = "system") -> None:
        """Update config in DB and cache."""
        try:
            keys = key.split(".")
            top_key = keys[0]
            result = await session.execute(select(GameConfig).where(GameConfig.config_key == top_key))
            cfg = result.scalar_one_or_none()

            if len(keys) > 1:
                data = cfg.config_value.copy() if cfg else {}
                current = data
                for k in keys[1:-1]:
                    current = current.setdefault(k, {})
                current[keys[-1]] = value
                final_value = data
            else:
                final_value = value

            if cfg:
                cfg.config_value = final_value
                cfg.modified_by = modified_by
                cfg.last_modified = datetime.utcnow()
            else:
                cfg = GameConfig(config_key=top_key, config_value=final_value, modified_by=modified_by)
                session.add(cfg)

            await session.commit()
            cls._cache[top_key] = final_value
            cls._cache_timestamps[top_key] = datetime.utcnow()
            logger.info(f"ConfigManager updated: {key} by {modified_by}")

        except Exception as e:
            logger.error(f"Failed to update config {key}: {e}")
            await session.rollback()
            raise

    @classmethod
    def clear_cache(cls) -> None:
        """Clear memory cache and reset initialization state."""
        cls._cache.clear()
        cls._cache_timestamps.clear()
        cls._initialized = False
        logger.info("ConfigManager cache cleared")
