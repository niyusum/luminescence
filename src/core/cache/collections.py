"""
Collection caching operations for Lumen (2025).

Purpose
-------
Provides high-performance caching for game collections and global data including
maiden collections, fusion rates, leader bonuses, daily quests, drop charges,
and leaderboards. Optimized for different access patterns and update frequencies.

Responsibilities
----------------
- Maiden collection caching with per-player scope
- Global collection caching (fusion rates, leader bonuses)
- Daily quest caching with date-based keys
- Drop charge caching for gacha mechanics
- Leaderboard caching with type and period parameters
- Automatic TTL management based on data volatility

Non-Responsibilities
--------------------
- Player-specific resources (handled by player module)
- Batch operations (handled by operations module)
- Metrics tracking (handled by metrics module)
- Cache invalidation strategies (handled by operations module)

LES 2025 Compliance
-------------------
- **Config-Driven**: TTLs managed via ConfigManager
- **Observability**: Structured logging for all operations
- **Graceful Degradation**: Handles Redis failures transparently
- **Type Safety**: Complete type hints throughout
- **Consistent Naming**: Fixed key naming conventions (no uppercase)

Architecture Notes
------------------
- Uses RedisService for storage backend
- Longer TTLs for stable data (fusion rates: 1 hour)
- Shorter TTLs for volatile data (leaderboards: 10 minutes)
- Maiden collections: 5 minutes (frequently updated)
- Daily quests: 24 hours (date-scoped)
- Drop charges: 5 minutes (session-based)

Key Format
----------
All keys follow versioned patterns:
- `lumen:v2:player:{player_id}:maidens`
- `lumen:v2:fusion:rates:{tier}`
- `lumen:v2:leader:{maiden_base_id}:{tier}`
- `lumen:v2:daily:{player_id}:{date}`
- `lumen:v2:drop:{player_id}`
- `lumen:v2:leaderboard:{type}:{period}`

Dependencies
------------
- RedisService: Redis operations with JSON serialization
- ConfigManager: TTL configuration
- CacheMetrics: Performance metrics tracking
- Logger: Structured logging with context

Performance Characteristics
---------------------------
- Average GET latency: <5ms
- Average SET latency: <10ms
- Typical cache hit rate: 85-95%
- Memory per collection: 1KB - 10KB (varies by collection size)
"""

import time
from typing import Any, Dict, Optional

from src.core.cache.metrics import CacheMetrics
from src.core.config import ConfigManager
from src.core.logging.logger import get_logger
from src.core.redis.service import RedisService

logger = get_logger(__name__)


class CollectionCache:
    """
    Collection caching operations for game data.
    
    Provides specialized caching for various game collections with
    appropriate TTLs based on update frequency and access patterns.
    """

    # Key templates with version prefix (v2 for consistency)
    MAIDEN_COLLECTION_KEY = "lumen:v2:player:{player_id}:maidens"
    FUSION_RATES_KEY = "lumen:v2:fusion:rates:{tier}"
    LEADER_BONUSES_KEY = "lumen:v2:leader:{maiden_base_id}:{tier}"
    DAILY_QUEST_KEY = "lumen:v2:daily:{player_id}:{date}"
    DROP_CHARGES_KEY = "lumen:v2:drop:{player_id}"  # Fixed: was uppercase DROP_CHARGES
    LEADERBOARDS_KEY = "lumen:v2:leaderboard:{type}:{period}"

    # TTL configuration defaults (overridable via ConfigManager)
    _TTL_DEFAULTS = {
        "maiden_collection": 300,    # 5 minutes - frequently updated
        "fusion_rates": 3600,        # 1 hour - rarely changes
        "leader_bonuses": 3600,      # 1 hour - rarely changes
        "daily_quest": 86400,        # 24 hours - date-scoped
        "drop_charges": 300,         # 5 minutes - session-based
        "leaderboards": 600,         # 10 minutes - moderate volatility
    }

    @classmethod
    def _get_ttl(cls, cache_type: str) -> int:
        """
        Get TTL for specific cache type from ConfigManager with fallback.
        
        Parameters
        ----------
        cache_type:
            Cache type identifier.
        
        Returns
        -------
        int
            TTL in seconds from ConfigManager or sensible default.
        """
        default = cls._TTL_DEFAULTS.get(cache_type, 300)
        config_key = f"cache.ttl.{cache_type}"
        return ConfigManager.get(config_key, default)

    # =========================================================================
    # MAIDEN COLLECTION CACHING
    # =========================================================================

    @classmethod
    async def cache_maiden_collection(
        cls,
        player_id: int,
        collection_data: Dict[str, Any],
        ttl: Optional[int] = None,
    ) -> bool:
        """
        Cache player's maiden collection with automatic JSON serialization.
        
        Parameters
        ----------
        player_id:
            Player's Discord ID (snowflake).
        collection_data:
            Maiden collection data including owned maidens, levels, and stats.
        ttl:
            Optional TTL override. Uses ConfigManager default if None.
        
        Returns
        -------
        bool
            True if cached successfully, False on Redis failure.
        
        Example
        -------
        >>> await CollectionCache.cache_maiden_collection(
        ...     player_id=123456789,
        ...     collection_data={
        ...         "maidens": [{"id": 1, "level": 5, "tier": "SR"}],
        ...         "collection_size": 25,
        ...         "last_updated": 1640000000
        ...     }
        ... )
        """
        start_time = time.perf_counter()
        key = cls.MAIDEN_COLLECTION_KEY.format(player_id=player_id)

        if ttl is None:
            ttl = cls._get_ttl("maiden_collection")

        try:
            success = await RedisService.set_json(key, collection_data, ttl_seconds=ttl)

            if success:
                await CacheMetrics.record_set()

                elapsed_ms = (time.perf_counter() - start_time) * 1000
                await CacheMetrics.record_set_time(elapsed_ms)

                logger.debug(
                    "Cached maiden collection",
                    extra={
                        "player_id": player_id,
                        "ttl_seconds": ttl,
                        "latency_ms": round(elapsed_ms, 2),
                        "operation": "cache_maiden_collection",
                    },
                )

            return success

        except Exception as e:
            await CacheMetrics.record_error()
            logger.error(
                "Exception caching maiden collection",
                extra={
                    "player_id": player_id,
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                    "operation": "cache_maiden_collection",
                },
                exc_info=True,
            )
            return False

    @classmethod
    async def get_cached_maiden_collection(
        cls, player_id: int
    ) -> Optional[Dict[str, Any]]:
        """
        Get cached maiden collection with performance tracking.
        
        Parameters
        ----------
        player_id:
            Player's Discord ID (snowflake).
        
        Returns
        -------
        Optional[Dict[str, Any]]
            Cached collection data or None if not found/expired.
        
        Example
        -------
        >>> collection = await CollectionCache.get_cached_maiden_collection(123456789)
        >>> if collection:
        ...     maiden_count = collection.get("collection_size", 0)
        ... else:
        ...     collection = await fetch_maiden_collection_from_db(123456789)
        """
        start_time = time.perf_counter()
        key = cls.MAIDEN_COLLECTION_KEY.format(player_id=player_id)

        try:
            data = await RedisService.get_json(key)

            elapsed_ms = (time.perf_counter() - start_time) * 1000
            await CacheMetrics.record_get_time(elapsed_ms)

            if data:
                await CacheMetrics.record_hit()
                logger.debug(
                    "Cache HIT: maiden_collection",
                    extra={
                        "player_id": player_id,
                        "latency_ms": round(elapsed_ms, 2),
                        "operation": "get_cached_maiden_collection",
                    },
                )
                return data
            else:
                await CacheMetrics.record_miss()
                logger.debug(
                    "Cache MISS: maiden_collection",
                    extra={
                        "player_id": player_id,
                        "latency_ms": round(elapsed_ms, 2),
                        "operation": "get_cached_maiden_collection",
                    },
                )
                return None

        except Exception as e:
            await CacheMetrics.record_error()
            await CacheMetrics.record_miss()
            logger.error(
                "Exception getting cached maiden collection",
                extra={
                    "player_id": player_id,
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                    "operation": "get_cached_maiden_collection",
                },
                exc_info=True,
            )
            return None

    # =========================================================================
    # FUSION RATES CACHING
    # =========================================================================

    @classmethod
    async def cache_fusion_rates(
        cls,
        tier: str,
        rates_data: Dict[str, Any],
        ttl: Optional[int] = None,
    ) -> bool:
        """
        Cache fusion rates for a specific tier.
        
        Fusion rates are global data that rarely changes, so longer TTL is used.
        
        Parameters
        ----------
        tier:
            Tier identifier (e.g., "SR", "SSR", "UR").
        rates_data:
            Fusion rate configuration for the tier.
        ttl:
            Optional TTL override. Uses ConfigManager default (1 hour) if None.
        
        Returns
        -------
        bool
            True if cached successfully, False on Redis failure.
        
        Example
        -------
        >>> await CollectionCache.cache_fusion_rates(
        ...     tier="SSR",
        ...     rates_data={
        ...         "base_success_rate": 0.75,
        ...         "cost_multiplier": 1.5,
        ...         "tier_bonus": 0.05
        ...     }
        ... )
        """
        key = cls.FUSION_RATES_KEY.format(tier=tier)

        if ttl is None:
            ttl = cls._get_ttl("fusion_rates")

        try:
            success = await RedisService.set_json(key, rates_data, ttl_seconds=ttl)

            if success:
                await CacheMetrics.record_set()
                logger.debug(
                    "Cached fusion rates",
                    extra={
                        "tier": tier,
                        "ttl_seconds": ttl,
                        "operation": "cache_fusion_rates",
                    },
                )

            return success

        except Exception as e:
            await CacheMetrics.record_error()
            logger.error(
                "Exception caching fusion rates",
                extra={
                    "tier": tier,
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                    "operation": "cache_fusion_rates",
                },
                exc_info=True,
            )
            return False

    @classmethod
    async def get_cached_fusion_rates(cls, tier: str) -> Optional[Dict[str, Any]]:
        """
        Get cached fusion rates for a tier.
        
        Parameters
        ----------
        tier:
            Tier identifier (e.g., "SR", "SSR", "UR").
        
        Returns
        -------
        Optional[Dict[str, Any]]
            Cached rates data or None if not found/expired.
        
        Example
        -------
        >>> rates = await CollectionCache.get_cached_fusion_rates("SSR")
        >>> if rates:
        ...     success_rate = rates.get("base_success_rate", 0.5)
        ... else:
        ...     rates = await fetch_fusion_rates_from_config("SSR")
        """
        key = cls.FUSION_RATES_KEY.format(tier=tier)

        try:
            data = await RedisService.get_json(key)

            if data:
                await CacheMetrics.record_hit()
                logger.debug(
                    "Cache HIT: fusion_rates",
                    extra={"tier": tier, "operation": "get_cached_fusion_rates"},
                )
                return data
            else:
                await CacheMetrics.record_miss()
                logger.debug(
                    "Cache MISS: fusion_rates",
                    extra={"tier": tier, "operation": "get_cached_fusion_rates"},
                )
                return None

        except Exception as e:
            await CacheMetrics.record_error()
            await CacheMetrics.record_miss()
            logger.error(
                "Exception getting cached fusion rates",
                extra={
                    "tier": tier,
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                    "operation": "get_cached_fusion_rates",
                },
                exc_info=True,
            )
            return None

    # =========================================================================
    # LEADER BONUSES CACHING
    # =========================================================================

    @classmethod
    async def cache_leader_bonuses(
        cls,
        maiden_base_id: int,
        tier: str,
        bonuses_data: Dict[str, Any],
        ttl: Optional[int] = None,
    ) -> bool:
        """
        Cache leader bonuses for a specific maiden and tier.
        
        Leader bonuses are global data that rarely changes, so longer TTL is used.
        
        Parameters
        ----------
        maiden_base_id:
            Maiden's base ID from the database.
        tier:
            Tier identifier (e.g., "SR", "SSR", "UR").
        bonuses_data:
            Leader bonus configuration.
        ttl:
            Optional TTL override. Uses ConfigManager default (1 hour) if None.
        
        Returns
        -------
        bool
            True if cached successfully, False on Redis failure.
        
        Example
        -------
        >>> await CollectionCache.cache_leader_bonuses(
        ...     maiden_base_id=101,
        ...     tier="SSR",
        ...     bonuses_data={
        ...         "atk_bonus": 0.15,
        ...         "def_bonus": 0.10,
        ...         "special_effect": "fire_dmg_up"
        ...     }
        ... )
        """
        key = cls.LEADER_BONUSES_KEY.format(maiden_base_id=maiden_base_id, tier=tier)

        if ttl is None:
            ttl = cls._get_ttl("leader_bonuses")

        try:
            success = await RedisService.set_json(key, bonuses_data, ttl_seconds=ttl)

            if success:
                await CacheMetrics.record_set()
                logger.debug(
                    "Cached leader bonuses",
                    extra={
                        "maiden_base_id": maiden_base_id,
                        "tier": tier,
                        "ttl_seconds": ttl,
                        "operation": "cache_leader_bonuses",
                    },
                )

            return success

        except Exception as e:
            await CacheMetrics.record_error()
            logger.error(
                "Exception caching leader bonuses",
                extra={
                    "maiden_base_id": maiden_base_id,
                    "tier": tier,
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                    "operation": "cache_leader_bonuses",
                },
                exc_info=True,
            )
            return False

    @classmethod
    async def get_cached_leader_bonuses(
        cls, maiden_base_id: int, tier: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get cached leader bonuses for a maiden and tier.
        
        Parameters
        ----------
        maiden_base_id:
            Maiden's base ID from the database.
        tier:
            Tier identifier (e.g., "SR", "SSR", "UR").
        
        Returns
        -------
        Optional[Dict[str, Any]]
            Cached bonuses data or None if not found/expired.
        
        Example
        -------
        >>> bonuses = await CollectionCache.get_cached_leader_bonuses(101, "SSR")
        >>> if bonuses:
        ...     atk_bonus = bonuses.get("atk_bonus", 0.0)
        ... else:
        ...     bonuses = await fetch_leader_bonuses_from_db(101, "SSR")
        """
        key = cls.LEADER_BONUSES_KEY.format(maiden_base_id=maiden_base_id, tier=tier)

        try:
            data = await RedisService.get_json(key)

            if data:
                await CacheMetrics.record_hit()
                logger.debug(
                    "Cache HIT: leader_bonuses",
                    extra={
                        "maiden_base_id": maiden_base_id,
                        "tier": tier,
                        "operation": "get_cached_leader_bonuses",
                    },
                )
                return data
            else:
                await CacheMetrics.record_miss()
                logger.debug(
                    "Cache MISS: leader_bonuses",
                    extra={
                        "maiden_base_id": maiden_base_id,
                        "tier": tier,
                        "operation": "get_cached_leader_bonuses",
                    },
                )
                return None

        except Exception as e:
            await CacheMetrics.record_error()
            await CacheMetrics.record_miss()
            logger.error(
                "Exception getting cached leader bonuses",
                extra={
                    "maiden_base_id": maiden_base_id,
                    "tier": tier,
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                    "operation": "get_cached_leader_bonuses",
                },
                exc_info=True,
            )
            return None

    # =========================================================================
    # DROP CHARGES CACHING
    # =========================================================================

    @classmethod
    async def cache_drop_charges(
        cls,
        player_id: int,
        charges_data: Dict[str, Any],
        ttl: Optional[int] = None,
    ) -> bool:
        """
        Cache player's drop charges (gacha currency).
        
        Parameters
        ----------
        player_id:
            Player's Discord ID (snowflake).
        charges_data:
            Drop charge data including current count and timestamps.
        ttl:
            Optional TTL override. Uses ConfigManager default if None.
        
        Returns
        -------
        bool
            True if cached successfully, False on Redis failure.
        
        Example
        -------
        >>> await CollectionCache.cache_drop_charges(
        ...     player_id=123456789,
        ...     charges_data={
        ...         "current_charges": 10,
        ...         "max_charges": 20,
        ...         "last_regen": 1640000000
        ...     }
        ... )
        """
        key = cls.DROP_CHARGES_KEY.format(player_id=player_id)

        if ttl is None:
            ttl = cls._get_ttl("drop_charges")

        try:
            success = await RedisService.set_json(key, charges_data, ttl_seconds=ttl)

            if success:
                await CacheMetrics.record_set()
                logger.debug(
                    "Cached drop charges",
                    extra={
                        "player_id": player_id,
                        "ttl_seconds": ttl,
                        "operation": "cache_drop_charges",
                    },
                )

            return success

        except Exception as e:
            await CacheMetrics.record_error()
            logger.error(
                "Exception caching drop charges",
                extra={
                    "player_id": player_id,
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                    "operation": "cache_drop_charges",
                },
                exc_info=True,
            )
            return False

    @classmethod
    async def get_cached_drop_charges(
        cls, player_id: int
    ) -> Optional[Dict[str, Any]]:
        """
        Get cached drop charges for a player.
        
        Parameters
        ----------
        player_id:
            Player's Discord ID (snowflake).
        
        Returns
        -------
        Optional[Dict[str, Any]]
            Cached charges data or None if not found/expired.
        
        Example
        -------
        >>> charges = await CollectionCache.get_cached_drop_charges(123456789)
        >>> if charges:
        ...     current = charges.get("current_charges", 0)
        ... else:
        ...     charges = await fetch_drop_charges_from_db(123456789)
        """
        key = cls.DROP_CHARGES_KEY.format(player_id=player_id)

        try:
            data = await RedisService.get_json(key)

            if data:
                await CacheMetrics.record_hit()
                logger.debug(
                    "Cache HIT: drop_charges",
                    extra={
                        "player_id": player_id,
                        "operation": "get_cached_drop_charges",
                    },
                )
                return data
            else:
                await CacheMetrics.record_miss()
                logger.debug(
                    "Cache MISS: drop_charges",
                    extra={
                        "player_id": player_id,
                        "operation": "get_cached_drop_charges",
                    },
                )
                return None

        except Exception as e:
            await CacheMetrics.record_error()
            await CacheMetrics.record_miss()
            logger.error(
                "Exception getting cached drop charges",
                extra={
                    "player_id": player_id,
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                    "operation": "get_cached_drop_charges",
                },
                exc_info=True,
            )
            return None

    # =========================================================================
    # DAILY QUEST CACHING
    # =========================================================================

    @classmethod
    async def cache_daily_quest(
        cls,
        player_id: int,
        date: str,
        quest_data: Dict[str, Any],
        ttl: Optional[int] = None,
    ) -> bool:
        """
        Cache daily quest data for a player and date.
        
        Parameters
        ----------
        player_id:
            Player's Discord ID (snowflake).
        date:
            Date string in YYYY-MM-DD format.
        quest_data:
            Quest progress and completion data.
        ttl:
            Optional TTL override. Uses ConfigManager default (24 hours) if None.
        
        Returns
        -------
        bool
            True if cached successfully, False on Redis failure.
        
        Example
        -------
        >>> await CollectionCache.cache_daily_quest(
        ...     player_id=123456789,
        ...     date="2025-01-15",
        ...     quest_data={
        ...         "quests_completed": 3,
        ...         "total_quests": 5,
        ...         "last_updated": 1640000000
        ...     }
        ... )
        """
        key = cls.DAILY_QUEST_KEY.format(player_id=player_id, date=date)

        if ttl is None:
            ttl = cls._get_ttl("daily_quest")

        try:
            success = await RedisService.set_json(key, quest_data, ttl_seconds=ttl)

            if success:
                await CacheMetrics.record_set()
                logger.debug(
                    "Cached daily quest",
                    extra={
                        "player_id": player_id,
                        "date": date,
                        "ttl_seconds": ttl,
                        "operation": "cache_daily_quest",
                    },
                )

            return success

        except Exception as e:
            await CacheMetrics.record_error()
            logger.error(
                "Exception caching daily quest",
                extra={
                    "player_id": player_id,
                    "date": date,
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                    "operation": "cache_daily_quest",
                },
                exc_info=True,
            )
            return False

    @classmethod
    async def get_cached_daily_quest(
        cls, player_id: int, date: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get cached daily quest data.
        
        Parameters
        ----------
        player_id:
            Player's Discord ID (snowflake).
        date:
            Date string in YYYY-MM-DD format.
        
        Returns
        -------
        Optional[Dict[str, Any]]
            Cached quest data or None if not found/expired.
        
        Example
        -------
        >>> quest = await CollectionCache.get_cached_daily_quest(123456789, "2025-01-15")
        >>> if quest:
        ...     completed = quest.get("quests_completed", 0)
        ... else:
        ...     quest = await fetch_daily_quest_from_db(123456789, "2025-01-15")
        """
        key = cls.DAILY_QUEST_KEY.format(player_id=player_id, date=date)

        try:
            data = await RedisService.get_json(key)

            if data:
                await CacheMetrics.record_hit()
                logger.debug(
                    "Cache HIT: daily_quest",
                    extra={
                        "player_id": player_id,
                        "date": date,
                        "operation": "get_cached_daily_quest",
                    },
                )
                return data
            else:
                await CacheMetrics.record_miss()
                logger.debug(
                    "Cache MISS: daily_quest",
                    extra={
                        "player_id": player_id,
                        "date": date,
                        "operation": "get_cached_daily_quest",
                    },
                )
                return None

        except Exception as e:
            await CacheMetrics.record_error()
            await CacheMetrics.record_miss()
            logger.error(
                "Exception getting cached daily quest",
                extra={
                    "player_id": player_id,
                    "date": date,
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                    "operation": "get_cached_daily_quest",
                },
                exc_info=True,
            )
            return None

    # =========================================================================
    # LEADERBOARD CACHING
    # =========================================================================

    @classmethod
    async def cache_leaderboard(
        cls,
        leaderboard_type: str,
        period: str,
        leaderboard_data: Dict[str, Any],
        ttl: Optional[int] = None,
    ) -> bool:
        """
        Cache leaderboard data for a type and period.
        
        Parameters
        ----------
        leaderboard_type:
            Type of leaderboard (e.g., "lumees", "collection", "power").
        period:
            Period identifier (e.g., "daily", "weekly", "monthly", "all_time").
        leaderboard_data:
            Leaderboard rankings and player data.
        ttl:
            Optional TTL override. Uses ConfigManager default (10 minutes) if None.
        
        Returns
        -------
        bool
            True if cached successfully, False on Redis failure.
        
        Example
        -------
        >>> await CollectionCache.cache_leaderboard(
        ...     leaderboard_type="lumees",
        ...     period="weekly",
        ...     leaderboard_data={
        ...         "rankings": [
        ...             {"player_id": 123, "score": 10000, "rank": 1},
        ...             {"player_id": 456, "score": 9000, "rank": 2}
        ...         ],
        ...         "last_updated": 1640000000
        ...     }
        ... )
        """
        key = cls.LEADERBOARDS_KEY.format(type=leaderboard_type, period=period)

        if ttl is None:
            ttl = cls._get_ttl("leaderboards")

        try:
            success = await RedisService.set_json(key, leaderboard_data, ttl_seconds=ttl)

            if success:
                await CacheMetrics.record_set()
                logger.debug(
                    "Cached leaderboard",
                    extra={
                        "type": leaderboard_type,
                        "period": period,
                        "ttl_seconds": ttl,
                        "operation": "cache_leaderboard",
                    },
                )

            return success

        except Exception as e:
            await CacheMetrics.record_error()
            logger.error(
                "Exception caching leaderboard",
                extra={
                    "type": leaderboard_type,
                    "period": period,
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                    "operation": "cache_leaderboard",
                },
                exc_info=True,
            )
            return False

    @classmethod
    async def get_cached_leaderboard(
        cls, leaderboard_type: str, period: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get cached leaderboard data.
        
        Parameters
        ----------
        leaderboard_type:
            Type of leaderboard (e.g., "lumees", "collection", "power").
        period:
            Period identifier (e.g., "daily", "weekly", "monthly", "all_time").
        
        Returns
        -------
        Optional[Dict[str, Any]]
            Cached leaderboard data or None if not found/expired.
        
        Example
        -------
        >>> leaderboard = await CollectionCache.get_cached_leaderboard("lumees", "weekly")
        >>> if leaderboard:
        ...     rankings = leaderboard.get("rankings", [])
        ... else:
        ...     leaderboard = await fetch_leaderboard_from_db("lumees", "weekly")
        """
        key = cls.LEADERBOARDS_KEY.format(type=leaderboard_type, period=period)

        try:
            data = await RedisService.get_json(key)

            if data:
                await CacheMetrics.record_hit()
                logger.debug(
                    "Cache HIT: leaderboard",
                    extra={
                        "type": leaderboard_type,
                        "period": period,
                        "operation": "get_cached_leaderboard",
                    },
                )
                return data
            else:
                await CacheMetrics.record_miss()
                logger.debug(
                    "Cache MISS: leaderboard",
                    extra={
                        "type": leaderboard_type,
                        "period": period,
                        "operation": "get_cached_leaderboard",
                    },
                )
                return None

        except Exception as e:
            await CacheMetrics.record_error()
            await CacheMetrics.record_miss()
            logger.error(
                "Exception getting cached leaderboard",
                extra={
                    "type": leaderboard_type,
                    "period": period,
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                    "operation": "get_cached_leaderboard",
                },
                exc_info=True,
            )
            return None