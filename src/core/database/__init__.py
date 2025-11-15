"""
Database subsystem for Lumen (2025).

Provides async SQLAlchemy engine, session management, health monitoring,
metrics tracking, and observability.

Also exports ORM base classes and mixins for model definitions.
"""

from src.core.database.base import (
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    utc_now,
)
from src.core.database.bootstrap import (
    initialize_database_subsystem,
    shutdown_database_subsystem,
)
from src.core.database.health_monitor import (
    DatabaseHealthMonitor,
    DatabaseHealthMonitorConfig,
)
from src.core.database.metrics import AbstractDatabaseMetricsBackend, DatabaseMetrics
from src.core.database.service import (
    DatabaseInitializationError,
    DatabaseNotInitializedError,
    DatabaseService,
)

__all__ = [
    # ORM Base & Mixins
    "Base",
    "TimestampMixin",
    "SoftDeleteMixin",
    "utc_now",
    # Main service
    "DatabaseService",
    # Bootstrap
    "initialize_database_subsystem",
    "shutdown_database_subsystem",
    # Exceptions
    "DatabaseInitializationError",
    "DatabaseNotInitializedError",
    # Health monitoring
    "DatabaseHealthMonitor",
    "DatabaseHealthMonitorConfig",
    # Metrics
    "DatabaseMetrics",
    "AbstractDatabaseMetricsBackend",
]
