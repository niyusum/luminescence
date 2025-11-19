"""
Database Service - Core Infrastructure Layer (Lumen 2025)

Purpose
-------
Centralized async database engine and session management for the Lumen RPG system.
Provides atomic transactions, pessimistic locking, health monitoring, and comprehensive
observability for all database operations.

Responsibilities
----------------
- Initialize and manage a single AsyncEngine instance with connection pooling
- Provide async context managers for read-only sessions and atomic transactions
- Enforce transaction discipline: automatic commit on success, rollback on exception
- Support pessimistic row locking via `with_for_update=True`
- Expose health checks for infrastructure monitoring
- Record detailed metrics for engine lifecycle, transactions, and connection pool usage
- Configure statement timeouts for PostgreSQL connections
- Provide idempotent initialization with async lock protection

Non-Responsibilities
--------------------
- Query-level observability (handled by QueryObserver)
- Retry policies for transient failures (handled by DatabaseRetryPolicy)
- Background health monitoring (handled by DatabaseHealthMonitor)
- Database migrations or schema management (handled by Alembic)
- Domain logic, business rules, or Discord integration
- Cross-service orchestration or event emission

LUMEN 2025 Compliance
---------------------
✓ Article I: Transaction-safe with pessimistic locking support
✓ Article II: Comprehensive structured logging and audit trail
✓ Article III: Config-driven (all tunables from Config)
✓ Article IX: Graceful degradation with clear error messages
✓ Article X: Maximum observability (metrics, logs, health checks)

Architecture Notes
------------------
**Transaction Model**:
- `get_transaction()` is the primary interface for all state mutations
- Automatic commit on success, rollback on any exception
- Never manually call `session.commit()` inside service code
- Use pessimistic locks: `await session.get(Model, pk, with_for_update=True)`

**Connection Pooling**:
- QueuePool for production (configurable pool_size and max_overflow)
- NullPool for testing environments (no connection reuse)
- Automatic connection recycling via pool_recycle
- Pool timeout protection via pool_timeout

**Health Checks**:
- Lightweight `SELECT 1` query for fast liveness probes
- Records timing and success/failure metrics
- Suitable for Kubernetes readiness/liveness endpoints

**Configuration**:
All values sourced from Config with safe defaults:
- DATABASE_URL (required)
- DATABASE_POOL_SIZE (default: 5)
- DATABASE_MAX_OVERFLOW (default: 10)
- DATABASE_POOL_RECYCLE (default: 1800)
- DATABASE_POOL_TIMEOUT (default: 30)
- DATABASE_STATEMENT_TIMEOUT_MS (default: 30000)
- DATABASE_ECHO (default: False)
- TESTING (default: False)

Usage Example
-------------
Atomic write transaction (preferred):

>>> from src.core.database.service import DatabaseService
>>> from src.database.models import Player
>>>
>>> async with DatabaseService.get_transaction() as session:
>>>     player = await session.get(Player, player_id, with_for_update=True)
>>>     player.lumees += 1000
>>>     # Automatic commit on exit

Read-only access:

>>> async with DatabaseService.get_session() as session:
>>>     result = await session.execute(select(Player).where(Player.id == player_id))
>>>     player = result.scalar_one_or_none()

Pessimistic locking helper:

>>> async with DatabaseService.get_transaction() as session:
>>>     player = await DatabaseService.get_locked_entity(session, Player, player_id)
>>>     player.lumees += 1000

Error Handling
--------------
**DatabaseInitializationError** - Raised when:
- DATABASE_URL is missing or invalid
- Engine creation fails
- Configuration is malformed

**DatabaseNotInitializedError** - Raised when:
- Session requested before initialize() is called
- Service methods called after shutdown()

**Automatic Rollback** - Triggered by:
- OperationalError (connection failures, timeouts)
- DBAPIError (database-level errors)
- Any unhandled exception in transaction context
"""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Optional, Type, TypeVar

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool, Pool, QueuePool

from src.core.config.config import Config
from src.core.logging.logger import get_logger
from src.core.database.metrics import DatabaseMetrics
from src.core.database.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError

logger = get_logger(__name__)

# Type variable for generic entity locking
T = TypeVar("T")


# ============================================================================
# Domain Exceptions
# ============================================================================


class DatabaseInitializationError(RuntimeError):
    """Raised when database engine initialization fails."""


class DatabaseNotInitializedError(RuntimeError):
    """Raised when database operations are attempted before initialization."""


# ============================================================================
# Configuration Snapshot
# ============================================================================


@dataclass(frozen=True)
class _DatabaseConfigSnapshot:
    """
    Immutable snapshot of database configuration.

    Prevents repeated Config lookups and provides a stable configuration
    view for the lifetime of the engine.
    """

    url: str
    echo: bool
    pool_class: Type[Pool]
    pool_size: int
    max_overflow: int
    pool_recycle: int
    pool_timeout: int
    statement_timeout_ms: int

    @property
    def is_postgres(self) -> bool:
        """Check if the configured database is PostgreSQL."""
        return self.url.startswith(("postgresql://", "postgresql+asyncpg://"))

    @property
    def url_scheme(self) -> str:
        """Extract the URL scheme for logging/metrics."""
        return self.url.split(":", 1)[0] if ":" in self.url else "unknown"


# ============================================================================
# DatabaseService - Core Infrastructure
# ============================================================================


class DatabaseService:
    """
    Centralized async database engine and session management.

    Public API
    ----------
    **Lifecycle**:
    - initialize() -> Initialize engine and session factory
    - shutdown() -> Dispose engine and cleanup resources

    **Session Management**:
    - get_session() -> Read-only or manual transaction control
    - get_transaction() -> Atomic write transaction (preferred)

    **Utilities**:
    - health_check() -> Fast database reachability check
    - get_pool_metrics() -> Current connection pool statistics
    - record_pool_metrics() -> Emit pool metrics to monitoring backend
    - get_locked_entity() -> Helper for pessimistic row locking
    - get_circuit_breaker_metrics() -> Circuit breaker state and metrics

    **Circuit Breaker (P2.2)**:
    - Prevents cascading failures when database is unavailable
    - Automatically fails fast when failure threshold is reached
    - Tests for recovery and resumes normal operation when database recovers

    Thread Safety
    -------------
    All classmethods are safe for concurrent access. Initialization is
    protected by an async lock to ensure idempotent behavior.
    """

    _engine: Optional[AsyncEngine] = None
    _session_factory: Optional[async_sessionmaker[AsyncSession]] = None
    _config_snapshot: Optional[_DatabaseConfigSnapshot] = None
    _init_lock: asyncio.Lock = asyncio.Lock()
    _circuit_breaker: Optional[CircuitBreaker] = None

    # ========================================================================
    # Initialization & Shutdown
    # ========================================================================

    @classmethod
    def _build_config_snapshot(cls) -> _DatabaseConfigSnapshot:
        """
        Build an immutable configuration snapshot from Config.

        All values are sourced from Config to comply with LES config-driven
        architecture. Safe defaults are provided for all optional parameters.

        Raises
        ------
        DatabaseInitializationError
            If DATABASE_URL is missing or invalid.
        """
        database_url = getattr(Config, "DATABASE_URL", None)
        if not database_url or not isinstance(database_url, str):
            logger.error("DATABASE_URL is not configured or invalid")
            raise DatabaseInitializationError(
                "DATABASE_URL must be configured as a non-empty string"
            )

        # Determine environment context
        is_testing = bool(getattr(Config, "TESTING", False)) or (
            hasattr(Config, "is_testing") and Config.is_testing()
        )

        # Pool configuration
        pool_class: Type[Pool] = NullPool if is_testing else QueuePool
        pool_size = int(getattr(Config, "DATABASE_POOL_SIZE", 5))
        max_overflow = int(getattr(Config, "DATABASE_MAX_OVERFLOW", 10))
        pool_recycle = int(getattr(Config, "DATABASE_POOL_RECYCLE", 1800))
        pool_timeout = int(getattr(Config, "DATABASE_POOL_TIMEOUT", 30))
        statement_timeout_ms = int(
            getattr(Config, "DATABASE_STATEMENT_TIMEOUT_MS", 30_000)
        )
        echo = bool(getattr(Config, "DATABASE_ECHO", False))

        snapshot = _DatabaseConfigSnapshot(
            url=database_url,
            echo=echo,
            pool_class=pool_class,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_recycle=pool_recycle,
            pool_timeout=pool_timeout,
            statement_timeout_ms=statement_timeout_ms,
        )

        logger.debug(
            "Database configuration snapshot created",
            extra={
                "url_scheme": snapshot.url_scheme,
                "pool_class": pool_class.__name__,
                "pool_size": pool_size,
                "max_overflow": max_overflow,
                "pool_recycle": pool_recycle,
                "pool_timeout": pool_timeout,
                "statement_timeout_ms": statement_timeout_ms,
                "is_testing": is_testing,
            },
        )

        return snapshot

    @classmethod
    async def initialize(cls) -> None:
        """
        Initialize the database engine and session factory.

        This method is idempotent and safe to call multiple times. If already
        initialized, it returns immediately without re-creating the engine.

        Configuration is sourced entirely from Config with safe defaults.

        Raises
        ------
        DatabaseInitializationError
            If configuration is invalid or engine creation fails.
        """
        async with cls._init_lock:
            if cls._engine is not None:
                logger.debug("DatabaseService already initialized; skipping")
                return

            logger.info("Initializing DatabaseService")

            try:
                config = cls._build_config_snapshot()
                cls._config_snapshot = config

                # Build engine arguments
                engine_kwargs: dict[str, Any] = {
                    "echo": config.echo,
                    "poolclass": config.pool_class,
                }

                # Add pool-specific arguments only for QueuePool
                if config.pool_class == QueuePool:
                    engine_kwargs.update(
                        {
                            "pool_size": config.pool_size,
                            "max_overflow": config.max_overflow,
                            "pool_recycle": config.pool_recycle,
                            "pool_timeout": config.pool_timeout,
                        }
                    )

                cls._engine = create_async_engine(config.url, **engine_kwargs)
                cls._session_factory = async_sessionmaker(
                    bind=cls._engine,
                    class_=AsyncSession,
                    expire_on_commit=False,
                )

                # Initialize circuit breaker (P2.2)
                cls._circuit_breaker = CircuitBreaker()
                logger.debug("Circuit breaker initialized for DatabaseService")

                DatabaseMetrics.record_engine_initialized(
                    url_scheme=config.url_scheme,
                    pool_class=config.pool_class.__name__,
                    pool_size=config.pool_size,
                    max_overflow=config.max_overflow,
                )

                logger.info(
                    "DatabaseService initialized successfully",
                    extra={
                        "url_scheme": config.url_scheme,
                        "pool_class": config.pool_class.__name__,
                    },
                )

            except Exception as exc:
                config_error = isinstance(exc, DatabaseInitializationError)
                DatabaseMetrics.record_engine_initialization_failed(
                    config_error=config_error
                )
                logger.error(
                    "DatabaseService initialization failed",
                    extra={
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                        "config_error": config_error,
                    },
                    exc_info=True,
                )
                raise DatabaseInitializationError(
                    f"Database initialization failed: {exc}"
                ) from exc

    @classmethod
    async def shutdown(cls) -> None:
        """
        Shutdown the database engine and cleanup resources.

        Disposes the engine, closes all connections, and resets internal state.
        Safe to call multiple times; no-op if already shut down.
        """
        async with cls._init_lock:
            if cls._engine is None:
                logger.debug("DatabaseService not initialized; nothing to shutdown")
                return

            logger.info("Shutting down DatabaseService")

            try:
                await cls._engine.dispose()
                DatabaseMetrics.record_engine_shutdown()
                logger.info("DatabaseService shutdown complete")

            except Exception as exc:
                logger.error(
                    "Error during DatabaseService shutdown",
                    extra={
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                    },
                    exc_info=True,
                )
                raise

            finally:
                cls._engine = None
                cls._session_factory = None
                cls._config_snapshot = None
                cls._circuit_breaker = None

    # ========================================================================
    # Health Check
    # ========================================================================

    @classmethod
    async def health_check(cls) -> bool:
        """
        Perform a lightweight health check by executing a simple query.

        Returns
        -------
        bool
            True if the database is reachable and responsive, False otherwise.

        Notes
        -----
        - Does not raise exceptions on failure; returns False instead
        - Records timing and success/failure metrics
        - Suitable for Kubernetes liveness/readiness probes
        """
        if cls._engine is None:
            logger.warning("Health check called on uninitialized DatabaseService")
            DatabaseMetrics.record_health_check(success=False, duration_ms=0.0)
            return False

        start = time.perf_counter()
        success = False

        try:
            async with cls._engine.begin() as conn:
                await conn.execute(text("SELECT 1"))
            success = True
            return True

        except (OperationalError, DBAPIError) as exc:
            logger.warning(
                "Database health check failed",
                extra={
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
            )
            return False

        except Exception as exc:
            logger.error(
                "Unexpected error during database health check",
                extra={
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
            return False

        finally:
            duration_ms = (time.perf_counter() - start) * 1000.0
            DatabaseMetrics.record_health_check(
                success=success, duration_ms=duration_ms
            )
            logger.debug(
                "Database health check completed",
                extra={"success": success, "duration_ms": duration_ms},
            )

    # ========================================================================
    # Connection Pool Metrics
    # ========================================================================

    @classmethod
    def get_pool_metrics(cls) -> dict[str, int]:
        """
        Get current connection pool metrics.

        Returns
        -------
        dict[str, int]
            Dictionary containing:
            - pool_size: Configured pool size
            - checked_out: Connections currently in use
            - checked_in: Available connections
            - overflow: Overflow connections beyond pool_size
            - total_connections: Sum of checked_out, checked_in, and overflow

        Notes
        -----
        Returns a dict with all values set to 0 if the engine is not initialized
        or does not support pool metrics (e.g., NullPool in testing).
        """
        if cls._engine is None or cls._config_snapshot is None:
            logger.debug("Pool metrics requested but engine not initialized")
            return {
                "pool_size": 0,
                "checked_out": 0,
                "checked_in": 0,
                "overflow": 0,
                "total_connections": 0,
            }

        pool = cls._engine.pool
        config = cls._config_snapshot

        # NullPool doesn't track metrics
        if not hasattr(pool, "size") or config.pool_class == NullPool:
            return {
                "pool_size": 0,
                "checked_out": 0,
                "checked_in": 0,
                "overflow": 0,
                "total_connections": 0,
            }

        try:
            pool_size = getattr(pool, "size", 0)
            checked_out = getattr(pool, "checkedout", 0)
            overflow = getattr(pool, "overflow", 0)
            checked_in = max(0, pool_size - checked_out)
            total = checked_out + checked_in + overflow

            return {
                "pool_size": config.pool_size,
                "checked_out": checked_out,
                "checked_in": checked_in,
                "overflow": overflow,
                "total_connections": total,
            }

        except Exception as exc:
            logger.warning(
                "Error retrieving pool metrics",
                extra={
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
            )
            return {
                "pool_size": 0,
                "checked_out": 0,
                "checked_in": 0,
                "overflow": 0,
                "total_connections": 0,
            }

    @classmethod
    def record_pool_metrics(cls) -> None:
        """
        Record current pool metrics to the monitoring backend.

        Retrieves current pool metrics via get_pool_metrics() and emits them
        to DatabaseMetrics for observability.

        No-op if engine is not initialized or pool metrics are unavailable.
        """
        metrics = cls.get_pool_metrics()

        # Skip recording if no meaningful metrics available
        if metrics["total_connections"] == 0 and cls._config_snapshot is not None:
            if cls._config_snapshot.pool_class != NullPool:
                logger.debug("Pool metrics are zero; skipping recording")
            return

        DatabaseMetrics.record_pool_metrics(
            pool_size=metrics["pool_size"],
            checked_out=metrics["checked_out"],
            checked_in=metrics["checked_in"],
            overflow=metrics["overflow"],
            total_connections=metrics["total_connections"],
        )

        logger.debug(
            "Pool metrics recorded",
            extra={
                "pool_size": metrics["pool_size"],
                "checked_out": metrics["checked_out"],
                "checked_in": metrics["checked_in"],
                "overflow": metrics["overflow"],
                "total_connections": metrics["total_connections"],
            },
        )

    # ========================================================================
    # Session & Transaction Context Managers
    # ========================================================================

    @classmethod
    def _ensure_initialized(cls) -> None:
        """
        Ensure DatabaseService is initialized before session creation.

        Raises
        ------
        DatabaseNotInitializedError
            If engine or session factory is not initialized.
        """
        if cls._session_factory is None or cls._engine is None:
            logger.error("DatabaseService operation attempted before initialization")
            raise DatabaseNotInitializedError(
                "DatabaseService must be initialized before use. "
                "Call DatabaseService.initialize() during startup."
            )

    @classmethod
    def _get_config_snapshot(cls) -> _DatabaseConfigSnapshot:
        """
        Retrieve the configuration snapshot.

        Raises
        ------
        DatabaseNotInitializedError
            If config snapshot is not available.
        """
        if cls._config_snapshot is None:
            raise DatabaseNotInitializedError("DatabaseService is not initialized")
        return cls._config_snapshot

    @classmethod
    @asynccontextmanager
    async def get_session(cls) -> AsyncGenerator[AsyncSession, None]:
        """
        Create a database session without automatic commit.

        Use Cases
        ---------
        - Read-only operations
        - Manual transaction control (advanced cases only)

        Behavior
        --------
        - Session is automatically closed on exit
        - No automatic commit or rollback
        - PostgreSQL statement timeout is configured if applicable

        Yields
        ------
        AsyncSession
            An active database session.

        Raises
        ------
        DatabaseNotInitializedError
            If DatabaseService has not been initialized.

        Notes
        -----
        For write operations, prefer `get_transaction()` which provides
        automatic commit/rollback semantics.
        """
        cls._ensure_initialized()
        assert cls._session_factory is not None  # Type checker assertion

        start = time.perf_counter()
        async with cls._session_factory() as session:
            config = cls._get_config_snapshot()

            try:
                # Configure statement timeout for PostgreSQL
                if config.is_postgres:
                    await session.execute(
                        text(
                            f"SET LOCAL statement_timeout = "
                            f"{config.statement_timeout_ms}"
                        )
                    )

                logger.debug("Database session opened (read-only)")
                yield session

            finally:
                await session.close()
                duration_ms = (time.perf_counter() - start) * 1000.0
                logger.debug(
                    "Database session closed",
                    extra={"duration_ms": duration_ms},
                )

    @classmethod
    @asynccontextmanager
    async def get_transaction(cls) -> AsyncGenerator[AsyncSession, None]:
        """
        Create a database session wrapped in an atomic transaction.

        This is the **primary interface for all state mutations** in Lumen.

        Behavior
        --------
        **On Success**:
        - Automatically commits the transaction
        - Emits commit metrics and logs

        **On Exception**:
        - Automatically rolls back the transaction
        - Emits rollback metrics and logs with error context
        - Re-raises the original exception

        Yields
        ------
        AsyncSession
            An active database session inside a transaction.

        Raises
        ------
        DatabaseNotInitializedError
            If DatabaseService has not been initialized.
        OperationalError
            For database connection or operational issues.
        DBAPIError
            For database-level errors.
        Exception
            Any exception raised within the transaction context.

        Usage Example
        -------------
        >>> async with DatabaseService.get_transaction() as session:
        >>>     player = await session.get(Player, player_id, with_for_update=True)
        >>>     player.lumees += 1000
        >>>     # Automatic commit on exit

        Notes
        -----
        - Never manually call `session.commit()` or `session.rollback()`
        - Use `with_for_update=True` for pessimistic locking
        - Keep transactions short to avoid blocking other operations
        """
        cls._ensure_initialized()
        assert cls._session_factory is not None  # Type checker assertion
        assert cls._circuit_breaker is not None  # Type checker assertion

        # Circuit breaker check (P2.2)
        if not await cls._circuit_breaker.allow_request():
            logger.warning("Transaction rejected by circuit breaker (fail-fast)")
            raise CircuitBreakerOpenError(
                "Database circuit breaker is open. "
                "The database may be unavailable or experiencing issues."
            )

        start = time.perf_counter()
        async with cls._session_factory() as session:
            config = cls._get_config_snapshot()
            committed = False
            DatabaseMetrics.record_transaction_started()

            try:
                # Configure statement timeout for PostgreSQL
                if config.is_postgres:
                    await session.execute(
                        text(
                            f"SET LOCAL statement_timeout = "
                            f"{config.statement_timeout_ms}"
                        )
                    )

                logger.debug("Database transaction started")
                yield session

                # Commit on successful completion
                await session.commit()
                committed = True
                duration_ms = (time.perf_counter() - start) * 1000.0

                # Record success in circuit breaker (P2.2)
                await cls._circuit_breaker.record_success()

                DatabaseMetrics.record_transaction_committed(duration_ms=duration_ms)
                logger.debug(
                    "Database transaction committed",
                    extra={"duration_ms": duration_ms},
                )

            except OperationalError as exc:
                await session.rollback()
                duration_ms = (time.perf_counter() - start) * 1000.0

                # Record failure in circuit breaker (P2.2)
                await cls._circuit_breaker.record_failure()

                DatabaseMetrics.record_transaction_rolled_back(
                    duration_ms=duration_ms,
                    error_type=type(exc).__name__,
                )
                logger.error(
                    "OperationalError in transaction; rolled back",
                    extra={
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                        "committed": committed,
                        "duration_ms": duration_ms,
                    },
                    exc_info=True,
                )
                raise

            except DBAPIError as exc:
                await session.rollback()
                duration_ms = (time.perf_counter() - start) * 1000.0

                # Record failure in circuit breaker (P2.2)
                await cls._circuit_breaker.record_failure()

                DatabaseMetrics.record_transaction_rolled_back(
                    duration_ms=duration_ms,
                    error_type=type(exc).__name__,
                )
                logger.error(
                    "DBAPIError in transaction; rolled back",
                    extra={
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                        "committed": committed,
                        "duration_ms": duration_ms,
                    },
                    exc_info=True,
                )
                raise

            except Exception as exc:
                await session.rollback()
                duration_ms = (time.perf_counter() - start) * 1000.0

                # Record failure in circuit breaker (P2.2)
                await cls._circuit_breaker.record_failure()

                DatabaseMetrics.record_transaction_rolled_back(
                    duration_ms=duration_ms,
                    error_type=type(exc).__name__,
                )
                logger.error(
                    "Error in transaction; rolled back",
                    extra={
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                        "committed": committed,
                        "duration_ms": duration_ms,
                    },
                    exc_info=True,
                )
                raise

            finally:
                await session.close()
                logger.debug("Database transaction session closed")

    # ========================================================================
    # Pessimistic Locking Helper
    # ========================================================================

    @classmethod
    async def get_locked_entity(
        cls,
        session: AsyncSession,
        model: Type[T],
        primary_key: Any,
    ) -> Optional[T]:
        """
        Fetch an entity with a pessimistic row lock (SELECT FOR UPDATE).

        This is syntactic sugar over:
            await session.get(Model, pk, with_for_update=True)

        Parameters
        ----------
        session : AsyncSession
            Active session from get_transaction().
        model : Type[T]
            ORM model class.
        primary_key : Any
            Primary key value.

        Returns
        -------
        Optional[T]
            The locked entity instance, or None if not found.

        Usage Example
        -------------
        >>> async with DatabaseService.get_transaction() as session:
        >>>     player = await DatabaseService.get_locked_entity(
        >>>         session, Player, player_id
        >>>     )
        >>>     if player:
        >>>         player.lumees += 1000

        Notes
        -----
        - Must be used within a get_transaction() context
        - Locks the row until the transaction commits or rolls back
        - Other transactions attempting to lock the same row will block
        """
        return await session.get(model, primary_key, with_for_update=True)

    # ========================================================================
    # Circuit Breaker Metrics (P2.2)
    # ========================================================================

    @classmethod
    def get_circuit_breaker_metrics(cls) -> dict[str, Any]:
        """
        Get current circuit breaker state and metrics.

        Returns
        -------
        dict[str, Any]
            Dictionary containing:
            - state: Current circuit state (closed/open/half_open)
            - failure_count: Total failures since initialization
            - success_count: Total successes since initialization
            - consecutive_failures: Current consecutive failure streak
            - total_requests: Total requests processed
            - rejected_requests: Requests rejected by circuit breaker
            - last_failure_time: Timestamp of last failure (or None)
            - last_state_change_time: Timestamp of last state transition

        Notes
        -----
        Returns a dict with default values if circuit breaker is not initialized.
        Useful for health endpoints and monitoring dashboards.

        Usage Example
        -------------
        >>> metrics = DatabaseService.get_circuit_breaker_metrics()
        >>> if metrics["state"] == "open":
        >>>     logger.warning("Database circuit breaker is OPEN!")
        """
        if cls._circuit_breaker is None:
            return {
                "state": "not_initialized",
                "failure_count": 0,
                "success_count": 0,
                "consecutive_failures": 0,
                "total_requests": 0,
                "rejected_requests": 0,
                "last_failure_time": None,
                "last_state_change_time": None,
            }

        cb_metrics = cls._circuit_breaker.get_metrics()
        return {
            "state": cb_metrics.state.value,
            "failure_count": cb_metrics.failure_count,
            "success_count": cb_metrics.success_count,
            "consecutive_failures": cb_metrics.consecutive_failures,
            "total_requests": cb_metrics.total_requests,
            "rejected_requests": cb_metrics.rejected_requests,
            "last_failure_time": cb_metrics.last_failure_time,
            "last_state_change_time": cb_metrics.last_state_change_time,
            "half_open_test_count": cb_metrics.half_open_test_count,
        }