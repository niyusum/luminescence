"""
Cache subsystem for Lumen (2025).

Purpose
-------
Provides high-performance, observable caching layer with Redis backend.
Designed for production-grade performance optimization with comprehensive
monitoring and graceful degradation.

Features
--------
- Player-specific caching (resources, modifiers)
- Collection caching (maidens, fusion rates, leader bonuses, quests)
- Batch operations for efficiency
- Tag-based bulk invalidation
- Comprehensive metrics tracking
- ConfigManager-driven TTLs
- Automatic health monitoring
- Graceful Redis failure handling

Architecture
------------
The cache subsystem is organized into specialized modules:

- **service.py**: Main facade and public API
- **player.py**: Player-specific caching operations
- **collections.py**: Collection and global data caching
- **operations.py**: Batch operations and tag management
- **metrics.py**: Performance metrics and health monitoring

All modules follow LES 2025 standards with proper separation of concerns,
comprehensive observability, and config-driven behavior.

LES 2025 Compliance
-------------------
- **Article I**: Strict separation - infrastructure layer only
- **Article V**: Config-driven TTLs and thresholds
- **Article VI**: Comprehensive observability and metrics
- **Article IX**: Graceful degradation on Redis failure
- **Article X**: Structured logging throughout

Usage Example
-------------
>>> from src.core.cache import CacheService
>>>
>>> # Cache player resources
>>> await CacheService.cache_player_resources(
...     player_id=123456789,
...     resource_data={"lumees": 1000, "energy": 50}
... )
>>>
>>> # Get cached resources
>>> resources = await CacheService.get_cached_player_resources(123456789)
>>>
>>> # Check cache health
>>> health = await CacheService.health_check()
>>> print(f"Cache status: {health['status']}")

Dependencies
------------
- RedisService: Storage backend
- ConfigManager: Configuration management
- Logger: Structured logging
"""

from src.core.cache.collections import CollectionCache
from src.core.cache.metrics import CacheMetrics
from src.core.cache.operations import CacheOperations
from src.core.cache.player import PlayerCache
from src.core.cache.service import CacheService

__all__ = [
    # Main public API (use this for all external access)
    "CacheService",
    # Specialized modules (for advanced/internal usage)
    "PlayerCache",
    "CollectionCache",
    "CacheOperations",
    "CacheMetrics",
]
