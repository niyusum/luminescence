"""
Database Metrics - Infrastructure Observability Facade (Lumen 2025)

Purpose
-------
Centralized, backend-agnostic metrics facade for all database-related telemetry
including engine lifecycle, health checks, transactions, queries, retries, and
connection pool utilization.

Provides a stable API for database infrastructure to emit metrics without
coupling to specific monitoring backends (Prometheus, StatsD, etc.).

Responsibilities
----------------
- Define stable metrics API via DatabaseMetrics static facade
- Support pluggable backends via AbstractDatabaseMetricsBackend interface
- Emit structured logs as fallback when no backend configured
- Track all database operations: lifecycle, transactions, queries, retries
- Record connection pool metrics for capacity planning
- Maintain backend independence for infrastructure code

Non-Responsibilities
--------------------
- Database I/O or session management (DatabaseService handles this)
- Background monitoring or scheduling (handled by callers)
- Domain logic or business rules
- Discord integration

LUMEN 2025 Compliance
---------------------
✓ Article I: No state mutations, metrics recording only
✓ Article II: Comprehensive audit trail via metrics and logs
✓ Article III: Config-driven backend configuration
✓ Article IX: Graceful degradation (logs when no backend)
✓ Article X: Maximum observability across all operations

Architecture Notes
------------------
**Backend Pattern**:
- AbstractDatabaseMetricsBackend defines the contract
- DatabaseMetrics facade delegates to configured backend
- Falls back to debug logs when no backend configured
- Backend configured once at startup via configure_backend()

**Metric Categories**:
1. Engine lifecycle (init, failure, shutdown)
2. Health checks (success/failure, latency)
3. Transactions (start, commit, rollback with timing)
4. Queries (operation name, latency, success/failure)
5. Retries (attempts, give-ups with error types)
6. Connection pool (size, checked out/in, overflow)

**Connection Pool Metrics**:
Critical for:
- Capacity planning (is pool_size sufficient?)
- Connection leak detection (checked_out growing?)
- Performance analysis (overflow connections needed?)

Usage Example
-------------
Configure backend at startup:

>>> from src.core.database.metrics import DatabaseMetrics
>>> from src.infra.prometheus_backend import PrometheusMetricsBackend
>>>
>>> # During bot initialization
>>> backend = PrometheusMetricsBackend()
>>> DatabaseMetrics.configure_backend(backend)

Record metrics (infrastructure calls these):

>>> # Engine lifecycle
>>> DatabaseMetrics.record_engine_initialized(
>>>     url_scheme="postgresql",
>>>     pool_class="QueuePool",
>>>     pool_size=5,
>>>     max_overflow=10,
>>> )
>>>
>>> # Transaction
>>> DatabaseMetrics.record_transaction_started()
>>> DatabaseMetrics.record_transaction_committed(duration_ms=45.2)
>>>
>>> # Query
>>> DatabaseMetrics.record_query(
>>>     operation="Player.select_by_id",
>>>     duration_ms=12.3,
>>>     success=True,
>>>     error_type=None,
>>> )
>>>
>>> # Pool metrics
>>> DatabaseMetrics.record_pool_metrics(
>>>     pool_size=5,
>>>     checked_out=3,
>>>     checked_in=2,
>>>     overflow=0,
>>>     total_connections=5,
>>> )

Implementing a Backend
----------------------
Create a class implementing AbstractDatabaseMetricsBackend:

>>> from src.core.database.metrics import AbstractDatabaseMetricsBackend
>>>
>>> class CustomMetricsBackend(AbstractDatabaseMetricsBackend):
>>>     def record_engine_initialized(self, *, url_scheme, pool_class, ...):
>>>         # Send to your monitoring system
>>>         pass
>>>
>>>     def record_health_check(self, *, success, duration_ms):
>>>         # Send to your monitoring system
>>>         pass
>>>
>>>     # ... implement all abstract methods ...
>>>
>>> backend = CustomMetricsBackend()
>>> DatabaseMetrics.configure_backend(backend)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from src.core.logging.logger import get_logger

logger = get_logger(__name__)


# ============================================================================
# Abstract Backend Interface
# ============================================================================


class AbstractDatabaseMetricsBackend(ABC):
    """
    Interface for pluggable database metrics backends.

    Implementing classes should send metrics to their chosen monitoring
    system (Prometheus, StatsD, CloudWatch, etc.).
    """

    # ------------------------------------------------------------------------
    # Engine Lifecycle
    # ------------------------------------------------------------------------

    @abstractmethod
    def record_engine_initialized(
        self,
        *,
        url_scheme: str,
        pool_class: str,
        pool_size: int,
        max_overflow: int,
    ) -> None:
        """
        Record successful engine initialization.

        Parameters
        ----------
        url_scheme : str
            Database URL scheme (e.g., "postgresql", "sqlite").
        pool_class : str
            Connection pool class name (e.g., "QueuePool", "NullPool").
        pool_size : int
            Configured pool size.
        max_overflow : int
            Maximum overflow connections allowed.
        """
        ...

    @abstractmethod
    def record_engine_initialization_failed(self, *, config_error: bool) -> None:
        """
        Record engine initialization failure.

        Parameters
        ----------
        config_error : bool
            True if failure was due to configuration error, False otherwise.
        """
        ...

    @abstractmethod
    def record_engine_shutdown(self) -> None:
        """Record engine shutdown event."""
        ...

    # ------------------------------------------------------------------------
    # Health Checks
    # ------------------------------------------------------------------------

    @abstractmethod
    def record_health_check(self, *, success: bool, duration_ms: float) -> None:
        """
        Record health check result.

        Parameters
        ----------
        success : bool
            True if health check passed, False otherwise.
        duration_ms : float
            Health check duration in milliseconds.
        """
        ...

    # ------------------------------------------------------------------------
    # Transactions
    # ------------------------------------------------------------------------

    @abstractmethod
    def record_transaction_started(self) -> None:
        """Record transaction start event."""
        ...

    @abstractmethod
    def record_transaction_committed(self, *, duration_ms: float) -> None:
        """
        Record successful transaction commit.

        Parameters
        ----------
        duration_ms : float
            Transaction duration in milliseconds.
        """
        ...

    @abstractmethod
    def record_transaction_rolled_back(
        self,
        *,
        duration_ms: float,
        error_type: str,
    ) -> None:
        """
        Record transaction rollback.

        Parameters
        ----------
        duration_ms : float
            Transaction duration before rollback in milliseconds.
        error_type : str
            Exception type that caused rollback.
        """
        ...

    # ------------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------------

    @abstractmethod
    def record_query(
        self,
        *,
        operation: str,
        duration_ms: float,
        success: bool,
        error_type: Optional[str],
        extra_tags: Optional[dict[str, Any]] = None,
    ) -> None:
        """
        Record query execution.

        Parameters
        ----------
        operation : str
            Stable operation identifier (e.g., "Player.select_by_id").
        duration_ms : float
            Query duration in milliseconds.
        success : bool
            True if query succeeded, False otherwise.
        error_type : Optional[str]
            Exception type if query failed, None otherwise.
        extra_tags : Optional[dict[str, Any]]
            Additional tags for dimensionality (e.g., shard, module).
        """
        ...

    # ------------------------------------------------------------------------
    # Retries
    # ------------------------------------------------------------------------

    @abstractmethod
    def record_retry_attempt(
        self,
        *,
        operation: str,
        attempt: int,
        will_retry: bool,
        error_type: str,
    ) -> None:
        """
        Record retry attempt.

        Parameters
        ----------
        operation : str
            Operation being retried.
        attempt : int
            Current attempt number (1-indexed).
        will_retry : bool
            True if another retry will be attempted, False if giving up.
        error_type : str
            Exception type that triggered retry.
        """
        ...

    @abstractmethod
    def record_retry_give_up(
        self,
        *,
        operation: str,
        attempt: int,
        error_type: str,
    ) -> None:
        """
        Record retry exhaustion.

        Parameters
        ----------
        operation : str
            Operation that exhausted retries.
        attempt : int
            Final attempt number.
        error_type : str
            Exception type on final attempt.
        """
        ...

    # ------------------------------------------------------------------------
    # Connection Pool
    # ------------------------------------------------------------------------

    @abstractmethod
    def record_pool_metrics(
        self,
        *,
        pool_size: int,
        checked_out: int,
        checked_in: int,
        overflow: int,
        total_connections: int,
    ) -> None:
        """
        Record connection pool metrics.

        Parameters
        ----------
        pool_size : int
            Configured pool size.
        checked_out : int
            Connections currently in use.
        checked_in : int
            Connections available in pool.
        overflow : int
            Overflow connections (beyond pool_size).
        total_connections : int
            Total connections (checked_out + checked_in + overflow).
        """
        ...


# ============================================================================
# DatabaseMetrics Facade
# ============================================================================


class DatabaseMetrics:
    """
    Static facade for database metrics.

    Infrastructure code calls these classmethods to emit metrics. A concrete
    backend can be configured via configure_backend() to handle the metrics.
    When no backend is configured, falls back to debug-level logging.

    Thread Safety
    -------------
    Safe for concurrent access. Backend configuration is typically done once
    during application startup.
    """

    _backend: Optional[AbstractDatabaseMetricsBackend] = None

    # ------------------------------------------------------------------------
    # Backend Configuration
    # ------------------------------------------------------------------------

    @classmethod
    def configure_backend(cls, backend: AbstractDatabaseMetricsBackend) -> None:
        """
        Configure the metrics backend.

        Parameters
        ----------
        backend : AbstractDatabaseMetricsBackend
            Backend implementation to use for metrics recording.

        Notes
        -----
        - Should be called once during application startup
        - Subsequent calls will replace the existing backend
        - Thread-safe but not intended for runtime switching
        """
        cls._backend = backend
        logger.info(
            "Database metrics backend configured",
            extra={"backend_class": type(backend).__name__},
        )

    @classmethod
    def _log_fallback(cls, message: str, **extra: Any) -> None:
        """
        Fallback logging when no backend is configured.

        Parameters
        ----------
        message : str
            Metric event description.
        **extra : Any
            Additional context for structured logging.
        """
        logger.debug(
            f"[DatabaseMetrics fallback] {message}",
            extra=extra or None,
        )

    # ------------------------------------------------------------------------
    # Engine Lifecycle
    # ------------------------------------------------------------------------

    @classmethod
    def record_engine_initialized(
        cls,
        *,
        url_scheme: str,
        pool_class: str,
        pool_size: int,
        max_overflow: int,
    ) -> None:
        """Record successful engine initialization."""
        if cls._backend:
            cls._backend.record_engine_initialized(
                url_scheme=url_scheme,
                pool_class=pool_class,
                pool_size=pool_size,
                max_overflow=max_overflow,
            )
        else:
            cls._log_fallback(
                "engine_initialized",
                url_scheme=url_scheme,
                pool_class=pool_class,
                pool_size=pool_size,
                max_overflow=max_overflow,
            )

    @classmethod
    def record_engine_initialization_failed(cls, *, config_error: bool) -> None:
        """Record engine initialization failure."""
        if cls._backend:
            cls._backend.record_engine_initialization_failed(config_error=config_error)
        else:
            cls._log_fallback(
                "engine_initialization_failed",
                config_error=config_error,
            )

    @classmethod
    def record_engine_shutdown(cls) -> None:
        """Record engine shutdown."""
        if cls._backend:
            cls._backend.record_engine_shutdown()
        else:
            cls._log_fallback("engine_shutdown")

    # ------------------------------------------------------------------------
    # Health Checks
    # ------------------------------------------------------------------------

    @classmethod
    def record_health_check(cls, *, success: bool, duration_ms: float) -> None:
        """Record health check result."""
        if cls._backend:
            cls._backend.record_health_check(success=success, duration_ms=duration_ms)
        else:
            cls._log_fallback(
                "health_check",
                success=success,
                duration_ms=duration_ms,
            )

    # ------------------------------------------------------------------------
    # Transactions
    # ------------------------------------------------------------------------

    @classmethod
    def record_transaction_started(cls) -> None:
        """Record transaction start."""
        if cls._backend:
            cls._backend.record_transaction_started()
        else:
            cls._log_fallback("transaction_started")

    @classmethod
    def record_transaction_committed(cls, *, duration_ms: float) -> None:
        """Record successful transaction commit."""
        if cls._backend:
            cls._backend.record_transaction_committed(duration_ms=duration_ms)
        else:
            cls._log_fallback(
                "transaction_committed",
                duration_ms=duration_ms,
            )

    @classmethod
    def record_transaction_rolled_back(
        cls,
        *,
        duration_ms: float,
        error_type: str,
    ) -> None:
        """Record transaction rollback."""
        if cls._backend:
            cls._backend.record_transaction_rolled_back(
                duration_ms=duration_ms,
                error_type=error_type,
            )
        else:
            cls._log_fallback(
                "transaction_rolled_back",
                duration_ms=duration_ms,
                error_type=error_type,
            )

    # ------------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------------

    @classmethod
    def record_query(
        cls,
        *,
        operation: str,
        duration_ms: float,
        success: bool,
        error_type: Optional[str],
        extra_tags: Optional[dict[str, Any]] = None,
    ) -> None:
        """Record query execution."""
        if cls._backend:
            cls._backend.record_query(
                operation=operation,
                duration_ms=duration_ms,
                success=success,
                error_type=error_type,
                extra_tags=extra_tags,
            )
        else:
            cls._log_fallback(
                "query",
                operation=operation,
                duration_ms=duration_ms,
                success=success,
                error_type=error_type,
                extra_tags=extra_tags,
            )

    # ------------------------------------------------------------------------
    # Retries
    # ------------------------------------------------------------------------

    @classmethod
    def record_retry_attempt(
        cls,
        *,
        operation: str,
        attempt: int,
        will_retry: bool,
        error_type: str,
    ) -> None:
        """Record retry attempt."""
        if cls._backend:
            cls._backend.record_retry_attempt(
                operation=operation,
                attempt=attempt,
                will_retry=will_retry,
                error_type=error_type,
            )
        else:
            cls._log_fallback(
                "retry_attempt",
                operation=operation,
                attempt=attempt,
                will_retry=will_retry,
                error_type=error_type,
            )

    @classmethod
    def record_retry_give_up(
        cls,
        *,
        operation: str,
        attempt: int,
        error_type: str,
    ) -> None:
        """Record retry exhaustion."""
        if cls._backend:
            cls._backend.record_retry_give_up(
                operation=operation,
                attempt=attempt,
                error_type=error_type,
            )
        else:
            cls._log_fallback(
                "retry_give_up",
                operation=operation,
                attempt=attempt,
                error_type=error_type,
            )

    # ------------------------------------------------------------------------
    # Connection Pool
    # ------------------------------------------------------------------------

    @classmethod
    def record_pool_metrics(
        cls,
        *,
        pool_size: int,
        checked_out: int,
        checked_in: int,
        overflow: int,
        total_connections: int,
    ) -> None:
        """Record connection pool metrics."""
        if cls._backend:
            cls._backend.record_pool_metrics(
                pool_size=pool_size,
                checked_out=checked_out,
                checked_in=checked_in,
                overflow=overflow,
                total_connections=total_connections,
            )
        else:
            cls._log_fallback(
                "pool_metrics",
                pool_size=pool_size,
                checked_out=checked_out,
                checked_in=checked_in,
                overflow=overflow,
                total_connections=total_connections,
            )