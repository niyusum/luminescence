"""
Caching services and utilities.

Provides in-memory and Redis-backed caching for performance optimization.
"""

# Import from service module (unified facade)
from src.core.cache.service import CacheService

# Import specialized modules (for advanced usage)
from src.core.cache.collections import CollectionCache
from src.core.cache.metrics import CacheMetrics
from src.core.cache.operations import CacheOperations
from src.core.cache.player import PlayerCache

__all__ = [
    # Main facade
    "CacheService",
    # Specialized modules
    "PlayerCache",
    "CollectionCache",
    "CacheOperations",
    "CacheMetrics",
]
